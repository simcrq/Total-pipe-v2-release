# Total-pipe v3 使用说明

本文描述当前主链，不兼容 M5 已删除的旧 SlideDSL、sidecar 或 Team wrapper。

## 1. 输入与输出

完整输入从论文 PDF 开始，编译器直接输入从 `deck_ir.json` 开始。

```text
论文 PDF
  → PaperWorkflow workflow.json
  → Story Planner story_plan.json
  → [可选 DesignIntentPlanner design_intent.json]
  → pwf2rpa rpa_input.json
  → RPA deck_plan.json
  → canonical deck_ir.json
  → Deck Compiler build directory
```

build directory 中的重要文件：

| 文件 | 含义 |
|---|---|
| `deck_ir.json` | 本次编译冻结的 canonical input |
| `layout.json` | 确定性布局、文本契约与 adaptation log |
| `candidate.pptx` | OfficeCLI 写出的 PPTX |
| `candidate.officecli.batch.json` | 原子命令记录，哈希写入 QA |
| `officecli_issues.json` | `view issues` 原始结果；已汇入统一 QA |
| `staging.pptx` | 与 candidate 字节一致的验收对象 |
| `native.pdf` / `native.json` | PowerPoint 原生证据 |
| `qa_report.json` | 统一 QA 结果 |
| `metrics.json` | 编译指标 |
| `state.json` | 生命周期状态 |
| `final.pptx` | 通过晋级后的交付文件 |

## 2. 从 PaperWorkflow 到 RPA

在首轮 PaperWorkflow 调用前按论文主题设置 `queries`，并检查主文引用的补充文件。
有定制问题且未设置 `include_default_queries` 时只使用定制问题；没有定制问题时
才运行通用默认问题。文件名无法关联的补充 PDF/Markdown 可传
`supplementary_paths`（与主文处于同一源目录，可用绝对或相对路径）；工具记录
显式配对并检查文件存在。仅配对时补充材料门禁仍为 `review`；先将补充 PDF
合并后 OCR，或把其 OCR/Markdown 与主文合并为分析输入，再设置
`supplementary_content_included=true`。`quality_audit.ready` 只说明文本捕获可用，
科学综合要看 `synthesis_readiness` 六项门禁；出现 `review` 就按失败门禁补证据，
不能把 OCR 分数当作交付许可。

运行 PaperWorkflow 后，使用用户明确选择的高能力模型生成 Story。Story 节点保留
`question / answer / evidence / next` 四个必需字段；如果一句回答会丢掉后续页面必须保留的细节，可选加 `key_points` 字符串数组，不要求每个节点都有，也不限制条数。Story 不决定最终版式或 bbox。

调用 `pwf2rpa_story_prompt` 时传入 `workflow_path`、用户选定的 `model`、
`reasoning_effort` 和 `selected_by_user=true`。工具默认在 `workflow.json` 旁写
`workflow.story_prompt.json`；可用绝对路径 `out_path` 改写输出位置。MCP 始终只返回
路径、证据数量和模型选择等小回执。Story Planner 子代理读取完整文件后生成
`story_plan.json`。若 MCP 调度超时，在 `pwf2rpa` 目录使用同一生成器：

```bash
python -m pwf2rpa <workflow.json> \
  --make-story-prompt <story_prompt.json> \
  --story-model <user-selected-model> --story-reasoning <high-or-stronger> \
  --model-selected-by-user
```

这一命令只验证并封装证据，不执行模型推理。更改 MCP 服务代码后须重启服务以刷新
运行中的工具 schema；插件缓存中的技能说明需要刷新插件后才会同步工作区版本。
MCP 服务以 ASCII 转义的 JSON-RPC 响应传送中文内容，避免 Windows 默认代码页使
`story_prompt`、`check` 或 `convert` 的返回值变成无效 UTF-8；不改变解码后的内容。

```json
{
  "question": "为什么出现这一现象？",
  "answer": "结果支持机制 A，但不能排除机制 B。",
  "key_points": ["首先，实验观察到……", "进一步分析显示……", "但是仍不能排除……"],
  "evidence": ["EV0012", "EV0013"],
  "next": "如何区分机制 A 和机制 B？"
}
```

需要把四条连续 `key_points` 明确表达为流程时，可在 Story 完成后由独立
DesignIntentPlanner 写可选文件；它只判断关系，不写 bbox、槽位或坐标：

