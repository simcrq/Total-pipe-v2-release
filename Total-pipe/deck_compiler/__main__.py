import argparse
import json
from pathlib import Path
from .pipeline import (build, compile_input, ingest_native, locked, promote,
                       record_powerpoint_review)


def qa_summary(qa, out):
    return {'status': qa['status'], 'counts': qa['counts'],
            'unacked_count': qa.get('unacked_count', qa['counts']['REVIEW']),
            'acked_count': qa.get('acked_count', 0),
            'report': str(out/'qa_report.json'),
            'layout_feedback': str(out/'layout_feedback.json'),
            **({'next_action': qa['next_action']} if qa.get('next_action') else {}),
            **({'explain_viz': qa['explain_viz']} if 'explain_viz' in qa else {}),
            'design_notices': [
                {'rule': item['rule'], 'slide': item['slide'], 'message': item['message']}
                for item in qa['items']
                if item['source']['detector'] == 'design-preflight'
            ]}


def main():
    parser = argparse.ArgumentParser(description='Total-pipe Deck Compiler v3')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('capabilities', help='Print supported region-tree and backend contracts')
    for name in ('explain-viz-prompt', 'apply-explain-viz'):
        p = commands.add_parser(name, help='Optional reserved-slot native teaching diagrams')
        p.add_argument('--ir', required=True, type=Path)
        p.add_argument('--slots', required=True, type=Path, help='Explicit reserved-slot sidecar JSON')
        p.add_argument('--out', required=True, type=Path, help='Output JSON file')
        if name == 'apply-explain-viz':
            p.add_argument('--proposal', required=True, type=Path)
            p.add_argument('--mode', choices=('off', 'auto', 'prefer'), default='off')
            p.add_argument('--max-visuals-per-deck', type=int, default=4)
    for name in ('visual-prompt', 'apply-visual-plan'):
        p = commands.add_parser(name)
        p.add_argument('--ir', required=True, type=Path)
        p.add_argument('--out', required=True, type=Path, help='Output JSON file')
        if name == 'visual-prompt':
            p.add_argument('--requirements', default='', help='Research presentation requirements')
            p.add_argument('--slides', nargs='+', help='Existing slide ids; full deck remains in the prompt')
        else:
            p.add_argument('--proposal', required=True, type=Path)
    for name in ('compile', 'build'):
        p = commands.add_parser(name)
        p.add_argument('--ir', required=True, type=Path)
        p.add_argument('--out', required=True, type=Path)
        p.add_argument('--layout-provider', default='packer',
                       help='packer (bundled deterministic), compiler (templates only) or module:factory')
        p.add_argument('--skip-visual-design', action='store_true',
                       help='Explicit legacy mode: compile without the agent visual design pass')
        p.add_argument('--explain-viz-request', type=Path,
                       help='Optional self-contained ExplainViz request JSON; omitted means disabled')
        if name == 'build':
            p.add_argument('--officecli', default='officecli', help='OfficeCLI executable')
            p.add_argument('--skip-native', action='store_true', help='Development only; prevents final promotion')
    p = commands.add_parser('review-officecli')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--officecli', default='officecli')
    p.add_argument('--render', choices=('native','html'), default='native')
    p = commands.add_parser('promote')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--ack', type=Path)
    p = commands.add_parser('qa', help='Show pending candidate QA findings')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--include-acked', action='store_true')
    p = commands.add_parser('ack-review', help='Record candidate REVIEW notes; does not satisfy final promotion')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--reviewer', required=True)
    p.add_argument('--note', required=True)
    p.add_argument('--ids', nargs='+', required=True, help='Explicit current REVIEW issue ids')
    p = commands.add_parser('validate-native')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--pdf', required=True, type=Path)
    p.add_argument('--reviewer', help='Must match the direct PowerPoint UI review record')
    p = commands.add_parser('record-powerpoint-review')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--reviewer', required=True,
                   help='Reviewer who inspected staging.pptx directly in PowerPoint')
    p.add_argument('--slides', nargs='*', default=['all'],
                   help='Every reviewed slide id, or all')
    args = parser.parse_args()
    try:
        if args.command == 'capabilities':
            from .layout_tree import capabilities
            from .explain_viz.specs import capabilities as explain_capabilities
            print(json.dumps({'deck_ir_version': '2.0', 'layout_tree': capabilities(),
                'explain_viz': explain_capabilities(),
                'backend': {'name': 'officecli', 'minimum_version': '1.0.152',
                            'runtime_probe_required': True}}))
            return 0
        out = args.out.resolve()
        if args.command in ('explain-viz-prompt', 'apply-explain-viz'):
            from .explain_viz import DeckIRAdapter, enhance, make_prompt
            from .pipeline import write_json
            source = args.ir.resolve()
            inputs = {source, args.slots.resolve()}
            if args.command == 'apply-explain-viz':
                inputs.add(args.proposal.resolve())
            manifest_path = out.with_suffix('.explain-viz.json')
            if out in inputs or (args.command == 'apply-explain-viz' and
                                 (manifest_path in inputs or manifest_path == out)):
                raise ValueError('ExplainViz outputs must not overwrite source IR, slots or proposal')
            ir = json.loads(source.read_text(encoding='utf-8'))
            slots = json.loads(args.slots.read_text(encoding='utf-8'))
            if args.command == 'explain-viz-prompt':
                value = make_prompt(ir, slots, source.parent)
                write_json(out, value)
                print(json.dumps({'status': 'ready', 'candidate_count': len(value['candidates']),
                                  'output': str(out)}, ensure_ascii=False))
            else:
                if out.parent != source.parent:
                    raise ValueError('Write enhanced Deck IR alongside its source to preserve resource and font paths')
                proposal = json.loads(args.proposal.read_text(encoding='utf-8'))
                result = enhance(ir, {'slots': slots, 'proposal': proposal},
                                 {'mode': args.mode, 'max_visuals_per_deck': args.max_visuals_per_deck},
                                 DeckIRAdapter(source.parent))
                # A fallback is a successful preservation of the input, never an enhancement.
                write_json(manifest_path, result.audit())
                write_json(out, result.deck_ir)
                print(json.dumps({'status': result.status, 'output': str(out),
                    'manifest': str(manifest_path), 'applied_visuals': len(result.manifest),
                    'warnings': result.warnings}, ensure_ascii=False))
            return 0
        if args.command in ('visual-prompt', 'apply-visual-plan'):
            from .visual_planner import apply_proposal, make_prompt
            from .pipeline import write_json
            ir = json.loads(args.ir.read_text(encoding='utf-8'))
            if args.command == 'visual-prompt':
                value = make_prompt(ir, args.ir.resolve().parent, args.requirements, args.slides)
            else:
                proposal = json.loads(args.proposal.read_text(encoding='utf-8'))
                value = apply_proposal(ir, proposal)
                # A presentation-only merge never changes assets or theme to rebase paths.
                source_base = args.ir.resolve().parent
                paths = [asset['path'] for asset in value['assets'].values()]
                if value['theme'].get('background_image'):
                    paths.append(value['theme']['background_image'])
                if out.parent != source_base and any(not Path(path).is_absolute() for path in paths):
                    raise ValueError('Write the merged Deck IR alongside its source: relative asset paths must retain their meaning')
            write_json(out, value)
            print(json.dumps({'status': 'PASS', 'output': str(out)}))
            return 0
        if args.command == 'review-officecli':
            from .officecli_review import review
            result = review(out, args.officecli, args.render)
            print(json.dumps({'status':result['status'], 'issue_count':result['issue_count'],
                'issue_counts': result['issue_counts'], 'pages':len(result['pages']), 'report':str(out/'officecli_review.json')}))
            return 1 if result['status'] == 'REJECT' else 0
        if args.command in ('qa', 'ack-review'):
            from .qa_review import show_qa, acknowledge_reviews
            if args.command == 'qa':
                with locked(out):
                    qa = show_qa(out, args.include_acked)
                print(json.dumps(qa, ensure_ascii=False))
            else:
                qa = acknowledge_reviews(out, args.reviewer, args.note, args.ids)
                print(json.dumps(qa_summary(qa, out), ensure_ascii=False))
            return 1 if qa['counts']['FAIL'] else 0
        if args.command == 'promote':
            print(promote(out, json.loads(args.ack.read_text(encoding='utf-8')) if args.ack else None))
            return 0
        if args.command == 'validate-native':
            qa = ingest_native(out, args.pdf.resolve(), args.reviewer)
            print(json.dumps(qa_summary(qa, out)))
            return 1 if qa['counts']['FAIL'] else 0
        if args.command == 'record-powerpoint-review':
            print(record_powerpoint_review(out, args.reviewer, args.slides))
            return 0
        options = {'name': args.layout_provider,
                   'plugin': None if args.layout_provider in ('packer', 'compiler',
                                                              'deterministic', 'none')
                   else args.layout_provider}
        if args.command == 'compile':
            with locked(out):
                _, _, qa = compile_input(args.ir.resolve(), out, options,
                                         require_visual_design=not args.skip_visual_design,
                                         explain_viz_request=args.explain_viz_request)
        else:
            qa = build(args.ir.resolve(), out, not args.skip_native, args.officecli, options,
                       require_visual_design=not args.skip_visual_design,
                       explain_viz_request=args.explain_viz_request)
        print(json.dumps(qa_summary(qa, out)))
        return 1 if qa['counts']['FAIL'] else 0
    except (ValueError, OSError, KeyError) as e:
        parser.exit(2, f'{e}\n')


if __name__ == '__main__':
    raise SystemExit(main())
