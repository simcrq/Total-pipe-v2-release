"""Deck-wide scientific style and source-bound annotations, without content edits."""
import math
import re


DESIGN_TOKENS = {
    'style': ('research-seminar',),
    'title_treatment': ('plain', 'thin-rule'),
    'density': ('balanced', 'compact'),
    'figure_treatment': ('unframed', 'ruled-caption'),
    'decoration_policy': ('minimal', 'none'),
    'header_variant': ('standard', 'compact'),
    'type_scale': ('standard', 'compact'),
}
DESIGN_REQUIRED = {'style', 'title_treatment', 'density', 'figure_treatment', 'decoration_policy'}
COMPOSITIONS = {
    'measurement-evidence': ('figure-left', 'figure-right', 'figure-top'),
    'mechanism-explanation': ('graphic-left', 'graphic-right', 'graphic-top'),
    'evidence-comparison': ('evidence-columns', 'evidence-rows'),
}


def object_errors(value, allowed, required, path):
    if not isinstance(value, dict):
        return [f'{path} must be an object']
    return ([f'{path}: unknown fields {sorted(set(value)-set(allowed))}'] if set(value)-set(allowed) else []) + (
        [f'{path}: missing fields {sorted(set(required)-set(value))}'] if set(required)-set(value) else [])


def validate_design(design):
    errors = object_errors(design, {*DESIGN_TOKENS, 'accent_color'}, DESIGN_REQUIRED, 'academic_design')
    if not isinstance(design, dict):
        return errors
    for key, choices in DESIGN_TOKENS.items():
        if key in design and design[key] not in choices:
            errors.append(f'academic_design.{key} must be one of {choices}')
    if 'accent_color' in design and (not isinstance(design['accent_color'], str)
            or not re.fullmatch(r'#[0-9A-Fa-f]{6}', design['accent_color'])):
        errors.append('academic_design.accent_color requires #RRGGBB')
    if design.get('decoration_policy') == 'none' and (
            design.get('title_treatment') == 'thin-rule' or design.get('figure_treatment') == 'ruled-caption'):
        errors.append('decoration_policy=none requires plain titles and unframed figures')
    return errors


def source_text(slide, source):
    """Resolve only visible canonical text; never evaluate a planner-supplied expression."""
    if source in ('semantic.title', 'semantic.takeaway'):
        return slide.get('semantic', {}).get(source.split('.')[1])
    comp = slide.get('composition', {})
    if isinstance(source, str) and source.startswith('composition.blocks.') and source.endswith('.text'):
        block_id = source[len('composition.blocks.'):-len('.text')]
        return next((b.get('text') for b in comp.get('blocks', [])
                     if isinstance(b, dict) and b.get('id') == block_id), None)
    # Node text is useful on a mechanism-only page. Composite internals stay with v5.
    if isinstance(source, str) and source.startswith('composition.graphics.'):
        for graphic in comp.get('graphics', []):
            if not isinstance(graphic, dict):
                continue
            for node in graphic.get('nodes', []):
                if not isinstance(node, dict):
                    continue
                for field in ('title', 'body'):
                    if source == f"composition.graphics.{graphic.get('id')}.nodes.{node.get('id')}.{field}":
                        return node.get(field)
    return None


