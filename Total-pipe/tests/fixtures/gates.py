"""Gate fixture for the diagnostics scanner. Not imported by the package."""


def raises_a_literal_gate():
    issue('FRESH_GATE', 'FAIL', 'the reason is spelled out here')


def raises_a_template_gate(n):
    issue('TEMPLATE_GATE', 'WARNING', f'{n} rows do not fit the box')


def raises_two_severities():
    issue('MIXED', 'INFO', 'one')
    issue('MIXED', 'FAIL', 'two')


def raises_a_computed_gate(kind):
    code = {'figure': 'COMPUTED_FIGURE_GATE'}.get(kind, 'COMPUTED_OTHER_GATE')
    raise LayoutTreeError('body', code, 'region is shorter than its minimum', [0, 0], [0, 0])
