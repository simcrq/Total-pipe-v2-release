#!/usr/bin/env python3
"""P0 PageSpec density / geometry guardrails.

The point is not to be a full layout engine. It catches the failure modes that
made the earlier deck unreadable: too many objects, too much copy, missing
images, text boxes outside the page and text-text collisions.

Usage:
  python check_pagespec.py demo.deck.json
"""
import json
import sys
from pathlib import Path

PAGE_W, PAGE_H = 13.333, 7.5
BODY_FLOOR = 18.0
LABEL_FLOOR = 11.0
CAPTION_FLOOR = 8.5


def bbox(obj):
    return tuple(float(v) for v in obj['box'])


def overlap(a, b, pad=0.02):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + pad <= bx or bx + bw + pad <= ax or ay + ah + pad <= by or by + bh + pad <= ay)


def check_page(page, index, spec_path):
    errs = []
    pid = page.get('id', 'P?')
    if not page.get('title'):
        errs.append('%s: title required' % pid)
    elif len(page['title']) > 28:
        errs.append('%s: title is %d chars (max 28)' % (pid, len(page['title'])))
    if not page.get('take'):
        errs.append('%s: take required' % pid)
    else:
        take_max = 110 if pid == 'P1' else 68
        if len(page['take']) > take_max:
            errs.append('%s: take is %d chars (max %d)' % (pid, len(page['take']), take_max))
    objects = page.get('objects', [])
    if len(objects) > 14:
        errs.append('%s: %d objects (max 14)' % (pid, len(objects)))
    body_texts = [o for o in objects if o.get('type') == 'text' and o.get('role', 'body') == 'body']
    if len(body_texts) > 4:
        errs.append('%s: %d body text blocks (max 4)' % (pid, len(body_texts)))
    body_chars = sum(len(o.get('text', '')) for o in body_texts)
    if body_chars > 260:
        errs.append('%s: %d body chars (max 260)' % (pid, body_chars))
    visuals = [o for o in objects if o.get('type') in ('image', 'table')]
    if len(visuals) > 3:
        errs.append('%s: %d image/table objects (max 3)' % (pid, len(visuals)))
    text_boxes = []
    for oi, obj in enumerate(objects):
        typ = obj.get('type')
        if not obj.get('box') or len(obj['box']) != 4:
            errs.append('%s/%s: box must have four numbers' % (pid, obj.get('id', oi)))
            continue
        x, y, w, h = bbox(obj)
        if w <= 0 or h <= 0:
            errs.append('%s/%s: box must have positive size' % (pid, obj.get('id', oi)))
            continue
        if typ != 'line':
            if x < -0.01 or y < -0.01 or x + w > PAGE_W + 0.01 or y + h > PAGE_H + 0.01:
                errs.append('%s/%s: box outside page' % (pid, obj.get('id', oi)))
        if typ == 'text':
            role = obj.get('role', 'body')
            floor = {'body': BODY_FLOOR, 'label': LABEL_FLOOR, 'caption': CAPTION_FLOOR}.get(role, 10.0)
            if obj.get('size', 18 if role == 'body' else 12) + 0.01 < floor:
                errs.append('%s/%s: %s text below %.1f pt' % (pid, obj.get('id', oi), role, floor))
            text_boxes.append((oi, obj.get('id', str(oi)), bbox(obj), role))
        if typ == 'image':
            path = Path(obj.get('path', ''))
            if not path.is_absolute():
                path = spec_path.parent / path
            if not path.is_file():
                errs.append('%s/%s: image not found: %s' % (pid, obj.get('id', oi), path))
        if typ == 'table':
            rows = obj.get('rows') or []
            if len(rows) < 2 or len(rows[0]) < 2:
                errs.append('%s/%s: table needs at least 2x2' % (pid, obj.get('id', oi)))
            if any(len(r) != len(rows[0]) for r in rows):
                errs.append('%s/%s: table rows have unequal columns' % (pid, obj.get('id', oi)))
    # Text-text collisions only. Diagrams may put text over a shape; that is intentional.
    for i in range(len(text_boxes)):
        for j in range(i + 1, len(text_boxes)):
            _, a_id, a, a_role = text_boxes[i]
            _, b_id, b, b_role = text_boxes[j]
            if a_role == 'caption' or b_role == 'caption':
                continue
            if overlap(a, b):
                errs.append('%s: text collision %s vs %s' % (pid, a_id, b_id))
    return errs, body_chars, len(visuals)


def main():
    if len(sys.argv) != 2:
        print('usage: python check_pagespec.py <spec.json>')
        return 2
    path = Path(sys.argv[1])
    spec = json.loads(path.read_text(encoding='utf-8'))
    pages = spec.get('pages', [])
    all_errors = []
    ids = set()
    for i, page in enumerate(pages, 1):
        pid = page.get('id', 'P%d' % i)
        if pid in ids:
            all_errors.append('%s: duplicate page id' % pid)
        ids.add(pid)
        errs, body_chars, visuals = check_page(page, i, path)
        all_errors.extend(errs)
        print('%s: body_chars=%d visuals=%d objects=%d' % (pid, body_chars, visuals, len(page.get('objects', []))))
    if all_errors:
        print('\nFAIL:')
        for e in all_errors:
            print(' -', e)
        return 1
    print('\nPASS: %d pages' % len(pages))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
