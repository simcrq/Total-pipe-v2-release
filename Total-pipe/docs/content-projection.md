# 原子科学记录与观众表达契约

新任务使用 Story `content_contract.version=2.0`、页面设计`schema_version=1.3`。
叙事段落、科学断言、页面出现和原生对象是不同的东西；系统不再把整段 answer/limitation 当作条件绑定原子。
旧段落契约1.0/页面设计1.2及更早1.0/1.1按原版本恢复，不自动迁移或降级。实现不调用隐藏模型，不自动签收审读。

## 权限与不变量

| 阶段 | 科学与表达职责 | 验收 |
|---|---|---|
| Story独立子代理 | 论证顺序、原子科学记录、精确EV、观察/解释/推断身份、条件范围 | 完整Schema、来源、用户授权的真实委派 |
| scientific_review | 主Agent对照原文/实际SI审读科学单元、必要条件及遗漏 | 当前Story/workflow哈希、逐主题覆盖所有单元，失败回退Story |
| page_design独立子代理 | 观众文案、选图、自绘、关系、构图与讲解顺序 | 唯一所有权、明确复用、直接条件、来源/数字及具体可见载体 |
| page_review | 主Agent审读实际投屏文案与科学记录的关系 | 忠实性、条件范围、观众语言；不复用设计者自评 |
| IR / Compiler | 实现批准表达、绑定完整档案与来源、测量空间 | 实际可见对象、科学记录、图注/来源、原有字号和几何门禁 |

完整保留意味着记录和证据可追溯，必要信息在相关页面可见。不能靠缩字号、缩写、删条件或仅把内容存入notes通过。

## 原子科学记录（Story 2.0）

完整Schema见[Story Schema](../pwf2rpa/schemas/story-plan.schema.json)。以下是字段片段：

```json
{"content_contract":{"version":"2.0","units":{
  "C_detector":{"text":"作者报告响应度1.11 mA/W。","evidence":["EV0004"],"epistemic":"author_claim","kind":"claim","visibility":"required"},
  "C_oracle":{"text":"Oracle-MNIST准确率为98.58%。","evidence":["EV0005"],"epistemic":"author_claim","kind":"claim","visibility":"required"},
  "Q_oracle":{"text":"该任务按8:2划分训练和测试。","evidence":["EV0006"],"epistemic":"observation","kind":"condition","visibility":"with_claim","applies_to":["C_oracle"]}},
  "narrative_map":{"S3.answer":["C_detector","C_oracle","Q_oracle"]}}}
```

科学权威是`units`。`answer/key_points/ending`负责论证的组织，`narrative_map`恰好覆盖其全部现存路径，
每条unit至少被一个叙事路径引用。叙事可以合述多个断言，条件仍只绑定具体断言ID，不能绑定S3.answer。
每条unit的EV也必须被引用它的节点显式列出，不默认继承整篇证据。

unit必含`text/evidence/kind/visibility/epistemic`。一个断言应可被独立限定；不同任务、指标、观察、机制、条件和边界分别记录。
`epistemic`是author_claim、observation、author_interpretation或agent_inference；推断仍需真实依据，不能伪装作者结论。
这种科学身份进入投影快照和完整讲稿。程序不凭句子长短或关键词判断科学原子性、因果强度或完整性。

- `required`：需要可见文案或证据载体。claim必须required。
- `with_claim`：`applies_to`只能引用具体required单元，不能引用另一个限定；禁止条件级联。当所限定断言在页面可见时，本限定须同页可见。
- `notes_allowed`：仅detail/scope且给出科学相关性reason；不能隐藏关键条件、对照、负面结果或不确定性。

稳定unit ID是事实身份。再次概述同一断言时复用原ID，不能复制成另一条来摆脱限定。
概括性的结尾可以只讲两类功能，已解释的具体准确率不必再出现；若再报98.58%，对应任务条件必须一起出现。

## 科学源审读（scientific_review）

新原子Story提交后、RPA和页面设计之前，主Agent按next_action完整读取任务、提示和
[scientific review Schema](../agent/schemas/scientific-review.schema.json)，实际查看正文、关键图和真正提供的SI。

`scientific_review.json`绑定当前Story及workflow SHA-256。`decisions`可按真实科学主题分组，但每个unit须恰好被审读一次，
逐组检查evidence_fidelity、atomic_scope、essential_conditions并给具体note。全局`coverage`还须审查原文中没有进入ledger的重要条件、
初始化/预置、对照、负面结果、替代解释和来源矛盾；不能仅扫描已有unit。

任何科学失败返回`SCIENTIFIC_REVIEW_REJECTED`并回退Story，阻止提前调用页面设计。
缺项/过期表单仅修复审读记录。没有自动pass，没有把规划者自评当实际源审读；结构程序不证明语义正确。
此记录不代表渲染或PowerPoint验收。

