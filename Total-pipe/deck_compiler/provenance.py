"""Supplement-content provenance checks for canonical Deck IR.

Paper content keeps the existing evidence rules.  This module only answers one
question: is a non-paper addition clearly marked, and does it avoid pretending to
be paper content?  Text-overlap checks against the PaperWorkflow Evidence Store
live in the agent layer, where the normalized evidence corpus is available.
"""
from __future__ import annotations

from .contracts import issue


BASES = ("paper", "supplement")
KINDS = (
    "background",
    "analogy",
    "example",
    "derivation",
    "diagram",
    "comparison",
)
# A constructed example must be recognisable on the page itself.
CONSTRUCTED_MARKERS = (
    "示意",
    "构造",
    "简化",
    "示例",
    "虚构",
    "schematic",
    "constructed",
    "illustrative",
    "for illustration",
)


def _text(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def _strings(value):
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _collect(value, result):
    if isinstance(value, str):
        if value.strip():
            result.append(value)
    elif isinstance(value, list):
        for item in value:
            _collect(item, result)
    elif isinstance(value, dict):
        for key in ("text", "title", "body", "label", "caption", "cells", "content"):
            if key in value:
                _collect(value[key], result)


def _visible(slide):
    sem = slide.get("semantic") if isinstance(slide.get("semantic"), dict) else {}
    comp = slide.get("composition") if isinstance(slide.get("composition"), dict) else {}
    result = []
    for key in ("title", "takeaway"):
        _collect(sem.get(key), result)
    _collect(sem.get("caveats"), result)
    _collect(comp.get("blocks"), result)
    _collect(comp.get("layout_tree"), result)
    _collect(comp.get("figure_refs"), result)
    _collect(comp.get("tables"), result)
    for graphic in comp.get("graphics", []) or []:
        _collect(graphic.get("nodes"), result)
        _collect(graphic.get("labels"), result)
    return " ".join(result).casefold()


def _blocks(slide):
    comp = slide.get("composition") if isinstance(slide.get("composition"), dict) else {}
    blocks = comp.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _supplement_blocks(slide):
    return [block for block in _blocks(slide) if block.get("basis") == "supplement"]


def _paper_asset_ids(ir):
    assets = ir.get("assets") if isinstance(ir.get("assets"), dict) else {}
    return {
        key for key, asset in assets.items()
        if isinstance(asset, dict) and asset.get("origin", "paper") == "paper"
    }


def _uses_paper_figure(slide, paper_assets):
    comp = slide.get("composition") if isinstance(slide.get("composition"), dict) else {}
    for figure in comp.get("figure_refs", []) or []:
        if isinstance(figure, dict) and figure.get("asset_id") in paper_assets:
            return True
    return False


def _has_constructed_marker(slide):
    corpus = _visible(slide)
    return any(marker.casefold() in corpus for marker in CONSTRUCTED_MARKERS)


def _supplement_spec(block):
    spec = block.get("supplement")
    return spec if isinstance(spec, dict) else {}


def _check_supplement_block(block, index, slide_number, constructed_label, problems):
    bid = block.get("id")
    shape = f"blocks[{index}]"
    spec = _supplement_spec(block)
    kind = spec.get("kind")
    if not spec:
        problems.append(issue(
            "SUPPLEMENT_SPEC_MISSING", "FAIL",
            f"{shape} ({bid}): basis=supplement requires a supplement object",
            slide_number, shape, block=bid))
    if kind not in KINDS:
        problems.append(issue(
            "SUPPLEMENT_KIND_INVALID", "FAIL",
            f"{shape} ({bid}): supplement.kind must be one of {list(KINDS)}",
            slide_number, shape, block=bid))
    source = _text(spec.get("source"))
    if not source:
        problems.append(issue(
            "SUPPLEMENT_UNCITED", "INFO",
            f"{shape} ({bid}): supplement has no source note; treat it as unverified",
            slide_number, shape, block=bid))
    assumptions = _strings(spec.get("assumptions"))
    if kind == "derivation" and not assumptions:
        problems.append(issue(
            "SUPPLEMENT_ASSUMPTION_MISSING", "INFO",
            f"{shape} ({bid}): derivation has no stated assumptions",
            slide_number, shape, block=bid))
    if spec.get("constructed") is True and not constructed_label:
        problems.append(issue(
            "SUPPLEMENT_CONSTRUCTED_UNLABELED", "REVIEW",
            f"{shape} ({bid}): a constructed example needs a visible label "
            "(示意/构造/简化/示例)",
            slide_number, shape, block=bid))
    if block.get("evidence_refs"):
        problems.append(issue(
            "SUPPLEMENT_EVIDENCE_FORBIDDEN", "FAIL",
            f"{shape} ({bid}): a supplement block must not carry evidence_refs",
            slide_number, shape, block=bid))


def validate(ir):
    """Return semantic-preflight issues for supplement content on one deck."""
    problems = []
    if not isinstance(ir, dict):
        return problems
    slides = ir.get("slides")
    if not isinstance(slides, list) or not slides:
        return problems
    # Fast path: an all-paper deck keeps the exact pre-supplement behaviour.
    if not any(_supplement_blocks(slide) for slide in slides if isinstance(slide, dict)):
        return problems

    paper_assets = _paper_asset_ids(ir)
    supplement_pages = 0
    paper_pages = 0
    for number, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            continue
        blocks = _blocks(slide)
        supplements = _supplement_blocks(slide)
        sem = slide.get("semantic") if isinstance(slide.get("semantic"), dict) else {}
        all_supplement = bool(blocks) and len(supplements) == len(blocks)
        if all_supplement:
            supplement_pages += 1
            refs = sem.get("evidence_refs")
            if isinstance(refs, list) and refs:
                problems.append(issue(
                    "SUPPLEMENT_EVIDENCE_CONFLICT", "REVIEW",
                    "a supplement-only page carries evidence_refs; move the paper claim "
                    "to a paper block or remove the refs",
                    number, "semantic.evidence_refs"))
            if _uses_paper_figure(slide, paper_assets):
                problems.append(issue(
                    "SUPPLEMENT_PAPER_FIGURE", "FAIL",
                    "a supplement-only page uses a paper figure; add the paper block and "
                    "its evidence_refs, or use a generated/reference figure",
                    number, "composition.figure_refs"))
        else:
            paper_pages += 1

        constructed_label = _has_constructed_marker(slide)
        for index, block in enumerate(blocks):
            basis = block.get("basis", "paper")
            if basis not in BASES:
                problems.append(issue(
                    "SUPPLEMENT_BASIS_INVALID", "FAIL",
                    f"blocks[{index}]: basis must be paper or supplement",
                    number, f"blocks[{index}]", block=block.get("id")))
                continue
            if basis == "supplement":
                _check_supplement_block(block, index, number, constructed_label, problems)
            elif "supplement" in block:
                problems.append(issue(
                    "SUPPLEMENT_ON_PAPER_BLOCK", "FAIL",
                    f"blocks[{index}]: a paper block must not carry a supplement object",
                    number, f"blocks[{index}]", block=block.get("id")))

    if paper_pages and supplement_pages > paper_pages:
        problems.append(issue(
            "SUPPLEMENT_RATIO_HIGH", "INFO",
            f"{supplement_pages} supplement pages against {paper_pages} paper pages; "
            "check whether the deck still leads with the paper",
            detector="semantic-preflight"))
    return problems
