"""Atomic checkpoints describe files; stage completion is always derived."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
from urllib.parse import unquote
import uuid

from . import ROOT


class JobError(ValueError):
    def __init__(self, code, message, remedy='Use a new output directory or repair the recorded job.'):
        super().__init__(message)
        self.code, self.remedy = code, remedy


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def sha(path):
    path = Path(path)
    if not path.is_file():
        return None
    with path.open('rb') as stream:
        result = hashlib.sha256()
        for part in iter(lambda: stream.read(1024*1024), b''):
            result.update(part)
        return result.hexdigest()


def snapshot(path):
    path = Path(path)
    if path.is_dir():
        return digest({str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*'))
                       if p.is_file() and not p.is_symlink()})
    return sha(path)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def home():
    return Path(os.environ.get('TOTALPIPE_AGENT_HOME', str(Path.home()/'.local/state/total-pipe'))).expanduser().resolve()


def locate(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise JobError('JOB_NOT_FOUND', 'Unknown job_id', 'Use the job_id returned by totalpipe_start.')
    try:
        pointer = read(home()/'jobs'/(job_id+'.json'))
        out = Path(pointer['out_dir']).resolve()
        job = read(out/'.totalpipe/job.json')
        validate_job(job)
        if job['job_id'] != job_id or job['request']['out_dir'] != str(out):
            raise ValueError('Job identity mismatch')
        if job.get('schema_version') != 1:
            raise ValueError('Unsupported job version')
        return out, job
    except FileNotFoundError as error:
        raise JobError('JOB_NOT_FOUND', 'Job record is missing', 'Call start again with the original source and output directory.') from error
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise JobError('JOB_STATE_INVALID', 'Job record is corrupt or inconsistent; authorization cannot be reconstructed.') from error


def validate_job(job):
    if (not isinstance(job, dict) or any(not isinstance(job.get(k), dict) for k in
            ('request', 'checkpoints', 'inputs', 'attempts')) or
            not all(isinstance(job['request'].get(k), str) and job['request'][k] for k in
                    ('source', 'out_dir', 'language', 'presentation_type', 'source_kind'))):
        raise ValueError('Malformed job record')
    if (job.get('schema_version') != 1 or not isinstance(job.get('job_id'), str) or
            not re.fullmatch(r'[a-f0-9]{32}', job['job_id'])):
        raise ValueError('Malformed job identity')
    inputs = job['inputs']
    if inputs and (set(inputs) != {'model', 'reasoning_effort', 'selected_by_user'} or
                   not isinstance(inputs.get('model'), str) or not inputs['model'].strip() or
                   inputs.get('reasoning_effort') not in ('high','xhigh','max','ultra') or inputs.get('selected_by_user') is not True):
        raise ValueError('Malformed user model selection')
    for record in job['checkpoints'].values():
        if (not isinstance(record, dict) or not isinstance(record.get('files'), dict) or
                not isinstance(record.get('upstream'), str) or any(not isinstance(path, str) for path in record['files'])):
            raise ValueError('Malformed checkpoint')


@contextmanager
def locked(out):
    folder = Path(out)/'.totalpipe'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise JobError('JOB_BUSY', 'Another process is advancing this job.', 'Retry after the active process finishes.') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def save(job):
    write(Path(job['request']['out_dir'])/'.totalpipe/job.json', job)


def confined(path, root):
    raw, root = Path(path).absolute(), Path(root).resolve()
    if '..' in raw.parts:
        raise JobError('ARTIFACT_PATH_INVALID', 'Parent traversal is forbidden.', 'Write the artifact inside the job work directory.')
    if any(parent.is_symlink() for parent in [raw, *raw.parents] if parent != parent.parent):
        raise JobError('ARTIFACT_PATH_INVALID', 'Symlink artifacts are forbidden.', 'Use a regular file in work/.')
    resolved = raw.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise JobError('ARTIFACT_PATH_INVALID', 'Artifact must be an existing file inside work/.', 'Use expected_output from next_action.')
    return resolved


def resources(path):
    """Files explicitly referenced by an imported IR or evidence bundle."""
    path = Path(path)
    result = {str(path): snapshot(path)}
    if path.suffix.lower() == '.md' and path.is_file():
        for ref in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            ref = ref.strip('<>').split(' "', 1)[0].split('#', 1)[0]
            if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', ref):
                target = Path(unquote(ref))
                if not target.is_absolute():
                    target = path.parent/target
                result[str(target)] = snapshot(target)
        return result
    try:
        value = read(path)
        if value.get('schema_version') == '2.0':
            refs = [a['path'] for a in value.get('assets', {}).values()]
            refs += [value.get('theme', {}).get(k) for k in ('font_file', 'bold_font_file', 'background_image')]
        else:
            artifacts = value.get('artifacts', {})
            refs = ['paper.md', 'evidence.md', 'document.manifest.json', 'bundle.manifest.json']
            refs += artifacts.get('figure_asset_paths', [])
        for ref in refs:
            if not isinstance(ref, str):
                continue
            target = Path(ref)
            if not target.is_absolute():
                target = path.parent/target
            result[str(target)] = snapshot(target)
    except (ValueError, AttributeError, KeyError, TypeError):
        pass
    return result


def code_hash():
    files = list(Path(__file__).parent.rglob('*.py'))+list(Path(__file__).parent.rglob('*.json'))
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                              text=True, encoding='utf-8', errors='replace').stdout.strip() if (ROOT/'.git').exists() and shutil.which('git') else None
    return digest([revision, {str(p.relative_to(ROOT)): sha(p) for p in sorted(files)}])


def dependency(job, previous):
    request = job['request']
    inputs = resources(request['source'])
    for path in request.get('supplementary_paths', []):
        inputs.update(resources(path))
    return digest({'request': request, 'source_files': inputs,
                   'code': code_hash(), 'previous': previous})


def valid_record(record, upstream):
    return bool(record and record.get('upstream') == upstream and record.get('files') and
                all(expected is not None and snapshot(path) == expected for path, expected in record['files'].items()))


def checkpoint(job, stage, paths, upstream):
    files = {str(Path(path).resolve()): snapshot(path) for path in paths}
    if not files or any(value is None for value in files.values()):
        raise JobError('STAGE_OUTPUT_MISSING', 'A component did not produce every required output.', 'Inspect its log and retry the current stage.')
    job['checkpoints'][stage] = {'upstream': upstream, 'files': files}
    save(job)