```json
{
  "slides": [
    {"story_node_index": 2, "relation": "process", "orientation": "vertical", "emphasis": 4}
  ]
}
```

`story_node_index` 从 1 开始，`emphasis` 可省略；首版只支持恰好四条
`key_points` 的纵向 `process`。未知字段、重复索引和几何字段会报错。
不需要流程意图的页面省略该文件，旧 Story 四字段与转换输出保持兼容。

pwf2rpa 将 `answer` 送入 Brief 的 `takeaway`，将 `key_points` 按原顺序送入同名字段，并计入 `text_chars` 与布局容量检查。`evidence_texts` 是原始证据资料，不自动进入正文。直接提供 Brief spec 时，`body` 中的段落换行会保留。
默认结尾标题根据 Story 主体语言选择：英文为 `Conclusions and scope`，中文为
`结论与边界`；`title_chars` 由转换器根据生成标题计算。转换后检查整套标题语言，
若需改写标题，先改 Story/规划输入再运行转换，避免标题与计数不一致。`--design-intent` 只在有流程意图时传入；对应 Brief 的 `metadata.visual_intent` 不复制要点正文，并设 `allow_auto_split=false`。容量不足时返回重规划，不能自动拆散四点硬关系。

```bash
cd Total-pipe/pwf2rpa
PYTHONPATH=. python -m pwf2rpa workflow.json \
  --story story_plan.json \
  --design-intent design_intent.json \
  --story-model "<user-selected-model>" --story-reasoning high \
  --model-selected-by-user --strict --out rpa_input.json
```

然后在同级 `research-ppt-assistant` 项目运行：

```bash
cd ../../research-ppt-assistant
node server/cli.mjs normalize-content \
  --file ../Total-pipe/pwf2rpa/rpa_input.json --detail-level standard

node server/cli.mjs plan --file plan-input.json --detail-level full
```

实际路径按工作区调整。RPA 的 `normalize_content` 必须返回 `valid`，
`create_deck_plan` 必须完成 `plan_complete`，之后再运行 `validate-deck`。
保存未截短的 `normalized_content.json` 作为内容基准。每次修订 RPA 计划后，用
`{ "slides": <修订后的 slides>, "content_model": <原 normalized_content> }`
作为 `validate-deck` 输入；若返回 `KEY_POINTS_LOST`，恢复对应 `key_points`
的原文与顺序，再重新规划。`compact` 输出会完整携带 `slides[].key_points`，
但其 slot 文本可能截短，不能用它重建源 Slide Brief。

还需检查 `SOURCE_TEXT_NOT_BOUND`：它表示 `body` 或某条 `key_points` 只以
内容 ID 占了槽，实际文本已被截短或改写。此项是硬错误。长正文不可自动裁切；
总结页装不下时保持 `needs_replan` 和未规划 Brief，不能改选 literature 类别来
假装完成。`adapted` 只表示规划经过调整，须核对 `adaptation_log`；正式进入
Deck IR 前要求无未规划页、`validate-deck status=valid`。

有 `metadata.visual_intent` 时，RPA 输出 `slide.design_ir.visual_topology`，并用
`slide.layout_contract` 记录所选 `layout_id`、绑定整组原文的 `slot_id`、四点顺序
和强调索引。四条原文未完整落槽会返回 `needs_replan` /
`VISUAL_INTENT_NOT_BOUND`；自动拆分不能破坏该组（`VISUAL_INTENT_GROUP_SPLIT`）。
不要把 RPA 的布局坐标当作设计意图。

RPA 的总 `text_chars` 与槽位 `max_chars` 是码点粗筛，不等于英文单词、字宽或
实际换行数。绑定器优先选能完整容纳正文的槽；验收还会用槽宽和字号估计中英文
换行，`SLOT_WRAP_RISK` 需要真实页面复核。Evidence 内容角色与布局展示角色
分属不同体系，不应制造 `ROLE_MISMATCH`；真正的布局角色不匹配仍保留警告。

Codex 插件的 MCP 配置在 [Total-pipe/.mcp.json](../.mcp.json)，入口是
`deck_compiler/mcp_server.py`，内含 pwf2rpa 原有工具。`pwf2rpa_story_prompt`
构造 Story 请求，默认写出 `workflow.story_prompt.json` 并返回小回执；
`pwf2rpa_check` 在写文件前检查可选 `key_points` 与正文的容量；
`pwf2rpa_convert` 写出 `rpa_input.json`。`pwf2rpa_check` / `pwf2rpa_convert` 可传可选 `design_intent_path`，必须同时给 `story_path`。移动项目后需要更新配置中的 Python
可执行文件和服务脚本绝对路径。

