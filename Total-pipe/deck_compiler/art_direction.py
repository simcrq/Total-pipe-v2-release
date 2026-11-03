"""The design layer's device vocabulary: what a page can do beyond holding text.

A page design used to choose a *form* — a layout — and nothing else. Everything that makes a slide
read as designed (a labelled group, a boxed conclusion, the phrase that carries the claim, where a
figure came from, the contents page) was an optional detail on the IR author, so in practice it was
never chosen: an optional field with no trigger is a field that does not exist.

This module is the missing vocabulary, and the reason a designer can commit to it. Every device has
a defined degradation path, so choosing one can never hard-fail a build:

    chip label        -> full-width title band -> plain title
    contents page     -> no page
    caption provenance-> caption without the label
    emphasis          -> measured, and the page keeps one body size

A designer that knows every choice is safe chooses; a designer that knows every choice can fail
abstains. That is the whole point: the gates are here to catch a wrong page, not to train the
design layer to want nothing.
"""
import re

PAGE = 'page'
DECK = 'deck'

DEVICES = {
    'emphasis': {
        'scope': PAGE, 'slot': 'phrases', 'shape': 'list of 1-3 exact substrings',
        'ir': 'the phrase wrapped in ** in the text that carries the claim',
        'use': '一句话里承载结论的词；读者只看这一处也知道这句在说什么',
        'fallback': 'measured at the bold face; worst case the block takes one more line',
    },
    'highlight': {
        'scope': PAGE, 'slot': 'phrases', 'shape': 'list of 1-2 exact substrings',
        'ir': 'the phrase wrapped in == (highlighted run)',
        'use': '投影上必须被认出的符号、数字或短表达式',
        'fallback': 'same measurement as emphasis; the highlight itself never changes width',
    },
    'panel-group': {
        'scope': PAGE, 'slot': 'labels', 'shape': 'list of 2-3 short labels (<= 8 chars each)',
        'ir': 'layout_tree panels, each with frame.title_fill and title_band="chip"',
        'use': '一页要分成两三组，每组都有自己的名字（参考 deck 里最有效的结构手段）',
        'fallback': 'panel with a full-width title band, then a plain framed group',
    },
    'caption-source': {
        'scope': PAGE, 'slot': 'policy or labels',
        'shape': 'true (every paper figure gets its provenance) or a list of {figure: int, label: <=80 chars}',
        'ir': 'figure_refs[i].source_label',
        'use': '论文图的出处（作者、文献、图号）作为图注前的弱化前缀',
        'fallback': 'the caption is set without the label when the strip cannot hold both',
    },
    'takeaway-frame': {
        'scope': PAGE, 'slot': 'style', 'shape': '"fill" or "outline"',
        'ir': 'slide.presentation.takeaway_frame',
        'use': '这一页的结论必须看起来是结论，而不是又一行正文',
        'fallback': 'a plain takeaway line',
    },
    'sequence-rail': {
        'scope': PAGE, 'slot': None, 'shape': 'no slots',
        'ir': 'numbered rail whenever the page is an ordered process',
        'use': '四个以上步骤时给读者序号与轨道，避免读成四个并列事实',
        'fallback': 'plain blocks in reading order',
    },
    'sections': {
        'scope': DECK, 'slot': 'starts', 'shape': 'list of {page: page id, label: <=24 chars}',
        'ir': 'slides[i].presentation.section',
        'use': '给长报告分章；目录页与页码都从它派生',
        'fallback': 'no section labels and no contents page',
    },
    'agenda': {
        'scope': DECK, 'slot': 'title', 'shape': 'title string (<=20 chars)',
        'ir': 'presentation.agenda (+ the sections above)',
        'use': '长报告需要一张读者能按页索引的目录',
        'fallback': 'no contents page (AGENDA_EMPTY)',
    },
    'footer': {
        'scope': DECK, 'slot': 'text', 'shape': 'one line (<=120 chars)',
        'ir': 'presentation.footer',
        'use': '页脚署名：deck 的题目或实验室名',
        'fallback': 'numbers without the footer line',
    },
    'page-numbers': {
        'scope': DECK, 'slot': 'enabled', 'shape': 'true or false',
        'ir': 'presentation.page_numbers',
        'use': '全篇连续页码，最便宜的完成度信号',
        'fallback': 'no numbers',
    },
}

