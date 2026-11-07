"""Explicit compile/build integration; no source-file mutation or model invocation."""
import copy
from dataclasses import dataclass
import json
from pathlib import Path

from ..contracts import digest, issue
from .adapter import DeckIRAdapter
from .plugin import EnhanceResult, enhance
from .specs import Options, object_fields

class CompilationAdapter(DeckIRAdapter):
    """Use the selected build provider and retain the final checked compilation."""
    def __init__(self, base, compile_fn):
        super().__init__(base)
        self.compile_fn = compile_fn
        self.last = None

    def compile(self, deck_ir):
        layout, findings = self.compile_fn(copy.deepcopy(deck_ir))
        if layout is None or any(item['severity'] == 'FAIL' for item in findings):
            raise ValueError('compile_failed')
        if layout.get('ir_sha256') != digest(deck_ir):
            raise ValueError('compile_failed')
        self.last = (digest(deck_ir), layout, findings)
        return layout


@dataclass
class PreparedEnhancement:
    result: EnhanceResult
    request_sha256: str | None = None
    compiled: tuple | None = None

    def audit(self, source, output_ir):
        return {**self.result.audit(), 'request_sha256': self.request_sha256,
                'source_ir_sha256': digest(source),
                'enhanced_ir_sha256': digest(self.result.deck_ir),
                'output_ir_sha256': digest(output_ir)}

    def summary(self, source, output_ir, audit_path):
        return {'status': self.result.status,
                'mode': self.result.diagnostics.get('mode'),
                'applied_visuals': len(self.result.manifest),
                'added_objects': len(self.result.added_object_ids),
                'request_sha256': self.request_sha256,
                'source_ir_sha256': digest(source), 'output_ir_sha256': digest(output_ir),
                'audit': str(audit_path.resolve()), 'warnings': list(self.result.warnings)}

    def findings(self):
        status = self.result.status
        items = [issue('EXPLAIN_VIZ_'+status.upper(), 'WARNING' if status == 'fallback' else 'INFO',
                       f'ExplainViz {status}; accepted {len(self.result.manifest)} diagrams.',
                       detector='explain-viz', warnings=list(self.result.warnings))]
        if status == 'enhanced':
            items.append(issue('EXPLAIN_VIZ_SEMANTIC_REVIEW', 'REVIEW',
                'Review the source-bound teaching diagrams for scientific fidelity; layout checks do not prove scientific truth.',
                detector='explain-viz', confidence='MEDIUM',
                slide_ids=[item['slide_id'] for item in self.result.manifest]))
        return items


def prepare(deck_ir, request, base, compile_fn, mode=None):
    """Load a bounded self-contained request, failing open on all plugin/config errors."""
    request_hash = None
    try:
        if mode not in (None, 'auto', 'off', 'prefer'):
            raise ValueError('invalid_mode')
        value = ({'version': '1.0', 'options': {'mode': 'off'}} if mode == 'off' else
                 {'version': '1.0', 'options': {}} if request is None else
                 json.loads(Path(request).read_text(encoding='utf-8'))
                 if isinstance(request, (str, Path)) else copy.deepcopy(request))
        object_fields(value, ('version', 'options'), ('slots', 'proposal'))
        if value['version'] != '1.0':
            raise ValueError('unsupported_request')
        request_hash = digest(value)
        options = Options.read({**value['options'], **({'mode': mode} if mode else {})})
        adapter = CompilationAdapter(base, compile_fn)
        result = enhance(deck_ir, {key: value[key] for key in ('slots', 'proposal') if key in value},
                         options, adapter)
        compiled = None
        if result.status == 'enhanced':
            if not adapter.last or adapter.last[0] != digest(result.deck_ir):
                raise ValueError('missing_compilation_snapshot')
            compiled = adapter.last[1:]
        return PreparedEnhancement(result, request_hash, compiled)
    except Exception:
        # Never echo config, scientific copy, exception bodies or model text into QA.
        result = EnhanceResult(deck_ir, status='fallback', warnings=['invalid_request'],
                               diagnostics={'plugin_version': '1.0', 'model_calls': 0, 'compile_calls': 0})
        return PreparedEnhancement(result, request_hash)


def blocked(source):
    """An upstream Design gate is not permission to run ExplainViz."""
    return PreparedEnhancement(EnhanceResult(source, status='skipped',
        warnings=['visual_design_required'], diagnostics={'plugin_version': '1.0',
                                                         'model_calls': 0, 'compile_calls': 0}))
