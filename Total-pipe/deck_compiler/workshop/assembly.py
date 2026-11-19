"""装配器：把「空场地 + 成品单元」拼回 Deck IR。

前面两个工具是拆开看（骨架、单件），这一步是合回去：
- export 把每页拆成 pages.json：frame（只有框和引用）+ 该页的单元（文案/图/自绘图）。
- build 把 pages.json 装回 IR，先跑编译器自己的三道闸门，再编译一次比几何。
- build --verify 用同 id 的 bbox 逐元素对比原 IR，证明装配无损。

它不改语义、笔记、证据：这些仍取自 base IR，只重写 composition 里的 frame 与单元。
"""
import copy
import json
from pathlib import Path

from . import runtime as common

SCHEMA = 'workshop.pages/1'


def leaves(node, out):
    if node.get('type') in ('columns', 'stack'):
        for child in node.get('children', []):
            leaves(child, out)
    else:
        out.append(node)


def export(ir):
    pages = []
    for slide in ir['slides']:
        comp = slide['composition']
        frame = json.loads(json.dumps(comp['layout_tree']))
        body = frame['regions']['body']
        pages.append({'id': slide['id'], 'archetype': comp.get('archetype'),
                      'frame': body,
                      'blocks': comp.get('blocks', []),
                      'graphics': comp.get('graphics', []),
                      'charts': comp.get('charts', []),
                      'tables': comp.get('tables', []),
                      'figures': comp.get('figure_refs', [])})
    return {'schema': SCHEMA, 'pages': pages}


def collect_refs(frame):
    found = []
    leaves(frame, found)
    return found


def check_ownership(page):
    """内容投影要求每个单元恰好被一个叶子引用；少引或多引都在这里先报出来。"""
    problems = []
    refs = collect_refs(page['frame'])
    blocks = [b['id'] for b in page.get('blocks', [])]
    graphics = [g['id'] for g in page.get('graphics', [])]
    figures = len(page.get('figures', []))
    block_refs = [r['ref'] for r in refs if r.get('type') == 'block']
    graphic_refs = [r['ref'] for r in refs if r.get('type') == 'graphic']
    figure_refs = [r['ref'] for r in refs if r.get('type') == 'figure']

    for ref in block_refs:
        if ref not in blocks:
            problems.append(f'block 叶子引用了不存在的单元 {ref}')
    for ref in graphic_refs:
        if ref not in graphics:
            problems.append(f'graphic 叶子引用了不存在的自绘图 {ref}')
    for ref in figure_refs:
        if not isinstance(ref, int) or not 0 <= ref < figures:
            problems.append(f'figure 叶子的下标 {ref} 超出 figures 范围（0–{figures - 1}）')
    for bid in blocks:
        count = block_refs.count(bid)
        if count != 1:
            problems.append(f'单元 {bid} 被引用 {count} 次（必须恰好 1 次）')
    for gid in graphics:
        count = graphic_refs.count(gid)
        if count != 1:
            problems.append(f'自绘图 {gid} 被引用 {count} 次（必须恰好 1 次）')
    for kind, pool in (('chart', [c['id'] for c in page.get('charts', [])]),
                       ('table', [t['id'] for t in page.get('tables', [])])):
        used = [r['ref'] for r in refs if r.get('type') == kind]
        for ref in used:
            if ref not in pool:
                problems.append(f'{kind} 叶子引用了不存在的 {kind} {ref}')
        for item in pool:
            count = used.count(item)
            if count != 1:
                problems.append(f'{kind} {item} 被引用 {count} 次（必须恰好 1 次）')
    if len(set(figure_refs)) != len(figure_refs):
        problems.append('同一张图被两个叶子引用，图注会重复')
    return problems


def assemble(base_ir, spec):
    by_id = {page['id']: page for page in spec['pages']}
    out = json.loads(json.dumps(base_ir))
    problems, used = [], set()
    for slide in out['slides']:
        page = by_id.get(slide['id'])
        if page is None:
            problems.append(f"{slide['id']}: pages.json 里没有这一页")
            continue
        used.add(slide['id'])
        for problem in check_ownership(page):
            problems.append(f"{slide['id']}: {problem}")
        version = slide['composition']['layout_tree'].get('version', '1.2')
        composition = {
            'archetype': page['archetype'],
            'blocks': page['blocks'],
            'figure_refs': page['figures'],
            'graphics': page['graphics'],
            'layout_tree': {'version': version, 'regions': {'body': page['frame']}}}
        if page.get('charts'):
            composition['charts'] = page['charts']
        if page.get('tables'):
            composition['tables'] = page['tables']
        slide['composition'] = composition
    for extra in set(by_id) - used:
        problems.append(f'pages.json 多出这一页：{extra}')
    return out, problems


def _normalise(item, slide=None):
    if isinstance(item, dict):
        return {'rule': item.get('rule'), 'severity': item.get('severity'),
                'slide': item.get('slide', slide), 'message': item.get('message')}
    if isinstance(item, (tuple, list)):
        values = list(item) + [None, None, None]
        return {'rule': values[0], 'severity': values[1], 'slide': slide, 'message': values[2]}
    return {'rule': type(item).__name__, 'severity': 'INFO', 'slide': slide, 'message': str(item)}


