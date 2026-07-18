import datetime
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import ActivityLevel, BodyMeasurement, Sex
from workouts.models import Exercise, MuscleGroup, WorkoutSession, WorkoutSet

from .services import (
    EPLEY_DIVISOR,
    PLATEAU_IMPROVEMENT_THRESHOLD_PERCENT,
    PLATEAU_MIN_SESSIONS,
    _percentage_change,
    build_calorie_targets,
    calculate_bmr,
    calculate_maintenance_calories,
    compute_calorie_plan,
    compute_macros,
    detect_potential_plateau,
    get_calorie_target,
    estimate_one_rep_max,
    get_adherence,
    get_average_weekly_workouts,
    get_estimated_1rm_progress,
    get_max_weight_progress,
    get_personal_records,
    get_progress_trend,
    get_volume_progress,
    get_weekly_workout_frequency,
    get_wellness_dashboard,
    is_new_personal_record,
)

PASSWORD = "str0ng-pass-2026"


class AnalyticsTestCase(TestCase):
    """Shared fixture helpers."""

    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)
        self.bob = User.objects.create_user(username="bob", password=PASSWORD)
        self.bench = Exercise.objects.create(
            name="Bench Press", muscle_group=MuscleGroup.CHEST
        )
        self.squat = Exercise.objects.create(
            name="Barbell Squat", muscle_group=MuscleGroup.QUADRICEPS
        )

    def log_session(self, user, days_ago, sets, name="Workout", completed=True):
        """sets: list of (exercise, weight, reps)."""
        started = timezone.now() - timedelta(days=days_ago)
        session = WorkoutSession.objects.create(
            user=user,
            name=name,
            started_at=started,
            completed_at=started + timedelta(hours=1) if completed else None,
            is_completed=completed,
        )
        counters = {}
        for exercise, weight, reps in sets:
            counters[exercise.id] = counters.get(exercise.id, 0) + 1
            WorkoutSet.objects.create(
                session=session,
                exercise=exercise,
                set_number=counters[exercise.id],
                weight=Decimal(str(weight)),
                reps=reps,
            )
        return session


class EpleyFormulaTests(TestCase):
    def test_epley_matches_the_documented_formula(self):
        # 100 kg x 10 reps -> 100 * (1 + 10/30) = 133.33
        self.assertAlmostEqual(estimate_one_rep_max(100, 10), 133.333, places=2)

    def test_a_single_rep_adds_only_the_epley_term(self):
        # 100 * (1 + 1/30) = 103.33
        self.assertAlmostEqual(estimate_one_rep_max(100, 1), 103.333, places=2)

    def test_more_reps_at_the_same_weight_estimates_a_higher_1rm(self):
        self.assertGreater(estimate_one_rep_max(60, 10), estimate_one_rep_max(60, 5))

    def test_the_divisor_is_the_documented_constant(self):
        self.assertEqual(EPLEY_DIVISOR, 30)


class PercentageChangeTests(TestCase):
    def test_normal_increase(self):
        self.assertEqual(_percentage_change(100, 110), 10.0)

    def test_normal_decrease(self):
        self.assertEqual(_percentage_change(100, 90), -10.0)

    def test_zero_baseline_returns_none_rather_than_dividing_by_zero(self):
        self.assertIsNone(_percentage_change(0, 50))

    def test_missing_values_return_none(self):
        self.assertIsNone(_percentage_change(None, 50))
        self.assertIsNone(_percentage_change(100, None))


class MaxWeightProgressTests(AnalyticsTestCase):
    def test_no_data_returns_an_empty_series(self):
        self.assertEqual(get_max_weight_progress(self.alice, self.bench), [])

    def test_max_weight_per_session_in_date_order(self):
        self.log_session(self.alice, days_ago=14, sets=[(self.bench, 50, 10)])
        self.log_session(self.alice, days_ago=7, sets=[(self.bench, 55, 10)])
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 8)])

        series = get_max_weight_progress(self.alice, self.bench)

        self.assertEqual([point["value"] for point in series], [50.0, 55.0, 60.0])

    def test_takes_the_heaviest_set_of_each_session(self):
        self.log_session(
            self.alice,
            days_ago=1,
            sets=[(self.bench, 50, 10), (self.bench, 60, 8), (self.bench, 55, 9)],
        )

        series = get_max_weight_progress(self.alice, self.bench)

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["value"], 60.0)

    def test_ignores_unfinished_sessions(self):
        self.log_session(
            self.alice, days_ago=1, sets=[(self.bench, 90, 5)], completed=False
        )
        self.assertEqual(get_max_weight_progress(self.alice, self.bench), [])

    def test_ignores_other_exercises(self):
        self.log_session(
            self.alice, days_ago=1, sets=[(self.bench, 60, 10), (self.squat, 100, 5)]
        )

        series = get_max_weight_progress(self.alice, self.bench)
        self.assertEqual(series[0]["value"], 60.0)

    def test_is_isolated_per_user(self):
        self.log_session(self.bob, days_ago=1, sets=[(self.bench, 100, 5)])
        self.assertEqual(get_max_weight_progress(self.alice, self.bench), [])


