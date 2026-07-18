from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from users.models import ExperienceLevel, Goal, WorkoutLocation


class WorkoutPlan(models.Model):
    """An AI-generated training plan.

    The profile fields are copied here rather than read through the user's
    profile, so a historical plan still records the inputs it was generated
    from even after the user changes their profile.

    Plans are never deleted. Generating a new plan deactivates the previous
    active one, preserving history.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="workout_plans"
    )

    # Profile snapshot at generation time.
    goal = models.CharField(max_length=20, choices=Goal)
    days_per_week = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    experience_level = models.CharField(max_length=20, choices=ExperienceLevel)
    workout_location = models.CharField(max_length=20, choices=WorkoutLocation)
    session_duration = models.PositiveSmallIntegerField()

    # The validated plan returned by Claude. Only stored after passing schema
    # validation in ai_planner.validators.
    plan_json = models.JSONField()

    # The analytics summary passed to the model, kept for traceability: it
    # explains why this plan looks the way it does. Empty for a first plan
    # generated with no workout history.
    analytics_snapshot = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Plans are editable, so created_at alone would misreport a plan the user
    # has since reworked as untouched since generation.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]
        constraints = [
            # A user can have at most one active plan. Enforced by the database
            # so a race between two generations cannot leave two plans active.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_active=True),
                name="one_active_plan_per_user",
            ),
        ]

    def __str__(self):
        name = self.plan_json.get("plan_name", "Workout plan") if self.plan_json else "Workout plan"
        state = "active" if self.is_active else "archived"
        return f"{self.user.username} — {name} ({state})"
