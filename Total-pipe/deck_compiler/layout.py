"""Deterministic layout compiler. No LLM calls, mutation, or content rewriting."""
from dataclasses import replace
from pathlib import Path
import re
from PIL import Image, ImageFont
from . import audience
from .catalog import ARCHETYPES
from .capacity import DISPLAY_FORMULA_SIZES, FORMULA_GAP, FORMULA_LABEL_MAX, FORMULA_SIZES
from .formula_layout import formula_groups, plan_formula_flow, FormulaCapacityError
from .contracts import TextBoxContract, digest, file_hash, issue
from .ir import validate
from .layout_tree import walk as walk_regions
from .graphic_layout import (compile_graphic, graphic_counts, graphic_obstacle_collisions,
                             graphic_texts, intentional_overlap)
from .text_flow import DISTRIBUTED_ARROW_LIST, select_text_flow
from .visual_design import (TITLE_BOX_LINES, header_decoration, header_layout, preserve_scientific_terms,
                            resolve_design, rule, type_sizes)
from totalpipe_layout.inline_math import has_markup, strip_markup, unmatched_markers

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
    lines = break_lines(strip_markup(caption), load_font_file(font_file, size), max(1, width))
    return max(34.0, len(lines) * size * 1.25 + 8)


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
    return f'[[{label}]] · {caption}'


def caption_measure(ref, width, font_file):
    """``(height, lines)`` of a caption strip, measured the way it will be set.

    A labelled caption is set as runs, so it is measured by the inline engine that draws it: the
    plain wrapper and the run engine break lines slightly differently, and a strip that reserved
    one line too few would silently shrink the caption to its floor.
    """
    from .fonts import load_font_file
    content = caption_with_source(ref) if isinstance(ref, dict) else str(ref or '')
    size = float((ref or {}).get('caption_font_size', CAPTION_FONT_SIZE))
    if not content:
        return 0., 0
    if has_markup(content):
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
    if flow is None and block.get('text_flow') != DISTRIBUTED_ARROW_LIST:
        return None
    flow = flow or select_text_flow(block['text'], DISTRIBUTED_ARROW_LIST)
    if flow['mode'] != DISTRIBUTED_ARROW_LIST:
        return None
    if width < 520:
        return 10000.0
    pad_x, pad_y = padding
    rows = flow['items']
    face = ImageFont.truetype(font_file, 24)
    from .fonts import bullet_metrics
    marker = bullet_metrics(block.get('bullet_style', default_style), face.getname()[0], font_file, 24)
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


def break_lines(text, font, width):
    """Preserve paragraphs, break at words/CJK glyphs; long tokens split safely."""
    lines = []
    for paragraph in text.split("\n"):
        pieces = []
        for token in TOKEN.findall(paragraph):
            current = ''.join(pieces)
            if pieces and font.getlength(current + token) > width:
                # Kinsoku: a closing mark or unit never starts a line. The token before it travels
                # down instead, so "2.84×，" does not become "2.84" / "×，".
                if token[:1] in NO_LINE_START and len(current.strip()) > 2:
                    carried = pieces.pop()
                    lines.append(''.join(pieces).rstrip())
                    pieces = [carried + token.lstrip()]
                    continue
                lines.append(current.rstrip())
                pieces = []
                token = token.lstrip()
            if not pieces and font.getlength(token) > width:
                for char in token:
                    if pieces and font.getlength(''.join(pieces) + char) > width:
                        lines.append(''.join(pieces).rstrip())
                        pieces = []
                    pieces.append(char)
                continue
            pieces.append(token)
        lines.append(''.join(pieces).rstrip())
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
    """Estimate the occupied text edge, not the full reserved textbox edge."""
    _x, y, _w, height = element["bbox"]
    contract = element["contract"]
    if contract["vertical_anchor"] != "top":
        return y + height
    if element.get('inline_math'):
        return min(y+height, y+contract['inset']['top']+element['inline_layout']['height'])
    if element['kind'] == 'list':
        occupied = (sum(len(lines) for lines in element['items'])*contract['font_size']*contract['line_height']
                    +element['bullet'].get('space_after', 0)*max(0, len(element['items'])-1))
        return min(y+height, y+contract['inset']['top']+occupied)
    line_count = len(re.split('[\n\v]', element["text"]))
    return min(y + height, y + contract["inset"]["top"] +
               line_count * contract["font_size"] * contract["line_height"])


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


