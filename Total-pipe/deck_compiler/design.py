"""A page design is a faithful partition of the Story, checked before any Deck IR exists.

Designing a deck means deciding which Story item lands on which page, what the page is about, and
which form carries it. That freedom has exactly four ways to go wrong, and each one produces a deck
that looks better and is wrong:

* a Story item is dropped or used twice,
* an evidence id does not exist,
* a number appears that its cited evidence does not contain,
* a form is named that the compiler cannot render.

This module owns the vocabulary and the check. It never rewrites content; it only refuses a design
that cannot be traced back to the Story.
"""
import re

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
    text = f'{presentation_type or ""} {brief or ""}'.lower()
    for needle, occasion in (('组会', 'group-meeting'), ('group meeting', 'group-meeting'),
                             ('lab meeting', 'group-meeting'), ('journal club', 'research-sharing'),
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


def capabilities():
    from .art_direction import capabilities as art
    return {'contract': 'totalpipe.page-design', 'forms': FORMS, 'anchors': list(ANCHORS),
            'roles': list(ROLES), 'occasions': OCCASIONS, 'readings': list(READINGS),
            'art_direction': art(),
            'rules': ['Name the room in setting before the pages: pick the occasion from occasions, say '
                      'who is listening and what they already know, and whether a page is spoken to or '
                      'read alone. Density and page shape answer to that room, not to a template; the same '
                      'content in two rooms may legitimately be two decks.',
                      'Every Story answer, key point and ending line belongs to exactly one page; one unit '
                      'may be elaborated by several items on its page.',
                      'A page may merge two thin Story entries, and one dense entry may be split.',
                      'Every number in a claim or item must occur in the evidence that item cites; LaTeX '
                      'escapes such as $95.8\\%$ count as the same number.',
                      'A formula item is a definition rendered as written; its constants are not measurements.',
                      'Name a form from forms; the compiler renders exactly those compositions.',
                      'Name the devices the page actually needs. A device always degrades instead of failing, '
                      'so never drop one because it might cost space; a page with no device must say why '
                      'in its rationale.']}


def validate_design(design, story, evidence):
    """Errors that make a design untraceable. ``evidence`` maps id -> evidence text."""
    from .art_direction import DECK, PAGE, validate as validate_devices
    problems = []
    if not isinstance(design, dict):
        return ['page_design must be an object']
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
        form = page.get('form')
        if form not in FORMS:
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
        if 'devices' in page:
            problems += [f'{page_id} devices: {message}'
                         for message in validate_devices(page['devices'], PAGE)]
        if not page.get('items') and page.get('form') != 'cover':
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
    if len(pages) > max(2, len(story.get('story', []))*2):
        problems.append('page count is more than twice the Story entries; check for accidental splitting')
    return problems


def summary(design):
    """The design decisions an IR author needs, without the Story bodies."""
    return {'devices': dict((design or {}).get('devices') or {}),
            'setting': dict((design or {}).get('setting') or {}),
            'pages': [{'id': page.get('id'), 'role': page.get('role'), 'claim': page.get('claim'),
                       'form': page.get('form'), 'anchor': (page.get('anchor') or {}).get('kind'),
                       'devices': dict(page.get('devices') or {}),
                       'items': [{'id': item.get('id'), 'text': item.get('text'),
                                  'kind': item.get('kind', 'text'),
                                  'evidence': item.get('evidence')}
                                 for item in page.get('items') or []]}
                      for page in design.get('pages') or []]}
