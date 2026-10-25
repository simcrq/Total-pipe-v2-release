"""Agent prompt/validated merge boundary. No model service or PPTX writer lives here."""
import copy
import json
from pathlib import Path

from PIL import Image

from .contracts import digest, file_hash
from .ir import validate
from .visual_design import COMPOSITIONS, object_errors, validate_plan


INSTRUCTIONS = """Act as the Scientific Visual Planner for this canonical research deck.
Choose one restrained academic_design for the entire deck and visual_plan entries for selected eligible slides.
Return only the proposal shape below. Echo ir_sha256 exactly. Read the FULL deck_ir, including notes,
figures, conditions, limitations and explicit evidence/hypothesis relationships before choosing a layout.
Respect assets.origin: reference images retain reference_source and are user-provided visual material,
not independently verified paper evidence. Never invent a paper figure number or schematic caption for them.
Only these presentation decisions may change: never rewrite semantic, composition, graphics, assets,
evidence, numbers, captions or speaker notes. Do not invent relationships, crop a paper image, add a new
mechanism renderer, or copy scientific content into a second content model.
Never shorten or corrupt scientific terminology to satisfy a title/body character or layout budget.
Preserve the full correct term, its units, charge/state and qualifiers. Capacity excess may proceed as
a scientific-text REVIEW under preserve-terms policy; it is not permission to paraphrase the science.
Existing theme fonts apply deck-wide; choose type_scale, header_variant and optionally accent_color
once in academic_design.
Use only the attached schemas. Reference existing figures/graphics with zero-based primary.index.
measurement-evidence prioritizes a source figure and adjacent conditions; mechanism-explanation reuses
the existing v5 mechanism, preserving solid evidence and dashed hypothesis edges; evidence-comparison
aligns two existing source figures/captions and may set their evidence_order (primary first).
Select composition, proportions and context placement from the scientific reading sequence. Ratios
are preferences subject to measured capacity. Keep source text intact and all scientific review gates.
Any emphasis.text must occur EXACTLY in its visible canonical source: semantic.title,
semantic.takeaway, composition.blocks.<id>.text, or composition.graphics.<id>.nodes.<id>.title/body.
Use modest inline-callout annotations, thin rules or unframed figures. Avoid advertising cards,
dashboard tiles, poster-sized numbers, background textures and decoration without a reading purpose.
Use planning_targets to cover every selected eligible page; do not stop after a sample of the deck.
Omit plans for unsupported pages. For a deck with no eligible pages, return slides: [] and still choose
academic_design. Do not invent a source figure or mechanism to satisfy this stage.
Slides may carry semantic.explanation. Required obligations are hard reader requirements: choose a
composition that keeps them visible and never claim a text-only page is covered. planning_targets lists
the obligations for each page; the compiler's explanation_coverage ledger is authoritative.
Do not use per-slide colors/fonts, theme_tokens, component_variants,
page coordinates or geometry overrides. If a plan cannot fit, revise its design choices; never trim
content, weaken panel floors, split a hard group, or silently ignore VISUAL_PLAN_UNSATISFIABLE.
"""


def checked(ir):
    failures = [item for item in validate(ir) if item['severity'] == 'FAIL']
    if failures:
        raise ValueError(json.dumps(failures, ensure_ascii=False))


def _obligations(slide):
    explanation = slide.get('semantic', {}).get('explanation')
    if not isinstance(explanation, dict):
        return []
    return [{key: item.get(key) for key in ('id', 'kind', 'required', 'primary')}
            for item in explanation.get('obligations', []) if isinstance(item, dict)]


def planning_targets(ir):
    """Discover supported jobs using the same validation as the compiler, without inventing a plan."""
    targets = []
    for slide in ir['slides']:
        obligations = _obligations(slide)
        with_obligations = {'explanation_obligations': obligations} if obligations else {}
        if slide['composition'].get('layout_tree'):
            targets.append({'slide_id': slide['id'], 'visual_jobs': [], 'reason': 'body_layout_tree',
                            'layout_tree_version': slide['composition']['layout_tree']['version'],
                            **with_obligations})
            continue
        jobs = []
        for job, compositions in COMPOSITIONS.items():
            plan = {'visual_job': job, 'primary': {
                'kind': 'graphic' if job == 'mechanism-explanation' else 'figure', 'index': 0},
                'composition': compositions[0]}
            if not validate_plan(plan, {**slide, 'presentation': {}}):
                jobs.append(job)
        targets.append({'slide_id': slide['id'], 'visual_jobs': jobs,
                        **with_obligations,
                        **({'reason': 'hard_process_group' if slide['composition'].get('visual_intent')
                            else 'explanation_requires_text_structure' if obligations
                            else 'no_supported_visual_job'} if not jobs else {})})
    return targets


