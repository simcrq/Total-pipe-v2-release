"""Prompt templates and task briefs for agent-delegated design and IR authoring."""
import sys

from . import COMPONENT
from .content_review import SPOKEN_COPY


DESIGN_MARKER = ' A page design is approved.'

PROJECTION_IR_INSTRUCTIONS = (
    'Implement approved page design 1.2/1.3 as canonical Deck IR. Scientific records and audience copy '
    'are separate: the tool archives complete assigned Story text and scoped qualifiers in notes; '
    'do not copy those records, design directions, review notes or walkthrough instructions into prose. '
    'Use only the approved display_copy for audience narrative (titles, takeaways, body, labels and captions). '
    'You may write {"copy_ref":"id"} in a textual field; the tool resolves it before canonical Schema validation. '
    'Keep literal data/formulas and traceable paper-figure/source metadata in their evidence carriers. '
    'For 1.3, inspected figure identities and visible source labels are bound from figure_sources; '
    'do not prepend them to approved caption text or put experimental conditions in source metadata. '
    'Use caption_for={kind,ref} for captions. On a layout tree, caption_for.position or text_for.position '
    '(top/bottom/left/right) binds a caption or prose to an image, graphic, independent formula, table or chart. '
    'Keep the target leaf in the tree; omit the attached block leaf. '
    'Use native_bullet_list or native_numbered_list for approved parallel points or ordered steps '
    '(including one-item callouts); bullet_icon can set one Unicode symbol. Keep scientifically meaningful words intact. '
    'For independent prose keep one block ID, copy_ref, evidence binding and layout leaf per approved body entry. '
    'Set the marker on each block. For ordered independent blocks assign each block its own list_start '
    'in the approved reading order. Do not join approved entries with newlines or run listify on a reviewed page. '
    'Realize the approved body guides as editable objects: native markers, rounded group labels or text-bearing '
    'nodes, and the specified comparison lanes, dividers or connectors. Preserve each marker’s reading role '
    'and the approved copy. A panel title chip can name a group; rounded graphic nodes can show genuine steps '
    'or branches. Inspect the grouping and reading order in the layout and rendered previews. '
    'Implement content_map carriers exactly; notes never satisfy required visible content or scoped conditions. '
    'The semantic.content_projection is bound automatically from the reviewed design, never authored or edited. '
    'Preserve meaning, units, conditions, uncertainty, important controls and negative findings. '
    'Do not add prose or simplify a claim. If approved copy or required objects do not fit, return measured '
    'feedback and replan page_design, retaining scientific records. Use native editable drawings and formulas. '
    'Select compiler capabilities to realize the approved visual relationships; do not redesign them. '
    'All font floors, original-figure aspect ratios, provenance, supplement boundaries and scientific '
    'geometry gates remain. Set the venue visual_style; declare no page coordinates. '
    'Use composite-research/layout_tree when explicit grouping is needed, and simple archetypes otherwise. '
    'Native data values cannot be guessed from raster curves. Explicit $...$ supports measured inline math. '
    'Body and label copy can move between editable body/label carriers without rewriting it. '
    'Put an approved standalone equation in a block using its copy_ref. Binding converts a body block '
    'with an equation-only paper copy into a native display formula. Keep marked inline math in prose. '
    'Start with preview.mode=layout for compiled skeleton and single-object diagnostics on dense, sparse '
    'or new compositions. Then open the default preview PNG and check actual typography and math before '
    'submitting deck_ir_page. Use layout_feedback and deck_compiler explain for specific failures. '
    'Complete full Design, build/QA and PowerPoint native acceptance after authoring.'
)


def example_lookup(instructions):
    library = COMPONENT/'examples/library'
    return {
        'command_prefix': [sys.executable, str(library/'catalog.py')],
        'index_path': str(library/'index.json'),
        'instructions': instructions,
    }


BODY_GUIDES = (
    'Give the presenter a concrete reading path in design: name the first visual anchor, what to compare '
    'or trace there, and where to point to the explanation or applicable condition. '
    'Plan visual guides for independent body blocks. Explain which blocks belong together and '
    'how the audience reads them. Treat each body block as a separate editable object. '
    'A short rounded heading can name a group; peers can share a small icon '
    'or bullet and ordered steps can use numbering or connected text-bearing shapes. For a comparison, '
    'one shared heading can introduce two named groups or lanes, with a divider or alignment identifying '
    'the boundary; use arrows and short labels for real transitions within a lane. Use display_copy IDs '
    'when available to name the guided text, and say what the grouping or reading order expresses. Keep '
    'labels short and in approved audience copy. Choose guides only where they carry a relationship.'
)