class VolumeTests(AnalyticsTestCase):
    def test_volume_is_the_sum_of_weight_times_reps(self):
        # 60x10 + 60x9 + 55x10 = 600 + 540 + 550 = 1690
        self.log_session(
            self.alice,
            days_ago=1,
            sets=[(self.bench, 60, 10), (self.bench, 60, 9), (self.bench, 55, 10)],
        )

        series = get_volume_progress(self.alice, self.bench)

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["value"], 1690.0)

    def test_volume_counts_only_the_requested_exercise(self):
        self.log_session(
            self.alice, days_ago=1, sets=[(self.bench, 60, 10), (self.squat, 100, 10)]
        )

        series = get_volume_progress(self.alice, self.bench)
        self.assertEqual(series[0]["value"], 600.0)

    def test_decimal_weights_are_handled(self):
        # 22.5 x 10 = 225
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, "22.5", 10)])

        series = get_volume_progress(self.alice, self.bench)
        self.assertEqual(series[0]["value"], 225.0)


class EstimatedOneRepMaxProgressTests(AnalyticsTestCase):
    def test_uses_the_best_estimated_1rm_of_each_session(self):
        # 60x10 -> 80.0 ; 70x5 -> 81.67. The heavier set is not the best e1RM.
        self.log_session(
            self.alice, days_ago=1, sets=[(self.bench, 60, 10), (self.bench, 70, 5)]
        )

        series = get_estimated_1rm_progress(self.alice, self.bench)

        self.assertEqual(len(series), 1)
        self.assertAlmostEqual(series[0]["value"], 81.67, places=1)

    def test_progression_across_sessions(self):
        self.log_session(self.alice, days_ago=14, sets=[(self.bench, 60, 10)])  # 80.0
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 65, 10)])  # 86.67

        series = get_estimated_1rm_progress(self.alice, self.bench)

        self.assertAlmostEqual(series[0]["value"], 80.0, places=1)
        self.assertAlmostEqual(series[1]["value"], 86.67, places=1)


class PersonalRecordTests(AnalyticsTestCase):
    def test_no_data_returns_nulls(self):
        records = get_personal_records(self.alice, self.bench)

        self.assertIsNone(records["max_weight"])
        self.assertIsNone(records["best_estimated_1rm"])

    def test_records_track_the_best_ever_values(self):
        self.log_session(self.alice, days_ago=14, sets=[(self.bench, 60, 10)])
        self.log_session(self.alice, days_ago=7, sets=[(self.bench, 80, 3)])
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 70, 8)])

        records = get_personal_records(self.alice, self.bench)

        self.assertEqual(records["max_weight"], 80.0)
        # e1RM: 60x10=80.0, 80x3=88.0, 70x8=88.67 -> the last one wins
        self.assertAlmostEqual(records["best_estimated_1rm"], 88.67, places=1)

    def test_a_better_session_is_a_new_personal_record(self):
        self.log_session(self.alice, days_ago=7, sets=[(self.bench, 60, 10)])
        best = self.log_session(self.alice, days_ago=1, sets=[(self.bench, 70, 10)])

        self.assertTrue(is_new_personal_record(self.alice, self.bench, best))

    def test_a_weaker_session_is_not_a_personal_record(self):
        self.log_session(self.alice, days_ago=7, sets=[(self.bench, 80, 10)])
        weaker = self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 10)])

        self.assertFalse(is_new_personal_record(self.alice, self.bench, weaker))

    def test_the_first_ever_session_counts_as_a_record(self):
        first = self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 10)])
        self.assertTrue(is_new_personal_record(self.alice, self.bench, first))


