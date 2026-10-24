# Total-pipe：Deck IR 编译与 Agent 接口

本目录包含 Deck Compiler、确定性布局提供方、pwf2rpa、Schema、示例和总调度 Skill。
完整论文流程还使用同级的 `PaperWorkflow/` 和 `research-ppt-assistant/`。

**组件、当前版本和全流程入口见 [仓库 README](../README.md)。**
插件清单版本为 `3.3.0+codex.20261021203000`；MCP 握手版本为 `3.2.0`，
编译器 Python 模块仍声明 `2.0.0`。输入 Deck IR 为 `schema_version: "2.0"`，
可选 layout tree 支持 `1.0 / 1.1 / 1.2`。这些版本属于不同对象。

## 入口与职责

| 入口 | 用途 |
| --- | --- |
| [total-pipe-deck Skill](skills/total-pipe-deck/SKILL.md) | 由 Agent 调度 PWF → Story → pwf2rpa → RPA → Deck IR → Design → 编译 / 验收 |
| `python -m deck_compiler …` | 从已有 canonical Deck IR 开始，执行设计提案校验、布局编译、PPTX 构建及验收门禁 |
| `python totalpipe.py …` | 编译阶段的简化 CLI：generate、validate、preview、quality、template-merge、verify |
| `python -m deck_compiler.mcp_server` | Total-pipe stdio MCP，配置为 [.mcp.json](.mcp.json)，服务名 `total_pipe_v3` |
| `python -m pwf2rpa …` | 在 `pwf2rpa/` 中运行，转换已有 workflow / Story；详见 [适配器说明](pwf2rpa/README.md) |

编译器负责最终区域、文字与公式尺寸、几何约束和结构化反馈；OfficeCLI 是唯一的 PPTX 写入后端。
`packer` 是默认布局建议提供方，也可选 `compiler` 或外部 `module:factory`。
旧 v26 扩散模型已移除，当前运行无需 torch。

## 环境

完整流水线使用 Python 3.12+、Node.js 22+；编译依赖见 [requirements.txt](requirements.txt)。
生成 PPTX 需 OfficeCLI 1.0.152+，正式原生验收需 macOS / Windows 的 Microsoft PowerPoint。
PDF OCR、字体、可选数学度量和安装命令见 [环境清单](环境清单.md)。

## 从 Deck IR 编译

在本目录执行；尖括号参数替换为实际路径：

```bash
python -m deck_compiler capabilities

python -m deck_compiler visual-prompt --ir <deck_ir.json> --out <visual_prompt.json>
# Agent 阅读完整提示包，生成绑定当前 IR 哈希的 visual_proposal.json
python -m deck_compiler apply-visual-plan --ir <deck_ir.json> \
  --proposal <visual_proposal.json> --out <designed.deck_ir.json>

python -m deck_compiler compile --ir <designed.deck_ir.json> --out <build-dir>
python -m deck_compiler build --ir <designed.deck_ir.json> --out <build-dir> \
  --officecli <officecli-path> --skip-native
```

已完成整套设计的 IR 可直接 compile / build。Design 默认必做；漏做时返回
`VISUAL_DESIGN_REQUIRED` 和完整提示包。提案只改变 presentation；相对资源路径要求新 IR
与源 IR 同目录。简化构建命令为：

```bash
python totalpipe.py generate <designed.deck_ir.json> --out <build-dir>
```

该命令接收已有 Deck IR，默认生成候选。上述开发构建的 `--skip-native` 须在正式晋级前补验收。

### 快速运行已带设计的样例

```bash
python -m deck_compiler build --ir examples/inline-math.deck_ir.json \
  --out build/inline-math --officecli officecli --skip-native
```

此样例有三页，覆盖行内文字 / 根号 / 指数、行内矩阵与独立公式、原生表格。
样例字体名会按当前系统解析，字体替代和数学近似测量会进入 REVIEW。

## 构建产物与验收

| 文件 | 含义 |
| --- | --- |
| `deck_ir.json` | 本次构建冻结的科学内容输入 |
| `layout.json`、`layout_provider.json` | 最终几何、文本契约、提供方与回退记录 |
| `derived/` | 从输入派生的规划、资源清单与 QA expectation |
| `layout_feedback.json` | 绑定 IR 哈希的组件尺寸错误及上游修订建议 |
| `candidate.pptx`、`staging.pptx` | 可编辑候选与字节一致的验收副本 |
| `qa_report.json`、`officecli_issues.json` | 统一 QA 和保留的 OfficeCLI 原始问题 |
| `powerpoint_review.json`、`native.pdf`、`native.json` | 当前 staging 的直接 UI 检查与 PowerPoint 原生证据 |
| `final.pptx`、`state.json` | 完成验收 / REVIEW 审核 / promote 后的交付及状态 |

修改页面从 canonical Deck IR 开始；派生文件由编译器重建。
候选可以交付并注明未解决项；正式 final 按 [使用说明第 6 节](docs/USAGE.zh-CN.md#6-正式-finalpowerpoint-验收与晋级)
完成逐页 PowerPoint 检查、PDF 绑定及 REVIEW acknowledgement，再 promote。
OfficeCLI `Text overflow` 是排查线索，真实效果需看实际页面。

## 当前能力与协议

- [独立公式与矩阵](docs/deck-compiler-v2.md#formulas-component-formula)：原生 OMML、分式、根号、上下标、密集单双栏推导。
- [显式行内公式](docs/inline-math.md)：正文、标题 / takeaway 和表格文字格；按逐行片段宽度及基线上下需求计算容量。
- [原生列表](docs/native-lists.md)：takeaway 独立标记，整套 / block 样式与符号颜色；preserve-terms 保留列表呈现和全文。
- [复合区域](docs/composite-layouts.md)：RPA 子布局检索 / 组合 / 自动选型，Deck IR 递归分配 columns、stack、panel、image_grid。
- [边框容器](docs/framed-containers.md)：panel 原生描边、填充与标题色带；独立 takeaway 框选；内边距、描边与完整内容共同测量。
- [原生科研表格](docs/native-tables.md)：layout tree 1.1、多级合并表头、跨行跨列与公式格。
- [流程与 DAG](docs/native-graphics.md)、[机制 / 架构 / 路径](docs/native-components.md)：原生对象、连接符和贝塞尔曲线。
- [整套视觉设计](docs/scientific-visual-planner.md)：保留完整科研术语，文字超容量按 preserve-terms 生成候选及 REVIEW。

旧平面 IR、layout tree 1.0 和未启用行内公式的文字仍兼容。
文字容量例外允许保留全文；公式真实宽高、图形可读性和原图尺寸门禁继续执行。

完整操作见 [USAGE.zh-CN.md](docs/USAGE.zh-CN.md)；开发与验收记录见
[composite-layout-development.md](docs/composite-layout-development.md)。
