"""Explain a compiler or QA code: who raises it, why, and what to change.

The code inventory is derived from this package's own source by AST, so a gate
cannot ship without at least a source-grounded entry. Authored remediation is
kept in ``CATALOG``; codes that are discovered but not authored still explain
themselves through their raise sites and literal messages.

The shape mirrors the search/retrieve workflow used by agent skill packs: the
whole catalogue stays out of context, and one code is fetched on demand.
"""

from __future__ import annotations

import ast
import difflib
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent

SEVERITY_ORDER = ('FAIL', 'WARNING', 'REVIEW', 'INFO')

# A code literal: upper case, short, at least five characters.
GATE = re.compile(r'^[A-Z][A-Z0-9_]{4,}$')

# callee -> where the code, the literal message, and the severity sit.
# ``files`` restricts a common callee name to the module that defines it.
_RAISERS = {
    'issue': {'code': (0, 'rule'), 'message': 2, 'severity': (1, 'severity'), 'default': 'FAIL'},
    'check': {'code': (None, 'rule'), 'message': 1, 'severity': (None, 'severity'),
              'default': 'FAIL', 'code_default': 'IR_INVALID', 'files': ('ir.py',)},
    'add': {'code': (0, None), 'message': 1, 'severity': (3, 'severity'), 'default': 'FAIL'},
    'LayoutTreeError': {'code': (1, None), 'message': 2, 'default': 'FAIL'},
    'GraphicLayoutError': {'code': (0, None), 'message': 1, 'default': 'FAIL'},
    'ChartLayoutError': {'code': None, 'message': 0, 'default': 'FAIL'},
}
# classes whose code lives on the class itself rather than in the call
_STATIC = {'ChartLayoutError': 'CHART_CAPACITY'}


