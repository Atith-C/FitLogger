import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from users.models import Goal, Sex, UserProfile

from .management.commands.ingest_pdf import _chunk_page
from .models import KnowledgeChunk
from .prompts import MEDICAL_REFUSAL, OFF_TOPIC_REFUSAL, build_system_prompt
from .services import (
    AssistantError,
    answer_question,
    build_user_context,
    retrieve_relevant_chunks,
)

PASSWORD = "str0ng-pass-2026"


def _fake_client(reply="Here is your answer.", embedding=None):
    """A stand-in OpenAI client: embeddings + chat both return canned data."""
    client = MagicMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=embedding or [0.1, 0.2, 0.3])]
    )
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=reply))]
    )
    return client


class RetrievalTests(TestCase):
    def setUp(self):
        # Simple 3-dim embeddings so cosine similarity is easy to reason about.
        KnowledgeChunk.objects.create(content="about squats", embedding=[1.0, 0.0, 0.0], chunk_index=0)
        KnowledgeChunk.objects.create(content="about protein", embedding=[0.0, 1.0, 0.0], chunk_index=1)
        KnowledgeChunk.objects.create(content="about sleep", embedding=[0.0, 0.0, 1.0], chunk_index=2)

    def test_retrieves_the_closest_chunk_first(self):
        results = retrieve_relevant_chunks([0.9, 0.1, 0.0], k=1)
        self.assertEqual(results[0].content, "about squats")

    def test_returns_k_results_ranked(self):
        results = retrieve_relevant_chunks([0.0, 0.9, 0.2], k=2)
        self.assertEqual(results[0].content, "about protein")
        self.assertEqual(len(results), 2)

    def test_empty_knowledge_base_returns_nothing(self):
        KnowledgeChunk.objects.all().delete()
        self.assertEqual(retrieve_relevant_chunks([1.0, 0.0, 0.0]), [])


class UserContextTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        UserProfile.objects.create(
            user=self.alice, age=25, sex=Sex.MALE, weight_kg="70.0",
            height_cm=178, goal=Goal.BUILD_MUSCLE, days_per_week=4,
        )

    def test_context_includes_the_users_own_data(self):
        context = build_user_context(self.alice)
        self.assertIn("alice", context)
        self.assertIn("Build muscle", context)
        self.assertIn("70.0 kg", context)
        self.assertIn("4", context)  # planned days

    def test_context_notes_when_calories_are_not_set(self):
        context = build_user_context(self.alice)
        self.assertIn("not calculated yet", context)


class SystemPromptTests(TestCase):
    def test_prompt_carries_guardrails_and_context(self):
        prompt = build_system_prompt("SOME PDF TEXT", "USER DATA HERE")

        self.assertIn(OFF_TOPIC_REFUSAL, prompt)
        self.assertIn(MEDICAL_REFUSAL, prompt)
        self.assertIn("SOME PDF TEXT", prompt)
        self.assertIn("USER DATA HERE", prompt)
        self.assertIn("NOT about fitness", prompt)


@override_settings(OPENAI_API_KEY="test-key")
class AnswerQuestionTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        UserProfile.objects.create(user=self.alice, goal=Goal.LOSE_WEIGHT)

    def test_answer_flows_through_retrieval_and_chat(self):
        with patch("assistant.services._get_client", return_value=_fake_client("Do 3 sets.")):
            reply = answer_question(self.alice, "How many sets should I do?")
        self.assertEqual(reply, "Do 3 sets.")

    def test_an_empty_message_is_rejected(self):
        with self.assertRaises(AssistantError):
            answer_question(self.alice, "   ")

    def test_retrieval_failure_still_answers(self):
        client = _fake_client("Answer without context.")
        client.embeddings.create.side_effect = RuntimeError("embeddings down")
        with patch("assistant.services._get_client", return_value=client):
            reply = answer_question(self.alice, "protein?")
        self.assertEqual(reply, "Answer without context.")

    def test_chat_failure_becomes_a_friendly_error(self):
        client = _fake_client()
        client.chat.completions.create.side_effect = RuntimeError("api down")
        with patch("assistant.services._get_client", return_value=client):
            with self.assertRaises(AssistantError):
                answer_question(self.alice, "hello")


