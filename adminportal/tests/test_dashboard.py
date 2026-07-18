"""Admin dashboard: platform stats and section access."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class DashboardStatsTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")

    def test_total_and_active_users_count_only_trainees(self):
        make_trainee("t1")
        make_trainee("t2")
        make_trainee("blocked", is_active=False)

        stats = dashboard_stats(self.admin)
        self.assertEqual(stats["total_users"], 3)       # admin not counted
        self.assertEqual(stats["active_users"], 2)      # blocked excluded

    def test_today_logins_counts_trainees_who_logged_in_today(self):
        t = make_trainee("t1")
        User.objects.filter(pk=t.pk).update(last_login=timezone.now())
        make_trainee("t2")  # never logged in

        self.assertEqual(dashboard_stats(self.admin)["today_logins"], 1)

    def test_new_registrations_counts_trainees_joined_today(self):
        make_trainee("t1")  # joined now = today
        old = make_trainee("old")
        User.objects.filter(pk=old.pk).update(
            date_joined=timezone.now() - timezone.timedelta(days=5)
        )
        self.assertEqual(dashboard_stats(self.admin)["new_registrations"], 1)

    def test_unread_messages_and_notifications(self):
        trainee = make_trainee("t1")
        send_message(get_or_create_conversation(trainee), trainee, "hi admin")
        create_notification(self.admin, "A note")

        stats = dashboard_stats(self.admin)
        self.assertEqual(stats["unread_messages"], 1)
        # 1 explicit note + the "new message" notification the send created.
        self.assertGreaterEqual(stats["unread_notifications"], 1)

class DashboardAccessTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.trainee = make_trainee("tina")

    def test_dashboard_is_admin_only(self):
        self.client.force_login(self.trainee)
        self.assertEqual(self.client.get(reverse("adminportal:dashboard")).status_code, 403)

    def test_dashboard_renders_the_stat_cards(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("adminportal:dashboard")).content.decode()
        for label in ["Total registered users", "Active users", "Today's logins",
                      "New registrations", "Unread messages", "Unread notifications"]:
            self.assertIn(label, body)

    def test_section_stubs_are_admin_only(self):
        self.client.force_login(self.trainee)
        for name in ["trainees", "analytics", "settings"]:
            self.assertEqual(
                self.client.get(reverse(f"adminportal:{name}")).status_code, 403
            )

    def test_section_stubs_render_for_admin(self):
        self.client.force_login(self.admin)
        for name in ["trainees", "analytics", "settings"]:
            self.assertEqual(
                self.client.get(reverse(f"adminportal:{name}")).status_code, 200
            )

    def test_admin_nav_shows_the_sections(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("adminportal:dashboard")).content.decode()
        for section in ["Dashboard", "Trainees", "Messages", "Analytics", "Settings"]:
            self.assertIn(section, body)
