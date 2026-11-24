"""Multi-panel image_grid with native highlight callouts and structured side readout."""
from common import EXAMPLES, SOURCE, block_leaf, chip_panel, deck, page, region


def make_deck():
    assets = {
        'panel-quality': {
            'path': str(EXAMPLES/'demo_deck/figures/fig1_quality.png'),
            'origin': 'reference',
            'reference_source': 'Bundled Total-pipe demo · Fig. 1',
        },
        'panel-stages': {
            'path': str(EXAMPLES/'demo_deck/figures/fig2_stages.png'),
            'origin': 'reference',
            'reference_source': 'Bundled Total-pipe demo · Fig. 2',
        },
    }
    figures = [
        {
            'asset_id': 'panel-quality',
            'source_label': 'Demo Fig. 1',
            'caption': '(a) 版面填充比与最差页边界对比。',
            'min_panel_extent': 140,
            'highlights': [
                {'box': [0.52, 0.14, 0.42, 0.68], 'label': '峰值区间', 'color': '#C2410C'},
            ],
        },
        {
            'asset_id': 'panel-stages',
            'source_label': 'Demo Fig. 2',
            'caption': '(b) 分阶段几何门禁与收敛路径。',
            'min_panel_extent': 140,
        },
    ]
    cues = [
        {'id': 'cue-a', 'component': 'body', 'text_flow': 'native_numbered_list', 'list_start': 1,
         'text': '子图 (a) 高亮框标出最差页仍维持在安全阈值内的紧凑分布。', 'evidence_refs': [SOURCE]},
        {'id': 'cue-b', 'component': 'body', 'text_flow': 'native_numbered_list', 'list_start': 2,
         'text': '子图 (b) 显示预检门禁在进入渲染前拦截越界与字号压缩。', 'evidence_refs': [SOURCE]},
        {'id': 'cue-rule', 'component': 'body',
         'text': '拼版多图页通过统一网格与编号导读建立先看框选区、再核对流程的视线顺序。',
         'evidence_refs': [SOURCE]},
    ]
    body = region('grid-and-readout', 'columns', [
        {'id': 'panel-grid', 'type': 'image_grid', 'columns': 1, 'gap': 'compact', 'children': [
            {'id': 'fig-a', 'type': 'figure', 'ref': 0},
            {'id': 'fig-b', 'type': 'figure', 'ref': 1},
        ]},
        chip_panel('readout-card', '多子图对照导读', region('cues-stack', 'stack', [
            block_leaf('cue-a'), block_leaf('cue-b'), block_leaf('cue-rule'),
        ], gap='standard')),
    ], weights=[1.55, 1.0], gap='standard')
    slide = page(
        'multi-panel-grid-readout',
        '多子图网格配合原图高亮框统一引导跨面板证据核对',
        '左侧双子图共享对齐基准并框选关键异常区，右侧按编号逐条对应读图结论。',
        cues,
        body,
        figures=figures,
    )
    return deck('multi-panel-grid-readout', [slide], assets)
