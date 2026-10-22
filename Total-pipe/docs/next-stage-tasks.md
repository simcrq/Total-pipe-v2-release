# 下一阶段任务（仅记录，未执行）

状态：**待办**，未写任何代码。本文只把三条需求固化成可执行的设计，避免下一阶段重新讨论。
前置约定（与现有架构一致，三条任务都不得破坏）：

- Deck IR 不出现几何；版式与坐标只能由编译器产生。
- 提供方（packer / compiler / plugin）只回答 bbox，不写内容、不写样式。
- 任何"看起来更好"的改动都必须有门禁或测量兜底，不能只靠肉眼。

---

## 任务 1：多段长文本改用 PowerPoint 原生无序列表，并给符号单独上色

> **状态：已实现。** 一个 block = 一个文本框，每个条目是一个段落，`a:buChar` / `a:buFont` /
> `a:buClr` 由编译器直写，悬挂缩进 + 段间距由 `a:pPr` 控制；`presentation.bullet_style` 与
> `theme.accent` 进入 schema，deck 级只用一个符号样式；结构校验新增 `LIST_BULLET_MISMATCH`。
> 与计划的差异：段间距用 `a:spcAft` 而不是每行单独居中（一个文本框里无法逐段居中）；
> 符号默认色改为 `#C2410C`（新增 `DEFAULT_ACCENT`），不再跟随正文色。

### 现状

一页里多段并列文本时，编译器走 `distributed_arrow_list`（`deck_compiler/text_flow.py`）：
把每个条目渲染成**两个独立对象**——一个 `➢` 文本（`layout.py:260`，颜色取 `theme.accent`）
加一个正文文本（`layout.py:262`），外面套一层浅色面板。

后果：

- 在 PowerPoint 里它不是列表：没有列表缩进、不能调用"项目符号和编号"菜单、复制单条不带符号。
- 每页多出 N 个装饰对象，`structure` 校验与后续人工编辑都要照顾它们。
- 符号形态只有 `➢` 一种，长文本页全是同一个符号，层级信息丢失。

### 目标

1. 一个 block = **一个文本框**，每个条目是**一个段落**，符号由段落属性（`a:buChar` + `a:buFont`）产生。
2. 符号颜色独立于正文（`a:buClr`），默认用 `theme.accent`，正文保持前景色。
3. 符号样式从 PowerPoint 内置的九种里按语义选，**一页不超过两种层级**（一级 + 二级）。
4. 保留现有的确定性断行：条目内部仍由编译器排好行，不交给渲染器自动换行。

### 设计要点

- **段落与换行**：条目之间用 `\n`（新段落），条目内部的手工断行用 `\v`（同段换行）。
  OfficeCLI 的文本约定正好如此（`\n` 起新段落、`\v` 段内换行），所以"原生列表 + 预排断行"
  可以同时成立，不必打开 `wrap=square`。
- **悬挂缩进**：`marL` = 符号宽 + 间距（建议 0.62cm），`indent` = −同值，保证第二行文字与
  第一行正文对齐，而不是顶到符号下面。
- **样式映射**（建议，实现前先用一页纸验证）：

  | 语义 | 内置样式 | 说明 |
  |---|---|---|
  | 要点（默认） | `•` 圆点 | 最中性，长文本页默认 |
  | 并列对照 / 清单 | `▪` 或 `□` | 空心方块用于"假设/待验证"一类 |
  | 步骤、方向性 | `➢` 或 `→` | 保留现有观感，换成真正的列表符号 |
  | 结论、确认项 | `✓` | 只在"已确认"语义上用，避免滥用 |

  用户截图里的九宫格即为 PowerPoint「项目符号」下拉：无 / 圆点 / 方块 / 菱形 / 空心方块 /
  对勾 / 箭头 / 小圆点等，映射时优先用这些原生形状，自定义字体符号只在必要时用。

