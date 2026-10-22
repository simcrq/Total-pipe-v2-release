"""Composable scientific components lowered to the existing native shape/text protocol."""
import copy
import math
import re

from PIL import ImageFont

from .dag_layout import (audit_scene, compile_dag, connector_points, layered_order,
                         segment_hits_node)
from .graphic_layout import CONNECTION_SITES, GraphicLayoutError, IDENTIFIER, node_elements
from .graphic_paths import (custom_geometry, number, path_bounds, path_spec_commands, render_paths)

COMPONENT_TYPES = ('mechanism', 'architecture', 'funnel', 'path', 'composite')


def validate_component(data):
    from .graphic_layout import validate_graphics
    errors = []
    kind = data.get('type')
    allowed = {
        'mechanism': {'id', 'type', 'direction', 'nodes', 'edges'},
        'architecture': {'id', 'type', 'direction', 'layers', 'edges'},
        'funnel': {'id', 'type', 'variant', 'levels', 'end_width'},
        'path': {'id', 'type', 'view_box', 'paths', 'labels'},
        'composite': {'id', 'type', 'arrangement', 'components', 'weights'},
    }[kind]
    if set(data)-allowed:
        errors.append(f'{kind}: unknown fields; only local Path IR accepts coordinates')

    def identity(value, label):
        if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
            errors.append(f'{label}: use 1-64 letters, digits, hyphens or underscores')

    def title(value, label, limit=80):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            errors.append(f'{label}: requires 1-{limit} nonblank characters')

    def numeric(value, low, high, label):
        try:
            if not low <= number(value) <= high:
                raise ValueError()
        except ValueError:
            errors.append(f'{label}: requires a finite number between {low} and {high}')

    identity(data.get('id'), 'Component id')
    if kind == 'composite':
        children = data.get('components')
        if not isinstance(children, list) or not 2 <= len(children) <= 4:
            return errors+['A composite requires 2-4 independent components']
        if data.get('arrangement', 'columns') not in ('columns', 'rows'):
            errors.append('Composite arrangement must be columns or rows')
        ids = []
        for child in children:
            if not isinstance(child, dict) or child.get('type') == 'composite':
                errors.append('Composite children must be non-composite graphic objects')
            else:
                errors.extend(validate_graphics([child], 'native-graphic'))
                if isinstance(child.get('id'), str):
                    ids.append(child['id'])
        if len(set(ids)) != len(ids):
            errors.append('Component ids must be unique within a composite')
        weights = data.get('weights', [1]*len(children))
        if not isinstance(weights, list) or len(weights) != len(children):
            errors.append('Composite weights must match the component count')
        else:
            for weight in weights:
                numeric(weight, .01, 100, 'Component weight')
        return errors
    if kind == 'path':
        view = data.get('view_box')
        valid_view = isinstance(view, list) and len(view) == 4
        try:
            valid_view = valid_view and all(number(v) == v for v in view) and min(view[2:]) > 0
        except ValueError:
            valid_view = False
        if not valid_view:
            errors.append('Path view_box requires finite [x, y, positive width, positive height]')
        paths = data.get('paths')
        if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
            return errors+['A path component requires 1-32 paths']
        ids = []
        for path in paths:
            if not isinstance(path, dict):
                errors.append('Each path must be an object')
                continue
            identity(path.get('id'), 'Path id')
            if isinstance(path.get('id'), str):
                ids.append(path['id'])
            if set(path)-{'id', 'commands', 'd', 'fill', 'stroke', 'line_width'}:
                errors.append('Paths accept commands/d and solid fill/stroke only')
            for key, default in (('fill', 'none'), ('stroke', 'accent')):
                color = path.get(key, default)
                if not isinstance(color, str) or (color not in ('accent', 'foreground', 'background', 'none')
                        and not re.fullmatch(r'#[0-9A-Fa-f]{6}', color)):
                    errors.append(f'Path {key} requires a theme color, #RRGGBB or none')
            if path.get('fill', 'none') == 'none' and path.get('stroke', 'accent') == 'none':
                errors.append('A path must have a visible fill or stroke')
            numeric(path.get('line_width', 2), .5, 6, 'Path line_width')
            try:
                px, py, pw, ph = path_bounds(path_spec_commands(path))
                if pw+ph <= 0:
                    errors.append('A path must have a nonzero drawable extent')
                if valid_view and (px < view[0]-1e-6 or py < view[1]-1e-6 or
                        px+pw > view[0]+view[2]+1e-6 or py+ph > view[1]+view[3]+1e-6):
                    errors.append('Path geometry exceeds its declared view_box')
            except ValueError as error:
                errors.append(str(error))
        if len(set(ids)) != len(ids):
            errors.append('Path ids must be unique')
        labels = data.get('labels', [])
        if not isinstance(labels, list) or len(labels) > 32:
            return errors+['Path labels must be a list with at most 32 entries']
        ids = []
        for label in labels:
            if not isinstance(label, dict) or set(label)-{'id', 'text', 'box'}:
                errors.append('A path label accepts id, text and local box only')
                continue
            identity(label.get('id'), 'Path label id')
            title(label.get('text'), 'Path label text', 180)
            if isinstance(label.get('id'), str):
                ids.append(label['id'])
            box = label.get('box')
            try:
                if (not isinstance(box, list) or len(box) != 4 or
                        not all(number(v) == v for v in box) or min(box[2:]) <= 0):
                    raise ValueError()
                if valid_view and (box[0] < view[0] or box[1] < view[1] or
                        box[0]+box[2] > view[0]+view[2] or box[1]+box[3] > view[1]+view[3]):
                    raise ValueError()
            except ValueError:
                errors.append('Path label box must be positive and inside the local view_box')
        if len(set(ids)) != len(ids):
            errors.append('Path label ids must be unique')
        return errors
    if kind == 'funnel':
        levels = data.get('levels')
        if not isinstance(levels, list) or not 2 <= len(levels) <= 8:
            return errors+['A funnel/pyramid requires 2-8 explicitly declared levels']
        if data.get('variant', 'funnel') not in ('funnel', 'pyramid'):
            errors.append('Funnel variant must be funnel or pyramid')
        pyramid = data.get('variant', 'funnel') == 'pyramid'
        numeric(data.get('end_width', 0 if pyramid else .35), 0 if pyramid else .2, 1, 'Funnel end_width')
        for level in levels:
            if isinstance(level, dict) and set(level)-{'id', 'title', 'body'}:
                errors.append('Funnel levels accept id, title and body only')
        nodes, edges = levels, []
    elif kind == 'architecture':
        layers = data.get('layers')
        if not isinstance(layers, list) or not 1 <= len(layers) <= 4:
            return errors+['Architecture requires 1-4 explicit layers']
        nodes, layer_ids = [], []
        for layer in layers:
            if not isinstance(layer, dict) or set(layer)-{'id', 'title', 'nodes'}:
                errors.append('A layer accepts id, title and nodes only')
                continue
            identity(layer.get('id'), 'Layer id')
            title(layer.get('title'), 'Layer title')
            if isinstance(layer.get('id'), str):
                layer_ids.append(layer['id'])
            if not isinstance(layer.get('nodes'), list) or not 1 <= len(layer['nodes']) <= 4:
                errors.append('A layer requires 1-4 nodes')
            else:
                nodes.extend(layer['nodes'])
        if len(set(layer_ids)) != len(layer_ids):
            errors.append('Layer ids must be unique')
        edges = data.get('edges')
    else:
        nodes, edges = data.get('nodes'), data.get('edges')
    if kind != 'funnel' and data.get('direction', 'horizontal') != 'horizontal':
        errors.append('This component currently supports horizontal layers only')
    if not isinstance(edges, list):
        return errors+['Component edges must be explicitly declared as a list']
    if kind == 'mechanism':
        pairs, forward = [], []
        ids = [n.get('id') for n in nodes if isinstance(n, dict) and isinstance(n.get('id'), str)] if isinstance(nodes, list) else []
        for edge in edges:
            if not isinstance(edge, dict):
                errors.append('Each mechanism edge must be an object')
                continue
            if (set(edge)-{'from', 'to', 'kind', 'basis', 'evidence_refs', 'feedback', 'label'} or
                    edge.get('kind') not in ('activate', 'inhibit', 'associate') or
                    edge.get('basis') not in ('evidence', 'hypothesis') or
                    not isinstance(edge.get('feedback', False), bool)):
                errors.append('Mechanism edges require explicit kind and basis; feedback must be boolean')
            if not all(isinstance(edge.get(k), str) and edge[k] in ids for k in ('from', 'to')):
                errors.append('Mechanism edge endpoints must reference existing nodes')
            else:
                pairs.append((edge['from'], edge['to']))
            refs = edge.get('evidence_refs', [])
            if (not isinstance(refs, list) or not all(isinstance(r, str) and r.strip() for r in refs)
                    or (edge.get('basis') == 'evidence' and not refs)):
                errors.append('Evidence relationships require nonempty evidence_refs; hypotheses must be explicit')
            if 'label' in edge:
                title(edge['label'], 'Mechanism edge label')
            if not edge.get('feedback'):
                forward.append({'from': edge.get('from'), 'to': edge.get('to')})
        if len(edges) > 64 or len(pairs) != len(set(pairs)) or any(s == t for s, t in pairs):
            errors.append('Mechanism edges must be unique, without self-loops, and at most 64')
        base = {'id': data.get('id'), 'type': 'dag', 'direction': 'horizontal', 'nodes': nodes, 'edges': forward}
        errors.extend(validate_graphics([base], 'native-graphic'))
        if not errors:
            _, ranks = layered_order(ids, [(e['from'], e['to']) for e in forward])
            if any(ranks[e['from']] <= ranks[e['to']] for e in edges if e.get('feedback')):
                errors.append('Feedback must return from a later layer of the explicitly declared forward DAG')
        return errors
    base = {'id': data.get('id'), 'type': 'dag', 'direction': 'horizontal', 'nodes': nodes, 'edges': edges}
    errors.extend(validate_graphics([base], 'native-graphic'))
    if not errors and kind == 'architecture':
        ranks = {node['id']: rank for rank, layer in enumerate(data['layers']) for node in layer['nodes']}
        if any(ranks[e['from']] >= ranks[e['to']] for e in edges):
            errors.append('Architecture edges must advance through the explicit layer order')
    return errors


