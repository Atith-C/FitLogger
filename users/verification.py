"""Proving a signup owns the Gmail address it claimed.

The link carries a signed token rather than a database row. Nothing needs
storing, nothing needs expiring on a schedule, and there is no cleanup job to
run — which matters, because the application is serverless and has nowhere to
run one.
"""

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

# Changing the salt invalidates every link already in flight.
SALT = "users.email-verification"

# Long enough that a link found the next morning still works; short enough that
# an old message forwarded on, or left in a shared inbox, does not.
MAX_AGE_SECONDS = 24 * 60 * 60


def make_token(user):
    return signing.dumps(user.pk, salt=SALT)


def read_token(token):
    """The user this token names, or None if it is forged, expired or stale.

    Returns None rather than raising: to the caller every failure means the
    same thing — offer them a fresh link.
    """
    from django.contrib.auth.models import User

    try:
        user_id = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
    except signing.BadSignature:  # covers SignatureExpired
        return None

    return User.objects.filter(pk=user_id).first()


def send_verification_email(user):
    """Mail the user a fresh verification link.

    Raises if delivery fails. The caller must not report success to someone
    whose link was never sent — they would sit waiting for a message that is
    not coming.
    """
    context = {
        "username": user.username,
        "verify_url": settings.SITE_BASE_URL
        + reverse("users:verify_email", args=[make_token(user)]),
        "expiry_hours": MAX_AGE_SECONDS // 3600,
    }

    message = EmailMultiAlternatives(
        subject="Confirm your Fit Logger account",
        body=render_to_string("users/emails/verify_email.txt", context),
        to=[user.email],
    )
    message.attach_alternative(
        render_to_string("users/emails/verify_email.html", context), "text/html"
    )
    message.send()


def mark_verified(profile):
    """Record that the mailbox was opened, and tell the admins a real trainee
    has arrived.

    The admin notification waits until here rather than firing at signup, so
    abandoned and automated signups never reach the portal.
    """
    if profile.email_verified:
        return False  # already done; a link followed twice is not a new trainee

    profile.email_verified = True
    profile.save(update_fields=["email_verified"])

    from notifications.models import Category
    from notifications.services import notify_admins

    from .services import admin_trainee_link, trainee_display

    notify_admins(
        "New Trainee Registered",
        message=f"{trainee_display(profile.user)} just created an account.",
        link=admin_trainee_link(profile.user),
        actor=profile.user,
        category=Category.NEW_TRAINEE,
    )
    return True
