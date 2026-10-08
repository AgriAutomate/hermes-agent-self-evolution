#!/usr/bin/env python3
"""Measured model selection over the free catalogue (opencode / nvidia / xai).

WHY THIS EXISTS: the catalogue is too large to trial by hand (84 opencode,
57 nvidia, 13 xai entries; only a subset are free AND chat-capable), and the
Tier 4 pipeline needs a defensible answer to "which model is the mutator and
which is the reviewer". This module replaces preference with measurement.

METHOD (three stages, each one is a filter):

1. PROBE  -- one 1-token request per candidate. Records availability,
   round-trip latency, the model the PROVIDER says answered (never the alias we
   asked for), and the usage block. Unavailable candidates are eliminated with
   a receipt, not an opinion. Transient states (429/500/502/503/529, timeouts)
   are retried with backoff before they count as a failure: a rate limit is a
   property of the moment, not of the model.
2. SCREEN -- every surviving candidate runs the same three task-shaped
   prompts. Scores are computed by CODE, never by a judge model:
     * bugfix    -- returns corrected code that is EXECUTED against a fixed
                    assertion set (pass/fail, the exact standard the Tier 4
                    mutator is held to);
     * review    -- detects planted defects from a declared checklist, scored
                    as set F1;
     * extract   -- structured extraction from messy text against a fixed
                    schema, scored as correct fields / 6.
3. CONFIRM -- (a later run) the top candidates repeat the full suite to check
   the ranking is stable rather than one lucky sample.

TWO ROUTES, ONE YARDSTICK

OpenCode free-tier models refuse API use ("free tier can only be used from
within OpenCode"), so they are trialled as real OpenCode agent sessions
(`subagent` with model provider/model) answering the COMBINED prompt -- all
three tasks in one session -- with the saved answer graded by exactly the
same graders through `--score-file`. The route changes the transport, never
the measurement. Session wall time includes agent overhead, so it is not
compared against API latency.

MEASUREMENT DEFECTS ALREADY FOUND AND FIXED -- do not reintroduce

- A tight max_tokens cap scored the harness, not the model: reasoning models
  spent the budget on hidden reasoning, returned finish_reason=length with an
  EMPTY answer, and were recorded 0.0. Four models were falsely ranked last
  for it. Caps are now generous and truncation is a recorded field.
- A spoofed browser User-Agent lived in this file while the real fix (an
  honest project UA) lived in request_ledger. The constant is gone.
- Transient 429/503 were counted as model failures (laguna-xs, glm-5.3-flash
  were eliminated on provider hiccups). They are retried with backoff now.

BOUNDARIES THIS FILE DOES NOT CROSS

- Every fixture is synthetic. No client, customer, product or credential data
  enters a prompt: free-tier endpoints are not confidential channels.
- Free means $0 per token in the catalogue. It does NOT mean unrestricted:
  some free models refuse API use entirely (they are OpenCode-session-only),
  and some routed models require account funds (402).
- Execution of candidate code is the grading signal, so it runs in a temp
  directory with a timeout and an import/IO denylist. That is a guardrail
  against accidents, NOT a security sandbox; only low-risk fixtures belong
  here.
- The benchmark selects a model for a TASK. It does not license sending
  confidential data to the winner, and it is not evidence that a winner's
  patch is correct (that still needs holdout + full repository checks).

Budget line: the founder's "keep advancing" (2026-10-08) continued as the
explicit instruction to find a measured way to pick models. Every dispatch is
a RequestLedger receipt.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error

from evolution.code.request_ledger import BudgetExhausted, RequestLedger

ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# NOTE on the User-Agent: this file deliberately does NOT set one. The request
# ledger owns the header and sends an honest project identity
# (request_ledger.USER_AGENT). An earlier draft of this file carried a spoofed
# browser UA; Cloudflare error 1010 was solved with an honest UA, not a fake
# one, and the dead constant was removed so it cannot be picked up again.

# Each provider: where chat completions go and where the key comes from.
PROVIDERS: dict[str, dict] = {
    "opencode": {"url": ZEN_URL, "key_env": "OPENCODE_API_KEY"},
    "nvidia": {"url": NVIDIA_URL, "key_env": "NVIDIA_API_KEY"},
}

# The catalogue as of 2026-10-08, filtered to chat-capable entries priced at
# zero. xai lists 13 models but only grok-imagine image/video variants, so it
# contributes NO free text model: recorded here so the gap is a measured fact
# rather than something we re-derive every run.
#
# nvidia ids are the API's own model ids (vendor/model), taken from the
# catalogue's zero-cost chat entries. Not every catalogue entry is reachable
# from the API and not every API entry is chat-capable -- the probe decides,
# we do not guess. llama-3.1-nemotron-ultra-253b-v1 appears on the endpoint but
# carries no price in the catalogue, so it is deliberately NOT probed: unknown
# price is not the same as free.
CANDIDATES: list[dict] = [
    {"model": "space-bunny-free", "provider": "opencode", "family": "free"},
    {"model": "exo-free", "provider": "opencode", "family": "free"},
    {"model": "fledge-alpha-free", "provider": "opencode", "family": "free"},
    {"model": "ling-3.1-flash-free", "provider": "opencode", "family": "free"},
    {"model": "ling-3.0-flash-fin-free", "provider": "opencode", "family": "free"},
    {"model": "longcat-2.5-preview-free", "provider": "opencode", "family": "free"},
    {"model": "mimo-v2.6-flash-free", "provider": "opencode", "family": "free"},
    {
        "model": "muse-spark-1.3-contributor-free",
        "provider": "opencode",
        "family": "free",
    },
    {"model": "nemotron-3.5-lightning-free", "provider": "opencode", "family": "free"},
    {"model": "nemotron-3-ultra-free", "provider": "opencode", "family": "free"},
    {"model": "big-pickle", "provider": "opencode", "family": "session-only"},
    {
        "model": "deepseek-ai/deepseek-v4.1-flash",
        "provider": "nvidia",
        "family": "free",
    },
    {"model": "z-ai/glm-5.3-flash", "provider": "nvidia", "family": "free"},
    {"model": "z-ai/glm-5.3", "provider": "nvidia", "family": "free"},
    {"model": "moonshotai/kimi-k3", "provider": "nvidia", "family": "free"},
    {"model": "openai/gpt-oss-20b", "provider": "nvidia", "family": "free"},
    {
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "provider": "nvidia",
        "family": "free",
    },
    {"model": "meta/muse-glimmer-30b", "provider": "nvidia", "family": "free"},
    {"model": "poolside/laguna-xs-2.1", "provider": "nvidia", "family": "free"},
    {"model": "mistralai/magistral-small-2506", "provider": "nvidia", "family": "free"},
    {
        "model": "mistralai/mistral-medium-3-instruct",
        "provider": "nvidia",
        "family": "free",
    },
    {
        "model": "mistralai/mistral-7b-instruct-v0.3",
        "provider": "nvidia",
        "family": "free",
    },
    {"model": "meta/llama-guard-4-12b", "provider": "nvidia", "family": "free"},
    {
        "model": "google/diffusiongemma-26b-a4b-it",
        "provider": "nvidia",
        "family": "free",
    },
]
# xai: no free text/chat model exists in the catalogue (grok-4.7 is paid).

# ---------------------------------------------------------------------------
# Fixtures (synthetic, fixed, and known to discriminate: the tests prove the
# graders return 0.0 for the planted failure and 1.0 for the correction).
# ---------------------------------------------------------------------------

BUGFIX_BUGGY = '''def normalise_percentages(values):
    """Scale values so they sum to 100.0, rounded to 2 decimals.

    Contract:
      normalise_percentages([]) == []
      normalise_percentages([0, 0, 0]) == [0.0, 0.0, 0.0]
      normalise_percentages([1, 3]) == [25.0, 75.0]
      sum(normalise_percentages([1, 1, 1])) == 100.0 (within 1e-9)
    """
    total = sum(values)
    result = []
    for value in values:
        result.append(round(value / total * 100, 2))
    return result
'''

BUGFIX_CORRECT = '''def normalise_percentages(values):
    """Scale values so they sum to 100.0, rounded to 2 decimals."""
    total = sum(values)
    if not values or total == 0:
        return [0.0 for _ in values]
    scaled = [round(value / total * 100, 2) for value in values]
    scaled[-1] = round(scaled[-1] + (100.0 - sum(scaled)), 2)
    return scaled
'''

BUGFIX_ASSERTS = """
assert normalise_percentages([]) == []
assert normalise_percentages([0, 0, 0]) == [0.0, 0.0, 0.0]
assert normalise_percentages([1, 3]) == [25.0, 75.0]
assert abs(sum(normalise_percentages([1, 1, 1])) - 100.0) < 1e-9
assert abs(sum(normalise_percentages([7, 7, 7, 7, 7])) - 100.0) < 1e-9
assert abs(sum(normalise_percentages([0.1, 0.2, 0.3])) - 100.0) < 1e-9
print("ALL_ASSERTIONS_PASSED")
"""

BUGFIX_PROMPT = f"""A Python function fails its contract. Here is the current source:

