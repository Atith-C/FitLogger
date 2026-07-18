"""Every page must render.

A template error — a bad filter, a renamed context key, a typo in a URL tag —
is invisible to unit tests that never render the page. These tests do nothing
clever: they sign a user in and GET every route, asserting a 200 and the right
template. That is enough to catch the whole class of "the view is fine but the
page explodes" bug.

This matters most for the nutrition and calorie-guide screens, which had no
coverage of their own.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ai_planner.models import WorkoutPlan
from users.models import CalorieCalculation, UserProfile
from workouts.models import Equipment, Exercise, MuscleGroup, WorkoutSession, WorkoutSet

PASSWORD = "str0ng-pass-2026"

PLAN_JSON = {
    "plan_name": "Test Plan",
    "summary": "A plan for rendering.",
    "days": [
        {
            "day_number": 1,
            "day_name": "Upper Push",
            "focus": "Chest and triceps",
            "exercises": [
                {
                    "exercise": "Bench Press",
                    "sets": 4,
                    "rep_range": "6-8",
                    "notes": "Leave one in the tank.",
                }
            ],
        }
    ],
}


class PublicPageTests(TestCase):
    def test_landing_renders_signed_out(self):
        response = self.client.get(reverse("workouts:landing"))
        self.assertEqual(response.status_code, 200)

    def test_login_renders(self):
        response = self.client.get(reverse("users:login"))
        self.assertEqual(response.status_code, 200)
        # The field names the LoginView expects must survive any restyle.
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')

    def test_register_renders_every_field(self):
        response = self.client.get(reverse("users:register"))
        self.assertEqual(response.status_code, 200)
        for field in ("username", "email", "password1", "password2"):
            self.assertContains(response, 'name="%s"' % field)

    def test_healthz_is_public(self):
        response = self.client.get(reverse("workouts:healthz"))
        self.assertEqual(response.status_code, 200)


class AuthenticatedPageTests(TestCase):
    """Renders every signed-in page for a user with a full set of data."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="alice", password=PASSWORD)
        UserProfile.objects.update_or_create(
            user=cls.user,
            defaults={
                "age": 30,
                "sex": "male",
                "weight_kg": Decimal("80.0"),
                "height_cm": 180,
                "days_per_week": 4,
                "session_duration": 60,
            },
        )
        cls.bench = Exercise.objects.create(
            name="Bench Press",
            muscle_group=MuscleGroup.CHEST,
            equipment=Equipment.BARBELL,
        )

        # A completed session, so charts and history have something to draw.
        started = timezone.now() - timedelta(days=2)
        session = WorkoutSession.objects.create(
            user=cls.user,
            name="Push Day",
            started_at=started,
            completed_at=started + timedelta(hours=1),
            is_completed=True,
        )
        WorkoutSet.objects.create(
            session=session,
            exercise=cls.bench,
            set_number=1,
            weight=Decimal("60.00"),
            reps=10,
        )

        WorkoutPlan.objects.create(
            user=cls.user,
            goal="build_muscle",
            days_per_week=4,
            experience_level="beginner",
            workout_location="commercial_gym",
            session_duration=60,
            plan_json=PLAN_JSON,
            is_active=True,
        )

        # Nutrition needs a calorie calculation to show targets rather than a
        # "go and calculate first" prompt — both branches are asserted below.
        CalorieCalculation.objects.create(
            user=cls.user,
            sex="male",
            activity_level="moderate",
            age=30,
            height_cm=180,
            weight_kg=Decimal("80.0"),
            bmr=1780,
            maintenance_calories=2608,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_home_renders_with_stats(self):
        response = self.client.get(reverse("workouts:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "workouts/home.html")
        self.assertEqual(response.context["stats"]["total_workouts"], 1)

    def test_home_ring_renders_a_real_percentage(self):
        """The ring is a conic gradient driven by an inline custom property —
        if the value never lands in the HTML the ring silently reads as 0."""
        response = self.client.get(reverse("workouts:home"))
        html = response.content.decode()

        # One completed session against a 4-day plan = 25%.
        self.assertIn("--fl-ring-pct: 25", html)
        # The ring must be labelled: a conic gradient means nothing to a reader.
        self.assertIn("planned workouts completed this week", html)

    def test_home_shows_all_time_volume(self):
        response = self.client.get(reverse("workouts:home"))
        # 60kg x 10 reps = 600, rendered without decimals.
        self.assertContains(response, "600")
        self.assertEqual(response.context["stats"]["total_volume_kg"], Decimal("600.00"))

    def test_history_renders(self):
        response = self.client.get(reverse("workouts:history"))
        self.assertEqual(response.status_code, 200)

    def test_start_workout_renders(self):
        response = self.client.get(reverse("workouts:start_workout"))
        self.assertEqual(response.status_code, 200)

    def test_profile_renders(self):
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 200)

    def test_current_plan_renders(self):
        response = self.client.get(reverse("ai_planner:current_plan"))
        self.assertEqual(response.status_code, 200)

    def test_generate_plan_renders_with_a_skeleton_per_training_day(self):
        response = self.client.get(reverse("ai_planner:generate_plan"))
        self.assertEqual(response.status_code, 200)
        # The skeleton is built to the shape of the plan that is coming: the
        # ljust idiom must produce one card per training day.
        self.assertContains(response, "fl-plan-skeleton-day", count=4)

    def test_progress_renders_without_an_exercise(self):
        response = self.client.get(reverse("analytics:progress"))
        self.assertEqual(response.status_code, 200)

    def test_progress_renders_for_an_exercise(self):
        response = self.client.get(
            reverse("analytics:progress"), {"exercise": self.bench.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "chart-1rm")

    def test_wellness_renders(self):
        response = self.client.get(reverse("analytics:wellness"))
        self.assertEqual(response.status_code, 200)

    def test_calories_renders(self):
        response = self.client.get(reverse("analytics:calories"))
        self.assertEqual(response.status_code, 200)

    def test_calorie_guide_renders(self):
        """Previously uncovered — a static page still breaks if base.html does."""
        response = self.client.get(reverse("analytics:calorie_guide"))
        self.assertEqual(response.status_code, 200)

    def test_nutrition_renders_with_targets(self):
        """Previously uncovered."""
        response = self.client.get(reverse("analytics:nutrition"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["needs_calories"])

    def test_nutrition_renders_for_each_goal(self):
        for goal in (
            "maintain",
            "mild_loss",
            "loss",
            "extreme_loss",
            "mild_gain",
            "gain",
            "fast_gain",
        ):
            with self.subTest(goal=goal):
                response = self.client.get(reverse("analytics:nutrition"), {"goal": goal})
                self.assertEqual(response.status_code, 200)

    def test_active_workout_renders(self):
        session = WorkoutSession.objects.create(
            user=self.user, name="Live", started_at=timezone.now()
        )
        response = self.client.get(
            reverse("workouts:active_workout", args=[session.id]),
            {"exercise": self.bench.id},
        )
        self.assertEqual(response.status_code, 200)
        # JS contracts the logging screen depends on.
        for hook in ("exercise-picker", "exercise-select", "set-form", "fl-step-btn"):
            self.assertContains(response, hook)


class NutritionWithoutCaloriesTests(TestCase):
    """The other nutrition branch: no calorie calculation on file."""

    def setUp(self):
        self.user = User.objects.create_user(username="bob", password=PASSWORD)
        self.client.force_login(self.user)

    def test_nutrition_prompts_for_calories_first(self):
        response = self.client.get(reverse("analytics:nutrition"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["needs_calories"])


class TemplateCommentLeakTests(TestCase):
    """Django's {# #} is single-line only — a multi-line one is not a comment,
    it is text, and it renders to the user. workouts/tests.py guards the active
    workout screen; this covers the rest, since the mistake is invisible until
    someone reads the page."""

    def setUp(self):
        self.user = User.objects.create_user(username="dave", password=PASSWORD)

    def test_public_pages_leak_no_comment_markers(self):
        for name in ("workouts:landing", "users:login", "users:register"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertNotContains(response, "{#")
                self.assertNotContains(response, "{% comment %}")

    def test_signed_in_pages_leak_no_comment_markers(self):
        self.client.force_login(self.user)
        for name in (
            "workouts:home",
            "workouts:history",
            "workouts:start_workout",
            "users:profile",
            "ai_planner:current_plan",
            "ai_planner:generate_plan",
            "analytics:progress",
            "analytics:wellness",
            "analytics:calories",
            "analytics:calorie_guide",
            "analytics:nutrition",
        ):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertNotContains(response, "{#")
                self.assertNotContains(response, "{% comment %}")


class ChromeTests(TestCase):
    """base.html is shared by every page — a mistake here breaks the whole app."""

    def setUp(self):
        self.user = User.objects.create_user(username="carol", password=PASSWORD)

    def test_signed_out_brand_points_at_the_landing_page(self):
        response = self.client.get(reverse("users:login"))
        self.assertContains(response, 'href="%s"' % reverse("workouts:landing"))

    def test_signed_in_nav_shows_every_section(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("workouts:home"))
        for name in (
            "ai_planner:current_plan",
            "analytics:progress",
            "analytics:wellness",
            "analytics:calories",
            "analytics:nutrition",
            "workouts:history",
            "users:profile",
        ):
            self.assertContains(response, reverse(name))

    def test_landing_does_not_render_the_app_tab_bar(self):
        """The tab bar is for signed-in users; it must not leak onto the pitch."""
        response = self.client.get(reverse("workouts:landing"))
        self.assertNotContains(response, "fl-tabbar")
