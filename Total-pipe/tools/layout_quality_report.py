"""Measure a compiled deck: how much of each box is empty, and how small the type got.

The numbers exist because "looks fine" is not a review criterion. Two are taken from real review
sessions and are the ones the packer is tuned against:

* text slack -- delivered box height divided by the height the text actually needs. A box at 1.0 is
  exactly its content; 2.0 is a box with as much empty space as text. Side-by-side boxes share one
  height on purpose, so the row's tallest content is the fair denominator, not each box alone.
* figure void -- the fraction of a figure rectangle the contain-fitted picture cannot cover. The
  compiler centres the picture in the rectangle it is given, so a rectangle that ignores the
  picture's aspect shows a visible band.

Also reported: the smallest fitted type size, orphan trailing lines (one or two characters), and the
FAIL count from the QA report. Usage:

    python tools/layout_quality_report.py --build <out dir> --ir <deck_ir.json> [--json]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def row_groups(entries, tolerance=12.0):
    groups = []
    for entry in entries:
        if entry['role'] == 'figure':
            continue
        for group in groups:
            if abs(entry['bbox'][1]-group[0]) <= tolerance:
                group[1].append(entry)
                break
        else:
            groups.append((entry['bbox'][1], [entry]))
    return [members for _, members in groups if len(members) >= 2]


def measure(build_dir, ir_path):
    from totalpipe_layout.contracts import (figure_picture_void, read_requests,
                                            required_height)
    build = Path(build_dir)
    layout = json.loads((build/'layout.json').read_text(encoding='utf-8'))
    qa = json.loads((build/'qa_report.json').read_text(encoding='utf-8'))
    requests, _ = read_requests(ir_path, ROOT)
    by_slide = {request['slide_id']: request for request in requests}
    slacks, voids, fonts, orphans = [], [], [], []
    pages = []
    for page in layout['slides']:
        request = by_slide.get(page['id'])
        if request is None:
            continue
        units = {unit['id']: unit for unit in request['units']}
        entries = []
        for element in page['elements']:
            unit = units.get(element['id'])
            if unit is None or unit['role'] == 'figure':
                continue
            need = required_height(unit, element['bbox'][2], request)
            if need >= 10000:
                continue
            role = element.get('role', '')
            if role in ('title', 'takeaway', 'footer', 'caption', 'heading', 'bullet'):
                continue
            entries.append({'id': element['id'], 'role': unit['role'], 'bbox': element['bbox'],
                            'need': need, 'slack': element['bbox'][3]/max(need, 1e-6)})
            contract = element.get('contract') or {}
            if contract.get('font_size'):
                fonts.append(contract['font_size'])
            for line in (element.get('text') or '').split('\n'):
                if line.strip() and len(line.strip()) < 3:
                    orphans.append({'slide': page['id'], 'id': element['id'], 'line': line})
        for group in row_groups(entries):
            tallest = max(entry['need'] for entry in group)
            for entry in group:
                slacks.append(entry['bbox'][3]/max(tallest, 1e-6))
        for element_id, unit in units.items():
            if unit['role'] != 'figure':
                continue
            element = next((e for e in page['elements'] if e['id'] == element_id), None)
            if element is None:
                continue
            caption_height = (next((e['bbox'][3] for e in page['elements']
                                    if e['id'] == element_id+':caption'), 0))
            rect = [element['bbox'][0], element['bbox'][1], element['bbox'][2],
                    element['bbox'][3]+caption_height+12]
            voids.append(figure_picture_void(unit, rect, request))
        pages.append({'slide': page['id'], 'elements': len(page['elements'])})
    return {
        'build': str(build), 'ir': str(ir_path), 'pages': len(pages),
        'text_slack_mean': round(sum(slacks)/len(slacks), 3) if slacks else None,
        'text_slack_max': round(max(slacks), 3) if slacks else None,
        'text_boxes_measured': len(slacks),
        'figure_void_mean': round(sum(voids)/len(voids), 4) if voids else None,
        'figure_void_max': round(max(voids), 4) if voids else None,
        'figures_measured': len(voids),
        'min_font_pt': min(fonts) if fonts else None,
        'orphan_lines': len(orphans), 'orphan_examples': orphans[:5],
        'qa_fail': qa['counts']['FAIL'], 'qa_warning': qa['counts']['WARNING'],
        'qa_review': qa['counts']['REVIEW'],
        'provider': (layout.get('layout_provider') or {}).get('name'),
        'provider_counts': (layout.get('layout_provider') or {}).get('counts'),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', required=True, help='directory produced by deck_compiler compile')
    parser.add_argument('--ir', required=True, help='canonical deck_ir.json that produced it')
    parser.add_argument('--json', action='store_true')
    arguments = parser.parse_args()
    result = measure(arguments.build, arguments.ir)
    if arguments.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"deck {Path(arguments.ir).name}  pages={result['pages']}  provider={result['provider']} "
          f"{result['provider_counts']}")
    print(f"  text slack  mean {result['text_slack_mean']}  max {result['text_slack_max']} "
          f"({result['text_boxes_measured']} boxes)")
    print(f"  figure void mean {result['figure_void_mean']}  max {result['figure_void_max']} "
          f"({result['figures_measured']} figures)")
    print(f"  min font {result['min_font_pt']} pt  orphans {result['orphan_lines']}")
    print(f"  qa FAIL {result['qa_fail']}  WARNING {result['qa_warning']}  REVIEW {result['qa_review']}")


if __name__ == '__main__':
    main()