- **后端落点**：
  - OfficeCLI 的 `paragraph.list`（别名 `bullet`）已支持预设 `bullet|dash|arrow|check|star|none`
    与字面字符，`indent` / `marginLeft` / `level` 也有类型化属性；
    但**没有 `buClr` 类型属性**，符号颜色需要 `raw-set` 在 `a:pPr` 插入
    `<a:buClr><a:srgbClr val="..."/></a:buClr>`，或等上游补一个 `bulletColor`。
    动手前先用一页探针确认：`list=` 写入的 `buFont/buChar` 与手写 `buClr` 能否共存、
    `get` 回读是否变成 `bulletRaw`。
  - `deck_compiler/officecli.py` 的 `commands()` 目前每个文本元素发一条 `add`；改为
    "一个 block 一条 add + 若干 set（每段 list/indent/buClr）"，仍走同一个 batch。
  - artifact-tool 后端需同步，否则两个后端的产物不一致。

### 门禁与回归

- `ORPHAN_LINE`、`MIN_FONT_PT`、`DECIMAL_SPLIT` 仍按**段落内容**判定，不能因为换成原生列表就
  只看整体文本框。
- 新增断言：同一 block 的段落 `marL` 必须一致；一级符号只能一种；`buClr` 与正文色不同。
- 现有 `tests/test_deck_compiler.py`、`tests/test_layout_provider.py` 里针对 `:arrow:` 对象的
  断言要一起改（对象数量会减少，`adaptation_log` 的 `bullet_glyph` 字段需要换成语义名）。

### 验收标准

- 生成的 PPTX 中，选中一段文本按 Tab/Shift+Tab 能升降级，右键能看到项目符号菜单已选中对应样式。
- 符号颜色与正文不同；把 PPT 发到没有安装本机字体的机器上，符号仍能显示（`buFont` 用系统通用字体）。
- `python -m deck_compiler build` 仍然 0 FAIL；页面在 `review-officecli` 截图里与改造前视觉一致或更整齐。
- 对象数下降（每页少 N 个装饰对象），结构校验不退化。

### 未决

- 符号颜色是否需要跟随主题（`theme.accent`）还是固定在 `presentation` 里可覆盖？倾向前者，后者等真实需求。
- 二级列表要不要支持？现在 `distributed_arrow_list` 是单层，先做单层，多级留到有人真的写出层级文本。

---

## 任务 2：缺图/留白时，用 SVG / mermaid 先画结构化示意图再插入

> **状态：已实现（mermaid 后端需要 `mmdc`）。** `assets.origin: paper|generated` 与 `generator`
> 进入 schema；`origin=generated` 时禁止 `source_figure`（`FIGURE_PROVENANCE_FORBIDDEN`）、
> 要求 generator（`SCHEMATIC_GENERATOR_REQUIRED`）、图注必须含"示意图"（`SCHEMATIC_CAPTION_REQUIRED`）；
> 尺寸与图注门禁不放宽，但报 `SCHEMATIC_TOO_SMALL` / `SCHEMATIC_REVIEW` 以区别于论文图。
> 生成器为 `tools/make_schematic.py`（flow / trend 用 matplotlib，mermaid 走 `mmdc`），
> 参考页 `examples/schematic.deck_ir.json`。本机没有 `mmdc`，所以 mermaid 路径只验证了
> "缺工具时明确报错"，实际渲染待装了 mermaid-cli 的机器复核。

### 现状

- `figure_refs` 必须带 `source_figure`，且图注必须写出 `Fig.N`，否则
  `FIGURE_PROVENANCE_REQUIRED` / `FIGURE_CAPTION_MISMATCH` 直接 FAIL（`deck_compiler/ir.py:118-130`）。
  也就是：**只接受论文原图**，没有任何"自绘图"的位置。
- 留白已经有检测：`TEXT_ONLY_LOWER_WHITESPACE`（`layout.py:103`，下部空白 ≥160px 且 ≥40% 报
  WARNING），`MAX_FIGURE_VOID` 控制图框空洞。
- 结果：当原文没有合适的图，页面只能靠文字堆，或者留出一大块空白——这正是用户提的场景。

### 目标

在**图缺失**且**页面会因此大面积留白**时，允许先画一张结构化示意图（流程、结构、趋势），
再作为普通图片资产进入同一条编译链路。重点：不伪造"论文插图"，也不把生成过程塞进编译器。

### 设计要点

