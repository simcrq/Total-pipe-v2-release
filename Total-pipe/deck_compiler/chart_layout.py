"""Chart IR v1: a measured, editable data plot.

This module owns the contract, not the drawing. A chart is a *data* object: the values it plots
must be traceable, the axes are declared, and the renderer (next step) draws native shapes from the
same fields. Keeping the contract separate lets the design/IR stages produce chart data and pass a
deterministic check before a renderer exists.

The rules here are the ones JSON Schema cannot express: series length against the shared x domain,
monotonic x for a line, positivity on a log scale, and the evidence binding of every plotted value.
"""
import math
import re

KINDS = ('line', 'bar')
SCALES = ('linear', 'log')
BASES = ('evidence', 'explain')
MAX_CHARTS = 4
MAX_SERIES = 4
MIN_POINTS = 2
MAX_POINTS = 24
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_charts(charts, slide_evidence_refs=None):
    """Every reason a chart cannot be plotted as declared, as human-readable messages."""
    if charts is None or charts == []:
        return []
    if not isinstance(charts, list):
        return ['charts must be a list']
    errors = []
    if len(charts) > MAX_CHARTS:
        errors.append(f'at most {MAX_CHARTS} charts per page')
    seen = set()
    for position, chart in enumerate(charts):
        path = f'charts[{position}]'
        if not isinstance(chart, dict):
            errors.append(f'{path}: chart must be an object')
            continue
        chart_id = chart.get('id')
        if not isinstance(chart_id, str) or not IDENTIFIER.fullmatch(chart_id):
            errors.append(f'{path}: id must be 1-64 letters, digits, hyphens or underscores')
        elif chart_id in seen:
            errors.append(f'{path}: duplicate chart id {chart_id!r}')
        else:
            seen.add(chart_id)
        kind, basis = chart.get('kind'), chart.get('basis')
        if kind not in KINDS:
            errors.append(f'{path}: kind must be one of {list(KINDS)}')
        if basis not in BASES:
            errors.append(f'{path}: basis must be one of {list(BASES)}')
        illustrative = chart.get('illustrative', False)
        if not isinstance(illustrative, bool):
            errors.append(f'{path}: illustrative must be a boolean')
        elif basis == 'explain' and not illustrative:
            errors.append(f'{path}: an explanatory chart must set illustrative=true')
        elif basis == 'evidence' and illustrative:
            errors.append(f'{path}: an evidence chart cannot be illustrative')
        x = chart.get('x')
        if not isinstance(x, dict):
            errors.append(f'{path}.x: an axis object is required')
            x_values = []
        else:
            x_values = x.get('values')
            if not isinstance(x.get('label'), str) or not x['label'].strip():
                errors.append(f'{path}.x.label: a readable axis label is required')
            if x.get('scale', 'linear') not in SCALES:
                errors.append(f'{path}.x.scale: must be linear or log')
            if (not isinstance(x_values, list) or not MIN_POINTS <= len(x_values) <= MAX_POINTS
                    or not all(_number(value) for value in x_values)):
                errors.append(f'{path}.x.values: {MIN_POINTS}-{MAX_POINTS} finite numbers required')
                x_values = []
            elif x.get('scale') == 'log' and any(value <= 0 for value in x_values):
                errors.append(f'{path}.x.values: a log axis cannot contain zero or negative values')
            elif kind == 'line' and any(a >= b for a, b in zip(x_values, x_values[1:])):
                errors.append(f'{path}.x.values: a line chart needs strictly increasing x')
        y = chart.get('y')
        if not isinstance(y, dict):
            errors.append(f'{path}.y: an axis object is required')
        else:
            if not isinstance(y.get('label'), str) or not y['label'].strip():
                errors.append(f'{path}.y.label: a readable axis label is required')
            if y.get('scale', 'linear') not in SCALES:
                errors.append(f'{path}.y.scale: must be linear or log')
        series = chart.get('series')
        if not isinstance(series, list) or not 1 <= len(series) <= MAX_SERIES:
            errors.append(f'{path}.series: 1-{MAX_SERIES} series required')
            series = []
        for index, entry in enumerate(series):
            position_path = f'{path}.series[{index}]'
            if not isinstance(entry, dict):
                errors.append(f'{position_path}: series must be an object')
                continue
            if not isinstance(entry.get('label'), str) or not entry['label'].strip():
                errors.append(f'{position_path}.label: a series label is required')
            values = entry.get('values')
            if not isinstance(values, list) or not all(_number(value) for value in values):
                errors.append(f'{position_path}.values: finite numbers required')
            elif x_values and len(values) != len(x_values):
                errors.append(f'{position_path}.values: length must match x.values ({len(x_values)})')
            elif isinstance(y, dict) and y.get('scale') == 'log' and any(value <= 0 for value in values):
                errors.append(f'{position_path}.values: a log axis cannot contain zero or negative values')
            refs = entry.get('evidence_refs', [])
            if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
                errors.append(f'{position_path}.evidence_refs: a list of non-empty ids is required')
                refs = []
            if basis == 'evidence' and not refs:
                errors.append(f'{position_path}: an evidence chart needs evidence_refs for every series')
            if slide_evidence_refs is not None:
                missing = sorted(set(refs) - set(slide_evidence_refs))
                if missing:
                    errors.append(f'{position_path}: evidence {missing} is not on semantic.evidence_refs')
        if basis == 'evidence' and (not isinstance(chart.get('source'), str)
                                    or not chart['source'].strip()):
            errors.append(f'{path}.source: an evidence chart needs its provenance line')
    return errors
