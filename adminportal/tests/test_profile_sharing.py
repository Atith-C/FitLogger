"""The Phase G/H profile-sharing gate."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class ProfileSharingGateTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, height_cm=165, weight_kg="58.5",
            goal=Goal.LOSE_WEIGHT, experience_level=ExperienceLevel.INTERMEDIATE,
            profile_shared=False,
        )
        self.url = reverse("adminportal:trainee_detail", args=[self.alice.id])
        self.client.force_login(self.admin)

    def _share(self, on=True):
        UserProfile.objects.filter(user=self.alice).update(profile_shared=on)

    # --- sharing OFF ---

    def test_not_approved_message_is_shown(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn("This trainee has not approved profile sharing", body)

    def test_core_is_still_visible_when_not_shared(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn("Alice", body)
        self.assertIn("25", body)        # age
        self.assertIn("Female", body)    # gender

    def test_chat_still_works_when_not_shared(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn("Open chat", body)
        self.assertIn(reverse("adminportal:open_chat", args=[self.alice.id]), body)

    def test_no_private_data_reaches_the_page_when_not_shared(self):
        response = self.client.get(self.url)
        body = response.content.decode()
        # The gate is server-side: private values never enter the context...
        self.assertIsNone(response.context.get("personal"))
        # ...nor the HTML. Assert on the displayed form ("165 cm", not a bare
        # "165", which could collide with the trainee's id in an action URL).
        self.assertNotIn("165 cm", body)       # height
        self.assertNotIn("58.5 kg", body)      # weight
        self.assertNotIn("Lose weight", body)  # goal
        self.assertNotIn("Intermediate", body) # experience
        self.assertNotIn("Personal information", body)

    # --- sharing ON ---

    def test_personal_information_is_shown_when_shared(self):
        self._share(True)
        body = self.client.get(self.url).content.decode()

        self.assertIn("Personal information", body)
        self.assertIn("165", body)
        self.assertIn("58.5", body)
        self.assertIn("Lose weight", body)
        self.assertIn("Intermediate", body)
        self.assertNotIn("has not approved profile sharing", body)

    def test_toggling_sharing_flips_the_page_immediately(self):
        self.assertIn(
            "has not approved", self.client.get(self.url).content.decode()
        )
        self._share(True)
        self.assertIn(
            "Personal information", self.client.get(self.url).content.decode()
        )
        self._share(False)
        self.assertIn(
            "has not approved", self.client.get(self.url).content.decode()
        )

    def test_gate_page_is_still_admin_only(self):
        self._share(True)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url).status_code, 403)

class PhaseHSharingGateTests(TestCase):
    """None of the Phase H data may reach the page when sharing is off."""

    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, height_cm=165, weight_kg="60.00",
            goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE, profile_shared=False,
        )
        CalorieCalculation.objects.create(
            user=self.alice, sex=Sex.FEMALE, weight_kg="60.00", height_cm=165,
            age=25, activity_level=ActivityLevel.MODERATE,
            bmr=1400, maintenance_calories=2000,
        )
        WorkoutPlan.objects.create(
            user=self.alice, goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE,
            workout_location=WorkoutLocation.COMMERCIAL_GYM, session_duration=60,
            is_active=True,
            plan_json={"plan_name": "Lean Builder", "days": []},
        )
        session = make_session(self.alice, days_ago=0, name="Chest Day")
        exercise = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        WorkoutSet.objects.create(
            session=session, exercise=exercise, set_number=1, weight="40.00", reps=10
        )
        self.url = reverse("adminportal:trainee_detail", args=[self.alice.id])
        self.client.force_login(self.admin)

    def test_no_phase_h_data_in_the_context(self):
        context = self.client.get(self.url).context
        for key in ["nutrition", "fitness", "stats", "charts", "history"]:
            self.assertIsNone(context.get(key), f"{key} leaked into the context")

    def test_no_phase_h_data_in_the_html(self):
        body = self.client.get(self.url).content.decode()
        for heading in ["Nutrition", "Fitness", "Workout analytics", "Recent workouts"]:
            self.assertNotIn(heading, body)
        for value in ["2000", "1500", "Lean Builder", "Chest Day", "Bench Press"]:
            self.assertNotIn(value, body)

    def test_no_chart_payload_or_plotly_when_not_shared(self):
        body = self.client.get(self.url).content.decode()
        self.assertNotIn('id="chart-data"', body)
        self.assertNotIn("plotly", body.lower())

    def test_sections_appear_the_moment_sharing_is_approved(self):
        UserProfile.objects.filter(user=self.alice).update(profile_shared=True)
        body = self.client.get(self.url).content.decode()
        self.assertIn("Nutrition", body)
        self.assertIn("Lean Builder", body)
        self.assertIn("Chest Day", body)

    def test_sections_stay_admin_only_when_shared(self):
        UserProfile.objects.filter(user=self.alice).update(profile_shared=True)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url).status_code, 403)
