from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Notification
from .services import mark_all_read, mark_read, recent_notifications, unread_badges


@login_required
def notification_list(request):
    """The signed-in user's notifications (their own only)."""
    return render(
        request,
        "notifications/list.html",
        {"notifications": recent_notifications(request.user)},
    )


@login_required
def open_notification(request, notification_id):
    """Mark a notification read, then redirect to whatever it points at.

    Scoped to request.user via get_object_or_404, so a guessed id 404s rather
    than opening someone else's notification.
    """
    notification = get_object_or_404(
        Notification, pk=notification_id, recipient=request.user
    )
    mark_read(request.user, notification.id)
    return redirect(notification.link or "notifications:list")


@login_required
@require_POST
def read_all(request):
    mark_all_read(request.user)
    return redirect("notifications:list")


@login_required
def poll(request):
    """Unread counts for the nav badges (AJAX).

    Lets an admin see a trainee's change land without refreshing. Counts only —
    no titles or links, so this cheap, frequently-hit endpoint cannot leak the
    content of anyone's notifications.
    """
    from users.services import get_or_create_profile

    is_admin = get_or_create_profile(request.user).is_admin
    return JsonResponse(unread_badges(request.user, is_admin))
