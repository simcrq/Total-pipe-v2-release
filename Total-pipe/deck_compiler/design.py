"""Check page-design provenance without asking the designer to rewrite the Story.

1.1 assigns Story paths to pages and leaves visual instructions open ended. Legacy 1.0 designs
remain readable. Content bindings are derived for IR validation, never authored a second time.
"""
import copy
import re
from pathlib import Path

DESIGN_SCHEMA = Path(__file__).resolve().parents[1]/'schemas/page-design.schema.json'

FORMS = {
    'cover': {'anchor': 'none', 'ir': 'title page: the deck title, one line, no body',
              'use': '开场页：这场报告是什么，为什么值得听'},
    'spec-table': {'anchor': 'table', 'ir': 'native table',
                   'use': '并列的条件、参数或取值，没有主次'},
    'comparison-table': {'anchor': 'table', 'ir': 'native table',
                         'use': '两个以上对象在同一组指标上的对比'},
    'equation-reading': {'anchor': 'formula', 'ir': 'formula full width above a short reading',
                         'use': '页面对象是一个算子、定义或更新式；公式是主角，读数在下方'},
    'mechanism-flow': {'anchor': 'graphic', 'ir': 'process/dag graphic + note',
                       'use': '有顺序或分支的机制，句子读不出顺序'},
    'figure-reading': {'anchor': 'figure', 'ir': 'figure + reading panel',
                       'use': '论文图就是论点本身'},
    'three-limits': {'anchor': 'number', 'ir': 'columns of three',
                     'use': '三条并列的边界或限制'},
    'text-stack': {'anchor': 'none', 'ir': 'stack of blocks',
                   'use': '兜底：只有一两句、无法分组也无法放大的陈述'},
    # A text-only page still needs a composition. These three are the shapes a designer reaches
    # for when there is no figure: one statement that owns the page, two or three short groups
    # side by side, or a numbered set of points.
    'statement': {'anchor': 'none', 'ir': 'one block at display size (component=metric) + 1-2 notes; set '
                  'presentation.academic_design.type_scale="statement" so the number takes the poster step '
                  '(88 px) while body and captions keep their deck sizes',
                  'use': '一页就是一句话：把结论放大成主句，其余为注'},
    'text-columns': {'anchor': 'none', 'ir': 'composite-research + layout_tree columns (fit=hug), 2-3 short blocks',
                     'use': '两三组短陈述并排（路线 | 数字 | 边界），把横向空间用起来'},
    'problem-route-result': {'anchor': 'graphic',
                             'ir': 'three-node mechanism graphic (问题 → 做法 → 结果); each edge carries a short label with basis=evidence and evidence_refs, under a text band whose columns use fit=hug',
                             'use': '三段式论证没有现成图：把瓶颈、做法、结果画成三节点机制图，条件写在边上'},
    'chart-reading': {'anchor': 'graphic',
                      'ir': 'composition.charts + layout_tree chart leaf (line/bar, axes, legend, source)',
                      'use': '数字在正文或表格里、一张曲线能说明趋势；论文已有图时不要重画'},
    'numbered-points': {'anchor': 'none', 'ir': 'columns or stack of blocks, each with a short label 01-0N',
                        'use': '两到四条并列要点，带序号或标签'},
    'closing-statement': {'anchor': 'none', 'ir': 'conclusion + caveat',
                          'use': '一句结论加一条边界'},
}

ANCHORS = ('figure', 'table', 'formula', 'graphic', 'number', 'none')
ROLES = ('setup', 'problem', 'mechanism', 'result', 'limitation', 'closing', 'context')

