# Agent 接入层：安装、推进与恢复

默认入口为 `total_pipe` 四工具服务，完整科学 / 几何规范仍见 [总调度 Skill](../skills/total-pipe-deck/SKILL.md)。
[修订设计 v2](agent-adapter-design.md)记录了对用户 v1 稿的评审与实施取舍。
接入层不替代 PWF、pwf2rpa、RPA、Deck Compiler；也不自动生成 Story、IR 或视觉提案。

## 安装和 profile

完整仓库需包含相邻的 Total-pipe、PaperWorkflow、research-ppt-assistant，使用 Python 3.12+、Node.js 22+，
生成 PPTX 需 OfficeCLI 1.0.152+。在仓库根目录运行：

```bash
python3.12 install.py --client codex
# Claude 用户：
python3.12 install.py --client claude
# 只安装、验证服务，不注册客户端：
python3.12 install.py --client none
```

安装器在仓库 `.venv` 安装真实依赖，启动服务执行 initialize / tools/list，然后才写客户端配置。
`--python` 指定创建 venv 的解释器，`--venv` 指定环境目录；已有完备环境可用 `--skip-deps`。
`--config` 指定目标配置。`--dry-run` 只展示计划和配置检查，不创建 venv、不安装依赖、不写文件。
安装结果在根目录 `install-report.json`（已 gitignore），包含 doctor、握手与工具数。

Codex 默认配置位置是 `$CODEX_HOME/config.toml`，未设置时为 `~/.codex/config.toml`。
只替换末尾受管块，写前备份；坏 TOML、非托管同名服务或作用域歧义会中止。
Claude 默认 `~/.claude.json`，保留其他键并备份；仅命令、参数、环境写入其 stdio 配置，
绝对 launcher 自行切换正确 cwd。明确 `--force` 可替换 JSON 同名冲突，不能绕过 TOML 语义保护。
运行本仓库的开发测试不会修改真实用户配置；示例中的配置目标可换到临时目录。

默认 [`.mcp.json`](../.mcp.json) 仅声明四工具。调试 / 回切使用：

```bash
python3.12 install.py --client codex --profile advanced
```

[`.mcp.advanced.json`](../.mcp.advanced.json) 声明 PWF、RPA、低层 total_pipe_v3 三服务。
工具数量从当前实现握手读取，不固定为旧稿的 39。profile 切换删除本安装器原来的受管项，保留其他服务。
插件已有 mcpServers 路径仍指向 `.mcp.json`；源码 / 配置变化后须重载服务，插件缓存需另行更新。
孤立的组件缓存可能没有相邻 PWF / RPA；完整论文流程用安装器定位到完整 checkout。

## 四工具与工作循环

| 工具 | 输入与行为 |
| --- | --- |
| totalpipe_doctor | 可选 deep / source_kind；检查环境、实际 evidence 导入依赖与阶段能力，不运行 OCR |
| totalpipe_start | source、out_dir、language、presentation_type；可选 source_kind、requirements、queries、slide_count、supplementary_paths、supplementary_content_included、supplement |
| totalpipe_advance | job_id；提交 artifact_kind / artifact_path（含 deck_ir_patch）；deck_ir 可设 preflight=true；回填 inputs 或指定 replan_from / acknowledge；候选后可单独提交 native 操作 |
| totalpipe_status | job_id；可选 detail=summary/full，默认紧凑回复；只读，不执行组件或准备提示包 |

start / advance / status 默认返回阶段、next_action、QA 摘要、out_dir、state_path、events_path 和
artifacts_summary（引用数、去重文件数与阶段名）。完整请求与逐文件哈希不重复塞入每次回复；
需要时调用 `totalpipe_status(job_id, detail="full")`，返回原 request 与 artifacts 清单。
自动化若依赖这两个字段，应显式选择 full。状态查询不改写 job、提示包、反馈或事件日志；提示缺失时
返回 ADVANCE_REQUIRED，由 advance 准备完整提示。Agent 仍必须完整读取 next_action 指定的提示包和 Schema。

PDF doctor 使用 PWF 的实际 CLI/配置执行 `mineru-open-api auth --verify`，识别环境变量、配置密钥及
官方 CLI 缓存登录；只校验认证、不上传文档。`authentication_verified=true` 仅表示官方验证成功；
网络/CLI 不可用与认证拒绝分别报告。Markdown/workflow/IR 的浅检查跳过该网络请求，deep 可显式验证。

