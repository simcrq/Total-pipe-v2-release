"""Absolute stdio launcher for clients without a cwd configuration field."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

COMPONENT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=('agent', 'advanced'), required=True)
    parser.add_argument('--service', required=True)
    args = parser.parse_args()
    path = COMPONENT/('.mcp.json' if args.profile == 'agent' else '.mcp.advanced.json')
    server = json.loads(path.read_text(encoding='utf-8'))['mcpServers'][args.service]
    os.chdir((COMPONENT/server['cwd']).resolve())
    environment = {**os.environ, **server.get('env', {}), 'PYTHONIOENCODING': 'utf-8'}
    command = sys.executable if server['command'] == 'python' else server['command']
    # Do not os.exec*: on Windows that overlays the process, so the PID the host
    # spawned exits immediately and its inherited stdio pipes are lost. A stdio
    # host then sees a clean exit with no initialize response and reports a
    # timeout. Running as a child keeps the spawned PID and the pipes alive.
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(subprocess.call([command, *server['args']], env=environment))


if __name__ == '__main__':
    main()
