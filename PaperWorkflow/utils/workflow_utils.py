from pathlib import Path

def find_pdf_files(root_dir):
    """
    遍历目录查找所有 PDF 文件
    返回列表: [{'id': '4586', 'path': '...'}]
    """
    root = Path(root_dir).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    pdf_list = []
    # The first directory below input_dir is the user-facing paper/task ID.
    # Deeper nesting is allowed so a task can keep supplementary PDFs nearby.
    for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        relative_parts = path.parent.relative_to(root).parts
        if not relative_parts:
            # Keep the documented ID-folder contract explicit instead of
            # silently treating a loose PDF as a task.
            continue
        paper_id = relative_parts[0]
        pdf_list.append(
            {
                "id": paper_id,
                "folder_path": str(path.parent),
                "file_path": str(path),
                "file_name": path.name,
            }
        )

    return pdf_list


def determine_mode(paper_id, rules_config):
    """
    根据 ID 和配置判断阅读模式
    """
    # 强制转字符串比较
    paper_id = str(paper_id)
    
    deep_ids = {str(value) for value in rules_config.get('deep_read_ids', [])}
    skim_ids = {str(value) for value in rules_config.get('skim_ids', [])}

    if paper_id in deep_ids:
        return 'deep_read'
    
    if paper_id in skim_ids:
        return 'skim'
        
    return rules_config.get('default_mode', 'skim')
