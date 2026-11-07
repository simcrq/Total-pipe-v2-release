"""Bounded empty-rectangle detection and canonical relative body-layout proposals."""
import copy
import math

from ..contracts import digest


def contains(inner, outer, tolerance=.1):
    x, y, w, h = inner
    a, b, c, d = outer
    return x >= a-tolerance and y >= b-tolerance and x+w <= a+c+tolerance and y+h <= b+d+tolerance


def empty_rectangles(region, occupied, minimum=(420, 260), margin=12):
    """Subtract expanded occupied boxes; prune contained rectangles after every cut."""
    if (len(region) != 4 or any(not math.isfinite(v) for v in region) or min(region[2:]) <= 0
            or region[2] < minimum[0] or region[3] < minimum[1]):
        return []
    boxes = [list(region)]
    for ox, oy, ow, oh in occupied:
        obstacle = [ox-margin, oy-margin, max(0, ow)+2*margin, max(0, oh)+2*margin]
        next_boxes = []
        for x, y, w, h in boxes:
            a, b = max(x, obstacle[0]), max(y, obstacle[1])
            c, d = min(x+w, obstacle[0]+obstacle[2]), min(y+h, obstacle[1]+obstacle[3])
            if a >= c or b >= d:
                next_boxes.append([x, y, w, h])
                continue
            next_boxes.extend(([x, y, a-x, h], [c, y, x+w-c, h],
                               [x, y, w, b-y], [x, d, w, y+h-d]))
        useful = sorted({tuple(round(v, 5) for v in box) for box in next_boxes
                         if box[2] >= minimum[0] and box[3] >= minimum[1]},
                        key=lambda b: (-b[2]*b[3], b[1], b[0]))
        boxes = []
        for box in useful:
            if not any(contains(box, kept) for kept in boxes):
                boxes.append(list(box))
        boxes = boxes[:128]
    return boxes


def body_region(deck_ir, slide, layout):
    from ..layout import ARCHETYPES, body_region as bounds, frame_variant, preserve_scientific_terms, resolve_design
    page = next(page for page in layout['slides'] if page['id'] == slide['id'])
    fonts = {}
    for key, bold in (('font_file', False), ('bold_font_file', True)):
        fonts[key] = next((e['contract']['font_file'] for e in page['elements'] if e.get('contract')
                           and (e['contract'].get('font_weight', 400) >= 700) == bold), deck_ir['theme'][key])
    top, bottom = bounds(slide, ARCHETYPES[slide['composition']['archetype']]['layout'],
                         frame_variant(deck_ir), resolve_design(deck_ir), fonts, preserve_scientific_terms(deck_ir))
    return [56., top, 1168., bottom-top]


def _nodes(root, path=()):
    yield path, root
    if root['type'] == 'panel':
        yield from _nodes(root['body'], (*path, 'body'))
    for index, child in enumerate(root.get('children', [])):
        yield from _nodes(child, (*path, 'children', index))


def _without(root, graphic_id):
    node = copy.deepcopy(root)
    if node['type'] == 'graphic' and node['ref'] == graphic_id:
        return None
    if node['type'] == 'panel':
        node['body'] = _without(node['body'], graphic_id)
        return node if node['body'] else None
    if 'children' in node:
        children, weights = [], []
        for index, child in enumerate(node['children']):
            value = _without(child, graphic_id)
            if value:
                children.append(value)
                if 'weights' in node:
                    weights.append(node['weights'][index])
        if not children:
            return None
        node['children'] = children
        if 'weights' in node:
            node['weights'] = weights
    return node


def _content_tree(comp, graphic_id, prefix):
    if comp.get('layout_tree'):
        return _without(comp['layout_tree']['regions']['body'], graphic_id)
    children = [{'id': prefix+f'b{i}', 'type': 'block', 'ref': block['id']}
                for i, block in enumerate(comp['blocks'])]
    children += [{'id': prefix+f'f{i}', 'type': 'figure', 'ref': i} for i in range(len(comp['figure_refs']))]
    for field, kind in (('graphics', 'graphic'), ('tables', 'table'), ('charts', 'chart')):
        children += [{'id': prefix+f'{kind}{i}', 'type': kind, 'ref': item['id']}
                     for i, item in enumerate(comp.get(field, [])) if item['id'] != graphic_id]
    if not children:
        return None
    kind = 'columns' if len(children) <= 4 and not any(b.get('component') == 'formula' for b in comp['blocks']) else 'stack'
    return {'id': prefix+'content', 'type': kind, 'gap': 'compact', 'children': children}


