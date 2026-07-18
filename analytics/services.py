"""Workout analytics.

Every metric here is calculated deterministically in Python. The AI planner
consumes these numbers as context — it never recalculates them.

pandas is used where tabular grouping genuinely helps (per-session aggregates,
weekly rollups) and deliberately avoided for single-record lookups.
"""

import logging
from datetime import timedelta

import pandas as pd
from django.utils import timezone

from users.models import ActivityLevel, BodyMeasurement, Sex
from workouts.models import WorkoutSession, WorkoutSet

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Tunable constants — no magic numbers scattered through the code
# --------------------------------------------------------------------------

# Epley coefficient: estimated_1rm = weight * (1 + reps / EPLEY_DIVISOR)
EPLEY_DIVISOR = 30

# How many recent completed sessions the trend and plateau checks look at.
RECENT_SESSION_WINDOW = 4

# The plateau heuristic needs at least this many sessions before it will say
# anything at all. Fewer than this is not enough signal.
PLATEAU_MIN_SESSIONS = 4

# If estimated 1RM has improved by less than this percentage across the recent
# window, we flag a *potential* plateau. This is an application heuristic, not
# a scientific or medical claim.
PLATEAU_IMPROVEMENT_THRESHOLD_PERCENT = 2.0

# How many weeks of history the frequency and adherence charts cover.
DEFAULT_WEEKS_ANALYSED = 12


def estimate_one_rep_max(weight, reps):
    """Epley formula: estimated_1rm = weight * (1 + reps / 30).

    This is an *estimate* derived from a submaximal set, not a measured 1RM.
    The UI must always label it "Estimated 1RM".
    """
    return float(weight) * (1 + float(reps) / EPLEY_DIVISOR)


# --------------------------------------------------------------------------
# Base data
# --------------------------------------------------------------------------


def _exercise_sets_dataframe(user, exercise):
    """Every set this user has logged for one exercise, in completed sessions.

    Returns a DataFrame with one row per set:
        session_id, date, weight, reps, volume, estimated_1rm

    Returns an empty DataFrame (with those columns) when there is no data, so
    callers never have to special-case a missing frame.
    """
    columns = ["session_id", "date", "weight", "reps", "volume", "estimated_1rm"]

    rows = WorkoutSet.objects.filter(
        session__user=user,
        session__is_completed=True,
        exercise=exercise,
    ).values("session_id", "session__started_at", "weight", "reps")

    if not rows:
        return pd.DataFrame(columns=columns)

    frame = pd.DataFrame(list(rows))
    frame = frame.rename(columns={"session__started_at": "started_at"})

    # Decimal -> float once, here, so no downstream code has to think about it.
    frame["weight"] = frame["weight"].astype(float)
    frame["reps"] = frame["reps"].astype(int)

    frame["date"] = pd.to_datetime(frame["started_at"], utc=True).dt.date
    frame["volume"] = frame["weight"] * frame["reps"]
    frame["estimated_1rm"] = frame["weight"] * (1 + frame["reps"] / EPLEY_DIVISOR)

    return frame[columns].sort_values("date")


