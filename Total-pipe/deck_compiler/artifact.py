"""Finalization and structural verification of the actual exported package."""
from pathlib import Path
import zipfile
from lxml import etree as ET
from .contracts import issue, TextBoxContract
from .layout import intersect
from .ooxml import NS, slide_parts, relationships, background

A = '{' + NS['a'] + '}'
EMU = 9525


def finalize(candidate, staging, layout):
    """Set explicit body/paragraph properties; no font substitution or content edits."""
    with zipfile.ZipFile(candidate) as z:
        parts = slide_parts(z)
        if len(parts) != len(layout['slides']):
            raise ValueError('Renderer changed slide count')
        replacements = {}
        for part, planned in zip(parts, layout['slides']):
            root = ET.fromstring(z.read(part))
            expected = {e['id']: e for e in planned['elements'] if e['kind'] == 'text'}
            found = set()
            for shape in root.findall('.//p:sp', NS):
                name = shape.find('p:nvSpPr/p:cNvPr', NS).get('name')
                if name not in expected:
                    continue
                found.add(name)
                c = TextBoxContract(**expected[name]['contract'])
                tx = shape.find('p:txBody', NS)
                body = tx.find('a:bodyPr', NS)
                if body is None:
                    body = ET.Element(A+'bodyPr')
                    tx.insert(0, body)
                body.set('wrap', 'square' if c.wrap else 'none')
                body.set('anchor', {'top': 't', 'middle': 'ctr', 'bottom': 'b'}[c.vertical_anchor])
                for key, value in c.inset.items():
                    body.set({'left': 'lIns', 'right': 'rIns', 'top': 'tIns', 'bottom': 'bIns'}[key], str(round(value*EMU)))
                for node in list(body):
                    if node.tag in (A+'noAutofit', A+'normAutofit', A+'spAutoFit'):
                        body.remove(node)
                ET.SubElement(body, A+'noAutofit')
                for paragraph in tx.findall('a:p', NS):
                    props = paragraph.find('a:pPr', NS)
                    if props is None:
                        props = ET.Element(A+'pPr')
                        paragraph.insert(0, props)
                    for tag in ('lnSpc', 'spcBef', 'spcAft'):
                        old = props.find('a:'+tag, NS)
                        if old is not None:
                            props.remove(old)
                    # Place spacing before default run properties (OOXML sequence).
                    for idx, (tag, val) in enumerate((('lnSpc', round(c.font_size*c.line_height*75)), ('spcBef', 0), ('spcAft', 0))):
                        spacing = ET.Element(A+tag)
                        ET.SubElement(spacing, A+'spcPts', val=str(val))
                        props.insert(idx, spacing)
            if found != set(expected):
                raise ValueError(f'Renderer lost text identities: {set(expected)-found}')
            replacements[part] = ET.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
        with zipfile.ZipFile(staging, 'w', zipfile.ZIP_DEFLATED) as out:
            for info in z.infolist():
                out.writestr(info, replacements.get(info.filename, z.read(info.filename)))


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
            parts = slide_parts(z)
            if len(parts) != len(layout['slides']):
                add('SLIDE_COUNT_MISMATCH', 'Slide count differs from IR')
            presentation = ET.fromstring(z.read('ppt/presentation.xml'))
            size = presentation.find('p:sldSz', NS)
            if any(abs(int(size.get(k))/EMU-v) > .1 for k, v in zip(('cx', 'cy'), layout['slide_size'])):
                add('CANVAS_MISMATCH', 'Canvas differs from compiled layout')
            for n, (part, slide) in enumerate(zip(parts, layout['slides']), 1):
                root = ET.fromstring(z.read(part))
                bg, source = background(z, part)
                if bg is None:
                    add('BACKGROUND_UNRESOLVED', source, n, severity='REVIEW', confidence='LOW')
                elif bg.upper() != slide['background'].upper():
                    add('BACKGROUND_MISMATCH', f'{bg} != {slide["background"]}', n)
                shapes = root.findall('p:cSld/p:spTree/p:sp', NS)
                actual = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s for s in shapes}
                boxes = []
                for e in slide['elements']:
                    if e['kind'] != 'text':
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
                    if '\n'.join(paragraphs) != e['text']:
                        add('TEXT_MISMATCH', 'Export changed text or line breaks', n, e['id'])
                    attrs = {'wrap': 'none', 'anchor': {'top':'t','middle':'ctr','bottom':'b'}[c['vertical_anchor']]}
                    attrs.update({k: str(round(c['inset'][v]*EMU)) for k,v in
                                  [('lIns','left'),('rIns','right'),('tIns','top'),('bIns','bottom')]})
                    if body is None or any(body.get(k) != v for k,v in attrs.items()) or body.find('a:noAutofit', NS) is None:
                        add('TEXT_CONTRACT_MISMATCH', 'Body properties differ from contract', n, e['id'])
                    for p in tx.findall('a:p', NS):
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
                pics = root.findall('p:cSld/p:spTree/p:pic', NS)
                planned_pics = [e for e in slide['elements'] if e['kind'] == 'image']
                if len(pics) != len(planned_pics):
                    add('IMAGE_COUNT_MISMATCH', 'Image count differs from IR', n)
                for pic, e in zip(pics, planned_pics):
                    blip = pic.find('.//a:blip', NS)
                    target = relationships(z, part).get(blip.get('{'+NS['r']+'}embed'), {}).get('target')
                    import hashlib
                    if target not in z.namelist() or hashlib.sha256(z.read(target)).hexdigest() != layout['assets'][e['asset_id']]['sha256']:
                        add('IMAGE_CONTENT_MISMATCH', 'Evidence image bytes differ from source', n, e['id'])
                    xf = pic.find('p:spPr/a:xfrm', NS)
                    off, ext = xf.find('a:off', NS), xf.find('a:ext', NS)
                    box = [int(off.get('x'))/EMU,int(off.get('y'))/EMU,int(ext.get('cx'))/EMU,int(ext.get('cy'))/EMU]
                    boxes.append((e['id'], box))
                    if any(abs(a-b) > .2 for a,b in zip(box, e['bbox'])):
                        add('GEOMETRY_MISMATCH', 'Image geometry differs from compiler', n, e['id'])
                for idx, (name, box) in enumerate(boxes):
                    x,y,w,h = box
                    if x < -.1 or y < -.1 or x+w > 1280.1 or y+h > 720.1:
                        add('SHAPE_OUT_OF_BOUNDS', 'Actual shape outside slide', n, name)
                    for other, obox in boxes[:idx]:
                        if intersect(box, obox):
                            add('CRITICAL_COLLISION', f'Actual shape overlaps {other}', n, name)
    except (ValueError, KeyError, AttributeError, zipfile.BadZipFile, ET.XMLSyntaxError) as e:
        add('FILE_INTEGRITY', str(e))
    return items
