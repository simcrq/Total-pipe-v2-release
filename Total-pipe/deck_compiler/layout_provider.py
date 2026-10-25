"""Layout providers: the plug-in point where a body layout may come from somewhere else.

The compiler owns the canonical content, the page frame and the file writer. A provider may only
propose one body box per unit; it cannot add, drop or rewrite content. That boundary is why the
diffusion model could be removed without touching the writer: it was one implementation of this
interface, not part of the pipeline.

Three providers ship here:

* ``compiler``  -- proposes nothing; the compiler's own family templates lay out every page. This is
  the reference behaviour and the fallback that always exists.
* ``packer``    -- the bundled deterministic packer. It proposes a full body layout, is checked
  against the same geometric gates the compiler enforces, and is the default.
* an external one, loaded as ``module:factory`` or ``path/to/file.py:factory`` (or through
  ``TOTALPIPE_LAYOUT_PROVIDER``). The factory is called with no arguments and must return an object
  with a ``propose(requests)`` method; requests are plain dictionaries (see
  ``totalpipe_layout.contracts.read_requests``). Returning ``{slide_id: {"units": {unit_id:
  {"bbox": [x, y, w, h]}}}}`` is the whole contract. A model, a remote service or a hand-tuned rule
  set all fit behind it, and none of them needs to import the compiler.

A provider that raises, or that proposes a box the gates reject, loses that page to the compiler's
templates: the build never silently ships an unverified layout.
"""
from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from typing import Protocol, runtime_checkable

from .contracts import digest, file_hash, issue
from .layout import compile_deck

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_VARIABLE = 'TOTALPIPE_LAYOUT_PROVIDER'
BUILT_IN = ('packer', 'compiler')


@runtime_checkable
class LayoutProvider(Protocol):
    """One body box per unit, keyed by slide id. Content stays canonical."""

    name: str

    def propose(self, requests: list[dict]) -> dict:
        """Return ``{slide_id: {"units": {unit_id: {"bbox": [x, y, w, h]}}}}``."""
        ...


class CompilerProvider:
    """Propose nothing: the compiler's family templates are the layout."""

    name = 'compiler'

    def propose(self, requests: list[dict]) -> dict:
        return {}


class PackerProvider:
    """The bundled deterministic packer.

    It reads the same requests the compiler produced and answers with a body layout the geometric
    gates accept. When no candidate survives, it answers nothing for that page, which is a normal
    outcome: the compiler templates still lay the page out.
    """

    name = 'packer'

    def __init__(self, totalpipe_root=None):
        self.totalpipe_root = str(totalpipe_root) if totalpipe_root else str(ROOT)

    def propose(self, requests: list[dict]) -> dict:
        from totalpipe_layout.contracts import check, teacher
        proposals = {}
        for request in requests:
            if not request.get('units') or request.get('compiler_owned'):
                continue
            boxes = teacher(request)
            if boxes is None or check(request, boxes):
                continue
            proposals[request['slide_id']] = {'units': {unit['id']: {'bbox': list(box)}
                                                        for unit, box in zip(request['units'], boxes)},
                                              'status': 'PACKED'}
        return proposals


def _load_factory(specification: str):
    if ':' not in specification:
        raise ValueError(f'layout provider {specification!r} is neither built in nor a module:factory')
    # rsplit, not partition: a Windows path starts with a drive letter and that colon is not
    # the separator between the module and the factory.
    target, _, attribute = specification.rpartition(':')
    if target.endswith('.py') or os.sep in target:
        path = Path(target).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f'layout provider file not found: {path}')
        module_name = f'totalpipe_layout_plugin_{path.stem}'
        module_spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(target)
    factory = getattr(module, attribute, None)
    if factory is None:
        raise AttributeError(f'{target!r} has no attribute {attribute!r}')
    return factory


