"""Component invocations and deterministic validation, never scientific content generation."""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import signal
from time import perf_counter

from . import ROOT, COMPONENT
from .state import read, write, sha, resources
from .requests import prompt_request
from .telemetry import span, timestamp

sys.path.insert(0, str(COMPONENT/'pwf2rpa'))


class Failure(ValueError):
    def __init__(self, code, message, action='resolve_dependency', target=None, log=None):
        super().__init__(message)
        self.code, self.action, self.target, self.log = code, action, target, log


def redact(text):
    for key, value in os.environ.items():
        if len(value) >= 6 and any(term in key.upper() for term in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')):
            text = text.replace(value, '[REDACTED]')
    return text


def classify(code, message, stage=None, log=None):
    if code in ('KEY_POINTS_LOST', 'SOURCE_TEXT_NOT_BOUND', 'CONTENT_LOSS'):
        return Failure('CONTENT_LOSS', message, 'replan', 'story' if stage == 'rpa' else 'deck_ir', log)
    if code == 'VISUAL_DESIGN_REQUIRED':
        return Failure('DESIGN_MISSING', message, 'author_artifact', 'visual_design', log)
    if code.startswith('STORY_'):
        return Failure('STORY_PROVENANCE_MISMATCH' if code == 'STORY_PROVENANCE_MISMATCH' else 'STORY_PROVENANCE_INVALID',
                       message, 'resolve_dependency' if code.endswith('MISMATCH') else 'author_artifact', 'story', log)
    if code.startswith('VISUAL_PLAN_'):
        return Failure(code, message, 'replan', 'visual_design', log)
    if any(term in code for term in ('CAPACITY', 'SPACE', 'SPLIT_REQUIRED', 'LAYOUT_TREE', 'SLOT_WRAP')):
        return Failure(code, message, 'replan', 'story' if stage == 'rpa' else 'deck_ir', log)
    return Failure(code, message, 'review_required' if stage == 'build' else 'resolve_dependency', stage, log)


def findings(value):
    result = []
    if isinstance(value, list):
        for child in value:
            result += findings(child)
    elif isinstance(value, dict):
        if ('code' in value or 'rule' in value) and str(value.get('severity', '')).upper() in ('FAIL', 'ERROR', 'BLOCKING'):
            result.append(value)
        for key in ('items', 'issues', 'deck_issues', 'problems', 'violations', 'errors', 'validation', 'slides'):
            result += findings(value.get(key))
    return result


def run_process(argv, cwd, timeout):
    options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    with subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
            **options) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=10)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def run(argv, cwd, out, name, timeout=120, json_output=True, allow_unplanned=False):
    job_path = Path(out)/'.totalpipe/job.json'
    try:
        job_id = read(job_path).get('job_id') if job_path.is_file() else None
    except (OSError, ValueError):
        job_id = None
    with span(out, stage=name, operation='component', component=name, job_id=job_id):
        return _run(argv, cwd, out, name, timeout, json_output, allow_unplanned)


def _run(argv, cwd, out, name, timeout, json_output, allow_unplanned):
    log = Path(out)/'logs'/(name+'.json')
    started_at, started = timestamp(), perf_counter()
    def record(value):
        write(log, {**value, 'started_at': started_at, 'finished_at': timestamp(),
                    'duration_ms': round((perf_counter()-started)*1000, 3)})
    try:
        process = run_process([str(a) for a in argv], cwd, timeout)
    except FileNotFoundError as error:
        code = 'OFFICECLI_MISSING' if 'officecli' in str(argv[0]).lower() else 'EXECUTABLE_MISSING'
        record({'code': code})
        raise Failure(code, f'Executable unavailable: {argv[0]}') from error
    except subprocess.TimeoutExpired as error:
        record({'code': 'COMPONENT_TIMEOUT', 'message': redact(str(error))})
        raise Failure('COMPONENT_TIMEOUT', 'Component timed out; its process was terminated. Retry or inspect the log.', log=str(log)) from error
    stdout, stderr = redact(process.stdout), redact(process.stderr)
    record({'argv': [redact(str(a)) for a in argv], 'exit_code': process.returncode,
            'stdout': stdout, 'stderr': stderr})
    value = None
    if json_output:
        try:
            value = json.loads(stdout)
        except ValueError as error:
            raise Failure('COMPONENT_BAD_JSON', 'Component did not return JSON; inspect its log.', log=str(log)) from error
    errors = findings(value)
    unplanned_ok = (allow_unplanned and process.returncode == 0 and not errors and
                    isinstance(value, dict) and bool(value.get('slides')) and
                    bool(value.get('unplanned_slide_briefs')))
    if (name.startswith('rpa-') and isinstance(value, dict) and not errors and
            (value.get('status') in ('failed', 'needs_replan') or value.get('unplanned_slide_briefs'))
            and not unplanned_ok):
        raise Failure('RPA_PLAN_REQUIRES_REPLAN',
                      'RPA left source briefs unplanned. Inspect the complete planning log and revise Story without dropping content.',
                      'replan', 'story', str(log))
    if (process.returncode or errors or (isinstance(value, dict) and value.get('status') in ('blocked', 'needs_replan', 'invalid'))) and not unplanned_ok:
        first = errors[0] if errors else {}
        code = first.get('code', first.get('rule'))
        if not code:
            match = re.search(r'\b(STORY_[A-Z_]+|[A-Z_]*CAPACITY[A-Z_]*|SOURCE_TEXT_NOT_BOUND|KEY_POINTS_LOST)\b', stderr)
            code = match.group(1) if match else 'COMPONENT_FAILED'
        raise classify(code, first.get('message') or stderr[-1000:] or 'Component rejected this input; inspect its log.',
                       'rpa' if name.startswith('rpa') or name == 'pwf2rpa'
                       else 'build' if name == 'build' else None, str(log))
    return value


def compiler(command, out, *args, timeout=120):
    return run([sys.executable, '-m', 'deck_compiler', command, *args], COMPONENT, out, command, timeout)


def pwf_cli(out, *args):
    return run([sys.executable, '-m', 'pwf2rpa', *args], COMPONENT/'pwf2rpa', out, 'pwf2rpa', json_output=False)


def rpa(command, source, out, allow_unplanned=False):
    value = run(['node', ROOT/'research-ppt-assistant/server/cli.mjs', command, '--file', source,
                 '--detail-level', 'full'], ROOT, out, 'rpa-'+command,
                allow_unplanned=allow_unplanned)
    return value


def check_queries(value):
    if not isinstance(value, list) or not value or len(value) > 32:
        raise Failure('QUERIES_INVALID', 'Provide 1–32 topic-specific query objects.', 'author_artifact', 'queries')
    ids = set()
    for query in value:
        if (not isinstance(query, dict) or set(query)-{'id', 'query', 'intent'} or
                not all(isinstance(query.get(k), str) and query[k].strip() for k in ('id', 'query')) or query['id'] in ids):
            raise Failure('QUERIES_INVALID', 'Each query needs a unique id and nonempty query; optional intent.', 'author_artifact', 'queries')
        ids.add(query['id'])


def check_story(prompt, story, workflow):
    from pwf2rpa import Workflow, story_to_specs
    from pwf2rpa.errors import AdapterError
    if not isinstance(story, dict):
        raise classify('STORY_PROVENANCE_INVALID', 'Story must be a JSON object.')
    expected, actual = prompt.get('delegation', {}), story.get('planner', {})
    if not isinstance(actual, dict) or not actual:
        raise classify('STORY_PLANNER_PROVENANCE_MISSING', 'Story must record its real subagent provenance.')
    if any(actual.get(key) != expected.get(key) for key in ('model', 'reasoning_effort')):
        raise classify('STORY_PROVENANCE_MISMATCH', 'Story model / reasoning differs from the user-selected prompt delegation.')
    from pwf2rpa.content_contract import validate_contract
    problems = validate_contract(story, required=bool(prompt.get('content_contract_version')),
                                 required_version=prompt.get('content_contract_version'))
    if problems:
        raise Failure('STORY_CONTENT_CONTRACT_INVALID', ' '.join(problems), 'author_artifact', 'story')
    try:
        story_to_specs(story, Workflow(workflow))
    except (ValueError, AdapterError) as error:
        raise classify('STORY_PROVENANCE_INVALID', str(error)) from error


def _supplement_blocks(ir):
    if not isinstance(ir, dict):
        return
    for slide in ir.get('slides', []) or []:
        if not isinstance(slide, dict):
            continue
        comp = slide.get('composition') if isinstance(slide.get('composition'), dict) else {}
        blocks = comp.get('blocks') if isinstance(comp.get('blocks'), list) else []
        supplements = [block for block in blocks
                       if isinstance(block, dict) and block.get('basis') == 'supplement']
        yield slide, supplements, [block for block in blocks if isinstance(block, dict)]


