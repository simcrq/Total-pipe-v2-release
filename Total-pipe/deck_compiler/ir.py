"""Canonical input validation and read-only derived views."""
import re

from . import audience
from .catalog import ARCHETYPES, COMPONENTS
from .capacity import FORMULA_MIN_ANCHOR_CHARS, FORMULA_MIN_TEXT_CHARS
from .contracts import digest, issue
from .explanation import coverage as explanation_coverage
from .explanation import validate_explanation
from .graphic_layout import graphic_texts, mechanism_edges, validate_graphics
from .provenance import validate as validate_provenance
from .visual_design import preserve_scientific_terms, validate_design, validate_plan
from .layout_tree import ATTACHMENT_POSITIONS
from .text_flow import (EXPLICIT_LISTS, NATIVE_BULLET_LIST, NATIVE_NUMBERED_LIST,
                        TEXT_FLOWS, select_text_flow, valid_bullet_icon)


SOURCE_FIGURE = re.compile(r"^S?[1-9][0-9]*[a-z]?$")
CAPTION_FIGURE = re.compile(r"\bFig(?:ure)?\.?\s*(S?[1-9][0-9]*)\s*([a-z])?", re.IGNORECASE)
ACCENT = re.compile(r"^#[0-9A-Fa-f]{6}$")
# A schematic drawn by the pipeline is not a paper figure, so its caption has to say so.
SCHEMATIC_MARKERS = ("示意图", "schematic", "diagram")


def caption_figure_ids(caption):
    """Return normalized paper figure/panel ids explicitly named by a caption."""
    result = {f"{number.upper()}{(panel or '').lower()}" for number, panel in CAPTION_FIGURE.findall(caption or "")}
    from .scientific_numbers import REFERENCE
    for match in REFERENCE.finditer(str(caption or '')):
        if match['kind'] == '图':
            value = match['id']
            result.add(('S' if value.upper().startswith('S') else '')+value.lstrip('Ss').lower())
    return result


def coarse_characters(text, inline_math=False):
    """Prose characters plus atomic formulas; actual mathematical dimensions are a layout gate."""
    if not isinstance(text, str): return 0
    if not inline_math: return len(text)
    from totalpipe_layout.inline_math import parse_inline, InlineMathError
    try:
        return sum(len(s.text) if s.kind == 'text' else 1 for s in parse_inline(text))
    except InlineMathError:
        return len(text)  # Syntax is reported separately; validation must return structured errors.


def enable_bare_subscripts(ir):
    """Enable native math on supported text fields without modifying their copy."""
    from totalpipe_layout.inline_math import has_bare_subscript

    def objects(value, field):
        entries = value.get(field) if isinstance(value, dict) else None
        return (entry for entry in entries if isinstance(entry, dict)) if isinstance(entries, list) else ()

    for slide in objects(ir, 'slides'):
        semantic = slide.get('semantic')
        if isinstance(semantic, dict):
            fields = semantic.get('inline_math', [])
            if isinstance(fields, list):
                automatic = [key for key in ('title', 'takeaway') if key not in fields
                             and has_bare_subscript(semantic.get(key))]
                if automatic:
                    semantic['inline_math'] = [*fields, *automatic]
        comp = slide.get('composition')
        for block in objects(comp, 'blocks'):
            if (block.get('component') not in ('caption', 'formula')
                    and block.get('text_flow') not in EXPLICIT_LISTS
                    and has_bare_subscript(block.get('text'))):
                block.setdefault('inline_math', True)
        for table in objects(comp, 'tables'):
            for cell in objects(table, 'cells'):
                if cell.get('kind') != 'formula' and has_bare_subscript(cell.get('text')):
                    cell.setdefault('inline_math', True)
    return ir


def visual_carriers(composition):
    """Visual objects a page can be built around: figures, native diagrams, charts, real tables.

    A table counts only as a matrix - two rows by two columns or more - so a one-cell table cannot
    stand in for an explanation.
    """
    composition = composition if isinstance(composition, dict) else {}
    tables = [table for table in composition.get('tables') or []
              if isinstance(table, dict)
              and isinstance(table.get('row_count'), int) and table['row_count'] >= 2
              and isinstance(table.get('column_count'), int) and table['column_count'] >= 2]
    equations = [block for block in composition.get('blocks') or []
                 if isinstance(block, dict) and block.get('component') == 'formula']
    return (len(composition.get('figure_refs') or []) + len(composition.get('graphics') or [])
            + len(composition.get('charts') or []) + len(tables) + len(equations))


def text_only_pages(ir):
    """[(slide number, slide id, copy block count)] for pages that are prose only."""
    found = []
    for number, slide in enumerate(ir.get('slides', []), 1):
        composition = slide.get('composition') or {}
        if not visual_carriers(composition):
            found.append((number, slide.get('id'), len(composition.get('blocks') or [])))
    return found


