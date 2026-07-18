"""Schema and validation for AI-generated workout plans.

Two layers, on purpose:

1. Pydantic models (WorkoutPlanSchema and friends) define the STRUCTURE. They
   are handed to the OpenAI SDK as the response_format, so the model is forced
   to return JSON matching this shape, and the SDK parses it into typed objects.
   Wrong types, missing fields and malformed JSON are caught here, before our
   code ever sees them.

2. validate_plan() enforces the BUSINESS RULES that a static schema cannot:
   the day count must match what this specific user asked for, values must sit
   in sane ranges, text is trimmed and length-capped. These depend on runtime
   context (the user's profile) so they cannot live in the schema.
"""

from pydantic import BaseModel, StrictInt

MAX_PLAN_NAME_LENGTH = 120
MAX_SUMMARY_LENGTH = 1500
MAX_DAY_NAME_LENGTH = 120
MAX_FOCUS_LENGTH = 200
MAX_EXERCISE_NAME_LENGTH = 100
MAX_REP_RANGE_LENGTH = 20
MAX_NOTES_LENGTH = 300
MAX_EXERCISES_PER_DAY = 15
MAX_SETS_PER_EXERCISE = 20
MAX_PLAN_DAYS = 7


# --------------------------------------------------------------------------
# Structure — the schema handed to OpenAI structured outputs
# --------------------------------------------------------------------------
#
# StrictInt on the integer fields so a JSON boolean cannot masquerade as a
# number (plain int would coerce True -> 1). No fields have defaults: OpenAI
# strict structured outputs requires every field to be present.


class PlanExerciseSchema(BaseModel):
    exercise: str
    sets: StrictInt
    rep_range: str
    notes: str


class PlanDaySchema(BaseModel):
    day_number: StrictInt
    day_name: str
    focus: str
    exercises: list[PlanExerciseSchema]


class WorkoutPlanSchema(BaseModel):
    plan_name: str
    summary: str
    days: list[PlanDaySchema]


# --------------------------------------------------------------------------
# Business rules
# --------------------------------------------------------------------------


class PlanValidationError(Exception):
    """The model returned well-formed JSON, but not a plan we will store."""


def _require_text(value, field, max_length):
    """A non-empty string, trimmed and length-capped.

    Pydantic guarantees value is a str; this enforces that it is not blank.
    """
    text = value.strip()
    if not text:
        raise PlanValidationError(f"'{field}' must not be empty.")
    return text[:max_length]


def validate_plan(plan, expected_days=None):
    """Apply business rules to a parsed WorkoutPlanSchema and return a clean dict.

    Structure and types are already guaranteed by Pydantic, so this checks only
    what the schema cannot: value ranges and non-empty text, plus the day count.

    expected_days pins the count for AI generation (which must honour the
    profile). It is left None for a manual edit, where the user may choose any
    number of days within 1..MAX_PLAN_DAYS.

    Returns the dict that gets stored in WorkoutPlan.plan_json.
    """
    if expected_days is not None and len(plan.days) != expected_days:
        raise PlanValidationError(
            f"The plan has {len(plan.days)} day(s) but {expected_days} were requested."
        )

    if not 1 <= len(plan.days) <= MAX_PLAN_DAYS:
        raise PlanValidationError(
            f"A plan must have between 1 and {MAX_PLAN_DAYS} day(s)."
        )

    return {
        "plan_name": _require_text(plan.plan_name, "plan_name", MAX_PLAN_NAME_LENGTH),
        "summary": plan.summary.strip()[:MAX_SUMMARY_LENGTH],
        "days": [_validate_day(day, position) for position, day in enumerate(plan.days, start=1)],
    }


def _validate_day(day, position):
    if not day.exercises:
        raise PlanValidationError(f"Day {position} must contain at least one exercise.")

    if len(day.exercises) > MAX_EXERCISES_PER_DAY:
        raise PlanValidationError(
            f"Day {position} has {len(day.exercises)} exercises, which is unreasonable."
        )

    # Trust our own ordering over the model's day_number, which models
    # sometimes duplicate or skip.
    day_number = day.day_number if day.day_number >= 1 else position

    return {
        "day_number": day_number,
        "day_name": _require_text(
            day.day_name or f"Day {position}", "day_name", MAX_DAY_NAME_LENGTH
        ),
        "focus": day.focus.strip()[:MAX_FOCUS_LENGTH],
        "exercises": [_validate_exercise(exercise) for exercise in day.exercises],
    }


def _validate_exercise(exercise):
    name = _require_text(exercise.exercise, "exercise", MAX_EXERCISE_NAME_LENGTH)

    if exercise.sets < 1 or exercise.sets > MAX_SETS_PER_EXERCISE:
        raise PlanValidationError(
            f"'sets' for {name} must be between 1 and {MAX_SETS_PER_EXERCISE}."
        )

    return {
        "exercise": name,
        "sets": exercise.sets,
        "rep_range": _require_text(exercise.rep_range, "rep_range", MAX_REP_RANGE_LENGTH),
        "notes": exercise.notes.strip()[:MAX_NOTES_LENGTH],
    }
