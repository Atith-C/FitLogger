from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from pydantic import ValidationError as PydanticValidationError

from users.models import ExperienceLevel, Goal, Sex, UserProfile, WorkoutLocation
from workouts.models import Exercise, MuscleGroup
from workouts.services import get_exercises_grouped_by_muscle

from .models import WorkoutPlan
from .prompts import (
    SYSTEM_PROMPT,
    build_initial_plan_prompt,
    format_exercise_library,
    format_lifter,
)
from .services import (
    PlanGenerationError,
    _call_model,
    delete_plan,
    generate_initial_plan,
    get_active_plan,
    get_plan_history,
    get_user_plan,
    save_edited_plan,
)
from .views import _parse_plan_form
from .validators import PlanValidationError, WorkoutPlanSchema, validate_plan

PASSWORD = "str0ng-pass-2026"


def valid_plan(days=3):
    """A well-formed plan dict of the requested length."""
    return {
        "plan_name": "Beginner Full Body",
        "summary": "Three full-body sessions a week.",
        "days": [
            {
                "day_number": number,
                "day_name": f"Day {number}",
                "focus": "Full body",
                "exercises": [
                    {
                        "exercise": "Barbell Squat",
                        "sets": 3,
                        "rep_range": "6-8",
                        "notes": "Keep your chest up.",
                    }
                ],
            }
            for number in range(1, days + 1)
        ],
    }


def plan_schema(days=3, **plan_overrides):
    """A parsed WorkoutPlanSchema, as _call_model would return it."""
    data = valid_plan(days)
    data.update(plan_overrides)
    return WorkoutPlanSchema.model_validate(data)


def mock_ai_response(payload):
    """Patch the model call to return a parsed WorkoutPlanSchema.

    Accepts a plan dict (validated into a schema object) or an already-built
    schema. Tests never make a real API call.
    """
    model = payload if isinstance(payload, WorkoutPlanSchema) else WorkoutPlanSchema.model_validate(payload)
    return patch("ai_planner.services._call_model", return_value=model)


def failing_ai_call(message=None):
    """Patch the model call to fail the way a provider outage or refusal would."""
    from ai_planner.services import GENERIC_FAILURE_MESSAGE

    return patch(
        "ai_planner.services._call_model",
        side_effect=PlanGenerationError(message or GENERIC_FAILURE_MESSAGE),
    )


class WorkoutPlanModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="pw-test-1234")
        self.other_user = User.objects.create_user(username="bob", password="pw-test-1234")

    def _make_plan(self, user=None, is_active=True):
        return WorkoutPlan.objects.create(
            user=user or self.user,
            goal=Goal.BUILD_MUSCLE,
            days_per_week=4,
            experience_level=ExperienceLevel.BEGINNER,
            workout_location=WorkoutLocation.COMMERCIAL_GYM,
            session_duration=60,
            plan_json={"plan_name": "Test Plan", "days": []},
            is_active=is_active,
        )

    def test_plan_stores_json(self):
        plan = self._make_plan()
        self.assertEqual(plan.plan_json["plan_name"], "Test Plan")

    def test_analytics_snapshot_defaults_to_empty(self):
        plan = self._make_plan()
        self.assertEqual(plan.analytics_snapshot, {})

    def test_user_cannot_have_two_active_plans(self):
        self._make_plan()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_plan()

    def test_archived_plans_are_kept_alongside_an_active_one(self):
        """Plan history must survive: archiving is not deletion."""
        self._make_plan(is_active=False)
        self._make_plan(is_active=False)
        self._make_plan(is_active=True)

        self.assertEqual(WorkoutPlan.objects.filter(user=self.user).count(), 3)
        self.assertEqual(
            WorkoutPlan.objects.filter(user=self.user, is_active=True).count(), 1
        )

    def test_active_plan_constraint_is_per_user(self):
        self._make_plan(user=self.user)
        plan = self._make_plan(user=self.other_user)
        self.assertTrue(plan.is_active)


