import os
import hashlib
from pathlib import Path
from loguru import logger
from .pdf_local_handler import LocalPDFProcessor
from .pdf_api_handler import ApiPDFProcessor
from .pdf_official_handler import OfficialMinerUProcessor

class PDFProcessor:
    def __init__(self, config):
        self.config = config
        self.temp_dir = config['paths'].get('temp_dir', './temp_markdowns')
        self.mode = config.get('api', {}).get('mineru', {}).get('mode', 'official_cli')
        
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
            
        mineru_config = config.get('api', {}).get('mineru', {})
        if self.mode == 'official_cli':
            self.processor = OfficialMinerUProcessor(config)
        elif self.mode == 'local_cli':
            self.processor = LocalPDFProcessor(config)
        elif self.mode == 'api':
            if mineru_config.get('legacy_http', False):
                logger.warning(
                    "Using the legacy handwritten MinerU HTTP adapter because "
                    "api.mineru.legacy_http=true."
                )
                self.processor = ApiPDFProcessor(config)
            else:
                logger.warning(
                    "api.mineru.mode=api is migrated to the official mineru-open-api CLI. "
                    "Set legacy_http=true only for the old HTTP adapter."
                )
                self.processor = OfficialMinerUProcessor(config)
        else:
            raise ValueError(f"Unknown PDF processing mode: {self.mode}")

    def convert_to_markdown(self, pdf_path):
        """
        将 PDF 转换为 Markdown
        返回转换后的 Markdown 内容字符串
        """
        file_name = Path(pdf_path).stem

        # 确保 temp_dir 是绝对路径
        abs_temp_dir = os.path.abspath(self.temp_dir).replace('\\', '/')
        
        # Use a source-specific namespace so identically named PDFs in two task
        # folders cannot reuse one another's Markdown cache.
        source = Path(pdf_path).expanduser().resolve()
        stat = source.stat()
        cache_key = hashlib.sha256(
            f"{source}\0{stat.st_size}\0{stat.st_mtime_ns}".encode("utf-8")
        ).hexdigest()[:16]
        output_root = os.path.join(abs_temp_dir, cache_key)
        output_path = os.path.join(output_root, file_name)
        legacy_output_path = os.path.join(abs_temp_dir, file_name)
        
        # 1. 检查缓存
        cached_content = self._check_cache(output_path, file_name)
        if cached_content is None:
            cached_content = self._check_cache(output_root, file_name)
        if cached_content is None:
            cached_content = self._check_cache(legacy_output_path, file_name)
        if cached_content:
            return cached_content

        logger.info(f"Converting PDF: {file_name} using {self.mode}")

        try:
            # 2. Execute the selected adapter in the source-specific root.
            self.processor.process(pdf_path, output_root)
            
            # 3. 读取结果
            return self._read_result(output_root, file_name)

        except Exception as e:
            logger.error(f"Error processing PDF {pdf_path}: {str(e)}")
            raise e
            
    def _check_cache(self, output_path, file_name):
        possible_paths = [
            os.path.join(output_path, f"{file_name}.md"),
            os.path.join(output_path, "full.md"),
            os.path.join(output_path, "auto", f"{file_name}.md"),
            os.path.join(output_path, "hybrid_auto", f"{file_name}.md"),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"Using cached markdown for {file_name} from {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()

        # Official MinerU CLI versions may choose a slightly different
        # resource layout.  Reuse any exact-name Markdown beneath the cache
        # root before deciding to submit the document again.
        if os.path.isdir(output_path):
            for root, _, files in os.walk(output_path):
                if f"{file_name}.md" in files:
                    path = os.path.join(root, f"{file_name}.md")
                    logger.info(f"Using cached markdown for {file_name} from {path}")
                    with open(path, 'r', encoding='utf-8') as f:
                        return f.read()
        return None
        
    def _read_result(self, output_path, file_name):
        # 尝试在可能的子目录中查找生成的 Markdown 文件
        possible_paths = [
            os.path.join(output_path, f"{file_name}.md"),
            os.path.join(output_path, "full.md"),
            os.path.join(output_path, "auto", f"{file_name}.md"),
            os.path.join(output_path, "hybrid_auto", f"{file_name}.md"),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"Found markdown file at: {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()

        # 如果预定义路径都没找到，尝试遍历查找
        logger.warning(f"Markdown file not found in common paths, checking subfolders of {output_path}...")
        for root, dirs, files in os.walk(output_path):
            for file in files:
                # 优先匹配同名 md 文件
                if file == f"{file_name}.md":
                    found_path = os.path.join(root, file)
                    logger.info(f"Found markdown file at: {found_path}")
                    with open(found_path, 'r', encoding='utf-8') as f:
                        return f.read()
        
        # 如果还找不到，尝试找任意 md 文件
        for root, dirs, files in os.walk(output_path):
            for file in files:
                if file.endswith(".md"):
                    found_path = os.path.join(root, file)
                    logger.info(f"Found markdown file (fallback) at: {found_path}")
                    with open(found_path, 'r', encoding='utf-8') as f:
                        return f.read()
            
        raise FileNotFoundError(f"Converted Markdown file not found in {output_path}")


