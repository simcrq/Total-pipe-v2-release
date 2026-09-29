"""Small geometry regressions for the v26 proposal contract."""
import unittest

from totalpipe_layout.contracts import check, snap_rhythm

from test_deck_compiler import fixture


class LayoutRhythmTests(unittest.TestCase):
    def test_peer_column_and_figure_caption_slack_are_corrected(self):
        theme = fixture()['theme']
        request = {
            'archetype': 'figure-parameters', 'region': [56, 236, 1168, 404],
            'font': theme['font_file'], 'bold_font': theme['bold_font_file'],
            'font_family': theme['font_family'], 'frame': [],
            'units': [
                {'id': name, 'role': 'process-step', 'text': value}
                for name, value in (
                    ('sample', 'MoS2 film is 2.1 nm thick'),
                    ('probe', 'Probe-guided laser focus'),
                    ('power', 'Power controls removal'),
                    ('result', 'Grayscale steps form'))
            ] + [{'id': 'figure-1', 'role': 'figure', 'aspect': 681/387,
                  'caption': 'Fig. 1a process diagram', 'caption_height': 62}],
        }
        boxes = [[575, 236, 649, 122], [575, 422, 649, 58],
                 [575, 518, 649, 58], [575, 582, 649, 58],
                 [56, 236, 463.5, 404]]
        self.assertIn('figure-1:FIGURE_CAPTION_SLACK', check(request, boxes))
        corrected = snap_rhythm(request, boxes)
        self.assertEqual(check(request, corrected), [])
        self.assertEqual([round(b[1]-a[1]-a[3]) for a, b in
                          zip(corrected[:3], corrected[1:4])], [24, 24, 24])
        self.assertAlmostEqual(corrected[4][3] - 62 - 12, 463.5/(681/387))
        self.assertEqual(boxes[0], [575, 236, 649, 122])

        # Longer peers may need different heights; the shared 24 px gaps remain.
        request['region'][3] = 352
        request['units'][1]['text'] = ('Scientific observation with an extended '
                                      'explanation that crosses the column width.')
        request['units'][2]['text'] = ('Independent evidence with an extended '
                                      'explanation that crosses the column width.')
        boxes[3] = [575, 530, 649, 58]
        corrected = snap_rhythm(request, boxes)
        self.assertEqual(check(request, corrected), [])
        self.assertGreater(corrected[1][3], corrected[0][3])
        self.assertEqual([round(b[1]-a[1]-a[3]) for a, b in
                          zip(corrected[:3], corrected[1:4])], [24, 24, 24])


if __name__ == '__main__':
    unittest.main()