def _callee(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _message(node):
    """Literal text, or an f-string reduced to its fixed parts with {} holes."""
    literal = _literal(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            literal = _literal(piece)
            parts.append(literal if literal is not None else '{}')
        text = ''.join(parts).strip()
        return text or None
    return None


def _site(path, node, message, severity, source=None, function=None):
    snippet = None
    if source:
        line = source[node.lineno - 1].strip() if node.lineno - 1 < len(source) else ''
        snippet = line[:160] or None
    return {'module': path.stem, 'line': node.lineno, 'message': message,
            'severity': severity, 'function': function, 'snippet': snippet}


def _parents(tree):
    found = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            found[child] = node
    return found


def _enclosing(node, parents):
    """Nearest function that raises, so a bare ``check(False, message)`` still says where."""
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _gate_literals(expression):
    """Code-shaped literals anywhere in an expression: if/else arms, dict values, get() defaults."""
    return [value for child in ast.walk(expression)
            if (value := _literal(child)) is not None and _looks_like_a_code(value)]


def _looks_like_a_code(text):
    """A code is upper case and whole; a trailing underscore means a string prefix."""
    return bool(GATE.match(text)) and not text.endswith('_')


def _assigned_codes(name, function):
    """Literals assigned to ``name`` inside the raising function, e.g. ``code = {...}.get(..)``."""
    found = []
    for child in ast.walk(function):
        if isinstance(child, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in child.targets):
            found += _gate_literals(child.value)
    return found


def _severity(node, position, keyword, default):
    """Worst severity the call can report; a conditional picks between two literals."""
    target = node.args[position] if position is not None and len(node.args) > position else None
    if target is None and keyword:
        target = next((word.value for word in node.keywords if word.arg == keyword), None)
    if target is None:
        return default
    named = [value for child in ast.walk(target)
             if (value := _literal(child)) is not None and value in SEVERITY_ORDER]
    return sorted(named, key=SEVERITY_ORDER.index)[0] if named else default


def _composed_prefix(node):
    """``'EXPLAIN_VIZ_' + status`` builds a code at runtime; the prefix is all a scanner sees."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal(node.left)
        if left and left.endswith('_') and GATE.match(left):
            return left
    return None


def _codes(node, spec, function):
    """(code, is_family) for every code one call can raise; a local variable resolves in place."""
    static = spec.get('code') is None
    if static:
        return [(spec['code_default'], False)] if spec.get('code_default') else []
    position, keyword = spec['code']
    target = node.args[position] if position is not None and len(node.args) > position else None
    if target is None and keyword:
        target = next((word.value for word in node.keywords if word.arg == keyword), None)
    if target is None:
        return [(spec['code_default'], False)] if spec.get('code_default') else []
    direct = _literal(target)
    if direct and _looks_like_a_code(direct):
        return [(direct, False)]
    prefix = _composed_prefix(target)
    if prefix:
        return [(prefix, True)]
    if isinstance(target, ast.Name) and function is not None:
        resolved = _assigned_codes(target.id, function)
        if resolved:
            return [(code, False) for code in resolved]
    return [(code, False) for code in _gate_literals(target)]


def _dict_gate(node):
    """Some findings are built as ``{'rule': 'CODE', 'severity': ...}`` dicts."""
    mapping = {_literal(key): value for key, value in zip(node.keys, node.values)
               if key is not None and _literal(key)}
    code = _literal(mapping['rule']) if 'rule' in mapping else None
    if not code or not _looks_like_a_code(code):
        return None
    severity = _literal(mapping['severity']) if 'severity' in mapping else None
    message = _message(mapping['message']) if 'message' in mapping else None
    return code, severity if severity in SEVERITY_ORDER else None, message


def _tuple_gate(node):
    """Gates also travel as ``('CODE', 'FAIL', message)`` appended to a findings list."""
    if not isinstance(node, ast.Tuple) or len(node.elts) < 2:
        return None
    code, severity = _literal(node.elts[0]), _literal(node.elts[1])
    if not code or not _looks_like_a_code(code) or severity not in SEVERITY_ORDER:
        return None
    message = _message(node.elts[2]) if len(node.elts) > 2 else None
    return code, severity, message


def discover(root=None):
    """Map every code raised in this package to the sites that raise it."""
    return _scan(str(Path(root or PACKAGE)))[0]


def families(root=None):
    """Composed-code prefixes, e.g. ``EXPLAIN_VIZ_`` whose suffix is decided at runtime."""
    return _scan(str(Path(root or PACKAGE)))[1]


@lru_cache(maxsize=8)
def _scan(base):
    found, composed = defaultdict(list), defaultdict(list)
    for path in sorted(Path(base).rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        try:
            text = path.read_text(encoding='utf-8')
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue
        source = text.splitlines()
        parents = _parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                pair = _dict_gate(node)
                if pair:
                    code, severity, message = pair
                    function = _enclosing(node, parents)
                    found[code].append(_site(path, node, message, severity, source,
                                             function.name if function is not None else None))
                continue
            if not isinstance(node, ast.Call):
                continue
            function = _enclosing(node, parents)
            where = function.name if function is not None else None
            for argument in node.args:
                pair = _tuple_gate(argument)
                if pair:
                    code, severity, message = pair
                    found[code].append(_site(path, node, message, severity, source, where))
            name = _callee(node.func)
            spec = _RAISERS.get(name)
            if spec is None:
                continue
            if spec.get('files') and path.name not in spec['files']:
                continue
            codes = ([(_STATIC.get(name), False)] if name in _STATIC
                     else _codes(node, spec, function))
            if not codes:
                continue
            message = None
            if spec.get('message') is not None and len(node.args) > spec['message']:
                message = _message(node.args[spec['message']])
            severity = spec['default']
            if spec.get('severity'):
                severity = _severity(node, *spec['severity'], spec['default'])
            site = _site(path, node, message, severity, source, where)
            for code, is_family in codes:
                (composed if is_family else found)[code].append(dict(site))
    order = lambda sites: sorted(sites, key=lambda s: (s['module'], s['line']))
    return ({code: order(sites) for code, sites in sorted(found.items())},
            {code: order(sites) for code, sites in sorted(composed.items())})


def mentions(code, root=None):
    """Where a code is named but not raised through a recognisable call."""
    return _mentions(code, str(Path(root or PACKAGE)))


@lru_cache(maxsize=64)
def _mentions(code, base):
    hits = []
    for path in sorted(Path(base).rglob('*.py')):
        if path.name == Path(__file__).name or '__pycache__' in path.parts:
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            if code in line:
                hits.append({'module': path.stem, 'line': number, 'message': None,
                             'severity': None, 'function': None,
                             'snippet': line.strip()[:160]})
    return hits


def severity_of(sites):
    """Worst severity among the sites, or None when a code raises instead."""
    for name in SEVERITY_ORDER:
        if any(site['severity'] == name for site in sites):
            return name
    return None


def _longest_prefix(code, keys):
    best = None
    for key in keys:
        if key.endswith('_') and code.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return best


def _authored(code):
    """Exact guidance, else guidance written once for a composed family."""
    if code in CATALOG:
        return CATALOG[code]
    prefix = _longest_prefix(code, CATALOG)
    return CATALOG.get(prefix) if prefix else None


def explain(code, root=None):
    """Return one structured explanation; the code must exist in the source."""
    sites = discover(root).get(code, [])
    entry = _authored(code)
    family = None
    if not sites:
        prefix = _longest_prefix(code, families(root))
        if prefix:
            family, sites = prefix, families(root)[prefix]
    if not sites:
        sites = mentions(code, root)
    if not sites and entry is None:
        raise KeyError(code)
    row = {
        'code': code,
        'authored': entry is not None,
        'family': family,
        'severity': severity_of(sites),
        'summary': (entry or {}).get('summary') or next(
            (site['message'] for site in sites if site['message']), code),
        'cause': (entry or {}).get('cause'),
        'fixes': [{'action': action, 'cost': cost, 'detail': detail}
                  for action, cost, detail in (entry or {}).get('fixes', ())],
        'see': list((entry or {}).get('see', ())),
        'count': len(sites),
        'sites': sites,
    }
    return row


def search(text, root=None):
    """Rank codes against a free-text query over the code, summary, and cause."""
    text = (text or '').strip().lower()
    if not text:
        return []
    scored = []
    for code in discover(root):
        entry = _authored(code) or {}
        blob = ' '.join(filter(None, (code, entry.get('summary'), entry.get('cause')))).lower()
        if text in code.lower() or text in blob:
            scored.append((0, code))
        else:
            ratio = difflib.SequenceMatcher(None, text, code.lower()).ratio()
            if ratio >= .5:
                scored.append((1, code))
    return [code for _, code in sorted(scored)]


def unauthored(root=None, severity=None):
    """Codes that exist in the source but still lack authored remediation."""
    found = discover(root)
    return [code for code in found if _authored(code) is None
            and (severity is None or severity_of(found[code]) == severity)]


def inventory(root=None):
    """Every code with its severity and whether guidance is authored."""
    found = discover(root)
    return [{'code': code, 'severity': severity_of(found[code]),
             'authored': _authored(code) is not None, 'sites': len(found[code])}
            for code in found]


def render(row):
    """Human-readable form of one ``explain`` record."""
    count = row['count']
    header = f"{row['code']}  [{row['severity'] or 'unknown'}]  ({count} site{'s' if count != 1 else ''})"
    lines = [header, '']
    lines.append(row['summary'] or '(no summary)')
    if row.get('family'):
        lines += ['', f"This code is composed at runtime from the prefix {row['family']}."]
    if row['cause']:
        lines += ['', 'Why', *[f'  {line}' for line in _wrap(row['cause'])]]
    if row['fixes']:
        lines += ['', 'Fix, cheapest first']
        for number, fix in enumerate(row['fixes'], 1):
            lines.append(f"  {number}. [{fix['cost']}] {fix['action']}")
            lines += [f'     {line}' for line in _wrap(fix['detail'])]
    if row['sites']:
        lines += ['', 'Raised at']
        for site in row['sites']:
            message = site['message'] or site['snippet'] or ''
            where = f"{site['module']}.py:{site['line']}"
            if site['function']:
                where += f" ({site['function']})"
            lines.append(f'  {where}  {message}'.rstrip())
    if row['see']:
        lines += ['', 'Read', *[f'  {path}' for path in row['see']]]
    if not row['authored']:
        lines += ['', 'No authored guidance yet; the raise sites above are all this code has.']
    return '\n'.join(lines)


def _wrap(text, width=76):
    words, lines, line = text.split(), [], ''
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f'{line} {word}'.strip()
    return lines + ([line] if line else [])


# Authored remediation. Costs are relative to a rebuild, not to authoring effort.
CATALOG = {
    'INSUFFICIENT_DRAWING_SPACE': {
        'summary': 'A native graphic cannot reach its readable minimum width, or no height '
                   'in the first-fit ladder fits the region it was given.',
        'cause': 'A graphic starts at 96 px and climbs 96/128/160/200/240/272/320/384/448/512 '
                 '640/768/1024/1536. Merged layers and multi-node diagrams need 320-384 px; '
                 'a plain chain needs 240 px. When the region is shorter than the first rung, '
                 'or narrower than the minimum width, the page fails rather than shrinking '
                 'the drawing below legibility.',
        'fixes': (
            ('switch_to_chain', 'cheap', 'Replace a merged or multi-node layer with a chain or a '
             'two-node form; chains cost 240 px where layers cost 320-384 px.'),
            ('widen_region', 'cheap', 'Give the graphic the full content width and move prose '
             'into a list block beneath it, instead of a side-by-side split.'),
            ('switch_to_two_columns', 'medium', 'Move part of the copy out of the body region so '
             'the graphic keeps a taller box.'),
            ('split_slide', 'expensive', 'Give the graphic its own page. Last resort: it costs a '
             'slide and breaks the argument flow.'),
        ),
        'see': ('docs/native-graphics.md', 'docs/composite-layouts.md'),
    },
    'INSUFFICIENT_LIST_SPACE': {
        'summary': 'An explicit native list needs at least 520 px of width in its region.',
        'cause': 'The list block keeps a fixed minimum width so markers and hanging indents stay '
                 'aligned. A column that is narrower than 520 px cannot host one, even when the '
                 'total area would be large enough.',
        'fixes': (
            ('reweight_columns', 'cheap', 'Raise the list column weight; a chart beside it usually '
             'survives at [1.15, 1].'),
            ('stack_above', 'cheap', 'Put the visual in a row above and let the list span the full '
             'content width.'),
            ('drop_to_prose', 'medium', 'Keep the block as prose when the region cannot host a '
             'list; a squeezed list reads worse than a paragraph.'),
        ),
        'see': ('docs/native-lists.md',),
    },
    'INSUFFICIENT_FIGURE_SPACE': {
        'summary': 'A figure cannot fit the region left for it at its minimum legible size.',
        'cause': 'Figures carry a hard minimum derived from the source resolution and the '
                 'scientific detail that must stay readable. Two panels side by side often '
                 'exceed the body height once a caption and a list are also present.',
        'fixes': (
            ('drop_a_panel', 'cheap', 'Keep the panel that carries the argument and cite the other '
             'in the caption.'),
            ('row_then_list', 'cheap', 'Lay panels in a row above a full-width list rather than '
             'beside it.'),
            ('split_slide', 'medium', 'Give the figure its own page with a short reading.'),
        ),
        'see': ('docs/composite-layouts.md',),
    },
    'INSUFFICIENT_TABLE_SPACE': {
        'summary': 'A native table cannot fit its rows at the minimum cell height.',
        'cause': 'Table height grows with the row count times the minimum cell height, which is '
                 'fixed by the smallest legible body size. A table wider than the region also '
                 'wraps cells and pushes rows past the available height.',
        'fixes': (
            ('cut_columns', 'cheap', 'Remove a column that repeats information already in the '
             'prose.'),
            ('cut_rows', 'cheap', 'Keep the rows the argument needs; move the rest into one '
             'listed sentence.'),
            ('full_width', 'medium', 'Give the table the full content width and put the reading '
             'beneath it.'),
        ),
        'see': ('docs/native-tables.md',),
    },
    'INSUFFICIENT_FORMULA_SPACE': {
        'summary': 'A formula block cannot be placed at a legible size in the remaining region.',
        'cause': 'Formulas are measured with their real glyph metrics, including radicals, '
                 'indices, and every sub/superscript. A tall fraction or a stacked limit needs '
                 'more vertical room than the ladder offers once prose and anchors are placed.',
        'fixes': (
            ('drop_an_anchor', 'cheap', 'Detach an explanation anchor so the formula stands as '
             'its own row.'),
            ('widen_region', 'cheap', 'Give the formula the full content width; inline forms '
             'often fit where a two-column split does not.'),
            ('split_slide', 'medium', 'Move the derivation to its own page.'),
        ),
        'see': ('docs/inline-math.md',),
    },
    'INSUFFICIENT_CHART_SPACE': {
        'summary': 'A chart cannot reach its minimum canvas of 420x260 px.',
        'cause': 'Charts are drawn natively, so axis labels, ticks, and the legend need real '
                 'space. Below the minimum canvas the renderer would drop labels rather than '
                 'shrink them.',
        'fixes': (
            ('widen_region', 'cheap', 'Give the chart the full content width; keep the reading '
             'beneath it.'),
            ('drop_the_legend', 'cheap', 'Name the series in the reading and let the chart carry '
             'no legend.'),
            ('split_slide', 'medium', 'Give the chart its own page.'),
        ),
        'see': ('docs/chart-ir.md',),
    },
    'INSUFFICIENT_TEXT_SPACE': {
        'summary': 'A copy block cannot fit even at the minimum body size.',
        'cause': 'The block was measured against the real font metrics for its region and still '
                 'overflowed. This is a content-versus-region mismatch, not a rendering fault.',
        'fixes': (
            ('shorten_copy', 'cheap', 'Cut the sentence that repeats the title.'),
            ('widen_region', 'cheap', 'Reclaim width from a neighbouring visual.'),
            ('split_slide', 'medium', 'Move the trailing point to the next page.'),
        ),
        'see': ('docs/content-projection.md',),
    },
    'TEXT_ONLY_PAGE': {
        'summary': 'The page carries no figure, table, chart, or native graphic.',
        'cause': 'A research deck reads as a wall of prose when a page has only text. The gate '
                 'runs when the build requires visuals; a table counts only at 2x2 or larger, '
                 'and an inline formula does not count as a carrier.',
        'fixes': (
            ('add_a_visual', 'medium', 'Add a diagram that explains the relation the prose '
             'asserts, not a decorative shape.'),
            ('add_a_table', 'medium', 'Turn a comparison already in the prose into a native '
             'table.'),
            ('merge_pages', 'cheap', 'Fold the page into a neighbour that already carries a '
             'visual.'),
        ),
        'see': ('docs/scientific-visual-planner.md',),
    },
    'SPLIT_REQUIRED': {
        'summary': 'Content exceeds the capacity of its frame.',
        'cause': 'Measured characters against the frame capacity; the overflow ratio is reported '
                 'with the error.',
        'fixes': (
            ('enable_overflow_repair', 'cheap', 'Let the compiler split into a continuation '
             'page.'),
            ('reduce_density', 'cheap', 'Drop detail that the talk does not need.'),
            ('spacious_frame', 'medium', 'Use the spacious frame variant for more room.'),
        ),
        'see': ('docs/deck-compiler-v2.md',),
    },
    'CONTENT_PROJECTION_FAILED': {
        'summary': 'The page shows copy, a number, or a figure the approved projection does not '
                   'allow.',
        'cause': 'Every visible string must trace to the page display_copy with a source '
                 'reference. Graphic node labels, chart annotations, panel titles, and numbers '
                 'are projected too, so a label invented while drawing the diagram fails here as '
                 'well.',
        'fixes': (
            ('register_the_label', 'cheap', 'Add the exact string to the page display_copy with '
             'source_refs and basis "paper", then reference it from the graphic label.'),
            ('reuse_approved_wording', 'cheap', 'Reword the label to a phrase already approved '
             'for this page.'),
            ('bind_the_number', 'medium', 'A number needs its origin; if it is arithmetic over '
             'measured values, declare it as derived rather than letting it read as measured.'),
        ),
        'see': ('docs/content-projection.md',),
    },
    'FORMULA_MISSING': {
        'summary': 'A formula the story requires is absent from the page.',
        'cause': 'The explanation contract lists the formula as required evidence, and the page '
                 'rendered without it.',
        'fixes': (
            ('add_the_formula', 'cheap', 'Add the equation as a formula block, not as an image '
             'or as plain text.'),
            ('waive_explicitly', 'medium', 'Record an explicit waiver in the explanation '
             'contract if the talk does not need it.'),
        ),
        'see': ('docs/explanation-contract.md', 'docs/inline-math.md'),
    },
    'FORMULA_CONTENT_MISMATCH': {
        'summary': 'A formula exists but its structure differs from the required one.',
        'cause': 'The check compares radicals, root indices, and every sub/superscript, not just '
                 'the visible characters. A flattened or partially reconstructed equation fails.',
        'fixes': (
            ('restore_structure', 'cheap', 'Keep the radicand, the root index, and all '
             'sub/superscripts from the source.'),
            ('rebuild_from_source', 'medium', 'Re-derive the equation instead of editing the '
             'rendered form.'),
        ),
        'see': ('docs/inline-math.md',),
    },
    'IR_INVALID': {
        'summary': 'The Deck IR does not satisfy the schema contract.',
        'cause': 'The default rule for a structural check in validate(); the message names the '
                 'field that failed.',
        'fixes': (
            ('read_the_message', 'cheap', 'The message names the field and the expectation; fix '
             'that field before rerunning.'),
            ('start_from_an_example', 'medium', 'When several fields fail at once, compare '
             'against a shipped example IR instead of patching field by field.'),
        ),
        'see': ('docs/deck-compiler-v2.md',),
    },
    'NATIVE_RENDER_UNAVAILABLE': {
        'summary': 'The native PDF render did not run, so native evidence is missing.',
        'cause': 'OfficeCLI or PowerPoint could not export the candidate. This is a REVIEW item, '
                 'not proof that the deck is wrong.',
        'fixes': (
            ('check_officecli', 'cheap', 'Verify the backend is installed and the candidate is '
             'not open in another process.'),
            ('free_the_file', 'cheap', 'Close the file if a previous run still holds it; a locked '
             'pptx blocks the export.'),
        ),
        'see': ('docs/officecli-backend.zh-CN.md',),
    },
    'CHART_CAPACITY': {
        'summary': 'A chart cannot be drawn in the region it was given.',
        'cause': 'Two different failures share this code. A log axis rejects zero and negative '
                 'values outright, and the chart body cannot go below its minimum canvas because '
                 'axes, ticks, and a series need real space.',
        'fixes': (
            ('make_values_positive', 'cheap', 'On a log axis every point must be > 0; a measured '
             'zero usually means "not detected", so state the floor in the reading instead.'),
            ('widen_region', 'cheap', 'Give the chart the full content width and put the reading '
             'beneath it.'),
            ('drop_the_legend', 'cheap', 'Name the series in the reading; the legend is the first '
             'thing to go when the canvas is tight.'),
        ),
        'see': ('docs/chart-ir.md',),
    },
    'GRAPHIC_CAPACITY': {
        'summary': 'A native graphic has no room to lay out its own parts.',
        'cause': 'Each part carries a floor: a DAG layer needs 176 px per node, a funnel level '
                 'needs its label at 18 pt, a composite needs a component area, and a path needs '
                 'a drawable box. When the region cannot pay every floor, the graphic fails '
                 'instead of silently shrinking its labels.',
        'fixes': (
            ('fewer_layers', 'cheap', 'Reduce the layer or level count; four layers is close to '
             'the practical maximum in one body region.'),
            ('merge_nodes', 'cheap', 'Collapse sibling nodes that the talk treats as one step.'),
            ('full_width', 'medium', 'Give the graphic the full content width and move the prose '
             'into a list beneath it.'),
        ),
        'see': ('docs/native-graphics.md', 'docs/composite-layouts.md'),
    },
    'GRAPHIC_LABEL_CAPACITY': {
        'summary': 'No area is left for a label that clears the nodes and connectors.',
        'cause': 'Edge and node labels are placed at the label floor size, and a dense routing '
                 'leaves no rectangle that avoids both the shapes and the lines.',
        'fixes': (
            ('shorten_labels', 'cheap', 'Two or three words per label; the reading carries the '
             'rest.'),
            ('drop_one_edge', 'cheap', 'Remove a connector whose relation the reading states in '
             'words.'),
            ('simpler_route', 'medium', 'Switch the connector geometry; a straight edge needs no '
             'label clearance.'),
        ),
        'see': ('docs/native-graphics.md',),
    },
    'GRAPHIC_PAGE_CAPACITY': {
        'summary': 'The graphic, its context copy, and a source figure cannot share the page.',
        'cause': 'All three have size floors. A page that carries a diagram, a reading block, and '
                 'a source panel exceeds the body region before any of them reaches a comfortable '
                 'size.',
        'fixes': (
            ('drop_the_context_block', 'cheap', 'Let the reading beneath the graphic carry the '
             'context.'),
            ('split_slide', 'medium', 'Give the source figure its own page with a short caption.'),
            ('composite_region', 'medium', 'Use a composite body region so the panes are allocated '
             'together instead of competing.'),
        ),
        'see': ('docs/composite-layouts.md',),
    },
    'GRAPHIC_TEXT_OVERFLOW': {
        'summary': 'A node label does not fit its box at the label floor size.',
        'cause': 'Node boxes are measured with the real font metrics at the label size, and the '
                 'compiler will not shrink below that floor.',
        'fixes': (
            ('shorten_the_node', 'cheap', 'Keep the subject and the verb; move qualifiers into the '
             'reading.'),
            ('fewer_nodes', 'cheap', 'Fewer nodes means wider boxes for the same width.'),
        ),
        'see': ('docs/native-graphics.md',),
    },
    'INLINE_FORMULA_SPACE': {
        'summary': 'An inline formula cannot fit the remaining width of its line.',
        'cause': 'Inline math is measured as glyphs inside the paragraph, so it competes with the '
                 'sentence around it rather than wrapping on its own.',
        'fixes': (
            ('promote_to_display', 'cheap', 'Make it a display formula when the equation carries '
             'the argument.'),
            ('shorten_the_sentence', 'cheap', 'Cut the clause before the formula.'),
        ),
        'see': ('docs/inline-math.md',),
    },
    'INLINE_TEXT_CAPACITY': {
        'summary': 'An inline run overflows its line box.',
        'cause': 'The run was measured with the real font metrics and the paragraph could not '
                 'reflow around it.',
        'fixes': (
            ('rephrase', 'cheap', 'Break the run into two sentences.'),
            ('widen_region', 'cheap', 'Reclaim width from the neighbouring visual.'),
        ),
        'see': ('docs/inline-math.md',),
    },
    'TYPOGRAPHY_FLOOR': {
        'summary': 'Some text would render below the legibility floor.',
        'cause': 'The compiler refuses to shrink body text below 24 px (18 pt) to make content '
                 'fit; hitting this gate means the content genuinely exceeds the page.',
        'fixes': (
            ('cut_content', 'cheap', 'Remove the sentence the page can do without.'),
            ('split_slide', 'medium', 'Move the trailing point to the next page.'),
        ),
        'see': ('docs/art-direction.md',),
    },
    'SCIENTIFIC_PANEL_TOO_SMALL': {
        'summary': 'A scientific panel would render below its legible minimum.',
        'cause': 'Panels carry per-source minimums so axis labels and curve annotations stay '
                 'readable; a crop that satisfies the layout but not the panel floor fails.',
        'fixes': (
            ('drop_the_panel', 'cheap', 'Keep the panel that carries the argument.'),
            ('crop_tighter', 'cheap', 'Crop to the data region and drop the empty margin.'),
            ('own_page', 'medium', 'Give the panel a full-width page.'),
        ),
        'see': ('docs/scientific-visual-planner.md',),
    },
    'SCHEMATIC_TOO_SMALL': {
        'summary': 'A generated schematic cannot be placed above its minimum size.',
        'cause': 'Generated diagrams are rasterised at a size tied to their label count, so a '
                 'small region yields an unreadable image rather than a compact one.',
        'fixes': (
            ('give_it_a_page', 'cheap', 'A schematic that explains the mechanism deserves a page '
             'of its own.'),
            ('simplify_it', 'cheap', 'Fewer boxes and fewer labels lowers the floor.'),
        ),
        'see': ('docs/scientific-visual-planner.md',),
    },
    'REFERENCE_IMAGE_TOO_SMALL': {
        'summary': 'A reference image is below the minimum size for its role.',
        'cause': 'Reference art is decorative at small sizes but claims to be evidence when '
                 'placed large; the gate keeps it from being mistaken for a data panel.',
        'fixes': (
            ('enlarge_or_drop', 'cheap', 'Either give it real area or remove it; a thumbnail '
             'adds nothing to a research talk.'),
        ),
        'see': ('docs/art-direction.md',),
    },
    'GRAPHIC_INVALID': {
        'summary': 'The declared graphic structure does not form a valid diagram.',
        'cause': 'Edges must reference declared nodes, and when layers are declared they must '
                 'contain every node exactly once. A node outside the layer list, or an edge to '
                 'an unknown id, makes the drawing ambiguous.',
        'fixes': (
            ('check_the_ids', 'cheap', 'Every edge endpoint must match a node id exactly.'),
            ('complete_the_layers', 'cheap', 'Each node appears in exactly one layer, or drop the '
             'layer declaration and let the compiler derive it.'),
        ),
        'see': ('docs/native-graphics.md',),
    },
    'GRAPHIC_CYCLE': {
        'summary': 'The declared edges contain a directed cycle.',
        'cause': 'A DAG cannot express a loop; a cycle means the relation is either feedback or a '
                 'mistake in edge direction.',
        'fixes': (
            ('declare_feedback', 'cheap', 'Mark the returning edge as feedback so it is routed as '
             'a return channel.'),
            ('fix_direction', 'cheap', 'Reverse the edge that closes the loop if the flow is '
             'actually one-way.'),
        ),
        'see': ('docs/native-graphics.md',),
    },
    'GRAPHIC_PATH_INVALID': {
        'summary': 'A path component carries coordinates or a path string the renderer rejects.',
        'cause': 'Coordinates must be finite and within +/-1e9, and a path string is capped at '
                 '32000 characters. Values outside that range come from hand-written SVG or from '
                 'a unit confusion, not from the layout.',
        'fixes': (
            ('check_units', 'cheap', 'Coordinates are in the graphic box, not in slide pixels or '
             'millimetres.'),
            ('simplify_the_path', 'cheap', 'A path that long is usually a traced bitmap; use the '
             'image instead.'),
        ),
        'see': ('docs/native-graphics.md',),
    },
    'GRAPHIC_ROUTE_CAPACITY': {
        'summary': 'A connector cannot be routed through the space that is left.',
        'cause': 'A long edge needs a dogleg with distinct endpoint heights, and feedback needs '
                 'distinct forward layers plus a return channel that clears the content.',
        'fixes': (
            ('align_endpoints', 'cheap', 'Give the two ends different vertical positions so a '
             'dogleg has somewhere to turn.'),
            ('fewer_feedback_edges', 'cheap', 'One return channel per diagram; state the rest in '
             'the reading.'),
        ),
        'see': ('docs/native-graphics.md',),
    },
    'GRAPHIC_ROUTE_CONFLICT': {
        'summary': 'A declared feedback edge has no conflict-free return channel.',
        'cause': 'The return path would have to cross a node or another connector, and the '
                 'compiler will not draw an ambiguous crossing.',
        'fixes': (
            ('change_sides', 'cheap', 'Move the target node to a side that leaves a clear margin.'),
            ('drop_the_feedback', 'cheap', 'State the feedback in the reading instead of drawing '
             'it.'),
        ),
        'see': ('docs/native-graphics.md',),
    },
    'CRITICAL_COLLISION': {
        'summary': 'Two rendered elements overlap beyond the tolerance.',
        'cause': 'Measured on the compiled geometry, not on the intent. It is downgraded to REVIEW '
                 'when the overlap is a deliberate scientific text overlay.',
        'fixes': (
            ('reallocate', 'cheap', 'Reclaim the space from the element that is over-wide.'),
            ('shorten_text', 'cheap', 'The overlapping element is usually a label that grew past '
             'its estimate.'),
        ),
        'see': ('docs/complex-page-qa.md',),
    },
    'REGION_CONTENT_OUT_OF_BOUNDS': {
        'summary': 'A rendered component is painted outside the region the compiler gave it.',
        'cause': 'The component ignored its assigned box, usually because its own internal '
                 'padding or stroke was not part of the measurement.',
        'fixes': (
            ('report_the_component', 'cheap', 'This is a compiler or renderer defect, not a '
             'content problem; keep the IR and report the page.'),
        ),
        'see': ('docs/complex-page-qa.md',),
    },
    'FRAME_CONTENT_OUT_OF_BOUNDS': {
        'summary': 'Content extends past its frame.',
        'cause': 'The frame was sized for less content than the block carries; frames do not clip, '
                 'so the overflow is visible.',
        'fixes': (
            ('spacious_frame', 'cheap', 'Switch the page to the spacious variant.'),
            ('cut_content', 'cheap', 'Remove the line that overflows.'),
        ),
        'see': ('docs/framed-containers.md',),
    },
    'NATIVE_TEXT_OUT_OF_BOUNDS': {
        'summary': 'In the native render, some text sits outside the slide.',
        'cause': 'Measured from the exported PDF, so this is what PowerPoint actually drew: a '
                 'shape grew when PowerPoint substituted a font or re-wrapped a line.',
        'fixes': (
            ('check_fonts', 'cheap', 'A missing font on the render machine widens every run.'),
            ('shorten_the_run', 'cheap', 'Leave headroom for the substitution.'),
        ),
        'see': ('docs/officecli-backend.zh-CN.md',),
    },
    'NATIVE_PAGE_COUNT': {
        'summary': 'The native render has a different page count than the IR.',
        'cause': 'Almost always a stale artifact: the PDF was exported from an earlier candidate, '
                 'or the build wrote the IR after the export.',
        'fixes': (
            ('rebuild', 'cheap', 'Rebuild the candidate and re-export; do not compare across '
             'builds.'),
        ),
        'see': ('docs/officecli-backend.zh-CN.md',),
    },
    'VISUAL_DESIGN_REQUIRED': {
        'summary': 'The design stage was skipped.',
        'cause': 'A deck that carries visuals must pass through the visual planner: prompt, '
                 'proposal, apply. Generating pages without that step leaves the plan unowned.',
        'fixes': (
            ('run_the_stage', 'cheap', 'visual-prompt, then author the proposal, then '
             'apply-visual-plan.'),
            ('reuse_the_plan', 'cheap', 'If the IR already has visual_plan entries, apply them '
             'rather than regenerate.'),
        ),
        'see': ('docs/scientific-visual-planner.md',),
    },
    'VISUAL_PLAN_INVALID': {
        'summary': 'visual_plan is attached to the wrong level.',
        'cause': 'The plan belongs to a slide; a deck-level visual_plan cannot be resolved to a '
                 'page.',
        'fixes': (
            ('move_to_slide', 'cheap', 'Move the entry under the slide that owns it.'),
        ),
        'see': ('docs/scientific-visual-planner.md',),
    },
    'VISUAL_PLAN_UNSATISFIABLE': {
        'summary': 'No composition satisfies the plan together with the content and the gates.',
        'cause': 'The requested composition needs more room than the page has once the copy, the '
                 'panel floors, the typography floor, and the collision check are all applied.',
        'fixes': (
            ('replan', 'cheap', 'Change the composition, not the science: a row instead of a '
             'column, or a list instead of prose.'),
            ('split_slide', 'medium', 'Give the visual its own page.'),
        ),
        'see': ('docs/scientific-visual-planner.md',),
    },
    'COMPILATION_FAILED': {
        'summary': 'The build aborted with an underlying error.',
        'cause': 'This is the umbrella item; the real cause is in the message it wraps.',
        'fixes': (
            ('read_the_wrapped_error', 'cheap', 'The message carries the original exception; '
             'explain that code instead.'),
            ('check_the_output_lock', 'cheap', 'A candidate still open in PowerPoint, or a stale '
             'lock in the output directory, also lands here.'),
        ),
        'see': ('docs/deck-compiler-v2.md',),
    },
    'LAYOUT_PROVIDER_FAILED': {
        'summary': 'The layout provider could not propose a usable layout.',
        'cause': 'The provider contract was not met. The page falls back to the compiler '
                 'templates and the fallback is recorded, so the build is not blocked.',
        'fixes': (
            ('use_the_packer', 'cheap', 'Run with --layout-provider packer.'),
            ('check_the_factory', 'cheap', 'An external provider must resolve module:factory and '
             'return propose(requests).'),
        ),
        'see': ('docs/layout-provider.md',),
    },
    'FONT_UNAVAILABLE': {
        'summary': 'A font named by the theme or the deck could not be loaded.',
        'cause': 'Measuring and rendering must use the same font; without it every width estimate '
                 'is wrong, so the build stops instead of substituting silently.',
        'fixes': (
            ('install_the_font', 'cheap', 'Install the family or point the deck at one that '
             'exists.'),
            ('discover_fonts', 'cheap', 'Use the discover-fonts command to see what is available.'),
        ),
        'see': ('docs/art-direction.md',),
    },
    'ASSET_INVALID': {
        'summary': 'An asset referenced by the IR is missing or unreadable.',
        'cause': 'Path resolution is relative to the deck_ir.json, not to the working directory.',
        'fixes': (
            ('fix_the_path', 'cheap', 'Use a path relative to the IR file, or an absolute one.'),
            ('check_the_format', 'cheap', 'The file must decode as a real image.'),
        ),
        'see': ('docs/deck-compiler-v2.md',),
    },
    'FORMULA_ANCHOR_INVALID': {
        'summary': 'A block carries an anchor that only a formula may own.',
        'cause': 'Anchors bind an explanation to an equation; attaching one to prose or to a '
                 'figure leaves the explanation pointing at nothing.',
        'fixes': (
            ('move_the_anchor', 'cheap', 'Attach the anchor to the formula block it explains.'),
        ),
        'see': ('docs/inline-math.md', 'docs/explanation-contract.md'),
    },
    'SUPPLEMENT_PAPER_FIGURE': {
        'summary': 'A supplement-only page uses a paper figure.',
        'cause': 'Paper figures carry evidence_from the paper; putting one on a supplement page '
                 'blurs which claims the paper supports and which the speaker adds.',
        'fixes': (
            ('add_the_paper_block', 'cheap', 'Give the page its paper content and evidence_refs so '
             'the figure is grounded.'),
            ('swap_the_visual', 'cheap', 'Use a generated or reference visual on a supplement-only '
             'page.'),
        ),
        'see': ('docs/content-projection.md',),
    },
    'SUPPLEMENT_KIND_INVALID': {
        'summary': 'The supplement declares a kind outside the allowed set.',
        'cause': 'Supplement content must state what it is, so the reader can tell derived '
                 'material from published material.',
        'fixes': (
            ('use_a_known_kind', 'cheap', 'Pick one of the declared kinds in the supplement '
             'contract.'),
        ),
        'see': ('docs/content-projection.md',),
    },
    'SUPPLEMENT_SPEC_MISSING': {
        'summary': 'Supplement content is present but its spec is not.',
        'cause': 'The page shows supplement material without the block that declares its kind, '
                 'basis, and sources.',
        'fixes': (
            ('add_the_spec', 'cheap', 'Declare the supplement block before its content.'),
        ),
        'see': ('docs/content-projection.md',),
    },
    'PROVENANCE_PAPER_EVIDENCE_MISSING': {
        'summary': 'A mixed page carries paper content but declares no paper evidence.',
        'cause': 'On a page that mixes paper and supplement material, every paper claim needs an '
                 'evidence reference; otherwise a derived statement reads as published.',
        'fixes': (
            ('attach_evidence_refs', 'cheap', 'Add semantic.evidence_refs for the paper content.'),
            ('split_the_page', 'cheap', 'Keep paper and supplement on separate pages.'),
        ),
        'see': ('docs/explanation-contract.md', 'docs/content-projection.md'),
    },
    'OFFICECLI_FORMAT': {
        'summary': 'OfficeCLI reported a formatting warning, most often a text overflow estimate.',
        'cause': 'The estimate comes from the writer, not from the compiled layout, so it is kept '
                 'as INFO with the original issue attached. The page may well render correctly.',
        'fixes': (
            ('look_at_the_page', 'cheap', 'Check the rendered page before changing anything.'),
            ('do_not_shrink_content', 'cheap', 'Do not compress or delete scientific content to '
             'silence an estimate; treat it as INFO unless the page really overflows.'),
        ),
        'see': ('docs/officecli-backend.zh-CN.md',),
    },
    'EXPLAIN_VIZ_': {
        'summary': 'The optional teaching-diagram pass reports what it did, and why.',
        'cause': 'The suffix is decided at runtime: APPLIED when a diagram was placed, SKIPPED '
                 'when the page had no reserved slot or the pass was off, FALLBACK when the '
                 'conservative source rules were used instead of a proposal, DISABLED when the '
                 'request turned it off. These are notices about an optional pass, not defects.',
        'fixes': (
            ('ignore_skipped', 'cheap', 'SKIPPED on a page that never declared a slot is '
             'expected; no page can be forced to carry a diagram.'),
            ('read_fallback', 'cheap', 'FALLBACK means no proposal was applied; supply one with '
             'apply-explain-viz --proposal if the page deserves a diagram.'),
        ),
        'see': ('docs/explain-viz.md',),
    },
    'VISUAL_STYLE_INVALID': {
        'summary': 'presentation.visual_style is not a valid style object.',
        'cause': 'The object accepts only pack and overrides. Every override key must be a dotted '
                 'token that exists in the chosen pack, and each token type has a closed value set '
                 '(shape, align, arrow, sparse_balance, furniture, bold).',
        'fixes': (
            ('check_the_pack', 'cheap', 'The pack name must be one the build ships.'),
            ('check_the_dotted_token', 'cheap', 'An unknown override key is ignored silently at '
             'render time, so it is rejected here instead.'),
            ('match_the_value_set', 'cheap', 'The message names the accepted values for that '
             'token.'),
        ),
        'see': ('docs/visual-style.md',),
    },
    'ACADEMIC_DESIGN_INVALID': {
        'summary': 'page_design is incomplete or cannot be traced back to the story.',
        'cause': 'A design must declare its schema version (1.2, or 1.3 when the story carries '
                 'content_contract 2.0), the room it is for (setting.audience, occasion, reading), '
                 'and the devices that carry the argument. The message names the first missing '
                 'field.',
        'fixes': (
            ('fill_the_named_field', 'cheap', 'Fix exactly the field the message names; the rest '
             'are validated in order.'),
            ('do_not_downgrade', 'cheap', 'Lowering schema_version to pass validation is rejected: '
             'a downgrade hides the visibility and review checks.'),
        ),
        'see': ('docs/art-direction.md', 'docs/page-recipes.md'),
    },
    'COMPONENT_RENDER_FAILED': {
        'summary': 'A component got its region but failed its own renderer.',
        'cause': 'Region allocation succeeded, and then the component hit a second gate of its '
                 'own, such as a label floor or a route that no longer fits the final box.',
        'fixes': (
            ('read_the_nested_message', 'cheap', 'The wrapped error names the component and the '
             'floor it missed.'),
            ('shrink_the_content', 'cheap', 'The box was sized by the plan; when the component '
             'cannot use it, simplify the component.'),
        ),
        'see': ('docs/native-components.md',),
    },
    'SHAPE_OUT_OF_BOUNDS': {
        'summary': 'An element carries geometry the renderer cannot place.',
        'cause': 'Width, height, or a coordinate is not a finite number, or the box is not inside '
                 'its container. This comes from hand-written geometry in the IR, not from the '
                 'layout tree.',
        'fixes': (
            ('check_the_numbers', 'cheap', 'Look for NaN, Infinity, negative width, or a unit '
             'confusion in the element that the message names.'),
        ),
        'see': ('docs/deck-compiler-v2.md',),
    },
    'VISUAL_PROMPT_FAILED': {
        'summary': 'The visual planner prompt could not be produced.',
        'cause': 'The wrapped error is the real cause: usually an IR field the planner needs, or '
                 'an output path it cannot write.',
        'fixes': (
            ('read_the_wrapped_error', 'cheap', 'The message carries the original exception.'),
            ('free_the_output', 'cheap', 'A locked or missing output directory also lands here.'),
        ),
        'see': ('docs/scientific-visual-planner.md',),
    },
}
