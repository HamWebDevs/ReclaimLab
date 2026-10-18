"""Clearly labelled synthetic traces for demonstrations and repeatable fixtures."""
import random
from . import __version__
from .trace import signature


def synthetic(label="Synthetic laptop workload", improved=False, seed=42, seconds=60):
    rng = random.Random(seed)
    header = {"type": "header", "schema": 1, "version": __version__, "label": label, "synthetic": True, "platform": "Linux", "backend": "synthetic", "interval_s": .5, "heartbeat_s": .05, "workload": "synthetic repeated workload", "hardware": {"machine": "synthetic-x64", "logical_cpus": 2, "memory_bytes": 4 * 1024**3, "cpu_model": "Synthetic dual-core laptop", "scope_warning": None}, "process_names_enabled": True}
    header["compatibility_signature"] = signature(header)
    samples = []
    for index in range(seconds * 2):
        t = (index + 1) * .5
        crowded = 12 <= t <= 24 or 38 <= t <= 49
        base = 7 if improved else 75 if crowded else 4
        lag = [max(0, rng.gauss(base, 2 if improved else 15 if crowded else 2)) for _ in range(10)]
        metrics = {"cpu_pct": min(100, rng.uniform(87, 98) if crowded else rng.uniform(28, 48)), "memory_available_pct": rng.uniform(4, 8) if crowded else rng.uniform(27, 35), "commit_pct": None, "iowait_pct": 18 if crowded and t > 38 else 1, "cpu_pressure_pct": 22 if crowded else 1, "memory_pressure_pct": 12 if crowded else 0, "io_pressure_pct": 18 if crowded and t > 38 else 0, "swap_in_Bps": 2 * 1024**2 if crowded else 0, "swap_out_Bps": 1024**2 if crowded else 0, "disk_busy_pct": 93 if crowded and t > 38 else 8, "temperature_c": 77 if crowded else 53, "throttle_events": 0, "power": "ac"}
        samples.append({"type": "sample", "t": t, "dt": .5, "collector_ms": .4, "wake_lag_ms": lag, "metrics": metrics, "processes": [{"pid": 100, "name": "example-browser", "cpu_pct": 79 if crowded else 22, "rss_bytes": 900000000}]})
    return {"header": header, "samples": samples, "markers": [m for m in [{"type": "marker", "t": 15, "label": "Video playback starts"}, {"type": "marker", "t": 41, "label": "Tabs become unresponsive"}] if m["t"] <= seconds], "footer": {"type": "footer", "duration_s": seconds, "interrupted": False, "observer_cpu_s": .08, "dropped_wake_samples": 0, "samples": len(samples)}}


def write_study(directory):
    """Write a complete example protocol and independent synthetic sample payloads."""
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from . import study
    from .trace import exclusive, write_row
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    manifest = study.plan('Synthetic repeated laptop experiment', 'synthetic repeated workload', baseline='Synthetic baseline', candidate='Synthetic candidate; not a measured speedup')
    manifest['synthetic'] = True
    manifest_path = root / 'study.json'
    study.save(manifest, manifest_path)
    for i, slot in enumerate(study.schedule(manifest)):
        trace = synthetic(slot['pair'] + ' / ' + slot['condition'], improved=slot['condition'] == 'candidate', seed=1000 + i)
        trace['header']['created_utc'] = (datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i * 90)).isoformat()
        trace['header']['study'] = {'protocol': study.fingerprint(manifest), 'pair': slot['pair'], 'condition': slot['condition']}
        with exclusive(study.resolve(root, slot['path'])) as stream:
            for row in [trace['header'], *trace['samples'], *trace['markers'], trace['footer']]:
                write_row(stream, row)
    return manifest_path
