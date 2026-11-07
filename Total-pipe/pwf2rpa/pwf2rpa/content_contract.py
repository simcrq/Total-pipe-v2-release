"""Scientific records and their visibility policies; independent of any slide renderer."""
import copy
import re

KINDS = ('claim', 'condition', 'uncertainty', 'control', 'negative_result', 'interpretation', 'scope', 'detail')
VISIBILITY = ('required', 'with_claim', 'notes_allowed')
EPISTEMIC = ('author_claim', 'observation', 'author_interpretation', 'agent_inference')


def records(story):
    result = {}
    nodes = story.get('story', [])
    nodes = nodes if isinstance(nodes, list) else []
    all_evidence = list(dict.fromkeys(ref for node in nodes if isinstance(node, dict)
                                    for ref in (node.get('evidence') if isinstance(node.get('evidence'), list) else []) if isinstance(ref, str)))
    for i, node in enumerate(nodes, 1):
        if not isinstance(node, dict):
            continue
        values = {f'S{i}.answer': node.get('answer', '')}
        points = node.get('key_points', [])
        values.update({f'S{i}.key_points[{j}]': text for j, text in enumerate(points if isinstance(points, list) else [])})
        result.update({ref: {'source': ref, 'text': text, 'evidence': list(node.get('evidence') or [])}
                       for ref, text in values.items()})
    for field in ('takeaway', 'limitation'):
        ending = story.get('ending', {})
        text = ending.get(field) if isinstance(ending, dict) else None
        if text:
            ref = 'ending.'+field
            result[ref] = {'source': ref, 'text': text, 'evidence': all_evidence}
    return result


def _validate_legacy(story, required=False):
    """Validate explicit policies, never guess importance from words such as 'not reported'."""
    contract = story.get('content_contract')
    if contract is None:
        return ['content_contract 1.0 is required for the new audience projection contract'] if required else []
    if (not isinstance(contract, dict) or set(contract) != {'version', 'items'} or
            contract.get('version') != '1.0' or not isinstance(contract.get('items'), dict)):
        return ['content_contract requires version=1.0 and an items map']
    catalog, policies, problems = records(story), contract['items'], []
    if set(policies) != set(catalog):
        problems.append('content_contract.items must classify every Story content path exactly once; '
                        f'missing={sorted(set(catalog)-set(policies))}, unknown={sorted(set(policies)-set(catalog))}')
    for ref, policy in policies.items():
        if (not isinstance(policy, dict) or set(policy)-{'kind', 'visibility', 'applies_to', 'reason'} or
                policy.get('kind') not in KINDS or policy.get('visibility') not in VISIBILITY):
            problems.append(f'{ref}: invalid kind/visibility policy')
            continue
        applies = policy.get('applies_to', [])
        if (not isinstance(applies, list) or not all(isinstance(v, str) and v in catalog and v != ref for v in applies)
                or len(set(applies)) != len(applies)):
            problems.append(f'{ref}: applies_to must name unique other Story paths')
            continue
        visibility = policy['visibility']
        if visibility == 'with_claim' and not applies:
            problems.append(f'{ref}: with_claim needs applies_to')
        if visibility != 'with_claim' and applies:
            problems.append(f'{ref}: applies_to is only valid with visibility=with_claim')
        if visibility == 'notes_allowed':
            if policy['kind'] not in ('detail', 'scope'):
                problems.append(f'{ref}: {policy["kind"]} cannot be made notes-only; keep it visible or bind it to a claim')
            if not isinstance(policy.get('reason'), str) or not policy['reason'].strip():
                problems.append(f'{ref}: notes_allowed needs a scientific relevance reason')
        if policy['kind'] == 'claim' and visibility != 'required':
            problems.append(f'{ref}: a core claim must be required on the page')
        if (ref.endswith('.answer') or ref == 'ending.takeaway') and (policy['kind'], visibility) != ('claim', 'required'):
            problems.append(f'{ref}: Story answers and the ending takeaway are required claims')
        if ref == 'ending.limitation' and visibility != 'required':
            problems.append(f'{ref}: the ending scientific limitation must be visible')
    return problems


def _legacy_catalog(story):
    result = records(story)
    for ref, policy in (story.get('content_contract') or {}).get('items', {}).items():
        if ref in result:
            result[ref]['policy'] = copy.deepcopy(policy)
    return result


