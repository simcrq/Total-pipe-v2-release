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
    use_deck_ir = request.get('page_mode') == 'deck_ir'
    downstream = (
        '输出 `work/page_design.json`，使用 topic-1.0 协议。后续进入 Deck IR（自动测量排版、原生流程图/架构图/图表/表格/公式编译）；'
        '也可在设计阶段直接将单页 Deck IR 草稿写入 `work/pages/<id>.json` 并用 `advance(preview=...)` 实时调试。'
        if use_deck_ir else
        '输出 `work/page_design.json`，使用 topic-1.0 协议。后续 PageScene 可细化文案和视觉实现。'
    )
    task = f"""# 题目入口的内容策划与页面设计

完整读取 `work/page_design_prompt.json` 和其中 schema_path 指向的 Schema。
从 request.topic 出发，依照用户的语言、场合和 requirements，自行确定论点、受众需要了解的内容及讲解顺序。
language 为 auto 时，根据题目及用户要求决定语言。{target}

- 为每页写清内容、视觉关系、多区排布和讲解顺序。可写 title、take、notes，正文、图示、对照表与公式构想写进 design。
- 非封面页优先规划 2–3 个互补视觉区（目标覆盖正文带约 45%–75%），避免单列几句文字或大面积空洞留白。
- 是否查资料以及如何使用图表、公式、列表和图片，按题目及用户要求决定。页面设计只提交设计 JSON。
- {TOPIC_EXAMPLES}
- {downstream}
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
    payload = {
        'request': prompt_request(request),
        'schema_path': str(SCHEMA),
        'example_lookup': lookup,
        'shape': {'schema_version': DESIGN_VERSION, 'deck_id': '<string>',
                  'pages': [{'id': 'P1', 'title': '<optional title>', 'take': '<optional lead>',
                             'design': '<content, visual relationships and walkthrough>'}]},
    }
    if use_deck_ir:
        from . import COMPONENT
        payload['syntax_reference_path'] = str(COMPONENT/'docs/deck-ir-syntax-reference.md')
    write(prompt_path, payload)
    task_path.write_text(task, encoding='utf-8')
    return [prompt_path, task_path]


def prepare_ir(work, request, design=None):
    """Prepare Deck IR handoff and per-page prompts for a topic-1.0 job."""
    from . import COMPONENT, adapters as a
    from .ir_pages import prepare_prompts
    from .prompts import example_lookup
    from deck_compiler.design import capabilities

    if design is None:
        design = read(work/'page_design.json')
    base = a.ir_prompt({}, {}, {}, {}, 'off')
    for key in ('workflow', 'rpa_input', 'content_model', 'deck_plan'):
        base.pop(key, None)
    lookup = example_lookup(TOPIC_EXAMPLES)
    try:
        from deck_compiler.example_index import catalog_brief, inventory
        lookup['catalog'] = catalog_brief(inventory())
    except (OSError, ValueError, KeyError, TypeError):
        pass
    prompt = {
        **base,
        'request': prompt_request(request),
        'page_design': design.get('pages', []),
        'design_forms': capabilities()['forms'],
        'design_devices': capabilities()['art_direction']['devices'],
        'example_lookup': lookup,
        'topic_mode_rules': {
            'slide_evidence_refs': 'Set semantic.evidence_refs=[] and semantic.caveats=[] (or caveats list); no paper EV IDs are required.',
            'tables': 'Use origin="generated" and omit evidence_refs.',
            'charts': 'Use basis="explain" and illustrative=true (or explicit non-paper data) with no evidence_refs.',
            'figures': 'Use origin="reference" (with reference_source) or origin="generated" (with 示意图/schematic in caption).',
            'academic_design': 'Optionally set presentation.academic_design (e.g. {"style":"research-seminar","title_treatment":"thin-rule","density":"balanced","figure_treatment":"unframed","decoration_policy":"minimal","header_variant":"compact"}) directly to skip the visual_design step.',
        },
    }
    raw_ir_prompt = work/'ir_prompt.json'
    if not raw_ir_prompt.is_file() or read(raw_ir_prompt) != prompt:
        write(raw_ir_prompt, prompt)
    designed_path = work/'ir_prompt_designed.json'
    if not designed_path.is_file() or read(designed_path) != prompt:
        write(designed_path, prompt)
    prepare_prompts(work, design, prompt)
    task_path = work/'deck_ir_task.md'
    task_text = """# 题目入口的 Deck IR 实现

完整读取 `work/ir_prompt_designed.json` 与 `syntax_reference_path`（`docs/deck-ir-syntax-reference.md`）。
按 `page_design.json` 的页面 ID 与顺序，输出完整 `work/deck_ir.json` 或按页提交 `deck_ir_page`（`work/pages/<id>.json`）。

- **查阅案例库与语法手册**：阅读 `docs/deck-ir-syntax-reference.md` 掌握 `layout_tree`、`graphics`（`process`/`dag`/`architecture`/`funnel`/`mechanism`/`path`）、`charts`（`line`/`bar`/`hbar`/`scatter`）、`tables` 与原生公式语法；用 `example_lookup` 打开匹配示例，避免空洞单列文字。
- **题目模式零论文门禁规则**：每页 `semantic.evidence_refs` 设为 `[]`；表格设 `"origin": "generated"`；图表设 `"basis": "explain", "illustrative": true`；可在顶层 `presentation.academic_design` 直接声明学术版式以自动完成视觉统合。
- 用 `advance(preview={artifact_path, slide_ids, mode:"layout"|"render"})` 检查骨架与渲染 PNG，确认无截断、孤字与失衡留白后提交。
"""
    if not task_path.is_file() or task_path.read_text(encoding='utf-8') != task_text:
        task_path.write_text(task_text, encoding='utf-8')
    return designed_path


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
