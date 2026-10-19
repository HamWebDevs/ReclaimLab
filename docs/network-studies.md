# Repeated browser-network experiments

[Back to ReclaimLab](../README.md) · [Single HAR analysis](browser-network.md) · [DevPocket integration](devpocket.md)

ReclaimLab 0.4 compares a declared browser workload across whole paired HAR exports. Choose a primary captured metric, plan balanced baseline-first/candidate-first runs, export each capture manually, then inspect an offline audit and descriptive uncertainty. No browser is automated, no URLs are fetched and no settings are changed.

## Try a complete demonstration

```bash
reclaimlab network-study-demo --directory synthetic-browser --output synthetic-browser.html
reclaimlab network-study synthetic-browser/network-study.json --max-growth 0 --json
```

The six synthetic pairs illustrate the workflow. They do not measure a real browser or establish a speedup. Every report labels synthetic input.

## Declare the experiment before capturing

```bash
reclaimlab network-plan --workload "Load the same dashboard route" --browser "Chromium, fixed version and profile" --cache "Clear cache before each run" --network "Same fixed throttling preset" --baseline "Current production build" --candidate "Smaller initial module graph" --metric wait_p95_ms --pairs 6 --seed 42 --output trial/network-study.json
reclaimlab network-next trial/network-study.json
```

Apply the displayed condition yourself. Keep the declared browser version, profile, cache preparation, throttling, route and task consistent. Save a **fresh** HAR export at the displayed path, then run `network-next` again. Follow the complete planned order, including condition order within each pair. Do not copy or retimestamp exports. Capture paths are relative to the protocol's directory, and every run needs a distinct `.har` file.

The default is six pairs. Planning accepts 2–20 pairs, but analysis requires at least four complete compatible pairs and both capture orders. `--page NUMBER` fixes one-based page selection for every export; multi-page exports without explicit selection are incompatible. An empty/missing measurement is unknown, never zero.

## Choose one primary metric

| `--metric` | Unit | Required coverage |
| --- | --- | --- |
| `wait_p95_ms` | ms | Every selected HTTP request has a known HAR response-wait phase. This is a within-capture request p95. |
| `body_bytes` | bytes | Every selected HTTP response has a known captured body size. A measured zero, including cached responses, is valid. |
| `requests` | requests | Count of selected HTTP(S) requests. Non-HTTP entries remain outside scope. |
| `span_ms` | ms | First selected HTTP request start to last selected HTTP completion. This is not navigation or rendering duration. |

All metrics require complete request durations for overlap/order auditing, consistent exported timings, and zero captured HTTP statuses ≥400 or status 0. Failed pages cannot become apparent improvements. Differences in request population are flagged as context: a changed wait p95 may describe a different mix, rather than faster identical endpoints.

## Analyze and choose a growth budget

```bash
reclaimlab network-study trial/network-study.json --iterations 2000 --seed 7 --output experiment.html
reclaimlab network-study trial/network-study.json --max-growth 25 --json
```

`--max-growth` uses the primary metric's absolute units. For `wait_p95_ms`, 25 means at most 25 ms candidate-minus-baseline growth; for `body_bytes`, use bytes. The budget must be nonnegative. The protocol fixes the metric; changing it changes the reported protocol hash but cannot prove the choice was made before looking at results.

Each pair contributes one candidate-minus-baseline value with equal weight. A seeded descriptive bootstrap resamples whole paired values; it never treats individual HTTP requests as independent experiments. The report retains every planned pair, shows baseline/candidate summaries, the mean paired delta, relative change where defined, a 95% descriptive interval, and means for both capture-order groups. Filtering the table does not recompute the study result.

| Gate state | Meaning |
| --- | --- |
| `pass` | The interval's upper endpoint and both capture-order mean deltas are within the chosen limit. |
| `fail` | The interval's lower endpoint and both order-group means exceed the limit. |
| `unknown` | Captures are incompatible/insufficient, or the interval/order groups cannot settle the chosen budget. |
| `not requested` | The audit is comparable and no growth budget was configured. Direction remains descriptive. |

CLI status **0** means a complete descriptive analysis with no budget, or a passing configured gate; **1** means incompatible/insufficient evidence or a configured failed/unknown gate; **2** means malformed protocol, invalid options, output collision or tool/resource error; interruption is **130**. Without a growth budget, even consistently higher measurements return 0 after a complete analysis. Use a budget for CI enforcement.

A directional verdict needs an interval entirely on one side of zero, at least 75% of pair deltas in that direction, and agreement from both order-group means. Otherwise it is inconclusive. These are descriptive consistency criteria, not a causal test or a population confidence guarantee.

## Audit and privacy boundaries

- Missing/invalid captures, unknown required metrics and incompatible pairs remain visible and block an aggregate claim; valid pairs are never silently pooled around failures.
- Absolute selected-request timestamps audit chronological order and overlaps, including across pairs. Timestamps are discarded from returned data. Timestamp edits can defeat this check; it is not authentication.
- Allowlisted measurement signatures detect identical payloads even when exports are retimestamped. Identical measurements can arise independently, so this conservative blocker is not proof of fabricated evidence.
- Exported browser name/version, when present, must match across captures; mixed presence is incompatible. If all exports omit browser metadata, the report says so. This consistency check does not verify the manually declared browser or settings.
- Mixed synthetic/measured input blocks comparability. Headers, cookies, bodies, URL paths/queries/userinfo, browser metadata and absolute timestamps never appear in analysis output. User-written experiment descriptions and declared context do appear; review them before sharing.

Manual HAR exports cannot bind captures to a code revision, prove independent runs or establish that a change caused a result. They do not measure Core Web Vitals, GUI latency or perceived responsiveness. Keep native [laptop studies](studies.md) for scheduling/resource experiments.

Inputs are bounded: 256 KiB protocol, 128 MiB total HAR bytes, 32 MiB per HAR, up to 40 captures and the single-HAR entry/page/origin limits. Protocol paths stay beneath their manifest directory; symlinks, nonregular captures, observed mutations and traversal are refused. Reports use exclusive writes, inert escaped JSON, text-only labels, no external assets and no network requests.

## Connect the result to project checks

Install both packages in the same environment and enable `reclaimlab-network-study` explicitly. See the [four-plugin guide](devpocket.md). Cache only with the protocol **and every referenced HAR** declared as inputs. DevPocket 0.6 workspaces can make browser evidence depend on finished-build checks and combine both projects into one SARIF report; neither command automatically builds or captures the target application.
