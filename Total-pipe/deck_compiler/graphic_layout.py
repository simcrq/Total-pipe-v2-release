"""A small semantic process graphic, lowered to the existing shape/text protocol."""
import re


SHAPES = {
    'rect': 'rect', 'rounded-rect': 'roundRect', 'ellipse': 'ellipse',
    'diamond': 'diamond', 'hexagon': 'hexagon',
}
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
# Zero-based cxnLst sites in the DrawingML preset definitions. Ellipse has eight,
# hexagon six; they do not share the rectangle's ordering.
# https://github.com/apache/poi/blob/trunk/poi/src/main/resources/org/apache/poi/sl/draw/geom/presetShapeDefinitions.xml
CONNECTION_SITES = {
    'rect': {'right': 3, 'left': 1, 'top': 0, 'bottom': 2},
    'roundRect': {'right': 3, 'left': 1, 'top': 0, 'bottom': 2},
    'ellipse': {'right': 6, 'left': 2, 'top': 0, 'bottom': 4},
    'diamond': {'right': 3, 'left': 1, 'top': 0, 'bottom': 2},
    # A hexagon has vertices rather than top/bottom edge midpoints; the nearest
    # upper/lower vertices keep a vertical chain editable without pretending a
    # centre site exists.
    'hexagon': {'right': 0, 'left': 3, 'top': 5, 'bottom': 2},
}
NODE_TONES = ('default', 'emphasis')
PROCESS_LAYOUTS = ('chain', 'staggered', 'compact')
NODE_PAD_X, NODE_PAD_Y = 18., 12.


def _wrap(text, face, max_width):
    """Greedy wrap that works for CJK, where there are no spaces to break on."""
    lines, current = [], ''
    for char in text:
        if face.getlength(current+char) <= max_width or not current:
            current += char
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines or ['']


def _chain_width(nodes, limit, theme, font_paths):
    """Widest label that still fits one line, clamped to the column the chain can afford."""
    from .fonts import load_font_file
    from .style import node_style
    style = node_style(theme)
    size = float(style.get('title_size', 30))
    if not font_paths:
        return limit
    face = load_font_file(font_paths['bold_font_file' if style.get('bold', True) else 'font_file'], size)
    # The label box is 94% of the node width, so the required width is the measured line divided
    # back out of that factor.
    need = max(face.getlength(node['title']) for node in nodes)/.94+4
    return max(160., min(limit, need))


def node_fit(nodes, node_width, theme, font_paths, max_height):
    """The height a chain of nodes needs, so a box is not taller than its label.

    A process box is a label with a rule around it, not a card. Sizing it from the measured label
    removes the empty band that made a three-step mechanism look like a slide of empty boxes.
    The measurement follows what ``node_elements`` will draw: the text sits inside the preset's
    contour (a diamond keeps half the box, an ellipse two thirds), title and body split the inner
    height 45/55, and a body line costs its own line height. A box measured for one title line
    used to clip a two-line body on every diamond node.
    """
    from .fonts import load_font_file
    from .style import node_style
    style = node_style(theme)
    size = float(style.get('title_size', 30))
    body_size = float(style.get('body_size', 26))
    if not font_paths:
        return min(max_height, max(72., size*1.25+2*NODE_PAD_Y)), 1
    face = load_font_file(font_paths['bold_font_file' if style.get('bold', True) else 'font_file'], size)
    body_face = load_font_file(font_paths['font_file'], body_size)
    inset = {'diamond': (.5, .5), 'ellipse': (.66, .66), 'hexagon': (.66, .76)}
    lines, need = 1, 0.
    for node in nodes:
        geometry = SHAPES[node.get('shape') or style.get('shape', 'rect')]
        sx, sy = inset.get(geometry, (.94, .78))
        title_lines = _wrap(node['title'], face, max(24., node_width*sx))
        lines = max(lines, len(title_lines))
        title_need = len(title_lines)*size*1.25
        body = str(node.get('body') or '')
        body_need = len(_wrap(body, body_face, max(24., node_width*sx)))*body_size*1.25 if body.strip() else 0.
        # A label-only node keeps the inner height for the title; a node with a body splits it
        # 45/55 the way node_elements does, so both parts have to be paid for.
        inner = max(title_need/.45, (body_need+8)/.55) if body_need else title_need
        need = max(need, inner/sy+2*NODE_PAD_Y)
    return min(max_height, max(72., need)), lines
