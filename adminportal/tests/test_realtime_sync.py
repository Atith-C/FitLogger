"""Real-time sync: triggers, badges, and change notifications."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class WorkoutNotificationTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        self.bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)

    def _session(self):
        session = create_workout_session(self.alice, "Chest Day")
        WorkoutSet.objects.create(
            session=session, exercise=self.bench, set_number=1, weight="40.00", reps=10
        )
        return session

    def test_completing_a_workout_notifies_admins(self):
        session = self._session()
        complete_workout_session(self.alice, session.id)

        note = admin_notes(self.admin, Category.WORKOUT).get()
        self.assertEqual(note.title, "Alice completed a workout")
        self.assertIn("Chest Day", note.message)
        self.assertIn("1 set", note.message)
        self.assertEqual(note.actor, self.alice)

    def test_the_notification_links_to_the_trainees_profile(self):
        session = self._session()
        complete_workout_session(self.alice, session.id)

        note = admin_notes(self.admin, Category.WORKOUT).get()
        self.assertEqual(
            note.link, reverse("adminportal:trainee_detail", args=[self.alice.id])
        )

    def test_starting_a_workout_does_not_notify(self):
        self._session()
        self.assertEqual(admin_notes(self.admin, Category.WORKOUT).count(), 0)

    def test_completing_twice_notifies_once(self):
        session = self._session()
        complete_workout_session(self.alice, session.id)
        complete_workout_session(self.alice, session.id)
        self.assertEqual(admin_notes(self.admin, Category.WORKOUT).count(), 1)

    def test_editing_the_note_after_finishing_does_not_re_notify(self):
        # complete_workout_session doubles as the save-note path; a note edit
        # must not re-announce the workout.
        session = self._session()
        complete_workout_session(self.alice, session.id, notes="Felt strong")
        complete_workout_session(self.alice, session.id, notes="Actually felt awful")

        self.assertEqual(admin_notes(self.admin, Category.WORKOUT).count(), 1)
        session.refresh_from_db()
        self.assertEqual(session.notes, "Actually felt awful")

    def test_pluralisation_of_the_set_count(self):
        session = create_workout_session(self.alice, "Chest Day")
        for number in (1, 2):
            WorkoutSet.objects.create(
                session=session, exercise=self.bench, set_number=number,
                weight="40.00", reps=10,
            )
        complete_workout_session(self.alice, session.id)
        self.assertIn("2 sets", admin_notes(self.admin, Category.WORKOUT).get().message)

    def test_an_admins_own_workout_does_not_notify(self):
        session = create_workout_session(self.admin, "Admin lifts too")
        complete_workout_session(self.admin, session.id)
        self.assertEqual(Notification.objects.filter(category=Category.WORKOUT).count(), 0)

    def test_every_admin_is_notified(self):
        second = make_admin("admin2")
        session = self._session()
        complete_workout_session(self.alice, session.id)

        self.assertEqual(admin_notes(self.admin, Category.WORKOUT).count(), 1)
        self.assertEqual(admin_notes(second, Category.WORKOUT).count(), 1)

class CalorieNotificationWordingTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")

    def test_the_title_matches_the_spec_example(self):
        form = CalorieCalculationForm(data={
            "sex": Sex.FEMALE, "age": 25, "height_cm": 165,
            "weight_kg": "60.0", "activity_level": AL.MODERATE,
        })
        self.assertTrue(form.is_valid(), form.errors)
        save_calorie_calculation(self.alice, form, 1400, 2050)

        note = admin_notes(self.admin, Category.CALORIES).get()
        # Spec: "Atith updated Maintenance Calories."
        self.assertEqual(note.title, "Alice updated Maintenance Calories")
        self.assertIn("2050", note.message)

class UnreadBadgeTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")

    def test_counts_start_at_zero(self):
        self.assertEqual(
            unread_badges(self.admin, is_admin=True), {"notifications": 0, "messages": 0}
        )

    def test_a_trainee_change_raises_the_admins_notification_count(self):
        create_notification(self.admin, "Something happened")
        self.assertEqual(unread_badges(self.admin, is_admin=True)["notifications"], 1)

    def test_admin_and_trainee_message_counts_differ(self):
        send_message(get_or_create_conversation(self.alice), self.alice, "hi")
        self.assertEqual(unread_badges(self.admin, is_admin=True)["messages"], 1)
        self.assertEqual(unread_badges(self.alice, is_admin=False)["messages"], 0)

class BadgePollTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        self.url = reverse("notifications:poll")

    def test_poll_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

    def test_poll_returns_the_admins_counts(self):
        create_notification(self.admin, "A note")
        send_message(get_or_create_conversation(self.alice), self.alice, "hi")

        self.client.force_login(self.admin)
        data = self.client.get(self.url).json()
        # The message also generates a notification, hence >= rather than ==.
        self.assertGreaterEqual(data["notifications"], 1)
        self.assertEqual(data["messages"], 1)

    def test_poll_is_scoped_to_the_caller(self):
        create_notification(self.admin, "For the admin only")
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.url).json()["notifications"], 0)

    def test_poll_reflects_a_change_without_a_page_reload(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).json()["notifications"], 0)

        create_notification(self.admin, "Alice updated Weight")
        self.assertEqual(self.client.get(self.url).json()["notifications"], 1)

    def test_poll_leaks_no_notification_content(self):
        create_notification(self.admin, "Alice changed Goal", message="secret detail")
        self.client.force_login(self.admin)
        body = self.client.get(self.url).content.decode()

        self.assertNotIn("Alice changed Goal", body)
        self.assertNotIn("secret detail", body)

    def test_the_badge_poll_hook_is_on_the_page(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("adminportal:dashboard")).content.decode()
        self.assertIn('id="badge-poll"', body)
        self.assertIn(self.url, body)
        self.assertIn('data-badge="notifications"', body)

    def test_signed_out_pages_do_not_poll(self):
        body = self.client.get(reverse("users:login")).content.decode()
        self.assertNotIn('id="badge-poll"', body)

class AdminSeesTraineeChangesTests(TestCase):
    """The synchronisation guarantee: the admin's page reflects the trainee's
    latest state on the next request, with no cache to invalidate."""

    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, height_cm=165, weight_kg="60.00",
            goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE,
            workout_location=WorkoutLocation.COMMERCIAL_GYM, session_duration=60,
            profile_shared=True,
        )
        self.url = reverse("adminportal:trainee_detail", args=[self.alice.id])
        self.client.force_login(self.admin)

    def _body(self):
        return self.client.get(self.url).content.decode()

    def _edit_profile(self, **changes):
        profile = UserProfile.objects.get(user=self.alice)
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

    def test_a_weight_change_shows_on_the_admins_next_request(self):
        self.assertIn("60", self._body())
        self._edit_profile(weight_kg="72.5")
        self.assertIn("72.5", self._body())

    def test_a_goal_change_shows_on_the_admins_next_request(self):
        self.assertIn("Lose weight", self._body())
        self._edit_profile(goal=Goal.BUILD_MUSCLE)

        body = self._body()
        self.assertIn("Build muscle", body)
        self.assertNotIn("Lose weight", body)

    def test_a_height_change_shows_on_the_admins_next_request(self):
        self._edit_profile(height_cm=170)
        self.assertIn("170", self._body())

    def test_a_completed_workout_shows_on_the_admins_next_request(self):
        self.assertIn("No workouts logged yet", self._body())

        bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        session = create_workout_session(self.alice, "Chest Day")
        WorkoutSet.objects.create(
            session=session, exercise=bench, set_number=1, weight="40.00", reps=10
        )
        complete_workout_session(self.alice, session.id)

        body = self._body()
        self.assertIn("Chest Day", body)
        self.assertNotIn("No workouts logged yet", body)
        self.assertIn("400", body)  # volume recomputed, not cached

    def test_new_calories_and_macros_show_on_the_admins_next_request(self):
        self.assertIn("has not calculated their calories yet", self._body())

        form = CalorieCalculationForm(data={
            "sex": Sex.FEMALE, "age": 25, "height_cm": 165,
            "weight_kg": "60.0", "activity_level": AL.MODERATE,
        })
        self.assertTrue(form.is_valid(), form.errors)
        save_calorie_calculation(self.alice, form, 1400, 2000)

        body = self._body()
        self.assertIn("2000", body)   # maintenance
        self.assertIn("1500", body)   # goal calories (lose weight)
        self.assertIn("108 g", body)  # macros follow automatically

    def test_recalculating_updates_the_admins_view(self):
        for maintenance in (2000, 2400):
            form = CalorieCalculationForm(data={
                "sex": Sex.FEMALE, "age": 25, "height_cm": 165,
                "weight_kg": "60.0", "activity_level": AL.MODERATE,
            })
            self.assertTrue(form.is_valid(), form.errors)
            save_calorie_calculation(self.alice, form, 1400, maintenance)

        # Assert on the value in context, not a raw "2000"/"2400" string match —
        # those could collide with the trainee's id in an action URL.
        nutrition = self.client.get(self.url).context["nutrition"]
        self.assertEqual(nutrition["maintenance"], 2400)  # the recalculated figure

    def test_revoking_sharing_hides_the_data_again_immediately(self):
        self.assertIn("Personal information", self._body())
        set_profile_sharing(self.alice, False)
        self.assertIn("has not approved profile sharing", self._body())

class ChangeNotificationRoutingTests(TestCase):
    """Every tracked change notifies admins and points at the trainee."""

    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, height_cm=165, weight_kg="60.00",
            goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE,
            workout_location=WorkoutLocation.COMMERCIAL_GYM, session_duration=60,
        )
        self.link = reverse("adminportal:trainee_detail", args=[self.alice.id])

    def test_every_change_notification_opens_the_trainees_profile(self):
        profile = UserProfile.objects.get(user=self.alice)
        form = UserProfileForm(
            data={
                "age": 26, "sex": profile.sex, "weight_kg": "61.0",
                "height_cm": profile.height_cm, "goal": Goal.BUILD_MUSCLE,
                "days_per_week": profile.days_per_week,
                "experience_level": profile.experience_level,
                "workout_location": profile.workout_location,
                "session_duration": profile.session_duration,
            },
            instance=profile,
        )
        self.assertTrue(form.is_valid(), form.errors)
        update_profile(form)
        set_profile_sharing(self.alice, True)

        notes = admin_notes(self.admin)
        self.assertGreaterEqual(notes.count(), 2)
        for note in notes:
            self.assertEqual(note.link, self.link)

    def test_clicking_a_change_notification_lands_on_the_trainee(self):
        set_profile_sharing(self.alice, True)
        note = admin_notes(self.admin, Category.PERMISSION).get()

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("notifications:open", args=[note.id])
        )
        self.assertRedirects(response, self.link)
        note.refresh_from_db()
        self.assertTrue(note.is_read)
