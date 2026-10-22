"""Read-only structural verification of the actual exported package."""
import hashlib
import zipfile
from lxml import etree as ET
from .contracts import issue
from .layout import intersect
from .ooxml import NS, slide_parts, relationships, background, fill
from .graphic_layout import graphic_obstacle_collisions, intentional_overlap
from .dag_layout import audit_scene, connector_points
from .graphic_paths import geometry_signature

A = '{' + NS['a'] + '}'
EMU = 9525


def verify(path, layout):
    items = []
    def add(rule, message, slide=None, shape=None, severity='FAIL', confidence='HIGH'):
        items.append(issue(rule, severity, message, slide, shape, detector='structural-ooxml',
                           confidence=confidence, geometry='ooxml', textbox_contract='deck_ir'))
    try:
        with zipfile.ZipFile(path) as z:
            if z.testzip():
                raise ValueError('ZIP CRC failure')
            for name in z.namelist():
                if name.endswith('.xml') or name.endswith('.rels'):
                    ET.fromstring(z.read(name))
                if name.endswith('.rels'):
                    source = name.replace('/_rels/', '/').removesuffix('.rels')
                    if name == '_rels/.rels':
                        source = ''
                    for rel in relationships(z, source).values():
                        if not rel['external'] and rel['target'] not in z.namelist():
                            add('BROKEN_RELATIONSHIP', f"{name}: {rel['target']}")
            if layout.get('background_image'):
                # The picture is one part on the slide master; check the bytes actually landed.
                expected = layout['assets'].get('@background', {}).get('sha256')
                master = next((name for name in z.namelist()
                               if name.startswith('ppt/slideMasters/slideMaster')
                               and name.endswith('.xml')), None)
                target = None
                if master:
                    blip = ET.fromstring(z.read(master)).find('.//p:bg//a:blip', NS)
                    if blip is not None:
                        target = relationships(z, master).get(
                            blip.get('{' + NS['r'] + '}embed'), {}).get('target')
                if not target or target not in z.namelist() or hashlib.sha256(
                        z.read(target)).hexdigest() != expected:
                    add('BACKGROUND_IMAGE_MISSING',
                        'The declared background picture is not on the slide master')
            parts = slide_parts(z)
            if len(parts) != len(layout['slides']):
                add('SLIDE_COUNT_MISMATCH', 'Slide count differs from IR')
            presentation = ET.fromstring(z.read('ppt/presentation.xml'))
            size = presentation.find('p:sldSz', NS)
            if any(abs(int(size.get(k))/EMU-v) > .1 for k, v in zip(('cx', 'cy'), layout['slide_size'])):
                add('CANVAS_MISMATCH', 'Canvas differs from compiled layout')
            for n, (part, slide) in enumerate(zip(parts, layout['slides']), 1):
                root = ET.fromstring(z.read(part))
                # A full-bleed picture lives on the master, once, so every slide inherits it
                # without carrying a copy of the image. The colour comparison does not apply.
                if not layout.get('background_image'):
                    bg, source = background(z, part)
                    if bg is None:
                        add('BACKGROUND_UNRESOLVED', source, n, severity='REVIEW', confidence='LOW')
                    elif bg.upper() != slide['background'].upper():
                        add('BACKGROUND_MISMATCH', f'{bg} != {slide["background"]}', n)
                notes_part = next((rel['target'] for rel in relationships(z, part).values()
                                   if rel['type'] == 'notesSlide' and not rel['external']), None)
                if notes_part not in z.namelist():
                    add('MISSING_NOTES', 'Speaker notes part absent', n)
                else:
                    notes_root = ET.fromstring(z.read(notes_part))
                    body = next((shape for shape in notes_root.findall('.//p:sp', NS)
                                 if (shape.find('p:nvSpPr/p:nvPr/p:ph', NS) is not None and
                                     shape.find('p:nvSpPr/p:nvPr/p:ph', NS).get('type') == 'body')), None)
                    paragraphs = [] if body is None else [
                        ''.join(text.text or '' for text in paragraph.findall('.//a:t', NS))
                        for paragraph in body.findall('p:txBody/a:p', NS)]
                    if '\n'.join(paragraphs) != slide['notes']:
                        add('NOTES_MISMATCH', 'Speaker notes differ from compiled layout', n)
                shapes = root.findall('p:cSld/p:spTree/p:sp', NS)
                actual = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s for s in shapes}
                connectors = root.findall('p:cSld/p:spTree/p:cxnSp', NS)
                actual_connectors = {s.find('p:nvCxnSpPr/p:cNvPr', NS).get('name'): s for s in connectors}
                planned = {e['id']: e for e in slide['elements']}
                expected_graphics = [e['id'] for e in slide['elements'] if e.get('graphic_id')]
                if expected_graphics:
                    if len(connectors) != sum(e['kind'] == 'connector' for e in slide['elements']):
                        add('CONNECTOR_COUNT_MISMATCH', 'Native connector count differs from layout', n)
                    graphic_names = [s.find('p:nvSpPr/p:cNvPr', NS).get('name') for s in shapes
                                     if s.find('p:nvSpPr/p:cNvPr', NS).get('name', '').startswith('graphic:')]
                    graphic_names += [s.find('p:nvCxnSpPr/p:cNvPr', NS).get('name') for s in connectors
                                      if s.find('p:nvCxnSpPr/p:cNvPr', NS).get('name', '').startswith('graphic:')]
                    if sorted(graphic_names) != sorted(expected_graphics):
                        add('GRAPHIC_OBJECT_MISMATCH',
                            'Native graphic object names/count differ from the compiled layout', n)
                    numeric_ids = [s.get('id') for s in root.findall('.//p:cNvPr', NS)]
                    if len(set(numeric_ids)) != len(numeric_ids):
                        add('GRAPHIC_ID_COLLISION', 'PowerPoint shape ids must be unique on each slide', n)
                boxes = []
                routed, native_nodes, native_paths = [], [], []
                for e in slide['elements']:
                    if e['kind'] == 'connector':
                        connector = actual_connectors.get(e['id'])
                        if connector is None:
                            add('CONNECTOR_MISSING', 'Expected p:cxnSp connector absent', n, e['id'])
                            continue
                        connections = connector.find('p:nvCxnSpPr/p:cNvCxnSpPr', NS)
                        for tag, endpoint, site in (('stCxn', 'source_id', 'start_site'),
                                                     ('endCxn', 'target_id', 'end_site')):
                            references = [] if connections is None else connections.findall('a:'+tag, NS)
                            target = actual.get(e[endpoint])
                            if len(references) != 1 or target is None:
                                add('CONNECTOR_REFERENCE_INVALID', 'Connector endpoint/node missing', n, e['id'])
                                continue
                            ref = references[0]
                            target_id = target.find('p:nvSpPr/p:cNvPr', NS).get('id')
                            node_ids = {s.find('p:nvSpPr/p:cNvPr', NS).get('id') for name, s in actual.items()
                                        if planned.get(name, {}).get('role') == 'graphic-node'}
                            if ref.get('id') not in node_ids:
                                add('CONNECTOR_REFERENCE_INVALID',
                                    'Connector reference does not identify a native node on this slide', n, e['id'])
                            if (planned.get(e[endpoint], {}).get('role') != 'graphic-node' or
                                    ref.get('id') != target_id or ref.get('idx') != str(e[site])):
                                add('CONNECTOR_BINDING_MISMATCH',
                                    'Connector must bind the declared node and preset connection site', n, e['id'])
                        props = connector.find('p:spPr', NS)
                        xf = props.find('a:xfrm', NS)
                        off, ext = xf.find('a:off', NS), xf.find('a:ext', NS)
                        box = [int(off.get('x'))/EMU, int(off.get('y'))/EMU,
                               int(ext.get('cx'))/EMU, int(ext.get('cy'))/EMU]
                        flip_v = xf.get('flipV', '0') in ('1', 'true')
                        flip_h = xf.get('flipH', '0') in ('1', 'true')
                        if (any(abs(a-b) > .2 for a, b in zip(box, e['bbox'])) or
                                xf.get('rot', '0') != '0' or flip_h != e.get('flip_h', False) or
                                flip_v != e.get('flip_v', False)):
                            add('GEOMETRY_MISMATCH', 'Connector endpoints differ from layout', n, e['id'])
                        preset = props.find('a:prstGeom', NS)
                        if preset is None or preset.get('prst') != e['geometry']:
                            add('CONNECTOR_GEOMETRY_MISMATCH', 'Expected native connector preset', n, e['id'])
                        if e.get('route') and preset is not None:
                            try:
                                guides = preset.findall('a:avLst/a:gd', NS)
                                adjustments = {}
                                for guide in guides:
                                    formula = guide.get('fmla', '').split()
                                    if len(formula) != 2 or formula[0] != 'val':
                                        raise ValueError('Expected literal routing adjustment')
                                    adjustments[guide.get('name')] = int(formula[1])
                                if len(guides) != len(adjustments) or adjustments != e['adjustments']:
                                    add('CONNECTOR_ROUTE_MISMATCH', 'Native routing adjustments differ from layout', n, e['id'])
                                route = connector_points(box, preset.get('prst'), adjustments, flip_v, flip_h)
                                if len(route) != len(e['route']) or any(abs(a-b) > .2 for p, q in zip(route, e['route'])
                                                                                          for a, b in zip(p, q)):
                                    add('CONNECTOR_ROUTE_MISMATCH', 'Native orthogonal path differs from layout', n, e['id'])
                                routed.append({**e, 'bbox': box, 'route': route})
                                native_paths.append({**e, 'route': route})
                            except (KeyError, ValueError, TypeError) as error:
                                add('CONNECTOR_ROUTE_MISMATCH', str(error), n, e['id'])
                        elif preset is not None and preset.get('prst') == 'straightConnector1':
                            native_paths.append({**e, 'route': connector_points(box, 'straightConnector1', flip_v=flip_v, flip_h=flip_h)})
                        line = props.find('a:ln', NS)
                        if (line is None or fill(line) != e['line'].upper() or
                                abs(int(line.get('w', '0'))/EMU-e['line_width']) > .1):
                            add('CONNECTOR_STYLE_MISMATCH', 'Connector line differs from layout', n, e['id'])
                        dash = None if line is None else line.find('a:prstDash', NS)
                        if (dash.get('val') if dash is not None else 'solid') != e.get('line_dash', 'solid'):
                            add('CONNECTOR_STYLE_MISMATCH', 'Connector evidence/hypothesis dash differs from layout', n, e['id'])
                        for tag, key in (('headEnd', 'head_end'), ('tailEnd', 'tail_end')):
                            arrow = None if line is None else line.find('a:'+tag, NS)
                            if arrow is None or arrow.get('type') != e[key]:
                                add('CONNECTOR_DIRECTION_MISMATCH',
                                    'Arrow must point from the declared source to target', n, e['id'])
                        boxes.append((e['id'], box))
                        continue
                    if e['kind'] == 'shape' and e.get('graphic_id'):
                        shape = actual.get(e['id'])
                        if shape is None:
                            add('MISSING_SHAPE', 'Expected native graphic shape absent', n, e['id'])
                            continue
                        props = shape.find('p:spPr', NS)
                        xf = props.find('a:xfrm', NS)
                        off, ext = xf.find('a:off', NS), xf.find('a:ext', NS)
                        box = [int(off.get('x'))/EMU, int(off.get('y'))/EMU,
                               int(ext.get('cx'))/EMU, int(ext.get('cy'))/EMU]
                        if any(abs(a-b) > .2 for a, b in zip(box, e['bbox'])):
                            add('GEOMETRY_MISMATCH', 'Native graphic geometry differs from layout', n, e['id'])
                        if xf.get('rot', '0') != '0' or any(xf.get(k, '0') not in ('0', 'false')
                                                          for k in ('flipH', 'flipV')):
                            add('GEOMETRY_MISMATCH', 'Unexpected native graphic rotation/flip', n, e['id'])
                        preset = props.find('a:prstGeom', NS)
                        custom = props.find('a:custGeom', NS)
                        if e.get('custom_geometry'):
                            if (preset is not None or custom is None or
                                    geometry_signature(custom) != geometry_signature(e['custom_geometry'])):
                                add('GRAPHIC_PATH_MISMATCH', 'Native custom geometry differs from compiled Path IR', n, e['id'])
                        elif custom is not None or preset is None or preset.get('prst') != e['geometry']:
                            add('GRAPHIC_PRESET_MISMATCH', 'Native preset differs from graphic shape', n, e['id'])
                        line = props.find('a:ln', NS)
                        for element, expected in ((props, e['fill']), (line, e['line'])):
                            expected = expected.upper() if expected != 'none' else None
                            if fill(element) != expected:
                                add('GRAPHIC_STYLE_MISMATCH', 'Native fill/outline differs from layout', n, e['id'])
                        if e['line'] != 'none' and (line is None or
                                abs(int(line.get('w', '0'))/EMU-e['line_width']) > .1):
                            add('GRAPHIC_STYLE_MISMATCH', 'Native outline width differs from layout', n, e['id'])
                        if e.get('role') == 'graphic-node':
                            native_nodes.append({**e, 'bbox': box})
                        boxes.append((e['id'], box))
                        continue
                    if e['kind'] == 'math':
                        shape = actual.get(e['id'])
                        if shape is None:
                            add('MISSING_SHAPE', 'Expected equation shape absent', n, e['id'])
                            continue
                        xf = shape.find('p:spPr/a:xfrm', NS)
                        off, ext = xf.find('a:off', NS), xf.find('a:ext', NS)
                        box = [int(off.get('x'))/EMU, int(off.get('y'))/EMU,
                               int(ext.get('cx'))/EMU, int(ext.get('cy'))/EMU]
                        if any(abs(a-b) > .2 for a, b in zip(box, e['bbox'])):
                            add('GEOMETRY_MISMATCH', 'Equation box differs from compiled layout',
                                n, e['id'])
                        boxes.append((e['id'], box))
                        xml = ET.tostring(shape, encoding='unicode')
                        if 'oMathPara' not in xml or 'mc:AlternateContent' not in xml:
                            add('FORMULA_MISSING', 'Equation shape carries no OMML payload', n, e['id'])
                        fallback = ''.join(text.text or '' for text in shape.iter(A+'t')).strip()
                        if fallback and fallback != e['plain'].strip():
                            add('FORMULA_FALLBACK_MISMATCH',
                                'Plain fallback differs from the parsed formula', n, e['id'])
                        continue
                    if e['kind'] not in ('text', 'list'):
                        continue
                    shape = actual.get(e['id'])
                    if shape is None:
                        add('MISSING_SHAPE', 'Expected text shape absent', n, e['id'])
                        continue
                    tx = shape.find('p:txBody', NS)
                    body = tx.find('a:bodyPr', NS)
                    c = e['contract']
                    xf = shape.find('p:spPr/a:xfrm', NS)
                    off, ext = xf.find('a:off', NS), xf.find('a:ext', NS)
                    box = [int(off.get('x'))/EMU, int(off.get('y'))/EMU, int(ext.get('cx'))/EMU, int(ext.get('cy'))/EMU]
                    if any(abs(a-b) > .2 for a,b in zip(box, e['bbox'])):
                        add('GEOMETRY_MISMATCH', 'Exported box differs from compiled layout', n, e['id'])
                    boxes.append((e['id'], box))
                    paragraphs = []
                    for p in tx.findall('a:p', NS):
                        paragraphs.append(''.join('\n' if el.tag == A+'br' else (el.text or '')
                                                  for el in p.iter() if el.tag in (A+'t', A+'br')))
                    # A hard break (\n) starts a paragraph; a soft break (\v) is a a:br inside the
                    # paragraph. Comparing flattened text kept the footer's two-line soft break
                    # looking like a text change, so the paragraph structure is compared as written.
                    expected = ([''.join(line if i == 0 else '\n' + line
                                         for i, line in enumerate(item_lines))
                                 for item_lines in e['items']] if e['kind'] == 'list'
                                else [paragraph.replace('\v', '\n')
                                      for paragraph in e['text'].split('\n')])
                    if paragraphs != expected:
                        add('TEXT_MISMATCH', 'Export changed text or line breaks', n, e['id'])
                    if e['kind'] == 'list':
                        marker = e['bullet']
                        gutter = str(round(marker['gutter'] * EMU))
                        for p in tx.findall('a:p', NS):
                            ppr = p.find('a:pPr', NS)
                            char = None if ppr is None else ppr.find('a:buChar', NS)
                            colour = None if ppr is None else ppr.find('a:buClr/a:srgbClr', NS)
                            face = None if ppr is None else ppr.find('a:buFont', NS)
                            if (ppr is None or char is None or char.get('char') != marker['char']
                                    or face is None or face.get('typeface') != marker['face']
                                    or colour is None or colour.get('val') != marker['color'].lstrip('#').upper()
                                    or ppr.get('marL') != gutter or ppr.get('indent') != '-' + gutter):
                                add('LIST_BULLET_MISMATCH', 'Native bullet differs from compiled layout',
                                    n, e['id'])
                                break
                    attrs = {'wrap': 'none', 'anchor': {'top':'t','middle':'ctr','bottom':'b'}[c['vertical_anchor']]}
                    attrs.update({k: str(round(c['inset'][v]*EMU)) for k,v in
                                  [('lIns','left'),('rIns','right'),('tIns','top'),('bIns','bottom')]})
                    if body is None or any(body.get(k) != v for k,v in attrs.items()) or body.find('a:noAutofit', NS) is None:
                        add('TEXT_CONTRACT_MISMATCH', 'Body properties differ from contract', n, e['id'])
                    for p in tx.findall('a:p', NS):
                        if e.get('align'):
                            ppr = p.find('a:pPr', NS)
                            expected_align = {'left': 'l', 'center': 'ctr', 'right': 'r'}[e['align']]
                            if ppr is None or ppr.get('algn') != expected_align:
                                add('TEXT_CONTRACT_MISMATCH', 'Paragraph alignment differs from layout', n, e['id'])
                        default = p.find('a:pPr/a:defRPr', NS)
                        spacing = p.find('a:pPr/a:lnSpc/a:spcPts', NS)
                        if spacing is None or int(spacing.get('val')) != round(c['font_size']*c['line_height']*75):
                            add('LINE_HEIGHT_MISMATCH', 'Exact line spacing differs from contract', n, e['id'])
                        for run in p.findall('a:r', NS):
                            props = run.find('a:rPr', NS)
                            def attr(k):
                                return props.get(k) if props is not None and props.get(k) is not None else default.get(k) if default is not None else None
                            face = props.find('a:latin', NS) if props is not None else None
                            if face is None and default is not None:
                                face = default.find('a:latin', NS)
                            if attr('sz') is None or abs(int(attr('sz'))/75-c['font_size']) > .1 or face is None or face.get('typeface') != c['font_family']:
                                add('FONT_CONTRACT_MISMATCH', 'Run font differs from contract', n, e['id'])
                            if any('\u2e80' <= char <= '\uffef' for char in ''.join(
                                    text.text or '' for text in run.findall('a:t', NS))):
                                east_asian = props.find('a:ea', NS) if props is not None else None
                                if east_asian is None or east_asian.get('typeface') != c['font_family']:
                                    add('EAST_ASIAN_FONT_MISMATCH', 'East Asian font slot differs from contract', n, e['id'])
                if routed:
                    fallback = next((a['region'] for a in slide.get('adaptation_log', [])
                                     if a.get('action') == 'native_graphic'), [0, 0, *layout['slide_size']])
                    for graphic_id in dict.fromkeys(e['graphic_id'] for e in routed):
                        edges = [e for e in routed if e['graphic_id'] == graphic_id]
                        nodes = [e for e in native_nodes if e['graphic_id'] == graphic_id]
                        region = edges[0].get('graphic_region', fallback)
                        for rule, message, shape in audit_scene(nodes, edges, region):
                            add(rule, message, n, shape)
                pics = root.findall('p:cSld/p:spTree/p:pic', NS)
                planned_pics = [e for e in slide['elements'] if e['kind'] == 'image']
                if len(pics) != len(planned_pics):
                    add('IMAGE_COUNT_MISMATCH', 'Image count differs from IR', n)
                for pic, e in zip(pics, planned_pics):
                    blip = pic.find('.//a:blip', NS)
                    target = relationships(z, part).get(blip.get('{'+NS['r']+'}embed'), {}).get('target')
                    if target not in z.namelist() or hashlib.sha256(z.read(target)).hexdigest() != layout['assets'][e['asset_id']]['sha256']:
                        add('IMAGE_CONTENT_MISMATCH', 'Evidence image bytes differ from source', n, e['id'])
                    xf = pic.find('p:spPr/a:xfrm', NS)
                    off, ext = xf.find('a:off', NS), xf.find('a:ext', NS)
                    box = [int(off.get('x'))/EMU,int(off.get('y'))/EMU,int(ext.get('cx'))/EMU,int(ext.get('cy'))/EMU]
                    if e.get('role') == 'background':
                        # A full-bleed picture is supposed to sit under everything; counting it as a
                        # collision would reject every page that has a background.
                        continue
                    boxes.append((e['id'], box))
                    if any(abs(a-b) > .2 for a,b in zip(box, e['bbox'])):
                        add('GEOMETRY_MISMATCH', 'Image geometry differs from compiler', n, e['id'])
                actual_elements = [{**planned[name], 'bbox': box} for name, box in boxes if name in planned]
                for edge_id, obstacle_id in graphic_obstacle_collisions(native_paths, actual_elements):
                    add('GRAPHIC_ROUTE_THROUGH_CONTENT', f'Connector crosses page content {obstacle_id}', n, edge_id)
                for idx, (name, box) in enumerate(boxes):
                    x,y,w,h = box
                    if x < -.1 or y < -.1 or x+w > 1280.1 or y+h > 720.1:
                        add('SHAPE_OUT_OF_BOUNDS', 'Actual shape outside slide', n, name)
                    for other, obox in boxes[:idx]:
                        if planned.get(name, {}).get('route') or planned.get(other, {}).get('route'):
                            continue
                        if intentional_overlap(planned.get(name, {}), planned.get(other, {})):
                            continue
                        if intersect(box, obox):
                            add('CRITICAL_COLLISION', f'Actual shape overlaps {other}', n, name)
    except (ValueError, KeyError, AttributeError, zipfile.BadZipFile, ET.XMLSyntaxError) as e:
        add('FILE_INTEGRITY', str(e))
    return items
