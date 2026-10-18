# Changelog

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