```python
{BUGFIX_BUGGY}
```

Two things are wrong with it: one input shape raises instead of returning, and
the rounded results do not add up to 100.0.

Return ONLY a single ```python fenced block containing the complete corrected
function. Keep the name `normalise_percentages` and its signature. Do not add
imports, do not read or write files, do not print anything."""

# --- Tiebreak fixture -------------------------------------------------------
# Run 1 showed the basic suite has a ceiling: seven candidates scored 1.0, so
# "which is best" could not be answered from that alone. This fixture carries
# five independent defects and is graded PER ASSERTION, so partial repairs earn
# partial credit and the tie breaks on measured difference, not on taste.
BUGFIX2_BUGGY = '''def summarise_batches(batches):
    """Aggregate numeric batches, skipping poisoned ones.

    Contract:
      summarise_batches([]) == (0, 0.0, None)
      summarise_batches([[], []]) == (0, 0.0, None)
      summarise_batches([[1, 2], [3]]) == (6, 2.0, 3)
      summarise_batches([[1, None], [2]]) == (2, 2.0, 2)
      summarise_batches([["a"], [2.5]]) == (2.5, 2.5, 2.5)
      summarise_batches([[0.1, 0.2]]) == (0.3, 0.15, 0.2)
      summarise_batches([[-1, -2]]) == (-3, -1.5, -1)
      summarise_batches("nope") raises TypeError
    """
    total = 0
    count = 0
    highest = 0
    for batch in batches:
        for item in batch:
            total = total + item
            count = count + 1
            if item > highest:
                highest = item
    return round(total, 2), round(total / count, 2), highest
'''

BUGFIX2_CORRECT = '''def summarise_batches(batches):
    """Aggregate numeric batches, skipping poisoned ones. See contract."""
    if not isinstance(batches, list):
        raise TypeError("batches must be a list")
    numbers = []
    for batch in batches:
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in batch):
            continue
        numbers.extend(batch)
    if not numbers:
        return (0, 0.0, None)
    total = round(sum(numbers), 3)
    mean = round(total / len(numbers), 3)
    highest = round(max(numbers), 3)
    return (total, mean, highest)
'''

# One assertion per defect class; each is graded independently so a candidate
# that fixes four of five defects scores 4/5, not 0.
BUGFIX2_CHECKS = [
    "assert summarise_batches([]) == (0, 0.0, None)",
    "assert summarise_batches([[], []]) == (0, 0.0, None)",
    "assert summarise_batches([[1, 2], [3]]) == (6, 2.0, 3)",
    "assert summarise_batches([[1, None], [2]]) == (2, 2.0, 2)",
    'assert summarise_batches([["a"], [2.5]]) == (2.5, 2.5, 2.5)',
    "assert summarise_batches([[0.1, 0.2]]) == (0.3, 0.15, 0.2)",
    "assert summarise_batches([[-1, -2]]) == (-3, -1.5, -1)",
    "try:\n    summarise_batches('nope')\n    raised = False\nexcept TypeError:\n    raised = True\nassert raised",
]

BUGFIX2_PROMPT = f"""A Python function violates its own documented contract. Current source:

```python
{BUGFIX2_BUGGY}
```

It mishandles several independent cases: missing input validation, poisoned
batches, wrong rounding precision, empty input, and the initial maximum.

Return ONLY a single ```python fenced block containing the complete corrected
function. Keep the name `summarise_batches` and its signature. Do not add
imports, do not read or write files, do not print anything."""

DEFECT_SNIPPET = """def load_sites(path, cache={}):
    if path == None:
        return []
    handle = open(path)
    data = handle.read()
    cache[path] = data
    rows = [line for line in data.split("\\n") if line != ""]
    count = len(rows)
    while count > 0:
        count = count - 1
    return [row.strip() for row in rows]
