"""Protocol integrity, run-level inference and usable offline study workflows."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from reclaimlab import study
from reclaimlab.cli import main
from reclaimlab.demo import synthetic
from reclaimlab.record import record
from reclaimlab.report import create_study
from reclaimlab.trace import exclusive, load, write_row


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def write_trace(self, path, trace):
        if path.exists():
            path.unlink()  # Only a test fixture is replaced.
        with exclusive(path) as stream:
            for row in [trace['header'], *trace['samples'], *trace['markers'], trace['footer']]:
                write_row(stream, row)

    def complete(self, count=6, deltas=None, workload='fixed repeated task'):
        manifest = study.plan('Controlled synthetic fixture', workload, pairs=count)
        path = self.root / 'study.json'
        study.save(manifest, path)
        pair_index = {p['id']: i for i, p in enumerate(manifest['pairs'])}
        for index, slot in enumerate(study.schedule(manifest)):
            trace = synthetic(seed=700 + index)
            trace['header'].update(workload=workload, created_utc=(datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index * 90)).isoformat(), study={'protocol': study.fingerprint(manifest), 'pair': slot['pair'], 'condition': slot['condition']})
            delta = deltas[pair_index[slot['pair']]] if deltas else -30
            value = 100 + (delta if slot['condition'] == 'candidate' else 0)
            for sample in trace['samples']:
                sample['wake_lag_ms'] = [value] * 10
            self.write_trace(study.resolve(self.root, slot['path']), trace)
        return path, manifest

    def change(self, manifest, index, condition, callback):
        path = study.resolve(self.root, manifest['pairs'][index][condition])
        trace = load(path)
        callback(trace)
        self.write_trace(path, trace)

    def cli(self, args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(args)
        return code, output.getvalue(), errors.getvalue()

    def test_plan_is_reproducible_balanced_and_has_unique_capture_paths(self):
        a = study.plan('test', 'task', seed=42)
        self.assertEqual(a, study.plan('test', 'task', seed=42))
        self.assertEqual(sum(p['order'][0] == 'baseline' for p in a['pairs']), 3)
        self.assertEqual(len({slot['path'] for slot in study.schedule(a)}), 12)
        odd = study.plan('test', 'task', pairs=5)
        self.assertLessEqual(abs(sum(p['order'][0] == 'baseline' for p in odd['pairs']) * 2 - 5), 1)

    def test_missing_captures_are_audited_without_a_directional_verdict(self):
        path = self.root / 'study.json'
        study.save(study.plan('test', 'task'), path)
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report['verdict'], 'not comparable')
        self.assertEqual(report['valid_pairs'], 0)
        self.assertEqual(len(report['pairs']), 6)
        self.assertFalse(report['protocol_bound'])

    def test_consistent_paired_change_is_reproducible_and_bound(self):
        path, _ = self.complete()
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report, study.evaluate(path, iterations=500))
        self.assertEqual(report['verdict'], 'consistent lower measured wake delay')
        self.assertEqual(report['mean_delta_ms'], -30)
        self.assertEqual(report['bootstrap_interval95_ms'], [-30, -30])
        self.assertTrue(report['synthetic'])
        self.assertTrue(report['protocol_bound'])

    def test_regression_and_small_change_have_distinct_verdicts(self):
        path, manifest = self.complete(deltas=[40] * 6)
        self.assertEqual(study.evaluate(path, iterations=500)['verdict'], 'consistent higher measured wake delay')
        for index in range(6):
            self.change(manifest, index, 'candidate', lambda t: [s.update(wake_lag_ms=[99] * 10) for s in t['samples']])
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report['mean_delta_ms'], -1)
        self.assertEqual(report['verdict'], 'inconclusive')

    def test_each_pair_has_equal_weight_despite_different_observation_counts(self):
        path, manifest = self.complete(count=4, deltas=[-30, -30, -30, 30])
        for condition in ('baseline', 'candidate'):
            self.change(manifest, 3, condition, lambda t: [s.update(wake_lag_ms=s['wake_lag_ms'] * 10) for s in t['samples']])
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report['mean_delta_ms'], -15)
        self.assertEqual(report['valid_pairs'], 4)
        self.assertIn('one resampling unit', report['interpretation'])

    def test_duplicated_samples_remain_duplicates_after_header_changes(self):
        path, manifest = self.complete()
        original = load(self.root / manifest['pairs'][0]['baseline'])['samples']
        self.change(manifest, 1, 'baseline', lambda t: t.update(samples=copy.deepcopy(original)))
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report['verdict'], 'not comparable')
        self.assertTrue(any('reused' in message for message in report['incompatible']))

    def test_hardware_and_power_changes_between_otherwise_valid_pairs_block_pooling(self):
        path, manifest = self.complete()
        for condition in ('baseline', 'candidate'):
            self.change(manifest, 2, condition, lambda t: t['header']['hardware'].update(memory_bytes=8 * 1024**3))
            self.change(manifest, 3, condition, lambda t: [s['metrics'].update(power='battery') for s in t['samples']])
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report['verdict'], 'not comparable')
        self.assertTrue(any('across the study' in message for message in report['incompatible']))

    def test_protocol_edits_are_detected_and_captures_are_never_overwritten(self):
        path, manifest = self.complete()
        manifest['conditions']['candidate'] = 'Changed after capture'
        path.write_text(json.dumps(manifest))
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report['verdict'], 'not comparable')
        self.assertFalse(report['protocol_bound'])
        with self.assertRaisesRegex(ValueError, 'another protocol'):
            study.next_capture(path)

    def test_capture_order_and_time_overlap_are_verified(self):
        path, manifest = self.complete()
        self.change(manifest, 2, 'baseline', lambda t: t['header'].update(created_utc='2025-01-01T00:00:00+00:00'))
        report = study.evaluate(path, iterations=500)
        self.assertTrue(any('overlap' in message for message in report['incompatible']))

    def test_missing_timestamps_and_workload_mismatch_block_pair(self):
        path, manifest = self.complete()
        self.change(manifest, 0, 'candidate', lambda t: t['header'].update(workload='different task', created_utc='not a timestamp'))
        report = study.evaluate(path, iterations=500)
        self.assertTrue(any('timestamp' in message for message in report['incompatible']))
        self.assertTrue(any('workload' in message for message in report['incompatible']))

    def test_missing_protocol_stamps_are_explicit_context(self):
        path, manifest = self.complete()
        self.change(manifest, 0, 'candidate', lambda t: t['header'].pop('study'))
        report = study.evaluate(path, iterations=500)
        self.assertFalse(report['protocol_bound'])
        self.assertTrue(any('no protocol stamp' in message for message in report['context']))

    def test_insufficient_pairs_and_one_sided_capture_orders_block_verdict(self):
        path, manifest = self.complete(count=2)
        self.assertEqual(study.evaluate(path, iterations=500)['verdict'], 'not comparable')
        for pair in manifest['pairs']:
            pair['order'] = ['baseline', 'candidate']
        path.write_text(json.dumps(manifest))
        self.assertTrue(any('Both baseline-first' in message for message in study.evaluate(path, iterations=500)['incompatible']))

    def test_order_effects_are_reported_and_direction_withheld(self):
        path, manifest = self.complete()
        for index, pair in enumerate(manifest['pairs']):
            value = 10 if pair['order'][0] == 'baseline' else 110
            self.change(manifest, index, 'candidate', lambda t, v=value: [s.update(wake_lag_ms=[v] * 10) for s in t['samples']])
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report['verdict'], 'inconclusive')
        self.assertTrue(any('opposite' in message for message in report['context']))

    def test_corrupt_incomplete_or_dropped_captures_are_not_silently_removed(self):
        path, manifest = self.complete()
        self.change(manifest, 1, 'baseline', lambda t: t['footer'].update(dropped_wake_samples=1))
        (self.root / manifest['pairs'][2]['candidate']).write_text('not json')
        report = study.evaluate(path, iterations=500)
        self.assertEqual(report['planned_pairs'], 6)
        self.assertEqual(report['valid_pairs'], 4)
        self.assertEqual(report['verdict'], 'not comparable')
        self.assertIsNone(report['bootstrap_interval95_ms'])

    def test_manifest_and_trace_resource_limits_fail_before_trace_loading(self):
        path, _ = self.complete()
        with mock.patch('reclaimlab.study.MAX_STUDY_BYTES', 1), mock.patch('reclaimlab.study.load') as reader:
            with self.assertRaisesRegex(ValueError, '128 MiB'):
                study.evaluate(path)
            reader.assert_not_called()
        with mock.patch('reclaimlab.study.MAX_MANIFEST', 16):
            with self.assertRaisesRegex(ValueError, '256 KiB'):
                study.read_manifest(path)

    def test_manifest_paths_and_bounds(self):
        original = study.plan('test', 'task')
        for path in ('../escape', '/absolute', 'C:/outside', 'a\\b', './capture', 'a/../capture'):
            manifest = copy.deepcopy(original)
            manifest['pairs'][0]['baseline'] = path
            with self.assertRaises(ValueError):
                study.validate(manifest)
        for pairs in (True, 1, 21):
            with self.assertRaises(ValueError):
                study.plan('test', 'task', pairs=pairs)
        with self.assertRaises(ValueError):
            study.plan('test', ' ' * 300 + 'task')
        with self.assertRaises(ValueError):
            study.plan('test', 'task', candidate='control\x1b[2J')

    def test_symlink_capture_is_refused(self):
        path, manifest = self.complete()
        target = self.root / manifest['pairs'][0]['baseline']
        target.unlink()
        try:
            target.symlink_to(self.root / manifest['pairs'][0]['candidate'])
        except OSError:
            self.skipTest('Symlink creation unavailable')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            study.evaluate(path)

    def test_next_is_read_only_unless_record_is_explicit(self):
        path = self.root / 'study.json'
        study.save(study.plan('test', 'task'), path)
        with mock.patch('reclaimlab.cli.record') as recorder:
            code, output, _ = self.cli(['next', str(path), '--json'])
            self.assertEqual(code, 0)
            self.assertFalse(json.loads(output)['complete'])
            recorder.assert_not_called()
            recorder.return_value = {'samples': 120, 'interrupted': False, 'seconds': 60}
            code, _, _ = self.cli(['next', str(path), '--record', '--json'])
            self.assertEqual(code, 0)
            self.assertEqual(recorder.call_args.kwargs['workload'], 'task')
            self.assertEqual(recorder.call_args.kwargs['study_stamp']['protocol'], study.fingerprint(study.read_manifest(path)))

    def test_complete_next_and_plan_output_collision(self):
        path, _ = self.complete()
        code, output, _ = self.cli(['next', str(path), '--json'])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)['complete'])
        code, _, _ = self.cli(['plan', '--workload', 'task', '--output', str(path)])
        self.assertEqual(code, 2)

    def test_record_rejects_invalid_protocol_stamp_before_native_access(self):
        backend = mock.Mock()
        with self.assertRaises(ValueError):
            record(self.root / 'no-file', backend=backend, study_stamp={'protocol': 'invalid'})
        backend.snapshot.assert_not_called()
        self.assertFalse((self.root / 'no-file').exists())

    def test_study_cli_json_and_report_collision(self):
        path, _ = self.complete()
        output = self.root / 'study.html'
        code, text, _ = self.cli(['study', str(path), '--iterations', '500', '--output', str(output), '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)['valid_pairs'], 6)
        with mock.patch('reclaimlab.study.evaluate') as evaluator:
            code, _, _ = self.cli(['study', str(path), '--output', str(output)])
            self.assertEqual(code, 2)
            evaluator.assert_not_called()

    def test_study_report_inert_data_and_template_token_boundaries(self):
        path, _ = self.complete()
        report = study.evaluate(path, iterations=500)
        payload = '</script><script>throw new Error("injected")</script>__TITLE__ __DATA__'
        report['title'] = payload
        report['conditions']['candidate'] = payload
        output = self.root / 'safe.html'
        create_study(report, output)
        text = output.read_text()
        raw = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', text, re.S)[1]
        self.assertNotIn('</script>', raw)
        self.assertEqual(json.loads(raw)['title'], payload)
        self.assertEqual(json.loads(raw)['conditions']['candidate'], payload)
        self.assertNotIn('innerHTML', text)
        self.assertIn("connect-src 'none'", text)
        with self.assertRaises(FileExistsError):
            create_study(report, output)

    @unittest.skipUnless(shutil.which('node'), 'JavaScript runtime unavailable')
    def test_offline_chart_modes_filter_and_hover_execute(self):
        path, _ = self.complete()
        output = self.root / 'interactive.html'
        create_study(study.evaluate(path, iterations=500), output)
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8');
const raw=html.match(/<script type="application\/json" id="report-data">([\s\S]*?)<\/script>/)[1];
function node(){let value='';const n={children:[],style:{},checked:false,appendChild(x){this.children.push(x)},setAttribute(k,v){this[k]=v},getContext(){return new Proxy({},{get(){return ()=>{}}})},getBoundingClientRect(){return {width:800,height:320,left:0,top:0}}};Object.defineProperty(n,'textContent',{get(){return value},set(x){value=x;this.children=[]}});return n;}
const nodes={};for(const match of html.matchAll(/id="([^"]+)"/g))nodes[match[1]]=node();nodes['report-data'].textContent=raw;
const sandbox={document:{getElementById(id){assert(nodes[id],id);return nodes[id]},createElement:node},window:{devicePixelRatio:1,addEventListener(){}},console};
vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],sandbox);
assert.equal(nodes.pairs.children.length,6);nodes['mode-values'].onclick();assert.equal(nodes['mode-values']['aria-pressed'],'true');
nodes['pairs-chart'].onmousemove({clientY:50});assert(nodes.readout.textContent.includes('baseline'));
nodes.attention.checked=true;nodes.attention.onchange();assert.equal(nodes.pairs.children.length,0);assert.equal(nodes['pairs-chart'].onmousemove,null);
nodes.attention.checked=false;nodes.attention.onchange();nodes['mode-delta'].onclick();assert.equal(nodes.pairs.children.length,6);assert.equal(nodes['mode-delta']['aria-pressed'],'true');
'''
        result = subprocess.run(['node', '-e', script, str(output)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_bootstrap_budget_is_rejected(self):
        path, _ = self.complete()
        for iterations in (True, 499, 10001):
            with self.assertRaises(ValueError):
                study.evaluate(path, iterations=iterations)


if __name__ == '__main__':
    unittest.main()
