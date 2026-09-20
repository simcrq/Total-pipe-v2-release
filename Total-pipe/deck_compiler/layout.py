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


def break_lines(text, font, width):
    """Preserve paragraphs, break at words/CJK glyphs; long tokens split safely."""
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for token in re.findall(r"[A-Za-z0-9_]+|[^\S\n]+|.", paragraph):
            if current and font.getlength(current + token) > width:
                lines.append(current.rstrip())
                current = ""
                token = token.lstrip()
            for char in token:
                if current and font.getlength(current + char) > width:
                    lines.append(current.rstrip())
                    current = ""
                current += char
        lines.append(current.rstrip())
    return lines


def fit_text(text, bbox, contract):
    inner_w = bbox[2] - contract.inset["left"] - contract.inset["right"]
    inner_h = bbox[3] - contract.inset["top"] - contract.inset["bottom"]
    for size in range(int(contract.font_size), int(contract.font_floor) - 1, -1):
        font = ImageFont.truetype(contract.font_file, size)
        lines = break_lines(text, font, inner_w)
        # Exact line spacing is emitted into OOXML by finalizer.
        if (len(lines) <= contract.max_lines and len(lines) * size * contract.line_height <= inner_h
                and all(font.getlength(line) <= inner_w for line in lines)):
            return "\n".join(lines), replace(contract, font_size=size)
    raise ValueError("SPLIT_REQUIRED")


def intersect(a, b):
    return min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0]) > .5 and \
           min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]) > .5


