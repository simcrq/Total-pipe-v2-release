# 示意图示例

一页"没有论文插图也要讲清楚"的演示：流程图由 `tools/make_schematic.py` 生成，deck 里用
`origin: "generated"` 声明来源，图注写明"示意图"。

```bash
cd Total-pipe
python tools/make_schematic.py --spec examples/schematic/flow.json \
  --out examples/schematic/flow.png
python -m deck_compiler build --ir examples/schematic.deck_ir.json --out builds/schematic
```

`flow.json` 是唯一的事实来源（节点文本），`flow.png` 只是它的投影；改图先改 spec 再重跑脚本，
不要手工修 PNG。

支持的 spec：

- `{"kind": "flow", "nodes": [...]}` —— 2–6 个节点的横向流程条，2.6:1；
- `{"kind": "trend", "series": [{"label": ..., "points": [[x, y], ...]}]}` —— 关系曲线；
- `{"kind": "mermaid", "source": "graph LR; ..."}` —— 交给 `mermaid-cli`（需要 `mmdc`，
  未安装时会明确报错，不会静默失败）。

自绘图不是论文证据：它必须带 `generator`、不能写 `source_figure`，图注必须含"示意图"。
