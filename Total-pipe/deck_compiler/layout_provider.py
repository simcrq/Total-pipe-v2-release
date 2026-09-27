"""Opt-in v26 body proposals. Canonical content and final writer stay in the compiler."""
import copy
import json
from pathlib import Path

from .contracts import digest, file_hash, issue
from .layout import compile_deck

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / 'models/totalpipe_content_v26.pt'
MODEL_SHA256 = 'ab306795c73c8c6888889e78aadc2acd0bc799eee9614af67b0e1f865f5d050c'


def compile_v26(ir_path, checkpoint=None, candidates=32, seed=20261007):
    """Build proposals in memory, then use the compiler's own element emitters."""
    if not 1 <= candidates <= 256:
        raise ValueError('layout candidates must be between 1 and 256')
    ir_path = Path(ir_path)
    ir = json.loads(ir_path.read_text(encoding='utf-8'))
    baseline, baseline_issues = compile_deck(ir, ir_path.parent)
    if baseline is None:
        return baseline, baseline_issues
    path = Path(checkpoint) if checkpoint else CHECKPOINT
    if file_hash(path) != MODEL_SHA256:
        raise ValueError('v26 checkpoint SHA-256 mismatch')
    # Optional dependencies are imported only on the v26 path. The deterministic
    # compiler continues to run without torch or model weights.
    import torch
    from layoutdiffusion_demo.config import DemoConfig
    from totalpipe_layout.contracts import read_requests, check, teacher, quality, height
    from totalpipe_layout.data import tensors, decode
    from totalpipe_layout.model import ContentDenoiser, sample
    requests, _ = read_requests(ir_path, ROOT)
    with torch.serialization.safe_globals([torch.torch_version.TorchVersion]):
        data = torch.load(path, map_location='cpu', weights_only=True)
    if data['training']['kind'] != 'totalpipe-content-proposal-v1':
        raise ValueError('Unsupported layout checkpoint contract')
    cfg = DemoConfig(**data['config'])
    # Constructing a module also consumes RNG; preserve the embedding caller's state.
    with torch.random.fork_rng(devices=[]):
        model = ContentDenoiser(cfg)
    model.load_state_dict(data['model'], strict=True)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device).eval()
    proposals = {}
    records = []
    for index, request in enumerate(requests):
        valid = []
        if request['units']:
            batch = tensors([request] * candidates, cfg, device)
            tokens = sample(model, batch, seed + index).cpu().tolist()
            for token in tokens:
                boxes = decode(request, token, cfg.num_bins)
                if not check(request, boxes):
                    valid.append(boxes)
        chosen = min(valid, key=lambda b: quality(request, b)) if valid else teacher(request)
        status = 'MODEL_PROPOSAL' if valid else 'PACKING_FALLBACK'
        if chosen is None or not request['units']:
            status = 'COMPILER_FALLBACK'
        else:
            if check(request, chosen):
                raise ValueError('Provider selected an invalid candidate')
            units = {}
            for unit, box in zip(request['units'], chosen):
                entry = {'bbox': box}
                if unit['role'] == 'figure':
                    entry['caption_height'] = max(unit.get('caption_height', 62),
                        height(unit.get('caption', ''), request['font'],
                               unit.get('caption_font_floor', 20), box[2], 2)) if unit.get('caption') else 0
                units[unit['id']] = entry
            proposals[request['slide_id']] = {'units': units, 'status': status}
        records.append({'slide_id': request['slide_id'], 'status': status,
                        'valid_candidates': len(valid), 'candidate_count': candidates,
                        'seed': seed + index, 'request_sha256': digest(request)})
    result, findings = compile_deck(ir, ir_path.parent, proposals=proposals)
    # Never discard a compiler failure. Retry only affected provider pages using
    # the existing deterministic compiler; any remaining FAIL still blocks build.
    rejected = {f.get('slide') for f in findings if f['severity'] == 'FAIL'}
    for number in rejected:
        if isinstance(number, int) and 1 <= number <= len(records):
            sid = records[number-1]['slide_id']
            if sid in proposals:
                proposals.pop(sid)
                records[number-1].update(status='COMPILER_FALLBACK',
                    rejected_rules=[f['rule'] for f in findings if f.get('slide') == number and f['severity'] == 'FAIL'])
    if rejected:
        result, findings = compile_deck(ir, ir_path.parent, proposals=proposals)
    if result:
        provenance = {'name': 'v26-experiment', 'checkpoint_sha256': MODEL_SHA256,
            'checkpoint_step': data['training']['completed_steps'], 'device': device,
            'seed': seed, 'candidates': candidates, 'ir_sha256': digest(ir), 'slides': records,
            'source_sha256': {str(p.relative_to(ROOT)): file_hash(p) for p in
                [Path(__file__), ROOT/'deck_compiler/layout.py',
                 *sorted((ROOT/'totalpipe_layout').glob('*.py')),
                 *sorted((ROOT/'layoutdiffusion_demo').glob('*.py'))]}}
        result['layout_provider'] = provenance
        for n, record in enumerate(records, 1):
            findings.append(issue('LAYOUT_PROVIDER', 'INFO', record['status'], n,
                                  detector='layout-provider', provider='v26',
                                  valid_candidates=record['valid_candidates']))
    return result, findings