# The room, not the paper, decides what a page has to do. These five are the occasions a research
# deck is actually presented in; the designer picks one and writes it into setting.occasion. Each
# profile says who is listening, how long a page lives, and what a page in that room must survive --
# it never names a layout, so it constrains the design without dictating the visual.
OCCASIONS = {
    'group-meeting': {
        'label': '组会汇报',
        'audience': '同组同行与导师；熟悉这篇论文的背景、方法与表征，不需要科普',
        'length': '10–20 分钟',
        'reading': 'spoken',
        'expects': '页面会停在屏幕上被追问：每页要能被指着问，数字、图、机制自己站得住；'
                   '讲者补的是细节，不是补页面缺的内容',
        'avoid': '把摘要抄成一页；两三行字占满一页；为了好看加的装饰图',
    },
    'research-report': {
        'label': '学术报告（会议 / 答辩）',
        'audience': '同行，但不一定读过这篇；需要一条自洽的论证',
        'length': '12–20 分钟',
        'reading': 'mixed',
        'expects': '页面要能独立读懂：问题、做法、证据、边界齐全；讲者不在时也成立',
        'avoid': '离开讲者口述就散掉的页；只有结论没有依据的页',
    },
    'research-sharing': {
        'label': '文献分享 / journal club',
        'audience': '想快速理解这篇论文的同行；对背景有兴趣但未必熟',
        'length': '20–30 分钟',
        'reading': 'spoken',
        'expects': '解释性更强：机制、图与结论的因果链要铺开，读者跟着你走一遍论文',
        'avoid': '只报结果不讲怎么得到；把分享做成摘要朗读',
    },
    'lecture': {
        'label': '讲课 / 教学',
        'audience': '学生；需要概念铺垫，不能假定读过论文',
        'length': '45–90 分钟',
        'reading': 'mixed',
        'expects': '节奏慢，定义、例子、推导各占其位；一页一个概念，允许重复与停顿',
        'avoid': '研究论文式的密集结果页；一页塞三个新概念',
    },
    'commercial': {
        'label': '商业路演 / 产品汇报',
        'audience': '决策者与客户；时间短，关心价值、差异与可信度',
        'length': '5–15 分钟',
        'reading': 'spoken',
        'expects': '一句主张、一个数字、一个视觉；每页只推进一步，装饰可以比学术场合多',
        'avoid': '论文式的方法细节与边界讨论；需要背景知识才看得懂的图',
    },
}
READINGS = ('spoken', 'read', 'mixed')


def default_occasion(presentation_type, brief=''):
    """The occasion a request most likely means, before the designer confirms it.

    ``presentation_type`` is free text upstream (paper_presentation, seminar, ...), so the brief is
    read too: a group meeting named in the requirements outranks a generic type.
    """
    text = f'{presentation_type or ""} {brief or ""}'.lower().replace('_', ' ').replace('-', ' ')
    for needle, occasion in (('组会', 'group-meeting'), ('group meeting', 'group-meeting'),
                             ('lab meeting', 'group-meeting'), ('journal club', 'research-sharing'),
                             ('research sharing', 'research-sharing'),
                             ('文献分享', 'research-sharing'), ('文献', 'research-sharing'),
                             ('讲课', 'lecture'), ('课程', 'lecture'), ('lecture', 'lecture'),
                             ('教学', 'lecture'), ('路演', 'commercial'), ('商业', 'commercial'),
                             ('pitch', 'commercial'), ('commercial', 'commercial'),
                             ('答辩', 'research-report'), ('defense', 'research-report'),
                             ('conference', 'research-report'), ('会议', 'research-report')):
        if needle in text:
            return occasion
    return 'research-report'

NUMBER = re.compile(r'\d+(?:\.\d+)?(?:\s*[×x]\s*10\^?-?\d+)?%?')
# A panel id is not a measurement: "Fig. 3e" names a source panel, and requiring its 3 in the
# evidence rejected correct items that simply say which panel they show.
FIGURE = re.compile(r'\bFig(?:ure)?\.?\s*\d+[a-z]?', re.IGNORECASE)


def _squash(text):
    """Numbers are compared as written, not as typeset: LaTeX evidence writes a percent as \\% and
    wraps values in $...$, so the escape and the math delimiters are dropped before the comparison.
    Without this, a correct item ·95.8%· was rejected because its evidence said $95.8\\%$."""
    return (re.sub(r'\s+', '', str(text)).replace('×', 'x').replace('−', '-')
            .replace('\\', '').replace('$', ''))


def _numbers(text):
    return {_squash(value) for value in NUMBER.findall(FIGURE.sub('', str(text)))}


def story_items(story):
    """Every unit of Story content that must appear exactly once, keyed by a stable path."""
    items = {}
    for index, entry in enumerate(story.get('story', []), 1):
        key = f'S{index}'
        items[f'{key}.answer'] = entry.get('answer', '')
        for position, point in enumerate(entry.get('key_points') or []):
            items[f'{key}.key_points[{position}]'] = point
    ending = story.get('ending') or {}
    for field in ('takeaway', 'limitation'):
        if ending.get(field):
            items[f'ending.{field}'] = ending[field]
    return items


