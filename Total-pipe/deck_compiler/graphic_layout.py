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
    'rect': {'right': 3, 'left': 1},
    'roundRect': {'right': 3, 'left': 1},
    'ellipse': {'right': 6, 'left': 2},
    'diamond': {'right': 3, 'left': 1},
    'hexagon': {'right': 0, 'left': 3},
}
EMBEDDED_ARCHETYPES = frozenset({'process-flow', 'figure-parameters'})


class GraphicLayoutError(ValueError):
    def __init__(self, rule, message):
        super().__init__(message)
        self.rule = rule


def validate_graphics(graphics, archetype):
    """Return actionable errors; unsupported graphic content must never disappear."""
    if not isinstance(graphics, list):
        return ['composition.graphics must be a list']
    if archetype != 'native-graphic' and not graphics:
        return []
    if archetype != 'native-graphic' and archetype not in EMBEDDED_ARCHETYPES:
        return ['graphics require native-graphic, process-flow or figure-parameters']
    if len(graphics) != 1:
        return ['Declare exactly one process or DAG graphic on this page']
    errors = []
    graphic = graphics[0]
    if not isinstance(graphic, dict):
        return ['A graphic must be an object']
    if set(graphic) - {'id', 'type', 'direction', 'nodes', 'edges'}:
        errors.append('Unknown graphic fields; geometry is computed by the compiler')
    if not isinstance(graphic.get('id'), str) or not IDENTIFIER.fullmatch(graphic['id']):
        errors.append('Graphic id must use 1-64 letters, digits, hyphens or underscores')
    kind = graphic.get('type')
    if kind not in ('process', 'dag') or graphic.get('direction') != 'horizontal':
        errors.append('Use type=process or dag, direction=horizontal')
    nodes = graphic.get('nodes')
    lower, upper = (1, 16) if kind == 'dag' else (3, 4)
    if not isinstance(nodes, list) or not lower <= len(nodes) <= upper:
        return errors + [f'A {kind} graphic requires {lower}-{upper} nodes']
    ids = []
    for index, node in enumerate(nodes, 1):
        prefix = f'Node {index}: '
        if not isinstance(node, dict):
            errors.append(prefix + 'must be an object')
            continue
        if set(node) - {'id', 'shape', 'title', 'body'}:
            errors.append(prefix + 'unknown fields; do not supply coordinates')
        nid = node.get('id')
        if not isinstance(nid, str) or not IDENTIFIER.fullmatch(nid):
            errors.append(prefix + 'id must use 1-64 letters, digits, hyphens or underscores')
        else:
            ids.append(nid)
        shape = node.get('shape', 'rounded-rect')
        if not isinstance(shape, str) or shape not in SHAPES:
            errors.append(prefix + f'unsupported shape; choose from {", ".join(SHAPES)}')
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
    return (bool(first.get('graphic_id')) and
            first.get('graphic_id') == second.get('graphic_id') and
            bool(first.get('node_id')) and first.get('node_id') == second.get('node_id') and
            {first['kind'], second['kind']} == {'shape', 'text'})


def graphic_obstacle_collisions(connectors, elements):
    """Check actual line segments against page content outside their own graphic."""
    from .dag_layout import segment_hits_node
    findings = []
    for edge in connectors:
        route = edge.get('route') or [edge['start'], edge['end']]
        for other in elements:
            if (other['kind'] == 'connector' or other.get('collision_mode') == 'container' or
                    other.get('graphic_id') == edge.get('graphic_id')):
                continue
            if any(segment_hits_node(a, b, other['bbox']) for a, b in zip(route, route[1:])):
                findings.append((edge['id'], other['id']))
    return findings


def node_elements(graphic_id, node, bbox, theme, text_heights=None):
    """The v2 node/label renderer, also used by measured DAG nodes."""
    nx, node_y, node_width, node_height = bbox
    accent = theme.get('accent', '#C2410C')
    foreground = theme.get('foreground', '#142735')
    background = theme.get('background', '#FFFFFF')
    # A restrained theme tint, computed once; the PPTX still carries a solid editable fill.
    fill = '#' + ''.join(f'{round(int(accent[k:k+2], 16)*.08 + int(background[k:k+2], 16)*.92):02X}'
                         for k in (1, 3, 5))
    elements = []
    prefix = f"graphic:{graphic_id}:node:{node['id']}"
    metadata = {'graphic_id': graphic_id, 'node_id': node['id']}
    geometry = SHAPES[node.get('shape', 'rounded-rect')]
    elements.append({'id': prefix, 'kind': 'shape', 'role': 'graphic-node',
                     'bbox': [nx, node_y, node_width, node_height],
                     'geometry': geometry, 'fill': fill, 'line': accent,
                     'line_width': 2, **metadata})
    # A rectangle inside each preset's contour, including a diamond's sloping sides.
    sx, sy = {'diamond': (.5, .5), 'ellipse': (.66, .66),
              'hexagon': (.66, .76)}.get(geometry, (.84, .78))
    inner_w, inner_h = node_width*sx, node_height*sy
    inner_x, inner_y = nx+(node_width-inner_w)/2, node_y+(node_height-inner_h)/2
    body = node.get('body', '')
    title_h = inner_h*.45 if body.strip() else inner_h
    if text_heights and body.strip():
        title_need, body_need = text_heights
        title_h = (inner_h-8)*title_need/(title_need+body_need)
    elements.append({'id': prefix+':title', 'kind': 'text', 'role': 'heading',
                     'text': node['title'], 'bbox': [inner_x, inner_y, inner_w, title_h],
                     'font_size': 30, 'max_lines': 2, 'color': foreground, **metadata})
    if body.strip():
        elements.append({'id': prefix+':body', 'kind': 'text', 'role': 'body',
                         'text': body, 'bbox': [inner_x, inner_y+title_h+8, inner_w,
                                               inner_h-title_h-8],
                         'font_size': 26, 'max_lines': 4, 'color': foreground, **metadata})
    return elements


def compile_graphic(graphic, region, theme, font_paths=None):
    """Keep v2 process geometry intact; only explicit DAGs use layered layout."""
    if graphic.get('type') == 'dag':
        from .dag_layout import compile_dag
        return compile_dag(graphic, region, theme, font_paths)
    x, y, width, height = region
    count = len(graphic['nodes'])
    gap = 64.0
    node_width = (width - gap*(count-1))/count
    node_height = min(272.0, height-32)
    if node_width < 200 or node_height < 240:
        raise ValueError('Process graphic needs at least 200 px per node and 272 px of height')
    node_y = y + (height-node_height)/2
    accent = theme.get('accent', '#C2410C')
    elements = []
    for index, node in enumerate(graphic['nodes']):
        nx = x + index*(node_width+gap)
        elements.extend(node_elements(graphic['id'], node, [nx, node_y, node_width, node_height], theme))
    nodes = {e['node_id']: e for e in elements if e['kind'] == 'shape'}
    # Emit after the nodes, in visual order even if the IR edge list is permuted.
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
                         'geometry': 'straightConnector1', 'line': accent, 'line_width': 2.5,
                         'head_end': 'none', 'tail_end': 'triangle'})
    return elements
