"""Messaging business logic.

A conversation is one trainee's thread with the admin(s). Views stay thin and
call these functions; access is always checked server-side.
"""

from collections import OrderedDict
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from users.models import Role

from .models import Conversation, Message

MAX_MESSAGE_LENGTH = 2000


def get_or_create_conversation(trainee):
    """The trainee's single conversation, created on first use."""
    conversation, _ = Conversation.objects.get_or_create(trainee=trainee)
    return conversation


def can_access(user, conversation):
    """The trainee owner, or any admin, may access a conversation."""
    if not user.is_authenticated:
        return False
    if conversation.trainee_id == user.id:
        return True
    return user.profile.role == Role.ADMIN


def _is_admin(user):
    return user.is_authenticated and user.profile.role == Role.ADMIN


@transaction.atomic
def send_message(conversation, sender, body):
    """Create a message and notify the other side.

    A trainee's message notifies the admins; an admin's reply notifies the
    trainee. The link points each recipient at their own view of the thread.
    """
    body = (body or "").strip()[:MAX_MESSAGE_LENGTH]
    if not body:
        return None

    now = timezone.now()
    message = Message.objects.create(conversation=conversation, sender=sender, body=body)
    conversation.last_message_at = now
    # The sender has, by definition, read up to their own message.
    if _is_admin(sender):
        conversation.admin_last_read_at = now
    else:
        conversation.trainee_last_read_at = now
    conversation.save(
        update_fields=["last_message_at", "admin_last_read_at", "trainee_last_read_at"]
    )

    _notify(conversation, sender)
    return message


def _notify(conversation, sender):
    from notifications.models import Category
    from notifications.services import create_notification, notify_admins

    name = sender.get_full_name() or sender.username if sender else "Someone"

    if _is_admin(sender):
        # Admin replied → tell the trainee.
        create_notification(
            conversation.trainee,
            "New reply from your coach",
            message=f"{name} replied to your message.",
            link=reverse("messaging:inbox"),
            actor=sender,
            category=Category.MESSAGE,
        )
    else:
        # Trainee messaged → tell the admins.
        notify_admins(
            f"New message from {name}",
            message="Open the conversation to reply.",
            link=reverse("adminportal:conversation", args=[conversation.id]),
            actor=sender,
            category=Category.MESSAGE,
        )


def mark_read(conversation, user):
    """Record that this user has read the thread up to now."""
    now = timezone.now()
    if _is_admin(user):
        conversation.admin_last_read_at = now
        conversation.save(update_fields=["admin_last_read_at"])
    elif conversation.trainee_id == user.id:
        conversation.trainee_last_read_at = now
        conversation.save(update_fields=["trainee_last_read_at"])


def messages_after(conversation, after_id):
    """Messages newer than a given id (for polling)."""
    return conversation.messages.select_related("sender").filter(id__gt=after_id)


def grouped_by_date(conversation):
    """Messages grouped into dated blocks, oldest first.

    Labels are Today / Yesterday / '17 July 2026'. A Today block is always
    present (possibly empty) so newly sent messages have somewhere to append.
    """
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    groups = OrderedDict()
    for message in conversation.messages.select_related("sender"):
        day = timezone.localtime(message.created_at).date()
        groups.setdefault(day, []).append(message)

    if today not in groups:
        groups[today] = []

    blocks = []
    for day in sorted(groups):
        if day == today:
            label = "Today"
        elif day == yesterday:
            label = "Yesterday"
        else:
            label = f"{day.day} {day:%B %Y}"
        blocks.append(
            {"date": day, "label": label, "is_today": day == today, "messages": groups[day]}
        )
    return blocks


# --------------------------------------------------------------------------
# Unread helpers (badges)
# --------------------------------------------------------------------------


def trainee_unread_count(user):
    """Unread messages for a trainee (admin replies they haven't seen)."""
    conversation = Conversation.objects.filter(trainee=user).first()
    if conversation is None:
        return 0
    qs = conversation.messages.exclude(sender=user)
    if conversation.trainee_last_read_at:
        qs = qs.filter(created_at__gt=conversation.trainee_last_read_at)
    return qs.count()


def admin_unread_count():
    """Total unread trainee messages across all conversations (admin badge)."""
    total = 0
    for conversation in Conversation.objects.all():
        qs = conversation.messages.filter(sender=conversation.trainee)
        if conversation.admin_last_read_at:
            qs = qs.filter(created_at__gt=conversation.admin_last_read_at)
        total += qs.count()
    return total


def conversation_unread_for_admin(conversation):
    qs = conversation.messages.filter(sender=conversation.trainee)
    if conversation.admin_last_read_at:
        qs = qs.filter(created_at__gt=conversation.admin_last_read_at)
    return qs.count()


def admin_conversations():
    """All conversations for the admin list, most recent activity first, each
    annotated with its unread count and latest message."""
    conversations = (
        Conversation.objects.select_related("trainee")
        .prefetch_related("messages")
        .all()
    )
    rows = []
    for conversation in conversations:
        latest = conversation.messages.last()
        rows.append(
            {
                "conversation": conversation,
                "latest": latest,
                "unread": conversation_unread_for_admin(conversation),
            }
        )
    return rows
