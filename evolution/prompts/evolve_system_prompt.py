"""Tier 3 — system-prompt evolution, behind the frozen-invariant gate.

The target: the fork's execution-discipline block (OPENAI_MODEL_EXECUTION_GUIDANCE,
agent/prompt_builder.py) — the tool-usage guidance shipped in the cached system
prompt to every session. The fork's own rule: "Short on purpose — token cost is
paid once at install. Keep it tight."

The lever (the Tier 2 finding): tool-usage PROMPTS govern tool-selection accuracy
(reason-first selection doubled it, 26.5% -> 58.8%). So the block is evolved
against the tool-selection eval, with:

- the FROZEN-INVARIANT GATE: the AA-Core identifiers, canonical names, governance
  rails and the block's own sub-section structure are immutable inputs;
- a SIZE gate: the candidate stays within the baseline's rendered size (the fork's
  "keep it tight" rule — no bloat in the cached prompt);
- the eval: tool-selection accuracy on a holdout the loop never saw.

Deployment (only on a gate-passing improvement): the evolved block replaces the
constant in prompt_builder.py — offline, a new version for NEW sessions only
(prompt caching is sacred; mid-conversation mutation is never done).
"""

import json, re, time
from pathlib import Path

import dspy

GUIDANCE_FILE = Path(r"D:/dev/caches/temp/opencode/execution-guidance.txt")
TOOLS_FILE = Path(r"D:/dev/caches/temp/opencode/hermes-tool-descriptions.json")
MODEL = "openai/gpt-4.1-mini"
OUT_DIR = Path("output") / "system-prompt" / time.strftime("%Y%m%d_%H%M%S")
GENERATIONS = 4

NEUTRAL_SELECTOR_NOTE = ""  # none: the block itself instructs selection

# Train tasks (the loop's fitness): the confusable cluster.
TRAIN = [
    (
        "Find every file in this repo that references the RPC trigger_run_repair.",
        "search_files",
    ),
    (
        "Read the file src/lib/supabase.ts and quote its first 20 lines verbatim.",
        "read_file",
    ),
    ("Search the web for the current Vercel AI Gateway pricing page.", "web_search"),
    ("Run the test suite in this repo and report the pass count.", "terminal"),
    (
        "Grep for 'exposed_schemas' across the engine's supabase directory.",
        "search_files",
    ),
    (
        "Pull the contents of https://vercel.com/docs/ai-gateway/trace-drains as markdown.",
        "web_extract",
    ),
    (
        "List the files under .cache/remotes without reading their contents.",
        "search_files",
    ),
    ("Compute the SHA-256 of this JSON blob inside the agent process.", "execute_code"),
    ("Find every TODO comment mentioning the AGPL licence.", "search_files"),
    ("Apply this exact diff to src/lib/models.ts.", "patch"),
    (
        "Locate every migration file that alters engine.knowledge_chunks.",
        "search_files",
    ),
    ("Write the refreshed index to .cache/index.json.", "write_file"),
    (
        "Find where the graph index endpoint is implemented in this workspace.",
        "search_files",
    ),
    ("Run git log -S 'match_knowledge_chunks' in the engine repo.", "terminal"),
    ("Quote the YAML frontmatter of the graph-navigate skill.", "read_file"),
    (
        "Search the repo for every file that shadows a stdlib module name.",
        "search_files",
    ),
    ("Deploy the edge functions with the CLI and report the result.", "terminal"),
    ("Find where the claim gate is judged in the rebuild's engine.", "search_files"),
    ("Rewrite src/lib/render.ts to split the render function.", "write_file"),
    ("Fetch the AI SDK spend-report docs page and summarise it.", "web_extract"),
]

# Holdout (never seen by the loop): the report set.
HOLDOUT = [
    ("Find which files import the ToolRegistry class in this repo.", "search_files"),
    ("Read the LICENSE file and quote its first line.", "read_file"),
    ("Search the docs for the trace drain sampling rules.", "web_search"),
    ("List every migration file in supabase/migrations by name.", "search_files"),
    ("Install the Python dependencies from pyproject.toml.", "terminal"),
    ("Quote the tool registry's register() signature.", "read_file"),
    ("Find every file that shadows a stdlib module name.", "search_files"),
    ("Check the gateway credit balance via the /v1/credits endpoint.", "terminal"),
    ("Replace the deprecated call in this file with the new signature.", "patch"),
    ("Look up the AI Gateway's custom reporting docs page.", "web_search"),
    ("Find every file that references knowledge_source_registry.", "search_files"),
    ("Append the run result to the ledger JSONL file.", "write_file"),
]

# The block's sub-section tags are the structure contract: a candidate that
# deletes one loses the guidance's organisation.
SUB_SECTIONS = [
    "tool_persistence",
    "mandatory_tool_use",
    "act_dont_ask",
    "prerequisite_checks",
    "verification",
    "external_state_verification",
    "literal_preservation",
    "missing_context",
]


def load_block():
    return Path(GUIDANCE_FILE).read_text(encoding="utf-8")


def load_catalog():
    rows = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
    return {r["name"]: (r["description"] or "") for r in rows}


