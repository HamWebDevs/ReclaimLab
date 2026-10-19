"""Descriptive before/after HAR differences with ephemeral private route matching."""
from __future__ import annotations

from collections import defaultdict
import copy
from pathlib import Path
from urllib.parse import urlsplit

from . import har
from .analysis import quantile
from .jsonio import loads

INTERPRETATION = (
    'This compares two captured HTTP samples descriptively, not repeated experimental runs. '
    'Changes do not establish a regression, improvement or cause. Origin, HTTP method and '
    'encoded path identify route groups; query variants are aggregated. Request order does '
    'not identify a route. Missing measurements keep dependent deltas unknown. '
    'Use a planned repeated network study for uncertainty-aware growth gates.'
)


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('HAR comparison inputs must be regular files, not symlinks')
    with path.open('rb') as stream:
        payload = stream.read(har.MAX_BYTES + 1)
    if len(payload) > har.MAX_BYTES:
        raise ValueError('HAR exceeds 32 MiB; export a smaller capture')
    return loads(payload)


def _key(data, row):
    # HAR validation has already checked this URL. The complete private matching
    # key stays in memory; report labels/hashes are never used as identities.
    url = urlsplit(data['log']['entries'][row['id'] - 1]['request']['url'])
    port = url.port
    if port == (443 if url.scheme.lower() == 'https' else 80):
        port = None
    host = url.hostname.lower()
    origin = url.scheme.lower() + '://' + ('[' + host + ']' if ':' in host else host) + (':' + str(port) if port is not None else '')
    return row['method'], origin, url.path or '/'


def _metrics(rows):
    count = len(rows)
    bodies = [r['body_bytes'] for r in rows if r['body_bytes'] is not None]
    waits = [r['phases_ms']['wait'] for r in rows if r['phases_ms']['wait'] is not None]
    mismatches = sum(r['timing_mismatch'] for r in rows)
    return {
        'requests': count,
        'errors': sum(r['status'] == 0 or r['status'] >= 400 for r in rows),
        'body_bytes': sum(bodies) if len(bodies) == count else None,
        'known_body_bytes': sum(bodies), 'body_known_requests': len(bodies),
        'wait_p95_ms': round(quantile(waits, .95), 3) if count and len(waits) == count and not mismatches else None,
        'wait_known_requests': len(waits), 'timing_mismatches': mismatches,
    }


def _deltas(before, after):
    result = {}
    for metric in ('requests', 'errors', 'body_bytes', 'wait_p95_ms'):
        left, right = before[metric], after[metric]
        known = left is not None and right is not None
        result[metric] = {
            'before': left, 'after': right,
            'change': round(right - left, 3) if known else None,
            'percent': round((right - left) / abs(left) * 100, 3) if known and left != 0 else None,
            'state': 'known' if known else 'unknown',
        }
    return result


def compare(before, after, *, before_page=None, after_page=None, include_paths=False):
    if type(include_paths) is not bool:
        raise ValueError('include_paths must be boolean')
    reports = [har.analyse(before, page=before_page), har.analyse(after, page=after_page)]
    groups = [defaultdict(list), defaultdict(list)]
    ordered, seen = [], set()
    for data, report, grouped in zip((before, after), reports, groups):
        for row in report['requests']:
            identity = _key(data, row)
            grouped[identity].append(row)
            if identity not in seen:
                seen.add(identity)
                ordered.append(identity)
    origins, rows = {}, []
    for number, key in enumerate(ordered, 1):
        method, origin, path = key
        origin_id = origins.setdefault(origin, 'origin-' + str(len(origins) + 1))
        left, right = groups[0].get(key, []), groups[1].get(key, [])
        a, b = _metrics(left), _metrics(right)
        delta = _deltas(a, b)
        state = 'added' if not left else 'removed' if not right else 'changed' if any(v['change'] not in (None, 0) for v in delta.values()) else 'unknown' if any(v['state'] == 'unknown' for v in delta.values()) else 'unchanged'
        kinds = sorted({r['kind'] for r in left + right})
        rows.append({
            'id': 'route-' + str(number), 'label': (origin + path)[:400] if include_paths else 'Route ' + str(number).zfill(4),
            'origin': origin_id, 'method': method, 'kinds': kinds, 'state': state,
            'before': a, 'after': b, 'delta': delta,
        })
    left, right = (_metrics(r['requests']) for r in reports)
    notes = ['Capture quality needs review' for r in reports if r['quality']]
    if any(r['scope']['entries_outside_selected_page'] or r['scope']['excluded_non_http_entries'] for r in reports):
        notes.append('The comparison covers only the selected HTTP scopes')
    return {
        'schema': 1, 'tool': 'reclaimlab-har-compare', 'mode': 'descriptive',
        'synthetic': any(r['synthetic'] for r in reports),
        'privacy': {'mode': 'origin-and-path' if include_paths else 'aliases', 'discarded': reports[0]['privacy']['discarded'], 'matching': 'Origin, method and full encoded path; query variants aggregated; private matching keys discarded'},
        'before': {'summary': left, 'scope': reports[0]['scope'], 'quality': reports[0]['quality']},
        'after': {'summary': right, 'scope': reports[1]['scope'], 'quality': reports[1]['quality']},
        'delta': _deltas(left, right),
        'summary': {'routes': len(rows), **{s: sum(r['state'] == s for r in rows) for s in ('added', 'removed', 'changed', 'unchanged', 'unknown')}},
        'origins': [{'id': identity, 'label': origin if include_paths else identity} for origin, identity in origins.items()],
        'routes': rows, 'notes': sorted(set(notes)), 'interpretation': INTERPRETATION,
    }


def load(before, after, **options):
    return compare(_read(before), _read(after), **options)


def compact(report):
    result = {k: v for k, v in report.items() if k not in {'routes', 'origins'}}
    result['top_changes'] = sorted(report['routes'], key=lambda r: (-abs(r['delta']['body_bytes']['change'] or 0), -abs(r['delta']['requests']['change'] or 0), r['id']))[:20]
    result['routes_omitted'] = max(0, len(report['routes']) - 20)
    return result


def synthetic():
    before = har.synthetic()
    after = copy.deepcopy(before)
    after['log']['entries'] = after['log']['entries'][1:]
    for entry in after['log']['entries']:
        entry['response']['bodySize'] *= 2
    extra = copy.deepcopy(after['log']['entries'][0])
    extra['request']['url'] = 'https://example.invalid/new-feature.js'
    after['log']['entries'].append(extra)
    return compare(before, after, include_paths=True)
