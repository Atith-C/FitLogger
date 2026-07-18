"""Seed the starter exercise library.

Safe to run repeatedly: get_or_create means an exercise that already exists is
left untouched rather than duplicated.

    python manage.py seed_exercises
"""

from django.core.management.base import BaseCommand

from workouts.models import Equipment, Exercise, MuscleGroup

# (name, muscle_group, equipment)
STARTER_EXERCISES = [
    # Chest
    ("Bench Press", MuscleGroup.CHEST, Equipment.BARBELL),
    ("Incline Dumbbell Press", MuscleGroup.CHEST, Equipment.DUMBBELL),
    ("Chest Fly", MuscleGroup.CHEST, Equipment.CABLE),
    ("Push-Up", MuscleGroup.CHEST, Equipment.BODYWEIGHT),
    # Back
    ("Lat Pulldown", MuscleGroup.BACK, Equipment.CABLE),
    ("Pull-Up", MuscleGroup.BACK, Equipment.BODYWEIGHT),
    ("Barbell Row", MuscleGroup.BACK, Equipment.BARBELL),
    ("Seated Cable Row", MuscleGroup.BACK, Equipment.CABLE),
    ("Deadlift", MuscleGroup.BACK, Equipment.BARBELL),
    # Shoulders
    ("Overhead Press", MuscleGroup.SHOULDERS, Equipment.BARBELL),
    ("Dumbbell Shoulder Press", MuscleGroup.SHOULDERS, Equipment.DUMBBELL),
    ("Lateral Raise", MuscleGroup.SHOULDERS, Equipment.DUMBBELL),
    ("Rear Delt Fly", MuscleGroup.SHOULDERS, Equipment.DUMBBELL),
    # Quadriceps
    ("Barbell Squat", MuscleGroup.QUADRICEPS, Equipment.BARBELL),
    ("Leg Press", MuscleGroup.QUADRICEPS, Equipment.MACHINE),
    ("Leg Extension", MuscleGroup.QUADRICEPS, Equipment.MACHINE),
    ("Bulgarian Split Squat", MuscleGroup.QUADRICEPS, Equipment.DUMBBELL),
    # Hamstrings
    ("Romanian Deadlift", MuscleGroup.HAMSTRINGS, Equipment.BARBELL),
    ("Leg Curl", MuscleGroup.HAMSTRINGS, Equipment.MACHINE),
    # Glutes
    ("Hip Thrust", MuscleGroup.GLUTES, Equipment.BARBELL),
    # Calves
    ("Standing Calf Raise", MuscleGroup.CALVES, Equipment.MACHINE),
    ("Seated Calf Raise", MuscleGroup.CALVES, Equipment.MACHINE),
    # Biceps
    ("Barbell Curl", MuscleGroup.BICEPS, Equipment.BARBELL),
    ("Dumbbell Curl", MuscleGroup.BICEPS, Equipment.DUMBBELL),
    ("Hammer Curl", MuscleGroup.BICEPS, Equipment.DUMBBELL),
    # Triceps
    ("Tricep Pushdown", MuscleGroup.TRICEPS, Equipment.CABLE),
    ("Overhead Tricep Extension", MuscleGroup.TRICEPS, Equipment.DUMBBELL),
    ("Skull Crusher", MuscleGroup.TRICEPS, Equipment.BARBELL),
    # Core
    ("Plank", MuscleGroup.CORE, Equipment.BODYWEIGHT),
    ("Cable Crunch", MuscleGroup.CORE, Equipment.CABLE),
    ("Hanging Leg Raise", MuscleGroup.CORE, Equipment.BODYWEIGHT),
]


class Command(BaseCommand):
    help = "Seed the starter exercise library. Safe to run more than once."

    def handle(self, *args, **options):
        created_count = 0

        for name, muscle_group, equipment in STARTER_EXERCISES:
            _, created = Exercise.objects.get_or_create(
                name=name,
                defaults={"muscle_group": muscle_group, "equipment": equipment},
            )
            if created:
                created_count += 1
                self.stdout.write(f"  + {name}")

        skipped = len(STARTER_EXERCISES) - created_count
        self.stdout.write(
            self.style.SUCCESS(
                f"\nSeeded {created_count} new exercise(s). "
                f"{skipped} already existed and were left unchanged. "
                f"Library now holds {Exercise.objects.count()} exercises."
            )
        )
