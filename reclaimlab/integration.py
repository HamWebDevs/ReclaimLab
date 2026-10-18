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
