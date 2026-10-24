import tempfile
import unittest
from pathlib import Path
from PIL import Image

from utils.artifact_bundle import image_metadata, stage_markdown_bundle


class AssetMetadataTests(unittest.TestCase):
    def test_raster_dimensions_and_default_no_crop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'images').mkdir()
            Image.new('RGB', (800, 400), 'white').save(root/'images/a.png')
            source = root/'source.md'
            source.write_text('![panel](images/a.png)')
            bundle = stage_markdown_bundle(source, root/'bundle')
            asset = bundle['asset_metadata'][0]
            self.assertEqual(asset['asset_id'], 'images/a.png')
            self.assertEqual((asset['source_width_px'], asset['source_height_px']), (800, 400))
            self.assertEqual(asset['visual_aspect_ratio'], 2)
            self.assertFalse(asset['crop_allowed'])
            self.assertEqual(asset['metadata_status'], 'available')
            self.assertEqual(len(asset['sha256']), 64)

    def test_unsupported_and_vector_metadata_do_not_invent_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'a.svg').write_text('<svg viewBox="0 0 300 100"/>')
            asset = image_metadata(root/'a.svg', 'a.svg')
            self.assertEqual(asset['visual_aspect_ratio'], 3)
            self.assertNotIn('source_width_px', asset)
            (root/'bad.svg').write_text('<not-xml')
            self.assertEqual(image_metadata(root/'bad.svg', 'bad.svg')['metadata_status'], 'unavailable')
            (root/'bad.png').write_bytes(b'not an image')
            self.assertNotIn('source_width_px', image_metadata(root/'bad.png', 'bad.png'))
