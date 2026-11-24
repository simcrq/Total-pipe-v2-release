"""Case-study evolution slide: top section nav bar, accent-bar title, dual-card arrow transition, and bottom takeaway."""
from common import SOURCE, block_leaf, deck, page, region


def _stage_panel(id, title, title_fill, border_color, fill_color, block_ids, chart_id):
    return {
        'id': id,
        'type': 'panel',
        'title': title,
        'padding': 'compact',
        'gap': 'compact',
        'frame': {
            'border': {'color': border_color, 'width': 1.2},
            'fill': fill_color,
            'title_band': 'chip',
            'title_align': 'center',
            'title_fill': title_fill,
            'title_color': '#FFFFFF',
        },
        'body': region(
            f'{id}-body',
            'stack',
            [
                *[block_leaf(bid) for bid in block_ids],
                {'id': f'{id}-chart', 'type': 'chart', 'ref': chart_id},
            ],
            gap='compact',
        ),
    }


def make_deck():
    transition_arrow = {
        'id': 'transition-arrow',
        'type': 'path',
        'view_box': [0, 0, 80, 260],
        'paths': [
            {
                'id': 'arrow-body',
                'commands': [
                    ['M', 8, 118],
                    ['L', 44, 118],
                    ['L', 44, 102],
                    ['L', 74, 130],
                    ['L', 44, 158],
                    ['L', 44, 142],
                    ['L', 8, 142],
                    ['Z'],
                ],
                'stroke': '#B85D3B',
                'fill': '#F6E5DD',
                'line_width': 2.0,
            },
        ],
    }

    charts = [
        {
            'id': 'chart-benign',
            'kind': 'line',
            'basis': 'explain',
            'illustrative': True,
            'x': {'label': '迭代轮次', 'scale': 'linear', 'values': [1, 2, 3, 4]},
            'y': {'label': '准确率', 'scale': 'linear', 'unit': '%', 'min': 55, 'max': 100},
            'series': [
                {'label': '公开验证集', 'values': [68, 75, 81, 86]},
                {'label': '独立留出集', 'values': [66, 73, 79, 84]},
            ],
            'reference_lines': [
                {'axis': 'y', 'value': 90, 'label': '泛化目标 90%', 'style': 'dashed'},
            ],
            'annotations': [
                {'text': '同步 +18 pt', 'series': 1, 'point': 3, 'dx': -78, 'dy': 18},
            ],
            'source': '构造示例',
        },
        {
            'id': 'chart-drift',
            'kind': 'line',
            'basis': 'explain',
            'illustrative': True,
            'x': {'label': '迭代轮次', 'scale': 'linear', 'values': [1, 2, 3, 4]},
            'y': {'label': '准确率', 'scale': 'linear', 'unit': '%', 'min': 55, 'max': 100},
            'series': [
                {'label': '公开榜单', 'values': [72, 80, 85, 89]},
                {'label': '独立留出集', 'values': [70, 73, 67, 62]},
            ],
            'shaded_zones': [
                {'axis': 'x', 'low': 2.5, 'high': 4.0, 'label': '刷榜分化区'},
            ],
            'annotations': [
                {'text': '落差 -27 pt', 'series': 1, 'point': 3, 'dx': -78, 'dy': -22},
            ],
            'source': '构造示例',
        },
    ]

    blocks = [
        {
            'id': 'benign-1',
            'component': 'body',
            'text': '公开基准为算法迭代提供**统一量尺**与**可复现基线**，推动跨域方法持续收敛。',
            'evidence_refs': [SOURCE],
        },
        {
            'id': 'benign-2',
            'component': 'body',
            'text': '围绕榜单开展**消融诊断**与误差剖析，属于健康的良性工程演进。',
            'evidence_refs': [SOURCE],
        },
        {
            'id': 'drift-1',
            'component': 'body',
            'text': '盲目追逐单一榜单名次，借**测试集泄露**与**超参硬调**推高表观分数。',
            'evidence_refs': [SOURCE],
        },
        {
            'id': 'drift-2',
            'component': 'body',
            'text': '将评测工具异化为**唯分数论**，掩盖真实分布偏移下的泛化退化风险。',
            'evidence_refs': [SOURCE],
        },
        {
            'id': 'bottom-takeaway',
            'component': 'conclusion',
            'text': '**重视公开基准 ≠ 唯榜单分数论**：警惕评测工具异化为制造虚假领先的刷榜竞赛（构造示例）。',
            'evidence_refs': [SOURCE],
        },
    ]

    transition_pair = region(
        'transition-pair',
        'columns',
        [
            _stage_panel(
                'benign-panel',
                '良性基准驱动',
                '#266E72',
                '#CBD5E1',
                '#F8FAFC',
                ['benign-1', 'benign-2'],
                'chart-benign',
            ),
            {'id': 'arrow-zone', 'type': 'graphic', 'ref': 'transition-arrow'},
            _stage_panel(
                'drift-panel',
                '指标异化与刷榜',
                '#B85D3B',
                '#E2B8A8',
                '#FDF8F6',
                ['drift-1', 'drift-2'],
                'chart-drift',
            ),
        ],
        weights=[1.0, 0.14, 1.0],
        fit='stretch',
        gap='compact',
    )

    body = region(
        'case-evolution-root',
        'stack',
        [
            transition_pair,
            block_leaf('bottom-takeaway'),
        ],
        gap='compact',
    )

    slide = page(
        'case-evolution-transition',
        '案例一：公开基准驱动转向“过拟合刷榜”',
        '顶部通栏导航锚定章节位置，双边框卡片配合居中演进箭头对照良性初衷与异化风险。',
        blocks,
        body,
        graphics=[transition_arrow],
        charts=charts,
        presentation={'section': '案例剖析'},
    )
    return deck(
        'case-evolution-transition',
        [slide],
        presentation={
            'academic_design': {
                'title_treatment': 'accent-bar',
                'accent_color': '#B85D3B',
            },
            'section_nav': {
                'items': ['现象观察', '本质机理', '演进路径', '案例剖析', '治理应对'],
                'active_fill': '#B85D3B',
                'active_color': '#FFFFFF',
                'fill': '#F3F4F6',
                'color': '#52606D',
                'divider_color': '#CBD5E1',
            },
            'hide_takeaway': True,
            'page_numbers': False,
        },
    )
