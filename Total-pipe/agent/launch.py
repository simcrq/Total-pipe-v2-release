"""Absolute stdio launcher for clients without a cwd configuration field."""
import argparse
import json
import os
from pathlib import Path
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
    os.execvpe(command, [command, *server['args']], environment)


if __name__ == '__main__':
    main()
