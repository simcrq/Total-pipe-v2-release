# Agent 接入层：安装、推进与恢复

默认入口为 `total_pipe` 四工具服务，完整科学 / 几何规范仍见 [总调度 Skill](../skills/total-pipe-deck/SKILL.md)。
[修订设计 v2](agent-adapter-design.md)记录了对用户 v1 稿的评审与实施取舍。
接入层不替代 PWF、pwf2rpa、RPA、Deck Compiler；也不自动生成 Story、IR 或视觉提案。

## 安装和 profile

完整仓库需包含相邻的 Total-pipe、PaperWorkflow、research-ppt-assistant，使用 Python 3.12+、Node.js 22+，
生成 PPTX 需 OfficeCLI 1.0.152+。在仓库根目录运行：

```bash
python3.12 install.py --client codex
# Claude 用户：
python3.12 install.py --client claude
# 只安装、验证服务，不注册客户端：
python3.12 install.py --client none
```

安装器在仓库 `.venv` 安装真实依赖，启动服务执行 initialize / tools/list，然后才写客户端配置。
`--python` 指定创建 venv 的解释器，`--venv` 指定环境目录；已有完备环境可用 `--skip-deps`。
`--config` 指定目标配置。`--dry-run` 只展示计划和配置检查，不创建 venv、不安装依赖、不写文件。
安装结果在根目录 `install-report.json`（已 gitignore），包含 doctor、握手与工具数。

Codex 默认配置位置是 `$CODEX_HOME/config.toml`，未设置时为 `~/.codex/config.toml`。
只替换末尾受管块，写前备份；坏 TOML、非托管同名服务或作用域歧义会中止。
Claude 默认 `~/.claude.json`，保留其他键并备份；仅命令、参数、环境写入其 stdio 配置，
绝对 launcher 自行切换正确 cwd。明确 `--force` 可替换 JSON 同名冲突，不能绕过 TOML 语义保护。
运行本仓库的开发测试不会修改真实用户配置；示例中的配置目标可换到临时目录。

默认 [`.mcp.json`](../.mcp.json) 仅声明四工具。调试 / 回切使用：

```bash
python3.12 install.py --client codex --profile advanced
```

[`.mcp.advanced.json`](../.mcp.advanced.json) 声明 PWF、RPA、低层 total_pipe_v3 三服务。
工具数量从当前实现握手读取，不固定为旧稿的 39。profile 切换删除本安装器原来的受管项，保留其他服务。
插件已有 mcpServers 路径仍指向 `.mcp.json`；源码 / 配置变化后须重载服务，插件缓存需另行更新。
孤立的组件缓存可能没有相邻 PWF / RPA；完整论文流程用安装器定位到完整 checkout。

## 四工具与工作循环

| 工具 | 输入与行为 |
| --- | --- |
| totalpipe_doctor | 可选 deep / source_kind；报告 12 类环境检查与阶段能力 |
| totalpipe_start | source、out_dir、language、presentation_type；可选 source_kind、requirements、queries、slide_count、supplementary_paths、supplementary_content_included |
| totalpipe_advance | job_id；可提交 artifact_kind / artifact_path，回填 inputs，或指定 replan_from / acknowledge |
| totalpipe_status | job_id；只读取实际哈希和状态，不执行组件 |

source_kind 可为 auto、pdf、markdown、workflow、deck_ir。JSON 自动按 schema_version 识别；
已有 IR 保持语义，在 work 中保存以绝对资源路径重定位的副本，完整设计可直接 build。
已有 workflow 保留原证据包目录，从 readiness 与模型选择门禁继续。
PDF / Markdown 首先需要实际主题的 queries。queries 是 `[{"id":"q1","query":"具体检索问题"}]`，
可附 intent；接入层将 query 字符串交给 PWF，PWF 自行推导检索 intent 和 custom query ID。
显式配对 supplementary_paths；内容确已合入分析输入后才确认 supplementary_content_included=true。

start 不收模型字段。在 model_selection 暂停点使用用户本轮或此前的明确选择回填：

```json
{"model":"<用户选择的准确模型>","reasoning_effort":"high","selected_by_user":true}
```

reasoning 支持 high / xhigh / max / ultra。Story 的 planner 必须匹配提示包 delegation；
仍需由宿主真实调用独立子代理，字段校验不能证明模型真的被调用。
测试中的 test-model / 固定 Story 只是 fixture，不能冒充生产 provenance。

阶段与路由见 [stages.json](../agent/stages.json)。每次读取 next_action：

- author_artifact / invoke_subagent：按完整提示和 schema 写 expected_output，用 artifact_kind / artifact_path 提交。
- provide_input：沿用或询问用户选择，传 advance.inputs。
- replan：读取反馈，按 target_stage 修订；必要时显式 replan_from 清除该阶段及下游 checkpoint。
- resolve_dependency：按 remedy 处理环境后 advance。未知错误保留脱敏日志路径。
- review_required：处理具体 FAIL 或修订上限；不能用 acknowledgement 消除 FAIL。
- none：若 status=running / reason=ADVANCE_REQUIRED 则 advance；CANDIDATE_READY 才交付候选。