def load_provider(specification=None, totalpipe_root=None) -> LayoutProvider:
    """Resolve a provider name or ``module:factory`` specification."""
    specification = (specification or os.environ.get(ENVIRONMENT_VARIABLE) or 'packer').strip()
    if specification in ('compiler', 'none', 'deterministic'):
        return CompilerProvider()
    if specification == 'packer':
        return PackerProvider(totalpipe_root)
    if specification == 'v26':
        raise ValueError('the v26 diffusion provider was removed; use "packer", "compiler" or '
                         f'"module:factory" instead')
    factory = _load_factory(specification)
    provider = factory()
    if not hasattr(provider, 'propose'):
        raise TypeError(f'layout provider {specification!r} has no propose(requests) method')
    if not getattr(provider, 'name', None):
        provider.name = specification
    return provider


def _propose(provider, requests):
    """Keep the batch API, retrying pages independently if a batch raises."""
    eligible = [(number, request) for number, request in enumerate(requests, 1)
                if not request.get('compiler_owned') and request.get('units')]
    if not eligible or isinstance(provider, CompilerProvider):
        return {}, set(), []
    warnings, failed = [], set()
    name = getattr(provider, 'name', 'unknown')

    def ask(batch):
        result = provider.propose(copy.deepcopy(batch))
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise TypeError('propose(requests) must return a slide-id dictionary or None')
        return result

    def failure(number, request, error):
        failed.add(request['slide_id'])
        warnings.append(issue('LAYOUT_PROVIDER_FAILED', 'WARNING',
                              f'{type(error).__name__}: {error}', number,
                              detector='layout-provider', provider=name))

    try:
        return ask([request for _, request in eligible]), failed, warnings
    except Exception as error:  # external providers must not break unrelated pages
        if len(eligible) == 1:
            failure(*eligible[0], error)
            return {}, failed, warnings
        warnings.append(issue('LAYOUT_PROVIDER_BATCH_RETRY', 'WARNING',
                              f'{type(error).__name__}: {error}; retrying individual pages',
                              detector='layout-provider', provider=name))
    proposed = {}
    for number, request in eligible:
        try:
            answer = ask([request])
            if request['slide_id'] in answer:
                proposed[request['slide_id']] = answer[request['slide_id']]
        except Exception as error:
            failure(number, request, error)
    return proposed, failed, warnings


