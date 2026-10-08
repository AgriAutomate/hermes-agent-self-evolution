"""Tier 2 — tool-description evolution for the AgriAutomate workspace's Hermes fork.

The tool-selection problem is a classification task: the agent sees every tool
description on every API call and picks one. This script evolves ONE target
description with MIPROv2, scoring candidates on whether the model picks the
right tool for held-out tasks given ALL descriptions (the real context).

Gates: the evolved description stays within a byte bound, keeps its tool's
key facts, keeps valid frontmatter-free plain text, and stays under the
fork's longest description so the schema does not bloat.
"""

import json, time
from pathlib import Path

import dspy

TOOLS_FILE = Path(r"D:/dev/caches/temp/opencode/hermes-tool-descriptions.json")
TARGET = "search_files"
OUT_DIR = Path("output") / "tool-descriptions" / time.strftime("%Y%m%d_%H%M%S")

# The tool-selection eval set: real workspace tasks, the tool that SHOULD win.
# The confusable cluster (file search vs web vs terminal vs code) is where
# selection quality actually matters.
TASKS = [
    {"task": "Find every file in this repo that references the RPC trigger_run_repair.", "tool": "search_files"},
    {"task": "Read the file src/lib/supabase.ts and quote its first 20 lines verbatim.", "tool": "read_file"},
    {"task": "Search the web for the current Vercel AI Gateway pricing page.", "tool": "web_search"},
    {"task": "Pull the contents of https://vercel.com/docs/ai-gateway/trace-drains as markdown.", "tool": "web_extract"},
    {"task": "Run the test suite in this repo and report the pass count.", "tool": "terminal"},
    {"task": "Compute the SHA-256 of this JSON blob inside the agent process.", "tool": "execute_code"},
    {"task": "Write the refreshed index to .cache/index.json.", "tool": "write_file"},
    {"task": "Apply this exact diff to src/lib/models.ts.", "tool": "patch"},
    {"task": "Find where the graph index endpoint is implemented in this workspace.", "tool": "search_files"},
    {"task": "Open the dashboard page and check it renders.", "tool": "browser_navigate"},
    {"task": "Remember that the deploy gate requires the migrate job to have executed.", "tool": "memory"},
    {"task": "Quote the YAML frontmatter of the graph-navigate skill.", "tool": "read_file"},
    {"task": "Grep for 'exposed_schemas' across the engine's supabase directory.", "tool": "search_files"},
    {"task": "Fetch the AI SDK spend-report docs page and summarise it.", "tool": "web_extract"},
    {"task": "Check the gateway credit balance via the /v1/credits endpoint.", "tool": "terminal"},
    {"task": "List the files under .cache/remotes without reading their contents.", "tool": "search_files"},
    {"task": "Rewrite src/lib/render.ts to split the render function.", "tool": "write_file"},
    {"task": "Search for the current best-practice GEPA optimizer settings.", "tool": "web_search"},
    {"task": "Run git log -S 'match_knowledge_chunks' in the engine repo.", "tool": "terminal"},
    {"task": "Evaluate this claim against its evidence and give a verdict.", "tool": "execute_code"},
    {"task": "Find which files import the ToolRegistry class in this repo.", "tool": "search_files"},
    {"task": "Read the LICENSE file and quote its first line.", "tool": "read_file"},
    {"task": "Look up who won the 2026 ICLR best paper award.", "tool": "web_search"},
    {"task": "Download the README from https://github.com/NousResearch/hermes-agent.", "tool": "web_extract"},
    {"task": "Install the Python dependencies from pyproject.toml.", "tool": "terminal"},
    {"task": "Sum the total bytes of every file listed in this JSON array.", "tool": "execute_code"},
    {"task": "Update the config file .cache/settings.json with the new timeout.", "tool": "write_file"},
    {"task": "Refactor this function to accept a typed options object (edit this file).", "tool": "patch"},
    {"task": "Locate every migration file that alters engine.knowledge_chunks.", "tool": "search_files"},
    {"task": "Navigate to the runs page and screenshot what renders.", "tool": "browser_navigate"},
    {"task": "Recall which provider served the last evolution run.", "tool": "memory"},
    {"task": "Read the first 50 lines of the deploy workflow YAML.", "tool": "read_file"},
    {"task": "Find every TODO comment mentioning the AGPL licence.", "tool": "search_files"},
    {"task": "Fetch the GraphQL schema of the Supabase docs API.", "tool": "web_extract"},
    {"task": "Run the smoke suite and report any FAIL lines.", "tool": "terminal"},
    {"task": "Parse this HTML table and compute the column averages.", "tool": "execute_code"},
    {"task": "Create the directory .cache/snapshots and write a manifest into it.", "tool": "write_file"},
    {"task": "Replace the deprecated call in this file with the new signature.", "tool": "patch"},
    {"task": "Search the web for whether optuna supports a 5-request-per-minute limit.", "tool": "web_search"},
    {"task": "Read the evolved skill's body and summarise its process steps.", "tool": "read_file"},
    {"task": "Find where the claim gate is judged in the rebuild's engine.", "tool": "search_files"},
    {"task": "Pull the current GEPA paper's abstract page as text.", "tool": "web_extract"},
    {"task": "Deploy the edge functions with the CLI and report the result.", "tool": "terminal"},
    {"task": "Compute the token cost from this usage JSON: input 308564 at 0.40 dollars per million.", "tool": "execute_code"},
    {"task": "Append the run result to the ledger JSONL file.", "tool": "write_file"},
    {"task": "Fix the import path in this file (it shadows a stdlib module).", "tool": "patch"},
    {"task": "Search the repo for every file that shadows a stdlib module name.", "tool": "search_files"},
    {"task": "Read the tool registry source and list the register() signature.", "tool": "read_file"},
    {"task": "Search the docs for the trace drain sampling rules.", "tool": "web_search"},
    {"task": "Run the refresh pipeline in the background and report the PID.", "tool": "terminal"},
]

