"""Read-only Deck IR bridge and conservative content gates, in CSS pixels.

Blocks and figure/caption pairs are atomic units. The canonical IR is never
rewritten. A proposal is an optional body layout, not compiler/native approval.
"""
import copy
import hashlib
import importlib
import json
import math
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFont

ARCHETYPES = ('cover-hero', 'metric-comparison', 'process-flow', 'figure-parameters',
              'hero-dual-evidence', 'evidence-hypothesis', 'dual-demonstration',
              'three-limitations', 'three-conclusions')
ROLES = ('body', 'metric', 'parameter', 'process-step', 'direct-evidence', 'hypothesis',
         'limitation', 'conclusion', 'callout', 'comparison', 'definition', 'observation',
         'method', 'result', 'question', 'source', 'caveat', 'figure')
WIDTHS = (180, 280, 440, 700, 1168)
MAX_UNITS = 16
FEATURES = 17

# One grid for the packer and the compiler: 12 columns of 75.33 px with 24 px gutters across the
# 1168 px body. Every proposal is a whole number of columns, so gutters stay at 24 px and a page
# cannot drift by a few pixels between templates.
GRID_COLUMNS = 12
GRID_GAP = 24.0
# Human review rules, enforced instead of merely rendered: a scientific talk keeps every body size
# at or above 18 pt, and a trailing line of one or two characters is a typographic defect.
MIN_FONT_PT = 18.0
MIN_LINE_CHARS = 3
# A text box may exceed its content by this much before it reads as empty space. The pad covers
# descenders and pixel rounding; the factor covers a last line that just misses fitting.
HUG_FACTOR = 1.05
HUG_PAD = 8.0
# A figure box that is much larger than its picture leaves a visible empty band. The packer sizes
# the box to the picture, so anything above this is a real defect, not a stylistic preference.
MAX_FIGURE_VOID = 0.15


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def compiler(root=None):
    """Make the Deck Compiler importable and return its layout module.

    Resolution order, so that a checkout runs against its own compiler and an installed deployment
    does not silently pick up an unrelated one: an explicit ``root`` argument, the
    ``DECK_COMPILER_ROOT`` environment variable, the compiler vendored next to this package, then the
    plugin cache used by the Codex plugin deployment.
    """
    if root is None:
        root = os.environ.get('DECK_COMPILER_ROOT') or None
    if root is None:
        vendored = Path(__file__).resolve().parents[1]
        if (vendored/'deck_compiler/ir.py').is_file():
            root = vendored
        else:
            paths = list((Path.home()/'.codex/plugins/cache/personal/total-pipe').glob('*/deck_compiler/ir.py'))
            if not paths:
                raise FileNotFoundError('Pass --totalpipe-root or set DECK_COMPILER_ROOT: an installed '
                                        'Deck Compiler is required')
            root = max(paths, key=lambda p: p.stat().st_mtime).parents[1]
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    module = importlib.import_module('deck_compiler.layout')
    if Path(module.__file__).resolve().parent.parent != root:
        raise RuntimeError('A different Deck Compiler is already imported')
    return module


@lru_cache(maxsize=64)
def font(path, size):
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=65536)
def height(text, path, size, width, max_lines=10):
    # Extra width/height allowance is intentionally conservative. It is not a
    # substitute for OfficeCLI's diagnostics or PowerPoint's text renderer.
    from deck_compiler.layout import break_lines
    lines = break_lines(text, font(path, size), max(1, width - 16))
    if len(lines) > max_lines:
        return 10000.0
    return len(lines) * size * 1.4 + 12


def required_height(unit, width, request):
    if unit['role'] == 'figure':
        caption = unit.get('caption', '')
        ch = max(unit.get('caption_height', 62), height(caption, request['font'],
            unit.get('caption_font_floor', 20), width, 2)) if caption else 0
        e = unit.get('min_panel_extent', 220)
        aspect, panels = unit['aspect'], unit.get('panel_count', 1)
        # Contain scaling, retaining the original image aspect and panel count.
        min_h = max(e, e * panels / aspect)
        if width < min_h * aspect:
            return 10000.0
        return min_h + ch + 12
    if request.get('sequence_flow'):
        width -= 56
    label = unit.get('label', '')
    label_box = 40 if request['archetype'] == 'figure-parameters' else 44
    lh = max(label_box, height(label, request['bold_font'], 24, width, 1)) if label else 0
    return lh + height(unit['text'], request['font'], 24, width)


