"""A caption must not print the provenance it already carries as a label."""
import unittest

from deck_compiler.layout import caption_with_source


class CaptionSourceTests(unittest.TestCase):
    def test_the_same_figure_is_not_named_twice(self):
        ref = {'source_label': '原文 Fig. 2c',
               'caption': 'Fig. 2c | 300 K 转移曲线：NbS2–MoS2 与未处理 MoS2'}
        self.assertEqual(caption_with_source(ref),
                         '[[原文 Fig. 2c]] · 300 K 转移曲线：NbS2–MoS2 与未处理 MoS2')

    def test_a_different_figure_stays_in_the_caption(self):
        ref = {'source_label': '原文 Fig. 2c', 'caption': 'Fig. 3e | 脉冲串下的电导'}
        self.assertEqual(caption_with_source(ref), '[[原文 Fig. 2c]] · Fig. 3e | 脉冲串下的电导')

    def test_a_caption_that_is_only_the_figure_keeps_the_label(self):
        ref = {'source_label': '原文 Fig. 4c', 'caption': 'Fig. 4c | '}
        self.assertEqual(caption_with_source(ref), '[[原文 Fig. 4c]]')


if __name__ == '__main__':
    unittest.main()
