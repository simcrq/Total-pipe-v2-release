"""Approved audience copy, scientific records and explicit content destinations (page design 1.2)."""
import copy
import re

try:
    from pwf2rpa.content_contract import catalog, validate_contract
except ModuleNotFoundError as error:
    if error.name not in ('pwf2rpa', 'pwf2rpa.content_contract'):
        raise
    # Standalone compiler from Total-pipe/ sees the outer namespace package.
    from pwf2rpa.pwf2rpa.content_contract import catalog, validate_contract

ROLES = ('title', 'takeaway', 'body', 'label', 'caption')
CARRIERS = ('copy', 'figure', 'formula', 'table', 'chart', 'graphic')


def normalized(text):
    text = str(text).replace('**', '').replace('==', '').replace('−', '-')
    text = re.sub(r'\^\{([-+]?\d+)\}', r'^\1', text)
    for old, new in (('$', ''), (r'\(', ''), (r'\)', ''), (r'\times', '×')):
        text = text.replace(old, new)
    return re.sub(r'(?<=\d)[xX]10\^', '×10^', re.sub(r'\s+', '', text))


def page_sources(page, source_catalog):
    """Ownership is unique; a scoped qualifier may be displayed again beside another claim."""
    owned = set(page.get('content_refs', []))
    routes = page.get('content_map', {})
    visible = {ref for ref, route in routes.items() if isinstance(route, dict) and route.get('destination') == 'visible'}
    reuse = page.get('reuse_refs', [])
    needed = owned | {r for r in reuse if isinstance(r, str)} if isinstance(reuse, list) else owned
    for ref, item in source_catalog.items():
        policy = item.get('policy', {})
        if policy.get('visibility') == 'with_claim' and visible.intersection(policy.get('applies_to', [])):
            needed.add(ref)
    return needed