LABELS = re.compile(r'^.{1,24}$')
SHORT = re.compile(r'^.{1,8}$')


def capabilities():
    """What a design may choose, published to the design and IR prompts."""
    return {'contract': 'totalpipe.art-direction', 'devices': DEVICES,
            'rules': [
                'A device is a decision, not a decoration: declare it when the page needs it.',
                'Every device degrades instead of failing: chip→band→plain, agenda→none, '
                'provenance→caption, emphasis→measured line.',
                'Abstaining is a decision too: say in the rationale why the page uses no device.',
                'Content invariants still hold: every Story item once, numbers only from cited evidence.']}


def _page_devices():
    return {name: spec for name, spec in DEVICES.items() if spec['scope'] == PAGE}


def _deck_devices():
    return {name: spec for name, spec in DEVICES.items() if spec['scope'] == DECK}


def _errors(name, value):
    """Shape errors only. A device is never rejected for what it might cost on the page."""
    if name == 'emphasis' or name == 'highlight':
        limit = 3 if name == 'emphasis' else 2
        if not isinstance(value, list) or not value or len(value) > limit:
            return [f'{name} requires 1-{limit} phrases']
        return [f'{name}: every phrase must be a non-empty string' for phrase in value
                if not isinstance(phrase, str) or not phrase.strip()][:1]
    if name == 'panel-group':
        if not isinstance(value, list) or not 2 <= len(value) <= 3:
            return ['panel-group requires 2-3 labels']
        return [f'panel-group: {label!r} must be at most 8 characters'
                for label in value if not isinstance(label, str) or not SHORT.match(label)][:1]
    if name == 'caption-source':
        if value is True:
            return []          # a policy: provenance for whatever paper figure the page ends up with
        if not isinstance(value, list) or not value:
            return ['caption-source requires true or a list of {figure, label}']
        errors = []
        for entry in value:
            if not isinstance(entry, dict) or set(entry) - {'figure', 'label'}:
                errors.append('caption-source entries are {figure: index, label: text}')
                continue
            if not isinstance(entry.get('figure'), int) or entry['figure'] < 0:
                errors.append('caption-source.figure must be a zero-based figure index')
            label = entry.get('label')
            if not isinstance(label, str) or not label.strip() or len(label) > 80:
                errors.append('caption-source.label requires one line of at most 80 characters')
        return errors[:1]
    if name == 'takeaway-frame':
        if value not in ('fill', 'outline'):
            return ['takeaway-frame requires "fill" or "outline"']
        return []
    if name == 'sequence-rail':
        return [] if value in (True, None) else ['sequence-rail takes no setting']
    if name == 'sections':
        if not isinstance(value, list) or len(value) < 2:
            return ['sections requires at least two {page, label} entries']
        errors = []
        for entry in value:
            if not isinstance(entry, dict) or set(entry) - {'page', 'label'}:
                errors.append('sections entries are {page: id, label: text}')
                continue
            if not isinstance(entry.get('page'), str) or not entry['page'].strip():
                errors.append('sections.page must be a designed page id')
            label = entry.get('label')
            if not isinstance(label, str) or not LABELS.match(label) or '\n' in label:
                errors.append('sections.label requires one line of at most 24 characters')
        return errors[:1]
    if name == 'agenda':
        if value is True:
            return []
        if not isinstance(value, dict) or set(value) - {'title'}:
            return ['agenda takes true or {"title": text}']
        title = value.get('title')
        if title is not None and (not isinstance(title, str) or not title.strip() or len(title) > 20):
            return ['agenda.title requires one line of at most 20 characters']
        return []
    if name == 'footer':
        if not isinstance(value, str) or not value.strip() or len(value) > 120 or '\n' in value:
            return ['footer requires one line of at most 120 characters']
        return []
    if name == 'page-numbers':
        if not isinstance(value, bool):
            return ['page-numbers takes true or false']
        return []
    return [f'unknown device {name}']


