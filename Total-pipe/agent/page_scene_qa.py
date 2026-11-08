#!/usr/bin/env python3
"""PageScene guardrails and page-level native preview.

This module is intentionally separate from the existing Deck IR compiler:
- it validates explicit page bboxes and density;
- it renders a single PageScene to PPTX;
- it exports selected pages through PowerPoint and returns PNGs for human review.

The job layer calls `preview_pages()` from `advance.scene_preview` before accepting
a scene, and `render_spec()` / `page_scene_build.build()` for a candidate.
"""
import argparse
import json
import sys
from pathlib import Path

from .page_scene import Renderer

PAGE_W, PAGE_H = 13.333, 7.5
BODY_FLOOR = 18.0
LABEL_FLOOR = 11.0
CAPTION_FLOOR = 8.5
SCHEMA = Path(__file__).with_name('schemas')/'page-scene.schema.json'


def _box(obj):
    return tuple(float(v) for v in obj['box'])


def _overlap(a, b, pad=0.02):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + pad <= bx or bx + bw + pad <= ax or ay + ah + pad <= by or by + bh + pad <= ay)


def _flatten_objects(objects, dx=0.0, dy=0.0):
    """Expand groups into absolute boxes so density and collision checks see children."""
    import copy
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if obj.get('type') == 'group':
            gx, gy = (obj.get('box') or [0, 0])[:2]
            yield from _flatten_objects(obj.get('children') or [], dx + gx, dy + gy)
            continue
        out = copy.deepcopy(obj)
        if out.get('box') and len(out['box']) == 4:
            out['box'] = [out['box'][0] + dx, out['box'][1] + dy, out['box'][2], out['box'][3]]
        yield out


def _text_len(obj, bindings):
    if obj.get('copy_ref'):
        return len(bindings.get(obj['copy_ref'], ''))
    return len(obj.get('text', ''))


def _resolve_field(page, field, bindings):
    ref = page.get(field + '_ref')
    if ref:
        if ref not in bindings:
            return None, '%s_ref unresolved: %s' % (field, ref)
        return bindings[ref], None
    return page.get(field, ''), None


def _resolve_item(item, bindings):
    if item.get('copy_ref'):
        return bindings.get(item['copy_ref'])
    return item.get('text', '')


