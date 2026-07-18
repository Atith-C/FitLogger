"""Workout business logic.

Views stay thin and delegate here. Every function that touches user data takes
the user explicitly and filters on it — ownership is never inferred from a
client-supplied id.
"""

from collections import OrderedDict
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, Prefetch, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Exercise, MuscleGroup, WorkoutSession, WorkoutSet


# --------------------------------------------------------------------------
# Exercise selection
# --------------------------------------------------------------------------


def get_all_exercises():
    """Every active exercise in the library, ordered by muscle group then name.

    Archived exercises are excluded, so an exercise an admin has removed drops
    out of every picker and the AI planner at once, while its logged history
    survives.
    """
    return Exercise.objects.filter(is_active=True)


def get_exercise(exercise_id):
    """Look up one exercise, or None if the id does not exist.

    Returns None rather than raising, so callers can reject an unknown
    exercise id from a client without a 500.
    """
    return Exercise.objects.filter(pk=exercise_id).first()


def get_exercises_grouped_by_muscle():
    """Exercises grouped by muscle group, for the exercise picker.

    Built from a single query — grouping happens in Python, not with one query
    per muscle group.
    """
    grouped = OrderedDict()
    labels = dict(MuscleGroup.choices)

    for exercise in get_all_exercises():
        label = labels.get(exercise.muscle_group, exercise.muscle_group)
        grouped.setdefault(label, []).append(exercise)

    return grouped


# --------------------------------------------------------------------------
# Exercise library management (admin)
# --------------------------------------------------------------------------


def get_exercises_for_admin():
    """Active exercises grouped by muscle group, each annotated with how many
    logged sets reference it — so the admin sees what deleting would archive."""
    from django.db.models import Count

    grouped = OrderedDict()
    labels = dict(MuscleGroup.choices)

    exercises = (
        Exercise.objects.filter(is_active=True)
        .annotate(set_count=Count("sets"))
        .order_by("muscle_group", "name")
    )
    for exercise in exercises:
        label = labels.get(exercise.muscle_group, exercise.muscle_group)
        grouped.setdefault(label, []).append(exercise)

    return grouped


def get_archived_exercises():
    """Exercises an admin removed but that logged workouts still reference."""
    return Exercise.objects.filter(is_active=False).order_by("muscle_group", "name")


@transaction.atomic
def remove_exercise(exercise_id):
    """Remove an exercise from the library.

    Truly deletes it when nothing references it; archives it (hides it from
    every picker, keeps it on the historical sets) when a trainee has already
    logged it — because WorkoutSet.exercise is PROTECT and a hard delete would
    destroy that history. Returns "deleted", "archived", or None if not found.
    """
    exercise = Exercise.objects.filter(pk=exercise_id).first()
    if exercise is None:
        return None

    if exercise.sets.exists():
        if exercise.is_active:
            exercise.is_active = False
            exercise.save(update_fields=["is_active"])
        return "archived"

    exercise.delete()
    return "deleted"


@transaction.atomic
def restore_exercise(exercise_id):
    """Return an archived exercise to the library. Returns it, or None."""
    exercise = Exercise.objects.filter(pk=exercise_id, is_active=False).first()
    if exercise is None:
        return None
    exercise.is_active = True
    exercise.save(update_fields=["is_active"])
    return exercise


# --------------------------------------------------------------------------
# Workout sessions
# --------------------------------------------------------------------------


def get_active_workout_session(user):
    """The user's unfinished session, or None.

    The database guarantees there is at most one (one_active_session_per_user).
    """
    return WorkoutSession.objects.filter(user=user, is_completed=False).first()


@transaction.atomic
def create_workout_session(user, name="Workout"):
    """Start a workout, or resume the one already in progress.

    A user may only have one active session at a time. Rather than failing when
    one already exists, we hand the existing session back — the user pressing
    "Start Workout" again mid-session wants to get back to it, not to lose it.
    """
    active = get_active_workout_session(user)
    if active is not None:
        return active

    return WorkoutSession.objects.create(
        user=user,
        name=name.strip() or "Workout",
        started_at=timezone.now(),
    )


