# Agent 原生 PowerPoint 验收：独立回归记录

日期：2026-11-05（Asia/Shanghai）。工作树分支 `codex/slim-agent-pipeline`，起始 HEAD
`57a63ccedfddb3e91b714646e6bb20baa7299716`。独立测试执行者为 `/root/native_regressions`，
本轮宿主实际调用指定 `gpt-6-luna`、`reasoning_effort=max`。接入层实现由主代理维护；验证发生在
该起始 HEAD 之上的工作树。测试代理未执行 Git 提交；报告后续由主代理依据其执行记录和磁盘证据整理。

## 测试环境与边界

- macOS；Python 3.12.12；OfficeCLI 1.0.158。
- Python 使用已有虚拟环境；命令显式设置 `PYTHONPATH` 指向该工作树的 `Total-pipe` 和 `tests`。
  `TOTALPIPE_AGENT_HOME` 指向 `/private/tmp` 隔离目录；`AgentCase` 的各测试另用独立临时目录。
- 单元/回归阶段通过真实 OfficeCLI 建立可编辑 `native-bullets` 候选；该阶段导出 PDF、PDF 检查和
  UI 审核均为明确 mock / synthetic fixture，AppleScript 只用 `osacompile` 静态编译。
- 回归完成后，另做下文记录的真实 PowerPoint 自动导出/缓存集成；该阶段实际调用 Apple Events，
  没有提交 UI review、REVIEW acknowledgement 或 final。全程没有使用 LibreOffice。

## 覆盖范围

新增 `Total-pipe/tests/test_agent_native.py`，并扩充 `Total-pipe/tests/test_native_renderer.py`，覆盖：

- MCP 仍为四工具；advance 暴露完整 native schema；native 与普通 advance mutation 互斥；非候选阶段拒绝。
- 自动 render 只更新 native QA，不写 UI review、candidate REVIEW acknowledgement 或 final；四个必需检查与
  每页实际 ID 均为显式输入，`all` 和不完整页集被拒绝。
- 手动 ingest 要求 `source=powerpoint-export`、实际 PDF SHA-256、已有 UI review 和同一 reviewer；
  测试用 reviewer 记录明确标为 synthetic，不能视为真实验收。
- 有效导出重复复用；删除预览后只重新栅格化 PDF；删除或改动 PDF 后原生导出恢复；候选、IR、layout
  字节和 mtime 及 job 输入选择不变，build checkpoint 只刷新已有输出哈希。
- Native QA FAIL 不能被签收；仅当全部 FAIL 都来自 `native-visual` 时，允许 `force:true` 重跑 render
  或合规 ingest，并以新 PDF 重做检查；任何结构、编译或其他来源 FAIL 仍阻断。
- 导出依赖失败后可重试；错误 PDF 不附加原生证据；预览栅格异常保留已验证 PDF，并允许只重试预览。
- staging、layout 或原生检查期间的 TOCTOU 变化不能提交 proof 或 QA；改变请求哈希不能调用渲染器。
- Windows renderer 的输入哈希绑定、失败不制造证据，以及 macOS AppleScript 静态编译。

首轮发现两处恢复缺口并反馈主代理：原生来源 FAIL 会被通用 FAIL 门禁永久挡住重验；PDF parser 的
`PdfminerException` 会逃出 native 调用且不生成结构化失败结果。主代理收窄了 native-only FAIL 的重验条件，
并在 renderer / preview 外部异常边界记录失败或 `preview_error`；最终目标集包含这两处修复后的回归。

## 验证结果

| 范围 | 结果 | 说明 |
| --- | --- | --- |
| Agent / repair / native / publication / QA / renderer 受影响集 | **157 tests，0 failures，0 errors，0 skips** | 修复后；139.785 秒 |
| 新增 native parser/rasterizer 异常回归 | **2 tests，全部通过** | 作为受影响集的一部分；坏 PDF 不造 proof，预览失败可恢复 |
| 完整 Total-pipe 主套件 | **592 tests，18 failures，5 errors，0 skips** | 在最后一项 PDF parser 异常捕获修复之前运行；210.092 秒 |
| 完整套件失败集合对照 | **新增/消失均为 0** | 与基线 `/private/tmp/totalpipe-repair-full-final.log` 的 579 tests、18 failures、5 errors 方法集合完全相同 |
| `git diff --check` / Python 编译 / 本地 Markdown 链接 | 通过 | 独立验证阶段链接无失效；轻量 Skill 为 57 行（上限 60） |

最终受影响集命令：

```bash
TOTALPIPE_AGENT_HOME=/private/tmp/totalpipe-native-agent-focused-fixed-home \
PYTHONPATH=<checkout>/Total-pipe:<checkout>/Total-pipe/tests \
<existing-python-3.12-venv>/bin/python -m unittest \
  test_agent_adapters test_agent_doctor test_agent_entry test_agent_install \
  test_agent_slimming test_agent_state test_agent_repair test_agent_native \
  test_deck_compiler test_qa_review test_native_renderer -v
```

