"""Small SVG -> native PageScene importer.

This intentionally supports the presentation-oriented SVG subset that models
write well: text, rect, circle, line, path, polygon/polyline, simple styles and
marker-end arrows.  Geometry stays in the SVG viewBox; PageScene receives native
shapes and text, never a raster image.
"""
from __future__ import annotations

import math
import re
from xml.etree import ElementTree as ET

NUMBER = r'-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
TOKEN = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|' + NUMBER)
STYLE = re.compile(r'([.#]?[A-Za-z][\w-]*)\s*\{([^}]*)\}')


def _number(value, default=0.0):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _style_map(source):
    result = {}
    for name, body in STYLE.findall(source or ''):
        props = {}
        for item in body.split(';'):
            if ':' in item:
                key, value = item.split(':', 1)
                props[key.strip()] = value.strip()
        result[name] = props
    return result


def _class_style(element, styles):
    result = {}
    for name in (element.get('class') or '').split():
        result.update(styles.get('.'+name, {}))
    return result


def _fill(element, styles):
    value = element.get('fill') or _class_style(element, styles).get('fill') or 'none'
    return value


def _stroke(element, styles):
    return element.get('stroke') or _class_style(element, styles).get('stroke') or 'none'


def _width(element, styles):
    value = element.get('stroke-width') or _class_style(element, styles).get('stroke-width') or '1'
    return _number(value, 1.0)


def _tokens(source):
    return TOKEN.findall(source or '')


def _arc_points(x0, y0, rx, ry, rotation, large, sweep, x1, y1, steps=12):
    """Flatten one SVG elliptical arc into line points (editable approximation)."""
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [(x1, y1)]
    phi = math.radians(rotation)
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    c, s = math.cos(phi), math.sin(phi)
    x1p, y1p = c*dx + s*dy, -s*dx + c*dy
    lam = (x1p*x1p)/(rx*rx) + (y1p*y1p)/(ry*ry)
    if lam > 1:
        rx, ry = rx*math.sqrt(lam), ry*math.sqrt(lam)
    sign = -1 if large == sweep else 1
    numerator = max(0.0, (rx*rx*ry*ry - rx*rx*y1p*y1p - ry*ry*x1p*x1p) /
                    max(1e-12, rx*rx*y1p*y1p + ry*ry*x1p*x1p))
    coef = sign*math.sqrt(numerator)
    cxp, cyp = coef*rx*y1p/ry, -coef*ry*x1p/rx
    cx = c*cxp - s*cyp + (x0 + x1)/2
    cy = s*cxp + c*cyp + (y0 + y1)/2
    def angle(ux, uy, vx, vy):
        return math.atan2(ux*vy - uy*vx, ux*vx + uy*vy)
    theta = angle(1, 0, (x1p-cxp)/rx, (y1p-cyp)/ry)
    delta = angle((x1p-cxp)/rx, (y1p-cyp)/ry, (-x1p-cxp)/rx, (-y1p-cyp)/ry)
    if not sweep and delta > 0:
        delta -= 2*math.pi
    elif sweep and delta < 0:
        delta += 2*math.pi
    points = []
    for i in range(1, steps+1):
        t = theta + delta*i/steps
        points.append((cx + rx*math.cos(t)*c - ry*math.sin(t)*s,
                       cy + rx*math.cos(t)*s + ry*math.sin(t)*c))
    return points


