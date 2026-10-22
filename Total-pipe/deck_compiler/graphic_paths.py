"""A bounded absolute Path IR -> native DrawingML compiler; this is not SVG import."""
import math
import re
import xml.etree.ElementTree as ET

from .graphic_layout import GraphicLayoutError

A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
ARITY = {'M': 2, 'L': 2, 'C': 6, 'Q': 4, 'Z': 0}
TOKEN = re.compile(r'[MLCQZ]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?')
CANVAS = 100000


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1e9 or not math.isfinite(value):
        raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Path coordinates must be finite numbers within +/-1e9')
    return float(value)


def parse_path(value):
    """Accept commands [[op, ...numbers], ...] or an uppercase M/L/C/Q/Z string."""
    if isinstance(value, str):
        if len(value) > 32000:
            raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Path string exceeds 32000 characters')
        tokens, cursor = [], 0
        for match in TOKEN.finditer(value):
            if value[cursor:match.start()].strip(' ,\t\r\n'):
                raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Only absolute M/L/C/Q/Z path commands are supported')
            tokens.append(match.group())
            cursor = match.end()
        if value[cursor:].strip(' ,\t\r\n'):
            raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Unrecognized path input')
        commands, index, operation = [], 0, None
        while index < len(tokens):
            if tokens[index] in ARITY:
                operation = tokens[index]
                index += 1
                if operation == 'Z':
                    commands.append(['Z'])
                    operation = None
                    continue
            if operation is None or index+ARITY[operation] > len(tokens):
                raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Missing path command or coordinates')
            values = tokens[index:index+ARITY[operation]]
            if any(v in ARITY for v in values):
                raise GraphicLayoutError('GRAPHIC_PATH_INVALID', f'{operation} has an incomplete coordinate list')
            commands.append([operation, *[float(v) for v in values]])
            index += ARITY[operation]
            if operation == 'M':
                operation = 'L'
        value = commands
    if not isinstance(value, list) or not 2 <= len(value) <= 512:
        raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'A path requires 2-512 commands')
    result, current, start, drawn = [], None, None, False
    for command in value:
        if (not isinstance(command, (list, tuple)) or not command or not isinstance(command[0], str)
                or command[0] not in ARITY or len(command) != ARITY[command[0]]+1):
            raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Use M/L/C/Q/Z commands with exact coordinate counts')
        op = command[0]
        values = [number(v) for v in command[1:]]
        if op != 'M' and current is None:
            raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Each subpath must start with M')
        if op == 'M':
            current = start = values
        elif op == 'Z':
            current = start
        elif op == 'Q':
            qx, qy, ex, ey = values
            values = [current[0]+2*(qx-current[0])/3, current[1]+2*(qy-current[1])/3,
                      ex+2*(qx-ex)/3, ey+2*(qy-ey)/3, ex, ey]
            op = 'C'
            current, drawn = values[-2:], True
        else:
            current, drawn = values[-2:], True
        result.append([op, *values])
    if not drawn:
        raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'A path must draw at least one segment')
    return result


def _cubic(p0, p1, p2, p3, t):
    return (1-t)**3*p0+3*(1-t)**2*t*p1+3*(1-t)*t*t*p2+t**3*p3


def _extrema(p0, p1, p2, p3):
    a, b, c = 3*(-p0+3*p1-3*p2+p3), 6*(p0-2*p1+p2), 3*(p1-p0)
    if abs(a) < 1e-10:
        return [-c/b] if abs(b) >= 1e-10 else []
    disc = b*b-4*a*c
    if disc < 0:
        return []
    root = math.sqrt(disc)
    return [(-b-root)/(2*a), (-b+root)/(2*a)]


def path_bounds(commands):
    """Exact cubic extrema rather than control-point boxes or sampled curves."""
    points, current, start = [], None, None
    for command in commands:
        op, values = command[0], command[1:]
        if op == 'M':
            current = start = values
        elif op == 'Z':
            points.extend([current, start])
            current = start
        else:
            end = values[-2:]
            points.extend([current, end])
            if op == 'C':
                for axis in (0, 1):
                    controls = [current[axis], values[axis], values[axis+2], end[axis]]
                    for t in _extrema(*controls):
                        if 0 < t < 1:
                            points.append([_cubic(current[j], values[j], values[j+2], end[j], t) for j in (0, 1)])
            current = end
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return [min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)]