### 逐页 IR 与来源绑定

已通过 page_design 1.1 时，`next_action.page_authoring.pages` 提供每页完整 input_path、输出路径和缓存状态。
逐页读取提示包及完整 Schema，写一个 canonical Deck IR（slides 恰好一页，ID 与设计相同），再调用
`advance(job_id, artifact_kind="deck_ir_page", artifact_path=...)`。各页共用相同 deck_id/theme/presentation 头部。
逐页包保留本页全部分配文本、相关 Story 上下文、证据和完整实现指令；Schema 通过绝对路径引用。
设计者可以自绘机制、流程、结构及解释性图示，保持可见的示意标识与科学来源边界。

程序补入省略的 Story 证据清单和完整原文讲稿；显式提供的证据按逐页锚点/跨页完整覆盖检查。
figure_refs.asset_id 可直接使用 PWF 图片 inventory 的资产 ID 或路径，由证据包解析；source_figure 可在
引用或资产上声明一次并复制绑定，不从文件名猜图号，不覆盖冲突声明。S14 与主文 14 保持区分。

每页立即执行原有语义、证据、设计与 compiler/packer 容量检查；page_result 返回全部问题及 pending_pages。
通过页冻结在 work/ir_pages，相同页/图片/字体/编译器字节可复用测量（保留原 REVIEW），只修失败页；
每页各有3次不同拒稿额度。preflight=true 也可用于 deck_ir_page，检查不写缓存、不计次。
全部页就绪后按批准页序组装，复验整套 Story、证据和页数，再继续篇级 Design 和完整构建。
最终 PPTX 仍整套生成，未宣称逐页 OfficeCLI 或原生验收。改变公共头部须显式 replan_from="deck_ir"，
这会重置全部页缓存；只改局部内容时继续提交对应页即可。

### 完整 IR 提交预检

在 deck_ir 阶段提交前调用：

```json
{"job_id":"<job_id>","artifact_kind":"deck_ir","artifact_path":"/absolute/job/work/deck_ir.json","preflight":true}
```

CLI 对应 `python -m agent advance --job-id <job_id> --artifact-kind deck_ir --artifact-path <path> --preflight`。
`preflight_result` 汇总全部语义、设计、证据、补充泄漏问题，以及可测量的几何问题；正式提交共用相同
验收检查，并将全部问题写入 submission_feedback.json。预检在临时目录调用原 compiler/packer，禁用
自动内容修复和尚未完成的篇级视觉设计要求；不写 PPTX、不改 job/候选/事件、不消耗修订额度。
输入结构无效时可能无法测量几何，查看 `geometry_checked`。顶层 status 仍描述当前任务，预检结果看
`preflight_result.status`；CLI 退出码按预检结果。预检不等于接受产物，后续 Design、完整构建和原生验收仍必做。

page_design 1.1 将一个 Story 节点拆到多页时，每页须引用该节点的证据锚点，节点完整证据由这些页的
引用并集覆盖；不再要求每个子页重复整节点清单。ending 的综合证据由整套页覆盖。旧 1.0 显式逐页
证据要求保持不变；逐页数值、图片、讲解义务和补充泄漏检查继续执行。

`presentation_type` 支持 RPA 的 group_meeting / journal_club / proposal / progress_report / defense /
paper_presentation / custom。入口将“组会”“研究生组会”“group-meeting”规范化为 group_meeting，
research-sharing / 文献分享为 journal_club，research-report / 科研汇报为 paper_presentation。
lecture / 讲课与 commercial / 路演规范为 custom，同时在 presentation_context 保留原场合。
可在已识别标签后用逗号、分号或冒号补充听众/时长；未知标签在创建 job 前拒绝，建议把详细要求写在 requirements。
同一请求可用等价标签恢复，包括旧 job 的已识别别名；保留原 job 请求及用户模型选择，不从产物重建授权。
听众/时长说明、requirements 或 lecture/commercial 场合等实质要求改变时仍返回 JOB_OUTPUT_IN_USE。

