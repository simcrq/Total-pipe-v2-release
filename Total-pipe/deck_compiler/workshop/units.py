"""单件渲染：把自绘图和文案块单独拿出来看、单独量。

对应「先把纹理、材质、模型分开画好」里的第一、三步：
- 模型：compile_graphic() 本来就是独立函数，喂它区域就能单独出图，不经过整本 build。
- 纹理：每个文案块的契约里已有字号、行高、max_lines 和断行结果，可以直接算「框能放几行 vs 字几行」。

输出 PNG 与规格卡，不改动任何管线产物。
"""
import json
import sys
from pathlib import Path

from . import runtime as common
from PIL import Image, ImageDraw, ImageFont

SCALE = 2
MARGIN = 14
HEADER = 34
PAGE_W, PAGE_H = 1280, 720
BODY_ROLES = ('body', 'label', 'caption', 'definition')
_FACES = {}


def load_face(path, size):
    from ..fonts import load_font_file
    key = (str(path), size)
    if key not in _FACES:
        _FACES[key] = load_font_file(path, size)
    return _FACES[key]


def px_to_pt(px):
    return round(px * .75, 2)


def wrap(text, font, width):
    """用编译器自己的断行器，避免预览与成品断在不同的地方。"""
    from ..layout import break_lines
    return break_lines(text, font, max(1., width))


def draw_arrow(draw, start, end, color, width):
    draw.line([start, end], fill=color, width=max(1, int(round(width))))
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = (dx * dx + dy * dy) ** .5 or 1.
    ux, uy = dx / length, dy / length
    size = max(5., width * 3.)
    left = (end[0] - ux * size - uy * size * .5, end[1] - uy * size + ux * size * .5)
    right = (end[0] - ux * size + uy * size * .5, end[1] - uy * size - ux * size * .5)
    draw.polygon([end, left, right], fill=color)


def render_graphic(graphic, region, theme, fonts, path, caption):
    from ..graphic_layout import compile_graphic

    elements = compile_graphic(graphic, region, theme, fonts)
    width, height = region[2], region[3]
    canvas_w = int((width + MARGIN * 2) * SCALE)
    canvas_h = int((height + MARGIN * 2 + HEADER) * SCALE)
    img = Image.new('RGB', (canvas_w, canvas_h), 'white')
    draw = ImageDraw.Draw(img)
    draw.text((MARGIN * SCALE, 8 * SCALE), caption, fill='#4a5560',
              font=load_face(fonts['font_file'], 7 * SCALE))

    offset = (MARGIN - region[0], MARGIN + HEADER - region[1])

    def place(box):
        x, y, w, h = box
        return [(x + offset[0]) * SCALE, (y + offset[1]) * SCALE,
                (x + w + offset[0]) * SCALE, (y + h + offset[1]) * SCALE]

    def ink(value, default):
        # Path shapes carry the literal string 'none' for an absent stroke; PIL wants None.
        return default if value in (None, '', 'none') else value

    for element in elements:
        if element['kind'] == 'shape':
            draw.rectangle(place(element['bbox']), outline=ink(element.get('line'), '#333333'),
                           width=max(1, int(round((element.get('line_width') or 1.) * SCALE))))
        elif element['kind'] == 'connector':
            start = ((element['start'][0] + offset[0]) * SCALE, (element['start'][1] + offset[1]) * SCALE)
            end = ((element['end'][0] + offset[0]) * SCALE, (element['end'][1] + offset[1]) * SCALE)
            color = ink(element.get('line'), '#2563A6')
            if element.get('tail_end') == 'triangle':
                draw_arrow(draw, start, end, color, (element.get('line_width') or 1.) * SCALE)
            else:
                draw.line([start, end], fill=color, width=max(1, int((element.get('line_width') or 1.) * SCALE)))

    for element in elements:
        if element['kind'] != 'text':
            continue
        bbox = element['bbox']
        # Break lines at 1x and draw at 2x: rounding the face up at 2x made the type relatively
        # wider and wrapped a label the spec card had proved fits on one line.
        face1 = load_face(fonts['font_file'], max(6, int(round(element['font_size']))))
        lines = wrap(element['text'], face1, bbox[2])
        size = element['font_size'] * SCALE
        face = load_face(fonts['font_file'], max(6, int(round(size))))
        line_h = size * 1.25
        block_h = line_h * len(lines)
        top = (bbox[1] + offset[1]) * SCALE + max(0., ((bbox[3] * SCALE) - block_h) / 2)
        for index, line in enumerate(lines):
            walk = face.getlength(line)
            draw.text(((bbox[0] + offset[0]) * SCALE + ((bbox[2] * SCALE) - walk) / 2,
                       top + index * line_h), line, fill=element.get('color') or '#142735', font=face)
    img.save(path)
    return elements


