"""Portable evidence preservation, field withholding and hostile archive boundaries."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

from reclaimlab import bundle, network_study as ns
from reclaimlab.cli import main
import test_network_study as fixtures


class BundleTests(unittest.TestCase):
    complete = fixtures.NetworkStudyTests.complete
    change = fixtures.NetworkStudyTests.change

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / 'experiment.rlb'

    def packed(self, **kw):
        path, manifest = self.complete(**kw)
        bundle.create(path, self.output, iterations=500, max_growth=0)
        return path, manifest

    def files(self):
        with zipfile.ZipFile(self.output) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def rewrite(self, files, *, reindex=True, attributes=None):
        if reindex:
            index = bundle.decode(files['bundle.json'])
            index['files'] = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items() if name != 'bundle.json'}
            files['bundle.json'] = bundle.encoded(index)
        with zipfile.ZipFile(self.output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = ((stat.S_IFREG | 0o600) << 16) if attributes is None else attributes
                archive.writestr(info, data)

    def cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_reanalysis_preserves_all_metrics_and_gate_semantics(self):
        for metric in ns.METRICS:
            with self.subTest(metric=metric), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                self.output = self.root / 'experiment.rlb'
                path, _ = self.packed(metric=metric)
                original = ns.evaluate(path, 500, max_growth=0)
                verified = bundle.verify(self.output)
                self.assertEqual(bundle.evidence(original), bundle.evidence(verified))
                self.assertEqual(verified['bundle']['integrity'], 'verified')

    def test_pack_is_reproducible_and_dates_are_shifted(self):
        path, _ = self.packed()
        second = self.root / 'same.rlb'
        bundle.create(path, second, iterations=500, max_growth=0)
        self.assertEqual(self.output.read_bytes(), second.read_bytes())
        files = self.files()
        self.assertNotIn(b'2025-01-01', b''.join(files.values()))
        self.assertIn(b'2000-01-01', b''.join(files.values()))
        self.assertEqual(len(files), 16)

    def test_private_har_fields_labels_paths_and_browser_identity_are_withheld(self):
        path, manifest = self.complete()
        manifest['title'] = 'PRIVATE_TITLE'
        manifest['workload'] = 'PRIVATE_TASK'
        manifest['conditions']['candidate'] = 'PRIVATE_BUILD'
        manifest['context']['browser'] = 'PRIVATE_CONTEXT'
        path.write_text(json.dumps(manifest))
        def inject(data):
            data['log']['browser'] = {'name': 'PRIVATE_BROWSER', 'version': 'PRIVATE_VERSION', 'comment': 'PRIVATE_COMMENT'}
            row = data['log']['entries'][0]
            row['request'].update(url='https://PRIVATE_USER:PRIVATE_PASS@private.example.invalid/PRIVATE_PATH?key=PRIVATE_QUERY#PRIVATE_FRAGMENT', headers=[{'name': 'Authorization', 'value': 'PRIVATE_TOKEN'}], postData={'text': 'PRIVATE_BODY'})
            row['response'].update(cookies=[{'value': 'PRIVATE_COOKIE'}])
            row['response']['content']['text'] = 'PRIVATE_RESPONSE'
        self.change(manifest, 0, 'candidate', inject)
        bundle.create(path, self.output, iterations=500)
        content = b''.join(self.files().values())
        self.assertNotIn(b'PRIVATE_', content)
        self.assertNotIn(b'private.example.invalid', content)
        self.assertFalse(bundle.verify(self.output)['comparable'])

    def test_unknown_measurements_stay_unknown_and_cannot_pass(self):
        path, manifest = self.complete()
        self.change(manifest, 0, 'candidate', lambda d: d['log']['entries'][0]['timings'].update(wait=-1))
        bundle.create(path, self.output, iterations=500, max_growth=1e9)
        result = bundle.verify(self.output)
        self.assertEqual(result['gate']['state'], 'unknown')
        self.assertIsNone(result['pairs'][0]['candidate']['value'])
        self.assertEqual(result['exit_code'], 1)

    def test_synthetic_mixing_and_http_errors_remain_audit_blockers(self):
        path, manifest = self.complete()
        self.change(manifest, 1, 'candidate', lambda d: d['log'].update(_reclaimlab_synthetic=True))
        self.change(manifest, 2, 'baseline', lambda d: d['log']['entries'][0]['response'].update(status=503))
        bundle.create(path, self.output, iterations=500)
        result = bundle.verify(self.output)
        self.assertTrue(result['synthetic'])
        self.assertEqual(result['exit_code'], 1)
        self.assertIn('HTTP errors', ' '.join(result['incompatible']))

    def test_fresh_budget_override_does_not_trust_stored_gate(self):
        path, _ = self.complete(deltas=[20] * 6)
        bundle.create(path, self.output, iterations=500, max_growth=30)
        self.assertEqual(bundle.verify(self.output)['gate']['state'], 'pass')
        result = bundle.verify(self.output, max_growth=0)
        self.assertEqual(result['gate']['state'], 'fail')
        self.assertEqual(result['exit_code'], 1)

    def test_checksum_tampering_is_detected(self):
        self.packed()
        files = self.files()
        files['analysis.json'] += b' '
        self.rewrite(files, reindex=False)
        with self.assertRaisesRegex(ValueError, 'checksum'): bundle.verify(self.output)

    def test_recomputed_checksums_cannot_hide_fabricated_analysis(self):
        self.packed()
        files = self.files()
        result = bundle.decode(files['analysis.json'])
        result['evidence']['mean_delta'] = -9999
        files['analysis.json'] = bundle.encoded(result)
        self.rewrite(files)
        with self.assertRaisesRegex(ValueError, 'reanalysis'): bundle.verify(self.output)

    def test_recomputed_checksums_cannot_smuggle_private_fields(self):
        self.packed()
        files = self.files()
        name = next(n for n in files if n.endswith('.har'))
        capture = bundle.decode(files[name])
        capture['log']['entries'][0]['request']['headers'] = [{'value': 'PRIVATE_TOKEN'}]
        files[name] = bundle.encoded(capture)
        self.rewrite(files)
        with self.assertRaisesRegex(ValueError, 'unapproved'): bundle.verify(self.output)

    def test_path_traversal_and_extra_archive_members_are_refused_without_extraction(self):
        self.packed()
        files = self.files()
        files['../outside'] = b'not extracted'
        self.rewrite(files)
        with self.assertRaisesRegex(ValueError, 'Unsafe'): bundle.verify(self.output)
        self.assertFalse((self.root.parent / 'outside').exists())

    def test_zip_symlinks_directories_and_duplicate_names_are_refused(self):
        self.packed()
        original = self.files()
        for mode in (stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO):
            self.rewrite(original, attributes=(mode | 0o600) << 16)
            with self.assertRaises(ValueError): bundle.verify(self.output)
        self.rewrite(original)
        with zipfile.ZipFile(self.output, 'a') as archive:
            with self.assertWarns(UserWarning): archive.writestr('analysis.json', original['analysis.json'])
        with self.assertRaisesRegex(ValueError, 'inventory'): bundle.verify(self.output)

    def test_zip_leading_and_trailing_bytes_are_refused(self):
        self.packed()
        original = self.output.read_bytes()
        for data in (b'PRIVATE_PREFIX' + original, original + b'PRIVATE_SUFFIX'):
            self.output.write_bytes(data)
            with self.assertRaises(ValueError): bundle.verify(self.output)

    def test_archive_and_decompressed_content_bounds_precede_analysis(self):
        self.packed()
        with mock.patch.object(bundle, 'MAX_ARCHIVE', 1), mock.patch.object(bundle, 'evaluate_files') as evaluator:
            with self.assertRaisesRegex(ValueError, '64 MiB'): bundle.verify(self.output)
            evaluator.assert_not_called()
        with mock.patch.object(bundle, 'MAX_CONTENT', 1), mock.patch.object(bundle, 'evaluate_files') as evaluator:
            with self.assertRaisesRegex(ValueError, '128 MiB'): bundle.verify(self.output)
            evaluator.assert_not_called()

    def test_unsupported_format_and_false_integer_version_are_refused(self):
        self.packed()
        original = self.files()
        for version in (True, 2):
            files = dict(original)
            index = bundle.decode(files['bundle.json'])
            index['format'] = version
            files['bundle.json'] = bundle.encoded(index)
            self.rewrite(files, reindex=False)
            with self.assertRaisesRegex(ValueError, 'Unsupported'): bundle.verify(self.output)

    def test_json_duplicate_keys_nonfinite_values_and_depth_are_refused(self):
        for payload in (b'{"key":1,"key":2}', b'{"key":NaN}', b'{"key":1e9999}', b'{"key":' + b'9' * 129 + b'}', b'[' * 32 + b'0' + b']' * 32):
            with self.assertRaises(ValueError): bundle.decode(payload)

    def test_changed_evidence_refuses_export_before_writing(self):
        path, _ = self.complete()
        with mock.patch.object(bundle, 'evidence', side_effect=[{'original': 1}, {'changed': 1}]):
            with self.assertRaisesRegex(ValueError, 'changes the audited result'): bundle.create(path, self.output, iterations=500)
        self.assertFalse(self.output.exists())

    def test_missing_capture_refuses_creation_without_a_partial_archive(self):
        path, manifest = self.complete()
        (self.root / manifest['pairs'][0]['baseline']).unlink()
        with self.assertRaises(ValueError): bundle.create(path, self.output, iterations=500)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.name == 'posix', 'symlink support')
    def test_symlink_bundle_and_source_capture_are_refused(self):
        path, manifest = self.packed()
        link = self.root / 'alias.rlb'
        link.symlink_to(self.output)
        with self.assertRaises(ValueError): bundle.verify(link)
        capture = self.root / manifest['pairs'][0]['baseline']
        capture.unlink()
        capture.symlink_to(self.root / manifest['pairs'][0]['candidate'])
        with self.assertRaises(ValueError): bundle.create(path, self.root / 'other.rlb', iterations=500)

    def test_creation_and_cli_report_outputs_are_exclusive_before_work(self):
        path, _ = self.packed()
        with mock.patch.object(ns, 'evaluate') as evaluator:
            with self.assertRaises(ValueError): bundle.create(path, self.output)
            evaluator.assert_not_called()
        html = self.root / 'fresh.html'
        code, out, err = self.cli(['bundle', 'verify', str(self.output), '--json', '--output', str(html)])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['bundle']['integrity'], 'verified')
        self.assertIn('Shared browser experiment', html.read_text())
        with mock.patch.object(bundle, 'verify') as verifier:
            code, _, _ = self.cli(['bundle', 'verify', str(self.output), '--output', str(html)])
            self.assertEqual(code, 2)
            verifier.assert_not_called()

    def test_invalid_archive_is_handled_by_cli(self):
        self.output.write_bytes(b'not a ZIP')
        code, _, err = self.cli(['bundle', 'verify', str(self.output), '--json'])
        self.assertEqual(code, 2)
        self.assertIn('ZIP', err)

    def test_frozen_format1_fixture_is_readable_without_current_exporter(self):
        fixture = json.loads(Path(__file__).with_name('fixtures').joinpath('bundle-format1.json').read_text())
        self.rewrite({name: value.encode() for name, value in fixture['files'].items()}, reindex=False)
        result = bundle.verify(self.output)
        self.assertEqual(result['valid_pairs'], 4)
        self.assertEqual(result['mean_delta'], -20)
        self.assertEqual(result['gate']['state'], 'pass')

    def test_verification_does_not_extract_or_write_temporary_measurements(self):
        self.packed()
        with mock.patch.object(Path, 'write_bytes') as writer, mock.patch('tempfile.TemporaryDirectory') as temporary, mock.patch.object(zipfile.ZipFile, 'extractall') as extractor:
            result = bundle.verify(self.output)
        self.assertEqual(result['exit_code'], 0)
        writer.assert_not_called()
        temporary.assert_not_called()
        extractor.assert_not_called()


if __name__ == '__main__': unittest.main()