def content_bindings(story):
    """Stable content paths and inherited evidence; no new scientific interpretation."""
    result = {}
    all_refs = list(dict.fromkeys(ref for node in story.get('story', [])
                                  for ref in node.get('evidence') or []))
    for source, text in story_items(story).items():
        if source.startswith('S'):
            index = int(source.split('.')[0][1:])-1
            refs = story['story'][index].get('evidence') or []
        else:
            # Ending lines synthesize the Story; this is inherited provenance, not fresh evidence.
            refs = all_refs
        result[source] = {'source': source, 'text': text, 'evidence': list(refs)}
    return result


def bind_design(design, story):
    """Internal IR checks receive immutable Story content, not designer-authored paraphrases."""
    if not design or design.get('schema_version') != '1.1':
        return design
    bound = copy.deepcopy(design)
    catalog = content_bindings(story)
    for page in bound.get('pages') or []:
        page['items'] = [dict(catalog[source], id=source) for source in page['content_refs']]
    bound['_content_bound'] = True
    return bound


def _validate_reference_design(design, story, evidence, slide_count):
    """Validate only the stable handoff envelope; design prose is deliberately unconstrained."""
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    problems = []
    if not text(design.get('deck_id')):
        problems.append('deck_id is required')
    setting = design.get('setting')
    if (not isinstance(setting, dict) or not text(setting.get('audience'))
            or not isinstance(setting.get('occasion'), str)
            or setting['occasion'] not in OCCASIONS or setting.get('reading') not in READINGS):
        problems.append('setting requires audience, a known occasion and reading=spoken|read|mixed')
    pages = design.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 40:
        return problems+['page_design.pages must contain 1–40 pages']
    for page in pages:
        if not isinstance(page, dict):
            problems.append('each page must be an object')
            continue
        if not text(page.get('id')):
            problems.append('every page needs an id')
        refs = page.get('content_refs')
        if not isinstance(refs, list) or not all(text(ref) for ref in refs) or len(set(refs)) != len(refs):
            problems.append('content_refs must be a list of unique Story paths')
        # Instructions may be prose or a bespoke object. No fixed element/layout vocabulary.
        instruction = page.get('design')
        if not (text(instruction) or (isinstance(instruction, dict) and instruction)):
            problems.append('each page needs non-empty design instructions (text or object)')
        for key in ('figures', 'marks'):
            if key in page and (not isinstance(page[key], list) or not all(text(v) for v in page[key])):
                problems.append(f'{key} must be a list of non-empty strings')
        if 'title' in page and not text(page['title']):
            problems.append('title must be a non-empty string when supplied')
    if problems:
        return problems
    catalog, used, ids = content_bindings(story), {}, set()
    for page in design['pages']:
        pid = page['id']
        if pid in ids:
            problems.append(f'duplicate page id {pid}')
        ids.add(pid)
        for source in page['content_refs']:
            used.setdefault(source, set()).add(pid)
            if source not in catalog:
                problems.append(f'{pid}: unknown Story content_ref {source!r}')
        refs = {ref for source in page['content_refs'] if source in catalog
                for ref in catalog[source]['evidence']}
        for ref in refs:
            if ref not in evidence:
                problems.append(f'{pid}: unknown evidence {ref}')
        # A short optional display title is the only newly authored scientific text. Drawing
        # instructions contain geometry/counts as well as science and cannot be scanned as data.
        cited = ' '.join(evidence.get(ref, '') for ref in refs)
        for number in _numbers(page.get('title', ''))-_numbers(cited):
            problems.append(f'{pid}: title number {number} is not in the cited evidence')
        text = ' '.join(catalog[source]['text'] for source in page['content_refs'] if source in catalog)
        for mark in page.get('marks') or []:
            if _squash(mark) not in _squash(text+' '+page.get('title', '')):
                problems.append(f'{pid}: mark {mark!r} does not occur in assigned Story text or title')
    for source in catalog:
        count = len(used.get(source) or [])
        if not count:
            problems.append(f'unused Story item {source}')
        elif count > 1:
            problems.append(f'Story item {source} appears on {count} pages; one unit belongs to one page')
    if slide_count is not None:
        if type(slide_count) is not int or not 1 <= slide_count <= 40:
            problems.append('slide_count must be an integer in [1,40]')
        elif len(design['pages']) != slide_count:
            problems.append(f'page_design has {len(design["pages"])} pages; the requested final '
                            f'paper-page target is {slide_count}. Replan without dropping content.')
    return problems


