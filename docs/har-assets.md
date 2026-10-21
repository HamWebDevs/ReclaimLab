# Individual captured-asset evidence

[Back to ReclaimLab](../README.md) · [Browser network lab](browser-network.md) · [DevPocket integration](devpocket.md)

```bash
reclaimlab har-assets page.har --max-asset-kib 256 --max-duration-ms 1000 --json
reclaimlab har-assets page.har --kind script --kind style --top 10
reclaimlab har-assets-demo --max-asset-kib 512 --max-duration-ms 1000
```

`har-assets` reads a saved HAR 1.2 and returns per-request size/duration rankings, coverage, resource-kind summaries and optional budgets. It makes no network requests and does not execute or replay resources. The demo is synthetic and labelled as such.

Default kinds are scripts, styles, images, fonts and media, derived from captured response MIME metadata. Repeat `--kind` to choose from `document`, `script`, `style`, `image`, `font`, `media`, `data` and `other`. Requests outside those kinds are counted explicitly and do not affect selected budgets. Error pages may have a different MIME kind from the resource requested: this tool is not a whole-page error gate. Use `har --max-errors 0` alongside it when that is required.

## Measurements and gates

| Option | Measurement and policy |
| --- | --- |
| `--max-asset-kib` | Maximum captured `response.bodySize` across selected request records, divided by 1,024. |
| `--max-duration-ms` | Maximum exported request duration across selected records with consistent timing evidence. |
| `--page` | Explicit one-based page selection for multi-page exports. |
| `--top` | 1–50 details per largest/slowest list; default 20. Every selected request still affects totals and budgets. |

Equality passes a complete budget. Zero is a known measurement; missing/-1 remains unknown. A known maximum over the limit fails even when other records are incomplete. Otherwise a missing required measurement, inconsistent required timing, selected status 0/HTTP error or empty selection makes that budget unknown. Both fail and unknown return status 1. Invalid input/policy returns 2; no requested budgets returns 0 with `not evaluated`.

`known_max_body_bytes` and `known_max_duration_ms` retain observed lower bounds; the corresponding complete maxima become null when required measurements are missing/inconsistent. The budget's `measured` is null when certification is incomplete, even if its `known_maximum` proves an overage. A duration inconsistency does not invalidate an otherwise complete body-size measurement. Request errors prevent both budgets from certifying a pass.

These are individual captured HTTP records, including repeated requests. They are not decoded asset-memory estimates, guaranteed wire-transfer sizes, rendering times or a page-speed score. Filtering/incomplete exports do not establish whole-page coverage. Use repeated network studies for uncertainty-aware before/after growth comparisons.

## Privacy and limits

Only the existing HAR allowlisted measurements enter results. Request/origin aliases remain the default and this interface has no URL-label opt-in. Headers, cookies, bodies, query/userinfo/path URLs, absolute timestamps, initiators and page descriptions are discarded. Alias numbers identify records only within this capture.

The existing 32 MiB HAR, 5,000-entry, 100-page and 256-origin limits apply. Explicit regular-file inputs reject symlinks and redirected directories. Work on stable saved exports. Compact lists contain at most 50 entries each and every omission is counted. No HTML interface is added or changed by this command.

## DevPocket

Install ReclaimLab and DevPocket in the same environment, enable the plugin, then use it explicitly (Bash quoting shown):

```bash
devpocket plugins enable reclaimlab-har-assets
devpocket run reclaimlab-har-assets --input '{"capture":"page.har","max_asset_kib":256,"max_duration_ms":1000}' --format sarif
devpocket serve --root /absolute/project --plugin reclaimlab-har-assets
```

For project/workspace checks:

```json
{
  "version": 1,
  "plugins": ["reclaimlab-har-assets"],
  "checks": {
    "asset-evidence": {
      "tool": "reclaimlab-har-assets",
      "input": {"capture": "page.har", "max_asset_kib": 256, "max_duration_ms": 1000},
      "cache": {"inputs": ["page.har"], "env": []}
    }
  }
}
```

One HAR is the complete file input for opt-in caching. Failed/unknown requested budgets return a nonzero operational result that finding baselines and `--fail-on none` cannot suppress; failed results are not cached as success. Ordinary descriptive warnings follow the host severity policy. MCP remains read-only and requires explicit project enablement plus server exposure. Standalone use has no DevPocket dependency.
