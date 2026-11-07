"""Local IR repairs measured by the existing compiler before canonical state changes."""
from collections import Counter
import copy
from dataclasses import dataclass
from pathlib import Path
import re
import uuid

from . import COMPONENT
from .state import code_hash, digest, read, resources, sha
from .telemetry import span


SCHEMA = COMPONENT/'agent/schemas/deck-ir-patch.schema.json'
STAGES = ('deck_ir', 'build', 'candidate_ready')


def resource_snapshot(ir_path):
    """Bind external bytes, including resolved theme fonts rather than only font names."""
    from deck_compiler.fonts import resolve_theme_fonts
    value = read(ir_path)
    result = resources(ir_path)
    files = [p for root in ('deck_compiler', 'totalpipe_layout', 'pwf2rpa/pwf2rpa')
             for p in (COMPONENT/root).rglob('*.py')]
    files += list((COMPONENT/'schemas').rglob('*.json'))
    files += list((COMPONENT/'pwf2rpa/schemas').rglob('*.json'))
    result['@compiler'] = digest([code_hash(), {str(p.relative_to(COMPONENT)): sha(p) for p in sorted(files)}])
    # The same immutable content is used for both snapshots. Layout-only patches
    # cannot change the text sample, theme or declared fonts.
    sample = str(value.get('slides', []))
    regular, bold, _ = resolve_theme_fonts(value['theme'], ir_path.parent, sample)
    for font in (regular, bold):
        if font:
            result[str(Path(font).resolve())] = sha(font)
    return result


def descriptor(out):
    path = Path(out)/'work/deck_ir.json'
    if not path.is_file():
        return None
    return {'artifact_kind': 'deck_ir_patch', 'schema_path': str(SCHEMA),
            'expected_output': str(path.with_name('deck_ir_patch.json')),
            'base_ir_sha256': sha(path), 'base_resources_sha256': digest(resource_snapshot(path)),
            'modes': ['preflight', 'apply'], 'max_rejected_revisions': 3}


def fingerprint(patch, path):
    """Image-byte changes are new submissions even if the patch JSON is unchanged."""
    paths = {}
    if isinstance(patch, dict) and isinstance(patch.get('asset_updates', {}), dict):
        for aid, update in patch.get('asset_updates', {}).items():
            if isinstance(update, dict) and isinstance(update.get('path'), str):
                target = Path(update['path']).expanduser()
                target = target if target.is_absolute() else path.parent/target
                paths[aid] = sha(target)
    return digest({'patch': patch, 'asset_bytes': paths})


def validate_patch(patch):
    from .adapters import Failure
    def reject(message):
        raise Failure('PATCH_INVALID', message, 'author_artifact', 'deck_ir')
    fields = {'schema_version', 'mode', 'base_ir_sha256', 'base_resources_sha256',
              'asset_updates', 'slide_updates'}
    required = fields-{'asset_updates', 'slide_updates'}
    if not isinstance(patch, dict) or set(patch)-fields or not required <= set(patch):
        reject('Use the complete deck-ir-patch schema; unknown or missing fields are forbidden.')
    if patch['schema_version'] != '1.0' or patch['mode'] not in ('preflight', 'apply'):
        reject('schema_version must be 1.0 and mode must be preflight or apply.')
    if any(not isinstance(patch[key], str) or not re.fullmatch('[a-f0-9]{64}', patch[key])
           for key in ('base_ir_sha256', 'base_resources_sha256')):
        reject('Both base hashes must be the current SHA-256 values returned in repair.')
    if not patch.get('asset_updates') and not patch.get('slide_updates'):
        reject('A patch needs at least one asset or slide update.')
    if 'asset_updates' in patch:
        updates = patch['asset_updates']
        if not isinstance(updates, dict) or not updates:
            reject('asset_updates must be a non-empty object keyed by existing asset ID.')
        for aid, update in updates.items():
            if (not isinstance(aid, str) or not isinstance(update, dict) or set(update) != {'path'}
                    or not isinstance(update['path'], str) or not update['path'].strip()):
                reject('An asset update may only replace path; provenance and dimensions are not author inputs.')
    if 'slide_updates' in patch:
        updates = patch['slide_updates']
        if not isinstance(updates, list) or not 1 <= len(updates) <= 40:
            reject('slide_updates must contain 1–40 existing slides.')
        ids = set()
        for update in updates:
            if (not isinstance(update, dict) or set(update) != {'id', 'layout_tree'}
                    or not isinstance(update['id'], str) or not update['id'].strip()
                    or update['id'] in ids):
                reject('Slide updates need unique IDs and only layout_tree; scientific fields are immutable.')
            ids.add(update['id'])


