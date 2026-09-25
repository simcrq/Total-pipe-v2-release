"""OfficeCLI backend for the compiled layout protocol (CSS pixels at 96 dpi)."""
import json
import os
from pathlib import Path
import subprocess


def _px(value):
    return (f'{value:.6f}'.rstrip('0').rstrip('.') or '0') + 'px'


def _pt(css_pixels):
    return (f'{css_pixels * .75:.6f}'.rstrip('0').rstrip('.') or '0') + 'pt'


def _color(value):
    return value.lstrip('#') if value and value != 'none' else 'none'


def commands(layout):
    """Translate only compiled geometry; Deck IR remains the sole content source."""
    width, height = layout['slide_size']
    result = [{'command': 'set', 'path': '/', 'props': {
        'slideWidth': _px(width), 'slideHeight': _px(height)}}]
    for index, slide in enumerate(layout['slides'], 1):
        parent = f'/slide[{index}]'
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
            elif kind == 'text':
                contract = element['contract']
                props.update({'name': element['id'], 'text': element['text'],
                              'font': contract['font_family'], 'size': _pt(contract['font_size']),
                              'bold': str(contract['font_weight'] >= 700).lower(),
                              'color': _color(element['color']), 'fill': 'none', 'line': 'none',
                              'autoFit': 'none', 'margin': '0px',
                              'valign': 'center' if contract['vertical_anchor'] == 'middle'
                                        else contract['vertical_anchor']})
                typ = 'shape'
            else:
                raise ValueError(f'Unsupported compiled element kind: {kind}')
            result.append({'command': 'add', 'parent': parent, 'type': typ, 'props': props})
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
    if (validation.get('data') or {}).get('count') != 0:
        raise ValueError(f'OfficeCLI schema validation did not pass: {validation.get("data")}')
    return batch_path


def inspect(pptx_path, executable='officecli'):
    """Read OfficeCLI's supplemental issue report from the flushed staging PPTX."""
    validation = _run(executable, 'validate', pptx_path).get('data') or {}
    if validation.get('count') != 0:
        raise ValueError(f'OfficeCLI staging schema validation did not pass: {validation}')
    data = _run(executable, 'view', pptx_path, 'issues').get('data')
    if not isinstance(data, dict) or not isinstance(data.get('issues'), list):
        raise ValueError('OfficeCLI view issues returned an invalid JSON report')
    if data.get('count') != len(data['issues']):
        raise ValueError('OfficeCLI view issues count differs from its issue list')
    return data
