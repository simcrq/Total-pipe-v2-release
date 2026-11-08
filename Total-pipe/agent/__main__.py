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
    p.add_argument('--page-mode', default='deck_ir', choices=('deck_ir', 'page_scene'))
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
    p.add_argument('--supplement', default='off', choices=('off', 'inline', 'pages', 'both'))
    p.add_argument('--explain-viz-mode', default='auto', choices=('auto', 'off', 'prefer'))
    p.add_argument('--page-mode', default='deck_ir', choices=('deck_ir', 'page_scene'))
    p = commands.add_parser('status')
    p.add_argument('--job-id', required=True)
    p.add_argument('--detail', choices=('summary', 'full'), default='summary')
    p = commands.add_parser('advance')
    p.add_argument('--job-id', required=True)
    p.add_argument('--artifact-kind')
    p.add_argument('--artifact-path')
    p.add_argument('--preflight', action='store_true', help='Check Deck IR without accepting it or consuming a revision')
    p.add_argument('--inputs', type=Path)
    p.add_argument('--acknowledge', type=Path)
    p.add_argument('--native', type=Path, help='Artifact-bound PowerPoint render/review/ingest operation JSON')
    p.add_argument('--preview', type=Path, help='Isolated IR preview request JSON: artifact_path and optional slide_ids')
    p.add_argument('--scene-preview', type=Path, help='PageScene native preview request JSON: artifact_path and optional page_ids')
    p.add_argument('--replan-from')
    commands.add_parser('serve')
    commands.add_parser('setup', help='Print the repository installer location')
    p = commands.add_parser('ir-prompt')
    for name in ('workflow', 'rpa', 'normalized', 'plan', 'out'):
        p.add_argument('--'+name, required=True, type=Path)
    p = commands.add_parser('pagespec-check')
    p.add_argument('--spec', required=True, type=Path)
    p = commands.add_parser('pagespec-render')
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p = commands.add_parser('pagespec-preview')
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--page', required=True)
    p.add_argument('--out-dir', required=True, type=Path)
    args = vars(parser.parse_args())
    command = args.pop('command')
    try:
        if command == 'pagespec-check':
            from .page_scene_qa import check_file
            result = check_file(args['spec'])
            print(json.dumps(result, ensure_ascii=True))
            return 0 if result['status'] == 'PASS' else 1
        if command == 'pagespec-render':
            from .page_scene_qa import render_spec, validate_spec
            spec = read(args['spec'])
            errors, _ = validate_spec(spec, args['spec'])
            if errors:
                print(json.dumps({'status': 'FAIL', 'errors': errors}, ensure_ascii=True))
                return 1
            out = render_spec(spec, args['spec'], args['out'])
            print(json.dumps({'status': 'PASS', 'output': str(out)}, ensure_ascii=True))
            return 0
        if command == 'pagespec-preview':
            from .page_scene_qa import preview_page
            result = preview_page(args['spec'], args['page'], args['out_dir'])
            print(json.dumps(result, ensure_ascii=True))
            return 0 if result['status'] in ('PASS', 'BLOCKED') else 1
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
            for key in ('queries', 'inputs', 'acknowledge', 'native', 'preview', 'scene_preview'):
                if args.get(key) is not None:
                    args[key] = read(args[key])
            result = {'doctor': doctor, 'start': start, 'advance': advance, 'status': status}[command](**args)
        print(json.dumps(result, ensure_ascii=True))
        state = result.get('scene_preview_result',
                           result.get('preview_result',
                                      result.get('page_result',
                                                 result.get('preflight_result', {})))).get('status', result.get('status'))
        return 1 if state in ('FAIL', 'blocked', 'failed', 'revision_limit') else 0
    except (ValueError, OSError) as error:
        parser.exit(2, str(error)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
