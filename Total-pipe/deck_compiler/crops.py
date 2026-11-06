"""Verify lossless rectangular scientific crops against their declared source bytes."""
from pathlib import Path
import hashlib
from io import BytesIO

from PIL import Image, ImageChops


def verified_source(asset, base=Path('.')):
    crop = asset.get('crop')
    if not isinstance(crop, dict) or set(crop) != {'source_path', 'source_sha256', 'box'}:
        raise ValueError('crop requires source_path, source_sha256 and a pixel box [left,top,right,bottom]')
    if asset.get('origin', 'paper') != 'paper':
        raise ValueError('crop provenance is only for paper assets')
    def resolve(value):
        path = Path(value)
        return path if path.is_absolute() else Path(base)/path
    source, target = resolve(crop['source_path']), resolve(asset['path'])
    original_bytes = source.read_bytes()
    if hashlib.sha256(original_bytes).hexdigest() != crop['source_sha256']:
        raise ValueError('crop source SHA-256 differs from the declared source')
    box = crop['box']
    if not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box):
        raise ValueError('crop pixel box requires four integers')
    with Image.open(BytesIO(original_bytes)) as original, Image.open(target) as actual:
        left, top, right, bottom = box
        if not (0 <= left < right <= original.width and 0 <= top < bottom <= original.height):
            raise ValueError('crop pixel box lies outside its source')
        expected = original.crop(tuple(box)).convert('RGBA')
        actual = actual.convert('RGBA')
        if expected.size != actual.size or any(band.getbbox() for band in ImageChops.difference(expected, actual).split()):
            raise ValueError('crop pixels differ from the declared source rectangle; scaling, masking or redraw is not a lossless crop')
    return str(source.resolve())
