#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
archive_pipeline.py — 将 PaperWorkflow 产物归档为可移植的 rpa-pipe 包。

归档内容（来源于 workflow.json，路径不硬编码）：
  1. MinerU OCR 后的 Markdown（source.markdown_path）
  2. 证据包 evidence.md（artifacts.evidence_report_path）
  3. document.manifest.json（artifacts.document_manifest_path）
  4. Markdown 同级的 images/ 目录（MinerU 提取的全部插图）
  5. 可选：科学综合报告（--report，可多次传入）

目标结构（默认 <项目根>/rpa-pipe/<name>/）：
  rpa-pipe/<name>/
  ├── <stem>.md                # OCR Markdown（保持原名）
  ├── evidence.md
  ├── document.manifest.json
  ├── images/                  # 相对引用与 Markdown 保持一致
  ├── <report 原名>.md         # 综合报告（若提供）
  └── archive.manifest.json    # 归档清单（含每个文件的 sha256）

可迁移性设计：
  * 仅使用 Python 标准库（argparse/json/shutil/hashlib/pathlib），
    不依赖 venv 或第三方包，Python 3.8+ 即可运行。
  * 项目根由脚本自身位置推导（Path(__file__).resolve().parent.parent），
    无任何硬编码绝对路径；workflow 目录与输出根均可用相对路径。
  * 复制后逐文件校验 sha256，失败即退出非零。
  * 默认不覆盖已有归档（--force 覆盖），支持 --dry-run 预演。

用法：
  python3 scripts/archive_pipeline.py output/workflows/<fingerprint> \
      [--name <子目录名>] [--report <综合报告路径>]... \
      [--out-root rpa-pipe] [--force] [--dry-run] [--no-images]
"""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ARCHIVE_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_workflow(workflow_dir: Path) -> dict:
    wf = workflow_dir / "workflow.json"
    if not wf.is_file():
        sys.exit(f"[错误] 未找到 {wf}；请传入包含 workflow.json 的工作流输出目录")
    return json.loads(wf.read_text(encoding="utf-8"))


def _get(data: dict, *keys, default=None):
    cur = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def resolve_path(workflow: dict, *keys, default=None) -> Path | None:
    raw = _get(workflow, *keys, default=default)
    if not raw:
        return None
    p = Path(str(raw))
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def collect_files(workflow: dict, report_paths: list[Path], no_images: bool):
    """返回 (文件清单[(源路径, 目标相对路径)], 源 PDF 名, workflow_id, markdown 父目录)。"""
    markdown = resolve_path(workflow, "source", "markdown_path")
    evidence = resolve_path(workflow, "artifacts", "evidence_report_path")
    doc_manifest = resolve_path(workflow, "artifacts", "document_manifest_path")
    source_pdf = resolve_path(workflow, "source", "input_path")

    missing = [p for p in (markdown, evidence, doc_manifest) if p is None or not p.is_file()]
    if missing:
        sys.exit(f"[错误] workflow.json 引用的产物缺失: {[str(p) for p in missing]}")

    files: list[tuple[Path, str]] = [
        (markdown, markdown.name),
        (evidence, evidence.name),
        (doc_manifest, doc_manifest.name),
    ]

    images_src = markdown.parent / "images"
    if no_images:
        if images_src.is_dir():
            print(f"[提示] --no-images：跳过 images/（{len(list(images_src.iterdir()))} 个文件）")
    elif images_src.is_dir():
        for img in sorted(images_src.iterdir()):
            if img.is_file():
                files.append((img, f"images/{img.name}"))
    else:
        print(f"[警告] 未找到 images/ 目录: {images_src}")

    for r in report_paths:
        if not r.is_file():
            sys.exit(f"[错误] 综合报告不存在: {r}")
        files.append((r, r.name))

    pdf_name = source_pdf.name if source_pdf else "unknown"
    return files, pdf_name, _get(workflow, "workflow_id", default="unknown"), markdown.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="归档 PaperWorkflow 工作流产物为可移植的 rpa-pipe 包",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("workflow_dir", help="工作流输出目录（含 workflow.json），可为相对路径")
    ap.add_argument("--name", help="归档子目录名（默认取源 PDF 文件名去扩展名）")
    ap.add_argument("--report", action="append", default=[], metavar="PATH",
                    help="附加的综合报告路径（可多次传入）")
    ap.add_argument("--out-root", default="rpa-pipe", help="归档根目录（相对项目根或绝对路径）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的归档目录")
    ap.add_argument("--dry-run", action="store_true", help="仅列出将复制的文件，不执行复制")
    ap.add_argument("--no-images", action="store_true", help="不复制 images/ 目录")
    args = ap.parse_args(argv)

    workflow_dir = Path(args.workflow_dir)
    workflow_dir = workflow_dir if workflow_dir.is_absolute() else (PROJECT_ROOT / workflow_dir)
    workflow = load_workflow(workflow_dir)

    report_paths = []
    for r in args.report:
        p = Path(r)
        report_paths.append(p if p.is_absolute() else (PROJECT_ROOT / p))

    files, pdf_name, workflow_id, _ = collect_files(workflow, report_paths, args.no_images)

    out_root = Path(args.out_root)
    out_root = out_root if out_root.is_absolute() else (PROJECT_ROOT / out_root)
    name = args.name or Path(pdf_name).stem
    out_dir = out_root / name
    if out_dir.resolve() == workflow_dir.resolve():
        sys.exit("[错误] 归档目标不能与工作流目录相同")

    target_nonempty = out_dir.exists() and any(out_dir.iterdir())
    if target_nonempty and not args.force and not args.dry_run:
        sys.exit(f"[错误] 归档目录已存在且非空: {out_dir}（使用 --force 覆盖）")
    if target_nonempty and not args.force:
        print(f"[警告] 目标已存在且非空（正式执行需 --force）: {out_dir}")

    print(f"[归档] {workflow_dir}")
    print(f"[目标] {out_dir}")
    if args.dry_run:
        for src, rel in files:
            print(f"  → {rel}  ({src})")
        print(f"[预演] 共 {len(files)} 个文件，未执行复制")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for src, rel in files:
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if sha256_of(dst) != sha256_of(src):
            sys.exit(f"[错误] 校验失败: {rel}")
        copied.append({"rel_path": rel, "size": dst.stat().st_size, "sha256": sha256_of(dst)})

    manifest = {
        "archive_version": ARCHIVE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool": "scripts/archive_pipeline.py",
        "workflow_id": workflow_id,
        "workflow_dir": str(workflow_dir),
        "source_pdf": str(_get(workflow, "source", "input_path", default="")),
        "source_markdown": str(_get(workflow, "source", "markdown_path", default="")),
        "out_root": str(out_root),
        "name": name,
        "file_count": len(copied),
        "files": copied,
    }
    manifest_path = out_dir / "archive.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[完成] 归档 {len(copied)} 个文件 → {out_dir}")
    print(f"[清单] {manifest_path.name}（含逐文件 sha256）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
