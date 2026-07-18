import logging
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from users.services import get_or_create_profile

from .models import WorkoutPlan
from .services import (
    PlanGenerationError,
    delete_plan as delete_plan_service,
    generate_initial_plan,
    get_active_plan,
    get_plan_history,
    save_edited_plan,
)
from .validators import PlanValidationError

logger = logging.getLogger(__name__)

_DAY_FIELD = re.compile(r"^day_(\d+)_(name|focus)$")
_EX_FIELD = re.compile(r"^day_(\d+)_ex_(\d+)_(name|sets|reps|notes)$")


def _parse_plan_form(post):
    """Rebuild the plan_json structure from the edit form's POST data.

    Field names look like day_0_name / day_0_ex_1_sets. Indices are scanned
    (not assumed contiguous), so removing a day or exercise leaves no gap that
    breaks parsing. Blank exercise rows and fully-empty days are dropped, which
    is how the form expresses "remove this".
    """
    day_meta = {}   # day_index -> {name, focus}
    ex_data = {}    # day_index -> {ex_index -> {name, sets, reps, notes}}

    for key in post:
        day_match = _DAY_FIELD.match(key)
        if day_match:
            di, field = int(day_match.group(1)), day_match.group(2)
            day_meta.setdefault(di, {})[field] = post.get(key, "")
            continue
        ex_match = _EX_FIELD.match(key)
        if ex_match:
            di, ei, field = int(ex_match.group(1)), int(ex_match.group(2)), ex_match.group(3)
            ex_data.setdefault(di, {}).setdefault(ei, {})[field] = post.get(key, "")

    days = []
    for di in sorted(day_meta):
        exercises = []
        for ei in sorted(ex_data.get(di, {})):
            cells = ex_data[di][ei]
            name = (cells.get("name") or "").strip()
            if not name:
                continue  # blank row = removed exercise
            try:
                sets_value = int((cells.get("sets") or "").strip())
            except ValueError:
                sets_value = -1  # invalid; validation will reject it
            exercises.append(
                {
                    "exercise": name,
                    "sets": sets_value,
                    "rep_range": (cells.get("reps") or "").strip(),
                    "notes": (cells.get("notes") or "").strip(),
                }
            )

        day_name = (day_meta[di].get("name") or "").strip()
        if not day_name and not exercises:
            continue  # empty day = removed day

        days.append(
            {
                "day_number": len(days) + 1,
                "day_name": day_name,
                "focus": (day_meta[di].get("focus") or "").strip(),
                "exercises": exercises,
            }
        )

    return {
        "plan_name": post.get("plan_name", "").strip(),
        "summary": post.get("summary", "").strip(),
        "days": days,
    }


@login_required
def generate_plan(request):
    """Confirm the profile, then generate a plan from it."""
    profile = get_or_create_profile(request.user)

    if request.method == "POST":
        try:
            plan = generate_initial_plan(request.user)
        except PlanGenerationError as exc:
            # exc carries a user-safe message; the technical cause is in the log.
            messages.error(request, str(exc))
            return redirect("ai_planner:generate_plan")

        messages.success(request, "Your new workout plan is ready.")
        return redirect("ai_planner:current_plan")

    return render(
        request,
        "ai_planner/generate_plan.html",
        {"profile": profile, "has_existing_plan": get_active_plan(request.user) is not None},
    )


@login_required
def current_plan(request):
    """The user's active plan, plus their archived ones."""
    plan = get_active_plan(request.user)

    history = get_plan_history(request.user)
    if plan is not None:
        history = history.exclude(pk=plan.pk)

    return render(
        request,
        "ai_planner/current_plan.html",
        {"plan": plan, "history": history},
    )


@login_required
def plan_detail(request, plan_id):
    """Reopen an archived plan. Scoped to request.user, so a guessed id in the
    URL cannot open somebody else's plan."""
    plan = get_object_or_404(WorkoutPlan, pk=plan_id, user=request.user)

    return render(
        request,
        "ai_planner/current_plan.html",
        {"plan": plan, "history": get_plan_history(request.user).exclude(pk=plan.pk)},
    )


@login_required
def edit_plan(request, plan_id):
    """Edit one of the user's plans by hand, then save.

    Scoped to request.user. On a validation error the submitted (unsaved) edits
    are shown again so nothing is lost.
    """
    plan = get_object_or_404(WorkoutPlan, pk=plan_id, user=request.user)

    if request.method == "POST":
        plan_dict = _parse_plan_form(request.POST)
        try:
            save_edited_plan(request.user, plan_id, plan_dict)
        except PlanValidationError as exc:
            messages.error(request, f"Could not save: {exc}")
            return render(
                request,
                "ai_planner/edit_plan.html",
                {"plan": plan, "plan_data": plan_dict},
            )

        messages.success(request, "Plan saved.")
        return redirect("ai_planner:plan_detail", plan_id=plan.id)

    return render(
        request,
        "ai_planner/edit_plan.html",
        {"plan": plan, "plan_data": plan.plan_json},
    )


@login_required
@require_POST
def delete_plan(request, plan_id):
    """Delete one of the user's plans. POST only, so a link or image tag cannot
    trigger it, and scoped to request.user so nobody deletes another's plan."""
    if delete_plan_service(request.user, plan_id):
        messages.success(request, "Workout plan deleted.")
    else:
        messages.error(request, "That plan could not be found.")

    return redirect("ai_planner:current_plan")