def validate_spec(spec, spec_path):
    """Return (errors, page_metrics). Explicit geometry and density only."""
    errors = []
    if not isinstance(spec, dict) or spec.get('schema_version') != '0.1':
        return ['spec.schema_version must be 0.1'], []
    pages = spec.get('pages')
    if not isinstance(pages, list) or not pages:
        return ['spec.pages must be a non-empty list'], []
    if len(pages) > 40:
        return ['spec.pages supports at most 40 pages'], []
    metrics = []
    ids = set()
    for index, page in enumerate(pages, 1):
        pid = page.get('id') or 'P%d' % index
        if pid in ids:
            errors.append('%s: duplicate page id' % pid)
        ids.add(pid)
        bindings = spec.get('bindings') or {}
        title, problem = _resolve_field(page, 'title', bindings)
        take, take_problem = _resolve_field(page, 'take', bindings)
        if problem:
            errors.append('%s: %s' % (pid, problem))
        if take_problem:
            errors.append('%s: %s' % (pid, take_problem))
        if not title:
            errors.append('%s: title required' % pid)
        elif len(title) > 28:
            errors.append('%s: title is %d chars (max 28)' % (pid, len(title)))
        if not take:
            errors.append('%s: take required' % pid)
        else:
            take_max = 110 if index == 1 else 68
            if len(take) > take_max:
                errors.append('%s: take is %d chars (max %d)' % (pid, len(take), take_max))
        raw_objects = page.get('objects', [])
        if not isinstance(raw_objects, list):
            errors.append('%s: objects must be a list' % pid)
            raw_objects = []
        objects = list(_flatten_objects(raw_objects))
        allowed = {'text', 'list', 'image', 'shape', 'line', 'table', 'group',
                   'formula', 'path', 'chart'}
        unknown = sorted({str(obj.get('type')) for obj in objects if obj.get('type') not in allowed})
        if unknown:
            errors.append('%s: unknown object type(s): %s' % (pid, ', '.join(unknown)))
        if len(objects) > 14:
            errors.append('%s: %d objects (max 14)' % (pid, len(objects)))
        body_texts = [o for o in objects if o.get('type') in ('text', 'list') and o.get('role', 'body') == 'body']
        if len(body_texts) > 4:
            errors.append('%s: %d body text blocks (max 4)' % (pid, len(body_texts)))
        body_chars = 0
        for o in body_texts:
            if o.get('type') == 'list':
                body_chars += sum(_text_len(item, bindings) for item in (o.get('items') or []))
            else:
                body_chars += _text_len(o, bindings)
        if body_chars > 260:
            errors.append('%s: %d body chars (max 260)' % (pid, body_chars))
        visuals = [o for o in objects if o.get('type') in ('image', 'table', 'chart')]
        if len(visuals) > 3:
            errors.append('%s: %d image/table/chart objects (max 3)' % (pid, len(visuals)))
        text_boxes = []
        for oi, obj in enumerate(objects):
            typ = obj.get('type')
            box = obj.get('box')
            if not box or len(box) != 4:
                errors.append('%s/%s: box must have four numbers' % (pid, obj.get('id', oi)))
                continue
            x, y, w, h = _box(obj)
            if w <= 0 or h <= 0:
                errors.append('%s/%s: box must have positive size' % (pid, obj.get('id', oi)))
                continue
            if typ != 'line' and (x < -0.01 or y < -0.01 or x + w > PAGE_W + 0.01 or y + h > PAGE_H + 0.01):
                errors.append('%s/%s: box outside page' % (pid, obj.get('id', oi)))
            if typ in ('text', 'list'):
                role = obj.get('role', 'body')
                floor = {'body': BODY_FLOOR, 'label': LABEL_FLOOR, 'caption': CAPTION_FLOOR}.get(role, 10.0)
                if obj.get('size', 18 if role == 'body' else 12) + 0.01 < floor:
                    errors.append('%s/%s: %s text below %.1f pt' % (pid, obj.get('id', oi), role, floor))
                if typ == 'list':
                    for item in obj.get('items') or []:
                        isize = item.get('size', obj.get('size', 18))
                        if isize + 0.01 < BODY_FLOOR:
                            errors.append('%s/%s: list item below %.1f pt' % (pid, obj.get('id', oi), BODY_FLOOR))
                        ref = item.get('copy_ref')
                        if ref and ref not in bindings:
                            errors.append('%s/%s: unresolved item copy_ref %s' % (pid, obj.get('id', oi), ref))
                if obj.get('copy_ref') and obj['copy_ref'] not in bindings:
                    errors.append('%s/%s: unresolved copy_ref %s' % (pid, obj.get('id', oi), obj['copy_ref']))
                text_boxes.append((oi, obj.get('id', str(oi)), _box(obj), role))
            if typ == 'image':
                path = Path(obj.get('path', ''))
                if not path.is_absolute():
                    path = Path(spec_path).parent / path
                if not path.is_file():
                    errors.append('%s/%s: image not found: %s' % (pid, obj.get('id', oi), path))
            if typ == 'table':
                rows = obj.get('rows') or []
                if len(rows) < 2 or len(rows[0]) < 2:
                    errors.append('%s/%s: table needs at least 2x2' % (pid, obj.get('id', oi)))
                if any(len(r) != len(rows[0]) for r in rows):
                    errors.append('%s/%s: table rows have unequal columns' % (pid, obj.get('id', oi)))
            if typ == 'formula':
                if not isinstance(obj.get('latex'), str) or not obj['latex'].strip():
                    errors.append('%s/%s: formula requires a non-empty latex string' % (pid, obj.get('id', oi)))
                else:
                    try:
                        from totalpipe_layout.formula import parse
                        parse(obj['latex'])
                    except Exception as error:
                        errors.append('%s/%s: invalid latex: %s' % (pid, obj.get('id', oi), error))
                if obj.get('size', 20) + 0.01 < 14:
                    errors.append('%s/%s: formula below 14 pt' % (pid, obj.get('id', oi)))
            if typ == 'path':
                if ('commands' in obj) == ('d' in obj):
                    errors.append('%s/%s: path requires exactly one of commands or d' % (pid, obj.get('id', oi)))
                else:
                    try:
                        from deck_compiler.graphic_paths import parse_path
                        parse_path(obj.get('commands', obj.get('d')))
                    except Exception as error:
                        errors.append('%s/%s: invalid path: %s' % (pid, obj.get('id', oi), error))
                view_box = obj.get('view_box')
                if view_box is not None and (not isinstance(view_box, list) or len(view_box) != 4 or
                                             any(not isinstance(value, (int, float)) for value in view_box) or
                                             view_box[2] <= 0 or view_box[3] <= 0):
                    errors.append('%s/%s: view_box must be [x,y,w,h] with positive size' % (pid, obj.get('id', oi)))
            if typ == 'chart':
                series = obj.get('series')
                if not isinstance(series, list) or not series:
                    errors.append('%s/%s: chart requires at least one series' % (pid, obj.get('id', oi)))
                else:
                    for series_index, item in enumerate(series):
                        if not isinstance(item, dict) or not isinstance(item.get('values'), list) or not item['values']:
                            errors.append('%s/%s: chart series %d needs values' % (pid, obj.get('id', oi), series_index))
                    categories = obj.get('categories')
                    if categories is not None and (not isinstance(categories, list) or
                                                   len(categories) != len(series[0].get('values') or [])):
                        errors.append('%s/%s: chart categories must match series length' % (pid, obj.get('id', oi)))
                if obj.get('chart_type') not in ('line', 'bar', 'column', 'scatter'):
                    errors.append('%s/%s: chart_type must be line, bar, column or scatter' % (pid, obj.get('id', oi)))
        for i in range(len(text_boxes)):
            for j in range(i + 1, len(text_boxes)):
                _, a_id, a, a_role = text_boxes[i]
                _, b_id, b, b_role = text_boxes[j]
                if a_role == 'caption' or b_role == 'caption':
                    continue
                if _overlap(a, b):
                    errors.append('%s: text collision %s vs %s' % (pid, a_id, b_id))
        metrics.append({'page_id': pid, 'body_chars': body_chars, 'visuals': len(visuals), 'objects': len(objects)})
    return errors, metrics