source_kind 可为 auto、pdf、markdown、workflow、deck_ir。JSON 自动按 schema_version 识别；
已有 IR 保持语义，在 work 中保存以绝对资源路径重定位的副本，完整设计可直接 build。
已有 workflow 保留原证据包目录，从 readiness 与模型选择门禁继续。
PDF / Markdown 首先需要实际主题的 queries。queries 是 `[{"id":"q1","query":"具体检索问题"}]`，
可附 intent；接入层将 query 字符串交给 PWF，PWF 自行推导检索 intent 和 custom query ID。
显式配对 supplementary_paths；内容确已合入分析输入后才确认 supplementary_content_included=true。

`supplement` 取 `off`（默认）/ `inline` / `pages` / `both`，只影响 Deck IR 阶段：允许模型
添加论文之外的背景、类比、构造示例、推导说明、示意图或对照。补充块标
`basis=supplement`，不写 EV；`inline` 只允许页内块，`pages/both` 才允许独立补充页（页数不限）。
补充页可写 `semantic.explanation`，义务写 `basis=supplement`、不写 `evidence_refs`；paper 义务不变。
论文页/Story/RPA 不变；Agent 检查论文数值、图、长引用泄漏，补充页数超过论文页只给 INFO。
`slide_count` 表示最终论文页的精确目标（1–40），不是 Story 节点数或 RPA brief 数；未指定时由设计者
按内容与场合安排，最多 40 个论文页。独立补充文字页额外计；带论文 EV、图、表或原生图形的页仍算论文页。

**默认 RPA 阶段只做内容规范化。** pwf2rpa 产生完整 rpa_input，RPA `normalize-content` 保留完整正文、
key_points、引用与 EV；接入层不再调用 `plan/validate-deck` 生成随后被 page_design 覆盖的模板计划。
`rpa_validation.status=content_normalized`、`layout_owner=page_design` 只声明规范化完成，不冒充模板或
版面验证通过。旧 plan_input/deck_plan/validation_input 是该阶段拥有的过时派生物，阶段成功后移除。
RPA 独立 CLI 的模板规划功能不变。页面设计在目标页数内安排完整内容；空间不足回退设计，不能删句、
缩写术语或把听众理解所必需的证据藏进 notes。最终仍校验内容覆盖、证据、数字、字号与真实尺寸。

### 页面设计阶段（page_design）

Story 决定研究问题、论证顺序、科学结论和证据边界；页面设计决定**怎么把这些内容画出来、摆出来、带着观众看**。
RPA 之后交给独立子代理，完整读取 `work/page_design_task.md`、`work/page_design_prompt.json` 和
其中 `schema_path` 指向的 [page-design 1.1 Schema](../schemas/page-design.schema.json)。设计提示不提供
编译器 forms / devices / type_scale 清单；设计者可以选择视觉形式，IR 作者负责翻译为实现能力。

```json
{"schema_version":"1.1","deck_id":"example",
 "setting":{"audience":"有领域基础、未读本文的研究生","occasion":"group-meeting","reading":"spoken"},
 "pages":[{"id":"P3","content_refs":["S2.answer"],
   "figures":["images/<实际检查过的资产>.jpg"],
   "design":{
     "composition":"左侧以器件原图为主，右侧按材料上下顺序排列功能标签，标签与图层用细线对应。",
     "drawing":"沿用原图；只加对应线与材料标签，少量黄色突出材料名，不把器件画成装饰卡片。",
     "walkthrough":"先指原图定位层次，再沿对应线逐层指出功能，最后指向电极。"}}]}
```

以上只是单页结构示意；实际文件须覆盖完整 Story。`design` 的对象键是示例，**不是必填清单**。
可查看 [独立子代理生成的 10 页实际样例](../examples/page-design-v11/README.zh-CN.md) 与
[本次验证记录](../../docs/agent-page-design-validation.md)；该样例未声明完成幻灯片布局验收。

- 每页只必填 `id`、`content_refs` 和 `design`。`content_refs` 使用提示包 `content_catalog` 中的
  Story 路径，正文与 evidence 自动继承，无需重写 claim / items / anchor 理由 / rationale。
  开场等纯组织页可用空引用；Story 的每个 answer、key_point、ending 仍须恰好分配到一页。
- `design` 可以是自由文本或自定字段对象，按页面需要说明原图、图形元素、箭头及关系、图标用途、
  公式标注、对照方式、相对排布、视觉层级和讲者指向顺序。不要止于“解释机制”，也不要再抄一段 Story。
  没有统一卡片、三栏、图标数量或字段模板。
