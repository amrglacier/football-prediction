"""Unit tests for core logic: state machine, cutoff, weights, voting."""

import pytest
from datetime import date, datetime
from unittest.mock import patch

from app.core.constants import (
    MatchStatus, STATE_TRANSITIONS, BASE_WEIGHTS, FACTOR_DEFINITIONS,
    LEAGUE_WEIGHT_RULES, ERROR_TAXONOMY,
)
from app.core.state_machine import (
    is_valid_transition, get_cutoff_time, is_locked, can_predict,
)
from app.core.weights import (
    get_dynamic_weights, detect_focus_match, iterate_weight, normalise_weights,
)


# ============================================================
# State Machine Tests
# ============================================================

class TestStateMachine:
    def test_valid_transition_scheduled_to_data_fetching(self):
        assert is_valid_transition(MatchStatus.SCHEDULED, MatchStatus.DATA_FETCHING) is True

    def test_valid_transition_data_ready_to_predicting(self):
        assert is_valid_transition(MatchStatus.DATA_READY, MatchStatus.PREDICTING) is True

    def test_valid_transition_predicted_to_locked(self):
        assert is_valid_transition(MatchStatus.PREDICTED, MatchStatus.LOCKED) is True

    def test_valid_transition_locked_to_finished(self):
        assert is_valid_transition(MatchStatus.LOCKED, MatchStatus.FINISHED) is True

    def test_valid_transition_finished_to_reviewed(self):
        assert is_valid_transition(MatchStatus.FINISHED, MatchStatus.REVIEWED) is True

    def test_invalid_transition_scheduled_to_predicted(self):
        assert is_valid_transition(MatchStatus.SCHEDULED, MatchStatus.PREDICTED) is False

    def test_invalid_transition_locked_to_predicting(self):
        assert is_valid_transition(MatchStatus.LOCKED, MatchStatus.PREDICTING) is False

    def test_invalid_transition_reviewed_to_anything(self):
        # REVIEWED is terminal state
        for target in MatchStatus:
            assert is_valid_transition(MatchStatus.REVIEWED, target) is False

    def test_error_can_recover_to_scheduled(self):
        assert is_valid_transition(MatchStatus.ERROR, MatchStatus.SCHEDULED) is True

    def test_error_can_recover_to_data_ready(self):
        assert is_valid_transition(MatchStatus.ERROR, MatchStatus.DATA_READY) is True

    def test_predicted_can_update_prediction(self):
        # PREDICTED -> PREDICTING (for updating V_latest)
        assert is_valid_transition(MatchStatus.PREDICTED, MatchStatus.PREDICTING) is True


# ============================================================
# Cutoff Time Tests
# ============================================================

class TestCutoffTime:
    def test_weekday_cutoff_is_22(self):
        # 2026-07-22 is a Wednesday
        d = date(2026, 7, 22)
        cutoff = get_cutoff_time(d)
        assert cutoff.hour == 22

    def test_weekend_cutoff_is_23(self):
        # 2026-07-25 is a Saturday
        d = date(2026, 7, 25)
        cutoff = get_cutoff_time(d)
        assert cutoff.hour == 23

    def test_sunday_cutoff_is_23(self):
        # 2026-07-26 is a Sunday
        d = date(2026, 7, 26)
        cutoff = get_cutoff_time(d)
        assert cutoff.hour == 23

    def test_monday_cutoff_is_22(self):
        # 2026-07-20 is a Monday
        d = date(2026, 7, 20)
        cutoff = get_cutoff_time(d)
        assert cutoff.hour == 22

    def test_friday_cutoff_is_22(self):
        # 2026-07-24 is a Friday
        d = date(2026, 7, 24)
        cutoff = get_cutoff_time(d)
        assert cutoff.hour == 22

    def test_cutoff_returns_timezone_aware(self):
        d = date(2026, 7, 22)
        cutoff = get_cutoff_time(d)
        assert cutoff.tzinfo is not None

    def test_is_locked_before_cutoff(self):
        # 2026-07-22 (Wednesday), check at 21:59
        d = date(2026, 7, 22)
        import pytz
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 7, 22, 21, 59))
        assert is_locked(d, now) is False

    def test_is_locked_at_cutoff(self):
        # 2026-07-22 (Wednesday), check at 22:00
        d = date(2026, 7, 22)
        import pytz
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 7, 22, 22, 0))
        assert is_locked(d, now) is True

    def test_is_locked_after_cutoff(self):
        # 2026-07-22 (Wednesday), check at 23:30
        d = date(2026, 7, 22)
        import pytz
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 7, 22, 23, 30))
        assert is_locked(d, now) is True

    def test_can_predict_before_cutoff(self):
        d = date(2026, 7, 22)
        import pytz
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 7, 22, 20, 0))
        assert can_predict(d, now) is True

    def test_can_predict_false_after_cutoff(self):
        d = date(2026, 7, 22)
        import pytz
        tz = pytz.timezone("Asia/Shanghai")
        now = tz.localize(datetime(2026, 7, 22, 22, 30))
        assert can_predict(d, now) is False


