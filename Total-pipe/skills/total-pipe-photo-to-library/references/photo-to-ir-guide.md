# 手机拍摄 PPT 照片 → Total-pipe Deck IR 重建与索引手册

本手册供 `total-pipe-photo-to-library` 在深度拆解单页照片、映射到 Deck IR 原语以及设计高召回不冲突的索引标签时按需查阅。

---

## 1. 手机拍摄 PPT 照片的专项处理规则

与直接导出 PPTX 不同，手机实拍会引入几何畸变与环境噪音。按以下规则去噪，**只提炼版式骨架与讲解逻辑，不照抄像素与私人内容**：

| 照片干扰类型 | 正确处理方式 | 禁止行为 |
| --- | --- | --- |
| 梯形透视畸变 / 歪斜拍摄 | 根据屏幕四边还原视觉比例（如左 62% / 右 38%、上 45% / 下 55%），用原生 `columns`/`rows` 权重重建 | 不要把透视倾斜画成斜切图形 |
| 屏幕反光 / 摩尔纹 / 局部过曝 | 识别结构骨架与可读标题；被反光遮住的数字或小字，用**同量级且自洽的构造科学算例**补全 | 不要胡猜看不清的真实实验数字 |
| 演讲者遮挡 / 激光笔红点 / 礼堂黑边 | 完全忽略屏幕外环境、讲台、窗帘、水印、会议角标和激光笔光点 | 绝不把手机原图直接放进 `Total-pipe/examples/` |
| 字体/配色受投影偏色影响 | 保留“主色 + 强调色 + 中性灰”的**层级对比关系**，映射到 Total-pipe 默认科研配色（`#266E72` 主色、`#B85D3B` 暖色强调、`#142735` 正文） | 不要照搬投影仪发青/偏黄的原始 RGB |
| 照片中包含真实人物、单位、未发表数据、邮箱/二维码 | **100% 脱敏替换**：改写为清晰、自洽、可复现的公开科研或工程**构造示例**（标注 `origin: "generated"` 或构造来源） | 严禁保留姓名、校徽、机构名、真实未公开数据、本地路径或联系方式 |

---

## 2. 照片视觉模式 → Total-pipe Deck IR 原语映射表

完整字段写法与参数边界以仓库内 `Total-pipe/docs/deck-ir-syntax-reference.md` 和 `Total-pipe/examples/library/common.py` 为准。

| 照片里看到的典型版式/组件 | 优先使用的 Deck IR 原语 | 关键注意事项 |
| --- | --- | --- |
| 左右双栏 / 上下双区 / 三段网格 | `layout_tree`（`columns` / `rows` + `weights`，`gap: "compact"`） | 避免三列并排塞满长段落导致单列过窄；优先双主角或“上架构 + 下双栏” |
| 顶部分层架构 / 技术栈 / 流水线 | `graphics[].kind = "architecture"`（`layers` + `items` + `connections`） | 保持节点文字精炼（单行或极短两行），默认 `academic` 简洁风不堆叠花哨渐变 |
| 单线流程 / 阶段演进 / 双泳道对照 | `graphics[].kind = "process"` 或 `dag`（配合 `tracks`/`lanes`、`action_label`） | 状态节点与动作标签分离，对照路线尽量对齐列位 |
| 机理图 / 激活与抑制 / 假设虚线 | `graphics[].kind = "mechanism"`（`activate` / `inhibit` / `dashed`） | 用 T 形端帽和虚线区分实证关系与可检验假设 |
| 漏斗收缩 / 问题逐层聚焦 | `graphics[].kind = "funnel"` | 左侧漏斗 + 右侧缺口/切入路径是高频立题页构图 |
| 自定义剖面 / 波形 / 辐射类比 / 路径示意 | `graphics[].kind = "path"` / `diagram`（几何图元 + 坐标连接） | 跨图对应元素用同一强调色建立视觉锚定 |
| 折线图 / 柱状图 / 水平消融条形图 / 散点误差图 | `charts[]`（`line` / `bar` / `hbar` / `scatter`，支持 `x.categories`、`y_error`、`reference_lines`、`shaded_zones`、`annotations`） | 数值由脚本内构造数据直接计算，明确单位、坐标范围与误差定义 |
| 多级合并表头 / 参数对照矩阵 / 边界表 | `tables[]`（`header_rows`、`row_span`、`column_span`、`column_weights`） | 合并表头用原生表格单元格而非画矩形拼接 |
| 原图/实验显微图 + 局部放大/框选导读 | `figure_refs[]` + `highlights`（必要时配 `image_grid` 或 `figure_crop`） | **只能引用仓库内已有示例图**（如 `Total-pipe/examples/demo_deck/figures/` 下文件），严禁引入手机原图 |
| 行内数学符号 + 独立大公式 + 符号解释 | `inline_math` + 独立 `equation` 块 + `anchor` / `caption_for` | 只使用编译器支持的原生 OMML 语法 |
| 分组圆角标签头 + 独立编号要点 | `chip_panel()` + 多条独立 `block`（`native_bullet_list` / `native_numbered_list` + `list_start`） | 每条独立要点保留自己的 `block ID`，防止合并成一整块死文本 |

