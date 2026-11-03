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
| totalpipe_doctor | 可选 deep / source_kind；报告 12 类环境检查与阶段能力 |
| totalpipe_start | source、out_dir、language、presentation_type；可选 source_kind、requirements、queries、slide_count、supplementary_paths、supplementary_content_included、supplement |
| totalpipe_advance | job_id；可提交 artifact_kind / artifact_path，回填 inputs，或指定 replan_from / acknowledge |
| totalpipe_status | job_id；只读取实际哈希和状态，不执行组件 |

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
`slide_count` 仍按 RPA 论文 brief 计，补充页是额外页。

**Story 不为 RPA 槽位缩短科学内容。** RPA 只规划它当前能容纳的页面；若仍有完整 brief 无法规划，
`rpa_validation.status=partial`，`unplanned_slide_briefs` 随 IR 提示包下发。IR 必须为这些 brief
补页或拆页，优先 `composite-research` + `layout_tree`，保留完整 body/key_points 和 EV；不能靠删句、
缩写术语或把内容藏进 notes 通过。

### 页面设计阶段（page_design）

RPA 之后、Deck IR 之前有一个 `page_design` 阶段：Agent 先交一份**页面设计表**，再写 IR。
设计表只写决策，不写坐标：

```json
{"schema_version":"1.0","deck_id":"<id>",
 "devices":{"sections":[{"page":"P1","label":"背景"}],"agenda":{"title":"目录"},
            "footer":"组会报告","page-numbers":true},
 "pages":[
  {"id":"P1","from_story":["S1"],"role":"setup","claim":"基准为 N=512、K=50。",
   "takeaway_from":"S1.answer",
   "items":[{"id":"p1-a","text":"N=512、K=50","source":"S1.key_points[0]","evidence":["EV0001"]}],
   "form":"spec-table","anchor":{"kind":"table","why":"条件并列"},"rationale":"表格比句子更好查",
   "devices":{"emphasis":["K=50"],"takeaway-frame":"fill","panel-group":["条件","边界"]}}]}
```

**执行方式**：与 Story 一样交给独立子代理，不主 Agent 代写。RPA 完成后接入层写出两份文件：
`work/page_design_prompt.json`（约 40 KB：Story、briefs、证据、可用图、forms 与 devices 清单、输出 shape）
与 `work/page_design_task.md`（任务书）。主 Agent 把这两份交给子代理，收回子代理写的
`work/page_design.json` 再 advance。提示是**能力清单**——每个形式与设备买来什么、放不下怎么退化——
不是规则清单；设计层按这场报告的需要选择，不要为了稳妥而不用。

- `forms` 是一份封闭的形式库（下表由 `deck_compiler.design.capabilities()` 发布），每个形式对应一个
  编译器能渲染的构图；`anchor` 必须与形式一致（表格页不能声明图作锚点）。
- `devices` 是设计层设备（见 [设计层设备清单](art-direction.md)）：页级 `emphasis` / `highlight` /
  `panel-group` / `caption-source` / `takeaway-frame` / `sequence-rail`；篇级 `sections` / `agenda` /
  `footer` / `page-numbers`。每项都有退化路径，所以选它不会让构建失败。
- 校验只看内容不变式（`PAGE_DESIGN_INVALID`）：Story 的每个 answer/key_point/ending **只属于一页**（同一页可被
  多个 item 引用展开，跨页重复才会报错）；evidence id 必须存在；条目与 claim 里的数字必须出现在所引
  evidence 中（`kind=formula` 的定义式除外；证据里的 `$95.8\%$` 与条目里的 `95.8%` 视为同一个数）；
  页数可以少于 brief 数（合并）或多于（拆分），但不能超过两倍。设备只校验形状
  （名字在清单里、取值个数与长度），**不判断它在页面上会占多少空间**。
- 通过后，IR 提示包会带上 `page_design`（含 devices）与"逐页实现、不得重新设计"的指令；IR 交回时按设计校验
  （`DESIGN_REALIZATION_FAILED`）：页数一致、每页保留设计声明的 evidence、设计页上的数字不能丢、
  设计点名的设备必须出现在页面上。机械类设备（标记、图注出处、结论框、章节、目录、页脚、页码）由编译器
  在 IR 校验前直接写进 IR，作者漏写也不会丢；结构类（`panel-group`）由 IR 自己搭 panel。
- 有设计表时，`check_ir` 不再做"逐字保留 brief 原文"的比对——设计表已经是溯源记录；没有设计表的
  旧路径行为不变。

| 形式 | 锚点 | 渲染为 | 适用 |
| --- | --- | --- | --- |
| cover | none | 封面页（标题 + 一句定位，无页脚无页码，items 可为空） | 开场 |
| spec-table / comparison-table | table | 原生表格 | 并列条件、参数、对比 |
| equation-reading | formula | 公式 + 读法栏 | 算子、定义、更新式 |
| mechanism-flow | graphic | 原生流程/DAG + 一行注 | 有顺序或分支的机制 |
| figure-reading | figure | 图 + 读数面板 | 论文图就是论点 |
| three-limits | number | 三列（可带小标题） | 并列边界 |
| statement | none | 一句主张放大成主句 + 1–2 条注 | 一页就是一句话 |
| text-columns | none | 2–3 组短陈述并排（可带 chip 标签） | 平行短内容，没有表可依 |
| numbered-points | none | 带 01–0N 标签的并列要点 | 两到四条并列要点 |
| problem-route-result | graphic | 三节点机制图（问题 → 做法 → 结果，边上带条件）+ 文本带 | 三段式论证，没有现成图 |
| chart-reading | graphic | 原生折线/柱状图（坐标轴、图例、出处） | 数字在正文/表格，曲线说明趋势 |
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
slide_count 与完整 Story briefs 数量冲突时要求改 Story，不截断 / 复制 brief。
补充页不计入 slide_count；IR 页数下界仍按论文 brief 检查。
IR 另校验完整 body / key_points、证据引用和页数下界，不能将多页内容塞成一页来消除容量问题。

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

## 本次实施验证（2026-10-25）

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