def graphic_spec(graphic, region, elements, fonts):
    texts = [e for e in elements if e['kind'] == 'text']
    nodes = [e for e in elements if e['kind'] == 'shape']
    node_w = [round(e['bbox'][2], 1) for e in nodes]
    node_h = [round(e['bbox'][3], 1) for e in nodes]
    sizes = sorted({round(e['font_size'], 2) for e in texts})
    labels = []
    for element in texts:
        face = load_face(fonts['font_file'], max(6, int(round(element['font_size']))))
        lines = wrap(element['text'], face, element['bbox'][2])
        needed = face.getlength(element['text'])
        tail = lines[-1].strip() if lines else ''
        labels.append({'text': element['text'], 'lines': lines,
                       'max_lines': element.get('max_lines'),
                       'box_px': round(element['bbox'][2], 1),
                       'needed_px': round(needed, 1),
                       'tail': tail,
                       'orphan': len(tail) <= 1,
                       'widow': len(lines) > 1 and len(tail) <= 2})
    return {'graphic_id': graphic['id'], 'type': graphic['type'],
            'nodes': len(graphic.get('nodes', [])), 'edges': len(graphic.get('edges', [])),
            'region': [round(v, 1) for v in region],
            'node_w': node_w, 'node_h': node_h,
            'node_aspect': (round(node_w[0] / node_h[0], 2) if node_w and node_h and node_h[0] else None),
            'box_font_px': sizes, 'box_font_pt': [px_to_pt(s) for s in sizes],
            'labels': labels,
            'multi_line_labels': sum(1 for item in labels if len(item['lines']) > 1),
            'orphan_labels': sum(1 for item in labels if item['orphan']),
            'widow_labels': sum(1 for item in labels if item['widow'])}


def copy_spec(element):
    contract = element.get('contract') or {}
    size, lh = contract.get('font_size'), contract.get('line_height') or 1.25
    if not size:
        return None
    height = element['bbox'][3]
    allocated = int(round(height / (size * lh)))
    used = element['text'].count('\n') + 1
    return {'id': element['id'], 'role': element.get('role'),
            'width': round(element['bbox'][2], 1), 'height': round(height, 1),
            'font_pt': px_to_pt(size), 'allocated_lines': allocated, 'used_lines': used,
            'slack_lines': allocated - used,
            'fill': round(min(1., used * size * lh / max(1., height)), 2)}


