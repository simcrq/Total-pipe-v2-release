"""Versioned body-region trees. Content stays canonical; only the compiler owns geometry."""
from collections import Counter
from dataclasses import dataclass
import math
import re

VERSION = '1.0'
MAX_DEPTH = 6
MAX_NODES = 64
CONTAINERS = ('columns', 'stack', 'panel', 'image_grid')
LEAVES = ('block', 'figure', 'graphic')
GAPS = {'compact': 12., 'standard': 24., 'spacious': 32.}
PADDING = {'none': 0., 'compact': 12., 'standard': 20.}
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def capabilities():
    return {'contract': 'totalpipe.layout-tree', 'version': VERSION,
            'regions': ['body'], 'containers': list(CONTAINERS), 'leaves': list(LEAVES),
            'limits': {'max_depth': MAX_DEPTH, 'max_nodes': MAX_NODES, 'max_columns': 4,
                       'max_graphics': 8, 'max_grid_figures': 12},
            'geometry_owner': 'deck_compiler', 'figure_fit': 'contain',
            'native': ['native_equation', 'native_flowchart', 'native_bezier'],
            'graphic_types': ['process', 'dag', 'mechanism', 'architecture', 'funnel', 'path', 'composite'],
            'legacy_flat_ir': True}


def walk(tree):
    """Yield stable component paths; call only after bounded validation."""
    def visit(node, path):
        yield path, node
        if node['type'] == 'panel':
            yield from visit(node['body'], path+'.body')
        else:
            for index, child in enumerate(node.get('children', [])):
                yield from visit(child, f'{path}.children[{index}]')
    for region, root in tree['regions'].items():
        yield from visit(root, region)


