from django.contrib import admin

from .models import Exercise, WorkoutSession, WorkoutSet


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("name", "muscle_group", "equipment")
    list_filter = ("muscle_group", "equipment")
    search_fields = ("name",)


class WorkoutSetInline(admin.TabularInline):
    """Sets are shown inside their session — they are never edited standalone."""

    model = WorkoutSet
    extra = 0
    fields = ("exercise", "set_number", "weight", "reps")


@admin.register(WorkoutSession)
class WorkoutSessionAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "started_at", "completed_at", "is_completed")
    list_filter = ("is_completed",)
    search_fields = ("user__username", "name")
    date_hierarchy = "started_at"
    inlines = [WorkoutSetInline]
    readonly_fields = ("created_at",)


@admin.register(WorkoutSet)
class WorkoutSetAdmin(admin.ModelAdmin):
    list_display = ("exercise", "session", "set_number", "weight", "reps", "created_at")
    list_filter = ("exercise__muscle_group",)
    search_fields = ("session__user__username", "exercise__name")
    # select_related avoids one query per row when rendering the list.
    list_select_related = ("exercise", "session", "session__user")
    readonly_fields = ("client_record_id", "created_at")
