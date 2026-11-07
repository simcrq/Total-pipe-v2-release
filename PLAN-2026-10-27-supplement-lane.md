# TotalPipe Supplement Lane 实施版（B：页内 + 少量独立补充页）

> 日期：2026-10-27　状态：S1/S2/S3 与 v0.6（supplement explain）完成；全量回归 416 项 0 failure，17 项环境错误（缺 jsonschema / Windows symlink 权限）
> 分支：`feat/supplement-lane`
> 决策：用户选择 B —— 允许页内补充块 + 少量独立补充页（页数不限）
> 取代：[teaching 子系统方案](PLAN-2026-10-27-teaching-provenance.md)（已标注范围修正，不再作为实施依据）
> 目标：AI 为“讲好”可以顺手加背景、类比、例子、解释图；论文事实仍严格由 EV 约束；补充内容不被误认为论文内容。

---

## 1. 一句话方案

在 Deck IR 的 block 上加一个可选标记：`basis: supplement` + `supplement` 对象。论文块仍是 `basis: paper`（默认）且必须有 EV；补充块不写 EV、可选来源、构造示例必须可见标注。补充内容只在 IR 阶段加入，不经过 Story/pwf2rpa/RPA；编译器做 4 条确定性检查，质量指标不再惩罚无论文的补充页。

---

## 2. 范围

### 2.1 做

- 页内补充：论文页里加背景定义、类比、解释句、公式说明、对照文字。
- 独立补充页：页数不限，用来放先修概念、示意流程、简化算例、对比表；建议每页只讲一件事。
- 论文页 + 补充块同页混合；按块区分 `paper` / `supplement`。
- 补充块的来源：可选一行 `source`；不写只标 INFO。
- 构造示例：`constructed: true` + 可见“示意/构造/简化”标注。
- 默认关闭；`supplement: off|inline|pages|both`。

### 2.2 不做

- 不做 teaching plan / 教学规划器 / 受众模型。
- 不做来源注册表、逐条核实、联网核验。
- 不做 Story/pwf2rpa/RPA 改动。
- v0.6 已追加 explanation 的 `basis=supplement` 义务；paper 义务规则不变。
- 不做完整混合图形页（论文图 + 教学图 + 示例表同页）；只做“论文内容 + 1–2 个补充文字块”的轻混合。
- 不做纯补充 deck（必须有论文页；补充页是附加）。

---

## 3. 数据契约

### 3.1 block

```json
{
  "id": "b3",
  "component": "definition",
  "text": "补充：梯度下降是一阶迭代优化方法。",
  "basis": "supplement",
  "supplement": {
    "kind": "background",
    "source": "Sutton & Barto, Reinforcement Learning, 2nd ed., ch. 3",
    "constructed": false,
    "assumptions": []
  }
}
```

规则：

| 字段 | 规则 |
|---|---|
| `basis` | `paper`（默认）或 `supplement`；旧 IR 无此字段 = paper |
| `supplement.kind` | `background / analogy / example / derivation / diagram / comparison` |
| `supplement.source` | 可选，自由文本；空 = INFO“未注明来源” |
| `supplement.constructed` | `true` 时必须有可见“示意/构造/简化/示例”标注 |
| `supplement.assumptions` | 仅 `kind=derivation` 使用；空 = INFO“未写假设” |
| 禁止 | `basis=supplement` 的块写 `evidence_refs`；`basis=paper` 的块带 `supplement` 对象 |

### 3.2 slide

- **补充页**：`semantic.evidence_refs: []`；所有 block 都是 `basis=supplement`；至少 1 个 block。
- **混合页**：既有 `basis=paper` 块，也有 `basis=supplement` 块；`semantic.evidence_refs` 只放论文块的 EV。
- **论文页**：保持现状，无 supplement 块。
- 补充页可以没有 `semantic.explanation`；有的话义务写 `basis=supplement`、不写 `evidence_refs`，paper 义务仍是 `basis=paper` + EV。
- 补充页的 `semantic.title/takeaway` 也是补充内容，不要求 EV。

### 3.3 页面数量

