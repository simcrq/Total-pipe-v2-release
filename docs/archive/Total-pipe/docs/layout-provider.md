> **历史归档，非当前操作指引。** 2026-10-25 整理；原路径：`Total-pipe/docs/layout-provider.md`。
> 文中的版本、命令、测试数量和完成状态仅代表当时记录。当前入口见[仓库 README](../../../../README.md)和[文档索引](../../../README.md)。

# 布局提供方接口（layout provider）

Deck Compiler 只负责三件事：校验 canonical 内容、绘制页面框架、写出 PPTX。
**正文几何**可以由外部提供方提出，这就是模型接口保留的位置。

> 2026-10-21 起，项目内的扩散模型（`layoutdiffusion_demo/`、`totalpipe_layout/model.py`、
> `models/*.pt`、`torch` 依赖）已**完全移除**。移除后交付质量没有下降：默认提供方改成了
> 内置确定性打包器 `packer`，它比编译器自带模板更贴合内容（见文末实测）。

## 三种提供方

| 名称 | 行为 | 用途 |
|---|---|---|
| `packer`（默认） | 内置确定性打包器：12 列网格、按内容高度收框、同行齐高、图框按图片宽高比定形 | 生产交付 |
| `compiler` | 不提供任何建议，全部页面交给编译器自带模板 | 对照基线 / 排障 |
| `module:factory` 或 `path/to/file.py:factory` | 外部提供方，工厂函数返回带 `propose(requests)` 的对象 | 新模型、规则引擎、远程服务 |

选择方式（优先级从高到低）：

```bash
--layout-provider packer          # 命令行
--layout-provider compiler
--layout-provider my_pkg.my_provider:make_provider
export TOTALPIPE_LAYOUT_PROVIDER=my_pkg.my_provider:make_provider   # 环境变量兜底
```

## 契约

```python
class LayoutProvider(Protocol):
    name: str
    def propose(self, requests: list[dict]) -> dict:
        """{slide_id: {"units": {unit_id: {"bbox": [x, y, w, h]}}}}"""
```

* `requests` 由 `totalpipe_layout.contracts.read_requests` 生成，每页含 `units`（`id/role/text/
  label/aspect/caption/...`）、`region`（正文区 `[x, y, w, h]`，CSS 像素）、字体路径与页面框架。
* 返回的每个 `bbox` 是**该单元整块**的矩形；图片单元的矩形包含图注条（编译器在其中等比放置图片，
  图注画在下方 12 px 处）。
* 内容不可改：单元 id 必须与页面完全一致，多一个少一个都会被拒绝（`REJECTED_UNIT_MISMATCH`）。
* 提供方**不能**绕过门禁：提案先过 `totalpipe_layout.contracts.check`（越界、容量、重叠、图文间距、
  字号线、孤行、阅读顺序……），任何一条不过该页即被记为 `REJECTED_GATES`。
* 提供方抛异常不会中断构建：记 `LAYOUT_PROVIDER_FAILED` WARNING，所有页面回退编译器模板。
* 编译器自身报 FAIL 的页面，会摘掉提案后用模板重编，剩余 FAIL 仍然可见（不吞错）。

## 逐页溯源

构建产物里 `layout_provider.json` 记录每页状态：

```json
{"name": "packer", "kind": "PackerProvider",
 "slides": [{"slide_id": "s04-k1-onset", "status": "PACKED", "request_sha256": "..."}],
 "counts": {"packed": 9, "fallback": 0, "rejected": 0},
 "source_sha256": {"deck_compiler/layout_provider.py": "...", "totalpipe_layout/contracts.py": "..."}}
```

`status` 取值：`PACKED`、`COMPILER_FALLBACK`、`REJECTED_GATES`、`REJECTED_UNIT_MISMATCH`。

## 写一个外部提供方

```python
# my_provider.py
from totalpipe_layout.contracts import teacher   # 复用内置打包器

class MyProvider:
    name = "my-provider"
    source_files = [__file__]        # 可选：进入 source_sha256
    def propose(self, requests):
        return {request["slide_id"]: {
            "units": {unit["id"]: {"bbox": box}
                      for unit, box in zip(request["units"], teacher(request))},
            "status": "PACKED"} for request in requests
        }

def make():
    return MyProvider()
```

```bash
python -m deck_compiler compile --ir deck_ir.json --out build/ \
    --layout-provider ./my_provider.py:make
```

一个未来的扩散模型只要在 `propose` 里返回同样的字典即可接回来，不需要接触编译器、写入器或门禁。

## 实测：为什么默认是 packer

同一份含两张图的夹具（1.8:1 面板 + 4:1 长条），同一套门禁：

| 提供方 | 文本框冗余（框高÷所需） | 图框空洞 | 编译 FAIL |
|---|---|---|---|
| `packer` | 均值 **1.19**，最大 1.23 | 0.044 / 0.047 | **0** |
| `compiler` 模板 | 均值 **2.84**，最大 3.97 | 0.038 / 0.067 | 1（`SCIENTIFIC_PANEL_TOO_SMALL`） |

文本框冗余 1.19 表示"框只比文字高 19%"，2.84 表示"框里有近三分之二是空的"——这正是人评反复指出的
"文本框面积大、字少"。复算脚本：`python tools/layout_quality_report.py --build <out> --ir <ir>`。

## 与模型一起消失的东西

| 已删除 | 原因 |
|---|---|
| `layoutdiffusion_demo/` | 扩散模型实现（去噪器、配置、采样） |
| `totalpipe_layout/model.py` | 模型外壳（`ContentDenoiser`、`sample`） |
| `totalpipe_layout/data.py` | 只服务于 64 bin token 的张量编码 |
| `models/totalpipe_content_v26.pt` | 训练权重（8 MB） |
| `torch` 依赖、`--layout-checkpoint/-candidates/-seed` | 推理与采样参数 |
| `--layout-provider v26` | 传该名字会明确报错并指向本文件 |

保留：`totalpipe_layout/contracts.py` 的请求构造、门禁、打包器与质量评分——它们本来就不依赖模型。