@override_settings(OPENAI_API_KEY="test-key")
class ChatEndpointTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        UserProfile.objects.create(user=self.alice)
        self.url = reverse("assistant:chat")

    def _post(self, message="hi"):
        return self.client.post(
            self.url,
            data=json.dumps({"message": message}),
            content_type="application/json",
        )

    def test_requires_login(self):
        self.assertEqual(self._post().status_code, 302)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_returns_a_reply(self):
        self.client.force_login(self.alice)
        with patch("assistant.views.answer_question", return_value="Joey says hi."):
            response = self._post("hello")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Joey says hi.")

    def test_a_safe_error_is_returned_as_json(self):
        self.client.force_login(self.alice)
        with patch("assistant.views.answer_question", side_effect=AssistantError("nope")):
            response = self._post("hello")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "nope")

    def test_bad_json_is_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.url, data="not json", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_the_endpoint_uses_the_logged_in_user(self):
        """Joey's context must be built for request.user, not anyone else."""
        self.client.force_login(self.alice)
        captured = {}

        def fake_answer(user, message):
            captured["user"] = user
            return "ok"

        with patch("assistant.views.answer_question", side_effect=fake_answer):
            self._post("hi")

        self.assertEqual(captured["user"], self.alice)


class ChunkingTests(TestCase):
    def test_page_is_split_into_overlapping_chunks(self):
        text = " ".join(f"word{i}" for i in range(500))
        chunks = list(_chunk_page(text, page_number=7))

        self.assertGreater(len(chunks), 1)
        # Every chunk is tagged with its page.
        self.assertTrue(all(source == "page 7" for _, source in chunks))
        # Consecutive chunks overlap (the last words of one appear in the next).
        first_words = chunks[0][0].split()
        second_words = chunks[1][0].split()
        self.assertTrue(set(first_words) & set(second_words))

    def test_blank_page_yields_no_chunks(self):
        self.assertEqual(list(_chunk_page("   ", page_number=1)), [])


# --------------------------------------------------------------------------
# Ingest robustness — real PDFs are messier than the happy path
# --------------------------------------------------------------------------

from io import StringIO  # noqa: E402

from django.core.management import call_command  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402

from .management.commands.ingest_pdf import _clean  # noqa: E402


class NulByteTests(TestCase):
    """PostgreSQL text columns cannot hold 0x00, and real PDFs contain it."""

    def test_clean_strips_nul_bytes(self):
        self.assertEqual(_clean("squat\x00 depth"), "squat depth")

    def test_clean_leaves_ordinary_text_alone(self):
        text = "Progressive overload — 3×8 @ 40kg, 60% 1RM.\nNext week: +2.5kg"
        self.assertEqual(_clean(text), text)

    def test_a_nul_byte_page_ingests_instead_of_crashing(self):
        # The 600-page ingest died on page 496 for exactly this reason: one bad
        # byte took down an otherwise healthy book after ~8 minutes of embedding.
        #
        # Patch pypdf itself rather than _extract_pages — cleaning happens
        # inside _extract_pages, so stubbing that out would test nothing and
        # pass whether or not the fix exists.
        raw = "Chest press\x00 technique: keep the elbows tucked."
        reader = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: raw)])

        with patch("pypdf.PdfReader", return_value=reader), patch(
            "assistant.management.commands.ingest_pdf.embed_text",
            return_value=[0.1] * 8,
        ):
            call_command("ingest_pdf", "book.pdf", stdout=StringIO())

        chunk = KnowledgeChunk.objects.get()
        self.assertNotIn("\x00", chunk.content)
        self.assertIn("Chest press technique", chunk.content)