---

## 3. 单页“视觉走读卡”模板（Phase 2 必写）

动笔写 Python 脚本前，先用 6 行文字把单张照片的版式骨架定下来，避免写着写着跑偏：

```text
Photo ID: IMG_014 -> Proposed Example ID: <kebab-case-id>
1. 一句话主张（改造为脱敏构造场景）: ...
2. 第一视觉焦点: ...（如“左侧水平消融条形图的阈值虚线”）
3. 走读路径: 标题/Takeaway -> [区A] -> [区B] -> [区C]
4. 区域比例与结构: layout_tree = rows([0.44, 0.56]) / columns([0.58, 0.42]) ...
5. 视觉载体清单: architecture / hbar chart + reference_lines / comparison_table / independent numbered blocks ...
6. 差异化价值: 与现有 index.json 最接近条目 <existing-id> 相比，新增了什么版式组合或讲解手法？
```

---

## 4. `example_index.py` 检索引擎打标规则与防冲突清单

Total-pipe 的检索引擎（`Total-pipe/deck_compiler/example_index.py`）对每条 `index.json` 记录按以下权重打分：

- `exact` 命中（完整 tag 或精确词项匹配）：**+10 分**
- `partial` 命中（子串 / 2-gram / 3-gram 命中）：**+5 分**
- `intent_hits`（`_INTENT_HINTS` 意图词命中）：**+2 分**
- `contextual`（`title` / `summary` 命中）：**+1 分**

### 高召回、低冲突打标准则

1. **8–14 个双语标签**：
   - **3–5 个中文场景/结构词**（用户怎么搜它，如 `"双栏对比"`, `"时间轴演进"`, `"指标卡片矩阵"`）
   - **3–5 个中文视觉手法词**（关键构成，如 `"横向消融"`, `"色块聚焦"`, `"上下对照"`）
   - **3–5 个英文意图 + Deck IR 原语词**（如 `"timeline"`, `"kpi cards"`, `"hbar"`, `"reference_lines"`, `"image_grid"`）
2. **避免泛滥复制旧条目的专属触发词**：不要把别的样例的招牌词盲目塞进 `tags`，否则会劫持已有查询！
3. **9 条受测试锁定的查询（绝不可被新条目劫持 Rank #1）**：
   - `独立正文块加圆角标题和编号` → `independent-blocks`
   - `A/B 对照路线 动作标签` → `comparison-lanes`
   - `directional annotations caption_for` → `directional-notes`
   - `原图导读 图文并排` → `figure-readout`
   - `误差棒 y_error` → `chart-uncertainty`
   - `native table merged headers` → `grouped-table`
   - `行内公式 独立公式 符号定义` → `equation-explainer`
   - `机制图 假设虚线` → `mechanism-hypothesis`
   - `复杂混排 曲线与公式` → `rc-discharge-composite`

`register_example.py check` 和 `register_example.py register` 会自动对以上全部 9 条查询执行无回归校验，并验证你为新样例指定的 `--primary-query` 稳居第 1 名。

---

## 5. 隐私与合规底线检查（入库前零容忍）

- 照片里的真实人名、课题组名、医院/公司名、论文尚未公开的数字、邮箱、手机号、二维码、微信水印、相机路径**不得出现**在脚本、注释、`speaker_notes` 或 `index.json` 中。
- `evidence_refs` 统一使用 `common.py` 的 `SOURCE`（`'fixture:layout-examples'`），并在图注/表注或正文里注明“构造示例”。
- `batch_manifest.json`、归一化照片和联系表（`contact_sheets/`）属于临时工作区，**必须放在仓库外或未追踪临时目录**（如 scratch/tmp），严禁把用户的原始手机照片提交进 Git 仓库！
