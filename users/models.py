from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Goal(models.TextChoices):
    BUILD_MUSCLE = "BUILD_MUSCLE", "Build muscle"
    LOSE_WEIGHT = "LOSE_WEIGHT", "Lose weight"
    STAY_FIT = "STAY_FIT", "Stay fit"


class ExperienceLevel(models.TextChoices):
    BEGINNER = "BEGINNER", "Beginner"
    INTERMEDIATE = "INTERMEDIATE", "Intermediate"
    ADVANCED = "ADVANCED", "Advanced"


class WorkoutLocation(models.TextChoices):
    COMMERCIAL_GYM = "COMMERCIAL_GYM", "Commercial gym"
    HOME = "HOME", "Home"
    LIMITED_EQUIPMENT = "LIMITED_EQUIPMENT", "Limited equipment"


class Sex(models.TextChoices):
    # Male/female because the BMR formula (calorie calculator) is sex-specific.
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"


class Role(models.TextChoices):
    """Access role. Public signup only ever creates a TRAINEE; ADMIN is granted
    solely through the seed_admin management command."""

    TRAINEE = "TRAINEE", "Trainee"
    ADMIN = "ADMIN", "Admin"


class UserProfile(models.Model):
    """Fitness profile for a user.

    Drives AI plan generation and the adherence calculation (which compares
    completed sessions against days_per_week).
    """

    MIN_AGE = 13
    MAX_AGE = 100
    MIN_WEIGHT_KG = 20
    MAX_WEIGHT_KG = 400
    MIN_HEIGHT_CM = 90
    MAX_HEIGHT_CM = 250
    MIN_DAYS_PER_WEEK = 1
    MAX_DAYS_PER_WEEK = 7
    MIN_SESSION_DURATION = 10
    MAX_SESSION_DURATION = 240

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    # Access role. Defaults to TRAINEE; only seed_admin grants ADMIN. The
    # frontend never sets this — role is enforced entirely server-side.
    role = models.CharField(max_length=10, choices=Role, default=Role.TRAINEE)

    # Whether the trainee lets admins view their full profile. Private by
    # default; the trainee opts in from their profile page.
    profile_shared = models.BooleanField(default=False)

    # Soft deletion. Set when an admin removes the account: every row is kept,
    # but the trainee disappears from admin lists and counts and cannot log in.
    # A hard delete would cascade through their plans, sessions, sets,
    # measurements, calorie calculations, notifications and conversation, so
    # removal is recorded rather than destructive. Distinct from is_active,
    # which is blocking — a blocked account is still a live account.
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Body stats. null=True so existing profiles and the profile created
    # automatically at registration are valid without these values; the form
    # still requires them, so the app collects them on first edit.
    age = models.PositiveSmallIntegerField(
        null=True,
        validators=[MinValueValidator(MIN_AGE), MaxValueValidator(MAX_AGE)],
        help_text="Your age in years.",
    )
    sex = models.CharField(
        max_length=6,
        choices=Sex,
        null=True,
        help_text="Used for calorie estimates and to tailor your plan.",
    )
    weight_kg = models.DecimalField(
        null=True,
        max_digits=5,
        decimal_places=1,  # supports 74.5 kg
        validators=[
            MinValueValidator(MIN_WEIGHT_KG),
            MaxValueValidator(MAX_WEIGHT_KG),
        ],
        help_text="Your body weight in kilograms.",
    )
    height_cm = models.PositiveSmallIntegerField(
        null=True,
        validators=[MinValueValidator(MIN_HEIGHT_CM), MaxValueValidator(MAX_HEIGHT_CM)],
        help_text="Your height in centimetres.",
    )

    goal = models.CharField(max_length=20, choices=Goal, default=Goal.BUILD_MUSCLE)
    days_per_week = models.PositiveSmallIntegerField(
        default=3,
        validators=[
            MinValueValidator(MIN_DAYS_PER_WEEK),
            MaxValueValidator(MAX_DAYS_PER_WEEK),
        ],
        help_text="Planned training days per week (1-7).",
    )
    experience_level = models.CharField(
        max_length=20, choices=ExperienceLevel, default=ExperienceLevel.BEGINNER
    )
    workout_location = models.CharField(
        max_length=20, choices=WorkoutLocation, default=WorkoutLocation.COMMERCIAL_GYM
    )
    session_duration = models.PositiveSmallIntegerField(
        default=60,
        validators=[
            MinValueValidator(MIN_SESSION_DURATION),
            MaxValueValidator(MAX_SESSION_DURATION),
        ],
        help_text="Typical session length in minutes.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # The admin portal's hottest lookup. Every trainee list, dashboard
            # count and notify_admins() call filters on role, and since soft
            # deletion also on deleted_at. Composite rather than two indexes:
            # role leads, so role-only queries use this one too.
            models.Index(fields=["role", "deleted_at"]),
        ]

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_trainee(self):
        return self.role == Role.TRAINEE

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def __str__(self):
        return f"{self.user.username} — {self.get_goal_display()}"


