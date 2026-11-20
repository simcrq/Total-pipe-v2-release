# TotalPipe 论文证据门禁与教学内容：架构评估

> 评估日期：2026-10-27　范围：当前工作区 `Total-pipe-v2-release`
> 性质：只读代码审查 + 最小可复现实验。本文是评估备忘，不是实现方案；未修改产品代码。
> 方法：对需求文档 §3.1–§3.5 逐条核验；用 12 组最小实验验证门禁的实际行为；评估方案 A/B/C 及两种轻量变体。

---

## 0. 结论摘要

1. **主诊断成立。** 当前管线把论文 Evidence 当作页面/节点的“准入令牌”，缺少教学内容的合法表示；§4.3 描述的 misbinding 风险是真实的，而且实验证明它今天就能发生。

2. **根因比文档写的更精确：证据检查是“引用存在性”，不是“主张蕴含”。** 一段教材文字只要挂上一个真实存在但无关的 `EV####`，就能通过 Story → pwf2rpa → RPA → Deck IR → 编译；实验 E2（Story→RPA）与 E10（IR→编译，`explanation_coverage` 显示 `satisfied`）分别在不同层验证了这一点。因此“严格证据门禁保护了论文事实”目前主要是名义上的：被禁止的是“没有 EV 标签”，不是“没有依据”。这决定了改造重点不应只是“开一个教学豁免”，而是让来源与验证状态真正有语义。

3. **硬门位置与文档略有出入。**
   - 真正阻断教学页的是 **Story/pwf2rpa**（节点和义务必须有 EV）与 **explanation 契约**（义务必须有非空 `evidence_refs`，连 `status=waived` 也不行）。
   - **RPA 与 Deck Compiler 已经接受无论文证据的页面**：`normalize-content` / `plan` / `validate-deck` 对 `evidence_ids: []` 的 brief 返回成功；空 `evidence_refs` 的 IR 可正常编译（E4/E5）。§3.4 “限制主要来自上游”的判断正确，且下游比文档预期更宽松。
   - §3.1 的 `EVIDENCE_NOT_READY` 是**论文输入质量门**，不会因为“教学页没有 EV”触发；保留它不与教学目标冲突。
   - §3.5 的 QA 误判真实存在，但 `quality_metrics` 是可选 CLI、MEDIUM 严重度、完整性只降 8 分（权重 0.15），**不在 build 验收链上**。影响被高估，但“用论文引用率定义完整性”这个定义错误应随教学页一起修正。

4. **只放宽 evidence 不足以得到自然教学叙事。** 还有一批文档未列出的约束会继续卡住教学页：4–10 个 Story 节点、`next` 必须是未解决科学问题（“接下来介绍……”会被判错）、首页固定映射到 `question` 类别（带流程的教学首页会容量告警）、封面/总结继承首末节点的 Evidence、Story prompt 明确要求 answer 只能由 Evidence 支撑。见 §3。

5. **建议不要直接把 Story 改成多来源（方案 B），也不建议马上新建重服务（方案 C）。** 推荐分阶段：
   - **Phase 0（0 代码）**：用 IR overlay 做教学页试点，先验证“教学页是否真的提升讲解质量”；
   - **Phase 1（低风险）**：在 Deck IR / explanation / QA 引入共享的 provenance 协议（来源类型、依据、验证状态、块级 basis），并加“反重贴标签”检测；
   - **Phase 2**：根据试点结果，在“Story 原生教学节点（B-lite）”与“可选轻量教学规划器（C-lite）”之间二选一。若教学是长期主场景，C-lite 更符合 §5.5 的模块化目标；若只是偶发需求，A + Phase 1 协议即可。

---

## 1. 逐条核验

