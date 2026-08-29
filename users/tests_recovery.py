"""Forgotten username, forgotten password, or both."""

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import Role, UserProfile

VALID_PASSWORD = "str0ng-pass-2026"
NEW_PASSWORD = "even-str0nger-2026"


def trainee(username="alice", email="alice@gmail.com", verified=True):
    user = User.objects.create_user(username=username, email=email, password=VALID_PASSWORD)
    UserProfile.objects.create(user=user, role=Role.TRAINEE, email_verified=verified)
    return user


def ask_for_help(client, email):
    return client.post(reverse("users:password_reset"), {"email": email})


def reset_link():
    """The set-a-new-password URL out of the last email."""
    words = mail.outbox[-1].body.split()
    return [w for w in words if "/forgot/set/" in w][0]


class RecoveryEmailTests(TestCase):
    def setUp(self):
        self.user = trainee()

    def test_the_email_names_the_username(self):
        """The whole point for someone who only forgot their username."""
        ask_for_help(self.client, "alice@gmail.com")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("alice", mail.outbox[0].body)

    def test_the_email_also_carries_a_reset_link(self):
        ask_for_help(self.client, "alice@gmail.com")
        self.assertIn("/forgot/set/", mail.outbox[0].body)

    def test_the_email_never_contains_a_password(self):
        ask_for_help(self.client, "alice@gmail.com")

        body = mail.outbox[0].body + str(mail.outbox[0].alternatives)
        self.assertNotIn(VALID_PASSWORD, body)

    def test_any_spelling_of_the_mailbox_finds_the_account(self):
        """Someone who signed up with a tag will not remember typing it."""
        User.objects.filter(username="alice").update(email="a.lice+gym@googlemail.com")

        ask_for_help(self.client, "alice@gmail.com")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["a.lice+gym@googlemail.com"])

    def test_a_legacy_non_gmail_account_is_still_recoverable(self):
        trainee("oldtimer", "old@example.com")
        ask_for_help(self.client, "old@example.com")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["old@example.com"])


class RecoveryDoesNotLeakTests(TestCase):
    """The form must not become a way of checking who is registered."""

    def setUp(self):
        trainee()

    def test_an_unknown_address_gets_the_same_page(self):
        known = ask_for_help(self.client, "alice@gmail.com")
        unknown = ask_for_help(self.client, "nobody@gmail.com")

        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)

    def test_an_unknown_address_is_mailed_nothing(self):
        ask_for_help(self.client, "nobody@gmail.com")
        self.assertEqual(len(mail.outbox), 0)

    def test_a_blocked_account_cannot_be_recovered(self):
        """Recovery must not hand back an account an admin shut off."""
        from .services import set_trainee_blocked

        set_trainee_blocked(User.objects.get(username="alice"), True)
        ask_for_help(self.client, "alice@gmail.com")

        self.assertEqual(len(mail.outbox), 0)


class SetNewPasswordTests(TestCase):
    def setUp(self):
        self.user = trainee()
        ask_for_help(self.client, "alice@gmail.com")
        self.link = reset_link()

    def _set_password(self, password=NEW_PASSWORD):
        # The link redirects to a URL carrying the token in the session; the
        # form is posted to wherever that lands.
        form_url = self.client.get(self.link, follow=True).redirect_chain[-1][0]
        return self.client.post(
            form_url, {"new_password1": password, "new_password2": password}
        )

    def test_the_password_actually_changes(self):
        self._set_password()
        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.check_password(VALID_PASSWORD))

    def test_the_user_can_log_in_with_the_new_password(self):
        self._set_password()

        response = self.client.post(
            reverse("users:login"), {"username": "alice", "password": NEW_PASSWORD}
        )
        self.assertRedirects(response, reverse("workouts:home"))

    def test_a_weak_password_is_refused(self):
        self._set_password(password="123")
        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password(VALID_PASSWORD))

    def test_the_link_works_only_once(self):
        self._set_password()
        mail.outbox.clear()

        response = self.client.get(self.link)

        # Django's confirm view renders the "link is invalid" page rather than
        # erroring, so the check is that the page refuses, not its status.
        self.assertContains(response, "Send me a new one")

    def test_a_confirmation_email_is_sent(self):
        mail.outbox.clear()
        self._set_password()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("password was changed", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["alice@gmail.com"])

    def test_the_confirmation_email_carries_no_password(self):
        mail.outbox.clear()
        self._set_password()

        body = mail.outbox[0].body + str(mail.outbox[0].alternatives)
        self.assertNotIn(NEW_PASSWORD, body)


class ResettingProvesTheMailboxTests(TestCase):
    """Completing a reset is the same proof signup verification asks for."""

    def test_an_unverified_account_becomes_verified(self):
        user = trainee(verified=False)
        ask_for_help(self.client, "alice@gmail.com")

        link = reset_link()
        form_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        self.client.post(
            form_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        )

        self.assertTrue(UserProfile.objects.get(user=user).email_verified)

    def test_and_can_then_log_in(self):
        trainee(verified=False)
        ask_for_help(self.client, "alice@gmail.com")

        link = reset_link()
        form_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        self.client.post(
            form_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        )

        response = self.client.post(
            reverse("users:login"), {"username": "alice", "password": NEW_PASSWORD}
        )
        self.assertRedirects(response, reverse("workouts:home"))


class RecoveryLinkOnLoginPageTests(TestCase):
    def test_the_login_page_offers_recovery(self):
        """Someone who cannot log in has to be able to find this."""
        response = self.client.get(reverse("users:login"))
        self.assertContains(response, reverse("users:password_reset"))