def validate_tree(tree, composition):
    """Strict runtime contract, including complete references and bounded recursion."""
    errors, ids, references, parents = [], set(), [], {}
    def fail(path, message):
        errors.append(f'{path}: {message}')
    if not isinstance(tree, dict) or set(tree) != {'version', 'regions'}:
        return ['layout_tree requires only version and regions']
    if tree.get('version') != VERSION:
        fail('layout_tree.version', f'unsupported version; expected {VERSION}')
    regions = tree.get('regions')
    if not isinstance(regions, dict) or set(regions) != {'body'}:
        return errors+['layout_tree.regions must contain only the compiler-owned body region']
    count = 0
    def visit(node, path, depth, parent=None):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            fail(path, f'layout tree exceeds {MAX_NODES} nodes or depth {MAX_DEPTH}')
            return
        if not isinstance(node, dict):
            fail(path, 'node must be an object')
            return
        kind, nid = node.get('type'), node.get('id')
        if not isinstance(nid, str) or not IDENTIFIER.fullmatch(nid) or nid in ids:
            fail(path, 'unique node id required (1-64 letters, digits, hyphens or underscores)')
        else:
            ids.add(nid)
        fields = {'id', 'type'}
        if kind in ('columns', 'stack'):
            fields |= {'children', 'weights', 'gap'}
        elif kind == 'image_grid':
            fields |= {'children', 'columns', 'gap'}
        elif kind == 'panel':
            fields |= {'title', 'body', 'padding', 'gap'}
        elif kind in LEAVES:
            fields |= {'ref'}
        else:
            fail(path, f'unsupported node type {kind!r}')
            return
        if set(node)-fields:
            fail(path, f'unknown fields {sorted(set(node)-fields)}; page coordinates are forbidden')
        if not isinstance(node.get('gap', 'standard'), str) or node.get('gap', 'standard') not in GAPS:
            fail(path, 'gap must be compact, standard or spacious')
        if kind == 'panel':
            if not isinstance(node.get('title'), str) or not node.get('title', '').strip():
                fail(path, 'panel title required; retain complete terminology')
            if not isinstance(node.get('padding', 'none'), str) or node.get('padding', 'none') not in PADDING:
                fail(path, 'padding must be none, compact or standard')
            visit(node.get('body'), path+'.body', depth+1, (kind, path))
        elif kind in CONTAINERS:
            children = node.get('children')
            maximum = 4 if kind == 'columns' else 12
            if not isinstance(children, list) or not 1 <= len(children) <= maximum:
                fail(path, f'{kind} requires 1-{maximum} children')
                return
            if kind == 'image_grid':
                if type(node.get('columns')) is not int or not 1 <= node['columns'] <= 4:
                    fail(path, 'image_grid.columns must be an integer in [1,4]')
                if any(not isinstance(c, dict) or c.get('type') != 'figure' for c in children):
                    fail(path, 'image_grid children must reference figure_refs, including their captions')
            weights = node.get('weights', [1]*len(children))
            if not isinstance(weights, list) or len(weights) != len(children) or any(
                    isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w)
                    or not .1 <= w <= 10 for w in weights):
                fail(path, 'weights must match children, each finite and in [0.1,10]')
            for index, child in enumerate(children):
                visit(child, f'{path}.children[{index}]', depth+1, (kind, path))
        else:
            ref = node.get('ref')
            valid_ref = type(ref) is int and ref >= 0 if kind == 'figure' else isinstance(ref, str) and bool(ref)
            if not valid_ref:
                fail(path, 'figure ref is a zero-based index; block/graphic ref is a canonical ID')
                return
            references.append((kind, ref))
            if kind == 'block':
                parents[ref] = (parent, path)
    visit(regions['body'], 'body', 1)
    expected = [('block', b['id']) for b in composition.get('blocks', [])
                if isinstance(b, dict) and isinstance(b.get('id'), str)]
    expected += [('figure', i) for i, _ in enumerate(composition.get('figure_refs', []))]
    graphics = composition.get('graphics', [])
    expected += [('graphic', g['id']) for g in (graphics if isinstance(graphics, list) else [])
                 if isinstance(g, dict) and isinstance(g.get('id'), str)]
    actual = Counter(references)
    for key in expected:
        if actual[key] != 1:
            fail('body', f'{key[0]} {key[1]!r} must be referenced exactly once (got {actual[key]})')
    for key in actual.keys()-set(expected):
        fail('body', f'unknown {key[0]} reference {key[1]!r}')
    for block in composition.get('blocks', []):
        if (not isinstance(block, dict) or not isinstance(block.get('anchor'), str)
                or not isinstance(block.get('id'), str)):
            continue
        current, target = parents.get(block.get('id')), parents.get(block['anchor'])
        if (not current or not target or current[0] != target[0] or not current[0]
                or current[0][0] != 'stack'):
            fail(current[1] if current else 'body', 'formula and explanation anchor must be siblings in one stack')
        elif list(parents).index(block['anchor']) > list(parents).index(block['id']):
            fail(current[1], 'explanation anchor must precede its formula in tree reading order')
    return errors


class LayoutTreeError(ValueError):
    def __init__(self, path, code, message, required, available, actions=None, cause=None):
        super().__init__(message)
        self.detail = {'component': path, 'code': code, 'message': message,
                       'required_size_px': [round(x, 2) for x in required],
                       'available_size_px': [round(x, 2) for x in available],
                       'measurement': 'conservative_minimum',
                       'suggested_actions': actions or ['switch_to_two_columns', 'split_slide']}
        if cause:
            self.detail['cause'] = cause


@dataclass
class Need:
    hard: float
    preferred: float
    min_width: float = 1.


