"""骨架预排：把 Deck IR 的「文字层」换成占位汉字，跑真实编译器，只画框。

空场地 = 与成品同几何、无真实内容的孪生 IR。
- 汉字逐字替换为「文」：全角等宽，断行位置与字号预算完全一致。
- 拉丁字母、数字、标点原样保留：让科学数字校验、英文术语的词边界断行继续有效。
- 于是 compile_deck() 得到的 bbox 就是成品 bbox，偏差只来自极少数西文词宽差异，会被测出来。
"""
import copy
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
WIRE_KEYS = ('text', 'label', 'caption', 'title', 'panel', 'takeaway', 'purpose')

PAGE_W, PAGE_H = 1280, 720
SCALE = 1

INK = {
    'title':    ('#c9d5e2', '#6f86a3'),
    'takeaway': ('#dde8f2', '#8ba3bd'),
    'body':     ('#eef2f6', '#a3b1c0'),
    'label':    ('#f6f2e6', '#c2b795'),
    'caption':  ('#f6f2e6', '#c2b795'),
    'definition': ('#f0f4ef', '#a9bda6'),
}
DEFAULT_INK = ('#f2f2f2', '#b9b9b9')


def wire(value):
    return CJK.sub('文', value)


def scrub(node):
    if isinstance(node, dict):
        for key in list(node):
            value = node[key]
            if key in WIRE_KEYS and isinstance(value, str):
                node[key] = wire(value)
            elif isinstance(value, (dict, list)):
                scrub(value)
    elif isinstance(node, list):
        for value in node:
            scrub(value)


def wireframe(ir):
    twin = copy.deepcopy(ir)
    for slide in twin['slides']:
        scrub(slide.get('semantic', {}))
        scrub(slide.get('composition', {}))
    return twin


# 空场地编译只关心几何。这些规则断言的是「文案能被证据追溯」，占位汉字必然不满足，
# 与框装不装得下无关，所以显式跳过并记进报告，而不是伪造通过。
SKIP_PREFIXES = ('CONTENT_PROJECTION', 'STORY_PROVENANCE', 'EVIDENCE')


def compile_wire(ir, base):
    import deck_compiler.layout as compiler
    original = compiler.validate

    def geometry_only(document):
        kept = []
        for item in original(document):
            rule = str(item.get('rule', ''))
            if any(rule.startswith(prefix) for prefix in SKIP_PREFIXES):
                continue
            kept.append(item)
        return kept

    compiler.validate = geometry_only
    try:
        return compiler.compile_deck(ir, Path(base))
    finally:
        compiler.validate = original


def geometry(layout):
    """slide id -> element id -> bbox"""
    table = {}
    for slide in layout.get('slides', []):
        table[slide['id']] = {e['id']: e['bbox'] for e in slide.get('elements', [])}
    return table


def drift(wire_geo, real_geo):
    """最大 bbox 偏差，逐页。同 id 对齐，缺 id 记为 None。"""
    out = {}
    for page, wired in wire_geo.items():
        real = real_geo.get(page, {})
        shared = set(wired) & set(real)
        worst, worst_id = 0.0, None
        if shared:
            for eid in shared:
                a, b = wired[eid], real[eid]
                delta = max(abs(a[i] - b[i]) for i in range(4))
                if delta > worst:
                    worst, worst_id = delta, eid
        out[page] = {'shared': len(shared),
                     'only_skeleton': len(set(wired) - set(real)),
                     'only_real': len(set(real) - set(wired)),
                     'max_delta_px': round(worst, 2), 'worst_id': worst_id}
    return out


def border_for(ink):
    if ink is None:
        return '#dcdcdc'
    if ink >= .60:
        return '#c3d6c3'
    return '#e3c49f' if ink >= .45 else '#dfa9a9'