_INLINE_MATH = re.compile(r'(?<!\\)\$[^$\n]+\$|\\\(.+?\\\)')
_SCI_FULL = re.compile(
    r'(?<![\w$])(-?\d+(?:\.\d+)?)\s*[×xX]\s*10\s*\^\s*\{?\s*([+\-−]?\d+)\s*\}?(?![\w$])')
_SCI_POWER = re.compile(
    r'(?<![\w$×xX])10\s*\^\s*\{?\s*([+\-−]?\d+)\s*\}?(?![\w$])')


def _has_inline_math(text):
    return isinstance(text, str) and bool(_INLINE_MATH.search(text))


def _scientific_math(text):
    """Turn plain scientific notation into the existing measured inline-math path."""
    if not isinstance(text, str) or ('$' in text and _INLINE_MATH.search(text)):
        return text, False
    changed = False

    def full(match):
        nonlocal changed
        changed = True
        exponent = match.group(2).replace('−', '-')
        return f'${match.group(1)}\\times10^{{{exponent}}}$'

    def power(match):
        nonlocal changed
        changed = True
        exponent = match.group(1).replace('−', '-')
        return f'$10^{{{exponent}}}$'

    text = _SCI_FULL.sub(full, text)
    text = _SCI_POWER.sub(power, text)
    return text, changed


def _expand_diagram(comp, diagram):
    """Expand the small authoring shorthand into a canonical native graphic."""
    nodes = diagram.get('nodes')
    if not isinstance(nodes, list):
        return
    edges = diagram.get('edges')
    if not isinstance(edges, list):
        edges = [{'from': left.get('id'), 'to': right.get('id'), 'kind': 'arrow'}
                 for left, right in zip(nodes, nodes[1:])
                 if isinstance(left, dict) and isinstance(right, dict)
                 and left.get('id') and right.get('id')]
    graphic = {
        'id': diagram.get('id') or 'diagram',
        'type': diagram.get('type') or 'process',
        'direction': diagram.get('direction') or 'horizontal',
        'layout': diagram.get('layout') or 'chain',
        'nodes': nodes,
        'edges': edges,
    }
    if graphic['type'] == 'dag':
        graphic['direction'] = 'horizontal'
        graphic['layout'] = 'chain'
    graphics = comp.setdefault('graphics', [])
    if isinstance(graphics, list):
        graphics.append(graphic)


def normalize_authoring_ir(value):
    """Accept the small authoring shorthands before canonical schema validation.

    ``latex`` on a block is a display formula; ``composition.diagram`` is a
    chain/process graphic.  The canonical IR is unchanged after normalization,
    so the compiler, QA and layout providers keep their existing contracts.
    Inline ``$...$`` / ``\\(...\\)`` in a body block or title/takeaway enables
    the existing measured inline-math path.
    """
    if not isinstance(value, dict):
        return value
    slides = value.get('slides')
    if not isinstance(slides, list):
        return value
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        semantic = slide.get('semantic')
        if isinstance(semantic, dict):
            for key in ('title', 'takeaway'):
                converted, changed = _scientific_math(semantic.get(key))
                if changed:
                    semantic[key] = converted
                if changed or _has_inline_math(semantic.get(key)):
                    fields = semantic.setdefault('inline_math', [])
                    if isinstance(fields, list) and key not in fields:
                        fields.append(key)
        composition = slide.get('composition')
        if not isinstance(composition, dict):
            continue
        diagram = composition.pop('diagram', None)
        if isinstance(diagram, dict):
            _expand_diagram(composition, diagram)
        blocks = composition.get('blocks')
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if 'latex' in block and 'text' not in block:
                block['text'] = block.pop('latex')
                block.setdefault('component', 'formula')
            if block.get('component') != 'formula':
                converted, changed = _scientific_math(block.get('text'))
                if changed:
                    block['text'] = converted
                    block['inline_math'] = True
            if block.get('component') == 'body' and not block.get('inline_math'):
                if _has_inline_math(block.get('text')):
                    block['inline_math'] = True
        # Table cells are text too: a unit such as 1.2 × 10^5 Ω must become native math there as
        # well, otherwise a table shows carets next to superscripts on the rest of the page.
        for table in composition.get('tables') or []:
            if not isinstance(table, dict):
                continue
            for cell in table.get('cells') or []:
                if not isinstance(cell, dict) or cell.get('kind') == 'formula':
                    continue
                converted, changed = _scientific_math(cell.get('text'))
                if changed:
                    cell['text'] = converted
                    cell['inline_math'] = True
    return value


def check_design(value, story, evidence, slide_count=None, figures=None):
    """Refuse a page design that cannot be traced back to the Story or the evidence."""
    from deck_compiler.design import validate_design
    problems = validate_design(value, story, evidence, slide_count=slide_count)
    if isinstance(value, dict) and value.get('schema_version') in ('1.2', '1.3'):
        from .supplement import leak_messages
        supplements = [{'id': item.get('id'), 'text': item.get('text'), 'basis': 'supplement'}
                       for page in value.get('pages', []) if isinstance(page, dict)
                       for item in (page.get('display_copy') if isinstance(page.get('display_copy'), list) else [])
                       if isinstance(item, dict) and item.get('basis') == 'supplement']
        if supplements:
            problems += leak_messages({'slides': [{'id': 'design-copy', 'semantic': {}, 'composition': {'blocks': supplements}}]},
                                      {'evidence': [{'id': key, 'text': text} for key, text in evidence.items()]})
    if figures is not None and isinstance(value, dict) and value.get('schema_version') in ('1.1', '1.2', '1.3'):
        known = {figure['asset_id'] for figure in figures}
        for page in value.get('pages') or []:
            if isinstance(page, dict) and isinstance(page.get('figures', []), list):
                for asset in page.get('figures') or []:
                    if isinstance(asset, str) and asset not in known:
                        problems.append(f'{page.get("id")}: unknown figure asset {asset}')
    if problems:
        failure = Failure('PAGE_DESIGN_INVALID', ' '.join(problems[:6]),
                          'author_artifact', 'page_design')
        failure.details = problems
        raise failure


def load_design(work):
    """Load visual instructions and derive content from the immutable upstream Story."""
    from deck_compiler.design import bind_design
    work = Path(work)
    path = work/'page_design.json'
    if not path.is_file():
        return None
    design = read(path)
    if design.get('schema_version') in ('1.1', '1.2', '1.3'):
        from .ir_pages import resolve_design_sources
        design = resolve_design_sources(bind_design(design, read(work/'story_plan.json')), work)
        if design.get('schema_version') == '1.3':
            from .science_review import binding as science_binding
            try:
                science_binding(work)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise Failure('SCIENTIFIC_REVIEW_REQUIRED', str(error), 'author_artifact', 'scientific_review') from error
        if design.get('schema_version') in ('1.2', '1.3'):
            from .content_review import binding
            try:
                design['_review'] = binding(work)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise Failure('PAGE_DESIGN_REVIEW_REQUIRED', str(error), 'author_artifact', 'page_review') from error
        return design
    return design


DESIGN_MARKER = ' A page design is approved.'

PROJECTION_IR_INSTRUCTIONS = (
    'Implement approved page design 1.2/1.3 as canonical Deck IR. Scientific records and audience copy '
    'are separate: the tool archives complete assigned Story text and scoped qualifiers in notes; '
    'do not copy those records, design directions, review notes or walkthrough instructions into prose. '
    'Use only the approved display_copy for audience narrative (titles, takeaways, body, labels and captions). '
    'You may write {"copy_ref":"id"} in a textual field; the tool resolves it before canonical Schema validation. '
    'Keep literal data/formulas and traceable paper-figure/source metadata in their evidence carriers. '
    'For 1.3, inspected figure identities and visible source labels are bound from figure_sources; '
    'do not prepend them to approved caption text or put experimental conditions in source metadata. '
    'Native diagram/table/chart captions use component=caption with caption_for={kind,ref}; '
    'they are measured and emitted at the existing caption scale. Body prose cannot masquerade as a caption. '
    'Implement content_map carriers exactly; notes never satisfy required visible content or scoped conditions. '
    'The semantic.content_projection is bound automatically from the reviewed design, never authored or edited. '
    'Preserve meaning, units, conditions, uncertainty, important controls and negative findings. '
    'Do not add prose or simplify a claim. If approved copy or required objects do not fit, return measured '
    'feedback and replan page_design, retaining scientific records. Use native editable drawings and formulas. '
    'Select compiler capabilities to realize the approved visual relationships; do not redesign them. '
    'All font floors, original-figure aspect ratios, provenance, supplement boundaries and scientific '
    'geometry gates remain. Set the venue visual_style; declare no page coordinates. '
    'Use composite-research/layout_tree when explicit grouping is needed, and simple archetypes otherwise. '
    'Native data values cannot be guessed from raster curves. Explicit $...$ supports measured inline math. '
    'Submit deck_ir_page for page measurement/caching; call preview and actually open its PNG while revising. '
    'Complete full Design, build/QA and PowerPoint native acceptance after authoring.'
)


