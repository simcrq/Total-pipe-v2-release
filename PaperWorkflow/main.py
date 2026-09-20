import argparse
import json
import os
import yaml
import time
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from loguru import logger
from tqdm import tqdm

from utils.pdf_handler import PDFProcessor
from utils.llm_handler import LLMHandler
from utils.prompt_builder import PromptBuilder
from utils.workflow_utils import find_pdf_files, determine_mode
from utils.md_merger import merge_markdown_files
from utils.paper_tools import document_manifest

logger.remove()
# 显示 INFO 及以上，避免跳过缓存、迁移和重试提示
logger.add(
    sys.stderr,
    format= "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{message}</level>",
    filter=lambda r: r["level"].no >= 20,
    colorize=True
)


def load_config(config_path="config.yaml"):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}
    config_dir = Path(config_path).expanduser().resolve().parent
    paths = config.setdefault('paths', {})
    for key in ('input_dir', 'output_dir', 'merge_output_dir', 'temp_dir'):
        value = paths.get(key)
        if isinstance(value, str) and value.strip() and not Path(value).expanduser().is_absolute():
            paths[key] = str((config_dir / value).resolve())
    return config


def _summary_path(paper_info, config, mode):
    file_stem = Path(paper_info['file_name']).stem
    output_filename = f"Summary_{mode}_{file_stem}.md"
    configured_output = str(config.get('paths', {}).get('output_dir', '') or '').strip()
    if configured_output:
        output_dir = Path(configured_output).expanduser() / str(paper_info['id'])
    else:
        output_dir = Path(paper_info['folder_path'])
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / output_filename


def process_single_paper(paper_info, config, pdf_processor, llm_handler):
    """
    处理单篇论文的完整流程
    """
    paper_id = paper_info['id']
    pdf_path = paper_info['file_path']
    file_name = paper_info['file_name']
    
    # 1. 确定模式
    mode = determine_mode(paper_id, config['processing_rules'])
    logger.info(f"正在处理子目录 [{paper_id}] 下pdf, 处理模式: {mode}")
    
    output_path = _summary_path(paper_info, config, mode)
    manifest_path = output_path.with_suffix('.manifest.json')
    
    # 检查是否已存在
    if output_path.exists() and manifest_path.exists():
        logger.warning(f"Output for {paper_id} already exists. Skipping.")
        return str(output_path)
    if output_path.exists() and not manifest_path.exists():
        logger.warning(f"Summary exists without manifest for {paper_id}; rebuilding the evidence manifest.")


    try:
        # 2. PDF -> Markdown
        start_time = time.time()
        md_content = pdf_processor.convert_to_markdown(pdf_path)
        logger.debug(f"[{paper_id}] PDF converted in {time.time() - start_time:.2f}s")
        
        # 3. Build Prompt
        # 获取配置
        processing = config.get('processing_rules', {})
        remove_refs = processing.get('remove_references', True)
        max_prompt_chars = int(processing.get('max_prompt_chars', 60000))
        prompt = PromptBuilder.build_summary_prompt(
            md_content,
            mode,
            remove_refs=remove_refs,
            max_chars=max_prompt_chars,
            source_name=file_name,
        )
        
        # 4. LLM Extraction
        summary = llm_handler.summarize(prompt)
        
        # 5. Save Result
        with output_path.open('w', encoding='utf-8') as f:
            f.write(f"# Summary: {file_name}\n")
            f.write(f"- **ID**: {paper_id}\n")
            f.write(f"- **Mode**: {mode}\n")
            f.write(f"- **Date**: {time.strftime('%Y-%m-%d')}\n\n")
            f.write(summary)

        # Persist the section map next to the human-readable report.  This is
        # the hand-off point for an Agent: it can retrieve evidence by E###
        # without reparsing the PDF or trusting an opaque model summary.
        manifest = document_manifest(
            md_content,
            pdf_path=pdf_path,
            markdown_path=None,
            chunk_chars=int(processing.get('chunk_chars', 6000)),
        )
        manifest['summary_path'] = str(output_path.resolve())
        with manifest_path.open('w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        logger.success(f"[{paper_id}] Summary saved to {output_path}")
        return str(output_path)
    except Exception as e:
        logger.error(f"[{paper_id}] Failed: {str(e)}")
        return None


def main(config_path="config.yaml", dry_run=False):
    # Setup Logger
    Path("logs").mkdir(parents=True, exist_ok=True)
    logger.add("logs/workflow_{time}.log", rotation="500 MB")
    
    # Load Config
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        return
    config = load_config(config_path)
    
    # Find Files
    input_dir = config['paths']['input_dir']
    if not os.path.exists(input_dir):
        logger.error(f"Input directory not found: {input_dir}")
        return
    papers = find_pdf_files(input_dir)
    logger.info(f"共找到 {len(papers)} 篇论文待处理。")
    logger.info(f"本项目已在github开源, 仓库地址:https://github.com/SimCr/PaperWorkflow")

    if dry_run:
        for paper in papers:
            logger.info(f"DRY RUN [{paper['id']}] {paper['file_path']} -> {determine_mode(paper['id'], config['processing_rules'])}")
        return

    # Initialize network/local handlers only after dry-run validation.
    try:
        pdf_processor = PDFProcessor(config)
        llm_handler = LLMHandler(config)
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        return
    
    # Concurrent Processing
    max_workers = config['concurrency']['max_workers']
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 使用 list 强制执行，配合 tqdm 显示进度
        outputs = list(tqdm(
            executor.map(lambda p: process_single_paper(p, config, pdf_processor, llm_handler), papers),
            total=len(papers),
        ))

    # Optional Post-Processing Steps
    # 1.合并所有Markdown文件
    if config.get('processing_rules', {}).get('is_merger_md', False):
        logger.info("正在合并所有Markdown文件...")
        valid_outputs = [path for path in outputs if path and Path(path).is_file()]
        if not valid_outputs:
            logger.warning("没有可合并的总结文件，跳过合并。")
            return
        merge_dir = Path(config['paths'].get('merge_output_dir') or '.')
        merge_dir.mkdir(parents=True, exist_ok=True)
        merge_markdown_files(valid_outputs, str(merge_dir / f"Merged_Summaries+{time.strftime('%Y%m%d')}.md"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch PDF ingestion and paper summarisation workflow")
    parser.add_argument('--config', default='config.yaml', help='Path to config YAML')
    parser.add_argument('--dry-run', action='store_true', help='List papers and modes without calling APIs')
    args = parser.parse_args()
    main(args.config, dry_run=args.dry_run)