def slot_candidates(deck_ir, slide_id, slot, baseline, options, adapter):
    """Yield candidate IRs plus authorization metadata. No candidate mutates the input."""
    slide = next(s for s in deck_ir['slides'] if s['id'] == slide_id)
    anchor = adapter.find_visual_slot(slide, slot)
    if anchor is not None:
        yield copy.deepcopy(deck_ir), {'source': 'reserved', 'variant': 'existing_slot'}
    if options.slot_policy == 'reserved_only':
        return
    from .adapter import placeholder
    region = body_region(deck_ir, slide, baseline)
    page = next(p for p in baseline['slides'] if p['id'] == slide_id)
    occupied = [e['bbox'] for e in page['elements'] if e.get('graphic_id') != slot['graphic_id']
                and e.get('role') != 'background' and not e.get('frame_members')]
    free = empty_rectangles(region, occupied)
    prefix = 'evz_layout_'+digest([slide_id, slot['graphic_id']])[:10]+'_'
    content = _content_tree(slide['composition'], slot['graphic_id'], prefix)
    leaf = {'id': prefix+'slot', 'type': 'graphic', 'ref': slot['graphic_id']}
    seen = set()

    def make(root, policy, name):
        key = digest(root)
        if key in seen:
            return None
        seen.add(key)
        candidate = copy.deepcopy(deck_ir)
        comp = next(s for s in candidate['slides'] if s['id'] == slide_id)['composition']
        if anchor is None:
            if any(g['id'] == slot['graphic_id'] for g in comp.get('graphics', [])):
                return None
            comp.setdefault('graphics', []).append(placeholder(slot['graphic_id']))
        comp['archetype'] = 'composite-research'
        comp['layout_tree'] = {'version': comp.get('layout_tree', {}).get('version', '1.2'),
                               'regions': {'body': root}}
        return candidate, {'source': policy, 'variant': name, 'free_regions': free, 'body_region': region}

    # Appending into a measured stack can consume its unused tail without moving
    # any old native box. Actual geometry is checked after compilation.
    tree = slide['composition'].get('layout_tree')
    if anchor is None and tree and free:
        for path, node in _nodes(tree['regions']['body']):
            if node['type'] != 'stack' or node.get('weights') or len(node['children']) >= 12:
                continue
            root = copy.deepcopy(tree['regions']['body'])
            target = root
            for step in path:
                target = target[step]
            target['children'].append(copy.deepcopy(leaf))
            measured = {entry['node_id']: entry for adaptation in page.get('adaptation_log', [])
                        if adaptation.get('action') == 'layout_tree' for entry in adaptation.get('nodes', [])}
            if node['id'] in measured and all(child['id'] in measured for child in node['children']):
                from ..layout_tree import GAPS
                heights = [measured[child['id']]['bbox'][3] for child in node['children']]
                remaining = measured[node['id']]['bbox'][3]-sum(heights)-GAPS[node.get('gap', 'standard')]*len(heights)
                if remaining >= 260:
                    values = [*heights, remaining]
                    target['weights'] = [round(value/max(values)*10, 6) for value in values]
                    if min(target['weights']) >= .1:
                        value = make(root, 'detected', 'fill_measured_stack_tail')
                        if value:
                            yield value
                    target.pop('weights', None)
            value = make(root, 'detected', 'append_stack')
            if value:
                yield value
    if content is None:
        value = make(leaf, 'detected', 'empty_body')
        if value:
            yield value
        return
    variants = [('stack', False, [1, 3]), ('columns', False, [1, 1]),
                ('stack', False, [1, 2]), ('columns', False, [1.4, 1]),
                ('stack', True, [3, 1]), ('columns', True, [1, 1]),
                ('stack', False, [1, 1]), ('columns', False, [2, 1])]
    for kind, first, weights in variants:
        root = {'id': prefix+'root', 'type': kind, 'gap': 'compact', 'weights': weights,
                'children': [copy.deepcopy(leaf), copy.deepcopy(content)] if first else
                            [copy.deepcopy(content), copy.deepcopy(leaf)]}
        if free:
            value = make(root, 'detected', f'{kind}_{"first" if first else "last"}_{weights}')
            if value:
                yield value
        if options.allow_local_reflow:
            # Same relative proposal, but explicitly authorize only this page's body
            # to move. Keep a separate attempt identity from the no-movement proposal.
            seen.discard(digest(root))
            value = make(root, 'local_reflow', f'{kind}_{"first" if first else "last"}_{weights}')
            if value:
                yield value