def custom_geometry(commands, box):
    """Normalize to a stable local coordinate system inside a shape's own bbox."""
    x, y, w, h = box
    if min(w, h) <= 0:
        raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Native path geometry requires a positive local bbox')
    parts = [f'<a:custGeom xmlns:a="{A_NS}"><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>',
             '<a:rect l="0" t="0" r="w" b="h"/><a:pathLst>',
             f'<a:path w="{CANVAS}" h="{CANVAS}" fill="norm" stroke="1" extrusionOk="0">']
    for op, *values in commands:
        if op == 'Z':
            parts.append('<a:close/>')
            continue
        tag = {'M': 'moveTo', 'L': 'lnTo', 'C': 'cubicBezTo'}[op]
        parts.append(f'<a:{tag}>')
        for index in range(0, len(values), 2):
            nx, ny = (values[index]-x)/w*CANVAS, (values[index+1]-y)/h*CANVAS
            if not math.isfinite(nx) or not math.isfinite(ny):
                raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Path normalization exceeds finite coordinate capacity')
            px, py = round(nx), round(ny)
            if max(abs(px), abs(py)) > 2**31-1:
                raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'Normalized control points exceed DrawingML integer range')
            parts.append(f'<a:pt x="{px}" y="{py}"/>')
        parts.append(f'</a:{tag}>')
    parts.append('</a:path></a:pathLst></a:custGeom>')
    return ''.join(parts)


def geometry_signature(value):
    """Compare actual and planned native geometry independent of XML prefix formatting."""
    root = ET.fromstring(value) if isinstance(value, str) else value
    return (root.tag, tuple(sorted(root.attrib.items())),
            tuple(geometry_signature(child) for child in root))


def path_spec_commands(spec):
    if ('commands' in spec) == ('d' in spec):
        raise GraphicLayoutError('GRAPHIC_PATH_INVALID', 'A path requires exactly one of commands or d')
    return parse_path(spec.get('commands', spec.get('d')))


def render_paths(data, theme, bounds):
    vx, vy, vw, vh = data['view_box']
    x, y, w, h = bounds
    pad = 4.0
    scale = min((w-2*pad)/vw, (h-2*pad)/vh)
    if not math.isfinite(scale) or scale <= 0:
        raise GraphicLayoutError('GRAPHIC_CAPACITY', 'Path component has no drawable area')
    left, top = x+(w-vw*scale)/2, y+(h-vh*scale)/2
    elements = []
    palette = {'accent': theme.get('accent', '#C2410C'),
               'foreground': theme.get('foreground', '#142735'),
               'background': theme.get('background', '#FFFFFF'), 'none': 'none'}
    for spec in data['paths']:
        commands = path_spec_commands(spec)
        px, py, pw, ph = path_bounds(commands)
        # Zero-height/width open paths still get an editable positive shape extent.
        if pw == 0:
            px, pw = px-.5/scale, 1/scale
        if ph == 0:
            py, ph = py-.5/scale, 1/scale
        fill, stroke = spec.get('fill', 'none'), spec.get('stroke', 'accent')
        elements.append({'id': f"graphic:{data['id']}:path:{spec['id']}", 'kind': 'shape',
            'role': 'graphic-path', 'graphic_id': data['id'], 'node_id': spec['id'],
            'overlap_group': f"path:{data['id']}",
            'bbox': [left+(px-vx)*scale, top+(py-vy)*scale, pw*scale, ph*scale],
            'custom_geometry': custom_geometry(commands, [px, py, pw, ph]),
            'fill': palette.get(fill, fill), 'line': palette.get(stroke, stroke),
            'line_width': spec.get('line_width', 2)})
    for label in data.get('labels', []):
        lx, ly, lw, lh = label['box']
        elements.append({'id': f"graphic:{data['id']}:label:{label['id']}", 'kind': 'text',
            'role': 'body', 'graphic_id': data['id'], 'node_id': 'label:'+label['id'],
            'overlap_group': f"path:{data['id']}", 'text': label['text'],
            'bbox': [left+(lx-vx)*scale, top+(ly-vy)*scale, lw*scale, lh*scale],
            'font_size': 28, 'max_lines': 6, 'color': palette['foreground']})
    return elements
