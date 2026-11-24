---
name: total-pipe-photo-to-library
description: >-
  Batch-convert smartphone-photographed PPTX slide images into clean, anonymized,
  reusable native Deck IR scripts in Total-pipe/examples/library/ and safely index
  them in Total-pipe/examples/library/index.json. Use when the user supplies a folder
  or collection of phone-shot slide photos and wants to expand, curate, and index the
  Total-pipe example library.
---

# 手机拍摄 PPT 照片批量构建 Total-pipe 示例库

将大量人工制作的 PPTX **手机实拍照片**，通过“批量预处理与联系表分诊 → 版式骨架提取与去重 → 脱敏原生 Deck IR 重建 → 自动门禁校验与安全打索引”流水线，转化为高质量、可编辑、可检索的 `Total-pipe/examples/library/` 示例库条目。

> **核心原则**：手机照片只用于学习人类优秀幻灯片的**视觉结构、走读路径、载体组合与强调语法**。严禁把手机原图、真实隐私/未公开数据或本地路径写入示例库；每条示例必须用 **Deck IR v2.0 原生对象 + 自洽构造示例数据**重建，并经门禁脚本验证后再入库。

---

## 随附工具与参考

- 批量收图、EXIF 纠偏、连拍去重与联系表脚本：[photo_batch_intake.py](./scripts/photo_batch_intake.py)
- 门禁校验、隐私扫描、防索引劫持与原子入库脚本：[register_example.py](./scripts/register_example.py)
- 照片去噪、Deck IR 映射与打标规则详解：[photo-to-ir-guide.md](./references/photo-to-ir-guide.md)
- 仓库必读参考：`Total-pipe/docs/deck-ir-syntax-reference.md`、`Total-pipe/examples/library/common.py`、`Total-pipe/examples/library/FROM_PPTX.md`

---

## 执行流程（5 阶段闭环）

### Phase 1：批量收图、连拍去重与联系表分诊（避免 Token 爆炸）

不要逐张直接读取几十/上百张原始手机照片。先用 `photo_batch_intake.py scan` 生成**EXIF 自动扶正、dHash 连拍聚类、带编号与质量徽章的 3×3 联系表**，工作目录放在仓库外的临时目录（切勿放在 `Total-pipe/` 内避免污染 Git）：

```bash
python <skill_dir>/scripts/photo_batch_intake.py scan \
  --input-dir "<用户手机照片目录>" \
  --work-dir "<仓库外临时工作目录>" \
  --grid 3x3
```

1. 依次读取输出中的 `contact_sheets/sheet_001.png`、`sheet_002.png`……（每次看图可同时审阅 9 页）。
2. 将肉眼看到的幻灯片按**版式/讲解模式**聚类，优先挑选结构清晰、对示例库有**增量价值**的代表页。
3. 对每个候选模式，先查现有示例库避免重复造轮子：

```bash
python <skill_dir>/scripts/register_example.py find-similar \
  --query "<用中文+英文简述你看到的版式特征>"
```

4. 用 `mark` 将状态写回可断点续跑的 `batch_manifest.json`（连拍重复已自动标 `skipped_duplicate`）：

```bash
# 选中入库代表页
python <skill_dir>/scripts/photo_batch_intake.py mark \
  --work-dir "<work_dir>" --ids IMG_003 --status selected \
  --pattern "<版式族名>" --example-id "<拟定kebab-case-id>" --note "<一句话亮点>"

# 已有同类示例覆盖，跳过
python <skill_dir>/scripts/photo_batch_intake.py mark \
  --work-dir "<work_dir>" --ids IMG_005 --status skipped_existing \
  --matched-existing "<已有example-id>"

# 模糊/反光严重/非幻灯片，跳过
python <skill_dir>/scripts/photo_batch_intake.py mark \
  --work-dir "<work_dir>" --ids IMG_009 --status skipped_unreadable
```

---

### Phase 2：按波次深度读图与版式解剖

每次只取 **3–5 页** `selected` 照片作为一个波次推进，保持上下文清晰、质量可控：

```bash
python <skill_dir>/scripts/photo_batch_intake.py next \
  --work-dir "<work_dir>" --status selected --limit 5
```

对波次中每张照片，打开其 EXIF 已扶正的 `normalized_path` 图像，按 [photo-to-ir-guide.md](./references/photo-to-ir-guide.md) 写出 6 行**视觉走读卡**：
- 脱敏重构后的构造科研/工程主张
- 第一视觉焦点与完整走读顺序
- 区域比例（忽略梯形透视和屏幕黑边）
- 所需的原生 Deck IR 载体（图表 / 架构 / 流程 / 表格 / 公式 / 独立块 / 原图导读）
- 与现有最相近示例的差异化价值

---

### Phase 3：脱敏构造与原生 Deck IR 脚本编写

