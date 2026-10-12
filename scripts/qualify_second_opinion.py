#!/usr/bin/env python3
"""Budgeted qualification of the governor's second opinion on recorded states.

The committed live-validation receipts already contain the PRIMARY judgment for
each known fixture shape. This script spends calls ONLY on the cases the primary
judgment left doubtful, so the spend is proportional to the real need.

Method (no judge model grades the run):
  1. Reconstruct each committed fixture and verify its saved state hash. A
     receipt whose hash no longer matches the current fixture is EXCLUDED, not
     reinterpreted.
  2. Replay the recorded primary answer. Compute needs_escalation deterministically.
  3. For doubtful cases only, call the live second opinion through a RequestLedger
     with an explicit call cap and one receipt per dispatch.
  4. Re-check the second answer with the SAME predicate. `needs_escalation`
     already returns True for a verdict that contradicts the observed trend, so
     "resolved" (the runner would apply it) implies trend consistency;
     `trendConsistent` is recorded as an additional explicit check, not a second
     gate. `BudgetExhausted` stops the loop (it is a refusal, not a call failure).
  5. Write the JSON report AND a markdown summary from that same JSON, so the
     human-readable numbers cannot drift from the artifact.

Budget line: CAP-approved 2026-10-12, max US$1 and 32 dispatch attempts combined
for governor/skill qualification. This script's own cap is the --max-calls flag.

NOT an evolution run: no darwinian_evolver invocation, no product mutation.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import sys
import time
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evolution.code.request_ledger import BudgetExhausted, RequestLedger, write_json  # noqa: E402
from evolution.code.sampling_governor import (  # noqa: E402
    analyze_trend,
    apply_verdict,
    ask_jev_choice,
    build_state,
    needs_escalation,
)

BASE_POSTURE = {"sharpness": 10, "midpoint_score": "p75"}
GOAL = "evolve the parrot prompt (validation fixture)"
RECEIPTS = ROOT / "scripts" / "output" / "governor-live-validation"
OUT = ROOT / "scripts" / "output" / "second-opinion-qualification"


def fixtures_from_driver() -> dict[str, list[dict]]:
    """Read the fixture shapes from the committed validation driver (one source
    of truth; no duplicated literals)."""
    tree = ast.parse(
        (ROOT / "scripts" / "validate_governor_live.py").read_text(encoding="utf-8")
    )
    node = next(
        n.value
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "FIXTURES" for t in n.targets)
    )
    shapes: dict[str, list[dict]] = {}
    for item in node.elts:
        name = ast.literal_eval(item.elts[0])
        args = [ast.literal_eval(a) for a in item.elts[1].args]
        scores = args[0]
        children = args[1] if len(args) > 1 else None
        shapes[name] = [
            {
                "iteration": i + 1,
                "best_score": s,
                "population_size": 24,
                **({"distinct_children": children[i]} if children else {}),
            }
            for i, s in enumerate(scores)
        ]
    return shapes


def trend_consistent(posture: dict, state: dict) -> bool:
    """Does the mapped posture avoid contradicting the observed trend?

    Code owns this check; it mirrors needs_escalation's contradiction rules.
    """
    trend = analyze_trend(state)
    if posture.get("stop"):
        return trend["plateaued"]
    if posture.get("sharpness") == 5:  # explore
        return not trend["climbing"]
    if posture.get("sharpness") == 20:  # exploit
        return trend["climbing"]
    return True  # hold: never contradicts on its own


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=8)
    ap.add_argument("--budget-note", default="")
    ap.add_argument("--model", default="jev-latest")
    args = ap.parse_args()
    if not 1 <= args.max_calls <= 32:
        raise SystemExit("max-calls must be within the approved 1..32 range")
    if not args.budget_note.strip():
        raise SystemExit("live requests require an explicit budget note")

    api_key = os.environ.get("JEV_API_KEY")
    if not api_key:
        raise SystemExit("JEV_API_KEY is unavailable")

    shapes = fixtures_from_driver()
    # Each run gets its own directory: receipts are immutable (exclusive write),
    # so a re-run must not collide with an earlier one.
    run_dir = OUT / time.strftime("run-%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    ledger = RequestLedger(run_dir / "requests", args.max_calls, args.budget_note)

    rows: list[dict] = []
    excluded: list[dict] = []
    for path in sorted(RECEIPTS.glob("*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if "verdict" not in receipt:
            continue
        rows.append(receipt)

    results: list[dict] = []
    for receipt in rows:
        shape = shapes[receipt["fixture"]]
        state = build_state(shape, GOAL, dict(BASE_POSTURE))
        state_hash = hashlib.sha256(
            json.dumps(state, sort_keys=True).encode()
        ).hexdigest()[:16]
        if state_hash != receipt["state_hash"]:
            excluded.append(
                {
                    "receipt": receipt["receipt_id"],
                    "reason": "saved state hash does not match the current fixture",
                    "savedStateHash": receipt["state_hash"],
                    "reconstructedStateHash": state_hash,
                }
            )
            continue
        primary = {"verdict": receipt["verdict"], "confidence": receipt["confidence"]}
        doubtful, reason = needs_escalation(primary, state)
        entry = {
            "fixture": receipt["fixture"],
            "stateHash": state_hash,
            "primary": primary,
            "primaryDoubtful": doubtful,
            "escalationReason": reason,
        }
        if not doubtful:
            entry.update(
                status="not-doubtful",
                applied=apply_verdict(dict(BASE_POSTURE), SimpleNamespace(**primary)),
            )
            results.append(entry)
            continue
        review_state = {
            **state,
            "governor_review": {"first_judgment": primary, "escalation_reason": reason},
        }
        try:
            second = ask_jev_choice(
                review_state, api_key=api_key, model=args.model, ledger=ledger
            )
        except BudgetExhausted:
            # A cap refusal is not a call failure: nothing was dispatched.
            # Stop the loop instead of recording the remaining cases as failures.
            entry.update(status="budget-refused")
            results.append(entry)
            break
        except Exception as cause:  # noqa: BLE001 - record the failure honestly
            entry.update(status="call-failed", error=type(cause).__name__)
            results.append(entry)
            continue
        still_doubtful, second_reason = needs_escalation(second, state)
        # Record the RUNNER's actual outcome, not the raw mapping: an unresolved
        # review retains the current posture (run_segment returns dict(posture)).
        would_map_to = apply_verdict(dict(BASE_POSTURE), SimpleNamespace(**second))
        applied = dict(BASE_POSTURE) if still_doubtful else would_map_to
        entry.update(
            second={
                "verdict": second["verdict"],
                "confidence": second["confidence"],
                "model": second.get("model"),
            },
            secondStillDoubtful=still_doubtful,
            secondReason=second_reason,
            status="unresolved" if still_doubtful else "resolved",
            applied=applied,
            wouldMapTo=would_map_to,
            trendConsistent=trend_consistent(applied, state),
        )
        results.append(entry)

    report = {
        "schemaVersion": "governor-second-opinion-qualification.v1",
        "executingModel": "opencode/gpt-6.1-sol",
        "secondOpinionModel": args.model,
        "kind": "offline-recorded primary + live second opinion; deterministic grading",
        "budgetNote": args.budget_note,
        "maxCalls": args.max_calls,
        "callsUsed": ledger.calls,
        "doubtfulCases": sum(r.get("primaryDoubtful", False) for r in results),
        "resolved": sum(r.get("status") == "resolved" for r in results),
        "unresolved": sum(r.get("status") == "unresolved" for r in results),
        "callFailures": sum(r.get("status") == "call-failed" for r in results),
        "budgetRefused": sum(r.get("status") == "budget-refused" for r in results),
        "excluded": excluded,
        "results": results,
    }
    write_json(run_dir / "report.json", report)
    # Generate the human-readable summary FROM the JSON so the prose cannot drift
    # from the artifact (the defect a review caught in the hand-written report).
    summary_lines = [
        "# Governor second-opinion qualification",
        "",
        f"- Second-opinion model: `{report['secondOpinionModel']}`",
        f"- Budget note: {report['budgetNote']}",
        f"- Call cap: {report['maxCalls']} | calls used: {report['callsUsed']}",
        f"- Doubtful cases: {report['doubtfulCases']} | resolved: {report['resolved']}"
        f" | unresolved: {report['unresolved']} | call failures: {report['callFailures']}"
        f" | budget refusals: {report['budgetRefused']}",
        "",
        "| Fixture | Primary | Reason | Second | Second verdict | Outcome |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if not r.get("primaryDoubtful"):
            summary_lines.append(
                f"| {r['fixture']} | {r['primary']['verdict']} @{r['primary']['confidence']}"
                f" | (mapped cleanly) | - | - | applied |"
            )
            continue
        second = r.get("second")
        second_text = f"{second['verdict']} @{second['confidence']}" if second else "-"
        outcome = r.get("status", "-")
        summary_lines.append(
            f"| {r['fixture']} | {r['primary']['verdict']} @{r['primary']['confidence']}"
            f" | {r['escalationReason']} | {second_text} | {r.get('secondReason', '') or '-'}"
            f" | {outcome} |"
        )
    summary_lines.append("")
    summary_lines.append(
        "Generated from report.json in this directory; edit the script, not this file."
    )
    (run_dir / "summary.md").write_text(
        "\n".join(summary_lines) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "callsUsed",
                    "doubtfulCases",
                    "resolved",
                    "unresolved",
                    "callFailures",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