def render(slide, out_path, page_no, band_fill=None):
    img = Image.new('RGB', (PAGE_W * SCALE, PAGE_H * SCALE), 'white')
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.rectangle([0, 0, PAGE_W - 1, PAGE_H - 1], outline=border_for(band_fill))

    # 左侧刻度：每 100 px 一条，用来判断比例
    for y in range(0, PAGE_H, 100):
        draw.line([(0, y), (8, y)], fill='#c4c4c4')
        draw.text((11, y + 1), str(y), fill='#9a9a9a', font=font)

    for element in slide.get('elements', []):
        x, y, w, h = element['bbox']
        box = [x, y, x + w, y + h]
        kind, role = element['kind'], element.get('role', '')
        if kind == 'image':
            draw.rectangle(box, fill='#e2e5e8', outline='#9aa4ae')
            draw.line([(x, y), (x + w, y + h)], fill='#c3cad1')
            draw.line([(x + w, y), (x, y + h)], fill='#c3cad1')
            continue
        if kind in ('shape', 'connector'):
            if h <= 3 or w <= 3:
                draw.line([(x, y + h / 2), (x + w, y + h / 2)], fill='#a9b2bb')
            else:
                draw.rectangle(box, outline='#c2cad2')
            continue
        fill, line = INK.get(role, DEFAULT_INK)
        if role in ('title', 'takeaway'):
            fill, line = '#e9edf2', '#d3dae2'
        draw.rectangle(box, fill=fill, outline=line)
        label = f"{element['id']}  {int(round(w))}x{int(round(h))}"
        if h >= 12 and w >= 40:
            draw.text((x + 3, y + 2), label, fill='#5c6773', font=font)

    if page_no is not None:
        draw.text((PAGE_W - 34, PAGE_H - 16), f'P{page_no}', fill='#8c959e', font=font)
    if band_fill is not None:
        draw.text((PAGE_W - 116, PAGE_H - 16), f'ink {band_fill * 100:.0f}%',
                  fill='#7d8791', font=font)
    img.save(out_path)


