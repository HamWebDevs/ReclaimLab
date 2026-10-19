"""Offline, paired HAR experiments with explicit audit and conservative gates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import fmean

from .jsonio import loads
from . import har
from .analysis import quantile
from .study import CONDITIONS, PAIR_ID, relative_path, resolve, schedule
from .trace import exclusive

MAX_MANIFEST = 256 * 1024
MAX_BYTES = 128 * 1024 * 1024
METRICS = {'wait_p95_ms': ('Response-wait p95', 'ms'), 'body_bytes': ('Captured response-body bytes', 'bytes'), 'requests': ('Captured HTTP requests', 'requests'), 'span_ms': ('Captured HTTP span', 'ms')}
INTERPRETATION = ('Descriptive paired bootstrap resamples whole runs with equal pair weights. The interval describes these captures, not a population confidence guarantee. '
                  'Manual workload, browser, cache and network declarations are unverified; HAR exports cannot bind a run to a code revision, prove independent runs or establish causality. '
                  'Lower HTTP measurements do not establish better user experience. Absolute timestamps are used only to audit capture order; private URL, header and body fields are discarded.')


class StudyLimit(ValueError):
    """Total read budget exhausted; stop the complete study."""


def text(value):
    return isinstance(value, str) and 1 <= len(value) <= 200 and bool(value.strip()) and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def validate(manifest):
    fields = {'schema', 'kind', 'title', 'workload', 'conditions', 'context', 'metric', 'page', 'seed', 'pairs', 'synthetic'}
    if not isinstance(manifest, dict) or set(manifest) - fields or type(manifest.get('schema')) is not int or manifest['schema'] != 1 or manifest.get('kind') != 'network-study':
        raise ValueError('Expected network-study schema 1 protocol')
    if not all(text(manifest.get(key)) for key in ('title', 'workload')):
        raise ValueError('Title and workload need 1..200 printable characters')
    conditions = manifest.get('conditions')
    context = manifest.get('context')
    if not isinstance(conditions, dict) or set(conditions) != CONDITIONS or not all(text(v) for v in conditions.values()):
        raise ValueError('Describe baseline and candidate conditions')
    if not isinstance(context, dict) or set(context) != {'browser', 'cache', 'network'} or not all(text(v) for v in context.values()):
        raise ValueError('Declare browser, cache and network context')
    if not isinstance(manifest.get('metric'), str) or manifest['metric'] not in METRICS:
        raise ValueError('Choose one supported primary network metric')
    if type(manifest.get('seed')) is not int or not 0 <= manifest['seed'] < 2**32:
        raise ValueError('Seed must be a 32-bit nonnegative integer')
    if type(manifest.get('synthetic', False)) is not bool:
        raise ValueError('Synthetic must be boolean')
    if 'page' in manifest and (type(manifest['page']) is not int or not 1 <= manifest['page'] <= 100):
        raise ValueError('Page must be a one-based HAR page number')
    pairs = manifest.get('pairs')
    if not isinstance(pairs, list) or not 2 <= len(pairs) <= 20:
        raise ValueError('Plan 2..20 pairs; a verdict requires at least four')
    ids, paths = set(), set()
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {'id', 'baseline', 'candidate', 'order'} or not isinstance(pair['id'], str) or not PAIR_ID.fullmatch(pair['id']) or pair['id'] in ids:
            raise ValueError('Each pair needs a unique lowercase ID and two capture paths')
        order = pair['order']
        if not isinstance(order, list) or len(order) != 2 or any(not isinstance(v, str) for v in order) or set(order) != CONDITIONS:
            raise ValueError('Each order must contain baseline and candidate once')
        ids.add(pair['id'])
        for condition in ('baseline', 'candidate'):
            path = relative_path(pair[condition]).as_posix()
            if not path.endswith('.har') or path in paths:
                raise ValueError('Each capture needs its own distinct .har path')
            paths.add(path)
    return manifest


def plan(title, workload, browser, cache, network, *, baseline='Original build', candidate='One deliberate change', metric='wait_p95_ms', pairs=6, seed=0, page=None):
    if type(pairs) is not int or not 2 <= pairs <= 20 or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('Plan 2..20 pairs and use a 32-bit nonnegative seed')
    rng = random.Random(seed)
    orders = [['baseline', 'candidate'] for _ in range(pairs // 2)] + [['candidate', 'baseline'] for _ in range(pairs // 2)]
    if pairs % 2: orders.append(rng.choice([['baseline', 'candidate'], ['candidate', 'baseline']]))
    rng.shuffle(orders)
    result = {'schema': 1, 'kind': 'network-study', 'title': title, 'workload': workload, 'conditions': {'baseline': baseline, 'candidate': candidate}, 'context': {'browser': browser, 'cache': cache, 'network': network}, 'metric': metric, 'seed': seed, 'pairs': [{'id': f'p{i+1:02d}', 'baseline': f'captures/p{i+1:02d}-baseline.har', 'candidate': f'captures/p{i+1:02d}-candidate.har', 'order': order} for i, order in enumerate(orders)]}
    if page is not None: result['page'] = page
    return validate(result)


def save(manifest, path):
    validate(manifest)
    with exclusive(path) as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write('\n')


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Network protocol must be a regular file')
    with path.open('rb') as stream: payload = stream.read(MAX_MANIFEST + 1)
    if len(payload) > MAX_MANIFEST: raise ValueError('Network protocol exceeds 256 KiB')
    return validate(loads(payload))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def next_capture(path):
    manifest = read(path)
    for slot in schedule(manifest):
        target = resolve(Path(path).parent, slot['path'])
        if not target.exists():
            return {**slot, 'context': manifest['context'], 'workload': manifest['workload'], 'protocol': fingerprint(manifest), 'instructions': 'Apply this condition yourself, reproduce the declared workload, then export a fresh HAR to this path. Capture/export is manual; this command only inspects files.'}
        if not target.is_file(): raise ValueError('Planned HAR path is not a regular file')
    return None


def measure(payload, manifest):
    raw = loads(payload)
    report = har.analyse(raw, page=manifest.get('page'))
    summary, rows = report['summary'], report['requests']
    issues = []
    if summary['http_errors'] or summary['failed_requests']: issues.append('Captured HTTP errors or status 0')
    if summary['duration_known_requests'] != summary['requests']: issues.append('Incomplete request durations; cannot audit capture overlap')
    if summary['timing_mismatches']: issues.append('Inconsistent exported timings')
    metric = manifest['metric']
    if metric == 'wait_p95_ms':
        value = summary['wait_p95_ms']
        if summary['wait_known_requests'] != summary['requests']:
            issues.append('Incomplete response-wait coverage')
            value = None
    elif metric == 'body_bytes':
        value = summary['known_body_bytes']
        if summary['body_known_requests'] != summary['requests']:
            issues.append('Incomplete response-body size coverage')
            value = None
    else: value = summary[metric]
    browser = raw['log'].get('browser')
    if browser is not None and (not isinstance(browser, dict) or not all(isinstance(browser.get(k), str) and 1 <= len(browser[k]) <= 200 for k in ('name', 'version'))):
        issues.append('Invalid exported browser metadata')
        browser = None
    # All signatures stay internal and contain allowlisted measurements only.
    signature = fingerprint([{k: v for k, v in row.items() if k not in {'id', 'label'}} for row in rows])
    first = min(har.timestamp(raw['log']['entries'][row['id'] - 1]['startedDateTime']) for row in rows)
    return {'value': value, 'summary': summary, 'synthetic': report['synthetic'], 'issues': issues, '_first': first, '_end': first + (summary['span_ms'] or summary['known_span_ms']), '_signature': signature, '_browser': fingerprint({k: browser[k] for k in ('name', 'version')}) if browser else None}


def validate_options(iterations, seed, max_growth):
    if type(iterations) is not int or not 500 <= iterations <= 10000 or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('Use 500..10000 bootstrap iterations and a 32-bit nonnegative seed')
    if max_growth is not None and (type(max_growth) not in {int, float} or not math.isfinite(max_growth) or not 0 <= max_growth <= 1e12):
        raise ValueError('Maximum growth must be a finite nonnegative amount in the primary metric units')


def evaluate(path, iterations=2000, seed=0, max_growth=None):
    validate_options(iterations, seed, max_growth)
    manifest = read(path)
    base = Path(path).resolve().parent
    slots = schedule(manifest)
    targets, captures = {}, {}
    total = 0
    # Resolve and size the complete schedule before parsing large inputs.
    for slot in slots:
        name = slot['path']
        try:
            target = resolve(base, name)
            if not target.is_file(): raise ValueError('Missing or nonregular capture')
            size = target.stat().st_size
            if size > har.MAX_BYTES: raise ValueError('HAR exceeds 32 MiB')
            total += size
            targets[name] = target
        except (OSError, ValueError):
            captures[name] = {'value': None, 'summary': None, 'synthetic': False, 'issues': ['Missing, unsafe or oversized HAR capture']}
    if total > MAX_BYTES: raise ValueError('Network study exceeds 128 MiB of HAR inputs')
    consumed = 0
    for name, target in targets.items():
        try:
            target = resolve(base, name)
            if not target.is_file(): raise ValueError('Capture changed before reading')
            before_stat = target.stat()
            with target.open('rb') as stream: payload = stream.read(min(har.MAX_BYTES, MAX_BYTES - consumed) + 1)
            consumed += len(payload)
            if consumed > MAX_BYTES: raise StudyLimit('Network study exceeds 128 MiB of HAR inputs while reading')
            after_stat = target.stat()
            identity = lambda s: (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if len(payload) > har.MAX_BYTES or identity(before_stat) != identity(after_stat) or resolve(base, name) != target:
                raise ValueError('Capture changed or exceeded its size bound while reading')
            captures[name] = measure(payload, manifest)
        except StudyLimit:
            raise
        except (ValueError, OSError, TypeError, KeyError, RecursionError):
            captures[name] = {'value': None, 'summary': None, 'synthetic': False, 'issues': ['Invalid HAR or incompatible page scope']}
    return summarize(manifest, captures, iterations, seed, max_growth)


def evaluate_memory(manifest, payloads, iterations=2000, seed=0, max_growth=None):
    """Internal bounded in-memory path for verified bundles; performs no file writes."""
    validate_options(iterations, seed, max_growth)
    validate(manifest)
    expected = {slot["path"] for slot in schedule(manifest)}
    if not isinstance(payloads, dict) or set(payloads) - expected or any(not isinstance(p, bytes) for p in payloads.values()):
        raise ValueError("In-memory study requires only the planned capture byte payloads")
    if sum(map(len, payloads.values())) > MAX_BYTES or any(len(p) > har.MAX_BYTES for p in payloads.values()):
        raise ValueError("In-memory study exceeds HAR input bounds")
    captures = {}
    for name in expected:
        if name not in payloads:
            captures[name] = {"value": None, "summary": None, "synthetic": False, "issues": ["Missing, unsafe or oversized HAR capture"]}
            continue
        try:
            captures[name] = measure(payloads[name], manifest)
        except (ValueError, TypeError, KeyError, RecursionError):
            captures[name] = {"value": None, "summary": None, "synthetic": False, "issues": ["Invalid HAR or incompatible page scope"]}
    return summarize(manifest, captures, iterations, seed, max_growth)


def summarize(manifest, captures, iterations, seed, max_growth):
    slots = schedule(manifest)
    signatures = {}
    previous_end, previous_name = None, None
    for slot in slots:
        name = slot['path']
        capture = captures[name]
        signature = capture.get('_signature')
        if signature in signatures:
            capture['issues'].append('Identical exported measurement payload reused across captures')
            captures[signatures[signature]]['issues'].append('Identical exported measurement payload reused across captures')
        elif signature: signatures[signature] = name
        if '_first' in capture:
            if previous_end is not None and capture['_first'] < previous_end:
                capture['issues'].append('Capture overlaps or violates the planned chronological order')
                captures[previous_name]['issues'].append('Capture overlaps or violates the planned chronological order')
            previous_end, previous_name = capture['_end'], name
    blockers, context = [], []
    browsers = {c.get('_browser') for c in captures.values() if c['summary'] is not None}
    if len(browsers) > 1: blockers.append('Exported browser metadata differs or is missing in only some captures')
    if browsers == {None}: context.append('HAR exports omit browser identity; only the manual browser declaration is available')
    synthetic_values = {c['synthetic'] for c in captures.values() if c['summary'] is not None}
    if len(synthetic_values) > 1: blockers.append('Synthetic and measured exports cannot form one comparable study')
    synthetic = manifest.get('synthetic', False) or True in synthetic_values
    if synthetic: context.append('Synthetic demonstration; no measured performance claim')
    audit, deltas, before, after = [], [], [], []
    order_groups = {'baseline-first': [], 'candidate-first': []}
    for pair in manifest['pairs']:
        a, b = captures[pair['baseline']], captures[pair['candidate']]
        problems = sorted(set(a['issues'] + b['issues']))
        if a['value'] is None or b['value'] is None: problems.append('Primary metric is unknown')
        valid = not problems
        delta = b['value'] - a['value'] if valid else None
        group = pair['order'][0] + '-first'
        if valid:
            deltas.append(delta)
            before.append(a['value'])
            after.append(b['value'])
            order_groups[group].append(delta)
            if a['summary']['requests'] != b['summary']['requests']:
                context.append('Request populations differ in at least one pair; p95 changes may reflect a different request mix')
        else: blockers.append(pair['id'] + ': ' + '; '.join(problems))
        public = lambda capture: {k: capture[k] for k in ('value', 'summary', 'synthetic', 'issues')}
        audit.append({'id': pair['id'], 'order': pair['order'], 'valid': valid, 'delta': round(delta, 6) if delta is not None else None, 'issues': problems, 'baseline': public(a), 'candidate': public(b)})
    if len(deltas) < 4: blockers.append('At least four complete compatible pairs are required')
    if not all(order_groups.values()): blockers.append('Both baseline-first and candidate-first orders are required')
    means = {name: fmean(values) if values else None for name, values in order_groups.items()}
    comparable = not blockers
    interval, delta, relative = None, None, None
    mean_before, mean_after = None, None
    verdict = 'not comparable'
    gate = {'state': 'unknown' if not comparable else 'not requested', 'max_growth': max_growth}
    if comparable:
        rng = random.Random(seed)
        samples = [fmean(rng.choices(deltas, k=len(deltas))) for _ in range(iterations)]
        interval = [quantile(samples, .025), quantile(samples, .975)]
        delta, mean_before, mean_after = fmean(deltas), fmean(before), fmean(after)
        relative = 100 * delta / mean_before if mean_before else None
        verdict = 'inconclusive'
        if interval[1] < 0 and sum(d < 0 for d in deltas) / len(deltas) >= .75 and all(m <= 0 for m in means.values()): verdict = 'consistent lower captured measurement'
        elif interval[0] > 0 and sum(d > 0 for d in deltas) / len(deltas) >= .75 and all(m >= 0 for m in means.values()): verdict = 'consistent higher captured measurement'
        if max_growth is not None:
            gate['state'] = 'pass' if interval[1] <= max_growth and all(m <= max_growth for m in means.values()) else 'fail' if interval[0] > max_growth and all(m > max_growth for m in means.values()) else 'unknown'
    return {'schema': 1, 'tool': 'reclaimlab-network-study', 'title': manifest['title'], 'workload': manifest['workload'], 'conditions': manifest['conditions'], 'declared_context': manifest['context'], 'metric': manifest['metric'], 'metric_label': METRICS[manifest['metric']][0], 'unit': METRICS[manifest['metric']][1], 'page': manifest.get('page'), 'protocol_sha256': fingerprint(manifest), 'synthetic': synthetic, 'comparable': comparable, 'planned_pairs': len(audit), 'valid_pairs': len(deltas), 'mean_baseline': mean_before, 'mean_candidate': mean_after, 'mean_delta': delta, 'relative_delta_pct': relative, 'bootstrap_interval95': interval, 'bootstrap': {'iterations': iterations, 'seed': seed, 'resampling_unit': 'whole paired run'}, 'order_group_mean_deltas': means, 'gate': gate, 'verdict': verdict, 'incompatible': blockers, 'context': sorted(set(context)), 'pairs': audit, 'interpretation': INTERPRETATION, 'exit_code': int(not comparable or gate['state'] in {'unknown', 'fail'})}


def write_demo(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'captures').mkdir()
    manifest = plan('Synthetic browser experiment', 'Repeat the same navigation', 'Synthetic browser 1', 'Fresh cache each run', 'Fixed synthetic connection')
    manifest['synthetic'] = True
    path = directory / 'network-study.json'
    save(manifest, path)
    for index, slot in enumerate(schedule(manifest)):
        data = har.synthetic()
        data['log']['browser'] = {'name': 'Synthetic', 'version': '1'}
        factor = (1.02 + index * .007) * (.65 if slot['condition'] == 'candidate' else 1)
        start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
        for entry in data['log']['entries']:
            entry['response']['status'] = 200
            entry['time'] *= factor
            for key, value in entry['timings'].items():
                if value >= 0: entry['timings'][key] = value * factor
            original = datetime.fromisoformat(entry['startedDateTime'].replace('Z', '+00:00'))
            offset = (original - datetime(2025, 1, 1, tzinfo=timezone.utc)).total_seconds()
            entry['startedDateTime'] = (start + timedelta(seconds=offset)).isoformat()
        with exclusive(directory / slot['path']) as stream: json.dump(data, stream, allow_nan=False)
    return path
