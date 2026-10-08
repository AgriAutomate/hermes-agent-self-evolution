"""Shadow test for the sampling governor: fixtures with known shapes, a stub
judge, and the fixed flag mapping. No real Jev calls, no evolution costs —
the live path (ask_jev_choice) is never exercised here (the budget rail).

Fixtures: a plateau (expect explore), steady improvement (expect hold/exploit
via the thresholds), converged (a stop candidate), and the absent/unknown
paths (the honest hold fallback).
"""

from __future__ import annotations

import pytest

from evolution.code.sampling_governor import (
    FLAG_PRESETS,
    MIDPOINT_PERCENTILE_RANGE,
    POSTURE_CHANGE_CONFIDENCE,
    SHARPNESS_RANGE,
    STOP_CONFIDENCE,
    apply_verdict,
    build_state,
    run_segment,
)

BASE_POSTURE = {"sharpness": 10, "midpoint_score": "p75"}


def rows(
    scores: list[float],
    children: list[int] | None = None,
    start: int = 1,
    outcome: str | None = None,
) -> list[dict]:
    out = []
    for i, s in enumerate(scores):
        row = {"iteration": start + i, "best_score": s, "population_size": 24}
        if children is not None and i < len(children):
            row["distinct_children"] = children[i]
        if outcome:
            row["observed_outcome"] = outcome
        out.append(row)
    return out


class StubVerdict:
    def __init__(self, verdict: str, confidence: float):
        self.verdict = verdict
        self.confidence = confidence


class TestBuildState:
    def test_state_from_fixture(self):
        state = build_state(
            rows([0.71, 0.72, 0.72, 0.71, 0.72], [3, 2, 2, 1, 2]),
            "evolve the parrot prompt",
            dict(BASE_POSTURE),
        )
        evo = state["evolution"]
        assert evo["best_scores_last_5"] == [0.71, 0.72, 0.72, 0.71, 0.72]
        assert evo["best_score_peak"] == 0.72
        assert evo["improvement_over_window"] == 0.01
        assert evo["distinct_children_per_iteration"] == [3, 2, 2, 1, 2]
        assert evo["current_posture"] == BASE_POSTURE

    def test_plateau_count_is_code_arithmetic(self):
        state = build_state(
            rows([0.72, 0.72, 0.72, 0.72, 0.72]), "goal", dict(BASE_POSTURE)
        )
        assert state["evolution"]["plateau_iterations"] == 5

    def test_out_of_order_rows_are_sorted(self):
        state = build_state(rows([0.5, 0.9], start=4), "goal", dict(BASE_POSTURE))
        assert state["evolution"]["iterations_so_far"] == 5
        assert state["evolution"]["best_score_peak"] == 0.9

    def test_empty_results_raise(self):
        with pytest.raises(ValueError):
            build_state([], "goal", dict(BASE_POSTURE))

    def test_children_optional(self):
        state = build_state(rows([0.5, 0.6]), "goal", dict(BASE_POSTURE))
        assert state["evolution"]["distinct_children_per_iteration"] == []


class TestFixedMappingBounds:
    def test_every_preset_within_documented_ranges(self):
        for posture, preset in FLAG_PRESETS.items():
            if preset is None:
                continue
            assert SHARPNESS_RANGE[0] <= preset["sharpness"] <= SHARPNESS_RANGE[1], (
                posture
            )
            assert (
                MIDPOINT_PERCENTILE_RANGE[0]
                <= int(preset["midpoint_score"][1:])
                <= MIDPOINT_PERCENTILE_RANGE[1]
            ), posture

    def test_no_out_of_range_path(self):
        # The mapping is a fixed dictionary: whatever the verdict says, the
        # resulting flags are one of the presets or the current posture.
        for posture in ("exploit", "explore", "hold", "stop", "garbage", ""):
            for confidence in (0.0, 0.49, 0.5, 0.51, 0.79, 0.8, 0.81, 1.0):
                result = apply_verdict(
                    dict(BASE_POSTURE), StubVerdict(posture, confidence)
                )
                if result.get("stop"):
                    assert result["sharpness"] == BASE_POSTURE["sharpness"]
                elif result != BASE_POSTURE:
                    assert result in (FLAG_PRESETS["exploit"], FLAG_PRESETS["explore"])


