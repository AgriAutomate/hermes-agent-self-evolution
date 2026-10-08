"""Self-tests for the model-selection benchmark.

The graders are the measurement instrument, so these tests prove they
DISCRIMINATE: the planted failure must score 0.0 and the known correction
1.0. A grader that scores both the same way would rank models on noise.

Everything here is offline: no network, no candidate model, no credentials.
"""

from __future__ import annotations

import json

from evolution.bench.model_selection import (
    BUGFIX2_BUGGY,
    BUGFIX2_CORRECT,
    BUGFIX_BUGGY,
    BUGFIX_CORRECT,
    CANDIDATES,
    DEFECT_TRUTH,
    DENYLIST,
    EXTRACT_PROMPT,
    EXTRACT_TRUTH,
    PROVIDERS,
    TASKS,
    combined_prompt,
    extract_fence,
    grade_bugfix,
    grade_bugfix2,
    grade_extract,
    grade_review,
    parse_sections,
    score_sections,
    summarise,
)


class TestBugfixGrader:
    def test_buggy_source_scores_zero(self):
        assert grade_bugfix(f"```python\n{BUGFIX_BUGGY}```") == 0.0

    def test_correction_scores_one(self):
        assert grade_bugfix(f"```python\n{BUGFIX_CORRECT}```") == 1.0

    def test_unfenced_correction_still_scores_one(self):
        assert grade_bugfix(BUGFIX_CORRECT) == 1.0

    def test_prose_without_code_scores_zero(self):
        assert grade_bugfix("I would rename the function and add logging.") == 0.0

    def test_wrong_function_name_is_not_graded_as_the_fix(self):
        assert (
            grade_bugfix("```python\ndef helper(values):\n    return values\n```")
            == 0.0
        )

    def test_denied_capability_scores_zero_without_executing(self):
        answer = "```python\nimport subprocess\n\ndef normalise_percentages(values):\n    return values\n```"
        assert any(token in answer for token in DENYLIST)
        assert grade_bugfix(answer) == 0.0


class TestReviewGrader:
    def test_exact_set_scores_one(self):
        payload = json.dumps({"defects": sorted(DEFECT_TRUTH)})
        assert grade_review(payload) == 1.0

    def test_empty_detection_scores_zero(self):
        assert grade_review(json.dumps({"defects": []})) == 0.0

    def test_partial_detection_is_between_zero_and_one(self):
        payload = json.dumps(
            {"defects": ["mutable-default-argument", "off-by-one-loop-bound"]}
        )
        score = grade_review(payload)
        assert 0.0 < score < 1.0

    def test_labels_outside_the_checklist_are_ignored(self):
        payload = json.dumps({"defects": sorted(DEFECT_TRUTH | {"invented-label"})})
        assert grade_review(payload) == 1.0

    def test_unparseable_answer_scores_zero(self):
        assert grade_review("looks fine to me") == 0.0

    def test_fenced_json_is_accepted(self):
        payload = f"```json\n{json.dumps({'defects': sorted(DEFECT_TRUTH)})}\n```"
        assert grade_review(payload) == 1.0


class TestExtractGrader:
    def test_exact_record_scores_one(self):
        assert grade_extract(json.dumps(EXTRACT_TRUTH)) == 1.0

    def test_wrong_json_scores_zero(self):
        assert grade_extract("the record is Willow Bend") == 0.0

    def test_partial_record_scores_field_fraction(self):
        payload = dict(EXTRACT_TRUTH)
        payload["registered"] = "2024-12-03"  # the day-first trap
        payload["area_ha"] = 4.35  # the survey figure, not the registration
        score = grade_extract(json.dumps(payload))
        assert round(score, 4) == round(4 / 6, 4)

    def test_survey_figure_cannot_pass_as_registration_area(self):
        payload = dict(EXTRACT_TRUTH)
        payload["area_ha"] = 4.35
        assert grade_extract(json.dumps(payload)) < 1.0


class TestFenceExtraction:
    def test_fenced_python_is_pulled_out(self):
        assert extract_fence("text\n```python\nx = 1\n```\nmore") == "x = 1"

    def test_plain_text_passes_through(self):
        assert extract_fence("  json only  ") == "json only"


class TestCatalogue:
    def test_candidates_have_unique_ids(self):
        ids = [candidate["model"] for candidate in CANDIDATES]
        assert len(ids) == len(set(ids))

    def test_tasks_carry_their_own_grader(self):
        for task in TASKS:
            assert callable(task["grade"])
            assert task["max_tokens"] > 0

    def test_reasoning_headroom_is_not_a_trap(self):
        # Run 1 scored four models 0.0 purely because their token cap was
        # consumed by hidden reasoning (finish_reason=length, empty answer).
        # The caps must stay large enough that "ran out of budget" is the
        # model's fault, not the harness's.
        for task in TASKS:
            assert task["max_tokens"] >= 3000

    def test_fixture_prompt_requires_work_not_transcription(self):
        # The converted date is graded, and must not be handed over verbatim.
        assert EXTRACT_TRUTH["registered"] == "2024-03-12"
        assert EXTRACT_TRUTH["registered"] not in EXTRACT_PROMPT
        # Both competing area figures must appear, or the task has no trap.
        assert "4.2 ha" in EXTRACT_PROMPT and "4.35 ha" in EXTRACT_PROMPT


