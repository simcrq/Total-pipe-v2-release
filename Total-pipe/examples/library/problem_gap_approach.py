"""Opening motivation slide: funnel narrowing from domain bottleneck to our targeted approach."""
from common import SOURCE, block_leaf, chip_panel, deck, page, region


def make_deck():
    funnel = {
        'id': 'scope-funnel',
        'type': 'funnel',
        'variant': 'funnel',
        'end_width': 0.42,
        'levels': [
            {'id': 'domain', 'title': '高频采样系统吞吐需求', 'body': '多通道并发下延迟预算 ≤ 2 ms'},
            {'id': 'bottleneck', 'title': '全局同步锁死尾延迟', 'body': '跨核归约占 68% 等待时间'},
            {'id': 'focus', 'title': '分块异步局部归约', 'body': '仅在块边界交换摘要统计量'},
        ],
    }
    blocks = [
        {'id': 'gap-1', 'component': 'body', 'text_flow': 'native_bullet_list', 'bullet_icon': '▪',
         'text': '全量广播方案随通道数线性放大带宽开销。', 'evidence_refs': [SOURCE]},
        {'id': 'gap-2', 'component': 'body', 'text_flow': 'native_bullet_list', 'bullet_icon': '▪',
         'text': '启发式丢包虽降延迟，但破坏守恒估计无偏性。', 'evidence_refs': [SOURCE]},
        {'id': 'approach-1', 'component': 'body', 'text_flow': 'native_numbered_list', 'list_start': 1,
         'text': '窗口内保留局部充分统计量，避免逐样本跨核同步。', 'evidence_refs': [SOURCE]},
        {'id': 'approach-2', 'component': 'body', 'text_flow': 'native_numbered_list', 'list_start': 2,
         'text': '边界校正项严格控制估计偏差在 $\\epsilon \\le 0.5\\%$ 以内。',
         'evidence_refs': [SOURCE]},
    ]
    # Note: inline_math cannot combine with native_numbered_list; keep plain on math-bearing copy.
    blocks[-1] = {
        'id': 'approach-2', 'component': 'body', 'inline_math': True,
        'text': '边界校正项严格控制估计偏差在 $\\epsilon \\le 0.5\\%$ 以内（简化构造示例）。',
        'evidence_refs': [SOURCE],
    }
    body = region('motivation-split', 'columns', [
        {'id': 'funnel-zone', 'type': 'graphic', 'ref': 'scope-funnel'},
        region('right-cards', 'stack', [
            chip_panel('gap-panel', '现有路线缺口', region('gap-list', 'stack', [
                block_leaf('gap-1'), block_leaf('gap-2'),
            ])),
            chip_panel('our-panel', '本文切入路径', region('our-list', 'stack', [
                block_leaf('approach-1'), block_leaf('approach-2'),
            ])),
        ], gap='standard'),
    ], weights=[1.15, 1.35], gap='standard')
    slide = page(
        'problem-gap-approach',
        '局部充分统计量绕开跨核同步瓶颈并保持无偏估计',
        '用块边界摘要替代逐样本锁同步，同时兼顾尾延迟上限与统计无偏性。',
        blocks,
        body,
        graphics=[funnel],
    )
    return deck('problem-gap-approach', [slide])
