"""Formula abstraction: one AST, three projections (OMML, plain text, measurement).

The pipeline never lets a formula reach the writer as markup it cannot inspect. Authoring code
writes a small LaTeX subset; this module parses it once and can then

* ``to_omml()``    — emit DrawingML/Office Math markup (the delivery path),
* ``to_plain()``   — emit the Unicode fallback PowerPoint shows when math is unavailable,
* ``measure()``    — report the box the formula needs, which is what the layout and the gates use.

Only a whitelisted grammar is accepted: there is no TeX macro expansion here, so ``\\input`` and
friends cannot smuggle anything in. Unknown commands raise :class:`FormulaError` with the offset,
which is what the Story/planner side needs to fix the source instead of guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

MATH_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'

GREEK = {
    'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ε', 'zeta': 'ζ',
    'eta': 'η', 'theta': 'θ', 'kappa': 'κ', 'lambda': 'λ', 'mu': 'μ', 'nu': 'ν', 'xi': 'ξ',
    'pi': 'π', 'rho': 'ρ', 'sigma': 'σ', 'tau': 'τ', 'phi': 'φ', 'chi': 'χ', 'psi': 'ψ',
    'omega': 'ω', 'Gamma': 'Γ', 'Delta': 'Δ', 'Theta': 'Θ', 'Lambda': 'Λ', 'Xi': 'Ξ',
    'Pi': 'Π', 'Sigma': 'Σ', 'Phi': 'Φ', 'Psi': 'Ψ', 'Omega': 'Ω',
}
OPERATORS = {
    'times': '×', 'cdot': '·', 'pm': '±', 'mp': '∓', 'leq': '≤', 'le': '≤', 'geq': '≥',
    'ge': '≥', 'neq': '≠', 'ne': '≠', 'approx': '≈', 'infty': '∞', 'partial': '∂',
    'propto': '∝', 'sim': '∼', 'll': '≪', 'gg': '≫', 'degree': '°',
    'nabla': '∇', 'rightarrow': '→', 'to': '→', 'Rightarrow': '⇒', 'in': '∈',
    'sum': '∑', 'prod': '∏', 'int': '∫', 'oint': '∮', 'lim': 'lim',
}
NARY = {'sum', 'prod', 'int', 'oint'}
SUPERSCRIPT = str.maketrans('0123456789+-=()n', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ')
SUBSCRIPT = str.maketrans('0123456789+-=()aeiox', '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒₓ')


class FormulaError(ValueError):
    """Syntax error with the character offset, so the authoring side can fix it."""

    def __init__(self, message, position):
        super().__init__(f'{message} at char {position}')
        self.position = position


# --------------------------------------------------------------------------------------------
# AST
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Node:
    pass


@dataclass(frozen=True)
class Row(Node):
    children: tuple


@dataclass(frozen=True)
class Text(Node):
    value: str


@dataclass(frozen=True)
class Frac(Node):
    numerator: Node
    denominator: Node


@dataclass(frozen=True)
class Scripts(Node):
    base: Node
    sup: Node | None = None
    sub: Node | None = None


@dataclass(frozen=True)
class Sqrt(Node):
    body: Node


@dataclass(frozen=True)
class Nary(Node):
    char: str
    sub: Node | None
    sup: Node | None
    body: Node


@dataclass(frozen=True)
class Group(Node):
    body: Node
    left: str
    right: str


# --------------------------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------------------------

_TOKEN = re.compile(r'\\[A-Za-z]+|\\.|[{}^_&]|\s+|.', re.DOTALL)
_ESCAPES = {'\\{': '{', '\\}': '}', '\\,': ' ', '\\;': ' ', '\\!': '', '\\ ': ' ',
            '\\%': '%', '\\$': '$', '\\&': '&', '\\#': '#'}


class _Parser:
    def __init__(self, source):
        self.source = source
        self.tokens = [(match.group(0), match.start()) for match in _TOKEN.finditer(source)]
        self.index = 0

    def peek(self):
        return self.tokens[self.index][0] if self.index < len(self.tokens) else None

    def take(self):
        token, position = self.tokens[self.index]
        self.index += 1
        return token, position

    def error(self, message):
        position = self.tokens[self.index][1] if self.index < len(self.tokens) else len(self.source)
        raise FormulaError(message, position)

    def parse(self):
        row = self.row()
        if self.index != len(self.tokens):
            self.error(f'unexpected {self.peek()!r}')
        return row

    def row(self, stop=()):
        children = []
        while self.index < len(self.tokens):
            token = self.peek()
            if token in stop or token in ('}', '\\right'):
                break
            children.append(self.scripted())
        if not children:
            return Row(())
        return children[0] if len(children) == 1 else Row(tuple(children))

    def scripted(self):
        base = self.atom()
        sup = sub = None
        while self.peek() in ('^', '_'):
            marker, _ = self.take()
            argument = self.group_or_atom()
            if marker == '^':
                if sup is not None:
                    self.error('double superscript')
                sup = argument
            else:
                if sub is not None:
                    self.error('double subscript')
                sub = argument
        return base if sup is None and sub is None else Scripts(base, sup, sub)

    def group_or_atom(self):
        if self.peek() == '{':
            self.take()
            body = self.row(stop=('}',))
            if self.peek() != '}':
                self.error('missing }')
            self.take()
            return body
        return self.atom()

    def atom(self):
        token = self.peek()
        if token is None:
            self.error('unexpected end of formula')
        if token == '{':
            return self.group_or_atom()
        if token.startswith('\\'):
            return self.command()
        if token == '(':
            self.take()
            body = self.row(stop=(')',))
            if self.peek() != ')':
                self.error('missing )')
            self.take()
            return Group(body, '(', ')')
        if token in ('^', '_'):
            self.error(f'{token} without a base')
        self.take()
        return Text(token)

    def command(self):
        name, position = self.take()
        bare = name[1:]
        if name == '\\left':
            opener, _ = self.take()
            body = self.row(stop=('\\right',))
            if self.peek() != '\\right':
                self.error('\\left without \\right')
            self.take()
            closer, _ = self.take()
            return Group(body, opener, closer)
        if bare in ('frac', 'dfrac', 'tfrac'):
            return Frac(self.group_or_atom(), self.group_or_atom())
        if bare == 'sqrt':
            if self.peek() == '[':
                self.error('indexed roots are not supported; use a superscript')
            return Sqrt(self.group_or_atom())
        if bare == 'text':
            if self.peek() != '{':
                self.error('\\text needs braces')
            self.take()
            pieces = []
            while self.peek() not in ('}', None):
                pieces.append(self.take()[0])
            if self.peek() != '}':
                self.error('missing }')
            self.take()
            return Text(''.join(pieces))
        if bare in NARY:
            sub = sup = None
            while self.peek() in ('_', '^'):
                marker, _ = self.take()
                argument = self.group_or_atom()
                if marker == '_':
                    sub = argument
                else:
                    sup = argument
            return Nary(OPERATORS[bare], sub, sup, self.row())
        if bare in GREEK:
            return Text(GREEK[bare])
        if bare in OPERATORS:
            return Text(OPERATORS[bare])
        if name in _ESCAPES:
            return Text(_ESCAPES[name])
        raise FormulaError(f'unsupported command {name!r}', position)


def parse(source):
    """Parse the supported LaTeX subset into an AST."""
    text = str(source or '').strip()
    if text.startswith('$') and text.endswith('$') and len(text) > 1:
        text = text[1:-1]
    if not text:
        raise FormulaError('empty formula', 0)
    return _Parser(text).parse()


# --------------------------------------------------------------------------------------------
# Projections
# --------------------------------------------------------------------------------------------

def _xml(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _run_props(size_px=None, color=None, face='Cambria Math'):
    """Text run properties for every math run: size, colour and the math face."""
    if size_px is None and not color:
        return ''
    attributes = ' lang="en-US"'
    if size_px is not None:
        attributes += f' sz="{round(size_px * 75)}"'
    if color:
        face_xml = f'<a:latin typeface="{_xml(face)}" />' if face else ''
        return (f'<a:rPr{attributes}><a:solidFill><a:srgbClr val="{color.lstrip("#")}" />'
                f'</a:solidFill>{face_xml}</a:rPr>')
    return f'<a:rPr{attributes} />'


def _omml_row(node, props=''):
    if isinstance(node, Row):
        return ''.join(_omml_row(child, props) for child in node.children)
    return _omml_node(node, props)


def _omml_node(node, props=''):
    if isinstance(node, Text):
        if node.value.strip() == '':
            return ''
        return f'<m:r>{props}<m:t xml:space="preserve">{_xml(node.value)}</m:t></m:r>'
    if isinstance(node, Row):
        return _omml_row(node, props)
    if isinstance(node, Frac):
        return (f'<m:f><m:num>{_omml_row(node.numerator, props)}</m:num>'
                f'<m:den>{_omml_row(node.denominator, props)}</m:den></m:f>')
    if isinstance(node, Sqrt):
        return ('<m:rad><m:radPr><m:degHide m:val="1" /></m:radPr><m:deg />'
                f'<m:e>{_omml_row(node.body, props)}</m:e></m:rad>')
    if isinstance(node, Scripts):
        base = _omml_row(node.base, props)
        if node.sup is not None and node.sub is not None:
            return (f'<m:sSubSup><m:e>{base}</m:e><m:sub>{_omml_row(node.sub, props)}</m:sub>'
                    f'<m:sup>{_omml_row(node.sup, props)}</m:sup></m:sSubSup>')
        if node.sup is not None:
            return f'<m:sSup><m:e>{base}</m:e><m:sup>{_omml_row(node.sup, props)}</m:sup></m:sSup>'
        return f'<m:sSub><m:e>{base}</m:e><m:sub>{_omml_row(node.sub, props)}</m:sub></m:sSub>'
    if isinstance(node, Nary):
        sub = (f'<m:sub>{_omml_row(node.sub, props)}</m:sub>' if node.sub is not None
               else '<m:sub />')
        sup = (f'<m:sup>{_omml_row(node.sup, props)}</m:sup>' if node.sup is not None
               else '<m:sup />')
        return (f'<m:nary><m:naryPr><m:chr m:val="{_xml(node.char)}" />'
                f'<m:limLoc m:val="undOvr" /></m:naryPr>{sub}{sup}'
                f'<m:e>{_omml_row(node.body, props)}</m:e></m:nary>')
    if isinstance(node, Group):
        return (f'<m:r>{props}<m:t>{_xml(node.left)}</m:t></m:r>' + _omml_row(node.body, props)
                + f'<m:r>{props}<m:t>{_xml(node.right)}</m:t></m:r>')
    raise TypeError(f'unsupported node: {node!r}')


def to_omml(node, size_px=None, color=None, face='Cambria Math'):
    """The ``m:oMath`` payload (without the wrapping paragraph)."""
    props = _run_props(size_px, color, face)
    return f'<m:oMath xmlns:m="{MATH_NS}">{_omml_row(node, props)}</m:oMath>'


def to_omml_paragraph(node, size_px=None, color=None, face='Cambria Math'):
    """A display equation wrapped the way PowerPoint stores it, including the plain fallback."""
    props = _run_props(size_px, color, face)
    fallback = _xml(to_plain(node))
    return (
        '<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main">'
        '<mc:AlternateContent><mc:Choice Requires="a14"><a14:m>'
        f'<m:oMathPara xmlns:m="{MATH_NS}">{_omml_row(node, props)}</m:oMathPara>'
        '</a14:m></mc:Choice>'
        f'<mc:Fallback><a:r>{props}<a:t xml:space="preserve">{fallback}</a:t></a:r></mc:Fallback>'
        '</mc:AlternateContent></a:p>')


def _plain(node):
    if isinstance(node, Text):
        return node.value
    if isinstance(node, Row):
        return ''.join(_plain(child) for child in node.children)
    if isinstance(node, Frac):
        return f'{_grouped_plain(node.numerator)}/{_grouped_plain(node.denominator)}'
    if isinstance(node, Sqrt):
        body = _plain(node.body)
        return f'√{body}' if len(body) == 1 else f'√({body})'
    if isinstance(node, Scripts):
        base = _plain(node.base)
        text = base
        if node.sub is not None:
            sub = _plain(node.sub)
            text += (sub.translate(SUBSCRIPT) if sub.isdigit() else f'_{sub}')
        if node.sup is not None:
            sup = _plain(node.sup)
            can_lift = sup and all(ord(char) in SUPERSCRIPT for char in sup)
            text += sup.translate(SUPERSCRIPT) if can_lift else f'^{sup}'
        return text
    if isinstance(node, Nary):
        limits = ''
        if node.sub is not None:
            limits += _plain(node.sub).translate(SUBSCRIPT)
        if node.sup is not None:
            limits += f'^{_plain(node.sup)}'
        return f'{node.char}{limits} {_plain(node.body).lstrip()}'
    if isinstance(node, Group):
        return f'{node.left}{_plain(node.body)}{node.right}'
    raise TypeError(f'unsupported node: {node!r}')


def _grouped_plain(node):
    """A fraction operand keeps its meaning in plain text: ``1/(1+e)``, not ``1/1+e``."""
    text = _plain(node)
    compound = isinstance(node, Row) and len(node.children) > 1
    if compound or any(char in text for char in '+-'):
        return f'({text})'
    return text


def to_plain(node):
    """Unicode fallback: what the reader sees when OMML is not available."""
    return _plain(node).strip()


@dataclass(frozen=True)
class Metrics:
    width: float          # css px at 96 dpi
    height: float
    exact: bool           # False when a heuristic had to be used

    def as_box(self):
        return [0.0, 0.0, self.width, self.height]


def measure(node, font_size_px=24.0):
    """Width/height of the typeset formula, in css pixels.

    matplotlib's mathtext is the same offline font-metric source used elsewhere in the compiler, so
    the number does not depend on a LaTeX installation. Constructs mathtext cannot set (CJK inside
    ``\\text``, for one) fall back to a width estimate and are marked ``exact=False`` so the caller
    can raise a REVIEW instead of silently trusting an approximation.
    """
    source = to_latex(node)
    plain = to_plain(node)
    # mathtext has no CJK glyphs and silently substitutes boxes, so a formula carrying text is
    # measured by the heuristic and flagged, never reported as exact.
    if any('\u2e80' <= character <= '\uffef' for character in plain):
        return _estimate(plain, font_size_px, node)
    try:
        from matplotlib.mathtext import MathTextParser
        from matplotlib.font_manager import FontProperties
        parser = MathTextParser('path')
        width, height, depth, _, _ = parser.parse(source, dpi=96,
                                                  prop=FontProperties(size=font_size_px * .75))
        return Metrics(round(float(width), 2), round(float(height + depth), 2), True)
    except Exception:
        return _estimate(plain, font_size_px, node)


def _estimate(plain, font_size_px, node):
    width = sum(2.0 if '\u3400' <= char <= '\u9fff' else 1.0 for char in plain)
    depth = 1.6 if any(isinstance(item, Frac) for item in _walk(node)) else 1.0
    return Metrics(round(width * font_size_px * .55, 2),
                   round(font_size_px * 1.25 * depth, 2), False)


def _walk(node):
    yield node
    for field in ('children',):
        for child in getattr(node, field, ()):
            yield from _walk(child)
    for field in ('numerator', 'denominator', 'base', 'sup', 'sub', 'body'):
        child = getattr(node, field, None)
        if isinstance(child, Node):
            yield from _walk(child)


def to_latex(node):
    """Back to the mathtext-compatible subset; used for measurement and error messages."""
    if isinstance(node, Text):
        return node.value
    if isinstance(node, Row):
        return ''.join(to_latex(child) for child in node.children)
    if isinstance(node, Frac):
        return f'\\frac{{{to_latex(node.numerator)}}}{{{to_latex(node.denominator)}}}'
    if isinstance(node, Sqrt):
        return f'\\sqrt{{{to_latex(node.body)}}}'
    if isinstance(node, Scripts):
        text = to_latex(node.base)
        if node.sub is not None:
            text += f'_{{{to_latex(node.sub)}}}'
        if node.sup is not None:
            text += f'^{{{to_latex(node.sup)}}}'
        return text
    if isinstance(node, Nary):
        text = node.char
        if node.sub is not None:
            text += f'_{{{to_latex(node.sub)}}}'
        if node.sup is not None:
            text += f'^{{{to_latex(node.sup)}}}'
        return text + f' {to_latex(node.body)}'
    if isinstance(node, Group):
        return f'\\left{node.left}{to_latex(node.body)}\\right{node.right}'
    raise TypeError(f'unsupported node: {node!r}')
