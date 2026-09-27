"""Artifact-bound OfficeCLI review export; never fabricates PowerPoint UI evidence."""
import json
import os
from pathlib import Path
import subprocess
from .contracts import digest, file_hash
from .pipeline import locked, write_json
from .structural import verify


def review(out, executable='officecli', render='native'):
    out = Path(out)
    if render not in ('native', 'html'):
        raise ValueError('OfficeCLI render must be native or html')
    with locked(out):
        staging, layout_path = out/'staging.pptx', out/'layout.json'
        layout = json.loads(layout_path.read_text(encoding='utf-8'))
        ir = json.loads((out/'deck_ir.json').read_text(encoding='utf-8'))
        qa = json.loads((out/'qa_report.json').read_text(encoding='utf-8'))
        sha = file_hash(staging)
        if (qa['artifact_sha256'] != sha or qa['layout_sha256'] != file_hash(layout_path)
                or qa['ir_sha256'] != digest(ir) or layout['ir_sha256'] != digest(ir)):
            raise ValueError('Stale build; rebuild before OfficeCLI review')
        evidence_dir = out/'officecli-review'
        evidence_dir.mkdir(exist_ok=True)
        commands = []

        def run(*args, export=False):
            argv = [executable, *map(str,args), '--json']
            result = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=180, env={**os.environ, 'OFFICECLI_NO_AUTO_RESIDENT':'1'})
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                if not export:
                    raise ValueError(f'OfficeCLI returned non-JSON output: {result.stdout} {result.stderr}')
                # Native screenshot export may print only the output filename.
                # Its success is checked against a freshly created PNG below.
                payload = {'success': result.returncode == 0, 'stdout': result.stdout,
                           'stderr': result.stderr, 'response_format': 'text'}
            commands.append({'argv': argv, 'exit_code': result.returncode, 'response': payload})
            if result.returncode or payload.get('success') is not True:
                raise ValueError(f'OfficeCLI review failed: {payload}')
            return payload

        schema = run('validate', staging)
        issues = run('view', staging, 'issues')
        issue_data = issues.get('data') or {}
        schema_count = (schema.get('data') or {}).get('count')
        if (not isinstance(schema_count, int) or schema_count < 0
                or not isinstance(issue_data.get('issues'), list)
                or issue_data.get('count') != len(issue_data['issues'])):
            raise ValueError('OfficeCLI returned an invalid validation report')
        text = run('view', staging, 'text')
        structural = verify(staging, layout)
        write_json(evidence_dir/'schema.json', schema)
        write_json(evidence_dir/'issues.json', issues)
        write_json(evidence_dir/'text.json', text)
        pages = []
        for n, slide in enumerate(layout['slides'], 1):
            png = evidence_dir/f'slide-{n}.png'
            if png.exists():
                png.unlink()
            run('view', staging, 'screenshot', '--render', render, '--page', n, '-o', png, export=True)
            if not png.is_file() or not png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError(f'OfficeCLI did not produce slide {n} PNG')
            pages.append({'slide_id':slide['id'], 'path':str(png), 'sha256':file_hash(png)})
        run('close', staging)
        if file_hash(staging) != sha:
            raise ValueError('Review unexpectedly changed staging bytes')
        issue_count = issue_data['count']
        # A successful export is not visual acceptance. Raw warnings stay visible.
        record = {'schema_version':'officecli-review-1', 'method':'officecli-cli',
            'requested_render':render, 'artifact_sha256':sha,
            'layout_sha256':file_hash(layout_path), 'ir_sha256':digest(ir),
            'officecli_runtime':qa['checks'].get('officecli_runtime'),
            'schema_count':schema_count, 'issue_count':issue_count,
            'structural_items':structural, 'pages':pages,
            'status':'REJECT' if issue_count or schema_count or any(i['severity']=='FAIL' for i in structural)
                     else 'AWAITING_VISUAL_REVIEW',
            'powerpoint_ui_review':False, 'final_promotion':False}
        write_json(evidence_dir/'commands.json', commands)
        record['commands_sha256'] = file_hash(evidence_dir/'commands.json')
        write_json(out/'officecli_review.json',record)
        return record
