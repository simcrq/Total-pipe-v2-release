"""Deterministic layout compiler. No LLM calls, mutation, or content rewriting."""
from dataclasses import replace
from pathlib import Path
import re
from PIL import Image, ImageFont
from . import audience
from .catalog import ARCHETYPES
from .capacity import FORMULA_GAP, FORMULA_LABEL_MAX, FORMULA_SIZES
from .formula_layout import formula_groups, plan_formula_flow, FormulaCapacityError
from .contracts import TextBoxContract, digest, file_hash, issue
from .ir import validate
from .graphic_layout import (compile_graphic, graphic_counts, graphic_obstacle_collisions,
                             graphic_texts, intentional_overlap)
from .text_flow import DISTRIBUTED_ARROW_LIST, select_text_flow
from .visual_design import (header_decoration, header_layout, preserve_scientific_terms,
                            resolve_design, rule, type_sizes)

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
CAPTION_FONT_SIZE = 22

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
    lines = break_lines(caption, load_font_file(font_file, size), max(1, width))
    return max(34.0, len(lines) * size * 1.25 + 8)


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
        return 132, (632 if audience.visible_caveats(slide) else 672)
    spacious = frame == "spacious"
    return (236 if spacious else 260), body_bottom(slide, family, spacious)

# Which marker a deck gets when it does not say. A deck keeps one style, so this is decided once
# from the dominant list semantics: a procedure reads as arrows, a set of claims as open squares,
# settled points as filled squares, and anything mixed falls back to the square PowerPoint itself
# uses as its second list style.
BULLET_COMPONENT_STYLE = {
    "process-step": "arrow", "method": "arrow",
    "conclusion": "square", "result": "square",
    "hypothesis": "open_square", "caveat": "open_square", "comparison": "open_square",
}


def choose_bullet_style(ir):
    """One list-marker style for the whole deck: explicit, else the dominant list semantics."""
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
        return "square"
    top = max(sorted(counts), key=lambda component: counts[component])
    return BULLET_COMPONENT_STYLE.get(top, "square")


def fit_list_items(items, width, font_file, size, floor, max_lines):
    """Break every item at one shared font size; ``None`` when the markers cannot fit the box."""
    for candidate in range(int(size), int(floor) - 1, -1):
        face = ImageFont.truetype(font_file, candidate)
        lines = [break_lines(item, face, width) for item in items]
        if all(len(item_lines) <= max_lines for item_lines in lines):
            return lines, candidate
    return None


def text_floor_height(text, width, font_file, floor=24, max_lines=10):
    """Height of ``text`` at the 18 pt floor, or None when it cannot fit in ``max_lines``."""
    face = ImageFont.truetype(font_file, floor)
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


def formula_widths(text):
    """Measured metrics at every allowed size, widest (the floor) last."""
    from totalpipe_layout.formula import measure, parse
    ast = parse(text)
    return {size: measure(ast, size) for size in FORMULA_SIZES}


def formula_fit(text, width):
    """Metrics of the largest allowed size whose measured width fits ``width``, else None."""
    widths = formula_widths(text)
    for size in FORMULA_SIZES:
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
    if composition.get("graphics"):
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


TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/\\-]*(?:%|[×x])?|[^\S\n]+|.")
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
    line_count = len(element["text"].split("\n"))
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


def graphic_page_regions(composition, region, assets, font_paths, visual_plan=None):
    """Finite page-level candidates; graph internals stay with compile_graphic.

    Measure context at the existing font floor and keep each image with its caption.
    The real block/figure/graphic emitters still make the final capacity decision.
    """
    x, y, width, height = region
    blocks, figures = composition['blocks'], composition['figure_refs']
    gap = 24.0
    if visual_plan and not figures:
        from .academic_layout import graphic_without_evidence
        yield from graphic_without_evidence(composition, region, font_paths, visual_plan)
        return

    def need(block, w):
        label = block.get('label', '')
        if block.get('component') == 'formula':
            label_w = formula_label_width(label, font_paths['bold_font_file'])
            metrics = formula_fit(block['text'], w-20-(label_w+12 if label_w else 0))
            return max(30 if label else 0, metrics.height+12) if metrics else 10000
        label_h = (40 if composition['archetype'] == 'figure-parameters' else 44) if label else 0
        return label_h + (text_floor_height(block['text'], w, font_paths['font_file']) or 10000)

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
    ch = (ref.get('caption_height') or caption_height(ref['caption'], figure_w,
          font_paths['font_file'], ref.get('caption_font_size', 22))) if ref['caption'] else 0
    lower_h = max(context_h, image_h+ch+12)
    lower_y = y+height-lower_h
    shares = ratios(visual_plan.get('graphic_width_ratio', 1.0), .4, 1.0) if visual_plan else [1.0]
    for graphic_share in shares:
        yield {'pattern': 'graphic-above-evidence',
               'blocks': [[bx, lower_y+by, bw, bh] for bx, by, bw, bh in context],
               'figures': [[figure_x, lower_y, figure_w, lower_h]],
               'graphic': [x+(width-width*graphic_share)/2, y, width*graphic_share, height-lower_h-gap],
               **({'graphic_width_ratio': graphic_share} if visual_plan else {})}


