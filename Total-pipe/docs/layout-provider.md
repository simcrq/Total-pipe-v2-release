# 布局提供方接口（layout provider）

Deck Compiler 校验 canonical 内容、决定最终几何、测量容量并生成后端对象。
布局提供方可为受支持的平面正文提出整块矩形建议；编译器验证建议后交给 OfficeCLI 写入 PPTX。
递归区域、视觉设计和数学等需要专门测量的页面由编译器布局，覆盖边界如下。

## 三种提供方

| 名称 | 行为 | 用途 |
|---|---|---|
| `packer`（默认） | 为受支持页面提供确定性建议：12 列网格、按内容高度收框、同行齐高、图框按图片宽高比定形 | 默认正文建议 |
| `compiler` | 显式关闭外部建议，全部页面由编译器布局 | 对照基线 / 排障 |
| `module:factory` 或 `path/to/file.py:factory` | 外部提供方，工厂函数返回带 `propose(requests)` 的对象 | 新模型、规则引擎、远程服务 |

选择方式（优先级从高到低）：

```bash
--layout-provider packer          # 命令行
--layout-provider compiler
--layout-provider my_pkg.my_provider:make_provider
export TOTALPIPE_LAYOUT_PROVIDER=my_pkg.my_provider:make_provider   # 环境变量兜底
```

## 覆盖边界

以下页面不送给 `propose()`，逐页状态为 `COMPILER_OWNED`。条件同时命中时按表中顺序记录首个原因。

| 条件 | reason |
| --- | --- |
| `composition.layout_tree` | `recursive_regions` |
| `presentation.visual_plan` | `scientific_visual_plan` |
| block 含独立公式或启用 `inline_math` | `measured_formula_flow` |
| block 显式请求 `distributed_arrow_list` | `measured_native_list` |
| 正文中混排 `graphics` | `native_graphic_composition` |
| `native-graphic` 独立图形页 | `graphic_page` |
| 没有 block / figure 单元 | `no_units` |

选择 `compiler` 时，其余页面也标为 `COMPILER_OWNED`，原因是 `provider_disabled`。
整套页面均由编译器布局是正常结果；现代复杂 Deck IR 不要求经过旧式整块矩形建议接口。
树页目前没有 provider 权重或 gap 建议接口；应由 RPA / Design 修改 canonical 结构后重新编译。

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
* 正常情况批量调用一次。批量抛异常时记 `LAYOUT_PROVIDER_BATCH_RETRY` WARNING，改为逐页请求；
  只有仍抛异常的页记 `LAYOUT_PROVIDER_FAILED` WARNING 并回退。其它页继续验证自己的建议。
  没有可请求页面时不调用提供方。
* 编译器自身报 FAIL 的页面，会摘掉提案后用模板重编，剩余 FAIL 仍然可见（不吞错）。
* 请求构造复用本次 baseline；没有可接受提案时直接沿用 baseline，不为相同 IR 重复编译。
  独立调用 `read_requests(path, root)` 仍会自行编译；已有结果可传 `layout=` 和 `compile_issues=`，
  baseline 的 `ir_sha256` 必须匹配当前 IR。

## 逐页溯源

构建产物里 `layout_provider.json` 记录每页状态：

```json
{"name": "packer", "kind": "PackerProvider",
 "slides": [{"slide_id": "s04-k1-onset", "status": "PACKED", "request_sha256": "..."}],
 "counts": {"packed": 2, "owned": 7, "fallback": 0, "rejected": 0, "coverage": 1.0},
 "source_sha256": {"deck_compiler/layout_provider.py": "...", "totalpipe_layout/contracts.py": "..."}}
```

| status | 含义 |
| --- | --- |
| `PACKED` | 提案通过门禁，编译器采用了建议 |
| `COMPILER_OWNED` | 未请求提供方；`reason` 见覆盖边界 |
| `COMPILER_FALLBACK` | 已请求但无提案（`no_proposal`）、提供方异常（`provider_error`）或编译复核拒绝（`compiler_rejected`） |
| `REJECTED_GATES` | 提案的格式或几何不合法，附 `violations` |
| `REJECTED_UNIT_MISMATCH` | 提案单元 ID 与原文不一致 |

`packed + owned + fallback + rejected` 等于总页数。`coverage = packed / (总页数 - owned)`
表示可请求页面中最终采用提案的比例；分母为零时是 `null`，不表示提供方失败。
例如全为递归区域的九页 deck 应报告 `packed: 0, owned: 9, fallback: 0, rejected: 0, coverage: null`。

## 写一个外部提供方

```python
# my_provider.py
from totalpipe_layout.contracts import teacher   # 复用内置打包器

class MyProvider:
    name = "my-provider"
    source_files = [__file__]        # 可选：进入 source_sha256
    def propose(self, requests):
        proposals = {}
        for request in requests:
            boxes = teacher(request)
            if boxes is not None:
                proposals[request["slide_id"]] = {
                    "units": {unit["id"]: {"bbox": box}
                              for unit, box in zip(request["units"], boxes)}}
        return proposals

def make():
    return MyProvider()
```

```bash
python -m deck_compiler compile --ir deck_ir.json --out build/ \
    --layout-provider ./my_provider.py:make
```

一个未来的扩散模型只要在 `propose` 里返回同样的字典即可接回来，不需要接触编译器、写入器或门禁。

旧 `v26` 扩散提供方已移除，指定该名称会明确报错。早期删除清单和单一夹具的性能比较保留在
[历史快照](../../docs/archive/Total-pipe/docs/layout-provider.md)，不能作为当前交付质量承诺。
