"""Fail-open, per-page transactions around deterministic native teaching templates."""
import copy
from dataclasses import dataclass, field
import time

from ..contracts import digest
from .adapter import DeckIRAdapter
from .decision import candidates
from .specs import Options, decision_score, read_proposal, read_slots, validate_spec


@dataclass
class EnhanceResult:
    deck_ir: dict
    status: str = 'skipped'
    decisions: list = field(default_factory=list)
    added_object_ids: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    manifest: list = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)

    def audit(self):
        return {key: value for key, value in vars(self).items() if key != 'deck_ir'}


def enhance(deck_ir, context=None, options=None, adapter=None):
    return ExplainVizPlugin().enhance(deck_ir, context, options, adapter)


class ExplainVizPlugin:
    version = '1.0'

    def enhance(self, deck_ir, context=None, options=None, adapter=None):
        result = EnhanceResult(deck_ir=deck_ir)
        started = time.monotonic()
        try:
            config = Options.read(options)
            result.diagnostics = {'plugin_version': self.version, 'mode': config.mode,
                                  'model_calls': 0, 'compile_calls': 0}
            if config.mode == 'off':
                result.status = 'disabled'
                return result
            if config.max_visuals_per_deck == 0:
                result.decisions.append({'decision': 'skip', 'reason': 'deck_budget'})
                return result
            context = context or {}
            adapter = adapter or DeckIRAdapter(context.get('base', '.'))
            slides = adapter.list_slides(deck_ir)
            slots_value = context.get('slots', {'version': '1.0', 'slots': []})
            slots = read_slots(slots_value, {s['id'] for s in slides})
            result.diagnostics.update(input_ir_sha256=digest(deck_ir), slots_sha256=digest(slots_value))
            pending = []
            existing = sum(adapter.already_processed(slide) for slide in slides)
            for slide in slides:
                sid = slide['id']
                reason = None
                if sid not in slots:
                    reason = 'no_slot'
                elif adapter.already_processed(slide):
                    reason = 'already_enhanced'
                elif adapter.find_visual_slot(slide, slots[sid]) is None:
                    reason = 'invalid_slot'
                else:
                    semantics = adapter.read_slide_semantics(slide, slots[sid])
                    templates, reason = candidates(semantics)
                    if templates:
                        pending.append((sid, semantics, templates))
                        continue
                result.decisions.append({'slide_id': sid, 'decision': 'skip', 'reason': reason})
            if not pending:
                return result
            if context.get('proposal') is None:
                result.warnings.append('proposal_required')
                for sid, _, _ in pending:
                    result.decisions.append({'slide_id': sid, 'decision': 'skip', 'reason': 'proposal_required'})
                return result
            proposal = read_proposal(context['proposal'], digest(deck_ir), digest(slots_value), set(slots))
            working, baseline = copy.deepcopy(deck_ir), None
            for sid, semantics, templates in pending:
                entry = proposal.get(sid)
                record = {'slide_id': sid, 'decision': 'skip', 'reason': 'no_decision'}
                result.decisions.append(record)
                if existing+len(result.manifest) >= config.max_visuals_per_deck:
                    record['reason'] = 'deck_budget'
                    continue
                if entry is None:
                    continue
                if entry['decision'] == 'skip':
                    record['reason'] = 'agent_skip'
                    continue
                try:
                    score = decision_score(entry)
                    record['score'] = round(score, 6)
                    if entry['scores']['source_confidence'] < .8:
                        raise ValueError('insufficient_facts')
                    if entry['scores']['explanation_gain'] < .5 or entry['scores']['relationship_clarity'] < .6:
                        record['reason'] = 'low_explanation_gain'
                        continue
                    threshold = config.min_auto_score if config.mode == 'auto' else config.min_prefer_score
                    if score < threshold:
                        record['reason'] = 'low_score'
                        continue
                    spec = validate_spec(entry['visual_spec'], semantics['facts'])
                    if spec['template'] not in templates:
                        raise ValueError('template_not_candidate')
                    if baseline is None:
                        result.diagnostics['compile_calls'] += 1
                        try:
                            baseline = adapter.compile(deck_ir)
                        except Exception:
                            record.update(reason='baseline_compile_failed', qa='revert_deck')
                            self._revert(result, 'baseline_compile_failed', deck_ir)
                            return result
                    slot = slots[sid]
                    adapter.find_slot_box(baseline, sid, slot['graphic_id'])
                    # Isolate all adapter mutations, including unexpected exceptions.
                    candidate = copy.deepcopy(working)
                    slide = next(s for s in adapter.list_slides(candidate) if s['id'] == sid)
                    anchor = adapter.find_visual_slot(slide, slot)
                    group = adapter.build_native_group(spec, anchor, candidate['theme'])
                    ids = adapter.append_group(candidate, sid, slot['graphic_id'], group)
                    manifest = {'slide_id': sid, 'graphic_id': slot['graphic_id'],
                                'template': spec['template'], 'spec_sha256': digest(spec),
                                'source_hash': digest({ref: semantics['facts'][ref] for ref in spec['source_fact_ids']}),
                                'source_fact_ids': list(spec['source_fact_ids']),
                                'shape_ids': ids, 'semantic_review_required': True}
                    result.diagnostics['compile_calls'] += 1
                    adapter.validate_ir(deck_ir, candidate, baseline, result.manifest+[manifest])
                    working = candidate
                    result.manifest.append(manifest)
                    record.update(decision='draw', reason='accepted', template=spec['template'],
                                  object_count=len(ids), qa='passed')
                except Exception as error:
                    # Log known bounded error codes only, never page text or raw exceptions.
                    reason = str(error) if type(error) is ValueError and str(error) in REASONS else 'page_failed'
                    record.update(reason=reason, qa='revert_slide')
                    result.warnings.append(f'{sid}:{reason}')
            if result.manifest:
                try:
                    result.diagnostics['compile_calls'] += 1
                    adapter.validate_ir(deck_ir, working, baseline, result.manifest)
                except Exception:
                    self._revert(result, 'final_compile_failed', deck_ir)
                    return result
                result.deck_ir = working
                result.added_object_ids = [f"{item['slide_id']}/{eid}"
                                           for item in result.manifest for eid in item['shape_ids']]
                result.status = 'enhanced'
                result.warnings.append('semantic_review_required')
            elif result.warnings:
                result.status = 'fallback'
            return result
        except Exception as error:
            reason = str(error) if type(error) is ValueError and str(error) in REASONS else 'plugin_failed'
            self._revert(result, reason, deck_ir)
            return result
        finally:
            result.diagnostics['elapsed_ms'] = round((time.monotonic()-started)*1000, 2)

    @staticmethod
    def _revert(result, reason, original):
        result.deck_ir = original
        result.status = 'fallback'
        result.manifest.clear()
        result.added_object_ids.clear()
        result.warnings.append(reason)
        for record in result.decisions:
            if record['decision'] == 'draw':
                record.update(decision='skip', reason=reason, qa='revert_deck')


REASONS = frozenset(('invalid_fields', 'invalid_text', 'invalid_score', 'invalid_mode',
    'invalid_budget', 'invalid_slots', 'invalid_slot_slide', 'unsupported_proposal_version',
    'stale_proposal', 'invalid_decisions', 'invalid_decision_slide', 'invalid_decision',
    'skip_cannot_draw', 'unsupported_template', 'insufficient_facts', 'symbolic_angle_required',
    'invalid_labels', 'unbound_label', 'ambiguous_labels', 'invalid_relations', 'unbound_relation',
    'unsupported_source_relation',
    'template_not_candidate', 'invalid_ir', 'compile_failed', 'insufficient_space',
    'invalid_native_group', 'page_set_changed', 'existing_object_order_changed',
    'existing_object_changed', 'unexpected_object', 'out_of_slot', 'layout_conflict', 'illegible_label',
    'label_overlap', 'missing_native_object', 'unauthorized_ir_change'))
