"""Deterministic literature-workflow analysis and hand-off artifacts.

This module intentionally does not call an LLM. It prepares a traceable,
line-addressable evidence package that the Harness agent or another plugin can
use without trusting an opaque summary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .workflow_audits import (
    audit_quantities_enhanced,
    audit_retrieval_enhanced,
    audit_source_dependencies,
    audit_structure_enhanced,
    build_evidence_registry,
    synthesis_gate,
)

from .evidence_graph import build_document_graph, search_graph
from .paper_tools import source_fingerprint


WORKFLOW_SCHEMA_VERSION = 4

DEFAULT_EVIDENCE_QUERIES: tuple[dict[str, str], ...] = (
    {
        "query_id": "objective",
        "intent": "objective",
        "label": "Research objective",
        "query": (
            "abstract objective objectives purpose aim motivation research question "
            "摘要 目的 目标 动机 研究问题"
        ),
    },
    {
        "query_id": "methods",
        "intent": "methods",
        "label": "Methods and conditions",
        "query": (
            "method methods methodology experiment experimental computational simulation "
            "sample materials measurement setup parameter condition "
            "方法 实验 计算 模拟 样品 材料 测量 参数 条件"
        ),
    },
    {
        "query_id": "results",
        "intent": "key_results",
        "label": "Results and conclusions",
        "query": (
            "result results finding findings discussion conclusion conclusions performance "
            "value observation mechanism "
            "结果 发现 讨论 结论 性能 数值 观测 机制"
        ),
    },
    {
        "query_id": "limitations",
        "intent": "limitations",
        "label": "Limitations and uncertainty",
        "query": (
            "limitation limitations uncertainty uncertainties error errors challenge challenges "
            "future work assumption assumptions constraint requirement viewing condition "
            "局限 限制 不确定性 误差 挑战 未来 假设 约束 条件"
        ),
    },
)

HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)\s*$")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
ARXIV_RE = re.compile(r"\b(?:arXiv\s*:\s*)?\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
FIGURE_CAPTION_RE = re.compile(r"(?im)^\s*(?:figure|fig\.?|图)\s*[\dA-Z一二三四五六七八九十]+[.:\s]")
TABLE_CAPTION_RE = re.compile(r"(?im)^\s*(?:table|表)\s*[\dA-Z一二三四五六七八九十]+[.:\s]")
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"(?m)^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
CITATION_RE = re.compile(r"\[(?:\d+(?:\s*[-,]\s*\d+)*)\]")
SUPERSCRIPT_CITATION_RE = re.compile(r"\$\s*\^\{\s*\d+(?:\s*[-,]\s*\d+)*\s*\}\s*\$")
TITLE_BOILERPLATE_RE = re.compile(
    r"^(?:article type|research article|original article|review article|contents?|"
    r"(?:\d+(?:\.\d+)*\s*)?(?:abstract|introduction|background|methods?|methodology|results?|discussion|conclusions?|summary|references?|bibliography|acknowledgements?|conflicts? of interest)|"
    r"摘要|引言|背景|方法|实验方法|结果|讨论|结论|总结|参考文献|致谢)$",
    re.IGNORECASE,
)

SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "abstract": re.compile(r"\babstract\b|摘要", re.IGNORECASE),
    "introduction": re.compile(r"\bintroduction\b|\bbackground\b|引言|背景", re.IGNORECASE),
    "methods": re.compile(
        r"\bmethods?\b|\bmethodology\b|\bexperimental\b|\bcomputational\b|方法|实验|计算",
        re.IGNORECASE,
    ),
    "results": re.compile(r"\bresults?\b|\bfindings?\b|结果|发现", re.IGNORECASE),
    "discussion": re.compile(r"\bdiscussion\b|讨论", re.IGNORECASE),
    "conclusion": re.compile(r"\bconclusions?\b|\bsummary\b|结论|总结", re.IGNORECASE),
    "references": re.compile(r"\breferences?\b|\bbibliography\b|参考文献", re.IGNORECASE),
}

SUPPLEMENT_TOKENS = (
    "supp",
    "supporting",
    "supplement",
    "appendix",
    "additional",
    "si_",
    "-si",
    "补充",

    "附录",
)
QUERY_INTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "sample_preparation",
        re.compile(
            r"sample.*(?:prepar|fabricat|synthesi)|prepar.*sample|fabrication procedure|"
            r"样品.*(?:制备|合成)|制备方法|合成流程|前处理",
            re.IGNORECASE,
        ),
    ),
    (
        "physical_mechanism",
        re.compile(
            r"physical picture|working principle|mechanism|morphology|field distribution|"
            r"物理图像|物理机制|作用机理|微观形貌",
            re.IGNORECASE,
        ),
    ),
    (
        "key_results",
        re.compile(
            r"key results?|main findings?|performance|关键.*结果|核心结论|性能数据",
            re.IGNORECASE,
        ),
    ),
    (
        "limitations",
        re.compile(
            r"limitations?|drawbacks?|future outlook|uncertaint|局限|不足|未来展望",
            re.IGNORECASE,
        ),
    ),
)

INTENT_QUERY_EXPANSIONS: dict[str, str] = {
    "objective": "abstract motivation purpose aim present demonstrate propose",
    "methods": (
        "methods materials experimental preparation fabrication synthesis polymerization "
        "substrate printing coating curing processing measurement simulation"
    ),
    "sample_preparation": (
        "sample preparation fabrication synthesis polymerization materials substrate substrates pretreatment plasma hydrophobic silane "
        "reagent styrene acrylic acid methyl methacrylate PDMS formamide ink formulation "
        "printing coating curing peeling transfer rolling winding processing experimental details"
    ),
    "physical_mechanism": (
        "physical mechanism structure morphology optical field distribution light propagation "
        "photonic bandgap total internal reflection interference simulation working principle"
    ),
    "key_results": (
        "results conclusions demonstrate achieve yield resolution stability performance "
        "scalability tunability cycle metre-scale"
    ),
    "limitations": (
        "limitation constraint challenge uncertainty requirement depends recommended viewing "
        "illumination angle substrate background assumption future supplementary information discussions evidence dependency unavailable"
    ),
}

EVIDENCE_TYPES = (
    "direct_observation",
    "measurement",
    "simulation",
    "fit",
    "author_inference",
    "reviewer_inference",
    "extrapolation",
    "method_protocol",
    "figure_caption",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalise_inline(value: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_~]+", "", value).replace(chr(96), "")
    return re.sub(r"\s+", " ", value).strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalised = value.strip()
        key = normalised.casefold()
        if normalised and key not in seen:
            seen.add(key)
            result.append(normalised)
    return result


def _language_profile(markdown: str) -> str:
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", markdown))
    latin_count = len(re.findall(r"[A-Za-z]", markdown))
    if cjk_count and latin_count and min(cjk_count, latin_count) / max(cjk_count, latin_count) >= 0.12:
        return "mixed"
    if cjk_count > latin_count * 0.15:
        return "zh-dominant"
    return "latin-dominant"


def extract_metadata(markdown: str, source_path: Path) -> dict[str, Any]:
    """Extract conservative identifiers and structural metadata."""

    heading_matches = list(HEADING_RE.finditer(markdown))
    level_one = [match for match in heading_matches if len(match.group(1)) == 1]
    title_candidates = [
        match
        for match in level_one
        if 8 <= len(_normalise_inline(match.group(2))) <= 400
        and not TITLE_BOILERPLATE_RE.fullmatch(_normalise_inline(match.group(2)))
    ]
    if title_candidates:
        title_match = title_candidates[0]
        title_guess = _normalise_inline(title_match.group(2))
        title_source = "filtered_level_one_heading"
    else:
        title_guess = source_path.stem
        title_source = "source_filename"

    dois = _dedupe(match.group(0).rstrip(".,;:)]}") for match in DOI_RE.finditer(markdown))
    arxiv_ids = _dedupe(
        re.sub(r"(?i)^arXiv\s*:\s*", "", match.group(0))
        for match in ARXIV_RE.finditer(markdown)
    )
    urls = _dedupe(match.group(0).rstrip(".,;:)]}") for match in URL_RE.finditer(markdown))
    headings = [_normalise_inline(match.group(2)) for match in heading_matches]
    section_coverage = {
        name: any(pattern.search(heading) for heading in headings)
        for name, pattern in SECTION_PATTERNS.items()
    }

    return {
        "title_guess": title_guess,
        "title_source": title_source,
        "language_profile": _language_profile(markdown),
        "dois": dois[:50],
        "arxiv_ids": arxiv_ids[:20],
        "urls": urls[:50],
        "section_headings": headings,
        "section_coverage": section_coverage,
    }


def audit_extraction(markdown: str, chunk_count: int) -> dict[str, Any]:
    """Assess OCR/Markdown usability, not the scientific merit of the paper."""

    lines = markdown.splitlines()
    nonempty_lines = [re.sub(r"\s+", " ", line.strip()) for line in lines if line.strip()]
    duplicate_candidates = [line for line in nonempty_lines if len(line) >= 30]
    duplicate_counter = Counter(duplicate_candidates)
    duplicate_instances = sum(count - 1 for count in duplicate_counter.values() if count > 1)
    duplicate_ratio = duplicate_instances / max(1, len(duplicate_candidates))
    replacement_count = markdown.count("\ufffd")
    replacement_ratio = replacement_count / max(1, len(markdown))
    heading_count = len(HEADING_RE.findall(markdown))
    alphabetic_count = len(re.findall(r"[A-Za-z\u3400-\u9fff]", markdown))
    readable_ratio = alphabetic_count / max(1, len(markdown))
    broken_hyphen_lines = sum(1 for line in nonempty_lines if re.search(r"[A-Za-z]{3,}-$", line))
    markdown_images = len(MARKDOWN_IMAGE_RE.findall(markdown))
    figure_captions = len(FIGURE_CAPTION_RE.findall(markdown))
    table_captions = len(TABLE_CAPTION_RE.findall(markdown))
    markdown_tables = len(MARKDOWN_TABLE_SEPARATOR_RE.findall(markdown))
    formula_blocks = markdown.count("$$") // 2 + len(re.findall(r"\\\[(?:.|\n)*?\\\]", markdown))
    inline_formula_markers = max(0, markdown.count("$") - (markdown.count("$$") * 2)) // 2
    citation_markers = len(CITATION_RE.findall(markdown)) + len(
        SUPERSCRIPT_CITATION_RE.findall(markdown)
    )

    metadata = extract_metadata(markdown, Path("document.md"))
    coverage = metadata["section_coverage"]
    warnings: list[dict[str, str]] = []
    score = 100

    if len(markdown) < 500:
        score -= 65
        warnings.append(
            {
                "code": "document_too_short",
                "severity": "high",
                "message": "Extracted Markdown is under 500 characters; OCR likely failed or the input is incomplete.",
            }
        )
    elif len(markdown) < 3000:
        score -= 25
        warnings.append(
            {
                "code": "document_short",
                "severity": "medium",
                "message": "Extracted Markdown is unusually short for a paper; inspect the source and page coverage.",
            }
        )

    if heading_count == 0:
        score -= 15
        warnings.append(
            {
                "code": "no_headings",
                "severity": "medium",
                "message": "No Markdown headings were found, so section boundaries may be unreliable.",
            }
        )

    if replacement_ratio > 0.005:
        score -= 35
        warnings.append(
            {
                "code": "replacement_characters_high",
                "severity": "high",
                "message": "Many Unicode replacement characters were found; rerun OCR or review encoding.",
            }
        )
    elif replacement_ratio > 0.0002:
        score -= 10
        warnings.append(
            {
                "code": "replacement_characters_present",
                "severity": "medium",
                "message": "Unicode replacement characters are present and may affect evidence retrieval.",
            }
        )

    if duplicate_ratio > 0.15:
        score -= 20
        warnings.append(
            {
                "code": "duplicate_lines_high",
                "severity": "medium",
                "message": "Repeated long lines suggest duplicated headers, footers, or OCR blocks.",
            }
        )
    elif duplicate_ratio > 0.05:
        score -= 7
        warnings.append(
            {
                "code": "duplicate_lines_present",
                "severity": "low",
                "message": "Some repeated long lines were detected.",
            }
        )

    if readable_ratio < 0.35:
        score -= 15
        warnings.append(
            {
                "code": "readable_text_ratio_low",
                "severity": "medium",
                "message": "The ratio of readable letters/CJK characters is low; formulas or OCR noise may dominate.",
            }
        )

    missing_core = [name for name in ("abstract", "methods", "results", "conclusion") if not coverage[name]]
    if len(missing_core) >= 3:
        score -= 10
        warnings.append(
            {
                "code": "core_sections_missing",
                "severity": "low",
                "message": "Several common paper sections were not identified: " + ", ".join(missing_core) + ".",
            }
        )

    score = max(0, min(100, score))
    if score < 45:
        readiness = "blocked"
    elif score < 75 or any(item["severity"] == "high" for item in warnings):
        readiness = "review"
    else:
        readiness = "ready"

    return {
        "scope": "OCR/Markdown extraction usability only; not scientific-quality assessment",
        "score": score,
        "readiness": readiness,
        "metrics": {
            "char_count": len(markdown),
            "line_count": len(lines),
            "nonempty_line_count": len(nonempty_lines),
            "heading_count": heading_count,
            "chunk_count": chunk_count,
            "readable_character_ratio": round(readable_ratio, 6),
            "replacement_character_count": replacement_count,
            "replacement_character_ratio": round(replacement_ratio, 8),
            "duplicate_long_line_ratio": round(duplicate_ratio, 6),
            "broken_hyphen_line_count": broken_hyphen_lines,
        },
        "content_inventory": {
            "markdown_image_count": markdown_images,
            "figure_caption_count": figure_captions,
            "table_caption_count": table_captions,
            "markdown_table_count": markdown_tables,
            "formula_block_count": formula_blocks,
            "inline_formula_estimate": inline_formula_markers,
            "citation_marker_count": citation_markers,
        },
        "section_coverage": coverage,
        "warnings": warnings,
    }


def audit_quantities(markdown: str) -> dict[str, Any]:
    """Public wrapper for the relation- and symbol-aware quantity audit."""
    return audit_quantities_enhanced(markdown)


def synthesis_contract() -> dict[str, Any]:
    """Describe the evidence ledger expected from a downstream model."""

    return {
        "required_claim_fields": [
            "claim",
            "evidence_refs",
            "evidence_type",
            "confidence",
            "needs_review",
        ],
        "evidence_ref_format": {
            "evidence_id": "EV####",
            "span_id": "S####",
            "chunk_id": "E###",
            "source_lines": {"start": "integer", "end": "integer"},
            "source_chars": {"start": "integer", "end": "integer"},
            "page_or_figure": "optional string",
        },
        "allowed_evidence_types": list(EVIDENCE_TYPES),
        "rules": [
            "Attach evidence to each major claim and every reported number.",
            "Keep laboratory, optimized batch, and roll-to-roll process conditions separate.",
            "Separate test conditions from observed performance.",
            "Cite EV#### as the primary evidence reference; E### is only a coarse parent chunk.",
            "Preserve span character offsets when reading order is under review.",
            "Separate author-stated limitations from reviewer-inferred limitations.",
            "Do not silently merge differing values or repair missing signs and units.",
        ],
    }


def _normalise_document_stem(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", value.casefold()).strip()


def discover_related_documents(
    source_path: Path,
    project_root: Path,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return only filename-linked supplements or close sibling documents."""

    parent = source_path.parent
    source_stem = _normalise_document_stem(source_path.stem)
    results: list[dict[str, Any]] = []
    for candidate in sorted(parent.rglob("*"), key=lambda item: str(item).casefold()):
        if not candidate.is_file() or candidate.resolve() == source_path.resolve():
            continue
        if candidate.suffix.lower() not in {".pdf", ".md"}:
            continue
        resolved = candidate.resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError:
            continue

        raw_stem = candidate.stem.casefold()
        has_supplement_token = any(token in raw_stem for token in SUPPLEMENT_TOKENS)
        family_stem = raw_stem
        for token in sorted(SUPPLEMENT_TOKENS, key=len, reverse=True):
            family_stem = family_stem.replace(token, " ")
        family_stem = _normalise_document_stem(family_stem)
        similarity = SequenceMatcher(None, source_stem, family_stem).ratio()
        exact_family = bool(source_stem) and family_stem == source_stem
        same_stem = _normalise_document_stem(raw_stem) == source_stem
        nested_family = (
            candidate.parent != parent
            and _normalise_document_stem(candidate.parent.name) == source_stem
        )
        close_sibling = len(source_stem) >= 4 and similarity >= 0.82
        if not (same_stem or exact_family or nested_family or close_sibling):
            continue

        role = "supplementary_candidate" if has_supplement_token else "related_candidate"
        results.append(
            {
                "path": str(resolved),
                "type": candidate.suffix.lower().lstrip("."),
                "role": role,
                "size_bytes": candidate.stat().st_size,
                "match_reason": (
                    "supplement_filename"
                    if has_supplement_token and exact_family
                    else "same_document_stem"
                    if same_stem
                    else "matching_document_folder"
                    if nested_family
                    else "high_filename_similarity"
                ),
                "filename_similarity": round(similarity, 3),
            }
        )
        if len(results) >= limit:
            break
    return results