默认候选允许 REVIEW，返回全部 QA 计数和 unacked_count。真实复核后可传
`acknowledge: {reviewer, note, review_ids}`，复用[候选逐项签收](complex-page-qa.md)。
正式 final 仍使用原 `record-powerpoint-review / validate-native / promote` CLI；接入层不暴露或执行它们。

## CLI 与提示包

在 Total-pipe 目录执行：

```bash
python -m agent doctor --json
python -m agent doctor --deep --json
python -m agent start --source /abs/deck_ir.json --out-dir /abs/output \
  --language zh --presentation-type group_meeting
python -m agent status --job-id <job-id>
python -m agent advance --job-id <job-id> --artifact-kind story_plan \
  --artifact-path /abs/output/work/story_plan.json
python -m agent advance --job-id <job-id> --inputs /abs/selection.json
python -m agent serve
```

`python -m agent setup` 返回安装器位置。IR 提示由接入层准备：

```bash
python -m agent ir-prompt --workflow /abs/workflow.json --rpa /abs/rpa_input.json \
  --normalized /abs/normalized_content.json --plan /abs/deck_plan.json --out /abs/ir_prompt.json
```

正常流程在 RPA 成功后自动生成同一个提示包。它包含完整 workflow、原始 content model、完整 plan、
真实 catalog / 能力 / schema 及素材根。没有新增 `deck_compiler ir-prompt` 命令。
RPA 的业务参数写在 plan_input.json；不能把 `--file` 后的命令行参数当成合并成功。
slide_count 与完整 Story briefs 数量冲突时要求改 Story，不截断 / 复制 brief。
IR 另校验完整 body / key_points、证据引用和页数下界，不能将多页内容塞成一页来消除容量问题。

## 恢复与文件边界

- out/.totalpipe/job.json 存请求、指针、用户选择与 checkpoint；out/build/state.json 仍由编译器拥有。
- registry 位于 `TOTALPIPE_AGENT_HOME/jobs/`，默认 `~/.local/state/total-pipe/jobs/`。只存输出目录，重启后可按 job_id 继续。
- job 和 registry 原子写；OS 文件锁冲突返回 JOB_BUSY，进程退出释放锁。
- Agent 产物须是 work 内的真实文件，拒绝越界、`..` 和 symlink；组件证据包留在 evidence，输入包不搬目录。
- 每次重新校验实际文件哈希、资源与上游依赖；缺失、改动、接入层源码 / 阶段表或 Git 版本变化使相应下游失效。
- 依赖重试成功后清除旧失败；上游变化后，status 不再返回已经失效的诊断。
- 相同提交不增加失败次数，仍继续未完成组件；状态查询不计次。被拒绝的不同 Agent 提交才消耗修订预算。
- job 损坏返回 JOB_STATE_INVALID，按记录修复或换新输出目录；不从文件猜回模型授权。
- adapter 超时会终止所启动的进程树；日志写 logs 并屏蔽当前环境的 token/key/password 等值。

doctor 的 can_native_final 仅说明依赖就绪，不能当作 PowerPoint 验收结果。
MinerU token / CLI 就绪不能证明云认证有效；缓存登录无法确认时报告不确定，并允许实际 OCR 返回诊断。
字体、OCR 和 PowerPoint 不在所有机器上可用；能力与实际原生验收分别报告。

## 本次实施验证（2026-10-25）

在 macOS、Python 3.12.12、Node.js 24.20.0、OfficeCLI 1.0.158 上执行：

| 验证 | 结果 |
| --- | --- |
| Total-pipe 主测试套件 | 384 项通过，包含 39 项接入层测试，无 skip |
| pwf2rpa | 83 项通过 |
| RPA | 316 项通过 |
| PaperWorkflow | 38 项通过；1 项因缺少 Li Markdown fixture 跳过 |
| 干净 venv 安装与真实 stdio 握手 | 默认 4 工具；advanced 三服务合计 41 工具；重复配置、profile 回切和 Claude launcher 已验证 |
| 实际候选闭环 | 已有 IR，以及合成 Markdown → PWF → RPA → IR → Design → OfficeCLI，均到零 FAIL 候选 |
| 文档与 Skill | 本地链接无缺失；轻量 Skill 43 行，格式验证通过 |

Markdown 测试的 Story / IR / 视觉提案为明确标注的测试产物，未调用真实 Story 模型。
安装验证仅使用临时客户端配置；deep doctor 实际创建、关闭并校验临时 PPTX。
本次未执行云 PDF OCR、Windows 锁 / 进程树路径或 PowerPoint UI / 原生 PDF / final 晋级。
doctor 检测到 PowerPoint 与字体，MinerU 认证仍报告未验证，不把依赖检测计为原生验收。
