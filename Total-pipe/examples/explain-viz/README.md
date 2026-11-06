# ExplainViz 三模板构造样例

`reserved.deck_ir.json` 是三页既有 Deck IR，每页保留明确的背景矩形槽位：
剥离角、层叠结构、过程步骤。文字和关系为开发用构造内容，不对应真实论文或实验。

`slots.json` 绑定预留图形；`proposal.json` 绑定当前 IR 和槽位哈希，提供三个受约束 VisualSpec。
修改源 IR 后须重新准备提案。输出可编辑原生路径和独立文字，不输出位图或原生编组。

从 `Total-pipe/` 运行：

```bash
python -m deck_compiler explain-viz-prompt \
  --ir examples/explain-viz/reserved.deck_ir.json \
  --slots examples/explain-viz/slots.json --out examples/explain-viz/prompt.json
python -m deck_compiler apply-explain-viz \
  --ir examples/explain-viz/reserved.deck_ir.json \
  --slots examples/explain-viz/slots.json \
  --proposal examples/explain-viz/proposal.json --mode auto \
  --out examples/explain-viz/enhanced.deck_ir.json
python -m deck_compiler build --ir examples/explain-viz/enhanced.deck_ir.json \
  --out build/explain-viz --skip-native
```

先查看 stdout 的 `status/applied_visuals/warnings` 与旁路审计。
fallback/skipped 的输出保留原页，不表示新增图示成功。`--skip-native` 为开发模式，正式晋级仍需原生验收。

本轮按用户要求未执行以上命令，未附生成截图或 PPTX，也不声明样例编译通过。
字段、门槛与限制见[协议](../../docs/explain-viz.md)。
