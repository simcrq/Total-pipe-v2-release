"""Higher-level evidence, dependency and synthesis-readiness audits."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Iterable


NUMBERED_REFERENCE_RE = re.compile(r"(?m)^\s*\d{1,3}\.\s+\S")
TEMPERATURE_RANGE_RE = re.compile(
    r"(?P<low>-?\d+(?:\.\d+)?)\s*(?:to|–|—|-)\s*(?P<high>-?\d+(?:\.\d+)?)\s*°\s*C",
    re.IGNORECASE,
)
TEMPERATURE_RE = re.compile(r"(?<![\d.])(?P<value>-?\d+(?:\.\d+)?)\s*°\s*C", re.I)

COVERAGE_FACETS: dict[str, dict[str, re.Pattern[str]]] = {
    "sample_preparation": {
        "materials": re.compile(r"\bmaterials?\b|styrene|PDMS|polystyrene|reagent", re.I),
        "particle_synthesis": re.compile(r"synthesi|emulsion polymerization|nanospheres?|core.shell|nanoparticles? were", re.I),
        "ink_formulation": re.compile(r"formamide|viscosity|surface tension|ultrason|colloidal nanoparticle ink", re.I),
        "substrate_preparation": re.compile(r"substrate|plasma|hydrophobic|contact angle|silane", re.I),
        "printing": re.compile(r"inkjet|print(?:ed|ing)|nozzle|droplet", re.I),
        "embedding_or_coating": re.compile(r"coat|blade|embed|penetrate|prepolymer", re.I),
        "curing": re.compile(r"cur(?:e|ed|ing)|polymerization of PDMS|irradiated", re.I),
        "peeling_or_transfer": re.compile(r"peel|transfer|flipped|rolled up", re.I),
        "roll_to_roll": re.compile(r"roll-to-roll|R2R|winding|rolling|continuous", re.I),
    },
    "physical_mechanism": {
        "multiscale_structure": re.compile(r"nanoscale|microscale|n lattice|nanolattice|concave|hemispher", re.I),
        "photonic_bandgap": re.compile(r"photonic bandgap|\bPBG\b|Bragg|wavelength-selective", re.I),
        "total_internal_reflection": re.compile(r"total internal reflection|\bTIRs?\b|guided-wave", re.I),
        "interference_or_dispersion": re.compile(r"interference|dispersion|optical path|phase", re.I),
        "field_or_simulation": re.compile(r"field distribution|field enhancement|simulat|FDTD|calculated", re.I),
        "observable_mapping": re.compile(r"rim|centre|central colour|reflectance|angle-dependent|colour", re.I),
    },
    "key_results": {
        "scale_or_throughput": re.compile(r"metre-scale|million|orders of magnitude|roll-to-roll|scalab", re.I),
        "yield_or_resolution": re.compile(r"yield|dots per inch|dpi|single-pixel|uniformity", re.I),
        "optical_tunability": re.compile(r"tunable|tunability|redshift|colour mixing|separation|integration", re.I),
        "stability": re.compile(r"stability|resistance|ultraviolet|temperature|solvent|washing", re.I),
        "mechanical_robustness": re.compile(r"cycle|stretch|bend|twist|mechanical|elongation", re.I),
    },
    "limitations": {
        "illumination_geometry": re.compile(r"collimated|incident light|illumination|viewing conditions", re.I),
        "observation_geometry": re.compile(r"observation point|observer|distance|angle-dependent|receiving angle", re.I),
        "background_or_substrate": re.compile(r"black (?:background|substrate)|background reflection", re.I),
        "evidence_dependency": re.compile(r"Supplementary|more .*details|online version", re.I),
    },
}

DEPENDENCY_PATTERNS: dict[str, re.Pattern[str]] = {
    "supplementary_information": re.compile(r"Supplementary Information", re.I),
    "supplementary_discussions": re.compile(r"Supplementary Discussions?", re.I),
    "supplementary_figures": re.compile(r"Supplementary Figs?(?:ures?)?\.?\s*[\d–—, -]+", re.I),
    "supplementary_tables": re.compile(r"Supplementary Tables?\.?\s*\d+", re.I),
    "supplementary_materials": re.compile(r"Supplementary Materials?", re.I),
}


def _warning(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _status(score: int, ready_at: int = 85, blocked_below: int = 45) -> str:
    return "blocked" if score < blocked_below else "review" if score < ready_at else "ready"


def audit_structure_enhanced(
    markdown: str,
    extraction_audit: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Audit semantic ownership, reading order and cross-modality chunk mixing."""

    explicit = dict(extraction_audit["section_coverage"])
    inferred: dict[str, str] = {}
    numbered_references = len(NUMBERED_REFERENCE_RE.findall(markdown))
    figure_captions = extraction_audit["content_inventory"]["figure_caption_count"]
    opening = markdown[:12000]
    if not explicit["abstract"] and re.search(r"\b10\.\d{4,9}/", opening) and len(opening) >= 1000:
        inferred["abstract"] = "unheaded opening summary"
    if not explicit["results"] and figure_captions >= 2 and explicit["conclusion"]:
        inferred["results"] = "article-style unheaded results body"
    if not explicit["references"] and numbered_references >= 5:
        inferred["references"] = "numbered bibliography without a References heading"
    effective = dict(explicit)
    for section in inferred:
        effective[section] = True
    missing_core = [
        name for name in ("abstract", "methods", "results", "conclusion")
        if not effective[name]
    ]

    chunks = manifest["chunks"]
    fake_headings = [chunk for chunk in chunks if chunk.get("heading_kind") == "boilerplate"]
    empty_nodes = [chunk for chunk in chunks if chunk.get("empty_node")]
    semantic_score = max(25, 100 - 5 * len(fake_headings) - 6 * len(empty_nodes) - 15 * len(missing_core))
    semantic_warnings: list[dict[str, str]] = []
    if fake_headings:
        semantic_warnings.append(_warning(
            "layout_headings_not_semantic",
            "medium",
            f"{len(fake_headings)} layout/boilerplate headings were detached from semantic ownership.",
        ))
    if empty_nodes:
        semantic_warnings.append(_warning(
            "empty_heading_nodes",
            "medium",
            "Heading-only nodes were retained as containers, not scientific evidence: "
            + ", ".join(item["chunk_id"] for item in empty_nodes) + ".",
        ))

    lines = markdown.splitlines()
    heading_interruptions: list[dict[str, Any]] = []
    media_interruptions: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if re.fullmatch(r"#{1,6}\s+Article\s*", line, re.I):
            previous = next((lines[pos].strip() for pos in range(index - 1, -1, -1) if lines[pos].strip()), "")
            following = next((lines[pos].strip() for pos in range(index + 1, len(lines)) if lines[pos].strip()), "")
            if previous and following and not re.search(r"[.!?。！？:;]$", previous) and re.match(r"[a-z]", following):
                heading_interruptions.append({
                    "heading_line": index + 1,
                    "before": previous[-180:],
                    "after": following[:180],
                })
        if line.rstrip().endswith((",", "–", "-")):
            seen_media = False
            for later in range(index + 1, min(len(lines), index + 45)):
                candidate = lines[later].strip()
                if IMAGE_TOKEN(candidate):
                    seen_media = True
                if seen_media and re.match(
                    r"(?:whereas|however|therefore|consequently|together|owing|because|thus|notably)\b",
                    candidate,
                    re.I,
                ):
                    media_interruptions.append({
                        "before_line": index + 1,
                        "resume_line": later + 1,
                        "before": line.strip()[-180:],
                        "after": candidate[:180],
                    })
                    break

    interruption_count = len(heading_interruptions) + len(media_interruptions)
    reading_score = max(20, 100 - 28 * len(heading_interruptions) - 18 * len(media_interruptions))
    reading_warnings: list[dict[str, str]] = []
    if heading_interruptions:
        reading_warnings.append(_warning(
            "sentence_interrupted_by_layout_heading",
            "high",
            f"Detected {len(heading_interruptions)} sentence continuation(s) split by a layout heading.",
        ))
    if media_interruptions:
        reading_warnings.append(_warning(
            "body_text_interrupted_by_media_stream",
            "high",
            f"Detected {len(media_interruptions)} likely body continuation(s) displaced by images/captions.",
        ))

    mixed_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        modalities = set(chunk.get("modalities", [])) - {"heading", "formula"}
        textual_streams = modalities.intersection({"body_text", "boilerplate", "bibliography"})
        if textual_streams and modalities.intersection({"figure_caption", "image_ref"}):
            mixed_chunks.append({
                "chunk_id": chunk["chunk_id"],
                "heading": chunk["heading"],
                "semantic_heading": chunk["semantic_heading"],
                "modalities": sorted(modalities),
                "figure_parents": chunk.get("figure_parents", []),
            })
    coherence_score = max(30, 100 - 9 * len(mixed_chunks))
    coherence_warnings = []
    if mixed_chunks:
        coherence_warnings.append(_warning(
            "mixed_scientific_streams_in_chunks",
            "medium",
            "Chunks combine body, figure-caption and/or image streams: "
            + ", ".join(item["chunk_id"] for item in mixed_chunks) + ".",
        ))

    score = round(0.4 * semantic_score + 0.4 * reading_score + 0.2 * coherence_score)
    warnings = semantic_warnings + reading_warnings + coherence_warnings
    return {
        "scope": "Semantic structure, reading order and chunk-coherence audit.",
        "score": score,
        "readiness": "review" if interruption_count or score < 85 else "ready",
        "explicit_section_coverage": explicit,
        "effective_section_coverage": effective,
        "inference_reasons": inferred,
        "numbered_reference_entry_count": numbered_references,
        "text_capture_fidelity": {
            "score": extraction_audit["score"],
            "readiness": extraction_audit["readiness"],
        },
        "reading_order_integrity": {
            "score": reading_score,
            "readiness": _status(reading_score),
            "heading_interruptions": heading_interruptions,
            "media_interruptions": media_interruptions,
            "warnings": reading_warnings,
        },
        "semantic_structure_integrity": {
            "score": semantic_score,
            "readiness": _status(semantic_score),
            "fake_heading_count": len(fake_headings),
            "fake_heading_chunks": [item["chunk_id"] for item in fake_headings],
            "empty_node_count": len(empty_nodes),
            "empty_node_chunks": [item["chunk_id"] for item in empty_nodes],
            "warnings": semantic_warnings,
        },
        "chunk_coherence": {
            "score": coherence_score,
            "readiness": _status(coherence_score),
            "mixed_chunk_count": len(mixed_chunks),
            "mixed_chunks": mixed_chunks,
            "warnings": coherence_warnings,
        },
        "warnings": warnings,
    }