def validate(devices, scope):
    """Errors for a device plan of one scope; unknown names are reported, never guessed."""
    if not isinstance(devices, dict):
        return ['devices must be an object']
    allowed = _page_devices() if scope == PAGE else _deck_devices()
    errors = []
    for name, value in devices.items():
        if name not in allowed:
            errors.append(f'{name}: not a {scope} device; choose one of {sorted(allowed)}')
            continue
        errors += _errors(name, value)
    return errors


def deck_devices(design):
    return dict((design or {}).get('devices') or {})


def page_devices(page):
    return dict((page or {}).get('devices') or {})


def _text_fields(slide):
    """The visible text a phrase can be marked in, in reading order."""
    semantic = slide.get('semantic') or {}
    yield 'takeaway', semantic
    for block in (slide.get('composition') or {}).get('blocks') or []:
        yield 'block', block


def _mark(text, phrase, opener):
    if not isinstance(text, str) or phrase not in text:
        return None
    if f'{opener}{phrase}{opener}' in text:
        # The IR author already marked it. Marking again produced ····phrase····, which parses as
        # one literal ·· around the phrase instead of an emphasis run.
        return text
    return text.replace(phrase, f'{opener}{phrase}{opener}', 1)


def _page_index(design, page_id):
    """Where a designed page sits in the deck; the IR copies that order one page at a time."""
    for index, page in enumerate((design or {}).get('pages') or []):
        if str(page.get('id')) == str(page_id):
            return index
    return None


def apply_deck(ir, design):
    """Write the deck-level devices into the IR. Returns ``(ir, notes)``."""
    notes = []
    presentation = ir.setdefault('presentation', {})
    devices = deck_devices(design)
    slides = ir.get('slides') or []
    if 'page-numbers' in devices:
        presentation['page_numbers'] = bool(devices['page-numbers'])
    if 'footer' in devices:
        presentation['footer'] = devices['footer']
    if 'sections' in devices:
        for entry in devices['sections']:
            index = _page_index(design, entry['page'])
            if index is None or index >= len(slides):
                notes.append(f"sections: page {entry['page']!r} is not in the design")
                continue
            slides[index].setdefault('presentation', {})['section'] = entry['label']
    if 'agenda' in devices:
        presentation['agenda'] = devices['agenda']
    return ir, notes


def apply_page(slide, page):
    """Write one page's devices into its IR slide. Returns ``(slide, notes)``."""
    notes, devices = [], page_devices(page)
    for name in ('emphasis', 'highlight'):
        for phrase in devices.get(name) or []:
            opener = '**' if name == 'emphasis' else '=='
            marked = False
            for kind, holder in _text_fields(slide):
                key = 'text' if kind == 'block' else 'takeaway'
                updated = _mark(holder.get(key), phrase, opener)
                if updated is not None:
                    holder[key] = updated
                    marked = True
                    break
            if not marked:
                notes.append(f'{name}: {phrase!r} is not in this page\'s visible text')
    captions = devices.get('caption-source')
    if captions is True:
        # The design stage has no figure list, so it can only ask for provenance. The compiler
        # writes the honest minimum (the paper figure number) and the IR stage replaces it with
        # the real citation when the evidence names one.
        for figure in (slide.get('composition') or {}).get('figure_refs') or []:
            if figure.get('source_figure') and not figure.get('source_label'):
                figure['source_label'] = f"原文 Fig. {figure['source_figure']}"
    for entry in captions if isinstance(captions, list) else []:
        figures = (slide.get('composition') or {}).get('figure_refs') or []
        if entry['figure'] >= len(figures):
            notes.append(f"caption-source: figure {entry['figure']} does not exist on this page")
            continue
        # The design names the figure; the label text is the IR's job. Never overwrite a label the
        # author wrote (it may carry the citation the design could not know).
        if not figures[entry['figure']].get('source_label'):
            figures[entry['figure']]['source_label'] = entry['label']
    style = devices.get('takeaway-frame')
    if style:
        create = {'border': {'color': '#C4CED9', 'width': 1},
                  'fill': '#F8FAFC' if style == 'fill' else 'none', 'padding': 'compact'}
        slide.setdefault('presentation', {})['takeaway_frame'] = create
    if devices.get('panel-group'):
        notes.append('panel-group is structural: the IR must build the panels with frame.title_band="chip"')
    return slide, notes


