"""Native evidence must describe the PDF actually produced in this invocation."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from deck_compiler import native
from deck_compiler.contracts import file_hash


class NativeRendererTests(unittest.TestCase):
    @patch.object(native.sys, 'platform', 'win32')
    def test_windows_evidence_is_bound_to_new_pdf_and_input(self):
        with tempfile.TemporaryDirectory() as folder:
            pptx = Path(folder)/"input with 'quotes'.pptx"
            pdf = Path(folder)/'native.pdf'
            pptx.write_bytes(b'input deck')
            def export(command, **kwargs):
                self.assertNotIn(str(pptx), command[-1])
                self.assertEqual(kwargs['env']['TOTALPIPE_NATIVE_INPUT'], str(pptx.resolve()))
                Path(kwargs['env']['TOTALPIPE_NATIVE_PDF']).write_bytes(b'%PDF native output')
            with patch.object(native.subprocess, 'run', side_effect=export):
                evidence, findings = native.render(pptx, pdf)
            self.assertFalse(findings)
            self.assertEqual(evidence['artifact_sha256'], file_hash(pptx))
            self.assertEqual(evidence['pdf_sha256'], file_hash(pdf))
            self.assertEqual(evidence['renderer'], 'powerpoint')

    @patch.object(native.sys, 'platform', 'win32')
    def test_stale_or_missing_pdf_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            pptx, pdf = Path(folder)/'input.pptx', Path(folder)/'native.pdf'
            pptx.write_bytes(b'input deck')
            pdf.write_bytes(b'%PDF previous output')
            with patch.object(native.subprocess, 'run'):
                evidence, findings = native.render(pptx, pdf)
            self.assertIsNone(evidence)
            self.assertEqual(findings[0]['rule'], 'NATIVE_RENDER_UNAVAILABLE')
            self.assertFalse(pdf.exists())

    @patch.object(native.sys, 'platform', 'win32')
    def test_powerpoint_failure_remains_review(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(native.subprocess, 'run', side_effect=subprocess.CalledProcessError(
                    1, 'PowerPoint', stderr='PowerPoint unavailable')):
                evidence, findings = native.render(Path(folder)/'input.pptx', Path(folder)/'native.pdf')
            self.assertIsNone(evidence)
            self.assertEqual(findings[0]['severity'], 'REVIEW')
            self.assertIn('PowerPoint unavailable', findings[0]['message'])
