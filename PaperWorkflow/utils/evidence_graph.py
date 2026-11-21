"""Semantic document graph and span-level evidence retrieval.

The raw MinerU Markdown is retained unchanged.  This module adds a second,
semantic address layer so layout headings, figures and interrupted reading
order do not silently become scientific evidence boundaries.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)\s*$")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
FORMULA_RE = re.compile(r"\$\$(?:.|\n)*?\$\$|\\\[(?:.|\n)*?\\\]", re.MULTILINE)
MARKER_RE = re.compile(
    r"(?m)^(?:#{1,6})[ \t]+.+?$|!\[[^\]]*\]\([^)]+\)|\$\$(?:.|\n)*?\$\$|\\\[(?:.|\n)*?\\\]"
)
ENGLISH_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
NUMERIC_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?:%|(?:nm|um|μm|mm|cm|ms|ns|ps|fs|ev|mev|gev|mv|ma|μa|khz|mhz|ghz|hz|db|k|v|a)\b)?(?![A-Za-z0-9_])",
    re.I,
)
REF_TOKEN_RE = re.compile(r"\b(?:fig(?:ure)?\.?\s*(s?\d+[a-z]?)|eq(?:uation)?\.?\s*(\d+)|table\.?\s*(s?\d+))\b", re.I)
CJK_TOKEN_RE = re.compile(r"[\u3400-\u9fff]+")

# Lightweight bilingual scientific synonyms so Chinese queries hit English papers (and vice versa).
_BILINGUAL_QUERY_EXPANSIONS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"公式|方程|推导|表达式|equation|formula", re.I), ("equation", "equations", "formula", "formulas", "eq", "model", "derived", "relation", "公式", "方程")),
    (re.compile(r"对照|基线|比较|对比|control|baseline|comparison", re.I), ("control", "controls", "baseline", "comparison", "compared", "versus", "对照", "基线")),
    (re.compile(r"消融|ablation", re.I), ("ablation", "without", "removed", "消融")),
    (re.compile(r"误差|不确定|标准差|方差|波动|error|uncertainty|std|deviation", re.I), ("error", "errors", "uncertainty", "standard", "deviation", "variance", "sd", "sem", "误差", "不确定")),
    (re.compile(r"局限|边界|限制|条件|适用|limitation|boundary|scope|condition", re.I), ("limitation", "limitations", "limit", "limits", "boundary", "scope", "condition", "conditions", "temperature", "degrades", "局限", "条件")),
    (re.compile(r"方法|制备|合成|初始化|前处理|实验|method|fabricat|prepar|synthesi|initializ", re.I), ("method", "methods", "fabrication", "preparation", "synthesis", "initialization", "experimental", "方法", "制备")),
    (re.compile(r"性能|准确率|精度|开关比|效率|响应|performance|accuracy|efficiency|ratio", re.I), ("performance", "accuracy", "efficiency", "ratio", "responsivity", "gain", "性能", "准确率")),
    (re.compile(r"机制|原理|物理|mechanism|principle|physics", re.I), ("mechanism", "mechanisms", "principle", "principles", "physical", "transport", "injection", "机制", "原理")),
    (re.compile(r"负面|失败|反例|未证实|negative|failure|fail|exception", re.I), ("negative", "failure", "failed", "exception", "cannot", "unresolved", "负面", "反例")),
    (re.compile(r"补充材料|附录|supplementary|extended\s+data", re.I), ("supplementary", "extended", "supporting", "appendix", "补充材料")),
)
_FORMULA_QUERY_RE = re.compile(r"公式|方程|推导|表达式|\b(?:eq(?:uation)?|formula|latex|math)\b", re.I)
SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<!Fig\.)(?<!fig\.)(?<!Eq\.)(?<!eq\.)(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?。！？])\s+(?=(?:[A-Z0-9（(]|[\u3400-\u9fff]))"
)
FIGURE_RE = re.compile(
    r"(?i)\b(?P<label>(?:Extended\s+Data\s+)?(?:Fig(?:ure)?\.?|图)\s*"
    r"(?P<number>\d+[A-Za-z]?))\s*[|:：]"
)
REFERENCE_ENTRY_RE = re.compile(r"^\s*\d{1,3}\.\s+\S")
BOILERPLATE_HEADING_RE = re.compile(r"^article$", re.IGNORECASE)
DEPRIORITIZED_HEADING_RE = re.compile(
    r"data availability|online content|references?|bibliography|additional information|"
    r"acknowledgements?|author contributions?|competing interests?",
    re.IGNORECASE,
)
METHOD_ONLY_HEADING_RE = re.compile(
    r"test$|experimental details|characterizations?|methods?$", re.IGNORECASE
)

SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "data", "for", "from",
    "how", "in", "is", "key", "main", "of", "on", "or", "paper", "the", "to",
    "what", "with", "什么", "如何", "论文", "重点",
}

INTENT_HEADING_PATTERNS: dict[str, re.Pattern[str]] = {
    "objective": re.compile(r"abstract|introduction|conclusions?|summary", re.I),
    "methods": re.compile(
        r"methods?|materials?|experimental|prepar|fabricat|synthesi|processing|"
        r"printing|coating|curing|peeling|characterization|simulation", re.I
    ),
    "sample_preparation": re.compile(
        r"methods?|materials?|prepar|fabricat|synthesi|processing|printing|coating|"
        r"curing|peeling|substrate|polymer|ink", re.I
    ),
    "physical_mechanism": re.compile(
        r"optical|mechanism|simulation|principles?|field|colour|tunability", re.I
    ),
    "key_results": re.compile(
        r"results?|conclusions?|performance|stability|principles?|tunability", re.I
    ),
    "limitations": re.compile(r"limitations?|discussion|performance|stability|conclusions?", re.I),
}

INTENT_DIVERSITY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "sample_preparation": (
        re.compile(r"\bmaterials?\b|styrene|reagent|acrylic acid|methyl methacrylate", re.I),
        re.compile(r"synthesi|emulsion polymerization|nanospheres?|core.shell", re.I),
        re.compile(r"formamide|viscosity|surface tension|colloidal nanoparticle ink|ink exhibits", re.I),
        re.compile(r"plasma|surface.modified|hydrophobic substrates?|silane|sonicated in methanol", re.I),
        re.compile(r"inkjet|print(?:ed|ing)|nozzle|droplet", re.I),
        re.compile(r"coat|blade|embed|penetrate|prepolymer", re.I),
        re.compile(r"polymerization of PDMS|irradiated|PDMS prepolymer was continuously|cured at", re.I),
        re.compile(r"peel|transfer|flipped|rolled up", re.I),
        re.compile(r"roll-to-roll|R2R|winding|rolling|continuous", re.I),
    ),
    "physical_mechanism": (
        re.compile(r"nanoscale|microscale|nanolattice|concave|hemispher", re.I),
        re.compile(r"photonic bandgap|\bPBG\b|wavelength-selective", re.I),
        re.compile(r"total internal reflection|\bTIRs?\b", re.I),
        re.compile(r"interference|dispersion|optical path|phase", re.I),
        re.compile(r"field distribution|field enhancement|simulat|FDTD", re.I),
        re.compile(r"rim|centre|central colour|reflectance|angle-dependent", re.I),
    ),
    "key_results": (
        re.compile(r"metre-scale|million|orders of magnitude|scalab", re.I),
        re.compile(r"yield|dots per inch|dpi|single-pixel|uniformity", re.I),
        re.compile(r"tunable|tunability|redshift|colour mixing|separation", re.I),
        re.compile(r"stability|resistance|ultraviolet|temperature|solvent|washing", re.I),
        re.compile(r"cycle|stretch|bend|twist|mechanical|elongation", re.I),
    ),
    "limitations": (
        re.compile(r"collimated|illumination|viewing conditions", re.I),
        re.compile(r"observation point|observer|distance|angle-dependent", re.I),
        re.compile(r"black (?:background|substrate)|background reflection", re.I),
        re.compile(r"Supplementary|more .*details|online version", re.I),
    ),
}


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _normalise_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip()).rstrip("†")


def terms(value: str) -> list[str]:
    """Tokenize English, numeric quantities, figure/equation refs, and CJK text."""

    result = [
        token.lower()
        for token in ENGLISH_TOKEN_RE.findall(value)
        if len(token) > 1 and token.lower() not in SEARCH_STOPWORDS
    ]
    for num in NUMERIC_TOKEN_RE.findall(value):
        cleaned = num.lower().strip()
        if cleaned:
            result.append(cleaned)
            stem = re.match(r"\d+(?:\.\d+)?", cleaned)
            if stem and stem.group(0) != cleaned and (len(stem.group(0)) >= 2 or "." in stem.group(0)):
                result.append(stem.group(0))
    for fig_id, eq_id, tab_id in REF_TOKEN_RE.findall(value):
        if fig_id:
            result.append(f"fig:{fig_id.lower()}")
        if eq_id:
            result.append(f"eq:{eq_id.lower()}")
        if tab_id:
            result.append(f"table:{tab_id.lower()}")
    for sequence in CJK_TOKEN_RE.findall(value):
        if sequence in SEARCH_STOPWORDS:
            continue
        if len(sequence) <= 4:
            result.append(sequence)
        if len(sequence) >= 2:
            result.extend(
                sequence[index:index + 2]
                for index in range(len(sequence) - 1)
                if sequence[index:index + 2] not in SEARCH_STOPWORDS
            )
    return result


def expand_query_terms(query: str) -> list[str]:
    """Return original query terms plus lightweight bilingual scientific synonyms."""
    base = terms(query)
    seen = set(base)
    expanded = list(base)
    for pattern, synonyms in _BILINGUAL_QUERY_EXPANSIONS:
        if pattern.search(query):
            for syn in synonyms:
                for tok in terms(syn):
                    if tok not in seen:
                        expanded.append(tok)
                        seen.add(tok)
    return expanded


def split_chunks(markdown: str, max_chars: int = 6000) -> list[dict[str, Any]]:
    """Build raw chunks while separating layout headings from semantic ownership."""

    if max_chars < 200:
        raise ValueError("max_chars must be at least 200")
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(HEADING_RE.finditer(text))
    ranges: list[tuple[int, int, str, int]] = []
    if not matches:
        ranges.append((0, len(text), "Document", 0))
    else:
        if matches[0].start() > 0 and text[:matches[0].start()].strip():
            ranges.append((0, matches[0].start(), "Preamble", 0))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            ranges.append((match.start(), end, _normalise_title(match.group(2)), len(match.group(1))))

    chunks: list[dict[str, Any]] = []
    chunk_number = 0
    semantic_owner = "Document"
    for start, end, raw_heading, level in ranges:
        section_text = text[start:end].strip()
        if not section_text:
            continue
        heading_only = bool(HEADING_RE.fullmatch(section_text))
        is_boilerplate = bool(BOILERPLATE_HEADING_RE.fullmatch(raw_heading))
        if not is_boilerplate:
            semantic_owner = raw_heading
        semantic_heading = semantic_owner
        heading_kind = (
            "boilerplate" if is_boilerplate else "semantic_container" if heading_only else "semantic"
        )

        if len(section_text) <= max_chars:
            fragments = [section_text]
        else:
            fragments: list[str] = []
            current = ""
            for paragraph in re.split(r"\n\s*\n", section_text):
                paragraph = paragraph.strip()
                if not paragraph:
                    continue
                candidate = f"{current}\n\n{paragraph}" if current else paragraph
                if current and len(candidate) > max_chars:
                    fragments.append(current)
                    current = paragraph
                elif len(paragraph) > max_chars:
                    if current:
                        fragments.append(current)
                        current = ""
                    fragments.extend(
                        paragraph[offset:offset + max_chars]
                        for offset in range(0, len(paragraph), max_chars)
                    )
                else:
                    current = candidate
            if current:
                fragments.append(current)

        search_from = start
        for part, fragment in enumerate(fragments, start=1):
            position = text.find(fragment, search_from, end)
            if position < 0:
                position = search_from
            position_end = position + len(fragment)
            search_from = position_end
            chunk_number += 1
            chunks.append({
                "chunk_id": f"E{chunk_number:03d}",
                "heading": raw_heading,
                "raw_heading": raw_heading,
                "semantic_heading": semantic_heading,
                "heading_kind": heading_kind,
                "empty_node": heading_only,
                "level": level,
                "part": part,
                "text": fragment,
                "char_start": position,
                "char_end": position_end,
                "line_start": _line_number(text, position),
                "line_end": _line_number(text, max(position, position_end - 1)),
            })
    return chunks


def _trimmed_region(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _modality_for_text(text: str, chunk: dict[str, Any], parent_figure: str | None) -> str:
    if parent_figure or FIGURE_RE.search(text):
        return "figure_caption"
    if DEPRIORITIZED_HEADING_RE.search(chunk["semantic_heading"]):
        return "boilerplate"
    if re.search(r"references?|bibliography", chunk["semantic_heading"], re.I) or REFERENCE_ENTRY_RE.match(text):
        return "bibliography"
    return "body_text"


def build_spans(markdown: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create sentence/block-sized spans with exact source offsets and modality."""

    spans: list[dict[str, Any]] = []
    for chunk in chunks:
        fragment = markdown[chunk["char_start"]:chunk["char_end"]]
        base = chunk["char_start"]
        cursor = 0
        parent_figure: str | None = None

        def add_span(local_start: int, local_end: int, modality: str, figure: str | None = None) -> None:
            absolute_start, absolute_end = _trimmed_region(markdown, base + local_start, base + local_end)
            if absolute_start >= absolute_end:
                return
            value = markdown[absolute_start:absolute_end]
            spans.append({
                "span_id": "",
                "chunk_id": chunk["chunk_id"],
                "heading": chunk["heading"],
                "semantic_heading": chunk["semantic_heading"],
                "modality": modality,
                "parent_figure": figure,
                "text": value,
                "char_start": absolute_start,
                "char_end": absolute_end,
                "line_start": _line_number(markdown, absolute_start),
                "line_end": _line_number(markdown, max(absolute_start, absolute_end - 1)),
            })

        def add_text_region(local_start: int, local_end: int) -> None:
            nonlocal parent_figure
            region = fragment[local_start:local_end]
            for paragraph_match in re.finditer(r"\S(?:.|\n)*?(?=\n\s*\n|\Z)", region):
                paragraph_start = local_start + paragraph_match.start()
                paragraph_end = local_start + paragraph_match.end()
                paragraph = fragment[paragraph_start:paragraph_end]
                figure_match = FIGURE_RE.search(paragraph)
                if figure_match:
                    parent_figure = re.sub(r"\s+", " ", figure_match.group("label")).strip()
                elif not re.match(r"^\s*(?:[a-z](?:[–-][a-z])?[,;]?\s*)", paragraph):
                    parent_figure = None

                sentence_cursor = 0
                boundaries = list(SENTENCE_BOUNDARY_RE.finditer(paragraph))
                for boundary in boundaries:
                    sentence_end = boundary.start()
                    sentence = paragraph[sentence_cursor:sentence_end]
                    figure_in_sentence = FIGURE_RE.search(sentence)
                    figure = (
                        re.sub(r"\s+", " ", figure_in_sentence.group("label")).strip()
                        if figure_in_sentence else parent_figure
                    )
                    modality = _modality_for_text(sentence, chunk, figure)
                    add_span(paragraph_start + sentence_cursor, paragraph_start + sentence_end, modality, figure)
                    sentence_cursor = boundary.end()
                sentence = paragraph[sentence_cursor:]
                figure_in_sentence = FIGURE_RE.search(sentence)
                figure = (
                    re.sub(r"\s+", " ", figure_in_sentence.group("label")).strip()
                    if figure_in_sentence else parent_figure
                )
                modality = _modality_for_text(sentence, chunk, figure)
                add_span(paragraph_start + sentence_cursor, paragraph_end, modality, figure)

        for marker in MARKER_RE.finditer(fragment):
            if marker.start() > cursor:
                add_text_region(cursor, marker.start())
            value = marker.group(0)
            if HEADING_RE.fullmatch(value):
                add_span(marker.start(), marker.end(), "heading")
            elif IMAGE_RE.fullmatch(value):
                add_span(marker.start(), marker.end(), "image_ref", parent_figure)
            elif FORMULA_RE.fullmatch(value):
                add_span(marker.start(), marker.end(), "formula", parent_figure)
            cursor = marker.end()
        if cursor < len(fragment):
            add_text_region(cursor, len(fragment))

    for index, span in enumerate(spans, start=1):
        span["span_id"] = f"S{index:04d}"

    by_chunk: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        by_chunk.setdefault(span["chunk_id"], []).append(span)
    for chunk in chunks:
        owned = by_chunk.get(chunk["chunk_id"], [])
        chunk["span_ids"] = [span["span_id"] for span in owned]
        chunk["modalities"] = sorted({span["modality"] for span in owned})
        chunk["figure_parents"] = sorted({span["parent_figure"] for span in owned if span["parent_figure"]})
        chunk["semantic_owner_type"] = "section"
        content_modalities = set(chunk["modalities"]) - {"heading", "image_ref", "formula"}
        if (
            chunk.get("heading_kind") == "boilerplate"
            and content_modalities == {"figure_caption"}
            and chunk["figure_parents"]
        ):
            chunk["semantic_heading"] = chunk["figure_parents"][-1]
            chunk["semantic_owner_type"] = "figure_caption"
            for span in owned:
                span["semantic_heading"] = chunk["semantic_heading"]
    return spans


