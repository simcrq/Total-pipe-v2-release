"""Opt-in mixed prose/math measurement. A formula is one indivisible line-breaking atom."""
from dataclasses import dataclass
from functools import lru_cache
import re

from .formula import FormulaError, measure, parse, to_plain


class InlineMathError(ValueError):
    pass


class InlineWidthError(InlineMathError):
    def __init__(self, required, available):
        self.required_width = required
        self.available_width = available
        super().__init__(f'Complete inline formula needs {required:.1f} px; line provides {available:.1f} px. Widen the region or use a display formula.')


@dataclass(frozen=True)
class Span:
    kind: str
    text: str
    mark: str = ''      # '' | 'emphasis' | 'highlight' | 'citation'; only text spans carry a mark


# Emphasis and citations are written in the text, not declared in a parallel array: the author
# types what should read louder or weaker and the compiler turns each pair into a run. Every mark
# is opt-in on purpose — a deck with no markers parses exactly as before.
MARKERS = (('**', '**', 'emphasis'), ('==', '==', 'highlight'), ('[[', ']]', 'citation'))
MARK_NAMES = tuple(name for _, _, name in MARKERS)
ESCAPES = ('\\\\', '\\$', '\\*', '\\=')


def _closing_marker(source, start, closer):
    """Index of the matching closer, or ``None`` when the pair is not a pair.

    A formula inside a marked span would need the mark to reach an OMML run, so an opener that
    meets ``$`` first stays literal. An unclosed or empty pair stays literal too: visible ``**`` is
    a defect a reviewer can see, while silently swallowing the rest of the sentence is not.
    """
    index = start
    while index < len(source):
        char = source[index]
        if char == '\\':
            index += 2
            continue
        if char == '\n' or char == '$' or source.startswith('\\(', index):
            return None
        if source.startswith(closer, index):
            return index
        index += 1
    return None


@lru_cache(maxsize=2048)
def parse_inline(source):
    """Recognize $...$ and \\(...\\) only after explicit opt-in; preserve the source elsewhere."""
    spans, prose, index = [], [], 0
    def flush():
        if prose:
            spans.append(Span('text', ''.join(prose)))
            prose.clear()
    while index < len(source):
        if source.startswith(ESCAPES, index):
            prose.append(source[index+1]); index += 2; continue
        if source.startswith(('$$', '\\[', '\\]'), index):
            raise InlineMathError(f'Display delimiters are not inline math at char {index}; use component=formula.')
        opening = '$' if source[index] == '$' else '\\(' if source.startswith('\\(', index) else None
        if opening is None:
            if source.startswith('\\)', index):
                raise InlineMathError(f'Unmatched inline closing delimiter at char {index}.')
            marker = next(((opener, closer, name) for opener, closer, name in MARKERS
                           if source.startswith(opener, index)), None)
            if marker is not None:
                opener, closer_text, name = marker
                closer = _closing_marker(source, index+len(opener), closer_text)
                inner = source[index+len(opener):closer] if closer is not None else ''
                if closer is not None and inner.strip() and not inner[0].isspace() and not inner[-1].isspace():
                    flush()
                    spans.append(Span('text', inner, name))
                    index = closer+len(closer_text)
                    continue
            prose.append(source[index]); index += 1; continue
        flush()
        start = index
        closing = '$' if opening == '$' else '\\)'
        index += len(opening)
        begin = index
        while index < len(source):
            if source.startswith(closing, index):
                break
            if source[index] == '\\':
                index += 2
            else:
                index += 1
        if index >= len(source):
            raise InlineMathError(f'Unclosed inline formula at char {start}.')
        expression = source[begin:index]
        try:
            parse(expression)
        except FormulaError as error:
            raise InlineMathError(f'Inline formula at char {start}: {error}') from error
        spans.append(Span('formula', expression))
        if sum(s.kind == 'formula' for s in spans) > 128:
            raise InlineMathError('At most 128 inline formulas per text field are supported.')
        index += len(closing)
    flush()
    return tuple(spans)


def plain_text(source):
    return ''.join(s.text if s.kind == 'text' else to_plain(parse(s.text)) for s in parse_inline(source))


def prose_only(source):
    return ''.join(s.text for s in parse_inline(source) if s.kind == 'text')


TOKEN = re.compile(r'[A-Za-z0-9_\u00c0-\u02af\u0370-\u03ff][A-Za-z0-9_.:/\\\-\u00c0-\u02af\u0370-\u03ff\u1d2c-\u1d6a\u2070-\u209f¹²³]*|[^\S\n]+|\n|.')
NO_LINE_START = set('，。、；：？！）】》」』”’,.;:?!)]}%×')


