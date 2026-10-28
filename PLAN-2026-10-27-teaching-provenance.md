# TotalPipe 教学内容改造方案（v1）

> **2026-10-27 范围修正**：用户澄清“teaching 只是形式”，实际需求是“在保证论文事实的前提下顺手补充内容、服务于讲好”，并已选择 B（页内 + 少量独立补充页）。本文的 teaching 子系统方案偏重，不再作为实施依据；实施版见 [Supplement Lane 方案](PLAN-2026-10-27-supplement-lane.md)。
>
> 日期：2026-10-27　状态：方案评审稿，未实现
> 依据：[评估备忘](EVALUATION-2026-10-27-teaching-provenance.md)
> 目标读者：维护 Total-pipe / pwf2rpa / Deck Compiler 的开发者与 Agent 接入层维护者

---

## 1. 决策摘要

| 决策 | 选择 | 理由 |
|---|---|---|
| 总体架构 | **双轨内容模型**：论文轨保持 Story→EV 不变；教学轨新增独立 `teaching` 产物，在 pwf2rpa 合并 | 不改变 Story 节点/证据语义，回归风险最低 |
| 教学规划放在哪 | **Story 产物的独立顶层段 `teaching`**，不是 Story 节点 | 一次规划保证叙事连贯；节点仍是纯论文推理链 |
| 是否新增 Agent stage | **v1 不新增**；用 `content_mode` 控制提示与校验 | 避免改状态机；后续若提示质量下降，再拆独立 stage |
| 来源协议 | `basis + sources + verification`，块级 | 页面级无法表达同页混合；验证状态必须显式 |
| Deck IR 版本 | **保持 `2.0`，新增可选字段**；子协议用 `provenance.schema` 版本化 | 不触碰 `ir.py:45` 与现有 fixtures；新字段运行时宽容 |
| 默认行为 | `content_mode=paper_report`，教学能力关闭 | 现有论文 deck 的 prompt、校验、QA 完全不变 |
| 反重贴标签 | Agent 层确定性检查：论文图/论文数值/长片段重合 → 必须 paper basis | 防止 `basis` 自报变成绕过门禁 |
| v1 范围 | 独立教学页 + 受限混合页（论文图 + 1–2 个教学文字块） | 混合图形页容量风险高，放 v1.1 |
| 改动边界 | 不改 PaperWorkflow、不改 RPA 布局库、不改布局计算、不加全局开关 | 与需求 non-goals 一致 |

**一句话**：把“页面有没有 EV”改成“每个内容块声明依据类型，并按类型接受不同验证”；论文块仍必须 EV，教学块必须有来源或构造标记，且不能被重新标成教学来逃避论文事实检查。

---

## 2. 目标与不变量

### 2.1 目标

1. 教学页可以**不含任何 `EV####`**，仍能进入 Story → pwf2rpa → RPA → Deck IR → 编译。
2. 教学页可以声明 `explain`（必须看见流程图、公式、对照、推导步骤），不再因缺少 EV 放弃讲解契约。
3. 同一页可以混合论文内容与教学解释，且**按块**分别验证。
4. 论文事实仍然只能由 EV 支撑；教学块不能携带论文具体数值、图或结论而不声明 paper basis。
5. 外部知识默认 `unverified`，缺来源产生 REVIEW，不默认正确。
6. 构造示例必须显式标记，不能被识别为论文实验。
7. 默认 `paper_report` 行为不变；旧 Story / 旧 IR / 旧 build 目录可读。

### 2.2 不变量（实现时任何一条不满足即回退）

- **I1**：`basis=paper` 的块/义务必须有可解析的 EV；教学模式不得豁免。
- **I2**：`basis!=paper` 的块不得写 `EV####`（防止错绑）；需要引用论文事实时拆成 paper 块。
- **I3**：教学页/块不能使用 `assets.origin=paper` 的图而不声明 paper basis。
- **I4**：`content_mode=paper_report` 时，Story prompt、rpa_input、IR 校验、QA 与今天一致。
- **I5**：PaperWorkflow 的 `synthesis_readiness` 语义不变；教学能力不要求改 PWF。
- **I6**：不新增“全局关闭证据校验”的开关；所有豁免按 basis 逐块判定。

---

## 3. 总体架构

```text
论文 PDF/MD
  → PaperWorkflow（不变）
  → Story Planner
       ├─ story[]        论文推理链（4–10 节点，EV 必填，规则不变）
       └─ teaching{}     教学计划（可选，无 EV，sources/basis/placement）
  → pwf2rpa
       ├─ 校验 paper story（原逻辑）
       ├─ 校验 teaching（新 teaching.py）
       ├─ paper briefs（原逻辑）
       ├─ teaching briefs（evidence_ids: []，metadata.content_basis/sources）
       └─ 混合页：teaching_blocks 挂到对应 paper brief 的 metadata
  → RPA（不改代码）
       normalize / plan / validate-deck，接受空 evidence_ids
  → Agent 映射 Deck IR
       ├─ semantic.evidence_refs（论文 refs；教学页可为空）
       ├─ root.content_sources（来源注册表）
       ├─ block.basis / source_refs / assumptions
       └─ semantic.explanation（paper 义务 + teaching 义务，各带 basis）
  → Deck Compiler
       ├─ provenance.py：结构校验
       ├─ explanation.py：按 basis 校验义务
       ├─ quality_metrics：按 basis 统计
       └─ 布局/容量/OfficeCLI（不变）
```

关键点：**RPA 与布局计算不改**。教学页复用现有 `background / theory / method_overview / case / table` 类别；教学 brief 的空 `evidence_ids` 已被 RPA 接受（评估实验 E4）。

