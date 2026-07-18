"""Blocking, soft deletion, restore, and the blocked-login flow."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class BlockingServiceTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice", first_name="Alice")

    def test_blocking_deactivates_the_account(self):
        set_trainee_blocked(self.alice, True)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_active)

    def test_unblocking_reactivates(self):
        set_trainee_blocked(self.alice, True)
        set_trainee_blocked(self.alice, False)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_active)

    def test_blocking_is_not_deletion(self):
        set_trainee_blocked(self.alice, True)
        self.assertFalse(self.alice.profile.is_deleted)

    def test_blocking_keeps_every_row(self):
        bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        session = make_session(self.alice, days_ago=0, name="Chest Day")
        WorkoutSet.objects.create(
            session=session, exercise=bench, set_number=1, weight="40.0", reps=10
        )
        set_trainee_blocked(self.alice, True)

        self.assertTrue(WorkoutSession.objects.filter(user=self.alice).exists())
        self.assertTrue(WorkoutSet.objects.filter(session__user=self.alice).exists())
        self.assertTrue(UserProfile.objects.filter(user=self.alice).exists())

class SoftDeleteServiceTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice", first_name="Alice")

    def test_removal_marks_and_deactivates(self):
        soft_delete_trainee(self.alice)
        self.alice.refresh_from_db()

        self.assertTrue(self.alice.profile.is_deleted)
        self.assertIsNotNone(self.alice.profile.deleted_at)
        self.assertFalse(self.alice.is_active)

    def test_removal_keeps_every_row(self):
        bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        session = make_session(self.alice, days_ago=0, name="Chest Day")
        WorkoutSet.objects.create(
            session=session, exercise=bench, set_number=1, weight="40.0", reps=10
        )
        create_notification(self.alice, "Keep me")

        soft_delete_trainee(self.alice)

        # The whole point of soft deletion: nothing cascades away.
        self.assertTrue(User.objects.filter(pk=self.alice.pk).exists())
        self.assertTrue(UserProfile.objects.filter(user=self.alice).exists())
        self.assertTrue(WorkoutSession.objects.filter(user=self.alice).exists())
        self.assertTrue(WorkoutSet.objects.filter(session__user=self.alice).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.alice).exists())

    def test_removing_twice_keeps_the_first_timestamp(self):
        soft_delete_trainee(self.alice)
        first = UserProfile.objects.get(user=self.alice).deleted_at
        soft_delete_trainee(self.alice)
        self.assertEqual(UserProfile.objects.get(user=self.alice).deleted_at, first)

    def test_restore_undoes_a_removal(self):
        soft_delete_trainee(self.alice)
        restore_trainee(self.alice)
        self.alice.refresh_from_db()

        self.assertFalse(self.alice.profile.is_deleted)
        self.assertTrue(self.alice.is_active)

    def test_restoring_a_live_account_changes_nothing(self):
        restore_trainee(self.alice)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_active)

class BlockedLoginTests(TestCase):
    """Blocked and removed accounts cannot log in, and are told why — but only
    once they have proved the password."""

    def setUp(self):
        self.alice = make_trainee("alice", first_name="Alice")
        self.url = reverse("users:login")

    def _login(self, password=PASSWORD, username="alice"):
        return self.client.post(
            self.url,
            {"username": username, "password": password, "as_role": "trainee"},
            follow=True,
        )

    def test_a_live_trainee_can_log_in(self):
        response = self._login()
        self.assertTrue(response.context["user"].is_authenticated)

    def test_a_blocked_trainee_cannot_log_in(self):
        set_trainee_blocked(self.alice, True)
        response = self._login()
        self.assertFalse(response.context["user"].is_authenticated)

    def test_a_blocked_trainee_is_told_the_account_is_blocked(self):
        set_trainee_blocked(self.alice, True)
        body = self._login().content.decode()
        self.assertIn(BLOCKED_MESSAGE, body)
        self.assertNotIn(GENERIC_MESSAGE, body)

    def test_a_removed_trainee_is_told_the_account_is_removed(self):
        soft_delete_trainee(self.alice)
        body = self._login().content.decode()
        self.assertIn(REMOVED_MESSAGE, body)
        self.assertNotIn(BLOCKED_MESSAGE, body)

    def test_a_wrong_password_on_a_blocked_account_reveals_nothing(self):
        # Otherwise this page becomes a username probe.
        set_trainee_blocked(self.alice, True)
        body = self._login(password="wrong-password").content.decode()

        self.assertIn(GENERIC_MESSAGE, body)
        self.assertNotIn(BLOCKED_MESSAGE, body)

    def test_a_wrong_password_on_a_removed_account_reveals_nothing(self):
        soft_delete_trainee(self.alice)
        body = self._login(password="wrong-password").content.decode()

        self.assertIn(GENERIC_MESSAGE, body)
        self.assertNotIn(REMOVED_MESSAGE, body)

    def test_an_unknown_username_reveals_nothing(self):
        body = self._login(username="nobody").content.decode()
        self.assertIn(GENERIC_MESSAGE, body)

    def test_unblocking_lets_them_back_in(self):
        set_trainee_blocked(self.alice, True)
        set_trainee_blocked(self.alice, False)
        self.assertTrue(self._login().context["user"].is_authenticated)

    def test_restoring_lets_them_back_in(self):
        soft_delete_trainee(self.alice)
        restore_trainee(self.alice)
        self.assertTrue(self._login().context["user"].is_authenticated)

    def test_blocking_kills_a_session_already_signed_in(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("workouts:home")).status_code, 200)

        set_trainee_blocked(self.alice, True)

        # ModelBackend re-checks is_active on every request, so the open
        # session stops working at the next click rather than lasting forever.
        response = self.client.get(reverse("workouts:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

class RefusedLoginReasonTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice")

    def test_none_for_a_live_account(self):
        self.assertIsNone(refused_login_reason("alice", PASSWORD))

    def test_none_for_an_unknown_username(self):
        self.assertIsNone(refused_login_reason("nobody", PASSWORD))

    def test_none_when_the_password_is_wrong(self):
        set_trainee_blocked(self.alice, True)
        self.assertIsNone(refused_login_reason("alice", "wrong-password"))

    def test_blocked(self):
        set_trainee_blocked(self.alice, True)
        self.assertEqual(refused_login_reason("alice", PASSWORD), "blocked")

    def test_removed_beats_blocked(self):
        soft_delete_trainee(self.alice)
        self.assertEqual(refused_login_reason("alice", PASSWORD), "removed")

class UserManagementViewTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        self.detail = reverse("adminportal:trainee_detail", args=[self.alice.id])
        self.client.force_login(self.admin)

    def _post(self, name, data=None, trainee=None):
        return self.client.post(
            reverse(f"adminportal:{name}", args=[(trainee or self.alice).id]), data or {}
        )

    # --- block ---

    def test_block_deactivates_and_redirects_back(self):
        response = self._post("set_blocked", {"blocked": "on"})
        self.assertRedirects(response, self.detail)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_active)

    def test_unblock_reactivates(self):
        set_trainee_blocked(self.alice, True)
        self._post("set_blocked", {"blocked": "off"})
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_active)

    # --- remove / restore ---

    def test_remove_soft_deletes_and_returns_to_the_list(self):
        response = self._post("delete_trainee")
        self.assertRedirects(response, reverse("adminportal:trainees"))
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.profile.is_deleted)
        self.assertFalse(self.alice.is_active)

    def test_restore_brings_them_back(self):
        soft_delete_trainee(self.alice)
        response = self._post("restore")
        self.assertRedirects(response, self.detail)
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.profile.is_deleted)

    # --- method and permission guards ---

    def test_all_three_actions_are_post_only(self):
        for name in ["set_blocked", "delete_trainee", "restore"]:
            with self.subTest(action=name):
                response = self.client.get(
                    reverse(f"adminportal:{name}", args=[self.alice.id])
                )
                self.assertEqual(response.status_code, 405)

    def test_all_three_actions_are_admin_only(self):
        self.client.force_login(self.alice)
        for name in ["set_blocked", "delete_trainee", "restore"]:
            with self.subTest(action=name):
                self.assertEqual(self._post(name).status_code, 403)

    def test_an_admin_cannot_be_blocked_or_removed(self):
        # get_trainee_or_none only ever returns trainees, so an admin id 404s —
        # including the admin making the request.
        other = make_admin("admin2")
        for name in ["set_blocked", "delete_trainee", "restore"]:
            for target in (self.admin, other):
                with self.subTest(action=name, target=target.username):
                    self.assertEqual(self._post(name, trainee=target).status_code, 404)

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

class RemovedTraineeVisibilityTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        self.bob = make_trainee("bob", first_name="Bob")
        self.client.force_login(self.admin)

    def _usernames(self, **params):
        response = self.client.get(reverse("adminportal:trainees"), params)
        return [t.username for t in response.context["trainees"]]

    def test_a_removed_trainee_leaves_the_list(self):
        soft_delete_trainee(self.alice)
        self.assertEqual(self._usernames(), ["bob"])

    def test_a_removed_trainee_leaves_the_dashboard_counts(self):
        self.assertEqual(dashboard_stats(self.admin)["total_users"], 2)
        soft_delete_trainee(self.alice)
        self.assertEqual(dashboard_stats(self.admin)["total_users"], 1)

    def test_the_removed_filter_finds_them(self):
        soft_delete_trainee(self.alice)
        self.assertEqual(self._usernames(status="deleted"), ["alice"])

    def test_the_blocked_filter_does_not_include_removed_trainees(self):
        # Removal deactivates the account, so without care a removed trainee
        # would show up as merely "blocked".
        soft_delete_trainee(self.alice)
        set_trainee_blocked(self.bob, True)
        self.assertEqual(self._usernames(status="blocked"), ["bob"])

    def test_their_page_still_opens_so_they_can_be_restored(self):
        soft_delete_trainee(self.alice)
        response = self.client.get(
            reverse("adminportal:trainee_detail", args=[self.alice.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Restore account")

    def test_restoring_returns_them_to_the_list(self):
        soft_delete_trainee(self.alice)
        restore_trainee(self.alice)
        self.assertIn("alice", self._usernames())

class AccountCardTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        self.url = reverse("adminportal:trainee_detail", args=[self.alice.id])
        self.client.force_login(self.admin)

    def _body(self):
        return self.client.get(self.url).content.decode()

    def test_a_live_account_offers_block_and_remove(self):
        body = self._body()
        self.assertIn("Block account", body)
        self.assertIn("Remove account", body)
        self.assertNotIn("Restore account", body)

    def test_a_blocked_account_offers_unblock(self):
        set_trainee_blocked(self.alice, True)
        body = self._body()
        self.assertIn("Unblock account", body)
        self.assertIn("Blocked", body)

    def test_a_removed_account_offers_only_restore(self):
        soft_delete_trainee(self.alice)
        body = self._body()
        self.assertIn("Restore account", body)
        self.assertIn("Removed", body)
        self.assertNotIn("Block account", body)
        self.assertNotIn("Remove account", body)

    def test_the_destructive_actions_ask_for_confirmation(self):
        body = self._body()
        self.assertIn("return confirm(", body)

    def test_account_actions_do_not_need_profile_sharing(self):
        # An admin can always manage the account, even when they cannot see
        # inside the profile.
        UserProfile.objects.filter(user=self.alice).update(profile_shared=False)
        body = self._body()
        self.assertIn("has not approved profile sharing", body)
        self.assertIn("Block account", body)