| 文档断言 | 代码 / 实验证据 | 判定 | 备注 |
|---|---|---|---|
| §3.1 `synthesis_readiness.readiness == "ready"`，否则 `EVIDENCE_NOT_READY` | `Total-pipe/agent/adapters.py:284`、`:298`；readiness 取值为 `blocked/review/ready`（`PaperWorkflow/utils/literature_workflow.py:429-438`） | **成立，但相关度低** | 它拦的是论文证据提取质量，不是教学内容合法性；教学页无 EV 不会触发。文档把它列为“可能造成限制的机制”容易误导改造优先级。 |
| §3.2 每个 Story 节点必须有 `evidence`，且至少一个 `EV####`；`STORY_EVIDENCE_EMPTY` / `UNKNOWN_EVIDENCE_ID` | schema `Total-pipe/pwf2rpa/schemas/story-plan.schema.json:29,38-43`；运行时 `Total-pipe/pwf2rpa/pwf2rpa/story.py:616-636` | **成立，且 schema 更严** | 实验 E1：教学节点 `evidence: []` → `STORY_EVIDENCE_EMPTY`，exit 2。schema 要求数组内**每个**元素都匹配 `^EV[0-9]{4}$`，不只是“至少一个”。 |
| §3.2 叙事必须是“未解决科学问题”推进 | `story.py:638-651`（`STORY_NEXT_IS_SEQUENTIAL`）；节点数 `4–10` 在 `story.py:509-518`、schema `:22-25` | **成立，且比文档更严** | 实验 E7：`next="接下来介绍梯度下降的基本原理"` → `STORY_NEXT_IS_SEQUENTIAL`。即使放宽 evidence，教学过渡语仍会被拒。 |
| §3.3 每条 `explain.must_show` 必须绑定本节点 Evidence | `story.py:283-299`；`Total-pipe/deck_compiler/explanation.py:237-248`；IR schema `Total-pipe/schemas/deck-ir.schema.json:469,480` | **成立** | 实验 E3：义务无 `evidence` → `STORY_EXPLAIN_EVIDENCE_EMPTY`；实验 E6：IR 层空 `evidence_refs` → `EXPLANATION_INVALID` FAIL。 |
| §3.3 explanation 允许 `waived` 作为降级 | `explanation.py:249-252` 只要求 `note`，但 `:237-241` 仍先要求非空 `evidence_refs` | **部分不成立** | 实验 E6：`status=waived` + 空 refs 仍 FAIL。当前没有“合法豁免”的逃生口。 |
| §3.4 限制沿 pwf2rpa / RPA / IR 传播 | `story_to_specs` 写 `evidence_ids`（`story.py:832`）；封面取首节点（`:789`）；总结取末两节点（`:871-875`）；Agent 检查引用存在于 normalized store（`adapters.py:180-182`） | **成立，但下游可放宽** | RPA `normalize-content/plan/validate-deck` 接受 `evidence_ids: []`（E4）；编译器接受空 `evidence_refs`（E5）。真正的传播是“字段语义”，不是“下游校验”。 |
| §3.5 QA 对无论文引用页面报告 `No evidence citations on this slide` 并降分 | `Total-pipe/deck_compiler/quality_metrics.py:405-418`、`:447-460` | **成立，但严重度被高估** | 实验 E9：1 页无引用 → completeness 92（有引用 100），MEDIUM；`quality` 是可选用法，`Total-pipe/docs/QUALITY_METRICS.md:28-34` 明确它不是验收结论。 |
| §4.3 “错误绑定 Evidence 尤其危险” | 无蕴含检查；`STORY_CERTAINTY_ESCALATION_RISK` 只是词表启发式（`story.py:653-670`） | **成立，且是当前最大隐患** | 实验 E2：教材句“该算法按 A→B→C 三步执行”绑定 `EV0006`（原文只是“supplies a methodological detail”），pwf2rpa 生成 `evidence_texts`，RPA 规划成功，validate-deck 通过。 |

---

## 2. 当前门禁的真实分层

| 层 | 是否要求论文 EV | 粒度 | 关键代码 | 对教学页的实际影响 |
|---|---|---|---|---|
| PaperWorkflow | 否（它生产 EV） | 论文/查询 | `literature_workflow.py:429-438` | 只在 Agent evidence 阶段以 readiness 拦截；低层组件独立使用不受影响。 |
| Story schema / story.py | **是，硬错误** | 节点 + 每条 explain 义务 | `story.py:616-636`、`:283-299` | 无法声明纯教学节点；无合法豁免。 |
| Story 叙事规则 | 否（但约束叙事） | 节点序列 | `story.py:509-518`、`:638-651` | 4–10 节点；`next` 必须是科学问题；首页类别固定。 |
| Story prompt | 是（文本指令） | 回答 | `story.py:971-1009`，尤其 `:977-978` | 即使校验放宽，提示仍要求“只能由列出的 Evidence 支撑”。 |
| pwf2rpa 映射 | 是（复制字段） | 节点→brief | `story.py:789`、`:832`、`:871-875` | 封面/总结会继承教学节点的 EV；教学节点在首/末会污染溯源。 |
| RPA normalize/plan/validate | **否** | brief | 实验 E4；`research-ppt-assistant/server/core.mjs:658-666` | `evidence_ids: []` 可正常规划；但类别仍是研究汇报类（background/theory 等）。 |
| Agent `check_ir` | 仅当 refs 非空 | 页面 | `adapters.py:178-186` | 额外页面允许（页数只要求 ≥ brief 数）；空 refs 跳过存在性检查。 |
| Deck IR schema | 键必填，值可为空 | 页面 | `deck-ir.schema.json:508,517` | `semantic.evidence_refs` 必填但无 `minItems`。 |
| IR 运行时校验 | 否（但 explanation 内部要求） | 页面/义务 | `deck_compiler/ir.py:37-45`、`:191` | 手写校验，容忍未知字段（实验 E11）；explanation 走 `explanation.py` 的严格规则。 |
| Deck Compiler 其他阶段 | 否 | 页面 | 实验 E5 | 教学页可编译；生成示意图会得到 `SCHEMATIC_REVIEW`。 |
| QA / quality metrics | 部分 | 页面 | `qa_report` vs `quality_metrics.py` | `EXPLANATION_INVALID` 是 FAIL；完整性扣分是独立可选分析。 |

