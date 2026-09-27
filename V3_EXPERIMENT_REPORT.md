# Total-pipe v3 实验接入报告

## 结论

v26 布局模型已在本实验目录接入完整 v2，完成真实 9 页 IR → 模型布局建议 → 编译器 → OfficeCLI → PPTX 与逐页截图。适合继续实验；尚未满足生产 final 发布门禁。

## 已完成

- 新增可选 `--layout-provider v26`；默认仍为 deterministic。
- 模型只提供 bbox，科学内容和 canonical IR 保持原样；编译器负责最终元素，OfficeCLI 写入 PPTX。
- 本次逐页路径：{'MODEL_PROPOSAL': 8, 'PACKING_FALLBACK': 1}。第 8 页为保护 0.216 数字完整而使用 packing 回退。
- 在实际实验目录运行完整测试：48/48 通过（最近运行 13.667 秒）。
- OfficeCLI 1.0.152 实际运行 `review-officecli`：schema 0 错误、9 张原生截图导出完成。
- 独立审查已逐页查看 9 张截图，全部视觉 PASS。第 5、9 页图中细字可选放大以改善投影阅读。
- 保留用户已有修改；原始文件备份见 `.v3-integration-backup`，安装增量已逐项校验 manifest 哈希。

## 同一 IR 对照

| 构建 | FAIL | WARNING | REVIEW |
|---|---:|---:|---:|
| v2 baseline | 0 | 19 | 7 |
| v26 experiment | 0 | 16 | 7 |

8 页模型成功不等于模型已普遍成熟；以上是这份 9 页案例及现有测试集的结果。

## 尚未通过的检查

- 原始 OfficeCLI issues 仍有 16 条 text overflow，因此严格 CLI 状态为 **REJECT**，命令退出码为 1。截图视觉 PASS 不覆盖这些警告。
- 示例：第 2 页 shape 100014 的实际文本为 2 行，wrap=false，21pt、26.25pt 行距、约 80pt 框高；CLI 估算为 4 行需 105pt。截图未显示截断，怀疑自动估算误报，尚未修改上游检测器或清除警告。
- 原有 7 项 REVIEW 保留。未生成 PowerPoint UI 眼检证据，也未晋级 final。
- OfficeCLI PDF 导出尝试返回 exporter_not_found；本机未安装相应 exporter，未生成 PDF。

## 文件与复现

- 实验候选：[candidate.pptx](builds/graphene-v26/candidate.pptx)
- 总览：[officecli-native-contact.png](builds/graphene-v26/officecli-native-contact.png)
- CLI 检查：[officecli_review.json](builds/graphene-v26/officecli_review.json)
- 独立逐页审查：[officecli_visual_review.json](builds/graphene-v26/officecli_visual_review.json)
- 逐页来源：[layout_provider.json](builds/graphene-v26/layout_provider.json)
- 命令及环境：[v3-experiment.md](Total-pipe/docs/v3-experiment.md)

PPTX SHA-256：`1f4bb396b207251727e39fb38b19e3c95e63f538b6f05102da3c3ee790d72139`。
IR SHA-256：`b76968cb892023841312e9d774119bd1769b7e1ceee83c08787217d631a5ae2a`。
模型 SHA-256：`ab306795c73c8c6888889e78aadc2acd0bc799eee9614af67b0e1f865f5d050c`。
