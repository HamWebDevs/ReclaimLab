"""Optional DevPocket integration; standalone use needs no external package."""

def inspect(context, params):
    from devpocket.sdk import Finding, ToolResult
    from .trace import load
    from .analysis import analyse
    trace_path = context.resolve(params['trace'])
    report = analyse(load(trace_path))
    findings = [Finding(issue['code'], issue['title'], severity='warning', path=trace_path.relative_to(context.root).as_posix(), help=issue['evidence'] + ' ' + issue['next_step']) for issue in report['issues']]
    return ToolResult('ReclaimLab scheduling/resource evidence', findings, report)

def build_tool():
    from devpocket.sdk import ToolSpec
    options = {'cache_version': 'trace-v2'} if 'cache_version' in ToolSpec.__dataclass_fields__ else {}
    return ToolSpec(name='reclaimlab', description='Read a laptop trace and explain resource/scheduling overlap', input_schema={'type': 'object', 'properties': {'trace': {'type': 'string', 'maxLength': 4096}}, 'required': ['trace'], 'additionalProperties': False}, run=inspect, read_only=True, **options)


def inspect_study(context, params):
    from devpocket.sdk import Finding, ToolResult
    from .study import evaluate
    path = context.resolve(params['manifest'])
    report = evaluate(path, iterations=params.get('iterations', 2000))
    relative = path.relative_to(context.root).as_posix()
    findings = []
    if report['incompatible']:
        findings.append(Finding('study-incompatible', 'Study contains incompatible or insufficient captures', path=relative, help=' '.join(report['incompatible'])))
    elif report['verdict'] == 'consistent higher measured wake delay':
        findings.append(Finding('study-regression', 'Candidate repeatedly has higher measured wake delay', severity='error', path=relative, help=report['interpretation']))
    elif report['verdict'] == 'consistent lower measured wake delay':
        findings.append(Finding('study-lower-delay', 'Candidate repeatedly has lower measured wake delay', severity='note', path=relative, help=report['interpretation']))
    else:
        findings.append(Finding('study-inconclusive', 'Repeated runs have no consistent directional result', path=relative, help=report['interpretation']))
    if report['synthetic']:
        findings.append(Finding('study-synthetic', 'Study uses synthetic demonstration data', severity='note', path=relative))
    if report['context']:
        findings.append(Finding('study-context', 'Study context needs review', severity='note', path=relative, help=' '.join(report['context'])))
    return ToolResult('ReclaimLab repeated study: ' + report['verdict'], findings, report)


def build_study_tool():
    from devpocket.sdk import ToolSpec
    options = {'cache_version': 'study-v1'} if 'cache_version' in ToolSpec.__dataclass_fields__ else {}
    return ToolSpec(name='reclaimlab-study', description='Audit a repeated laptop experiment and compare paired runs', input_schema={'type': 'object', 'properties': {'manifest': {'type': 'string', 'maxLength': 4096}, 'iterations': {'type': 'integer', 'minimum': 500, 'maximum': 10000}}, 'required': ['manifest'], 'additionalProperties': False}, run=inspect_study, read_only=True, **options)


def inspect_har(context, params):
    from devpocket.sdk import Finding, ToolResult
    from . import har
    path = context.resolve(params['capture'])
    if (context.root / params['capture']).is_symlink():
        raise ValueError('HAR input cannot be a symlink')
    report = har.load(path, **{key: params[key] for key in ('page', 'max_requests', 'max_body_kib', 'max_wait_p95_ms', 'max_errors') if key in params})
    relative = path.relative_to(context.root).as_posix()
    findings = [Finding(item['rule'], item['message'], severity=item['severity'], path=relative) for item in report['findings']]
    if report['synthetic']:
        findings.append(Finding('har-synthetic', 'Capture uses synthetic demonstration data', severity='note', path=relative))
    return ToolResult('Captured browser network: ' + report['verdict'], findings, har.compact(report))