---

## 3. 文档遗漏的约束（只放宽 evidence 仍会卡住）

### 3.1 节点数 4–10

`story.py:509-518` 与 schema `:22-25` 都强制 4–10 个 Story 节点。教学 deck 若要“先修 → 直观 → 推导 → 例子 → 论文方法”，常常超过 10 个讲解单元；少于 4 个又无法成 deck。节点是“推理步骤”不是页，可以通过 `allow_auto_split` 拆页，但**不能有纯教学节点**，所以这个下限实际是“至少 4 个论文证据推理步”。

### 3.2 `next` 的教学过渡被当成错误

`STORY_NEXT_IS_SEQUENTIAL` 的正则是“然后/接下来/此外 + 看/讨论/介绍/作者/we/the authors”，并要求句子含 epistemic marker（`story.py:126-138`、`:638-651`）。教学叙事常用的“接下来介绍标准算法”“先看一个简化例子”会被判错。这不是 evidence 问题，放宽 evidence 不会自动解决。

### 3.3 首页固定 `question` 类别

`_category_for()` 在 `index == 0` 时无条件返回 `question`（`story.py:751-752`）。实验 E8：首页带 `ordered_steps`（A/B/C）时，`process_steps` 被写入 brief，但类别仍是 `question`，pwf2rpa 报：

```
[WARNING][CAPACITY_EXCEEDED] briefs[1]: no layout in category 'question' can hold this page:
3 process step(s) but only 0 process slot(s)
```

`--strict` 下 exit 3，Agent 适配层会把它当作失败（`adapters.py:316`）。教学 deck 的首页往往正是“背景/先修/总览”，这条硬映射会让最需要流程图的一页落到纯文字池。

### 3.4 封面/总结继承首末节点 Evidence

`first_evidence = plan["story"][0]["evidence"][:2]`（`story.py:789`）让封面继承第一个节点的 EV；总结取末两个节点（`:871-875`）。若教学节点在首/末，它的（可能是错绑的）EV 会扩散到封面/总结，进一步破坏溯源。实验 E2 中封面确实带上了 `EV0006`。

### 3.5 Story prompt 明确禁止无证据回答

`build_story_prompt()` 的指令写着“answer 是回答，只能由列出的 Evidence id 支撑；不得创造事实、因果关系或确定性”（`story.py:977-978`），并要求每个节点写 `explain`（`:987`）、每条义务绑定本节点 evidence（`:997`）。即使校验器放宽，子代理仍会按提示只写论文内容。**改协议必须同时改提示，否则行为不会变。**

### 3.6 Agent 错误分类掩盖真实原因

`check_story()` 把任何 `StoryError` 统一包成 `STORY_PROVENANCE_INVALID`（`adapters.py:153-156`），`classify()` 再映射为 `author_artifact/story`（`:35-37`）。教学节点被拒时，Agent 看到的是“provenance invalid”，会倾向于重写 provenance / 重试，而不是“这种 deck 类型当前不受支持”。诊断信息可用性差。

### 3.7 Schema 与运行时不是同一套

`story-plan.schema.json` 在仓库里只被 `pwf2rpa/README.md` 引用，**运行时不加载它**；真正的校验在 `story.py`。Deck IR 也不同：`deck_compiler/ir.py` 是手写校验（`ir.py:37-45`），对未知字段宽容（实验 E11），而发布的 JSON Schema 是 `additionalProperties: false`。这意味着：

