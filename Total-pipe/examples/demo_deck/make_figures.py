"""Draw the three figures of the demo deck from measured numbers, not from hand-typed ones.

``measurements.json`` is written by ``tools/demo_measurements.py``; this script only turns it into
pictures. Re-running both keeps the chart and the slide text consistent with the compiler.
"""
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrow, FancyBboxPatch

BASE = Path(__file__).resolve().parent
NAVY, INK, MUTED = '#142735', '#3E5566', '#8A9AA6'
LIGHT, RULE, ACCENT = '#E6EDF2', '#C7D4DD', '#C2410C'

for face in ('msyh.ttc', 'msyhbd.ttc'):
    path = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', face)
    if os.path.exists(path):
        font_manager.fontManager.addfont(path)
matplotlib.rcParams.update({'font.family': 'Microsoft YaHei', 'font.size': 12,
                            'text.color': NAVY, 'axes.edgecolor': RULE})


def clean(ax):
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)


def quality_figure(path):
    """One panel, not two: on a cover the figure gets half a page, so every mark must survive it."""
    data = {run['provider']: run for run in
            json.loads((BASE / 'measurements.json').read_text(encoding='utf-8'))['figure_fixture']}
    template, packed = data['compiler'], data['packer']
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=200)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=15, length=0)

    names = [f'模板 compiler\n最差页 {template["slack_max"]:.2f}×',
             f'打包器 packer\n最差页 {packed["slack_max"]:.2f}×']
    values = [template['slack_mean'], packed['slack_mean']]
    bars = ax.bar(names, values, width=.42, color=[MUTED, NAVY], zorder=3)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + .10, f'{value:.2f}×',
                ha='center', va='bottom', fontsize=30, color=NAVY,
                fontweight='bold' if value < 2 else 'normal')
    ax.axhline(1.0, color=ACCENT, lw=1.4, ls=(0, (5, 3)), zorder=2)
    ax.text(.5, 1.06, '1.00 = 框与文字等高', color=ACCENT, fontsize=15, ha='center',
            va='bottom')
    ax.set_ylim(0, 3.6)
    ax.set_ylabel('框高 ÷ 内容所需高度', color=INK, fontsize=16)
    ax.set_title('同一份双图夹具上的文本框贴合度', color=NAVY, fontsize=20, loc='left', pad=14)
    fig.subplots_adjust(left=.10, right=.97, top=.84, bottom=.17)
    fig.savefig(path, facecolor='white')
    plt.close(fig)


def stages_figure(path):
    """The six handoff points between a paper PDF and a PPTX."""
    stages = [('论文 PDF', '原始材料'), ('证据', 'PaperWorkflow\nEV 编号'),
              ('故事', 'Story Planner\n5–8 节点'), ('规划', 'RPA\n版式意图'),
              ('Deck IR', '唯一事实来源'), ('PPTX', 'OfficeCLI\n+ QA 门禁')]
    fig, ax = plt.subplots(figsize=(8.4, 3.2), dpi=200)
    clean(ax)
    step, gap = .1466, .0215
    for index, (name, detail) in enumerate(stages):
        x = .012 + index * (step + gap)
        fill = NAVY if index in (0, 4, 5) else LIGHT
        edge = NAVY if index in (0, 4, 5) else RULE
        ax.add_patch(FancyBboxPatch((x, .38), step, .44, boxstyle='round,pad=0,rounding_size=.016',
                                    facecolor=fill, edgecolor=edge, lw=1.1, zorder=3))
        ax.text(x + step / 2, .70, name, ha='center', va='center', fontsize=16,
                color='white' if index in (0, 4, 5) else NAVY,
                fontweight='bold')
        ax.text(x + step / 2, .52, detail, ha='center', va='center', fontsize=11.5,
                color='white' if index in (0, 4, 5) else INK, linespacing=1.6)
        if index < len(stages) - 1:
            ax.add_patch(FancyArrow(x + step + .003, .60, gap - .006, 0, width=.012,
                                    head_width=.055, head_length=.008, length_includes_head=True,
                                    facecolor=ACCENT, edgecolor='none', zorder=4))
    ax.set_ylim(.32, .88)
    fig.subplots_adjust(left=.01, right=.99, top=.98, bottom=.02)
    fig.savefig(path, facecolor='white')
    plt.close(fig)