def get_user_session(user, session_id):
    """Fetch one of this user's sessions.

    Raises PermissionDenied for a session belonging to somebody else, so a
    guessed id in the URL cannot expose another user's workout.
    """
    session = WorkoutSession.objects.filter(pk=session_id).first()
    if session is None or session.user_id != user.id:
        raise PermissionDenied("That workout session does not belong to you.")
    return session


def _notify_admins_of_workout(user, session):
    """Tell admins a trainee finished a workout.

    Called only on the transition to completed. complete_workout_session is
    idempotent and also accepts notes-only calls, so notifying on every call
    would re-announce the same workout each time the note was edited.
    """
    from users.services import (
        admin_trainee_link,
        get_or_create_profile,
        trainee_display,
    )

    if not get_or_create_profile(user).is_trainee:
        return

    from notifications.models import Category
    from notifications.services import notify_admins

    set_count = session.sets.count()
    notify_admins(
        f"{trainee_display(user)} completed a workout",
        message=f"{session.name} — {set_count} set{'' if set_count == 1 else 's'}.",
        link=admin_trainee_link(user),
        actor=user,
        category=Category.WORKOUT,
    )


@transaction.atomic
def complete_workout_session(user, session_id, notes=None):
    """Finish a workout. Ownership is verified before anything is written.

    An optional note is saved alongside completion, so a user can jot how the
    session went as they finish it.
    """
    session = get_user_session(user, session_id)

    fields = []
    if notes is not None:
        session.notes = notes.strip()
        fields.append("notes")

    # Captured before the save: afterwards every call looks "already complete",
    # and admins would be notified again for a note edit.
    just_completed = not session.is_completed
    if just_completed:
        session.is_completed = True
        session.completed_at = timezone.now()
        fields += ["is_completed", "completed_at"]

    if fields:
        session.save(update_fields=fields)

    if just_completed:
        _notify_admins_of_workout(user, session)

    return session


@transaction.atomic
def update_session_notes(user, session_id, notes):
    """Save the session note without finishing the workout."""
    session = get_user_session(user, session_id)
    session.notes = (notes or "").strip()
    session.save(update_fields=["notes"])
    return session


@transaction.atomic
def delete_workout_session(user, session_id):
    """Delete one of the user's workout sessions (and its sets, by cascade).

    Scoped to the user, so a guessed id cannot delete someone else's workout.
    Returns True if a session was deleted, False if none matched.
    """
    deleted_count, _ = WorkoutSession.objects.filter(
        pk=session_id, user=user
    ).delete()
    return deleted_count > 0


def workout_streak(user):
    """Consecutive weeks (Monday-start) with at least one completed workout.

    Weeks, not days: people train 3-5 times a week, so a day streak would read
    "1" almost always. The current week is in progress, so an empty one does not
    break the streak — we start counting from last week in that case.
    """
    completed = WorkoutSession.objects.filter(user=user, is_completed=True)

    trained_weeks = set()
    for started_at in completed.values_list("started_at", flat=True):
        day = timezone.localtime(started_at).date()
        trained_weeks.add(day - timedelta(days=day.weekday()))

    if not trained_weeks:
        return 0

    today = timezone.localdate()
    week = today - timedelta(days=today.weekday())
    if week not in trained_weeks:
        week -= timedelta(weeks=1)  # this week is not over yet

    streak = 0
    while week in trained_weeks:
        streak += 1
        week -= timedelta(weeks=1)
    return streak


def get_active_session_with_sets(user):
    """The user's in-progress session with its sets grouped by exercise.

    Returns (session, grouped) or (None, None). Used by the history page to
    show the unfinished workout with Continue / Delete options.
    """
    session = get_active_workout_session(user)
    if session is None:
        return None, None
    return session, group_session_sets_by_exercise_prefetched(session)


