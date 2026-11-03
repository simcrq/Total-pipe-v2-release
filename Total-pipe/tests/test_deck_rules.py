"""Deck-level fallbacks: one title size, list styling for stacked paragraphs, caption capacity."""
import unittest

from deck_compiler import text_flow
from deck_compiler.text_flow import DISTRIBUTED_ARROW_LIST, fallback_list
from deck_compiler.visual_design import TITLE_BOX_LINES, type_sizes


class ListFallbackTests(unittest.TestCase):
    def test_two_paragraphs_become_a_native_list(self):
        block = {'id': 'b', 'component': 'body', 'text': '第一句陈述\n第二句陈述'}
        converted = fallback_list(block)
        self.assertEqual(converted['text_flow'], DISTRIBUTED_ARROW_LIST)
        self.assertEqual(converted['text'], block['text'])  # content untouched
        self.assertNotIn('text_flow', block)                # the caller's IR is not mutated

    def test_single_paragraph_stays_plain(self):
        block = {'id': 'b', 'component': 'result', 'text': '只有一句结论。'}
        self.assertIs(fallback_list(block), block)

    def test_formula_and_explicit_flow_are_left_alone(self):
        formula = {'id': 'f', 'component': 'formula', 'text': 'a\nb'}
        self.assertIs(fallback_list(formula), formula)
        explicit = {'id': 'b', 'component': 'body', 'text': 'a\nb', 'text_flow': 'plain'}
        self.assertEqual(fallback_list(explicit)['text_flow'], 'plain')

    def test_tables_and_fenced_blocks_are_not_lists(self):
        table = {'id': 'b', 'component': 'body', 'text': '| a | b |\n| 1 | 2 |'}
        self.assertIs(fallback_list(table), table)

    def test_long_paragraphs_are_not_split(self):
        long_line = '这是一段很长的正文' * 30
        block = {'id': 'b', 'component': 'body', 'text': long_line+'\n'+long_line}
        self.assertIs(fallback_list(block), block)

    def test_seven_paragraphs_stay_plain(self):
        block = {'id': 'b', 'component': 'body', 'text': '\n'.join(f'第{i}句' for i in range(7))}
        self.assertIs(fallback_list(block), block)


class TitleScaleTests(unittest.TestCase):
    def test_title_size_is_one_step_above_takeaway(self):
        sizes = type_sizes({'type_scale': 'standard'})
        self.assertEqual(sizes['title'], 44)
        self.assertGreater(sizes['title'], sizes['takeaway'])
        self.assertGreater(sizes['title'], sizes['display'])

    def test_header_box_allows_three_lines(self):
        self.assertEqual(TITLE_BOX_LINES, 3)


if __name__ == '__main__':
    unittest.main()