def _tree_text(tree):
    """Keep visible titles attached to their node, even when containers move."""
    values = Counter()
    def visit(value, owner='root', path=''):
        if isinstance(value, dict):
            owner = value.get('id', owner)
            for key, item in value.items():
                if key in ('title', 'text', 'label', 'caption', 'latex') and isinstance(item, str):
                    values[(owner, key, item)] += 1
                elif isinstance(item, (dict, list)):
                    visit(item, owner, path+'.'+key)
        elif isinstance(value, list):
            for item in value:
                visit(item, owner, path)
    visit(tree)
    return values


def _panel_groups(tree):
    """A titled Control panel cannot quietly acquire the Treatment data."""
    groups = {}
    def leaves(node):
        if not isinstance(node, dict):
            return []
        if node.get('type') in ('block', 'figure', 'graphic', 'table', 'chart'):
            return [(node['type'], node.get('ref'))]
        if node.get('type') == 'panel':
            return leaves(node.get('body'))
        return [leaf for child in node.get('children', []) for leaf in leaves(child)]
    def visit(node):
        if not isinstance(node, dict):
            return
        if node.get('type') == 'panel':
            groups[node['id']] = Counter(leaves(node.get('body')))
            visit(node.get('body'))
        else:
            for child in node.get('children', []):
                visit(child)
    for root in (tree.get('regions') or {}).values():
        visit(root)
    return groups


def patched_ir(base, patch, patch_path):
    from PIL import Image
    from deck_compiler.layout_tree import validate_tree
    from .adapters import Failure
    value = copy.deepcopy(base)
    changed, dimensions = set(), {}
    slides = {slide['id']: slide for slide in value['slides']}
    for update in patch.get('slide_updates', []):
        if update['id'] not in slides:
            raise Failure('PATCH_INVALID', 'A layout patch cannot add or rename slides.', 'author_artifact', 'deck_ir')
        slide = slides[update['id']]
        comp, tree = slide['composition'], update['layout_tree']
        errors = validate_tree(tree, comp)
        if errors:
            raise Failure('PATCH_INVALID', ' '.join(errors[:4]), 'author_artifact', 'deck_ir')
        if _tree_text(comp.get('layout_tree', {})) != _tree_text(tree):
            raise Failure('PATCH_INVALID', 'Visible panel titles cannot change in a layout-only patch; '
                          'use full IR revision for scientific text changes.', 'author_artifact', 'deck_ir')
        if _panel_groups(comp.get('layout_tree', {})) != _panel_groups(tree):
            raise Failure('PATCH_INVALID', 'Titled panel content groups cannot change in a layout-only patch; '
                          'use full IR revision to regroup scientific content.', 'author_artifact', 'deck_ir')
        comp['layout_tree'] = copy.deepcopy(tree)
        changed.add(update['id'])
    for aid, update in patch.get('asset_updates', {}).items():
        if aid not in value['assets']:
            raise Failure('PATCH_INVALID', 'An asset patch cannot add or rename assets.', 'author_artifact', 'deck_ir')
        target = Path(update['path']).expanduser()
        target = (target if target.is_absolute() else patch_path.parent/target).resolve()
        before_bytes = sha(target)
        try:
            with Image.open(target) as image:
                image.verify()
            with Image.open(target) as image:
                dimensions[aid] = [image.width, image.height]
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            raise Failure('PATCH_INVALID', 'Asset path must name a readable raster image.',
                          'author_artifact', 'deck_ir') from error
        if sha(target) != before_bytes:
            raise Failure('PATCH_STALE', 'Replacement image changed while its dimensions were read.',
                          'author_artifact', 'deck_ir')
        value['assets'][aid]['path'] = str(target)
        for slide in value['slides']:
            if any(ref.get('asset_id') == aid for ref in slide['composition'].get('figure_refs', [])):
                changed.add(slide['id'])
    return value, [s['id'] for s in value['slides'] if s['id'] in changed], dimensions


