"""Self-contained HTML reports with inert imported data and bounded chart geometry."""
import html
import json
import math
import re
from pathlib import Path
from .analysis import analyse, quantile
from .trace import exclusive


def timeline(samples, buckets=250):
    chosen = set()
    step = max(1, math.ceil(len(samples) / buckets))
    for first in range(0, len(samples), step):
        group = list(range(first, min(len(samples), first + step)))
        chosen.update((group[0], group[-1]))
        chosen.add(max(group, key=lambda i: max(samples[i]['wake_lag_ms'], default=0)))
        for key, operation in (('cpu_pct', max), ('memory_available_pct', min)):
            known = [i for i in group if samples[i]['metrics'].get(key) is not None]
            if known:
                chosen.add(operation(known, key=lambda i: samples[i]['metrics'][key]))
    return [{'t': samples[i]['t'], 'cpu': samples[i]['metrics'].get('cpu_pct'), 'memory': samples[i]['metrics'].get('memory_available_pct'), 'disk': samples[i]['metrics'].get('disk_busy_pct'), 'lag': max(samples[i]['wake_lag_ms']) if samples[i]['wake_lag_ms'] else None} for i in sorted(chosen)]


def write_document(data, title, output, template_name):
    serialized = json.dumps(data, ensure_ascii=True, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = Path(__file__).with_name(template_name).read_text(encoding='utf-8')
    document = re.sub(r'__(DATA|TITLE)__', lambda match: serialized if match[1] == 'DATA' else html.escape(title, quote=True), template)
    with exclusive(output) as stream:
        stream.write(document)
    return output


def create(trace, output, analysis=None, comparison=None):
    data = {'header': trace['header'], 'analysis': analysis or analyse(trace), 'comparison': comparison, 'timeline': timeline(trace['samples']), 'markers': trace['markers'][:1000], 'original_records': len(trace['samples'])}
    return write_document(data, trace['header']['label'], output, 'report_template.html')


def create_study(result, output):
    return write_document(result, result['title'], output, 'study_template.html')


def create_network(result, output):
    return write_document(result, 'Browser network report', output, 'network_template.html')


def create_network_study(result, output):
    return write_document(result, result['title'], output, 'network_study_template.html')


def create_network_compare(result, output):
    return write_document(result, 'Before / after HTTP captures', output, 'network_compare_template.html')


def create_network_assets(result, output):
    return write_document(result, 'Captured asset evidence', output, 'network_assets_template.html')