def _validate_deck_presentation(deck_presentation, check):
    check(deck_presentation.get('text_capacity_policy', 'strict') in ('strict', 'preserve-terms'),
          'text_capacity_policy must be strict or preserve-terms')
    if 'academic_design' in deck_presentation:
        for message in validate_design(deck_presentation['academic_design']):
            check(False, message, rule='ACADEMIC_DESIGN_INVALID')
    check('visual_plan' not in deck_presentation, 'visual_plan belongs to a slide',
          rule='VISUAL_PLAN_INVALID')
    check(deck_presentation.get("frame_variant", "default") in ("default", "spacious", "template"),
          "Unknown deck frame variant")
    if "bullet_style" in deck_presentation:
        from .fonts import BULLET_STYLES
        check(isinstance(deck_presentation['bullet_style'], str) and deck_presentation["bullet_style"] in BULLET_STYLES,
              f"Unknown bullet_style; expected one of {sorted(BULLET_STYLES)}",
              rule="BULLET_STYLE_INVALID")
    if 'bullet_color' in deck_presentation:
        check(isinstance(deck_presentation['bullet_color'], str) and ACCENT.fullmatch(deck_presentation['bullet_color']),
              'presentation.bullet_color must be #RRGGBB', rule='BULLET_COLOR_INVALID')
    if "list_gap" in deck_presentation:
        gap = deck_presentation["list_gap"]
        check(isinstance(gap, (int, float)) and not isinstance(gap, bool)
              and .1 <= float(gap) <= 1.5,
              "presentation.list_gap must be between 0.1 and 1.5", rule="LIST_GAP_INVALID")
    if 'visual_style' in deck_presentation:
        from .style import validate_style
        for message in validate_style(deck_presentation['visual_style']):
            check(False, message, rule='VISUAL_STYLE_INVALID')
    if 'page_numbers' in deck_presentation:
        check(isinstance(deck_presentation['page_numbers'], bool),
              'presentation.page_numbers must be true or false', rule='PAGE_NUMBER_INVALID')
    if 'footer' in deck_presentation:
        value = deck_presentation['footer']
        check(isinstance(value, str) and bool(value.strip()) and len(value) <= 120
              and '\n' not in value,
              'presentation.footer requires one line of at most 120 characters',
              rule='FOOTER_INVALID')
    if 'agenda' in deck_presentation:
        value = deck_presentation['agenda']
        check(value is True or (isinstance(value, dict) and set(value) <= {'title'}
                                and (value.get('title') is None or (
                                    isinstance(value['title'], str) and 0 < len(value['title']) <= 20))),
              'presentation.agenda requires true or {"title": "..."} (at most 20 characters)',
              rule='AGENDA_INVALID')


def _validate_theme(theme, check):
    check(isinstance(theme, dict) and all(isinstance(theme.get(k), str) and theme[k]
          for k in ("font_family", "font_file", "bold_font_file")), "Explicit theme fonts required")
    if isinstance(theme, dict) and "accent" in theme:
        check(isinstance(theme["accent"], str) and ACCENT.fullmatch(theme["accent"]),
              "theme.accent must look like #C2410C")
    if isinstance(theme, dict) and "background_image" in theme:
        check(isinstance(theme["background_image"], str) and bool(theme["background_image"].strip()),
              "theme.background_image must be a file path relative to deck_ir.json",
              rule="BACKGROUND_INVALID")


def _validate_assets(assets, check):
    for key, asset in assets.items():
        check(isinstance(asset, dict) and isinstance(asset.get("path"), str), f"asset {key}: path required")
        if isinstance(asset, dict) and "source_figure" in asset:
            check(isinstance(asset.get("source_figure"), str) and
                  bool(SOURCE_FIGURE.fullmatch(asset["source_figure"])),
                  f"asset {key}: source_figure must look like 3, 3a or S14", rule="FIGURE_PROVENANCE_INVALID")
        if isinstance(asset, dict):
            origin = asset.get("origin", "paper")
            check(origin in ("paper", "generated", "reference"),
                  f"asset {key}: origin must be paper, generated or reference", rule="FIGURE_PROVENANCE_INVALID")
            if origin == "generated":
                check(isinstance(asset.get("generator"), str) and bool(asset["generator"].strip()),
                      f"asset {key}: a generated schematic records its generator",
                      rule="SCHEMATIC_GENERATOR_REQUIRED")
            elif origin == "reference":
                check(isinstance(asset.get("reference_source"), str) and bool(asset["reference_source"].strip()),
                      f"asset {key}: a reference image records its source",
                      rule="REFERENCE_SOURCE_REQUIRED")
                check("source_figure" not in asset,
                      f"asset {key}: a reference image cannot claim a paper figure number",
                      rule="FIGURE_PROVENANCE_FORBIDDEN")


