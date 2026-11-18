# Deck IR 脚本示例库

从 `Total-pipe/` 目录执行。先按任务关键词查索引，再打开相关的一份示例。

```bash
python examples/library/catalog.py search "独立正文块 圆角标题 编号" --limit 2
python examples/library/catalog.py show independent-blocks
python examples/library/catalog.py build independent-blocks --out /tmp/totalpipe-independent-blocks
```

`search` 仅读取元数据索引，返回 ID、摘要和脚本路径。可用中文、英文或 Deck IR 字段名检索。例子包括
`A/B 对照路线`、`四向说明` 和 `caption_for`。无匹配时返回空数组。
`show` 只执行所选脚本，并输出 canonical Deck IR，其中的文案、证据编号和素材用于演示结构。
`build` 使用正常编译器输出可编辑候选和 QA 报告，PowerPoint 原生验收按实际项目工作流执行。

在 Agent 工作流中，整套及逐页 IR 提示的 `example_lookup` 提供实际解释器和检索脚本路径。
页面设计负责写清视觉关系。IR 作者根据需要查询，把示例的结构应用到批准的 `copy_ref`、证据和选图。
独立正文每条用一个 block ID，符号逐块声明。顺序由布局树和各块的 `list_start` 表达。
`independent-blocks` 用无外框的圆角标题标识两组正文。

## 添加示例

1. 在此目录添加一个 Python 文件，提供无参数的 `make_deck()`，返回完整 canonical Deck IR。需要的资源相对脚本定位。
2. 在 [index.json](index.json) 添加唯一 `id`、`title`、中英关键词 `tags`、短 `summary` 和脚本文件名 `script`。
3. 验证检索能命中。用 `show` 检查生成的 IR，用 `build` 检查候选。测试会检查所有新索引项的 Schema 和编译结果。