1. **谁决定要画图**：planner（Story/RPA 阶段）显式产出 `schematic_request`，或在 Deck IR 里
   用 `figure_refs[].origin = "generated"` 声明；编译器只负责排版与门禁，**不自己猜"这里该补张图"**。
   自动触发最多做到"报 WARNING 提示可补图"（复用 `TEXT_ONLY_LOWER_WHITESPACE`），不自动生成。
2. **来源必须可辨**：
   - `assets.<id>` 增加 `origin: "paper" | "generated"`（默认 `paper`）与 `generator`（`mermaid` /
     `svg` / `matplotlib` + 版本）。
   - `origin=generated` 时**禁止**写 `source_figure`；图注用独立编号（`图 A` / `Fig. S1`），
     并强制含"示意图"字样，避免被当成实验结果。
   - `FIGURE_PROVENANCE_REQUIRED` 相应放宽为"论文图必须有 source_figure，自绘图必须没有"。
3. **生成位置**：在 Deck IR 之前、由脚本产出 PNG 落盘（`assets/` 目录），IR 只引用路径。
   推荐链路：`mermaid` 源码 → `mmdc`（mermaid-cli）导出 SVG → 2× 栅格化成 PNG；
   代码里现成的 `matplotlib`（已在 `examples/demo_deck/make_figures.py` 用过）是趋势曲线的兜底。
   直接在 PPTX 里放 SVG 也可以（PowerPoint 2016+ 原生支持），但 OfficeCLI 的 `picture` 对 SVG
   的行为未验证，先按 PNG 走。
4. **尺寸与门禁**：生成的图同样受 `min_panel_extent`（默认 220px）、`FIGURE_VOID ≤ 0.15`、
   图注字号与 `FIGURE_CAPTION_SLACK` 约束——不能因为"自绘图"就放宽。
5. **可复现**：`mermaid` 源码与生成脚本必须提交（放在 deck 的 `assets/` 旁），
   只提交 PNG 等于不可复现；`layout_provider.json` 的 `source_sha256` 再把它们绑进构建溯源。

### 触发与判据（建议）

- 硬条件：该页 `figure_refs` 为空或图片缺失，且版面留白超阈值（现有 WARNING 的同一套计算）。
- 软条件（由 planner 判断）：内容是流程/分层结构/两三条趋势对比，且用文字描述会超过 60 字。
- 反例：真实数据曲线、显微图、照片一律不生成——那些必须来自论文，生成即造假。

### 验收标准

- 一张缺图页在开启该能力后，`TEXT_ONLY_LOWER_WHITESPACE` 消失或降到阈值下，且 0 FAIL。
- 自绘图页的图注含"示意图"，`source_figure` 为空，`qa_report.json` 能区分 `origin=generated`。
- `mmdc` 不可用时给出明确降级（保留文字页 + WARNING），不是静默失败。
- 至少一条回归测试：生成资产缺少 `generator` 或误带 `source_figure` → FAIL。

### 未决

- mermaid 依赖 Node 与 `@mermaid-js/mermaid-cli`，要不要进 `requirements`（还是按可选依赖 + 检测降级）？
- 中文字体在 mermaid 里的渲染（默认 sans 可能吃不到中文字体），需要 `themeVariables.fontFamily` 显式指定。
- 生成的图是否允许参与「美学/占比」评分？倾向允许，但单独打标签，避免污染论文图的统计。

---

## 任务 3：数学公式（OOXML 直写 OMML）+ 公式抽象层

### 现状

- Deck IR 的 `blocks[].text` 是纯字符串，编译器按字符宽度断行（`break_lines` → `fit_text`），
  再用 OfficeCLI 的 `add shape --prop text=...` 写进去。**没有任何公式通道**：`$...$` 会被当普通
  字符排版，`\frac` 原样出现。
- 好消息：OfficeCLI 1.0.158 已经有类型化的 `equation` 元素
  （`/slide[N]/shape[M]/oMath[K]`，`--prop formula="x^2+y^2=z^2"`，内部 `FormulaParser` 解析
  LaTeX-ish 输入；`query equation` 能把 `<m:oMath>` 树还原成 LaTeX）。所以"能显示公式"这件事
  本身不必从零写。
