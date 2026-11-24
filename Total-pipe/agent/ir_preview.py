"""Isolated, page-cached rendering for IR authoring, never candidate/native evidence."""
import copy
from pathlib import Path
import re
import tempfile

from . import COMPONENT
from .state import confined, digest, read, sha, write

_CJK_SINGLE_RE = re.compile(r'^[\u3400-\u9fff\uf900-\ufaff][，。、；：？！）】》」』”’,.!?;:)]*$')


def _box_overlap(a, b, pad=1.0):
    return not (a[0] + a[2] + pad <= b[0] or b[0] + b[2] + pad <= a[0]
                or a[1] + a[3] + pad <= b[1] or b[1] + b[3] + pad <= a[1])


def build_visual_checklist(slide_layout, issues, capacity_metrics, pixel_ws=None):
    """Structured geometric + pixel visual checklist returned on every IR preview."""
    elements = (slide_layout or {}).get('elements') or []
    orphan_ids = []
    max_bottom = 0.0
    for elem in elements:
        bbox = elem.get('bbox') or [0, 0, 0, 0]
        if elem.get('role') not in ('background', 'footer', 'page_number') and not str(elem.get('id', '')).startswith('page:'):
            max_bottom = max(max_bottom, float(bbox[1]) + float(bbox[3]))
        if elem.get('kind') == 'text':
            lines = [ln.strip() for ln in str(elem.get('text') or '').split('\n') if ln.strip()]
            if len(lines) >= 2 and _CJK_SINGLE_RE.fullmatch(lines[-1]):
                orphan_ids.append(elem.get('id'))
        elif elem.get('kind') == 'list':
            for item_lines in elem.get('items') or []:
                clean = [ln.strip() for ln in item_lines if ln.strip()]
                if len(clean) >= 2 and _CJK_SINGLE_RE.fullmatch(clean[-1]):
                    orphan_ids.append(elem.get('id'))
                    break
    chart_conflicts = [
        item.get('shape') or item.get('rule')
        for item in (issues or [])
        if item.get('severity') == 'FAIL'
        and ('chart:' in str(item.get('shape', '')) or 'chart:' in str(item.get('message', '')))
    ]
    # Perform real geometric overlap audit between chart annotations/ref-labels and bars/reference lines.
    chart_labels = [e for e in elements if e.get('kind') == 'text'
                    and (':annotation:' in str(e.get('id', '')) or ':ref-label:' in str(e.get('id', '')))]
    chart_marks = [e for e in elements if e.get('kind') == 'shape'
                   and any(tag in str(e.get('id', '')) for tag in (':bar:', ':ref:'))]
    for lbl in chart_labels:
        cid = lbl.get('graphic_id')
        for mark in chart_marks:
            if mark.get('graphic_id') != cid:
                continue
            if _box_overlap(lbl['bbox'], mark['bbox'], pad=0.5):
                chart_conflicts.append(f"{lbl['id']} overlaps {mark['id']}")
    ws_info = (capacity_metrics or {}).get('whitespace') or {}
    empty_quads = int(ws_info.get('empty_quadrants', 0)) if isinstance(ws_info, dict) else 0
    pixel_skew = False
    if isinstance(pixel_ws, dict):
        q_ink = pixel_ws.get('quadrant_pixel_ink') or []
        if len(q_ink) == 4 and sum(1 for v in q_ink if v < 0.008) >= 2 and pixel_ws.get('pixel_ink_ratio', 1.0) > 0.01:
            pixel_skew = True
    is_cover = len([e for e in elements if e.get('role') not in ('background', 'title', 'takeaway', 'footer', 'page_number')
                    and not str(e.get('id', '')).startswith('page:')]) == 0
    balance_ok = is_cover or (empty_quads <= 1 and not pixel_skew)
    return {
        'orphan_line_wraps': {'status': 'REVIEW' if orphan_ids else 'PASS', 'elements': orphan_ids},
        'chart_annotation_clearance': {'status': 'FAIL' if chart_conflicts else 'PASS', 'conflicts': chart_conflicts},
        'quadrant_balance': {
            'status': 'PASS' if balance_ok else 'REVIEW',
            'empty_quadrants': empty_quads,
            **({'pixel_ink_ratio': pixel_ws['pixel_ink_ratio'],
                'quadrant_pixel_ink': pixel_ws['quadrant_pixel_ink']} if isinstance(pixel_ws, dict) else {}),
        },
        'footer_clearance': {
            'status': 'PASS' if max_bottom <= 692.0 else 'REVIEW',
            'max_content_bottom_px': round(max_bottom, 1),
        },
    }