class ProgressTrendTests(AnalyticsTestCase):
    def test_no_data_reports_nothing(self):
        trend = get_progress_trend(self.alice, self.bench)

        self.assertIsNone(trend["estimated_1rm_change_percentage"])
        self.assertEqual(trend["sessions_analysed"], 0)

    def test_a_single_session_cannot_produce_a_trend(self):
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 10)])
        trend = get_progress_trend(self.alice, self.bench)

        self.assertIsNone(trend["estimated_1rm_change_percentage"])

    def test_improving_1rm_gives_a_positive_change(self):
        self.log_session(self.alice, days_ago=14, sets=[(self.bench, 60, 10)])  # 80.0
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 66, 10)])  # 88.0

        trend = get_progress_trend(self.alice, self.bench)

        self.assertAlmostEqual(trend["estimated_1rm_change_percentage"], 10.0, places=1)

    def test_declining_1rm_gives_a_negative_change(self):
        self.log_session(self.alice, days_ago=14, sets=[(self.bench, 60, 10)])
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 54, 10)])

        trend = get_progress_trend(self.alice, self.bench)

        self.assertLess(trend["estimated_1rm_change_percentage"], 0)


class PlateauHeuristicTests(AnalyticsTestCase):
    def test_too_few_sessions_never_flags_a_plateau(self):
        for days in (21, 14, 7):  # 3 sessions; the minimum is 4
            self.log_session(self.alice, days_ago=days, sets=[(self.bench, 60, 10)])

        result = detect_potential_plateau(self.alice, self.bench)

        self.assertFalse(result["potential_plateau"])
        self.assertEqual(result["reason"], "insufficient_data")

    def test_flat_performance_flags_a_potential_plateau(self):
        for days in (28, 21, 14, 7):
            self.log_session(self.alice, days_ago=days, sets=[(self.bench, 60, 10)])

        result = detect_potential_plateau(self.alice, self.bench)

        self.assertTrue(result["potential_plateau"])
        self.assertEqual(result["reason"], "below_threshold")
        self.assertEqual(result["improvement_percentage"], 0.0)

    def test_steady_improvement_does_not_flag_a_plateau(self):
        for days, weight in ((28, 60), (21, 65), (14, 70), (7, 75)):
            self.log_session(self.alice, days_ago=days, sets=[(self.bench, weight, 10)])

        result = detect_potential_plateau(self.alice, self.bench)

        self.assertFalse(result["potential_plateau"])
        self.assertEqual(result["reason"], "progressing")
        self.assertGreater(
            result["improvement_percentage"], PLATEAU_IMPROVEMENT_THRESHOLD_PERCENT
        )

    def test_improvement_below_the_threshold_flags_a_plateau(self):
        # 60 -> 60.5 is a ~0.83% gain, below the 2% threshold.
        for days, weight in ((28, 60), (21, 60), (14, 60), (7, 60.5)):
            self.log_session(self.alice, days_ago=days, sets=[(self.bench, weight, 10)])

        result = detect_potential_plateau(self.alice, self.bench)
        self.assertTrue(result["potential_plateau"])

    def test_the_minimum_session_constant_is_documented(self):
        self.assertEqual(PLATEAU_MIN_SESSIONS, 4)


class WeeklyFrequencyTests(AnalyticsTestCase):
    def test_no_workouts_returns_an_empty_series(self):
        self.assertEqual(get_weekly_workout_frequency(self.alice), [])

    def test_one_session_is_one_workout_regardless_of_exercise_count(self):
        """Three exercises in one session is still ONE workout."""
        self.log_session(
            self.alice,
            days_ago=1,
            sets=[(self.bench, 60, 10), (self.squat, 100, 5), (self.bench, 55, 10)],
        )

        weeks = get_weekly_workout_frequency(self.alice)

        self.assertEqual(len(weeks), 1)
        self.assertEqual(weeks[0]["workouts"], 1)

    def test_sessions_in_the_same_week_are_counted_together(self):
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 10)])
        self.log_session(self.alice, days_ago=2, sets=[(self.bench, 60, 10)])

        weeks = get_weekly_workout_frequency(self.alice)
        total = sum(week["workouts"] for week in weeks)

        self.assertEqual(total, 2)

    def test_unfinished_sessions_are_not_counted(self):
        self.log_session(
            self.alice, days_ago=1, sets=[(self.bench, 60, 10)], completed=False
        )
        self.assertEqual(get_weekly_workout_frequency(self.alice), [])

    def test_is_isolated_per_user(self):
        self.log_session(self.bob, days_ago=1, sets=[(self.bench, 60, 10)])
        self.assertEqual(get_weekly_workout_frequency(self.alice), [])


