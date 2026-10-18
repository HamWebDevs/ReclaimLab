# Browser network evidence

[Back to ReclaimLab](../README.md) · [DevPocket integration](devpocket.md) · [AssetGuard build budgets](https://github.com/HamWebDevs/DevPocket/blob/main/docs/assetguard.md)

ReclaimLab 0.3 reads saved HAR 1.2 exports from browser developer tools. It produces an offline request waterfall, response-size and wait summaries, capture-quality checks and explicit CI budgets. It never opens the site, replays requests or uploads the capture.

## Start with a capture or a synthetic demo

In Chrome DevTools, record the task in **Network**, then choose **Export HAR (sanitized)**. Other browsers/exporters producing HAR 1.2 can also be used. Review the capture scope, cache state, throttling and any applied filters yourself; HAR cannot prove the export includes every request or a full page load. See the [Chrome export reference](https://developer.chrome.com/docs/devtools/network/reference#save-all-network-requests-to-a-har-file).

```bash
reclaimlab har artifacts/page.har --output network.html
reclaimlab har artifacts/page.har --json
reclaimlab har-demo --output synthetic-network.html
```

Open the HTML locally. Search, filter by resource type/origin/errors, sort by wait/size/duration, select a time window and inspect individual phase measurements. The table shows 50 rows per page. Filters and windows change the visible rows, while summaries and budgets describe the entire selected HAR scope. Synthetic reports are labelled throughout.

Default request/origin aliases keep raw URLs and hostnames out of JSON, HTML and plugin reports. To inspect meaningful resource paths locally:

```bash
reclaimlab har artifacts/page.har --include-paths --output named-network.html
```

This explicitly includes origins and URL paths. Paths may contain names, IDs or path-based credentials. Queries, fragments and URL userinfo remain excluded. Headers, cookies, request/response bodies, page titles, absolute timestamps, connection IP fields and initiator stacks are never copied into reports. Even aliased timings, sizes and request order can be identifying. Review both input and output before sharing. Sanitized browser exports may still contain sensitive data.

## Define budgets for your application

```bash
reclaimlab har artifacts/page.har --max-requests 100 --max-body-kib 1024 --max-wait-p95-ms 800 --max-errors 0 --output network.html
```

The values above are examples, not universal performance targets. No budgets apply by default.

| Option | Metric | Verification requirements |
| --- | --- | --- |
| `--max-requests` | Selected HTTP(S) request count | A valid selected scope. |
| `--max-body-kib` | Sum of recorded response-body bytes, in KiB | Every selected request has a known body size. |
| `--max-wait-p95-ms` | Linearly interpolated p95 of exported HAR `wait` phases | Every selected request has a known wait and no timing mismatch is detected. |
| `--max-errors` | HTTP status 400–599 plus status 0 | Valid status fields for every selected request. |

Each result is `pass`, `fail` or `unknown`. Missing measurements cannot pass a budget that requires them. Partial byte totals are labelled **known** subtotals, with explicit request coverage. A genuine zero, including a recorded zero-byte cached response, stays distinct from missing/-1 data. Budgets apply to captured requests only; an apparently successful export cannot certify unrecorded traffic.

Standalone exit codes are **0** analysis completed and every configured budget passed (or none were configured); **1** at least one configured budget failed or could not be verified; **2** invalid input/tool error; **130** interrupted. An HTTP error is shown diagnostically even when no budget was configured. `--max-errors 0` makes it an explicit standalone gate.

## Keep page scopes separate

A HAR with multiple `log.pages` entries requires an explicit one-based selection:

```bash
reclaimlab har artifacts/multiple-pages.har --page 2 --output second-page.html
```

Only entries whose `pageref` matches that page are included. Entries outside that scope and excluded non-HTTP(S) entries are counted. A file with no page list is an export-wide capture, not an inferred page navigation. Multiple conflicting page references without a page list are rejected.

## Read the metrics precisely

- **Response wait** is the HAR `wait` phase. It is not complete end-to-end TTFB, rendering delay or a Core Web Vitals metric.
- **Captured span** runs from the first selected request start to the last selected request end. It is not page load, LCP or time to interactive.
- **Busy time** is the union of known request intervals; overlapping requests are counted once. **Peak in flight** counts overlapping requests, not sockets or HTTP/2 streams. Unknown durations prevent a complete span/concurrency claim.
- **Idle time** means no captured request was active in that span. It does not establish CPU idleness, a stalled page or wasted time.
- **Response-body bytes** are HAR `response.bodySize`. **Decoded content bytes** use `response.content.size`. **Message bytes** add exported `headersSize` and `bodySize` only when both are known; these are not complete transport/TLS byte counts.
- **TLS** is a subset of HAR `connect`, never an extra additive phase. Inconsistent phase totals or TLS/connect relationships are flagged.
- Timing-total checks tolerate the greater of 1 ms or 2% for exporter rounding. They flag known phase sums above the exported duration, disagreeing fully known sums, and TLS exceeding connect by more than 1 ms.
- **Repeated GET groups** use the exact URL identity, including its query and userinfo but excluding fragments, only in memory. Raw URLs and identity hashes are not published. Repeats are not proof of wasted bytes or unsafe caching: authentication, varying headers, application behavior and server policy can matter.

Network evidence complements the native laptop recorder. Correlation between separate HAR and native captures is not automatically established, and neither tool attributes a root cause or causal speedup from one capture.

## Connect build and network checks

Install DevPocket 0.5+ and ReclaimLab in one environment, review the plugin, then use [examples/web-checks.json](../examples/web-checks.json) as a project configuration. Supply your finished `dist` and saved `artifacts/page.har`:

```bash
devpocket plugins enable reclaimlab-har
devpocket run reclaimlab-har --input '{"capture":"artifacts/page.har","max_errors":0}' --format sarif
devpocket check --config examples/web-checks.json --fail-on error --format json
devpocket serve --root /absolute/path/to/project --plugin reclaimlab-har
```

The example config enables the reviewed plugin and combines the build and captured-network budgets. Use its JSON in your application's `.devpocket.json`; the example's paths refer to your application's files. `--fail-on error` gates explicit budgets while retaining warning-level capture-quality and request-error findings. The normal default `warning` gate is stricter. MCP exposure additionally requires enabling the plugin in the root's `.devpocket.json`.

The HAR plugin returns compact private summaries and at most 20 slow-wait rows, preserving coverage and budget results rather than copying the full capture into coding-assistant context. It is read-only and cannot start browser capture, replay requests, record the machine or write reports. Its optional cache contract requires the HAR file in `cache.inputs`; direct runs and MCP calls remain uncached.

## Supported input and limits

HAR 1.2 inputs are bounded to **32 MiB**, **5,000 entries**, **100 pages**, **256 HTTP(S) origins** and a **seven-day selected span**. URL fields are bounded, timestamps require a timezone, numeric values must be finite, byte sizes must be whole numbers and invalid status/method fields are rejected. A symlinked HAR is refused. The parser intentionally accepts missing/-1 measurements as unknown so incomplete captures can still be inspected honestly.

The implementation follows the [HAR 1.2 format](https://www.softwareishard.com/blog/har-12-spec/). It does not consume exporter-specific initiator graphs, Chrome performance traces, WebSocket frames, browser rendering events or server-timing extensions. No critical-path or causal dependency graph is inferred from request overlap.
