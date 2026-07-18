from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from messaging.services import get_or_create_conversation
from users.decorators import admin_required
from users.models import PlatformSettings
from users.services import (
    can_admin_view_profile,
    restore_trainee,
    set_trainee_blocked,
    soft_delete_trainee,
    trainee_display,
)
from workouts.forms import ExerciseForm
from workouts.services import (
    get_archived_exercises,
    get_exercises_for_admin,
    get_exercises_grouped_by_muscle,
    remove_exercise,
    restore_exercise,
)

from .services import (
    dashboard_stats,
    get_selected_exercise,
    get_trainee_or_none,
    list_trainees,
    platform_analytics,
    trainee_exercise_analytics,
    trainee_overview,
    trainee_personal_info,
)


def _trainee_or_404(trainee_id):
    """The trainee, or 404. Admin ids never resolve, so these actions cannot be
    turned on an admin — including the one making the request."""
    trainee = get_trainee_or_none(trainee_id)
    if trainee is None:
        raise Http404("No such trainee.")
    return trainee


@admin_required
def dashboard(request):
    """Admin dashboard: platform stats and quick links to each section."""
    return render(
        request,
        "adminportal/dashboard.html",
        {"stats": dashboard_stats(request.user)},
    )


@admin_required
def trainees(request):
    """Searchable, filterable directory of all trainees."""
    q = request.GET.get("q", "")
    gender = request.GET.get("gender", "")
    status = request.GET.get("status", "")
    sharing = request.GET.get("sharing", "")

    return render(
        request,
        "adminportal/trainees.html",
        {
            "trainees": list_trainees(q, gender, status, sharing),
            "q": q,
            "gender": gender,
            "status": status,
            "sharing": sharing,
        },
    )


@admin_required
def trainee_detail(request, trainee_id):
    """One trainee's page.

    Name, age, gender and chat are always available. Everything else is gated on
    the trainee having approved profile sharing — and the gate is enforced here,
    not in the template: when sharing is off, private data never enters the
    context, so there is nothing in the HTML to reveal.
    """
    trainee = _trainee_or_404(trainee_id)
    shared = can_admin_view_profile(trainee)
    context = {"trainee": trainee, "shared": shared}
    if shared:
        context["personal"] = trainee_personal_info(trainee)
        overview = trainee_overview(trainee)
        context.update(overview)
        # Chart data is prepared server-side; charts.js only renders it.
        context["charts"] = overview["charts"]

        # Exercise analytics for ?exercise=<id>. Inside the gate, so a guessed
        # exercise id against a private profile still reveals nothing.
        exercise = get_selected_exercise(request.GET.get("exercise"))
        context["exercise_groups"] = get_exercises_grouped_by_muscle()
        context["selected_exercise"] = exercise
        # charts.js draws the per-exercise lines only when this is non-empty.
        context["exercise_name"] = exercise.name if exercise else ""

        if exercise is not None:
            analytics = trainee_exercise_analytics(trainee, exercise)
            context["exercise_summary"] = analytics["summary"]
            context["exercise_history"] = analytics["history"]
            # One payload for charts.js: the weekly bars plus this exercise.
            context["charts"] = {**overview["charts"], **analytics["charts"]}

    return render(request, "adminportal/trainee_detail.html", context)


@admin_required
def open_chat(request, trainee_id):
    """Ensure the trainee's conversation exists, then open it."""
    trainee = _trainee_or_404(trainee_id)
    conversation = get_or_create_conversation(trainee)
    return redirect("adminportal:conversation", conversation_id=conversation.id)


@admin_required
@require_POST
def set_blocked(request, trainee_id):
    """Block or unblock a trainee. POST only, so a link cannot trigger it."""
    trainee = _trainee_or_404(trainee_id)
    blocked = request.POST.get("blocked") == "on"
    set_trainee_blocked(trainee, blocked)

    name = trainee_display(trainee)
    messages.success(
        request,
        f"{name} has been blocked and can no longer log in."
        if blocked
        else f"{name} can log in again.",
    )
    return redirect("adminportal:trainee_detail", trainee_id=trainee.id)


@admin_required
@require_POST
def delete_trainee(request, trainee_id):
    """Remove a trainee's account, keeping their data (see soft_delete_trainee)."""
    trainee = _trainee_or_404(trainee_id)
    soft_delete_trainee(trainee)

    messages.success(
        request,
        f"{trainee_display(trainee)} has been removed. Their data is kept and "
        f"the account can be restored.",
    )
    return redirect("adminportal:trainees")


@admin_required
@require_POST
def restore(request, trainee_id):
    """Undo a removal."""
    trainee = _trainee_or_404(trainee_id)
    restore_trainee(trainee)

    messages.success(request, f"{trainee_display(trainee)} has been restored.")
    return redirect("adminportal:trainee_detail", trainee_id=trainee.id)


@admin_required
def analytics(request):
    """Platform analytics: growth, activity, and profile distributions.

    Every series is aggregated server-side; admin_analytics.js only renders it.
    The growth chart's range comes from ?range=; the rest ignore it.
    """
    data = platform_analytics(request.GET.get("range", ""))
    return render(
        request,
        "adminportal/analytics.html",
        {
            "analytics": data,
            # (key, label) for the growth toggle, in display order.
            "ranges": [("week", "Week"), ("month", "Month"), ("year", "Year")],
        },
    )


@admin_required
def settings_view(request):
    """Admin settings: the platform-wide switches."""
    return render(
        request,
        "adminportal/settings.html",
        {"settings": PlatformSettings.load()},
    )


@admin_required
def exercises(request):
    """The exercise library manager: active exercises with usage counts, an add
    form, and the archived list."""
    return render(
        request,
        "adminportal/exercises.html",
        {
            "form": ExerciseForm(),
            "groups": get_exercises_for_admin(),
            "archived": get_archived_exercises(),
        },
    )


@admin_required
@require_POST
def add_exercise(request):
    """Create a library exercise. It appears in every trainee picker at once."""
    form = ExerciseForm(request.POST)
    if form.is_valid():
        exercise = form.save()
        messages.success(request, f"Added {exercise.name}.")
    else:
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, errors or "Could not add that exercise.")
    return redirect("adminportal:exercises")


@admin_required
@require_POST
def delete_exercise(request, exercise_id):
    """Remove an exercise — deleted if unused, archived if it has logged sets."""
    result = remove_exercise(exercise_id)
    if result == "deleted":
        messages.success(request, "Exercise deleted.")
    elif result == "archived":
        messages.success(
            request,
            "Exercise archived — it's hidden from trainees, and the workouts "
            "that logged it keep their history.",
        )
    else:
        messages.error(request, "That exercise could not be found.")
    return redirect("adminportal:exercises")


@admin_required
@require_POST
def restore_exercise_view(request, exercise_id):
    """Return an archived exercise to the library."""
    exercise = restore_exercise(exercise_id)
    if exercise is not None:
        messages.success(request, f"{exercise.name} is back in the library.")
    else:
        messages.error(request, "That exercise could not be restored.")
    return redirect("adminportal:exercises")


@admin_required
@require_POST
def update_settings(request):
    """Save the three platform switches. An unchecked box is absent from POST,
    which is exactly how a checkbox reports 'off'."""
    settings = PlatformSettings.load()
    settings.notifications_enabled = "notifications" in request.POST
    settings.messaging_enabled = "messaging" in request.POST
    settings.signups_enabled = "signups" in request.POST
    settings.save()

    messages.success(request, "Settings saved.")
    return redirect("adminportal:settings")