def build(ir_path, layout_path, out):
    """Render each graphic on its own and report the type contract of every copy block."""
    ir_path, layout_path, out = Path(ir_path), Path(layout_path), Path(out)
    out.mkdir(parents=True, exist_ok=True)

    ir = common.load_json(ir_path)
    layout = common.load_json(layout_path)
    design, theme, fonts, _ = common.runtime(ir, ir_path.parent)
    matched = list(layout.get('font_hashes') or {}) == [fonts['font_file'], fonts['bold_font_file']]

    graphics, copies = [], []
    for number, (slide, slide_layout) in enumerate(zip(ir['slides'], layout['slides']), 1):
        regions = common.regions_of(slide_layout)
        for graphic in common.graphics_of(slide):
            region = regions.get(graphic['id'])
            if not region:
                continue
            caption = (f"P{number} · {graphic['id']} · {graphic['type']} · "
                       f"{int(region[2])}x{int(region[3])}")
            path = out / f'slide-{number:02d}-{graphic["id"]}.png'
            elements = render_graphic(graphic, region, theme, fonts, path, caption)
            graphics.append({'page': number, **graphic_spec(graphic, region, elements, fonts),
                             'image': str(path)})
        for element in slide_layout.get('elements', []):
            if element['kind'] != 'text' or element.get('role') not in BODY_ROLES:
                continue
            spec = copy_spec(element)
            if spec:
                copies.append({'page': number, **spec, 'text': element['text'].replace('\n', '⏎')})

    slack = [c for c in copies if c['slack_lines'] >= 3]
    report = {'source_ir': str(ir_path), 'font_paths': fonts, 'font_match_layout': matched,
              'graphics': graphics, 'copies': copies, 'copy_blocks': len(copies),
              'blocks_with_slack': len(slack)}
    (out.parent / 'units.json').write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                           encoding='utf-8')

    lines = ['# 单件规格卡', '',
             f'- 源 IR：`{ir_path}`',
             f'- 字体：{Path(fonts["font_file"]).name}（与成品一致：{"是" if matched else "否"}）',
             f'- 文案块：{len(copies)}，其中框内余量 ≥3 行的 {len(slack)} 块',
             '', '## 自绘图（模型）', '',
             '| 页 | 图形 | 类型 | 区域 | 节点框 | 宽高比 | 箱内字号 | 多行标签 | 短尾行 | 孤儿行 |',
             '|---|---|---|---|---|---|---|---|---|---|']
    for item in graphics:
        lines.append('| {page} | {gid} | {type} | {w}x{h} | {nw}x{nh} | {aspect}:1 | {pt} pt | {multi} | {widow} | {orphan} |'.format(
            page=item['page'], gid=item['graphic_id'], type=item['type'],
            w=int(item['region'][2]), h=int(item['region'][3]),
            nw=int(item['node_w'][0]) if item['node_w'] else 0,
            nh=int(item['node_h'][0]) if item['node_h'] else 0,
            aspect=item['node_aspect'] or '-',
            pt='/'.join(str(v) for v in item['box_font_pt']) or '-',
            multi=f"{item['multi_line_labels']}/{item['nodes']}",
            widow=item['widow_labels'], orphan=item['orphan_labels']))
    orphans = [(item, label) for item in graphics for label in item['labels'] if label['widow']]
    if orphans:
        lines += ['', '### 折行缺陷（末行只剩 1–2 字）', '',
                  '| 页 | 图形 | 标签 | 末行 | 现宽 | 单行需宽 | 缺口 |',
                  '|---|---|---|---|---|---|---|']
        for item, label in orphans:
            gap = label['needed_px'] - label['box_px']
            lines.append(f"| {item['page']} | {item['graphic_id']} | {label['text']} | {label['tail']} | "
                         f"{label['box_px']:.0f} px | {label['needed_px']:.0f} px | "
                         f"{gap:+.0f} px |")
    lines += ['', '## 文案（纹理）：框容行数 vs 实际行数', '',
              '余量越大，说明框比字大得越多。', '',
              '| 页 | 块 | 尺寸 | 字号 | 可容行 | 实用行 | 余量 | 填充 |',
              '|---|---|---|---|---|---|---|---|']
    for item in sorted(slack, key=lambda c: -c['slack_lines'])[:18]:
        lines.append(f"| {item['page']} | {item['id']} | {item['width']:.0f}x{item['height']:.0f} | "
                     f"{item['font_pt']} pt | {item['allocated_lines']} | {item['used_lines']} | "
                     f"{item['slack_lines']} | {item['fill'] * 100:.0f}% |")
    if not slack:
        lines.append('| - | 无 ≥3 行余量的块 | | | | | | |')
    (out.parent / 'units_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(f'graphics={len(graphics)} copy_blocks={len(copies)} slack3={len(slack)} font_match={matched}')
    for item in graphics:
        print(f"  P{item['page']} {item['graphic_id']}: region {int(item['region'][2])}x{int(item['region'][3])} "
              f"node {item['node_w'][0] if item['node_w'] else 0:.0f}x{item['node_h'][0] if item['node_h'] else 0:.0f} "
              f"aspect {item['node_aspect']} font {item['box_font_pt']}pt "
              f"widow {item['widow_labels']} orphan {item['orphan_labels']}")
    for item, label in orphans:
        print(f"  ORPHAN P{item['page']} {label['text']}: box {label['box_px']:.0f}px "
              f"needs {label['needed_px']:.0f}px ({label['needed_px'] - label['box_px']:+.0f})")
    for item in sorted(slack, key=lambda c: -c['slack_lines'])[:8]:
        print(f"  P{item['page']} {item['id']}: {item['allocated_lines']} lines fit, "
              f"{item['used_lines']} used ({item['font_pt']}pt, {item['width']:.0f}x{item['height']:.0f})")
    return 0