BODY_GUIDES_TASK = (
    '在 design 里写清观众先看哪个视觉锚点，在那里比较什么或沿什么顺序看，以及到哪里看解释或适用条件。'
    '为独立正文块设计视觉引导，写清哪些块属于同组。'
    '各条正文保持独立，分组可以共享标题或标记样式。'
    '短圆角标题框可以给一组正文命名，并列要点共用项目符号或图标，顺序步骤可用编号或相连的带文字形状。'
    '对照流程可用一个共同标题统领两条有名称的路线，用对齐或分隔线区分路线，用带动作短语的箭头说明路线内的步骤。'
    '有 display_copy 时指明对应 ID，新增可见标题和标签须进入批准文案。标记服务于实际关系。'
)

DESIGN_EXAMPLE_TASK = (
    '需要构思呈现方式时，用 `example_lookup.command_prefix` 执行 `search "<讲解关系>" --limit 2`，'
    '例如“机制对比 双路线”或“原图导读 条件与结论”。按需打开一份匹配的示例脚本，参考构图、视觉关系和讲解顺序。'
    '设计交接用自然语言写清如何应用于当前论文。示例中的文案、数据和证据仅用于演示。'
)


LEGACY_DESIGN_INSTRUCTIONS = (
    'Design the visual explanation of the approved Story. Story owns the scientific argument, '
    'claims, evidence and boundaries; do not retell it, reinterpret it or write another outline. '
    'Your output is a drawing and presentation brief for the IR author: what to put on the page, '
    'what to draw or reuse, how to arrange it and how the presenter guides attention. '
    'Assign each Story content path from content_catalog to exactly one page using content_refs; '
    'the pipeline inherits its text and evidence automatically. Never copy Story paragraphs into '
    'the design. A short display title or a necessary diagram label is fine. '
    'Use design as free prose or a custom object, whichever communicates the page best. Describe '
    'concrete visual objects: selected original panels, drawn shapes, layer stacks, arrows and '
    'edge meanings, icons with a purpose, comparison axes, equation annotations or data charts. '
    + BODY_GUIDES + ' '
    'You may draw your own explanatory diagrams, mechanisms, processes and structures; using a paper '
    'image is a choice, not a requirement for every page. Mark illustrative drawings as schematic, '
    'keep paper facts and data bound to their evidence, and label constructed examples explicitly. '
    'Specify their relationship, relative placement, visual hierarchy and the order in which the '
    'presenter points to them. A vague instruction such as explain the mechanism is insufficient. '
    'Choose which visual forms serve the content; nothing you decide here depends on what a tool '
    'can draw. You may name a diagram or composition, but do not choose compiler templates, '
    'archetypes or API components. No mandatory cards, columns, icon quotas or decorative filler. '
    'The room is given by the request; record setting briefly rather than analyzing it at length. '
    'Inspect actual image files before selecting them; use the exact asset_id in figures, preserve '
    'aspect ratio and figure/source labels, and say where annotations should point. Never guess '
    'curve points or draw an unavailable supplementary figure. New measurements, causal claims or '
    'external facts are outside this stage; flag missing Story/evidence upstream rather than inventing '
    'them. Illustration is visibly schematic and must preserve the distinction between observation '
    'and author interpretation. A data chart needs traceable data; otherwise use the original image. '
    'Respect Story explain obligations: the visible page must contain the objects needed to understand '
    'the conclusion, while optional detail can be spoken. Split or merge content references as '
    'needed within the requested page count, retaining every content unit. Do not write Deck IR '
    'or final coordinates. Make a concise, concrete design handoff, not a second scientific essay.'
)

