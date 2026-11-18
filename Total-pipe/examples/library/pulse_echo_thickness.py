"""Pair an editable pulse-echo cross section with a calculated time-of-flight readout."""
from common import block_leaf, deck, page, region


FRONT_US, BACK_US = 8, 12
SOUND_SPEED_MM_PER_US = 2.5
INTERVAL_US = BACK_US - FRONT_US
THICKNESS_MM = SOUND_SPEED_MM_PER_US * INTERVAL_US / 2
FRONT = '#277482'
BACK = '#B55329'
AXIS = '#708493'


def echo_peak(id, center, peak_y, color):
    return {'id': id, 'stroke': color, 'line_width': 3, 'd':
            f'M {center-66} 170 C {center-23} 170 {center-22} {peak_y} {center} {peak_y} '
            f'C {center+22} {peak_y} {center+23} 170 {center+66} 170'}


def echo_graphic():
    first_x, second_x = (406 + 38 * time for time in (FRONT_US, BACK_US))
    return {
        'id': 'echo-map', 'type': 'path', 'view_box': [0, 0, 1070, 246],
        'paths': [
            {'id': 'sample', 'd': 'M 38 108 L 265 108 L 265 186 L 38 186 Z',
             'fill': '#E3EEF2', 'stroke': 'none'},
            {'id': 'probe', 'd': 'M 68 22 L 241 22 L 241 63 L 68 63 Z',
             'fill': '#E1E7EB', 'stroke': '#7890A0'},
            {'id': 'walls', 'd': 'M 38 108 L 265 108 M 38 186 L 265 186',
             'stroke': '#8298A8', 'line_width': 1.6},
            {'id': 'front-travel', 'stroke': FRONT, 'line_width': 3,
             'd': 'M 102 64 L 102 101 M 95 94 L 102 102 L 109 94 '
                  'M 123 106 L 123 70 M 116 77 L 123 69 L 130 77'},
            {'id': 'back-travel', 'stroke': BACK, 'line_width': 3,
             'd': 'M 179 64 L 179 181 M 172 174 L 179 182 L 186 174 '
                  'M 201 183 L 201 70 M 194 77 L 201 69 L 208 77'},
            {'id': 'separation', 'd': 'M 373 18 L 373 218', 'stroke': '#D3DEE4', 'line_width': 1},
            {'id': 'axis', 'd': 'M 406 170 L 1040 170 M 1031 164 L 1040 170 L 1031 176',
             'stroke': AXIS, 'line_width': 1.6},
            {'id': 'interval', 'd': f'M {first_x} 66 L {first_x} 55 L {second_x} 55 L {second_x} 66',
             'stroke': '#617789', 'line_width': 1.5},
            {'id': 'time-marks', 'd': f'M {first_x} 168 L {first_x} 179 M {second_x} 168 L {second_x} 179',
             'stroke': AXIS, 'line_width': 1.8},
            echo_peak('front-echo', first_x, 83, FRONT),
            echo_peak('back-echo', second_x, 104, BACK),
        ],
        'labels': [
            {'id': 'probe-label', 'text': '探头', 'box': [107, 23, 95, 41]},
            {'id': 'front-label', 'text': '前壁', 'box': [270, 92, 96, 40]},
            {'id': 'back-label', 'text': '后壁', 'box': [270, 168, 96, 40]},
            {'id': 'signal', 'text': '回波波形', 'box': [410, 22, 171, 43]},
            {'id': 'delta', 'text': f'相隔 {INTERVAL_US} μs', 'box': [(first_x+second_x)/2-91, 9, 182, 42]},
            {'id': 'first-time', 'text': str(FRONT_US), 'box': [first_x-34, 180, 68, 42]},
            {'id': 'second-time', 'text': str(BACK_US), 'box': [second_x-34, 180, 68, 42]},
            {'id': 'time-title', 'text': '时间 (μs)', 'box': [934, 180, 135, 43]},
        ],
    }


def make_deck():
    blocks = [
        {'id': 'read-peaks', 'component': 'body', 'text': '沿着蓝绿和橙色声路，在波形上定位前壁和后壁回波。',
         'text_flow': 'native_numbered_list', 'list_start': 1,
         'text_for': {'kind': 'graphic', 'ref': 'echo-map', 'position': 'top'}},
        {'id': 'return-trip', 'component': 'body', 'text': '两峰间隔对应声波在试样内多走的一次往返。',
         'text_flow': 'native_numbered_list', 'list_start': 2},
        {'id': 'thickness', 'component': 'formula',
         'text': rf'd=\frac{{c\Delta t}}{{2}}={THICKNESS_MM:g}\,\mathrm{{mm}}'},
    ]
    source = {'kind': 'example', 'constructed': True, 'source': '脚本内构造峰位和法向传播模型'}
    for block in blocks:
        block.update(basis='supplement', supplement=source)

    body = region('echo-reading', 'stack', [
        {'id': 'pulse-echo', 'type': 'graphic', 'ref': 'echo-map'},
        region('convert-to-thickness', 'columns', [block_leaf('return-trip'), block_leaf('thickness')],
               weights=[1.5, 1], fit='hug', gap='standard'),
    ], align='center', gap='standard')
    slide = page(
        'echo-thickness', f'相隔 {INTERVAL_US} μs 的两次回波对应 {THICKNESS_MM:g} mm 厚度',
        f'构造示例 · 声波垂直进入试样，层内声速 c 为 {SOUND_SPEED_MM_PER_US:g} mm/μs。',
        blocks, body, graphics=[echo_graphic()], evidence_refs=(),
    )
    slide['semantic']['speaker_notes'] = '两峰采用同一触发基准。定位前后界面的回波后，用峰间隔乘声速得到往返路程。'
    result = deck('pulse-echo-thickness', [slide])
    result['theme'].update(font_family='Microsoft YaHei', font_file='msyh.ttc', bold_font_file='msyh.ttc')
    result['presentation']['text_capacity_policy'] = 'strict'
    return result