def _validate_slide_presentation(pres, deck_presentation, slide, comp, n, check):
    check('academic_design' not in pres, 'academic_design belongs to the deck', n,
          'ACADEMIC_DESIGN_INVALID')
    if 'section' in pres:
        label = pres['section']
        check(isinstance(label, str) and bool(label.strip()) and len(label) <= 24
              and '\n' not in label,
              'presentation.section requires one line of at most 24 characters', n,
              'SECTION_INVALID')
    if 'takeaway_marker' in pres:
        from .fonts import BULLET_STYLES
        marker = pres['takeaway_marker']
        check(isinstance(marker, dict) and not set(marker) - {'style', 'color'}
              and isinstance(marker.get('style'), str) and marker['style'] in BULLET_STYLES,
              'presentation.takeaway_marker requires a supported style and optional color', n, 'TAKEAWAY_MARKER_INVALID')
        if isinstance(marker, dict) and 'color' in marker:
            check(isinstance(marker['color'], str) and ACCENT.fullmatch(marker['color']),
                  'takeaway_marker.color must be #RRGGBB', n, 'BULLET_COLOR_INVALID')
    if 'takeaway_frame' in pres:
        from .container_frames import validate_frame
        for message in validate_frame(pres['takeaway_frame']):
            check(False, message, n, 'TAKEAWAY_FRAME_INVALID')
    if 'visual_plan' in pres:
        check(isinstance(deck_presentation, dict) and 'academic_design' in deck_presentation,
              'visual_plan requires deck presentation.academic_design', n, 'VISUAL_PLAN_INVALID')
        if isinstance(comp.get('graphics', []), list):
            for message in validate_plan(pres['visual_plan'], slide):
                check(False, message, n, 'VISUAL_PLAN_INVALID')
    if isinstance(deck_presentation, dict) and 'academic_design' in deck_presentation:
        for key in ('theme_tokens', 'component_variants'):
            check(not pres.get(key), f'Use deck academic_design instead of per-slide {key}',
                  n, 'ACADEMIC_DESIGN_INVALID')


