"""Incremental candidate review notes. Formal final acknowledgement stays artifact-bound."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from .contracts import digest, file_hash
from .ooxml import target_part

ACK_FILE = 'qa_acknowledgements.json'


def _load_records(out):
    path = out/ACK_FILE
    saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': '1.0', 'records': {}}
    if (not isinstance(saved, dict) or saved.get('version') != '1.0' or
            not isinstance(saved.get('records'), dict) or
            any(not isinstance(value, dict) for value in saved['records'].values())):
        raise ValueError('Invalid candidate QA acknowledgement records')
    return saved


def _artifact_slides(path, count):
    """Hash each slide and its transitive package dependencies, ignoring ZIP timestamps."""
    if not path.is_file():
        return {}
    try:
        with zipfile.ZipFile(path) as package:
            names, hashes, references = set(package.namelist()), {}, {}

            def visit(part, seen):
                if part in seen or part not in names:
                    return
                seen.add(part)
                if part not in hashes:
                    hashes[part] = hashlib.sha256(package.read(part)).hexdigest()
                    rels = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part)+'.rels')
                    references[part] = [rels] if rels in names else []
                    if rels in names:
                        references[part] += [target_part(part, rel.get('Target', ''))
                            for rel in ET.fromstring(package.read(rels))
                            if rel.get('TargetMode') != 'External']
                for dependency in references[part]:
                    visit(dependency, seen)

            result = {}
            for number in range(1, count+1):
                seen = set()
                visit(f'ppt/slides/slide{number}.xml', seen)
                result[number] = digest({part: hashes[part] for part in sorted(seen)}) if seen else file_hash(path)
            return result
    except (zipfile.BadZipFile, ET.ParseError, ValueError, OSError):
        # An invalid package still has QA failures; never reuse notes across changed bytes.
        return {number: file_hash(path) for number in range(1, count+1)}


def _native_pages(path):
    if not path.is_file():
        return {}
    import pdfplumber
    with pdfplumber.open(path) as document:
        fields = ('text', 'fontname', 'size', 'x0', 'x1', 'top', 'bottom')
        return {number: digest({'size': [page.width, page.height],
                    'chars': [{key: char.get(key) for key in fields} for char in page.chars]})
                for number, page in enumerate(document.pages, 1)}


def attach_acknowledgements(out, qa, ir, layout):
    """Refresh bindings; a stored ack only follows the same finding and reviewed slide state."""
    out = Path(out)
    reviews = [item for item in qa['items'] if item['severity'] == 'REVIEW']
    for item in qa['items']:
        item.pop('ack', None)
    qa['acked_count'], qa['unacked_count'] = 0, len(reviews)
    if not reviews:
        return qa
    records = _load_records(out)['records']
    raw_pages = ir.get('slides', []) if isinstance(ir, dict) else []
    pages = raw_pages if isinstance(raw_pages, list) else []
    compiled = (layout or {}).get('slides', [])
    artifact = _artifact_slides(out/'staging.pptx', len(pages)) if qa.get('artifact_sha256') else {}
    native = _native_pages(out/'native.pdf') if qa.get('checks', {}).get('native') and any(
        i.get('source', {}).get('detector') == 'native-visual' for i in reviews) else {}
    contexts, font_hashes = {}, {}
    for number, page in enumerate(pages, 1):
        rendered = compiled[number-1] if number <= len(compiled) else {}
        elements = rendered.get('elements', [])
        fonts = {}
        for element in elements:
            font = element.get('contract', {}).get('font_file')
            if font:
                if font not in font_hashes:
                    font_hashes[font] = file_hash(Path(font)) if Path(font).is_file() else None
                fonts[font] = font_hashes[font]
        asset_ids = {e['asset_id'] for e in elements if e.get('asset_id')}
        contexts[number] = digest({'slide': page, 'theme': ir.get('theme') if isinstance(ir, dict) else None,
            'presentation': ir.get('presentation') if isinstance(ir, dict) else None,
            'rendered': {k: v for k, v in rendered.items() if k != 'adaptation_log'},
            'assets': {aid: (layout or {}).get('assets', {}).get(aid) for aid in sorted(asset_ids)},
            'fonts': fonts})
    for item in qa['items']:
        if item['severity'] != 'REVIEW':
            continue
        number = item.get('slide')
        page = pages[number-1] if type(number) is int and 1 <= number <= len(pages) else None
        slide_id = page.get('id') if isinstance(page, dict) else None
        source = {k: v for k, v in item.get('source', {}).items() if k != 'officecli_issue_id'}
        key = digest([item['rule'], slide_id, item.get('shape') or source.get('component') or item['message'],
                      source.get('detector')])[:24]
        backend_finding = source.get('detector') in ('structural-ooxml', 'native-visual', 'officecli-view-issues')
        signature = digest({'key': key, 'message': item['message'], 'source': source,
            'context': contexts.get(number) or digest([ir, layout]),
            'artifact': artifact.get(number, qa.get('artifact_sha256')) if backend_finding else None,
            'native': (native.get(number) if slide_id else digest(native))
                      if source.get('detector') == 'native-visual' else None,
            'runtime': qa.get('checks', {}).get('officecli_runtime') if backend_finding else None})
        item.update(review_key=key, review_signature=signature)
        stored = records.get(key, {})
        if (stored.get('signature') == signature and isinstance(stored.get('ack'), dict)
                and all(isinstance(stored['ack'].get(k), str) and stored['ack'][k].strip()
                        for k in ('by', 'at', 'note'))):
            item['ack'] = stored['ack']
    qa['acked_count'] = sum(bool(item.get('ack')) for item in reviews)
    qa['unacked_count'] = len(reviews)-qa['acked_count']
    return qa


def _current(out):
    qa = json.loads((out/'qa_report.json').read_text(encoding='utf-8'))
    ir = json.loads((out/'deck_ir.json').read_text(encoding='utf-8'))
    layout_path = out/'layout.json'
    layout = json.loads(layout_path.read_text(encoding='utf-8')) if layout_path.exists() else None
    if (qa.get('ir_sha256') != digest(ir) or
            qa.get('layout_sha256') != (file_hash(layout_path) if layout else None) or
            (qa.get('artifact_sha256') and
             (not (out/'staging.pptx').is_file() or qa['artifact_sha256'] != file_hash(out/'staging.pptx')))):
        raise ValueError('QA evidence is stale; rebuild before recording candidate review')
    if qa.get('checks', {}).get('native'):
        evidence_path, pdf_path = out/'native.json', out/'native.pdf'
        if not evidence_path.is_file() or not pdf_path.is_file():
            raise ValueError('Native QA evidence is stale; rebuild before recording candidate review')
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        if (evidence.get('artifact_sha256') != qa.get('artifact_sha256') or
                evidence.get('pdf_sha256') != file_hash(pdf_path)):
            raise ValueError('Native QA evidence is stale; rebuild before recording candidate review')
    return attach_acknowledgements(out, qa, ir, layout)


def show_qa(out, include_acked=False):
    qa = _current(Path(out))
    return {**qa, 'items': [item for item in qa['items'] if include_acked or not item.get('ack')],
            'includes_acked': include_acked}


def acknowledge_reviews(out, reviewer, note, ids):
    from .pipeline import locked, write_json
    out = Path(out)
    if (not isinstance(reviewer, str) or not reviewer.strip() or
            not isinstance(note, str) or not note.strip() or
            not isinstance(ids, list) or not ids or
            any(not isinstance(value, str) or not value.strip() for value in ids)):
        raise ValueError('Candidate review requires reviewer, note and explicit REVIEW ids')
    with locked(out):
        qa = _current(out)
        selected = [item for item in qa['items'] if item['id'] in ids and item['severity'] == 'REVIEW']
        if set(ids) != {item['id'] for item in selected}:
            raise ValueError('Every selected id must be a current REVIEW finding')
        path = out/ACK_FILE
        saved = _load_records(out)
        ack = {'by': reviewer.strip(), 'at': datetime.now(timezone.utc).isoformat(), 'note': note.strip()}
        for item in selected:
            item['ack'] = ack
            saved['records'][item['review_key']] = {'signature': item['review_signature'], 'ack': ack}
        qa['acked_count'] = sum(bool(item.get('ack')) for item in qa['items'] if item['severity'] == 'REVIEW')
        qa['unacked_count'] = qa['counts']['REVIEW']-qa['acked_count']
        write_json(path, saved)
        write_json(out/'qa_report.json', qa)
        return qa
