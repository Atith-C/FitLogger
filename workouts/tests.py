import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands.seed_exercises import STARTER_EXERCISES
from .models import Equipment, Exercise, MuscleGroup, WorkoutSession, WorkoutSet
from .services import (
    complete_workout_session,
    create_workout_session,
    create_workout_set,
    delete_workout_session,
    get_active_workout_session,
    get_all_exercises,
    get_exercise,
    get_exercises_grouped_by_muscle,
    get_history_with_grouped_sets,
    get_home_stats,
    get_next_set_number,
    get_previous_exercise_performance,
    get_user_session,
    get_user_workout_history,
    update_session_notes,
)

PASSWORD = "str0ng-pass-2026"


class WorkoutModelTests(TestCase):
    """Phase 2: the database itself must reject invalid workout data."""

    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="pw-test-1234")
        self.other_user = User.objects.create_user(username="bob", password="pw-test-1234")
        self.bench = Exercise.objects.create(
            name="Bench Press",
            muscle_group=MuscleGroup.CHEST,
            equipment=Equipment.BARBELL,
        )
        self.session = WorkoutSession.objects.create(
            user=self.user, name="Push Day", started_at=timezone.now()
        )

    def _make_set(self, **overrides):
        fields = {
            "session": self.session,
            "exercise": self.bench,
            "set_number": 1,
            "weight": Decimal("60.00"),
            "reps": 10,
        }
        fields.update(overrides)
        return WorkoutSet.objects.create(**fields)

    def test_set_stores_decimal_weight(self):
        workout_set = self._make_set(weight=Decimal("22.50"))
        self.assertEqual(workout_set.weight, Decimal("22.50"))

    def test_set_volume_is_weight_times_reps(self):
        workout_set = self._make_set(weight=Decimal("60.00"), reps=10)
        self.assertEqual(workout_set.volume, Decimal("600.00"))

    def test_negative_weight_is_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_set(weight=Decimal("-5.00"))

    def test_zero_reps_are_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_set(reps=0)

    def test_zero_set_number_is_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_set(set_number=0)

    def test_duplicate_client_record_id_is_rejected(self):
        """Offline sync idempotency depends on this uniqueness guarantee."""
        record_id = uuid.uuid4()
        self._make_set(set_number=1, client_record_id=record_id)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_set(set_number=2, client_record_id=record_id)

    def test_user_cannot_have_two_active_sessions(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkoutSession.objects.create(
                    user=self.user, name="Leg Day", started_at=timezone.now()
                )

    def test_completing_a_session_frees_the_user_to_start_another(self):
        self.session.is_completed = True
        self.session.completed_at = timezone.now()
        self.session.save()

        second = WorkoutSession.objects.create(
            user=self.user, name="Leg Day", started_at=timezone.now()
        )
        self.assertFalse(second.is_completed)

    def test_active_session_constraint_is_per_user(self):
        """Alice having an active session must not block Bob."""
        session = WorkoutSession.objects.create(
            user=self.other_user, name="Pull Day", started_at=timezone.now()
        )
        self.assertEqual(session.user, self.other_user)

    def test_exercise_name_is_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Exercise.objects.create(
                    name="Bench Press", muscle_group=MuscleGroup.CHEST
                )


class SeedExercisesCommandTests(TestCase):
    """Phase 4: the exercise library must seed without ever duplicating."""

    def _seed(self):
        out = StringIO()
        call_command("seed_exercises", stdout=out)
        return out.getvalue()

    def test_seeding_creates_the_starter_library(self):
        self._seed()
        self.assertEqual(Exercise.objects.count(), len(STARTER_EXERCISES))

    def test_seeding_twice_does_not_duplicate(self):
        self._seed()
        first_count = Exercise.objects.count()

        self._seed()
        self.assertEqual(Exercise.objects.count(), first_count)

    def test_seeding_reports_that_nothing_was_created_on_a_rerun(self):
        self._seed()
        output = self._seed()
        self.assertIn("Seeded 0 new exercise(s)", output)

    def test_seeding_preserves_an_existing_exercise(self):
        """An exercise already in the database must not be overwritten."""
        Exercise.objects.create(
            name="Bench Press",
            muscle_group=MuscleGroup.CHEST,
            equipment=Equipment.DUMBBELL,  # deliberately different from the seed
        )
        self._seed()

        bench = Exercise.objects.get(name="Bench Press")
        self.assertEqual(bench.equipment, Equipment.DUMBBELL)
        self.assertEqual(Exercise.objects.filter(name="Bench Press").count(), 1)

    def test_every_muscle_group_is_represented(self):
        self._seed()
        seeded_groups = set(
            Exercise.objects.values_list("muscle_group", flat=True).distinct()
        )
        self.assertEqual(seeded_groups, {group.value for group in MuscleGroup})

    def test_seed_names_are_unique(self):
        names = [name for name, _, _ in STARTER_EXERCISES]
        self.assertEqual(len(names), len(set(names)))


class ExerciseSelectionServiceTests(TestCase):
    def setUp(self):
        call_command("seed_exercises", stdout=StringIO())

    def test_get_all_exercises_returns_the_library(self):
        self.assertEqual(get_all_exercises().count(), len(STARTER_EXERCISES))

    def test_get_exercise_returns_the_match(self):
        bench = Exercise.objects.get(name="Bench Press")
        self.assertEqual(get_exercise(bench.id), bench)

    def test_get_exercise_returns_none_for_an_unknown_id(self):
        """An unknown id from a client must not raise."""
        self.assertIsNone(get_exercise(999999))

    def test_exercises_are_grouped_by_muscle(self):
        grouped = get_exercises_grouped_by_muscle()

        self.assertIn("Chest", grouped)
        self.assertIn("Back", grouped)
        self.assertIn(
            "Bench Press", [exercise.name for exercise in grouped["Chest"]]
        )

    def test_grouping_covers_every_seeded_exercise(self):
        grouped = get_exercises_grouped_by_muscle()
        total = sum(len(exercises) for exercises in grouped.values())
        self.assertEqual(total, len(STARTER_EXERCISES))


class WorkoutSessionServiceTests(TestCase):
    """Phase 5: session lifecycle."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)

    def test_starting_a_workout_creates_an_active_session(self):
        session = create_workout_session(self.alice, "Push Day")

        self.assertEqual(session.user, self.alice)
        self.assertEqual(session.name, "Push Day")
        self.assertFalse(session.is_completed)
        self.assertIsNone(session.completed_at)

    def test_starting_again_resumes_the_active_session(self):
        """Pressing Start twice must not lose the workout in progress."""
        first = create_workout_session(self.alice, "Push Day")
        second = create_workout_session(self.alice, "Leg Day")

        self.assertEqual(first.id, second.id)
        self.assertEqual(second.name, "Push Day")  # original name preserved
        self.assertEqual(WorkoutSession.objects.filter(user=self.alice).count(), 1)

    def test_a_blank_name_falls_back_to_a_default(self):
        session = create_workout_session(self.alice, "   ")
        self.assertEqual(session.name, "Workout")

    def test_completing_a_session_stamps_the_finish_time(self):
        session = create_workout_session(self.alice, "Push Day")
        completed = complete_workout_session(self.alice, session.id)

        self.assertTrue(completed.is_completed)
        self.assertIsNotNone(completed.completed_at)

    def test_completing_twice_is_harmless(self):
        session = create_workout_session(self.alice, "Push Day")
        complete_workout_session(self.alice, session.id)
        first_finish = WorkoutSession.objects.get(pk=session.id).completed_at

        complete_workout_session(self.alice, session.id)
        self.assertEqual(
            WorkoutSession.objects.get(pk=session.id).completed_at, first_finish
        )

    def test_finishing_frees_the_user_to_start_a_new_workout(self):
        first = create_workout_session(self.alice, "Push Day")
        complete_workout_session(self.alice, first.id)

        second = create_workout_session(self.alice, "Leg Day")
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(second.name, "Leg Day")

    def test_bob_cannot_read_alices_session(self):
        session = create_workout_session(self.alice, "Push Day")
        with self.assertRaises(PermissionDenied):
            get_user_session(self.bob, session.id)

    def test_bob_cannot_complete_alices_session(self):
        session = create_workout_session(self.alice, "Push Day")
        with self.assertRaises(PermissionDenied):
            complete_workout_session(self.bob, session.id)

        self.assertFalse(WorkoutSession.objects.get(pk=session.id).is_completed)

    def test_active_session_is_per_user(self):
        create_workout_session(self.alice, "Push Day")
        self.assertIsNone(get_active_workout_session(self.bob))


class WorkoutSetServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )
        self.session = create_workout_session(self.alice, "Push Day")

    def test_logging_a_set(self):
        workout_set, created = create_workout_set(
            self.alice, self.session.id, self.bench.id, Decimal("60"), 10
        )

        self.assertTrue(created)
        self.assertEqual(workout_set.weight, Decimal("60"))
        self.assertEqual(workout_set.reps, 10)
        self.assertEqual(workout_set.set_number, 1)

    def test_set_numbers_increment_automatically(self):
        create_workout_set(self.alice, self.session.id, self.bench.id, Decimal("60"), 10)
        create_workout_set(self.alice, self.session.id, self.bench.id, Decimal("60"), 9)
        third, _ = create_workout_set(
            self.alice, self.session.id, self.bench.id, Decimal("55"), 10
        )

        self.assertEqual(third.set_number, 3)

    def test_set_numbers_are_tracked_per_exercise(self):
        squat = Exercise.objects.create(
            name="Barbell Squat", muscle_group=MuscleGroup.QUADRICEPS
        )
        create_workout_set(self.alice, self.session.id, self.bench.id, Decimal("60"), 10)

        first_squat, _ = create_workout_set(
            self.alice, self.session.id, squat.id, Decimal("80"), 8
        )
        self.assertEqual(first_squat.set_number, 1)

    def test_decimal_weights_are_kept(self):
        workout_set, _ = create_workout_set(
            self.alice, self.session.id, self.bench.id, Decimal("22.5"), 10
        )
        self.assertEqual(workout_set.weight, Decimal("22.5"))

    def test_negative_weight_is_rejected(self):
        with self.assertRaises(ValidationError):
            create_workout_set(
                self.alice, self.session.id, self.bench.id, Decimal("-5"), 10
            )
        self.assertEqual(WorkoutSet.objects.count(), 0)

    def test_zero_reps_are_rejected(self):
        with self.assertRaises(ValidationError):
            create_workout_set(
                self.alice, self.session.id, self.bench.id, Decimal("60"), 0
            )
        self.assertEqual(WorkoutSet.objects.count(), 0)

    def test_unknown_exercise_is_rejected(self):
        with self.assertRaises(ValidationError):
            create_workout_set(self.alice, self.session.id, 999999, Decimal("60"), 10)

    def test_bob_cannot_log_a_set_into_alices_session(self):
        with self.assertRaises(PermissionDenied):
            create_workout_set(
                self.bob, self.session.id, self.bench.id, Decimal("60"), 10
            )
        self.assertEqual(WorkoutSet.objects.count(), 0)

    def test_cannot_log_into_a_finished_workout(self):
        complete_workout_session(self.alice, self.session.id)
        with self.assertRaises(ValidationError):
            create_workout_set(
                self.alice, self.session.id, self.bench.id, Decimal("60"), 10
            )

    def test_same_client_record_id_does_not_create_a_duplicate(self):
        """The guarantee offline sync will depend on in Phase 11."""
        record_id = uuid.uuid4()

        first, created_first = create_workout_set(
            self.alice,
            self.session.id,
            self.bench.id,
            Decimal("60"),
            10,
            client_record_id=record_id,
        )
        second, created_second = create_workout_set(
            self.alice,
            self.session.id,
            self.bench.id,
            Decimal("60"),
            10,
            client_record_id=record_id,
        )

        self.assertTrue(created_first)
        self.assertFalse(created_second)  # recognised as already synced
        self.assertEqual(first.id, second.id)
        self.assertEqual(WorkoutSet.objects.count(), 1)


class PreviousExercisePerformanceTests(TestCase):
    """The core feature: what did I lift for this exercise last time?"""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )
        self.squat = Exercise.objects.create(
            name="Barbell Squat", muscle_group=MuscleGroup.QUADRICEPS
        )

    def _completed_session(self, user, name, days_ago, sets):
        started = timezone.now() - timedelta(days=days_ago)
        session = WorkoutSession.objects.create(
            user=user,
            name=name,
            started_at=started,
            completed_at=started + timedelta(hours=1),
            is_completed=True,
        )
        for number, (exercise, weight, reps) in enumerate(sets, start=1):
            WorkoutSet.objects.create(
                session=session,
                exercise=exercise,
                set_number=number,
                weight=Decimal(weight),
                reps=reps,
            )
        return session

    def test_no_history_returns_nothing(self):
        session, sets = get_previous_exercise_performance(self.alice, self.bench)

        self.assertIsNone(session)
        self.assertEqual(sets, [])

    def test_returns_the_sets_from_the_last_session(self):
        self._completed_session(
            self.alice,
            "Push Day",
            days_ago=7,
            sets=[(self.bench, "60", 10), (self.bench, "60", 9), (self.bench, "55", 10)],
        )

        session, sets = get_previous_exercise_performance(self.alice, self.bench)

        self.assertEqual(session.name, "Push Day")
        self.assertEqual(len(sets), 3)
        self.assertEqual(
            [(s.set_number, s.weight, s.reps) for s in sets],
            [
                (1, Decimal("60.00"), 10),
                (2, Decimal("60.00"), 9),
                (3, Decimal("55.00"), 10),
            ],
        )

    def test_returns_the_most_recent_session_not_an_older_one(self):
        self._completed_session(
            self.alice, "Old Push", days_ago=14, sets=[(self.bench, "50", 10)]
        )
        self._completed_session(
            self.alice, "Recent Push", days_ago=3, sets=[(self.bench, "65", 8)]
        )

        session, sets = get_previous_exercise_performance(self.alice, self.bench)

        self.assertEqual(session.name, "Recent Push")
        self.assertEqual(sets[0].weight, Decimal("65.00"))

    def test_only_returns_sets_for_the_requested_exercise(self):
        self._completed_session(
            self.alice,
            "Full Body",
            days_ago=3,
            sets=[(self.bench, "60", 10), (self.squat, "100", 5)],
        )

        _, sets = get_previous_exercise_performance(self.alice, self.bench)

        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0].exercise, self.bench)

    def test_skips_sessions_that_did_not_train_the_exercise(self):
        self._completed_session(
            self.alice, "Bench Day", days_ago=10, sets=[(self.bench, "60", 10)]
        )
        self._completed_session(
            self.alice, "Leg Day", days_ago=2, sets=[(self.squat, "100", 5)]
        )

        session, sets = get_previous_exercise_performance(self.alice, self.bench)

        self.assertEqual(session.name, "Bench Day")
        self.assertEqual(sets[0].weight, Decimal("60.00"))

    def test_ignores_unfinished_sessions(self):
        """A workout still in progress is not 'last time'."""
        self._completed_session(
            self.alice, "Completed Push", days_ago=5, sets=[(self.bench, "60", 10)]
        )

        in_progress = create_workout_session(self.alice, "Today")
        WorkoutSet.objects.create(
            session=in_progress, exercise=self.bench, set_number=1,
            weight=Decimal("70"), reps=8,
        )

        session, sets = get_previous_exercise_performance(self.alice, self.bench)

        self.assertEqual(session.name, "Completed Push")
        self.assertEqual(sets[0].weight, Decimal("60.00"))

    def test_excludes_the_current_session(self):
        self._completed_session(
            self.alice, "Last Push", days_ago=5, sets=[(self.bench, "60", 10)]
        )
        current = create_workout_session(self.alice, "Today")

        session, sets = get_previous_exercise_performance(
            self.alice, self.bench, exclude_session=current
        )

        self.assertEqual(session.name, "Last Push")

    def test_bob_does_not_see_alices_performance(self):
        self._completed_session(
            self.alice, "Push Day", days_ago=3, sets=[(self.bench, "60", 10)]
        )

        session, sets = get_previous_exercise_performance(self.bob, self.bench)

        self.assertIsNone(session)
        self.assertEqual(sets, [])


class WorkoutViewTests(TestCase):
    """The screens a user actually touches."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )
        self.client.force_login(self.alice)

    def test_start_workout_creates_a_session_and_redirects(self):
        response = self.client.post(
            reverse("workouts:start_workout"), {"name": "Push Day"}
        )

        session = WorkoutSession.objects.get(user=self.alice)
        self.assertRedirects(
            response, reverse("workouts:active_workout", args=[session.id])
        )

    def test_active_workout_shows_the_exercise_picker(self):
        session = create_workout_session(self.alice, "Push Day")
        response = self.client.get(
            reverse("workouts:active_workout", args=[session.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bench Press")

    def test_selecting_an_exercise_shows_previous_performance(self):
        old = WorkoutSession.objects.create(
            user=self.alice,
            name="Last Push",
            started_at=timezone.now() - timedelta(days=7),
            completed_at=timezone.now() - timedelta(days=7),
            is_completed=True,
        )
        WorkoutSet.objects.create(
            session=old, exercise=self.bench, set_number=1,
            weight=Decimal("60"), reps=10,
        )

        session = create_workout_session(self.alice, "Push Day")
        response = self.client.get(
            reverse("workouts:active_workout", args=[session.id]),
            {"exercise": self.bench.id},
        )

        self.assertContains(response, "Last time")
        self.assertContains(response, "60 kg × 10")

    def test_first_time_exercise_shows_a_baseline_message(self):
        session = create_workout_session(self.alice, "Push Day")
        response = self.client.get(
            reverse("workouts:active_workout", args=[session.id]),
            {"exercise": self.bench.id},
        )

        self.assertContains(response, "First time logging this exercise")

    def test_logging_a_set_through_the_view(self):
        session = create_workout_session(self.alice, "Push Day")
        self.client.post(
            reverse("workouts:log_set", args=[session.id]),
            {"exercise_id": self.bench.id, "weight": "60", "reps": "10"},
        )

        workout_set = WorkoutSet.objects.get(session=session)
        self.assertEqual(workout_set.weight, Decimal("60.00"))
        self.assertEqual(workout_set.reps, 10)

    def test_logging_a_negative_weight_through_the_view_is_rejected(self):
        session = create_workout_session(self.alice, "Push Day")
        self.client.post(
            reverse("workouts:log_set", args=[session.id]),
            {"exercise_id": self.bench.id, "weight": "-5", "reps": "10"},
        )

        self.assertEqual(WorkoutSet.objects.count(), 0)

    def test_finishing_a_workout(self):
        session = create_workout_session(self.alice, "Push Day")
        response = self.client.post(
            reverse("workouts:finish_workout", args=[session.id])
        )

        self.assertRedirects(response, reverse("workouts:home"))
        session.refresh_from_db()
        self.assertTrue(session.is_completed)

    def test_bob_cannot_open_alices_active_workout(self):
        session = create_workout_session(self.alice, "Push Day")

        self.client.force_login(self.bob)
        response = self.client.get(
            reverse("workouts:active_workout", args=[session.id])
        )

        self.assertEqual(response.status_code, 403)

    def test_bob_cannot_log_a_set_into_alices_workout_via_the_view(self):
        session = create_workout_session(self.alice, "Push Day")

        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("workouts:log_set", args=[session.id]),
            {"exercise_id": self.bench.id, "weight": "60", "reps": "10"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorkoutSet.objects.count(), 0)

    def test_start_workout_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("workouts:start_workout"))
        self.assertEqual(response.status_code, 302)

    def test_home_offers_to_resume_an_active_workout(self):
        create_workout_session(self.alice, "Push Day")
        response = self.client.get(reverse("workouts:home"))

        self.assertContains(response, "Resume workout")


class ResumeWorkoutTests(TestCase):
    """Resuming a workout shows what was already logged and continues it."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )
        self.squat = Exercise.objects.create(
            name="Barbell Squat", muscle_group=MuscleGroup.QUADRICEPS
        )
        self.session = create_workout_session(self.alice, "Push Day")
        self.client.force_login(self.alice)

    def _resume(self):
        # Resume = open the active workout with no ?exercise chosen.
        return self.client.get(
            reverse("workouts:active_workout", args=[self.session.id])
        )

    def test_a_fresh_workout_with_no_sets_shows_the_picker_prompt(self):
        response = self._resume()
        self.assertContains(response, "Choose an exercise")
        self.assertNotContains(response, "This session so far")

    def test_resuming_auto_selects_the_last_worked_exercise_with_its_sets(self):
        create_workout_set(self.alice, self.session.id, self.bench.id, Decimal("60"), 10)
        create_workout_set(self.alice, self.session.id, self.bench.id, Decimal("60"), 9)

        response = self._resume()

        # The exercise you were on is loaded, with its sets shown in the log card.
        self.assertContains(response, "Bench Press")
        self.assertContains(response, "60 kg × 10")
        self.assertContains(response, "60 kg × 9")
        # The next set continues the numbering.
        self.assertContains(response, "Set 3")

    def test_resuming_shows_other_exercises_in_the_session_summary(self):
        create_workout_set(self.alice, self.session.id, self.bench.id, Decimal("60"), 10)
        create_workout_set(self.alice, self.session.id, self.squat.id, Decimal("100"), 5)

        response = self._resume()  # auto-selects Squat (last), Bench is "other"

        self.assertContains(response, "This session so far")
        self.assertContains(response, "Bench Press")   # in the summary
        self.assertContains(response, "Continue")

    def test_the_summary_excludes_the_currently_open_exercise(self):
        create_workout_set(self.alice, self.session.id, self.bench.id, Decimal("60"), 10)

        # Only one exercise worked -> it is the open one -> no summary card.
        response = self._resume()
        self.assertNotContains(response, "This session so far")

    def test_continue_link_reopens_a_specific_exercise(self):
        create_workout_set(self.alice, self.session.id, self.bench.id, Decimal("60"), 10)
        create_workout_set(self.alice, self.session.id, self.squat.id, Decimal("100"), 5)

        response = self.client.get(
            reverse("workouts:active_workout", args=[self.session.id]),
            {"exercise": self.bench.id},
        )
        self.assertContains(response, "Bench Press")
        self.assertContains(response, "60 kg × 10")


class MobileWorkoutUxTests(TestCase):
    """Phase 9: the active workout screen is used one-handed, mid-set."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )
        self.session = create_workout_session(self.alice, "Push Day")
        self.client.force_login(self.alice)

    def _open(self):
        return self.client.get(
            reverse("workouts:active_workout", args=[self.session.id]),
            {"exercise": self.bench.id},
        )

    def test_weight_and_rep_steppers_are_present(self):
        response = self._open()

        self.assertContains(response, "fl-step-btn")
        self.assertContains(response, 'data-step="2.5"')
        self.assertContains(response, 'data-step="-1"')

    def test_inputs_prefill_from_the_last_set_logged_today(self):
        create_workout_set(
            self.alice, self.session.id, self.bench.id, Decimal("62.5"), 8
        )

        response = self._open()
        body = response.content.decode()

        self.assertIn('value="62.50"', body)  # DecimalField renders 2 places
        self.assertIn('value="8"', body)

    def test_no_template_comment_leaks_into_the_page(self):
        """Django's {# #} is single-line only. A multi-line one is not parsed as
        a comment and renders as visible text on the page."""
        response = self._open()
        self.assertNotContains(response, "{#")

    def test_inputs_prefill_from_last_time_when_nothing_logged_today(self):
        old = WorkoutSession.objects.create(
            user=self.alice,
            name="Last Push",
            started_at=timezone.now() - timedelta(days=7),
            completed_at=timezone.now() - timedelta(days=7),
            is_completed=True,
        )
        WorkoutSet.objects.create(
            session=old, exercise=self.bench, set_number=1,
            weight=Decimal("60"), reps=10,
        )

        response = self._open()
        self.assertIn('value="60.00"', response.content.decode())

    def test_a_brand_new_exercise_prefills_nothing(self):
        response = self._open()
        self.assertContains(response, "First time logging this exercise")

    def test_the_bottom_tab_bar_is_rendered_for_logged_in_users(self):
        response = self.client.get(reverse("workouts:home"))
        self.assertContains(response, "fl-tabbar")

    def test_anonymous_visitors_get_no_tab_bar(self):
        self.client.logout()
        response = self.client.get(reverse("users:login"))
        self.assertNotContains(response, "fl-tabbar")

    def test_the_current_tab_is_marked_for_screen_readers(self):
        """Active state must not be communicated by colour alone."""
        response = self.client.get(reverse("workouts:history"))
        self.assertContains(response, 'aria-current="page"')


class WorkoutHistoryServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)

    def _completed(self, user, name, days_ago):
        started = timezone.now() - timedelta(days=days_ago)
        return WorkoutSession.objects.create(
            user=user, name=name, started_at=started,
            completed_at=started, is_completed=True,
        )

    def test_history_is_newest_first(self):
        self._completed(self.alice, "Old", days_ago=10)
        self._completed(self.alice, "New", days_ago=1)

        history = list(get_user_workout_history(self.alice))
        self.assertEqual([s.name for s in history], ["New", "Old"])

    def test_history_excludes_unfinished_workouts(self):
        self._completed(self.alice, "Done", days_ago=2)
        create_workout_session(self.alice, "In progress")

        history = list(get_user_workout_history(self.alice))
        self.assertEqual([s.name for s in history], ["Done"])

    def test_history_is_isolated_per_user(self):
        self._completed(self.alice, "Alice Push", days_ago=1)
        self._completed(self.bob, "Bob Push", days_ago=1)

        history = list(get_user_workout_history(self.alice))
        self.assertEqual([s.name for s in history], ["Alice Push"])


class WorkoutNotesTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        self.session = create_workout_session(self.alice, "Push Day")
        self.client.force_login(self.alice)

    def test_a_note_can_be_saved_without_finishing(self):
        update_session_notes(self.alice, self.session.id, "Felt strong today.")

        self.session.refresh_from_db()
        self.assertEqual(self.session.notes, "Felt strong today.")
        self.assertFalse(self.session.is_completed)  # saving a note does not finish

    def test_finishing_saves_the_note(self):
        complete_workout_session(self.alice, self.session.id, notes="Tough session.")

        self.session.refresh_from_db()
        self.assertTrue(self.session.is_completed)
        self.assertEqual(self.session.notes, "Tough session.")

    def test_the_note_is_shown_in_history(self):
        complete_workout_session(self.alice, self.session.id, notes="Great pump.")

        response = self.client.get(reverse("workouts:history"))
        self.assertContains(response, "Great pump.")

    def test_saving_a_note_through_the_view(self):
        self.client.post(
            reverse("workouts:save_note", args=[self.session.id]),
            {"notes": "Left knee felt off."},
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.notes, "Left knee felt off.")

    def test_bob_cannot_note_alices_workout(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("workouts:save_note", args=[self.session.id]),
            {"notes": "hacked"},
        )
        self.assertEqual(response.status_code, 403)
        self.session.refresh_from_db()
        self.assertEqual(self.session.notes, "")


class DeleteWorkoutTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        self.client.force_login(self.alice)

    def _finished(self, user, name):
        return WorkoutSession.objects.create(
            user=user, name=name, started_at=timezone.now(),
            completed_at=timezone.now(), is_completed=True,
        )

    # --- service ---

    def test_deleting_removes_the_session_and_its_sets(self):
        session = create_workout_session(self.alice, "Push Day")
        bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        create_workout_set(self.alice, session.id, bench.id, Decimal("60"), 10)

        self.assertTrue(delete_workout_session(self.alice, session.id))
        self.assertFalse(WorkoutSession.objects.filter(pk=session.id).exists())
        self.assertEqual(WorkoutSet.objects.count(), 0)  # sets cascade

    def test_a_user_cannot_delete_another_users_workout(self):
        bob_session = self._finished(self.bob, "Bob Push")
        self.assertFalse(delete_workout_session(self.alice, bob_session.id))
        self.assertTrue(WorkoutSession.objects.filter(pk=bob_session.id).exists())

    # --- view ---

    def test_deleting_an_unfinished_workout_through_the_view(self):
        session = create_workout_session(self.alice, "Push Day")
        response = self.client.post(reverse("workouts:delete_workout", args=[session.id]))

        self.assertRedirects(response, reverse("workouts:history"))
        self.assertFalse(WorkoutSession.objects.filter(pk=session.id).exists())

    def test_deleting_a_finished_workout_through_the_view(self):
        session = self._finished(self.alice, "Old Junk Workout")
        self.client.post(reverse("workouts:delete_workout", args=[session.id]))
        self.assertFalse(WorkoutSession.objects.filter(pk=session.id).exists())

    def test_delete_requires_post(self):
        session = create_workout_session(self.alice, "Push Day")
        response = self.client.get(reverse("workouts:delete_workout", args=[session.id]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(WorkoutSession.objects.filter(pk=session.id).exists())

    def test_bob_cannot_delete_alices_workout_through_the_view(self):
        session = create_workout_session(self.alice, "Push Day")
        self.client.force_login(self.bob)
        self.client.post(reverse("workouts:delete_workout", args=[session.id]))
        self.assertTrue(WorkoutSession.objects.filter(pk=session.id).exists())


class HistoryPageActiveSessionTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.client.force_login(self.alice)

    def test_history_shows_a_start_button_when_no_active_workout(self):
        response = self.client.get(reverse("workouts:history"))
        self.assertContains(response, "Start a new workout")

    def test_history_shows_the_in_progress_workout_with_continue_and_delete(self):
        create_workout_session(self.alice, "Ongoing Session")
        response = self.client.get(reverse("workouts:history"))

        self.assertContains(response, "Ongoing Session")
        self.assertContains(response, "In progress")
        self.assertContains(response, "Continue")
        self.assertContains(response, "Resume workout")

    def test_finished_workouts_are_labelled_finished(self):
        WorkoutSession.objects.create(
            user=self.alice, name="Done Session", started_at=timezone.now(),
            completed_at=timezone.now(), is_completed=True,
        )
        response = self.client.get(reverse("workouts:history"))
        self.assertContains(response, "Workout finished")


class HistoryPageTests(TestCase):
    """Phase 6: the history page."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )
        self.incline = Exercise.objects.create(
            name="Incline Dumbbell Press", muscle_group=MuscleGroup.CHEST
        )
        self.client.force_login(self.alice)

    def _completed_session(self, user, name, days_ago, sets):
        started = timezone.now() - timedelta(days=days_ago)
        session = WorkoutSession.objects.create(
            user=user, name=name, started_at=started,
            completed_at=started + timedelta(hours=1), is_completed=True,
        )
        counters = {}
        for exercise, weight, reps in sets:
            counters[exercise.id] = counters.get(exercise.id, 0) + 1
            WorkoutSet.objects.create(
                session=session, exercise=exercise,
                set_number=counters[exercise.id],
                weight=Decimal(weight), reps=reps,
            )
        return session

    def test_empty_history_shows_a_prompt(self):
        response = self.client.get(reverse("workouts:history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No completed workouts yet")

    def test_history_shows_a_completed_session(self):
        self._completed_session(
            self.alice, "Push Day", days_ago=1,
            sets=[(self.bench, "60", 10), (self.bench, "60", 9)],
        )

        response = self.client.get(reverse("workouts:history"))

        self.assertContains(response, "Push Day")
        self.assertContains(response, "Bench Press")
        self.assertContains(response, "60 kg × 10")
        self.assertContains(response, "60 kg × 9")

    def test_sets_are_grouped_under_their_exercise(self):
        self._completed_session(
            self.alice, "Push Day", days_ago=1,
            sets=[
                (self.bench, "60", 10),
                (self.incline, "22.5", 10),
                (self.bench, "55", 10),
            ],
        )

        history = get_history_with_grouped_sets(self.alice)
        session, grouped = history[0]

        self.assertEqual(len(grouped), 2)  # two exercises, not three set rows
        self.assertEqual(len(grouped[self.bench]), 2)
        self.assertEqual(len(grouped[self.incline]), 1)

    def test_grouped_sets_keep_set_order(self):
        self._completed_session(
            self.alice, "Push Day", days_ago=1,
            sets=[(self.bench, "60", 10), (self.bench, "60", 9), (self.bench, "55", 10)],
        )

        _, grouped = get_history_with_grouped_sets(self.alice)[0]
        self.assertEqual(
            [s.set_number for s in grouped[self.bench]], [1, 2, 3]
        )

    def test_newest_session_appears_first(self):
        self._completed_session(
            self.alice, "Older Push", days_ago=10, sets=[(self.bench, "50", 10)]
        )
        self._completed_session(
            self.alice, "Newer Push", days_ago=1, sets=[(self.bench, "60", 10)]
        )

        response = self.client.get(reverse("workouts:history"))
        body = response.content.decode()

        self.assertLess(body.index("Newer Push"), body.index("Older Push"))

    def test_unfinished_workouts_are_not_in_the_finished_list(self):
        """An unfinished workout is excluded from the completed history, though
        the page now surfaces it separately as the in-progress workout."""
        create_workout_session(self.alice, "Still Going")

        finished = get_history_with_grouped_sets(self.alice)
        self.assertEqual(finished, [])

        response = self.client.get(reverse("workouts:history"))
        self.assertContains(response, "In progress")  # shown as active, not finished

    def test_history_shows_only_the_users_own_workouts(self):
        self._completed_session(
            self.alice, "Alice Push", days_ago=1, sets=[(self.bench, "60", 10)]
        )
        self._completed_session(
            self.bob, "Bob Secret Session", days_ago=1, sets=[(self.bench, "100", 5)]
        )

        response = self.client.get(reverse("workouts:history"))

        self.assertContains(response, "Alice Push")
        self.assertNotContains(response, "Bob Secret Session")
        self.assertNotContains(response, "100 kg × 5")

    def test_history_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("workouts:history"))
        self.assertEqual(response.status_code, 302)

    def test_history_does_not_issue_a_query_per_session(self):
        """Guards against N+1: the query count must not grow with the number
        of sessions. Ten sessions must cost the same as two."""
        for day in range(2):
            self._completed_session(
                self.alice, f"Workout {day}", days_ago=day + 1,
                sets=[(self.bench, "60", 10), (self.incline, "22.5", 8)],
            )

        with self.assertNumQueries(3):  # sessions, sets, exercises
            get_history_with_grouped_sets(self.alice)

        for day in range(2, 10):
            self._completed_session(
                self.alice, f"Workout {day}", days_ago=day + 1,
                sets=[(self.bench, "60", 10), (self.incline, "22.5", 8)],
            )

        with self.assertNumQueries(3):  # unchanged with 5x the data
            get_history_with_grouped_sets(self.alice)


class HomeStatsTests(TestCase):
    """The dashboard headline numbers must count completed work only, and must
    never leak another user's training into your totals."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST, equipment=Equipment.BARBELL
        )

    def _completed(self, user, name, days_ago, sets):
        started = timezone.now() - timedelta(days=days_ago)
        session = WorkoutSession.objects.create(
            user=user, name=name, started_at=started,
            completed_at=started + timedelta(hours=1), is_completed=True,
        )
        for number, (weight, reps) in enumerate(sets, start=1):
            WorkoutSet.objects.create(
                session=session, exercise=self.bench, set_number=number,
                weight=Decimal(weight), reps=reps,
            )
        return session

    def test_empty_history_returns_zeros_not_none(self):
        stats = get_home_stats(self.alice, planned_days_per_week=3)

        self.assertEqual(stats["total_workouts"], 0)
        self.assertEqual(stats["total_volume_kg"], 0)
        self.assertEqual(stats["total_sets"], 0)
        self.assertEqual(stats["week_percentage"], 0)
        self.assertIsNone(stats["last_session"])
        self.assertEqual(stats["recent_sessions"], [])

    def test_volume_is_summed_across_sets(self):
        self._completed(self.alice, "Push", days_ago=1, sets=[("60", 10), ("60", 5)])

        stats = get_home_stats(self.alice, planned_days_per_week=3)

        self.assertEqual(stats["total_volume_kg"], Decimal("900.00"))  # 600 + 300
        self.assertEqual(stats["total_sets"], 2)
        self.assertEqual(stats["total_workouts"], 1)

    def test_an_active_session_is_not_counted(self):
        create_workout_session(self.alice, "In progress")

        stats = get_home_stats(self.alice, planned_days_per_week=3)

        self.assertEqual(stats["total_workouts"], 0)

    def test_another_users_work_is_excluded(self):
        self._completed(self.bob, "Bob's push", days_ago=1, sets=[("100", 10)])

        stats = get_home_stats(self.alice, planned_days_per_week=3)

        self.assertEqual(stats["total_workouts"], 0)
        self.assertEqual(stats["total_volume_kg"], 0)

    def test_week_percentage_is_capped_at_100(self):
        for day in range(5):
            self._completed(self.alice, f"W{day}", days_ago=0, sets=[("60", 10)])

        stats = get_home_stats(self.alice, planned_days_per_week=3)

        self.assertEqual(stats["this_week"], 5)
        self.assertEqual(stats["week_percentage"], 100)  # 5/3 would be 167%

    def test_week_percentage_is_zero_when_no_plan_is_set(self):
        self._completed(self.alice, "Push", days_ago=0, sets=[("60", 10)])

        stats = get_home_stats(self.alice, planned_days_per_week=0)

        self.assertEqual(stats["week_percentage"], 0)

    def test_recent_sessions_are_newest_first_and_capped(self):
        for day in range(5):
            self._completed(self.alice, f"Session {day}", days_ago=day, sets=[("60", 10)])

        stats = get_home_stats(self.alice, planned_days_per_week=3)

        self.assertEqual(len(stats["recent_sessions"]), 3)
        self.assertEqual(stats["recent_sessions"][0].name, "Session 0")
        self.assertEqual(stats["last_session"].name, "Session 0")

    def test_dashboard_cost_does_not_grow_with_history(self):
        """The dashboard is the most-hit page in the app. Its query count must
        be flat: five sessions and fifty must cost the same."""
        for day in range(5):
            self._completed(self.alice, f"Session {day}", days_ago=day, sets=[("60", 10)])

        with self.assertNumQueries(5):
            get_home_stats(self.alice, planned_days_per_week=3)

        for day in range(5, 50):
            self._completed(self.alice, f"Session {day}", days_ago=day, sets=[("60", 10)])

        with self.assertNumQueries(5):  # unchanged with 10x the history
            get_home_stats(self.alice, planned_days_per_week=3)

    def test_volume_is_a_decimal_even_when_zero(self):
        """Callers format this with floatformat; a type that flips between
        Decimal and int depending on the data is a trap."""
        stats = get_home_stats(self.alice, planned_days_per_week=3)

        self.assertIsInstance(stats["total_volume_kg"], Decimal)


class LandingPageTests(TestCase):
    """/ must be reachable signed out — it is the app's front door."""

    def test_landing_is_public(self):
        response = self.client.get(reverse("workouts:landing"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "landing.html")

    def test_landing_redirects_signed_in_users_to_the_dashboard(self):
        User.objects.create_user(username="alice", password=PASSWORD)
        self.client.login(username="alice", password=PASSWORD)

        response = self.client.get(reverse("workouts:landing"))

        self.assertRedirects(response, reverse("workouts:home"))

    def test_landing_offers_signup_and_login(self):
        response = self.client.get(reverse("workouts:landing"))

        self.assertContains(response, reverse("users:register"))
        self.assertContains(response, reverse("users:login"))
