# Changelog

## 1.2.0 — 2026-10-21

- Add `har-assets` and a labelled synthetic demo to rank captured assets by per-request response-body bytes and exported HTTP duration, with resource-kind filters and explicit detail limits.
- Enforce individual asset-size/duration budgets over all selected records, retain known lower bounds and refuse passing evidence from missing measurements, timing inconsistencies, selected request errors or empty selections.
- Preserve private aliases, discard URLs/headers/bodies, keep whole-capture/page/kind scope explicit, and distinguish known budget overages from unknown coverage.
- Add the seventh read-only DevPocket API v1 plugin, `reclaimlab-har-assets`, with compact JSON/SARIF/MCP evidence, complete-HAR opt-in caching and unsuppressible budget outcomes.
- Extend CLI, privacy, scope, gate, wheel and installed-plugin checks. Keep schema-1 traces/protocols, bundle format 1 and all existing report interfaces unchanged.

## 1.1.1 — 2026-10-20

- Clarify local-first performance evidence and improve discoverable package metadata for HAR and offline-report use cases.
- Update the README's DevPocket integration examples to list all six currently shipped read-only plugins instead of the older three-plugin wording.
- Add a repository-description/topic checklist and cross-project discovery guidance; preserve all 1.1 file formats, metrics and CLI behaviour.

## 1.1.0 — 2026-10-19

- Add `har-compare` for descriptive before/after saved-browser captures: request/error counts, complete response-body sizes and response-wait p95, with unknown dependent deltas retained.
- Match route groups by full origin, method and encoded path across reordered captures. Aggregate query variants explicitly and discard private matching keys from reports; aliases remain the default.
- Add an offline responsive comparison report with search, state filters, pagination, sorting, route details, fixed capture totals and explicit measurement limits.
- Add the sixth optional read-only DevPocket API v1 plugin with compact evidence and opt-in caching that declares both HAR files.
- Extend CLI/privacy/bounds tests, installed six-plugin cache/SARIF/MCP checks and real-browser desktop/mobile QA. Existing schema-1 files and bundle format 1 remain unchanged.

## 1.0.0 — 2026-10-19

- Establish supported 1.x file/CLI meanings, platform boundaries and SDK API v1 integration contracts, with an explicit upgrade guide.
- Add portable format-v1 browser-experiment bundles with allowlisted measurements, withheld descriptions/URLs/private HAR fields/browser identities, shifted dates, canonical members and SHA-256 inventory checks.
- Refuse export if transformation changes paired measurements, audit blockers, uncertainty or gates; retain unknowns, request errors, synthetic mixing and capture-order problems honestly.
- Verify bundle structure/checksums and reanalyse entirely in memory without extraction, temporary capture files, target execution or uploads. Compare a frozen evidence contract independently of report presentation fields.
- Add `bundle create`, `bundle verify`, fresh budget overrides, verified report metadata and the fifth read-only DevPocket plugin. One archive is a complete declared cache input; invalid integrity or unknown/failed gates cannot be suppressed by baselines.
- Bound compressed/decompressed bytes, members, JSON depth/keys, capture windows and metadata; refuse traversal, duplicate names, special files, unexpected fields and unsupported ZIP envelopes.
- Add a frozen format-v1 fixture, privacy/tamper/compatibility tests, installed five-plugin CI and desktop/mobile Chromium checks for verified-bundle reports. Preserve zero runtime dependencies and all existing native/HAR workflows.

## 0.4.0 — 2026-10-19

- Add balanced, seeded repeated browser-HAR protocols, read-only next-export guidance and a complete synthetic experiment demo.
- Compare response-wait p95, captured response-body bytes, HTTP request counts or HTTP span using equal whole-pair weights and a seeded descriptive paired bootstrap.
- Audit every planned capture for coverage, request failures, timing consistency, copied measurement payloads, browser metadata, chronological order, overlap and synthetic mixing. Incompatible/insufficient evidence blocks aggregation.
- Add conservative optional growth gates: intervals and both capture-order means must satisfy the budget; unresolved evidence returns unknown and cannot pass CI.
- Add an offline responsive experiment report with pair filters, delta charts, capture audit details, stable study totals and explicit limits of manual HAR evidence.
- Discard private network fields, absolute timestamps and internal signatures from results. Bound protocol/total/per-HAR reads, refuse unsafe paths and observed mutations, and preserve exclusive output writes.
- Add the fourth read-only API v1 DevPocket plugin, optional complete-input caching, MCP/SARIF integration and a combined build/network workspace verification using DevPocket 0.6.
- Extend installed-wheel cross-platform smoke checks and real-Chromium desktop/mobile report QA. No runtime dependencies, browser automation, uploads or automatic tuning are added to the package.

## 0.3.0 — 2026-10-18

- Add offline HAR 1.2 analysis with explicit page scoping, interval-union busy time, request concurrency, response-wait p95, size coverage and query-sensitive repeated GET groups.
- Add private-by-default exports: origin/request aliases and allowlisted measurements; discard headers, cookies, bodies, queries, userinfo and absolute timestamps. Origin/path labels require explicit opt-in.
- Add `har` request/body/wait/error budgets with pass/fail/unknown results; missing or inconsistent measurements cannot pass verification. Preserve zero values and avoid TLS/connect double counting.
- Add a self-contained network report with searchable, paginated waterfalls, error/origin/type filters, time windows, detailed timings and honest scope/coverage explanations.
- Add `har-demo`, the optional read-only `reclaimlab-har` DevPocket plugin and a combined web-build/network CI configuration.
- Validate bounded inputs and package the network report template for installed-wheel use on Windows, Linux and macOS.

## 0.2.0 — 2026-10-18

- Add verified GitHub release builds with wheels, source distributions, versioned tags and SHA-256 checksums.
- Balanced seeded crossover plans, guided next-capture inspection and explicit planned recording.
- Protocol/pair/condition stamps, workload/duration/schedule checks, per-run sample digests and reused-observation detection.
- Whole-pair bootstrap analysis with equal pair weights, directional consistency gates and order-effect context.
- Complete audits retain missing/incompatible pairs and block aggregate conclusions rather than silently dropping them.
- Offline interactive study reports, chart modes, attention filtering and a complete synthetic study demo.
- Add the `reclaimlab-study` DevPocket API v1 plugin with structured quality gates and MCP exposure.
- Opt both plugins into DevPocket 0.4 caching while retaining uncached compatibility with host 0.3.
- Shared pair compatibility assessment, stricter trace header/stamp validation and bounded study input handling.

## 0.1.0 — 2026-10-18

- Native Windows/Linux flight recording with independent timer wake-delay observations.
- Bounded, validated JSONL traces, optional process evidence and interactive markers.
- Transparent CPU/memory/storage/thermal overlap rules and recorder-quality flags.
- Duration-weighted summaries, explicit missing-counter coverage and selected-window analysis.
- Reproducible before/after block-bootstrap comparisons with compatibility gates.
- Offline interactive HTML reports with bounded chart geometry and inert imported data.
- Clearly labelled synthetic demos and optional DevPocket API v1 integration.
- Tests for counter maths, native capture, report interactions, trace boundaries and experiment limitations.
