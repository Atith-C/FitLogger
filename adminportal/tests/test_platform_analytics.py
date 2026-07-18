"""The admin Analytics page: growth, activity, distributions."""

from adminportal.tests.helpers import *  # noqa: F401,F403

class UserGrowthTests(TestCase):
    def test_cumulative_count_climbs_one_per_trainee(self):
        for i in range(3):
            set_joined(make_trainee(f"t{i}"), days_ago=3 - i)
        points = platform_analytics("year")["growth"]
        self.assertEqual([p["count"] for p in points], [1, 2, 3])

    def test_each_dot_carries_a_name_and_join_date(self):
        set_joined(make_trainee("alice", first_name="Alice"), days_ago=1)
        point = platform_analytics("year")["growth"][0]
        self.assertEqual(point["name"], "Alice")
        self.assertIn("/", point["joined"])  # dd/mm/yyyy

    def test_the_week_range_hides_older_signups_but_keeps_the_running_total(self):
        set_joined(make_trainee("old"), days_ago=40)
        set_joined(make_trainee("recent"), days_ago=2)

        week = platform_analytics("week")["growth"]
        self.assertEqual(len(week), 1)              # only the recent dot shows
        self.assertEqual(week[0]["count"], 2)       # but at the true total, not 1

    def test_an_unknown_range_falls_back_to_the_default(self):
        make_trainee("t1")
        self.assertEqual(platform_analytics("garbage")["range"], "year")

    def test_the_year_range_excludes_signups_older_than_a_year(self):
        set_joined(make_trainee("ancient"), days_ago=400)
        set_joined(make_trainee("recent"), days_ago=100)

        year = platform_analytics("year")["growth"]
        self.assertEqual(len(year), 1)          # the 400-day-old dot is hidden
        self.assertEqual(year[0]["count"], 2)   # but the running total is right

class ActiveUsersTests(TestCase):
    def _bars(self):
        return {b["label"]: b for b in platform_analytics()["active"]}

    def test_windows_nest_daily_within_weekly_within_monthly(self):
        set_last_login(make_trainee("today"), days_ago=0)
        set_last_login(make_trainee("thisweek"), days_ago=3)
        set_last_login(make_trainee("thismonth"), days_ago=20)
        set_last_login(make_trainee("old"), days_ago=90)

        bars = self._bars()
        self.assertEqual(bars["Daily"]["count"], 1)
        self.assertEqual(bars["Weekly"]["count"], 2)
        self.assertEqual(bars["Monthly"]["count"], 3)  # old (90d) excluded

    def test_active_bars_carry_names(self):
        set_last_login(make_trainee("adi", first_name="Adi"), days_ago=0)
        self.assertIn("Adi", self._bars()["Daily"]["names"])

    def test_a_trainee_who_never_logged_in_is_not_active(self):
        make_trainee("ghost")  # last_login stays NULL
        for bar in self._bars().values():
            self.assertEqual(bar["count"], 0)

