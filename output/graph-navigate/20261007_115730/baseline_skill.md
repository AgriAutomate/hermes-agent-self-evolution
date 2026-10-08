---
name: graph-navigate
description: Query the unified code graph for bounded work items and follow cross-repo references.
version: 1.0.0
author: Martin (CAP) + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-graph, navigation, architecture, evidence]
    category: codebase
    requires_toolsets: [http]
environments:
  - codebase
---

# Graph Navigate Skill

Turn the unified code graph's head into a bounded work item. This skill reads
the graph's compact index and per-repository fragments, follows cross-repo
references, and returns a scope with evidence. It does **not** verify claims by
itself — the graph is an index, not an authority on truth.

## When to Use

Use this skill when any of the following are true:

- you need to find where a symbol, RPC or board task actually lives before
  touching code;
- you need every repository that references a target before scoping a change;
- a board item names a repository and you must confirm the attribution first.

Do not use it to answer "does this exist in the live database" — repo evidence
cannot answer that (nine client-called RPCs are defined in no migration while
migration drift is zero).

## Prerequisites

- The graph head served by `scripts/serve.mjs` (default `127.0.0.1:4102`).
- Endpoints: `GET /api/graph-index` (compact index — 41 repositories, type
  counts, per-repo fragment sizes, observations) and
  `GET /api/repo-fragment/:name` (one repository's sharded graph).
- `fetch` or any HTTP client. No token is required; the server is loopback-only
  and never serves the full 182 MB graph body.

## How to Run

1. Read the index once: `GET /api/graph-index`. Use `totals` and
   `typeCounts` to size the question; use each repository's `fragment.types`
   to decide whether a repo has the surface you need (a repo with zero
   `symbol` nodes has metadata only).
2. Pick the candidate repositories by `pushedAt` (recency is a development
   activity proxy, never usage or traffic).
3. Read only the fragments you need: `GET /api/repo-fragment/<owner>/<name>`.
   Fragment nodes carry `file`, `sha` and commit-pinned `url` fields.
4. Follow cross-repo `references-repository` / `source-reference` edges to
   find every repository touched by the change. A name match is a discoverable
   candidate contract, never proof of deployment, grants or permission.
5. Verify every claim against the actual files before acting on it. Re-read
   the target repository's AGENTS.md before writing there.

## Quick Reference

| Question | Endpoint | Then |
|---|---|---|
| What exists and where | `/api/graph-index` | pick candidate repos by type + recency |
| Where is this symbol | `/api/repo-fragment/:name` | search fragment nodes by label/file |
| What else references it | fragment edges | follow `references-*`, then verify in the real repo |
| What does the source look like | `GET /api/source?id=<node-id>` | commit-pinned, credential-filtered |

## Boundaries

- The graph is evidence-gathered, never assumed true: re-verify against files.
- Fragments and observations stay inside the private graph repo — never quote
  them in public PR bodies or issue comments.
- A parsed-with-warnings observation means partial extraction; treat its
  symbol coverage as incomplete, not wrong.
