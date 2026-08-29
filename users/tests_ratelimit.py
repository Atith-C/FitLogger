"""Caps on the endpoints that send mail to an address the submitter chose."""

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import Role, UserProfile
from .ratelimit import over_limit
from .views import (
    RESENDS_PER_ACCOUNT_PER_HOUR,
    RESETS_PER_ADDRESS_PER_HOUR,
    SIGNUPS_PER_IP_PER_HOUR,
)

VALID_PASSWORD = "str0ng-pass-2026"


class OverLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_it_allows_exactly_the_limit_then_refuses(self):
        allowed = [not over_limit("k", 3) for _ in range(3)]

        self.assertEqual(allowed, [True, True, True])
        self.assertTrue(over_limit("k", 3))

    def test_separate_keys_are_counted_separately(self):
        for _ in range(4):
            over_limit("one", 3)

        self.assertFalse(over_limit("two", 3))

    def test_the_count_expires(self):
        over_limit("k", 1, window=1)
        self.assertTrue(over_limit("k", 1, window=1))

        cache.delete("k")  # stands in for the window elapsing
        self.assertFalse(over_limit("k", 1, window=1))


class SignupRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def _register(self, n):
        return self.client.post(
            reverse("users:register"),
            {
                "username": f"user{n}",
                "email": f"user{n}@gmail.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )

    def test_signups_from_one_address_are_capped(self):
        for n in range(SIGNUPS_PER_IP_PER_HOUR):
            self._register(n)
            self.client.logout()

        response = self._register(99)

        self.assertEqual(response.status_code, 429)
        self.assertFalse(User.objects.filter(username="user99").exists())

    def test_a_rejected_form_does_not_count_against_the_cap(self):
        """Someone fumbling the password rules must not be locked out for
        trying."""
        for _ in range(SIGNUPS_PER_IP_PER_HOUR + 3):
            self.client.post(
                reverse("users:register"),
                {
                    "username": "alice",
                    "email": "alice@gmail.com",
                    "password1": "123",
                    "password2": "123",
                },
            )

        response = self._register(1)

        self.assertEqual(response.status_code, 302)  # accepted
        self.assertTrue(User.objects.filter(username="user1").exists())


class ResendRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.post(
            reverse("users:register"),
            {
                "username": "alice",
                "email": "alice@gmail.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        mail.outbox.clear()

    def test_resends_are_capped_per_account(self):
        for _ in range(RESENDS_PER_ACCOUNT_PER_HOUR):
            self.client.post(reverse("users:resend_verification"))

        self.client.post(reverse("users:resend_verification"))

        self.assertEqual(len(mail.outbox), RESENDS_PER_ACCOUNT_PER_HOUR)


class ResetRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        user = User.objects.create_user(
            username="alice", email="alice@gmail.com", password=VALID_PASSWORD
        )
        UserProfile.objects.create(user=user, role=Role.TRAINEE, email_verified=True)

    def _ask(self, email="alice@gmail.com"):
        return self.client.post(reverse("users:password_reset"), {"email": email})

    def test_requests_for_one_address_are_capped(self):
        for _ in range(RESETS_PER_ADDRESS_PER_HOUR):
            self._ask()

        self._ask()

        self.assertEqual(len(mail.outbox), RESETS_PER_ADDRESS_PER_HOUR)

    def test_the_cap_follows_the_mailbox_not_the_spelling(self):
        """Otherwise the cap is bypassed by adding a dot."""
        for spelling in ["alice@gmail.com", "a.lice@gmail.com", "alice+1@gmail.com"]:
            self.client.post(reverse("users:password_reset"), {"email": spelling})

        self.client.post(reverse("users:password_reset"), {"email": "a.l.i.c.e@gmail.com"})

        self.assertEqual(len(mail.outbox), RESETS_PER_ADDRESS_PER_HOUR)

    def test_a_limited_request_looks_exactly_like_an_ordinary_one(self):
        """Saying "too many requests for that address" would confirm the
        address is registered — the one thing this form must not reveal."""
        first = self._ask()
        for _ in range(RESETS_PER_ADDRESS_PER_HOUR + 2):
            self._ask()
        limited = self._ask()

        self.assertEqual(first.status_code, limited.status_code)
        self.assertEqual(first.url, limited.url)