def build_document_graph(markdown: str, max_chars: int = 6000) -> dict[str, Any]:
    chunks = split_chunks(markdown, max_chars=max_chars)
    spans = build_spans(markdown, chunks)
    return {
        "schema_version": 2,
        "char_count": len(markdown),
        "chunk_count": len(chunks),
        "span_count": len(spans),
        "chunks": chunks,
        "spans": spans,
    }


def _load_markdown(value: str | Path) -> str:
    if isinstance(value, Path):
        return value.read_text(encoding="utf-8")
    if "\n" not in value and len(value) < 4096:
        path = Path(value)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return str(value)


def _support_type(text: str, heading: str, modality: str) -> str:
    combined = f"{heading} {text}"
    if modality == "figure_caption":
        return "figure_caption"
    if re.search(r"simulat|calculated|numerical|FDTD|finite-difference", combined, re.I):
        return "simulation"
    if re.search(r"measur|spectr|test|quantif|recorded|intensity", combined, re.I):
        return "measurement"
    if re.search(r"prepar|fabricat|synthesi|printing|coating|curing|peeling|materials", combined, re.I):
        return "method_protocol"
    if re.search(r"suggest|indicat|owing to|thereby|thus|as a result", text, re.I):
        return "author_inference"
    return "direct_observation"


