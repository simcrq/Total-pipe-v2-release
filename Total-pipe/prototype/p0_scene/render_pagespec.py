#!/usr/bin/env python3
"""P0 PageSpec -> native PPTX renderer.

This is deliberately a small, explicit scene renderer:
- page headers are a fixed design system;
- every body object has an explicit bbox in inches;
- text, images, tables, shapes and lines are native PowerPoint objects;
- the renderer never allocates or guesses geometry.

Usage:
  python render_pagespec.py --spec demo.deck.json --out build/demo.pptx
"""
import argparse
import json
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

PAGE_W, PAGE_H = 13.333, 7.5
MARGIN = 0.72
HEADER = {
    'section_y': 0.42, 'title_y': 0.72, 'rule_y': 1.46, 'take_y': 1.57,
}
FOOTER = {'rule_y': 7.08, 'text_y': 7.14}


def rgb(value, default='#142735'):
    value = (value or default).lstrip('#')
    return RGBColor.from_string(value.upper())


def align_from(value):
    return {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}.get(value, PP_ALIGN.LEFT)


def anchor_from(value):
    return {'top': MSO_ANCHOR.TOP, 'middle': MSO_ANCHOR.MIDDLE, 'bottom': MSO_ANCHOR.BOTTOM}.get(value, MSO_ANCHOR.TOP)


