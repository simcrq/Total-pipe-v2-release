from loguru import logger
import os

def merge_markdown_files(md_file_paths, output_path):
    """
    合并多个 Markdown 文件为一个文件
    md_file_paths: 列表，包含要合并的 Markdown 文件路径
    output_path: 输出合并后文件的路径
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as outfile:
            for md_file in md_file_paths:
                logger.info(f"Merging file: {md_file}")
                with open(md_file, 'r', encoding='utf-8') as infile:
                    content = infile.read()
                    outfile.write(content)
                    outfile.write("\n\n")  # 在每个文件内容后添加两个换行符作为分隔
        logger.info(f"Successfully merged files into {output_path}")
    except Exception as e:
        logger.error(f"Error merging markdown files: {str(e)}")
        raise e
