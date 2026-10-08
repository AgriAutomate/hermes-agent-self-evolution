# SPDX-License-Identifier: AGPL-3.0-only
"""Run bounded code-evolution segments, preserving the upstream population.

Governance decisions affect sampling only. An empty trainable failure set
stops deterministically; candidate export is never product deployment.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from darwinian_evolver.evolve_problem_loop import EvolveProblemLoop
from darwinian_evolver.learning_log_view import EmptyLearningLogView
from darwinian_evolver.problem import Mutator

from evolution.code.request_ledger import BudgetExhausted, RequestLedger, write_json
from evolution.code.sampling_governor import run_segment


class _FinishDispatchedChildren(Mutator):
    """Budget refusal ends dispatching, not evaluation of successful siblings."""

    def __init__(self, inner):
        super().__init__()
        self.inner = inner
        self.exhausted = False

    @property
    def supports_batch_mutation(self):
        return self.inner.supports_batch_mutation

    def set_context(self, context):
        super().set_context(context)
        self.inner.set_context(context)

    def mutate(self, organism, failure_cases, learning_log_entries):
        if self.exhausted:
            return []
        try:
            return self.inner.mutate(organism, failure_cases, learning_log_entries)
        except BudgetExhausted:
            self.exhausted = True
            return []


def _fingerprint(organism) -> str:
    data = getattr(organism, "file_contents", None)
    if data is None:
        data = organism.model_dump(
            exclude={
                "id",
                "parent",
                "additional_parents",
                "from_failure_cases",
                "from_learning_log_entries",
                "from_change_summary",
            }
        )
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def run_governed(
    problem,
    directory: Path,
    ledger: RequestLedger,
    *,
    judge=None,
    iterations: int = 3,
    segment_iterations: int = 5,
    parents: int = 1,
    mode: str = "baseline-or-live",
) -> dict:
    if any(
        isinstance(v, bool) or not isinstance(v, int) or v < 1
        for v in (iterations, segment_iterations, parents)
    ):
        raise ValueError(
            "iteration, segment and parent limits must be positive integers"
        )
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    initial = problem.initial_organism
    baseline = problem.evaluator.evaluate(initial)
    write_json(
        directory / "baseline.json",
        baseline.model_dump(serialize_as_any=True, mode="json"),
    )
    write_json(
        directory / "manifest.json",
        {
            "mode": mode,
            "source_sha": getattr(initial, "git_hash", None),
            "source_hash": _fingerprint(initial),
            "iterations_cap": iterations,
            "segment_iterations": segment_iterations,
            "parents": parents,
            "model_dispatch_cap": ledger.max_calls,
            "budget_note": ledger.budget_note,
            "author_model": "opencode/gpt-6.1-sol",
        },
    )
    best, best_result = initial, baseline
    rows = []
    decisions = []
    posture = {"sharpness": 10, "midpoint_score": "p75"}
    status = "iteration_limit"
    if not baseline.is_viable:
        status = "baseline_gate_failed"
    elif not baseline.trainable_failure_cases:
        status = "no_trainable_failures"
    else:
        mutators = [_FinishDispatchedChildren(m) for m in problem.mutators]
        loop = EvolveProblemLoop(
            problem=problem.model_copy(update={"mutators": mutators}),
            learning_log_view_type=(EmptyLearningLogView, {}),
            num_parents_per_iteration=parents,
            mutator_concurrency=1,
            evaluator_concurrency=1,
            sharpness=10,
            midpoint_score_percentile=75,
        )
        seen = {_fingerprint(initial)}
        completed = 0
        try:
            while completed < iterations:
                count = min(segment_iterations, iterations - completed)
                for snapshot in loop.run(count):
                    # run() emits iteration zero only on its first invocation.
                    best, best_result = max(
                        ((o, r) for o, r in loop.population.organisms if r.is_viable),
                        key=lambda pair: pair[1].score,
                    )
                    content = {_fingerprint(o) for o, _ in loop.population.organisms}
                    row = {
                        "iteration": snapshot.iteration,
                        "best_score": best_result.score,
                        "population_size": snapshot.population_size,
                        "distinct_children": len(content - seen),
                        "mutation_attempts": snapshot.evolver_stats.num_mutate_calls,
                        "observed_outcome": best_result.format_observed_outcome(
                            baseline
                        ),
                    }
                    seen |= content
                    rows.append(row)
                    write_json(
                        directory / "iterations" / f"{snapshot.iteration:04d}.json", row
                    )
                    path = directory / "snapshots" / f"{snapshot.iteration:04d}.pkl"
                    path.parent.mkdir(exist_ok=True)
                    with path.open("xb") as handle:
                        handle.write(snapshot.snapshot)
                    completed = snapshot.iteration
                    if any(m.exhausted for m in mutators):
                        status = "request_budget_exhausted"
                        break
                    if (
                        snapshot.iteration > 0
                        and not best_result.trainable_failure_cases
                    ):
                        break
                if status == "request_budget_exhausted":
                    break
                if not best_result.trainable_failure_cases:
                    status = "no_trainable_failures"
                    break
                if completed >= iterations:
                    break
                if judge is not None:
                    try:
                        next_posture = run_segment(
                            rows,
                            "Improve failing code cases while retaining all regression gates",
                            posture,
                            judge,
                        )
                        decision = {
                            "iteration": completed,
                            "before": posture,
                            "after": next_posture,
                            "error": None,
                        }
                    except BudgetExhausted:
                        raise
                    except Exception as cause:
                        next_posture = dict(posture)
                        decision = {
                            "iteration": completed,
                            "before": posture,
                            "after": next_posture,
                            "error": type(cause).__name__,
                        }
                    decisions.append(decision)
                    write_json(
                        directory / "decisions" / f"{completed:04d}.json", decision
                    )
                    if next_posture.get("stop"):
                        status = "governor_stop"
                        break
                    posture = next_posture
                    loop.population.set_sharpness(posture["sharpness"])
                    loop.population.set_midpoint_score_percentile(
                        float(posture["midpoint_score"][1:])
                    )
        except BudgetExhausted:
            status = "request_budget_exhausted"
    improved = best_result.is_viable and best_result.score > baseline.score
    if improved:
        write_json(
            directory / "candidate.json",
            best.model_dump(
                exclude={"parent", "additional_parents"},
                serialize_as_any=True,
                mode="json",
            ),
        )
    summary = {
        "status": status,
        "baseline_score": baseline.score,
        "best_score": best_result.score,
        "best_viable": best_result.is_viable,
        "improved": improved,
        "iterations_completed": rows[-1]["iteration"] if rows else 0,
        "model_dispatches": ledger.calls,
        "sampling_posture": posture,
        "governor_decisions": decisions,
        "product_files_written": 0,
        "promotion": "requires-independent-holdout-and-full-repository-checks",
    }
    write_json(directory / "summary.json", summary)
    return summary