---

## 4. 协议规范

### 4.1 `content_mode`

Agent 请求新增可选字段：

```json
{"content_mode": "paper_report | method_teaching | mixed"}
```

- 默认 `paper_report`；缺失等价于默认。
- 仅改变：Story prompt 是否附教学段、pwf2rpa 是否合并 teaching、IR prompt 的说明、QA 期望。
- 不改变：论文 story 节点规则、RPA 规划、布局、OfficeCLI。
- 存储：`job.request.content_mode`；`totalpipe_start` 的 MCP schema 增加 enum；`runner.start` 增加参数。
- 注意：`agent/stages.json` 不改；教学段是 Story 产物的一部分，不新增 stage。

| 模式 | 允许独立教学页 | 允许 attach 混合页 | 用途 |
|---|---|---|---|
| `paper_report` | 否 | 否 | 现有论文汇报，完全不变 |
| `method_teaching` | 是 | 否（v1） | 方法讲解，教学页插在论文节点前/后 |
| `mixed` | 是 | 是（v1 受限） | 教学页 + 同页混合解释 |

### 4.2 Story 产物：新增可选顶层 `teaching`

`story_plan.json`：

```json
{
  "planner": {"mode": "subagent", "model": "...", "reasoning_effort": "high", "selected_by_user": true},
  "core_question": "...",
  "main_message": "...",
  "story": [ ... 原样，4–10 个论文节点 ... ],
  "ending": {"takeaway": "...", "limitation": "..."},
  "teaching": {
    "schema": "totalpipe.teaching-plan/1",
    "audience": {"level": "graduate", "assumed": ["概率论", "线性代数"]},
    "sources": [ ... 见 4.4 ... ],
    "sections": [ ... 见下 ... ],
    "conflicts": [ ... 可选 ... ]
  }
}
```

规则：

- `teaching` 仅当 `content_mode != paper_report` 时允许；paper_report 下出现 → `TEACHING_NOT_ENABLED`。
- `story` 仍必须有 4–10 个论文节点；v1 不支持“纯教学、无论文节点”的 deck。
- `teaching.sections` 1–8 个；`teaching` 不参与 `story` 节点计数。
- 论文节点的 `evidence`、`explain.evidence` 规则完全不变。
- schema 文件 `pwf2rpa/schemas/story-plan.schema.json` 增加可选 `teaching`；运行时 `story.py` 的 `_ROOT_FIELDS` 增加 `"teaching"`。

### 4.3 `teaching` 内部结构

```json
{
  "id": "T1",
  "role": "prerequisite | intuition | derivation | example | comparison | summary",
  "title": "先修：标准算法的三步流程",
  "takeaway": "标准算法按 A→B→C 执行；这是教材内容，不是论文结果。",
  "placement": {"before_story_node": 1},
  "blocks": [
    {"id": "T1-b1", "component": "definition", "text": "……", "basis": "external", "source_refs": ["TB-1"]},
    {"id": "T1-b2", "component": "formula", "text": "……", "basis": "derived", "source_refs": ["DER-1"], "assumptions": ["线性近似"]}
  ],
  "must_show": [
    {"id": "T1-ob1", "kind": "ordered_steps", "required": true,
     "content": {"items": ["A", "B", "C"]}, "basis": "external", "source_refs": ["TB-1"]}
  ],
  "constructed": false
}
```

字段规则：

| 字段 | 规则 |
|---|---|
| `role` | 决定 RPA 类别提示与默认版式池 |
| `placement` | 三选一：`before_story_node` / `after_story_node` / `attach_to_story_node`，1-based，必须在论文节点范围内 |
| `blocks` | 1–6 个；`component` 复用 IR 现有枚举；`text` 非空 |
| `must_show` | 0–4 条；`kind` 复用 explain 八类；`basis/source_refs` 规则同块 |
| `constructed` | `true` 时该 section 的图/数据必须是构造示例；必须有可见标注 |
| `conflicts` | 可选；声明与论文证据冲突，触发 REVIEW，不静默覆盖 |

### 4.4 来源注册表与 basis

```json
"sources": [
  {"id": "TB-1", "kind": "textbook", "citation": "Sutton & Barto, Reinforcement Learning, 2nd ed., ch. 3",
   "locator": "pp. 55-60", "verification": "unverified"},
  {"id": "STD-1", "kind": "standard", "citation": "ISO 5725-2:2019", "verification": "verified"},
  {"id": "DER-1", "kind": "derived", "from": ["EV0007"], "assumptions": ["线性近似", "忽略二阶项"]},
  {"id": "EX-1", "kind": "constructed", "constructed": true, "note": "为讲解构造的二维示意数据"}
]
```

`basis` 四类：

| basis | 必填 | 禁止 | QA 默认 |
|---|---|---|---|
| `paper` | `evidence_refs` 非空、可解析；`source_quote` 若给必须匹配 | 外部来源 | 缺失 → FAIL |
| `external` | `source_refs` 非空、可解析；来源 `verification` | `EV####`；derived/constructed 来源 | `unverified` → REVIEW |
| `derived` | `source_refs` 指向 `DER-*`/EV；`assumptions` 非空 | 只写 EV 而无 `assumptions`；把推导结论标成 paper | 缺假设 → REVIEW |
| `constructed` | `constructed: true` + 可见标注 | 论文图、论文数值 | 缺标注 → REVIEW/FAIL |

补充：