- `figures` 可选，但选用原图时列出精确 asset_id；先实际检查路径基于 `workflow_root` 的图像，
  保留比例、图号及来源。IR 检查选图不得丢失。图标和示意不得增添科学主张，数据图不得猜点。
- `title` 和 `marks` 可选；title 的数值仍要有继承的证据，marks 必须来自本页所分配 Story 或 title。
  新的科学数据、外部知识或因果解释不由设计阶段发明，证据缺口回报上游。
- `setting` 简述 audience / occasion / reading，沿用请求，无需重新分析听众。
  occasion 取 `group-meeting` / `research-report` / `research-sharing` / `lecture` / `commercial`，
  reading 取 spoken / read / mixed。
- 校验保留唯一页 ID、完整且唯一的内容分配、已知证据、已知选图、显式页数目标（未指定最多 40 页）。
  自由绘图说明中的布局数字不作为测量数据；其科学忠实性仍须人工核对，并由下游 IR 证据与图形 QA 复核。
  ending 的证据自动继承 Story 节点证据的并集，仅为收束内容提供溯源，不是新结果。
- IR 提示包完整保留自定设计字段；运行时从原 Story 派生内部内容绑定，不把副本写回设计文件。
  IR 保留页序、分配、证据、数字、选图和视觉关系，实现设计指定的元素与构图；不能改成文字摘要。
  空间不足时回报实际容量，回退页面设计，不删内容或缩字号。
- 旧 `schema_version=1.0` 的 claim/items/anchor/shape/form/devices 继续兼容，不要求迁移旧任务。
  这些是旧协议；新任务默认 1.1，不再强制设计者重复科学策划。

以下是 IR 阶段可选的构图（`design_forms`）。新设计表不写编译器键名：IR 作者按每页的 `design` 选择能实现设计的构图。

| 形式 | 锚点 | 渲染为 | 适用 |
| --- | --- | --- | --- |
| cover | none | 封面页（标题 + 一句定位，无页脚无页码，items 可为空） | 开场 |
| spec-table / comparison-table | table | 原生表格 | 并列条件、参数、对比 |
| equation-reading | formula | 公式 + 读法栏 | 算子、定义、更新式 |
| mechanism-flow | graphic | 原生流程/DAG + 一行注 | 有顺序或分支的机制 |
| figure-reading | figure | 图 + 读数面板 | 论文图就是论点 |
| three-limits | number | 三列（可带小标题） | 并列边界 |
| statement | none | 一句主张放大成主句 + 1–2 条注；可设 `type_scale="statement"` 让数字到 88 px | 一页就是一句话 |
| text-columns | none | 2–3 组短陈述并排（可带 chip 标签） | 平行短内容，没有表可依 |
| numbered-points | none | 带 01–0N 标签的并列要点 | 两到四条并列要点 |
| problem-route-result | graphic | 三节点机制图（问题 → 做法 → 结果，边上带条件）+ 文本带 | 三段式论证，没有现成图 |
| chart-reading | graphic | 原生折线 / 柱状 / 散点图（坐标轴、误差棒、标注、出处） | 数字在正文/表格，曲线说明趋势 |
| text-stack / closing-statement | none | 兜底堆叠 / 单句结论 | 只有一两句、无法分组时 |

视觉语言另由 `presentation.visual_style` 选择风格包（`academic`/`commercial`/`print`），见
[视觉风格包](visual-style.md)。

Deck IR 还接受两个 authoring shorthand，在 schema 校验前展开为 canonical IR：

```json
{"id":"eq1","latex":"S_{\\lambda}(z)=\\operatorname{sign}(z)\\max(|z|-\\lambda,0)"}
```

等价于 `component:"formula"` + `text`；正文、标题或 takeaway 中的 `$...$` / `\\(...\\)`
会自动打开已有行内公式路径。简单流程可写：

```json
{"diagram":{"id":"proximal-flow","nodes":[
  {"id":"grad","title":"梯度步"},{"id":"prox","title":"近端步"},{"id":"next","title":"新迭代"}]}}
```

它展开为 `composition.graphics` 的一个原生 `process` 图，自动串链。复杂 DAG、机制图、架构图
仍按 `composition.graphics` 的完整 schema 写；shorthand 只降低常见补充图的输入成本，不改变编译器、
QA 或证据契约。展开后的 IR 会写回 `work/deck_ir.json`，Design/Build 只读 canonical 版本。