def features(request):
    result = []
    for unit in request['units']:
        required = [min(4., required_height(unit, w, request)/request['region'][3]) for w in WIDTHS]
        result.append(required + [unit.get('aspect', 0)/4, unit.get('panel_count', 0)/6,
            unit.get('min_panel_extent', 0)/380, len(unit.get('text', ''))/600,
            len(unit.get('caption', ''))/180, bool(unit.get('label')),
            request['region'][3]/404, len(request['units'])/MAX_UNITS,
            len(unit.get('label', ''))/80, unit.get('caption_height', 0)/100,
            unit.get('caption_font_floor', 0)/28, unit['role'] == 'figure'])
    return result


def column_width(region_width):
    """Width of one grid column inside a body region."""
    return (region_width-GRID_GAP*(GRID_COLUMNS-1))/GRID_COLUMNS


def span_width(region_width, columns):
    """Width of ``columns`` adjacent grid columns, gutters included."""
    columns = max(1, min(GRID_COLUMNS, int(columns)))
    return columns*column_width(region_width)+GRID_GAP*(columns-1)


def figure_caption_height(unit, width, request):
    caption = unit.get('caption', '') or ''
    if not caption:
        return 0.0
    return max(unit.get('caption_height', 62),
               height(caption, request['font'], unit.get('caption_font_floor', 20), width, 2))


def figure_picture_void(unit, box, request):
    """Fraction of a figure box's picture area that the contain-fitted picture cannot cover.

    The compiler centres the picture inside the proposed rectangle, so a rectangle that is wider or
    taller than the picture shows a band of dead space. Sub-pixel slack is not a defect; a fifth of
    the box being empty is.
    """
    width, box_height = box[2], box[3]
    aspect = unit.get('aspect', 1.0) or 1.0
    area_h = max(1.0, box_height-figure_caption_height(unit, width, request))
    picture_h = min(area_h, width/aspect)
    return 1.0-(picture_h*aspect*picture_h)/(width*area_h)


def figure_box_height(unit, width, request, available):
    """Height of a rectangle that holds the picture plus its caption, or None if it cannot fit.

    The picture keeps its aspect, so the height follows from the width. Returning None lets the
    caller try a narrower column instead of proposing a box the compiler would fill with empty
    space.
    """
    caption = figure_caption_height(unit, width, request)
    aspect = unit.get('aspect', 1.0) or 1.0
    panel_floor = required_height(unit, width, request)-caption-12
    if panel_floor >= 10000:
        return None                      # the width cannot carry the panel floor at all
    needed = max(width/aspect, panel_floor)+caption+12
    return None if needed > available+.5 else needed


def row_groups(request, boxes, tolerance=12.0):
    """Indices of text boxes that sit side by side on one visual row."""
    groups = []
    for index, box in enumerate(boxes):
        if request['units'][index]['role'] == 'figure':
            continue
        for group in groups:
            if abs(box[1]-group[0]) <= tolerance:
                group[1].append(index)
                break
        else:
            groups.append((box[1], [index]))
    return [members for _, members in groups if len(members) >= 2]


def tighten(request, boxes, factor=HUG_FACTOR, pad=HUG_PAD, gap=GRID_GAP):
    """Shrink text boxes to their content, align peer rows, and re-stack each column.

    A proposal that fills the body region is the older behaviour, and it is what makes a box look
    empty: the text is set at its fitted size and the rest of the rectangle stays blank. Three rules
    replace it, and each one is a rule the compiler does not have:

    * every text box is at most ``factor x content + pad`` tall;
    * text boxes that sit side by side share one height, the tallest content in that row, so a card
      row has one baseline instead of a staircase;
    * boxes in one column are re-stacked at 24 px gaps from the column's own top, so the space
      between rows is the grid gutter rather than leftover template slack.

    Figures are left alone: their rectangles are already sized to the picture. Returns None when the
    result would leave the region, so the caller can drop that candidate instead of proposing it.
    """
    units = request['units']
    result = [list(box) for box in boxes]
    for index, unit in enumerate(units):
        if unit['role'] == 'figure':
            continue
        need = required_height(unit, result[index][2], request)
        if need >= 10000:
            return None
        result[index][3] = min(result[index][3], need*factor+pad)
    for group in row_groups(request, result):
        shared = max(result[index][3] for index in group)
        top = min(result[index][1] for index in group)
        for index in group:
            result[index][1] = top
            result[index][3] = shared
    columns = {}
    for index, unit in enumerate(units):
        if unit['role'] == 'figure':
            continue
        columns.setdefault((round(result[index][0], 1), round(result[index][2], 1)), []).append(index)
    bottom_limit = request['region'][1]+request['region'][3]+.5
    for members in columns.values():
        members.sort(key=lambda index: result[index][1])
        cursor = min(result[index][1] for index in members)
        for index in members:
            result[index][1] = cursor
            cursor += result[index][3]+gap
        if cursor-gap > bottom_limit:
            return None
    return result


