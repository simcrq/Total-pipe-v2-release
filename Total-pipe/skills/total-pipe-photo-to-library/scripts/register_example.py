#!/usr/bin/env python3
"""Validate, regression-check, and atomically register Total-pipe Deck IR examples
into Total-pipe/examples/library/index.json.

Works both when executed from inside the Total-pipe checkout and when installed
into an external agent skills directory (auto-discovers Total-pipe from cwd or
--repo-root).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import runpy
import sys
from typing import Any

KEBAB_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
SNAKE_PY_RE = re.compile(r'^[a-z0-9]+(?:_[a-z0-9]+)*\.py$')

# Privacy & portability leak patterns (never allowed in public library examples).
EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
LOCAL_PATH_RE = re.compile(r'(?:[A-Za-z]:\\Users\\|/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/)')
CN_PHONE_RE = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')

# Locked search queries verified by Total-pipe/tests/test_example_library.py.
# New entries MUST NOT hijack rank #1 for any of these queries.
LOCKED_QUERIES: tuple[tuple[str, str], ...] = (
    ('独立正文块加圆角标题和编号', 'independent-blocks'),
    ('A/B 对照路线 动作标签', 'comparison-lanes'),
    ('directional annotations caption_for', 'directional-notes'),
    ('原图导读 图文并排', 'figure-readout'),
    ('误差棒 y_error', 'chart-uncertainty'),
    ('native table merged headers', 'grouped-table'),
    ('行内公式 独立公式 符号定义', 'equation-explainer'),
    ('机制图 假设虚线', 'mechanism-hypothesis'),
    ('复杂混排 曲线与公式', 'rc-discharge-composite'),
)


def _discover_component_root(explicit_root: Path | None) -> Path:
    """Locate the Total-pipe component directory containing examples/library/index.json."""
    candidates: list[Path] = []
    if explicit_root is not None:
        r = explicit_root.expanduser().resolve()
        candidates.extend([r, r / 'Total-pipe'])
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        candidates.append(parent / 'Total-pipe')
        candidates.append(parent)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / 'Total-pipe')
        candidates.append(parent)

    seen: set[Path] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        if (cand / 'examples' / 'library' / 'index.json').is_file() and (cand / 'deck_compiler').is_dir():
            return cand
    raise FileNotFoundError(
        'Cannot locate Total-pipe directory (expected examples/library/index.json and deck_compiler/). '
        'Pass --repo-root pointing to the repository root or Total-pipe directory.'
    )


def _parse_tags(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith('['):
        parsed = json.loads(text)
        if not isinstance(parsed, list) or not all(isinstance(t, str) for t in parsed):
            raise ValueError('--tags JSON must be a list of strings')
        tags = [t.strip() for t in parsed if t.strip()]
    else:
        tags = [part.strip() for part in re.split(r'[,，;；]+', text) if part.strip()]
    # Deduplicate while preserving order
    deduped: list[str] = []
    seen_lower: set[str] = set()
    for tag in tags:
        key = tag.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            deduped.append(tag)
    return deduped


def _privacy_scan(script_path: Path, deck_value: dict[str, Any], component_root: Path) -> list[dict[str, str]]:
    """Scan script source and generated Deck IR for PII, local paths, or broken figure assets."""
    findings: list[dict[str, str]] = []
    source_text = script_path.read_text(encoding='utf-8')
    ir_text = json.dumps(deck_value, ensure_ascii=False)

    for label, blob in (('script', source_text), ('deck_ir', ir_text)):
        for match in EMAIL_RE.findall(blob):
            if not match.endswith('@example.com') and not match.endswith('@example.org'):
                findings.append({'severity': 'FAIL', 'code': 'PRIVACY_EMAIL', 'detail': f'{label} contains email {match!r}'})
        for match in LOCAL_PATH_RE.findall(blob):
            findings.append({'severity': 'FAIL', 'code': 'LOCAL_USER_PATH', 'detail': f'{label} contains user path {match!r}'})
        for match in CN_PHONE_RE.findall(blob):
            findings.append({'severity': 'FAIL', 'code': 'PRIVACY_PHONE', 'detail': f'{label} contains phone-like digits {match!r}'})

    # Verify all figure assets resolve inside Total-pipe/examples/
    examples_root = (component_root / 'examples').resolve()
    library_root = (examples_root / 'library').resolve()
    assets = deck_value.get('assets') or {}
    if isinstance(assets, dict):
        for asset_key, asset_spec in assets.items():
            raw_path = asset_spec.get('path') if isinstance(asset_spec, dict) else (asset_spec if isinstance(asset_spec, str) else None)
            if not raw_path:
                continue
            p = Path(raw_path)
            resolved = p.resolve() if p.is_absolute() else (library_root / p).resolve()
            if not resolved.is_file():
                findings.append({'severity': 'FAIL', 'code': 'MISSING_ASSET', 'detail': f'asset {asset_key!r} not found at {resolved}'})
            else:
                try:
                    resolved.relative_to(examples_root)
                except ValueError:
                    findings.append({
                        'severity': 'FAIL',
                        'code': 'ASSET_OUTSIDE_EXAMPLES',
                        'detail': f'asset {asset_key!r} points outside Total-pipe/examples/: {resolved}',
                    })
    return findings


def _evaluate_candidate(
    component_root: Path,
    script_path: Path,
    entry: dict[str, Any],
    existing_entries: list[dict[str, Any]],
    *,
    allow_update: bool,
    primary_queries: list[str],
) -> dict[str, Any]:
    if str(component_root) not in sys.path:
        sys.path.insert(0, str(component_root))

    from agent.ir_preview import build_visual_checklist
    from deck_compiler.example_index import search as index_search
    from deck_compiler.ir import validate as ir_validate
    from deck_compiler.layout import compile_deck

    library_dir = (component_root / 'examples' / 'library').resolve()
    if str(library_dir) not in sys.path:
        sys.path.insert(0, str(library_dir))
    failures: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []

    # 1. Metadata validation
    ex_id = entry['id']
    if not KEBAB_RE.fullmatch(ex_id):
        failures.append({'code': 'INVALID_ID', 'message': f'id {ex_id!r} must be lowercase kebab-case'})

    existing_ids = {item['id'] for item in existing_entries}
    if ex_id in existing_ids and not allow_update:
        failures.append({'code': 'DUPLICATE_ID', 'message': f'id {ex_id!r} already exists in index.json (pass --update to modify)'})

    if not entry['title'].strip():
        failures.append({'code': 'EMPTY_TITLE', 'message': 'title must be non-empty'})
    if not entry['summary'].strip():
        failures.append({'code': 'EMPTY_SUMMARY', 'message': 'summary must be non-empty'})
    if len(entry['tags']) < 4:
        reviews.append({'code': 'FEW_TAGS', 'message': f'only {len(entry["tags"])} tags provided; recommend 6-14 bilingual tags'})

    has_cjk = any(any('\u4e00' <= ch <= '\u9fff' for ch in t) for t in entry['tags'])
    has_ascii = any(any('a' <= ch.lower() <= 'z' for ch in t) for t in entry['tags'])
    if not (has_cjk and has_ascii):
        reviews.append({'code': 'MONOLINGUAL_TAGS', 'message': 'tags should include both Chinese intent terms and English/Deck IR keywords'})

    resolved_script = script_path.expanduser().resolve()
    if not resolved_script.is_file():
        failures.append({'code': 'MISSING_SCRIPT', 'message': f'script not found: {resolved_script}'})
        return {'status': 'FAIL', 'failures': failures, 'reviews': reviews}

    if resolved_script.parent != library_dir:
        failures.append({'code': 'SCRIPT_OUTSIDE_LIBRARY', 'message': f'script must live directly in {library_dir}'})
    if not SNAKE_PY_RE.fullmatch(resolved_script.name):
        failures.append({'code': 'INVALID_SCRIPT_NAME', 'message': f'script filename {resolved_script.name!r} should be lowercase snake_case.py'})

    # 2. Execute make_deck()
    try:
        module_ns = runpy.run_path(str(resolved_script))
        if 'make_deck' not in module_ns or not callable(module_ns['make_deck']):
            raise ValueError('script must define a zero-argument make_deck() function')
        deck_value = module_ns['make_deck']()
    except Exception as exc:
        failures.append({'code': 'MAKE_DECK_ERROR', 'message': f'make_deck() failed: {exc}'})
        return {'status': 'FAIL', 'failures': failures, 'reviews': reviews}

    # 3. Privacy & asset portability check
    for finding in _privacy_scan(resolved_script, deck_value, component_root):
        if finding['severity'] == 'FAIL':
            failures.append({'code': finding['code'], 'message': finding['detail']})
        else:
            reviews.append({'code': finding['code'], 'message': finding['detail']})

    # 4. Optional JSON Schema validation
    schema_status = 'SKIPPED (jsonschema not installed)'
    try:
        import jsonschema  # type: ignore

        schema = json.loads((component_root / 'schemas' / 'deck-ir.schema.json').read_text(encoding='utf-8'))
        jsonschema.validate(deck_value, schema)
        schema_status = 'PASS'
    except ImportError:
        pass
    except Exception as exc:
        schema_status = 'FAIL'
        failures.append({'code': 'SCHEMA_INVALID', 'message': f'deck-ir.schema.json validation failed: {exc}'})

    # 5. IR validate + compile_deck
    ir_issues = ir_validate(deck_value)
    layout, compile_issues = compile_deck(deck_value, library_dir)
    all_issues = list(ir_issues) + list(compile_issues)
    fail_issues = [i for i in all_issues if i.get('severity') == 'FAIL']
    review_issues = [i for i in all_issues if i.get('severity') in ('REVIEW', 'WARNING')]

    def _extract_issue(item: dict[str, Any]) -> dict[str, Any]:
        entry_out: dict[str, Any] = {
            'code': item.get('rule') or item.get('code') or 'COMPILE_ISSUE',
            'slide': item.get('slide'),
            'message': item.get('message', str(item)),
        }
        src = item.get('source')
        if isinstance(src, dict):
            for key in ('component', 'required_size_px', 'available_size_px', 'cause',
                        'suggested_actions', 'subtree_breakdown'):
                if key in src and src[key] is not None:
                    entry_out[key] = src[key]
        return entry_out

    for item in fail_issues:
        failures.append(_extract_issue(item))
    for item in review_issues:
        reviews.append(_extract_issue(item))

    # 6. Visual checklist per slide
    slide_checklists: list[dict[str, Any]] = []
    if layout and isinstance(layout.get('slides'), list):
        for sl in layout['slides']:
            sid = sl.get('id')
            sl_issues = [i for i in all_issues if i.get('slide') in (None, sid)]
            checklist = build_visual_checklist(sl, sl_issues, {})
            slide_checklists.append({'slide_id': sid, 'checklist': checklist})
            for check_name, detail in checklist.items():
                st = detail.get('status')
                if st == 'FAIL':
                    failures.append({'code': f'VISUAL_{check_name.upper()}', 'slide': sid, 'detail': detail})
                elif st == 'REVIEW':
                    reviews.append({'code': f'VISUAL_{check_name.upper()}', 'slide': sid, 'detail': detail})

    # 7. Simulated index search regression & recall check
    candidate_entries = [item for item in existing_entries if item['id'] != ex_id] + [entry]
    hijacked: list[dict[str, Any]] = []
    for query, expected_id in LOCKED_QUERIES:
        hits = index_search(query, candidate_entries, limit=2)
        top_id = hits[0]['id'] if hits else None
        if top_id != expected_id:
            hijacked.append({'query': query, 'expected': expected_id, 'actual_top1': top_id})
            failures.append({
                'code': 'LOCKED_QUERY_HIJACKED',
                'message': f'Locked query {query!r} expected {expected_id!r} as #1, got {top_id!r}. Trim overlapping tags.',
            })

    query_results: list[dict[str, Any]] = []
    for q in primary_queries:
        hits = index_search(q, candidate_entries, limit=3)
        top_ids = [h['id'] for h in hits]
        hit_top1 = bool(top_ids and top_ids[0] == ex_id)
        query_results.append({'query': q, 'rank1_pass': hit_top1, 'top3': top_ids})
        if not hit_top1:
            failures.append({
                'code': 'PRIMARY_QUERY_MISS',
                'message': f'Primary query {q!r} did not rank {ex_id!r} as #1 (top3={top_ids}). Strengthen distinctive tags.',
            })

    # 8. High tag-overlap similarity warning against existing entries
    cand_tags = {t.lower() for t in entry['tags']}
    similar_existing: list[dict[str, Any]] = []
    for item in existing_entries:
        if item['id'] == ex_id:
            continue
        other_tags = {t.lower() for t in item.get('tags', [])}
        union = cand_tags | other_tags
        if not union:
            continue
        jaccard = len(cand_tags & other_tags) / len(union)
        if jaccard >= 0.45:
            similar_existing.append({
                'existing_id': item['id'],
                'jaccard': round(jaccard, 2),
                'shared_tags': sorted(cand_tags & other_tags),
            })
            reviews.append({
                'code': 'HIGH_TAG_OVERLAP',
                'message': f'Tags overlap {round(jaccard * 100)}% with existing {item["id"]!r}; verify this is a distinct layout pattern.',
            })

    status = 'FAIL' if failures else ('REVIEW' if reviews else 'PASS')
    return {
        'status': status,
        'id': ex_id,
        'script': resolved_script.name,
        'slide_count': len((deck_value or {}).get('slides') or []),
        'schema_check': schema_status,
        'locked_queries_passed': len(LOCKED_QUERIES) - len(hijacked),
        'locked_queries_total': len(LOCKED_QUERIES),
        'primary_query_results': query_results,
        'visual_checklists': slide_checklists,
        'similar_existing': similar_existing,
        'failures': failures,
        'reviews': reviews,
    }


def cmd_find_similar(args: argparse.Namespace) -> int:
    component_root = _discover_component_root(args.repo_root)
    if str(component_root) not in sys.path:
        sys.path.insert(0, str(component_root))
    from deck_compiler.example_index import inventory, search

    entries = inventory()
    query_parts = []
    if args.query:
        query_parts.append(args.query)
    if args.tags:
        query_parts.extend(_parse_tags(args.tags))
    combined = ' '.join(query_parts).strip()
    hits = search(combined, entries, limit=args.limit) if combined else []
    print(
        json.dumps(
            {
                'status': 'PASS',
                'total_library_entries': len(entries),
                'query': combined,
                'matches': hits,
                'all_ids': [e['id'] for e in entries],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_check_or_register(args: argparse.Namespace, *, do_register: bool) -> int:
    component_root = _discover_component_root(args.repo_root)
    index_path = component_root / 'examples' / 'library' / 'index.json'
    index_data = json.loads(index_path.read_text(encoding='utf-8'))
    existing_entries = index_data.get('entries', [])

    tags = _parse_tags(args.tags)
    script_path = Path(args.script)
    if not script_path.is_absolute() and not script_path.is_file():
        candidate = component_root / 'examples' / 'library' / script_path.name
        if candidate.is_file():
            script_path = candidate

    entry = {
        'id': args.id.strip(),
        'title': args.title.strip(),
        'tags': tags,
        'summary': args.summary.strip(),
        'script': script_path.name,
    }

    report = _evaluate_candidate(
        component_root,
        script_path,
        entry,
        existing_entries,
        allow_update=args.update,
        primary_queries=args.primary_query or [],
    )

    blocked = bool(report['failures']) or (args.strict and bool(report['reviews']))
    if not do_register:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if blocked else 0

    if blocked:
        report['registered'] = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    if args.dry_run:
        report['registered'] = False
        report['dry_run'] = True
        report['entry_preview'] = entry
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # Atomic update to index.json
    new_entries = []
    replaced = False
    for item in existing_entries:
        if item['id'] == entry['id']:
            new_entries.append(entry)
            replaced = True
        else:
            new_entries.append(item)
    if not replaced:
        new_entries.append(entry)

    index_data['entries'] = new_entries
    tmp_path = index_path.with_suffix('.json.tmp')
    tmp_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp_path.replace(index_path)

    report['registered'] = True
    report['action'] = 'updated' if replaced else 'appended'
    report['total_entries'] = len(new_entries)
    report['index_path'] = str(index_path.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    component_root = _discover_component_root(args.repo_root)
    if str(component_root) not in sys.path:
        sys.path.insert(0, str(component_root))
    from deck_compiler.example_index import search as index_search
    from deck_compiler.ir import validate as ir_validate
    from deck_compiler.layout import compile_deck

    library_dir = (component_root / 'examples' / 'library').resolve()
    if str(library_dir) not in sys.path:
        sys.path.insert(0, str(library_dir))
    index_data = json.loads((library_dir / 'index.json').read_text(encoding='utf-8'))
    entries = index_data.get('entries', [])

    failures: list[dict[str, Any]] = []
    ids = [e['id'] for e in entries]
    if len(ids) != len(set(ids)):
        failures.append({'code': 'DUPLICATE_IDS', 'message': 'Duplicate IDs found in index.json'})

    for query, expected_id in LOCKED_QUERIES:
        hits = index_search(query, entries, limit=1)
        got = hits[0]['id'] if hits else None
        if got != expected_id:
            failures.append({'code': 'LOCKED_QUERY_FAIL', 'query': query, 'expected': expected_id, 'actual': got})

    checked = 0
    for entry in entries:
        script_path = library_dir / entry['script']
        if not script_path.is_file():
            failures.append({'code': 'MISSING_SCRIPT', 'id': entry['id'], 'script': entry['script']})
            continue
        try:
            deck_val = runpy.run_path(str(script_path))['make_deck']()
            issues = list(ir_validate(deck_val))
            _, comp_issues = compile_deck(deck_val, library_dir)
            issues.extend(comp_issues)
            hard = [i for i in issues if i.get('severity') == 'FAIL']
            if hard:
                failures.append({'code': 'COMPILE_FAIL', 'id': entry['id'], 'issues': hard})
            checked += 1
        except Exception as exc:
            failures.append({'code': 'EXEC_ERROR', 'id': entry['id'], 'message': str(exc)})

    print(
        json.dumps(
            {
                'status': 'FAIL' if failures else 'PASS',
                'total_entries': len(entries),
                'compiled_ok': checked,
                'locked_queries_checked': len(LOCKED_QUERIES),
                'failures': failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failures else 0


def _add_candidate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--repo-root', type=Path, help='Repository root or Total-pipe directory')
    parser.add_argument('--script', required=True, help='Path or filename of example script under examples/library/')
    parser.add_argument('--id', required=True, help='Unique lowercase kebab-case example ID')
    parser.add_argument('--title', required=True, help='Concise Chinese title describing the layout pattern')
    parser.add_argument('--summary', required=True, help='1-2 sentence summary of visual structure and reading flow')
    parser.add_argument('--tags', required=True, help='Comma-separated tags or JSON array of bilingual tags')
    parser.add_argument('--primary-query', action='append', help='Target retrieval query that MUST rank this example #1 (repeatable)')
    parser.add_argument('--update', action='store_true', help='Allow updating an existing ID in index.json')
    parser.add_argument('--strict', action='store_true', help='Treat REVIEW warnings as hard FAIL')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)

    p_find = sub.add_parser('find-similar', help='Search existing index.json to avoid duplicate layout patterns')
    p_find.add_argument('--repo-root', type=Path)
    p_find.add_argument('--query', default='', help='Natural-language pattern description')
    p_find.add_argument('--tags', default='', help='Comma-separated candidate tags')
    p_find.add_argument('--limit', type=int, default=5)

    p_check = sub.add_parser('check', help='Validate candidate example script, visual checklist, privacy, and index non-regression')
    _add_candidate_args(p_check)

    p_reg = sub.add_parser('register', help='Validate and atomically register candidate example into index.json')
    _add_candidate_args(p_reg)
    p_reg.add_argument('--dry-run', action='store_true', help='Run full checks without modifying index.json')

    p_audit = sub.add_parser('audit-library', help='Audit every entry currently in Total-pipe/examples/library/index.json')
    p_audit.add_argument('--repo-root', type=Path)

    args = parser.parse_args()
    if args.action == 'find-similar':
        return cmd_find_similar(args)
    if args.action == 'check':
        return cmd_check_or_register(args, do_register=False)
    if args.action == 'register':
        return cmd_check_or_register(args, do_register=True)
    if args.action == 'audit-library':
        return cmd_audit(args)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
