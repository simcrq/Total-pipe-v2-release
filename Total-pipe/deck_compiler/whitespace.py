"""Geometrically accurate 2D whitespace and spatial coverage analysis.

Shared by compiled Deck IR (layout preflight, skeleton preview, quality metrics,
ExplainViz empty-space detection) and PageScene QA/build.

Key properties:
- Uses exact 2D rectangle union area (never double-counts overlapping boxes).
- Excludes full-bleed backgrounds, page furniture, container frames, and thin rules.
- Measures actual visible text ink bounds instead of full reserved textbox heights.
- Reports both overall body-area coverage and largest contiguous empty rectangle +
  quadrant balance so lopsided or half-empty slides are detected accurately.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from .explain_viz.space import empty_rectangles

DEFAULT_IR_BODY = [56.0, 200.0, 1168.0, 464.0]
# PageScene 13.333 x 7.5 in canvas; header ends below take (~2.15 in), footer rule at 7.08 in.
DEFAULT_SCENE_BODY = [0.72, 2.20, 11.893, 4.80]
_CJK_RE = re.compile(r'[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]')


def clip_rect(rect, bounds):
    """Clip [x, y, w, h] to bounds [bx, by, bw, bh]; return None if empty."""
    if not rect or len(rect) < 4:
        return None
    x, y, w, h = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        return None
    if bounds is None:
        return [x, y, w, h]
    bx, by, bw, bh = (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
    x0, y0 = max(x, bx), max(y, by)
    x1, y1 = min(x + w, bx + bw), min(y + h, by + bh)
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


def union_area(rects, bounds=None):
    """Exact 2D union area of axis-aligned [x, y, w, h] rectangles via sweep line."""
    clipped = []
    for rect in rects or ():
        item = clip_rect(rect, bounds)
        if item is not None:
            clipped.append(item)
    if not clipped:
        return 0.0
    xs = sorted({x for r in clipped for x in (r[0], r[0] + r[2])})
    total = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        dx = x1 - x0
        if dx <= 0:
            continue
        mid = (x0 + x1) * 0.5
        intervals = sorted((r[1], r[1] + r[3]) for r in clipped if r[0] <= mid <= r[0] + r[2])
        if not intervals:
            continue
        cur_start, cur_end = intervals[0]
        covered_y = 0.0
        for start, end in intervals[1:]:
            if start <= cur_end:
                if end > cur_end:
                    cur_end = end
            else:
                covered_y += cur_end - cur_start
                cur_start, cur_end = start, end
        covered_y += cur_end - cur_start
        total += dx * covered_y
    return total


def _approx_text_width_px(text, font_size_px, font_file=None):
    """Measure or conservatively estimate single-line width in px."""
    if not text:
        return 0.0
    if font_file:
        try:
            path = Path(font_file)
            if path.is_file():
                from PIL import ImageFont
                return float(ImageFont.truetype(str(path), max(1, int(round(font_size_px)))).getlength(text))
        except (OSError, ValueError, ImportError):
            pass
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return font_size_px * (cjk * 1.0 + other * 0.56)


def _text_occupied_box_ir(element):
    """Return actual visible ink box [x, y, w, h] for a compiled IR text/list element."""
    x, y, w, h = (float(v) for v in element['bbox'][:4])
    contract = element.get('contract') or {}
    inset = contract.get('inset') or {'top': 0.0, 'bottom': 0.0, 'left': 0.0, 'right': 0.0}
    top_ins = float(inset.get('top', 0.0))
    bot_ins = float(inset.get('bottom', 0.0))
    left_ins = float(inset.get('left', 0.0))
    right_ins = float(inset.get('right', 0.0))
    font_size = float(contract.get('font_size', 24.0))
    line_height = float(contract.get('line_height', 1.25))

    if element.get('inline_math') and isinstance(element.get('inline_layout'), dict):
        occupied_h = float(element['inline_layout'].get('height', h))
        vis_w = w
    elif element.get('kind') == 'list':
        items = element.get('items') or []
        bullet = element.get('bullet') or {}
        gutter = float(bullet.get('gutter', 0.0))
        space_after = float(bullet.get('space_after', 0.0))
        total_lines = sum(len(lines) for lines in items) or 1
        occupied_h = total_lines * font_size * line_height + space_after * max(0, len(items) - 1)
        all_lines = [line for lines in items for line in lines]
        if all_lines:
            max_line_w = max(_approx_text_width_px(line, font_size, contract.get('font_file')) for line in all_lines)
            vis_w = min(w, max(0.0, left_ins + right_ins + gutter + max_line_w + 8.0))
        else:
            vis_w = w
    else:
        raw_text = str(element.get('text') or '')
        lines = re.split(r'[\n\v]', raw_text) if raw_text else ['']
        occupied_h = len(lines) * font_size * line_height
        max_line_w = max(_approx_text_width_px(line, font_size, contract.get('font_file')) for line in lines)
        vis_w = min(w, max(0.0, left_ins + right_ins + max_line_w + 8.0))

    vis_h = min(h, max(0.0, occupied_h + top_ins + bot_ins))
    anchor = contract.get('vertical_anchor', 'top')
    if anchor == 'middle':
        vis_y = y + max(0.0, (h - vis_h) * 0.5)
    elif anchor == 'bottom':
        vis_y = y + max(0.0, h - vis_h)
    else:
        vis_y = y
    align = element.get('align')
    if align == 'center':
        vis_x = x + max(0.0, (w - vis_w) * 0.5)
    elif align == 'right':
        vis_x = x + max(0.0, w - vis_w)
    else:
        vis_x = x
    return [vis_x, vis_y, vis_w, vis_h]


def is_decorative_ir_element(element):
    """True for backgrounds, page furniture, container frames, and thin dividers."""
    role = element.get('role', '')
    eid = str(element.get('id', ''))
    if role in ('background', 'footer', 'page_number') or eid.startswith('page:'):
        return True
    if element.get('collision_mode') == 'container' or element.get('frame_members') or element.get('container_frame'):
        return True
    bbox = element.get('bbox') or []
    if len(bbox) < 4 or min(float(bbox[2]), float(bbox[3])) <= 0:
        return True
    if element.get('kind') == 'shape' and (element.get('visual_decoration') or (role == 'decoration' and not element.get('graphic_id'))):
        return True
    if element.get('kind') in ('shape', 'connector') and (float(bbox[2]) <= 3.0 or float(bbox[3]) <= 3.0):
        return True
    return False


def element_visible_box(element, *, include_header=False):
    """Return visible ink [x, y, w, h] for a compiled IR element, or None if non-content."""
    if is_decorative_ir_element(element):
        return None
    if not include_header and element.get('role') in ('title', 'takeaway'):
        return None
    bbox = element.get('bbox')
    if not bbox or len(bbox) < 4:
        return None
    if element.get('kind') in ('text', 'list') and element.get('contract'):
        return _text_occupied_box_ir(element)
    return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]


def visible_element_boxes(elements, bounds=None, *, include_header=False):
    """Return clipped visible ink boxes for real content elements in a compiled slide."""
    boxes = []
    for element in elements or ():
        box = element_visible_box(element, include_header=include_header)
        if box is None:
            continue
        clipped = clip_rect(box, bounds)
        if clipped is not None:
            boxes.append(clipped)
    return boxes


def _estimate_wrapped_text_in(text, box_w_in, box_h_in, font_pt, line_spacing=1.2, gutter_in=0.0):
    """Estimate visible width & height in inches for wrapped prose inside a PageScene box."""
    usable_w = max(0.25, box_w_in - gutter_in)
    font_in = max(8.0, float(font_pt)) / 72.0
    line_h = font_in * max(1.0, float(line_spacing))
    paragraphs = str(text or '').split('\n')
    total_lines = 0
    max_line_w = 0.0
    for para in paragraphs:
        if not para.strip():
            total_lines += 1
            continue
        cjk = len(_CJK_RE.findall(para))
        other = len(para) - cjk
        raw_w = font_in * (cjk * 1.0 + other * 0.54)
        wrapped = max(1, int(math.ceil(raw_w / usable_w)))
        total_lines += wrapped
        max_line_w = max(max_line_w, usable_w if wrapped > 1 else raw_w)
    vis_w = min(box_w_in, max(0.2, max_line_w + gutter_in + 0.08))
    vis_h = min(box_h_in, max(line_h, total_lines * line_h + 0.04))
    return vis_w, vis_h


def _resolve_scene_text(obj, bindings):
    if obj.get('copy_ref'):
        return str((bindings or {}).get(obj['copy_ref'], ''))
    return str(obj.get('text') or '')


def estimate_scene_object_box(obj, bindings=None):
    """Estimate actual visible ink [x, y, w, h] in inches for a flattened PageScene object."""
    box = obj.get('box')
    if not box or len(box) != 4:
        return None
    x, y, w, h = (float(v) for v in box)
    if w <= 0 or h <= 0:
        return None
    kind = obj.get('type')
    if kind == 'line':
        # Hairlines and dividers organize space; they are not occupied content ink.
        if min(w, h) < 0.08:
            return None
        return [x, y, w, h]
    if kind == 'shape':
        text = _resolve_scene_text(obj, bindings).strip()
        fill = str(obj.get('fill', 'none')).strip().upper()
        # Unfilled container rectangles with no text do not occupy visual content area.
        if not text and fill in ('', 'NONE', '#FFFFFF', 'FFFFFF'):
            return None
        return [x, y, w, h]
    if kind == 'text':
        text = _resolve_scene_text(obj, bindings)
        if not text.strip():
            return None
        role = obj.get('role', 'body')
        size = float(obj.get('size', 18 if role == 'body' else 12))
        spacing = float(obj.get('line_spacing', 1.2))
        vis_w, vis_h = _estimate_wrapped_text_in(text, w, h, size, spacing)
        align = obj.get('align', 'left')
        anchor = obj.get('valign', obj.get('anchor', 'top'))
        vis_x = x + (w - vis_w) * 0.5 if align == 'center' else (x + w - vis_w if align == 'right' else x)
        vis_y = y + (h - vis_h) * 0.5 if anchor == 'middle' else (y + h - vis_h if anchor == 'bottom' else y)
        return [vis_x, vis_y, vis_w, vis_h]
    if kind == 'list':
        items = obj.get('items') or []
        if not items:
            return None
        base_size = float(obj.get('size', 18))
        base_spacing = float(obj.get('line_spacing', 1.15))
        base_after = float(obj.get('space_after', 7)) / 72.0
        total_h = 0.0
        max_w = 0.0
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            text = _resolve_scene_text(item, bindings)
            level = max(0, min(3, int(item.get('level', 0))))
            gutter = 0.22 + 0.28 * level
            size = float(item.get('size', base_size))
            spacing = float(item.get('line_spacing', base_spacing))
            iw, ih = _estimate_wrapped_text_in(text, w, h, size, spacing, gutter_in=gutter)
            total_h += ih
            if idx + 1 < len(items):
                total_h += float(item.get('space_after', base_after * 72.0)) / 72.0
            max_w = max(max_w, iw)
        return [x, y, min(w, max(0.2, max_w)), min(h, max(0.2, total_h))]
    if kind in ('image', 'table', 'chart', 'formula', 'path'):
        return [x, y, w, h]
    return None


def analyze_region_whitespace(occupied_rects, bounds, *, min_empty_size, margin=0.0):
    """Compute exact 2D coverage, largest empty rectangle, and quadrant balance inside bounds."""
    bx, by, bw, bh = (float(v) for v in bounds)
    body_area = max(1e-9, bw * bh)
    clipped = [r for r in (clip_rect(rect, bounds) for rect in (occupied_rects or ())) if r is not None]
    occ_area = union_area(clipped, bounds)
    coverage = min(1.0, max(0.0, occ_area / body_area))
    whitespace = max(0.0, 1.0 - coverage)

    free = empty_rectangles([bx, by, bw, bh], clipped, minimum=min_empty_size, margin=margin)
    largest = free[0] if free else None
    largest_ratio = (largest[2] * largest[3] / body_area) if largest else 0.0

    if clipped:
        min_x = min(r[0] for r in clipped)
        min_y = min(r[1] for r in clipped)
        max_x = max(r[0] + r[2] for r in clipped)
        max_y = max(r[1] + r[3] for r in clipped)
        content_bounds = [round(min_x, 2), round(min_y, 2), round(max_x - min_x, 2), round(max_y - min_y, 2)]
        empty_lower = max(0.0, (by + bh) - max_y)
        empty_right = max(0.0, (bx + bw) - max_x)
    else:
        content_bounds = None
        empty_lower = bh
        empty_right = bw

    hw, hh = bw * 0.5, bh * 0.5
    quadrants = [
        [bx, by, hw, hh],
        [bx + hw, by, hw, hh],
        [bx, by + hh, hw, hh],
        [bx + hw, by + hh, hw, hh],
    ]
    q_area = max(1e-9, hw * hh)
    quadrant_coverage = [round(min(1.0, union_area(clipped, q) / q_area), 3) for q in quadrants]
    empty_quadrants = sum(1 for val in quadrant_coverage if val < 0.05)

    return {
        'body_bounds': [round(bx, 2), round(by, 2), round(bw, 2), round(bh, 2)],
        'body_area': round(body_area, 2),
        'occupied_area': round(occ_area, 2),
        'coverage_ratio': round(coverage, 4),
        'whitespace_ratio': round(whitespace, 4),
        'largest_empty_rect': [round(v, 2) for v in largest] if largest else None,
        'largest_empty_ratio': round(largest_ratio, 4),
        'content_bounds': content_bounds,
        'empty_lower': round(empty_lower, 2),
        'empty_lower_ratio': round(empty_lower / max(1e-9, bh), 4),
        'empty_right': round(empty_right, 2),
        'empty_right_ratio': round(empty_right / max(1e-9, bw), 4),
        'quadrant_coverage': quadrant_coverage,
        'empty_quadrants': empty_quadrants,
    }


def analyze_rendered_png_whitespace(png_path, body_frac=(0.054, 0.293, 0.892, 0.640), bg_tolerance=12):
    """Measure actual non-background ink coverage on a rendered slide PNG."""
    from PIL import Image
    with Image.open(png_path) as image:
        rgb = image.convert('RGB')
        w, h = rgb.size
        # Sample corner pixels for background colour (typically white #FFFFFF).
        corners = [rgb.getpixel((2, 2)), rgb.getpixel((w - 3, 2)),
                   rgb.getpixel((2, h - 3)), rgb.getpixel((w - 3, h - 3))]
        bg = tuple(sorted(c[ch] for c in corners)[1] for ch in range(3))
        bx0 = max(0, int(round(w * body_frac[0])))
        by0 = max(0, int(round(h * body_frac[1])))
        bx1 = min(w, int(round(w * (body_frac[0] + body_frac[2]))))
        by1 = min(h, int(round(h * (body_frac[1] + body_frac[3]))))
        crop = rgb.crop((bx0, by0, bx1, by1))
        cw, ch = crop.size
        if cw <= 0 or ch <= 0:
            return {'pixel_ink_ratio': 0.0, 'pixel_whitespace_ratio': 1.0, 'quadrant_pixel_ink': [0.0] * 4}
        # Downsample cleanly for fast, noise-resistant ink density measurement.
        target_w = min(cw, 320)
        target_h = max(1, int(round(ch * target_w / cw)))
        small = crop.resize((target_w, target_h))
        pixels = list(small.get_flattened_data() if hasattr(small, 'get_flattened_data') else small.getdata())
        mid_x, mid_y = target_w // 2, target_h // 2
        q_ink = [0, 0, 0, 0]
        q_tot = [0, 0, 0, 0]
        ink_count = 0
        for idx, (r, g, b) in enumerate(pixels):
            py, px = divmod(idx, target_w)
            q = (0 if py < mid_y else 2) + (0 if px < mid_x else 1)
            q_tot[q] += 1
            if (abs(r - bg[0]) > bg_tolerance or abs(g - bg[1]) > bg_tolerance
                    or abs(b - bg[2]) > bg_tolerance):
                ink_count += 1
                q_ink[q] += 1
        total = max(1, len(pixels))
        ink_ratio = ink_count / total
        return {
            'pixel_ink_ratio': round(ink_ratio, 4),
            'pixel_whitespace_ratio': round(1.0 - ink_ratio, 4),
            'quadrant_pixel_ink': [round(q_ink[i] / max(1, q_tot[i]), 4) for i in range(4)],
        }
