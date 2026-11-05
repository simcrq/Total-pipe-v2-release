# Total-pipe 快速开始

当前组件、版本、环境和完整入口以 [README.md](README.md) 为准。
完整操作见 [中文使用说明](Total-pipe/docs/USAGE.zh-CN.md)，安装见 [环境清单](Total-pipe/环境清单.md)。

## 从论文开始

在完整仓库根目录安装并注册默认四工具入口：

```bash
python3.12 install.py --client codex
```

Claude 使用 `--client claude`，先检查配置可加 `--dry-run`。
使用 [total-pipe-agent Skill](Total-pipe/skills/total-pipe-agent/SKILL.md)，按 next_action 提交 queries、
真实 Story 子代理产物、IR 与视觉提案；用户选择的模型和完整科学内容必须保留。
需要低层三服务时用 `--profile advanced`；[安装与恢复](Total-pipe/docs/agent-adapter.md)。

```text
PWF 证据 → Story → pwf2rpa → RPA 内容规范化 → page_design → canonical Deck IR
  → 整套 Design → Deck Compiler → OfficeCLI → 候选 + QA
```

## 从已有 Deck IR 开始

在 `Total-pipe/` 目录运行：

```bash
python -m agent start --source /abs/deck_ir.json --out-dir /abs/output \
  --language zh --presentation-type group_meeting
```

也可继续使用原编译 CLI：

```bash
python -m deck_compiler visual-prompt --ir deck_ir.json --out visual_prompt.json
# Agent 阅读提示包后编写 visual_proposal.json
python -m deck_compiler apply-visual-plan --ir deck_ir.json \
  --proposal visual_proposal.json --out designed.deck_ir.json
python -m deck_compiler build --ir designed.deck_ir.json --out build/my-deck \
  --officecli officecli --skip-native
```

已有完整设计的 IR 可直接 build。候选在 `candidate.pptx` / `staging.pptx`，
检查 `qa_report.json` 与 `layout_feedback.json` 后修订输入。
已有 IR 的布局/裁图小修可按 `repair` 提供的 Schema 提交 deck_ir_patch：先用 preflight 查看原编译器反馈，
再用 apply 接受，内容/来源变更仍走完整 IR 重规划。最终构建与 QA 保持完整。
正式 `final.pptx` 还需 PowerPoint 逐页验收、原生 PDF、REVIEW 审核及 promote。
四工具任务可在候选后按 `native` 描述，用 `advance.native` 单独导出、生成全页预览并记录实际 UI 复核；
复用已生成 PPTX，QA 随之更新。见[原生接入与恢复](Total-pipe/docs/agent-adapter.md#原生-powerpoint-验收接入)，promote 仍用 CLI。
