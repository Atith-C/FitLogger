from django.contrib.auth.models import User
from django.db import models


class JoeyMessage(models.Model):
    """One turn in a trainee's Joey conversation.

    Persisted so the chat survives navigating between pages, and deleted when
    the user logs out (see the user_logged_out receiver in apps.py) — so it
    lasts exactly one session and never carries over to the next person on a
    shared device.
    """

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="joey_messages"
    )
    role = models.CharField(max_length=10, choices=Role)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self):
        return f"{self.user.username} [{self.role}] {self.content[:40]}"


class KnowledgeChunk(models.Model):
    """One chunk of the ingested knowledge PDF, with its embedding.

    Retrieval computes cosine similarity between a question's embedding and
    these vectors in Python (no pgvector needed) — fine for the few hundred
    chunks a book produces. Re-ingesting replaces the whole set.
    """

    content = models.TextField()
    # The embedding vector as a list of floats (text-embedding-3-small -> 1536).
    embedding = models.JSONField()
    source = models.CharField(max_length=200, blank=True)  # e.g. "page 42"
    chunk_index = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["chunk_index"]

    def __str__(self):
        preview = self.content[:60].replace("\n", " ")
        return f"[{self.source or self.chunk_index}] {preview}…"
