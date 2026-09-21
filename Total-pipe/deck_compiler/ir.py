"""Canonical input validation and read-only derived views."""
import re

from .catalog import ARCHETYPES, COMPONENTS
from .contracts import digest, issue


SOURCE_FIGURE = re.compile(r"^[1-9][0-9]*[a-z]$")
CAPTION_FIGURE = re.compile(r"\bFig(?:ure)?\.?\s*([1-9][0-9]*)\s*([a-z])", re.IGNORECASE)


def caption_figure_ids(caption):
    """Return normalized paper panel ids explicitly named by a caption."""
    return {f"{number}{panel.lower()}" for number, panel in CAPTION_FIGURE.findall(caption or "")}


def validate(ir):
    errors = []
    def check(ok, message, slide=None, rule="IR_INVALID"):
        if not ok:
            errors.append(issue(rule, "FAIL", message, slide))
    check(isinstance(ir, dict), "Deck IR must be an object")
    if errors:
        return errors
    check(ir.get("schema_version") == "2.0", "schema_version must be 2.0")
    check(isinstance(ir.get("deck_id"), str) and bool(ir.get("deck_id")), "deck_id required")
    theme = ir.get("theme", {})
    check(isinstance(theme, dict) and all(isinstance(theme.get(k), str) and theme[k]
          for k in ("font_family", "font_file", "bold_font_file")), "Explicit theme fonts required")
    slides = ir.get("slides")
    check(isinstance(slides, list) and bool(slides), "slides must be a nonempty list")
    if not isinstance(slides, list):
        return errors
    assets = ir.get("assets", {})
    check(isinstance(assets, dict), "assets must be an object")
    if not isinstance(assets, dict):
        return errors
    for key, asset in assets.items():
        check(isinstance(asset, dict) and isinstance(asset.get("path"), str), f"asset {key}: path required")
        if isinstance(asset, dict) and "source_figure" in asset:
            check(isinstance(asset.get("source_figure"), str) and
                  bool(SOURCE_FIGURE.fullmatch(asset["source_figure"])),
                  f"asset {key}: source_figure must look like 3a", rule="FIGURE_PROVENANCE_INVALID")
    seen = set()
    for n, s in enumerate(slides, 1):
        if not isinstance(s, dict):
            check(False, "Slide must be an object", n)
            continue
        sid = s.get("id")
        check(isinstance(sid, str) and bool(sid) and sid not in seen, "Unique slide id required", n)
        if isinstance(sid, str):
            seen.add(sid)
        sem, comp, pres = (s.get(k) for k in ("semantic", "composition", "presentation"))
        if not all(isinstance(x, dict) for x in (sem, comp, pres)):
            check(False, "semantic/composition/presentation objects required", n)
            continue
        for key in ("title", "purpose", "takeaway", "speaker_notes"):
            check(isinstance(sem.get(key), str) and bool(sem.get(key, "").strip()), f"semantic.{key} required", n)
        for key in ("evidence_refs", "caveats"):
            check(isinstance(sem.get(key), list) and all(isinstance(v, str) for v in sem[key]), f"semantic.{key} list required", n)
        archetype = comp.get("archetype")
        check(archetype in ARCHETYPES, f"Unknown archetype: {archetype}", n)
        blocks, figures = comp.get("blocks"), comp.get("figure_refs")
        if not isinstance(blocks, list) or not isinstance(figures, list):
            check(False, "composition.blocks/figure_refs must be lists", n)
            continue
        ids = set()
        for b in blocks:
            if not isinstance(b, dict):
                check(False, "Block must be an object", n)
                continue
            bid = b.get("id")
            check(isinstance(bid, str) and bid and bid not in ids, "Unique block id required", n)
            if isinstance(bid, str):
                ids.add(bid)
            check(b.get("component") in COMPONENTS, "Unknown component", n)
            check(isinstance(b.get("text"), str) and bool(b["text"].strip()), "Block text required", n)
            check(b.get("text_flow", "auto") in ("auto", "plain", "distributed_arrow_list"),
                  "Unknown block text_flow", n)
            check(not any(k in b for k in ("bbox", "x", "y", "w", "h")), "Geometry belongs to compiled layout", n)
        for f in figures:
            check(isinstance(f, dict) and f.get("asset_id") in assets and
                  isinstance(f.get("caption"), str), "Figure needs asset reference and caption", n)
            if not isinstance(f, dict) or f.get("asset_id") not in assets:
                continue
            asset = assets[f["asset_id"]]
            expected = f.get("source_figure")
            actual = asset.get("source_figure") if isinstance(asset, dict) else None
            check(isinstance(expected, str) and bool(SOURCE_FIGURE.fullmatch(expected)),
                  "Figure reference requires source_figure such as 3a", n,
                  "FIGURE_PROVENANCE_REQUIRED")
            check(isinstance(actual, str) and bool(SOURCE_FIGURE.fullmatch(actual)),
                  f"Asset {f['asset_id']} requires source_figure", n,
                  "FIGURE_PROVENANCE_REQUIRED")
            if isinstance(expected, str) and isinstance(actual, str):
                check(expected == actual,
                      f"Caption expects Fig.{expected}, but asset {f['asset_id']} is Fig.{actual}", n,
                      "FIGURE_SOURCE_MISMATCH")
                check(expected in caption_figure_ids(f.get("caption", "")),
                      f"Caption must explicitly name Fig.{expected}", n,
                      "FIGURE_CAPTION_MISMATCH")
        if archetype in ARCHETYPES:
            cap = ARCHETYPES[archetype]
            check(len(blocks) <= cap["blocks"] and len(figures) <= cap["figures"],
                  "Archetype block/figure capacity exceeded", n, "CONTENT_CAPACITY_EXCEEDED")
            if archetype == "evidence-hypothesis":
                check(all(b.get("component") in ("direct-evidence", "hypothesis") for b in blocks)
                      and all(sum(b.get("component") == role for b in blocks) <= 4
                              for role in ("direct-evidence", "hypothesis")),
                      "Evidence and hypothesis must be separate, each <= 4", n, "CONTENT_CAPACITY_EXCEEDED")
        for field, limit in (("title", 120), ("takeaway", 180)):
            check(isinstance(sem.get(field), str) and len(sem[field]) <= limit,
                  f"{field} exceeds {limit} characters", n, "CONTENT_CAPACITY_EXCEEDED")
        check(all(isinstance(b, dict) and len(b.get("text", "")) <= 600 for b in blocks),
              "Block exceeds 600 characters", n, "CONTENT_CAPACITY_EXCEEDED")
        check(all(isinstance(f, dict) and len(f.get("caption", "")) <= 180 and
                  isinstance(f.get("panel_count", 1), int) and 1 <= f.get("panel_count", 1) <= 6 for f in figures),
              "Caption/panel capacity exceeded", n, "CONTENT_CAPACITY_EXCEEDED")
        check(not pres.get("optional_overrides"), "Geometry overrides unsupported in v2.0; choose a variant", n)
        check(pres.get("variant", "default") in ("default", "spacious"), "Unknown component variant", n)
    return errors


def derive(ir, layout):
    """Disposable projections; never accepted as compiler input."""
    provenance = {"derived_from": "deck_ir.json", "ir_sha256": digest(ir), "read_only": True}
    return {
        "deck_plan.json": {**provenance, "slides": [{"index": n, "slide_id": s["id"],
            "title": s["semantic"]["title"], "layout_id": s["composition"]["archetype"],
            "evidence_ids": s["semantic"]["evidence_refs"]} for n, s in enumerate(ir["slides"], 1)]},
        "visual_manifest.json": {**provenance, "visuals": [{"slide_id": s["id"], **f}
            for s in ir["slides"] for f in s["composition"]["figure_refs"]]},
        "plan_to_layout.json": {**provenance, "slides": [{"slide_id": s["id"], "elements": s["elements"]}
                                                       for s in layout["slides"]]},
        "qa_expectation.json": {**provenance, "slide_count": len(ir["slides"]),
                                "required_renderer": "powerpoint"},
    }