- 只改 schema 不会改变行为；改 `story.py` 不改 schema 会造成文档漂移；
- IR 新增字段在运行时可能“悄悄通过”，但在契约/第三方校验器处失败；
- 兼容性评估必须同时看“运行时”和“发布的 schema”。

### 3.8 Skill / 文档与代码同构

`Total-pipe/skills/total-pipe-deck/SKILL.md:112`（`question/answer/evidence` 必填）、`:138`（每条义务绑定本节点 evidence）、`:215`（IR 带 `story_explain` 的 `evidence_refs`）；`docs/explanation-contract.md:51`（每条义务必须绑定本节点 evidence）；`pwf2rpa/README.md:120`（4–10 节点）。这些是 Agent 直接阅读的规范；只改代码会让 Agent 继续按旧契约创作。

---

## 4. 根因：三个轴被折叠成一个 `evidence` 数组

当前 `evidence: ["EV0007", ...]` 同时承担了三件事：

1. **叙事角色**：这是论文推理链的一步；
2. **内容来源**：这段话来自论文；
3. **验证状态**：它被“验证”了（实际上只是引用存在）。

教学页需要的是把这些轴拆开：

| 轴 | 取值 | 当前表示 | 教学场景需求 |
|---|---|---|---|
| 叙事角色 | reasoning / teaching / example / summary | 无（所有节点都是 reasoning） | 允许教学节点、例子节点 |
| 来源 | paper / external / derived / constructed | 只有 paper EV | 教材、标准、推导、构造示例 |
| 验证 | verified / unverified / review_required / conflict | 由“有 EV”隐含 | 明确标记待审核，不默认正确 |
| 粒度 | 页面 / 节点 / 主张 / 块 | 节点/页面 | 同页混合来源需要块级 |

代码里其实已有可复用的词汇，不必另造一套：

- `assets[*].origin: paper | generated | reference`，且 `generated` 在运行时必填 `generator`（`deck_compiler/ir.py:100-103`）、`reference` 必填 `reference_source`（`:104-107`）——这是“来源 + 条件字段”的现成范式（schema 的 `allOf` 只对 reference 编码了条件，generated 的检查在运行时）；
- `mechanism.edges[*].basis: evidence | hypothesis`，`evidence` 时强制非空 `evidence_refs`（`:355-364`）——这是“依据类型决定验证要求”的现成范式；
- `curve.content.schematic: true`（`story.py:279-282`）与 `SCHEMATIC_REVIEW`（实验 E5 实际出现在生成流程图页）——这是“示意内容必须显式标记”的现成范式。

因此，正确的方向不是“全局关闭证据校验”，而是把 `evidence: EV####` 升级为 `basis + source_refs + verification`，并让每种 basis 有自己的规则。**这比单纯放宽更严格，而不是更宽松。**

---

## 5. 方案评估

评分只针对本文档的目标（§5.1–§5.5）与验收表（§9），不考虑“未来可能想做别的”。

| 方案 | 场景 A（独立教学页） | 场景 B（同页混合） | 改动面 | 兼容/回归风险 | 可复用 | 结论 |
|---|---|---|---|---|---|---|
| A. Teaching Overlay | 可以 | **不行**（页面级） | 小 | 低 | 低 | 适合 1–2 天试点，不足以作为目标架构 |
| B. Story 原生多来源 | 可以 | 节点级可以，块级仍要额外协议 | 大（8 处） | 中高（动最敏感的 Story 校验） | 中 | 教学成为主场景时再考虑 |
| C. 独立教学规划层（完整服务） | 可以 | 取决于合并协议 | 最大 | 中 | 高 | 现在过早 |
| C-lite（提示 + schema + 合并函数，不做新服务） | 可以 | 需要块级协议 | 中 | 低 | 高 | **推荐作为 Phase 2 候选** |
| P. 只做共享 provenance 协议（IR/QA/explanation） | 可以（配合 overlay） | 可以（块级 basis） | 中小 | 低 | 高 | **推荐作为 Phase 1** |

### A. Teaching Overlay

**做法**：在 Story/RPA 之后，用独立 JSON 把教学页合入 Deck IR；不改 Story。

**优点**：
- 组件层今天就能做：编译器接受空 `evidence_refs`（E5），Agent 的 `check_ir` 允许 IR 页数 ≥ brief 数（`adapters.py:178-179`），额外页不会触发 content-loss（它只检查 brief 文本是否仍在 IR 中）；端到端 Agent 作业仍需实际跑一次确认。
- 可逆，适合做 A/B 质量实验。

