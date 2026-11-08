"""Normalize presentation labels before a request reaches a component."""
import re


PRESENTATION_TYPES = ('group_meeting', 'journal_club', 'proposal', 'progress_report',
                      'defense', 'paper_presentation', 'custom')
_ALIASES = {
    'group meeting': 'group_meeting', 'lab meeting': 'group_meeting',
    '组会': 'group_meeting', '研究生组会': 'group_meeting',
    'journal club': 'journal_club', 'research sharing': 'journal_club',
    '文献分享': 'journal_club', '文献汇报': 'journal_club', '文献研读': 'journal_club',
    'proposal': 'proposal', '开题': 'proposal', '开题报告': 'proposal',
    'progress report': 'progress_report', '进展汇报': 'progress_report',
    'defense': 'defense', '答辩': 'defense',
    'paper presentation': 'paper_presentation', 'research report': 'paper_presentation',
    'seminar': 'paper_presentation', 'conference': 'paper_presentation',
    '科研汇报': 'paper_presentation', '论文汇报': 'paper_presentation',
    '会议': 'paper_presentation', '会议报告': 'paper_presentation',
    'custom': 'custom', '自定义': 'custom',
    # RPA has no lecture/pitch blueprint. Preserve the original room in the prompt,
    # and use its custom blueprint rather than silently changing that occasion.
    'lecture': 'custom', '讲课': 'custom', '课程': 'custom', '教学': 'custom',
    'commercial': 'custom', 'pitch': 'custom', '路演': 'custom', '商业路演': 'custom',
}


def _parts(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('presentation_type is required')
    # Accept a recognized label followed by context, not arbitrary substring matches.
    # For example: 研究生组会，面向本领域研究生，约30分钟。
    parts = re.split(r'[,，;；:：。]', value.strip(), maxsplit=1)
    label = parts[0].strip().casefold()
    label = re.sub(r'[_\-\s]+', ' ', label)
    return label, parts[1].strip() if len(parts) > 1 else ''


def presentation_type(value):
    label, _ = _parts(value)
    canonical = _ALIASES.get(label)
    if canonical is None:
        raise ValueError('Unsupported presentation_type; use '+', '.join(PRESENTATION_TYPES)
                         +' or a documented occasion alias. Put audience and duration in requirements.')
    return canonical


def request_identity(request):
    """Compare aliases without migrating an existing request or its authorization.

    Preserve descriptions and distinguish lectures from pitches even though both
    use RPA's custom blueprint. All other request fields must remain identical.
    """
    value = dict(request)
    value.setdefault('explain_viz_mode', 'auto')
    value.setdefault('page_mode', 'deck_ir')
    canonical = presentation_type(value['presentation_type'])
    context = value.pop('presentation_context', value['presentation_type'])
    label, details = _parts(context)
    if presentation_type(context) != canonical:
        raise ValueError('presentation_context conflicts with presentation_type')
    occasion = ('lecture' if label in ('lecture', '讲课', '课程', '教学') else
                'commercial' if label in ('commercial', 'pitch', '路演', '商业路演') else canonical)
    value.update(presentation_type=canonical,
                 presentation_context={'occasion': occasion, 'details': details})
    return value


def slide_count(value):
    if value is not None and (type(value) is not int or not 1 <= value <= 40):
        raise ValueError('slide_count must be an integer in [1,40]')
    return value


def prompt_request(request):
    """Keep the complete user brief in prompts, including the final paper-page target."""
    return {key: request.get(key) for key in
            ('language', 'presentation_type', 'requirements', 'slide_count', 'presentation_context')
            if key != 'presentation_context' or request.get(key)}