def parse_path(source):
    """Convert SVG path data to absolute PageScene M/L/C/Q/Z commands."""
    tokens = _tokens(source)
    out, index = [], 0
    cx = cy = sx = sy = 0.0
    command = None
    last_cubic = last_quad = None
    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in 'Zz':
                out.append(['Z'])
                cx, cy = sx, sy
                continue
        if command is None:
            raise ValueError('SVG path data must start with a command')
        relative = command.islower()
        kind = command.upper()

        def take(count):
            nonlocal index
            values = [float(tokens[index+i]) for i in range(count)]
            index += count
            return values
        if kind in ('M', 'L'):
            x, y = take(2)
            if relative:
                x, y = cx+x, cy+y
            out.append([kind, x, y])
            if kind == 'M':
                sx, sy = x, y
                command = 'l' if relative else 'L'
            cx, cy = x, y
            last_cubic = last_quad = None
        elif kind == 'H':
            x = take(1)[0] + (cx if relative else 0)
            out.append(['L', x, cy]); cx = x
        elif kind == 'V':
            y = take(1)[0] + (cy if relative else 0)
            out.append(['L', cx, y]); cy = y
        elif kind == 'C':
            x1, y1, x2, y2, x, y = take(6)
            if relative:
                x1, y1, x2, y2, x, y = cx+x1, cy+y1, cx+x2, cy+y2, cx+x, cy+y
            out.append(['C', x1, y1, x2, y2, x, y])
            last_cubic = (x2, y2); cx, cy = x, y
        elif kind == 'S':
            x2, y2, x, y = take(4)
            if relative:
                x2, y2, x, y = cx+x2, cy+y2, cx+x, cy+y
            x1, y1 = (2*cx-last_cubic[0], 2*cy-last_cubic[1]) if last_cubic else (cx, cy)
            out.append(['C', x1, y1, x2, y2, x, y])
            last_cubic = (x2, y2); cx, cy = x, y
        elif kind == 'Q':
            x1, y1, x, y = take(4)
            if relative:
                x1, y1, x, y = cx+x1, cy+y1, cx+x, cy+y
            out.append(['Q', x1, y1, x, y])
            last_quad = (x1, y1); cx, cy = x, y
        elif kind == 'T':
            x, y = take(2)
            if relative:
                x, y = cx+x, cy+y
            x1, y1 = (2*cx-last_quad[0], 2*cy-last_quad[1]) if last_quad else (cx, cy)
            out.append(['Q', x1, y1, x, y])
            last_quad = (x1, y1); cx, cy = x, y
        elif kind == 'A':
            rx, ry, rotation, large, sweep, x, y = take(7)
            if relative:
                x, y = cx+x, cy+y
            for px, py in _arc_points(cx, cy, rx, ry, rotation, int(large), int(sweep), x, y):
                out.append(['L', px, py])
            cx, cy = x, y
        else:
            raise ValueError('unsupported SVG path command %s' % command)
    return out


def _text_width(text, font):
    units = 0.0
    for char in text:
        units += font * (0.82 if ord(char) < 128 else 1.0)
    return max(font*3.5, units)