def IMAGE_TOKEN(line: str) -> bool:
    return bool(re.search(r"!\[[^\]]*\]\([^)]+\)", line))


def _temperature_role(context: str) -> str:
    if re.search(r"curing|cured|thermal polymerization", context, re.I):
        return "curing"
    if re.search(r"drying|dried|evaporation|substrate temperature", context, re.I):
        return "drying_or_substrate"
    if re.search(r"stability|resistance|hotplate|freezer|test", context, re.I):
        return "stability_test"
    if re.search(r"reaction|polymerization|APS|synthesi", context, re.I):
        return "particle_synthesis"
    return "unspecified"


def audit_quantities_enhanced(markdown: str) -> dict[str, Any]:
    """Audit ranges, operating regimes, linked speeds and symbol definitions."""

    temperature_ranges: list[dict[str, Any]] = []
    temperatures: list[dict[str, Any]] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        context = re.sub(r"\s+", " ", line.strip())[:520]
        for match in TEMPERATURE_RANGE_RE.finditer(line):
            temperature_ranges.append({
                "low": float(match.group("low")),
                "high": float(match.group("high")),
                "unit": "°C",
                "line": line_number,
                "role": _temperature_role(context),
                "context": context,
            })
        for match in TEMPERATURE_RE.finditer(line):
            temperatures.append({
                "value": float(match.group("value")),
                "unit": "°C",
                "line": line_number,
                "role": _temperature_role(context),
                "context": context,
            })

    warnings: list[dict[str, str]] = []
    unique_ranges = {(item["low"], item["high"]) for item in temperature_ranges}
    if len(unique_ranges) > 1:
        warnings.append(_warning(
            "multiple_temperature_ranges",
            "medium",
            "Multiple temperature ranges occur in different contexts; preserve each source location.",
        ))
    operating_roles: dict[str, set[float]] = defaultdict(set)
    for item in temperatures:
        operating_roles[item["role"]].add(item["value"])
    process_values = set().union(*(
        values for role, values in operating_roles.items()
        if role in {"curing", "drying_or_substrate", "particle_synthesis"}
    )) if operating_roles else set()
    if len(process_values) >= 3:
        warnings.append(_warning(
            "multiple_operating_temperature_regimes",
            "medium",
            "Laboratory drying, synthesis and R2R curing temperatures form distinct operating regimes; do not merge them.",
        ))

    speed_relations: list[dict[str, Any]] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        printing = re.search(r"printing speed\s*\(\s*(\d+(?:\.\d+)?)\s*mm", line, re.I)
        winding = re.search(r"winding speed.{0,180}?(\d+(?:\.\d+)?)\s*mm", line, re.I)
        if printing and winding and re.search(r"synchronized", line, re.I):
            first = float(printing.group(1))
            second = float(winding.group(1))
            item = {
                "relation": "winding speed synchronized with printing speed",
                "printing_speed": first,
                "winding_speed": second,
                "unit": "mm/s",
                "line": line_number,
                "status": "review" if first != second else "consistent",
                "context": re.sub(r"\s+", " ", line.strip())[:600],
            }
            speed_relations.append(item)
            if first != second:
                warnings.append(_warning(
                    "potential_relational_inconsistency",
                    "high",
                    f"Printing speed ({first:g} mm/s) and synchronized winding speed ({second:g} mm/s) differ at line {line_number}; verify the intended relationship.",
                ))

    symbol_definitions: list[dict[str, Any]] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        if not re.search(r"D\s*_?\s*\{?\s*(?:\\mathrm\{)?n", line):
            continue
        kinds: list[str] = []
        if re.search(r"D[^.]{0,80}(?:photonic )?lattice constant|lattice constant[^.]{0,80}D", line, re.I):
            kinds.append("photonic_lattice_constant")
        if re.search(r"nanoparticle size\s*\([^)]*D|D[^.]{0,120}nanoparticles? with .*sizes", line, re.I):
            kinds.append("nanoparticle_size")
        for kind in kinds:
            symbol_definitions.append({
                "symbol": "D_n",
                "definition": kind,
                "line": line_number,
                "context": re.sub(r"\s+", " ", line.strip())[:520],
            })
    definitions = {item["definition"] for item in symbol_definitions}
    if len(definitions) > 1:
        warnings.append(_warning(
            "symbol_definition_drift",
            "high",
            "D_n is associated with both photonic lattice constant and nanoparticle size; downstream claims must preserve the source wording.",
        ))

    score = max(35, 100 - sum(20 if item["severity"] == "high" else 10 for item in warnings))
    return {
        "scope": "Quantity and symbol guardrail; warnings request verification, not automatic correction.",
        "score": score,
        "readiness": "review" if warnings else "ready",
        "temperature_ranges": temperature_ranges,
        "temperature_occurrences": temperatures,
        "operating_temperature_regimes": {key: sorted(value) for key, value in operating_roles.items()},
        "speed_relations": speed_relations,
        "symbol_definitions": symbol_definitions,
        "warnings": warnings,
    }


