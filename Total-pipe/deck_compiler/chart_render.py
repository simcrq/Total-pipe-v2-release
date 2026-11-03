"""Chart rendering: native shapes and measured text for line and bar plots.

The contract lives in ``chart_layout``. This module only draws what the contract allows: axes,
ticks, series, legend and provenance, all as editable shapes/text so the existing geometry and font
gates keep applying. It never embeds an image and never invents a value.
"""
import math

from PIL import ImageFont

MARGIN = {'left': 96., 'right': 24., 'top': 46., 'bottom': 104.}
MIN_SIZE = (420., 260.)
PALETTE = ('#0F4C81', '#C2410C', '#2F7D6D', '#7A4E9E')
TICK_SIZE = 20
LABEL_SIZE = 24
SOURCE_SIZE = 20


class ChartLayoutError(ValueError):
    rule = 'CHART_CAPACITY'


def chart_need(chart, width):
    """Minimum and preferred region for a chart; the tree owns the final box."""
    from .layout_tree import Need
    return Need(MIN_SIZE[1], 320. if len(chart.get('series') or []) <= 2 else 344., MIN_SIZE[0])


def _fmt(value):
    if abs(value) >= 10000 or (value and abs(value) < .01):
        return f'{value:.1e}'.replace('e+0', 'e').replace('e-0', 'e-')
    if abs(value-round(value)) < 1e-9:
        return str(int(round(value)))
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def _linear_ticks(low, high, count=4):
    if high <= low:
        high = low+1
    raw = (high-low)/count
    magnitude = 10**math.floor(math.log10(raw)) if raw > 0 else 1
    for factor in (1, 2, 2.5, 5, 10):
        step = factor*magnitude
        if raw <= step:
            break
    start = math.ceil(low/step)*step
    ticks = []
    value = start
    while value <= high+step*1e-9 and len(ticks) <= count+2:
        ticks.append(round(value, 10))
        value += step
    return ticks or [low, high]


def _log_ticks(low, high):
    if low <= 0 or high <= 0:
        raise ChartLayoutError('a log axis cannot contain zero or negative values')
    first, last = math.floor(math.log10(low)), math.ceil(math.log10(high))
    ticks = [10.**power for power in range(first, last+1)
             if low*(1-1e-9) <= 10.**power <= high*(1+1e-9)]
    if not ticks:
        ticks = [low, high]
    else:
        if ticks[0] > low*(1+1e-6):
            ticks.insert(0, low)
        if ticks[-1] < high*(1-1e-6):
            ticks.append(high)
    if len(ticks) > 6:
        ticks = ticks[::2]
    return ticks


def _positions(values, low, high, scale, start, length):
    if scale == 'log':
        low, high = math.log10(max(low, 1e-12)), math.log10(max(high, 1e-12))
        project = lambda value: (math.log10(value)-low)/(high-low) if high > low else .5
    else:
        project = lambda value: (value-low)/(high-low) if high > low else .5
    return [start+project(value)*length for value in values]


def _shape(eid, bbox, fill, geometry='rect'):
    return {'id': eid, 'kind': 'shape', 'role': 'decoration', 'bbox': list(bbox),
            'geometry': geometry, 'fill': fill, 'line': 'none', 'line_width': 0}


def _polyline(eid, xs, ys, color, width=2.5):
    """One editable stroke shape per series; OfficeCLI connects only graphic edges, not plot lines."""
    from .graphic_paths import custom_geometry
    low_x, high_x, low_y, high_y = min(xs), max(xs), min(ys), max(ys)
    box = [low_x, low_y, max(1., high_x-low_x), max(1., high_y-low_y)]
    commands = [('M', xs[0], ys[0])] + [('L', x, y) for x, y in zip(xs[1:], ys[1:])]
    return {'id': eid, 'kind': 'shape', 'role': 'chart-line', 'bbox': box,
            'geometry': 'rect', 'fill': 'none', 'line': color, 'line_width': width,
            'custom_geometry': custom_geometry(commands, box)}