SCHEMA = COMPONENT/'agent/schemas/ir-preview.schema.json'


def descriptor():
    return {'schema_path': str(SCHEMA), 'renderer': 'officecli-html',
            'instruction': 'Before accepting a draft, especially a dense, sparse or new layout, call '
                           'advance(preview={artifact_path, slide_ids, mode:"layout"}) and inspect skeleton and '
                           'unit reports. Then use default preview for the actual HTML PNG. This does not accept IR, consume revisions, '
                           'change the candidate or attest PowerPoint review.'}


def _preview_call(job_id, request):
    return {'tool': 'totalpipe_advance', 'arguments': {'job_id': job_id, 'preview': request}}


def authoring_plan(job_id, draft_path, slide_id, reasons):
    """The first preview command for a page, once its draft has been written."""
    request = {'artifact_path': draft_path, 'slide_ids': [slide_id], 'mode': 'layout'}
    return {'reasons': reasons, 'first_call': _preview_call(job_id, request)}


def authoring_follow_up(job_id, request, result):
    """Guide the Agent from measured geometry to a visual check of the draft."""
    pages = result.get('pages', [])
    if result.get('status') == 'FAIL' or not pages:
        return {'type': 'review_preview_failure',
                'instruction': 'Read the preview issues or error. Correct geometry or restore the rendering '
                               'dependency as indicated, then preview again. Report any unavailable preview.'}
    if request.get('mode', 'render') == 'layout':
        return {'type': 'inspect_skeleton',
                'instruction': 'Open the skeleton and unit reports. Check crowding, footer clearance and any '
                               'collision or overflow REVIEW. If you revise the draft, rerun layout before rendering.',
                'next_call': _preview_call(job_id, {**request, 'mode': 'render'})}
    if not all(page.get('png') for page in pages):
        return {'type': 'review_preview_failure',
                'instruction': 'Read the preview feedback for any page without a rendered PNG.'}
    flagged = [
        f"{page['slide_id']}:{check_name}"
        for page in pages
        for check_name, detail in (page.get('visual_checklist') or {}).items()
        if isinstance(detail, dict) and detail.get('status') in ('REVIEW', 'FAIL')
    ]
    return {'type': 'inspect_render',
            'instruction': 'Open the rendered PNGs and follow the approved reading order. Verify the evidence anchor, '
                           'chart marks, formulas, units and conditions. Check clipping, quadrant balance and overlap. '
                           'Revise and re-preview as needed, then submit the draft through the normal IR acceptance step.',
            **({'attention_items': flagged} if flagged else {})}


def validate_request(request):
    if (not isinstance(request, dict) or set(request)-{'artifact_path', 'slide_ids', 'mode'} or
            not isinstance(request.get('artifact_path'), str) or
            not Path(request['artifact_path']).is_absolute()):
        raise ValueError('preview requires an absolute artifact_path and optional slide_ids.')
    if request.get('mode', 'render') not in ('layout', 'render'):
        raise ValueError('preview.mode must be layout or render.')
    if 'slide_ids' in request:
        ids = request['slide_ids']
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 40 or
                not all(isinstance(sid, str) and sid.strip() for sid in ids) or len(set(ids)) != len(ids)):
            raise ValueError('preview.slide_ids must contain 1–40 unique slide IDs.')


def _cached(folder, key):
    try:
        value = read(folder/'preview.json')
        if value['cache_key'] == key and value['files'] and all(
                sha(folder/name) == hashed for name, hashed in value['files'].items()):
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _counts(issues):
    return {level: sum(i.get('severity', 'FAIL') == level for i in issues)
            for level in ('FAIL', 'WARNING', 'REVIEW', 'INFO')}


