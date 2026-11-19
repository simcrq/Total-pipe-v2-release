"""Define a condition, then map its factor categories onto a familiar analogy."""
from common import block_leaf, deck, page, region
from totalpipe_layout.inline_math import strip_markup


EXAMPLE_ID = 'definition-factor-analogy'
SOURCE = 'https://www.nrel.gov/docs/fy19osti/71712.pdf'
BLUE = '#234E86'
AMBER = '#AE4B20'
AMBER_TINT = '#FFF3E8'
BLUE_TINT = '#EEF5FF'
RED = '#A73732'
FRAME_WIDTH = 1160


def ellipse(cx, cy, rx, ry):
    k = 0.55228475
    dx, dy = rx * k, ry * k
    return [
        ['M', cx + rx, cy],
        ['C', cx + rx, cy + dy, cx + dx, cy + ry, cx, cy + ry],
        ['C', cx - dx, cy + ry, cx - rx, cy + dy, cx - rx, cy],
        ['C', cx - rx, cy - dy, cx - dx, cy - ry, cx, cy - ry],
        ['C', cx + dx, cy - ry, cx + rx, cy - dy, cx + rx, cy],
        ['Z'],
    ]


def rounded_box(x, y, width, height, radius):
    right, bottom = x + width, y + height
    return [
        ['M', x + radius, y], ['L', right - radius, y], ['Q', right, y, right, y + radius],
        ['L', right, bottom - radius], ['Q', right, bottom, right - radius, bottom],
        ['L', x + radius, bottom], ['Q', x, bottom, x, bottom - radius],
        ['L', x, y + radius], ['Q', x, y, x + radius, y], ['Z'],
    ]


def battery_symbol(cx):
    return [
        {'id': 'cell-heat', 'stroke': AMBER, 'fill': '#F9B94E', 'line_width': 1.5,
         'commands': [
             ['M', cx - 47, 114],
             ['Q', cx - 61, 91, cx - 37, 75],
             ['Q', cx - 43, 97, cx - 21, 92],
             ['Q', cx - 30, 75, cx - 4, 58],
             ['Q', cx - 7, 74, cx + 5, 82],
             ['Q', cx + 12, 72, cx + 10, 65],
             ['Q', cx + 36, 79, cx + 27, 98],
             ['Q', cx + 45, 91, cx + 42, 80],
             ['Q', cx + 64, 101, cx + 44, 114], ['Z'],
         ]},
        {'id': 'cell-case', 'stroke': AMBER, 'fill': '#FFFFFF', 'line_width': 3.5,
         'commands': rounded_box(cx - 66, 108, 122, 54, 9)},
        {'id': 'cell-terminal', 'stroke': AMBER, 'fill': AMBER, 'line_width': 1,
         'commands': rounded_box(cx + 56, 125, 10, 20, 2)},
        {'id': 'cell-bolt', 'stroke': AMBER, 'fill': AMBER, 'line_width': 1.5,
         'commands': [
             ['M', cx + 2, 114], ['L', cx - 17, 137], ['L', cx - 4, 137],
             ['L', cx - 10, 155], ['L', cx + 13, 130], ['L', cx, 130], ['Z'],
         ]},
    ]


def person_symbol(cx):
    return [
        {'id': 'person-head', 'stroke': BLUE, 'fill': BLUE, 'line_width': 1,
         'commands': ellipse(cx, 84, 12, 12)},
        {'id': 'person-body', 'stroke': BLUE, 'line_width': 6,
         'commands': [
             ['M', cx, 106], ['L', cx, 134],
             ['M', cx - 25, 117], ['L', cx, 106], ['L', cx + 25, 117],
             ['M', cx - 19, 160], ['L', cx, 134], ['L', cx + 19, 160],
         ]},
    ]


def factor_analogy():
    """Group five example factors around each central subject."""
    paths, labels = [], []
    groups = (
        ('cell', 272, AMBER, AMBER_TINT, '电芯热失控', battery_symbol,
         ('电芯老化', '充放电异常', '内部损伤', '环境温度', '散热受限')),
        ('person', 888, BLUE, BLUE_TINT, '人体健康状态', person_symbol,
         ('既往疾病', '生活习惯', '遗传因素', '环境暴露', '休息不足')),
    )
    positions = (
        ('upper-left', -96, 23), ('upper-right', 105, 23),
        ('left', -170, 111), ('right', 170, 111),
        ('bottom', -72, 197),
    )
    for key, cx, ink, tint, subject, symbol, examples in groups:
        paths.append({'id': f'{key}-ring', 'stroke': '#B57068', 'fill': tint, 'line_width': 1.5,
                      'commands': ellipse(cx, 128, 203, 97)})
        paths.extend(symbol(cx))
        labels.append({'id': f'{key}-subject', 'text': subject, 'box': [cx - 108, 161, 216, 36]})
        for (position, dx, y), factor in zip(positions, examples):
            x = cx + dx - 75
            paths.append({'id': f'{key}-{position}-tag', 'stroke': ink, 'fill': '#FFFFFF',
                          'line_width': 0.85, 'commands': rounded_box(x, y, 150, 40, 12)})
            labels.append({'id': f'{key}-{position}', 'text': factor, 'box': [x + 3, y + 1, 144, 38]})

    paths.append({
        'id': 'analogy-link', 'stroke': BLUE, 'fill': BLUE, 'line_width': 1,
        'commands': [['M', 530, 129], ['L', 548, 112], ['L', 548, 122],
                     ['L', 612, 122], ['L', 612, 112], ['L', 630, 129],
                     ['L', 612, 146], ['L', 612, 136], ['L', 548, 136],
                     ['L', 548, 146], ['Z']],
    })
    labels.append({'id': 'relation', 'text': '类比', 'box': [529, 69, 102, 39]})
    return paths, labels


