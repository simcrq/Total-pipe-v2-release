"""Official MinerU Open API CLI adapter.

The CLI owns authentication and the upload/task/result protocol.  Keeping the
subprocess boundary here prevents the workflow from depending on private API
details that may change independently of this project.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger


class OfficialMinerUProcessor:
    """Run the mineru-open-api command for one local document."""

    def __init__(self, config: dict[str, Any]):
        mineru = config.get("api", {}).get("mineru", {})
        self.config = config
        command = mineru.get("cli_command", "mineru-open-api")
        # Keep a configured executable path with spaces intact.  Extra wrapper
        # arguments can be supplied as a YAML list when needed.
        self.command = [str(part) for part in command] if isinstance(command, list) else [str(command)]
        if not self.command or not self.command[0].strip():
            raise ValueError("api.mineru.cli_command cannot be empty")
        self.extract_mode = str(mineru.get("extract_mode", "precision")).lower()
        if self.extract_mode not in {"precision", "flash"}:
            raise ValueError("api.mineru.extract_mode must be 'precision' or 'flash'")
        self.model = str(mineru.get("model", "vlm"))
        self.timeout = int(mineru.get("timeout", 1800))
        ocr_value = mineru.get("ocr", False)
        self.ocr = (
            ocr_value
            if isinstance(ocr_value, bool)
            else str(ocr_value).strip().lower() in {"1", "true", "yes", "on"}
        )
        self.api_key = str(mineru.get("api_key") or "").strip()

    def process(self, pdf_path: str, output_dir: str) -> None:
        output = Path(output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        source = Path(pdf_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)

        subcommand = "flash-extract" if self.extract_mode == "flash" else "extract"
        command = [*self.command, subcommand, str(source), "-o", str(output)]
        if self.extract_mode == "precision":
            command.extend(["-f", "md", "--model", self.model, "--timeout", str(self.timeout)])
        if self.ocr:
            command.append("--ocr")

        child_env = os.environ.copy()
        # The official CLI resolves MINERU_TOKEN itself.  Passing the token via
        # the child environment keeps it out of logs and process arguments.
        if self.api_key and "MINERU_TOKEN" not in child_env:
            child_env["MINERU_TOKEN"] = self.api_key

        safe_command = " ".join(shlex.quote(part) for part in command if part != str(source))
        logger.info(f"Running official MinerU CLI: {safe_command} <pdf>")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=child_env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "mineru-open-api was not found. Install the official CLI or set "
                "api.mineru.cli_command to its full path."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"MinerU timed out after {self.timeout}s: {source.name}") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "no CLI output").strip()
            raise RuntimeError(f"MinerU CLI failed ({result.returncode}): {detail[-2000:]}")
        if result.stderr:
            logger.debug(f"MinerU CLI stderr for {source.name}: {result.stderr[-2000:]}")
