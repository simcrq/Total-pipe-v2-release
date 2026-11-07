# Page design 1.1 实际样例

`page_design.json` 是独立子代理根据本次 RFGPT 论文既有 Story/证据生成的 10 页视觉设计样例。
宿主实际调用请求为 `gpt-6-luna`、`reasoning_effort=max`；不是主代理代写。

每页只必填 `id`、`content_refs`、`design`。其中 composition / walkthrough / risk 等键由设计者自行选用，
不属于 Schema 必填模板。内容引用继承 Story，不再逐页复制 claim、items 或 rationale。
第 3 页沿用用户喜欢的器件原图与材料功能对应；其他页分别使用概念关系、流程、原图比较与收束路径。

这是协议与设计交接样例，不是已编译或完成 PowerPoint 验收的幻灯片。P5/P8/P9 仍需在 IR/布局阶段
检查实际容量；结构校验不等于排版通过。原 PDF、Story、OCR 与图片不打包到本目录，图片 asset_id
须由原 workflow_root 解析，文件不能独立生成 PPTX。

本机实际任务、人工复核修订与测试记录见 [验证报告](../../../docs/agent-page-design-validation.md)。
协议见 [页面设计说明](../../docs/agent-adapter.md#页面设计阶段page_design)，
Schema 见 [page-design.schema.json](../../schemas/page-design.schema.json)。