def validate_plan(plan, slide):
    allowed = {'visual_job', 'primary', 'composition', 'figure_width_ratio', 'graphic_width_ratio',
               'evidence_order', 'context_placement', 'emphasis'}
    errors = object_errors(plan, allowed, {'visual_job', 'primary', 'composition'}, 'visual_plan')
    if not isinstance(plan, dict):
        return errors
    job = plan.get('visual_job')
    if not isinstance(job, str) or job not in COMPOSITIONS:
        errors.append('visual_plan.visual_job is not supported')
    elif plan.get('composition') not in COMPOSITIONS[job]:
        errors.append(f'visual_plan.composition must be one of {COMPOSITIONS[job]}')
    primary = plan.get('primary')
    errors += object_errors(primary, {'kind', 'index'}, {'kind', 'index'}, 'visual_plan.primary')
    comp = slide.get('composition', {})
    if comp.get('layout_tree'):
        errors.append('layout_tree already defines the body composition; choose deck academic_design only')
    figures, graphics = comp.get('figure_refs', []), comp.get('graphics', [])
    if isinstance(primary, dict):
        kind, index = primary.get('kind'), primary.get('index')
        expected = 'graphic' if job == 'mechanism-explanation' else 'figure'
        if kind != expected:
            errors.append(f'{job} requires primary.kind={expected}')
        targets = graphics if kind == 'graphic' else figures
        if type(index) is not int or not 0 <= index < len(targets):
            errors.append('visual_plan.primary.index must reference an existing visual (zero based)')
    for key in ('figure_width_ratio', 'graphic_width_ratio'):
        if key not in plan:
            continue
        value = plan[key]
        low, high = (.35, .75) if key == 'figure_width_ratio' else (.4, 1.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            errors.append(f'visual_plan.{key} requires a finite number in [{low}, {high}]')
    if job == 'measurement-evidence' and (len(figures) != 1 or graphics):
        errors.append('measurement-evidence requires exactly one source figure and no graphics')
    if job == 'mechanism-explanation':
        def has_mechanism(graphic):
            return isinstance(graphic, dict) and (graphic.get('type') == 'mechanism' or (
                graphic.get('type') == 'composite' and any(has_mechanism(c) for c in graphic.get('components', []))))
        if len(graphics) != 1 or not has_mechanism(graphics[0]):
            errors.append('mechanism-explanation requires an existing v5 mechanism or composite containing one')
    if job == 'evidence-comparison' and (len(figures) != 2 or graphics):
        errors.append('evidence-comparison requires exactly two source figures and no graphics')
    if 'figure_width_ratio' in plan and (job == 'mechanism-explanation' or (
            job == 'evidence-comparison' and plan.get('composition') == 'evidence-rows')):
        errors.append('figure_width_ratio applies to measurement or comparison columns')
    if 'graphic_width_ratio' in plan and job != 'mechanism-explanation':
        errors.append('graphic_width_ratio applies only to mechanism-explanation')
    if 'context_placement' in plan:
        if plan['context_placement'] not in ('above-visuals', 'with-evidence') or job != 'mechanism-explanation':
            errors.append('context_placement applies only to mechanisms: above-visuals or with-evidence')
        elif plan.get('composition') == 'graphic-top':
            errors.append('context_placement applies to graphic-left/right; graphic-top fixes the vertical reading order')
        elif not figures and plan['context_placement'] == 'with-evidence':
            errors.append('with-evidence requires a source figure')
        elif not figures:
            errors.append('context_placement requires a source figure; figure-free mechanisms use their composition')
    if 'evidence_order' in plan:
        order = plan['evidence_order']
        if (job != 'evidence-comparison' or not isinstance(order, list) or len(order) != 2
                or any(type(i) is not int for i in order) or sorted(order) != [0, 1]):
            errors.append('evidence_order must be a permutation of [0, 1] on a comparison page')
        elif isinstance(primary, dict) and order[0] != primary.get('index'):
            errors.append('evidence_order must start with the primary figure')
    if comp.get('visual_intent'):
        errors.append('visual_plan cannot rearrange a hard composition.visual_intent process group')
    if 'emphasis' in plan:
        emphasis = plan['emphasis']
        errors += object_errors(emphasis, {'source', 'text', 'treatment'}, {'source', 'text', 'treatment'}, 'visual_plan.emphasis')
        if isinstance(emphasis, dict):
            original = source_text(slide, emphasis.get('source'))
            text = emphasis.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 80 or not isinstance(original, str) or text not in original:
                errors.append('emphasis.text must occur exactly in the referenced canonical text (1-80 characters)')
            if emphasis.get('treatment') != 'inline-callout':
                errors.append('emphasis.treatment must be inline-callout')
    # These objects would otherwise promise per-page styling that the compiler does not implement.
    for key in ('theme_tokens', 'component_variants'):
        if slide.get('presentation', {}).get(key):
            errors.append(f'V6 does not accept per-slide {key}; use deck academic_design tokens')
    return errors


def resolve_design(ir):
    design = (ir.get('presentation') or {}).get('academic_design')
    if design is None:
        return None
    return {'header_variant': 'compact', 'type_scale': 'standard', **design,
            'accent_color': design.get('accent_color', ir['theme'].get('accent', '#C2410C'))}


def preserve_scientific_terms(ir):
    presentation = ir.get('presentation') or {}
    if not isinstance(presentation, dict):
        return False
    return presentation.get('text_capacity_policy',
                            'preserve-terms' if 'academic_design' in presentation else 'strict') == 'preserve-terms'


def type_sizes(design):
    return ({'title': 40, 'takeaway': 26, 'body': 26, 'heading': 26, 'caption': 20}
            if design['type_scale'] == 'compact' else
            {'title': 44, 'takeaway': 28, 'body': 28, 'heading': 28, 'caption': 22})


def header_layout(design, slide=None, fonts=None, preserve_terms=False):
    compact = design['header_variant'] == 'compact'
    header = {'title': [56, 24, 1168, 64 if compact else 112],
            'takeaway': [56, 100 if compact else 148, 1168, 70],
            'body_top': 190 if compact else 240,
            'rule': [56, 92 if compact else 140, 1168, 2]}
    if preserve_terms and slide and fonts:
        from .fonts import load_font_file
        from .layout import break_lines
        title_lines = len(break_lines(slide['semantic']['title'], load_font_file(fonts['bold_font_file'], 36), 1168))
        takeaway_lines = len(break_lines(slide['semantic']['takeaway'], load_font_file(fonts['font_file'], 24), 1168))
        title_extra = max(0, title_lines*45-header['title'][3])
        takeaway_extra = max(0, takeaway_lines*30-header['takeaway'][3])
        header['title'][3] += title_extra
        header['rule'][1] += title_extra
        header['takeaway'][1] += title_extra
        header['takeaway'][3] += takeaway_extra
        header['body_top'] += title_extra+takeaway_extra
        header['title_lines'] = max(2, title_lines)
        header['takeaway_lines'] = max(2, takeaway_lines)
    return header


def rule(element_id, box, design):
    """A native separator with no collision exemption or full-page container."""
    return {'id': element_id, 'kind': 'shape', 'role': 'decoration', 'bbox': box,
            'geometry': 'rect', 'fill': design['accent_color'], 'line': 'none', 'line_width': 0,
            'visual_decoration': True}


def header_decoration(design, header=None):
    if design and design['title_treatment'] == 'thin-rule':
        return [rule('visual:title-rule', (header or header_layout(design))['rule'], design)]
    return []