class BodyMeasurement(models.Model):
    """A dated body-composition entry — the digitised weigh-in ritual.

    Weight is required; body fat and muscle mass are optional, since not every
    scale reports them. One entry per user per day: the service uses
    update_or_create so a re-weigh on the same day replaces rather than piling
    up. This is the time series behind the Wellness passport trends.
    """

    MIN_WEIGHT_KG = 20
    MAX_WEIGHT_KG = 400
    MIN_BODY_FAT = 1
    MAX_BODY_FAT = 70
    MIN_MUSCLE_KG = 10
    MAX_MUSCLE_KG = 150

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="body_measurements"
    )
    recorded_on = models.DateField()
    weight_kg = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        validators=[
            MinValueValidator(MIN_WEIGHT_KG),
            MaxValueValidator(MAX_WEIGHT_KG),
        ],
        help_text="Body weight in kilograms.",
    )
    body_fat_percentage = models.DecimalField(
        null=True,
        blank=True,
        max_digits=4,
        decimal_places=1,
        validators=[
            MinValueValidator(MIN_BODY_FAT),
            MaxValueValidator(MAX_BODY_FAT),
        ],
        help_text="Body fat percentage, if your scale reports it.",
    )
    muscle_mass_kg = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=1,
        validators=[
            MinValueValidator(MIN_MUSCLE_KG),
            MaxValueValidator(MAX_MUSCLE_KG),
        ],
        help_text="Muscle mass in kilograms, if your scale reports it.",
    )
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # A re-weigh on the same day overwrites the entry via update_or_create, so
    # created_at alone cannot say when the number was last corrected.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-recorded_on"]
        indexes = [models.Index(fields=["user", "-recorded_on"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "recorded_on"],
                name="one_measurement_per_user_per_day",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} — {self.weight_kg} kg on {self.recorded_on}"


class ActivityLevel(models.TextChoices):
    # Labels and the multipliers (in analytics.services) mirror calculator.net.
    SEDENTARY = "SEDENTARY", "Sedentary: little or no exercise"
    LIGHT = "LIGHT", "Light: exercise 1–3 times/week"
    MODERATE = "MODERATE", "Moderate: exercise 4–5 times/week"
    ACTIVE = "ACTIVE", "Active: daily exercise or intense exercise 3–4 times/week"
    VERY_ACTIVE = "VERY_ACTIVE", "Very active: intense exercise 6–7 times/week"
    EXTRA_ACTIVE = "EXTRA_ACTIVE", "Extra active: very intense exercise daily, or a physical job"


class CalorieCalculation(models.Model):
    """A saved calorie (TDEE) calculation.

    Stores the inputs it was based on plus the computed BMR and maintenance
    calories, so the calorie page shows a returning user their result without
    re-entering anything. Recalculating overwrites this one entry (the user
    keeps a single current target, not a history).
    """

    MIN_AGE = 15
    MAX_AGE = 80
    MIN_HEIGHT_CM = 90
    MAX_HEIGHT_CM = 250
    MIN_WEIGHT_KG = 20
    MAX_WEIGHT_KG = 400

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="calorie_calculation"
    )

    # Inputs (snapshot at calculation time).
    sex = models.CharField(max_length=6, choices=Sex)
    activity_level = models.CharField(max_length=20, choices=ActivityLevel)
    age = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(MIN_AGE), MaxValueValidator(MAX_AGE)]
    )
    height_cm = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(MIN_HEIGHT_CM), MaxValueValidator(MAX_HEIGHT_CM)]
    )
    weight_kg = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        validators=[MinValueValidator(MIN_WEIGHT_KG), MaxValueValidator(MAX_WEIGHT_KG)],
    )

    # Computed results.
    bmr = models.PositiveIntegerField()
    maintenance_calories = models.PositiveIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} — {self.maintenance_calories} kcal maintenance"


class PlatformSettings(models.Model):
    """Platform-wide switches the admin controls from the Settings page.

    A singleton — there is only ever one row (pk=1). Read it through
    PlatformSettings.load(), which creates it with everything on if it does not
    exist yet, so the platform behaves as "open" until an admin decides
    otherwise. Kept in the users app because every gate that reads it (messaging,
    notifications, registration) already imports users, so there is no import
    cycle.
    """

    notifications_enabled = models.BooleanField(
        default=True,
        help_text="When off, admins stop receiving new notifications.",
    )
    messaging_enabled = models.BooleanField(
        default=True,
        help_text="When off, trainees cannot message the admin.",
    )
    signups_enabled = models.BooleanField(
        default=True,
        help_text="When off, new trainees cannot register.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform settings"
        verbose_name_plural = "Platform settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce the singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Platform settings"
