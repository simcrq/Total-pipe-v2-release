#!/usr/bin/env python3
"""Run PaperWorkflow's prompt-fusion + LLM summarization stage on an existing
MinerU Markdown file (no OCR is performed).

Outputs (all into --output-dir):
  - Summary_<mode>_<stem>.md            human-readable LLM summary
  - Summary_<mode>_<stem>.manifest.json evidence-addressable section manifest
  - outline_<stem>.json                 section outline snapshot
  - evidence_<stem>.json                evidence-retrieval snapshot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml

# The project root is derived from this script's own location (scripts/ ->
# project root) and can be overridden with PAPERWORKFLOW_ROOT.
PROJECT_ROOT = Path(
    os.environ.get("PAPERWORKFLOW_ROOT")
    or Path(__file__).resolve().parent.parent
).resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from utils.agent_tools import get_document_outline, retrieve_evidence
from utils.llm_handler import LLMHandler
from utils.paper_tools import document_manifest
from utils.prompt_builder import PromptBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown_path")
    parser.add_argument("--mode", default="deep_read", choices=["skim", "deep_read"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pdf-path", default=None)
    parser.add_argument("--source-name", default="e1.pdf")
    parser.add_argument("--paper-id", default="e1")
    parser.add_argument(
        "--evidence-query", default="synthesis methods parameters conclusions"
    )
    parser.add_argument("--model", default="deepseek-v4-flash")
    args = parser.parse_args()

    config_path = PROJECT_ROOT / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    # LLM credentials: reuse the local DSH DeepSeek credential (user-approved).
    creds_path = Path.home() / ".dsh" / ".credentials.yaml"
    creds = yaml.safe_load(creds_path.read_text(encoding="utf-8")) or {}
    ds_key = str(creds.get("DEEPSEEK_API_KEY") or "").strip()
    if not ds_key:
        raise RuntimeError(f"DEEPSEEK_API_KEY not found in {creds_path}")
    llm = config.setdefault("api", {}).setdefault("llm", {})
    llm.update(
        {
            "api_key": ds_key,
            "base_url": "https://api.deepseek.com",
            "model_name": args.model,
            "timeout": 400,
        }
    )

    markdown_path = Path(args.markdown_path).expanduser().resolve()
    markdown = markdown_path.read_text(encoding="utf-8")

    processing = config.get("processing_rules", {})
    prompt = PromptBuilder.build_summary_prompt(
        markdown,
        mode=args.mode,
        remove_refs=bool(processing.get("remove_references", False)),
        max_chars=int(processing.get("max_prompt_chars", 60000)),
        source_name=args.source_name,
    )

    handler = LLMHandler(config)
    summary = handler.summarize(prompt)

    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.source_name).stem

    summary_path = out / f"Summary_{args.mode}_{stem}.md"
    with summary_path.open("w", encoding="utf-8") as handle:
        handle.write(f"# Summary: {args.source_name}\n")
        handle.write(f"- **ID**: {args.paper_id}\n")
        handle.write(f"- **Mode**: {args.mode}\n")
        handle.write(f"- **Date**: {time.strftime('%Y-%m-%d')}\n")
        handle.write(f"- **LLM**: {llm['model_name']} @ {llm['base_url']}\n\n")
        handle.write(summary)

    chunk_chars = int(processing.get("chunk_chars", 6000))
    manifest = document_manifest(
        markdown,
        pdf_path=args.pdf_path,
        markdown_path=str(markdown_path),
        chunk_chars=chunk_chars,
    )
    manifest["summary_path"] = str(summary_path.resolve())
    manifest_path = out / f"Summary_{args.mode}_{stem}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    outline = get_document_outline(str(markdown_path), chunk_chars=chunk_chars)
    outline_path = out / f"outline_{stem}.json"
    outline_path.write_text(
        json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    evidence = {
        "source": str(markdown_path),
        "query": args.evidence_query,
        "note": "中文查询'实验方法、关键参数和结论'在该词法检索器中命中为0（正文为英文），故改用等价英文关键词检索。",
        "results": retrieve_evidence(str(markdown_path), args.evidence_query, top_k=8)[
            "results"
        ],
    }
    evidence_path = out / f"evidence_{stem}.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "summary_path": str(summary_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "outline_path": str(outline_path.resolve()),
                "evidence_path": str(evidence_path.resolve()),
                "mode": args.mode,
                "model": llm["model_name"],
                "summary_chars": len(summary),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