def _validate_blocks(blocks, comp, figures, has_tree, n, check):
    from totalpipe_layout.inline_math import InlineMathError, parse_inline
    ids = set()
    formulas = []
    for b in blocks:
        if not isinstance(b, dict):
            check(False, "Block must be an object", n)
            continue
        bid = b.get("id")
        check(isinstance(bid, str) and bid and bid not in ids, "Unique block id required", n)
        if isinstance(bid, str):
            ids.add(bid)
        check(b.get("component") in COMPONENTS, "Unknown component", n)
        caption = b.get('component') == 'caption'
        if caption or 'caption_for' in b or 'text_for' in b:
            field = 'caption_for' if caption or 'caption_for' in b else 'text_for'
            link = b.get(field)
            valid = (isinstance(link, dict) and {'kind', 'ref'} <= set(link) <= {'kind', 'ref', 'position'}
                     and isinstance(link.get('ref'), str) and bool(link['ref'].strip()))
            check(valid, f'Block {bid} needs a valid {field} visual identity', n, 'CAPTION_ANCHOR_INVALID')
            if valid:
                kind, ref = link['kind'], link['ref']
                pool_key = {'graphic': 'graphics', 'table': 'tables', 'chart': 'charts'}
                pool = comp.get(pool_key.get(kind, ''), []) if isinstance(kind, str) else []
                found = any(obj.get('id') == ref for obj in pool if isinstance(obj, dict))
                if kind == 'figure':
                    found = any(f.get('asset_id') == ref for f in figures if isinstance(f, dict))
                elif kind == 'formula':
                    found = any(f.get('id') == ref and f.get('component') == 'formula' and not f.get('anchor')
                                for f in blocks if isinstance(f, dict))
                check(found, f'Block {bid} must explain an existing visual on this page', n, 'CAPTION_ANCHOR_INVALID')
                if 'position' in link or field == 'text_for':
                    check(has_tree and link.get('position') in ATTACHMENT_POSITIONS,
                          f'Block {bid} needs a body layout tree and top/bottom/left/right',
                          n, 'CAPTION_ANCHOR_INVALID')
            check(caption if field == 'caption_for' else b.get('component') != 'formula',
                  'Use caption_for on captions and text_for on prose blocks', n, 'CAPTION_ANCHOR_INVALID')
            check(not ('text_for' in b and 'caption_for' in b),
                  'A block may attach to one object', n, 'CAPTION_ANCHOR_INVALID')
        if caption:
            check(not any(key in b for key in ('label', 'anchor', 'bullet_style', 'bullet_color',
                                               'bullet_icon', 'list_start'))
                  and not b.get('inline_math') and b.get('text_flow', 'plain') == 'plain',
                  'Native captions use plain annotation text; body/list/formula treatments are not captions', n, 'CAPTION_INVALID')
        if 'bullet_style' in b:
            from .fonts import BULLET_STYLES
            check(isinstance(b['bullet_style'], str) and b['bullet_style'] in BULLET_STYLES,
                  f"block {bid}: unknown bullet_style", n, 'BULLET_STYLE_INVALID')
        if 'bullet_color' in b:
            check(isinstance(b['bullet_color'], str) and ACCENT.fullmatch(b['bullet_color']),
                  f'block {bid}: bullet_color must be #RRGGBB', n, 'BULLET_COLOR_INVALID')
        flow = b.get('text_flow', 'auto')
        if 'bullet_style' in b or 'bullet_color' in b or flow in EXPLICIT_LISTS:
            check(b.get('component') != 'formula' and not b.get('inline_math') and b.get('text_flow', 'auto') != 'plain',
                  f'block {bid}: bullet overrides require native prose-list flow', n, 'TEXT_FLOW_INVALID')
        if 'bullet_icon' in b:
            check(flow == NATIVE_BULLET_LIST and 'bullet_style' not in b and valid_bullet_icon(b['bullet_icon']),
                  f'block {bid}: bullet_icon requires one symbol or punctuation glyph and native_bullet_list',
                  n, 'BULLET_STYLE_INVALID')
        if 'list_start' in b:
            start = b['list_start']
            check(flow == NATIVE_NUMBERED_LIST and type(start) is int and 1 <= start <= 9999,
                  f'block {bid}: list_start is an integer from 1 to 9999 for native_numbered_list',
                  n, 'TEXT_FLOW_INVALID')
        if flow == NATIVE_NUMBERED_LIST:
            check('bullet_style' not in b, f'block {bid}: numeric lists use native Arabic numbers',
                  n, 'TEXT_FLOW_INVALID')
        if flow in EXPLICIT_LISTS and isinstance(b.get('text'), str):
            minimum = 2 if flow == EXPLICIT_LISTS[0] else 1
            check(select_text_flow(b['text'], flow)['mode'] != 'plain',
                  f'block {bid}: this native list requires {minimum} to 6 nonempty rows', n, 'TEXT_FLOW_INVALID')
        check(isinstance(b.get("text"), str) and bool(b["text"].strip()), "Block text required", n)
        check(type(b.get('inline_math', False)) is bool, 'inline_math must be boolean', n, 'INLINE_MATH_INVALID')
        if b.get('inline_math') is True:
            check(b.get('component') != 'formula' and flow not in EXPLICIT_LISTS,
                  'Inline math requires a prose block with auto/plain text flow', n, 'INLINE_MATH_INVALID')
            if isinstance(b.get('text'), str):
                try:
                    parse_inline(b['text'])
                except InlineMathError as error:
                    check(False, f'block {bid}: {error}', n, 'INLINE_MATH_SYNTAX')
        if b.get("component") == "formula":
            formulas.append(b)
            from totalpipe_layout.formula import FormulaError, parse as parse_formula
            try:
                parse_formula(b.get("text", ""))
            except FormulaError as error:
                check(False, f"block {b.get('id')}: {error}", n, rule="FORMULA_SYNTAX")
        elif "anchor" in b:
            check(False, f"block {b.get('id')}: only a formula block may carry an anchor", n,
                  rule="FORMULA_ANCHOR_INVALID")
        check(flow in TEXT_FLOWS, "Unknown block text_flow", n)
        check(not any(k in b for k in ("bbox", "x", "y", "w", "h")), "Geometry belongs to compiled layout", n)
    # Formula count is not a capacity measure. Complete equations and explanations must fit
    # actual regions, including independent columns and tall matrices.
    if formulas:
        prose = sum(coarse_characters(b.get("text", ""), b.get('inline_math', False)) for b in blocks
                    if isinstance(b, dict) and b.get("component") != "formula")
        check(prose >= FORMULA_MIN_TEXT_CHARS,
              "this page is an equation with no prose beside it: confirm the sentence it "
              "belongs to was not moved or cut to make room for it",
              n, "FORMULA_TEXT_FLOOR", severity="REVIEW")
        for b in formulas:
            anchor = b.get("anchor")
            if anchor is None:
                continue
            target = next((other for other in blocks
                           if isinstance(other, dict) and other.get("id") == anchor), None)
            check(target is not None and target.get("component") != "formula",
                  f"block {b.get('id')}: anchor must name a non-formula block on this slide", n,
                  "FORMULA_ANCHOR_INVALID")
            if target is not None and target.get("component") != "formula":
                check(blocks.index(target) < blocks.index(b),
                      f"block {b.get('id')}: anchor must precede its equation", n,
                      "FORMULA_ANCHOR_INVALID")
                check(len(target.get("text", "").strip()) >= FORMULA_MIN_ANCHOR_CHARS,
                      f"block {b.get('id')}: the block it is anchored to carries no text to "
                      "explain", n, "FORMULA_ANCHOR_INVALID")


