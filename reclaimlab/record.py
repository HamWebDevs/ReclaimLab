"""Low-rate native capture and an independent scheduler wake-delay probe."""
from __future__ import annotations
from collections import deque
from datetime import datetime, timezone
import os
import platform
import queue
import sys
import threading
import time

from . import __version__
from .native import collector, delta
from .trace import exclusive, signature, write_row


class Heartbeat:
    def __init__(self, interval=.05):
        self.interval = interval
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.values = deque(maxlen=2048)
        self.dropped = 0
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        while not self.stop.is_set():
            start = time.monotonic()
            if self.stop.wait(self.interval):
                break
            lag = max(0, (time.monotonic() - start - self.interval) * 1000)
            with self.lock:
                if len(self.values) == self.values.maxlen:
                    self.dropped += 1
                self.values.append(lag)

    def drain(self):
        with self.lock:
            values = list(self.values)
            self.values.clear()
        # Keep a bounded representation even after an unusual capture gap.
        if len(values) > 512:
            self.dropped += len(values) - 512
            values = sorted(values)[-512:]
        return values


def record(path, seconds=60, interval=.5, label="recording", processes=False, interactive=False, backend=None, workload=""):
    if not 2 <= seconds <= 3600 or not .2 <= interval <= 10 or len(label) > 200 or len(workload) > 200:
        raise ValueError("Use 2..3600 seconds, a .2..10 second sample interval and a label up to 200 characters")
    source = backend or collector(processes)
    previous = source.snapshot()
    cpus = os.cpu_count() or 1
    header = {"type": "header", "schema": 1, "version": __version__, "label": label, "workload": workload, "created_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.system(), "release": platform.release(), "backend": source.name, "interval_s": interval, "heartbeat_s": .05, "process_names_enabled": processes, "hardware": {"logical_cpus": cpus, "memory_bytes": previous.get("memory_total"), "machine": platform.machine(), **source.description()}}
    header["compatibility_signature"] = signature(header)
    beat = Heartbeat()
    commands = queue.Queue(maxsize=128)
    start = time.monotonic()
    observer_start = time.process_time()
    interrupted = False
    capture_error = None
    count = 0
    def input_loop():
        for line in sys.stdin:
            try:
                commands.put_nowait(line.strip()[:200])
            except queue.Full:
                pass
            if line.strip().lower() == "quit":
                break
    with exclusive(path) as stream:
        write_row(stream, header)
        beat.thread.start()
        if interactive:
            print("Type a short label and Enter to mark a moment; type quit to finish.", file=sys.stderr)
            threading.Thread(target=input_loop, daemon=True).start()
        try:
            deadline = start + seconds
            while time.monotonic() < deadline:
                time.sleep(min(interval, max(0, deadline - time.monotonic())))
                before = time.monotonic()
                current = source.snapshot()
                elapsed = time.monotonic() - start
                metrics, procs = delta(current, previous, cpus)
                write_row(stream, {"type": "sample", "t": elapsed, "dt": current["clock"] - previous["clock"], "collector_ms": (time.monotonic() - before) * 1000, "wake_lag_ms": beat.drain(), "metrics": metrics, "processes": procs})
                previous = current
                count += 1
                should_stop = False
                while not commands.empty():
                    command = commands.get_nowait()
                    if command.lower() == "quit":
                        should_stop = True
                    elif command:
                        write_row(stream, {"type": "marker", "t": elapsed, "label": command})
                if should_stop:
                    break
        except KeyboardInterrupt:
            interrupted = True
        except Exception as exc:
            capture_error = (type(exc).__name__ + ": " + str(exc))[:500]
            raise
        finally:
            beat.stop.set()
            beat.thread.join(timeout=1)
            write_row(stream, {"type": "footer", "duration_s": time.monotonic() - start, "interrupted": interrupted, "error": capture_error, "observer_cpu_s": time.process_time() - observer_start, "dropped_wake_samples": beat.dropped, "samples": count})
    return {"samples": count, "interrupted": interrupted, "seconds": time.monotonic() - start}
