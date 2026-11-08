"""Bind an authored PageScene to the approved page design and Story evidence.

PageScene is deliberately a *page geometry* contract, not a second scientific
authority.  A scene may use literal display copy only when it is byte-for-byte
the approved copy; otherwise it must use ``copy_ref`` keys from this binder.
The binder also carries the design's evidence anchors and rejects new numeric
claims that are absent from the approved design / Story / evidence corpus.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from .requests import prompt_request
from .state import digest, read, write

SCHEMA = Path(__file__).with_name('schemas') / 'page-scene.schema.json'


class SceneBindingError(ValueError):
    def __init__(self, code, message, issues=None):
        super().__init__(message)
        self.code = code
        self.issues = list(issues or [])


def _page_copy(page):
    copies = page.get('display_copy')
    return [item for item in copies if isinstance(item, dict)] if isinstance(copies, list) else []


def copy_bindings(design):
    """Return copy_ref -> approved text, including page-scoped aliases.

    Bare ids are exposed only when globally unique: a design may legitimately
    reuse ``b1`` on several pages, and silently picking one would put the wrong
    sentence on a slide.
    """
    result, seen = {}, {}
    pages = design.get('pages') if isinstance(design, dict) else []
    for page in pages or []:
        page_id = page.get('id')
        # Legacy 1.0 designs keep title/take on the page instead of display_copy.
        if isinstance(page.get('title'), str) and page['title']:
            result.setdefault(f'{page_id}.title', page['title'])
        if isinstance(page.get('take'), str) and page['take']:
            result.setdefault(f'{page_id}.take', page['take'])
        for item in _page_copy(page):
            copy_id, text = item.get('id'), item.get('text')
            if not isinstance(copy_id, str) or not isinstance(text, str):
                continue
            result[f'{page_id}.{copy_id}'] = text
            if item.get('role') == 'title':
                result[f'{page_id}.title'] = text
            elif item.get('role') == 'takeaway':
                result[f'{page_id}.take'] = text
            seen.setdefault(copy_id, []).append(text)
    for copy_id, texts in seen.items():
        if len(set(texts)) == 1:
            result[copy_id] = texts[0]
    return result


def page_copy_catalog(design):
    """Machine-readable page copy for the page-scene prompt."""
    catalog = []
    for page in (design.get('pages') if isinstance(design, dict) else []) or []:
        copies = []
        evidence = []
        for item in page.get('items') or []:
            if isinstance(item, dict):
                evidence += [ref for ref in item.get('evidence') or [] if isinstance(ref, str)]
        for item in page.get('context_items') or []:
            if isinstance(item, dict):
                evidence += [ref for ref in item.get('evidence') or [] if isinstance(ref, str)]
        for item in _page_copy(page):
            copies.append({key: item.get(key) for key in ('id', 'role', 'text', 'source_refs', 'basis')
                           if item.get(key) is not None})
        catalog.append({
            'id': page.get('id'),
            'content_refs': list(page.get('content_refs') or []),
            'reuse_refs': list(page.get('reuse_refs') or []),
            'title': page.get('title'),
            'display_copy': copies,
            'evidence_refs': sorted(set(evidence)),
            'figures': list(page.get('figures') or []),
            'figure_sources': page.get('figure_sources') or {},
        })
    return catalog


def _approved_title(page, copies):
    for item in copies:
        if item.get('role') == 'title':
            return item.get('text')
    return page.get('title') or ''


def _approved_take(page, copies):
    for item in copies:
        if item.get('role') == 'takeaway':
            return item.get('text')
    return page.get('take') or ''


def _walk_objects(objects):
    for obj in objects or []:
        if not isinstance(obj, dict):
            continue
        yield obj
        if obj.get('type') == 'group':
            yield from _walk_objects(obj.get('children') or [])


def _visible_texts(page):
    def page_field(value):
        return value if isinstance(value, str) else ''
    yield page_field(page.get('title'))
    yield page_field(page.get('take'))
    for obj in _walk_objects(page.get('objects')):
        if obj.get('type') == 'list':
            for item in obj.get('items') or []:
                if isinstance(item, dict):
                    yield page_field(item.get('text'))
        elif obj.get('type') in ('text', 'shape'):
            yield page_field(obj.get('text'))
        elif obj.get('type') == 'table':
            for row in obj.get('rows') or []:
                for cell in row if isinstance(row, list) else []:
                    yield page_field(str(cell))


def _copy_refs(page):
    refs = []
    if page.get('title_ref'):
        refs.append(('title', page['title_ref']))
    if page.get('take_ref'):
        refs.append(('take', page['take_ref']))
    for obj in _walk_objects(page.get('objects')):
        if obj.get('copy_ref'):
            refs.append((obj.get('id', obj.get('type')), obj['copy_ref']))
        if obj.get('type') == 'list':
            for item in obj.get('items') or []:
                if isinstance(item, dict) and item.get('copy_ref'):
                    refs.append((item.get('id', 'list-item'), item['copy_ref']))
    return refs


def _numbers(text):
    return set(re.findall(r'(?<![A-Za-z])\d+(?:\.\d+)?', str(text)))


def _corpus(design, story, evidence):
    parts = []
    for page in (design.get('pages') if isinstance(design, dict) else []) or []:
        parts.append(str(page.get('id') or ''))
        parts.append(str(page.get('title') or ''))
        parts.append(str(page.get('figures') or []))
        parts.append(str(page.get('figure_sources') or {}))
        for item in page.get('items') or []:
            if isinstance(item, dict):
                parts.append(str(item.get('text') or ''))
        for item in page.get('context_items') or []:
            if isinstance(item, dict):
                parts.append(str(item.get('text') or ''))
        for item in _page_copy(page):
            parts.append(str(item.get('text') or ''))
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('text', 'answer', 'question', 'takeaway', 'limitation', 'title'):
                    parts.append(str(item))
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(story)
    parts.extend(str(value) for value in (evidence or {}).values())
    return '\n'.join(parts)


def _resolve_field(page, key, bindings):
    ref = page.get(key + '_ref')
    if ref:
        if ref not in bindings:
            raise SceneBindingError('PAGE_SCENE_COPY_UNRESOLVED',
                                    f'{page.get("id")}: unresolved {key}_ref {ref}')
        return bindings[ref]
    return page.get(key) or ''


def image_paths(scene):
    paths = []
    for page in scene.get('pages') or []:
        for obj in _walk_objects(page.get('objects')):
            if obj.get('type') == 'image' and obj.get('path'):
                paths.append(Path(obj['path']))
    return paths


def _image_path(obj, base):
    value = obj.get('path')
    if not isinstance(value, str) or not value.strip():
        raise SceneBindingError('PAGE_SCENE_IMAGE_MISSING',
                                f'{obj.get("id", "image")}: image requires a non-empty path')
    path = Path(value)
    if not path.is_absolute():
        path = Path(base) / path
    return str(path.resolve())


def _collect_used(page, bindings):
    used = set()
    for _, ref in _copy_refs(page):
        if ref in bindings:
            used.add(ref)
    # Literal approved copy also counts, but only after exact comparison.
    visible = [text for text in _visible_texts(page) if text]
    for ref, text in bindings.items():
        if text and text in visible:
            used.add(ref)
    return used


def _expected_carriers(page):
    """Approved copy references that must be visibly realized on this page."""
    required = set()
    content_map = page.get('content_map')
    if not isinstance(content_map, dict):
        return required
    for mapping in content_map.values():
        if not isinstance(mapping, dict) or mapping.get('destination') != 'visible':
            continue
        for carrier in mapping.get('carriers') or []:
            if isinstance(carrier, dict) and carrier.get('kind') == 'copy' and carrier.get('ref'):
                required.add(carrier['ref'])
    return required


def bind(value, work, request=None, source_dir=None):
    """Validate and canonicalize a PageScene against the approved page design.

    Returns ``(canonical_scene, report)``.  Relative image paths are resolved
    against ``source_dir`` (normally the submitted artifact's directory) before
    the canonical scene is written to ``work/page_scene.json`` by the caller.
    """
    from .adapters import load_design, Failure

    work = Path(work)
    try:
        design = load_design(work)
    except Failure as error:
        raise SceneBindingError(error.code, str(error)) from error
    if not isinstance(design, dict) or not design.get('pages'):
        raise SceneBindingError('PAGE_SCENE_DESIGN_REQUIRED',
                                'PageScene requires an approved page_design.json with pages.')
    story = read(work / 'story_plan.json') if (work / 'story_plan.json').is_file() else {}
    pointer = work / 'evidence_pointer.json'
    evidence = {}
    if pointer.is_file():
        try:
            flow = read(read(pointer)['workflow'])
            evidence = {entry['evidence_id']: entry.get('text', '')
                        for entry in flow.get('evidence_registry') or []}
        except (OSError, ValueError, KeyError, TypeError):
            evidence = {}
    bindings = copy_bindings(design)
    design_pages = design['pages']
    supplement = (request or {}).get('supplement', 'off')
    if supplement == 'off':
        for page in design_pages:
            if any(item.get('basis') == 'supplement' for item in _page_copy(page)):
                raise SceneBindingError(
                    'PAGE_SCENE_SUPPLEMENT_NOT_ENABLED',
                    f'{page.get("id")}: the approved design contains supplement copy, '
                    'but this job did not enable supplement content.')
    if not isinstance(value, dict) or value.get('schema_version') != '0.1':
        raise SceneBindingError('PAGE_SCENE_INVALID', 'PageScene must be a 0.1 JSON object.')
    pages = value.get('pages')
    if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages):
        raise SceneBindingError('PAGE_SCENE_INVALID', 'PageScene pages must be a list of objects.')
    if len(pages) != len(design_pages):
        raise SceneBindingError(
            'PAGE_SCENE_PAGE_COUNT',
            f'PageScene has {len(pages)} pages; approved design has {len(design_pages)}.')
    known_numbers = _numbers(_corpus(design, story, evidence))
    report = {'schema_version': '1.0', 'design_sha256': digest(design),
              'copy_refs': len(bindings), 'pages': [], 'issues': []}
    canonical = copy.deepcopy(value)
    canonical['bindings'] = bindings
    canonical['provenance'] = {
        'schema_version': '1.0',
        'design_sha256': digest(design),
        'story_sha256': digest(story),
        'evidence_count': len(evidence),
        'mode': 'page_design_binding',
    }
    for index, (page, approved) in enumerate(zip(pages, design_pages), 1):
        pid = approved.get('id') or page.get('id')
        if page.get('id') != pid:
            raise SceneBindingError(
                'PAGE_SCENE_PAGE_ORDER',
                f'Page {index} is {page.get("id")!r}; approved design expects {pid!r}.')
        copies = _page_copy(approved)
        require = _expected_carriers(approved)
        approved_title, approved_take = _approved_title(approved, copies), _approved_take(approved, copies)
        title = _resolve_field(page, 'title', bindings)
        take = _resolve_field(page, 'take', bindings)
        if approved_title and title != approved_title:
            raise SceneBindingError(
                'PAGE_SCENE_COPY_DRIFT',
                f'{pid}: title differs from approved display_copy. Use title_ref '
                f'{pid}.title (or exact approved text).')
        if approved_take and take != approved_take:
            raise SceneBindingError(
                'PAGE_SCENE_COPY_DRIFT',
                f'{pid}: take differs from approved display_copy. Use take_ref '
                f'{pid}.take (or exact approved text).')
        for label, ref in _copy_refs(page):
            if ref not in bindings:
                raise SceneBindingError('PAGE_SCENE_COPY_UNRESOLVED',
                                        f'{pid}/{label}: unresolved copy_ref {ref}')
        used = _collect_used(page, bindings)
        # A page-scoped alias such as P1.title refers to the approved copy id
        # p1-title; count either spelling for the visibility obligation.
        aliases = {item.get('id'): f'{pid}.{item.get("id")}' for item in copies}
        for item in copies:
            if item.get('role') == 'title':
                aliases[item.get('id')] = f'{pid}.title'
            elif item.get('role') == 'takeaway':
                aliases[item.get('id')] = f'{pid}.take'
        missing = sorted(ref for ref in require
                         if ref not in used and aliases.get(ref) not in used)
        if missing:
            raise SceneBindingError(
                'PAGE_SCENE_COPY_MISSING',
                f'{pid}: approved visible copy is not realized: {", ".join(missing)}')
        evidence_refs = page.get('evidence_refs')
        approved_evidence = set()
        for item in [*(approved.get('items') or []), *(approved.get('context_items') or [])]:
            if isinstance(item, dict):
                approved_evidence.update(item.get('evidence') or [])
        if evidence_refs is None:
            evidence_refs = sorted(approved_evidence)
        elif not isinstance(evidence_refs, list) or any(not isinstance(ref, str) for ref in evidence_refs):
            raise SceneBindingError('PAGE_SCENE_EVIDENCE_INVALID',
                                    f'{pid}: evidence_refs must be a list of strings.')
        elif not set(evidence_refs) <= approved_evidence:
            raise SceneBindingError(
                'PAGE_SCENE_EVIDENCE_DRIFT',
                f'{pid}: evidence_refs not owned by this designed page: '
                f'{sorted(set(evidence_refs) - approved_evidence)}')
        else:
            evidence_refs = list(evidence_refs)
        # Only visible prose can introduce a new numeric claim.  Source labels
        # and figure identities are provenance, not scientific assertions.
        visible = '\n'.join(text for text in _visible_texts(page) if text)
        unknown = sorted(_numbers(visible) - known_numbers)
        if unknown:
            raise SceneBindingError(
                'PAGE_SCENE_NUMBER_UNBOUND',
                f'{pid}: visible numbers absent from approved design/Story/evidence: '
                f'{", ".join(unknown)}')
        for obj in _walk_objects(page.get('objects')):
            if obj.get('type') == 'image':
                obj['path'] = _image_path(obj, Path(source_dir) if source_dir else work)
        canonical_page = canonical['pages'][index - 1]
        canonical_page['title'] = title
        canonical_page['take'] = take
        if approved_title:
            canonical_page['title_ref'] = f'{pid}.title'
        else:
            canonical_page.pop('title_ref', None)
        if approved_take:
            canonical_page['take_ref'] = f'{pid}.take'
        else:
            canonical_page.pop('take_ref', None)
        canonical_page['evidence_refs'] = evidence_refs
        report['pages'].append({'id': pid, 'title': title, 'take': take,
                                'required_copy': sorted(require), 'used_copy': sorted(used),
                                'evidence_refs': evidence_refs})
    return canonical, report


def prepare(work, request):
    """Write the PageScene authoring prompt and task; no scientific content."""
    from .adapters import load_design
    work = Path(work)
    design = load_design(work)
    if not isinstance(design, dict) or not design.get('pages'):
        raise SceneBindingError('PAGE_SCENE_DESIGN_REQUIRED',
                                'Approve page_design before preparing PageScene.')
    story = read(work / 'story_plan.json') if (work / 'story_plan.json').is_file() else {}
    pointer = work / 'evidence_pointer.json'
    evidence, figures, workflow_root = {}, [], None
    if pointer.is_file():
        try:
            workflow_path = read(pointer)['workflow']
            workflow_root = str(Path(workflow_path).parent)
            flow = read(workflow_path)
            evidence = {entry['evidence_id']: entry.get('text', '')
                        for entry in flow.get('evidence_registry') or []}
            figures = [{'asset_id': item.get('asset_id'), 'path': item.get('path'),
                        'width': item.get('source_width_px'), 'height': item.get('source_height_px')}
                       for item in (flow.get('artifacts') or {}).get('figure_assets_metadata') or []]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    catalog = page_copy_catalog(design)
    bindings = copy_bindings(design)
    prompt = {
        'schema_path': str(SCHEMA),
        'request': prompt_request(request or {}),
        'page_design': design,
        'page_catalog': catalog,
        'copy_bindings': bindings,
        'story': story,
        'evidence': evidence,
        'figures': figures,
        'workflow_root': workflow_root,
        'page_size': {'width': 13.333, 'height': 7.5, 'unit': 'inches'},
        'instructions': PAGE_SCENE_INSTRUCTIONS,
    }
    prompt_path = work / 'page_scene_prompt.json'
    write(prompt_path, prompt)
    task = work / 'page_scene_task.md'
    text = scene_task(prompt)
    task.write_text(text, encoding='utf-8')
    return [prompt_path, task]


PAGE_SCENE_INSTRUCTIONS = (
    'Author a PageScene 0.1 JSON. The approved page_design owns audience copy; the Story owns '
    'scientific meaning and evidence. Use title_ref and take_ref (and object copy_ref) from '
    'copy_bindings for approved sentences; a literal title/take/body is accepted only when it is '
    'exactly the approved text. Do not paraphrase, add claims, invent numbers, delete conditions, '
    'or move a claim to another page. One idea per page: a main visual plus at most three short '
    'conclusions. Every object needs an explicit box in inches [x,y,w,h]; no auto-layout. The renderer '
    'draws the section chip, title and highlighted takeaway band automatically; set section as '
    '"NN · LABEL" and use title_ref/take_ref plus optional title_emphasis/take_emphasis. In the body, '
    'build two to four labelled zones rather than one full-width bullet stack: a visual, a short '
    'readout, and an implication. Use chips/shapes for subheads and large numbers for key metrics. '
    'On a figure page, name the panels, axes/conditions and feature to look at in the caption or a '
    'nearby label; do not leave the figure as an unlabelled assertion. Prefer light cards, thin accent '
    'rules and small labels; avoid large dark fill blocks such as full-width banners or near-black '
    'cards (dark fill is for small tags/chips only). Prefer '
    'native text/list/group/image/shape/line/table/path/formula/chart. Use path with view_box and '
    'absolute M/L/C/Q/Z commands for editable curves; formula with latex for OMML; chart with a '
    'native editable chart data object. Group children are relative to the group origin. Put '
    'speaker notes in page.notes. Do not put production notes, review text, audit caveats or deck '
    'metadata on the slide; limitations belong on one boundary page or in notes. Check density before '
    'submitting: <=14 objects, <=4 body blocks, <=260 body characters, <=3 images/tables/charts, '
    'body >=18 pt, label >=11 pt, caption >=8.5 pt. Preview individual pages through scene_preview '
    'and inspect the PowerPoint PNG before acceptance.'
)


def scene_task(prompt):
    pages = len(prompt.get('page_catalog') or [])
    boxes = sum(len(item.get('display_copy') or []) for item in prompt.get('page_catalog') or [])
    return f"""# PageScene 任务（显式页面几何）

完整读取 `work/page_scene_prompt.json` 和 schema_path 指向的 PageScene Schema。输出
`work/page_scene.json`，共 {pages} 页，对应已批准的 page_design 页面顺序。

- 页面文案以 `copy_bindings` 为唯一来源。标题/结论用 `title_ref`/`take_ref`；正文、
  标签和图注用对象 `copy_ref`。只有与批准文本逐字相同才允许写字面量。
- 每页给每个对象显式 `box`（英寸）。不要写“左边两张图、右边三条结论”让程序猜几何；
  不要让对象重叠，不要把说明文字塞进装饰框。
- 一页只讲一个判断：一个主视觉 + 至多三条短结论。保留原图比例、图号/面板字母和来源；
  论文图不能重画成示意，示意必须标 schematic。
- 页眉由渲染器统一画：section 写 `NN · LABEL`，标题/结论用 `title_ref`/`take_ref`，可用
  `title_emphasis`/`take_emphasis` 强调关键术语。正文组织成 2–4 个带小标题的区，不要整页
  一排等权重的项目符号；用形状小标题、关键数字卡、图旁标注建立层级。
- 有图的页面必须有可见读图说明：点名面板、轴/条件、要看的变化和含义；不能只放图加结论。
  不把“作者主张/未验证/仅/不能”等审查口吻写进正文；局限集中到一页边界或 notes。
- 用浅色卡片、细强调线和少量小标签分组；不要整条深色横幅或大面积近黑卡片。
  深色只用于小标签/小徽章，不用于承载大段正文。
- 原生对象：text / list（0–3 级）/ group（子对象相对组原点）/ image / shape / line /
  table / path（贝塞尔）/ formula（OMML）/ chart（原生数据图）。notes 写讲稿。
- 提交前运行 `pagespec-check` 或让 totalpipe_advance 校验；用 `scene_preview` 选页，
  实际打开 PowerPoint PNG 检查截断、重叠、图注和阅读顺序。失败页只改该页。

交付时列出页数、每页主视觉和真实未解决项；不要声称已完成科学审读或 PowerPoint UI 验收。"""