## 3. RPA 到 Deck IR

该步骤是明确的契约映射，不允许复制 RPA 的最终 bbox：

- RPA title/goal/takeaway/evidence 映射到 `semantic`；
- 内容角色映射为稳定的 `composition.blocks[].component`；
- 视觉对象映射为 `figure_refs` 和 `assets`；
- RPA Layout 只用于选择合适 archetype/component，不把坐标写进 IR；
- 对通过验收的流程 `layout_contract`，把四条原文依序映射为四个实际 block，并在 `composition.visual_intent.members` 引用这些 block ID；
- 该显式流程若有一张科学图用 `figure-parameters`，若没有图用 `process-flow`；不要为了版式凭空补图；
- 整套页面先确定顶层 `presentation.frame_variant`（`default` 或 `spacious`）；省略时，只要任一页请求 `spacious`，编译器整套采用 spacious frame；
- 一图加 3–4 个同级步骤/参数用 `figure-parameters`，将 block 按阅读顺序放入 `composition.blocks`；编译器据此保持 24 px 纵向间距，无需新增坐标字段；
- 对单图四步加工路径，若四个 block 无独立 `label`，从 `method` 开始、中间含 `process-step`、以 `result` 结束，编译器会加入编号与纵向连线，展示由材料/方法到结果的推进；文本保持原样，56 px 引导区计入容量检查；
- 所有 `evidence_refs`、`caveats` 和 `speaker_notes` 必须保留。
- `key_points` 的科学内容须按源 Brief 的顺序进入 block 正文或 speaker notes；
  不能只保留 `takeaway` 或压缩后的设计意图。普通页面容量不足时拆页；硬流程组须先重规划。

显式流程意图在 Deck IR 中使用下面的无坐标结构；`members` 必须与四个
`composition.blocks[].id` 的实际顺序完全一致，`emphasis` 为可选 block ID，
从 RPA `emphasis_index` 映射而来：

```json
"visual_intent": {
  "relation": "process",
  "members": ["b1", "b2", "b3", "b4"],
  "orientation": "vertical",
  "preserve_order": true,
  "emphasis": "b4"
}
```

编译器只接受四个无独立标签的 block：单图时用 `figure-parameters`，
无图时用 `process-flow`；
成员不匹配会以 `VISUAL_INTENT_INVALID` 阻断。未声明显式意图时，
旧版按组件角色识别的四步流程仍兼容。

Deck IR 只接受
[catalog.py](../deck_compiler/catalog.py) 中的 archetype/component。
超出容量时返回 `CONTENT_CAPACITY_EXCEEDED` 或 `SPLIT_REQUIRED`，应回到 Story/RPA
拆页，而不是继续缩小字号。

### 长多段正文

如果 RPA 输出 `design_ir.text_flow.mode = distributed_arrow_list`：

1. 保留该布局展示的条目顺序；源 Brief 的 `key_points` 没有固定条数；
2. 用换行连接到一个 Deck IR block 的 `text`；
3. 将该 block 的 `text_flow` 设置为 `distributed_arrow_list`。

也可以将 block 设为 `auto`，由 Deck Compiler 识别。示例：

```json
{
  "id": "limits",
  "component": "body",
  "label": "适用边界",
  "text_flow": "auto",
  "text": "实验覆盖当前材料和功率窗口。\n机制证据仍不能排除替代解释。\n跨材料结论需要新的对照实验。"
}
```

自动模式要求 3–5 个明确段落、总显示长度至少 72 单位、单项不超过 120 单位，
汉字按 2 单位计。公式、表格、图注、参考文献和单个长段落保持普通文本。

## 4. 编译

v26 候选通过同级间距和图注留白校正后再次检查容量、碰撞与字体；无法通过时回退。`layout.json` 给出实际 `deck_frame_variant`，`layout_provider.json` 与 `derived/plan_to_layout.json` 给出每页布局来源。图像至图注正常相隔 12 px；较长的同级文字允许不同框高，但不允许间距漂移。
四步流程的编号连线由编译器生成，记录为 slide `adaptation_log` 中的 `sequence_rail`；不把装饰性几何写进 Deck IR。v26 只建议现有单位的宏观几何；文字适配、等距、连线及最终合法性由编译器负责，不另加排版器或全量 deck 风格 pass。

