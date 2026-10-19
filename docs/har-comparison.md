# Compare two saved browser captures

[Back to ReclaimLab](../README.md) · [HAR analysis](browser-network.md) · [Repeated experiments](network-studies.md)

Use this when a build changes and you want to see which recorded HTTP route groups appeared, disappeared or changed measurements:

```bash
reclaimlab har-compare before.har after.har --output changes.html --json
reclaimlab har-compare before.har after.har --include-paths --output named-changes.html
reclaimlab har-compare-demo --output synthetic-changes.html
```

Export HAR 1.2 files yourself using your browser's network panel. ReclaimLab reads the saved files offline; it does not capture or replay requests. Choose the same workload and capture scope for a useful comparison. Multi-page exports require explicit one-based `--before-page` and `--after-page` selections. Each file is bounded to 32 MiB and 5,000 entries by the HAR reader.

## What is compared

| Measurement | Meaning |
| --- | --- |
| Requests | Number of selected HTTP requests. |
| Errors | HTTP status 400+ or status 0; not a claim about all application failures. |
| Response-body bytes | Sum of captured HAR body sizes, excluding headers; unknown if any size is missing. Known partial sizes and coverage are retained separately. |
| Response-wait p95 | p95 across captured request wait phases; unknown if a wait is missing or phase timing is inconsistent. This is not page-load time. |

Changes are after minus before. Percentage change is unknown for a zero baseline. Added/removed groups have zero requests/body bytes on the absent side and no wait estimate there. A group marked “same metrics” does not establish identical content.

Matching uses the full origin, HTTP method and encoded path, with normalized host/default port. Request order and truncated report labels are never identities. Query variants are aggregated: `/search?q=a` and `/search?q=b` share a route group. Different methods/origins remain distinct. There can be at most 10,000 groups across both files.

## Privacy and interpretation

Aliases hide origins and paths by default. Private route keys exist only during matching and are discarded, without emitting stable URL hashes. `--include-paths` opts into origin/path labels; it still discards queries, userinfo, headers, cookies, bodies and absolute capture dates. Review labels before sharing: paths can contain private identifiers. Aliases do not guarantee anonymity.

The report is self-contained and makes no network requests. Filters, sort order and pagination change the table while summary totals stay fixed. Route details retain coverage and unknowns. Synthetic examples are prominently marked.

Two manual captures cannot establish a regression, improvement or cause. A complete comparison returns **0**, including growth; invalid input or failed inspection returns **2**. There is no comparison pass/fail budget. Use a [planned repeated network study](network-studies.md) for whole-pair uncertainty and conservative CI growth gates.

## DevPocket

Install both projects in one environment, enable `reclaimlab-har-compare`, then run:

```bash
devpocket run reclaimlab-har-compare --input '{"before":"before.har","after":"after.har"}' --format json
devpocket serve --root /absolute/project --plugin reclaimlab-har-compare
```

The API v1 adapter returns aliases, summary deltas, capture coverage and at most 20 route changes. It never returns the original HAR. An incomplete metric adds a warning; growth alone is not a regression finding. Normal DevPocket severity/baseline policy applies. Declare **both** files when opting into project-check caching:

```json
{
  "version": 1,
  "plugins": ["reclaimlab-har-compare"],
  "checks": {
    "capture-difference": {
      "tool": "reclaimlab-har-compare",
      "input": {"before": "before.har", "after": "after.har"},
      "cache": {"inputs": ["before.har", "after.har"]}
    }
  }
}
```

Optional `before_page`/`after_page` inputs select explicit pages. Path labels are intentionally unavailable through the adapter. Standalone ReclaimLab does not import or require DevPocket.
