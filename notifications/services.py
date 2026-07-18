"""Notification business logic.

Other apps call these helpers (create_notification / notify_admins) from their
own service layer when something worth telling someone about happens.
"""

from django.contrib.auth.models import User

from users.models import Role

from .models import Category, Notification


def create_notification(recipient, title, message="", link="", actor=None,
                        category=Category.SYSTEM):
    """Create one notification for one recipient."""
    return Notification.objects.create(
        recipient=recipient,
        actor=actor,
        category=category,
        title=title,
        message=message,
        link=link,
    )


def notify_admins(title, message="", link="", actor=None, category=Category.SYSTEM):
    """Send a notification to every admin.

    Used for trainee-triggered events. Skips the actor themselves in the rare
    case an admin triggers an admin-facing event. Respects the platform
    notifications switch: when an admin has turned notifications off, no new
    admin notifications are created (the triggering action still succeeds).
    """
    from users.models import PlatformSettings

    if not PlatformSettings.load().notifications_enabled:
        return []

    admins = User.objects.filter(profile__role=Role.ADMIN)
    if actor is not None:
        admins = admins.exclude(pk=actor.pk)

    created = []
    for admin in admins:
        created.append(
            create_notification(
                admin, title, message=message, link=link, actor=actor,
                category=category,
            )
        )
    return created


def recent_notifications(user, limit=30):
    """The user's most recent notifications, newest first."""
    return user.notifications.select_related("actor")[:limit]


def unread_count(user):
    if not user.is_authenticated:
        return 0
    return user.notifications.filter(is_read=False).count()


def unread_badges(user, is_admin):
    """The two unread counts the nav badges show.

    One helper so the server-rendered badge and the live poll can never
    disagree. is_admin is passed in rather than looked up, since both callers
    already know it.
    """
    # Local import: messaging.services reaches back into this module.
    from messaging.services import admin_unread_count, trainee_unread_count

    return {
        "notifications": unread_count(user),
        "messages": admin_unread_count() if is_admin else trainee_unread_count(user),
    }


def mark_read(user, notification_id):
    """Mark one of the user's notifications read. Returns it, or None if it is
    not theirs (so a guessed id cannot touch another user's notification)."""
    notification = user.notifications.filter(pk=notification_id).first()
    if notification is not None and not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    return notification


def mark_all_read(user):
    return user.notifications.filter(is_read=False).update(is_read=True)
