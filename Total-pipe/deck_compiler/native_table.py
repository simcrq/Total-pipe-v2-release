"""Measured semantic tables, lowered to one editable DrawingML table per reference."""
import math
import re
from xml.etree import ElementTree as ET

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
ET.register_namespace('a', A)
ET.register_namespace('m', 'http://schemas.openxmlformats.org/officeDocument/2006/math')
ET.register_namespace('mc', 'http://schemas.openxmlformats.org/markup-compatibility/2006')
ET.register_namespace('a14', 'http://schemas.microsoft.com/office/drawing/2010/main')


def validate_tables(tables, evidence_refs):
    if not isinstance(tables, list) or len(tables) > 4:
        return ['tables must be a list of at most four native tables']
    errors, ids = [], set()
    for table in tables:
        if not isinstance(table, dict):
            errors.append('table must be an object')
            continue
        tid = table.get('id')
        if not isinstance(tid, str) or not IDENTIFIER.fullmatch(tid) or tid in ids:
            errors.append('table id must be unique and use 1-64 letters, digits, hyphens or underscores')
        else:
            ids.add(tid)
        if set(table)-{'id', 'row_count', 'column_count', 'column_weights', 'header_rows', 'cells', 'origin', 'evidence_refs'}:
            errors.append(f'{tid}: unknown table fields; no page geometry')
        rows, cols = table.get('row_count'), table.get('column_count')
        if type(rows) is not int or type(cols) is not int or not 1 <= rows <= 32 or not 1 <= cols <= 12:
            errors.append(f'{tid}: row_count in [1,32], column_count in [1,12] required')
            continue
        if type(table.get('header_rows', 1)) is not int or not 0 <= table.get('header_rows', 1) <= rows:
            errors.append(f'{tid}: invalid header_rows')
        weights = table.get('column_weights', [1]*cols)
        if not isinstance(weights, list) or len(weights) != cols or any(
                isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or not .1 <= w <= 10 for w in weights):
            errors.append(f'{tid}: column_weights must match columns, each in [0.1,10]')
        refs = table.get('evidence_refs', [])
        if table.get('origin') not in ('paper', 'generated'):
            errors.append(f'{tid}: origin must be paper or generated')
        if (not isinstance(refs, list) or any(not isinstance(r, str) or r not in evidence_refs for r in refs)
                or table.get('origin') == 'paper' and not refs):
            errors.append(f'{tid}: paper table evidence_refs must bind to this slide')
        cells = table.get('cells')
        if not isinstance(cells, list) or not 1 <= len(cells) <= rows*cols:
            errors.append(f'{tid}: nonempty cells list required')
            continue
        occupied, cell_ids = set(), set()
        for cell in cells:
            if not isinstance(cell, dict):
                errors.append(f'{tid}: cell must be an object')
                continue
            if set(cell)-{'id', 'row', 'column', 'row_span', 'column_span', 'text', 'kind', 'align'}:
                errors.append(f'{tid}: unknown cell fields; dimensions are compiler-owned')
            cid = cell.get('id')
            if not isinstance(cid, str) or not IDENTIFIER.fullmatch(cid) or cid in cell_ids:
                errors.append(f'{tid}: unique cell id required')
            else:
                cell_ids.add(cid)
            r, c, rs, cs = (cell.get(k, 1 if 'span' in k else -1) for k in ('row', 'column', 'row_span', 'column_span'))
            if (any(type(v) is not int for v in (r, c, rs, cs)) or min(r, c) < 0 or min(rs, cs) < 1
                    or r+rs > rows or c+cs > cols):
                errors.append(f'{tid}.{cid}: cell span lies outside the logical grid')
                continue
            positions = {(y, x) for y in range(r, r+rs) for x in range(c, c+cs)}
            if occupied & positions:
                errors.append(f'{tid}.{cid}: overlapping merged cells')
            occupied |= positions
            if not isinstance(cell.get('text'), str) or cell.get('kind', 'text') not in ('text', 'formula'):
                errors.append(f'{tid}.{cid}: cell text and supported kind required')
            elif cell.get('kind') == 'formula':
                from totalpipe_layout.formula import parse, FormulaError
                try:
                    parse(cell['text'])
                except FormulaError as error:
                    errors.append(f'{tid}.{cid}: {error}')
            if cell.get('align', 'left') not in ('left', 'center', 'right'):
                errors.append(f'{tid}.{cid}: invalid alignment')
        if len(occupied) != rows*cols:
            errors.append(f'{tid}: every logical position must be covered exactly once; use explicit blank cells')
    return errors


