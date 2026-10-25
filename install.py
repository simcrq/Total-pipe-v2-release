#!/usr/bin/env python3
"""Install dependencies and register an explicitly selected client profile."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', choices=('codex', 'claude', 'none'), default='none')
    parser.add_argument('--profile', choices=('agent', 'advanced'), default='agent')
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--venv', type=Path, default=ROOT/'.venv')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--skip-deps', action='store_true', help='Use an already provisioned venv')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        if args.python != sys.executable:
            try:
                checked = subprocess.run([args.python, '-c', 'import sys; print(int(sys.version_info >= (3,12)))'],
                                         check=True, capture_output=True, text=True, timeout=10)
                if checked.stdout.strip() != '1':
                    parser.error('--python must select Python >=3.12')
            except (OSError, subprocess.SubprocessError):
                parser.error('Cannot run --python; provide a Python >=3.12 executable')
            os.execvp(args.python, [args.python, str(Path(__file__).resolve()), *sys.argv[1:]])
        parser.error('Python >=3.12 required; rerun with --python /path/to/python3.12')
    sys.path.insert(0, str(ROOT/'Total-pipe'))
    from agent.installation import profile_servers, configure, handshake
    from agent.state import write
    import tomllib
    dependencies = tomllib.loads((ROOT/'PaperWorkflow/pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']
    venv = args.venv.expanduser().resolve()
    python = venv/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    config = args.config or (Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'config.toml'
                            if args.client == 'codex' else Path.home()/'.claude.json')
    try:
        if args.dry_run:
            servers = profile_servers(args.profile, python)
            result = {'status': 'DRY_RUN', 'venv': str(venv), 'dependencies': dependencies,
                'requirements': str(ROOT/'Total-pipe/requirements.txt'), 'servers': servers,
                'configuration': configure(config, args.client, servers, args.force, True) if args.client != 'none' else None}
            print(json.dumps(result, ensure_ascii=True))
            return 0
        if args.client != 'none':
            configure(config, args.client, profile_servers(args.profile, python), args.force, True)
        if not python.is_file():
            subprocess.run([args.python, '-m', 'venv', str(venv)], check=True)
        if not args.skip_deps:
            subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT/'Total-pipe/requirements.txt'), *dependencies], check=True)
        servers = profile_servers(args.profile, python)
        diagnostics = subprocess.run([str(python), '-m', 'agent', 'doctor', '--deep', '--json'], cwd=ROOT/'Total-pipe',
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        doctor = json.loads(diagnostics.stdout)
        if not doctor['can_build_editable'] or not doctor['can_rpa'] or not doctor['can_evidence_markdown']:
            result = {'status': 'BLOCKED', 'doctor': doctor, 'configuration_written': False}
            write(ROOT/'install-report.json', result)
            print(json.dumps(result, ensure_ascii=True))
            return 1
        handshakes = {name: handshake(server) for name, server in servers.items()}
        if args.profile == 'agent' and set(handshakes['total_pipe']['tools']) != \
                {'totalpipe_doctor', 'totalpipe_start', 'totalpipe_advance', 'totalpipe_status'}:
            raise ValueError('Agent profile must expose exactly the four entry tools')
        result = {'status': 'PASS', 'profile': args.profile, 'doctor': doctor,
            'handshakes': handshakes, 'tool_count': sum(len(h['tools']) for h in handshakes.values()),
            'configuration': configure(config, args.client, servers, args.force) if args.client != 'none' else None}
        write(ROOT/'install-report.json', result)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'FAIL', 'message': str(error)}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
