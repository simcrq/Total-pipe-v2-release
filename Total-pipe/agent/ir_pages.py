"""Deterministic source binding and measured, independently replaceable IR pages."""
import copy
import json
from pathlib import Path
import tempfile
import re

from . import COMPONENT
from .state import read, write, sha, digest, resources, save


VISUAL_TERMS = {
    'figure': (r'原图|读图|\b(?:paper figure|figure readout|figure reading)\b', '原图导读 图文并排'),
    'chart': (r'曲线图|折线图|散点图|柱状图|数据图|误差棒|\b(?:charts?|(?:line|data) plots?|error bars?)\b', '数据图'),
    'formula': (r'公式|方程|\b(?:equations?|formulas?|inline math)\b', '原生公式 符号定义'),
    'table': (r'表格|对照表|表头|\b(?:tables?|merged headers)\b', '对照表 原生表格'),
    'graphic': (r'机制|流程|示意图|结构图|电路图|\b(?:mechanism|diagram|workflow|flowchart)\b', ''),
}
LAYOUT_RISK = re.compile(r'混排|多栏|图文并排|标注|留白|稀疏|密集|嵌套|新布局|'
                         r'\b(?:annotations?|side.by.side|nested|sparse|dense|new layout)\b', re.I)


def _visual_intent(page):
    """Interpret approved design language without copying Story text into search."""
    from deck_compiler.content_projection import standalone_math
    design = page.get('design', '')
    text = design if isinstance(design, str) else json.dumps(design, ensure_ascii=False)
    objects = {('figure', ref) for ref in page.get('figures', [])}
    objects.update((carrier['kind'], carrier['ref'])
                   for route in page.get('content_map', {}).values() if route.get('destination') == 'visible'
                   for carrier in route.get('carriers', []) if carrier.get('kind') in VISUAL_TERMS)
    kinds = {kind for kind, _ in objects}
    if any(item.get('role') in ('body', 'label') and standalone_math(item.get('text'))
           for item in page.get('display_copy', [])):
        kinds.add('formula')
    kinds.update(kind for kind, (pattern, _) in VISUAL_TERMS.items() if re.search(pattern, text, re.I))
    return text, objects, kinds


def _example_suggestions(page, entries):
    from deck_compiler.example_index import search
    text, _, kinds = _visual_intent(page)
    hints = [hint for kind, (_, hint) in VISUAL_TERMS.items() if kind in kinds and hint]
    if {'chart', 'formula'}.issubset(kinds):
        hints.append('图表公式混排 曲线与公式 多功能同页')
    if re.search(r'机制|\bmechanism\b', text, re.I):
        hints.append('机制图')
    return search(' '.join([text, *hints]), entries, limit=2)


def _preview_reasons(page, errors):
    text, objects, kinds = _visual_intent(page)
    reasons = []
    if len(objects) > 1 or len(kinds) > 1:
        reasons.append('multiple_visuals')
    if kinds.intersection(('chart', 'formula', 'table', 'graphic')):
        reasons.append('compiled_visual')
    if LAYOUT_RISK.search(text):
        reasons.append('layout_or_annotation_risk')
    if errors:
        reasons.append('previous_submission_failed')
    return reasons


def _inventory(work):
    inventory = {}
    pointer = work/'evidence_pointer.json'
    if pointer.is_file():
        workflow = Path(read(pointer)['workflow'])
        for asset in (read(workflow).get('artifacts') or {}).get('figure_assets_metadata', []):
            path = Path(asset.get('path') or asset.get('asset_id', ''))
            path = path if path.is_absolute() else workflow.parent/path
            if path.is_file():
                for key in (asset.get('asset_id'), asset.get('path'), str(path.resolve())):
                    if key: inventory[str(key)] = str(path.resolve())
    return inventory


