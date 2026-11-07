"""Fail-open, per-page transactions around deterministic native teaching templates."""
import copy
from dataclasses import dataclass, field
import time

from ..contracts import digest
from .adapter import DeckIRAdapter
from .decision import auto_decision, candidates
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
                                  'model_calls': 0, 'compile_calls': 0, 'layout_attempts': 0,
                                  'slot_policy': config.slot_policy, 'local_reflow': config.allow_local_reflow}
            if config.mode == 'off':
                result.status = 'disabled'
                return result
            if config.max_visuals_per_deck == 0:
                result.decisions.append({'decision': 'skip', 'reason': 'deck_budget'})
                return result
            context = context or {}
            adapter = adapter or DeckIRAdapter(context.get('base', '.'))
            slides = adapter.list_slides(deck_ir)
            if set(config.protected_slide_ids) - {slide['id'] for slide in slides}:
                raise ValueError('invalid_protected_slides')
            slots_value = context.get('slots')
            if slots_value is None:
                slots_value = adapter.discover_slots(deck_ir, config)
            slots = read_slots(slots_value, {s['id'] for s in slides})
            result.diagnostics.update(input_ir_sha256=digest(deck_ir), slots_sha256=digest(slots_value))
            pending = []
            existing = sum(adapter.already_processed(slide) for slide in slides)
            for slide in slides:
                sid = slide['id']
                reason = None
                if sid in config.protected_slide_ids:
                    reason = 'protected_slide'
                elif slide['composition'].get('visual_intent'):
                    reason = 'hard_visual_intent'
                elif sid not in slots:
                    reason = 'no_slot'
                elif adapter.already_processed(slide):
                    reason = 'already_enhanced'
                elif adapter.find_visual_slot(slide, slots[sid]) is None and (
                        config.slot_policy == 'reserved_only' or any(
                            g['id'] == slots[sid]['graphic_id'] for g in slide['composition'].get('graphics', []))):
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
            automatic = context.get('proposal') is None
            proposal = ({sid: auto_decision(sid, semantics, templates) for sid, semantics, templates in pending}
                        if automatic else read_proposal(context['proposal'], digest(deck_ir), digest(slots_value), set(slots)))
            working, baseline = copy.deepcopy(deck_ir), None
            for sid, semantics, templates in pending:
                entry = proposal.get(sid)
                record = {'slide_id': sid, 'decision': 'skip', 'reason': 'no_decision',
                          'decision_origin': 'source_rules' if automatic else 'agent_proposal'}
                result.decisions.append(record)
                if existing+len(result.manifest) >= config.max_visuals_per_deck:
                    record['reason'] = 'deck_budget'
                    continue
                if entry is None:
                    continue
                if entry['decision'] == 'skip':
                    record['reason'] = entry['reason'] if automatic else 'agent_skip'
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
                    accepted, last_reason = False, 'insufficient_space'
                    for attempt, (candidate, placement) in enumerate(
                            adapter.slot_candidates(working, sid, slot, baseline, config)):
                        if (attempt >= config.max_layout_attempts_per_slide or
                                result.diagnostics['layout_attempts'] >= config.max_visuals_per_deck*config.max_layout_attempts_per_slide):
                            last_reason = 'layout_budget'
                            break
                        result.diagnostics['layout_attempts'] += 1
                        try:
                            slide = next(s for s in adapter.list_slides(candidate) if s['id'] == sid)
                            anchor = adapter.find_visual_slot(slide, slot)
                            group = adapter.build_native_group(spec, anchor, candidate['theme'])
                            ids = adapter.append_group(candidate, sid, slot['graphic_id'], group)
                            original_slide = next(s for s in slides if s['id'] == sid)
                            if not any(g['id'] == slot['graphic_id'] for g in
                                       original_slide['composition'].get('graphics', [])):
                                # The synthetic background path is a new native object too.
                                ids.insert(0, f"graphic:{slot['graphic_id']}:path:reserved_area")
                            manifest = {'slide_id': sid, 'graphic_id': slot['graphic_id'],
                                'template': spec['template'], 'spec_sha256': digest(spec),
                                'source_hash': digest({ref: semantics['facts'][ref] for ref in spec['source_fact_ids']}),
                                'source_fact_ids': list(spec['source_fact_ids']),
                                'shape_ids': ids, 'semantic_review_required': True,
                                'slot_source': placement['source'], 'layout_variant': placement['variant'],
                                'free_regions': placement.get('free_regions', [])}
                            result.diagnostics['compile_calls'] += 1
                            checked = adapter.validate_ir(deck_ir, candidate, baseline, result.manifest+[manifest])
                            manifest['slot_box_px'] = adapter.find_slot_box(checked, sid, slot['graphic_id'])
                            manifest['layout_changes'] = layout_changes(baseline, checked, sid)
                            working = candidate
                            result.manifest.append(manifest)
                            record.update(decision='draw', reason='accepted', template=spec['template'],
                                          slot_source=placement['source'], object_count=len(ids), qa='passed')
                            accepted = True
                            break
                        except Exception as error:
                            last_reason = str(error) if type(error) is ValueError and str(error) in REASONS else 'page_failed'
                    if not accepted:
                        raise ValueError(last_reason)
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
    'label_overlap', 'missing_native_object', 'unauthorized_ir_change', 'no_free_region',
    'reflow_font_changed', 'reflow_text_overflow', 'layout_budget', 'page_failed',
    'invalid_slot_policy', 'invalid_reflow_policy', 'invalid_layout_budget', 'invalid_protected_slides'))


def layout_changes(before, after, slide_id):
    old_page = next((p for p in before['slides'] if p['id'] == slide_id), {'elements': []})
    new_page = next((p for p in after['slides'] if p['id'] == slide_id), {'elements': []})
    current = {e['id']: e for e in new_page['elements']}
    return [{'object_id': e['id'], 'before': e['bbox'], 'after': current[e['id']]['bbox']}
            for e in old_page['elements'] if e['id'] in current and any(
                abs(a-b) > .1 for a, b in zip(e['bbox'], current[e['id']]['bbox']))]