def _validate_visual_intent(visual_intent, archetype, blocks, figures, n, check):
    valid_shape = isinstance(visual_intent, dict)
    check(valid_shape, "composition.visual_intent must be an object", n, "VISUAL_INTENT_INVALID")
    if not valid_shape:
        return
    allowed = {"relation", "members", "orientation", "preserve_order", "emphasis"}
    members = visual_intent.get("members")
    ordered_ids = [b.get("id") for b in blocks if isinstance(b, dict)]
    check(set(visual_intent) <= allowed and visual_intent.get("relation") == "process"
          and visual_intent.get("orientation") == "vertical"
          and visual_intent.get("preserve_order") is True,
          "Only a vertical ordered process intent is supported", n, "VISUAL_INTENT_INVALID")
    check(((archetype == "figure-parameters" and len(figures) == 1)
           or (archetype == "process-flow" and len(figures) == 0))
          and len(blocks) == 4
          and not any(b.get("label") for b in blocks if isinstance(b, dict)),
          "Process intent requires four unlabeled blocks, with one figure or no figure",
          n, "VISUAL_INTENT_INVALID")
    check(isinstance(members, list) and all(isinstance(item, str) for item in members)
          and members == ordered_ids and len(set(members)) == 4,
          "Process intent members must match block order exactly", n, "VISUAL_INTENT_INVALID")
    if "emphasis" in visual_intent:
        check(visual_intent["emphasis"] in ordered_ids,
              "Process emphasis must name a member block", n, "VISUAL_INTENT_INVALID")


def _validate_figures(figures, assets, sem, n, check):
    for f in figures:
        check(isinstance(f, dict) and f.get("asset_id") in assets and
              isinstance(f.get("caption"), str), "Figure needs asset reference and caption", n)
        if not isinstance(f, dict) or f.get("asset_id") not in assets:
            continue
        if 'source_label' in f:
            label = f['source_label']
            check(isinstance(label, str) and bool(label.strip()) and len(label) <= 80
                  and '\n' not in label,
                  "figure_refs.source_label requires one line of at most 80 characters, "
                  "e.g. 'Xie et al., Fig. 1g'", n, "FIGURE_SOURCE_LABEL_INVALID")
        if 'highlights' in f:
            highlights = f['highlights']
            check(isinstance(highlights, list) and len(highlights) <= 6,
                  "figure_refs.highlights must be a list of at most 6 items", n, "FIGURE_HIGHLIGHT_INVALID")
            if isinstance(highlights, list):
                for h_idx, h_item in enumerate(highlights, 1):
                    if not isinstance(h_item, dict) or set(h_item) - {'box', 'label', 'color'}:
                        check(False, f"figure_refs.highlights[{h_idx}] supports only box, label, and color",
                              n, "FIGURE_HIGHLIGHT_INVALID")
                        continue
                    box = h_item.get('box')
                    valid_box = (isinstance(box, list) and len(box) == 4
                                 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)
                                 and 0.0 <= box[0] < 1.0 and 0.0 <= box[1] < 1.0
                                 and 0.02 <= box[2] <= 1.0 and 0.02 <= box[3] <= 1.0
                                 and box[0] + box[2] <= 1.001 and box[1] + box[3] <= 1.001)
                    check(valid_box,
                          f"figure_refs.highlights[{h_idx}].box requires normalized [rx, ry, rw, rh] within [0, 1]",
                          n, "FIGURE_HIGHLIGHT_INVALID")
                    if 'label' in h_item:
                        hl_label = h_item['label']
                        check(isinstance(hl_label, str) and bool(hl_label.strip()) and len(hl_label) <= 36
                              and '\n' not in hl_label,
                              f"figure_refs.highlights[{h_idx}].label must be 1-36 single-line characters",
                              n, "FIGURE_HIGHLIGHT_INVALID")
                    if 'color' in h_item:
                        check(isinstance(h_item['color'], str) and bool(ACCENT.fullmatch(h_item['color'])),
                              f"figure_refs.highlights[{h_idx}].color must be #RRGGBB",
                              n, "FIGURE_HIGHLIGHT_INVALID")
        asset = assets[f["asset_id"]]
        asset = asset if isinstance(asset, dict) else {}
        origin = asset.get("origin", "paper")
        if origin == "reference":
            check("source_figure" not in f and "source_figure" not in asset,
                  f"{f['asset_id']}: a reference image cannot claim a paper figure number",
                  n, "FIGURE_PROVENANCE_FORBIDDEN")
            continue
        if origin == "generated":
            # A drawn schematic must be recognisable as one: no paper figure number, and a
            # caption that says so. Everything else about it (size, caption height) is checked
            # like any other picture.
            check("source_figure" not in f and "source_figure" not in asset,
                  f"{f['asset_id']}: a generated schematic must not claim a paper figure number",
                  n, "FIGURE_PROVENANCE_FORBIDDEN")
            check(any(marker in f.get("caption", "").lower() for marker in SCHEMATIC_MARKERS),
                  "A generated schematic caption must say it is a schematic (示意图)",
                  n, "SCHEMATIC_CAPTION_REQUIRED")
            continue
        expected = f.get("source_figure")
        actual = asset.get("source_figure")
        check(isinstance(expected, str) and bool(SOURCE_FIGURE.fullmatch(expected)),
              "Figure reference requires source_figure such as 3, 3a or S14", n,
              "FIGURE_PROVENANCE_REQUIRED")
        check(isinstance(actual, str) and bool(SOURCE_FIGURE.fullmatch(actual)),
              f"Asset {f['asset_id']} requires source_figure", n,
              "FIGURE_PROVENANCE_REQUIRED")
        if isinstance(expected, str) and isinstance(actual, str):
            check(expected == actual,
                  f"Caption expects Fig.{expected}, but asset {f['asset_id']} is Fig.{actual}", n,
                  "FIGURE_SOURCE_MISMATCH")
            projection = sem.get('content_projection', {})
            source = f.get('source_label', '') if projection.get('version') == '2.0' else ''
            check(expected in caption_figure_ids(f.get("caption", "") + ' ' + source),
                  f"Caption must explicitly name Fig.{expected}", n,
                  "FIGURE_CAPTION_MISMATCH")


