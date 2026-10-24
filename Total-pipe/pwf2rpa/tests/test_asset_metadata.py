import copy
import unittest

from pwf2rpa.asset_metadata import enrich_visuals
from pwf2rpa.briefs import _normalize_visual


class AssetMetadataTests(unittest.TestCase):
    def test_visual_dimensions_survive_whitelist(self):
        problems = []
        raw = {'source_width_px': 800, 'source_height_px': 400, 'source_asset_id': 'images/a.png',
               'image_kind': 'raster', 'image_format': 'png', 'crop_allowed': False}
        result = _normalize_visual(raw, 'visual', problems)
        self.assertFalse(problems)
        for key, value in raw.items(): self.assertEqual(result[key], value)

    def test_only_exact_asset_references_are_enriched_without_modifying_workflow(self):
        workflow = {'artifacts': {'figure_assets_metadata': [{'asset_id': 'images/a.png', 'path': 'images/a.png',
            'source_width_px': 800, 'source_height_px': 400, 'visual_aspect_ratio': 2,
            'image_kind': 'raster', 'image_format': 'png', 'crop_allowed': False}]}}
        original = copy.deepcopy(workflow)
        briefs = [{'visuals': [{'asset_uri': 'images/a.png'}, {'asset_uri': 'a.png'}]}]
        self.assertFalse(enrich_visuals(briefs, workflow))
        self.assertEqual(workflow, original)
        self.assertEqual(briefs[0]['visuals'][0]['source_width_px'], 800)
        self.assertNotIn('source_width_px', briefs[0]['visuals'][1])
        briefs[0]['visuals'][0]['source_width_px'] = 1
        self.assertEqual(enrich_visuals(briefs, workflow)[0].code, 'ASSET_METADATA_CONFLICT')

    def test_legacy_workflows_remain_usable(self):
        briefs = [{'visuals': [{'asset_uri': 'images/a.png'}]}]
        original = copy.deepcopy(briefs)
        self.assertFalse(enrich_visuals(briefs, {}))
        self.assertEqual(briefs, original)
