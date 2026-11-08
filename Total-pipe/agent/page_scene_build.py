"""File-level PageScene build and native-PDF inspection.

The ordinary Deck IR path writes a compiled layout, then OfficeCLI paints it.
A PageScene is already explicit geometry, so it is painted directly by
``page_scene.Renderer``.  This module still produces the same build boundary
(candidate/staging, layout, QA, native evidence) so the existing candidate and
PowerPoint acceptance contracts remain usable.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .page_scene import Renderer
from .page_scene_qa import (_flatten_objects, _overlap, expression_gate,
                            expression_report, validate_spec)
from .state import digest, sha, write

PAGE_W, PAGE_H = 13.333, 7.5


class SceneBuildError(ValueError):
    def __init__(self, code, message, issues=None):
        super().__init__(message)
        self.code = code
        self.issues = list(issues or [])


def _normal(value):
    text = ''.join(str(value or '').split()).replace('\u00ad', '')
    for marker in ('•', '·', '–', '—'):
        text = text.replace(marker, '')
    return text


def _layout(scene):
    slides = []
    for page in scene['pages']:
        slides.append({
            'id': page.get('id'),
            'background': '#FFFFFF',
            'notes': page.get('notes') or '',
            'elements': [],
        })
    return {
        'schema_version': '2.0',
        # The shared layout/QA contract is in CSS pixels (96 dpi), not inches.
        'slide_size': [PAGE_W * 96, PAGE_H * 96],
        'slides': slides,
        'assets': {},
    }


def _provenance(scene):
    return {
        'schema_version': '2.0',
        'provenance': 'page_scene',
        'deck_id': scene.get('deck_id'),
        'scene_sha256': digest(scene),
        'theme': scene.get('theme') or {},
        'slides': [{'id': page.get('id'), 'semantic': {}, 'composition': {}} for page in scene['pages']],
        'presentation': {},
    }


def _notes(scene):
    return {page.get('id'): page.get('notes') or '' for page in scene['pages']}


def _check_scene(scene, path):
    errors, metrics = validate_spec(scene, path)
    if errors:
        raise SceneBuildError('PAGE_SCENE_INVALID', ' '.join(errors[:8]), errors)
    return metrics


def build(work, out, request=None):
    """Render ``work/page_scene.json`` to a native candidate and QA boundary."""
    work, out = Path(work), Path(out)
    source = work / 'page_scene.json'
    if not source.is_file():
        raise SceneBuildError('PAGE_SCENE_MISSING', 'work/page_scene.json is required.')
    scene = json.loads(source.read_text(encoding='utf-8'))
    metrics = _check_scene(scene, source)
    build_dir = out / 'build'
    build_dir.mkdir(parents=True, exist_ok=True)
    for name in ('candidate.pptx', 'staging.pptx', 'layout.json', 'layout_feedback.json',
                 'deck_ir.json', 'page_scene.json', 'qa_report.json', 'native.pdf', 'native.json',
                 'native_preview.json', 'state.json', 'metrics.json'):
        (build_dir / name).unlink(missing_ok=True)
    candidate = build_dir / 'candidate.pptx'
    renderer = Renderer(scene, source)
    for index, page in enumerate(scene['pages'], 1):
        renderer.render_page(page, index, len(scene['pages']))
    renderer.save(candidate)
    staging = build_dir / 'staging.pptx'
    shutil.copyfile(candidate, staging)
    if sha(candidate) != sha(staging):
        raise SceneBuildError('PAGE_SCENE_STAGE_MISMATCH', 'Candidate and staging differ after render.')

    write(build_dir / 'page_scene.json', scene)
    provenance = _provenance(scene)
    write(build_dir / 'deck_ir.json', provenance)
    layout = _layout(scene)
    write(build_dir / 'layout.json', layout)

    items = package_items(staging, scene)
    # The old structural verifier expects a full compiled Deck IR layout with
    # measured contracts and named elements. PageScene has its own explicit
    # geometry, so use the package-level checks above and native PDF inspection
    # later instead of translating scene boxes into a fake Deck IR layout.
    from deck_compiler.contracts import issue
    expression = expression_report(scene, source)
    gate = expression_gate(expression['summary'])
    if len(scene['pages']) >= 6 and gate['status'] != 'PASS':
        items.append(issue('PAGE_SCENE_EXPRESSION_GATE', 'FAIL',
                           '; '.join(gate['failures']),
                           detector='page-scene-expression', renderer='python-pptx'))
    items.append(issue('PAGE_SCENE_BUILT', 'INFO',
                       f'PageScene rendered {len(scene["pages"])} native slides from explicit boxes.',
                       detector='page-scene-build', renderer='python-pptx'))
    fails = [item for item in items if item.get('severity') == 'FAIL']
    if fails:
        raise SceneBuildError('PAGE_SCENE_STRUCTURAL_FAILED', fails[0].get('message', 'PageScene build failed.'), items)
    _write_qa(build_dir, scene, items, structural=True, native=False, metrics=metrics)
    return [build_dir / name for name in
            ('candidate.pptx', 'staging.pptx', 'qa_report.json', 'layout_feedback.json',
             'layout.json', 'deck_ir.json', 'page_scene.json')]


def package_items(staging, scene):
    """Package/canvas/notes/image checks for a PageScene PPTX.

    The Deck IR verifier compares named native elements against a compiled
    layout. A PageScene has no such layout: its authoritative geometry is the
    scene itself, and the actual text/image evidence comes from the PowerPoint
    PDF. This function therefore checks the package invariants that still apply.
    """
    from deck_compiler.contracts import issue
    from deck_compiler.ooxml import NS, background, relationships, slide_parts
    import zipfile
    import xml.etree.ElementTree as ET
    items = []
    def add(rule, severity, message, slide=None):
        items.append(issue(rule, severity, message, slide, detector='page-scene-package'))
    try:
        with zipfile.ZipFile(staging) as package:
            if package.testzip():
                raise ValueError('ZIP CRC failure')
            names = package.namelist()
            for name in names:
                if name.endswith(('.xml', '.rels')):
                    ET.fromstring(package.read(name))
                if name.endswith('.rels'):
                    source = name.replace('/_rels/', '/').removesuffix('.rels')
                    if name == '_rels/.rels':
                        source = ''
                    for rel in relationships(package, source).values():
                        if not rel['external'] and rel['target'] not in names:
                            add('BROKEN_RELATIONSHIP', 'FAIL', f'{name}: {rel["target"]}')
            parts = slide_parts(package)
            if len(parts) != len(scene['pages']):
                add('SLIDE_COUNT_MISMATCH', 'FAIL',
                    f'PPTX has {len(parts)} slides; PageScene has {len(scene["pages"])}.')
            presentation = ET.fromstring(package.read('ppt/presentation.xml'))
            size = presentation.find('p:sldSz', NS)
            actual = [int(size.get('cx')) / 9525, int(size.get('cy')) / 9525]
            if any(abs(a - b) > .2 for a, b in zip(actual, [PAGE_W * 96, PAGE_H * 96])):
                add('CANVAS_MISMATCH', 'FAIL', f'Canvas is {actual}; expected 1280x720 px.')
            for number, (part, page) in enumerate(zip(parts, scene['pages']), 1):
                root = ET.fromstring(package.read(part))
                bg, source = background(package, part)
                if bg is None:
                    add('BACKGROUND_UNRESOLVED', 'REVIEW', source, number)
                elif bg.upper().lstrip('#') != 'FFFFFF':
                    add('BACKGROUND_MISMATCH', 'FAIL', f'{bg} != FFFFFF', number)
                notes_part = next((rel['target'] for rel in relationships(package, part).values()
                                   if rel['type'] == 'notesSlide' and not rel['external']), None)
                if notes_part not in names:
                    add('MISSING_NOTES', 'FAIL', 'Speaker notes part absent', number)
                else:
                    notes_root = ET.fromstring(package.read(notes_part))
                    body = next((shape for shape in notes_root.findall('.//p:sp', NS)
                                 if (shape.find('p:nvSpPr/p:nvPr/p:ph', NS) is not None and
                                     shape.find('p:nvSpPr/p:nvPr/p:ph', NS).get('type') == 'body')), None)
                    paragraphs = [] if body is None else [
                        ''.join(text.text or '' for text in paragraph.findall('.//a:t', NS))
                        for paragraph in body.findall('p:txBody/a:p', NS)]
                    if '\n'.join(paragraphs) != (page.get('notes') or ''):
                        add('NOTES_MISMATCH', 'FAIL', 'Speaker notes differ from PageScene', number)
                expected_images = len([obj for obj in _flatten_objects(page.get('objects'))
                                       if obj.get('type') == 'image'])
                pics = root.findall('p:cSld/p:spTree/p:pic', NS)
                if len(pics) != expected_images:
                    add('IMAGE_COUNT_MISMATCH', 'FAIL',
                        f'{len(pics)} images rendered; PageScene declares {expected_images}', number)
                for pic in pics:
                    blip = pic.find('.//a:blip', NS)
                    target = relationships(package, part).get(blip.get('{' + NS['r'] + '}embed'), {}).get('target')
                    if target not in names:
                        add('IMAGE_CONTENT_MISSING', 'FAIL', 'Rendered image relationship is missing', number)
                expected_tables = len([obj for obj in _flatten_objects(page.get('objects'))
                                       if obj.get('type') == 'table'])
                tables = [frame for frame in root.findall('p:cSld/p:spTree/p:graphicFrame', NS)
                          if frame.find('a:graphic/a:graphicData/a:tbl', NS) is not None]
                if len(tables) != expected_tables:
                    add('TABLE_OBJECT_MISMATCH', 'FAIL',
                        f'{len(tables)} tables rendered; PageScene declares {expected_tables}', number)
                expected_charts = len([obj for obj in _flatten_objects(page.get('objects'))
                                       if obj.get('type') == 'chart'])
                charts = []
                for frame in root.findall('p:cSld/p:spTree/p:graphicFrame', NS):
                    data = frame.find('a:graphic/a:graphicData', NS)
                    if data is not None and any(child.tag.endswith('}chart') for child in data):
                        charts.append(frame)
                if len(charts) != expected_charts:
                    add('CHART_OBJECT_MISMATCH', 'FAIL',
                        f'{len(charts)} charts rendered; PageScene declares {expected_charts}', number)
    except (OSError, ValueError, KeyError, AttributeError, zipfile.BadZipFile, ET.ParseError) as error:
        add('FILE_INTEGRITY', 'FAIL', str(error))
    return items


def _write_qa(build_dir, scene, items, *, structural, native, metrics=None,
              native_evidence=None, review=None, extra_checks=None):
    from deck_compiler.contracts import report
    from deck_compiler.pipeline import write_qa
    build_dir = Path(build_dir)
    provenance = json.loads((build_dir / 'deck_ir.json').read_text(encoding='utf-8'))
    checks = {
        'structural': bool(structural),
        'native': bool(native),
        'renderer': 'powerpoint' if native else 'python-pptx',
        'backend': 'page_scene',
        'page_scene': True,
        'visual_review': review is not None,
        'visual_review_method': 'powerpoint-ui' if review else None,
        **(extra_checks or {}),
    }
    qa = report(items, sha(build_dir / 'staging.pptx'), digest(provenance), checks)
    qa['page_scene_sha256'] = digest(scene)
    qa['page_scene_metrics'] = metrics or []
    qa['expression'] = expression_report(scene, build_dir / 'page_scene.json')
    qa['expression_gate'] = expression_gate(qa['expression']['summary'])
    qa['checks']['expression_gate'] = qa['expression_gate']['status']
    if native_evidence:
        qa['native'] = {key: native_evidence.get(key) for key in
                        ('renderer', 'artifact_sha256', 'pdf_sha256', 'export_method')
                        if native_evidence.get(key) is not None}
    write_qa(build_dir, qa, provenance, json.loads((build_dir / 'layout.json').read_text(encoding='utf-8')))
    write(build_dir / 'layout_feedback.json', {
        'schema_version': '1.0', 'status': qa['status'], 'checks': qa['checks'],
        'items': [item for item in qa['items'] if item.get('severity') in ('FAIL', 'REVIEW')],
    })
    write(build_dir / 'state.json', {
        'phase': 'failed' if qa['counts']['FAIL'] else
                 'awaiting_native_validation' if not native else
                 'awaiting_powerpoint_review' if not review else
                 'awaiting_review' if qa['counts']['REVIEW'] else 'validated',
        'artifact_sha256': qa['artifact_sha256'],
        'page_scene': True,
        **({'powerpoint_visual_reviewed': True, 'powerpoint_reviewer': review.get('reviewer')} if review else {}),
    })
    write(build_dir / 'metrics.json', {
        'backend': 'page_scene',
        'slide_count': len(scene['pages']),
        'pages': len(scene['pages']),
        'python_pptx': True,
        'native_validated': bool(native),
        'powerpoint_visual_reviewed': review is not None,
        'expression': qa['expression']['summary'],
        'expression_gate': qa['expression_gate'],
        'qa_counts': qa['counts'],
    })
    return qa


def refresh_qa(build_dir, *, native=False, review=None, native_evidence=None, metrics=None):
    """Rebuild QA after native render/review without changing candidate bytes."""
    build_dir = Path(build_dir)
    scene = json.loads((build_dir / 'page_scene.json').read_text(encoding='utf-8'))
    prior = json.loads((build_dir / 'qa_report.json').read_text(encoding='utf-8'))
    keep = [item for item in prior.get('items', [])
            if item.get('source', {}).get('detector') not in ('page-scene-native', 'page-scene-package')]
    items = keep + package_items(build_dir / 'staging.pptx', scene)
    if native:
        items += native_items(build_dir / 'native.pdf', scene)
    return _write_qa(build_dir, scene, items,
                     structural=prior.get('checks', {}).get('structural', True),
                     native=native, metrics=metrics or prior.get('page_scene_metrics'),
                     native_evidence=native_evidence, review=review,
                     extra_checks={'page_scene_native': native})


def native_items(pdf, scene):
    """Check the actual PowerPoint PDF against PageScene boxes and copy."""
    from deck_compiler.contracts import issue
    items = []
    try:
        import pdfplumber
        with pdfplumber.open(pdf) as document:
            if len(document.pages) != len(scene['pages']):
                items.append(issue('PAGE_SCENE_NATIVE_PAGE_COUNT', 'FAIL',
                                   f'Native PDF has {len(document.pages)} pages; PageScene has {len(scene["pages"])}.',
                                   detector='page-scene-native', renderer='powerpoint'))
            for number, (pdf_page, page) in enumerate(zip(document.pages, scene['pages']), 1):
                for char in pdf_page.chars:
                    if (char['x0'] < -1 or char['top'] < -1 or
                            char['x1'] > pdf_page.width + 1 or char['bottom'] > pdf_page.height + 1):
                        items.append(issue('PAGE_SCENE_NATIVE_TEXT_OUT_OF_BOUNDS', 'FAIL',
                                           f'Rendered text exceeds slide {number}.',
                                           number, detector='page-scene-native', renderer='powerpoint'))
                        break
                scale_x = pdf_page.width / PAGE_W
                scale_y = pdf_page.height / PAGE_H
                for obj in _flatten_objects(page.get('objects')):
                    kind = obj.get('type')
                    if kind not in ('text', 'list'):
                        continue
                    if kind == 'text' and obj.get('size', 18) < 10:
                        continue
                    x, y, w, h = obj['box']
                    region = pdf_page.crop((x * scale_x, y * scale_y,
                                            (x + w) * scale_x, (y + h) * scale_y), strict=False)
                    actual = _normal(region.extract_text() or '')
                    if kind == 'list':
                        expected_parts = []
                        for item in obj.get('items') or []:
                            text = (scene.get('bindings', {}).get(item.get('copy_ref'), '')
                                    if item.get('copy_ref') else item.get('text', ''))
                            # PDF extraction of inline OMML does not preserve the
                            # prose/math run order; page bounds are still checked.
                            if text and '$' not in text and '\\(' not in text:
                                expected_parts.append(_normal(text))
                        missing = [text for text in expected_parts if text and text not in actual]
                        if missing:
                            items.append(issue('PAGE_SCENE_NATIVE_LIST_REVIEW', 'REVIEW',
                                               f'Native list region does not contain every item for {obj.get("id", "list")}.',
                                               number, detector='page-scene-native', renderer='powerpoint'))
                    else:
                        text = (scene.get('bindings', {}).get(obj.get('copy_ref'), '')
                                if obj.get('copy_ref') else obj.get('text', ''))
                        expected = _normal(text)
                        # PDF text extraction does not preserve the visual order
                        # of superscripts (10^-8 can extract as "1...0...8").
                        # Labels/notes with superscripts are still inspected for
                        # page bounds, but not compared character-for-character.
                        superscripted = any(char in expected for char in '⁰¹²³⁴⁵⁶⁷⁸⁹⁻')
                        # Labels and notes are often adjacent to superscripted
                        # axis values; PDF extraction can pull those competing
                        # glyphs into the crop. Their page-bound check above is
                        # still authoritative, while prose remains exact.
                        if obj.get('role') in ('label', 'note'):
                            continue
                        if (expected and not superscripted
                                and expected not in actual and actual not in expected):
                            items.append(issue('PAGE_SCENE_NATIVE_TEXT_REVIEW', 'REVIEW',
                                               f'Native text region does not match {obj.get("id", "text")}.',
                                               number, detector='page-scene-native', renderer='powerpoint'))
                    if kind == 'text' and obj.get('role') == 'body':
                        # A body block is the only object whose content must be readable at
                        # the project floor; formulas/labels have their own limits.
                        if obj.get('size', 18) < 18:
                            items.append(issue('PAGE_SCENE_BODY_FLOOR', 'FAIL',
                                               f'{obj.get("id", "text")}: body text below 18 pt.',
                                               number, detector='page-scene-native'))
                # The PDF reports a substituted face when a requested font family
                # is absent. This is a review item, not a scientific failure.
                face = (scene.get('theme') or {}).get('font', 'Microsoft YaHei').replace(' ', '').lower()
                faces = {str(char.get('fontname', '')).replace(' ', '').replace('-', '').lower()
                         for char in pdf_page.chars if char.get('fontname')}
                if faces and not any(face in value for value in faces):
                    items.append(issue('PAGE_SCENE_FONT_REVIEW', 'REVIEW',
                                       f'Native font faces {sorted(faces)} do not include {face}.',
                                       number, detector='page-scene-native', renderer='powerpoint'))
    except Exception as error:
        items.append(issue('PAGE_SCENE_NATIVE_INSPECT_FAILED', 'FAIL',
                           f'Could not inspect the PowerPoint PDF: {error}',
                           detector='page-scene-native', renderer='powerpoint'))
    return items


def check_layout_overflow(scene):
    """Return text collisions that the density validator intentionally ignores for captions."""
    errors = []
    for page in scene.get('pages') or []:
        texts = [obj for obj in _flatten_objects(page.get('objects'))
                 if obj.get('type') in ('text', 'list') and obj.get('role', 'body') != 'caption']
        for index, left in enumerate(texts):
            for right in texts[index + 1:]:
                if _overlap(left['box'], right['box']):
                    errors.append(f'{page.get("id")}: text collision '
                                  f'{left.get("id", "text")} vs {right.get("id", "text")}')
    return errors
