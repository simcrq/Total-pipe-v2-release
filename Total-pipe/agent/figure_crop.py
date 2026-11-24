"""Controlled lossless multi-panel figure inspection and rectangular cropping."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw

from deck_compiler.crops import verified_source

MIN_CROP_EXTENT = 32
SAFE_NAME = re.compile(r'^[A-Za-z0-9._-]{1,80}\.png$')


def _foreground_mask_sums(gray: Image.Image, bg_threshold: int = 245) -> tuple[list[int], list[int]]:
    """Return per-row and per-column counts of non-background pixels without external numeric deps."""
    w, h = gray.size
    data = gray.tobytes()
    row_counts = [0] * h
    col_counts = [0] * w
    for y in range(h):
        offset = y * w
        row_fg = 0
        for x in range(w):
            if data[offset + x] < bg_threshold:
                row_fg += 1
                col_counts[x] += 1
        row_counts[y] = row_fg
    return row_counts, col_counts


def _find_gaps(counts: list[int], start: int, end: int, span_len: int,
               max_fg_ratio: float = 0.012, min_gap_px: int = 12) -> list[tuple[int, int]]:
    """Find interior whitespace channels where foreground density stays near zero."""
    threshold = max(0, int(span_len * max_fg_ratio))
    gaps: list[tuple[int, int]] = []
    run_start: int | None = None
    for idx in range(start, end):
        if counts[idx] <= threshold:
            if run_start is None:
                run_start = idx
        else:
            if run_start is not None:
                if run_start > start and idx - run_start >= min_gap_px:
                    gaps.append((run_start, idx))
                run_start = None
    return gaps


def _trim_box(gray: Image.Image, box: tuple[int, int, int, int],
              bg_threshold: int = 245, pad: int = 6) -> list[int] | None:
    l, t, r, b = box
    sub = gray.crop((l, t, r, b))
    mask = sub.point(lambda p: 255 if p < bg_threshold else 0)
    tight = mask.getbbox()
    if tight is None:
        return None
    w, h = gray.size
    tl = max(0, l + tight[0] - pad)
    tt = max(0, t + tight[1] - pad)
    tr = min(w, l + tight[2] + pad)
    tb = min(h, t + tight[3] + pad)
    return [int(tl), int(tt), int(tr), int(tb)]


def auto_detect_panels(image: Image.Image, *, min_panel_px: int = 80,
                       bg_threshold: int = 245, min_gap_px: int = 12,
                       max_depth: int = 4) -> list[list[int]]:
    """Segment a multi-panel figure into candidate [left, top, right, bottom] integer boxes."""
    gray = image.convert('L')
    width, height = gray.size
    if width < min_panel_px or height < min_panel_px:
        return []

    def recurse(box: tuple[int, int, int, int], depth: int) -> list[list[int]]:
        trimmed = _trim_box(gray, box, bg_threshold=bg_threshold, pad=6)
        if trimmed is None:
            return []
        l, t, r, b = trimmed
        bw, bh = r - l, b - t
        if bw < min_panel_px or bh < min_panel_px:
            return []
        if depth >= max_depth:
            return [trimmed]
        sub = gray.crop((l, t, r, b))
        row_counts, col_counts = _foreground_mask_sums(sub, bg_threshold=bg_threshold)
        h_gaps = _find_gaps(row_counts, 0, bh, bw, min_gap_px=min_gap_px)
        v_gaps = _find_gaps(col_counts, 0, bw, bh, min_gap_px=min_gap_px)
        best_h = max((g[1] - g[0] for g in h_gaps), default=0)
        best_v = max((g[1] - g[0] for g in v_gaps), default=0)
        if best_h == 0 and best_v == 0:
            return [trimmed]
        children: list[list[int]] = []
        if best_h >= best_v and h_gaps:
            cuts = [0]
            for gs, ge in h_gaps:
                cuts.extend([gs, ge])
            cuts.append(bh)
            spans = [(cuts[i], cuts[i + 1]) for i in range(0, len(cuts), 2)
                     if cuts[i + 1] - cuts[i] >= min_panel_px]
            if len(spans) >= 2:
                for sy0, sy1 in spans:
                    children.extend(recurse((l, t + sy0, r, t + sy1), depth + 1))
                if len(children) >= 2:
                    return children
        if v_gaps:
            cuts = [0]
            for gs, ge in v_gaps:
                cuts.extend([gs, ge])
            cuts.append(bw)
            spans = [(cuts[i], cuts[i + 1]) for i in range(0, len(cuts), 2)
                     if cuts[i + 1] - cuts[i] >= min_panel_px]
            if len(spans) >= 2:
                children = []
                for sx0, sx1 in spans:
                    children.extend(recurse((l + sx0, t, l + sx1, b), depth + 1))
                if len(children) >= 2:
                    return children
        return [trimmed]

    panels = recurse((0, 0, width, height), 0)
    # Sort in natural reading order (row-banded top-to-bottom, then left-to-right).
    row_quantum = max(24, min_panel_px // 2)
    panels.sort(key=lambda b: (b[1] // row_quantum, b[0]))
    return panels[:12]


def inspect_figure(source_path: str | Path, out_dir: str | Path) -> dict:
    """Render a 100 px coordinate ruler grid + auto-detected panel boxes for visual inspection."""
    src = Path(source_path).resolve()
    raw = src.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(raw)) as original:
        width, height = original.size
        candidates = auto_detect_panels(original)
        canvas = original.convert('RGBA')
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    step = 100 if max(width, height) <= 1600 else 200
    for x in range(step, width, step):
        draw.line([(x, 0), (x, height)], fill=(30, 64, 175, 72), width=1)
        draw.rectangle([x + 2, 2, x + 44, 16], fill=(255, 255, 255, 215))
        draw.text((x + 4, 3), str(x), fill=(30, 64, 175, 255))
    for y in range(step, height, step):
        draw.line([(0, y), (width, y)], fill=(30, 64, 175, 72), width=1)
        draw.rectangle([2, y + 2, 44, y + 16], fill=(255, 255, 255, 215))
        draw.text((4, y + 3), str(y), fill=(30, 64, 175, 255))
    for idx, box in enumerate(candidates, 1):
        l, t, r, b = box
        draw.rectangle([l, t, r - 1, b - 1], outline=(220, 38, 38, 235), width=3)
        tag = f'P{idx} [{l},{t},{r},{b}]'
        tag_w = min(width - l, max(96, len(tag) * 6 + 10))
        draw.rectangle([l, t, l + tag_w, min(height, t + 18)], fill=(220, 38, 38, 225))
        draw.text((l + 4, t + 3), tag, fill=(255, 255, 255, 255))
    merged = Image.alpha_composite(canvas, overlay)
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', src.stem).strip('_') or 'figure'
    grid_path = (out_root / f'{stem}-{source_sha256[:8]}-grid.png').resolve()
    merged.save(grid_path, format='PNG')
    return {
        'action': 'inspect',
        'source_path': str(src),
        'source_sha256': source_sha256,
        'width': width,
        'height': height,
        'grid_preview_path': str(grid_path),
        'candidate_panels': [
            {'id': f'P{idx}', 'box': box, 'width': box[2] - box[0], 'height': box[3] - box[1]}
            for idx, box in enumerate(candidates, 1)
        ],
    }


def crop_figure(source_path: str | Path, box: list[int], out_dir: str | Path, *,
                output_name: str | None = None, source_figure: str | None = None) -> dict:
    """Extract an exact lossless rectangular crop and certify it via crops.verified_source()."""
    if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
        raise ValueError('crop box requires four integers [left, top, right, bottom]')
    left, top, right, bottom = box
    src = Path(source_path).resolve()
    raw = src.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    with Image.open(BytesIO(raw)) as original:
        width, height = original.size
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError(f'crop box {box} lies outside source dimensions {width}x{height}')
        if right - left < MIN_CROP_EXTENT or bottom - top < MIN_CROP_EXTENT:
            raise ValueError(f'crop box {box} must be at least {MIN_CROP_EXTENT}x{MIN_CROP_EXTENT} px')
        cropped = original.crop((left, top, right, bottom))
        cropped.load()
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    if output_name is not None:
        if not SAFE_NAME.fullmatch(output_name):
            raise ValueError('output_name must match ^[A-Za-z0-9._-]{1,80}\\.png$')
        filename = output_name
    else:
        stem = re.sub(r'[^A-Za-z0-9._-]+', '_', src.stem).strip('_') or 'figure'
        filename = f'{stem}-{source_sha256[:8]}-{left}_{top}_{right}_{bottom}.png'
    out_path = (out_root / filename).resolve()
    cropped.save(out_path, format='PNG')
    asset_entry = {
        'path': str(out_path),
        'origin': 'paper',
        **({'source_figure': source_figure} if source_figure else {}),
        'crop': {
            'source_path': str(src),
            'source_sha256': source_sha256,
            'box': [left, top, right, bottom],
        },
    }
    verified_source(asset_entry)
    return {
        'action': 'crop',
        'output_path': str(out_path),
        'width': right - left,
        'height': bottom - top,
        'box': [left, top, right, bottom],
        'source_path': str(src),
        'source_sha256': source_sha256,
        'verified_lossless': True,
        'asset_entry': asset_entry,
    }


def _parse_box(spec: str) -> list[int]:
    parts = [p.strip() for p in spec.split(',') if p.strip()]
    if len(parts) != 4:
        raise ValueError('--box requires four comma-separated integers: left,top,right,bottom')
    return [int(p) for p in parts]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Lossless scientific multi-panel figure inspector and cropper.')
    sub = parser.add_subparsers(dest='command', required=True)

    p_inspect = sub.add_parser('inspect', help='Render pixel ruler grid and candidate sub-panels')
    p_inspect.add_argument('--source', required=True, help='Source figure path')
    p_inspect.add_argument('--out-dir', required=True, help='Output directory for grid PNG')

    p_crop = sub.add_parser('crop', help='Extract lossless sub-rectangle certified by verified_source')
    p_crop.add_argument('--source', required=True, help='Source figure path')
    p_crop.add_argument('--box', required=True, help='Comma-separated pixel box: left,top,right,bottom')
    p_crop.add_argument('--out-dir', required=True, help='Output directory for cropped PNG')
    p_crop.add_argument('--name', default=None, help='Optional PNG filename')
    p_crop.add_argument('--source-figure', default=None, help='Optional paper figure id (e.g. 3a)')

    args = parser.parse_args(argv)
    if args.command == 'inspect':
        payload = inspect_figure(args.source, args.out_dir)
    else:
        payload = crop_figure(
            args.source,
            _parse_box(args.box),
            args.out_dir,
            output_name=args.name,
            source_figure=args.source_figure,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
