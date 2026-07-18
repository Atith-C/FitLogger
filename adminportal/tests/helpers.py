"""Shared fixtures for the adminportal test package: factories, constants
and the imports the test modules lean on. Imported with `from .helpers
import *` so each themed module stays focused on its own cases."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from messaging.services import get_or_create_conversation, send_message
from notifications.services import create_notification
from users.models import Role, UserProfile
from adminportal.services import dashboard_stats
from users.models import Sex  # noqa: E402
from messaging.models import Conversation  # noqa: E402
from users.models import ExperienceLevel, Goal  # noqa: E402
from datetime import timedelta  # noqa: E402
from ai_planner.models import WorkoutPlan  # noqa: E402
from users.models import ActivityLevel, CalorieCalculation, WorkoutLocation  # noqa: E402
from workouts.models import Exercise, MuscleGroup, WorkoutSession, WorkoutSet  # noqa: E402
from workouts.services import workout_streak  # noqa: E402
from adminportal.services import trainee_nutrition, trainee_overview  # noqa: E402
from workouts.services import get_exercise_history  # noqa: E402
from adminportal.services import get_selected_exercise, trainee_exercise_analytics  # noqa: E402
from decimal import Decimal  # noqa: E402
from django.utils import timezone as tz  # noqa: E402
from notifications.models import Category, Notification  # noqa: E402
from notifications.services import unread_badges  # noqa: E402
from users.forms import CalorieCalculationForm, UserProfileForm  # noqa: E402
from users.models import ActivityLevel as AL  # noqa: E402
from users.services import (  # noqa: E402
    save_calorie_calculation,
    set_profile_sharing,
    update_profile,
)
from workouts.services import complete_workout_session, create_workout_session  # noqa: E402
from users.services import (  # noqa: E402
    refused_login_reason,
    restore_trainee,
    set_trainee_blocked,
    soft_delete_trainee,
)
from adminportal.services import list_trainees as list_trainees_service  # noqa: E402
from io import StringIO  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from ai_planner.models import WorkoutPlan as Plan  # noqa: E402
from messaging.models import Message  # noqa: E402
from users.models import BodyMeasurement  # noqa: E402
import json  # noqa: E402
from users.models import ExperienceLevel as EL  # noqa: E402
from adminportal.services import platform_analytics  # noqa: E402

PASSWORD = "str0ng-pass-2026"
NO_ENTRIES = "No workout entries found for this exercise."
BLOCKED_MESSAGE = "Your account has been blocked"
REMOVED_MESSAGE = "This account has been removed"
GENERIC_MESSAGE = "Incorrect username or password"

def make_admin(username="admin1"):
    u = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=u, role=Role.ADMIN)
    return u

def make_trainee(username="trainee1", **user_kwargs):
    u = User.objects.create_user(username=username, password=PASSWORD, **user_kwargs)
    UserProfile.objects.create(user=u, role=Role.TRAINEE)
    return u

def make_session(user, days_ago=0, completed=True, name="Workout"):
    """A workout session started `days_ago` days back."""
    started = timezone.now() - timedelta(days=days_ago)
    session = WorkoutSession.objects.create(
        user=user, name=name, started_at=started, is_completed=completed
    )
    if completed:
        session.completed_at = started + timedelta(hours=1)
        session.save(update_fields=["completed_at"])
    return session

def log_set(session, exercise, weight, reps, set_number=1):
    return WorkoutSet.objects.create(
        session=session, exercise=exercise, set_number=set_number,
        weight=weight, reps=reps,
    )

def admin_notes(admin, category=None):
    qs = Notification.objects.filter(recipient=admin)
    if category is not None:
        qs = qs.filter(category=category)
    return qs

def set_joined(user, days_ago):
    User.objects.filter(pk=user.pk).update(
        date_joined=timezone.now() - timezone.timedelta(days=days_ago)
    )

def set_last_login(user, days_ago):
    User.objects.filter(pk=user.pk).update(
        last_login=timezone.now() - timezone.timedelta(days=days_ago)
    )
