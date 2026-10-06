import os, json, sys, time
from pathlib import Path

# Attribution for the evolution loop: every request is tagged with the skill
# and run so the Custom Reporting API can attribute spend per skill.
# Writes cost $0.075 / 1,000 tag/user IDs - negligible at our scale.

sys.path.insert(0, str(Path(__file__).parent))

EVOLUTION_TAGS = {
    "program": "agriautomate-self-evolution",
    "surface": "hermes-agent-self-evolution",
}
BASE_URL = "https://ai-gateway.vercel.sh/v1"
MAX_TAGS = 10


def reporting_headers(skill: str, run_id: str) -> dict:
    """HTTP-header attribution - merged with any body values by the gateway.

    Keeps the pipeline's model-call code untouched: the OpenAI client is
    constructed with these as default_headers. Tags use the documented
    key:value form, capped at 10 tags of 1-64 characters.
    """
    tags = [
        f"skill:{skill}",
        f"program:{EVOLUTION_TAGS['program']}",
        f"run:{run_id}",
    ]
    assert len(tags) <= MAX_TAGS and all(1 <= len(t) <= 64 for t in tags)
    return {
        "ai-reporting-tags": ",".join(tags),
        "ai-reporting-user": EVOLUTION_TAGS["program"],
    }


def reporting_extra_body(skill: str, run_id: str) -> dict:
    """Body-form attribution for OpenAI-compatible calls via extra_body."""
    tags = [f"skill:{skill}", f"program:{EVOLUTION_TAGS['program']}", f"run:{run_id}"]
    return {
        "providerOptions": {
            "gateway": {"user": EVOLUTION_TAGS["program"], "tags": tags}
        }
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True)
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    print(json.dumps(reporting_headers(args.skill, args.run_id), indent=2))
    print(json.dumps(reporting_extra_body(args.skill, args.run_id), indent=2))
