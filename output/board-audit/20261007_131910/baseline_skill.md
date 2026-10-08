---
name: board-audit
description: Compare board records against the graph's observations and surface divergences with evidence.
version: 1.0.0
author: Martin (CAP) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [board, audit, evidence, governance]
    category: codebase
    requires_toolsets: [http, http-file]
environments:
  - codebase
---

# Board Audit Skill

Compare what the board claims against what the code and the live platform
actually show, and surface every divergence with evidence. This skill audits;
it does not adjudicate — a model never becomes the source of truth.
Deterministic proof or explicit human adjudication sets TRUE/FALSE.

## When to Use

Use this skill when any of the following are true:

- a board item is about to be ticked and its claims must be checked;
- a ticked item's evidence must be re-verified after the repos it references
  moved on;
- a stale claim is suspected (a KNOWN-ISSUES entry, an "already done" note, a
  board task claiming work that may have regressed or been superseded).

## Prerequisites

- The graph head: `GET /api/graph-index` and `GET /api/repo-fragment/:name`.
  Board-task records appear as `board-task` nodes with `state`, `owner`,
  `recordedModel` and `evidence: board-record`.
- Read access to the board repo (TASKS.json) and, where a claim touches a live
  platform, read-only platform tooling (Vercel firewall/deployment config,
  Supabase migrations/advisors).

## How to Run

1. Read the board's task records from the graph fragment (`board-task` nodes)
   and the board repo's TASKS.json. A tick is an owner claim, not proof — the
   board's own node state records `owner-ticked (not proof)`.
2. For each claim, find the evidence the item names (paths, commits, PR
   numbers, checks) and reproduce what can be reproduced.
3. Reconcile against what moved since the claim was written: a board item
   created before a repo's commits may be stale, misattributed, or resolved by
   someone else. Check the symbol the item names actually exists in the repo it
   names — one board item said "engine" for a symbol that lived in residential
   with zero callers.
4. For claims about live platforms, verify against the platform's read APIs
   (deployment state, firewall rules, migration lists) rather than repo
   evidence. Repo absence does not prove live-DB absence: migration drift can
   be zero while functions exist out-of-band.
5. Report divergences as: claim → evidence found → verdict (aligned /
   misattributed / stale / unresolvable) → what would resolve it. Never
   renumber or re-tick; deprecate with a pointer.

## Quick Reference

| Divergence | Signature | Resolution |
|---|---|---|
| misattributed | the named symbol/RPC exists in a different repo | correct the item's repo field |
| stale | resolved or superseded by later commits | mark resolved with the merge SHA |
| unresolvable | repo evidence cannot answer (live DB, runtime state) | name the check that would resolve it |
| regressed | evidence existed, current check fails | file the regression with the repro |

## Boundaries

- Never tick a task; the page owns `tasks`, agents own `meta`.
- Never present a model's conclusion as adjudication.
- Never report an unexecuted check as evidence.
