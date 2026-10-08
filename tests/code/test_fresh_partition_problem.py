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
    PartitionFailure,
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
    def test_overload_is_part_of_the_frozen_api(self):
        initial, evaluator, _ = make_problem("stub")
        source = initial.file_contents[TARGET_FILE]
        changed = source.replace(
            "export function partitionEven(",
            "export function partitionEven(ring: Ring, count: 1): Ring[];\nexport function partitionEven(",
            1,
        )
        assert changed != source
        result = evaluator.evaluate(
            initial.model_copy(update={"file_contents": {TARGET_FILE: changed}})
        )
        assert not result.is_viable
        assert result.trainable_failure_cases[0].data_point_id == "frozen_signatures"

    def test_child_does_not_inherit_prior_generation_failures(self):
        initial, _, _ = make_problem("stub")
        parent = initial.model_copy(
            update={
                "from_failure_cases": [
                    PartitionFailure(data_point_id="old", actual="old generation")
                ]
            }
        )

        class Reply:
            def post_json(self, *args, **kwargs):
                return {
                    "model": "offline-control",
                    "choices": [
                        {
                            "message": {
                                "content": "```typescript\n"
                                + parent.file_contents[TARGET_FILE]
                                + "\n// offline change\n```"
                            }
                        }
                    ],
                }

        child = ZenMutator("stub", ledger=Reply()).mutate(
            parent, [PartitionFailure(data_point_id="new", actual="new generation")]
        )[0]
        assert child.from_failure_cases is None
        assert child.from_learning_log_entries is None
        assert child.additional_parents == []

    def test_mutator_refuses_signature_changing_content(self):
        initial, _, _ = make_problem("stub")

        class Reply:
            def post_json(self, *args, **kwargs):
                return {
                    "model": "offline-control",
                    "choices": [
                        {"message": {"content": "```typescript\n// no exports\n```"}}
                    ],
                }

        mutator = ZenMutator("stub-key", ledger=Reply())
        failure = PartitionFailure(
            data_point_id="control", actual="reproduced export deletion"
        )
        assert mutator.mutate(initial, [failure]) == []

    def test_mutation_keeps_diagnostics_and_allocates_a_fresh_id(self):
        initial, _, _ = make_problem("stub")
        captured = []

        class Reply:
            def post_json(self, endpoint, payload, *args, **kwargs):
                captured.append(payload)
                code = (
                    initial.file_contents[TARGET_FILE]
                    + "\n// offline mutation control\n"
                )
                return {
                    "model": "offline-control",
                    "choices": [
                        {"message": {"content": f"```typescript\n{code}\n```"}}
                    ],
                }

        mutator = ZenMutator("stub-key", ledger=Reply())
        children = mutator.mutate(
            initial,
            [
                PartitionFailure(
                    data_point_id="control", actual="diagnostic to preserve"
                )
            ],
        )
        assert children[0].id != initial.id
        assert children[0].parent is initial
        assert "diagnostic to preserve" in captured[0]["messages"][1]["content"]

    def test_signature_change_is_rejected_even_with_all_export_names(self):
        initial, evaluator, _ = make_problem("stub")
        source = initial.file_contents[TARGET_FILE]
        changed = source.replace("count: number", "count: string")
        assert changed != source
        candidate = initial.model_copy(update={"file_contents": {TARGET_FILE: changed}})
        result = evaluator.evaluate(candidate)
        assert not result.is_viable and result.score == 0
        assert result.trainable_failure_cases[0].data_point_id == "frozen_signatures"
        assert "signatures_match" in result.trainable_failure_cases[0].actual

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
