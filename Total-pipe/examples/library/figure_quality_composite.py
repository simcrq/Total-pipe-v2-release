"""Pair the intact benchmark figure with a table from its underlying QA fixture."""
import json

from common import EXAMPLES, SOURCE, block_leaf, chip_panel, comparison_table, deck, page, region


def make_deck():
    demo = EXAMPLES/'demo_deck'
    measured = json.loads((demo/'measurements.json').read_text(encoding='utf-8'))['figure_fixture']
    methods = {row['provider']: row for row in measured}
    template, packer = methods['compiler'], methods['packer']
    table = comparison_table('checks', [
        ('检查项', '模板', '打包'),
        ('回退页 / 总页', *[f"{row['counts']['fallback']} / {row['pages']}" for row in (template, packer)]),
        ('图版过小', *['有' if 'SCIENTIFIC_PANEL_TOO_SMALL' in row['fail'] else '无' for row in (template, packer)]),
    ], [1.8, 1, 1])
    table['evidence_refs'] = [SOURCE]
    figure = {'asset_id': 'benchmark-original', 'source_label': 'Total-pipe 软件样例 · 图 1',
              'caption': '柱高是平均贴合度，柱下还给出了最差页。'}
    blocks = [
        {'id': 'baseline', 'component': 'caption', 'text': '对照虚线 1.00×，方框与文字刚好等高。',
         'caption_for': {'kind': 'figure', 'ref': 'benchmark-original', 'position': 'top'},
         'evidence_refs': [SOURCE]},
        {'id': 'worst', 'component': 'body',
         'text': f"最差页由 {template['slack_max']:.2f}× 降至 {packer['slack_max']:.2f}×。",
         'text_flow': 'native_bullet_list', 'bullet_icon': '→', 'evidence_refs': [SOURCE]},
        {'id': 'fixture', 'component': 'body', 'text': '右表只统计本次双图夹具。',
         'text_flow': 'native_bullet_list', 'bullet_icon': '→', 'evidence_refs': [SOURCE]},
    ]
    body = region('figure-and-checks', 'columns', [
        {'id': 'original', 'type': 'figure', 'ref': 0},
        chip_panel('companion', '核对版面代价', region('checks-and-takeaways', 'stack', [
            {'id': 'check-table', 'type': 'table', 'ref': 'checks'},
            block_leaf('worst'), block_leaf('fixture'),
        ], gap='standard', align='center')),
    ], weights=[1.72, 1], gap='standard')
    slide = page('figure-quality', '在这组夹具上，打包后的最差页也更贴合',
                 'Total-pipe 软件测试 · 同一组双图输入比较模板与打包方案。',
                 blocks, body, figures=[figure], tables=[table])
    assets = {'benchmark-original': {'path': str(demo/'figures/fig1_quality.png'), 'origin': 'reference',
                                      'reference_source': 'Bundled Total-pipe demo · Fig. 1'}}
    output = deck('figure-quality-composite', [slide], assets)
    output['presentation']['text_capacity_policy'] = 'strict'
    return output
