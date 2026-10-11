# SPDX-License-Identifier: AGPL-3.0-only
"""Offline integration against the real upstream loop, with synthetic organisms.

These controls establish runner behavior, not code quality or model accuracy.
They do not dispatch inference or qualify a product patch for release.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from darwinian_evolver.problem import (
    Organism,
    Evaluator,
    Mutator,
    EvaluationResult,
    EvaluationFailureCase,
    Problem,
)

from evolution.code.governed_runner import run_governed
from evolution.code.request_ledger import BudgetExhausted, RequestLedger, write_json


class CounterOrganism(Organism):
    value: int = 0


CounterOrganism.model_rebuild()


class CounterEvaluator(Evaluator):
    def evaluate(self, organism):
        return EvaluationResult(
            score=organism.value / 10,
            is_viable=True,
            trainable_failure_cases=[]
            if organism.value == 10
            else [EvaluationFailureCase(data_point_id="synthetic")],
        )


class CounterMutator(Mutator):
    def __init__(self, ceiling=9, budget_failure=False):
        super().__init__()
        self.calls = 0
        self.observed_postures = []
        self.ceiling = ceiling
        self.budget_failure = budget_failure

    def mutate(self, organism, failure_cases, learning_log_entries):
        if self.budget_failure:
            raise BudgetExhausted("synthetic exhausted budget")
        self.calls += 1
        self.observed_postures.append(
            (
                self._context.population._sharpness,
                self._context.population._midpoint_score_percentile,
            )
        )
        return [
            CounterOrganism(
                value=min(self.calls, self.ceiling),
                parent=organism,
                from_change_summary="synthetic control",
            )
        ]


def problem(initial=0, **kwargs):
    mutator = CounterMutator(**kwargs)
    return Problem[CounterOrganism, EvaluationResult, EvaluationFailureCase](
        initial_organism=CounterOrganism(value=initial),
        evaluator=CounterEvaluator(),
        mutators=[mutator],
    ), mutator


def run(tmp_path, p, **kwargs):
    directory = tmp_path / f"run-{uuid4()}"
    result = run_governed(
        p,
        directory,
        RequestLedger(directory / "requests"),
        mode="offline-test",
        **kwargs,
    )
    return result, directory


def test_all_passing_baseline_skips_judge_and_mutator(tmp_path):
    p, mutator = problem(initial=10)

    def judge(_):
        raise AssertionError("all-passing baseline must never ask a model")

    summary, directory = run(tmp_path, p, judge=judge)
    assert summary["status"] == "no_trainable_failures"
    assert (
        summary["iterations_completed"]
        == summary["model_dispatches"]
        == mutator.calls
        == 0
    )
    assert not (directory / "candidate.json").exists()


def test_population_continues_across_segments_and_posture_reaches_upstream_sampler(
    tmp_path,
):
    p, mutator = problem()
    states = []

    def judge(state):
        states.append(state)
        return {"verdict": "exploit", "confidence": 0.9}

    summary, directory = run(
        tmp_path, p, iterations=3, segment_iterations=1, judge=judge
    )
    assert summary["iterations_completed"] == mutator.calls == 3
    assert mutator.observed_postures == [(10, 75), (20, 90), (20, 90)]
    assert [s["evolution"]["population_size_last"] for s in states] == [2, 3]
    assert summary["best_score"] == 0.3 and summary["improved"]
    assert len(list((directory / "iterations").glob("*.json"))) == 4
    assert summary["product_files_written"] == 0


def test_stop_prevents_next_segment(tmp_path):
    p, mutator = problem()
    summary, _ = run(
        tmp_path,
        p,
        iterations=5,
        segment_iterations=1,
        judge=lambda _: {"verdict": "stop", "confidence": 0.9},
    )
    assert summary["status"] == "governor_stop" and mutator.calls == 1


def test_failed_judge_holds_and_records_error(tmp_path):
    p, mutator = problem()

    def judge(_):
        raise ValueError("synthetic invalid reply")

    summary, _ = run(tmp_path, p, iterations=2, segment_iterations=1, judge=judge)
    assert mutator.observed_postures == [(10, 75), (10, 75)]
    assert summary["governor_decisions"][0]["error"] == "ValueError"


def test_doubtful_primary_is_not_applied_to_the_upstream_sampler(tmp_path):
    p, mutator = problem()
    summary, directory = run(
        tmp_path,
        p,
        iterations=2,
        segment_iterations=1,
        judge=lambda _: {"verdict": "explore", "confidence": 0.9},
    )
    assert mutator.observed_postures == [(10, 75), (10, 75)]
    decision = summary["governor_decisions"][0]
    assert decision["escalation_required"]
    assert decision["escalation_reason"] == "explore-while-improving"
    assert decision["resolution"] == "unavailable"
    assert json.loads((directory / "decisions/0001.json").read_text()) == decision


def test_second_opinion_changes_the_real_sampler_and_records_both_models(tmp_path):
    p, mutator = problem()
    reviews = []

    def review(state):
        reviews.append(state)
        return {"verdict": "exploit", "confidence": 0.9, "model": "fixture-reviewer"}

    summary, _ = run(
        tmp_path,
        p,
        iterations=2,
        segment_iterations=1,
        judge=lambda _: {
            "verdict": "explore",
            "confidence": 0.9,
            "model": "fixture-primary",
        },
        escalation_judge=review,
    )
    assert mutator.observed_postures == [(10, 75), (20, 90)]
    assert len(reviews) == 1
    assert (
        reviews[0]["governor_review"]["escalation_reason"] == "explore-while-improving"
    )
    decision = summary["governor_decisions"][0]
    assert decision["primary"]["model"] == "fixture-primary"
    assert decision["secondary"]["model"] == "fixture-reviewer"
    assert decision["resolution"] == "secondary"


def test_second_opinion_uses_the_same_request_cap_and_refusal_is_recorded(
    tmp_path, monkeypatch
):
    import io

    requests = []

    class Response(io.BytesIO):
        status = 200

    def transport(req, **kwargs):
        requests.append(req)
        return Response(b'{"verdict":"explore","confidence":0.9}')

    monkeypatch.setattr("urllib.request.urlopen", transport)
    directory = tmp_path / "budgeted-review"
    ledger = RequestLedger(directory / "requests", 1, "offline HTTP fixture")
    p, mutator = problem()

    def primary(state):
        return ledger.post_json(
            "https://example.invalid",
            {"model": "fixture", "state": state},
            "unit-secret",
        )

    def secondary(state):
        return ledger.post_json(
            "https://example.invalid",
            {"model": "fixture-reviewer", "state": state},
            "unit-secret",
        )

    summary = run_governed(
        p,
        directory,
        ledger,
        iterations=3,
        segment_iterations=1,
        judge=primary,
        escalation_judge=secondary,
        mode="offline-test",
    )
    assert summary["status"] == "request_budget_exhausted"
    assert mutator.calls == ledger.calls == len(requests) == 1
    decision = summary["governor_decisions"][0]
    assert decision["escalation_attempted"] and decision["error"] == "BudgetExhausted"
    assert decision["after"] == decision["before"]
    assert json.loads((directory / "decisions/0001.json").read_text()) == decision


@pytest.mark.parametrize(
    "primary,secondary,sharpness,percentile",
    [
        ("exploit", None, 20, 90),
        ("explore", "exploit", 20, 90),
        ("explore", None, 10, 75),
    ],
)
def test_admitted_posture_changes_actual_parent_sampling_weights(
    tmp_path, monkeypatch, primary, secondary, sharpness, percentile
):
    import math

    draws = []

    def draw(population, weights, k):
        if isinstance(population[0], tuple) and isinstance(
            population[0][0], CounterOrganism
        ):
            draws.append(list(weights))
        return [population[0]] * k

    monkeypatch.setattr("darwinian_evolver.population.random.choices", draw)
    p, _ = problem()
    run(
        tmp_path,
        p,
        iterations=2,
        segment_iterations=1,
        judge=lambda _: {"verdict": primary, "confidence": 0.9},
        escalation_judge=(lambda _: {"verdict": secondary, "confidence": 0.9})
        if secondary
        else None,
    )
    # At the next draw the scores are [0, 0.1], and their child counts [1, 0].
    # Compute the independent sigmoid/novelty formula, rather than inspecting
    # the sampler's configured attributes or calling its implementation.
    midpoint = 0.1 * percentile / 100
    expected = [
        1 / (2 * (1 + math.exp(sharpness * midpoint))),
        1 / (1 + math.exp(-sharpness * (0.1 - midpoint))),
    ]
    assert len(draws) == 2
    assert draws[1] == pytest.approx(expected)


@pytest.mark.parametrize("exception", [TimeoutError, ValueError])
def test_failed_secondary_retains_a_previously_admitted_posture(tmp_path, exception):
    primary = iter(["exploit", "explore"])

    def review(_):
        raise exception("offline secondary failure")

    p, mutator = problem()
    summary, directory = run(
        tmp_path,
        p,
        iterations=3,
        segment_iterations=1,
        judge=lambda _: {"verdict": next(primary), "confidence": 0.9},
        escalation_judge=review,
    )
    assert mutator.observed_postures == [(10, 75), (20, 90), (20, 90)]
    decision = summary["governor_decisions"][1]
    assert decision["after"] == decision["before"]
    assert decision["resolution"] == "secondary_error"
    assert decision["error"] == exception.__name__
    assert decision["primary"]["verdict"] == "explore"
    assert json.loads((directory / "decisions/0002.json").read_text()) == decision


@pytest.mark.parametrize(
    "cap,failed_secondary", [(1, False), (2, False), (3, False), (3, True)]
)
def test_mutation_and_both_judges_share_the_exact_dispatch_cap(
    tmp_path, monkeypatch, cap, failed_secondary
):
    import io

    dispatched = []

    class Response(io.BytesIO):
        status = 200

    def transport(request, **kwargs):
        model = json.loads(request.data)["model"]
        dispatched.append(model)
        if model == "fixture-reviewer" and failed_secondary:
            raise TimeoutError("offline secondary timeout")
        return Response(b'{"verdict":"exploit","confidence":0.9}')

    monkeypatch.setattr("urllib.request.urlopen", transport)
    directory = tmp_path / "combined-budget"
    ledger = RequestLedger(
        directory / "requests", cap, "offline combined dispatch fixture"
    )

    class LedgerMutator(CounterMutator):
        def mutate(self, organism, failure_cases, entries):
            ledger.post_json(
                "https://example.invalid", {"model": "fixture-mutator"}, "unit-secret"
            )
            return super().mutate(organism, failure_cases, entries)

    mutator = LedgerMutator()
    p = Problem[CounterOrganism, EvaluationResult, EvaluationFailureCase](
        initial_organism=CounterOrganism(),
        evaluator=CounterEvaluator(),
        mutators=[mutator],
    )

    def primary(_):
        ledger.post_json(
            "https://example.invalid", {"model": "fixture-primary"}, "unit-secret"
        )
        return {"verdict": "explore", "confidence": 0.9}

    def secondary(_):
        return ledger.post_json(
            "https://example.invalid", {"model": "fixture-reviewer"}, "unit-secret"
        )

    summary = run_governed(
        p,
        directory,
        ledger,
        iterations=2,
        segment_iterations=1,
        judge=primary,
        escalation_judge=secondary,
        mode="offline-test",
    )
    assert (
        dispatched == ["fixture-mutator", "fixture-primary", "fixture-reviewer"][:cap]
    )
    assert ledger.calls == summary["model_dispatches"] == cap
    assert mutator.calls == 1
    assert summary["status"] == "request_budget_exhausted"
    resolution = (
        "primary_error"
        if cap == 1
        else ("secondary_error" if cap == 2 or failed_secondary else "secondary")
    )
    assert summary["governor_decisions"][0]["resolution"] == resolution
    assert len(list((directory / "requests").glob("*-request.json"))) == cap
    assert len(list((directory / "requests").glob("*-response.json"))) == cap


def test_budget_exhaustion_stops_without_exporting_a_candidate(tmp_path):
    p, mutator = problem(budget_failure=True)
    summary, directory = run(tmp_path, p)
    assert summary["status"] == "request_budget_exhausted"
    assert mutator.calls == 0 and not summary["improved"]
    assert not (directory / "candidate.json").exists()


def test_budget_refusal_keeps_successful_sibling_mutation(tmp_path):
    class OneChild(CounterMutator):
        def mutate(self, organism, cases, entries):
            if self.calls:
                raise BudgetExhausted("offline refusal after first child")
            return super().mutate(organism, cases, entries)

    mutator = OneChild()
    p = Problem[CounterOrganism, EvaluationResult, EvaluationFailureCase](
        initial_organism=CounterOrganism(),
        evaluator=CounterEvaluator(),
        mutators=[mutator],
    )
    summary, directory = run(tmp_path, p, parents=2, iterations=1)
    assert mutator.calls == 1
    assert summary["status"] == "request_budget_exhausted"
    assert summary["improved"] and summary["best_score"] == 0.1
    assert (directory / "candidate.json").exists()
    assert (
        summary["promotion"]
        == "requires-independent-holdout-and-full-repository-checks"
    )


def test_nonviable_candidate_cannot_win(tmp_path):
    p, _ = problem()

    class RejectingEvaluator(CounterEvaluator):
        def evaluate(self, organism):
            result = super().evaluate(organism)
            return (
                result
                if organism.value == 0
                else EvaluationResult(
                    score=1,
                    is_viable=False,
                    trainable_failure_cases=[
                        EvaluationFailureCase(data_point_id="gate")
                    ],
                )
            )

    p = Problem[CounterOrganism, EvaluationResult, EvaluationFailureCase](
        initial_organism=p.initial_organism,
        evaluator=RejectingEvaluator(),
        mutators=p.mutators,
    )
    summary, directory = run(tmp_path, p, iterations=1)
    assert not summary["improved"] and not (directory / "candidate.json").exists()


def test_receipts_and_run_reports_are_exclusive(tmp_path):
    path = tmp_path / "proof.json"
    write_json(path, {"value": "observed"})
    with pytest.raises(FileExistsError):
        write_json(path, {"value": "overwritten"})
    assert json.loads(path.read_text(encoding="utf-8"))["value"] == "observed"


def test_dispatch_cap_and_failed_request_are_counted(tmp_path, monkeypatch):
    calls = []

    def fail(req, **kwargs):
        calls.append(req)
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    ledger = RequestLedger(
        tmp_path, max_calls=1, budget_note="offline transport control"
    )
    with pytest.raises(TimeoutError):
        ledger.post_json(
            "https://example.invalid", {"model": "synthetic"}, "unit-secret"
        )
    with pytest.raises(BudgetExhausted):
        ledger.post_json(
            "https://example.invalid", {"model": "synthetic"}, "unit-secret"
        )
    assert len(calls) == ledger.calls == 1
    receipts = [
        json.loads(f.read_text(encoding="utf-8"))
        for f in tmp_path.glob("*-response.json")
    ]
    assert receipts[0]["error"] == "TimeoutError"
    assert "unit-secret" not in "".join(
        f.read_text(encoding="utf-8") for f in tmp_path.glob("*.json")
    )


def test_oversized_body_is_refused_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: pytest.fail("must refuse locally")
    )
    ledger = RequestLedger(tmp_path, 1, "offline body-size control")
    with pytest.raises(ValueError, match="byte limit"):
        ledger.post_json(
            "https://example.invalid", {"state": "x" * 120_001}, "unit-secret"
        )
    assert ledger.calls == 0