start 不收模型字段。在 model_selection 暂停点使用用户本轮或此前的明确选择回填：

```json
{"model":"<用户选择的准确模型>","reasoning_effort":"high","selected_by_user":true}
```

reasoning 支持 high / xhigh / max / ultra。Story 的 planner 必须匹配提示包 delegation；
仍需由宿主真实调用独立子代理，字段校验不能证明模型真的被调用。
测试中的 test-model / 固定 Story 只是 fixture，不能冒充生产 provenance。

阶段与路由见 [stages.json](../agent/stages.json)。每次读取 next_action：

- author_artifact / invoke_subagent：按完整提示和 schema 写 expected_output，用 artifact_kind / artifact_path 提交。
- provide_input：沿用或询问用户选择，传 advance.inputs。
- replan：读取反馈，按 target_stage 修订；必要时显式 replan_from 清除该阶段及下游 checkpoint。
- resolve_dependency：按 remedy 处理环境后 advance。未知错误保留脱敏日志路径。
- review_required：处理具体 FAIL 或修订上限；不能用 acknowledgement 消除 FAIL。
- none：若 status=running / reason=ADVANCE_REQUIRED 则 advance；CANDIDATE_READY 才交付候选。

默认候选允许 REVIEW，返回全部 QA 计数和 unacked_count。真实复核后可传
`acknowledge: {reviewer, note, review_ids}`，复用[候选逐项签收](complex-page-qa.md)。
正式 final 仍使用原 `record-powerpoint-review / validate-native / promote` CLI；接入层不暴露或执行它们。

## CLI 与提示包

在 Total-pipe 目录执行：

```bash
python -m agent doctor --json
python -m agent doctor --deep --json
python -m agent start --source /abs/deck_ir.json --out-dir /abs/output \
  --language zh --presentation-type group_meeting
python -m agent status --job-id <job-id>
python -m agent status --job-id <job-id> --detail full
python -m agent advance --job-id <job-id> --artifact-kind story_plan \
  --artifact-path /abs/output/work/story_plan.json
python -m agent advance --job-id <job-id> --inputs /abs/selection.json
python -m agent serve
```

`python -m agent setup` 返回安装器位置。IR 提示由接入层准备：

```bash
python -m agent ir-prompt --workflow /abs/workflow.json --rpa /abs/rpa_input.json \
  --normalized /abs/normalized_content.json --plan /abs/deck_plan.json --out /abs/ir_prompt.json
```

上面的 CLI 供显式导入外部 RPA 计划使用，保留完整 workflow/content model/plan。默认四工具在 RPA
规范化后只写编译契约、真实 catalog/schema 和 content_paths；页面设计通过后，ir_prompt_designed
补齐完整设计、Story、证据与图片。原始科学内容保存在对应输入文件，不重复内联多份。没有新增
`deck_compiler ir-prompt` 命令。显式低层 RPA 模板路径的业务参数须写在 plan_input.json，不能把
`--file` 后的命令行参数当成合并成功。
slide_count 不与 Story briefs 数量比较；例如 9 个论证节点、11 个 briefs 可以设计为 22 页。
设计提交时用 PAGE_DESIGN_INVALID 报告页数目标不符；IR（包括已有 IR 导入）在 build 之前用
SLIDE_COUNT_MISMATCH 拒绝目标不符。内容合并仍校验每条完整 body/key_points 与 EV，设计路径继续
检查唯一覆盖、数字溯源及逐页实现；布局的字号、图片与图形尺寸门禁不变。

## 局部修补与布局预检

deck_ir / build / candidate_ready 且已有 `work/deck_ir.json` 时，回复的 `repair` 提供两个当前哈希、
patch Schema 路径和建议输出路径。完整读取 [patch Schema](../agent/schemas/deck-ir-patch.schema.json)；
布局树沿用 [Deck IR layout-tree](../schemas/deck-ir.schema.json) 定义。例如：

```json
{"schema_version":"1.0","mode":"preflight",
 "base_ir_sha256":"<repair.base_ir_sha256>","base_resources_sha256":"<repair.base_resources_sha256>",
 "asset_updates":{"existing-asset-id":{"path":"source_crops/reviewed.png"}}}
```

