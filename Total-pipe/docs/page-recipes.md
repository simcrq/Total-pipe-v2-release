# Page recipes pilot

状态：**最小闭环验证通过，尚未接入 job 状态机**。

## 问题

设计方在开放 PageScene 上自由发挥，同时审查会退回任何偏差；它的最优策略是
纯文字/卡片，而不是原生列表、行内公式、路径或表格。继续增加能力说明不会改变
这个策略。

## 做法

`agent/page_recipes.py` 把“设计”收成 recipe + slots：

| recipe | slots | 默认原生动作 |
|---|---|---|
| `cover` | figure, title, take, stats | 原图 + 行内公式 + 无卡片数字行 |
| `contrast` | left/right lists, key | square/dash 两套原生无序列表 + 原生路径波形 |
| `figure_readout` | figure, items | 原图 + 箭头读图列表 |
| `metrics` | figures, items, condition | 两张原图 + 原生列表 + 行内公式 |
| `mechanism` | items, formula | 无图机制页：原生列表 + 可选公式 |
| `panel_grid` | figures, items, caption | 2–3 面板原图 + 读图列表 |
| `table_compare` | table, big, items | 原生表格 + 大号数字 + 原生列表 |
| `closing` | big, items, stats | 大号数字 + 两级原生列表 + 行内公式 |
| `eviz_chain` | eviz.spec, eviz.facts | 复用 EViz `validate_spec` + `templates.build`；进程链降为原生 path/label，不再画卡片 |
| `svg_diagram` | svg / svg_path, box | 模型 SVG → 原生 text / rect / circle / path（弧展平）/ marker 箭头 |

设计方不写坐标、不选形状、不写 OMML。几何和原生能力由 recipe 兑现。
`page_design` prompt 现在也带 `recipes`，页面可选填 `recipe` + `slots`；`page_catalog`
会把它们传给 PageScene。当前 pilot 仍是 PageScene 层选 recipe，design 层直出 recipe 尚待全链路回归。

## 验证

8 页 pilot 在 `E:\ppt_x\AVDG_recipe_pilot`：

- `text_only_pages=0`
- `card_area=0.0`
- `inline_math=10`
- `list_styles=[arrow,dash,dot,square]`
- `native_move_pages=8/8`
- PageScene QA PASS，native PDF 6 页，`native_items=0`
- `officecli validate` PASS
- 32 个回归测试 PASS

pilot 证明：**不用卡片、用原生列表和行内公式，可以由 recipe 默认路径生成**。

## 尚未接入

- EViz 只接了 `process_steps@1`，尚未接 `layer_stack@1` / `peel_angle@1`；
- SVG 导入只覆盖 text/rect/circle/line/path/polygon 和简单 marker；渐变、filter、transform、clipPath 尚未覆盖；
- recipe 页已可由 `page_scene_binding.bind` 先展开再走原有科学/数字/可见文案门禁；但 `page_design` 还没有 recipe 字段；
- slots 仍直接写字符串，还没走 approved copy / `content_map`；
- 只覆盖 6 类页面，还需要 mechanism、panel_grid、roadmap；
- style 审查尚未从 hard fail 降为 advisory。

接入顺序见 `PILOT_QA.md` 的“下一步”。