def audit_source_dependencies(
    markdown: str,
    related_documents: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Detect referenced supplementary sources even when files are unavailable."""

    local_supplements = [item for item in related_documents if item.get("role") == "supplementary_candidate"]
    dependencies: list[dict[str, Any]] = []
    for dependency_type, pattern in DEPENDENCY_PATTERNS.items():
        matches = [re.sub(r"\s+", " ", match.group(0)).strip() for match in pattern.finditer(markdown)]
        if not matches:
            continue
        dependencies.append({
            "dependency_type": dependency_type,
            "required_for_full_evidence": True,
            "reference_count": len(matches),
            "reference_examples": list(dict.fromkeys(matches))[:12],
            "availability": "available" if local_supplements else "unavailable",
            "local_paths": [item["path"] for item in local_supplements],
        })
    missing = [item for item in dependencies if item["availability"] == "unavailable"]
    warnings = []
    if missing:
        warnings.append(_warning(
            "required_supplementary_sources_unavailable",
            "high",
            "The paper relies on supplementary evidence that is referenced but not present locally: "
            + ", ".join(item["dependency_type"] for item in missing) + ".",
        ))
    score = max(35, 100 - 12 * len(missing))
    return {
        "scope": "Availability of sources referenced by the paper; DOI links do not count as local evidence.",
        "score": score,
        "readiness": "review" if missing else "ready",
        "dependencies": dependencies,
        "missing_required_count": len(missing),
        "warnings": warnings,
    }


def coverage_for_intent(intent: str, texts: Iterable[str]) -> dict[str, Any]:
    facets = COVERAGE_FACETS.get(intent, {})
    joined = "\n".join(texts)
    hits = {name: bool(pattern.search(joined)) for name, pattern in facets.items()}
    covered = [name for name, found in hits.items() if found]
    missing = [name for name, found in hits.items() if not found]
    ratio = len(covered) / len(facets) if facets else 1.0
    return {
        "facet_count": len(facets),
        "covered_facets": covered,
        "missing_facets": missing,
        "coverage_ratio": round(ratio, 3),
    }


def build_evidence_registry(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate exact supporting spans and make queries reference EV identifiers."""

    registry: list[dict[str, Any]] = []
    by_location: dict[tuple[int, int, str], dict[str, Any]] = {}
    for group in evidence:
        group_ids: list[str] = []
        clean_results: list[dict[str, Any]] = []
        seen_in_group: set[str] = set()
        for result in group.get("results", []):
            result_ids: list[str] = []
            for span in result.get("supporting_spans", []):
                chars = span["source_chars"]
                key = (chars["start"], chars["end"], span["modality"])
                entry = by_location.get(key)
                if entry is None:
                    entry = {
                        "evidence_id": f"EV{len(registry) + 1:04d}",
                        "span_id": span["span_id"],
                        "chunk_id": span["chunk_id"],
                        "source_lines": span["source_lines"],
                        "source_chars": span["source_chars"],
                        "modality": span["modality"],
                        "support_type": span["support_type"],
                        "text": span["text"],
                        "query_ids": [],
                        "queries": [],
                    }
                    by_location[key] = entry
                    registry.append(entry)
                if group["query_id"] not in entry["query_ids"]:
                    entry["query_ids"].append(group["query_id"])
                result_ids.append(entry["evidence_id"])
                query_text = group.get("query")
                if query_text and query_text not in entry["queries"]:
                    entry["queries"].append(query_text)
                if entry["evidence_id"] not in group_ids:
                    group_ids.append(entry["evidence_id"])
            result_ids = list(dict.fromkeys(result_ids))
            if not result_ids or result_ids[0] in seen_in_group:
                continue
            seen_in_group.add(result_ids[0])
            clean = {key: value for key, value in result.items() if key not in {"snippet", "supporting_spans"}}
            clean["evidence_ids"] = result_ids
            clean_results.append(clean)
        group["results"] = clean_results
        group["evidence_ids"] = group_ids
    return registry


def audit_retrieval_enhanced(
    evidence: list[dict[str, Any]],
    registry: list[dict[str, Any]],
) -> dict[str, Any]:
    """Report retrieval precision, facet coverage and supporting-span exposure separately."""

    registry_by_id = {item["evidence_id"]: item for item in registry}
    diagnostics: list[dict[str, Any]] = []
    acceptable = 0
    total_results = 0
    exposed_results = 0
    coverage_values: list[float] = []
    for group in evidence:
        results = group.get("results", [])
        total_results += len(results)
        exposed_results += sum(bool(item.get("evidence_ids")) for item in results)
        texts = [registry_by_id[item]["text"] for item in group.get("evidence_ids", []) if item in registry_by_id]
        coverage = coverage_for_intent(group.get("intent", "general"), texts)
        group["coverage"] = coverage
        if coverage["facet_count"]:
            coverage_values.append(coverage["coverage_ratio"])
        intent_facets = COVERAGE_FACETS.get(group.get("intent", "general"), {})
        precision_hits = 0
        for item in results:
            result_text = "\n".join(
                registry_by_id[evidence_id]["text"]
                for evidence_id in item.get("evidence_ids", [])
                if evidence_id in registry_by_id
            )
            facet_fit = not intent_facets or any(
                pattern.search(result_text) for pattern in intent_facets.values()
            )
            if item.get("section_fit") != "deprioritized" and item.get("relevance") in {"high", "medium"} and facet_fit:
                precision_hits += 1
        precision = precision_hits / len(results) if results else 0.0
        if not results:
            status = "no_match"
        elif precision < 0.7:
            status = "weak"
        elif coverage["facet_count"] and coverage["coverage_ratio"] < 0.6:
            status = "partial"
        else:
            status = "acceptable"
            acceptable += 1
        group["retrieval_status"] = status
        diagnostics.append({
            "query_id": group["query_id"],
            "canonical_query_id": group.get("canonical_query_id", group["query_id"]),
            "intent": group.get("intent", "general"),
            "status": status,
            "result_count": len(results),
            "unique_evidence_count": len(group.get("evidence_ids", [])),
            "precision_ratio": round(precision, 3),
            "coverage": coverage,
        })
    exposure = exposed_results / total_results if total_results else 1.0
    mean_coverage = sum(coverage_values) / len(coverage_values) if coverage_values else 1.0
    query_success = acceptable / len(evidence) if evidence else 1.0
    mean_precision = sum(item["precision_ratio"] for item in diagnostics) / max(1, len(diagnostics))
    score = round(100 * (0.20 * query_success + 0.30 * mean_precision + 0.30 * mean_coverage + 0.20 * exposure))
    warnings: list[dict[str, str]] = []
    missing = [item["query_id"] for item in diagnostics if item["status"] == "no_match"]
    partial = [item["query_id"] for item in diagnostics if item["status"] in {"partial", "weak"}]
    if missing:
        warnings.append(_warning("evidence_queries_without_matches", "high", "No evidence match for: " + ", ".join(missing) + "."))
    if partial:
        warnings.append(_warning("evidence_coverage_incomplete", "medium", "Precision or facet coverage is incomplete for: " + ", ".join(partial) + "."))
    if exposure < 1.0:
        warnings.append(_warning("support_span_exposure_incomplete", "high", "Some retrieval results do not expose an exact supporting span."))
    return {
        "scope": "Span-level evidence retrieval precision and workflow-facet coverage; not claim correctness.",
        "score": score,
        "readiness": "blocked" if exposure < 0.5 or missing else "review" if warnings or score < 85 else "ready",
        "query_count": len(evidence),
        "acceptable_count": acceptable,
        "precision_ratio": round(mean_precision, 3),
        "mean_coverage_ratio": round(mean_coverage, 3),
        "support_span_exposure_ratio": round(exposure, 3),
        "unique_evidence_count": len(registry),
        "diagnostics": diagnostics,
        "warnings": warnings,
    }


def synthesis_gate(
    extraction: dict[str, Any],
    structure: dict[str, Any],
    retrieval: dict[str, Any],
    quantities: dict[str, Any],
    dependencies: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate explicit gates; the display score never overrides a failed gate."""

    gates: list[dict[str, str]] = []
    def gate(name: str, status: str, message: str) -> None:
        gates.append({"gate": name, "status": status, "message": message})

    gate("text_capture_fidelity", "block" if extraction["readiness"] == "blocked" else "review" if extraction["readiness"] == "review" else "pass", "Raw OCR/Markdown text must be usable.")
    reading = structure["reading_order_integrity"]
    gate("reading_order_integrity", "review" if reading["score"] < 85 else "pass", "Scientific prose must not be silently reordered by layout streams.")
    exposure = retrieval["support_span_exposure_ratio"]
    gate("support_span_exposure", "block" if exposure < 0.5 else "review" if exposure < 0.95 else "pass", "Every retrieved item must expose an exact sentence/span and offsets.")
    gate("evidence_coverage", "review" if retrieval["mean_coverage_ratio"] < 0.7 or retrieval["readiness"] != "ready" else "pass", "Required workflow facets must be covered, not merely represented in top-k.")
    gate("supplementary_dependencies", "review" if dependencies["missing_required_count"] else "pass", "Required supplementary evidence must be locally available for a complete mechanism audit.")
    gate("quantity_and_symbol_consistency", "review" if quantities["readiness"] == "review" else "pass", "Linked quantities and symbol definitions require contextual consistency.")

    statuses = {item["status"] for item in gates}
    readiness = "blocked" if "block" in statuses else "review" if "review" in statuses else "ready"
    score = round(sum((extraction["score"], structure["score"], retrieval["score"], quantities["score"], dependencies["score"])) / 5)
    return {
        "scope": "Hard-gated scientific-synthesis hand-off; score is descriptive and cannot override a failed gate.",
        "score": score,
        "readiness": readiness,
        "mechanism_completeness": "partial" if dependencies["missing_required_count"] else "complete_with_available_sources",
        "gates": gates,
        "failed_gate_count": sum(item["status"] != "pass" for item in gates),
    }
