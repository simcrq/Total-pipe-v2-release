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
from functools import lru_cache
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
    'cdots': '⋯', 'ldots': '…', 'dots': '…', 'vdots': '⋮', 'ddots': '⋱',
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
    upright: bool = False


@dataclass(frozen=True)
class Space(Node):
    em: int = 1


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
    degree: Node | None = None


@dataclass(frozen=True)
class Styled(Node):
    body: Node
    style: str


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


@dataclass(frozen=True)
class Matrix(Node):
    rows: tuple[tuple[Node, ...], ...]
    environment: str = 'matrix'


MATRIX_DELIMITERS = {'matrix': ('', ''), 'pmatrix': ('(', ')'), 'bmatrix': ('[', ']'),
                     'Bmatrix': ('{', '}'), 'vmatrix': ('|', '|'), 'Vmatrix': ('‖', '‖')}


# --------------------------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------------------------

_TOKEN = re.compile(r'\\[A-Za-z]+|\\.|[{}^_&]|\s+|.', re.DOTALL)
_ESCAPES = {'\\{': '{', '\\}': '}', '\\,': ' ', '\\;': ' ', '\\!': '', '\\ ': ' ',
            '\\%': '%', '\\$': '$', '\\&': '&', '\\#': '#'}
_FUNCTIONS = {'exp', 'log', 'ln', 'sin', 'cos', 'tan', 'arcsin', 'arccos', 'arctan',
              'sinh', 'cosh', 'tanh', 'min', 'max', 'det', 'lim'}
_DELIMITERS = {'(': '(', ')': ')', '[': '[', ']': ']', '|': '|', '.': '',
               '\\{': '{', '\\}': '}', '\\lbrace': '{', '\\rbrace': '}',
               '\\langle': '⟨', '\\rangle': '⟩', '\\vert': '|', '\\Vert': '‖'}


