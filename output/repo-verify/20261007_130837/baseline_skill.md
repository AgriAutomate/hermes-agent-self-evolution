---
name: repo-verify
description: Run a repository's documented checks from the graph's recorded commands and report evidence.
version: 1.0.0
author: Martin (CAP) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [verification, testing, evidence, gates]
    category: codebase
    requires_toolsets: [terminal, http]
environments:
  - codebase
---

# Repo Verify Skill

Produce evidence, not conclusions. This skill runs a repository's documented
checks and reports what executed, what passed, and what failed. It never
certifies correctness: passing tests written by the same author are not
evidence of correctness, and a green workflow does not mean code shipped.

## When to Use

Use this skill when any of the following are true:

- a change is about to be proposed and its gate evidence must exist first;
- a claim says "tests pass" or "build green" and the evidence must be
  reproduced rather than adopted;
- a merge batch landed and the deploy step's execution must be confirmed.

## Prerequisites

- A local checkout of the target repository (the graph's `local-map.json`
  records which repos are mapped; the graph index's `source` observation
  records the SHA each repo was last indexed at).
- The repo's AGENTS.md — read it first; it defines the check commands and the
  rails that bind this skill.

## How to Run

1. Read the repo's AGENTS.md and extract its documented check commands (for
   example `npm test`, `deno test`, `npm run build`,
   `scripts/check-encoding.cjs`, `scripts/check-board.cjs`).
2. Confirm the checkout is on the commit you intend to verify: `git rev-parse
   HEAD`, clean worktree. Record the SHA in the evidence.
3. Run each command as documented. Capture the exit code and the summary line —
   not the assumption. A command that was never executed is UNVERIFIED, and a
   cancelled or superseded CI run counts as UNDEPLOYED.
4. After a merge batch touching deployable paths, confirm the deploy step
   **executed** for the head SHA: read the run's job steps, not the workflow
   conclusion. If the batch touched no deployable path, say so.
5. Report the evidence as: command → exit code → observed summary → SHA.
   Mark every check you did not run as unverified rather than assuming it.

## Quick Reference

| Claim | Evidence that proves it |
|---|---|
| tests pass | the test command's exit code + pass count at a recorded SHA |
| build green | the build command's exit code, not a CI badge |
| deployed | the deploy job's executed step for the target SHA |
| encoding clean | `check-encoding.cjs` reporting zero mojibake files |
| board consistent | `check-board.cjs` C1–C10 pass |

## Boundaries

- Never hand a green workflow conclusion as deploy evidence.
- Never report a check you did not execute.
- Reviewers' findings are reproduced before adoption — a reviewer that has not
  written the code is not proof.
