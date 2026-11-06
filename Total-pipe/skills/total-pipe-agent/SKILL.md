---
name: total-pipe-agent
description: 从论文 PDF、Markdown、已有证据包或 Deck IR 生成可编辑科研 PPTX；通过四工具接入层推进证据、Story、页面设计、IR、Design 和候选 QA。
---

# Total-pipe Agent

默认服务是 `total_pipe`，仅有 doctor / start / advance / status 四个工具。先用 totalpipe_doctor 判断当前输入所需能力；source_kind=pdf 时查看 OCR 认证与依赖。
使用已安装仓库，安装 / 回切说明见 [接入层用法](../../docs/agent-adapter.md)。

将用户提供的 source、out_dir、language、presentation_type 传给 totalpipe_start。
slide_count 是最终论文页目标（1–40），不等于 Story 节点或 brief 数；独立补充文字页额外计。
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
新 Story 使用 content_contract 2.0：units 是独立可限定的科学断言/条件，含精确EV与 epistemic；narrative_map 只组织论证，不把整段 answer 当投屏原子。
Story 后按 next_action 进入 scientific_review：主 Agent 读完整任务、提示、Schema、原文和实际SI，实际审查单位粒度、来源及遗漏的初始化/对照/负面结果；禁止自动 pass，失败回退 Story。
RPA 之后的 page_design 必须由用户指定模型的真实独立子代理完成；完整读 work/page_design_task.md、page_design_prompt.json、schema_path。
页面设计1.3中 content_refs 将科学单元恰好分配一次；reuse_refs 明确再次展示的主张，只有直接限定这些可见主张的条件随页出现，不能整包继承叙事段落。
display_copy 是实际投屏文案，content_map 指定可见载体或允许入讲稿的细节；重要条件、对照、负面结果和不确定性不能隐藏。
选图须实际查看；figures列精确资产ID，figure_sources记录真实图号。来源标签与观众图注分开绑定，图号不是实验数值，不能删图号换PASS。
设计者不读取编译器形式清单，自主决定图形、关系、构图和讲解顺序；IR实现批准设计，不能替换为文字摘要。
设计后主 Agent 按 page_review 完整提示实际逐页审读科学忠实性、限定范围和观众语言，提交当前哈希及具体说明；不复用设计者自评，不代表看过渲染或完成原生验收。
旧Story/页面设计1.0、1.1和段落契约1.0/页面设计1.2按原版本恢复；新提示不能降级绕过审读。版本与完整协议见[内容契约](../../docs/content-projection.md)。
IR只实现批准文案/视觉；{copy_ref:id}可引用文本，科学记录、来源、审读哈希和完整讲稿由程序绑定，notes/元数据不能充当可见证据。
原生图示/表格/数据图图注使用component=caption和caption_for视觉引用，按既有图注字号测量；正文不能伪装图注缩小。论文图的可见来源标签自动绑定。
提交 IR 前可用 advance 的 preflight=true（deck_ir + artifact_path）检查全部语义/设计问题并测量几何；读取全部 issues，预检不改 job、不占修订次数，正式验收仍必做。
deck_ir 或之后可单独调用 advance.preview={artifact_path,slide_ids}，渲染 work/ 中的草稿页；完整协议见回复 ir_preview.schema_path。
实际打开 preview_result.pages 的 PNG，再修改源 IR 并重新 preview；未变页复用渲染缓存。预览不接受 IR、不计修订、不改候选或正式 QA。
officecli-html 预览可能与 PowerPoint 的字体/公式不同，不能代替篇级 Design、完整构建或原生验收；FAIL 原样保留，不能凭生成图片签收。
有 next_action.page_authoring 时逐页读完整 input_path 和 Schema，交一页 canonical IR（deck_ir_page）；程序绑定省略的引用/讲稿及已知素材、测量并缓存通过页，只修失败页，齐全后整套复验。
空间不足回退重规划，不删图、缩写术语或降低字号门槛；保留 source_figure 和原图比例。
同一阶段仅对被拒绝的新提交计次；读取 status 和依赖失败不计次。达到预算后请求人工处理。
status 只读；同一提交可重复 advance，已完成组件不会重复执行，未完成下游继续运行。
局部布局/裁图修复可按 repair 指定的完整 Schema 提交 deck_ir_patch，先预检；科学文字/数据/分组变更仍重规划。
默认回复为摘要；完整请求/哈希清单用 status(detail="full")；各轮执行/等待时间见 logs/events.jsonl。job_id 在重启后可用；job.json 损坏时不能从产物伪造用户选择，按 remedy 处理。
候选 REVIEW 如实报告；仅真实复核后用 advance.acknowledge 传 reviewer、note、review_ids。
原生验收按 native.schema_path 完整协议，用 advance.native 单独提交 render / review / ingest；复用候选，不重跑上游。
自动 PDF/PNG 导出不等于直接 PowerPoint 眼检；review 只在实际逐页检查后提交当前哈希、全部页 ID、检查项和说明。候选笔记不能替代 final 审核；promote 仍仅用原 CLI，原生接入与预览说明见接入层用法。

需要完整 Story 规范时读 [总调度 Skill 的 Story 节](../total-pipe-deck/SKILL.md#2-科学故事story-planner)。
复杂页、公式及原生对象的额外限制按提示包和 [当前文档索引](../../../docs/README.md) 按需读取。