def validate_page(page, story, evidence, numbers):
    """Structural and traceability checks only; semantic equivalence is an explicit review."""
    problems = validate_contract(story, required=True)
    if problems:
        return problems
    sources = catalog(story)
    atomic = (story.get('content_contract') or {}).get('version') == '2.0'
    copies, routes = page.get('display_copy'), page.get('content_map')
    if not isinstance(copies, list) or not copies or not isinstance(routes, dict):
        return ['1.2 requires non-empty display_copy and a content_map object']
    from .provenance import KINDS as SUPPLEMENT_KINDS, CONSTRUCTED_MARKERS
    by_id, visible_text = {}, []
    display_text = ' '.join(item.get('text', '') for item in copies if isinstance(item, dict) and isinstance(item.get('text'), str)).casefold()
    allowed = page_sources(page, sources).intersection(sources)
    reused = page.get('reuse_refs', [])
    if not isinstance(reused, list) or any(not isinstance(r, str) or r not in sources for r in reused):
        return problems+['reuse_refs must contain known scientific unit IDs']
    if not atomic and reused:
        problems.append('reuse_refs requires atomic content_contract 2.0')
    for ref in reused:
        if ref in page.get('content_refs', []) or sources[ref]['policy']['visibility'] != 'required':
            problems.append(f'{ref}: reuse must name a required assertion owned by another page')
        if routes.get(ref, {}).get('destination') != 'visible':
            problems.append(f'{ref}: a reused assertion must actually be visible')
    figure_sources = page.get('figure_sources', {})
    if atomic:
        if not isinstance(figure_sources, dict) or set(figure_sources) != set(page.get('figures', [])):
            problems.append('figure_sources must identify every selected inspected figure exactly once')
            figure_sources = {}
        for ref, meta in figure_sources.items():
            if (not isinstance(meta, dict) or set(meta) != {'source_figure'} or
                    not isinstance(meta['source_figure'], str) or not re.fullmatch(r'S?[1-9][0-9]*[a-z]?', meta['source_figure'])):
                problems.append(f'{ref}: inspected figure needs an exact source_figure identity')
    if set(routes) != allowed:
        problems.append(f'content_map must route owned items and active scoped qualifiers; '
                        f'missing={sorted(allowed-set(routes))}, unexpected={sorted(set(routes)-allowed)}')
    for item in copies:
        if (not isinstance(item, dict) or set(item)-{'id', 'role', 'text', 'source_refs', 'basis', 'supplement'} or
                not isinstance(item.get('id'), str) or not item['id'].strip() or item['id'] in by_id or
                item.get('role') not in ROLES or not isinstance(item.get('text'), str) or not item['text'].strip()):
            problems.append('display_copy items require unique id, role and non-empty text')
            continue
        by_id[item['id']] = item
        visible_text.append(item['text'])
        refs, basis = item.get('source_refs', []), item.get('basis', 'paper')
        if (not isinstance(refs, list) or not all(isinstance(ref, str) and ref in allowed for ref in refs)
                or len(set(refs)) != len(refs)):
            problems.append(f'{item["id"]}: source_refs must name owned content or active scoped qualifiers')
            continue
        if basis == 'paper':
            if not refs or 'supplement' in item:
                problems.append(f'{item["id"]}: paper copy needs source_refs and cannot carry supplement metadata')
            cited = ' '.join(evidence.get(ev, '') for ref in refs for ev in sources[ref]['evidence'])
            if atomic:
                from .scientific_numbers import numbers as science_numbers, unknown_references
                selected = [m['source_figure'] for m in figure_sources.values() if isinstance(m, dict) and 'source_figure' in m]
                context = cited+' '+' '.join(sources[ref]['text'] for ref in refs)
                for ref in unknown_references(item['text'], context, selected):
                    problems.append(f'{item["id"]}: reference {ref} has no cited or inspected source')
                context += ' '+' '.join('Fig. '+identity for identity in selected)
                missing = science_numbers(item['text'], context)-science_numbers(cited, context)
            else:
                missing = numbers(item['text'])-numbers(cited)
            for number in missing:
                problems.append(f'{item["id"]}: number {number} is not in the cited evidence')
        elif basis == 'organization':
            if refs or 'supplement' in item or numbers(item['text']):
                problems.append(f'{item["id"]}: organizational copy cannot carry paper refs, scientific numbers or supplement metadata')
        elif basis == 'supplement':
            meta = item.get('supplement')
            if refs or not isinstance(meta, dict) or not isinstance(meta.get('source'), str) or not meta['source'].strip():
                problems.append(f'{item["id"]}: supplementary copy needs its source and no paper source_refs')
            else:
                # Detailed supplement shape/leak checks run on the bound IR through existing gates.
                if (set(meta)-{'kind', 'source', 'constructed', 'assumptions'} or
                        type(meta.get('constructed')) is not bool or meta.get('kind') not in SUPPLEMENT_KINDS):
                    problems.append(f'{item["id"]}: supplementary copy needs kind and constructed boolean')
                if meta.get('constructed') and not any(marker.casefold() in display_text for marker in CONSTRUCTED_MARKERS):
                    problems.append(f'{item["id"]}: a constructed example needs a visible label')
                if 'assumptions' in meta and (not isinstance(meta['assumptions'], list) or
                        not all(isinstance(v, str) and v.strip() for v in meta['assumptions'])):
                    problems.append(f'{item["id"]}: assumptions must be non-empty strings')
        else:
            problems.append(f'{item["id"]}: unknown copy basis')
    for role in ('title', 'takeaway'):
        if sum(item.get('role') == role for item in copies if isinstance(item, dict)) != 1:
            problems.append(f'display_copy needs exactly one {role}')
    for ref, route in routes.items():
        if (ref not in sources or not isinstance(route, dict) or
                set(route)-{'destination', 'carriers', 'reason'} or route.get('destination') not in ('visible', 'notes')):
            problems.append(f'{ref}: invalid content route')
            continue
        policy = sources[ref].get('policy', {})
        active = policy.get('visibility') == 'with_claim' and any(
            routes.get(target, {}).get('destination') == 'visible' for target in policy.get('applies_to', []))
        if route['destination'] == 'notes':
            if policy.get('visibility') == 'required' or active:
                problems.append(f'{ref}: required content or a qualifier of a visible claim cannot be notes-only')
            if route.get('carriers') or not isinstance(route.get('reason'), str) or not route['reason'].strip():
                problems.append(f'{ref}: notes destination needs a reason and no visible carriers')
            continue
        carriers = route.get('carriers')
        if not isinstance(carriers, list) or not carriers:
            problems.append(f'{ref}: visible content needs at least one carrier')
            continue
        for carrier in carriers:
            if (not isinstance(carrier, dict) or set(carrier)-{'kind', 'ref', 'locator'} or
                    carrier.get('kind') not in CARRIERS or not isinstance(carrier.get('ref'), str) or not carrier['ref'].strip()):
                problems.append(f'{ref}: invalid carrier')
                continue
            if carrier['kind'] == 'copy':
                item = by_id.get(carrier['ref'], {})
                if ref not in item.get('source_refs', []):
                    problems.append(f'{ref}: copy carrier must cite this scientific source')
            elif not isinstance(carrier.get('locator'), str) or not carrier['locator'].strip():
                problems.append(f'{ref}: visual carrier needs a concrete locator for semantic review')
            elif carrier['kind'] == 'figure' and carrier['ref'] not in page.get('figures', []):
                problems.append(f'{ref}: figure carrier must be a selected inspected figure')
    for item in by_id.values():
        for ref in item.get('source_refs', []):
            route = routes.get(ref, {})
            if route.get('destination') != 'visible':
                problems.append(f'{item["id"]}: copy cannot display a source routed only to notes')
    return problems