class _Parser:
    def __init__(self, source):
        self.source = source
        self.tokens = [(match.group(0), match.start()) for match in _TOKEN.finditer(source)]
        self.index = 0
        self.matrix_depth = 0

    def peek(self):
        return self.tokens[self.index][0] if self.index < len(self.tokens) else None

    def take(self):
        if self.index >= len(self.tokens):
            self.error('unexpected end of formula')
        token, position = self.tokens[self.index]
        self.index += 1
        return token, position

    def error(self, message):
        position = self.tokens[self.index][1] if self.index < len(self.tokens) else len(self.source)
        raise FormulaError(message, position)

    def skip_space(self):
        while self.peek() is not None and self.peek().isspace():
            self.take()

    def script_marker(self):
        index = self.index
        self.skip_space()
        if self.peek() in ('^', '_'):
            return self.peek()
        self.index = index
        return None

    def parse(self):
        row = self.row()
        if self.index != len(self.tokens):
            self.error(f'unexpected {self.peek()!r}')
        return row

    def row(self, stop=()):
        children = []
        while self.index < len(self.tokens):
            token = self.peek()
            if token in stop or token in ('}', ')', ']', '\\right'):
                break
            if self.matrix_depth and token in ('&', '\\\\', '\\end'):
                break
            children.append(self.scripted())
        if not children:
            return Row(())
        return children[0] if len(children) == 1 else Row(tuple(children))

    def scripted(self):
        base = self.atom()
        sup = sub = None
        while self.script_marker() is not None:
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
        self.skip_space()
        if self.peek() == '{':
            self.take()
            body = self.row(stop=('}',))
            if self.peek() != '}':
                self.error('missing }')
            self.take()
            if not to_plain(body):
                self.error('empty formula argument')
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
        if token in ('(', '['):
            closer = ')' if token == '(' else ']'
            self.take()
            body = self.row(stop=(closer,))
            if self.peek() != closer:
                self.error(f'missing {closer}')
            self.take()
            return Group(body, token, closer)
        if token in ('^', '_', '}', ')', '&', '$', ']'):
            self.error(f'{token} without a base')
        self.take()
        return Text(token)

    def command(self):
        name, position = self.take()
        bare = name[1:]
        if bare == 'begin':
            return self.matrix()
        if bare in ('quad', 'qquad'):
            return Space(1 if bare == 'quad' else 2)
        if name == '\\left':
            opener = self.delimiter()
            body = self.row(stop=('\\right',))
            if self.peek() != '\\right':
                self.error('\\left without \\right')
            self.take()
            closer = self.delimiter()
            return Group(body, opener, closer)
        if bare in ('frac', 'dfrac', 'tfrac'):
            return Frac(self.group_or_atom(), self.group_or_atom())
        if bare == 'sqrt':
            self.skip_space()
            degree = None
            if self.peek() == '[':
                self.take()
                degree = self.row(stop=(']',))
                if self.peek() != ']':
                    self.error('missing ] in root degree')
                self.take()
                if not to_plain(degree):
                    self.error('empty root degree')
            return Sqrt(self.group_or_atom(), degree)
        if bare in ('mathrm', 'mathbf', 'mathit'):
            return Styled(self.group_or_atom(), {'mathrm': 'p', 'mathbf': 'b', 'mathit': 'i'}[bare])
        if bare in ('text', 'operatorname'):
            self.skip_space()
            if self.peek() != '{':
                self.error(f'{name} needs braces')
            self.take()
            pieces = []
            depth = 1
            while self.peek() is not None:
                token, offset = self.take()
                if token == '{': depth += 1
                elif token == '}': depth -= 1
                if depth == 0:
                    break
                if token.startswith('\\') and token not in _ESCAPES:
                    raise FormulaError(f'unsupported text command {token!r}', offset)
                pieces.append(_ESCAPES.get(token, token))
            if depth:
                self.error('missing }')
            return Text(''.join(pieces), upright=True)
        if bare in NARY:
            sub = sup = None
            while self.script_marker() is not None:
                marker, _ = self.take()
                argument = self.group_or_atom()
                if marker == '_':
                    if sub is not None: self.error('double subscript')
                    sub = argument
                else:
                    if sup is not None: self.error('double superscript')
                    sup = argument
            return Nary(OPERATORS[bare], sub, sup, self.row())
        if bare in _FUNCTIONS:
            return Text(bare, upright=True)
        if bare in GREEK:
            return Text(GREEK[bare])
        if bare in OPERATORS:
            return Text(OPERATORS[bare])
        if name in _ESCAPES:
            return Text(_ESCAPES[name])
        raise FormulaError(f'unsupported command {name!r}', position)

    def environment_name(self):
        self.skip_space()
        if self.peek() != '{':
            self.error('matrix environment name needs braces')
        self.take()
        name = ''
        while self.peek() not in ('}', None):
            name += self.take()[0]
        if self.peek() != '}':
            self.error('missing } in matrix environment name')
        self.take()
        return name

    def matrix(self):
        environment = self.environment_name()
        if environment not in MATRIX_DELIMITERS:
            self.error(f'unsupported matrix environment {environment!r}')
        rows, cells = [], []
        self.matrix_depth += 1
        try:
            while True:
                self.skip_space()
                if self.peek() == '\\end' and not cells:
                    break  # a trailing row separator does not create a phantom row
                cells.append(self.row())
                self.skip_space()
                token = self.peek()
                if token == '&':
                    self.take()
                    continue
                if token in ('\\\\', '\\end'):
                    rows.append(tuple(cells))
                    cells = []
                    if token == '\\end':
                        break
                    self.take()
                    continue
                self.error('expected &, row separator, or \\end in matrix')
            self.take()  # \\end
            if self.environment_name() != environment:
                self.error(f'matrix must end with \\end{{{environment}}}')
        finally:
            self.matrix_depth -= 1
        if not rows or not any(to_plain(cell) for row in rows for cell in row):
            self.error('matrix must contain a nonempty cell')
        if any(len(row) != len(rows[0]) for row in rows):
            self.error('matrix rows must have the same number of columns')
        return Matrix(tuple(rows), environment)

    def delimiter(self):
        self.skip_space()
        token = self.peek()
        if token not in _DELIMITERS:
            self.error('expected a delimiter after \\left or \\right')
        self.take()
        return _DELIMITERS[token]


