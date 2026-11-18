# README 展示图

本目录的两张 PNG 通过 Microsoft PowerPoint 的“导出 → PNG → 仅保存当前幻灯片”生成。
三张讲解示意图来自对应样例的 PowerPoint 原生 PDF。五张图均为 1920 × 1080 的幻灯片画面。

| 图片 | 来源与范围 |
| --- | --- |
| [complex-mixed.png](complex-mixed.png) | [复杂混排单页 PPTX](../../Total-pipe/examples/complex-mixed/complex-mixed.pptx)；[IR、参考图片来源及重建步骤](../../Total-pipe/examples/complex-mixed/README.zh-CN.md) |
| [native-table.png](native-table.png) | [原生表格样例 IR](../../Total-pipe/examples/native-table.deck_ir.json) 的 `merged-table` 第一页；展示标题改为“原生科研表格：多级表头、合并单元格与矩阵”，其余表格内容沿用样例 |
| [剥离角](../../Total-pipe/examples/explain-viz/whitespace-filled/slide-1.png)、[层叠结构](../../Total-pipe/examples/explain-viz/whitespace-filled/slide-2.png)、[工艺流程](../../Total-pipe/examples/explain-viz/whitespace-filled/slide-3.png) | [三页讲解标注样例](../../Total-pipe/examples/explain-viz/whitespace-filled/README.md)。图形和标注可在[样例 PPTX](../../Total-pipe/examples/explain-viz/whitespace-filled/filled.pptx)中编辑。三页使用构造内容。 |

复杂混排中的两张设备照片来自用户提供参考页的裁图，已随可编辑样例保存；原始分辨率较低。
数学内容用于展示编译器功能。表格是独立算例，不与第一张混排页共享同一个数值矩阵。

2026-10-25 对混排和表格两张图完成画面与元数据检查。

- 仅包含幻灯片区域，无桌面、窗口标题、账户或讲稿。
- 未见姓名、个人联系方式、本机路径或密钥。
- 已去除 EXIF 和 PNG 文本元数据；保留的像素数据未重新压缩或改写。
- 两张图片均经过独立视觉检查，文字、矩阵、根号和指数未见明显裁切或遮挡。

新增到首页的三张讲解示意图均已逐页查看，画面只包含幻灯片及页码，未见账户、个人路径或讲稿。

后续替换展示图时，重新从对应 PPTX 导出，并重复画面和元数据检查。