- 但它只覆盖解析器能吃的子集，且是"整条公式 = 一个对象"，无法表达公式内嵌在中文句子里、
  编号对齐、多行推导等真实排版需求——这正是要自己做抽象层的理由。

### 抽象层要抽象掉什么

四个可变点收进一层，编译器与提供方都只看这一层：

```text
作者/Story/RPA 写的公式源码（LaTeX 子集 / 也可直接给 AST）
        │  parse()                     ← 语法错误必须带位置，便于 Story 侧返修
        ▼
   Formula AST（frac / sup / sub / sqrt / nary / func / matrix / cases / rows / text-run）
        ├─ emit_omml()  → OMML 片段（直写路线，覆盖全量）
        ├─ emit_plain() → 纯文本退化（无 OMML 时的兜底、alt 文本、搜索）
        └─ measure()    → (width, height, baseline) px   ← 布局与门禁唯一可信来源
```

- **不抽象**的东西：几何（编译器管）、字体资源（沿用 `resolve_theme_fonts`）、门禁阈值。
- 公式节点只有一种真相（AST），三个后端（`omml` / `officecli-equation` / `plain`）都是它的投影；
  `officecli-equation` 只用于快速探针与回读比对，不作为交付路径。

### 直写 OMML 的落点（结构已用 1.0.158 探针确认）

OfficeCLI 自己在 slide XML 里写出来的是这个形状，直写必须复刻它，不能只塞 `<m:oMathPara>`：

```xml
<a:p>
  <mc:AlternateContent>
    <mc:Choice Requires="a14">
      <a14:m>
        <m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
          <m:oMath>…</m:oMath>
        </m:oMathPara>
      </a14:m>
    </mc:Choice>
    <mc:Fallback><a:r><a:rPr lang="en-US"/><a:t>x²+y²=z²</a:t></a:r></mc:Fallback>
  </mc:AlternateContent>
</a:p>
```

要点：

- `a14` 与 `mc` 声明在 `p:sld` 上并计入 `mc:Ignorable="a14"`；`xmlns:m` 由 `m:oMathPara` 自带，
  所以片段可以自包含，但**外层的 `mc:AlternateContent` + `a14:m` 不能省**。
- `mc:Fallback` 是给不认 OMML 的渲染器的纯文本版本——它同时就是抽象层 `plain()` 的落点，
  必须写成可读的 Unicode 版本（上标用 `²` 一类），否则退化读者看到的是乱码。
- 公式对象本身是普通 `p:sp`，位置尺寸由 `a:xfrm` 决定。**默认尺寸是整页级**
  （探针里 29.21cm × 7.62cm），必须显式设成测量值，否则 layout 与门禁都会按一个巨大框判断。
- 编译器新增元素 kind `math`：`officecli.py` 的 `commands()` 里对它发 `add shape`（占位、无文字）
  → `raw-set /slide[N] --xpath ... --action replace --xml <上面的片段>`；或者先用
  `add --type equation` 拿默认结构，再 `raw-set` 把 `m:oMath` 换成我们的版本。
- 写完后 `officecli validate` 必须是 0 error（探针里该结构 validate 通过）。

### 尺寸从哪来（这是最容易翻车的地方）

公式没有"字符宽度"可算，`fit_text` 那套不适用。三级策略，逐级降级并打标签：

1. **精确**：用 matplotlib 的 mathtext 解析同一份 AST，取字形轮廓外接框（离线、毫秒级、
   已验证环境里有 matplotlib）。覆盖 `\frac`、上下标、根号、求和积分、括号。
2. **半精确**：mathtext 不支持的构造（`cases`、`matrix`、多行对齐）用行高 × 列宽估算，
   记 `FORMULA_MEASURE_APPROXIMATE`（INFO）。
3. **保守兜底**：无测量依赖时按 `字符数 × 0.55em` 估宽并向上取整，记 WARNING，禁止用这种
   测量结果参与"是否放得下"的最终放行（只用于选版式）。

