"""Trace measurements separately from inspected reference identifiers.

Reference labels are not measured values. Bare S11 is excluded only when the cited
context establishes it as a supplementary figure; arbitrary S999 is not a waiver.
"""
import re

REFERENCE = re.compile(r'(?<![A-Za-z])(?P<kind>Fig(?:ure)?\.?|Table|Supplementary\s+Note|Note|图|表|补充说明)\s*(?P<id>S?\d+[a-z]?)(?![A-Za-z0-9])', re.I)
BARE_SUPPLEMENT = re.compile(r'(?<![A-Za-z0-9])S\d+[a-z]?(?![A-Za-z0-9])')
NUMBER = re.compile(r'(?<![\d.])-?\d+(?:\.\d+)?(?:\s*[×x]\s*10\^?-?\d+)?%?')


def reference_ids(text):
    return {m['id'].upper() for m in REFERENCE.finditer(str(text))}


def numbers(text, reference_context=''):
    text = str(text).replace('−', '-').replace('\\%', '%').replace('$', '')
    text = re.sub(r'\^\{([-+]?\d+)\}', r'^\1', text)
    known = reference_ids(reference_context)
    # Explicit figure/table/note labels are checked separately as references, never as data.
    text = REFERENCE.sub('', text)
    text = BARE_SUPPLEMENT.sub(lambda m: '' if m[0].upper() in known else m[0], text)
    return {re.sub(r'\s+', '', v).replace('×', 'x') for v in NUMBER.findall(text)}


def unknown_references(text, context, selected=()):
    known = reference_ids(context) | {str(v).upper() for v in selected}
    return reference_ids(text)-known


def figure_source_label(figure_id, caption):
    """Keep approved caption wording literal; print the source identity exactly once."""
    explicit = any((m['kind'].lower().startswith('fig') or m['kind'] == '图') and m['id'].upper() == figure_id.upper()
                   for m in REFERENCE.finditer(str(caption)))
    return '本文' if explicit else '本文 Fig. '+figure_id
