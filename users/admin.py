from django.contrib import admin

from .models import BodyMeasurement, CalorieCalculation, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "goal", "experience_level", "days_per_week", "workout_location")
    list_filter = ("goal", "experience_level", "workout_location")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BodyMeasurement)
class BodyMeasurementAdmin(admin.ModelAdmin):
    list_display = ("user", "recorded_on", "weight_kg", "body_fat_percentage", "muscle_mass_kg")
    list_filter = ("recorded_on",)
    search_fields = ("user__username",)
    date_hierarchy = "recorded_on"
    list_select_related = ("user",)


@admin.register(CalorieCalculation)
class CalorieCalculationAdmin(admin.ModelAdmin):
    list_display = ("user", "sex", "activity_level", "bmr", "maintenance_calories", "updated_at")
    list_filter = ("sex", "activity_level")
    search_fields = ("user__username",)
    list_select_related = ("user",)
