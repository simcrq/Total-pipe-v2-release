"""Expose a counterexample while retaining the sample-level paired changes."""
from statistics import median

from common import block_leaf, chip_panel, deck, page, region


PAIRS = (('A', 24, 18), ('B', 30, 21), ('C', 26, 20), ('D', 22, 23), ('E', 27, 19))
CHANGES = [after-before for _, before, after in PAIRS]
IMPROVED = sum(change < 0 for change in CHANGES)
EXCEPTION, EXCEPTION_BEFORE, EXCEPTION_AFTER = next(row for row in PAIRS if row[2] > row[1])
COOL = '#237681'
WARM = '#B55329'
NEUTRAL = '#637D90'
TICKS = tuple(range(16, 33, 4))


def plot_x(value):
    return 136 + 30 * (value-TICKS[0])


def dot(id, x, y, stroke, fill):
    radius, tangent = 6.5, 3.59
    return {'id': id, 'stroke': stroke, 'fill': fill, 'line_width': 2, 'commands': [
        ['M', x+radius, y],
        ['C', x+radius, y+tangent, x+tangent, y+radius, x, y+radius],
        ['C', x-tangent, y+radius, x-radius, y+tangent, x-radius, y],
        ['C', x-radius, y-tangent, x-tangent, y-radius, x, y-radius],
        ['C', x+tangent, y-radius, x+radius, y-tangent, x+radius, y],
        ['Z'],
    ]}


def paired_graphic():
    exception_index = next(index for index, row in enumerate(PAIRS) if row[0] == EXCEPTION)
    exception_y = 78 + 43 * exception_index
    paths = [
        {'id': 'exception-band', 'stroke': 'none', 'fill': '#FCF0E5',
         'd': f'M 12 {exception_y-19} L 646 {exception_y-19} '
              f'L 646 {exception_y+19} L 12 {exception_y+19} Z'},
        {'id': 'grid', 'stroke': '#D7E2E8', 'line_width': 1,
         'd': ' '.join(f'M {plot_x(tick)} 58 L {plot_x(tick)} 273' for tick in TICKS)},
        {'id': 'axis', 'd': f'M {plot_x(TICKS[0])} 273 L {plot_x(TICKS[-1])} 273',
         'stroke': NEUTRAL, 'line_width': 1.5},
        dot('key-before', 149, 25, NEUTRAL, '#FFFFFF'),
        dot('key-after', 331, 25, COOL, COOL),
    ]
    labels = [
        {'id': 'key-before', 'text': '处理前', 'box': [165, 7, 111, 39]},
        {'id': 'key-after', 'text': '处理后', 'box': [347, 7, 111, 39]},
    ]
    for index, (name, before, after) in enumerate(PAIRS):
        y = 78 + 43 * index
        x0, x1 = plot_x(before), plot_x(after)
        color = WARM if after > before else COOL
        paths.extend([
            {'id': f'pair-{name}', 'd': f'M {x0} {y} L {x1} {y}', 'stroke': color, 'line_width': 2.8},
            dot(f'before-{name}', x0, y, color, '#FFFFFF'),
            dot(f'after-{name}', x1, y, color, color),
        ])
        labels.append({'id': f'sample-{name}', 'text': f'样品 {name}', 'box': [21, y-18, 102, 38]})
    labels.append({'id': 'exception-delta', 'text': f'上升 {EXCEPTION_AFTER-EXCEPTION_BEFORE}',
                   'box': [plot_x(EXCEPTION_AFTER)+24, exception_y-18, 166, 38]})
    labels.extend({'id': f'tick-{tick}', 'text': str(tick), 'box': [plot_x(tick)-15, 277, 46, 38]}
                  for tick in TICKS)
    labels.append({'id': 'axis-title', 'text': 'RMS 噪声 (a.u.)', 'box': [306, 314, 270, 38]})
    return {'id': 'paired-plot', 'type': 'path', 'view_box': [0, 0, 650, 356],
            'paths': paths, 'labels': labels}


def make_deck():
    blocks = [
        {'id': 'median-change', 'component': 'metric', 'label': '配对差中位数（后 − 前）',
         'text': f'{median(CHANGES):g} a.u.'.replace('-', '−')},
        {'id': 'same-sample', 'component': 'body', 'text': '沿每条线比较同一个样品的两次读数。',
         'text_flow': 'native_numbered_list', 'list_start': 1},
        {'id': 'reversal', 'component': 'body',
         'text': f'查看橙色行。样品 {EXCEPTION} 从 {EXCEPTION_BEFORE} 升到 {EXCEPTION_AFTER} a.u.。',
         'text_flow': 'native_numbered_list', 'list_start': 2, 'bullet_color': WARM},
    ]
    source = {'kind': 'example', 'constructed': True, 'source': '脚本内五组配对读数'}
    for block in blocks:
        block.update(basis='supplement', supplement=source)

    readout = region('paired-observations', 'stack', [
        block_leaf('same-sample'), block_leaf('reversal'), block_leaf('median-change'),
    ], gap='standard')
    body = region('paired-evidence', 'columns', [
        {'id': 'dumbbell', 'type': 'graphic', 'ref': 'paired-plot'},
        region('guide-column', 'stack', [
            chip_panel('reading-guide', '逐对读变化', readout),
        ], align='center'),
    ], weights=[1.97, 1], gap='standard')
    slide = page(
        'paired-noise', f'{len(PAIRS)} 个样品中有 {IMPROVED} 个噪声下降，样品 {EXCEPTION} 例外',
        '构造示例 · 各样品在相同窗口内测量处理前后的 RMS 噪声，数值越低越安静。',
        blocks, body, graphics=[paired_graphic()], evidence_refs=(),
    )
    slide['semantic']['speaker_notes'] = '差值定义为处理后减处理前。这里只描述这五组构造读数的方向和中位数。'
    result = deck('paired-noise-dumbbell', [slide])
    result['theme'].update(font_family='Microsoft YaHei', font_file='msyh.ttc', bold_font_file='msyh.ttc')
    result['presentation']['text_capacity_policy'] = 'strict'
    return result