门禁配套：`MIN_FORMULA_HEIGHT`（不小于正文字号 1.2 倍）、`FORMULA_CAPACITY`（测量宽高必须
≤ 单位框，超出报 `SPLIT_REQUIRED` 而不是缩字号）、`FORMULA_FALLBACK_USED`（用 plain 渲染时
必须 REVIEW）。

### 与 Deck IR 的接口（先定字段，再写实现）

- 行内公式：`blocks[].text` 里用 `$...$`。IR 层做一次 tokenize，得到 `text` / `math` 两类 run。
  限制：只允许**单行段落**里的短公式（总宽 ≤ 该行剩余宽度的 60%），否则编译期报
  `SPLIT_REQUIRED`——因为编译器无法在预排断行里切开一个 OMML 对象。
- 独立公式（推荐先用这条）：新的 `blocks[].component = "formula"`，`text` 就是公式源码，
  由编译器给它一个独立单位（居中、可带编号），packer 照常给 bbox，复杂度最低。
- 公式源码需要洗白：禁止 `\input`、`\write18` 之类（虽然不解析 TeX 宏，但白名单式解析器更省心），
  只接受 AST 里定义过的构造，未知命令报 `FORMULA_UNSUPPORTED`。

### 验收标准

- 三页公式（分式+上下标、求和/积分、cases 多行）构建 0 FAIL，`validate` 0 error，
  `review-officecli --render native` 的截图里公式正确排版且不溢出（html 渲染只有 fallback 文本）。
- `parse(emit_omml(x))` 与 `parse(x)` 的 AST 等价（round-trip 测到节点级），
  且 `officecli get .../oMath` 能回读出可再解析的 LaTeX。
- 测量误差：对 10 个典型公式，`measure()` 与 OfficeCLI 渲染截图的外接框误差 ≤ 6px。
- 不支持构造走 plain 退化时，页面仍可交付（REVIEW，不 FAIL）。

### 探针结论（2026-10-21，OfficeCLI 1.0.158，临时文件）

这些是实测结果，不是推测，实现时可直接依赖：

| 问题 | 结果 |
|---|---|
| `add --type equation` 能否写入 | 能，产出 `p:sp` + `mc:AlternateContent` 结构，`validate` 通过 |
| 默认几何 | `off 720000,1080000 / ext 10515600×2743200` EMU（29.21cm×7.62cm），必须显式改尺寸 |
| 公式能否被读回 | `query equation` 返回 `text: "x^2+y^2=z^2"`（LaTeX 还原）；`get .../oMath[1]` 在 1.0.158 解析不到，按 query 走 |
| 类型化解析器的分组 | `x^2+y^2=z^2` 被拆成三个 `sSup`，底数分别是 `x` / `+y` / `=z`；观感尚可，但说明它是按 token 贪心组合，直写 OMML 才能精确控制 |
| `view screenshot --render html` | **不渲染公式**，只显示 `mc:Fallback` 的文本（截图里是 `x²+y²=z²` 的字面量） |
| `view screenshot --render native` | **正确排版**（Cambria Math 斜体，在 shape 框内居中）——本机可做公式的视觉验收，测量也能拿它当基准 |

因此验证策略定为：测量与几何用 native 截图比对；`mc:Fallback` 单独当"降级可读性"检查；
html 截图只用于检查非公式区域。

### 未决

- 公式编号（(1)(2) 右对齐）要不要做？OMML 里是 `m:oMathPara` + 制表位，先不做。
- `Cambria Math` 缺失时的替换策略：PowerPoint 一般自带；但要确认替换后测量不崩。
- 类型化解析器 vs 直写 OMML 的覆盖边界：以「mathtext 能力」为直写的下限，解析器只当快速探针。

---

## 建议顺序

1. 任务 1 先落地（改动集中在 `layout.py` + `officecli.py`，可在一页内验证，回归面小）。
2. 任务 2 需要 IR 与 schema 一起动，先把 `origin/generator` 的字段定下来，再谈生成器。
3. 任务 3 建议与任务 2 并行设计、串行实现：先只做"独立公式单位 + OMML 直写 + 精确测量"，
   行内公式留到第二迭代（它要动断行器，风险最高）。
4. 三条都完成后，再回头统一跑一次 `tools/layout_quality_report.py` 与人工逐页复核，更新基线数字。