class AdherenceTests(AnalyticsTestCase):
    def test_no_workouts_reports_no_adherence(self):
        result = get_adherence(self.alice, planned_days_per_week=4)
        self.assertIsNone(result["average_adherence_percentage"])

    def test_hitting_the_plan_exactly_is_100_percent(self):
        # Four sessions on one day, against a plan of four per week.
        for _ in range(4):
            self.log_session(self.alice, days_ago=0, sets=[(self.bench, 60, 10)])

        result = get_adherence(self.alice, planned_days_per_week=4)

        self.assertEqual(result["weekly"][0]["adherence_percentage"], 100.0)

    def test_half_the_plan_is_50_percent(self):
        for _ in range(2):
            self.log_session(self.alice, days_ago=0, sets=[(self.bench, 60, 10)])

        result = get_adherence(self.alice, planned_days_per_week=4)

        self.assertEqual(result["weekly"][0]["adherence_percentage"], 50.0)

    def test_adherence_is_not_capped_at_100(self):
        """Documented behaviour: training more than planned reports above 100%,
        because hiding it would misrepresent the data to the AI planner.

        All four sessions are logged on the same day so they are guaranteed to
        land in one calendar week whatever weekday the suite runs on.
        """
        for _ in range(4):
            self.log_session(self.alice, days_ago=0, sets=[(self.bench, 60, 10)])

        result = get_adherence(self.alice, planned_days_per_week=2)

        # 4 workouts against a plan of 2 = 200%.
        self.assertEqual(len(result["weekly"]), 1)
        self.assertEqual(result["weekly"][0]["adherence_percentage"], 200.0)
        self.assertEqual(result["average_adherence_percentage"], 200.0)

    def test_a_zero_plan_does_not_divide_by_zero(self):
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 10)])

        result = get_adherence(self.alice, planned_days_per_week=0)
        self.assertIsNone(result["average_adherence_percentage"])

    def test_each_week_reports_its_planned_target(self):
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 10)])

        result = get_adherence(self.alice, planned_days_per_week=3)
        self.assertEqual(result["weekly"][0]["planned"], 3)

    def test_average_weekly_workouts(self):
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 10)])
        self.log_session(self.alice, days_ago=2, sets=[(self.bench, 60, 10)])

        self.assertGreater(get_average_weekly_workouts(self.alice), 0)

    def test_average_weekly_workouts_with_no_data_is_zero(self):
        self.assertEqual(get_average_weekly_workouts(self.alice), 0.0)


class WellnessDashboardTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password=PASSWORD)

    def _log(self, date, weight, **extra):
        return BodyMeasurement.objects.create(
            user=self.alice, recorded_on=date, weight_kg=Decimal(str(weight)), **extra
        )

    def test_empty_dashboard(self):
        dashboard = get_wellness_dashboard(self.alice, height_cm=180)

        self.assertFalse(dashboard["has_data"])
        self.assertEqual(dashboard["charts"]["weight"], [])
        self.assertIsNone(dashboard["latest"])

    def test_latest_values_are_reported(self):
        self._log(datetime.date(2026, 7, 1), 82)
        self._log(datetime.date(2026, 7, 15), 80)

        dashboard = get_wellness_dashboard(self.alice, height_cm=180)

        self.assertTrue(dashboard["has_data"])
        self.assertEqual(dashboard["latest"]["weight_kg"], Decimal("80.0"))

    def test_bmi_is_calculated_from_weight_and_height(self):
        self._log(datetime.date(2026, 7, 1), 81)
        # 81 / (1.8 * 1.8) = 25.0
        dashboard = get_wellness_dashboard(self.alice, height_cm=180)
        self.assertEqual(dashboard["bmi"], 25.0)

    def test_bmi_is_none_without_height(self):
        self._log(datetime.date(2026, 7, 1), 81)
        dashboard = get_wellness_dashboard(self.alice, height_cm=None)
        self.assertIsNone(dashboard["bmi"])

    def test_recent_change_uses_a_four_week_baseline(self):
        self._log(datetime.date(2026, 6, 1), 85)   # baseline (>4 weeks before latest)
        self._log(datetime.date(2026, 7, 15), 80)  # latest

        dashboard = get_wellness_dashboard(self.alice, height_cm=180)
        self.assertEqual(dashboard["changes"]["weight"], -5.0)

    def test_a_single_measurement_has_no_change(self):
        self._log(datetime.date(2026, 7, 1), 80)
        dashboard = get_wellness_dashboard(self.alice, height_cm=180)
        self.assertIsNone(dashboard["changes"]["weight"])

    def test_the_weight_series_is_chronological(self):
        self._log(datetime.date(2026, 7, 15), 80)
        self._log(datetime.date(2026, 7, 1), 82)

        series = get_wellness_dashboard(self.alice, height_cm=180)["charts"]["weight"]
        self.assertEqual([point["value"] for point in series], [82.0, 80.0])

    def test_optional_series_skip_blank_entries(self):
        self._log(datetime.date(2026, 7, 1), 80)  # no body fat
        self._log(datetime.date(2026, 7, 8), 80, body_fat_percentage=Decimal("18.0"))

        charts = get_wellness_dashboard(self.alice, height_cm=180)["charts"]
        self.assertEqual(len(charts["weight"]), 2)
        self.assertEqual(len(charts["body_fat"]), 1)  # only the entry that had it


