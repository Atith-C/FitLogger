import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from users.decorators import admin_required, trainee_required

from .models import Conversation
from .services import (
    admin_conversations,
    can_access,
    get_or_create_conversation,
    grouped_by_date,
    mark_read,
    messages_after,
    send_message,
)


def _message_json(message, viewer):
    return {
        "id": message.id,
        "body": message.body,
        "is_mine": message.sender_id == viewer.id,
        "sender": (message.sender.get_full_name() or message.sender.username)
        if message.sender
        else "Deleted user",
        "time": timezone.localtime(message.created_at).strftime("%H:%M"),
    }


def _render_conversation(request, conversation, back_url=None):
    mark_read(conversation, request.user)
    last = conversation.messages.last()
    return render(
        request,
        "messaging/conversation.html",
        {
            "conversation": conversation,
            "blocks": grouped_by_date(conversation),
            "last_message_id": last.id if last else 0,
            "back_url": back_url,
        },
    )


@login_required
@trainee_required
def inbox(request):
    """The trainee's Connect-with-Admin conversation."""
    conversation = get_or_create_conversation(request.user)
    return _render_conversation(request, conversation)


@admin_required
def admin_messages(request):
    """Admin list of all trainee conversations."""
    return render(
        request,
        "messaging/admin_list.html",
        {"rows": admin_conversations()},
    )


@admin_required
def admin_conversation(request, conversation_id):
    """Admin view of one trainee's conversation."""
    from django.urls import reverse

    conversation = get_object_or_404(Conversation, pk=conversation_id)
    return _render_conversation(
        request, conversation, back_url=reverse("adminportal:messages")
    )


@login_required
@require_POST
def send(request, conversation_id):
    """Post a message to a conversation (AJAX). Trainee owner or admin only."""
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    if not can_access(request.user, conversation):
        raise PermissionDenied

    # Platform messaging switch. When an admin has turned messaging off, a
    # trainee cannot reach them; the admin can still reply, so the gate is on
    # the trainee direction only.
    from users.models import PlatformSettings

    if request.user.profile.is_trainee and not PlatformSettings.load().messaging_enabled:
        return JsonResponse(
            {"error": "You can't message the admin right now."}, status=403
        )

    try:
        body = json.loads(request.body.decode("utf-8")).get("body", "")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    message = send_message(conversation, request.user, body)
    if message is None:
        return JsonResponse({"error": "Empty message."}, status=400)

    return JsonResponse({"message": _message_json(message, request.user)})


@login_required
def poll(request, conversation_id):
    """Return messages newer than ?after= (AJAX). Marks the thread read."""
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    if not can_access(request.user, conversation):
        raise PermissionDenied

    try:
        after_id = int(request.GET.get("after", 0))
    except ValueError:
        after_id = 0

    new_messages = list(messages_after(conversation, after_id))
    mark_read(conversation, request.user)

    return JsonResponse(
        {"messages": [_message_json(m, request.user) for m in new_messages]}
    )