**不足**：
- 页面级来源，无法表达同页“左侧论文结构图 + 右侧标准算法 + 下方构造算例”；而 §9 明确要求混合页。
- 教学页不经过 RPA 版式规划，布局质量取决于 Agent 手写 composition；复杂页容易撞容量（本次验证中给 `native-graphic` 增加 body block 即触发 `CONTENT_CAPACITY_EXCEEDED`，说明“图 + 文”混合页还要过 archetype 容量门）。
- 教学页无法声明 `explain`（除非改 explanation 契约），于是“必须画流程图/公式”的结构保证对教学页失效——这恰好是 §4.4 抱怨的“有能力却用不上”。
- 与 Story 叙事脱节，教学页像补丁；不满足 §5.4 的“自然递进”。

**判断**：试点可用，不能作为最终形态。

### B. Story 原生支持多来源

**需要动的点**（按依赖顺序）：

1. `story-plan.schema.json`：节点 `required`、`evidence` 的 `minItems`、`obligation.required`、`maxItems: 10`；
2. `story.py`：`_NODE_FIELDS` / `_OBLIGATION_FIELDS`、`_normalize_obligation`、`validate_story` 的 evidence/next、`story_to_specs` 的封面/总结/类别、`build_story_prompt` 的指令与 output_shape；
3. `pwf2rpa/README.md`、`docs/explanation-contract.md`、`SKILL.md`、`USAGE.zh-CN.md`；
4. `agent/adapters.py`：`check_story` 的错误分类、`check_ir` 的来源命名空间、`ir_prompt` 的 explanation 指令；
5. `deck_compiler/explanation.py`：`evidence_refs` 非空与 membership 检查；
6. `schemas/deck-ir.schema.json`：`semantic`、block、`explanation-obligation`；
7. `deck_compiler/quality_metrics.py`：按 basis 统计；
8. 测试与 fixture。

**优点**：一次规划同时完成“论文论证 + 教学递进”，最接近 §5.4；RPA 仍能规划全部页面。

**风险**：
- Story 是当前最敏感、最有价值的组件；把“科学论证”与“教学法”塞进同一个 prompt，可能降低论文 deck 的质量，且很难用单元测试发现。
- 必须同时解决 §3 的 4–10、`next`、首页类别、封面/总结继承；否则“允许多来源”仍会被这些规则卡住。
- 需要“反重贴标签”机制，否则 Agent 会把论文主张标成 `external` 绕过门禁。

**判断**：可行，但应在协议与试点验证之后；不建议作为第一步。

### C. 独立教学规划层

**做法**：新组件负责理解路径、先修知识、推导、示例；输出教学计划，再与论文内容合并。

**优点**：职责分离；PaperWorkflow 与 Story 保持独立；教学规划可复用于其他工具（符合 §5.5）。

**不足**：
- 两个规划器可能给出不一致的叙事；合并逻辑是新复杂度；
- 若教学页不进入 RPA brief，就失去版式规划；若进入，则又回到 B 的 brief 协议；
- 新服务/新 CLI 的维护成本对个人项目不低。

**C-lite**：不新建服务，只增加“教学规划提示 + `teaching_plan.json` schema + 一个合并函数”，把教学块转成带 `basis` 的额外 brief（`evidence_ids: []`）或 IR block。这样既保留模块化，又复用 RPA/Compiler。**这是我认为最符合本文档约束的形态。**

**判断**：完整 C 过早；C-lite 值得作为 Phase 2 的首选。

---

## 6. 推荐目标形态（协议草案）

> 目标：论文事实继续由 EV 严格约束；非论文内容有合法表示，且不被默认为已核实；同页混合可按块判定；默认行为不变。

### 6.1 模式开关（默认关闭）

在 Agent 请求中增加可选 `content_mode: paper_report | method_teaching | mixed`，默认 `paper_report`。只有 `method_teaching/mixed` 才启用教学规划与放宽规则；`paper_report` 的 prompt、schema 行为与今天一致，确保回归为零。

### 6.2 Deck 级来源注册表

```json
"content_sources": [
  {"id": "TB-1", "kind": "textbook", "citation": "Sutton & Barto, RL: An Introduction, 2nd ed., ch. 3",
   "locator": "pp. 55-60", "verification": "unverified"},
  {"id": "STD-1", "kind": "standard", "citation": "ISO 5725-2:2019", "verification": "verified"},
  {"id": "DER-1", "kind": "derived", "from": ["EV0007"], "assumptions": ["线性近似", "忽略二阶项"]},
  {"id": "EX-1", "kind": "constructed", "constructed": true, "note": "为讲解构造的二维示意数据"}
]
```

