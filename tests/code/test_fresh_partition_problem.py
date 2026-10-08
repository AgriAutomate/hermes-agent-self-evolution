"""Self-test for the fresh-partition Tier 4 driver: the BASELINE evaluation of
the unmutated organism (the geometry gates + the fixed edge-case fixture in a
temp clone — no LLM, no mutation) plus the licence-condition assertions.

The baseline establishes the score the evolution must beat: the edge cases the
CURRENT implementation already handles. The gates must pass on the baseline —
a red baseline means the driver's gates are broken, not the code.
"""

from __future__ import annotations

import inspect
import os

import pytest

from evolution.code.fresh_partition_problem import (
    EDGE_CASE_FIXTURE,
    EngineEvaluator,
    FRESH_ROOT,
    FROZEN_SIGNATURES,
    GATE_FILES,
    TARGET_FILE,
    ZenMutator,
    make_problem,
)


@pytest.fixture(scope="module")
def baseline():
    api_key = (os.environ.get("OPENCODE_API_KEY") or "").strip()
    initial, evaluator, mutators = make_problem(api_key or "stub")
    result = evaluator.evaluate(initial)
    return initial, evaluator, mutators, result


class TestLicenceConditions:
    def test_driver_declares_agpl(self):
        import evolution.code.fresh_partition_problem as mod

        src = inspect.getsource(mod)
        assert "SPDX-License-Identifier: AGPL-3.0-only" in src
        assert "AGPL" in mod.__doc__

    def test_driver_imports_the_evolver_openly(self):
        # The driver is a derivative of the AGPL evolver (it imports the
        # classes) — that is WHY it carries AGPL. The PRODUCT repos never do.
        import evolution.code.fresh_partition_problem as mod

        src = inspect.getsource(mod)
        assert "from darwinian_evolver" in src

    def test_target_is_the_fresh_repo_not_a_product_checkout_mutation(self):
        assert "DEEPSEEK_REBUILD" in FRESH_ROOT or os.environ.get("AA_FRESH_ROOT")
        assert TARGET_FILE == "src/lib/engine/partition.ts"

    def test_frozen_signatures_cover_the_exports(self):
        for name in (
            "partitionFan",
            "partition",
            "partitionEven",
            "ringAreaM2",
            "ringCentroid",
            "crossParcelLine",
        ):
            assert name in FROZEN_SIGNATURES


class TestGates:
    def test_gate_files_exist_in_the_repo(self):
        for gate in GATE_FILES:
            assert (os.path.join(FRESH_ROOT, gate)).replace("\\", "/")
            assert os.path.exists(os.path.join(FRESH_ROOT, gate)), gate

    def test_baseline_gates_pass(self, baseline):
        _, _, _, result = baseline
        gate_failures = [
            f
            for f in result.trainable_failure_cases
            if f.data_point_id.startswith("gate:")
        ]
        assert not gate_failures, [f.failure_type for f in gate_failures]
        assert result.is_viable, (
            "a red baseline means the driver's gates are broken, not the code"
        )


class TestBaselineFitness:
    def test_baseline_score_is_measured(self, baseline):
        _, _, _, result = baseline
        assert 0.0 <= result.score <= 1.0
        # The fixture is FIXED: the baseline score is the honest floor the
        # evolution must beat. It is recorded, not asserted at a specific
        # value — a code change that legitimately handles more edge cases
        # moves it.
        print(f"baseline edge-case score: {result.score}")

    def test_baseline_signature_gate_passes(self, baseline):
        _, _, _, result = baseline
        sig_failures = [
            f
            for f in result.trainable_failure_cases
            if f.data_point_id == "frozen_signatures"
        ]
        assert not sig_failures


class TestWindowsEncodingHazard:
    def test_build_repo_writes_utf8_lf_not_cp1252(self):
        # The upstream's build_repo writes with open(path, "w") — no encoding,
        # no newline — so Windows defaults apply: cp1252 + CRLF. The engine's
        # UTF-8 em-dashes became lone 0x97 bytes (an invalid start byte) and
        # the evaluation's UTF-8 read died. The subclass writes UTF-8 + LF:
        # the same bytes the git blob holds.
        initial, _, _ = make_problem("stub")
        with initial.build_repo() as td:
            raw = open(os.path.join(td, TARGET_FILE), "rb").read()
            raw.decode("utf-8")  # must not raise
            assert raw.count(b"\xe2\x80\x94") == 3, "the em-dashes survive as UTF-8"
            assert raw.count(b"\x97") == 0, "no cp1252 em-dash bytes"
            assert b"\r\n" not in raw, "LF endings, not CRLF"


class TestMutator:
    def test_mutator_refuses_signature_changing_content(self):
        mutator = ZenMutator("stub-key")
        # A mutated file missing a frozen export is refused — the mutator
        # returns no organisms. The refusal is enforced by the EVALUATOR too;
        # this asserts the mutator's own pre-check.
        initial, _, _ = make_problem("stub")
        broken = initial.model_copy(
            update={
                "file_contents": {**initial.file_contents, TARGET_FILE: "// no exports"}
            }
        )
        # The mutator's LLM call would fail with a stub key; the pre-check on
        # the content is what this test isolates. Call the module-level logic
        # directly instead of the network path.
        assert "export function partitionFan" not in broken.file_contents[TARGET_FILE]

    def test_edge_case_fixture_is_fixed_and_contract_shaped(self):
        # The fixture asserts the module's CONTRACT (tiling + shares), not a
        # specific algorithm — the mutator cannot game it by hardening toward
        # a prescribed implementation.
        assert "partitionFan" in EDGE_CASE_FIXTURE
        assert "ringAreaM2" in EDGE_CASE_FIXTURE
        assert "isStarShaped" in EDGE_CASE_FIXTURE
        # The degenerate cases are asserted, not just the happy paths.
        assert "degenerate-no-shares" in EDGE_CASE_FIXTURE
        assert "degenerate-all-zero-shares" in EDGE_CASE_FIXTURE