def compile_deck(ir, base, _retry=True, proposals=None):
    issues = validate(ir)
    # A REVIEW is something a human confirms later; only a FAIL stops compilation. Treating every
    # finding as fatal meant an equation-only page could not even be laid out to be reviewed.
    if any(issue["severity"] == "FAIL" for issue in issues):
        return None, issues
    base = Path(base)
    design = resolve_design(ir)
    preserve_terms = preserve_scientific_terms(ir)
    theme = {**ir['theme'], **({'accent': design['accent_color']} if design else {})}
    from .style import StyleError, resolve as resolve_style
    try:
        theme['_visual_style'] = resolve_style(ir.get('presentation'))
    except StyleError as error:
        issues.append(issue('VISUAL_STYLE_INVALID', 'FAIL', str(error), detector='geometric-preflight'))
        return None, issues
    from .style import page_furniture, text_styles
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
        + [font_sample(block.get("text", ""), block.get('inline_math', False))+block.get("label", "") for slide in ir["slides"]
           for block in slide["composition"]["blocks"]]
        + [figure.get("caption", "") for slide in ir["slides"]
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
        return None, issues
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
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                assets[key] = {**asset, "path": str(path), "width": image.width,
                               "height": image.height, "sha256": file_hash(path),
                               "content_type": Image.MIME[image.format]}
        except (OSError, ValueError, KeyError) as e:
            issues.append(issue("ASSET_INVALID", "FAIL", f"{key}: {e}", detector="geometric-preflight"))
    if any(i["severity"] == "FAIL" for i in issues):
        return None, issues
    # A full-bleed background is declared by the theme and drawn by the compiler beneath every
    # element. It used to be stamped into the slide master by a script that ran after QA, which is
    # how a delivered deck ended up with bytes no report had inspected.
    background_key = None
    background_image = theme.get("background_image")
    if background_image:
        from . import background as background_layer
        path = (base / background_image).resolve()
        try:
            stats, findings = background_layer.review(
                path, theme.get("foreground", "#142735"), path.stat().st_size)
            issues += findings
            assets["@background"] = {"path": str(path), "width": WIDTH, "height": HEIGHT,
                                     "sha256": file_hash(path), "content_type": "image/png"}
            background_key = "@background"
        except (OSError, ValueError) as error:
            issues.append(issue("BACKGROUND_INVALID", "FAIL", f"{background_image}: {error}",
                                detector="geometric-preflight"))
            return None, issues
    deck_frame = frame_variant(ir)
    slides = []
    for n, slide in enumerate(ir["slides"], 1):
        sem, comp = slide["semantic"], slide["composition"]
        visual_plan = slide['presentation'].get('visual_plan')
        # Deck IR fallback: a block whose text is several paragraphs is a list, even when the author
        # forgot to say so. The copy keeps the caller's IR untouched.
        from .text_flow import fallback_list
        blocks = [fallback_list(block) for block in comp["blocks"]]
        comp = {**comp, "blocks": blocks}
        figs = comp["figure_refs"]
        # A page whose only object is one equation is an equation page: let it use the display
        # ladder, so the formula is the anchor instead of a body-sized line. Long equations fall
        # back down the ladder on their own when the measured width does not fit.
        formula_sizes = FORMULA_SIZES
        equation_page = (len([b for b in blocks if b.get('component') == 'formula']) == 1
                         and not figs and not comp.get('tables') and not comp.get('graphics')
                         and len(blocks) <= 4)
        if equation_page:
            formula_sizes = DISPLAY_FORMULA_SIZES+FORMULA_SIZES
        show_sequence = sequence_flow(comp)
        visual_intent = comp.get("visual_intent") or {}
        family = ARCHETYPES[comp["archetype"]]["layout"]
        elements = []
        adaptations = []
        slide_formulas = []
        scientific_text_ids = {'title', 'takeaway', *(b['id'] for b in blocks), *(b['id']+':label' for b in blocks)}
        if comp.get('layout_tree'):
            from .layout_tree import walk
            scientific_text_ids.update('region:'+node['id']+':title'
                                       for _, node in walk(comp['layout_tree']) if node['type'] == 'panel')
        def text(eid, content, bbox, role="body", size=28, floor=24, lines=10,
                 anchor="top", color=None, flow=None, align=None, inline_math=False, marker=None):
            if not content:
                return
            if design and role in type_sizes(design) and not eid.startswith('graphic:'):
                size = min(size, type_sizes(design)[role])
            contract = TextBoxContract(theme["font_family"], size,
                font_paths["bold_font_file" if role in ("title", "heading") else "font_file"],
                font_weight=700 if role in ("title", "heading") else 400,
                font_floor=floor, max_lines=lines, vertical_anchor=anchor)
            if marker:
                contract = replace(contract, line_height=max(contract.line_height, marker['line_height_px']/size))
            measure_box = [*bbox[:2], bbox[2]-(marker['gutter'] if marker else 0), bbox[3]]
            overflow = None
            # Authored emphasis is a measured run, not a decoration: the phrase is set in the bold
            # face, so it is laid out by the same inline engine that already handles a formula in a
            # sentence. Text without markers keeps the plain, cheaper path byte for byte.
            markup = has_markup(content)
            if inline_math or markup:
                from .inline_text import fit_inline, text_body
                from totalpipe_layout.inline_math import InlineWidthError
                try:
                    plan, fitted, overflowed = fit_inline(content, measure_box, contract, preserve_terms and eid in scientific_text_ids, marker,
                                                          font_paths['bold_font_file'])
                except InlineWidthError as error:
                    issues.append(issue('INLINE_FORMULA_SPACE', 'FAIL', str(error), n, eid,
                        detector='geometric-preflight', required_size_px=[error.required_width, 0],
                        available_size_px=bbox[2:], suggested_actions=['widen_region', 'use_display_formula', 'split_slide']))
                    return
                except ValueError as error:
                    issues.append(issue('INLINE_TEXT_CAPACITY', 'FAIL', str(error), n, eid, detector='geometric-preflight'))
                    return
                if overflowed:
                    overflow = {'original_bbox': list(bbox), 'policy': 'preserve-terms'}
                    bbox = [*bbox[:3], max(bbox[3], plan['height']+contract.inset['top']+contract.inset['bottom'])]
                    issues.append(issue('SCIENTIFIC_TEXT_OVERFLOW', 'REVIEW',
                        f'{eid}: complete mixed text and formulas retained beyond the nominal slot.', n, eid, detector='geometric-preflight'))
                unpaired = unmatched_markers(content)
                if unpaired:
                    # A marker pair that was never closed stays visible. Refusing the page would be
                    # worse than showing the author what to fix, so the phrase is set literally and
                    # the page is reported.
                    issues.append(issue('EMPHASIS_UNCLOSED', 'REVIEW',
                        f"{eid}: {', '.join(unpaired)} is set literally; close the marker or escape it.",
                        n, eid, detector='geometric-preflight', suggested_actions=['close_marker', 'escape_marker']))
                colour = color or theme.get('foreground', '#142735')
                elements.append({'id': eid, 'kind': 'text', 'role': role, 'text': plan['text'], 'source_text': content,
                    'bbox': bbox, 'contract': fitted.to_dict(), 'color': colour, 'inline_math': True,
                    'inline_layout': plan, 'inline_xml': text_body(plan, fitted.to_dict(), colour, align or 'left', marker=marker,
                                                                   styles=text_inks),
                    **({'bullet': marker, 'leading_marker': True} if marker else {}),
                    **({'align': align} if align else {}), **({'scientific_text_overflow': overflow} if overflow else {})})
                if plan['marks']:
                    adaptations.append({'action': 'inline_emphasis', 'element': eid, 'marks': plan['marks']})
                if plan['formula_count']:
                    issues.append(issue('INLINE_MATH_MEASUREMENT_REVIEW', 'REVIEW',
                        f'{eid}: verify native inline baseline, line spacing and formula bounds in PowerPoint.',
                        n, eid, detector='geometric-preflight', confidence='LOW'))
                return
            try:
                output, fitted = fit_text(content, measure_box, contract)
            except ValueError:
                if preserve_terms and eid in scientific_text_ids and min(bbox[2:]) > 0 and role != 'title':
                    wrapped = break_lines(content, ImageFont.truetype(contract.font_file, int(floor)), measure_box[2])
                    output = '\n'.join(wrapped)
                    overflow = {'original_bbox': list(bbox), 'policy': 'preserve-terms'}
                    bbox = [*bbox[:3], max(bbox[3], len(wrapped)*floor*contract.line_height)]
                    fitted = replace(contract, font_size=floor, max_lines=max(lines, len(wrapped)),
                                     overflow_policy='preserve_terms_review')
                    issues.append(issue('SCIENTIFIC_TEXT_OVERFLOW', 'REVIEW',
                        f'{eid}: full scientific text retained beyond its nominal slot; inspect the candidate without abbreviating terminology.',
                        n, eid, detector='geometric-preflight', original_bbox=overflow['original_bbox']))
                else:
                    issues.append(issue("SPLIT_REQUIRED", "FAIL", f"{eid} cannot fit above its font floor",
                                        n, eid, detector="geometric-preflight", textbox_contract="deck_ir"))
                    return
            # Missing-glyph comparison is a conservative signal, not full shaping coverage.
            font = ImageFont.truetype(fitted.font_file, int(fitted.font_size))
            missing = bytes(font.getmask(chr(0x10FFFF)))
            gaps = {c for c in set(content) if not c.isspace() and bytes(font.getmask(c)) == missing}
            if gaps and not gaps <= deck_gap:
                issues.append(issue("FONT_COVERAGE_REVIEW", "REVIEW", "Possible missing glyphs; verify in PowerPoint",
                                    n, eid, detector="geometric-preflight", confidence="LOW",
                                    font_metrics="pillow", characters=''.join(sorted(gaps))[:20]))
            # The declared scale, checked on the fitted size: an annotation may be 15 pt, body copy
            # may not. This is the rule the old code implied with two different floors and never
            # stated, which is how a 13.5 pt footer shipped beside 18 pt body text. A diagram label
            # is annotation: a node body is a caption inside a shape, not running copy.
            annotation = role in ANNOTATION_ROLES or eid.startswith('graphic:')
            minimum_pt = ANNOTATION_MIN_PT if annotation else BODY_MIN_PT
            if fitted.font_size * .75 < minimum_pt - .01:
                issues.append(issue("TYPOGRAPHY_FLOOR", "FAIL",
                                    f"{eid} is set at {fitted.font_size*.75:.1f} pt; the {role} "
                                    f"floor is {minimum_pt:.0f} pt",
                                    n, eid, detector="geometric-preflight", confidence="HIGH",
                                    role=role, font_pt=round(fitted.font_size*.75, 1),
                                    floor_pt=minimum_pt))
            if role == "footer" and "\n" in output:
                # A soft break, not a new paragraph: OfficeCLI's overflow estimator counts every
                # paragraph of a pre-broken footer as one line more than the renderer draws.
                output = output.replace("\n", "\v")
            unpaired = unmatched_markers(content)
            if unpaired:
                issues.append(issue('EMPHASIS_UNCLOSED', 'REVIEW',
                    f"{eid}: {', '.join(unpaired)} is set literally; close the marker or escape it.",
                    n, eid, detector='geometric-preflight', suggested_actions=['close_marker', 'escape_marker']))
            elements.append({"id": eid, "kind": 'list' if marker else "text", "role": role,
                             "text": output.replace('\n', '\v') if marker else output,
                             **({'items': [output.split('\n')], 'bullet': marker,
                                 'leading_marker': True, 'source_text': content} if marker else {}),
                             "source_text": content, "bbox": bbox, "contract": fitted.to_dict(),
                             "color": color or theme.get("foreground", "#142735"),
                             **({'scientific_text_overflow': overflow} if overflow else {}),
                             **({"align": align} if align else {}),
                             **({"text_flow": flow} if flow else {})})
        takeaway_marker = None
        if slide['presentation'].get('takeaway_marker'):
            setting = slide['presentation']['takeaway_marker']
            from .fonts import bullet_metrics
            takeaway_marker = {**bullet_metrics(setting['style'], theme['font_family'], regular_font, 28),
                               'color': setting.get('color', theme.get('foreground', '#142735')),
                               'space_after': 0}
            adaptations.append({'action': 'takeaway_marker', **takeaway_marker})
            if takeaway_marker['native_font_fallback']:
                issues.append(issue('BULLET_GLYPH_REVIEW', 'REVIEW',
                    'Requested native marker font is unavailable; inspect the Unicode fallback glyph.',
                    n, 'takeaway', detector='font-resolution'))
        spacious = deck_frame == "spacious"
        templated = deck_frame == "template"
        footer = " · ".join(sem["evidence_refs"])
        visible_caveats, moved_caveats = audience.split_caveats(sem["caveats"])
        takeaway_outer = None
        def takeaway(slot, size=28, color=None, lines=2, frame_plan=None):
            nonlocal takeaway_outer
            if slide['presentation'].get('takeaway_frame'):
                from .container_frames import measure_takeaway, rectangle, grow_frame, stroke_width
                plan = frame_plan or measure_takeaway(slide, font_paths, slot, takeaway_marker)
                framed = rectangle('takeaway:frame', plan['bbox'], plan['style'], ['takeaway'])
                elements.append(framed)
                first = len(elements)
                text('takeaway', sem['takeaway'], plan['text_bbox'], 'takeaway', size, 24,
                     plan['lines'], color=color, inline_math='takeaway' in sem.get('inline_math', []), marker=takeaway_marker)
                takeaway_outer = grow_frame(framed, plan['bbox'], elements[first:],
                                            plan['padding_px']+stroke_width(plan['style']))
                adaptations.append({'action': 'takeaway_frame', **plan, 'bbox': takeaway_outer})
            else:
                text('takeaway', sem['takeaway'], slot, 'takeaway', size, 24, lines,
                     color=color, inline_math='takeaway' in sem.get('inline_math', []), marker=takeaway_marker)
        if design and family == 'cover':
            # A cover is the page the design layer can ask for that carries no content blocks: the
            # title says what the talk is, one line says why it is worth the next forty minutes, and
            # a short accent rule sets the tone without a picture. It is deliberately the only page
            # whose title does not sit in the header box.
            sizes = type_sizes(design)
            elements.append(rule('cover:rule', [56, 268, 136, 4], design))
            text('title', sem['title'], [56, 300, 1100, 116], 'title', sizes['title'], sizes['title'], 2)
            text('takeaway', sem['takeaway'], [56, 462, 980, 96], 'takeaway', sizes['takeaway'], 24, 3)
            adaptations.append({'action': 'cover', 'title': sem['title']})
            # A cover has no caveat strip and no page furniture: it is the page before page 1.
            visible_caveats = []
            caveat_y, caveat_h = 604, 46
        elif design:
            header = header_layout(design, slide, font_paths, preserve_terms)
            # One title size for the whole deck; the header grew instead of the title shrinking.
            title_pt = header.get('title_size', type_sizes(design)['title'])
            text('title', sem['title'], header['title'], 'title', title_pt, title_pt,
                 header.get('title_lines', 2), inline_math='title' in sem.get('inline_math', []))
            if header.get('title_lines', 2) >= TITLE_BOX_LINES and len(
                    break_lines(sem['title'], ImageFont.truetype(font_paths['bold_font_file'], int(title_pt)), 1168)) > TITLE_BOX_LINES:
                issues.append(issue('TITLE_TOO_LONG', 'FAIL',
                    'The title needs more than three lines at the deck title size; shorten it or split the page.',
                    n, 'title', detector='geometric-preflight', suggested_actions=['shorten_title', 'split_slide']))
            takeaway(header['takeaway'], lines=header.get('takeaway_lines', 2), frame_plan=header.get('takeaway_frame'))
            elements.extend(header_decoration(design, header))
            caveat_y, caveat_h = (622, 36) if family == 'dual' else (604, 46)
        elif templated:
            # A lab template owns the page frame: its own title slot, its own footer band, its own
            # white page. The compiler keeps the body grid but hands the title, takeaway and caveat
            # to the template's geometry.
            # The template's title slot ends at its red rule (y=78), so the title is set to fit
            # above it and the takeaway opens the body underneath.
            text("title", sem["title"], [88, 24, 1104, 50], "title", 36, 30, 2, color="#1A1A1A", inline_math='title' in sem.get('inline_math', []))
            takeaway([88, 84, 1104, 42], 24, color='#333333')
            caveat_y, caveat_h = 640, 36
        else:
            text("title", sem["title"], [56, 24 if spacious else 34, 1168, 116 if spacious else 120], "title", 44, 36, 2, inline_math='title' in sem.get('inline_math', []))
            # These two evidence-heavy slides use a single-line takeaway; reclaiming
            # the unused vertical room lets the original scientific panels render
            # larger without colliding with the title block.
            takeaway_h = 56 if slide["id"] in ("s05-anneal", "s07-contact") else 76
            takeaway([56, 144 if spacious else 164, 1168, takeaway_h])
            # No footer element on any frame. The evidence ids used to be set at 15 pt under every
            # page, which meant a dozen EV numbers shared the bottom strip with the caveat. They are
            # traceability keys: the notes carry them, the room does not need them.
            caveat_y, caveat_h = 604, 46
            if family == "dual":
                # Compact callouts and larger scientific panels extend lower on
                # dual-evidence slides, while keeping the caveat clear.
                caveat_y, caveat_h = 622, 36
        if visible_caveats:
            text("caveats", audience.join_caveats(visible_caveats), [56, caveat_y, 1168, caveat_h], "caveat", 24, 24, 2)
        top, bottom = body_region(slide, family, deck_frame, design, font_paths, preserve_terms)
        if takeaway_outer:
            top = max(top, takeaway_outer[1]+takeaway_outer[3]+20)
        bh = bottom-top
        def block(b, box, formula_size=None, formula_align='center'):
            label = b.get("label", "")
            if b.get("component") == "formula":
                # A formula is a measured unit: it cannot wrap, it is never fed through the text
                # wrapper, and it is never silently set below 18 pt to make a page fit.
                from totalpipe_layout.formula import (FormulaError, measure, parse,
                                                      to_omml_paragraph, to_plain)
                try:
                    ast = parse(b["text"])
                except FormulaError as error:
                    issues.append(issue("FORMULA_SYNTAX", "FAIL", f"{b['id']}: {error}",
                                        n, b["id"], detector="geometric-preflight"))
                    return
                # A label sits to the left of the equation on its centre line. A heading above it
                # would cost the row 40 px, and on a dense page that is the whole difference.
                label_w = formula_label_width(label, font_paths["bold_font_file"])
                gaps = (label_w + 12) if label_w else 0
                inner = [box[0]+gaps, box[1]+6, box[2]-gaps-20 if label_w else box[2]-20,
                         box[3]-12]
                chosen = None
                for size_px in ([formula_size] if formula_size is not None else formula_sizes):
                    metrics = measure(ast, size_px)
                    if metrics.width <= inner[2]+.5 and metrics.height <= inner[3]+.5:
                        chosen = (size_px, metrics)
                        break
                if chosen is None:
                    widest = measure(ast, FORMULA_SIZES[-1])
                    issues.append(issue(
                        "FORMULA_CAPACITY", "FAIL",
                        f"{b['id']} needs {widest.width:.0f} × {widest.height:.0f} px at 18 pt but its slot is "
                        f"{max(inner[2], 0):.0f} × {max(inner[3], 0):.0f} px. Widen the slot or move the equation to "
                        "its own slide: the compiler will not shrink the body text, or the "
                        "equation below 18 pt, to make it fit.",
                        n, b["id"], detector="geometric-preflight",
                        formula_width_px=round(widest.width, 1),
                        formula_height_px=round(widest.height, 1),
                        slot_width_px=round(max(inner[2], 0), 1),
                        slot_height_px=round(max(inner[3], 0), 1),
                        suggested_fix="widen_text_column_or_split_slide"))
                    return
                if label_w:
                    text(b["id"]+":label", label,
                         [box[0], box[1]+(box[3]-30)/2, label_w, 30], "heading", 24, 24, 1)
                size_px, metrics = chosen
                slide_formulas.append((b["id"], metrics.height))
                bbox = [inner[0]+((inner[2]-metrics.width)/2 if formula_align == 'center' else 0),
                        inner[1]+(inner[3]-metrics.height)/2,
                        metrics.width, metrics.height]
                colour = theme.get("foreground", "#142735")
                elements.append({
                    "id": b["id"], "kind": "math", "role": "formula", "bbox": bbox,
                    "omml": to_omml_paragraph(ast, size_px, colour,
                                              fallback_font=font_paths["font_file"],
                                              box_width=inner[2]),
                    "plain": to_plain(ast), "font_size_px": size_px,
                    "measured_exact": metrics.exact, "source_text": b["text"],
                    "color": colour})
                if not metrics.exact:
                    issues.append(issue("FORMULA_MEASURE_APPROXIMATE", "REVIEW",
                                        f"{b['id']} uses conservative structural or fallback metrics; "
                                        "verify the rendered formula width and height in PowerPoint",
                                        n, b["id"], detector="geometric-preflight",
                                        confidence="LOW", font_metrics="heuristic"))
                return
            if show_sequence:
                box = [box[0]+56, box[1], box[2]-56, box[3]]
            flow = select_text_flow(b["text"], b.get("text_flow", "auto"))
            if b.get('inline_math'):
                flow = {**flow, 'mode': 'plain'}
            if flow['mode'] == DISTRIBUTED_ARROW_LIST and has_markup(b['text']):
                # A native list is one run style across its items: the words stay, the emphasis
                # cannot. Report it instead of shipping a bullet with visible ** in it.
                flow = {**flow, 'items': [strip_markup(item) for item in flow['items']]}
                issues.append(issue('EMPHASIS_IN_LIST', 'REVIEW',
                    f"{b['id']}: a native list carries one run style, so emphasis markers are set as plain text; "
                    "use text_flow=plain to keep the emphasis.", n, b['id'], detector='geometric-preflight',
                    suggested_actions=['text_flow_plain', 'drop_markers']))
            pad_x, pad_y = (0, 0) if design else (28, 18)
            measured_list_height = (native_list_height(
                b, max(520, box[2]), font_paths["font_file"], list_gap_ratio,
                (pad_x, pad_y), preserve_terms, bullet_style, flow=flow)
                if flow["mode"] == DISTRIBUTED_ARROW_LIST else None)
            if (flow["mode"] == DISTRIBUTED_ARROW_LIST and box[2] >= 520
                    and measured_list_height is not None
                    and (preserve_terms or box[3] + .5 >= measured_list_height)):
                label_h = 44 if label else 0
                items = flow["items"]
                current_style = b.get('bullet_style', bullet_style)
                from .fonts import bullet_metrics
                marker = bullet_metrics(current_style, theme['font_family'], regular_font, 24)
                # One text object, one paragraph per item, marker set by the paragraph itself.
                # The theme's line height is 1.25, which is what the contract and OfficeCLI agree on.
                fitted = fit_list_items(items, box[2]-2*pad_x-marker['gutter'],
                                        font_paths["font_file"], 24, 24, LIST_ITEM_LINES)
                beyond_lines = fitted is None
                if beyond_lines and not preserve_terms:
                    issues.append(issue("SPLIT_REQUIRED", "FAIL",
                                        f"{b['id']} list items cannot fit above their font floor",
                                        n, b["id"], detector="geometric-preflight",
                                        textbox_contract="deck_ir"))
                    return
                if beyond_lines:
                    size = 24
                    lines = [break_lines(item, ImageFont.truetype(font_paths['font_file'], size),
                                         box[2]-2*pad_x-marker['gutter']) for item in items]
                else:
                    lines, size = fitted
                line_h = marker['line_height_px']
                gaps = len(lines) - 1
                # Item spacing is a typographic value, not leftover space: filling the panel is what
                # pushed three short items a hundred pixels apart. The ratio is relative to the line
                # height (so it follows the font), and the deck may override it.
                space_after = round(line_h * list_gap_ratio, 2) if gaps else 0.0
                content_h = sum(len(item_lines) for item_lines in lines) * line_h + space_after * gaps
                panel_h = 2*pad_y + label_h + content_h
                overflow = None
                if (panel_h > box[3] + .5 or beyond_lines) and not preserve_terms:
                    issues.append(issue("SPLIT_REQUIRED", "FAIL",
                                        f"{b['id']} list needs {content_h:.0f}px but the panel gives "
                                        f"{box[3]-2*pad_y-label_h:.0f}px", n, b["id"],
                                        detector="geometric-preflight", textbox_contract="deck_ir"))
                    return
                if panel_h > box[3] + .5 or beyond_lines:
                    overflow = {'original_bbox': [box[0]+pad_x, box[1]+pad_y+label_h,
                                                 box[2]-2*pad_x, max(0, box[3]-2*pad_y-label_h)],
                                'policy': 'preserve-terms'}
                    issues.append(issue('SCIENTIFIC_TEXT_OVERFLOW', 'REVIEW',
                        f"{b['id']}: complete native list retained with its markers and wrapped scientific terms beyond the nominal slot or item-line budget.",
                        n, b['id'], detector='geometric-preflight', original_bbox=overflow['original_bbox'],
                        required_size_px=[box[2], panel_h], available_size_px=box[2:],
                        suggested_actions=['increase_region_height', 'split_slide', 'review_native_render']))
                # The card hugs the list instead of stretching to the page: a panel with 150 px of
                # empty space under three rows reads as a layout mistake, not as breathing room.
                if not design:
                    elements.append({
                    "id": b["id"] + ":panel", "kind": "shape", "role": "decoration",
                    "bbox": [box[0], box[1], box[2], panel_h],
                    "geometry": "rect", "fill": theme.get("panel_fill", "none"),
                    "line": theme.get("panel_line", "#142735"), "line_width": 1,
                    "collision_mode": "container",
                    **({'scientific_text_overflow': {'original_bbox': list(box), 'policy': 'preserve-terms'}} if overflow else {})})
                if label:
                    text(b["id"]+":label", label,
                         [box[0]+pad_x, box[1]+pad_y, box[2]-2*pad_x, label_h],
                         "heading", 28, 24, 1)
                style = {"id": b["id"], "kind": "list", "role": "body",
                         "bbox": [box[0]+pad_x, box[1]+pad_y+label_h, box[2]-2*pad_x, content_h],
                         "color": theme.get("foreground", "#142735")}
                contract = TextBoxContract(theme["font_family"], size, font_paths["font_file"],
                                           font_weight=400, font_floor=24,
                                           line_height=line_h/size,
                                           max_lines=max(len(item_lines) for item_lines in lines),
                                           vertical_anchor="top")
                bullet_glyph, bullet_face = marker['char'], marker['face']
                current_color = b.get('bullet_color', bullet_color)
                if marker['native_font_fallback']:
                    issues.append(issue('BULLET_GLYPH_REVIEW', 'REVIEW',
                        'Requested native marker font is unavailable; inspect the Unicode fallback glyph.',
                        n, b['id'], detector='font-resolution'))
                elements.append({**style, "items": lines,
                                 "text": "\n".join("\v".join(item_lines) for item_lines in lines),
                                 "source_text": b["text"], "contract": contract.to_dict(),
                                 "bullet": {**marker,
                                            "color": current_color,
                                            "space_after": round(space_after, 2)},
                                 "text_flow": flow,
                                 **({'scientific_text_overflow': overflow} if overflow else {})})
                adaptations.append({
                    "block_id": b["id"],
                    "action": DISTRIBUTED_ARROW_LIST,
                    "source": flow["source"],
                    "item_count": len(lines),
                    "bullet_style": current_style,
                    "bullet_color": current_color,
                    "bullet_glyph": bullet_glyph,
                    "bullet_face": bullet_face,
                    "distribution": flow["distribution"],
                })
                return
            if flow["mode"] == DISTRIBUTED_ARROW_LIST:
                if flow['source'] == 'explicit':
                    required_height = round(measured_list_height, 1)
                    issues.append(issue('SPLIT_REQUIRED', 'FAIL',
                        f"{b['id']}: explicit native list requires at least 520 px width and its measured content height; markers were not removed.",
                        n, b['id'], detector='geometric-preflight', required_size_px=[520, required_height],
                        available_size_px=box[2:], suggested_actions=['widen_region', 'increase_region_height', 'split_slide']))
                    return
                adaptations.append({
                    "block_id": b["id"],
                    "action": "text_flow_fallback",
                    "requested": DISTRIBUTED_ARROW_LIST,
                    "reason": "component_box_below_measured_minimum",
                })
                issues.append(issue("TEXT_FLOW_FALLBACK", "INFO",
                                    f"{b['id']} kept plain because its component box is narrower than 520 px or shorter than the measured list content",
                                    n, b["id"], detector="geometric-preflight"))
            label_h = (40 if comp["archetype"] == "figure-parameters" else 44) if label else 0
            text(b["id"]+":label", label, [box[0], box[1], box[2], label_h], "heading", 28, 24, 1)
            emphasis_color = theme.get("accent", DEFAULT_ACCENT) if b["id"] == visual_intent.get("emphasis") else None
            from .type_scale import display_floor, display_size
            size, floor = display_size(b, design), display_floor(b, design)
            if size:
                # A promoted object is the page's anchor: display role keeps its own floor instead
                # of being capped by the body size the rest of the page uses.
                text(b["id"], b["text"], [box[0], box[1]+label_h, box[2], box[3]-label_h], "display",
                     size, floor, 2, color=emphasis_color, inline_math=b.get('inline_math', False))
            else:
                text(b["id"], b["text"], [box[0], box[1]+label_h, box[2], box[3]-label_h], color=emphasis_color, inline_math=b.get('inline_math', False))
        def formula_flow(bs, box, max_columns=1, preferred_columns=1):
            try:
                plan = plan_formula_flow(bs, box, font_paths, comp['archetype'],
                    max_columns=max_columns, preferred_columns=preferred_columns,
                    body_size=type_sizes(design)['body'] if design else 28,
                    text_inset=56 if show_sequence else 0, preserve_terms=preserve_terms,
                    list_gap_ratio=list_gap_ratio, list_padding=(0, 0) if design else (28, 18),
                    bullet_style=bullet_style,
                    gap=24 if comp['archetype'] == 'figure-parameters' else 18)
            except FormulaCapacityError as error:
                issues.append(issue('FORMULA_CAPACITY', 'FAIL', str(error), n,
                    detector='geometric-preflight', confidence='HIGH',
                    suggested_fix='widen_text_column_or_split_slide', attempts=error.attempts,
                    available_width_px=box[2], available_height_px=box[3]))
                return
            by_id = {b['id']: b for b in bs}
            heights = plan.get('column_heights_px') or []
            if heights:
                offset = max(0.0, box[3]-max(heights))/2
                if offset > .5:
                    for item in plan['boxes'].values():
                        item[1] += offset
                    plan['vertical_offset_px'] = round(offset, 2)
            for bid in plan['reading_order']:
                block(by_id[bid], plan['boxes'][bid], plan['font_size_px'], 'left')
            adaptations.append({'action': 'formula_flow', 'region': list(box), **plan})

        def stack(bs, box):
            if not bs:
                return
            if any(b.get('component') == 'formula' or b.get('inline_math') for b in bs):
                formula_flow(bs, box)
                return
            from .academic_layout import block_height
            gap = 24 if comp['archetype'] == 'figure-parameters' else 18
            needs = [block_height(b, box[2], font_paths, comp['archetype'], design=design,
                                  list_gap_ratio=list_gap_ratio, bullet_style=bullet_style) for b in bs]
            total = sum(needs)+gap*(len(bs)-1)
            extra = max(0.0, box[3]-total)
            # Keep the content block at the top, share the remaining height as
            # breathing room above, between and below the blocks. This is the
            # same measured content, never a stretched text box.
            top_pad = extra/3
            gap_extra = (extra-2*top_pad)/max(1, len(bs)-1)
            cursor = box[1]+top_pad
            for b, need in zip(bs, needs):
                block(b, [box[0], cursor, box[2], need])
                cursor += need+gap+gap_extra
        def figure(f, box, k, caption_top=None):
            asset = assets[f["asset_id"]]
            schematic = (asset.get("origin") or "paper") == "generated"
            reference = asset.get("origin") == "reference"
            content = caption_with_source(f)
            caption_h, caption_lines = caption_measure(f, box[2], font_paths["font_file"])
            if f.get("caption_height") and content:
                # An explicit height still wins; it was measured by its author.
                caption_h = f["caption_height"]
                caption_lines = max(2, int(round((caption_h-8)/(f.get("caption_font_size", 22)*1.25))))
            h = box[3] - caption_h - 12
            if caption_top is not None:
                h = min(h, caption_top-12-box[1])
            scale = min(box[2]/asset["width"], h/asset["height"])
            w, h = asset["width"]*scale, asset["height"]*scale
            bbox = [box[0]+(box[2]-w)/2, box[1], w, h]
            if caption_top is not None:
                bbox[1] = caption_top-12-h
            eid = f"figure-{k}"
            min_extent = f.get("min_panel_extent", 220)
            actual_extent = min(w / f.get("panel_count", 1), h)
            element = {"id": eid, "kind": "image", "role": "reference" if reference else "evidence", "bbox": bbox,
                       "asset_id": f["asset_id"], "alt": f.get("alt", f["caption"]),
                       "min_panel_extent": min_extent,
                       "actual_panel_extent": actual_extent}
            if schematic:
                element["schematic"] = {"generator": asset.get("generator")}
            elif reference:
                element.update(origin="reference", reference_source=asset["reference_source"])
            else:
                element["source_figure"] = f["source_figure"]
            elements.append(element)
            if actual_extent < min_extent:
                if schematic:
                    issues.append(issue("SCHEMATIC_TOO_SMALL", "FAIL",
                                        f"Schematic extent {actual_extent:.1f}px is below {min_extent}px",
                                        n, eid, detector="geometric-preflight", confidence="HIGH"))
                elif reference:
                    issues.append(issue("REFERENCE_IMAGE_TOO_SMALL", "FAIL",
                                        f"Reference image extent {actual_extent:.1f}px is below {min_extent}px",
                                        n, eid, detector="geometric-preflight", confidence="HIGH",
                                        reference_source=asset["reference_source"]))
                else:
                    issues.append(issue("SCIENTIFIC_PANEL_TOO_SMALL", "FAIL",
                                        f"Scientific panel extent {actual_extent:.1f}px is below {min_extent}px",
                                        n, eid, detector="geometric-preflight", confidence="HIGH",
                                        source_figure=f["source_figure"]))
            caption_y = bbox[1]+bbox[3]+12
            if design and content and design['figure_treatment'] == 'ruled-caption':
                elements.append(rule(eid+':caption-rule', [box[0], caption_y-6, box[2], 1], design))
            # A real paper caption is often three or four lines; the strip was measured for exactly
            # that many lines, so the emitter must not clamp it back to two.
            text(eid+":caption", content, [box[0], caption_y, box[2], caption_h],
                 "caption", f.get("caption_font_size", 22), f.get("caption_font_floor", 20),
                 max(2, caption_lines))
            if schematic:
                issues.append(issue("SCHEMATIC_REVIEW", "REVIEW",
                                    "Confirm the drawn schematic matches the text it illustrates; "
                                    "it is not a paper figure",
                                    n, eid, detector="scientific-review", confidence="MEDIUM"))
            elif reference:
                issues.append(issue("REFERENCE_IMAGE_REVIEW", "REVIEW",
                                    "Confirm the crop and readability against its user-provided source; "
                                    "this image is not independently verified scientific evidence",
                                    n, eid, detector="source-review", confidence="MEDIUM",
                                    reference_source=asset["reference_source"]))
            else:
                issues.append(issue("SCIENTIFIC_PANEL_REVIEW", "REVIEW",
                                    "Confirm scientific panel labels and evidence fidelity",
                                    n, eid, detector="scientific-review", confidence="MEDIUM"))
        # A drawn schematic is not evidence that has to sit beside its text: it gets the width of
        # the page and the reader's eye goes text -> diagram -> caption, top to bottom.
        schematic_only = (len(figs) == 1 and
                          (assets[figs[0]["asset_id"]].get("origin") or "paper") == "generated")
        def schematic_band(bs, f):
            face = ImageFont.truetype(font_paths["font_file"], 28)
            if len(bs) == 2:
                # Two short paragraphs read as one line each of context: side by side they leave the
                # height to the diagram instead of stacking into a wall above it.
                rows = [break_lines(item["text"], face, 568) for item in bs]
                band = max((len(lines) for lines in rows), default=0) * 35
                for k, (item, _) in enumerate(zip(bs, rows)):
                    block(item, [56 + k * 600, top, 568, band])
                cursor = top + band + 18
            else:
                rows = [break_lines(item["text"], face, 1168) for item in bs]
                natural = sum(len(lines) for lines in rows) * 35 + 18 * max(len(bs) - 1, 0)
                band = min(natural, bh * .45)
                cursor = top
                total = max(sum(len(lines) for lines in rows), 1)
                for item, lines in zip(bs, rows):
                    height = band * len(lines) / total
                    block(item, [56, cursor, 1168, height])
                    cursor += height + 18
            figure(f, [56, cursor, 1168, bottom - cursor], 1)

        def native_graphic(region, graphic=None):
            graphic = graphic or comp["graphics"][0]
            try:
                graphic_elements = compile_graphic(graphic, region, theme, font_paths)
            except ValueError as error:
                graphic_elements = []
                issues.append(issue(getattr(error, "rule", "GRAPHIC_CAPACITY"), "FAIL", str(error), n, graphic["id"],
                                    detector="geometric-preflight"))
            for element in graphic_elements:
                if element["kind"] in ("shape", "connector"):
                    elements.append(element)
                    continue
                before = len(elements)
                text(element["id"], element["text"], element["bbox"], element["role"],
                     element["font_size"], min(24, element["font_size"]), element["max_lines"], "middle",
                     element["color"], align="center")
                if len(elements) > before:
                    elements[-1].update({key: element[key] for key in
                        ("graphic_id", "node_id", "container_id", "overlap_group", "graphic_region", "edge_id")
                        if key in element})
            node_count, edge_count = graphic_counts(graphic)
            adaptations.append({"action": "native_graphic", "graphic_id": graphic["id"],
                                "region": region, "node_count": node_count,
                                "edge_count": edge_count})
            issues.append(issue("SCHEMATIC_REVIEW", "REVIEW",
                                ("Confirm the process order and labels match the scientific explanation; "
                                 "this is a generated schematic, not a paper figure")
                                if graphic['type'] in ('process', 'dag') else
                                "Confirm component labels, explicit relationships and evidence/hypothesis distinctions; "
                                "generated graphics do not establish scientific correctness",
                                n, graphic["id"], detector="scientific-review", confidence="MEDIUM"))
        has_formulas = any(b.get('component') == 'formula' or b.get('inline_math') for b in blocks)
        proposal = None if comp.get('layout_tree') or visual_plan or schematic_only or comp.get('graphics') or has_formulas else (proposals or {}).get(slide['id'])
        if comp.get('layout_tree'):
            from .layout_tree import LayoutTreeError, compile_regions
            checkpoints = [len(elements), len(issues), len(adaptations)]
            try:
                plan = compile_regions(comp, [56, top, 1168, bh], assets, font_paths, theme, preserve_terms,
                                       list_gap_ratio, (0, 0) if design else (28, 18), bullet_style,
                                       design=design,
                                       formula_sizes=formula_sizes if equation_page else None)
                balance_shift = (plan.get('balanced') or {}).get('shift_px', 0.)
                if balance_shift > .5:
                    adaptations.append({'action': 'vertical_balance', **plan['balanced']})
                by_id = {b['id']: b for b in blocks}
                graphics_by_id = {g['id']: g for g in comp.get('graphics', [])}
                charts_by_id = {c['id']: c for c in comp.get('charts', [])}
                for entry in plan['nodes']:
                    first, issue_start = len(elements), len(issues)
                    if entry['type'] == 'panel':
                        title_id = 'region:'+entry['node_id']+':title'
                        style = entry.get('frame')
                        if style:
                            from .container_frames import rectangle
                            elements.append(rectangle('region:'+entry['node_id']+':frame', entry['bbox'], style, []))
                            if style.get('title_fill', 'none') != 'none':
                                elements.append({'id': 'region:'+entry['node_id']+':title-band', 'kind': 'shape',
                                    'role': 'decoration', 'bbox': entry['title_band_bbox'],
                                    'geometry': entry.get('title_band_geometry', 'rect'),
                                    'fill': style['title_fill'], 'line': 'none', 'line_width': 0,
                                    'visual_decoration': True, 'frame_members': [title_id],
                                    'frame_growth_inset': style['border'].get('width', 1.)})
                        text('region:'+entry['node_id']+':title', entry['title'], entry['title_bbox'],
                             'heading', 28, 24, max(2, int(entry['title_bbox'][3]/30)),
                             color=style.get('title_color') if style else None,
                             align=entry.get('title_align') or (style.get('title_align') if style else None))
                    elif entry['type'] == 'block':
                        block(by_id[entry['ref']], entry['bbox'], formula_align='left')
                    elif entry['type'] == 'figure':
                        figure(figs[entry['ref']], entry['bbox'], entry['ref']+1)
                    elif entry['type'] == 'graphic':
                        native_graphic(entry['bbox'], graphics_by_id[entry['ref']])
                    elif entry['type'] == 'chart':
                        from .chart_render import ChartLayoutError, compile_chart
                        chart = charts_by_id[entry['ref']]
                        try:
                            rendered = compile_chart(chart, entry['bbox'], theme, font_paths)
                        except ChartLayoutError as error:
                            issues.append(issue(error.rule, 'FAIL', str(error), n, chart['id'],
                                                detector='geometric-preflight',
                                                component=entry['component']))
                            continue
                        for element in rendered:
                            if element['kind'] in ('shape', 'connector'):
                                elements.append(element)
                            else:
                                before = len(elements)
                                text(element['id'], element['text'], element['bbox'], element['role'],
                                     element['font_size'],
                                     20 if element['role'] == 'caption' else 24,
                                     element['max_lines'], 'middle', element['color'],
                                     align=element.get('align'))
                                if len(elements) > before:
                                    elements[-1].update({key: element[key] for key in
                                        ('graphic_id', 'overlap_group', 'node_id') if key in element})
                        issues.append(issue(
                            'CHART_DATA_REVIEW' if chart.get('basis') == 'evidence' else 'CHART_ILLUSTRATIVE_REVIEW',
                            'REVIEW',
                            'Confirm every plotted point against the cited evidence; the compiler checked '
                            'the chart structure, not the paper text.' if chart.get('basis') == 'evidence'
                            else 'This chart is an illustrative schematic, not measured data; confirm the '
                                 '示意 badge is visible in the rendered slide.',
                            n, chart['id'], detector='scientific-review', confidence='MEDIUM'))
                    elif entry['type'] == 'table':
                        from .native_table import compile_table
                        table = next(t for t in comp['tables'] if t['id'] == entry['ref'])
                        try:
                            rendered = compile_table(table, entry['bbox'], font_paths, theme, preserve_terms)
                        except LayoutTreeError as error:
                            error.detail['component'] = entry['component']
                            raise
                        elements.append(rendered)
                        issues.append(issue('TABLE_CONTENT_REVIEW', 'REVIEW',
                            'Confirm every table value, scientific term, unit and source reference.', n, rendered['id'],
                            detector='scientific-review', confidence='MEDIUM'))
                        if any(c.get('measured_exact') is False for c in rendered['cells']):
                            issues.append(issue('FORMULA_MEASURE_APPROXIMATE', 'REVIEW',
                                'Native table formulas use conservative structural metrics; verify cell bounds in PowerPoint.',
                                n, rendered['id'], detector='geometric-preflight', confidence='LOW', font_metrics='heuristic'))
                        if any(c.get('inline_formula_count', 0) for c in rendered['cells']):
                            issues.append(issue('INLINE_MATH_MEASUREMENT_REVIEW', 'REVIEW',
                                'Verify inline formula baselines and measured line heights in native table cells.',
                                n, rendered['id'], detector='geometric-preflight', confidence='LOW'))
                        if rendered.get('scientific_text_overflow'):
                            issues.append(issue('SCIENTIFIC_TEXT_OVERFLOW', 'REVIEW',
                                'Native table retains complete scientific terminology beyond its nominal region.',
                                n, rendered['id'], detector='geometric-preflight'))
                    for element in elements[first:]:
                        element.update(layout_component=entry['component'], layout_region=entry['bbox'])
                        ex, ey, ew, eh = element['bbox']
                        rx, ry, rw, rh = entry['bbox']
                        if (not element.get('scientific_text_overflow') and
                            (ex < rx-.1 or ey < ry-.1 or ex+ew > rx+rw+.1 or ey+eh > ry+rh+.1)):
                            issues.append(issue('REGION_CONTENT_OUT_OF_BOUNDS', 'FAIL',
                                'Rendered component exceeds its assigned compiler region.', n, element['id'],
                                detector='geometric-preflight', component=entry['component']))
                    failures = [item for item in issues[issue_start:] if item['severity'] == 'FAIL']
                    if failures:
                        raise LayoutTreeError(entry['component'], 'COMPONENT_RENDER_FAILED',
                            'A component failed an existing renderer gate after region allocation.',
                            [entry['bbox'][2], entry['requirements']['min_height_px']], entry['bbox'][2:],
                            cause=failures[0]['message'])
                # Grow opted-in frames bottom-up when preserve-terms releases complete text.
                # Each frame only exempts its own descendants from overlap checks.
                from .container_frames import grow_frame, stroke_width
                for entry in reversed(plan['nodes']):
                    if not entry.get('frame'):
                        continue
                    prefix, eid = entry['component'], 'region:'+entry['node_id']
                    framed = next(e for e in elements if e['id'] == eid+':frame')
                    title_element = next(e for e in elements if e['id'] == eid+':title')
                    band = next((e for e in elements if e['id'] == eid+':title-band'), None)
                    # A chip is a label around its text, not a row that can absorb extra height:
                    # growing it would stretch the pill, so a chip keeps its measured size.
                    if band and not entry.get('title_band_geometry'):
                        needed = title_element['bbox'][1]+title_element['bbox'][3]+entry['padding_px']-band['bbox'][1]
                        if needed > band['bbox'][3]+.1:
                            band['bbox'] = [*band['bbox'][:3], needed]
                            band['scientific_text_overflow'] = {'policy': 'preserve-terms'}
                    members = [e for e in elements if e is not framed and
                               (e.get('layout_component') == prefix or e.get('layout_component', '').startswith(prefix+'.'))]
                    framed['frame_members'] = [e['id'] for e in members]
                    outer = grow_frame(framed, entry['bbox'], members,
                                       entry['padding_px']+stroke_width(entry['frame']))
                    entry['frame_bbox'] = outer
                    framed['layout_region'] = outer
                    if framed.get('scientific_text_overflow'):
                        issues.append(issue('FRAME_EXPANDED_FOR_TERMS', 'REVIEW',
                            'Native frame expanded with complete scientific content; inspect neighbouring regions.',
                            n, framed['id'], detector='geometric-preflight', component=prefix,
                            original_bbox=entry['bbox'], expanded_bbox=outer))
                adaptations.append({'action': 'layout_tree', **plan})
                for entry in plan['nodes']:
                    if (entry.get('underfill') and
                            balance_shift < entry['underfill']['underfill_px']*.5):
                        # The balance nudge is capped at 32 px; a 300 px gap is not explained by it.
                        # Suppress the report only when the shift actually absorbed most of the gap.
                        issues.append(issue('PAGE_UNDERFILL', 'REVIEW',
                            'A stack leaves more than 15% of its allocated height unused. '
                            'Review intentional whitespace or adjust relative weights / stack alignment.',
                            n, 'region:'+entry['node_id'], detector='geometric-preflight',
                            component=entry['component'], **entry['underfill']))
                    if sparse_text_page(entry, elements):
                        filled = entry['requirements']['preferred_height_px']/entry['bbox'][3]
                        # A stack of one-line statements in a half-empty region is the
                        # document look: the page has structure but no composition.
                        issues.append(issue('SPARSE_TEXT_PAGE', 'REVIEW',
                            f'The text on this page fills {filled*100:.0f}% of its region. Short '
                            'statements stacked in one column read as a document; give the page a '
                            'composition — two columns, one display-size statement, or numbered '
                            'points — or split it.', n, 'region:'+entry['node_id'],
                            detector='geometric-preflight', filled_ratio=round(filled, 3),
                            suggested_actions=['text_columns', 'statement', 'numbered_points',
                                               'split_slide']))
                adaptations.append({'action': 'layout_provider', 'provider': 'compiler',
                                    'status': 'COMPILER_OWNED', 'reason': 'recursive_regions'})
            except LayoutTreeError as error:
                del elements[checkpoints[0]:]
                del adaptations[checkpoints[2]:]
                issues.append(issue(error.detail['code'], 'FAIL', str(error), n,
                    detector='geometric-preflight', slide_id=slide['id'],
                    **{key: value for key, value in error.detail.items() if key not in ('code', 'message')}))
        elif visual_plan:
            from .academic_layout import candidates
            best_failures, attempts = [], []
            for plan in candidates(slide, [56, top, 1168, bh], assets, font_paths, design,
                                   list_gap_ratio=list_gap_ratio, bullet_style=bullet_style):
                boxes = [*plan['blocks'], *plan['figures']]
                boxes += [plan[key] for key in ('graphic', 'emphasis') if plan.get(key) is not None]
                if any(min(box[2:]) <= 0 for box in boxes):
                    attempts.append({'pattern': plan['pattern'], 'rules': ['INVALID_REGION']})
                    continue
                checkpoints = [len(values) for values in (elements, issues, adaptations, slide_formulas)]
                for b, box in zip(blocks, plan['blocks']):
                    block(b, box)
                for k, (f, box) in enumerate(zip(figs, plan['figures']), 1):
                    figure(f, box, k, plan.get('caption_top'))
                if plan.get('graphic'):
                    native_graphic(plan['graphic'])
                if plan.get('emphasis'):
                    text('visual:emphasis', visual_plan['emphasis']['text'], plan['emphasis'],
                         'body', 28, 24, 3, color=theme['accent'])
                failures = [finding for finding in issues[checkpoints[1]:] if finding['severity'] == 'FAIL']
                failures += geometry_issues(elements, n)
                if len({e['id'] for e in elements}) != len(elements):
                    failures.append(issue('VISUAL_PLAN_ID_COLLISION', 'FAIL',
                        'Page object names must be unique', n, detector='geometric-preflight'))
                failures += [finding for finding in issues[:checkpoints[1]]
                             if finding['severity'] == 'FAIL' and finding.get('slide') == n]
                attempts.append({'pattern': plan['pattern'], 'rules': sorted({i['rule'] for i in failures})})
                if not failures:
                    adaptations.append({'action': 'scientific_visual_plan', 'visual_job': visual_plan['visual_job'],
                        'requested': visual_plan, 'selected': plan, 'attempts': attempts})
                    adaptations.append({'action': 'layout_provider', 'provider': 'compiler',
                                        'status': 'COMPILER_FALLBACK', 'reason': 'scientific_visual_plan'})
                    break
                if not best_failures or len(failures) < len(best_failures):
                    best_failures = failures
                for values, checkpoint in zip((elements, issues, adaptations, slide_formulas), checkpoints):
                    del values[checkpoint:]
            else:
                issues.extend(best_failures)
                issues.append(issue('VISUAL_PLAN_UNSATISFIABLE', 'FAIL',
                    'No candidate satisfies the visual plan and existing content, panel, typography and collision gates. Replan this page.',
                    n, detector='geometric-preflight', attempted_compositions=attempts))
        elif family == "graphic":
            native_graphic([56, top, 1168, bh])
        elif comp.get('graphics'):
            # Try a small set of whole-page compositions using the existing emitters. Failed
            # attempts never leak partial content, warnings or text adaptations into the result.
            best_failures, attempted = [], 0
            for plan in graphic_page_regions(comp, [56, top, 1168, bh], assets, font_paths, design=design,
                    list_gap_ratio=list_gap_ratio, list_padding=(0, 0) if design else (28, 18),
                    bullet_style=bullet_style):
                boxes = [plan['graphic'], *plan['blocks'], *plan['figures']]
                if any(min(box[2:]) <= 0 for box in boxes):
                    continue
                attempted += 1
                checkpoints = [len(values) for values in (elements, issues, adaptations, slide_formulas)]
                for b, box in zip(blocks, plan['blocks']):
                    block(b, box)
                for k, (f, box) in enumerate(zip(figs, plan['figures']), 1):
                    figure(f, box, k)
                native_graphic(plan['graphic'])
                failures = [finding for finding in issues[checkpoints[1]:] if finding['severity'] == 'FAIL']
                if not failures:
                    adaptations.append({'action': 'graphic_composition', 'pattern': plan['pattern'],
                                        'block_ids': [b['id'] for b in blocks],
                                        'figure_ids': [f'figure-{k+1}' for k in range(len(figs))],
                                        'graphic_id': comp['graphics'][0]['id']})
                    adaptations.append({'action': 'layout_provider', 'provider': 'compiler',
                                        'status': 'COMPILER_FALLBACK', 'reason': 'native_graphic_composition'})
                    break
                if not best_failures or len(failures) < len(best_failures):
                    best_failures = failures
                for values, checkpoint in zip((elements, issues, adaptations, slide_formulas), checkpoints):
                    del values[checkpoint:]
            else:
                issues.extend(best_failures)
                issues.append(issue('GRAPHIC_PAGE_CAPACITY', 'FAIL',
                    'The graphic, context and source figure/caption cannot share this page above '
                    'their size floors. Try composite-research with a vertical layout_tree stack '
                    '(graphic + blocks) before splitting; if the measured tree still cannot fit, '
                    'split the page. No content was shortened or dropped.',
                    n, comp['graphics'][0]['id'], detector='geometric-preflight',
                    attempted_compositions=attempted))
                issues.append(issue('SCHEMATIC_REVIEW', 'REVIEW',
                    'Confirm the declared graphic relationships match the scientific evidence.',
                    n, comp['graphics'][0]['id'], detector='scientific-review', confidence='MEDIUM'))
        elif proposal:
            supplied = proposal['units']
            expected = [b['id'] for b in blocks] + [f'figure-{k+1}' for k in range(len(figs))]
            if len(expected) != len(set(expected)) or set(supplied) != set(expected):
                raise ValueError('Provider unit identities must match the canonical slide exactly')
            if family == 'evidence':
                for col, role in enumerate(('direct-evidence', 'hypothesis')):
                    text(role+':heading', '直接证据' if col == 0 else '假设（未证实）',
                         [56+col*600, top, 568, 44], 'heading', 28, 24, 1)
            for b in blocks:
                block(b, supplied[b['id']]['bbox'])
            for k, f in enumerate(figs, 1):
                group = supplied[f'figure-{k}']
                declared = group.get('caption_height', f.get('caption_height'))
                figure({**f, **({'caption_height': declared} if declared else {})},
                       group['bbox'], k)
            adaptations.append({'action': 'layout_provider',
                                'provider': proposal.get('provider', 'provider'),
                                'status': proposal['status']})
        elif schematic_only:
            schematic_band(blocks, figs[0])
        elif not figs and not show_sequence and family != 'evidence' and (has_formulas or family == 'equations'):
            formula_flow(blocks, [56, top, 1168, bh], max_columns=2,
                         preferred_columns=2 if comp['archetype'] == 'metric-comparison' else 1)
        elif family in ("figure-left", "figure-right") and figs:
            base_text = 440 if family == "figure-left" else 460
            txt_w = formula_column_width(blocks, font_paths["bold_font_file"], base_text, 616)
            fig_w = 1168 - 32 - txt_w
            if family == "figure-left":
                fig_x, txt_x = 56, 56 + fig_w + 32
            else:
                txt_x, fig_x = 56, 56 + txt_w + 32
            figure(figs[0], [fig_x, top, fig_w, bh], 1)
            stack(blocks, [txt_x, top, txt_w, bh])
        elif show_sequence and not figs:
            stack(blocks, [280, top, 720, bh])
        elif family == "process" and figs and len(blocks) >= 4:
            # The method slide needs both a legible process summary and a readable
            # source panel. A four-row left column frees the right half for the
            # original Fig.3a panel instead of squeezing it into a shallow strip.
            left_x, left_w = 56, 520
            row_h, row_gap = 75, 5
            for k, b in enumerate(blocks[:4]):
                y = top + k * (row_h + row_gap)
                text(b["id"]+":label", b.get("label", ""), [left_x, y, left_w, 32],
                     "heading", 24, 24, 1)
                text(b["id"], b["text"], [left_x, y+32, left_w, row_h-32],
                     "body", 24, 24, 1)
            figure(figs[0], [650, top, 574, bh], 1)
        elif slide["id"] == "s07-contact" and figs:
            # Keep the two numeric callouts compact so the two original Fig.3e/f
            # panels can occupy most of the evidence area at readable size.
            for k, b in enumerate(blocks[:2]):
                x = 56 + k * 600
                text(b["id"]+":label", b.get("label", ""), [x, top, 568, 32],
                     "heading", 24, 24, 1)
                text(b["id"], b["text"], [x, top+32, 568, 38],
                     "body", 26, 22, 1)
            fw = (1168-32*(len(figs)-1))/len(figs)
            for k, f in enumerate(figs):
                figure(f, [56+k*(fw+32), top+70, fw, bottom-(top+70)], k+1)
        elif family == "dual" and figs:
            # Dual scientific figures get compact native callouts and a hard
            # 240px evidence band. This avoids the former 154px thumbnails.
            for k, b in enumerate(blocks[:2]):
                x = 56 + k * 600
                text(b["id"]+":label", b.get("label", ""), [x, top, 568, 30],
                     "heading", 24, 24, 1)
                text(b["id"], b["text"], [x, top+30, 568, 34],
                     "body", 24, 24, 1)
            fw = (1168-32*(len(figs)-1))/len(figs)
            for k, f in enumerate(figs):
                figure(f, [56+k*(fw+32), top+70, fw, bottom-(top+70)], k+1)
        elif family == "evidence":
            for col, role in enumerate(("direct-evidence", "hypothesis")):
                x = 56 + col*600
                text(role+":heading", "直接证据" if col == 0 else "假设（未证实）",
                     [x, top, 568, 44], "heading", 28, 24, 1)
                stack([b for b in blocks if b["component"] == role], [x, top+56, 568, bh-56])
        else:
            if blocks:
                w = (1168-32*(len(blocks)-1))/len(blocks)
                column_start = len(elements)
                for k, b in enumerate(blocks):
                    block(b, [56+k*(w+32), top, w, bh])
                # Flat columns otherwise pin every label to the body top and
                # leave the lower band empty. Centre the measured content in
                # the body band without enlarging or re-wrapping it.
                if len(blocks) > 1 and not figs and not comp.get('graphics') and not show_sequence:
                    created = elements[column_start:]
                    visible = [e for e in created if e['kind'] in ('text', 'list', 'math')
                               and e['role'] in ('heading', 'body', 'formula')]
                    if visible:
                        content_top = min(e['bbox'][1] for e in visible)
                        content_bottom = max(text_visible_bottom(e) for e in visible)
                        empty = bh-(content_bottom-content_top)
                        if empty > 60:
                            shift = empty/2
                            limit = top+bh
                            for e in created:
                                e['bbox'][1] += shift
                                e['bbox'][3] = max(1, min(e['bbox'][3], limit-e['bbox'][1]))
        if show_sequence:
            rows = [next((e for e in elements if e["id"] == b["id"]), None) for b in blocks]
            if all(rows):
                rail_x = rows[0]["bbox"][0] - 56
                centers = [row["bbox"][1] + 18 for row in rows]
                accent = theme.get("accent", DEFAULT_ACCENT)
                elements.append({"id": "sequence:spine", "kind": "shape",
                    "role": "decoration", "bbox": [rail_x+25, centers[0], 2, centers[-1]-centers[0]],
                    "geometry": "rect", "fill": "#B9CCD8", "line": "none",
                    "collision_mode": "container"})
                for index, row in enumerate(rows, 1):
                    badge = [rail_x+10, row["bbox"][1]+2, 32, 32]
                    elements.append({"id": f"sequence:step:{index}", "kind": "shape",
                        "role": "decoration", "bbox": badge, "geometry": "ellipse",
                        "fill": accent, "line": "none", "collision_mode": "container"})
                    text(f"sequence:number:{index}", str(index), badge, "badge", 20, 20, 1,
                         "middle", "#FFFFFF")
                adaptations.append({"action": "sequence_rail",
                    "source": "visual_intent" if visual_intent else "legacy_roles",
                    "block_ids": [b["id"] for b in blocks]})
        if family in ('columns', 'equations') and not figs and not visible_caveats and len(blocks) >= 3:
            notice = lower_whitespace_issue(elements, n, top, bottom)
            if notice:
                issues.append(notice)
        page_furniture_elements(elements, text, n, slide, ir.get('presentation') or {}, design, furniture)
        if (comp.get('layout_tree') or comp.get('graphics') or design) and len({e['id'] for e in elements}) != len(elements):
            issues.append(issue('GRAPHIC_ID_COLLISION' if comp.get('graphics') else 'VISUAL_PLAN_ID_COLLISION',
                                'FAIL', 'Page object names must be unique',
                                n, detector='geometric-preflight'))
        # Diagram labels are their own type scale; this rule is about running body copy on the page.
        body_sizes = sorted({round(e['contract']['font_size'], 1) for e in elements
                             if e.get('kind') == 'text' and e.get('role') == 'body' and e.get('contract')
                             and not e['id'].startswith('graphic:')})
        if len(body_sizes) > 1:
            # Body copy on one page is one size. A fitted block may shrink to avoid a hard failure,
            # but then the page is reported so the composition can be reflowed instead of shipping
            # three body sizes that read as accidental emphasis.
            issues.append(issue('BODY_SIZE_VARIANCE', 'REVIEW',
                f'Body copy uses {len(body_sizes)} sizes on one page ({", ".join(f"{s*.75:.1f}" for s in body_sizes)} pt); '
                'reflow or split the page so body text keeps one size and the page anchor stays distinct.',
                n, detector='geometric-preflight', body_font_px=body_sizes,
                suggested_actions=['reflow_region', 'split_slide']))
        for b in blocks:
            if (b.get('text_flow') == DISTRIBUTED_ARROW_LIST
                    and not any(e['id'] == b['id'] and e['kind'] == 'list' for e in elements)
                    and not any(i['severity'] == 'FAIL' and i.get('slide') == n for i in issues)):
                issues.append(issue('SPLIT_REQUIRED', 'FAIL',
                    f"{b['id']}: this composition cannot realize the explicit native list; choose a wider layout or split the page.",
                    n, b['id'], detector='geometric-preflight', suggested_actions=['widen_region', 'split_slide']))
        issues.extend(geometry_issues(elements, n))
        if visual_plan and any(i['severity'] == 'FAIL' and i.get('slide') == n for i in issues) and not any(
                i['rule'] == 'VISUAL_PLAN_UNSATISFIABLE' and i.get('slide') == n for i in issues):
            issues.append(issue('VISUAL_PLAN_UNSATISFIABLE', 'FAIL',
                'The selected visual composition failed a page gate; replan without changing scientific content.',
                n, detector='geometric-preflight'))
        notes = sem["speaker_notes"]
        notes_only = [*(sem.get("run_notes") or []), *moved_caveats]
        if notes_only:
            # Provenance stays with the deck; it just stops being projected.
            notes += "\n\n备注（不投屏）：" + "；".join(notes_only)
        if footer:
            notes += "\nEvidence: " + footer
        slides.append({"id": slide["id"],
                       "background": "#FFFFFF" if templated else theme.get("background", "#FFFFFF"),
                       "notes": notes,
                       "elements": elements, "adaptation_log": adaptations})
    presentation = ir.get('presentation') or {}
    agenda = presentation.get('agenda')
    sections = agenda_sections(ir)
    if sections and not agenda:
        # Section labels only steer the contents page; without one they are invisible metadata.
        issues.append(issue('SECTION_LABELS_UNUSED', 'INFO',
            f'{len(sections)} section labels are declared but presentation.agenda is off, so nothing '
            'on the page shows them. Add an agenda or drop the labels.', detector='geometric-preflight'))
    if agenda:
        sections = agenda_sections(ir)
        if not design:
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
                        number_element['text'] = str(index+1)
            slides.insert(1, agenda_slide(agenda if isinstance(agenda, dict) else {},
                                          sections, theme, font_paths, design,
                                          2 if presentation.get('page_numbers', True) else None,
                                          furniture, footer_text=presentation.get('footer')))
            if len(sections) > AGENDA_MAX_SECTIONS:
                issues.append(issue('AGENDA_TRUNCATED', 'REVIEW',
                    f'presentation.section declares {len(sections)} sections; the contents page holds '
                    f'{AGENDA_MAX_SECTIONS}. Merge sections or split the deck.', detector='geometric-preflight'))
    if _retry and not design and not preserve_terms and any(i["rule"] == "SPLIT_REQUIRED" for i in issues):
        import copy
        alternative = copy.deepcopy(ir)
        alternative.setdefault("presentation", {})["frame_variant"] = "spacious"
        retry_layout, retry_issues = compile_deck(alternative, base, _retry=False, proposals=proposals)
        if retry_layout and not any(i["severity"] == "FAIL" for i in retry_issues):
            retry_layout["ir_sha256"] = digest(ir)
            retry_layout["selected_variants"] = {str(n): "spacious" for n in range(1, len(ir["slides"])+1)}
            return retry_layout, retry_issues
    return {"schema_version": "2.0", "ir_sha256": digest(ir), "slide_size": [WIDTH, HEIGHT],
            "deck_frame_variant": deck_frame,
            "frame_variant_overrides": {str(n): deck_frame for n, slide in enumerate(ir["slides"], 1)
                if slide["presentation"].get("variant", "default") != deck_frame},
            "assets": assets, "font_hashes": {p: file_hash(Path(p)) for p in font_paths.values()},
            "resolved_font_family": theme['font_family'],
            "background_image": (assets[background_key]["path"] if background_key else None),
            **({'academic_design': design} if design else {}),
            "slides": slides}, issues
