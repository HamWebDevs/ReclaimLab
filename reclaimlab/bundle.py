"""Versioned, measurement-only experiment bundles. No archive extraction or replay."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import zipfile
import zlib

from . import __version__, har, network_study as ns
from .study import resolve, schedule
from .jsonio import loads

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_CONTENT = 128 * 1024 * 1024
MAX_FILES = 44
ANCHOR = datetime(2000, 1, 1, tzinfo=timezone.utc)
TITLE = 'Shared browser experiment'
WORKLOAD = 'Original workload description withheld'
CONTEXT = {key: 'Original declaration withheld' for key in ('browser', 'cache', 'network')}
METHODS = {'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT', 'OPTIONS', 'TRACE', 'PATCH', 'OTHER'}
MIME = {'document': 'text/html', 'script': 'text/javascript', 'style': 'text/css', 'image': 'image/unknown', 'font': 'font/unknown', 'media': 'video/unknown', 'data': 'application/json', 'other': 'application/octet-stream'}
README = b'ReclaimLab measurement bundle v1\n\nDescriptions, URLs, headers, cookies, bodies, original absolute dates and browser identities are withheld. Relative timing, sizes, statuses, capture order and synthetic flags remain. Measurements may still be identifying; review before sharing.\n\nRun: reclaimlab bundle verify experiment.rlb --output verified.html\n\nSHA-256 detects content changes. It is not a signature, authenticity proof, revision binding or causal evidence. Verification reanalyses measurements and generates a fresh report; it never executes archived content.\n'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def decode(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Duplicate JSON key in bundle')
            result[key] = value
        return result
    try:
        value = loads(payload, object_pairs_hook=pairs)
        def depth(item, level=0):
            if level > 30: raise ValueError('Bundle JSON nesting exceeds 30 levels')
            for child in item.values() if isinstance(item, dict) else item if isinstance(item, list) else ():
                depth(child, level + 1)
        depth(value)
        return value
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('Invalid bundle JSON') from exc


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def scrub(raw, groups, *, page=None, epoch=None):
    report = har.analyse(raw, page=page)
    repeated = {identity: index for index, group in enumerate(report['repeated_gets'], 1) for identity in group['request_ids']}
    entries = []
    for ordinal, row in enumerate(sorted(report['requests'], key=lambda r: r['id']), 1):
        original = stamp(raw['log']['entries'][row['id'] - 1]['startedDateTime'])
        date = ANCHOR + (original - epoch) if epoch is not None else original
        identity = 'repeat-' + str(repeated[row['id']]) if row['id'] in repeated else 'request-' + str(ordinal)
        headers = row['message_bytes'] - row['body_bytes'] if row['message_bytes'] is not None else -1
        known = lambda value: -1 if value is None else value
        entries.append({'pageref': 'page', 'startedDateTime': date.isoformat(timespec='microseconds'), 'time': known(row['duration_ms']), 'request': {'method': row['method'] if row['method'] in METHODS else 'OTHER', 'url': 'https://' + row['origin'] + '.invalid/' + identity}, 'response': {'status': row['status'], 'bodySize': known(row['body_bytes']), 'headersSize': headers, 'content': {'size': known(row['decoded_bytes']), 'mimeType': MIME[row['kind']]}}, 'timings': {**{k: known(v) for k, v in row['phases_ms'].items()}, 'ssl': known(row['ssl_in_connect_ms'])}})
    log = {'version': '1.2', 'pages': [{'id': 'page'}], 'entries': entries, '_reclaimlab_synthetic': report['synthetic']}
    browser = raw['log'].get('browser')
    if browser is not None:
        if isinstance(browser, dict) and all(isinstance(browser.get(k), str) and 1 <= len(browser[k]) <= 200 for k in ('name', 'version')):
            identity = encoded({k: browser[k] for k in ('name', 'version')})
            alias = groups.setdefault(identity, 'Browser group ' + str(len(groups) + 1))
            log['browser'] = {'name': alias, 'version': 'withheld'}
        else:
            log['browser'] = {'name': '', 'version': ''}
    return {'log': log}


def evidence(result):
    keys = ('synthetic', 'comparable', 'planned_pairs', 'valid_pairs', 'mean_baseline', 'mean_candidate', 'mean_delta', 'relative_delta_pct', 'bootstrap_interval95', 'bootstrap', 'order_group_mean_deltas', 'gate', 'verdict', 'exit_code', 'context')
    result = {**{key: result[key] for key in keys}, 'global_blockers': [s for s in result['incompatible'] if ': ' not in s], 'pairs': [{k: pair[k] for k in ('order', 'valid', 'delta', 'issues', 'baseline', 'candidate')} for pair in result['pairs']]}
    return result


def evaluate_files(files, iterations, seed, max_growth):
    manifest = ns.validate(decode(files['network-study.json']))
    captures = {slot['path']: files[slot['path']] for slot in schedule(manifest)}
    return ns.evaluate_memory(manifest, captures, iterations, seed, max_growth)


def create(manifest_path, output, *, iterations=2000, seed=0, max_growth=None):
    output = Path(output)
    if output.exists() or output.is_symlink(): raise ValueError('Bundle output already exists')
    manifest_path = Path(manifest_path)
    original = ns.read(manifest_path)
    source_result = ns.evaluate(manifest_path, iterations, seed, max_growth)
    public = ns.plan(TITLE, WORKLOAD, **CONTEXT, baseline='Baseline', candidate='Candidate', metric=original['metric'], pairs=len(original['pairs']), seed=original['seed'], page=1)
    public['synthetic'] = original.get('synthetic', False)
    for old, new in zip(original['pairs'], public['pairs']): new['order'] = old['order']
    captures, groups, consumed = {}, {}, 0
    by_pair = {p['id']: i for i, p in enumerate(original['pairs'])}
    for slot in schedule(original):
        path = resolve(manifest_path.resolve().parent, slot['path'])
        if not path.is_file(): raise ValueError('Bundle creation needs every capture as a regular parseable HAR')
        before = path.stat()
        with path.open('rb') as stream: payload = stream.read(min(har.MAX_BYTES, MAX_CONTENT - consumed) + 1)
        consumed += len(payload)
        if consumed > MAX_CONTENT or len(payload) > har.MAX_BYTES: raise ValueError('Bundle source exceeds input byte bounds')
        after = path.stat()
        identity = lambda s: (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after): raise ValueError('Capture changed while preparing bundle')
        raw = decode(payload)
        capture = scrub(raw, groups, page=original.get('page'))
        captures[public['pairs'][by_pair[slot['pair']]][slot['condition']]] = capture
    dates = [stamp(e['startedDateTime']) for capture in captures.values() for e in capture['log']['entries']]
    first, last = min(dates), max(dates)
    if last - first > timedelta(days=31): raise ValueError('A portable experiment must fit within a 31-day capture window')
    for capture in captures.values():
        for entry in capture['log']['entries']:
            entry['startedDateTime'] = (ANCHOR + (stamp(entry['startedDateTime']) - first)).isoformat(timespec='microseconds')
    files = {'network-study.json': encoded(public), **{name: encoded(capture) for name, capture in captures.items()}}
    result = evaluate_files(files, iterations, seed, max_growth)
    if evidence(source_result) != evidence(result):
        raise ValueError('Measurement-only transformation changes the audited result; bundle was not written')
    snapshot = {'schema': 1, 'bootstrap': {'iterations': iterations, 'seed': seed}, 'max_growth': max_growth, 'evidence': evidence(result)}
    files.update({'analysis.json': encoded(snapshot), 'README.txt': README})
    index = {'schema': 1, 'kind': 'reclaimlab-network-bundle', 'format': 1, 'producer': __version__, 'files': {name: {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()} for name, payload in sorted(files.items())}}
    files['bundle.json'] = encoded(index)
    validate_files(files)
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_CONTENT: raise ValueError('Bundle exceeds content bounds')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, payload in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, payload, compresslevel=6)
    payload = buffer.getvalue()
    if len(payload) > MAX_ARCHIVE: raise ValueError('Compressed bundle exceeds 64 MiB')
    output.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream: stream.write(payload)
    return {'schema': 1, 'format': 1, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'files': len(files), 'analysis': result}


def validate_files(files):
    required = {'bundle.json', 'network-study.json', 'analysis.json', 'README.txt'}
    if not required <= files.keys() or len(files) > MAX_FILES:
        raise ValueError('Bundle file inventory is incomplete or too large')
    index = decode(files['bundle.json'])
    if not isinstance(index, dict) or set(index) != {'schema', 'kind', 'format', 'producer', 'files'} or type(index['schema']) is not int or index['schema'] != 1 or type(index['format']) is not int or index['format'] != 1 or index['kind'] != 'reclaimlab-network-bundle' or not isinstance(index['producer'], str) or not re.fullmatch(r'\d+\.\d+\.\d+', index['producer']):
        raise ValueError('Unsupported bundle format or producer metadata')
    inventory = index['files']
    if not isinstance(inventory, dict) or set(inventory) != set(files) - {'bundle.json'}: raise ValueError('Bundle inventory does not match its contents')
    for name, entry in inventory.items():
        if not isinstance(entry, dict) or set(entry) != {'bytes', 'sha256'} or type(entry['bytes']) is not int or entry['bytes'] != len(files[name]) or entry['sha256'] != hashlib.sha256(files[name]).hexdigest():
            raise ValueError('Bundle checksum or byte-count mismatch')
    manifest = ns.validate(decode(files['network-study.json']))
    if manifest['title'] != TITLE or manifest['workload'] != WORKLOAD or manifest['context'] != CONTEXT or manifest['conditions'] != {'baseline': 'Baseline', 'candidate': 'Candidate'} or manifest.get('page') != 1:
        raise ValueError('Bundle contains noncanonical descriptive metadata')
    expected = required | {slot['path'] for slot in schedule(manifest)}
    if set(files) != expected or files['README.txt'] != README: raise ValueError('Unexpected or missing bundle member')
    groups = {}
    for index, pair in enumerate(manifest['pairs'], 1):
        if pair['id'] != f'p{index:02d}' or any(pair[condition] != f'captures/p{index:02d}-{condition}.har' for condition in ('baseline', 'candidate')):
            raise ValueError('Bundle capture paths must use the canonical layout')
    for slot in schedule(manifest):
        raw = decode(files[slot['path']])
        if encoded(scrub(raw, groups, page=1, epoch=ANCHOR)) != files[slot['path']]:
            raise ValueError('Bundle HAR contains unapproved fields or noncanonical measurements')
        for entry in raw['log']['entries']:
            if not ANCHOR <= stamp(entry['startedDateTime']) <= ANCHOR + timedelta(days=31):
                raise ValueError('Bundle capture timestamps are outside the shifted experiment window')
    return manifest, decode(files['analysis.json'])


def verify(path, *, max_growth=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file(): raise ValueError('Bundle must be a regular file')
    with path.open('rb') as stream: payload = stream.read(MAX_ARCHIVE + 1)
    if len(payload) > MAX_ARCHIVE: raise ValueError('Compressed bundle exceeds 64 MiB')
    if len(payload) < 22 or payload[-22:-18] != b'PK\x05\x06' or payload[-2:] != b'\0\0':
        raise ValueError('Bundle has an unsupported ZIP envelope or trailing data')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            items = archive.infolist()
            if not 4 <= len(items) <= MAX_FILES or archive.comment or len({i.filename for i in items}) != len(items) or min(i.header_offset for i in items) != 0:
                raise ValueError('Invalid bundle ZIP inventory')
            if sum(i.file_size for i in items) > MAX_CONTENT: raise ValueError('Bundle contents exceed 128 MiB')
            files = {}
            for item in items:
                name = item.filename
                limit = har.MAX_BYTES if re.fullmatch(r'captures/p\d{2}-(baseline|candidate)\.har', name) else 2 * 1024 * 1024 if name == 'analysis.json' else 256 * 1024
                if name not in {'bundle.json', 'network-study.json', 'analysis.json', 'README.txt'} and not re.fullmatch(r'captures/p\d{2}-(baseline|candidate)\.har', name): raise ValueError('Unsafe or unexpected archive member')
                if item.file_size > limit or item.flag_bits & 1 or item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} or item.extra or item.comment or stat.S_IFMT(item.external_attr >> 16) not in {0, stat.S_IFREG} or item.is_dir():
                    raise ValueError('Unsupported or oversized archive member')
                with archive.open(item) as stream: data = stream.read(limit + 1)
                if len(data) != item.file_size: raise ValueError('Archive member length mismatch')
                files[name] = data
    except (zipfile.BadZipFile, RuntimeError, EOFError, zlib.error) as exc:
        raise ValueError('Invalid or damaged bundle ZIP data') from exc
    _, stored = validate_files(files)
    if not isinstance(stored, dict) or set(stored) != {'schema', 'bootstrap', 'max_growth', 'evidence'} or type(stored['schema']) is not int or stored['schema'] != 1 or not isinstance(stored['bootstrap'], dict) or set(stored['bootstrap']) != {'iterations', 'seed'}:
        raise ValueError('Invalid stored analysis')
    result = evaluate_files(files, stored['bootstrap']['iterations'], stored['bootstrap']['seed'], stored['max_growth'])
    if encoded(evidence(result)) != encoded(stored['evidence']): raise ValueError('Stored analysis does not match verified reanalysis')
    if max_growth is not None:
        result = evaluate_files(files, stored['bootstrap']['iterations'], stored['bootstrap']['seed'], max_growth)
    result['bundle'] = {'format': 1, 'integrity': 'verified', 'sha256': hashlib.sha256(payload).hexdigest(), 'files': len(files), 'descriptions_withheld': True, 'absolute_dates_shifted': True, 'interpretation': 'Checksums and reanalysis establish internal consistency, not source authenticity, privacy against reidentification, revision binding or causality.'}
    return result
