# 启发式质量指标

该模块分析已有构建目录中的 `qa_report.json`，并在存在时读取 `layout.json` 与 `deck_ir.json`。
实现见 [quality_metrics.py](../deck_compiler/quality_metrics.py)，当前 CLI 见 [unified_cli.py](../deck_compiler/unified_cli.py)。

## 使用

在 `Total-pipe/` 运行：

```bash
python totalpipe.py quality build/my-deck
python totalpipe.py quality build/my-deck --detailed
python totalpipe.py quality build/my-deck --json
```

CLI 的 JSON 输出前仍有进度行；需要纯结构化数据时直接调用 Python API：

```python
from pathlib import Path
from deck_compiler.quality_metrics import analyze_quality

result = analyze_quality(Path("build/my-deck"), detailed=True)
payload = result.to_dict()
```

维度为 `readability`、`consistency`、`completeness`、`balance`、`accessibility` 和 `scientific`。
`QualityReport.passes()` 的当前默认判断是加权分数至少 70 且没有 CRITICAL 指标；
该布尔值只表示此启发式分析的结果。CLI 成功输出报告的退出码也不是验收结论。

## 使用边界

- 分数基于构建元数据和规则，不能验证科研结论、图像内容、真实可读性或 PowerPoint 实际渲染。
- 不为提高分数删去原文、缩写专业术语、改写数值或把证据移入不可见区域。
- 正式交付以当前 QA、实际 PPTX 结构、PowerPoint UI / 原生 PDF 和 REVIEW 审核为准。
- 历史的固定分数目标、测试数量和“production ready”声明见[旧质量指标记录](../../docs/archive/Total-pipe/docs/QUALITY_METRICS.md)，不作为现行验收要求。

流程见[中文使用说明](USAGE.zh-CN.md)，文档导航见[当前索引](../../docs/README.md)。