EMBEDDED_ARCHETYPES = frozenset({'process-flow', 'figure-parameters'})


class GraphicLayoutError(ValueError):
    def __init__(self, rule, message):
        super().__init__(message)
        self.rule = rule


def validate_graphics(graphics, archetype, region_tree=False):
    """Return actionable errors; unsupported graphic content must never disappear."""
    if not isinstance(graphics, list):
        return ['composition.graphics must be a list']
    if region_tree:
        if len(graphics) > 8:
            return ['A layout tree supports at most eight canonical graphics']
        errors, ids = [], []
        for graphic in graphics:
            errors.extend(validate_graphics([graphic], 'native-graphic'))
            if isinstance(graphic, dict) and isinstance(graphic.get('id'), str):
                ids.append(graphic['id'])
        if len(ids) != len(set(ids)):
            errors.append('Graphic ids must be unique across layout-tree leaves')
        return errors
    if archetype != 'native-graphic' and not graphics:
        return []
    if archetype != 'native-graphic' and archetype not in EMBEDDED_ARCHETYPES:
        return ['graphics require native-graphic, process-flow or figure-parameters']
    if len(graphics) != 1:
        return ['Declare exactly one graphic or composite on this page']
    errors = []
    graphic = graphics[0]
    if not isinstance(graphic, dict):
        return ['A graphic must be an object']
    if graphic.get('type') in ('mechanism', 'architecture', 'funnel', 'path', 'composite'):
        from .graphic_components import validate_component
        return validate_component(graphic)
    if set(graphic) - {'id', 'type', 'direction', 'layout', 'nodes', 'edges'}:
        errors.append('Unknown graphic fields; geometry is computed by the compiler')
    if not isinstance(graphic.get('id'), str) or not IDENTIFIER.fullmatch(graphic['id']):
        errors.append('Graphic id must use 1-64 letters, digits, hyphens or underscores')
    kind = graphic.get('type')
    direction = graphic.get('direction', 'horizontal')
    layout = graphic.get('layout', 'chain')
    if kind not in ('process', 'dag'):
        errors.append('Use type=process or dag')
    elif kind == 'dag' and direction != 'horizontal':
        errors.append('A DAG uses direction=horizontal; use a vertical process for a top-down chain')
    elif direction not in ('horizontal', 'vertical'):
        errors.append('direction must be horizontal or vertical')
    if kind == 'process' and layout not in PROCESS_LAYOUTS:
        errors.append(f'layout must be one of {PROCESS_LAYOUTS}')
    elif kind == 'dag' and layout != 'chain':
        errors.append('A DAG uses layout=chain; staggered/compact are process layouts')
    elif layout in ('staggered', 'compact') and direction != 'horizontal':
        errors.append(f'{layout} requires direction=horizontal')
    nodes = graphic.get('nodes')
    if kind == 'dag':
        lower, upper = 1, 16
    elif layout == 'compact':
        lower, upper = 3, 8
    else:
        lower, upper = 3, 4
    if not isinstance(nodes, list) or not lower <= len(nodes) <= upper:
        return errors + [f'A {kind} graphic requires {lower}-{upper} nodes']
    ids = []
    for index, node in enumerate(nodes, 1):
        prefix = f'Node {index}: '
        if not isinstance(node, dict):
            errors.append(prefix + 'must be an object')
            continue
        if set(node) - {'id', 'shape', 'title', 'body', 'tone'}:
            errors.append(prefix + 'unknown fields; do not supply coordinates')
        nid = node.get('id')
        if not isinstance(nid, str) or not IDENTIFIER.fullmatch(nid):
            errors.append(prefix + 'id must use 1-64 letters, digits, hyphens or underscores')
        else:
            ids.append(nid)
        raw_shape = node.get('shape')
        if layout == 'compact':
            if raw_shape not in (None, 'rect'):
                errors.append(prefix + 'compact uses square rect nodes; omit shape or use rect')
            shape = 'rect'
        else:
            shape = raw_shape if raw_shape is not None else 'rounded-rect'
        if not isinstance(shape, str) or shape not in SHAPES:
            errors.append(prefix + f'unsupported shape; choose from {", ".join(SHAPES)}')
        tone = node.get('tone', 'default')
        if tone not in NODE_TONES:
            errors.append(prefix + f'tone must be one of {NODE_TONES}')
        title = node.get('title')
        if not isinstance(title, str) or not title.strip() or len(title) > 80:
            errors.append(prefix + 'title must contain 1-80 characters')
        if 'body' in node and (not isinstance(node['body'], str) or len(node['body']) > 180):
            errors.append(prefix + 'body must be a string of at most 180 characters')
    if len(set(ids)) != len(ids):
        errors.append('Node ids must be unique within the graphic')
    edges = graphic.get('edges')
    if not isinstance(edges, list):
        return errors + ['Graphic edges must be a list']
    pairs = []
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append('Each edge must be an object')
            continue
        if (set(edge) - {'from', 'to', 'kind'} or
                edge.get('kind', 'arrow') != 'arrow'):
            errors.append('Edges support from, to and kind=arrow only')
        if not all(isinstance(edge.get(key), str) and edge[key] in ids for key in ('from', 'to')):
            errors.append('Edge endpoints must reference existing node ids')
        else:
            pairs.append((edge['from'], edge['to']))
    if len(set(pairs)) != len(pairs):
        errors.append('Duplicate edges are not allowed')
    if any(source == target for source, target in pairs):
        errors.append('Self-loops are not allowed')
    if kind == 'process' and len(ids) == len(nodes) and (len(pairs) != len(nodes)-1 or
                                  set(pairs) != set(zip(ids, ids[1:]))):
        errors.append('Edges must connect every adjacent node in the declared order exactly once')
    if kind == 'dag':
        if len(edges) > 64:
            errors.append('A DAG supports at most 64 explicitly declared edges')
        if not errors:
            from .dag_layout import layered_order
            try:
                layered_order(ids, pairs)
            except GraphicLayoutError as error:
                errors.append(str(error))
    return errors