def build_har_tool():
    from devpocket.sdk import ToolSpec
    options = {'cache_version': 'har-v1'} if 'cache_version' in ToolSpec.__dataclass_fields__ else {}
    properties = {'capture': {'type': 'string', 'maxLength': 4096}, 'page': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'max_requests': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000000}, 'max_errors': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000000}, 'max_body_kib': {'type': 'number', 'minimum': 0, 'maximum': 1000000000000}, 'max_wait_p95_ms': {'type': 'number', 'minimum': 0, 'maximum': 1000000000000}}
    return ToolSpec(name='reclaimlab-har', description='Audit a saved HAR with private network summaries, coverage and explicit performance budgets', input_schema={'type': 'object', 'properties': properties, 'required': ['capture'], 'additionalProperties': False}, run=inspect_har, read_only=True, **options)


def inspect_network_study(context, params):
    from devpocket.sdk import Finding, ToolResult
    from .network_study import evaluate
    path = context.resolve(params['manifest'])
    result = evaluate(path, **{key: params[key] for key in ('iterations', 'seed', 'max_growth') if key in params})
    location = path.relative_to(context.root).as_posix()
    findings = []
    if not result['comparable']:
        findings.append(Finding('network-study-incompatible', 'Network experiment cannot certify a comparison', severity='error', path=location, help=' '.join(result['incompatible'])))
    elif result['gate']['state'] in {'fail', 'unknown'}:
        findings.append(Finding('network-study-growth-' + result['gate']['state'], 'Network growth gate: ' + result['gate']['state'], severity='error', path=location, help='The paired interval and both order groups must satisfy the configured growth budget.'))
    elif result['verdict'] == 'consistent higher captured measurement':
        findings.append(Finding('network-study-higher', result['verdict'], path=location, help=result['interpretation']))
    else:
        findings.append(Finding('network-study-result', result['verdict'], severity='note', path=location, help=result['interpretation']))
    if result['synthetic']: findings.append(Finding('network-study-synthetic', 'Synthetic demonstration data', severity='note', path=location))
    return ToolResult('Repeated browser experiment: ' + result['verdict'], findings, result, exit_code=result['exit_code'])


def build_network_study_tool():
    from devpocket.sdk import ToolSpec
    options = {'cache_version': 'network-study-v1'} if 'cache_version' in ToolSpec.__dataclass_fields__ else {}
    properties = {'manifest': {'type': 'string', 'maxLength': 4096}, 'iterations': {'type': 'integer', 'minimum': 500, 'maximum': 10000}, 'seed': {'type': 'integer', 'minimum': 0, 'maximum': 4294967295}, 'max_growth': {'type': 'number', 'minimum': 0, 'maximum': 1000000000000}}
    return ToolSpec(name='reclaimlab-network-study', description='Audit paired HAR exports, run whole-pair descriptive bootstraps and gate captured metric growth', input_schema={'type': 'object', 'properties': properties, 'required': ['manifest'], 'additionalProperties': False}, run=inspect_network_study, read_only=True, **options)


def inspect_bundle(context, params):
    from devpocket.sdk import Finding, ToolResult
    from .bundle import verify
    if (context.root / params['bundle']).is_symlink():
        raise ValueError('Bundle cannot be a symlink')
    path = context.resolve(params['bundle'])
    result = verify(path, max_growth=params.get('max_growth'))
    location = path.relative_to(context.root).as_posix()
    findings = [Finding('bundle-result', 'Verified measurement bundle: ' + result['verdict'], severity='error' if result['exit_code'] else 'note', path=location, help=result['bundle']['interpretation'])]
    if result['synthetic']: findings.append(Finding('bundle-synthetic', 'Synthetic demonstration data', severity='note', path=location))
    return ToolResult('Verified portable experiment: ' + result['verdict'], findings, result, exit_code=result['exit_code'])


def build_bundle_tool():
    from devpocket.sdk import ToolSpec
    options = {'cache_version': 'bundle-format1-v1'} if 'cache_version' in ToolSpec.__dataclass_fields__ else {}
    return ToolSpec(name='reclaimlab-bundle', description='Verify and reanalyse a bounded measurement-only experiment bundle without uploads, extraction or execution', input_schema={'type': 'object', 'properties': {'bundle': {'type': 'string', 'maxLength': 4096}, 'max_growth': {'type': 'number', 'minimum': 0, 'maximum': 1000000000000}}, 'required': ['bundle'], 'additionalProperties': False}, run=inspect_bundle, read_only=True, **options)


