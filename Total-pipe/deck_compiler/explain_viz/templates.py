"""Versioned deterministic templates lowered only to existing Path IR and text."""
import colorsys
import math
import re

from ..background import contrast_ratio, relative_luminance
from ..contracts import digest
from ..style import tint
from .specs import PREFIX, TEMPLATES

VIEW = [0, 0, 1000, 600]


def _fill(color, theme):
    """Keep categorical washes readable with the existing foreground, including dark decks."""
    background = theme.get('background', '#FFFFFF')
    luminance = lambda value: relative_luminance(tuple(int(value[i:i+2], 16) for i in (1, 3, 5)))
    foreground = luminance(theme.get('foreground', '#142735'))
    minimum = min(4.5, contrast_ratio(foreground, luminance(background)))
    for strength in (.24, .16, .08, 0):
        fill = tint(color, background, 1-strength)
        if contrast_ratio(foreground, luminance(fill)) >= minimum:
            return fill
    return background


def build(spec, theme=None):
    theme = theme or {}
    prefix = PREFIX+digest(spec)[:12]+'_'
    paths, labels = [], []
    monochrome = theme.get('_explain_viz_monochrome', False)
    accent = 'foreground' if monochrome else 'accent'
    color = theme.get('accent', '#C2410C')
    hue, saturation, value = colorsys.rgb_to_hsv(*(int(color[i:i+2], 16)/255 for i in (1, 3, 5)))
    fills = []
    for offset in (0, -1/6, .5, 1/6):
        rgb = colorsys.hsv_to_rgb((hue+offset) % 1, saturation, value)
        categorical = '#' + ''.join(f'{round(channel*255):02X}' for channel in rgb)
        fills.append('background' if monochrome else _fill(categorical, theme))

    def path(name, points, fill='none', stroke='foreground', width=2):
        paths.append({'id': prefix+name, 'commands': points, 'fill': fill,
                      'stroke': stroke, 'line_width': width})

    def line(name, points, stroke='foreground', width=2):
        path(name, [['M' if i == 0 else 'L', *p] for i, p in enumerate(points)],
             stroke=stroke, width=width)

    def rect(name, x, y, w, h, fill='background', stroke='foreground'):
        path(name, [['M', x, y], ['L', x+w, y], ['L', x+w, y+h],
                    ['L', x, y+h], ['Z']], fill, stroke)

    def label(name, value, box):
        labels.append({'id': prefix+name, 'text': value, 'box': box})

    def arrow(name, x, y, end):
        line(name, [(x, y), (end, y)], accent)
        line(name+'_head', [(end-14, y-12), (end, y), (end-14, y+12)], accent)

    # This marker is the only non-source label. Geometry and spacing are illustrative,
    # never inferred numerical measurements, layer thicknesses or process durations.
    values = spec['labels']
    marker = '示意' if any(re.search(r'[\u4e00-\u9fff]', value) for value in values.values()) else 'Schematic'
    label('illustrative', marker, [40, 20, 320, 80])
    if spec['template'] == TEMPLATES[0]:
        rect('substrate', 60, 414, 870, 65, fills[0])
        angle = math.radians(35)  # fixed teaching geometry; no numerical angle label
        arc = [(420+110*math.cos(angle*i/16), 408-110*math.sin(angle*i/16)) for i in range(17)]
        path('angle_wash', [['M', 420, 408], *[['L', *point] for point in arc], ['Z']],
             fills[2], 'none')
        line('attached_film', [(90, 408), (420, 408)], accent, 4)
        end = (420+450*math.cos(angle), 408-450*math.sin(angle))
        line('peeled_film', [(420, 408), end], accent, 4)
        for index in range(6):
            x = 445+index*75
            line(f'reference_{index}', [(x, 408), (x+40, 408)])
        line('angle_arc', arc, accent)
        label('substrate', values['substrate'], [80, 485, 620, 70])
        label('film', values['film'], [630, 65, 330, 80])
        label('theta', values['theta'], [535, 315, 90, 75])
    elif spec['template'] == TEMPLATES[1]:
        count = len(values)
        height = min(100, 400/count)
        for i in range(count):
            y = 115+i*height
            rect(f'layer_{i}', 110, y, 780, height, fills[i])
            label(f'layer_{i}', values[f'layer_{i}'], [130, y+8, 740, height-16])
    else:
        # A narrow captioned process chain, not invented material cross-sections.
        count = len(values)
        width = (880-(count-1)*60)/count
        for i in range(count):
            x = 60+i*(width+60)
            rect(f'step_{i}', x, 215, width, 150, fills[i])
            label(f'step_{i}', values[f'step_{i}'], [x+12, 235, width-24, 110])
            if i < count-1:
                arrow(f'order_{i}', x+width+10, 290, x+width+50)
    return {'paths': paths, 'labels': labels, 'view_box': list(VIEW)}
