"""Email verification: signup is inert until the mailbox is opened."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import Role, UserProfile

VALID_PASSWORD = "str0ng-pass-2026"


def register(client, username="alice", email="alice@gmail.com"):
    return client.post(
        reverse("users:register"),
        {
            "username": username,
            "email": email,
            "password1": VALID_PASSWORD,
            "password2": VALID_PASSWORD,
        },
    )


def link_from_last_email():
    return [word for word in mail.outbox[-1].body.split() if "/verify/" in word][0]


class EmailVerificationTests(TestCase):
    def test_signup_does_not_log_the_user_in(self):
        """The whole point: an unopened mailbox must not grant a session."""
        response = register(self.client)

        self.assertRedirects(response, reverse("users:verify_sent"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_signup_leaves_the_account_unverified(self):
        register(self.client)
        self.assertFalse(UserProfile.objects.get(user__username="alice").email_verified)

    def test_signup_sends_one_email_to_the_address_given(self):
        register(self.client)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["alice@gmail.com"])
        self.assertIn("/verify/", mail.outbox[0].body)

    def test_the_emailed_link_verifies_and_logs_in(self):
        register(self.client)
        response = self.client.get(link_from_last_email())

        self.assertRedirects(response, reverse("users:profile"))
        self.assertTrue(UserProfile.objects.get(user__username="alice").email_verified)

    def test_a_forged_token_is_refused(self):
        register(self.client)
        response = self.client.get(reverse("users:verify_email", args=["not-a-real-token"]))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserProfile.objects.get(user__username="alice").email_verified)

    def test_an_expired_token_is_refused(self):
        from .verification import MAX_AGE_SECONDS, make_token

        register(self.client)
        user = User.objects.get(username="alice")

        # signing compares the token against the clock, so age the token
        # rather than the test.
        with patch("django.core.signing.time.time", return_value=0):
            token = make_token(user)
        with patch("django.core.signing.time.time", return_value=MAX_AGE_SECONDS + 1):
            response = self.client.get(reverse("users:verify_email", args=[token]))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserProfile.objects.get(user__username="alice").email_verified)

    def test_a_link_for_a_blocked_account_does_not_let_them_in(self):
        """An admin decision must outlive a link sitting in an inbox."""
        from .services import set_trainee_blocked

        register(self.client)
        link = link_from_last_email()
        set_trainee_blocked(User.objects.get(username="alice"), True)

        response = self.client.get(link)

        self.assertRedirects(response, reverse("users:login"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_following_the_link_twice_is_harmless(self):
        register(self.client)
        link = link_from_last_email()

        self.client.get(link)
        self.client.logout()
        response = self.client.get(link)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(UserProfile.objects.get(user__username="alice").email_verified)


class UnverifiedLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="alice", email="alice@gmail.com", password=VALID_PASSWORD
        )
        self.profile = UserProfile.objects.create(user=self.user, email_verified=False)

    def _login(self, password=VALID_PASSWORD):
        return self.client.post(
            reverse("users:login"), {"username": "alice", "password": password}
        )

    def test_an_unverified_account_cannot_log_in(self):
        response = self._login()

        self.assertRedirects(response, reverse("users:verify_sent"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_verifying_then_logging_in_works(self):
        self.profile.email_verified = True
        self.profile.save()

        self.assertRedirects(self._login(), reverse("workouts:home"))

    def test_a_wrong_password_is_still_just_a_wrong_password(self):
        """Verification state must not leak: someone guessing passwords cannot
        be shown a different outcome for an account that exists."""
        response = self._login(password="wrong-password-2026")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class ResendVerificationTests(TestCase):
    def test_resend_sends_another_link(self):
        register(self.client)
        self.client.post(reverse("users:resend_verification"))

        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("/verify/", mail.outbox[1].body)

    def test_resend_without_a_pending_signup_sends_nothing(self):
        """Otherwise the endpoint would mail anyone on demand."""
        response = self.client.post(reverse("users:resend_verification"))

        self.assertEqual(len(mail.outbox), 0)
        self.assertRedirects(response, reverse("users:login"))

    def test_resend_stops_once_the_account_is_verified(self):
        register(self.client)
        profile = UserProfile.objects.get(user__username="alice")
        profile.email_verified = True
        profile.save()

        self.client.post(reverse("users:resend_verification"))

        self.assertEqual(len(mail.outbox), 1)  # only the original


class VerificationNotifiesAdminsTests(TestCase):
    """Admins hear about a trainee when one actually arrives, not when a form
    is submitted."""

    def setUp(self):
        admin = User.objects.create_user(username="coach", password=VALID_PASSWORD)
        UserProfile.objects.create(user=admin, role=Role.ADMIN, email_verified=True)

    def _notifications(self):
        from notifications.models import Notification

        return Notification.objects.filter(title="New Trainee Registered")

    def test_signup_alone_does_not_notify_admins(self):
        register(self.client)
        self.assertEqual(self._notifications().count(), 0)

    def test_verifying_notifies_admins_exactly_once(self):
        register(self.client)
        link = link_from_last_email()

        self.client.get(link)
        self.client.logout()
        self.client.get(link)  # a second click must not announce them twice

        self.assertEqual(self._notifications().count(), 1)