def inspect_har_compare(context, params):
    from devpocket.sdk import Finding, ToolResult
    from . import har_compare
    paths = []
    for name in ('before', 'after'):
        if (context.root / params[name]).is_symlink():
            raise ValueError('HAR comparison input cannot be a symlink')
        paths.append(context.resolve(params[name]))
    report = har_compare.load(*paths, **{k: params[k] for k in ('before_page', 'after_page') if k in params})
    findings = [Finding('har-comparison-descriptive', 'Two-capture comparison is descriptive; use repeated studies for regression gates', severity='note')]
    if any(v['state'] == 'unknown' for v in report['delta'].values()):
        findings.append(Finding('har-comparison-coverage', 'Missing measurements keep some comparison deltas unknown', severity='warning'))
    if report['synthetic']:
        findings.append(Finding('har-comparison-synthetic', 'Synthetic demonstration data', severity='note'))
    return ToolResult('Before/after HTTP evidence: ' + str(report['summary']['routes']) + ' route groups', findings, har_compare.compact(report))


def build_har_compare_tool():
    from devpocket.sdk import ToolSpec
    options = {'cache_version': 'har-compare-v1'} if 'cache_version' in ToolSpec.__dataclass_fields__ else {}
    properties = {'before': {'type': 'string', 'maxLength': 4096}, 'after': {'type': 'string', 'maxLength': 4096}, 'before_page': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'after_page': {'type': 'integer', 'minimum': 1, 'maximum': 100}}
    return ToolSpec(name='reclaimlab-har-compare', description='Compare two saved HAR samples with private route aliases and explicit unknown deltas', input_schema={'type': 'object', 'properties': properties, 'required': ['before', 'after'], 'additionalProperties': False}, run=inspect_har_compare, read_only=True, **options)


def inspect_har_assets(context, params):
    from devpocket.sdk import Finding, ToolResult
    from . import har_assets
    requested = context.root / params['capture']
    if requested.is_symlink() or requested.absolute().resolve() != requested.absolute():
        raise ValueError('Asset HAR input cannot use symlinks or redirected directories')
    path = context.resolve(params['capture'])
    report = har_assets.load(path, **{key: params[key] for key in ('page', 'kinds', 'max_asset_kib', 'max_duration_ms', 'top') if key in params})
    relative = path.relative_to(context.root).as_posix()
    findings = [Finding(item['rule'], item['message'], severity=item['severity'], path=relative) for item in report['findings']]
    if report['synthetic']:
        findings.append(Finding('har-assets-synthetic', 'Synthetic demonstration data', severity='note', path=relative))
    return ToolResult('Captured per-request asset evidence: ' + report['verdict'], findings, report, exit_code=report['exit_code'])


def build_har_assets_tool():
    from devpocket.sdk import ToolSpec
    from .har_assets import KINDS
    options = {'cache_version': 'har-assets-v1'} if 'cache_version' in ToolSpec.__dataclass_fields__ else {}
    properties = {'capture': {'type': 'string', 'minLength': 1, 'maxLength': 4096}, 'page': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'kinds': {'type': 'array', 'items': {'type': 'string', 'enum': list(KINDS)}, 'minItems': 1, 'maxItems': len(KINDS)}, 'top': {'type': 'integer', 'minimum': 1, 'maximum': 50}, 'max_asset_kib': {'type': 'number', 'minimum': 0, 'maximum': 1e12}, 'max_duration_ms': {'type': 'number', 'minimum': 0, 'maximum': 1e12}}
    return ToolSpec(name='reclaimlab-har-assets', description='Rank selected captured assets privately and gate individual body-size/duration measurements with explicit coverage', input_schema={'type': 'object', 'properties': properties, 'required': ['capture'], 'additionalProperties': False}, run=inspect_har_assets, read_only=True, **options)