# ============================================================
# Weight Calculation Tests
# ============================================================

class TestWeights:
    def test_base_weights_sum_to_one(self):
        total = sum(BASE_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01, f"Base weights sum to {total}, expected 1.0"

    def test_eight_factors_defined(self):
        assert len(FACTOR_DEFINITIONS) == 8
        for i in range(1, 9):
            assert f"F{i}" in FACTOR_DEFINITIONS

    def test_dynamic_weights_sum_to_one(self):
        weights = get_dynamic_weights("英超")
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01

    def test_dynamic_weights_with_focus_match(self):
        weights = get_dynamic_weights("英超", is_focus_match=True)
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01

    def test_nordic_league_env_boosted(self):
        weights = get_dynamic_weights("瑞超")
        # F8 should be higher than base in Nordic leagues
        assert weights["F8"] > BASE_WEIGHTS["F8"]

    def test_nordic_league_historical_reduced(self):
        weights = get_dynamic_weights("瑞超")
        # F5 should be lower than base in Nordic leagues
        assert weights["F5"] < BASE_WEIGHTS["F5"]

    def test_top_league_fitness_boosted(self):
        weights = get_dynamic_weights("英超")
        # F6 should be higher than base
        assert weights["F6"] > BASE_WEIGHTS["F6"]

    def test_focus_match_cold_hunter_boosted(self):
        weights = get_dynamic_weights("英超", is_focus_match=True)
        assert weights["F7"] > BASE_WEIGHTS["F7"]

    def test_normal_match_odds_boosted(self):
        weights = get_dynamic_weights("英超", is_focus_match=False)
        assert weights["F1"] > BASE_WEIGHTS["F1"]

    def test_detect_focus_match_derby(self):
        assert detect_focus_match("皇马", "马竞", "西甲", "马德里德比") is True

    def test_detect_focus_match_normal(self):
        assert detect_focus_match("卡尔马", "马尔默", "瑞超") is False

    def test_iterate_weight_decreases_on_error(self):
        old = 0.20
        new = iterate_weight("F1", "瑞超", old, is_error=True)
        assert new < old

    def test_iterate_weight_no_change_on_correct(self):
        old = 0.20
        new = iterate_weight("F1", "瑞超", old, is_error=False)
        assert new == old

    def test_iterate_weight_nordic_double_penalty(self):
        # Nordic leagues have 1.5x sensitivity
        w_normal = iterate_weight("F1", "英超", 0.20, is_error=True)
        w_nordic = iterate_weight("F1", "瑞超", 0.20, is_error=True)
        assert w_nordic < w_normal, "Nordic league should have larger penalty"

    def test_iterate_weight_minimum_floor(self):
        # Should not go below 0.01
        w = iterate_weight("F1", "瑞超", 0.01, is_error=True)
        assert w >= 0.01

    def test_normalise_weights(self):
        raw = {"F1": 0.3, "F2": 0.2, "F3": 0.5}
        normalised = normalise_weights(raw)
        assert abs(sum(normalised.values()) - 1.0) < 0.001


# ============================================================
# Error Taxonomy Tests
# ============================================================

class TestErrorTaxonomy:
    def test_all_8_errors_defined(self):
        for i in range(1, 9):
            code = f"E{i:03d}"
            assert code in ERROR_TAXONOMY

    def test_each_error_has_factor_mapping(self):
        for code, entry in ERROR_TAXONOMY.items():
            assert "factor_id" in entry
            assert entry["factor_id"] in FACTOR_DEFINITIONS

    def test_error_codes_are_unique(self):
        codes = [e["code"] for e in ERROR_TAXONOMY.values()]
        assert len(codes) == len(set(codes))
