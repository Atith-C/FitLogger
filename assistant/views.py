import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from users.decorators import trainee_required

from .services import AssistantError, answer_question, get_history

logger = logging.getLogger(__name__)


@login_required
@trainee_required
@require_POST
def chat(request):
    """Joey chat endpoint.

    Accepts JSON {message}, returns {reply}. The conversation is stored
    server-side and scoped to request.user, so the client no longer sends
    history and the user's data context is always their own.

    trainee_required, not just login_required: base.html hides the widget from
    admins, and a permission that exists only in a template is not a permission
    — the endpoint has to refuse them itself.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    try:
        reply = answer_question(request.user, payload.get("message", ""))
    except AssistantError as exc:
        # exc carries a user-safe message.
        return JsonResponse({"error": str(exc)}, status=200)

    return JsonResponse({"reply": reply})


@login_required
@trainee_required
def history(request):
    """The user's saved Joey conversation, so the widget restores it on open."""
    return JsonResponse({"messages": get_history(request.user)})
