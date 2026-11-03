# 设计层：设备清单（art direction）

Deck 的观感不是由「版式」决定的，而是由一页里做了哪几个视觉决定决定的：这句里的哪个词该被看见、
两三条陈述是不是三个带标签的组、这张图出自哪篇文献、这一页的结论是不是看起来像结论、
整篇有没有目录。这些决定以前全部散落在 IR 的可选字段里——可选字段没有触发条件，就等于不存在。
真实数据：两份真 deck、35 个文本块、4 张论文图、3 个面板，`source_label` 用了 0 次、
`title_fill` 用了 0 次、`section` 用了 0 次。

设计层（`page_design` 阶段）现在多了一件事：**为每页点名要用的设备**。

## 为什么现在敢用

以前不用这些能力，是因为每一项都可能撞上容量门禁：chip 太宽、目录页多一页、图注超出两行。
一个知道「每次使用都可能失败」的设计者，最理性的选择是不用。

所以设计层的前提不是加词汇，而是**给每个设备一条退化路径**：

| 设备 | 退化 |
| --- | --- |
| `panel-group` 标签组 | chip 标签 → 整行色带 → 普通带框分组 |
| `agenda` 目录页 | 不生成（`AGENDA_EMPTY`），页码照常连续 |
| `caption-source` 图注出处 | 只留图注本体 |
| `emphasis` / `highlight` | 按真实粗体测宽，最坏多占一行 |
| `takeaway-frame` 结论框 | 退回普通结论行 |

设备不会把构建打红，所以「不用」不再是安全选择。设计提示词里写死了这条：设备一律退化而不是失败，
**不许为了稳妥而不用**；一页确实不用任何设备时，必须在 rationale 里说明原因。

## 清单

页级（`pages[i].devices`）：

| 设备 | 取值 | IR 落点 |
| --- | --- | --- |
| `emphasis` | 1–3 个精确短语 | 文本里的 `**短语**` |
| `highlight` | 1–2 个精确短语 | 文本里的 `==短语==` |
| `panel-group` | 2–3 个 ≤8 字标签 | layout_tree 里带 `frame.title_fill` + `title_band:"chip"` 的 panel |
| `caption-source` | `[{figure: 序号, label: ≤80 字}]` | `figure_refs[i].source_label` |
| `takeaway-frame` | `fill` / `outline` | `slides[i].presentation.takeaway_frame` |
| `sequence-rail` | 无 | 有序流程的编号轨道 |

篇级（与 `pages` 同级的 `devices`）：

| 设备 | 取值 | IR 落点 |
| --- | --- | --- |
| `sections` | ≥2 个 `{page: 页 id, label: ≤24 字}` | `slides[i].presentation.section` |
| `agenda` | `true` 或 `{title}` | `presentation.agenda` |
| `footer` | 一行 ≤120 字 | `presentation.footer` |
| `page-numbers` | true / false | `presentation.page_numbers` |

## 谁来写

- **机械设备由编译器写**（`art_direction.apply`）：文本标记、图注出处、结论框、章节、目录、页脚、页码。
  作者手抄一遍就等于会丢一遍；这些在 IR 校验之前直接写进去，作者就算忘写也不会漏。
- **结构设备由作者建**（`panel-group`）：把页面拆成两三个 panel 是版面结构，编译器不替你重排。
  写没写由 `art_direction.check` 核对，缺了就是 `DESIGN_REALIZATION_FAILED`——设计说要做的事，
  IR 不能当没发生。

## 校验边界

设备校验只看形状（名字在清单里、取值个数与长度），**绝不判断它在页面上会占多少空间**：

- 保留（内容不变式）：每个 Story 条目恰好用一次；数字只能来自所引证据；证据引用必须存在。
- 不保留（版式门禁）：设备不因「可能放不下」被拒绝；放不下的处理是退化 + REVIEW，而不是不用。

## 怎么加一个设备

1. 在 `deck_compiler/art_direction.py` 的 `DEVICES` 里加条目：`scope`、`slot`、`shape`、`ir`、`use`、`fallback`。
2. 写进 `_errors`（形状校验）、`apply_page`/`apply_deck`（能机械写入的）与 `check`（怎么算落地）。
3. 在编译器里给它一条退化路径；没有退化路径的设备不要进清单。

代码：`deck_compiler/art_direction.py`、`deck_compiler/design.py`（`validate_design` / `summary` /
`capabilities`）、`agent/adapters.py`（`apply_art_direction`、`check_ir`、设计提示词）。
测试：`Total-pipe/tests/test_art_direction.py`。
