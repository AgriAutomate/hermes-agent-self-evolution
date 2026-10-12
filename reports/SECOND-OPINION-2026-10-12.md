# Governor second-opinion qualification (2026-10-12)

Executing model: `opencode/gpt-6.1-sol`. Second-opinion model: `jev-latest`
(the same model as the primary judgment, given the added review context).

**All figures are generated from the run artifact, not hand-copied.**
See `scripts/output/second-opinion-qualification/run-*/summary.md`, written by
`scripts/qualify_second_opinion.py` from that run's `report.json` and its
request/response receipts. If the two ever disagree, the artifact is the truth.

Budget line: CAP-approved 2026-10-12, max US$1 and 32 dispatch attempts combined
for governor and skill qualification. This document does not restate spend
figures; the run's `report.json` records `callsUsed` for the retained run.

## Method

The committed live-validation receipts already hold the PRIMARY judgment for each
known fixture. The script reconstructs each fixture, verifies its saved state
hash, replays the recorded primary answer, and spends a live call ONLY on the
cases that `needs_escalation` flags as doubtful. Grading is deterministic: the
second answer is re-checked with the same predicate, and code computes the
observed trend and the resulting posture. No judge model grades the run. Each run
writes its own immutable `run-<timestamp>/` directory.

## Result

Every doubtful case was re-asked with the first judgment and the escalation
reason attached. **None resolved:** the same model, given the review context,
became *more* confident in the same verdict, so the runner held the posture on
every doubtful case. The plateau case mapped cleanly and needed no review. Exact
verdicts and confidences are in the generated summary.

## What this establishes, and what it does not

The runner's hold-on-doubt behaviour is verified on real recorded states: no
unresolved case reached the sampler, and each held the current posture. That is
the runner contract working end to end.

It also establishes a real limit: **asking the same model again with the review
context is not an escalation.** A second opinion is only useful if it is a
genuinely different or stronger judge, or if the review state changes the
decision it is asked to make.

Not claimed: no improvement in evolution quality, no correctness of any mutated
organism, and no general model judgment. This qualifies the escalation mechanism,
not the underlying posture choices. A different second-opinion model is the next
thing to measure, and its accuracy still needs a labeled standard to score against.

## Evidence discipline

An earlier draft of this report hand-copied figures from a development run while
the committed artifact was a later run, so the prose and the artifact disagreed.
The report is now generated from the artifact, and the script records a cap
refusal as `budget-refused` (stopping the loop) rather than as a `call-failed`,
so a refusal cannot inflate the failure count.