- `source_refs` 只能指向 `teaching.sources` 的 id，或 `paper` basis 时的 EV。
- `verification` 取 `verified | unverified | review_required`；external 默认 `unverified`。
- `derived.from` 可以是 EV id 或 source id；`assumptions` 至少 1 条非空字符串。
- v1 不做网络核验；`verified` 只表示“作者已核对”，不表示系统自动确认。

### 4.5 RPA brief 元数据契约

pwf2rpa 生成教学 brief 时写入：

```json
{
  "slide_type": "custom",
  "category_hint": "background",
  "title": "先修：标准算法的三步流程",
  "takeaway": "标准算法按 A→B→C 执行；这是教材内容，不是论文结果。",
  "evidence_ids": [],
  "citation_ids": [],
  "content_roles": ["context"],
  "allow_auto_split": true,
  "metadata": {
    "content_basis": "teaching",
    "content_sources": ["TB-1", "DER-1"],
    "teaching_id": "T1",
    "teaching_role": "prerequisite",
    "placement": {"before_story_node": 1},
    "content_basis_blocks": [
      {"id": "T1-b1", "basis": "external", "source_refs": ["TB-1"]},
      {"id": "T1-b2", "basis": "derived", "source_refs": ["DER-1"]}
    ],
    "teaching_explain": {
      "reader_task": "trace",
      "must_show": [
        {"id": "T1-ob1", "kind": "ordered_steps", "required": true,
         "content": {"items": ["A", "B", "C"]}, "basis": "external", "source_refs": ["TB-1"]}
      ],
      "must_not_lose": ["order"]
    }
  }
}
```

- RPA 已证明会保留未知 metadata（评估实验 E12），因此 v1 **不需要改 RPA**。
- `content_roles` 使用 RPA 现有枚举 `context`（`research-ppt-assistant/server/content-model.mjs:1282-1289`）。
- `teaching_explain` 进入 IR 后转成 `semantic.explanation.obligations`，每条带 `basis/source_refs`；attach 页与论文义务合并。
- `category_hint` 映射：

| role | 默认 category |
|---|---|
| prerequisite / intuition | `background` |
| derivation | `theory` |
| example | `case` |
| comparison | `table` |
| summary | `discussion` |

- 若 `must_show` 是 `ordered_steps`，同时写 `process_steps`；`comparison` 写 `comparison_dimensions`，让 RPA 能进入 process/table 池（与现有 explain→form 推导一致）。
- 教学 brief 的 `slide_count` 计入总页数；`totalpipe_start` 的 `slide_count` 校验改为“总 brief 数”（teaching 关闭时与原行为一致）。

### 4.6 Deck IR 新字段

**根级**（可选）：

```json
{
  "content_sources": [ ... 与 teaching.sources 合并去重 ... ],
  "provenance": {
    "schema": "totalpipe.provenance/1",
    "content_mode": "method_teaching",
    "teaching_plan_sha256": "...",
    "relabel_checked": true
  }
}
```

**slide.semantic**：`evidence_refs` 保持必填（可为空）；不改现有键。

**slide.composition.blocks[*]** 新增可选：

```json
{
  "id": "b2",
  "component": "definition",
  "text": "梯度下降是标准一阶优化方法。",
  "basis": "external",
  "source_refs": ["TB-1"],
  "evidence_refs": [],
  "assumptions": []
}
```

- `basis` 缺省 = `paper`（旧 IR 兼容）。
- `paper` 块：`evidence_refs` 可省略（继承 slide 的 `semantic.evidence_refs`）；若写，必须是其子集。
- `external`/`derived`/`constructed` 块：`source_refs` 必填；不得写非空 `evidence_refs`。
- `assumptions` 仅 `derived` 使用。

**semantic.explanation.obligations[*]** 新增可选：

```json
{"id": "ob-1", "kind": "ordered_steps", "required": true,
 "basis": "external", "source_refs": ["TB-1"],
 "content": {"items": ["A", "B", "C"]},
 "carrier": "process", "status": "bound"}
```

- `basis` 缺省 = `paper`；paper 时 `evidence_refs` 非空且是 `semantic.evidence_refs` 子集。
- 非 paper 时 `source_refs` 非空且解析；`evidence_refs` 可省略。
- `status=waived` 只要求 `note`，不再要求 evidence（修当前无逃生口的问题）。

**schema/运行时**：

- `Total-pipe/schemas/deck-ir.schema.json`：根 `content_sources`/`provenance`、block `basis/source_refs/assumptions/evidence_refs`、explanation obligation 条件必填。
- `deck_compiler/ir.py`：手写校验补充上述规则；`schema_version` 仍接受 `"2.0"`。
- 旧 IR 无新字段 → 全部按 paper 处理；行为不变。

### 4.7 混合页规则（v1 受限）

`placement.attach_to_story_node: n`（仅 `content_mode=mixed`）：

- 不生成独立 brief；`teaching_blocks` 写入第 n 个 paper brief 的 metadata。
- IR 阶段把这些块并入该页 `composition.blocks`，每块带 `basis`。
- v1 只保证：**论文图/文字 + 1–2 个教学文字块**（definition/body/limitation 等），不新增第二个图形或表格。
- 若编译器报容量不足：Agent 把教学块拆成独立教学页，或减少块数；不允许删除原文来凑容量。
- 完整混合（论文图 + 教学公式 + 示例表 + 流程图）放 v1.1，需要 composite 容量专项。
- `method_teaching` 模式下出现 `attach_to_story_node` → `TEACHING_MODE_MISMATCH`（error），提示改用 `mixed`。

---

## 5. 合并与排序规则（pwf2rpa）

输入：paper specs（cover + 4–10 节点 + summary）、teaching sections。

