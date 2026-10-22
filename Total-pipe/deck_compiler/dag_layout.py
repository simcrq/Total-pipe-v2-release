"""Small, deterministic layered DAG layout and native orthogonal connector routing."""
import math
from pathlib import Path
from PIL import ImageFont

from .graphic_layout import CONNECTION_SITES, SHAPES, GraphicLayoutError, node_elements

EPS = .05
INSETS = {'diamond': (.5, .5), 'ellipse': (.66, .66), 'hexagon': (.66, .76)}


def layered_order(ids, pairs):
    """Longest-path ranks, followed by stable barycenter sweeps. Never invent an edge."""
    order = {nid: i for i, nid in enumerate(ids)}
    parents, children = {n: [] for n in ids}, {n: [] for n in ids}
    for source, target in pairs:
        if source not in order or target not in order:
            raise GraphicLayoutError('GRAPHIC_INVALID', 'Edge references an unknown DAG node')
        parents[target].append(source)
        children[source].append(target)
    for adjacent in [*parents.values(), *children.values()]:
        adjacent.sort(key=order.get)
    degree = {n: len(parents[n]) for n in ids}
    ranks = dict.fromkeys(ids, 0)
    ready = [n for n in ids if not degree[n]]
    visited = []
    while ready:
        node = ready.pop(0)
        visited.append(node)
        for target in sorted(children[node], key=order.get):
            ranks[target] = max(ranks[target], ranks[node]+1)
            degree[target] -= 1
            if not degree[target]:
                ready.append(target)
                ready.sort(key=order.get)
    if len(visited) != len(ids):
        raise GraphicLayoutError('GRAPHIC_CYCLE', 'Directed cycle detected in the declared DAG edges')
    layers = [[n for n in ids if ranks[n] == rank] for rank in range(max(ranks.values())+1)]
    for _ in range(4):
        for indexes, neighbors in ((range(1, len(layers)), parents),
                                   (range(len(layers)-2, -1, -1), children)):
            for index in indexes:
                positions = {n: j/max(1, len(layer)-1) for layer in layers for j, n in enumerate(layer)}
                def key(n):
                    adjacent = neighbors[n]
                    return (sum(positions[a] for a in adjacent)/len(adjacent)
                            if adjacent else positions[n], order[n])
                layers[index].sort(key=key)
    return layers, ranks


def connector_points(bbox, geometry, adjustments=None, flip_v=False, flip_h=False):
    """Evaluate the small native preset subset used here, including external doglegs."""
    x, y, w, h = bbox
    a = adjustments or {}
    if geometry == 'straightConnector1':
        local = [(0, 0), (w, h)]
    elif geometry == 'bentConnector3':
        bend = w*a['adj1']/100000
        local = [(0, 0), (bend, 0), (bend, h), (w, h)]
    elif geometry == 'bentConnector5':
        first, bus, last = w*a['adj1']/100000, h*a['adj2']/100000, w*a['adj3']/100000
        local = [(0, 0), (first, 0), (first, bus), (last, bus), (last, h), (w, h)]
    else:
        raise GraphicLayoutError('GRAPHIC_ROUTE_INVALID', f'Unsupported connector geometry {geometry}')
    result = []
    for px, py in local:
        point = [x+w-px if flip_h else x+px, y+h-py if flip_v else y+py]
        if not result or any(abs(a-b) > EPS for a, b in zip(point, result[-1])):
            result.append(point)
    return result


def segment_hits_node(first, last, bbox):
    """Strict interior intersection: touching the declared node port is allowed."""
    x, y, w, h = bbox
    ax, ay = first
    bx, by = last
    if abs(ay-by) < EPS:
        return y+EPS < ay < y+h-EPS and max(min(ax, bx), x+EPS) < min(max(ax, bx), x+w-EPS)
    if abs(ax-bx) < EPS:
        return x+EPS < ax < x+w-EPS and max(min(ay, by), y+EPS) < min(max(ay, by), y+h-EPS)
    return True  # A diagonal is not an orthogonal route.


def segments_conflict(a, b, c, d):
    horizontal_a, horizontal_b = abs(a[1]-b[1]) < EPS, abs(c[1]-d[1]) < EPS
    if horizontal_a == horizontal_b:
        fixed, variable = (1, 0) if horizontal_a else (0, 1)
        return (abs(a[fixed]-c[fixed]) < EPS and
                max(min(a[variable], b[variable]), min(c[variable], d[variable])) <
                min(max(a[variable], b[variable]), max(c[variable], d[variable]))-EPS)
    if not horizontal_a:
        a, b, c, d = c, d, a, b
    return (min(a[0], b[0])-EPS <= c[0] <= max(a[0], b[0])+EPS and
            min(c[1], d[1])-EPS <= a[1] <= max(c[1], d[1])+EPS)