规则：
- `id` 唯一；`citation` 非空；`verification` 取 `verified | unverified | review_required`；
- `derived` 必须有 `from`（EV 或来源 id）与 `assumptions`；
- `constructed` 必须有 `constructed: true`，且不得引用 `source_figure` / 论文图资产；
- 外部来源默认 `unverified`，QA 生成 REVIEW，不默认正确。

### 6.3 块级 basis

在 `composition.blocks[*]` 增加可选 `basis`（以及 `source_refs`）：

```json
{"id": "b2", "component": "definition", "text": "梯度下降是标准一阶优化方法。",
 "basis": "external", "source_refs": ["TB-1"]}
```

- `basis` 缺省 = `paper`（兼容旧 IR；旧页面继续走 EV 规则）；
- `paper`：必须 `evidence_refs` 非空且能解析；`source_quote` 若给必须匹配；
- `external`：必须 `source_refs` 解析；`verification=unverified` → REVIEW；
- `derived`：必须 `source_refs` 指向 `DER-*` 或 EV；缺 `assumptions` → REVIEW；
- `constructed`：必须有可见标注（“示意/构造示例”），且不得使用论文图；缺失 → REVIEW/FAIL；
- `generated`：沿用 asset 的 `origin: generated` + `generator`；已有 `SCHEMATIC_REVIEW`。

### 6.4 explanation 义务同样按 basis

`explanation-obligation` 增加 `basis` / `source_refs`；`evidence_refs` 仅在 `basis=paper` 时必填。`status=waived` 只要求 `note`，不再要求 evidence。这样教学页才能声明“这一页必须看见流程图/公式”，而不是被迫放弃讲解契约。

### 6.5 反重贴标签（关键）

如果 `basis` 完全由写内容的 Agent 自报，它可以把论文主张标成 `external` 来绕过门禁。需要确定性的护栏：

- 页面/块中引用了论文图资产（`assets.origin=paper` 或 `figure_refs` 指向 paper）→ 必须 `basis=paper`；
- 文本与任一 EV 原文有长片段重合（例如 ≥12 个连续字符/词，或数字+单位组合）→ 必须 `basis=paper` 或给出 `external` 来源并说明；
- 出现论文中的具体数值/单位（可通过 EV 文本抽取数字）→ 必须 `basis=paper`。

命中但未声明 → `REVIEW`（不静默通过）；重复违规可升级为 FAIL。这个检查比“必须有 EV”更严格，且不阻止真正的教学扩展。

### 6.6 冲突标记

对“教学内容与论文观点矛盾”，确定性检测不现实。要求规划器在声明矛盾时写 `conflicts_with: ["EV0007"]`，QA 生成 REVIEW 并要求人工确认；**未声明的语义矛盾只能靠人工/LLM 审核，不能承诺自动发现**。这与文档 §7 的边界一致，但验收表应如实标注为“部分可测”。

### 6.7 兼容性策略

- 所有新字段可选；缺省 = 旧行为；`paper_report` 路径的 prompt 与校验不变。
- Story 若走 C-lite，则**完全不动** `story.py` 的 4–10/next/evidence 规则；教学 brief 在 pwf2rpa 合并阶段追加，`evidence_ids: []`。
- Deck IR 运行时校验是手写的（`ir.py`），新字段可先“运行时通过”；但发布的 schema 必须同步，否则第三方校验器会拒绝。版本策略二选一：
  - 保持 `schema_version: "2.0"`，把新字段视为可选扩展（运行时宽容，但 schema 文档不严谨）；
  - 或升 `2.1`，`ir.py:45` 接受 `2.0` 与 `2.1`，旧 IR 继续可编译。
  我倾向后者：显式版本比“运行时偷偷通过”更适合跨 Agent 协议。
- PWF 不改；RPA v1 不改（教学页用现有 `background/theory` 类别；若后续要专用版式，再评估 RPA 布局库，属于独立工作）。

---

## 7. 验收标准的可测性