def intentional_overlap(first, second):
    """A node's background may contain its own labels, but no unrelated object."""
    for container, child in ((first, second), (second, first)):
        if child.get('id') in container.get('frame_members', []):
            return True
    same_graphic = bool(first.get('graphic_id')) and first.get('graphic_id') == second.get('graphic_id')
    if same_graphic:
        if first.get('overlap_group') and first.get('overlap_group') == second.get('overlap_group'):
            return True  # Explicit paths/labels in one authored local coordinate scene.
        for container, child in ((first, second), (second, first)):
            if container.get('role') == 'graphic-container' and child.get('container_id') == container['id']:
                return True
    return (bool(first.get('graphic_id')) and
            first.get('graphic_id') == second.get('graphic_id') and
            bool(first.get('node_id')) and first.get('node_id') == second.get('node_id') and
            {first['kind'], second['kind']} == {'shape', 'text'})


def graphic_texts(graphic):
    """Visible component strings for font coverage and the existing audience-text gate."""
    if not isinstance(graphic, dict):
        return
    for child in graphic.get('components', []) if isinstance(graphic.get('components'), list) else []:
        if isinstance(child, dict) and child.get('type') != 'composite':
            yield from graphic_texts(child)
    layers = graphic.get('layers', [])
    layers = layers if isinstance(layers, list) else []
    for layer in layers:
        if isinstance(layer, dict) and isinstance(layer.get('title'), str):
            yield f"graphic layer {layer.get('id')}.title", layer['title']
    nodes = graphic.get('nodes', graphic.get('levels', []))
    nodes = nodes if isinstance(nodes, list) else []
    nodes = nodes + [node for layer in layers if isinstance(layer, dict)
                     and isinstance(layer.get('nodes'), list) for node in layer['nodes']]
    for node in nodes:
        if isinstance(node, dict):
            for key in ('title', 'body'):
                if isinstance(node.get(key, ''), str):
                    yield f"graphic node {node.get('id')}.{key}", node.get(key, '')
    for key in ('labels', 'edges'):
        values = graphic.get(key, [])
        for value in values if isinstance(values, list) else []:
            if isinstance(value, dict):
                field = 'text' if key == 'labels' else 'label'
                if isinstance(value.get(field), str):
                    yield f"graphic {key} {value.get('id', '')}.{field}", value[field]