def routes_conflict(first, second):
    # Shared endpoints may have a visible common trunk; unrelated edges may not form false junctions.
    if {first['source_id'], first['target_id']} & {second['source_id'], second['target_id']}:
        return False
    return any(segments_conflict(a, b, c, d)
               for a, b in zip(first['route'], first['route'][1:])
               for c, d in zip(second['route'], second['route'][1:]))


def audit_scene(nodes, connectors, region):
    """The same segment checks are used before output and on actual OOXML paths."""
    findings = []
    rx, ry, rw, rh = region
    for index, node in enumerate(nodes):
        x, y, w, h = node['bbox']
        if x < rx-EPS or y < ry-EPS or x+w > rx+rw+EPS or y+h > ry+rh+EPS:
            findings.append(('GRAPHIC_OUT_OF_BOUNDS', 'Node exceeds the graphic region', node['id']))
        for other in nodes[:index]:
            ox, oy, ow, oh = other['bbox']
            if min(x+w, ox+ow) > max(x, ox)+EPS and min(y+h, oy+oh) > max(y, oy)+EPS:
                findings.append(('GRAPHIC_NODE_OVERLAP', f"Node overlaps {other['id']}", node['id']))
    for index, edge in enumerate(connectors):
        route = edge['route']
        if len(route) < 2 or any(not math.isfinite(v) for point in route for v in point):
            findings.append(('GRAPHIC_ROUTE_INVALID', 'Invalid orthogonal path', edge['id']))
            continue
        if any(px < rx-EPS or py < ry-EPS or px > rx+rw+EPS or py > ry+rh+EPS for px, py in route):
            findings.append(('GRAPHIC_OUT_OF_BOUNDS', 'Connector path exceeds the graphic region', edge['id']))
        for a, b in zip(route, route[1:]):
            if abs(a[0]-b[0]) > EPS and abs(a[1]-b[1]) > EPS:
                findings.append(('GRAPHIC_ROUTE_INVALID', 'Connector contains a diagonal segment', edge['id']))
            for node in nodes:
                if segment_hits_node(a, b, node['bbox']):
                    findings.append(('GRAPHIC_ROUTE_THROUGH_NODE', f"Connector crosses {node['id']}", edge['id']))
        for other in connectors[:index]:
            if routes_conflict(edge, other):
                findings.append(('GRAPHIC_ROUTE_CONFLICT', f"Unrelated connector crosses/overlaps {other['id']}", edge['id']))
    return findings


def _connector(graphic_id, source, target, bend_x, bus_y=None, last_x=None):
    sx, sy, sw, sh = source['bbox']
    tx, ty, _, th = target['bbox']
    start, end = [sx+sw, sy+sh/2], [tx, ty+th/2]
    width, height = end[0]-start[0], abs(end[1]-start[1])
    flip = start[1] > end[1]
    geometry = 'straightConnector1' if height < EPS and bus_y is None else 'bentConnector3'
    adjustments = {}
    if geometry != 'straightConnector1':
        adjustments['adj1'] = round((bend_x-start[0])/width*100000)
    if bus_y is not None:
        if height < 1:
            raise GraphicLayoutError('GRAPHIC_ROUTE_CAPACITY', 'Long-edge dogleg requires distinct endpoint heights')
        geometry = 'bentConnector5'
        adjustments['adj2'] = round((start[1]-bus_y if flip else bus_y-start[1])/height*100000)
        adjustments['adj3'] = round((last_x-start[0])/width*100000)
    edge = {'id': f"graphic:{graphic_id}:edge:{source['node_id']}:{target['node_id']}",
            'kind': 'connector', 'role': 'graphic-edge', 'graphic_id': graphic_id,
            'source_id': source['id'], 'target_id': target['id'],
            'start_site': CONNECTION_SITES[source['geometry']]['right'],
            'end_site': CONNECTION_SITES[target['geometry']]['left'],
            'start': start, 'end': end,
            'bbox': [start[0], min(start[1], end[1]), width, height],
            'geometry': geometry, 'adjustments': adjustments, 'flip_v': flip,
            'line_width': 2.5, 'head_end': 'none', 'tail_end': 'triangle'}
    edge['route'] = connector_points(edge['bbox'], geometry, adjustments, flip)
    return edge