def _finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def compile_with_provider(ir_path, provider=None, totalpipe_root=None):
    """Compile a deck, letting ``provider`` propose the body layout.

    Returns ``(layout, findings)`` exactly like ``compile_deck``. Provider provenance lands in
    ``layout['layout_provider']``; pages the provider lost or spoiled are recorded there too.
    """
    ir_path = Path(ir_path)
    ir = json.loads(ir_path.read_text(encoding='utf-8'))
    baseline, baseline_issues = compile_deck(ir, ir_path.parent)
    if baseline is None:
        return baseline, baseline_issues
    if provider is None:
        provider = load_provider(totalpipe_root=totalpipe_root)
    from totalpipe_layout.contracts import check, digest as request_digest, read_requests
    requests, meta = read_requests(ir_path, totalpipe_root or ROOT,
                                   layout=baseline, compile_issues=baseline_issues)
    proposals: dict = {}
    records = []
    proposed, failed, warnings = _propose(provider, requests)
    for request in requests:
        proposal = proposed.get(request['slide_id'])
        record = {'slide_id': request['slide_id'], 'request_sha256': request_digest(request),
                  'status': 'COMPILER_FALLBACK',
                  'reason': 'provider_error' if request['slide_id'] in failed else 'no_proposal'}
        owned = request.get('compiler_owned') or ('provider_disabled' if isinstance(provider, CompilerProvider) else None)
        if owned or not request.get('units'):
            record.update(status='COMPILER_OWNED', reason=owned or 'no_units')
            records.append(record)
            continue
        if proposal is not None:
            if not isinstance(proposal, dict):
                record.update(status='REJECTED_GATES', reason='invalid_proposal',
                              violations=['MALFORMED_PROPOSAL'])
                records.append(record)
                continue
            units = proposal.get('units') or {}
            expected = [unit['id'] for unit in request['units']]
            if not isinstance(units, dict) or set(units) != set(expected):
                record.update(status='REJECTED_UNIT_MISMATCH', reason='unit_mismatch')
            else:
                boxes = [units[unit_id].get('bbox') if isinstance(units[unit_id], dict) else None
                         for unit_id in expected]
                violations = check(request, boxes) if all(
                    isinstance(box, (list, tuple)) and len(box) == 4 and all(_finite_number(v) for v in box)
                    for box in boxes) else ['MALFORMED_BBOX']
                if any(unit['role'] == 'figure' and units[unit['id']].get('caption_height') is not None
                       and (not _finite_number(units[unit['id']]['caption_height'])
                            or units[unit['id']]['caption_height'] < 0)
                       for unit in request['units'] if isinstance(units[unit['id']], dict)):
                    violations.append('MALFORMED_CAPTION_HEIGHT')
                if violations:
                    record.update(status='REJECTED_GATES', reason='geometric_gates')
                    record['violations'] = violations[:8]
                else:
                    kept = {}
                    for unit, box in zip(request['units'], boxes):
                        entry = {'bbox': [float(value) for value in box]}
                        if unit['role'] == 'figure':
                            caption_height = proposal['units'][unit['id']].get('caption_height')
                            if caption_height is not None:
                                entry['caption_height'] = caption_height
                        kept[unit['id']] = entry
                    proposals[request['slide_id']] = {'units': kept, 'status': 'PACKED',
                                                      'provider': getattr(provider, 'name', 'unknown')}
                    record['status'] = 'PACKED'
                    record.pop('reason', None)
        records.append(record)
    result, findings = (compile_deck(ir, ir_path.parent, proposals=proposals)
                        if proposals else (baseline, list(baseline_issues)))
    # A compiler failure is never attributed to the provider silently: retry those pages with the
    # deterministic templates and keep whatever failure remains visible.
    rejected = {finding.get('slide') for finding in findings if finding['severity'] == 'FAIL'}
    changed = False
    for number in rejected:
        if isinstance(number, int) and 1 <= number <= len(records):
            slide_id = records[number - 1]['slide_id']
            if slide_id in proposals:
                proposals.pop(slide_id)
                changed = True
                records[number - 1]['status'] = 'COMPILER_FALLBACK'
                records[number - 1]['reason'] = 'compiler_rejected'
                records[number - 1]['rejected_rules'] = [
                    finding['rule'] for finding in findings
                    if finding.get('slide') == number and finding['severity'] == 'FAIL']
    if changed:
        result, findings = (compile_deck(ir, ir_path.parent, proposals=proposals)
                            if proposals else (baseline, list(baseline_issues)))
    findings = warnings + findings
    if result:
        sources = [Path(__file__), ROOT/'deck_compiler/layout.py',
                   ROOT/'deck_compiler/academic_layout.py', ROOT/'deck_compiler/visual_design.py',
                   ROOT/'deck_compiler/layout_tree.py', ROOT/'deck_compiler/layout_feedback.py',
                   ROOT/'deck_compiler/native_table.py',
                   ROOT/'deck_compiler/inline_text.py', ROOT/'totalpipe_layout/inline_math.py',
                   *sorted((ROOT/'totalpipe_layout').glob('*.py'))]
        if getattr(provider, 'source_files', None):
            sources.extend(Path(path) for path in provider.source_files)
        packed = sum(r['status'] == 'PACKED' for r in records)
        owned = sum(r['status'] == 'COMPILER_OWNED' for r in records)
        offered = len(records) - owned
        result['layout_provider'] = {
            'name': getattr(provider, 'name', 'unknown'),
            'kind': type(provider).__name__,
            'ir_sha256': digest(ir),
            'compiler_sha256': meta.get('compiler_sha256'),
            'slides': records,
            'counts': {'packed': packed, 'owned': owned,
                       'fallback': sum(r['status'] == 'COMPILER_FALLBACK' for r in records),
                       'rejected': sum(r['status'].startswith('REJECTED') for r in records),
                       'coverage': packed / offered if offered else None},
            'source_sha256': {str(path.relative_to(ROOT)) if ROOT in Path(path).resolve().parents
                              else str(path): file_hash(path) for path in sources if Path(path).is_file()},
        }
        for number, record in enumerate(records, 1):
            findings.append(issue('LAYOUT_PROVIDER', 'INFO', record['status'], number,
                                  detector='layout-provider', provider=getattr(provider, 'name', 'unknown')))
    return result, findings