def _fonts(theme, font_paths):
    if font_paths:
        return font_paths
    from pathlib import Path
    from .fonts import resolve_theme_fonts
    regular, bold, _ = resolve_theme_fonts(theme, Path.cwd())
    return {'font_file': regular, 'bold_font_file': bold}


def render_process_graph(data, theme, bounds, font_paths=None):
    from .graphic_layout import compile_graphic
    return compile_graphic(data, bounds, theme, font_paths)


def render_layered_architecture(data, theme, bounds, font_paths=None):
    x, y, w, h = bounds
    graph = {'id': data['id'], 'nodes': [n for layer in data['layers'] for n in layer['nodes']],
             'edges': data['edges']}
    groups = [[n['id'] for n in layer['nodes']] for layer in data['layers']]
    elements = compile_dag(graph, [x+16, y+64, w-32, h-80], theme, font_paths, layers_override=groups)
    containers = []
    for layer in data['layers']:
        members = {node['id'] for node in layer['nodes']}
        nodes = [e for e in elements if e.get('role') == 'graphic-node' and e['node_id'] in members]
        left, width = nodes[0]['bbox'][0]-16, nodes[0]['bbox'][2]+32
        cid = f"graphic:{data['id']}:container:{layer['id']}"
        containers.append({'id': cid, 'kind': 'shape', 'role': 'graphic-container',
            'graphic_id': data['id'], 'node_id': 'container:'+layer['id'],
            'bbox': [left, y, width, h], 'geometry': 'roundRect',
            'fill': theme.get('background', '#FFFFFF'), 'line': theme.get('accent', '#C2410C'), 'line_width': 1})
        containers.append({'id': cid+':title', 'kind': 'text', 'role': 'heading',
            'graphic_id': data['id'], 'node_id': 'container:'+layer['id'], 'container_id': cid,
            'text': layer['title'], 'bbox': [left+12, y+10, width-24, 40],
            'font_size': 28, 'max_lines': 1, 'color': theme.get('foreground', '#142735')})
        for e in elements:
            if e.get('node_id') in members:
                e['container_id'] = cid
    return containers+elements