def read_requests(path, root=None):
    module = compiler(root)
    path = Path(path).resolve()
    ir = json.loads(path.read_text(encoding='utf-8'))
    from deck_compiler.ir import validate
    issues = validate(ir)
    if any(i['severity'] == 'FAIL' for i in issues):
        raise ValueError(json.dumps(issues, ensure_ascii=False))
    layout, compile_issues = module.compile_deck(copy.deepcopy(ir), path.parent)
    if layout is None:
        raise ValueError(json.dumps(compile_issues, ensure_ascii=False))
    requests = []
    spacious = layout.get('deck_frame_variant', module.frame_variant(ir)) == 'spacious'
    for number, slide in enumerate(ir['slides'], 1):
        units = []
        for block in slide['composition']['blocks']:
            units.append({**copy.deepcopy(block), 'role': block['component']})
        for index, ref in enumerate(slide['composition']['figure_refs'], 1):
            asset = layout['assets'][ref['asset_id']]
            units.append({**copy.deepcopy(ref), 'id': f'figure-{index}', 'role': 'figure',
                'aspect': asset['width']/asset['height'], 'asset_sha256': asset['sha256'],
                'member_ids': [f'figure-{index}', f'figure-{index}:caption']})
        top = 236 if spacious else 260
        bottom = 588 if slide['semantic']['caveats'] else 640
        frames = [e for e in layout['slides'][number-1]['elements']
                  if e['id'] in ('title', 'takeaway', 'footer', 'caveats',
                                 'direct-evidence:heading', 'hypothesis:heading')]
        frame_failures = [i for i in compile_issues if i['severity'] == 'FAIL'
                          and i.get('slide') == number and i.get('shape') in
                          ('title', 'takeaway', 'footer', 'caveats')]
        request = {'slide_id': slide['id'], 'archetype': slide['composition']['archetype'],
            'ir_sha256': digest(ir), 'units': units, 'region': [56, top, 1168, bottom-top],
            'sequence_flow': module.sequence_flow(slide['composition']),
            'font': str((path.parent/ir['theme']['font_file']).resolve()),
            'bold_font': str((path.parent/ir['theme']['bold_font_file']).resolve()),
            'font_family': ir['theme']['font_family'], 'frame': frames,
            'frame_failures': frame_failures}
        if len(units) > MAX_UNITS or len({u['id'] for u in units}) != len(units):
            raise ValueError('CAPACITY_OR_ID_COLLISION: no units may be truncated')
        requests.append(request)
    return requests, {'ir_sha256': digest(ir), 'compiler_issues': compile_issues,
        'compiler_sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
        'source': str(path)}


def rhythm_groups(request):
    """Keep peer blocks aligned, including an explicit figure-free process."""
    units = request['units']
    texts = [i for i, unit in enumerate(units) if unit['role'] != 'figure']
    if (request.get('sequence_flow') and request['archetype'] == 'process-flow'
            and len(texts) == 4 and len(units) == 4):
        return [texts]
    if (request['archetype'] == 'figure-parameters' and len(texts) >= 3
            and len(units) - len(texts) == 1):
        return [texts]
    return []


