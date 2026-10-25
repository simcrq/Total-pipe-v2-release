# 开发与文档维护

先按[环境清单](../Total-pipe/环境清单.md)安装对应组件依赖。以下命令以仓库根目录为工作目录，
选择与本次任务相关的检查；文档整理不要求重新运行完整实现测试。

## 组件测试入口

```bash
PYTHONPATH=Total-pipe python -m unittest discover -s Total-pipe/tests -v
PYTHONPATH=Total-pipe python -m unittest discover -s Total-pipe/pwf2rpa/tests -v
PYTHONPATH=PaperWorkflow python -m unittest discover -s PaperWorkflow/tests -v
```

RPA 在 `research-ppt-assistant/` 中执行 `npm test`，要求 Node.js 22+。
OfficeCLI、字体和可选素材影响对应检查；缺少素材造成的 skip 要单独报告，不能计作通过。
测试数量和历史运行时间属于具体提交的记录，不是接口或固定质量承诺。

仓库根目录的 [Deck Compiler CI](../.github/workflows/deck-compiler.yml) 在 Ubuntu 的 Python
3.12 / 3.13 上安装当前满足依赖声明的 Pillow wheel、确认 Raqm 可用后运行编译器测试。
该作业不安装 OfficeCLI；相关原生后端测试会按自身条件跳过，需另在本地执行。
PowerPoint UI / 原生 PDF 验收仍在 macOS 或 Windows 单独完成。

## 当前验收依据

- 输入和内容绑定：当前 Schema、语义校验与 RPA 内容模型。
- 几何和容量：`layout.json`、`layout_feedback.json` 及当前 QA；完整术语按指定文字策略保留。
- PPTX：实际导出文件的结构检查和原始 OfficeCLI issues。启发式 `Text overflow` 要在实际 PowerPoint 中核对。
- 正式 final：直接 PowerPoint UI 复核、绑定当前文件的原生 PDF、REVIEW 审核与晋级门禁。
  详见[使用说明](../Total-pipe/docs/USAGE.zh-CN.md#6-正式-finalpowerpoint-验收与晋级)。

## 文档维护

1. 先查[当前索引](README.md)，用源码、Schema 和实际 CLI 确认变更。
2. 按[文档同步 Skill](../Total-pipe/skills/total-pipe-doc-sync/SKILL.md)更新相关入口、协议、环境和样例。
3. 失效开发记录移入 `docs/archive/`，保留日期、原路径和历史性质；在归档索引与 `catalog.json` 登记。
4. 修复当前文档的链接和旧路径引用，更新本索引。不要把过时说明继续放在默认 Agent 阅读路径中。
5. 检查公开图片及文字中的个人信息。展示图只保留幻灯片画面，不包含桌面、账户、讲稿和本机路径。
6. 报告实际执行的检查；文档核对、结构检查、PowerPoint 视觉检查和原生 PDF 验收分别记录。