def expression_report(spec, spec_path):
    """Positive report: native moves, inline math, card area and list-style mix.

    This is intentionally advisory for the pilot. It measures whether a deck uses the
    renderer's native vocabulary instead of turning every page into a text block.
    """
    import re
    spec_path = Path(spec_path)
    bindings = spec.get('bindings') or {}
    rows, styles = [], set()
    for page in spec.get('pages') or []:
        title, _ = _resolve_field(page, 'title', bindings)
        take, _ = _resolve_field(page, 'take', bindings)
        text = [title or '', take or '']
        formulas = len(re.findall(r'\$[^$]+\$', (title or '') + ' ' + (take or '')))
        objects = list(_flatten_objects(page.get('objects') or []))
        native, card_area = 0, 0.0
        lists = 0
        for obj in objects:
            kind = obj.get('type')
            if kind == 'text':
                value = _resolve_item(obj, bindings) or ''
                text.append(value)
                formulas += len(re.findall(r'\$[^$]+\$', value))
            elif kind == 'list':
                items = obj.get('items') or []
                lists += 1
                styles.add(obj.get('bullet_style', 'dot'))
                if len(items) >= 2:
                    native += 1
                for item in items:
                    value = _resolve_item(item, bindings) or ''
                    text.append(value)
                    formulas += len(re.findall(r'\$[^$]+\$', value))
            elif kind in ('image', 'table', 'chart', 'path', 'formula'):
                native += 1
            elif kind == 'shape':
                area = float(obj['box'][2]) * float(obj['box'][3])
                fill = str(obj.get('fill', 'none')).upper()
                if area > 0.5 and fill not in ('NONE', '#FFFFFF', 'FFFFFF'):
                    card_area += area
        plain = ''.join(text)
        text_only = native == 0
        rows.append({'page_id': page.get('id'), 'native_moves': native, 'lists': lists,
                     'inline_math': formulas, 'card_area': round(card_area, 2),
                     'text_only': text_only, 'chars': len(plain)})
    total = len(rows) or 1
    summary = {
        'pages': len(rows),
        'text_only_pages': sum(row['text_only'] for row in rows),
        'card_area': round(sum(row['card_area'] for row in rows), 2),
        'inline_math': sum(row['inline_math'] for row in rows),
        'list_styles': sorted(styles),
        'native_move_pages': sum(row['native_moves'] > 0 for row in rows),
    }
    summary['status'] = ('PASS' if summary['text_only_pages'] == 0
                         and summary['card_area'] <= 0.01
                         and summary['inline_math'] > 0
                         and len(summary['list_styles']) >= 2 else 'REVIEW')
    return {'spec': str(spec_path), 'pages': rows, 'summary': summary}