1. cover 固定第一页，evidence 取第一个论文节点（**不取教学节点**，因为教学不在 story 里）。
2. 论文节点按原顺序生成 brief。
3. teaching sections 按 placement 插入：
   - `before_story_node: k` → 放在第 k 个论文 brief 之前；
   - `after_story_node: k` → 放在之后；
   - `attach_to_story_node: k` → 不新增页，写入第 k 个 brief 的 `metadata.teaching_blocks`。
4. 同一锚点的多个 section 保持 `sections` 输入顺序。
5. summary 固定最后；evidence 仍取末两个论文节点。
6. 输出 `slide_briefs` 的 `slide_id` 由 RPA 重新分配；`metadata.teaching_id` 保留原 id，便于审计。
7. 断言：teaching 页数 + 论文页数 = 总 brief 数；cover/summary 各 1；attach 不增加页数。

排序函数建议独立：

```python
def merge_specs(paper_specs, teaching_specs):
    cover, nodes, summary = paper_specs[0], paper_specs[1:-1], paper_specs[-1]
    ordered = []
    before = defaultdict(list); after = defaultdict(list)
    for spec in teaching_specs:
        placement = spec["metadata"]["placement"]
        if "attach_to_story_node" in placement:
            index = placement["attach_to_story_node"] - 1
            nodes[index].setdefault("metadata", {}).setdefault("teaching_blocks", []).extend(
                spec["metadata"]["content_basis_blocks"])
        elif "before_story_node" in placement:
            before[placement["before_story_node"]].append(spec)
        else:
            after[placement["after_story_node"]].append(spec)
    for index, node in enumerate(nodes, 1):
        ordered.extend(before.get(index, []))
        ordered.append(node)
        ordered.extend(after.get(index, []))
    return [cover, *ordered, summary]
```

（实际实现需处理 section 级 `blocks` 到 brief `key_points` 的映射；见 §6。）

---

## 6. 代码改造清单

> 路径均相对 `Total-pipe/`。行号为当前版本参考，实施时以源码为准。

### 6.1 新增模块

| 文件 | 内容 | 预估 |
|---|---|---|
| `pwf2rpa/pwf2rpa/teaching.py` | `validate_teaching`、`teaching_to_specs`、`merge_specs`、`build_teaching_prompt`；错误码 `TEACHING_*` | ~400 行 |
| `pwf2rpa/schemas/teaching-plan.schema.json` | 独立发布 schema；story-plan 内嵌引用 | ~150 行 |
| `deck_compiler/provenance.py` | IR 结构校验：sources、basis、constructed、conflict、paper 图 | ~300 行 |
| `agent/provenance.py` | 反重贴标签：文本重合、数字+单位、论文图；需要 normalized evidence 文本 | ~150 行 |
| `tests/fixtures/teaching/` | 最小 workflow + story+teaching + 期望 rpa_input/IR | ~6 文件 |

### 6.2 修改模块

| 文件 | 改动 | 风险 |
|---|---|---|
| `pwf2rpa/pwf2rpa/story.py` | `_ROOT_FIELDS` 加 `teaching`；`validate_story` 调用 `teaching.validate_teaching`；`story_to_specs` 增加 `content_mode`/`include_teaching` 参数并合并；`build_story_prompt` 增加 `content_mode` 与教学段 output_shape/instructions | 中；已有 story 测试需回归 |
| `pwf2rpa/pwf_to_rpa.py`（或 `__main__.py`） | `--teaching PATH`、`--content-mode`；`--make-story-prompt` 传递 mode | 低 |
| `pwf2rpa/README.md` | 教学段协议、CLI、错误码 | 低 |
| `agent/adapters.py` | `start`/request 增加 `content_mode`；`story_prompt` 传 mode 并写入 `prompt.request.content_mode`；`check_story` 按 `StoryError.problems` 里的 `TEACHING_*` 码分类（不要统一包成 `STORY_PROVENANCE_INVALID`）；`rpa` 传 `--content-mode`，`slide_count` 用总 brief；`check_ir` 调 `provenance.validate` + `agent.provenance.check`；`ir_prompt` 增加教学/来源说明 | 中 |
| `agent/runner.py` | `start(..., content_mode='paper_report')`；请求字典；证据/错误信封不变 | 低 |
| `agent/state.py` | `validate_job` 不强制 content_mode（可选）；无其他改动 | 低 |
| `agent/mcp_server.py` | `totalpipe_start` schema 增加 `content_mode` enum | 低 |
| `deck_compiler/ir.py` | 调用 `provenance.validate(ir)`；`validate_explanation` 传 `ir`/sources；block 基础字段检查 | 中 |
| `deck_compiler/explanation.py` | obligation `basis/source_refs/assumptions`；paper 才要求 `evidence_refs`；waived 不要求 evidence；coverage 记录 basis | 中 |
| `deck_compiler/quality_metrics.py` | `analyze_completeness` 按 basis 拆分：paper 引用覆盖 vs teaching 来源覆盖；不再对教学页报 “No evidence citations” | 低 |
| `schemas/deck-ir.schema.json` | 根 `content_sources`/`provenance`；block 字段；explanation 条件必填 | 中（closed schema） |
| `skills/total-pipe-deck/SKILL.md` | 教学模式、teaching 段、IR 映射、REVIEW 处理 | 低 |
| `docs/explanation-contract.md` | basis 表；paper/teaching 义务规则 | 低 |
| `docs/deck-compiler-v2.md` | 根 `content_sources`、block basis、explanation basis | 低 |
| `docs/USAGE.zh-CN.md` | `content_mode` 用法、示例、限制 | 低 |
| `README.md` / `docs/README.md` | 能力条目与协议索引 | 低 |

