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
    return ToolSpec(name='reclaimlab', description='Read a laptop trace and explain resource/scheduling overlap', input_schema={'type': 'object', 'properties': {'trace': {'type': 'string', 'maxLength': 4096}}, 'required': ['trace'], 'additionalProperties': False}, run=inspect, read_only=True)
