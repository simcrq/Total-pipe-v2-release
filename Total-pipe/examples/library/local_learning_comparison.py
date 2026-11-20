"""Aligned training routes, a localized mechanism change, and its update rules."""
from common import block_leaf, comparison_table, deck, page, region
from comparison_lanes import arrow, rounded_box


PURPLE = '#542099'
LAVENDER = '#F8F5FC'
MUTED_PURPLE = '#927BAF'
ORANGE = '#BA420F'
PEACH = '#FFF3E9'
INK = '#191524'
SOURCE = 'https://arxiv.org/abs/2006.01981'
EXAMPLE_ID = 'local-learning-comparison'

STAGES = (
    ('a', 'A 反向传播', (
        ('forward', '前向推理', 'matrix'),
        ('loss', '计算损失', 'loss'),
        ('backward', '逐层反传', 'backward'),
        ('write', '按梯度写入', 'pulse'),
    )),
    ('b', 'B 平衡传播', (
        ('free', '自由相弛豫', 'grid'),
        ('nudge', '微扰相弛豫', 'nudge'),
        ('local', '局部压降驱动', 'drop'),
        ('write', '局部写入', 'pulse'),
    )),
)


def circle(x, y, r):
    k = 0.55228475 * r
    return [
        ['M', x + r, y],
        ['C', x + r, y + k, x + k, y + r, x, y + r],
        ['C', x - k, y + r, x - r, y + k, x - r, y],
        ['C', x - r, y - k, x - k, y - r, x, y - r],
        ['C', x + k, y - r, x + r, y - k, x + r, y],
        ['Z'],
    ]


def polyline(*points):
    return [['M', *points[0]], *[['L', *point] for point in points[1:]]]


def stage_symbol(name):
    """Return vector strokes in the same local coordinate system for each symbol."""
    if name == 'matrix':
        return (
            polyline((-56, -23), (-63, -23), (-63, 23), (-56, 23))
            + polyline((56, -23), (63, -23), (63, 23), (56, 23))
            + [command for x in (-40, -20, 0, 20, 40) for y in (-14, 0, 14)
               for command in circle(x, y, 3)]
        )
    if name == 'pulse':
        return (
            polyline((-78, 12), (-62, 12), (-62, -14), (-46, -14), (-46, 12),
                     (-29, 12), (-29, -14), (-13, -14), (-13, 12), (0, 12))
            + polyline((10, 0), (32, 0))
            + polyline((25, -6), (32, 0), (25, 6))
            + polyline((46, 0), (53, 0), (53, -13), (78, -13), (78, 13),
                       (53, 13), (53, 0))
            + polyline((78, 0), (88, 0))
            + polyline((58, 6), (63, 6), (63, -6), (70, -6), (70, 6), (75, 6))
        )
    if name == 'drop':
        return (circle(-66, 0, 7) + circle(66, 0, 7)
                + polyline((-59, 0), (-39, 0)) + polyline((39, 0), (59, 0)))

    xs, ys = (-47, 0, 47), (-18, 0, 18)
    commands = [command for x in xs for y in ys for command in circle(x, y, 5)]
    for y in ys:
        for left, right in zip(xs, xs[1:]):
            start = left + 7
            commands += polyline((start, y), (right - 7, y))
            if name == 'backward':
                commands += polyline((start + 7, y - 4), (start, y), (start + 7, y + 4))
    if name in ('grid', 'nudge'):
        for x in xs:
            for top, bottom in zip(ys, ys[1:]):
                commands += polyline((x, top + 5), (x, bottom - 5))
    if name == 'nudge':
        commands += polyline((61, -21), (71, -21), (71, 21), (61, 21))
        commands += polyline((85, 0), (71, 0), (77, -5)) + polyline((71, 0), (77, 5))
    return commands


def place_symbol(commands, x, y):
    return [[op, *(value * 0.65 + (x if i % 2 == 0 else y) for i, value in enumerate(coords))]
            for op, *coords in commands]


