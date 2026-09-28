# Total-pipe v3

本目录复用完整 v2 科研链路，新增 v26 布局模型与 agent MCP 工具。PaperWorkflow、Story、pwf2rpa、RPA 规划职责保持不变；编译器约束最终布局，OfficeCLI 写入 PPTX。

## v3.1-pwf2rpa

Story 节点仍以 `question / answer / evidence / next` 为必需字段；需要保留连续细节时可选填 `key_points`，不限制条数。pwf2rpa 将 `answer` 映射为 `takeaway`，将 `key_points` 原顺序送入 RPA Slide Brief，并把它们计入容量。Brief 的 `body` 保留段落换行，`evidence_texts` 继续保存原始证据。详见 [pwf2rpa README](Total-pipe/pwf2rpa/README.md) 和 [中文使用说明](Total-pipe/docs/USAGE.zh-CN.md)。

RPA 修订后以原始内容模型运行 `validate-deck`；若出现 `KEY_POINTS_LOST`，
恢复详细内容，不用压缩后的 slot 文本替代。OfficeCLI `Text overflow`
提示可能不准确，需查看实际页面。
RPA 现在会阻止正文静默截断，并在原文未完整绑定时报告
`SOURCE_TEXT_NOT_BOUND`；字符容量仍只是前置粗筛，需检查换行风险与实际页面。
PaperWorkflow 首轮应按论文主题设置检索问题，文件名不相似的补充材料用
`supplementary_paths` 明确配对，补充 OCR 文本纳入分析后才声明
`supplementary_content_included=true`；`quality_audit` 的 OCR 就绪不代表
`synthesis_readiness` 已通过。英文 Story 经 pwf2rpa 转换会生成英文结尾标题，
`title_chars` 随实际标题自动计算。

## Agent 入口

- Skill：`Total-pipe/skills/total-pipe-deck/SKILL.md`
- MCP：`Total-pipe/.mcp.json`（本机可执行配置，使用已装好 torch 的 Python）
- 服务：`Total-pipe/deck_compiler/mcp_server.py`
- 工具：`totalpipe_compile`、`totalpipe_build`、`totalpipe_review`，并保留 pwf2rpa 原有 5 个工具。

给 build 传入绝对 `ir`、`out` 路径即可，默认 v26。可选 `layout_provider="deterministic"`；OfficeCLI 不在 PATH 时传 `officecli` 绝对路径。返回 JSON QA 与候选文件路径。review 为可选步骤，不自动晋级 final。

移动到其他机器时，安装 `Total-pipe/requirements-v26.txt` 和 OfficeCLI，并更新 `.mcp.json` 的 Python、服务脚本路径。模型文件随项目提供。

原始 v2 说明见 RELEASE_README.md；案例产物只是 smoke test，不是 v3 的主体。