class PromptTests(TestCase):
    """The prompt is what separates a designed plan from a generic template."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.profile = UserProfile.objects.create(user=self.alice, days_per_week=4)

        Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        Exercise.objects.create(
            name="Barbell Squat", muscle_group=MuscleGroup.QUADRICEPS
        )
        self.library = get_exercises_grouped_by_muscle()

    def test_the_prompt_lists_the_exercise_library(self):
        """A plan may only prescribe movements the app can actually log."""
        prompt = build_initial_plan_prompt(self.profile, self.library)

        self.assertIn("Bench Press", prompt)
        self.assertIn("Barbell Squat", prompt)
        self.assertIn("ONLY prescribe exercises from this list", prompt)

    def test_the_prompt_states_the_exact_day_count(self):
        prompt = build_initial_plan_prompt(self.profile, self.library)
        self.assertIn("EXACTLY 4 training day(s)", prompt)

    def test_the_prompt_demands_a_concrete_progression_scheme(self):
        prompt = build_initial_plan_prompt(self.profile, self.library)

        self.assertIn("PROGRESSION SCHEME", prompt)
        self.assertIn("Be concrete", prompt)

    def test_the_prompt_demands_rest_periods_and_real_cues(self):
        prompt = build_initial_plan_prompt(self.profile, self.library)
        self.assertIn("Include the rest period", prompt)

    def test_the_prompt_carries_the_users_actual_profile(self):
        self.profile.session_duration = 45
        self.profile.save()

        prompt = build_initial_plan_prompt(self.profile, self.library)

        self.assertIn("45 minutes", prompt)
        self.assertIn("Commercial gym", prompt)

    def test_the_system_prompt_forbids_medical_advice_and_guarantees(self):
        self.assertIn("Do not give medical advice", SYSTEM_PROMPT)
        self.assertIn("Do not promise or guarantee results", SYSTEM_PROMPT)

    def test_the_library_is_grouped_by_muscle(self):
        rendered = format_exercise_library(self.library)

        self.assertIn("Chest: Bench Press", rendered)
        self.assertIn("Quadriceps: Barbell Squat", rendered)

    def test_the_prompt_includes_body_stats_when_set(self):
        """Age, gender, weight and height must reach the model."""
        self.profile.age = 28
        self.profile.sex = Sex.MALE
        self.profile.weight_kg = 82.5
        self.profile.height_cm = 180
        self.profile.save()

        prompt = build_initial_plan_prompt(self.profile, self.library)

        self.assertIn("28 years", prompt)
        self.assertIn("Gender: Male", prompt)
        self.assertIn("82.5 kg", prompt)
        self.assertIn("180 cm", prompt)

    def test_the_prompt_omits_body_stats_that_are_not_set(self):
        """An older profile without body stats must still build a valid prompt."""
        self.profile.age = None
        self.profile.weight_kg = None
        self.profile.height_cm = None
        self.profile.save()

        prompt = build_initial_plan_prompt(self.profile, self.library)

        self.assertNotIn("Age:", prompt)
        self.assertNotIn("Bodyweight:", prompt)
        self.assertIn("Goal:", prompt)  # the rest of the profile still renders

    def test_format_lifter_leads_with_body_stats(self):
        self.profile.age = 30
        self.profile.weight_kg = 75
        self.profile.height_cm = 175
        self.profile.save()

        block = format_lifter(self.profile)
        self.assertIn("Age: 30 years", block)
        self.assertIn("Bodyweight: 75", block)


class PlanSchemaTests(TestCase):
    """The Pydantic schema is the first gate: it guarantees structure and types.
    Malformed shapes are rejected here, at parse time, before our code runs."""

    def test_a_well_formed_plan_parses(self):
        model = WorkoutPlanSchema.model_validate(valid_plan(days=3))
        self.assertEqual(model.plan_name, "Beginner Full Body")
        self.assertEqual(len(model.days), 3)

    def test_a_non_object_is_rejected(self):
        with self.assertRaises(PydanticValidationError):
            WorkoutPlanSchema.model_validate(["not", "a", "plan"])

    def test_a_missing_plan_name_is_rejected(self):
        plan = valid_plan()
        del plan["plan_name"]
        with self.assertRaises(PydanticValidationError):
            WorkoutPlanSchema.model_validate(plan)

    def test_days_must_be_a_list(self):
        plan = valid_plan()
        plan["days"] = "Monday, Wednesday, Friday"
        with self.assertRaises(PydanticValidationError):
            WorkoutPlanSchema.model_validate(plan)

    def test_non_integer_sets_are_rejected(self):
        plan = valid_plan(days=1)
        plan["days"][0]["exercises"][0]["sets"] = "three"
        with self.assertRaises(PydanticValidationError):
            WorkoutPlanSchema.model_validate(plan)

    def test_a_boolean_is_not_accepted_as_a_set_count(self):
        """StrictInt: in plain Python True == 1, so bool must be rejected."""
        plan = valid_plan(days=1)
        plan["days"][0]["exercises"][0]["sets"] = True
        with self.assertRaises(PydanticValidationError):
            WorkoutPlanSchema.model_validate(plan)

    def test_unknown_keys_from_the_model_are_dropped(self):
        plan = valid_plan(days=1)
        plan["injected_field"] = "should not be stored"
        plan["days"][0]["exercises"][0]["price"] = 9.99

        model = WorkoutPlanSchema.model_validate(plan)

        self.assertFalse(hasattr(model, "injected_field"))
        self.assertFalse(hasattr(model.days[0].exercises[0], "price"))


class PlanBusinessRuleTests(TestCase):
    """validate_plan enforces the rules the static schema cannot: day count,
    value ranges, non-empty text. It runs on an already-parsed schema object."""

    def test_a_well_formed_plan_passes(self):
        cleaned = validate_plan(plan_schema(days=3), expected_days=3)

        self.assertEqual(cleaned["plan_name"], "Beginner Full Body")
        self.assertEqual(len(cleaned["days"]), 3)

    def test_an_empty_plan_name_is_rejected(self):
        with self.assertRaises(PlanValidationError):
            validate_plan(plan_schema(plan_name="   "), expected_days=3)

    def test_the_wrong_number_of_days_is_rejected(self):
        """Asking for 4 days and getting 3 is a failure, not a suggestion."""
        with self.assertRaises(PlanValidationError):
            validate_plan(plan_schema(days=3), expected_days=4)

    def test_a_day_with_no_exercises_is_rejected(self):
        model = plan_schema(days=1)
        model.days[0].exercises = []
        with self.assertRaises(PlanValidationError):
            validate_plan(model, expected_days=1)

    def test_an_exercise_with_no_name_is_rejected(self):
        model = plan_schema(days=1)
        model.days[0].exercises[0].exercise = ""
        with self.assertRaises(PlanValidationError):
            validate_plan(model, expected_days=1)

    def test_zero_sets_are_rejected(self):
        model = plan_schema(days=1)
        model.days[0].exercises[0].sets = 0
        with self.assertRaises(PlanValidationError):
            validate_plan(model, expected_days=1)

    def test_an_absurd_set_count_is_rejected(self):
        model = plan_schema(days=1)
        model.days[0].exercises[0].sets = 500
        with self.assertRaises(PlanValidationError):
            validate_plan(model, expected_days=1)

    def test_an_empty_rep_range_is_rejected(self):
        model = plan_schema(days=1)
        model.days[0].exercises[0].rep_range = ""
        with self.assertRaises(PlanValidationError):
            validate_plan(model, expected_days=1)

    def test_overlong_text_is_truncated_not_rejected(self):
        cleaned = validate_plan(plan_schema(plan_name="x" * 5000), expected_days=3)
        self.assertLessEqual(len(cleaned["plan_name"]), 120)

    def test_the_cleaned_output_is_a_plain_dict_for_storage(self):
        cleaned = validate_plan(plan_schema(days=1), expected_days=1)
        self.assertIsInstance(cleaned, dict)
        self.assertIsInstance(cleaned["days"], list)


@override_settings(OPENAI_API_KEY="test-key-not-real")
class PlanGenerationServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.profile = UserProfile.objects.create(user=self.alice, days_per_week=3)

    def test_a_valid_response_is_saved_as_the_active_plan(self):
        with mock_ai_response(valid_plan(days=3)):
            plan = generate_initial_plan(self.alice)

        self.assertTrue(plan.is_active)
        self.assertEqual(plan.user, self.alice)
        self.assertEqual(plan.plan_json["plan_name"], "Beginner Full Body")
        self.assertEqual(len(plan.plan_json["days"]), 3)

    def test_the_profile_is_snapshotted_onto_the_plan(self):
        self.profile.goal = Goal.LOSE_WEIGHT
        self.profile.session_duration = 45
        self.profile.save()

        with mock_ai_response(valid_plan(days=3)):
            plan = generate_initial_plan(self.alice)

        self.assertEqual(plan.goal, Goal.LOSE_WEIGHT)
        self.assertEqual(plan.session_duration, 45)

    def test_an_initial_plan_has_an_empty_analytics_snapshot(self):
        with mock_ai_response(valid_plan(days=3)):
            plan = generate_initial_plan(self.alice)

        self.assertEqual(plan.analytics_snapshot, {})

    def test_generating_a_new_plan_deactivates_the_old_one(self):
        with mock_ai_response(valid_plan(days=3)):
            first = generate_initial_plan(self.alice)
        with mock_ai_response(valid_plan(days=3)):
            second = generate_initial_plan(self.alice)

        first.refresh_from_db()

        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(get_active_plan(self.alice), second)

    def test_old_plans_are_archived_not_deleted(self):
        with mock_ai_response(valid_plan(days=3)):
            generate_initial_plan(self.alice)
        with mock_ai_response(valid_plan(days=3)):
            generate_initial_plan(self.alice)

        self.assertEqual(get_plan_history(self.alice).count(), 2)

    def test_the_requested_number_of_days_follows_the_profile(self):
        self.profile.days_per_week = 5
        self.profile.save()

        with mock_ai_response(valid_plan(days=5)):
            plan = generate_initial_plan(self.alice)

        self.assertEqual(len(plan.plan_json["days"]), 5)

    def test_a_plan_with_the_wrong_day_count_is_not_saved(self):
        """The model returned 3 days when 5 were asked for. Reject it."""
        self.profile.days_per_week = 5
        self.profile.save()

        with mock_ai_response(valid_plan(days=3)):
            with self.assertRaises(PlanGenerationError):
                generate_initial_plan(self.alice)

        self.assertEqual(WorkoutPlan.objects.count(), 0)

    def test_a_business_invalid_plan_is_not_saved(self):
        """Schema-valid (empty exercise list is allowed by the schema) but
        rejected by the business rules — must not be stored."""
        broken = valid_plan(days=3)
        broken["days"][0]["exercises"] = []

        with mock_ai_response(broken):
            with self.assertRaises(PlanGenerationError):
                generate_initial_plan(self.alice)

        self.assertEqual(WorkoutPlan.objects.count(), 0)

    def test_a_provider_outage_produces_a_readable_error(self):
        with patch(
            "ai_planner.services._call_model",
            side_effect=PlanGenerationError(
                "Workout plan generation is temporarily unavailable. Please try again."
            ),
        ):
            with self.assertRaises(PlanGenerationError) as caught:
                generate_initial_plan(self.alice)

        message = str(caught.exception)
        self.assertIn("temporarily unavailable", message)
        # The user must never see technical internals or anything key-shaped.
        self.assertNotIn("api_key", message.lower())
        self.assertNotIn("openai", message.lower())

    def test_a_failed_generation_leaves_the_existing_plan_active(self):
        with mock_ai_response(valid_plan(days=3)):
            original = generate_initial_plan(self.alice)

        with failing_ai_call():
            with self.assertRaises(PlanGenerationError):
                generate_initial_plan(self.alice)

        original.refresh_from_db()
        self.assertTrue(original.is_active)  # not left plan-less


@override_settings(OPENAI_API_KEY="test-key-not-real")
class CallModelTests(TestCase):
    """The structured-output layer: _call_model turns a client response into a
    parsed schema, or a user-safe error."""

    def _client_returning(self, message):
        completion = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        client = MagicMock()
        client.chat.completions.parse.return_value = completion
        return client

    def test_a_parsed_plan_is_returned(self):
        message = SimpleNamespace(refusal=None, parsed=plan_schema(days=3))
        client = self._client_returning(message)

        with patch("ai_planner.services._get_client", return_value=client):
            result = _call_model("a prompt")

        self.assertIsInstance(result, WorkoutPlanSchema)
        self.assertEqual(result.plan_name, "Beginner Full Body")

    def test_the_pydantic_schema_is_sent_as_the_response_format(self):
        message = SimpleNamespace(refusal=None, parsed=plan_schema(days=3))
        client = self._client_returning(message)

        with patch("ai_planner.services._get_client", return_value=client):
            _call_model("a prompt")

        _, kwargs = client.chat.completions.parse.call_args
        self.assertIs(kwargs["response_format"], WorkoutPlanSchema)

    def test_a_refusal_is_turned_into_a_user_safe_error(self):
        message = SimpleNamespace(refusal="I can't help with that.", parsed=None)
        client = self._client_returning(message)

        with patch("ai_planner.services._get_client", return_value=client):
            with self.assertRaises(PlanGenerationError):
                _call_model("a prompt")

    def test_no_parsed_object_is_turned_into_a_user_safe_error(self):
        message = SimpleNamespace(refusal=None, parsed=None)
        client = self._client_returning(message)

        with patch("ai_planner.services._get_client", return_value=client):
            with self.assertRaises(PlanGenerationError):
                _call_model("a prompt")

    def test_an_api_exception_is_turned_into_a_user_safe_error(self):
        client = MagicMock()
        client.chat.completions.parse.side_effect = RuntimeError("network down")

        with patch("ai_planner.services._get_client", return_value=client):
            with self.assertRaises(PlanGenerationError) as caught:
                _call_model("a prompt")

        # The raw technical error must not surface to the user.
        self.assertNotIn("network down", str(caught.exception))


@override_settings(OPENAI_API_KEY="")
class MissingApiKeyTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        UserProfile.objects.create(user=self.alice)

    def test_generation_without_a_key_fails_cleanly(self):
        with self.assertRaises(PlanGenerationError) as caught:
            generate_initial_plan(self.alice)

        self.assertIn("not configured", str(caught.exception))
        self.assertEqual(WorkoutPlan.objects.count(), 0)


@override_settings(OPENAI_API_KEY="test-key-not-real")
class PlanViewTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        UserProfile.objects.create(user=self.alice, days_per_week=3)
        UserProfile.objects.create(user=self.bob, days_per_week=3)
        self.client.force_login(self.alice)

    def test_plan_pages_require_login(self):
        self.client.logout()

        for url in (
            reverse("ai_planner:current_plan"),
            reverse("ai_planner:generate_plan"),
        ):
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_no_plan_yet_shows_a_prompt(self):
        response = self.client.get(reverse("ai_planner:current_plan"))

        self.assertContains(response, "No workout plan yet")

    def test_generating_a_plan_through_the_view(self):
        with mock_ai_response(valid_plan(days=3)):
            response = self.client.post(reverse("ai_planner:generate_plan"))

        self.assertRedirects(response, reverse("ai_planner:current_plan"))
        self.assertEqual(WorkoutPlan.objects.filter(user=self.alice).count(), 1)

    def test_the_plan_page_renders_the_exercises(self):
        with mock_ai_response(valid_plan(days=3)):
            self.client.post(reverse("ai_planner:generate_plan"))

        response = self.client.get(reverse("ai_planner:current_plan"))

        self.assertContains(response, "Beginner Full Body")
        self.assertContains(response, "Barbell Squat")
        self.assertContains(response, "6-8")

    def test_a_failure_shows_a_readable_message_not_a_traceback(self):
        with failing_ai_call():
            response = self.client.post(
                reverse("ai_planner:generate_plan"), follow=True
            )

        self.assertContains(response, "Please try again")
        self.assertEqual(WorkoutPlan.objects.count(), 0)

    def test_the_disclaimer_is_shown(self):
        response = self.client.get(reverse("ai_planner:generate_plan"))

        self.assertContains(response, "not medical advice")

    def test_a_saved_plan_can_be_reopened(self):
        with mock_ai_response(valid_plan(days=3)):
            plan = generate_initial_plan(self.alice)

        response = self.client.get(reverse("ai_planner:plan_detail", args=[plan.id]))
        self.assertContains(response, "Beginner Full Body")

    def test_bob_cannot_open_alices_plan(self):
        with mock_ai_response(valid_plan(days=3)):
            plan = generate_initial_plan(self.alice)

        self.client.force_login(self.bob)
        response = self.client.get(reverse("ai_planner:plan_detail", args=[plan.id]))

        self.assertEqual(response.status_code, 404)

    def test_bob_does_not_see_alices_plan_on_his_own_page(self):
        with mock_ai_response(valid_plan(days=3)):
            generate_initial_plan(self.alice)

        self.client.force_login(self.bob)
        response = self.client.get(reverse("ai_planner:current_plan"))

        self.assertNotContains(response, "Beginner Full Body")
        self.assertContains(response, "No workout plan yet")

    def test_ai_generated_text_is_escaped_not_rendered_as_html(self):
        """AI output is never marked safe."""
        hostile = valid_plan(days=1)
        hostile["plan_name"] = "<script>alert('xss')</script>"

        UserProfile.objects.filter(user=self.alice).update(days_per_week=1)

        with mock_ai_response(hostile):
            self.client.post(reverse("ai_planner:generate_plan"))

        response = self.client.get(reverse("ai_planner:current_plan"))

        self.assertNotContains(response, "<script>alert")
        self.assertContains(response, "&lt;script&gt;")


class ParsePlanFormTests(TestCase):
    """The edit form's POST data must rebuild the plan structure correctly,
    even with non-contiguous indices left by add/remove."""

    def test_a_simple_plan_is_parsed(self):
        post = {
            "plan_name": "My Plan",
            "summary": "A summary.",
            "day_0_name": "Push",
            "day_0_focus": "Chest",
            "day_0_ex_0_name": "Bench Press",
            "day_0_ex_0_sets": "4",
            "day_0_ex_0_reps": "6-8",
            "day_0_ex_0_notes": "Rest 3 min.",
        }
        plan = _parse_plan_form(post)

        self.assertEqual(plan["plan_name"], "My Plan")
        self.assertEqual(len(plan["days"]), 1)
        self.assertEqual(plan["days"][0]["day_name"], "Push")
        self.assertEqual(plan["days"][0]["exercises"][0]["sets"], 4)

    def test_index_gaps_from_removed_rows_are_handled(self):
        # Exercise index 1 was removed, leaving 0 and 2.
        post = {
            "plan_name": "P", "summary": "",
            "day_0_name": "Day", "day_0_focus": "",
            "day_0_ex_0_name": "A", "day_0_ex_0_sets": "3", "day_0_ex_0_reps": "8", "day_0_ex_0_notes": "",
            "day_0_ex_2_name": "B", "day_0_ex_2_sets": "3", "day_0_ex_2_reps": "8", "day_0_ex_2_notes": "",
        }
        plan = _parse_plan_form(post)
        names = [e["exercise"] for e in plan["days"][0]["exercises"]]
        self.assertEqual(names, ["A", "B"])

    def test_blank_exercise_rows_are_dropped(self):
        post = {
            "plan_name": "P", "summary": "",
            "day_0_name": "Day", "day_0_focus": "",
            "day_0_ex_0_name": "A", "day_0_ex_0_sets": "3", "day_0_ex_0_reps": "8", "day_0_ex_0_notes": "",
            "day_0_ex_1_name": "  ", "day_0_ex_1_sets": "3", "day_0_ex_1_reps": "8", "day_0_ex_1_notes": "",
        }
        plan = _parse_plan_form(post)
        self.assertEqual(len(plan["days"][0]["exercises"]), 1)

    def test_non_numeric_sets_become_invalid(self):
        post = {
            "plan_name": "P", "summary": "",
            "day_0_name": "Day", "day_0_focus": "",
            "day_0_ex_0_name": "A", "day_0_ex_0_sets": "abc", "day_0_ex_0_reps": "8", "day_0_ex_0_notes": "",
        }
        plan = _parse_plan_form(post)
        self.assertEqual(plan["days"][0]["exercises"][0]["sets"], -1)  # rejected by validation


@override_settings(OPENAI_API_KEY="test-key-not-real")
class EditPlanTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        UserProfile.objects.create(user=self.alice, days_per_week=3)
        UserProfile.objects.create(user=self.bob, days_per_week=3)
        with mock_ai_response(valid_plan(days=3)):
            self.plan = generate_initial_plan(self.alice)
        self.client.force_login(self.alice)

    def _edited(self, **overrides):
        data = {
            "plan_name": "Edited Plan",
            "summary": "Edited summary.",
            "day_0_name": "Upper",
            "day_0_focus": "Push and pull",
            "day_0_ex_0_name": "Overhead Press",
            "day_0_ex_0_sets": "5",
            "day_0_ex_0_reps": "3-5",
            "day_0_ex_0_notes": "Brace hard.",
        }
        data.update(overrides)
        return data

    # --- service ---

    def test_editing_updates_the_plan(self):
        new_json = {
            "plan_name": "Edited Plan",
            "summary": "New summary.",
            "days": [
                {"day_number": 1, "day_name": "Upper", "focus": "Push",
                 "exercises": [{"exercise": "Bench Press", "sets": 5, "rep_range": "3-5", "notes": ""}]},
            ],
        }
        save_edited_plan(self.alice, self.plan.id, new_json)

        self.plan.refresh_from_db()
        self.assertEqual(self.plan.plan_json["plan_name"], "Edited Plan")
        self.assertEqual(len(self.plan.plan_json["days"]), 1)  # day count can change

    def test_editing_stays_active(self):
        new_json = {
            "plan_name": "Edited", "summary": "",
            "days": [{"day_number": 1, "day_name": "A", "focus": "",
                      "exercises": [{"exercise": "Squat", "sets": 3, "rep_range": "5", "notes": ""}]}],
        }
        save_edited_plan(self.alice, self.plan.id, new_json)
        self.plan.refresh_from_db()
        self.assertTrue(self.plan.is_active)

    def test_an_invalid_edit_is_rejected(self):
        broken = {
            "plan_name": "", "summary": "",  # empty name
            "days": [{"day_number": 1, "day_name": "A", "focus": "",
                      "exercises": [{"exercise": "Squat", "sets": 3, "rep_range": "5", "notes": ""}]}],
        }
        with self.assertRaises(PlanValidationError):
            save_edited_plan(self.alice, self.plan.id, broken)

    def test_zero_sets_edit_is_rejected(self):
        broken = {
            "plan_name": "P", "summary": "",
            "days": [{"day_number": 1, "day_name": "A", "focus": "",
                      "exercises": [{"exercise": "Squat", "sets": 0, "rep_range": "5", "notes": ""}]}],
        }
        with self.assertRaises(PlanValidationError):
            save_edited_plan(self.alice, self.plan.id, broken)

    def test_a_user_cannot_edit_another_users_plan(self):
        with self.assertRaises(PlanGenerationError):
            save_edited_plan(self.bob, self.plan.id, {"plan_name": "hax", "summary": "", "days": []})
        self.plan.refresh_from_db()
        self.assertNotEqual(self.plan.plan_json["plan_name"], "hax")

    # --- view ---

    def test_the_edit_page_renders_the_plan(self):
        response = self.client.get(reverse("ai_planner:edit_plan", args=[self.plan.id]))
        self.assertContains(response, "Beginner Full Body")  # current plan name in a field

    def test_editing_through_the_view_saves_and_redirects(self):
        response = self.client.post(
            reverse("ai_planner:edit_plan", args=[self.plan.id]), self._edited()
        )
        self.assertRedirects(response, reverse("ai_planner:plan_detail", args=[self.plan.id]))

        self.plan.refresh_from_db()
        self.assertEqual(self.plan.plan_json["plan_name"], "Edited Plan")
        self.assertEqual(self.plan.plan_json["days"][0]["exercises"][0]["exercise"], "Overhead Press")

    def test_an_invalid_edit_reshows_the_form_without_saving(self):
        response = self.client.post(
            reverse("ai_planner:edit_plan", args=[self.plan.id]),
            self._edited(plan_name=""),  # empty name
        )
        self.assertEqual(response.status_code, 200)  # re-rendered, not redirected
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.plan_json["plan_name"], "Beginner Full Body")  # unchanged

    def test_bob_cannot_open_alices_edit_page(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("ai_planner:edit_plan", args=[self.plan.id]))
        self.assertEqual(response.status_code, 404)

    def test_the_plan_page_shows_an_edit_button(self):
        response = self.client.get(reverse("ai_planner:current_plan"))
        self.assertContains(response, "Edit this plan")


@override_settings(OPENAI_API_KEY="test-key-not-real")
class DeletePlanTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        UserProfile.objects.create(user=self.alice, days_per_week=3)
        UserProfile.objects.create(user=self.bob, days_per_week=3)

    def _make_plan(self, user):
        return WorkoutPlan.objects.create(
            user=user,
            goal=Goal.BUILD_MUSCLE,
            days_per_week=3,
            experience_level=ExperienceLevel.BEGINNER,
            workout_location=WorkoutLocation.COMMERCIAL_GYM,
            session_duration=60,
            plan_json={"plan_name": "A Plan", "days": []},
            is_active=True,
        )

    # --- service ---

    def test_delete_removes_the_users_plan(self):
        plan = self._make_plan(self.alice)

        self.assertTrue(delete_plan(self.alice, plan.id))
        self.assertFalse(WorkoutPlan.objects.filter(pk=plan.id).exists())

    def test_delete_returns_false_for_an_unknown_plan(self):
        self.assertFalse(delete_plan(self.alice, 999999))

    def test_a_user_cannot_delete_another_users_plan(self):
        bob_plan = self._make_plan(self.bob)

        self.assertFalse(delete_plan(self.alice, bob_plan.id))
        self.assertTrue(WorkoutPlan.objects.filter(pk=bob_plan.id).exists())

    # --- view ---

    def test_deleting_through_the_view_redirects_and_removes_the_plan(self):
        plan = self._make_plan(self.alice)
        self.client.force_login(self.alice)

        response = self.client.post(reverse("ai_planner:delete_plan", args=[plan.id]))

        self.assertRedirects(response, reverse("ai_planner:current_plan"))
        self.assertFalse(WorkoutPlan.objects.filter(pk=plan.id).exists())

    def test_delete_requires_post_not_get(self):
        """A GET must not delete — otherwise a link or prefetch could destroy data."""
        plan = self._make_plan(self.alice)
        self.client.force_login(self.alice)

        response = self.client.get(reverse("ai_planner:delete_plan", args=[plan.id]))

        self.assertEqual(response.status_code, 405)  # method not allowed
        self.assertTrue(WorkoutPlan.objects.filter(pk=plan.id).exists())

    def test_delete_requires_login(self):
        plan = self._make_plan(self.alice)

        response = self.client.post(reverse("ai_planner:delete_plan", args=[plan.id]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(WorkoutPlan.objects.filter(pk=plan.id).exists())

    def test_bob_cannot_delete_alices_plan_through_the_view(self):
        plan = self._make_plan(self.alice)
        self.client.force_login(self.bob)

        self.client.post(reverse("ai_planner:delete_plan", args=[plan.id]))

        self.assertTrue(WorkoutPlan.objects.filter(pk=plan.id).exists())

    def test_deleting_the_active_plan_leaves_the_user_with_none(self):
        plan = self._make_plan(self.alice)
        self.client.force_login(self.alice)

        self.client.post(reverse("ai_planner:delete_plan", args=[plan.id]))

        self.assertIsNone(get_active_plan(self.alice))
        response = self.client.get(reverse("ai_planner:current_plan"))
        self.assertContains(response, "No workout plan yet")

    def test_the_plan_page_shows_a_delete_button(self):
        self._make_plan(self.alice)
        self.client.force_login(self.alice)

        response = self.client.get(reverse("ai_planner:current_plan"))
        self.assertContains(response, "Delete this plan")