def definition_and_analogy():
    """Use one view box so both editable frames share the same physical scale."""
    offset = 151
    analogy_paths, analogy_labels = factor_analogy()
    frames = [
        {'id': id, 'stroke': BLUE, 'fill': '#FFFFFF', 'line_width': 1.7,
         'commands': rounded_box(0, y, FRAME_WIDTH, height, 17)}
        for id, y, height in (('definition-frame', 1, 133), ('analogy-frame', offset + 1, 250))
    ]
    lines = (
        ('thermal-runaway-definition', '热失控时，电芯内部的**放热反应自我加速**，使温度迅速、不可控地上升。'),
        ('thermal-feedback', '**产热持续超过散热**时，热量积累。温升又可加快放热反应。'),
        ('risk-factors', '电芯的**当前状态**、使用工况和外部环境都会影响热失控风险。'),
    )
    labels = [
        {'id': id, 'text': phrase, 'box': [29, 8 + 40 * i, 28 * len(strip_markup(phrase)) + 16, 40]}
        for i, (id, phrase) in enumerate(lines)
    ]
    # The lower diagram is authored in its own local coordinates for easy content replacement.
    for path in analogy_paths:
        path['commands'] = [
            [op, *(coord + offset if i % 2 else coord for i, coord in enumerate(coords))]
            for op, *coords in path['commands']
        ]
    for label in analogy_labels:
        label['box'][1] += offset
    return {'id': 'factor-pair', 'type': 'path', 'view_box': [0, 0, FRAME_WIDTH, 403],
            'paths': [*frames, *analogy_paths], 'labels': [*labels, *analogy_labels]}


def make_deck():
    analogy = {
        'id': 'factor-category-correspondence', 'component': 'caption',
        'text': '两圈都从自身状态、使用或行为、外部环境三方面理解风险。',
        'caption_for': {'kind': 'graphic', 'ref': 'factor-pair'},
        'basis': 'supplement', 'supplement': {
            'kind': 'analogy', 'constructed': True,
            'source': 'definition_factor_analogy.py',
            'assumptions': ['左右各选取五个定性因素，用相同的三类视角观察两种情境。'],
        },
    }
    body = region('definition-and-analogy', 'stack', [
        {'id': 'analogy-diagram', 'type': 'graphic', 'ref': 'factor-pair'},
        block_leaf(analogy['id']),
    ], gap='compact')
    slide = page(
        'factor-analogy', '动力电池热失控的定义与理解',
        '构造示例 · 借人体健康理解热失控的风险来源',
        [analogy], body, graphics=[definition_and_analogy()], evidence_refs=(),
    )
    slide['semantic'].update(
        purpose='先建立概念定义，再用熟悉情境说明为何需要同时考虑不同类别的因素。',
        speaker_notes=(
            '放热自加速是热失控的定义要点。参见 Finegan 等，Journal of Power Sources 417 (2019)，'
            f'第 29–41 页，引言。{SOURCE}\n'
            '双圈为构造示例。电芯侧可从老化与内部损伤、充放电工况、外部温度与散热能力来梳理。'
            '人体侧可用既往疾病和遗传因素、生活习惯和休息、环境暴露来理解同样三类视角。'
            '双向箭头表示对照两组因素的思路。各标签的排列仅服务于视觉分组。'
        ),
    )
    output = deck(EXAMPLE_ID, [slide])
    output['theme'].update(accent=BLUE, foreground='#17283D', font_family='Microsoft YaHei',
                           font_file='msyh.ttc', bold_font_file='msyh.ttc')
    output['presentation']['academic_design'].update(density='compact', type_scale='compact')
    output['presentation']['visual_style'] = {'pack': 'academic', 'overrides': {'text.emphasis': RED}}
    output['presentation']['text_capacity_policy'] = 'strict'
    return output