def measure_table(table, width, fonts, size=24):
    from .layout import break_lines
    from .fonts import load_font_file
    from totalpipe_layout.formula import parse, measure
    cols = table['column_count']
    weights = table.get('column_weights', [1]*cols)
    widths = [width*w/sum(weights) for w in weights]
    heights = [size*1.25+16]*table['row_count']
    cells = []
    minimum_width = cols*48.
    # Logical coordinates, not serialization order, define the grid. Set single-row demands
    # before merged-row demands so reordering cells cannot introduce different whitespace.
    for cell in sorted(table['cells'], key=lambda c: (c.get('row_span', 1), c['row'], c['column'])):
        r, c = cell['row'], cell['column']
        rs, cs = cell.get('row_span', 1), cell.get('column_span', 1)
        cw = sum(widths[c:c+cs])-20
        bold = r < table.get('header_rows', 1)
        if cell.get('kind') == 'formula':
            metrics = measure(parse(cell['text']), size)
            required = metrics.width+20
            minimum_width = max(minimum_width, required*sum(weights)/sum(weights[c:c+cs]))
            needed = metrics.height+16
            lines = None
        else:
            face = load_font_file(fonts['bold_font_file' if bold else 'font_file'], size)
            lines = break_lines(cell['text'], face, max(1, cw)) if cell['text'] else ['']
            needed = len(lines)*size*1.25+16
        missing = max(0, needed-sum(heights[r:r+rs]))
        for y in range(r, r+rs):
            heights[y] += missing/rs
        cells.append({**cell, 'lines': lines, 'bold': bold,
                      **({'measured_exact': metrics.exact} if cell.get('kind') == 'formula' else {})})
    return {'column_widths': widths, 'row_heights': heights, 'height': sum(heights),
            'min_width': minimum_width, 'font_size_px': size, 'cells': cells}


def _element(parent, tag, attrs=None):
    return ET.SubElement(parent, '{'+A+'}'+tag, {k: str(v) for k, v in (attrs or {}).items()})


