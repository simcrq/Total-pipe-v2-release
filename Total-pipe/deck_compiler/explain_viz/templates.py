"""Versioned deterministic templates lowered only to existing Path IR and text."""
import math
import re

from ..contracts import digest
from .specs import PREFIX, TEMPLATES

VIEW = [0, 0, 1000, 600]


def build(spec):
    prefix = PREFIX+digest(spec)[:12]+'_'
    paths, labels = [], []

    def path(name, points, fill='none', stroke='foreground', width=2):
        paths.append({'id': prefix+name, 'commands': points, 'fill': fill,
                      'stroke': stroke, 'line_width': width})

    def line(name, points, stroke='foreground', width=2):
        path(name, [['M' if i == 0 else 'L', *p] for i, p in enumerate(points)],
             stroke=stroke, width=width)

    def rect(name, x, y, w, h, stroke='foreground'):
        path(name, [['M', x, y], ['L', x+w, y], ['L', x+w, y+h],
                    ['L', x, y+h], ['Z']], 'background', stroke)

    def label(name, value, box):
        labels.append({'id': prefix+name, 'text': value, 'box': box})

    def arrow(name, x, y, end):
        line(name, [(x, y), (end, y)], 'accent')
        line(name+'_head', [(end-14, y-12), (end, y), (end-14, y+12)], 'accent')

    # This marker is the only non-source label. Geometry and spacing are illustrative,
    # never inferred numerical measurements, layer thicknesses or process durations.
    values = spec['labels']
    marker = '示意' if any(re.search(r'[\u4e00-\u9fff]', value) for value in values.values()) else 'Schematic'
    label('illustrative', marker, [40, 20, 320, 80])
    if spec['template'] == TEMPLATES[0]:
        rect('substrate', 60, 414, 870, 65)
        line('attached_film', [(90, 408), (420, 408)], 'accent', 4)
        angle = math.radians(35)  # fixed teaching geometry; no numerical angle label
        end = (420+450*math.cos(angle), 408-450*math.sin(angle))
        line('peeled_film', [(420, 408), end], 'accent', 4)
        for index in range(6):
            x = 445+index*75
            line(f'reference_{index}', [(x, 408), (x+40, 408)])
        line('angle_arc', [(420+110*math.cos(angle*i/16), 408-110*math.sin(angle*i/16))
                           for i in range(17)], 'accent')
        label('substrate', values['substrate'], [80, 485, 620, 70])
        label('film', values['film'], [630, 65, 330, 80])
        label('theta', values['theta'], [535, 315, 90, 75])
    elif spec['template'] == TEMPLATES[1]:
        count = len(values)
        height = min(100, 400/count)
        for i in range(count):
            y = 115+i*height
            rect(f'layer_{i}', 110, y, 780, height)
            label(f'layer_{i}', values[f'layer_{i}'], [130, y+8, 740, height-16])
    else:
        # A narrow captioned process chain, not invented material cross-sections.
        count = len(values)
        width = (880-(count-1)*60)/count
        for i in range(count):
            x = 60+i*(width+60)
            rect(f'step_{i}', x, 215, width, 150)
            label(f'step_{i}', values[f'step_{i}'], [x+12, 235, width-24, 110])
            if i < count-1:
                arrow(f'order_{i}', x+width+10, 290, x+width+50)
    return {'paths': paths, 'labels': labels, 'view_box': list(VIEW)}
