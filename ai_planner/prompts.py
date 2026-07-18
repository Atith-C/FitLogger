"""Prompt construction for workout plan generation.

Prompts live here, never inside a view or tangled into the API call. The
service layer imports these builders and passes the result to the model.

The JSON contract is fixed by the specification. Richer plans are achieved by
demanding more of the EXISTING fields — progression in `summary`, rationale in
`focus`, rest periods and cues in `notes` — rather than by inventing new keys.
"""

import json

# The exact JSON contract the model must return. Kept as a literal string so
# the shape shown to the model and the shape enforced by validators.py cannot
# drift apart silently.
PLAN_JSON_SCHEMA = """{
  "plan_name": "string",
  "summary": "string",
  "days": [
    {
      "day_number": 1,
      "day_name": "string",
      "focus": "string",
      "exercises": [
        {
          "exercise": "string",
          "sets": 3,
          "rep_range": "6-8",
          "notes": "string"
        }
      ]
    }
  ]
}"""

SYSTEM_PROMPT = (
    "You are an experienced strength coach writing training programmes for a "
    "workout logging app.\n\n"
    "You write like a coach who knows what they are doing: specific loads, "
    "specific progression, specific rest. You never pad a plan with filler "
    "exercises, and you never write a generic template that would suit anyone.\n\n"
    "Rules you must follow:\n"
    "- Return ONLY valid JSON matching the requested schema. No prose, no markdown.\n"
    "- Do not give medical advice, diagnose injuries, or discuss health conditions.\n"
    "- Do not promise or guarantee results of any kind.\n"
    "- Do not invent exercises outside the provided library.\n"
    "- Never describe the plan as perfect, optimal, scientific, or guaranteed."
)


def format_lifter(profile):
    """The LIFTER block: body stats first (when known), then training profile.

    Age, bodyweight and height let the model reason about bodyweight-relative
    loading and age-appropriate volume. They are optional — an older profile may
    not have them — so each is included only when set.
    """
    lines = []
    if profile.age is not None:
        lines.append(f"- Age: {profile.age} years")
    if profile.sex:
        lines.append(f"- Gender: {profile.get_sex_display()}")
    if profile.weight_kg is not None:
        lines.append(f"- Bodyweight: {profile.weight_kg} kg")
    if profile.height_cm is not None:
        lines.append(f"- Height: {profile.height_cm} cm")

    lines.append(f"- Goal: {profile.get_goal_display()}")
    lines.append(f"- Experience: {profile.get_experience_level_display()}")
    lines.append(f"- Training days per week: {profile.days_per_week}")
    lines.append(f"- Trains at: {profile.get_workout_location_display()}")
    lines.append(f"- Time per session: {profile.session_duration} minutes")
    return "\n".join(lines)


def format_exercise_library(exercises_by_group):
    """Render the seeded exercise library for inclusion in a prompt.

    The model may only prescribe exercises the user can actually log. An
    exercise outside this library cannot be recorded, charted, or progressed —
    so a plan containing one is a broken plan.
    """
    lines = []
    for group_name, exercises in exercises_by_group.items():
        names = ", ".join(exercise.name for exercise in exercises)
        lines.append(f"{group_name}: {names}")
    return "\n".join(lines)


# Shared quality bar. Both the initial and adaptive prompts hold to it, so the
# two cannot drift into producing plans of different calibre.
QUALITY_REQUIREMENTS = """WHAT MAKES THIS PLAN GOOD (follow all of it)

Structure:
- Every training day must open with its hardest compound movement, while the
  lifter is fresh. Isolation work comes last.
- Balance pushing and pulling across the week. Do not build a day that is six
  chest exercises.
- Do not repeat the same movement pattern on consecutive days.
- Fit the work honestly into the session length: roughly 4-7 exercises for a
  60 minute session, fewer if shorter.

Prescription:
- Compound lifts: lower reps, more sets (e.g. 4 x 5-8).
- Isolation lifts: higher reps, fewer sets (e.g. 3 x 10-15).
- Match total volume to experience. A beginner does not need 25 sets a session.

The "notes" field for each exercise must be genuinely useful, not filler.
Include the rest period, and ONE specific execution cue or loading instruction.
Good: "Rest 3 min. Leave 2 reps in reserve on every set — do not grind."
Bad: "Focus on good form and control the weight."

The "focus" field for each day must say what that day trains and why it is
ordered the way it is. Not just "Upper body".

The "summary" field must state the PROGRESSION SCHEME in plain language: how
the lifter adds weight or reps week to week, and what to do when they stall.
This is the single most important part of the plan. Be concrete — give numbers.
Bad: "Progressively overload over time."
Good: "Add 2.5 kg to the bar when you hit the top of the rep range on every set.
If you miss the same weight twice, drop 10% and build back up."
"""


def build_initial_plan_prompt(profile, exercises_by_group):
    """Prompt for a user with no meaningful workout history.

    The plan is built from their stated profile alone. Be honest about that
    limitation: with five facts about a person there is a floor on how
    personalised any plan can be. The adaptive prompt is where real
    personalisation happens.
    """
    library = format_exercise_library(exercises_by_group)

    return f"""Write a training programme for this person.

LIFTER
{format_lifter(profile)}

EXERCISE LIBRARY — you may ONLY prescribe exercises from this list, spelled
exactly as written. The app can only log and track these movements, so an
exercise outside this list is useless to the lifter.

{library}

{QUALITY_REQUIREMENTS}

HARD REQUIREMENTS
- EXACTLY {profile.days_per_week} training day(s). Not more, not fewer.
- Every day must contain at least one exercise.
- Every exercise name must appear verbatim in the library above.
- Exercises must be possible at a {profile.get_workout_location_display().lower()}.
- "sets" must be a whole number.
- "rep_range" must be a string such as "6-8" or "10-12".

Return ONLY this JSON structure, with no surrounding text:

{PLAN_JSON_SCHEMA}"""


def build_adaptive_plan_prompt(profile, analytics_summary, exercises_by_group):
    """Prompt for a user with enough history to adapt the plan to.

    The analytics were calculated by the application. The model is told to use
    them as context and explicitly NOT to recompute them.
    """
    library = format_exercise_library(exercises_by_group)
    metrics = json.dumps(analytics_summary, indent=2)

    return f"""Write an updated training programme for this person, informed by
their measured training data.

LIFTER
{format_lifter(profile)}

MEASURED TRAINING DATA
These metrics were calculated by the application from the lifter's logged
workouts. Treat them as fact. Do NOT recalculate them, restate them, or
question them.

{metrics}

HOW TO USE THE DATA
- Adherence well below 100% means the plan was too demanding to follow. Cut
  the plan back rather than reissuing one they already failed to complete.
- Adherence above 100% means they have capacity for more work.
- Where an exercise shows "potential_plateau": true, CHANGE the stimulus. Vary
  the rep range, adjust the volume, or swap in a different movement for the
  same muscle. Do not simply prescribe the same thing harder.
- Where an exercise is progressing, keep the progression running. Do not
  change what is working.

EXERCISE LIBRARY — you may ONLY prescribe exercises from this list, spelled
exactly as written.

{library}

{QUALITY_REQUIREMENTS}

HARD REQUIREMENTS
- EXACTLY {profile.days_per_week} training day(s).
- Every day must contain at least one exercise.
- Every exercise name must appear verbatim in the library above.
- "sets" must be a whole number.
- "rep_range" must be a string such as "6-8".
- The "summary" must ALSO explain, in plain language, what you changed from
  their previous training and why — referring to their actual numbers.

Return ONLY this JSON structure, with no surrounding text:

{PLAN_JSON_SCHEMA}"""
