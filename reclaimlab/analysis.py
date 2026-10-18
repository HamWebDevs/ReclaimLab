"""Transparent heuristics: scheduling symptoms and coincident resource evidence."""
from __future__ import annotations
import math

METRICS = ("steal_pct", "cpu_pct", "memory_available_pct", "commit_pct", "cpu_pressure_pct", "memory_pressure_pct", "io_pressure_pct", "disk_busy_pct", "iowait_pct", "swap_in_Bps", "swap_out_Bps", "temperature_c")


def quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low = int(index)
    high = min(len(ordered) - 1, low + 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def weighted(samples, key):
    pairs = [(s["metrics"].get(key), s["dt"]) for s in samples if s["metrics"].get(key) is not None]
    total = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total if total else None


def select(trace, window=None, around=None, radius=5):
    if around is not None:
        marker = next((m for m in trace["markers"] if m["label"] == around), None)
        if marker is None:
            raise ValueError("Marker not found; labels are exact and case-sensitive")
        window = (max(0, marker["t"] - radius), marker["t"] + radius)
    if window is not None:
        if len(window) != 2 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in window) or not 0 <= window[0] < window[1]:
            raise ValueError("Window must be START:END with 0 <= START < END")
        samples = [s for s in trace["samples"] if window[0] <= s["t"] <= window[1]]
    else:
        samples = trace["samples"]
    if not samples:
        raise ValueError("No complete sample endpoints fall inside the selected window")
    return samples


