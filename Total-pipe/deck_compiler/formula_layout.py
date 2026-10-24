"""Measured formula flow: complete explanation groups, compact rows, and bounded column choices."""
from PIL import ImageFont

from .capacity import FORMULA_GAP, FORMULA_SIZES
from totalpipe_layout.formula import measure, parse


class FormulaCapacityError(ValueError):
    def __init__(self, message, attempts):
        super().__init__(message)
        self.attempts = attempts


def formula_groups(blocks):
    """Keep explicit anchors together; only the first implicit equation attaches to its prose.

    A run of standalone equations must never become children of the first equation (and disappear
    when that equation is emitted). Later unanchored equations are independent rows, so a long
    derivation may continue into a second column without duplicating its introductory sentence.
    """
    groups, anchors = [], {}
    for block in blocks:
        formula = block.get('component') == 'formula'
        anchor = block.get('anchor') if formula else None
        if anchor is not None:
            if anchor not in anchors:
                raise ValueError('FORMULA_ANCHOR_INVALID: anchor must precede the equation')
            groups[anchors[anchor]][1].append(block)
        elif (formula and not block.get('label') and groups
              and groups[-1][0].get('component') != 'formula' and not groups[-1][1]):
            groups[-1][1].append(block)
        else:
            groups.append((block, []))
            if not formula:
                anchors[block['id']] = len(groups)-1
    return groups


def plan_formula_flow(blocks, region, fonts, archetype, *, max_columns=2, preferred_columns=1,
                      body_size=28, gap=18, text_inset=0, preserve_terms=False, list_gap_ratio=.45):
    """Return one measured layout or explain why none fits above the existing 18 pt floor.

    Reading order is down the first column, then down the second. Column breaks are between
    complete groups; labels, prose, every equation and explicit anchors retain their identity.
    Spare height is not allocated to text boxes or multiplied across already independent columns.
    """
    from .layout import break_lines, formula_label_width

    x, y, width, height = region
    groups = formula_groups(blocks)
    if not groups:
        return {'boxes': {}, 'columns': 1, 'font_size_px': FORMULA_SIZES[0],
                'column_heights_px': [], 'reading_order': [], 'attempts': []}
    attempts = []

    def group_rows(anchor, equations, column_width, size, text_size, overflow_review):
        rows = []
        for block in (anchor, *equations):
            if block.get('component') == 'formula':
                label_w = formula_label_width(block.get('label', ''), fonts['bold_font_file'])
                available = column_width-20-(label_w+12 if label_w else 0)
                metrics = measure(parse(block['text']), size)
                if metrics.width > available+.5:
                    return None, {'block_id': block['id'], 'required_width_px': metrics.width,
                                  'available_width_px': round(available, 2)}
                need = max(30 if label_w else 0, metrics.height)+12
            else:
                face = ImageFont.truetype(fonts['font_file'], int(text_size))
                if block.get('text_flow') == 'distributed_arrow_list':
                    from .layout import native_list_height
                    content_height = native_list_height(block, column_width-text_inset, fonts['font_file'],
                                                        list_gap_ratio, preserve_terms=overflow_review)
                elif block.get('inline_math'):
                    from totalpipe_layout.inline_math import measure_inline, InlineWidthError
                    try:
                        inline = measure_inline(block['text'], column_width-text_inset, face, text_size)
                    except InlineWidthError as error:
                        return None, {'block_id': block['id'], 'required_width_px': error.required_width,
                                      'available_width_px': error.available_width}
                    content_height = inline['height']
                else:
                    lines = break_lines(block['text'], face, column_width-text_inset)
                    content_height = max(1, len(lines))*text_size*1.25
                label_h = (40 if archetype == 'figure-parameters' else 44) if block.get('label') else 0
                if block.get('text_flow') == 'distributed_arrow_list':
                    label_h = 0  # Native list measurement already includes the label and minimum box.
                # A last-resort nominal slot lets the existing text writer retain the full
                # scientific prose with SCIENTIFIC_TEXT_OVERFLOW REVIEW. Equations still have
                # to fit geometrically; terminology policy never hides a math capacity failure.
                need = label_h+(text_size*1.25 if overflow_review and block.get('text_flow') != 'distributed_arrow_list' else content_height)
            rows.append((block, need))
        return rows, None

    body_sizes = sorted({max(24, body_size), max(24, body_size-2), 24}, reverse=True)
    strategies = [(size, text_size, False) for size in FORMULA_SIZES for text_size in body_sizes]
    if preserve_terms:
        strategies.append((FORMULA_SIZES[-1], 24, True))
    for size, text_size, overflow_review in strategies:
        candidates = []
        for columns in range(1, min(max_columns, len(groups))+1):
            column_gap = 32
            column_width = (width-column_gap*(columns-1))/columns
            measured = [group_rows(*group, column_width, size, text_size, overflow_review) for group in groups]
            invalid = [error for _, error in measured if error]
            if invalid:
                attempts.append({'font_size_px': size, 'body_size_px': text_size, 'columns': columns,
                                 'prose_overflow_review': overflow_review, 'width_failures': invalid})
                continue
            rows = [value for value, _ in measured]
            heights = [sum(h for _, h in value)+FORMULA_GAP*(len(value)-1) for value in rows]
            # With two columns, enumerate every legal contiguous split; never balance by moving
            # individual equations away from their explicit explanation group.
            splits = [len(groups)] if columns == 1 else range(1, len(groups))
            best = None
            for split in splits:
                sections = [range(len(groups))] if columns == 1 else [range(split), range(split, len(groups))]
                used = [sum(heights[i] for i in section)+gap*max(0, len(section)-1) for section in sections]
                score = (max(used), max(used)-min(used))
                if best is None or score < best[0]:
                    best = (score, sections, used)
            _, sections, used = best
            attempts.append({'font_size_px': size, 'body_size_px': text_size, 'columns': columns,
                             'prose_overflow_review': overflow_review,
                             'required_column_heights_px': [round(h, 2) for h in used],
                             'available_height_px': round(height, 2)})
            if max(used) > height+.5:
                continue
            boxes, order = {}, []
            for col, section in enumerate(sections):
                cursor = y
                for index in section:
                    for block, need in rows[index]:
                        boxes[block['id']] = [x+col*(column_width+column_gap), cursor, column_width, need]
                        order.append(block['id'])
                        cursor += need+FORMULA_GAP
                    cursor += gap-FORMULA_GAP
            candidates.append({'boxes': boxes, 'columns': columns, 'font_size_px': size,
                               'body_size_px': text_size, 'prose_overflow_review': overflow_review,
                               'column_heights_px': [round(h, 2) for h in used], 'reading_order': order})
        if candidates:
            # Keep the largest shared formula size. A comparison prefers side-by-side groups;
            # derivations prefer one readable column when the measured content fits there.
            chosen = min(candidates, key=lambda c: (abs(c['columns']-preferred_columns), c['columns']))
            return {**chosen, 'attempts': attempts}
    raise FormulaCapacityError(
        f'Complete text/equation groups do not fit the {width:.0f} × {height:.0f} px region at 18 pt. '
        'Widen the region or split the derivation without cutting formulas or scientific terms.', attempts)
