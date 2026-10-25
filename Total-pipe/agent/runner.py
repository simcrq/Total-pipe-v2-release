"""Drive stages until the next human/agent decision; never author scientific content."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid

from . import COMPONENT
from . import adapters as a
from .state import (JobError, read, write, sha, digest, dependency, checkpoint, valid_record,
                    locked, save, locate, home, confined)
from .state import validate_job

TABLE = read(Path(__file__).with_name('stages.json'))
STAGES = TABLE['stages']
BY_ARTIFACT = {s['artifact']: s for s in STAGES if 'artifact' in s}
NAMES = [s['id'] for s in STAGES]


def design_complete(job):
    path = Path(job['request']['out_dir'])/'work/deck_ir.json'
    if not path.is_file():
        return False
    from deck_compiler.visual_planner import pending_design
    try:
        a.check_ir(read(path))
        pending = pending_design(read(path))
        return not pending['academic_design_required'] and not pending['slide_ids']
    except (ValueError, KeyError, TypeError):
        return False


def current(job):
    previous = []
    for stage in STAGES:
        if job['request']['source_kind'] not in stage.get('sources', [job['request']['source_kind']]):
            continue
        if stage.get('skip_if') == 'design_complete' and design_complete(job):
            continue
        upstream = dependency(job, previous)
        if stage['kind'] == 'input':
            values = job['request'] if stage['id'] == 'intake' else job.get('inputs', {})
            if not all(values.get(key) for key in stage['requires']):
                return stage, upstream
            previous.append({'input': stage['id'], 'values': values})
        elif stage['kind'] == 'terminal':
            return stage, upstream
        else:
            record = job['checkpoints'].get(stage['id'])
            if not valid_record(record, upstream):
                return stage, upstream
            previous.append(record)
    raise JobError('JOB_STATE_INVALID', 'No terminal stage')


def invalidate(job, stage_id):
    for name in NAMES[NAMES.index(stage_id):]:
        job['checkpoints'].pop(name, None)
    job.pop('last_error', None)


def envelope(job, stage, failure=None):
    out = Path(job['request']['out_dir'])
    work = out/'work'
    sid, kind = stage['id'], stage['kind']
    action = {'type': 'none', 'reason': 'ADVANCE_REQUIRED', 'tool': 'totalpipe_advance'}
    status = 'running'
    if kind == 'input':
        status = 'waiting_agent'
        action = {'type': 'provide_input', 'reason': 'MODEL_SELECTION_REQUIRED',
                  'fields': [{'name': 'model', 'type': 'string'},
                             {'name': 'reasoning_effort', 'enum': ['high', 'xhigh', 'max', 'ultra']},
                             {'name': 'selected_by_user', 'const': True}],
                  'note': 'Use the user’s explicit current or earlier model choice; never select silently.'}
    if kind == 'agent':
        status = 'waiting_agent'
        artifact = stage['artifact']
        prompt = {'story': work/'story_prompt.json', 'deck_ir': work/'ir_prompt.json',
                  'visual_design': work/'visual_prompt.json'}.get(sid)
        action = {'type': 'invoke_subagent' if sid == 'story' else 'author_artifact',
            'reason': 'STORY_PLANNING_REQUIRED' if sid == 'story' else artifact.upper()+'_REQUIRED',
            'artifact_kind': artifact, 'expected_output': str(work/(artifact+'.json')),
            'instructions_ref': stage['instructions_ref'], 'max_attempts': stage['max_attempts'],
            'instructions_path': str(COMPONENT/TABLE['instructions'][stage['instructions_ref']].split('#')[0])
                                 if sid in ('story', 'queries') else str(prompt),
            **({'instructions_anchor': TABLE['instructions'][stage['instructions_ref']].split('#', 1)[1]}
               if '#' in TABLE['instructions'][stage['instructions_ref']] else {}),
            **({'input_path': str(prompt)} if prompt else {}),
            **({'schema_path': str(Path(__file__).parent/'schemas/queries.schema.json')} if sid == 'queries' else {}),
            **({'required_capability': 'independent_subagent', 'delegation': job['inputs']} if sid == 'story' else {})}
    if kind == 'terminal':
        status = 'candidate_ready'
        action = {'type': 'none', 'reason': 'CANDIDATE_READY', 'candidate': str(out/'build/candidate.pptx'),
                  'promotion': {'available': False, 'reason': 'FINAL_PROMOTION_IS_CLI_ONLY'}}
    issues = []
    if failure:
        target_stage = next((s for s in STAGES if s['id'] == failure.target), stage)
        status = 'blocked'
        action = {'type': failure.action, 'reason': failure.code, 'remedy': a.redact(str(failure)),
                  'target_stage': failure.target or sid,
                  'feedback_path': failure.log or str(work/'evidence_feedback.json' if failure.code == 'EVIDENCE_NOT_READY'
                                                      else out/'build/layout_feedback.json'),
                  'constraints': ['Preserve complete scientific terms, figures, equations and font floors.']}
        action['max_attempts'] = target_stage.get('max_attempts', 1)
        if failure.action == 'author_artifact':
            target = next((s for s in STAGES if s['id'] == failure.target), stage)
            action.update({k: v for k, v in envelope(job, target)['next_action'].items()
                           if k not in ('type', 'reason')})
        if failure.action == 'review_required':
            action['qa_report'] = str(out/'build/qa_report.json')
        issues = [{'code': failure.code, 'severity': 'FAIL', 'message': a.redact(str(failure)),
                   **({'path': failure.log} if failure.log else {})}]
    qa_path = out/'build/qa_report.json'
    qa = None
    if kind == 'terminal' and qa_path.is_file():
        from deck_compiler.qa_review import show_qa
        try:
            qa = show_qa(out/'build', include_acked=True)
        except (OSError, ValueError) as error:
            return error_envelope(JobError('QA_STATE_INVALID', str(error), 'Repair the candidate review records or rebuild.'), job['job_id'])
    return {'job_id': job['job_id'], 'request': job['request'], 'status': status, 'stage': sid,
            'stage_index': NAMES.index(sid)+1, 'stage_total': len(STAGES), 'next_action': action,
            'artifacts': [{'stage': name, 'path': path, 'sha256': hashed}
                          for name, record in job['checkpoints'].items() for path, hashed in record['files'].items()],
            'issues': issues, 'blocking': bool(failure), 'retry': {'safe': False if failure else True,
            'max': (target_stage if failure else stage).get('max_attempts', 1)},
            **({'qa': {'counts': qa['counts'], 'unacked_count': qa.get('unacked_count', qa['counts']['REVIEW'])},
                'candidate': str(out/'build/candidate.pptx')} if qa else {})}


def error_envelope(error, job_id=None):
    return {'job_id': job_id, 'status': 'blocked', 'stage': None, 'stage_index': 0, 'stage_total': len(STAGES),
        'next_action': {'type': 'resolve_dependency', 'reason': error.code, 'remedy': str(error)+' '+error.remedy},
        'artifacts': [], 'issues': [{'code': error.code, 'severity': 'FAIL', 'message': str(error)}],
        'blocking': True, 'retry': {'safe': error.code == 'JOB_BUSY', 'max': 1}}


def start(source, out_dir, language, presentation_type, source_kind='auto', requirements='', queries=None,
          slide_count=None, supplementary_paths=None, supplementary_content_included=False):
    source, out = Path(source).expanduser().resolve(), Path(out_dir).expanduser().resolve()
    if not source.is_file():
        return error_envelope(JobError('SOURCE_NOT_FOUND', 'Source must be an existing file.', 'Provide its absolute path.'))
    if source_kind == 'auto':
        source_kind = {'.pdf': 'pdf', '.md': 'markdown'}.get(source.suffix.lower())
        if source.suffix.lower() == '.json':
            try:
                value = read(source)
                if not isinstance(value, dict):
                    raise ValueError('Expected a JSON object')
            except ValueError:
                return error_envelope(JobError('SOURCE_INVALID_JSON', 'Source JSON must be an object.', 'Repair the source JSON before starting.'))
            source_kind = 'deck_ir' if value.get('schema_version') == '2.0' else 'workflow'
    if source_kind not in ('pdf', 'markdown', 'workflow', 'deck_ir'):
        raise ValueError('Unsupported source_kind')
    if not language.strip() or not presentation_type.strip():
        raise ValueError('language and presentation_type are required')
    if slide_count is not None and (type(slide_count) is not int or not 1 <= slide_count <= 40):
        raise ValueError('slide_count must be in [1,40]')
    request = {'source': str(source), 'out_dir': str(out), 'language': language,
        'presentation_type': presentation_type, 'source_kind': source_kind, 'requirements': requirements,
        'supplementary_content_included': supplementary_content_included,
        'slide_count': slide_count, 'supplementary_paths': [str(Path(p).expanduser().resolve()) for p in supplementary_paths or []]}
    try:
        with locked(out):
            path = out/'.totalpipe/job.json'
            if path.exists():
                try:
                    job = read(path)
                    validate_job(job)
                    if job['request'] != request:
                        return error_envelope(JobError('JOB_OUTPUT_IN_USE', 'Output belongs to a different request.', 'Use a new output directory.'))
                    if queries is not None and source_kind in ('pdf', 'markdown'):
                        a.check_queries(queries)
                        query_path = out/'work/queries.json'
                        if not query_path.is_file() or read(query_path) != queries:
                            invalidate(job, 'queries')
                            write(query_path, queries)
                            stage, upstream = current(job)
                            checkpoint(job, 'queries', [query_path], upstream)
                except a.Failure:
                    raise
                except (ValueError, KeyError, TypeError):
                    return error_envelope(JobError('JOB_STATE_INVALID', 'Existing job cannot be reconstructed safely.'))
            else:
                (out/'work').mkdir(parents=True, exist_ok=True)
                job = {'schema_version': 1, 'job_id': uuid.uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(),
                       'request': request, 'checkpoints': {}, 'inputs': {}, 'attempts': {}}
                save(job)
                write(home()/'jobs'/(job['job_id']+'.json'), {'out_dir': str(out)})
                if queries is not None and source_kind in ('pdf', 'markdown'):
                    a.check_queries(queries)
                    write(out/'work/queries.json', queries)
                    stage, upstream = current(job)
                    checkpoint(job, stage['id'], [out/'work/queries.json'], upstream)
                if source_kind == 'deck_ir':
                    write(out/'work/ir_prompt.json', {**a.ir_prompt({}, {}, {}, {}),
                        'imported_deck_ir': read(source), 'source_base': str(source.parent),
                        'request': {key: request[key] for key in ('language', 'presentation_type', 'requirements')}})
                    a.import_ir(source, out/'work/deck_ir.json')
                    stage, upstream = current(job)
                    checkpoint(job, 'deck_ir', [Path(p) for p, hashed in a.resources(out/'work/deck_ir.json').items() if hashed is not None], upstream)
            write(home()/'jobs'/(job['job_id']+'.json'), {'out_dir': str(out)})
    except (JobError, OSError) as error:
        return error_envelope(error if isinstance(error, JobError) else JobError('OUTPUT_UNWRITABLE', str(error)))
    except a.Failure as error:
        return envelope(job, current(job)[0], error)
    return advance(job['job_id'])


def _accept(job, stage, upstream, kind, path):
    work = Path(job['request']['out_dir'])/'work'
    target = BY_ARTIFACT[kind]
    path = confined(path, work)
    if target['id'] != stage['id']:
        old = job['checkpoints'].get(target['id'], {})
        if old.get('files', {}).get(str(path)) == sha(path):
            return  # Continue unfinished downstream components even for a duplicate submission.
        raise JobError('ARTIFACT_STAGE_MISMATCH', f'Current stage is {stage["id"]}.', 'Submit its expected artifact first.')
    attempt_key = digest([stage['id'], upstream])
    attempts = job['attempts'].setdefault(attempt_key, {'stage': stage['id'], 'upstream': upstream, 'count': 0, 'rejected': []})
    if attempts['count'] >= target['max_attempts']:
        raise a.Failure('REPLAN_LIMIT_REACHED', 'Revision budget exhausted; revise upstream inputs or request manual review.', 'review_required', stage['id'])
    if sha(path) in attempts['rejected']:
        old = job.get('last_error', {})
        raise a.Failure(old.get('code', 'ARTIFACT_UNCHANGED'),
                        'This artifact was already rejected. Revise it using the recorded feedback before resubmitting.',
                        old.get('action', 'replan'), stage['id'], old.get('log'))
    try:
        try:
            value = read(path)
        except ValueError as error:
            raise a.Failure('ARTIFACT_INVALID_JSON', 'Write valid UTF-8 JSON to expected_output.', 'author_artifact', stage['id']) from error
        if kind == 'queries':
            a.check_queries(value)
        elif kind == 'story_plan':
            workflow = read(work/'evidence_pointer.json')['workflow']
            a.check_story(read(work/'story_prompt.json'), value, read(workflow))
        elif kind == 'deck_ir':
            a.check_ir(value, read(work/'normalized_content.json') if (work/'normalized_content.json').exists() else None)
        elif kind == 'visual_proposal':
            from deck_compiler.visual_planner import apply_proposal
            try:
                apply_proposal(read(work/'deck_ir.json'), value)
            except ValueError as error:
                raise a.Failure('VISUAL_PLAN_INCOMPLETE', str(error), 'replan', 'visual_design') from error
    except a.Failure:
        hashed = sha(path)
        if hashed not in attempts['rejected']:
            attempts['rejected'].append(hashed)
            attempts['count'] += 1
        save(job)
        raise
    destination = work/(kind+'.json')
    if destination != path:
        if kind == 'deck_ir':
            a.import_ir(path, destination)
        else:
            write(destination, value)
    paths = [Path(p) for p, hashed in a.resources(destination).items() if hashed is not None] if kind == 'deck_ir' else [destination]
    checkpoint(job, stage['id'], paths, upstream)
    job.pop('last_error', None)


def advance(job_id, artifact_kind=None, artifact_path=None, inputs=None, replan_from=None, acknowledge=None):
    try:
        out, _ = locate(job_id)
        with locked(out):
            _, job = locate(job_id)
            stage, upstream = current(job)
            try:
                if replan_from:
                    if replan_from not in NAMES or replan_from in ('intake', 'candidate_ready'):
                        raise ValueError('Invalid replan_from')
                    invalidate(job, replan_from)
                    stage, upstream = current(job)
                if inputs is not None:
                    if (not isinstance(inputs, dict) or set(inputs) != {'model', 'reasoning_effort', 'selected_by_user'} or
                            not isinstance(inputs['model'], str) or not inputs['model'].strip() or
                            inputs['reasoning_effort'] not in ('high', 'xhigh', 'max', 'ultra') or inputs['selected_by_user'] is not True):
                        raise ValueError('Provide explicit user-selected model, high-or-stronger reasoning_effort and selected_by_user=true')
                    if stage['id'] != 'model_selection' and not job['inputs']:
                        raise ValueError('Model input is only accepted at model_selection')
                    job['inputs'] = inputs
                    stage, upstream = current(job)
                if artifact_kind is not None or artifact_path is not None:
                    if artifact_kind not in BY_ARTIFACT or not artifact_path:
                        raise ValueError('artifact_kind and artifact_path must identify a supported artifact')
                    _accept(job, stage, upstream, artifact_kind, artifact_path)
                if acknowledge is not None:
                    if not isinstance(acknowledge, dict) or set(acknowledge) != {'reviewer', 'note', 'review_ids'}:
                        raise ValueError('acknowledge requires reviewer, note and explicit review_ids')
                    if stage['kind'] != 'terminal':
                        raise ValueError('Only a built candidate can be acknowledged')
                    from deck_compiler.qa_review import acknowledge_reviews
                    acknowledge_reviews(out/'build', acknowledge['reviewer'], acknowledge['note'], acknowledge['review_ids'])
                    record = job['checkpoints']['build']
                    checkpoint(job, 'build', record['files'], record['upstream'])
                save(job)
                for _ in range(len(STAGES)):
                    stage, upstream = current(job)
                    if stage['kind'] != 'component':
                        return envelope(job, stage)
                    paths = a.execute(stage['adapter'], job)
                    job.pop('last_error', None)
                    checkpoint(job, stage['id'], paths, upstream)
                raise a.Failure('STAGE_LOOP', 'Stage did not reach a decision; inspect checkpoints.')
            except a.Failure as failure:
                if not failure.log:
                    feedback = out/'work/submission_feedback.json'
                    write(feedback, {'code': failure.code, 'message': a.redact(str(failure)), 'stage': stage['id'],
                                     'target_stage': failure.target})
                    if failure.code != 'EVIDENCE_NOT_READY' and not (out/'build/layout_feedback.json').exists():
                        failure.log = str(feedback)
                job['last_error'] = {'code': failure.code, 'message': a.redact(str(failure)), 'action': failure.action,
                                     'target': failure.target, 'log': failure.log, 'stage': stage['id']}
                if failure.action in ('replan', 'author_artifact') and failure.target in NAMES and failure.target != stage['id']:
                    invalidate(job, failure.target)
                    target, target_upstream = current(job)
                    if target['kind'] == 'agent' and target['id'] == failure.target:
                        key = digest([target['id'], target_upstream])
                        record = job['attempts'].setdefault(key, {'stage': target['id'], 'upstream': target_upstream,
                                                                 'count': 0, 'rejected': []})
                        artifact = out/'work'/(target['artifact']+'.json')
                        hashed = sha(artifact)
                        if hashed and hashed not in record['rejected']:
                            record['count'] += 1
                            record['rejected'].append(hashed)
                    job['last_error'] = {'code': failure.code, 'message': a.redact(str(failure)), 'action': failure.action,
                                         'target': failure.target, 'log': failure.log, 'stage': stage['id']}
                pending, pending_upstream = current(job)
                job['last_error'].update({'at_stage': pending['id'], 'upstream': pending_upstream})
                save(job)
                return envelope(job, stage, failure)
            except (OSError, KeyError) as error:
                failure = a.Failure('COMPONENT_FAILED', a.redact(str(error)))
                pending, pending_upstream = current(job)
                job['last_error'] = {'code': failure.code, 'message': str(failure), 'action': failure.action,
                                     'target': failure.target, 'log': failure.log, 'stage': stage['id'],
                                     'at_stage': pending['id'], 'upstream': pending_upstream}
                save(job)
                return envelope(job, stage, failure)
    except JobError as error:
        return error_envelope(error, job_id)


def status(job_id):
    try:
        out, _ = locate(job_id)
        with locked(out):
            _, job = locate(job_id)
            stage, upstream = current(job)
            old = job.get('last_error')
            if old and (old.get('at_stage') != stage['id'] or old.get('upstream') != upstream):
                old = None
            failure = a.Failure(old['code'], old['message'], old['action'], old.get('target'), old.get('log')) if old else None
            return envelope(job, stage, failure)
    except JobError as error:
        return error_envelope(error, job_id)
