"""Per-request HAR budgets preserve privacy, scope and unknown evidence."""
import contextlib
import copy
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from reclaimlab import har, har_assets
from reclaimlab.cli import main
from reclaimlab.report import create_network_assets
from test_har import archive, entry


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_demo_scope_summary_and_individual_units(self):
        report = har_assets.analyse(har.synthetic(), max_asset_kib=280000 / 1024, max_duration_ms=595)
        self.assertEqual(report['summary']['requests'], 3)
        self.assertEqual(report['scope']['requests_outside_selected_kinds'], 4)
        self.assertEqual(report['summary']['max_body_bytes'], 280000)
        self.assertEqual(report['summary']['max_duration_ms'], 595)
        self.assertTrue(report['synthetic'])
        self.assertEqual(report['verdict'], 'within budgets')
        self.assertEqual(report['largest_assets'][0]['kind'], 'image')
        self.assertEqual(report['budgets'][0]['measured'], 280000 / 1024)

    def test_budget_covers_records_omitted_from_details(self):
        rows = [entry(index * 1000) for index in range(4)]
        rows[-1]['response']['bodySize'] = 1024 * 1024
        report = har_assets.analyse(archive(*rows), top=1, max_asset_kib=100)
        self.assertEqual(len(report['largest_assets']), 1)
        self.assertEqual(report['summary']['requests'], 4)
        self.assertEqual(report['details_omitted_per_list'], 3)
        self.assertEqual(report['exit_code'], 1)

    def test_unknown_body_is_not_zero_or_a_passing_budget(self):
        unknown = entry(100)
        unknown['response']['bodySize'] = -1
        report = har_assets.analyse(archive(entry(), unknown), max_asset_kib=1000)
        self.assertEqual(report['summary']['known_body_bytes'], 1000)
        self.assertIsNone(report['summary']['max_body_bytes'])
        self.assertEqual(report['budgets'][0]['state'], 'unknown')
        self.assertIsNone(report['budgets'][0]['measured'])
        self.assertEqual(report['budgets'][0]['known_maximum'], 1000 / 1024)
        self.assertEqual(report['exit_code'], 1)

    def test_known_overage_still_fails_with_other_unknowns(self):
        unknown = entry(100)
        unknown['response']['bodySize'] = -1
        report = har_assets.analyse(archive(entry(), unknown), max_asset_kib=.1)
        self.assertEqual(report['budgets'][0]['state'], 'fail')
        self.assertEqual(report['verdict'], 'budget exceeded')

    def test_zero_is_a_known_measurement(self):
        row = entry(duration=0)
        row['response']['bodySize'] = 0
        report = har_assets.analyse(archive(row), max_asset_kib=0, max_duration_ms=0)
        self.assertEqual(report['exit_code'], 0)
        self.assertEqual(report['summary']['max_body_bytes'], 0)
        self.assertEqual(report['summary']['max_duration_ms'], 0)

    def test_missing_or_mismatched_duration_cannot_pass_duration_gate(self):
        for unknown in (False, True):
            row = entry()
            if unknown:
                row['time'] = -1
            else:
                row['timings']['wait'] = 500
            report = har_assets.analyse(archive(row), max_asset_kib=100, max_duration_ms=1000)
            self.assertEqual([b['state'] for b in report['budgets']], ['pass', 'unknown'])
            self.assertIsNone(report['summary']['max_duration_ms'])

    def test_http_errors_prevent_certification_without_changing_known_maxima(self):
        for status in (0, 404, 503):
            row = entry()
            row['response']['status'] = status
            report = har_assets.analyse(archive(row), max_asset_kib=100, max_duration_ms=1000)
            self.assertEqual([b['state'] for b in report['budgets']], ['unknown', 'unknown'])
            self.assertEqual(report['summary']['request_errors'], 1)
            self.assertEqual(report['summary']['known_max_body_bytes'], 1000)

    def test_empty_selection_and_explicit_kind_scope(self):
        report = har_assets.analyse(archive(entry()), kinds=['font'], max_asset_kib=100)
        self.assertEqual(report['summary']['requests'], 0)
        self.assertEqual(report['budgets'][0]['state'], 'unknown')
        report = har_assets.analyse(har.synthetic(), kinds=['data'])
        self.assertEqual(report['summary']['requests'], 3)
        self.assertEqual(report['verdict'], 'not evaluated')
        self.assertEqual(report['exit_code'], 0)

    def test_only_selected_measurements_affect_budgets(self):
        row = entry()
        other = entry(100)
        other['response']['content']['mimeType'] = 'application/json'
        other['response']['bodySize'] = -1
        report = har_assets.analyse(archive(row, other), max_asset_kib=1)
        self.assertEqual(report['exit_code'], 0)
        self.assertEqual(report['scope']['requests_outside_selected_kinds'], 1)

    def test_private_network_fields_never_enter_result(self):
        row = entry(url='https://PRIVATE_USER:PRIVATE_PASSWORD@private.invalid/private-path?token=PRIVATE_QUERY')
        row['request']['headers'] = [{'name': 'Authorization', 'value': 'PRIVATE_HEADER'}]
        row['response']['content']['text'] = 'PRIVATE_BODY'
        row['response']['headers'] = [{'name': 'Set-Cookie', 'value': 'PRIVATE_COOKIE'}]
        row['_initiator'] = {'stack': 'PRIVATE_STACK'}
        report = json.dumps(har_assets.analyse(archive(row)))
        for value in ('PRIVATE_', 'private.invalid', 'private-path', '2025-01-01'):
            self.assertNotIn(value, report)

    def test_multi_page_scope_remains_explicit(self):
        raw = har.synthetic()
        raw['log']['pages'].append({'id': 'second'})
        extra = copy.deepcopy(raw['log']['entries'][1])
        extra['pageref'] = 'second'
        raw['log']['entries'].append(extra)
        with self.assertRaises(ValueError):
            har_assets.analyse(raw)
        report = har_assets.analyse(raw, page=2)
        self.assertEqual(report['summary']['requests'], 1)
        self.assertEqual(report['scope']['entries_outside_selected_page'], 7)

    def test_bad_policies_and_bounds_fail(self):
        for options in ({'kinds': []}, {'kinds': ['script', 'script']}, {'kinds': ['unknown']}, {'top': 0}, {'top': 51}, {'top': True}, {'max_asset_kib': -1}, {'max_asset_kib': math.nan}, {'max_duration_ms': math.inf}, {'max_duration_ms': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                har_assets.analyse(archive(entry()), **options)

    def test_file_and_cli_interfaces(self):
        path = self.root / 'page.har'
        path.write_text(json.dumps(archive(entry())), encoding='utf-8')
        self.assertEqual(har_assets.load(path)['summary']['requests'], 1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['har-assets', str(path), '--max-asset-kib', '.1', '--json'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['verdict'], 'budget exceeded')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['har-assets-demo', '--max-asset-kib', '512', '--max-duration-ms', '1000', '--json'])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())['synthetic'])

    def test_offline_report_is_exclusive_inert_and_preserves_budget_outcome(self):
        report = har_assets.analyse(har.synthetic(), max_asset_kib=1)
        report['largest_assets'][0]['label'] = '</script><img src=x onerror=alert(1)>'
        path = self.root / 'assets.html'
        create_network_assets(report, path)
        text = path.read_text(encoding='utf-8')
        self.assertNotIn('</script><img', text)
        self.assertIn('\\u003c/script\\u003e', text)
        self.assertIn('Content-Security-Policy', text)
        self.assertNotIn('innerHTML', text)
        self.assertNotIn('https://', text)
        with self.assertRaises(FileExistsError):
            create_network_assets(report, path)
        output = io.StringIO()
        target = self.root / 'cli-assets.html'
        with contextlib.redirect_stdout(output):
            code = main(['har-assets-demo', '--max-asset-kib', '1', '--output', str(target), '--json'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['verdict'], 'budget exceeded')
        self.assertTrue(target.is_file())

    @unittest.skipUnless(os.name == 'posix', 'symlinks')
    def test_symlink_files_and_directories_refused(self):
        folder = self.root / 'actual'
        folder.mkdir()
        path = folder / 'page.har'
        path.write_text(json.dumps(archive(entry())))
        (self.root / 'link.har').symlink_to(path)
        (self.root / 'linked').symlink_to(folder, target_is_directory=True)
        for value in (self.root / 'link.har', self.root / 'linked/page.har'):
            with self.assertRaises(ValueError):
                har_assets.load(value)


if __name__ == '__main__':
    unittest.main()
