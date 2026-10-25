# 讲解契约：从 Story 到 Deck IR 的可见结构

这套流水线里，Story Planner 不选版式，但必须说明**听众在这一页必须看见什么结构**。
`explain` 是这份说明的机器契约；Deck IR 的 `semantic.explanation` 是它在编译阶段的副本；
`derived/explanation_coverage.json` 是编译后的覆盖账本。

这样做的原因很具体：能力只写在 Skill 里，主 Agent 记得，Story 子代理看不到；IR 阶段靠临场记忆
补一个 `inline_math` 或 `graphics`，下一次换个人就丢。把“需要什么”写成产物，才能让下游验收。

## Story：`explain`

每个 `story[]` node 可带一个 `explain` 对象。它不是版式请求，不写组件名、坐标或颜色。

```json
{
  "question": "电学对照是否支持场诱导势垒？",
  "answer": "...",
  "evidence": ["EV0007", "EV0013"],
  "next": "...",
  "explain": {
    "reader_task": "distinguish",
    "must_show": [{
      "id": "ob-1",
      "kind": "parallel_items",
      "required": true,
      "primary": true,
      "content": {"items": ["Ti/Au–Si 接触 ≈10² Ω", "器件导通 ≈10⁵ Ω", "换源漏后整流近不变"]},
      "evidence": ["EV0007", "EV0013"],
      "source_quote": "Ti/Au–Si接触≈10^2 Ω vs 器件导通≈10^5 Ω"
    }],
    "must_not_lose": ["units", "uncertainty"]
  }
}
```

词表是闭集：

| kind | 读者要做什么 | 典型原生载体 |
|---|---|---|
| `quantity` | 精确读出一个量或公式 | `inline_math` / `formula` |
| `parallel_items` | 并列扫读 2–6 条、顺序可换 | 原生列表 / 表格 |
| `grouped_panels` | 看见 2–4 组层级或分组 | `layout_tree` 的 panel / columns |
| `comparison` | ≥2 个对象在 ≥2 个维度上并排 | 原生表格 / 双列 |
| `ordered_steps` | 跟 2–5 步固定顺序 | `process` / `dag` |
| `relation` | 追显式节点与有向边 | `mechanism` / `dag` |
| `curve` | 读一条示意趋势 | `path`（C/Q 贝塞尔） |
| `image_evidence` | 读一张实测原图 | `figure_refs` + `visual_plan` |

规则：

- 每条义务必须绑定本 node 的 `evidence`，不能引用 node 之外的 id。
- `source_quote` 可选；给了就必须能在引用证据里找到。
- 一页最多一个 `primary`。`required` 是硬约束，`required: false` 可以因容量降级。
- `must_show: []` 时必须写 `prose_ok_reason`。纯文字页是合法结果，不是失败。
- `curve` 必须写 `content.schematic: true`；管线画的曲线不能伪装成实测。
- 写了 `explain` 可以省略 `form`；required 的 `ordered_steps` / `comparison` 会推导 RPA 的
  `process_steps` / `comparison_dimensions` 计数，保留进入流程/表格布局池的能力。
- `form` 仍是兼容入口，但不表达列表、嵌套和曲线；新任务优先写 `explain`。

## Deck IR：`semantic.explanation`

IR 阶段把 brief 的 `metadata.story_explain` 原样带过来，并补上实际使用的载体：

```json
{
  "reader_task": "distinguish",
  "must_not_lose": ["units", "uncertainty"],
  "obligations": [{
    "id": "ob-1",
    "kind": "parallel_items",
    "required": true,
    "primary": true,
    "carrier": "native_list",
    "status": "bound",
    "content": {"items": ["Ti/Au–Si 接触 ≈10² Ω", "器件导通 ≈10⁵ Ω", "换源漏后整流近不变"]},
    "evidence_refs": ["EV0007", "EV0013"]
  }]
}
```

`carrier` 只能取 `inline_math / formula / native_list / table / layout_tree / process / dag /
mechanism / path / figure`。`status` 取 `bound / waived / unsupported`；后两者必须写 `note`。
不能因为放不下就删掉 required 义务；应回 Story/Binder 重规划，或明确记 `waived` 并说明原因。

## 覆盖账本

编译时 `derive()` 写出 `derived/explanation_coverage.json`（只在 IR 含 `semantic.explanation` 时）。
每个义务记录：

- 声明的 `carrier`；
- IR 实际找到的 `found_carriers`；
- `status`：`satisfied / waived / unsupported / missing`；
- 汇总 `summary.total / satisfied / waived / unsupported / missing`。

判定规则：

- `parallel_items` 可由原生列表、表格或 `layout_tree` 承载；
- `grouped_panels` 需要 `layout_tree`；
- `comparison` 需要表格或双列树；
- `ordered_steps` 需要 process/dag，原生有序列表只能算降级；
- `relation` 需要 mechanism/dag，`curve` 需要 path，`quantity` 需要行内公式或独立公式；
- `image_evidence` 需要 `figure_refs`；
- 列表/表格/分组/顺序/对照的 `content` 还必须出现在页面可见文字里；只加一个空列表不算完成。

结构错误（未知 kind、重复 id、证据不绑定、waiver 无 note）是 **FAIL**；
required 义务没有载体、或声明内容不可见，是 **REVIEW**。这样候选仍可生成，但不会被误报为
“设计已经覆盖”。

## 责任边界

| 决策 | 负责者 |
|---|---|
| 这页需不需要公式、列表、嵌套、流程或曲线 | Story Planner（`explain.must_show`） |
| 用哪个原生对象、放不放得下 | Binder / IR 映射 / Compiler |
| 整套配色、强调和副标题处理 | Scientific Visual Planner |
| 是否真的做到 | 覆盖账本 + QA |

Story 只判断“需不需要讲成这个结构”，不判断“画哪个组件”。组件由 Binder 和编译器按能力、
容量与证据关系选择；这样换渲染器时 Story 不需要重写，容量不足时也有地方回退。