DESIGN_INSTRUCTIONS = (
    'Design the audience expression and visual explanation of approved scientific records. '
    'Story owns facts, argument, evidence and visibility policies. You own faithful display_copy: '
    'rewrite for this audience, replace verbal repetition with a meaningful diagram, and give each page a clear claim. '
    'Preserve scientific meaning, causal strength, comparison objects, units, uncertainty, controls and negative results. '
    'Scientific record preservation does not require copying its sentences onto the screen. '
    + SPOKEN_COPY + ' Write claim-first audience copy, not an audit memo. '
    'Put a limitation in visible copy only when omitting it would make that page claim false or misleading; otherwise keep it in '
    'speaker notes or on one dedicated boundary page. Do not spread stock caveats (author claim, not verified, only, cannot, '
    'not a ranking) across result pages. A group-meeting audience needs calibrated claims, not defensive boilerplate. '
    'Never make a result title or takeaway announce what is unverified; state the finding, then one boundary page may carry scope. '
    'Every page with a paper figure needs a concrete readout in a caption or label: which panels, what axes/conditions, which '
    'feature to look at, and what it means. That is audience explanation, not a source disclaimer. '
    'Do not leave a figure page as an image plus unlabelled assertions; name the visual evidence in the projected text. '
    'Assign each scientific source in content_catalog exactly once with content_refs. Write display_copy (id, role, text, source_refs), '
    'with exactly one title and takeaway. Roles are title/takeaway/body/label/caption, not layout templates. '
    'Map every assigned source to visible carriers or justified notes using content_map. A visible route lists '
    'carriers {kind,ref,locator}: copy refers to display_copy id; figure names a selected inspected asset; '
    'formula/table/chart/graphic names the visual object you describe. Visual locators explain what evidence to read. '
    'Follow content_contract: required sources stay visible; a with_claim qualifier is also mapped visible on every '
    'page where an applies_to claim is visible, even when owned by another page. These contextual qualifiers may '
    'repeat visually, while source ownership remains unique. notes_allowed needs a reason based on the page claim. '
    'Do not turn important controls, uncertainty or negative findings into optional spoken detail. '
    'When a sourced equation actually explains how the method works or how to read the result, '
    'approve the complete equation in display_copy using $...$ (as its own body entry for display math), '
    'and separately approve short prose explaining the relevant variables and conditions. '
    'Use the exact source expression and omit decorative math or unsupported formulas. '
    'Keep production_notes separate. design/claim rationale/walkthrough/negative authoring directions are not '
    'display_copy. Do not dump evidence-audit prose onto slides; show a limitation only where it restricts the specific claim. '
    + BODY_GUIDES + ' '
    'Separate the visual, its reading cue and the implication where that helps the audience follow the claim. '
    'Use short subheads, key-number callouts and emphasis for the terms a speaker would point to; a page of equally '
    'weighted sentences is not a visual explanation. Prefer light panels, thin accent rules and small labels. '
    'Do not use large dark fill blocks, full-width dark banners or near-black cards behind body text; reserve '
    'dark fill for small tags/chips only. '
    'Paper copy cites source_refs and inherits their evidence. Organizational copy uses basis=organization and no '
    'source_refs or scientific numbers; it cannot supply scientific claims. Supplementary copy uses basis=supplement '
    'and supplement={kind,source,constructed}, no paper refs, and visible labels for constructed examples. '
    'Use design as free prose or a custom object for concrete visuals, their relationships, hierarchy and presenter '
    'pointing order. You may draw your own explanatory diagrams, mechanisms, processes and structures. '
    'Choose visual forms that serve the argument; nothing you decide here depends on what a tool can draw. '
    'Do not select compiler templates, archetypes, APIs or coordinates. No mandatory cards, columns or icon quotas. '
    'Inspect actual figure files before selecting exact asset IDs, preserve aspect ratio and source/figure labels. '
    'Do not guess curve points or unavailable supplementary images. Label illustrative drawings as schematic. '
    'Use setting to briefly reuse the requested room, audience and reading mode. After design, the orchestrator '
    'performs source/copy review; do not supply a self-approval. Keep the handoff concrete and concise.'
)

ATOMIC_DESIGN_INSTRUCTIONS = (
    'Atomic content_contract 2.0: scientific units, not narrative paragraphs, are the source of truth. '
    'Own every unit exactly once via content_refs. If you repeat a required assertion owned by another page, '
    'declare its ID in reuse_refs, actually display it and cite it; do not clone the assertion under a new ID. '
    'Only qualifiers directly targeting assertions actually visible here follow them. Do not inherit an entire '
    'Story node, unrelated experiment, or the conditions of a result you did not restate. '
    'A concluding conceptual claim can omit a numerical result already explained; if the number is restated, '
    'its source and applicable conditions must remain visible. Keep the whole scientific ledger in the deck, but '
    'keep the visibility ledger separate: scoped limitations can live in notes or one boundary page, not in every result. '
    'When a page fits a recipe in prompt.recipes, write recipe and slots; reference display_copy ids '
    'as {"copy_ref": "<id>"}. Record the body guides in design as well. If a recipe cannot express the '
    'intended hierarchy or reading order, describe the arrangement in design. '
    'For every selected figure, figure_sources maps its exact asset ID to {source_figure: inspected figure/panel ID}. '
    'These are source identities, not measurements. The tool renders their visible provenance separately from '
    'approved caption wording; never delete source labels to satisfy a numeric check. '
    'If the approved science still mixes independently limitable claims or omits a prerequisite, report an upstream '
    'Story problem instead of hiding conditions or adding unsupported facts. '
) + DESIGN_INSTRUCTIONS