class IngestAtomicityTests(TestCase):
    """A failed re-ingest must not destroy the knowledge base it was replacing."""

    def setUp(self):
        KnowledgeChunk.objects.create(
            content="The existing book.", embedding=[0.5] * 8,
            source="page 1", chunk_index=0,
        )

    def test_an_embedding_failure_leaves_the_old_corpus_intact(self):
        with patch(
            "assistant.management.commands.ingest_pdf._extract_pages",
            return_value=[(1, "A brand new book about squats.")],
        ), patch(
            "assistant.management.commands.ingest_pdf.embed_text",
            side_effect=RuntimeError("rate limited"),
        ):
            with self.assertRaises(CommandError):
                call_command("ingest_pdf", "book.pdf", stdout=StringIO())

        # Embeddings are fetched before anything is written, so a mid-run
        # failure cannot leave Joey with half a book.
        chunk = KnowledgeChunk.objects.get()
        self.assertEqual(chunk.content, "The existing book.")

    def test_a_successful_ingest_replaces_the_previous_corpus(self):
        with patch(
            "assistant.management.commands.ingest_pdf._extract_pages",
            return_value=[(1, "A brand new book about squats.")],
        ), patch(
            "assistant.management.commands.ingest_pdf.embed_text",
            return_value=[0.2] * 8,
        ):
            call_command("ingest_pdf", "book.pdf", stdout=StringIO())

        chunk = KnowledgeChunk.objects.get()  # exactly one — the old one is gone
        self.assertIn("squats", chunk.content)

    def test_chunks_are_numbered_and_page_tagged(self):
        with patch(
            "assistant.management.commands.ingest_pdf._extract_pages",
            return_value=[(7, " ".join(["word"] * 500))],
        ), patch(
            "assistant.management.commands.ingest_pdf.embed_text",
            return_value=[0.2] * 8,
        ):
            call_command("ingest_pdf", "book.pdf", stdout=StringIO())

        chunks = list(KnowledgeChunk.objects.order_by("chunk_index"))
        self.assertGreater(len(chunks), 1)  # 500 words > one 220-word chunk
        self.assertEqual([c.chunk_index for c in chunks], list(range(len(chunks))))
        for chunk in chunks:
            self.assertEqual(chunk.source, "page 7")


class NoTextPdfTests(TestCase):
    def test_a_scanned_pdf_is_refused_with_a_useful_message(self):
        with patch(
            "assistant.management.commands.ingest_pdf._extract_pages",
            return_value=[],
        ):
            with self.assertRaises(CommandError) as caught:
                call_command("ingest_pdf", "scan.pdf", stdout=StringIO())
        self.assertIn("OCR", str(caught.exception))


# --------------------------------------------------------------------------
# Conversation persistence, history endpoint, logout clearing, matrix cache
# --------------------------------------------------------------------------

from django.contrib.auth.signals import user_logged_out  # noqa: E402

from users.models import Role  # noqa: E402

from .models import JoeyMessage  # noqa: E402
from .services import clear_history, get_history  # noqa: E402


def _make_trainee(username="pat"):
    user = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=user, role=Role.TRAINEE)
    return user


@override_settings(OPENAI_API_KEY="test-key")
class PersistenceTests(TestCase):
    def setUp(self):
        self.alice = _make_trainee("alice")

    def test_a_turn_saves_both_the_question_and_the_reply(self):
        with patch("assistant.services._get_client", return_value=_fake_client("Do 3 sets.")):
            answer_question(self.alice, "How many sets?")

        saved = list(JoeyMessage.objects.filter(user=self.alice))
        self.assertEqual([m.role for m in saved], ["user", "assistant"])
        self.assertEqual(saved[0].content, "How many sets?")
        self.assertEqual(saved[1].content, "Do 3 sets.")

    def test_history_is_carried_into_the_next_turn(self):
        client = _fake_client("Second reply.")
        with patch("assistant.services._get_client", return_value=client):
            answer_question(self.alice, "first")
            answer_question(self.alice, "second")

        # The second call must have sent the prior turns as context: the first
        # question and its reply are both in the messages list.
        sent = client.chat.completions.create.call_args_list[-1].kwargs["messages"]
        contents = [m["content"] for m in sent]
        self.assertIn("first", contents)          # the earlier question
        self.assertIn("Second reply.", contents)  # the earlier reply
        self.assertIn("second", contents)         # the new question

    def test_a_failed_reply_saves_nothing(self):
        client = _fake_client()
        client.chat.completions.create.side_effect = RuntimeError("api down")
        with patch("assistant.services._get_client", return_value=client):
            with self.assertRaises(AssistantError):
                answer_question(self.alice, "hello")
        self.assertEqual(JoeyMessage.objects.filter(user=self.alice).count(), 0)

    def test_the_conversation_is_scoped_to_the_user(self):
        bob = _make_trainee("bob")
        with patch("assistant.services._get_client", return_value=_fake_client()):
            answer_question(self.alice, "alice's question")
        self.assertEqual(get_history(bob), [])
        self.assertEqual(len(get_history(self.alice)), 2)