def apply_art_direction(value, design):
    """Write the design's devices into the IR before it is validated.

    The mechanical devices (marks in the text, figure provenance, takeaway frame, deck sections,
    agenda, footer, page numbers) are written by the compiler, not re-typed by the author: a design
    decision that has to be transcribed by hand is a decision that gets dropped. Structural devices
    (a panel group) stay with the author and are checked afterwards.
    """
    from deck_compiler.art_direction import apply
    if not design:
        return value, []
    return apply(value, design)


def finalize_design(work, design=None):
    """Fold the approved design into the IR prompt so the next stage realizes, not redesigns.

    Idempotent: the IR envelope may be produced more than once (status polls, retries) and the
    instruction must not be appended twice.
    """
    from deck_compiler.design import capabilities, summary, content_bindings
    source = work/'ir_prompt.json'
    if not source.is_file():
        return None
    if design is None:
        design_path = work/'page_design.json'
        if not design_path.is_file():
            return None
        design = read(design_path)
    path = work/'ir_prompt_designed.json'
    prompt = read(source)
    pages = summary(design)
    prompt['page_design'] = pages
    prompt['design_forms'] = capabilities()['forms']
    prompt['design_devices'] = capabilities()['art_direction']['devices']
    instructions = prompt.get('instructions', '').split(DESIGN_MARKER)[0]
    if design.get('schema_version') in ('1.2', '1.3'):
        instructions = PROJECTION_IR_INSTRUCTIONS
    prompt['instructions'] = instructions+DESIGN_MARKER+(
        ' Story owns scientific content; the approved page design owns its visual explanation. '
        'For legacy 1.1, resolve content_refs against Story without paraphrasing away conditions or boundaries. '
        'For 1.2, realize display_copy and content_map; scientific records are not display text. '
        'Implement the complete design instructions: chosen images, drawn elements, relationships, '
        'arrangement and presenter walkthrough. A design may use free prose or custom fields; do not '
        'discard unfamiliar fields or replace its visuals with a text summary. For legacy 1.0 realize '
        'claim, items, anchor and shape. Choose renderer forms/devices that implement the design, '
        'not a new visual concept. Keep page order, content assignment, figure selections and visible '
        'explanation obligations. Use native editable objects for drawings. If geometry cannot fit at '
        'the required type scale, return measured feedback for page-design replanning; never drop '
        'scientific content or shrink fonts. Set presentation.visual_style for the venue. '
        'Prefer per-page authoring via artifact_kind=deck_ir_page: each file is canonical Deck IR '
        'with exactly one slide and the same shared header. See next_action.page_authoring for page IDs '
        'and output paths. Submit a page when ready; the tool binds omitted Story evidence/notes and '
        'known figure paths, measures capacity, and caches passing pages. Revise only failed pages. '
        'All pages are assembled in approved order and checked together before downstream Design/build. '
        'A figure_refs asset_id may directly name an inventory asset ID/path; source_figure may be '
        'declared on either the reference or asset and is copied without guessing. For a lossless '
        'rectangular crop, asset.crop records source_path, source_sha256 and box=[left,top,right,bottom]; '
        'the source path may name the inventory and its hash is filled if omitted. Actual pixels '
        'must match the source rectangle; no rescaling, masking or redrawing is certified as a crop.')
    # Story is the scientific authority; the approved design supplies the visual handoff.
    # Do not carry duplicate RPA plans/raw models into the implementation prompt.
    trimmed = 'ir_prompt_designed.json trimmed to the design, story, evidence and compiler contracts'
    prompt = {key: value for key, value in prompt.items()
              if key not in ('workflow', 'rpa_input', 'content_model', 'deck_plan', 'unplanned_briefs')}
    prompt['trimmed_inputs'] = trimmed
    # What the IR author still needs and the cut inputs used to carry: the Story (speaker notes and
    # purpose), the evidence text behind each id, and the figure panels it may place.
    try:
        prompt['story'] = read(work/'story_plan.json')
        if design.get('schema_version') in ('1.1', '1.2', '1.3'):
            prompt['content_catalog'] = {
                source: {key: item[key] for key in ('evidence', 'policy') if key in item}
                for source, item in content_bindings(prompt['story']).items()}
    except (OSError, ValueError):
        if design.get('schema_version') in ('1.1', '1.2', '1.3'):
            raise Failure('PAGE_DESIGN_SOURCE_MISSING',
                          'Restore the approved story_plan.json before preparing the IR handoff.',
                          'resolve_dependency', 'page_design')
    pointer = work/'evidence_pointer.json'
    if pointer.is_file():
        try:
            workflow = read(pointer)['workflow']
            flow = read(workflow)
            prompt['evidence'] = {entry['evidence_id']: entry['text']
                                  for entry in flow.get('evidence_registry') or []}
            prompt['figures'] = [{'asset_id': item.get('asset_id'), 'path': item.get('path'),
                                  'source_width_px': item.get('source_width_px'),
                                  'source_height_px': item.get('source_height_px')}
                                 for item in (flow.get('artifacts') or {}).get('figure_assets_metadata') or []]
            prompt['workflow_root'] = str(Path(workflow).parent)
        except (OSError, ValueError, KeyError):
            pass
    if not path.is_file() or read(path) != prompt:
        write(path, prompt)
    from .ir_pages import prepare_prompts
    prepare_prompts(work, design, prompt)
    task = work/'deck_ir_task.md'
    text = ir_task(prompt)
    if not task.is_file() or task.read_text(encoding='utf-8') != text:
        task.write_text(text, encoding='utf-8')
    return path


def _digit_runs(text):
    return set(re.findall(r'\d+(?:\.\d+)?', str(text)))


def paper_slides(value):
    """Only standalone, uncited supplement text pages are outside the paper target.

    A page that carries paper evidence or any non-text scientific object remains a
    paper page, even when someone labels its text as supplement.
    """
    return [slide for slide, supplements, blocks in _supplement_blocks(value)
            if not (blocks and len(supplements) == len(blocks)
                    and not slide.get('semantic', {}).get('evidence_refs')
                    and not any(slide['composition'].get(key)
                                for key in ('figure_refs', 'graphics', 'tables', 'charts')))]


