#!/usr/bin/env python3
"""Install Total-pipe for a supported AI harness from this checkout."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'Total-pipe'))

from agent.harnesses import CLIENTS, default_config, deepseek_plan, detect_clients, opencode_version, register_deepseek


def reply(status, **values):
    print(json.dumps({'status': status, **values}, ensure_ascii=True))
    return 0 if status in ('PASS', 'PARTIAL', 'DRY_RUN') else 1


def native_python(requested):
    """Find an existing Python 3.12+ when the default on PATH is older."""
    candidates = [[requested]] if requested else [[name] for name in ('python3.12', 'python3.13', 'python3.14')]
    if not requested and os.name == 'nt':
        candidates += [['py', '-3.12'], ['py', '-3.13'], ['py', '-3.14']]
    probe = 'import sys; print(sys.executable) if sys.version_info >= (3,12) else sys.exit(1)'
    for argv in candidates:
        if not shutil.which(argv[0]):
            continue
        try:
            result = subprocess.run([*argv, '-c', probe], check=True, capture_output=True, text=True, timeout=10)
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', choices=(*CLIENTS, 'auto', 'none'), default='none')
    parser.add_argument('--list-clients', action='store_true', help='Print supported harnesses and local detections as JSON')
    parser.add_argument('--profile', choices=('agent', 'advanced'), default='agent')
    parser.add_argument('--python', help='Python 3.12+ interpreter to create the virtual environment')
    parser.add_argument('--venv', type=Path, default=ROOT/'.venv')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT/'install-report.json')
    parser.add_argument('--skills-root', type=Path, help='Override where bundled skills are copied')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--skip-deps', action='store_true', help='Use an already provisioned venv')
    parser.add_argument('--opencode-version', choices=('auto', '1', '2'), default='auto',
                        help='MCP config format for a fresh OpenCode config')
    parser.add_argument('--dsh-profile', default='web', help='DeepSeek Harness profile to register the bundle in')
    parser.add_argument('--dsh-source', type=Path, help='Use pnpm dsh in a built DeepSeek Harness checkout')
    args = parser.parse_args()
    if args.list_clients or args.client == 'auto':
        detected = detect_clients()
        if args.list_clients:
            return reply('PASS', clients=[{'id': key, 'name': name, 'detected': key in detected}
                                          for key, (name, _) in CLIENTS.items()])
        if len(detected) != 1:
            return reply('BLOCKED', code='CLIENT_SELECTION_REQUIRED', candidates=detected or list(CLIENTS),
                         message='Select the active harness with --client. No files were written.')
        args.client = detected[0]
    if sys.version_info < (3, 12):
        interpreter = native_python(args.python)
        if not interpreter:
            return reply('BLOCKED', code='PYTHON_VERSION', message='Install Python 3.12+ or specify its path with --python.')
        return subprocess.call([interpreter, str(Path(__file__).resolve()), *sys.argv[1:]])

    import tomllib
    from agent.installation import configure, handshake, portable_servers, profile_servers
    from agent.skills import install as install_skills, plan as plan_skills
    from agent.state import write

    client = args.client
    venv = args.venv.expanduser().resolve()
    python = venv/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    common = {'client': client, 'profile': args.profile, 'venv': str(venv)}
    try:
        dependencies = tomllib.loads((ROOT/'PaperWorkflow/pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']
        if client in ('none', 'deepseek') and args.config:
            raise ValueError('--config applies to file-based clients. DeepSeek uses --dsh-profile.')
        config = (args.config or default_config(client)) if client not in ('none', 'deepseek') else None
        opencode_default = args.opencode_version
        if client == 'opencode' and opencode_default == 'auto':
            opencode_default = opencode_version()
        dsh = deepseek_plan(venv, args.dsh_profile, args.dsh_source) if client == 'deepseek' else None
        servers = profile_servers(args.profile, python)
        options = {'opencode_default': opencode_default}
        settings = configure(config, client, servers, args.force, True, **options) if config else None
        if args.dry_run:
            return reply('DRY_RUN', **common, dependencies=dependencies, requirements=str(ROOT/'Total-pipe/requirements.txt'),
                         servers=servers, configuration=settings or dsh,
                         skills=plan_skills(client, args.skills_root) if client != 'none' else None)
        if dsh and not dsh['cli_available']:
            return reply('BLOCKED', **common, code='DSH_CLI_MISSING', configuration_written=False,
                         message='Install the dsh CLI or provide a built --dsh-source with pnpm on PATH.')
        if not python.is_file():
            if args.skip_deps:
                return reply('BLOCKED', **common, code='VENV_MISSING', configuration_written=False,
                             message='Remove --skip-deps or select an existing virtual environment.')
            interpreter = native_python(args.python) if args.python else sys.executable
            if not interpreter:
                return reply('BLOCKED', **common, code='PYTHON_VERSION', configuration_written=False,
                             message='--python must point to a Python 3.12+ interpreter.')
            subprocess.run([interpreter, '-m', 'venv', str(venv)], check=True, stdout=sys.stderr)
        if not args.skip_deps:
            subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT/'Total-pipe/requirements.txt'),
                            *dependencies], check=True, stdout=sys.stderr)
        diagnostics = subprocess.run([str(python), '-m', 'agent', 'doctor', '--deep', '--json'], cwd=ROOT/'Total-pipe',
                                     capture_output=True, text=True, encoding='utf-8', errors='replace')
        doctor = json.loads(diagnostics.stdout)
        if not doctor['can_build_editable'] or not doctor['can_rpa'] or not doctor['can_evidence_markdown']:
            values = {**common, 'doctor': doctor, 'configuration_written': False}
            write(args.report.expanduser(), {'status': 'BLOCKED', **values})
            return reply('BLOCKED', **values)
        handshakes = {name: handshake(server) for name, server in servers.items()}
        if args.profile == 'agent' and set(handshakes['total_pipe']['tools']) != {
                'totalpipe_doctor', 'totalpipe_start', 'totalpipe_advance', 'totalpipe_status'}:
            raise ValueError('Agent profile must expose exactly the four entry tools')
        registration = None
        if config:
            registration = configure(config, client, servers, args.force, **options)
        elif dsh:
            registration = register_deepseek(dsh, servers)
        skills = install_skills(client, args.skills_root, force=args.force) if client != 'none' else None
        status = skills['status'] if skills else 'PASS'
        values = {**common, 'doctor': doctor, 'skills': skills, 'handshakes': handshakes,
                  'tool_count': sum(len(h['tools']) for h in handshakes.values()),
                  'configuration': registration, 'stdio': portable_servers(servers)}
        write(args.report.expanduser(), {'status': status, **values})
        return reply(status, **values)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        return reply('FAIL', client=client, message=str(error))


if __name__ == '__main__':
    raise SystemExit(main())