def search_graph(
    graph: dict[str, Any],
    query: str,
    top_k: int = 5,
    *,
    intent: str | None = None,
    modality: str | None = None,
    section: str | None = None,
    include_formulas: bool = False,
) -> list[dict[str, Any]]:
    """Rank atomic spans from an already-built document graph.

    This is the reusable core of ``search_spans``; callers that already hold a
    graph (for example a workflow that builds it once) can avoid re-parsing the
    Markdown for every query.
    """

    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    raw_query_terms = terms(query)
    if not raw_query_terms:
        raise ValueError("query must contain at least one searchable term")
    query_terms = expand_query_terms(query)
    raw_term_set = set(raw_query_terms)
    want_formula = include_formulas or modality == "formula" or bool(_FORMULA_QUERY_RE.search(query))
    excluded = {"heading", "image_ref", "bibliography", "boilerplate"}
    if not want_formula:
        excluded.add("formula")
    section_needle = (section or "").strip().casefold()
    candidates = []
    for span in graph["spans"]:
        span_mod = span["modality"]
        if span_mod in excluded:
            continue
        if modality:
            if modality == "figure" and span_mod not in {"figure_caption", "figure"}:
                continue
            elif modality != "figure" and span_mod != modality:
                continue
        if section_needle:
            h_text = f"{span.get('semantic_heading', '')} {span.get('heading', '')}".casefold()
            if section_needle not in h_text:
                continue
        min_terms = 1 if span_mod == "formula" else 2
        if len(terms(span["text"])) >= min_terms:
            candidates.append(span)
    if not candidates:
        return []
    token_counts = [Counter(terms(span["text"])) for span in candidates]
    frequency = Counter(token for counts in token_counts for token in counts)
    average_length = sum(sum(counts.values()) for counts in token_counts) / max(1, len(candidates))
    preferred_heading = INTENT_HEADING_PATTERNS.get(intent or "")
    ranked: list[tuple[float, dict[str, Any]]] = []

    all_spans = graph.get("spans", [])
    span_pos = {s["span_id"]: idx for idx, s in enumerate(all_spans)}

    def _formula_context_terms(span: dict[str, Any]) -> set[str]:
        idx = span_pos.get(span["span_id"])
        if idx is None:
            return set()
        ctx: set[str] = set()
        for neighbor_idx in (idx - 1, idx + 1):
            if 0 <= neighbor_idx < len(all_spans):
                nb = all_spans[neighbor_idx]
                if nb.get("chunk_id") == span.get("chunk_id"):
                    ctx.update(terms(nb.get("text", "")))
        return ctx

    for span, counts in zip(candidates, token_counts):
        heading = span["semantic_heading"]
        heading_terms = set(terms(heading))
        matched = sorted({term for term in query_terms if counts.get(term, 0)})
        heading_matched = sorted(heading_terms.intersection(query_terms))
        context_matched: list[str] = []
        if span["modality"] == "formula":
            context_matched = sorted(_formula_context_terms(span).intersection(query_terms))
        formula_modality_hit = bool(
            span["modality"] == "formula" and (modality == "formula" or want_formula)
        )
        if not matched and not heading_matched and not context_matched and not formula_modality_hit:
            continue
        document_length = max(1, sum(counts.values()))
        score = 0.0
        for term in set(query_terms):
            count = counts.get(term, 0)
            if not count:
                continue
            weight = 1.0 if term in raw_term_set else 0.55
            inverse = math.log(1.0 + (len(candidates) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            denominator = count + 1.5 * (0.25 + 0.75 * document_length / max(1.0, average_length))
            score += weight * inverse * (count * 2.5) / denominator
        if context_matched:
            score += 0.9 * len(context_matched)
        if formula_modality_hit:
            score += 1.5
            if not matched:
                matched = sorted(set(context_matched + heading_matched + ["formula"]))
        elif not matched:
            matched = sorted(set(heading_matched))

        if intent == "sample_preparation" and not re.search(
            r"prepar|fabricat|synthesi|polymer|material|reagent|ink|formamide|substrate|"
            r"plasma|hydrophobic|print|nozzle|droplet|coat|blade|embed|cur|peel|transfer|"
            r"rolling|winding|R2R|PDMS",
            f"{heading} {span['text']}",
            re.I,
        ):
            continue
        if intent == "sample_preparation" and re.search(r"simulation", heading, re.I):
            continue
        score += 1.25 * len(set(terms(heading)).intersection(query_terms))
        section_fit = "neutral"
        if DEPRIORITIZED_HEADING_RE.search(heading):
            score *= 0.05
            section_fit = "deprioritized"
        elif intent == "key_results" and METHOD_ONLY_HEADING_RE.search(heading):
            score *= 0.55
            section_fit = "method_context"
        elif preferred_heading and preferred_heading.search(heading):
            score = score * 1.35 + 0.75
            section_fit = "preferred"
        if intent == "sample_preparation" and re.search(r"prepar|synthesi|printing|coating|curing|peeling", heading, re.I):
            score += 3.0

        relevance = "high" if len(matched) >= 2 and section_fit != "deprioritized" else "medium"
        result = {
            "chunk_id": span["chunk_id"],
            "span_id": span["span_id"],
            "heading": heading,
            "raw_heading": span["heading"],
            "line_start": span["line_start"],
            "line_end": span["line_end"],
            "char_start": span["char_start"],
            "char_end": span["char_end"],
            "score": round(score, 3),
            "relevance": relevance,
            "section_fit": section_fit,
            "matched_terms": matched[:16],
            "snippet": span["text"],
            "supporting_spans": [{
                "span_id": span["span_id"],
                "chunk_id": span["chunk_id"],
                "source_lines": {"start": span["line_start"], "end": span["line_end"]},
                "source_chars": {"start": span["char_start"], "end": span["char_end"]},
                "modality": span["modality"],
                "support_type": _support_type(span["text"], heading, span["modality"]),
                "text": span["text"],
            }],
        }
        ranked.append((score, result))

    ranked.sort(key=lambda item: (-item[0], item[1]["char_start"]))
    if not ranked:
        return []
    top_score = ranked[0][0]
    diversity_patterns = INTENT_DIVERSITY_PATTERNS.get(intent or "", ())
    cutoff = max(0.05, top_score * (0.02 if diversity_patterns else 0.16))
    filtered = [
        result for score, result in ranked
        if score >= cutoff and result["section_fit"] != "deprioritized"
    ]
    if not diversity_patterns:
        return filtered[:top_k]
    diversity_pool = filtered
    if intent == "sample_preparation":
        diversity_pool = sorted(
            filtered,
            key=lambda item: (
                item["supporting_spans"][0]["support_type"] != "method_protocol",
                -item["score"],
            ),
        )
    selected: list[dict[str, Any]] = []
    selected_spans: set[str] = set()
    for pattern in diversity_patterns:
        match = next(
            (item for item in diversity_pool if item["span_id"] not in selected_spans and pattern.search(item["snippet"])),
            None,
        )
        if match is not None:
            selected.append(match)
            selected_spans.add(match["span_id"])
    for item in filtered:
        if len(selected) >= top_k:
            break
        if item["span_id"] not in selected_spans:
            selected.append(item)
            selected_spans.add(item["span_id"])
    return selected[:top_k]


def search_spans(
    markdown_or_path: str | Path,
    query: str,
    top_k: int = 5,
    *,
    intent: str | None = None,
    modality: str | None = None,
    section: str | None = None,
    include_formulas: bool = False,
    max_chars: int = 6000,
) -> list[dict[str, Any]]:
    """Rank atomic text spans and return the matching passage, never a chunk prefix."""
    markdown = _load_markdown(markdown_or_path)
    graph = build_document_graph(markdown, max_chars=max_chars)
    return search_graph(
        graph,
        query,
        top_k=top_k,
        intent=intent,
        modality=modality,
        section=section,
        include_formulas=include_formulas,
    )