class HistoryEndpointTests(TestCase):
    def setUp(self):
        self.alice = _make_trainee("alice")
        self.url = reverse("assistant:history")

    def test_requires_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_admins_are_refused(self):
        admin = User.objects.create_user(username="admin1", password=PASSWORD)
        UserProfile.objects.create(user=admin, role=Role.ADMIN)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_it_returns_the_saved_conversation(self):
        JoeyMessage.objects.create(user=self.alice, role="user", content="hi there")
        JoeyMessage.objects.create(user=self.alice, role="assistant", content="hello!")

        self.client.force_login(self.alice)
        data = self.client.get(self.url).json()
        self.assertEqual(
            data["messages"],
            [{"role": "user", "content": "hi there"},
             {"role": "assistant", "content": "hello!"}],
        )

    def test_it_returns_only_the_callers_messages(self):
        bob = _make_trainee("bob")
        JoeyMessage.objects.create(user=bob, role="user", content="bob's secret")

        self.client.force_login(self.alice)
        body = self.client.get(self.url).content.decode()
        self.assertNotIn("bob's secret", body)


class LogoutClearsChatTests(TestCase):
    def setUp(self):
        self.alice = _make_trainee("alice")

    def test_clear_history_deletes_only_that_users_chat(self):
        bob = _make_trainee("bob")
        JoeyMessage.objects.create(user=self.alice, role="user", content="a")
        JoeyMessage.objects.create(user=bob, role="user", content="b")

        clear_history(self.alice)
        self.assertEqual(JoeyMessage.objects.filter(user=self.alice).count(), 0)
        self.assertEqual(JoeyMessage.objects.filter(user=bob).count(), 1)

    def test_logging_out_wipes_the_conversation(self):
        JoeyMessage.objects.create(user=self.alice, role="user", content="remember me")
        self.assertTrue(JoeyMessage.objects.filter(user=self.alice).exists())

        # The signal receiver is connected in AssistantConfig.ready().
        user_logged_out.send(sender=self.__class__, request=None, user=self.alice)
        self.assertFalse(JoeyMessage.objects.filter(user=self.alice).exists())

    def test_a_real_logout_clears_it_end_to_end(self):
        JoeyMessage.objects.create(user=self.alice, role="user", content="hi")
        self.client.force_login(self.alice)
        self.client.post(reverse("users:logout"))
        self.assertEqual(JoeyMessage.objects.filter(user=self.alice).count(), 0)


class MatrixCacheTests(TestCase):
    def test_retrieval_reflects_a_changed_corpus(self):
        # The cache key is (count, max id); adding a chunk must invalidate it.
        KnowledgeChunk.objects.create(content="squats", embedding=[1.0, 0.0, 0.0], chunk_index=0)
        first = retrieve_relevant_chunks([1.0, 0.0, 0.0], k=3)
        self.assertEqual(len(first), 1)

        KnowledgeChunk.objects.create(content="deadlift", embedding=[0.9, 0.1, 0.0], chunk_index=1)
        second = retrieve_relevant_chunks([1.0, 0.0, 0.0], k=3)
        self.assertEqual(len(second), 2)  # the new chunk is now considered
