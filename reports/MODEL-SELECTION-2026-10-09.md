# Measured model selection over the free catalogue

**Dates:** 2026-10-08 → 2026-10-09 · **Branch:** `bench/model-selection` (PR #2) ·
**Work performed by:** `opencode/mimo-v2.6-flash-free` · **Suite:** `tests/bench` (37) in a
240-test green repo.

## 1. The question

The Tier 4 pipeline dispatches models through `evolution/code/request_ledger.py`
(`governed_runner.run_governed` supplies the model id per dispatch). Which id should it
supply? This document is the measured answer over the **free** catalogue
(`opencode` / `nvidia` / `xai`), not a preference.

Rules held throughout:

- **Code-graded, never a judge model.** Every score comes from executed code or set arithmetic.
- **Synthetic prompts only.** Free-tier endpoints are not a confidential channel.
- **Receipts or it did not happen.** Every dispatch leaves an immutable request/response pair
  under `D:\dev\caches\temp\opencode\model-selection\run*\requests\`.
- **Ties are reported as ties.** A tie is broken by stability, availability, latency, and policy
  — never by inventing score resolution.

## 2. Method — three stages, each one a filter

1. **Probe** — one token per candidate. Records availability, round-trip latency, the model the
   *provider* says answered (echo check), attempts.
2. **Screen** — three task-shaped prompts, each graded by code:
   - `bugfix` — returned code is executed against a fixed assertion set (pass = 1.0).
   - `review` — set F1 over planted defects in a review answer.
   - `extract` — schema fields, `correct / 6`.
3. **Confirm / tiebreak** — repeat for stability; `bugfix2` grades **per assertion**, so a partial
   repair earns partial credit. It exists because run 2 left seven candidates tied at 1.0 and a
   tie cannot pick a winner.

**Two routes, one yardstick.** OpenCode free-tier models refuse API use (`FreeTierError`), so they
run as real OpenCode `subagent` sessions answering a combined prompt (`--combined`), and the raw
answers are graded by the *identical* graders via `--score-file`. API candidates are called
directly. Both routes land in the same grade functions.

**Transient ≠ model failure.** `RETRYABLE_HTTP = {429, 500, 502, 503, 504, 529}` is retried with
backoff (attempts recorded); true unavailability (400/403/404) returns immediately with a receipt.
An elimination must be about the model, never about the moment.

## 3. Catalogue scan

| Provider | Catalogue | Free | Probed |
|---|---|---|---|
| opencode (zen) | 84 models | 11 free | API-accessible: **1** (`space-bunny-free`); the other 10 raise `FreeTierError` (session-only) → run on the session route |
| nvidia | 41 catalogue entries, all catalogue-$0 | 41 | 13 chat-capable probed; unknown price ≠ free, never probed |
| xai | — | 0 text models | `grok-imagine` only; no text candidate |

## 4. Defects this benchmark found — by running it, not by reading it

1. **`request_ledger` sent no User-Agent.** Every dispatch to `opencode.ai` died on Cloudflare 1010.
   The already-merged Tier 4 mutator would have failed identically at its first live call. Fixed
   with an honest project UA; the spoofed browser UA sitting in the bench file is gone.
2. **Transient states counted as model failures.** 429/503 eliminated `laguna-xs` and
   `glm-5.3-flash`; 504 later did the same to `glm-5.3`'s long code generations (twice). All are
   retried now; a gateway timeout says nothing about the model.
3. **The token cap scored the harness, not the model.** `reasoning_content` shares the completion
   budget: at 1500 tokens, four models returned `finish_reason=length` with an *empty* answer and
   were ranked last for it. Caps raised (12000/6000/3000), truncation recorded as its own field,
   `reasoning_tokens` retained per call and never graded.
4. **Counterfactual kept, rule not relaxed:** `diffusiongemma`'s `bugfix` code passes every
   assertion when the fence is ignored — and still scores 0.0. Format compliance is part of the
   declared contract; the counterfactual is recorded, the rule unchanged.

## 5. API-route runs

| Run | Dispatches | Status | What it showed |
|---|---|---|---|
| run1 | 48 | complete (defective harness) | 24 candidates, 8 available; exposed defects 1–3 |
| run2 | 53 | complete | 7 survivors, ranked (below) |
| run3 | 29 req / 28 resp | **stopped on instruction** — no `report.json` | never quoted as a completed confirm run |
| run4 | 35 | complete (post-credit retry) | probe 4/7; `laguna-xs` unlocked; `glm-5.3` hit 504 ×3 on code tasks |
| run5 | 11 | complete (tiebreak) | 3/3 probed; `space-bunny-free` and `gpt-oss-20b` both pass `bugfix2`; `glm-5.3` completes `bugfix` (1.0) but `bugfix2` 504 ×3 **again** — endpoint cap now reproduced in two runs |

### run2 (3-task screen)

| Model | Mean score | Fail | Trunc | Mean latency |
|---|---|---|---|---|
| `space-bunny-free` | 1.0 | 0 | 0 | **9.3 s** |
| `openai/gpt-oss-20b` | 1.0 | 0 | 0 | 15.2 s |
| `meta/muse-glimmer-30b` | 1.0 | 0 | 0 | 90.6 s |
| `google/diffusiongemma-26b-a4b-it` | 0.6667 | 0 | 0 | 1.3 s |
| `z-ai/glm-5.3` | 0.6667 | 0 | 1 | 93.0 s |
| `deepseek-ai/deepseek-v4.1-flash` | 0.6667 | 0 | 1 | 95.6 s |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 0.6667 | 0 | 1 | 143.1 s |

`deepseek-v4.1-flash` exhausted 12 000 completion tokens with an empty visible answer across runs
1–3 — recorded as a model property, not a harness cap.

### run4 (4-task screen incl. `bugfix2`)

Probe 4/7: `kimi-k3` timeout ×3 (90.3 s), `llama-guard-4-12b` timeout ×3 (91.0 s),
`glm-5.3-flash` 429 ×3 → eliminated with receipts; `glm-5.3`, `muse-glimmer-30b`, `laguna-xs`,
`diffusiongemma` available.

| Model | Mean score | Fail | Trunc | Retry | Mean latency |
|---|---|---|---|---|---|
| `meta/muse-glimmer-30b` | **1.0 (4/4)** | 0 | 0 | 0 | 112.5 s |
| `poolside/laguna-xs-2.1` | 0.9688 (bugfix2 0.875 = 7/8 checks) | 0 | 0 | 1 | 31.7 s |
| `google/diffusiongemma-26b-a4b-it` | 0.7188 (bugfix 0.0 — the fence) | 0 | 0 | 0 | **10.4 s** |
| `z-ai/glm-5.3` | 0.5 — `bugfix`/`bugfix2` both **504 ×3** (~101 s/attempt) | 2 | 0 | 2 | 24.5 s |

`glm-5.3` scored 1.0 on `review` and `extract`; its two code-task failures are gateway 504s on
long generations (run 2 once completed the same call at 481 s), i.e. an inconsistent endpoint cap,
recorded as such rather than as a coding failure.

### run5 (tiebreak completion, 11 dispatches)

| Model | `bugfix` | `bugfix2` | Notes |
|---|---|---|---|
| `space-bunny-free` | 1.0 (repeat of run2, 85.1 s, 9301 reasoning tok) | **1.0** (71.0 s) | → 4/4 |
| `openai/gpt-oss-20b` | 1.0 (repeat, 116.7 s) | **1.0** (139.8 s) | → 4/4 |
| `z-ai/glm-5.3` | **1.0** (227.8 s — completes when the gateway holds) | 0.0 — `ok=False`, **504 ×3** (302.5 s) | second run with the identical failure |

## 6. Session route (OpenCode free models, graded by the same graders)

**Round 1 (3 tasks):** 10 candidates, 8 answered. `exo-free` and `ling-3.0-flash-fin-free` failed
twice each ("Upstream request failed: Endpoint is unavailable") → eliminated with receipts.

**Round 2 (4 tasks incl. `bugfix2`):**

| Model | Round 1 | Round 2 | Note |
|---|---|---|---|
| `ling-3.1-flash-free` | 1.0 | **4/4** | |
| `big-pickle` | 1.0 | **4/4** | |
| `fledge-alpha-free` | 1.0 | **4/4** | |
| `longcat-2.5-preview-free` | 1.0 | **4/4** | |
| `mimo-v2.6-flash-free` | 1.0 | **4/4** | |
| `muse-spark-1.3-contributor-free` | 1.0 | **4/4** | |
| `nemotron-3.5-lightning-free` | 0.9524 | 0.9643 | `review` F1 = 0.8571 **in both rounds** — stable, not noise |
| `nemotron-3-ultra-free` | 1.0 | 0.9375 | `bugfix2` 0.75 (one missed check) |

Session-route latency is **not** measured — no receipts comparable to the API route; this is a
stated gap, not a silent omission.

## 7. Ranking and recommendation

### API route (what `request_ledger` can dispatch) — 4-task standing

Scores are the best successful reading per task across run2 + run4 + run5; `×2` marks a task
passed in two independent runs. Latency is the mean over the four tasks using each task's most
recent successful run (run2's three-task means — 9.3 / 15.2 / 90.6 s — show the same ordering).

| # | Model | bugfix | review | extract | bugfix2 | Score | Mean lat | Fail/Trunc/Retry |
|---|---|---|---|---|---|---|---|---|
| 1 | `space-bunny-free` | 1.0 ×2 | 1.0 | 1.0 | 1.0 | **4/4** | **39.9 s** | 0/0/0 |
| 2 | `openai/gpt-oss-20b` | 1.0 ×2 | 1.0 | 1.0 | 1.0 | **4/4** | 67.0 s | 0/0/0 |
| 3 | `meta/muse-glimmer-30b` | 1.0 ×2 | 1.0 | 1.0 | 1.0 | **4/4** | 112.5 s | 0/0/0 |
| 4 | `poolside/laguna-xs-2.1` | 1.0 | 1.0 | 1.0 | 0.875 | 0.9688 | 31.7 s | 0/0/1 |
| 5 | `google/diffusiongemma-26b-a4b-it` | 0.0 ×2 | 1.0 | 1.0 | 0.875 | 0.7188 | 10.4 s | 0/0/0 |
| — | `z-ai/glm-5.3` | 1.0 | 1.0 | 1.0 | **504 ×3** | 3/4 tasks completed | 92.3 s | 2 endpoint |
| — | `deepseek-ai/deepseek-v4.1-flash` | 0.0 (`finish=length`, whole budget on reasoning) | 1.0 | 1.0 | — | 0.6667 | 95.6 s | 0/1/0 |
| — | `nvidia/nemotron-3.5-lightning-30b-a3b` | 1.0 | 0.0 (`finish=length` at 3000 tok) | 1.0 | — | 0.6667 | 143.1 s | 0/1/0 |

**The tie and how it breaks.** Three models are indistinguishable at 4/4, with zero failures,
zero truncations, zero retries, and both `bugfix` repeats passing. Measured latency separates
them (39.9 s < 67.0 s < 112.5 s), and the machine's own policy settles it:
`space-bunny-free` is the zero-retention default, while the other two are third-party free
endpoints. Scores were not adjusted to manufacture a winner.

**Recommendation — mutator/reviewer id for the Tier 4 ledger: `space-bunny-free`.**
Measured fallbacks, in order: `openai/gpt-oss-20b` (same score, 1.7× the latency), then
`meta/muse-glimmer-30b` (same score, 2.8× the latency). If score-per-second outweighs one
partial repair, `poolside/laguna-xs-2.1` earned 0.9688 at 31.7 s — the best score-per-second of
the accurate models, and its one miss (`bugfix2` = 7/8 checks) is on the record.

**Excluded, each with receipts:** `z-ai/glm-5.3` (gateway 504 on the longest code task in two
separate runs — its completed tasks are all 1.0, so this is an endpoint verdict, not a coding
one), `deepseek-v4.1-flash` (burns the completion budget on reasoning until the visible answer
is empty — reproduced across runs 1–3), `diffusiongemma` (fence contract, §4.4),
`glm-5.3-flash` (429 ×3), `moonshotai/kimi-k3` and `meta/llama-guard-4-12b` (timeout ×3 each),
`mistralai/*` ×3 (404 on endpoint), 10 zen free models (`FreeTierError` — session-only),
xai (no free text model).

### Session route (OpenCode agent-side roles)

Six models are **tied at 4/4 across two rounds** — reported as a tie, not resolved by invented
scores. Applying the machine's own confidential-data policy (`AGENTS.md`: models marked "do not
submit personal or confidential data" should not carry repo internals) filters the tie to a
shortlist: **`ling-3.1-flash-free`, `fledge-alpha-free`, `longcat-2.5-preview-free`,
`muse-spark-1.3-contributor-free`** — all 4/4 twice, none flagged. Measured below the tie:
`nemotron-3.5-lightning-free` 0.9643 (`review` F1 = 0.8571 in *both* rounds — a stable
weakness, not noise), `nemotron-3-ultra-free` 0.9375 (`bugfix2` 0.75). Eliminated:
`exo-free` and `ling-3.0-flash-fin-free` (endpoint unavailable, ×2 each).

### Reproduce

```powershell
python -m evolution.bench.model_selection --run --tasks bugfix,review,extract,bugfix2 `
  --models "space-bunny-free" --max-calls 30 --budget-note "<why>" --out "<dir>"
# session route: --combined for the prompt fixture, --score-file to grade saved answers
```

## 8. What this does not prove

- No production traffic was measured; every prompt is synthetic and disposable.
- No judge model graded anything; a model never became the source of truth.
- No claim of product-quality improvement follows from these scores — the suite measures three
  narrow skills, not farming-domain correctness.
- Session-route latency and token usage are unrecorded (gap above).
- Ties are real: six session models are indistinguishable at 4/4 on this suite. They are reported
  as ties and broken only by stability, availability, and policy.

## 9. Receipts

```
D:\dev\caches\temp\opencode\model-selection\
  run1\requests\  run2\requests\  run4\requests\  run5\requests\   (immutable pairs)
  run1\report.json  run2\report.json  run4\report.json  run5\report.json   (complete runs)
  run3\requests\                                                 (partial; no report — not evidence)
  run2\session-scores.jsonl   session-round2\session-scores.jsonl  (session grades)
  answers\                                                       (raw session answers)
  combined_prompt_4t.txt                                         (round-2 prompt fixture)
```

Harness: `evolution/bench/model_selection.py` · self-tests: `tests/bench/test_model_selection.py`
(37) · repo suite: 240 passed.
