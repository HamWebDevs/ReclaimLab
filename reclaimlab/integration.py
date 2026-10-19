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
