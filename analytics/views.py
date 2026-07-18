from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from users.forms import BodyMeasurementForm, CalorieCalculationForm
from users.services import (
    get_calorie_calculation,
    get_latest_measurement,
    get_or_create_profile,
    log_body_measurement,
    save_calorie_calculation,
)
from workouts.models import Exercise
from workouts.services import get_exercises_grouped_by_muscle

from .nutrition_data import NUTRITION_TABLE_GROUPS
from .services import (
    build_calorie_targets,
    calculate_bmr,
    calculate_maintenance_calories,
    compute_macros,
    get_calorie_target,
    get_progress_dashboard,
    get_wellness_dashboard,
)


@login_required
def progress(request):
    """Progress dashboard for one exercise, selected via ?exercise=<id>.

    All numbers are computed server-side; the browser only renders the charts.
    """
    profile = get_or_create_profile(request.user)

    selected_exercise = None
    exercise_id = request.GET.get("exercise")
    if exercise_id:
        selected_exercise = get_object_or_404(Exercise, pk=exercise_id)

    dashboard = get_progress_dashboard(
        request.user, selected_exercise, profile.days_per_week
    )

    return render(
        request,
        "analytics/progress.html",
        {
            "exercise_groups": get_exercises_grouped_by_muscle(),
            "selected_exercise": selected_exercise,
            "summary": dashboard["summary"],
            "adherence": dashboard["adherence"],
            "average_weekly_workouts": dashboard["average_weekly_workouts"],
            "planned_days_per_week": profile.days_per_week,
            # Handed to the template as a dict and rendered with the
            # json_script tag, which escapes it safely for embedding in HTML.
            "charts": dashboard["charts"],
            "exercise_name": selected_exercise.name if selected_exercise else "",
        },
    )


@login_required
def wellness(request):
    """The Wellness passport: log a weigh-in and see body-composition trends.

    GET shows the passport; POST logs a measurement (scoped to request.user).
    """
    profile = get_or_create_profile(request.user)

    if request.method == "POST":
        form = BodyMeasurementForm(request.POST)
        if form.is_valid():
            log_body_measurement(request.user, form)
            messages.success(request, "Measurement saved.")
            return redirect("analytics:wellness")
    else:
        form = BodyMeasurementForm(initial={"recorded_on": timezone.localdate()})

    dashboard = get_wellness_dashboard(request.user, height_cm=profile.height_cm)

    return render(
        request,
        "analytics/wellness.html",
        {
            "form": form,
            "dashboard": dashboard,
            "charts": dashboard["charts"],
        },
    )


@login_required
def calories(request):
    """Calorie calculator. First visit collects the inputs; after that it shows
    the saved result, with a Recalculate option for when weight or activity
    changes."""
    profile = get_or_create_profile(request.user)
    existing = get_calorie_calculation(request.user)

    if request.method == "POST":
        form = CalorieCalculationForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            bmr = calculate_bmr(
                data["sex"], data["weight_kg"], data["height_cm"], data["age"]
            )
            maintenance = calculate_maintenance_calories(bmr, data["activity_level"])
            save_calorie_calculation(
                request.user, form, int(round(bmr)), int(round(maintenance))
            )
            messages.success(request, "Your calorie targets are ready.")
            return redirect("analytics:calories")
    else:
        form = None

    # Show the form on the first visit, or when the user asks to recalculate.
    show_form = existing is None or "recalculate" in request.GET or form is not None

    if show_form and form is None:
        # Prefill from the current profile (and latest weigh-in) so a
        # recalculation picks up their up-to-date numbers automatically.
        latest = get_latest_measurement(request.user)
        initial = {
            "age": profile.age,
            "sex": profile.sex,  # synced from the fitness profile
            "height_cm": profile.height_cm,
            "weight_kg": (latest.weight_kg if latest else profile.weight_kg),
        }
        if existing:
            initial.setdefault("sex", existing.sex)
            initial.setdefault("activity_level", existing.activity_level)
        form = CalorieCalculationForm(initial=initial)

    targets = None
    if existing and not show_form:
        targets = build_calorie_targets(existing.maintenance_calories, existing.sex)

    return render(
        request,
        "analytics/calories.html",
        {
            "form": form if show_form else None,
            "show_form": show_form,
            "calculation": existing,
            "targets": targets,
        },
    )


@login_required
def calorie_guide(request):
    """Educational guidance behind the 'Know your calories' button."""
    return render(request, "analytics/calorie_guide.html")


@login_required
def nutrition(request):
    """Macro targets for a chosen goal, using the calorie figure the calorie
    calculator worked out. Falls back to a prompt if calories aren't set yet."""
    calculation = get_calorie_calculation(request.user)

    if calculation is None:
        return render(request, "analytics/nutrition.html", {"needs_calories": True})

    targets = build_calorie_targets(calculation.maintenance_calories, calculation.sex)
    goal_key = request.GET.get("goal", "maintain")
    selected = get_calorie_target(
        calculation.maintenance_calories, calculation.sex, goal_key
    )

    macros = compute_macros(selected["calories"], calculation.weight_kg)

    return render(
        request,
        "analytics/nutrition.html",
        {
            "needs_calories": False,
            "targets": targets,
            "selected": selected,
            "macros": macros,
            "table_groups": NUTRITION_TABLE_GROUPS,
        },
    )