def render_funnel(data, theme, bounds, font_paths=None):
    from .layout import break_lines
    font_paths = _fonts(theme, font_paths)
    regular = ImageFont.truetype(str(font_paths['font_file']), 24)
    bold = ImageFont.truetype(str(font_paths['bold_font_file']), 24)
    x, y, w, h = bounds
    pyramid = data.get('variant', 'funnel') == 'pyramid'
    count, end = len(data['levels']), data.get('end_width', 0 if pyramid else .35)
    gap, heights, widths = 12.0, [], []
    for i, level in enumerate(data['levels']):
        a, b = i/count, (i+1)/count
        if pyramid:
            a, b = 1-a, 1-b
        top_w, bottom_w = w*(1-(1-end)*a), w*(1-(1-end)*b)
        apex = top_w == 0
        text_w = (bottom_w*.5 if apex else min(top_w, bottom_w))*.84
        tl = break_lines(level['title'], bold, text_w)
        bl = break_lines(level.get('body', ''), regular, text_w) if level.get('body', '').strip() else []
        if len(tl) > 2 or len(bl) > 4:
            raise GraphicLayoutError('GRAPHIC_TEXT_OVERFLOW', f"{level['id']}: funnel label exceeds the 18 pt capacity")
        heights.append(max(64, math.ceil((30*(len(tl)+len(bl))+(8 if bl else 0))/(.39 if apex else .78)/8)*8))
        widths.append((top_w, bottom_w, len(tl)*30, len(bl)*30, apex))
    total = sum(heights)+gap*(count-1)
    if total > h:
        raise GraphicLayoutError('GRAPHIC_CAPACITY', f'Funnel levels need {total:.0f} px at 18 pt, only {h:.0f} px available')
    cursor, elements = y+(h-total)/2, []
    for level, height, (top_w, bottom_w, th, bh, apex) in zip(data['levels'], heights, widths):
        outer_w, inner_w = max(top_w, bottom_w), min(top_w, bottom_w)
        left = x+(w-outer_w)/2
        commands = [['M', (outer_w-top_w)/2, 0], ['L', (outer_w+top_w)/2, 0],
                    ['L', (outer_w+bottom_w)/2, height], ['L', (outer_w-bottom_w)/2, height], ['Z']]
        label_w = bottom_w*.5 if apex else inner_w
        label_y, label_h = (cursor+height/2, height/2) if apex else (cursor, height)
        parts = node_elements(data['id'], level, [x+(w-label_w)/2, label_y, label_w, label_h], theme, (th, bh))
        parts[0]['bbox'] = [left, cursor, outer_w, height]
        parts[0].pop('geometry')
        parts[0]['custom_geometry'] = custom_geometry(commands, [0, 0, outer_w, height])
        elements.extend(parts)
        cursor += height+gap
    return elements


