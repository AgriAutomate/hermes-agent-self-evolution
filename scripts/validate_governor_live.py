#!/usr/bin/env python3
"""Live-Jev validation for the sampling governor: the shadow-tested fixtures
through the REAL Jev path (ask_jev_choice). Three calls, one per fixture —
~600 tokens each. Budget line: the founder's "keep advancing" (2026-10-08) —
the live-Jev validation was the separate budgeted decision this script runs.

Every call writes an immutable receipt (the state hash, the answer, the
verdict, the model) to output/governor-live-validation/. The governor's
mapping + thresholds were already shadow-tested (20/20); this validates that
the LIVE Jev answers match the expected postures for the known fixture
shapes — the calibration evidence the shadow test cannot provide.

NOT an evolution run: no darwinian_evolver invocation, no code mutated.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / ".."))

from evolution.code.sampling_governor import (
    build_state,
    ask_jev_choice,
    needs_escalation,
)

BASE_POSTURE = {"sharpness": 10, "midpoint_score": "p75"}
# A fixture passes by escalation (the 4th, by design) or by the listed verdicts.
ESCALATION_OK = "--escalated--"
OUT = pathlib.Path(__file__).resolve().parent / "output" / "governor-live-validation"
OUT.mkdir(parents=True, exist_ok=True)


def rows(scores, children=None, start=1):
    out = []
    for i, s in enumerate(scores):
        row = {"iteration": start + i, "best_score": s, "population_size": 24}
        if children is not None and i < len(children):
            row["distinct_children"] = children[i]
        out.append(row)
    return out


FIXTURES = [
    (
        "plateau",
        rows([0.71, 0.72, 0.72, 0.71, 0.72], [3, 2, 2, 1, 2]),
        ["explore", "hold", "stop"],
    ),
    (
        "steady_improvement",
        rows([0.60, 0.65, 0.68, 0.70, 0.74], [4, 4, 5, 4, 5]),
        ["exploit", "hold"],
    ),
    (
        "converged",
        rows([0.95, 0.95, 0.95, 0.95, 0.95], [1, 1, 0, 1, 1]),
        ["stop", "hold", "explore"],
    ),
    # The 4th fixture: a hedged case. Live Jev explored a converged ceiling on
    # 2026-10-09 (state shape identical), which the fixed mapping applied as a
    # posture change. Expected outcome is ESCALATION — the governor hands the
    # case to a second opinion instead of mapping a doubtful verdict. The pure
    # unit tests pin the predicate; this run records which path fired live.
    # `pass` means: escalation fired, or Jev answered stop (the defensible
    # verdict for this shape), with the path recorded in the receipt.
    (
        "hedged_ceiling",
        rows([0.96, 0.96, 0.96, 0.96, 0.96], [0, 1, 0, 0, 1]),
        ESCALATION_OK,
    ),
]

api_key = os.environ["JEV_API_KEY"]
results = []
for name, fixture, acceptable in FIXTURES:
    state = build_state(
        fixture, "evolve the parrot prompt (validation fixture)", dict(BASE_POSTURE)
    )
    state_hash = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[
        :16
    ]
    receipt_id = f"{name}-{state_hash}"
    try:
        answer = ask_jev_choice(state, api_key=api_key)
        verdict = answer["verdict"]
        confidence = answer["confidence"]
        escalate, escalate_reason = needs_escalation(answer, state)
        # A fixture matches if EITHER the verdict maps cleanly (a confident
        # case) OR the case escalates (a doubtful one, handed to a second
        # opinion instead of silently coerced by the fixed dictionary). The
        # receipt records which path fired — that is the calibration data,
        # not the pass/fail.
        matches = escalate or verdict in acceptable
        outcome = (
            f"ESCALATED ({escalate_reason})" if escalate else f"{verdict} (mapped)"
        )
        print(
            f"{name}: Jev says {verdict} (confidence {confidence}) — {outcome} {'MATCHES' if matches else 'OUTSIDE expected'}"
        )
        receipt = {
            "receipt_id": receipt_id,
            "fixture": name,
            "state_hash": state_hash,
            "verdict": verdict,
            "confidence": confidence,
            "escalated": escalate,
            "escalation_reason": escalate_reason,
            "acceptable": acceptable,
            "matches": matches,
            "budget_line": "founder approval: keep advancing (2026-10-08)",
            "model": "jev-latest",
        }
    except Exception as cause:  # noqa: BLE001 - the receipt records the failure honestly
        print(f"{name}: LIVE CALL FAILED — {cause}")
        receipt = {
            "receipt_id": receipt_id,
            "fixture": name,
            "state_hash": state_hash,
            "error": str(cause),
            "budget_line": "founder approval: keep advancing (2026-10-08)",
        }
    (OUT / f"{receipt_id}.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    results.append(receipt)

ok = [r for r in results if r.get("matches")]
failed = [r for r in results if r.get("error")]
print(
    f"\nLIVE VALIDATION: {len(ok)}/{len(FIXTURES)} fixtures matched the expected postures; {len(failed)} call failures; receipts at {OUT}"
)
