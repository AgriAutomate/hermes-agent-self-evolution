#!/usr/bin/env python3
"""The sampling governor — Jev over the evolver's posture.

The Darwinian Evolver tunes its sampling parameters by eye: the README's
guidance ("adjust to fit an expected score range, or to prioritize between
exploiting the highest-scoring organisms and generating more diverse
populations") has illustrative sigmoid plots and NO rule for WHEN to adjust.
The posture (`--sharpness`, default 10; `--midpoint_score`, default p75) is
fixed for an entire run, so a run that plateaus keeps exploiting at p75
exactly when diversity is needed to escape the local optima.

This governor runs the evolver in SEGMENTS (e.g. --num_iterations 5), reads
results.jsonl between segments, asks Jev ONE Choice judgment over the
observed state, and maps the answer through a FIXED dictionary to the next
segment's flags.

Design constraints (docs/SELF-EVOLUTION.md, the sampling governor section):

- Code owns the arithmetic. The posture→flags mapping is a fixed dictionary
  bounded to the README's documented ranges (sharpness 5–20, midpoint pXX) —
  there is no code path for an out-of-range value.
- Thresholds are DECLARED PROVISIONAL: a posture change needs confidence
  > 0.5, stop needs > 0.8, and below the floor the governor falls back to
  `hold` (the conservative default). Calibrated vs own labels is future work.
- One Jev request per segment. Every request is a ledger row (the budget
  rail lives in the driver, not here).
- Licence-clean: this module never imports darwinian_evolver; the evolver CLI
  is invoked unmodified (mere aggregation).

The Jev judgment is injected: the shadow test passes a stub, never the live
API. The live path (ask_jev_choice) is separate so the budget rail can gate
it.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Protocol

# The README's documented ranges — the mapping is bounded to these.
SHARPNESS_RANGE = (5, 20)
MIDPOINT_PERCENTILE_RANGE = (0, 100)

# DECLARED PROVISIONAL thresholds — calibrated vs own labels is future work.
POSTURE_CHANGE_CONFIDENCE = 0.5
STOP_CONFIDENCE = 0.8


class PostureVerdict(Protocol):
    """What a posture judgment returns. The live Jev Choice answer and the
    shadow-test stub both satisfy this."""

    verdict: str
    confidence: float


# The fixed dictionary — posture → the next segment's flags. There is no code
# path that can set a value outside the documented ranges: every entry is a
# literal within SHARPNESS_RANGE / the percentile syntax.
FLAG_PRESETS: dict[str, dict[str, Any]] = {
    "exploit": {"sharpness": 20, "midpoint_score": "p90"},
    "explore": {"sharpness": 5, "midpoint_score": "p50"},
    "hold": None,  # keep the current posture unchanged
    "stop": None,  # end the run; no flags change
}

VALID_POSTURES = ("exploit", "explore", "hold", "stop")


def build_state(
    results: list[dict[str, Any]],
    goal: str,
    current_posture: dict[str, Any],
    window: int = 5,
) -> dict[str, Any]:
    """Build the named Jev state from OBSERVED results only.

    `results` is the parsed results.jsonl rows (iteration, best_score,
    population_size, ...) in run order. Derived arithmetic (the trend, the
    plateau count) is computed here in code — never asked of the model.
    """
    if not results:
        raise ValueError("no results rows to build state from")
    ordered = sorted(results, key=lambda r: int(r.get("iteration", 0)))
    recent = ordered[-window:]
    best_scores = [float(r["best_score"]) for r in recent]
    populations = [int(r.get("population_size", 0)) for r in recent]
    # The novelty signal: distinct children per iteration, when recorded.
    children = [
        int(r["distinct_children"])
        for r in recent
        if r.get("distinct_children") is not None
    ]
    peak = max(best_scores)
    improvement = round(best_scores[-1] - best_scores[0], 6)
    plateau = (
        sum(1 for s in best_scores if s == peak)
        if len(best_scores) > 1
        else len(best_scores)
    )
    learning = [
        str(r.get("observed_outcome") or r.get("attempted_change") or "")
        for r in recent
        if r.get("observed_outcome") or r.get("attempted_change")
    ]
    return {
        "evolution": {
            "goal": goal,
            "iterations_so_far": int(ordered[-1].get("iteration", 0)),
            f"best_scores_last_{len(best_scores)}": best_scores,
            "best_score_peak": peak,
            "improvement_over_window": improvement,
            "population_size_last": populations[-1] if populations else 0,
            "distinct_children_per_iteration": children,
            "plateau_iterations": plateau,
            "learning_log_outcomes": learning,
            "current_posture": current_posture,
        }
    }


POSTURE_QUESTION = {
    "posture": {
        "type": "choice",
        "instructions": (
            "Given this evolution state, which sampling posture should the "
            "next segment use? The evolver balances exploiting the "
            "highest-scoring organisms against generating diverse "
            "populations. A plateau with shrinking novelty suggests "
            "exploration; steady improvement suggests holding the current "
            "posture; a score converged at its peak suggests stopping."
        ),
        "criteria": {
            "exploit": "Scores improving steadily; concentrate on the best organisms. sharpness 20, midpoint p90.",
            "explore": "Scores plateaued and/or novelty shrinking; diversity to escape a local optimum. sharpness 5, midpoint p50.",
            "hold": "The current posture is working; keep sharpness and midpoint unchanged.",
            "stop": "The score is converged at its peak and further segments are unlikely to help; end the run early.",
        },
    }
}

JUDGE_PROMPT_TEMPLATE = (
    "Decide the next sampling posture for this evolution run. State:\n{state}"
)


def ask_jev_choice(
    state: dict[str, Any],
    *,
    api_key: str,
    endpoint: str = "https://api.typesafe.ai/v1/systemone",
    model: str = "jev-latest",
) -> dict[str, Any]:
    """The LIVE Jev path. NOT exercised by the shadow test — the budget rail
    gates this (one ledger row per request, the driver's job)."""
    import urllib.request

    body = json.dumps(
        {
            "state": JUDGE_PROMPT_TEMPLATE.format(state=state),
            "model": model,
            "questions": POSTURE_QUESTION,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - the fixed endpoint
        answer = json.loads(resp.read().decode("utf-8"))
    entry = answer["answers"]["posture"]
    return {"verdict": entry["choice"], "confidence": entry["confidence"]}


def apply_verdict(
    current_posture: dict[str, Any], verdict: PostureVerdict
) -> dict[str, Any]:
    """Map the verdict through the fixed dictionary under the thresholds.

    Code owns the arithmetic: the mapping is a fixed dictionary bounded to the
    documented ranges. A posture change below the confidence floor falls back
    to hold; stop below its (higher) floor falls back to hold; an unknown
    verdict falls back to hold. The current posture is never mutated.
    """
    v = (verdict.verdict or "").strip().lower()
    confidence = float(verdict.confidence)
    if v not in VALID_POSTURES:
        return dict(current_posture)
    if v == "hold":
        return dict(current_posture)
    if v == "stop":
        if confidence > STOP_CONFIDENCE:
            return {
                "stop": True,
                "sharpness": current_posture.get("sharpness", 10),
                "midpoint_score": current_posture.get("midpoint_score", "p75"),
            }
        return dict(current_posture)
    # exploit / explore: a posture CHANGE — gated at the lower floor.
    if confidence > POSTURE_CHANGE_CONFIDENCE:
        preset = FLAG_PRESETS[v]
        sharpness = int(preset["sharpness"])
        midpoint = str(preset["midpoint_score"])
        assert SHARPNESS_RANGE[0] <= sharpness <= SHARPNESS_RANGE[1]
        pct = int(midpoint[1:])
        assert MIDPOINT_PERCENTILE_RANGE[0] <= pct <= MIDPOINT_PERCENTILE_RANGE[1]
        return {"sharpness": sharpness, "midpoint_score": midpoint}
    return dict(current_posture)


GovernorJudge = Callable[[dict[str, Any]], PostureVerdict]


def run_segment(
    results: list[dict[str, Any]],
    goal: str,
    current_posture: dict[str, Any],
    judge: GovernorJudge,
) -> dict[str, Any]:
    """One segment step: build the state, judge, map. Returns the next
    segment's flags (and stop when the verdict clears the stop floor). The
    judge is injected — the shadow test stubs it; the driver passes the live
    path behind the budget rail."""
    state = build_state(results, goal, current_posture)
    verdict = judge(state)
    return apply_verdict(current_posture, verdict)