def version(story):
    value = story.get('content_contract')
    return value.get('version') if isinstance(value, dict) else None


def _validate_atomic(story):
    """Units are scientific assertions; narrative paths merely group them for explanation.

    A qualifier can target a required assertion, never another qualifier or a paragraph.
    Semantic atomicity/completeness is deliberately still reviewed against original sources.
    """
    contract = story['content_contract']
    if set(contract) != {'version', 'units', 'narrative_map'} or not isinstance(contract.get('units'), dict):
        return ['content_contract 2.0 requires units and narrative_map, not paragraph policies']
    units, narrative = contract['units'], contract.get('narrative_map')
    paths = records(story)
    errors = []
    if not units:
        errors.append('content_contract.units must contain scientific units')
    if not isinstance(narrative, dict) or set(narrative) != set(paths):
        return errors+['narrative_map must map every answer/key_point/ending path, with no unknown paths']
    used = set()
    for path, refs in narrative.items():
        if (not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in units for r in refs)
                or len(set(refs)) != len(refs)):
            errors.append(f'{path}: narrative_map needs unique known unit IDs')
            continue
        used.update(refs)
        inherited = set(paths[path]['evidence'])
        for ref in refs:
            item = units[ref]
            if isinstance(item, dict) and isinstance(item.get('evidence'), list) and not set(item['evidence']) <= inherited:
                errors.append(f'{path}: unit {ref} evidence must also be cited by this narrative node')
    for ref, item in units.items():
        if not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', ref):
            errors.append('Scientific unit IDs must be stable identifiers, not Story paragraph paths')
        if (not isinstance(item, dict) or set(item)-{'text', 'evidence', 'kind', 'visibility', 'applies_to', 'reason', 'epistemic'}
                or not isinstance(item.get('text'), str) or not item['text'].strip()
                or not isinstance(item.get('evidence'), list) or not item['evidence']
                or any(not isinstance(ev, str) or not re.fullmatch(r'EV\d{4}', ev) for ev in item['evidence'])
                or len(set(item['evidence'])) != len(item['evidence'])
                or item.get('kind') not in KINDS or item.get('visibility') not in VISIBILITY or item.get('epistemic') not in EPISTEMIC):
            errors.append(f'{ref}: unit needs text, precise evidence, epistemic identity, kind and visibility')
            continue
        if ref not in used:
            errors.append(f'{ref}: scientific unit is not linked to the narrative')
        policy = item['visibility']
        targets = item.get('applies_to', [])
        if not isinstance(targets, list) or any(not isinstance(t, str) or t not in units or t == ref for t in targets) or len(set(targets)) != len(targets):
            errors.append(f'{ref}: applies_to must name unique other scientific units')
            continue
        if policy == 'with_claim':
            if not targets:
                errors.append(f'{ref}: scoped qualifier needs concrete assertion targets')
            for target in targets:
                if not isinstance(units[target], dict) or units[target].get('visibility') != 'required':
                    errors.append(f'{ref}: qualifier target {target} must be a required assertion; qualifier cascades are forbidden')
        elif targets:
            errors.append(f'{ref}: applies_to is only valid with with_claim')
        if item['kind'] == 'claim' and policy != 'required':
            errors.append(f'{ref}: a claim must be required')
        if policy == 'notes_allowed':
            if item['kind'] not in ('detail', 'scope') or not isinstance(item.get('reason'), str) or not item['reason'].strip():
                errors.append(f'{ref}: notes_allowed requires a detail/scope and a scientific relevance reason')
    return errors


def validate_contract(story, required=False, required_version=None):
    current = version(story)
    if required_version and current != required_version:
        return [f'content_contract version {required_version} is required by this prompt; no silent legacy downgrade']
    if current == '2.0':
        return _validate_atomic(story)
    return _validate_legacy(story, required)


def catalog(story):
    if version(story) != '2.0':
        return _legacy_catalog(story)
    return {ref: {'source': ref, 'text': item['text'], 'evidence': list(item['evidence']), 'epistemic': item['epistemic'],
                  'policy': {k: copy.deepcopy(item[k]) for k in ('kind', 'visibility', 'applies_to', 'reason') if k in item}}
            for ref, item in story['content_contract']['units'].items()}