class TestThresholds:
    def test_plateau_explore_above_floor(self):
        result = apply_verdict(dict(BASE_POSTURE), StubVerdict("explore", 0.7))
        assert result == FLAG_PRESETS["explore"]

    def test_explore_below_floor_falls_back_to_hold(self):
        result = apply_verdict(
            dict(BASE_POSTURE), StubVerdict("explore", POSTURE_CHANGE_CONFIDENCE)
        )
        assert result == BASE_POSTURE

    def test_exploit_below_floor_falls_back_to_hold(self):
        result = apply_verdict(dict(BASE_POSTURE), StubVerdict("exploit", 0.2))
        assert result == BASE_POSTURE

    def test_exploit_above_floor(self):
        result = apply_verdict(dict(BASE_POSTURE), StubVerdict("exploit", 0.9))
        assert result == FLAG_PRESETS["exploit"]

    def test_stop_needs_higher_floor(self):
        result = apply_verdict(dict(BASE_POSTURE), StubVerdict("stop", 0.8))
        assert result == BASE_POSTURE
        result = apply_verdict(dict(BASE_POSTURE), StubVerdict("stop", 0.81))
        assert result.get("stop") is True

    def test_hold_never_mutates(self):
        current = dict(BASE_POSTURE)
        result = apply_verdict(current, StubVerdict("hold", 1.0))
        assert result == BASE_POSTURE and current == BASE_POSTURE

    def test_unknown_verdict_falls_back_to_hold(self):
        result = apply_verdict(dict(BASE_POSTURE), StubVerdict("garbage", 1.0))
        assert result == BASE_POSTURE

    def test_boundary_confidence_exactly_at_floor_is_hold(self):
        # > 0.5 is the rule: exactly at the floor is NOT a change.
        assert (
            apply_verdict(
                dict(BASE_POSTURE), StubVerdict("explore", POSTURE_CHANGE_CONFIDENCE)
            )
            == BASE_POSTURE
        )


class TestRunSegment:
    def test_plateau_fixture_yields_explore(self):
        fixture = rows([0.71, 0.72, 0.72, 0.71, 0.72], [3, 2, 2, 1, 2])
        result = run_segment(
            fixture,
            "evolve the parrot prompt",
            dict(BASE_POSTURE),
            lambda state: StubVerdict("explore", 0.7),
        )
        assert result == FLAG_PRESETS["explore"]

    def test_steady_improvement_yields_exploit(self):
        fixture = rows([0.60, 0.65, 0.68, 0.70, 0.74], [4, 4, 5, 4, 5])
        result = run_segment(
            fixture,
            "goal",
            dict(BASE_POSTURE),
            lambda state: StubVerdict("exploit", 0.9),
        )
        assert result == FLAG_PRESETS["exploit"]

    def test_converged_fixture_yields_stop_above_floor(self):
        fixture = rows([0.95, 0.95, 0.95, 0.95, 0.95], [1, 1, 0, 1, 1])
        result = run_segment(
            fixture, "goal", dict(BASE_POSTURE), lambda state: StubVerdict("stop", 0.85)
        )
        assert result.get("stop") is True

    def test_low_confidence_stub_yields_hold(self):
        fixture = rows([0.71, 0.72, 0.72, 0.71, 0.72], [3, 2, 2, 1, 2])
        result = run_segment(
            fixture,
            "goal",
            dict(BASE_POSTURE),
            lambda state: StubVerdict("explore", 0.3),
        )
        assert result == BASE_POSTURE

    def test_the_governor_never_imports_darwinian_evolver(self):
        # The licence condition: the governor is driver-side, the evolver CLI
        # is invoked unmodified (mere aggregation). Assert the module source
        # carries no darwinian_evolver import.
        import inspect
        import evolution.code.sampling_governor as gov

        src = inspect.getsource(gov)
        assert "from darwinian_evolver" not in src
        assert "import darwinian_evolver" not in src
