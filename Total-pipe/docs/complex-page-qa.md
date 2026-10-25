# 复杂页 QA、密度与维护

适用于 layout tree、原生科研图形、独立 / 行内公式和原生表格页面。
结构与容量检查、候选逐项审核、PowerPoint 原生验收分别记录；候选审核笔记不改变正式 final 门禁。

## 文本溢出的判定

OfficeCLI `OFFICECLI_FORMAT` 中的 `Text overflow` **警告估计**进入统一 QA 时记为 INFO，
附 `source.measurement=officecli_heuristic`、`native_verification_required=true` 与原始严重度。
原始消息和严重度仍完整保存在 `officecli_issues.json`。其他 WARNING 和全部 Error 保持原级别。
`review-officecli` 仅因真实 WARNING / FAIL、schema 错误或结构 FAIL 拒绝候选，
只有启发式溢出或其他 INFO 时返回 `AWAITING_VISUAL_REVIEW`。

字体回退、CJK 断行及 OMML 基线会使 OfficeCLI 的行高估计与实际页面不同。
不能仅按 `suggest.height` 删正文或缩字号；先在 PowerPoint 核对实际边界、遮挡和字体。
原生 PDF 的文字 / 字体检查提供证据，仍不能取代直接 UI 眼检。
这次变更没有把 PowerPoint COM 文本框度量接入编译器，也没有声称 INFO 就代表无溢出。

## stack 的留白与显式分配

`stack` 保留默认 `align: "start"`：按实测 minimum → preferred 贴合内容，余量留在底部。
没有显式 weights 时可选 `center` 将内容组垂直居中，或 `distribute` 在实测高度之上按比例分配余量。
两者都保留原文、原生公式和字号下限。显式 weights 本身按比例铺满，因此只能省略 align 或写 start。

```json
{"id":"rows","type":"stack","align":"distribute","gap":"standard",
 "children":[{"id":"diagram-leaf","type":"graphic","ref":"diagram"},
             {"id":"explanation-leaf","type":"block","ref":"explanation"}]}
```

默认贴顶 stack 的未分配高度超过该 stack 高度的 15% 时，QA 产生 `PAGE_UNDERFILL` REVIEW。
`layout_feedback.json` 同时包含 `component`、`underfill_px`、`underfill_ratio`、`available_size_px`
和 `suggested_actions`；存在可行比例时提供 `suggested_weights`。建议值已归一化到 `[0.1,10]`，
并检查各子项满足实测硬下限。它们是相对权重，不是像素值。改后仍须重新编译。
`layout.json` 对应 stack 节点的 `underfill` 保留测量明细。

该规则测量布局树中分配区域的剩余高度，不是像素级图像密度评分；适当留白可以审核接受。
显式 center / distribute 与已分配 weights 不发该提示。已有纯文字页的
`TEXT_ONLY_LOWER_WHITESPACE` 提示继续保留，平面页没有通用 weights 建议。

## 候选的逐项签收

在 `Total-pipe/` 运行：

```bash
# 默认显示未签收项，保留 FAIL、WARNING、INFO
python -m deck_compiler qa --out <build-dir>

# 真实复核后，使用当前 qa_report.json 的 REVIEW id
python -m deck_compiler ack-review --out <build-dir> \
  --reviewer '<审核者>' --note '<核对内容与结论>' --ids <review-id> <another-review-id>

# 展开全部记录
python -m deck_compiler qa --out <build-dir> --include-acked
```

MCP 对应 `totalpipe_qa(out, include_acked?)` 和
`totalpipe_ack_review(out, reviewer, note, review_ids)`。重载服务后新工具才会可见。
不自动批量接受 REVIEW；必须明确选择 ID 并填写真实审核说明，FAIL 不能签收。

完整 `qa_report.json.items` 始终保留全部发现，签收项增加 `ack: {by, at, note}`；
`counts.REVIEW` 继续统计总数，`acked_count` / `unacked_count` 区分已签收与待复核数量。
状态仍可能是 REVIEW。`qa` 默认视图隐藏已签收项，`build` / `compile` / `generate` 摘要显示待复核数。
增量记录保存在同目录的 `qa_acknowledgements.json`，重建时不删除它。

`review_key` 使用规则、稳定 slide ID、shape / component（无对象时使用消息）及 detector；
`review_signature` 绑定该发现、页面内容、实际几何、主题、资源和字体。
后端发现还绑定该页 PPTX 包依赖和 OfficeCLI 运行版本；原生文本发现绑定该页 PDF 字形证据。
输入、布局或相关产物改变后旧签收失效，未改变的页面可保留记录。
全局项保守绑定全套输入；不能从旧 `qa_report.json` 的 ack 字段直接恢复签收。

这些笔记只帮助候选复审。`promote --ack` 仍要求当前 staging 文件哈希、真实审核者和全部
REVIEW ID，另检查完整 PowerPoint UI review、原生 PDF、OfficeCLI provenance 和结构证据。
候选 `unacked_count=0` 不能代替正式验收。

## 图形编辑与 provider 边界

复杂原生图形由独立 shape、文字、关系标签、T 端帽、层容器及连接符组成，尚无 `p:grpSp` 编组。
拖动节点不会自动移动独立文字和标签；PowerPoint 重新布线可能穿越其他节点。
持久修改优先改 canonical Deck IR 的结构、weights、gap 或 align 后重建。
需要手工微调时，在选择窗格中选全相关对象，必要时自行组合；编辑后重新核对文字和路由。
原文件本来没有组，无需“先解组”。手改产物不会回写 IR，重建会覆盖。

树、视觉计划、数学、显式列表和原生图形页面由编译器布局，`COMPILER_OWNED` 是正常状态。
全部页面 owned 时 provider coverage 为 null，不能据此判定生成失败。
本次没有增加树的 provider 权重接口；现有调整入口是 canonical IR，
不能让平面 provider 覆盖复杂叶节点的最终 bbox。详见[提供方协议](layout-provider.md)。

## 对所附 Windows 报告的审阅

2026-10-25 根据 `bad9a9d` 源码核对用户提供的 9 页 Windows 实测报告。
该 deck 与 COM 输出未随报告提供，13 / 1 条溢出及 64 条 REVIEW 是报告数据，不是本次独立复测结论。

| 报告事项 | 处置 / 校正 |
| --- | --- |
| OfficeCLI 估计与实际页面不同 | 降级警告估计、保留原 issue，并修复截图检查把 INFO 也当拒绝的行为 |
| 默认 hug 造成剩余空间 | 保持既有默认几何，新增 stack 对齐、15% 提示和合法权重建议 |
| 候选无法逐项记录已审核项 | 新增增量签收和待复核视图；正式 final 仍按当前产物完整审核 |
| 无编组、provider 不接管复杂页 | 明示边界与维护方式；不以放宽 bbox 覆盖代替专用测量 |
| “QA 无留白规则” | 已有纯文字页规则，本次补充的是布局树 stack |
| “正文与图注下限均 18 pt” | 正文下限 18 pt；图注、caveat 等注释角色下限是 15 pt，具体字号由模板决定 |
| “三节点 DAG 最少 728 px” | 728 px 是三节点 process 的宽度下限；DAG 按实际分层、文字和路由测量 |
| “caveat 固定 46 px / 20 pt” | 模板有 36 / 46 px 等槽位；代码字号单位为 CSS px，20 CSS px 是 15 pt |

公式宏的受限语法、行内公式作用域和树 / 表格规模仍以当前 Schema、解析器与
[公式协议](deck-compiler-v2.md#formulas-component-formula)为准。受限语法不是通过删改科学表达式来消除的 QA 噪声。
