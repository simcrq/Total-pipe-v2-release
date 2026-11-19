"""Installer targets and the native DeepSeek Harness profile adapter."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from . import COMPONENT


CLIENTS = {
    'codex': ('Codex', 'codex'),
    'claude': ('Claude Code', 'claude'),
    'workbuddy': ('WorkBuddy', 'workbuddy'),
    'opencode': ('OpenCode', 'opencode'),
    'gemini': ('Gemini CLI', 'gemini'),
    'deepseek': ('DeepSeek Harness', 'dsh'),
}


def client_home(client):
    home = Path.home()
    if client == 'opencode':
        return Path(os.environ.get('OPENCODE_CONFIG_DIR')
                    or Path(os.environ.get('XDG_CONFIG_HOME') or home/'.config')/'opencode').expanduser()
    if client == 'gemini':
        return Path(os.environ.get('GEMINI_CLI_HOME') or home).expanduser()/'.gemini'
    if client == 'workbuddy':
        return home/'.workbuddy'
    override, fallback = {
        'codex': ('CODEX_HOME', '.codex'), 'claude': ('CLAUDE_CONFIG_DIR', '.claude'),
        'deepseek': ('DSH_HOME', '.dsh'),
    }[client]
    return Path(os.environ.get(override) or home/fallback).expanduser()


def default_config(client):
    home = client_home(client)
    if client == 'opencode':
        explicit = os.environ.get('OPENCODE_CONFIG')
        if explicit:
            return Path(explicit).expanduser()
        jsonc = home/'opencode.jsonc'
        return jsonc if jsonc.is_file() else home/'opencode.json'
    if client == 'claude':
        return (home if os.environ.get('CLAUDE_CONFIG_DIR') else Path.home())/'.claude.json'
    if client == 'deepseek':
        return None
    return home/{'codex': 'config.toml', 'workbuddy': 'mcp.json', 'gemini': 'settings.json'}[client]


def detect_clients():
    return [client for client, (_, binary) in CLIENTS.items()
            if shutil.which(binary) or client_home(client).is_dir()
            or (default_config(client) or client_home(client)).is_file()]


def opencode_version():
    binary = shutil.which('opencode')
    if binary:
        try:
            result = subprocess.run([binary, '--version'], capture_output=True, text=True,
                                    check=True, timeout=5)
            match = re.search(r'\b([12])\.\d+\.\d+(?:\s|$|-)', result.stdout)
            if match:
                return match[1]
        except (OSError, subprocess.SubprocessError):
            pass
    return '2'


def deepseek_plan(venv, profile, source=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', profile):
        raise ValueError('Use a simple DeepSeek profile name, such as web.')
    if source:
        cwd = source.expanduser().resolve()
        if not (cwd/'package.json').is_file():
            raise ValueError('--dsh-source must be a built DeepSeek Harness source checkout.')
        binary = shutil.which('pnpm')
        command = [binary or 'pnpm', 'dsh']
    else:
        cwd = COMPONENT.parent
        binary = shutil.which('dsh')
        command = [binary or 'dsh']
    bundle = venv/'totalpipe-dsh-mcp'
    return {'path': str(bundle), 'profile': profile, 'cwd': str(cwd), 'cli_available': bool(binary),
            'register': [*command, 'plugin', '--profile', profile, 'add', str(bundle)],
            'inspect': [*command, '--profile', profile, '--dump-config']}


def register_deepseek(plan, servers):
    """Install one scoped configuration bundle through the official DSH CLI."""
    from .installation import write_config
    bundle = Path(plan['path'])
    manifest = {'name': 'totalpipe-dsh-mcp', 'version': '1.0.0', 'private': True,
                'files': ['cordis.patch.yml'], 'dsh': {'bundle': {'patch': './cordis.patch.yml'}}}
    rows = [{'id': 'totalpipe-mcp-'+name.replace('_', '-'), 'name': '@deepseek-ai/dsh-mcp-client',
             'config': {'serverName': name, 'transport': 'stdio', 'command': spec['command'],
                        'args': spec['args'], 'cwd': spec['cwd'], 'env': spec['env'],
                        'startupTimeoutMs': spec.get('startup_timeout_sec', 30)*1000,
                        'toolCallTimeoutMs': spec.get('tool_timeout_sec', 1800)*1000}}
            for name, spec in servers.items()]
    # JSON is valid YAML and quotes arrays, Windows paths and control characters safely.
    for filename, value in (('package.json', manifest), ('cordis.patch.yml', [{'insert': rows}])):
        path = bundle/filename
        old = path.read_text(encoding='utf-8') if path.is_file() else ''
        write_config(path, old, json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    subprocess.run(plan['register'], cwd=plan['cwd'], check=True, capture_output=True, text=True, timeout=120)
    result = subprocess.run(plan['inspect'], cwd=plan['cwd'], check=True, capture_output=True, text=True, timeout=30)
    if not all(row['id'] in result.stdout for row in rows):
        raise ValueError('DeepSeek registered the bundle but could not verify it in the selected profile.')
    return {'path': str(bundle), 'profile': plan['profile'], 'verified_profile': True}
