"""Compiler-to-planner JSON feedback. No planner calls or automatic scientific edits."""
from .contracts import digest


def make_feedback(ir, layout, items):
    slides = []
    pages = ir.get('slides', []) if isinstance(ir, dict) else []
    for number, slide in enumerate(pages if isinstance(pages, list) else [], 1):
        findings = [i for i in items if i.get('slide') in (None, number)]
        errors = []
        for item in findings:
            if item['severity'] not in ('FAIL', 'REVIEW'):
                continue
            source = item.get('source', {})
            errors.append({'code': item['rule'], 'severity': item['severity'],
                'component': source.get('component', item.get('shape') or 'slide'),
                'message': item['message'],
                **{key: source[key] for key in ('required_size_px', 'available_size_px',
                    'measurement', 'cause', 'suggested_actions', 'underfill_px',
                    'underfill_ratio', 'suggested_weights') if key in source}})
        has_fail = any(e['severity'] == 'FAIL' for e in errors)
        slides.append({'slide_id': slide.get('id', f'invalid-slide-{number}') if isinstance(slide, dict) else f'invalid-slide-{number}',
            'status': 'layout_failed' if has_fail else 'needs_review' if errors else 'compiled',
            'errors': errors,
            'suggested_actions': sorted({action for e in errors for action in e.get('suggested_actions', [])})})
    return {'version': '1.0', 'ir_sha256': digest(ir), 'geometry_generated': layout is not None,
            'slides': slides, 'retry_owner': 'skill_or_caller', 'automatic_retries': 0}
