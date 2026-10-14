"""Detect mixed-build evidence and stale readable tables."""
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import subprocess
import sys
import unittest
from evidence_contract import REPORTS, verify_evidence

class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[1]
        shutil.copyfile(source / 'environment.json', self.root / 'environment.json')
        shutil.copytree(source / 'results', self.root / 'results')

    def test_verifier_supports_isolated_python(self):
        source = Path(__file__).resolve().parents[1]
        subprocess.run([sys.executable, "-I", str(source / "scripts/verify.py")],
                       capture_output=True, check=True)

    def test_consistent_snapshot(self):
        verify_evidence(self.root)

    def test_every_report_rejects_a_stale_build(self):
        for name in REPORTS:
            path = self.root / 'results' / (name + '.json.gz')
            original = path.read_bytes()
            report = json.loads(gzip.decompress(original))
            report['compiler_source_sha256'] = 'sha256:' + '0' * 64
            path.write_bytes(gzip.compress(json.dumps(report).encode()))
            with self.subTest(report=name), self.assertRaisesRegex(ValueError, 'build identity'):
                verify_evidence(self.root)
            path.write_bytes(original)

    def test_nested_preset_identity_is_checked(self):
        path = self.root / 'results/source-presets.json.gz'
        report = json.loads(gzip.decompress(path.read_bytes()))
        report['cases'][0]['engine_identity']['compiler_source_sha256'] = 'sha256:' + '0' * 64
        path.write_bytes(gzip.compress(json.dumps(report).encode()))
        with self.assertRaisesRegex(ValueError, 'compiler source'):
            verify_evidence(self.root)

    def test_csv_changes_cannot_hide_behind_correct_row_counts(self):
        for name in ('simulations.csv', 'fitting.csv'):
            path = self.root / 'results' / name
            original = path.read_text()
            lines = original.splitlines()
            fields = lines[1].split(',');fields[-1] = '123456789'
            lines[1] = ','.join(fields);path.write_text('\n'.join(lines) + '\n')
            with self.subTest(table=name), self.assertRaisesRegex(ValueError, 'CSV'):
                verify_evidence(self.root)
            path.write_text(original)

    def test_summary_identity_is_checked(self):
        path = self.root / 'results/summary.json'
        value = json.loads(path.read_text());value['cli_sha256'] = '0' * 64
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'summary'):
            verify_evidence(self.root)

if __name__ == '__main__':
    unittest.main()
