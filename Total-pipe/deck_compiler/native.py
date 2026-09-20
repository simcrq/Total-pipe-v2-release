"""Golden renderer: PowerPoint on macOS. No fallback can masquerade as golden."""
import subprocess
import sys
from pathlib import Path
from .contracts import file_hash, issue

SCRIPT = '''on run argv
set inputPath to item 1 of argv
set outputPath to item 2 of argv
tell application "Microsoft PowerPoint"
    open POSIX file inputPath
    set p to active presentation
    try
        save p in POSIX file outputPath as save as PDF
    on error messageText number errorNumber
        close p saving no
        error messageText number errorNumber
    end try
    close p saving no
end tell
end run'''


def render(pptx, pdf):
    if sys.platform != 'darwin':
        return None, [issue('NATIVE_RENDER_UNAVAILABLE', 'REVIEW', 'PowerPoint golden renderer requires macOS',
                           detector='native-visual', confidence='LOW', renderer='powerpoint')]
    if pdf.exists():
        pdf.unlink()
    try:
        subprocess.run(['osascript', '-e', SCRIPT, str(pptx.resolve()), str(pdf.resolve())],
                       check=True, capture_output=True, text=True, timeout=55)
        if not pdf.exists() or not pdf.read_bytes().startswith(b'%PDF'):
            raise ValueError('PowerPoint did not produce a PDF')
        return {'renderer': 'powerpoint', 'artifact_sha256': file_hash(pptx),
                'pdf_sha256': file_hash(pdf), 'pdf': str(pdf.resolve())}, []
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        return None, [issue('NATIVE_RENDER_UNAVAILABLE', 'REVIEW', (getattr(error, 'stderr', None) or str(error)),
                            detector='native-visual', confidence='LOW', renderer='powerpoint')]


def inspect_pdf(pdf, layout):
    """Native PDF text/font evidence; scientific panel interpretation stays REVIEW."""
    import pdfplumber
    items = []
    def add(rule, msg, page=None, severity='FAIL', confidence='HIGH'):
        items.append(issue(rule, severity, msg, page, detector='native-visual',
                           confidence=confidence, renderer='powerpoint', font_metrics='powerpoint-pdf'))
    with pdfplumber.open(pdf) as doc:
        if len(doc.pages) != len(layout['slides']):
            add('NATIVE_PAGE_COUNT', 'Native render page count differs from IR')
        layout_width, layout_height = layout['slide_size']
        for n, (page, slide) in enumerate(zip(doc.pages, layout['slides']), 1):
            normalize = lambda s: ''.join(s.split()).replace('\u00ad', '')
            scale_x = page.width / layout_width
            scale_y = page.height / layout_height
            for e in slide['elements']:
                if e['kind'] != 'text':
                    continue
                expected = normalize(e['text'])
                x, y, width, height = e['bbox']
                region = page.crop((x * scale_x, y * scale_y,
                                    (x + width) * scale_x, (y + height) * scale_y), strict=False)
                actual = normalize(region.extract_text() or '')
                if expected and expected != actual:
                    add('NATIVE_TEXT_REVIEW',
                        f"Native text region does not match {e['id']}",
                        n, 'REVIEW', 'MEDIUM')
            spans = page.chars
            requested = {e['contract']['font_family'].replace(' ', '').lower()
                         for e in slide['elements'] if e['kind'] == 'text'}
            for span in spans:
                box = (span['x0'], span['top'], span['x1'], span['bottom'])
                if box[0] < -1 or box[1] < -1 or box[2] > page.width+1 or box[3] > page.height+1:
                    add('NATIVE_TEXT_OUT_OF_BOUNDS', 'Rendered text exceeds slide', n)
                face = span['fontname'].replace(' ', '').replace('-', '').lower()
                if not any(f in face for f in requested):
                    add('FONT_SUBSTITUTION_REVIEW', f"Native font: {span['fontname']}", n, 'REVIEW', 'MEDIUM')
    # Deduplicate repeated font findings.
    return list({i['id']: i for i in items}.values())
