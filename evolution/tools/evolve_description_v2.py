"""Tier 2 (corrected) — tool-description evolution.

Design fix over the first Tier 2 attempt: the selector's prompt is FIXED and
neutral; only the target tool's DESCRIPTION varies inside the catalog. The
mutation is a reflective LLM rewrite (why the baseline failed the train tasks),
so the evolved artifact is genuinely a better description — deployable into the
fork's tool schema without corrupting the catalog.

Loop: hill-climb on a train set's failures, select on a val set, report on a
holdout the optimizer never saw.
"""

import json, os, time
from pathlib import Path

import dspy
from openai import OpenAI

TOOLS_FILE = Path(r"D:/dev/caches/temp/opencode/hermes-tool-descriptions.json")
TARGET = "search_files"
OUT_DIR = Path("output") / "tool-descriptions-v2" / time.strftime("%Y%m%d_%H%M%S")
MODEL = "openai/gpt-4.1-mini"
MAX_CANDIDATE_CHARS = 900  # a description, not an essay
GENERATIONS = 4

NEUTRAL_PROMPT = (
    "You are a tool selector. Given a task and a catalog of every available tool, "
    "pick the single best tool name for the task. Reply with ONLY the exact tool name."
)

# Train tasks (the mutation feedback): mixed confusable cluster.
TRAIN = [
    (
        "Find every file in this repo that references the RPC trigger_run_repair.",
        "search_files",
        True,
    ),
    (
        "Read the file src/lib/supabase.ts and quote its first 20 lines verbatim.",
        "read_file",
        False,
    ),
    (
        "Search the web for the current Vercel AI Gateway pricing page.",
        "web_search",
        False,
    ),
    ("Run the test suite in this repo and report the pass count.", "terminal", False),
    (
        "Grep for 'exposed_schemas' across the engine's supabase directory.",
        "search_files",
        True,
    ),
    (
        "Pull the contents of https://vercel.com/docs/ai-gateway/trace-drains as markdown.",
        "web_extract",
        False,
    ),
    (
        "List the files under .cache/remotes without reading their contents.",
        "search_files",
        True,
    ),
    (
        "Compute the SHA-256 of this JSON blob inside the agent process.",
        "execute_code",
        False,
    ),
    ("Find every TODO comment mentioning the AGPL licence.", "search_files", True),
    ("Apply this exact diff to src/lib/models.ts.", "patch", False),
    (
        "Locate every migration file that alters engine.knowledge_chunks.",
        "search_files",
        True,
    ),
    ("Write the refreshed index to .cache/index.json.", "write_file", False),
    (
        "Find where the graph index endpoint is implemented in this workspace.",
        "search_files",
        True,
    ),
    ("Run git log -S 'match_knowledge_chunks' in the engine repo.", "terminal", False),
    ("Quote the YAML frontmatter of the graph-navigate skill.", "read_file", False),
    (
        "Search the repo for every file that shadows a stdlib module name.",
        "search_files",
        True,
    ),
    (
        "Deploy the edge functions with the CLI and report the result.",
        "terminal",
        False,
    ),
    (
        "Find where the claim gate is judged in the rebuild's engine.",
        "search_files",
        True,
    ),
    ("Rewrite src/lib/render.ts to split the render function.", "write_file", False),
    ("Fetch the AI SDK spend-report docs page and summarise it.", "web_extract", False),
]

# Holdout (never seen by the mutation): the report set.
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

KEY_FACTS = ["search", "file"]


def load_catalog():
    rows = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
    return {r["name"]: (r["description"] or "") for r in rows}


def catalog_text(catalog, target_desc):
    return "\n".join(
        f"- {n}: {target_desc if n == TARGET else d}"
        for n, d in sorted(catalog.items())
    )


def evaluate(client, catalog, target_desc, tasks):
    """Selection accuracy: the model picks one tool per task, given the catalog."""
    dspy.configure(lm=dspy.LM(MODEL, num_retries=8, max_tokens=700))
    mod = dspy.ChainOfThought(
        dspy.Signature("task_with_catalog -> tool", instructions=NEUTRAL_PROMPT)
    )
    hits, misses = 0, []
    text = catalog_text(catalog, target_desc)
    for task, want, *is_target in tasks:
        pred = mod(
            task_with_catalog=f"{task}\n\nAVAILABLE TOOLS (reply with exactly one name):\n{text}"
        )
        got = (getattr(pred, "tool", "") or "").strip()
        if want in got:
            hits += 1
        elif len(tasks) <= 20 or is_target and is_target[0]:
            misses.append((task, want, got))
    return hits, misses