def design_task(prompt=None):
    """Delegate visual explanation, without duplicating scientific planning."""
    figures = len((prompt or {}).get('figures') or [])
    briefs = len((prompt or {}).get('briefs') or [])
    target = ((prompt or {}).get('request') or {}).get('slide_count')
    pages = f'最终论文页为 {target} 页。' if target else '按内容和场合排页，最多 40 页。'
    if ((prompt or {}).get('story') or {}).get('content_contract'):
        atomic = (prompt['story']['content_contract'].get('version') == '2.0')
        contract = '1.3（原子科学记录）' if atomic else '1.2'
        return f"""# 页面表达与设计任务（独立子代理，{contract}）

完整读取 `work/page_design_prompt.json` 和 schema_path 的完整 Schema。输入含 {briefs} 条参考 briefs、
科学记录及其可见性契约、{figures} 张图、证据与场合。输出 `work/page_design.json`。{pages}

- Story 决定科学含义及边界，你负责忠实改写成观众文案和视觉讲解，不重做科学大纲。
- 每条科学记录用 content_refs 恰好分配一次；display_copy 写实际投屏的标题、结论、正文、图中标签和图注。
  每项用 source_refs 追溯，保留关键英文术语。标题先说发现，正文把比较对象和直接条件说清。图形节点和边短语也在此审批。
  顶层 marks 只写要强调的现有文案片段，绘图动作写入 design。
- content_map 给每条分配记录标明 visible 的载体或 notes 的理由。required 必须可见；with_claim 的条件
  跟随它限定的主张同页可见，必要时重复显示条件，而不重复分配原始记录。完整记录由程序归档到讲稿。
- design 自由说明用什么原图、画什么元素与关系、如何排布、怎样带着观众看。figures 写精确资产 id，先看图。
  图中数据不能猜点；示意与构造例须可见标识，论文与补充背景来源分开。
- {BODY_GUIDES_TASK}
- {DESIGN_EXAMPLE_TASK}
- setting 复用用户场合，不展开第二次听众分析。讲解顺序指向具体对象。无需知道编译器能力，不读编译器源码。
- 你不填写通过审查的记录。主 Agent 之后逐页对照科学记录审读文案，未通过会退回设计。

输出设计，简述页数和关键视觉选择。不要把这份任务书改写成幻灯片正文。"""
    return f"""# 页面设计任务（独立子代理）

Story 已经决定讲什么以及证据边界。你的任务是把它变成可执行的视觉讲解设计，交给 IR 作者。

- 完整读取 `work/page_design_prompt.json` 和其中 `schema_path` 指向的 Schema；输入含 Story、
  {briefs} 条参考 briefs、证据、{figures} 张图的路径与尺寸、场合以及 `content_catalog` 引用索引。
  Story 是内容权威，briefs 是传输参考，不需要重写其中的正文。
- 输出 `work/page_design.json`，使用 1.1 协议。{pages} 每条 Story 内容用 `content_refs`
  恰好分配一次；开场等纯组织页可为空。正文与 evidence 由管线从 Story 自动继承。
- 每页只必填 `id`、`content_refs`、`design`。`design` 可以是一段话，也可以是你自定字段的对象；
  不规定所有页面用同一套结构。说明**用什么原图、画什么元素与关系、如何排布、怎样带着观众看**。
  可按需写图形、图标、图表、公式标注、对照、局部放大和指示线；不要止于“解释某机制”。
- {BODY_GUIDES_TASK}
- {DESIGN_EXAMPLE_TASK}
- `figures` 列精确资产 id，先实际查看图再选择；相对路径基于 `workflow_root`。`title` 和 `marks`
  都可选，marks 只用于需要强调的现有短语。不需要重写 claim、items、anchor 理由或 rationale。
- `setting` 简述 audience、occasion（沿用 room.default_occasion 或选合适键）、reading（spoken/read/mixed）。
  场合服务于设计，不展开第二次听众分析。
- 内容顺序与科学结论沿用 Story，允许为视觉表达拆页、合页。讲解顺序写指向动作与对象，
  不再复述整段科学解释。保留 explain 中必需可见的内容。
- 可以决定图形与构图形式，不需要知道编译器能力；不写坐标、API 或 Deck IR，不读取编译器源码。
  原图保持比例与来源；数据图不猜点；没有补充图就不虚构；示意须可见标注且不增添科学主张。

交付时简述页数及最关键的视觉设计，不重述论文。"""


