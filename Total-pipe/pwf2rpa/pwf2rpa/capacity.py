"""RPA layout-library capacity table (generated data -- do not hand-edit).

Regenerate against a checkout of research-ppt-assistant with::

    python3 -m pwf2rpa refresh-capacity --rpa-root <path/to/research-ppt-assistant>

Why this table exists
---------------------
RPA gates a page twice, and both gates are pure functions of the slide brief:

1. ``layout-retriever.mjs`` filters candidate layouts by hard capacity
   constraints (title chars, total text chars, image/table/chart counts,
   process steps, and the minimum display width each visual type needs).
2. ``slot-binding.mjs`` then pours the brief's text into concrete slots and
   raises ``SLOT_CAPACITY_EXCEEDED`` when an untrimmable item does not fit.

Reproducing those numbers offline lets the adapter explain a problem in terms
of the offending field and its ceiling, instead of leaving the author to infer
it from a relaxed category hint several commands later.

All 320 layouts are listed rather than one envelope per category,
because the number of layouts that can hold a page matters on its own: RPA
passes already-used layout ids back as ``exclude_ids``, so a deck reusing one
category competes for a shrinking pool of variants.

``Layout.text_slots`` is ordered the way slot-binding fills slots (priority
descending, then reading order), so a left-to-right greedy walk mirrors RPA's
own assignment order. A ``max_chars`` of ``None`` means the slot has no
character ceiling.
"""

from typing import NamedTuple

__all__ = [
    "CATEGORIES",
    "CONTENT_ROLES",
    "Category",
    "LAYOUT_LIBRARY_VERSION",
    "Layout",
    "VIEWING_MODE",
    "VISUAL_TYPE_MIN_WIDTH",
]

LAYOUT_LIBRARY_VERSION = "2.0.0"
VIEWING_MODE = "projector"


class Layout(NamedTuple):
    """The capacity envelope of one concrete layout."""

    title_chars: int | None
    """Title slot ceiling at the minimum readable font; ``None`` if unbounded."""

    text_chars: int
    """Whole-page body-text ceiling enforced by the retriever."""

    text_slots: tuple[tuple[str, int | None], ...]
    """``(slot_type, max_chars)`` in slot-binding order."""

    visual_widths: tuple[float, ...]
    """Figure slot widths as a fraction of slide width, widest first."""

    required_visual_slots: int
    """Figure slots that are not optional."""

    image_capacity: int
    table_capacity: int
    chart_capacity: int
    process_capacity: int


class Category(NamedTuple):
    """One of RPA's 40 layout categories."""

    name_zh: str
    family: str
    roles: tuple[str, ...]
    layouts: tuple[Layout, ...]


#: Minimum display width (fraction of slide width) per visual_type, mirroring
#: RPA's VISUAL_TYPE_RULES. A multi-panel figure needs more room than a photo.
VISUAL_TYPE_MIN_WIDTH: dict[str, float] = {
    "photo": 0.25,
    "schematic": 0.36,
    "simple_plot": 0.36,
    "dense_plot": 0.5,
    "multi_panel_figure": 0.55,
    "composite_figure_region": 0.42,
    "table_screenshot": 0.55,
    "microscopy": 0.36,
    "visual_evidence": 0.34,
}

#: content_role values RPA's content model recognises.
CONTENT_ROLES: tuple[str, ...] = (
    "primary_claim",
    "primary_evidence",
    "supporting_evidence",
    "caption",
    "context",
    "optional_visual",
)

