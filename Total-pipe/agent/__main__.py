import argparse
import json
from pathlib import Path

from .doctor import doctor
from .runner import start, advance, status
from .state import read, write


def main():
    parser = argparse.ArgumentParser(description='Total-pipe Agent access layer')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('doctor')
    p.add_argument('--deep', action='store_true')
    p.add_argument('--source-kind')
    p.add_argument('--json', action='store_true')
    p = commands.add_parser('start')
    for name in ('source', 'out-dir', 'language', 'presentation-type'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--source-kind', default='auto')
    p.add_argument('--requirements', default='')
    p.add_argument('--queries', type=Path)
    p.add_argument('--slide-count', type=int)
    p.add_argument('--supplementary-paths', nargs='*')
    p.add_argument('--supplementary-content-included', action='store_true')
    p = commands.add_parser('status')
    p.add_argument('--job-id', required=True)
    p = commands.add_parser('advance')
    p.add_argument('--job-id', required=True)
    p.add_argument('--artifact-kind')
    p.add_argument('--artifact-path')
    p.add_argument('--inputs', type=Path)
    p.add_argument('--acknowledge', type=Path)
    p.add_argument('--replan-from')
    commands.add_parser('serve')
    commands.add_parser('setup', help='Print the repository installer location')
    p = commands.add_parser('ir-prompt')
    for name in ('workflow', 'rpa', 'normalized', 'plan', 'out'):
        p.add_argument('--'+name, required=True, type=Path)
    args = vars(parser.parse_args())
    command = args.pop('command')
    try:
        if command == 'serve':
            from .mcp_server import transport
            return transport.main()
        if command == 'setup':
            from . import ROOT
            result = {'installer': str(ROOT/'install.py'), 'next': 'python install.py --client codex'}
        elif command == 'ir-prompt':
            from .adapters import ir_prompt
            result = ir_prompt(read(args['workflow']), read(args['rpa']), read(args['normalized']), read(args['plan']))
            result['workflow_root'] = str(args['workflow'].resolve().parent)
            write(args['out'], result)
            result = {'status': 'PASS', 'output': str(args['out'].resolve())}
        else:
            args.pop('json', None)
            for key in ('queries', 'inputs', 'acknowledge'):
                if args.get(key) is not None:
                    args[key] = read(args[key])
            result = {'doctor': doctor, 'start': start, 'advance': advance, 'status': status}[command](**args)
        print(json.dumps(result, ensure_ascii=True))
        return 1 if result.get('status') in ('FAIL', 'blocked', 'failed') else 0
    except (ValueError, OSError) as error:
        parser.exit(2, str(error)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