```bash
python -m agent advance --job-id <job-id> --artifact-kind deck_ir_patch \
  --artifact-path /abs/output/work/deck_ir_patch.json
```

- `mode=preflight` 调用现有 compiler/packer 测量，禁用自动内容修复，不写 PPTX、不改 canonical 或候选。
  这是已有 IR 的修补预检，不是从设计 prose 猜测坐标。独立结果在 work/repairs 下，不能当最终 QA。
- `mode=apply` 再核对基线和替换资源，在预检通过、canonical 原子写入成功后才失效 IR 下游并恢复正常
  构建。最终 PPTX 仍整套写入、完整结构 QA；没有宣称逐页 OfficeCLI 重编译或原生验收已完成。
- asset_updates 只允许既有 asset 的 path；路径相对 patch 文件。图片必须实际可读，尺寸由图片取得。
  origin/source_figure 等来源元数据保持原样；像素变化不能由程序证明科学等价，必须重新检查论文图。
- slide_updates 为 `[{id,layout_tree}]`；不能改页序、页数、semantic、blocks、数据、theme 或字号门槛。
  布局树必须完整引用内容；可见 panel 标题及其叶子内容归属保持不变，不能把 Treatment 数据换进 Control。
  科学内容、分组或出处修订使用完整 IR 和正常重规划。
- 双哈希绑定当前 IR、图片、声明/解析的主题字体与编译器代码；测量和接受时再次核验字节。过期输入
  返回 PATCH_STALE，不应用补丁。预检或 canonical 写入失败保留旧候选、QA 与 checkpoint。
- 同基线/同补丁（含图片字节）的既有几何拒绝复用仍存在的反馈；资源/代码改变或反馈丢失会重新检查。
  每个基线最多三次不同的内容/几何拒绝，重复不计次。依赖异常不缓存、不耗预算，可恢复后重试。
  预算耗尽转完整 IR 重规划。同一已接受补丁重提不重复构建，并可继续中断的下游组件。
- repair_result 给 changed_slide_ids、实测图片尺寸、反馈路径和状态。拒绝调用返回 blocked；后续 status
  仍可报告未变的旧候选，并保留 last_repair，不能把它当作本轮修复成功。预检通过后 OfficeCLI 构建仍可能
  因运行环境失败，按原构建反馈恢复；接受补丁不等于候选验收。
- 没有自动签收 REVIEW；已有候选签收仅按原来的页面/资产签名规则复用，改变的页面需重新复核。
  正式 final 仍要求完整 PowerPoint 原生验收。

## 原生 PowerPoint 验收接入

候选后的回复新增 `native` 描述，含完整 `schema_path`、当前 staging 与 layout 的 SHA-256、
全部 `slide_ids`、`required_checks`、预览路径与验收状态。四工具数量不变；向 advance 的 `native`
字段提交一个操作，不能同时提交 artifact、inputs、replan 或 acknowledge。CLI 对应
`python -m agent advance --job-id <job-id> --native /abs/native-operation.json`。

先完整读取 [native Schema](../agent/schemas/native-acceptance.schema.json)。所有操作都绑定回复中的
`artifact_sha256` / `layout_sha256`；不使用旧候选的哈希。以下哈希占位符应替换为当前实际值：

```json
{"operation":"render","artifact_sha256":"<当前 staging SHA-256>","layout_sha256":"<当前 layout SHA-256>"}
```

`render` 用 Microsoft PowerPoint 导出现有 staging 的私有字节副本，检查 PDF 并回写 QA，
不重新运行 Story、page_design、Design 或 OfficeCLI。它不操作已打开用户文档的保存状态。
成功后 `checks.native=true`，尚未直接眼检时 `checks.visual_review=false`；这两项分别报告。
macOS 使用系统或用户 Applications 中的完整 PowerPoint.app 路径加载 AppleScript 术语，避免按名称
或 bundle ID 查找命中不完整的应用字典；路径仅用于选择程序，文稿/输出路径仍通过参数传入。
导出前检查实际打开文稿的完整路径；已打开的输入或不匹配的活动文稿会被拒绝，不关闭用户文稿。
宿主还须允许 Apple Events/LaunchServices（Windows 为 COM）；受限 shell 即使能读到 app 也可能
无法发出原生自动化请求，此时用已授权的 GUI 宿主执行，或通过下面的手动导出路径接入。
已有有效原生 PDF 时重复调用复用导出；可选 `force:true` 强制再次导出。锁屏、自动化权限或文件访问
弹窗导致失败时，解锁/授权后重试，或使用下面的 UI 导出接入。没有备用渲染器冒充 PowerPoint。

