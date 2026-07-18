"""Admin exercise-library management: add, delete, archive, restore."""

from adminportal.tests.helpers import *  # noqa: F401,F403

from workouts.services import (
    get_all_exercises,
    get_archived_exercises,
    remove_exercise,
    restore_exercise,
)


class RemoveExerciseServiceTests(TestCase):
    def setUp(self):
        self.exercise = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )

    def test_an_unused_exercise_is_truly_deleted(self):
        self.assertEqual(remove_exercise(self.exercise.id), "deleted")
        self.assertFalse(Exercise.objects.filter(pk=self.exercise.id).exists())

    def test_a_logged_exercise_is_archived_not_deleted(self):
        trainee = make_trainee("t1")
        session = make_session(trainee, days_ago=0)
        log_set(session, self.exercise, "40.0", 10)

        self.assertEqual(remove_exercise(self.exercise.id), "archived")
        self.exercise.refresh_from_db()
        self.assertFalse(self.exercise.is_active)          # hidden
        self.assertTrue(Exercise.objects.filter(pk=self.exercise.id).exists())  # kept
        # The logged set survives, unharmed.
        self.assertTrue(WorkoutSet.objects.filter(exercise=self.exercise).exists())

    def test_archiving_keeps_it_out_of_the_library(self):
        trainee = make_trainee("t1")
        session = make_session(trainee, days_ago=0)
        log_set(session, self.exercise, "40.0", 10)
        remove_exercise(self.exercise.id)

        self.assertNotIn(self.exercise, get_all_exercises())
        self.assertIn(self.exercise, get_archived_exercises())

    def test_remove_returns_none_for_an_unknown_id(self):
        self.assertIsNone(remove_exercise(999999))

    def test_restore_returns_it_to_the_library(self):
        trainee = make_trainee("t1")
        session = make_session(trainee, days_ago=0)
        log_set(session, self.exercise, "40.0", 10)
        remove_exercise(self.exercise.id)

        restore_exercise(self.exercise.id)
        self.exercise.refresh_from_db()
        self.assertTrue(self.exercise.is_active)
        self.assertIn(self.exercise, get_all_exercises())

    def test_restore_only_touches_archived_exercises(self):
        self.assertIsNone(restore_exercise(self.exercise.id))  # already active


class LibraryFilterTests(TestCase):
    def test_get_all_exercises_excludes_archived(self):
        active = Exercise.objects.create(name="Squat", muscle_group=MuscleGroup.QUADRICEPS)
        Exercise.objects.create(
            name="Old Machine", muscle_group=MuscleGroup.CHEST, is_active=False
        )
        names = [e.name for e in get_all_exercises()]
        self.assertIn("Squat", names)
        self.assertNotIn("Old Machine", names)


class ExercisePageTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.url = reverse("adminportal:exercises")
        self.client.force_login(self.admin)
        Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)

    def test_page_is_admin_only(self):
        self.client.force_login(make_trainee("t1"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_page_lists_exercises_and_the_add_form(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn("Bench Press", body)
        self.assertIn('name="name"', body)
        self.assertIn('name="muscle_group"', body)

    def test_settings_links_to_the_library(self):
        body = self.client.get(reverse("adminportal:settings")).content.decode()
        self.assertIn(self.url, body)


class AddExerciseTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.url = reverse("adminportal:add_exercise")
        self.client.force_login(self.admin)

    def test_adding_creates_it_and_it_reaches_the_trainee_picker(self):
        self.client.post(self.url, {
            "name": "Cable Fly", "muscle_group": MuscleGroup.CHEST, "equipment": "CABLE",
        })
        exercise = Exercise.objects.get(name="Cable Fly")
        self.assertTrue(exercise.is_active)
        self.assertIn(exercise, get_all_exercises())

    def test_the_muscle_group_dropdown_has_no_blank_option(self):
        from workouts.forms import ExerciseForm

        choices = dict(ExerciseForm().fields["muscle_group"].choices)
        self.assertNotIn("", choices)  # no "---------"
        body = self.client.get(reverse("adminportal:exercises")).content.decode()
        self.assertNotIn('<option value="">', body)

    def test_a_duplicate_name_is_rejected(self):
        Exercise.objects.create(name="Deadlift", muscle_group=MuscleGroup.BACK)
        self.client.post(self.url, {
            "name": "Deadlift", "muscle_group": MuscleGroup.BACK, "equipment": "BARBELL",
        })
        self.assertEqual(Exercise.objects.filter(name="Deadlift").count(), 1)

    def test_add_is_post_only_and_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_login(make_trainee("t1"))
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)


class DeleteRestoreEndpointTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.exercise = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )
        self.client.force_login(self.admin)

    def test_deleting_an_unused_exercise_removes_it(self):
        self.client.post(reverse("adminportal:delete_exercise", args=[self.exercise.id]))
        self.assertFalse(Exercise.objects.filter(pk=self.exercise.id).exists())

    def test_deleting_a_used_exercise_archives_it(self):
        trainee = make_trainee("t1")
        session = make_session(trainee, days_ago=0)
        log_set(session, self.exercise, "40.0", 10)

        self.client.post(reverse("adminportal:delete_exercise", args=[self.exercise.id]))
        self.exercise.refresh_from_db()
        self.assertFalse(self.exercise.is_active)

    def test_restore_endpoint_brings_it_back(self):
        self.exercise.is_active = False
        self.exercise.save(update_fields=["is_active"])
        self.client.post(reverse("adminportal:restore_exercise", args=[self.exercise.id]))
        self.exercise.refresh_from_db()
        self.assertTrue(self.exercise.is_active)

    def test_mutations_are_admin_only_and_post_only(self):
        for name in ["delete_exercise", "restore_exercise"]:
            url = reverse(f"adminportal:{name}", args=[self.exercise.id])
            with self.subTest(action=name):
                self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(make_trainee("t1"))
        self.assertEqual(
            self.client.post(
                reverse("adminportal:delete_exercise", args=[self.exercise.id])
            ).status_code,
            403,
        )
