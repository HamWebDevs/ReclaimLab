"""Paired HAR math, complete audits, private exports and report interactions."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from reclaimlab import network_study as ns
from reclaimlab.cli import main
from reclaimlab.report import create_network_study
from test_har import entry, archive


class NetworkStudyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = main(args)
        return code, out.getvalue(), err.getvalue()

    def complete(self, deltas=None, metric='wait_p95_ms'):
        deltas = [-20] * 6 if deltas is None else deltas
        manifest = ns.plan('Test experiment', 'Fixed navigation', 'Browser 1', 'Fresh cache', 'Fixed network', pairs=len(deltas), metric=metric)
        path = self.root / 'study.json'
        ns.save(manifest, path)
        indices = {pair['id']: i for i, pair in enumerate(manifest['pairs'])}
        (self.root / 'captures').mkdir()
        for i, slot in enumerate(ns.schedule(manifest)):
            pair = indices[slot['pair']]
            wait = 100 + pair + (deltas[pair] if slot['condition'] == 'candidate' else 0)
            row = entry(start=i * 60000, duration=wait + 10)
            row['timings'].update(wait=wait, receive=10)
            row['response']['bodySize'] = 1000 + i
            data = archive(row)
            data['log']['browser'] = {'name': 'Fixture browser', 'version': '1'}
            (self.root / slot['path']).write_text(json.dumps(data))
        return path, manifest

    def change(self, manifest, i, condition, transform):
        path = self.root / manifest['pairs'][i][condition]
        data = json.loads(path.read_text())
        transform(data)
        path.write_text(json.dumps(data))

    def test_reproducible_balanced_plan_and_manual_next(self):
        m = ns.plan('Title', 'Task', 'Browser', 'Cache', 'Network', seed=17)
        self.assertEqual(m, ns.plan('Title', 'Task', 'Browser', 'Cache', 'Network', seed=17))
        self.assertEqual(sum(p['order'][0] == 'baseline' for p in m['pairs']), 3)
        path = self.root / 'new.json'
        ns.save(m, path)
        with mock.patch('reclaimlab.cli.record') as recorder:
            code, output, _ = self.cli(['network-next', str(path), '--json'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)['path'], ns.schedule(m)[0]['path'])
            recorder.assert_not_called()
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_paired_bootstrap_and_budget_are_reproducible(self):
        path, _ = self.complete()
        report = ns.evaluate(path, 500, max_growth=0)
        self.assertEqual(report, ns.evaluate(path, 500, max_growth=0))
        self.assertEqual(report['mean_delta'], -20)
        self.assertEqual(report['bootstrap_interval95'], [-20, -20])
        self.assertEqual(report['verdict'], 'consistent lower captured measurement')
        self.assertEqual(report['gate']['state'], 'pass')
        self.assertEqual(report['exit_code'], 0)
        self.assertIn('unverified', report['interpretation'])

    def test_regression_and_uncertainty_gate_states(self):
        path, _ = self.complete([20] * 6)
        report = ns.evaluate(path, 500, max_growth=10)
        self.assertEqual(report['gate']['state'], 'fail')
        self.assertEqual(report['verdict'], 'consistent higher captured measurement')
        self.assertEqual(report['exit_code'], 1)
        self.assertEqual(ns.evaluate(path, 500)['exit_code'], 0)

    def test_interval_crossing_budget_stays_unknown(self):
        path, _ = self.complete([-20, 20, -20, 20, -20, 20])
        report = ns.evaluate(path, 1000, max_growth=0)
        self.assertLess(report['bootstrap_interval95'][0], 0)
        self.assertGreater(report['bootstrap_interval95'][1], 0)
        self.assertEqual(report['gate']['state'], 'unknown')
        self.assertEqual(report['verdict'], 'inconclusive')

    def test_opposite_capture_order_effects_withhold_direction(self):
        path, manifest = self.complete()
        for i, pair in enumerate(manifest['pairs']):
            delta = -60 if pair['order'][0] == 'baseline' else 5
            def change(data, i=i, delta=delta):
                row = data['log']['entries'][0]
                row['timings']['wait'] = 100 + i + delta
                row['time'] = row['timings']['wait'] + 10
            self.change(manifest, i, 'candidate', change)
        report = ns.evaluate(path, 1000, max_growth=0)
        self.assertEqual(report['order_group_mean_deltas'], {'baseline-first': -60, 'candidate-first': 5})
        self.assertEqual(report['verdict'], 'inconclusive')
        self.assertEqual(report['gate']['state'], 'unknown')

    def test_whole_pairs_have_equal_weight_when_request_counts_differ(self):
        path, manifest = self.complete([-30, -30, -30, 30])
        for condition in ('baseline', 'candidate'):
            def change(data):
                first = data['log']['entries'][0]
                data['log']['entries'] = [copy.deepcopy(first) for _ in range(20)]
            self.change(manifest, 3, condition, change)
        report = ns.evaluate(path, 500)
        self.assertTrue(report['comparable'], report)
        self.assertEqual(report['mean_delta'], -15)

    def test_missing_and_invalid_captures_remain_in_audit(self):
        path, manifest = self.complete()
        (self.root / manifest['pairs'][0]['baseline']).unlink()
        (self.root / manifest['pairs'][2]['candidate']).write_text('invalid json')
        report = ns.evaluate(path, 500, max_growth=10000)
        self.assertEqual(len(report['pairs']), 6)
        self.assertEqual(report['valid_pairs'], 4)
        self.assertFalse(report['comparable'])
        self.assertIsNone(report['bootstrap_interval95'])
        self.assertEqual(report['gate']['state'], 'unknown')
        self.assertEqual(report['exit_code'], 1)

    def test_duplicated_measurements_stay_duplicates_after_retiming(self):
        path, manifest = self.complete()
        source = json.loads((self.root / manifest['pairs'][0]['baseline']).read_text())
        def duplicate(data):
            timestamp = data['log']['entries'][0]['startedDateTime']
            data['log']['entries'] = copy.deepcopy(source['log']['entries'])
            data['log']['entries'][0]['startedDateTime'] = timestamp
        self.change(manifest, 1, 'baseline', duplicate)
        report = ns.evaluate(path, 500)
        self.assertFalse(report['comparable'])
        self.assertTrue(any('reused' in s for s in report['incompatible']))
        self.assertFalse(report['pairs'][0]['valid'])

    def test_overlaps_and_out_of_order_captures_block_aggregation(self):
        path, manifest = self.complete()
        self.change(manifest, 3, 'candidate', lambda d: d['log']['entries'][0].update(startedDateTime='2025-01-01T00:00:00Z'))
        report = ns.evaluate(path, 500)
        self.assertTrue(any('chronological' in s for s in report['incompatible']))
        self.assertIsNone(report['mean_delta'])

    def test_coverage_and_broken_requests_cannot_pass_growth_gate(self):
        path, manifest = self.complete()
        self.change(manifest, 0, 'candidate', lambda d: d['log']['entries'][0]['timings'].update(wait=-1))
        self.change(manifest, 1, 'candidate', lambda d: d['log']['entries'][0]['response'].update(status=503))
        self.change(manifest, 2, 'baseline', lambda d: d['log']['entries'][0].update(time=-1))
        report = ns.evaluate(path, 500, max_growth=1e9)
        self.assertEqual(report['gate']['state'], 'unknown')
        self.assertIsNone(report['pairs'][0]['candidate']['value'])
        messages = ' '.join(report['incompatible'])
        for marker in ('coverage', 'HTTP errors', 'durations'): self.assertIn(marker, messages)

    def test_body_unknown_is_not_zero_but_known_zero_is_valid(self):
        path, manifest = self.complete(metric='body_bytes')
        for i in range(6):
            for condition in ('baseline', 'candidate'):
                self.change(manifest, i, condition, lambda d: d['log']['entries'][0]['response'].update(bodySize=0))
        report = ns.evaluate(path, 500, max_growth=0)
        self.assertEqual(report['mean_delta'], 0)
        self.assertEqual(report['gate']['state'], 'pass')
        self.assertIsNone(report['relative_delta_pct'])
        self.change(manifest, 0, 'candidate', lambda d: d['log']['entries'][0]['response'].update(bodySize=-1))
        report = ns.evaluate(path, 500, max_growth=0)
        self.assertIsNone(report['pairs'][0]['candidate']['value'])
        self.assertEqual(report['gate']['state'], 'unknown')

    def test_browser_metadata_consistency_and_manual_declarations(self):
        path, manifest = self.complete()
        self.change(manifest, 2, 'baseline', lambda d: d['log']['browser'].update(version='2'))
        self.assertFalse(ns.evaluate(path, 500)['comparable'])
        for i in range(6):
            for condition in ('baseline', 'candidate'): self.change(manifest, i, condition, lambda d: d['log'].pop('browser'))
        report = ns.evaluate(path, 500)
        self.assertTrue(report['comparable'])
        self.assertTrue(any('omit browser' in c for c in report['context']))

    def test_synthetic_mixing_blocks_claim_and_demo_is_labelled(self):
        path, manifest = self.complete()
        self.change(manifest, 1, 'candidate', lambda d: d['log'].update(_reclaimlab_synthetic=True))
        report = ns.evaluate(path, 500)
        self.assertTrue(report['synthetic'])
        self.assertFalse(report['comparable'])
        demo = ns.write_demo(self.root / 'demo')
        result = ns.evaluate(demo, 500)
        self.assertEqual(result['exit_code'], 0, result)
        self.assertTrue(result['synthetic'])
        self.assertIsNone(ns.next_capture(demo))
        with self.assertRaises(FileExistsError): ns.write_demo(self.root / 'demo')

    def test_private_urls_and_export_metadata_never_enter_report(self):
        path, manifest = self.complete()
        def private(data):
            data['log']['browser'].update(extra='PRIVATE_BROWSER')
            row = data['log']['entries'][0]
            row['request'].update(url='https://PRIVATE_USER:PRIVATE_PASS@private.example.invalid/PRIVATE_PATH?key=PRIVATE_QUERY', headers=[{'value': 'PRIVATE_HEADER'}], postData={'text': 'PRIVATE_BODY'})
        self.change(manifest, 0, 'candidate', private)
        report = ns.evaluate(path, 500)
        exported = json.dumps(report)
        self.assertNotIn('PRIVATE_', exported)
        self.assertNotIn('private.example.invalid', exported)
        self.assertNotIn('2025-01-01', exported)
        self.assertNotIn('_signature', exported)

    def test_resource_limits_preflight_all_files_before_parsing(self):
        path, _ = self.complete()
        with mock.patch.object(ns, 'MAX_BYTES', 1), mock.patch.object(ns, 'measure') as reader:
            with self.assertRaisesRegex(ValueError, '128 MiB'): ns.evaluate(path, 500)
            reader.assert_not_called()
        with mock.patch.object(ns, 'MAX_MANIFEST', 16):
            with self.assertRaisesRegex(ValueError, '256 KiB'): ns.read(path)

    @unittest.skipUnless(os.name == 'posix', 'symlink support')
    def test_symlink_inputs_are_explicit_incompatible_captures(self):
        path, manifest = self.complete()
        capture = self.root / manifest['pairs'][0]['baseline']
        capture.unlink()
        capture.symlink_to(self.root / manifest['pairs'][0]['candidate'])
        report = ns.evaluate(path, 500)
        self.assertEqual(report['gate']['state'], 'unknown')
        self.assertIn('unsafe', ' '.join(report['incompatible']))

    def test_invalid_protocol_and_sampling_parameters(self):
        path, manifest = self.complete()
        for value in ('../x.har', '/x.har', './x.har', 'a/../x.har', 'x.json', 'a\\x.har'):
            modified = copy.deepcopy(manifest)
            modified['pairs'][0]['baseline'] = value
            with self.assertRaises(ValueError): ns.validate(modified)
        for kw in ({'iterations': True}, {'iterations': 499}, {'seed': -1}, {'max_growth': float('nan')}, {'max_growth': -1}):
            with self.assertRaises(ValueError): ns.evaluate(path, **kw)

    def test_cli_json_and_output_preflight(self):
        path, _ = self.complete()
        output = self.root / 'report.html'
        code, text, errors = self.cli(['network-study', str(path), '--iterations', '500', '--max-growth', '0', '--json', '--output', str(output)])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(text)['gate']['state'], 'pass')
        with mock.patch.object(ns, 'evaluate') as evaluator:
            code, _, _ = self.cli(['network-study', str(path), '--output', str(output)])
            self.assertEqual(code, 2)
            evaluator.assert_not_called()

    def test_report_inert_data_and_single_pass_template_tokens(self):
        path, _ = self.complete()
        report = ns.evaluate(path, 500)
        payload = '</script><script>throw Error("injected")</script>__TITLE__ __DATA__'
        report['title'] = payload
        report['conditions']['candidate'] = payload
        output = self.root / 'safe.html'
        create_network_study(report, output)
        html = output.read_text()
        raw = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)[1]
        self.assertNotIn('</script>', raw)
        self.assertEqual(json.loads(raw)['title'], payload)
        self.assertEqual(json.loads(raw)['conditions']['candidate'], payload)
        self.assertNotIn('innerHTML', html)
        self.assertIn("connect-src 'none'", html)
        with self.assertRaises(FileExistsError): create_network_study(report, output)

    @unittest.skipUnless(shutil.which('node'), 'JavaScript runtime unavailable')
    def test_report_filters_sort_details_preserve_study_totals(self):
        path, _ = self.complete()
        output = self.root / 'interactive.html'
        create_network_study(ns.evaluate(path, 500), output)
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert'),html=fs.readFileSync(process.argv[1],'utf8');
function element(){return {children:[],value:'all',checked:false,hidden:false,textContent:'',handlers:{},classList:{add(){}},setAttribute(k,v){this[k]=v},append(...nodes){this.children.push(...nodes)},replaceChildren(...nodes){this.children=nodes},addEventListener(k,fn){this.handlers[k]=fn}};}
const nodes={};for(const match of html.matchAll(/id="([^"]+)"/g))nodes[match[1]]=element();nodes.data.textContent=html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];nodes.sort.value='planned';
vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],{document:{getElementById:id=>nodes[id],createElement:element,createElementNS:element},console,Intl});
assert.equal(nodes['pair-rows'].children.length,6);assert.equal(nodes.pairs.textContent,'6 / 6');nodes.order.value='baseline';nodes.order.handlers.change();assert.equal(nodes['pair-rows'].children.length,3);assert.equal(nodes.pairs.textContent,'6 / 6');
nodes['pair-rows'].children[0].children[6].children[0].handlers.click();assert.equal(nodes.detail.hidden,false);assert(nodes['detail-data'].textContent.includes('summary'));
nodes.invalid.checked=true;nodes.invalid.handlers.change();assert.equal(nodes['pair-rows'].children.length,0);nodes.reset.handlers.click();assert.equal(nodes['pair-rows'].children.length,6);nodes.sort.value='delta';nodes.sort.handlers.change();assert.equal(nodes['pair-rows'].children.length,6);
'''
        result = subprocess.run(['node', '-e', script, str(output)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__': unittest.main()