def parse(source):
    """Parse the supported LaTeX subset into an AST."""
    text = str(source or '').strip()
    for left, right in (('$$', '$$'), ('\\[', '\\]'), ('\\(', '\\)'), ('$', '$')):
        if text.startswith(left):
            if len(text) < len(left)+len(right) or not text.endswith(right):
                raise FormulaError('unclosed math delimiter', 0)
            text = text[len(left):-len(right)].strip()
            break
    if not text:
        raise FormulaError('empty formula', 0)
    node = _Parser(text).parse()
    if not to_plain(node):
        raise FormulaError('empty formula', 0)
    return node


# --------------------------------------------------------------------------------------------
# Projections
# --------------------------------------------------------------------------------------------

def _xml(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _run_props(size_px=None, color=None, face='Cambria Math'):
    """Text run properties for every math run: size, colour and the math face."""
    if size_px is None and not color and not face:
        return ''
    attributes = ' lang="en-US"'
    if size_px is not None:
        attributes += f' sz="{round(size_px * 75)}"'
    fill = (f'<a:solidFill><a:srgbClr val="{_xml(color.lstrip("#"))}" />'
            '</a:solidFill>') if color else ''
    face_xml = f'<a:latin typeface="{_xml(face)}" />' if face else ''
    return f'<a:rPr{attributes}>{fill}{face_xml}</a:rPr>'


def _omml_row(node, props=''):
    if isinstance(node, Row):
        return ''.join(_omml_row(child, props) for child in node.children)
    return _omml_node(node, props)


def _omml_fenced(body, left, right, props, *, matrix=False, fraction_cells=False):
    # Office's extensible bracket ink falls inside its nominal math bounds. A larger delimiter
    # control face gives fraction-bearing matrices enough cap/descender coverage. Plain matrices
    # keep native sizing: applying the same enlargement there produces oversized brackets.
    # Cell runs retain their authored size; native probes cover this separately from metrics.
    fence_props = (re.sub(r'\bsz="(\d+)"', lambda m: f'sz="{round(int(m[1])*1.5)}"', props)
                   if matrix and fraction_cells else props)
    shape = 'centered' if matrix else 'match'
    return (f'<m:d><m:dPr><m:begChr m:val="{_xml(left)}" />'
            f'<m:endChr m:val="{_xml(right)}" /><m:grow m:val="1" />'
            f'<m:shp m:val="{shape}" /><m:ctrlPr>{fence_props}</m:ctrlPr></m:dPr>'
            f'<m:e>{body}</m:e></m:d>')


def _omml_node(node, props=''):
    if isinstance(node, Space):
        spacing = '\u2003'*node.em
        return (f'<m:r><m:rPr><m:nor /></m:rPr>{props}'
                f'<m:t xml:space="preserve">{spacing}</m:t></m:r>')
    if isinstance(node, Matrix):
        # DrawingML math prohibits mcJc and custom matrix spacing; native defaults apply. Keep blank cells
        # as empty arguments and hide their editor placeholders, never fill them with zeros.
        columns = len(node.rows[0])
        value = (f'<m:m><m:mPr><m:baseJc m:val="center" /><m:plcHide m:val="1" />'
                 f'<m:mcs><m:mc><m:mcPr><m:count m:val="{columns}" /></m:mcPr></m:mc></m:mcs>'
                 f'<m:ctrlPr>{props}</m:ctrlPr></m:mPr>')
        value += ''.join('<m:mr>' + ''.join(f'<m:e>{_omml_row(cell, props)}</m:e>' for cell in row)
                         + '</m:mr>' for row in node.rows) + '</m:m>'
        left, right = MATRIX_DELIMITERS[node.environment]
        if left or right:
            value = _omml_fenced(value, left, right, props, matrix=True,
                                 fraction_cells=any(isinstance(n, Frac) for n in _walk(node)))
        return value
    if isinstance(node, Text):
        if node.value.strip() == '':
            return ''
        style = '<m:rPr><m:nor /></m:rPr>' if node.upright else ''
        return f'<m:r>{style}{props}<m:t xml:space="preserve">{_xml(node.value)}</m:t></m:r>'
    if isinstance(node, Row):
        return _omml_row(node, props)
    if isinstance(node, Frac):
        return (f'<m:f><m:fPr><m:ctrlPr>{props}</m:ctrlPr></m:fPr>'
                f'<m:num>{_omml_row(node.numerator, props)}</m:num>'
                f'<m:den>{_omml_row(node.denominator, props)}</m:den></m:f>')
    if isinstance(node, Sqrt):
        degree = _omml_row(node.degree, props) if node.degree is not None else ''
        return (f'<m:rad><m:radPr><m:degHide m:val="{int(node.degree is None)}" />'
                f'<m:ctrlPr>{props}</m:ctrlPr></m:radPr>'
                f'<m:deg>{degree}</m:deg>'
                f'<m:e>{_omml_row(node.body, props)}</m:e></m:rad>')
    if isinstance(node, Styled):
        # Apply the style to leaf runs without introducing WordprocessingML into DrawingML.
        from xml.etree import ElementTree as ET
        root = ET.fromstring(f'<root xmlns:m="{MATH_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                             f'{_omml_row(node.body, props)}</root>')
        for run in root.iter(f'{{{MATH_NS}}}r'):
            properties = run.find(f'{{{MATH_NS}}}rPr')
            if properties is None:
                properties = ET.Element(f'{{{MATH_NS}}}rPr')
                run.insert(0, properties)
            if properties.find(f'{{{MATH_NS}}}sty') is None:
                ET.SubElement(properties, f'{{{MATH_NS}}}sty', {f'{{{MATH_NS}}}val': node.style})
        return ''.join(ET.tostring(child, encoding='unicode') for child in root)
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
                f'<m:limLoc m:val="undOvr" /><m:ctrlPr>{props}</m:ctrlPr></m:naryPr>{sub}{sup}'
                f'<m:e>{_omml_row(node.body, props)}</m:e></m:nary>')
    if isinstance(node, Group):
        return _omml_fenced(_omml_row(node.body, props), node.left, node.right, props,
                            matrix=any(isinstance(n, Matrix) for n in _walk(node.body)),
                            fraction_cells=any(isinstance(n, Frac) for n in _walk(node.body)))
    raise TypeError(f'unsupported node: {node!r}')


def to_omml(node, size_px=None, color=None, face='Cambria Math'):
    """The ``m:oMath`` payload (without the wrapping paragraph)."""
    props = _run_props(size_px, color, face)
    return (f'<m:oMath xmlns:m="{MATH_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f'{_omml_row(node, props)}</m:oMath>')


def to_omml_paragraph(node, size_px=None, color=None, face='Cambria Math'):
    """A display equation wrapped the way PowerPoint stores it, including the plain fallback."""
    props = _run_props(size_px, color, face)
    fallback = _xml(to_plain(node))
    return (
        '<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main">'
        '<mc:AlternateContent><mc:Choice Requires="a14"><a14:m>'
        f'<m:oMathPara xmlns:m="{MATH_NS}"><m:oMath>{_omml_row(node, props)}</m:oMath></m:oMathPara>'
        '</a14:m></mc:Choice>'
        f'<mc:Fallback><a:r>{props}<a:t xml:space="preserve">{fallback}</a:t></a:r></mc:Fallback>'
        '</mc:AlternateContent></a:p>')


def _plain(node):
    if isinstance(node, Space):
        return ' '*node.em
    if isinstance(node, Matrix):
        rows = '; '.join(', '.join(_plain(cell).strip() for cell in row) for row in node.rows)
        left, right = MATRIX_DELIMITERS[node.environment]
        return (left or '[') + rows + (right or ']')
    if isinstance(node, Text):
        return node.value
    if isinstance(node, Row):
        return ''.join(_plain(child) for child in node.children)
    if isinstance(node, Frac):
        return f'{_grouped_plain(node.numerator)}/{_grouped_plain(node.denominator)}'
    if isinstance(node, Sqrt):
        body = _plain(node.body)
        radical = f'√{body}' if len(body) == 1 else f'√({body})'
        if node.degree is not None:
            degree = _plain(node.degree)
            radical = (degree.translate(SUPERSCRIPT) if degree.isdigit() else f'[{degree}]') + radical
        return radical
    if isinstance(node, Styled):
        return _plain(node.body)
    if isinstance(node, Scripts):
        base = _grouped_plain(node.base)
        text = base
        if node.sub is not None:
            sub = _plain(node.sub)
            text += sub.translate(SUBSCRIPT) if sub.isdigit() else f'_{_script_plain(sub)}'
        if node.sup is not None:
            sup = _plain(node.sup)
            can_lift = sup and all(ord(char) in SUPERSCRIPT for char in sup)
            text += sup.translate(SUPERSCRIPT) if can_lift else f'^{_script_plain(sup)}'
        return text
    if isinstance(node, Nary):
        limits = ''
        if node.sub is not None:
            limits += _plain(node.sub).translate(SUBSCRIPT)
        if node.sup is not None:
            limits += f'^{_plain(node.sup)}'
        return f'{node.char}{limits} {_plain(node.body).lstrip()}'
    if isinstance(node, Group):
        if isinstance(node.body, Matrix) and node.body.environment == 'matrix':
            rows = '; '.join(', '.join(_plain(cell).strip() for cell in row) for row in node.body.rows)
            return f'{node.left}{rows}{node.right}'
        return f'{node.left}{_plain(node.body)}{node.right}'
    raise TypeError(f'unsupported node: {node!r}')


def _grouped_plain(node):
    """A fraction operand keeps its meaning in plain text: ``1/(1+e)``, not ``1/1+e``."""
    text = _plain(node)
    if isinstance(node, (Matrix, Group)):
        return text
    compound = ((isinstance(node, Row) and len(node.children) > 1)
                or isinstance(node, (Frac, Scripts, Sqrt, Nary)))
    if compound or any(char in text for char in '+-'):
        return f'({text})'
    return text


def _script_plain(text):
    return text if len(text) == 1 else f'({text})'


def to_plain(node):
    """Unicode fallback: what the reader sees when OMML is not available."""
    return _plain(node).strip()


@dataclass(frozen=True)
class Metrics:
    width: float          # css px at 96 dpi
    height: float
    exact: bool           # False when a heuristic had to be used
    depth: float = 0.0    # baseline to bottom; matrix/row composition needs a shared baseline

    def as_box(self):
        return [0.0, 0.0, self.width, self.height]


@lru_cache(maxsize=4096)
def measure(node, font_size_px=24.0):
    """Width/height of the typeset formula, in css pixels.

    matplotlib's mathtext is the same offline font-metric source used elsewhere in the compiler, so
    the number does not depend on a LaTeX installation. Constructs mathtext cannot set (CJK inside
    ``\\text``, for one) fall back to a width estimate and are marked ``exact=False`` so the caller
    can raise a REVIEW instead of silently trusting an approximation.
    """
    if any(isinstance(item, Matrix) for item in _walk(node)):
        return _structural_metrics(node, font_size_px)
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
        # Without the dollar delimiters mathtext measures literal TeX source, not the equation.
        width, height, depth, _, _ = parser.parse(f'${source}$', dpi=96,
                                                  prop=FontProperties(size=font_size_px * .75))
        metrics = Metrics(round(float(width), 2), round(float(height), 2), True, round(float(depth), 2))
    except Exception:
        metrics = _estimate(plain, font_size_px, node)
    if any(isinstance(item, (Frac, Sqrt, Nary)) for item in _walk(node)):
        # mathtext uses reduced fraction operands and different extensible operators. Native
        # display math can be taller, especially a radical around a sum or full-size cell fraction.
        # Keep its typeset width/baseline but bound both sides by the native structural estimate.
        native = _structural_metrics(node, font_size_px)
        depth = max(metrics.depth, native.depth)
        ascent = max(metrics.height-metrics.depth, native.height-native.depth)
        return Metrics(round(max(metrics.width, native.width), 2), round(ascent+depth, 2), False,
                       round(depth, 2))
    return metrics


def _structural_metrics(node, size):
    """Measure each cell, then compose rows/columns and surrounding math on a shared baseline.

    mathtext has no matrix environment. Serializing a matrix to a text estimate collapses its
    height and adds every cell to its width. These conservative structural metrics retain two
    dimensions, with native review (exact=False) for Office's delimiter and row spacing.
    """
    def result(width, height, depth):
        return Metrics(round(width, 2), round(height, 2), False, round(depth, 2))

    if isinstance(node, (Text, Space)):
        return measure(node, size)
    if isinstance(node, Matrix):
        cells = [[measure(cell, size) if to_plain(cell).strip() else Metrics(0, size, True, size*.2)
                  for cell in row] for row in node.rows]
        widths = [max(row[c].width for row in cells) for c in range(len(cells[0]))]
        heights = [max(size, max(m.height-m.depth for m in row) + max(m.depth for m in row))
                   for row in cells]
        height = sum(heights) + size*.35*(len(cells)-1) + size*.25
        width = sum(widths) + size*(len(widths)-1)
        if node.environment != 'matrix':
            fraction_cells = any(isinstance(n, Frac) for n in _walk(node))
            height = max(height, size*1.8 if fraction_cells else 0)
            width += 2*max(size*(.6 if fraction_cells else .4), height*.06)
        return result(width, height, height/2-size*.25)
    if isinstance(node, Row):
        parts, scalar = [], []
        for child in node.children:
            if any(isinstance(item, (Matrix, Frac, Sqrt, Nary)) for item in _walk(child)):
                if scalar and (to_plain(Row(tuple(scalar))).strip() or any(isinstance(n, Space) for n in scalar)):
                    parts.append(measure(Row(tuple(scalar)), size))
                scalar = []
                parts.append(measure(child, size))
            else:
                scalar.append(child)
        if scalar and (to_plain(Row(tuple(scalar))).strip() or any(isinstance(n, Space) for n in scalar)):
            parts.append(measure(Row(tuple(scalar)), size))
        ascent = max((m.height-m.depth for m in parts), default=0)
        depth = max((m.depth for m in parts), default=0)
        return result(sum(m.width for m in parts), ascent+depth, depth)
    if isinstance(node, Styled):
        return measure(node.body, size)
    if isinstance(node, Group):
        body = measure(node.body, size)
        fences = bool(node.left) + bool(node.right)
        matrix = any(isinstance(n, Matrix) for n in _walk(node.body))
        fraction_cells = matrix and any(isinstance(n, Frac) for n in _walk(node.body))
        height = max(body.height+size*.2, size*1.8 if fraction_cells and fences else 0)
        return result(body.width + fences*max(size*(.6 if fraction_cells else .4), body.height*.06),
                      height, body.depth+(height-body.height)/2)
    if isinstance(node, Scripts):
        base = measure(node.base, size)
        sup = measure(node.sup, size*.7) if node.sup is not None else Metrics(0, 0, True)
        sub = measure(node.sub, size*.7) if node.sub is not None else Metrics(0, 0, True)
        return result(base.width+max(sup.width, sub.width),
                      base.height+sup.height*.8+sub.height*.8, base.depth+sub.height*.8)
    if isinstance(node, Frac):
        num, den = measure(node.numerator, size), measure(node.denominator, size)
        num_h, den_h = max(size, num.height), max(size, den.height)
        return result(max(num.width, den.width)+size*.3,
                      num_h+den_h+size*.5, den_h+size*.2)
    if isinstance(node, Sqrt):
        body = measure(node.body, size)
        degree = measure(node.degree, size*.5) if node.degree is not None else Metrics(0, 0, True)
        return result(body.width+size*.65+degree.width, body.height+size*.7, body.depth+size*.15)
    if isinstance(node, Nary):
        body = measure(node.body, size)
        op = measure(Text(node.char), size*1.3)
        limits = [measure(limit, size*.7) for limit in (node.sub, node.sup) if limit is not None]
        height = max(body.height, max(op.height, size*2)+sum(max(size*.7, m.height) for m in limits)+size*.2)
        return result(body.width+max([op.width, *(m.width for m in limits)])+size*.2,
                      height, height/2-size*.25)
    raise TypeError(f'unsupported matrix expression: {node!r}')


def _estimate(plain, font_size_px, node):
    width = sum(2.0 if '\u3400' <= char <= '\u9fff' else 1.0 for char in plain)
    depth = 1.6 if any(isinstance(item, Frac) for item in _walk(node)) else 1.0
    return Metrics(round(width * font_size_px * .55, 2),
                   round(font_size_px * 1.25 * depth, 2), False)


def _walk(node):
    yield node
    if isinstance(node, Matrix):
        for row in node.rows:
            for cell in row:
                yield from _walk(cell)
    for field in ('children',):
        for child in getattr(node, field, ()):
            yield from _walk(child)
    for field in ('numerator', 'denominator', 'base', 'sup', 'sub', 'body', 'degree'):
        child = getattr(node, field, None)
        if isinstance(child, Node):
            yield from _walk(child)


def to_latex(node):
    """Back to the mathtext-compatible subset; used for measurement and error messages."""
    if isinstance(node, Space):
        return r'\quad ' if node.em == 1 else r'\qquad '
    if isinstance(node, Matrix):
        cells = r' \\ '.join(' & '.join(to_latex(cell) for cell in row) for row in node.rows)
        return f'\\begin{{{node.environment}}}{cells}\\end{{{node.environment}}}'
    if isinstance(node, Text):
        if not node.upright and node.value.isspace():
            return ''
        escaped = ''.join({'{': r'\{', '}': r'\}', '$': r'\$', '%': r'\%', '&': r'\&',
                           '#': r'\#', '_': r'\_', ' ': r'\ '}.get(char, char) for char in node.value)
        return f'\\mathrm{{{escaped}}}' if node.upright else escaped
    if isinstance(node, Row):
        return ''.join(to_latex(child) for child in node.children)
    if isinstance(node, Frac):
        return f'\\frac{{{to_latex(node.numerator)}}}{{{to_latex(node.denominator)}}}'
    if isinstance(node, Sqrt):
        degree = f'[{to_latex(node.degree)}]' if node.degree is not None else ''
        return f'\\sqrt{degree}{{{to_latex(node.body)}}}'
    if isinstance(node, Styled):
        command = {'p': 'mathrm', 'b': 'mathbf', 'i': 'mathit'}[node.style]
        return f'\\{command}{{{to_latex(node.body)}}}'
    if isinstance(node, Scripts):
        text = '{' + to_latex(node.base) + '}'
        if node.sub is not None:
            text += f'_{{{to_latex(node.sub)}}}'
        if node.sup is not None:
            text += f'^{{{to_latex(node.sup)}}}'
        return text
    if isinstance(node, Nary):
        text = '\\' + next(command for command in NARY if OPERATORS[command] == node.char)
        if node.sub is not None:
            text += f'_{{{to_latex(node.sub)}}}'
        if node.sup is not None:
            text += f'^{{{to_latex(node.sup)}}}'
        return text + f' {to_latex(node.body)}'
    if isinstance(node, Group):
        delimiters = {'': '.', '{': r'\{', '}': r'\}'}
        return (f'\\left{delimiters.get(node.left, node.left)}{to_latex(node.body)}'
                f'\\right{delimiters.get(node.right, node.right)}')
    raise TypeError(f'unsupported node: {node!r}')
