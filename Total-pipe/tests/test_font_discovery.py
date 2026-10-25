"""Configured nested font directories work with Linux family and filename resolution."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from deck_compiler.fonts import (FONT_DIRECTORY_VARIABLE, discover_fonts, find_font_file,
                                 load_font_file, resolve_theme_fonts)
from test_deck_compiler import ROOT, fixture


class FontDiscoveryTests(unittest.TestCase):
    def test_linux_discovers_nested_noto_collections_and_honours_configured_priority(self):
        regular, bold, _ = resolve_theme_fonts(fixture()['theme'], ROOT/'examples')
        with tempfile.TemporaryDirectory() as temporary:
            # Real loadable faces, placed under the filenames and directory hierarchy
            # used by fonts-noto-cjk. This test checks discovery, not glyph identity.
            root = Path(temporary)
            nested = root/'opentype/noto'
            nested.mkdir(parents=True)
            target_regular = nested/'NotoSansCJK-Regular.ttc'
            target_bold = nested/'NotoSansCJK-Bold.ttc'
            shutil.copyfile(regular, target_regular)
            shutil.copyfile(bold, target_bold)
            with patch.dict(os.environ, {FONT_DIRECTORY_VARIABLE: str(root)}), \
                    patch('deck_compiler.fonts.platform.system', return_value='Linux'):
                fonts = discover_fonts()
                self.assertEqual(fonts['Noto Sans CJK SC']['regular'], str(target_regular))
                self.assertEqual(fonts['Noto Sans CJK SC']['bold'], str(target_bold))
                self.assertEqual(find_font_file('NotoSansCJK-Regular.ttc'), str(target_regular.resolve()))
                self.assertGreater(load_font_file('NotoSansCJK-Regular.ttc', 24).getlength('Scientific labels'), 0)


if __name__ == '__main__':
    unittest.main()
