"""One candidate, one staging file, one atomically promoted final per workspace."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from .contracts import digest, file_hash, issue, report
from .ir import derive
from .layout import compile_deck
from .artifact import finalize, verify
from . import native


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    os.replace(temp, path)


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


def build(ir_path, out, node='node', native_render=True):
    started = time.monotonic()
    with locked(out):
        # Last final remains a previous successful artifact, explicitly identified in state.
        old_final = file_hash(out/'final.pptx') if (out/'final.pptx').exists() else None
        write_json(out/'state.json', {'phase': 'compiling', 'previous_final_sha256': old_final})
        for name in ('candidate.pptx', 'staging.pptx', 'native.pdf', 'native.json', 'layout.json'):
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
            render_env = os.environ.copy()
            if not render_env.get('ARTIFACT_TOOL_MODULE'):
                resolved_node = Path(shutil.which(node) or node).resolve()
                bundled_module = (resolved_node.parents[1]/'node_modules'/'@oai'/'artifact-tool'/
                                  'dist'/'artifact_tool.mjs')
                if bundled_module.exists():
                    render_env['ARTIFACT_TOOL_MODULE'] = str(bundled_module)
            subprocess.run([node, str(Path(__file__).with_name('render.mjs')), str(out/'layout.json'),
                            str(out/'candidate.pptx')], check=True, timeout=180, env=render_env)
            render_count = 1
            finalize(out/'candidate.pptx', out/'staging.pptx', layout)
            items += verify(out/'staging.pptx', layout)
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
                    'native': native_evidence is not None, 'renderer': 'powerpoint' if native_evidence else None})
        qa['layout_sha256'] = file_hash(out/'layout.json')
        write_json(out/'qa_report.json', qa)
        write_json(out/'state.json', {'phase': 'failed' if qa['counts']['FAIL'] else 'awaiting_validation',
                                     'artifact_sha256': sha, 'previous_final_sha256': old_final})
        write_json(out/'metrics.json', {'elapsed_seconds': round(time.monotonic()-started, 3),
            'rerenders': render_count, 'canonical_truth_count': 1, 'new_adapter_count': 0,
            'slide_count': len(ir['slides']), 'layout_llm_fallback_count': 0,
            'qa_counts': qa['counts'], 'false_positive_rate': None, 'repair_amplification_factor': None})
        return qa


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
        layout = json.loads(layout_path.read_text())
        ir = json.loads(ir_path.read_text())
        prior = json.loads((out/'qa_report.json').read_text())
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
            'visual_review': ({'reviewer': reviewer, 'status': 'reviewed'}
                              if reviewer else {'status': 'not_recorded'}),
        }
        write_json(out/'native.json', evidence)
        qa = report(items, evidence['artifact_sha256'], digest(ir), {
            'structural': True,
            'native': True,
            'renderer': 'powerpoint',
            'visual_review': bool(reviewer),
        })
        qa['layout_sha256'] = file_hash(layout_path)
        write_json(out/'qa_report.json', qa)
        metrics_path = out/'metrics.json'
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text())
            metrics['qa_counts'] = qa['counts']
            metrics['native_validated'] = True
            metrics['powerpoint_visual_reviewed'] = bool(reviewer)
            write_json(metrics_path, metrics)
        write_json(out/'state.json', {
            'phase': 'awaiting_review' if qa['counts']['REVIEW'] else 'validated',
            'artifact_sha256': evidence['artifact_sha256'],
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
        evidence = json.loads((out/'native.json').read_text())
        if evidence.get('renderer') != 'powerpoint' or evidence.get('artifact_sha256') != sha or evidence.get('pdf_sha256') != file_hash(out/'native.pdf'):
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
