"""Direct MinerU CLI wrapper for PDF OCR in Total-pipe.

Invokes ``mineru-open-api`` directly without requiring PaperWorkflow's optional
``loguru`` / ``pyyaml`` / ``requests`` stack, resolves Windows ``.CMD`` shims
automatically, and caches OCR outputs by source PDF SHA-256.

CLI usage:
  python -m agent.mineru_cli --pdf <paper.pdf> --out <dir>
  python -m agent.mineru_cli --verify-auth
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from typing import Any

from . import ROOT


class MinerUError(RuntimeError):
    """Typed failure raised when direct MinerU CLI execution cannot succeed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _optional_pwf_mineru_config() -> dict[str, Any]:
    """Read api.mineru from PaperWorkflow config if PyYAML and a config file exist."""
    candidates: list[Path] = []
    explicit = str(os.environ.get('PAPERWORKFLOW_CONFIG') or '').strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(ROOT / 'PaperWorkflow' / 'config.yaml')
    try:
        candidates.append(Path.home() / '.config' / 'paperworkflow' / 'config.yaml')
    except OSError:
        pass
    cfg_path = None
    for candidate in candidates:
        try:
            if candidate.is_file():
                cfg_path = candidate.resolve()
                break
        except OSError:
            continue
    if cfg_path is None:
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    try:
        loaded = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    api = loaded.get('api')
    if not isinstance(api, dict):
        return {}
    mineru = api.get('mineru')
    return mineru if isinstance(mineru, dict) else {}


