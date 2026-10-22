"""A background picture is declared in the IR, measured, and drawn once on the master.

The test deck shipped a 1.8 MB decorative background that a script had stamped into the master
after QA: the report described 0.44 MB while the delivered file was 2.28 MB. Declaring it in the
theme means the compiler measures its contrast against the text colour, the writer places it once
on the slide master, and the structural check can see it.
"""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from deck_compiler import background, officecli
from deck_compiler.layout import compile_deck
from deck_compiler.unified_cli import verify_artifact

from test_deck_compiler import ROOT, fixture


def deck_with(path, foreground='#142735'):
    ir = fixture()
    ir['theme']['background_image'] = path
    ir['theme']['foreground'] = foreground
    return ir


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)

    def solid(self, colour, name='bg.png', size=(320, 180)):
        Image.new('RGB', size, colour).save(self.base/name)
        return name

    def test_a_dark_background_fails_the_contrast_budget(self):
        name = self.solid((16, 24, 32))
        layout, issues = compile_deck(deck_with(name), self.base)
        self.assertIn('BACKGROUND_CONTRAST', [i['rule'] for i in issues if i['severity'] == 'FAIL'])

    def test_a_light_background_passes_and_is_placed_once_on_the_master(self):
        name = self.solid((246, 250, 252))
        layout, issues = compile_deck(deck_with(name), self.base)
        self.assertEqual([i for i in issues if i['severity'] == 'FAIL'], [])
        self.assertEqual(layout['background_image'], str((self.base/name).resolve()))
        commands = officecli.commands(layout)
        master = [c for c in commands if c.get('path') == '/slidemaster[1]']
        self.assertEqual(len(master), 1)
        self.assertTrue(master[0]['props']['background'].startswith('image:'))
        slides = [c for c in commands if c.get('type') == 'slide']
        self.assertTrue(slides)
        self.assertTrue(all('background' not in c['props'] for c in slides),
                        'a per-slide image fill embeds one copy of the picture per slide')

    def test_a_busy_background_is_reported(self):
        image = Image.new('RGB', (320, 180))
        pixels = image.load()
        for y in range(180):
            for x in range(320):
                pixels[x, y] = (255, 255, 255) if (x//20 + y//20) % 2 else (20, 20, 20)
        path = self.base/'busy.png'
        image.save(path)
        stats, issues = background.review(path, '#142735', path.stat().st_size)
        self.assertGreater(stats['deviation'], .075)
        self.assertIn('BACKGROUND_BUSY', [i['rule'] for i in issues])

    def test_a_missing_background_is_a_failure(self):
        layout, issues = compile_deck(deck_with('missing.png'), self.base)
        self.assertIsNone(layout)
        self.assertIn('BACKGROUND_INVALID', [i['rule'] for i in issues if i['severity'] == 'FAIL'])

    def test_a_delivered_file_is_checked_against_its_qa_report(self):
        build = self.base/'build'
        build.mkdir()
        staged = (build/'staging.pptx').write_bytes(b'PK\x03\x04 staged bytes')
        from deck_compiler.contracts import file_hash
        qa = {'schema_version': '2.0', 'artifact_sha256': file_hash(build/'staging.pptx'),
              'status': 'REVIEW', 'counts': {'FAIL': 0}}
        (build/'qa_report.json').write_text(json.dumps(qa), encoding='utf-8')
        delivered = self.base/'delivered.pptx'
        delivered.write_bytes((build/'staging.pptx').read_bytes())
        self.assertTrue(verify_artifact(delivered, build)['match'])
        with delivered.open('ab') as handle:
            handle.write(b'patched after QA')
        result = verify_artifact(delivered, build)
        self.assertFalse(result['match'])
        self.assertNotEqual(result['delivered_sha256'], result['qa_artifact_sha256'])


if __name__ == '__main__':
    unittest.main()