"""

# Exactly four of the six declared labels are true. The model never sees which.
DEFECT_CHECKLIST = [
    "mutable-default-argument",
    "file-handle-not-closed",
    "loose-none-comparison",
    "dead-loop-unused-counter",
    "off-by-one-loop-bound",
    "missing-recursion-guard",
]
DEFECT_TRUTH = {
    "mutable-default-argument",
    "file-handle-not-closed",
    "loose-none-comparison",
    "dead-loop-unused-counter",
}

DEFECT_PROMPT = f"""Review this Python function:

```python
{DEFECT_SNIPPET}
```

Some of the labels below are genuine defects in it and some are not.

Labels: {", ".join(DEFECT_CHECKLIST)}

Respond with ONLY a JSON object of the form {{"defects": ["label", ...]}}
listing exactly the labels that are genuinely present. Use only labels from
the list. No prose, no markdown fence."""

EXTRACT_RAW = """SITE REGISTRATION EXTRACT - do not edit manually
Site .........: Willow Bend (SA5-0431)
Area .........: 4.2 ha (includes 0.3 ha dam)
Registered .... 12/03/2024
Status ........ active
Zone .......... residential-smallholder
Renewal ....... 2026-07-01
Operator note: the survey measured 4.35 ha but the registration area governs.
"""

EXTRACT_PROMPT = f"""Extract the fields from this record:

