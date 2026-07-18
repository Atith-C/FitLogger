"""Per-exercise analytics on the trainee page."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class ExerciseHistoryTests(TestCase):
    def setUp(self):
        self.user = make_trainee("lifter")
        self.bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        self.pulldown = Exercise.objects.create(name="Lat Pulldown", muscle_group=MuscleGroup.BACK)

    def test_no_history_for_an_untrained_exercise(self):
        self.assertEqual(get_exercise_history(self.user, self.bench), [])

    def test_history_returns_sessions_newest_first(self):
        old = make_session(self.user, days_ago=10, name="Old")
        recent = make_session(self.user, days_ago=1, name="Recent")
        log_set(old, self.bench, "40.00", 8)
        log_set(recent, self.bench, "45.00", 8)

        history = get_exercise_history(self.user, self.bench)
        self.assertEqual([s.name for s, _ in history], ["Recent", "Old"])

    def test_history_carries_only_that_exercises_sets(self):
        session = make_session(self.user, days_ago=0)
        log_set(session, self.bench, "40.00", 8, set_number=1)
        log_set(session, self.bench, "42.50", 6, set_number=2)
        log_set(session, self.pulldown, "50.00", 10, set_number=1)

        history = get_exercise_history(self.user, self.bench)
        self.assertEqual(len(history), 1)
        _, sets = history[0]
        self.assertEqual(len(sets), 2)
        self.assertTrue(all(s.exercise_id == self.bench.id for s in sets))

    def test_history_sets_are_in_set_order(self):
        session = make_session(self.user, days_ago=0)
        log_set(session, self.bench, "42.50", 6, set_number=2)
        log_set(session, self.bench, "40.00", 8, set_number=1)

        _, sets = get_exercise_history(self.user, self.bench)[0]
        self.assertEqual([s.set_number for s in sets], [1, 2])

    def test_unfinished_sessions_are_excluded(self):
        session = make_session(self.user, days_ago=0, completed=False)
        log_set(session, self.bench, "40.00", 8)
        self.assertEqual(get_exercise_history(self.user, self.bench), [])

    def test_history_is_scoped_to_the_user(self):
        other = make_trainee("other")
        session = make_session(other, days_ago=0)
        log_set(session, self.bench, "40.00", 8)
        self.assertEqual(get_exercise_history(self.user, self.bench), [])

    def test_a_session_appears_once_however_many_sets(self):
        session = make_session(self.user, days_ago=0)
        for number in range(1, 5):
            log_set(session, self.bench, "40.00", 8, set_number=number)
        self.assertEqual(len(get_exercise_history(self.user, self.bench)), 1)

class SelectedExerciseTests(TestCase):
    def setUp(self):
        self.bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)

    def test_a_valid_id_resolves(self):
        self.assertEqual(get_selected_exercise(str(self.bench.id)), self.bench)

    def test_blank_and_missing_are_no_selection(self):
        self.assertIsNone(get_selected_exercise(""))
        self.assertIsNone(get_selected_exercise(None))

    def test_a_non_numeric_id_is_no_selection_rather_than_a_crash(self):
        # Comes straight from the query string; a bare pk lookup would be a 500.
        self.assertIsNone(get_selected_exercise("abc"))
        self.assertIsNone(get_selected_exercise("1; DROP TABLE"))

    def test_an_unknown_id_is_no_selection(self):
        self.assertIsNone(get_selected_exercise("999999"))

class TraineeExerciseAnalyticsTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice", first_name="Alice")
        self.bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)

    def test_no_data_for_an_untrained_exercise(self):
        analytics = trainee_exercise_analytics(self.alice, self.bench)
        self.assertFalse(analytics["summary"]["has_data"])
        self.assertEqual(analytics["history"], [])
        self.assertEqual(analytics["charts"]["max_weight"], [])
        self.assertEqual(analytics["charts"]["estimated_1rm"], [])
        self.assertEqual(analytics["charts"]["volume"], [])

    def test_all_three_series_are_built_from_logged_sets(self):
        session = make_session(self.alice, days_ago=0)
        log_set(session, self.bench, "40.00", 10)

        analytics = trainee_exercise_analytics(self.alice, self.bench)
        self.assertTrue(analytics["summary"]["has_data"])
        self.assertEqual(len(analytics["charts"]["max_weight"]), 1)
        self.assertEqual(len(analytics["charts"]["estimated_1rm"]), 1)
        self.assertEqual(len(analytics["charts"]["volume"]), 1)
        self.assertEqual(analytics["charts"]["volume"][0]["value"], 400)
        self.assertEqual(len(analytics["history"]), 1)

    def test_analytics_is_scoped_to_the_trainee(self):
        other = make_trainee("other")
        session = make_session(other, days_ago=0)
        log_set(session, self.bench, "40.00", 10)
        self.assertFalse(
            trainee_exercise_analytics(self.alice, self.bench)["summary"]["has_data"]
        )

class ExerciseAnalyticsPageTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, height_cm=165, weight_kg="60.00",
            goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE, profile_shared=True,
        )
        self.bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        self.url = reverse("adminportal:trainee_detail", args=[self.alice.id])
        self.client.force_login(self.admin)

    def _body(self, **params):
        return self.client.get(self.url, params).content.decode()

    def _train(self):
        session = make_session(self.alice, days_ago=0, name="Chest Day")
        log_set(session, self.bench, "40.00", 10)
        return session

    def test_the_picker_lists_the_exercise_library(self):
        body = self._body()
        self.assertIn('id="exercise-picker"', body)
        self.assertIn("Bench Press", body)
        self.assertIn("Chest", body)  # muscle-group optgroup

    def test_nothing_selected_shows_no_exercise_sections(self):
        body = self._body()
        self.assertNotIn('id="chart-1rm"', body)
        self.assertNotIn(NO_ENTRIES, body)

    def test_selecting_an_untrained_exercise_shows_the_spec_empty_state(self):
        body = self._body(exercise=self.bench.id)
        self.assertIn(NO_ENTRIES, body)
        self.assertNotIn('id="chart-1rm"', body)

    def test_selecting_a_trained_exercise_shows_all_four_sections(self):
        self._train()
        body = self._body(exercise=self.bench.id)
        self.assertIn('id="chart-1rm"', body)          # progress graph
        self.assertIn('id="chart-max-weight"', body)   # weight trend
        self.assertIn('id="chart-volume"', body)       # volume
        self.assertIn("Bench Press history", body)     # workout history
        self.assertNotIn(NO_ENTRIES, body)

    def test_the_history_lists_the_logged_sets(self):
        self._train()
        body = self._body(exercise=self.bench.id)
        self.assertIn("Chest Day", body)
        self.assertIn("40 kg × 10", body)

    def test_the_summary_tiles_render(self):
        self._train()
        body = self._body(exercise=self.bench.id)
        self.assertIn("Heaviest weight", body)
        self.assertIn("Best estimated 1RM", body)
        self.assertIn("Recent volume load", body)
        self.assertIn("1 session logged", body)

    def test_the_chart_payload_carries_the_exercise_series(self):
        self._train()
        response = self.client.get(self.url, {"exercise": self.bench.id})
        charts = response.context["charts"]
        # The weekly bars from Phase H survive alongside the Phase I series.
        self.assertIn("weekly_workouts", charts)
        for key in ["max_weight", "estimated_1rm", "volume"]:
            self.assertEqual(len(charts[key]), 1)
        self.assertEqual(response.context["exercise_name"], "Bench Press")

    def test_no_exercise_name_means_charts_js_skips_the_line_charts(self):
        self.assertEqual(self.client.get(self.url).context["exercise_name"], "")

    def test_a_non_numeric_exercise_id_does_not_error(self):
        response = self.client.get(self.url, {"exercise": "abc"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_exercise"])

    def test_an_unknown_exercise_id_does_not_error(self):
        response = self.client.get(self.url, {"exercise": "999999"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_exercise"])

    def test_the_page_is_still_admin_only_with_an_exercise_selected(self):
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(self.url, {"exercise": self.bench.id}).status_code, 403
        )

class ExerciseAnalyticsSharingGateTests(TestCase):
    """Exercise data is private: ?exercise= must reveal nothing when sharing is off."""

    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, days_per_week=4, profile_shared=False,
        )
        self.bench = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        session = make_session(self.alice, days_ago=0, name="Chest Day")
        log_set(session, self.bench, "40.00", 10)
        self.url = reverse("adminportal:trainee_detail", args=[self.alice.id])
        self.client.force_login(self.admin)

    def test_no_picker_when_not_shared(self):
        body = self.client.get(self.url).content.decode()
        self.assertNotIn('id="exercise-picker"', body)
        self.assertNotIn("Exercise analytics", body)

    def test_guessing_an_exercise_id_reveals_nothing(self):
        response = self.client.get(self.url, {"exercise": self.bench.id})
        body = response.content.decode()

        # Not in the context...
        for key in ["selected_exercise", "exercise_summary", "exercise_history",
                    "exercise_groups", "exercise_name"]:
            self.assertIsNone(response.context.get(key), f"{key} leaked into the context")

        # ...nor the HTML.
        self.assertNotIn("Chest Day", body)
        self.assertNotIn('id="chart-1rm"', body)
        self.assertNotIn('id="exercise-name"', body)
        self.assertIn("has not approved profile sharing", body)

    def test_the_picker_appears_once_sharing_is_approved(self):
        UserProfile.objects.filter(user=self.alice).update(profile_shared=True)
        body = self.client.get(self.url, {"exercise": self.bench.id}).content.decode()
        self.assertIn('id="exercise-picker"', body)
        self.assertIn("Bench Press history", body)
