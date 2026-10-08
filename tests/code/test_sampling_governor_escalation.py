"""Escalation: the hedged-judgment path. The fixed dictionary coerces (below
the floor -> silent hold; a contradictory verdict -> applied verbatim);
needs_escalation runs BEFORE it and hands the case to a second opinion."""

from types import SimpleNamespace

from evolution.code.sampling_governor import (
    POSTURE_CHANGE_CONFIDENCE,
    analyze_trend,
    build_state,
    needs_escalation,
)

BASE_POSTURE = {"sharpness": 10, "midpoint_score": "p75"}


def _rows(scores, children):
    return [
        {
            "iteration": i + 1,
            "best_score": s,
            "population_size": 24,
            "distinct_children": c,
        }
        for i, (s, c) in enumerate(zip(scores, children))
    ]


def _state(scores, children):
    return build_state(_rows(scores, children), "goal", dict(BASE_POSTURE))


def _v(verdict, confidence):
    return SimpleNamespace(verdict=verdict, confidence=confidence)


def test_below_floor_escalates():
    escalate, reason = needs_escalation(
        _v("exploit", POSTURE_CHANGE_CONFIDENCE), _state([0.6] * 5, [2] * 5)
    )
    assert escalate and reason == "below-confidence-floor"


def test_exploit_without_improvement_escalates():
    escalate, reason = needs_escalation(_v("exploit", 0.9), _state([0.7] * 5, [2] * 5))
    assert escalate and reason == "exploit-without-improvement"


def test_explore_while_climbing_escalates():
    escalate, reason = needs_escalation(
        _v("explore", 0.9), _state([0.60, 0.65, 0.68, 0.70, 0.74], [4, 4, 5, 4, 5])
    )
    assert escalate and reason == "explore-while-improving"


def test_explore_on_ceiling_escalates():
    escalate, reason = needs_escalation(
        _v("explore", 0.88), _state([0.95] * 5, [1, 1, 0, 1, 1])
    )
    assert escalate and reason == "explore-on-ceiling"


def test_hold_on_clean_improvement_escalates():
    escalate, reason = needs_escalation(
        _v("hold", 0.73), _state([0.60, 0.65, 0.68, 0.70, 0.74], [4, 4, 5, 4, 5])
    )
    assert escalate and reason == "hold-on-clean-improvement"


def test_plateau_explore_maps_despite_wobble():
    # 0.71,0.72,0.72,0.71,0.72 is a +0.01 wobble, NOT a climb: the noise margin
    # keeps the canonical explore case mapping instead of escalating.
    trend = analyze_trend(_state([0.71, 0.72, 0.72, 0.71, 0.72], [3, 2, 2, 1, 2]))
    assert not trend["climbing"]
    escalate, _ = needs_escalation(
        _v("explore", 0.96), _state([0.71, 0.72, 0.72, 0.71, 0.72], [3, 2, 2, 1, 2])
    )
    assert not escalate


def test_decisive_verdicts_do_not_escalate():
    assert not needs_escalation(
        _v("exploit", 0.9), _state([0.60, 0.65, 0.68, 0.70, 0.74], [4, 4, 5, 4, 5])
    )[0]
    assert not needs_escalation(_v("stop", 0.9), _state([0.95] * 5, [1, 1, 0, 1, 1]))[0]


def test_invalid_answers_escalate():
    assert needs_escalation(
        _v("exploit", 1.7), _state([0.6, 0.65, 0.68, 0.7, 0.74], [4] * 5)
    )[0]
    assert needs_escalation(
        _v("gamble", 0.99), _state([0.6, 0.65, 0.68, 0.7, 0.74], [4] * 5)
    )[0]


def test_live_dict_shape_accepted():
    # ask_jev_choice returns a dict; the shadow runner passes objects.
    assert needs_escalation(
        {"verdict": "explore", "confidence": 0.9},
        _state([0.6, 0.65, 0.68, 0.7, 0.74], [4] * 5),
    )[0]
    assert not needs_escalation(
        {"verdict": "exploit", "confidence": 0.9},
        _state([0.6, 0.65, 0.68, 0.7, 0.74], [4] * 5),
    )[0]