def check_file(path):
    path = Path(path)
    spec = json.loads(path.read_text(encoding='utf-8'))
    errors, metrics = validate_spec(spec, path)
    report = {'status': 'FAIL' if errors else 'PASS', 'pages': len(spec.get('pages', [])),
              'metrics': metrics, 'errors': errors, 'schema': str(SCHEMA)}
    if not errors:
        report['expression'] = expression_report(spec, path)
    return report


def render_spec(spec, spec_path, out):
    spec_path = Path(spec_path)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    renderer = Renderer(spec, spec_path)
    for index, page in enumerate(spec['pages'], 1):
        renderer.render_page(page, index, len(spec['pages']))
    renderer.save(out)
    return out


def preview_page(spec_path, page_id, out_dir):
    """Render one page to a native PowerPoint PDF/PNG and return explicit checks."""
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    errors, _ = validate_spec(spec, spec_path)
    page = next((p for p in spec.get('pages', []) if p.get('id') == page_id), None)
    if page is None:
        return {'status': 'FAIL', 'page_id': page_id, 'issues': ['unknown page id'], 'errors': errors}
    if errors:
        return {'status': 'FAIL', 'page_id': page_id, 'issues': errors}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    original_index = spec['pages'].index(page) + 1
    page = dict(page)
    page['page_number'] = page.get('page_number', original_index)
    one = dict(spec)
    one['pages'] = [page]
    # A one-page preview is written outside the original spec folder, so image
    # paths must be resolved before the temporary spec is serialized. Groups can
    # nest images, so resolve recursively rather than only at the top level.
    def resolve_images(objects):
        for obj in objects or []:
            if not isinstance(obj, dict):
                continue
            if obj.get('type') == 'image':
                image_path = Path(obj.get('path', ''))
                if image_path and not image_path.is_absolute():
                    obj['path'] = str((spec_path.parent / image_path).resolve())
            if obj.get('type') == 'group':
                resolve_images(obj.get('children'))
    resolve_images(one['pages'][0].get('objects'))
    one_path = out_dir/('%s.pagespec.json' % page_id)
    one_path.write_text(json.dumps(one, ensure_ascii=False, indent=2), encoding='utf-8')
    pptx = out_dir/('%s.pptx' % page_id)
    pdf = out_dir/('%s.pdf' % page_id)
    png = out_dir/('%s.png' % page_id)
    render_spec(one, one_path, pptx)
    from deck_compiler import native
    evidence, issues = native.render(pptx, pdf)
    if not evidence:
        return {'status': 'BLOCKED', 'page_id': page_id, 'pdf': str(pdf), 'png': None,
                'issues': [i.get('message', str(i)) for i in issues]}
    try:
        import pdfplumber
        with pdfplumber.open(pdf) as doc:
            if len(doc.pages) != 1:
                issues.append({'rule': 'NATIVE_PAGE_COUNT', 'severity': 'FAIL',
                               'message': 'page preview PDF must contain exactly one page'})
            page_pdf = doc.pages[0]
            page_pdf.to_image(resolution=150).original.convert('RGB').save(png)
            for char in page_pdf.chars:
                if (char['x0'] < -1 or char['y0'] < -1 or
                        char['x1'] > page_pdf.width + 1 or char['bottom'] > page_pdf.height + 1):
                    issues.append({'rule': 'NATIVE_TEXT_OUT_OF_BOUNDS', 'severity': 'FAIL',
                                   'message': 'rendered text exceeds the page'})
                    break
    except Exception as error:
        issues.append({'rule': 'PREVIEW_RASTERIZE_FAILED', 'severity': 'FAIL', 'message': str(error)})
    fails = [i for i in issues if i.get('severity') == 'FAIL']
    return {'status': 'FAIL' if fails else 'PASS', 'page_id': page_id, 'pdf': str(pdf),
            'png': str(png) if png.exists() else None, 'issues': issues,
            'evidence': evidence}


