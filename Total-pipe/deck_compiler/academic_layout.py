"""Finite region choices for scientific visual jobs; emitters and gates remain shared."""
from PIL import ImageFont


def ratios(preferred, low=.35, high=.75):
    """Try the requested share first, then nearby capacity repairs in the same composition."""
    seen = set()
    for delta in (0, -.04, .04, -.08, .08, -.16, .16):
        value = round(max(low, min(high, preferred+delta)), 4)
        if value not in seen:
            seen.add(value)
            yield value


def block_height(block, width, fonts, archetype):
    from .layout import formula_fit, formula_label_width, text_floor_height
    label = block.get('label', '')
    if block.get('component') == 'formula':
        label_w = formula_label_width(label, fonts['bold_font_file'])
        metrics = formula_fit(block['text'], width-20-(label_w+12 if label_w else 0))
        return max(30 if label else 0, metrics.height+12) if metrics else 10000
    label_h = (40 if archetype == 'figure-parameters' else 44) if label else 0
    return label_h + (text_floor_height(block['text'], width, fonts['font_file'], inline_math=block.get('inline_math', False)) or 10000)


def text_regions(blocks, box, fonts, archetype, gap=24, band=False):
    x, y, width, height = box
    if not blocks:
        return [], 0
    if band:
        w = (width-gap*(len(blocks)-1))/len(blocks)
        h = max(block_height(b, w, fonts, archetype) for b in blocks)
        return [[x+i*(w+gap), y, w, h] for i in range(len(blocks))], h
    needs = [block_height(b, width, fonts, archetype) for b in blocks]
    required = sum(needs)+gap*(len(blocks)-1)
    extra = max(0, height-required)/len(blocks)
    boxes = []
    for need in needs:
        boxes.append([x, y, width, need+extra])
        y += need+extra+gap
    return boxes, required


def emphasis_region(plan, box, fonts):
    """Reserve a small source-bound annotation, adjacent to the evidence context."""
    from .layout import break_lines
    if not plan.get('emphasis'):
        return None, box
    x, y, w, h = box
    face = ImageFont.truetype(fonts['font_file'], 28)
    height = max(36, len(break_lines(plan['emphasis']['text'], face, max(1, w)))*35)
    return [x, y, w, height], [x, y+height+12, w, h-height-12]


def candidates(slide, region, assets, fonts, design):
    """Only allocate regions. No canonical text, figure, or relationship is rewritten."""
    from .layout import graphic_page_regions, caption_height
    comp = slide['composition']
    plan = slide['presentation']['visual_plan']
    job, composition = plan['visual_job'], plan['composition']
    blocks, figures = comp['blocks'], comp['figure_refs']
    x, y, width, height = region
    gap = 24 if design['density'] == 'balanced' else 18
    archetype = comp['archetype']
    if job == 'mechanism-explanation':
        annotation, body = emphasis_region(plan, region, fonts)
        for candidate in graphic_page_regions(comp, body, assets, fonts, visual_plan=plan):
            yield {**candidate, 'emphasis': annotation}
        return
    if job == 'measurement-evidence':
        for ratio in ratios(plan.get('figure_width_ratio', .64)):
            figure_w = width*ratio
            if composition == 'figure-top':
                context, needed = text_regions(blocks, [x, 0, width, height], fonts, archetype, gap, band=True)
                annotation, _ = emphasis_region(plan, [x, 0, width, height], fonts)
                ah = annotation[3]+12 if annotation else 0
                figure_h = height-needed-ah-(gap if blocks or annotation else 0)
                context_y = y+figure_h+gap+ah
                context = [[bx, context_y, bw, bh] for bx, _, bw, bh in context]
                if annotation:
                    annotation[1] = y+figure_h+gap
                figure_box = [x+(width-figure_w)/2, y, figure_w, figure_h]
            else:
                text_w = width-figure_w-gap
                figure_x = x if composition == 'figure-left' else x+text_w+gap
                text_x = x+figure_w+gap if composition == 'figure-left' else x
                annotation, text_box = emphasis_region(plan, [text_x, y, text_w, height], fonts)
                context, _ = text_regions(blocks, text_box, fonts, archetype, gap)
                figure_box = [figure_x, y, figure_w, height]
            yield {'pattern': composition, 'blocks': context, 'figures': [figure_box],
                   'emphasis': annotation, 'figure_width_ratio': ratio}
        return
    # A comparison preserves the original figure identities even when their reading order changes.
    primary = plan['primary']['index']
    order = plan.get('evidence_order', [primary, 1-primary])
    annotation, body = emphasis_region(plan, region, fonts)
    x, y, width, height = body
    context, needed = text_regions(blocks, body, fonts, archetype, gap, band=True)
    figure_y = y+needed+(gap if blocks else 0)
    figure_h = y+height-figure_y
    shares = ratios(plan.get('figure_width_ratio', .5)) if composition == 'evidence-columns' else [1]
    for ratio in shares:
        boxes = [None, None]
        if composition == 'evidence-columns':
            widths = [(width-gap)*ratio, (width-gap)*(1-ratio)]
            cursor = x
            for index, w in zip(order, widths):
                boxes[index] = [cursor, figure_y, w, figure_h]
                cursor += w+gap
            # Both captions start on the same baseline. Images keep their aspect and sit above it.
            caption_h = max((f.get('caption_height') or caption_height(f['caption'], boxes[i][2],
                fonts['font_file'], f.get('caption_font_size', 22))) if f['caption'] else 0
                for i, f in enumerate(figures))
            caption_top = figure_y+figure_h-caption_h
        else:
            h = (figure_h-gap)/2
            for row, index in enumerate(order):
                boxes[index] = [x, figure_y+row*(h+gap), width, h]
            caption_top = None
        yield {'pattern': composition, 'blocks': context, 'figures': boxes,
               'emphasis': annotation, 'caption_top': caption_top, 'evidence_order': order,
               **({'figure_width_ratio': ratio} if composition == 'evidence-columns' else {})}


def graphic_without_evidence(composition, region, fonts, plan):
    """Add left/right/below context variants to the existing graphic candidate mechanism."""
    x, y, width, height = region
    blocks = composition['blocks']
    preferred = plan.get('graphic_width_ratio', .68 if blocks else 1.0)
    for share in ratios(preferred, .4, 1.0):
        if plan['composition'] == 'graphic-top':
            context, needed = text_regions(blocks, [x, 0, width, height], fonts,
                                           composition['archetype'], band=True)
            graphic_h = height-needed-(24 if blocks else 0)
            yield {'pattern': 'graphic-above-context',
                   'blocks': [[bx, y+graphic_h+24, bw, bh] for bx, _, bw, bh in context],
                   'figures': [], 'graphic': [x+(width-width*share)/2, y, width*share, graphic_h],
                   'graphic_width_ratio': share}
        elif blocks:
            graphic_w = (width-24)*share
            context_w = width-24-graphic_w
            left = plan['composition'] == 'graphic-left'
            graphic_x = x if left else x+context_w+24
            context_x = x+graphic_w+24 if left else x
            context, _ = text_regions(blocks, [context_x, y, context_w, height], fonts, composition['archetype'])
            yield {'pattern': plan['composition'], 'blocks': context, 'figures': [],
                   'graphic': [graphic_x, y, graphic_w, height], 'graphic_width_ratio': share}
        else:
            graphic_w = width*share
            graphic_x = x if plan['composition'] == 'graphic-left' else x+width-graphic_w
            yield {'pattern': plan['composition'], 'blocks': [], 'figures': [],
                   'graphic': [graphic_x, y, graphic_w, height], 'graphic_width_ratio': share}
