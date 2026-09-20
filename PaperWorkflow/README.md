# PaperWorkflow

PaperWorkflow 是一个面向科研文献的本地批处理接入层：把 PDF 解析成可检索的 Markdown，按任务 ID 选择略读/精读模板，调用 OpenAI-compatible 模型生成报告，并将证据区块 manifest 与报告一起落盘。

它不替代通用 Agent：PaperWorkflow 负责确定性的文件解析、缓存、批量执行和证据定位；Agent 负责决定读什么、比较什么、何时调用工具。当前 WSL2 部署已经提供 DeepSeek Harness 原生 bundle 插件。

完整的 WSL 使用、安装、更新和排错流程见：[DeepSeek-Harness 对接与使用](DeepSeek-Harness对接与使用.md)。

## WSL2 快速开始

在 WSL Bash 中执行：

~~~bash
cd /home/simcrq/0_Project/paperworkflow

# 先把 iconfig.yaml 复制为 config.yaml 并按需修改
cp -n iconfig.yaml config.yaml

# 先检查论文路径和任务模式
python3 main.py --dry-run

# 执行完整工作流
python3 main.py
~~~

PDF 应放在 `INput/<任务ID>/`，例如 `INput/4668/paper-a.pdf`。任务 ID 决定使用 `deep_read`、`skim` 或默认模式。

## DeepSeek Harness 插件

插件源码位于：

~~~text
integrations/deepseek-harness/
~~~

它安装到 WSL 的 `web` profile 后暴露两个模型工具：

- `paperworkflow_literature_workflow`：以项目内 PDF 或 Markdown 为入口，完成整套可追溯文献处理和下游交接。
- `paperworkflow_prompt_builder`：递归索引 `INput` 下的全部 PDF，使用相对路径供用户选择，并根据研究信息自动生成主工作流提示词。

工具内部按顺序完成：

1. PDF 使用 MinerU OCR/转 Markdown，Markdown 输入则跳过 OCR。
2. 提取标题、DOI、arXiv 标识、语言和章节覆盖情况。
3. 将文本捕获质量、阅读顺序、语义标题、chunk coherence、检索精度/覆盖率、补充材料依赖和数值/符号一致性分别审计。
4. 只发现文件名或目录关系明确的补充材料，避免把同目录无关论文误判为关联文献。
5. 保留 `E###` 粗粒度 chunk，同时建立带字符偏移的 `S####` 原子 span；检索命中后注册成去重的 `EV####` 证据。
6. 输出带硬门禁的 `synthesis_readiness`；阅读顺序、证据暴露、覆盖率或补充材料缺失不能被加权总分掩盖。
7. 写出 `workflow.json`、`document.manifest.json` 和 `evidence.md`，供其他插件继续处理。

安装并启动：

~~~bash
source ~/.nvm/nvm.sh
export DSH_HOME=~/.dsh
cd “你的dsh安装目录”

pnpm dsh plugin --profile web add "paperwork目录"/integrations/deepseek-harness
pnpm dsh web
~~~

不知道文件名时，先让 Agent 调用提示词工具：

~~~text
请调用 paperworkflow_prompt_builder 列出输入目录中的全部 PDF。
~~~

工具只返回 `INput` 相对路径和 `P001` 形式的编号。选择后继续输入：

~~~text
选择 P004。研究目标是解释结构色的制备与物理机制，
重点回答样品制备、物理图像、关键结果和局限性。请自动生成工作流提示词。
~~~

然后打开 [http://127.0.0.1:3080](http://127.0.0.1:3080)，直接要求 Agent 调用统一工具：

~~~text
请调用 paperworkflow_literature_workflow 处理
"你的paperwork目录"/INput/4668/paper-a.pdf，
并围绕“样品制备、测量条件、关键结果和局限性”建立证据包。
~~~

## MinerU 后端

`official_cli` 是默认推荐模式，调用 MinerU 官方 CLI，由官方工具负责鉴权、上传、任务轮询、下载和输出格式：

~~~bash
curl --compressed -fsSL https://cdn-mineru.openxlab.org.cn/open-api-cli/install.sh -o /tmp/mineru-open-api-install.sh
INSTALL_DIR=/home/simcrq/.local/bin sh /tmp/mineru-open-api-install.sh
mineru-open-api auth
# 当前 WSL 配置 api.mineru.ocr=true，插件会向官方 CLI 传递 --ocr。
~~~

历史 `mode: api` 配置会自动迁移到官方 CLI；只有同时设置 `legacy_http: true` 时才启用旧的手写 HTTP 适配器。

## 输出与 Agent 接口

统一工具会为每个源文件生成：

- `temp_markdowns/<cache>/.../full.md`：MinerU 原始 Markdown，Markdown 输入时直接复用源文件。
- `output/workflows/<source fingerprint>/workflow.json`：阶段状态、分维度审计、query→EV 映射、去重 Evidence Registry、来源依赖、门禁和下游交接路径。
- 同目录 `document.manifest.json`：保留原始 `E###` chunk，并提供 `S####` 原子科学句段、模态、语义父标题、行号和字符偏移。
- 同目录 `evidence.md`：查询区只列 EV 编号；证据正文只在 Evidence Registry 出现一次，供其他插件优先读取。

`E###` 只用于粗粒度回看，科学主张应优先引用 `EV####`，同时保留其 `S####`、原始行范围和字符偏移。伪标题（例如版式 `Article`）不会再覆盖语义父级；图注会携带 `parent_figure`。

`quality_audit` 为兼容字段，只表示 OCR/Markdown 提取质量；科学综合前应检查 `synthesis_readiness` 和 `quality_dimensions`。只要后两者为 `review` 或 `blocked`，下游模型就必须明确提示复核。

传统批处理入口仍可生成 `Summary_<mode>_<filename>.md` 及同名 manifest。旧的 outline/search Python 包装也继续保留兼容性。

Python 中可以直接调用同一套确定性工具：

~~~python
from utils.agent_tools import get_document_outline, retrieve_evidence

outline = get_document_outline("temp_markdowns/<cache>/paper/full.md")
hits = retrieve_evidence(
    "temp_markdowns/<cache>/paper/full.md",
    query="实验温度、样品制备和测量方法",
    top_k=5,
)
~~~

Agent 应优先使用 manifest 或检索工具返回的证据块，不要把旧的总结文件当作唯一事实来源。

## 配置要点

- `paths.input_dir`：论文根目录；PDF 应位于任务 ID 子目录。
- `paths.output_dir`：输出目录；为空时写回 PDF 同级目录。
- `processing_rules.max_prompt_chars`：提示词预算。
- `processing_rules.chunk_chars`：证据块大小。
- `processing_rules.is_merger_md`：是否合并本次报告。

Python 工作流需要调用 DeepSeek API 时，在同一个 WSL Bash 终端设置：

~~~bash
export DEEPSEEK_API_KEY='你的 DeepSeek API Key'
export OPENAI_API_KEY="$DEEPSEEK_API_KEY"
~~~

不要把真实 Key 写入配置、Markdown 或 Git。项目级完整说明见 [DeepSeek-Harness 对接与使用](DeepSeek-Harness对接与使用.md)。