def execute(job, request):
    """Use the existing scientific/geometry checks; write only disposable work previews."""
    from . import adapters as a
    from .ir_pages import bind_sources
    from .repair import resource_snapshot
    from deck_compiler import officecli
    from deck_compiler.pipeline import compile_input
    validate_request(request)
    work = Path(job['request']['out_dir'])/'work'
    path = confined(request['artifact_path'], work)
    source_sha = sha(path)
    design_draft_mode = False
    try:
        design = a.load_design(work)
    except a.Failure:
        # During merged page_design/page_review co-design, allow single-page IR prototyping
        # and layout/PNG debugging before final source/copy review is signed off.
        design_draft_mode = True
        raw_design = work/'page_design.json'
        design = read(raw_design) if raw_design.is_file() else None
    if design is None and not (work/'page_design.json').is_file():
        design_draft_mode = True
    value = bind_sources(read(path), None if design_draft_mode else design, work, path)
    slides = value.get('slides')
    if not isinstance(slides, list) or not slides or any(not isinstance(s, dict) for s in slides):
        raise ValueError('Preview input must be canonical Deck IR with slides.')
    ids = [s.get('id') for s in slides]
    if any(not isinstance(sid, str) or not sid for sid in ids) or len(set(ids)) != len(ids):
        raise ValueError('Preview input needs unique non-empty slide IDs.')
    selected = request.get('slide_ids', ids)
    if set(selected)-set(ids):
        raise ValueError('Preview requested an unknown slide ID.')
    normalized = read(work/'normalized_content.json') if (work/'normalized_content.json').is_file() else None
    # Include the renderer runtime, compiler sources, resolved fonts and image bytes in cache identity.
    render_pptx = request.get('mode', 'render') == 'render'
    renderer = 'officecli-html' if render_pptx else 'compiler-layout'
    runtime = officecli.preflight(connectors=True, tables=True) if render_pptx else None
    pages = []
    for slide in slides:
        if slide['id'] not in selected:
            continue
        sid = slide['id']
        partial = None
        if design and not design_draft_mode:
            partial = copy.deepcopy(design)
            partial['pages'] = [p for p in partial['pages'] if p['id'] == sid]
            partial['_partial'] = True
            if not partial['pages']:
                raise ValueError(f'Preview slide {sid} is not in the approved page design.')
        elif design and design_draft_mode:
            matched = [p for p in (design.get('pages') or []) if isinstance(p, dict) and p.get('id') == sid]
            if matched and design.get('schema_version') not in ('1.2', '1.3'):
                partial = {**copy.deepcopy(design), 'pages': matched, '_partial': True}
        page = {**copy.deepcopy(value), 'slides': [copy.deepcopy(slide)]}
        used = {ref.get('asset_id') for ref in slide.get('composition', {}).get('figure_refs', [])}
        page['assets'] = {aid: asset for aid, asset in value.get('assets', {}).items() if aid in used}
        page, _ = a.apply_art_direction(page, partial)
        page = a.normalize_authoring_ir(page)
        root = work/'previews'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.prepare-', dir=root) as temp:
            input_path = Path(temp)/'input.json'
            a.persist_ir(page, path, input_path)
            prepared = read(input_path)
            resources = resource_snapshot(input_path)
            resources.pop(str(input_path), None)
            # Unresolved font aliases are relative to this disposable folder; the declared alias
            # stays in prepared IR and the actual resolved fallback font is fingerprinted separately.
            resources = {key: hashed for key, hashed in resources.items() if hashed is not None}
        key = digest({'ir': prepared, 'resources': resources, 'renderer': runtime,
                      'preview_mode': renderer, 'design': partial, 'normalized': normalized,
                      'supplement': job['request'].get('supplement', 'off')})
        folder = root/key
        cached = _cached(folder, key)
        if cached:
            current = resource_snapshot(folder/'input.json')
            current.pop(str(folder/'input.json'), None)
            current = {key: hashed for key, hashed in current.items() if hashed is not None}
            if current != resources or sha(path) != source_sha:
                raise ValueError('Preview source or resources changed while reading the cache; retry.')
            pages.append({**cached, 'reused': True})
            continue
        folder.mkdir(parents=True, exist_ok=True)
        a.persist_ir(prepared, path, folder/'input.json')
        issues = a.ir_issues(prepared, normalized, job['request'].get('supplement', 'off'), partial, 1)
        _, layout, qa = compile_input(folder/'input.json', folder, {'name': 'packer'},
                                     enable_overflow_repair=False, require_visual_design=False, explain_viz_mode='off')
        seen = {(i.get('rule', i.get('code')), i.get('message'), i.get('slide')) for i in issues}
        for item in qa['items']:
            marker = (item.get('rule', item.get('code')), item.get('message'), item.get('slide'))
            if marker not in seen:
                issues.append(item)
                seen.add(marker)
        outputs = ['input.json', 'qa_report.json', 'layout_feedback.json']
        png = None
        diagnostics = {}
        if layout:
            # A debug picture may show a failed layout. The FAIL remains; it is never accepted.
            target = [s for s in layout['slides'] if s['id'] == sid]
            if len(target) != 1:
                raise ValueError('Compiled preview cannot identify exactly one requested page.')
            write(folder/'preview-layout.json', {**layout, 'slides': target})
            from deck_compiler.workshop.skeleton import inspect_page
            metrics = inspect_page(target[0], issues, folder)
            diagnostics = {'skeleton_png': str(folder/'skeleton.png'),
                           'skeleton_report': str(folder/'skeleton_report.json'), 'capacity': metrics}
            outputs += ['layout.json', 'preview-layout.json', 'skeleton.png', 'skeleton_report.json']
            if not render_pptx:
                from deck_compiler.workshop.units import build as inspect_units
                inspect_units(folder/'input.json', folder/'preview-layout.json', folder/'units', verbose=False)
                diagnostics['units_report'] = str(folder/'units_report.md')
                outputs += ['units.json', 'units_report.md']
                outputs += [str(p.relative_to(folder)) for p in sorted((folder/'units').glob('*.png'))]
            pixel_ws = None
            if render_pptx:
                officecli.render(folder/'preview-layout.json', folder/'preview.pptx')
                officecli._run('officecli', 'view', folder/'preview.pptx', 'screenshot',
                               '--render', 'html', '--page', '1', '--out', folder/'slide.png', timeout=90)
                from PIL import Image
                with Image.open(folder/'slide.png') as picture:
                    picture.verify()
                from deck_compiler.whitespace import analyze_rendered_png_whitespace
                pixel_ws = analyze_rendered_png_whitespace(folder/'slide.png')
                diagnostics['pixel_whitespace'] = pixel_ws
                png = str(folder/'slide.png')
                outputs += ['preview.pptx', 'slide.png']
            diagnostics['visual_checklist'] = build_visual_checklist(target[0], issues, metrics, pixel_ws)
        after = resource_snapshot(folder/'input.json')
        after.pop(str(folder/'input.json'), None)
        after = {key: hashed for key, hashed in after.items() if hashed is not None}
        if after != resources or sha(path) != source_sha:
            changed = [key for key in resources.keys() | after.keys() if resources.get(key) != after.get(key)]
            raise ValueError('Preview source, resources or compiler changed during rendering; retry. '
                             +', '.join(changed))
        write(folder/'preview_qa.json', {'counts': _counts(issues), 'items': issues,
                                       'checks': qa['checks'], 'preview_only': True})
        outputs.append('preview_qa.json')
        result = {'slide_id': sid, 'cache_key': key, 'renderer': renderer,
                  'status': 'FAIL' if _counts(issues)['FAIL'] else 'PASS', 'issues': issues,
                  'counts': _counts(issues), 'png': png, **diagnostics,
                  'qa_report': str(folder/'preview_qa.json'), 'feedback_path': str(folder/'layout_feedback.json'),
                  'files': {name: sha(folder/name) for name in outputs}}
        write(folder/'preview.json', result)
        pages.append({**result, 'reused': False})
    if sha(path) != source_sha:
        raise ValueError('Preview source changed during rendering; retry.')
    return {'status': 'FAIL' if any(p['status'] == 'FAIL' for p in pages) else 'PASS',
            'source_sha256': source_sha, 'renderer': renderer, 'pages': pages,
            'design_draft_mode': design_draft_mode,
            'job_unchanged': True, 'candidate_unchanged': True, 'powerpoint_ui_review': False,
            'note': 'Inspect the skeleton and unit diagnostics when planning, then open the actual rendered PNG. HTML previews can differ from PowerPoint '
                    'in fonts, equations and shapes; isolated page numbers restart and generated agenda pages are omitted. '
                    'Complete Design, full build/QA and native acceptance remain required.'}