def catalog_text(catalog):
    return "\n".join(f"- {n}: {d}" for n, d in sorted(catalog.items()))


class Selector(dspy.Module):
    """The block IS the signature's instructions — the mutation target."""

    def __init__(self, block: str):
        super().__init__()
        self.predictor = dspy.ChainOfThought(
            dspy.Signature("task_with_catalog -> tool", instructions=block)
        )

    def forward(self, task_with_catalog: str):
        return self.predictor(task_with_catalog=task_with_catalog)


def with_catalog(task: str, catalog: str) -> str:
    return f"{task}\n\nAVAILABLE TOOLS (reply with exactly one name):\n{catalog}"


def fitness(example, pred, trace=None):
    return 1.0 if example.tool in (getattr(pred, "tool", "") or "") else 0.0


def gates(cand: str, base: str) -> dict:
    # 1. The frozen-invariant gate: the governance rails + identifiers.
    from evolution.core.frozen_invariants import check as check_frozen

    v = check_frozen(base, cand)
    # 2. Size: the fork's "keep it tight" — no bloat in the cached prompt.
    size_ok = len(cand) <= len(base) + 200  # ≤ baseline +5% headroom
    # 3. The block's sub-section structure survives.
    missing_secs = [s for s in SUB_SECTIONS if f"<{s}>" not in cand]
    return {
        "frozen_invariants": v,
        "size": {"ok": size_ok, "chars": len(cand), "base": len(base)},
        "sub_sections_missing": missing_secs,
        "passed": v["passed"] and size_ok and not missing_secs,
    }


def main():
    block = load_block()
    catalog = load_catalog()
    cat = catalog_text(catalog)
    print(
        f"Target: the execution-discipline block — {len(block)} chars, {len(catalog)} tools"
    )

    dspy.configure(lm=dspy.LM(MODEL, num_retries=8, max_tokens=900))

    to_ex = lambda i: dspy.Example(
        task_with_catalog=with_catalog(TRAIN[i][0], cat), tool=TRAIN[i][1]
    ).with_inputs("task_with_catalog")
    trainset = [to_ex(i) for i in range(14)]
    valset = [to_ex(i) for i in range(14, 20)]
    holdout = [
        dspy.Example(task_with_catalog=with_catalog(t, cat), tool=w).with_inputs(
            "task_with_catalog"
        )
        for t, w in HOLDOUT
    ]

    # Baseline accuracy with the UNTOUCHED block.
    base_mod = Selector(block)
    base_hits = sum(fitness(e, base_mod(e.task_with_catalog)) for e in holdout)
    print(f"Baseline selection accuracy: {base_hits}/{len(holdout)}")

    t0 = time.time()
    optimizer = dspy.MIPROv2(metric=fitness, auto="light", num_threads=1)
    optimized = optimizer.compile(Selector(block), trainset=trainset, valset=valset)
    elapsed = time.time() - t0

    evolved = optimized.predictor.predict.signature.instructions
    print(f"\nOptimization: {elapsed:.1f}s, evolved block {len(evolved)} chars")

    hold_mod = Selector(evolved)
    evolved_hits = sum(fitness(e, hold_mod(e.task_with_catalog)) for e in holdout)
    print(f"Evolved selection accuracy: {evolved_hits}/{len(holdout)}")

    g = gates(evolved, block)
    print("\nGates:")
    print(
        f"  frozen_invariants: {'pass' if g['frozen_invariants']['passed'] else 'FAIL ' + json.dumps(g['frozen_invariants'])}"
    )
    print(
        f"  size: {'pass' if g['size']['ok'] else 'FAIL'} ({g['size']['chars']} vs base {g['size']['base']})"
    )
    print(
        f"  sub_sections: {'all 8 survive' if not g['sub_sections_missing'] else 'MISSING ' + ', '.join(g['sub_sections_missing'])}"
    )
    print(f"  OVERALL: {'PASS' if g['passed'] else 'REJECTED'}")

    print("\nTier 3 results")
    print(f"  baseline accuracy : {base_hits}/{len(holdout)}")
    print(f"  evolved accuracy  : {evolved_hits}/{len(holdout)}")
    print(f"  change            : {evolved_hits - base_hits:+d}")
    print(f"  block size        : {len(block)} -> {len(evolved)} chars")
    print(f"  time              : {elapsed:.1f}s")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "baseline_block.txt").write_text(block, encoding="utf-8")
    (OUT_DIR / "evolved_block.txt").write_text(evolved, encoding="utf-8")
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(
            {
                "target": "execution-discipline block",
                "iterations": 4,
                "model": MODEL,
                "holdout_baseline": base_hits,
                "holdout_size": len(holdout),
                "holdout_evolved": evolved_hits,
                "change": evolved_hits - base_hits,
                "baseline_chars": len(block),
                "evolved_chars": len(evolved),
                "gates": {k: v for k, v in g.items() if k != "frozen_invariants"}
                | {"frozen_passed": g["frozen_invariants"]["passed"]},
                "constraints_passed": g["passed"],
                "elapsed_seconds": round(elapsed, 1),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"Saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
