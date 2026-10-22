"""Draw a schematic (flow, trend or mermaid) so a page never has to ship a blank where a figure goes.

A generated diagram is not a paper figure: the deck says ``origin: generated`` and the caption says
示意图, so a reviewer can tell the two apart. The spec and this script are committed next to the
image, which is what keeps the picture reproducible.

    python tools/make_schematic.py --spec examples/schematic/flow.json --out examples/schematic/flow.png

Spec (JSON):

    {"kind": "flow",  "nodes": ["论文 PDF", "证据筛选", "故事", "页面规划", "PPTX"]}
    {"kind": "trend", "x_label": "功率 (W)", "y_label": "去除深度 (nm)",
     "series": [{"label": "样品 A", "points": [[1, 12], [2, 25], [3, 41]]}]}
    {"kind": "mermaid", "source": "graph LR; A[论文] --> B[证据]; B --> C[PPTX]"}

``--backend auto`` uses mermaid-cli when the spec is mermaid and ``mmdc`` is installed, and the
native renderer otherwise; ``--backend native`` never shells out.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrow, FancyBboxPatch

NAVY, INK, MUTED = '#142735', '#3E5566', '#8A9AA6'
LIGHT, RULE, ACCENT = '#E6EDF2', '#C7D4DD', '#C2410C'


def _culture_font():
    """Pick an installed face that can draw Chinese and register it with matplotlib."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from deck_compiler.fonts import discover_fonts
    fonts = discover_fonts()
    for family in ('Microsoft YaHei', 'Noto Sans CJK SC', 'SimHei', 'Arial', 'DejaVu Sans'):
        path = (fonts.get(family) or {}).get('regular')
        if path and Path(path).is_file():
            font_manager.fontManager.addfont(path)
            return font_manager.FontProperties(fname=path).get_name(), path
    raise SystemExit('no usable font found; set TOTALPIPE_FONT_DIR to a directory with a CJK face')


def _wrap(label, per_line):
    label = str(label).strip()
    if len(label) <= per_line:
        return label
    lines, current = [], ''
    for char in label:
        current += char
        if len(current) >= per_line:
            lines.append(current)
            current = ''
    if current:
        lines.append(current)
    return '\n'.join(lines)


def flow(spec, path, family):
    nodes = [str(node) for node in spec.get('nodes') or []]
    if not 2 <= len(nodes) <= 6:
        raise SystemExit('flow needs two to six nodes')
    longest = max(len(node) for node in nodes)
    per_line = 6 if longest > 8 else 10
    labels = [_wrap(node, per_line) for node in nodes]
    # 2.6:1 keeps the strip above the 220 px panel floor in a 672 px figure slot; the data window is
    # fitted to 1.7x the box height so the boxes fill the frame instead of floating in white.
    fig, ax = plt.subplots(figsize=(7.0, 2.69), dpi=200)
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(.32, .80)
    step = (1 - .024) / len(labels) - .021
    gap = .021
    for index, label in enumerate(labels):
        x = .012 + index * (step + gap)
        ax.add_patch(FancyBboxPatch((x, .40), step, .28, boxstyle='round,pad=0,rounding_size=.016',
                                    facecolor=NAVY if index == len(labels) - 1 else LIGHT,
                                    edgecolor=NAVY if index == len(labels) - 1 else RULE,
                                    lw=1.1, zorder=3))
        ax.text(x + step / 2, .54, label, ha='center', va='center', fontsize=15,
                color='white' if index == len(labels) - 1 else NAVY, linespacing=1.6)
        if index < len(labels) - 1:
            ax.add_patch(FancyArrow(x + step + .003, .54, gap - .006, 0, width=.012,
                                    head_width=.06, head_length=.008, length_includes_head=True,
                                    facecolor=ACCENT, edgecolor='none', zorder=4))
    note = spec.get('note')
    if note:
        ax.text(.012, .345, note, fontsize=9.5, color=MUTED, va='center')
    fig.subplots_adjust(left=.01, right=.99, top=.99, bottom=.01)
    fig.savefig(path, facecolor='white')
    plt.close(fig)


def trend(spec, path, family):
    series = spec.get('series') or []
    if not series:
        raise SystemExit('trend needs at least one series')
    fig, ax = plt.subplots(figsize=(8.0, 4.4), dpi=200)
    colors = (NAVY, ACCENT, MUTED, INK)
    for index, item in enumerate(series):
        points = item.get('points') or []
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        ax.plot(xs, ys, marker='o', markersize=4, linewidth=2,
                color=colors[index % len(colors)], label=item.get('label'))
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.grid(axis='y', color=RULE, linewidth=.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=10, length=0)
    if spec.get('x_label'):
        ax.set_xlabel(spec['x_label'], color=INK, fontsize=11)
    if spec.get('y_label'):
        ax.set_ylabel(spec['y_label'], color=INK, fontsize=11)
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, facecolor='white')
    plt.close(fig)


def mermaid(spec, path, backend):
    source = spec.get('source')
    if not source:
        raise SystemExit('mermaid spec needs a "source" field')
    mmdc = shutil.which('mmdc')
    if backend == 'native' or not mmdc:
        raise SystemExit('mermaid rendering needs mermaid-cli (mmdc) on PATH; '
                         'install it or switch the spec to "flow"')
    work = Path(path).with_suffix('.mmd')
    work.write_text(source, encoding='utf-8')
    subprocess.run([mmdc, '-i', str(work), '-o', str(path), '-b', 'white', '-w', '1600'],
                   check=True, timeout=180)
    return {'backend': 'mermaid-cli', 'source': str(work)}


def render(spec, path, backend='auto'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    family, font_path = _culture_font()
    matplotlib.rcParams.update({'font.family': family, 'text.color': NAVY})
    kind = spec.get('kind')
    if kind == 'flow':
        flow(spec, path, family)
    elif kind == 'trend':
        trend(spec, path, family)
    elif kind == 'mermaid':
        return mermaid(spec, path, backend)
    else:
        raise SystemExit(f'unknown schematic kind: {kind!r}')
    return {'backend': 'native', 'font': font_path}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Draw a schematic PNG for a deck.')
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--backend', choices=('auto', 'native', 'mermaid'), default='auto')
    args = parser.parse_args(argv)
    spec = json.loads(Path(args.spec).read_text(encoding='utf-8'))
    result = render(spec, args.out, args.backend)
    print(json.dumps({'out': args.out, **result}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
