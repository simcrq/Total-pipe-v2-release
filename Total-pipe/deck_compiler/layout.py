"""Deterministic layout compiler. No LLM calls, mutation, or content rewriting."""
from dataclasses import replace
from pathlib import Path
import re
from PIL import Image, ImageFont
from .catalog import ARCHETYPES
from .contracts import TextBoxContract, digest, file_hash, issue
from .ir import validate
from .text_flow import DISTRIBUTED_ARROW_LIST, select_text_flow

WIDTH, HEIGHT = 1280, 720

# Native list markers. The glyph is a *paragraph* property (a:buChar + a:buClr), so an item stays a
# real list item in PowerPoint: Tab changes its level, the bullet menu reflects it, and copying one
# row carries the marker. The catalogue lives in fonts.BULLET_STYLES and is resolved to a face that
# can actually draw the glyph, so a deck never depends on a symbol font being installed.
BULLET_GUTTER = 42.0            # px reserved for the marker, text starts on the gutter edge

# One accent colour per deck, used by list markers, sequence badges and emphasis. It is deliberately
# not the body colour: a marker in the same ink as the sentence reads as a typo, and a step badge in
# the same ink as its label disappears into it. Decks override it with theme.accent.
DEFAULT_ACCENT = "#C2410C"

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
    intent = composition.get("visual_intent")
    if intent is not None:
        return intent.get("relation") == "process"
    return (composition["archetype"] == "figure-parameters" and
            len(composition["figure_refs"]) == 1 and len(blocks) == 4 and
            not any(block.get("label") for block in blocks) and
            blocks[0]["component"] == "method" and
            any(block["component"] == "process-step" for block in blocks) and
            blocks[-1]["component"] == "result")


TOKEN = re.compile(r"[A-Za-z0-9_]+(?:[.,][0-9]+)*(?:%|[×x])?|[^\S\n]+|.")
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
               if element["kind"] == "text" and element["role"] in ("heading", "body")
               and body_top <= element["bbox"][1] < body_bottom]
    if not content:
        return None
    content_bottom = max(text_visible_bottom(element) for element in content)
    gap = body_bottom - content_bottom
    share = gap / (body_bottom - body_top)
    if gap < 160 or share < .40:
        return None
    return issue("TEXT_ONLY_LOWER_WHITESPACE", "WARNING",
                 f"Text content ends near y={content_bottom:.0f}px; the lower {gap:.0f}px "
                 f"({share:.0%} of the body area) is empty. Review vertical balance or "
                 "choose a layout that uses the available space.",
                 slide_number, detector="design-preflight", confidence="MEDIUM",
                 body_top_px=body_top, body_bottom_px=body_bottom,
                 content_bottom_px=round(content_bottom), empty_lower_px=round(gap),
                 empty_share=round(share, 3))


