"""Install the bundled agent skills into a client's skill directory.

Each client reads ``<skills>/<name>/SKILL.md``, and this package already ships
its skills in exactly that layout, so installing one is a copy. Nothing here
provisions the interpreter or the MCP server; that is ``agent.installation``.
"""

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT/'skills'

# Where each client looks for personal skills. Both honour a config-dir override.
_TARGETS = {
    'claude': lambda: Path(os.environ.get('CLAUDE_CONFIG_DIR')
                           or Path.home()/'.claude')/'skills',
    'codex': lambda: Path(os.environ.get('CODEX_HOME')
                          or Path.home()/'.codex')/'skills',
}


def clients():
    return tuple(sorted(_TARGETS))


def source_dir(root=None):
    return Path(root) if root else SOURCE


def target_dir(client, root=None):
    """The client's skills directory; ``root`` overrides it for tests and packaging."""
    if root:
        return Path(root)
    if client not in _TARGETS:
        raise ValueError(f'unknown client {client!r}; expected one of {clients()}')
    return _TARGETS[client]()


def _files(directory):
    return {path.relative_to(directory): path for path in directory.rglob('*')
            if path.is_file() and '__pycache__' not in path.parts}


def _identical(left, right):
    mine, theirs = _files(left), _files(right)
    return (mine.keys() == theirs.keys()
            and all(mine[key].read_bytes() == theirs[key].read_bytes() for key in mine))


def plan(client, root=None, source=None):
    """One row per bundled skill: what installing it would do."""
    origin = source_dir(source)
    destination = target_dir(client, root)
    if not origin.is_dir():
        raise ValueError(f'no skills directory at {origin}')
    rows = []
    for folder in sorted(path for path in origin.iterdir() if path.is_dir()):
        target = destination/folder.name
        if not (folder/'SKILL.md').is_file():
            state, reason = 'invalid', 'no SKILL.md'
        elif not target.exists():
            state, reason = 'new', None
        elif _identical(folder, target):
            state, reason = 'unchanged', 'already installed'
        else:
            state, reason = 'update', 'differs from the bundled copy'
        rows.append({'name': folder.name, 'source': str(folder), 'target': str(target),
                     'state': state, 'reason': reason})
    return rows


def install(client, root=None, source=None, force=False, dry_run=False):
    """Copy every bundled skill into the client directory and report what happened."""
    rows = plan(client, root, source)
    result = {'client': client, 'target': str(target_dir(client, root)),
              'installed': [], 'updated': [], 'unchanged': [], 'skipped': []}
    for row in rows:
        state = row['state']
        if state == 'unchanged':
            result['unchanged'].append(row['name'])
            continue
        if state == 'invalid':
            result['skipped'].append({'name': row['name'], 'reason': row['reason']})
            continue
        if state == 'update' and not force:
            result['skipped'].append({'name': row['name'],
                                      'reason': 'exists and differs; pass --force to replace'})
            continue
        if dry_run:
            result['installed' if state == 'new' else 'updated'].append(row['name'])
            continue
        target = Path(row['target'])
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(row['source'], target,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        result['installed' if state == 'new' else 'updated'].append(row['name'])
    result['dry_run'] = bool(dry_run)
    result['status'] = 'PASS' if not result['skipped'] else 'PARTIAL'
    return result
