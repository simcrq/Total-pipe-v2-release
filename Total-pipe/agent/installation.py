"""Portable profiles, isolated handshake, conservative client configuration edits."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import uuid
import stat

from . import ROOT, COMPONENT

BEGIN = '# >>> total-pipe (managed by install.py) >>>'
END = '# <<< total-pipe <<<'


def profile_servers(profile, python):
    path = COMPONENT/('.mcp.json' if profile == 'agent' else '.mcp.advanced.json')
    servers = deepcopy(json.loads(path.read_text(encoding='utf-8'))['mcpServers'])
    for server in servers.values():
        server['cwd'] = str((COMPONENT/server.get('cwd', '.')).resolve())
        if server['command'] == 'python':
            server['command'] = str(Path(python).absolute())
        elif server['command'] == 'node':
            import shutil
            server['command'] = shutil.which('node') or 'node'
        server['env'] = {**server.get('env', {}), 'PYTHONUTF8': '1'}
    return servers


def handshake(server, timeout=45):
    messages = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                                 'clientInfo': {'name': 'total-pipe-installer', 'version': '1'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
    ]
    result = subprocess.run([server['command'], *server['args']], cwd=server['cwd'],
        input=''.join(json.dumps(message)+'\n' for message in messages), capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=timeout,
        env={**os.environ, **server.get('env', {}), 'PYTHONIOENCODING': 'utf-8'})
    if result.returncode:
        raise ValueError('MCP handshake process failed: '+result.stderr[-1000:])
    responses = {value['id']: value for line in result.stdout.splitlines() if line.strip()
                 for value in [json.loads(line)] if 'id' in value}
    if any(key not in responses or 'result' not in responses[key] for key in (1, 2)):
        raise ValueError('MCP initialize/tools/list failed')
    return {'server': responses[1]['result']['serverInfo'],
            'tools': [tool['name'] for tool in responses[2]['result']['tools']]}


def _prune_servers(value, names):
    result = deepcopy(value)
    table = result.get('mcp_servers', {})
    for name in names:
        table.pop(name, None)
    if not table:
        result.pop('mcp_servers', None)
    return result


def toml_config(text, servers):
    before = tomllib.loads(text)
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError('Invalid Total-pipe managed markers')
    outside = text
    old_names = []
    if BEGIN in text:
        match = re.search(r'(?m)^'+re.escape(BEGIN)+r'\r?\n[\s\S]*?^'+re.escape(END)+r'(?:\r?\n|$)', text)
        if not match:
            raise ValueError('Malformed managed block')
        old_names = list(tomllib.loads(match.group())['mcp_servers'])
        outside = text[:match.start()]+text[match.end():]
    baseline = tomllib.loads(outside)
    if _prune_servers(before, old_names) != _prune_servers(baseline, []):
        raise ValueError('Removing managed block would change unrelated TOML semantics; repair config manually.')
    conflicts = set(servers)&set(baseline.get('mcp_servers', {}))
    if conflicts:
        raise ValueError(f'Unmanaged MCP server conflict: {sorted(conflicts)}')
    lines = [BEGIN]
    for name, server in servers.items():
        lines.append(f'[mcp_servers.{name}]')
        for key in ('command', 'args', 'cwd', 'startup_timeout_sec', 'tool_timeout_sec', 'env_vars'):
            if key in server:
                lines.append(key+' = '+json.dumps(server[key], ensure_ascii=False))
        lines.append('env = { '+', '.join(json.dumps(k)+' = '+json.dumps(v) for k, v in server.get('env', {}).items())+' }')
    lines.append(END)
    updated = outside+('' if not outside or outside.endswith('\n') else '\n')+'\n'.join(lines)+'\n'
    if _prune_servers(tomllib.loads(updated), servers) != _prune_servers(baseline, []):
        raise ValueError('New configuration would change unrelated TOML semantics')
    return updated


def json_config(text, servers, force=False):
    value = json.loads(text) if text.strip() else {}
    if not isinstance(value, dict) or not isinstance(value.get('mcpServers', {}), dict):
        raise ValueError('Client configuration must be an object with mcpServers')
    table = value.setdefault('mcpServers', {})
    managed_cwds = {str(COMPONENT), str(ROOT/'PaperWorkflow'), str(ROOT/'research-ppt-assistant')}
    for name in ('total_pipe', 'total_pipe_v3', 'paperworkflow', 'research_ppt'):
        old = table.get(name)
        if isinstance(old, dict) and old.get('cwd') in managed_cwds:
            expected = ['-m', 'agent.mcp_server'] if name == 'total_pipe' else ['-m', 'deck_compiler.mcp_server'] if name == 'total_pipe_v3' else \
                       ['mcp_server.py'] if name == 'paperworkflow' else ['./server/mcp-server.mjs']
            if old.get('args') == expected:
                table.pop(name)
    profile = 'agent' if 'total_pipe' in servers else 'advanced'
    python = next(server['command'] for name, server in servers.items() if name != 'research_ppt')
    for name in list(table):
        old = table[name]
        if (isinstance(old, dict) and len(old.get('args', [])) >= 1 and
                old['args'][0] == str(COMPONENT/'agent/launch.py') and name in
                ('total_pipe', 'total_pipe_v3', 'paperworkflow', 'research_ppt')):
            table.pop(name)
    if (set(servers)&set(table)) and not force:
        raise ValueError('Unmanaged MCP server conflict; explicitly --force for JSON replacement.')
    table.update({name: {'command': python, 'args': [str(COMPONENT/'agent/launch.py'), '--profile', profile, '--service', name],
                         'env': server.get('env', {})} for name, server in servers.items()})
    return json.dumps(value, ensure_ascii=False, indent=2)+'\n'


def configure(path, client, servers, force=False, dry_run=False):
    path = Path(path).expanduser().resolve()
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    updated = toml_config(text, servers) if client == 'codex' else json_config(text, servers, force)
    if dry_run or updated == text:
        return {'path': str(path), 'changed': updated != text, 'dry_run': dry_run}
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]
        backup = path.with_name(path.name+'.bak.'+stamp)
        with os.fdopen(os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
            stream.write(path.read_bytes())
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    with os.fdopen(os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode), 'w', encoding='utf-8') as stream:
        stream.write(updated)
    os.replace(temp, path)
    return {'path': str(path), 'changed': True, 'backup': str(backup) if backup else None}