class TestRanking:
    def test_models_rank_by_score_then_latency(self):
        rows = [
            {"model": "b", "ok": True, "score": 0.5, "latency_s": 1.0},
            {"model": "a", "ok": True, "score": 1.0, "latency_s": 9.0},
            {"model": "c", "ok": False, "score": 0.0, "latency_s": 2.0},
        ]
        ranking = summarise(rows)
        assert [row["model"] for row in ranking] == ["a", "b", "c"]
        assert ranking[0]["mean_score"] == 1.0
        assert ranking[2]["failures"] == 1

    def test_truncation_and_retries_are_surfaced_not_hidden(self):
        rows = [
            {
                "model": "a",
                "ok": True,
                "score": 0.0,
                "latency_s": 1.0,
                "truncated": True,
                "attempts": 3,
            },
            {"model": "b", "ok": True, "score": 1.0, "latency_s": 2.0},
        ]
        by_model = {row["model"]: row for row in summarise(rows)}
        assert by_model["a"]["truncated"] == 1
        assert by_model["a"]["retried"] == 1
        assert by_model["b"]["truncated"] == 0
        assert by_model["b"]["retried"] == 0


def _perfect_combined() -> str:
    """A combined answer a perfect candidate would produce, built from the
    known-correct fixtures so the test cannot drift from the graders."""
    return (
        "=== SECTION: bugfix ===\n"
        f"```python\n{BUGFIX_CORRECT}```\n"
        "=== SECTION: review ===\n"
        f"{json.dumps({'defects': sorted(DEFECT_TRUTH)})}\n"
        "=== SECTION: extract ===\n"
        f"{json.dumps(EXTRACT_TRUTH)}\n"
    )


class TestCombinedSections:
    def test_perfect_combined_answer_scores_full_marks(self):
        scores = score_sections(_perfect_combined())
        assert scores == {"bugfix": 1.0, "review": 1.0, "extract": 1.0}

    def test_sections_parse_out_of_order(self):
        answer = (
            "=== SECTION: extract ===\n{}\n"
            "=== SECTION: bugfix ===\ncode\n"
            "=== SECTION: review ===\n{}\n"
        )
        sections = parse_sections(answer)
        assert set(sections) == {"bugfix", "review", "extract"}
        assert sections["bugfix"] == "code"

    def test_missing_section_scores_zero_not_an_exception(self):
        answer = "=== SECTION: bugfix ===\n```python\n" + BUGFIX_CORRECT + "```"
        scores = score_sections(answer)
        assert scores["bugfix"] == 1.0
        assert scores["review"] == 0.0
        assert scores["extract"] == 0.0

    def test_prose_around_markers_does_not_break_parsing(self):
        answer = (
            "Sure! Here are my answers.\n\n"
            + _perfect_combined()
            + "\nHope that helps."
        )
        assert score_sections(answer) == {"bugfix": 1.0, "review": 1.0, "extract": 1.0}

    def test_unknown_marker_names_are_kept_but_not_scored(self):
        answer = "=== SECTION: bonus ===\nextra\n" + _perfect_combined()
        assert "bonus" in parse_sections(answer)
        assert score_sections(answer) == {"bugfix": 1.0, "review": 1.0, "extract": 1.0}

    def test_combined_prompt_asks_for_every_task_with_markers(self):
        prompt = combined_prompt()
        for task in TASKS:
            assert f"=== SECTION: {task['name']} ===" in prompt
            assert task["prompt"] in prompt


class TestProviderRouting:
    def test_every_candidate_maps_to_a_configured_provider(self):
        for candidate in CANDIDATES:
            assert candidate["provider"] in PROVIDERS

    def test_provider_endpoints_use_https(self):
        for spec in PROVIDERS.values():
            assert spec["url"].startswith("https://")
            assert spec["key_env"].endswith("_API_KEY")


class TestTiebreakGrader:
    """The tiebreak exists because seven candidates tied at 1.0 on the main
    suite. It must therefore separate: full credit for the repair, partial
    credit for a partial repair, zero for noise."""

    def test_correction_scores_full(self):
        assert grade_bugfix2(f"```python\n{BUGFIX2_CORRECT}```") == 1.0

    def test_buggy_source_scores_partial_not_extremes(self):
        score = grade_bugfix2(f"```python\n{BUGFIX2_BUGGY}```")
        assert 0.0 < score < 1.0

    def test_irrelevant_answer_scores_zero(self):
        assert grade_bugfix2("looks fine to me") == 0.0

    def test_denied_capability_scores_zero(self):
        answer = "```python\nimport subprocess\n\ndef summarise_batches(b):\n    return b\n```"
        assert grade_bugfix2(answer) == 0.0

    def test_tiebreak_is_selectable_without_changing_the_default_suite(self):
        assert [task["name"] for task in TASKS] == ["bugfix", "review", "extract"]
        scores = score_sections(_perfect_combined())
        assert scores == {"bugfix": 1.0, "review": 1.0, "extract": 1.0}
