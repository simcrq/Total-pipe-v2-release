"""Prompts and the lightweight page design contract for a topic-driven deck."""
from pathlib import Path
import re

from .requests import prompt_request
from .state import read, write

SCHEMA = Path(__file__).with_name('schemas')/'topic-page-design.schema.json'
DESIGN_VERSION = 'topic-1.0'
TOPIC_EXAMPLES = (
    '需要构思页面时，用 example_lookup.command_prefix 执行 search "<讲解关系>" --limit 2。'
    '按需打开一份匹配脚本，参考构图和阅读顺序。当前题目的内容自行组织。'
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
        for field in ('title', 'take', 'notes'):
            if field in page and not isinstance(page[field], str):
                raise ValueError(f'{pid}: {field} must be a string.')


def prepare_design(work, request):
    from .adapters import example_lookup

    count = request.get('slide_count')
    target = f'交付 {count} 页。' if count is not None else '根据题目决定页数，最多 40 页。'
    task = f"""# 题目入口的内容策划与页面设计

完整读取 `work/page_design_prompt.json` 和其中 schema_path 指向的 Schema。
从 request.topic 出发，依照用户的语言、场合和 requirements，自行确定论点、受众需要了解的内容及讲解顺序。
language 为 auto 时，根据题目及用户要求决定语言。{target}

- 为每页写清内容、视觉关系、排布和讲解顺序。可写 title、take、notes，正文与图表构想可以写进 design。
- 是否查资料以及如何使用图表、公式、列表和图片，按题目及用户要求决定。页面设计只提交设计 JSON。
- {TOPIC_EXAMPLES}
- 输出 `work/page_design.json`，使用 topic-1.0 协议。后续 PageScene 可细化文案和视觉实现。
"""
    prompt_path, task_path = work/'page_design_prompt.json', work/'page_design_task.md'
    write(prompt_path, {
        'request': prompt_request(request),
        'schema_path': str(SCHEMA),
        'example_lookup': example_lookup(TOPIC_EXAMPLES),
        'shape': {'schema_version': DESIGN_VERSION, 'deck_id': '<string>',
                  'pages': [{'id': 'P1', 'title': '<optional title>', 'take': '<optional lead>',
                             'design': '<content, visual relationships and walkthrough>'}]},
    })
    task_path.write_text(task, encoding='utf-8')
    return [prompt_path, task_path]


def prepare_scene(work, request):
    from .page_recipes import capabilities
    from .page_scene_binding import SCHEMA as SCENE_SCHEMA, copy_bindings

    design = read(work/'page_design.json')
    prompt_path, task_path = work/'page_scene_prompt.json', work/'page_scene_task.md'
    write(prompt_path, {
        'request': prompt_request(request),
        'schema_path': str(SCENE_SCHEMA),
        'page_design': design,
        'copy_bindings': copy_bindings(design),
        'recipes': capabilities(),
        'page_size': {'width': 13.333, 'height': 7.5, 'unit': 'inches'},
    })
    task_path.write_text("""# 题目入口的 PageScene 实现

完整读取 `work/page_scene_prompt.json` 和其中 schema_path 指向的 Schema。
按页面设计的 ID 和顺序，写出 `work/page_scene.json`。可直接填写标题、正文、标签、表格和公式，
也可选用 copy_bindings 中的引用。需要时细化文案或调整视觉实现。

- 手写对象使用英寸坐标 box。使用可编辑的文字、形状、表格、图表或公式；图片使用实际文件路径。
- 合适时从 recipes 选择布局。题目页可按需要选择标题、结论和讲稿。可见信息应在页面内，保证字号和间距可读。
- 用 scene_preview 检查需要复核的页面。提交后构建可编辑候选；如需 PowerPoint 导出，按候选返回的 native 操作继续。
""", encoding='utf-8')
    return [prompt_path, task_path]