def capabilities():
    from .art_direction import capabilities as art
    return {'contract': 'totalpipe.page-design', 'schema_version': '1.1',
            'supported_versions': ['1.0', '1.1'],
            # Renderer choices are for the IR author, never injected into the design prompt.
            'forms': FORMS, 'anchors': list(ANCHORS), 'roles': list(ROLES),
            'occasions': OCCASIONS, 'readings': list(READINGS), 'art_direction': art(),
            'rules': ['Story owns scientific content and evidence. Page design owns visual explanation.',
                      '1.1 assigns each Story content path to exactly one page with content_refs; '
                      'text and evidence are inherited, not reauthored.',
                      'Use design as free prose or a custom object describing visual elements, '
                      'composition and presenter walkthrough. No fixed visual template.',
                      'Keep the requested setting and final page count; merging and splitting '
                      'content assignments does not change the scientific argument.',
                      'Inspect selected original figures and preserve their source and aspect ratio. '
                      'Data plots require actual data; do not invent scientific content.',
                      'IR implements the complete visual handoff using renderer forms/devices. '
                      'Legacy 1.0 designs retain their original validation.']}


def validate_design(design, story, evidence, slide_count=None):
    """Errors that make a design untraceable. ``evidence`` maps id -> evidence text."""
    from .art_direction import DECK, PAGE, validate as validate_devices
    problems = []
    if not isinstance(design, dict):
        return ['page_design must be an object']
    if design.get('schema_version') == '1.1':
        return _validate_reference_design(design, story, evidence, slide_count)
    if design.get('schema_version', '1.0') != '1.0':
        return ['unsupported page_design schema_version; use 1.1 (or legacy 1.0)']
    if 'devices' in design:
        problems += [f'deck devices: {message}' for message in validate_devices(design['devices'], DECK)]
    # The room is a design input, not a caption: without it, density and page shape are decided by
    # habit. One line each is enough; the designer may add anything else it needs.
    setting = design.get('setting')
    if not isinstance(setting, dict):
        problems.append('setting is required: who is in the room (audience), the occasion key from '
                        f'occasions ({", ".join(OCCASIONS)}), and whether pages are spoken to, read '
                        'alone or mixed (reading)')
    else:
        if not str(setting.get('audience') or '').strip():
            problems.append('setting.audience is required: who is listening and what they already know')
        if setting.get('occasion') not in OCCASIONS:
            problems.append(f'setting.occasion must be one of {list(OCCASIONS)}, not '
                            f'{setting.get("occasion")!r}')
        if setting.get('reading') not in READINGS:
            problems.append('setting.reading must be spoken, read or mixed')
    pages = design.get('pages')
    if not isinstance(pages, list) or not pages:
        return ['page_design.pages must be a non-empty list']
    items = story_items(story)
    used = {}
    for page in pages:
        if not isinstance(page, dict):
            problems.append('each page must be an object')
            continue
        page_id = page.get('id')
        if not isinstance(page_id, str) or not page_id.strip():
            problems.append('every page needs an id')
            page_id = '?'
        if page.get('role') not in ROLES:
            problems.append(f"{page_id}: role must be one of {list(ROLES)}")
        # The designer describes what the page should look like in words; naming a compiler form is
        # optional and left to the stage that knows the renderer. Legacy designs that name a form are
        # still checked against it, because they asked for that form explicitly.
        form = page.get('form')
        shape = str(page.get('shape') or '').strip()
        if form is None and not shape:
            problems.append(f'{page_id}: describe what the page should look like (shape), in one or two '
                            'sentences a designer would say to another designer')
        if form is not None and form not in FORMS:
            problems.append(f'{page_id}: unknown form {form!r}; use one of {sorted(FORMS)}')
        anchor = (page.get('anchor') or {}).get('kind')
        if anchor not in ANCHORS:
            problems.append(f'{page_id}: anchor.kind must be one of {list(ANCHORS)}')
        elif form in FORMS and FORMS[form]['anchor'] != anchor:
            problems.append(f'{page_id}: form {form} carries a {FORMS[form]["anchor"]} anchor, not {anchor}')
        if not str(page.get('claim') or '').strip():
            problems.append(f'{page_id}: claim is required')
        if not str(page.get('rationale') or '').strip():
            problems.append(f'{page_id}: rationale is required')
        marks = page.get('marks')
        if marks is not None:
            if not isinstance(marks, list) or not all(isinstance(mark, str) and mark.strip() for mark in marks):
                problems.append(f'{page_id}: marks must be a list of phrases from this page')
            else:
                page_text = ' '.join(str(item.get('text') or '') for item in page.get('items') or [])
                page_text = (page_text+' '+str(page.get('claim') or '')+str(shape))
                for mark in marks:
                    if _squash(mark) not in _squash(page_text):
                        problems.append(f'{page_id}: mark {mark!r} does not occur in this page\'s text')
        if 'devices' in page:
            problems += [f'{page_id} devices: {message}'
                         for message in validate_devices(page['devices'], PAGE)]
        opening = page.get('form') == 'cover' or (page.get('role') == 'context' and not page.get('from_story'))
        if not page.get('items') and not opening:
            problems.append(f'{page_id}: at least one item is required (only a cover may be empty)')
        takeaway_from = page.get('takeaway_from')
        if takeaway_from:
            used.setdefault(takeaway_from, set()).add(page_id)
            if takeaway_from not in items:
                problems.append(f'{page_id}: takeaway_from {takeaway_from} is not a Story item')
        page_evidence = set()
        for item in page.get('items') or []:
            sources = item.get('source')
            sources = sources if isinstance(sources, list) else [sources]
            for source in sources:
                # `source` is provenance, not a claim of one-to-one use: a page may elaborate one
                # key point into three table rows. What must not happen is the same Story unit
                # landing on two different pages.
                used.setdefault(source, set()).add(page_id)
                if source not in items and source not in evidence:
                    problems.append(f"{page_id}/{item.get('id')}: source {source!r} is neither a Story item nor evidence")
            refs = item.get('evidence') or []
            if not refs:
                problems.append(f"{page_id}/{item.get('id')}: evidence is required")
            for ref in refs:
                if ref not in evidence:
                    problems.append(f"{page_id}/{item.get('id')}: unknown evidence {ref}")
            page_evidence |= set(refs)
            if item.get('kind') == 'formula':
                continue
            cited = _squash(' '.join(evidence.get(ref, '') for ref in refs))
            for number in _numbers(item.get('text', ''))-_numbers(cited):
                problems.append(f"{page_id}/{item.get('id')}: number {number} is not in its cited evidence")
        if page.get('claim'):
            cited = _squash(' '.join(evidence.get(ref, '') for ref in page_evidence))
            for number in _numbers(page['claim'])-_numbers(cited):
                problems.append(f'{page_id}: claim number {number} is not in the cited evidence')
    for source, value in items.items():
        pages_used = sorted(used.get(source) or [])
        if not pages_used:
            problems.append(f'unused Story item {source}: {str(value)[:40]}')
        elif len(pages_used) > 1:
            problems.append(f'Story item {source} appears on {len(pages_used)} pages '
                            f"({', '.join(pages_used)}); one unit belongs to one page")
    # Story nodes describe reasoning, not physical pages. Content coverage above is
    # the invariant; an arbitrary multiple of the node count blocks legitimate splits.
    if len(pages) > 40:
        problems.append('page_design supports at most 40 paper pages')
    if slide_count is not None:
        if type(slide_count) is not int or not 1 <= slide_count <= 40:
            problems.append('slide_count must be an integer in [1,40]')
        elif len(pages) != slide_count:
            problems.append(f'page_design has {len(pages)} pages; the requested final paper-page '
                            f'target is {slide_count}. Replan pages while retaining every Story item.')
    return problems


