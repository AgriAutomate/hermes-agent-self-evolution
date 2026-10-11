# Governor second-opinion qualification (2026-10-12)

Executing model: `opencode/gpt-6.1-sol`. Second-opinion model: `jev-1.13.0`
(the same model as the primary judgment, given the added review context).

Budget line: CAP-approved 2026-10-12, max US$1 and 32 dispatch attempts combined
for governor and skill qualification. This qualification used **9** dispatch
attempts across three script runs (3 + 3 + 3); the final artifact run used 3.
The model reported no token usage block, and Jev's published input rate is about
$0.042/M with free output, so the measured spend is a small fraction of the cap.

## Method

The committed live-validation receipts already hold the PRIMARY judgment for each
known fixture. The script reconstructs each fixture, verifies its saved state
hash, replays the recorded primary answer, and spends a live call ONLY on the
cases that `needs_escalation` flags as doubtful. Grading is deterministic: the
second answer is re-checked with the same predicate, and code computes the
observed trend and the resulting posture. No judge model grades the run.

Script: `scripts/qualify_second_opinion.py` (re-runnable; each run writes its own
immutable `run-<timestamp>/` directory of request/response receipts).

## Result

Three of the four verified receipts were doubtful; the plateau case mapped
cleanly and needed no review. All three doubtful cases were re-asked with the
first judgment and the escalation reason attached:

| Fixture | Primary | Reason | Second | Second verdict | Outcome |
| --- | --- | --- | --- | --- | --- |
| converged | explore @0.86 | explore-on-ceiling | explore @0.95 | still doubtful | held 10/p75 |
| hedged_ceiling | explore @0.85 | explore-on-ceiling | explore @0.95 | still doubtful | held 10/p75 |
| steady_improvement | hold @0.73 | hold-on-clean-improvement | hold @0.88 | still doubtful | held 10/p75 |

**Resolved: 0 of 3. Unresolved: 3 of 3. Call failures: 0.**

## What this establishes, and what it does not

The runner's hold-on-doubt behavior is verified on real recorded states: every
unresolved case retained the current posture (10/p75), and no doubtful verdict
reached the sampler. That is the runner contract working end to end.

It also establishes a real limit: **asking the same model again with the review
context is not an escalation.** Jev became *more* confident in the same verdict
(0.86→0.95, 0.85→0.95, 0.73→0.88) rather than reconsidering. A second opinion is
only useful if it is a genuinely different or stronger judge, or if the review
state changes the decision it is asked to make.

Not claimed: no improvement in evolution quality, no correctness of any mutated
organism, and no general model judgment. This qualifies the escalation mechanism,
not the underlying posture choices. A different second-opinion model is the next
thing to measure, and its accuracy still needs a labeled standard to score against.
