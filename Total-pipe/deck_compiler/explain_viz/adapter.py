"""The only ExplainViz module that knows canonical Deck IR and compiled geometry."""
import copy
from pathlib import Path

from ..contracts import digest
from .specs import PREFIX


def placeholder(graphic_id='explanation_visual'):
    """An ordinary, explicitly reserved Path IR scene; no new compiler syntax."""
    return {'id': graphic_id, 'type': 'path', 'view_box': [0, 0, 1000, 600],
            'paths': [{'id': 'reserved_area', 'commands': [
                ['M', 0, 0], ['L', 1000, 0], ['L', 1000, 600], ['L', 0, 600], ['Z']],
                'fill': 'background', 'stroke': 'none'}]}


def inside(inner, outer, tolerance=.1):
    x, y, w, h = inner
    a, b, c, d = outer
    return x >= a-tolerance and y >= b-tolerance and x+w <= a+c+tolerance and y+h <= b+d+tolerance


def overlaps(a, b):
    return (min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0]) > .1
            and min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]) > .1)


class DeckIRAdapter:
    version = '1.0'

    def __init__(self, base='.'):
        self.base = Path(base)

    def list_slides(self, deck_ir):
        return deck_ir['slides']

    def read_slide_semantics(self, slide, slot):
        sem, comp = slide['semantic'], slide['composition']
        facts = {f'semantic.{key}': sem[key] for key in ('title', 'takeaway')}
        facts.update({f"block:{block['id']}": block['text'] for block in comp['blocks']})
        visuals = len(comp['figure_refs'])+len(comp.get('charts', []))+len(comp.get('tables', []))
        visuals += sum(graphic['id'] != slot['graphic_id'] for graphic in comp.get('graphics', []))
        return {'title': sem['title'], 'archetype': comp['archetype'],
                'facts': facts, 'existing_visuals': visuals}

    def already_processed(self, slide):
        return any(item.get('id', '').startswith(PREFIX)
                   for graphic in slide['composition'].get('graphics', [])
                   for field in ('paths', 'labels') for item in graphic.get(field, []))

    def find_visual_slot(self, slide, slot):
        from ..graphic_paths import path_spec_commands
        from ..graphic_layout import validate_graphics
        comp = slide['composition']
        if not comp.get('layout_tree'):
            return None
        graphic = next((g for g in comp.get('graphics', []) if g['id'] == slot['graphic_id']), None)
        if (not graphic or graphic.get('type') != 'path' or graphic.get('labels')
                or len(graphic.get('paths', [])) != 1
                or validate_graphics([graphic], 'native-graphic')):
            return None
        path = graphic['paths'][0]
        if path.get('fill') != 'background' or path.get('stroke') != 'none':
            return None
        x, y, w, h = graphic['view_box']
        expected = [['M', x, y], ['L', x+w, y], ['L', x+w, y+h], ['L', x, y+h], ['Z']]
        if path_spec_commands(path) != expected:
            return None
        return graphic

    def supported_primitives(self):
        return ['path', 'polyline', 'text']

    def compile(self, deck_ir):
        from ..ir import validate
        from ..layout import compile_deck
        if any(item['severity'] == 'FAIL' for item in validate(deck_ir)):
            raise ValueError('invalid_ir')
        layout, issues = compile_deck(deck_ir, self.base)
        if layout is None or any(item['severity'] == 'FAIL' for item in issues):
            raise ValueError('compile_failed')
        return layout

    def find_slot_box(self, layout, slide_id, graphic_id):
        page = next(page for page in layout['slides'] if page['id'] == slide_id)
        element = next(e for e in page['elements'] if e.get('graphic_id') == graphic_id)
        box = element.get('layout_region')
        if box is None or box[2] < 420 or box[3] < 260:
            raise ValueError('insufficient_space')
        return box

    def list_occupied_boxes(self, layout, slide_id, graphic_id):
        page = next(page for page in layout['slides'] if page['id'] == slide_id)
        reserved_ids = {e['id'] for e in page['elements'] if e.get('graphic_id') == graphic_id}
        return [e['bbox'] for e in page['elements'] if e.get('graphic_id') != graphic_id
                and e.get('role') != 'background'
                and not reserved_ids.intersection(e.get('frame_members', []))]

    def build_native_group(self, visual_spec, slot, theme):
        from .templates import build
        group = build(visual_spec)
        x, y, w, h = slot['view_box']
        _, _, source_w, source_h = group['view_box']
        scale = min(w/source_w, h/source_h)
        left, top = x+(w-source_w*scale)/2, y+(h-source_h*scale)/2
        for path in group['paths']:
            for command in path['commands']:
                command[1:] = [round(value*scale+(left if i % 2 == 0 else top), 6)
                               for i, value in enumerate(command[1:])]
        for label in group['labels']:
            lx, ly, lw, lh = label['box']
            label['box'] = [round(left+lx*scale, 6), round(top+ly*scale, 6),
                            round(lw*scale, 6), round(lh*scale, 6)]
        group['view_box'] = list(slot['view_box'])
        return group

    def append_group(self, deck_ir, slide_id, graphic_id, group):
        from ..graphic_layout import validate_graphics
        slide = next(s for s in self.list_slides(deck_ir) if s['id'] == slide_id)
        graphic = next(g for g in slide['composition']['graphics'] if g['id'] == graphic_id)
        graphic['paths'].extend(copy.deepcopy(group['paths']))
        graphic.setdefault('labels', []).extend(copy.deepcopy(group['labels']))
        if len(graphic['labels']) > 7 or validate_graphics([graphic], 'native-graphic'):
            raise ValueError('invalid_native_group')
        return [f"graphic:{graphic_id}:path:{item['id']}" for item in group['paths']]+[
            f"graphic:{graphic_id}:label:{item['id']}" for item in group['labels']]

    def validate_ir(self, original, candidate, baseline, additions):
        """Use the real compiler, then compare every pre-existing native object."""
        layout = self.compile(candidate)
        before_pages = {page['id']: page for page in baseline['slides']}
        after_pages = {page['id']: page for page in layout['slides']}
        if before_pages.keys() != after_pages.keys():
            raise ValueError('page_set_changed')
        allowed = {(item['slide_id'], eid) for item in additions for eid in item['shape_ids']}
        found = set()
        for sid, before_page in before_pages.items():
            after = after_pages[sid]['elements']
            old_ids = [element['id'] for element in before_page['elements']]
            old_set = set(old_ids)
            if [e['id'] for e in after if e['id'] in old_set] != old_ids:
                raise ValueError('existing_object_order_changed')
            after_by_id = {element['id']: element for element in after}
            for old in before_page['elements']:
                current = after_by_id[old['id']]
                # Existing frame membership can gain new objects; geometry, content,
                # style, existing members and relative z order remain identical.
                old_fields = {k: v for k, v in old.items() if k != 'frame_members'}
                new_fields = {k: v for k, v in current.items() if k != 'frame_members'}
                if old_fields != new_fields or [eid for eid in current.get('frame_members', [])
                                               if eid in old_set] != old.get('frame_members', []):
                    raise ValueError('existing_object_changed')
            new_text = []
            for element in after:
                if element['id'] in old_set:
                    continue
                key = (sid, element['id'])
                if key not in allowed:
                    raise ValueError('unexpected_object')
                found.add(key)
                record = next(item for item in additions if item['slide_id'] == sid)
                box = self.find_slot_box(baseline, sid, record['graphic_id'])
                if not inside(element['bbox'], box):
                    raise ValueError('out_of_slot')
                if any(overlaps(element['bbox'], occupied) for occupied in
                       self.list_occupied_boxes(baseline, sid, record['graphic_id'])):
                    raise ValueError('layout_conflict')
                if element['kind'] == 'text':
                    from ..fonts import load_font_file
                    from ..layout import break_lines
                    contract = element['contract']
                    size = contract['font_size']
                    face = load_font_file(contract['font_file'], size)
                    lines = break_lines(element['text'], face, element['bbox'][2])
                    if (size < 24 or len(lines)*size*contract['line_height'] > element['bbox'][3]+.1
                            or any(face.getlength(line) > element['bbox'][2]+.1 for line in lines)):
                        raise ValueError('illegible_label')
                    if any(overlaps(element['bbox'], other['bbox']) for other in new_text):
                        raise ValueError('label_overlap')
                    new_text.append(element)
        if found != allowed:
            raise ValueError('missing_native_object')
        # No changes outside the reserved graphic arrays, including notes/evidence/tree.
        restored = copy.deepcopy(candidate)
        source = {slide['id']: slide for slide in original['slides']}
        for item in additions:
            slide = next(s for s in restored['slides'] if s['id'] == item['slide_id'])
            graphics = slide['composition']['graphics']
            index = next(i for i, g in enumerate(graphics) if g['id'] == item['graphic_id'])
            graphics[index] = copy.deepcopy(next(g for g in source[item['slide_id']]['composition']['graphics']
                                                if g['id'] == item['graphic_id']))
        if digest(restored) != digest(original):
            raise ValueError('unauthorized_ir_change')
        return layout