def snapshot(page, source_catalog, review):
    needed = page_sources(page, source_catalog)
    result = {'version': '1.0', 'items': {ref: copy.deepcopy(source_catalog[ref]) for ref in sorted(needed)},
            'display_copy': copy.deepcopy(page['display_copy']), 'content_map': copy.deepcopy(page['content_map']),
            'review': copy.deepcopy(review)}
    if 'reuse_refs' in page or 'figure_sources' in page:
        result.update(version='2.0', figure_sources=copy.deepcopy(page.get('figure_sources', {})))
    return result


def bind_copy(value, page):
    """Authoring shorthand {copy_ref: id} is resolved before canonical Schema validation."""
    copies = {item['id']: item['text'] for item in page['display_copy']}
    def visit(node):
        if isinstance(node, dict):
            if set(node) == {'copy_ref'}:
                if node['copy_ref'] not in copies:
                    raise ValueError(f'Unknown approved copy_ref {node["copy_ref"]}')
                return copies[node['copy_ref']]
            return {key: visit(item) for key, item in node.items()}
        if isinstance(node, list):
            return [visit(item) for item in node]
        return node
    return visit(value)


def visible_slots(slide):
    """Narrative strings destined for actual page objects, never notes or explanation metadata."""
    from .audience import visible_caveats
    from .graphic_layout import graphic_texts
    sem, comp = slide.get('semantic', {}), slide.get('composition', {})
    slots = [('title', sem.get('title', '')), ('takeaway', sem.get('takeaway', ''))]
    slots += [('body', text) for text in visible_caveats(slide)]
    for block in comp.get('blocks', []):
        if not isinstance(block, dict): continue
        if block.get('component') != 'formula':
            slots.append(('caption' if block.get('component') == 'caption' else 'body', block.get('text', '')))
        if block.get('label'):
            slots.append(('label', block['label']))
    slots += [('caption', figure.get('caption', '')) for figure in comp.get('figure_refs', [])]
    for graphic in comp.get('graphics', []):
        slots += [('graphic', text) for _, text in graphic_texts(graphic)]
    # Native table data/formulas and chart ticks/values are visual evidence, not narrative prose.
    for chart in comp.get('charts', []):
        for axis in ('x', 'y'):
            slots.append(('label', chart.get(axis, {}).get('label', '')))
        slots += [('label', item.get('label', '')) for item in chart.get('series', [])]
        slots += [('label', item.get('text', '')) for item in chart.get('annotations', [])]
    def panel_titles(node):
        if isinstance(node, dict):
            if isinstance(node.get('title'), str): slots.append(('label', node['title']))
            for value in node.values(): panel_titles(value)
        elif isinstance(node, list):
            for value in node: panel_titles(value)
    panel_titles(comp.get('layout_tree', {}))
    return [(role, text) for role, text in slots if isinstance(text, str) and text.strip()]