### 6.3 关键函数签名（建议）

```python
# pwf2rpa/teaching.py
def validate_teaching(raw, workflow, paper_nodes) -> tuple[dict | None, list[Problem]]: ...
def teaching_to_specs(teaching, paper_count) -> list[dict]: ...
def merge_specs(paper_specs, teaching_specs) -> list[dict]: ...
def build_teaching_prompt(workflow, paper_story, model, reasoning_effort) -> dict: ...

# pwf2rpa/story.py
def story_to_specs(raw, workflow, *, include_teaching=False) -> tuple[list[dict], list[Problem]]: ...

# deck_compiler/provenance.py
def validate(ir) -> list[dict]: ...          # issue 结构同 contracts.issue

# agent/provenance.py
def check(ir, normalized) -> list[str]: ...  # 返回 FAIL 级问题描述
```

---

## 7. 校验规则矩阵

### 7.1 结构校验（pwf2rpa teaching.py）

| 检查 | 代码 | 级别 |
|---|---|---|
| `teaching` 出现在 paper_report | `TEACHING_NOT_ENABLED` | error |
| 教学曲线未标 schematic | `TEACHING_CURVE_UNMARKED` | error |
| `method_teaching` 使用 attach | `TEACHING_MODE_MISMATCH` | error |
| sections 为空/超过 8 | `TEACHING_SECTIONS_INVALID` | error |
| placement 缺失/越界/多键 | `TEACHING_PLACEMENT_INVALID` | error |
| source id 重复/空 citation | `TEACHING_SOURCE_INVALID` | error |
| external 无 source_refs | `TEACHING_SOURCE_MISSING` | error |
| external 引用 EV | `TEACHING_EVIDENCE_FORBIDDEN` | error |
| derived 缺 assumptions | `TEACHING_ASSUMPTION_MISSING` | error |
| constructed 无标记 | `TEACHING_CONSTRUCTED_UNMARKED` | error |
| paper 块无 EV | `TEACHING_PAPER_EVIDENCE_MISSING` | error |
| must_show 空但无 prose 理由 | `TEACHING_PROSE_REASON_MISSING` | warning |
| attached 块超过 2 | `TEACHING_ATTACH_TOO_MANY` | error（v1 限制） |

### 7.2 Deck IR 结构校验（provenance.py）

| 检查 | 代码 | 级别 |
|---|---|---|
| `basis` 非法 | `PROVENANCE_BASIS_INVALID` | FAIL |
| paper 块/页无 EV | `PROVENANCE_PAPER_EVIDENCE_MISSING` | FAIL |
| non-paper 块写 EV | `PROVENANCE_EVIDENCE_FORBIDDEN` | FAIL |
| source_refs 无法解析 | `PROVENANCE_SOURCE_UNKNOWN` | FAIL |
| external 未核实 | `PROVENANCE_SOURCE_UNVERIFIED` | REVIEW |
| derived 缺 assumptions | `PROVENANCE_ASSUMPTION_MISSING` | REVIEW |
| constructed 无可见标注 | `PROVENANCE_CONSTRUCTED_UNLABELED` | REVIEW |
| constructed 使用论文图 | `PROVENANCE_CONSTRUCTED_USES_PAPER` | FAIL |
| conflict 声明 | `PROVENANCE_CONFLICT_DECLARED` | REVIEW |
| 页面同时有 paper 图与全教学块 | `PROVENANCE_MIXED_AMBIGUOUS` | REVIEW |
| 导入教学 IR 但无证据语料可做反重贴标签 | `PROVENANCE_CORPUS_UNAVAILABLE` | REVIEW |

`explanation.py` 另按义务校验：paper 义务缺 `evidence_refs` → `EXPLANATION_INVALID` FAIL；teaching 义务缺/无法解析 `source_refs` → `EXPLANATION_SOURCE_INVALID` FAIL；来源 `unverified` → `EXPLANATION_SOURCE_UNVERIFIED` REVIEW；`waived` 只要求 `note`。

### 7.3 反重贴标签（agent/provenance.py）

对每个 `basis != paper` 的块：

1. 文本规范化（去空白/标点、casefold）。
2. 与所有 EV 文本求最长公共子串；阈值默认：CJK ≥ 12 字或拉丁 ≥ 8 词。
3. 抽取数字+单位 token；若出现在 EV 文本中 → 命中。
4. 页面引用 `assets.origin=paper` 的图 → 命中。
5. 命中且 basis != paper → `PROVENANCE_RELABEL_RISK`（FAIL），报出匹配的 EV id/片段与修复建议（拆块或改 paper + EV）。

阈值集中在 `agent/provenance.py` 常量，先保守；若误报高，可把“长片段重合”降为 REVIEW，但“论文数值/论文图”保持 FAIL。

---

## 8. 兼容与迁移

