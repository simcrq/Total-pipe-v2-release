import hashlib
import os
from pathlib import Path

from loguru import logger

from .pdf_api_handler import ApiPDFProcessor
from .pdf_local_handler import LocalPDFProcessor
from .pdf_official_handler import OfficialMinerUProcessor


class PDFProcessor:
    def __init__(self, config):
        self.config = config
        self.temp_dir = config["paths"].get("temp_dir", "./temp_markdowns")
        self.mode = config.get("api", {}).get("mineru", {}).get("mode", "official_cli")

        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)

        mineru_config = config.get("api", {}).get("mineru", {})
        if self.mode == "official_cli":
            self.processor = OfficialMinerUProcessor(config)
        elif self.mode == "local_cli":
            self.processor = LocalPDFProcessor(config)
        elif self.mode == "api":
            if mineru_config.get("legacy_http", False):
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

    def convert_to_markdown_result(self, pdf_path):
        """
        Convert a PDF and return both content and the real MinerU artifact path.

        Keeping the path is essential for Total-pipe: extracted images live next
        to this Markdown and must be staged into the hand-off bundle with it.
        """
        file_name = Path(pdf_path).stem

        # 确保 temp_dir 是绝对路径
        abs_temp_dir = os.path.abspath(self.temp_dir).replace("\\", "/")

        # Use a source-specific namespace so identically named PDFs in two task
        # folders cannot reuse one another's Markdown cache.
        source = Path(pdf_path).expanduser().resolve()
        stat = source.stat()
        cache_key = hashlib.sha256(
            f"{source}\0{stat.st_size}\0{stat.st_mtime_ns}".encode()
        ).hexdigest()[:16]
        output_root = os.path.join(abs_temp_dir, cache_key)
        output_path = os.path.join(output_root, file_name)
        legacy_output_path = os.path.join(abs_temp_dir, file_name)

        # 1. 检查缓存
        cached_path = self._find_markdown(output_path, file_name)
        if cached_path is None:
            cached_path = self._find_markdown(output_root, file_name)
        if cached_path is None:
            cached_path = self._find_markdown(legacy_output_path, file_name)
        if cached_path is not None:
            logger.info(f"Using cached markdown for {file_name} from {cached_path}")
            return {
                "content": cached_path.read_text(encoding="utf-8"),
                "markdown_path": str(cached_path.resolve()),
                "cache_dir": str(Path(output_root).resolve()),
                "cache_hit": True,
            }

        logger.info(f"Converting PDF: {file_name} using {self.mode}")

        try:
            # 2. Execute the selected adapter in the source-specific root.
            self.processor.process(pdf_path, output_root)

            # 3. 读取结果
            markdown_path = self._find_markdown(output_root, file_name, allow_any=True)
            if markdown_path is None:
                raise FileNotFoundError(f"Converted Markdown file not found in {output_root}")
            logger.info(f"Found markdown file at: {markdown_path}")
            return {
                "content": markdown_path.read_text(encoding="utf-8"),
                "markdown_path": str(markdown_path.resolve()),
                "cache_dir": str(Path(output_root).resolve()),
                "cache_hit": False,
            }

        except Exception as e:
            logger.error(f"Error processing PDF {pdf_path}: {str(e)}")
            raise e

    def convert_to_markdown(self, pdf_path):
        """Backward-compatible content-only API."""

        return self.convert_to_markdown_result(pdf_path)["content"]

    def _find_markdown(self, output_path, file_name, allow_any=False):
        possible_paths = [
            os.path.join(output_path, f"{file_name}.md"),
            os.path.join(output_path, "full.md"),
            os.path.join(output_path, "auto", f"{file_name}.md"),
            os.path.join(output_path, "hybrid_auto", f"{file_name}.md"),
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return Path(path)

        # Official MinerU CLI versions may choose a slightly different
        # resource layout.  Reuse any exact-name Markdown beneath the cache
        # root before deciding to submit the document again.
        if os.path.isdir(output_path):
            for root, _, files in os.walk(output_path):
                if f"{file_name}.md" in files:
                    return Path(root) / f"{file_name}.md"
            if allow_any:
                for root, _, files in os.walk(output_path):
                    for file in files:
                        if file.endswith(".md"):
                            return Path(root) / file
        return None