| §9 测试 | 可自动化？ | 落点 | 缺口/备注 |
|---|---|---|---|
| 原有纯论文汇报不退化 | 是 | 现有 pwf2rpa / deck_compiler 回归 fixture；快照对比 | 需要先建立“黄金 deck”基线 |
| 无 EV 的基础知识页可生成 | 是 | Phase 1 IR/QA；RPA 已支持空 evidence | 需去掉 explanation 的强制 EV |
| 数学推导页可生成，保留依据与状态 | 部分 | `basis=derived` + `assumptions` + REVIEW | 数学正确性不能自动验证，只能检查“依据是否声明” |
| 构造示意案例不被当成论文实验 | 是 | `constructed: true` + 可见标注 + 禁止 paper 图 | 需 QA 规则与图注检查 |
| 同页混合来源分别约束 | 是（若块级标注） | block `basis` + QA 聚合 | 需要块级协议；页面级方案做不到 |
| 教学页声称论文结果仍须 EV | 是 | `basis=paper` 强制 EV；反重贴标签 | 语义级“声称”仍需人工/LLM |
| 缺外部依据产生 REVIEW 而非伪造 EV | 是 | `source_refs` 解析 + `verification` | 需要来源注册表 |
| 无引用教学页不被 QA 误判 | 是 | 修 `quality_metrics` 与 qa 规则 | 现为 MEDIUM −8；改按 basis 统计 |
| 教学与论文矛盾明确标记 | **否（只能部分）** | `conflicts_with` + REVIEW | 未声明的矛盾无法确定性发现 |
| 跨 Agent/平台可用 | 是 | 独立 JSON Schema + CLI/MCP 测试 | 避免 Python 私有校验；给出 schema 版本 |

**建议新增的测试**（文档验收表没有覆盖，但直接对应 §4.3）：

1. **misbinding 测试**：真实 EV 与主张无重合 → 期望 REVIEW（当前会通过，E2）。
2. **教学过渡测试**：`next` 为“接下来介绍……” → 教学模式允许，论文模式仍拒绝。
3. **教学首页流程测试**：首页 `ordered_steps` → 不被强制 `question` 类别，或不产生 strict 失败。
4. **外部来源缺失测试**：`basis=external` 无 `source_refs` → REVIEW。
5. **推导假设缺失测试**：`basis=derived` 无 `assumptions` → REVIEW。
6. **混合页容量测试**：论文图 + 教学文字 + 示例表同页 → 编译通过或有明确 `layout_feedback`。

**质量对比协议**（§9 最后一段）：

- 材料：2 篇论文（一篇方法密集、一篇理论密集）× 2 种模式（paper_report / method_teaching）× 2 种条件（现状 / Phase 1+2）。
- 评分：2–3 名领域读者盲评 5 维（先修充分性、推导完整性、例子清晰度、叙事流畅度、事实准确性），1–5 分。
- 自动指标：教学页数、先修概念数、推导步数、构造示例数、逐字复述论文比例、论文数值无 EV 的比例（misbinding 率）、QA 误报数。
- 通过标准：5 维中至少 3 维提升 ≥1 分；事实错误与 misbinding 不增加；paper_report 不退化。
- 样本小，只能作形成性评估，不能当统计显著结论。

---

## 8. 主要风险与反模式

1. **“教学”成为绕过门禁的标签**：如果 basis 自报且无护栏，Agent 会把论文主张标成 external。必须上 §6.5 的确定性检查；否则新机制会让证据体系比现在更弱。
2. **页面级豁免**：同页混合会被粗判为“教学页”，论文图/数值逃过检查。必须块级。
3. **把“无 EV”当成“已核实”**：新协议必须带 `verification`，QA 显示未核实计数；默认不通过。
4. **过度设计**：完整的来源管理、冲突检测、推导验证会拖垮个人项目。先做“来源类型 + 必填字段 + REVIEW”，不要做语义证明。
5. **改 Story 伤及论文 deck**：B 方案的最大风险不是工作量，而是 prompt 复杂度导致原有科学叙事质量下降；用 `content_mode` 隔离，并保留旧 prompt 回归。
6. **文档漂移**：Skill、explanation-contract、README 都是 Agent 的输入；代码改了文档不改，Agent 仍按旧规则创作。每个 Phase 都要同步这四处。
7. **QA 自身的误报**：实验发现 `_visible()` 过滤长度 <2 的字符串（`explanation.py:160`），`A/B/C` 这类符号会被判“不可见”；教学页常用短符号，需一并修。
8. **版本兼容**：IR 运行时宽容但 schema 严格，跨平台消费者会受影响；显式版本化，别依赖“旧编译器忽略新字段”。

---

## 9. 建议决策

**建议：Go，但分阶段，不直接做 B 或完整 C。**

