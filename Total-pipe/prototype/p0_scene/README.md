# PageScene 试片：显式页面场景与原生渲染

> 正式入口已经是 `agent/page_scene.py`、`agent/page_scene_qa.py`、
> `agent/page_scene_binding.py`、`agent/page_scene_build.py` 和
> `agent/schemas/page-scene.schema.json`。本目录保留 8 页试片、18 页回归场景、
> 图片资产和独立原型脚本，用于复现页面层结果；日常使用请走 `python -m agent pagespec-*`
> 或 `page_mode=page_scene`，见 [`Total-pipe/docs/page-scene.md`](../../docs/page-scene.md)。

## 验证目标

页面设计不再写散文让编译器猜，而是写显式 PageScene；渲染器直接生成原生 PowerPoint；
每页可立即原生导出检查。

## 当前正式能力

- PageScene 0.1：页面 `title / take / notes`，所有对象显式 `box`（英寸）。
- 原生对象：`text / list / group / image / shape / line / table / path / formula / chart`。
- 多级无序列表：0–3 级原生段落、逐项字号/粗细/颜色。
- 嵌套 group：子对象相对组原点，递归渲染。
- 路径：DrawingML 贝塞尔（`view_box` + `M/L/C/Q/Z`）。
- 公式：OMML（`latex`）。
- 图表：原生可编辑 line/bar/column/scatter。
- 页级门禁、PowerPoint 单页/选页 PNG、job 绑定和 candidate 构建已接入。

旧 `deck_ir` 路径仍保留 Bezier/Path IR、OMML、Chart IR、EViz、完整图形组件和
OfficeCLI；PageScene 不冒充这些复杂对象的完整替代。

## 文件

- `demo.deck.json`：8 页 AVDG 试片。
- `deck18.json`：18 页 AVDG 回归场景。
- `demo_assets/`：原图与裁片。
- `check_pagespec.py` / `render_pagespec.py` / `preview_native.ps1`：早期独立原型，
  保留用于复现；正式入口在 `agent/`。
- `pagespec.schema.json`：早期最小 schema；正式 schema 在 `agent/schemas/`。

## 命令

在 `Total-pipe/` 下：

```powershell
python -m agent pagespec-check --spec prototype\p0_scene\deck18.json
python -m agent pagespec-render --spec prototype\p0_scene\deck18.json --out E:\ppt_x\AVDG_18_scene.pptx
python -m agent pagespec-preview --spec prototype\p0_scene\deck18.json --page P17 --out-dir E:\ppt_x\AVDG_18_scene_preview
```

job 入口：

```text
totalpipe_start(page_mode="page_scene", ...)
advance(scene_preview={artifact_path, page_ids})
advance(artifact_kind="page_scene", artifact_path=...)
```

## 结果

- `pagespec-check`：18 页 PASS。
- `page_scene_build.build`：18 页 candidate，QA PASS。
- PowerPoint 原生导出：18 页。
- `officecli validate`：通过。
- P17 使用 native 多级无序列表 + nested group。

## 限制

- 这个试片是手写 PageScene，不冒充 page_design 绑定、科学审读或 PowerPoint UI 验收。
- EViz 自动讲解图、完整 mechanism/funnel/architecture 组件仍走 `deck_ir`。
- 正式 final promotion 仍是 CLI-only；PageScene 的边界是 candidate + native evidence。