MCP 入口提供三个工具：`totalpipe_compile` 编译布局（默认 v26），
`totalpipe_build` 通过 OfficeCLI 生成 PPTX 候选与 QA，
`totalpipe_review` 按需检查现有构建并导出截图。三个工具的 `ir` / `out`
路径都应为绝对路径；`review` 只需要 `out`。

先做无渲染编译检查：

```bash
cd Total-pipe
python -m deck_compiler compile \
  --ir /absolute/path/to/deck_ir.json --out /absolute/path/to/build
```

正式生成：

```bash
python -m deck_compiler build \
  --ir /absolute/path/to/deck_ir.json --out /absolute/path/to/build \
  --officecli /absolute/path/to/officecli
```

开发时可添加 `--skip-native`，但该结果只能用于检查，不能晋级 final。
OfficeCLI 是唯一的 PPTX 写入后端；完整协议与 agent 操作见
[OfficeCLI 后端说明](officecli-backend.zh-CN.md)。
OfficeCLI `view issues` 中的 `Text overflow` 判断不准确，既可能误报也可能漏报。
保留该 issue 记录，结合实际 PPTX 页面和 PowerPoint 逐页眼检确认；
不要为了清除提示压缩或删除 `key_points`。真实溢出应通过布局调整或拆页解决。

## 5. PowerPoint 原生验收

验收对象始终是当前 `staging.pptx`。在 macOS 或 Windows 的 PowerPoint 中：

1. 用 Microsoft PowerPoint 打开 staging，在普通视图或阅读视图直接逐页检查；
2. 核对文字、图片比例、论文图号—图注—素材、panel 标签、页脚、越界、碰撞和字体；
3. 不要用 Preview、PDF 或逐页渲染图代替 PowerPoint 中的眼检；
4. 眼检完成后记录与当前 staging/layout 哈希绑定的证据：

```bash
python -m deck_compiler record-powerpoint-review \
  --out /absolute/path/to/build --reviewer "reviewer" --slides all
```

5. 在同一次 PowerPoint 控制流程中导出为 build directory 下的 `native.pdf`；
6. 绑定该 PDF：

```bash
python -m deck_compiler validate-native \
  --out /absolute/path/to/build --pdf /absolute/path/to/build/native.pdf \
  --reviewer "reviewer"
```

`validate-native` 会重新检查当前 staging、layout 与 `powerpoint_review.json`；不要复用
其他版本的 PDF 或眼检记录。论文图 asset、figure reference 和图注必须声明并匹配
同一个 `source_figure`；科学图面默认最小有效尺寸为 220 px，任一条件不满足均为 FAIL。
macOS 可由编译器自动尝试导出 PowerPoint PDF；Windows 当前按上述步骤在 PowerPoint
界面完成逐页眼检与 PDF 导出，再使用 `validate-native` 绑定原生证据。

## 6. REVIEW acknowledgement 与晋级

如果 `qa_report.json` 含 REVIEW，acknowledgement 至少包含：

```json
{
  "artifact_sha256": "<staging sha256>",
  "reviewer": "<reviewer>",
  "accepted_review_ids": ["<review id>"]
}
```

必须列出当前报告中的全部 REVIEW ID：

```bash
python -m deck_compiler promote \
  --out /absolute/path/to/build --ack /absolute/path/to/review_ack.json
```

只有结构检查、PowerPoint 证据和 REVIEW acknowledgement 都与当前 bytes 对应时，
才会生成 `final.pptx`。

## 7. 常见误区

- `compile` 只生成 IR/layout/QA，不生成 PPTX。
- `build --skip-native` 不代表正式通过。
- RPA `design_status: pass` 不代表 Deck Compiler 或 PowerPoint 验收通过。
- `candidate.pptx` 不是交付文件；验收和晋级针对 `staging.pptx`。
- 手工修改 staging 后，旧 QA、PDF 和 acknowledgement 都会失效。
- `final_msyh_decorated.pptx` 是 Test3 的人工修订变体，不是编译器自动输出基线。
- 不要恢复 M5 已删除的旧 adapter 或双轨 QA 作为兼容路径。

## 8. 回归检查

```bash
cd Total-pipe
python -m unittest discover -s tests -v

cd pwf2rpa
PYTHONPATH=. python -m unittest discover -s tests -v

cd ../../research-ppt-assistant
npm test
npm run audit:layouts
```

发布副本的 `SHA256SUMS` 必须在所有同步修改完成后重新校验。