每页 PNG 来自实际 PowerPoint PDF 的栅格化。`build/native_preview.json` 绑定 PPTX/PDF 与各预览文件
哈希；`native-preview/<id>/pages.html` 可逐页查看，另有 contact sheet。预览缺失时重试 render 只
重新栅格化现有 PDF。预览依赖失败在 `native_result.preview_error` 中报告，原生 PDF/QA 仍保留，
不能声称已完成图片眼检。PNG/PDF 检查不等于直接检查 PowerPoint 可编辑页面。
坏 PDF 的解析失败返回结构化 native failure（含 error_type），不附加原生证明；已验证 PDF 的可选
预览解析/栅格化异常只记录 preview_error，可修复依赖后重试。宿主取消仍正常传播，不改写成成功。

实际在 PowerPoint 中逐页查看当前 staging，核对图与图注、科学面板可读性、文字截断/重叠和字体后，
提交明确的审核者、说明、全部实际页 ID 和检查项；不接受 `all` 代替逐页 ID：

```json
{"operation":"review","artifact_sha256":"<当前 staging SHA-256>","layout_sha256":"<当前 layout SHA-256>",
 "reviewer":"<实际审核者>","note":"<实际逐页复核范围和发现>","method":"powerpoint-ui",
 "reviewed_slide_ids":["<实际页 ID 1>","<实际页 ID 2>"],
 "checks":["figure_caption_alignment","scientific_panel_readability","text_overflow_and_collisions","font_rendering"]}
```

只记录实际完成的检查；该声明由调用者负责，接口不会替调用者打开页面并判断科学内容。PowerPoint
页面若有未保存修改，应先回到 canonical IR 修订/重建，不能对与磁盘 staging 不同的画面签收。
`review` 可在 render 前或后执行；已有当前 PDF 时会更新 QA 中的 UI review 绑定。
这不自动签收任何科学 REVIEW，也不创建 final。

自动导出不可用时，在同一次控制流程中从当前 staging 手动导出 PDF。实际逐页 UI 检查并提交
review 后，用以下操作接入；`source` 是调用者对真实来源的明确声明，不能由 PDF 文件扩展名推断：

```json
{"operation":"ingest","artifact_sha256":"<当前 staging SHA-256>","layout_sha256":"<当前 layout SHA-256>",
 "reviewer":"<与 UI review 相同的审核者>","pdf_path":"/abs/powerpoint-export.pdf",
 "pdf_sha256":"<该 PDF SHA-256>","source":"powerpoint-export"}
```

页数、文字区域、原生字体及结构检查会重新运行；新的 FAIL 必须修复。
若当前 FAIL 全部来自 native-visual（例如错导 PDF 页数），可用 force render 或经过相同 UI 约束的
ingest 换入正确 PDF 并重新验证；只有新检查不再失败才解除阻断。review、非强制缓存复用及任一
非原生/无来源 FAIL 均不能走此恢复路径，不修改字号或科学门禁。
原生 PDF 被删除/改变时，
status 标记 `NATIVE_EVIDENCE_STALE`，可 render 恢复而不重建 PPTX。过期/缺失的 PPTX、IR 或布局仍
要求重建。失败调用保留 `last_native`；后续 status 可能仍报告旧候选，不能把它当成本轮验收成功。
原生动作不消耗科学产物修订次数；本地区间以 `native_render/native_review/native_ingest` 记入事件。

`native.status` 区分 awaiting_native_render / awaiting_powerpoint_review /
awaiting_review_acknowledgements / accepted / qa_failed。accepted 仅表示当前原生步骤及候选 REVIEW
已完成，**正式晋级仍使用原 CLI promote 及其文件绑定 acknowledgement**，不由 advance 自动晋级。
低层 CLI record-powerpoint-review / validate-native 保持兼容；需通过 Agent 恢复的 job 建议使用上述操作，
以同步 QA checkpoint，避免把正常 QA 更新当成源文件改动。

## 执行耗时记录