def compile_deck(ir, base, _retry=True, proposals=None):
    issues = validate(ir)
    if issues:
        return None, issues
    base = Path(base)
    theme = ir["theme"]
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
           for figure in slide["composition"]["figure_refs"]])
    try:
        regular_font, bold_font, font_notes = resolve_theme_fonts(theme, base, text_sample)
    except (FileNotFoundError, OSError) as error:
        issues.append(issue("FONT_UNAVAILABLE", "FAIL", str(error), detector="geometric-preflight"))
        return None, issues
    font_paths = {"font_file": regular_font, "bold_font_file": bold_font}
    bullet_style = choose_bullet_style(ir)
    bullet_glyph, bullet_face = resolve_bullet(bullet_style, theme["font_family"], regular_font)
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
    deck_frame = frame_variant(ir)
    slides = []
    for n, slide in enumerate(ir["slides"], 1):
        sem, comp = slide["semantic"], slide["composition"]
        blocks, figs = comp["blocks"], comp["figure_refs"]
        show_sequence = sequence_flow(comp)
        visual_intent = comp.get("visual_intent") or {}
        family = ARCHETYPES[comp["archetype"]]["layout"]
        elements = []
        def text(eid, content, bbox, role="body", size=28, floor=24, lines=10,
                 anchor="top", color=None, flow=None):
            if not content:
                return
            contract = TextBoxContract(theme["font_family"], size,
                font_paths["bold_font_file" if role in ("title", "heading") else "font_file"],
                font_weight=700 if role in ("title", "heading") else 400,
                font_floor=floor, max_lines=lines, vertical_anchor=anchor)
            try:
                output, fitted = fit_text(content, bbox, contract)
            except ValueError:
                issues.append(issue("SPLIT_REQUIRED", "FAIL", f"{eid} cannot fit above its font floor",
                                    n, eid, detector="geometric-preflight", textbox_contract="deck_ir"))
                return
            # Missing-glyph comparison is a conservative signal, not full shaping coverage.
            font = ImageFont.truetype(fitted.font_file, int(fitted.font_size))
            missing = bytes(font.getmask(chr(0x10FFFF)))
            if any(bytes(font.getmask(c)) == missing for c in set(content) if not c.isspace()):
                issues.append(issue("FONT_COVERAGE_REVIEW", "REVIEW", "Possible missing glyphs; verify in PowerPoint",
                                    n, eid, detector="geometric-preflight", confidence="LOW", font_metrics="pillow"))
            elements.append({"id": eid, "kind": "text", "role": role, "text": output,
                             "source_text": content, "bbox": bbox, "contract": fitted.to_dict(),
                             "color": color or theme.get("foreground", "#142735"),
                             **({"text_flow": flow} if flow else {})})
        spacious = deck_frame == "spacious"
        text("title", sem["title"], [56, 24 if spacious else 34, 1168, 116 if spacious else 120], "title", 44, 36, 2)
        # These two evidence-heavy slides use a single-line takeaway; reclaiming
        # the unused vertical room lets the original scientific panels render
        # larger without colliding with the title block.
        takeaway_h = 56 if slide["id"] in ("s05-anneal", "s07-contact") else 76
        text("takeaway", sem["takeaway"], [56, 144 if spacious else 164, 1168, takeaway_h], "takeaway", 28, 24, 2)
        footer = " · ".join(sem["evidence_refs"])
        footer_y, footer_h = 658, 44
        caveat_y, caveat_h = 604, 46
        if slide["id"] == "s05-anneal":
            footer_y, footer_h = 666, 36
        elif family == "dual":
            # Compact callouts and larger scientific panels extend lower on
            # dual-evidence slides, while keeping caveats and evidence ids clear.
            caveat_y, caveat_h = 622, 36
            footer_y, footer_h = 670, 32
        text("footer", footer, [56, footer_y, 1168, footer_h], "footer", 18, 16, 2)
        if sem["caveats"]:
            text("caveats", "；".join(sem["caveats"]), [56, caveat_y, 1168, caveat_h], "caveat", 20, 18, 2)
        bottom = 588 if sem["caveats"] else 640
        top = 236 if spacious else 260
        bh = bottom-top
        def block(b, box):
            label = b.get("label", "")
            if show_sequence:
                box = [box[0]+56, box[1], box[2]-56, box[3]]
            flow = select_text_flow(b["text"], b.get("text_flow", "auto"))
            if flow["mode"] == DISTRIBUTED_ARROW_LIST and box[2] >= 520 and box[3] >= 220:
                panel_id = b["id"] + ":panel"
                elements.append({
                    "id": panel_id,
                    "kind": "shape",
                    "role": "decoration",
                    "bbox": box,
                    "geometry": "rect",
                    "fill": theme.get("panel_fill", "none"),
                    "line": theme.get("panel_line", "#142735"),
                    "line_width": 1,
                    "collision_mode": "container",
                })
                pad_x, pad_y = 28, 18
                label_h = 44 if label else 0
                if label:
                    text(b["id"]+":label", label,
                         [box[0]+pad_x, box[1]+pad_y, box[2]-2*pad_x, label_h],
                         "heading", 28, 24, 1)
                items = flow["items"]
                items_box = [box[0]+pad_x, box[1]+pad_y+label_h,
                             box[2]-2*pad_x, box[3]-2*pad_y-label_h]
                # One text object, one paragraph per item, marker set by the paragraph itself.
                # The theme's line height is 1.25, which is what the contract and OfficeCLI agree on.
                style = {"id": b["id"], "kind": "list", "role": "body",
                         "bbox": items_box, "color": theme.get("foreground", "#142735")}
                fitted = fit_list_items(items, items_box[2]-BULLET_GUTTER,
                                        font_paths["font_file"], 24, 22, 2)
                if fitted is None:
                    issues.append(issue("SPLIT_REQUIRED", "FAIL",
                                        f"{b['id']} list items cannot fit above their font floor",
                                        n, b["id"], detector="geometric-preflight",
                                        textbox_contract="deck_ir"))
                    return
                lines, size = fitted
                content_h = sum(len(item_lines) for item_lines in lines) * size * 1.25
                if content_h > items_box[3] + .5:
                    issues.append(issue("SPLIT_REQUIRED", "FAIL",
                                        f"{b['id']} list needs {content_h:.0f}px but the panel gives "
                                        f"{items_box[3]:.0f}px", n, b["id"],
                                        detector="geometric-preflight", textbox_contract="deck_ir"))
                    return
                gaps = len(lines) - 1
                space_after = (items_box[3] - content_h) / gaps if gaps else 0.0
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
        def stack(bs, box):
            if not bs:
                return
            gap = 24 if comp["archetype"] == "figure-parameters" else 18
            h = (box[3]-gap*(len(bs)-1))/len(bs)
            for k, b in enumerate(bs):
                block(b, [box[0], box[1]+k*(h+gap), box[2], h])
        def figure(f, box, k):
            asset = assets[f["asset_id"]]
            caption_h = f.get("caption_height", 62) if f["caption"] else 0
            h = box[3] - caption_h - 12
            scale = min(box[2]/asset["width"], h/asset["height"])
            w, h = asset["width"]*scale, asset["height"]*scale
            bbox = [box[0]+(box[2]-w)/2, box[1], w, h]
            eid = f"figure-{k}"
            min_extent = f.get("min_panel_extent", 220)
            actual_extent = min(w / f.get("panel_count", 1), h)
            elements.append({"id": eid, "kind": "image", "role": "evidence", "bbox": bbox,
                             "asset_id": f["asset_id"], "alt": f.get("alt", f["caption"]),
                             "source_figure": f["source_figure"],
                             "min_panel_extent": min_extent,
                             "actual_panel_extent": actual_extent})
            if actual_extent < min_extent:
                issues.append(issue("SCIENTIFIC_PANEL_TOO_SMALL", "FAIL",
                                    f"Scientific panel extent {actual_extent:.1f}px is below {min_extent}px",
                                    n, eid, detector="geometric-preflight", confidence="HIGH",
                                    source_figure=f["source_figure"]))
            text(eid+":caption", f["caption"], [box[0], bbox[1]+bbox[3]+12, box[2], caption_h],
                 "caption", f.get("caption_font_size", 22), f.get("caption_font_floor", 20), 2)
            issues.append(issue("SCIENTIFIC_PANEL_REVIEW", "REVIEW", "Confirm scientific panel labels and evidence fidelity",
                                n, eid, detector="scientific-review", confidence="MEDIUM"))
        adaptations = []
        proposal = (proposals or {}).get(slide['id'])
        if proposal:
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
                figure({**f, 'caption_height': group.get('caption_height', f.get('caption_height', 62))},
                       group['bbox'], k)
            adaptations.append({'action': 'layout_provider',
                                'provider': proposal.get('provider', 'provider'),
                                'status': proposal['status']})
        elif family in ("figure-left", "figure-right") and figs:
            fig_x, txt_x = (56, 784) if family == "figure-left" else (552, 56)
            fig_w, txt_w = (692, 440) if family == "figure-left" else (672, 460)
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
                     "heading", 24, 22, 1)
                text(b["id"], b["text"], [left_x, y+32, left_w, row_h-32],
                     "body", 22, 20, 1)
            figure(figs[0], [650, top, 574, bh], 1)
        elif slide["id"] == "s07-contact" and figs:
            # Keep the two numeric callouts compact so the two original Fig.3e/f
            # panels can occupy most of the evidence area at readable size.
            for k, b in enumerate(blocks[:2]):
                x = 56 + k * 600
                text(b["id"]+":label", b.get("label", ""), [x, top, 568, 32],
                     "heading", 24, 22, 1)
                text(b["id"], b["text"], [x, top+32, 568, 38],
                     "body", 26, 22, 1)
            fw = (1168-32*(len(figs)-1))/len(figs)
            for k, f in enumerate(figs):
                figure(f, [56+k*(fw+32), top+70, fw, bh-40], k+1)
        elif family == "dual" and figs:
            # Dual scientific figures get compact native callouts and a hard
            # 240px evidence band. This avoids the former 154px thumbnails.
            for k, b in enumerate(blocks[:2]):
                x = 56 + k * 600
                text(b["id"]+":label", b.get("label", ""), [x, top, 568, 30],
                     "heading", 24, 22, 1)
                text(b["id"], b["text"], [x, top+30, 568, 34],
                     "body", 22, 20, 1)
            fw = (1168-32*(len(figs)-1))/len(figs)
            for k, f in enumerate(figs):
                figure(f, [56+k*(fw+32), top+70, fw, bh-40], k+1)
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
        if family == "columns" and not figs and not sem["caveats"] and len(blocks) >= 3:
            notice = lower_whitespace_issue(elements, n, top, bottom)
            if notice:
                issues.append(notice)
        # Detect errors before emitting any PPTX, including title/footer collisions.
        for idx, e in enumerate(elements):
            x, y, w, h = e["bbox"]
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > WIDTH+.1 or y+h > HEIGHT+.1:
                issues.append(issue("SHAPE_OUT_OF_BOUNDS", "FAIL", "Invalid element geometry", n, e["id"], detector="geometric-preflight"))
            for other in elements[:idx]:
                if e.get("collision_mode") == "container" or other.get("collision_mode") == "container":
                    continue
                if intersect(e["bbox"], other["bbox"]):
                    issues.append(issue("CRITICAL_COLLISION", "FAIL", f"Overlaps {other['id']}", n, e["id"], detector="geometric-preflight"))
        slides.append({"id": slide["id"], "background": theme.get("background", "#FFFFFF"),
                       "notes": sem["speaker_notes"] + "\nEvidence: " + footer,
                       "elements": elements, "adaptation_log": adaptations})
    if _retry and any(i["rule"] == "SPLIT_REQUIRED" for i in issues):
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
            "slides": slides}, issues
