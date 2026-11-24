"""Unified evidence retrieval for Story Planner, scientific_review, and page_design.

Searches three grounded layers without fabricating EV IDs:
1. ``registry``: exact ``EVxxxx`` records already indexed in ``workflow.json``.
2. ``source``: full paper Markdown spans (via PaperWorkflow's semantic graph),
   mapping overlapping passages to existing ``EVxxxx`` IDs or flagging unindexed gaps.
3. ``supplementary``: paired supplementary Markdown files when available.

CLI usage (for independent subagents reading story_prompt.json):
  python -m agent.evidence_search --workflow <workflow.json> search "<query>" [--top-k 8] [--scope all|registry|source|supplementary] [--modality formula|figure|table|text] [--section "<heading>"]
  python -m agent.evidence_search --workflow <workflow.json> outline
  python -m agent.evidence_search --workflow <workflow.json> read-lines --start 120 --end 180
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from . import ROOT


def _ensure_paperworkflow() -> None:
    pwf_root = str(ROOT / 'PaperWorkflow')
    if pwf_root not in sys.path:
        sys.path.insert(0, pwf_root)


def _load_workflow(workflow_path: str | Path) -> tuple[dict[str, Any], Path]:
    path = Path(workflow_path).expanduser().resolve()
    return json.loads(path.read_text(encoding='utf-8')), path


def _resolve_markdown(workflow: dict[str, Any], workflow_path: Path) -> Path | None:
    source = workflow.get('source') or {}
    candidates = [
        source.get('markdown_path'),
        source.get('input_path') if str(source.get('input_path') or '').lower().endswith('.md') else None,
        (workflow.get('artifacts') or {}).get('markdown_path'),
    ]
    for raw in candidates:
        if not raw:
            continue
        p = Path(raw)
        if not p.is_absolute():
            p = (workflow_path.parent / p).resolve()
        if p.is_file():
            return p
    return None


def _supplementary_markdowns(workflow: dict[str, Any], workflow_path: Path, extra_paths: list[str] | None = None) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    candidates: list[str] = list(extra_paths or [])
    for item in workflow.get('related_documents') or []:
        if isinstance(item, dict):
            for key in ('markdown_path', 'path', 'file_path'):
                if item.get(key):
                    candidates.append(str(item[key]))
    for item in (workflow.get('source_dependencies') or {}).get('supplementary_paths') or []:
        if item:
            candidates.append(str(item))
    for raw in candidates:
        p = Path(raw)
        if not p.is_absolute():
            p = (workflow_path.parent / p).resolve()
        key = str(p)
        if key not in seen and p.is_file() and p.suffix.lower() in ('.md', '.txt'):
            seen.add(key)
            found.append(p)
    return found


def _registry_search(
    workflow: dict[str, Any],
    query: str,
    *,
    top_k: int = 8,
    modality: str | None = None,
    section: str | None = None,
) -> list[dict[str, Any]]:
    _ensure_paperworkflow()
    from utils.evidence_graph import expand_query_terms, terms

    raw_terms = set(terms(query))
    q_terms = expand_query_terms(query)
    if not q_terms:
        return []
    registry = workflow.get('evidence_registry') or []
    section_needle = (section or '').strip().casefold()
    candidates = []
    for entry in registry:
        if not isinstance(entry, dict) or not entry.get('evidence_id'):
            continue
        if modality:
            mod = str(entry.get('modality') or '').casefold()
            if modality == 'figure' and mod not in ('figure', 'figure_caption'):
                continue
            elif modality != 'figure' and mod != modality.casefold():
                continue
        if section_needle:
            heading = str(entry.get('heading') or entry.get('section') or '').casefold()
            if section_needle not in heading:
                continue
        candidates.append(entry)
    if not candidates:
        return []
    counts_list = [Counter(terms(f"{e.get('heading', '')} {e.get('text', '')}")) for e in candidates]
    df = Counter(tok for c in counts_list for tok in c)
    avg_len = sum(sum(c.values()) for c in counts_list) / max(1, len(candidates))
    ranked = []
    for entry, counts in zip(candidates, counts_list):
        matched = sorted({t for t in q_terms if counts.get(t, 0)})
        if not matched:
            continue
        doc_len = max(1, sum(counts.values()))
        score = 0.0
        for tok in set(q_terms):
            cnt = counts.get(tok, 0)
            if not cnt:
                continue
            w = 1.0 if tok in raw_terms else 0.55
            idf = math.log(1.0 + (len(candidates) - df[tok] + 0.5) / (df[tok] + 0.5))
            denom = cnt + 1.5 * (0.25 + 0.75 * doc_len / max(1.0, avg_len))
            score += w * idf * (cnt * 2.5) / denom
        ranked.append((score, {
            'evidence_id': entry['evidence_id'],
            'score': round(score, 3),
            'matched_terms': matched[:16],
            'modality': entry.get('modality'),
            'support_type': entry.get('support_type'),
            'heading': entry.get('heading') or entry.get('section'),
            'query_ids': list(entry.get('query_ids') or []),
            'text': entry.get('text', ''),
        }))
    ranked.sort(key=lambda item: (-item[0], item[1]['evidence_id']))
    return [item for _, item in ranked[:top_k]]


def _matching_registry_ids(snippet: str, workflow: dict[str, Any]) -> list[str]:
    norm = re.sub(r'\s+', ' ', (snippet or '').strip())
    if len(norm) < 16:
        return []
    probe = norm[:120]
    ids = []
    for entry in workflow.get('evidence_registry') or []:
        if not isinstance(entry, dict) or not entry.get('evidence_id'):
            continue
        ev_text = re.sub(r'\s+', ' ', str(entry.get('text') or '').strip())
        if not ev_text:
            continue
        if probe in ev_text or ev_text[:120] in norm:
            ids.append(entry['evidence_id'])
    return ids[:5]


def document_outline(workflow_path: str | Path) -> dict[str, Any]:
    """Return a compact outline of the source paper Markdown and registry counts."""
    workflow, wpath = _load_workflow(workflow_path)
    registry = workflow.get('evidence_registry') or []
    by_modality = Counter(str(e.get('modality') or 'text') for e in registry if isinstance(e, dict))
    by_support = Counter(str(e.get('support_type') or 'unknown') for e in registry if isinstance(e, dict))
    md = _resolve_markdown(workflow, wpath)
    sections: list[dict[str, Any]] = []
    if md is not None:
        _ensure_paperworkflow()
        from utils.paper_tools import section_index
        try:
            sections = [
                {
                    'heading': item.get('semantic_heading') or item.get('heading'),
                    'line_start': item.get('line_start'),
                    'line_end': item.get('line_end'),
                    'modalities': item.get('modalities') or [],
                }
                for item in section_index(md.read_text(encoding='utf-8', errors='replace'))
                if not item.get('empty_node')
            ]
        except Exception:
            sections = []
    return {
        'workflow': str(wpath),
        'source_markdown': str(md) if md else None,
        'registry_count': len(registry),
        'by_modality': dict(by_modality),
        'by_support_type': dict(by_support),
        'sections': sections[:60],
    }


def read_source_lines(workflow_path: str | Path, start: int, end: int, *, file_path: str | None = None) -> dict[str, Any]:
    """Read an exact line slice from the source paper or a supplementary Markdown file."""
    workflow, wpath = _load_workflow(workflow_path)
    if start < 1 or end < start or end - start > 250:
        raise ValueError('Read at most 250 lines with 1 <= start <= end.')
    if file_path:
        target = Path(file_path).expanduser().resolve()
        allowed = {p.resolve() for p in [_resolve_markdown(workflow, wpath), *_supplementary_markdowns(workflow, wpath)] if p}
        if target not in allowed:
            raise ValueError('Requested file is not a source or paired supplementary Markdown for this workflow.')
    else:
        target = _resolve_markdown(workflow, wpath)
    if target is None or not target.is_file():
        raise ValueError('Source Markdown is unavailable for this workflow.')
    lines = target.read_text(encoding='utf-8', errors='replace').splitlines()
    selected = lines[start - 1:min(len(lines), end)]
    return {
        'source': str(target),
        'start': start,
        'end': min(len(lines), end),
        'total_lines': len(lines),
        'text': '\n'.join(f'{start + i}: {line}' for i, line in enumerate(selected)),
    }


def search_evidence(
    workflow_path: str | Path,
    query: str,
    *,
    top_k: int = 8,
    scope: str = 'all',
    modality: str | None = None,
    section: str | None = None,
    extra_supplementary: list[str] | None = None,
) -> dict[str, Any]:
    """Search evidence_registry, full source Markdown, and paired supplementary files."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError('query must be a non-empty string.')
    if not 1 <= int(top_k) <= 25:
        raise ValueError('top_k must be between 1 and 25.')
    if scope not in ('all', 'registry', 'source', 'supplementary'):
        raise ValueError('scope must be all, registry, source, or supplementary.')
    workflow, wpath = _load_workflow(workflow_path)
    result: dict[str, Any] = {
        'query': query.strip(),
        'scope': scope,
        'modality': modality,
        'section': section,
        'workflow': str(wpath),
        'registry_hits': [],
        'source_hits': [],
        'supplementary_hits': [],
    }
    if scope in ('all', 'registry'):
        result['registry_hits'] = _registry_search(
            workflow, query, top_k=top_k, modality=modality, section=section
        )
    _ensure_paperworkflow()
    from utils.evidence_graph import search_spans
    if scope in ('all', 'source'):
        md = _resolve_markdown(workflow, wpath)
        if md is not None:
            try:
                hits = search_spans(
                    md, query, top_k=top_k, modality=modality, section=section,
                    include_formulas=(modality == 'formula' or scope == 'source' or True),
                )
            except ValueError:
                hits = []
            for hit in hits:
                ev_ids = _matching_registry_ids(hit.get('snippet', ''), workflow)
                result['source_hits'].append({
                    'heading': hit.get('heading'),
                    'line_start': hit.get('line_start'),
                    'line_end': hit.get('line_end'),
                    'score': hit.get('score'),
                    'modality': (hit.get('supporting_spans') or [{}])[0].get('modality'),
                    'support_type': (hit.get('supporting_spans') or [{}])[0].get('support_type'),
                    'matched_terms': hit.get('matched_terms') or [],
                    'nearest_ev_ids': ev_ids,
                    'not_in_registry': not bool(ev_ids),
                    'snippet': hit.get('snippet', ''),
                })
    if scope in ('all', 'supplementary'):
        for smd in _supplementary_markdowns(workflow, wpath, extra_supplementary):
            try:
                hits = search_spans(
                    smd, query, top_k=min(5, top_k), modality=modality, section=section,
                    include_formulas=True,
                )
            except ValueError:
                hits = []
            for hit in hits:
                result['supplementary_hits'].append({
                    'file': smd.name,
                    'path': str(smd),
                    'heading': hit.get('heading'),
                    'line_start': hit.get('line_start'),
                    'line_end': hit.get('line_end'),
                    'score': hit.get('score'),
                    'matched_terms': hit.get('matched_terms') or [],
                    'snippet': hit.get('snippet', ''),
                })
    result['note'] = (
        'Cite exact EVxxxx IDs from registry_hits / nearest_ev_ids in story_plan.json. '
        'If a critical fact appears only in source_hits with not_in_registry=true, either '
        'expand queries via replan_from=queries or report the retrieval gap explicitly; never invent EV IDs.'
    )
    return result


