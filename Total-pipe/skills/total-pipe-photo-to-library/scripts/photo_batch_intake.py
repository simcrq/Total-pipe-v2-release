#!/usr/bin/env python3
"""Batch intake, EXIF normalization, near-duplicate clustering, and contact-sheet
generation for smartphone-photographed PPTX slide images.

Pure Python stdlib + Pillow (no OpenCV/NumPy required). Designed for resumable
Agent triage when converting large batches (10-500+) of phone-shot slide photos
into Total-pipe Deck IR example library entries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

try:
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except Exception:
    HEIF_SUPPORTED = False

SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'}
HEIF_EXTS = {'.heic', '.heif'}
VALID_STATUSES = (
    'pending',
    'selected',
    'skipped_duplicate',
    'skipped_existing',
    'skipped_unreadable',
    'skipped_off_scope',
    'authored',
    'verified',
    'indexed',
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _dhash_64(img: Image.Image) -> int:
    """Compute a 64-bit difference hash (9x8 grayscale horizontal gradients)."""
    small = img.convert('L').resize((9, 8), Image.Resampling.BILINEAR)
    px = list(small.get_flattened_data()) if hasattr(small, 'get_flattened_data') else list(small.getdata())
    bits = 0
    for row in range(8):
        offset = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if px[offset + col] < px[offset + col + 1] else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _quality_metrics(img: Image.Image) -> dict[str, Any]:
    """Fast pure-Pillow sharpness, brightness, and geometry quality heuristics."""
    w, h = img.size
    long_side = max(w, h)
    aspect = round(w / max(h, 1), 3)

    # Normalize to 480px long side for resolution-independent sharpness/glare checks.
    scale = 480.0 / max(long_side, 1)
    nw = max(32, int(round(w * scale)))
    nh = max(32, int(round(h * scale)))
    gray = img.convert('L').resize((nw, nh), Image.Resampling.BILINEAR)

    # Edge energy proxy using a 3x3 Laplacian-like kernel.
    edges = gray.filter(ImageFilter.Kernel((3, 3), (-1, -1, -1, -1, 8, -1, -1, -1, -1), scale=1, offset=128))
    edge_stat = ImageStat.Stat(edges)
    sharpness = round(float(edge_stat.var[0]), 1)

    luma_stat = ImageStat.Stat(gray)
    brightness = round(float(luma_stat.mean[0]), 1)
    contrast = round(float(luma_stat.stddev[0]), 1)

    # Compute fraction of near-clipped highlights (glare indicator).
    hist = gray.histogram()
    total_px = max(sum(hist), 1)
    glare_ratio = round(sum(hist[248:]) / total_px, 4)

    flags: list[str] = []
    if long_side < 640:
        flags.append('low_resolution')
    if sharpness < 140.0:
        flags.append('possibly_blurry')
    if brightness < 38.0:
        flags.append('too_dark')
    elif brightness > 238.0 and contrast < 18.0:
        flags.append('washed_out')
    if glare_ratio > 0.35 and contrast < 30.0:
        flags.append('heavy_glare')
    if aspect < 0.85:
        flags.append('portrait_orientation')

    return {
        'width': w,
        'height': h,
        'aspect_ratio': aspect,
        'sharpness_score': sharpness,
        'brightness_mean': brightness,
        'contrast_std': contrast,
        'glare_ratio': glare_ratio,
        'quality_flags': flags,
    }


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for candidate in (
        'arialbd.ttf',
        'arial.ttf',
        'DejaVuSans-Bold.ttf',
        'DejaVuSans.ttf',
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/msyhbd.ttc',
    ):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _parse_grid(grid_str: str) -> tuple[int, int]:
    parts = grid_str.lower().split('x')
    if len(parts) != 2:
        raise ValueError(f'Invalid --grid {grid_str!r}; expected COLSxROWS such as 3x3')
    cols, rows = int(parts[0]), int(parts[1])
    if cols < 1 or rows < 1 or cols > 8 or rows > 8:
        raise ValueError('--grid dimensions must be between 1 and 8')
    return cols, rows


def _save_normalized_copy(img: Image.Image, dest: Path, max_side: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy = img.convert('RGB')
    if max(copy.size) > max_side:
        copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    copy.save(dest, format='JPEG', quality=88, optimize=True)


def _render_contact_sheets(
    records: list[dict[str, Any]],
    sheets_dir: Path,
    grid: tuple[int, int],
    tile_w: int,
    tile_h: int,
) -> list[str]:
    """Render numbered contact sheets so an Agent can triage 9-12 photos per view."""
    sheets_dir.mkdir(parents=True, exist_ok=True)
    for stale in sheets_dir.glob('sheet_*.png'):
        stale.unlink(missing_ok=True)

    cols, rows = grid
    per_sheet = cols * rows
    margin = 18
    gutter = 14
    header_h = 54
    caption_h = 46

    cell_w = tile_w
    cell_h = tile_h + caption_h
    canvas_w = margin * 2 + cols * cell_w + (cols - 1) * gutter
    canvas_h = margin * 2 + header_h + rows * cell_h + (rows - 1) * gutter

    font_header = _load_font(16)
    font_id = _load_font(15)
    font_meta = _load_font(12)

    total_sheets = max(1, math.ceil(len(records) / per_sheet))
    sheet_paths: list[str] = []

    for sheet_idx in range(total_sheets):
        chunk = records[sheet_idx * per_sheet : (sheet_idx + 1) * per_sheet]
        if not chunk:
            continue
        sheet = Image.new('RGB', (canvas_w, canvas_h), (246, 248, 250))
        draw = ImageDraw.Draw(sheet)

        # Header banner
        draw.rectangle([0, 0, canvas_w, header_h], fill=(20, 39, 53))
        first_id, last_id = chunk[0]['id'], chunk[-1]['id']
        banner = (
            f'Sheet {sheet_idx + 1}/{total_sheets} | '
            f'{first_id}-{last_id} ({len(chunk)}) | '
            f'Teal=Ready  Amber=Warn  Gray=Dup'
        )
        draw.text((margin, 18), banner, fill=(255, 255, 255), font=font_header)

        for idx, rec in enumerate(chunk):
            r = idx // cols
            c = idx % cols
            x0 = margin + c * (cell_w + gutter)
            y0 = margin + header_h + r * (cell_h + gutter)

            is_dup = bool(rec.get('duplicate_of'))
            has_warn = bool(rec.get('quality_flags'))
            status = rec.get('status', 'pending')

            if status in ('indexed', 'verified'):
                badge_bg = (31, 122, 92)
            elif is_dup or status == 'skipped_duplicate':
                badge_bg = (120, 130, 140)
            elif has_warn:
                badge_bg = (196, 122, 26)
            else:
                badge_bg = (38, 110, 114)

            # Card background & border
            draw.rectangle([x0, y0, x0 + cell_w, y0 + cell_h], fill=(255, 255, 255), outline=(206, 214, 222), width=2)

            # Fit photo into tile area
            img_path = Path(rec.get('normalized_path') or rec['source_path'])
            try:
                with Image.open(img_path) as im:
                    thumb = ImageOps.exif_transpose(im).convert('RGB')
                    thumb.thumbnail((tile_w - 8, tile_h - 8), Image.Resampling.LANCZOS)
                    px = x0 + (tile_w - thumb.width) // 2
                    py = y0 + (tile_h - thumb.height) // 2
                    sheet.paste(thumb, (px, py))
            except Exception:
                draw.rectangle([x0 + 4, y0 + 4, x0 + tile_w - 4, y0 + tile_h - 4], fill=(235, 225, 225))
                draw.text((x0 + 16, y0 + tile_h // 2 - 8), 'UNREADABLE', fill=(160, 40, 40), font=font_id)

            # Caption bar
            cy = y0 + tile_h
            draw.rectangle([x0, cy, x0 + cell_w, y0 + cell_h], fill=badge_bg)
            tag_str = f"[{status.upper()}]"
            if is_dup:
                tag_str = f"[DUP -> {rec['duplicate_of']}]"
            elif rec.get('example_id'):
                tag_str = f"[{status}:{rec['example_id']}]"

            line1 = f"{rec['id']}  {tag_str}"
            draw.text((x0 + 8, cy + 4), line1[:46], fill=(255, 255, 255), font=font_id)

            fname = Path(rec['relative_path']).name
            if len(fname) > 26:
                fname = fname[:12] + '...' + fname[-11:]
            flags_txt = ','.join(rec.get('quality_flags') or []) or f"sharp={int(rec.get('sharpness_score', 0))}"
            line2 = f"{fname} | {flags_txt}"
            draw.text((x0 + 8, cy + 25), line2[:54], fill=(236, 244, 245), font=font_meta)

        out_path = sheets_dir / f'sheet_{sheet_idx + 1:03d}.png'
        sheet.save(out_path, format='PNG', optimize=True)
        sheet_paths.append(str(out_path.resolve()))

    return sheet_paths


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if manifest_path.is_file():
        return json.loads(manifest_path.read_text(encoding='utf-8'))
    return {'version': 1, 'created_at': _now_iso(), 'records': []}


def _write_manifest(manifest_path: Path, data: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data['updated_at'] = _now_iso()
    tmp = manifest_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(manifest_path)


def cmd_scan(args: argparse.Namespace) -> int:
    input_dir = args.input_dir.expanduser().resolve()
    work_dir = args.work_dir.expanduser().resolve()
    if not input_dir.is_dir():
        print(json.dumps({'status': 'FAIL', 'error': f'input_dir not found: {input_dir}'}, ensure_ascii=False))
        return 1

    grid = _parse_grid(args.grid)
    manifest_path = work_dir / 'batch_manifest.json'
    norm_dir = work_dir / 'normalized'
    sheets_dir = work_dir / 'contact_sheets'

    existing = _load_manifest(manifest_path)
    prev_by_sha: dict[str, dict[str, Any]] = {}
    prev_by_rel: dict[str, dict[str, Any]] = {}
    max_num = 0
    for rec in existing.get('records', []):
        if rec.get('sha256'):
            prev_by_sha[rec['sha256']] = rec
        if rec.get('relative_path'):
            prev_by_rel[rec['relative_path']] = rec
        rid = str(rec.get('id', ''))
        if rid.startswith('IMG_') and rid[4:].isdigit():
            max_num = max(max_num, int(rid[4:]))

    raw_files = sorted(p for p in input_dir.rglob('*') if p.is_file())
    warnings: list[str] = []
    scanned: list[dict[str, Any]] = []

    for path in raw_files:
        ext = path.suffix.lower()
        if ext in HEIF_EXTS and not HEIF_SUPPORTED:
            warnings.append(
                f'Skipped HEIC/HEIF file {path.relative_to(input_dir)} '
                '(install pillow-heif or batch-convert to JPG/PNG first).'
            )
            continue
        if ext not in SUPPORTED_EXTS and not (ext in HEIF_EXTS and HEIF_SUPPORTED):
            continue

        rel = path.relative_to(input_dir).as_posix()
        sha = _sha256_file(path)
        prev = prev_by_rel.get(rel) or prev_by_sha.get(sha)

        if prev:
            rec_id = prev['id']
        else:
            max_num += 1
            rec_id = f'IMG_{max_num:03d}'

        norm_path = norm_dir / f'{rec_id}.jpg'
        try:
            with Image.open(path) as raw_im:
                im = ImageOps.exif_transpose(raw_im)
                metrics = _quality_metrics(im)
                dhash_val = _dhash_64(im)
                if not norm_path.is_file() or args.force_rebuild:
                    _save_normalized_copy(im, norm_path, args.max_inspect)
            unreadable = False
            read_error = None
        except Exception as exc:
            metrics = {
                'width': 0,
                'height': 0,
                'aspect_ratio': 0.0,
                'sharpness_score': 0.0,
                'brightness_mean': 0.0,
                'contrast_std': 0.0,
                'glare_ratio': 0.0,
                'quality_flags': ['unreadable_file'],
            }
            dhash_val = None
            unreadable = True
            read_error = str(exc)

        rec: dict[str, Any] = {
            'id': rec_id,
            'relative_path': rel,
            'source_path': str(path.resolve()),
            'normalized_path': str(norm_path.resolve()) if not unreadable else None,
            'sha256': sha,
            'dhash_hex': f'{dhash_val:016x}' if dhash_val is not None else None,
            '_dhash_int': dhash_val,
            **metrics,
            'cluster_id': None,
            'duplicate_of': None,
            'status': (prev or {}).get('status') or ('skipped_unreadable' if unreadable else 'pending'),
            'pattern_family': (prev or {}).get('pattern_family'),
            'example_id': (prev or {}).get('example_id'),
            'matched_existing_id': (prev or {}).get('matched_existing_id'),
            'note': (prev or {}).get('note') or read_error,
        }
        scanned.append(rec)

    # Sort deterministically by ID
    scanned.sort(key=lambda r: r['id'])

    # Near-duplicate clustering via connected components on dHash Hamming distance.
    clusters: list[list[dict[str, Any]]] = []
    for rec in scanned:
        dh = rec.get('_dhash_int')
        if dh is None:
            continue
        placed = False
        for cluster in clusters:
            if any(_hamming(dh, member['_dhash_int']) <= args.dedup_threshold for member in cluster):
                cluster.append(rec)
                placed = True
                break
        if not placed:
            clusters.append([rec])

    dup_count = 0
    for c_idx, cluster in enumerate(clusters, start=1):
        cid = f'C{c_idx:03d}'
        # Prefer the sharpest photo with fewest quality flags as the cluster representative.
        best = max(
            cluster,
            key=lambda r: (-len(r.get('quality_flags') or []), r.get('sharpness_score', 0.0), r.get('width', 0)),
        )
        for member in cluster:
            member['cluster_id'] = cid
            if member['id'] != best['id']:
                member['duplicate_of'] = best['id']
                dup_count += 1
                if member['status'] == 'pending':
                    member['status'] = 'skipped_duplicate'

    for rec in scanned:
        rec.pop('_dhash_int', None)

    sheet_paths = _render_contact_sheets(scanned, sheets_dir, grid, args.tile_width, args.tile_height)

    manifest = {
        'version': 1,
        'created_at': existing.get('created_at', _now_iso()),
        'input_dir': str(input_dir),
        'work_dir': str(work_dir),
        'grid': args.grid,
        'dedup_threshold': args.dedup_threshold,
        'contact_sheets': sheet_paths,
        'warnings': warnings,
        'records': scanned,
    }
    _write_manifest(manifest_path, manifest)

    counts: dict[str, int] = {}
    for rec in scanned:
        counts[rec['status']] = counts.get(rec['status'], 0) + 1

    print(
        json.dumps(
            {
                'status': 'PASS',
                'manifest_path': str(manifest_path.resolve()),
                'total_photos': len(scanned),
                'unique_clusters': len(clusters),
                'near_duplicates_flagged': dup_count,
                'status_counts': counts,
                'contact_sheets': sheet_paths,
                'warnings': warnings,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    manifest_path = args.work_dir.expanduser().resolve() / 'batch_manifest.json'
    if not manifest_path.is_file():
        print(json.dumps({'status': 'FAIL', 'error': f'manifest not found: {manifest_path}'}, ensure_ascii=False))
        return 1
    data = _load_manifest(manifest_path)
    records = data.get('records', [])
    by_status: dict[str, list[str]] = {}
    for rec in records:
        by_status.setdefault(rec.get('status', 'pending'), []).append(rec['id'])
    print(
        json.dumps(
            {
                'status': 'PASS',
                'total_photos': len(records),
                'counts': {k: len(v) for k, v in sorted(by_status.items())},
                'ids_by_status': by_status,
                'contact_sheets': data.get('contact_sheets', []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    manifest_path = args.work_dir.expanduser().resolve() / 'batch_manifest.json'
    if not manifest_path.is_file():
        print(json.dumps({'status': 'FAIL', 'error': f'manifest not found: {manifest_path}'}, ensure_ascii=False))
        return 1
    data = _load_manifest(manifest_path)
    by_id = {rec['id']: rec for rec in data.get('records', [])}
    missing = [rid for rid in args.ids if rid not in by_id]
    if missing:
        print(json.dumps({'status': 'FAIL', 'error': f'unknown photo IDs: {missing}'}, ensure_ascii=False))
        return 1

    updated = []
    for rid in args.ids:
        rec = by_id[rid]
        rec['status'] = args.status
        if args.pattern is not None:
            rec['pattern_family'] = args.pattern
        if args.example_id is not None:
            rec['example_id'] = args.example_id
        if args.matched_existing is not None:
            rec['matched_existing_id'] = args.matched_existing
        if args.note is not None:
            rec['note'] = args.note
        updated.append(rid)

    _write_manifest(manifest_path, data)
    print(json.dumps({'status': 'PASS', 'updated': updated, 'new_status': args.status}, ensure_ascii=False, indent=2))
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    manifest_path = args.work_dir.expanduser().resolve() / 'batch_manifest.json'
    if not manifest_path.is_file():
        print(json.dumps({'status': 'FAIL', 'error': f'manifest not found: {manifest_path}'}, ensure_ascii=False))
        return 1
    data = _load_manifest(manifest_path)
    matches = [rec for rec in data.get('records', []) if rec.get('status') == args.status]
    wave = matches[: args.limit]
    print(
        json.dumps(
            {
                'status': 'PASS',
                'requested_status': args.status,
                'remaining_total': len(matches),
                'items': [
                    {
                        'id': r['id'],
                        'normalized_path': r.get('normalized_path'),
                        'source_path': r.get('source_path'),
                        'pattern_family': r.get('pattern_family'),
                        'example_id': r.get('example_id'),
                        'quality_flags': r.get('quality_flags', []),
                        'note': r.get('note'),
                    }
                    for r in wave
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)

    p_scan = sub.add_parser('scan', help='Scan raw phone photos, dedup bursts, and generate contact sheets')
    p_scan.add_argument('--input-dir', required=True, type=Path, help='Folder containing raw slide photos')
    p_scan.add_argument('--work-dir', required=True, type=Path, help='Working directory for manifest and contact sheets')
    p_scan.add_argument('--grid', default='3x3', help='Contact sheet grid COLSxROWS (default: 3x3)')
    p_scan.add_argument('--tile-width', type=int, default=420, help='Contact sheet tile image width in px')
    p_scan.add_argument('--tile-height', type=int, default=260, help='Contact sheet tile image height in px')
    p_scan.add_argument('--max-inspect', type=int, default=1600, help='Max long-side px for EXIF-fixed inspection copy')
    p_scan.add_argument('--dedup-threshold', type=int, default=8, help='dHash Hamming distance threshold for burst dedup')
    p_scan.add_argument('--force-rebuild', action='store_true', help='Regenerate normalized copies even if present')

    p_status = sub.add_parser('status', help='Show compact batch triage and authoring progress')
    p_status.add_argument('--work-dir', required=True, type=Path)

    p_mark = sub.add_parser('mark', help='Update triage/authoring status for one or more photo IDs')
    p_mark.add_argument('--work-dir', required=True, type=Path)
    p_mark.add_argument('--ids', nargs='+', required=True, help='One or more photo IDs such as IMG_001 IMG_004')
    p_mark.add_argument('--status', required=True, choices=VALID_STATUSES)
    p_mark.add_argument('--pattern', help='Layout/pedagogical pattern family label')
    p_mark.add_argument('--example-id', help='Assigned Total-pipe example ID (kebab-case)')
    p_mark.add_argument('--matched-existing', help='Existing library ID if skipped as already covered')
    p_mark.add_argument('--note', help='Short triage or reconstruction note')

    p_next = sub.add_parser('next', help='Fetch the next wave of photos with a given status')
    p_next.add_argument('--work-dir', required=True, type=Path)
    p_next.add_argument('--status', default='selected', choices=VALID_STATUSES)
    p_next.add_argument('--limit', type=int, default=5)

    args = parser.parse_args()
    if args.action == 'scan':
        return cmd_scan(args)
    if args.action == 'status':
        return cmd_status(args)
    if args.action == 'mark':
        return cmd_mark(args)
    if args.action == 'next':
        return cmd_next(args)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
