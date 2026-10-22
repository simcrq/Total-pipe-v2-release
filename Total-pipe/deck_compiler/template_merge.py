"""Place compiled slides inside a lab template package.

A compiled deck is a self-contained package: its own master, its own theme, its own slide size. A
lab template is the opposite: one master with the university logo, the red footer band and the slide
number, and blank layouts that carry no placeholders. This module joins them at the OOXML level
rather than rebuilding shapes through a CLI, because a compiled slide carries things a typed API
cannot reproduce: OMML equations, exact line spacing, per-run East Asian font slots.

The rules are deliberately narrow:

* the template's package, master, theme and media are the base; nothing is re-rendered;
* a compiled slide keeps its bytes, gains the template's blank layout relationship, and is inserted
  before the template's closing slide;
* every media part is deduplicated by SHA-256, so ten slides that share one figure carry one image;
* each inserted slide gets the template's slide-number field, so page numbers continue the template's
  own sequence;
* template slides named in ``drop`` are removed together with their notes and relationships.
"""
from __future__ import annotations

import hashlib
import posixpath
import re
import shutil
import zipfile
from pathlib import Path

from lxml import etree

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
NS = {'p': P, 'r': R, 'a': A}
SLIDE_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide'
NOTES_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide'
LAYOUT_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout'
NOTES_MASTER_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster'
SLIDE_CT = 'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'
NOTES_CT = 'application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml'

SLIDE_NUMBER_FRAME = """
<p:sp xmlns:p="{p}" xmlns:a="{a}">
  <p:nvSpPr><p:cNvPr id="{ident}" name="slide-number" /><p:cNvSpPr txBox="1" /><p:nvPr /></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}" /><a:ext cx="{cx}" cy="{cy}" /></a:xfrm>
    <a:prstGeom prst="rect"><a:avLst /></a:prstGeom><a:noFill /><a:ln><a:noFill /></a:ln></p:spPr>
  <p:txBody><a:bodyPr wrap="none" anchor="ctr" /><a:lstStyle /><a:p><a:pPr algn="r" />
    <a:fld id="{{8B5C1F4E-5A24-4D6E-9C0B-6B7A9F2E4D31}}" type="slidenum">
      <a:rPr lang="en-US" sz="1600" b="1"><a:solidFill><a:srgbClr val="FFFFFF" /></a:solidFill>
        <a:latin typeface="Arial" /></a:rPr><a:t>{number}</a:t></a:fld>
    <a:endParaRPr lang="en-US" /></a:p></p:txBody>
</p:sp>
"""


def _rels_path(part):
    directory, name = posixpath.split(part)
    return posixpath.join(directory, '_rels', name + '.rels')


def _read_rels(parts, part):
    name = _rels_path(part)
    if name not in parts:
        return etree.Element('{%s}Relationships' % REL, nsmap={None: REL})
    return etree.fromstring(parts[name])


def _target(part, target):
    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))


def _relative(part, absolute):
    return posixpath.relpath(absolute, posixpath.dirname(part))


def _slide_number(ident, number, width=1280, height=720):
    # Same rectangle as the template layouts' slide-number placeholder (1209,683 71x38), so the
    # field lands on the red band exactly where the template's own numbers sit.
    return SLIDE_NUMBER_FRAME.format(
        p=P, a=A, ident=ident, number=number,
        x=int((width - 71) * 9525), y=int((height - 37) * 9525),
        cx=int(71 * 9525), cy=int(38 * 9525))


