"""Cheap conservative opportunity screening, before any agent-authored decision."""
import re

from .specs import TEMPLATES

CUES = {
    TEMPLATES[0]: re.compile(r'剥离角|peel(?:ing)?\s+angle', re.I),
    TEMPLATES[1]: re.compile(r'层叠|叠层|从上到下|自上而下|top.to.bottom|layer\s+stack', re.I),
    TEMPLATES[2]: re.compile(r'步骤|流程|先.{1,100}再|→|->|process|steps?', re.I),
}
SUMMARY = re.compile(r'^(?:目录|参考文献|结论|总结|致谢|contents|references|conclusions?|summary)\b', re.I)


def candidates(semantics):
    if semantics['archetype'] in ('cover', 'cover-hero', 'three-conclusions', 'three-limitations'):
        return [], 'summary_page'
    if SUMMARY.search(semantics['title']):
        return [], 'summary_page'
    if semantics['existing_visuals']:
        return [], 'existing_visual'
    content = '\n'.join(semantics['facts'].values())
    templates = [name for name, pattern in CUES.items() if pattern.search(content)]
    return templates, 'candidate' if templates else 'no_explanatory_relation'
