# OfficeCLI 后端接口与 agent 调用

Deck Compiler v2 可从同一份 canonical `deck_ir.json` 选择 `artifact-tool` 或
`officecli` 生成 PPTX。OfficeCLI 是**渲染后端**：它读取编译器生成的 `layout.json`，
不改写科学内容、证据引用或最终 bbox。`staging.pptx` 仍是统一验收对象。

## 1. 准备环境

确认 OfficeCLI 可执行文件可运行 `officecli --version`。Windows 可把 `officecli.exe`
放入 `PATH`，或在调用时传入绝对路径 `--officecli C:\path\to\officecli.exe`。
本项目随附的 OfficeCLI 源码目录本身不是可执行文件；若只克隆了源码，需要先按
OfficeCLI 项目说明构建或安装。本适配按工作区 OfficeCLI 源码的 `1.0.152`
接口实现；如可执行文件版本不同，先检查 `officecli --version` 和本项目的 batch
warning/QA 结果。Python 依赖见
`deck_compiler/requirements.txt`。Deck IR 的 `theme.font_file` 与
`theme.bold_font_file` 必须指向**当前机器实际存在**的字体文件；发布包中的
`examples/research.deck_ir.json` 使用 macOS Arial 路径，在 Windows 上需先复制并
替换为本机字体路径。

## 2. agent 的调用顺序

在 `Total-pipe` 目录执行（PowerShell 示例）：

```powershell
python -m deck_compiler compile --ir C:\path\deck_ir.json --out C:\path\build
python -m deck_compiler build --ir C:\path\deck_ir.json --out C:\path\build `
  --backend officecli --officecli C:\path\officecli.exe --skip-native
```

第二条中的 `--skip-native` 只适用于开发期检查。正式交付时删除它，并按
[主流程说明](USAGE.zh-CN.md)完成 PowerPoint 逐页眼检、`record-powerpoint-review`、
导出 `native.pdf`、`validate-native`、处理 REVIEW acknowledgement 和 `promote`。
在没有 PowerPoint 的机器上可以完成 OfficeCLI 生成与结构 QA，但当前正式晋级门禁
仍要求 PowerPoint 原生证据。不要把 OfficeCLI 的 HTML、截图或 PDF 当成
`native.pdf` 提交。

检查 `qa_report.json` 的 `counts.FAIL` 必须是 `0`，`checks.backend` 应为
`officecli`；检查 `state.json.phase`。交付只能取通过晋级的 `final.pptx`。
若前一步失败，停止后续命令，读取 `qa_report.json` 的规则 ID 和消息修复输入或
后端适配；不要手改 `layout.json` 再继续。

## 3. 版本化边界

输入协议是 Deck Compiler v2 的 `layout.json`（长度均为 96 dpi CSS px），
OfficeCLI 后端只处理已编译的三类元素：

| layout kind | OfficeCLI batch 操作 | 保留的契约 |
|---|---|---|
| `text` | `add /slide[N] --type shape` | 名称、文本、显式字体/字号/颜色/位置；finalizer 补齐精确行距、无自动缩放和四边 inset |
| `shape` | `add /slide[N] --type shape` | 名称、预设几何、填充、描边和位置 |
| `image` | `add /slide[N] --type picture` | 原始素材路径、名称、alt、按编译结果保持比例的位置 |

后端先 `create candidate.pptx`，再写入 `candidate.officecli.batch.json`，通过
`officecli batch ... --input ... --stop-on-error --json` 原子执行。每页先添加
`layout=blank` 的 slide，再按 layout 顺序添加元素，最后添加 speaker notes。
执行后调用 `close` 刷新文件，再调用 `validate --json` 检查 OpenXML schema。
OOXML finalizer 完成后，对 `staging.pptx` 再调用 `validate --json` 和
`view issues --json`；原始 issue 结果写入
`officecli_issues.json`，逐条并入统一 `qa_report.json`（Error→FAIL、Warning→WARNING、
Info→INFO）。
`batch` 外层 `success`、每项 `success`、`summary.succeeded/total` 和逐项 warning
都必须通过；OfficeCLI 的退出码 `2` 也视为失败，防止属性被静默丢弃。

单位换算：位置和大小发送为 `px`；OfficeCLI 对 `px` 使用 9525 EMU/px。
字体大小发送为 `pt = CSS px × 0.75`。新行在 batch JSON 中是实际换行字符，
OfficeCLI 将其映射为新的 DrawingML 段落。科学图在 layout 阶段已经按原比例
计算 bbox，OfficeCLI 按该 bbox 放置图片。

`candidate.officecli.batch.json` 是可复查的后端命令记录，不是第二份页面真源；
不要编辑并重放它替代 `deck_ir.json`。每次重新 `build` 会清理旧 candidate、staging、
原生证据和 review 记录，避免旧证据混入新构建。

## 4. 能力和边界

- OfficeCLI 后端支持当前 catalog 产生的文本、矩形及图片元素、背景、画布和讲者备注。
- 同一份 OOXML finalizer 和 `verify()` 对两个后端运行；图片字节、文本、坐标、
  字体、背景和碰撞均以实际导出的 PPTX 为准。
- 后端选择记录在 `qa_report.json.checks.backend` 和 `metrics.json.backend`。
- OfficeCLI 的 `view issues` 自动进入统一 QA；`view html`、`view screenshot` 可用于
  调试。正式原生验收仍使用 PowerPoint 的 UI 检查与 PDF。
- 当前 release 不把 OfficeCLI 导出 PDF 作为 PowerPoint golden render；
  如需要改变验收标准，应先升级 QA schema 和 evidence provenance 协议。

遇到 OfficeCLI 属性兼容问题，先在对应版本运行 `officecli help pptx shape --json`、
`officecli help pptx picture --json` 和 `officecli help pptx slide --json`，然后查看
`candidate.officecli.batch.json` 中对应命令。修改应落在
`deck_compiler/officecli.py` 的稳定 backend 映射，而非新增逐论文 adapter。
