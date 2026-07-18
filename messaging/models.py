from django.contrib.auth.models import User
from django.db import models


class Conversation(models.Model):
    """One thread per trainee, shared with the admin(s).

    The trainee owns exactly one conversation; any admin can read and reply to
    it. Per-side last-read timestamps drive the unread badges.
    """

    trainee = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="conversation"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    trainee_last_read_at = models.DateTimeField(null=True, blank=True)
    admin_last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]

    def __str__(self):
        return f"Conversation with {self.trainee.username}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    # Sender is the trainee or an admin. SET_NULL so deleting an admin does not
    # erase the history.
    sender = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="sent_messages"
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self):
        who = self.sender.username if self.sender else "deleted"
        return f"{who}: {self.body[:40]}"