def ir_task(prompt=None):
    """The brief an orchestrator hands to the IR subagent once the design is approved."""
    pages = ((prompt or {}).get('page_design') or {}).get('pages') or []
    if ((prompt or {}).get('page_design') or {}).get('schema_version') in ('1.2', '1.3'):
        return f"""# Deck IR 实现任务（页面表达契约 1.2）

源文案已由主 Agent 审读。完整读取 `work/ir_prompt_designed.json` 或指定逐页提示包及完整 IR Schema。
实现 {len(pages)} 页的 display_copy、content_map 和视觉设计，保持页序、分配、选图和科学含义。

- display_copy 是投屏文案权威；Story 是科学记录。可在文本字段写 {{"copy_ref":"文案 id"}}，提交时自动绑定。
  不把 Story 长段、设计指令、walkthrough、核查备注重新填成正文；不自行增加或改写已批准的句子。
- semantic.content_projection、完整讲稿、来源和 scoped qualifiers 由程序绑定。必需可见的对象、条件和对照
  按 content_map 实现；讲稿和元数据不算页面可见。原生图表/公式承载的数据和原图来源保持可追溯。
- 选择能力实现既定视觉；自绘优先用原生对象，布局树可直接使用。不写页面 bbox，不缩字号、不删内容。
  容量不足时把测量反馈退回页面设计，不能修改科学含义或擅自润色文案。
- 落实已批准的正文分组、圆角标签、项目符号/编号和带箭头的阅读顺序。标题框与实质正文均保持可编辑。
- 保持每条独立正文各自的 block、文案引用与来源。先查逐页 `example_lookup.suggestions`，需要时细化检索，只读选中的示例。
- 写完草稿后，按 `next_action.page_authoring.pages[].preview_plan` 调用骨架预览。检查反馈后按
  `next_action.preview_follow_up` 渲染并打开实际 PNG。其他页可按需预览。
  已审读的独立公式用 copy_ref 进入原生公式块，混排保留原有数学标记。渲染与 QA 分开检查。

交付实现选择与真实未解决项。"""
    return f"""# Deck IR 实现任务（子代理）

页面设计已经批准。逐页实现视觉设计；Story 保持科学内容权威。

- 完整读取 `work/ir_prompt_designed.json` 及 IR Schema。其中有 {len(pages)} 页设计、Story、证据和实现能力。
- 输出符合 canonical Schema 的 `work/deck_ir.json`。资产 path 基于 workflow_root，IR assets 用绝对路径。
- 1.1 设计的 content_refs 指向 Story 原文；content_catalog 给出自动继承的 evidence，含 ending 的汇总来源。
  设计里的 design 是绘图、构图与讲解交代，
  包含具体元素、关系、排布和注意顺序。完整保留自定义设计说明，不把它退化成文字摘要。
  自绘内容优先用原生对象；图形形式已由设计确定，你只选择可实现它的 archetype / layout_tree 等。
- 页序、内容分配、选图和视觉关系不变；marks 如有则落实为文字强调。旧 1.0 设计的 claim/items/shape 同样实现。
- 保留设计要求的可编辑正文标记、分组标签和路线之间的对照关系。
- 每条独立正文保留一个块。先查逐页 `example_lookup.suggestions`，需要时细化检索，仅读选中的示例。
- 写完草稿后按 `next_action.page_authoring.pages[].preview_plan` 和 `next_action.preview_follow_up` 检查骨架与渲染图。
- 理解结论所需的证据必须可见，讲稿不能替代；保留单位、条件、误差和 Story explain 义务。
  放不下时报告具体所需空间并回退页面设计，不改科学含义、不猜数据、不删内容、不缩字号。

交付时简述实现选择与未解决限制。"""
