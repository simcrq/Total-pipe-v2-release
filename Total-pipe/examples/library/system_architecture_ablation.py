"""Layered system architecture paired with a horizontal ablation bar chart and summary table."""
from common import SOURCE, block_leaf, chip_panel, comparison_table, deck, page, region


def make_deck():
    arch = {
        'id': 'sys-arch',
        'type': 'architecture',
        'direction': 'horizontal',
        'layers': [
            {'id': 'ingest', 'title': '采集层', 'nodes': [
                {'id': 'sensor', 'title': '多源流输入', 'shape': 'rounded-rect'},
            ]},
            {'id': 'core', 'title': '核心引擎', 'nodes': [
                {'id': 'align', 'title': '时序对齐', 'shape': 'rounded-rect'},
                {'id': 'fuse', 'title': '残差融合', 'shape': 'rounded-rect', 'tone': 'emphasis'},
            ]},
            {'id': 'serve', 'title': '输出层', 'nodes': [
                {'id': 'head', 'title': '校准预测', 'shape': 'rounded-rect'},
            ]},
        ],
        'edges': [
            {'from': 'sensor', 'to': 'align', 'kind': 'arrow'},
            {'from': 'sensor', 'to': 'fuse', 'kind': 'arrow'},
            {'from': 'align', 'to': 'head', 'kind': 'arrow'},
            {'from': 'fuse', 'to': 'head', 'kind': 'arrow'},
        ],
    }
    ablation_chart = {
        'id': 'ablation-hbar',
        'kind': 'hbar',
        'basis': 'explain',
        'illustrative': True,
        'x': {'label': '配置变体', 'categories': ['完整系统', '去残差融合', '去时序对齐', '单源基线']},
        'y': {'label': '宏平均检出率', 'unit': '%', 'min': 60, 'max': 100},
        'series': [
            {'id': 'f1', 'label': '检出率 (%)', 'values': [94.2, 86.5, 81.0, 72.4]},
        ],
        'reference_lines': [
            {'axis': 'y', 'value': 90.0, 'label': '上线阈值 90%', 'style': 'dashed'},
        ],
    }
    table = comparison_table('ablation-table', [
        ['模块改动', '检出率', 'P99 延迟'],
        ['完整三层架构（构造算例）', '94.2%', '1.4 ms'],
        ['移除残差融合分支', '86.5%', '1.2 ms'],
        ['移除时序对齐与融合', '72.4%', '1.0 ms'],
    ], [2.1, 1.0, 1.0])
    blocks = [
        {'id': 'ablation-note', 'component': 'body',
         'text': '残差融合贡献 +7.7 个百分点增益，仅增加 0.2 ms 延迟开销。',
         'evidence_refs': [SOURCE]},
    ]
    body = region('arch-and-ablation', 'columns', [
        region('left-arch', 'stack', [
            {'id': 'arch-leaf', 'type': 'graphic', 'ref': 'sys-arch'},
            chip_panel('arch-summary', '架构增益机制', block_leaf('ablation-note')),
        ], gap='standard'),
        region('right-ablation', 'stack', [
            {'id': 'hbar-leaf', 'type': 'chart', 'ref': 'ablation-hbar'},
            {'id': 'tbl-leaf', 'type': 'table', 'ref': 'ablation-table'},
        ], gap='compact'),
    ], weights=[1.65, 1.0], gap='standard')
    slide = page(
        'system-architecture-ablation',
        '三层流水架构通过残差融合突破 90% 检出率阈值',
        '架构模块与水平消融条形图同页对应，直观定位每个组件的精度贡献与延迟代价。',
        blocks,
        body,
        graphics=[arch],
        charts=[ablation_chart],
        tables=[table],
    )
    return deck('system-architecture-ablation', [slide])
