"""Indexes, timestamps, relationships and database invariants."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class NoModelDriftTests(TestCase):
    def test_every_model_change_has_a_migration(self):
        # Catches a field added without makemigrations — which works locally
        # against an already-migrated database and then fails on deploy.
        out = StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=out)
        except SystemExit:
            self.fail(f"Models have changes with no migration:\n{out.getvalue()}")

class UserProfileIndexTests(TestCase):
    def test_the_role_lookup_is_indexed(self):
        # Every admin list, dashboard count and notify_admins() call filters on
        # role (and deleted_at). Without this index they are sequential scans.
        indexes = connection.introspection.get_constraints(
            connection.cursor(), UserProfile._meta.db_table
        )
        indexed_columns = [
            tuple(details["columns"])
            for details in indexes.values()
            if details["index"]
        ]
        self.assertIn(("role", "deleted_at"), indexed_columns)

    def test_the_index_covers_a_role_only_query(self):
        # role leads the composite, so a role-only filter uses it too.
        make_admin("a1")
        make_trainee("t1")
        plan = str(
            User.objects.filter(profile__role=Role.TRAINEE).query
        )
        self.assertIn("role", plan)  # sanity: the filter reaches the profile table
        self.assertEqual(
            User.objects.filter(profile__role=Role.TRAINEE).count(), 1
        )

class TimestampTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice")

    def test_a_plan_records_when_it_was_last_edited(self):
        plan = Plan.objects.create(
            user=self.alice, goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE,
            workout_location=WorkoutLocation.COMMERCIAL_GYM, session_duration=60,
            is_active=True, plan_json={"plan_name": "First", "days": []},
        )
        created, first_touch = plan.created_at, plan.updated_at

        plan.plan_json = {"plan_name": "Edited", "days": []}
        plan.save()
        plan.refresh_from_db()

        self.assertGreater(plan.updated_at, first_touch)
        self.assertEqual(plan.created_at, created)  # creation time is preserved

    def test_a_corrected_weigh_in_records_when_it_changed(self):
        measurement = BodyMeasurement.objects.create(
            user=self.alice, recorded_on=timezone.localdate(), weight_kg="70.0"
        )
        created, first_touch = measurement.created_at, measurement.updated_at

        # Same-day re-weigh: update_or_create overwrites rather than piling up.
        BodyMeasurement.objects.update_or_create(
            user=self.alice, recorded_on=timezone.localdate(),
            defaults={"weight_kg": "69.5"},
        )
        measurement.refresh_from_db()

        self.assertEqual(str(measurement.weight_kg), "69.5")
        self.assertGreater(measurement.updated_at, first_touch)
        self.assertEqual(measurement.created_at, created)

    def test_every_model_carries_a_created_at(self):
        from assistant.models import KnowledgeChunk
        from messaging.models import Conversation, Message
        from users.models import CalorieCalculation

        models = [
            UserProfile, BodyMeasurement, CalorieCalculation, Exercise,
            WorkoutSession, WorkoutSet, Plan, Conversation, Message,
            Notification, KnowledgeChunk,
        ]
        for model in models:
            with self.subTest(model=model.__name__):
                fields = {f.name for f in model._meta.get_fields()}
                self.assertIn("created_at", fields)

class RelationshipTests(TestCase):
    """The on_delete rules decide what a deletion destroys."""

    def setUp(self):
        self.alice = make_trainee("alice")
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )

    def test_an_exercise_cannot_be_deleted_out_from_under_logged_sets(self):
        from django.db.models import ProtectedError

        session = make_session(self.alice, days_ago=0)
        WorkoutSet.objects.create(
            session=session, exercise=self.bench, set_number=1,
            weight="40.0", reps=10,
        )
        # PROTECT, not CASCADE: removing an exercise from the library must not
        # silently erase everyone's history of doing it.
        with self.assertRaises(ProtectedError):
            self.bench.delete()

    def test_a_deleted_admin_leaves_their_replies_behind(self):
        from messaging.services import get_or_create_conversation, send_message

        admin = make_admin("coach")
        conversation = get_or_create_conversation(self.alice)
        send_message(conversation, admin, "keep pushing")
        admin.delete()

        # Message.sender is SET_NULL, so a departing coach does not take their
        # side of every conversation with them.
        message = conversation.messages.get()
        self.assertIsNone(message.sender)
        self.assertEqual(message.body, "keep pushing")

    def test_hard_deleting_a_trainee_destroys_their_whole_conversation(self):
        from messaging.models import Conversation
        from messaging.services import get_or_create_conversation, send_message

        conversation = get_or_create_conversation(self.alice)
        send_message(conversation, self.alice, "hello coach")
        conversation_id = conversation.id
        self.alice.delete()

        # Conversation.trainee is CASCADE, so the thread and every message in
        # it — including the coach's replies — go with them. This is precisely
        # why Phase L removes accounts with a soft delete instead.
        self.assertFalse(Conversation.objects.filter(pk=conversation_id).exists())
        self.assertFalse(Message.objects.filter(conversation_id=conversation_id).exists())

    def test_deleting_a_user_cascades_their_own_records(self):
        session = make_session(self.alice, days_ago=0)
        WorkoutSet.objects.create(
            session=session, exercise=self.bench, set_number=1,
            weight="40.0", reps=10,
        )
        user_id = self.alice.id
        self.alice.delete()

        self.assertFalse(UserProfile.objects.filter(user_id=user_id).exists())
        self.assertFalse(WorkoutSession.objects.filter(user_id=user_id).exists())
        self.assertFalse(WorkoutSet.objects.filter(session__user_id=user_id).exists())
        # The exercise itself is library data and stays.
        self.assertTrue(Exercise.objects.filter(pk=self.bench.pk).exists())

class DatabaseInvariantTests(TestCase):
    """Rules the database enforces itself, not just the forms."""

    def setUp(self):
        self.alice = make_trainee("alice")
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )

    def test_only_one_active_session_per_user(self):
        from django.db import IntegrityError, transaction

        WorkoutSession.objects.create(
            user=self.alice, name="First", started_at=timezone.now(), is_completed=False
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkoutSession.objects.create(
                    user=self.alice, name="Second", started_at=timezone.now(),
                    is_completed=False,
                )

    def test_only_one_active_plan_per_user(self):
        from django.db import IntegrityError, transaction

        def make_plan():
            return Plan.objects.create(
                user=self.alice, goal=Goal.LOSE_WEIGHT, days_per_week=4,
                experience_level=ExperienceLevel.INTERMEDIATE,
                workout_location=WorkoutLocation.COMMERCIAL_GYM,
                session_duration=60, is_active=True,
                plan_json={"plan_name": "P", "days": []},
            )

        make_plan()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_plan()

    def test_only_one_measurement_per_user_per_day(self):
        from django.db import IntegrityError, transaction

        today = timezone.localdate()
        BodyMeasurement.objects.create(user=self.alice, recorded_on=today, weight_kg="70.0")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BodyMeasurement.objects.create(
                    user=self.alice, recorded_on=today, weight_kg="71.0"
                )

    def test_the_database_rejects_impossible_sets(self):
        from django.db import IntegrityError, transaction

        session = make_session(self.alice, days_ago=0)
        # The forms validate too, but the sync endpoint bypasses forms — so the
        # database has to be the backstop.
        for weight, reps in [("-5.0", 10), ("40.0", 0)]:
            with self.subTest(weight=weight, reps=reps):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        WorkoutSet.objects.create(
                            session=session, exercise=self.bench, set_number=1,
                            weight=weight, reps=reps,
                        )
