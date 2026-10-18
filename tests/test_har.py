"""HAR math, metric coverage, private exports and real report interactions."""
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

from reclaimlab import har
from reclaimlab.cli import main
from reclaimlab.report import create_network


def entry(start=0, duration=100, url='https://example.invalid/app.js', **changes):
    value = {'startedDateTime': (datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=start)).isoformat(), 'time': duration, 'request': {'url': url, 'method': 'GET'}, 'response': {'status': 200, 'bodySize': 1000, 'headersSize': 200, 'content': {'size': 2000, 'mimeType': 'text/javascript'}}, 'timings': {'blocked': 0, 'dns': 0, 'connect': 0, 'ssl': -1, 'send': 0, 'wait': duration * .9, 'receive': duration * .1}}
    value.update(changes)
    return value


def archive(*entries):
    return {'log': {'version': '1.2', 'entries': list(entries) or [entry()]}}


class HARTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def save(self, data, name='capture.har'):
        path = self.root / name
        path.write_text(json.dumps(data))
        return path

    def cli(self, args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(args)
        return code, output.getvalue(), errors.getvalue()

    def test_interval_union_counts_overlap_and_shared_endpoints_once(self):
        result = har.analyse(archive(entry(0, 100), entry(50, 100), entry(150, 50)))
        summary = result['summary']
        self.assertEqual(summary['span_ms'], 200)
        self.assertEqual(summary['busy_ms'], 200)
        self.assertEqual(summary['idle_ms'], 0)
        self.assertEqual(summary['peak_inflight'], 2)
        self.assertEqual(summary['known_body_bytes'], 3000)
        self.assertEqual(summary['known_message_bytes'], 3600)

    def test_gaps_and_zero_duration_requests_do_not_invent_concurrency(self):
        summary = har.analyse(archive(entry(0, 10), entry(20, 10), entry(30, 0)))['summary']
        self.assertEqual((summary['busy_ms'], summary['idle_ms'], summary['peak_inflight']), (20, 10, 1))

    def test_tls_is_a_subset_of_connect_and_not_double_counted(self):
        row = entry(duration=150)
        row['timings'].update(connect=80, ssl=50, wait=60, receive=10)
        result = har.analyse(archive(row), max_wait_p95_ms=100)
        self.assertEqual(result['summary']['timing_mismatches'], 0)
        self.assertEqual(result['summary']['span_ms'], 150)
        self.assertEqual(result['requests'][0]['ssl_in_connect_ms'], 50)
        self.assertEqual(result['verdict'], 'within budgets')
        row['timings']['ssl'] = 90
        bad = har.analyse(archive(row), max_wait_p95_ms=100)
        self.assertEqual(bad['budgets'][0]['state'], 'unknown')

    def test_unknown_bytes_waits_and_durations_never_become_zero_or_pass(self):
        row = entry()
        row['response']['bodySize'] = -1
        row['response']['headersSize'] = -1
        row['timings']['wait'] = -1
        row['time'] = -1
        result = har.analyse(archive(row), max_body_kib=999, max_wait_p95_ms=999)
        self.assertEqual({b['state'] for b in result['budgets']}, {'unknown'})
        self.assertIsNone(result['summary']['wait_p95_ms'])
        self.assertIsNone(result['summary']['span_ms'])
        self.assertIsNone(result['summary']['peak_inflight'])
        self.assertEqual(result['summary']['body_known_requests'], 0)
        self.assertIsNone(result['requests'][0]['message_bytes'])
        self.assertEqual(result['verdict'], 'insufficient data')

    def test_zero_cached_body_size_is_a_known_measurement(self):
        row = entry()
        row['response'].update(status=304, bodySize=0)
        result = har.analyse(archive(row), max_body_kib=0, max_errors=0)
        self.assertEqual(result['verdict'], 'within budgets')
        self.assertEqual(result['summary']['body_known_requests'], 1)
        self.assertEqual(result['summary']['known_body_bytes'], 0)

    def test_partial_sizes_remain_known_subtotals_and_budget_is_unverifiable(self):
        unknown = entry(200)
        unknown['response'].pop('bodySize')
        result = har.analyse(archive(entry(), unknown), max_body_kib=1000)
        self.assertEqual(result['summary']['known_body_bytes'], 1000)
        self.assertEqual(result['summary']['body_known_requests'], 1)
        self.assertIsNone(result['budgets'][0]['measured'])

    def test_budget_failures_and_capture_errors_are_distinct_from_parse_errors(self):
        bad = entry(200)
        bad['response']['status'] = 503
        failed = entry(400)
        failed['response']['status'] = 0
        result = har.analyse(archive(entry(), bad, failed), max_requests=2, max_body_kib=1, max_errors=0)
        self.assertEqual(result['verdict'], 'budget exceeded')
        self.assertEqual([b['state'] for b in result['budgets']], ['fail', 'fail', 'fail'])
        self.assertEqual(result['summary']['http_errors'], 1)
        self.assertEqual(result['summary']['failed_requests'], 1)

    def test_headers_cookies_bodies_urls_and_export_metadata_are_discarded(self):
        row = entry(url='https://fixture-user:fixture-pass@private.example.invalid/private-path?token=PRIVATE_QUERY#PRIVATE_FRAGMENT')
        row['request'].update(headers=[{'name': 'Authorization', 'value': 'PRIVATE_HEADER'}], cookies=[{'name': 'session', 'value': 'PRIVATE_COOKIE'}], postData={'text': 'PRIVATE_REQUEST_BODY'})
        row['response']['content']['text'] = 'PRIVATE_RESPONSE_BODY'
        row.update(serverIPAddress='192.0.2.5', _initiator={'url': 'PRIVATE_STACK'})
        raw = archive(row)
        raw['log'].update(creator={'name': 'PRIVATE_CREATOR'}, pages=[{'id': 'private-id', 'title': 'PRIVATE_TITLE'}])
        serialized = json.dumps(har.analyse(raw))
        for value in ['PRIVATE_', 'fixture-user', 'fixture-pass', 'private.example.invalid', 'private-path', 'private-id', '192.0.2.5', '2025-01-01']:
            self.assertNotIn(value, serialized)
        names = json.dumps(har.analyse(raw, include_paths=True))
        self.assertIn('https://private.example.invalid/private-path', names)
        for value in ['PRIVATE_', 'fixture-user', 'fixture-pass', 'private-id']:
            self.assertNotIn(value, names)

    def test_repeat_groups_are_query_sensitive_and_do_not_merge_credentials(self):
        rows = [entry(url='https://example.invalid/api?q=1'), entry(100, url='https://example.invalid/api?q=2'), entry(200, url='https://example.invalid/api?q=1#fragment'), entry(300, url='https://different:identity@example.invalid/api?q=1')]
        result = har.analyse(archive(*rows))
        self.assertEqual([group['request_ids'] for group in result['repeated_gets']], [[1, 3]])
        self.assertNotIn('q=1', json.dumps(result))

    def test_multi_page_exports_require_explicit_scope(self):
        data = archive(entry(pageref='one'), entry(1000, pageref='two'))
        data['log']['pages'] = [{'id': 'one'}, {'id': 'two'}]
        with self.assertRaises(ValueError):
            har.analyse(data)
        result = har.analyse(data, page=2, max_requests=1)
        self.assertEqual(result['summary']['requests'], 1)
        self.assertEqual(result['scope']['entries_outside_selected_page'], 1)
        self.assertEqual(result['requests'][0]['start_ms'], 0)
        self.assertEqual(result['requests'][0]['id'], 2)
        self.assertEqual(result['verdict'], 'within budgets')
        data['log'].pop('pages')
        with self.assertRaises(ValueError):
            har.analyse(data)

    def test_non_http_entries_are_counted_as_excluded(self):
        result = har.analyse(archive(entry(url='data:text/plain,ignored'), entry()))
        self.assertEqual(result['scope']['excluded_non_http_entries'], 1)
        self.assertEqual(result['summary']['requests'], 1)

    def test_extension_http_methods_remain_valid(self):
        row = entry()
        row['request']['method'] = 'VERSION-CONTROL'
        self.assertEqual(har.analyse(archive(row))['requests'][0]['method'], 'VERSION-CONTROL')

    def test_malformed_metrics_timestamps_urls_and_shapes_fail_without_raw_values(self):
        for field, value in [('bodySize', float('nan')), ('bodySize', -2), ('bodySize', True), ('bodySize', 1.2), ('status', True), ('status', 600)]:
            row = entry()
            row['response'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                har.analyse(archive(row))
        for changes in [{'startedDateTime': '2025-01-01T00:00:00'}, {'time': float('inf')}, {'request': {'url': 'https://[PRIVATE_INVALID', 'method': 'GET'}}, {'timings': {'wait': True}}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                har.analyse(archive(entry(**changes)))
        for changes in [{'version': '1.1'}, {'entries': []}, {'pages': [{'id': 'same'}, {'id': 'same'}]}]:
            data = archive()
            data['log'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                har.analyse(data)

    def test_bad_limits_and_budget_values_fail_explicitly(self):
        for value in [float('nan'), -1, True, float('inf')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                har.analyse(archive(), max_body_kib=value)
        for value in [1.1, True]:
            with self.assertRaises(ValueError):
                har.analyse(archive(), max_requests=value)
        with mock.patch.object(har, 'MAX_ENTRIES', 1), self.assertRaises(ValueError):
            har.analyse(archive(entry(), entry()))
        path = self.save(archive())
        with mock.patch.object(har, 'MAX_BYTES', 10), self.assertRaises(ValueError):
            har.load(path)
        path.write_text('{invalid json')
        with self.assertRaisesRegex(ValueError, '^Invalid HAR JSON$'):
            har.load(path)

    def test_symlink_input_is_refused(self):
        path = self.save(archive())
        link = self.root / 'link.har'
        try:
            link.symlink_to(path)
        except OSError:
            self.skipTest('Symlinks unavailable')
        with self.assertRaises(ValueError):
            har.load(link)

    def test_cli_exit_codes_reports_and_collision_preflight(self):
        path = self.save(archive())
        code, out, errors = self.cli(['har', str(path), '--max-requests', '0', '--json'])
        self.assertEqual(code, 1, errors)
        self.assertEqual(json.loads(out)['verdict'], 'budget exceeded')
        self.assertEqual(self.cli(['har', str(path), '--max-body-kib', '-1'])[0], 2)
        output = self.root / 'network.html'
        self.assertEqual(self.cli(['har', str(path), '--output', str(output)])[0], 0)
        with mock.patch.object(har, 'load') as load:
            self.assertEqual(self.cli(['har', str(path), '--output', str(output)])[0], 2)
            load.assert_not_called()
        demo = self.root / 'demo.html'
        self.assertEqual(self.cli(['har-demo', '--output', str(demo)])[0], 0)
        self.assertIn('Synthetic demonstration', demo.read_text())

    def test_html_uses_inert_data_and_keeps_template_tokens_literal(self):
        malicious = 'https://example.invalid/</script><script>throw(1)</script>/__DATA__/__TITLE__'
        result = har.analyse(archive(entry(url=malicious)), include_paths=True)
        output = self.root / 'report.html'
        create_network(result, output)
        text = output.read_text()
        self.assertNotIn(malicious, text)
        self.assertNotIn('innerHTML', text)
        embedded = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', text, re.S)[1]
        self.assertEqual(json.loads(embedded), result)
        self.assertEqual(text.count('<script>'), 1)
        self.assertIn("connect-src 'none'", text)

    def test_compact_plugin_data_keeps_coverage_without_full_capture_rows(self):
        result = har.analyse(har.synthetic())
        compact = har.compact(result)
        self.assertNotIn('requests', compact)
        self.assertEqual(compact['summary'], result['summary'])
        self.assertEqual(compact['slowest_waits'][0]['id'], 4)
        self.assertEqual(compact['repeated_get_groups'], 1)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for report interaction checks')
    def test_report_filters_pagination_window_and_details_in_javascript(self):
        data = archive(*(entry(i * 100, url='https://example.invalid/' + str(i) + '.js') for i in range(123)))
        data['log']['entries'][1]['response']['status'] = 503
        report = har.analyse(data)
        output = self.root / 'network.html'
        create_network(report, output)
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8'),raw=html.match(/<script type="application\/json" id="report-data">([\s\S]*?)<\/script>/)[1],source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function node(){let text='';const n={children:[],style:{},value:'',checked:false,appendChild(x){this.children.push(x);return x;}};Object.defineProperty(n,'textContent',{get(){return text},set(value){text=value;this.children=[];}});return n;}
const nodes={};for(const m of html.matchAll(/id="([^"]+)"/g))nodes[m[1]]=node();nodes['report-data'].textContent=raw;nodes['kind-filter'].value='all';nodes['origin-filter'].value='all';nodes['sort-order'].value='start';
const sandbox={document:{getElementById(id){assert(nodes[id],id);return nodes[id];},createElement:node},console};vm.runInNewContext(source,sandbox);
assert.equal(nodes['request-rows'].children.length,50);assert(nodes['page-state'].textContent.includes('1–50'));
nodes['next-page'].onclick();assert(nodes['page-state'].textContent.includes('51–100'));assert.equal(nodes['request-rows'].children.length,50);
nodes['only-errors'].checked=true;nodes['only-errors'].onchange();assert.equal(nodes['request-rows'].children.length,1);assert(nodes['page-state'].textContent.includes('1 matching'));assert.equal(nodes['stat-requests'].textContent,'123');
nodes['only-errors'].checked=false;nodes['only-errors'].onchange();nodes['search'].value='no-match';nodes.search.oninput();assert.equal(nodes['page-state'].textContent,'0 matching requests');
nodes.search.value='';nodes.search.oninput();nodes['time-start'].value='100';nodes['time-end'].value='150';nodes['time-end'].oninput();assert(nodes['page-state'].textContent.includes('2 matching'));
nodes['time-start'].value='200';nodes['time-end'].oninput();assert.equal(nodes['range-label'].textContent,'Invalid time window');nodes['reset-window'].onclick();assert(nodes['page-state'].textContent.includes('123 matching'));
nodes['request-rows'].children[0].children[0].children[0].onclick();assert(nodes.detail.children.length>=3);
"""
        result = subprocess.run(['node', '-e', script, str(output)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
