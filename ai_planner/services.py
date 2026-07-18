"""AI workout plan generation.

The only place in the codebase that talks to an AI provider. Everything else
consumes the validated plan_json that comes out of here.

DEVIATION FROM SPEC: the specification names the Anthropic Claude API. The
project owner supplied an OpenAI key, so this uses the OpenAI SDK. The provider
is contained entirely within this module.
"""

import logging

from django.conf import settings
from django.db import transaction

from users.services import get_or_create_profile
from workouts.services import get_all_exercises, get_exercises_grouped_by_muscle

from .models import WorkoutPlan
from .prompts import SYSTEM_PROMPT, build_initial_plan_prompt
from pydantic import ValidationError as PydanticValidationError

from .validators import PlanValidationError, WorkoutPlanSchema, validate_plan

logger = logging.getLogger(__name__)

# What the user sees when anything goes wrong. Technical detail goes to the log,
# never to the page — and never anywhere near the API key.
GENERIC_FAILURE_MESSAGE = (
    "Workout plan generation is temporarily unavailable. Please try again."
)


class PlanGenerationError(Exception):
    """Raised with a message that is safe to show a user."""


def _get_client():
    """Build the AI client, or fail loudly if the key is missing."""
    if not settings.OPENAI_API_KEY:
        logger.error("AI plan generation attempted with no API key configured.")
        raise PlanGenerationError(
            "The workout planner is not configured yet. Please add an API key."
        )

    # Imported here rather than at module load so the app still boots (and the
    # test suite still runs) without the SDK's import-time environment checks.
    from openai import OpenAI

    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
    )


def _call_model(prompt):
    """Send the prompt and return a parsed WorkoutPlanSchema.

    Uses OpenAI structured outputs: the Pydantic schema is handed to the SDK as
    the response_format, so the model is constrained to return JSON of that
    shape and the SDK parses and type-checks it for us. We get a typed object,
    not raw text — malformed JSON and wrong types can no longer reach us.

    Any provider failure or refusal is logged and re-raised as a user-safe error.
    """
    client = _get_client()

    try:
        completion = client.chat.completions.parse(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format=WorkoutPlanSchema,
            temperature=0.7,
        )
    except PlanGenerationError:
        raise
    except Exception as exc:
        # Log the technical cause; show the user something readable.
        logger.exception("AI provider call failed: %s", exc.__class__.__name__)
        raise PlanGenerationError(GENERIC_FAILURE_MESSAGE) from exc

    message = completion.choices[0].message

    # A structured-output model can decline the request. That arrives as a
    # refusal string rather than a parsed plan.
    if getattr(message, "refusal", None):
        logger.error("AI refused to generate a plan: %s", message.refusal[:300])
        raise PlanGenerationError(GENERIC_FAILURE_MESSAGE)

    if message.parsed is None:
        logger.error("AI returned no parsable plan.")
        raise PlanGenerationError(GENERIC_FAILURE_MESSAGE)

    return message.parsed


def _warn_about_unloggable_exercises(plan_json):
    """Log any prescribed exercise that is not in the seeded library.

    The prompt tells the model to stay inside the library, because an exercise
    the app cannot log is an exercise the user cannot track or chart. This does
    not reject the plan — a slightly-off name is still a usable plan — but it
    must be visible rather than silent.
    """
    known = {name.casefold() for name in get_all_exercises().values_list("name", flat=True)}

    prescribed = {
        exercise["exercise"]
        for day in plan_json["days"]
        for exercise in day["exercises"]
    }
    unknown = sorted(name for name in prescribed if name.casefold() not in known)

    if unknown:
        logger.warning(
            "AI plan prescribed %d exercise(s) outside the library: %s",
            len(unknown),
            ", ".join(unknown),
        )


@transaction.atomic
def _save_plan(user, profile, plan_json, analytics_snapshot=None):
    """Store the validated plan and make it the active one.

    Previous plans are archived, never deleted, so history survives. The
    deactivate-then-create pair runs in one transaction, so the database's
    one_active_plan_per_user constraint can never be violated part-way.
    """
    WorkoutPlan.objects.filter(user=user, is_active=True).update(is_active=False)

    return WorkoutPlan.objects.create(
        user=user,
        goal=profile.goal,
        days_per_week=profile.days_per_week,
        experience_level=profile.experience_level,
        workout_location=profile.workout_location,
        session_duration=profile.session_duration,
        plan_json=plan_json,
        analytics_snapshot=analytics_snapshot or {},
        is_active=True,
    )


def generate_initial_plan(user):
    """Generate a plan from the user's profile alone.

    Used when the user has no meaningful workout history. Phase 12 adds the
    adaptive variant that also feeds in calculated analytics.
    """
    profile = get_or_create_profile(user)

    prompt = build_initial_plan_prompt(profile, get_exercises_grouped_by_muscle())
    plan_model = _call_model(prompt)

    try:
        plan_json = validate_plan(plan_model, expected_days=profile.days_per_week)
    except PlanValidationError as exc:
        # The model produced JSON, but not a plan we are willing to store.
        logger.error("AI plan failed validation: %s", exc)
        raise PlanGenerationError(
            "The generated plan did not come back in a usable form. Please try again."
        ) from exc

    _warn_about_unloggable_exercises(plan_json)

    plan = _save_plan(user, profile, plan_json)
    logger.info("Generated workout plan %s for user %s", plan.id, user.id)
    return plan


def get_active_plan(user):
    """The user's current plan, or None."""
    return WorkoutPlan.objects.filter(user=user, is_active=True).first()


def get_plan_history(user):
    """Every plan this user has ever had, newest first."""
    return WorkoutPlan.objects.filter(user=user).order_by("-created_at")


def get_user_plan(user, plan_id):
    """One of this user's plans, or None if it is not theirs."""
    return WorkoutPlan.objects.filter(pk=plan_id, user=user).first()


def delete_plan(user, plan_id):
    """Permanently delete one of the user's plans (active or archived).

    Scoped to the user, so a guessed id cannot delete someone else's plan.
    Returns True if a plan was deleted, False if none matched.
    """
    deleted_count, _ = WorkoutPlan.objects.filter(pk=plan_id, user=user).delete()
    return deleted_count > 0


@transaction.atomic
def save_edited_plan(user, plan_id, plan_dict):
    """Save a user's manual edits to one of their plans.

    The submitted plan goes through the same validation as an AI plan (so a
    hand-edited plan can never store something malformed), but the day count is
    not pinned to the profile — the user may pick any 1..7 days.

    Raises PlanValidationError on invalid input, or PlanGenerationError (with a
    user-safe message) if the plan is not theirs. Returns the updated plan.
    """
    plan = get_user_plan(user, plan_id)
    if plan is None:
        raise PlanGenerationError("That plan could not be found.")

    try:
        model = WorkoutPlanSchema.model_validate(plan_dict)
        cleaned = validate_plan(model, expected_days=None)
    except PydanticValidationError as exc:
        # Types were wrong (e.g. sets not a whole number).
        raise PlanValidationError("Please check the values you entered.") from exc

    plan.plan_json = cleaned
    plan.save(update_fields=["plan_json"])
    logger.info("User %s edited workout plan %s", user.id, plan.id)
    return plan