按需查阅 `Total-pipe/docs/deck-ir-syntax-reference.md` 与 `Total-pipe/examples/library/common.py`，在 `Total-pipe/examples/library/<snake_case_id>.py` 编写独立脚本：

1. **脚本规范**：
   - 文件名使用小写 `snake_case.py`，与 `index.json` 的 `kebab-case` `id` 对应（如 `id: "kpi-ribbon-comparison"` → `kpi_ribbon_comparison.py`）。
   - 必须提供无参入口函数 `make_deck()`，返回符合 `schema_version: "2.0"` 的 canonical Deck IR，优先复用 `common.py` 的 `deck()`、`page()`、`region()`、`block_leaf()`、`chip_panel()`、`comparison_table()`。
2. **原生重构与脱敏底线**：
   - 图表数值由脚本内公开/构造数据实时计算，明确坐标单位与误差定义；不得抄录照片中的私人或未公开实测数据。
   - 若版式需要展示“实拍图/实验图 + 高亮框导读”，**只能复用**仓库 `Total-pipe/examples/demo_deck/figures/` 下现有图片，绝不引入用户的手机照片。
   - 清除一切人名、机构名、邮箱、电话、本地路径和会议水印。

---

### Phase 4：自动门禁校验、视觉复核与原子打索引

脚本写完后，先跑 `register_example.py check`（它会自动执行 `make_deck()`、`ir.validate()`、`compile_deck()`、隐私/路径扫描、`visual_checklist` 几何重叠与孤字换行检测、**9 条锁定回归查询防劫持检查**，以及你指定的主查询 Top-1 命中检查）：

```bash
python <skill_dir>/scripts/register_example.py check \
  --script Total-pipe/examples/library/<snake_case_id>.py \
  --id "<kebab-case-id>" \
  --title "<中文版式标题>" \
  --summary "<1-2句视觉结构与走读说明>" \
  --tags "<8-14个中英双语标签，逗号分隔>" \
  --primary-query "<该示例必须排第1的典型检索词>"
```

1. **若有 `FAIL` 或可修复的 `REVIEW`**（例如 `LOCKED_QUERY_HIJACKED`、`PRIMARY_QUERY_MISS`、`VISUAL_ORPHAN_LINE_WRAPS`、`VISUAL_CHART_ANNOTATION_CLEARANCE`、`VISUAL_FOOTER_CLEARANCE`）：立即修改脚本或调整 `tags`，重新 `check` 至全绿。
2. **建议视觉抽检**：对结构复杂的新版式，用 `catalog.py build` 编译为可编辑 PPTX；若本机已安装 OfficeCLI 与 PowerPoint，直接加 `--render-png` 一步导出高分辨率 PNG 预览图（`<out>/slides_png/slide_001.png`）并肉眼复核无拥挤、无遮挡、留白均衡：

```bash
python Total-pipe/examples/library/catalog.py build <kebab-case-id> --out "<work_dir>/preview/<kebab-case-id>" --render-png
```

（若未安装 PowerPoint，可省去 `--render-png` 仅生成可编辑 PPTX。）

3. **通过后原子注册入 `index.json`**：

```bash
python <skill_dir>/scripts/register_example.py register \
  --script Total-pipe/examples/library/<snake_case_id>.py \
  --id "<kebab-case-id>" \
  --title "<中文版式标题>" \
  --summary "<1-2句视觉结构与走读说明>" \
  --tags "<8-14个中英双语标签，逗号分隔>" \
  --primary-query "<典型检索词>"
```

4. 回写 `batch_manifest.json` 进度：

```bash
python <skill_dir>/scripts/photo_batch_intake.py mark \
  --work-dir "<work_dir>" --ids IMG_003 --status indexed --example-id "<kebab-case-id>"
```

---

### Phase 5：大批量作业策略与整库收尾审计

- **50 张以上大批量照片**：
  - Phase 1 先一次性完成全量联系表分诊，导出清单中全部 `selected` 代表页（通常 100 张实拍去重后可浓缩为 10–25 个高价值独立版式）。
  - Phase 2–3 可按波次（每波 3–5 页）推进，或拆分波次给多个并行子代理分别编写各自独立的 `<snake_case>.py` 脚本；**Phase 4 的 `register_example.py register` 必须串行执行**，避免并发改写 `index.json` 或相互抢占标签排名。
  - 随时用 `photo_batch_intake.py status --work-dir "<work_dir>"` 查看进度并支持中断恢复。
- **整库收尾审计**：全部波次入库后，运行整库审计确认 0 回归，并向用户汇报本次新增条目、跳过原因统计与检索测试结果：

```bash
python <skill_dir>/scripts/register_example.py audit-library
```

若本机安装了 `jsonschema`，也可追加运行 `pytest Total-pipe/tests/test_example_library.py` 做最终确认。