def resolve_design_sources(design, work):
    design = copy.deepcopy(design)
    inventory = _inventory(work)
    for page in design.get('pages', []):
        page['figures'] = [inventory.get(selected, selected) for selected in page.get('figures', [])]
        if design.get('schema_version') in ('1.2', '1.3'):
            if design.get('schema_version') == '1.3':
                page['figure_sources'] = {inventory.get(ref, ref): meta for ref, meta in page.get('figure_sources', {}).items()}
            for route in page.get('content_map', {}).values():
                for carrier in route.get('carriers', []):
                    if carrier.get('kind') == 'figure':
                        carrier['ref'] = inventory.get(carrier['ref'], carrier['ref'])
    return design


def bind_sources(value, design, work, authored_path):
    """Copy approved text/provenance; never infer a claim, value or figure number."""
    value = copy.deepcopy(value)
    inventory = _inventory(work)
    def resolve(path):
        return inventory.get(path, str((Path(authored_path).parent/Path(path)).resolve()))
    pages = {p['id']: p for p in (design or {}).get('pages', [])}
    assets = value.setdefault('assets', {})
    for index, slide in enumerate(value.get('slides', [])):
        page = pages.get(slide.get('id'))
        if page and (design or {}).get('schema_version') in ('1.2', '1.3'):
            from deck_compiler.content_projection import bind_copy, snapshot, standalone_math
            slide = bind_copy(slide, page)
            value['slides'][index] = slide
            expected = snapshot(page, design['_content_catalog'], design['_review'])
            actual = slide.get('semantic', {}).get('content_projection')
            if actual is not None and actual != expected:
                raise ValueError('The approved audience projection changed; replan the page design and source/copy review.')
            slide.setdefault('semantic', {})['content_projection'] = expected
            supplements = {item['text']: item for item in page['display_copy'] if item.get('basis') == 'supplement'}
            equations = {item['text']: standalone_math(item['text']) for item in page['display_copy']
                         if item['role'] in ('body', 'label') and item.get('basis', 'paper') == 'paper'}
            for block in slide.get('composition', {}).get('blocks', []):
                expression = equations.get(block.get('text'))
                if expression is not None and block.get('component') in ('body', 'formula'):
                    block['text'] = expression
                    block['component'] = 'formula'
                    block.pop('inline_math', None)
                supplement = supplements.get(block.get('text'))
                if supplement:
                    if block.get('basis', 'supplement') != 'supplement' or block.get('evidence_refs'):
                        raise ValueError('Approved supplementary copy must stay in the supplement channel.')
                    block['basis'], block['supplement'] = 'supplement', copy.deepcopy(supplement['supplement'])
        sem = slide.get('semantic')
        if page and isinstance(sem, dict):
            items = [*(page.get('items') or []), *(page.get('context_items') or [])]
            if 'evidence_refs' not in sem:
                sem['evidence_refs'] = list(dict.fromkeys(ref for item in items for ref in item.get('evidence', [])))
            notes = sem.get('speaker_notes', '')
            for item in items:
                text = item.get('text', '')
                source = item.get('source', item.get('id', 'Story'))
                identity = ' ['+item['epistemic']+']' if item.get('epistemic') else ''
                record = source+identity+': '+text
                if text and (record not in notes if identity else text not in notes):
                    notes += '\n\n'+record
            sem['speaker_notes'] = notes.strip()
            if page.get('production_notes'):
                sem['run_notes'] = list(dict.fromkeys([*sem.get('run_notes', []), *page['production_notes']]))
        for figure in slide.get('composition', {}).get('figure_refs', []):
            aid = figure.get('asset_id')
            if not isinstance(aid, str): continue
            if aid not in assets and aid in inventory:
                assets[aid] = {'path': inventory[aid], 'origin': 'paper'}
            asset = assets.get(aid)
            if not isinstance(asset, dict): continue
            if isinstance(asset.get('path'), str):
                asset['path'] = resolve(asset['path'])
            if page and (design or {}).get('schema_version') == '1.3':
                manifest = page.get('figure_sources', {})
                meta = manifest.get(aid) or manifest.get(asset.get('path'))
                if not meta:
                    raise ValueError(f'{aid}: no inspected figure identity in the approved design')
                figure_id = meta['source_figure']
                for obj in (asset, figure):
                    if obj.get('source_figure', figure_id) != figure_id:
                        raise ValueError(f'{aid}: IR figure identity conflicts with inspected source')
                    obj['source_figure'] = figure_id
                from deck_compiler.scientific_numbers import figure_source_label
                label = figure_source_label(figure_id, figure.get('caption', ''))
                if figure.get('source_label', label) != label:
                    raise ValueError(f'{aid}: use the bound visible source label, not scientific prose in metadata')
                figure['source_label'] = label
            if asset.get('origin', 'paper') == 'paper':
                # A declared paper ID may be copied, but never guessed from a filename.
                if 'source_figure' not in asset and figure.get('source_figure'):
                    asset['source_figure'] = figure['source_figure']
                if 'source_figure' not in figure and asset.get('source_figure'):
                    figure['source_figure'] = asset['source_figure']
            if isinstance(asset.get('crop'), dict) and asset['crop'].get('source_path'):
                source = resolve(asset['crop']['source_path'])
                asset['crop']['source_path'] = source
                if 'source_sha256' not in asset['crop'] and Path(source).is_file():
                    asset['crop']['source_sha256'] = sha(source)
    return value


