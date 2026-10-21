"""Private per-request asset-size and duration evidence from a saved HAR."""
from __future__ import annotations

import math
from pathlib import Path

from . import har

KINDS = ("document", "script", "style", "image", "font", "media", "data", "other")
DEFAULT_KINDS = ("script", "style", "image", "font", "media")
INTERPRETATION = (
    "Budgets cover individual captured HTTP request records of the selected MIME-derived kinds, not whole-page performance. "
    "Body bytes are the HAR response-body measurement, not decoded memory or a guaranteed wire-transfer size. "
    "Request duration is exported HTTP activity, not rendering time or user input latency. "
    "Aliases do not identify URLs across captures. Missing measurements, request errors and an empty selection cannot certify a budget. "
    "A known over-budget value still fails when other evidence is incomplete."
)


def _summary(rows):
    bodies = [r["body_bytes"] for r in rows if r["body_bytes"] is not None]
    durations = [r["duration_ms"] for r in rows if r["duration_ms"] is not None and not r["timing_mismatch"]]
    return {"requests": len(rows), "body_known_requests": len(bodies), "known_body_bytes": sum(bodies),
            "known_max_body_bytes": max(bodies, default=None),
            "max_body_bytes": max(bodies) if rows and len(bodies) == len(rows) else None,
            "duration_known_requests": len(durations), "known_max_duration_ms": max(durations, default=None),
            "max_duration_ms": max(durations) if rows and len(durations) == len(rows) else None,
            "request_errors": sum(r["status"] == 0 or r["status"] >= 400 for r in rows),
            "timing_mismatches": sum(r["timing_mismatch"] for r in rows)}


def _from_network(network, *, kinds=None, max_asset_kib=None, max_duration_ms=None, top=20):
    selected = list(DEFAULT_KINDS if kinds is None else kinds)
    if not selected or len(selected) > len(KINDS) or any(kind not in KINDS for kind in selected) or len(set(selected)) != len(selected):
        raise ValueError("Asset kinds must be a nonempty unique selection of the documented resource kinds")
    if type(top) is not int or not 1 <= top <= 50:
        raise ValueError("Asset detail limit must be between 1 and 50")
    for value in (max_asset_kib, max_duration_ms):
        if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1e12):
            raise ValueError("Asset budgets must be finite non-negative numbers up to 1e12")
    rows = [row for row in network["requests"] if row["kind"] in selected]
    summary = _summary(rows)
    findings, budgets = [], []
    for metric, limit, observed, complete in (
        ("asset_kib", max_asset_kib, summary["known_max_body_bytes"] / 1024 if summary["known_max_body_bytes"] is not None else None, summary["body_known_requests"] == len(rows)),
        ("duration_ms", max_duration_ms, summary["known_max_duration_ms"], summary["duration_known_requests"] == len(rows)),
    ):
        if limit is None:
            continue
        complete = bool(rows) and complete and not summary["request_errors"]
        state = "fail" if observed is not None and observed > limit else "pass" if complete else "unknown"
        budgets.append({"metric": metric, "limit": limit, "measured": observed if complete else None, "known_maximum": observed, "state": state})
        if state != "pass":
            findings.append({"rule": "har-assets-budget-" + metric.replace("_", "-"), "severity": "error",
                             "message": f"A captured asset exceeds the {metric} budget" if state == "fail" else f"Cannot verify the {metric} budget from the selected capture evidence"})
    if not rows:
        findings.append({"rule": "har-assets-empty", "severity": "warning", "message": "No captured HTTP requests match the selected resource kinds"})
    elif summary["body_known_requests"] != len(rows) or summary["duration_known_requests"] != len(rows):
        findings.append({"rule": "har-assets-coverage", "severity": "warning", "message": "Some selected body-size or duration measurements are missing or inconsistent"})
    if summary["request_errors"]:
        findings.append({"rule": "har-assets-request-errors", "severity": "warning", "message": f"{summary['request_errors']} selected requests have HTTP errors or status 0"})
    verdict = "not evaluated" if not budgets else "budget exceeded" if any(b["state"] == "fail" for b in budgets) else "insufficient data" if any(b["state"] == "unknown" for b in budgets) else "within budgets"

    def details(ordered):
        # All fields are allowlisted from the already-sanitised network model.
        return [{key: row[key] for key in ("id", "label", "origin", "kind", "status", "body_bytes", "duration_ms", "timing_mismatch")} for row in ordered[:top]]

    largest = sorted(rows, key=lambda r: (r["body_bytes"] is None, -(r["body_bytes"] or 0), r["id"]))
    slowest = sorted(rows, key=lambda r: (r["duration_ms"] is None or r["timing_mismatch"], -(r["duration_ms"] or 0), r["id"]))
    return {"schema": 1, "tool": "reclaimlab-har-assets", "synthetic": network["synthetic"],
            "scope": {**network["scope"], "kinds": sorted(selected), "http_requests_in_scope": len(network["requests"]), "requests_outside_selected_kinds": len(network["requests"]) - len(rows)},
            "privacy": network["privacy"], "summary": summary,
            "by_kind": [{"kind": kind, **_summary([row for row in rows if row["kind"] == kind])} for kind in sorted(selected)],
            "largest_assets": details(largest), "slowest_assets": details(slowest), "details_omitted_per_list": max(0, len(rows) - top),
            "budgets": budgets, "verdict": verdict, "exit_code": int(any(b["state"] != "pass" for b in budgets)),
            "findings": findings, "interpretation": INTERPRETATION}


def analyse(data, *, page=None, **options):
    return _from_network(har.analyse(data, page=page), **options)


def load(path, *, page=None, **options):
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Asset HAR input cannot use symlinks or redirected directories")
    return _from_network(har.load(path, page=page), **options)