def group_session_sets_by_exercise_prefetched(session):
    """Group a single session's sets by exercise with select_related, so it
    costs one query rather than one per set."""
    grouped = OrderedDict()
    sets = session.sets.select_related("exercise").order_by(
        "exercise__name", "set_number"
    )
    for workout_set in sets:
        grouped.setdefault(workout_set.exercise, []).append(workout_set)
    return grouped


def get_session_details(user, session_id):
    """A session with its sets grouped by exercise, ready to render.

    Returns (session, grouped) where grouped maps exercise -> [sets in order].
    Uses select_related so rendering does not fire one query per set.
    """
    session = get_user_session(user, session_id)

    grouped = OrderedDict()
    sets = session.sets.select_related("exercise").order_by("exercise__name", "set_number")
    for workout_set in sets:
        grouped.setdefault(workout_set.exercise, []).append(workout_set)

    return session, grouped


# --------------------------------------------------------------------------
# Workout sets
# --------------------------------------------------------------------------


def get_next_set_number(session, exercise):
    """The set number the next set for this exercise should get."""
    last = (
        WorkoutSet.objects.filter(session=session, exercise=exercise)
        .order_by("-set_number")
        .first()
    )
    return (last.set_number + 1) if last else 1


def get_session_sets_for_exercise(session, exercise):
    """Sets already logged for this exercise in this session, in order."""
    return WorkoutSet.objects.filter(session=session, exercise=exercise).order_by(
        "set_number"
    )


@transaction.atomic
def create_workout_set(
    user, session_id, exercise_id, weight, reps, set_number=None, client_record_id=None
):
    """Log one set.

    Idempotent on client_record_id: the offline queue may send the same set
    twice after a reconnect, and that must not create two rows. The database
    also enforces this with a unique index, so the check here is a friendly
    fast path rather than the actual guarantee.
    """
    session = get_user_session(user, session_id)

    if session.is_completed:
        raise ValidationError("This workout is already finished.")

    exercise = get_exercise(exercise_id)
    if exercise is None:
        raise ValidationError("That exercise does not exist.")

    if client_record_id is not None:
        existing = WorkoutSet.objects.filter(client_record_id=client_record_id).first()
        if existing is not None:
            return existing, False  # already synced

    if set_number is None:
        set_number = get_next_set_number(session, exercise)

    workout_set = WorkoutSet(
        session=session,
        exercise=exercise,
        set_number=set_number,
        weight=weight,
        reps=reps,
    )
    if client_record_id is not None:
        workout_set.client_record_id = client_record_id

    # full_clean runs the model validators (non-negative weight, positive reps)
    # before we hit the database, so we surface a readable error rather than an
    # IntegrityError from the CHECK constraint.
    workout_set.full_clean(exclude=["client_record_id"])
    workout_set.save()

    return workout_set, True


# --------------------------------------------------------------------------
# Previous performance — the core feature
# --------------------------------------------------------------------------


def get_previous_exercise_performance(user, exercise, exclude_session=None):
    """What this user did for this exercise the last time they trained it.

    Looks only at completed sessions, ignoring the workout currently in
    progress. Returns (session, [sets in set order]) or (None, []) when the
    exercise has never been logged before.
    """
    sessions = (
        WorkoutSession.objects.filter(
            user=user,
            is_completed=True,
            sets__exercise=exercise,
        )
        .distinct()
        .order_by("-started_at")
    )

    if exclude_session is not None:
        sessions = sessions.exclude(pk=exclude_session.pk)

    previous = sessions.first()
    if previous is None:
        return None, []

    sets = WorkoutSet.objects.filter(session=previous, exercise=exercise).order_by(
        "set_number"
    )
    return previous, list(sets)


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


def get_user_workout_history(user):
    """This user's completed sessions, newest first.

    prefetch_related pulls every set and exercise in two extra queries instead
    of one per session (the N+1 problem).
    """
    return (
        WorkoutSession.objects.filter(user=user, is_completed=True)
        .prefetch_related("sets__exercise")
        .order_by("-started_at")
    )