```
{EXTRACT_RAW}
```

Return ONLY a JSON object with exactly these keys:
- "site_id": the bracketed registration code as a string
- "area_ha": the REGISTRATION area as a JSON number (not the survey figure)
- "registered": date as "YYYY-MM-DD" (the record is day-first)
- "status": one of "active" or "lapsed"
- "zone": the zone string
- "renewal": date as "YYYY-MM-DD"

No prose, no markdown fence."""

EXTRACT_TRUTH = {
    "site_id": "SA5-0431",
    "area_ha": 4.2,
    "registered": "2024-03-12",
    "status": "active",
    "zone": "residential-smallholder",
    "renewal": "2026-07-01",
}

# The correction is a pure numeric/string function; anything reaching for the
# filesystem, the network or the interpreter is outside the contract and is
# refused rather than executed.
DENYLIST = (
    "import socket",
    "import urllib",
    "import subprocess",
    "import shutil",
    "import requests",
    "import ctypes",
    "import os",
    "os.system",
    "os.remove",
    "__import__",
    "eval(",
    "exec(",
    "open(",
)


def _temp_root() -> pathlib.Path:
    root = os.environ.get("AA_CODE_TEMP_ROOT") or "D:/dev/caches/temp/opencode"
    path = pathlib.Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_fence(text: str) -> str:
    """First fenced block if present, else the raw text (normalised)."""
    match = re.search(
        r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    return text.strip()


def _run_capture(script: str, timeout: int = 20) -> tuple[int, str, str]:
    """Execute a harness-built script in the temp root; (code, stdout, stderr)."""
    path = _temp_root() / f"bench-{os.getpid()}-{time.time_ns()}.py"
    path.write_text(script, encoding="utf-8", newline="\n")
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(path.parent),
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    finally:
        with_error = None
        try:
            path.unlink()
        except OSError as cause:  # pragma: no cover - temp cleanup only
            with_error = cause


def _run_assertions(source: str) -> tuple[bool, str]:
    code, _out, err = _run_capture(
        source
        + "\n\nif __name__ == '__main__':\n"
        + "\n".join("    " + line for line in BUGFIX_ASSERTS.strip().splitlines())
    )
    return code == 0, err[-600:]


def _run_checks(source: str, checks: list[str]) -> tuple[int, int, str]:
    """Run each check independently; returns (passed, total, error tail).

    Per-check isolation is what makes partial credit honest: a candidate that
    fixes four of five defects scores 4/5 instead of collapsing to zero.
    """
    lines = [source, "", "if __name__ == '__main__':", "    _results = []"]
    for index, check in enumerate(checks):
        lines.append(f"    def _check_{index}():")
        lines.extend("        " + line for line in check.splitlines())
        lines.extend(
            [
                f"    try:",
                f"        _check_{index}()",
                "        _results.append(1)",
                "    except BaseException:",
                "        _results.append(0)",
            ]
        )
    lines.append('    print("__CHECKS__", sum(_results), len(_results))')
    code, out, err = _run_capture("\n".join(lines) + "\n")
    match = re.search(r"__CHECKS__ (\d+) (\d+)", out)
    if not match:
        return 0, len(checks), (err or out or f"exit {code}")[-600:]
    return int(match.group(1)), int(match.group(2)), err[-600:]


def grade_bugfix(answer: str) -> float:
    """1.0 only when the returned code satisfies the fixed assertion set."""
    code = extract_fence(answer)
    if not code:
        return 0.0
    lowered = code.lower()
    if any(token in lowered for token in DENYLIST):
        return 0.0
    if "def normalise_percentages" not in code:
        return 0.0
    passed, _ = _run_assertions(code)
    return 1.0 if passed else 0.0


def grade_bugfix2(answer: str) -> float:
    """Tiebreak grader: fraction of independent contract checks passed."""
    code = extract_fence(answer)
    if not code:
        return 0.0
    lowered = code.lower()
    if any(token in lowered for token in DENYLIST):
        return 0.0
    if "def summarise_batches" not in code:
        return 0.0
    passed, total, _err = _run_checks(code, BUGFIX2_CHECKS)
    return round(passed / total, 4) if total else 0.0


def _answer_json(text: str):
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*\n(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if fence:
        stripped = fence.group(1).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in answer")
    return json.loads(stripped[start : end + 1])


def grade_review(answer: str) -> float:
    """Set F1 of the reported defect labels against the planted truth."""
    try:
        payload = _answer_json(answer)
        reported = payload.get("defects")
        if not isinstance(reported, list):
            return 0.0
        predicted = {str(item).strip() for item in reported}
    except (ValueError, TypeError, json.JSONDecodeError):
        return 0.0
    predicted &= set(DEFECT_CHECKLIST)
    if not predicted:
        return 0.0
    true_positives = len(predicted & DEFECT_TRUTH)
    precision = true_positives / len(predicted)
    recall = true_positives / len(DEFECT_TRUTH)
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def grade_extract(answer: str) -> float:
    """Fraction of schema fields whose values are exactly right."""
    try:
        payload = _answer_json(answer)
    except (ValueError, TypeError, json.JSONDecodeError):
        return 0.0
    if not isinstance(payload, dict):
        return 0.0
    correct = 0
    for key, expected in EXTRACT_TRUTH.items():
        value = payload.get(key)
        if isinstance(expected, float):
            try:
                if abs(float(value) - expected) < 1e-9:
                    correct += 1
            except (TypeError, ValueError):
                pass
        elif isinstance(value, str) and value.strip() == expected:
            correct += 1
    return round(correct / len(EXTRACT_TRUTH), 4)


TASKS = [
    {
        "name": "bugfix",
        "prompt": BUGFIX_PROMPT,
        "grade": grade_bugfix,
        # Generous caps on purpose: reasoning models spend tokens on hidden
        # reasoning before the visible answer, and reasoning_content is billed
        # against the SAME completion budget. A tight cap scores the harness,
        # not the model (run 1 forced four 0.0s; run 2 still lost deepseek and
        # glm-5.3 at 6000). Usage and reasoning tokens are recorded per call,
        # so a model needing 11k tokens of thinking to fix 15 lines stays
        # visible as slow instead of being silently excused.
        "max_tokens": 12000,
    },
    {
        "name": "review",
        "prompt": DEFECT_PROMPT,
        "grade": grade_review,
        "max_tokens": 6000,
    },
    {
        "name": "extract",
        "prompt": EXTRACT_PROMPT,
        "grade": grade_extract,
        "max_tokens": 3000,
    },
]

TASK_BY_NAME: dict[str, dict] = {task["name"]: task for task in TASKS}

# The tiebreak is NOT part of the default suite: it is run explicitly
# (`--tasks bugfix2`) once the cheap tasks have narrowed the field, because it
# costs a full execution per candidate and exists to separate ties, not to
# re-measure them.
TIEBREAK_TASK = {
    "name": "bugfix2",
    "prompt": BUGFIX2_PROMPT,
    "grade": grade_bugfix2,
    "max_tokens": 12000,
}

ALL_TASKS: list[dict] = TASKS + [TIEBREAK_TASK]
ALL_TASK_BY_NAME: dict[str, dict] = {task["name"]: task for task in ALL_TASKS}

# ---------------------------------------------------------------------------
# Combined prompt: one request per model for candidates that are reachable
# only as OpenCode sessions (free-tier models refuse API use with
# "free tier can only be used from within OpenCode"). One session per model
# instead of three, with content-based section markers so the answer can be
# graded by exactly the same graders as the API path.
# ---------------------------------------------------------------------------

SECTION_MARKER = "=== SECTION: {name} ==="


def combined_prompt(tasks: list[dict] | None = None) -> str:
    """All tasks in one request, in a fixed order with fixed markers."""
    selected = TASKS if tasks is None else tasks
    names = ", ".join(task["name"] for task in selected)
    header = (
        "You have several independent tasks. Answer ALL of them. Introduce "
        "each answer with a line of the exact form === SECTION: <name> === on "
        f"its own line, using these names in this order: {names}. "
        "Do not merge, reorder or omit sections.\n"
    )
    body = "\n\n".join(
        SECTION_MARKER.format(name=task["name"]) + "\n" + task["prompt"]
        for task in selected
    )
    return header + "\n" + body


def parse_sections(answer: str) -> dict[str, str]:
    """Split an answer into {task_name: section_body} on the section markers.

    Content-based, not position-based: a model that reorders or adds prose
    around the markers still grades correctly. Unknown marker names are kept
    (a caller can ignore them); a missing section simply has no entry, and the
    scorer treats that as a failed section rather than raising.
    """
    sections: dict[str, str] = {}
    matches = list(
        re.finditer(
            r"^===[ \t]*SECTION:[ \t]*([a-z0-9_-]+)[ \t]*===[ \t]*$", answer, re.M
        )
    )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(answer)
        sections[match.group(1)] = answer[match.end() : end].strip()
    return sections


def score_sections(answer: str, tasks: list[dict] | None = None) -> dict[str, float]:
    """Grade every selected task section; absent or ungraded sections score 0.0."""
    sections = parse_sections(answer)
    selected = TASKS if tasks is None else tasks
    scores: dict[str, float] = {}
    for task in selected:
        name = task["name"]
        body = sections.get(name)
        if not body:
            scores[name] = 0.0
            continue
        try:
            scores[name] = float(task["grade"](body))
        except Exception:  # noqa: BLE001 - a grader crash is a zero, not a run-end
            scores[name] = 0.0
    return scores


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def endpoint_for(candidate: dict) -> tuple[str, str]:
    """(url, api_key) for a candidate; raises when its key is not configured."""
    spec = PROVIDERS.get(candidate.get("provider", ""))
    if spec is None:
        raise KeyError(f"no endpoint for provider {candidate.get('provider')!r}")
    key = (os.environ.get(spec["key_env"]) or "").strip()
    if not key:
        raise KeyError(f"{spec['key_env']} is not set")
    return spec["url"], key


# Transient transport states are retried, not eliminated: a 429/503 or a
# client timeout says the provider was having a moment, not that the model is
# unavailable. True unavailability (403/404/400) returns immediately so the
# elimination still carries a receipt.
RETRYABLE_HTTP = {429, 500, 502, 503, 529}
RETRY_BACKOFF_S = (15, 45)


def _reasoning_tokens(usage: object) -> int | None:
    """Hidden reasoning spend, when the provider reports it.

    Graded output is always the VISIBLE answer -- reasoning_content is never
    scored -- but how many tokens a model burned before answering is exactly
    the kind of fact a mutator selection should keep in the record.
    """
    if not isinstance(usage, dict):
        return None
    details = usage.get("completion_tokens_details")
    if not isinstance(details, dict):
        return None
    value = details.get("reasoning_tokens")
    return value if isinstance(value, int) else None


def dispatch(
    ledger: RequestLedger,
    model: str,
    prompt: str,
    max_tokens: int,
    api_key: str,
    timeout: int = 120,
    url: str = ZEN_URL,
    retries: int = 2,
) -> dict:
    """One measured request: latency, provider-reported model, usage, answer.

    Latency is the FIRST attempt's round trip; retries are counted in
    `attempts` so a model that only answers after two rate limits is still
    visible as slow/unreliable rather than silently laundered into the mean.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    attempts = 0
    while True:
        started = time.time()
        try:
            response = ledger.post_json(url, payload, api_key, timeout=timeout)
            break
        except BudgetExhausted:
            raise
        except urllib.error.HTTPError as cause:
            body = ""
            try:
                body = cause.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001 - the status is the signal
                pass
            attempts += 1
            if cause.code in RETRYABLE_HTTP and attempts <= retries:
                time.sleep(RETRY_BACKOFF_S[attempts - 1])
                continue
            return {
                "model": model,
                "ok": False,
                "http": cause.code,
                "detail": body,
                "attempts": attempts,
                "latency_s": round(time.time() - started, 3),
                "score": 0.0,
            }
        except Exception as cause:  # noqa: BLE001 - a failed call is a recorded zero
            attempts += 1
            if attempts <= retries:
                time.sleep(RETRY_BACKOFF_S[attempts - 1])
                continue
            return {
                "model": model,
                "ok": False,
                "error": type(cause).__name__,
                "attempts": attempts,
                "latency_s": round(time.time() - started, 3),
                "score": 0.0,
            }
    choices = response.get("choices") or [{}]
    content = choices[0].get("message", {}).get("content") or ""
    usage = response.get("usage")
    return {
        "model": model,
        "ok": True,
        "answered_by": response.get("model"),
        "attempts": attempts + 1,
        "latency_s": round(time.time() - started, 3),
        "usage": usage,
        "reasoning_tokens": _reasoning_tokens(usage),
        "finish_reason": choices[0].get("finish_reason"),
        "answer": content,
    }