def _objects(root, box, styles, prefix):
    vx, vy, vw, vh = (float(v) for v in (root.get('viewBox') or '0 0 1000 600').replace(',', ' ').split())
    sx, sy = box[2]/vw, box[3]/vh
    objects = []

    def point(x, y):
        return box[0] + (float(x)-vx)*sx, box[1] + (float(y)-vy)*sy

    def emit_path(oid, commands, fill, stroke, width, dash=False):
        if not commands:
            return
        objects.append({'id': oid, 'type': 'path', 'box': list(box),
                        'view_box': [vx, vy, vw, vh], 'commands': commands,
                        'fill': fill or 'none', 'stroke': stroke or 'none',
                        'stroke_width': max(.5, width*sx*72),
                        'dash': bool(dash)})

    def arrowhead(oid, commands, color, width):
        if not commands:
            return
        last = commands[-1]
        if last[0] not in ('L', 'C', 'Q'):
            return
        x2, y2 = last[-2], last[-1]
        prev = commands[-2] if len(commands) > 1 else None
        if prev is None:
            return
        x1, y1 = prev[-2], prev[-1]
        angle = math.atan2(y2-y1, x2-x1)
        length = 9.0
        left = [x2-length*math.cos(angle-.45), y2-length*math.sin(angle-.45)]
        right = [x2-length*math.cos(angle+.45), y2-length*math.sin(angle+.45)]
        emit_path(oid, [['M', *left], ['L', x2, y2], ['L', *right]], 'none', color, width)

    for element in list(root):
        tag = element.tag.rsplit('}', 1)[-1]
        if tag in ('defs', 'title', 'desc', 'style'):
            continue
        style = _class_style(element, styles)
        fill = _fill(element, styles)
        stroke = _stroke(element, styles)
        width = _width(element, styles)
        if tag == 'rect':
            x, y = point(element.get('x', 0), element.get('y', 0))
            w, h = _number(element.get('width'))*sx, _number(element.get('height'))*sy
            objects.append({'id': '%s_rect_%d' % (prefix, len(objects)), 'type': 'shape',
                            'shape': 'rounded' if _number(element.get('rx')) else 'rect',
                            'box': [x, y, w, h], 'fill': fill, 'stroke': stroke,
                            'stroke_width': max(.5, width*sx*72)})
        elif tag == 'circle':
            x, y = point(element.get('cx', 0), element.get('cy', 0))
            r = _number(element.get('r'))*sx
            objects.append({'id': '%s_circle_%d' % (prefix, len(objects)), 'type': 'shape',
                            'shape': 'oval', 'box': [x-r, y-r, 2*r, 2*r], 'fill': fill,
                            'stroke': stroke, 'stroke_width': max(.5, width*sx*72)})
        elif tag in ('path', 'polygon', 'polyline'):
            if tag == 'path':
                commands = parse_path(element.get('d'))
            else:
                values = [float(v) for v in re.findall(NUMBER, element.get('points') or '')]
                commands = [['M' if i == 0 else 'L', values[i], values[i+1]]
                            for i in range(0, len(values)-1, 2)]
                if tag == 'polygon':
                    commands.append(['Z'])
            emit_path('%s_path_%d' % (prefix, len(objects)), commands, fill, stroke, width,
                      bool(element.get('stroke-dasharray')))
            if element.get('marker-end') and stroke != 'none':
                arrowhead('%s_arrow_%d' % (prefix, len(objects)), commands, stroke, width)
        elif tag == 'line':
            x1, y1 = point(element.get('x1', 0), element.get('y1', 0))
            x2, y2 = point(element.get('x2', 0), element.get('y2', 0))
            objects.append({'id': '%s_line_%d' % (prefix, len(objects)), 'type': 'line',
                            'box': [x1, y1, x2, y2], 'stroke': stroke,
                            'stroke_width': max(.5, width*sx*72)})
        elif tag == 'text':
            value = ''.join(element.itertext()).strip()
            if not value:
                continue
            font = _number(style.get('font-size', element.get('font-size', '12')).replace('px', ''), 12)
            anchor = element.get('text-anchor', 'start')
            width_units = _text_width(value, font)
            x, y = point(element.get('x', 0), element.get('y', 0))
            top = y - font*0.82*sy
            box_w = width_units*sx
            if anchor == 'middle':
                box_x, align = x - box_w/2, 'center'
            elif anchor == 'end':
                box_x, align = x - box_w, 'right'
            else:
                box_x, align = x, 'left'
            role = 'caption' if str(style.get('font-size', element.get('font-size', ''))).startswith('11') else 'label'
            size = max(8.5, font*sy*72)
            objects.append({'id': '%s_text_%d' % (prefix, len(objects)), 'type': 'text',
                            'box': [box_x, top, box_w, font*1.35*sy], 'role': role,
                            'text': value, 'size': size, 'align': align, 'valign': 'top',
                            'color': fill if fill != 'none' else '#102A43',
                            'line_spacing': 1.0})
    return objects


def svg_to_objects(source, box, prefix='svg'):
    root = ET.fromstring(source)
    if root.tag.rsplit('}', 1)[-1] != 'svg':
        raise ValueError('SVG document must have an svg root')
    styles = _style_map(''.join(part.text or '' for part in root.iter()
                                if part.tag.rsplit('}', 1)[-1] == 'style'))
    return _objects(root, box, styles, prefix)
