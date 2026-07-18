from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from users.services import get_or_create_profile

from .forms import StartWorkoutForm, WorkoutSetForm
from .models import Exercise
from .services import (
    complete_workout_session,
    create_workout_session,
    create_workout_set,
    delete_workout_session,
    get_active_session_with_sets,
    get_active_workout_session,
    get_exercises_grouped_by_muscle,
    get_history_with_grouped_sets,
    get_home_stats,
    get_next_set_number,
    group_session_sets_by_exercise_prefetched,
    get_previous_exercise_performance,
    get_session_sets_for_exercise,
    get_user_session,
    update_session_notes,
)


def landing(request):
    """Public marketing page at /.

    Signed-in users have no use for the sales pitch, so they go straight to the
    dashboard — this keeps / as the single address anyone can be given.
    """
    if request.user.is_authenticated:
        return redirect("workouts:home")
    return render(request, "landing.html")


@login_required
def home(request):
    """Authenticated dashboard."""
    profile = get_or_create_profile(request.user)
    active_session = get_active_workout_session(request.user)
    stats = get_home_stats(request.user, profile.days_per_week)

    return render(
        request,
        "workouts/home.html",
        {
            "profile": profile,
            "active_session": active_session,
            "stats": stats,
        },
    )


@login_required
def start_workout(request):
    """Name and begin a workout — or resume one already in progress."""
    active_session = get_active_workout_session(request.user)
    if active_session is not None:
        messages.info(request, "You already have a workout in progress.")
        return redirect("workouts:active_workout", session_id=active_session.id)

    if request.method == "POST":
        form = StartWorkoutForm(request.POST)
        if form.is_valid():
            session = create_workout_session(
                request.user, name=form.cleaned_data["name"]
            )
            return redirect("workouts:active_workout", session_id=session.id)
    else:
        form = StartWorkoutForm()

    return render(request, "workouts/start_workout.html", {"form": form})


@login_required
def active_workout(request, session_id):
    """The screen used mid-workout.

    The selected exercise comes from ?exercise=<id>. Selecting one immediately
    shows what the user lifted for it last time.
    """
    session = get_user_session(request.user, session_id)  # ownership enforced

    if session.is_completed:
        messages.info(request, "That workout is already finished.")
        return redirect("workouts:home")

    selected_exercise = None
    previous_session = None
    previous_sets = []
    todays_sets = []
    next_set_number = 1

    initial = {}

    # Everything already logged in this session, so resuming shows your progress
    # instead of an empty screen.
    session_exercises = group_session_sets_by_exercise_prefetched(session)

    exercise_id = request.GET.get("exercise")
    if not exercise_id and session_exercises:
        # Resuming with no explicit choice: continue the exercise you were last
        # working on, with its sets already there.
        last_set = session.sets.order_by("-created_at", "-id").first()
        if last_set is not None:
            exercise_id = str(last_set.exercise_id)

    if exercise_id:
        selected_exercise = get_object_or_404(Exercise, pk=exercise_id)

        previous_session, previous_sets = get_previous_exercise_performance(
            request.user, selected_exercise, exclude_session=session
        )
        todays_sets = list(get_session_sets_for_exercise(session, selected_exercise))
        next_set_number = get_next_set_number(session, selected_exercise)

        # Prefill the inputs so a straight-set workout is just tap-Save-tap-Save.
        # Prefer what they already did today; fall back to last time's opener.
        reference_set = todays_sets[-1] if todays_sets else (
            previous_sets[0] if previous_sets else None
        )
        if reference_set is not None:
            initial = {"weight": reference_set.weight, "reps": reference_set.reps}

    # The "this session so far" summary lists exercises other than the one open
    # in the logging card below (which already shows its own sets).
    other_session_exercises = {
        exercise: sets
        for exercise, sets in session_exercises.items()
        if selected_exercise is None or exercise.id != selected_exercise.id
    }

    return render(
        request,
        "workouts/active_workout.html",
        {
            "session": session,
            "exercise_groups": get_exercises_grouped_by_muscle(),
            "selected_exercise": selected_exercise,
            "session_exercises": other_session_exercises,
            "previous_session": previous_session,
            "previous_sets": previous_sets,
            "todays_sets": todays_sets,
            "next_set_number": next_set_number,
            "form": WorkoutSetForm(initial=initial),
        },
    )


@login_required
@require_POST
def log_set(request, session_id):
    """Save one set, then return to the active workout on the same exercise."""
    exercise_id = request.POST.get("exercise_id")
    form = WorkoutSetForm(request.POST)

    if form.is_valid():
        try:
            create_workout_set(
                user=request.user,
                session_id=session_id,
                exercise_id=exercise_id,
                weight=form.cleaned_data["weight"],
                reps=form.cleaned_data["reps"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    else:
        # Surface the specific problem (negative weight, zero reps) rather than
        # a generic failure.
        errors = [error for errors in form.errors.values() for error in errors]
        messages.error(request, "; ".join(errors))

    redirect_url = redirect("workouts:active_workout", session_id=session_id).url
    if exercise_id:
        redirect_url = f"{redirect_url}?exercise={exercise_id}"
    return redirect(redirect_url)


@login_required
@require_POST
def save_note(request, session_id):
    """Save the workout note without finishing, then stay on the workout."""
    update_session_notes(request.user, session_id, request.POST.get("notes", ""))
    messages.success(request, "Note saved.")

    redirect_url = redirect("workouts:active_workout", session_id=session_id).url
    exercise_id = request.POST.get("exercise_id")
    if exercise_id:
        redirect_url = f"{redirect_url}?exercise={exercise_id}"
    return redirect(redirect_url)


@login_required
@require_POST
def finish_workout(request, session_id):
    """Complete the workout, saving any note written on the finish form."""
    # notes may be absent (finished from the header) or present (finish card).
    notes = request.POST.get("notes")
    session = complete_workout_session(request.user, session_id, notes=notes)
    messages.success(request, f"“{session.name}” saved.")
    return redirect("workouts:home")


@login_required
@require_POST
def delete_workout(request, session_id):
    """Delete a workout session. POST only, scoped to request.user."""
    if delete_workout_session(request.user, session_id):
        messages.success(request, "Workout deleted.")
    else:
        messages.error(request, "That workout could not be found.")
    return redirect("workouts:history")


@login_required
def history(request):
    """Workout history: the in-progress workout (with Continue / Delete) plus
    completed workouts newest first, all grouped by exercise. Own sessions only.
    """
    active_session, active_grouped = get_active_session_with_sets(request.user)

    return render(
        request,
        "workouts/history.html",
        {
            "active_session": active_session,
            "active_grouped": active_grouped,
            "history": get_history_with_grouped_sets(request.user),
        },
    )


def healthz(request):
    """Liveness probe. Public by design — it exposes no user data."""
    return JsonResponse({"status": "ok"})