def infer_query_intent(query: str) -> str:
    for intent, pattern in QUERY_INTENT_RULES:
        if pattern.search(query):
            return intent
    return "general"


def _expanded_query(query: str, intent: str) -> str:
    expansion = INTENT_QUERY_EXPANSIONS.get(intent, "")
    return re.sub(r"\s+", " ", f"{query} {expansion}").strip()


def build_evidence_queries(
    custom_queries: Iterable[str],
    *,
    include_defaults: bool = True,
) -> list[dict[str, Any]]:
    query_specs: list[dict[str, Any]] = []
    if include_defaults:
        for item in DEFAULT_EVIDENCE_QUERIES:
            spec = dict(item)
            spec["expanded_query"] = _expanded_query(spec["query"], spec["intent"])
            spec["query_expansion_applied"] = True
            spec["language_bridge_applied"] = False
            query_specs.append(spec)

    seen = {item["query"].casefold() for item in query_specs}
    for index, query in enumerate(custom_queries, start=1):
        normalised = re.sub(r"\s+", " ", query.strip())
        if not normalised or normalised.casefold() in seen:
            continue
        seen.add(normalised.casefold())
        intent = infer_query_intent(normalised)
        expanded = _expanded_query(normalised, intent)
        query_specs.append(
            {
                "query_id": f"custom-{index:02d}",
                "label": f"Custom question {index}",
                "query": normalised,
                "intent": intent,
                "expanded_query": expanded,
                "query_expansion_applied": expanded != normalised,
                "language_bridge_applied": bool(
                    re.search(r"[\u3400-\u9fff]", normalised) and intent != "general"
                ),
            }
        )
    return query_specs


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _escape_table(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _evidence_report_v4(workflow: dict[str, Any]) -> str:
    """Render registry text once, then map every query to EV identifiers."""

    source = workflow["source"]
    dimensions = workflow["quality_dimensions"]
    synthesis = workflow["synthesis_readiness"]
    lines = [
        "# PaperWorkflow evidence package",
        "",
        f"- Workflow ID: {workflow['workflow_id']}",
        f"- Input: {source['input_path']}",
        f"- Markdown: {source['markdown_path']}",
        f"- Text-capture fidelity: **{dimensions['extraction']['readiness']}** ({dimensions['extraction']['score']}/100)",
        f"- Scientific-synthesis readiness: **{synthesis['readiness']}** ({synthesis['score']}/100)",
        f"- Mechanism completeness: **{synthesis['mechanism_completeness']}**",
        "",
        "## Readiness gates",
        "",
        "| Gate | Status | Meaning |",
        "|---|---|---|",
    ]
    for item in synthesis["gates"]:
        lines.append(f"| {_escape_table(item['gate'])} | {item['status']} | {_escape_table(item['message'])} |")

    lines.extend([
        "",
        "## Quality dimensions",
        "",
        "| Dimension | Score | Readiness |",
        "|---|---:|---|",
    ])
    for name in (
        "extraction", "structure", "reading_order", "semantic_structure",
        "chunk_coherence", "retrieval", "quantities", "dependencies",
    ):
        item = dimensions[name]
        lines.append(f"| {name} | {item['score']} | {item['readiness']} |")

    lines.extend(["", "### Audit warnings", ""])
    warning_count = 0
    for name in ("extraction", "structure", "retrieval", "quantities", "dependencies"):
        for warning in dimensions[name].get("warnings", []):
            warning_count += 1
            lines.append(f"- [{name}/{warning['severity']}] {warning['code']}: {warning['message']}")
    if not warning_count:
        lines.append("- No quality warnings.")

    lines.extend([
        "",
        "## Semantic outline",
        "",
        "| Chunk | Raw heading | Semantic owner | Kind | Lines | Figure parent(s) |",
        "|---|---|---|---|---:|---|",
    ])
    for section in workflow["outline"]["sections"]:
        lines.append(
            f"| {section['chunk_id']} | {_escape_table(section['raw_heading'])} | "
            f"{_escape_table(section['semantic_heading'])} | {section['heading_kind']} | "
            f"{section['line_start']}-{section['line_end']} | "
            f"{_escape_table(', '.join(section['figure_parents']))} |"
        )

    lines.extend(["", "## Query-to-evidence map", ""])
    for group in workflow["evidence"]:
        coverage = group.get("coverage", {})
        ids = ", ".join(group.get("evidence_ids", [])) or "(none)"
        alias = ""
        if group.get("canonical_query_id") != group["query_id"]:
            alias = f"; canonical: {group['canonical_query_id']}"
        lines.extend([
            f"### {group['label']} ({group['query_id']})",
            "",
            f"- Intent: {group.get('intent', 'general')}{alias}",
            f"- Status: **{group.get('retrieval_status', 'unknown')}**",
            f"- Evidence: {ids}",
        ])
        if coverage.get("facet_count"):
            lines.append(f"- Coverage: {coverage['coverage_ratio']:.1%}; missing: {', '.join(coverage['missing_facets']) or '(none)'}")
        lines.append("")

    lines.extend([
        "## Evidence Registry",
        "",
        "Evidence text appears only here; queries above reference these stable IDs.",
        "",
    ])
    if not workflow["evidence_registry"]:
        lines.append("- No evidence spans were registered.")
    for item in workflow["evidence_registry"]:
        text = re.sub(r"\s+", " ", item["text"]).strip()
        lines.extend([
            f"### {item['evidence_id']} · {item['span_id']} · {item['chunk_id']}",
            "",
            f"- Source lines: {item['source_lines']['start']}-{item['source_lines']['end']}",
            f"- Source chars: {item['source_chars']['start']}-{item['source_chars']['end']}",
            f"- Modality / support: {item['modality']} / {item['support_type']}",
            f"- Used by: {', '.join(item['query_ids'])}",
            f"- Text: {text}",
            "",
        ])

    lines.extend(["## Referenced source dependencies", ""])
    dependencies = workflow["source_dependencies"]["dependencies"]
    if not dependencies:
        lines.append("- No external supplementary dependency was detected.")
    for item in dependencies:
        lines.append(
            f"- {item['dependency_type']}: **{item['availability']}**; "
            f"{item['reference_count']} reference(s); examples: "
            + ", ".join(item["reference_examples"][:4])
        )
    lines.extend([
        "",
        "## Claim ledger contract",
        "",
        "Use EV#### plus S####/E###, raw line range and character offsets for every major claim and number.",
        "Treat supplementary-dependent mechanism claims as partial until the referenced files are available.",
        "",
    ])
    return "\n".join(lines)



def build_literature_workflow(
    *,
    markdown_path: Path,
    source_path: Path,
    project_root: Path,
    output_dir: Path,
    custom_queries: Iterable[str] = (),
    include_default_queries: bool = True,
    top_k: int = 5,
    chunk_chars: int = 6000,
    ingestion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and persist one end-to-end literature hand-off package."""

    markdown_path = markdown_path.expanduser().resolve()
    source_path = source_path.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    markdown = markdown_path.read_text(encoding="utf-8")
    graph = build_document_graph(markdown, max_chars=chunk_chars)
    manifest = dict(graph)
    if source_path.suffix.lower() == ".pdf":
        manifest["pdf_path"] = str(source_path)
        try:
            manifest["source_id"] = source_fingerprint(source_path)
        except FileNotFoundError:
            manifest["source_id"] = None
    manifest["markdown_path"] = str(markdown_path)
    outline = [
        {
            key: chunk[key]
            for key in (
                "chunk_id", "heading", "raw_heading", "semantic_heading",
                "heading_kind", "empty_node", "level", "part", "line_start",
                "line_end", "modalities", "figure_parents", "semantic_owner_type",
            )
        }
        for chunk in graph["chunks"]
    ]
    metadata = extract_metadata(markdown, source_path)
    extraction_audit = audit_extraction(markdown, len(outline))
    structure_audit = audit_structure_enhanced(markdown, extraction_audit, manifest)
    quantity_audit = audit_quantities(markdown)
    related_documents = discover_related_documents(source_path, project_root)
    dependency_audit = audit_source_dependencies(markdown, related_documents)

    query_specs = build_evidence_queries(custom_queries, include_defaults=include_default_queries)
    evidence: list[dict[str, Any]] = []
    canonical_by_intent: dict[str, str] = {}
    results_by_canonical: dict[str, list[dict[str, Any]]] = {}
    for query_spec in query_specs:
        intent = query_spec.get("intent", "general")
        canonical_id = (
            canonical_by_intent.setdefault(intent, query_spec["query_id"])
            if intent != "general"
            else query_spec["query_id"]
        )
        if canonical_id not in results_by_canonical:
            coverage_depth = {
                "sample_preparation": 12,
                "physical_mechanism": 9,
                "key_results": 8,
                "limitations": 5,
            }.get(intent, top_k)
            results_by_canonical[canonical_id] = search_graph(
                graph,
                query_spec["expanded_query"],
                top_k=max(top_k, coverage_depth),
                intent=intent,
            )
        evidence.append(
            {
                **query_spec,
                "canonical_query_id": canonical_id,
                "results": results_by_canonical[canonical_id],
            }
        )
    evidence_registry = build_evidence_registry(evidence)
    retrieval_audit = audit_retrieval_enhanced(evidence, evidence_registry)
    synthesis_audit = synthesis_gate(
        extraction_audit,
        structure_audit,
        retrieval_audit,
        quantity_audit,
        dependency_audit,
    )

    markdown_sha256 = _sha256_text(markdown)
    source_sha256 = _sha256_file(source_path)
    run_payload = {
        "source_sha256": source_sha256,
        "markdown_sha256": markdown_sha256,
        "queries": query_specs,
        "top_k": top_k,
        "chunk_chars": chunk_chars,
    }
    workflow_id = hashlib.sha256(
        json.dumps(run_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    generated_at = datetime.now(timezone.utc).isoformat()

    document_manifest_path = output_dir / "document.manifest.json"
    workflow_manifest_path = output_dir / "workflow.json"
    evidence_report_path = output_dir / "evidence.md"

    stages = [
        {
            "stage": "ingestion",
            "status": "completed" if source_path.suffix.lower() == ".pdf" else "skipped",
            "details": ingestion or {"reason": "Markdown input; OCR was not required."},
        },
        {"stage": "metadata", "status": "completed"},
        {"stage": "extraction_quality_audit", "status": "completed"},
        {"stage": "structure_quality_audit", "status": "completed"},
        {"stage": "quantity_consistency_audit", "status": "completed"},
        {"stage": "source_dependency_audit", "status": "completed"},
        {
            "stage": "document_graph",
            "status": "completed",
            "chunk_count": len(outline),
            "span_count": manifest["span_count"],
        },
        {
            "unique_evidence_count": len(evidence_registry),
            "stage": "evidence_retrieval",
            "status": "completed" if evidence else "skipped",
            "query_count": len(evidence),
            "readiness": retrieval_audit["readiness"],
        },
        {"stage": "artifact_export", "status": "completed"},
    ]

    workflow: dict[str, Any] = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "workflow_id": workflow_id,
        "generated_at": generated_at,
        "source": {
            "input_path": str(source_path),
            "input_type": source_path.suffix.lower().lstrip("."),
            "markdown_path": str(markdown_path),
            "source_fingerprint": source_fingerprint(source_path),
            "source_sha256": source_sha256,
            "markdown_sha256": markdown_sha256,
            "mineru": ingestion,
        },
        "stages": stages,
        "metadata": metadata,
        "quality_audit": extraction_audit,
        "quality_dimensions": {
            "extraction": extraction_audit,
            "structure": structure_audit,
            "reading_order": structure_audit["reading_order_integrity"],
            "semantic_structure": structure_audit["semantic_structure_integrity"],
            "chunk_coherence": structure_audit["chunk_coherence"],
            "retrieval": retrieval_audit,
            "quantities": quantity_audit,
            "dependencies": dependency_audit,
        },
        "synthesis_readiness": synthesis_audit,
        "outline": {
            "span_count": manifest["span_count"],
            "chunk_count": len(outline),
            "chunk_chars": chunk_chars,
            "sections": outline,
        },
        "evidence": evidence,
        "evidence_registry": evidence_registry,
        "source_dependencies": dependency_audit,
        "related_documents": related_documents,
        "claim_ledger_contract": synthesis_contract(),
        "artifacts": {
            "artifact_dir": str(output_dir),
            "workflow_manifest_path": str(workflow_manifest_path),
            "document_manifest_path": str(document_manifest_path),
            "evidence_report_path": str(evidence_report_path),
        },
        "handoff": {
            "primary_markdown_path": str(markdown_path),
            "preferred_context_path": str(evidence_report_path),
            "provenance_path": str(workflow_manifest_path),
            "line_addressable_manifest_path": str(document_manifest_path),
            "needs_human_review": synthesis_audit["readiness"] != "ready",
            "instruction": (
                "Downstream plugins should read the evidence package first, use the primary "
                "Markdown when more context is needed, and cite EV#### plus S####/E###, exact "
                "line ranges and character offsets for every major claim and number. Follow "
                "claim_ledger_contract; keep process modes and evidence types separate."
            ),
        },
        "recommended_next_steps": [
            "Review all quality dimensions before scientific synthesis.",
            "Treat extraction readiness as OCR/Markdown usability only.",
            "Use evidence.md as the compact input for a summarization, comparison, or tutorial plugin.",
            "Use EV#### as the primary evidence reference; retain S####/E### and exact offsets.",
            "Preserve differing numerical ranges with their individual contexts.",
            "Inspect only filename-linked supplementary_candidate files.",
        ],
    }

    _atomic_write_json(document_manifest_path, manifest)
    _atomic_write_text(evidence_report_path, _evidence_report_v4(workflow))
    _atomic_write_json(workflow_manifest_path, workflow)
    return workflow
