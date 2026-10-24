"""Compiler typography for opt-in inline math; one editable mixed text body, explicit measured lines."""
from dataclasses import replace
from xml.etree import ElementTree as ET

from .fonts import load_font_file
from totalpipe_layout.inline_math import InlineWidthError, measure_inline
from totalpipe_layout.formula import parse, to_omml, to_plain

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
A14 = 'http://schemas.microsoft.com/office/drawing/2010/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
for prefix, namespace in (('a', A), ('p', P), ('mc', MC), ('a14', A14), ('m', M)):
    ET.register_namespace(prefix, namespace)


def fit_inline(source, bbox, contract, preserve_terms=False):
    width = bbox[2]-contract.inset['left']-contract.inset['right']
    available = bbox[3]-contract.inset['top']-contract.inset['bottom']
    width_error = None
    for size in range(int(contract.font_size), int(contract.font_floor)-1, -1):
        try:
            plan = measure_inline(source, width, load_font_file(contract.font_file, size), size, contract.line_height)
        except InlineWidthError as error:
            width_error = error
            continue
        if plan['height'] <= available+.01 and len(plan['lines']) <= contract.max_lines:
            return plan, replace(contract, font_size=size), False
    if width_error and size == int(contract.font_floor):
        # Re-measure the floor: a wider formula at an earlier size must not mask a height issue.
        plan = measure_inline(source, width, load_font_file(contract.font_file, size), size, contract.line_height)
    if preserve_terms:
        return plan, replace(contract, font_size=size, max_lines=max(contract.max_lines, len(plan['lines'])),
                             overflow_policy='preserve_terms_review'), True
    raise ValueError('INLINE_TEXT_CAPACITY')


def _sub(parent, tag, attrs=None):
    return ET.SubElement(parent, '{'+A+'}'+tag, {k: str(v) for k, v in (attrs or {}).items()})


def _props(parent, tag, contract, color):
    props = _sub(parent, tag, {'lang': 'zh-CN', 'sz': round(contract['font_size']*75),
                              'b': '1' if contract['font_weight'] >= 700 else '0'})
    _sub(_sub(props, 'solidFill'), 'srgbClr', {'val': color.lstrip('#')})
    for name in ('latin', 'ea', 'cs'):
        _sub(props, name, {'typeface': contract['font_family']})
    return props


def paragraphs(plan, contract, color, align='left'):
    result = []
    for line in plan['lines']:
        p = ET.Element('{'+A+'}p')
        ppr = _sub(p, 'pPr', {'algn': {'left': 'l', 'center': 'ctr', 'right': 'r'}[align]})
        _sub(_sub(ppr, 'lnSpc'), 'spcPts', {'val': round(line['height']*75)})
        _sub(_sub(ppr, 'spcBef'), 'spcPts', {'val': 0})
        _sub(_sub(ppr, 'spcAft'), 'spcPts', {'val': 0})
        _sub(ppr, 'buNone')
        _props(ppr, 'defRPr', contract, color)
        for fragment in line['fragments']:
            if fragment['kind'] == 'text':
                run = _sub(p, 'r'); _props(run, 'rPr', contract, color)
                _sub(run, 't', {'{http://www.w3.org/XML/1998/namespace}space': 'preserve'}).text = fragment['text']
            else:
                alternate = ET.SubElement(p, '{'+MC+'}AlternateContent')
                choice = ET.SubElement(alternate, '{'+MC+'}Choice', {'Requires': 'a14'})
                math = ET.SubElement(choice, '{'+A14+'}m')
                math.append(ET.fromstring(to_omml(parse(fragment['text']), contract['font_size'], color)))
                fallback = ET.SubElement(alternate, '{'+MC+'}Fallback')
                run = _sub(fallback, 'r'); _props(run, 'rPr', contract, color)
                _sub(run, 't').text = to_plain(parse(fragment['text']))
        _props(p, 'endParaRPr', contract, color)
        result.append(p)
    return result


def text_body(plan, contract, color, align='left'):
    root = ET.Element('{'+P+'}txBody')
    attrs = {'wrap': 'none', 'anchor': {'top': 't', 'middle': 'ctr', 'bottom': 'b'}[contract['vertical_anchor']]}
    attrs.update({key: round(contract['inset'][name]*9525) for key, name in
                  (('lIns', 'left'), ('rIns', 'right'), ('tIns', 'top'), ('bIns', 'bottom'))})
    _sub(_sub(root, 'bodyPr', attrs), 'noAutofit')
    _sub(root, 'lstStyle')
    root.extend(paragraphs(plan, contract, color, align))
    return ET.tostring(root, encoding='unicode')