CATEGORIES: dict[str, Category] = {
    'ablation': Category(
        name_zh='消融实验',
        family='data',
        roles=('body_text', 'data_visual', 'headline', 'primary_visual', 'table', 'takeaway'),
        layouts=(
            Layout(26, 280, (('text', 52), ('callout', 27)), (), 0, 0, 1, 1, 0),
            Layout(26, 280, (('text', 52), ('callout', 27)), (), 0, 0, 1, 1, 0),
            Layout(26, 280, (('text', 52), ('callout', 38)), (), 0, 0, 1, 1, 0),
            Layout(26, 280, (('text', 68), ('callout', 36)), (), 0, 0, 1, 1, 0),
            Layout(26, 280, (('text', 182), ('callout', 57)), (), 0, 0, 1, 1, 0),
            Layout(26, 280, (('callout', 82), ('text', 22)), (), 0, 0, 1, 1, 0),
            Layout(26, 280, (('text', 30), ('callout', 12)), (), 0, 0, 1, 1, 0),
            Layout(26, 280, (('callout', 12), ('text', 17)), (), 0, 0, 1, 1, 0),
        ),
    ),
    'agenda': Category(
        name_zh='议程 / 导航',
        family='linear',
        roles=('body_text', 'headline', 'process', 'timeline'),
        layouts=(
            Layout(26, 170, (), (), 0, 0, 0, 0, 4),
            Layout(26, 170, (), (), 0, 0, 0, 0, 4),
            Layout(26, 170, (), (), 0, 0, 0, 0, 4),
            Layout(26, 170, (), (), 0, 0, 0, 0, 4),
            Layout(26, 170, (), (), 0, 0, 0, 0, 4),
            Layout(26, 167, (), (), 0, 0, 0, 0, 4),
            Layout(26, 170, (), (), 0, 0, 0, 0, 4),
            Layout(26, 170, (('text', 416),), (), 0, 0, 0, 0, 4),
        ),
    ),
    'algorithm': Category(
        name_zh='算法 / 伪代码',
        family='code_eq',
        roles=('body_text', 'code', 'headline', 'metric', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 300, (('text', 34), ('callout', 26)), (0.295,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 32), ('callout', 24)), (0.275,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 84), ('callout', 27)), (0.208,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 42), ('callout', 12)), (0.12,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 175), ('callout', 19)), (0.42,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 175), ('callout', 19)), (0.42,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 24), ('callout', 9)), (0.209,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 95), ('callout', 10)), (0.89,), 1, 1, 0, 0, 0),
        ),
    ),
    'appendix': Category(
        name_zh='附录 / 备份',
        family='table',
        roles=('body_text', 'headline', 'metadata', 'reference'),
        layouts=(
            Layout(26, 520, (('text', 312), ('text', 52), ('reference', None), ('meta', 16)), (), 0, 0, 0, 0, 0),
            Layout(26, 520, (('text', 312), ('text', 52), ('reference', None), ('meta', 16)), (), 0, 0, 0, 0, 0),
            Layout(26, 520, (('text', 208), ('text', 208), ('text', 34), ('reference', None), ('meta', 20)), (), 0, 0, 0, 0, 0),
            Layout(26, 520, (('text', 440), ('text', 68), ('reference', None), ('meta', 20)), (), 0, 0, 0, 0, 0),
            Layout(26, 520, (('text', 182), ('text', 182), ('reference', None), ('meta', 31)), (), 0, 0, 0, 0, 0),
            Layout(26, 520, (('text', 440), ('text', 22), ('reference', None), ('meta', 14)), (), 0, 0, 0, 0, 0),
            Layout(26, 520, (('text', 296), ('text', 30), ('reference', None), ('meta', 7)), (), 0, 0, 0, 0, 0),
            Layout(26, 520, (('text', 440), ('text', 17), ('reference', None), ('meta', 20)), (), 0, 0, 0, 0, 0),
        ),
    ),
    'architecture': Category(
        name_zh='模型 / 系统架构',
        family='diagram',
        roles=('body_text', 'headline', 'primary_visual', 'process', 'secondary_visual', 'takeaway'),
        layouts=(
            Layout(26, 128, (('callout', 21),), (0.17, 0.108), 2, 2, 0, 0, 3),
            Layout(26, 190, (('callout', 36),), (0.283, 0.283), 2, 2, 0, 0, 3),
            Layout(26, 119, (('callout', 18),), (0.32, 0.22), 2, 2, 0, 0, 3),
            Layout(26, 175, (('callout', 21),), (0.76, 0.52), 2, 2, 0, 0, 3),
            Layout(26, 190, (('callout', 31), ('text', 56)), (0.68, 0.68), 2, 2, 0, 0, 3),
            Layout(26, 80, (('callout', 10),), (0.89, 0.133, 0.133), 3, 3, 0, 0, 3),
            Layout(26, 132, (('callout', 15),), (0.133, 0.133), 2, 2, 0, 0, 3),
            Layout(26, 173, (('callout', 29),), (0.64, 0.64), 2, 2, 0, 0, 3),
        ),
    ),
    'background': Category(
        name_zh='背景 / 问题定义',
        family='two_col',
        roles=('body_text', 'headline', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 391, (('text', 208), ('callout', 57), ('callout', 38)), (0.43,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 272), ('callout', 39), ('callout', 50)), (0.305,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 272), ('callout', 39), ('callout', 50)), (0.31,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 385), ('callout', 57), ('callout', 41)), (0.43,), 1, 1, 0, 0, 0),
            Layout(26, 369, (('text', 128), ('callout', 81), ('callout', 36)), (0.285,), 1, 1, 0, 0, 0),
            Layout(26, 369, (('text', 128), ('callout', 81), ('callout', 36)), (0.285,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 200), ('callout', 60), ('callout', 40)), (0.445,), 1, 1, 0, 0, 0),
            Layout(26, 357, (('text', 275), ('callout', 36), ('callout', 36)), (0.28,), 1, 1, 0, 0, 0),
        ),
    ),
    'baseline': Category(
        name_zh='基线对比',
        family='data',
        roles=('data_visual', 'headline', 'primary_visual', 'table', 'takeaway'),
        layouts=(
            Layout(26, 97, (('callout', 27), ('callout', 27)), (), 0, 0, 1, 1, 0),
            Layout(26, 97, (('callout', 27), ('callout', 27)), (), 0, 0, 1, 1, 0),
            Layout(26, 230, (('callout', 38), ('callout', 38)), (), 0, 0, 1, 1, 0),
            Layout(26, 125, (('callout', 36), ('callout', 36)), (), 0, 0, 1, 1, 0),
            Layout(26, 230, (('callout', 57), ('callout', 57)), (), 0, 0, 1, 1, 0),
            Layout(26, 93, (('callout', 38), ('callout', 38)), (), 0, 0, 1, 1, 0),
            Layout(26, 80, (('callout', 12), ('callout', 12)), (), 0, 0, 1, 1, 0),
            Layout(26, 80, (('callout', 12), ('callout', 12)), (), 0, 0, 1, 1, 0),
        ),
    ),
    'case': Category(
        name_zh='案例研究',
        family='figure',
        roles=('body_text', 'headline', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 135, (('callout', 32), ('text', 40), ('text', 24), ('text', 32)), (0.7,), 1, 1, 0, 0, 0),
            Layout(26, 135, (('callout', 33), ('text', 40), ('text', 24), ('text', 32)), (0.71,), 1, 1, 0, 0, 0),
            Layout(26, 153, (('callout', 41), ('text', 34), ('text', 32), ('text', 32)), (0.89,), 1, 1, 0, 0, 0),
            Layout(26, 140, (('callout', 12), ('text', 55), ('text', 17), ('text', 16)), (0.89,), 1, 1, 0, 0, 0),
            Layout(26, 232, (('callout', 41), ('text', 68), ('text', 68), ('text', 68)), (0.58,), 1, 1, 0, 0, 0),
            Layout(26, 232, (('callout', 41), ('text', 68), ('text', 68), ('text', 68)), (0.58,), 1, 1, 0, 0, 0),
            Layout(26, 132, (('callout', 31), ('text', 20), ('text', 20), ('text', 42)), (0.68,), 1, 1, 0, 0, 0),
            Layout(26, 180, (('callout', 41), ('text', 20), ('text', 22), ('text', 55)), (0.89,), 1, 1, 0, 0, 0),
        ),
    ),
    'chart_compare': Category(
        name_zh='多图表对比',
        family='data',
        roles=('caption', 'data_visual', 'headline', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 80, (('caption', 32), ('callout', 18)), (), 0, 0, 0, 3, 0),
            Layout(26, 80, (('caption', 32), ('callout', 18)), (), 0, 0, 0, 3, 0),
            Layout(26, 80, (('caption', 40), ('callout', 24)), (), 0, 0, 0, 3, 0),
            Layout(26, 80, (('caption', 28), ('callout', 27)), (), 0, 0, 0, 3, 0),
            Layout(26, 150, (('caption', 62), ('callout', 4)), (), 0, 0, 0, 3, 0),
            Layout(26, 91, (('callout', 82), ('caption', 28)), (), 0, 0, 0, 3, 0),
            Layout(26, 80, (('caption', 14), ('callout', 12)), (), 0, 0, 0, 3, 0),
            Layout(26, 80, (('callout', 9), ('caption', 14)), (), 0, 0, 0, 3, 0),
        ),
    ),
    'chart_takeaway': Category(
        name_zh='图表 + 结论',
        family='data',
        roles=('body_text', 'data_visual', 'headline', 'metric', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 89, (('callout', 27), ('text', 52)), (), 0, 0, 0, 1, 0),
            Layout(26, 89, (('callout', 27), ('text', 52)), (), 0, 0, 0, 1, 0),
            Layout(26, 80, (('callout', 24), ('text', 34)), (), 0, 0, 0, 2, 0),
            Layout(26, 114, (('callout', 36), ('text', 68)), (), 0, 0, 0, 1, 0),
            Layout(26, 180, (('callout', 57), ('text', 182)), (), 0, 0, 0, 1, 0),
            Layout(26, 83, (('callout', 38), ('text', 22)), (), 0, 0, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 30)), (), 0, 0, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 17)), (), 0, 0, 0, 1, 0),
        ),
    ),
    'cover': Category(
        name_zh='封面 / 标题页',
        family='cover',
        roles=('headline', 'metadata', 'primary_visual', 'subtitle'),
        layouts=(
            Layout(10, 76, (('subtitle', 19), ('meta', 31)), (0.32,), 1, 1, 0, 0, 0),
            Layout(16, 83, (('subtitle', 29), ('meta', 37)), (0.8,), 1, 1, 0, 0, 0),
            Layout(12, 57, (('subtitle', 23), ('meta', 31)), (0.92,), 1, 1, 0, 0, 0),
            Layout(17, 75, (('subtitle', 27), ('meta', 37)), (0.86,), 1, 1, 0, 0, 0),
            Layout(10, 75, (('subtitle', 23), ('meta', 33)), (0.28,), 1, 1, 0, 0, 0),
            Layout(17, 56, (('subtitle', 28), ('meta', 14)), (0.92,), 1, 1, 0, 0, 0),
            Layout(11, 58, (('subtitle', 22), ('meta', 23)), (0.48,), 1, 1, 0, 0, 0),
            Layout(14, 76, (('subtitle', 28), ('meta', 37)), (0.86,), 1, 1, 0, 0, 0),
        ),
    ),
    'dataset': Category(
        name_zh='数据集 / 样本',
        family='multi_panel',
        roles=('body_text', 'data_visual', 'headline', 'primary_visual', 'secondary_visual'),
        layouts=(
            Layout(26, 80, (('text', 52),), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 1, 0),
            Layout(26, 80, (('text', 52),), (0.285, 0.285, 0.285, 0.285), 4, 4, 0, 1, 0),
            Layout(26, 80, (('text', 52),), (0.436, 0.436, 0.436, 0.436), 4, 4, 0, 1, 0),
            Layout(26, 80, (('text', 52),), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 1, 0),
            Layout(26, 80, (('text', 52),), (0.89, 0.89, 0.89, 0.89), 4, 4, 0, 1, 0),
            Layout(26, 80, (('text', 52),), (0.5, 0.36, 0.36, 0.36), 4, 4, 0, 1, 0),
            Layout(26, 80, (('text', 52),), (0.5, 0.36, 0.36, 0.36), 4, 4, 0, 1, 0),
            Layout(26, 80, (('text', 52),), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 1, 0),
        ),
    ),
    'decision': Category(
        name_zh='待决策 / 求反馈',
        family='cards',
        roles=('body_text', 'headline', 'question', 'takeaway'),
        layouts=(
            Layout(26, 280, (('question', 36), ('callout', 36), ('callout', 36), ('text', 128), ('question', 36)), (), 0, 0, 0, 0, 0),
            Layout(26, 280, (('question', 69), ('callout', 32), ('callout', 32), ('text', 63), ('question', 32)), (), 0, 0, 0, 0, 0),
            Layout(26, 280, (('question', 69), ('callout', 32), ('callout', 32), ('text', 63), ('question', 32)), (), 0, 0, 0, 0, 0),
            Layout(26, 280, (('question', 123), ('callout', 27), ('callout', 27), ('text', 84), ('question', 27)), (), 0, 0, 0, 0, 0),
            Layout(26, 212, (('question', 51), ('callout', 27), ('callout', 27), ('text', 60), ('question', 27)), (), 0, 0, 0, 0, 0),
            Layout(26, 280, (('question', 123), ('question', 27), ('callout', 27), ('callout', 27), ('text', 96)), (), 0, 0, 0, 0, 0),
            Layout(26, 280, (('question', 33), ('callout', 33), ('callout', 33), ('text', 88), ('question', 33), ('text', 48)), (), 0, 0, 0, 0, 0),
            Layout(26, 280, (('question', 51), ('callout', 66), ('question', 51), ('callout', 66), ('text', 184)), (), 0, 0, 0, 0, 0),
        ),
    ),
    'discussion': Category(
        name_zh='讨论 / 解释',
        family='cards',
        roles=('body_text', 'headline', 'question', 'takeaway'),
        layouts=(
            Layout(26, 312, (('callout', 36), ('callout', 36), ('callout', 36), ('text', 128), ('question', 36)), (), 0, 0, 0, 0, 0),
            Layout(26, 297, (('callout', 69), ('callout', 32), ('callout', 32), ('text', 63), ('question', 32)), (), 0, 0, 0, 0, 0),
            Layout(26, 297, (('callout', 69), ('callout', 32), ('callout', 32), ('text', 63), ('question', 32)), (), 0, 0, 0, 0, 0),
            Layout(26, 300, (('callout', 123), ('callout', 27), ('callout', 27), ('text', 84), ('question', 27)), (), 0, 0, 0, 0, 0),
            Layout(26, 209, (('callout', 51), ('callout', 27), ('callout', 27), ('text', 60), ('question', 27)), (), 0, 0, 0, 0, 0),
            Layout(26, 313, (('question', 123), ('callout', 27), ('callout', 27), ('callout', 27), ('text', 96)), (), 0, 0, 0, 0, 0),
            Layout(26, 340, (('callout', 33), ('callout', 33), ('callout', 33), ('text', 88), ('question', 33), ('text', 48)), (), 0, 0, 0, 0, 0),
            Layout(26, 340, (('callout', 51), ('callout', 66), ('question', 51), ('callout', 66), ('text', 184)), (), 0, 0, 0, 0, 0),
        ),
    ),
    'dual_figure': Category(
        name_zh='双图对照',
        family='multi_panel',
        roles=('body_text', 'caption', 'headline', 'primary_visual', 'secondary_visual'),
        layouts=(
            Layout(26, 100, (('text', 34), ('caption', 20), ('caption', 20)), (0.436, 0.436), 2, 2, 0, 0, 0),
            Layout(26, 100, (('text', 34), ('caption', 20), ('caption', 20)), (0.436, 0.436), 2, 2, 0, 0, 0),
            Layout(26, 100, (('text', 34), ('caption', 20), ('caption', 20)), (0.436, 0.436), 2, 2, 0, 0, 0),
            Layout(26, 100, (('text', 34), ('caption', 20), ('caption', 20)), (0.436, 0.436), 2, 2, 0, 0, 0),
            Layout(26, 100, (('text', 34), ('caption', 20), ('caption', 20)), (0.89, 0.89), 2, 2, 0, 0, 0),
            Layout(26, 100, (('text', 34), ('caption', 20), ('caption', 20)), (0.5, 0.36), 2, 2, 0, 0, 0),
            Layout(26, 100, (('text', 34), ('caption', 20), ('caption', 20)), (0.5, 0.36), 2, 2, 0, 0, 0),
            Layout(26, 100, (('text', 34), ('caption', 20), ('caption', 20)), (0.436, 0.436), 2, 2, 0, 0, 0),
        ),
    ),
    'error': Category(
        name_zh='误差 / 错误分析',
        family='multi_panel',
        roles=('body_text', 'data_visual', 'headline', 'primary_visual', 'secondary_visual', 'takeaway'),
        layouts=(
            Layout(26, 80, (('callout', 12), ('text', 34)), (0.285, 0.285, 0.285), 3, 3, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 34)), (0.285, 0.285, 0.285), 3, 3, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 34)), (0.436, 0.436, 0.436), 3, 3, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 34)), (0.285, 0.285, 0.285), 3, 3, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 34)), (0.89, 0.89, 0.89), 3, 3, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 34)), (0.5, 0.36, 0.36), 3, 3, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 34)), (0.5, 0.36, 0.36), 3, 3, 0, 1, 0),
            Layout(26, 80, (('callout', 12), ('text', 34)), (0.285, 0.285, 0.285), 3, 3, 0, 1, 0),
        ),
    ),
    'experiment': Category(
        name_zh='实验设置',
        family='two_col',
        roles=('body_text', 'data_visual', 'headline', 'primary_visual', 'secondary_visual', 'table'),
        layouts=(
            Layout(26, 250, (('text', 208), ('text', 11)), (0.43,), 1, 1, 1, 1, 0),
            Layout(26, 250, (('text', 126), ('text', 11)), (0.56,), 1, 1, 1, 1, 0),
            Layout(26, 250, (('text', 126), ('text', 11)), (0.555,), 1, 1, 1, 1, 0),
            Layout(26, 250, (('text', 182), ('text', 11)), (0.89,), 1, 1, 1, 1, 0),
            Layout(26, 250, (('text', 288), ('text', 11)), (0.27,), 1, 1, 1, 1, 0),
            Layout(26, 250, (('text', 288), ('text', 11)), (0.27,), 1, 1, 1, 1, 0),
            Layout(26, 250, (('text', 108), ('text', 11)), (0.42,), 1, 1, 1, 1, 0),
            Layout(26, 250, (('text', 128), ('text', 11)), (0.89,), 1, 1, 1, 1, 0),
        ),
    ),
    'failure': Category(
        name_zh='失败实验 / 负结果',
        family='two_col',
        roles=('body_text', 'headline', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 420, (('text', 208), ('text', 52), ('text', 52), ('callout', 8)), (0.43,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 272), ('text', 126), ('text', 68), ('callout', 8)), (0.305,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 272), ('text', 126), ('text', 68), ('callout', 8)), (0.31,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 385), ('text', 182), ('text', 110), ('callout', 8)), (0.43,), 1, 1, 0, 0, 0),
            Layout(26, 399, (('text', 128), ('text', 85), ('text', 85), ('callout', 8)), (0.595,), 1, 1, 0, 0, 0),
            Layout(26, 399, (('text', 128), ('text', 85), ('text', 85), ('callout', 8)), (0.595,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 200), ('text', 108), ('text', 81), ('callout', 8)), (0.445,), 1, 1, 0, 0, 0),
            Layout(26, 420, (('text', 275), ('text', 128), ('text', 128), ('callout', 8)), (0.28,), 1, 1, 0, 0, 0),
        ),
    ),
    'figure_text': Category(
        name_zh='图 + 解释',
        family='figure',
        roles=('body_text', 'headline', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 90, (('callout', 18), ('text', 40), ('text', 24)), (0.7,), 1, 1, 0, 0, 0),
            Layout(26, 90, (('callout', 18), ('text', 40), ('text', 24)), (0.71,), 1, 1, 0, 0, 0),
            Layout(26, 105, (('callout', 12), ('text', 34), ('text', 32)), (0.89,), 1, 1, 0, 0, 0),
            Layout(26, 118, (('callout', 12), ('text', 55), ('text', 17)), (0.89,), 1, 1, 0, 0, 0),
            Layout(26, 166, (('callout', 36), ('text', 68), ('text', 68)), (0.58,), 1, 1, 0, 0, 0),
            Layout(26, 166, (('callout', 36), ('text', 68), ('text', 68)), (0.58,), 1, 1, 0, 0, 0),
            Layout(26, 102, (('callout', 9), ('text', 20), ('text', 42)), (0.68,), 1, 1, 0, 0, 0),
            Layout(26, 143, (('callout', 8), ('text', 20), ('text', 55)), (0.89,), 1, 1, 0, 0, 0),
        ),
    ),
    'four_panel': Category(
        name_zh='四宫格结果',
        family='multi_panel',
        roles=('headline', 'primary_visual', 'secondary_visual', 'takeaway'),
        layouts=(
            Layout(26, 50, (('callout', 41),), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.285, 0.285, 0.285, 0.285), 4, 4, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.436, 0.436, 0.436, 0.436), 4, 4, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.89, 0.89, 0.89, 0.89), 4, 4, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.5, 0.36, 0.36, 0.36), 4, 4, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.5, 0.36, 0.36, 0.36), 4, 4, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 0, 0),
        ),
    ),
    'gap': Category(
        name_zh='研究缺口 / 贡献',
        family='two_col',
        roles=('body_text', 'headline', 'takeaway'),
        layouts=(
            Layout(26, 420, (('text', 208), ('callout', 57), ('callout', 38), ('text', 52)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('text', 272), ('callout', 39), ('callout', 39), ('text', 68)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('text', 272), ('callout', 39), ('callout', 39), ('text', 68)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('text', 385), ('callout', 57), ('callout', 57), ('text', 110)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('text', 128), ('callout', 81), ('callout', 36), ('text', 85)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('text', 128), ('callout', 81), ('callout', 36), ('text', 85)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('text', 200), ('callout', 60), ('callout', 60), ('text', 81)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('text', 275), ('callout', 36), ('callout', 36), ('text', 128)), (), 0, 0, 0, 0, 0),
        ),
    ),
    'limitations': Category(
        name_zh='局限性',
        family='cards',
        roles=('body_text', 'headline', 'takeaway'),
        layouts=(
            Layout(26, 309, (('callout', 36), ('callout', 36), ('callout', 36), ('text', 128), ('callout', 36)), (), 0, 0, 0, 0, 0),
            Layout(26, 296, (('callout', 69), ('callout', 32), ('callout', 32), ('text', 63), ('callout', 32)), (), 0, 0, 0, 0, 0),
            Layout(26, 296, (('callout', 69), ('callout', 32), ('callout', 32), ('text', 63), ('callout', 32)), (), 0, 0, 0, 0, 0),
            Layout(26, 298, (('callout', 123), ('callout', 27), ('callout', 27), ('text', 84), ('callout', 27)), (), 0, 0, 0, 0, 0),
            Layout(26, 207, (('callout', 51), ('callout', 27), ('callout', 27), ('text', 60), ('callout', 27)), (), 0, 0, 0, 0, 0),
            Layout(26, 308, (('callout', 123), ('callout', 27), ('callout', 27), ('callout', 27), ('text', 96)), (), 0, 0, 0, 0, 0),
            Layout(26, 330, (('callout', 33), ('callout', 33), ('callout', 33), ('text', 88), ('callout', 33), ('text', 48)), (), 0, 0, 0, 0, 0),
            Layout(26, 330, (('callout', 51), ('callout', 66), ('callout', 51), ('callout', 66), ('text', 184)), (), 0, 0, 0, 0, 0),
        ),
    ),
    'literature': Category(
        name_zh='文献综述',
        family='cards',
        roles=('body_text', 'headline', 'reference', 'takeaway'),
        layouts=(
            Layout(26, 430, (('reference', None), ('reference', None), ('reference', None), ('callout', 57)), (), 0, 0, 0, 0, 0),
            Layout(26, 430, (('reference', None), ('reference', None), ('reference', None), ('callout', 48)), (), 0, 0, 0, 0, 0),
            Layout(26, 430, (('reference', None), ('reference', None), ('reference', None), ('callout', 48)), (), 0, 0, 0, 0, 0),
            Layout(26, 430, (('reference', None), ('reference', None), ('reference', None), ('callout', 36)), (), 0, 0, 0, 0, 0),
            Layout(26, 430, (('reference', None), ('reference', None), ('reference', None), ('callout', 27)), (), 0, 0, 0, 0, 0),
            Layout(26, 430, (('callout', 123), ('reference', None), ('reference', None), ('reference', None)), (), 0, 0, 0, 0, 0),
            Layout(26, 430, (('reference', None), ('reference', None), ('reference', None), ('callout', 66), ('text', 48)), (), 0, 0, 0, 0, 0),
            Layout(26, 430, (('reference', None), ('reference', None), ('reference', None), ('callout', 51)), (), 0, 0, 0, 0, 0),
        ),
    ),
    'method_overview': Category(
        name_zh='方法总览',
        family='process',
        roles=('body_text', 'headline', 'primary_visual', 'process', 'secondary_visual', 'takeaway'),
        layouts=(
            Layout(26, 132, (('callout', 15),), (0.133, 0.133), 2, 2, 0, 0, 3),
            Layout(26, 173, (('callout', 29),), (0.64, 0.64), 2, 2, 0, 0, 3),
            Layout(26, 128, (('callout', 21),), (0.17, 0.108), 2, 2, 0, 0, 3),
            Layout(26, 180, (('callout', 36),), (0.283, 0.283), 2, 2, 0, 0, 3),
            Layout(26, 119, (('callout', 18),), (0.32, 0.22), 2, 2, 0, 0, 3),
            Layout(26, 175, (('callout', 21),), (0.76, 0.52), 2, 2, 0, 0, 3),
            Layout(26, 180, (('callout', 31), ('text', 56)), (0.68, 0.68), 2, 2, 0, 0, 3),
            Layout(26, 80, (('callout', 10),), (0.89, 0.133, 0.133), 3, 3, 0, 0, 3),
        ),
    ),
    'metrics': Category(
        name_zh='多指标看板',
        family='cards',
        roles=('body_text', 'data_visual', 'headline', 'metric', 'primary_visual'),
        layouts=(
            Layout(26, 260, (('text', 128),), (), 0, 0, 0, 1, 0),
            Layout(26, 207, (('text', 42),), (), 0, 0, 0, 1, 0),
            Layout(26, 207, (('text', 42),), (), 0, 0, 0, 1, 0),
            Layout(26, 208, (('text', 63),), (), 0, 0, 0, 1, 0),
            Layout(26, 175, (('text', 69),), (), 0, 0, 0, 1, 0),
            Layout(26, 320, (('text', 220),), (), 0, 0, 0, 1, 0),
            Layout(26, 286, (('text', 88), ('text', 48)), (), 0, 0, 0, 1, 0),
            Layout(26, 185, (), (), 0, 0, 0, 1, 0),
        ),
    ),
    'next_steps': Category(
        name_zh='下一步计划',
        family='cards',
        roles=('body_text', 'headline', 'metric', 'process', 'takeaway'),
        layouts=(
            Layout(26, 288, (('callout', 36),), (), 0, 0, 0, 0, 3),
            Layout(26, 351, (('callout', 32),), (), 0, 0, 0, 0, 3),
            Layout(26, 351, (('callout', 32),), (), 0, 0, 0, 0, 3),
            Layout(26, 337, (('callout', 27),), (), 0, 0, 0, 0, 3),
            Layout(26, 216, (('callout', 27),), (), 0, 0, 0, 0, 3),
            Layout(26, 290, (('callout', 123),), (), 0, 0, 0, 0, 3),
            Layout(26, 353, (('callout', 33), ('text', 48)), (), 0, 0, 0, 0, 3),
            Layout(26, 377, (('callout', 51),), (), 0, 0, 0, 0, 3),
        ),
    ),
    'qa': Category(
        name_zh='Q&A / 讨论页',
        family='summary',
        roles=('body_text', 'headline', 'metadata', 'primary_visual', 'question', 'secondary_visual'),
        layouts=(
            Layout(26, 349, (('question', 36), ('text', 128), ('meta', 20)), (0.43,), 1, 1, 0, 0, 0),
            Layout(26, 366, (('question', 123), ('text', 128), ('meta', 20)), (0.283,), 1, 1, 0, 0, 0),
            Layout(26, 371, (('question', 54), ('text', 108), ('meta', 33)), (0.455,), 1, 1, 0, 0, 0),
            Layout(26, 371, (('question', 54), ('text', 108), ('meta', 33)), (0.455,), 1, 1, 0, 0, 0),
            Layout(26, 210, (('question', 51), ('text', 60), ('meta', 15)), (0.22,), 1, 1, 0, 0, 0),
            Layout(26, 355, (('question', 70), ('text', 141), ('meta', 57)), (0.76,), 1, 1, 0, 0, 0),
            Layout(26, 161, (('question', 30), ('text', 63), ('meta', 25)), (0.52, 0.35), 1, 2, 0, 0, 0),
            Layout(26, 420, (('text', 220), ('question', 27), ('text', 96), ('meta', 14)), (0.208,), 1, 1, 0, 0, 0),
        ),
    ),
    'qualitative': Category(
        name_zh='定性结果',
        family='multi_panel',
        roles=('caption', 'headline', 'primary_visual', 'secondary_visual', 'takeaway'),
        layouts=(
            Layout(26, 80, (('callout', 19), ('caption', 32)), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 0, 0),
            Layout(26, 80, (('callout', 19), ('caption', 32)), (0.285, 0.285, 0.285, 0.285), 4, 4, 0, 0, 0),
            Layout(26, 80, (('callout', 19), ('caption', 32)), (0.436, 0.436, 0.436, 0.436), 4, 4, 0, 0, 0),
            Layout(26, 80, (('callout', 19), ('caption', 32)), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 0, 0),
            Layout(26, 80, (('callout', 19), ('caption', 32)), (0.89, 0.89, 0.89, 0.89), 4, 4, 0, 0, 0),
            Layout(26, 80, (('callout', 19), ('caption', 32)), (0.5, 0.36, 0.36, 0.36), 4, 4, 0, 0, 0),
            Layout(26, 80, (('callout', 19), ('caption', 32)), (0.5, 0.36, 0.36, 0.36), 4, 4, 0, 0, 0),
            Layout(26, 80, (('callout', 19), ('caption', 32)), (0.209, 0.209, 0.209, 0.209), 4, 4, 0, 0, 0),
        ),
    ),
    'question': Category(
        name_zh='研究问题 / 假设',
        family='cards',
        roles=('body_text', 'headline', 'question', 'takeaway'),
        layouts=(
            Layout(26, 420, (('question', 57), ('callout', 57), ('text', 208), ('text', 208)), (), 0, 0, 0, 0, 0),
            Layout(26, 384, (('question', 69), ('callout', 48), ('text', 84), ('text', 84)), (), 0, 0, 0, 0, 0),
            Layout(26, 384, (('question', 69), ('callout', 48), ('text', 84), ('text', 84)), (), 0, 0, 0, 0, 0),
            Layout(26, 398, (('question', 123), ('callout', 36), ('text', 112), ('text', 112)), (), 0, 0, 0, 0, 0),
            Layout(26, 230, (('question', 51), ('callout', 27), ('text', 60), ('text', 60)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('text', 220), ('question', 36), ('callout', 36), ('text', 128)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('question', 66), ('callout', 66), ('text', 132), ('text', 132), ('text', 48)), (), 0, 0, 0, 0, 0),
            Layout(26, 420, (('question', 51), ('callout', 66), ('text', 240), ('text', 184)), (), 0, 0, 0, 0, 0),
        ),
    ),
    'references': Category(
        name_zh='参考文献',
        family='table',
        roles=('body_text', 'headline', 'primary_visual', 'reference', 'takeaway'),
        layouts=(
            Layout(26, 520, (('reference', None), ('callout', 27), ('text', 52)), (0.225,), 1, 1, 0, 0, 0),
            Layout(26, 520, (('reference', None), ('callout', 27), ('text', 52)), (0.225,), 1, 1, 0, 0, 0),
            Layout(26, 520, (('reference', None), ('reference', None), ('callout', 24), ('text', 34)), (0.285,), 1, 1, 0, 0, 0),
            Layout(26, 520, (('reference', None), ('callout', 36), ('text', 68)), (0.285,), 1, 1, 0, 0, 0),
            Layout(26, 520, (('reference', None), ('callout', 57), ('text', 182)), (0.43,), 1, 1, 0, 0, 0),
            Layout(26, 520, (('reference', None), ('callout', 82), ('text', 22)), (0.2,), 0, 1, 0, 0, 0),
            Layout(26, 520, (('reference', None), ('callout', 12), ('text', 30)), (0.12,), 1, 1, 0, 0, 0),
            Layout(26, 520, (('reference', None), ('callout', 12), ('text', 17)), (0.285,), 1, 1, 0, 0, 0),
        ),
    ),
    'section': Category(
        name_zh='章节过渡',
        family='section',
        roles=('headline', 'metric', 'primary_visual', 'subtitle'),
        layouts=(
            Layout(19, 50, (('subtitle', 27),), (0.34,), 1, 1, 0, 0, 0),
            Layout(20, 48, (('subtitle', 25),), (0.92,), 1, 1, 0, 0, 0),
            Layout(23, 60, (('subtitle', 33),), (0.2,), 1, 1, 0, 0, 0),
            Layout(24, 58, (('subtitle', 32),), (0.59,), 1, 1, 0, 0, 0),
            Layout(13, 37, (('subtitle', 19),), (0.33,), 1, 1, 0, 0, 0),
            Layout(24, 55, (('subtitle', 33),), (0.84,), 1, 1, 0, 0, 0),
            Layout(11, 39, (('subtitle', 17),), (0.42,), 1, 1, 0, 0, 0),
            Layout(19, 48, (('subtitle', 25),), (0.28,), 1, 1, 0, 0, 0),
        ),
    ),
    'single_figure': Category(
        name_zh='单图结果',
        family='figure',
        roles=('caption', 'headline', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 67, (('callout', 12), ('callout', 18), ('caption', 20)), (0.7,), 1, 1, 0, 0, 0),
            Layout(26, 67, (('callout', 12), ('callout', 18), ('caption', 20)), (0.71,), 1, 1, 0, 0, 0),
            Layout(26, 74, (('callout', 12), ('callout', 12), ('caption', 42)), (0.89,), 1, 1, 0, 0, 0),
            Layout(26, 98, (('callout', 13), ('callout', 12), ('caption', 67)), (0.89,), 1, 1, 0, 0, 0),
            Layout(26, 119, (('callout', 36), ('callout', 36), ('caption', 40)), (0.58,), 1, 1, 0, 0, 0),
            Layout(26, 119, (('callout', 36), ('callout', 36), ('caption', 40)), (0.58,), 1, 1, 0, 0, 0),
            Layout(26, 83, (('callout', 9), ('callout', 9), ('caption', 51)), (0.68,), 1, 1, 0, 0, 0),
            Layout(26, 119, (('callout', 7), ('callout', 8), ('caption', 134)), (0.89,), 1, 1, 0, 0, 0),
        ),
    ),
    'summary': Category(
        name_zh='总结 / Takeaways',
        family='summary',
        roles=('body_text', 'headline', 'primary_visual', 'secondary_visual', 'takeaway'),
        layouts=(
            Layout(26, 192, (('callout', 36), ('callout', 36), ('callout', 36), ('callout', 38)), (0.43,), 1, 1, 0, 0, 0),
            Layout(26, 203, (('callout', 123), ('callout', 27), ('callout', 27), ('callout', 27)), (0.208,), 1, 1, 0, 0, 0),
            Layout(26, 217, (('callout', 54), ('callout', 40), ('callout', 40), ('callout', 40)), (0.455,), 1, 1, 0, 0, 0),
            Layout(26, 217, (('callout', 54), ('callout', 40), ('callout', 40), ('callout', 40)), (0.455,), 1, 1, 0, 0, 0),
            Layout(26, 140, (('callout', 51), ('callout', 27), ('callout', 27), ('callout', 27)), (0.22,), 1, 1, 0, 0, 0),
            Layout(26, 166, (('callout', 35), ('callout', 35), ('callout', 35), ('callout', 35)), (0.76,), 1, 1, 0, 0, 0),
            Layout(26, 80, (('callout', 15), ('callout', 15), ('callout', 15), ('callout', 15)), (0.52, 0.35), 1, 2, 0, 0, 0),
            Layout(26, 240, (('text', 220), ('callout', 18), ('callout', 18), ('callout', 18), ('callout', 18)), (0.162,), 1, 1, 0, 0, 0),
        ),
    ),
    'table': Category(
        name_zh='表格结果',
        family='table',
        roles=('body_text', 'headline', 'table', 'takeaway'),
        layouts=(
            Layout(26, 360, (('callout', 27), ('callout', 27), ('text', 52)), (), 0, 0, 1, 0, 0),
            Layout(26, 360, (('callout', 27), ('callout', 27), ('text', 52)), (), 0, 0, 1, 0, 0),
            Layout(26, 360, (('callout', 24), ('callout', 24), ('text', 34)), (), 0, 0, 2, 0, 0),
            Layout(26, 360, (('callout', 36), ('callout', 36), ('text', 68)), (), 0, 0, 1, 0, 0),
            Layout(26, 360, (('callout', 57), ('callout', 57), ('text', 182)), (), 0, 0, 1, 0, 0),
            Layout(26, 360, (('callout', 38), ('callout', 38), ('text', 22)), (), 0, 0, 1, 0, 0),
            Layout(26, 360, (('callout', 12), ('callout', 12), ('text', 30)), (), 0, 0, 1, 0, 0),
            Layout(26, 360, (('callout', 12), ('callout', 12), ('text', 17)), (), 0, 0, 1, 0, 0),
        ),
    ),
    'table_chart': Category(
        name_zh='表 + 图',
        family='data',
        roles=('body_text', 'data_visual', 'headline', 'primary_visual', 'table', 'takeaway'),
        layouts=(
            Layout(26, 300, (('callout', 27), ('text', 52)), (), 0, 0, 1, 1, 0),
            Layout(26, 300, (('callout', 27), ('text', 52)), (), 0, 0, 1, 1, 0),
            Layout(26, 300, (('callout', 38), ('text', 52)), (), 0, 0, 1, 1, 0),
            Layout(26, 300, (('callout', 36), ('text', 68)), (), 0, 0, 1, 1, 0),
            Layout(26, 300, (('callout', 57), ('text', 182)), (), 0, 0, 1, 1, 0),
            Layout(26, 300, (('callout', 82), ('text', 22)), (), 0, 0, 1, 1, 0),
            Layout(26, 300, (('callout', 12), ('text', 30)), (), 0, 0, 1, 1, 0),
            Layout(26, 300, (('callout', 12), ('text', 17)), (), 0, 0, 1, 1, 0),
        ),
    ),
    'theory': Category(
        name_zh='理论 / 公式',
        family='code_eq',
        roles=('body_text', 'equation', 'headline', 'primary_visual', 'takeaway'),
        layouts=(
            Layout(26, 260, (('text', 34), ('text', 34), ('callout', 26)), (0.295,), 1, 1, 0, 0, 0),
            Layout(26, 260, (('text', 32), ('text', 32), ('callout', 24)), (0.275,), 1, 1, 0, 0, 0),
            Layout(26, 260, (('text', 84), ('text', 84), ('callout', 27)), (0.208,), 1, 1, 0, 0, 0),
            Layout(26, 251, (('text', 42), ('text', 42), ('callout', 12)), (0.12,), 1, 1, 0, 0, 0),
            Layout(26, 260, (('text', 175), ('text', 25), ('callout', 19)), (0.42,), 1, 1, 0, 0, 0),
            Layout(26, 260, (('text', 175), ('text', 25), ('callout', 19)), (0.42,), 1, 1, 0, 0, 0),
            Layout(26, 260, (('text', 24), ('text', 24), ('callout', 9)), (0.209,), 1, 1, 0, 0, 0),
            Layout(26, 260, (('text', 95), ('text', 95), ('callout', 10)), (0.89,), 1, 1, 0, 0, 0),
        ),
    ),
    'timeline': Category(
        name_zh='时间线 / 里程碑',
        family='linear',
        roles=('body_text', 'headline', 'timeline'),
        layouts=(
            Layout(26, 177, (), (), 0, 0, 0, 0, 0),
            Layout(26, 180, (), (), 0, 0, 0, 0, 0),
            Layout(26, 180, (), (), 0, 0, 0, 0, 0),
            Layout(26, 180, (), (), 0, 0, 0, 0, 0),
            Layout(26, 180, (), (), 0, 0, 0, 0, 0),
            Layout(26, 150, (), (), 0, 0, 0, 0, 0),
            Layout(26, 180, (), (), 0, 0, 0, 0, 0),
            Layout(26, 180, (('text', 416),), (), 0, 0, 0, 0, 0),
        ),
    ),
    'triple_figure': Category(
        name_zh='三图结果',
        family='multi_panel',
        roles=('headline', 'primary_visual', 'secondary_visual', 'takeaway'),
        layouts=(
            Layout(26, 50, (('callout', 41),), (0.285, 0.285, 0.285), 3, 3, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.285, 0.285, 0.285), 3, 3, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.436, 0.436, 0.436), 3, 3, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.285, 0.285, 0.285), 3, 3, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.89, 0.89, 0.89), 3, 3, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.5, 0.36, 0.36), 3, 3, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.5, 0.36, 0.36), 3, 3, 0, 0, 0),
            Layout(26, 50, (('callout', 41),), (0.285, 0.285, 0.285), 3, 3, 0, 0, 0),
        ),
    ),
    'weekly': Category(
        name_zh='周进展看板',
        family='cards',
        roles=('body_text', 'headline', 'metric', 'primary_visual', 'question', 'takeaway'),
        layouts=(
            Layout(26, 300, (('text', 128), ('callout', 36), ('callout', 36), ('question', 36)), (0.28,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 240), ('callout', 16), ('callout', 16), ('question', 16)), (0.355,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 240), ('callout', 16), ('callout', 16), ('question', 16)), (0.355,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 385), ('callout', 18), ('callout', 18), ('question', 18)), (0.162,), 1, 1, 0, 0, 0),
            Layout(26, 274, (('text', 184), ('callout', 27), ('callout', 27), ('question', 34)), (0.22,), 1, 1, 0, 0, 0),
            Layout(26, 256, (('question', 123), ('text', 72), ('callout', 18), ('callout', 18)), (0.162,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 88), ('callout', 33), ('callout', 33), ('question', 33), ('text', 48)), (0.72,), 1, 1, 0, 0, 0),
            Layout(26, 300, (('text', 138), ('callout', 66), ('callout', 51)), (0.49,), 1, 1, 0, 0, 0),
        ),
    ),
    'workflow': Category(
        name_zh='流程 / Pipeline',
        family='process',
        roles=('body_text', 'headline', 'primary_visual', 'process'),
        layouts=(
            Layout(26, 220, (('text', 56),), (), 0, 0, 0, 0, 5),
            Layout(26, 220, (('text', 78),), (), 0, 0, 0, 0, 5),
            Layout(26, 220, (('text', 54),), (), 0, 0, 0, 0, 5),
            Layout(26, 220, (('text', 96),), (), 0, 0, 0, 0, 5),
            Layout(26, 220, (('text', 36),), (), 0, 0, 0, 0, 5),
            Layout(26, 220, (('text', 56),), (), 0, 0, 0, 0, 5),
            Layout(26, 220, (('text', 84), ('text', 56)), (), 0, 0, 0, 0, 5),
            Layout(26, 104, (('text', 21),), (0.89,), 1, 1, 0, 0, 5),
        ),
    ),
}
