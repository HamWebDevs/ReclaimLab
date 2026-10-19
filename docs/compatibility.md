# Version 1 contracts and migration

[Back to ReclaimLab](../README.md)

ReclaimLab 1.0.0 establishes supported contracts for the 1.x series:

| Surface | Contract |
| --- | --- |
| Python/runtime | Python 3.10+, zero runtime dependencies, local operation and no automatic uploads/tuning. |
| Platforms | Native recording on Windows/Linux; offline analysis/reports on Windows/Linux/macOS. |
| Native trace | Schema 1 JSONL, explicit completeness/unknown values and documented units. |
| Experiments | Schema 1 native/network protocols, paired-run resampling, retained incompatible evidence and descriptive confidence language. |
| HAR imports | HAR 1.2 allowlisted measurements; explicit multi-page scope and unknown coverage. |
| Bundles | Network-bundle format 1, bounded canonical fields/checksums, frozen evidence and fresh reanalysis. |
| JSON reports | Documented existing meanings remain; additive fields are permitted. Consumers should ignore unknown fields. |
| DevPocket | Five read-only entry points using SDK API v1. Optional cache fields are omitted on older API v1 hosts. |

CLI command meanings, documented units and file-schema versions remain stable within 1.x. Text/HTML layout, internal Python modules and cache bytes are not public APIs. A new required file format or removal of a supported CLI option requires a documented migration and a new major release. Fixes can reject malformed/unsafe inputs and correct analysis; archived bundle evidence is never silently changed to fit a newer calculation.

All file readers reject nonfinite numeric values and bound integer literals to 128 digits/floating literals to 256 characters before conversion, including on Python 3.10. These limits exceed the supported measurement ranges and prevent oversized numeric input from consuming unbounded conversion work.

## Upgrade from 0.x

Existing schema-1 traces/protocols and HAR workflows remain usable. Keep original private traces/HARs if you need full source context; bundle export intentionally withholds descriptions and source identities. Verify a new bundle before sharing it. Older hosts do not gain new bundle commands automatically; install the v1 package to use the format-v1 reader/exporter.

`analyze`, `compare` and native `study` are descriptive workflows; their successful execution is not an automatic performance gate. `har` enforces configured budgets, `network-study` enforces comparability/configured growth gates, and `bundle verify` enforces integrity plus those frozen/reapplied gates. See the command-specific guides for exact exit statuses. No command promises a speedup, diagnosis, independent runs or proof of causality.

Standalone installation never imports or requires DevPocket. Existing four plugin names remain unchanged; `reclaimlab-bundle` is additive. Installed integration CI uses DevPocket 1.x, including a configuration preflight, all five plugins, content invalidation, project/workspace checks, SARIF and MCP. API v1 host compatibility does not imply every old dependency bound accepts a 1.x package; maintainers should verify and update package metadata explicitly.

Each release is built/tested, installs its wheel outside the source checkout, and includes a wheel, source archive and SHA-256 manifest. Packages are published as [GitHub release assets](https://github.com/HamWebDevs/ReclaimLab/releases), not PyPI. See [methodology](methodology.md), [security](../SECURITY.md) and [contributing](../CONTRIBUTING.md).