def mutate(client, desc, misses):
    """Reflective rewrite: why the selector failed; fix the description."""
    missed = "\n".join(
        f"- task: {t!r} | picked: {g or 'nothing'} (should be {w})"
        for t, w, g in misses[:8]
    )
    prompt = (
        "You are writing the DESCRIPTION of the `search_files` tool — the text an agent "
        "reads when deciding whether to use it. It must describe ONLY what the tool does: "
        "searching LOCAL FILE CONTENTS by substring/regex across a working tree.\n\n"
        f"Current description:\n{desc}\n\n"
        "The tool selector mis-picked on these tasks:\n"
        f"{missed}\n\n"
        "Rewrite the description so an agent reading it picks `search_files` for local "
        "file-content search tasks and NOT for web search, web page fetching, terminal "
        "commands, code execution, or file edits. Keep it under "
        f"{MAX_CANDIDATE_CHARS} characters. Reply with ONLY the description text."
    )
    r = client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=1200
    )
    return (r.choices[0].message.content or "").strip().strip("`")


def main():
    key = os.environ.get("VERCEL_AIGATEWAY_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("no gateway key in env")
    client = OpenAI(api_key=key, base_url="https://ai-gateway.vercel.sh/v1", timeout=90)

    catalog = load_catalog()
    baseline = catalog[TARGET]
    print(
        f"Target: {TARGET} — baseline {len(baseline)} chars | catalog: {len(catalog)} tools"
    )

    t0 = time.time()
    best_desc, best_hits = baseline, None
    history = []

    for gen in range(GENERATIONS):
        hits, misses = evaluate(client, catalog, best_desc, TRAIN)
        print(f"\nGeneration {gen + 1}: train {hits}/{len(TRAIN)}")
        cand = mutate(client, best_desc, misses)
        if (
            not cand
            or len(cand) > MAX_CANDIDATE_CHARS
            or not all(k in cand.lower() for k in KEY_FACTS)
        ):
            print("  candidate rejected by gates")
            history.append({"gen": gen + 1, "train": hits, "accepted": False})
            continue
        cand_hits, _ = evaluate(client, catalog, cand, TRAIN)
        print(f"  candidate: {len(cand)} chars, train {cand_hits}/{len(TRAIN)}")
        history.append(
            {
                "gen": gen + 1,
                "train": hits,
                "cand_train": cand_hits,
                "accepted": cand_hits >= hits,
            }
        )
        if cand_hits >= hits:
            best_desc, best_hits = cand, cand_hits
            print("  accepted (improved or equal)")
        else:
            print("  rejected (worse on train)")

    elapsed = time.time() - t0
    val_hits, _ = evaluate(client, catalog, best_desc, TRAIN)
    hold_hits, hold_misses = evaluate(client, catalog, best_desc, HOLDOUT)
    base_hold, _ = evaluate(client, catalog, baseline, HOLDOUT)

    print("\n=== RESULT ===")
    print(f"  holdout baseline : {base_hold}/{len(HOLDOUT)}")
    print(f"  holdout evolved  : {hold_hits}/{len(HOLDOUT)}")
    print(f"  change           : {hold_hits - base_hold:+d}")
    print(f"  description      : {len(baseline)} -> {len(best_desc)} chars")
    print(f"  time             : {elapsed:.1f}s")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "baseline_description.txt").write_text(baseline, encoding="utf-8")
    (OUT_DIR / "evolved_description.txt").write_text(best_desc, encoding="utf-8")
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(
            {
                "target": TARGET,
                "generations": GENERATIONS,
                "model": MODEL,
                "holdout_baseline": base_hold,
                "holdout_size": len(HOLDOUT),
                "holdout_evolved": hold_hits,
                "change": hold_hits - base_hold,
                "baseline_chars": len(baseline),
                "evolved_chars": len(best_desc),
                "elapsed_seconds": round(elapsed, 1),
                "history": history,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"Saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
