import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from users.models import Goal, Role, Sex, UserProfile

from .models import Category, Notification
from .services import (
    create_notification,
    mark_all_read,
    mark_read,
    notify_admins,
    unread_count,
)

PASSWORD = "str0ng-pass-2026"


def make_admin(username="admin1"):
    user = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=user, role=Role.ADMIN)
    return user


def make_trainee(username="trainee1"):
    user = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=user, role=Role.TRAINEE)
    return user


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice")

    def test_create_notification(self):
        note = create_notification(self.alice, "Hello", message="Body", link="/x/")
        self.assertEqual(note.recipient, self.alice)
        self.assertFalse(note.is_read)

    def test_notify_admins_reaches_every_admin(self):
        a1, a2 = make_admin("a1"), make_admin("a2")
        notify_admins("New event", actor=self.alice, category=Category.PROFILE)

        self.assertEqual(Notification.objects.filter(recipient=a1).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=a2).count(), 1)
        # Trainees are not admins — the actor gets nothing.
        self.assertEqual(Notification.objects.filter(recipient=self.alice).count(), 0)

    def test_notify_admins_excludes_an_admin_actor(self):
        admin = make_admin("a1")
        notify_admins("Self event", actor=admin)
        self.assertEqual(Notification.objects.filter(recipient=admin).count(), 0)

    def test_unread_count(self):
        create_notification(self.alice, "1")
        create_notification(self.alice, "2")
        self.assertEqual(unread_count(self.alice), 2)

    def test_mark_read_is_scoped_to_the_user(self):
        bob = make_trainee("bob")
        bob_note = create_notification(bob, "Bob's note")

        # Alice cannot mark Bob's notification read.
        self.assertIsNone(mark_read(self.alice, bob_note.id))
        bob_note.refresh_from_db()
        self.assertFalse(bob_note.is_read)

    def test_mark_all_read(self):
        create_notification(self.alice, "1")
        create_notification(self.alice, "2")
        mark_all_read(self.alice)
        self.assertEqual(unread_count(self.alice), 0)


class TriggerTests(TestCase):
    """Trainee actions notify admins."""

    def setUp(self):
        self.admin = make_admin("theadmin")

    def _admin_notes(self, category=None):
        qs = Notification.objects.filter(recipient=self.admin)
        return qs.filter(category=category) if category else qs

    def test_new_trainee_registration_notifies_admins(self):
        self.client.post(
            reverse("users:register"),
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )
        note = self._admin_notes(Category.NEW_TRAINEE).first()
        self.assertIsNotNone(note)
        # Spec wording: the title is fixed, so the name moved to the message.
        self.assertEqual(note.title, "New Trainee Registered")
        self.assertIn("newbie", note.message)

    def test_goal_change_notifies_admins(self):
        trainee = make_trainee("gina")
        UserProfile.objects.filter(user=trainee).update(
            age=25, sex=Sex.MALE, weight_kg="70.0", height_cm=175,
            goal=Goal.BUILD_MUSCLE,
        )
        self.client.force_login(trainee)
        self.client.post(
            reverse("users:profile"),
            {
                "age": 25, "sex": Sex.MALE, "weight_kg": "70.0", "height_cm": 175,
                "goal": Goal.LOSE_WEIGHT, "days_per_week": 3,
                "experience_level": "BEGINNER",
                "workout_location": "COMMERCIAL_GYM", "session_duration": 60,
            },
        )
        note = self._admin_notes(Category.GOAL).first()
        self.assertIsNotNone(note)
        self.assertIn("goal", note.title.lower())

    def test_calorie_update_notifies_admins(self):
        trainee = make_trainee("carl")
        UserProfile.objects.filter(user=trainee).update(
            age=25, sex=Sex.MALE, height_cm=180, weight_kg="65.0"
        )
        self.client.force_login(trainee)
        self.client.post(
            reverse("analytics:calories"),
            {"age": 25, "sex": Sex.MALE, "height_cm": 180,
             "weight_kg": "65.0", "activity_level": "MODERATE"},
        )
        self.assertTrue(self._admin_notes(Category.CALORIES).exists())

    def test_body_measurement_notifies_admins(self):
        trainee = make_trainee("bella")
        UserProfile.objects.filter(user=trainee).update(height_cm=170)
        self.client.force_login(trainee)
        self.client.post(
            reverse("analytics:wellness"),
            {"recorded_on": "2026-07-16", "weight_kg": "62.0",
             "body_fat_percentage": "", "muscle_mass_kg": "", "notes": ""},
        )
        self.assertTrue(self._admin_notes(Category.BODY).exists())

    def test_an_admin_updating_their_own_profile_does_not_self_notify(self):
        # Admin editing their profile is not a trainee event.
        self.client.force_login(self.admin)
        self.client.post(
            reverse("users:profile"),
            {"age": 40, "sex": Sex.MALE, "weight_kg": "80.0", "height_cm": 180,
             "goal": Goal.STAY_FIT, "days_per_week": 3,
             "experience_level": "ADVANCED",
             "workout_location": "HOME", "session_duration": 60},
        )
        self.assertEqual(Notification.objects.count(), 0)


class NotificationViewTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice")
        self.bob = make_trainee("bob")
        self.client.force_login(self.alice)

    def test_list_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("notifications:list")).status_code, 302)

    def test_list_shows_only_the_users_own(self):
        create_notification(self.alice, "For Alice")
        create_notification(self.bob, "For Bob")

        response = self.client.get(reverse("notifications:list"))
        self.assertContains(response, "For Alice")
        self.assertNotContains(response, "For Bob")

    def test_empty_state(self):
        response = self.client.get(reverse("notifications:list"))
        self.assertContains(response, "No notifications yet")

    def test_opening_marks_read_and_redirects_to_link(self):
        note = create_notification(self.alice, "Go here", link="/home/")
        response = self.client.get(reverse("notifications:open", args=[note.id]))

        self.assertRedirects(response, "/home/", fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_opening_another_users_notification_404s(self):
        bob_note = create_notification(self.bob, "Bob's")
        response = self.client.get(reverse("notifications:open", args=[bob_note.id]))
        self.assertEqual(response.status_code, 404)

    def test_mark_all_read_button(self):
        create_notification(self.alice, "1")
        create_notification(self.alice, "2")
        self.client.post(reverse("notifications:read_all"))
        self.assertEqual(unread_count(self.alice), 0)

    def test_unread_badge_shows_in_the_navbar(self):
        create_notification(self.alice, "Ping")
        response = self.client.get(reverse("workouts:home"))
        self.assertContains(response, "fl-bell-badge")


# --------------------------------------------------------------------------
# Phase K — admin notification wording and click-through routing
# --------------------------------------------------------------------------

from django.utils import timezone as tz  # noqa: E402

from messaging.services import get_or_create_conversation, send_message  # noqa: E402
from users.forms import UserProfileForm  # noqa: E402
from users.models import ExperienceLevel, WorkoutLocation  # noqa: E402
from users.services import set_profile_sharing, update_profile  # noqa: E402


def named_trainee(username, first_name):
    user = User.objects.create_user(
        username=username, password=PASSWORD, first_name=first_name
    )
    UserProfile.objects.create(
        user=user, role=Role.TRAINEE, age=25, sex=Sex.MALE, weight_kg="70.0",
        height_cm=175, goal=Goal.BUILD_MUSCLE, days_per_week=3,
        experience_level=ExperienceLevel.BEGINNER,
        workout_location=WorkoutLocation.COMMERCIAL_GYM, session_duration=60,
    )
    return user


class NotificationWordingTests(TestCase):
    """The titles an admin reads, against the spec's examples."""

    def setUp(self):
        self.admin = make_admin("theadmin")

    def _note(self, category=None):
        qs = Notification.objects.filter(recipient=self.admin)
        if category is not None:
            qs = qs.filter(category=category)
        return qs.first()

    def _edit(self, user, **changes):
        profile = UserProfile.objects.get(user=user)
        data = {
            "age": profile.age, "sex": profile.sex, "weight_kg": profile.weight_kg,
            "height_cm": profile.height_cm, "goal": profile.goal,
            "days_per_week": profile.days_per_week,
            "experience_level": profile.experience_level,
            "workout_location": profile.workout_location,
            "session_duration": profile.session_duration,
        }
        data.update(changes)
        form = UserProfileForm(data=data, instance=profile)
        self.assertTrue(form.is_valid(), form.errors)
        update_profile(form)

    # --- the five spec examples ---

    def test_new_message_from_rahul(self):
        rahul = named_trainee("rahul", "Rahul")
        send_message(get_or_create_conversation(rahul), rahul, "hello coach")
        self.assertEqual(self._note(Category.MESSAGE).title, "New message from Rahul")

    def test_atith_updated_weight(self):
        atith = named_trainee("atith", "Atith")
        self._edit(atith, weight_kg="72.5")
        self.assertEqual(self._note(Category.PROFILE).title, "Atith updated Weight")

    def test_riya_changed_goal(self):
        riya = named_trainee("riya", "Riya")
        self._edit(riya, goal=Goal.LOSE_WEIGHT)
        self.assertEqual(self._note(Category.GOAL).title, "Riya changed Goal")

    def test_amit_enabled_profile_sharing(self):
        amit = named_trainee("amit", "Amit")
        set_profile_sharing(amit, True)
        self.assertEqual(
            self._note(Category.PERMISSION).title, "Amit enabled Profile Sharing"
        )

    def test_new_trainee_registered(self):
        self.client.post(
            reverse("users:register"),
            {"username": "newbie", "email": "n@example.com",
             "password1": PASSWORD, "password2": PASSWORD},
        )
        note = self._note(Category.NEW_TRAINEE)
        self.assertEqual(note.title, "New Trainee Registered")
        self.assertIn("newbie", note.message)

    # --- the rest of the tracked fields ---

    def test_disabling_sharing_reads_naturally_too(self):
        amit = named_trainee("amit", "Amit")
        set_profile_sharing(amit, True)
        set_profile_sharing(amit, False)
        self.assertEqual(
            self._note(Category.PERMISSION).title, "Amit disabled Profile Sharing"
        )

    def test_each_single_field_names_itself(self):
        cases = [
            ({"height_cm": 180}, "Height"),
            ({"age": 26}, "Age"),
            ({"sex": Sex.FEMALE}, "Gender"),
            ({"days_per_week": 5}, "Training Days"),
            ({"experience_level": ExperienceLevel.ADVANCED}, "Experience Level"),
            ({"workout_location": WorkoutLocation.HOME}, "Workout Location"),
            ({"session_duration": 90}, "Session Length"),
        ]
        for index, (change, label) in enumerate(cases):
            with self.subTest(label=label):
                user = named_trainee(f"t{index}", "Sam")
                self._edit(user, **change)
                note = Notification.objects.filter(
                    recipient=self.admin, actor=user
                ).first()
                self.assertEqual(note.title, f"Sam updated {label}")

    def test_a_single_change_shows_the_old_and_new_value(self):
        atith = named_trainee("atith", "Atith")
        self._edit(atith, weight_kg="72.5")
        self.assertEqual(self._note(Category.PROFILE).message, "70.0 → 72.5")

    def test_a_whole_number_weight_still_reads_consistently(self):
        # The old value is read back from the database, the new one comes off
        # the form — so "72" must not render as "70.0 → 72".
        atith = named_trainee("atith", "Atith")
        self._edit(atith, weight_kg="72")
        self.assertEqual(self._note(Category.PROFILE).message, "70.0 → 72.0")

    def test_a_choice_field_shows_labels_not_stored_keys(self):
        riya = named_trainee("riya", "Riya")
        self._edit(riya, goal=Goal.LOSE_WEIGHT)

        message = self._note(Category.GOAL).message
        self.assertEqual(message, "Build muscle → Lose weight")
        self.assertNotIn("BUILD_MUSCLE", message)

    def test_several_fields_at_once_group_into_one_notification(self):
        atith = named_trainee("atith", "Atith")
        self._edit(atith, weight_kg="72.5", height_cm=180)

        notes = Notification.objects.filter(recipient=self.admin, actor=atith)
        self.assertEqual(notes.count(), 1)  # one save, one notification
        self.assertEqual(notes.first().title, "Atith updated their profile")
        self.assertEqual(notes.first().message, "Updated: Weight, Height.")

    def test_a_username_only_trainee_falls_back_to_their_username(self):
        user = User.objects.create_user(username="nameless", password=PASSWORD)
        UserProfile.objects.create(
            user=user, role=Role.TRAINEE, age=25, sex=Sex.MALE, weight_kg="70.0",
            height_cm=175, goal=Goal.BUILD_MUSCLE, days_per_week=3,
            experience_level=ExperienceLevel.BEGINNER,
            workout_location=WorkoutLocation.COMMERCIAL_GYM, session_duration=60,
        )
        self._edit(user, weight_kg="71.0")
        self.assertEqual(self._note(Category.PROFILE).title, "nameless updated Weight")

    def test_saving_the_profile_unchanged_notifies_nobody(self):
        atith = named_trainee("atith", "Atith")
        self._edit(atith)
        self.assertEqual(Notification.objects.filter(recipient=self.admin).count(), 0)


class NotificationRoutingTests(TestCase):
    """Clicking a notification lands on the page it is about."""

    def setUp(self):
        self.admin = make_admin("theadmin")
        self.rahul = named_trainee("rahul", "Rahul")
        self.client.force_login(self.admin)

    def _open(self, note):
        return self.client.get(reverse("notifications:open", args=[note.id]))

    def _note(self, category):
        return Notification.objects.filter(
            recipient=self.admin, category=category
        ).first()

    def test_a_message_notification_opens_the_conversation(self):
        conversation = get_or_create_conversation(self.rahul)
        send_message(conversation, self.rahul, "hello coach")

        self.assertRedirects(
            self._open(self._note(Category.MESSAGE)),
            reverse("adminportal:conversation", args=[conversation.id]),
        )

    def test_a_profile_notification_opens_the_trainee(self):
        profile = UserProfile.objects.get(user=self.rahul)
        form = UserProfileForm(
            data={
                "age": 26, "sex": profile.sex, "weight_kg": profile.weight_kg,
                "height_cm": profile.height_cm, "goal": profile.goal,
                "days_per_week": profile.days_per_week,
                "experience_level": profile.experience_level,
                "workout_location": profile.workout_location,
                "session_duration": profile.session_duration,
            },
            instance=profile,
        )
        self.assertTrue(form.is_valid(), form.errors)
        update_profile(form)

        self.assertRedirects(
            self._open(self._note(Category.PROFILE)),
            reverse("adminportal:trainee_detail", args=[self.rahul.id]),
        )

    def test_a_sharing_notification_opens_the_trainee(self):
        set_profile_sharing(self.rahul, True)
        self.assertRedirects(
            self._open(self._note(Category.PERMISSION)),
            reverse("adminportal:trainee_detail", args=[self.rahul.id]),
        )

    def test_a_registration_notification_opens_the_new_trainee(self):
        self.client.logout()
        self.client.post(
            reverse("users:register"),
            {"username": "newbie", "email": "n@example.com",
             "password1": PASSWORD, "password2": PASSWORD},
        )
        newbie = User.objects.get(username="newbie")

        self.client.force_login(self.admin)
        self.assertRedirects(
            self._open(self._note(Category.NEW_TRAINEE)),
            reverse("adminportal:trainee_detail", args=[newbie.id]),
        )

    def test_opening_a_notification_marks_it_read(self):
        set_profile_sharing(self.rahul, True)
        note = self._note(Category.PERMISSION)
        self.assertFalse(note.is_read)

        self._open(note)
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_every_admin_notification_has_somewhere_to_go(self):
        set_profile_sharing(self.rahul, True)
        send_message(get_or_create_conversation(self.rahul), self.rahul, "hi")

        notes = Notification.objects.filter(recipient=self.admin)
        self.assertGreaterEqual(notes.count(), 2)
        for note in notes:
            with self.subTest(title=note.title):
                self.assertTrue(note.link, f"{note.title!r} has no link")
