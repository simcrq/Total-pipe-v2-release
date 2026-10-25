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


@lru_cache(maxsize=2048)
def parse_inline(source):
    """Recognize $...$ and \\(...\\) only after explicit opt-in; preserve the source elsewhere."""
    spans, prose, index = [], [], 0
    def flush():
        if prose:
            spans.append(Span('text', ''.join(prose)))
            prose.clear()
    while index < len(source):
        if source.startswith(('\\\\', '\\$'), index):
            prose.append(source[index+1]); index += 2; continue
        if source.startswith(('$$', '\\[', '\\]'), index):
            raise InlineMathError(f'Display delimiters are not inline math at char {index}; use component=formula.')
        opening = '$' if source[index] == '$' else '\\(' if source.startswith('\\(', index) else None
        if opening is None:
            if source.startswith('\\)', index):
                raise InlineMathError(f'Unmatched inline closing delimiter at char {index}.')
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


def measure_inline(source, width, font, size, line_height=1.25, leading_marker=None):
    """Sum widths within each line; sum per-line max ascent + max descent, not TeX length."""
    if width <= 0:
        raise InlineWidthError(1, width)
    ascent, descent = font.getmetrics()
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
            # Line breaks are layout controls, not glyphs. In particular, Raqm-backed
            # Pillow 13 fonts reject getlength('\n') and getlength('\r'). Normalize
            # authored Windows/Mac breaks locally; the canonical source stays intact.
            prose = span.text.replace('\r\n', '\n').replace('\r', '\n')
            for token in TOKEN.findall(prose):
                pieces = list(token) if token != '\n' and font.getlength(token) > width else [token]
                for piece in pieces:
                    atoms.append({'kind': 'text', 'text': piece, 'plain': piece,
                        'width': 0.0 if piece == '\n' else font.getlength(piece),
                        'ascent': ascent, 'descent': descent})

    lines, current = [], []
    def finish():
        # Whitespace at a soft line boundary is typographic; source remains byte-for-byte in IR.
        while current and current[-1]['kind'] == 'text' and current[-1]['text'].isspace(): current.pop()
        fragments = []
        for atom in current:
            if fragments and fragments[-1]['kind'] == atom['kind'] == 'text':
                fragments[-1]['text'] += atom['text']; fragments[-1]['plain'] += atom['plain']
                fragments[-1]['width'] = font.getlength(fragments[-1]['text'])
            else:
                fragments.append(dict(atom))
        above = max([ascent, *(a['ascent'] for a in current)])
        below = max([descent, *(a['descent'] for a in current)])
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
            'measured_exact': exact, 'font_size_px': size, 'text': '\n'.join(line['text'] for line in lines)}
