"""Deterministic layout compiler. No LLM calls, mutation, or content rewriting."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import re
from PIL import Image, ImageFont
from . import audience
from .catalog import ARCHETYPES
from .capacity import DISPLAY_FORMULA_SIZES, FORMULA_GAP, FORMULA_LABEL_MAX, FORMULA_SIZES
from .formula_layout import formula_groups, plan_formula_flow, FormulaCapacityError
from .contracts import TextBoxContract, digest, file_hash, issue
from .ir import enable_bare_subscripts, validate
from .layout_tree import walk as walk_regions
from .graphic_layout import (compile_graphic, graphic_counts, graphic_obstacle_collisions,
                             graphic_texts, intentional_overlap)
from .text_flow import DISTRIBUTED_ARROW_LIST, EXPLICIT_LISTS, list_min_width, select_text_flow
from .visual_design import (TITLE_BOX_LINES, header_decoration, header_layout, preserve_scientific_terms,
                            resolve_design, rule, type_sizes)
from totalpipe_layout.inline_math import has_bare_subscript, has_markup, strip_markup, unmatched_markers

WIDTH, HEIGHT = 1280, 720

# Native list markers. The glyph is a *paragraph* property (a:buChar + a:buClr), so an item stays a
# real list item in PowerPoint: Tab changes its level, the bullet menu reflects it, and copying one
# row carries the marker. The catalogue lives in fonts.BULLET_STYLES and is resolved to a face that
# can actually draw the glyph, so a deck never depends on a symbol font being installed.
BULLET_GUTTER = 42.0            # px reserved for the marker, text starts on the gutter edge
LIST_ITEM_LINES = 4             # a list item may wrap to four lines before the page must split
# Space between list items as a fraction of the line height. It is relative on purpose: an absolute
# gap stops matching when the font shrinks, and filling the panel instead is what made three short
# items drift apart. A deck may override it with presentation.list_gap.
DEFAULT_LIST_GAP = 0.45

# One accent colour per deck, used by list markers, sequence badges and emphasis. It is deliberately
# not the body colour: a marker in the same ink as the sentence reads as a typo, and a step badge in
# the same ink as its label disappears into it. Decks override it with theme.accent.
DEFAULT_ACCENT = "#C2410C"

# A caption strip is measured from the caption, not reserved at a fixed 62 px. A one-line caption in
# a 692 px column needs 36 px; reserving 62 for it costs the picture 26 px on every page and was one
# half of the "figure + caveat does not fit" dead end in the packer.
CAPTION_FONT_SIZE = 22  # captions may sit below the 18 pt body floor

# One typographic scale, enforced instead of implied. Body copy, headings and labels are never set
# below 18 pt; the annotation roles that support them (figure captions, caveats, step badges) are
# never below 15 pt. The compiler used to carry body floors and annotation floors with nothing that
# said which role was which, so a 13.5 pt footer and a 15 pt caveat sat next to 18 pt body text
# without a finding. Evidence ids no longer have a role here: they are notes, not page furniture.
BODY_MIN_PT = 18.0
ANNOTATION_MIN_PT = 15.0
ANNOTATION_ROLES = {"caption", "caveat", "footer", "badge"}


def caption_height(caption, width, font_file, size=CAPTION_FONT_SIZE):
    """Height of a caption strip: the wrapped line count at the size it is set in."""
    from .fonts import load_font_file
    if has_bare_subscript(caption):
        return caption_measure({'caption': caption, 'caption_font_size': size}, width, font_file)[0]
    lines = break_lines(strip_markup(caption), load_font_file(font_file, size), max(1, width))
    return max(34.0, len(lines) * size * 1.25 + 8)


CAPTION_FIGURE_PREFIX = re.compile(
    r'^(?:原文\s*)?[Ff]ig(?:ure)?\.?\s*([0-9]+[a-z]?)\s*[|｜·•:：\-–]\s*')


def caption_with_source(ref):
    """A panel's caption with its provenance set as a weakened prefix.

    A paper panel belongs to a figure, an author and a panel letter; a caption that only says what
    is plotted makes the reader hunt for the source. The label is part of the measured caption, so
    the strip grows by the characters it costs — it is never a separate text box that could drift
    onto the picture.
    """
    label = str((ref or {}).get('source_label') or '').strip()
    caption = str((ref or {}).get('caption') or '')
    if not label or not caption:
        return caption
    # A caption that starts with the same figure it already labels ("Fig. 2c | ...") would print
    # the provenance twice: once as the label, once as the first words of the caption.
    prefix = CAPTION_FIGURE_PREFIX.match(caption)
    if prefix and prefix.group(1).lower() in label.lower():
        caption = caption[prefix.end():]
        if not caption:
            return f'[[{label}]]'
    return f'[[{label}]] · {caption}'


def native_caption_size(design=None):
    return min(CAPTION_FONT_SIZE, type_sizes(design)['caption']) if design else CAPTION_FONT_SIZE


def caption_measure(ref, width, font_file, design=None):
    """``(height, lines)`` of a caption strip, measured the way it will be set.

    A labelled caption is set as runs, so it is measured by the inline engine that draws it: the
    plain wrapper and the run engine break lines slightly differently, and a strip that reserved
    one line too few would silently shrink the caption to its floor.
    """
    from .fonts import load_font_file
    content = caption_with_source(ref) if isinstance(ref, dict) else str(ref or '')
    size = float((ref or {}).get('caption_font_size', CAPTION_FONT_SIZE))
    if design:
        size = min(size, native_caption_size(design))
    if not content:
        return 0., 0
    if has_markup(content) or has_bare_subscript(content):
        from totalpipe_layout.inline_math import InlineWidthError, measure_inline
        try:
            plan = measure_inline(content, max(1., width), load_font_file(font_file, int(size)), int(size))
            return max(34.0, plan['height']+8), len(plan['lines'])
        except InlineWidthError:
            pass
    lines = break_lines(strip_markup(content), load_font_file(font_file, int(size)), max(1., width))
    return max(34.0, len(lines)*size*1.25+8), len(lines)


def body_bottom(slide, family, spacious):
    """Where the body region ends on this page.

    The dual-figure template has always used the strip between the body bottom and the compact caveat
    row at y=622; the packer's requests said 588, so the two disagreed by 30 px and no two-up figure
    could ever satisfy the panel floor. One function now answers for both.
    """
    bottom = 588 if audience.visible_caveats(slide) else 640
    if family == "dual" and audience.visible_caveats(slide):
        bottom = 618
    return bottom


def body_region(slide, family, frame, design=None, font_paths=None, preserve_terms=False):
    """The body rectangle's vertical bounds for a frame variant, in the compiler's own units.

    The lab-template frame is tighter above (a 40 pt title and a one-line takeaway instead of the
    compass frame's 120 px title block) and lower below (the template's footer band starts at
    y=686), so a content page gains about 150 px of body height.
    """
    if design:
        return header_layout(design, slide, font_paths, preserve_terms)['body_top'], body_bottom(slide, family, False)
    if frame == "template":
        top, bottom = 132, (632 if audience.visible_caveats(slide) else 672)
    else:
        spacious = frame == "spacious"
        top, bottom = (236 if spacious else 260), body_bottom(slide, family, spacious)
    if slide.get('presentation', {}).get('takeaway_frame') and font_paths:
        from .container_frames import measure_takeaway, legacy_takeaway_box
        box = measure_takeaway(slide, font_paths, legacy_takeaway_box(slide, frame))['bbox']
        top = max(top, box[1]+box[3]+20)
    return top, bottom

# Which marker a deck gets when it does not say. A deck keeps one style, so this is decided once
# from the dominant list semantics: a procedure reads as arrows, a set of claims as open squares,
# settled points as filled squares, and anything mixed falls back to the square PowerPoint itself
# uses as its second list style.
BULLET_COMPONENT_STYLE = {
    "process-step": "arrowhead", "method": "arrowhead",
    "conclusion": "large_square", "result": "large_square",
    "hypothesis": "open_square", "caveat": "open_square", "comparison": "open_square",
}


def choose_bullet_style(ir):
    """Deck default; individual blocks may override the marker without changing other lists."""
    explicit = (ir.get("presentation") or {}).get("bullet_style")
    if explicit:
        return explicit
    counts = {}
    for slide in ir["slides"]:
        for block in slide["composition"]["blocks"]:
            if select_text_flow(block["text"], block.get("text_flow", "auto"))["mode"] == DISTRIBUTED_ARROW_LIST:
                component = block.get("component", "body")
                counts[component] = counts.get(component, 0) + 1
    if not counts:
        return "large_square"
    top = max(sorted(counts), key=lambda component: counts[component])
    return BULLET_COMPONENT_STYLE.get(top, "large_square")


def fit_list_items(items, width, font_file, size, floor, max_lines):
    """Break every item at one shared font size; ``None`` when the markers cannot fit the box."""
    for candidate in range(int(size), int(floor) - 1, -1):
        face = ImageFont.truetype(font_file, candidate)
        lines = [break_lines(item, face, width) for item in items]
        if all(len(item_lines) <= max_lines for item_lines in lines):
            return lines, candidate
    return None


def native_list_height(block, width, font_file, gap_ratio=DEFAULT_LIST_GAP, padding=(0, 0), preserve_terms=False,
                       default_style='large_square', *, flow=None, wrap_items=True):
    """Measure an explicit or already-selected native list, including indent and item gaps.

    Planners only reserve compulsory lists by default. The emitter may pass its selected auto
    flow; measuring it must not silently turn other prose into a compulsory list. With wrapping
    disabled, preserve-terms still reserves one complete marker row per item before overflow.
    """
    if block.get('component') == 'caption':
        return None
    if flow is None and block.get('text_flow') not in EXPLICIT_LISTS:
        return None
    flow = flow or select_text_flow(block['text'], block.get('text_flow'))
    if flow['mode'] != DISTRIBUTED_ARROW_LIST:
        return None
    if width < list_min_width(block):
        return 10000.0
    pad_x, pad_y = padding
    rows = flow['items']
    face = ImageFont.truetype(font_file, 24)
    from .fonts import list_marker_metrics
    marker = list_marker_metrics(block, default_style, face.getname()[0], font_file, 24, len(rows))
    line_h = marker['line_height_px']
    line_count = (sum(len(break_lines(row, face, width-2*pad_x-marker['gutter'])) for row in rows)
                  if wrap_items else len(rows))
    height = (line_count*line_h
              +max(0, len(rows)-1)*round(line_h*gap_ratio, 2)+2*pad_y+(44 if block.get('label') else 0))
    # Height is content-dependent. A fixed floor creates unexplained gaps in compact regions.
    # preserve_terms affects overflow handling at emission time, not the measured minimum.
    return height


def text_floor_height(text, width, font_file, floor=24, max_lines=10, inline_math=False):
    """Height of ``text`` at ``floor`` px, or None when it cannot fit in ``max_lines``.

    Body copy is measured at the size it will be set at (21 pt, not the 18 pt emergency floor), so a
    slot is big enough for the page's one body size instead of being shrunk back to the floor later.
    """
    face = ImageFont.truetype(font_file, floor)
    if inline_math:
        from totalpipe_layout.inline_math import InlineWidthError, measure_inline
        try:
            plan = measure_inline(text, width, face, floor)
        except InlineWidthError:
            return None
        return plan['height'] if len(plan['lines']) <= max_lines else None
    lines = break_lines(text, face, max(1, width))
    if len(lines) > max_lines:
        return None
    return len(lines) * floor * 1.25


def formula_label_width(label, bold_font_file, size=24):
    """Width of the label that sits to the left of an equation, capped."""
    if not label:
        return 0.0
    face = ImageFont.truetype(bold_font_file, size)
    return min(FORMULA_LABEL_MAX, max(56.0, float(face.getlength(label)) + 12))


def formula_widths(text, sizes=None):
    """Measured metrics at every allowed size, widest (the floor) last."""
    from totalpipe_layout.formula import measure, parse
    ast = parse(text)
    return {size: measure(ast, size) for size in (sizes or FORMULA_SIZES)}


def formula_fit(text, width, sizes=None):
    """Metrics of the largest allowed size whose measured width fits ``width``, else None."""
    widths = formula_widths(text, sizes)
    for size in (sizes or FORMULA_SIZES):
        if widths[size].width <= width:
            return widths[size]
    return None


def formula_column_width(blocks, bold_font_file, base, limit):
    """The text column a formula page needs: inline label + equation at 18 pt, else ``base``.

    An equation is the one element that cannot be re-wrapped, so on a formula page the column is
    derived from the equation instead of the equation being squeezed into the default column. The
    figure keeps the rest of the width.
    """
    need = base
    for block in blocks:
        if block.get("component") != "formula":
            continue
        label_w = formula_label_width(block.get("label", ""), bold_font_file)
        gaps = (label_w + 12) if label_w else 0
        widths = formula_widths(block["text"])
        # The largest size the column can carry: an equation is the reason the page exists, so it
        # is set as large as the figure allows instead of at the 18 pt floor by default.
        chosen = next((widths[size] for size in FORMULA_SIZES
                       if gaps + widths[size].width + 24 <= limit), widths[FORMULA_SIZES[-1]])
        need = max(need, gaps + chosen.width + 24)
    return min(limit, need)


def frame_variant(ir):
    """Use one title/takeaway/body grid for the whole deck."""
    explicit = (ir.get("presentation") or {}).get("frame_variant")
    if explicit:
        return explicit
    return ("spacious" if any(slide.get("presentation", {}).get("variant") == "spacious"
                              for slide in ir["slides"]) else "default")


def sequence_flow(composition):
    """Render an explicit process intent, retaining the legacy role heuristic."""
    blocks = composition["blocks"]
    if composition.get("graphics") or composition.get('layout_tree'):
        return False  # The declared graphic edges own the process topology.
    intent = composition.get("visual_intent")
    if intent is not None:
        return intent.get("relation") == "process"
    return (composition["archetype"] == "figure-parameters" and
            len(composition["figure_refs"]) == 1 and len(blocks) == 4 and
            not any(block.get("label") for block in blocks) and
            blocks[0]["component"] == "method" and
            any(block["component"] == "process-step" for block in blocks) and
            blocks[-1]["component"] == "result")


TOKEN = re.compile(r"[A-Za-z0-9_\u00c0-\u02af\u0370-\u03ff][A-Za-z0-9_.:/\\\-\u00c0-\u02af\u0370-\u03ff\u1d2c-\u1d6a\u2070-\u209f¹²³]*(?:%|[×x])?|[^\S\n]+|.")
# Kinsoku: a line may not begin with closing punctuation or a unit suffix. When the break would
# land there, the previous character travels down with it instead. Two real review findings drove
# this: a wrapped "1." / "19×" (the DECIMAL_SPLIT rule) and a line that consisted of "。" alone.
NO_LINE_START = set('，。、；：？！）】》」』”’,.;:?!)]}%×')


_CJK_ORPHAN_RE = re.compile(r'^[\u3400-\u9fff][，。、；：？！）】》」』”’,.!?;:)]*$')


def break_lines(text, font, width):
    """Preserve paragraphs, break at words/CJK glyphs, and prevent 1-CJK-char orphan lines."""
    lines = []
    for paragraph in text.split("\n"):
        para_start = len(lines)
        pieces = []
        current = ''
        for token in TOKEN.findall(paragraph):
            if pieces and font.getlength(current + token) > width:
                # Kinsoku: a closing mark or unit never starts a line. The token before it travels
                # down instead, so "2.84×，" does not become "2.84" / "×，".
                if token[:1] in NO_LINE_START and len(current.strip()) > 2:
                    carried = pieces.pop()
                    lines.append(''.join(pieces).rstrip())
                    current = carried + token.lstrip()
                    pieces = [current]
                    continue
                lines.append(current.rstrip())
                pieces = []
                current = ''
                token = token.lstrip()
            if not pieces and font.getlength(token) > width:
                for char in token:
                    if pieces and font.getlength(current + char) > width:
                        lines.append(current.rstrip())
                        pieces = []
                        current = ''
                    pieces.append(char)
                    current += char
                continue
            pieces.append(token)
            current += token
        lines.append(current.rstrip())
        # CJK orphan guard: avoid leaving a lone CJK character (+ optional punctuation) on the final line.
        if (len(lines) - para_start >= 2
                and _CJK_ORPHAN_RE.fullmatch(lines[-1].strip())
                and len(lines[-2]) >= 3
                and '\u3400' <= lines[-2][-1] <= '\u9fff'):
            cand_prev = lines[-2][:-1].rstrip()
            cand_last = lines[-2][-1] + lines[-1]
            if cand_prev and font.getlength(cand_last) <= width:
                lines[-2], lines[-1] = cand_prev, cand_last
    return lines


def fit_text(text, bbox, contract):
    inner_w = bbox[2] - contract.inset["left"] - contract.inset["right"]
    inner_h = bbox[3] - contract.inset["top"] - contract.inset["bottom"]
    for size in range(int(contract.font_size), int(contract.font_floor) - 1, -1):
        font = ImageFont.truetype(contract.font_file, size)
        lines = break_lines(text, font, inner_w)
        # OfficeCLI writes this exact line spacing into DrawingML.
        if (len(lines) <= contract.max_lines and len(lines) * size * contract.line_height <= inner_h
                and all(font.getlength(line) <= inner_w for line in lines)):
            return "\n".join(lines), replace(contract, font_size=size)
    raise ValueError("SPLIT_REQUIRED")


def intersect(a, b):
    return min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0]) > .5 and \
           min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]) > .5


def text_visible_bottom(element):
    """Estimate the occupied text bottom edge, respecting vertical anchor."""
    _x, y, _w, height = element["bbox"]
    contract = element["contract"]
    if element.get('inline_math'):
        occupied = element['inline_layout']['height']
    elif element['kind'] == 'list':
        occupied = (sum(len(lines) for lines in element['items']) * contract['font_size'] * contract['line_height']
                    + element['bullet'].get('space_after', 0) * max(0, len(element['items']) - 1))
    else:
        line_count = len(re.split('[\n\v]', element["text"]))
        occupied = line_count * contract["font_size"] * contract["line_height"]
    vis_h = min(height, contract["inset"]["top"] + occupied + contract["inset"].get("bottom", 0))
    anchor = contract.get("vertical_anchor", "top")
    if anchor == "middle":
        return min(y + height, y + (height - vis_h) / 2 + vis_h)
    if anchor == "bottom":
        return y + height
    return min(y + height, y + contract["inset"]["top"] + occupied)


def lower_whitespace_issue(elements, slide_number, body_top, body_bottom):
    """Notify on a large empty lower band in a text-only column layout."""
    content = [element for element in elements
               if element["kind"] in ('text', 'list', 'math') and element["role"] in ("heading", "body", 'formula')
               and body_top <= element["bbox"][1] < body_bottom]
    if not content:
        return None
    content_bottom = max((element['bbox'][1]+element['bbox'][3] if element['kind'] == 'math'
                          else text_visible_bottom(element)) for element in content)
    gap = body_bottom - content_bottom
    share = gap / (body_bottom - body_top)
    if gap < 160 or share < .40:
        return None
    return issue('CONTENT_LOWER_WHITESPACE' if any(e['kind'] == 'math' for e in content)
                 else "TEXT_ONLY_LOWER_WHITESPACE", "WARNING",
                 f"Page content ends near y={content_bottom:.0f}px; the lower {gap:.0f}px "
                 f"({share:.0%} of the body area) is empty. Review vertical balance or "
                 "choose a layout that uses the available space.",
                 slide_number, detector="design-preflight", confidence="MEDIUM",
                 body_top_px=body_top, body_bottom_px=body_bottom,
                 content_bottom_px=round(content_bottom), empty_lower_px=round(gap),
                 empty_share=round(share, 3))


def body_whitespace_issue(elements, slide_number, body_top, body_bottom):
    """Detect genuinely excessive 2D whitespace across the full body band using exact union ink."""
    if body_bottom - body_top < 120:
        return None
    from .whitespace import analyze_region_whitespace, visible_element_boxes

    body_bounds = [56.0, float(body_top), 1168.0, float(body_bottom - body_top)]
    visible = visible_element_boxes(elements, body_bounds, include_header=False)
    if not visible:
        return None
    metrics = analyze_region_whitespace(
        visible, body_bounds, min_empty_size=(360.0, 160.0), margin=0.0
    )
    if metrics['coverage_ratio'] >= 0.25 or metrics['largest_empty_ratio'] < 0.45:
        return None
    return issue(
        'BODY_WHITESPACE_EXCESSIVE',
        'REVIEW',
        f"Body visible ink covers only {metrics['coverage_ratio']:.0%} of the body band; "
        f"the largest contiguous empty region covers {metrics['largest_empty_ratio']:.0%} "
        f"({metrics['empty_quadrants']}/4 quadrants empty). Consider a richer multi-zone layout "
        "or an example from the library.",
        slide_number,
        detector='design-preflight',
        confidence='MEDIUM',
        body_coverage_ratio=metrics['coverage_ratio'],
        whitespace_ratio=metrics['whitespace_ratio'],
        largest_empty_ratio=metrics['largest_empty_ratio'],
        largest_empty_rect=metrics['largest_empty_rect'],
        empty_quadrants=metrics['empty_quadrants'],
        suggested_actions=['add_supporting_visual', 'consult_example_library', 'rebalance_columns'],
    )


def sparse_text_page(entry, elements):
    """Whether this stack is the bare-document look: text only, less than half its region filled.

    The measure is one stack's own region, so a page that already carries a figure, table or
    graphic elsewhere is not sparse text even when its text column is short: that page has a
    composition, and advising it to "use two columns" describes columns it already has. Only a
    page whose ink is all stacked text gets the warning.
    """
    if entry['type'] != 'stack' or entry['bbox'][3] <= 0:
        return False
    prefix = entry['component']
    own = [e for e in elements if (e.get('layout_component') or '').startswith(prefix)]
    if not own:
        return False
    if any(e['kind'] in ('image', 'table', 'math', 'connector') or e.get('graphic_id') for e in own):
        return False
    # A connector is a rule or an arrow, not a composition; only real visual objects count as the
    # page's other half.
    if any(e['kind'] in ('image', 'table', 'math') or e.get('graphic_id') for e in elements
           if not (e.get('layout_component') or '').startswith(prefix)):
        return False
    return entry['requirements']['preferred_height_px']/entry['bbox'][3] < .5


def graphic_page_regions(composition, region, assets, font_paths, visual_plan=None, *, design=None,
                         list_gap_ratio=DEFAULT_LIST_GAP, list_padding=(0, 0), bullet_style='large_square'):
    """Finite page-level candidates; graph internals stay with compile_graphic.

    Measure context at the existing font floor and keep each image with its caption.
    The real block/figure/graphic emitters still make the final capacity decision.
    """
    x, y, width, height = region
    blocks, figures = composition['blocks'], composition['figure_refs']
    gap = 24.0
    if visual_plan and not figures:
        from .academic_layout import graphic_without_evidence
        yield from graphic_without_evidence(composition, region, font_paths, visual_plan,
                                             design=design, list_gap_ratio=list_gap_ratio,
                                             bullet_style=bullet_style)
        return

    def need(block, w):
        if block.get('component') == 'caption':
            return caption_measure({'caption': block['text']}, w, font_paths['font_file'], design)[0]
        list_height = native_list_height(block, w, font_paths['font_file'], list_gap_ratio,
                                         list_padding, default_style=bullet_style)
        if list_height is not None:
            return list_height
        label = block.get('label', '')
        if block.get('component') == 'formula':
            label_w = formula_label_width(label, font_paths['bold_font_file'])
            metrics = formula_fit(block['text'], w-20-(label_w+12 if label_w else 0))
            return max(30 if label else 0, metrics.height+12) if metrics else 10000
        label_h = (40 if composition['archetype'] == 'figure-parameters' else 44) if label else 0
        from .type_scale import body_size, display_floor
        display = display_floor(block, design)
        return label_h + (text_floor_height(block['text'], w, font_paths['font_file'],
                                            floor=display or body_size(design),
                                            max_lines=2 if display else 10,
                                            inline_math=block.get('inline_math', False)) or 10000)

    def rows(w, bx, by):
        boxes = []
        for b in blocks:
            h = need(b, w)
            boxes.append([bx, by, w, h])
            by += h+gap
        return boxes, sum(b[3] for b in boxes)+gap*max(0, len(boxes)-1)

    band_w = (width-gap*max(0, len(blocks)-1))/max(1, len(blocks))
    band_h = max((need(b, band_w) for b in blocks), default=0)
    band = [[x+i*(band_w+gap), y, band_w, band_h] for i in range(len(blocks))]
    body_y = y+band_h+(gap if blocks else 0)
    body_h = y+height-body_y
    if not figures:
        yield {'pattern': 'context-above-graphic', 'blocks': band, 'figures': [],
               'graphic': [x, body_y, width, body_h]}
        return

    # Keep the familiar figure-left convention; process pages read diagram -> evidence.
    if visual_plan:
        from .academic_layout import ratios
        shares = ratios(visual_plan.get('graphic_width_ratio', .68), .4, .9)
        figure_widths = [(width-gap)*(1-share) for share in shares]
        if visual_plan['composition'] == 'graphic-top':
            figure_widths = []
    else:
        figure_widths = (360.0, 280.0, 440.0, 224.0, 520.0)
    for figure_w in figure_widths:
        graphic_w = width-gap-figure_w
        figure_left = (visual_plan['composition'] == 'graphic-right' if visual_plan
                       else composition['archetype'] == 'figure-parameters')
        figure_x, graphic_x = ((x, x+figure_w+gap)
                              if figure_left
                              else (x+graphic_w+gap, x))
        above = {'pattern': 'context-above-visuals', 'blocks': band,
               'figures': [[figure_x, body_y, figure_w, body_h]],
               'graphic': [graphic_x, body_y, graphic_w, body_h]}
        context, context_h = rows(figure_w, figure_x, y)
        figure_y = y+context_h+(gap if blocks else 0)
        beside = {'pattern': 'context-with-evidence', 'blocks': context,
               'figures': [[figure_x, figure_y, figure_w, y+height-figure_y]],
               'graphic': [graphic_x, y, graphic_w, height]}
        ordered = (beside, above) if visual_plan and visual_plan.get('context_placement') == 'with-evidence' else (above, beside)
        for candidate in ordered:
            if visual_plan:
                candidate['graphic_width_ratio'] = graphic_w/(width-gap)
            yield candidate

    if visual_plan and visual_plan['composition'] != 'graphic-top':
        return

    # Wide graphs can use a full-width upper band when the frame has enough height.
    figure_w = (width-gap)/2 if blocks else width
    figure_x = x if composition['archetype'] == 'figure-parameters' else x+width-figure_w
    text_x = x+figure_w+gap if composition['archetype'] == 'figure-parameters' else x
    context, context_h = rows(figure_w, text_x, 0)
    ref, asset = figures[0], assets[figures[0]['asset_id']]
    extent = ref.get('min_panel_extent', 220)
    image_h = max(extent, extent*ref.get('panel_count', 1)*asset['height']/asset['width'])
    ch = (ref.get('caption_height') or caption_measure(ref, figure_w, font_paths['font_file'])[0]
          ) if ref['caption'] else 0
    lower_h = max(context_h, image_h+ch+12)
    lower_y = y+height-lower_h
    shares = ratios(visual_plan.get('graphic_width_ratio', 1.0), .4, 1.0) if visual_plan else [1.0]
    for graphic_share in shares:
        yield {'pattern': 'graphic-above-evidence',
               'blocks': [[bx, lower_y+by, bw, bh] for bx, by, bw, bh in context],
               'figures': [[figure_x, lower_y, figure_w, lower_h]],
               'graphic': [x+(width-width*graphic_share)/2, y, width*graphic_share, height-lower_h-gap],
               **({'graphic_width_ratio': graphic_share} if visual_plan else {})}


# Page furniture sits below the caveat strip: a hairline and a page number are the cheapest signal
# that a deck is a finished document rather than a strip of screenshots. It is deliberately the
# quietest object on the page — supporting ink, 15-16 pt — so it never competes with the content.
FOOTER_RULE_Y = 664.0
FOOTER_TEXT_Y = 672.0
FOOTER_TEXT_H = 28.0
FOOTER_NUMBER_BOX = [1160, FOOTER_TEXT_Y, 64, FOOTER_TEXT_H]
FOOTER_TEXT_BOX = [56, FOOTER_TEXT_Y, 880, FOOTER_TEXT_H]


def page_furniture_elements(elements, text, number, slide, presentation, design, furniture):
    """Bottom rule, page number and the deck's own footer line on a designed page.

    Evidence ids are traceability keys and stay in the speaker notes; what the audience needs is a
    number they can refer to and a line that says whose deck this is. Both are opt-out per deck
    (``presentation.page_numbers``) and per page (``presentation.page_number``).
    """
    if not design or furniture.get('furniture', 'rule') == 'none':
        return
    if (slide.get('composition') or {}).get('archetype') == 'cover':
        return      # the page before page 1 carries no number and no footer
    numbering = slide.get('presentation', {}).get('page_number',
                                                  presentation.get('page_numbers', True))
    footer = presentation.get('footer')
    if numbering is False and not footer:
        return
    elements.append({'id': 'page:rule', 'kind': 'shape', 'role': 'decoration',
                     'bbox': [56, FOOTER_RULE_Y, 1168, 1], 'geometry': 'rect',
                     'fill': furniture['rule'], 'line': 'none', 'line_width': 0,
                     'visual_decoration': True})
    if footer:
        text('page:footer', footer, list(FOOTER_TEXT_BOX), 'footer', furniture['footer_size'], 20, 1,
             color=furniture['footer_ink'])
    if numbering is not False:
        text('page:number', str(number), list(FOOTER_NUMBER_BOX), 'footer',
             furniture['number_size'], 20, 1, color=furniture['number_ink'], align='right')


# A table of contents is a page the deck already knows how to write: the sections are the ones the
# author marked with presentation.section and the page numbers are the compiler's own. Nothing here
# is new content, so the page never consumes a Story item and never invents a page reference.
AGENDA_ROW_GAP = 52.0
AGENDA_NUMBER_W = 64.0
AGENDA_DOT = '·'
AGENDA_MAX_SECTIONS = 8


def agenda_sections(ir):
    """``[(label, first slide index)]`` in deck order, one entry per section start."""
    sections, current = [], None
    for index, slide in enumerate(ir.get('slides') or [], 1):
        label = str((slide.get('presentation') or {}).get('section') or '').strip()
        if label and label != current:
            sections.append((label, index))
            current = label
    return sections


def _fitted_element(eid, content, bbox, role, size, font_file, family, color,
                    floor=None, max_lines=1, align=None):
    """One measured text element for a page the compiler writes itself."""
    contract = TextBoxContract(family, size, font_file,
                               font_weight=700 if role in ('title', 'heading') else 400,
                               font_floor=floor or size, max_lines=max_lines, vertical_anchor='top')
    output, fitted = fit_text(content, bbox, contract)
    element = {'id': eid, 'kind': 'text', 'role': role, 'text': output, 'source_text': content,
               'bbox': list(bbox), 'contract': fitted.to_dict(), 'color': color}
    if align:
        element['align'] = align
    return element


def agenda_slide(agenda, sections, theme, font_paths, design, number, furniture, footer_text=None):
    """The generated contents page: numbered sections, dot leaders, the page each one starts on.

    The label text is the author's own section name; the dot leader is measured against the same
    font that draws it and the number column is right-aligned, so the rows read as a contents page
    instead of as a list of sentences.
    """
    family, regular, bold = theme['font_family'], font_paths['font_file'], font_paths['bold_font_file']
    from .style import named_color
    title_size = type_sizes(design)['title']
    header = header_layout(design)
    rows_top = header['body_top']+8
    ink = theme.get('foreground', '#142735')
    accent = theme.get('accent', DEFAULT_ACCENT)
    elements = [_fitted_element('agenda:title', str(agenda.get('title') or '目录'), header['title'],
                                'title', title_size, bold, family, accent, max_lines=1)]
    if design['title_treatment'] == 'thin-rule':
        elements.append(rule('agenda:title-rule', header['rule'], design))
    size = float(type_sizes(design)['body'])
    face = ImageFont.truetype(regular, int(size))
    dot = face.getlength(AGENDA_DOT) or 1.
    muted = named_color('muted', theme)
    for index, (label, first) in enumerate(sections[:AGENDA_MAX_SECTIONS], 1):
        y = rows_top+(index-1)*AGENDA_ROW_GAP
        row_w = 1168-AGENDA_NUMBER_W-24
        numbered = f'{index:02d}  {label}'
        label_w = face.getlength(numbered)
        # The label box hugs its own text: a box spanning the whole row would overlap the leader
        # that starts where the text ends.
        text_w = min(row_w, label_w+6)
        elements.append(_fitted_element(f'agenda:row:{index}', numbered, [56, y, text_w, 30], 'body',
                                        size, regular, family, ink, floor=24, max_lines=1))
        # The leader is its own run so it can stay in the supporting ink: a row of dots at body
        # weight competes with the section names it is supposed to point at.
        leader_x, leader_w = 56+text_w+8, row_w-text_w-8
        dots = max(0, int(leader_w/dot))
        if dots:
            # A couple of pixels of slack keeps OfficeCLI's width estimate from calling the leader
            # a two-line paragraph; PowerPoint draws it on one line either way.
            elements.append(_fitted_element(f'agenda:leader:{index}', AGENDA_DOT*dots,
                                            [leader_x, y, min(leader_w, dots*dot+3), 30], 'body', size,
                                            regular, family, muted, floor=24, max_lines=1))
        page = first+1 if first > 1 else first     # the agenda page itself shifts later pages by one
        elements.append(_fitted_element(f'agenda:page:{index}', str(page),
                                        [56+row_w+24, y, AGENDA_NUMBER_W, 30], 'badge',
                                        float(furniture['number_size']), regular, family,
                                        furniture['number_ink'], floor=20, max_lines=1, align='right'))
    if furniture.get('furniture', 'rule') != 'none':
        elements.append({'id': 'page:rule', 'kind': 'shape', 'role': 'decoration',
                         'bbox': [56, FOOTER_RULE_Y, 1168, 1], 'geometry': 'rect',
                         'fill': furniture['rule'], 'line': 'none', 'line_width': 0,
                         'visual_decoration': True})
    footer = footer_text or (agenda.get('footer') if isinstance(agenda, dict) else None)
    if footer:
        elements.append(_fitted_element('page:footer', str(footer), list(FOOTER_TEXT_BOX), 'footer',
                                        float(furniture['footer_size']), regular, family,
                                        furniture['footer_ink'], floor=20, max_lines=1))
    if number is not None:
        elements.append(_fitted_element('page:number', str(number), list(FOOTER_NUMBER_BOX), 'footer',
                                        float(furniture['number_size']), regular, family,
                                        furniture['number_ink'], floor=20, max_lines=1, align='right'))
    return {'id': 'agenda', 'background': theme.get('background', '#FFFFFF'),
            'notes': '目录页：由 presentation.section 的章节标记生成，页码由编译器按最终页序计算。',
            'elements': elements,
            'adaptation_log': [{'action': 'agenda', 'sections': [label for label, _ in sections]}]}


def geometry_issues(elements, number):
    """The same page gates run on every candidate and on the final composition."""
    findings = []
    from .container_frames import containment_errors
    for frame_id, message in containment_errors(elements):
        findings.append(issue('FRAME_CONTENT_OUT_OF_BOUNDS', 'FAIL', message, number, frame_id,
                              detector='geometric-preflight'))
    for edge_id, obstacle_id in graphic_obstacle_collisions(
            [e for e in elements if e['kind'] == 'connector'], elements):
        overflow = any(e['id'] == obstacle_id and e.get('scientific_text_overflow') for e in elements)
        findings.append(issue('GRAPHIC_ROUTE_THROUGH_CONTENT', 'REVIEW' if overflow else 'FAIL',
            f'Connector crosses page content {obstacle_id}', number, edge_id,
            detector='geometric-preflight'))
    for idx, element in enumerate(elements):
        x, y, w, h = element['bbox']
        invalid = (w < 0 or h < 0 or w+h <= 0) if element['kind'] == 'connector' else (w <= 0 or h <= 0)
        if x < 0 or y < 0 or invalid or x+w > WIDTH+.1 or y+h > HEIGHT+.1:
            findings.append(issue('SHAPE_OUT_OF_BOUNDS', 'REVIEW' if element.get('scientific_text_overflow') else 'FAIL', 'Invalid element geometry',
                                  number, element['id'], detector='geometric-preflight'))
        for other in elements[:idx]:
            if element.get('collision_mode') == 'container' or other.get('collision_mode') == 'container':
                continue
            if intentional_overlap(element, other) or element.get('route') or other.get('route'):
                continue
            if intersect(element['bbox'], other['bbox']):
                findings.append(issue('CRITICAL_COLLISION', 'REVIEW' if element.get('scientific_text_overflow') or other.get('scientific_text_overflow') else 'FAIL', f"Overlaps {other['id']}",
                                      number, element['id'], detector='geometric-preflight'))
    return findings


def _resolve_deck_context(ir, base, issues):
    base = Path(base)
    design = resolve_design(ir)
    preserve_terms = preserve_scientific_terms(ir)
    theme = {**ir['theme'], **({'accent': design['accent_color']} if design else {})}
    from .style import StyleError, page_furniture, resolve as resolve_style, text_styles
    try:
        theme['_visual_style'] = resolve_style(ir.get('presentation'))
    except StyleError as error:
        issues.append(issue('VISUAL_STYLE_INVALID', 'FAIL', str(error), detector='geometric-preflight'))
        return None
    text_inks = text_styles(theme)
    furniture = page_furniture(theme)
    # Fonts are resolved by the platform, not by the deck's author: a theme may name a file from
    # another operating system, and a deck that cannot find its declared face is still deliverable in
    # a substituted one. Only "no font anywhere" is a FAIL.
    from .fonts import resolve_theme_fonts
    # Every character the deck will set, so the resolver can reject a face that cannot draw them.
    # The compiler's own strings count too: the evidence family draws 直接证据 / 假设（未证实） and the
    # header separator ·, none of which appear in the Deck IR. The list marker is left out of the
    # sample on purpose: it has its own face (a:buFont) and letting it decide the body face would
    # push a Chinese deck from a sans face to a symbol one.
    compiler_strings = '·0123456789'
    from totalpipe_layout.inline_math import prose_only
    font_sample = lambda value, enabled=False: prose_only(value) if enabled else value
    if any(ARCHETYPES[s['composition']['archetype']]['layout'] == 'evidence' for s in ir['slides']):
        compiler_strings += '直接证据假设（未证实）'
    text_sample = compiler_strings + "".join(
        [font_sample(slide['semantic'].get(field, ''), field in slide['semantic'].get('inline_math', []))
         for slide in ir['slides'] for field in ('title', 'purpose', 'takeaway', 'speaker_notes')]
        + [font_sample(block.get("text", ""), block.get('inline_math', False)) + block.get("label", "") for slide in ir["slides"]
           for block in slide["composition"]["blocks"]]
        + [figure.get("caption", "") + "".join(
               h.get("label", "") for h in figure.get("highlights", []) if isinstance(h, dict))
           for slide in ir["slides"]
           for figure in slide["composition"]["figure_refs"]]
        + [value for slide in ir["slides"] for graphic in slide["composition"].get("graphics", [])
           for _, value in graphic_texts(graphic)]
        + [node['title'] for slide in ir['slides']
           for _, node in walk_regions(
               slide['composition'].get('layout_tree', {'regions': {}})) if node['type'] == 'panel']
        + [font_sample(cell['text'], cell.get('inline_math', False)) for slide in ir['slides'] for table in slide['composition'].get('tables', [])
           for cell in table['cells'] if cell.get('kind', 'text') == 'text'])
    try:
        regular_font, bold_font, font_notes = resolve_theme_fonts(theme, base, text_sample)
    except (FileNotFoundError, OSError) as error:
        issues.append(issue("FONT_UNAVAILABLE", "FAIL", str(error), detector="geometric-preflight"))
        return None
    font_paths = {"font_file": regular_font, "bold_font_file": bold_font}
    # The measured fallback must also be the native typeface. Keeping the authored Arial family
    # after measuring a CJK fallback lets PowerPoint choose different advances and overrun a panel.
    theme['font_family'] = ImageFont.truetype(regular_font, 24).getname()[0]
    # Characters the deck-level font note already covers: repeating them per text element turns one
    # real finding into fifty identical REVIEWs and buries everything else in the report.
    deck_gap = set()
    for note in font_notes:
        if note['rule'] in ('FONT_SUBSTITUTED', 'FONT_GLYPH_FALLBACK'):
            deck_gap.update(note.get('detail', {}).get('unsupported_characters', ''))
    bullet_style = choose_bullet_style(ir)
    bullet_color = (ir.get('presentation') or {}).get('bullet_color', theme.get('accent', DEFAULT_ACCENT))
    list_gap_ratio = float((ir.get("presentation") or {}).get("list_gap", DEFAULT_LIST_GAP))
    for note in font_notes:
        issues.append(issue(note["rule"], note["severity"], note["message"],
                            detector="font-resolution", detail=note.get("detail")))
    assets = {}
    for key, asset in ir.get("assets", {}).items():
        path = (base / asset["path"]).resolve()
        try:
            if 'crop' in asset:
                from .crops import verified_source
                verified_source(asset, base)
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                assets[key] = {**asset, "path": str(path), "width": image.width,
                               "height": image.height, "sha256": file_hash(path),
                               "content_type": Image.MIME[image.format]}
        except (OSError, ValueError, KeyError) as e:
            issues.append(issue("ASSET_INVALID", "FAIL", f"{key}: {e}", detector="geometric-preflight"))
    if any(i["severity"] == "FAIL" for i in issues):
        return None
    # A full-bleed background is declared by the theme and drawn by the compiler beneath every
    # element. It used to be stamped into the slide master by a script that ran after QA, which is
    # how a delivered deck ended up with bytes no report had inspected.
    background_key = None
    background_image = theme.get("background_image")
    if background_image:
        from . import background as background_layer
        path = (base / background_image).resolve()
        try:
            _, findings = background_layer.review(
                path, theme.get("foreground", "#142735"), path.stat().st_size)
            issues += findings
            assets["@background"] = {"path": str(path), "width": WIDTH, "height": HEIGHT,
                                     "sha256": file_hash(path), "content_type": "image/png"}
            background_key = "@background"
        except (OSError, ValueError) as error:
            issues.append(issue("BACKGROUND_INVALID", "FAIL", f"{background_image}: {error}",
                                detector="geometric-preflight"))
            return None
    return {
        "ir": ir, "design": design, "preserve_terms": preserve_terms, "theme": theme,
        "text_inks": text_inks, "furniture": furniture, "regular_font": regular_font,
        "font_paths": font_paths, "deck_gap": deck_gap, "bullet_style": bullet_style,
        "bullet_color": bullet_color, "list_gap_ratio": list_gap_ratio,
        "assets": assets, "background_key": background_key, "deck_frame": frame_variant(ir),
    }


class _SlideCompiler:
    def __init__(self, ctx, n, slide, issues):
        self.ctx = ctx
        self.ir = ctx["ir"]
        self.design = ctx["design"]
        self.preserve_terms = ctx["preserve_terms"]
        self.theme = ctx["theme"]
        self.text_inks = ctx["text_inks"]
        self.furniture = ctx["furniture"]
        self.regular_font = ctx["regular_font"]
        self.font_paths = ctx["font_paths"]
        self.deck_gap = ctx["deck_gap"]
        self.bullet_style = ctx["bullet_style"]
        self.bullet_color = ctx["bullet_color"]
        self.list_gap_ratio = ctx["list_gap_ratio"]
        self.assets = ctx["assets"]
        self.deck_frame = ctx["deck_frame"]
        self.issues = issues
        self.n = n
        self.slide = slide
        self.sem = slide["semantic"]
        self.visual_plan = slide['presentation'].get('visual_plan')
        # Deck IR fallback: a block whose text is several paragraphs is a list, even when the author
        # forgot to say so. The copy keeps the caller's IR untouched.
        from .text_flow import fallback_list
        comp = slide["composition"]
        self.blocks = [fallback_list(block) for block in comp["blocks"]]
        self.comp = {**comp, "blocks": self.blocks}
        self.figs = self.comp["figure_refs"]
        # A page whose only object is one equation is an equation page: let it use the display
        # ladder, so the formula is the anchor instead of a body-sized line. Long equations fall
        # back down the ladder on their own when the measured width does not fit.
        self.equation_page = (len([b for b in self.blocks if b.get('component') == 'formula']) == 1
                              and not self.figs and not self.comp.get('tables') and not self.comp.get('graphics')
                              and len(self.blocks) <= 4)
        self.formula_sizes = DISPLAY_FORMULA_SIZES + FORMULA_SIZES if self.equation_page else FORMULA_SIZES
        self.show_sequence = sequence_flow(self.comp)
        self.visual_intent = self.comp.get("visual_intent") or {}
        self.family = ARCHETYPES[self.comp["archetype"]]["layout"]
        self.elements = []
        self.adaptations = []
        self.slide_formulas = []
        self.scientific_text_ids = {'title', 'takeaway', *(b['id'] for b in self.blocks), *(b['id'] + ':label' for b in self.blocks)}
        if self.comp.get('layout_tree'):
            from .layout_tree import walk
            self.scientific_text_ids.update('region:' + node['id'] + ':title'
                                            for _, node in walk(self.comp['layout_tree']) if node['type'] == 'panel')
        self.takeaway_marker = None
        self.takeaway_outer = None
        self.spacious = self.deck_frame == "spacious"
        self.templated = self.deck_frame == "template"
        self.footer = " · ".join(self.sem["evidence_refs"])
        self.visible_caveats, self.moved_caveats = audience.split_caveats(self.sem["caveats"])
        self.top = 0
        self.bottom = 0
        self.bh = 0

    def emit_text(self, eid, content, bbox, role="body", size=28, floor=24, lines=10,
                  anchor="top", color=None, flow=None, align=None, inline_math=False, marker=None):
        if not content:
            return
        if self.design and role in type_sizes(self.design) and not eid.startswith('graphic:'):
            size = min(size, type_sizes(self.design)[role])
        contract = TextBoxContract(self.theme["font_family"], size,
            self.font_paths["bold_font_file" if role in ("title", "heading") else "font_file"],
            font_weight=700 if role in ("title", "heading") else 400,
            font_floor=floor, max_lines=lines, vertical_anchor=anchor)
        if marker:
            contract = replace(contract, line_height=max(contract.line_height, marker['line_height_px'] / size))
        measure_box = [*bbox[:2], bbox[2] - (marker['gutter'] if marker else 0), bbox[3]]
        overflow = None
        # Authored emphasis is a measured run, not a decoration: the phrase is set in the bold
        # face, so it is laid out by the same inline engine that already handles a formula in a
        # sentence. Text without markers keeps the plain, cheaper path byte for byte.
        markup = has_markup(content)
        if inline_math or markup or (role == 'caption' and has_bare_subscript(content)):
            from .inline_text import fit_inline, text_body
            from totalpipe_layout.inline_math import InlineWidthError
            try:
                plan, fitted, overflowed = fit_inline(content, measure_box, contract,
                    self.preserve_terms and eid in self.scientific_text_ids, marker,
                    self.font_paths['bold_font_file'])
            except InlineWidthError as error:
                self.issues.append(issue('INLINE_FORMULA_SPACE', 'FAIL', str(error), self.n, eid,
                    detector='geometric-preflight', required_size_px=[error.required_width, 0],
                    available_size_px=bbox[2:], suggested_actions=['widen_region', 'use_display_formula', 'split_slide']))
                return
            except ValueError as error:
                self.issues.append(issue('INLINE_TEXT_CAPACITY', 'FAIL', str(error), self.n, eid, detector='geometric-preflight'))
                return
            if overflowed:
                overflow = {'original_bbox': list(bbox), 'policy': 'preserve-terms'}
                bbox = [*bbox[:3], max(bbox[3], plan['height'] + contract.inset['top'] + contract.inset['bottom'])]
                self.issues.append(issue('SCIENTIFIC_TEXT_OVERFLOW', 'REVIEW',
                    f'{eid}: complete mixed text and formulas retained beyond the nominal slot.', self.n, eid, detector='geometric-preflight'))
            unpaired = unmatched_markers(content)
            if unpaired:
                # A marker pair that was never closed stays visible. Refusing the page would be
                # worse than showing the author what to fix, so the phrase is set literally and
                # the page is reported.
                self.issues.append(issue('EMPHASIS_UNCLOSED', 'REVIEW',
                    f"{eid}: {', '.join(unpaired)} is set literally; close the marker or escape it.",
                    self.n, eid, detector='geometric-preflight', suggested_actions=['close_marker', 'escape_marker']))
            colour = color or self.theme.get('foreground', '#142735')
            self.elements.append({'id': eid, 'kind': 'text', 'role': role, 'text': plan['text'], 'source_text': content,
                'bbox': bbox, 'contract': fitted.to_dict(), 'color': colour, 'inline_math': True,
                'inline_layout': plan, 'inline_xml': text_body(plan, fitted.to_dict(), colour, align or 'left', marker=marker,
                                                               styles=self.text_inks),
                **({'bullet': marker, 'leading_marker': True} if marker else {}),
                **({'align': align} if align else {}), **({'scientific_text_overflow': overflow} if overflow else {})})
            if plan['marks']:
                self.adaptations.append({'action': 'inline_emphasis', 'element': eid, 'marks': plan['marks']})
            if plan['formula_count']:
                self.issues.append(issue('INLINE_MATH_MEASUREMENT_REVIEW', 'REVIEW',
                    f'{eid}: verify native inline baseline, line spacing and formula bounds in PowerPoint.',
                    self.n, eid, detector='geometric-preflight', confidence='LOW'))
            return
        try:
            output, fitted = fit_text(content, measure_box, contract)
        except ValueError:
            if self.preserve_terms and eid in self.scientific_text_ids and min(bbox[2:]) > 0 and role != 'title':
                wrapped = break_lines(content, ImageFont.truetype(contract.font_file, int(floor)), measure_box[2])
                output = '\n'.join(wrapped)
                overflow = {'original_bbox': list(bbox), 'policy': 'preserve-terms'}
                bbox = [*bbox[:3], max(bbox[3], len(wrapped) * floor * contract.line_height)]
                fitted = replace(contract, font_size=floor, max_lines=max(lines, len(wrapped)),
                                 overflow_policy='preserve_terms_review')
                self.issues.append(issue('SCIENTIFIC_TEXT_OVERFLOW', 'REVIEW',
                    f'{eid}: full scientific text retained beyond its nominal slot; inspect the candidate without abbreviating terminology.',
                    self.n, eid, detector='geometric-preflight', original_bbox=overflow['original_bbox']))
            else:
                self.issues.append(issue("SPLIT_REQUIRED", "FAIL", f"{eid} cannot fit above its font floor",
                                         self.n, eid, detector="geometric-preflight", textbox_contract="deck_ir"))
                return
        # Missing-glyph comparison is a conservative signal, not full shaping coverage.
        font = ImageFont.truetype(fitted.font_file, int(fitted.font_size))
        missing = bytes(font.getmask(chr(0x10FFFF)))
        gaps = {c for c in set(content) if not c.isspace() and bytes(font.getmask(c)) == missing}
        if gaps and not gaps <= self.deck_gap:
            self.issues.append(issue("FONT_COVERAGE_REVIEW", "REVIEW", "Possible missing glyphs; verify in PowerPoint",
                                     self.n, eid, detector="geometric-preflight", confidence="LOW",
                                     font_metrics="pillow", characters=''.join(sorted(gaps))[:20]))
        # The declared scale, checked on the fitted size: an annotation may be 15 pt, body copy
        # may not. This is the rule the old code implied with two different floors and never
        # stated, which is how a 13.5 pt footer shipped beside 18 pt body text. A diagram label
        # is annotation: a node body is a caption inside a shape, not running copy.
        annotation = role in ANNOTATION_ROLES or eid.startswith('graphic:')
        minimum_pt = ANNOTATION_MIN_PT if annotation else BODY_MIN_PT
        if fitted.font_size * .75 < minimum_pt - .01:
            self.issues.append(issue("TYPOGRAPHY_FLOOR", "FAIL",
                                     f"{eid} is set at {fitted.font_size * .75:.1f} pt; the {role} "
                                     f"floor is {minimum_pt:.0f} pt",
                                     self.n, eid, detector="geometric-preflight", confidence="HIGH",
                                     role=role, font_pt=round(fitted.font_size * .75, 1),
                                     floor_pt=minimum_pt))
        if role == "footer" and "\n" in output:
            # A soft break, not a new paragraph: OfficeCLI's overflow estimator counts every
            # paragraph of a pre-broken footer as one line more than the renderer draws.
            output = output.replace("\n", "\v")
        unpaired = unmatched_markers(content)
        if unpaired:
            self.issues.append(issue('EMPHASIS_UNCLOSED', 'REVIEW',
                f"{eid}: {', '.join(unpaired)} is set literally; close the marker or escape it.",
                self.n, eid, detector='geometric-preflight', suggested_actions=['close_marker', 'escape_marker']))
        self.elements.append({"id": eid, "kind": 'list' if marker else "text", "role": role,
                              "text": output.replace('\n', '\v') if marker else output,
                              **({'items': [output.split('\n')], 'bullet': marker,
                                  'leading_marker': True, 'source_text': content} if marker else {}),
                              "source_text": content, "bbox": bbox, "contract": fitted.to_dict(),
                              "color": color or self.theme.get("foreground", "#142735"),
                              **({'scientific_text_overflow': overflow} if overflow else {}),
                              **({"align": align} if align else {}),
                              **({"text_flow": flow} if flow else {})})

    def emit_takeaway(self, slot, size=28, color=None, lines=2, frame_plan=None):
        if self.slide['presentation'].get('takeaway_frame'):
            from .container_frames import grow_frame, measure_takeaway, rectangle, stroke_width
            plan = frame_plan or measure_takeaway(self.slide, self.font_paths, slot, self.takeaway_marker)
            framed = rectangle('takeaway:frame', plan['bbox'], plan['style'], ['takeaway'])
            self.elements.append(framed)
            first = len(self.elements)
            self.emit_text('takeaway', self.sem['takeaway'], plan['text_bbox'], 'takeaway', size, 24,
                           plan['lines'], color=color, inline_math='takeaway' in self.sem.get('inline_math', []),
                           marker=self.takeaway_marker)
            self.takeaway_outer = grow_frame(framed, plan['bbox'], self.elements[first:],
                                             plan['padding_px'] + stroke_width(plan['style']))
            self.adaptations.append({'action': 'takeaway_frame', **plan, 'bbox': self.takeaway_outer})
        else:
            self.emit_text('takeaway', self.sem['takeaway'], slot, 'takeaway', size, 24, lines,
                           color=color, inline_math='takeaway' in self.sem.get('inline_math', []),
                           marker=self.takeaway_marker)

    def emit_header(self):
        if self.slide['presentation'].get('takeaway_marker'):
            setting = self.slide['presentation']['takeaway_marker']
            from .fonts import bullet_metrics
            self.takeaway_marker = {**bullet_metrics(setting['style'], self.theme['font_family'], self.regular_font, 28),
                                    'color': setting.get('color', self.theme.get('foreground', '#142735')),
                                    'space_after': 0}
            self.adaptations.append({'action': 'takeaway_marker', **self.takeaway_marker})
            if self.takeaway_marker['native_font_fallback']:
                self.issues.append(issue('BULLET_GLYPH_REVIEW', 'REVIEW',
                    'Requested native marker font is unavailable; inspect the Unicode fallback glyph.',
                    self.n, 'takeaway', detector='font-resolution'))
        if self.design and self.family == 'cover':
            # A cover is the page the design layer can ask for that carries no content blocks: the
            # title says what the talk is, one line says why it is worth the next forty minutes, and
            # a short accent rule sets the tone without a picture. It is deliberately the only page
            # whose title does not sit in the header box.
            sizes = type_sizes(self.design)
            self.elements.append(rule('cover:rule', [56, 268, 136, 4], self.design))
            self.emit_text('title', self.sem['title'], [56, 300, 1100, 116], 'title', sizes['title'], sizes['title'], 2)
            self.emit_text('takeaway', self.sem['takeaway'], [56, 462, 980, 96], 'takeaway', sizes['takeaway'], 24, 3)
            self.adaptations.append({'action': 'cover', 'title': self.sem['title']})
            # A cover has no caveat strip and no page furniture: it is the page before page 1.
            self.visible_caveats = []
            caveat_y, caveat_h = 604, 46
        elif self.design:
            header = header_layout(self.design, self.slide, self.font_paths, self.preserve_terms)
            # One title size for the whole deck; the header grew instead of the title shrinking.
            title_pt = header.get('title_size', type_sizes(self.design)['title'])
            self.emit_text('title', self.sem['title'], header['title'], 'title', title_pt, title_pt,
                           header.get('title_lines', 2), inline_math='title' in self.sem.get('inline_math', []))
            if header.get('title_lines', 2) >= TITLE_BOX_LINES and len(
                    break_lines(self.sem['title'], ImageFont.truetype(self.font_paths['bold_font_file'], int(title_pt)), 1168)) > TITLE_BOX_LINES:
                self.issues.append(issue('TITLE_TOO_LONG', 'FAIL',
                    'The title needs more than three lines at the deck title size; shorten it or split the page.',
                    self.n, 'title', detector='geometric-preflight', suggested_actions=['shorten_title', 'split_slide']))
            self.emit_takeaway(header['takeaway'], lines=header.get('takeaway_lines', 2), frame_plan=header.get('takeaway_frame'))
            self.elements.extend(header_decoration(self.design, header))
            caveat_y, caveat_h = (622, 36) if self.family == 'dual' else (604, 46)
        elif self.templated:
            # A lab template owns the page frame: its own title slot, its own footer band, its own
            # white page. The compiler keeps the body grid but hands the title, takeaway and caveat
            # to the template's geometry.
            # The template's title slot ends at its red rule (y=78), so the title is set to fit
            # above it and the takeaway opens the body underneath.
            self.emit_text("title", self.sem["title"], [88, 24, 1104, 50], "title", 36, 30, 2, color="#1A1A1A",
                           inline_math='title' in self.sem.get('inline_math', []))
            self.emit_takeaway([88, 84, 1104, 42], 24, color='#333333')
            caveat_y, caveat_h = 640, 36
        else:
            self.emit_text("title", self.sem["title"], [56, 24 if self.spacious else 34, 1168, 116 if self.spacious else 120],
                           "title", 44, 36, 2, inline_math='title' in self.sem.get('inline_math', []))
            # These two evidence-heavy slides use a single-line takeaway; reclaiming
            # the unused vertical room lets the original scientific panels render
            # larger without colliding with the title block.
            takeaway_h = 56 if self.slide["id"] in ("s05-anneal", "s07-contact") else 76
            self.emit_takeaway([56, 144 if self.spacious else 164, 1168, takeaway_h])
            # No footer element on any frame. The evidence ids used to be set at 15 pt under every
            # page, which meant a dozen EV numbers shared the bottom strip with the caveat. They are
            # traceability keys: the notes carry them, the room does not need them.
            caveat_y, caveat_h = 604, 46
            if self.family == "dual":
                # Compact callouts and larger scientific panels extend lower on
                # dual-evidence slides, while keeping the caveat clear.
                caveat_y, caveat_h = 622, 36
        if self.visible_caveats:
            self.emit_text("caveats", audience.join_caveats(self.visible_caveats), [56, caveat_y, 1168, caveat_h], "caveat", 24, 24, 2)
        self.top, self.bottom = body_region(self.slide, self.family, self.deck_frame, self.design, self.font_paths, self.preserve_terms)
        if self.takeaway_outer:
            self.top = max(self.top, self.takeaway_outer[1] + self.takeaway_outer[3] + 20)
        self.bh = self.bottom - self.top

    def _emit_formula_block(self, b, box, label, formula_size, formula_align):
        # A formula is a measured unit: it cannot wrap, it is never fed through the text
        # wrapper, and it is never silently set below 18 pt to make a page fit.
        from totalpipe_layout.formula import FormulaError, measure, parse, to_omml_paragraph, to_plain
        try:
            ast = parse(b["text"])
        except FormulaError as error:
            self.issues.append(issue("FORMULA_SYNTAX", "FAIL", f"{b['id']}: {error}",
                                     self.n, b["id"], detector="geometric-preflight"))
            return
        # A label sits to the left of the equation on its centre line. A heading above it
        # would cost the row 40 px, and on a dense page that is the whole difference.
        label_w = formula_label_width(label, self.font_paths["bold_font_file"])
        gaps = (label_w + 12) if label_w else 0
        inner = [box[0] + gaps, box[1] + 6, box[2] - gaps - 20 if label_w else box[2] - 20, box[3] - 12]
        chosen = None
        for size_px in ([formula_size] if formula_size is not None else self.formula_sizes):
            metrics = measure(ast, size_px)
            if metrics.width <= inner[2] + .5 and metrics.height <= inner[3] + .5:
                chosen = (size_px, metrics)
                break
        if chosen is None:
            widest = measure(ast, FORMULA_SIZES[-1])
            self.issues.append(issue(
                "FORMULA_CAPACITY", "FAIL",
                f"{b['id']} needs {widest.width:.0f} × {widest.height:.0f} px at 18 pt but its slot is "
                f"{max(inner[2], 0):.0f} × {max(inner[3], 0):.0f} px. Widen the slot or move the equation to "
                "its own slide: the compiler will not shrink the body text, or the "
                "equation below 18 pt, to make it fit.",
                self.n, b["id"], detector="geometric-preflight",
                formula_width_px=round(widest.width, 1),
                formula_height_px=round(widest.height, 1),
                slot_width_px=round(max(inner[2], 0), 1),
                slot_height_px=round(max(inner[3], 0), 1),
                suggested_fix="widen_text_column_or_split_slide"))
            return
        if label_w:
            self.emit_text(b["id"] + ":label", label,
                           [box[0], box[1] + (box[3] - 30) / 2, label_w, 30], "heading", 24, 24, 1)
        size_px, metrics = chosen
        self.slide_formulas.append((b["id"], metrics.height))
        bbox = [inner[0] + ((inner[2] - metrics.width) / 2 if formula_align == 'center' else 0),
                inner[1] + (inner[3] - metrics.height) / 2,
                metrics.width, metrics.height]
        colour = self.theme.get("foreground", "#142735")
        self.elements.append({
            "id": b["id"], "kind": "math", "role": "formula", "bbox": bbox,
            "omml": to_omml_paragraph(ast, size_px, colour,
                                      fallback_font=self.font_paths["font_file"],
                                      box_width=inner[2]),
            "plain": to_plain(ast), "font_size_px": size_px,
            "measured_exact": metrics.exact, "source_text": b["text"],
            "color": colour})
        if not metrics.exact:
            self.issues.append(issue("FORMULA_MEASURE_APPROXIMATE", "REVIEW",
                                     f"{b['id']} uses conservative structural or fallback metrics; "
                                     "verify the rendered formula width and height in PowerPoint",
                                     self.n, b["id"], detector="geometric-preflight",
                                     confidence="LOW", font_metrics="heuristic"))

    def _emit_list_block(self, b, box, label, flow, pad_x, pad_y, min_list_width):
        label_h = 44 if label else 0
        items = flow["items"]
        from .fonts import list_marker_metrics
        marker = list_marker_metrics(b, self.bullet_style, self.theme['font_family'], self.regular_font, 24, len(items))
        # One text object, one paragraph per item, marker set by the paragraph itself.
        # The theme's line height is 1.25, which is what the contract and OfficeCLI agree on.
        fitted = fit_list_items(items, box[2] - 2 * pad_x - marker['gutter'],
                                self.font_paths["font_file"], 24, 24, LIST_ITEM_LINES)
        beyond_lines = fitted is None
        if beyond_lines and not self.preserve_terms:
            self.issues.append(issue("SPLIT_REQUIRED", "FAIL",
                                     f"{b['id']} list items cannot fit above their font floor",
                                     self.n, b["id"], detector="geometric-preflight",
                                     textbox_contract="deck_ir"))
            return
        if beyond_lines:
            size = 24
            lines = [break_lines(item, ImageFont.truetype(self.font_paths['font_file'], size),
                                 box[2] - 2 * pad_x - marker['gutter']) for item in items]
        else:
            lines, size = fitted
        line_h = marker['line_height_px']
        gaps = len(lines) - 1
        # Item spacing is a typographic value, not leftover space: filling the panel is what
        # pushed three short items a hundred pixels apart. The ratio is relative to the line
        # height (so it follows the font), and the deck may override it.
        space_after = round(line_h * self.list_gap_ratio, 2) if gaps else 0.0
        content_h = sum(len(item_lines) for item_lines in lines) * line_h + space_after * gaps
        panel_h = 2 * pad_y + label_h + content_h
        overflow = None
        if (panel_h > box[3] + .5 or beyond_lines) and not self.preserve_terms:
            self.issues.append(issue("SPLIT_REQUIRED", "FAIL",
                                     f"{b['id']} list needs {content_h:.0f}px but the panel gives "
                                     f"{box[3] - 2 * pad_y - label_h:.0f}px", self.n, b["id"],
                                     detector="geometric-preflight", textbox_contract="deck_ir"))
            return
        if panel_h > box[3] + .5 or beyond_lines:
            overflow = {'original_bbox': [box[0] + pad_x, box[1] + pad_y + label_h,
                                          box[2] - 2 * pad_x, max(0, box[3] - 2 * pad_y - label_h)],
                        'policy': 'preserve-terms'}
            self.issues.append(issue('SCIENTIFIC_TEXT_OVERFLOW', 'REVIEW',
                f"{b['id']}: complete native list retained with its markers and wrapped scientific terms beyond the nominal slot or item-line budget.",
                self.n, b['id'], detector='geometric-preflight', original_bbox=overflow['original_bbox'],
                required_size_px=[box[2], panel_h], available_size_px=box[2:],
                suggested_actions=['increase_region_height', 'split_slide', 'review_native_render']))
        # The card hugs the list instead of stretching to the page: a panel with 150 px of
        # empty space under three rows reads as a layout mistake, not as breathing room.
        if not self.design and min_list_width == 520:
            self.elements.append({
                "id": b["id"] + ":panel", "kind": "shape", "role": "decoration",
                "bbox": [box[0], box[1], box[2], panel_h],
                "geometry": "rect", "fill": self.theme.get("panel_fill", "none"),
                "line": self.theme.get("panel_line", "#142735"), "line_width": 1,
                "collision_mode": "container",
                **({'scientific_text_overflow': {'original_bbox': list(box), 'policy': 'preserve-terms'}} if overflow else {})})
        if label:
            self.emit_text(b["id"] + ":label", label,
                           [box[0] + pad_x, box[1] + pad_y, box[2] - 2 * pad_x, label_h],
                           "heading", 28, 24, 1)
        style = {"id": b["id"], "kind": "list", "role": "body",
                 "bbox": [box[0] + pad_x, box[1] + pad_y + label_h, box[2] - 2 * pad_x, content_h],
                 "color": self.theme.get("foreground", "#142735")}
        contract = TextBoxContract(self.theme["font_family"], size, self.font_paths["font_file"],
                                   font_weight=400, font_floor=24,
                                   line_height=line_h / size,
                                   max_lines=max(len(item_lines) for item_lines in lines),
                                   vertical_anchor="top")
        current_color = b.get('bullet_color', self.bullet_color)
        if marker['native_font_fallback']:
            self.issues.append(issue('BULLET_GLYPH_REVIEW', 'REVIEW',
                'Requested native marker is unavailable in the installed fonts; inspect the fallback glyph.',
                self.n, b['id'], detector='font-resolution'))
        self.elements.append({**style, "items": lines,
                              "text": "\n".join("\v".join(item_lines) for item_lines in lines),
                              "source_text": b["text"], "contract": contract.to_dict(),
                              "bullet": {**marker,
                                         "color": current_color,
                                         "space_after": round(space_after, 2)},
                              "text_flow": flow,
                              **({'scientific_text_overflow': overflow} if overflow else {})})
        self.adaptations.append({
            "block_id": b["id"],
            "action": DISTRIBUTED_ARROW_LIST,
            "source": flow["source"],
            "item_count": len(lines),
            "bullet_style": marker['style'],
            "bullet_color": current_color,
            "bullet_glyph": marker.get('char', ''),
            "bullet_face": marker['face'],
            **({'list_start': marker['start']} if marker.get('numbering') else {}),
            "distribution": flow["distribution"],
        })

    def emit_block(self, b, box, formula_size=None, formula_align='center'):
        label = b.get("label", "")
        if b.get('component') == 'caption':
            _, lines = caption_measure({'caption': b['text']}, box[2], self.font_paths['font_file'], self.design)
            size = native_caption_size(self.design)
            self.emit_text(b['id'], b['text'], box, 'caption', size, size, max(2, lines))
            if self.elements and self.elements[-1].get('id') == b['id']:
                self.elements[-1]['caption_for'] = dict(b['caption_for'])
            return
        if b.get("component") == "formula":
            self._emit_formula_block(b, box, label, formula_size, formula_align)
            return
        if self.show_sequence:
            box = [box[0] + 56, box[1], box[2] - 56, box[3]]
        flow = select_text_flow(b["text"], b.get("text_flow", "auto"))
        if b.get('_inferred_list') and flow['source'] == 'explicit':
            flow = {**flow, 'source': 'auto'}
        if b.get('inline_math'):
            flow = {**flow, 'mode': 'plain'}
        if flow['mode'] == DISTRIBUTED_ARROW_LIST and has_markup(b['text']):
            # A native list is one run style across its items: the words stay, the emphasis
            # cannot. Report it instead of shipping a bullet with visible ** in it.
            flow = {**flow, 'items': [strip_markup(item) for item in flow['items']]}
            self.issues.append(issue('EMPHASIS_IN_LIST', 'REVIEW',
                f"{b['id']}: a native list carries one run style, so emphasis markers are set as plain text; "
                "use text_flow=plain to keep the emphasis.", self.n, b['id'], detector='geometric-preflight',
                suggested_actions=['text_flow_plain', 'drop_markers']))
        pad_x, pad_y = (0, 0) if self.design else (28, 18)
        min_list_width = list_min_width(b)
        measured_list_height = (native_list_height(
            b, max(min_list_width, box[2]), self.font_paths["font_file"], self.list_gap_ratio,
            (pad_x, pad_y), self.preserve_terms, self.bullet_style, flow=flow)
            if flow["mode"] == DISTRIBUTED_ARROW_LIST else None)
        if (flow["mode"] == DISTRIBUTED_ARROW_LIST and box[2] >= min_list_width
                and measured_list_height is not None
                and (self.preserve_terms or box[3] + .5 >= measured_list_height)):
            self._emit_list_block(b, box, label, flow, pad_x, pad_y, min_list_width)
            return
        if flow["mode"] == DISTRIBUTED_ARROW_LIST:
            if flow['source'] == 'explicit':
                required_height = round(measured_list_height, 1)
                self.issues.append(issue('SPLIT_REQUIRED', 'FAIL',
                    f"{b['id']}: explicit native list requires at least {min_list_width} px width and its measured content height; markers were not removed.",
                    self.n, b['id'], detector='geometric-preflight', required_size_px=[min_list_width, required_height],
                    available_size_px=box[2:], suggested_actions=['widen_region', 'increase_region_height', 'split_slide']))
                return
            self.adaptations.append({
                "block_id": b["id"],
                "action": "text_flow_fallback",
                "requested": DISTRIBUTED_ARROW_LIST,
                "reason": "component_box_below_measured_minimum",
            })
            self.issues.append(issue("TEXT_FLOW_FALLBACK", "INFO",
                                     f"{b['id']} kept plain because its component box is narrower than 520 px or shorter than the measured list content",
                                     self.n, b["id"], detector="geometric-preflight"))
        label_h = (40 if self.comp["archetype"] == "figure-parameters" else 44) if label else 0
        self.emit_text(b["id"] + ":label", label, [box[0], box[1], box[2], label_h], "heading", 28, 24, 1)
        emphasis_color = self.theme.get("accent", DEFAULT_ACCENT) if b["id"] == self.visual_intent.get("emphasis") else None
        from .type_scale import display_floor, display_size
        size, floor = display_size(b, self.design), display_floor(b, self.design)
        if size:
            # A promoted object is the page's anchor: display role keeps its own floor instead
            # of being capped by the body size the rest of the page uses.
            self.emit_text(b["id"], b["text"], [box[0], box[1] + label_h, box[2], box[3] - label_h], "display",
                           size, floor, 2, color=emphasis_color, inline_math=b.get('inline_math', False))
        else:
            self.emit_text(b["id"], b["text"], [box[0], box[1] + label_h, box[2], box[3] - label_h],
                           color=emphasis_color, inline_math=b.get('inline_math', False))

    def emit_formula_flow(self, bs, box, max_columns=1, preferred_columns=1):
        try:
            plan = plan_formula_flow(bs, box, self.font_paths, self.comp['archetype'],
                max_columns=max_columns, preferred_columns=preferred_columns,
                body_size=type_sizes(self.design)['body'] if self.design else 28,
                text_inset=56 if self.show_sequence else 0, preserve_terms=self.preserve_terms,
                list_gap_ratio=self.list_gap_ratio, list_padding=(0, 0) if self.design else (28, 18),
                bullet_style=self.bullet_style,
                gap=24 if self.comp['archetype'] == 'figure-parameters' else 18)
        except FormulaCapacityError as error:
            self.issues.append(issue('FORMULA_CAPACITY', 'FAIL', str(error), self.n,
                detector='geometric-preflight', confidence='HIGH',
                suggested_fix='widen_text_column_or_split_slide', attempts=error.attempts,
                available_width_px=box[2], available_height_px=box[3]))
            return
        by_id = {b['id']: b for b in bs}
        heights = plan.get('column_heights_px') or []
        if heights:
            offset = max(0.0, box[3] - max(heights)) / 2
            if offset > .5:
                for item in plan['boxes'].values():
                    item[1] += offset
                plan['vertical_offset_px'] = round(offset, 2)
        for bid in plan['reading_order']:
            self.emit_block(by_id[bid], plan['boxes'][bid], plan['font_size_px'], 'left')
        self.adaptations.append({'action': 'formula_flow', 'region': list(box), **plan})

    def emit_stack(self, bs, box):
        if not bs:
            return
        if any(b.get('component') == 'formula' or b.get('inline_math') for b in bs):
            self.emit_formula_flow(bs, box)
            return
        from .academic_layout import block_height
        gap = 24 if self.comp['archetype'] == 'figure-parameters' else 18
        needs = [block_height(b, box[2], self.font_paths, self.comp['archetype'], design=self.design,
                              list_gap_ratio=self.list_gap_ratio, bullet_style=self.bullet_style) for b in bs]
        total = sum(needs) + gap * (len(bs) - 1)
        extra = max(0.0, box[3] - total)
        # Keep the content block at the top, share the remaining height as
        # breathing room above, between and below the blocks. This is the
        # same measured content, never a stretched text box.
        top_pad = extra / 3
        gap_extra = (extra - 2 * top_pad) / max(1, len(bs) - 1)
        cursor = box[1] + top_pad
        for b, need in zip(bs, needs):
            self.emit_block(b, [box[0], cursor, box[2], need])
            cursor += need + gap + gap_extra

    def emit_figure(self, f, box, k, caption_top=None):
        asset = self.assets[f["asset_id"]]
        schematic = (asset.get("origin") or "paper") == "generated"
        reference = asset.get("origin") == "reference"
        content = caption_with_source(f)
        caption_h, caption_lines = caption_measure(f, box[2], self.font_paths["font_file"])
        if f.get("caption_height") and content:
            # An explicit height still wins; it was measured by its author.
            caption_h = f["caption_height"]
            caption_lines = max(2, int(round((caption_h - 8) / (f.get("caption_font_size", 22) * 1.25))))
        h = box[3] - caption_h - 12
        if caption_top is not None:
            h = min(h, caption_top - 12 - box[1])
        scale = min(box[2] / asset["width"], h / asset["height"])
        w, h = asset["width"] * scale, asset["height"] * scale
        bbox = [box[0] + (box[2] - w) / 2, box[1], w, h]
        if caption_top is not None:
            bbox[1] = caption_top - 12 - h
        eid = f"figure-{k}"
        min_extent = f.get("min_panel_extent", 220)
        actual_extent = min(w / f.get("panel_count", 1), h)
        highlights = f.get("highlights") if isinstance(f.get("highlights"), list) else []
        element = {"id": eid, "kind": "image", "role": "reference" if reference else "evidence", "bbox": bbox,
                   "asset_id": f["asset_id"], "alt": f.get("alt", f["caption"]),
                   "min_panel_extent": min_extent,
                   "actual_panel_extent": actual_extent,
                   **({"overlap_group": eid} if highlights else {})}
        if schematic:
            element["schematic"] = {"generator": asset.get("generator")}
        elif reference:
            element.update(origin="reference", reference_source=asset["reference_source"])
        else:
            element["source_figure"] = f["source_figure"]
        self.elements.append(element)
        if highlights:
            default_hl_color = self.theme.get("accent", DEFAULT_ACCENT)
            badge_face = ImageFont.truetype(self.font_paths["bold_font_file"], 20)
            for h_idx, hl in enumerate(highlights, 1):
                rx, ry, rw, rh = hl["box"]
                hx = bbox[0] + rx * bbox[2]
                hy = bbox[1] + ry * bbox[3]
                hw = max(8.0, min(bbox[0] + bbox[2] - hx, rw * bbox[2]))
                hh = max(8.0, min(bbox[1] + bbox[3] - hy, rh * bbox[3]))
                hl_color = hl.get("color") or default_hl_color
                self.elements.append({
                    "id": f"{eid}:highlight:{h_idx}",
                    "kind": "shape",
                    "role": "decoration",
                    "bbox": [hx, hy, hw, hh],
                    "geometry": "rect",
                    "fill": "none",
                    "line": hl_color,
                    "line_width": 2.5,
                    "visual_decoration": True,
                    "overlap_group": eid,
                })
                hl_label = str(hl.get("label") or "").strip()
                if hl_label:
                    lbl_w = min(bbox[2] - 4.0, max(36.0, badge_face.getlength(hl_label) + 16.0))
                    lbl_h = 26.0
                    lbl_x = min(max(bbox[0] + 2.0, hx), bbox[0] + bbox[2] - lbl_w - 2.0)
                    lbl_y = hy - lbl_h - 2.0 if hy - lbl_h - 2.0 >= bbox[1] + 2.0 else min(
                        hy + 2.0, bbox[1] + bbox[3] - lbl_h - 2.0)
                    badge_box = [lbl_x, lbl_y, lbl_w, lbl_h]
                    self.elements.append({
                        "id": f"{eid}:highlight-badge:{h_idx}",
                        "kind": "shape",
                        "role": "decoration",
                        "bbox": badge_box,
                        "geometry": "roundRect",
                        "fill": hl_color,
                        "line": "none",
                        "visual_decoration": True,
                        "overlap_group": eid,
                    })
                    self.emit_text(f"{eid}:highlight-label:{h_idx}", hl_label, badge_box,
                                   "badge", 20, 20, 1, "middle", "#FFFFFF")
                    if self.elements and self.elements[-1]["id"] == f"{eid}:highlight-label:{h_idx}":
                        self.elements[-1]["overlap_group"] = eid
        if actual_extent < min_extent:
            if schematic:
                self.issues.append(issue("SCHEMATIC_TOO_SMALL", "FAIL",
                                         f"Schematic extent {actual_extent:.1f}px is below {min_extent}px",
                                         self.n, eid, detector="geometric-preflight", confidence="HIGH"))
            elif reference:
                self.issues.append(issue("REFERENCE_IMAGE_TOO_SMALL", "FAIL",
                                         f"Reference image extent {actual_extent:.1f}px is below {min_extent}px",
                                         self.n, eid, detector="geometric-preflight", confidence="HIGH",
                                         reference_source=asset["reference_source"]))
            else:
                self.issues.append(issue("SCIENTIFIC_PANEL_TOO_SMALL", "FAIL",
                                         f"Scientific panel extent {actual_extent:.1f}px is below {min_extent}px",
                                         self.n, eid, detector="geometric-preflight", confidence="HIGH",
                                         source_figure=f["source_figure"]))
        caption_y = bbox[1] + bbox[3] + 12
        if self.design and content and self.design['figure_treatment'] == 'ruled-caption':
            self.elements.append(rule(eid + ':caption-rule', [box[0], caption_y - 6, box[2], 1], self.design))
        # A real paper caption is often three or four lines; the strip was measured for exactly
        # that many lines, so the emitter must not clamp it back to two.
        self.emit_text(eid + ":caption", content, [box[0], caption_y, box[2], caption_h],
                       "caption", f.get("caption_font_size", 22), f.get("caption_font_floor", 20),
                       max(2, caption_lines))
        if schematic:
            self.issues.append(issue("SCHEMATIC_REVIEW", "REVIEW",
                                     "Confirm the drawn schematic matches the text it illustrates; "
                                     "it is not a paper figure",
                                     self.n, eid, detector="scientific-review", confidence="MEDIUM"))
        elif reference:
            self.issues.append(issue("REFERENCE_IMAGE_REVIEW", "REVIEW",
                                     "Confirm the crop and readability against its user-provided source; "
                                     "this image is not independently verified scientific evidence",
                                     self.n, eid, detector="source-review", confidence="MEDIUM",
                                     reference_source=asset["reference_source"]))
        else:
            self.issues.append(issue("SCIENTIFIC_PANEL_REVIEW", "REVIEW",
                                     "Confirm scientific panel labels and evidence fidelity",
                                     self.n, eid, detector="scientific-review", confidence="MEDIUM"))

    def emit_schematic_band(self, bs, f):
        face = ImageFont.truetype(self.font_paths["font_file"], 28)
        if len(bs) == 2:
            # Two short paragraphs read as one line each of context: side by side they leave the
            # height to the diagram instead of stacking into a wall above it.
            rows = [break_lines(item["text"], face, 568) for item in bs]
            band = max((len(lines) for lines in rows), default=0) * 35
            for k, (item, _) in enumerate(zip(bs, rows)):
                self.emit_block(item, [56 + k * 600, self.top, 568, band])
            cursor = self.top + band + 18
        else:
            rows = [break_lines(item["text"], face, 1168) for item in bs]
            natural = sum(len(lines) for lines in rows) * 35 + 18 * max(len(bs) - 1, 0)
            band = min(natural, self.bh * .45)
            cursor = self.top
            total = max(sum(len(lines) for lines in rows), 1)
            for item, lines in zip(bs, rows):
                height = band * len(lines) / total
                self.emit_block(item, [56, cursor, 1168, height])
                cursor += height + 18
        self.emit_figure(f, [56, cursor, 1168, self.bottom - cursor], 1)

    def emit_native_graphic(self, region, graphic=None):
        graphic = graphic or self.comp["graphics"][0]
        try:
            graphic_elements = compile_graphic(graphic, region, self.theme, self.font_paths)
        except ValueError as error:
            graphic_elements = []
            self.issues.append(issue(getattr(error, "rule", "GRAPHIC_CAPACITY"), "FAIL", str(error), self.n, graphic["id"],
                                     detector="geometric-preflight"))
        for element in graphic_elements:
            if element["kind"] in ("shape", "connector"):
                self.elements.append(element)
                continue
            before = len(self.elements)
            self.emit_text(element["id"], element["text"], element["bbox"], element["role"],
                           element["font_size"], min(24, element["font_size"]), element["max_lines"], "middle",
                           element["color"], align="center")
            if len(self.elements) > before:
                self.elements[-1].update({key: element[key] for key in
                    ("graphic_id", "node_id", "container_id", "overlap_group", "graphic_region", "edge_id")
                    if key in element})
        node_count, edge_count = graphic_counts(graphic)
        self.adaptations.append({"action": "native_graphic", "graphic_id": graphic["id"],
                                 "region": region, "node_count": node_count,
                                 "edge_count": edge_count})
        self.issues.append(issue("SCHEMATIC_REVIEW", "REVIEW",
                                 ("Confirm the process order and labels match the scientific explanation; "
                                  "this is a generated schematic, not a paper figure")
                                 if graphic['type'] in ('process', 'dag') else
                                 "Confirm component labels, explicit relationships and evidence/hypothesis distinctions; "
                                 "generated graphics do not establish scientific correctness",
                                 self.n, graphic["id"], detector="scientific-review", confidence="MEDIUM"))

    def _checkpoints(self):
        return [len(values) for values in (self.elements, self.issues, self.adaptations, self.slide_formulas)]

    def _rollback(self, checkpoints):
        for values, checkpoint in zip((self.elements, self.issues, self.adaptations, self.slide_formulas), checkpoints):
            del values[checkpoint:]

    def _emit_tree_node(self, entry, by_id, annotated_formulas, graphics_by_id, charts_by_id):
        from .container_frames import rectangle, stroke_width
        from .layout_tree import LayoutTreeError
        first = len(self.elements)
        if entry['type'] == 'panel':
            title_id = 'region:' + entry['node_id'] + ':title'
            style = entry.get('frame')
            if style and (style.get('border') or style.get('fill', 'none') != 'none'):
                self.elements.append(rectangle('region:' + entry['node_id'] + ':frame', entry['bbox'], style, []))
            if style and style.get('title_fill', 'none') != 'none':
                self.elements.append({'id': 'region:' + entry['node_id'] + ':title-band', 'kind': 'shape',
                    'role': 'decoration', 'bbox': entry['title_band_bbox'],
                    'geometry': entry.get('title_band_geometry', 'rect'),
                    'fill': style['title_fill'], 'line': 'none', 'line_width': 0,
                    'visual_decoration': True, 'frame_members': [title_id],
                    'frame_growth_inset': stroke_width(style)})
            self.emit_text('region:' + entry['node_id'] + ':title', entry['title'], entry['title_bbox'],
                           'heading', 28, 24, max(2, int(entry['title_bbox'][3] / 30)),
                           anchor='middle' if entry.get('title_band_geometry') == 'roundRect' else 'top',
                           color=style.get('title_color') if style else None,
                           align=entry.get('title_align') or (style.get('title_align') if style else None))
        elif entry['type'] == 'block':
            source = by_id[entry['ref']]
            self.emit_block(source, entry['bbox'],
                            formula_align='center' if source['id'] in annotated_formulas else 'left')
            if source.get('text_for'):
                for element in self.elements[first:]:
                    if element['id'] == source['id']:
                        element['text_for'] = dict(source['text_for'])
        elif entry['type'] == 'figure':
            self.emit_figure(self.figs[entry['ref']], entry['bbox'], entry['ref'] + 1)
        elif entry['type'] == 'graphic':
            self.emit_native_graphic(entry['bbox'], graphics_by_id[entry['ref']])
        elif entry['type'] == 'chart':
            from .chart_render import ChartLayoutError, compile_chart
            chart = charts_by_id[entry['ref']]
            try:
                rendered = compile_chart(chart, entry['bbox'], self.theme, self.font_paths)
            except ChartLayoutError as error:
                self.issues.append(issue(error.rule, 'FAIL', str(error), self.n, chart['id'],
                                         detector='geometric-preflight', component=entry['component']))
                return None
            for element in rendered:
                if element['kind'] in ('shape', 'connector'):
                    self.elements.append(element)
                else:
                    before = len(self.elements)
                    self.emit_text(element['id'], element['text'], element['bbox'], element['role'],
                                   element['font_size'],
                                   20 if element['role'] == 'caption' else 24,
                                   element['max_lines'], 'middle', element['color'],
                                   align=element.get('align'))
                    if len(self.elements) > before:
                        self.elements[-1].update({key: element[key] for key in
                            ('graphic_id', 'overlap_group', 'node_id') if key in element})
            self.issues.append(issue(
                'CHART_DATA_REVIEW' if chart.get('basis') == 'evidence' else 'CHART_ILLUSTRATIVE_REVIEW',
                'REVIEW',
                'Confirm every plotted point against the cited evidence; the compiler checked '
                'the chart structure, not the paper text.' if chart.get('basis') == 'evidence'
                else 'This chart is an illustrative schematic, not measured data; confirm the '
                     '示意 badge is visible in the rendered slide.',
                self.n, chart['id'], detector='scientific-review', confidence='MEDIUM'))
        elif entry['type'] == 'table':
            from .native_table import compile_table
            table = next(t for t in self.comp['tables'] if t['id'] == entry['ref'])
            try:
                rendered = compile_table(table, entry['bbox'], self.font_paths, self.theme, self.preserve_terms)
            except LayoutTreeError as error:
                error.detail['component'] = entry['component']
                raise
            self.elements.append(rendered)
            self.issues.append(issue('TABLE_CONTENT_REVIEW', 'REVIEW',
                'Confirm every table value, scientific term, unit and source reference.', self.n, rendered['id'],
                detector='scientific-review', confidence='MEDIUM'))
            if any(c.get('measured_exact') is False for c in rendered['cells']):
                self.issues.append(issue('FORMULA_MEASURE_APPROXIMATE', 'REVIEW',
                    'Native table formulas use conservative structural metrics; verify cell bounds in PowerPoint.',
                    self.n, rendered['id'], detector='geometric-preflight', confidence='LOW', font_metrics='heuristic'))
            if any(c.get('inline_formula_count', 0) for c in rendered['cells']):
                self.issues.append(issue('INLINE_MATH_MEASUREMENT_REVIEW', 'REVIEW',
                    'Verify inline formula baselines and measured line heights in native table cells.',
                    self.n, rendered['id'], detector='geometric-preflight', confidence='LOW'))
            if rendered.get('scientific_text_overflow'):
                self.issues.append(issue('SCIENTIFIC_TEXT_OVERFLOW', 'REVIEW',
                    'Native table retains complete scientific terminology beyond its nominal region.',
                    self.n, rendered['id'], detector='geometric-preflight'))
        return first

    def compile_layout_tree(self):
        from .layout_tree import LayoutTreeError, attachment_link, compile_regions
        from .container_frames import grow_frame, stroke_width
        checkpoints = self._checkpoints()
        try:
            plan = compile_regions(self.comp, [56, self.top, 1168, self.bh], self.assets, self.font_paths,
                                   self.theme, self.preserve_terms, self.list_gap_ratio,
                                   (0, 0) if self.design else (28, 18), self.bullet_style,
                                   design=self.design,
                                   formula_sizes=self.formula_sizes if self.equation_page else None)
            balance_shift = (plan.get('balanced') or {}).get('shift_px', 0.)
            if balance_shift > .5:
                self.adaptations.append({'action': 'vertical_balance', **plan['balanced']})
            if plan.get('elastic_micro_fit'):
                emf = plan['elastic_micro_fit']
                self.adaptations.append({'action': 'elastic_micro_fit', **emf})
                self.issues.append(issue(
                    'ELASTIC_MICRO_FIT', 'INFO',
                    f"Tightened container spacing by {emf['saved_px']} px ({', '.join(emf['adjustments'][:3])}) without altering font sizes.",
                    self.n, detector='geometric-preflight', slide_id=self.slide['id']))
            by_id = {b['id']: b for b in self.blocks}
            annotated_formulas = {link['ref'] for b in self.blocks if (link := attachment_link(b))
                                  and link['kind'] == 'formula' and 'position' in link}
            graphics_by_id = {g['id']: g for g in self.comp.get('graphics', [])}
            charts_by_id = {c['id']: c for c in self.comp.get('charts', [])}
            for entry in plan['nodes']:
                issue_start = len(self.issues)
                first = self._emit_tree_node(entry, by_id, annotated_formulas, graphics_by_id, charts_by_id)
                if first is None:
                    continue
                for element in self.elements[first:]:
                    element.update(layout_component=entry['component'], layout_region=entry['bbox'])
                    ex, ey, ew, eh = element['bbox']
                    rx, ry, rw, rh = entry['bbox']
                    # Sub-pixel rounding is not a layout decision: a preserve-terms block whose
                    # region came out of a ratio split can be 0.7 px shorter than the line grid.
                    # Clamp that residue so "an element never leaves its assigned region" stays
                    # true; anything larger is still reported as a real overflow below.
                    if eh > rh and eh - rh < 1.0:
                        element['bbox'][3] = rh
                        eh = rh
                    if ew > rw and ew - rw < 1.0:
                        element['bbox'][2] = rw
                        ew = rw
                    if (not element.get('scientific_text_overflow') and
                        (ex < rx - .1 or ey < ry - .1 or ex + ew > rx + rw + .1 or ey + eh > ry + rh + .1)):
                        self.issues.append(issue('REGION_CONTENT_OUT_OF_BOUNDS', 'FAIL',
                            'Rendered component exceeds its assigned compiler region.', self.n, element['id'],
                            detector='geometric-preflight', component=entry['component']))
                failures = [item for item in self.issues[issue_start:] if item['severity'] == 'FAIL']
                if failures:
                    raise LayoutTreeError(entry['component'], 'COMPONENT_RENDER_FAILED',
                        'A component failed an existing renderer gate after region allocation.',
                        [entry['bbox'][2], entry['requirements']['min_height_px']], entry['bbox'][2:],
                        cause=failures[0]['message'])
            # Grow opted-in frames bottom-up when preserve-terms releases complete text.
            # Each frame only exempts its own descendants from overlap checks.
            for entry in reversed(plan['nodes']):
                if not entry.get('frame'):
                    continue
                prefix, eid = entry['component'], 'region:' + entry['node_id']
                framed = next((e for e in self.elements if e['id'] == eid + ':frame'), None)
                title_element = next(e for e in self.elements if e['id'] == eid + ':title')
                band = next((e for e in self.elements if e['id'] == eid + ':title-band'), None)
                # A chip is a label around its text, not a row that can absorb extra height:
                # growing it would stretch the pill, so a chip keeps its measured size.
                if band and not entry.get('title_band_geometry'):
                    needed = title_element['bbox'][1] + title_element['bbox'][3] + entry['padding_px'] - band['bbox'][1]
                    if needed > band['bbox'][3] + .1:
                        band['bbox'] = [*band['bbox'][:3], needed]
                        band['scientific_text_overflow'] = {'policy': 'preserve-terms'}
                if framed is None:
                    continue
                members = [e for e in self.elements if e is not framed and
                           (e.get('layout_component') == prefix or e.get('layout_component', '').startswith(prefix + '.'))]
                framed['frame_members'] = [e['id'] for e in members]
                outer = grow_frame(framed, entry['bbox'], members,
                                   entry['padding_px'] + stroke_width(entry['frame']))
                entry['frame_bbox'] = outer
                framed['layout_region'] = outer
                if framed.get('scientific_text_overflow'):
                    self.issues.append(issue('FRAME_EXPANDED_FOR_TERMS', 'REVIEW',
                        'Native frame expanded with complete scientific content; inspect neighbouring regions.',
                        self.n, framed['id'], detector='geometric-preflight', component=prefix,
                        original_bbox=entry['bbox'], expanded_bbox=outer))
            self.adaptations.append({'action': 'layout_tree', **plan})
            for entry in plan['nodes']:
                if (entry.get('underfill') and
                        balance_shift < entry['underfill']['underfill_px'] * .5):
                    # The balance nudge is capped at 32 px; a 300 px gap is not explained by it.
                    # Suppress the report only when the shift actually absorbed most of the gap.
                    self.issues.append(issue('PAGE_UNDERFILL', 'REVIEW',
                        'A stack leaves more than 15% of its allocated height unused. '
                        'Review intentional whitespace or adjust relative weights / stack alignment.',
                        self.n, 'region:' + entry['node_id'], detector='geometric-preflight',
                        component=entry['component'], **entry['underfill']))
                if sparse_text_page(entry, self.elements):
                    filled = entry['requirements']['preferred_height_px'] / entry['bbox'][3]
                    # A stack of one-line statements in a half-empty region is the
                    # document look: the page has structure but no composition.
                    self.issues.append(issue('SPARSE_TEXT_PAGE', 'REVIEW',
                        f'The text on this page fills {filled * 100:.0f}% of its region. Short '
                        'statements stacked in one column read as a document; give the page a '
                        'composition — two columns, one display-size statement, or numbered '
                        'points — or split it.', self.n, 'region:' + entry['node_id'],
                        detector='geometric-preflight', filled_ratio=round(filled, 3),
                        suggested_actions=['text_columns', 'statement', 'numbered_points', 'split_slide']))
            self.adaptations.append({'action': 'layout_provider', 'provider': 'compiler',
                                     'status': 'COMPILER_OWNED', 'reason': 'recursive_regions'})
        except LayoutTreeError as error:
            self._rollback(checkpoints)
            self.issues.append(issue(error.detail['code'], 'FAIL', str(error), self.n,
                detector='geometric-preflight', slide_id=self.slide['id'],
                **{key: value for key, value in error.detail.items() if key not in ('code', 'message')}))

    def compile_visual_plan(self):
        from .academic_layout import candidates
        best_failures, attempts = [], []
        for plan in candidates(self.slide, [56, self.top, 1168, self.bh], self.assets, self.font_paths, self.design,
                               list_gap_ratio=self.list_gap_ratio, bullet_style=self.bullet_style):
            boxes = [*plan['blocks'], *plan['figures']]
            boxes += [plan[key] for key in ('graphic', 'emphasis') if plan.get(key) is not None]
            if any(min(box[2:]) <= 0 for box in boxes):
                attempts.append({'pattern': plan['pattern'], 'rules': ['INVALID_REGION']})
                continue
            checkpoints = self._checkpoints()
            for b, box in zip(self.blocks, plan['blocks']):
                self.emit_block(b, box)
            for k, (f, box) in enumerate(zip(self.figs, plan['figures']), 1):
                self.emit_figure(f, box, k, plan.get('caption_top'))
            if plan.get('graphic'):
                self.emit_native_graphic(plan['graphic'])
            if plan.get('emphasis'):
                self.emit_text('visual:emphasis', self.visual_plan['emphasis']['text'], plan['emphasis'],
                               'body', 28, 24, 3, color=self.theme['accent'])
            failures = [finding for finding in self.issues[checkpoints[1]:] if finding['severity'] == 'FAIL']
            failures += geometry_issues(self.elements, self.n)
            if len({e['id'] for e in self.elements}) != len(self.elements):
                failures.append(issue('VISUAL_PLAN_ID_COLLISION', 'FAIL',
                    'Page object names must be unique', self.n, detector='geometric-preflight'))
            failures += [finding for finding in self.issues[:checkpoints[1]]
                         if finding['severity'] == 'FAIL' and finding.get('slide') == self.n]
            attempts.append({'pattern': plan['pattern'], 'rules': sorted({i['rule'] for i in failures})})
            if not failures:
                self.adaptations.append({'action': 'scientific_visual_plan', 'visual_job': self.visual_plan['visual_job'],
                    'requested': self.visual_plan, 'selected': plan, 'attempts': attempts})
                self.adaptations.append({'action': 'layout_provider', 'provider': 'compiler',
                                         'status': 'COMPILER_FALLBACK', 'reason': 'scientific_visual_plan'})
                break
            if not best_failures or len(failures) < len(best_failures):
                best_failures = failures
            self._rollback(checkpoints)
        else:
            self.issues.extend(best_failures)
            self.issues.append(issue('VISUAL_PLAN_UNSATISFIABLE', 'FAIL',
                'No candidate satisfies the visual plan and existing content, panel, typography and collision gates. Replan this page.',
                self.n, detector='geometric-preflight', attempted_compositions=attempts))

    def compile_graphic_composition(self):
        # Try a small set of whole-page compositions using the existing emitters. Failed
        # attempts never leak partial content, warnings or text adaptations into the result.
        best_failures, attempted = [], 0
        for plan in graphic_page_regions(self.comp, [56, self.top, 1168, self.bh], self.assets, self.font_paths,
                design=self.design, list_gap_ratio=self.list_gap_ratio,
                list_padding=(0, 0) if self.design else (28, 18), bullet_style=self.bullet_style):
            boxes = [plan['graphic'], *plan['blocks'], *plan['figures']]
            if any(min(box[2:]) <= 0 for box in boxes):
                continue
            attempted += 1
            checkpoints = self._checkpoints()
            for b, box in zip(self.blocks, plan['blocks']):
                self.emit_block(b, box)
            for k, (f, box) in enumerate(zip(self.figs, plan['figures']), 1):
                self.emit_figure(f, box, k)
            self.emit_native_graphic(plan['graphic'])
            failures = [finding for finding in self.issues[checkpoints[1]:] if finding['severity'] == 'FAIL']
            if not failures:
                self.adaptations.append({'action': 'graphic_composition', 'pattern': plan['pattern'],
                                         'block_ids': [b['id'] for b in self.blocks],
                                         'figure_ids': [f'figure-{k + 1}' for k in range(len(self.figs))],
                                         'graphic_id': self.comp['graphics'][0]['id']})
                self.adaptations.append({'action': 'layout_provider', 'provider': 'compiler',
                                         'status': 'COMPILER_FALLBACK', 'reason': 'native_graphic_composition'})
                break
            if not best_failures or len(failures) < len(best_failures):
                best_failures = failures
            self._rollback(checkpoints)
        else:
            self.issues.extend(best_failures)
            self.issues.append(issue('GRAPHIC_PAGE_CAPACITY', 'FAIL',
                'The graphic, context and source figure/caption cannot share this page above '
                'their size floors. Try composite-research with a vertical layout_tree stack '
                '(graphic + blocks) before splitting; if the measured tree still cannot fit, '
                'split the page. No content was shortened or dropped.',
                self.n, self.comp['graphics'][0]['id'], detector='geometric-preflight',
                attempted_compositions=attempted))
            self.issues.append(issue('SCHEMATIC_REVIEW', 'REVIEW',
                'Confirm the declared graphic relationships match the scientific evidence.',
                self.n, self.comp['graphics'][0]['id'], detector='scientific-review', confidence='MEDIUM'))

    def compile_body(self, proposals):
        # A drawn schematic is not evidence that has to sit beside its text: it gets the width of
        # the page and the reader's eye goes text -> diagram -> caption, top to bottom.
        schematic_only = (len(self.figs) == 1 and
                          (self.assets[self.figs[0]["asset_id"]].get("origin") or "paper") == "generated")
        has_formulas = any(b.get('component') == 'formula' or b.get('inline_math') for b in self.blocks)
        proposal = None if (self.comp.get('layout_tree') or self.visual_plan or schematic_only
                            or self.comp.get('graphics') or has_formulas) else (proposals or {}).get(self.slide['id'])
        if self.comp.get('layout_tree'):
            self.compile_layout_tree()
        elif self.visual_plan:
            self.compile_visual_plan()
        elif self.family == "graphic":
            self.emit_native_graphic([56, self.top, 1168, self.bh])
        elif self.comp.get('graphics'):
            self.compile_graphic_composition()
        elif proposal:
            supplied = proposal['units']
            expected = [b['id'] for b in self.blocks] + [f'figure-{k + 1}' for k in range(len(self.figs))]
            if len(expected) != len(set(expected)) or set(supplied) != set(expected):
                raise ValueError('Provider unit identities must match the canonical slide exactly')
            if self.family == 'evidence':
                for col, role in enumerate(('direct-evidence', 'hypothesis')):
                    self.emit_text(role + ':heading', '直接证据' if col == 0 else '假设（未证实）',
                                   [56 + col * 600, self.top, 568, 44], 'heading', 28, 24, 1)
            for b in self.blocks:
                self.emit_block(b, supplied[b['id']]['bbox'])
            for k, f in enumerate(self.figs, 1):
                group = supplied[f'figure-{k}']
                declared = group.get('caption_height', f.get('caption_height'))
                self.emit_figure({**f, **({'caption_height': declared} if declared else {})},
                                 group['bbox'], k)
            self.adaptations.append({'action': 'layout_provider',
                                     'provider': proposal.get('provider', 'provider'),
                                     'status': proposal['status']})
        elif schematic_only:
            self.emit_schematic_band(self.blocks, self.figs[0])
        elif not self.figs and not self.show_sequence and self.family != 'evidence' and (has_formulas or self.family == 'equations'):
            self.emit_formula_flow(self.blocks, [56, self.top, 1168, self.bh], max_columns=2,
                                   preferred_columns=2 if self.comp['archetype'] == 'metric-comparison' else 1)
        elif self.family in ("figure-left", "figure-right") and self.figs:
            base_text = 440 if self.family == "figure-left" else 460
            txt_w = formula_column_width(self.blocks, self.font_paths["bold_font_file"], base_text, 616)
            fig_w = 1168 - 32 - txt_w
            if self.family == "figure-left":
                fig_x, txt_x = 56, 56 + fig_w + 32
            else:
                txt_x, fig_x = 56, 56 + txt_w + 32
            self.emit_figure(self.figs[0], [fig_x, self.top, fig_w, self.bh], 1)
            self.emit_stack(self.blocks, [txt_x, self.top, txt_w, self.bh])
        elif self.show_sequence and not self.figs:
            self.emit_stack(self.blocks, [280, self.top, 720, self.bh])
        elif self.family == "process" and self.figs and len(self.blocks) >= 4:
            # The method slide needs both a legible process summary and a readable
            # source panel. A four-row left column frees the right half for the
            # original Fig.3a panel instead of squeezing it into a shallow strip.
            left_x, left_w = 56, 520
            row_h, row_gap = 75, 5
            for k, b in enumerate(self.blocks[:4]):
                y = self.top + k * (row_h + row_gap)
                self.emit_text(b["id"] + ":label", b.get("label", ""), [left_x, y, left_w, 32], "heading", 24, 24, 1)
                self.emit_text(b["id"], b["text"], [left_x, y + 32, left_w, row_h - 32], "body", 24, 24, 1)
            self.emit_figure(self.figs[0], [650, self.top, 574, self.bh], 1)
        elif self.slide["id"] == "s07-contact" and self.figs:
            # Keep the two numeric callouts compact so the two original Fig.3e/f
            # panels can occupy most of the evidence area at readable size.
            for k, b in enumerate(self.blocks[:2]):
                x = 56 + k * 600
                self.emit_text(b["id"] + ":label", b.get("label", ""), [x, self.top, 568, 32], "heading", 24, 24, 1)
                self.emit_text(b["id"], b["text"], [x, self.top + 32, 568, 38], "body", 26, 22, 1)
            fw = (1168 - 32 * (len(self.figs) - 1)) / len(self.figs)
            for k, f in enumerate(self.figs):
                self.emit_figure(f, [56 + k * (fw + 32), self.top + 70, fw, self.bottom - (self.top + 70)], k + 1)
        elif self.family == "dual" and self.figs:
            # Dual scientific figures get compact native callouts and a hard
            # 240px evidence band. This avoids the former 154px thumbnails.
            for k, b in enumerate(self.blocks[:2]):
                x = 56 + k * 600
                self.emit_text(b["id"] + ":label", b.get("label", ""), [x, self.top, 568, 30], "heading", 24, 24, 1)
                self.emit_text(b["id"], b["text"], [x, self.top + 30, 568, 34], "body", 24, 24, 1)
            fw = (1168 - 32 * (len(self.figs) - 1)) / len(self.figs)
            for k, f in enumerate(self.figs):
                self.emit_figure(f, [56 + k * (fw + 32), self.top + 70, fw, self.bottom - (self.top + 70)], k + 1)
        elif self.family == "evidence":
            for col, role in enumerate(("direct-evidence", "hypothesis")):
                x = 56 + col * 600
                self.emit_text(role + ":heading", "直接证据" if col == 0 else "假设（未证实）",
                               [x, self.top, 568, 44], "heading", 28, 24, 1)
                self.emit_stack([b for b in self.blocks if b["component"] == role], [x, self.top + 56, 568, self.bh - 56])
        elif self.blocks:
            w = (1168 - 32 * (len(self.blocks) - 1)) / len(self.blocks)
            column_start = len(self.elements)
            for k, b in enumerate(self.blocks):
                self.emit_block(b, [56 + k * (w + 32), self.top, w, self.bh])
            # Flat columns otherwise pin every label to the body top and
            # leave the lower band empty. Centre the measured content in
            # the body band without enlarging or re-wrapping it.
            if len(self.blocks) > 1 and not self.figs and not self.comp.get('graphics') and not self.show_sequence:
                created = self.elements[column_start:]
                visible = [e for e in created if e['kind'] in ('text', 'list', 'math')
                           and e['role'] in ('heading', 'body', 'formula')]
                if visible:
                    content_top = min(e['bbox'][1] for e in visible)
                    content_bottom = max((e['bbox'][1] + e['bbox'][3] if e['kind'] == 'math'
                                          else text_visible_bottom(e)) for e in visible)
                    empty = self.bh - (content_bottom - content_top)
                    if empty > 60:
                        shift = empty / 2
                        limit = self.top + self.bh
                        for e in created:
                            e['bbox'][1] += shift
                            e['bbox'][3] = max(1, min(e['bbox'][3], limit - e['bbox'][1]))
        if self.show_sequence:
            rows = [next((e for e in self.elements if e["id"] == b["id"]), None) for b in self.blocks]
            if all(rows):
                rail_x = rows[0]["bbox"][0] - 56
                centers = [row["bbox"][1] + 18 for row in rows]
                accent = self.theme.get("accent", DEFAULT_ACCENT)
                self.elements.append({"id": "sequence:spine", "kind": "shape",
                    "role": "decoration", "bbox": [rail_x + 25, centers[0], 2, centers[-1] - centers[0]],
                    "geometry": "rect", "fill": "#B9CCD8", "line": "none",
                    "collision_mode": "container"})
                for index, row in enumerate(rows, 1):
                    badge = [rail_x + 10, row["bbox"][1] + 2, 32, 32]
                    self.elements.append({"id": f"sequence:step:{index}", "kind": "shape",
                        "role": "decoration", "bbox": badge, "geometry": "ellipse",
                        "fill": accent, "line": "none", "collision_mode": "container"})
                    self.emit_text(f"sequence:number:{index}", str(index), badge, "badge", 20, 20, 1, "middle", "#FFFFFF")
                self.adaptations.append({"action": "sequence_rail",
                    "source": "visual_intent" if self.visual_intent else "legacy_roles",
                    "block_ids": [b["id"] for b in self.blocks]})

    def finalize_slide(self):
        if self.family in ('columns', 'equations') and not self.figs and not self.visible_caveats and len(self.blocks) >= 3:
            notice = lower_whitespace_issue(self.elements, self.n, self.top, self.bottom)
            if notice:
                self.issues.append(notice)
        if self.family != 'cover' and not any(
            i.get('slide') == self.n and i.get('rule') in (
                'TEXT_ONLY_LOWER_WHITESPACE', 'CONTENT_LOWER_WHITESPACE', 'SPARSE_TEXT_PAGE'
            )
            for i in self.issues
        ):
            ws_notice = body_whitespace_issue(self.elements, self.n, self.top, self.bottom)
            if ws_notice:
                self.issues.append(ws_notice)
        page_furniture_elements(self.elements, self.emit_text, self.n, self.slide,
                                self.ir.get('presentation') or {}, self.design, self.furniture)
        if (self.comp.get('layout_tree') or self.comp.get('graphics') or self.design) and len({e['id'] for e in self.elements}) != len(self.elements):
            self.issues.append(issue('GRAPHIC_ID_COLLISION' if self.comp.get('graphics') else 'VISUAL_PLAN_ID_COLLISION',
                                     'FAIL', 'Page object names must be unique',
                                     self.n, detector='geometric-preflight'))
        # Diagram labels are their own type scale; this rule is about running body copy on the page.
        body_sizes = sorted({round(e['contract']['font_size'], 1) for e in self.elements
                             if e.get('kind') == 'text' and e.get('role') == 'body' and e.get('contract')
                             and not e['id'].startswith('graphic:')})
        if len(body_sizes) > 1:
            # Body copy on one page is one size. A fitted block may shrink to avoid a hard failure,
            # but then the page is reported so the composition can be reflowed instead of shipping
            # three body sizes that read as accidental emphasis.
            self.issues.append(issue('BODY_SIZE_VARIANCE', 'REVIEW',
                f'Body copy uses {len(body_sizes)} sizes on one page ({", ".join(f"{s * .75:.1f}" for s in body_sizes)} pt); '
                'reflow or split the page so body text keeps one size and the page anchor stays distinct.',
                self.n, detector='geometric-preflight', body_font_px=body_sizes,
                suggested_actions=['reflow_region', 'split_slide']))
        for b in self.blocks:
            if (b.get('text_flow') in EXPLICIT_LISTS and not b.get('_inferred_list')
                    and not any(e['id'] == b['id'] and e['kind'] == 'list' for e in self.elements)
                    and not any(i['severity'] == 'FAIL' and i.get('slide') == self.n for i in self.issues)):
                self.issues.append(issue('SPLIT_REQUIRED', 'FAIL',
                    f"{b['id']}: this composition cannot realize the explicit native list; choose a wider layout or split the page.",
                    self.n, b['id'], detector='geometric-preflight', suggested_actions=['widen_region', 'split_slide']))
        self.issues.extend(geometry_issues(self.elements, self.n))
        if self.visual_plan and any(i['severity'] == 'FAIL' and i.get('slide') == self.n for i in self.issues) and not any(
                i['rule'] == 'VISUAL_PLAN_UNSATISFIABLE' and i.get('slide') == self.n for i in self.issues):
            self.issues.append(issue('VISUAL_PLAN_UNSATISFIABLE', 'FAIL',
                'The selected visual composition failed a page gate; replan without changing scientific content.',
                self.n, detector='geometric-preflight'))
        notes = self.sem["speaker_notes"]
        notes_only = [*(self.sem.get("run_notes") or []), *self.moved_caveats]
        if notes_only:
            # Provenance stays with the deck; it just stops being projected.
            notes += "\n\n备注（不投屏）：" + "；".join(notes_only)
        if self.footer:
            notes += "\nEvidence: " + self.footer
        return {"id": self.slide["id"],
                "background": "#FFFFFF" if self.templated else self.theme.get("background", "#FFFFFF"),
                "notes": notes,
                "elements": self.elements, "adaptation_log": self.adaptations}

    def compile(self, proposals):
        self.emit_header()
        self.compile_body(proposals)
        return self.finalize_slide()


def _apply_deck_agenda(ir, slides, ctx, issues):
    presentation = ir.get('presentation') or {}
    agenda = presentation.get('agenda')
    sections = agenda_sections(ir)
    if sections and not agenda:
        # Section labels only steer the contents page; without one they are invisible metadata.
        issues.append(issue('SECTION_LABELS_UNUSED', 'INFO',
            f'{len(sections)} section labels are declared but presentation.agenda is off, so nothing '
            'on the page shows them. Add an agenda or drop the labels.', detector='geometric-preflight'))
    if not agenda:
        return
    if not ctx['design']:
        issues.append(issue('AGENDA_SKIPPED', 'REVIEW',
            'presentation.agenda needs academic_design: the contents page uses the designed header, '
            'footer rule and page numbers.', detector='geometric-preflight'))
    elif len(sections) < 2:
        issues.append(issue('AGENDA_EMPTY', 'REVIEW',
            'presentation.agenda needs at least two slides that declare presentation.section; '
            'no contents page was generated.', detector='geometric-preflight'))
    elif len(slides) >= 2:
        # The contents page goes after the opening page, so every later page moves one slot;
        # the number the reader sees is rewritten before the contents page is built from it.
        for index, page in enumerate(slides, 1):
            if index > 1:
                number_element = next((e for e in page['elements'] if e['id'] == 'page:number'), None)
                if number_element is not None:
                    number_element['text'] = str(index + 1)
        slides.insert(1, agenda_slide(agenda if isinstance(agenda, dict) else {},
                                      sections, ctx['theme'], ctx['font_paths'], ctx['design'],
                                      2 if presentation.get('page_numbers', True) else None,
                                      ctx['furniture'], footer_text=presentation.get('footer')))
        if len(sections) > AGENDA_MAX_SECTIONS:
            issues.append(issue('AGENDA_TRUNCATED', 'REVIEW',
                f'presentation.section declares {len(sections)} sections; the contents page holds '
                f'{AGENDA_MAX_SECTIONS}. Merge sections or split the deck.', detector='geometric-preflight'))


def compile_deck(ir, base, _retry=True, proposals=None):
    ir = enable_bare_subscripts(deepcopy(ir))
    issues = validate(ir)
    # A REVIEW is something a human confirms later; only a FAIL stops compilation. Treating every
    # finding as fatal meant an equation-only page could not even be laid out to be reviewed.
    if any(item["severity"] == "FAIL" for item in issues):
        return None, issues
    ctx = _resolve_deck_context(ir, base, issues)
    if ctx is None:
        return None, issues
    slides = [_SlideCompiler(ctx, n, slide, issues).compile(proposals)
              for n, slide in enumerate(ir["slides"], 1)]
    _apply_deck_agenda(ir, slides, ctx, issues)
    if _retry and not ctx["design"] and not ctx["preserve_terms"] and any(i["rule"] == "SPLIT_REQUIRED" for i in issues):
        import copy
        alternative = copy.deepcopy(ir)
        alternative.setdefault("presentation", {})["frame_variant"] = "spacious"
        retry_layout, retry_issues = compile_deck(alternative, base, _retry=False, proposals=proposals)
        if retry_layout and not any(i["severity"] == "FAIL" for i in retry_issues):
            retry_layout["ir_sha256"] = digest(ir)
            retry_layout["selected_variants"] = {str(n): "spacious" for n in range(1, len(ir["slides"]) + 1)}
            return retry_layout, retry_issues
    deck_frame = ctx["deck_frame"]
    assets = ctx["assets"]
    background_key = ctx["background_key"]
    return {"schema_version": "2.0", "ir_sha256": digest(ir), "slide_size": [WIDTH, HEIGHT],
            "deck_frame_variant": deck_frame,
            "frame_variant_overrides": {str(n): deck_frame for n, slide in enumerate(ir["slides"], 1)
                if slide["presentation"].get("variant", "default") != deck_frame},
            "assets": assets, "font_hashes": {p: file_hash(Path(p)) for p in ctx["font_paths"].values()},
            "resolved_font_family": ctx["theme"]['font_family'],
            "background_image": (assets[background_key]["path"] if background_key else None),
            **({'academic_design': ctx["design"]} if ctx["design"] else {}),
            "slides": slides}, issues
