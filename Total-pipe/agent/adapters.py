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

from . import ROOT, COMPONENT
from .state import read, write, sha, resources

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
    log = Path(out)/'logs'/(name+'.json')
    try:
        process = run_process([str(a) for a in argv], cwd, timeout)
    except FileNotFoundError as error:
        code = 'OFFICECLI_MISSING' if 'officecli' in str(argv[0]).lower() else 'EXECUTABLE_MISSING'
        raise Failure(code, f'Executable unavailable: {argv[0]}') from error
    except subprocess.TimeoutExpired as error:
        write(log, {'code': 'COMPONENT_TIMEOUT', 'message': redact(str(error))})
        raise Failure('COMPONENT_TIMEOUT', 'Component timed out; its process was terminated. Retry or inspect the log.', log=str(log)) from error
    stdout, stderr = redact(process.stdout), redact(process.stderr)
    write(log, {'argv': [redact(str(a)) for a in argv], 'exit_code': process.returncode,
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


def check_design(value, story, evidence):
    """Refuse a page design that cannot be traced back to the Story or the evidence."""
    from deck_compiler.design import validate_design
    problems = validate_design(value, story, evidence)
    if problems:
        raise Failure('PAGE_DESIGN_INVALID', ' '.join(problems[:6]),
                      'author_artifact', 'page_design', str(problems))


DESIGN_MARKER = ' A page design is approved.'


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
    from deck_compiler.design import capabilities, summary
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
    if prompt.get('page_design') == pages and DESIGN_MARKER in prompt.get('instructions', ''):
        return path
    prompt['page_design'] = pages
    prompt['design_forms'] = capabilities()['forms']
    prompt['design_devices'] = capabilities()['art_direction']['devices']
    instructions = prompt.get('instructions', '').split(DESIGN_MARKER)[0]
    prompt['instructions'] = instructions+DESIGN_MARKER+(
        ' Realize it page by page: same pages, same claims, same form and anchor for each, and the devices '
        'each page names. A device is a decision, not a suggestion: **…** / ==…== go into the text that '
        'carries the claim, figure_refs carry source_label, a panel group is built as layout_tree panels '
        'whose frame carries title_fill and title_band="chip", a takeaway-frame becomes '
        'presentation.takeaway_frame, and the deck devices (sections, agenda, footer, page-numbers) go into '
        'the deck presentation. The compiler writes the mechanical ones for you and degrades them instead of '
        'failing; the panel groups are yours to build. Do not redesign, drop an item or move one to another '
        'page. If a form cannot be realized at the required font floors, split that page and keep every item; '
        'never delete content or shrink below the type scale. Set presentation.visual_style to the pack that '
        'fits the venue.')
    # With an approved design the RPA plan and the raw content model are no longer inputs: the pages,
    # their claims and their items are the design. Carrying them anyway made the prompt 1.6 MB, which
    # is the same "too big to read" failure the design prompt just fixed.
    trimmed = 'ir_prompt_designed.json trimmed to the design, story, evidence and compiler contracts'
    prompt = {key: value for key, value in prompt.items()
              if key not in ('workflow', 'rpa_input', 'content_model', 'deck_plan', 'unplanned_briefs')}
    prompt['trimmed_inputs'] = trimmed
    # What the IR author still needs and the cut inputs used to carry: the Story (speaker notes and
    # purpose), the evidence text behind each id, and the figure panels it may place.
    try:
        prompt['story'] = read(work/'story_plan.json')
    except (OSError, ValueError):
        pass
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
    write(path, prompt)
    (work/'deck_ir_task.md').write_text(ir_task(prompt), encoding='utf-8')
    return path


def _digit_runs(text):
    return set(re.findall(r'\d+(?:\.\d+)?', str(text)))


def check_design_realization(value, design):
    """An approved page design fixes the structure; the IR must realize it, not re-decide it."""
    pages = design.get('pages') or []
    if len(value['slides']) != len(pages):
        raise Failure('DESIGN_REALIZATION_FAILED',
                      f'The approved design has {len(pages)} pages but the IR has {len(value["slides"])}. '
                      'Realize one IR page per designed page; split inside a page instead of adding or '
                      'dropping pages.', 'author_artifact', 'deck_ir')
    for index, (slide, page) in enumerate(zip(value['slides'], pages), 1):
        semantic = slide['semantic']
        cited = set(semantic.get('evidence_refs') or [])
        needed = {ref for item in page.get('items') or [] for ref in item.get('evidence') or []}
        if not needed <= cited:
            raise Failure('DESIGN_REALIZATION_FAILED',
                          f'Page {index} ({page.get("id")}) must keep evidence {sorted(needed-cited)} '
                          'from the approved design.', 'author_artifact', 'deck_ir')
        visible = semantic.get('title', '')+' '+semantic.get('takeaway', '')+' '+semantic.get('speaker_notes', '')
        for block in slide['composition'].get('blocks') or []:
            visible += ' '+str(block.get('text', ''))+str(block.get('label', ''))
        for figure in slide['composition'].get('figure_refs') or []:
            visible += ' '+str(figure.get('caption', ''))
        for table in slide['composition'].get('tables') or []:
            for cell in table.get('cells') or []:
                visible += ' '+str(cell.get('text', ''))
        runs = _digit_runs(visible)
        for item in page.get('items') or []:
            if item.get('kind') == 'formula':
                continue  # a definition is rendered as written; its constants are not measurements
            missing = _digit_runs(item.get('text', ''))-runs
            if missing:
                raise Failure('DESIGN_REALIZATION_FAILED',
                              f'Page {index} ({page.get("id")}) lost the numbers {sorted(missing)} that the '
                              f'approved design placed there.', 'author_artifact', 'deck_ir')


def check_ir(value, normalized=None, supplement='off', design=None):
    from deck_compiler.ir import validate
    original = copy.deepcopy(value)
    value = normalize_authoring_ir(value)
    mode = supplement if supplement in ('off', 'inline', 'pages', 'both') else 'off'
    has_supplement = False
    has_supplement_page = False
    for slide, supplements, blocks in _supplement_blocks(value):
        has_supplement = has_supplement or bool(supplements)
        has_supplement_page = has_supplement_page or (bool(blocks) and len(supplements) == len(blocks))
    if has_supplement and mode == 'off':
        raise Failure('SUPPLEMENT_NOT_ENABLED',
                      'This job did not enable supplement content; remove the supplement blocks/pages or start a job with supplement=inline/pages/both.',
                      'author_artifact', 'deck_ir')
    if has_supplement_page and mode == 'inline':
        raise Failure('SUPPLEMENT_PAGE_NOT_ENABLED',
                      'supplement=inline only allows blocks on existing pages; start with supplement=pages/both for standalone supplement pages.',
                      'author_artifact', 'deck_ir')
    failures = [i for i in validate(value) if i['severity'] == 'FAIL']
    if failures:
        item = failures[0]
        failure = classify(item['rule'], item['message'], 'deck_ir')
        if failure.action == 'resolve_dependency':
            failure.action, failure.target = 'author_artifact', 'deck_ir'
        raise failure
    if normalized:
        def texts(value):
            if isinstance(value, dict):
                return '\n'.join(texts(v) if isinstance(v, (list, dict)) else str(v)
                    for k, v in value.items() if isinstance(v, (dict, list)) or k in
                    ('text', 'title', 'body', 'label', 'takeaway', 'speaker_notes'))
            if isinstance(value, list):
                return '\n'.join(texts(v) if isinstance(v, (dict, list)) else str(v) for v in value)
            return ''
        # Content-loss compares the author's visible text before scientific
        # notation is rewritten into $...$ math; otherwise a brief number such
        # as 1.2×10^-3 would no longer match its normalized LaTeX form.
        corpus = ''.join(texts(original.get('slides', []) if isinstance(original, dict) else []).split())
        if design:
            # The approved design already accounts for every Story item; the IR is checked against
            # the design instead of against the verbatim brief text it was allowed to rewrite.
            check_design_realization(value, design)
            from deck_compiler.art_direction import check as check_devices
            missing = check_devices(value, design)
            if missing:
                page, message = missing[0]
                raise Failure('DESIGN_REALIZATION_FAILED',
                              f'{page or "deck"}: the approved design chose a device this IR does not carry — '
                              f'{message}. Devices are decisions; the page must show them.', 'author_artifact', 'deck_ir')
        elif len(value['slides']) < len(normalized.get('slide_briefs', [])):
            raise classify('CONTENT_LOSS', 'IR has fewer pages than the original complete briefs; revise Story explicitly before merging pages.', 'deck_ir')
        known = {entry.get('id', entry.get('evidence_id')) for entry in normalized.get('evidence', [])}
        if known and any(ref not in known for page in value['slides'] for ref in page['semantic']['evidence_refs']):
            raise classify('CONTENT_LOSS', 'IR evidence_refs must resolve to the original normalized evidence store.', 'deck_ir')
        if not design:
            for brief in normalized.get('slide_briefs', []):
                for content in [brief.get('body', ''), *brief.get('key_points', [])]:
                    if content and ''.join(str(content).split()) not in corpus:
                        raise classify('CONTENT_LOSS', 'IR must retain each complete brief body and key_point in page text or speaker notes.', 'deck_ir')
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
                    if not isinstance(graphic, dict) or graphic.get('type') != 'process' \
                            or graphic.get('layout') != 'compact':
                        continue
                    nodes = [node for node in graphic.get('nodes', []) if isinstance(node, dict)]
                    if len(nodes) < node_count:
                        continue
                    titles = ''.join(''.join(str(node.get(key, '')).split())
                                     for node in nodes for key in ('title', 'body'))
                    if all(''.join(item.split()) in titles for item in items):
                        carried = True
                        break
                if carried:
                    break
            if not carried:
                raise classify(
                    'CONTENT_LOSS',
                    f'Story declared a {node_count}-step compact process, but the IR has no type=process/'
                    'layout=compact graphic carrying every step; replace the RPA three-slot placeholder.',
                    'deck_ir')
    if normalized and mode != 'off':
        from .supplement import leak_messages
        leaks = leak_messages(value, normalized)
        if leaks:
            raise Failure('SUPPLEMENT_PAPER_LEAK', leaks[0], 'author_artifact', 'deck_ir')


def persist_ir(value, source, destination):
    """Write the canonical IR with asset paths resolved against the file it was authored in."""
    for asset in value.get('assets', {}).values():
        if not Path(asset['path']).is_absolute():
            asset['path'] = str((Path(source).parent/asset['path']).resolve())
    for key in ('font_file', 'bold_font_file', 'background_image'):
        ref = value.get('theme', {}).get(key)
        if ref and not Path(ref).is_absolute() and (Path(source).parent/ref).is_file():
            value['theme'][key] = str((Path(source).parent/ref).resolve())
    write(destination, value)
    return destination


def import_ir(source, destination, supplement='off'):
    value = read(source)
    check_ir(value, supplement=supplement)
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


DESIGN_INSTRUCTIONS = (
    'You are designing a research talk, not filling a template. The room comes before the page: the '
    'request names a presentation type and a brief, and between them they say who is in the room, what '
    'they already know, how long the talk runs and how long one page stays on screen, and whether the '
    'page is spoken to or read on its own. Settle that first and write it down as deck.setting. It '
    'decides density and page shape, not decoration: a page that stays up while the room argues has to '
    'give the eye something to hold, and a page meant to be read alone cannot depend on the voice. Do '
    'not import the habits of a different room. You have the Story (what the talk '
    'argues), the briefs (one unit of content each), the evidence behind them, the figure panels that '
    'exist, and the catalogue of forms and devices this compiler can actually draw. Everything you '
    'name is drawn natively and stays editable in PowerPoint. '
    'Read the Story first, then decide the walk-through: what a listener should believe after page 1, '
    'what each following page adds, and where the deck lands. One page argues one thing; give it the '
    'form whose job matches that thing — a table when the content is parallel values, a figure when '
    'the paper figure is the argument, a formula when the page is about an operator, a flow when the '
    'order carries meaning, columns when three limits stand side by side. A page with no figure, '
    'table or formula still needs a shape: one statement at display size when the page is a single '
    'claim, two or three short groups side by side when the material is parallel, numbered points '
    'when it is a list. Stacked blocks are the fallback for a page that really is one or two bare '
    'lines with nothing to group; if you can name the groups, do not stack them. '
    'Then make the page read: a labelled group when it carries two or three parallel groups, a boxed '
    'takeaway when the page ends in a claim, the phrase that carries the claim (marked in the item '
    'text itself), the provenance of a paper figure, a numbered rail for an ordered process. The '
    'devices list says what each one buys and how it degrades if the page cannot hold it — a device '
    'never costs you the build, so choose the page you want rather than the page you are sure of. A '
    'page that genuinely is one statement needs no device; say why in its rationale. '
    'Deck-level devices describe the deck as a whole: sections and a contents page when the talk is '
    'long enough to need a map, a footer line for the venue, page numbers unless they would be wrong. '
    'What happens after you: the pipeline checks that every Story answer and key point appears '
    'exactly once across the pages, that each item cites evidence containing its numbers, and that '
    'each form matches its anchor. Everything else — where the eye lands, how much air a page gets, '
    'which words are marked — is your judgement. Do not write layout coordinates and do not write '
    'Deck IR: this design is the thing the next stage realizes.'
)


def design_task(prompt=None):
    """The brief an orchestrator hands to a design subagent, at the same level as the story planner."""
    figures = len((prompt or {}).get('figures') or [])
    briefs = len((prompt or {}).get('briefs') or [])
    return f"""# 页面设计任务（子代理）

你是这次 deck 的页面设计师。你决定这场报告按什么顺序讲、每一页靠什么成立。

- **输入**：`work/page_design_prompt.json`。里面是 Story（论证骨架）、{briefs} 条 briefs（每条要讲的内容）、
  证据原文、{figures} 张可用的论文图，以及这套编译器能画的**形式**（forms）和**设备**（devices）清单，
  每项都写了它买来什么、放不下时怎么退化。
- **输出**：`work/page_design.json`，结构照输入里的 `shape`。
- **先看场合，再排页**：输入里的 `room` 是这场报告的场合与对象。先从 `occasions` 里选一个键写进
  `setting.occasion`：`group-meeting`（组会）、`research-report`（会议/答辩）、`research-sharing`
  （文献分享）、`lecture`（讲课）、`commercial`（商业路演）。每个键都写了听众、时长、讲者口述还是听众
  自读、以及“一页要扛住什么、别出现什么”。再写 `setting.audience`（听众是谁、已经知道什么）和
  `setting.reading`（spoken/read/mixed）。后面的密度、文字量和页面形态都按它来；同一篇论文在这五种
  场合里应该长得不一样。
- **你的判断范围**：一页放哪条内容、用什么形式、要不要标签组/结论框/强调/出处/目录，都是你定。
  设备的退化写在清单里，用了不会让构建失败；一页确实不需要设备时，在 rationale 里写一句为什么。
- **写完自查**：JSON 合法；每条 Story 的 answer / key_point / ending 恰好落在一页上；每个 item 引了
  含它数字的 evidence；每页的 form 与 anchor 对得上。
- **不要做**：不要写页面坐标，不要写 Deck IR，不要去读管线源码或别的 deck。

做完用几句话说明：几页、每页的形式、以及你在哪几处做了取舍。"""


def ir_task(prompt=None):
    """The brief an orchestrator hands to the IR subagent once the design is approved."""
    pages = ((prompt or {}).get('page_design') or {}).get('pages') or []
    devices = ((prompt or {}).get('page_design') or {}).get('devices') or {}
    return f"""# Deck IR 实现任务（子代理）

设计已经批准。你要做的是**逐页实现**它，不是重新设计。

- **输入**：`work/ir_prompt_designed.json`。里面是设计表（{len(pages)} 页，含每页的 claim、form、
  anchor、items 与 devices）、Story、证据、可用 archetype / layout_tree 能力、类型尺度与 IR schema。
  篇级设备：{', '.join(devices) or '无'}。
- **输出**：`work/deck_ir.json`，符合 schema 的 canonical Deck IR（不要写作者简写）。
  图片资产从 `figures` 里选，`path` 相对 `workflow_root`；IR 的 `assets` 用绝对路径。
- **规则只有三条**：页序与页数照设计；每页语义（title / takeaway / evidence_refs）与设计一致；设计点名的
  设备都要真的落在页面上——文字标记、图注 source_label、结论框、panel 的 chip 标题、章节与目录。
  机械类设备编译器会在校验前替你写进 IR，结构类（panel-group）要你自己搭 panel。
- **写不出来时**：拆这一页或调整页面内的区域结构，不删内容、不缩字号、不改数字。空间确实不够时，
  把问题留在回复里（哪一页、缺多少），不要悄悄简化。

做完用几句话说明：页数、每页用的 archetype / layout_tree 结构、以及哪几页用了哪些设备。"""


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
        prompt['request'] = {key: request[key] for key in ('language', 'presentation_type', 'requirements')}
        prompt['instructions'] += ('\n\nPresentation request: '+json.dumps(prompt['request'], ensure_ascii=False)+
                                   '\nUse the requested presentation language while preserving scientific terms and uncertainty.')
        write(work/'story_prompt.json', prompt)
        return [work/'story_prompt.json']
    if stage == 'rpa':
        workflow = read(work/'evidence_pointer.json')['workflow']
        pwf_cli(out, workflow, '--story', work/'story_plan.json', '--out', work/'rpa_input.json')
        payload = read(work/'rpa_input.json')
        model = rpa('normalize-content', work/'rpa_input.json', out)
        write(work/'normalized_content.json', model)
        count = request.get('slide_count')
        if count and count != len(payload['slide_briefs']):
            raise Failure('SLIDE_COUNT_REPLAN', 'Requested slide_count differs from the complete Story briefs; revise Story instead of truncating briefs.', 'replan', 'story')
        write(work/'plan_input.json', {**payload, 'presentation_type': request['presentation_type']})
        plan = rpa('plan', work/'plan_input.json', out, allow_unplanned=True)
        write(work/'deck_plan.json', plan)
        unplanned = plan.get('unplanned_slide_briefs') or []
        if unplanned:
            # Story content is not shortened to satisfy RPA slots. The planned
            # pages stay RPA-owned; the unplanned briefs are handed to Deck IR,
            # where composite-research + layout_tree can split or reflow them.
            validation = {'status': 'partial', 'slides': [s.get('slide_id') for s in plan.get('slides', [])],
                          'unplanned_slide_briefs': unplanned}
        else:
            write(work/'validation_input.json', {'slides': plan['slides'], 'content_model': model})
            validation = rpa('validate-deck', work/'validation_input.json', out)
        write(work/'rpa_validation.json', validation)
        prompt = ir_prompt(read(workflow), payload, model, plan, request.get('supplement', 'off'))
        prompt['unplanned_briefs'] = unplanned
        if unplanned:
            prompt['instructions'] += (
                ' RPA left these briefs unplanned: '
                + ', '.join(str(brief.get('slide_id') or brief.get('title') or '?') for brief in unplanned)
                + '. Do NOT shorten the Story or drop content. Add one page per unplanned brief (or split a '
                  'planned page only when necessary), using composite-research + layout_tree so the complete '
                  'body/key_points and evidence fit. Keep the planned RPA pages. Every brief, key point and '
                  'evidence ref must appear exactly once across the deck; two thin briefs may share a page '
                  'when that reads better, so the page count may differ from the brief count.')
        prompt['workflow_root'] = str(Path(workflow).parent)
        prompt['request'] = {**{key: request[key] for key in ('language', 'presentation_type', 'requirements')},
                             'supplement': request.get('supplement', 'off')}
        write(work/'ir_prompt.json', prompt)
        return [work/name for name in ('rpa_input.json', 'normalized_content.json', 'deck_plan.json', 'rpa_validation.json', 'ir_prompt.json')]
    if stage == 'page_design':
        from deck_compiler.design import capabilities as design_capabilities, default_occasion
        from deck_compiler.style import capabilities as style_capabilities
        from deck_compiler.type_scale import constraints
        workflow = read(work/'evidence_pointer.json')['workflow']
        value = read(workflow)
        evidence = {entry['evidence_id']: entry['text'] for entry in value['evidence_registry']}
        # The extracted figure panels are the only visual inventory the design can name. The
        # workflow keeps them under `figure_assets_metadata`; reading `artifacts.figures` (which no
        # PDF run fills) is why earlier designs never saw a single image.
        figures = [{'asset_id': item.get('asset_id'),
                    'width': item.get('source_width_px'), 'height': item.get('source_height_px')}
                   for item in (value.get('artifacts') or {}).get('figure_assets_metadata') or []]
        content = read(work/'normalized_content.json')
        briefs = [{'id': brief.get('slide_id'), 'title': brief.get('title'),
                   'body': brief.get('body'), 'key_points': brief.get('key_points') or [],
                   'claims': brief.get('claims') or [],
                   'evidence': brief.get('evidence_ids') or []}
                  for brief in content.get('slide_briefs') or []]
        capabilities = design_capabilities()
        prompt = {
            'request': {key: request[key] for key in ('language', 'presentation_type', 'requirements')},
            'room': {
                'presentation_type': request['presentation_type'],
                'brief': request['requirements'],
                'default_occasion': default_occasion(request['presentation_type'], request['requirements']),
                'occasions': capabilities['occasions'],
                'settle_before_designing': [
                    'which occasion this is — the five keys in occasions, each with its own audience, '
                    'length, reading mode and what a page must survive in that room',
                    'in this room, who is listening and what do they already know — what must not be explained again',
                    'how long the talk runs and how long one page stays on screen before the next',
                    'is the page spoken to, read alone, or both — who carries the detail, the voice or the page',
                    'what the projector does to small type, thin rules and light greys at the back of the room',
                ],
                'why': 'The occasion is a constraint on density and page shape, not a template: a group '
                       'meeting, a conference talk, a journal club, a lecture and a pitch legitimately '
                       'produce different pages from the same paper. Write the chosen key into '
                       'setting.occasion; refine the audience in setting.audience.',
            },
            'story': read(work/'story_plan.json'),
            'briefs': briefs,
            'evidence': evidence,
            'figures': figures,
            'forms': capabilities['forms'],
            'rules': capabilities['rules'],
            'devices': capabilities['art_direction'],
            'roles': capabilities['roles'],
            'type_scale': constraints(),
            'visual_style': style_capabilities(),
            'shape': {
                'schema_version': '1.0', 'deck_id': '<string>',
                'setting': {'audience': '<who, and what they already know>',
                            'occasion': '<one key from occasions, e.g. group-meeting>',
                            'reading': 'spoken|read|mixed'},
                'devices': {'<deck device>': '<setting, e.g. sections/agenda/footer/page-numbers>'},
                'pages': [{'id': 'P1', 'from_story': ['S1'], 'role': 'setup',
                           'claim': '<one declarative sentence the page argues>',
                           'takeaway_from': '<optional: the Story item this page concludes with>',
                           'items': [{'id': 'p1-a', 'text': '<display text>',
                                      'source': 'S1.key_points[0]', 'evidence': ['EV0001'],
                                      'kind': 'text|formula|figure|graphic'}],
                           'form': '<one of forms>', 'anchor': {'kind': 'table', 'why': '<one line>'},
                           'devices': {'emphasis': ['<exact phrase on this page>'],
                                       'panel-group': ['<label>', '<label>']},
                           'rationale': '<why this form and these devices carry this claim>'}]},
            'instructions': DESIGN_INSTRUCTIONS,
        }
        write(work/'page_design_prompt.json', prompt)
        # The subagent brief is prose, not state: it is handed to the design subagent verbatim.
        (work/'page_design_task.md').write_text(design_task(prompt), encoding='utf-8')
        return [work/'page_design_prompt.json', work/'page_design_task.md']
    if stage == 'design':
        compiler('visual-prompt', out, '--ir', work/'deck_ir.json', '--out', work/'visual_prompt.json',
                 '--requirements', request.get('requirements', ''))
        return [work/'visual_prompt.json']
    if stage == 'build':
        if not shutil.which('officecli'):
            raise Failure('OFFICECLI_MISSING', 'Install OfficeCLI >=1.0.152 and add it to PATH.')
        ir = work/'deck_ir.json'
        from deck_compiler.visual_planner import pending_design
        pending = pending_design(read(ir))
        if pending['academic_design_required'] or pending['slide_ids']:
            compiler('apply-visual-plan', out, '--ir', ir, '--proposal', work/'visual_proposal.json', '--out', work/'designed.deck_ir.json')
            ir = work/'designed.deck_ir.json'
        compiler('build', out, '--ir', ir, '--out', out/'build', '--skip-native', timeout=540)
        qa = read(out/'build/qa_report.json')
        if qa['counts']['FAIL']:
            first = next(i for i in qa['items'] if i['severity'] == 'FAIL')
            raise classify(first['rule'], first['message'], 'build')
        if qa.get('artifact_sha256') != sha(out/'build/candidate.pptx') or qa.get('artifact_sha256') != sha(out/'build/staging.pptx'):
            raise Failure('CANDIDATE_EVIDENCE_STALE', 'Candidate / staging / QA hashes disagree.', 'review_required', 'build')
        layout = read(out/'build/layout.json')
        extra = [Path(asset['path']) for asset in layout['assets'].values()]
        extra += [Path(e['contract']['font_file']) for slide in layout['slides'] for e in slide['elements'] if e.get('contract')]
        return [*[out/'build'/name for name in ('candidate.pptx', 'staging.pptx', 'qa_report.json', 'layout_feedback.json', 'layout.json')], *extra]
    raise Failure('STAGE_UNSUPPORTED', f'Unknown adapter {stage}')
