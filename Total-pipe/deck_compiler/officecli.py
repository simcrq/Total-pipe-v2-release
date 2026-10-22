"""OfficeCLI backend for the compiled layout protocol (CSS pixels at 96 dpi)."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess

_A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'


def _px(value):
    return (f'{value:.6f}'.rstrip('0').rstrip('.') or '0') + 'px'


def _pt(css_pixels):
    return (f'{css_pixels * .75:.6f}'.rstrip('0').rstrip('.') or '0') + 'pt'


def _color(value):
    return value.lstrip('#') if value and value != 'none' else 'none'


def preflight(executable='officecli'):
    """Pin the minimum tested CLI and verify its schema before writing a deck."""
    version = subprocess.run([executable, '--version'], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=15)
    match = re.search(r'\b(\d+)\.(\d+)\.(\d+)\b', version.stdout)
    if version.returncode or not match or tuple(map(int, match.groups())) < (1, 0, 152):
        raise ValueError(f'OfficeCLI 1.0.152+ required: {version.stdout} {version.stderr}')
    required = {
        'presentation': {'slideWidth': 'set', 'slideHeight': 'set'},
        'slide': {'layout': 'add', 'background': 'add'},
        'shape': {key: 'add' for key in ('x', 'y', 'width', 'height', 'name', 'text',
                                       'font', 'font.ea', 'size', 'lineSpacing', 'bold',
                                       'color', 'fill', 'line', 'autoFit', 'margin', 'valign')},
        'picture': {key: 'add' for key in ('x', 'y', 'width', 'height', 'name', 'src', 'alt')},
        'notes': {'text': 'add'},
    }
    schemas = {}
    for element, props in required.items():
        response = subprocess.run([executable, 'help', 'pptx', element, '--json'],
                                  capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=15)
        if response.returncode:
            raise ValueError(f'OfficeCLI schema unavailable for pptx {element}: {response.stderr}')
        schema = json.loads(response.stdout)
        properties = schema.get('properties') or {}
        missing = [f'{key}.{operation}' for key, operation in props.items()
                   if not (properties.get(key) or {}).get(operation)]
        if missing:
            raise ValueError(f'OfficeCLI pptx {element} lacks required capabilities: {missing}')
        schemas[element] = schema
    fingerprint = hashlib.sha256(json.dumps(schemas, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'version': match.group(0), 'schema_sha256': fingerprint}


def _xml_attribute(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def list_paragraph_properties(contract, bullet, index, count):
    """One ``a:pPr`` for a native list item: exact line spacing, coloured marker, hanging indent.

    Written as raw XML because the typed OfficeCLI paragraph API has no bullet colour and no
    before/after paragraph spacing; the element order below is the order DrawingML requires
    (lnSpc → spcAft → buClr → buFont → buChar).
    """
    gutter = round(float(bullet['gutter']) * 9525)          # css px → EMU
    spacing = round(contract['font_size'] * contract['line_height'] * 75)   # px → 1/100 pt
    parts = [f'<a:pPr xmlns:a="{_A_NS}" marL="{gutter}" indent="-{gutter}">',
             f'<a:lnSpc><a:spcPts val="{spacing}" /></a:lnSpc>']
    gap = float(bullet.get('space_after') or 0)
    if index < count - 1 and gap > 0:
        parts.append(f'<a:spcAft><a:spcPts val="{round(gap * 75)}" /></a:spcAft>')
    parts.append(f'<a:buClr><a:srgbClr val="{_color(bullet["color"])}" /></a:buClr>')
    parts.append(f'<a:buFont typeface="{_xml_attribute(bullet["face"])}" />')
    parts.append(f'<a:buChar char="{_xml_attribute(bullet["char"])}" />')
    parts.append('</a:pPr>')
    return ''.join(parts)


def commands(layout):
    """Translate only compiled geometry; Deck IR remains the sole content source."""
    width, height = layout['slide_size']
    result = [{'command': 'set', 'path': '/', 'props': {
        'slideWidth': _px(width), 'slideHeight': _px(height)}}]
    for index, slide in enumerate(layout['slides'], 1):
        parent = f'/slide[{index}]'
        has_text = False
        result.append({'command': 'add', 'parent': '/', 'type': 'slide',
                       'props': {'layout': 'blank', 'background': _color(slide['background'])}})
        for element in slide['elements']:
            x, y, w, h = element['bbox']
            props = {'x': _px(x), 'y': _px(y), 'width': _px(w), 'height': _px(h)}
            kind = element['kind']
            if kind == 'image':
                asset = layout['assets'][element['asset_id']]
                props.update({'name': element['id'], 'src': asset['path'],
                              'alt': element['id'] + ': ' + element['alt']})
                typ = 'picture'
            elif kind == 'shape':
                props.update({'name': element['id'], 'geometry': element.get('geometry', 'rect'),
                              'fill': _color(element['fill']), 'line': _color(element['line']),
                              'lineWidth': _pt(element.get('line_width', 1))})
                typ = 'shape'
            elif kind in ('text', 'list'):
                has_text = True
                contract = element['contract']
                props.update({'name': element['id'], 'text': element['text'],
                              'font': contract['font_family'],
                              'font.ea': contract['font_family'],
                              'size': _pt(contract['font_size']),
                              'lineSpacing': _pt(contract['font_size'] * contract['line_height']),
                              'bold': str(contract['font_weight'] >= 700).lower(),
                              'color': _color(element['color']), 'fill': 'none', 'line': 'none',
                              'autoFit': 'none', 'margin': '0px',
                              'valign': 'center' if contract['vertical_anchor'] == 'middle'
                                        else contract['vertical_anchor']})
                typ = 'shape'
            else:
                raise ValueError(f'Unsupported compiled element kind: {kind}')
            result.append({'command': 'add', 'parent': parent, 'type': typ, 'props': props})
            if kind in ('text', 'list') and any(contract['inset'].values()):
                inset = contract['inset']
                margin = ','.join(_px(inset[side]) for side in ('left', 'top', 'right', 'bottom'))
                result.append({'command': 'set', 'path': f'{parent}/shape[@name={element["id"]}]',
                               'props': {'margin': margin}})
            if kind == 'list':
                # The typed API has no bullet colour, so each item's paragraph properties are
                # replaced whole; the run properties written by `add` stay untouched.
                for number in range(1, len(element['items']) + 1):
                    result.append({
                        'command': 'raw-set', 'part': parent,
                        'xpath': (f"//p:sp[p:nvSpPr/p:cNvPr[@name='{element['id']}']]"
                                  f"/p:txBody/a:p[{number}]/a:pPr"),
                        'action': 'replace',
                        'xml': list_paragraph_properties(contract, element['bullet'],
                                                         number - 1, len(element['items']))})
        if has_text:
            # OfficeCLI has typed line spacing and insets, but no typed bodyPr.wrap yet.
            result.append({'command': 'raw-set', 'part': parent,
                           'xpath': '//p:sp[p:txBody]/p:txBody/a:bodyPr',
                           'action': 'setattr', 'xml': 'wrap=none'})
        result.append({'command': 'add', 'parent': parent, 'type': 'notes',
                       'props': {'text': slide['notes']}})
    return result


def _run(executable, *args, timeout=180):
    completed = subprocess.run([executable, *map(str, args), '--json'],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=timeout,
                               env={**os.environ, 'OFFICECLI_NO_AUTO_RESIDENT': '1'})
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f'OfficeCLI returned non-JSON output: {completed.stdout[:500]} {completed.stderr[:500]}') from error
    if completed.returncode or payload.get('success') is not True or payload.get('warnings'):
        raise ValueError(f'OfficeCLI {args[0]} failed: {completed.stderr[:500]} {payload}')
    data = payload.get('data')
    if args[0] == 'batch' and isinstance(data, dict) and data.get('outputFile'):
        full_path = Path(data['outputFile'])
        full_bytes = full_path.read_bytes()
        if len(full_bytes) != data.get('outputSize'):
            raise ValueError('OfficeCLI batch spill file size differs from its JSON envelope')
        payload['data'] = json.loads(full_bytes)
    return payload


def render(layout_path, output_path, executable='officecli'):
    """Create and atomically populate a PPTX, then flush before OOXML inspection."""
    layout_path, output_path = Path(layout_path), Path(output_path)
    layout = json.loads(layout_path.read_text(encoding='utf-8'))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path = output_path.with_suffix('.officecli.batch.json')
    batch = commands(layout)
    batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    output_path.unlink(missing_ok=True)
    _run(executable, 'create', output_path)
    response = _run(executable, 'batch', output_path, '--input', batch_path, '--stop-on-error')
    data = response.get('data') or {}
    summary = data.get('summary') or {}
    results = data.get('results') or []
    if (summary.get('total') != len(batch) or summary.get('succeeded') != len(batch)
            or len(results) != len(batch) or any(not r.get('success') or r.get('warnings')
                                                 or 'WARNING:' in (r.get('output') or '') for r in results)):
        raise ValueError(f'OfficeCLI batch did not apply every property: {summary}')
    _run(executable, 'close', output_path)
    if not output_path.exists():
        raise ValueError('OfficeCLI did not write candidate.pptx')
    validation = _run(executable, 'validate', output_path)
    if schema_error_count(validation) != 0:
        raise ValueError(f'OfficeCLI schema validation did not pass: {validation.get("data")}')
    return batch_path


def schema_error_count(payload):
    """How many OpenXML schema errors OfficeCLI reported.

    OfficeCLI 1.0.158 answers ``validate --json`` with a human message instead of a count object,
    so a successful envelope is the zero. Older builds return ``data.count``; both are accepted.
    """
    data = payload.get('data')
    if isinstance(data, dict):
        count = data.get('count')
        if isinstance(count, int):
            return count
    if payload.get('success') is True:
        return 0
    raise ValueError(f'OfficeCLI validate returned an unrecognised report: {payload}')


def inspect(pptx_path, executable='officecli'):
    """Read OfficeCLI's supplemental issue report from the flushed staging PPTX."""
    validation = _run(executable, 'validate', pptx_path)
    if schema_error_count(validation) != 0:
        raise ValueError(f'OfficeCLI staging schema validation did not pass: {validation.get("data")}')
    data = _run(executable, 'view', pptx_path, 'issues').get('data')
    if not isinstance(data, dict) or not isinstance(data.get('issues'), list):
        raise ValueError('OfficeCLI view issues returned an invalid JSON report')
    if data.get('count') != len(data['issues']):
        raise ValueError('OfficeCLI view issues count differs from its issue list')
    return data