`logs/events.jsonl` 追加保存每轮运行事件，旧事件不被下轮构建覆盖。每行是 schema_version=1 的 JSON，
含 UTC timestamp、event、job_id、stage；执行区间另有 span_id、operation、status 和终态 duration_ms。
stage_started / stage_finished 覆盖导入、提交验收、提示准备和组件执行；component_started /
component_finished 记录子进程调用。waiting、blocked、replan_requested 与 job_created/job_resumed
记录暂停、失败与恢复时间点。组件 `logs/<name>.json` 仍保存最后一轮脱敏输出，新增 started_at /
finished_at / duration_ms；各轮耗时从 JSONL 追溯。

duration_ms 测量本地执行区间，不代表宿主模型的生成时间。waiting 到提交之间还可能包含用户、网络或
队列等待，不能全算模型耗时；父 stage 与子 component 区间会重叠，统计时不要直接相加。
事件采用固定字段，不记录提示正文、argv、模型私有推理或密钥。status 不追加事件；只有 start/advance
与实际组件调用写事件。未完成的 started 区间可识别为中断，不能当作成功。

## 恢复与文件边界

- out/.totalpipe/job.json 存请求、指针、用户选择与 checkpoint；out/build/state.json 仍由编译器拥有。
- registry 位于 `TOTALPIPE_AGENT_HOME/jobs/`，默认 `~/.local/state/total-pipe/jobs/`。只存输出目录，重启后可按 job_id 继续。
- job 和 registry 原子写；OS 文件锁冲突返回 JOB_BUSY，进程退出释放锁。
- Agent 产物须是 work 内的真实文件，拒绝越界、`..` 和 symlink；组件证据包留在 evidence，输入包不搬目录。
- 每次重新校验实际文件哈希、资源与上游依赖；缺失、改动、接入层源码 / 阶段表或 Git 版本变化使相应下游失效。
- 依赖重试成功后清除旧失败；上游变化后，status 不再返回已经失效的诊断。
- 相同提交不增加失败次数，仍继续未完成组件；状态查询不计次。被拒绝的不同 Agent 提交才消耗修订预算。
- job 损坏返回 JOB_STATE_INVALID，按记录修复或换新输出目录；不从文件猜回模型授权。
- adapter 超时会终止所启动的进程树；日志写 logs 并屏蔽当前环境的 token/key/password 等值。

doctor 的 can_native_final 仅说明依赖就绪，不能当作 PowerPoint 验收结果。
MinerU token / CLI 就绪不能证明云认证有效；缓存登录无法确认时报告不确定，并允许实际 OCR 返回诊断。
字体、OCR 和 PowerPoint 不在所有机器上可用；能力与实际原生验收分别报告。

## 历史实施验证（2026-10-25）

以下只记录当时提交的验证，不代表后续源码的当前测试数量或耗时基准。

在 macOS、Python 3.12.12、Node.js 24.20.0、OfficeCLI 1.0.158 上执行：

| 验证 | 结果 |
| --- | --- |
| Total-pipe 主测试套件 | 384 项通过，包含 39 项接入层测试，无 skip |
| pwf2rpa | 83 项通过 |
| RPA | 316 项通过 |
| PaperWorkflow | 38 项通过；1 项因缺少 Li Markdown fixture 跳过 |
| 干净 venv 安装与真实 stdio 握手 | 默认 4 工具；advanced 三服务合计 41 工具；重复配置、profile 回切和 Claude launcher 已验证 |
| 实际候选闭环 | 已有 IR，以及合成 Markdown → PWF → RPA → IR → Design → OfficeCLI，均到零 FAIL 候选 |
| 文档与 Skill | 本地链接无缺失；轻量 Skill 43 行，格式验证通过 |

Markdown 测试的 Story / IR / 视觉提案为明确标注的测试产物，未调用真实 Story 模型。
安装验证仅使用临时客户端配置；deep doctor 实际创建、关闭并校验临时 PPTX。
本次未执行云 PDF OCR、Windows 锁 / 进程树路径或 PowerPoint UI / 原生 PDF / final 晋级。
该历史验证中的 doctor 仅检测到 PowerPoint 与字体、未验证 MinerU 认证；当前 PDF doctor 的官方认证探测见上文。
依赖检测或认证验证均不计为 PowerPoint 原生验收。