class CalorieFormulaTests(TestCase):
    """Numbers are pinned to the calculator.net reference (the screenshot):
    25yo male, 180 cm, 65 kg, Moderate -> BMR 1655, maintenance 2425."""

    def test_mifflin_bmr_for_men(self):
        # 10*65 + 6.25*180 - 5*25 + 5 = 1655
        self.assertEqual(round(calculate_bmr(Sex.MALE, 65, 180, 25)), 1655)

    def test_mifflin_bmr_for_women(self):
        # 10*65 + 6.25*180 - 5*25 - 161 = 1489
        self.assertEqual(round(calculate_bmr(Sex.FEMALE, 65, 180, 25)), 1489)

    def test_moderate_activity_matches_the_reference(self):
        bmr = calculate_bmr(Sex.MALE, 65, 180, 25)
        maintenance = calculate_maintenance_calories(bmr, ActivityLevel.MODERATE)
        self.assertEqual(round(maintenance), 2425)  # matches calculator.net

    def test_sedentary_multiplier(self):
        maintenance = calculate_maintenance_calories(2000, ActivityLevel.SEDENTARY)
        self.assertEqual(maintenance, 2400)  # 2000 * 1.2

    def test_targets_match_the_reference_table(self):
        targets = build_calorie_targets(2425, Sex.MALE)
        by_label = {t["label"]: t for t in targets}

        self.assertEqual(by_label["Maintain weight"]["calories"], 2425)
        self.assertEqual(by_label["Mild weight loss"]["calories"], 2175)   # -250
        self.assertEqual(by_label["Weight loss"]["calories"], 1925)        # -500
        self.assertEqual(by_label["Extreme weight loss"]["calories"], 1425)  # -1000
        self.assertEqual(by_label["Weight gain"]["calories"], 2925)        # +500

    def test_target_percentages(self):
        targets = build_calorie_targets(2425, Sex.MALE)
        by_label = {t["label"]: t for t in targets}
        self.assertEqual(by_label["Maintain weight"]["percent"], 100)
        self.assertEqual(by_label["Mild weight loss"]["percent"], 90)
        self.assertEqual(by_label["Extreme weight loss"]["percent"], 59)

    def test_below_floor_is_flagged_for_men(self):
        # maintenance 2200, extreme loss -1000 = 1200 < 1500 floor for men
        targets = build_calorie_targets(2200, Sex.MALE)
        extreme = next(t for t in targets if t["label"] == "Extreme weight loss")
        self.assertTrue(extreme["below_floor"])

    def test_gain_targets_are_never_flagged_below_floor(self):
        targets = build_calorie_targets(1600, Sex.FEMALE)
        for target in targets:
            if target["calories"] > 1600:  # a surplus
                self.assertFalse(target["below_floor"])

    def test_compute_calorie_plan_bundles_everything(self):
        plan = compute_calorie_plan(Sex.MALE, 65, 180, 25, ActivityLevel.MODERATE)
        self.assertEqual(plan["bmr"], 1655)
        self.assertEqual(plan["maintenance_calories"], 2425)
        self.assertEqual(len(plan["targets"]), 7)

    def test_get_calorie_target_by_goal_key(self):
        target = get_calorie_target(2425, Sex.MALE, "loss")
        self.assertEqual(target["calories"], 1925)  # 2425 - 500

    def test_get_calorie_target_falls_back_to_maintain(self):
        target = get_calorie_target(2425, Sex.MALE, "nonsense")
        self.assertEqual(target["label"], "Maintain weight")


