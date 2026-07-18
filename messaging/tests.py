import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from notifications.models import Category, Notification
from users.models import Role, UserProfile

from .models import Conversation, Message
from .services import (
    admin_unread_count,
    can_access,
    get_or_create_conversation,
    grouped_by_date,
    send_message,
    trainee_unread_count,
)

PASSWORD = "str0ng-pass-2026"


def make_admin(username="admin1"):
    u = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=u, role=Role.ADMIN)
    return u


def make_trainee(username="trainee1"):
    u = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=u, role=Role.TRAINEE)
    return u


class ConversationServiceTests(TestCase):
    def setUp(self):
        self.trainee = make_trainee("tina")
        self.admin = make_admin("adam")
        self.other = make_trainee("olive")

    def test_one_conversation_per_trainee(self):
        c1 = get_or_create_conversation(self.trainee)
        c2 = get_or_create_conversation(self.trainee)
        self.assertEqual(c1.id, c2.id)

    def test_access_rules(self):
        conv = get_or_create_conversation(self.trainee)
        self.assertTrue(can_access(self.trainee, conv))   # owner
        self.assertTrue(can_access(self.admin, conv))     # any admin
        self.assertFalse(can_access(self.other, conv))    # another trainee

    def test_send_message_updates_conversation(self):
        conv = get_or_create_conversation(self.trainee)
        msg = send_message(conv, self.trainee, "Hello coach")

        conv.refresh_from_db()
        self.assertEqual(msg.body, "Hello coach")
        self.assertIsNotNone(conv.last_message_at)

    def test_trainee_message_notifies_admins(self):
        conv = get_or_create_conversation(self.trainee)
        send_message(conv, self.trainee, "Need help with squats")

        note = Notification.objects.filter(recipient=self.admin, category=Category.MESSAGE).first()
        self.assertIsNotNone(note)
        self.assertIn("tina", note.title)

    def test_admin_reply_notifies_the_trainee(self):
        conv = get_or_create_conversation(self.trainee)
        send_message(conv, self.admin, "Sure, here's how")

        note = Notification.objects.filter(recipient=self.trainee, category=Category.MESSAGE).first()
        self.assertIsNotNone(note)
        self.assertEqual(note.link, reverse("messaging:inbox"))

    def test_empty_message_is_ignored(self):
        conv = get_or_create_conversation(self.trainee)
        self.assertIsNone(send_message(conv, self.trainee, "   "))
        self.assertEqual(conv.messages.count(), 0)


class UnreadTests(TestCase):
    def setUp(self):
        self.trainee = make_trainee("tina")
        self.admin = make_admin("adam")
        self.conv = get_or_create_conversation(self.trainee)

    def test_trainee_unread_counts_admin_messages(self):
        send_message(self.conv, self.admin, "Reply 1")
        send_message(self.conv, self.admin, "Reply 2")
        self.assertEqual(trainee_unread_count(self.trainee), 2)

    def test_admin_unread_counts_trainee_messages(self):
        send_message(self.conv, self.trainee, "Hi")
        self.assertEqual(admin_unread_count(), 1)

    def test_sending_marks_your_own_side_read(self):
        # The trainee's own message is not unread for the trainee.
        send_message(self.conv, self.trainee, "Hi")
        self.assertEqual(trainee_unread_count(self.trainee), 0)


class DateGroupingTests(TestCase):
    def setUp(self):
        self.trainee = make_trainee("tina")
        self.admin = make_admin("adam")
        self.conv = get_or_create_conversation(self.trainee)

    def test_a_today_block_is_always_present(self):
        blocks = grouped_by_date(self.conv)  # no messages yet
        self.assertTrue(any(b["is_today"] for b in blocks))
        self.assertEqual(blocks[-1]["label"], "Today")

    def test_today_messages_land_in_the_today_block(self):
        send_message(self.conv, self.trainee, "Hello")
        blocks = grouped_by_date(self.conv)
        today = [b for b in blocks if b["is_today"]][0]
        self.assertEqual(len(today["messages"]), 1)

    def test_older_messages_form_a_dated_block(self):
        m = send_message(self.conv, self.trainee, "Old")
        Message.objects.filter(pk=m.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=3)
        )
        labels = [b["label"] for b in grouped_by_date(self.conv)]
        self.assertIn("Today", labels)
        self.assertTrue(any(lbl not in ("Today", "Yesterday") for lbl in labels))


class MessagingViewTests(TestCase):
    def setUp(self):
        self.trainee = make_trainee("tina")
        self.other = make_trainee("olive")
        self.admin = make_admin("adam")

    def test_inbox_is_trainee_only(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("messaging:inbox")).status_code, 403)

    def test_inbox_creates_and_shows_the_conversation(self):
        self.client.force_login(self.trainee)
        response = self.client.get(reverse("messaging:inbox"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Conversation.objects.filter(trainee=self.trainee).exists())

    def test_admin_message_list_is_admin_only(self):
        self.client.force_login(self.trainee)
        self.assertEqual(self.client.get(reverse("adminportal:messages")).status_code, 403)

    def test_admin_can_open_a_trainee_conversation(self):
        conv = get_or_create_conversation(self.trainee)
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("adminportal:conversation", args=[conv.id])).status_code,
            200,
        )

    def test_trainee_can_send_to_their_own_conversation(self):
        conv = get_or_create_conversation(self.trainee)
        self.client.force_login(self.trainee)
        response = self.client.post(
            reverse("messaging:send", args=[conv.id]),
            data=json.dumps({"body": "Hello"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"]["body"], "Hello")

    def test_a_trainee_cannot_send_to_another_trainees_conversation(self):
        conv = get_or_create_conversation(self.trainee)
        self.client.force_login(self.other)
        response = self.client.post(
            reverse("messaging:send", args=[conv.id]),
            data=json.dumps({"body": "sneaky"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(conv.messages.count(), 0)

    def test_poll_returns_only_new_messages(self):
        conv = get_or_create_conversation(self.trainee)
        m1 = send_message(conv, self.trainee, "one")
        m2 = send_message(conv, self.admin, "two")

        self.client.force_login(self.trainee)
        response = self.client.get(
            reverse("messaging:poll", args=[conv.id]) + f"?after={m1.id}"
        )
        bodies = [m["body"] for m in response.json()["messages"]]
        self.assertEqual(bodies, ["two"])

    def test_opening_marks_read(self):
        conv = get_or_create_conversation(self.trainee)
        send_message(conv, self.admin, "unread reply")
        self.assertEqual(trainee_unread_count(self.trainee), 1)

        self.client.force_login(self.trainee)
        self.client.get(reverse("messaging:inbox"))
        self.assertEqual(trainee_unread_count(self.trainee), 0)

    def test_send_requires_login(self):
        conv = get_or_create_conversation(self.trainee)
        response = self.client.post(
            reverse("messaging:send", args=[conv.id]),
            data=json.dumps({"body": "hi"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 302)