def apply(ir, design):
    """Materialize every declared device the compiler can write mechanically."""
    ir, notes = apply_deck(ir, design)
    for slide, page in zip(ir.get('slides') or [], (design or {}).get('pages') or []):
        _, page_notes = apply_page(slide, page)
        notes += [f'{page.get("id")}: {note}' for note in page_notes]
    return ir, notes


def check(ir, design):
    """Devices the design committed to that the IR does not carry, as ``(page, message)``."""
    missing = []
    presentation = ir.get('presentation') or {}
    deck = deck_devices(design)
    if deck.get('footer') and presentation.get('footer') != deck['footer']:
        missing.append((None, 'footer device was not set'))
    if 'page-numbers' in deck and presentation.get('page_numbers', True) != bool(deck['page-numbers']):
        missing.append((None, 'page-numbers device was not set'))
    if deck.get('agenda') and not presentation.get('agenda'):
        missing.append((None, 'agenda device was not set'))
    if deck.get('sections'):
        declared = {entry['page']: entry['label'] for entry in deck['sections']}
        for slide, page in zip(ir.get('slides') or [], (design or {}).get('pages') or []):
            expected = declared.get(str(page.get('id')))
            if expected and (slide.get('presentation') or {}).get('section') != expected:
                missing.append((page.get('id'), f'section label {expected!r} is missing'))
    for slide, page in zip(ir.get('slides') or [], (design or {}).get('pages') or []):
        devices = page_devices(page)
        for name in ('emphasis', 'highlight'):
            opener = '**' if name == 'emphasis' else '=='
            visible = ' '.join(str(holder.get('text') or holder.get('takeaway') or '')
                               for _, holder in _text_fields(slide))
            # The IR normalizes scientific notation (10^8 -> $10^{8}$) after the device is applied.
            # Compare against the same text with math delimiters and grouping braces removed so a
            # phrase the designer saw in the brief still matches its native-math form.
            plain = visible.replace('$', '').replace('{', '').replace('}', '')
            for phrase in devices.get(name) or []:
                marker = f'{opener}{phrase}{opener}'
                if marker not in visible and marker not in plain:
                    missing.append((page.get('id'), f'{name} {phrase!r} is not marked'))
        captions = devices.get('caption-source')
        figures = (slide.get('composition') or {}).get('figure_refs') or []
        if captions is True:
            for index, figure in enumerate(figures):
                if figure.get('source_figure') and not figure.get('source_label'):
                    missing.append((page.get('id'), f'figure {index} has no source label'))
        for entry in captions if isinstance(captions, list) else []:
            index = entry['figure']
            if index >= len(figures) or not figures[index].get('source_label'):
                missing.append((page.get('id'), f"figure {index} has no source label"))
        if devices.get('takeaway-frame') and not (slide.get('presentation') or {}).get('takeaway_frame'):
            missing.append((page.get('id'), 'takeaway-frame device was not set'))
        if devices.get('panel-group'):
            panels = [node for node in _walk((slide.get('composition') or {}).get('layout_tree') or {})
                      if node.get('type') == 'panel']
            chipped = [node for node in panels
                       if (node.get('frame') or {}).get('title_band') == 'chip']
            if len(chipped) < len(devices['panel-group']):
                missing.append((page.get('id'),
                                f'panel-group asked for {len(devices["panel-group"])} labelled panels, '
                                f'{len(chipped)} carry a chip title'))
    return missing


def _walk(node):
    if not isinstance(node, dict):
        return
    if node.get('type'):
        yield node
    for region in (node.get('regions') or {}).values() if isinstance(node.get('regions'), dict) else []:
        yield from _walk(region)
    for child in node.get('children') or []:
        yield from _walk(child)
    if isinstance(node.get('body'), dict):
        yield from _walk(node['body'])
