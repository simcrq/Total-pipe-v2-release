import argparse
import json
from pathlib import Path
from .pipeline import build, compile_input, ingest_native, locked, promote


def main():
    parser = argparse.ArgumentParser(description='Total-pipe Deck Compiler v2')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('compile', 'build'):
        p = commands.add_parser(name)
        p.add_argument('--ir', required=True, type=Path)
        p.add_argument('--out', required=True, type=Path)
        if name == 'build':
            p.add_argument('--node', default='node')
            p.add_argument('--skip-native', action='store_true', help='Development only; prevents final promotion')
    p = commands.add_parser('promote')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--ack', type=Path)
    p = commands.add_parser('validate-native')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--pdf', required=True, type=Path)
    p.add_argument('--reviewer', help='Records who visually inspected every rendered page')
    args = parser.parse_args()
    try:
        out = args.out.resolve()
        if args.command == 'promote':
            print(promote(out, json.loads(args.ack.read_text()) if args.ack else None))
            return 0
        if args.command == 'validate-native':
            qa = ingest_native(out, args.pdf.resolve(), args.reviewer)
            print(json.dumps({'status': qa['status'], 'counts': qa['counts'],
                              'report': str(out/'qa_report.json')}))
            return 1 if qa['counts']['FAIL'] else 0
        if args.command == 'compile':
            with locked(out):
                _, _, qa = compile_input(args.ir.resolve(), out)
        else:
            qa = build(args.ir.resolve(), out, args.node, not args.skip_native)
        print(json.dumps({'status': qa['status'], 'counts': qa['counts'], 'report': str(out/'qa_report.json')}))
        return 1 if qa['counts']['FAIL'] else 0
    except (ValueError, OSError, KeyError) as e:
        parser.exit(2, f'{e}\n')


if __name__ == '__main__':
    raise SystemExit(main())
