"""Closing synthesis slide: three contribution pillars above an operating-boundary matrix."""
from common import SOURCE, block_leaf, chip_panel, comparison_table, deck, page, region


def make_deck():
    blocks = [
        {'id': 'p1', 'component': 'body',
         'text': '以局部守恒统计量替代全局锁同步，消除多通道并发瓶颈。',
         'evidence_refs': [SOURCE]},
        {'id': 'p2', 'component': 'body', 'inline_math': True,
         'text': '在构造基准上将尾延迟降低 $3.4\\times$，同时维持偏差 $\\le 0.5\\%$。',
         'evidence_refs': [SOURCE]},
        {'id': 'p3', 'component': 'body',
         'text': '提供确定性几何门禁与逐阶段校验记录，支持跨平台复现实验。',
         'evidence_refs': [SOURCE]},
    ]
    boundary = comparison_table('boundary-matrix', [
        ['运行工况（构造示例）', '适用范围', '失效边界', '部署建议'],
        ['稳态高频采样', '通道数 4–64，丢包率 < 1%', '突发时钟漂移 > 5 ms', '默认开启异步块归约'],
        ['强非平稳脉冲', '脉宽 ≥ 3 个采样窗口', '单点尖峰脉宽 < 1 窗口', '切换双阈值精确回退通道'],
    ], [1.4, 1.5, 1.5, 1.6])
    body = region('closing-synthesis', 'stack', [
        region('three-pillars', 'columns', [
            chip_panel('pillar-1', '① 核心机制突破', block_leaf('p1')),
            chip_panel('pillar-2', '② 定量性能收益', block_leaf('p2')),
            chip_panel('pillar-3', '③ 工程复现保障', block_leaf('p3')),
        ], gap='standard'),
        chip_panel('boundary-card', '适用条件与运行边界矩阵', {
            'id': 'boundary-leaf', 'type': 'table', 'ref': 'boundary-matrix',
        }),
    ], gap='standard')
    slide = page(
        'conclusions-boundary-matrix',
        '三项核心贡献与明确失效边界共同构成可落地的工程结论',
        '收束页同时交代定量收益与单点脉冲失效边界，避免脱离前提泛化结论。',
        blocks,
        body,
        tables=[boundary],
    )
    return deck('conclusions-boundary-matrix', [slide])
