"""Forgotten username, forgotten password, or both.

One entry point: the user types the Gmail address they signed up with, and the
message that arrives names their username and carries a reset link underneath.
That covers someone who only forgot the username (they read it and log in with
the password they remember) and someone who forgot both.

The token, its expiry and its single use come from Django's own password-reset
machinery — this file only changes how an address finds an account, and adds a
note home once the password actually changes.
"""

from django.contrib.auth.forms import PasswordResetForm
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from .validators import normalize_gmail


class ForgotAccountForm(PasswordResetForm):
    """Password reset, but matching addresses the way Gmail does."""

    def get_users(self, email):
        """Accounts that should be sent recovery mail for this address.

        Django matches the address exactly. That would strand anyone who signed
        up as "a.dith+gym@gmail.com" and later types "adith@gmail.com" — the
        same inbox as far as Google is concerned, and the one holding the mail
        we are about to send.

        Inactive accounts are excluded, as in Django's version: a blocked or
        removed account must not be recoverable by its former owner. So are
        accounts with an unusable password, which have no password to reset.
        """
        from django.contrib.auth.models import User

        target = normalize_gmail(email)
        candidates = User.objects.filter(is_active=True)

        if target:
            candidates = candidates.filter(email__icontains="@g")
            matches = (u for u in candidates if normalize_gmail(u.email) == target)
        else:
            # Accounts predating the Gmail-only rule keep their address and
            # must stay recoverable.
            matches = candidates.filter(email__iexact=email.strip())

        return (user for user in matches if user.has_usable_password())


def send_password_changed_email(user):
    """Tell the user their password changed.

    If they did not do it, this is the only warning they get — so it is sent
    after the change rather than as part of the reset flow, and a failure to
    send must never undo a password the user has already set.
    """
    context = {"username": user.username}

    message = EmailMultiAlternatives(
        subject="Your Fit Logger password was changed",
        body=render_to_string("users/emails/password_changed.txt", context),
        to=[user.email],
    )
    message.attach_alternative(
        render_to_string("users/emails/password_changed.html", context), "text/html"
    )
    message.send()
