"""Component invocations and deterministic validation, never scientific content generation."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import signal

from . import ROOT, COMPONENT
from .state import read, write, sha, resources

sys.path.insert(0, str(COMPONENT/'pwf2rpa'))


class Failure(ValueError):
    def __init__(self, code, message, action='resolve_dependency', target=None, log=None):
        super().__init__(message)
        self.code, self.action, self.target, self.log = code, action, target, log


def redact(text):
    for key, value in os.environ.items():
        if len(value) >= 6 and any(term in key.upper() for term in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')):
            text = text.replace(value, '[REDACTED]')
    return text


def classify(code, message, stage=None, log=None):
    if code in ('KEY_POINTS_LOST', 'SOURCE_TEXT_NOT_BOUND', 'CONTENT_LOSS'):
        return Failure('CONTENT_LOSS', message, 'replan', 'story' if stage == 'rpa' else 'deck_ir', log)
    if code == 'VISUAL_DESIGN_REQUIRED':
        return Failure('DESIGN_MISSING', message, 'author_artifact', 'visual_design', log)
    if code.startswith('STORY_'):
        return Failure('STORY_PROVENANCE_MISMATCH' if code == 'STORY_PROVENANCE_MISMATCH' else 'STORY_PROVENANCE_INVALID',
                       message, 'resolve_dependency' if code.endswith('MISMATCH') else 'author_artifact', 'story', log)
    if code.startswith('VISUAL_PLAN_'):
        return Failure(code, message, 'replan', 'visual_design', log)
    if any(term in code for term in ('CAPACITY', 'SPACE', 'SPLIT_REQUIRED', 'LAYOUT_TREE', 'SLOT_WRAP')):
        return Failure(code, message, 'replan', 'story' if stage == 'rpa' else 'deck_ir', log)
    return Failure(code, message, 'review_required' if stage == 'build' else 'resolve_dependency', stage, log)


def findings(value):
    result = []
    if isinstance(value, list):
        for child in value:
            result += findings(child)
    elif isinstance(value, dict):
        if ('code' in value or 'rule' in value) and str(value.get('severity', '')).upper() in ('FAIL', 'ERROR', 'BLOCKING'):
            result.append(value)
        for key in ('items', 'issues', 'deck_issues', 'problems', 'violations', 'errors', 'validation', 'slides'):
            result += findings(value.get(key))
    return result


def run_process(argv, cwd, timeout):
    options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    with subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
            **options) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=10)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def run(argv, cwd, out, name, timeout=120, json_output=True):
    log = Path(out)/'logs'/(name+'.json')
    try:
        process = run_process([str(a) for a in argv], cwd, timeout)
    except FileNotFoundError as error:
        code = 'OFFICECLI_MISSING' if 'officecli' in str(argv[0]).lower() else 'EXECUTABLE_MISSING'
        raise Failure(code, f'Executable unavailable: {argv[0]}') from error
    except subprocess.TimeoutExpired as error:
        write(log, {'code': 'COMPONENT_TIMEOUT', 'message': redact(str(error))})
        raise Failure('COMPONENT_TIMEOUT', 'Component timed out; its process was terminated. Retry or inspect the log.', log=str(log)) from error
    stdout, stderr = redact(process.stdout), redact(process.stderr)
    write(log, {'argv': [redact(str(a)) for a in argv], 'exit_code': process.returncode,
                'stdout': stdout, 'stderr': stderr})
    value = None
    if json_output:
        try:
            value = json.loads(stdout)
        except ValueError as error:
            raise Failure('COMPONENT_BAD_JSON', 'Component did not return JSON; inspect its log.', log=str(log)) from error
    errors = findings(value)
    if (name.startswith('rpa-') and isinstance(value, dict) and not errors and
            (value.get('status') in ('failed', 'needs_replan') or value.get('unplanned_slide_briefs'))):
        raise Failure('RPA_PLAN_REQUIRES_REPLAN',
                      'RPA left source briefs unplanned. Inspect the complete planning log and revise Story without dropping content.',
                      'replan', 'story', str(log))
    if process.returncode or errors or (isinstance(value, dict) and value.get('status') in ('blocked', 'needs_replan', 'invalid')):
        first = errors[0] if errors else {}
        code = first.get('code', first.get('rule'))
        if not code:
            match = re.search(r'\b(STORY_[A-Z_]+|[A-Z_]*CAPACITY[A-Z_]*|SOURCE_TEXT_NOT_BOUND|KEY_POINTS_LOST)\b', stderr)
            code = match.group(1) if match else 'COMPONENT_FAILED'
        raise classify(code, first.get('message') or stderr[-1000:] or 'Component rejected this input; inspect its log.',
                       'rpa' if name.startswith('rpa') else 'build' if name == 'build' else None, str(log))
    return value


def compiler(command, out, *args, timeout=120):
    return run([sys.executable, '-m', 'deck_compiler', command, *args], COMPONENT, out, command, timeout)


def pwf_cli(out, *args):
    return run([sys.executable, '-m', 'pwf2rpa', *args], COMPONENT/'pwf2rpa', out, 'pwf2rpa', json_output=False)


def rpa(command, source, out):
    value = run(['node', ROOT/'research-ppt-assistant/server/cli.mjs', command, '--file', source,
                 '--detail-level', 'full'], ROOT, out, 'rpa-'+command)
    return value


def check_queries(value):
    if not isinstance(value, list) or not value or len(value) > 32:
        raise Failure('QUERIES_INVALID', 'Provide 1–32 topic-specific query objects.', 'author_artifact', 'queries')
    ids = set()
    for query in value:
        if (not isinstance(query, dict) or set(query)-{'id', 'query', 'intent'} or
                not all(isinstance(query.get(k), str) and query[k].strip() for k in ('id', 'query')) or query['id'] in ids):
            raise Failure('QUERIES_INVALID', 'Each query needs a unique id and nonempty query; optional intent.', 'author_artifact', 'queries')
        ids.add(query['id'])


def check_story(prompt, story, workflow):
    from pwf2rpa import Workflow, story_to_specs
    from pwf2rpa.errors import AdapterError
    if not isinstance(story, dict):
        raise classify('STORY_PROVENANCE_INVALID', 'Story must be a JSON object.')
    expected, actual = prompt.get('delegation', {}), story.get('planner', {})
    if not isinstance(actual, dict) or not actual:
        raise classify('STORY_PLANNER_PROVENANCE_MISSING', 'Story must record its real subagent provenance.')
    if any(actual.get(key) != expected.get(key) for key in ('model', 'reasoning_effort')):
        raise classify('STORY_PROVENANCE_MISMATCH', 'Story model / reasoning differs from the user-selected prompt delegation.')
    try:
        story_to_specs(story, Workflow(workflow))
    except (ValueError, AdapterError) as error:
        raise classify('STORY_PROVENANCE_INVALID', str(error)) from error


def check_ir(value, normalized=None):
    from deck_compiler.ir import validate
    failures = [i for i in validate(value) if i['severity'] == 'FAIL']
    if failures:
        item = failures[0]
        failure = classify(item['rule'], item['message'], 'deck_ir')
        if failure.action == 'resolve_dependency':
            failure.action, failure.target = 'author_artifact', 'deck_ir'
        raise failure
    if normalized:
        def texts(value):
            if isinstance(value, dict):
                return '\n'.join(texts(v) if isinstance(v, (list, dict)) else str(v)
                    for k, v in value.items() if isinstance(v, (dict, list)) or k in
                    ('text', 'title', 'body', 'label', 'takeaway', 'speaker_notes'))
            if isinstance(value, list):
                return '\n'.join(texts(v) if isinstance(v, (dict, list)) else str(v) for v in value)
            return ''
        corpus = ''.join(texts(value.get('slides', [])).split())
        if len(value['slides']) < len(normalized.get('slide_briefs', [])):
            raise classify('CONTENT_LOSS', 'IR has fewer pages than the original complete briefs; revise Story explicitly before merging pages.', 'deck_ir')
        known = {entry.get('id', entry.get('evidence_id')) for entry in normalized.get('evidence', [])}
        if known and any(ref not in known for page in value['slides'] for ref in page['semantic']['evidence_refs']):
            raise classify('CONTENT_LOSS', 'IR evidence_refs must resolve to the original normalized evidence store.', 'deck_ir')
        for brief in normalized.get('slide_briefs', []):
            for content in [brief.get('body', ''), *brief.get('key_points', [])]:
                if content and ''.join(str(content).split()) not in corpus:
                    raise classify('CONTENT_LOSS', 'IR must retain each complete brief body and key_point in page text or speaker notes.', 'deck_ir')
        for brief in normalized.get('slide_briefs', []):
            compact = (brief.get('metadata') or {}).get('story_compact_process')
            if not isinstance(compact, dict):
                continue
            items = [str(item) for item in compact.get('items', []) if str(item).strip()]
            node_count = compact.get('node_count') or len(items)
            if len(items) < 6:
                continue
            carried = False
            for page in value['slides']:
                for graphic in page.get('composition', {}).get('graphics', []) or []:
                    if not isinstance(graphic, dict) or graphic.get('type') != 'process' \
                            or graphic.get('layout') != 'compact':
                        continue
                    nodes = [node for node in graphic.get('nodes', []) if isinstance(node, dict)]
                    if len(nodes) < node_count:
                        continue
                    titles = ''.join(''.join(str(node.get(key, '')).split())
                                     for node in nodes for key in ('title', 'body'))
                    if all(''.join(item.split()) in titles for item in items):
                        carried = True
                        break
                if carried:
                    break
            if not carried:
                raise classify(
                    'CONTENT_LOSS',
                    f'Story declared a {node_count}-step compact process, but the IR has no type=process/'
                    'layout=compact graphic carrying every step; replace the RPA three-slot placeholder.',
                    'deck_ir')


def import_ir(source, destination):
    value = read(source)
    check_ir(value)
    for asset in value.get('assets', {}).values():
        if not Path(asset['path']).is_absolute():
            asset['path'] = str((Path(source).parent/asset['path']).resolve())
    for key in ('font_file', 'bold_font_file', 'background_image'):
        ref = value.get('theme', {}).get(key)
        if ref and not Path(ref).is_absolute() and (Path(source).parent/ref).is_file():
            value['theme'][key] = str((Path(source).parent/ref).resolve())
    write(destination, value)


def ir_prompt(workflow, rpa_input, normalized, plan):
    from deck_compiler.catalog import ARCHETYPES, COMPONENTS
    from deck_compiler.layout_tree import capabilities
    return {'workflow': workflow, 'rpa_input': rpa_input, 'content_model': normalized, 'deck_plan': plan,
        'archetypes': ARCHETYPES, 'components': sorted(COMPONENTS), 'capabilities': capabilities(),
        'schema': read(COMPONENT/'schemas/deck-ir.schema.json'),
        'instructions': 'Write canonical Deck IR. Preserve complete scientific body, key_points, figures, equations, '
        'units and uncertainty. Source paths are relative to workflow_root; use absolute paths in work/deck_ir.json. '
        'Retain original body/key_points in speaker_notes when a display expression changes their literal notation. '
        'Do not write page bboxes. Keep full evidence refs; use native formulas and explicit graph relationships. '
        'For every brief with metadata.story_explain, write semantic.explanation with the same obligations and '
        'evidence_refs. Set carrier to the native object actually used and status=bound; if a required obligation '
        'cannot be carried, use status=waived or unsupported with a note, never drop it silently. Use inline_math or '
        'formula for quantity, a native list/table/layout_tree for parallel_items, layout_tree for grouped_panels, '
        'table/columns for comparison, process/dag for ordered_steps, mechanism/dag for relation and path for curve. '
        'If a brief has metadata.story_compact_process, ignore the smaller RPA process placeholder and write one '
        'type=process graphic with layout=compact, one square rect node per declared item, in the declared order; '
        'do not collapse the chain to the RPA three-slot page.'}


def execute(stage, job):
    out = Path(job['request']['out_dir'])
    work = out/'work'
    request = job['request']
    if stage == 'evidence':
        if request['source_kind'] == 'workflow':
            workflow = Path(request['source'])
            value = read(workflow)
            outputs = [Path(p) for p, hashed in resources(workflow).items() if hashed is not None]
        else:
            args = work/'evidence_args.json'
            # Forward the declared intent when present; PaperWorkflow honours it
            # instead of re-inferring from the wording.
            queries = [{'query': q['query'], **({'intent': q['intent']} if q.get('intent') else {})}
                       for q in read(work/'queries.json')]
            write(args, {'source_path': request['source'], 'output_dir': str(out/'evidence'),
                         'queries': queries,
                         'supplementary_paths': request.get('supplementary_paths', []),
                         'supplementary_content_included': request.get('supplementary_content_included', False)})
            result = run([sys.executable, Path(__file__).parent/'bridges/paperworkflow_bridge.py',
                          '--op', 'literature_workflow', '--args', args], ROOT, out, 'evidence', 1200)
            if not result.get('ok') or result['result'].get('status') == 'blocked':
                raise Failure('EVIDENCE_DEPENDENCY_FAILED', result.get('message') or 'PaperWorkflow cannot ingest the source; run doctor.')
            workflow = Path(result['result']['workflow_path'])
            value = read(workflow)
            outputs = [out/'evidence']
        from pwf2rpa import Workflow
        from pwf2rpa.errors import AdapterError
        try:
            Workflow(value).validate()
        except AdapterError as error:
            raise Failure('EVIDENCE_INVALID', str(error), 'replan', 'evidence' if request['source_kind'] == 'workflow' else 'queries') from error
        if value.get('synthesis_readiness', {}).get('readiness') != 'ready':
            # Keep the failing gate, but also carry per-query diagnostics so the
            # replan action says which query to fix instead of "revise queries".
            feedback = dict(value.get('synthesis_readiness') or {})
            retrieval = (value.get('quality_dimensions') or {}).get('retrieval') or {}
            feedback['retrieval'] = {k: retrieval.get(k) for k in
                                     ('score', 'readiness', 'mean_coverage_ratio', 'coverage_domain',
                                      'precision_ratio', 'support_span_exposure_ratio', 'warnings')}
            feedback['per_query'] = [
                {**{k: item.get(k) for k in ('query_id', 'intent', 'status', 'precision_ratio')},
                 'coverage': item.get('coverage')}
                for item in retrieval.get('diagnostics') or []
            ]
            write(work/'evidence_feedback.json', feedback)
            raise Failure('EVIDENCE_NOT_READY', 'Evidence synthesis requires source / supplementary review; inspect evidence_feedback.json. '
                          'Repair the original evidence bundle or revise queries / source material before advancing.', 'replan',
                          'evidence' if request['source_kind'] == 'workflow' else 'queries')
        write(work/'evidence_pointer.json', {'workflow': str(workflow)})
        return [*outputs, work/'evidence_pointer.json']
    if stage == 'story_prompt':
        workflow = read(work/'evidence_pointer.json')['workflow']
        selection = job['inputs']
        pwf_cli(out, workflow, '--make-story-prompt', work/'story_prompt.json', '--story-model', selection['model'],
                '--story-reasoning', selection['reasoning_effort'], '--model-selected-by-user')
        prompt = read(work/'story_prompt.json')
        prompt['request'] = {key: request[key] for key in ('language', 'presentation_type', 'requirements')}
        prompt['instructions'] += ('\n\nPresentation request: '+json.dumps(prompt['request'], ensure_ascii=False)+
                                   '\nUse the requested presentation language while preserving scientific terms and uncertainty.')
        write(work/'story_prompt.json', prompt)
        return [work/'story_prompt.json']
    if stage == 'rpa':
        workflow = read(work/'evidence_pointer.json')['workflow']
        pwf_cli(out, workflow, '--story', work/'story_plan.json', '--strict', '--out', work/'rpa_input.json')
        payload = read(work/'rpa_input.json')
        model = rpa('normalize-content', work/'rpa_input.json', out)
        write(work/'normalized_content.json', model)
        count = request.get('slide_count')
        if count and count != len(payload['slide_briefs']):
            raise Failure('SLIDE_COUNT_REPLAN', 'Requested slide_count differs from the complete Story briefs; revise Story instead of truncating briefs.', 'replan', 'story')
        write(work/'plan_input.json', {**payload, 'presentation_type': request['presentation_type']})
        plan = rpa('plan', work/'plan_input.json', out)
        write(work/'deck_plan.json', plan)
        write(work/'validation_input.json', {'slides': plan['slides'], 'content_model': model})
        validation = rpa('validate-deck', work/'validation_input.json', out)
        write(work/'rpa_validation.json', validation)
        prompt = ir_prompt(read(workflow), payload, model, plan)
        prompt['workflow_root'] = str(Path(workflow).parent)
        prompt['request'] = {key: request[key] for key in ('language', 'presentation_type', 'requirements')}
        write(work/'ir_prompt.json', prompt)
        return [work/name for name in ('rpa_input.json', 'normalized_content.json', 'deck_plan.json', 'rpa_validation.json', 'ir_prompt.json')]
    if stage == 'design':
        compiler('visual-prompt', out, '--ir', work/'deck_ir.json', '--out', work/'visual_prompt.json',
                 '--requirements', request.get('requirements', ''))
        return [work/'visual_prompt.json']
    if stage == 'build':
        if not shutil.which('officecli'):
            raise Failure('OFFICECLI_MISSING', 'Install OfficeCLI >=1.0.152 and add it to PATH.')
        ir = work/'deck_ir.json'
        from deck_compiler.visual_planner import pending_design
        pending = pending_design(read(ir))
        if pending['academic_design_required'] or pending['slide_ids']:
            compiler('apply-visual-plan', out, '--ir', ir, '--proposal', work/'visual_proposal.json', '--out', work/'designed.deck_ir.json')
            ir = work/'designed.deck_ir.json'
        compiler('build', out, '--ir', ir, '--out', out/'build', '--skip-native', timeout=540)
        qa = read(out/'build/qa_report.json')
        if qa['counts']['FAIL']:
            first = next(i for i in qa['items'] if i['severity'] == 'FAIL')
            raise classify(first['rule'], first['message'], 'build')
        if qa.get('artifact_sha256') != sha(out/'build/candidate.pptx') or qa.get('artifact_sha256') != sha(out/'build/staging.pptx'):
            raise Failure('CANDIDATE_EVIDENCE_STALE', 'Candidate / staging / QA hashes disagree.', 'review_required', 'build')
        layout = read(out/'build/layout.json')
        extra = [Path(asset['path']) for asset in layout['assets'].values()]
        extra += [Path(e['contract']['font_file']) for slide in layout['slides'] for e in slide['elements'] if e.get('contract')]
        return [*[out/'build'/name for name in ('candidate.pptx', 'staging.pptx', 'qa_report.json', 'layout_feedback.json', 'layout.json')], *extra]
    raise Failure('STAGE_UNSUPPORTED', f'Unknown adapter {stage}')