def snap_rhythm(request, boxes):
    """Remove model slack without changing unit identity, order, or source text."""
    result = [list(box) for box in boxes]
    for i, unit in enumerate(request['units']):
        if unit['role'] != 'figure' or not unit.get('caption'):
            continue
        box = result[i]
        caption_h = max(unit.get('caption_height', 62),
                        height(unit['caption'], request['font'],
                               unit.get('caption_font_floor', 20), box[2], 2))
        image_h = min(box[2] / unit['aspect'], box[3] - caption_h - 12)
        if image_h > 0:
            box[3] = image_h + caption_h + 12
    for group in rhythm_groups(request):
        members = [result[i] for i in group]
        if (any(abs(box[0] - members[0][0]) > 4 or
                abs(box[2] - members[0][2]) > 4 for box in members[1:]) or
                any(a[1] >= b[1] for a, b in zip(members, members[1:]))):
            continue
        top = members[0][1]
        bottom = members[-1][1] + members[-1][3]
        gap = 24
        available = bottom - top - gap * (len(group)-1)
        minimums = [required_height(request['units'][index], members[0][2], request)
                    for index in group]
        if available < sum(minimums):
            continue
        equal_height = available / len(group)
        heights = ([equal_height] * len(group) if equal_height >= max(minimums)
                   else [minimum + (available - sum(minimums)) / len(group)
                         for minimum in minimums])
        cursor = top
        for row, index in enumerate(group):
            result[index] = [members[0][0], cursor, members[0][2], heights[row]]
            cursor += heights[row] + gap
    return result


def check(request, boxes):
    errors = []
    units = request['units']
    if len(boxes) != len(units):
        return ['UNIT_COUNT_MISMATCH']
    if request.get('frame_failures'):
        errors.append('FRAME_REQUIRES_COMPILER_REPAIR')
    rx, ry, rw, rh = request['region']
    from deck_compiler.layout import fit_text, intersect
    from deck_compiler.contracts import TextBoxContract
    from deck_compiler.text_flow import select_text_flow, DISTRIBUTED_ARROW_LIST
    for i, (u, b) in enumerate(zip(units, boxes)):
        if len(b) != 4 or not all(math.isfinite(v) for v in b):
            errors.append(f'{u["id"]}:NONFINITE'); continue
        x, y, w, h = b
        if min(w, h) <= 0 or x < rx-.1 or y < ry-.1 or x+w > rx+rw+.1 or y+h > ry+rh+.1:
            errors.append(f'{u["id"]}:BOUNDS')
            continue
        if h + .1 < required_height(u, w, request):
            errors.append(f'{u["id"]}:CONTENT_CAPACITY')
            continue
        if u['role'] == 'figure' and u.get('caption'):
            caption_h = max(u.get('caption_height', 62),
                            height(u['caption'], request['font'],
                                   u.get('caption_font_floor', 20), w, 2))
            if h - caption_h - 12 - w / u['aspect'] > 2:
                errors.append(f'{u["id"]}:FIGURE_CAPTION_SLACK')
        if u['role'] == 'figure' and figure_picture_void(u, b, request) > MAX_FIGURE_VOID:
            errors.append(f'{u["id"]}:FIGURE_VOID')
        if u['role'] != 'figure':
            if u['role'] == 'formula' or u.get('component') == 'formula':
                # A bbox provider cannot size a formula: its height comes from the typeset math, not
                # from character advances, so formula pages stay with the compiler.
                errors.append(f'{u["id"]}:FORMULA_REQUIRES_COMPILER')
            if select_text_flow(u['text'], u.get('text_flow','auto'))['mode'] == DISTRIBUTED_ARROW_LIST:
                errors.append(f'{u["id"]}:TEXT_FLOW_REQUIRES_COMPILER')
            label=u.get('label','')
            lh=(40 if request['archetype']=='figure-parameters' else 44) if label else 0
            inset=56 if request.get('sequence_flow') else 0
            pieces=[(u['text'],[x+inset,y+lh,w-inset,h-lh],request['font'],28,24,10)]
            if label: pieces.append((label,[x,y,w,lh],request['bold_font'],28,24,1))
        else:
            ch=max(u.get('caption_height',62),height(u.get('caption',''),request['font'],u.get('caption_font_floor',20),w,2))
            pieces=[(u.get('caption',''),[x,y+h-ch,w,ch],request['font'],u.get('caption_font_size',22),u.get('caption_font_floor',20),2)]
        for text,box,font_path,size,floor,lines in pieces:
            if not text: continue
            try:
                wrapped,contract=fit_text(text,box,TextBoxContract(request['font_family'],size,font_path,font_floor=floor,max_lines=lines))
                if re.search(r'\d(?:\.\n|\n\.)\d',wrapped):
                    errors.append(f'{u["id"]}:DECIMAL_SPLIT')
                # Two rules taken from real review: nothing below 18 pt, and a last line of one or
                # two characters is an orphan rather than a wrap.
                if contract.font_size < MIN_FONT_PT-.01:
                    errors.append(f'{u["id"]}:FONT_BELOW_MINIMUM')
                rendered=[line for line in wrapped.split('\n') if line.strip()]
                if len(rendered)>1 and len(rendered[-1].strip()) < MIN_LINE_CHARS:
                    errors.append(f'{u["id"]}:ORPHAN_LINE')
            except ValueError:
                errors.append(f'{u["id"]}:COMPILER_TEXT_FIT')
        if any(intersect(b,e['bbox']) for e in request.get('frame',[])):
            errors.append(f'{u["id"]}:FRAME_COLLISION')
        if request['archetype'] == 'evidence-hypothesis':
            if u['role'] == 'direct-evidence' and x+w > 624.1:
                errors.append(f'{u["id"]}:EVIDENCE_ZONE')
            if u['role'] == 'hypothesis' and x < 655.9:
                errors.append(f'{u["id"]}:HYPOTHESIS_ZONE')
        for other in boxes[:i]:
            if min(x+w,other[0]+other[2])-max(x,other[0]) > .5 and min(y+h,other[1]+other[3])-max(y,other[1]) > .5:
                errors.append(f'{u["id"]}:OVERLAP')
    if not errors:
        for group in rhythm_groups(request):
            members = [boxes[i] for i in group]
            gaps = [b[1] - a[1] - a[3] for a, b in zip(members, members[1:])]
            available = members[-1][1] + members[-1][3] - members[0][1] - 24*(len(group)-1)
            equal_feasible = available / len(group) >= max(
                required_height(units[i], members[0][2], request) for i in group)
            if (any(abs(box[0] - members[0][0]) > 2 or
                    abs(box[2] - members[0][2]) > 2 or
                    (equal_feasible and abs(box[3] - members[0][3]) > 2)
                    for box in members[1:]) or
                    any(abs(gap - 24) > 2 for gap in gaps)):
                errors.append('SAME_LEVEL_RHYTHM')
        textual=[(u,b) for u,b in zip(units,boxes) if u['role']!='figure']
        if request['archetype']=='process-flow':
            for (_,a),(_,b) in zip(textual,textual[1:]):
                same_row=abs(a[1]-b[1])<=24
                if (same_row and b[0]<a[0]+a[2]-.5) or (not same_row and b[1]<a[1]+a[3]-.5):
                    errors.append('PROCESS_READING_ORDER')
        if len(textual)==len(units) and request['archetype']!='evidence-hypothesis':
            rows=[]
            for _,b in sorted(textual,key=lambda pair:pair[1][1]):
                if not rows or b[1]-rows[-1][0]>24: rows.append([b[1],1])
                else: rows[-1][1]+=1
            if len({row[1] for row in rows})>1:
                errors.append('UNBALANCED_TEXT_GRID')
    return errors