def _validate_slide_capacity_and_audience(ir, sem, comp, pres, archetype, has_tree, blocks, figures, inline_fields, n, check):
    if archetype in ARCHETYPES and not has_tree:
        cap = ARCHETYPES[archetype]
        context_count = sum(b.get('component') != 'formula' for b in blocks if isinstance(b, dict))
        check((len(blocks) if cap['blocks'] == 0 else context_count) <= cap["blocks"]
              and len(figures) <= cap["figures"],
              "Archetype block/figure capacity exceeded; use composite-research with layout_tree "
              "to hold the extra objects, or split the page if the measured tree still overflows",
              n, "CONTENT_CAPACITY_EXCEEDED")
        if archetype == "evidence-hypothesis":
            check(all(b.get("component") in ("direct-evidence", "hypothesis") for b in blocks)
                  and all(sum(b.get("component") == role for b in blocks) <= 4
                          for role in ("direct-evidence", "hypothesis")),
                  "Evidence and hypothesis must be separate, each <= 4", n, "CONTENT_CAPACITY_EXCEEDED")
    for field, limit in (("title", 120), ("takeaway", 180)):
        check(isinstance(sem.get(field), str) and coarse_characters(sem[field], field in inline_fields) <= limit,
              f"{field} exceeds {limit} characters; retain complete scientific terminology", n,
              "SCIENTIFIC_TEXT_CAPACITY_REVIEW" if preserve_scientific_terms(ir) else "CONTENT_CAPACITY_EXCEEDED",
              severity='REVIEW' if preserve_scientific_terms(ir) and isinstance(sem.get(field), str) else 'FAIL')
    check(all(isinstance(b, dict) and coarse_characters(b.get("text", ""), b.get('inline_math', False)) <= 600 for b in blocks),
          "Block exceeds 600 characters; retain complete scientific terminology", n,
          "SCIENTIFIC_TEXT_CAPACITY_REVIEW" if preserve_scientific_terms(ir) else "CONTENT_CAPACITY_EXCEEDED",
          severity='REVIEW' if preserve_scientific_terms(ir) else 'FAIL')
    # A published figure caption runs three or four lines; the strip is measured for the lines
    # it actually needs, so the character cap is only there to stop a paragraph being pasted in.
    check(all(isinstance(f, dict) and len(f.get("caption", "")) <= 320 and
              isinstance(f.get("panel_count", 1), int) and 1 <= f.get("panel_count", 1) <= 6 for f in figures),
          "Caption/panel capacity exceeded", n, "CONTENT_CAPACITY_EXCEEDED")
    # The page is read by an audience, not by the person auditing the build. Evidence ids,
    # repository paths and notes about which files this run happened to have are real
    # provenance, but they belong in the speaker notes. The compiler moves run-state caveats
    # there; this gate names every string that reads as a work log so it cannot ship silently.
    caveats = sem.get("caveats") if isinstance(sem.get("caveats"), list) else []
    visible_text = [("semantic.title", sem.get("title", "")),
                    ("semantic.takeaway", sem.get("takeaway", ""))]
    visible_text += [(f"semantic.caveats[{i}]", caveat) for i, caveat in enumerate(caveats)
                     if not audience.is_run_state(caveat)]
    visible_text += [(f"block {b.get('id')}", b.get("text", ""))
                     for b in blocks if isinstance(b, dict)]
    visible_text += [(f"block {b.get('id')}.label", b.get("label", ""))
                     for b in blocks if isinstance(b, dict) and b.get("label")]
    for f_idx, f_item in enumerate(figures, 1):
        if isinstance(f_item, dict) and isinstance(f_item.get("highlights"), list):
            for h_idx, h_item in enumerate(f_item["highlights"], 1):
                if isinstance(h_item, dict) and isinstance(h_item.get("label"), str):
                    visible_text.append((f"figure_refs[{f_idx}].highlights[{h_idx}].label", h_item["label"]))
    graphics = comp.get("graphics")
    if isinstance(graphics, list):
        for graphic in graphics:
            visible_text.extend(graphic_texts(graphic))
    for field, text in visible_text:
        found = audience.hits(text)
        if found:
            check(False, f"{field}: " + "; ".join(f"{kind} {value}" for kind, value in found),
                  n, "AUDIENCE_TEXT", severity="REVIEW")
    _, moved = audience.split_caveats(caveats)
    for clause in moved:
        check(False, "caveat clause moves to the speaker notes: " + clause[:70],
              n, "RUN_STATE_CAVEAT", severity="REVIEW")
    check(not pres.get("optional_overrides"), "Geometry overrides unsupported in v2.0; choose a variant", n)
    check(pres.get("variant", "default") in ("default", "spacious"), "Unknown component variant", n)


