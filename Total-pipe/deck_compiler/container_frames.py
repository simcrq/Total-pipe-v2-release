"""Measured native frames inside the existing compiler, with explicit child membership."""
import math
import re

PADDING = {'none': 0., 'compact': 12., 'standard': 20.}
COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')


def validate_frame(value, panel=False):
    allowed = {'border', 'fill'} | ({'title_fill', 'title_color', 'title_align'} if panel else {'padding'})
    if not isinstance(value, dict):
        return ['frame must be an object']
    errors = []
    if set(value)-allowed:
        errors.append('unknown frame fields; geometry belongs to the compiler')
    border = value.get('border')
    if not isinstance(border, dict) or set(border)-{'color', 'width'}:
        errors.append('frame.border requires color and optional width')
    else:
        if not isinstance(border.get('color'), str) or not COLOR.fullmatch(border['color']):
            errors.append('frame.border.color must be #RRGGBB')
        width = border.get('width', 1.)
        if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or not .5 <= width <= 6:
            errors.append('frame.border.width must be finite in [0.5,6] CSS px')
    for key in ('fill', 'title_fill', 'title_color'):
        if key not in value:
            continue
        color = value[key]
        if not isinstance(color, str) or not (COLOR.fullmatch(color) or (key != 'title_color' and color == 'none')):
            errors.append(f'frame.{key} must be #RRGGBB'+(' or none' if key != 'title_color' else ''))
    if 'title_align' in value and value['title_align'] not in ('left', 'center'):
        errors.append('frame.title_align must be left or center')
    if 'padding' in value and (not isinstance(value['padding'], str) or value['padding'] not in PADDING):
        errors.append('frame.padding must be none, compact or standard')
    return errors


def stroke_width(style):
    return float(style['border'].get('width', 1.))


def rectangle(element_id, outer, style, members):
    """Inset the centreline so the complete stroke stays inside the allocated outer box."""
    x, y, w, h = outer
    stroke = stroke_width(style)
    return {'id': element_id, 'kind': 'shape', 'role': 'decoration',
            'bbox': [x+stroke/2, y+stroke/2, w-stroke, h-stroke],
            'geometry': 'rect', 'fill': style.get('fill', 'none'),
            'line': style['border']['color'], 'line_width': stroke,
            'visual_decoration': True, 'frame_members': list(members), 'container_frame': True}


def panel_metrics(node):
    style = node.get('frame')
    pad = PADDING[node.get('padding', 'compact' if style else 'none')]
    stroke = stroke_width(style) if style else 0.
    # A framed title band has padding above and below its title; body also has bottom padding.
    return pad, stroke, (3 if style else 2)*pad+2*stroke


def legacy_takeaway_box(slide, frame):
    if frame == 'template':
        return [88, 84, 1104, 42]
    return [56, 144 if frame == 'spacious' else 164, 1168,
            56 if slide['id'] in ('s05-anneal', 's07-contact') else 76]


def measure_takeaway(slide, fonts, slot, marker=None):
    """Reserve a frame for complete takeaway prose/math at the existing 18 pt text floor."""
    from .fonts import bullet_metrics, load_font_file
    from .layout import break_lines
    style = slide['presentation']['takeaway_frame']
    pad = PADDING[style.get('padding', 'compact')]
    inset = pad+stroke_width(style)
    x, y, w, _ = slot
    font = load_font_file(fonts['font_file'], 24)
    setting = slide['presentation'].get('takeaway_marker')
    if marker is None and setting:
        marker = bullet_metrics(setting['style'], font.getname()[0], fonts['font_file'], 28)
    width = w-2*inset-(marker['gutter'] if marker else 0)
    line_height = max(30., marker['line_height_px'] if marker else 30.)
    content = slide['semantic']['takeaway']
    lines = len(break_lines(content, font, max(1., width)))
    height = lines*line_height
    if 'takeaway' in slide['semantic'].get('inline_math', []):
        from totalpipe_layout.inline_math import measure_inline, InlineWidthError
        try:
            measured = measure_inline(content, width, font, 24, leading_marker=marker)
            height, lines = measured['height'], len(measured['lines'])
        except InlineWidthError:
            pass  # The final text emitter reports a precise formula width failure.
    return {'bbox': [x, y, w, height+2*inset],
            'text_bbox': [x+inset, y+inset, w-2*inset, height],
            'lines': max(1, lines), 'padding_px': pad, 'style': style,
            'measurement': 'complete_text_at_font_floor'}


def grow_frame(frame, outer, members, inset=0.):
    """Preserved scientific text may grow a frame; subsequent page checks still see collisions."""
    x, y, w, h = outer
    right, bottom = x+w, y+h
    for element in members:
        ex, ey, ew, eh = element['bbox']
        spacing = element.get('frame_growth_inset', inset)
        edge = element.get('line_width', 0)/2 if element.get('container_frame') else 0
        right = max(right, ex+ew+edge+spacing)
        bottom = max(bottom, ey+eh+edge+spacing)
    grown = [x, y, right-x, bottom-y]
    if grown[2] > w+.1 or grown[3] > h+.1:
        stroke = frame['line_width']
        frame['bbox'] = [x+stroke/2, y+stroke/2, grown[2]-stroke, grown[3]-stroke]
        frame['scientific_text_overflow'] = {'original_bbox': list(outer), 'policy': 'preserve-terms'}
    else:
        grown = list(outer)
    return grown


def containment_errors(elements):
    """Only declared descendants may overlap a frame; their boxes must stay inside its stroke."""
    by_id = {e['id']: e for e in elements}
    errors = []
    for frame in elements:
        if not frame.get('container_frame'):
            continue
        x, y, w, h = frame['bbox']
        half = frame['line_width']/2
        for member_id in frame['frame_members']:
            member = by_id.get(member_id)
            if member is None:
                errors.append((frame['id'], f'Missing framed content {member_id}'))
                continue
            mx, my, mw, mh = member['bbox']
            # Nested native frames have a centred stroke of their own.
            edge = member.get('line_width', 0)/2 if member.get('container_frame') else 0
            if mx-edge < x+half-.2 or my-edge < y+half-.2 or mx+mw+edge > x+w-half+.2 or my+mh+edge > y+h-half+.2:
                errors.append((frame['id'], f'Framed content {member_id} exceeds the inner border'))
    return errors
