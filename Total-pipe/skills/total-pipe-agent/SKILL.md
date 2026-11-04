---
name: total-pipe-agent
description: 从论文 PDF、Markdown、已有证据包或 Deck IR 生成可编辑科研 PPTX；通过四工具接入层推进证据、Story、页面设计、IR、Design 和候选 QA。
---

# Total-pipe Agent

默认服务是 `total_pipe`，仅有 doctor / start / advance / status 四个工具。
先用 totalpipe_doctor 判断当前输入所需能力；source_kind=pdf 时查看 OCR 认证与依赖。
使用已安装仓库，安装 / 回切说明见 [接入层用法](../../docs/agent-adapter.md)。

将用户提供的 source、out_dir、language、presentation_type 传给 totalpipe_start。
source_kind 支持 auto/pdf/markdown/workflow/deck_ir；从已有产物继续，保留用户已有要求。
queries 可先写入或在暂停点提交；必须围绕实际论文。补充材料按真实路径显式配对。
只有补充材料内容已进入分析输入时，才传 supplementary_content_included=true。

每次读取返回的 stage、status 和 next_action；阶段顺序由 agent/stages.json 定义。
status=running 时调用 totalpipe_advance；status=candidate_ready 时交付 candidate 路径及 QA。
其余按 next_action.type 操作：

| type | 动作 |
| --- | --- |
| author_artifact | 读 schema_path / input_path / instructions_path；在 expected_output 写完整 JSON，再提交 artifact_kind、artifact_path |
| invoke_subagent | 用用户明确选择的模型和 reasoning 启动真实独立子代理；完整读取 input_path，提交其真实产物 |
| provide_input | 沿用用户本轮或此前明确的选择；缺失才询问，用 advance.inputs 回填 |
| replan | 读 feedback_path，保留完整内容改结构；按 target_stage 提交或用 replan_from 回退 |
| resolve_dependency | 按 remedy 处理依赖后 advance；不猜密钥或伪造认证 |
| review_required | 读 qa_report / feedback_path；FAIL 需修复，不能签收；修订耗尽时向用户说明 |
| none | 若 reason=ADVANCE_REQUIRED 则 advance；若 CANDIDATE_READY 则交付候选 |

queries 是对象数组，含唯一 id、query，可选 intent。适配器把 query 文本传入 PWF，PWF 自行确定检索 intent。
Story 提示的 delegation 绑定用户选择；模型字段仍是声明，必须真实执行子代理，不伪造 provenance。
Story 缺模型选择时先询问；不得静默选择，也不得由主 Agent 代写。
RPA 之后会先要求 `page_design`：一页一个论点、一个锚点、一段 `shape`（读者看到什么），Story 的每条
内容恰好出现一次，数字只能来自所引 evidence；设计通过后 IR 必须逐页实现，不得重新设计。
`page_design` 与 Story 一样交给**独立子代理**执行，不主 Agent 代写：读 `work/page_design_task.md` 作为任务书，
把 `work/page_design_prompt.json` 与输出路径交给子代理，收回它写出的 `work/page_design.json` 再 advance。
设计提示是**设计问题**，不含 forms / devices / type_scale：设计者不需要知道编译器能画什么，
只写 claim、anchor、`shape`、`marks` 和场合 `setting`（组会 / 会议 / 文献分享 / 讲课 / 路演）；
形式由 IR 阶段从 `design_forms` 里翻译。
校验只关心内容不变式：Story 每条内容恰好一次、数字来自所引 evidence、`marks` 出现在本页文本里、
`setting.occasion` 在五个键内、页数不超过 brief 数两倍。
IR / Design 提示包是完整输入；原文 body、key_points、公式、单位和不确定性保留在页面或讲稿。
空间不足回退重规划，不删图、缩写术语或降低字号门槛；保留 source_figure 和原图比例。
同一阶段仅对被拒绝的新提交计次；读取 status 和依赖失败不计次。达到预算后请求人工处理。
status 只读；同一提交可重复 advance，已完成组件不会重复执行，未完成下游继续运行。
job_id 在重启后可用；job.json 损坏时不能从产物伪造用户选择，按 remedy 处理。
候选 REVIEW 如实报告；仅真实复核后用 advance.acknowledge 传 reviewer、note、review_ids。
候选笔记不能替代 final 审核；promote / validate-native / record-powerpoint-review 仅用原 CLI。

需要完整 Story 规范时读 [总调度 Skill 的 Story 节](../total-pipe-deck/SKILL.md#2-科学故事story-planner)。
复杂页、公式及原生对象的额外限制按提示包和 [当前文档索引](../../../docs/README.md) 按需读取。
