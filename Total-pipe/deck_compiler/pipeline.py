"""One candidate, one staging file, one atomically promoted final per workspace."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from .contracts import digest, file_hash, issue, report
from .ir import derive
from .layout import compile_deck
from .artifact import finalize, verify
from . import officecli
from . import native


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    os.replace(temp, path)


POWERPOINT_REVIEW_CHECKS = [
    'figure_caption_alignment',
    'scientific_panel_readability',
    'text_overflow_and_collisions',
    'font_rendering',
]


@contextmanager
def locked(out):
    out.mkdir(parents=True, exist_ok=True)
    lock = out/'.compiler.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lock.unlink()


def compile_input(ir_path, out):
    ir = json.loads(ir_path.read_text())
    layout, issues = compile_deck(ir, ir_path.parent)
    write_json(out/'deck_ir.json', ir)
    if layout:
        write_json(out/'layout.json', layout)
        for name, value in derive(ir, layout).items():
            write_json(out/'derived'/name, value)
    qa = report(issues, ir_sha256=digest(ir), checks={'semantic': True, 'geometric': layout is not None})
    write_json(out/'qa_report.json', qa)
    return ir, layout, qa


def build(ir_path, out, node='node', native_render=True, backend='artifact-tool', officecli_executable='officecli'):
    started = time.monotonic()
    with locked(out):
        # Last final remains a previous successful artifact, explicitly identified in state.
        old_final = file_hash(out/'final.pptx') if (out/'final.pptx').exists() else None
        write_json(out/'state.json', {'phase': 'compiling', 'previous_final_sha256': old_final})
        for name in ('candidate.pptx', 'candidate.officecli.batch.json', 'officecli_issues.json',
                     'staging.pptx', 'native.pdf', 'native.json',
                     'powerpoint_review.json', 'layout.json'):
            (out/name).unlink(missing_ok=True)
        ir, layout, qa = compile_input(ir_path, out)
        items = qa['items']
        if qa['counts']['FAIL']:
            write_json(out/'state.json', {'phase': 'preflight_failed', 'previous_final_sha256': old_final})
            return qa
        render_count = 0
        native_evidence = None
        structural_complete = False
        try:
            # Bind external files to the compiled input before reading them in a subprocess.
            for asset in layout['assets'].values():
                if file_hash(Path(asset['path'])) != asset['sha256']:
                    raise ValueError('Asset changed since compilation')
            if backend == 'officecli':
                officecli.render(out/'layout.json', out/'candidate.pptx', officecli_executable)
            elif backend == 'artifact-tool':
                render_env = os.environ.copy()
                if not render_env.get('ARTIFACT_TOOL_MODULE'):
                    resolved_node = Path(shutil.which(node) or node).resolve()
                    bundled_module = (resolved_node.parents[1]/'node_modules'/'@oai'/'artifact-tool'/
                                      'dist'/'artifact_tool.mjs')
                    if bundled_module.exists():
                        render_env['ARTIFACT_TOOL_MODULE'] = str(bundled_module)
                subprocess.run([node, str(Path(__file__).with_name('render.mjs')), str(out/'layout.json'),
                                str(out/'candidate.pptx')], check=True, timeout=180, env=render_env)
            else:
                raise ValueError(f'Unknown renderer backend: {backend}')
            render_count = 1
            finalize(out/'candidate.pptx', out/'staging.pptx', layout)
            items += verify(out/'staging.pptx', layout)
            if backend == 'officecli':
                officecli_report = officecli.inspect(out/'staging.pptx', officecli_executable)
                write_json(out/'officecli_issues.json', officecli_report)
                for finding in officecli_report['issues']:
                    severity = {'0': 'FAIL', '1': 'WARNING', '2': 'INFO',
                                'error': 'FAIL', 'warning': 'WARNING', 'info': 'INFO'}.get(
                                    str(finding.get('severity')).lower())
                    if not severity:
                        raise ValueError(f'OfficeCLI returned unknown issue severity: {finding}')
                    path = finding.get('path') or ''
                    slide = re.search(r'/slide\[(\d+)\]', path)
                    category = finding.get('subtype') or {0: 'FORMAT', 1: 'CONTENT', 2: 'STRUCTURE'}.get(
                        finding.get('type'), str(finding.get('type') or 'ISSUE'))
                    rule = 'OFFICECLI_' + re.sub(r'[^A-Z0-9]+', '_',
                        category.upper()).strip('_')
                    items.append(issue(rule, severity, finding.get('message') or '',
                                       int(slide.group(1)) if slide else None, path or None,
                                       detector='officecli-view-issues', backend='officecli',
                                       officecli_issue_id=finding.get('id')))
            structural_complete = True
            if native_render and not any(i['severity']=='FAIL' for i in items):
                native_evidence, native_items = native.render(out/'staging.pptx', out/'native.pdf')
                items += native_items
                if native_evidence:
                    items += native.inspect_pdf(out/'native.pdf', layout)
                    write_json(out/'native.json', native_evidence)
            elif not native_render:
                items.append(issue('NATIVE_RENDER_SKIPPED', 'REVIEW', 'Golden validation has not run',
                                   detector='native-visual', confidence='LOW', renderer='powerpoint'))
        except (OSError, ValueError, subprocess.SubprocessError, ImportError) as error:
            items.append(issue('COMPILATION_FAILED', 'FAIL', str(error), detector='compiler'))
        sha = file_hash(out/'staging.pptx') if (out/'staging.pptx').exists() else None
        qa = report(items, sha, digest(ir), {'structural': structural_complete,
                    'native': native_evidence is not None, 'renderer': 'powerpoint' if native_evidence else None,
                    'backend': backend,
                    'officecli_schema': backend == 'officecli' and structural_complete,
                    'officecli_issues': backend == 'officecli' and structural_complete})
        qa['layout_sha256'] = file_hash(out/'layout.json')
        write_json(out/'qa_report.json', qa)
        write_json(out/'state.json', {'phase': 'failed' if qa['counts']['FAIL'] else 'awaiting_validation',
                                     'artifact_sha256': sha, 'previous_final_sha256': old_final})
        write_json(out/'metrics.json', {'elapsed_seconds': round(time.monotonic()-started, 3),
            'rerenders': render_count, 'canonical_truth_count': 1, 'new_adapter_count': 0,
            'backend': backend,
            'slide_count': len(ir['slides']), 'layout_llm_fallback_count': 0,
            'qa_counts': qa['counts'], 'false_positive_rate': None, 'repair_amplification_factor': None})
        return qa


def record_powerpoint_review(out, reviewer, slide_ids=None):
    """Bind a direct PowerPoint UI review to the current staging bytes.

    The caller records this only after inspecting the editable staging deck in
    PowerPoint itself. Preview/PDF inspection is native evidence, but does not
    satisfy this visual-review gate.
    """
    out = Path(out)
    with locked(out):
        staging = out/'staging.pptx'
        layout_path = out/'layout.json'
        if not staging.exists() or not layout_path.exists():
            raise ValueError('staging.pptx and layout.json are required')
        if not reviewer or not reviewer.strip():
            raise ValueError('PowerPoint reviewer is required')
        layout = json.loads(layout_path.read_text())
        expected = [slide['id'] for slide in layout.get('slides', [])]
        reviewed = expected if not slide_ids or slide_ids == ['all'] else slide_ids
        if len(reviewed) != len(set(reviewed)) or set(reviewed) != set(expected):
            missing = sorted(set(expected) - set(reviewed))
            extra = sorted(set(reviewed) - set(expected))
            raise ValueError(f'PowerPoint review must cover every slide; missing={missing}, extra={extra}')
        evidence = {
            'schema_version': '2.0',
            'method': 'powerpoint-ui',
            'reviewer': reviewer.strip(),
            'artifact_sha256': file_hash(staging),
            'layout_sha256': file_hash(layout_path),
            'reviewed_slide_ids': expected,
            'checks': POWERPOINT_REVIEW_CHECKS,
        }
        write_json(out/'powerpoint_review.json', evidence)
        state_path = out/'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        state.update({'phase': 'awaiting_native_validation',
                      'artifact_sha256': evidence['artifact_sha256'],
                      'powerpoint_visual_reviewed': True})
        write_json(state_path, state)
        return out/'powerpoint_review.json'


def _load_powerpoint_review(out, staging, layout_path, reviewer=None):
    path = out/'powerpoint_review.json'
    if not path.exists():
        raise ValueError('Direct PowerPoint UI review is required; run record-powerpoint-review')
    evidence = json.loads(path.read_text())
    layout = json.loads(layout_path.read_text())
    expected = {slide['id'] for slide in layout.get('slides', [])}
    if (evidence.get('method') != 'powerpoint-ui' or
            evidence.get('artifact_sha256') != file_hash(staging) or
            evidence.get('layout_sha256') != file_hash(layout_path) or
            set(evidence.get('reviewed_slide_ids', [])) != expected or
            set(evidence.get('checks', [])) != set(POWERPOINT_REVIEW_CHECKS) or
            not evidence.get('reviewer')):
        raise ValueError('PowerPoint UI review evidence is stale or incomplete')
    if reviewer and reviewer != evidence['reviewer']:
        raise ValueError('PowerPoint reviewer does not match recorded review')
    return evidence


def ingest_native(out, pdf, reviewer=None):
    """Attach a PowerPoint-exported PDF to the exact staging artifact.

    This is the deterministic continuation path when macOS shows a first-use
    file-access dialog and unattended export cannot complete.  It refreshes
    structural evidence instead of trusting the earlier report.
    """
    out = Path(out)
    pdf = Path(pdf)
    with locked(out):
        staging = out/'staging.pptx'
        layout_path = out/'layout.json'
        ir_path = out/'deck_ir.json'
        if not all(path.exists() for path in (staging, layout_path, ir_path, pdf)):
            raise ValueError('staging.pptx, layout.json, deck_ir.json and native PDF are required')
        if not pdf.read_bytes().startswith(b'%PDF'):
            raise ValueError('Native evidence is not a PDF')
        review = _load_powerpoint_review(out, staging, layout_path, reviewer)
        layout = json.loads(layout_path.read_text())
        ir = json.loads(ir_path.read_text())
        prior = json.loads((out/'qa_report.json').read_text())
        if prior.get('artifact_sha256') != file_hash(staging):
            raise ValueError('staging.pptx changed after build; rebuild before native validation')
        # Rebuild all artifact-derived findings against the current bytes.
        keep = [item for item in prior.get('items', [])
                if item.get('source', {}).get('detector') not in ('native-visual', 'structural-ooxml')]
        items = keep + verify(staging, layout) + native.inspect_pdf(pdf, layout)
        native_path = out/'native.pdf'
        if pdf.resolve() != native_path.resolve():
            temp_pdf = out/'native.pdf.tmp'
            shutil.copyfile(pdf, temp_pdf)
            os.replace(temp_pdf, native_path)
        evidence = {
            'renderer': 'powerpoint',
            'artifact_sha256': file_hash(staging),
            'pdf_sha256': file_hash(native_path),
            'pdf': str(native_path.resolve()),
            'visual_review': review,
        }
        write_json(out/'native.json', evidence)
        qa = report(items, evidence['artifact_sha256'], digest(ir), {
            'structural': True,
            'native': True,
            'renderer': 'powerpoint',
            'visual_review': True,
            'visual_review_method': 'powerpoint-ui',
            'backend': prior.get('checks', {}).get('backend', 'artifact-tool'),
            'officecli_schema': prior.get('checks', {}).get('officecli_schema', False),
            'officecli_issues': prior.get('checks', {}).get('officecli_issues', False),
        })
        qa['layout_sha256'] = file_hash(layout_path)
        write_json(out/'qa_report.json', qa)
        metrics_path = out/'metrics.json'
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text())
            metrics['qa_counts'] = qa['counts']
            metrics['native_validated'] = True
            metrics['powerpoint_visual_reviewed'] = True
            write_json(metrics_path, metrics)
        write_json(out/'state.json', {
            'phase': 'awaiting_review' if qa['counts']['REVIEW'] else 'validated',
            'artifact_sha256': evidence['artifact_sha256'],
            'powerpoint_visual_reviewed': True,
            'powerpoint_reviewer': review['reviewer'],
        })
        return qa


def promote(out, acknowledgements=None):
    """Fail closed: stale report/IR/native evidence or outstanding reviews cannot publish."""
    with locked(out):
        qa = json.loads((out/'qa_report.json').read_text())
        sha = file_hash(out/'staging.pptx')
        if qa.get('schema_version') != '2.0' or qa.get('artifact_sha256') != sha:
            raise ValueError('QA report does not describe staging.pptx')
        if digest(json.loads((out/'deck_ir.json').read_text())) != qa['ir_sha256']:
            raise ValueError('IR changed since validation')
        if file_hash(out/'layout.json') != qa['layout_sha256']:
            raise ValueError('Compiled layout changed since validation')
        if any(i['severity'] == 'FAIL' for i in qa['items']):
            raise ValueError('FAIL findings block final')
        if not qa['checks'].get('structural') or not qa['checks'].get('native'):
            raise ValueError('Structural and PowerPoint golden validation required')
        review = _load_powerpoint_review(out, out/'staging.pptx', out/'layout.json')
        if not qa['checks'].get('visual_review') or qa['checks'].get('visual_review_method') != 'powerpoint-ui':
            raise ValueError('Direct PowerPoint UI visual review required')
        evidence = json.loads((out/'native.json').read_text())
        if (evidence.get('renderer') != 'powerpoint' or evidence.get('artifact_sha256') != sha or
                evidence.get('pdf_sha256') != file_hash(out/'native.pdf') or
                evidence.get('visual_review', {}).get('artifact_sha256') != review['artifact_sha256']):
            raise ValueError('Native evidence is stale or non-golden')
        reviews = {i['id'] for i in qa['items'] if i['severity']=='REVIEW'}
        ack = acknowledgements or {}
        if reviews and (ack.get('artifact_sha256') != sha or not ack.get('reviewer') or
                        not reviews <= set(ack.get('accepted_review_ids', []))):
            raise ValueError('REVIEW items need artifact-bound reviewer acknowledgement')
        # Recheck actual bytes immediately before promotion. Warnings remain
        # non-blocking; any newly surfaced REVIEW still needs the same
        # artifact-bound acknowledgement as the saved report.
        fresh = verify(out/'staging.pptx', json.loads((out/'layout.json').read_text()))
        if any(item['severity'] == 'FAIL' for item in fresh):
            raise ValueError('Structural recheck produced FAIL findings')
        fresh_reviews = {item['id'] for item in fresh if item['severity'] == 'REVIEW'}
        if fresh_reviews and not fresh_reviews <= set(ack.get('accepted_review_ids', [])):
            raise ValueError('Structural recheck produced unacknowledged REVIEW findings')
        temp = out/'final.pptx.tmp'
        shutil.copyfile(out/'staging.pptx', temp)
        os.replace(temp, out/'final.pptx')
        write_json(out/'state.json', {'phase': 'final', 'artifact_sha256': sha, 'review_acknowledgement': ack})
        return out/'final.pptx'