def lookup_descriptor(workflow_path: str | Path, job_id: str | None = None) -> dict[str, Any]:
    """Structured evidence-retrieval descriptor embedded in story/review/design prompts."""
    outline_info = document_outline(workflow_path)
    descriptor: dict[str, Any] = {
        'command_prefix': [sys.executable, '-m', 'agent.evidence_search', '--workflow', str(Path(workflow_path).resolve())],
        'examples': [
            'search "<关键词或物理量/公式/图号>" --top-k 8',
            'search "equation formula 公式" --modality formula --top-k 6',
            'search "control baseline limitation 对照 边界" --scope all',
            'outline',
            'read-lines --start 1 --end 80',
        ],
        'registry_summary': {
            'count': outline_info['registry_count'],
            'by_modality': outline_info['by_modality'],
            'by_support_type': outline_info['by_support_type'],
        },
        'outline': outline_info['sections'],
        'source_markdown': outline_info['source_markdown'],
        'instructions': (
            'Use evidence_lookup whenever you need to verify exact numbers, formulas, controls, '
            'initialization/methods, negative findings, or supplementary conditions beyond the initial '
            'evidence_store. Prefer exact EVxxxx IDs returned in registry_hits or nearest_ev_ids; '
            'if an essential passage is missing from evidence_registry (not_in_registry=true), report the '
            'gap or trigger replan_from=queries instead of inventing EV IDs.'
        ),
    }
    if job_id:
        descriptor['mcp_call'] = {
            'tool': 'totalpipe_advance',
            'arguments': {
                'job_id': job_id,
                'evidence_query': {'query': '<keywords>', 'top_k': 8, 'scope': 'all'},
            },
        }
    return descriptor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Search Total-pipe evidence registry, source paper, and SI.')
    parser.add_argument('--workflow', required=True, type=Path)
    sub = parser.add_subparsers(dest='command', required=True)

    p_search = sub.add_parser('search')
    p_search.add_argument('query')
    p_search.add_argument('--top-k', type=int, default=8)
    p_search.add_argument('--scope', choices=('all', 'registry', 'source', 'supplementary'), default='all')
    p_search.add_argument('--modality', default=None)
    p_search.add_argument('--section', default=None)

    sub.add_parser('outline')

    p_read = sub.add_parser('read-lines')
    p_read.add_argument('--start', required=True, type=int)
    p_read.add_argument('--end', required=True, type=int)
    p_read.add_argument('--file', default=None)

    args = parser.parse_args(argv)
    if args.command == 'search':
        payload = search_evidence(
            args.workflow,
            args.query,
            top_k=args.top_k,
            scope=args.scope,
            modality=args.modality,
            section=args.section,
        )
    elif args.command == 'outline':
        payload = document_outline(args.workflow)
    else:
        payload = read_source_lines(args.workflow, args.start, args.end, file_path=args.file)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
