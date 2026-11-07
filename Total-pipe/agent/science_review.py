"""Actual source review of atomic science, before paying for page design."""
from pathlib import Path

from . import COMPONENT
from .state import read, sha, write

SCHEMA = COMPONENT/'agent/schemas/scientific-review.schema.json'
CHECKS = ('evidence_fidelity', 'atomic_scope', 'essential_conditions')


class ReviewRejected(ValueError):
    pass


def validate(work, value):
    work = Path(work)
    from pwf2rpa.content_contract import catalog, validate_contract
    story = read(work/'story_plan.json')
    if validate_contract(story, required_version='2.0'):
        raise ValueError('Scientific review requires a valid atomic Story 2.0')
    workflow = Path(read(work/'evidence_pointer.json')['workflow'])
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'method', 'reviewer', 'story_sha256', 'workflow_sha256', 'coverage', 'decisions'}
            or value.get('schema_version') != '1.0' or value.get('method') != 'agent-source-review'
            or not isinstance(value.get('reviewer'), str) or not value['reviewer'].strip()
            or value.get('story_sha256') != sha(work/'story_plan.json') or value.get('workflow_sha256') != sha(workflow)):
        raise ValueError('Scientific review needs a reviewer and current Story/workflow hashes')
    units, seen, failures = catalog(story), [], []
    def check(record, location):
        if (not isinstance(record, dict) or set(record) != {'status', 'note'} or record.get('status') not in ('pass', 'fail')
                or not isinstance(record.get('note'), str) or not record['note'].strip()):
            raise ValueError(location+' requires an actual status and concrete source-review note')
        if record['status'] == 'fail': failures.append(location+': '+record['note'])
    check(value['coverage'], 'coverage')
    decisions = value['decisions']
    if not isinstance(decisions, list) or not decisions:
        raise ValueError('Review concrete scientific topics and cover every unit explicitly')
    ids = set()
    for item in decisions:
        if (not isinstance(item, dict) or set(item) != {'id', 'unit_refs', 'checks'}
                or not isinstance(item['id'], str) or not item['id'].strip() or item['id'] in ids
                or not isinstance(item['unit_refs'], list) or not item['unit_refs']
                or any(not isinstance(r, str) or r not in units for r in item['unit_refs'])
                or not isinstance(item['checks'], dict) or set(item['checks']) != set(CHECKS)):
            raise ValueError('Each scientific topic needs a unique ID, known unit_refs and every check')
        ids.add(item['id'])
        seen += item['unit_refs']
        for key in CHECKS: check(item['checks'][key], item['id']+' '+key)
    if set(seen) != set(units) or len(seen) != len(set(seen)):
        raise ValueError('Every scientific unit must be explicitly reviewed exactly once, grouped by scientific topic')
    if failures:
        raise ReviewRejected('Scientific source review rejected: '+'; '.join(failures))


def binding(work):
    work = Path(work)
    value = read(work/'scientific_review.json')
    validate(work, value)
    return {'scientific_review_sha256': sha(work/'scientific_review.json'), 'workflow_sha256': value['workflow_sha256']}


def prepare(work, request):
    work = Path(work)
    workflow = Path(read(work/'evidence_pointer.json')['workflow'])
    story, flow = read(work/'story_plan.json'), read(workflow)
    from pwf2rpa.content_contract import catalog
    write(work/'scientific_review_prompt.json', {
        'schema_path': str(SCHEMA), 'story_sha256': sha(work/'story_plan.json'), 'workflow_sha256': sha(workflow),
        'story': story, 'scientific_units': catalog(story), 'evidence': flow['evidence_registry'],
        'workflow_root': str(workflow.parent), 'supplementary_paths': request.get('supplementary_paths', []),
        'instructions': 'Actually compare the full paper, figures and supplied SI with this ledger before page design. '
        'Review every unit, grouped into concrete scientific topics. Judge completeness of essential prerequisites, controls, '
        'negative results, uncertainty and source discrepancies; record missing facts even if no unit represents them. '
        'Every assertion must be independently limitable. A mixed paragraph or a qualifier cascade must fail. '
        'Do not mechanically mark pass, reuse the planner self-review, or count file availability as source reading. '
        'Failures replan Story; no page-design invocation or IR can bypass this review.'})
    (work/'scientific_review_task.md').write_text(
        '# 原子科学记录源审读\n\n主 Agent 完整读取 scientific_review_prompt.json、Schema、原文和实际SI。'
        '逐个覆盖全部科学单元，可按真实科学主题分组，实际检查证据忠实性、独立可限定性和必要条件。'
        'coverage 须审查原文中未进入 ledger 的重要条件/对照/负面结果与矛盾，不能只查已有单元。'
        '每项给具体说明；禁止自动 pass 或复用规划者自评。写 scientific_review.json；失败回退 Story。\n', encoding='utf-8')
    return [work/'scientific_review_prompt.json', work/'scientific_review_task.md']