实际日志：`/private/tmp/totalpipe-native-agent-focused-fixed.log`、
`/private/tmp/totalpipe-native-parser-fixed.log`、
`/private/tmp/totalpipe-native-agent-full.log`。完整套件是在 parser/rasterizer 异常捕获改动前运行，
修复后的完整影响路径由上述 157 项目标集覆盖；因此本记录不声称修复后又跑过 592 项，也不宣称全仓全绿。
失败方法集合与基线相同，包括已有的数学度量/布局、原生图形/列表、复杂混排及 supplement 检查问题。

RPA 的 316 tests 和 pwf2rpa 的 96 tests 沿用此前通过记录；本轮未更改这两个组件，故未重跑。
此前结果见[局部 IR 修补独立验证记录](agent-repair-validation.md)。

## 与 mock 测试分开的真实 PowerPoint 证据

以下由 `/root/native_and_benchmark_tests`（本轮实际指定 `gpt-6-luna/max`）在获授权 GUI 中执行，
与上述 mock 导出回归分开：

- 用户提供的 22 页候选通过 PowerPoint 菜单导出 PDF：
  [candidate-native-ui.pdf](../build/benchmark-20261105/native-probe/candidate-native-ui.pdf)，22 页、
  1,506,290 字节，SHA-256 `c6221b18037bcb9205de5d53e54edeaaf4bb027815730279b5ab0df1c4cb2d54`；源 PPTX
  SHA-256 `e869b208ed06c96c580e61a05fa507437f673865717d034652edbb0452b8a562` 未变。该 subagent 只看了
  1 页，没有对这份 22 页候选提交逐页 UI review 或签收。
- 当前代码的 `native-bullets` 两页 fixture 经 Agent native API 由 PowerPoint 实际导出：
  [native.pdf](../build/benchmark-20261105/native-api-current/job/build/native.pdf)；候选未变，QA 为
  0 FAIL / 0 WARNING、8 REVIEW 未签收。随后该 subagent 在 PowerPoint 中检查两个 slide ID 并提交四项
  UI 检查；job 状态为 `awaiting_review_acknowledgements`，8 个 REVIEW 仍待处理。记录见
  [powerpoint_review.json](../build/benchmark-20261105/native-api-current/job/build/powerpoint_review.json)。
  **未解决视觉项：第二页根号前可见小点方框。** UI review 只记录检查已发生，未把该视觉问题或八条
  REVIEW 签收为通过，也没有将简单样例当作论文的科学验收。

这两项真实 GUI 证据证明软件路径可执行；简单 fixture 的两页 UI review 不等于用户 22 页论文候选已逐页
验收。正式 final 未由 Agent 自动晋级，仍保留现有 CLI promotion 门禁。

## 真实自动导出与缓存实测

由 `/root/native_regressions` 在当前工作树创建新的真实 OfficeCLI 候选，job
`a625dff0775b466bbf2a12e044d4e97d`，输出 `build/native-cache-final/job/`。
本机受限 shell 无法连接 LaunchServices，实际原生调用使用用户已授权的 GUI 自动化执行环境；
PowerPoint 只打开/关闭 UUID 私有副本，没有对用户原文稿执行保存或关闭。

| 调用 | 执行者记录的调用墙钟 | events.jsonl 内部 native span | 实际结果 |
| --- | ---: | ---: | --- |
| 首次 render | 21.429 s | 21.057433 s | 新 PowerPoint PDF 与两页预览，reused=false |
| 重复 render | 0.363 s | 0.104822 s | reused=true，无新原生导出 |
| 删除一个 PNG 后 render | 0.417 s | 0.166755 s | reused=true，仅重新生成两页预览 |

三次原生调用区间为 2026-11-05 03:21:02–03:21:24 UTC（北京时间 11:21）。`native-renders`
始终只有一个目录。候选和 staging 的 SHA-256 均保持
`3f4f1a1eeba09623bf4e445c5cb462e24d192acd34f0edb616a2798294bb8eee`；PDF 为两页、67,712 字节，
SHA-256 保持 `c2854e39a71d4df74dfdae533b4d538ca06c0af8d45353e6eece64b7ab83ae94`。
最终 QA 为 0 FAIL / 0 WARNING / 8 REVIEW（全部未签收），`native=true`、`visual_review=false`，
状态 `awaiting_powerpoint_review`，没有生成 review / acknowledgement / final。

证据：[追加事件日志](../build/native-cache-final/job/logs/events.jsonl)、
[native.json](../build/native-cache-final/job/build/native.json)、
[预览清单](../build/native-cache-final/job/build/native_preview.json)、
[QA](../build/native-cache-final/job/build/qa_report.json)。这是同一未改候选的原生导出/预览恢复实测，
不是论文 OCR→Story→设计→PPTX 的整链加速比；首次启动、缓存热度和样例仅两页也限制其推广。

## 变更文件与协议入口

- `Total-pipe/tests/test_agent_native.py`
- `Total-pipe/tests/test_native_renderer.py`
- 本报告

协议说明：[Agent 原生 PowerPoint 验收接入](../Total-pipe/docs/agent-adapter.md#原生-powerpoint-验收接入)、
[native acceptance schema](../Total-pipe/agent/schemas/native-acceptance.schema.json)。提交信息以 Git 历史为准。