def design_realization_issues(value, design):
    """Collect every design mismatch; split Story nodes retain evidence across their pages."""
    issues = []
    def add(message, slide=None):
        issues.append({'code': 'DESIGN_REALIZATION_FAILED', 'severity': 'FAIL', 'message': message,
                       **({'slide': slide} if slide is not None else {})})
    if design.get('schema_version') in ('1.1', '1.2', '1.3') and not design.get('_content_bound'):
        add('Resolve content_refs with bind_design / load_design before IR validation.')
        return issues
    pages, slides = design.get('pages') or [], paper_slides(value)
    if len(slides) != len(pages):
        add(f'The approved design has {len(pages)} pages but the IR has {len(slides)} paper pages. '
            'Realize one IR page per designed page; split inside a page instead of adding or dropping pages.')
        return issues
    modern = design.get('schema_version') in ('1.1', '1.2', '1.3')
    groups = {}
    deck_refs = {ref for slide in slides for ref in slide['semantic'].get('evidence_refs') or []}
    for index, (slide, page) in enumerate(zip(slides, pages), 1):
        semantic = slide['semantic']
        if design.get('schema_version') in ('1.2', '1.3'):
            from deck_compiler.content_projection import snapshot as projection_snapshot
            expected = projection_snapshot(page, design['_content_catalog'], design['_review'])
            if semantic.get('content_projection') != expected:
                add(f'Page {index} ({page.get("id")}) lost or changed its approved audience projection.', index)
        cited = set(semantic.get('evidence_refs') or [])
        items = page.get('items') or []
        if design.get('schema_version') == '1.3':
            for item in [*items, *page.get('context_items', [])]:
                missing = set(item.get('evidence', []))-cited
                if missing:
                    add(f'Page {index} ({page.get("id")}) must retain precise evidence {sorted(missing)} for unit {item.get("source")}.', index)
        if modern:
            page_groups = {}
            for item in items:
                source = item.get('source', item.get('id', ''))
                group = source.split('.', 1)[0] if re.match(r'^S\d+\.', source) else 'ending'
                needed = set(item.get('evidence') or [])
                page_groups.setdefault(group, set()).update(needed)
                entry = groups.setdefault(group, {'needed': set(), 'cited': set(), 'pages': []})
                entry['needed'].update(needed)
                entry['cited'].update(cited)
                if page.get('id') not in entry['pages']:
                    entry['pages'].append(page.get('id'))
            for group, needed in page_groups.items():
                if needed and not needed.intersection(cited):
                    add(f'Page {index} ({page.get("id")}) needs an evidence anchor from Story {group}.', index)
        else:
            needed = {ref for item in items for ref in item.get('evidence') or []}
            if not needed <= cited:
                add(f'Page {index} ({page.get("id")}) must keep evidence {sorted(needed-cited)} from the approved design.', index)
        if modern:
            paths = [str((value.get('assets', {}).get(f.get('asset_id'), {}) or {}).get('path', '')).replace('\\', '/')
                     for f in slide['composition'].get('figure_refs') or []]
            from deck_compiler.crops import verified_source
            for figure in slide['composition'].get('figure_refs') or []:
                asset = value.get('assets', {}).get(figure.get('asset_id'), {})
                if 'crop' in asset:
                    try:
                        paths.append(verified_source(asset).replace('\\', '/'))
                    except (OSError, ValueError, TypeError) as error:
                        add(f'Page {index} ({page.get("id")}) has invalid crop provenance: {error}.', index)
            for selected in page.get('figures') or []:
                selected = selected.replace('\\', '/')
                if not any(path == selected or path.endswith('/'+selected) for path in paths):
                    add(f'Page {index} ({page.get("id")}) lost selected figure {selected}.', index)
        visible = semantic.get('title', '')+' '+semantic.get('takeaway', '')+' '+semantic.get('speaker_notes', '')
        for block in slide['composition'].get('blocks') or []:
            visible += ' '+str(block.get('text', ''))+str(block.get('label', ''))
        for figure in slide['composition'].get('figure_refs') or []:
            visible += ' '+str(figure.get('caption', ''))
        for table in slide['composition'].get('tables') or []:
            for cell in table.get('cells') or []:
                visible += ' '+str(cell.get('text', ''))
        if modern:
            from deck_compiler.graphic_layout import graphic_texts
            for graphic in slide['composition'].get('graphics') or []:
                visible += ' '+' '.join(text for _, text in graphic_texts(graphic))
            for chart in slide['composition'].get('charts') or []:
                for axis in ('x', 'y'):
                    visible += ' '+str(chart[axis].get('label', ''))+' '+str(chart[axis].get('unit', ''))
                visible += ' '+str(chart['x'].get('values', []))
                for series in chart.get('series') or []:
                    visible += ' '+str(series.get('label', ''))
                    for key in ('values', 'x_values', 'y_error'):
                        visible += ' '+str(series.get(key, []))
                visible += ' '+' '.join(note.get('text', '') for note in chart.get('annotations') or [])
        runs = _digit_runs(visible)
        for item in items if design.get('schema_version') not in ('1.2', '1.3') else []:
            if item.get('kind') == 'formula':
                continue
            missing = _digit_runs(item.get('text', ''))-runs
            if missing:
                add(f'Page {index} ({page.get("id")}) lost the numbers {sorted(missing)} that the approved design placed there.', index)
    for group, entry in groups.items():
        if design.get('_partial'):
            continue  # A page submission is checked again in the complete assembled deck.
        # Ending lines synthesize the whole deck, rather than duplicating its source ledger.
        covered = deck_refs if group == 'ending' else entry['cited']
        missing = entry['needed']-covered
        if missing:
            add(f'Story {group} must keep evidence {sorted(missing)} across its assigned pages {entry["pages"]}.')
    return issues


def _raise_ir_issues(issues):
    if not issues:
        return
    item = issues[0]
    failure = classify(item['code'], item['message'], 'deck_ir')
    if failure.action == 'resolve_dependency':
        failure.action, failure.target = 'author_artifact', 'deck_ir'
    failure.issues = issues
    failure.details = [item['message'] for item in issues]
    raise failure


def check_design_realization(value, design):
    _raise_ir_issues(design_realization_issues(value, design))


def ir_issues(value, normalized=None, supplement='off', design=None, slide_count=None):
    """The shared, complete acceptance checks, without writes or attempt accounting."""
    from deck_compiler.ir import validate
    original = copy.deepcopy(value)
    value = normalize_authoring_ir(value)
    issues = []
    def add(code, message, slide=None):
        issues.append({'code': code, 'severity': 'FAIL', 'message': message,
                       **({'slide': slide} if slide is not None else {})})
    mode = supplement if supplement in ('off', 'inline', 'pages', 'both') else 'off'
    has_supplement = has_supplement_page = False
    for slide, supplements, blocks in _supplement_blocks(value):
        has_supplement = has_supplement or bool(supplements)
        has_supplement_page = has_supplement_page or (bool(blocks) and len(supplements) == len(blocks))
    for slide in value.get('slides', []) if isinstance(value, dict) else []:
        projection = slide.get('semantic', {}).get('content_projection') if isinstance(slide, dict) and isinstance(slide.get('semantic'), dict) else None
        copies = projection.get('display_copy', []) if isinstance(projection, dict) else []
        if isinstance(copies, list) and any(isinstance(item, dict) and item.get('basis') == 'supplement' for item in copies):
            has_supplement = True
    if has_supplement and mode == 'off':
        add('SUPPLEMENT_NOT_ENABLED', 'This job did not enable supplement content; remove the supplement blocks/pages or start a job with supplement=inline/pages/both.')
    if has_supplement_page and mode == 'inline':
        add('SUPPLEMENT_PAGE_NOT_ENABLED', 'supplement=inline only allows blocks on existing pages; start with supplement=pages/both for standalone supplement pages.')
    for item in validate(value):
        if item['severity'] == 'FAIL':
            add(item['rule'], item['message'], item.get('slide'))
    # Subsequent checks need the canonical slide containers; malformed input already has FAILs.
    if not isinstance(value.get('slides'), list) or any(not isinstance(s, dict) or
            not isinstance(s.get('semantic'), dict) or not isinstance(s.get('composition'), dict)
            for s in value['slides']):
        return issues
    if slide_count is not None:
        from .requests import slide_count as validate_count
        validate_count(slide_count)
        count = len(paper_slides(value))
        if count != slide_count:
            add('SLIDE_COUNT_MISMATCH', f'IR has {count} paper pages; the requested final paper-page target is {slide_count}. Replan the pages without dropping scientific content.')
    if design:
        issues.extend(design_realization_issues(value, design))
        from deck_compiler.art_direction import check as check_devices
        for page, message in check_devices(value, design):
            add('DESIGN_REALIZATION_FAILED', f'{page or "deck"}: the approved design chose a device this IR does not carry — {message}. Devices are decisions; the page must show them.')
    if normalized:
        def texts(value):
            if isinstance(value, dict):
                return '\n'.join(texts(v) if isinstance(v, (list, dict)) else str(v)
                    for k, v in value.items() if isinstance(v, (dict, list)) or k in
                    ('text', 'title', 'body', 'label', 'takeaway', 'speaker_notes'))
            if isinstance(value, list):
                return '\n'.join(texts(v) if isinstance(v, (dict, list)) else str(v) for v in value)
            return ''
        corpus = ''.join(texts(original.get('slides', [])).split())
        known = {entry.get('id', entry.get('evidence_id')) for entry in normalized.get('evidence', [])}
        for index, page in enumerate(value['slides'], 1):
            unknown = set(page['semantic'].get('evidence_refs') or [])-known
            if known and unknown:
                add('CONTENT_LOSS', f'IR evidence_refs must resolve to the original normalized evidence store: {sorted(unknown)}.', index)
        if not design:
            for brief in normalized.get('slide_briefs', []):
                for content in [brief.get('body', ''), *brief.get('key_points', [])]:
                    if content and ''.join(str(content).split()) not in corpus:
                        add('CONTENT_LOSS', 'IR must retain each complete brief body and key_point in page text or speaker notes.')
        for brief in normalized.get('slide_briefs', []):
            compact = (brief.get('metadata') or {}).get('story_compact_process')
            if not isinstance(compact, dict):
                continue
            items = [str(item) for item in compact.get('items', []) if str(item).strip()]
            node_count = compact.get('node_count') or len(items)
            if len(items) < 6:
                continue
            carried = False
            for page in value['slides']:
                for graphic in page.get('composition', {}).get('graphics', []) or []:
                    if not isinstance(graphic, dict) or graphic.get('type') != 'process' or graphic.get('layout') != 'compact':
                        continue
                    nodes = [node for node in graphic.get('nodes', []) if isinstance(node, dict)]
                    titles = ''.join(''.join(str(node.get(key, '')).split()) for node in nodes for key in ('title', 'body'))
                    if len(nodes) >= node_count and all(''.join(item.split()) in titles for item in items):
                        carried = True
                        break
                if carried:
                    break
            if not carried:
                add('CONTENT_LOSS', f'Story declared a {node_count}-step compact process, but the IR has no type=process/layout=compact graphic carrying every step; replace the RPA three-slot placeholder.')
        if mode != 'off':
            from .supplement import leak_messages
            # Scientific notation normalization must not hide an author's paper value.
            for message in leak_messages(original, normalized):
                add('SUPPLEMENT_PAPER_LEAK', message)
            for slide in original.get('slides', []):
                projection = slide.get('semantic', {}).get('content_projection')
                copies = projection.get('display_copy', []) if isinstance(projection, dict) else []
                supplementary = [{'id': item['id'], 'text': item['text'], 'basis': 'supplement'}
                                 for item in copies if isinstance(item, dict) and item.get('basis') == 'supplement'] if isinstance(copies, list) else []
                for message in leak_messages({'slides': [{'id': slide['id'], 'semantic': {}, 'composition': {'blocks': supplementary}}]}, normalized):
                    add('SUPPLEMENT_PAPER_LEAK', message)
    return issues