def group_session_sets_by_exercise(session):
    """Group one session's sets under their exercise, preserving set order.

    Reads session.sets.all() so that, on a session that arrived via
    get_user_workout_history's prefetch, this costs no extra queries.
    """
    grouped = OrderedDict()
    for workout_set in session.sets.all():
        grouped.setdefault(workout_set.exercise, []).append(workout_set)
    return grouped


def get_history_with_grouped_sets(user):
    """Completed sessions, newest first, each with its sets grouped by exercise.

    Shape: [(session, {exercise: [sets]}), ...] — ready to render directly.
    """
    return [
        (session, group_session_sets_by_exercise(session))
        for session in get_user_workout_history(user)
    ]


def get_exercise_history(user, exercise):
    """This user's completed sessions containing one exercise, newest first.

    Shape: [(session, [sets in set order]), ...] — carrying only that
    exercise's sets, not the whole session's, since this answers "how has this
    lift gone" rather than "what did this workout look like".

    The Prefetch filters the sets in the database, so a session that also
    contains ten other exercises still costs nothing extra to render.
    """
    sessions = (
        WorkoutSession.objects.filter(
            user=user, is_completed=True, sets__exercise=exercise
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "sets",
                queryset=WorkoutSet.objects.filter(exercise=exercise).order_by(
                    "set_number"
                ),
                to_attr="exercise_sets",
            )
        )
        .order_by("-started_at")
    )

    return [(session, session.exercise_sets) for session in sessions]


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


def get_home_stats(user, planned_days_per_week=None):
    """Headline numbers for the home dashboard.

    Every figure counts completed sessions only — a workout in progress has not
    been earned yet, and counting it would make the weekly ring jump backwards
    when the user abandons it.

    Volume is summed in the database rather than in Python so the whole
    dashboard stays a fixed number of queries however long the history gets.
    """
    completed = WorkoutSession.objects.filter(user=user, is_completed=True)

    # Week starts Monday, in the user's local date, matching how the analytics
    # adherence chart buckets weeks.
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())

    total_workouts = completed.count()
    this_week = completed.filter(started_at__date__gte=week_start).count()

    # output_field is required twice over: weight (Decimal) x reps (Integer) is
    # a mixed-type expression Django will not infer, and Coalesce's 0 literal
    # would otherwise resolve to an IntegerField and clash with the Sum.
    volume = WorkoutSet.objects.filter(
        session__user=user, session__is_completed=True
    ).aggregate(
        total=Coalesce(
            Sum(
                F("weight") * F("reps"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            0,
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )
    )[
        "total"
    ]

    total_sets = WorkoutSet.objects.filter(
        session__user=user, session__is_completed=True
    ).count()

    planned = planned_days_per_week or 0
    # Capped for the ring geometry: an over-achieving week should fill the ring,
    # not wrap past the start. The raw count is still shown as text.
    week_percentage = 0
    if planned > 0:
        week_percentage = min(round(this_week / planned * 100), 100)

    # Computed here because the template language cannot subtract, and because
    # "-1 to go" would be a nonsense thing to render.
    remaining_this_week = max(planned - this_week, 0)

    # Both are ordered by -started_at, so the newest session is simply the first
    # of the recent ones — fetching it separately would cost a query to re-read
    # a row already in memory.
    recent_sessions = list(completed.order_by("-started_at")[:3])

    return {
        "total_workouts": total_workouts,
        "this_week": this_week,
        "planned_days_per_week": planned,
        "week_percentage": week_percentage,
        "remaining_this_week": remaining_this_week,
        # Coalesce already guarantees a non-NULL Decimal; `or 0` would quietly
        # swap the zero case to an int, since Decimal("0.00") is falsy.
        "total_volume_kg": volume,
        "total_sets": total_sets,
        "last_session": recent_sessions[0] if recent_sessions else None,
        "recent_sessions": recent_sessions,
    }