class RegionCompiler:
    def __init__(self, composition, assets, fonts, theme, preserve_terms=False):
        self.comp, self.assets, self.fonts, self.theme = composition, assets, fonts, theme
        self.preserve = preserve_terms
        self.blocks = {b['id']: b for b in composition['blocks']}
        self.graphics = {g['id']: g for g in composition.get('graphics', [])}
        self.cache = {}
        self.entries = []

    def text_height(self, content, width, bold=False, size=24):
        from .layout import break_lines
        from .fonts import load_font_file
        face = load_font_file(self.fonts['bold_font_file' if bold else 'font_file'], size)
        return max(1, len(break_lines(content, face, max(1, width))))*size*1.25

    def graphic_min_width(self, graphic):
        kind = graphic['type']
        if kind == 'process':
            count = len(graphic['nodes'])
            return count*200+(count-1)*64
        if kind in ('dag', 'mechanism'):
            from .dag_layout import layered_order
            layers, _ = layered_order([n['id'] for n in graphic['nodes']], [
                (e['from'], e['to']) for e in graphic['edges'] if not e.get('feedback')])
            return len(layers)*176+(len(layers)-1)*72
        if kind == 'architecture':
            return len(graphic['layers'])*176+(len(graphic['layers'])-1)*72+32
        if kind == 'composite':
            sizes = [self.graphic_min_width(c) for c in graphic['components']]
            weights = graphic.get('weights', [1]*len(sizes))
            return (max(size/weight for size, weight in zip(sizes, weights))*sum(weights)
                    +24*(len(sizes)-1)) if graphic.get('arrangement', 'columns') == 'columns' else max(sizes)
        return 96. if kind == 'path' else 176.

    def graphic_height(self, graphic, width, path, available):
        from .graphic_layout import compile_graphic
        minimum = self.graphic_min_width(graphic)
        if width < minimum-.1:
            raise LayoutTreeError(path, 'INSUFFICIENT_DRAWING_SPACE',
                'Native graphic cannot reach its readable minimum width in this region.',
                [minimum, 272 if graphic['type'] == 'process' else 120], available)
        last_error = None
        for height in (96, 128, 160, 200, 240, 272, 320, 384, 448, 512, 640, 768, 1024, 1536):
            try:
                elements = compile_graphic(graphic, [0, 0, width, height], self.theme, self.fonts)
                # Path labels also have fixed font floors; a vector's ability to scale is not a
                # claim that its labels remain readable in the allocated local rectangles.
                if any(self.text_height(e['text'], e['bbox'][2], e.get('role') == 'heading') > e['bbox'][3]+.1
                       for e in elements if e['kind'] == 'text'):
                    last_error = 'Graphic label cannot fit at 18 pt'
                    continue
                return float(height)
            except ValueError as error:
                last_error = str(error)
        raise LayoutTreeError(path, 'INSUFFICIENT_DRAWING_SPACE',
            'Native graphic has no readable allocation in the bounded size search.',
            [minimum, 1536], available, cause=last_error)

    def measure(self, node, width, path, available):
        key = (path, round(width, 5))
        if key in self.cache:
            return self.cache[key]
        kind = node['type']
        gap = GAPS[node.get('gap', 'standard')]
        if width <= 0:
            raise LayoutTreeError(path, 'INSUFFICIENT_DRAWING_SPACE', 'No positive content width.', [1, 1], available)
        if kind == 'block':
            block = self.blocks[node['ref']]
            if block['component'] == 'formula':
                from .layout import formula_label_width
                from totalpipe_layout.formula import measure, parse
                metrics = measure(parse(block['text']), 24)
                label_w = formula_label_width(block.get('label', ''), self.fonts['bold_font_file'])
                required_w = metrics.width+20+(label_w+12 if label_w else 0)
                if required_w > width+.1:
                    raise LayoutTreeError(path, 'INSUFFICIENT_FORMULA_SPACE',
                        'Complete native equation cannot fit at the 18 pt floor.',
                        [required_w, metrics.height+12], available,
                        ['widen_region', 'switch_to_two_columns', 'split_slide'])
                height = max(30 if label_w else 0, metrics.height+12)
                from .layout import formula_fit
                preferred = formula_fit(block['text'], width-20-(label_w+12 if label_w else 0))
                need = Need(height, max(height, preferred.height+12 if preferred else height), required_w)
            else:
                label = 44 if block.get('label') else 0
                natural = label+self.text_height(block['text'], width)
                need = Need(label+30 if self.preserve else natural,
                            max(natural, label+self.text_height(block['text'], width, size=28)))
        elif kind == 'figure':
            ref = self.comp['figure_refs'][node['ref']]
            asset = self.assets[ref['asset_id']]
            floor, panels = ref.get('min_panel_extent', 220), ref.get('panel_count', 1)
            required_w = max(floor*panels, floor*asset['width']/asset['height'])
            caption = 0
            if ref['caption']:
                from .layout import caption_height
                caption = ref.get('caption_height') or caption_height(ref['caption'], width,
                    self.fonts['font_file'], ref.get('caption_font_size', 22))
            height = max(floor, floor*panels*asset['height']/asset['width'])+caption+12
            if required_w > width+.1:
                raise LayoutTreeError(path, 'INSUFFICIENT_FIGURE_SPACE',
                    'Scientific image cannot reach its existing panel floor without cropping.',
                    [required_w, height], available, ['widen_region', 'reduce_grid_columns', 'split_slide'])
            need = Need(height, max(height, width*asset['height']/asset['width']+caption+12), required_w)
        elif kind == 'graphic':
            graphic = self.graphics[node['ref']]
            height = self.graphic_height(graphic, width, path, available)
            preferred = width*graphic['view_box'][3]/graphic['view_box'][2]+8 if graphic['type'] == 'path' else height
            need = Need(height, max(height, preferred), self.graphic_min_width(graphic))
        elif kind == 'panel':
            pad = PADDING[node.get('padding', 'none')]
            inner_w = width-2*pad
            title = self.text_height(node['title'], inner_w, True)
            child = self.measure(node['body'], inner_w, path+'.body', [inner_w, max(0, available[1]-title-gap-2*pad)])
            need = Need(child.hard+(30 if self.preserve else title)+gap+2*pad,
                        child.preferred+title+gap+2*pad, child.min_width+2*pad)
        else:
            children = node['children']
            if kind == 'columns':
                weights = node.get('weights', [1]*len(children))
                usable = width-gap*(len(children)-1)
                needs = [self.measure(c, usable*w/sum(weights), f'{path}.children[{i}]',
                    [usable*w/sum(weights), available[1]]) for i, (c, w) in enumerate(zip(children, weights))]
                need = Need(max(n.hard for n in needs), max(n.preferred for n in needs),
                            max(n.min_width/w for n, w in zip(needs, weights))*sum(weights)+gap*(len(children)-1))
            elif kind == 'image_grid':
                columns = min(node['columns'], len(children))
                cell_w = (width-gap*(columns-1))/columns
                needs = [self.measure(c, cell_w, f'{path}.children[{i}]', [cell_w, available[1]])
                         for i, c in enumerate(children)]
                rows = [needs[i:i+columns] for i in range(0, len(needs), columns)]
                need = Need(sum(max(n.hard for n in row) for row in rows)+gap*(len(rows)-1),
                            sum(max(n.preferred for n in row) for row in rows)+gap*(len(rows)-1),
                            max(n.min_width for n in needs)*columns+gap*(columns-1))
            else:
                needs = [self.measure(c, width, f'{path}.children[{i}]', available) for i, c in enumerate(children)]
                weights = node.get('weights')
                need = Need((max(n.hard/w for n, w in zip(needs, weights))*sum(weights)
                             if weights else sum(n.hard for n in needs))+gap*(len(needs)-1),
                            sum(n.preferred for n in needs)+gap*(len(needs)-1), max(n.min_width for n in needs))
        self.cache[key] = need
        return need

    def allocate(self, node, box, path):
        x, y, width, height = box
        need = self.measure(node, width, path, [width, height])
        kind, gap = node['type'], GAPS[node.get('gap', 'standard')]
        if height < need.hard-.1:
            code = {'block': 'INSUFFICIENT_FORMULA_SPACE' if self.blocks[node['ref']]['component'] == 'formula'
                    else 'INSUFFICIENT_TEXT_SPACE', 'figure': 'INSUFFICIENT_FIGURE_SPACE'}.get(kind, 'INSUFFICIENT_DRAWING_SPACE')
            raise LayoutTreeError(path, code, 'Region is shorter than its measured readable minimum.',
                                  [width, need.hard], [width, height])
        self.entries.append({'component': path, 'node_id': node['id'], 'type': kind, 'bbox': list(box),
            'requirements': {'min_height_px': need.hard, 'preferred_height_px': need.preferred,
                             'min_width_px': need.min_width, 'measured_at_width_px': width,
                             'measurement': 'conservative_minimum'},
            **({'ref': node['ref']} if kind in LEAVES else {})})
        if kind in LEAVES:
            return
        if kind == 'panel':
            pad = PADDING[node.get('padding', 'none')]
            title = self.text_height(node['title'], width-2*pad, True)
            if self.preserve:
                child_need = self.measure(node['body'], width-2*pad, path+'.body', [width-2*pad, height])
                title = min(title, max(30., height-child_need.hard-gap-2*pad))
            self.entries[-1]['title_bbox'] = [x+pad, y+pad, width-2*pad, title]
            self.entries[-1]['title'] = node['title']
            self.allocate(node['body'], [x+pad, y+pad+title+gap, width-2*pad, height-title-gap-2*pad], path+'.body')
            return
        children = node['children']
        if kind == 'columns':
            weights = node.get('weights', [1]*len(children))
            usable = width-gap*(len(children)-1)
            cursor = x
            for i, (child, weight) in enumerate(zip(children, weights)):
                w = usable*weight/sum(weights)
                self.allocate(child, [cursor, y, w, height], f'{path}.children[{i}]')
                cursor += w+gap
            return
        columns = min(node['columns'], len(children)) if kind == 'image_grid' else 1
        cell_w = (width-gap*(columns-1))/columns
        needs = [self.measure(c, cell_w, f'{path}.children[{i}]', [cell_w, height]) for i, c in enumerate(children)]
        rows = [needs[i:i+columns] for i in range(0, len(needs), columns)]
        minimums = [max(n.hard for n in row) for row in rows]
        preferred = [max(n.preferred for n in row) for row in rows]
        usable = height-gap*(len(rows)-1)
        weights = node.get('weights')
        if weights:
            heights = [usable*w/sum(weights) for w in weights]
        else:
            # Hug measured content. Extra space is only consumed towards a child's preferred
            # height, so derivation rows never spread to fill an arbitrarily tall panel.
            extra, demand = max(0, usable-sum(minimums)), sum(max(0, p-m) for p, m in zip(preferred, minimums))
            heights = [m+(min(1., extra/demand)*(p-m) if demand else 0)
                       for m, p in zip(minimums, preferred)]
            if len(rows) == 1 and (kind == 'image_grid' or children[0]['type'] != 'block'):
                heights = [usable]
        cursor = y
        for row, row_h in enumerate(heights):
            for col in range(columns):
                index = row*columns+col
                if index < len(children):
                    self.allocate(children[index], [x+col*(cell_w+gap), cursor, cell_w, row_h],
                                  f'{path}.children[{index}]')
            cursor += row_h+gap


def compile_regions(composition, region, assets, fonts, theme, preserve_terms=False):
    compiler = RegionCompiler(composition, assets, fonts, theme, preserve_terms)
    compiler.allocate(composition['layout_tree']['regions']['body'], list(region), 'body')
    return {'version': VERSION, 'regions': {'body': list(region)}, 'nodes': compiler.entries,
            'reading_order': [e['node_id'] for e in compiler.entries if e['type'] in LEAVES]}