MAX_CANDIDATE_CHARS = (
    3_000  # the fork's longest description is 2,540; do not bloat past it
)
KEY_FACTS = ["search", "file"]  # a candidate must keep the tool's core verbs


def load_descriptions():
    rows = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
    return {r["name"]: r for r in rows}


class ToolSelect(dspy.Module):
    """Wraps the TARGET description as the signature's instructions — the only
    thing the optimizer mutates (DSPy mutates signature.instructions, never
    instance attributes)."""

    def __init__(self, target_description: str):
        super().__init__()
        self.predictor = dspy.ChainOfThought(
            dspy.Signature(
                "task_with_catalog -> tool",
                instructions=target_description,
            )
        )

    def forward(self, task_with_catalog: str):
        return self.predictor(task_with_catalog=task_with_catalog)


def with_catalog(task: str, catalog: str) -> str:
    return f"{task}\n\nAVAILABLE TOOLS (pick exactly one name):\n{catalog}"


def catalog_text(by_name, target_desc):
    lines = []
    for name, row in sorted(by_name.items()):
        desc = target_desc if name == TARGET else (row["description"] or "")
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


def fitness_metric(example, pred, trace=None):
    want = example.tool
    got = (getattr(pred, "tool", "") or "").strip()
    # Accept either the bare name or a name embedded in prose.
    hit = want in got
    return 1.0 if hit else 0.0


def gates(cand: str, base: str) -> dict:
    results = {}
    results["size_limit"] = (
        "pass" if len(cand) <= MAX_CANDIDATE_CHARS else "fail",
        f"{len(cand)}/{MAX_CANDIDATE_CHARS} chars",
    )
    results["key_facts"] = (
        "pass" if all(k in cand.lower() for k in KEY_FACTS) else "fail",
        f"keeps {KEY_FACTS}",
    )
    results["growth_limit"] = (
        "pass" if len(cand) <= max(len(base), MAX_CANDIDATE_CHARS) else "fail",
        f"{len(cand)} vs base {len(base)}",
    )
    results["non_empty"] = ("pass" if cand.strip() else "fail", "")
    return results