def mechanism_edges(graphic):
    if isinstance(graphic, dict):
        if graphic.get('type') == 'mechanism' and isinstance(graphic.get('edges'), list):
            yield from (edge for edge in graphic['edges'] if isinstance(edge, dict))
        if graphic.get('type') == 'composite' and isinstance(graphic.get('components'), list):
            for child in graphic['components']:
                if isinstance(child, dict) and child.get('type') == 'mechanism':
                    yield from mechanism_edges(child)


def graphic_counts(graphic):
    if graphic.get('type') == 'composite':
        counts = [graphic_counts(c) for c in graphic['components']]
        return sum(c[0] for c in counts), sum(c[1] for c in counts)
    if graphic.get('type') == 'architecture':
        nodes = [n for layer in graphic['layers'] for n in layer['nodes']]
    else:
        nodes = graphic.get('nodes', graphic.get('levels', graphic.get('paths', [])))
    return len(nodes), len(graphic.get('edges', []))


def graphic_obstacle_collisions(connectors, elements):
    """Check actual segments against labels, nodes and page content, including zero-height lines."""
    from .dag_layout import segment_hits_node
    findings = []
    for edge in connectors:
        if edge.get('role') == 'chart-line':
            continue  # A plot line is not a routed graphic edge; chart internals are one scene.
        route = edge.get('route') or [edge['start'], edge['end']]
        for other in elements:
            if other['kind'] == 'connector' or other.get('collision_mode') == 'container':
                continue
            if edge.get('id') in other.get('frame_members', []):
                continue  # The edge is inside this frame, not crossing unrelated page content.
            if other.get('graphic_id') == edge.get('graphic_id') and (
                    other.get('role') == 'graphic-container' or
                    (other.get('role') == 'graphic-mark' and other.get('edge_id') == edge['id'])):
                continue
            if any(segment_hits_node(a, b, other['bbox']) for a, b in zip(route, route[1:])):
                findings.append((edge['id'], other['id']))
    return findings


def node_elements(graphic_id, node, bbox, theme, text_heights=None, shape_override=None,
                  title_size=None, body_size=None):
    """The v2 node/label renderer, also used by measured DAG nodes."""
    from .style import node_style
    nx, node_y, node_width, node_height = bbox
    foreground = theme.get('foreground', '#142735')
    # A node is drawn in the deck's style pack: the pack owns shape, fill, rule weight and type
    # size, so "academic" and "commercial" are data rather than branches in the emitters.
    tone = node.get('tone', 'default')
    style = node_style(theme, tone)
    title_size = title_size or style.get('title_size', 30)
    body_size = body_size or style.get('body_size', 26)
    elements = []
    prefix = f"graphic:{graphic_id}:node:{node['id']}"
    metadata = {'graphic_id': graphic_id, 'node_id': node['id']}
    if tone != 'default':
        metadata['tone'] = tone
    declared = shape_override or node.get('shape')
    geometry = SHAPES[declared] if declared else SHAPES[style.get('shape', 'rounded-rect')]
    elements.append({'id': prefix, 'kind': 'shape', 'role': 'graphic-node',
                     'bbox': [nx, node_y, node_width, node_height],
                     'geometry': geometry, 'fill': style['fill'], 'line': style['stroke'],
                     'line_width': float(style['stroke_width']), **metadata})
    # A rectangle inside each preset's contour, including a diamond's sloping sides.
    sx, sy = {'diamond': (.5, .5), 'ellipse': (.66, .66),
              'hexagon': (.66, .76)}.get(geometry, (.94, .78))
    inner_w, inner_h = node_width*sx, node_height*sy
    inner_x, inner_y = nx+(node_width-inner_w)/2, node_y+(node_height-inner_h)/2
    body = node.get('body', '')
    title_h = inner_h*.45 if body.strip() else inner_h
    if text_heights and body.strip():
        title_need, body_need = text_heights
        title_h = (inner_h-8)*title_need/(title_need+body_need)
    elements.append({'id': prefix+':title', 'kind': 'text',
                     'role': 'heading' if style.get('bold', True) else 'body',
                     'text': node['title'], 'bbox': [inner_x, inner_y, inner_w, title_h],
                     'font_size': title_size, 'max_lines': 2, 'color': foreground, **metadata})
    if body.strip():
        elements.append({'id': prefix+':body', 'kind': 'text', 'role': 'body',
                         'text': body, 'bbox': [inner_x, inner_y+title_h+8, inner_w,
                                               inner_h-title_h-8],
                         'font_size': body_size, 'max_lines': 4, 'color': foreground, **metadata})
    return elements