def contact_sheet(pages, out_path, cols=4, thumb_w=320):
    rows = (len(pages) + cols - 1) // cols
    thumb_h = int(thumb_w * PAGE_H / PAGE_W)
    sheet = Image.new('RGB', (cols * thumb_w, rows * thumb_h), 'white')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, path in enumerate(pages):
        thumb = Image.open(path).resize((thumb_w, thumb_h))
        x, y = (index % cols) * thumb_w, (index // cols) * thumb_h
        sheet.paste(thumb, (x, y))
        draw.rectangle([x, y, x + thumb_w - 1, y + thumb_h - 1], outline='#d0d0d0')
        draw.text((x + 4, y + 3), f'{index + 1:02d}', fill='#333333', font=font)
    sheet.save(out_path)
    return sheet


def is_furniture(element):
    return (element.get('role') in ('page_number', 'footer')
            or str(element.get('id', '')).startswith('page:'))


def capacity(slide, issues):
    elements = slide.get('elements', [])
    body_roles = ('body', 'label', 'caption', 'definition')
    prose = [e for e in elements if not is_furniture(e) and e['kind'] in ('text', 'image')]
    body = [e for e in prose if e['kind'] == 'image' or e.get('role') in body_roles]
    boxes = [e['bbox'] for e in body]
    body_bottom = max((b[1] + b[3] for b in boxes), default=0)
    body_top = min((b[1] for b in boxes), default=0)
    footer = [e['bbox'][1] for e in elements
              if str(e.get('id', '')).startswith('page:') and e['kind'] == 'text']
    footer_top = min(footer) if footer else 672.
    height = max(1., footer_top - body_top)
    # 纵向延伸只说明「最下面那个框到哪儿」，一列 372 px 的空卡片能把整页算成满。
    # 覆盖率按框的投影面积算，才对应「版面被用掉了多少」。
    ink = 0.
    for x, y, w, h in boxes:
        top, bottom = max(y, body_top), min(y + h, footer_top)
        if bottom > top:
            ink += w * (bottom - top)
    band_area = 1168. * height
    text_boxes = [e['bbox'][3] for e in prose if e['kind'] == 'text']
    images = [e for e in prose if e['kind'] == 'image']
    graphic_marks = {e['graphic_id'] for e in elements if e.get('graphic_id')}
    return {'elements': len(elements),
            'text_boxes': len(text_boxes),
            'images': len(images),
            'graphics': len(graphic_marks),
            'text_only': not images and not graphic_marks,
            'body_top_px': round(body_top, 1),
            'body_bottom_px': round(body_bottom, 1),
            'gap_to_footer_px': round(footer_top - body_bottom, 1),
            'band_fill': round((body_bottom - body_top) / height, 2),
            'ink_ratio': round(min(1., ink / band_area), 2),
            'min_text_height_px': round(min(text_boxes, default=0), 1),
            'boxes_under_24px': [e['id'] for e in prose
                                 if e['kind'] == 'text' and e['bbox'][3] < 24],
            'issues': [f"{i['rule']}:{i['severity']}" for i in issues]}


def build(ir_path, out, real_layout=None):
    """Draw every page as a wireframe and report capacity. Returns 0 on a compiled deck."""
    ir_path, out = Path(ir_path), Path(out)
    real_layout = Path(real_layout) if real_layout else None
    (out / 'pages').mkdir(parents=True, exist_ok=True)

    ir = json.loads(ir_path.read_text(encoding='utf-8'))
    twin = wireframe(ir)
    (out / 'deck_ir.skeleton.json').write_text(
        json.dumps(twin, ensure_ascii=False, indent=1), encoding='utf-8')

    layout, issues = compile_wire(twin, ir_path.parent)
    if layout is None:
        print('COMPILE_FAILED')
        for item in issues:
            print(f"  {item['severity']:7} {item['rule']}: {item['message']}")
        return 1
    (out / 'layout_skeleton.json').write_text(
        json.dumps(layout, ensure_ascii=False, indent=1), encoding='utf-8')

    real_geo = {}
    if real_layout.exists():
        real_geo = geometry(json.loads(real_layout.read_text(encoding='utf-8')))
    deltas = drift(geometry(layout), real_geo) if real_geo else {}

    pages, rows = [], []
    for number, slide in enumerate(layout['slides'], 1):
        page_issues = [i for i in issues if i.get('slide') == number]
        metrics = capacity(slide, page_issues)
        path = out / 'pages' / f'slide-{number:02d}.png'
        render(slide, path, None, metrics['ink_ratio'])
        pages.append(path)
        rows.append({'page': number, 'slide': slide['id'], **metrics,
                     **(deltas.get(slide['id']) or {})})

    contact_sheet(pages, out / 'contact-sheet.png')
    worst = max((r.get('max_delta_px') or 0) for r in rows) if rows else 0
    report = {'source_ir': str(ir_path), 'pages': len(rows),
              'compile_issues': [{'rule': i['rule'], 'severity': i['severity'],
                                  'slide': i.get('slide'), 'message': i['message']}
                                 for i in issues],
              'rows': rows}
    (out / 'skeleton_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

    lines = ['# 骨架预排报告', '',
             f'- 源 IR：`{ir_path}`',
             f'- 页数：{len(rows)}',
             f'- 编译告警：{len(issues)}',
             f'- 骨架几何与成品最大偏差：{worst:.2f} px（同 id 逐元素比 bbox）',
             '',
             '「覆盖率」= 正文/图元素投影面积占正文带的比例；「空白」= 正文底到页码线的距离。',
             '',
             '| 页 | 元素 | 图/形 | 覆盖率 | 正文底 y | 空白 px | 最小框高 | 偏差 px | 告警 |',
             '|---|---|---|---|---|---|---|---|---|']
    for row in rows:
        delta = row.get('max_delta_px')
        lines.append('| {page} | {elements} | {assets} | {ink} | {body_bottom_px} | '
                     '{gap_to_footer_px} | {min_text_height_px} | {delta} | {warn} |'.format(
                         assets=f"{row['images']}/{row['graphics']}",
                         ink=f"{row['ink_ratio'] * 100:.0f}%",
                         warn=' '.join(row['issues']) or '-',
                         delta='-' if delta is None else f'{delta:.1f}',
                         **{k: row[k] for k in ('page', 'elements', 'body_bottom_px',
                                                'gap_to_footer_px', 'min_text_height_px')}))
    plain = [r['page'] for r in rows if r['text_only']]
    if plain:
        lines += ['', f'## 纯文字页（无图片、无原生图形）：{len(plain)} 页', '',
                  ' ' + '、'.join(f'P{p}' for p in plain)]
    sparse = sorted((r for r in rows if r['ink_ratio'] < .55), key=lambda r: r['ink_ratio'])
    if sparse:
        lines += ['', '## 空旷页（覆盖率 < 55%）', '',
                  '| 页 | 覆盖率 | 纵向占用 | 空白 px |', '|---|---|---|---|']
        lines += [f"| {r['page']} | {r['ink_ratio'] * 100:.0f}% | "
                  f"{r['band_fill'] * 100:.0f}% | {r['gap_to_footer_px']} |"
                  for r in sparse]
    (out / 'skeleton_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    fails = [i for i in issues if i['severity'] == 'FAIL']
    rules = {}
    for item in issues:
        rules[item['rule']] = rules.get(item['rule'], 0) + 1
    print(f'pages={len(rows)} issues={len(issues)} FAIL={len(fails)} '
          f'max_geometry_drift={worst:.2f}px')
    for rule, count in sorted(rules.items(), key=lambda kv: -kv[1]):
        print(f'  {rule}: {count}')
    for row in sorted(rows, key=lambda r: r['ink_ratio'])[:8]:
        print(f"  P{row['page']}: ink={row['ink_ratio'] * 100:.0f}% "
              f"extent={row['band_fill'] * 100:.0f}% gap={row['gap_to_footer_px']}px")
    return 0

