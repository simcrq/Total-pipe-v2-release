"""Explicit source/copy review, separate from design authorship and native visual review."""
from pathlib import Path
import re

from . import COMPONENT
from .state import read, sha, write

SCHEMA = COMPONENT/'agent/schemas/page-design-review.schema.json'
CHECKS = ('scientific_fidelity', 'qualifier_scope', 'audience_copy')


class ReviewRejected(ValueError):
    """An actual failed scientific/copy check requires design revision, not form repair."""


def binding(work, value=None):
    work = Path(work)
    value = read(work/'page_design_review.json') if value is None else value
    validate(work, value)
    result = {'story_sha256': sha(work/'story_plan.json'), 'design_sha256': sha(work/'page_design.json'),
            'review_sha256': sha(work/'page_design_review.json'), 'reviewer': value['reviewer'],
            'method': value['method']}
    if (read(work/'story_plan.json').get('content_contract') or {}).get('version') == '2.0':
        from .science_review import binding as science_binding
        result.update(science_binding(work))
    return result


def validate(work, value):
    work = Path(work)
    fields = {'schema_version', 'method', 'reviewer', 'story_sha256', 'design_sha256', 'pages'}
    if (not isinstance(value, dict) or set(value) != fields or value.get('schema_version') != '1.0' or
            value.get('method') != 'agent-source-review' or not isinstance(value.get('reviewer'), str) or
            not value['reviewer'].strip()):
        raise ValueError('Review requires schema_version=1.0, method=agent-source-review, reviewer, hashes and pages.')
    for key, name in (('story_sha256', 'story_plan.json'), ('design_sha256', 'page_design.json')):
        if not isinstance(value[key], str) or not re.fullmatch('[a-f0-9]{64}', value[key]) or value[key] != sha(work/name):
            raise ValueError('Source/copy review is stale: '+key)
    pages = value['pages']
    ids = [page['id'] for page in read(work/'page_design.json')['pages']]
    if (not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages) or
            [page.get('id') for page in pages] != ids):
        raise ValueError('Review every page explicitly in approved order; no all/omitted/duplicate page IDs.')
    for page in pages:
        if set(page) != {'id', 'checks'} or not isinstance(page['checks'], dict) or set(page['checks']) != set(CHECKS):
            raise ValueError('Every review page needs all source/copy checks.')
        for key, check in page['checks'].items():
            if (not isinstance(check, dict) or set(check) != {'status', 'note'} or
                    check.get('status') not in ('pass', 'fail') or not isinstance(check.get('note'), str) or not check['note'].strip()):
                raise ValueError('Each review check requires status=pass|fail and a concrete note.')
            if check['status'] == 'fail':
                raise ReviewRejected(f'{page["id"]} {key} rejected: {check["note"]}')


def prepare(work):
    from deck_compiler.design import content_bindings
    work = Path(work)
    source = read(work/'page_design_prompt.json')
    design, story = read(work/'page_design.json'), read(work/'story_plan.json')
    prompt = {'schema_path': str(SCHEMA), 'story_sha256': sha(work/'story_plan.json'),
              'design_sha256': sha(work/'page_design.json'), 'request': source.get('request', {}),
              'scientific_records': content_bindings(story), 'pages': design['pages'],
              'evidence': source.get('evidence', {}), 'figures': source.get('figures', []),
              'workflow_root': source.get('workflow_root'),
              'checks': list(CHECKS),
              'instructions': 'The orchestrator must actually compare every approved display copy and visual locator '
                              'with scientific records and cited evidence. Do not reuse the designer\'s self-attestation. '
                              'Check causal strength, observation vs interpretation, numerical/condition scope, important '
                              'controls and negative findings. Read only the audience copy to check objects, referents, '
                              'reasoning steps and production-note leakage. Fail and replan page_design on any mismatch. '
                              'For audience_copy, also judge communication, not only truth: a result page must lead with a finding, '
                              'not a disclaimer. Fail visible copy that stacks audit boilerplate ("authors claim", "not verified", '
                              '"only", "cannot", "not a ranking") or repeats a scope caveat on page after page; a genuine limitation '
                              'belongs once on a dedicated boundary page or in speaker notes, unless omitting it would make that '
                              'page claim false. For every page with a paper figure, fail if no visible caption/label tells the '
                              'viewer which panels, axes/conditions and feature to read; a caption that merely repeats the title '
                              'or warns about evidence does not pass. Use explicit per-page notes; do not generate automatic pass '
                              'records. This is source/copy review before implementation; rendered-page readability and PowerPoint '
                              'review remain separate.'}
    write(work/'page_design_review_prompt.json', prompt)
    task = ('# 页面源文案审读\n\n由主 Agent 实际审读，不调用设计者自动签收。完整读取 '
            '`work/page_design_review_prompt.json` 与 schema_path。对照科学记录和证据逐页检查 scientific_fidelity、'
            'qualifier_scope、audience_copy，尤其检查观察/解释、适用条件、对照和负面结果。只读投屏文案再判断'
            '观众是否能理解对象、方法、证据和论点。给出每页具体检查说明，不生成模板化 pass。\n\n'
            'audience_copy 同时判断“像不像组会讲解”，不只判断真假：结果页要以发现开头，不能以“作者主张/未验证/仅/'
            '不能/并非排名”等防御句占据主文案；真实局限放在一页边界或讲稿，除非删掉就会让本页主张失真。'
            '有论文图的页面必须有一句可见的读图说明：看哪几个面板、什么轴/条件、哪个特征、说明什么；只重复标题'
            '或只提醒证据不足不算通过。\n\n'
            '写 `work/page_design_review.json`，绑定当前 story/design 哈希。发现问题填 fail，工具将退回页面设计；'
            '不改科学内容来迁就文案。这个记录不代表已看渲染图或已完成 PowerPoint 验收。\n')
    (work/'page_design_review_task.md').write_text(task, encoding='utf-8')
    return [work/'page_design_review_prompt.json', work/'page_design_review_task.md']
