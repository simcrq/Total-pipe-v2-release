# PaperWorkflow

PaperWorkflow 是 Total-pipe 的论文接入层：把任意本地 PDF 或 Markdown 整理成 schema v4 的证据包，并把 OCR Markdown、图片资产、`workflow.json`、`document.manifest.json`、`evidence.md` 与校验清单自动放进同一个 bundle 目录。`workflow.json` 可直接交给 `Total-pipe/pwf2rpa`。

它不替代通用 Agent：PaperWorkflow 负责确定性的文件解析、缓存、批量执行和证据定位；Agent 负责决定读什么、比较什么、何时调用工具。当前 WSL2 部署已经提供 DeepSeek Harness 原生 bundle 插件。

完整的 WSL 使用、安装、更新和排错流程见：[DeepSeek-Harness 对接与使用](DeepSeek-Harness对接与使用.md)。

## MCP 快速开始

启动标准 stdio MCP server：

~~~bash
python3 PaperWorkflow/mcp_server.py
~~~

MCP 客户端配置示例：

~~~json
{
  "mcpServers": {
    "paperworkflow": {
      "command": "python3",
      "args": ["PaperWorkflow/mcp_server.py"]
    }
  }
}
~~~

`paperworkflow_literature_workflow` 的 `source_path` 和 `output_dir` 均可使用任意本地绝对路径，不再要求文件位于 `INput` 或 PaperWorkflow 项目目录内。省略 `output_dir` 时，默认写入 `output/workflows/<source fingerprint>/`。成功返回值顶层直接包含 `bundle_dir` 与 `workflow_path`，无需猜测目录；默认不把完整 workflow 塞进 MCP 响应，如确有需要可设置 `include_workflow=true`。

如果需要先浏览一个目录内的论文，可调用 `paperworkflow_prompt_builder` 并传 `source_dir`；省略时仍兼容旧的 `INput` 目录。

## 传统批处理快速开始

在 WSL Bash 中执行：

~~~bash
cd PaperWorkflow

# 先把 iconfig.yaml 复制为 config.yaml 并按需修改
cp -n iconfig.yaml config.yaml

# 先检查论文路径和任务模式
python3 main.py --dry-run

# 执行完整工作流
python3 main.py
~~~

传统 `main.py` 批处理仍从配置的 `paths.input_dir` 读取任务目录；这个限制只属于旧批处理模式，不适用于 MCP 工具。

## DeepSeek Harness 插件

插件源码位于：

~~~text
integrations/deepseek-harness/
~~~

它安装到 WSL 的 `web` profile 后暴露两个模型工具：

- `paperworkflow_literature_workflow`：以任意本地 PDF 或 Markdown 为入口，完成整套可追溯文献处理和下游交接。
- `paperworkflow_prompt_builder`：递归索引任意 `source_dir` 下的 PDF，使用相对路径供用户选择，并根据研究信息自动生成主工作流提示词。

工具内部按顺序完成：

1. PDF 使用 MinerU OCR/转 Markdown，Markdown 输入则跳过 OCR。
2. 提取标题、DOI、arXiv 标识、语言和章节覆盖情况。
3. 将文本捕获质量、阅读顺序、语义标题、chunk coherence、检索精度/覆盖率、补充材料依赖和数值/符号一致性分别审计。
4. 只发现文件名或目录关系明确的补充材料，避免把同目录无关论文误判为关联文献。
5. 保留 `E###` 粗粒度 chunk，同时建立带字符偏移的 `S####` 原子 span；检索命中后注册成去重的 `EV####` 证据。
6. 输出带硬门禁的 `synthesis_readiness`；阅读顺序、证据暴露、覆盖率或补充材料缺失不能被加权总分掩盖。
7. 自动生成一个 Total-pipe bundle，写出 `workflow.json`、`document.manifest.json`、`evidence.md`、`paper.md`、图片资产与 `bundle.manifest.json`。

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
INSTALL_DIR="$HOME/.local/bin" sh /tmp/mineru-open-api-install.sh
mineru-open-api auth
# 当前 WSL 配置 api.mineru.ocr=true，插件会向官方 CLI 传递 --ocr。
~~~

历史 `mode: api` 配置会自动迁移到官方 CLI；只有同时设置 `legacy_http: true` 时才启用旧的手写 HTTP 适配器。

## 输出与 Total-pipe 接口

统一工具会为每个源文件生成一个目录：

~~~text
output/workflows/<source fingerprint>/
├── workflow.json             # schema v4；pwf2rpa 入口
├── document.manifest.json    # E### chunk + S#### 原子 span
├── evidence.md               # 去重后的 EV#### 证据包
├── paper.md                  # OCR 后或原始 Markdown 的 bundle 副本
├── images/                   # MinerU 提取图片，保留 Markdown 相对引用
└── bundle.manifest.json      # Total-pipe 契约、角色、大小与逐文件 sha256
~~~

若 MinerU 使用 `figures/`、`assets/`、`media/` 等目录名，也会原样收集。发布文件中的路径全部相对于 bundle：`workflow.json.artifacts.bundle_relative_paths` 给出稳定入口，`artifacts.total_pipe_bundle_dir` 和 `bundle.manifest.json.bundle_dir` 均为 `.`。本机绝对路径只出现在 MCP 调用响应的 `bundle_dir` 与 `workflow_path`，不会写入产物。

交给下一阶段时直接使用返回的 `workflow_path`：

~~~bash
cd ../Total-pipe/pwf2rpa
PYTHONPATH=. python3 -m pwf2rpa /path/to/bundle/workflow.json \
  --story /path/to/story_plan.json \
  --story-model '<用户选择的模型>' --story-reasoning high \
  --model-selected-by-user --strict --out /path/to/rpa_input.json
~~~

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
