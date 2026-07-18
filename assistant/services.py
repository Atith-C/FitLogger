"""Joey assistant — RAG retrieval and chat.

Talks to OpenAI for embeddings and chat completion, retrieves relevant PDF
chunks by cosine similarity, and assembles the signed-in user's live data so
answers stay personal and current.
"""

import logging

import numpy as np
from django.conf import settings

from .models import JoeyMessage, KnowledgeChunk
from .prompts import GREETING, build_system_prompt

logger = logging.getLogger(__name__)

# How many PDF chunks to feed the model per question.
TOP_K = 5
# Cap how much conversation history we replay into the model. Fewer turns means
# less to send and shorter, snappier answers; six (three exchanges) keeps enough
# context to stay coherent.
MAX_HISTORY_MESSAGES = 6
MAX_MESSAGE_LENGTH = 1000

GENERIC_FAILURE = "Sorry — I hit a snag just now. Please try again in a moment."


class AssistantError(Exception):
    """Raised with a message safe to show the user."""


# One client, reused across requests. Building a fresh OpenAI() per call meant a
# new DNS lookup and TLS handshake every time — the bulk of the embedding call's
# latency. A cached client keeps the HTTP connection warm (keep-alive), so
# repeat calls skip the handshake entirely.
_client = None


def _get_client():
    global _client
    if not settings.OPENAI_API_KEY:
        raise AssistantError(
            "The assistant isn't configured yet. An API key needs to be added."
        )
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
        )
    return _client


# --------------------------------------------------------------------------
# Embeddings + retrieval
# --------------------------------------------------------------------------


def embed_text(text, client=None):
    """Embed a single string, returning a list of floats."""
    client = client or _get_client()
    response = client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


# Cached, L2-normalised embedding matrix. Rebuilding it from 700+ JSON rows on
# every question was the bulk of Joey's latency; now it is built once and reused.
_MATRIX_CACHE = {"key": None, "chunks": None, "normed": None}


def _knowledge_matrix():
    """The chunks and their normalised embedding matrix, cached in memory.

    Rebuilt only when the corpus changes — a re-ingest deletes and recreates
    every row, so (count, max id) is a cheap, reliable cache key. Between
    ingests every question reuses the same matrix and only does one dot product.
    """
    from django.db.models import Count, Max

    stats = KnowledgeChunk.objects.aggregate(n=Count("id"), last=Max("id"))
    key = (stats["n"], stats["last"])

    if key != _MATRIX_CACHE["key"]:
        chunks = list(KnowledgeChunk.objects.all())
        normed = None
        if chunks:
            matrix = np.array([c.embedding for c in chunks], dtype=float)
            normed = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
        _MATRIX_CACHE.update(key=key, chunks=chunks, normed=normed)

    return _MATRIX_CACHE["chunks"], _MATRIX_CACHE["normed"]


def retrieve_relevant_chunks(query_embedding, k=TOP_K):
    """The k most similar knowledge chunks to the query, by cosine similarity.

    Returns [] when nothing has been ingested yet, so Joey simply falls back to
    the user's data and general knowledge.
    """
    chunks, normed = _knowledge_matrix()
    if not chunks:
        return []

    query = np.array(query_embedding, dtype=float)
    query = query / (np.linalg.norm(query) + 1e-9)
    similarities = normed @ query

    top_indices = np.argsort(similarities)[::-1][:k]
    return [chunks[i] for i in top_indices]


# --------------------------------------------------------------------------
# Live user context (always current — read fresh each question)
# --------------------------------------------------------------------------