def check_ir(value, normalized=None, supplement='off', design=None, slide_count=None):
    _raise_ir_issues(ir_issues(value, normalized, supplement, design, slide_count))


def persist_ir(value, source, destination):
    """Write the canonical IR with asset paths resolved against the file it was authored in."""
    for asset in value.get('assets', {}).values():
        if not Path(asset['path']).is_absolute():
            asset['path'] = str((Path(source).parent/asset['path']).resolve())
        if isinstance(asset.get('crop'), dict) and not Path(asset['crop']['source_path']).is_absolute():
            asset['crop']['source_path'] = str((Path(source).parent/asset['crop']['source_path']).resolve())
    for key in ('font_file', 'bold_font_file', 'background_image'):
        ref = value.get('theme', {}).get(key)
        if ref and not Path(ref).is_absolute() and (Path(source).parent/ref).is_file():
            value['theme'][key] = str((Path(source).parent/ref).resolve())
    write(destination, value)
    return destination


def import_ir(source, destination, supplement='off', slide_count=None):
    value = read(source)
    check_ir(value, supplement=supplement, slide_count=slide_count)
    return persist_ir(value, source, destination)


def ir_prompt(workflow, rpa_input, normalized, plan, supplement='off'):
    from deck_compiler.catalog import ARCHETYPES, COMPONENTS
    from deck_compiler.layout_tree import capabilities
    from deck_compiler.type_scale import constraints
    from deck_compiler.style import capabilities as style_capabilities
    prompt = {'workflow': workflow, 'rpa_input': rpa_input, 'content_model': normalized, 'deck_plan': plan,
        'archetypes': ARCHETYPES, 'components': sorted(COMPONENTS), 'capabilities': capabilities(),
        'type_scale': constraints(), 'visual_style': style_capabilities(),
        'schema': read(COMPONENT/'schemas/deck-ir.schema.json'),
        'instructions': 'Write canonical Deck IR. Preserve complete scientific body, key_points, figures, equations, '
        'units and uncertainty. Semantic titles are declarative phrases, not questions: do not copy a Story '
        'question and do not end a title with ? or ？. '
        'Choose the page structure first: composite-research + layout_tree is a first-class option, not only '
        'a recovery after a capacity error. Use it from the start when a page has 3+ content objects, a native '
        'graphic plus text, or needs panels/columns. Minimal tree: version="1.0", regions.body={type:"stack"|'
        '"columns", children:[{type:"graphic",ref:"flow"},{type:"block",ref:"note"}]}; every block/figure/'
        'graphic is referenced exactly once. Do not add a tree merely to use one: if an archetype already owns '
        'the needed composition (for example figure-parameters for a figure + text split), keep the simpler '
        'archetype. Use the tree for a grouping, panel structure or capacity that the archetype cannot express. '
        'Process/DAG node body is optional: for a compact flow keep only '
        'the short node title and put explanation in the page takeaway, a supplement block or speaker notes; '
        'do not inflate nodes with filler. If a measured tree still overflows, split the page; do not delete '
        'content. Source paths are relative to workflow_root; use absolute paths in work/deck_ir.json. '
        'Respect type_scale: every page has one body size and the floors are hard. component="metric" '
        'marks the measured number a page is about; it is set one reading step above body copy, so use it '
        'only when that number is the point, never as a headline and never for prose. '
        'Set presentation.visual_style to the pack that fits the venue ("academic" for research talks, '
        '"commercial" for product decks, "print" for handouts); the pack decides node shape, fill and rule '
        'weight, never composition. '
        'Retain original body/key_points in speaker_notes when a display expression changes their literal notation. '
        'Do not write page bboxes. Keep full evidence refs; use native formulas and explicit graph relationships. '
        'For every brief with metadata.story_explain, write semantic.explanation with the same obligations and '
        'evidence_refs. Set carrier to the native object actually used and status=bound; if a required obligation '
        'cannot be carried, use status=waived or unsupported with a note, never drop it silently. Use inline_math or '
        'formula for quantity, a native list/table/layout_tree for parallel_items, layout_tree for grouped_panels, '
        'table/columns for comparison, process/dag for ordered_steps, mechanism/dag for relation and path for curve. '
        'If a brief has metadata.story_compact_process, ignore the smaller RPA process placeholder and write one '
        'type=process graphic with layout=compact, one square rect node per declared item, in the declared order; '
        'do not collapse the chain to the RPA three-slot page.'
        ' Authoring shorthand: a display equation may be written as '
        '{"id":"eq1","latex":"S_{\\\\lambda}(z)=..."} (component/text are filled automatically), and a simple '
        'flow may be written as composition.diagram={"id":"flow","nodes":[{"id":"a","title":"..."},...]}; '
        'the Agent expands it to one native process graphic with chained arrows. Inline $...$ in a body block, '
        'title or takeaway enables the measured inline-math path automatically. '
        'Emphasis is written in the text, never as a second text box: wrap the phrase that carries the claim in '
        '**double asterisks** (set in the deck accent and bold) and a symbol or short expression in ==double '
        'equals== (highlighted). One marked phrase per sentence is enough, markers may not span $...$ , and a '
        'native list carries one run style, so keep a marked block on text_flow plain. '
        'Page furniture: presentation.page_numbers defaults to true and numbers every designed page; set '
        'presentation.footer to one short line (deck title or lab) when the venue expects a signature, and '
        'presentation.page_numbers=false only when the numbers would be wrong. '
        'A long deck may declare structure instead of drawing it: mark the first page of each section with '
        'presentation.section (one line, at most 24 characters) and set presentation.agenda to true or '
        '{"title":"目录"}; the compiler inserts one contents page after the opening page with numbered '
        'sections, dot leaders and the page each one starts on. Every word on that page comes from your '
        'own section labels, so do not also spend a page on a table of contents. '
        'To label a group inside a panel, set frame.title_band="chip" with a solid title_fill: the title '
        'becomes a rounded label that hugs its text. When a source figure belongs to a paper panel, write '
        'figure_refs.source_label (author or citation, at most 80 characters); the compiler sets it as a '
        'weakened prefix before the caption.'}
    if supplement in ('inline', 'pages', 'both'):
        prompt['supplement'] = supplement
        prompt['instructions'] += (
            ' Supplement content is enabled. You may add background, analogy, a constructed example, a derivation '
            'step, an illustrative diagram or a comparison that is not from the paper, when it helps the audience. '
            'Mark every such block with "basis":"supplement" and "supplement":{"kind":"...","source":"...","constructed":false}. '
            'Never put evidence_refs on a supplement block; never put a paper number, unit, figure or a long verbatim '
            'passage from the evidence into a supplement block. If a supplement page uses a paper figure, keep a paper '
            'block with the correct evidence on that page. A constructed example needs a visible 示意/构造/简化/示例 label. '
            'A supplement page may write semantic.explanation; each obligation uses "basis":"supplement" and no '
            'evidence_refs, while paper obligations keep "basis":"paper" and their evidence. '
            'supplement=inline allows blocks on existing pages only; pages/both also allow standalone supplement pages.')
    return prompt


