"""Capture and analyse native laptop performance evidence."""
import argparse
import json
from pathlib import Path
import platform
import sys
from . import __version__
from .analysis import analyse
from .demo import synthetic
from .experiment import compare
from .native import collector
from .record import record
from .report import create
from .trace import exclusive, load, write_row

def parser():
    p = argparse.ArgumentParser(prog='reclaimlab', description='Record laptop slowdowns and compare changes with evidence.')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='action', required=True)
    r = sub.add_parser('record', help='Read native counters while reproducing a slowdown')
    r.add_argument('--seconds', type=float, default=60)
    r.add_argument('--interval', type=float, default=0.5)
    r.add_argument('--label', default='Laptop capture')
    r.add_argument('--workload', default='', help='Use the same description for the repeated task')
    r.add_argument('--processes', action='store_true', help='Opt in to process names/PIDs/CPU/available RSS; no command lines')
    r.add_argument('--interactive', action='store_true', help='Type a label and Enter to mark a moment; quit to finish')
    r.add_argument('--output', required=True)
    a = sub.add_parser('analyze', help='Explain trace evidence without changing settings')
    a.add_argument('trace')
    a.add_argument('--json', action='store_true')
    a.add_argument('--threshold', type=float, default=50)
    a.add_argument('--window', help='Sample endpoint range START:END, in seconds')
    a.add_argument('--around', help='Select around the first exact marker label')
    a.add_argument('--radius', type=float, default=5)
    r = sub.add_parser('report', help='Create an offline interactive HTML report')
    r.add_argument('trace')
    r.add_argument('--output', required=True)
    r = sub.add_parser('compare', help='Compare capture distributions with compatibility checks')
    r.add_argument('before')
    r.add_argument('after')
    r.add_argument('--iterations', type=int, default=300)
    r.add_argument('--json', action='store_true')
    r.add_argument('--output', help='Optional fresh HTML report')
    r = sub.add_parser('demo', help='Create a clearly labelled synthetic demo')
    r.add_argument('--output', required=True)
    r.add_argument('--trace-output')
    sub.add_parser('doctor', help='Show native capture capabilities')
    return p

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        for output in (getattr(args, 'output', None), getattr(args, 'trace_output', None)):
            if output and (Path(output).exists() or Path(output).is_symlink()):
                raise ValueError('Output already exists; choose a fresh filename')
        if args.action == 'record':
            result = record(args.output, args.seconds, args.interval, args.label, args.processes, args.interactive, workload=args.workload)
            print(f"Saved {result['samples']} samples: {args.output}")
            return 130 if result['interrupted'] else 0
        if args.action == 'doctor':
            source = collector()
            s = source.snapshot()
            print(json.dumps({'platform': platform.system(), 'backend': source.name, 'cpu_counters': bool(s.get('cpu')), 'memory_available': s.get('memory_available') is not None, 'psi': bool(s.get('psi', {}).get('memory')), 'disk_counters': bool(s.get('disks')), 'thermal': s.get('temperature_c') is not None, 'power': s['power'], 'process_names_default': False, **source.description()}, indent=2))
            return 0
        if args.action == 'demo':
            trace = synthetic()
            create(trace, args.output, comparison=compare(trace, synthetic('Synthetic comparison', improved=True)))
            if args.trace_output:
                with exclusive(args.trace_output) as stream:
                    for row in [trace['header'], *trace['samples'], *trace['markers'], trace['footer']]:
                        write_row(stream, row)
            print(f'Synthetic demo saved: {args.output}')
            return 0
        trace = load(args.trace if args.action in {'analyze', 'report'} else args.before)
        if args.action == 'analyze':
            window = tuple((float(x) for x in args.window.split(':'))) if args.window else None
            result = analyse(trace, args.threshold, window, args.around, args.radius)
            if args.json:
                print(json.dumps(result, indent=2, allow_nan=False))
            else:
                print(result['label'])
                print(f"p95 timer delay: {result['summary']['wake_p95_ms']} ms; {result['summary']['delayed_records']} delayed records")
                for issue in result['issues']:
                    print(f"\n[{issue['strength']}] {issue['title']}\n{issue['evidence']}\nTry: {issue['next_step']}")
                for quality in result['quality']:
                    print('Capture quality: ' + quality)
                print('\n' + result['interpretation'])
            return 0
        if args.action == 'report':
            create(trace, args.output)
            print(f'Offline report saved: {args.output}')
            return 0
        result = compare(trace, load(args.after), args.iterations)
        if args.output:
            create(trace, args.output, comparison=result)
        if args.json:
            print(json.dumps(result, indent=2, allow_nan=False))
        else:
            print(result['verdict'])
            print(f"Change in p95: {result['change_p95_ms']} ms; descriptive interval: {result['bootstrap_interval95_ms']}")
            for reason in result['incompatible'] + result['context']:
                print('- ' + reason)
            print(result['interpretation'])
        return 0
    except (OSError, ValueError, TypeError, KeyError, EOFError, RecursionError) as exc:
        print(f'reclaimlab: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('reclaimlab: interrupted', file=sys.stderr)
        return 130
