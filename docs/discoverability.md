# ReclaimLab positioning and discoverability

[ReclaimLab](../README.md) · [DevPocket integration](devpocket.md) · [Releases](https://github.com/HamWebDevs/ReclaimLab/releases)

ReclaimLab is a **local-first performance evidence toolkit**, not a one-click speed booster. It records supported system scheduling/resource evidence, analyzes saved browser HARs, and compares repeatable experiments with explicit limits. Offline reports and browser/HAR aliases reduce exposure of sensitive data.

## Suggested GitHub About fields

A maintainer must apply these in GitHub **About → gear icon**. This document cannot set repository metadata.

**Description:** `Offline laptop and browser performance analysis: HAR waterfalls, before/after experiments and privacy-first HTML reports.`

**Topics:** `performance-analysis`, `har`, `web-performance`, `browser-devtools`, `python`, `benchmarking`, `performance-testing`, `developer-tools`, `offline-first`, `observability`.

Use accurate topics. Do not claim Core Web Vitals measurement, automatic hardware tuning or a hosted service.

## First-run journeys

1. `reclaimlab demo --output demo.html` creates a **synthetic** offline report, without collecting machine data.
2. Export a browser HAR, then run `reclaimlab har page.har --output page.html`.
3. Compare `reclaimlab har-compare before.har after.har --output comparison.html` for descriptive changes.
4. Use [six optional DevPocket plugins](devpocket.md) to integrate chosen evidence checks into CI.

## Measuring adoption responsibly

Stars, forks and release downloads are only approximate adoption signals. A developer may install directly from source or use a workflow without downloading a release asset. ReclaimLab ships no outbound telemetry. Repository maintainers can inspect recent traffic in **Insights → Traffic**; do not add tracking to privacy-first offline reports.