class WeekdayActivityTests(TestCase):
    def test_counts_completed_workouts_by_weekday(self):
        alice = make_trainee("alice")
        bench = Exercise.objects.create(name="Bench", muscle_group=MuscleGroup.CHEST)

        # A completed session whose weekday we can assert.
        session = make_session(alice, days_ago=0)
        WorkoutSet.objects.create(
            session=session, exercise=bench, set_number=1, weight="40.0", reps=10
        )
        today_label = timezone.localdate().strftime("%a")

        weekday = {b["label"]: b["count"] for b in platform_analytics()["weekday"]}
        self.assertEqual(sum(weekday.values()), 1)
        self.assertEqual(weekday[today_label], 1)

    def test_all_seven_days_are_present_and_carry_no_names(self):
        make_trainee("alice")
        weekday = platform_analytics()["weekday"]
        self.assertEqual([b["label"] for b in weekday],
                         ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        for bar in weekday:
            self.assertNotIn("names", bar)

    def test_unfinished_workouts_do_not_count(self):
        alice = make_trainee("alice")
        make_session(alice, days_ago=0, completed=False)
        self.assertEqual(sum(b["count"] for b in platform_analytics()["weekday"]), 0)

class DistributionTests(TestCase):
    def _trainees(self, goals=None, exps=None):
        goals = goals or []
        exps = exps or []
        for i, goal in enumerate(goals):
            u = make_trainee(f"g{i}")
            UserProfile.objects.filter(user=u).update(goal=goal)
        for i, exp in enumerate(exps):
            u = make_trainee(f"e{i}")
            UserProfile.objects.filter(user=u).update(experience_level=exp)

    def test_goal_counts_in_enum_order_all_buckets_present(self):
        self._trainees(goals=[Goal.BUILD_MUSCLE, Goal.BUILD_MUSCLE, Goal.LOSE_WEIGHT])
        goals = platform_analytics()["goals"]
        self.assertEqual([b["label"] for b in goals],
                         ["Build muscle", "Lose weight", "Stay fit"])
        self.assertEqual([b["count"] for b in goals], [2, 1, 0])

    def test_experience_counts(self):
        self._trainees(exps=[EL.BEGINNER, EL.ADVANCED, EL.ADVANCED])
        exp = {b["label"]: b["count"] for b in platform_analytics()["experience"]}
        self.assertEqual(exp, {"Beginner": 1, "Intermediate": 0, "Advanced": 2})

    def test_distributions_are_withheld_below_the_minimum(self):
        make_trainee("only1")
        make_trainee("only2")  # 2 < MIN (3)
        data = platform_analytics()
        self.assertIsNone(data["goals"])
        self.assertIsNone(data["experience"])
        self.assertFalse(data["enough_for_distribution"])

    def test_distributions_appear_at_the_minimum(self):
        for i in range(3):
            make_trainee(f"t{i}")
        data = platform_analytics()
        self.assertIsNotNone(data["goals"])
        self.assertIsNotNone(data["experience"])

    def test_sex_renders_even_below_the_minimum(self):
        # Gender is not gated, so it is not subject to the distribution floor.
        u = make_trainee("solo")
        UserProfile.objects.filter(user=u).update(sex=Sex.MALE)
        sex = {b["label"]: b["count"] for b in platform_analytics()["sex"]}
        self.assertEqual(sex, {"Male": 1, "Female": 0})

    def test_sex_has_only_male_and_female_bars(self):
        make_trainee("t1")
        labels = [b["label"] for b in platform_analytics()["sex"]]
        self.assertEqual(labels, ["Male", "Female"])
        self.assertNotIn("Not specified", labels)

    def test_a_trainee_with_no_sex_set_is_simply_omitted(self):
        # sex is nullable and there is no catch-all bar by design: a trainee who
        # has not set a gender does not appear here until they do.
        make_trainee("nobody_set")  # sex stays NULL
        u = make_trainee("is_male")
        UserProfile.objects.filter(user=u).update(sex=Sex.MALE)

        sex = {b["label"]: b["count"] for b in platform_analytics()["sex"]}
        self.assertEqual(sex, {"Male": 1, "Female": 0})

class AnalyticsGateTests(TestCase):
    """The gated fields must never leave the server attached to a name."""

    def setUp(self):
        # Named trainees with distinctive goals/experience, none sharing.
        for name, goal, exp in [
            ("Zephyrina", Goal.LOSE_WEIGHT, EL.ADVANCED),
            ("Quintavius", Goal.BUILD_MUSCLE, EL.BEGINNER),
            ("Baltazar", Goal.STAY_FIT, EL.INTERMEDIATE),
        ]:
            u = make_trainee(name.lower(), first_name=name)
            UserProfile.objects.filter(user=u).update(
                goal=goal, experience_level=exp, profile_shared=False
            )

    def test_the_goal_and_experience_payloads_carry_no_names(self):
        data = platform_analytics()
        blob = json.dumps(data["goals"]) + json.dumps(data["experience"])
        for name in ["Zephyrina", "Quintavius", "Baltazar"]:
            self.assertNotIn(name, blob)

    def test_no_gated_name_reaches_the_rendered_page(self):
        # The distribution charts render as counts; a trainee's name must not
        # appear tied to a goal anywhere in the analytics JSON payload.
        admin = make_admin("theadmin")
        self.client.force_login(admin)
        body = self.client.get(reverse("adminportal:analytics")).content.decode()

        # Extract just the analytics-data script so we do not catch names that
        # legitimately appear elsewhere (there are none here, but be exact).
        import re
        blob = re.search(
            r'<script id="analytics-data"[^>]*>(.*?)</script>', body, re.S
        ).group(1)
        payload = json.loads(blob)

        # Goal/experience/weekday buckets are label+count only.
        for chart in ["goals", "experience", "weekday", "sex"]:
            for bar in payload[chart] or []:
                self.assertEqual(set(bar.keys()), {"label", "count"})

class AnalyticsPageTests(TestCase):
    def setUp(self):
        self.admin = make_admin("theadmin")
        self.client.force_login(self.admin)
        self.url = reverse("adminportal:analytics")

    def test_is_admin_only(self):
        self.client.force_login(make_trainee("intruder"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_empty_state_when_no_trainees(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn("No trainees yet", body)
        self.assertNotIn('id="analytics-data"', body)  # no chart payload

    def test_renders_the_charts_when_trainees_exist(self):
        for i in range(3):
            make_trainee(f"t{i}")
        body = self.client.get(self.url).content.decode()
        for cid in ["chart-growth", "chart-active", "chart-weekday",
                    "chart-goals", "chart-experience", "chart-sex"]:
            self.assertIn(f'id="{cid}"', body)
        self.assertIn('id="analytics-data"', body)
        self.assertIn("User goal preferences", body)
        self.assertIn("User experience distribution", body)

    def test_the_range_toggle_drives_the_growth_window(self):
        set_joined(make_trainee("old"), days_ago=40)
        make_trainee("t2")
        make_trainee("t3")

        month = self.client.get(self.url, {"range": "month"})
        self.assertEqual(month.context["analytics"]["range"], "month")
        # The 40-day-old signup is outside the month window.
        dates = [p["name"] for p in month.context["analytics"]["growth"]]
        self.assertNotIn("old", dates)

    def test_the_distribution_note_shows_below_the_minimum(self):
        make_trainee("only1")  # 1 < 3
        body = self.client.get(self.url).content.decode()
        self.assertIn("stay hidden until", body)
        self.assertNotIn('id="chart-goals"', body)