def training_routes():
    paths = []
    labels = []

    def label(id, text, x, y, width, height=32):
        labels.append({'id': id, 'text': text, 'box': [x, y, width, height]})

    card_width, stride, first_card = 218, 262, 165
    for (lane, name, stages), y in zip(STAGES, (2, 109)):
        lane_color = PURPLE if lane == 'a' else ORANGE
        paths.append({'id': f'lane-{lane}-marker', 'stroke': lane_color, 'line_width': 3,
                      'commands': polyline((1, y + 25), (1, y + 53))})
        label(f'{lane}-name', name, 8, y + 23, 142)
        for index, (id, title, symbol) in enumerate(stages):
            x = first_card + index * stride
            key = f'{lane}-{id}'
            highlighted = symbol == 'drop'
            color = ORANGE if highlighted else MUTED_PURPLE
            card = rounded_box(key, x, y, card_width, 78)
            paths.append(dict(card, fill=PEACH if highlighted else LAVENDER, stroke=color,
                              line_width=2.5 if highlighted else 0.9))
            label(f'{key}-title', title, x + 8, y + 7, card_width - 16)
            center, baseline = x + card_width / 2, y + 55
            if symbol == 'loss':
                label(f'{key}-loss', 'L(ŷ, y)', center - 60, baseline - 16, 120)
            else:
                paths.append({'id': f'{key}-symbol', 'stroke': ORANGE if highlighted else INK,
                              'line_width': 1.65,
                              'commands': place_symbol(stage_symbol(symbol), center, baseline)})
            if highlighted:
                label(f'{key}-delta', 'ΔV', center - 25, baseline - 16, 50)
            if index < len(stages) - 1:
                connector = arrow(f'{key}-next', x + card_width + 8, x + stride - 8, y + 39)
                paths.append(dict(connector, stroke=color))

    # The orange arrow links the storage implication to the exact step that changes.
    center = first_card + 2 * stride + card_width / 2
    paths.append({'id': 'local-callout-arrow', 'stroke': ORANGE, 'line_width': 2,
                  'commands': polyline((center, 204), (center, 189))
                  + polyline((center - 5, 194), (center, 189), (center + 5, 194))})
    label('local-cache-callout', '免存整网反传梯度', center - 160, 205, 320)
    return {'id': 'training-routes', 'type': 'path', 'view_box': [0, 0, 1172, 237],
            'paths': paths, 'labels': labels}


def make_deck():
    assumptions = ['以耦合电阻网络为构造示例，各支路的可调参数为欧姆电导。',
                   '两相保持输入不变。微扰只施加在输出端，梯度估计取弱微扰极限。']
    blocks = [
        {'id': 'backprop-update', 'component': 'body', 'inline_math': True,
         'text': r'A   $\Delta g=-\eta(\partial L/\partial g)$'},
        {'id': 'equilibrium-update', 'component': 'body', 'inline_math': True,
         'text': r'B   $\Delta g\approx-\eta(u_{\beta}^{2}-u_{0}^{2})/(2\beta)$'},
    ]
    for block in blocks:
        block.update(basis='supplement', supplement={'kind': 'derivation', 'constructed': True,
                                                     'source': SOURCE, 'assumptions': assumptions})
    table = comparison_table('architecture-mechanism', [
        ('对比维度', 'A 反向传播', 'B 平衡传播'),
        ('梯度来源', '链式求导', '压降平方差'),
        ('所需状态', '缓存或重算激活', '自由相支路压降'),
    ], [1, 1.53, 1.58])
    lower = region('mechanism-and-rules', 'columns', [
        {'id': 'mechanism-panel', 'type': 'panel', 'title': '训练机制对照',
         'padding': 'none', 'gap': 'compact',
         'body': {'id': 'mechanism-table', 'type': 'table', 'ref': table['id']}},
        {'id': 'rules-panel', 'type': 'panel', 'title': '电导更新规则（u 为支路压降）',
         'padding': 'none', 'gap': 'compact',
         'body': region('rule-blocks', 'stack', [block_leaf(block['id']) for block in blocks])},
    ], weights=[1.05, 1], gap='spacious')
    body = region('architecture-comparison', 'stack', [
        {'id': 'route-diagram', 'type': 'graphic', 'ref': 'training-routes'},
        lower,
    ], gap='standard')
    slide = page(
        'local-learning', '平衡传播用两相局部电压估计电导梯度',
        '构造示例 · 同一电阻网络的两种训练路线',
        blocks, body, graphics=[training_routes()], tables=[table], evidence_refs=(),
    )
    slide['semantic'].update(
        purpose='对齐两条训练路线，定位梯度来源的替换，并用表格和同一电导参数的更新式核对。',
        speaker_notes=(
            '外层更新均采用梯度下降。以电阻支路 i–j 的欧姆电导为参数，'
            'u 即图中的支路两端压降 ΔV。0 表示自由相，β 为微扰强度，η 为学习率。'
            '路线 A 逐层传递激活，以预测与目标计算损失，按链式法则计算梯度并写入电导。'
            '路线 B 先记录自由相稳态，再向输出端注入微扰。由两相读数计算支路压降平方差，再写入电导。'
            f'理论依据：Kendall 等（2020），定理 1，{SOURCE}。'
            '流程图为自制机制示意，不代表某种器件的实测结果。'
        ),
    )
    output = deck(EXAMPLE_ID, [slide])
    output['theme'].update(accent=PURPLE, foreground=INK, font_family='Microsoft YaHei',
                           font_file='msyh.ttc', bold_font_file='msyh.ttc')
    output['presentation']['academic_design'].update(density='compact')
    output['presentation']['text_capacity_policy'] = 'strict'
    output['presentation']['page_numbers'] = False
    return output
