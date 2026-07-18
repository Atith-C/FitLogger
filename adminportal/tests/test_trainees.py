"""Trainee directory: search, filter, detail, open chat."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class TraineeListTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice", email="alice@ex.com")
        UserProfile.objects.filter(user=self.alice).update(age=25, sex=Sex.FEMALE, profile_shared=True)
        self.bob = make_trainee("bob", first_name="Bob", email="bob@ex.com")
        UserProfile.objects.filter(user=self.bob).update(age=30, sex=Sex.MALE, profile_shared=False)
        self.blocked = make_trainee("carl", first_name="Carl", is_active=False)
        UserProfile.objects.filter(user=self.blocked).update(sex=Sex.MALE)
        self.client.force_login(self.admin)

    def _names(self, response):
        return response.context["trainees"]

    def test_list_is_admin_only(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("adminportal:trainees")).status_code, 403)

    def test_list_shows_all_trainees_with_core_fields(self):
        body = self.client.get(reverse("adminportal:trainees")).content.decode()
        self.assertIn("Alice", body)
        self.assertIn("Age 25", body)
        self.assertIn("Female", body)

    def test_list_excludes_admins(self):
        usernames = [t.username for t in self._names(self.client.get(reverse("adminportal:trainees")))]
        self.assertNotIn("theadmin", usernames)

    def test_search_by_name(self):
        r = self.client.get(reverse("adminportal:trainees"), {"q": "alice"})
        self.assertEqual([t.username for t in self._names(r)], ["alice"])

    def test_search_by_email(self):
        r = self.client.get(reverse("adminportal:trainees"), {"q": "bob@ex"})
        self.assertEqual([t.username for t in self._names(r)], ["bob"])

    def test_filter_by_gender(self):
        r = self.client.get(reverse("adminportal:trainees"), {"gender": "FEMALE"})
        self.assertEqual([t.username for t in self._names(r)], ["alice"])

    def test_filter_by_blocked_status(self):
        r = self.client.get(reverse("adminportal:trainees"), {"status": "blocked"})
        self.assertEqual([t.username for t in self._names(r)], ["carl"])

    def test_filter_by_sharing(self):
        r = self.client.get(reverse("adminportal:trainees"), {"sharing": "shared"})
        self.assertEqual([t.username for t in self._names(r)], ["alice"])

    def test_combined_search_and_filter(self):
        r = self.client.get(reverse("adminportal:trainees"), {"q": "b", "gender": "MALE"})
        self.assertEqual([t.username for t in self._names(r)], ["bob"])

class TraineeDetailTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(age=25, sex=Sex.FEMALE)
        self.client.force_login(self.admin)

    def test_detail_shows_core(self):
        body = self.client.get(reverse("adminportal:trainee_detail", args=[self.alice.id])).content.decode()
        self.assertIn("Alice", body)
        self.assertIn("25", body)
        self.assertIn("Female", body)
        self.assertIn("Open chat", body)

    def test_detail_is_admin_only(self):
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(reverse("adminportal:trainee_detail", args=[self.alice.id])).status_code,
            403,
        )

    def test_detail_404_for_a_non_trainee_id(self):
        self.assertEqual(
            self.client.get(reverse("adminportal:trainee_detail", args=[self.admin.id])).status_code,
            404,
        )

    def test_open_chat_creates_and_opens_the_conversation(self):
        response = self.client.get(reverse("adminportal:open_chat", args=[self.alice.id]))
        conv = Conversation.objects.get(trainee=self.alice)
        self.assertRedirects(response, reverse("adminportal:conversation", args=[conv.id]))

    def test_open_chat_404_for_a_non_trainee(self):
        self.assertEqual(
            self.client.get(reverse("adminportal:open_chat", args=[self.admin.id])).status_code,
            404,
        )
