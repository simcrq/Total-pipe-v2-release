"""Explicit native acceptance of an existing candidate; never infer a UI review."""
from pathlib import Path
import re
import shutil
import uuid

from . import COMPONENT
from .state import read, write, sha, digest


SCHEMA = COMPONENT/'agent/schemas/native-acceptance.schema.json'
HASHES = {'artifact_sha256', 'layout_sha256'}


def validate_request(value):
    from deck_compiler.pipeline import POWERPOINT_REVIEW_CHECKS
    if not isinstance(value, dict):
        raise ValueError('native must be an operation object; read native.schema_path.')
    operation = value.get('operation')
    common = {'operation', *HASHES}
    required = {
        'render': common,
        'review': common | {'reviewer', 'note', 'method', 'reviewed_slide_ids', 'checks'},
        'ingest': common | {'reviewer', 'pdf_path', 'pdf_sha256', 'source'},
    }.get(operation)
    allowed = required | ({'force'} if operation == 'render' else set()) if required else set()
    if required is None or not required <= set(value) or set(value)-allowed:
        raise ValueError('Use exactly the fields for native render, review or ingest in native.schema_path.')
    for key in HASHES | ({'pdf_sha256'} if operation == 'ingest' else set()):
        if not isinstance(value[key], str) or not re.fullmatch('[a-f0-9]{64}', value[key]):
            raise ValueError(f'{key} must be the current SHA-256 value.')
    for key in ('reviewer', 'note', 'pdf_path'):
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            raise ValueError(f'{key} must be non-empty text.')
    if 'force' in value and type(value['force']) is not bool:
        raise ValueError('force must be a boolean.')
    if operation == 'review':
        ids, checks = value['reviewed_slide_ids'], value['checks']
        if (value['method'] != 'powerpoint-ui' or not isinstance(ids, list) or not ids or
                any(not isinstance(s, str) or not s.strip() for s in ids) or
                len(set(ids)) != len(ids) or not isinstance(checks, list) or
                any(not isinstance(s, str) for s in checks) or
                len(checks) != len(POWERPOINT_REVIEW_CHECKS) or set(checks) != set(POWERPOINT_REVIEW_CHECKS)):
            raise ValueError('Record only actual direct PowerPoint UI inspection: explicit slide IDs and all required checks.')
    if operation == 'ingest' and (value['source'] != 'powerpoint-export' or
            not Path(value['pdf_path']).is_absolute()):
        raise ValueError('ingest needs an absolute PDF path and source=powerpoint-export.')


def _candidate(build):
    from deck_compiler.qa_review import show_qa
    qa = read(build/'qa_report.json')
    if not isinstance(qa, dict):
        raise ValueError('Malformed candidate QA report.')
    if (qa.get('artifact_sha256') != sha(build/'candidate.pptx') or
            qa.get('artifact_sha256') != sha(build/'staging.pptx') or
            qa.get('layout_sha256') != sha(build/'layout.json') or
            qa.get('ir_sha256') != digest(read(build/'deck_ir.json'))):
        raise ValueError('Candidate, staging, IR, layout or QA differ; rebuild before native acceptance.')
    # A deleted native PDF should require a new export, not an OfficeCLI rebuild.
    # Keep normal stale-IR/artifact and malformed acknowledgement guards intact.
    if qa.get('checks', {}).get('native') and not _native_current(build, qa):
        from deck_compiler.qa_review import attach_acknowledgements
        qa['checks'].update(native=False, visual_review=False, visual_review_method=None)
        qa['native_evidence_stale'] = True
        return attach_acknowledgements(build, qa, read(build/'deck_ir.json'), read(build/'layout.json'))
    return show_qa(build, include_acked=True)