## 页面设计1.3：所有权和再次出现分开

完整Schema见[page design 1.3](../schemas/page-design-v1.3.schema.json)。设计者从论文、听众和证据出发，
不读取编译器形式清单。

| 字段 | 含义 |
|---|---|
| content_refs | 本页负责的科学单元；全套每个unit恰好拥有一次 |
| reuse_refs | 本页真正再次展示的、由另一页拥有的required断言；必须可见，不能写完不展示 |
| display_copy | 实际标题、结论、正文、图中标签、图注；id/role/text/source_refs |
| content_map | 每条拥有/复用记录和本页活跃直接限定的去向，visible带具体carriers，允许notes的记录给reason |
| figures / figure_sources | 实际查看的精确资产ID，以及对应真实source_figure身份 |
| design | 自由文字或对象：claim、锚点、自绘元素、关系、层级、构图与讲解指向 |
| production_notes | 制作记录，进入run_notes而不进入投屏 |

只展示C_detector的页不继承Q_oracle；重述C_oracle的页即使不是其所有者，也必须列reuse_refs并显示Q_oracle。
原单元仍仅拥有一次，允许必要条件重复展示。程序拒绝多重所有权、未声明的复述和仅存notes的活跃条件。
`content_map`的copy引用display_copy ID；figure引用精确选图；formula/table/chart/graphic引用实际对象并给阅读locator。

`display_copy.role`为title/takeaway/body/label/caption，每页一个title和takeaway。可以忠实改写和图示化，不能改变意义、比较对象、
单位、误差和确定性。paper文案引用科学单元；organization无论文引用和科学数字，只能组织报告；supplement沿用basis/source/constructed协议，
构造示例须可见标识。实际SI事实仍走paper通道，不能冒充背景补充。

## 图号、数值与原生图注

图号是来源身份，700 nm等是实验数值。1.3分别核查：显式Fig/Figure/图、Table/表、Note编号必须有引用或实际选图依据；
裸S11只在引用/选图上下文确立其身份时才按来源处理，任意S999不豁免。科学数值仍对精确EV检查，正负条件不混同。
图源元数据只记录真实source_figure，不允许塞入未经批准的实验条件。

`figure_sources`形如`{"<asset_id>":{"source_figure":"S17a"}}`，恰好覆盖所选图。绑定器写入source_figure和可见来源标签，
不改批准caption文字。caption已经写明同一图号时，来源前缀用“本文”；否则用“本文 Fig. S17a”。
所以图号在页面可见，也不会为了数值检查而删除或重复。图号是否确实对应实际原图仍须实际源文案审读。

IR新增原生图注块：

```json
{"id":"mechanism_caption","component":"caption","text":{"copy_ref":"mechanism_note"},
 "caption_for":{"kind":"graphic","ref":"mechanism"}}
```

`caption_for`须指向本页存在的figure/graphic/table/chart。图注用既有图注字号和真实测量路径，成为可编辑原生文本；
不再当作body计量。它不能带正文标题、公式、列表或使用图注角色缩小批准的body文案；实际copy角色与对象仍严格一致。
论文图自带的caption仍由figure_refs实现。

## 页面源文案审读与IR绑定

接受设计后按原page_review检查scientific_fidelity、qualifier_scope、audience_copy。主Agent只读投屏文案，核对观众能否理解对象、做法、
证据和论点，避免制作指令/核查过程泄漏。提交[page review Schema](../agent/schemas/page-design-review.schema.json)要求的当前哈希与20页具体记录，
不能自动填pass或复用设计者自评。改文案/内容去向须重审。

IR可用`{"copy_ref":"id"}`实现批准文字。程序绑定科学单元、直接限定、复用主张、来源清单和两次实际审读的哈希，
把完整记录连同epistemic身份写入讲稿。1.3的`semantic.content_projection.version=2.0`；旧1.2投影保持1.0。
编译器分别核对完整档案、批准文字、原生caption角色、来源身份和实际编译对象；notes或投影元数据不满足可见覆盖。
缺少原图、图形、科学条件或图注会失败，视觉含义仍保留实际复核要求。

IR阶段可选页preflight/preview并实际看PNG后改源IR；预览不接受IR、不消耗修订、不替代完整Design、整套构建或PowerPoint原生验收。
字体、原图比例、来源、科学数值、Supplement泄漏、几何及原生验收门禁均未放宽。0个机器FAIL不等于人工视觉通过。

## 兼容与部署

版本由当前提示约束：新提示要求2.0，不能提交旧1.0契约或把设计降为1.2来绕过新关口。
旧提示/Story仍使用旧语义，旧1.0/1.1设计可恢复；升级需要真实重新规划和审读，不能复用旧调用记录冒充新调用。
此开发分支不会自动替换已运行MCP；切换后需重载服务，或明确从更新worktree使用CLI。代码指纹变化会按原规则失效下游checkpoint。
