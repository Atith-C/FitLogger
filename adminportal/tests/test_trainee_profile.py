"""The trainee profile: nutrition, fitness, streak, overview."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class WorkoutStreakTests(TestCase):
    def setUp(self):
        self.user = make_trainee("streaky")

    def test_no_workouts_is_zero(self):
        self.assertEqual(workout_streak(self.user), 0)

    def test_a_workout_this_week_is_one(self):
        make_session(self.user, days_ago=0)
        self.assertEqual(workout_streak(self.user), 1)

    def test_consecutive_weeks_accumulate(self):
        # One workout in each of the last three weeks.
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        for weeks_back in range(3):
            week_monday = monday - timedelta(weeks=weeks_back)
            make_session(self.user, days_ago=(today - week_monday).days)
        self.assertEqual(workout_streak(self.user), 3)

    def test_a_gap_ends_the_streak(self):
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        # This week and last week trained; the week before that skipped.
        for weeks_back in (0, 1, 3):
            week_monday = monday - timedelta(weeks=weeks_back)
            make_session(self.user, days_ago=(today - week_monday).days)
        self.assertEqual(workout_streak(self.user), 2)

    def test_an_empty_current_week_does_not_break_the_streak(self):
        # The current week is still in progress — a streak built last week and
        # the week before must survive until this week actually ends.
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        for weeks_back in (1, 2):
            week_monday = monday - timedelta(weeks=weeks_back)
            make_session(self.user, days_ago=(today - week_monday).days)
        self.assertEqual(workout_streak(self.user), 2)

    def test_multiple_workouts_in_one_week_count_once(self):
        make_session(self.user, days_ago=0)
        make_session(self.user, days_ago=0)
        self.assertEqual(workout_streak(self.user), 1)

    def test_unfinished_workouts_do_not_count(self):
        make_session(self.user, days_ago=0, completed=False)
        self.assertEqual(workout_streak(self.user), 0)

    def test_streak_is_per_user(self):
        other = make_trainee("other")
        make_session(other, days_ago=0)
        self.assertEqual(workout_streak(self.user), 0)

class TraineeNutritionTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, height_cm=165, weight_kg="60.00",
            goal=Goal.LOSE_WEIGHT,
        )
        self.alice.refresh_from_db()

    def _calculate(self, maintenance=2000):
        return CalorieCalculation.objects.create(
            user=self.alice, sex=Sex.FEMALE, weight_kg="60.00", height_cm=165,
            age=25, activity_level=ActivityLevel.MODERATE,
            bmr=1400, maintenance_calories=maintenance,
        )

    def test_none_when_never_calculated(self):
        self.assertIsNone(trainee_nutrition(self.alice))

    def test_goal_calories_follow_the_profile_goal(self):
        self._calculate(maintenance=2000)
        nutrition = trainee_nutrition(self.alice)
        # Lose weight = maintenance - 500.
        self.assertEqual(nutrition["maintenance"], 2000)
        self.assertEqual(nutrition["goal_calories"], 1500)
        self.assertEqual(nutrition["goal_label"], "Weight loss")

    def test_build_muscle_goal_adds_calories(self):
        UserProfile.objects.filter(user=self.alice).update(goal=Goal.BUILD_MUSCLE)
        self.alice.refresh_from_db()
        self._calculate(maintenance=2000)
        self.assertEqual(trainee_nutrition(self.alice)["goal_calories"], 2500)

    def test_stay_fit_goal_is_maintenance(self):
        UserProfile.objects.filter(user=self.alice).update(goal=Goal.STAY_FIT)
        self.alice.refresh_from_db()
        self._calculate(maintenance=2000)
        self.assertEqual(trainee_nutrition(self.alice)["goal_calories"], 2000)

    def test_macros_are_derived_from_the_goal_calories(self):
        self._calculate(maintenance=2000)
        macros = trainee_nutrition(self.alice)["macros"]
        # Macros must describe the 1500 goal figure, not the 2000 maintenance.
        self.assertEqual(macros["calories"], 1500)
        self.assertEqual(macros["protein"]["grams"], 108)   # 60kg * 1.8
        self.assertEqual(macros["fat"]["grams"], 42)        # 25% of 1500 / 9
        self.assertEqual(macros["fibre"]["min"], 30)

class TraineeOverviewTests(TestCase):
    def setUp(self):
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, height_cm=165, weight_kg="60.00",
            goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE,
        )
        self.alice.refresh_from_db()

    def test_empty_profile_returns_zeroed_sections(self):
        overview = trainee_overview(self.alice)
        self.assertIsNone(overview["nutrition"])
        self.assertEqual(overview["fitness"]["streak"], 0)
        self.assertEqual(overview["fitness"]["planned"], 4)
        self.assertIsNone(overview["fitness"]["plan"])
        self.assertEqual(overview["stats"]["total_workouts"], 0)
        self.assertEqual(overview["charts"]["weekly_workouts"], [])
        self.assertEqual(overview["history"], [])

    def test_overview_reflects_logged_workouts(self):
        session = make_session(self.alice, days_ago=0, name="Chest Day")
        exercise = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        WorkoutSet.objects.create(
            session=session, exercise=exercise, set_number=1, weight="40.00", reps=10
        )

        overview = trainee_overview(self.alice)
        self.assertEqual(overview["stats"]["total_workouts"], 1)
        self.assertEqual(overview["stats"]["total_sets"], 1)
        self.assertEqual(overview["stats"]["total_volume_kg"], 400)
        self.assertEqual(overview["fitness"]["this_week"], 1)
        self.assertEqual(overview["fitness"]["streak"], 1)
        self.assertEqual(len(overview["charts"]["weekly_workouts"]), 1)
        self.assertEqual(len(overview["history"]), 1)

    def test_history_is_capped_at_five_sessions(self):
        for day in range(8):
            make_session(self.alice, days_ago=day)
        self.assertEqual(len(trainee_overview(self.alice)["history"]), 5)

    def test_overview_is_scoped_to_the_trainee(self):
        other = make_trainee("other")
        make_session(other, days_ago=0)
        self.assertEqual(trainee_overview(self.alice)["stats"]["total_workouts"], 0)

class TraineeDetailSectionTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.alice = make_trainee("alice", first_name="Alice")
        UserProfile.objects.filter(user=self.alice).update(
            age=25, sex=Sex.FEMALE, height_cm=165, weight_kg="60.00",
            goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE, profile_shared=True,
        )
        self.url = reverse("adminportal:trainee_detail", args=[self.alice.id])
        self.client.force_login(self.admin)

    def _body(self):
        return self.client.get(self.url).content.decode()

    def _calculate(self):
        CalorieCalculation.objects.create(
            user=self.alice, sex=Sex.FEMALE, weight_kg="60.00", height_cm=165,
            age=25, activity_level=ActivityLevel.MODERATE,
            bmr=1400, maintenance_calories=2000,
        )

    def test_all_four_sections_render_when_shared(self):
        body = self._body()
        for heading in ["Nutrition", "Fitness", "Workout analytics", "Recent workouts"]:
            self.assertIn(heading, body)

    def test_nutrition_shows_calories_and_macros(self):
        self._calculate()
        body = self._body()
        self.assertIn("2000", body)   # maintenance
        self.assertIn("1500", body)   # goal calories
        self.assertIn("108 g", body)  # protein
        self.assertIn("30–40 g", body)  # fibre

    def test_nutrition_empty_state(self):
        self.assertIn("has not calculated their calories yet", self._body())

    def test_fitness_shows_streak_and_weekly_progress(self):
        make_session(self.alice, days_ago=0)
        body = self._body()
        self.assertIn("Week streak", body)
        self.assertIn("1 / 4", body)  # this week / planned

    def test_fitness_plan_empty_state(self):
        self.assertIn("No active plan", self._body())

    def test_fitness_shows_the_active_plan(self):
        WorkoutPlan.objects.create(
            user=self.alice, goal=Goal.LOSE_WEIGHT, days_per_week=4,
            experience_level=ExperienceLevel.INTERMEDIATE,
            workout_location=WorkoutLocation.COMMERCIAL_GYM, session_duration=60,
            is_active=True,
            plan_json={"plan_name": "Lean Builder", "days": []},
        )
        self.assertIn("Lean Builder", self._body())

    def test_analytics_shows_the_stat_tiles_and_chart_container(self):
        session = make_session(self.alice, days_ago=0)
        exercise = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        WorkoutSet.objects.create(
            session=session, exercise=exercise, set_number=1, weight="40.00", reps=10
        )
        body = self._body()
        self.assertIn('id="chart-weekly"', body)
        self.assertIn('id="chart-data"', body)
        self.assertIn("kg lifted", body)
        self.assertIn("400", body)

    def test_history_lists_recent_workouts(self):
        session = make_session(self.alice, days_ago=0, name="Chest Day")
        exercise = Exercise.objects.create(name="Bench Press", muscle_group=MuscleGroup.CHEST)
        WorkoutSet.objects.create(
            session=session, exercise=exercise, set_number=1, weight="40.00", reps=10
        )
        body = self._body()
        self.assertIn("Chest Day", body)
        self.assertIn("Bench Press", body)
        self.assertIn("40×10", body)

    def test_history_empty_state(self):
        # Distinct from the weekly chart's "No completed workouts yet", which
        # is always in the HTML (hidden) and would make this assertion vacuous.
        self.assertIn("No workouts logged yet", self._body())