def _text(eid, content, bbox, color, size=TICK_SIZE, align='left', lines=1, role='caption'):
    return {'id': eid, 'kind': 'text', 'text': content, 'bbox': list(bbox),
            'role': role, 'font_size': size, 'max_lines': lines,
            'color': color, 'align': align}


def compile_chart(chart, bbox, theme, font_paths):
    """Native elements for one chart. Raises ``ChartLayoutError`` when it cannot be drawn."""
    x, y, w, h = bbox
    if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
        raise ChartLayoutError(f'chart needs at least {MIN_SIZE[0]:.0f}x{MIN_SIZE[1]:.0f} px, '
                               f'got {w:.0f}x{h:.0f}')
    left, right = MARGIN['left'], MARGIN['right']
    top, bottom = MARGIN['top'], MARGIN['bottom']
    plot = (x+left, y+top, w-left-right, h-top-bottom)
    if plot[2] < 120 or plot[3] < 80:
        raise ChartLayoutError('chart body is too small for axes and a series')
    px, py, pw, ph = plot
    accent = theme.get('accent', PALETTE[0])
    ink = theme.get('foreground', '#142735')
    muted = theme.get('muted', '#6B7A88')
    grid = theme.get('rule', '#D8DEE6')
    face = ImageFont.truetype(str(font_paths['font_file']), TICK_SIZE)

    x_values = list(chart['x']['values'])
    series = chart['series']
    x_scale = chart['x'].get('scale', 'linear')
    y_scale = chart['y'].get('scale', 'linear')
    y_values = [value for entry in series for value in entry['values']]
    y_low, y_high = min(y_values), max(y_values)
    if chart['kind'] == 'bar':
        y_low = min(0., y_low)
        y_high = max(0., y_high)
    if y_high <= y_low:
        y_high = y_low+1.
    pad = (y_high-y_low)*.08
    if chart['kind'] == 'line':
        y_low, y_high = y_low-pad, y_high+pad
    x_low, x_high = (0., float(len(x_values)-1)) if chart['kind'] == 'bar' else (min(x_values), max(x_values))
    if x_high <= x_low:
        x_high = x_low+1.

    elements = []
    # Axes and horizontal guides.
    elements.append(_shape(f'chart:{chart["id"]}:axis-y', [px, py, 1, ph], ink))
    elements.append(_shape(f'chart:{chart["id"]}:axis-x', [px, py+ph, pw, 1], ink))
    y_ticks = _log_ticks(y_low, y_high) if y_scale == 'log' else _linear_ticks(y_low, y_high, 4)
    y_positions = _positions(y_ticks, y_low, y_high, y_scale, py+ph, -ph)
    for index, (tick, ty) in enumerate(zip(y_ticks, y_positions)):
        label = _fmt(tick)
        width = face.getlength(label)+8
        if width > left-16:
            raise ChartLayoutError(f'y tick label {label!r} does not fit the chart margin')
        elements.append(_shape(f'chart:{chart["id"]}:ytick:{index}', [px-5, ty-.5, 5, 1], ink))
        elements.append(_text(f'chart:{chart["id"]}:ylabel:{index}', label,
                              [px-width-8, ty-14, width, 28], muted, TICK_SIZE, 'right'))
        if index:
            elements.append(_shape(f'chart:{chart["id"]}:grid:{index}', [px, ty, pw, 1], grid))

    if chart['kind'] == 'bar':
        x_ticks = [float(index) for index in range(len(x_values))]
    elif x_scale == 'log':
        x_ticks = _log_ticks(x_low, x_high)
    else:
        x_ticks = _linear_ticks(x_low, x_high, 5)
    x_positions = _positions(x_ticks, x_low, x_high, x_scale, px, pw)
    for index, (tick, tx) in enumerate(zip(x_ticks, x_positions)):
        label = _fmt(x_values[index]) if chart['kind'] == 'bar' else _fmt(tick)
        width = face.getlength(label)+8
        elements.append(_shape(f'chart:{chart["id"]}:xtick:{index}', [tx-.5, py+ph, 1, 5], ink))
        label_x = min(max(tx-width/2, x+2), x+w-width-2)
        elements.append(_text(f'chart:{chart["id"]}:xlabel:{index}', label,
                              [label_x, py+ph+6, width, 28], muted, TICK_SIZE, 'center'))

    # Series.
    for series_index, entry in enumerate(series):
        color = PALETTE[series_index % len(PALETTE)]
        if chart['kind'] == 'bar':
            band = pw/len(x_values)
            width = band*.6/max(1, len(series))
            zero = _positions([0.], y_low, y_high, y_scale, py+ph, -ph)[0]
            for point, value in enumerate(entry['values']):
                centre = px+(point+.5)*band+series_index*width-(len(series)-1)*width/2
                top_y = _positions([value], y_low, y_high, y_scale, py+ph, -ph)[0]
                elements.append(_shape(f'chart:{chart["id"]}:bar:{series_index}:{point}',
                                       [centre-width/2, min(top_y, zero), width, abs(zero-top_y)],
                                       color))
        else:
            points = _positions(entry['values'], y_low, y_high, y_scale, py+ph, -ph)
            xs = _positions(x_values, x_low, x_high, x_scale, px, pw)
            elements.append(_polyline(f'chart:{chart["id"]}:line:{series_index}', xs, points, color))
            for point, (cx, cy) in enumerate(zip(xs, points)):
                elements.append(_shape(f'chart:{chart["id"]}:dot:{series_index}:{point}',
                                       [cx-3, cy-3, 6, 6], color, 'ellipse'))

    # Axis titles.
    elements.append(_text(f'chart:{chart["id"]}:x-title', chart['x']['label'],
                          [px, y+h-70, pw, 32], ink, LABEL_SIZE, 'center', role='body'))
    y_label = chart['y']['label'] + (f' ({chart["y"]["unit"]})' if chart.get('y', {}).get('unit') else '')
    elements.append(_text(f'chart:{chart["id"]}:y-title', y_label,
                          [px, y+2, pw, 32], ink, LABEL_SIZE, 'left', role='body'))

    # Legend: always shown above the plot on the right, one row.
    legend = []
    cursor = px+pw
    for series_index, entry in enumerate(series):
        color = PALETTE[series_index % len(PALETTE)]
        width = face.getlength(entry['label'])+8
        cursor -= width+6
        legend.append(_text(f'chart:{chart["id"]}:legend:{series_index}', entry['label'],
                            [cursor, y+2, width, 28], ink, TICK_SIZE, 'left'))
        legend.append(_shape(f'chart:{chart["id"]}:swatch:{series_index}', [cursor-14, y+10, 10, 10], color))
        cursor -= 14
        if cursor < px+pw*.45:
            raise ChartLayoutError(f'chart legend does not fit: {entry["label"]!r}')
    elements.extend(legend)

    # Provenance and the illustrative badge.
    if chart.get('source'):
        width = face.getlength(chart['source'])+8
        elements.append(_text(f'chart:{chart["id"]}:source', chart['source'],
                              [x+w-right-width, y+h-32, width, 28], muted, SOURCE_SIZE, 'right'))
    if chart.get('basis') == 'explain':
        elements.append({**_shape(f'chart:{chart["id"]}:badge', [x+8, y+8, 46, 28], accent),
                         'node_id': 'badge'})
        elements.append({**_text(f'chart:{chart["id"]}:badge-text', '示意',
                                 [x+8, y+8, 46, 28], '#FFFFFF', TICK_SIZE, 'center'),
                         'node_id': 'badge'})
    for element in elements:
        element['graphic_id'] = f'chart:{chart["id"]}'
        element['overlap_group'] = f'chart:{chart["id"]}'
    return elements