def _feedback(data, source, target, bus_y, theme):
    sx, sy, sw, sh = source['bbox']
    tx, ty, _, th = target['bbox']
    start, end = [sx+sw, sy+sh/2], [tx, ty+th/2]
    width, height = start[0]-end[0], abs(end[1]-start[1])
    if width <= 0 or height < 1:
        raise GraphicLayoutError('GRAPHIC_ROUTE_CAPACITY', 'Feedback needs distinct forward layers and endpoint heights')
    flip_v = start[1] > end[1]
    adjustments = {'adj1': round(-32/width*100000),
                   'adj2': round(((start[1]-bus_y) if flip_v else (bus_y-start[1]))/height*100000),
                   'adj3': round((width+32)/width*100000)}
    edge = {'id': f"graphic:{data['id']}:edge:{source['node_id']}:{target['node_id']}",
        'kind': 'connector', 'role': 'graphic-edge', 'graphic_id': data['id'],
        'source_id': source['id'], 'target_id': target['id'],
        'start_site': CONNECTION_SITES[source['geometry']]['right'],
        'end_site': CONNECTION_SITES[target['geometry']]['left'],
        'start': start, 'end': end, 'bbox': [end[0], min(start[1], end[1]), width, height],
        'geometry': 'bentConnector5', 'adjustments': adjustments, 'flip_h': True, 'flip_v': flip_v,
        'line': theme.get('accent', '#C2410C'), 'line_width': 2.5, 'head_end': 'none', 'tail_end': 'triangle'}
    edge['route'] = connector_points(edge['bbox'], edge['geometry'], adjustments, flip_v, True)
    return edge