def validate_ir(slide, assets, rendered=None):
    """Check records separately from approved visible copy, optionally against compiled objects."""
    projection = slide.get('semantic', {}).get('content_projection')
    if projection is None:
        return []
    errors = []
    def fail(message): errors.append(('CONTENT_PROJECTION_FAILED', 'FAIL', message))
    expected = {'version', 'items', 'display_copy', 'content_map', 'review'}
    if isinstance(projection, dict) and projection.get('version') == '2.0': expected.add('figure_sources')
    if (not isinstance(projection, dict) or set(projection) != expected or
            projection.get('version') not in ('1.0', '2.0') or not isinstance(projection.get('items'), dict) or
            not isinstance(projection.get('display_copy'), list) or not isinstance(projection.get('content_map'), dict)):
        fail('content_projection requires version, items, display_copy, content_map and review')
        return errors
    items, copies, routes = projection['items'], projection['display_copy'], projection['content_map']
    if (not copies or any(not isinstance(item, dict) or item.get('role') not in ROLES or
                         not isinstance(item.get('text'), str) or not isinstance(item.get('id'), str) for item in copies)):
        fail('content_projection contains malformed approved copy')
        return errors
    if len({item['id'] for item in copies}) != len(copies):
        fail('content_projection has duplicate copy IDs')
    if set(items) != set(routes):
        fail('Every scientific record needs an explicit destination')
    for ref, item in items.items():
        if (not isinstance(item, dict) or not isinstance(item.get('text'), str) or
                not isinstance(item.get('policy'), dict) or not isinstance(item.get('evidence'), list)):
            fail(f'{ref}: malformed scientific record')
            continue
        if projection['version'] == '2.0' and item.get('epistemic') not in (
                'author_claim', 'observation', 'author_interpretation', 'agent_inference'):
            fail(f'{ref}: atomic scientific record lost its epistemic identity')
        policy = item['policy']
        if policy.get('visibility') not in ('required', 'with_claim', 'notes_allowed') or not isinstance(policy.get('applies_to', []), list):
            fail(f'{ref}: malformed visibility policy')
    for ref, route in routes.items():
        if (not isinstance(route, dict) or route.get('destination') not in ('visible', 'notes') or
                not isinstance(route.get('carriers', []), list) or
                any(not isinstance(c, dict) or c.get('kind') not in CARRIERS or not isinstance(c.get('ref'), str)
                    for c in route.get('carriers', []))):
            fail(f'{ref}: malformed content route')
    for item in copies:
        if not isinstance(item.get('source_refs'), list) or any(ref not in items for ref in item['source_refs']):
            fail(f'{item["id"]}: invalid copy source refs')
    review = projection['review']
    if (not isinstance(review, dict) or review.get('method') != 'agent-source-review' or
            any(not isinstance(review.get(key), str) or not re.fullmatch('[a-f0-9]{64}', review[key])
                for key in ('story_sha256', 'design_sha256', 'review_sha256'))):
        fail('content_projection needs the source/copy review binding')
    if projection['version'] == '2.0' and (not isinstance(review, dict) or any(
            not isinstance(review.get(key), str) or not re.fullmatch('[a-f0-9]{64}', review[key])
            for key in ('scientific_review_sha256', 'workflow_sha256'))):
        fail('Atomic projection needs the actual pre-design scientific source review binding')
    if errors:
        return errors
    corpus = normalized(slide.get('semantic', {}).get('speaker_notes', ''))
    for ref, item in items.items():
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not isinstance(item.get('policy'), dict):
            fail(f'{ref}: scientific record/policy missing')
            continue
        if normalized(item['text']) not in corpus:
            fail(f'{ref}: complete scientific record is missing from speaker notes')
        if projection['version'] == '2.0' and normalized(ref+' ['+str(item.get('epistemic'))+']: '+item['text']) not in corpus:
            fail(f'{ref}: scientific record and epistemic identity must be archived together in notes')
        route = routes.get(ref, {})
        if not isinstance(route, dict):
            fail(f'{ref}: invalid route')
            continue
        policy = item['policy']
        active = any(routes.get(target, {}).get('destination') == 'visible' for target in policy.get('applies_to', []))
        if (policy.get('visibility') == 'required' or active) and route.get('destination') != 'visible':
            fail(f'{ref}: required content/active qualifier must remain visible')
    slots = visible_slots(slide)
    by_text = {normalized(item['text']): item for item in copies}
    for block in slide.get('composition', {}).get('blocks', []):
        approved = by_text.get(normalized(block.get('text', '')))
        if approved and approved.get('basis') == 'supplement':
            if block.get('basis') != 'supplement' or block.get('supplement') != approved.get('supplement') or block.get('evidence_refs'):
                fail(f'{approved["id"]}: supplementary copy lost its source/basis')
        elif approved and block.get('basis') == 'supplement':
            fail(f'{approved["id"]}: paper/organizational copy cannot change to supplement basis')
    for role, text in slots:
        accepted_roles = ('body', 'label') if role == 'graphic' else (role,)
        candidates = [normalized(item['text']) for item in copies if item['role'] in accepted_roles]
        # An explicit native list may carry one approved sentence per paragraph.
        parts = [normalized(part) for part in text.split('\n') if part.strip()]
        if normalized(text) not in candidates and not (role == 'body' and parts and all(p in candidates for p in parts)):
            fail(f'Unapproved {role} copy: {text[:100]}')
    raw_visible = [normalized(text) for _, text in slots]
    rendered_text = [normalized(e.get('source_text', e.get('text', ''))) for e in (rendered or {}).get('elements', [])
                     if e.get('kind') in ('text', 'list', 'math')]
    for item in copies:
        needle = normalized(item['text'])
        if not any(needle in text for text in raw_visible):
            fail(f'Approved copy {item["id"]} has no visible IR object; notes do not count')
        if rendered is not None and not any(needle in text for text in rendered_text):
            fail(f'Approved copy {item["id"]} is absent from compiled page objects')
    by_id = {item['id']: item for item in copies}
    comp = slide.get('composition', {})
    if projection['version'] == '2.0':
        manifest = projection['figure_sources']
        if not isinstance(manifest, dict):
            fail('Atomic projection requires the inspected figure source manifest')
        else:
            for source in manifest:
                if not any(f.get('asset_id') == source or assets.get(f.get('asset_id'), {}).get('path') == source
                           for f in comp.get('figure_refs', [])):
                    fail(f'{source}: inspected figure from the approved manifest is missing')
            for figure in comp.get('figure_refs', []):
                aid = figure.get('asset_id')
                meta = manifest.get(aid) or manifest.get(assets.get(aid, {}).get('path'))
                expected_id = meta.get('source_figure') if isinstance(meta, dict) else None
                from .scientific_numbers import figure_source_label
                label = figure_source_label(expected_id, figure.get('caption', '')) if expected_id else None
                if not expected_id or figure.get('source_figure') != expected_id or figure.get('source_label') != label:
                    fail(f'{aid}: figure provenance must match the inspected source identity and visible source label')
    for ref, route in routes.items():
        if not isinstance(route, dict) or route.get('destination') != 'visible':
            continue
        if not route.get('carriers'):
            fail(f'{ref}: no visible carrier')
        for carrier in route.get('carriers', []):
            kind, target = carrier.get('kind'), carrier.get('ref')
            if kind == 'copy':
                if target not in by_id or ref not in by_id[target].get('source_refs', []):
                    fail(f'{ref}: unbound approved copy carrier')
            elif kind == 'figure':
                def origin_matches(figure):
                    asset = assets.get(figure.get('asset_id'), {})
                    if figure.get('asset_id') == target or asset.get('path') == target: return True
                    if 'crop' in asset:
                        from .crops import verified_source
                        try: return verified_source(asset) == target
                        except (OSError, ValueError, TypeError): return False
                    return False
                selected = [f for f in comp.get('figure_refs', []) if f.get('asset_id') == target or
                            origin_matches(f)]
                if not selected:
                    fail(f'{ref}: selected figure carrier is missing')
                elif rendered is not None and not any(e.get('kind') == 'image' and
                        any(e.get('asset_id') == f.get('asset_id') for f in selected) for e in rendered.get('elements', [])):
                    fail(f'{ref}: figure carrier is not in compiled page objects')
            else:
                pool = comp.get({'formula': 'blocks', 'table': 'tables', 'chart': 'charts', 'graphic': 'graphics'}.get(kind, ''), [])
                found = next((obj for obj in pool if obj.get('id') == target), None)
                if not found or (kind == 'formula' and found.get('component') != 'formula'):
                    fail(f'{ref}: {kind} carrier {target} is missing')
                elif rendered is not None:
                    prefix = {'graphic': 'graphic:', 'chart': 'chart:', 'table': 'table:'}.get(kind, '')+str(target)
                    if not any(e.get('id') == target or str(e.get('id', '')).startswith(prefix+':')
                               or e.get('id') == prefix for e in rendered.get('elements', [])):
                        fail(f'{ref}: {kind} carrier {target} is absent from compiled page objects')
            if kind != 'copy':
                errors.append(('CONTENT_VISUAL_SEMANTICS_REVIEW', 'REVIEW',
                               f'{ref}: inspect {kind} {target}: {carrier.get("locator", "")}'))
    return errors
