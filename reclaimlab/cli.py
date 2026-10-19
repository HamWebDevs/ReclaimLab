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
from .report import create, create_study, create_network, create_network_study, create_network_compare
from . import bundle, har, study, network_study, har_compare
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
    r = sub.add_parser('har', help='Analyze a saved browser HAR with offline waterfall reports and CI budgets')
    r.add_argument('capture', help='HAR 1.2 export; never uploaded or replayed')
    r.add_argument('--page', type=int, help='One-based page number; required for multi-page captures')
    r.add_argument('--include-paths', action='store_true', help='Opt in to origin/path labels; queries, userinfo and fragments remain excluded')
    r.add_argument('--max-requests', type=int)
    r.add_argument('--max-body-kib', type=float, help='Budget for captured response-body bytes; requires complete body-size coverage')
    r.add_argument('--max-wait-p95-ms', type=float, help='Budget for the HAR response-wait phase p95; incomplete/inconsistent measurements fail verification')
    r.add_argument('--max-errors', type=int, help='Budget for HTTP status >=400 plus status 0')
    r.add_argument('--json', action='store_true')
    r.add_argument('--output', help='Optional fresh offline HTML network report')
    r = sub.add_parser('har-demo', help='Create a clearly labelled synthetic browser-network report')
    r.add_argument('--output', required=True)
    r = sub.add_parser('har-compare', help='Compare two saved HAR samples descriptively, with private route matching')
    r.add_argument('before')
    r.add_argument('after')
    r.add_argument('--before-page', type=int)
    r.add_argument('--after-page', type=int)
    r.add_argument('--include-paths', action='store_true', help='Opt in to origin/path labels; queries and URL userinfo stay excluded')
    r.add_argument('--json', action='store_true')
    r.add_argument('--output', help='Fresh offline comparison report')
    r = sub.add_parser('har-compare-demo', help='Create a synthetic before/after network comparison')
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
    r = sub.add_parser('plan', help='Create a balanced, reproducible crossover study protocol')
    r.add_argument('--title', default='Repeated laptop experiment')
    r.add_argument('--workload', required=True)
    r.add_argument('--baseline', default='Original setup')
    r.add_argument('--candidate', default='One deliberate change')
    r.add_argument('--pairs', type=int, default=6)
    r.add_argument('--seconds', type=float, default=60)
    r.add_argument('--interval', type=float, default=.5)
    r.add_argument('--seed', type=int, default=0)
    r.add_argument('--output', required=True)
    r = sub.add_parser('next', help='Show the next condition, or explicitly record its planned capture')
    r.add_argument('manifest')
    r.add_argument('--record', action='store_true', help='Record after you have applied the displayed/planned condition yourself')
    r.add_argument('--json', action='store_true')
    r = sub.add_parser('study', help='Audit repeated runs and bootstrap whole paired runs')
    r.add_argument('manifest')
    r.add_argument('--iterations', type=int, default=2000)
    r.add_argument('--seed', type=int, default=0)
    r.add_argument('--output', help='Optional fresh offline HTML study report')
    r.add_argument('--json', action='store_true')
    r = sub.add_parser('study-demo', help='Write synthetic study traces and an offline report')
    r.add_argument('--directory', required=True, help='Fresh directory for the synthetic protocol and captures')
    r.add_argument('--output', required=True)
    r = sub.add_parser('network-plan', help='Plan balanced repeated browser HAR comparisons')
    r.add_argument('--title', default='Repeated browser experiment')
    for field in ('workload', 'browser', 'cache', 'network'):
        r.add_argument('--' + field, required=True)
    r.add_argument('--baseline', default='Original build')
    r.add_argument('--candidate', default='One deliberate change')
    r.add_argument('--metric', choices=network_study.METRICS, default='wait_p95_ms')
    r.add_argument('--pairs', type=int, default=6)
    r.add_argument('--seed', type=int, default=0)
    r.add_argument('--page', type=int)
    r.add_argument('--output', required=True)
    r = sub.add_parser('network-next', help='Show the next manual HAR export in the planned order')
    r.add_argument('manifest')
    r.add_argument('--json', action='store_true')
    r = sub.add_parser('network-study', help='Audit repeated HAR captures and gate paired metric growth')
    r.add_argument('manifest')
    r.add_argument('--iterations', type=int, default=2000)
    r.add_argument('--seed', type=int, default=0)
    r.add_argument('--max-growth', type=float, help='Maximum candidate-minus-baseline growth in the selected metric units; uncertainty cannot pass')
    r.add_argument('--json', action='store_true')
    r.add_argument('--output', help='Optional fresh offline HTML report')
    r = sub.add_parser('network-study-demo', help='Write a synthetic paired HAR experiment and interactive report')
    r.add_argument('--directory', required=True)
    r.add_argument('--output', required=True)
    b = sub.add_parser('bundle', help='Create or verify a portable measurement-only browser experiment')
    actions = b.add_subparsers(dest='bundle_action', required=True)
    r = actions.add_parser('create', help='Withhold descriptions/private HAR fields, shift dates and verify preserved measurements')
    r.add_argument('manifest')
    r.add_argument('--iterations', type=int, default=2000)
    r.add_argument('--seed', type=int, default=0)
    r.add_argument('--max-growth', type=float)
    r.add_argument('--output', required=True, help='Fresh .rlb archive; never overwritten')
    r.add_argument('--json', action='store_true')
    r = actions.add_parser('verify', help='Check bounded archive contents and reanalyse; never extract or execute archive code')
    r.add_argument('bundle')
    r.add_argument('--max-growth', type=float, help='Override the stored growth budget for fresh verified analysis')
    r.add_argument('--output', help='Fresh offline report generated from verified reanalysis')
    r.add_argument('--json', action='store_true')
    sub.add_parser('doctor', help='Show native capture capabilities')
    return p

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        for output in (getattr(args, 'output', None), getattr(args, 'trace_output', None)):
            if output and (Path(output).exists() or Path(output).is_symlink()):
                raise ValueError('Output already exists; choose a fresh filename')
        if args.action == 'bundle':
            if args.bundle_action == 'create':
                result = bundle.create(args.manifest, args.output, iterations=args.iterations, seed=args.seed, max_growth=args.max_growth)
                print(json.dumps(result, indent=2, allow_nan=False) if args.json else 'Measurement-only bundle saved: ' + args.output + '\nSHA-256: ' + result['sha256'] + '\n' + bundle.README.decode())
                return 0
            result = bundle.verify(args.bundle, max_growth=args.max_growth)
            if args.output: create_network_study(result, args.output)
            if args.json: print(json.dumps(result, indent=2, allow_nan=False))
            else:
                print('Bundle integrity verified; ' + result['verdict'])
                print('Growth gate: ' + result['gate']['state'])
                print(result['bundle']['interpretation'])
                if args.output: print('Fresh verified report saved: ' + args.output)
            return result['exit_code']
        if args.action == 'network-plan':
            manifest = network_study.plan(args.title, args.workload, args.browser, args.cache, args.network, **{key: getattr(args, key) for key in ('baseline', 'candidate', 'metric', 'pairs', 'seed', 'page')})
            network_study.save(manifest, args.output)
            print('Network protocol saved: ' + args.output)
            print('Run reclaimlab network-next with this manifest; export each fresh HAR manually in the displayed order.')
            return 0
        if args.action == 'network-next':
            slot = network_study.next_capture(args.manifest)
            print(json.dumps(slot or {'complete': True, 'instructions': 'All files exist; run network-study to audit them.'}, indent=2))
            return 0
        if args.action in {'network-study', 'network-study-demo'}:
            if args.action == 'network-study-demo':
                result = network_study.evaluate(network_study.write_demo(args.directory))
            else:
                result = network_study.evaluate(args.manifest, args.iterations, args.seed, args.max_growth)
            if args.output: create_network_study(result, args.output)
            if getattr(args, 'json', False): print(json.dumps(result, indent=2, allow_nan=False))
            else:
                print(('Synthetic demonstration: ' if result['synthetic'] else '') + result['verdict'])
                print(f"Compatible pairs: {result['valid_pairs']}/{result['planned_pairs']}; mean change: {result['mean_delta']} {result['unit']}")
                print(f"Descriptive paired-bootstrap interval: {result['bootstrap_interval95']}; growth gate: {result['gate']['state']}")
                for reason in result['incompatible'] + result['context']: print('- ' + reason)
                if args.output: print('Offline experiment report saved: ' + args.output)
                print(result['interpretation'])
            return result['exit_code']
        if args.action == 'record':
            result = record(args.output, args.seconds, args.interval, args.label, args.processes, args.interactive, workload=args.workload)
            print(f"Saved {result['samples']} samples: {args.output}")
            return 130 if result['interrupted'] else 0
        if args.action == 'doctor':
            source = collector()
            s = source.snapshot()
            print(json.dumps({'platform': platform.system(), 'backend': source.name, 'cpu_counters': bool(s.get('cpu')), 'memory_available': s.get('memory_available') is not None, 'psi': bool(s.get('psi', {}).get('memory')), 'disk_counters': bool(s.get('disks')), 'thermal': s.get('temperature_c') is not None, 'power': s['power'], 'process_names_default': False, **source.description()}, indent=2))
            return 0
        if args.action in {'har-compare', 'har-compare-demo'}:
            result = har_compare.synthetic() if args.action == 'har-compare-demo' else har_compare.load(args.before, args.after, before_page=args.before_page, after_page=args.after_page, include_paths=args.include_paths)
            if args.output:
                create_network_compare(result, args.output)
            if getattr(args, 'json', False):
                print(json.dumps(result, indent=2, allow_nan=False))
            else:
                print('Synthetic demonstration' if result['synthetic'] else 'Descriptive HTTP capture comparison')
                print(f"{result['summary']['routes']} route groups; {result['summary']['added']} added; {result['summary']['removed']} removed")
                for name, metric in result['delta'].items():
                    print(f"{name}: {metric['before']} -> {metric['after']}; change: {metric['change']}")
                print(result['interpretation'])
            return 0
        if args.action in {'har', 'har-demo'}:
            if args.action == 'har-demo':
                result = har.analyse(har.synthetic(), include_paths=True)
            else:
                result = har.load(args.capture, **{key: getattr(args, key) for key in ('page', 'include_paths', 'max_requests', 'max_body_kib', 'max_wait_p95_ms', 'max_errors')})
            if args.output:
                create_network(result, args.output)
            if getattr(args, 'json', False):
                print(json.dumps(result, indent=2, allow_nan=False))
            else:
                summary = result['summary']
                print('Synthetic network demo' if result['synthetic'] else 'Captured browser HTTP activity')
                print(f"{summary['requests']} requests; {summary['known_body_bytes']} known response-body bytes ({summary['body_known_requests']}/{summary['requests']} measured); wait p95: {summary['wait_p95_ms']} ms")
                print('Budgets: ' + result['verdict'])
                for issue in result['findings']:
                    print(f"[{issue['severity']}] {issue['rule']}: {issue['message']}")
                if args.output:
                    print('Offline network report saved: ' + args.output)
                print(result['interpretation'])
            return int(any(b['state'] != 'pass' for b in result['budgets']))
        if args.action == 'demo':
            trace = synthetic()
            create(trace, args.output, comparison=compare(trace, synthetic('Synthetic comparison', improved=True)))
            if args.trace_output:
                with exclusive(args.trace_output) as stream:
                    for row in [trace['header'], *trace['samples'], *trace['markers'], trace['footer']]:
                        write_row(stream, row)
            print(f'Synthetic demo saved: {args.output}')
            return 0
        if args.action == 'plan':
            manifest = study.plan(args.title, args.workload, args.baseline, args.candidate, args.pairs, args.seconds, args.interval, args.seed)
            study.save(manifest, args.output)
            print(f'Saved {args.pairs} paired runs ({args.pairs * 2} captures): {args.output}')
            print('Use reclaimlab next with this manifest to inspect the next condition. Apply it yourself before using --record.')
            return 0
        if args.action == 'next':
            slot = study.next_capture(args.manifest)
            if slot is None:
                print(json.dumps({'complete': True}) if args.json else 'All planned capture files exist. Run reclaimlab study to audit compatibility.')
                return 0
            capture = slot['manifest']['capture']
            result = {key: slot[key] for key in ('pair', 'condition', 'path', 'description')}
            result.update(capture, complete=False, protocol=slot['stamp']['protocol'])
            if not args.json:
                print(f"Next: {slot['pair']} / {slot['condition']} — {slot['description']}")
            if args.record:
                recorded = record(slot['target'], seconds=capture['seconds'], interval=capture['interval'], label=slot['pair'] + ' / ' + slot['condition'], workload=slot['manifest']['workload'], study_stamp=slot['stamp'])
                result['recording'] = recorded
                if args.json:
                    print(json.dumps(result, allow_nan=False))
                else:
                    print(f"Saved planned capture: {slot['path']}")
                return 130 if recorded['interrupted'] else 0
            print(json.dumps(result, indent=2) if args.json else 'Apply this condition yourself, reproduce the same task, then run this command with --record. No settings are changed automatically.')
            return 0
        if args.action == 'study-demo':
            from .demo import write_study
            manifest_path = write_study(args.directory)
            create_study(study.evaluate(manifest_path), args.output)
            print(f'Synthetic study report saved: {args.output}')
            return 0
        if args.action == 'study':
            result = study.evaluate(args.manifest, args.iterations, args.seed)
            if args.output:
                create_study(result, args.output)
            if args.json:
                print(json.dumps(result, indent=2, allow_nan=False))
            else:
                print(result['verdict'])
                print(f"Compatible pairs: {result['valid_pairs']}/{result['planned_pairs']}; mean p95 change: {result['mean_delta_ms']} ms")
                print(f"Descriptive paired-bootstrap interval: {result['bootstrap_interval95_ms']}")
                for reason in result['incompatible'] + result['context']:
                    print('- ' + reason)
                print(result['interpretation'])
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