def probe(ledger: RequestLedger, candidates: list[dict]) -> list[dict]:
    """Stage 1: availability + latency, one token each.

    Keys are resolved per candidate from its provider, so an unset key for one
    provider is a recorded zero for those candidates, not a crash for all.
    """
    rows = []
    for candidate in candidates:
        row = dict(candidate)
        try:
            url, key = endpoint_for(candidate)
        except KeyError as cause:
            row.update(
                {
                    "ok": False,
                    "error": str(cause),
                    "latency_s": 0.0,
                    "score": 0.0,
                }
            )
            rows.append(row)
            continue
        result = dispatch(
            ledger,
            candidate["model"],
            "Reply with exactly: OK",
            8,
            key,
            timeout=90,
            url=url,
        )
        row.update({k: v for k, v in result.items() if k != "answer"})
        row["probe_text"] = result.get("answer", "")[:40]
        rows.append(row)
    return rows


def screen(
    ledger: RequestLedger, candidates: list[dict], tasks: list[dict] | None = None
) -> list[dict]:
    """Stage 2: every surviving candidate on every task, graded by code."""
    rows = []
    tasks = TASKS if tasks is None else tasks
    for candidate in candidates:
        try:
            url, key = endpoint_for(candidate)
        except KeyError as cause:
            rows.append(
                {
                    "model": candidate["model"],
                    "task": "*",
                    "ok": False,
                    "error": str(cause),
                    "score": 0.0,
                    "latency_s": 0.0,
                }
            )
            continue
        for task in tasks:
            result = dispatch(
                ledger,
                candidate["model"],
                task["prompt"],
                task["max_tokens"],
                key,
                url=url,
                timeout=600,
            )
            answer = result.pop("answer", "")
            result["task"] = task["name"]
            result["truncated"] = result.get("finish_reason") == "length"
            result["score"] = task["grade"](answer) if result.get("ok") else 0.0
            result["answer"] = answer
            rows.append(result)
    return rows


