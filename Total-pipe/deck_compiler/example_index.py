"""Search and summarize example library metadata shared by CLI, design, IR and PageScene prompts."""
import json
from pathlib import Path
import re


LIBRARY = Path(__file__).resolve().parents[1] / 'examples/library'
_CJK_SPAN = re.compile(r'[\u4e00-\u9fff]{2,}')

# Common presentation-intent synonyms so unspaced natural Chinese/English queries still hit.
_INTENT_HINTS = (
    (r'对比|对照|比较|差异|优劣|正反|双路线|两套|vs\b|versus|compar|contrast|a/b', '对照路线 架构对比 双路线 机制对照表'),
    (r'流程|步骤|阶段|管线|架构|系统|pipeline|workflow|process|stage|step|architecture', '流程图 阶段对齐 机制替换 双泳道'),
    (r'公式|方程|推导|恒等式|收敛|定律|数学|equation|formula|math|deriv|converg', '原生公式 独立公式 符号定义 曲线与公式'),
    (r'原图|读图|面板|实验图|figure|fig\.|panel|readout|microscop|spectrum', '原图导读 图文并排 原图与表格'),
    (r'曲线|折线|散点|误差|标准差|分布|数据图|趋势|chart|plot|curve|scatter|error|dumbbell', '数据图 折线图 误差棒 对数散点 配对哑铃图'),
    (r'表格|矩阵|参数|指标|汇总|table|matrix|metric|benchmark|parameter', '对照表 合并表头 科研表格 二维对照矩阵'),
    (r'机制|假设|因果|抑制|激活|原理|mechanism|hypothesis|causal|inhibit|feedback', '机制图 机制假设 综合科研页'),
    (r'类比|定义|概念|因素|直观|通俗|科普|入门|analogy|definition|concept|factor|intuiti', '定义 类比 多因素 双中心'),
    (r'剖面|结构|回路|电路|波形|采样|信号|cross.section|circuit|wave|signal|alias', '材料剖面 波形时间尺 采样混叠 电路示意'),
)


def inventory():
    return json.loads((LIBRARY / 'index.json').read_text(encoding='utf-8'))['entries']


def _tokens(query):
    """Extract alphanumeric words plus CJK 2/3-grams so unspaced Chinese queries match."""
    query = query.casefold().strip()
    words = set(re.findall(r'[a-z0-9][a-z0-9_/-]*', query))
    for span in _CJK_SPAN.findall(query):
        words.add(span)
        for n in (2, 3):
            if len(span) >= n:
                for i in range(len(span) - n + 1):
                    words.add(span[i:i + n])
    return words


def _expanded_query(query):
    extras = [hint for pattern, hint in _INTENT_HINTS if re.search(pattern, query, re.I)]
    return f'{query} {" ".join(extras)}' if extras else query


def search(query, entries, limit):
    raw_query = (query or '').casefold().strip()
    if not raw_query:
        return []
    expanded = _expanded_query(raw_query).casefold()
    raw_words = _tokens(raw_query)
    expanded_words = _tokens(expanded)
    matches = []
    for entry in entries:
        aliases = [entry['id'].casefold(), *(tag.casefold() for tag in entry['tags'])]
        exact = sum(alias in raw_words or alias == raw_query for alias in aliases)
        partial = sum(alias in raw_query for alias in aliases if alias not in raw_words)
        intent_hits = sum(alias in expanded_words or alias in expanded for alias in aliases) - exact - partial
        description = (entry['title'] + ' ' + entry['summary']).casefold()
        contextual = sum(word in description for word in raw_words if len(word) >= 2)
        tag_score = 10 * exact + 5 * partial + 2 * max(0, intent_hits)
        # Require either an explicit tag/intent match or >=2 contextual hits so a single stray
        # generic word (e.g. "目标" on an opening slide) never produces noise.
        score = tag_score + contextual if (tag_score > 0 or contextual >= 2) else 0
        if score > 0:
            matches.append((score, entry))
    ranked = sorted(matches, key=lambda item: (-item[0], item[1]['id']))
    return [{
        'id': entry['id'],
        'title': entry['title'],
        'summary': entry['summary'],
        'script': str(LIBRARY / entry['script']),
    } for _, entry in ranked[:limit]]


def catalog_brief(entries=None):
    """Compact summary of every library example for direct inclusion in design/scene prompts."""
    items = entries if entries is not None else inventory()
    return [
        {
            'id': entry['id'],
            'title': entry['title'],
            'tags': list(entry.get('tags') or [])[:5],
            'summary': entry['summary'],
        }
        for entry in items
    ]


def suggest_for_text(text, entries=None, limit=3):
    """Suggest matching library examples for a design brief, Story excerpt, or topic."""
    items = entries if entries is not None else inventory()
    hits = search(text or '', items, limit=limit)
    if len(hits) < limit:
        seen = {item['id'] for item in hits}
        # Fill remaining slots with high-craft multi-zone reference compositions instead of empty [].
        defaults = ('comparison-lanes', 'figure-readout', 'directional-notes',
                    'equation-explainer', 'definition-factor-analogy', 'rc-discharge-composite')
        by_id = {entry['id']: entry for entry in items}
        for eid in defaults:
            if eid in by_id and eid not in seen:
                entry = by_id[eid]
                hits.append({
                    'id': entry['id'],
                    'title': entry['title'],
                    'summary': entry['summary'],
                    'script': str(LIBRARY / entry['script']),
                })
                seen.add(eid)
                if len(hits) >= limit:
                    break
    return hits[:limit]