@dataclass
class PreparedPatch:
    value: dict
    summary: dict
    base_resources: dict
    measured_resources: dict


def preflight(job, patch, path):
    out = Path(job['request']['out_dir'])
    with span(out, job_id=job['job_id'], stage='deck_ir', operation='repair_preflight'):
        return _preflight(job, patch, path)


def _preflight(job, patch, path):
    from deck_compiler.pipeline import compile_input
    from .adapters import Failure, check_ir, persist_ir, load_design
    out = Path(job['request']['out_dir'])
    base_path, work = out/'work/deck_ir.json', out/'work'
    before = resource_snapshot(base_path)
    if patch['base_ir_sha256'] != sha(base_path) or patch['base_resources_sha256'] != digest(before):
        raise Failure('PATCH_STALE', 'Canonical IR or its asset/font bytes changed; read current repair hashes.',
                      'author_artifact', 'deck_ir')
    value, changed, dimensions = patched_ir(read(base_path), patch, path)
    replacement_bytes = {value['assets'][aid]['path']: sha(value['assets'][aid]['path'])
                         for aid in patch.get('asset_updates', {})}
    check_ir(value, read(work/'normalized_content.json') if (work/'normalized_content.json').is_file() else None,
             job['request'].get('supplement', 'off'),
             design=load_design(work),
             slide_count=job['request'].get('slide_count'))
    folder = work/'repairs'/uuid.uuid4().hex
    persist_ir(value, base_path, folder/'input.json')
    _, _, qa = compile_input(folder/'input.json', folder, {'name': 'packer'},
                             enable_overflow_repair=False, require_visual_design=True, explain_viz_mode='off')
    if resource_snapshot(base_path) != before or any(sha(path) != expected for path, expected in replacement_bytes.items()):
        raise Failure('PATCH_STALE', 'Base or replacement bytes changed during preflight; nothing was applied.',
                      'author_artifact', 'deck_ir')
    # Neither geometry preflight nor patch acceptance establishes image fidelity.
    summary = {'mode': patch['mode'], 'status': 'preflight_passed', 'changed_slide_ids': changed,
               'asset_dimensions': dimensions, 'candidate_unchanged': True,
               'qa_report': str(folder/'qa_report.json'), 'feedback_path': str(folder/'layout_feedback.json'),
               'counts': qa['counts'], 'scientific_image_review_required': bool(dimensions)}
    if qa['counts']['FAIL']:
        error = Failure('PATCH_PREFLIGHT_FAILED', 'Repair failed existing compiler gates; '
                        'inspect the separate layout feedback. Canonical IR and candidate were preserved.',
                        'author_artifact', 'deck_ir', summary['feedback_path'])
        error.repair_summary = {**summary, 'status': 'rejected'}
        error.repair_base_resources = before
        raise error
    if resource_snapshot(base_path) != before:
        raise Failure('PATCH_STALE', 'Base resources changed during preflight; nothing was applied.',
                      'author_artifact', 'deck_ir')
    # The compiled snapshot also binds replacement assets/fonts to measured bytes.
    layout = read(folder/'layout.json')
    measured = {}
    for asset in layout['assets'].values():
        if sha(asset['path']) != asset['sha256']:
            raise Failure('PATCH_STALE', 'Replacement image changed during preflight; nothing was applied.',
                          'author_artifact', 'deck_ir')
        measured[asset['path']] = asset['sha256']
    return PreparedPatch(value, summary, before, measured)