def _validate_slide(ir, s, n, seen, deck_presentation, assets, errors, check):
    if not isinstance(s, dict):
        check(False, "Slide must be an object", n)
        return
    sid = s.get("id")
    check(isinstance(sid, str) and bool(sid) and sid not in seen, "Unique slide id required", n)
    if isinstance(sid, str):
        seen.add(sid)
    sem, comp, pres = (s.get(k) for k in ("semantic", "composition", "presentation"))
    if not all(isinstance(x, dict) for x in (sem, comp, pres)):
        check(False, "semantic/composition/presentation objects required", n)
        return
    for key in ("title", "purpose", "takeaway", "speaker_notes"):
        check(isinstance(sem.get(key), str) and bool(sem.get(key, "").strip()), f"semantic.{key} required", n)
    for key in ("evidence_refs", "caveats"):
        check(isinstance(sem.get(key), list) and all(isinstance(v, str) for v in sem[key]), f"semantic.{key} list required", n)
    from totalpipe_layout.inline_math import InlineMathError, parse_inline
    inline_fields = sem.get('inline_math', [])
    check(isinstance(inline_fields, list) and all(f in ('title', 'takeaway') for f in inline_fields)
          and len(set(inline_fields)) == len(inline_fields),
          'semantic.inline_math must list unique title/takeaway fields', n, 'INLINE_MATH_INVALID')
    if not isinstance(inline_fields, list):
        inline_fields = []
    for field in ('title', 'takeaway'):
        if isinstance(inline_fields, list) and field in inline_fields and isinstance(sem.get(field), str):
            try:
                parse_inline(sem[field])
            except InlineMathError as error:
                check(False, f'semantic.{field}: {error}', n, 'INLINE_MATH_SYNTAX')
    if "run_notes" in sem:
        check(isinstance(sem["run_notes"], list)
              and all(isinstance(v, str) for v in sem["run_notes"]),
              "semantic.run_notes must be a list of strings", n, "IR_INVALID")
    archetype = comp.get("archetype")
    check(archetype in ARCHETYPES, f"Unknown archetype: {archetype}", n)
    blocks, figures = comp.get("blocks"), comp.get("figure_refs")
    if not isinstance(blocks, list) or not isinstance(figures, list):
        check(False, "composition.blocks/figure_refs must be lists", n)
        return
    _validate_slide_presentation(pres, deck_presentation, s, comp, n, check)
    has_tree = 'layout_tree' in comp
    from .native_table import validate_tables
    for message in validate_tables(comp.get('tables', []), sem.get('evidence_refs', [])):
        check(False, message, n, 'TABLE_INVALID')
    check(not comp.get('tables') or has_tree, 'Native tables require a region tree', n, 'TABLE_INVALID')
    from .chart_layout import validate_charts
    for message in validate_charts(comp.get('charts', []), sem.get('evidence_refs', [])):
        check(False, message, n, 'CHART_INVALID')
    check(not comp.get('charts') or has_tree, 'Charts require a region tree', n, 'CHART_INVALID')
    check(archetype != 'composite-research' or has_tree,
          'composite-research requires composition.layout_tree', n, 'LAYOUT_TREE_INVALID')
    if has_tree:
        from .layout_tree import validate_tree
        for message in validate_tree(comp['layout_tree'], comp):
            check(False, message, n, 'LAYOUT_TREE_INVALID')
        check(not pres.get('visual_plan') and not comp.get('visual_intent'),
              'layout_tree owns body organization; visual_plan/visual_intent cannot also allocate it',
              n, 'LAYOUT_TREE_INVALID')
    for message in validate_graphics(comp.get("graphics", []), archetype, region_tree=has_tree):
        check(False, message, n, "GRAPHIC_INVALID")
    errors.extend(validate_explanation(sem.get("explanation"), sem, comp, n))
    if isinstance(comp.get('graphics'), list):
        for graphic in comp['graphics']:
            for edge in mechanism_edges(graphic):
                refs = edge.get('evidence_refs', [])
                if isinstance(refs, list) and isinstance(sem.get('evidence_refs'), list):
                    check(all(ref in sem['evidence_refs'] for ref in refs),
                          'Mechanism evidence_refs must bind to this slide semantic.evidence_refs',
                          n, 'GRAPHIC_EVIDENCE_INVALID')
    if comp.get("graphics"):
        check(comp.get("visual_intent") is None,
              "Use explicit graphic edges instead of combining graphics with a block visual_intent",
              n, "GRAPHIC_INVALID")
        check(all(not str(b.get("id", "")).startswith("graphic:")
                  for b in blocks if isinstance(b, dict)),
              "Block ids must not use the reserved graphic: object namespace", n, "GRAPHIC_INVALID")
    _validate_blocks(blocks, comp, figures, has_tree, n, check)
    visual_intent = comp.get("visual_intent")
    if visual_intent is not None:
        _validate_visual_intent(visual_intent, archetype, blocks, figures, n, check)
    _validate_figures(figures, assets, sem, n, check)
    _validate_slide_capacity_and_audience(ir, sem, comp, pres, archetype, has_tree, blocks, figures, inline_fields, n, check)
    if 'content_projection' in sem:
        from .content_projection import validate_ir as validate_projection
        for rule, severity, message in validate_projection(s, assets):
            check(False, message, n, rule, severity)


