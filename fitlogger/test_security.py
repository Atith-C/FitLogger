"""Phase N — security.

Most of these are sweeps rather than one-off checks. An audit only proves that
today is safe; a sweep walks the live URLconf, so the next view added without a
decorator fails here instead of shipping.
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from users.models import Role, UserProfile

PASSWORD = "str0ng-pass-2026"

# Routes that are public on purpose. Anything not listed here must refuse an
# anonymous visitor — that is the point of the sweep, so keep this list short
# and justify every entry.
PUBLIC_ROUTES = {
    "workouts:landing",   # marketing page
    "workouts:healthz",   # liveness probe; returns {"status": "ok"} and nothing else
    "users:login",
    "users:register",
    "users:logout",       # POST-only; logging out an anonymous user is harmless
}

# Django's own admin. Not part of this app's RBAC — it has its own staff gate,
# and it redirects rather than 403s, so it is swept separately below.
SKIPPED_NAMESPACES = {"admin"}


def make_admin(username="sweep_admin"):
    user = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=user, role=Role.ADMIN)
    return user


def make_trainee(username="sweep_trainee"):
    user = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=user, role=Role.TRAINEE)
    return user


def iter_routes(resolver=None, namespace=None):
    """Every named route in the URLconf, as (route_name, pattern)."""
    resolver = resolver or get_resolver()
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            child = pattern.namespace or namespace
            if child in SKIPPED_NAMESPACES:
                continue
            yield from iter_routes(pattern, child)
        elif isinstance(pattern, URLPattern) and pattern.name:
            name = f"{namespace}:{pattern.name}" if namespace else pattern.name
            yield name, pattern


def build_url(name, pattern, **ids):
    """reverse() the route, filling any int argument with a plausible id."""
    keys = list(pattern.pattern.regex.groupindex)
    if not keys:
        return reverse(name)
    return reverse(name, kwargs={key: ids.get(key, 1) for key in keys})


class AnonymousAccessSweepTests(TestCase):
    """Every route refuses an anonymous visitor, unless it is on the allowlist."""

    def test_no_route_serves_an_anonymous_visitor(self):
        client = Client()
        for name, pattern in iter_routes():
            if name in PUBLIC_ROUTES:
                continue
            with self.subTest(route=name):
                url = build_url(name, pattern)
                for method in ("get", "post"):
                    response = getattr(client, method)(url)
                    # Redirect to login, 403, 404 or 405 are all refusals.
                    # A 200 would mean the page rendered for a stranger.
                    self.assertNotEqual(
                        response.status_code, 200,
                        f"{method.upper()} {url} ({name}) served an anonymous visitor",
                    )

    def test_the_public_routes_really_are_public(self):
        # Guards the allowlist itself: if one of these starts 404ing, the
        # allowlist is stale and the sweep above is weaker than it looks.
        client = Client()
        for name in ["workouts:landing", "workouts:healthz", "users:login",
                     "users:register"]:
            with self.subTest(route=name):
                self.assertEqual(client.get(reverse(name)).status_code, 200)

    def test_the_sweep_actually_covers_the_app(self):
        # A sweep that silently enumerated nothing would pass forever.
        names = [name for name, _ in iter_routes()]
        self.assertGreater(len(names), 25)
        for expected in ["adminportal:dashboard", "workouts:home",
                         "assistant:chat", "notifications:poll"]:
            self.assertIn(expected, names)


class AdminRouteSweepTests(TestCase):
    """Every admin route refuses a signed-in trainee."""

    def setUp(self):
        self.trainee = make_trainee()
        self.client.force_login(self.trainee)

    def test_no_admin_route_serves_a_trainee(self):
        for name, pattern in iter_routes():
            if not name.startswith("adminportal:"):
                continue
            with self.subTest(route=name):
                url = build_url(name, pattern)
                for method in ("get", "post"):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(
                        response.status_code, 403,
                        f"{method.upper()} {url} ({name}) did not 403 for a trainee",
                    )

    def test_the_admin_sweep_covers_every_portal_route(self):
        portal = [n for n, _ in iter_routes() if n.startswith("adminportal:")]
        self.assertGreaterEqual(len(portal), 9)

    def test_a_trainee_cannot_reach_djangos_own_admin(self):
        response = self.client.get("/admin/")
        self.assertNotEqual(response.status_code, 200)


class TraineeRouteTests(TestCase):
    """Trainee-only areas refuse an admin."""

    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin)

    def test_trainee_only_routes_refuse_an_admin(self):
        for name in ["messaging:inbox", "users:toggle_profile_sharing"]:
            with self.subTest(route=name):
                response = self.client.post(reverse(name))
                self.assertEqual(response.status_code, 403)

    def test_joey_refuses_an_admin(self):
        # base.html hides the widget from admins; that is decoration. The
        # endpoint has to refuse them itself.
        response = self.client.post(
            reverse("assistant:chat"),
            data='{"message": "hi"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_joey_serves_a_trainee(self):
        self.client.force_login(make_trainee("joey_user"))
        response = self.client.post(
            reverse("assistant:chat"),
            data='{"message": ""}',
            content_type="application/json",
        )
        self.assertNotEqual(response.status_code, 403)


class RoleIsServerSideTests(TestCase):
    """The client never gets a say in what role it has."""

    def test_registration_always_creates_a_trainee(self):
        self.client.post(
            reverse("users:register"),
            {"username": "sneaky", "email": "s@example.com",
             "password1": PASSWORD, "password2": PASSWORD},
        )
        user = User.objects.get(username="sneaky")
        self.assertEqual(user.profile.role, Role.TRAINEE)

    def test_posting_a_role_at_registration_is_ignored(self):
        # The form has no role field; prove that submitting one anyway does
        # nothing rather than trusting that it is absent.
        self.client.post(
            reverse("users:register"),
            {"username": "climber", "email": "c@example.com",
             "password1": PASSWORD, "password2": PASSWORD,
             "role": Role.ADMIN, "is_staff": "on", "is_superuser": "on"},
        )
        user = User.objects.get(username="climber")
        self.assertEqual(user.profile.role, Role.TRAINEE)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_choosing_the_admin_door_does_not_grant_admin(self):
        make_trainee("tina")
        response = self.client.post(
            reverse("users:login"),
            {"username": "tina", "password": PASSWORD, "as_role": "admin"},
            follow=True,
        )
        # Right password, wrong door: refused, and still not an admin.
        self.assertEqual(User.objects.get(username="tina").profile.role, Role.TRAINEE)
        self.assertNotIn("/portal/", response.request["PATH_INFO"])

    def test_a_trainee_cannot_promote_themselves_via_the_profile_form(self):
        trainee = make_trainee("tina")
        self.client.force_login(trainee)
        self.client.post(
            reverse("users:profile"),
            {"age": 25, "sex": "MALE", "weight_kg": "70.0", "height_cm": 175,
             "goal": "STAY_FIT", "days_per_week": 3, "experience_level": "BEGINNER",
             "workout_location": "HOME", "session_duration": 60,
             "role": Role.ADMIN, "profile_shared": "on", "deleted_at": ""},
        )
        trainee.refresh_from_db()
        self.assertEqual(trainee.profile.role, Role.TRAINEE)


class CsrfProtectionTests(TestCase):
    """State-changing POSTs need a CSRF token."""

    def setUp(self):
        # enforce_csrf_checks: the normal test client bypasses CSRF entirely,
        # so without this these tests would pass no matter what.
        self.client = Client(enforce_csrf_checks=True)
        self.trainee = make_trainee("tina")

    def test_a_post_without_a_token_is_rejected(self):
        self.client.force_login(self.trainee)
        response = self.client.post(reverse("users:toggle_profile_sharing"), {"share": "on"})
        self.assertEqual(response.status_code, 403)

    def test_login_without_a_token_is_rejected(self):
        response = self.client.post(
            reverse("users:login"), {"username": "tina", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 403)

    def test_an_admin_action_without_a_token_is_rejected(self):
        admin = make_admin()
        self.client.force_login(admin)
        response = self.client.post(
            reverse("adminportal:delete_trainee", args=[self.trainee.id])
        )
        self.assertEqual(response.status_code, 403)
        # And the trainee is untouched.
        self.trainee.refresh_from_db()
        self.assertFalse(self.trainee.profile.is_deleted)

    def test_no_view_in_the_project_is_csrf_exempt(self):
        for name, pattern in iter_routes():
            with self.subTest(route=name):
                callback = pattern.callback
                self.assertFalse(
                    getattr(callback, "csrf_exempt", False),
                    f"{name} is csrf_exempt",
                )


class PasswordStorageTests(TestCase):
    def test_a_registered_password_is_hashed(self):
        self.client.post(
            reverse("users:register"),
            {"username": "hashme", "email": "h@example.com",
             "password1": PASSWORD, "password2": PASSWORD},
        )
        user = User.objects.get(username="hashme")

        self.assertNotEqual(user.password, PASSWORD)
        self.assertNotIn(PASSWORD, user.password)
        self.assertTrue(user.password.startswith("pbkdf2_"))
        self.assertTrue(user.check_password(PASSWORD))

    def test_no_raw_password_reaches_the_database(self):
        make_trainee("tina")
        stored = User.objects.values_list("password", flat=True)
        for value in stored:
            self.assertNotIn(PASSWORD, value)

    def test_seed_admin_hashes_its_password(self):
        import os
        from io import StringIO

        from django.core.management import call_command

        os.environ["ADMIN_PASSWORD"] = "seed-pass-2026"
        try:
            call_command("seed_admin", stdout=StringIO())
        finally:
            os.environ.pop("ADMIN_PASSWORD", None)

        admin = User.objects.get(profile__role=Role.ADMIN)
        self.assertNotIn("seed-pass-2026", admin.password)
        self.assertTrue(admin.check_password("seed-pass-2026"))


class OwnershipTests(TestCase):
    """A guessed id must never reach another user's data."""

    def setUp(self):
        self.alice = make_trainee("alice")
        self.bob = make_trainee("bob")

    def test_a_guessed_session_id_is_refused(self):
        from django.utils import timezone

        from workouts.models import WorkoutSession

        session = WorkoutSession.objects.create(
            user=self.alice, name="Alice's workout", started_at=timezone.now()
        )
        self.client.force_login(self.bob)

        # Bob guesses Alice's session id in the URL.
        response = self.client.get(
            reverse("workouts:active_workout", args=[session.id])
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertNotContains(
            response, "Alice's workout", status_code=response.status_code
        )

        # The POST paths are scoped too, not just the page.
        for name in ["finish_workout", "save_note"]:
            with self.subTest(route=name):
                response = self.client.post(
                    reverse(f"workouts:{name}", args=[session.id])
                )
                self.assertIn(response.status_code, (403, 404))

        # log_set needs a valid payload to reach the ownership check at all —
        # an empty POST is turned away by form validation first, which would
        # make this pass for the wrong reason.
        from workouts.models import Exercise, MuscleGroup, WorkoutSet

        exercise = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        response = self.client.post(
            reverse("workouts:log_set", args=[session.id]),
            {"exercise_id": exercise.id, "weight": "40.0", "reps": 10},
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertEqual(WorkoutSet.objects.filter(session=session).count(), 0)

        # delete_workout answers 302 rather than 403: it scopes the delete to
        # request.user, finds nothing, and says "could not be found". That
        # leaks less than a 403, which would confirm the session exists.
        response = self.client.post(reverse("workouts:delete_workout", args=[session.id]))
        self.assertEqual(response.status_code, 302)

        # What actually matters — Alice's workout is untouched by all of it.
        session.refresh_from_db()
        self.assertFalse(session.is_completed)
        self.assertEqual(session.name, "Alice's workout")

    def test_a_guessed_plan_id_is_refused(self):
        from ai_planner.models import WorkoutPlan

        plan = WorkoutPlan.objects.create(
            user=self.alice, goal="STAY_FIT", days_per_week=3,
            experience_level="BEGINNER", workout_location="HOME",
            session_duration=60, is_active=True,
            plan_json={"plan_name": "Alice's plan", "days": []},
        )
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(reverse("ai_planner:plan_detail", args=[plan.id])).status_code,
            404,
        )
        self.client.post(reverse("ai_planner:delete_plan", args=[plan.id]))
        self.assertTrue(WorkoutPlan.objects.filter(pk=plan.id).exists())

    def test_a_guessed_notification_id_is_refused(self):
        from notifications.services import create_notification

        note = create_notification(self.alice, "Alice's private note")
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(reverse("notifications:open", args=[note.id])).status_code,
            404,
        )
        note.refresh_from_db()
        self.assertFalse(note.is_read)

    def test_a_trainee_cannot_read_another_trainees_conversation(self):
        from messaging.services import get_or_create_conversation, send_message

        conversation = get_or_create_conversation(self.alice)
        send_message(conversation, self.alice, "Alice's private message")

        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(
                reverse("messaging:poll", args=[conversation.id])
            ).status_code,
            403,
        )
        response = self.client.post(
            reverse("messaging:send", args=[conversation.id]),
            data='{"body": "intruding"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(conversation.messages.count(), 1)

    def test_the_badge_poll_counts_only_your_own(self):
        from notifications.services import create_notification

        for _ in range(3):
            create_notification(self.alice, "For Alice")

        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("notifications:poll")).json()["notifications"], 0)


class SecretsTests(TestCase):
    def test_the_ai_key_never_reaches_a_page(self):
        from django.conf import settings

        key = getattr(settings, "OPENAI_API_KEY", "")
        if not key:
            self.skipTest("No API key configured in this environment.")

        trainee = make_trainee("tina")
        self.client.force_login(trainee)
        for name in ["workouts:home", "ai_planner:current_plan", "users:profile"]:
            with self.subTest(page=name):
                body = self.client.get(reverse(name)).content.decode()
                self.assertNotIn(key, body)

    def test_the_secret_key_is_not_the_django_default(self):
        from django.conf import settings

        self.assertNotIn("django-insecure", settings.SECRET_KEY)
        self.assertGreaterEqual(len(settings.SECRET_KEY), 32)