def analyse(trace, threshold=50, window=None, around=None, radius=5):
    if not 5 <= threshold <= 5000 or not .1 <= radius <= 600:
        raise ValueError("Use a 5..5000 ms delay threshold and a .1..600 second marker radius")
    samples = select(trace, window, around, radius)
    wake = [x for s in samples for x in s["wake_lag_ms"]]
    duration = sum(s["dt"] for s in samples)
    delayed = [s for s in samples if any(x >= threshold for x in s["wake_lag_ms"])]
    averages = {k: weighted(samples, k) for k in METRICS}
    coverage = {k: sum(s["dt"] for s in samples if s["metrics"].get(k) is not None) / duration if duration else 0 for k in METRICS}
    episodes = []
    interval = trace["header"]["interval_s"]
    for sample in delayed:
        start = max(0, sample["t"] - sample["dt"])
        peak = max(sample["wake_lag_ms"])
        if episodes and start - episodes[-1]["end_s"] <= interval * 1.5:
            episodes[-1]["end_s"] = sample["t"]
            episodes[-1]["peak_ms"] = max(peak, episodes[-1]["peak_ms"])
            episodes[-1]["records"] += 1
        else:
            episodes.append({"start_s": start, "end_s": sample["t"], "peak_ms": peak, "records": 1})
    issues = []
    def issue(code, title, evidence, next_step, strength="moderate"):
        issues.append({"code": code, "title": title, "evidence": evidence, "next_step": next_step, "strength": strength})
    cpu = [s for s in delayed if (s["metrics"].get("cpu_pct") or 0) >= 85]
    if cpu:
        pressure = [s for s in cpu if (s["metrics"].get("cpu_pressure_pct") or 0) >= 10]
        issue("cpu-coincidence", "High CPU activity overlaps delayed timer wake-ups", f"{len(cpu)} of {len(delayed)} delayed records have CPU activity >=85%; {len(pressure)} also show Linux CPU pressure >=10%.", "Repeat the same workload with one background task closed, or with lower video resolution. Compare a separate capture.", "strong overlap" if len(pressure) >= 3 else "moderate")
    memory = [s for s in delayed if s["metrics"].get("memory_available_pct") is not None and s["metrics"]["memory_available_pct"] <= 10]
    paging = [s for s in memory if (s["metrics"].get("memory_pressure_pct") or 0) >= 5 or (s["metrics"].get("swap_in_Bps") or 0) + (s["metrics"].get("swap_out_Bps") or 0) >= 1048576]
    if paging:
        issue("memory-pressure-overlap", "Low memory headroom and paging/pressure overlap delays", f"{len(paging)} delayed records combine <=10% available memory with memory PSI >=5% or swap traffic >=1 MiB/s.", "Repeat with a smaller active working set, such as fewer heavy tabs. Swap usage alone is not evidence of current thrashing.", "strong overlap" if len(paging) >= 3 else "moderate")
    elif memory:
        issue("memory-headroom", "Little immediately available memory during delays", f"{len(memory)} delayed records have <=10% available memory. Paging/pressure evidence is absent or unavailable.", "Check whether reducing the active workload changes wake delays. This reading alone does not prove memory is the bottleneck.", "limited")
    io = [s for s in delayed if (s["metrics"].get("disk_busy_pct") or 0) >= 85 and ((s["metrics"].get("io_pressure_pct") or 0) >= 10 or (s["metrics"].get("iowait_pct") or 0) >= 15)]
    if io:
        issue("storage-pressure-overlap", "Busy storage and I/O waiting overlap delays", f"{len(io)} delayed records combine >=85% busy time on a measured block device with I/O PSI >=10% or CPU iowait >=15%.", "Repeat after a known background copy/indexing task finishes. Busy time is not throughput, device health or proof that an SSD upgrade is required.", "strong overlap" if len(io) >= 3 else "moderate")
    thermal = [s for s in samples if (s["metrics"].get("throttle_events") or 0) > 0]
    if thermal:
        issue("throttle-counter", "A measured CPU throttle counter increased", f"Counter growth was observed in {len(thermal)} records. {sum(s in delayed for s in thermal)} of those also contain delayed wake-ups.", "Check cooling and repeat the workload. Do not infer causality from temperature or frequency alone.", "direct counter evidence")
    elif sum((s["metrics"].get("temperature_c") or 0) >= 90 for s in samples) >= 2:
        issue("temperature-exposure", "High reported CPU-related temperature", "At least two records report >=90 C, without direct observed throttle-counter growth.", "Check the sensor's meaning and cooling. High temperature alone does not establish throttling.", "limited")
    if delayed and not issues:
        issue("unexplained-delay", "Delayed wake-ups lack a matching resource explanation", f"{len(delayed)} records contain a wake delay >={threshold:g} ms without matching the implemented overlap rules.", "Repeat with a marker at the perceived slowdown. GPU/driver/application-specific tracing may be needed; this tool does not measure those.", "unexplained")
    quality = []
    footer = trace.get("footer")
    if not footer or footer.get("interrupted") or footer.get("error"):
        quality.append("Capture is incomplete or was interrupted.")
    if duration < 20 or len(wake) < 200:
        quality.append("Short capture: tail percentiles and experiment comparisons may be unstable.")
    observer = footer["observer_cpu_s"] * 100 / footer["duration_s"] if footer and footer["duration_s"] else None
    if observer is not None and observer > 5:
        quality.append("Recorder CPU time exceeded 5% of one logical core; observer overhead may affect results.")
    collector_p95 = quantile([s["collector_ms"] for s in samples], .95)
    if collector_p95 > interval * 1000 * .15:
        quality.append("Collector wall time used a substantial fraction of the requested sampling interval.")
    if any(s["dt"] > interval * 3 for s in samples):
        quality.append("Sampling gaps exceed three requested intervals; timing detail is sparse in those periods.")
    if footer and footer.get("dropped_wake_samples", 0):
        quality.append("Some wake-delay observations were dropped to preserve bounded memory.")
    if trace["header"]["hardware"].get("scope_warning"):
        quality.append(trace["header"]["hardware"]["scope_warning"])
    process_evidence = {}
    for sample in delayed:
        for process in sample["processes"]:
            name = process["name"]
            item = process_evidence.setdefault(name, {"name": name, "peak_cpu_pct": 0, "delayed_records": 0})
            item["peak_cpu_pct"] = max(item["peak_cpu_pct"], process["cpu_pct"])
            item["delayed_records"] += 1
    return {"schema": 1, "label": trace["header"]["label"], "synthetic": trace["header"].get("synthetic", False), "threshold_ms": threshold, "selection": {"start_s": max(0, samples[0]["t"] - samples[0]["dt"]), "end_s": samples[-1]["t"]}, "summary": {"duration_s": duration, "records": len(samples), "wake_observations": len(wake), "wake_p50_ms": quantile(wake, .5), "wake_p95_ms": quantile(wake, .95), "wake_p99_ms": quantile(wake, .99), "wake_max_ms": max(wake) if wake else None, "delayed_wakes": sum(x >= threshold for x in wake), "delayed_records": len(delayed), "observer_cpu_pct_one_core": observer, "collector_p95_ms": collector_p95}, "averages": averages, "coverage": coverage, "episodes": episodes, "issues": issues, "quality": quality, "process_evidence": sorted(process_evidence.values(), key=lambda p: -p["peak_cpu_pct"])[:10], "interpretation": "Wake delay measures this Python probe's scheduling/sleep lateness, not GUI input lag, frame time or application responsiveness. Resource overlap is evidence to investigate, not a demonstrated cause."}
