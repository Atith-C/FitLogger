import uuid

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models


class MuscleGroup(models.TextChoices):
    CHEST = "CHEST", "Chest"
    BACK = "BACK", "Back"
    SHOULDERS = "SHOULDERS", "Shoulders"
    QUADRICEPS = "QUADRICEPS", "Quadriceps"
    HAMSTRINGS = "HAMSTRINGS", "Hamstrings"
    GLUTES = "GLUTES", "Glutes"
    BICEPS = "BICEPS", "Biceps"
    TRICEPS = "TRICEPS", "Triceps"
    CALVES = "CALVES", "Calves"
    CORE = "CORE", "Core"


class Equipment(models.TextChoices):
    BARBELL = "BARBELL", "Barbell"
    DUMBBELL = "DUMBBELL", "Dumbbell"
    MACHINE = "MACHINE", "Machine"
    CABLE = "CABLE", "Cable"
    BODYWEIGHT = "BODYWEIGHT", "Bodyweight"
    OTHER = "OTHER", "Other"


class Exercise(models.Model):
    """A movement in the exercise library. Shared by all users, seeded via
    the seed_exercises management command."""

    name = models.CharField(max_length=100, unique=True)
    muscle_group = models.CharField(max_length=20, choices=MuscleGroup)
    equipment = models.CharField(
        max_length=20, choices=Equipment, default=Equipment.OTHER
    )
    # Archived when an admin removes an exercise that trainees have already
    # logged: it drops out of every picker and the AI planner (get_all_exercises
    # filters on this), but stays attached to the historical sets that PROTECT
    # would otherwise forbid deleting.
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["muscle_group", "name"]

    def __str__(self):
        return self.name


class WorkoutSession(models.Model):
    """A single training session belonging to exactly one user.

    A session is "active" while is_completed is False. Finishing the workout
    sets completed_at and flips is_completed to True.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="workout_sessions"
    )
    name = models.CharField(max_length=100, default="Workout")
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    # A free-text note about the session (how it felt, what to change next time).
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at"]  # history shows newest first
        indexes = [
            # Drives the history page and every analytics query, which always
            # filter by user and completion state.
            models.Index(fields=["user", "-started_at"]),
            models.Index(fields=["user", "is_completed"]),
        ]
        constraints = [
            # A user may only have one unfinished session at a time. The service
            # layer resumes the existing session rather than creating a second.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_completed=False),
                name="one_active_session_per_user",
            ),
        ]

    def __str__(self):
        state = "completed" if self.is_completed else "active"
        return f"{self.user.username} — {self.name} ({state})"


class WorkoutSet(models.Model):
    """One logged set: a weight lifted for a number of reps.

    client_record_id is generated in the browser before the set is sent to the
    server, so an offline set that gets retried on reconnect is recognised as
    the same record instead of being inserted twice.
    """

    session = models.ForeignKey(
        WorkoutSession, on_delete=models.CASCADE, related_name="sets"
    )
    exercise = models.ForeignKey(
        Exercise, on_delete=models.PROTECT, related_name="sets"
    )
    set_number = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,  # supports 22.5, 27.5 etc.
        validators=[MinValueValidator(0)],
        help_text="Weight in kg. 0 is allowed for bodyweight exercises.",
    )
    reps = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    client_record_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["exercise__name", "set_number"]
        indexes = [
            models.Index(fields=["session", "exercise"]),
            models.Index(fields=["exercise", "created_at"]),
        ]
        constraints = [
            # Enforced by the database, so invalid numbers cannot slip in
            # through the sync endpoint even if a validator is bypassed.
            models.CheckConstraint(
                condition=models.Q(weight__gte=0), name="weight_not_negative"
            ),
            models.CheckConstraint(condition=models.Q(reps__gte=1), name="reps_positive"),
            models.CheckConstraint(
                condition=models.Q(set_number__gte=1), name="set_number_positive"
            ),
        ]

    def __str__(self):
        return f"{self.exercise.name} — set {self.set_number}: {self.weight} kg x {self.reps}"

    @property
    def volume(self):
        """Set volume = weight x reps. Used by the analytics service."""
        return self.weight * self.reps
