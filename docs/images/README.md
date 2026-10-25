# README 展示图

两张 PNG 均由 Microsoft PowerPoint 的“导出 → PNG → 仅保存当前幻灯片”生成，尺寸为 1920 × 1080。
图片是实际幻灯片的渲染结果；源文件保留可编辑文字、公式、表格和图形。

| 图片 | 来源与范围 |
| --- | --- |
| [complex-mixed.png](complex-mixed.png) | [复杂混排单页 PPTX](../../Total-pipe/examples/complex-mixed/complex-mixed.pptx)；[IR、参考图片来源及重建步骤](../../Total-pipe/examples/complex-mixed/README.zh-CN.md) |
| [native-table.png](native-table.png) | [原生表格样例 IR](../../Total-pipe/examples/native-table.deck_ir.json) 的 `merged-table` 第一页；展示标题改为“原生科研表格：多级表头、合并单元格与矩阵”，其余表格内容沿用样例 |

复杂混排中的两张设备照片来自用户提供参考页的裁图，已随可编辑样例保存；原始分辨率较低。
数学内容用于展示编译器功能。表格是独立算例，不与第一张混排页共享同一个数值矩阵。

2026-10-25 完成画面与元数据检查：

- 仅包含幻灯片区域，无桌面、窗口标题、账户或讲稿。
- 未见姓名、个人联系方式、本机路径或密钥。
- 已去除 EXIF 和 PNG 文本元数据；保留的像素数据未重新压缩或改写。
- 两张图片均经过独立视觉检查，文字、矩阵、根号和指数未见明显裁切或遮挡。

后续替换展示图时，重新从对应 PPTX 导出，并重复画面和元数据检查。
