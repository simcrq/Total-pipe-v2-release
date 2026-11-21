"""Prompts and the lightweight page design contract for a topic-driven deck."""
from pathlib import Path
import re

from .requests import prompt_request
from .state import read, write

SCHEMA = Path(__file__).with_name('schemas')/'topic-page-design.schema.json'
DESIGN_VERSION = 'topic-1.0'
TOPIC_EXAMPLES = (
    '设计页面前，先查看 `example_lookup.recommended` 和完整目录 `example_lookup.catalog`，'
    '并用 `example_lookup.command_prefix` 执行 `search "<讲解关系>" --limit 3` 与 `show <id>` 打开至少 1–2 份匹配示例，'
    '参考其多区构图、空间占比、图示关系与阅读顺序。避免把非封面页做成保守的单列要点或大面积留白。'
)


def check_design(value, slide_count=None):
    """Validate the handoff shape and page order without checking the subject matter."""
    if not isinstance(value, dict) or value.get('schema_version') != DESIGN_VERSION:
        raise ValueError(f'Write a topic page design with schema_version={DESIGN_VERSION}.')
    if not isinstance(value.get('deck_id'), str) or not value['deck_id'].strip():
        raise ValueError('Topic page design requires a deck_id.')
    pages = value.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 40:
        raise ValueError('Topic page design requires 1–40 pages.')
    if slide_count is not None and len(pages) != slide_count:
        raise ValueError(f'Requested {slide_count} pages; topic page design has {len(pages)}.')
    seen = set()
    for index, page in enumerate(pages, 1):
        pid = page.get('id') if isinstance(page, dict) else None
        if not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', pid) or pid in seen:
            raise ValueError(f'Page {index} requires a unique id made of letters, digits, underscores or hyphens.')
        seen.add(pid)
        design = page.get('design')
        if not ((isinstance(design, str) and design.strip()) or (isinstance(design, dict) and design)):
            raise ValueError(f'{pid}: provide a non-empty visual design or walkthrough.')
        if isinstance(design, str):
            compact = re.sub(r'\s+', '', design)
            if len(compact) < 8 or re.fullmatch(r'(?:tbd|todo|placeholder|待定|略|放文字|默认排版)[\s.。!！]*', design.strip(), re.I):
                raise ValueError(f'{pid}: DESIGN_TOO_VAGUE — design brief is too vague; describe concrete visual elements and reading order.')
        for field in ('title', 'take', 'notes'):
            if field in page and not isinstance(page[field], str):
                raise ValueError(f'{pid}: {field} must be a string.')


def prepare_design(work, request):
    from .prompts import example_lookup

    count = request.get('slide_count')
    target = f'交付 {count} 页。' if count is not None else '根据题目决定页数，最多 40 页。'
    task = f"""# 题目入口的内容策划与页面设计

完整读取 `work/page_design_prompt.json` 和其中 schema_path 指向的 Schema。
从 request.topic 出发，依照用户的语言、场合和 requirements，自行确定论点、受众需要了解的内容及讲解顺序。
language 为 auto 时，根据题目及用户要求决定语言。{target}

- 为每页写清内容、视觉关系、多区排布和讲解顺序。可写 title、take、notes，正文、图示、对照表与公式构想写进 design。
- 非封面页优先规划 2–3 个互补视觉区（目标覆盖正文带约 45%–75%），避免单列几句文字或大面积空洞留白。
- 是否查资料以及如何使用图表、公式、列表和图片，按题目及用户要求决定。页面设计只提交设计 JSON。
- {TOPIC_EXAMPLES}
- 输出 `work/page_design.json`，使用 topic-1.0 协议。后续 PageScene 可细化文案和视觉实现。
"""
    lookup = example_lookup(TOPIC_EXAMPLES)
    try:
        from deck_compiler.example_index import catalog_brief, inventory, suggest_for_text
        entries = inventory()
        query = f"{request.get('topic') or request.get('source') or ''} {request.get('requirements') or ''}"
        lookup['catalog'] = catalog_brief(entries)
        lookup['recommended'] = suggest_for_text(query, entries, limit=5)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    prompt_path, task_path = work/'page_design_prompt.json', work/'page_design_task.md'
    write(prompt_path, {
        'request': prompt_request(request),
        'schema_path': str(SCHEMA),
        'example_lookup': lookup,
        'shape': {'schema_version': DESIGN_VERSION, 'deck_id': '<string>',
                  'pages': [{'id': 'P1', 'title': '<optional title>', 'take': '<optional lead>',
                             'design': '<content, visual relationships and walkthrough>'}]},
    })
    task_path.write_text(task, encoding='utf-8')
    return [prompt_path, task_path]


def prepare_scene(work, request):
    from .page_recipes import capabilities
    from .page_scene_binding import SCHEMA as SCENE_SCHEMA, _scene_example_lookup, copy_bindings

    design = read(work/'page_design.json')
    prompt_path, task_path = work/'page_scene_prompt.json', work/'page_scene_task.md'
    write(prompt_path, {
        'request': prompt_request(request),
        'schema_path': str(SCENE_SCHEMA),
        'page_design': design,
        'copy_bindings': copy_bindings(design),
        'recipes': capabilities(),
        'example_lookup': _scene_example_lookup(design, request),
        'page_size': {'width': 13.333, 'height': 7.5, 'unit': 'inches'},
    })
    task_path.write_text("""# 题目入口的 PageScene 实现

完整读取 `work/page_scene_prompt.json` 和其中 schema_path 指向的 Schema。
按页面设计的 ID 和顺序，写出 `work/page_scene.json`。可直接填写标题、正文、标签、表格和公式，
也可选用 copy_bindings 中的引用。需要时细化文案或调整视觉实现。

- **先参考案例库再排布几何**：查看 `example_lookup.per_page_suggestions` 和 `example_lookup.catalog`，
  用 `example_lookup.command_prefix` 执行 `show <id>` 打开匹配的示例脚本，参考多区构图、图/表/公式组合与空间比例。
- 手写对象使用英寸坐标 box。非封面页正文带 `[0.72, 2.20, 11.893, 4.80]` 目标可见覆盖率 **45%–75%**，
  避免单列稀疏文本或大片空白区（`pagespec-check` 与 `scene_preview` 会检测并报告 `PAGE_SCENE_SPARSE_LAYOUT`）。
- 使用可编辑的文字、形状、表格、图表、贝塞尔路径或公式；图片使用实际文件路径。
- 仅在 `recipes` 真正匹配该页视觉复杂度时选用 recipe；若会压平多区设计或留白过大，直接手写显式对象。
- 题目页可按需要选择标题、结论和讲稿。可见信息应在页面内，保证字号和间距可读。
- 用 `scene_preview` 检查需要复核的页面（核对截断、重叠与留白覆盖率）。提交后构建可编辑候选；如需 PowerPoint 导出，按候选返回的 native 操作继续。
""", encoding='utf-8')
    return [prompt_path, task_path]
