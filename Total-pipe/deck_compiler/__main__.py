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



def common_load(path):
    import json as _json
    from pathlib import Path as _Path
    return _json.loads(_Path(path).read_text(encoding='utf-8'))

def main():
    parser = argparse.ArgumentParser(description='Total-pipe Deck Compiler v3')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('capabilities', help='Print supported region-tree and backend contracts')
    p = commands.add_parser('listify', help='Merge a page of prose blocks into one native list')
    p.add_argument('--ir', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path, help='Output Deck IR (write beside its source)')
    p.add_argument('--pages', nargs='+', help='Slide ids to convert; default every page that fits')
    p.add_argument('--bullet', default='arrow', help='Native marker style (arrow, square, diamond, ...)')
    p.add_argument('--gap', type=float, default=0.55, help='Item gap as a fraction of the line height')
    p = commands.add_parser('skeleton', help='Draw every page as a wireframe and report capacity')
    p.add_argument('--ir', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--layout', type=Path, help='Compiled layout.json to measure geometric drift against')
    p = commands.add_parser('units', help='Render each graphic alone and report copy-block fit')
    p.add_argument('--ir', required=True, type=Path)
    p.add_argument('--layout', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p = commands.add_parser('assemble', help='Split a Deck IR into pages.json and assemble it back')
    p.add_argument('--mode', choices=('export', 'build', 'selftest'), required=True)
    p.add_argument('--ir', required=True, type=Path, help='Source Deck IR (base IR for build)')
    p.add_argument('--out', required=True, type=Path, help='pages.json, assembled IR, or the report')
    p.add_argument('--spec', type=Path, help='pages.json for build')
    p.add_argument('--verify', action='store_true', help='Compile both IRs and compare every bbox')
    p = commands.add_parser('explain', help='Explain a compiler or QA code: what raised it, why, what to change')
    p.add_argument('codes', nargs='*', help='Codes to explain')
    p.add_argument('--list', action='store_true', help='List every code this package can raise')
    p.add_argument('--unauthored', action='store_true', help='Only codes without authored guidance')
    p.add_argument('--search', help='Rank codes against free text')
    p.add_argument('--json', action='store_true', help='Machine-readable output')
    for name in ('explain-viz-prompt', 'apply-explain-viz'):
        p = commands.add_parser(name, help='Optional reserved-slot native teaching diagrams')
        p.add_argument('--ir', required=True, type=Path)
        p.add_argument('--slots', type=Path, help='Optional explicit slot allowlist; otherwise discover opportunities')
        p.add_argument('--out', required=True, type=Path, help='Output JSON file')
        if name == 'apply-explain-viz':
            p.add_argument('--proposal', type=Path, help='Optional agent proposal; otherwise use conservative source rules')
            p.add_argument('--mode', choices=('off', 'auto', 'prefer'), default='auto')
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
                       help='Optional ExplainViz configuration/proposal; omitted uses automatic defaults')
        p.add_argument('--explain-viz-mode', choices=('auto', 'off', 'prefer'),
                       help='Override request mode; default auto, off explicitly disables enhancement')
        if name == 'build':
            p.add_argument('--officecli', default='officecli', help='OfficeCLI executable')
            p.add_argument('--skip-native', action='store_true', help='Development only; prevents final promotion')
            p.add_argument('--require-visuals', action='store_const', const=True, default=None,
                           help='Strictly require a visual or standalone equation on each page')
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
        if args.command == 'explain':
            from . import diagnostics as diag
            found = diag.discover()
            if args.search:
                picks = diag.search(args.search)
                for code in picks:
                    sites = found[code]
                    first = (diag.CATALOG.get(code) or {}).get('summary') or next(
                        (site['message'] for site in sites if site['message']), '')
                    print(f"{diag.severity_of(sites) or 'unknown':8} {code:34} {first}")
                if not picks:
                    print(f'no code matches {args.search!r}; try explain --list')
                    return 1
                return 0
            if args.list or args.unauthored:
                rows = [row for row in diag.inventory()
                        if not args.unauthored or not row['authored']]
                if args.json:
                    print(json.dumps(rows, ensure_ascii=False))
                    return 0
                for row in rows:
                    mark = 'authored' if row['authored'] else '-'
                    print(f"{row['severity'] or 'unknown':8} {row['code']:34} "
                          f"{row['sites']:3} {mark}")
                owned = sum(row['authored'] for row in rows)
                print(f'\n{len(rows)} codes, {owned} with authored guidance')
                return 0
            if not args.codes:
                raise ValueError('explain needs a code, --list, --search, or --unauthored')
            rows, missing = [], []
            for code in args.codes:
                try:
                    rows.append(diag.explain(code))
                except KeyError:
                    missing.append(code)
            if missing:
                import difflib
                for code in missing:
                    close = difflib.get_close_matches(code, list(found), 3)
                    hint = f"; closest are {', '.join(close)}" if close else ''
                    print(f'unknown code {code}{hint}')
                return 1
            if args.json:
                print(json.dumps(rows, ensure_ascii=False))
            else:
                print('\n\n'.join(diag.render(row) for row in rows))
            return 0
        if args.command == 'skeleton':
            from .workshop import skeleton
            return skeleton.build(args.ir, args.out, args.layout)
        if args.command == 'units':
            from .workshop import units
            return units.build(args.ir, args.layout, args.out)
        if args.command == 'assemble':
            from .workshop import assembly
            if args.mode == 'export':
                from .pipeline import write_json
                spec = assembly.export(common_load(args.ir))
                spec['deck'] = {'base_ir': str(args.ir), 'slide_count': len(spec['pages'])}
                write_json(args.out, spec)
                print(json.dumps({'status': 'PASS', 'pages': len(spec['pages']),
                                  'output': str(args.out)}, ensure_ascii=False))
                return 0
            if args.mode == 'selftest':
                return assembly.selftest(args.ir)
            if args.spec is None:
                raise ValueError('assemble --mode build needs --spec pages.json')
            from .pipeline import write_json
            base = common_load(args.ir)
            assembled, problems = assembly.assemble(base, common_load(args.spec))
            issues = assembly.gates(assembled)
            fails = [item for item in issues if item['severity'] == 'FAIL']
            write_json(args.out, assembled)
            print(json.dumps({'status': 'PASS' if not problems and not fails else 'FAIL',
                              'ownership_problems': problems[:8], 'gate_fails': len(fails),
                              'output': str(args.out)}, ensure_ascii=False))
            if args.verify and not problems and not fails:
                before, _ = assembly.geometry(base, args.ir.parent)
                after, _ = assembly.geometry(assembled, args.ir.parent)
                if not before or not after:
                    print(json.dumps({'verify': 'compile failed'}, ensure_ascii=False))
                    return 1
                rows = assembly.diff(before, after)
                worst = max(row['max_delta_px'] for row in rows)
                print(json.dumps({'verify': 'PASS' if worst == 0 else 'FAIL',
                                  'max_delta_px': worst, 'pages': len(rows)}, ensure_ascii=False))
                return 0 if worst == 0 else 1
            return 0 if not problems and not fails else 1
        if args.command == 'listify':
            from .lists import apply as apply_lists, candidates
            from .layout import compile_deck
            from .pipeline import write_json
            source, out_path = args.ir.resolve(), args.out.resolve()
            if out_path.parent != source.parent:
                raise ValueError('Write the listified Deck IR beside its source: relative asset paths '
                                 'must keep their meaning')
            ir = json.loads(source.read_text(encoding='utf-8'))
            attempt = set(args.pages or candidates(ir))
            dropped = []
            # A merged page can overflow, or shrink its type to fit. Both mean the page was better
            # off as blocks, so it goes back one round at a time until the deck compiles clean.
            for _ in range(6):
                trial = apply_lists(ir, attempt, bullet=args.bullet, gap=args.gap)
                layout, issues = compile_deck(trial, source.parent)
                numbers = {number: slide['id'] for number, slide in enumerate(trial['slides'], 1)}
                broken = {numbers[item['slide']] for item in issues
                          if (item['severity'] == 'FAIL' or 'OVERFLOW' in str(item['rule']))
                          and item.get('slide') in numbers}
                drop = broken & attempt
                if not drop:
                    break
                attempt -= drop
                dropped.extend(sorted(drop))
            write_json(out_path, apply_lists(ir, attempt, bullet=args.bullet, gap=args.gap))
            print(json.dumps({'status': 'PASS', 'pages': sorted(attempt),
                              'dropped': sorted(set(dropped)), 'output': str(out_path)},
                             ensure_ascii=False))
            return 0
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
            inputs = {source}
            if args.slots:
                inputs.add(args.slots.resolve())
            if args.command == 'apply-explain-viz' and args.proposal:
                inputs.add(args.proposal.resolve())
            manifest_path = out.with_suffix('.explain-viz.json')
            if out in inputs or (args.command == 'apply-explain-viz' and
                                 (manifest_path in inputs or manifest_path == out)):
                raise ValueError('ExplainViz outputs must not overwrite source IR, slots or proposal')
            ir = json.loads(source.read_text(encoding='utf-8'))
            slots = json.loads(args.slots.read_text(encoding='utf-8')) if args.slots else None
            if args.command == 'explain-viz-prompt':
                value = make_prompt(ir, slots, source.parent)
                write_json(out, value)
                print(json.dumps({'status': 'ready', 'candidate_count': len(value['candidates']),
                                  'output': str(out)}, ensure_ascii=False))
            else:
                if out.parent != source.parent:
                    raise ValueError('Write enhanced Deck IR alongside its source to preserve resource and font paths')
                proposal = json.loads(args.proposal.read_text(encoding='utf-8')) if args.proposal else None
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
                                         explain_viz_request=args.explain_viz_request,
                                         explain_viz_mode=args.explain_viz_mode)
        else:
            qa = build(args.ir.resolve(), out, not args.skip_native, args.officecli, options,
                       require_visual_design=not args.skip_visual_design,
                       explain_viz_request=args.explain_viz_request,
                       explain_viz_mode=args.explain_viz_mode, require_visuals=args.require_visuals)
        print(json.dumps(qa_summary(qa, out)))
        return 1 if qa['counts']['FAIL'] else 0
    except (ValueError, OSError, KeyError) as e:
        parser.exit(2, f'{e}\n')


if __name__ == '__main__':
    raise SystemExit(main())
