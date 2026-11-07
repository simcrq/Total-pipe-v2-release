"""Cheap conservative opportunity screening, before any agent-authored decision."""
import re

from .specs import TEMPLATES

CUES = {
    TEMPLATES[0]: re.compile(r'剥离角|peel(?:ing)?\s+angle', re.I),
    TEMPLATES[1]: re.compile(r'层叠|叠层|从上到下|自上而下|top.to.bottom|layer\s+stack', re.I),
    TEMPLATES[2]: re.compile(r'步骤|流程|先.{1,100}再|→|->|process|steps?', re.I),
}
SUMMARY = re.compile(r'^(?:目录|参考文献|结论|总结|致谢)|^(?:contents|references|conclusions?|summary)\b', re.I)


def candidates(semantics):
    if semantics['archetype'] in ('cover', 'cover-hero', 'three-conclusions', 'three-limitations'):
        return [], 'summary_page'
    if SUMMARY.search(semantics['title']):
        return [], 'summary_page'
    if semantics['existing_visuals']:
        return [], 'existing_visual'
    content = '\n'.join(semantics['facts'].values())
    templates = [name for name, pattern in CUES.items() if pattern.search(content)]
    return templates, 'candidate' if templates else 'no_explanatory_relation'


def auto_decision(slide_id, semantics, templates):
    """Only explicit symbolic definitions or enumerated orders; no model or new facts."""
    from .specs import validate_spec
    facts = semantics['facts']
    for template in templates:
        for ref, source in facts.items():
            labels, relations = None, []
            if template == TEMPLATES[0]:
                film = next((word for word in ('薄膜', 'film') if word in source), None)
                substrate = next((word for word in ('衬底', '基底', 'substrate') if word in source), None)
                theta = next((word for word in ('θ', 'theta', 'Θ') if word in source), None)
                if film and substrate and theta:
                    labels = dict(substrate=substrate, film=film, theta=theta)
                    relations = [('attached_to', 'film', 'substrate'), ('angle_between', 'film', 'substrate')]
            else:
                if template == TEMPLATES[1]:
                    match = re.search(r'(?:从上到下|自上而下|top.to.bottom)\s*(?:依次)?\s*(?:为|是|:|：)?\s*([^；;。\n]+)', source, re.I)
                    parts = re.split(r'、|，|,|\s+and\s+', match[1]) if match else []
                    stem, kind = 'layer', 'above'
                else:
                    match = re.search(r'(?:依次为|步骤为|流程为|流程：|步骤：|steps?\s*:|process\s*:)\s*([^；;。\n]+)', source, re.I)
                    value = match[1] if match else source.split('；')[0].split('。')[0]
                    parts = re.split(r'→|->', value) if re.search(r'→|->', value) else []
                    stem, kind = 'step', 'precedes'
                parts = [part.strip().rstrip('.') for part in parts]
                if 2 <= len(parts) <= 4 and all(0 < len(part) <= 48 for part in parts):
                    labels = {f'{stem}_{i}': part for i, part in enumerate(parts)}
                    keys = list(labels)
                    relations = [(kind, a, b) for a, b in zip(keys, keys[1:])]
            if labels is None:
                continue
            spec = {'version': '1.0', 'template': template, 'source_fact_ids': [ref], 'labels': labels,
                    'relations': [{'type': kind, 'from': a, 'to': b, 'source_fact_ids': [ref]}
                                  for kind, a, b in relations]}
            try:
                validate_spec(spec, facts)
            except ValueError:
                continue
            return {'slide_id': slide_id, 'decision': 'draw', 'reason': 'explicit_source_relation',
                    'teaching_goal': semantics['title'], 'visual_spec': spec,
                    'scores': dict(explanation_gain=.9, relationship_clarity=.95,
                                   source_confidence=1., layout_fit=.9, redundancy=0.)}
    return {'slide_id': slide_id, 'decision': 'skip', 'reason': 'insufficient_explicit_facts'}