| 场景 | 行为 |
|---|---|
| 旧 `story_plan.json`（无 teaching） | 完全兼容；`include_teaching=False` 时不读该字段 |
| 旧 `rpa_input.json` / `normalized_content.json` | 不涉及；RPA 不变 |
| 旧 `deck_ir.json`（无 basis/sources） | 全部按 paper；`provenance.validate` 快速返回；编译结果不变 |
| 导入教学 IR（`source_kind=deck_ir`） | 结构校验照常；反重贴标签缺少 evidence 语料，`relabel_checked` 不为 true 时 QA 多一条 `PROVENANCE_CORPUS_UNAVAILABLE` REVIEW，需人工确认 |
| 旧 build 目录 | 可读；quality_metrics 对无 teaching 的 deck 保持原逻辑 |
| 旧 Agent job | **不能续跑**：`state.code_hash()` 包含 `agent/*.py|json`（`agent/state.py:182-186`），任何接入层改动都会使 checkpoint 失效。这是现有特性，不是本次新增；发布说明需注明“升级后新建 job”。 |
| 外部 JSON Schema 消费者 | 新字段是可选；旧 schema 会拒绝新字段，需要同步更新；v1 不升 IR 版本，子协议用 `provenance.schema` 标识 |
| 回滚 | 删除 `content_mode`/teaching 段即可回旧行为；paper_report 路径不依赖新代码分支 |

**版本策略**：

- v1 保持 `schema_version: "2.0"`，新增可选字段；`provenance.schema = "totalpipe.provenance/1"` 单独版本化。
- 若后续需要严格契约版本，再升 `2.1`；届时同步 `ir.py:45`、`agent/state.py:163`、`agent/runner.py:151`、`unified_cli.py:134` 等版本判断。v1 不做，控制改动面。

**PWF 不改**：`synthesis_readiness` 仍是论文输入质量门；教学能力不等待它放宽。

**RPA 不改**：v1 用现有类别；若后续发现教学页版式质量不足，再评估新增 `method_teaching` blueprint（独立工作，不阻塞 v1）。

---

## 9. 测试计划

### 9.1 单元测试

- `pwf2rpa/tests/test_teaching.py`（新）
  - placement 三种、越界、多键；
  - sources 重复/缺 citation；external 无 refs；external 引用 EV；
  - derived 缺 assumptions；constructed 无标记；
  - paper 块无 EV；
  - merge 顺序：before/after/attach；cover/summary 不取教学；
  - `content_mode=paper_report` + teaching → error。
- `tests/test_provenance.py`（新）
  - paper 块无 EV → FAIL；non-paper 写 EV → FAIL；
  - external 未核实 → REVIEW；constructed 无标注 → REVIEW；
  - conflict → REVIEW；paper 图 + 全教学块 → REVIEW；
  - 旧 IR 快速返回。
- `tests/test_explanation_contract.py`（改）
  - paper 义务无 refs → FAIL；teaching 义务无 refs 但有 source_refs → 通过；
  - waived 无 refs → 通过；
  - 非 paper 义务 `evidence_refs` 为空不再 FAIL。
- `tests/test_agent_adapters.py`（改）
  - `content_mode` 透传；teaching 错误码映射；slide_count 总页数；
  - anti-relabel 正/负样例。

### 9.2 集成测试

用 `tests/fixtures/teaching/` 跑：

1. `pwf2rpa workflow.json --story story_teaching.json --content-mode method_teaching --out rpa_input.json`
2. `node server/cli.mjs normalize-content` → `plan` → `validate-deck`
3. Agent 映射 IR（fixture 提供期望 IR 或脚本）
4. `python -m deck_compiler compile --ir teaching.deck_ir.json --out build`
5. 断言：无 FAIL；教学页 REVIEW 仅来自未核实来源/示意图；explanation coverage 覆盖教学义务。

### 9.3 回归测试

- 现有 `pwf2rpa/tests/test_story.py`、`test_adapter.py` 全绿。
- 现有 `tests/test_explanation_contract.py`、`test_deck_compiler.py`、`test_schematic.py`、`test_reference_images.py` 全绿。
- 旧 paper deck 的 `rpa_input`/`qa_report` 快照不变（paper_report 模式）。
- `python totalpipe.py quality` 对旧 deck 分数不变。

### 9.4 负向/安全测试

- 教学块写“本文在 ImageNet 上达到 95%”但不带 EV → 反重贴标签命中（数值/片段）→ FAIL。
- 教学块复制 EV 原句 → FAIL。
- 教学块使用论文图 → FAIL。
- 教学页声称“作者的结论是……”但无 EV → 人工/LLM 审核缺口；v1 只能靠反重贴标签与人工 REVIEW，文档需写明。
- 构造示例未标“示意” → REVIEW。
- 外部来源 citation 为空 → FAIL。
- 混合页 attach 3 个块 → `TEACHING_ATTACH_TOO_MANY`。

### 9.5 质量对比（验收必需）

- 2 篇论文（方法密集/理论密集）× 2 模式 × 2 条件（现状/新方案）。
- 2–3 名读者盲评 5 维（先修、推导、例子、叙事、事实），1–5 分。
- 自动指标：教学页数、先修概念数、推导步数、构造示例数、逐字复述比例、无 EV 的论文数值数、QA 误报数。
- 通过：至少 3 维提升 ≥1 分；事实错误/misbinding 不增加；paper_report 不退化。

---

## 10. 实施阶段

> 工作量为粗略估算，按 1 名熟悉仓库的开发者计；不含真实 PPT 渲染与人工盲评的日历时间。