- `supplement=inline`：只加块，不新增页。
- `supplement=pages|both`：允许新增页，**页数不限**；不设 `supplement_max_pages`。
- 唯一软信号：补充页数超过论文页数时，QA 记一条 `SUPPLEMENT_RATIO_HIGH` **INFO**（不阻塞），提示检查是否讲得过多；是否调整由 Agent/用户判断。
- 新增页插在 RPA 规划页之间或之后；`check_ir` 的 `len(slides) >= len(briefs)` 已允许。
- `slide_count` 仍按 RPA brief 计；补充页是额外页，不改变 `slide_count` 语义（文档写明）。

---

## 4. 校验规则（只有 4 条）

| 规则 | 级别 | 落点 |
|---|---|---|
| 补充块里出现论文数值/单位、EV 长原文、论文图（补充页无 paper 块） | **FAIL** | `agent/adapters.check_ir` + `provenance.py` |
| `constructed: true` 但页面无可见“示意/构造/简化/示例”标注 | **REVIEW** | `provenance.py` |
| 补充块 `source` 为空 | **INFO** | `provenance.py` |
| `basis=supplement` 但 `supplement` 缺失/非法，或 `supplement` 模式下页面没有补充内容 | **FAIL** | `ir.py` / `provenance.py` |

补充说明：

- “论文数值/单位”检测：从 normalized evidence 文本抽取数字+单位 token；补充块出现同 token 即 FAIL。
- “EV 长原文”检测：CJK ≥12 字或拉丁 ≥8 词的连续重合；命中即 FAIL。
- “论文图”检测：补充页引用 `assets.origin=paper` 的图，且页面没有 `basis=paper` 块 → FAIL。混合页允许论文图 + 补充块（这正是“解释论文图”的常见用法）。
- 构造标注允许中英文：示意 / 构造 / 简化 / 示例 / schematic / constructed / illustrative。
- 补充页正文不能出现 `EV####`（现有 RPA 的 `EVIDENCE_ID_LEAKED_TO_SLIDE` 也会警告）。
- 非阻塞 INFO：`SUPPLEMENT_RATIO_HIGH`（补充页数 > 论文页数）只提示，不阻断；补充页页数不限。

---

## 5. 代码改动

> 只改 IR 与 Agent 提示/校验；Story、pwf2rpa、RPA、PWF、布局计算、OfficeCLI 不动。

| 文件 | 改动 | 预估 |
|---|---|---|
| `Total-pipe/schemas/deck-ir.schema.json` | block 增加 `basis`、`supplement`；条件：supplement 时必填 supplement，paper 时禁止 supplement | 40 行 |
| `Total-pipe/deck_compiler/provenance.py` | 新增：block 结构、构造标注、paper 图误用、source 空 INFO | ~150 行 |
| `Total-pipe/deck_compiler/ir.py` | 调用 `provenance.validate`；block 基础检查 | 15 行 |
| `Total-pipe/deck_compiler/quality_metrics.py` | 全 supplement 页不再报 “No evidence citations”；加 `supplement_slides` 统计 | 25 行 |
| `Total-pipe/agent/adapters.py` | `start`/request 增加 `supplement`；`ir_prompt` 追加补充内容规则；`check_ir` 做论文泄漏检查与补充页比例 INFO | 80 行 |
| `Total-pipe/agent/runner.py` | `start(..., supplement='off')`；请求字典 | 10 行 |
| `Total-pipe/agent/mcp_server.py` | `totalpipe_start` schema 增加 enum | 5 行 |
| `Total-pipe/deck_compiler/mcp_server.py` | 无需改；`capabilities` 可加 `supplement` 标记（可选） | 0–5 行 |
| `Total-pipe/tests/test_supplement.py` | 新增：结构、构造标注、泄漏、质量指标 | ~180 行 |
| `Total-pipe/tests/test_agent_adapters.py` | 补 `check_ir` 开关/泄漏用例 | ~40 行 |
| `Total-pipe/examples/supplement/` | 一个最小 IR + 说明 | 2 文件 |
| `Total-pipe/docs/deck-compiler-v2.md` | “补充内容”协议 | 20 行 |
| `Total-pipe/docs/USAGE.zh-CN.md` | 用法与限制 | 20 行 |
| `Total-pipe/skills/total-pipe-deck/SKILL.md` | IR 阶段怎么加、加多少、怎么标 | 30 行 |
| `README.md` / `docs/README.md` | 能力条目 | 5 行 |

### 5.1 `ir_prompt` 追加内容（示意）

