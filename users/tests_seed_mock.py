"""Tests for the seed_mock_trainees command."""

from collections import Counter
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from users.models import CalorieCalculation, Goal, Role, Sex, UserProfile
from workouts.models import WorkoutSession, WorkoutSet

# The command creates 30 accounts per call, each hashing a password. The real
# pbkdf2 hasher makes that dominate the whole suite's runtime; MD5 is fine for a
# test that only needs the hashing to happen, not to be strong.
FAST_HASHER = override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)


def seed(**opts):
    call_command("seed_mock_trainees", stdout=StringIO(), **opts)


def trainees():
    return User.objects.filter(profile__role=Role.TRAINEE)


class SeedTestBase(TestCase):
    """The exercise library is seeded by a management command, not a migration,
    so a fresh test database has none. Workout generation needs it — without it
    sessions are created but every set is silently dropped."""

    def setUp(self):
        call_command("seed_exercises", stdout=StringIO())


@FAST_HASHER
class SeedCreationTests(SeedTestBase):
    def test_it_creates_thirty_shared_active_trainees(self):
        seed(weeks=0)
        self.assertEqual(trainees().count(), 30)
        # Every one is shared with the admin, active, and a real login.
        self.assertEqual(trainees().filter(profile__profile_shared=True).count(), 30)
        self.assertEqual(trainees().filter(is_active=True).count(), 30)
        for user in trainees():
            self.assertTrue(user.check_password("FitLogger@2026"))

    def test_all_mock_accounts_use_the_example_domain(self):
        seed(weeks=0)
        self.assertEqual(trainees().exclude(email__iendswith="@example.com").count(), 0)

    def test_strength_gain_folds_into_build_muscle(self):
        seed(weeks=0)
        # 12 Build Muscle + 3 Strength Gain in the sheet -> 15 Build muscle.
        goals = Counter(t.profile.goal for t in trainees())
        self.assertEqual(goals[Goal.BUILD_MUSCLE], 15)
        self.assertEqual(goals[Goal.LOSE_WEIGHT], 9)
        self.assertEqual(goals[Goal.STAY_FIT], 6)

    def test_the_gender_split_is_fifteen_each(self):
        seed(weeks=0)
        sexes = Counter(t.profile.sex for t in trainees())
        self.assertEqual(sexes[Sex.MALE], 15)
        self.assertEqual(sexes[Sex.FEMALE], 15)

    def test_every_trainee_has_a_calorie_calculation(self):
        seed(weeks=0)
        self.assertEqual(CalorieCalculation.objects.count(), 30)

    def test_signup_dates_are_preserved(self):
        seed(weeks=0)
        rahul = User.objects.get(username="rahul.sharma")
        self.assertEqual(timezone.localtime(rahul.date_joined).strftime("%d %b %Y"),
                         "08 Jul 2025")

    def test_some_trainees_are_active_and_some_never_logged_in(self):
        seed(weeks=0)
        # The recency spread must produce both, or DAU/WAU/MAU would be flat.
        self.assertTrue(trainees().filter(last_login__isnull=True).exists())
        self.assertTrue(trainees().filter(last_login__isnull=False).exists())

    def test_it_is_idempotent(self):
        seed(weeks=0)
        seed(weeks=0)  # second run must not duplicate
        self.assertEqual(trainees().count(), 30)

    def test_it_does_not_notify_admins(self):
        # Straight-ORM creation must not fire the "new trainee" notifications
        # that register_user would — 30 of them would be noise.
        from notifications.models import Notification

        seed(weeks=0)
        self.assertEqual(Notification.objects.count(), 0)


@FAST_HASHER
class SeedWorkoutTests(SeedTestBase):
    def test_workouts_land_on_the_trainees_training_days(self):
        seed(weeks=1)
        rahul = User.objects.get(username="rahul.sharma")  # Mon/Tue/Thu/Sat
        weekdays = {
            timezone.localtime(s.started_at).strftime("%a")
            for s in WorkoutSession.objects.filter(user=rahul)
        }
        self.assertTrue(weekdays)
        self.assertTrue(weekdays <= {"Mon", "Tue", "Thu", "Sat"})

    def test_workouts_are_completed_and_have_sets(self):
        seed(weeks=1)
        self.assertTrue(WorkoutSession.objects.exists())
        self.assertEqual(WorkoutSession.objects.filter(is_completed=False).count(), 0)
        self.assertTrue(WorkoutSet.objects.exists())

    def test_weeks_zero_makes_no_workouts(self):
        seed(weeks=0)
        self.assertEqual(WorkoutSession.objects.count(), 0)


@FAST_HASHER
class SeedClearTests(SeedTestBase):
    def test_clear_removes_every_mock_trainee_and_their_data(self):
        seed(weeks=1)
        self.assertEqual(trainees().count(), 30)

        seed(clear=True)
        self.assertEqual(trainees().count(), 0)
        self.assertEqual(WorkoutSession.objects.count(), 0)
        self.assertEqual(WorkoutSet.objects.count(), 0)
        self.assertEqual(CalorieCalculation.objects.count(), 0)

    def test_clear_spares_a_real_account(self):
        real = User.objects.create_user(
            username="realuser", email="real@gmail.com", password="x"
        )
        UserProfile.objects.create(user=real, role=Role.TRAINEE)
        seed(weeks=0)
        seed(clear=True)

        self.assertTrue(User.objects.filter(username="realuser").exists())
        self.assertEqual(trainees().count(), 1)  # only the real one remains


@FAST_HASHER
class SeedAnalyticsTests(SeedTestBase):
    def test_the_platform_charts_reflect_the_seed(self):
        from adminportal.services import platform_analytics

        seed(weeks=1)
        data = platform_analytics("year")

        self.assertEqual(data["total_trainees"], 30)
        # Goal / experience / sex distributions render (well above the floor).
        self.assertIsNotNone(data["goals"])
        goal = {b["label"]: b["count"] for b in data["goals"]}
        self.assertEqual(goal["Build muscle"], 15)
        # The weekday chart has real workouts behind it now.
        self.assertGreater(sum(b["count"] for b in data["weekday"]), 0)
        # Active-users buckets are populated by the recency spread.
        self.assertGreater(data["active"][2]["count"], 0)  # Monthly
