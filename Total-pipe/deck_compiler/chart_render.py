"""Chart rendering: native shapes and measured text for line, bar, hbar and scatter plots.

The contract lives in ``chart_layout``. This module only draws what the contract allows: axes,
ticks, series, reference lines, shaded zones, legend and provenance, all as editable shapes/text so
the existing geometry and font gates keep applying. It never embeds an image and never invents a value.
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
    n_series = len(chart.get('series') or [])
    if chart.get('kind') == 'hbar':
        cats = len((chart.get('x') or {}).get('categories') or (chart.get('x') or {}).get('values') or [])
        pref_h = max(300., min(380., 160. + cats * 38.))
        return Need(MIN_SIZE[1], pref_h, MIN_SIZE[0])
    return Need(MIN_SIZE[1], 320. if n_series <= 2 else 344., MIN_SIZE[0])


def _fmt(value):
    if isinstance(value, str):
        return value
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


def _geometry_shape(eid, commands, color, width=1.5):
    """One open stroke path (error bar, leader, dashed ref line) as a native custom-geometry shape."""
    from .graphic_paths import custom_geometry
    xs = [x for _, x, _ in commands]
    ys = [y for _, _, y in commands]
    low_x, high_x, low_y, high_y = min(xs), max(xs), min(ys), max(ys)
    box = [low_x, low_y, max(1., high_x-low_x), max(1., high_y-low_y)]
    return {'id': eid, 'kind': 'shape', 'role': 'chart-mark', 'bbox': box,
            'geometry': 'rect', 'fill': 'none', 'line': color, 'line_width': width,
            'custom_geometry': custom_geometry(commands, box)}


def _dashed_line(eid, x1, y1, x2, y2, color, width=1.5, dash=8., gap=5.):
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist <= 1e-6:
        return _shape(eid, [x1, y1, 1, 1], color)
    ux, uy = (x2 - x1) / dist, (y2 - y1) / dist
    commands = []
    pos = 0.0
    while pos < dist:
        end = min(dist, pos + dash)
        commands.append(('M', x1 + ux * pos, y1 + uy * pos))
        commands.append(('L', x1 + ux * end, y1 + uy * end))
        pos += dash + gap
    return _geometry_shape(eid, commands, color, width)


def _text(eid, content, bbox, color, size=TICK_SIZE, align='left', lines=1, role='caption'):
    return {'id': eid, 'kind': 'text', 'text': content, 'bbox': list(bbox),
            'role': role, 'font_size': size, 'max_lines': lines,
            'color': color, 'align': align}


def _boxes_overlap(a, b, pad=2.0):
    return not (
        a[0] + a[2] + pad <= b[0]
        or b[0] + b[2] + pad <= a[0]
        or a[1] + a[3] + pad <= b[1]
        or b[1] + b[3] + pad <= a[1]
    )


def _segment_hits_box(x1, y1, x2, y2, box, pad=2.0):
    from .dag_layout import segment_hits_node
    expanded = [box[0] - pad, box[1] - pad, box[2] + 2 * pad, box[3] + 2 * pad]
    return segment_hits_node((x1, y1), (x2, y2), expanded)


def _pack_legend_rows(series, widths, max_row_width):
    """Pack legend items into 1 row when compact, or up to 2 balanced rows when wide."""
    item_widths = [w + 22 for w in widths]
    if sum(item_widths) <= max_row_width:
        return [list(range(len(series)))]
    rows = [[]]
    row_w = 0.0
    for idx, iw in enumerate(item_widths):
        if rows[-1] and row_w + iw > max_row_width:
            rows.append([idx])
            row_w = iw
        else:
            rows[-1].append(idx)
            row_w += iw
    if len(rows) > 2 or any(sum(item_widths[i] for i in r) > max_row_width * 1.35 for r in rows):
        raise ChartLayoutError('chart legend does not fit the plot width (even across 2 rows)')
    return rows


def _place_annotation(cx, cy, width, height, note, plot, bounds, segments, obstacle_boxes):
    """Place an annotation near (cx, cy), avoiding series lines, bars and sibling labels."""
    px, py, pw, ph = plot
    bx, by, bw, bh = bounds
    explicit = 'dx' in note or 'dy' in note
    raw_dx = note.get('dx', 14)
    raw_dy = note.get('dy', -28)

    def clamp_box(dx, dy):
        tx = min(max(cx + dx, px + 4), bx + bw - width - 6)
        ty = min(max(cy + dy, py + 2), py + ph - height - 2)
        return [tx, ty, width, height]

    def penalty(box):
        score = 0.0
        for seg in segments:
            if _segment_hits_box(seg[0], seg[1], seg[2], seg[3], box, pad=2.5):
                score += 100.0
        for obs in obstacle_boxes:
            if _boxes_overlap(box, obs, pad=2.0):
                score += 80.0
        # Slight preference for staying close to the target point without touching it.
        mx, my = box[0] + box[2] / 2, box[1] + box[3] / 2
        dist = math.hypot(mx - cx, my - cy)
        if dist < 14:
            score += 40.0
        score += dist * 0.05
        return score

    initial = clamp_box(raw_dx, raw_dy)
    best_box = initial
    best_score = penalty(initial)
    if explicit and best_score < 50.0:
        return best_box

    candidates = [
        (raw_dx, raw_dy),
        (14, -32),
        (14, 16),
        (-width - 14, -32),
        (-width - 14, 16),
        (-width / 2, -36),
        (-width / 2, 18),
        (20, -14),
        (-width - 20, -14),
        (16, 28),
        (-width - 16, 28),
    ]
    for dx, dy in candidates:
        cand = clamp_box(dx, dy)
        sc = penalty(cand)
        if sc < best_score:
            best_score = sc
            best_box = cand
    return best_box


def _leader_endpoint(cx, cy, box):
    """Connect leader line to the nearest edge of the annotation text box."""
    tx, ty, tw, th = box
    ex = min(max(cx, tx), tx + tw)
    ey = min(max(cy, ty), ty + th)
    if tx < ex < tx + tw and ty < ey < ty + th:
        return (tx if cx < tx + tw / 2 else tx + tw), ty + th / 2
    return ex, ey


def _compile_hbar(chart, bbox, theme, face, legend_rows, widths):
    x, y, w, h = bbox
    accent = theme.get('accent', PALETTE[0])
    ink = theme.get('foreground', '#142735')
    muted = theme.get('muted', '#6B7A88')
    grid = theme.get('rule', '#D8DEE6')
    series = chart['series']
    cats = list(chart['x'].get('categories') or [_fmt(v) for v in (chart['x'].get('values') or [])])
    max_cat_w = max((face.getlength(str(c)) + 10 for c in cats), default=72.)
    left = max(MARGIN['left'], min(200., max_cat_w + 18.))
    right = MARGIN['right']
    top = 46. + (26. if len(legend_rows) == 2 else 0.)
    bottom = MARGIN['bottom']
    px, py, pw, ph = x + left, y + top, w - left - right, h - top - bottom
    if pw < 120 or ph < 80:
        raise ChartLayoutError('hbar chart body is too small for categories and bars')

    val_scale = chart['y'].get('scale', 'linear')
    bars = [entry.get('y_error') or [0.] * len(entry['values']) for entry in series]
    v_all = [val - err for entry, errs in zip(series, bars) for val, err in zip(entry['values'], errs)]
    v_all += [val + err for entry, errs in zip(series, bars) for val, err in zip(entry['values'], errs)]
    for rline in chart.get('reference_lines') or []:
        if rline.get('axis') == 'y':
            v_all.append(rline['value'])
    v_low, v_high = min(v_all), max(v_all)
    if val_scale == 'log':
        if v_low <= 0:
            raise ChartLayoutError('a log value axis needs strictly positive values')
        v_low, v_high = v_low / 1.25, v_high * 1.25
    else:
        v_low = min(0., v_low)
        v_high = max(0., v_high * 1.08 if v_high > 0 else 1.)
    if v_high <= v_low:
        v_high = v_low + 1.

    elements = []
    obstacle_boxes = []
    segments = []

    for z_idx, zone in enumerate(chart.get('shaded_zones') or []):
        if zone.get('axis') == 'y':
            zx1, zx2 = _positions([zone['low'], zone['high']], v_low, v_high, val_scale, px, pw)
            zl, zr = max(px, min(zx1, zx2)), min(px + pw, max(zx1, zx2))
            if zr > zl + 1:
                elements.append(_shape(f'chart:{chart["id"]}:zone:{z_idx}', [zl, py, zr - zl, ph], '#EEF4FA'))
                if zone.get('label'):
                    zw = min(face.getlength(zone['label']) + 10, zr - zl)
                    if zw >= 32:
                        zbox = [zl + 4, py + 4, zw, 26]
                        elements.append(_text(f'chart:{chart["id"]}:zone-label:{z_idx}', zone['label'], zbox, muted, SOURCE_SIZE))
                        obstacle_boxes.append(zbox)

    v_ticks = _log_ticks(v_low, v_high) if val_scale == 'log' else _linear_ticks(v_low, v_high, 4)
    v_pos = _positions(v_ticks, v_low, v_high, val_scale, px, pw)
    for index, (tick, tx) in enumerate(zip(v_ticks, v_pos)):
        label = _fmt(tick)
        lw = face.getlength(label) + 8
        elements.append(_shape(f'chart:{chart["id"]}:xtick:{index}', [tx - .5, py + ph, 1, 5], ink))
        lx = min(max(tx - lw / 2, x + 2), x + w - lw - 2)
        elements.append(_text(f'chart:{chart["id"]}:xlabel:{index}', label, [lx, py + ph + 6, lw, 28], muted, TICK_SIZE, 'center'))
        if index:
            elements.append(_shape(f'chart:{chart["id"]}:grid:{index}', [tx, py, 1, ph], grid))

    band = ph / max(1, len(cats))
    for index, cat in enumerate(cats):
        cy = py + (index + 0.5) * band
        lw = min(left - 14, face.getlength(str(cat)) + 10)
        elements.append(_text(f'chart:{chart["id"]}:ylabel:{index}', str(cat),
                              [px - lw - 8, cy - 14, lw, 28], ink, TICK_SIZE, 'right'))

    elements.append(_shape(f'chart:{chart["id"]}:axis-y', [px, py, 1, ph], ink))
    elements.append(_shape(f'chart:{chart["id"]}:axis-x', [px, py + ph, pw, 1], ink))

    bar_h = band * 0.62 / max(1, len(series))
    zero_x = _positions([v_low if val_scale == 'log' else 0.], v_low, v_high, val_scale, px, pw)[0]
    point_coords = {}
    for s_idx, entry in enumerate(series):
        color = PALETTE[s_idx % len(PALETTE)]
        end_xs = _positions(entry['values'], v_low, v_high, val_scale, px, pw)
        errs = entry.get('y_error')
        for p_idx, val in enumerate(entry['values']):
            cy = py + (p_idx + 0.5) * band + s_idx * bar_h - (len(series) - 1) * bar_h / 2
            ex = end_xs[p_idx]
            bx = min(zero_x, ex)
            bw_bar = max(1., abs(ex - zero_x))
            bar_box = [bx, cy - bar_h / 2, bw_bar, bar_h]
            elements.append(_shape(f'chart:{chart["id"]}:bar:{s_idx}:{p_idx}', bar_box, color))
            obstacle_boxes.append(bar_box)
            point_coords[(s_idx, p_idx)] = (ex, cy)
            if errs and errs[p_idx] > 0:
                lo_x, hi_x = _positions([val - errs[p_idx], val + errs[p_idx]], v_low, v_high, val_scale, px, pw)
                cmds = [('M', lo_x, cy), ('L', hi_x, cy), ('M', lo_x, cy - 4), ('L', lo_x, cy + 4), ('M', hi_x, cy - 4), ('L', hi_x, cy + 4)]
                elements.append(_geometry_shape(f'chart:{chart["id"]}:error:{s_idx}:{p_idx}', cmds, color))

    for r_idx, rline in enumerate(chart.get('reference_lines') or []):
        if rline.get('axis') == 'y':
            rx = _positions([rline['value']], v_low, v_high, val_scale, px, pw)[0]
            if px <= rx <= px + pw:
                el = (_dashed_line(f'chart:{chart["id"]}:ref:{r_idx}', rx, py, rx, py + ph, '#475569', 1.6)
                      if rline.get('style', 'dashed') == 'dashed'
                      else _shape(f'chart:{chart["id"]}:ref:{r_idx}', [rx - .75, py, 1.5, ph], '#475569'))
                elements.append(el)
                segments.append((rx, py, rx, py + ph))
                if rline.get('label'):
                    rw = face.getlength(rline['label']) + 10
                    rlx = min(max(rx + 4, px + 2), px + pw - rw - 2)
                    rbox = [rlx, py + 4, rw, 26]
                    elements.append(_text(f'chart:{chart["id"]}:ref-label:{r_idx}', rline['label'], rbox, '#475569', SOURCE_SIZE))
                    obstacle_boxes.append(rbox)

    for index, note in enumerate(chart.get('annotations') or []):
        cx, cy = point_coords[(note['series'], note['point'])]
        aw = min(max(face.getlength(note['text']) + 12, 60), pw * .55)
        abox = _place_annotation(cx, cy, aw, 28, note, (px, py, pw, ph), (x, y, w, h), segments, obstacle_boxes)
        obstacle_boxes.append(abox)
        elements.append({**_text(f'chart:{chart["id"]}:annotation:{index}', note['text'], abox, ink, TICK_SIZE, 'left'),
                         'node_id': f'annotation:{index}'})
        lx, ly = _leader_endpoint(cx, cy, abox)
        elements.append({**_geometry_shape(f'chart:{chart["id"]}:annotation-leader:{index}',
                                           [('M', cx, cy), ('L', lx, ly)], muted, 1.2),
                         'node_id': f'annotation:{index}'})

    val_label = chart['y']['label'] + (f' ({chart["y"]["unit"]})' if chart.get('y', {}).get('unit') else '')
    elements.append(_text(f'chart:{chart["id"]}:x-title', val_label, [px, y + h - 70, pw, 32], ink, LABEL_SIZE, 'center', role='body'))
    elements.append(_text(f'chart:{chart["id"]}:y-title', chart['x']['label'], [px, y + 2, pw * 0.48, 32], ink, LABEL_SIZE, 'left', role='body'))
    return elements, (px, py, pw, ph), (left, right, top, bottom)


def compile_chart(chart, bbox, theme, font_paths):
    """Native elements for one chart. Raises ``ChartLayoutError`` when it cannot be drawn."""
    x, y, w, h = bbox
    if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
        raise ChartLayoutError(f'chart needs at least {MIN_SIZE[0]:.0f}x{MIN_SIZE[1]:.0f} px, '
                               f'got {w:.0f}x{h:.0f}')
    accent = theme.get('accent', PALETTE[0])
    ink = theme.get('foreground', '#142735')
    muted = theme.get('muted', '#6B7A88')
    grid = theme.get('rule', '#D8DEE6')
    face = ImageFont.truetype(str(font_paths['font_file']), TICK_SIZE)

    series = chart['series']
    widths = [face.getlength(entry['label'])+8 for entry in series]
    prelim_pw = max(120., w - MARGIN['left'] - MARGIN['right'])
    legend_rows = _pack_legend_rows(series, widths, prelim_pw * 0.65)

    if chart['kind'] == 'hbar':
        elements, (px, py, pw, ph), (left, right, top, bottom) = _compile_hbar(
            chart, bbox, theme, face, legend_rows, widths
        )
    else:
        left, right = MARGIN['left'], MARGIN['right']
        top = MARGIN['top'] + (26. if len(legend_rows) == 2 else 0.)
        bottom = MARGIN['bottom']
        plot = (x+left, y+top, w-left-right, h-top-bottom)
        if plot[2] < 120 or plot[3] < 80:
            raise ChartLayoutError('chart body is too small for axes and a series')
        px, py, pw, ph = plot

        x_scale = chart['x'].get('scale', 'linear')
        y_scale = chart['y'].get('scale', 'linear')
        x_cats = list(chart['x'].get('categories') or [])
        shared_x = list(chart['x'].get('values') or ([float(i) for i in range(len(x_cats))] if x_cats else []))
        bars = [entry.get('y_error') or [0.]*len(entry['values']) for entry in series]
        y_values = [value-bar for entry, errors in zip(series, bars) for value, bar in zip(entry['values'], errors)]
        y_values += [value+bar for entry, errors in zip(series, bars) for value, bar in zip(entry['values'], errors)]
        for rline in chart.get('reference_lines') or []:
            if rline.get('axis') == 'y':
                y_values.append(rline['value'])
        y_low, y_high = min(y_values), max(y_values)
        if y_scale == 'log':
            if y_low <= 0:
                raise ChartLayoutError('a log y axis needs strictly positive values')
            y_low, y_high = y_low/1.25, y_high*1.25
        else:
            if chart['kind'] == 'bar':
                y_low = min(0., y_low)
                y_high = max(0., y_high)
            pad = (y_high-y_low)*.08
            if chart['kind'] in ('line', 'scatter'):
                y_low, y_high = y_low-pad, y_high+pad
            elif chart['kind'] == 'bar' and y_high > 0:
                y_high = y_high + pad
        if y_high <= y_low:
            y_high = y_low+1.
        if chart['kind'] == 'scatter':
            x_values = []
            all_x = [value for entry in series for value in (entry.get('x_values') or [])]
            x_low, x_high = min(all_x), max(all_x)
        else:
            x_values = shared_x
            x_low, x_high = (0., float(len(x_values)-1)) if chart['kind'] == 'bar' else (min(x_values), max(x_values))
        if x_high <= x_low:
            x_high = x_low+1.

        elements = []
        obstacle_boxes = []
        segments = []

        # Shaded operating zones (drawn behind grid and series).
        for z_idx, zone in enumerate(chart.get('shaded_zones') or []):
            if zone.get('axis') == 'x':
                zx1, zx2 = _positions([zone['low'], zone['high']], x_low, x_high, x_scale, px, pw)
                zl, zr = max(px, min(zx1, zx2)), min(px + pw, max(zx1, zx2))
                if zr > zl + 1:
                    elements.append(_shape(f'chart:{chart["id"]}:zone:{z_idx}', [zl, py, zr - zl, ph], '#EEF4FA'))
                    if zone.get('label'):
                        zw = min(face.getlength(zone['label']) + 10, zr - zl)
                        if zw >= 32:
                            zbox = [zl + 4, py + 4, zw, 26]
                            elements.append(_text(f'chart:{chart["id"]}:zone-label:{z_idx}', zone['label'], zbox, muted, SOURCE_SIZE))
                            obstacle_boxes.append(zbox)
            else:
                zy1, zy2 = _positions([zone['low'], zone['high']], y_low, y_high, y_scale, py + ph, -ph)
                zt, zb = max(py, min(zy1, zy2)), min(py + ph, max(zy1, zy2))
                if zb > zt + 1:
                    elements.append(_shape(f'chart:{chart["id"]}:zone:{z_idx}', [px, zt, pw, zb - zt], '#EEF4FA'))
                    if zone.get('label'):
                        zw = min(face.getlength(zone['label']) + 10, pw - 8)
                        zbox = [px + 6, zt + 2, zw, 26]
                        elements.append(_text(f'chart:{chart["id"]}:zone-label:{z_idx}', zone['label'], zbox, muted, SOURCE_SIZE))
                        obstacle_boxes.append(zbox)

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
            band = pw / max(1, len(x_values))
            x_positions = [px + (index + 0.5) * band for index in range(len(x_values))]
        elif x_scale == 'log':
            x_ticks = _log_ticks(x_low, x_high)
            x_positions = _positions(x_ticks, x_low, x_high, x_scale, px, pw)
        else:
            x_ticks = _linear_ticks(x_low, x_high, 5)
            x_positions = _positions(x_ticks, x_low, x_high, x_scale, px, pw)
        for index, (tick, tx) in enumerate(zip(x_ticks, x_positions)):
            if chart['kind'] == 'bar':
                label = x_cats[index] if x_cats else _fmt(x_values[index])
            else:
                label = _fmt(tick)
            width = face.getlength(str(label))+8
            elements.append(_shape(f'chart:{chart["id"]}:xtick:{index}', [tx-.5, py+ph, 1, 5], ink))
            label_x = min(max(tx-width/2, x+2), x+w-width-2)
            elements.append(_text(f'chart:{chart["id"]}:xlabel:{index}', str(label),
                                  [label_x, py+ph+6, width, 28], muted, TICK_SIZE, 'center'))

        # Reference lines (thresholds / baselines).
        for r_idx, rline in enumerate(chart.get('reference_lines') or []):
            dashed = rline.get('style', 'dashed') == 'dashed'
            if rline.get('axis') == 'y':
                ry = _positions([rline['value']], y_low, y_high, y_scale, py + ph, -ph)[0]
                if py <= ry <= py + ph:
                    el = (_dashed_line(f'chart:{chart["id"]}:ref:{r_idx}', px, ry, px + pw, ry, '#475569', 1.6)
                          if dashed else _shape(f'chart:{chart["id"]}:ref:{r_idx}', [px, ry - .75, pw, 1.5], '#475569'))
                    elements.append(el)
                    segments.append((px, ry, px + pw, ry))
                    if rline.get('label'):
                        rw = face.getlength(rline['label']) + 10
                        rbox = [px + pw - rw - 4, max(py + 2, ry - 26), rw, 24]
                        elements.append(_text(f'chart:{chart["id"]}:ref-label:{r_idx}', rline['label'], rbox, '#475569', SOURCE_SIZE, 'right'))
                        obstacle_boxes.append(rbox)
            else:
                rx = _positions([rline['value']], x_low, x_high, x_scale, px, pw)[0]
                if px <= rx <= px + pw:
                    el = (_dashed_line(f'chart:{chart["id"]}:ref:{r_idx}', rx, py, rx, py + ph, '#475569', 1.6)
                          if dashed else _shape(f'chart:{chart["id"]}:ref:{r_idx}', [rx - .75, py, 1.5, ph], '#475569'))
                    elements.append(el)
                    segments.append((rx, py, rx, py + ph))
                    if rline.get('label'):
                        rw = face.getlength(rline['label']) + 10
                        rbox = [min(rx + 4, px + pw - rw - 2), py + 4, rw, 24]
                        elements.append(_text(f'chart:{chart["id"]}:ref-label:{r_idx}', rline['label'], rbox, '#475569', SOURCE_SIZE))
                        obstacle_boxes.append(rbox)

        # Series.
        point_coords = {}
        for series_index, entry in enumerate(series):
            color = PALETTE[series_index % len(PALETTE)]
            xs = _positions(entry.get('x_values') or x_values, x_low, x_high, x_scale, px, pw)
            points = _positions(entry['values'], y_low, y_high, y_scale, py+ph, -ph)
            if chart['kind'] == 'bar':
                band = pw/len(x_values)
                width = band*.6/max(1, len(series))
                zero = _positions([y_low if y_scale == 'log' else 0.], y_low, y_high, y_scale, py+ph, -ph)[0]
                centres = []
                for point, value in enumerate(entry['values']):
                    centre = px+(point+.5)*band+series_index*width-(len(series)-1)*width/2
                    centres.append(centre)
                    top_y = points[point]
                    bar_box = [centre-width/2, min(top_y, zero), width, abs(zero-top_y)]
                    elements.append(_shape(f'chart:{chart["id"]}:bar:{series_index}:{point}', bar_box, color))
                    obstacle_boxes.append(bar_box)
                    point_coords[(series_index, point)] = (centre, top_y)
                mark_x = centres
            else:
                mark_x = xs
                if chart['kind'] == 'line':
                    elements.append(_polyline(f'chart:{chart["id"]}:line:{series_index}', xs, points, color))
                    for (x1, y1), (x2, y2) in zip(zip(xs, points), zip(xs[1:], points[1:])):
                        segments.append((x1, y1, x2, y2))
                for point, (cx, cy) in enumerate(zip(xs, points)):
                    dot_box = [cx-3, cy-3, 6, 6]
                    elements.append(_shape(f'chart:{chart["id"]}:dot:{series_index}:{point}', dot_box, color, 'ellipse'))
                    obstacle_boxes.append([cx-5, cy-5, 10, 10])
                    point_coords[(series_index, point)] = (cx, cy)
            errors = entry.get('y_error')
            if errors:
                for point, (cx, value, bar) in enumerate(zip(mark_x, entry['values'], errors)):
                    if bar <= 0:
                        continue
                    low = _positions([value-bar], y_low, y_high, y_scale, py+ph, -ph)[0]
                    high = _positions([value+bar], y_low, y_high, y_scale, py+ph, -ph)[0]
                    commands = [('M', cx, low), ('L', cx, high),
                                ('M', cx-4, low), ('L', cx+4, low),
                                ('M', cx-4, high), ('L', cx+4, high)]
                    elements.append(_geometry_shape(
                        f'chart:{chart["id"]}:error:{series_index}:{point}', commands, color))
                    segments.append((cx, low, cx, high))

        # In-plot annotations: auto-avoid plotted lines, bars and sibling annotations.
        for index, note in enumerate(chart.get('annotations') or []):
            cx, cy = point_coords[(note['series'], note['point'])]
            width = min(max(face.getlength(note['text'])+12, 60), pw*.55)
            abox = _place_annotation(cx, cy, width, 28, note, (px, py, pw, ph), (x, y, w, h), segments, obstacle_boxes)
            obstacle_boxes.append(abox)
            elements.append({**_text(f'chart:{chart["id"]}:annotation:{index}', note['text'],
                                     abox, ink, TICK_SIZE, 'left'),
                             'node_id': f'annotation:{index}'})
            edge_x, edge_y = _leader_endpoint(cx, cy, abox)
            elements.append({**_geometry_shape(f'chart:{chart["id"]}:annotation-leader:{index}',
                                               [('M', cx, cy), ('L', edge_x, edge_y)], muted, 1.2),
                             'node_id': f'annotation:{index}'})

        # Axis titles.
        elements.append(_text(f'chart:{chart["id"]}:x-title', chart['x']['label'],
                              [px, y+h-70, pw, 32], ink, LABEL_SIZE, 'center', role='body'))
        y_label = chart['y']['label'] + (f' ({chart["y"]["unit"]})' if chart.get('y', {}).get('unit') else '')
        elements.append(_text(f'chart:{chart["id"]}:y-title', y_label,
                              [px, y+2, pw, 32], ink, LABEL_SIZE, 'left', role='body'))

    # Legend: 1 or 2 right-aligned rows above the plot.
    legend = []
    for row_idx, row_items in enumerate(legend_rows):
        row_total = sum(widths[i] + 22 for i in row_items)
        cursor = px + pw - row_total
        ry = y + 2 + row_idx * 26
        for series_index in row_items:
            entry = series[series_index]
            color = PALETTE[series_index % len(PALETTE)]
            legend.append(_shape(f'chart:{chart["id"]}:swatch:{series_index}', [cursor, ry + 8, 10, 10], color))
            legend.append(_text(f'chart:{chart["id"]}:legend:{series_index}', entry['label'],
                                [cursor+16, ry, widths[series_index], 28], ink, TICK_SIZE, 'left'))
            cursor += widths[series_index]+22
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
