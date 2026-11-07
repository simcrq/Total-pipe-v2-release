"""Isolated, page-cached rendering for IR authoring, never candidate/native evidence."""
import copy
from pathlib import Path
import tempfile

from . import COMPONENT
from .state import confined, digest, read, sha, write


SCHEMA = COMPONENT/'agent/schemas/ir-preview.schema.json'


def descriptor():
    return {'schema_path': str(SCHEMA), 'renderer': 'officecli-html',
            'instruction': 'Call advance(preview={artifact_path, slide_ids}) on draft IR, open each returned PNG, '
                           'revise the source IR and repeat. This does not accept IR, consume revisions, '
                           'change the candidate or attest PowerPoint review.'}


def validate_request(request):
    if (not isinstance(request, dict) or set(request)-{'artifact_path', 'slide_ids'} or
            not isinstance(request.get('artifact_path'), str) or
            not Path(request['artifact_path']).is_absolute()):
        raise ValueError('preview requires an absolute artifact_path and optional slide_ids.')
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
    design = a.load_design(work)
    value = bind_sources(read(path), design, work, path)
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
    runtime = officecli.preflight(connectors=True, tables=True)
    pages = []
    for slide in slides:
        if slide['id'] not in selected:
            continue
        sid = slide['id']
        partial = copy.deepcopy(design)
        if partial:
            partial['pages'] = [p for p in partial['pages'] if p['id'] == sid]
            partial['_partial'] = True
            if not partial['pages']:
                raise ValueError(f'Preview slide {sid} is not in the approved page design.')
        page = {**copy.deepcopy(value), 'slides': [copy.deepcopy(slide)]}
        used = {ref.get('asset_id') for ref in slide.get('composition', {}).get('figure_refs', [])}
        page['assets'] = {aid: asset for aid, asset in value.get('assets', {}).items() if aid in used}
        page, _ = a.apply_art_direction(page, partial)
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
                      'design': partial, 'normalized': normalized,
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
        if layout:
            # A debug picture may show a failed layout. The FAIL remains; it is never accepted.
            target = [s for s in layout['slides'] if s['id'] == sid]
            if len(target) != 1:
                raise ValueError('Compiled preview cannot identify exactly one requested page.')
            write(folder/'preview-layout.json', {**layout, 'slides': target})
            officecli.render(folder/'preview-layout.json', folder/'preview.pptx')
            officecli._run('officecli', 'view', folder/'preview.pptx', 'screenshot',
                           '--render', 'html', '--page', '1', '--out', folder/'slide.png', timeout=90)
            from PIL import Image
            with Image.open(folder/'slide.png') as picture:
                picture.verify()
            png = str(folder/'slide.png')
            outputs += ['layout.json', 'preview-layout.json', 'preview.pptx', 'slide.png']
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
        result = {'slide_id': sid, 'cache_key': key, 'renderer': 'officecli-html',
                  'status': 'FAIL' if _counts(issues)['FAIL'] else 'PASS', 'issues': issues,
                  'counts': _counts(issues), 'png': png,
                  'qa_report': str(folder/'preview_qa.json'), 'feedback_path': str(folder/'layout_feedback.json'),
                  'files': {name: sha(folder/name) for name in outputs}}
        write(folder/'preview.json', result)
        pages.append({**result, 'reused': False})
    if sha(path) != source_sha:
        raise ValueError('Preview source changed during rendering; retry.')
    return {'status': 'FAIL' if any(p['status'] == 'FAIL' for p in pages) else 'PASS',
            'source_sha256': source_sha, 'renderer': 'officecli-html', 'pages': pages,
            'job_unchanged': True, 'candidate_unchanged': True, 'powerpoint_ui_review': False,
            'note': 'Open the returned PNGs before revising. HTML previews can differ from PowerPoint '
                    'in fonts, equations and shapes; isolated page numbers restart and generated agenda pages are omitted. '
                    'Complete Design, full build/QA and native acceptance remain required.'}
