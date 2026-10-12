# Bounded Tier 4 runner

The partition driver evaluates the target repository in temporary clones. It
preserves UTF-8/LF, checks the complete exported API with the target's
TypeScript parser, runs its three geometry regression gates, and scores the
fixed 15-case partition fixture.

```powershell
python -m evolution.code.fresh_partition_problem --output_dir <private-output-folder> --max_model_calls 0
```

`AA_FRESH_ROOT` selects the target checkout. Its dependencies must already be
installed because the signature gate uses its TypeScript devDependency.
`AA_CODE_TEMP_ROOT` selects the temporary-clone directory. On this workstation
it defaults to `D:/dev/caches/temp/opencode`.

## Stop rules and artifacts

- A nonviable baseline stops before any model request.
- A baseline with no trainable failures stops before any model request. This
  is a measured result, not a reason to invent mutations.
- A live run requires a positive `--max_model_calls` and an explicit
  `--budget_note`. The cap counts attempted dispatches, including failures;
  it is a request limit, not a claimed dollar-price guarantee.
- Iterations run in bounded segments of `--segment_iterations` (default 5),
  retaining one upstream population. Between segments a Jev judgment may change
  sampling parameters through the fixed preset dictionary, under the provisional
  confidence thresholds. A judgment that contradicts the observed trend, or sits
  below a floor (including a stop below its own higher floor), is not mapped: it
  holds the current posture and records the reason. An optional second opinion
  may be supplied; its answer is checked the same way, and an unavailable or
  still-doubtful review holds the posture. Invalid replies hold the current
  parameters and record the error.
- `OPENCODE_API_KEY` supplies the mutation client; `JEV_API_KEY` enables the
  governor. No keys or authorization headers are written to receipts.
- Budget refusal stops new dispatches while allowing already-produced sibling
  mutations to be evaluated.
- Run manifests, baselines, iteration records, decisions, request/response
  receipts and summaries are exclusive writes. Receipts retain the answering
  model, full response and usage rather than treating an alias as provenance.
- An improving, viable candidate can be written to the private output folder.
  Publication still requires independent holdout evidence and full repository
  checks. The runner does not edit, commit, push or deploy the product checkout.

The governor tests use synthetic judgments. The runner integration controls use
synthetic organisms with the actual upstream evolver. Neither set qualifies
model accuracy or an evolved product patch. The earlier three-call Jev smoke
exercise used broad acceptable-label sets; it is connectivity evidence, not
calibration.

## Licensing boundary

`fresh_partition_problem.py` and `governed_runner.py` carry AGPL-3.0-only SPDX
headers because they import the upstream evolver. These are development-side
adapters, outside the product repositories. The independent governor and
request ledger use the standard library. No upstream mirror files are modified.