LEGACY_DESIGN_INSTRUCTIONS = (
    'Design the visual explanation of the approved Story. Story owns the scientific argument, '
    'claims, evidence and boundaries; do not retell it, reinterpret it or write another outline. '
    'Your output is a drawing and presentation brief for the IR author: what to put on the page, '
    'what to draw or reuse, how to arrange it and how the presenter guides attention. '
    'Assign each Story content path from content_catalog to exactly one page using content_refs; '
    'the pipeline inherits its text and evidence automatically. Never copy Story paragraphs into '
    'the design. A short display title or a necessary diagram label is fine. '
    'Use design as free prose or a custom object, whichever communicates the page best. Describe '
    'concrete visual objects: selected original panels, drawn shapes, layer stacks, arrows and '
    'edge meanings, icons with a purpose, comparison axes, equation annotations or data charts. '
    'You may draw your own explanatory diagrams, mechanisms, processes and structures; using a paper '
    'image is a choice, not a requirement for every page. Mark illustrative drawings as schematic, '
    'keep paper facts and data bound to their evidence, and label constructed examples explicitly. '
    'Specify their relationship, relative placement, visual hierarchy and the order in which the '
    'presenter points to them. A vague instruction such as explain the mechanism is insufficient. '
    'Choose which visual forms serve the content; nothing you decide here depends on what a tool '
    'can draw. You may name a diagram or composition, but do not choose compiler templates, '
    'archetypes or API components. No mandatory cards, columns, icon quotas or decorative filler. '
    'The room is given by the request; record setting briefly rather than analyzing it at length. '
    'Inspect actual image files before selecting them; use the exact asset_id in figures, preserve '
    'aspect ratio and figure/source labels, and say where annotations should point. Never guess '
    'curve points or draw an unavailable supplementary figure. New measurements, causal claims or '
    'external facts are outside this stage; flag missing Story/evidence upstream rather than inventing '
    'them. Illustration is visibly schematic and must preserve the distinction between observation '
    'and author interpretation. A data chart needs traceable data; otherwise use the original image. '
    'Respect Story explain obligations: the visible page must contain the objects needed to understand '
    'the conclusion, while optional detail can be spoken. Split or merge content references as '
    'needed within the requested page count, retaining every content unit. Do not write Deck IR '
    'or final coordinates. Make a concise, concrete design handoff, not a second scientific essay.'
)

DESIGN_INSTRUCTIONS = (
    'Design the audience expression and visual explanation of approved scientific records. '
    'Story owns facts, argument, evidence and visibility policies. You own faithful display_copy: '
    'rewrite for this audience, replace verbal repetition with a meaningful diagram, and give each page a clear claim. '
    'Preserve scientific meaning, causal strength, comparison objects, units, uncertainty, controls and negative results. '
    'Scientific record preservation does not require copying its sentences onto the screen. '
    'Assign each scientific source in content_catalog exactly once with content_refs. Write display_copy (id, role, text, source_refs), '
    'with exactly one title and takeaway. Roles are title/takeaway/body/label/caption, not layout templates. '
    'Map every assigned source to visible carriers or justified notes using content_map. A visible route lists '
    'carriers {kind,ref,locator}: copy refers to display_copy id; figure names a selected inspected asset; '
    'formula/table/chart/graphic names the visual object you describe. Visual locators explain what evidence to read. '
    'Follow content_contract: required sources stay visible; a with_claim qualifier is also mapped visible on every '
    'page where an applies_to claim is visible, even when owned by another page. These contextual qualifiers may '
    'repeat visually, while source ownership remains unique. notes_allowed needs a reason based on the page claim. '
    'Do not turn important controls, uncertainty or negative findings into optional spoken detail. '
    'Keep production_notes separate. design/claim rationale/walkthrough/negative authoring directions are not '
    'display_copy. Do not dump evidence-audit prose onto slides; show scientific limitations where they restrict a claim. '
    'Paper copy cites source_refs and inherits their evidence. Organizational copy uses basis=organization and no '
    'source_refs or scientific numbers; it cannot supply scientific claims. Supplementary copy uses basis=supplement '
    'and supplement={kind,source,constructed}, no paper refs, and visible labels for constructed examples. '
    'Use design as free prose or a custom object for concrete visuals, their relationships, hierarchy and presenter '
    'pointing order. You may draw your own explanatory diagrams, mechanisms, processes and structures. '
    'Choose visual forms that serve the argument; nothing you decide here depends on what a tool can draw. '
    'Do not select compiler templates, archetypes, APIs or coordinates. No mandatory cards, columns or icon quotas. '
    'Inspect actual figure files before selecting exact asset IDs, preserve aspect ratio and source/figure labels. '
    'Do not guess curve points or unavailable supplementary images. Label illustrative drawings as schematic. '
    'Use setting to briefly reuse the requested room, audience and reading mode. After design, the orchestrator '
    'performs source/copy review; do not supply a self-approval. Keep the handoff concrete and concise.'
)

ATOMIC_DESIGN_INSTRUCTIONS = (
    'Atomic content_contract 2.0: scientific units, not narrative paragraphs, are the source of truth. '
    'Own every unit exactly once via content_refs. If you repeat a required assertion owned by another page, '
    'declare its ID in reuse_refs, actually display it and cite it; do not clone the assertion under a new ID. '
    'Only qualifiers directly targeting assertions actually visible here follow them. Do not inherit an entire '
    'Story node, unrelated experiment, or the conditions of a result you did not restate. '
    'A concluding conceptual claim can omit a numerical result already explained; if the number is restated, '
    'its source and applicable conditions must remain visible. Keep the whole scientific ledger in the deck. '
    'For every selected figure, figure_sources maps its exact asset ID to {source_figure: inspected figure/panel ID}. '
    'These are source identities, not measurements. The tool renders their visible provenance separately from '
    'approved caption wording; never delete source labels to satisfy a numeric check. '
    'If the approved science still mixes independently limitable claims or omits a prerequisite, report an upstream '
    'Story problem instead of hiding conditions or adding unsupported facts. '
)+DESIGN_INSTRUCTIONS


def design_task(prompt=None):
    """Delegate visual explanation, without duplicating scientific planning."""
    figures = len((prompt or {}).get('figures') or [])
    briefs = len((prompt or {}).get('briefs') or [])
    target = ((prompt or {}).get('request') or {}).get('slide_count')
    pages = f'最终论文页为 {target} 页。' if target else '按内容和场合排页，最多 40 页。'
    if ((prompt or {}).get('story') or {}).get('content_contract'):
        atomic = (prompt['story']['content_contract'].get('version') == '2.0')
        contract = '1.3（原子科学记录）' if atomic else '1.2'
        return f"""# 页面表达与设计任务（独立子代理，{contract}）

完整读取 `work/page_design_prompt.json` 和 schema_path 的完整 Schema。输入含 {briefs} 条参考 briefs、
科学记录及其可见性契约、{figures} 张图、证据与场合。输出 `work/page_design.json`。{pages}

- Story 决定科学含义及边界，你负责忠实改写成观众文案和视觉讲解，不重做科学大纲。
- 每条科学记录用 content_refs 恰好分配一次；display_copy 写实际投屏的标题、结论、正文、图中标签和图注。
  每项用 source_refs 追溯，关键英文术语和科学含义保持正确；不复制制作说明、核查过程或设计指令。
- content_map 给每条分配记录标明 visible 的载体或 notes 的理由。required 必须可见；with_claim 的条件
  跟随它限定的主张同页可见，必要时重复显示条件，而不重复分配原始记录。完整记录由程序归档到讲稿。
- design 自由说明用什么原图、画什么元素与关系、如何排布、怎样带着观众看。figures 写精确资产 id，先看图。
  图中数据不能猜点；示意与构造例须可见标识，论文与补充背景来源分开。
- setting 复用用户场合，不展开第二次听众分析。讲解顺序指向具体对象。无需知道编译器能力，不读源码。
- 你不填写通过审查的记录。主 Agent 之后逐页对照科学记录审读文案，未通过会退回设计。

输出设计，简述页数和关键视觉选择。不要把这份任务书改写成幻灯片正文。"""
    return f"""# 页面设计任务（独立子代理）

Story 已经决定讲什么以及证据边界。你的任务是把它变成可执行的视觉讲解设计，交给 IR 作者。

- 完整读取 `work/page_design_prompt.json` 和其中 `schema_path` 指向的 Schema；输入含 Story、
  {briefs} 条参考 briefs、证据、{figures} 张图的路径与尺寸、场合以及 `content_catalog` 引用索引。
  Story 是内容权威，briefs 是传输参考，不需要重写其中的正文。
- 输出 `work/page_design.json`，使用 1.1 协议。{pages} 每条 Story 内容用 `content_refs`
  恰好分配一次；开场等纯组织页可为空。正文与 evidence 由管线从 Story 自动继承。
- 每页只必填 `id`、`content_refs`、`design`。`design` 可以是一段话，也可以是你自定字段的对象；
  不规定所有页面用同一套结构。说明**用什么原图、画什么元素与关系、如何排布、怎样带着观众看**。
  可按需写图形、图标、图表、公式标注、对照、局部放大和指示线；不要止于“解释某机制”。
- `figures` 列精确资产 id，先实际查看图再选择；相对路径基于 `workflow_root`。`title` 和 `marks`
  都可选，marks 只用于需要强调的现有短语。不需要重写 claim、items、anchor 理由或 rationale。
- `setting` 简述 audience、occasion（沿用 room.default_occasion 或选合适键）、reading（spoken/read/mixed）。
  场合服务于设计，不展开第二次听众分析。
- 内容顺序与科学结论沿用 Story，允许为视觉表达拆页、合页。讲解顺序写指向动作与对象，
  不再复述整段科学解释。保留 explain 中必需可见的内容。
- 可以决定图形与构图形式，不需要知道编译器能力；不写坐标、API 或 Deck IR，不读取编译器源码。
  原图保持比例与来源；数据图不猜点；没有补充图就不虚构；示意须可见标注且不增添科学主张。

交付时简述页数及最关键的视觉设计，不重述论文。"""