def render_mechanism_graph(data, theme, bounds, font_paths=None):
    from .layout import break_lines, intersect
    font_paths = _fonts(theme, font_paths)
    x, y, w, h = bounds
    forward = [e for e in data['edges'] if not e.get('feedback')]
    graph = {**data, 'edges': forward}
    side = 40 if any(e.get('feedback') for e in data['edges']) else 0
    elements = compile_dag(graph, [x+side, y+48, w-2*side, h-96], theme, font_paths, column_gap=128)
    nodes = [e for e in elements if e.get('role') == 'graphic-node']
    by_id = {e['node_id']: e for e in nodes}
    routes = [e for e in elements if e['kind'] == 'connector']
    for relation in (e for e in data['edges'] if e.get('feedback')):
        for bus in (y+40, y+h-40, y+12, y+h-12):
            edge = _feedback(data, by_id[relation['from']], by_id[relation['to']], bus, theme)
            if not audit_scene(nodes, routes+[edge], bounds):
                routes.append(edge)
                elements.append(edge)
                break
        else:
            raise GraphicLayoutError('GRAPHIC_ROUTE_CONFLICT', 'Declared feedback has no conflict-free return channel')
    labels = []
    for relation in data['edges']:
        edge = next(e for e in routes if e['source_id'] == by_id[relation['from']]['id']
                    and e['target_id'] == by_id[relation['to']]['id'])
        edge['relation_kind'], edge['basis'] = relation['kind'], relation['basis']
        edge['evidence_refs'] = list(relation.get('evidence_refs', []))
        if relation['kind'] != 'activate':
            edge['tail_end'] = 'none'
        if relation['basis'] == 'hypothesis':
            edge['line_dash'] = 'dash'
        if relation['kind'] == 'inhibit':
            ex, ey = edge['end']
            elements.append({'id': edge['id']+':inhibition', 'kind': 'shape', 'role': 'graphic-mark',
                'graphic_id': data['id'], 'edge_id': edge['id'],
                'bbox': [ex-5, ey-7, 2, 14],
                'geometry': 'rect', 'fill': edge['line'], 'line': 'none', 'line_width': 0})
        label = relation.get('label', '')
        if relation['basis'] == 'hypothesis':
            label = '假设' + ('：'+label if label else '')
        if not label:
            continue
        face = ImageFont.truetype(str(font_paths['font_file']), 24)
        candidates = []
        for a, b in zip(edge['route'], edge['route'][1:]):
            length = abs(a[0]-b[0])
            if abs(a[1]-b[1]) > .05 or length <= 24:
                continue
            label_w = min(length-8, max(56, face.getlength(label)+8))
            lines = break_lines(label, face, label_w)
            if len(lines) > 2 or any(face.getlength(line) > label_w for line in lines):
                continue
            lh = len(lines)*30
            for ly in (a[1]-lh-8, a[1]+8):
                box = [(a[0]+b[0]-label_w)/2, ly, label_w, lh]
                if (box[0] < x or box[1] < y or box[0]+box[2] > x+w or box[1]+box[3] > y+h
                        or any(intersect(box, item['bbox']) for item in [*nodes, *labels])
                        or any(segment_hits_node(p, q, box) for r in routes for p, q in zip(r['route'], r['route'][1:]))):
                    continue
                candidates.append(box)
        if not candidates:
            raise GraphicLayoutError('GRAPHIC_LABEL_CAPACITY', f'{label}: no label area clear of nodes and connectors at 18 pt')
        item = {'id': edge['id']+':label', 'kind': 'text', 'role': 'body', 'graphic_id': data['id'],
            'node_id': 'edge-label:'+relation['from']+':'+relation['to'], 'edge_id': edge['id'],
            'text': label, 'bbox': candidates[0], 'font_size': 24, 'max_lines': 2,
            'color': theme.get('foreground', '#142735')}
        labels.append(item)
    return elements+labels


def render_component(data, theme, bounds, font_paths=None):
    kind = data['type']
    if kind == 'composite':
        x, y, w, h = bounds
        children, gap = data['components'], 24.0
        weights = data.get('weights', [1]*len(children))
        horizontal = data.get('arrangement', 'columns') == 'columns'
        available, cursor = (w if horizontal else h)-gap*(len(children)-1), x if horizontal else y
        if available <= 0:
            raise GraphicLayoutError('GRAPHIC_CAPACITY', 'Composite has no available component area')
        result = []
        for child, weight in zip(children, weights):
            size = available*weight/sum(weights)
            box = [cursor, y, size, h] if horizontal else [x, cursor, w, size]
            spec = copy.deepcopy(child)
            spec['id'] = data['id']+'.'+child['id']
            result.extend(render_component(spec, theme, box, font_paths))
            cursor += size+gap
        return result
    renderer = {'process': render_process_graph, 'dag': render_process_graph,
                'mechanism': render_mechanism_graph, 'architecture': render_layered_architecture,
                'funnel': render_funnel}.get(kind)
    if kind == 'path':
        elements = render_paths(data, theme, bounds)
    elif renderer:
        elements = renderer(data, theme, bounds, font_paths)
    else:
        raise GraphicLayoutError('GRAPHIC_INVALID', f'Unsupported graphic component {kind}')
    for element in elements:
        element['graphic_region'] = list(bounds)
    return elements
