from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "category", "title", "is_read", "created_at")
    list_filter = ("category", "is_read")
    search_fields = ("recipient__username", "title", "message")
    list_select_related = ("recipient", "actor")
    readonly_fields = ("created_at",)
