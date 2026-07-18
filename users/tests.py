import datetime
import os
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .forms import BodyMeasurementForm
from .models import (
    ActivityLevel,
    BodyMeasurement,
    CalorieCalculation,
    ExperienceLevel,
    Goal,
    Role,
    Sex,
    UserProfile,
    WorkoutLocation,
)
from .services import (
    get_calorie_calculation,
    get_latest_measurement,
    get_measurement_history,
    log_body_measurement,
)

VALID_PASSWORD = "str0ng-pass-2026"


def profile_post(**overrides):
    """A complete, valid set of profile form fields, with per-test overrides.

    The profile form now requires age, weight and height, so every profile
    POST must supply them.
    """
    data = {
        "age": 25,
        "sex": Sex.MALE,
        "weight_kg": "75.0",
        "height_cm": 178,
        "goal": Goal.BUILD_MUSCLE,
        "days_per_week": 3,
        "experience_level": ExperienceLevel.BEGINNER,
        "workout_location": WorkoutLocation.COMMERCIAL_GYM,
        "session_duration": 60,
    }
    data.update(overrides)
    return data


class RegistrationTests(TestCase):
    def _register(self, **overrides):
        data = {
            "username": "alice",
            "email": "alice@example.com",
            "password1": VALID_PASSWORD,
            "password2": VALID_PASSWORD,
        }
        data.update(overrides)
        return self.client.post(reverse("users:register"), data)

    def test_registration_creates_user(self):
        self._register()
        self.assertTrue(User.objects.filter(username="alice").exists())

    def test_registration_creates_a_profile(self):
        """A user must never exist without a profile."""
        self._register()
        user = User.objects.get(username="alice")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_registration_logs_the_user_in(self):
        response = self._register()
        self.assertRedirects(response, reverse("users:profile"))

    def test_password_is_hashed_not_stored_raw(self):
        self._register()
        user = User.objects.get(username="alice")
        self.assertNotEqual(user.password, VALID_PASSWORD)
        self.assertTrue(user.check_password(VALID_PASSWORD))

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(
            username="existing", email="alice@example.com", password=VALID_PASSWORD
        )
        response = self._register()

        self.assertEqual(response.status_code, 200)  # redisplayed with errors
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_duplicate_email_check_ignores_case(self):
        User.objects.create_user(
            username="existing", email="Alice@Example.com", password=VALID_PASSWORD
        )
        self._register(email="alice@example.com")
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_mismatched_passwords_are_rejected(self):
        self._register(password2="something-else-2026")
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_weak_password_is_rejected(self):
        """Django's password validators must be enforced."""
        self._register(password1="123", password2="123")
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_duplicate_username_is_rejected(self):
        User.objects.create_user(username="alice", password=VALID_PASSWORD)
        response = self._register()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username="alice").count(), 1)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password=VALID_PASSWORD)

    def test_login_with_valid_credentials(self):
        response = self.client.post(
            reverse("users:login"), {"username": "alice", "password": VALID_PASSWORD}
        )
        self.assertRedirects(response, reverse("workouts:home"))

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(
            reverse("users:login"), {"username": "alice", "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_logout(self):
        self.client.force_login(self.user)
        self.client.post(reverse("users:logout"))

        response = self.client.get(reverse("workouts:home"))
        self.assertEqual(response.status_code, 302)  # bounced back to login


class SessionBehaviourTests(TestCase):
    def test_the_session_cookie_expires_when_the_browser_closes(self):
        """A browser-session cookie has no Max-Age/Expires, so the browser drops
        it on close rather than keeping the user logged in for 14 days."""
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)

        User.objects.create_user(username="alice", password=VALID_PASSWORD)
        self.client.post(
            reverse("users:login"), {"username": "alice", "password": VALID_PASSWORD}
        )

        cookie = self.client.cookies["sessionid"]
        self.assertEqual(cookie["max-age"], "")
        self.assertEqual(cookie["expires"], "")

    def test_logging_out_clears_the_session(self):
        user = User.objects.create_user(username="alice", password=VALID_PASSWORD)
        self.client.force_login(user)

        self.assertEqual(Session.objects.count(), 1)
        self.client.post(reverse("users:logout"))
        self.assertEqual(Session.objects.count(), 0)


class ProtectedRouteTests(TestCase):
    def test_home_requires_login(self):
        response = self.client.get(reverse("workouts:home"))
        self.assertRedirects(
            response, f"{reverse('users:login')}?next={reverse('workouts:home')}"
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response.url)


class ProfileTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=VALID_PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=VALID_PASSWORD)
        self.client.force_login(self.alice)

    def test_profile_is_created_on_demand_for_users_without_one(self):
        """Superusers made with createsuperuser never hit the registration form."""
        self.assertFalse(UserProfile.objects.filter(user=self.alice).exists())

        self.client.get(reverse("users:profile"))
        self.assertTrue(UserProfile.objects.filter(user=self.alice).exists())

    def test_profile_can_be_updated(self):
        self.client.post(
            reverse("users:profile"),
            profile_post(
                goal=Goal.LOSE_WEIGHT,
                days_per_week=5,
                experience_level=ExperienceLevel.INTERMEDIATE,
                workout_location=WorkoutLocation.HOME,
                session_duration=45,
            ),
        )

        profile = UserProfile.objects.get(user=self.alice)
        self.assertEqual(profile.goal, Goal.LOSE_WEIGHT)
        self.assertEqual(profile.days_per_week, 5)
        self.assertEqual(profile.session_duration, 45)

    def test_body_stats_are_saved(self):
        self.client.post(
            reverse("users:profile"),
            profile_post(age=31, weight_kg="82.5", height_cm=182),
        )

        profile = UserProfile.objects.get(user=self.alice)
        self.assertEqual(profile.age, 31)
        self.assertEqual(str(profile.weight_kg), "82.5")
        self.assertEqual(profile.height_cm, 182)

    def test_saving_then_reloading_preserves_every_field(self):
        """Guards against silent drift: what you save is exactly what comes back."""
        self.client.post(
            reverse("users:profile"),
            profile_post(
                age=23, sex=Sex.MALE, weight_kg="65.0", height_cm=180,
                goal=Goal.BUILD_MUSCLE, days_per_week=5,
                experience_level=ExperienceLevel.ADVANCED,
                workout_location=WorkoutLocation.COMMERCIAL_GYM,
                session_duration=60,
            ),
        )

        profile = UserProfile.objects.get(user=self.alice)
        self.assertEqual(profile.age, 23)
        self.assertEqual(profile.sex, Sex.MALE)
        self.assertEqual(str(profile.weight_kg), "65.0")
        self.assertEqual(profile.height_cm, 180)
        self.assertEqual(profile.days_per_week, 5)
        self.assertEqual(profile.session_duration, 60)

    def test_gender_is_saved(self):
        self.client.post(reverse("users:profile"), profile_post(sex=Sex.FEMALE))
        self.assertEqual(UserProfile.objects.get(user=self.alice).sex, Sex.FEMALE)

    def test_gender_is_required(self):
        UserProfile.objects.create(user=self.alice)
        data = profile_post()
        del data["sex"]

        response = self.client.post(reverse("users:profile"), data)
        self.assertEqual(response.status_code, 200)  # redisplayed with errors
        self.assertIsNone(UserProfile.objects.get(user=self.alice).sex)

    def test_viewing_the_profile_page_does_not_change_stored_values(self):
        """A GET (e.g. after logging back in) must never mutate the profile."""
        UserProfile.objects.create(
            user=self.alice, age=23, sex=Sex.MALE, weight_kg="65.0",
            height_cm=180, days_per_week=5,
        )

        for _ in range(3):
            self.client.get(reverse("users:profile"))

        profile = UserProfile.objects.get(user=self.alice)
        self.assertEqual(profile.age, 23)
        self.assertEqual(profile.sex, Sex.MALE)
        self.assertEqual(str(profile.weight_kg), "65.0")
        self.assertEqual(profile.height_cm, 180)
        self.assertEqual(profile.days_per_week, 5)

    def test_number_inputs_disable_browser_autofill(self):
        UserProfile.objects.create(user=self.alice)
        body = self.client.get(reverse("users:profile")).content.decode()

        # The weight field must not be autofilled by the browser.
        self.assertIn('name="weight_kg"', body)
        self.assertIn('autocomplete="off"', body)

    def test_age_weight_and_height_are_required(self):
        UserProfile.objects.create(user=self.alice)
        data = profile_post()
        del data["age"]
        del data["weight_kg"]
        del data["height_cm"]

        response = self.client.post(reverse("users:profile"), data)

        self.assertEqual(response.status_code, 200)  # redisplayed with errors
        self.assertIsNone(UserProfile.objects.get(user=self.alice).age)

    def test_an_impossible_age_is_rejected(self):
        UserProfile.objects.create(user=self.alice)
        response = self.client.post(reverse("users:profile"), profile_post(age=5))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(UserProfile.objects.get(user=self.alice).age)

    def test_a_negative_weight_is_rejected(self):
        UserProfile.objects.create(user=self.alice)
        self.client.post(reverse("users:profile"), profile_post(weight_kg="-5"))
        self.assertIsNone(UserProfile.objects.get(user=self.alice).weight_kg)

    def test_days_per_week_above_seven_is_rejected(self):
        UserProfile.objects.create(user=self.alice)
        response = self.client.post(
            reverse("users:profile"), profile_post(days_per_week=9)  # max is 7
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserProfile.objects.get(user=self.alice).days_per_week, 3)

    def test_days_per_week_below_one_is_rejected(self):
        UserProfile.objects.create(user=self.alice)
        self.client.post(reverse("users:profile"), profile_post(days_per_week=0))
        self.assertEqual(UserProfile.objects.get(user=self.alice).days_per_week, 3)

    def test_the_form_renders_fields_in_the_intended_order(self):
        UserProfile.objects.create(user=self.alice)
        body = self.client.get(reverse("users:profile")).content.decode()

        order = ["id_age", "id_sex", "id_weight_kg", "id_height_cm", "id_goal",
                 "id_days_per_week", "id_experience_level",
                 "id_workout_location", "id_session_duration"]
        positions = [body.index(field_id) for field_id in order]
        self.assertEqual(positions, sorted(positions))


