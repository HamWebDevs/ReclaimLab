"""Balanced crossover protocols and run-level paired descriptive inference."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import random
import re
from statistics import fmean

from .analysis import quantile
from .experiment import assess
from .trace import exclusive, load, signature

MAX_MANIFEST = 256 * 1024
MAX_STUDY_BYTES = 128 * 1024 * 1024
CONDITIONS = {"baseline", "candidate"}
PAIR_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


def relative_path(text):
    if not isinstance(text, str) or not text or len(text) > 4096 or any(c in text for c in "\\:\0") or any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise ValueError("Study paths must be relative POSIX paths")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or str(path) != text or text == ".":
        raise ValueError("Study paths must remain below the manifest directory")
    return path


def resolve(base, relative):
    relative_path(relative)
    base = Path(base).resolve()
    path = base / relative
    for parent in (path, *path.parents):
        if parent == base:
            break
        if parent.is_symlink():
            raise ValueError("Study paths must not pass through symlinks")
    if not path.resolve().is_relative_to(base):
        raise ValueError("Study path leaves its manifest directory")
    return path


def validate(manifest):
    keys = {"schema", "title", "workload", "conditions", "pairs", "capture", "seed", "synthetic"}
    if not isinstance(manifest, dict) or set(manifest) - keys or type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        raise ValueError("Expected a ReclaimLab study schema 1 manifest")
    for key in ("title", "workload"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip() or not 1 <= len(manifest[key]) <= 200:
            raise ValueError(f"Study {key} needs 1..200 characters")
        if any(ord(c) < 32 or ord(c) == 127 for c in manifest[key]):
            raise ValueError("Study descriptions must be single-line text without control characters")
    conditions = manifest.get("conditions")
    if not isinstance(conditions, dict) or set(conditions) != CONDITIONS or any(not isinstance(x, str) or not x.strip() or not 1 <= len(x) <= 200 for x in conditions.values()):
        raise ValueError("Describe both baseline and candidate conditions")
    if any(ord(c) < 32 or ord(c) == 127 for text in conditions.values() for c in text):
        raise ValueError("Study conditions must be single-line text without control characters")
    if type(manifest.get("seed")) is not int or not 0 <= manifest["seed"] < 2**32:
        raise ValueError("Study seed must be a 32-bit nonnegative integer")
    if type(manifest.get("synthetic", False)) is not bool:
        raise ValueError("Invalid study synthetic flag")
    capture = manifest.get("capture")
    if not isinstance(capture, dict) or set(capture) != {"seconds", "interval"}:
        raise ValueError("Study capture requires seconds and interval")
    for key, low, high in (("seconds", 20, 3600), ("interval", .2, 10)):
        if type(capture[key]) not in {int, float} or not low <= capture[key] <= high:
            raise ValueError(f"Study capture {key} must be {low}..{high}")
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list) or not 2 <= len(pairs) <= 20:
        raise ValueError("Study requires 2..20 planned pairs; a verdict needs at least four")
    ids, paths = set(), set()
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {"id", "baseline", "candidate", "order"} or not isinstance(pair["id"], str) or not PAIR_ID.fullmatch(pair["id"]) or pair["id"] in ids:
            raise ValueError("Study pair IDs must be unique lowercase names")
        order = pair["order"]
        if not isinstance(order, list) or len(order) != 2 or any(not isinstance(x, str) for x in order) or set(order) != CONDITIONS:
            raise ValueError("Each pair's order must contain baseline and candidate once")
        ids.add(pair["id"])
        for condition in ("baseline", "candidate"):
            path = relative_path(pair[condition]).as_posix()
            if path in paths:
                raise ValueError("Every study capture needs its own unique path")
            paths.add(path)
    return manifest


def plan(title, workload, baseline="Original setup", candidate="One deliberate change", pairs=6, seconds=60, interval=.5, seed=0):
    if type(pairs) is not int or not 2 <= pairs <= 20:
        raise ValueError("Plan 2..20 pairs; a verdict requires at least four")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Study seed must be a 32-bit nonnegative integer")
    rng = random.Random(seed)
    orders = [["baseline", "candidate"] for _ in range(pairs // 2)] + [["candidate", "baseline"] for _ in range(pairs // 2)]
    if pairs % 2:
        orders.append(rng.choice([["baseline", "candidate"], ["candidate", "baseline"]]))
    rng.shuffle(orders)
    manifest = {"schema": 1, "title": title, "workload": workload, "conditions": {"baseline": baseline, "candidate": candidate}, "capture": {"seconds": seconds, "interval": interval}, "seed": seed, "pairs": [{"id": f"p{i + 1:02d}", "baseline": f"captures/p{i + 1:02d}-baseline.jsonl", "candidate": f"captures/p{i + 1:02d}-candidate.jsonl", "order": order} for i, order in enumerate(orders)]}
    return validate(manifest)


def save(manifest, path):
    validate(manifest)
    with exclusive(path) as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write("\n")


def read_manifest(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Study manifest must be a regular file")
    with path.open(encoding="utf-8") as stream:
        raw = stream.read(MAX_MANIFEST + 1)
    if len(raw.encode()) > MAX_MANIFEST:
        raise ValueError("Study manifest exceeds 256 KiB")
    return validate(json.loads(raw))


def fingerprint(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def schedule(manifest):
    return [{"pair": pair["id"], "condition": condition, "path": pair[condition], "description": manifest["conditions"][condition]} for pair in manifest["pairs"] for condition in pair["order"]]


def next_capture(path):
    manifest = read_manifest(path)
    for slot in schedule(manifest):
        target = resolve(Path(path).parent, slot["path"])
        if not target.exists():
            return {**slot, "target": target, "manifest": manifest, "stamp": {"protocol": fingerprint(manifest), "pair": slot["pair"], "condition": slot["condition"]}}
        trace = load(target)
        footer = trace.get("footer")
        stamp = trace["header"].get("study")
        expected = {"protocol": fingerprint(manifest), "pair": slot["pair"], "condition": slot["condition"]}
        if not footer or footer.get("interrupted") or footer.get("error") or footer.get("dropped_wake_samples") or trace["header"].get("workload") != manifest["workload"] or stamp and stamp != expected:
            raise ValueError(f"Existing capture {slot['path']} is incomplete or belongs to another protocol; it will not be overwritten")
    return None


def observations(trace):
    hashed = hashlib.sha256()
    for sample in trace["samples"]:
        value = {k: sample[k] for k in ("t", "dt", "wake_lag_ms", "metrics")}
        hashed.update(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        hashed.update(b"\n")
    return hashed.hexdigest()


def created(trace):
    value = trace["header"].get("created_utc", "")
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.timestamp() if result.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def evaluate(path, iterations=2000, seed=0):
    if type(iterations) is not int or not 500 <= iterations <= 10000 or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Use 500..10000 study bootstrap iterations and a 32-bit nonnegative seed")
    manifest = read_manifest(path)
    base, protocol = Path(path).resolve().parent, fingerprint(manifest)
    # Resolve and budget every declared path before reading any potentially large trace.
    targets, total = {}, 0
    for slot in schedule(manifest):
        target = resolve(base, slot["path"])
        if target.exists():
            total += target.stat().st_size
        targets[slot["path"]] = target
    if total > MAX_STUDY_BYTES:
        raise ValueError("Study traces exceed the combined 128 MiB limit")
    rows, blockers, context = [], [], []
    seen, hardware, instrumentation, synthetic_flags, power_states = {}, set(), set(), set(), set()
    previous_end, bound, unstamped = None, True, False
    for pair in manifest["pairs"]:
        traces, problems, notes, audit = {}, [], [], {}
        for condition in pair["order"]:
            target = targets[pair[condition]]
            try:
                trace = load(target)
            except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
                bound = False
                problems.append(f"{condition}: unavailable or invalid capture ({type(exc).__name__})")
                continue
            traces[condition] = trace
            header = trace["header"]
            sample_digest = observations(trace)
            audit[condition] = {"path": pair[condition], "observation_sha256": sample_digest, "created_utc": header.get("created_utc")}
            if sample_digest in seen:
                problems.append(f"{condition}: sample payload reused from {seen[sample_digest]}; repeated data is not a new run")
            seen[sample_digest] = pair["id"] + "/" + condition
            hardware.add(signature(header))
            instrumentation.add((header.get("backend"), header.get("process_names_enabled", False), header["interval_s"], header.get("heartbeat_s")))
            synthetic_flags.add(header.get("synthetic", False))
            power_states.update(sample['metrics'].get('power') for sample in trace['samples'] if sample['metrics'].get('power') not in {None, 'unknown'})
            stamp = header.get("study")
            if stamp is None:
                bound = False
                unstamped = True
            elif stamp != {"protocol": protocol, "pair": pair["id"], "condition": condition}:
                bound = False
                problems.append(f"{condition}: protocol/pair/condition stamp differs")
            if header.get("workload") != manifest["workload"]:
                problems.append(f"{condition}: declared workload does not match the plan")
            capture = manifest["capture"]
            if abs(header["interval_s"] - capture["interval"]) > capture["interval"] * .05:
                problems.append(f"{condition}: sampling interval differs from the plan")
            duration = sum(sample["dt"] for sample in trace["samples"])
            if not capture["seconds"] * .8 <= duration <= capture["seconds"] * 1.25:
                problems.append(f"{condition}: duration is outside 80..125% of the plan")
            start = created(trace)
            if start is None:
                problems.append(f"{condition}: timezone-aware start timestamp is missing")
            else:
                if previous_end is not None and start < previous_end - .5:
                    problems.append(f"{condition}: captures overlap or do not follow the declared schedule")
                previous_end = start + (trace.get("footer") or {}).get("duration_s", duration)
            if any(s["dt"] > header["interval_s"] * 3 for s in trace["samples"]):
                problems.append(f"{condition}: sampling gaps exceed three intervals")
            if quantile([s["collector_ms"] for s in trace["samples"]], .95) > header["interval_s"] * 1000 * .15:
                problems.append(f"{condition}: collector wall time is too high")
        row = {"id": pair["id"], "order": pair["order"], "audit": audit, "baseline_p95_ms": None, "candidate_p95_ms": None, "delta_ms": None}
        if len(traces) == 2:
            assessment = assess(traces["baseline"], traces["candidate"])
            problems.extend(assessment["incompatible"])
            notes.extend(assessment["context"])
            row.update(baseline_p95_ms=assessment["before"]["summary"]["wake_p95_ms"], candidate_p95_ms=assessment["after"]["summary"]["wake_p95_ms"], delta_ms=assessment["change_p95_ms"], quality={"baseline": assessment["before"]["quality"], "candidate": assessment["after"]["quality"]})
        row.update(status="not comparable" if problems else "complete", incompatible=list(dict.fromkeys(problems)), context=notes)
        rows.append(row)
        blockers.extend(pair["id"] + ": " + p for p in row["incompatible"])
        context.extend(pair["id"] + ": " + n for n in notes)
    if len(hardware) > 1:
        blockers.append("Coarse hardware/platform signatures differ across the study.")
    if len(instrumentation) > 1:
        blockers.append("Collector/instrumentation settings differ across the study.")
    if len(power_states) > 1:
        blockers.append("Known power-source states differ across the study.")
    if len(synthetic_flags) > 1 or manifest.get("synthetic") and False in synthetic_flags:
        blockers.append("Synthetic and real captures cannot be combined.")
    if unstamped:
        context.append("Some captures have no protocol stamp; the planned conditions cannot be bound to those headers.")
    valid = [row for row in rows if row["status"] == "complete" and row["delta_ms"] is not None]
    if len(valid) < 4:
        blockers.append("At least four complete, compatible pairs are required; six or more are preferable.")
    orders = {row["order"][0] for row in valid}
    if len(orders) < 2:
        blockers.append("Both baseline-first and candidate-first capture orders are required.")
    deltas = [row["delta_ms"] for row in valid]
    average = fmean(deltas) if deltas else None
    baseline_average = fmean(row["baseline_p95_ms"] for row in valid) if valid else None
    candidate_average = fmean(row["candidate_p95_ms"] for row in valid) if valid else None
    order_groups = {}
    for first in ("baseline", "candidate"):
        selected = [row["delta_ms"] for row in valid if row["order"][0] == first]
        order_groups[first + "_first"] = {"pairs": len(selected), "mean_delta_ms": fmean(selected) if selected else None}
    material = max(5, (baseline_average or 0) * .15)
    group_means = [g["mean_delta_ms"] for g in order_groups.values()]
    order_conflict = all(x is not None for x in group_means) and group_means[0] * group_means[1] < 0 and abs(group_means[0] - group_means[1]) >= material
    if order_conflict:
        context.append("Capture orders show materially opposite mean changes; a directional verdict is withheld.")
    interval, verdict = None, "not comparable" if blockers else "inconclusive"
    if not blockers:
        rng = random.Random(seed)
        values = [fmean(rng.choices(deltas, k=len(deltas))) for _ in range(iterations)]
        interval = [quantile(values, .025), quantile(values, .975)]
        if not order_conflict:
            if interval[1] < 0 and average <= -material and sum(d < 0 for d in deltas) / len(deltas) >= .75:
                verdict = "consistent lower measured wake delay"
            elif interval[0] > 0 and average >= material and sum(d > 0 for d in deltas) / len(deltas) >= .75:
                verdict = "consistent higher measured wake delay"
    return {"schema": 1, "kind": "reclaimlab-study", "title": manifest["title"], "workload": manifest["workload"], "conditions": manifest["conditions"], "synthetic": True in synthetic_flags or manifest.get("synthetic", False), "protocol_sha256": protocol, "protocol_bound": bound and bool(seen), "planned_pairs": len(rows), "valid_pairs": len(valid), "pairs": rows, "verdict": verdict, "mean_baseline_p95_ms": baseline_average, "mean_candidate_p95_ms": candidate_average, "mean_delta_ms": average, "relative_change_pct": average * 100 / baseline_average if baseline_average and average is not None else None, "bootstrap_interval95_ms": interval, "bootstrap_iterations": iterations if interval else 0, "seed": seed, "material_threshold_ms": material, "order_groups": order_groups, "incompatible": list(dict.fromkeys(blockers)), "context": list(dict.fromkeys(context)), "interpretation": "Descriptive paired run-level bootstrap of candidate-minus-baseline p95 timer wake delay. Each complete pair is one resampling unit; individual timer observations are not independent experimental runs. Balanced planned order, consistency stamps and a descriptive interval do not establish authenticity, independence or a causal effect. Repeat the same task, change one condition, allow cooling/warm-up consistently and inspect order effects."}
