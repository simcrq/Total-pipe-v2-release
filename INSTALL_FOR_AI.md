# Total-pipe 一键安装

在包含 `Total-pipe/`、`PaperWorkflow/` 和 `research-ppt-assistant/` 的仓库根目录运行。完整流程需要 Python 3.12+、Node.js 22+ 和 OfficeCLI 1.0.152+。安装脚本会在 `.venv` 安装 Python 依赖。处理 PDF 时还需要按环境清单配置 MinerU。[环境清单](Total-pipe/环境清单.md)

## 给 AI 助手的指令

> 读取当前仓库的 `INSTALL_FOR_AI.md`，把 Total-pipe 安装到我正在使用的宿主，使用默认四工具模式。运行命令并按返回的 JSON 报告结果。

1. 知道当前宿主时，运行 `python3 install.py --client <id>`，将 `<id>` 替换为下表对应值。宿主不明确时，运行 `python3 install.py --client auto`。如果返回 `CLIENT_SELECTION_REQUIRED`，根据 `candidates` 确认目标宿主，再用其 ID 重跑。
2. 用 `--dry-run` 查看配置路径和技能变更计划，用 `--list-clients` 查看支持和检测结果。需要测试隔离时，文件型宿主可用 `--config` 和 `--skills-root` 指定临时位置。
3. 根据 stdout 的 JSON 报告安装结果。`PASS` 表示环境、握手和安装均通过，`PARTIAL` 表示保留了有差异的现有技能，详见 `skills.skipped`。`BLOCKED` 或 `FAIL` 时先处理报告的条件或错误。成功后的报告默认写入 `install-report.json`，可用 `--report` 指定路径。
4. 重载宿主的 MCP 配置或打开一个新会话。确认 `totalpipe_doctor`、`totalpipe_start`、`totalpipe_advance`、`totalpipe_status` 可用，调用 `totalpipe_doctor`。有些宿主会显示完整工具名，例如 `mcp__total_pipe__totalpipe_doctor`。如宿主显示信任提示，按宿主流程确认。

开始制作后按 `next_action` 推进。流程要求独立子代理时，按用户指定的模型和推理力度调用。宿主缺少对应能力时报告阻塞。[四工具与工作循环](Total-pipe/docs/agent-adapter.md#四工具与工作循环)

只使用题目入口可在 Python 3.12+ 环境安装 `Total-pipe/requirements.txt` 后直接使用 CLI，或在宿主配置同一 Python 环境下的 `python -m agent.mcp_server`。工作目录为仓库的 `Total-pipe/`。[题目入口](Total-pipe/docs/agent-adapter.md#从题目开始)

## 宿主 ID 与默认配置

| 宿主 | ID | 配置位置 |
| --- | --- | --- |
| Codex | `codex` | `~/.codex/config.toml`，支持 `CODEX_HOME` |
| Claude Code | `claude` | `~/.claude.json`，支持 `CLAUDE_CONFIG_DIR` |
| WorkBuddy | `workbuddy` | `~/.workbuddy/mcp.json` |
| OpenCode | `opencode` | `~/.config/opencode/opencode.json(c)`，支持 `XDG_CONFIG_HOME`、`OPENCODE_CONFIG_DIR`、`OPENCODE_CONFIG` |
| Gemini CLI | `gemini` | `~/.gemini/settings.json`，支持 `GEMINI_CLI_HOME` |
| DeepSeek Harness | `deepseek` | 通过 `dsh` 注册到指定 profile，默认 `web` |

现有配置写入前会备份。OpenCode 的 JSONC 配置更新后以 JSON 格式写回，原注释在备份中。已有 MCP 配置决定 OpenCode 格式，新配置按 CLI 主版本选择，可用 `--opencode-version 1` 或 `2` 指定。[OpenCode 配置](https://opencode.ai/docs/config/) · [OpenCode MCP](https://opencode.ai/docs/mcp-servers/) · [Gemini CLI MCP](https://geminicli.com/docs/tools/mcp-server/)

Codex 本脚本注册用户级 stdio 配置。使用已启用的 Total-pipe marketplace 插件时，沿用该插件的服务入口即可。

DeepSeek CLI 需在 PATH 中。用 `--dsh-profile` 指定当前 profile，或用 `--dsh-source` 指向已构建的 DeepSeek Harness 源码目录，安装器会使用该目录中的 `pnpm dsh`。[DeepSeek 插件发布与安装](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md)

```sh
python3 install.py --client codex
python3 install.py --client deepseek --dsh-profile web
```

其他支持 stdio MCP 的宿主可运行 `python3 install.py --client none`，直接使用报告 `stdio` 字段里的 `command`、`args` 和 `env`。调试低层服务时可显式指定 `--profile advanced`。[服务配置与恢复](Total-pipe/docs/agent-adapter.md)