| 阶段 | 内容 | 产出 | 预估 | 退出条件 |
|---|---|---|---|---|
| M0 协议冻结 | 评审本方案；确定字段名/错误码/`content_mode` 语义；确认 v1 范围 | 本文件 + 1 页 schema 草案 | 0.5 天 | 无阻塞异议 |
| M1 teaching 校验 | `teaching.py`、`teaching-plan.schema.json`、story.py 钩子、CLI `--content-mode/--teaching` | 手写 teaching 段可校验；单测 | 2 天 | `test_teaching.py` 绿；旧 story 测试绿 |
| M2 合并与 RPA | `teaching_to_specs`/`merge_specs`；brief metadata；rpa_input 生成；RPA 集成测试 | 教学页出现在 RPA plan | 1.5 天 | 独立教学页 plan/validate 成功；paper 模式输出不变 |
| M3 IR/QA | `provenance.py`、IR schema/ir.py、explanation.py、quality_metrics；负向测试 | 教学 IR 可编译；误绑/无来源被拦 | 2 天 | 教学 IR 无 FAIL；旧 examples 编译不变 |
| M4 Agent 接入 | `content_mode`、Story prompt 教学附件、check_story/check_ir、反重贴标签、`ir_prompt` | 端到端 job 到 candidate | 1.5 天 | `totalpipe_start` 教学 job 跑通；paper job 不变 |
| M5 文档与评估 | SKILL/USAGE/README/contracts；盲评；修问题 | 文档同步 + 评估报告 | 1.5 天 | 验收表通过；文档无旧规则残留 |
| **合计** | | | **~9 天** | |

**建议的提交切片**（便于回滚）：

1. `feat(pwf2rpa): teaching plan validation`
2. `feat(pwf2rpa): merge teaching briefs into RPA input`
3. `feat(deck): provenance contract for block-level sources`
4. `feat(agent): teaching content mode + relabel guard`
5. `docs: teaching provenance contract`

每个切片都必须保持 `paper_report` 回归绿。

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Story prompt 同时做论文链 + 教学路径，质量下降 | 论文 deck 或教学 deck 变差 | `content_mode` 隔离；教学附件只追加，不改原指令；M5 盲评；若下降，M6 拆独立 teaching stage（协议不变） |
| 教学页版式质量不足（RPA 类别不匹配） | 教学页像文字页 | v1 用 background/theory/case；M2 观察 plan；必要时新增 blueprint（独立） |
| 混合页容量超限 | 编译失败或挤掉内容 | v1 限 1–2 个文字块；容量失败拆独立页；v1.1 再做完整混合 |
| `basis` 自报被滥用 | 论文事实被标成 external | 反重贴标签（数值/图/长片段）+ 人工 REVIEW；I2/I3 不变量 |
| 外部来源不可核实 | 教学页“看起来可信” | 默认 unverified + REVIEW；支持 citation/locator；不自动 verified |
| 旧 job 失效 | 升级后续跑失败 | 发布说明明确“升级后新建 job”；这是现有 `code_hash` 行为 |
| Schema 封闭导致外部消费者拒绝 | 跨平台集成失败 | 可选字段 + 同步发布 schema；子协议版本；必要时 2.1 |
| 范围膨胀（冲突检测、来源网络核验、完整混合） | 个人维护成本 | 明确 v1 非目标；REVIEW + 人工兜底 |

**v1 明确不做**：

- 纯教学 deck（无 paper story）；
- 完整混合图形页；
- 外部来源自动联网核验；
- 语义级“论文观点矛盾”自动检测（只做显式 `conflicts` + REVIEW）；
- 修改 PWF readiness 语义；
- 修改 RPA 布局库/编译布局计算；
- 全局 `disable_evidence_validation`。

---

## 12. 验收清单

| 验收项 | 判定方式 | v1 |
|---|---|---|
| 原有纯论文汇报不退化 | paper_report 快照 + 现有测试 | 必须 |
| 无 EV 的基础知识页可生成 | 集成测试 + 编译 | 必须 |
| 数学推导页保留依据/验证状态 | `basis=derived` + assumptions + REVIEW | 必须 |
| 构造示例不被当成论文实验 | `constructed` + 可见标注 + 禁论文图 | 必须 |
| 同页混合按块约束 | block basis + QA | v1 受限模式 |
| 教学页声称论文结果仍须 EV | paper basis + anti-relabel | 必须 |
| 缺外部依据产生 REVIEW | source_refs + verification | 必须 |
| 无引用教学页不被 QA 误判 | quality_metrics 按 basis | 必须 |
| 教学与论文矛盾明确标记 | `conflicts` + REVIEW | 显式声明；未声明不保证 |
| 跨 Agent/平台可用 | 独立 schema + CLI/MCP | 必须 |

---

## 13. 开放问题（需评审确认）

1. **Story 产物 vs 新 stage**：v1 选 Story 产物内嵌；若教学规划明显拖累 Story，是否接受拆成独立 stage（协议不变）？
2. **IR 版本**：v1 保持 2.0 + 子协议版本；是否要求立即升 2.1（更严格但改动面大）？
3. **`slide_count` 语义**：教学模式下按“总页数”还是“论文页数”？建议总页数。
4. **纯教学 deck**：v1 不支持；是否有真实需求需要在 v1.1 放开（需要重新设计 Story 最小节点）？
5. **来源格式**：中文教材/标准/网页的 citation 最小字段是否足够（作者、书名、版次、章节、页码/URL）？
6. **`verified` 的含义**：是否允许作者手动标 verified，还是必须由独立审核步骤写入？

---

## 附录 A：最小示例（教学页 + 混合页）

### A.1 教学页

```json
{
  "id": "T1",
  "role": "prerequisite",
  "title": "先修：梯度下降的三步",
  "takeaway": "标准梯度下降按“算梯度→取步长→更新参数”执行；这是教材内容，不是本文结果。",
  "placement": {"before_story_node": 1},
  "blocks": [
    {"id": "T1-b1", "component": "definition", "text": "梯度下降是一阶迭代优化方法。", "basis": "external", "source_refs": ["TB-1"]},
    {"id": "T1-b2", "component": "formula", "text": "\\theta_{t+1} = \\theta_t - \\eta \\nabla L(\\theta_t)", "basis": "derived", "source_refs": ["DER-1"], "assumptions": ["L 可微", "学习率固定"]}
  ],
  "must_show": [
    {"id": "T1-ob1", "kind": "ordered_steps", "required": true, "content": {"items": ["计算梯度", "取步长", "更新参数"]}, "basis": "external", "source_refs": ["TB-1"]}
  ]
}
```

