"""Freeze an immutable baseline; unavailable historical metrics stay null."""
import argparse
from pathlib import Path
import shutil
import zipfile
import xml.etree.ElementTree as ET
from .contracts import file_hash
from .ooxml import NS, slide_parts
from .pipeline import write_json


def freeze(source, out):
    out.mkdir(parents=True, exist_ok=True)
    target = out/'baseline.pptx'
    sha = file_hash(source)
    if target.exists() and file_hash(target) != sha:
        raise ValueError('Baseline already frozen with different bytes')
    if not target.exists():
        shutil.copyfile(source, target)
    with zipfile.ZipFile(source) as z:
        slides = [ET.fromstring(z.read(p)) for p in slide_parts(z)]
        counts = {key: sum(len(s.findall(path, NS)) for s in slides) for key, path in
                  [('shapes', './/p:sp'), ('pictures', './/p:pic'), ('text_bodies', './/p:txBody')]}
    result = {'baseline_sha256': sha, 'source': source.name, 'slide_count': len(slides), **counts,
              'runtime_seconds': None, 'mcp_calls': None, 'qa_false_positive_rate': None,
              'historical_metrics_status': 'not_recorded', 'repair_amplification_factor': None}
    write_json(out/'benchmark.json', result)
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--pptx', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    print(freeze(args.pptx, args.out))