def merge(template, deck, output, keep=(1, 2, 9), layout_name='2_标题幻灯片'):
    """Insert every slide of ``deck`` into ``template`` before its closing slide.

    ``keep`` names the template slides to retain (1-based, in template order). The compiled slides
    go in before the last retained slide, which is the template's closing page. Returns a manifest.
    """
    template, deck, output = Path(template), Path(deck), Path(output)
    with zipfile.ZipFile(template) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    with zipfile.ZipFile(deck) as archive:
        source = {name: archive.read(name) for name in archive.namelist()}

    presentation = etree.fromstring(parts['ppt/presentation.xml'])
    pres_rels = _read_rels(parts, 'ppt/presentation.xml')
    rel_map = {rel.get('Id'): rel for rel in pres_rels}
    sld_ids = list(presentation.find('p:sldIdLst', NS))

    def slide_part_of(element):
        return _target('ppt/presentation.xml', rel_map[element.get('{%s}id' % R)].get('Target'))

    existing = [(element, slide_part_of(element)) for element in sld_ids]
    kept = [existing[index - 1] for index in keep if 0 < index <= len(existing)]
    dropped = [item for item in existing if item not in kept]

    # The blank layout: named, not guessed by index. Fall back to the layout of the last kept slide.
    layout_part = next((name for name in parts
                        if name.startswith('ppt/slideLayouts/slideLayout')
                        and name.endswith('.xml')
                        and ('name="%s"' % layout_name) in parts[name].decode('utf-8', 'ignore')),
                       None)
    if layout_part is None:
        kept_rels = _read_rels(parts, kept[-1][1] if kept else 'ppt/slides/slide1.xml')
        layout_rel = next((rel for rel in kept_rels if rel.get('Type') == LAYOUT_TYPE), None)
        if layout_rel is None:
            raise ValueError('The template has no slide layout to inherit')
        layout_part = _target(kept[-1][1], layout_rel.get('Target'))

    media = {}
    for name, data in parts.items():
        if name.startswith('ppt/media/'):
            media.setdefault(hashlib.sha256(data).hexdigest(), name)
    # Names already present in the template decide the numbering of new media parts.
    used_numbers = [int(match.group(1)) for name in media.values()
                    if (match := re.search(r'(\d+)\.\w+$', name))]

    def media_name(data, extension):
        digest = hashlib.sha256(data).hexdigest()
        if digest in media:
            return media[digest]
        start = max(used_numbers + [0]) + 1
        used_numbers.append(start)
        name = 'ppt/media/image%d%s' % (start, extension or '.png')
        parts[name] = data
        media[digest] = name
        return name

    content_types = etree.fromstring(parts['[Content_Types].xml'])
    defaults = {node.get('Extension').lower() for node in content_types.findall('{%s}Default' % CT)}
    overrides = {node.get('PartName') for node in content_types.findall('{%s}Override' % CT)}

    def declare_override(part, content_type):
        node = etree.SubElement(content_types, '{%s}Override' % CT)
        node.set('PartName', '/' + part)
        node.set('ContentType', content_type)
        overrides.add('/' + part)

    next_slide = max([int(m.group(1)) for name in parts
                      if (m := re.match(r'ppt/slides/slide(\d+)\.xml$', name))] or [0]) + 1
    next_notes = max([int(m.group(1)) for name in parts
                      if (m := re.match(r'ppt/notesSlides/notesSlide(\d+)\.xml$', name))] or [0]) + 1
    notes_master = next((name for name in parts
                         if re.match(r'ppt/notesMasters/notesMaster\d+\.xml$', name)), None)
    next_rid = max([int(re.sub(r'\D', '', rel.get('Id')) or 0) for rel in pres_rels] or [0]) + 1

    source_slides = sorted(
        (name for name in source if re.match(r'ppt/slides/slide\d+\.xml$', name)),
        key=lambda name: int(re.search(r'slide(\d+)', name).group(1)))

    inserted = []
    for order, name in enumerate(source_slides, 1):
        number = next_slide + order - 1
        target = 'ppt/slides/slide%d.xml' % number
        xml = etree.fromstring(source[name])
        sp_tree = xml.find('.//p:cSld/p:spTree', NS)
        if sp_tree is None:
            raise ValueError('%s has no shape tree' % name)
        identifiers = [int(node.get('id')) for node in xml.iter('{%s}cNvPr' % P) if node.get('id')]
        sp_tree.append(etree.fromstring(_slide_number(
            max(identifiers + [0]) + 1, number, width=int(1280), height=int(720))))
        parts[target] = etree.tostring(xml, xml_declaration=True, encoding='UTF-8', standalone=True)
        declare_override(target, SLIDE_CT)

        source_rels = _read_rels(source, name)
        rels = etree.Element('{%s}Relationships' % REL, nsmap={None: REL})
        # The compiled slide's own relationship ids are preserved (its blips reference them), so
        # the layout relationship gets an id the source cannot already use.
        etree.SubElement(rels, '{%s}Relationship' % REL, Id='rIdLayout', Type=LAYOUT_TYPE,
                         Target=_relative(target, layout_part))
        for rel in source_rels:
            kind, rel_target = rel.get('Type'), rel.get('Target')
            if kind == LAYOUT_TYPE:
                # rIdLayout already carries the template's layout; a second slideLayout
                # relationship is what makes the package invalid ("only one instance").
                continue
            new = etree.SubElement(rels, '{%s}Relationship' % REL, Id=rel.get('Id'), Type=kind)
            if kind == NOTES_TYPE:
                note = _target(name, rel_target)
                note_number = next_notes
                next_notes += 1
                note_target = 'ppt/notesSlides/notesSlide%d.xml' % note_number
                parts[note_target] = source[note]
                if note_target not in {node.get('PartName') for node in content_types}:
                    declare_override(note_target, NOTES_CT)
                note_rels = etree.Element('{%s}Relationships' % REL, nsmap={None: REL})
                etree.SubElement(note_rels, '{%s}Relationship' % REL, Id='rId1', Type=SLIDE_TYPE,
                                 Target=_relative(note_target, target))
                if notes_master:
                    etree.SubElement(note_rels, '{%s}Relationship' % REL, Id='rId2',
                                     Type=NOTES_MASTER_TYPE,
                                     Target=_relative(note_target, notes_master))
                parts[_rels_path(note_target)] = etree.tostring(
                    note_rels, xml_declaration=True, encoding='UTF-8', standalone=True)
                new.set('Target', _relative(target, note_target))
            else:
                source_part = _target(name, rel_target)
                if rel.get('TargetMode') == 'External' or source_part not in source:
                    new.set('Target', rel_target)
                    if rel.get('TargetMode'):
                        new.set('TargetMode', rel.get('TargetMode'))
                    continue
                extension = posixpath.splitext(source_part)[1].lower()
                if extension.lstrip('.') not in defaults:
                    defaults.add(extension.lstrip('.'))
                    node = etree.SubElement(content_types, '{%s}Default' % CT)
                    node.set('Extension', extension.lstrip('.'))
                    node.set('ContentType', 'image/%s' % extension.lstrip('.').replace('jpg', 'jpeg'))
                new.set('Target', _relative(target, media_name(source[source_part], extension)))
        parts[_rels_path(target)] = etree.tostring(rels, xml_declaration=True, encoding='UTF-8',
                                                   standalone=True)
        inserted.append({'slide': number, 'source': name,
                         'notes': any(rel.get('Type') == NOTES_TYPE for rel in rels)})

    # Drop the template's placeholder content slides, with their notes and relationships.
    for element, part in dropped:
        rid = element.get('{%s}id' % R)
        sld_list = presentation.find('p:sldIdLst', NS)
        if element in list(sld_list):
            sld_list.remove(element)
        if rid in rel_map:
            pres_rels.remove(rel_map[rid])
        for name in list(parts):
            if name == part or name == _rels_path(part):
                parts.pop(name, None)
            elif name.startswith('ppt/notesSlides/notesSlide'):
                rels = _read_rels(parts, name)
                if any(_target(name, rel.get('Target')) == part for rel in rels):
                    parts.pop(name, None)
                    parts.pop(_rels_path(name), None)

    sld_list = presentation.find('p:sldIdLst', NS)
    closing = sld_list[-1] if len(sld_list) else None
    highest = max([int(item.get('id')) for item in sld_list] or [255])
    for entry in inserted:
        highest += 1
        rid = 'rId%d' % next_rid
        next_rid += 1
        etree.SubElement(pres_rels, '{%s}Relationship' % REL, Id=rid, Type=SLIDE_TYPE,
                         Target='slides/slide%d.xml' % entry['slide'])
        node = etree.SubElement(sld_list, '{%s}sldId' % P)
        node.set('id', str(highest))
        node.set('{%s}id' % R, rid)

    # Presentation order: kept slides, then the compiled ones, then the template's closing page.
    if closing is not None and closing in list(sld_list):
        sld_list.remove(closing)
        sld_list.append(closing)

    parts['ppt/presentation.xml'] = etree.tostring(presentation, xml_declaration=True,
                                                   encoding='UTF-8', standalone=True)
    parts['ppt/_rels/presentation.xml.rels'] = etree.tostring(pres_rels, xml_declaration=True,
                                                              encoding='UTF-8', standalone=True)
    parts['[Content_Types].xml'] = etree.tostring(content_types, xml_declaration=True,
                                                  encoding='UTF-8', standalone=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.pptx.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', parts.pop('[Content_Types].xml'))
        for name, data in parts.items():
            archive.writestr(name, data)
    temporary.replace(output)
    return {'template': str(template), 'deck': str(deck), 'output': str(output),
            'kept_template_slides': [part for _, part in kept],
            'dropped_template_slides': [part for _, part in dropped],
            'inserted': inserted, 'layout': layout_part,
            'slide_count': len(kept) + len(inserted)}