| 阶段 | 内容 | 产出 | 预估 | 决策点 |
|---|---|---|---|---|
| Phase 0 | IR overlay 试点（不改代码） | 2 篇论文的教学版 deck + 盲评 | 1–2 天 | 教学页是否真的提升质量？misbinding 是否增加？ |
| Phase 1 | 共享 provenance 协议（IR/explanation/QA）+ `content_mode`；反重贴标签 | 教学页合法、可审计；paper_report 不变 | 3–4 天 | 协议是否足够表达混合页？QA 误报是否可接受？ |
| Phase 2 | 二选一：C-lite 教学规划器（推荐先试）或 B-lite Story 原生节点 | 教学叙事与论文叙事融合 | 3–5 天 | 教学是主场景还是偶发？ |
| Phase 3 | 冲突标记、外部来源校验、跨 Agent 打包 | 完整验收表 | 2–3 天 | 是否值得继续投入？ |

**为什么把 Phase 1 放在 Story 改造之前**：它是所有方案共用的底座，风险最低，且能立即让 overlay 教学页获得 `explain` 契约和正确的 QA 语义；先验证“协议够不够用”，再决定是否动 Story。

**为什么 C-lite 优先于 B**：Story 的职责是“证据推理链”，这是它最大的价值；把教学法塞进去会让它同时优化两个目标，回归风险高。C-lite 用独立提示/计划生成教学块，再合并为 RPA brief 或 IR block，既保留 Story 的严格性，又满足 §5.5 的模块化。若试点显示“教学页必须和论文节点一一对应、无法外挂”，再升级到 B。

**不建议做的事**（与文档 non-goals 一致）：改 PWF 的 Evidence 语义；全局 `disable_evidence_validation`；重写布局计算；把外部知识塞进 Evidence Store；默认所有任务启用教学扩展。

---

## 附录：实验与结果

> 以下实验均在 `.tmp-eval/` 临时目录完成，使用 `flow-test/workflow.json` 作为证据 fixture；实验后已删除临时目录，未改产品代码。如需复现，按表中描述重建最小 fixture 即可。

| 编号 | 实验 | 结果 |
|---|---|---|
| E1 | Story 教学节点 `evidence: []` | `STORY_EVIDENCE_EMPTY`，exit 2（`story.py:616-620`） |
| E2 | 同一教学节点改绑无关 `EV0006` | 通过；生成 7 个 brief；RPA `plan` 成功，`validate-deck` valid；封面也带 `EV0006` |
| E3 | `explain` 义务无 evidence | `STORY_EXPLAIN_EVIDENCE_EMPTY`（`story.py:283-286`） |
| E4 | brief `evidence_ids: []` 走 RPA normalize/plan/validate | 全部成功，7 页，无 violation |
| E5 | 教学 IR（空 `evidence_refs`、无 explanation）编译 | 成功；仅 `SCHEMATIC_REVIEW` + `INFO` |
| E6 | 空 `evidence_refs` 的 explanation IR 编译；`waived` 另用 validator 直接测试 | 编译 `EXPLANATION_INVALID` FAIL；`waived` + 空 refs 仍 FAIL |
| E7 | `next="接下来介绍梯度下降的基本原理"` | `STORY_NEXT_IS_SEQUENTIAL`，exit 2 |
| E8 | 首页 `ordered_steps`（A/B/C） | `CAPACITY_EXCEEDED`（question 类别无 process slot）；`--strict` exit 3 |
| E9 | 教学页 1 页无引用 | quality completeness 92（有引用 100），MEDIUM；不影响 build |
| E10 | 独立教学 IR + `EV0001` + process 载体（编译器不解析 EV 存在性） | 编译成功；`explanation_coverage` summary `satisfied: 1`（证明 gate 是引用存在性，不是相关性） |
| E11 | `semantic.content_sources` 未知字段 | 运行时编译成功（手写校验宽容）；发布 schema 会拒绝 |
| E12 | RPA metadata 透传 `story_explain` / 自定义键 | normalize 后保留（C-lite 的 metadata 通道可行） |

**未验证**：实际 PPTX 渲染与 PowerPoint 视觉质量（本机未跑 OfficeCLI/原生导出）；RPA 对教学页的版式质量（只测了 1 个简单 brief）；长教学页/复杂推导的容量；跨平台 MCP 调用。上述需要在 Phase 0 试点中补测。

---

## 一句话总结

**问题不是“论文证据太严”，而是“证据只有标签、没有语义”；解法不是开一个教学后门，而是把来源、依据和验证状态做成块级协议，让论文事实继续被 EV 约束，让教学解释有合法身份，并加上防止重贴标签的确定性护栏。**
