"""Synthetic contract curriculum. Real Deck IR is evaluation-only."""
import random
import math
import torch
from .contracts import (ARCHETYPES, ROLES, WIDTHS, MAX_UNITS, FEATURES, features,
                        teacher, check, digest)

TRAIN_WORDS = 'measured response reference sample control field energy parameter uncertainty observation mechanism signal structure effect'.split()
TEST_WORDS = 'spectral boundary transport interface stability displacement symmetry threshold orientation relaxation experiment calculation'.split()


def tensors(requests, cfg, device='cpu'):
    b=len(requests); n=cfg.max_elements
    labels=torch.zeros(b,n,dtype=torch.long)
    mask=torch.zeros(b,n,dtype=torch.bool)
    feats=torch.zeros(b,n,FEATURES)
    roles=torch.zeros(b,n,dtype=torch.long)
    arch=torch.tensor([ARCHETYPES.index(r['archetype']) for r in requests])
    for i,r in enumerate(requests):
        count=len(r['units'])
        if not 0<count<=n: raise ValueError('EMPTY_OR_OVER_CAPACITY_REQUEST')
        labels[i,:count]=torch.tensor([3 if u['role']=='figure' else 2 for u in r['units']])
        mask[i,:count]=True
        feats[i,:count]=torch.tensor(features(r))
        roles[i,:count]=torch.tensor([ROLES.index(u['role']) for u in r['units']])
    return tuple(t.to(device) for t in (labels,mask,feats,roles,arch))


def encode(request, boxes, bins=64):
    rx,ry,rw,rh=request['region']; k=bins-1
    # Quantize edges jointly so teacher boxes stay within the region.
    rows=[]
    for x,y,w,h in boxes:
        a,b,c,d=math.ceil((x-rx)/rw*k-1e-8),math.ceil((y-ry)/rh*k-1e-8),math.floor((x+w-rx)/rw*k+1e-8),math.floor((y+h-ry)/rh*k+1e-8)
        rows.append([a,b,c-a,d-b])
    return rows


def decode(request, tokens, bins=64):
    rx,ry,rw,rh=request['region']; k=bins-1
    return [[rx+a/k*rw,ry+b/k*rh,c/k*rw,d/k*rh] for a,b,c,d in tokens[:len(request['units'])]]


def curriculum(count, seed, font, bold_font, split='train'):
    rng=random.Random(seed); result=[]; attempts=0
    words=TRAIN_WORDS if split=='train' else TEST_WORDS
    chinese='测量响应对照样品能量参数不确定性结构信号' if split=='train' else '界面输运边界应变稳定性计算实验阈值'
    def sentence(lo,hi):
        length=rng.randint(lo,hi)
        if rng.random()<.2: return ''.join(rng.choices(chinese,k=length*3))+'。'
        return ' '.join(rng.choices(words,k=length)).capitalize()+'.'
    while len(result)<count:
        attempts+=1
        if attempts>count*100: raise RuntimeError(f'Curriculum rejection rate too high at {len(result)}: {ARCHETYPES[len(result)%9]}')
        arch=ARCHETYPES[len(result)%len(ARCHETYPES)]
        n=rng.randint(1,4); nf=0
        if arch=='cover-hero': n=rng.randint(1,2); nf=1
        if arch=='figure-parameters': n=rng.randint(1,3); nf=1
        if arch=='process-flow': nf=int(rng.random()<.5)
        if arch in ('hero-dual-evidence','dual-demonstration'): n=rng.randint(0,2); nf=2
        if arch in ('three-limitations','three-conclusions'): n=rng.randint(1,3)
        if arch=='evidence-hypothesis': n=rng.randint(2,8)
        units=[]
        for i in range(n):
            role={'process-flow':'process-step','three-limitations':'limitation','three-conclusions':'conclusion'}.get(arch,'body')
            if arch=='evidence-hypothesis': role='direct-evidence' if i%2==0 else 'hypothesis'
            if role=='body': role=rng.choice(ROLES[:-1])
            # Dual figures reserve most of the vertical area, hence brief callouts.
            maxwords=5 if nf==2 else (12 if n>=4 else 24)
            units.append({'id':f'block-{i}','role':role,'text':sentence(2,maxwords),
                          'label':rng.choice(['','Result','Control','Evidence']), 'text_flow':'plain'})
        for i in range(nf):
            units.append({'id':f'figure-{i+1}','role':'figure','aspect':rng.uniform(.85,2.3),
                'panel_count':rng.choice([1,1,1,2]),'min_panel_extent':220,
                'caption':f'Fig. {i+1}. '+sentence(2,7),'caption_height':62,
                'caption_font_floor':20,'source_figure':str(i+1),'asset_id':f'synthetic-{i}',
                'member_ids':[f'figure-{i+1}',f'figure-{i+1}:caption']})
        r={'slide_id':f'{split}-{len(result)}','archetype':arch,'units':units,
           'region':[56,rng.choice([236,260]),1168,rng.choice([328,352,380,404])],
           'font':font,'bold_font':bold_font,'font_family':'Microsoft YaHei',
           'frame':[],'frame_failures':[]}
        # Body must end before the standard footer/caveat frame.
        r['region'][3]=min(r['region'][3],640-r['region'][1])
        boxes=teacher(r)
        if boxes is None: continue
        tok=encode(r,boxes)
        if check(r,decode(r,tok)): continue
        result.append({'request':r,'tokens':tok,'signature':digest([arch,units,r['region']])})
    return result,attempts