def compile_graphic(graphic, region, theme, font_paths=None):
    """Preserve v2/v3 layouts and lower explicit v5 components through the same protocol."""
    if graphic.get('type') not in ('process', 'dag'):
        from .graphic_components import render_component
        return render_component(graphic, theme, region, font_paths)
    if graphic.get('type') == 'dag':
        from .dag_layout import compile_dag
        return compile_dag(graphic, region, theme, font_paths)
    x, y, width, height = region
    count = len(graphic['nodes'])
    direction = graphic.get('direction', 'horizontal')
    layout = graphic.get('layout', 'chain')
    accent = theme.get('accent', '#C2410C')
    from .style import edge_style
    edge_color, edge_width = edge_style(theme)
    elements = []

    if direction == 'vertical':
        gap = 20.0
        # A vertical chain also fits its labels: three short step names in a tall region used to
        # become three 190 px boxes with one line each, which reads as an empty table, not a flow.
        node_width = min(width-32, 560.0)
        node_height, _ = node_fit(graphic['nodes'], node_width, theme, font_paths,
                                  (height-gap*(count-1))/count)
        if node_width < 240 or node_height < 72:
            raise ValueError('Vertical process needs at least 240 px width and 72 px per node')
        node_x = x+(width-node_width)/2
        total = node_height*count+gap*(count-1)
        start_y = y+max(0., (height-total)/2)
        for index, node in enumerate(graphic['nodes']):
            ny = start_y+index*(node_height+gap)
            elements.extend(node_elements(graphic['id'], node, [node_x, ny, node_width, node_height], theme))
        nodes = {e['node_id']: e for e in elements if e['kind'] == 'shape'}
        for source, target in zip(graphic['nodes'], graphic['nodes'][1:]):
            start, end = nodes[source['id']], nodes[target['id']]
            sx, sy, sw, sh = start['bbox']
            tx, ty, tw, th = end['bbox']
            start_point, end_point = [sx+sw/2, sy+sh], [tx+tw/2, ty]
            # A straight preset is diagonal once its bbox has both width and
            # height.  A two-pixel three-segment elbow is visually vertical but
            # keeps the orthogonal route audit and a valid positive extent.
            bbox = [start_point[0]-1.0, start_point[1], 2.0, end_point[1]-start_point[1]]
            adjustments = {'adj1': 50000}
            edge = {'id': f"graphic:{graphic['id']}:edge:{source['id']}:{target['id']}",
                    'kind': 'connector', 'role': 'graphic-edge', 'graphic_id': graphic['id'],
                    'source_id': start['id'], 'target_id': end['id'],
                    'start_site': CONNECTION_SITES[start['geometry']]['bottom'],
                    'end_site': CONNECTION_SITES[end['geometry']]['top'],
                    'start': start_point, 'end': end_point, 'bbox': bbox,
                    'geometry': 'bentConnector3', 'adjustments': adjustments, 'flip_v': False,
                    'line': edge_color, 'line_width': edge_width,
                    'head_end': 'none', 'tail_end': 'triangle'}
            from .dag_layout import connector_points
            edge['route'] = connector_points(bbox, 'bentConnector3', adjustments, False)
            elements.append(edge)
        return elements

    if layout == 'compact':
        gap = 16.0
        node_size = min(180.0, (width-gap*(count-1))/count, height-32)
        if node_size < 96:
            raise ValueError('Compact process needs at least 96 px per square node')
        total = node_size*count+gap*(count-1)
        start_x = x+(width-total)/2
        node_y = y+(height-node_size)/2
        for index, node in enumerate(graphic['nodes']):
            nx = start_x+index*(node_size+gap)
            elements.extend(node_elements(graphic['id'], node, [nx, node_y, node_size, node_size],
                                          theme, shape_override='rect', title_size=24, body_size=24))
        nodes = {e['node_id']: e for e in elements if e['kind'] == 'shape'}
        for source, target in zip(graphic['nodes'], graphic['nodes'][1:]):
            start, end = nodes[source['id']], nodes[target['id']]
            sx, sy, sw, sh = start['bbox']
            tx, ty, _, th = end['bbox']
            start_point, end_point = [sx+sw, sy+sh/2], [tx, ty+th/2]
            elements.append({'id': f"graphic:{graphic['id']}:edge:{source['id']}:{target['id']}",
                             'kind': 'connector', 'role': 'graphic-edge', 'graphic_id': graphic['id'],
                             'source_id': start['id'], 'target_id': end['id'],
                             'start_site': CONNECTION_SITES[start['geometry']]['right'],
                             'end_site': CONNECTION_SITES[end['geometry']]['left'],
                             'start': start_point, 'end': end_point,
                             'bbox': [start_point[0], start_point[1], tx-start_point[0], 0],
                             'geometry': 'straightConnector1', 'line': edge_color, 'line_width': edge_width,
                             'head_end': 'none', 'tail_end': 'triangle'})
        return elements

    gap = 32.0
    limit = min(320.0, (width - gap*(count-1))/count)
    node_width = _chain_width(graphic['nodes'], limit, theme, font_paths)
    total_width = node_width*count + gap*(count-1)
    start_x = x + (width-total_width)/2
    if layout == 'staggered':
        offset = 18.0
        node_height, _ = node_fit(graphic['nodes'], node_width, theme, font_paths, height-32-2*offset)
        if node_width < 160 or node_height < 72:
            raise ValueError('Staggered process needs at least 160 px per node and 72 px of height')
        base_y = y+(height-node_height)/2
    else:
        node_height, _ = node_fit(graphic['nodes'], node_width, theme, font_paths, height-32)
        if node_width < 160 or node_height < 72:
            raise ValueError('Process graphic needs at least 160 px per node and 72 px of height')
        base_y = y+(height-node_height)/2
    for index, node in enumerate(graphic['nodes']):
        nx = start_x + index*(node_width+gap)
        ny = base_y + (-offset if index % 2 == 0 else offset) if layout == 'staggered' else base_y
        elements.extend(node_elements(graphic['id'], node, [nx, ny, node_width, node_height], theme))
    nodes = {e['node_id']: e for e in elements if e['kind'] == 'shape'}
    # Emit after the nodes, in visual order even if the IR edge list is permuted.
    for source, target in zip(graphic['nodes'], graphic['nodes'][1:]):
        start, end = nodes[source['id']], nodes[target['id']]
        sx, sy, sw, sh = start['bbox']
        tx, ty, _, th = end['bbox']
        start_point, end_point = [sx+sw, sy+sh/2], [tx, ty+th/2]
        if layout == 'staggered':
            top, dy = min(start_point[1], end_point[1]), abs(end_point[1]-start_point[1])
            width = tx-start_point[0]
            bbox = [start_point[0], top, width, dy]
            # A diagonal straight connector is rejected by the orthogonal route
            # audit; a three-segment elbow keeps the staggered rhythm editable.
            adjustments = {'adj1': round((width/2)/width*100000)}
            geometry = 'bentConnector3'
            flip_v = end_point[1] < start_point[1]
            edge = {'id': f"graphic:{graphic['id']}:edge:{source['id']}:{target['id']}",
                    'kind': 'connector', 'role': 'graphic-edge', 'graphic_id': graphic['id'],
                    'source_id': start['id'], 'target_id': end['id'],
                    'start_site': CONNECTION_SITES[start['geometry']]['right'],
                    'end_site': CONNECTION_SITES[end['geometry']]['left'],
                    'start': start_point, 'end': end_point, 'bbox': bbox,
                    'geometry': geometry, 'adjustments': adjustments, 'flip_v': flip_v,
                    'line': edge_color, 'line_width': edge_width,
                    'head_end': 'none', 'tail_end': 'triangle'}
            from .dag_layout import connector_points
            edge['route'] = connector_points(bbox, geometry, adjustments, flip_v)
            elements.append(edge)
        else:
            elements.append({'id': f"graphic:{graphic['id']}:edge:{source['id']}:{target['id']}",
                             'kind': 'connector', 'role': 'graphic-edge', 'graphic_id': graphic['id'],
                             'source_id': start['id'], 'target_id': end['id'],
                             'start_site': CONNECTION_SITES[start['geometry']]['right'],
                             'end_site': CONNECTION_SITES[end['geometry']]['left'],
                             'start': start_point, 'end': end_point,
                             'bbox': [start_point[0], start_point[1], tx-start_point[0], 0],
                             'geometry': 'straightConnector1', 'line': edge_color, 'line_width': edge_width,
                             'head_end': 'none', 'tail_end': 'triangle'})
    return elements