def provider_figure(path):
    """The plug-in point: three providers, one contract, compiler-owned everything else."""
    fig, ax = plt.subplots(figsize=(7.4, 3.9), dpi=200)
    clean(ax)
    ax.set_ylim(.20, 1.0)
    providers = [('packer', '内置打包器 · 默认'), ('compiler', '模板 · 参考实现'),
                 ('module:factory', '外部插件 / 模型')]
    for index, (name, detail) in enumerate(providers):
        y = .78 - index * .155
        ax.add_patch(FancyBboxPatch((.02, y), .35, .115,
                                    boxstyle='round,pad=0,rounding_size=.012',
                                    facecolor=LIGHT, edgecolor=RULE, lw=1.1, zorder=3))
        ax.text(.045, y + .068, name, fontsize=13.5, color=NAVY, fontweight='bold', va='center')
        ax.text(.045, y + .028, detail, fontsize=10.5, color=MUTED, va='center')
        ax.add_patch(FancyArrow(.378, y + .055, .055, 0, width=.008, head_width=.038,
                                head_length=.013, length_includes_head=True,
                                facecolor=ACCENT, edgecolor='none', zorder=4))
    ax.add_patch(FancyBboxPatch((.445, .60), .175, .34, boxstyle='round,pad=0,rounding_size=.014',
                                facecolor=NAVY, edgecolor='none', zorder=3))
    ax.text(.533, .845, 'propose()', fontsize=14.5, color='white', fontweight='bold',
            ha='center', va='center')
    ax.text(.533, .735, '每单元\n一个 bbox', fontsize=11.5, color='#D8E2E9', ha='center',
            va='center', linespacing=1.5)
    ax.text(.533, .645, '仅此而已', fontsize=10.5, color='#9FB3BF', ha='center', va='center')
    ax.add_patch(FancyArrow(.628, .77, .05, 0, width=.008, head_width=.038, head_length=.013,
                            length_includes_head=True, facecolor=ACCENT, edgecolor='none', zorder=4))
    owned = [('内容与画框', '编译器所有，提供方不可写'), ('门禁 check()', '不过则整页回退模板'),
             ('写入与 QA', 'OfficeCLI + qa_report.json')]
    for index, (name, detail) in enumerate(owned):
        y = .845 - index * .165
        ax.add_patch(FancyBboxPatch((.69, y - .06), .29, .12,
                                    boxstyle='round,pad=0,rounding_size=.012',
                                    facecolor='white', edgecolor=NAVY, lw=1.2, zorder=3))
        ax.text(.835, y + .014, name, fontsize=12, color=NAVY, fontweight='bold',
                ha='center', va='center')
        ax.text(.835, y - .030, detail, fontsize=9.5, color=MUTED, ha='center', va='center')
    ax.text(.02, .34, '删掉模型，接口还在：', fontsize=11.5, color=ACCENT, va='center')
    ax.text(.02, .27, '新模型实现 propose() 即可接回，编译器与门禁一行不改。',
            fontsize=11.5, color=ACCENT, va='center')
    fig.subplots_adjust(left=.01, right=.99, top=.99, bottom=.01)
    fig.savefig(path, facecolor='white')
    plt.close(fig)


def main():
    figures = BASE / 'figures'
    figures.mkdir(exist_ok=True)
    quality_figure(figures / 'fig1_quality.png')
    stages_figure(figures / 'fig2_stages.png')
    provider_figure(figures / 'fig3_provider.png')
    for path in sorted(figures.glob('*.png')):
        from PIL import Image
        with Image.open(path) as image:
            print(f'{path.name}: {image.width}x{image.height}')


if __name__ == '__main__':
    main()