def compile_deck(ir, base, _retry=True):
    issues = validate(ir)
    if issues:
        return None, issues
    base = Path(base)
    theme = ir["theme"]
    font_paths = {}
    for key in ("font_file", "bold_font_file"):
        path = (base / theme[key]).resolve()
        try:
            ImageFont.truetype(str(path), 24)
        except (OSError, ValueError) as e:
            issues.append(issue("FONT_UNAVAILABLE", "FAIL", str(e), detector="geometric-preflight"))
        font_paths[key] = str(path)
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
    slides = []
    for n, slide in enumerate(ir["slides"], 1):
        sem, comp = slide["semantic"], slide["composition"]
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
        spacious = slide["presentation"].get("variant") == "spacious"
        text("title", sem["title"], [56, 24 if spacious else 34, 1168, 116 if spacious else 120], "title", 44, 36, 2)
        text("takeaway", sem["takeaway"], [56, 144 if spacious else 164, 1168, 76], "takeaway", 28, 24, 2)
        footer = " · ".join(sem["evidence_refs"])
        text("footer", footer, [56, 658, 1168, 44], "footer", 18, 16, 2)
        if sem["caveats"]:
            text("caveats", "；".join(sem["caveats"]), [56, 604, 1168, 46], "caveat", 20, 18, 2)
        bottom = 588 if sem["caveats"] else 640
        top = 236 if spacious else 260
        bh = bottom-top
        blocks, figs = comp["blocks"], comp["figure_refs"]
        family = ARCHETYPES[comp["archetype"]]["layout"]
        def block(b, box):
            label = b.get("label", "")
            flow = select_text_flow(b["text"], b.get("text_flow", "auto"))
            if flow["mode"] == DISTRIBUTED_ARROW_LIST and box[2] >= 520 and box[3] >= 220:
                panel_id = b["id"] + ":panel"
                elements.append({
                    "id": panel_id,
                    "kind": "shape",
                    "role": "decoration",
                    "bbox": box,
                    "geometry": "rect",
                    "fill": theme.get("panel_fill", "#F4F8FA"),
                    "line": theme.get("panel_line", "#D6E4EA"),
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
                row_top = box[1] + pad_y + label_h
                row_height = (box[3] - 2*pad_y - label_h) / len(items)
                for item_index, item in enumerate(items):
                    y = row_top + item_index * row_height
                    arrow_box = [box[0]+pad_x, y, 42, row_height]
                    item_box = [box[0]+pad_x+54, y, box[2]-2*pad_x-54, row_height]
                    item_flow = {**flow, "item_index": item_index, "item_count": len(items)}
                    text(f"{b['id']}:arrow:{item_index+1}", flow["bullet_glyph"], arrow_box,
                         "bullet", 28, 24, 1, "middle", theme.get("accent", "#142735"), item_flow)
                    text(f"{b['id']}:item:{item_index+1}", item, item_box,
                         "body", 24, 22, 2, "middle", None, item_flow)
                adaptations.append({
                    "block_id": b["id"],
                    "action": DISTRIBUTED_ARROW_LIST,
                    "source": flow["source"],
                    "item_count": len(items),
                    "bullet_glyph": flow["bullet_glyph"],
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
            label_h = 44 if label else 0
            text(b["id"]+":label", label, [box[0], box[1], box[2], label_h], "heading", 28, 24, 1)
            text(b["id"], b["text"], [box[0], box[1]+label_h, box[2], box[3]-label_h])
        def stack(bs, box):
            if not bs:
                return
            gap = 18
            h = (box[3]-gap*(len(bs)-1))/len(bs)
            for k, b in enumerate(bs):
                block(b, [box[0], box[1]+k*(h+gap), box[2], h])
        def figure(f, box, k):
            asset = assets[f["asset_id"]]
            caption_h = 62 if f["caption"] else 0
            h = box[3] - caption_h - 12
            scale = min(box[2]/asset["width"], h/asset["height"])
            w, h = asset["width"]*scale, asset["height"]*scale
            bbox = [box[0]+(box[2]-w)/2, box[1], w, h]
            eid = f"figure-{k}"
            elements.append({"id": eid, "kind": "image", "role": "evidence", "bbox": bbox,
                             "asset_id": f["asset_id"], "alt": f.get("alt", f["caption"])})
            if min(w / f.get("panel_count", 1), h) < 140:
                issues.append(issue("PANEL_TOO_SMALL", "WARNING", "Scientific panel needs readability review", n, eid,
                                    detector="geometric-preflight", confidence="MEDIUM"))
            text(eid+":caption", f["caption"], [box[0], box[1]+box[3]-caption_h, box[2], caption_h],
                 "caption", 22, 20, 2)
            issues.append(issue("SCIENTIFIC_PANEL_REVIEW", "REVIEW", "Confirm scientific panel labels and evidence fidelity",
                                n, eid, detector="scientific-review", confidence="MEDIUM"))
        adaptations = []
        if family in ("figure-left", "figure-right") and figs:
            fig_x, txt_x = (56, 784) if family == "figure-left" else (552, 56)
            fig_w, txt_w = (692, 440) if family == "figure-left" else (672, 460)
            figure(figs[0], [fig_x, top, fig_w, bh], 1)
            stack(blocks, [txt_x, top, txt_w, bh])
        elif family in ("dual", "process") and figs:
            text_h = 88 if blocks else 0
            if blocks:
                for k, b in enumerate(blocks):
                    bw = (1168-24*(len(blocks)-1))/len(blocks)
                    block(b, [56+k*(bw+24), top, bw, text_h])
            fw = (1168-32*(len(figs)-1))/len(figs)
            for k, f in enumerate(figs):
                figure(f, [56+k*(fw+32), top+text_h+12, fw, bh-text_h-12], k+1)
        elif family == "evidence":
            for col, role in enumerate(("direct-evidence", "hypothesis")):
                x = 56 + col*600
                text(role+":heading", "Direct evidence" if col == 0 else "Hypothesis (unconfirmed)",
                     [x, top, 568, 44], "heading", 28, 24, 1)
                stack([b for b in blocks if b["component"] == role], [x, top+56, 568, bh-56])
        else:
            if blocks:
                w = (1168-32*(len(blocks)-1))/len(blocks)
                for k, b in enumerate(blocks):
                    block(b, [56+k*(w+32), top, w, bh])
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
        failed_slides = {i["slide"] for i in issues if i["rule"] == "SPLIT_REQUIRED"}
        for n in failed_slides:
            alternative["slides"][n-1]["presentation"]["variant"] = "spacious"
        retry_layout, retry_issues = compile_deck(alternative, base, _retry=False)
        if retry_layout and not any(i["severity"] == "FAIL" for i in retry_issues):
            retry_layout["ir_sha256"] = digest(ir)
            retry_layout["selected_variants"] = {str(n): "spacious" for n in sorted(failed_slides)}
            return retry_layout, retry_issues
    return {"schema_version": "2.0", "ir_sha256": digest(ir), "slide_size": [WIDTH, HEIGHT],
            "assets": assets, "font_hashes": {p: file_hash(Path(p)) for p in font_paths.values()},
            "slides": slides}, issues