def validate(ir):
    errors = []

    def check(ok, message, slide=None, rule="IR_INVALID", severity="FAIL"):
        if not ok:
            errors.append(issue(rule, severity, message, slide))

    check(isinstance(ir, dict), "Deck IR must be an object")
    if errors:
        return errors
    check(ir.get("schema_version") == "2.0", "schema_version must be 2.0")
    check(isinstance(ir.get("deck_id"), str) and bool(ir.get("deck_id")), "deck_id required")
    deck_presentation = ir.get("presentation", {})
    check(isinstance(deck_presentation, dict), "presentation must be an object")
    if isinstance(deck_presentation, dict):
        _validate_deck_presentation(deck_presentation, check)
    _validate_theme(ir.get("theme", {}), check)
    slides = ir.get("slides")
    check(isinstance(slides, list) and bool(slides), "slides must be a nonempty list")
    if not isinstance(slides, list):
        return errors
    assets = ir.get("assets", {})
    check(isinstance(assets, dict), "assets must be an object")
    if not isinstance(assets, dict):
        return errors
    _validate_assets(assets, check)
    seen = set()
    for n, s in enumerate(slides, 1):
        _validate_slide(ir, s, n, seen, deck_presentation, assets, errors, check)
    errors.extend(validate_provenance(ir))
    return errors


def derive(ir, layout):
    """Disposable projections; never accepted as compiler input."""
    provenance = {"derived_from": "deck_ir.json", "ir_sha256": digest(ir), "read_only": True}
    result = {
        "deck_plan.json": {**provenance, "slides": [{"index": n, "slide_id": s["id"],
            "title": s["semantic"]["title"], "layout_id": s["composition"]["archetype"],
            "evidence_ids": s["semantic"]["evidence_refs"]} for n, s in enumerate(ir["slides"], 1)]},
        "visual_manifest.json": {**provenance, "visuals": [{"slide_id": s["id"], **f}
            for s in ir["slides"] for f in s["composition"]["figure_refs"]],
            "graphics": [{"slide_id": s["id"], **g} for s in ir["slides"]
                         for g in s["composition"].get("graphics", [])],
            "tables": [{"slide_id": s['id'], **t} for s in ir['slides'] for t in s['composition'].get('tables', [])]},
        "plan_to_layout.json": {**provenance, "deck_frame_variant": layout.get("deck_frame_variant"),
            **({'academic_design': layout['academic_design']} if layout.get('academic_design') else {}),
            "slides": [{"slide_id": s["id"], "elements": s["elements"],
                        **({'visual_plan': next(entry for entry in s.get('adaptation_log', [])
                            if entry.get('action') == 'scientific_visual_plan')}
                           if any(entry.get('action') == 'scientific_visual_plan'
                                  for entry in s.get('adaptation_log', [])) else {}),
                        "layout_provider_status": next((entry.get("status") for entry in
                            s.get("adaptation_log", []) if entry.get("action") == "layout_provider"),
                            "DETERMINISTIC")}
                       for s in layout["slides"]]},
        "qa_expectation.json": {**provenance, "slide_count": len(ir["slides"]),
                                "required_renderer": "powerpoint"},
    }
    ledger = explanation_coverage(ir)
    if ledger["slides"]:
        result["explanation_coverage.json"] = ledger
    rendered = {slide['id']: slide for slide in layout['slides']}
    projected = []
    for slide in ir['slides']:
        projection = slide['semantic'].get('content_projection')
        if projection:
            from .content_projection import validate_ir as validate_projection
            findings = validate_projection(slide, ir.get('assets', {}), rendered.get(slide['id']))
            projected.append({'slide_id': slide['id'], 'record_refs': list(projection['items']),
                              'visible_refs': [ref for ref, route in projection['content_map'].items() if route['destination'] == 'visible'],
                              'notes_refs': [ref for ref, route in projection['content_map'].items() if route['destination'] == 'notes'],
                              'review': projection['review'], 'findings': [dict(rule=r, severity=s, message=m) for r, s, m in findings]})
    if projected:
        result['content_projection_coverage.json'] = {**provenance, 'version': '1.0', 'slides': projected,
                                                     'note': 'Structural/visible-object checks; semantic fidelity and audience comprehension require actual review.'}
    return result