class MacroFormulaTests(TestCase):
    """Pinned to the worked examples in the feature spec."""

    def test_protein_is_bodyweight_times_1_8(self):
        macros = compute_macros(2500, 60)
        # 60 * 1.8 = 108 g ; 108 * 4 = 432 kcal
        self.assertEqual(macros["protein"]["grams"], 108)
        self.assertEqual(macros["protein"]["kcal"], 432)

    def test_fat_is_25_percent_of_calories(self):
        macros = compute_macros(2500, 60)
        # 2500 * 0.25 = 625 kcal ; 625 / 9 = 69.4 -> 69 g
        self.assertEqual(macros["fat"]["kcal"], 625)
        self.assertEqual(macros["fat"]["grams"], 69)

    def test_carbs_take_the_remaining_calories(self):
        macros = compute_macros(2500, 60)
        # 2500 - 432 - 625 = 1443 kcal ; 1443 / 4 = 360.75 -> 361 g
        self.assertEqual(macros["carbs"]["kcal"], 1443)
        self.assertEqual(macros["carbs"]["grams"], 361)

    def test_fibre_is_a_flat_target(self):
        macros = compute_macros(2500, 60)
        self.assertEqual(macros["fibre"]["min"], 30)
        self.assertEqual(macros["fibre"]["max"], 40)

    def test_the_macro_kcal_split_never_exceeds_total(self):
        macros = compute_macros(2500, 60)
        total = macros["protein"]["kcal"] + macros["fat"]["kcal"] + macros["carbs"]["kcal"]
        self.assertLessEqual(total, 2500)

    def test_carbs_clamp_at_zero_when_protein_and_fat_exceed_calories(self):
        # A tiny calorie target with a heavy person: protein + fat > calories.
        macros = compute_macros(800, 120)
        self.assertGreaterEqual(macros["carbs"]["grams"], 0)


class ProgressPageTests(AnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def test_progress_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("analytics:progress"))
        self.assertEqual(response.status_code, 302)

    def test_page_renders_with_no_data_at_all(self):
        """An empty account must not produce a broken page."""
        response = self.client.get(reverse("analytics:progress"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose an exercise")

    def test_selecting_an_exercise_with_no_history_explains_itself(self):
        response = self.client.get(
            reverse("analytics:progress"), {"exercise": self.bench.id}
        )

        self.assertContains(response, "No completed workouts with this exercise yet")

    def test_summary_cards_appear_once_there_is_data(self):
        self.log_session(self.alice, days_ago=7, sets=[(self.bench, 60, 10)])
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 65, 10)])

        response = self.client.get(
            reverse("analytics:progress"), {"exercise": self.bench.id}
        )

        self.assertContains(response, "Heaviest weight")
        self.assertContains(response, "Best estimated 1RM")

    def test_estimated_1rm_is_labelled_as_an_estimate(self):
        """It must never be presented as a measured one-rep max."""
        self.log_session(self.alice, days_ago=1, sets=[(self.bench, 60, 10)])

        response = self.client.get(
            reverse("analytics:progress"), {"exercise": self.bench.id}
        )

        self.assertContains(response, "Estimated 1RM")
        self.assertContains(response, "not a measured one-rep max")

    def test_plateau_warning_uses_cautious_wording(self):
        for days in (28, 21, 14, 7):
            self.log_session(self.alice, days_ago=days, sets=[(self.bench, 60, 10)])

        response = self.client.get(
            reverse("analytics:progress"), {"exercise": self.bench.id}
        )

        self.assertContains(response, "Potential plateau")
        self.assertContains(response, "not a diagnosis")

    def test_a_user_cannot_see_another_users_analytics(self):
        self.log_session(self.bob, days_ago=1, sets=[(self.bench, 200, 10)])

        response = self.client.get(
            reverse("analytics:progress"), {"exercise": self.bench.id}
        )

        self.assertContains(response, "No completed workouts with this exercise yet")