def compile_dag(graphic, region, theme, font_paths=None, *, layers_override=None, column_gap=72.0):
    from .layout import break_lines
    if font_paths is None:
        from .fonts import resolve_theme_fonts
        regular, bold, _ = resolve_theme_fonts(theme, Path.cwd())
        font_paths = {'font_file': regular, 'bold_font_file': bold}
    ids = [n['id'] for n in graphic['nodes']]
    pairs = [(e['from'], e['to']) for e in graphic['edges']]
    layers, ranks = layered_order(ids, pairs)
    if layers_override is not None:
        layers = layers_override
        if sorted(n for layer in layers for n in layer) != sorted(ids) or any(not layer for layer in layers):
            raise GraphicLayoutError('GRAPHIC_INVALID', 'Declared layers must contain every node exactly once')
        ranks = {nid: rank for rank, layer in enumerate(layers) for nid in layer}
        if any(ranks[s] >= ranks[t] for s, t in pairs):
            raise GraphicLayoutError('GRAPHIC_INVALID', 'Architecture edges must advance through the declared layers')
    by_id = {n['id']: n for n in graphic['nodes']}
    x, y, width, height = region
    columns, gap = len(layers), float(column_gap)
    node_width = min(320.0, (width-gap*(columns-1))/columns)
    if node_width < 176:
        raise GraphicLayoutError('GRAPHIC_CAPACITY', f'{columns} DAG layers leave less than 176 px per node; split the diagram')
    long_edges = [(s, t) for s, t in pairs if ranks[t]-ranks[s] > 1]
    pad = 32 if long_edges else 12
    available = height-2*pad-4*(columns-1)
    faces = {key: ImageFont.truetype(str(font_paths[key]), 24) for key in ('font_file', 'bold_font_file')}
    heights, text_heights = {}, {}
    for nid in ids:
        node = by_id[nid]
        sx, sy = INSETS.get(SHAPES[node.get('shape', 'rounded-rect')], (.84, .78))
        title_lines = break_lines(node['title'], faces['bold_font_file'], node_width*sx)
        body_lines = break_lines(node.get('body', ''), faces['font_file'], node_width*sx) if node.get('body', '').strip() else []
        if len(title_lines) > 2 or len(body_lines) > 4:
            raise GraphicLayoutError('GRAPHIC_TEXT_OVERFLOW',
                f'{nid}: text needs {len(title_lines)} title / {len(body_lines)} body lines at 18 pt; widen or split the diagram')
        th, bh = len(title_lines)*30.0, len(body_lines)*30.0
        text_heights[nid] = th, bh
        heights[nid] = max(96.0, math.ceil((th+bh+(8 if bh else 0))/sy/8)*8)
    boxes = {}
    left = x+(width-(node_width*columns+gap*(columns-1)))/2
    for rank, layer in enumerate(layers):
        need = sum(heights[n] for n in layer)+24*(len(layer)-1)
        if need > available+EPS:
            raise GraphicLayoutError('GRAPHIC_CAPACITY',
                f'DAG layer {rank+1} needs {need:.0f} px, only {available:.0f} px available at 18 pt; split the diagram')
        cursor = y+pad+(available-need)/2+4*rank
        for nid in layer:
            boxes[nid] = [left+rank*(node_width+gap), cursor, node_width, heights[nid]]
            cursor += heights[nid]+24
    # Avoid the zero-height degeneracy of native five-segment presets for long detours.
    for source, target in sorted(long_edges, key=lambda p: (ranks[p[1]], ids.index(p[1]), ids.index(p[0]))):
        if abs(boxes[source][1]+boxes[source][3]/2-boxes[target][1]-boxes[target][3]/2) < 1:
            for nid in layers[ranks[target]]:
                boxes[nid][1] += 4
    elements = []
    for node in graphic['nodes']:
        elements.extend(node_elements(graphic['id'], node, boxes[node['id']], theme, text_heights[node['id']]))
    nodes = [e for e in elements if e['kind'] == 'shape']
    native_nodes = {n['node_id']: n for n in nodes}
    routes = []
    lanes = [.5, 1/3, 2/3, .25, .75, 1/6, 5/6]
    for source, target in sorted(pairs, key=lambda p: (ranks[p[1]]-ranks[p[0]], ids.index(p[0]), ids.index(p[1]))):
        src, dst = native_nodes[source], native_nodes[target]
        start_x = src['bbox'][0]+node_width
        target_x = dst['bbox'][0]
        accepted = None
        last_findings = []
        for fraction in lanes:
            bend_x = start_x+gap*fraction
            buses = [None] if ranks[target]-ranks[source] == 1 else [y+12, y+height-12, y+20, y+height-20]
            for bus in buses:
                edge = _connector(graphic['id'], src, dst, bend_x, bus,
                                  target_x-gap*fraction if bus is not None else None)
                edge['line'] = theme.get('accent', '#C2410C')
                last_findings = audit_scene(nodes, routes+[edge], region)
                if not last_findings:
                    accepted = edge
                    break
            if accepted:
                break
        if accepted is None:
            rule, message, _ = last_findings[0]
            raise GraphicLayoutError(rule, f'{source} -> {target}: {message}; split or simplify the diagram')
        routes.append(accepted)
    findings = audit_scene(nodes, routes, region)
    if findings:
        rule, message, _ = findings[0]
        raise GraphicLayoutError(rule, message)
    return elements+routes