class Renderer:
    def __init__(self, spec, spec_path):
        self.spec = spec
        self.spec_path = Path(spec_path)
        self.theme = spec.get('theme', {})
        self.font = self.theme.get('font', 'Microsoft YaHei')
        self.ink = rgb(self.theme.get('ink', '#1B2A3A'))
        self.navy = rgb(self.theme.get('navy', '#102A43'))
        self.accent = rgb(self.theme.get('accent', '#0B6E99'))
        self.orange = rgb(self.theme.get('orange', '#D97706'))
        self.gray = rgb(self.theme.get('gray', '#5E7084'))
        self.light = rgb(self.theme.get('light', '#F3F6F8'))
        self.white = rgb('#FFFFFF')
        self.prs = Presentation()
        self.prs.slide_width = Inches(PAGE_W)
        self.prs.slide_height = Inches(PAGE_H)

    def add_text(self, slide, x, y, w, h, text, size=18, color=None, bold=False, italic=False,
                 align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP, spacing=1.12, bullet=False):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = 0
        tf.margin_right = 0
        tf.margin_top = 0
        tf.margin_bottom = 0
        tf.vertical_anchor = valign
        lines = text.split('\n') if text else ['']
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            p.line_spacing = spacing
            r = p.add_run()
            r.text = ('•  ' + line) if bullet and line else line
            r.font.name = self.font
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.italic = italic
            r.font.color.rgb = color or self.ink
        return tb

    def add_rule(self, slide, x, y, w, color=None, height=0.02, dash=False):
        sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(height))
        sh.fill.solid()
        sh.fill.fore_color.rgb = color or self.accent
        sh.line.fill.background()
        if dash:
            sh.line.color.rgb = color or self.accent
            sh.line.width = Pt(1)
            sh.line.dash_style = 4
            sh.fill.background()
        return sh

    def add_shape(self, slide, obj):
        x, y, w, h = obj['box']
        kind = obj.get('shape', 'rect')
        shape_map = {
            'rect': MSO_SHAPE.RECTANGLE,
            'rounded': MSO_SHAPE.ROUNDED_RECTANGLE,
            'oval': MSO_SHAPE.OVAL,
            'arrow': MSO_SHAPE.RIGHT_ARROW,
            'chevron': MSO_SHAPE.CHEVRON,
        }
        sh = slide.shapes.add_shape(shape_map.get(kind, MSO_SHAPE.RECTANGLE), Inches(x), Inches(y), Inches(w), Inches(h))
        fill = obj.get('fill', 'none')
        if fill == 'none':
            sh.fill.background()
        else:
            sh.fill.solid()
            sh.fill.fore_color.rgb = rgb(fill, '#F3F6F8')
        stroke = obj.get('stroke', 'none')
        if stroke == 'none':
            sh.line.fill.background()
        else:
            sh.line.color.rgb = rgb(stroke, '#8C9BAE')
            sh.line.width = Pt(obj.get('stroke_width', 1.2))
            if obj.get('dash'):
                sh.line.dash_style = 4
        if obj.get('text'):
            tf = sh.text_frame
            tf.word_wrap = True
            tf.margin_left = Inches(0.05)
            tf.margin_right = Inches(0.05)
            tf.margin_top = Inches(0.02)
            tf.margin_bottom = Inches(0.02)
            tf.vertical_anchor = anchor_from(obj.get('valign', 'middle'))
            p = tf.paragraphs[0]
            p.alignment = align_from(obj.get('align', 'center'))
            p.line_spacing = obj.get('line_spacing', 1.0)
            r = p.add_run()
            r.text = obj['text']
            r.font.name = self.font
            r.font.size = Pt(obj.get('size', 14))
            r.font.bold = obj.get('bold', False)
            r.font.color.rgb = rgb(obj.get('color', '#102A43'))
        return sh

    def add_line(self, slide, obj):
        x1, y1, x2, y2 = obj['box']
        ln = slide.shapes.add_connector(1, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        ln.line.color.rgb = rgb(obj.get('stroke', '#8C9BAE'), '#8C9BAE')
        ln.line.width = Pt(obj.get('stroke_width', 1.2))
        if obj.get('dash'):
            ln.line.dash_style = 4
        return ln

    def add_image(self, slide, obj):
        x, y, w, h = obj['box']
        path = Path(obj['path'])
        if not path.is_absolute():
            path = self.spec_path.parent / path
        im = Image.open(path)
        iw, ih = im.size
        if obj.get('fit', 'contain') == 'cover':
            target_ratio = w / h
            src_ratio = iw / ih
            if src_ratio > target_ratio:
                new_w = int(ih * target_ratio)
                left = (iw - new_w) // 2
                im = im.crop((left, 0, left + new_w, ih))
            else:
                new_h = int(iw / target_ratio)
                top = (ih - new_h) // 2
                im = im.crop((0, top, iw, top + new_h))
            tmp = path.with_name(path.stem + '_fit' + path.suffix)
            im.save(tmp, quality=95)
            path = tmp
        scale = min(w / im.width, h / im.height)
        ww, hh = im.width * scale, im.height * scale
        xx = x + (w - ww) / 2
        yy = y + (h - hh) / 2
        return slide.shapes.add_picture(str(path), Inches(xx), Inches(yy), Inches(ww), Inches(hh))

    def add_table(self, slide, obj):
        rows = obj['rows']
        x, y, w, h = obj['box']
        nrows, ncols = len(rows), len(rows[0])
        row_h = obj.get('row_height', h / nrows)
        shape = slide.shapes.add_table(nrows, ncols, Inches(x), Inches(y), Inches(w), Inches(row_h * nrows))
        table = shape.table
        widths = obj.get('col_widths')
        if widths:
            total = sum(widths)
            for i, cw in enumerate(widths):
                table.columns[i].width = Inches(w * cw / total)
        header = obj.get('header', True)
        accent_rows = set(obj.get('accent_rows', []))
        for r in range(nrows):
            table.rows[r].height = Inches(row_h)
            for c in range(ncols):
                cell = table.cell(r, c)
                cell.margin_left = Inches(0.08)
                cell.margin_right = Inches(0.08)
                cell.margin_top = Inches(0.03)
                cell.margin_bottom = Inches(0.03)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.text = ''
                p = cell.text_frame.paragraphs[0]
                p.alignment = align_from('center' if c else 'left')
                run = p.add_run()
                run.text = str(rows[r][c])
                run.font.name = self.font
                run.font.size = Pt(obj.get('font_size', 15))
                run.font.bold = (header and r == 0) or (r in accent_rows)
                run.font.color.rgb = self.white if (header and r == 0) else self.ink
                cell.fill.solid()
                if header and r == 0:
                    cell.fill.fore_color.rgb = self.navy
                elif r in accent_rows:
                    cell.fill.fore_color.rgb = rgb('#E8F3F8')
                else:
                    cell.fill.fore_color.rgb = self.white if r % 2 else self.light
        return shape

    def render_page(self, page, index, total):
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = self.white
        title_y = page.get('title_y', HEADER['title_y'])
        title_h = page.get('title_h', 0.64)
        title_size = page.get('title_size', 28)
        rule_y = page.get('rule_y', HEADER['rule_y'])
        take_y = page.get('take_y', HEADER['take_y'])
        take_h = page.get('take_h', 0.58)
        if page.get('section'):
            self.add_text(slide, MARGIN, HEADER['section_y'], 9.0, 0.28, page['section'], 10.5, self.accent, True)
        self.add_text(slide, MARGIN, title_y, PAGE_W - 2 * MARGIN, title_h, page['title'], title_size, self.navy, True, spacing=1.0)
        self.add_rule(slide, MARGIN, rule_y, PAGE_W - 2 * MARGIN, self.gray, 0.015)
        self.add_text(slide, MARGIN, take_y, PAGE_W - 2 * MARGIN, take_h, page.get('take', ''), 16.5, self.gray, False, spacing=1.08)
        for obj in page['objects']:
            kind = obj['type']
            if kind == 'text':
                role = obj.get('role', 'body')
                default_size = {'body': 18, 'label': 13, 'caption': 9.3, 'note': 11}[role]
                default_color = {'body': self.ink, 'label': self.navy, 'caption': self.gray, 'note': self.gray}[role]
                self.add_text(
                    slide, *obj['box'], obj.get('text', ''), obj.get('size', default_size),
                    rgb(obj.get('color')) if obj.get('color') else default_color,
                    obj.get('bold', False), obj.get('italic', False),
                    align_from(obj.get('align', 'left')), anchor_from(obj.get('valign', 'top')),
                    obj.get('line_spacing', 1.12), obj.get('bullet', False),
                )
            elif kind == 'image':
                self.add_image(slide, obj)
            elif kind == 'shape':
                self.add_shape(slide, obj)
            elif kind == 'line':
                self.add_line(slide, obj)
            elif kind == 'table':
                self.add_table(slide, obj)
            else:
                raise ValueError('Unknown object type: %s' % kind)
        if page.get('footer', True):
            self.add_rule(slide, MARGIN, FOOTER['rule_y'], PAGE_W - 2 * MARGIN, rgb('#D7DEE6'), 0.01)
            self.add_text(slide, MARGIN, FOOTER['text_y'], 8.6, 0.18, 'Tian et al. · Nat. Commun. 2026 · AVDG digital–analog multimode circuits', 8.8, self.gray)
            self.add_text(slide, PAGE_W - 1.0, FOOTER['text_y'], 0.35, 0.18, str(index), 8.8, self.gray, align=PP_ALIGN.RIGHT)
        return slide

    def save(self, out):
        self.prs.save(out)
        return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding='utf-8'))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    renderer = Renderer(spec, args.spec)
    for i, page in enumerate(spec['pages'], 1):
        renderer.render_page(page, i, len(spec['pages']))
    renderer.save(out)
    print('rendered %s pages -> %s' % (len(spec['pages']), out))


if __name__ == '__main__':
    main()
