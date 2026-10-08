"""HTTP boundary controls for structured state and complete Choice evidence."""

import json
from types import SimpleNamespace

import pytest

from evolution.code.sampling_governor import ask_jev_choice, apply_verdict, build_state


def answer():
    return {
        "model": "jev-response-control",
        "usage": {"input_tokens": 10, "output_tokens": 4},
        "answers": {
            "posture": {
                "type": "choice",
                "choice": "explore",
                "confidence": 0.9,
                "probabilities": {"explore": 1, "exploit": 0, "hold": 0, "stop": 0},
            }
        },
    }


def test_jev_state_is_structured_and_returned_model_is_preserved(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps(answer()).encode()

    def transport(req, **kwargs):
        requests.append(json.loads(req.data))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", transport)
    state = {"evolution": {"goal": "offline control"}}
    result = ask_jev_choice(state, api_key="unit-secret")
    assert requests[0]["state"] == state
    assert result["model"] == "jev-response-control"
    assert result["probabilities"]["explore"] == 1
    assert result["usage"]["input_tokens"] == 10


@pytest.mark.parametrize(
    "defect",
    [
        "missing_model",
        "partial_probabilities",
        "nonunit_distribution",
        "nan_confidence",
        "bad_choice",
    ],
)
def test_malformed_responses_never_change_posture(defect):
    response = answer()
    entry = response["answers"]["posture"]
    if defect == "missing_model":
        del response["model"]
    if defect == "partial_probabilities":
        del entry["probabilities"]["stop"]
    if defect == "nonunit_distribution":
        entry["probabilities"]["exploit"] = 0.5
    if defect == "nan_confidence":
        entry["confidence"] = float("nan")
    if defect == "bad_choice":
        entry["choice"] = "invented"

    class Reply:
        def post_json(self, *args):
            return response

    with pytest.raises(ValueError):
        ask_jev_choice({}, api_key="unit-secret", ledger=Reply())


@pytest.mark.parametrize(
    "confidence", [float("inf"), float("nan"), -0.1, 1.1, True, None]
)
def test_bad_confidence_holds(confidence):
    posture = {"sharpness": 10, "midpoint_score": "p75"}
    assert (
        apply_verdict(
            posture, SimpleNamespace(verdict="explore", confidence=confidence)
        )
        == posture
    )


def test_plateau_counts_consecutive_tail_not_disconnected_maxima():
    state = build_state(
        [
            {"iteration": i, "best_score": score}
            for i, score in enumerate([0.7, 0.8, 0.7, 0.8, 0.8])
        ],
        "offline control",
        {},
    )
    assert state["evolution"]["plateau_iterations"] == 2