def measure_inline(source, width, font, size, line_height=1.25, leading_marker=None, strong_font=None):
    """Sum widths within each line; sum per-line max ascent + max descent, not TeX length.

    ``strong_font`` is the bold face used for ``**...**`` runs. Bold advances are wider than regular
    ones for Latin text, so an emphasised phrase is measured with the face it will be drawn in; when
    no bold face is available the run is laid out in the regular face and PowerPoint synthesises it.
    """
    if width <= 0:
        raise InlineWidthError(1, width)
    atoms, minimum, exact = [], 0., True
    for span in parse_inline(source):
        if span.kind == 'formula':
            metrics = measure(parse(span.text), size)
            # Native math uses Cambria Math and its own baseline; retain conservative bearings.
            w = metrics.width+4
            minimum = max(minimum, w)
            if w > width+.01:
                raise InlineWidthError(w, width)
            atoms.append({'kind': 'formula', 'text': span.text, 'plain': to_plain(parse(span.text)),
                'width': w, 'ascent': metrics.height-metrics.depth+2, 'descent': metrics.depth+2})
            exact = exact and metrics.exact
        else:
            face = strong_font if (span.mark == 'emphasis' and strong_font is not None) else font
            ascent, descent = face.getmetrics()
            # Line breaks are layout controls, not glyphs. In particular, Raqm-backed
            # Pillow 13 fonts reject getlength('\n') and getlength('\r'). Normalize
            # authored Windows/Mac breaks locally; the canonical source stays intact.
            prose = span.text.replace('\r\n', '\n').replace('\r', '\n')
            for token in TOKEN.findall(prose):
                pieces = list(token) if token != '\n' and face.getlength(token) > width else [token]
                for piece in pieces:
                    atoms.append({'kind': 'text', 'text': piece, 'plain': piece, 'mark': span.mark,
                        'width': 0.0 if piece == '\n' else face.getlength(piece),
                        'ascent': ascent, 'descent': descent})

    lines, current = [], []
    base_ascent, base_descent = font.getmetrics()
    def finish():
        # Whitespace at a soft line boundary is typographic; source remains byte-for-byte in IR.
        while current and current[-1]['kind'] == 'text' and current[-1]['text'].isspace(): current.pop()
        fragments = []
        for atom in current:
            if (fragments and fragments[-1]['kind'] == atom['kind'] == 'text'
                    and fragments[-1].get('mark', '') == atom.get('mark', '')):
                fragments[-1]['text'] += atom['text']; fragments[-1]['plain'] += atom['plain']
                face = strong_font if (atom.get('mark') == 'emphasis' and strong_font is not None) else font
                fragments[-1]['width'] = face.getlength(fragments[-1]['text'])
            else:
                fragments.append(dict(atom))
        above = max([base_ascent, *(a['ascent'] for a in current)])
        below = max([base_descent, *(a['descent'] for a in current)])
        if leading_marker and not lines:
            above = max(above, leading_marker['ascent'])
            below = max(below, leading_marker['descent'])
        if leading_marker and not lines:
            above = max(above, leading_marker['ascent'])
            below = max(below, leading_marker['descent'])
        lines.append({'fragments': fragments, 'ascent': above, 'descent': below,
            'height': max(size*line_height, above+below),
            'width': sum(a['width'] for a in fragments), 'text': ''.join(a['plain'] for a in fragments)})
        current.clear()

    for atom in atoms:
        if atom['text'] == '\n' and atom['kind'] == 'text':
            finish(); continue
        if atom['kind'] == 'text' and atom['text'].isspace():
            # Defer trailing spaces until the next visible atom. Otherwise an overflowing
            # space can commit a line before its closing punctuation has a chance to travel.
            if current: current.append(atom)
            continue
        if current and sum(a['width'] for a in current)+atom['width'] > width+.01:
            if atom['kind'] == 'text' and atom['text'][:1] in NO_LINE_START:
                while current and current[-1]['kind'] == 'text' and current[-1]['text'].isspace(): current.pop()
                previous = current.pop()
                if current: finish()
                if previous['width']+atom['width'] > width+.01:
                    raise InlineWidthError(previous['width']+atom['width'], width)
                current.append(previous)
            else:
                finish()
        if atom['width'] > width+.01:
            raise InlineWidthError(atom['width'], width)
        current.append(atom)
    if current or not lines or source.endswith(('\n', '\r')): finish()
    return {'lines': lines, 'height': sum(line['height'] for line in lines),
            'min_width': minimum, 'formula_count': sum(s.kind == 'formula' for s in parse_inline(source)),
            'marks': sorted({f.get('mark') for line in lines for f in line['fragments'] if f.get('mark')}),
            'measured_exact': exact, 'font_size_px': size, 'text': '\n'.join(line['text'] for line in lines)}


def has_markup(source):
    """Whether a text field asks for run-level emphasis or a citation; never raises on bad math."""
    if not isinstance(source, str) or not any(opener in source for opener, _, _ in MARKERS):
        return False
    try:
        return any(span.mark for span in parse_inline(source))
    except InlineMathError:
        return False


def unmatched_markers(source):
    """Markers that will be printed literally because no closing marker paired with them.

    Escaped markers and formula regions are skipped: ``\\*\\*`` is intent, an unclosed ``**`` is a
    typo the page should report.
    """
    if not isinstance(source, str):
        return []
    found, index = [], 0
    while index < len(source):
        if source.startswith(ESCAPES, index):
            index += 2
            continue
        if source.startswith('\\(', index):
            end = source.find('\\)', index)
            index = end+2 if end >= 0 else len(source)
            continue
        if source[index] == '$':
            end = index+1
            while end < len(source):
                if source[end] == '\\':
                    end += 2
                    continue
                if source[end] == '$':
                    break
                end += 1
            index = end+1
            continue
        marker = next(((opener, closer, name) for opener, closer, name in MARKERS
                       if source.startswith(opener, index)), None)
        if marker is None:
            index += 1
            continue
        opener, closer_text, name = marker
        closer = _closing_marker(source, index+len(opener), closer_text)
        if closer is None:
            found.append(name)
            index += len(opener)
        else:
            index = closer+len(closer_text)
    return found


def strip_markup(source):
    """Prose without emphasis markers, for paths that cannot carry runs (native list items)."""
    if not isinstance(source, str):
        return source
    try:
        return ''.join(span.text for span in parse_inline(source))
    except InlineMathError:
        return source
