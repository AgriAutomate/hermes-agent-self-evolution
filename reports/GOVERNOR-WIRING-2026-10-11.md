# Governor escalation runner connection

Executing model: `opencode/gpt-6.1-sol`.
Base: `75f2dacfd154f7706eafe910b8a6fe04cd7256b9`, the merged integration branch
`fix/validate-reassembled-skill`, rather than the upstream-mirror `main`.
Work branch: `fix/governor-escalation-wiring`.
Programme record: B-160 on the active blueprint-fresh board.

## Reproduced gap

The merged escalation helper identified a contradiction, but the actual segment
path did not call it. With scores `[0.60, 0.65, 0.68, 0.70, 0.74]` and primary
`explore @0.9`, `needs_escalation` returned `explore-while-improving` while
`run_segment` still returned sharpness 5 / midpoint p50. This was reproduced
without inference. The live-validation driver's escalation labels did not
establish the bounded runner's behavior.

## Connection

`run_segment` now checks before mapping. It admits at most one injected
`escalation_judge`, includes the first judgment and reason in its review state,
then applies the same check to the second answer. An unavailable or unresolved
opinion retains the current posture. Stop answers also require review when they
do not clear the separate stop confidence floor.

`run_governed` accepts the optional callback and records both returned model
identities, verdicts, confidence, reason and resolution. A request-cap refusal
during either judgment is recorded before the runner ends dispatching. Existing
fixed mapping and sampling bounds still apply to admitted answers.

For an explicitly budgeted live caller, inject both callbacks through the same
`RequestLedger`; its cap counts attempts, including failures:

```python
run_governed(
    problem,
    directory,
    ledger,
    judge=budgeted_primary,
    escalation_judge=budgeted_second_opinion,
)
```

The current partition CLI supplies the primary judge. Without a configured
secondary callback, doubtful judgments are recorded as `unavailable` and hold
the posture. No secondary provider/model selection or inference-quality claim
is implied by this offline connection.

## Verification

The focused checks execute the real upstream population sampler using synthetic
organisms. They cover: an admitted primary posture, rejection before sampling,
one resolved second opinion reaching the sampler, unresolved second opinion
holding without recursion, and shared-cap refusal stopping with decision evidence.
These are developer-authored regression controls, not proof of better mutations.
The programme record retains actual command counts and replay observations.

All 254 repository checks passed. The before/after replay in
`reports/governor-replay-20261011.json` reconstructs the committed fixtures and
verifies their saved state hashes before using the judgments. Four receipts
matched. The plateau still reaches 5/p50; converged and hedged ceilings now
retain 10/p75 instead of applying exploration; the climbing hold case retains
10/p75 with an explicit unresolved-review record. One older plateau receipt's
hash does not match the current fixture and is explicitly excluded. Zero new
inference requests were dispatched.

Vet was invoked with the executing model after logical changes. Its Windows
agentic CLI failed with Errno 22 before review; no review pass is claimed.

## Next qualification

Choose a budgeted second-opinion adapter and measure it on recorded real-run
states. Separately, Phase 1 skill scoring remains a keyword-overlap proxy;
measured agent/tool execution is required before claiming skill improvement.
The source-lookup qualification supports lexical as the default, with dense/hybrid
optional after its parity result. Neither qualification establishes general
self-evolution improvement.
