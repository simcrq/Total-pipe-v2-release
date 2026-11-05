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
| totalpipe_advance | job_id；可提交 artifact_kind / artifact_path，回填 inputs，或指定 replan_from / acknowledge |
| totalpipe_status | job_id；可选 detail=summary/full，默认紧凑回复；只读，不执行组件或准备提示包 |

start / advance / status 默认返回阶段、next_action、QA 摘要、out_dir、state_path、events_path 和
artifacts_summary（引用数、去重文件数与阶段名）。完整请求与逐文件哈希不重复塞入每次回复；
需要时调用 `totalpipe_status(job_id, detail="full")`，返回原 request 与 artifacts 清单。
自动化若依赖这两个字段，应显式选择 full。状态查询不改写 job、提示包、反馈或事件日志；提示缺失时
返回 ADVANCE_REQUIRED，由 advance 准备完整提示。Agent 仍必须完整读取 next_action 指定的提示包和 Schema。

`presentation_type` 支持 RPA 的 group_meeting / journal_club / proposal / progress_report / defense /
paper_presentation / custom。入口将“组会”“研究生组会”“group-meeting”规范化为 group_meeting，
research-sharing / 文献分享为 journal_club，research-report / 科研汇报为 paper_presentation。
lecture / 讲课与 commercial / 路演使用 custom 的 RPA 规划，同时在 presentation_context 保留原场合。
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

**Story 不为 RPA 槽位缩短科学内容。** RPA 只规划它当前能容纳的页面；若仍有完整 brief 无法规划，
`rpa_validation.status=partial`，`unplanned_slide_briefs` 留在原始 IR 提示包。页面设计在目标页数内为完整
内容安排拆分或合并；IR 逐页实现已通过设计，优先 `composite-research` + `layout_tree`。空间不足回退
页面设计；不能靠删句、缩写术语或把听众理解所必需的证据藏进 notes 通过。

### 页面设计阶段（page_design）

RPA 之后、Deck IR 之前有一个 `page_design` 阶段：Agent 先交一份**页面设计表**，再写 IR。
设计表只写决策，不写坐标；**也不写形式或组件**——设计者不需要知道这套编译器的能力，只需要想清楚
每一页要让读者看到什么：

```json
{"schema_version":"1.0","deck_id":"<id>",
 "setting":{"audience":"同组同行，已熟悉二维器件与浮栅存储","occasion":"group-meeting",
            "reading":"spoken"},
 "pages":[
  {"id":"P1","from_story":["S1"],"role":"setup","claim":"基准为 N=512、K=50。",
   "takeaway_from":"S1.answer",
   "items":[{"id":"p1-a","text":"N=512、K=50","source":"S1.key_points[0]","evidence":["EV0001"]}],
   "anchor":{"kind":"table","why":"条件并列"},
   "figures":["images/0bb7ce79….jpg"],
   "shape":"两张条件并排，数字比标签大两档；读者先看到 512，再看到 K=50 的对照",
   "marks":["K=50"],
   "rationale":"组会同行的条件页，两个数字要能同时被查到"}]}
```

**执行方式**：与 Story 一样交给独立子代理，不主 Agent 代写。RPA 完成后接入层写出两份文件：
`work/page_design_prompt.json`（Story、briefs、证据、可用图、场合与输出 shape）与
`work/page_design_task.md`（任务书）。主 Agent 把这两份交给子代理，收回子代理写的
`work/page_design.json` 再 advance。提示里**没有 forms / devices / type_scale / visual_style**：
设计是能力无关的，选形式是 IR 阶段的翻译工作。

`setting` 是必填的**场合与对象**：`occasion` 从五个键里选一个——`group-meeting`（组会）、
`research-report`（会议/答辩）、`research-sharing`（文献分享/journal club）、`lecture`（讲课）、
`commercial`（商业路演）；`audience` 写听众是谁、已经知道什么；`reading` 写页面是讲者口述
（`spoken`）、听众自读（`read`）还是两者兼有。它不直接产生版面，但决定密度与页面形态：同一篇论文在
这五种场合里可以合理地长成五套不同的页。缺 `setting` 或 `occasion` 不在键里会报
`PAGE_DESIGN_INVALID`；`room.default_occasion` 是接入层按 `presentation_type` 与 brief 猜的默认值，
设计者可以改。

- `anchor` 是**这页围绕什么对象**（figure / table / formula / number / none），是内容事实，不是能力。
- `shape` 是一两句设计交代：读者看到什么、什么大、眼睛先落在哪、什么并排、空白怎么用。**必填**
  （或给旧的 `form`，向后兼容）。
- `marks` 是这页承载主张的短语；IR 阶段把它们落成文字标记，不需要设计者知道“强调设备”叫什么。
- `figures`（可选）列出这页要用的资产 id。设计者按图号认面板，IR 只拿到 hash；这一列是两者之间
  唯一的对应关系，没有它就只能由 IR 猜。
- 校验只看内容不变式（`PAGE_DESIGN_INVALID`）：Story 的每个 answer/key_point/ending **只属于一页**
  （同一页可被多个 item 引用展开，跨页重复才会报错）；evidence id 必须存在；条目与 claim 里的数字必须
  出现在所引 evidence 中（`kind=formula` 的定义式除外；证据里的 `$95.8\%$` 与条目里的 `95.8%` 视为
  同一个数）；`marks` 必须是这页文本里出现过的短语。页数可少于 brief 数（合并）或多于（拆分），
  显式 slide_count 校验最终论文页目标；不再按 Story 节点数乘倍数限制页数。
- 通过后，IR 提示包会带上 `page_design`（含 `shape`、`marks`、`anchor`）与"逐页实现、不得重新设计"的
  指令；IR 作者从 `design_forms` 里选择最能实现该 `shape` 的构图。IR 交回时按设计校验
  （`DESIGN_REALIZATION_FAILED`）：页数一致、每页保留设计声明的 evidence、设计页上的数字不能丢。
- 有设计表时，`check_ir` 不再做"逐字保留 brief 原文"的比对——设计表已经是溯源记录；没有设计表的
  旧路径行为不变。

以下是 IR 阶段可选的构图（`design_forms`）。设计表不写这一列：IR 作者按每页的 `shape` 与 `anchor`
选择最能实现它的形式。

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

正常流程在 RPA 成功后自动生成同一个提示包。它包含完整 workflow、原始 content model、完整 plan、
真实 catalog / 能力 / schema 及素材根。没有新增 `deck_compiler ir-prompt` 命令。
RPA 的业务参数写在 plan_input.json；不能把 `--file` 后的命令行参数当成合并成功。
slide_count 不与 Story briefs 数量比较；例如 9 个论证节点、11 个 briefs 可以设计为 22 页。
设计提交时用 PAGE_DESIGN_INVALID 报告页数目标不符；IR（包括已有 IR 导入）在 build 之前用
SLIDE_COUNT_MISMATCH 拒绝目标不符。内容合并仍校验每条完整 body/key_points 与 EV，设计路径继续
检查唯一覆盖、数字溯源及逐页实现；布局的字号、图片与图形尺寸门禁不变。

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
doctor 检测到 PowerPoint 与字体，MinerU 认证仍报告未验证，不把依赖检测计为原生验收。
