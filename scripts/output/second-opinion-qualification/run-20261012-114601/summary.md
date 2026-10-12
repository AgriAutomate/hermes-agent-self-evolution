# Governor second-opinion qualification

- Second-opinion model: `jev-latest`
- Budget note: CAP-approved 2026-10-12: US$1 / 32 dispatches for governor and skill qualification
- Call cap: 8 | calls used: 3
- Doubtful cases: 3 | resolved: 0 | unresolved: 3 | call failures: 0 | budget refusals: 0

| Fixture | Primary | Reason | Second | Second verdict | Outcome |
| --- | --- | --- | --- | --- | --- |
| converged | explore @0.86 | explore-on-ceiling | explore @0.93 | explore-on-ceiling | unresolved |
| hedged_ceiling | explore @0.85 | explore-on-ceiling | explore @0.95 | explore-on-ceiling | unresolved |
| plateau | explore @0.96 | (mapped cleanly) | - | - | applied |
| steady_improvement | hold @0.73 | hold-on-clean-improvement | hold @0.88 | hold-on-clean-improvement | unresolved |

Generated from report.json in this directory; edit the script, not this file.
