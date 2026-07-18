from django.contrib import admin

from .models import WorkoutPlan


@admin.register(WorkoutPlan)
class WorkoutPlanAdmin(admin.ModelAdmin):
    list_display = ("user", "goal", "days_per_week", "experience_level", "is_active", "created_at")
    list_filter = ("is_active", "goal", "experience_level")
    search_fields = ("user__username",)
    readonly_fields = ("plan_json", "analytics_snapshot", "created_at")