def ir_task(prompt=None):
    """The brief an orchestrator hands to the IR subagent once the design is approved."""
    pages = ((prompt or {}).get('page_design') or {}).get('pages') or []
    if ((prompt or {}).get('page_design') or {}).get('schema_version') in ('1.2', '1.3'):
        return f"""# Deck IR 实现任务（页面表达契约 1.2）

源文案已由主 Agent 审读。完整读取 `work/ir_prompt_designed.json` 或指定逐页提示包及完整 IR Schema。
实现 {len(pages)} 页的 display_copy、content_map 和视觉设计，保持页序、分配、选图和科学含义。

- display_copy 是投屏文案权威；Story 是科学记录。可在文本字段写 {{"copy_ref":"文案 id"}}，提交时自动绑定。
  不把 Story 长段、设计指令、walkthrough、核查备注重新填成正文；不自行增加或改写已批准的句子。
- semantic.content_projection、完整讲稿、来源和 scoped qualifiers 由程序绑定。必需可见的对象、条件和对照
  按 content_map 实现；讲稿和元数据不算页面可见。原生图表/公式承载的数据和原图来源保持可追溯。
- 选择能力实现既定视觉；自绘优先用原生对象，布局树可直接使用。不写页面 bbox，不缩字号、不删内容。
  容量不足时把测量反馈退回页面设计，不能修改科学含义或擅自润色文案。
- 可以随时 preview，实际打开返回 PNG 后再修 IR；语义、补充归属、几何、完整 Design、构建及原生验收均保留。

交付实现选择与真实未解决项。"""
    return f"""# Deck IR 实现任务（子代理）

页面设计已经批准。逐页实现视觉设计；Story 保持科学内容权威。

- 完整读取 `work/ir_prompt_designed.json` 及 IR Schema。其中有 {len(pages)} 页设计、Story、证据和实现能力。
- 输出符合 canonical Schema 的 `work/deck_ir.json`。资产 path 基于 workflow_root，IR assets 用绝对路径。
- 1.1 设计的 content_refs 指向 Story 原文；content_catalog 给出自动继承的 evidence，含 ending 的汇总来源。
  设计里的 design 是绘图、构图与讲解交代，
  包含具体元素、关系、排布和注意顺序。完整保留自定义设计说明，不把它退化成文字摘要。
  自绘内容优先用原生对象；图形形式已由设计确定，你只选择可实现它的 archetype / layout_tree 等。
- 页序、内容分配、选图和视觉关系不变；marks 如有则落实为文字强调。旧 1.0 设计的 claim/items/shape 同样实现。
- 理解结论所需的证据必须可见，讲稿不能替代；保留单位、条件、误差和 Story explain 义务。
  放不下时报告具体所需空间并回退页面设计，不改科学含义、不猜数据、不删内容、不缩字号。

交付时简述实现选择与未解决限制。"""