class UserIsolationTests(TestCase):
    """Core security property: a user only ever touches their own data."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=VALID_PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=VALID_PASSWORD)
        self.bob_profile = UserProfile.objects.create(user=self.bob, days_per_week=6)

    def test_alice_editing_her_profile_does_not_touch_bobs(self):
        self.client.force_login(self.alice)
        self.client.post(
            reverse("users:profile"),
            profile_post(
                goal=Goal.LOSE_WEIGHT,
                days_per_week=2,
                experience_level=ExperienceLevel.ADVANCED,
                workout_location=WorkoutLocation.HOME,
                session_duration=30,
            ),
        )

        self.bob_profile.refresh_from_db()
        self.assertEqual(self.bob_profile.days_per_week, 6)
        self.assertEqual(self.bob_profile.goal, Goal.BUILD_MUSCLE)

    def test_a_submitted_user_id_cannot_hijack_another_profile(self):
        """The profile is resolved from request.user, so injecting a user id
        into the POST body must have no effect."""
        self.client.force_login(self.alice)
        self.client.post(
            reverse("users:profile"),
            profile_post(
                user=self.bob.id,  # attacker-supplied — must be ignored
                goal=Goal.STAY_FIT,
                days_per_week=1,
                experience_level=ExperienceLevel.BEGINNER,
                workout_location=WorkoutLocation.HOME,
                session_duration=20,
            ),
        )

        self.bob_profile.refresh_from_db()
        self.assertEqual(self.bob_profile.user, self.bob)
        self.assertEqual(self.bob_profile.days_per_week, 6)

        alice_profile = UserProfile.objects.get(user=self.alice)
        self.assertEqual(alice_profile.days_per_week, 1)

    def test_home_greets_the_logged_in_user_only(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("workouts:home"))
        self.assertContains(response, "alice")
        self.assertNotContains(response, "bob")


class BodyMeasurementModelTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=VALID_PASSWORD)

    def test_a_measurement_is_stored(self):
        m = BodyMeasurement.objects.create(
            user=self.alice, recorded_on=datetime.date(2026, 7, 1),
            weight_kg=Decimal("80.0"),
        )
        self.assertEqual(m.weight_kg, Decimal("80.0"))

    def test_one_measurement_per_user_per_day(self):
        BodyMeasurement.objects.create(
            user=self.alice, recorded_on=datetime.date(2026, 7, 1),
            weight_kg=Decimal("80.0"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BodyMeasurement.objects.create(
                    user=self.alice, recorded_on=datetime.date(2026, 7, 1),
                    weight_kg=Decimal("81.0"),
                )

    def test_the_same_date_is_allowed_for_different_users(self):
        bob = User.objects.create_user(username="bob", password=VALID_PASSWORD)
        BodyMeasurement.objects.create(
            user=self.alice, recorded_on=datetime.date(2026, 7, 1),
            weight_kg=Decimal("80.0"),
        )
        m = BodyMeasurement.objects.create(
            user=bob, recorded_on=datetime.date(2026, 7, 1),
            weight_kg=Decimal("70.0"),
        )
        self.assertEqual(m.user, bob)


class BodyMeasurementServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=VALID_PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=VALID_PASSWORD)

    def _form(self, **overrides):
        data = {
            "recorded_on": "2026-07-01",
            "weight_kg": "80.0",
            "body_fat_percentage": "18.0",
            "muscle_mass_kg": "35.0",
            "notes": "",
        }
        data.update(overrides)
        return BodyMeasurementForm(data)

    def _log(self, user=None, **overrides):
        """Validate and log — log_body_measurement expects a validated form."""
        form = self._form(**overrides)
        assert form.is_valid(), form.errors
        return log_body_measurement(user or self.alice, form)

    def test_logging_creates_a_measurement(self):
        form = self._form()
        self.assertTrue(form.is_valid())

        m = log_body_measurement(self.alice, form)

        self.assertEqual(m.user, self.alice)
        self.assertEqual(m.weight_kg, Decimal("80.0"))
        self.assertEqual(m.body_fat_percentage, Decimal("18.0"))

    def test_optional_fields_can_be_blank(self):
        form = self._form(body_fat_percentage="", muscle_mass_kg="")
        self.assertTrue(form.is_valid())

        m = log_body_measurement(self.alice, form)
        self.assertIsNone(m.body_fat_percentage)
        self.assertIsNone(m.muscle_mass_kg)

    def test_logging_twice_on_the_same_day_updates_rather_than_duplicates(self):
        self._log(weight_kg="80.0")
        self._log(weight_kg="79.0")

        measurements = BodyMeasurement.objects.filter(user=self.alice)
        self.assertEqual(measurements.count(), 1)
        self.assertEqual(measurements.first().weight_kg, Decimal("79.0"))

    def test_a_negative_weight_is_rejected_by_the_form(self):
        form = self._form(weight_kg="-5")
        self.assertFalse(form.is_valid())

    def test_history_is_ordered_oldest_first(self):
        self._log(recorded_on="2026-07-10")
        self._log(recorded_on="2026-07-01")

        dates = [m.recorded_on for m in get_measurement_history(self.alice)]
        self.assertEqual(dates, sorted(dates))

    def test_latest_measurement(self):
        self._log(recorded_on="2026-07-01")
        self._log(recorded_on="2026-07-10")

        latest = get_latest_measurement(self.alice)
        self.assertEqual(latest.recorded_on, datetime.date(2026, 7, 10))

    def test_measurements_are_isolated_per_user(self):
        self._log()
        self.assertEqual(get_measurement_history(self.bob).count(), 0)


class WellnessPageTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=VALID_PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.alice, height_cm=180)
        self.client.force_login(self.alice)

    def _log(self, date, weight, **extra):
        BodyMeasurement.objects.create(
            user=self.alice, recorded_on=date, weight_kg=Decimal(str(weight)), **extra
        )

    def test_wellness_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("analytics:wellness"))
        self.assertEqual(response.status_code, 302)

    def test_empty_passport_prompts_a_first_weigh_in(self):
        response = self.client.get(reverse("analytics:wellness"))
        self.assertContains(response, "No measurements yet")

    def test_logging_through_the_page(self):
        response = self.client.post(
            reverse("analytics:wellness"),
            {"recorded_on": "2026-07-01", "weight_kg": "82.0",
             "body_fat_percentage": "", "muscle_mass_kg": "", "notes": ""},
        )
        self.assertRedirects(response, reverse("analytics:wellness"))
        self.assertEqual(BodyMeasurement.objects.filter(user=self.alice).count(), 1)

    def test_the_passport_shows_the_latest_weight_and_bmi(self):
        self._log(datetime.date(2026, 7, 1), 81)
        response = self.client.get(reverse("analytics:wellness"))

        self.assertContains(response, "81")
        self.assertContains(response, "BMI")
        # 81 kg at 180 cm -> BMI 25.0
        self.assertContains(response, "25.0")

    def test_bob_cannot_see_alices_measurements(self):
        self._log(datetime.date(2026, 7, 1), 123)

        self.client.force_login(self.bob)
        response = self.client.get(reverse("analytics:wellness"))

        self.assertContains(response, "No measurements yet")
        self.assertNotContains(response, "123")


class CalorieCalculatorPageTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=VALID_PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=VALID_PASSWORD)
        UserProfile.objects.create(
            user=self.alice, age=25, sex=Sex.MALE, height_cm=180, weight_kg="65.0"
        )
        self.client.force_login(self.alice)

    def _calc_post(self, **overrides):
        data = {
            "age": 25,
            "sex": Sex.MALE,
            "height_cm": 180,
            "weight_kg": "65.0",
            "activity_level": ActivityLevel.MODERATE,
        }
        data.update(overrides)
        return data

    def test_calorie_page_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("analytics:calories")).status_code, 302)

    def test_first_visit_shows_the_input_form(self):
        response = self.client.get(reverse("analytics:calories"))
        self.assertContains(response, "Calculate")
        self.assertContains(response, "Activity level")

    def test_the_calorie_form_prefills_gender_from_the_profile(self):
        """Gender entered once in the profile flows into the calorie calculator."""
        response = self.client.get(reverse("analytics:calories"))
        # The male radio/option is pre-selected from the profile.
        self.assertContains(response, "checked")  # RadioSelect marks the choice

    def test_calculating_saves_the_result(self):
        response = self.client.post(reverse("analytics:calories"), self._calc_post())

        self.assertRedirects(response, reverse("analytics:calories"))
        calc = CalorieCalculation.objects.get(user=self.alice)
        self.assertEqual(calc.bmr, 1655)
        self.assertEqual(calc.maintenance_calories, 2425)

    def test_returning_visit_shows_the_saved_result_without_the_form(self):
        self.client.post(reverse("analytics:calories"), self._calc_post())

        response = self.client.get(reverse("analytics:calories"))
        self.assertContains(response, "2425")            # maintenance
        self.assertContains(response, "Maintain weight")  # target table
        self.assertContains(response, "Recalculate")
        self.assertNotContains(response, "Calculate</button>")  # form not shown

    def test_recalculate_shows_the_form_again(self):
        self.client.post(reverse("analytics:calories"), self._calc_post())

        response = self.client.get(reverse("analytics:calories"), {"recalculate": "1"})
        self.assertContains(response, "Calculate")

    def test_recalculating_overwrites_rather_than_duplicating(self):
        self.client.post(reverse("analytics:calories"), self._calc_post())
        self.client.post(
            reverse("analytics:calories"),
            self._calc_post(weight_kg="80.0", activity_level=ActivityLevel.SEDENTARY),
        )

        self.assertEqual(CalorieCalculation.objects.filter(user=self.alice).count(), 1)
        calc = get_calorie_calculation(self.alice)
        self.assertEqual(str(calc.weight_kg), "80.0")

    def test_the_know_your_calories_guide_renders(self):
        response = self.client.get(reverse("analytics:calorie_guide"))
        self.assertContains(response, "maintenance calories")
        self.assertContains(response, "calorie deficit")
        self.assertContains(response, "not a substitute for personalised advice")

    def test_bob_does_not_see_alices_calculation(self):
        self.client.post(reverse("analytics:calories"), self._calc_post())

        self.client.force_login(self.bob)
        response = self.client.get(reverse("analytics:calories"))
        self.assertContains(response, "Calculate")  # bob gets a fresh form
        self.assertIsNone(get_calorie_calculation(self.bob))


class NutritionPageTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=VALID_PASSWORD)
        UserProfile.objects.create(
            user=self.alice, age=25, sex=Sex.MALE, height_cm=180, weight_kg="65.0"
        )
        self.client.force_login(self.alice)

    def _calculate_calories(self):
        self.client.post(
            reverse("analytics:calories"),
            {
                "age": 25, "sex": Sex.MALE, "height_cm": 180,
                "weight_kg": "60.0", "activity_level": ActivityLevel.MODERATE,
            },
        )

    def test_nutrition_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("analytics:nutrition")).status_code, 302)

    def test_without_a_calorie_calculation_it_prompts_to_calculate(self):
        response = self.client.get(reverse("analytics:nutrition"))
        self.assertContains(response, "Calculate your calories first")

    def test_with_calories_it_shows_macro_targets(self):
        self._calculate_calories()  # 60 kg, maintenance ~2337 for these inputs

        response = self.client.get(reverse("analytics:nutrition"))

        self.assertContains(response, "Protein")
        self.assertContains(response, "Fat")
        self.assertContains(response, "Carbohydrates")
        self.assertContains(response, "Fibre")
        self.assertContains(response, "108 g")  # 60 kg * 1.8 protein

    def test_choosing_a_goal_changes_the_calories_used(self):
        self._calculate_calories()

        maintain = self.client.get(reverse("analytics:nutrition"), {"goal": "maintain"})
        loss = self.client.get(reverse("analytics:nutrition"), {"goal": "loss"})

        # A deficit goal must yield fewer calories than maintenance.
        self.assertNotEqual(maintain.content, loss.content)

    def test_the_food_source_tables_are_shown(self):
        self._calculate_calories()
        response = self.client.get(reverse("analytics:nutrition"))

        self.assertContains(response, "Vegetarian protein sources")
        self.assertContains(response, "Soya chunks")
        self.assertContains(response, "oils and concentrated fats")
        self.assertContains(response, "grains and cereals")
        self.assertContains(response, "Fibre sources")
        self.assertContains(response, "Chia seeds")

    def test_the_formula_is_shown_to_the_user(self):
        self._calculate_calories()
        response = self.client.get(reverse("analytics:nutrition"))
        body = response.content.decode()

        # The protein formula uses the user's own bodyweight.
        self.assertIn("60.0", body)
        self.assertIn("1 g protein = 4 kcal", body)
        self.assertIn("1 g fat = 9 kcal", body)


# ==========================================================================
# Phase A — Role-based access control
# ==========================================================================


class RoleModelTests(TestCase):
    def test_public_registration_creates_a_trainee(self):
        self.client.post(
            reverse("users:register"),
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        profile = UserProfile.objects.get(user__username="newbie")
        self.assertEqual(profile.role, Role.TRAINEE)
        self.assertTrue(profile.is_trainee)
        self.assertFalse(profile.is_admin)

    def test_role_defaults_to_trainee(self):
        user = User.objects.create_user(username="x", password=VALID_PASSWORD)
        profile = UserProfile.objects.create(user=user)
        self.assertEqual(profile.role, Role.TRAINEE)


class SeedAdminCommandTests(TestCase):
    def test_seed_admin_creates_an_admin_with_hashed_password(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "Sup3r-Secret!"}):
            call_command("seed_admin", "--username", "atith", "--email", "a@b.com")

        user = User.objects.get(username="atith")
        self.assertTrue(user.profile.is_admin)
        self.assertTrue(user.is_staff)
        # Stored hashed, never plain.
        self.assertNotEqual(user.password, "Sup3r-Secret!")
        self.assertTrue(user.check_password("Sup3r-Secret!"))

    def test_seed_admin_is_idempotent(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "pw-one-2026"}):
            call_command("seed_admin", "--username", "atith")
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "pw-two-2026"}):
            call_command("seed_admin", "--username", "atith")

        self.assertEqual(User.objects.filter(username="atith").count(), 1)
        self.assertTrue(User.objects.get(username="atith").check_password("pw-two-2026"))

    def test_seed_admin_without_password_env_errors(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADMIN_PASSWORD", None)
            with self.assertRaises(CommandError):
                call_command("seed_admin", "--username", "atith")


class RoleDecoratorTests(TestCase):
    def setUp(self):
        self.trainee = User.objects.create_user(username="tina", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.trainee, role=Role.TRAINEE)
        self.admin = User.objects.create_user(username="adam", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.admin, role=Role.ADMIN)

    def test_admin_route_allows_admin(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("adminportal:dashboard")).status_code, 200)

    def test_admin_route_forbids_trainee(self):
        self.client.force_login(self.trainee)
        self.assertEqual(self.client.get(reverse("adminportal:dashboard")).status_code, 403)

    def test_admin_route_redirects_anonymous_to_login(self):
        response = self.client.get(reverse("adminportal:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response.url)


class LoginRedirectTests(TestCase):
    def setUp(self):
        self.trainee = User.objects.create_user(username="tina", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.trainee, role=Role.TRAINEE)
        self.admin = User.objects.create_user(username="adam", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.admin, role=Role.ADMIN)

    def test_trainee_login_redirects_home(self):
        response = self.client.post(
            reverse("users:login"),
            {"username": "tina", "password": VALID_PASSWORD, "as_role": "trainee"},
        )
        self.assertRedirects(response, reverse("workouts:home"))

    def test_admin_login_redirects_to_portal(self):
        response = self.client.post(
            reverse("users:login"),
            {"username": "adam", "password": VALID_PASSWORD, "as_role": "admin"},
        )
        self.assertRedirects(response, reverse("adminportal:dashboard"))

    def test_trainee_cannot_login_through_the_admin_option(self):
        response = self.client.post(
            reverse("users:login"),
            {"username": "tina", "password": VALID_PASSWORD, "as_role": "admin"},
        )
        self.assertEqual(response.status_code, 200)  # re-rendered with an error
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_admin_cannot_login_through_the_trainee_option(self):
        response = self.client.post(
            reverse("users:login"),
            {"username": "adam", "password": VALID_PASSWORD, "as_role": "trainee"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class RoleChromeTests(TestCase):
    """Admins must not see trainee chrome (bottom tab bar, Joey)."""

    def setUp(self):
        self.trainee = User.objects.create_user(username="tina", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.trainee, role=Role.TRAINEE)
        self.admin = User.objects.create_user(username="adam", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.admin, role=Role.ADMIN)

    def test_trainee_pages_show_the_tab_bar_and_joey(self):
        self.client.force_login(self.trainee)
        body = self.client.get(reverse("workouts:home")).content.decode()
        self.assertIn("fl-tabbar", body)
        self.assertIn("fl-joey", body)

    def test_admin_dashboard_hides_trainee_chrome(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("adminportal:dashboard")).content.decode()
        self.assertNotIn("fl-tabbar", body)
        self.assertNotIn("fl-joey", body)


# ==========================================================================
# Phase D — Profile sharing permission
# ==========================================================================


class ProfileSharingTests(TestCase):
    def setUp(self):
        from users.models import Role as _R
        self.admin = User.objects.create_user(username="theadmin", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.admin, role=_R.ADMIN)
        self.trainee = User.objects.create_user(username="tina", password=VALID_PASSWORD)
        UserProfile.objects.create(user=self.trainee, role=_R.TRAINEE)

    def _admin_perm_notes(self):
        from notifications.models import Category, Notification
        return Notification.objects.filter(recipient=self.admin, category=Category.PERMISSION)

    def test_sharing_is_off_by_default(self):
        self.assertFalse(self.trainee.profile.profile_shared)

    def test_can_admin_view_profile_reflects_the_flag(self):
        from users.services import can_admin_view_profile, set_profile_sharing
        self.assertFalse(can_admin_view_profile(self.trainee))
        set_profile_sharing(self.trainee, True)
        self.assertTrue(can_admin_view_profile(self.trainee))

    def test_enabling_notifies_admins(self):
        from users.services import set_profile_sharing
        set_profile_sharing(self.trainee, True)
        note = self._admin_perm_notes().first()
        self.assertIsNotNone(note)
        self.assertIn("enabled", note.title)

    def test_disabling_notifies_admins(self):
        from users.services import set_profile_sharing
        set_profile_sharing(self.trainee, True)
        set_profile_sharing(self.trainee, False)
        self.assertTrue(self._admin_perm_notes().filter(title__icontains="disabled").exists())

    def test_no_notification_when_unchanged(self):
        from users.services import set_profile_sharing
        set_profile_sharing(self.trainee, False)  # already False
        self.assertEqual(self._admin_perm_notes().count(), 0)

    def test_toggle_endpoint_enables(self):
        self.client.force_login(self.trainee)
        self.client.post(reverse("users:toggle_profile_sharing"), {"share": "on"})
        self.trainee.profile.refresh_from_db()
        self.assertTrue(self.trainee.profile.profile_shared)

    def test_toggle_endpoint_disables(self):
        UserProfile.objects.filter(user=self.trainee).update(profile_shared=True)
        self.client.force_login(self.trainee)
        self.client.post(reverse("users:toggle_profile_sharing"), {"share": "off"})
        self.trainee.profile.refresh_from_db()
        self.assertFalse(self.trainee.profile.profile_shared)

    def test_toggle_is_trainee_only(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("users:toggle_profile_sharing"), {"share": "on"})
        self.assertEqual(response.status_code, 403)

    def test_toggle_requires_login(self):
        response = self.client.post(reverse("users:toggle_profile_sharing"), {"share": "on"})
        self.assertEqual(response.status_code, 302)

    def test_profile_page_shows_the_toggle(self):
        self.client.force_login(self.trainee)
        body = self.client.get(reverse("users:profile")).content.decode()
        self.assertIn("Allow admin to view my profile", body)
        self.assertIn("Enable", body)
        self.assertIn("Disable", body)
