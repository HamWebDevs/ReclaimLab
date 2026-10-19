"""Offline HAR 1.2 analysis. Raw request/response material never enters a report."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from .jsonio import loads
from .analysis import quantile

MAX_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 5000
PHASES = ("blocked", "dns", "connect", "send", "wait", "receive")
INTERPRETATION = "This is captured HTTP activity, not a page-speed score, Core Web Vitals measurement, CPU profile or proof of a bottleneck. Overlap counts requests, not connections. Idle gaps only mean no captured request was active. HAR wait is the exported response-wait phase, not full end-to-end TTFB. TLS is already included in connect. Missing measurements remain unknown; filtered/incomplete exports cannot establish whole-page coverage."


def numeric(value, field, maximum=1e15):
    if value is None or value == -1 and type(value) in {int, float}:
        return None
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("Invalid HAR numeric field: " + field)
    return value


def byte_size(value, field):
    value = numeric(value, field, 1e12)
    if value is not None and int(value) != value:
        raise ValueError("HAR byte sizes must be whole numbers")
    return int(value) if value is not None else None


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("HAR entries need an ISO timestamp with a timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError()
        return result.timestamp() * 1000
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError("Invalid HAR timestamp or missing timezone") from exc


def resource_kind(mime):
    if not isinstance(mime, str):
        return "other"
    mime = mime.lower().split(";", 1)[0].strip()
    if mime in {"text/html", "application/xhtml+xml"}:
        return "document"
    if "javascript" in mime or "ecmascript" in mime:
        return "script"
    if mime == "text/css":
        return "style"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("font/") or "font" in mime:
        return "font"
    if mime.startswith(("audio/", "video/")):
        return "media"
    return "data" if "json" in mime or "xml" in mime else "other"


def union_metrics(rows):
    intervals = sorted((r["start_ms"], r["start_ms"] + r["duration_ms"]) for r in rows if r["duration_ms"] is not None and r["duration_ms"] > 0)
    events, busy = [], 0
    left = right = None
    for start, end in intervals:
        events.extend(((start, 1), (end, -1)))
        if left is None:
            left, right = start, end
        elif start <= right:
            right = max(right, end)
        else:
            busy += right - left
            left, right = start, end
    if left is not None:
        busy += right - left
    current = peak = 0
    for _, change in sorted(events):  # Ends precede starts at the same instant.
        current += change
        peak = max(peak, current)
    return round(busy, 3), peak


def analyse(data, *, page=None, include_paths=False, max_requests=None, max_body_kib=None, max_wait_p95_ms=None, max_errors=None):
    if type(include_paths) is not bool:
        raise ValueError("include_paths must be boolean")
    limits = {"requests": max_requests, "body_kib": max_body_kib, "wait_p95_ms": max_wait_p95_ms, "errors": max_errors}
    for key, value in limits.items():
        if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1e12 or key in {"requests", "errors"} and type(value) is not int):
            raise ValueError("Invalid network budget: " + key)
    if not isinstance(data, dict) or not isinstance(data.get("log"), dict) or data["log"].get("version") != "1.2":
        raise ValueError("Expected a HAR 1.2 log")
    log = data["log"]
    entries, pages = log.get("entries"), log.get("pages", [])
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        raise ValueError("HAR must contain 1..5000 entries")
    if not isinstance(pages, list) or len(pages) > 100:
        raise ValueError("HAR page list exceeds the limit or is invalid")
    page_ids = []
    for item in pages:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not 1 <= len(item["id"]) <= 512 or item["id"] in page_ids:
            raise ValueError("HAR page IDs must be nonempty and unique")
        page_ids.append(item["id"])
    if page is not None and (type(page) is not int or not 1 <= page <= len(pages)):
        raise ValueError("Choose a page number from the HAR pages list, starting at 1")
    if len(pages) > 1 and page is None:
        raise ValueError(f"HAR contains {len(pages)} pages; select one with --page NUMBER")
    if not pages and len({entry.get("pageref") for entry in entries if isinstance(entry, dict) and isinstance(entry.get("pageref"), str)}) > 1:
        raise ValueError("Multiple page references have no pages list; export a single-page capture")
    selected = page_ids[page - 1] if page is not None else None
    origins, rows, repeats = {}, [], defaultdict(list)
    skipped_scope = skipped_scheme = mismatches = 0
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError("HAR entry must be an object")
        pageref = entry.get("pageref")
        if pageref is not None and (not isinstance(pageref, str) or page_ids and pageref not in page_ids):
            raise ValueError("HAR entry references an unknown page")
        if selected is not None and pageref != selected:
            skipped_scope += 1
            continue
        request, response, timings = entry.get("request"), entry.get("response"), entry.get("timings", {})
        if not isinstance(request, dict) or not isinstance(response, dict) or not isinstance(timings, dict):
            raise ValueError("HAR entry requires request, response and timing objects")
        raw_url = request.get("url")
        if not isinstance(raw_url, str) or not 1 <= len(raw_url) <= 8192 or any(ord(c) < 32 or ord(c) == 127 for c in raw_url):
            raise ValueError("Invalid HAR request URL")
        try:
            url = urlsplit(raw_url)
            if url.scheme.lower() not in {"https", "http"}:
                skipped_scheme += 1
                continue
            host, port = url.hostname, url.port
            if not host:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("Invalid HAR request origin") from exc
        scheme = url.scheme.lower()
        if port == (443 if scheme == "https" else 80):
            port = None
        origin = scheme + "://" + ("[" + host.lower() + "]" if ":" in host else host.lower()) + (":" + str(port) if port is not None else "")
        origin_id = origins.setdefault(origin, "origin-" + str(len(origins) + 1))
        if len(origins) > 256:
            raise ValueError("HAR exceeds 256 origins; select a smaller capture")
        method = request.get("method")
        if not isinstance(method, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,32}", method):
            raise ValueError("Invalid HAR HTTP method")
        status = response.get("status")
        if type(status) is not int or not 0 <= status <= 599:
            raise ValueError("Invalid HAR response status")
        content = response.get("content", {})
        if not isinstance(content, dict):
            raise ValueError("HAR response content metadata must be an object")
        body = byte_size(response.get("bodySize"), "bodySize")
        headers = byte_size(response.get("headersSize"), "headersSize")
        decoded = byte_size(content.get("size"), "content.size")
        duration = numeric(entry.get("time"), "time", 86400000)
        phases = {key: numeric(timings.get(key), "timings." + key, 86400000) for key in PHASES}
        ssl = numeric(timings.get("ssl"), "timings.ssl", 86400000)
        known_sum = sum(v for v in phases.values() if v is not None)
        mismatch = duration is not None and (known_sum > duration + max(1, duration * .02) or all(v is not None for v in phases.values()) and abs(known_sum - duration) > max(1, duration * .02))
        if ssl is not None and phases["connect"] is not None and ssl > phases["connect"] + 1:
            mismatch = True
        mismatches += int(mismatch)
        label = origin + (url.path or "/") if include_paths else "Request " + str(index).zfill(4)
        label = "".join(c for c in label if ord(c) >= 32 and ord(c) != 127)[:400]
        row = {"id": index, "label": label, "origin": origin_id, "method": method, "status": status, "kind": resource_kind(content.get("mimeType")), "start_ms": timestamp(entry.get("startedDateTime")), "duration_ms": duration, "phases_ms": phases, "ssl_in_connect_ms": ssl, "body_bytes": body, "message_bytes": headers + body if headers is not None and body is not None else None, "decoded_bytes": decoded, "timing_mismatch": bool(mismatch)}
        rows.append(row)
        if method == "GET":
            # Query-sensitive identity is used only in memory; never expose the URL/hash.
            identity = hashlib.sha256((url.scheme + "\0" + url.netloc + "\0" + (url.path or "/") + "\0" + url.query).encode()).digest()
            repeats[identity].append(row)
    if not rows:
        raise ValueError("Selected HAR scope contains no HTTP(S) requests")
    first = min(row["start_ms"] for row in rows)
    for row in rows:
        row["start_ms"] = round(row["start_ms"] - first, 3)
    rows.sort(key=lambda row: (row["start_ms"], row["id"]))
    known_end = max(row["start_ms"] + (row["duration_ms"] or 0) for row in rows)
    if known_end > 7 * 86400000:
        raise ValueError("Selected HAR scope spans more than seven days")
    count = len(rows)
    body_known = sum(r["body_bytes"] is not None for r in rows)
    duration_known = sum(r["duration_ms"] is not None for r in rows)
    waits = [r["phases_ms"]["wait"] for r in rows if r["phases_ms"]["wait"] is not None]
    busy, peak = union_metrics(rows)
    summary = {"requests": count, "origins": len(origins), "http_errors": sum(r["status"] >= 400 for r in rows), "failed_requests": sum(r["status"] == 0 for r in rows), "known_body_bytes": sum(r["body_bytes"] or 0 for r in rows), "body_known_requests": body_known, "known_message_bytes": sum(r["message_bytes"] or 0 for r in rows), "message_known_requests": sum(r["message_bytes"] is not None for r in rows), "known_decoded_bytes": sum(r["decoded_bytes"] or 0 for r in rows), "decoded_known_requests": sum(r["decoded_bytes"] is not None for r in rows), "wait_p95_ms": round(quantile(waits, .95), 3) if waits else None, "wait_known_requests": len(waits), "duration_known_requests": duration_known, "span_ms": round(known_end, 3) if duration_known == count else None, "known_span_ms": round(known_end, 3), "busy_ms": busy if duration_known == count else None, "idle_ms": round(max(0, known_end - busy), 3) if duration_known == count else None, "peak_inflight": peak if duration_known == count else None, "timing_mismatches": mismatches}
    quality = []
    for code, measured, message in (("body-coverage", body_known, "Response-body byte sizes are missing"), ("wait-coverage", len(waits), "Response-wait measurements are missing"), ("duration-coverage", duration_known, "Request durations are missing")):
        if measured != count:
            quality.append({"code": code, "message": message, "affected_requests": count - measured})
    if mismatches:
        quality.append({"code": "timing-mismatch", "message": "Exported phase totals or TLS/connect measurements disagree", "affected_requests": mismatches})
    findings = []
    errors = summary["http_errors"] + summary["failed_requests"]
    if errors:
        findings.append({"rule": "har-request-errors", "severity": "warning", "message": f"{errors} captured requests have HTTP errors or status 0"})
    if quality:
        findings.append({"rule": "har-incomplete-measurements", "severity": "warning", "message": "Capture has missing or inconsistent measurements; inspect metric coverage"})
    budgets = []
    metrics = {"requests": (count, True), "body_kib": (summary["known_body_bytes"] / 1024, body_known == count), "wait_p95_ms": (summary["wait_p95_ms"], len(waits) == count and not mismatches), "errors": (errors, True)}
    for name, limit in limits.items():
        if limit is None:
            continue
        measured, complete = metrics[name]
        state = "unknown" if not complete else "fail" if measured > limit else "pass"
        budgets.append({"metric": name, "limit": limit, "measured": measured if complete else None, "state": state})
        if state != "pass":
            message = "Cannot verify the network budget because measurements are incomplete" if state == "unknown" else f"Measured {measured:g} exceeds the configured {limit:g} budget"
            findings.append({"rule": "har-budget-" + name.replace("_", "-"), "severity": "error", "message": message})
    verdict = "not evaluated" if not budgets else "budget exceeded" if any(b["state"] == "fail" for b in budgets) else "insufficient data" if any(b["state"] == "unknown" for b in budgets) else "within budgets"
    origin_rows = []
    for origin, identity in origins.items():
        group = [r for r in rows if r["origin"] == identity]
        origin_rows.append({"id": identity, "label": origin if include_paths else identity, "requests": len(group), "known_body_bytes": sum(r["body_bytes"] or 0 for r in group), "body_known_requests": sum(r["body_bytes"] is not None for r in group), "errors": sum(r["status"] == 0 or r["status"] >= 400 for r in group)})
    repeated = [{"request_ids": [r["id"] for r in group], "count": len(group), "known_body_bytes": sum(r["body_bytes"] or 0 for r in group), "interpretation": "Same GET URL, including query; repeated requests may be intentional."} for group in repeats.values() if len(group) > 1]
    return {"schema": 1, "tool": "reclaimlab-har", "synthetic": log.get("_reclaimlab_synthetic") is True, "scope": {"page": page, "pages_in_export": len(pages), "entries_in_export": len(entries), "entries_outside_selected_page": skipped_scope, "excluded_non_http_entries": skipped_scheme}, "privacy": {"mode": "origin-and-path" if include_paths else "aliases", "discarded": ["headers", "cookies", "query strings", "fragments", "URL userinfo", "request bodies", "response bodies", "page titles", "absolute timestamps", "connection IP addresses", "initiator stacks"]}, "summary": summary, "quality": quality, "budgets": budgets, "verdict": verdict, "findings": findings, "origins": origin_rows, "repeated_gets": repeated, "requests": rows, "interpretation": INTERPRETATION}


def load(path, **options):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("HAR input must be a regular file, not a symlink")
    with path.open("rb") as stream:
        payload = stream.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("HAR exceeds 32 MiB; export a smaller capture")
    try:
        data = loads(payload)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid HAR JSON") from exc
    return analyse(data, **options)


def compact(report):
    result = {key: report[key] for key in ("schema", "tool", "synthetic", "scope", "privacy", "summary", "quality", "budgets", "verdict", "findings", "interpretation")}
    result["origins"] = report["origins"][:50]
    result["origins_omitted"] = max(0, len(report["origins"]) - 50)
    result["slowest_waits"] = sorted((r for r in report["requests"] if r["phases_ms"]["wait"] is not None), key=lambda r: (-r["phases_ms"]["wait"], r["id"]))[:20]
    result["repeated_get_groups"] = len(report["repeated_gets"])
    return result


def synthetic():
    entries = []
    for index, (name, start, wait, receive, size, mime, status) in enumerate((("/", 0, 180, 40, 18000, "text/html", 200), ("/assets/app.js", 230, 90, 290, 170000, "text/javascript", 200), ("/assets/site.css", 235, 55, 30, 9000, "text/css", 200), ("/api/feed?cursor=1", 650, 720, 35, 24000, "application/json", 200), ("/images/hero.webp", 250, 85, 510, 280000, "image/webp", 200), ("/api/feed?cursor=1", 1500, 640, 30, 24000, "application/json", 200), ("/api/preferences", 1520, 160, 20, 350, "application/json", 503))):
        entries.append({"pageref": "demo", "startedDateTime": "2025-01-01T00:00:" + f"{start / 1000:06.3f}" + "Z", "time": wait + receive, "request": {"method": "GET", "url": "https://example.invalid" + name}, "response": {"status": status, "bodySize": size, "headersSize": 240, "content": {"size": size * 2, "mimeType": mime}}, "timings": {"blocked": 0, "dns": 0, "connect": 0, "ssl": -1, "send": 0, "wait": wait, "receive": receive}})
    return {"log": {"version": "1.2", "_reclaimlab_synthetic": True, "pages": [{"id": "demo"}], "entries": entries}}