def templates(request):
    """Generic packing fallback/teacher. No paper-specific IDs or coordinates."""
    units = request['units']; n = len(units)
    if not n:
        yield []; return
    x,y,w,h = request['region']; gap = 24
    figs = [i for i,u in enumerate(units) if u['role']=='figure']
    texts = [i for i in range(n) if i not in figs]
    def stack(indices, region, boxes):
        if not indices: return
        a,b,c,d = region
        # Allocate extra height to longer text, preserving input order/identity.
        mins = [required_height(units[i],c,request) for i in indices]
        extra = (d-gap*(len(indices)-1)-sum(mins))/len(indices)
        cursor = b
        for i,m in zip(indices,mins):
            boxes[i] = [a,cursor,c,m+extra]; cursor += m+extra+gap
    if request['archetype']=='evidence-hypothesis':
        boxes = [None]*n
        for role,a in [('direct-evidence',56),('hypothesis',656)]:
            stack([i for i,u in enumerate(units) if u['role']==role], [a,y+56,568,h-56],boxes)
        if all(b is not None for b in boxes): yield boxes
        return
    if len(figs)==1 and texts:
        right = request['archetype']=='cover-hero'
        # Whole grid columns instead of arbitrary fractions: the gutter is then exactly 24 px and
        # the figure rectangle follows the picture's aspect. A column that cannot hold the picture
        # plus its caption at the panel floor is skipped rather than proposed with dead space.
        for columns in range(3, GRID_COLUMNS-1):
            fw = span_width(w, columns)
            tw = span_width(w, GRID_COLUMNS-columns)
            fh = figure_box_height(units[figs[0]], fw, request, h)
            if fh is None:
                continue
            fx, tx = (x+tw+GRID_GAP, x) if right else (x, x+fw+GRID_GAP)
            boxes=[None]*n; boxes[figs[0]]=[fx,y,fw,fh]
            stack(texts,[tx,y,tw,h],boxes)
            yield boxes
        # A single very wide picture cannot live in a column: give it the full width and put the
        # text in one band underneath, which the grid still expresses exactly.
        k = len(texts)
        if 1 <= k <= 4:
            tw = (w-GRID_GAP*(k-1))/k
            needed = max(required_height(units[i], tw, request) for i in texts)
            fh = figure_box_height(units[figs[0]], w, request, h-needed-GRID_GAP)
            if fh is not None:
                boxes=[None]*n
                boxes[figs[0]]=[x,y,w,fh]
                for j, i in enumerate(texts):
                    boxes[i] = [x+j*(tw+GRID_GAP), y+fh+GRID_GAP, tw, needed]
                yield boxes
    if len(figs)==2:
        # Two cards sharing one row: the shared height is the taller picture need, so both cards
        # line up and neither rectangle is much larger than its picture.
        cw = span_width(w, 6)
        for th in (64,88,112):
            available = h-th-GRID_GAP
            heights = [figure_box_height(units[i], cw, request, available) for i in figs]
            if any(value is None for value in heights):
                continue
            shared = max(heights)
            boxes=[None]*n
            for k,i in enumerate(figs): boxes[i]=[x+k*(cw+GRID_GAP),y+th+GRID_GAP,cw,shared]
            if len(texts)<=2:
                for k,i in enumerate(texts): boxes[i]=[x+k*(cw+GRID_GAP),y,cw,th]
                yield boxes
        return
    if not figs:
        for cols in range(1,min(n,4)+1):
            if n%cols: continue
            rows=math.ceil(n/cols); cw=(w-gap*(cols-1))/cols; ch=(h-gap*(rows-1))/rows
            yield [[x+(i%cols)*(cw+gap),y+(i//cols)*(ch+gap),cw,ch] for i in range(n)]
        # Content-aware two-column alternatives preserve complete rows. Small
        # width changes can prevent decimal breaks without reducing font floors.
        if n%2==0:
            for fraction in (.40,.45,.55,.60):
                widths=[(w-gap)*fraction,(w-gap)*(1-fraction)]
                rows=n//2
                mins=[max(required_height(units[2*k+j],widths[j],request)
                          for j in range(2)) for k in range(rows)]
                extra=(h-gap*(rows-1)-sum(mins))/rows
                boxes=[]; cursor=y
                for k,minimum in enumerate(mins):
                    row_h=minimum+extra
                    for j in range(2):
                        boxes.append([x+(widths[0]+gap if j else 0),cursor,widths[j],row_h])
                    cursor+=row_h+gap
                yield boxes
        boxes=[None]*n; stack(list(range(n)),[x,y,w,h],boxes); yield boxes
    elif not texts:
        yield [[x,y,w,h]]


def quality(request, boxes):
    """Lower is better: empty space inside a box, an empty band inside a figure rectangle, and a
    page that wastes its body area.

    Slack is measured against the hug target rather than the raw content height. Comparing with
    ``required_height`` alone made the fixed 8 px pad look like emptiness, which is proportionally
    larger on short boxes; the scorer then preferred three narrow columns of three lines over three
    full-width single-line rows, because the tall boxes scored "tighter". Figure area carries a
    small bonus so that, once the text boxes are equally tight, the larger panel wins.
    """
    score = 0.
    figures = 0.
    for u, b in zip(request['units'], boxes):
        w, h = b[2:]
        if u['role'] == 'figure':
            score += figure_picture_void(u, b, request) * 2
            figures += w * h
        else:
            target = required_height(u, w, request) * HUG_FACTOR + HUG_PAD
            score += max(0., h - target) / max(h, 1) * 1.5
    rx, ry, rw, rh = request['region']
    return score - figures / max(rw * rh, 1) * .25


def teacher(request):
    """Best valid proposal for one slide, or None when nothing survives the gates."""
    valid = []
    for candidate in templates(request):
        snapped = snap_rhythm(request, candidate)
        for proposal in (snapped, tighten(request, snapped)):
            if proposal is None or check(request, proposal):
                continue
            if proposal not in valid:
                valid.append(proposal)
    return min(valid,key=lambda b:quality(request,b)) if valid else None