def geometry_issues(elements, number):
    """The same page gates run on every candidate and on the final composition."""
    findings = []
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
    # Fonts are resolved by the platform, not by the deck's author: a theme may name a file from
    # another operating system, and a deck that cannot find its declared face is still deliverable in
    # a substituted one. Only "no font anywhere" is a FAIL.
    from .fonts import resolve_bullet, resolve_theme_fonts
    # Every character the deck will set, so the resolver can reject a face that cannot draw them.
    # The compiler's own strings count too: the evidence family draws 直接证据 / 假设（未证实） and the
    # header separator ·, none of which appear in the Deck IR. The list marker is left out of the
    # sample on purpose: it has its own face (a:buFont) and letting it decide the body face would
    # push a Chinese deck from a sans face to a symbol one.
    compiler_strings = '直接证据假设（未证实）·0123456789'
    text_sample = compiler_strings + "".join(
        [str(value) for slide in ir["slides"]
         for value in (slide["semantic"].get("title", ""), slide["semantic"].get("purpose", ""),
                       slide["semantic"].get("takeaway", ""), slide["semantic"].get("speaker_notes", ""))]
        + [block.get("text", "")+block.get("label", "") for slide in ir["slides"]
           for block in slide["composition"]["blocks"]]
        + [figure.get("caption", "") for slide in ir["slides"]
           for figure in slide["composition"]["figure_refs"]]
        + [value for slide in ir["slides"] for graphic in slide["composition"].get("graphics", [])
           for _, value in graphic_texts(graphic)])
    try:
        regular_font, bold_font, font_notes = resolve_theme_fonts(theme, base, text_sample)
    except (FileNotFoundError, OSError) as error:
        issues.append(issue("FONT_UNAVAILABLE", "FAIL", str(error), detector="geometric-preflight"))
        return None, issues
    font_paths = {"font_file": regular_font, "bold_font_file": bold_font}
    # Characters the deck-level font note already covers: repeating them per text element turns one
    # real finding into fifty identical REVIEWs and buries everything else in the report.
    deck_gap = set()
    for note in font_notes:
        if note['rule'] in ('FONT_SUBSTITUTED', 'FONT_GLYPH_FALLBACK'):
            deck_gap.update(note.get('detail', {}).get('unsupported_characters', ''))
    bullet_style = choose_bullet_style(ir)
    bullet_glyph, bullet_face = resolve_bullet(bullet_style, theme["font_family"], regular_font)
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
        blocks, figs = comp["blocks"], comp["figure_refs"]
        show_sequence = sequence_flow(comp)
        visual_intent = comp.get("visual_intent") or {}
        family = ARCHETYPES[comp["archetype"]]["layout"]
        elements = []
        slide_formulas = []
        scientific_text_ids = {'title', 'takeaway', *(b['id'] for b in blocks), *(b['id']+':label' for b in blocks)}
        def text(eid, content, bbox, role="body", size=28, floor=24, lines=10,
                 anchor="top", color=None, flow=None, align=None):
            if not content:
                return
            if design and role in type_sizes(design) and not eid.startswith('graphic:'):
                size = min(size, type_sizes(design)[role])
            contract = TextBoxContract(theme["font_family"], size,
                font_paths["bold_font_file" if role in ("title", "heading") else "font_file"],
                font_weight=700 if role in ("title", "heading") else 400,
                font_floor=floor, max_lines=lines, vertical_anchor=anchor)
            overflow = None
            try:
                output, fitted = fit_text(content, bbox, contract)
            except ValueError:
                if preserve_terms and eid in scientific_text_ids and min(bbox[2:]) > 0:
                    wrapped = break_lines(content, ImageFont.truetype(contract.font_file, int(floor)), bbox[2])
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
            # stated, which is how a 13.5 pt footer shipped beside 18 pt body text.
            minimum_pt = ANNOTATION_MIN_PT if role in ANNOTATION_ROLES else BODY_MIN_PT
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
            elements.append({"id": eid, "kind": "text", "role": role, "text": output,
                             "source_text": content, "bbox": bbox, "contract": fitted.to_dict(),
                             "color": color or theme.get("foreground", "#142735"),
                             **({'scientific_text_overflow': overflow} if overflow else {}),
                             **({"align": align} if align else {}),
                             **({"text_flow": flow} if flow else {})})
        spacious = deck_frame == "spacious"
        templated = deck_frame == "template"
        footer = " · ".join(sem["evidence_refs"])
        visible_caveats, moved_caveats = audience.split_caveats(sem["caveats"])
        if design:
            header = header_layout(design, slide, font_paths, preserve_terms)
            text('title', sem['title'], header['title'], 'title', 44, 36, header.get('title_lines', 2))
            text('takeaway', sem['takeaway'], header['takeaway'], 'takeaway', 28, 24, header.get('takeaway_lines', 2))
            elements.extend(header_decoration(design, header))
            caveat_y, caveat_h = (622, 36) if family == 'dual' else (604, 46)
        elif templated:
            # A lab template owns the page frame: its own title slot, its own footer band, its own
            # white page. The compiler keeps the body grid but hands the title, takeaway and caveat
            # to the template's geometry.
            # The template's title slot ends at its red rule (y=78), so the title is set to fit
            # above it and the takeaway opens the body underneath.
            text("title", sem["title"], [88, 24, 1104, 50], "title", 36, 30, 2, color="#1A1A1A")
            text("takeaway", sem["takeaway"], [88, 84, 1104, 42], "takeaway", 24, 24, 2,
                 color="#333333")
            caveat_y, caveat_h = 640, 36
        else:
            text("title", sem["title"], [56, 24 if spacious else 34, 1168, 116 if spacious else 120], "title", 44, 36, 2)
            # These two evidence-heavy slides use a single-line takeaway; reclaiming
            # the unused vertical room lets the original scientific panels render
            # larger without colliding with the title block.
            takeaway_h = 56 if slide["id"] in ("s05-anneal", "s07-contact") else 76
            text("takeaway", sem["takeaway"], [56, 144 if spacious else 164, 1168, takeaway_h], "takeaway", 28, 24, 2)
            # No footer element on any frame. The evidence ids used to be set at 15 pt under every
            # page, which meant a dozen EV numbers shared the bottom strip with the caveat. They are
            # traceability keys: the notes carry them, the room does not need them.
            caveat_y, caveat_h = 604, 46
            if family == "dual":
                # Compact callouts and larger scientific panels extend lower on
                # dual-evidence slides, while keeping the caveat clear.
                caveat_y, caveat_h = 622, 36
        if visible_caveats:
            text("caveats", audience.join_caveats(visible_caveats), [56, caveat_y, 1168, caveat_h], "caveat", 20, 20, 2)
        top, bottom = body_region(slide, family, deck_frame, design, font_paths, preserve_terms)
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
                for size_px in ([formula_size] if formula_size is not None else FORMULA_SIZES):
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
                    "omml": to_omml_paragraph(ast, size_px, colour),
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
            if preserve_terms and flow['mode'] == DISTRIBUTED_ARROW_LIST:
                # The complete prose remains editable even when a native list's item limit is too
                # tight. Do not shorten a technical name to satisfy that presentational limit.
                flow = {**flow, 'mode': 'plain'}
            if flow["mode"] == DISTRIBUTED_ARROW_LIST and box[2] >= 520 and box[3] >= 220:
                pad_x, pad_y = (0, 0) if design else (28, 18)
                label_h = 44 if label else 0
                items = flow["items"]
                # One text object, one paragraph per item, marker set by the paragraph itself.
                # The theme's line height is 1.25, which is what the contract and OfficeCLI agree on.
                fitted = fit_list_items(items, box[2]-2*pad_x-BULLET_GUTTER,
                                        font_paths["font_file"], 24, 22, LIST_ITEM_LINES)
                if fitted is None:
                    issues.append(issue("SPLIT_REQUIRED", "FAIL",
                                        f"{b['id']} list items cannot fit above their font floor",
                                        n, b["id"], detector="geometric-preflight",
                                        textbox_contract="deck_ir"))
                    return
                lines, size = fitted
                line_h = size * 1.25
                gaps = len(lines) - 1
                # Item spacing is a typographic value, not leftover space: filling the panel is what
                # pushed three short items a hundred pixels apart. The ratio is relative to the line
                # height (so it follows the font), and the deck may override it.
                space_after = round(line_h * list_gap_ratio, 2) if gaps else 0.0
                content_h = sum(len(item_lines) for item_lines in lines) * line_h + space_after * gaps
                panel_h = 2*pad_y + label_h + content_h
                if panel_h > box[3] + .5:
                    issues.append(issue("SPLIT_REQUIRED", "FAIL",
                                        f"{b['id']} list needs {content_h:.0f}px but the panel gives "
                                        f"{box[3]-2*pad_y-label_h:.0f}px", n, b["id"],
                                        detector="geometric-preflight", textbox_contract="deck_ir"))
                    return
                # The card hugs the list instead of stretching to the page: a panel with 150 px of
                # empty space under three rows reads as a layout mistake, not as breathing room.
                if not design:
                    elements.append({
                    "id": b["id"] + ":panel", "kind": "shape", "role": "decoration",
                    "bbox": [box[0], box[1], box[2], panel_h],
                    "geometry": "rect", "fill": theme.get("panel_fill", "none"),
                    "line": theme.get("panel_line", "#142735"), "line_width": 1,
                    "collision_mode": "container"})
                if label:
                    text(b["id"]+":label", label,
                         [box[0]+pad_x, box[1]+pad_y, box[2]-2*pad_x, label_h],
                         "heading", 28, 24, 1)
                style = {"id": b["id"], "kind": "list", "role": "body",
                         "bbox": [box[0]+pad_x, box[1]+pad_y+label_h, box[2]-2*pad_x, content_h],
                         "color": theme.get("foreground", "#142735")}
                contract = TextBoxContract(theme["font_family"], size, font_paths["font_file"],
                                           font_weight=400, font_floor=22,
                                           max_lines=max(len(item_lines) for item_lines in lines),
                                           vertical_anchor="top")
                elements.append({**style, "items": lines,
                                 "text": "\n".join("\v".join(item_lines) for item_lines in lines),
                                 "source_text": b["text"], "contract": contract.to_dict(),
                                 "bullet": {"style": bullet_style, "char": bullet_glyph,
                                            "face": bullet_face,
                                            "color": theme.get("accent", DEFAULT_ACCENT),
                                            "gutter": BULLET_GUTTER,
                                            "space_after": round(space_after, 2)},
                                 "text_flow": flow})
                adaptations.append({
                    "block_id": b["id"],
                    "action": DISTRIBUTED_ARROW_LIST,
                    "source": flow["source"],
                    "item_count": len(lines),
                    "bullet_style": bullet_style,
                    "bullet_glyph": bullet_glyph,
                    "bullet_face": bullet_face,
                    "distribution": flow["distribution"],
                })
                return
            if flow["mode"] == DISTRIBUTED_ARROW_LIST:
                adaptations.append({
                    "block_id": b["id"],
                    "action": "text_flow_fallback",
                    "requested": DISTRIBUTED_ARROW_LIST,
                    "reason": "component_box_below_520x220",
                })
                issues.append(issue("TEXT_FLOW_FALLBACK", "INFO",
                                    f"{b['id']} kept plain because its component box is too narrow or short",
                                    n, b["id"], detector="geometric-preflight"))
            label_h = (40 if comp["archetype"] == "figure-parameters" else 44) if label else 0
            text(b["id"]+":label", label, [box[0], box[1], box[2], label_h], "heading", 28, 24, 1)
            emphasis_color = theme.get("accent", DEFAULT_ACCENT) if b["id"] == visual_intent.get("emphasis") else None
            text(b["id"], b["text"], [box[0], box[1]+label_h, box[2], box[3]-label_h], color=emphasis_color)
        def formula_flow(bs, box, max_columns=1, preferred_columns=1):
            try:
                plan = plan_formula_flow(bs, box, font_paths, comp['archetype'],
                    max_columns=max_columns, preferred_columns=preferred_columns,
                    body_size=type_sizes(design)['body'] if design else 28,
                    text_inset=56 if show_sequence else 0, preserve_terms=preserve_terms,
                    gap=24 if comp['archetype'] == 'figure-parameters' else 18)
            except FormulaCapacityError as error:
                issues.append(issue('FORMULA_CAPACITY', 'FAIL', str(error), n,
                    detector='geometric-preflight', confidence='HIGH',
                    suggested_fix='widen_text_column_or_split_slide', attempts=error.attempts,
                    available_width_px=box[2], available_height_px=box[3]))
                return
            by_id = {b['id']: b for b in bs}
            for bid in plan['reading_order']:
                block(by_id[bid], plan['boxes'][bid], plan['font_size_px'], 'left')
            adaptations.append({'action': 'formula_flow', 'region': list(box), **plan})

        def stack(bs, box):
            if not bs:
                return
            if any(b.get('component') == 'formula' for b in bs):
                formula_flow(bs, box)
                return
            gap = 24 if comp['archetype'] == 'figure-parameters' else 18
            h = (box[3]-gap*(len(bs)-1))/len(bs)
            for k, b in enumerate(bs):
                block(b, [box[0], box[1]+k*(h+gap), box[2], h])
        def figure(f, box, k, caption_top=None):
            asset = assets[f["asset_id"]]
            schematic = (asset.get("origin") or "paper") == "generated"
            caption_h = 0
            if f["caption"]:
                # Declared height wins; otherwise the strip follows the actual line count. A drawn
                # schematic and a one-line paper caption need the same thing: enough room for the
                # lines they have, not the two-line scientific default.
                caption_h = f.get("caption_height") or caption_height(
                    f["caption"], box[2], font_paths["font_file"], f.get("caption_font_size", 22))
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
            element = {"id": eid, "kind": "image", "role": "evidence", "bbox": bbox,
                       "asset_id": f["asset_id"], "alt": f.get("alt", f["caption"]),
                       "min_panel_extent": min_extent,
                       "actual_panel_extent": actual_extent}
            if schematic:
                element["schematic"] = {"generator": asset.get("generator")}
            else:
                element["source_figure"] = f["source_figure"]
            elements.append(element)
            if actual_extent < min_extent:
                if schematic:
                    issues.append(issue("SCHEMATIC_TOO_SMALL", "FAIL",
                                        f"Schematic extent {actual_extent:.1f}px is below {min_extent}px",
                                        n, eid, detector="geometric-preflight", confidence="HIGH"))
                else:
                    issues.append(issue("SCIENTIFIC_PANEL_TOO_SMALL", "FAIL",
                                        f"Scientific panel extent {actual_extent:.1f}px is below {min_extent}px",
                                        n, eid, detector="geometric-preflight", confidence="HIGH",
                                        source_figure=f["source_figure"]))
            caption_y = bbox[1]+bbox[3]+12
            if design and f['caption'] and design['figure_treatment'] == 'ruled-caption':
                elements.append(rule(eid+':caption-rule', [box[0], caption_y-6, box[2], 1], design))
            text(eid+":caption", f["caption"], [box[0], caption_y, box[2], caption_h],
                 "caption", f.get("caption_font_size", 22), f.get("caption_font_floor", 20), 2)
            if schematic:
                issues.append(issue("SCHEMATIC_REVIEW", "REVIEW",
                                    "Confirm the drawn schematic matches the text it illustrates; "
                                    "it is not a paper figure",
                                    n, eid, detector="scientific-review", confidence="MEDIUM"))
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

        adaptations = []
        def native_graphic(region):
            graphic = comp["graphics"][0]
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
                     element["font_size"], 24, element["max_lines"], "middle",
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
        has_formulas = any(b.get('component') == 'formula' for b in blocks)
        proposal = None if visual_plan or schematic_only or comp.get('graphics') or has_formulas else (proposals or {}).get(slide['id'])
        if visual_plan:
            from .academic_layout import candidates
            best_failures, attempts = [], []
            for plan in candidates(slide, [56, top, 1168, bh], assets, font_paths, design):
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
            for plan in graphic_page_regions(comp, [56, top, 1168, bh], assets, font_paths):
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
                    'their size floors. Split or replan the page; no content was shortened or dropped.',
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
                for k, b in enumerate(blocks):
                    block(b, [56+k*(w+32), top, w, bh])
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
        if (comp.get('graphics') or design) and len({e['id'] for e in elements}) != len(elements):
            issues.append(issue('GRAPHIC_ID_COLLISION' if comp.get('graphics') else 'VISUAL_PLAN_ID_COLLISION',
                                'FAIL', 'Page object names must be unique',
                                n, detector='geometric-preflight'))
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
            "background_image": (assets[background_key]["path"] if background_key else None),
            **({'academic_design': design} if design else {}),
            "slides": slides}, issues