def build_user_context(user):
    """A plain-text snapshot of the user's own data, read live so it reflects
    the latest profile / plan / calories / progress."""
    # Imported here to avoid import cycles at app-load time.
    from ai_planner.services import get_active_plan
    from analytics.services import (
        build_calorie_targets,
        get_average_weekly_workouts,
        get_wellness_dashboard,
    )
    from users.services import get_calorie_calculation, get_or_create_profile

    lines = [f"- Username: {user.username}"]

    profile = get_or_create_profile(user)
    if profile.age:
        lines.append(f"- Age: {profile.age}")
    if profile.sex:
        lines.append(f"- Gender: {profile.get_sex_display()}")
    if profile.weight_kg:
        lines.append(f"- Bodyweight (profile): {profile.weight_kg} kg")
    if profile.height_cm:
        lines.append(f"- Height: {profile.height_cm} cm")
    lines.append(f"- Goal: {profile.get_goal_display()}")
    lines.append(f"- Experience: {profile.get_experience_level_display()}")
    lines.append(f"- Planned training days/week: {profile.days_per_week}")
    lines.append(f"- Trains at: {profile.get_workout_location_display()}")
    lines.append(f"- Typical session: {profile.session_duration} min")

    calc = get_calorie_calculation(user)
    if calc:
        lines.append(
            f"- Maintenance calories: {calc.maintenance_calories} kcal/day "
            f"(BMR {calc.bmr})"
        )
        targets = build_calorie_targets(calc.maintenance_calories, calc.sex)
        maintain = next((t for t in targets if t["key"] == "maintain"), None)
        loss = next((t for t in targets if t["key"] == "loss"), None)
        gain = next((t for t in targets if t["key"] == "gain"), None)
        if maintain and loss and gain:
            lines.append(
                f"- Calorie targets: maintain {maintain['calories']}, "
                f"lose {loss['calories']}, gain {gain['calories']} kcal/day"
            )
    else:
        lines.append("- Calories: not calculated yet (Calorie calculator page)")

    avg = get_average_weekly_workouts(user)
    lines.append(f"- Recent average workouts/week: {avg}")

    wellness = get_wellness_dashboard(user, height_cm=profile.height_cm)
    if wellness["has_data"] and wellness["latest"]:
        latest = wellness["latest"]
        lines.append(
            f"- Latest weigh-in: {latest['weight_kg']} kg on "
            f"{latest['recorded_on']:%d %b %Y}"
        )
        if wellness["bmi"]:
            lines.append(f"- BMI: {wellness['bmi']}")

    plan = get_active_plan(user)
    if plan:
        plan_name = plan.plan_json.get("plan_name", "workout plan")
        day_count = len(plan.plan_json.get("days", []))
        lines.append(f"- Active plan: “{plan_name}” ({day_count} days)")
    else:
        lines.append("- Active plan: none yet")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Conversation persistence
# --------------------------------------------------------------------------


def get_history(user):
    """The user's whole saved Joey conversation, oldest first, as plain dicts —
    what the widget renders when it opens."""
    return [
        {"role": m.role, "content": m.content}
        for m in JoeyMessage.objects.filter(user=user)
    ]


def _recent_turns(user):
    """The last few turns, for the model's context window. Capped to control
    tokens and cost, and read before the new message is saved."""
    recent = JoeyMessage.objects.filter(user=user).order_by("-created_at")[
        :MAX_HISTORY_MESSAGES
    ]
    return [{"role": m.role, "content": m.content} for m in reversed(recent)]


def clear_history(user):
    """Delete the user's Joey conversation (called on logout)."""
    JoeyMessage.objects.filter(user=user).delete()


def answer_question(user, message):
    """Joey's reply to one message from a signed-in user.

    Retrieves PDF context, injects the user's live data, applies the guardrails
    via the system prompt, and calls the chat model. The conversation is read
    from and written to the database, so it survives page navigation. Both turns
    are saved only after a successful reply, so a failure never leaves a dangling
    half-turn.
    """
    message = (message or "").strip()
    if not message:
        raise AssistantError("Please type a message.")
    message = message[:MAX_MESSAGE_LENGTH]

    client = _get_client()

    try:
        query_embedding = embed_text(message, client=client)
        chunks = retrieve_relevant_chunks(query_embedding)
    except AssistantError:
        raise
    except Exception:
        # Retrieval failing shouldn't kill the answer — fall back to no context.
        logger.exception("Joey retrieval failed; answering without PDF context")
        chunks = []

    knowledge = "\n\n".join(f"[{c.source}] {c.content}" for c in chunks)
    user_context = build_user_context(user)
    system_prompt = build_system_prompt(knowledge, user_context)

    messages = [{"role": "system", "content": system_prompt}]
    messages += _recent_turns(user)
    messages.append({"role": "user", "content": message})

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=500,
        )
        reply = response.choices[0].message.content.strip()
    except Exception:
        logger.exception("Joey chat completion failed")
        raise AssistantError(GENERIC_FAILURE)

    JoeyMessage.objects.create(user=user, role=JoeyMessage.Role.USER, content=message)
    JoeyMessage.objects.create(
        user=user, role=JoeyMessage.Role.ASSISTANT, content=reply
    )
    return reply


def greeting():
    return GREETING