```text
If request.supplement is not "off", you may add supplementary content that is not
from the paper (background, analogy, a constructed example, a derivation step, an
illustrative diagram, a comparison). Mark every such block:
  "basis": "supplement",
  "supplement": {"kind": "...", "source": "...", "constructed": false}
Never put evidence_refs on a supplement block. Never put a paper number, unit,
figure or a long verbatim passage from the evidence into a supplement block.
If you use a paper figure on a supplement page, keep at least one paper block with
the correct EV on that page. Add as many supplement pages as the explanation needs;
keep each page focused. A constructed example must be visibly labelled
(示意/构造/简化/示例).
```

### 5.2 `check_ir` 泄漏检查（伪代码）

```python
def supplement_leaks(ir, normalized):
    ev_texts = [e.get("text", "") for e in normalized.get("evidence", [])]
    numbers = {tok for text in ev_texts for tok in numeric_tokens(text)}
    for slide in ir["slides"]:
        has_paper = any(b.get("basis", "paper") == "paper" for b in blocks(slide))
        for block in supplement_blocks(slide):
            text = block.get("text", "")
            if any(tok in text for tok in numbers):
                fail("SUPPLEMENT_PAPER_NUMBER", block)
            if longest_overlap(text, ev_texts) >= 12:  # CJK chars; Latin 8 words
                fail("SUPPLEMENT_PAPER_QUOTE", block)
            if not block["supplement"].get("source"):
                info("SUPPLEMENT_UNCITED", block)
        if is_supplement_only(slide) and has_paper_figure(slide) and not has_paper:
            fail("SUPPLEMENT_PAPER_FIGURE", slide)
```

实际实现放在 `agent/adapters.py` 或独立 `agent/supplement.py`；阈值集中常量。

---

## 6. 页面怎么加

1. RPA 规划出论文页 `deck_plan.json`。
2. Agent 映射 IR 时：
   - 页内补充：在对应页 `composition.blocks` 加 supplement 块；
   - 独立补充页：新增 slide，`semantic.evidence_refs: []`，`composition` 用现有 archetype（建议 `composite-research` / `process-flow` / `equation-derivation` / `cover-hero` 的纯文字变体）；图形用 `graphics` / `layout_tree` / `tables`。
3. 编译器正常测量容量；`layout_feedback` 提示放不下时，减少块或拆页；不允许删论文原文。
4. Design 阶段照常处理所有页；补充页也进 `visual_prompt.json`。
5. Build/QA 照常；补充页只多出 `SUPPLEMENT_UNCITED` INFO、构造标注 REVIEW 等。

---

## 7. 质量指标

`analyze_completeness` 改为：

- 逐页判断：
  - 有 `basis=paper` 块或 `semantic.evidence_refs` 非空 → 按原规则要求 evidence citations；
  - 全是 supplement 块 → 不报 “No evidence citations”，改记 `supplement_slides`；
  - 混合页 → 只按 paper 块/refs 判断。
- `details` 增加 `supplement_slides`、`supplement_blocks`、`uncited_supplements`。
- 总分不因补充页扣分；`SUPPLEMENT_UNCITED` 只作为 INFO/REVIEW 提示。

---

## 8. 测试

### 8.1 单元

- schema/`ir.validate`：supplement 缺对象、paper 带 supplement、非法 kind → FAIL。
- `provenance.validate`：
  - 构造示例无标注 → REVIEW；
  - 补充页用 paper 图且无 paper 块 → FAIL；
  - source 空 → INFO；
  - 正常补充页 → 无 issue。
- `quality_metrics`：补充页不扣分；论文页仍按 EV。
- `check_ir`：`supplement=off` 出现补充块 → FAIL；`pages` 页数超限 → FAIL；论文数值/长引用 → FAIL。

### 8.2 集成

- 在 `examples/complex-mixed` 或 `compact-explain-test` 上加 1 个 supplement 块 → `compile` 成功，无 FAIL。
- 新增 1 页补充页（流程/公式）→ `compile` 成功，QA 只有 INFO/REVIEW。
- 论文页 + 补充块混合 → `compile` 成功，论文 `evidence_refs` 不变。
- 旧 IR → `compile` 输出不变。

### 8.3 负向

- 补充块写“本文在 ImageNet 上达到 95%” → FAIL。
- 补充块复制 EV 原句 → FAIL。
- 补充页使用论文图且无 paper 块 → FAIL。
- 构造示例无“示意”标注 → REVIEW。
- 补充块写 `EV0007` → FAIL（结构 + RPA 泄漏）。
- `supplement=off` 时 Agent 加补充页 → FAIL。