def _native_current(build, qa):
    path = build/'native.json'
    if not path.is_file():
        return None
    try:
        evidence = read(path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(evidence, dict):
        return None
    if (evidence.get('renderer') == 'powerpoint' and
            evidence.get('artifact_sha256') == qa.get('artifact_sha256') and
            isinstance(evidence.get('pdf_sha256'), str) and
            evidence.get('pdf_sha256') == sha(build/'native.pdf') and
            evidence.get('layout_sha256', qa.get('layout_sha256')) == qa.get('layout_sha256') and
            qa.get('checks', {}).get('native')):
        return evidence
    return None


def _preview_current(build, evidence):
    path = build/'native_preview.json'
    if not evidence or not path.is_file():
        return None
    try:
        preview = read(path)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(preview, dict):
        return None
    if (preview.get('artifact_sha256') != evidence.get('artifact_sha256') or
            preview.get('pdf_sha256') != evidence.get('pdf_sha256') or not preview.get('pages')):
        return None
    try:
        files = preview['pages'] + [preview['contact_sheet'], preview['index']]
        return preview if all(isinstance(p['sha256'], str) and sha(p['path']) == p['sha256'] for p in files) else None
    except (KeyError, TypeError, OSError):
        return None


def descriptor(out, qa=None):
    """Read-only status: absent previews never trigger a render or a rebuild."""
    from deck_compiler.pipeline import POWERPOINT_REVIEW_CHECKS, _load_powerpoint_review
    build = Path(out)/'build'
    qa = _candidate(build) if qa is None else qa
    evidence = _native_current(build, qa)
    preview = _preview_current(build, evidence)
    reviewed = False
    try:
        _load_powerpoint_review(build, build/'staging.pptx', build/'layout.json')
        reviewed = True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {'schema_path': str(SCHEMA), 'operations': ['render', 'review', 'ingest'],
        'artifact_sha256': qa['artifact_sha256'], 'layout_sha256': qa['layout_sha256'],
        'staging': str(build/'staging.pptx'),
        'slide_ids': [s['id'] for s in read(build/'layout.json')['slides']],
        'required_checks': POWERPOINT_REVIEW_CHECKS,
        'status': 'qa_failed' if qa['counts']['FAIL'] else
                  'awaiting_native_render' if not evidence else
                  'awaiting_powerpoint_review' if not reviewed or not qa['checks'].get('visual_review') else
                  'awaiting_review_acknowledgements' if qa['unacked_count'] else 'accepted',
        'rendered': evidence is not None, 'powerpoint_ui_reviewed': reviewed,
        'pdf': str(build/'native.pdf') if evidence else None,
        'preview_manifest': str(build/'native_preview.json') if preview else None,
        'contact_sheet': preview['contact_sheet']['path'] if preview else None,
        'page_previews': preview['index']['path'] if preview else None,
        'final_promotion': 'CLI_ONLY',
        'review_instruction': 'Inspect every listed slide directly in PowerPoint, then submit review with '
                              'these exact hashes, explicit slide IDs, method=powerpoint-ui, checks, reviewer and note. '
                              'PDF/PNG inspection and automated export do not constitute this review.'}


def _previews(build, evidence):
    """Rasterize an actual PowerPoint PDF; these PNGs do not attest UI inspection."""
    from PIL import Image, ImageDraw
    import pdfplumber
    cached = _preview_current(build, evidence)
    if cached:
        return cached
    folder = build/'native-preview'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    pages, thumbs = [], []
    with pdfplumber.open(build/'native.pdf') as document:
        for number, page in enumerate(document.pages, 1):
            png = folder/f'slide-{number:02d}.png'
            picture = page.to_image(resolution=144).original.convert('RGB')
            picture.save(png)
            pages.append({'slide': number, 'path': str(png.resolve()), 'sha256': sha(png)})
            picture.thumbnail((320, 180))
            thumb = Image.new('RGB', (336, 212), '#edf0f4')
            thumb.paste(picture, ((336-picture.width)//2, 8))
            ImageDraw.Draw(thumb).text((12, 192), str(number), fill='#263348')
            thumbs.append(thumb)
    if not pages:
        raise ValueError('Native PDF has no pages.')
    columns = min(4, len(thumbs))
    sheet = Image.new('RGB', (336*columns, 212*((len(thumbs)+columns-1)//columns)), 'white')
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % columns)*336, (index//columns)*212))
    contact = folder/'contact-sheet.png'
    sheet.save(contact)
    index_path = folder/'pages.html'
    index_path.write_text('<!doctype html><meta charset="utf-8"><title>PowerPoint PDF previews</title>'
        '<style>body{margin:24px;background:#edf0f4;font-family:system-ui}img{display:block;width:min(100%,1280px);'
        'height:auto;margin:8px 0 32px}</style><h1>PowerPoint PDF previews</h1><p>PDF rasterization; UI review is separate.</p>' +
        ''.join(f'<p>{p["slide"]}</p><img src="{Path(p["path"]).name}" alt="Slide {p["slide"]}">' for p in pages), encoding='utf-8')
    if sha(build/'native.pdf') != evidence['pdf_sha256']:
        raise ValueError('Native PDF changed during preview rendering.')
    value = {'schema_version': '1.0', 'renderer': 'powerpoint-pdf-rasterization',
        'powerpoint_ui_review': False, 'artifact_sha256': evidence['artifact_sha256'],
        'pdf_sha256': evidence['pdf_sha256'], 'pages': pages,
        'contact_sheet': {'path': str(contact.resolve()), 'sha256': sha(contact)},
        'index': {'path': str(index_path.resolve()), 'sha256': sha(index_path)}}
    write(build/'native_preview.json', value)
    return value


def _is_page_scene(build):
    return (Path(build)/'page_scene.json').is_file() and (
        Path(build)/'qa_report.json').is_file()


def _scene_execute(build, request):
    """PageScene native evidence; never runs the Deck IR semantic verifier."""
    from deck_compiler import native
    from deck_compiler.pipeline import locked as locked_path, record_powerpoint_review
    from . import page_scene_build
    qa = _candidate(build)
    if any(request[key] != qa[key] for key in HASHES):
        raise ValueError('Native request is stale; use the current native hashes from status.')
    operation = request['operation']
    failures = [item for item in qa['items'] if item['severity'] == 'FAIL']
    retry_native = (failures and all(item.get('source', {}).get('detector') == 'page-scene-native'
                                   for item in failures) and
                    (operation == 'ingest' or operation == 'render' and request.get('force') is True))
    if (failures or qa['counts']['FAIL']) and not retry_native:
        raise ValueError('FAIL findings must be repaired before native acceptance.')
    evidence = _native_current(build, qa)
    reused = False
    review = None
    review_path = build/'powerpoint_review.json'
    if review_path.is_file():
        try:
            from deck_compiler.pipeline import _load_powerpoint_review
            review = _load_powerpoint_review(build, build/'staging.pptx', build/'layout.json')
        except (OSError, ValueError, KeyError, TypeError):
            review = None
    if operation == 'render':
        if evidence and not request.get('force'):
            reused = True
        else:
            folder = build/'native-renders'/uuid.uuid4().hex
            folder.mkdir(parents=True)
            source = folder/('native-'+folder.name+'.pptx')
            with locked_path(build):
                shutil.copyfile(build/'staging.pptx', source)
                if sha(source) != request['artifact_sha256']:
                    raise ValueError('Candidate changed before native export.')
                evidence, issues = native.render(source, folder/'native.pdf')
            if not evidence:
                raise RuntimeError('; '.join(i['message'] for i in issues) or 'PowerPoint export unavailable.')
            if evidence['artifact_sha256'] != request['artifact_sha256']:
                raise ValueError('Native export does not describe the requested candidate.')
            shutil.copyfile(folder/'native.pdf', build/'native.pdf')
            evidence['pdf'] = str((build/'native.pdf').resolve())
            evidence['pdf_sha256'] = sha(build/'native.pdf')
            evidence['layout_sha256'] = qa['layout_sha256']
            write(build/'native.json', evidence)
    elif operation == 'ingest':
        pdf = Path(request['pdf_path'])
        if sha(pdf) != request['pdf_sha256']:
            raise ValueError('Manual PDF bytes differ from the supplied pdf_sha256.')
        if not pdf.read_bytes().startswith(b'%PDF'):
            raise ValueError('Native evidence is not a PDF.')
        if not review_path.is_file():
            raise ValueError('Manual PDF ingest needs a direct PowerPoint UI review of the same staging deck.')
        shutil.copyfile(pdf, build/'native.pdf')
        evidence = {'renderer': 'powerpoint', 'artifact_sha256': request['artifact_sha256'],
                    'pdf_sha256': sha(build/'native.pdf'), 'layout_sha256': qa['layout_sha256'],
                    'export_method': 'powerpoint-manual'}
        write(build/'native.json', evidence)
    elif operation == 'review':
        expected = [s['id'] for s in read(build/'layout.json')['slides']]
        if set(request['reviewed_slide_ids']) != set(expected):
            raise ValueError('PowerPoint UI review must explicitly cover every slide ID; all is not accepted.')
        record_powerpoint_review(build, request['reviewer'], request['reviewed_slide_ids'],
                                 request['note'], expected_hashes=request)
        review = read(build/'powerpoint_review.json')
        evidence = _native_current(build, qa)
    else:
        raise ValueError('Unsupported PageScene native operation.')
    # Uploaded manual PDFs must be inspected with the same PageScene boxes.
    if evidence:
        scene = read(build/'page_scene.json')
        items = page_scene_build.native_items(build/'native.pdf', scene)
        prior = read(build/'qa_report.json')
        kept = [item for item in prior.get('items', [])
                if item.get('source', {}).get('detector') != 'page-scene-native']
        metrics = prior.get('page_scene_metrics')
        page_scene_build._write_qa(build, scene, kept + items, structural=True, native=True,
                                   metrics=metrics, native_evidence=evidence, review=review,
                                   extra_checks={'page_scene_native': True})
    elif review:
        # A UI review can be recorded before the native PDF exists; preserve the
        # evidence but do not claim native validation.
        prior = read(build/'qa_report.json')
        scene = read(build/'page_scene.json')
        page_scene_build._write_qa(build, scene, prior.get('items', []), structural=True,
                                   native=False, metrics=prior.get('page_scene_metrics'),
                                   review=review, extra_checks={'page_scene_native': False})
    preview_error = None
    if evidence:
        try:
            _previews(build, evidence)
        except Exception as error:
            preview_error = type(error).__name__+': '+str(error)
    info = descriptor(build.parent)
    return {'operation': operation, 'status': info['status'],
            'reused_native_export': reused,
            'counts': read(build/'qa_report.json')['counts'],
            'preview_error': preview_error,
            'candidate_unchanged': sha(build/'candidate.pptx') == request['artifact_sha256']}


def execute(job, request):
    """Run one explicit operation without rerunning Story, design or OfficeCLI."""
    from deck_compiler import native
    from deck_compiler.pipeline import locked, ingest_native, record_powerpoint_review
    validate_request(request)
    build = Path(job['request']['out_dir'])/'build'
    if _is_page_scene(build):
        return _scene_execute(build, request)
    qa = _candidate(build)
    if any(request[key] != qa[key] for key in HASHES):
        raise ValueError('Native request is stale; use the current native hashes from status.')
    operation = request['operation']
    failures = [item for item in qa['items'] if item['severity'] == 'FAIL']
    retry_native = (failures and all(item.get('source', {}).get('detector') == 'native-visual'
                                   for item in failures) and
                    (operation == 'ingest' or operation == 'render' and request.get('force') is True))
    if (failures or qa['counts']['FAIL']) and not retry_native:
        raise ValueError('FAIL findings must be repaired before native acceptance.')
    reused = False
    if operation == 'render':
        evidence = _native_current(build, qa)
        if evidence and not request.get('force'):
            reused = True
        else:
            # Use a private copy: never close an already-open user document or
            # export unsaved edits instead of the exact staging bytes.
            folder = build/'native-renders'/uuid.uuid4().hex
            folder.mkdir(parents=True)
            source = folder/('native-'+folder.name+'.pptx')
            with locked(build):
                shutil.copyfile(build/'staging.pptx', source)
                if sha(source) != request['artifact_sha256']:
                    raise ValueError('Candidate changed before native export.')
                evidence, issues = native.render(source, folder/'native.pdf')
            if not evidence:
                raise RuntimeError('; '.join(i['message'] for i in issues) or 'PowerPoint export unavailable.')
            if evidence['artifact_sha256'] != request['artifact_sha256']:
                raise ValueError('Native export does not describe the requested candidate.')
            if _candidate(build)['layout_sha256'] != request['layout_sha256']:
                raise ValueError('Layout changed during native export.')
            qa = ingest_native(build, folder/'native.pdf', render_evidence=evidence, expected_hashes=request)
    elif operation == 'review':
        expected = [s['id'] for s in read(build/'layout.json')['slides']]
        if set(request['reviewed_slide_ids']) != set(expected):
            raise ValueError('PowerPoint UI review must explicitly cover every slide ID; all is not accepted.')
        record_powerpoint_review(build, request['reviewer'], request['reviewed_slide_ids'], request['note'], expected_hashes=request)
        evidence = _native_current(build, qa)
        if evidence:
            qa = ingest_native(build, build/'native.pdf', request['reviewer'], render_evidence=evidence, expected_hashes=request)
    else:
        pdf = Path(request['pdf_path'])
        if sha(pdf) != request['pdf_sha256']:
            raise ValueError('Manual PDF bytes differ from the supplied pdf_sha256.')
        qa = ingest_native(build, pdf, request['reviewer'], expected_hashes=request)
    evidence = _native_current(build, _candidate(build))
    preview_error = None
    if evidence:
        try:
            _previews(build, evidence)
        except Exception as error:
            # Native PDF evidence remains valid if an optional rasterizer is
            # unavailable. A repeated render reuses PDF and retries previews.
            preview_error = type(error).__name__+': '+str(error)
    info = descriptor(build.parent)
    return {'operation': operation, 'status': info['status'],
        'reused_native_export': reused, 'counts': qa['counts'],
        'preview_error': preview_error, 'candidate_unchanged': sha(build/'candidate.pptx') == request['artifact_sha256']}
