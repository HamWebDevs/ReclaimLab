"""Versioned JSONL traces with bounded parsing and exclusive file creation."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path

MAX_BYTES = 128 * 1024 * 1024
MAX_RECORDS = 200000
PERCENT = {"steal_pct", "cpu_pct", "iowait_pct", "memory_available_pct", "commit_pct", "cpu_pressure_pct", "memory_pressure_pct", "io_pressure_pct", "disk_busy_pct"}
NONNEGATIVE = {"swap_in_Bps", "swap_out_Bps", "throttle_events"}


def number(value, minimum=0, maximum=1e18):
    return type(value) in {int, float} and math.isfinite(value) and minimum <= value <= maximum


def signature(header):
    hardware = header.get("hardware", {})
    value = {"platform": header.get("platform"), **{key: hardware.get(key) for key in ("machine", "logical_cpus", "memory_bytes", "cpu_model")}}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]


def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8")


def write_row(stream, row):
    stream.write(json.dumps(row, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")
    stream.flush()


def load(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Trace exceeds 128 MiB; select a shorter recording")
    header, footer = None, None
    samples, markers = [], []
    with path.open(encoding="utf-8") as stream:
        for index in range(MAX_RECORDS + 1):
            raw = stream.readline(1024 * 1024 + 1)
            if not raw:
                break
            if index == MAX_RECORDS or len(raw.encode()) > 1024 * 1024:
                raise ValueError("Trace exceeds record or line limits")
            try:
                row = json.loads(raw)
            except (ValueError, RecursionError) as exc:
                raise ValueError(f"Invalid JSON at trace line {index + 1}") from exc
            if not isinstance(row, dict) or not isinstance(row.get("type"), str):
                raise ValueError(f"Invalid trace record at line {index + 1}")
            kind = row["type"]
            if header is None:
                if kind != "header" or type(row.get("schema")) is not int or row["schema"] != 1:
                    raise ValueError("First record must be a schema 1 header")
                if not isinstance(row.get("hardware"), dict) or not isinstance(row.get("platform"), str) or not number(row.get("interval_s"), .2, 10):
                    raise ValueError("Invalid trace header")
                if not number(row.get("heartbeat_s"), .01, 1):
                    raise ValueError("Invalid heartbeat interval")
                if not isinstance(row.get("workload", ""), str) or len(row.get("workload", "")) > 200:
                    raise ValueError("Invalid workload description")
                if type(row.get("process_names_enabled", False)) is not bool or type(row.get("synthetic", False)) is not bool:
                    raise ValueError("Invalid trace feature flags")
                if not isinstance(row.get("label"), str) or len(row["label"]) > 200:
                    raise ValueError("Invalid trace label")
                cpus, memory = row["hardware"].get("logical_cpus"), row["hardware"].get("memory_bytes")
                if type(cpus) is not int or not 1 <= cpus <= 65536 or memory is not None and not number(memory, 1):
                    raise ValueError("Invalid hardware capacities")
                header = row
            elif footer is not None:
                raise ValueError("Records after footer are not allowed")
            elif kind == "sample":
                validate_sample(row, samples[-1]["t"] if samples else 0)
                samples.append(row)
            elif kind == "marker":
                if not number(row.get("t")) or not isinstance(row.get("label"), str) or len(row["label"]) > 200:
                    raise ValueError("Invalid marker")
                markers.append(row)
            elif kind == "footer":
                if not number(row.get("duration_s")) or type(row.get("interrupted")) is not bool or not number(row.get("observer_cpu_s")) or type(row.get("dropped_wake_samples")) is not int or row["dropped_wake_samples"] < 0:
                    raise ValueError("Invalid trace footer")
                if row.get("error") is not None and (not isinstance(row["error"], str) or len(row["error"]) > 500):
                    raise ValueError("Invalid capture error")
                footer = row
            else:
                raise ValueError("Unknown or repeated trace record type")
    if header is None or not samples:
        raise ValueError("Trace has no usable samples")
    if any(marker["t"] > samples[-1]["t"] for marker in markers):
        raise ValueError("Marker falls after the last recorded sample")
    if footer and footer["duration_s"] < samples[-1]["t"]:
        raise ValueError("Footer duration is shorter than the recorded timeline")
    return {"header": header, "samples": samples, "markers": markers, "footer": footer}


def validate_sample(row, previous_t):
    if not number(row.get("t")) or row["t"] <= previous_t or not number(row.get("dt"), 1e-6) or not number(row.get("collector_ms")):
        raise ValueError("Invalid or non-increasing sample timing")
    wake, metrics, processes = row.get("wake_lag_ms"), row.get("metrics"), row.get("processes")
    if not isinstance(wake, list) or len(wake) > 512 or any(not number(x, 0, 86400000) for x in wake):
        raise ValueError("Invalid wake-delay samples")
    if not isinstance(metrics, dict) or set(metrics) - (PERCENT | NONNEGATIVE | {"temperature_c", "power"}):
        raise ValueError("Unknown or invalid metric fields")
    for key, value in metrics.items():
        if value is None:
            continue
        if key in PERCENT and not number(value, 0, 100) or key in NONNEGATIVE and not number(value):
            raise ValueError(f"Invalid metric: {key}")
        if key == "temperature_c" and not number(value, 0, 130):
            raise ValueError("Invalid temperature")
        if key == "power" and (not isinstance(value, str) or value not in {"ac", "battery", "unknown"}):
            raise ValueError("Invalid power state")
    if not isinstance(processes, list) or len(processes) > 5:
        raise ValueError("Invalid process list")
    for process in processes:
        if not isinstance(process, dict) or type(process.get("pid")) is not int or process["pid"] < 0 or not isinstance(process.get("name"), str) or len(process["name"]) > 128 or not number(process.get("cpu_pct"), 0, 100) or process.get("rss_bytes") is not None and not number(process["rss_bytes"]):
            raise ValueError("Invalid process evidence")