def _per_session_summary(user, exercise):
    """One row per completed session containing this exercise, in date order:

        date, max_weight, total_volume, best_estimated_1rm

    This is the backbone of every exercise chart and of the plateau check.
    """
    frame = _exercise_sets_dataframe(user, exercise)
    if frame.empty:
        return frame

    summary = (
        frame.groupby(["session_id", "date"], as_index=False)
        .agg(
            max_weight=("weight", "max"),
            total_volume=("volume", "sum"),
            best_estimated_1rm=("estimated_1rm", "max"),
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    return summary


# --------------------------------------------------------------------------
# Exercise progress
# --------------------------------------------------------------------------


def get_max_weight_progress(user, exercise):
    """Heaviest weight lifted for this exercise per session, chronologically."""
    summary = _per_session_summary(user, exercise)
    if summary.empty:
        return []

    return [
        {"date": row.date.isoformat(), "value": round(float(row.max_weight), 2)}
        for row in summary.itertuples()
    ]


def get_volume_progress(user, exercise):
    """Training volume (sum of weight x reps) for this exercise per session."""
    summary = _per_session_summary(user, exercise)
    if summary.empty:
        return []

    return [
        {"date": row.date.isoformat(), "value": round(float(row.total_volume), 2)}
        for row in summary.itertuples()
    ]


def get_estimated_1rm_progress(user, exercise):
    """Best estimated 1RM per session, chronologically."""
    summary = _per_session_summary(user, exercise)
    if summary.empty:
        return []

    return [
        {"date": row.date.isoformat(), "value": round(float(row.best_estimated_1rm), 2)}
        for row in summary.itertuples()
    ]


def get_session_volume(session):
    """Total volume of one workout session, across every exercise."""
    total = sum(
        (float(s.weight) * s.reps) for s in session.sets.all()
    )
    return round(total, 2)


# --------------------------------------------------------------------------
# Personal records
# --------------------------------------------------------------------------


def get_personal_records(user, exercise):
    """Best-ever weight and best-ever estimated 1RM for this exercise.

    Returns None values when the exercise has never been logged.
    """
    frame = _exercise_sets_dataframe(user, exercise)
    if frame.empty:
        return {"max_weight": None, "best_estimated_1rm": None, "achieved_on": None}

    best_row = frame.loc[frame["estimated_1rm"].idxmax()]

    return {
        "max_weight": round(float(frame["weight"].max()), 2),
        "best_estimated_1rm": round(float(best_row["estimated_1rm"]), 2),
        "achieved_on": best_row["date"].isoformat(),
    }


def is_new_personal_record(user, exercise, session):
    """Did this session set a new best estimated 1RM for the exercise?

    Compares the session against everything that came *before* it, so a PR is
    only a PR relative to prior history.
    """
    frame = _exercise_sets_dataframe(user, exercise)
    if frame.empty:
        return False

    this_session = frame[frame["session_id"] == session.id]
    earlier = frame[frame["session_id"] != session.id]

    if this_session.empty:
        return False
    if earlier.empty:
        return True  # first time trained: everything is a baseline best

    return bool(this_session["estimated_1rm"].max() > earlier["estimated_1rm"].max())


# --------------------------------------------------------------------------
# Trends
# --------------------------------------------------------------------------


def _percentage_change(baseline, latest):
    """Safe percentage change. Returns None when there is no usable baseline.

    A zero baseline has no meaningful percentage change (it would be infinite),
    so we return None rather than dividing by zero or inventing a number.
    """
    if baseline is None or latest is None:
        return None
    if baseline == 0:
        return None
    return round(((latest - baseline) / baseline) * 100, 2)


def get_progress_trend(user, exercise, window=RECENT_SESSION_WINDOW):
    """Percentage change in estimated 1RM and volume across recent sessions.

    Compares the oldest session in the recent window against the newest.
    Returns None values when there is not enough history to compare.
    """
    summary = _per_session_summary(user, exercise)

    empty = {
        "estimated_1rm_change_percentage": None,
        "volume_change_percentage": None,
        "sessions_analysed": 0,
    }
    if summary.empty or len(summary) < 2:
        return {**empty, "sessions_analysed": len(summary)}

    recent = summary.tail(window)
    first, last = recent.iloc[0], recent.iloc[-1]

    return {
        "estimated_1rm_change_percentage": _percentage_change(
            float(first["best_estimated_1rm"]), float(last["best_estimated_1rm"])
        ),
        "volume_change_percentage": _percentage_change(
            float(first["total_volume"]), float(last["total_volume"])
        ),
        "sessions_analysed": len(recent),
    }


# --------------------------------------------------------------------------
# Plateau heuristic
# --------------------------------------------------------------------------


def detect_potential_plateau(user, exercise):
    """Flag a *potential* plateau in estimated 1RM for this exercise.

    The rule, deliberately simple and deterministic:
      - Need at least PLATEAU_MIN_SESSIONS recent completed sessions.
      - Take the best estimated 1RM of the first session in that window.
      - Compare it against the best estimated 1RM reached in any later session.
      - If that improvement is below PLATEAU_IMPROVEMENT_THRESHOLD_PERCENT,
        flag a potential plateau.

    This is an application heuristic to prompt reflection, not a scientific or
    medical assessment. The UI must always say "Potential plateau".
    """
    summary = _per_session_summary(user, exercise)

    if len(summary) < PLATEAU_MIN_SESSIONS:
        return {
            "potential_plateau": False,
            "reason": "insufficient_data",
            "sessions_analysed": len(summary),
            "improvement_percentage": None,
        }

    recent = summary.tail(RECENT_SESSION_WINDOW)
    baseline = float(recent.iloc[0]["best_estimated_1rm"])
    best_since = float(recent.iloc[1:]["best_estimated_1rm"].max())

    improvement = _percentage_change(baseline, best_since)

    # A zero baseline gives no usable signal — say nothing rather than guess.
    if improvement is None:
        return {
            "potential_plateau": False,
            "reason": "no_baseline",
            "sessions_analysed": len(recent),
            "improvement_percentage": None,
        }

    plateaued = improvement < PLATEAU_IMPROVEMENT_THRESHOLD_PERCENT

    return {
        "potential_plateau": plateaued,
        "reason": "below_threshold" if plateaued else "progressing",
        "sessions_analysed": len(recent),
        "improvement_percentage": improvement,
    }


# --------------------------------------------------------------------------
# Weekly frequency and adherence
# --------------------------------------------------------------------------


def get_weekly_workout_frequency(user, weeks=DEFAULT_WEEKS_ANALYSED):
    """Completed workouts per calendar week.

    One completed WorkoutSession is one workout. Exercises within a session are
    NOT counted as separate workouts.
    """
    since = timezone.now() - timedelta(weeks=weeks)

    rows = WorkoutSession.objects.filter(
        user=user, is_completed=True, started_at__gte=since
    ).values("started_at")

    if not rows:
        return []

    frame = pd.DataFrame(list(rows))
    frame["started_at"] = pd.to_datetime(frame["started_at"], utc=True)

    # Group by the Monday that starts each week.
    frame["week_start"] = (
        frame["started_at"] - pd.to_timedelta(frame["started_at"].dt.weekday, unit="D")
    ).dt.date

    counts = (
        frame.groupby("week_start", as_index=False)
        .size()
        .rename(columns={"size": "workouts"})
        .sort_values("week_start")
    )

    return [
        {"week_start": row.week_start.isoformat(), "workouts": int(row.workouts)}
        for row in counts.itertuples()
    ]


def get_adherence(user, planned_days_per_week, weeks=DEFAULT_WEEKS_ANALYSED):
    """How closely the user hit their planned workouts per week.

        adherence_percentage = completed_sessions / planned_sessions * 100

    Behaviour decision: adherence is NOT capped at 100%. Training five times in
    a week you planned for four is genuinely 125% adherence, and hiding that
    would misrepresent the data. The AI planner sees the true figure.

    Only weeks in which the user actually trained appear here — a week with no
    workouts contributes no row rather than a 0% row, because we cannot tell a
    missed week from a week before the user joined.
    """
    if not planned_days_per_week:
        return {"weekly": [], "average_adherence_percentage": None}

    weekly_counts = get_weekly_workout_frequency(user, weeks=weeks)
    if not weekly_counts:
        return {"weekly": [], "average_adherence_percentage": None}

    weekly = [
        {
            "week_start": week["week_start"],
            "workouts": week["workouts"],
            "planned": planned_days_per_week,
            "adherence_percentage": round(
                (week["workouts"] / planned_days_per_week) * 100, 2
            ),
        }
        for week in weekly_counts
    ]

    average = round(
        sum(week["adherence_percentage"] for week in weekly) / len(weekly), 2
    )

    return {"weekly": weekly, "average_adherence_percentage": average}


def get_average_weekly_workouts(user, weeks=DEFAULT_WEEKS_ANALYSED):
    """Mean completed workouts per week, across weeks the user trained."""
    weekly = get_weekly_workout_frequency(user, weeks=weeks)
    if not weekly:
        return 0.0

    return round(sum(week["workouts"] for week in weekly) / len(weekly), 2)


# --------------------------------------------------------------------------
# Dashboard assembly
# --------------------------------------------------------------------------


def get_exercise_summary(user, exercise):
    """Everything the progress dashboard shows for one exercise."""
    records = get_personal_records(user, exercise)
    trend = get_progress_trend(user, exercise)
    plateau = detect_potential_plateau(user, exercise)
    summary = _per_session_summary(user, exercise)

    recent_volume = None
    if not summary.empty:
        recent_volume = round(
            float(summary.tail(RECENT_SESSION_WINDOW)["total_volume"].sum()), 2
        )

    return {
        "has_data": not summary.empty,
        "sessions_logged": len(summary),
        "current_max_weight": records["max_weight"],
        "best_estimated_1rm": records["best_estimated_1rm"],
        "recent_volume": recent_volume,
        "estimated_1rm_change_percentage": trend["estimated_1rm_change_percentage"],
        "volume_change_percentage": trend["volume_change_percentage"],
        "potential_plateau": plateau["potential_plateau"],
        "plateau_reason": plateau["reason"],
    }


def get_progress_dashboard(user, exercise, planned_days_per_week):
    """All data for the progress page: summary cards plus chart-ready series.

    Chart data is prepared here in Python; the browser only renders it.
    """
    charts = {
        "max_weight": get_max_weight_progress(user, exercise) if exercise else [],
        "estimated_1rm": get_estimated_1rm_progress(user, exercise) if exercise else [],
        "volume": get_volume_progress(user, exercise) if exercise else [],
        "weekly_workouts": get_weekly_workout_frequency(user),
    }

    return {
        "summary": get_exercise_summary(user, exercise) if exercise else None,
        "charts": charts,
        "adherence": get_adherence(user, planned_days_per_week),
        "average_weekly_workouts": get_average_weekly_workouts(user),
    }


# --------------------------------------------------------------------------
# Wellness passport — body-composition trends
# --------------------------------------------------------------------------

# How far back the "recent change" figures look.
WELLNESS_TREND_WEEKS = 4


def _measurement_series(measurements, attribute):
    """Chart-ready [{date, value}] for one attribute, skipping blank entries.

    Body measurements are a handful of rows, so plain Python is used rather
    than pandas (per the analytics convention of not reaching for pandas on
    small single-column extracts).
    """
    series = []
    for measurement in measurements:
        value = getattr(measurement, attribute)
        if value is not None:
            series.append(
                {"date": measurement.recorded_on.isoformat(), "value": round(float(value), 1)}
            )
    return series


def _recent_change(measurements, attribute, weeks=WELLNESS_TREND_WEEKS):
    """Change in an attribute over the recent window (latest minus baseline).

    Baseline is the most recent entry at least `weeks` old; if none is that
    old, the earliest entry is used. Returns None when there is nothing to
    compare or a value is missing.
    """
    points = [m for m in measurements if getattr(m, attribute) is not None]
    if len(points) < 2:
        return None

    latest = points[-1]
    cutoff = latest.recorded_on - timedelta(weeks=weeks)

    baseline = points[0]
    for measurement in points:
        if measurement.recorded_on <= cutoff:
            baseline = measurement

    if baseline is latest:
        return None

    return round(
        float(getattr(latest, attribute)) - float(getattr(baseline, attribute)), 1
    )


def _bmi(weight_kg, height_cm):
    """Body Mass Index from weight and height, or None if either is missing."""
    if not weight_kg or not height_cm:
        return None
    height_m = float(height_cm) / 100
    return round(float(weight_kg) / (height_m * height_m), 1)


def get_wellness_dashboard(user, height_cm=None):
    """Everything the Wellness passport shows: latest values, recent changes,
    BMI, and chart-ready trend series. All computed server-side."""
    measurements = list(
        BodyMeasurement.objects.filter(user=user).order_by("recorded_on")
    )

    empty_charts = {"weight": [], "body_fat": [], "muscle_mass": []}

    if not measurements:
        return {
            "has_data": False,
            "entries_logged": 0,
            "latest": None,
            "changes": {"weight": None, "body_fat": None, "muscle_mass": None},
            "bmi": None,
            "charts": empty_charts,
            "recent_entries": [],
        }

    latest = measurements[-1]

    return {
        "has_data": True,
        "entries_logged": len(measurements),
        "latest": {
            "recorded_on": latest.recorded_on,
            "weight_kg": latest.weight_kg,
            "body_fat_percentage": latest.body_fat_percentage,
            "muscle_mass_kg": latest.muscle_mass_kg,
        },
        "changes": {
            "weight": _recent_change(measurements, "weight_kg"),
            "body_fat": _recent_change(measurements, "body_fat_percentage"),
            "muscle_mass": _recent_change(measurements, "muscle_mass_kg"),
        },
        "bmi": _bmi(latest.weight_kg, height_cm),
        "charts": {
            "weight": _measurement_series(measurements, "weight_kg"),
            "body_fat": _measurement_series(measurements, "body_fat_percentage"),
            "muscle_mass": _measurement_series(measurements, "muscle_mass_kg"),
        },
        # Newest first for the recent-entries list on the page.
        "recent_entries": list(reversed(measurements))[:8],
    }


# --------------------------------------------------------------------------
# Calorie calculator — BMR, TDEE (maintenance), and goal targets
# --------------------------------------------------------------------------
#
# Deterministic, all in Python. Uses the Mifflin-St Jeor BMR equation and the
# activity multipliers used by calculator.net, so results match that reference.

# BMR * multiplier = Total Daily Energy Expenditure (maintenance calories).
ACTIVITY_MULTIPLIERS = {
    ActivityLevel.SEDENTARY: 1.2,
    ActivityLevel.LIGHT: 1.375,
    ActivityLevel.MODERATE: 1.465,
    ActivityLevel.ACTIVE: 1.55,
    ActivityLevel.VERY_ACTIVE: 1.725,
    ActivityLevel.EXTRA_ACTIVE: 1.9,
}

# 1 kg/week of weight change is treated as ~1000 kcal/day, matching the
# reference calculator. (key, label, sub-label, daily kcal delta from maintenance)
CALORIE_GOALS = [
    ("maintain", "Maintain weight", "", 0),
    ("mild_loss", "Mild weight loss", "0.25 kg/week", -250),
    ("loss", "Weight loss", "0.5 kg/week", -500),
    ("extreme_loss", "Extreme weight loss", "1 kg/week", -1000),
    ("mild_gain", "Mild weight gain", "0.25 kg/week", 250),
    ("gain", "Weight gain", "0.5 kg/week", 500),
    ("fast_gain", "Fast weight gain", "1 kg/week", 1000),
]

# calculator.net does not recommend intakes below these floors.
SAFE_CALORIE_FLOOR = {Sex.MALE: 1500, Sex.FEMALE: 1200}


def calculate_bmr(sex, weight_kg, height_cm, age):
    """Basal Metabolic Rate via the Mifflin-St Jeor equation.

        men:   10*kg + 6.25*cm - 5*age + 5
        women: 10*kg + 6.25*cm - 5*age - 161
    """
    base = 10 * float(weight_kg) + 6.25 * float(height_cm) - 5 * int(age)
    return base + 5 if sex == Sex.MALE else base - 161


def calculate_maintenance_calories(bmr, activity_level):
    """TDEE = BMR adjusted for activity level."""
    return bmr * ACTIVITY_MULTIPLIERS[activity_level]


def build_calorie_targets(maintenance_calories, sex):
    """The maintain / lose / gain table from a maintenance figure.

    Returns a list of dicts: label, sublabel, calories, percent of maintenance,
    and whether the target dips below the recommended safe floor.
    """
    maintenance = int(round(maintenance_calories))
    floor = SAFE_CALORIE_FLOOR.get(sex, 1200)

    targets = []
    for key, label, sublabel, delta in CALORIE_GOALS:
        calories = maintenance + delta
        targets.append(
            {
                "key": key,
                "label": label,
                "sublabel": sublabel,
                "calories": calories,
                "percent": round(calories / maintenance * 100) if maintenance else 0,
                "below_floor": delta < 0 and calories < floor,
            }
        )
    return targets


def compute_calorie_plan(sex, weight_kg, height_cm, age, activity_level):
    """Full calculation from raw inputs: BMR, maintenance, and the target table.

    Returns a dict ready for both storage (bmr, maintenance) and display.
    """
    bmr = calculate_bmr(sex, weight_kg, height_cm, age)
    maintenance = calculate_maintenance_calories(bmr, activity_level)

    return {
        "bmr": int(round(bmr)),
        "maintenance_calories": int(round(maintenance)),
        "targets": build_calorie_targets(maintenance, sex),
    }


def get_calorie_target(maintenance_calories, sex, goal_key):
    """One goal's target from the table, or the maintain target as a fallback."""
    targets = build_calorie_targets(maintenance_calories, sex)
    return next((t for t in targets if t["key"] == goal_key), targets[0])


# --------------------------------------------------------------------------
# Macros — protein, fat, carbohydrate, fibre from a calorie target
# --------------------------------------------------------------------------
#
# Protein is prioritised, fat is a fixed share of calories, and carbohydrate
# takes whatever calories remain. Fibre is a flat daily target for gut health,
# not derived from calories.

PROTEIN_G_PER_KG = 1.8          # within the 1.6–2.0 g/kg working range
FAT_SHARE_OF_CALORIES = 0.25    # fat = 25% of total calories
PROTEIN_KCAL_PER_G = 4
FAT_KCAL_PER_G = 9
CARB_KCAL_PER_G = 4
FIBRE_TARGET_MIN_G = 30
FIBRE_TARGET_MAX_G = 40


def compute_macros(calories, bodyweight_kg):
    """Daily macro targets for a calorie figure and bodyweight.

    Order of operations (each step shown to the user on the page):
      1. Protein  = bodyweight * 1.8 g/kg, then * 4 kcal/g
      2. Fat      = 25% of calories, then / 9 kcal/g
      3. Carbs    = remaining calories, / 4 kcal/g
      4. Fibre    = flat 30–40 g/day target
    """
    bodyweight = float(bodyweight_kg)

    protein_g = round(bodyweight * PROTEIN_G_PER_KG)
    protein_kcal = protein_g * PROTEIN_KCAL_PER_G

    fat_kcal = round(calories * FAT_SHARE_OF_CALORIES)
    fat_g = round(fat_kcal / FAT_KCAL_PER_G)

    # Carbohydrate takes the calories left after protein and fat. Clamp at zero
    # in the rare case a very low target cannot cover protein + fat.
    carb_kcal = max(0, calories - protein_kcal - fat_kcal)
    carb_g = round(carb_kcal / CARB_KCAL_PER_G)

    return {
        "calories": calories,
        "bodyweight_kg": round(bodyweight, 1),
        "protein": {
            "grams": protein_g,
            "kcal": protein_kcal,
            "per_kg": PROTEIN_G_PER_KG,
        },
        "fat": {
            "grams": fat_g,
            "kcal": fat_kcal,
            "percent": int(FAT_SHARE_OF_CALORIES * 100),
        },
        "carbs": {"grams": carb_g, "kcal": carb_kcal},
        "fibre": {"min": FIBRE_TARGET_MIN_G, "max": FIBRE_TARGET_MAX_G},
    }