def compile_table(table, box, fonts, theme, preserve_terms=False):
    from .layout_tree import LayoutTreeError
    from totalpipe_layout.formula import parse, to_omml_paragraph, to_plain
    x, y, width, height = box
    chosen = None
    for size in (28, 26, 24):
        plan = measure_table(table, width, fonts, size)
        if plan['min_width'] <= width+.1 and plan['height'] <= height+.1:
            chosen = plan
            break
    if chosen is None:
        chosen = measure_table(table, width, fonts)
        if chosen['min_width'] > width+.1 or not preserve_terms or any(c.get('kind') == 'formula' for c in table['cells']):
            raise LayoutTreeError('table:'+table['id'], 'INSUFFICIENT_TABLE_SPACE',
                'Complete native table cannot fit above its 18 pt font floor.',
                [chosen['min_width'], chosen['height']], [width, height], ['widen_region', 'split_table_or_slide'])
    root = ET.Element('{'+A+'}tbl')
    _element(root, 'tblPr', {'firstRow': '0', 'bandRow': '0'})
    grid = _element(root, 'tblGrid')
    for w in chosen['column_widths']:
        _element(grid, 'gridCol', {'w': round(w*9525)})
    owners = {}
    for cell in chosen['cells']:
        for r in range(cell['row'], cell['row']+cell.get('row_span', 1)):
            for c in range(cell['column'], cell['column']+cell.get('column_span', 1)):
                owners[r, c] = cell
    font, color = theme['font_family'], theme.get('foreground', '#142735').lstrip('#')
    background = theme.get('background', '#FFFFFF').lstrip('#')
    header_color = ''.join(f'{round(int(background[i:i+2], 16)*.93+int(color[i:i+2], 16)*.07):02X}' for i in (0, 2, 4))
    native_cells = []
    for r, rh in enumerate(chosen['row_heights']):
        row = _element(root, 'tr', {'h': round(rh*9525)})
        for c in range(table['column_count']):
            cell = owners[r, c]
            anchor = (r, c) == (cell['row'], cell['column'])
            attrs = {}
            # DrawingML retains a tc at every grid position, including merged continuations.
            if c == cell['column'] and cell.get('column_span', 1) > 1: attrs['gridSpan'] = cell['column_span']
            if r == cell['row'] and cell.get('row_span', 1) > 1: attrs['rowSpan'] = cell['row_span']
            if c != cell['column']: attrs['hMerge'] = '1'
            if r != cell['row']: attrs['vMerge'] = '1'
            tc = _element(row, 'tc', attrs)
            body = _element(tc, 'txBody')
            _element(body, 'bodyPr', {'wrap': 'none', 'anchor': 'ctr'})
            _element(body, 'lstStyle')
            if anchor and cell.get('kind') == 'formula':
                paragraph = ET.fromstring(to_omml_paragraph(parse(cell['text']), chosen['font_size_px'], '#'+color))
                paragraph.insert(0, ET.Element('{'+A+'}pPr', {'algn': {'left': 'l', 'center': 'ctr', 'right': 'r'}[cell.get('align', 'left')]}))
                math_para = paragraph.find('.//{'+M+'}oMathPara')
                math_props = ET.Element('{'+M+'}oMathParaPr')
                ET.SubElement(math_props, '{'+M+'}jc', {'{'+M+'}val': cell.get('align', 'left')})
                math_para.insert(0, math_props)
                body.append(paragraph)
                content = to_plain(parse(cell['text']))
            else:
                lines = cell['lines'] if anchor else ['']
                p = _element(body, 'p')
                props = _element(p, 'pPr', {'algn': {'left': 'l', 'center': 'ctr', 'right': 'r'}[cell.get('align', 'left')]})
                _element(_element(props, 'lnSpc'), 'spcPts', {'val': round(chosen['font_size_px']*1.25*75)})
                for index, line in enumerate(lines or ['']):
                    if index: _element(p, 'br')
                    run = _element(p, 'r')
                    rp = _element(run, 'rPr', {'lang': 'zh-CN', 'sz': round(chosen['font_size_px']*75), 'b': '1' if cell['bold'] else '0'})
                    _element(_element(rp, 'solidFill'), 'srgbClr', {'val': color})
                    _element(rp, 'latin', {'typeface': font})
                    _element(rp, 'ea', {'typeface': font})
                    _element(run, 't').text = line
                _element(p, 'endParaRPr', {'lang': 'zh-CN', 'sz': round(chosen['font_size_px']*75)})
                content = cell['text']
            cp = _element(tc, 'tcPr', {'marL': 10*9525, 'marR': 10*9525, 'marT': 8*9525, 'marB': 8*9525, 'anchor': 'ctr'})
            for side in ('L', 'R', 'T', 'B'):
                line = _element(cp, 'ln'+side, {'w': 9525})
                _element(_element(line, 'solidFill'), 'srgbClr', {'val': 'CDD5DB'})
                _element(line, 'prstDash', {'val': 'solid'})
            _element(_element(cp, 'solidFill'), 'srgbClr', {'val': header_color if cell['bold'] else background})
            if anchor:
                native_cells.append({'id': cell['id'], 'text': content, 'kind': cell.get('kind', 'text'),
                    **({'measured_exact': cell['measured_exact']} if cell.get('kind') == 'formula' else {}),
                    'bbox': [x+sum(chosen['column_widths'][:c]), y+sum(chosen['row_heights'][:r]),
                        sum(chosen['column_widths'][c:c+cell.get('column_span', 1)]),
                        sum(chosen['row_heights'][r:r+cell.get('row_span', 1)])]})
    result = {'id': 'table:'+table['id'], 'kind': 'table', 'role': 'table', 'bbox': [x, y, width, chosen['height']],
        'table_xml': ET.tostring(root, encoding='unicode'), 'row_count': table['row_count'], 'column_count': table['column_count'],
        'font_size_px': chosen['font_size_px'], 'font_family': font, 'cells': native_cells,
        'column_widths': chosen['column_widths'], 'row_heights': chosen['row_heights']}
    if chosen['height'] > height+.1:
        result['scientific_text_overflow'] = {'policy': 'preserve-terms', 'original_bbox': list(box)}
    return result
