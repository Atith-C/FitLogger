from django.contrib.auth.models import User
from django.db import models


class Category(models.TextChoices):
    MESSAGE = "MESSAGE", "Message"
    PROFILE = "PROFILE", "Profile update"
    GOAL = "GOAL", "Goal change"
    CALORIES = "CALORIES", "Calorie update"
    BODY = "BODY", "Body measurement"
    WORKOUT = "WORKOUT", "Workout"
    NEW_TRAINEE = "NEW_TRAINEE", "New trainee"
    PERMISSION = "PERMISSION", "Profile sharing"
    SYSTEM = "SYSTEM", "System"


class Notification(models.Model):
    """A single notification shown to one recipient.

    One model serves both trainee-facing and admin-facing notifications — the
    recipient decides who sees it. `link` is the path to open when clicked;
    `actor` is who triggered it (a trainee, an admin, or nobody for system).
    """

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_notifications",
    )
    category = models.CharField(max_length=20, choices=Category, default=Category.SYSTEM)
    title = models.CharField(max_length=150)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True)  # path to open on click
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
        ]

    def __str__(self):
        state = "read" if self.is_read else "unread"
        return f"[{state}] {self.recipient.username}: {self.title}"
