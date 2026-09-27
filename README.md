# Total-pipe v3

本目录复用完整 v2 科研链路，新增 v26 布局模型与 agent MCP 工具。PaperWorkflow、Story、pwf2rpa、RPA 规划职责保持不变；编译器约束最终布局，OfficeCLI 写入 PPTX。

## Agent 入口

- Skill：`Total-pipe/skills/total-pipe-deck/SKILL.md`
- MCP：`Total-pipe/.mcp.json`（本机可执行配置，使用已装好 torch 的 Python）
- 服务：`Total-pipe/deck_compiler/mcp_server.py`
- 工具：`totalpipe_compile`、`totalpipe_build`、`totalpipe_review`，并保留 pwf2rpa 原有 5 个工具。

给 build 传入绝对 `ir`、`out` 路径即可，默认 v26。可选 `layout_provider="deterministic"`；OfficeCLI 不在 PATH 时传 `officecli` 绝对路径。返回 JSON QA 与候选文件路径。review 为可选步骤，不自动晋级 final。

移动到其他机器时，安装 `Total-pipe/requirements-v26.txt` 和 OfficeCLI，并更新 `.mcp.json` 的 Python、服务脚本路径。模型文件随项目提供。

原始 v2 说明见 RELEASE_README.md；案例产物只是 smoke test，不是 v3 的主体。
