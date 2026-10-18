"""Repeatable, bounded block-bootstrap comparisons with explicit compatibility checks."""
from __future__ import annotations
import random
from .analysis import analyse, quantile
from .trace import signature


def blocks(trace):
    grouped = {}
    for sample in trace["samples"]:
        grouped.setdefault(int(sample["t"]), []).extend(sample["wake_lag_ms"])
    return [v for v in grouped.values() if v]


def assess(before, after):
    """Describe a pair and its compatibility without resampling observations."""
    a, b = analyse(before), analyse(after)
    incompatible = []
    context = []
    if signature(before["header"]) != signature(after["header"]):
        incompatible.append("Platform/coarse hardware signatures differ.")
    if before["header"].get("backend") != after["header"].get("backend") or before["header"].get("process_names_enabled", False) != after["header"].get("process_names_enabled", False):
        incompatible.append("Collector backend or optional process instrumentation differs.")
    ha, hb = before["header"].get("heartbeat_s", .05), after["header"].get("heartbeat_s", .05)
    if abs(ha - hb) > max(ha, hb) * .05:
        incompatible.append("Heartbeat intervals differ by more than 5%.")
    if before["header"].get("synthetic", False) != after["header"].get("synthetic", False):
        incompatible.append("A synthetic demonstration cannot be compared with a real capture.")
    ia, ib = before["header"]["interval_s"], after["header"]["interval_s"]
    if abs(ia - ib) > max(ia, ib) * .05:
        incompatible.append("Sampling intervals differ by more than 5%.")
    da, db = a["summary"]["duration_s"], b["summary"]["duration_s"]
    if min(da, db) < 20 or max(da, db) / min(da, db) > 1.5:
        incompatible.append("Captures are too short or their durations differ by more than 50%.")
    wa, wb = before["header"].get("workload", ""), after["header"].get("workload", "")
    if wa and wb and wa != wb:
        incompatible.append("Declared workloads differ.")
    pa = {s["metrics"].get("power") for s in before["samples"]} - {None, "unknown"}
    pb = {s["metrics"].get("power") for s in after["samples"]} - {None, "unknown"}
    if len(pa) > 1 or len(pb) > 1 or pa and pb and pa != pb:
        incompatible.append("Known power-source states differ or changed during capture.")
    if not pa or not pb:
        context.append("Power state was not established in both captures.")
    for key, description in (("cpu_pct", "CPU activity"), ("memory_available_pct", "memory headroom")):
        x, y = a["averages"][key], b["averages"][key]
        if x is not None and y is not None and abs(x - y) > 15:
            context.append(f"Average {description} changed by {y - x:+.1f} percentage points; this may be the mechanism or a workload confound.")
    for trace in (before, after):
        if not trace.get("footer") or trace["footer"].get("interrupted") or trace["footer"].get("error") or trace["footer"].get("dropped_wake_samples", 0):
            incompatible.append("At least one capture is incomplete or dropped wake observations.")
            break
    if any((x["summary"]["observer_cpu_pct_one_core"] or 0) > 5 for x in (a, b)):
        incompatible.append("Measured recorder CPU overhead is too high for this comparison.")
    ba, bb = blocks(before), blocks(after)
    if min(len(ba), len(bb)) < 20 or min(a["summary"]["wake_observations"], b["summary"]["wake_observations"]) < 200:
        incompatible.append("Need at least 20 occupied one-second blocks and 200 wake observations per capture.")
    before_p95, after_p95 = a["summary"]["wake_p95_ms"], b["summary"]["wake_p95_ms"]
    change = after_p95 - before_p95 if before_p95 is not None and after_p95 is not None else None
    return {"schema": 1, "before": a, "after": b, "change_p95_ms": change, "incompatible": list(dict.fromkeys(incompatible)), "context": context}


def compare(before, after, iterations=300, seed=0):
    if type(iterations) is not int or not 50 <= iterations <= 2000:
        raise ValueError("Bootstrap iterations must be 50..2000")
    result = assess(before, after)
    incompatible = result["incompatible"]
    before_p95 = result["before"]["summary"]["wake_p95_ms"]
    change = result["change_p95_ms"]
    ba, bb = blocks(before), blocks(after)
    interval = None
    verdict = "not comparable" if incompatible else "inconclusive"
    if not incompatible:
        # Resample whole one-second buckets to retain short-range dependence.
        # This is a descriptive interval, not a causal or clinical confidence claim.
        rng = random.Random(seed)
        differences = []
        for _ in range(iterations):
            left = [v for block in rng.choices(ba, k=len(ba)) for v in block]
            right = [v for block in rng.choices(bb, k=len(bb)) for v in block]
            differences.append(quantile(right, .95) - quantile(left, .95))
        interval = [quantile(differences, .025), quantile(differences, .975)]
        material = max(5, (before_p95 or 0) * .15)
        if interval[1] < 0 and change <= -material:
            verdict = "lower measured wake delay"
        elif interval[0] > 0 and change >= material:
            verdict = "higher measured wake delay"
    return {**result, "verdict": verdict, "relative_change_pct": change * 100 / before_p95 if before_p95 and change is not None else None, "bootstrap_interval95_ms": interval, "bootstrap_iterations": iterations if interval else 0, "seed": seed, "interpretation": "Non-randomised before/after observations. A measured difference does not establish that the attempted tweak caused it. Repeat the same task, change one thing, and consider ABAB crossover runs. One-second bootstrap blocks do not remove longer-range dependence."}
