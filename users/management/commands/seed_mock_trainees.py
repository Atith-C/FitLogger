"""Seed 30 mock trainees for testing the admin side end to end.

    python manage.py seed_mock_trainees            # create them (+ ~6 weeks of workouts)
    python manage.py seed_mock_trainees --weeks 8  # deeper workout history
    python manage.py seed_mock_trainees --clear     # remove every mock trainee

The profiles come from the FitLogger mock-data sheets. Each becomes a real
User + UserProfile — shared with the admin, active, blockable, removable — plus
a calorie calculation and recent completed workouts on their stated training
days, so the whole admin surface (trainee list, per-trainee analytics, and the
six platform charts) has real data to render.

Every mock account uses an @example.com email, which is the marker --clear keys
on. Nothing else in the app uses that domain, so cleanup can never touch a real
account. Created straight through the ORM, so no "new trainee" notifications
fire and no real user is emailed.

Idempotent: a trainee that already exists is skipped, so re-running never
duplicates. To rebuild fresh, --clear then seed again.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from analytics.services import calculate_bmr, calculate_maintenance_calories
from users.models import (
    ActivityLevel,
    CalorieCalculation,
    ExperienceLevel,
    Goal,
    Role,
    Sex,
    UserProfile,
    WorkoutLocation,
)
from workouts.models import Exercise, WorkoutSession, WorkoutSet

MOCK_DOMAIN = "@example.com"
PASSWORD = "FitLogger@2026"
DEFAULT_WEEKS = 6

# The sheets use four goals; the app has three. Strength Gain folds into Build
# Muscle — its closest fit — as agreed. The others map one to one.
GOAL_MAP = {
    "Build Muscle": Goal.BUILD_MUSCLE,
    "Weight Loss": Goal.LOSE_WEIGHT,
    "Maintain Weight": Goal.STAY_FIT,
    "Strength Gain": Goal.BUILD_MUSCLE,
}
EXP_MAP = {
    "Beginner": ExperienceLevel.BEGINNER,
    "Intermediate": ExperienceLevel.INTERMEDIATE,
    "Advanced": ExperienceLevel.ADVANCED,
}
SEX_MAP = {"Male": Sex.MALE, "Female": Sex.FEMALE}
DAY_INDEX = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
SESSION_NAMES = {
    0: "Push Day", 1: "Pull Day", 2: "Leg Day", 3: "Upper Body",
    4: "Full Body", 5: "Conditioning", 6: "Accessory",
}
EXP_MULTIPLIER = {
    ExperienceLevel.BEGINNER: 0.7,
    ExperienceLevel.INTERMEDIATE: 1.0,
    ExperienceLevel.ADVANCED: 1.3,
}

# Working-set weight (kg) for an intermediate lifter; scaled by experience and
# nudged up over the weeks for a progressive-overload feel. 0 = bodyweight.
BASE_WEIGHT = {
    "Bench Press": 50, "Incline Dumbbell Press": 22, "Lateral Raise": 9,
    "Tricep Pushdown": 25, "Leg Press": 120, "Bulgarian Split Squat": 18,
    "Plank": 0, "Push-Up": 0, "Lat Pulldown": 45, "Seated Cable Row": 45,
    "Cable Crunch": 30, "Hip Thrust": 70, "Rear Delt Fly": 9,
    "Dumbbell Shoulder Press": 18, "Leg Curl": 35, "Deadlift": 100,
    "Barbell Squat": 80, "Barbell Row": 50, "Overhead Press": 35, "Pull-Up": 0,
    "Barbell Curl": 25, "Skull Crusher": 22, "Leg Extension": 40,
    "Hammer Curl": 12, "Romanian Deadlift": 70, "Standing Calf Raise": 45,
    "Hanging Leg Raise": 0,
}

# name, email, signup, gender, age, height, weight, goal, experience,
# days/week, session minutes, favourite exercises, active weekdays
TRAINEES = [
    ("Rahul Sharma", "rahul.sharma@example.com", "08 Jul 2025", "Male", 22, 178, 71, "Build Muscle", "Intermediate", 5, 75, ["Bench Press", "Incline Dumbbell Press", "Lateral Raise", "Tricep Pushdown"], ["Mon", "Tue", "Thu", "Sat"]),
    ("Priya Patel", "priya.patel@example.com", "26 Jul 2025", "Female", 24, 164, 59, "Weight Loss", "Beginner", 4, 60, ["Leg Press", "Bulgarian Split Squat", "Plank", "Push-Up"], ["Mon", "Wed", "Fri"]),
    ("Aman Verma", "aman.verma@example.com", "14 Aug 2025", "Male", 27, 181, 84, "Weight Loss", "Beginner", 4, 55, ["Lat Pulldown", "Seated Cable Row", "Cable Crunch"], ["Tue", "Thu", "Sat"]),
    ("Sneha Reddy", "sneha.reddy@example.com", "31 Aug 2025", "Female", 23, 160, 54, "Maintain Weight", "Intermediate", 5, 70, ["Hip Thrust", "Rear Delt Fly", "Dumbbell Shoulder Press", "Leg Curl"], ["Mon", "Tue", "Fri", "Sun"]),
    ("Karan Mehta", "karan.mehta@example.com", "18 Sep 2025", "Male", 25, 176, 79, "Build Muscle", "Advanced", 6, 90, ["Deadlift", "Barbell Squat", "Bench Press", "Barbell Row"], ["Mon", "Wed", "Thu", "Fri", "Sat"]),
    ("Aditi Singh", "aditi.singh@example.com", "05 Oct 2025", "Female", 21, 167, 63, "Build Muscle", "Beginner", 4, 60, ["Dumbbell Shoulder Press", "Incline Dumbbell Press", "Hammer Curl", "Leg Extension"], ["Tue", "Thu", "Sun"]),
    ("Arjun Nair", "arjun.nair@example.com", "23 Oct 2025", "Male", 29, 182, 86, "Strength Gain", "Advanced", 6, 95, ["Deadlift", "Overhead Press", "Bench Press", "Barbell Row", "Pull-Up"], ["Mon", "Tue", "Thu", "Fri", "Sat"]),
    ("Neha Kapoor", "neha.kapoor@example.com", "09 Nov 2025", "Female", 26, 162, 57, "Weight Loss", "Intermediate", 5, 65, ["Leg Press", "Hip Thrust", "Plank", "Cable Crunch"], ["Mon", "Wed", "Fri", "Sun"]),
    ("Vivek Joshi", "vivek.joshi@example.com", "21 Nov 2025", "Male", 28, 179, 76, "Build Muscle", "Intermediate", 5, 80, ["Bench Press", "Barbell Curl", "Skull Crusher", "Lat Pulldown"], ["Tue", "Wed", "Thu", "Sat"]),
    ("Ananya Das", "ananya.das@example.com", "12 Dec 2025", "Female", 22, 165, 56, "Maintain Weight", "Beginner", 3, 50, ["Push-Up", "Leg Extension", "Lateral Raise", "Plank"], ["Wed", "Fri", "Sun"]),
    ("Rohit Malhotra", "rohit.m@example.com", "06 Jan 2026", "Male", 24, 180, 78, "Build Muscle", "Intermediate", 5, 75, ["Bench Press", "Incline Dumbbell Press", "Tricep Pushdown", "Dumbbell Shoulder Press"], ["Mon", "Tue", "Thu", "Fri"]),
    ("Meera Iyer", "meera.iyer@example.com", "14 Jan 2026", "Female", 25, 163, 60, "Weight Loss", "Intermediate", 5, 65, ["Hip Thrust", "Leg Press", "Plank", "Cable Crunch"], ["Mon", "Wed", "Fri", "Sun"]),
    ("Siddharth Gupta", "sid.gupta@example.com", "27 Jan 2026", "Male", 23, 177, 69, "Build Muscle", "Beginner", 4, 60, ["Bench Press", "Push-Up", "Hammer Curl", "Lat Pulldown"], ["Tue", "Thu", "Sat"]),
    ("Pooja Nair", "pooja.nair@example.com", "09 Feb 2026", "Female", 28, 166, 64, "Maintain Weight", "Advanced", 6, 80, ["Romanian Deadlift", "Hip Thrust", "Rear Delt Fly", "Lateral Raise"], ["Mon", "Tue", "Thu", "Sat"]),
    ("Harsh Agrawal", "harsh.agrawal@example.com", "18 Feb 2026", "Male", 26, 182, 88, "Strength Gain", "Advanced", 6, 95, ["Deadlift", "Barbell Squat", "Overhead Press", "Pull-Up"], ["Mon", "Wed", "Thu", "Fri", "Sat"]),
    ("Kavya Rao", "kavya.rao@example.com", "28 Feb 2026", "Female", 22, 161, 55, "Build Muscle", "Beginner", 4, 60, ["Incline Dumbbell Press", "Leg Extension", "Lateral Raise", "Tricep Pushdown"], ["Tue", "Thu", "Sun"]),
    ("Nikhil Jain", "nikhil.jain@example.com", "08 Mar 2026", "Male", 27, 179, 82, "Weight Loss", "Intermediate", 5, 70, ["Seated Cable Row", "Lat Pulldown", "Cable Crunch", "Plank"], ["Mon", "Wed", "Fri", "Sat"]),
    ("Riya Banerjee", "riya.b@example.com", "19 Mar 2026", "Female", 24, 165, 58, "Build Muscle", "Intermediate", 5, 70, ["Bench Press", "Dumbbell Shoulder Press", "Leg Press", "Hip Thrust"], ["Tue", "Thu", "Fri", "Sun"]),
    ("Aditya Kulkarni", "aditya.k@example.com", "25 Mar 2026", "Male", 30, 183, 91, "Weight Loss", "Advanced", 6, 90, ["Deadlift", "Barbell Row", "Pull-Up", "Standing Calf Raise"], ["Mon", "Tue", "Thu", "Fri", "Sat"]),
    ("Simran Kaur", "simran.kaur@example.com", "07 Apr 2026", "Female", 23, 168, 62, "Maintain Weight", "Beginner", 4, 55, ["Push-Up", "Leg Curl", "Rear Delt Fly", "Hanging Leg Raise"], ["Wed", "Fri", "Sun"]),
    ("Yash Thakur", "yash.thakur@example.com", "16 Apr 2026", "Male", 22, 176, 72, "Build Muscle", "Beginner", 5, 65, ["Bench Press", "Lat Pulldown", "Hammer Curl", "Leg Press"], ["Mon", "Wed", "Fri"]),
    ("Ishita Sharma", "ishita.sharma@example.com", "02 May 2026", "Female", 21, 162, 53, "Weight Loss", "Beginner", 4, 55, ["Hip Thrust", "Plank", "Push-Up", "Leg Extension"], ["Tue", "Thu", "Sun"]),
    ("Dev Bansal", "dev.bansal@example.com", "11 May 2026", "Male", 25, 181, 81, "Build Muscle", "Intermediate", 5, 80, ["Deadlift", "Bench Press", "Barbell Row", "Overhead Press"], ["Mon", "Tue", "Thu", "Sat"]),
    ("Nisha Thomas", "nisha.thomas@example.com", "22 May 2026", "Female", 27, 167, 61, "Maintain Weight", "Intermediate", 5, 70, ["Leg Curl", "Rear Delt Fly", "Lateral Raise", "Cable Crunch"], ["Mon", "Wed", "Fri"]),
    ("Akash Yadav", "akash.yadav@example.com", "05 Jun 2026", "Male", 24, 180, 85, "Strength Gain", "Advanced", 6, 95, ["Barbell Squat", "Deadlift", "Bench Press", "Pull-Up"], ["Mon", "Tue", "Thu", "Fri", "Sat"]),
    ("Tanvi Joshi", "tanvi.j@example.com", "13 Jun 2026", "Female", 23, 164, 57, "Build Muscle", "Intermediate", 5, 65, ["Incline Dumbbell Press", "Hip Thrust", "Leg Press", "Plank"], ["Tue", "Thu", "Sun"]),
    ("Mohit Soni", "mohit.soni@example.com", "21 Jun 2026", "Male", 28, 178, 83, "Weight Loss", "Intermediate", 5, 75, ["Lat Pulldown", "Seated Cable Row", "Cable Crunch", "Standing Calf Raise"], ["Mon", "Wed", "Fri"]),
    ("Sakshi Gupta", "sakshi.g@example.com", "01 Jul 2026", "Female", 24, 166, 59, "Maintain Weight", "Beginner", 4, 60, ["Push-Up", "Leg Extension", "Lateral Raise", "Plank"], ["Tue", "Thu", "Sun"]),
    ("Rohan Desai", "rohan.desai@example.com", "10 Jul 2026", "Male", 26, 182, 87, "Build Muscle", "Advanced", 6, 90, ["Deadlift", "Bench Press", "Barbell Row", "Tricep Pushdown"], ["Mon", "Tue", "Thu", "Sat"]),
    ("Aarohi Sen", "aarohi.sen@example.com", "18 Jul 2026", "Female", 22, 163, 54, "Weight Loss", "Intermediate", 5, 60, ["Hip Thrust", "Leg Press", "Cable Crunch", "Rear Delt Fly"], ["Mon", "Wed", "Fri", "Sun"]),
]


def _activity_for(days_per_week):
    if days_per_week <= 3:
        return ActivityLevel.LIGHT
    if days_per_week == 4:
        return ActivityLevel.MODERATE
    if days_per_week == 5:
        return ActivityLevel.ACTIVE
    return ActivityLevel.VERY_ACTIVE


def _last_login_offset_days(index):
    """A spread of recency so DAU/WAU/MAU all have something to show.

    None means the trainee has never logged in. The value is the number of days
    before now; the caller clamps it so a login is never before signup.
    """
    return {
        0: 0, 1: 1, 2: 3, 3: 5,          # daily / weekly
        4: 10, 5: 18, 6: 25,             # monthly
        7: 45, 8: 60,                    # lapsed
        9: None,                         # never
    }[index % 10]


class Command(BaseCommand):
    help = "Create 30 mock trainees (with workouts) for admin-side testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--weeks", type=int, default=DEFAULT_WEEKS,
            help="Weeks of recent workout history to generate (default 6, 0 = none).",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="Remove every mock (@example.com) trainee and their data, then stop.",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self._clear()
            return
        self._seed(weeks=max(0, options["weeks"]))

    def _clear(self):
        qs = User.objects.filter(email__iendswith=MOCK_DOMAIN)
        count = qs.count()
        qs.delete()  # cascades profiles, sessions, sets, calorie calcs, messages
        self.stdout.write(self.style.SUCCESS(
            f"Removed {count} mock trainee(s) and all their data."
        ))

    @transaction.atomic
    def _seed(self, weeks):
        exercises = {e.name: e for e in Exercise.objects.all()}
        today = timezone.localdate()
        this_monday = today - timedelta(days=today.weekday())

        created = skipped = sessions_made = sets_made = 0

        for index, record in enumerate(TRAINEES):
            (name, email, signup, gender, age, height, weight, goal, exp,
             days, duration, favourites, active_days) = record
            username = email.split("@")[0]

            if User.objects.filter(username=username).exists():
                skipped += 1
                continue

            first, _, last = name.partition(" ")
            joined = timezone.make_aware(
                datetime.combine(
                    datetime.strptime(signup, "%d %b %Y").date(), time(10, 0)
                )
            )

            user = User.objects.create_user(
                username=username, email=email, password=PASSWORD,
                first_name=first, last_name=last,
            )
            user.date_joined = joined
            offset = _last_login_offset_days(index)
            if offset is not None:
                user.last_login = max(joined, timezone.now() - timedelta(days=offset))
            user.save(update_fields=["date_joined", "last_login"])

            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "role": Role.TRAINEE,
                    "profile_shared": True,
                    "age": age,
                    "sex": SEX_MAP[gender],
                    "weight_kg": weight,
                    "height_cm": height,
                    "goal": GOAL_MAP[goal],
                    "days_per_week": days,
                    "experience_level": EXP_MAP[exp],
                    "workout_location": WorkoutLocation.COMMERCIAL_GYM,
                    "session_duration": duration,
                },
            )

            bmr = round(calculate_bmr(SEX_MAP[gender], weight, height, age))
            activity = _activity_for(days)
            CalorieCalculation.objects.create(
                user=user, sex=SEX_MAP[gender], activity_level=activity,
                age=age, height_cm=height, weight_kg=weight, bmr=bmr,
                maintenance_calories=round(calculate_maintenance_calories(bmr, activity)),
            )

            s, w = self._make_workouts(
                user, favourites, active_days, EXP_MAP[exp], exercises,
                this_monday, today, joined.date(), weeks,
            )
            sessions_made += s
            sets_made += w
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Created {created} trainee(s), skipped {skipped} already present. "
            f"Generated {sessions_made} workout(s) and {sets_made} set(s)."
        ))
        if created:
            self.stdout.write(f"All mock trainees share the password: {PASSWORD}")

    def _make_workouts(self, user, favourites, active_days, experience,
                       exercises, this_monday, today, signup_date, weeks):
        """Completed sessions on the trainee's training weekdays, newest weeks
        heaviest. Returns (sessions, sets) created."""
        multiplier = EXP_MULTIPLIER[experience]
        pending = []  # (session, [(exercise, set_number, weight, reps), ...])

        for w in range(weeks):
            progress = weeks - 1 - w  # older weeks lighter
            week_monday = this_monday - timedelta(weeks=w)
            for day in active_days:
                day_date = week_monday + timedelta(days=DAY_INDEX[day])
                if day_date > today or day_date < signup_date:
                    continue

                started = timezone.make_aware(
                    datetime.combine(day_date, time(18, 0))
                )
                session = WorkoutSession(
                    user=user, name=SESSION_NAMES[DAY_INDEX[day]],
                    started_at=started, is_completed=True,
                    completed_at=started + timedelta(hours=1),
                )

                specs = []
                for ex_name in favourites:
                    exercise = exercises.get(ex_name)
                    if exercise is None:
                        continue
                    base = BASE_WEIGHT.get(ex_name, 20)
                    if base == 0:
                        kg = Decimal("0")
                    else:
                        kg = Decimal(str(round(base * multiplier + 2.5 * (progress // 2), 1)))
                    for set_number in range(1, 4):
                        specs.append((exercise, set_number, kg, 8 + ((set_number + w) % 4)))
                pending.append((session, specs))

        WorkoutSession.objects.bulk_create([session for session, _ in pending])

        all_sets = [
            WorkoutSet(session=session, exercise=exercise,
                       set_number=set_number, weight=kg, reps=reps)
            for session, specs in pending
            for exercise, set_number, kg, reps in specs
        ]
        WorkoutSet.objects.bulk_create(all_sets)
        return len(pending), len(all_sets)
