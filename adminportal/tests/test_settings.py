"""Admin Settings: the three platform switches and the flows they gate."""

import json

from adminportal.tests.helpers import *  # noqa: F401,F403

from notifications.services import notify_admins
from users.models import PlatformSettings


class PlatformSettingsModelTests(TestCase):
    def test_load_is_a_singleton_defaulting_to_on(self):
        first = PlatformSettings.load()
        second = PlatformSettings.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PlatformSettings.objects.count(), 1)
        self.assertTrue(first.notifications_enabled)
        self.assertTrue(first.messaging_enabled)
        self.assertTrue(first.signups_enabled)

    def test_save_cannot_create_a_second_row(self):
        PlatformSettings.load()
        PlatformSettings(notifications_enabled=False).save()
        self.assertEqual(PlatformSettings.objects.count(), 1)
        self.assertFalse(PlatformSettings.load().notifications_enabled)


class SettingsPageTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.url = reverse("adminportal:settings")
        self.save_url = reverse("adminportal:update_settings")
        self.client.force_login(self.admin)

    def test_page_is_admin_only(self):
        self.client.force_login(make_trainee("t1"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_page_shows_the_three_switches(self):
        body = self.client.get(self.url).content.decode()
        for name in ["notifications", "messaging", "signups"]:
            self.assertIn(f'name="{name}"', body)

    def test_switches_reflect_the_current_state(self):
        PlatformSettings.objects.update_or_create(
            pk=1, defaults={"messaging_enabled": False}
        )
        body = self.client.get(self.url).content.decode()
        # A checked box for notifications (on), none for messaging (off).
        self.assertRegex(body, r'name="notifications"[^>]*checked')
        self.assertNotRegex(body, r'name="messaging"[^>]*checked')

    def test_saving_reads_checkboxes_present_as_on_absent_as_off(self):
        # Only notifications ticked -> messaging and signups turn off.
        self.client.post(self.save_url, {"notifications": "on"})
        settings = PlatformSettings.load()
        self.assertTrue(settings.notifications_enabled)
        self.assertFalse(settings.messaging_enabled)
        self.assertFalse(settings.signups_enabled)

    def test_saving_all_three_turns_everything_on(self):
        PlatformSettings.objects.update_or_create(
            pk=1, defaults={"notifications_enabled": False,
                            "messaging_enabled": False, "signups_enabled": False}
        )
        self.client.post(
            self.save_url, {"notifications": "on", "messaging": "on", "signups": "on"}
        )
        settings = PlatformSettings.load()
        self.assertTrue(settings.notifications_enabled)
        self.assertTrue(settings.messaging_enabled)
        self.assertTrue(settings.signups_enabled)

    def test_save_is_admin_only_and_post_only(self):
        self.assertEqual(self.client.get(self.save_url).status_code, 405)
        self.client.force_login(make_trainee("t2"))
        self.assertEqual(self.client.post(self.save_url).status_code, 403)


class NotificationSwitchTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.trainee = make_trainee("t1")

    def _set(self, on):
        PlatformSettings.objects.update_or_create(
            pk=1, defaults={"notifications_enabled": on}
        )

    def test_admins_are_notified_when_the_switch_is_on(self):
        self._set(True)
        notify_admins("Something happened", actor=self.trainee)
        self.assertEqual(Notification.objects.filter(recipient=self.admin).count(), 1)

    def test_no_notification_is_created_when_the_switch_is_off(self):
        self._set(False)
        result = notify_admins("Silent event", actor=self.trainee)
        self.assertEqual(result, [])
        self.assertEqual(Notification.objects.filter(recipient=self.admin).count(), 0)

    def test_the_triggering_action_still_succeeds_with_notifications_off(self):
        # A trainee completing a workout should not fail just because the admin
        # muted notifications — the notify call no-ops, the workout still saves.
        self._set(False)
        from workouts.services import complete_workout_session, create_workout_session

        bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        session = create_workout_session(self.trainee, "Chest Day")
        WorkoutSet.objects.create(
            session=session, exercise=bench, set_number=1, weight="40.0", reps=10
        )
        finished = complete_workout_session(self.trainee, session.id)
        self.assertTrue(finished.is_completed)
        self.assertEqual(Notification.objects.filter(recipient=self.admin).count(), 0)


class MessagingSwitchTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.trainee = make_trainee("t1")
        self.conversation = get_or_create_conversation(self.trainee)
        self.url = reverse("messaging:send", args=[self.conversation.id])

    def _set(self, on):
        PlatformSettings.objects.update_or_create(
            pk=1, defaults={"messaging_enabled": on}
        )

    def _send(self, body="hello"):
        return self.client.post(
            self.url, data=json.dumps({"body": body}), content_type="application/json"
        )

    def test_a_trainee_can_message_when_the_switch_is_on(self):
        self._set(True)
        self.client.force_login(self.trainee)
        self.assertEqual(self._send().status_code, 200)
        self.assertEqual(self.conversation.messages.count(), 1)

    def test_a_trainee_is_refused_with_a_message_when_the_switch_is_off(self):
        self._set(False)
        self.client.force_login(self.trainee)
        response = self._send()
        self.assertEqual(response.status_code, 403)
        self.assertIn("can't message the admin", response.json()["error"])
        self.assertEqual(self.conversation.messages.count(), 0)

    def test_the_admin_can_still_reply_when_messaging_is_off(self):
        self._set(False)
        self.client.force_login(self.admin)
        self.assertEqual(self._send("keep going").status_code, 200)
        self.assertEqual(self.conversation.messages.count(), 1)


class SignupSwitchTests(TestCase):
    def setUp(self):
        self.url = reverse("users:register")

    def _set(self, on):
        PlatformSettings.objects.update_or_create(pk=1, defaults={"signups_enabled": on})

    def _register(self, username="newbie"):
        return self.client.post(
            self.url,
            {"username": username, "email": f"{username}@example.com",
             "password1": PASSWORD, "password2": PASSWORD},
        )

    def test_signup_works_when_the_switch_is_on(self):
        self._set(True)
        self._register("opener")
        self.assertTrue(User.objects.filter(username="opener").exists())

    def test_the_page_shows_the_closed_notice_when_the_switch_is_off(self):
        self._set(False)
        body = self.client.get(self.url).content.decode()
        self.assertIn("FitLogger is not accepting new users for now", body)
        self.assertNotIn('name="username"', body)  # the form is gone

    def test_posting_to_register_creates_nothing_when_signups_are_off(self):
        self._set(False)
        self._register("sneaky")
        self.assertFalse(User.objects.filter(username="sneaky").exists())

    def test_reopening_signups_lets_people_register_again(self):
        self._set(False)
        self._register("blocked")
        self.assertFalse(User.objects.filter(username="blocked").exists())
        self._set(True)
        self._register("welcomed")
        self.assertTrue(User.objects.filter(username="welcomed").exists())