def gates(ir):
    from .. import ir as ir_module
    found = [_normalise(item) for item in ir_module.validate(ir)]
    try:
        from ..content_projection import validate_ir
    except ImportError:
        return found
    assets = ir.get('assets', {})
    for slide in ir['slides']:
        try:
            found += [_normalise(item, slide['id']) for item in validate_ir(slide, assets)]
        except TypeError:
            break
    return found


def geometry(ir, base):
    from ..layout import compile_deck
    layout, issues = compile_deck(ir, Path(base))
    if layout is None:
        return None, issues
    table = {}
    for slide in layout.get('slides', []):
        table[slide['id']] = {e['id']: e['bbox'] for e in slide.get('elements', [])}
    return table, issues


def diff(before, after):
    rows = []
    for page in before:
        left, right = before[page], after.get(page, {})
        shared = set(left) & set(right)
        worst, worst_id = 0., None
        for eid in shared:
            delta = max(abs(left[eid][i] - right[eid][i]) for i in range(4))
            if delta > worst:
                worst, worst_id = delta, eid
        rows.append({'page': page, 'shared': len(shared),
                     'only_before': len(set(left) - set(right)),
                     'only_after': len(set(right) - set(left)),
                     'max_delta_px': round(worst, 2), 'worst_id': worst_id})
    return rows


def leaf_slots(frame, parent=None):
    """[(parent_list, index, node)] —— 能删、能复制、能交换的最小句柄。"""
    found = []
    if frame.get('type') in ('columns', 'stack'):
        children = frame.setdefault('children', [])
        for index, child in enumerate(list(children)):
            found += leaf_slots(child, children)
    elif parent is not None:
        found.append((parent, frame))
    return found


def pages_of(spec):
    return {page['id']: page for page in spec['pages']}


def selftest(ir_path):
    base = common.load_json(ir_path)
    spec = export(base)
    checks = []

    def rebuild(pages):
        assembled, problems = assemble(base, {'schema': SCHEMA, 'pages': pages})
        return assembled, problems, [i for i in gates(assembled) if i['severity'] == 'FAIL']

    # 1) 无损：原样装回去，几何必须一模一样
    assembled, problems, fails = rebuild(spec['pages'])
    base_geo, _ = geometry(base, ir_path.parent)
    new_geo, _ = geometry(assembled, ir_path.parent)
    worst = max(r['max_delta_px'] for r in diff(base_geo, new_geo)) if base_geo and new_geo else 99.
    checks.append(('无损往返', not problems and not fails and worst == 0,
                   f'problems={len(problems)} FAIL={len(fails)} max_delta={worst:.2f}px'))

    # 2) 漏引用：删掉一个叶子，必须被点名
    broken = json.loads(json.dumps(spec))
    page = broken['pages'][0]
    found = leaf_slots(page['frame'])
    parent, node = found[0]
    parent.remove(node)
    _, problems, _ = rebuild(broken['pages'])
    hit = any('0 次' in p or '被引用 0' in p for p in problems)
    checks.append(('漏引用被拦下', hit, f'{len(problems)} problems: {problems[0] if problems else "-"}'))

    # 3) 重复引用：复制一个叶子，必须被点名
    doubled = json.loads(json.dumps(spec))
    page = doubled['pages'][0]
    found = leaf_slots(page['frame'])
    parent, node = found[0]
    parent.append(json.loads(json.dumps(node)))
    _, problems, _ = rebuild(doubled['pages'])
    hit = any('2 次' in p or '被引用 2' in p for p in problems)
    checks.append(('重复引用被拦下', hit, f'{len(problems)} problems: {problems[0] if problems else "-"}'))

    # 4) 合法交换：同一页两个 block 叶子互换位置，闸门不应报错，但这页几何必须变
    swapped = json.loads(json.dumps(spec))
    page = next(p for p in swapped['pages']
                if len([s for s in leaf_slots(p['frame']) if s[1].get('type') == 'block']) >= 2)
    found = [s for s in leaf_slots(page['frame']) if s[1].get('type') == 'block'][:2]
    found[0][1]['ref'], found[1][1]['ref'] = found[1][1]['ref'], found[0][1]['ref']
    assembled, problems, fails = rebuild(swapped['pages'])
    new_geo, _ = geometry(assembled, ir_path.parent)
    moved = [r for r in diff(base_geo, new_geo) if r['page'] == page['id']]
    hurt = moved and moved[0]['max_delta_px'] > 0
    checks.append(('合法交换被接受', not problems and not fails and bool(hurt),
                   f'{page["id"]} max_delta={moved[0]["max_delta_px"] if moved else "-"}px '
                   f'problems={len(problems)} FAIL={len(fails)}'))

    for name, ok, detail in checks:
        print(f'  [{"PASS" if ok else "FAIL"}] {name}: {detail}')
    return 0 if all(ok for _, ok, _ in checks) else 1

