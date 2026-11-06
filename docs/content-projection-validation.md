# 内容契约 1.2 实现与验证

日期：2026-11-06。独立分支 `codex/audience-preview-loop`，基线 `f82b3b9`，本记录描述工作副本中的实现，
不是已发布插件或当前论文任务的完成声明。前一阶段的[选页预览](agent-ir-preview-validation.md)继续保留。

## 完成的工程变化

- Story 新增 content_contract 1.0：用稳定路径分类可见要求，绑定条件作用范围，完整科学正文不再承担投屏文案职责。
- 页面设计 1.2 新增 display_copy/content_map，允许忠实改写；科学记录只分配一次，必要限定可以随主张跨页显示。
- 新增 page_review：主 Agent 实际审读科学忠实性、限定范围和观众文案，逐页填写具体说明并绑定源文件哈希。
  代码不生成自动通过记录。格式/缺项/过期记录只退回修复审读记录；实际 fail 退回页面设计。
- IR 通过 copy_ref 绑定批准文案，自动归档完整科学记录、上下文限定和来源，冻结 content_projection。
- 验收分别检查科学归档与真实页面对象；notes、explanation 元数据和投影快照不算可见内容。
  未批准的新增正文、丢失的关键条件/负面对照、过期审读和投影篡改被拒绝。
- 原生图、表、数据图、公式和原图仍使用既有科学/尺寸/来源门禁。视觉载体的科学含义保留 REVIEW，
  不把对象存在误报成机器已理解图中证据。
- 旧 1.0/1.1 恢复路径保留。有新 content_contract 的任务不能降级到旧设计以绕过新验证。
- Supplement copy 继承 basis/source/constructed；论文数值和长原文泄漏检查继续执行，未放宽原门禁。

完整字段与操作：[内容契约](../Total-pipe/docs/content-projection.md)。

## 已执行的回归

| 分组 | 结果 | 范围 |
| --- | --- | --- |
| 接入层 test_agent_*.py | 125 通过 | 模型/provenance、组件推进、旧协议、状态、修订、预检、预览、原生接入及实际 OfficeCLI 构建 |
| 新内容契约 test_content_projection.py | 18 通过 | 合法改写、条件随主张、负面结果、记录/可见覆盖、禁止新增正文、审读哈希及阶段、版本降级、Schema、Supplement、原生图和候选全路径 |
| 页面设计 1.0/1.1 回归 | 25 通过 | 保留旧协议行为与来源绑定 |
| pwf2rpa Story 回归 | 31 通过 | 旧 Story 格式、证据、委派、解释义务与转换 |
| Supplement Agent 回归 | 9 通过 | 数值/原文泄漏、独立补充页和归属 |

以上按测试分组计 **208 项**；变更中还单独复跑 IR 22 项、状态 10 项，不重复计数。
分组在实现过程中分批执行；新增契约的 18 项是最后一轮结果。原始日志保存在本机忽略的 build/ 下：
contract-agent-tests.log、content-projection-tests.log、contract-story-tests.log、contract-supplement-tests.log、
contract-ir-regression.log、contract-state-regression.log。`git diff --check` 通过。

测试里的 test-model、Synthetic test reviewer、固定 Story/设计均是明确的软件 fixture；
测试辅助函数不属于运行时，不代表真实模型调用、论文证据审读或生产通过记录。
没有伪造独立子代理调用，也没有新增隐藏模型调用。

## 独立编译与实际看图

- 用包含科学记录/观众表达快照的四页合成样例，另启 `python -m deck_compiler compile`，
  验证不经 Agent 导入也可独立使用。结果 **0 FAIL / 0 WARNING / 9 REVIEW / 4 INFO**，未签收 REVIEW。
- 新契约集成测试实际走完 workflow → Story fixture → RPA → page_design 1.2 → 显式 review fixture →
  IR → OfficeCLI 可编辑 candidate；仍受完整既有 QA 约束。
- 对四页合成样例调用实际 OfficeCLI HTML 预览并逐页打开 PNG，检查主张、条件、负面结论和讲稿归属。
  P1 的非必要核查句只在科学归档/讲稿；P2 的数字、任务条件和负面解释边界可见；P4 的局限可见。
  无文字截断或重叠。该样例为稀疏的协议冒烟检查，不是科研页面设计范例。
- 本地输入/编译结果/预览位于 `build/contract-validation/`。HTML 图不是 PowerPoint 原生证据，
  没有提交 native review、promote 或任何正式 final 声明。

## 实际限制与恢复

- 科学等价、因果强度和观众可理解性仍依赖真实源文案审读和渲染图复核。字符/数字/对象检查不能证明语义。
- 原图、表格数据、机制图与公式的解释是否忠实仍须实际核对；对应 REVIEW 保留。
- 没有用 L.pdf 重新调用 Story/page_design 独立子代理，不能将本次工程测试称为论文 PPTX 已改好。
- 未给整链制作时间作提速承诺；自动归档、copy_ref 和页缓存减少重复转写/渲染，但新审读成本须在真实任务衡量。
- 当前论文任务所在的原工作副本和 MCP 配置未切换。切换后沿用现有源码指纹失效规则；
  旧任务可按原版本恢复/重验证，升级必须实际生成新契约和重新审读，不能伪造既有模型授权或委派。
- 当前分支没有提交、合并、推送或自动发布。
