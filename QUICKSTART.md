# Total-pipe 快速开始

当前组件、版本、环境和完整入口以 [README.md](README.md) 为准。
完整操作见 [中文使用说明](Total-pipe/docs/USAGE.zh-CN.md)，安装见 [环境清单](Total-pipe/环境清单.md)。

## 从论文开始

加载 `paperworkflow`、`research_ppt` 和 `total_pipe_v3` 三个 MCP 服务，
使用 [total-pipe-deck Skill](Total-pipe/skills/total-pipe-deck/SKILL.md) 调度：

```text
PWF 证据 → Story → pwf2rpa → RPA → canonical Deck IR
  → 整套 Design → Deck Compiler → OfficeCLI → 候选 + QA
```

## 从已有 Deck IR 开始

在 `Total-pipe/` 目录运行：

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
正式 `final.pptx` 还需 PowerPoint 逐页验收、原生 PDF、REVIEW 审核及 promote。
