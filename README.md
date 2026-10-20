![ReclaimLab — inspect the slowdown, measure the change](docs/assets/banner.svg)

[![Tests](https://github.com/HamWebDevs/ReclaimLab/actions/workflows/tests.yml/badge.svg)](https://github.com/HamWebDevs/ReclaimLab/actions/workflows/tests.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB)
[![MIT](https://img.shields.io/badge/licence-MIT-8ce8be)](LICENSE)
![Runtime dependencies: zero](https://img.shields.io/badge/runtime_dependencies-zero-8ce8be)

**Find out what slowed down your laptop or web application — with local evidence, not guesswork.** Record a repeatable laptop trace, inspect HAR files, compare before/after browser captures, and share private-by-default offline reports.

**Version 1:** stable file contracts, portable measurement bundles and six optional DevPocket plugins. [Compatibility and upgrading](docs/compatibility.md) · [Bundle format and verification](docs/bundles.md)

Record a slowdown while doing your normal work, inspect saved browser networks, or compare repeated baseline/candidate HAR exports. See native scheduling/resource evidence, explore HTTP waterfalls and gate captured metric growth using whole paired runs. Share self-contained offline reports and connect the evidence to DevPocket checks.

No account, background service, automatic tuning, telemetry or runtime dependencies. Capture supports **Windows and Linux**; analysis and reports also work on macOS.

[Repository positioning and discovery](docs/discoverability.md) · [Latest releases](https://github.com/HamWebDevs/ReclaimLab/releases) · [Quick start](#quick-start) · [Browser network lab](docs/browser-network.md) · [Browser experiments](docs/network-studies.md) · [Laptop studies](docs/studies.md) · [Commands](docs/commands.md) · [DevPocket integration](docs/devpocket.md)

## See what changed between browser captures

```bash
reclaimlab har-compare before.har after.har --output changes.html --json
```

Find added/removed routes and changes in requests, captured body bytes and response waits. Matching survives reordered exports; query variants are grouped explicitly. The offline report provides search, filters, sorting and route details. Private aliases are the default and missing measurements stay unknown. This is a descriptive comparison; use repeated studies for growth gates. [Comparison guide and DevPocket plugin →](docs/har-comparison.md)

## Share evidence without sharing the original HAR

```bash
reclaimlab bundle create trial/network-study.json --max-growth 0 --output experiment.rlb
reclaimlab bundle verify experiment.rlb --output verified-experiment.html
```

One portable file retains selected measurements, paired runs, uncertainty and the growth policy. Original URLs, headers, bodies, descriptions, browser identities and absolute dates are withheld. Verification checks bounded canonical fields and checksums, then reanalyses entirely in memory; it extracts no files and executes no archived code. Stored evidence must match the fresh result.

Use the read-only `reclaimlab-bundle` DevPocket plugin to check it in CI, cache it as one complete file input, or expose it to a coding assistant. Checksums establish internal consistency, not source authenticity or anonymity. [Privacy boundaries, reproducibility and CI →](docs/bundles.md)

## Check whether a web change holds up across runs

```bash
reclaimlab network-study-demo --directory browser-trial --output browser-trial.html
# For your own captures, declare the task, context, primary metric and conditions first.
reclaimlab network-plan --workload "Same dashboard navigation" --browser "Fixed browser/profile" --cache "Fresh cache" --network "Fixed throttling" --output trial/network-study.json
reclaimlab network-next trial/network-study.json
# Apply the displayed condition and export each fresh HAR manually in the planned order.
reclaimlab network-study trial/network-study.json --max-growth 0 --output experiment.html
```

Balanced capture orders, equal pair weights, coverage/error audits and descriptive paired-bootstrap intervals make uncertainty visible. Missing captures, copied measurement payloads, overlapping runs and unknown required metrics cannot pass a configured growth budget. Compare response-wait p95, captured body bytes, request counts or HTTP span. [Protocol, CI gates and interpretation →](docs/network-studies.md)

## Find the next question in a browser network capture

Export a HAR from your browser's developer tools, then:

```bash
reclaimlab har artifacts/page.har --output network.html
reclaimlab har artifacts/page.har --max-body-kib 1024 --max-wait-p95-ms 800 --max-errors 0 --json
reclaimlab har-demo --output synthetic-network.html
```

Filter the offline waterfall by resource type, origin, request errors and time window. Inspect response waits, payload-size coverage, request overlap and repeated GET groups. Reports use request/origin aliases by default and discard headers, cookies, bodies, queries and URL credentials. Opt in to origin/path labels with `--include-paths` when useful locally.

Choose your own budgets. Missing measurements cannot pass verification, TLS is never counted twice, and multi-page exports require explicit page selection. These are captured HTTP measurements, not a page-speed score or Core Web Vitals result. [Metrics, privacy, CI and the working configuration →](docs/browser-network.md)

## Quick start

From a checkout:

```bash
python -m pip install .
reclaimlab doctor
reclaimlab record --seconds 60 --label before --workload "usual browser task" --output before.jsonl
reclaimlab report before.jsonl --output before.html
```

Open `before.html` in your browser. The report works offline and makes no network requests. You can also run directly with `python -m reclaimlab` from this checkout. Python 3.10+ is required. Nothing is published to PyPI; install from this source.

Try the interface without collecting any device data:

```bash
reclaimlab demo --output demo.html
```

Demo data is clearly marked synthetic throughout the report. It is not evidence of a real laptop or a measured speedup.

## Make a change you can actually evaluate

Repeat the same task after changing one thing:

```bash
reclaimlab record --seconds 60 --label after --workload "usual browser task" --output after.jsonl
reclaimlab compare before.jsonl after.jsonl --output experiment.html
```

The comparison checks coarse hardware/platform compatibility, sampling rate, duration, declared workload, power state, trace completeness and recorder overhead. It uses a seeded block bootstrap to describe uncertainty around the difference in p95 timer wake delay. Mismatched or insufficient captures produce **not comparable**, rather than a confident improvement claim.

A lower measured delay does not establish that your attempted change caused it. Repeat captures, keep the task consistent and consider an ABAB crossover. [Read the methodology](docs/methodology.md).

## Test whether a change holds up across runs

ReclaimLab 0.2 plans balanced crossover studies, records each condition with a protocol stamp and compares whole paired runs. It detects reused sample payloads, changed protocols, schedule/order problems and incompatible captures. Missing or bad pairs remain visible in the audit.

```bash
reclaimlab plan --workload "usual browser task" --candidate "Lower video resolution" --output trial/study.json
reclaimlab next trial/study.json
# Apply the displayed condition yourself, then reproduce the task during capture.
reclaimlab next trial/study.json --record
# Repeat next / apply condition / record for every planned capture.
reclaimlab study trial/study.json --output study.html
```

The default is six pairs. Each pair has equal statistical weight; individual timer observations are not treated as independent experimental runs. The offline study report shows paired changes, an order-effect check, descriptive uncertainty and a per-capture audit. A matching stamp is a consistency check, not proof of causation or authenticity. [Protocol, interpretation and limits](docs/studies.md).

Try a complete synthetic study without collecting device data:

```bash
reclaimlab study-demo --directory synthetic-study --output synthetic-study.html
```

## Inside a report

| View | What it gives you |
| --- | --- |
| **Timeline** | Aligned wake-delay, CPU and memory charts; zoom controls; optional markers; evidence cards; capture-quality warnings. |
| **Evidence** | Duration-weighted counter averages and coverage, delay episodes and optional process-name evidence. Missing counters remain unknown. |
| **Experiment** | Before/after metrics, a descriptive bootstrap interval, compatibility blockers and workload-context changes. |

Large timelines retain bucket endpoints and resource/delay extremes for bounded chart geometry. Statistics use the original selected records. Zoom controls change the chart only; the UI states this explicitly. Imported labels/process names are inserted as text, and embedded JSON is escaped to prevent script injection.

## Useful capture options

```bash
# Mark a perceived pause by typing a label and pressing Enter
reclaimlab record --interactive --output marked.jsonl

# Explicitly opt in to names/PIDs and available per-process CPU/RSS evidence
reclaimlab record --processes --output processes.jsonl

# Inspect the sample records around the first exact marker label
reclaimlab analyze marked.jsonl --around "video froze" --radius 5 --json
```

Native process collection is off by default. Native recordings intentionally exclude command lines, window titles, browser history, hostnames, usernames, network addresses and hardware serial numbers. Labels and process names can still be private; review reports before sharing. Saved HAR imports have separate [field-discard and path-label controls](docs/browser-network.md).

## What the measurements mean

- **Timer wake delay** is the Python probe's sleep/scheduling lateness. It is not measured GUI input lag or game frame time.
- **Resource overlap** identifies clues during delayed records. It does not establish a root cause.
- **Low available memory alone** is weaker evidence than low headroom plus observed swap traffic or memory pressure.
- **High temperature alone** does not prove throttling. The Linux backend reports direct counter growth only when that counter is available.
- **Observer overhead** is measured, not assumed negligible. Capture quality flags excessive recorder CPU use and slow sampling.
- **Hardware signatures** are deliberately coarse and non-identifying. Matching signatures do not prove two traces came from the same physical machine.

Linux captures `/proc` CPU/memory, available PSI, swap and block-device counters, plus optional CPU-related thermal counters. Windows uses direct native APIs for CPU, immediately available memory, commit headroom, power status and optional process evidence. Windows PSI, disk-busy and thermal values remain unavailable. [Exact coverage and limits](docs/counters.md).

## Connect it to DevPocket

ReclaimLab includes six optional **DevPocket API v1 plugins**. Install both projects in the same environment, then:

```bash
devpocket plugins enable reclaimlab
devpocket plugins enable reclaimlab-study
devpocket plugins enable reclaimlab-har
devpocket plugins enable reclaimlab-network-study
devpocket plugins enable reclaimlab-bundle
devpocket plugins enable reclaimlab-har-compare
devpocket run reclaimlab --input '{"trace":"before.jsonl"}' --format sarif
devpocket run reclaimlab-study --input '{"manifest":"trial/study.json"}' --format json
devpocket run reclaimlab-har --input '{"capture":"artifacts/page.har","max_errors":0}' --format sarif
devpocket serve --root /absolute/path/to/project --plugin reclaimlab --plugin reclaimlab-study
```

The six plugins read saved traces, studies, HAR captures or portable bundles; they do not start recording or tune the machine. Findings work with DevPocket checks, baselines, SARIF and MCP. Supported read-only checks can use DevPocket's opt-in result caching when every input is declared. Combine HAR gates with DevPocket 0.5's AssetGuard to review built artifacts and captured network activity together. [Integration guide](docs/devpocket.md).

## Development

```bash
python -m unittest discover -s tests -v
```

Tests cover native counter maths, counter reset/PID reuse, trace validation, missing measurements, evidence rules, comparison blockers, reproducible intervals, report injection boundaries and JavaScript interactions. Windows/Linux CI additionally exercises real short native captures. The GitHub matrix covers Python 3.10, 3.12 and 3.14 on Windows, Linux and macOS; macOS live capture is intentionally unsupported.

See [CONTRIBUTING.md](CONTRIBUTING.md), [release packaging](docs/releases.md) and [SECURITY.md](SECURITY.md). Windows 8.1 compatibility has not been verified; use an interpreter supported by your OS. This is a diagnostic project, not a promise that software can overcome every hardware limit.

---

MIT licensed · Built by [HamWebDevs](https://github.com/HamWebDevs)