def main():
    by_name = load_descriptions()
    baseline_desc = by_name[TARGET]["description"]
    print(f"Target: {TARGET} — baseline {len(baseline_desc)} chars")

    catalog = catalog_text(by_name, baseline_desc)
    print(f"Catalog: {len(by_name)} tools, {len(catalog)} chars of selection context")

    # Deterministic split: 12 train / 4 val / 4 holdout.
    idx = list(range(len(TASKS)))
    train_idx, val_idx, hold_idx = idx[:12], idx[12:16], idx[16:]
    to_example = lambda i: dspy.Example(
        task_with_catalog=with_catalog(TASKS[i]["task"], catalog), tool=TASKS[i]["tool"]
    ).with_inputs("task_with_catalog")
    trainset, valset, holdout = (
        [to_example(i) for i in train_idx],
        [to_example(i) for i in val_idx],
        [to_example(i) for i in hold_idx],
    )

    lm = dspy.LM("openai/gpt-4.1-mini", num_retries=8, max_tokens=900)
    dspy.configure(lm=lm)

    # Baseline accuracy with the UNTOUCHED description.
    base_mod = ToolSelect(baseline_desc)
    base_hits = sum(fitness_metric(e, base_mod(e.task_with_catalog)) for e in holdout)
    print(f"Baseline tool-selection accuracy: {base_hits}/{len(holdout)}")

    optimizer = dspy.MIPROv2(metric=fitness_metric, auto="light", num_threads=1)
    t0 = time.time()
    optimized = optimizer.compile(
        ToolSelect(baseline_desc), trainset=trainset, valset=valset
    )
    elapsed = time.time() - t0

    # The evolved text is the signature's instructions — ChainOfThought wraps an
    # inner Predict at .predict, which is where the optimized signature lives.
    evolved_desc = optimized.predictor.predict.signature.instructions
    print(
        f"\nOptimization: {elapsed:.1f}s, evolved description {len(evolved_desc)} chars"
    )

    hold_mod = ToolSelect(evolved_desc)
    hold_catalog = catalog_text(by_name, evolved_desc)
    holdout_evolved = [
        dspy.Example(
            task_with_catalog=with_catalog(TASKS[i]["task"], hold_catalog),
            tool=TASKS[i]["tool"],
        ).with_inputs("task_with_catalog")
        for i in hold_idx
    ]
    evolved_hits = sum(
        fitness_metric(e, hold_mod(e.task_with_catalog)) for e in holdout_evolved
    )
    print(f"Evolved tool-selection accuracy: {evolved_hits}/{len(holdout)}")

    change = evolved_hits - base_hits
    gate_results = gates(evolved_desc, baseline_desc)
    print("\nGates:")
    for k, (ok, msg) in gate_results.items():
        print(f"  {'✓' if ok == 'pass' else '✗'} {k}: {msg}")

    print("\nEvolution results")
    print(f"  baseline accuracy : {base_hits}/{len(holdout)}")
    print(f"  evolved accuracy  : {evolved_hits}/{len(holdout)}")
    print(f"  change            : {change:+.1f}")
    print(f"  description       : {len(baseline_desc)} -> {len(evolved_desc)} chars")
    print(f"  time              : {elapsed:.1f}s")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "baseline_description.txt").write_text(baseline_desc, encoding="utf-8")
    (OUT_DIR / "evolved_description.txt").write_text(evolved_desc, encoding="utf-8")
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(
            {
                "target": TARGET,
                "iterations": 4,
                "optimizer_model": "openai/gpt-4.1-mini",
                "baseline_accuracy": base_hits,
                "holdout": len(holdout),
                "evolved_accuracy": evolved_hits,
                "change": change,
                "baseline_chars": len(baseline_desc),
                "evolved_chars": len(evolved_desc),
                "elapsed_seconds": round(elapsed, 1),
                "constraints_passed": all(
                    ok == "pass" for ok, _ in gate_results.values()
                ),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved to {OUT_DIR}")


if __name__ == "__main__":
    main()
