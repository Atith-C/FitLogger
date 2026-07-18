"""Admin read models — platform stats and the trainee directory."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from users.models import ExperienceLevel, Goal, Role, Sex

# The trainee picks a goal per visit on their nutrition page and it is not
# stored, so an admin's "goal calories" is derived from their profile goal.
GOAL_TO_CALORIE_KEY = {
    Goal.LOSE_WEIGHT: "loss",
    Goal.BUILD_MUSCLE: "gain",
    Goal.STAY_FIT: "maintain",
}


def trainees_queryset(include_deleted=False):
    """All trainee accounts (the platform's end users).

    Soft-deleted trainees are excluded by default: their rows survive, but they
    should not appear in a list or inflate a count. Only the "deleted" filter
    and the detail page (which offers Restore) ask for them.
    """
    qs = User.objects.filter(profile__role=Role.TRAINEE)
    if not include_deleted:
        qs = qs.filter(profile__deleted_at__isnull=True)
    return qs


def list_trainees(q="", gender="", status="", sharing=""):
    """Trainees filtered by search text and the list filters.

    q       — matches username / first / last / email (case-insensitive)
    gender  — 'MALE' / 'FEMALE'
    status  — 'active' / 'blocked' / 'deleted'
    sharing — 'shared' / 'private'
    """
    # Only the explicit "deleted" filter reaches removed accounts, so "blocked"
    # cannot quietly include them.
    qs = trainees_queryset(include_deleted=(status == "deleted")).select_related(
        "profile"
    )

    q = (q or "").strip()
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
        )

    if gender in (Sex.MALE, Sex.FEMALE):
        qs = qs.filter(profile__sex=gender)

    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "blocked":
        qs = qs.filter(is_active=False)
    elif status == "deleted":
        qs = qs.filter(profile__deleted_at__isnull=False)

    if sharing == "shared":
        qs = qs.filter(profile__profile_shared=True)
    elif sharing == "private":
        qs = qs.filter(profile__profile_shared=False)

    return qs.order_by("first_name", "username")


def get_trainee_or_none(trainee_id):
    """One trainee by id, or None if the id is not a trainee account.

    Includes soft-deleted trainees, so their page still opens to be restored.
    Admin accounts are never returned, which is what stops an admin from being
    blocked or removed through these views.
    """
    return (
        trainees_queryset(include_deleted=True)
        .select_related("profile")
        .filter(pk=trainee_id)
        .first()
    )


def trainee_personal_info(trainee):
    """Personal profile fields beyond the always-visible name/age/gender.

    Callers must check can_admin_view_profile() first — this is private data and
    is only ever built for a trainee who has approved sharing.
    """
    profile = trainee.profile
    return {
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "goal": profile.get_goal_display(),
        "experience_level": profile.get_experience_level_display(),
    }


def trainee_nutrition(trainee):
    """The trainee's calorie and macro targets, or None if never calculated.

    Goal calories follow the trainee's profile goal; macros are then derived
    from that figure using the same formulas the trainee sees.
    """
    from analytics.services import build_calorie_targets, compute_macros
    from users.services import get_calorie_calculation

    calculation = get_calorie_calculation(trainee)
    if calculation is None:
        return None

    targets = build_calorie_targets(
        calculation.maintenance_calories, calculation.sex
    )
    goal_key = GOAL_TO_CALORIE_KEY.get(trainee.profile.goal, "maintain")
    goal_target = next((t for t in targets if t["key"] == goal_key), targets[0])

    return {
        "maintenance": calculation.maintenance_calories,
        "goal_label": goal_target["label"],
        "goal_calories": goal_target["calories"],
        "macros": compute_macros(goal_target["calories"], calculation.weight_kg),
    }


def trainee_overview(trainee):
    """Everything the admin sees for a trainee who has approved sharing:
    nutrition, fitness, analytics and recent history. Read live, so it always
    reflects the trainee's latest state."""
    from ai_planner.services import get_active_plan
    from analytics.services import (
        get_average_weekly_workouts,
        get_weekly_workout_frequency,
    )
    from workouts.services import (
        get_history_with_grouped_sets,
        get_home_stats,
        workout_streak,
    )

    profile = trainee.profile
    stats = get_home_stats(trainee, profile.days_per_week)

    return {
        "nutrition": trainee_nutrition(trainee),
        "fitness": {
            "avg_weekly": get_average_weekly_workouts(trainee),
            "streak": workout_streak(trainee),
            "this_week": stats["this_week"],
            "planned": profile.days_per_week,
            "plan": get_active_plan(trainee),
        },
        "stats": stats,
        "charts": {"weekly_workouts": get_weekly_workout_frequency(trainee)},
        "history": get_history_with_grouped_sets(trainee)[:5],
    }


def get_selected_exercise(exercise_id):
    """The exercise chosen in the picker, or None.

    The value arrives raw from the query string, so anything unusable — blank,
    non-numeric, or an id that does not exist — is treated as "nothing
    selected" rather than raising. A bare pk lookup on "abc" would be a 500.
    """
    from workouts.services import get_exercise

    if not exercise_id or not str(exercise_id).isdigit():
        return None
    return get_exercise(exercise_id)


def trainee_exercise_analytics(trainee, exercise):
    """One exercise's progress for a trainee: summary, chart series, history.

    Calls the chart services directly rather than going through
    get_progress_dashboard(), which would recompute the weekly-workouts chart
    that trainee_overview() has already built.

    Callers must check can_admin_view_profile() first — this is private
    workout data.
    """
    from analytics.services import (
        get_estimated_1rm_progress,
        get_exercise_summary,
        get_max_weight_progress,
        get_volume_progress,
    )
    from workouts.services import get_exercise_history

    return {
        "summary": get_exercise_summary(trainee, exercise),
        "history": get_exercise_history(trainee, exercise),
        "charts": {
            "max_weight": get_max_weight_progress(trainee, exercise),
            "estimated_1rm": get_estimated_1rm_progress(trainee, exercise),
            "volume": get_volume_progress(trainee, exercise),
        },
    }


def dashboard_stats(admin_user):
    """The six headline numbers for the admin dashboard."""
    from messaging.services import admin_unread_count
    from notifications.services import unread_count

    trainees = trainees_queryset()
    today = timezone.localdate()

    return {
        "total_users": trainees.count(),
        "active_users": trainees.filter(is_active=True).count(),
        "today_logins": trainees.filter(last_login__date=today).count(),
        "new_registrations": trainees.filter(date_joined__date=today).count(),
        "unread_messages": admin_unread_count(),
        "unread_notifications": unread_count(admin_user),
    }


# --------------------------------------------------------------------------
# Platform analytics (the admin Analytics page)
# --------------------------------------------------------------------------

# How the growth toggle maps to a look-back window.
GROWTH_RANGES = {
    "week": timedelta(days=7),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}
DEFAULT_GROWTH_RANGE = "year"

# Below this many trainees, a goal/experience breakdown identifies individuals
# rather than describing a population — so those two charts show a "not enough
# yet" state instead of leaking gated profile data one bar at a time.
MIN_TRAINEES_FOR_DISTRIBUTION = 3


def _display_name(user):
    return user.get_full_name() or user.username


def _user_growth(trainees, range_key):
    """Cumulative registrations over time, one dot per trainee.

    The running total is computed across all of history, then the window only
    decides which dots are shown — so a dot in the last week still sits at the
    right cumulative height, not at 1.
    """
    ordered = list(trainees.order_by("date_joined"))

    window = GROWTH_RANGES.get(range_key, GROWTH_RANGES[DEFAULT_GROWTH_RANGE])
    cutoff = timezone.now() - window

    points = []
    for running_total, user in enumerate(ordered, start=1):
        if user.date_joined >= cutoff:
            points.append({
                "date": timezone.localtime(user.date_joined).strftime("%Y-%m-%d"),
                "count": running_total,
                "name": _display_name(user),
                "joined": timezone.localtime(user.date_joined).strftime("%d/%m/%Y"),
            })
    return points


def _active_users(trainees):
    """Daily / weekly / monthly active users, from last_login.

    last_login is a single timestamp (Django keeps only the most recent), so
    this is a point-in-time snapshot: DAU are users whose last login was today,
    WAU within 7 days, MAU within 30. The windows nest by definition.

    Names ride along on hover — login activity is not gated (admins already see
    'today's logins' on the dashboard), unlike goals or workouts.
    """
    now = timezone.now()
    today = timezone.localdate()
    windows = [
        ("Daily", lambda u: u.last_login and timezone.localtime(u.last_login).date() == today),
        ("Weekly", lambda u: u.last_login and u.last_login >= now - timedelta(days=7)),
        ("Monthly", lambda u: u.last_login and u.last_login >= now - timedelta(days=30)),
    ]

    users = list(trainees)
    bars = []
    for label, predicate in windows:
        names = sorted(_display_name(u) for u in users if predicate(u))
        bars.append({"label": label, "count": len(names), "names": names})
    return bars


def _weekday_activity(trainees):
    """Completed workouts per weekday, Monday-first.

    Counts of sessions, never names: this is workout data, which is gated, so it
    only ever leaves the server as an aggregate. The signal answers 'when do my
    trainees train', not 'who trained on Tuesday'.
    """
    from workouts.models import WorkoutSession

    order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    counts = {day: 0 for day in order}

    starts = WorkoutSession.objects.filter(
        user__in=trainees, is_completed=True
    ).values_list("started_at", flat=True)
    for started_at in starts:
        counts[timezone.localtime(started_at).strftime("%a")] += 1

    return [{"label": day, "count": counts[day]} for day in order]


def _distribution(trainees, field, choices, enough):
    """Counts across a choice field, in enum order, every bucket present.

    Counts only — never names. goal and experience_level are gated fields, so a
    named breakdown would hand an admin exactly what the sharing gate withholds.
    `enough` gates the gated fields on a minimum population; below it the view
    shows a message rather than an identifying breakdown.
    """
    if not enough:
        return None

    tallies = {value: 0 for value, _ in choices}
    for value in trainees.values_list(f"profile__{field}", flat=True):
        if value in tallies:
            tallies[value] += 1
    return [{"label": label, "count": tallies[value]} for value, label in choices]


def platform_analytics(range_key=DEFAULT_GROWTH_RANGE):
    """Everything the admin Analytics page renders, prepared server-side.

    Registration and login activity carry names (admin-appropriate); the
    profile-attribute distributions are counts only, and the gated ones (goal,
    experience) are withheld entirely below a minimum population.
    """
    if range_key not in GROWTH_RANGES:
        range_key = DEFAULT_GROWTH_RANGE

    trainees = trainees_queryset().select_related("profile")
    total = trainees.count()
    enough = total >= MIN_TRAINEES_FOR_DISTRIBUTION

    return {
        "range": range_key,
        "total_trainees": total,
        "enough_for_distribution": enough,
        "min_trainees": MIN_TRAINEES_FOR_DISTRIBUTION,
        "growth": _user_growth(trainees, range_key),
        "active": _active_users(trainees),
        "weekday": _weekday_activity(trainees),
        "goals": _distribution(trainees, "goal", Goal.choices, enough),
        "experience": _distribution(
            trainees, "experience_level", ExperienceLevel.choices, enough
        ),
        # Male / Female only — every trainee sets a gender, so there is no
        # "unspecified" bar. A brand-new trainee who has not filled their
        # profile yet simply does not appear here until they do. Sex is not
        # gated, so it ignores the distribution threshold.
        "sex": _distribution(trainees, "sex", Sex.choices, enough=True),
    }