def preview_pages(spec_path, page_ids, out_dir):
    """Render several selected pages natively and return one review manifest.

    This is a review utility: it never writes ``work/page_scene.json``, never
    accepts a draft and never touches the candidate.  A contact sheet is produced
    only from successfully rasterized pages.
    """
    from PIL import Image, ImageDraw
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    known = [page.get('id') for page in spec.get('pages', [])]
    selected = list(page_ids or known)
    unknown = [page_id for page_id in selected if page_id not in known]
    if unknown:
        return {'status': 'FAIL', 'pages': [], 'issues': [f'unknown page ids: {unknown}'],
                'job_unchanged': True, 'candidate_unchanged': True}
    results = []
    for page_id in selected:
        folder = Path(out_dir) / page_id
        results.append(preview_page(spec_path, page_id, folder))
    thumbs = []
    for result in results:
        if not result.get('png'):
            continue
        picture = Image.open(result['png']).convert('RGB')
        picture.thumbnail((480, 270))
        thumb = Image.new('RGB', (496, 306), '#edf0f4')
        thumb.paste(picture, ((496 - picture.width) // 2, 12))
        ImageDraw.Draw(thumb).text((12, 286), str(result.get('page_id')), fill='#263348')
        thumbs.append(thumb)
    contact = None
    if thumbs:
        columns = min(3, len(thumbs))
        sheet = Image.new('RGB', (496 * columns, 306 * ((len(thumbs) + columns - 1) // columns)), 'white')
        for index, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((index % columns) * 496, (index // columns) * 306))
        contact = Path(out_dir) / 'scene-contact.png'
        sheet.save(contact)
    statuses = {result.get('status') for result in results}
    status = 'FAIL' if 'FAIL' in statuses else 'BLOCKED' if 'BLOCKED' in statuses else 'PASS'
    return {'status': status, 'pages': results, 'contact_sheet': str(contact) if contact else None,
            'renderer': 'powerpoint', 'powerpoint_ui_review': False,
            'job_unchanged': True, 'candidate_unchanged': True,
            'note': 'PNG/PDF inspection is not a PowerPoint UI review and does not accept the scene.'}


def main():
    parser = argparse.ArgumentParser(description='Total-pipe PageScene P0 CLI')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('check')
    p.add_argument('--spec', required=True, type=Path)
    p = sub.add_parser('render')
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p = sub.add_parser('preview')
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--page', required=True)
    p.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'check':
        result = check_file(args.spec)
    elif args.command == 'render':
        spec = json.loads(args.spec.read_text(encoding='utf-8'))
        errors, _ = validate_spec(spec, args.spec)
        if errors:
            result = {'status': 'FAIL', 'errors': errors}
        else:
            out = render_spec(spec, args.spec, args.out)
            result = {'status': 'PASS', 'output': str(out)}
    else:
        result = preview_page(args.spec, args.page, args.out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('status') in ('PASS', 'BLOCKED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