def execute(stage, job):
    out = Path(job['request']['out_dir'])
    work = out/'work'
    request = job['request']
    if stage == 'evidence':
        if request['source_kind'] == 'workflow':
            workflow = Path(request['source'])
            value = read(workflow)
            outputs = [Path(p) for p, hashed in resources(workflow).items() if hashed is not None]
        else:
            args = work/'evidence_args.json'
            # Forward the declared intent when present; PaperWorkflow honours it
            # instead of re-inferring from the wording.
            queries = [{'query': q['query'], **({'intent': q['intent']} if q.get('intent') else {})}
                       for q in read(work/'queries.json')]
            write(args, {'source_path': request['source'], 'output_dir': str(out/'evidence'),
                         'queries': queries,
                         'supplementary_paths': request.get('supplementary_paths', []),
                         'supplementary_content_included': request.get('supplementary_content_included', False)})
            result = run([sys.executable, Path(__file__).parent/'bridges/paperworkflow_bridge.py',
                          '--op', 'literature_workflow', '--args', args], ROOT, out, 'evidence', 1200)
            if not result.get('ok') or result['result'].get('status') == 'blocked':
                raise Failure('EVIDENCE_DEPENDENCY_FAILED', result.get('message') or 'PaperWorkflow cannot ingest the source; run doctor.')
            workflow = Path(result['result']['workflow_path'])
            value = read(workflow)
            outputs = [out/'evidence']
        from pwf2rpa import Workflow
        from pwf2rpa.errors import AdapterError
        try:
            Workflow(value).validate()
        except AdapterError as error:
            raise Failure('EVIDENCE_INVALID', str(error), 'replan', 'evidence' if request['source_kind'] == 'workflow' else 'queries') from error
        if value.get('synthesis_readiness', {}).get('readiness') != 'ready':
            # Keep the failing gate, but also carry per-query diagnostics so the
            # replan action says which query to fix instead of "revise queries".
            feedback = dict(value.get('synthesis_readiness') or {})
            retrieval = (value.get('quality_dimensions') or {}).get('retrieval') or {}
            feedback['retrieval'] = {k: retrieval.get(k) for k in
                                     ('score', 'readiness', 'mean_coverage_ratio', 'coverage_domain',
                                      'precision_ratio', 'support_span_exposure_ratio', 'warnings')}
            feedback['per_query'] = [
                {**{k: item.get(k) for k in ('query_id', 'intent', 'status', 'precision_ratio')},
                 'coverage': item.get('coverage')}
                for item in retrieval.get('diagnostics') or []
            ]
            write(work/'evidence_feedback.json', feedback)
            raise Failure('EVIDENCE_NOT_READY', 'Evidence synthesis requires source / supplementary review; inspect evidence_feedback.json. '
                          'Repair the original evidence bundle or revise queries / source material before advancing.', 'replan',
                          'evidence' if request['source_kind'] == 'workflow' else 'queries')
        write(work/'evidence_pointer.json', {'workflow': str(workflow)})
        return [*outputs, work/'evidence_pointer.json']
    if stage == 'story_prompt':
        workflow = read(work/'evidence_pointer.json')['workflow']
        selection = job['inputs']
        pwf_cli(out, workflow, '--make-story-prompt', work/'story_prompt.json', '--story-model', selection['model'],
                '--story-reasoning', selection['reasoning_effort'], '--model-selected-by-user')
        prompt = read(work/'story_prompt.json')
        prompt['request'] = prompt_request(request)
        prompt['instructions'] += ('\n\nPresentation request: '+json.dumps(prompt['request'], ensure_ascii=False)+
                                   '\nUse the requested presentation language while preserving scientific terms and uncertainty.')
        write(work/'story_prompt.json', prompt)
        return [work/'story_prompt.json']
    if stage == 'rpa':
        workflow = read(work/'evidence_pointer.json')['workflow']
        pwf_cli(out, workflow, '--story', work/'story_plan.json', '--out', work/'rpa_input.json')
        model = rpa('normalize-content', work/'rpa_input.json', out)
        write(work/'normalized_content.json', model)
        # The independent page designer owns the page plan. Running the template
        # planner here produced a second, conflicting plan that was discarded later.
        write(work/'rpa_validation.json', {'status': 'content_normalized', 'layout_owner': 'page_design',
              'brief_count': len(model.get('slide_briefs', [])),
              'evidence_count': len(model.get('evidence', []))})
        prompt = ir_prompt({}, {}, {}, {}, request.get('supplement', 'off'))
        for key in ('workflow', 'rpa_input', 'content_model', 'deck_plan'):
            prompt.pop(key, None)
        prompt['content_paths'] = {'workflow': str(workflow),
                                  'rpa_input': str(work/'rpa_input.json'),
                                  'normalized_content': str(work/'normalized_content.json')}
        # finalize_design supplies the complete approved design, Story, evidence
        # and figures before the IR author is invoked; no 1.6 MB intermediate plan.
        prompt['workflow_root'] = str(Path(workflow).parent)
        prompt['request'] = {**prompt_request(request),
                             'supplement': request.get('supplement', 'off')}
        write(work/'ir_prompt.json', prompt)
        for obsolete in ('plan_input.json', 'deck_plan.json', 'validation_input.json'):
            (work/obsolete).unlink(missing_ok=True)
        return [work/name for name in ('rpa_input.json', 'normalized_content.json', 'rpa_validation.json', 'ir_prompt.json')]
    if stage == 'page_design':
        from deck_compiler.design import capabilities as design_capabilities, default_occasion, content_bindings
        workflow = read(work/'evidence_pointer.json')['workflow']
        value = read(workflow)
        evidence = {entry['evidence_id']: entry['text'] for entry in value['evidence_registry']}
        # The extracted figure panels are the only visual inventory the design can name. The
        # workflow keeps them under `figure_assets_metadata`; reading `artifacts.figures` (which no
        # PDF run fills) is why earlier designs never saw a single image.
        figures = [{'asset_id': item.get('asset_id'),
                    'path': item.get('path') or item.get('asset_id'),
                    'width': item.get('source_width_px'), 'height': item.get('source_height_px')}
                   for item in (value.get('artifacts') or {}).get('figure_assets_metadata') or []]
        content = read(work/'normalized_content.json')
        # RPA remains the content transport; its paraphrased bodies are not a second scientific
        # authority next to Story. Keep only its index here, not repeated prose/claims.
        briefs = [{'id': brief.get('slide_id'), 'title': brief.get('title'),
                   'evidence': brief.get('evidence_ids') or []}
                  for brief in content.get('slide_briefs') or []]
        capabilities = design_capabilities()
        story = read(work/'story_plan.json')
        projection = bool(story.get('content_contract'))
        atomic = (story.get('content_contract') or {}).get('version') == '2.0'
        design_version = '1.3' if atomic else '1.2'
        prompt = {
            'request': prompt_request(request),
            'room': {
                'presentation_type': request['presentation_type'],
                'brief': request['requirements'],
                'default_occasion': default_occasion(request.get('presentation_context', request['presentation_type']),
                                                    request['requirements']),
                'occasions': list(capabilities['occasions']),
                'note': 'Reuse the requested audience, duration and reading mode; do not re-plan the scientific story.',
            },
            'story': story,
            'briefs': briefs,
            'evidence': evidence,
            'figures': figures,
            'schema_path': str(COMPONENT/'schemas'/(f'page-design-v{design_version}.schema.json' if projection else 'page-design.schema.json')),
            'workflow_root': str(Path(workflow).parent),
            'content_catalog': {source: {key: binding[key] for key in ('evidence', 'policy') if key in binding}
                                for source, binding in content_bindings(read(work/'story_plan.json')).items()},
            'shape': {
                'schema_version': '1.1', 'deck_id': '<string>',
                'setting': {'audience': '<briefly reuse the request>',
                            'occasion': '<room.default_occasion or another occasion key>',
                            'reading': 'spoken|read|mixed'},
                'pages': [{'id': 'P1', 'content_refs': ['S1.answer'],
                           'design': '<free prose or your own object: visual elements, drawing '
                                     'instructions, arrangement and presenter pointing order>',
                           'figures': ['<optional: exact asset_id actually inspected>']}]},
            'instructions': ATOMIC_DESIGN_INSTRUCTIONS if atomic else DESIGN_INSTRUCTIONS if projection else LEGACY_DESIGN_INSTRUCTIONS,
        }
        if projection:
            prompt['shape']['schema_version'] = design_version
            page = prompt['shape']['pages'][0]
            page['display_copy'] = [{'id': 'heading', 'role': 'title', 'text': '<faithful audience title>', 'source_refs': ['S1.answer']},
                                    {'id': 'message', 'role': 'takeaway', 'text': '<clear conclusion>', 'source_refs': ['S1.answer']}]
            page['content_map'] = {'S1.answer': {'destination': 'visible', 'carriers': [{'kind': 'copy', 'ref': 'message'}]}}
            if atomic:
                page['content_refs'] = ['C_assertion']
                page['reuse_refs'] = []
                page['figure_sources'] = {'<selected inspected asset ID>': {'source_figure': '<exact figure/panel ID>'}}
                for item in page['display_copy']: item['source_refs'] = ['C_assertion']
                page['content_map'] = {'C_assertion': {'destination': 'visible', 'carriers': [{'kind': 'copy', 'ref': 'message'}]}}
        path = work/'page_design_prompt.json'
        if not path.is_file() or read(path) != prompt:
            write(path, prompt)
        # The subagent brief is prose, not state: it is handed to the design subagent verbatim.
        task = work/'page_design_task.md'
        text = design_task(prompt)
        if not task.is_file() or task.read_text(encoding='utf-8') != text:
            task.write_text(text, encoding='utf-8')
        return [work/'page_design_prompt.json', work/'page_design_task.md']
    if stage == 'page_review':
        from .content_review import prepare
        return prepare(work)
    if stage == 'page_scene':
        from .page_scene_binding import prepare
        return prepare(work, request)
    if stage == 'scientific_review':
        from .science_review import prepare
        return prepare(work, request)
    if stage == 'design':
        compiler('visual-prompt', out, '--ir', work/'deck_ir.json', '--out', work/'visual_prompt.json',
                 '--requirements', request.get('requirements', ''))
        return [work/'visual_prompt.json']
    if stage == 'build':
        if request.get('page_mode', 'deck_ir') == 'page_scene':
            from .page_scene_build import build as build_scene, SceneBuildError
            try:
                return build_scene(work, out, request)
            except SceneBuildError as error:
                failure = Failure(error.code, str(error), 'replan', 'page_scene')
                failure.issues = error.issues
                raise failure from error
        if not shutil.which('officecli'):
            raise Failure('OFFICECLI_MISSING', 'Install OfficeCLI >=1.0.152 and add it to PATH.')
        ir = work/'deck_ir.json'
        from deck_compiler.visual_planner import pending_design
        pending = pending_design(read(ir))
        if pending['academic_design_required'] or pending['slide_ids']:
            compiler('apply-visual-plan', out, '--ir', ir, '--proposal', work/'visual_proposal.json', '--out', work/'designed.deck_ir.json')
            ir = work/'designed.deck_ir.json'
        compiler('build', out, '--ir', ir, '--out', out/'build', '--skip-native',
                 '--explain-viz-mode', request.get('explain_viz_mode', 'auto'), timeout=540)
        qa = read(out/'build/qa_report.json')
        if qa['counts']['FAIL']:
            first = next(i for i in qa['items'] if i['severity'] == 'FAIL')
            raise classify(first['rule'], first['message'], 'build')
        if qa.get('artifact_sha256') != sha(out/'build/candidate.pptx') or qa.get('artifact_sha256') != sha(out/'build/staging.pptx'):
            raise Failure('CANDIDATE_EVIDENCE_STALE', 'Candidate / staging / QA hashes disagree.', 'review_required', 'build')
        layout = read(out/'build/layout.json')
        extra = [Path(asset['path']) for asset in layout['assets'].values()]
        extra += [Path(e['contract']['font_file']) for slide in layout['slides'] for e in slide['elements'] if e.get('contract')]
        return [*[out/'build'/name for name in ('candidate.pptx', 'staging.pptx', 'qa_report.json', 'layout_feedback.json', 'layout.json')],
                *[out/'build'/name for name in ('explain_viz.json', 'explain_viz.source.deck_ir.json')
                  if (out/'build'/name).is_file()], *extra]
    raise Failure('STAGE_UNSUPPORTED', f'Unknown adapter {stage}')
