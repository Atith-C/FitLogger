from django.contrib import admin

from .models import KnowledgeChunk


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ("chunk_index", "source", "created_at")
    search_fields = ("content", "source")
    # The embedding is a 1536-number blob — never edit it by hand.
    readonly_fields = ("embedding", "created_at")
