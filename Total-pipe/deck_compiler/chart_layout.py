"""Chart IR v1: a measured, editable data plot.

This module owns the contract, not the drawing. A chart is a *data* object: the values it plots
must be traceable, the axes are declared, and the renderer draws native shapes from the same
fields.

The rules here are the ones JSON Schema cannot express: series length against its x domain,
monotonic x for a line, positivity on a log scale, error-bar arithmetic, annotation indices, and
the evidence binding of every plotted value.
"""
import math
import re

KINDS = ('line', 'bar', 'hbar', 'scatter')
SCALES = ('linear', 'log')
BASES = ('evidence', 'explain')
MAX_CHARTS = 4
MAX_SERIES = 4
MAX_ANNOTATIONS = 6
MAX_REF_LINES = 4
MAX_SHADED_ZONES = 3
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
            x_categories = []
        else:
            unknown_x = set(x) - {'label', 'scale', 'values', 'categories', 'min', 'max'}
            if unknown_x:
                errors.append(f'{path}.x: unknown axis fields {sorted(unknown_x)}')
            for bound_key in ('min', 'max'):
                if bound_key in x and not _number(x[bound_key]):
                    errors.append(f'{path}.x.{bound_key}: finite number required')
            if _number(x.get('min')) and _number(x.get('max')) and x['min'] >= x['max']:
                errors.append(f'{path}.x: min must be strictly less than max')
            if x.get('scale') == 'log' and _number(x.get('min')) and x['min'] <= 0:
                errors.append(f'{path}.x.min: log axis min must be strictly positive')
            x_values = x.get('values')
            x_categories = x.get('categories')
            if not isinstance(x.get('label'), str) or not x['label'].strip():
                errors.append(f'{path}.x.label: a readable axis label is required')
            if x.get('scale', 'linear') not in SCALES:
                errors.append(f'{path}.x.scale: must be linear or log')
            if x_categories is not None:
                if kind not in ('bar', 'hbar'):
                    errors.append(f'{path}.x.categories: named categories are supported on bar and hbar charts only')
                elif (not isinstance(x_categories, list) or not MIN_POINTS <= len(x_categories) <= MAX_POINTS
                      or any(not isinstance(cat, str) or not cat.strip() or len(cat) > 40 for cat in x_categories)):
                    errors.append(f'{path}.x.categories: {MIN_POINTS}-{MAX_POINTS} non-empty category strings (<=40 chars) required')
                    x_categories = []
            if x_values is None:
                x_values = []
                if kind == 'line' or (kind in ('bar', 'hbar') and not x_categories):
                    errors.append(f'{path}.x.values: line and bar/hbar charts need a shared x domain or categories')
            elif (not isinstance(x_values, list) or not MIN_POINTS <= len(x_values) <= MAX_POINTS
                  or not all(_number(value) for value in x_values)):
                errors.append(f'{path}.x.values: {MIN_POINTS}-{MAX_POINTS} finite numbers required')
                x_values = []
            elif x.get('scale') == 'log' and any(value <= 0 for value in x_values):
                errors.append(f'{path}.x.values: a log axis cannot contain zero or negative values')
            elif kind == 'line' and any(a >= b for a, b in zip(x_values, x_values[1:])):
                errors.append(f'{path}.x.values: a line chart needs strictly increasing x')
            if x_values and x_categories and len(x_values) != len(x_categories):
                errors.append(f'{path}.x.categories: length must match x.values when both are provided')
        domain_len = len(x_categories) if x_categories else len(x_values)
        y = chart.get('y')
        if not isinstance(y, dict):
            errors.append(f'{path}.y: an axis object is required')
        else:
            unknown_y = set(y) - {'label', 'scale', 'unit', 'min', 'max'}
            if unknown_y:
                errors.append(f'{path}.y: unknown axis fields {sorted(unknown_y)}')
            if not isinstance(y.get('label'), str) or not y['label'].strip():
                errors.append(f'{path}.y.label: a readable axis label is required')
            if y.get('scale', 'linear') not in SCALES:
                errors.append(f'{path}.y.scale: must be linear or log')
            for bound_key in ('min', 'max'):
                if bound_key in y and not _number(y[bound_key]):
                    errors.append(f'{path}.y.{bound_key}: finite number required')
            if _number(y.get('min')) and _number(y.get('max')) and y['min'] >= y['max']:
                errors.append(f'{path}.y: min must be strictly less than max')
            if y.get('scale') == 'log' and _number(y.get('min')) and y['min'] <= 0:
                errors.append(f'{path}.y.min: log axis min must be strictly positive')
        series = chart.get('series')
        if not isinstance(series, list) or not 1 <= len(series) <= MAX_SERIES:
            errors.append(f'{path}.series: 1-{MAX_SERIES} series required')
            series = []
        for index, entry in enumerate(series):
            series_path = f'{path}.series[{index}]'
            if not isinstance(entry, dict):
                errors.append(f'{series_path}: series must be an object')
                continue
            if not isinstance(entry.get('label'), str) or not entry['label'].strip():
                errors.append(f'{series_path}.label: a series label is required')
            values = entry.get('values')
            if not isinstance(values, list) or not all(_number(value) for value in values):
                errors.append(f'{series_path}.values: finite numbers required')
                values = []
            series_x = entry.get('x_values')
            if kind == 'scatter':
                if (not isinstance(series_x, list) or len(series_x) != len(values)
                        or not all(_number(value) for value in series_x)):
                    errors.append(f'{series_path}.x_values: scatter needs one finite x per point')
                elif isinstance(x, dict) and x.get('scale') == 'log' and any(value <= 0 for value in series_x):
                    errors.append(f'{series_path}.x_values: a log axis cannot contain zero or negative values')
            elif series_x is not None:
                errors.append(f'{series_path}.x_values: only scatter charts have per-series x')
            if domain_len and values and len(values) != domain_len:
                errors.append(f'{series_path}.values: length must match shared domain ({domain_len})')
            if isinstance(y, dict) and y.get('scale') == 'log' and any(value <= 0 for value in values):
                errors.append(f'{series_path}.values: a log axis cannot contain zero or negative values')
            error = entry.get('y_error')
            if error is not None:
                if (not isinstance(error, list) or len(error) != len(values)
                        or not all(_number(value) for value in error)):
                    errors.append(f'{series_path}.y_error: one finite bar per point is required')
                elif any(value < 0 for value in error):
                    errors.append(f'{series_path}.y_error: error bars cannot be negative')
                elif isinstance(y, dict) and y.get('scale') == 'log' and any(
                        value-bar <= 0 for value, bar in zip(values, error)):
                    errors.append(f'{series_path}.y_error: a log axis cannot show a bar reaching zero')
            refs = entry.get('evidence_refs', [])
            if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
                errors.append(f'{series_path}.evidence_refs: a list of non-empty ids is required')
                refs = []
            if basis == 'evidence' and not refs:
                errors.append(f'{series_path}: an evidence chart needs evidence_refs for every series')
            if slide_evidence_refs is not None:
                missing = sorted(set(refs) - set(slide_evidence_refs))
                if missing:
                    errors.append(f'{series_path}: evidence {missing} is not on semantic.evidence_refs')
        annotations = chart.get('annotations', [])
        if not isinstance(annotations, list) or len(annotations) > MAX_ANNOTATIONS:
            errors.append(f'{path}.annotations: at most {MAX_ANNOTATIONS} annotations')
            annotations = []
        for index, note in enumerate(annotations):
            note_path = f'{path}.annotations[{index}]'
            if not isinstance(note, dict):
                errors.append(f'{note_path}: annotation must be an object')
                continue
            if not isinstance(note.get('text'), str) or not note['text'].strip():
                errors.append(f'{note_path}.text: a non-empty label is required')
            series_index, point = note.get('series'), note.get('point')
            if (not isinstance(series_index, int) or isinstance(series_index, bool)
                    or not 0 <= series_index < len(series)):
                errors.append(f'{note_path}.series: must index an existing series')
            elif (not isinstance(point, int) or isinstance(point, bool)
                  or not 0 <= point < len((series[series_index] or {}).get('values') or [])):
                errors.append(f'{note_path}.point: must index an existing point')
            for key, limit in (('dx', 160), ('dy', 120)):
                if key in note and (not _number(note[key]) or abs(note[key]) > limit):
                    errors.append(f'{note_path}.{key}: must be a finite offset within ±{limit} px')
        ref_lines = chart.get('reference_lines', [])
        if not isinstance(ref_lines, list) or len(ref_lines) > MAX_REF_LINES:
            errors.append(f'{path}.reference_lines: at most {MAX_REF_LINES} reference lines')
            ref_lines = []
        for index, rline in enumerate(ref_lines):
            rpath = f'{path}.reference_lines[{index}]'
            if not isinstance(rline, dict):
                errors.append(f'{rpath}: reference line must be an object')
                continue
            if rline.get('axis') not in ('x', 'y'):
                errors.append(f'{rpath}.axis: must be x or y')
            if not _number(rline.get('value')):
                errors.append(f'{rpath}.value: finite number required')
            if 'label' in rline and (not isinstance(rline['label'], str) or not rline['label'].strip() or len(rline['label']) > 60):
                errors.append(f'{rpath}.label: non-empty string <=60 chars required')
            if rline.get('style', 'dashed') not in ('dashed', 'solid'):
                errors.append(f'{rpath}.style: must be dashed or solid')
        zones = chart.get('shaded_zones', [])
        if not isinstance(zones, list) or len(zones) > MAX_SHADED_ZONES:
            errors.append(f'{path}.shaded_zones: at most {MAX_SHADED_ZONES} shaded zones')
            zones = []
        for index, zone in enumerate(zones):
            zpath = f'{path}.shaded_zones[{index}]'
            if not isinstance(zone, dict):
                errors.append(f'{zpath}: shaded zone must be an object')
                continue
            if zone.get('axis') not in ('x', 'y'):
                errors.append(f'{zpath}.axis: must be x or y')
            low_v, high_v = zone.get('low'), zone.get('high')
            if not (_number(low_v) and _number(high_v) and low_v < high_v):
                errors.append(f'{zpath}: low and high must be finite numbers with low < high')
            if 'label' in zone and (not isinstance(zone['label'], str) or not zone['label'].strip() or len(zone['label']) > 60):
                errors.append(f'{zpath}.label: non-empty string <=60 chars required')
        if basis == 'evidence' and (not isinstance(chart.get('source'), str)
                                    or not chart['source'].strip()):
            errors.append(f'{path}.source: an evidence chart needs its provenance line')
    return errors