def summary(design):
    """The design decisions an IR author needs, without the Story bodies.

    The design speaks in shapes, not forms: the IR stage is the one that knows what can be drawn,
    so it receives the description and chooses the composition that realizes it.
    """
    if design.get('schema_version') == '1.1':
        # Keep arbitrary designer instructions intact; do not whitelist away icons, diagrams,
        # reading paths or bespoke composition. Scientific bodies remain in the separate Story.
        return {'schema_version': '1.1', 'setting': copy.deepcopy(design['setting']),
                'pages': [{key: copy.deepcopy(value) for key, value in page.items() if key != 'items'}
                          for page in design['pages']]}
    return {'setting': dict((design or {}).get('setting') or {}),
            'pages': [{'id': page.get('id'), 'role': page.get('role'), 'claim': page.get('claim'),
                       'shape': page.get('shape'), 'marks': list(page.get('marks') or []),
                       'figures': list(page.get('figures') or []),
                       'form': page.get('form'), 'anchor': (page.get('anchor') or {}).get('kind'),
                       'devices': dict(page.get('devices') or {}),
                       'items': [{'id': item.get('id'), 'text': item.get('text'),
                                  'kind': item.get('kind', 'text'),
                                  'evidence': item.get('evidence')}
                                 for item in page.get('items') or []]}
                      for page in design.get('pages') or []]}