def pending_design(ir):
    """Public generation must make the agent's design pass explicit before rendering."""
    slides = {slide['id']: slide for slide in ir['slides']}
    missing = [target['slide_id'] for target in planning_targets(ir) if target['visual_jobs'] and
               not slides[target['slide_id']].get('presentation', {}).get('visual_plan')]
    return {'academic_design_required': not (ir.get('presentation') or {}).get('academic_design'),
            'slide_ids': missing}


def make_prompt(ir, base, requirements='', slide_ids=None):
    checked(ir)
    ids = [slide['id'] for slide in ir['slides']]
    selected = ids if slide_ids is None else slide_ids
    if (not isinstance(selected, list) or not selected or any(sid not in ids for sid in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError('Select unique existing slide ids')
    schema = json.loads((Path(__file__).resolve().parents[1]/'schemas/deck-ir.schema.json').read_text(encoding='utf-8'))
    resources = {}
    for key, asset in ir['assets'].items():
        path = (Path(base)/asset['path']).resolve()
        with Image.open(path) as image:
            resources[key] = {'path': str(path), 'width': image.width, 'height': image.height,
                              'sha256': file_hash(path), 'origin': asset.get('origin', 'paper'),
                              'source_figure': asset.get('source_figure'),
                              'reference_source': asset.get('reference_source')}
    targets = [target for target in planning_targets(ir) if target['slide_id'] in selected]
    required_ids = [target['slide_id'] for target in targets if target['visual_jobs']]
    return {'instructions': INSTRUCTIONS, 'requirements': requirements,
            'ir_sha256': digest(ir), 'deck_ir': copy.deepcopy(ir), 'available_assets': resources,
            'selected_slide_ids': selected,
            'planning_targets': targets, 'required_plan_slide_ids': required_ids,
            'schemas': {key: schema['$defs'][key] for key in ('academic-design', 'visual-plan')},
            'output_shape': {'ir_sha256': digest(ir), 'academic_design': '<academic-design object>',
                'slides': [{'slide_id': '<eligible selected slide id>', 'visual_plan': '<visual-plan object>'}]
                          if required_ids else []}}


def apply_proposal(ir, proposal):
    """Apply a source-bound, presentation-only proposal to a copy, atomically or not at all."""
    checked(ir)
    errors = object_errors(proposal, {'ir_sha256', 'academic_design', 'slides'},
                           {'ir_sha256', 'academic_design', 'slides'}, 'visual proposal')
    if not isinstance(proposal, dict):
        raise ValueError('; '.join(errors))
    if proposal.get('ir_sha256') != digest(ir):
        errors.append('VISUAL_PLAN_STALE: proposal must bind to the current full Deck IR SHA-256')
    entries = proposal.get('slides')
    if not isinstance(entries, list):
        errors.append('Proposal slides must be a list')
        entries = []
    if not entries and any(target['visual_jobs'] for target in planning_targets(ir)):
        errors.append('Proposal slides must include a visual plan when the deck has eligible pages')
    slides = {slide['id']: slide for slide in ir['slides']}
    seen = set()
    for entry in entries:
        errors += object_errors(entry, {'slide_id', 'visual_plan'}, {'slide_id', 'visual_plan'}, 'proposal slide')
        if not isinstance(entry, dict):
            continue
        sid = entry.get('slide_id')
        if not isinstance(sid, str) or sid not in slides or sid in seen:
            errors.append('Proposal must reference unique existing slide ids')
        if isinstance(sid, str):
            seen.add(sid)
    if errors:
        raise ValueError('; '.join(errors))
    merged = copy.deepcopy(ir)
    merged.setdefault('presentation', {})['academic_design'] = copy.deepcopy(proposal['academic_design'])
    by_id = {slide['id']: slide for slide in merged['slides']}
    for entry in entries:
        by_id[entry['slide_id']]['presentation']['visual_plan'] = copy.deepcopy(entry['visual_plan'])
    checked(merged)
    return merged
