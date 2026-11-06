"""Bounded internal contracts; these fields never become Deck IR extensions."""
from dataclasses import dataclass
import math
import re

VERSION = '1.0'
PREFIX = 'evz_'
TEMPLATES = ('geometry/peel_angle@1', 'layer_stack@1', 'process_steps@1')
SCORE_KEYS = ('explanation_gain', 'relationship_clarity', 'source_confidence',
              'layout_fit', 'redundancy')


def object_fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(required) | set(optional):
        raise ValueError('invalid_fields')


def text(value, limit=240):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('invalid_text')


def unit(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError('invalid_score')
    return value


@dataclass(frozen=True)
class Options:
    mode: str = 'off'
    max_visuals_per_deck: int = 4
    min_auto_score: float = .75
    min_prefer_score: float = .60

    @classmethod
    def read(cls, value):
        if value is None:
            return cls()
        if isinstance(value, cls):
            value = dict(vars(value))
        object_fields(value, (), cls.__dataclass_fields__)
        result = cls(**value)
        if result.mode not in ('off', 'auto', 'prefer'):
            raise ValueError('invalid_mode')
        if type(result.max_visuals_per_deck) is not int or not 0 <= result.max_visuals_per_deck <= 32:
            raise ValueError('invalid_budget')
        unit(result.min_auto_score)
        unit(result.min_prefer_score)
        return result


def read_slots(value, slide_ids):
    object_fields(value, ('version', 'slots'))
    if value['version'] != VERSION or not isinstance(value['slots'], list) or len(value['slots']) > 128:
        raise ValueError('invalid_slots')
    result = {}
    for slot in value['slots']:
        object_fields(slot, ('slide_id', 'graphic_id'))
        text(slot['slide_id'], 240)
        text(slot['graphic_id'], 64)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', slot['graphic_id']):
            raise ValueError('invalid_slots')
        if slot['slide_id'] not in slide_ids or slot['slide_id'] in result:
            raise ValueError('invalid_slot_slide')
        result[slot['slide_id']] = slot
    return result


def read_proposal(value, ir_hash, slots_hash, slide_ids):
    object_fields(value, ('version', 'ir_sha256', 'slots_sha256', 'slides'))
    if value['version'] != VERSION:
        raise ValueError('unsupported_proposal_version')
    if value['ir_sha256'] != ir_hash or value['slots_sha256'] != slots_hash:
        raise ValueError('stale_proposal')
    if not isinstance(value['slides'], list) or len(value['slides']) > 128:
        raise ValueError('invalid_decisions')
    result = {}
    for entry in value['slides']:
        object_fields(entry, ('slide_id', 'decision', 'reason'),
                      ('scores', 'teaching_goal', 'visual_spec'))
        sid = entry['slide_id']
        text(sid, 240)
        if sid not in slide_ids or sid in result:
            raise ValueError('invalid_decision_slide')
        text(entry['reason'])
        if entry['decision'] not in ('draw', 'skip'):
            raise ValueError('invalid_decision')
        if entry['decision'] == 'skip' and set(entry) != {'slide_id', 'decision', 'reason'}:
            raise ValueError('skip_cannot_draw')
        # Draw payloads are checked inside the page transaction so one bad spec cannot
        # discard accepted diagrams on other pages.
        result[sid] = entry
    return result


def decision_score(entry):
    object_fields(entry, ('slide_id', 'decision', 'reason', 'scores', 'teaching_goal', 'visual_spec'))
    text(entry['teaching_goal'])
    object_fields(entry['scores'], SCORE_KEYS)
    scores = {key: unit(entry['scores'][key]) for key in SCORE_KEYS}
    return (.35*scores['explanation_gain'] + .25*scores['relationship_clarity']
            + .20*scores['source_confidence'] + .20*scores['layout_fit']
            - .30*scores['redundancy'])


def validate_spec(spec, facts):
    object_fields(spec, ('version', 'template', 'source_fact_ids', 'labels', 'relations'))
    if spec['version'] != VERSION or spec['template'] not in TEMPLATES:
        raise ValueError('unsupported_template')
    refs = spec['source_fact_ids']
    if (not isinstance(refs, list) or not 1 <= len(refs) <= 8
            or any(not isinstance(ref, str) or ref not in facts for ref in refs)
            or len(set(refs)) != len(refs)):
        raise ValueError('insufficient_facts')
    labels = spec['labels']
    if spec['template'] == TEMPLATES[0]:
        object_fields(labels, ('substrate', 'film', 'theta'))
        if labels['theta'] not in ('θ', 'theta', 'Θ'):
            raise ValueError('symbolic_angle_required')
        pairs = [('attached_to', 'film', 'substrate'), ('angle_between', 'film', 'substrate')]
    else:
        if not isinstance(labels, dict) or not 2 <= len(labels) <= 4:
            raise ValueError('invalid_labels')
        stem = 'layer' if spec['template'] == TEMPLATES[1] else 'step'
        keys = [f'{stem}_{i}' for i in range(len(labels))]
        if set(labels) != set(keys):
            raise ValueError('invalid_labels')
        relation = 'above' if stem == 'layer' else 'precedes'
        pairs = [(relation, a, b) for a, b in zip(keys, keys[1:])]
    for label in labels.values():
        text(label, 48)
        if '\n' in label or '\r' in label or not any(label in facts[ref] for ref in refs):
            raise ValueError('unbound_label')
    if len(set(labels.values())) != len(labels):
        raise ValueError('ambiguous_labels')
    relations = spec['relations']
    if not isinstance(relations, list) or len(relations) != len(pairs):
        raise ValueError('invalid_relations')
    for relation, expected in zip(relations, pairs):
        object_fields(relation, ('type', 'from', 'to', 'source_fact_ids'))
        if tuple(relation[k] for k in ('type', 'from', 'to')) != expected:
            raise ValueError('invalid_relations')
        sources = relation['source_fact_ids']
        if (not isinstance(sources, list) or not sources or len(sources) > 8
                or any(not isinstance(ref, str) or ref not in refs for ref in sources)
                or len(set(sources)) != len(sources)):
            raise ValueError('unbound_relation')
        # Each relation must cite a current visible statement containing BOTH endpoints;
        # a label appearing somewhere else on the page is not a relationship source.
        if not any(labels[relation['from']] in facts[ref] and labels[relation['to']] in facts[ref]
                   for ref in sources):
            raise ValueError('unbound_relation')
        if not any(_supports_relation(relation['type'], labels[relation['from']],
                                      labels[relation['to']], facts[ref]) for ref in sources):
            raise ValueError('unsupported_source_relation')
    if spec['template'] == TEMPLATES[0] and not any(labels['theta'] in facts[ref] for ref in refs):
        raise ValueError('unbound_label')
    return spec


def _supports_relation(kind, first, second, source):
    if first not in source or second not in source:
        return False
    if re.search(r'(?:不|未|没有|并非|不是|无法|不能).{0,8}(?:贴附|附着|贴合|夹角|从上到下|依次|→|->)'
                 r'|(?:not|never|without)\b.{0,20}(?:attached|adhered|bonded|above|between)', source, re.I):
        return False
    if kind == 'attached_to':
        return bool(re.search(r'贴附|附着|贴合|attached|adhered|bonded', source, re.I))
    if kind == 'angle_between':
        return bool(re.search(r'夹角|相对.{0,40}平面|angle.{0,40}between|relative.{0,40}plane', source, re.I))
    if source.find(first) >= source.find(second):
        return False
    cue = (r'从上到下|自上而下|top.to.bottom' if kind == 'above'
           else r'→|->|依次|顺序|步骤|流程|先.{0,100}再|then|steps?|process')
    return bool(re.search(cue, source, re.I))