---

## 9. 分阶段（3–4 天）

| 阶段 | 内容 | 产出 | 预估 | 退出条件 |
|---|---|---|---|---|
| S0 | 冻结字段名/错误码/规则；确认 4 条规则 | 本文件 | 0.5 天 | 无异议 |
| S1 | schema + `provenance.py` + `ir.py` + 质量指标 + 单测 | 教学 IR 可编译/可拦截 | 1 天 | `test_supplement.py` 绿；旧 examples 不变 |
| S2 | Agent：`supplement` 开关、`ir_prompt`、`check_ir` 泄漏、MCP schema；集成测试 | 端到端 IR 加补充 | 1 天 | `supplement=off` 零变化；`pages` 跑通 |
| S3 | 文档、示例、Skill/Usage、README；手工跑一篇真实论文 | 可交付 | 0.5–1 天 | 验收清单通过 |

总计 **3–4 天**。

---

## 10. 验收

| 项 | 判定 |
|---|---|
| 原有论文 deck 不退化 | `supplement=off` 快照一致；现有测试全绿 |
| 页内补充可编译 | 示例 + 集成测试 |
| 独立补充页可编译 | 示例 + 集成测试 |
| 补充页不被 QA 误判 | `quality_metrics` 无 “No evidence citations” |
| 构造示例不冒充实验 | REVIEW 规则 + 负向测试 |
| 论文数值/图/引用不泄漏 | FAIL 规则 + 负向测试 |
| 来源缺失不阻塞 | INFO |
| 旧 IR / 旧 build 可读 | 回归测试 |
| 跨平台协议 | schema + CLI/MCP 可选 |

---

## 11. 风险与限制

- **独立补充页不经过 RPA**：版式由 Agent 手写 IR，容量靠编译器；复杂页可能多迭代一次。v0 建议补充页用 1 个主图形 + 3–5 个短块。
- **没有来源核实**：`source` 只是一行文本，未写标 INFO；不承诺“外部事实已验证”。
- **explanation 已支持 `basis=supplement`**：补充页可声明 `must_show`，不写 EV；不承诺论文式来源审计。
- **泄漏检测是启发式**：数字/长引用/论文图能抓，语义改写抓不到；需要人工抽查。
- **Agent 可能过度添加**：不设硬上限；`SUPPLEMENT_RATIO_HIGH` 只在补充页超过论文页数时给 INFO，由 Agent/用户判断是否精简；`supplement=inline` 时只允许页内块。
- **混合页容量**：只支持 1–2 个文字块；图 + 图 + 表同页放 v0.6。

---

## 12. 明确不做

- 不改 Story / pwf2rpa / RPA / PWF / 布局计算 / OfficeCLI。
- 不做 teaching plan、来源注册表、教学规划器、受众模型。
- 不做全局 `disable_evidence_validation`。
- 不做纯补充 deck；论文页仍是主体。
- 不做自动语义矛盾检测；补充内容与论文冲突时靠人工 REVIEW。

---

## 13. 最小示例

```json
{
  "id": "supplement-gradient",
  "semantic": {
    "title": "先修：梯度下降在做什么",
    "purpose": "补充背景，帮助理解论文优化过程",
    "takeaway": "梯度下降沿负梯度方向迭代；这是标准教材内容，不是本文结果。",
    "evidence_refs": [],
    "caveats": [],
    "speaker_notes": "补充页，不引用论文证据。"
  },
  "composition": {
    "archetype": "process-flow",
    "blocks": [
      {
        "id": "s1",
        "component": "definition",
        "text": "梯度下降是一阶迭代优化方法：计算梯度、取步长、更新参数。",
        "basis": "supplement",
        "supplement": {"kind": "background", "source": "Sutton & Barto, ch. 3", "constructed": false}
      },
      {
        "id": "s2",
        "component": "formula",
        "text": "\\theta_{t+1} = \\theta_t - \\eta \\nabla L(\\theta_t)",
        "basis": "supplement",
        "supplement": {"kind": "derivation", "source": "标准教材推导", "assumptions": ["L 可微", "学习率固定"]}
      }
    ],
    "figure_refs": []
  },
  "presentation": {}
}
```