def summarise(rows: list[dict]) -> list[dict]:
    """Mean score per model, plus mean latency over successful calls."""
    by_model: dict[str, list[dict]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)
    summary = []
    for model, items in by_model.items():
        scores = [item.get("score", 0.0) for item in items]
        latencies = [item["latency_s"] for item in items if item.get("ok")]
        summary.append(
            {
                "model": model,
                "mean_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
                "tasks": len(scores),
                "failures": sum(1 for item in items if not item.get("ok")),
                "truncated": sum(1 for item in items if item.get("truncated")),
                "retried": sum(1 for item in items if (item.get("attempts") or 1) > 1),
                "mean_latency_s": round(sum(latencies) / len(latencies), 3)
                if latencies
                else None,
            }
        )
    summary.sort(key=lambda row: (-row["mean_score"], row["mean_latency_s"] or 9e9))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--probe", action="store_true", help="stage 1 only")
    parser.add_argument("--run", action="store_true", help="stage 1 + stage 2")
    parser.add_argument(
        "--models", default="", help="comma list, overrides the catalogue"
    )
    parser.add_argument("--out", default="", help="output directory")
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument("--budget-note", default="")
    parser.add_argument(
        "--combined",
        action="store_true",
        help="print the combined task prompt (for session-only models) and exit",
    )
    parser.add_argument(
        "--tasks",
        default="bugfix,review,extract",
        help="comma list of task names to run/score (e.g. bugfix2 for the tiebreak)",
    )
    parser.add_argument(
        "--score-file",
        default="",
        help="grade a combined answer saved from an OpenCode session, write the result, exit",
    )
    parser.add_argument("--label", default="", help="model label for --score-file")
    args = parser.parse_args()

    wanted_tasks = [name.strip() for name in args.tasks.split(",") if name.strip()]
    unknown_tasks = [name for name in wanted_tasks if name not in ALL_TASK_BY_NAME]
    if unknown_tasks:
        print(f"unknown tasks: {', '.join(unknown_tasks)}", file=sys.stderr)
        return 2
    tasks = [ALL_TASK_BY_NAME[name] for name in wanted_tasks]

    if args.combined:
        print(combined_prompt(tasks))
        return 0

    if args.score_file:
        # Session-only free models refuse API use, so their answer arrives as
        # text from a real OpenCode session. It is graded by exactly the same
        # graders as the API path -- no separate yardstick for the in-house
        # route -- and the answer file itself is the evidence.
        source = pathlib.Path(args.score_file)
        if not source.is_file():
            print(f"no such file: {source}", file=sys.stderr)
            return 2
        scores = score_sections(source.read_text(encoding="utf-8"), tasks)
        result = {
            "model": args.label or source.stem,
            "route": "session",
            "source": str(source),
            "scores": scores,
            "mean_score": round(sum(scores.values()) / len(scores), 4)
            if scores
            else 0.0,
            "graded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "graders": "identical to the API path (grade_bugfix/grade_review/grade_extract)",
        }
        out = pathlib.Path(
            args.out
            or (
                pathlib.Path(__file__).resolve().parents[2]
                / "output"
                / "model-selection"
            )
        )
        out.mkdir(parents=True, exist_ok=True)
        target = out / "session-scores.jsonl"
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(json.dumps(result, indent=2))
        return 0

    candidates = CANDIDATES
    if args.models:
        wanted = {name.strip() for name in args.models.split(",") if name.strip()}
        candidates = [c for c in CANDIDATES if c["model"] in wanted] or [
            {"model": name, "provider": "unknown", "family": "requested"}
            for name in wanted
        ]

    # Only the providers this run actually touches must have keys, and a
    # missing key is reported up front rather than as 13 identical 403s.
    needed = sorted({c.get("provider", "unknown") for c in candidates})
    missing = [
        PROVIDERS[name]["key_env"]
        for name in needed
        if name in PROVIDERS
        and not (os.environ.get(PROVIDERS[name]["key_env"]) or "").strip()
    ]
    if missing:
        print(f"missing API keys: {', '.join(missing)}", file=sys.stderr)
        return 2
    unknown = [name for name in needed if name not in PROVIDERS]
    if unknown:
        print(f"no endpoint for providers: {', '.join(unknown)}", file=sys.stderr)
        return 2

    if args.run and args.max_calls <= 0:
        print(
            "--run requires a positive --max-calls and --budget-note", file=sys.stderr
        )
        return 2

    out = pathlib.Path(
        args.out
        or (pathlib.Path(__file__).resolve().parents[2] / "output" / "model-selection")
    )
    out.mkdir(parents=True, exist_ok=True)
    ledger = RequestLedger(out / "requests", args.max_calls, args.budget_note)

    report: dict = {
        "harness_author": "opencode/big-pickle",
        "endpoints": {name: spec["url"] for name, spec in PROVIDERS.items()},
        "tasks": [task["name"] for task in tasks],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "xai_note": "no free xai text model exists in the catalogue (grok-imagine only)",
        "nvidia_note": "priced at $0 in the catalogue; unknown-price models are not probed",
    }

    probe_rows = probe(ledger, candidates)
    report["probe"] = probe_rows
    survivors = [row for row in probe_rows if row.get("ok")]
    report["survivors"] = [row["model"] for row in survivors]
    print(
        f"probe: {len(survivors)}/{len(probe_rows)} available: "
        + (", ".join(report["survivors"]) or "none")
    )

    if args.run and survivors:
        screen_rows = screen(ledger, survivors, tasks)
        report["screen"] = screen_rows
        report["ranking"] = summarise(screen_rows)
        print(json.dumps(report["ranking"], indent=2))

    report["model_dispatches"] = ledger.calls
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"receipts + report in {out} ({ledger.calls} dispatches)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
