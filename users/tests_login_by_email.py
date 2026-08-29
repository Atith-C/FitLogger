"""Logging in with the Gmail address instead of the username."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Role, UserProfile
from .services import username_for_login

VALID_PASSWORD = "str0ng-pass-2026"


def trainee(username, email, password=VALID_PASSWORD):
    user = User.objects.create_user(username=username, email=email, password=password)
    UserProfile.objects.create(user=user, role=Role.TRAINEE, email_verified=True)
    return user


class ResolveLoginNameTests(TestCase):
    def setUp(self):
        trainee("alice", "a.dith+gym@gmail.com")

    def test_a_username_passes_straight_through(self):
        self.assertEqual(username_for_login("alice"), "alice")

    def test_an_address_resolves_to_its_username(self):
        self.assertEqual(username_for_login("a.dith+gym@gmail.com"), "alice")

    def test_any_spelling_of_the_same_mailbox_resolves(self):
        """Gmail treats these as one inbox, so the login box has to as well."""
        for variant in ["adith@gmail.com", "ADITH@GMAIL.COM", "a.d.i.t.h@googlemail.com"]:
            with self.subTest(variant=variant):
                self.assertEqual(username_for_login(variant), "alice")

    def test_an_unknown_address_is_returned_unchanged(self):
        """It must fail at authenticate() like any wrong username, rather than
        telling the visitor whether the account exists."""
        self.assertEqual(username_for_login("nobody@gmail.com"), "nobody@gmail.com")

    def test_a_legacy_non_gmail_address_still_resolves(self):
        trainee("oldtimer", "old@example.com")
        self.assertEqual(username_for_login("old@example.com"), "oldtimer")

    def test_an_ambiguous_address_resolves_to_nothing(self):
        """User.email was never unique, so historic rows can share one. Guessing
        which account was meant would sign someone into the wrong one."""
        trainee("twin1", "twin@gmail.com")
        trainee("twin2", "tw.in@gmail.com")

        self.assertEqual(username_for_login("twin@gmail.com"), "twin@gmail.com")


class LoginWithEmailTests(TestCase):
    def setUp(self):
        trainee("alice", "alice@gmail.com")

    def _login(self, who, password=VALID_PASSWORD):
        return self.client.post(
            reverse("users:login"), {"username": who, "password": password}
        )

    def test_logging_in_with_the_address_works(self):
        self.assertRedirects(self._login("alice@gmail.com"), reverse("workouts:home"))

    def test_logging_in_with_the_username_still_works(self):
        self.assertRedirects(self._login("alice"), reverse("workouts:home"))

    def test_a_dotted_variant_of_the_address_works(self):
        self.assertRedirects(self._login("a.l.i.c.e@gmail.com"), reverse("workouts:home"))

    def test_the_wrong_password_is_still_refused(self):
        response = self._login("alice@gmail.com", password="wrong-password-2026")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_a_blocked_account_is_told_so_when_it_logs_in_by_address(self):
        """refused_login_reason() has to be given the resolved username, or a
        blocked user signing in by address gets the generic wrong-password
        message instead of the real reason."""
        from .services import set_trainee_blocked

        set_trainee_blocked(User.objects.get(username="alice"), True)

        response = self._login("alice@gmail.com")

        self.assertContains(response, "blocked")
