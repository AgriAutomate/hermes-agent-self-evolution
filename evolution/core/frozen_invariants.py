"""The frozen-invariant gate — the Tier 3 prerequisite.

Before any prompt / AGENTS.md / governance-text mutation can be accepted, this
gate treats the AA-Core frozen identifiers and the canonical field names as
IMMUTABLE inputs:

- every frozen name present in the BASELINE must still be present in the
  candidate (no rename, no alias, no removal);
- retired names must never be (re)introduced;
- the rail sentences that carry the governance intent must survive verbatim
  (a variant may tighten wording around them, never delete the constraint).

A candidate failing any check is rejected before the loop can accept it —
an evolver that "improves" a rail would otherwise silently delete governance.
"""

import json

FROZEN_SUBSTRATE_FIELDS = [
    "conexus_bundle",
    "_formula_ref",
    "report_provenance",
    "evidence_hash",
    "rule_registry",
    "nexus_contract_version",
]

FROZEN_MODULE_IDS = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]

# The retired canonical name (FBA/SWIF Block C1, June 17 2026): reintroducing it
# is a canonical-name violation, not a style choice.
RETIRED_NAMES = ["chemical_records_kept"]
CANONICAL_REPLACEMENTS = {"chemical_records_kept": "fertiliser_records_kept"}

# The rail sentences: the governance intent, matched as substrings (normalized
# whitespace) so a variant that deletes or rewords them away is rejected.
RAIL_SENTENCES = [
    "CONEXUS substrate field names are FROZEN",
    "Per-conversation prompt caching is sacred",
    "The core is a narrow waist",
    "feature branches only",
]

# Persona registry SOT tables + boundary rules that must survive.
FROZEN_TABLES = ["ZONE_ACTIVATION_BY_AREA", "ZONE_PERSONA_MAP", "PERSONA_REGISTRY"]


def _normalized(text: str) -> str:
    return " ".join(text.split()).lower()


def frozen_names_missing(baseline: str, candidate: str) -> list:
    """Frozen identifiers present in the baseline but absent from the candidate."""
    missing = []
    for name in FROZEN_SUBSTRATE_FIELDS + FROZEN_MODULE_IDS + FROZEN_TABLES:
        if name in baseline and name not in candidate:
            missing.append(name)
    return missing


def retired_names_introduced(baseline: str, candidate: str) -> list:
    """Retired canonical names appearing in the candidate but not the baseline."""
    introduced = []
    for name in RETIRED_NAMES:
        if name in candidate and name not in baseline:
            introduced.append(name)
    return introduced


def rails_missing(baseline: str, candidate: str) -> list:
    """Rail sentences present in the baseline whose normalized form is gone."""
    b, c = _normalized(baseline), _normalized(candidate)
    return [
        rail
        for rail in RAIL_SENTENCES
        if _normalized(rail) in b and _normalized(rail) not in c
    ]


def check(baseline: str, candidate: str) -> dict:
    """The full frozen-invariant verdict. passed=True means the candidate may
    proceed to the other gates; passed=False means it is rejected outright."""
    verdict = {
        "frozen_missing": frozen_names_missing(baseline, candidate),
        "retired_introduced": retired_names_introduced(baseline, candidate),
        "rails_missing": rails_missing(baseline, candidate),
    }
    verdict["passed"] = not (
        verdict["frozen_missing"]
        or verdict["retired_introduced"]
        or verdict["rails_missing"]
    )
    return verdict


if __name__ == "__main__":
    demo_baseline = (
        "AA-Core invariants: conexus_bundle, _formula_ref, report_provenance, evidence_hash, "
        "rule_registry, nexus_contract_version and the module identifiers M1..M8 are frozen. "
        "CONEXUS substrate field names are FROZEN. Per-conversation prompt caching is sacred. "
        "The core is a narrow waist. feature branches only. ZONE_ACTIVATION_BY_AREA is the SOT. "
        "fertiliser_records_kept is canonical."
    )
    good = demo_baseline.replace("use for", "use for")  # unchanged
    bad_remove = demo_baseline.replace("rule_registry, ", "").replace("M5, ", "")
    bad_retired = demo_baseline + " chemical_records_kept is the field name."
    bad_rail = demo_baseline.replace("CONEXUS substrate field names are FROZEN. ", "")
    for label, cand in (
        ("unchanged", good),
        ("removes frozen names", bad_remove),
        ("reintroduces retired name", bad_retired),
        ("deletes a rail", bad_rail),
    ):
        v = check(demo_baseline, cand)
        print(
            f"{label}: passed={v['passed']} {json.dumps({k: v[k] for k in v if k != 'passed'})}"
        )

import json  # noqa: E402
