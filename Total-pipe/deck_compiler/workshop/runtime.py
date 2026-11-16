"""工坊共用：从 Deck IR 还原编译器真正会用的 theme 与字体。

这不是重写编译器的页面模型，只是把 compile_deck 开头那三步（design / style / fonts）单独调一次，
好让单件渲染器和骨架预排用完全相同的材质。调用方应校验 font_paths 与 layout.json 的
font_hashes 键一致，否则说明材质取自另一套解析结果。
"""
import json
from pathlib import Path

SAMPLES = ('·0123456789直接证据假设（未证实）')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


_FACES = {}


def face(path, size):
    """同一个字体文件只加载一次；断行必须和渲染用同一张脸。"""
    from ..fonts import load_font_file
    key = (str(path), int(size))
    if key not in _FACES:
        _FACES[key] = load_font_file(path, size)
    return _FACES[key]


def _sample(ir):
    parts = [SAMPLES]
    for slide in ir.get('slides', []):
        semantic = slide.get('semantic', {})
        parts += [str(semantic.get(k, '')) for k in ('title', 'purpose', 'takeaway')]
        comp = slide.get('composition', {})
        parts += [str(b.get('text', '')) + str(b.get('label', '')) for b in comp.get('blocks', [])]
        parts += [str(f.get('caption', '')) for f in comp.get('figure_refs', [])]
        parts += [str(n.get('title', '')) for g in comp.get('graphics', [])
                  for n in g.get('nodes', [])]
    return ''.join(parts)


def runtime(ir, base):
    from ..layout import resolve_design
    from ..style import resolve as resolve_style
    from ..fonts import resolve_theme_fonts

    design = resolve_design(ir)
    theme = {**ir['theme'], **({'accent': design['accent_color']} if design else {})}
    theme['_visual_style'] = resolve_style(ir.get('presentation'))
    regular, bold, notes = resolve_theme_fonts(theme, Path(base), _sample(ir))
    return design, theme, {'font_file': regular, 'bold_font_file': bold}, notes


def graphics_of(slide):
    return list(slide.get('composition', {}).get('graphics', []))


def regions_of(slide_layout):
    """layout 的 adaptation_log 记录了每个原生图形拿到的真实区域。"""
    return {item['graphic_id']: item['region']
            for item in slide_layout.get('adaptation_log', [])
            if item.get('action') == 'native_graphic' and item.get('region')}