### A.2 混合页（attach）

```json
{
  "id": "T2",
  "role": "intuition",
  "title": "论文结构与标准算法对照",
  "placement": {"attach_to_story_node": 2},
  "blocks": [
    {"id": "T2-b1", "component": "definition", "text": "标准算法先做全局归一化，再逐步细化。", "basis": "external", "source_refs": ["TB-1"]}
  ]
}
```

IR 映射后，该页 paper 块保持 `basis=paper` + EV，教学块为 `basis=external` + `source_refs:["TB-1"]`；`semantic.explanation` 同时含 paper 义务与 teaching 义务。

---

## 附录 B：错误码

| 错误码 | 层 | 级别 | 含义 |
|---|---|---|---|
| `TEACHING_NOT_ENABLED` | pwf2rpa | error | paper_report 模式出现 teaching |
| `TEACHING_MODE_MISMATCH` | pwf2rpa | error | method_teaching 模式使用 attach |
| `TEACHING_SECTIONS_INVALID` | pwf2rpa | error | sections 数量/结构错误 |
| `TEACHING_PLACEMENT_INVALID` | pwf2rpa | error | placement 缺失/越界/多键 |
| `TEACHING_SOURCE_INVALID` | pwf2rpa | error | 来源 id/citation 错误 |
| `TEACHING_SOURCE_MISSING` | pwf2rpa | error | external 无 source_refs |
| `TEACHING_EVIDENCE_FORBIDDEN` | pwf2rpa | error | 非 paper 块写 EV |
| `TEACHING_ASSUMPTION_MISSING` | pwf2rpa | error | derived 缺 assumptions |
| `TEACHING_CONSTRUCTED_UNMARKED` | pwf2rpa | error | constructed 无标记 |
| `TEACHING_PAPER_EVIDENCE_MISSING` | pwf2rpa | error | paper 块无 EV |
| `TEACHING_ATTACH_TOO_MANY` | pwf2rpa | error | v1 attach 块数超限 |
| `PROVENANCE_BASIS_INVALID` | compiler | FAIL | basis 非法 |
| `PROVENANCE_PAPER_EVIDENCE_MISSING` | compiler | FAIL | paper 块/页无 EV |
| `PROVENANCE_EVIDENCE_FORBIDDEN` | compiler | FAIL | 非 paper 块写 EV |
| `PROVENANCE_SOURCE_UNKNOWN` | compiler | FAIL | source_refs 无法解析 |
| `PROVENANCE_SOURCE_UNVERIFIED` | compiler | REVIEW | 外部来源未核实 |
| `PROVENANCE_ASSUMPTION_MISSING` | compiler | REVIEW | derived 缺假设 |
| `PROVENANCE_CONSTRUCTED_UNLABELED` | compiler | REVIEW | 构造示例无标注 |
| `PROVENANCE_CONSTRUCTED_USES_PAPER` | compiler | FAIL | 构造示例用论文图 |
| `PROVENANCE_CONFLICT_DECLARED` | compiler | REVIEW | 显式冲突声明 |
| `PROVENANCE_MIXED_AMBIGUOUS` | compiler | REVIEW | 混合页来源归属不清 |
| `PROVENANCE_CORPUS_UNAVAILABLE` | compiler | REVIEW | 导入教学 IR 无证据语料，反重贴标签跳过 |
| `PROVENANCE_RELABEL_RISK` | agent | FAIL | 论文内容被标成教学 |
| `EXPLANATION_SOURCE_INVALID` | compiler | FAIL | teaching 义务 source_refs 空/无法解析 |
| `EXPLANATION_SOURCE_UNVERIFIED` | compiler | REVIEW | teaching 义务来源未核实 |

---

## 附录 C：改动文件总览

```text
新增
  Total-pipe/pwf2rpa/pwf2rpa/teaching.py
  Total-pipe/pwf2rpa/schemas/teaching-plan.schema.json
  Total-pipe/deck_compiler/provenance.py
  Total-pipe/agent/provenance.py
  Total-pipe/tests/fixtures/teaching/*
  Total-pipe/pwf2rpa/tests/test_teaching.py
  Total-pipe/tests/test_provenance.py
  docs/teaching-content-provenance.md

修改
  Total-pipe/pwf2rpa/pwf2rpa/story.py
  Total-pipe/pwf2rpa/pwf_to_rpa.py
  Total-pipe/pwf2rpa/README.md
  Total-pipe/pwf2rpa/schemas/story-plan.schema.json
  Total-pipe/agent/adapters.py
  Total-pipe/agent/runner.py
  Total-pipe/agent/mcp_server.py
  Total-pipe/deck_compiler/ir.py
  Total-pipe/deck_compiler/explanation.py
  Total-pipe/deck_compiler/quality_metrics.py
  Total-pipe/schemas/deck-ir.schema.json
  Total-pipe/skills/total-pipe-deck/SKILL.md
  Total-pipe/docs/USAGE.zh-CN.md
  Total-pipe/docs/deck-compiler-v2.md
  docs/explanation-contract.md
  docs/README.md
  README.md
```

不修改：`PaperWorkflow/**`、`research-ppt-assistant/**`、`Total-pipe/totalpipe_layout/**`、布局计算与 OfficeCLI 后端。
