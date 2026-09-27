"""Read-only Deck IR bridge and conservative content gates, in CSS pixels.

Blocks and figure/caption pairs are atomic units. The canonical IR is never
rewritten. A proposal is an optional body layout, not compiler/native approval.
"""
import copy
import hashlib
import importlib
import json
import math
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


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def compiler(root=None):
    if root is None:
        paths = list((Path.home()/'.codex/plugins/cache/personal/total-pipe').glob('*/deck_compiler/ir.py'))
        if not paths:
            raise FileNotFoundError('Pass --totalpipe-root: installed Deck Compiler v2 required')
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
    label = unit.get('label', '')
    lh = max(44, height(label, request['bold_font'], 24, width, 1)) if label else 0
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
    for number, slide in enumerate(ir['slides'], 1):
        units = []
        for block in slide['composition']['blocks']:
            units.append({**copy.deepcopy(block), 'role': block['component']})
        for index, ref in enumerate(slide['composition']['figure_refs'], 1):
            asset = layout['assets'][ref['asset_id']]
            units.append({**copy.deepcopy(ref), 'id': f'figure-{index}', 'role': 'figure',
                'aspect': asset['width']/asset['height'], 'asset_sha256': asset['sha256'],
                'member_ids': [f'figure-{index}', f'figure-{index}:caption']})
        spacious = slide['presentation'].get('variant') == 'spacious'
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
        if u['role'] != 'figure':
            if select_text_flow(u['text'], u.get('text_flow','auto'))['mode'] == DISTRIBUTED_ARROW_LIST:
                errors.append(f'{u["id"]}:TEXT_FLOW_REQUIRES_COMPILER')
            label=u.get('label',''); lh=44 if label else 0
            pieces=[(u['text'],[x,y+lh,w,h-lh],request['font'],28,24,10)]
            if label: pieces.append((label,[x,y,w,44],request['bold_font'],28,24,1))
        else:
            ch=max(u.get('caption_height',62),height(u.get('caption',''),request['font'],u.get('caption_font_floor',20),w,2))
            pieces=[(u.get('caption',''),[x,y+h-ch,w,ch],request['font'],u.get('caption_font_size',22),u.get('caption_font_floor',20),2)]
        for text,box,font_path,size,floor,lines in pieces:
            if not text: continue
            try:
                wrapped,_=fit_text(text,box,TextBoxContract(request['font_family'],size,font_path,font_floor=floor,max_lines=lines))
                if re.search(r'\d(?:\.\n|\n\.)\d',wrapped):
                    errors.append(f'{u["id"]}:DECIMAL_SPLIT')
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
        for frac in (.42,.48,.54,.60,.66):
            fw=(w-gap)*frac; tw=w-gap-fw
            fx,tx = (x+tw+gap,x) if right else (x,x+fw+gap)
            boxes=[None]*n; boxes[figs[0]]=[fx,y,fw,h]
            stack(texts,[tx,y,tw,h],boxes)
            yield boxes
    if len(figs)==2:
        for th in (64,88,112):
            boxes=[None]*n; cw=(w-gap)/2
            for k,i in enumerate(figs): boxes[i]=[x+k*(cw+gap),y+th+gap,cw,h-th-gap]
            if len(texts)<=2:
                for k,i in enumerate(texts): boxes[i]=[x+k*(cw+gap),y,cw,th]
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
    # Prefer larger scientific panels and balanced text slack; hard gates first.
    score=0.
    for u,b in zip(request['units'],boxes):
        w,h=b[2:]
        if u['role']=='figure':
            ch=max(u.get('caption_height',62),height(u.get('caption',''),request['font'],u.get('caption_font_floor',20),w,2))
            panel=min(w/u['aspect'],h-ch-12)
            score -= min(panel,panel*u['aspect']/u.get('panel_count',1))/100
        else:
            score += abs(h-required_height(u,w,request))/max(h,1)*.2
    return score


def teacher(request):
    valid = [b for b in templates(request) if not check(request,b)]
    return min(valid,key=lambda b:quality(request,b)) if valid else None
