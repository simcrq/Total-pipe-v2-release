# 复杂混排单页样例

[直接打开可编辑 PPTX](complex-mixed.pptx)。

一页同时包含以下对象：

- 两张 `origin: reference` 图片、原始来源说明和图注。
- layout tree 1.2 的两个原生边框面板和标题色带。
- 带独立黑色大菱形的 takeaway，包含原生行内数学内容。
- 带橙色原生箭头的两条无序列表，实测高度 73.5 CSS px，低于旧的 220 px 下限。
- 对称正定矩阵的 Cholesky 分解，以及包含根号、分式、指数的行内响应函数。
- graphics/path 绘制的集成光子芯片图案：等距基底、双微环、弯曲波导、电极及输入输出光束，共 22 个可编辑的 PowerPoint 原生自定义几何对象。

图片与文字、图案的大小由布局树分配；没有在 canonical IR 中写绝对页面坐标。
左侧两图并排，说明与小图案共用底部一行，避免图案单独占一整行而把图片压小。

## 文件与来源

| 文件 | 用途 |
| --- | --- |
| `complex-mixed.deck_ir.json` | 已完成设计的 canonical IR，可修改内容后重建 |
| `complex-mixed.pptx` | 从该 IR 编译的单页样例 |
| `assets/*.jpg` | 用户提供的可行性参考页照片裁图，原始字节保留 |
| `validation.json` | 绑定本次 IR / PPTX 哈希的结构与 PowerPoint UI 检查记录 |

两张裁图的原始分辨率均为 126 × 114 px，适合作为功能测试素材；正式汇报应替换为原始高清照片。
`reference_source` 和讲稿保留来源，裁图不作为独立科研证据。矩阵与响应函数为演示模型，
不代表照片所示平台的实测结果。芯片图案用于演示原生 Path 功能，不代表实际器件拓扑或实验数据。

## 重建

先按[环境清单](../../环境清单.md)安装编译依赖、OfficeCLI 和中文字体。
在仓库的 `Total-pipe/` 目录运行：

```bash
python -m deck_compiler build \
  --ir examples/complex-mixed/complex-mixed.deck_ir.json \
  --out build/complex-mixed --officecli officecli --skip-native
```

新产物位于 `build/complex-mixed/`。默认不覆盖这里版本管理的样例文件。
样例声明 Microsoft YaHei，编译器仍按平台解析和替代字体；字体变化可能改变换行与几何。
数学内容始终保留原生结构和完整术语。

## 本次检查

2026-10-24 使用 OfficeCLI 1.0.158 生成并检查，OpenXML Schema 为零错误，编译与结构检查为零 FAIL。
已直接打开实际 PPTX 并在 Microsoft PowerPoint 放映中复核，包括独立视觉审查。

OfficeCLI 对含原生分式的混排文本报告一条通用 `text overflow` 警告。
原始警告保留在检查记录中；PowerPoint 放映中公式和后续文字均完整显示，未见裁切或碰撞。
近似数学测量、参考图片来源等 REVIEW 保持可见，不能把这份功能样例当作自动晋级的科研 final。
本次未导出 PowerPoint 原生 PDF，也未执行 final 晋级。