def _filename(sid):
    return (sid if re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', sid) else 'page-'+digest(sid)[:16])+'.json'


def prepare_prompts(work, design, prompt):
    """Complete page-specific science and shared contracts, rather than the whole deck every time."""
    if design.get('schema_version') not in ('1.1', '1.2', '1.3'): return
    from deck_compiler.design import bind_design
    design = bind_design(design, prompt['story'])
    shared = {k: prompt[k] for k in ('instructions', 'archetypes', 'components', 'capabilities', 'example_lookup',
              'type_scale', 'visual_style', 'design_forms', 'design_devices', 'request', 'workflow_root') if k in prompt}
    entries = []
    if 'example_lookup' in shared:
        from deck_compiler.example_index import inventory
        try:
            entries = inventory()
        except (OSError, ValueError, KeyError, TypeError):
            pass  # The library is optional for IR authoring.
    for page in design['pages']:
        refs = {ref for item in [*page.get('items', []), *page.get('context_items', [])] for ref in item.get('evidence', [])}
        nodes = {int(item['source'].split('.')[0][1:])-1 for item in page.get('items', [])
                 if re.match(r'^S\d+\.', item.get('source', ''))}
        ledger = prompt.get('story', {}).get('content_contract', {})
        if ledger.get('version') == '2.0':
            selected = {item['source'] for item in [*page.get('items', []), *page.get('context_items', [])]}
            nodes = {int(path.split('.')[0][1:])-1 for path, refs in ledger['narrative_map'].items()
                     if re.match(r'^S\d+\.', path) and selected.intersection(refs)}
        if any(item.get('source', '').startswith('ending.') for item in page.get('items', [])):
            nodes = set(range(len(prompt.get('story', {}).get('story', []))))
        value = {**shared, 'schema_path': str(COMPONENT/'schemas/deck-ir.schema.json'),
                 'page_design': page, 'setting': design.get('setting'),
                 'core_question': prompt.get('story', {}).get('core_question'),
                 'main_message': prompt.get('story', {}).get('main_message'),
                 'story_context': [node for i, node in enumerate(prompt.get('story', {}).get('story', [])) if i in nodes],
                 'evidence': {key: text for key, text in prompt.get('evidence', {}).items() if key in refs},
                 'figures': [f for f in prompt.get('figures', []) if f.get('path') in page.get('figures', []) or f.get('asset_id') in page.get('figures', [])],
                 'page_contract': 'Read this complete pack and the complete schema. Write canonical Deck IR with one slide of this page ID and a shared header identical across pages. Only assigned content_refs are allocated here; other Story context is background. Omitted notes/evidence refs are copied from assigned Story items. Use inventory asset IDs/paths or absolute custom asset paths. Submit deck_ir_page to measure; retain passing pages.'}
        if 'example_lookup' in shared:
            value['example_lookup'] = {**shared['example_lookup'],
                                       'suggestions': _example_suggestions(page, entries)}
        path = work/'ir_page_prompts'/_filename(page['id'])
        if not path.is_file() or read(path) != value: write(path, value)


def descriptor(job, upstream):
    from .ir_preview import authoring_plan
    work = Path(job['request']['out_dir'])/'work'
    if not (work/'page_design.json').is_file(): return None
    design = read(work/'page_design.json')
    cache = job.get('ir_pages', {})
    if cache.get('upstream') != upstream:
        cache = {}
    pages = []
    for page in design['pages']:
        sid = page['id']
        name = _filename(sid)
        output = str(work/'pages'/name)
        cached = sid in cache.get('records', {})
        entry = {'id': sid, 'expected_output': output,
                 'input_path': str(work/'ir_page_prompts'/name), 'cached': cached}
        if not cached and design.get('schema_version') in ('1.1', '1.2', '1.3'):
            reasons = _preview_reasons(page, cache.get('errors', {}).get(sid))
            if reasons:
                entry['preview_plan'] = authoring_plan(job['job_id'], output, sid, reasons)
        pages.append(entry)
    return {'artifact_kind': 'deck_ir_page', 'schema_path': str(COMPONENT/'schemas/deck-ir.schema.json'),
            'contract': 'Canonical Deck IR with exactly one slide; common header must match across pages. Story notes/omitted refs and selected asset paths are bound automatically.',
            'checks_before_submission': 'For pages with preview_plan, write the draft and follow its preview calls before submission. Other pages can use the same preview interface as needed.',
            'max_rejected_revisions_per_page': 3, 'pages': pages}


def _stamp(path):
    from .repair import resource_snapshot
    return digest(resource_snapshot(Path(path)))


def submit(job, upstream, path, dry=False):
    from . import adapters as a
    from deck_compiler.pipeline import compile_input
    work = Path(job['request']['out_dir'])/'work'
    design = a.load_design(work)
    if not design or design.get('schema_version') not in ('1.1', '1.2', '1.3'):
        raise ValueError('Per-page IR requires an approved page_design 1.1/1.2.')
    authored_sha = sha(path)
    value = bind_sources(read(path), design, work, path)
    if len(value.get('slides', [])) != 1:
        raise ValueError('deck_ir_page requires exactly one slide in canonical Deck IR.')
    sid = value['slides'][0].get('id')
    page = next((p for p in design['pages'] if p['id'] == sid), None)
    if page is None: raise ValueError('Page ID is not in the approved page design.')
    partial = {**design, 'pages': [page], '_partial': True}
    header = {k: v for k, v in value.items() if k not in ('slides', 'assets')}
    cache = copy.deepcopy(job.get('ir_pages', {}))
    if cache.get('upstream') != upstream:
        cache = {'upstream': upstream, 'records': {}, 'attempts': {}, 'errors': {}}
    issues = []
    if cache.get('header') is not None and cache['header'] != header:
        issues.append({'code': 'PAGE_HEADER_MISMATCH', 'severity': 'FAIL',
                       'message': 'Shared theme/deck presentation changed. Keep the header or explicitly replan_from=deck_ir to reset all pages.'})
    value, _ = a.apply_art_direction(value, partial)
    value = a.normalize_authoring_ir(value)
    issues.extend(a.ir_issues(value, read(work/'normalized_content.json') if (work/'normalized_content.json').is_file() else None,
                             job['request'].get('supplement', 'off'), partial, 1))
    fingerprint = digest([value, {a['path']: sha(a['path']) for a in value.get('assets', {}).values() if a.get('path')}])
    attempts = cache['attempts'].setdefault(sid, [])
    record = cache['records'].get(sid)
    reusable = False
    if record and Path(record['path']).is_file():
        try: reusable = record['content'] == digest(value) and record['stamp'] == _stamp(record['path'])
        except (OSError, ValueError): pass
    if not dry and not reusable and len(attempts) >= 3:
        return {'status': 'revision_limit', 'page_id': sid, 'issues': cache['errors'].get(sid, []), 'candidate_unchanged': True}, False
    geometry = reusable
    if reusable:
        issues.extend(record.get('measurement_issues', []))
    if not reusable:
        with tempfile.TemporaryDirectory(prefix='totalpipe-ir-page-') as temporary:
            folder = Path(temporary)
            try:
                a.persist_ir(value, path, folder/'input.json')
                before = _stamp(folder/'input.json')
                _, _, qa = compile_input(folder/'input.json', folder, {'name': 'packer'},
                                         enable_overflow_repair=False, require_visual_design=False, explain_viz_mode='off')
                issues.extend(qa['items'])
                geometry = qa['checks'].get('geometric', False)
                if before != _stamp(folder/'input.json') or sha(path) != authored_sha:
                    issues.append({'code': 'PAGE_INPUT_STALE', 'severity': 'FAIL', 'message': 'Page input or resources changed during measurement; retry.'})
            except (OSError, ValueError, KeyError, TypeError) as error:
                issues.append({'code': 'PAGE_MEASUREMENT_FAILED', 'severity': 'FAIL', 'message': str(error)})
    failures = [i for i in issues if i.get('severity', 'FAIL') == 'FAIL']
    result = {'status': 'FAIL' if failures else 'PASS', 'page_id': sid, 'issues': issues,
              'counts': {level: sum(i.get('severity', 'FAIL') == level for i in issues) for level in ('FAIL', 'WARNING', 'REVIEW', 'INFO')},
              'geometry_checked': geometry, 'reused_measurement': reusable, 'candidate_unchanged': True}
    if dry: return result, False
    if failures:
        if fingerprint not in attempts and not any(i.get('code') == 'PAGE_INPUT_STALE' for i in failures): attempts.append(fingerprint)
        cache['errors'][sid] = issues
        job['ir_pages'] = cache
        save(job)
        return result, False
    if not reusable:
        target = work/'ir_pages'/_filename(sid)
        a.persist_ir(value, path, target)
        cache['records'][sid] = {'path': str(target), 'content': digest(value), 'stamp': _stamp(target), 'measurement_issues': issues}
    cache.setdefault('header', header)
    cache['errors'].pop(sid, None)
    job['ir_pages'] = cache
    save(job)
    ordered = [p['id'] for p in design['pages']]
    missing = [pid for pid in ordered if pid not in cache['records']]
    result['pending_pages'] = missing
    if missing: return result, False
    missing = []
    for pid in ordered:
        record = cache['records'].get(pid)
        try: valid = record and record['stamp'] == _stamp(record['path'])
        except (OSError, ValueError): valid = False
        if not valid: missing.append(pid)
    result['pending_pages'] = missing
    if missing: return result, False
    assembled = {**copy.deepcopy(header), 'assets': {}, 'slides': []}
    for pid in ordered:
        part = read(cache['records'][pid]['path'])
        for aid, asset in part.get('assets', {}).items():
            if aid in assembled['assets'] and assembled['assets'][aid] != asset:
                result.update(status='FAIL', issues=[{'code': 'PAGE_ASSET_CONFLICT', 'severity': 'FAIL',
                              'message': f'Asset {aid} has conflicting definitions across pages.'}])
                return result, False
            assembled['assets'][aid] = asset
        assembled['slides'].extend(part['slides'])
    assembled, _ = a.apply_art_direction(assembled, design)
    full = a.ir_issues(assembled, read(work/'normalized_content.json') if (work/'normalized_content.json').is_file() else None,
                       job['request'].get('supplement', 'off'), design, job['request'].get('slide_count'))
    if full:
        result.update(status='FAIL', issues=full, pending_pages=[])
        return result, False
    a.persist_ir(assembled, work/'deck_ir.json', work/'deck_ir.json')
    result['assembled'] = True
    result.pop('candidate_unchanged', None)
    return result, True
