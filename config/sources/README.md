# config/sources/

One YAML per external source: id, name, adapter kind, URL, trust tier and
minimum call interval. Adding a provider is a file here, never code —
unless it needs a new `kind`, which is a reviewed framework change
(`src/mios/ingestion/adapters/`).

Secrets never appear here. A URL or header may reference `${ENV_VAR}`;
`mios.cli.resolve_sources` expands it, and a source whose variable is unset
is **disabled and reported as a data gap** rather than silently skipped.

Tiers (`src/mios/common/labels.py::SourceTier`):

| Tier | Meaning |
|---|---|
| 1 | The agency or central bank that publishes the number (BLS, BEA, Census, DOL, Federal Reserve, US Treasury, BOJ, e-Stat, MOF) |
| 2 | A redistributor of official or market data (e.g. Twelve Data, ADR-011) |
| 3 | Major financial media (Reuters, Bloomberg, WSJ, Nikkei) |
| 4 | Other media and commentary — never a primary datum |

A Tier 3/4 report of a figure never overrides the Tier 1 print of it.