def resolve_settings(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve MinerU CLI settings (overrides > env > optional PaperWorkflow config > defaults)."""
    cfg = _optional_pwf_mineru_config()
    ov = overrides or {}

    raw_cmd = ov.get('cli_command') or os.environ.get('MINERU_CLI') or cfg.get('cli_command') or 'mineru-open-api'
    if isinstance(raw_cmd, list):
        command = [str(part) for part in raw_cmd if str(part).strip()]
    else:
        raw_text = str(raw_cmd).strip()
        command = [raw_text] if raw_text else []
    if not command:
        raise MinerUError('MINERU_CLI_INVALID', 'MinerU CLI command cannot be empty.')

    extract_mode = str(
        ov.get('extract_mode') or os.environ.get('MINERU_EXTRACT_MODE') or cfg.get('extract_mode') or 'precision'
    ).strip().lower()
    if extract_mode not in ('precision', 'flash'):
        raise MinerUError('MINERU_CONFIG_INVALID', "MinerU extract_mode must be 'precision' or 'flash'.")

    model = str(ov.get('model') or os.environ.get('MINERU_MODEL') or cfg.get('model') or 'vlm').strip() or 'vlm'
    timeout = int(ov.get('timeout') or os.environ.get('MINERU_TIMEOUT') or cfg.get('timeout') or 1800)

    raw_ocr = ov.get('ocr') if 'ocr' in ov else (
        os.environ.get('MINERU_OCR') if 'MINERU_OCR' in os.environ else cfg.get('ocr', False)
    )
    ocr = raw_ocr if isinstance(raw_ocr, bool) else str(raw_ocr).strip().lower() in ('1', 'true', 'yes', 'on')

    api_key = str(ov.get('api_key') or cfg.get('api_key') or '').strip()
    return {
        'command': command,
        'extract_mode': extract_mode,
        'model': model,
        'timeout': timeout,
        'ocr': ocr,
        'api_key': api_key,
    }


def _child_env(api_key: str) -> dict[str, str]:
    env = os.environ.copy()
    if api_key:
        env['MINERU_TOKEN'] = api_key
    return env


def _run_cli(command: list[str], args: list[str], *, timeout: int, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the MinerU CLI, auto-resolving Windows .CMD/.BAT shims via shutil.which."""
    argv = [*command, *args]
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        if os.name == 'nt':
            resolved = shutil.which(command[0])
            if resolved and resolved != command[0]:
                return subprocess.run(
                    [resolved, *command[1:], *args],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=timeout,
                    env=env,
                    check=False,
                )
        raise


def verify_auth(timeout: int = 15, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify MinerU CLI authentication via ``auth --verify`` without uploading any file."""
    settings = resolve_settings(overrides)
    if settings['extract_mode'] == 'flash':
        present = bool(shutil.which(settings['command'][0]))
        return {
            'ready': present,
            'verified': False,
            'required': False,
            'status': 'not_required' if present else 'missing_cli',
            'cli': settings['command'][0],
        }
    try:
        result = _run_cli(settings['command'], ['auth', '--verify'], timeout=timeout, env=_child_env(settings['api_key']))
    except FileNotFoundError:
        status = 'missing_cli'
    except (OSError, subprocess.SubprocessError):
        status = 'unavailable'
    else:
        text = ((result.stdout or '') + '\n' + (result.stderr or '')).lower()
        denied = any(term in text for term in (
            'unauthorized', 'invalid token', 'token is invalid', 'expired', 'no token',
            'token invalid', 'token not found', 'no api token', 'failed to verify',
            'verification failed', 'authentication failed', 'not configured', 'not authenticated', '401', '403',
        ))
        status = 'invalid' if denied else 'verified' if result.returncode == 0 else 'unavailable'
    return {
        'ready': status == 'verified',
        'verified': status == 'verified',
        'required': True,
        'status': status,
        'cli': settings['command'][0],
    }


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _find_markdown(output_dir: Path, stem: str) -> Path | None:
    preferred = [
        output_dir / f'{stem}.md',
        output_dir / 'full.md',
        output_dir / stem / f'{stem}.md',
        output_dir / stem / 'full.md',
        output_dir / 'auto' / f'{stem}.md',
        output_dir / 'hybrid_auto' / f'{stem}.md',
        output_dir / stem / 'auto' / f'{stem}.md',
        output_dir / stem / 'hybrid_auto' / f'{stem}.md',
    ]
    for candidate in preferred:
        if candidate.is_file():
            return candidate.resolve()
    if output_dir.is_dir():
        exact = [p for p in sorted(output_dir.rglob(f'{stem}.md')) if p.is_file()]
        if exact:
            return exact[0].resolve()
        any_md = [p for p in sorted(output_dir.rglob('*.md')) if p.is_file()]
        if any_md:
            return any_md[0].resolve()
    return None


def _find_images_dir(markdown_path: Path) -> Path | None:
    for name in ('images', 'figures', 'assets', 'media'):
        candidate = markdown_path.parent / name
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _extract_outline(markdown_text: str) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for lineno, line in enumerate(markdown_text.splitlines(), 1):
        match = re.match(r'^(#{1,4})[ \t]+(.+?)\s*$', line)
        if match:
            outline.append({
                'level': len(match.group(1)),
                'heading': match.group(2).strip(),
                'line': lineno,
            })
            if len(outline) >= 60:
                break
    return outline


def extract_pdf(
    pdf_path: str | Path,
    output_root: str | Path,
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """OCR a single PDF directly via MinerU CLI into ``output_root/<stem>-<sha16>/``."""
    source = Path(pdf_path).expanduser().resolve()
    if not source.is_file():
        raise MinerUError('MINERU_SOURCE_MISSING', f'PDF file not found: {source}')

    settings = resolve_settings(overrides)
    source_sha = _file_sha256(source)
    safe_stem = re.sub(r'[^A-Za-z0-9._-]+', '_', source.stem).strip('_') or 'paper'
    target_dir = (Path(output_root).expanduser().resolve() / f'{safe_stem}-{source_sha[:16]}')
    target_dir.mkdir(parents=True, exist_ok=True)

    cached_md = _find_markdown(target_dir, source.stem)
    cache_hit = False
    if cached_md is not None and cached_md.stat().st_size > 0:
        markdown_path = cached_md
        cache_hit = True
    else:
        subcommand = 'flash-extract' if settings['extract_mode'] == 'flash' else 'extract'
        args = [subcommand, str(source), '-o', str(target_dir)]
        if settings['extract_mode'] == 'precision':
            args.extend(['-f', 'md', '--model', settings['model'], '--timeout', str(settings['timeout'])])
        if settings['ocr']:
            args.append('--ocr')
        try:
            result = _run_cli(settings['command'], args, timeout=settings['timeout'], env=_child_env(settings['api_key']))
        except FileNotFoundError as exc:
            raise MinerUError(
                'MINERU_CLI_MISSING',
                f"MinerU CLI '{settings['command'][0]}' not found. Install mineru-open-api "
                '(or set MINERU_CLI) and authenticate with `mineru-open-api auth`.',
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise MinerUError(
                'MINERU_OCR_TIMEOUT',
                f"MinerU CLI timed out after {settings['timeout']}s on {source.name}.",
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or 'no CLI output').strip()
            low = detail.lower()
            if any(term in low for term in ('unauthorized', 'invalid token', 'not authenticated', 'no token', '401', '403')):
                raise MinerUError(
                    'MINERU_AUTH_FAILED',
                    f'MinerU CLI authentication failed ({result.returncode}). Run `mineru-open-api auth` or set MINERU_TOKEN.',
                )
            raise MinerUError(
                'MINERU_OCR_FAILED',
                f'MinerU CLI exited with code {result.returncode}: {detail[-1200:]}',
            )

        markdown_path = _find_markdown(target_dir, source.stem)
        if markdown_path is None:
            raise MinerUError(
                'MINERU_OUTPUT_MISSING',
                f'MinerU CLI succeeded but produced no Markdown file under {target_dir}.',
            )

    text = markdown_path.read_text(encoding='utf-8', errors='replace')
    if not text.strip():
        raise MinerUError('MINERU_OUTPUT_EMPTY', f'MinerU CLI produced an empty Markdown file: {markdown_path}')

    images_dir = _find_images_dir(markdown_path)
    safe_cmd = ' '.join(shlex.quote(part) for part in settings['command'])
    return {
        'engine': 'mineru-open-api',
        'mode': 'direct_cli',
        'cli': safe_cmd,
        'extract_mode': settings['extract_mode'],
        'model': settings['model'],
        'ocr_flag': settings['ocr'],
        'source_pdf': str(source),
        'source_sha256': source_sha,
        'markdown_path': str(markdown_path),
        'output_dir': str(target_dir),
        'images_dir': str(images_dir) if images_dir else None,
        'cache_hit': cache_hit,
        'char_count': len(text),
        'outline': _extract_outline(text),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run MinerU CLI directly for Total-pipe PDF OCR.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--pdf', type=Path, help='PDF file to OCR directly via MinerU CLI.')
    group.add_argument('--verify-auth', action='store_true', help='Verify MinerU CLI credentials.')
    parser.add_argument('--out', type=Path, default=Path('./ocr_out'), help='Output root directory for --pdf.')
    args = parser.parse_args(argv)
    if args.verify_auth:
        print(json.dumps(verify_auth(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(extract_pdf(args.pdf, args.out), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
