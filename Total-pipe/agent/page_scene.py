#!/usr/bin/env python3
"""PageScene -> native PPTX renderer (job-integrated page_mode=page_scene).

This is deliberately a small, explicit scene renderer:
- page headers are a fixed design system;
- every body object has an explicit bbox in inches;
- text/list/group/image/table/shape/line/path/formula/chart are native objects;
- the renderer never allocates or guesses geometry.

Usage:
  python -m agent pagespec-render --spec work/page_scene.json --out build/candidate.pptx
"""
import argparse
import copy
import json
import re
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

MC_NS = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
A14_NS = 'http://schemas.microsoft.com/office/drawing/2010/main'
M_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
etree.register_namespace('mc', MC_NS)
etree.register_namespace('a14', A14_NS)
etree.register_namespace('m', M_NS)

PAGE_W, PAGE_H = 13.333, 7.5
MARGIN = 0.72
HEADER = {
    'section_y': 0.42, 'title_y': 0.72, 'rule_y': 1.46, 'take_y': 1.57,
}
FOOTER = {'rule_y': 7.08, 'text_y': 7.14}


def rgb(value, default='#142735'):
    if isinstance(value, RGBColor):
        return value
    value = (value or default).lstrip('#')
    return RGBColor.from_string(value.upper())


def align_from(value):
    return {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}.get(value, PP_ALIGN.LEFT)


def anchor_from(value):
    return {'top': MSO_ANCHOR.TOP, 'middle': MSO_ANCHOR.MIDDLE, 'bottom': MSO_ANCHOR.BOTTOM}.get(value, MSO_ANCHOR.TOP)


def emphasis_parts(text, terms):
    """Split visible text into (piece, emphasized) without changing its content."""
    terms = sorted({term for term in (terms or []) if isinstance(term, str) and term},
                   key=len, reverse=True)
    if not terms:
        return [(text, False)]
    pattern = re.compile('(' + '|'.join(re.escape(term) for term in terms) + ')')
    marked = set(terms)
    return [(piece, piece in marked) for piece in pattern.split(text) if piece]


def section_width(text):
    return min(2.45, max(1.35, 0.115 * len(text) + 0.42))


class Renderer:
    def __init__(self, spec, spec_path, bindings=None):
        self.spec = spec
        self.spec_path = Path(spec_path)
        self.bindings = dict(spec.get('bindings') or {})
        if bindings:
            self.bindings.update(bindings)
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

    def resolve_text(self, obj):
        if obj.get('text') is not None:
            return obj['text']
        ref = obj.get('copy_ref')
        if ref is not None:
            if ref not in self.bindings:
                raise ValueError('unresolved copy_ref: %s' % ref)
            return self.bindings[ref]
        return ''

    def page_text(self, page, field):
        ref = page.get(field + '_ref')
        if ref is not None:
            if ref not in self.bindings:
                raise ValueError('unresolved %s_ref: %s' % (field, ref))
            return self.bindings[ref]
        return page.get(field, '')

    def add_list(self, slide, obj):
        x, y, w, h = obj['box']
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = 0
        tf.margin_right = 0
        tf.margin_top = 0
        tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.TOP
        base_size = obj.get('size', 18)
        base_color = rgb(obj.get('color'), '#1B2A3A')
        bullets = {
            'dot': ['•', '–', '·', '◦'],
            'dash': ['–', '·', '◦', '•'],
            'square': ['▪', '–', '·', '◦'],
            'arrow': ['➢', '–', '·', '◦'],
            'none': ['', '', '', ''],
        }.get(obj.get('bullet_style', 'dot'), ['•', '–', '·', '◦'])
        for i, item in enumerate(obj.get('items', [])):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            level = max(0, min(3, int(item.get('level', 0))))
            size = item.get('size', base_size)
            p.level = level
            p.line_spacing = item.get('line_spacing', obj.get('line_spacing', 1.15))
            p.space_after = Pt(item.get('space_after', obj.get('space_after', 7)))
            pPr = p._p.get_or_add_pPr()
            pPr.set('marL', str(int(Inches(0.22 + 0.28 * level))))
            pPr.set('indent', str(int(-Inches(0.18))))
            for tag in ('a:buNone', 'a:buChar', 'a:buAutoNum', 'a:buClr', 'a:buFont'):
                for old in pPr.findall(qn(tag)):
                    pPr.remove(old)
            color = rgb(item.get('color'), obj.get('color', '#1B2A3A'))
            marker = bullets[level]
            if marker:
                buClr = etree.SubElement(pPr, qn('a:buClr'))
                srgb = etree.SubElement(buClr, qn('a:srgbClr'))
                srgb.set('val', str(color))
                buFont = etree.SubElement(pPr, qn('a:buFont'))
                buFont.set('typeface', 'Arial')
                buChar = etree.SubElement(pPr, qn('a:buChar'))
                buChar.set('char', marker)
            else:
                etree.SubElement(pPr, qn('a:buNone'))
            item_text = self.resolve_text(item) if item.get('copy_ref') else item.get('text', '')
            self.add_rich_runs(p, item_text, size, color,
                               bool(item.get('bold', obj.get('bold', False))), False,
                               item.get('emphasis') or obj.get('emphasis'),
                               item.get('emphasis_color'))
        return tb

    def add_math_run(self, paragraph, expression, size, color):
        """Append one native OMML inline-math run with a plain fallback."""
        from totalpipe_layout.formula import parse, to_omml, to_plain
        ast = parse(expression)
        alternate = etree.SubElement(paragraph, '{%s}AlternateContent' % MC_NS,
                                     nsmap={'mc': MC_NS, 'a14': A14_NS})
        choice = etree.SubElement(alternate, '{%s}Choice' % MC_NS,
                                  nsmap={'a14': A14_NS})
        choice.set('Requires', 'a14')
        a14 = etree.SubElement(choice, '{%s}m' % A14_NS)
        a14.append(etree.fromstring(to_omml(ast, size * 96.0 / 72.0, str(color), 'Cambria Math')))
        fallback = etree.SubElement(alternate, '{%s}Fallback' % MC_NS)
        run = etree.SubElement(fallback, qn('a:r'))
        rPr = etree.SubElement(run, qn('a:rPr'))
        rPr.set('lang', 'en-US')
        rPr.set('sz', str(int(round(size * 100))))
        fill = etree.SubElement(rPr, qn('a:solidFill'))
        etree.SubElement(fill, qn('a:srgbClr')).set('val', str(color))
        etree.SubElement(rPr, qn('a:latin')).set('typeface', 'Cambria Math')
        t = etree.SubElement(run, qn('a:t'))
        t.set(XML_SPACE, 'preserve')
        t.text = to_plain(ast)

    def add_rich_runs(self, paragraph, text, size, color, bold=False, italic=False,
                      emphasis=None, emphasis_color=None):
        """Render opt-in ``$...$`` math inside ordinary prose/list runs."""
        if '$' not in text and '\\(' not in text:
            spans = [(text, 'text')]
        else:
            from totalpipe_layout.inline_math import parse_inline
            try:
                spans = [(span.text, span.kind) for span in parse_inline(text)]
            except ValueError as error:
                raise ValueError('inline math: %s' % error) from error
        for value, kind in spans:
            if not value:
                continue
            if kind == 'formula':
                self.add_math_run(paragraph._p, value, size, color)
                continue
            for piece, hit in emphasis_parts(value, emphasis):
                run = paragraph.add_run()
                run.text = piece
                run.font.name = self.font
                run.font.size = Pt(size)
                run.font.bold = bool(bold or hit)
                run.font.italic = italic
                run.font.color.rgb = (rgb(emphasis_color) if hit and emphasis_color
                                      else self.accent if hit else color)

    def add_text(self, slide, x, y, w, h, text, size=18, color=None, bold=False, italic=False,
                 align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP, spacing=1.12, bullet=False,
                 emphasis=None, emphasis_color=None):
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
            value = ('•  ' + line) if bullet and line else line
            self.add_rich_runs(p, value, size, color or self.ink, bold, italic,
                               emphasis, emphasis_color)
        return tb

    def flat(self, shape):
        """Remove inherited theme effects so cards and rules stay truly flat."""
        shape.shadow.inherit = False
        for style in shape._element.findall(qn('p:style')):
            shape._element.remove(style)
        return shape

    def add_section_chip(self, slide, text):
        """A small typographic section marker, not a filled card."""
        if not text:
            return None
        self.add_rule(slide, MARGIN, 0.40, 0.045, self.accent, 0.25)
        self.add_text(slide, MARGIN + 0.13, 0.40, 5.6, 0.26, text, 9.6, self.accent, True,
                      spacing=1.0, valign=MSO_ANCHOR.MIDDLE)
        return None

    def add_take_band(self, slide, take, y, height, emphasis=None):
        """Lead sentence with one accent rule; no background panel."""
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(MARGIN), Inches(y),
                                     Inches(0.055), Inches(height))
        bar.fill.solid()
        bar.fill.fore_color.rgb = self.accent
        bar.line.fill.background()
        self.flat(bar)
        self.add_text(slide, MARGIN + 0.20, y + 0.04, PAGE_W - 2 * MARGIN - 0.24, height - 0.06,
                      take, 15.4, self.ink, False, spacing=1.05, valign=MSO_ANCHOR.MIDDLE,
                      emphasis=emphasis, emphasis_color=self.accent)

    def add_rule(self, slide, x, y, w, color=None, height=0.02, dash=False):
        sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(height))
        sh.fill.solid()
        sh.fill.fore_color.rgb = color or self.accent
        sh.line.fill.background()
        self.flat(sh)
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
        self.flat(sh)
        if obj.get('text') or obj.get('copy_ref'):
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
            r.text = self.resolve_text(obj)
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
        header_fill = rgb(obj.get('header_fill'), '#102A43')
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
                    cell.fill.fore_color.rgb = header_fill
                elif r in accent_rows:
                    cell.fill.fore_color.rgb = rgb('#E8F3F8')
                else:
                    cell.fill.fore_color.rgb = self.white if r % 2 else self.light
        return shape

    def add_formula(self, slide, obj):
        x, y, w, h = obj['box']
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = 0
        tf.margin_right = 0
        tf.margin_top = 0
        tf.margin_bottom = 0
        tf.vertical_anchor = anchor_from(obj.get('valign', 'middle'))
        from totalpipe_layout.formula import parse, to_omml_paragraph
        latex = obj.get('latex') or obj.get('text') or ''
        omml = to_omml_paragraph(parse(latex), size_px=obj.get('size', 20),
                                 color=obj.get('color', '#142735'), face='Cambria Math')
        body = tf._txBody
        for paragraph in body.findall(qn('a:p')):
            body.remove(paragraph)
        paragraph = etree.fromstring(omml)
        pPr = etree.Element(qn('a:pPr'))
        pPr.set('algn', {'left': 'l', 'center': 'ctr', 'right': 'r'}.get(
            obj.get('align', 'center'), 'ctr'))
        paragraph.insert(0, pPr)
        body.append(paragraph)
        return tb

    def add_path(self, slide, obj):
        from deck_compiler.graphic_paths import parse_path, path_bounds, custom_geometry
        commands = parse_path(obj.get('commands', obj.get('d')))
        x, y, w, h = obj['box']
        view = obj.get('view_box') or [0, 0, w, h]
        vx, vy, vw, vh = (float(value) for value in view)
        if vw <= 0 or vh <= 0:
            raise ValueError('path view_box requires positive width and height')
        transformed = []
        for command in commands:
            values = list(command[1:])
            points = []
            for index in range(0, len(values), 2):
                points.append(x + (float(values[index]) - vx) * w / vw)
                points.append(y + (float(values[index + 1]) - vy) * h / vh)
            transformed.append([command[0], *points])
        bx, by, bw, bh = path_bounds(transformed)
        if bw == 0:
            bx, bw = bx - 0.01, 0.02
        if bh == 0:
            by, bh = by - 0.01, 0.02
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(bx), Inches(by), Inches(bw), Inches(bh))
        spPr = shape._element.spPr
        prst = spPr.find(qn('a:prstGeom'))
        geometry = etree.fromstring(custom_geometry(transformed, [bx, by, bw, bh]))
        if prst is not None:
            spPr.replace(prst, geometry)
        else:
            spPr.insert(2, geometry)
        fill = obj.get('fill', 'none')
        if fill == 'none':
            shape.fill.background()
        else:
            shape.fill.solid()
            shape.fill.fore_color.rgb = rgb(fill, '#F3F6F8')
        stroke = obj.get('stroke', '#0B6E99')
        if stroke == 'none':
            shape.line.fill.background()
        else:
            shape.line.color.rgb = rgb(stroke, '#0B6E99')
            shape.line.width = Pt(obj.get('stroke_width', 2.0))
            if obj.get('dash'):
                shape.line.dash_style = 4
        shape.shadow.inherit = False
        return shape

    def add_chart(self, slide, obj):
        x, y, w, h = obj['box']
        kind = obj.get('chart_type', 'line')
        series = obj.get('series') or []
        if not series:
            raise ValueError('chart requires at least one series')
        if kind == 'scatter':
            data = XyChartData()
            for item in series:
                values = list(item.get('values') or [])
                x_values = list(item.get('x_values') or obj.get('x_values') or
                                range(1, len(values) + 1))
                if len(x_values) != len(values):
                    raise ValueError('scatter chart needs one x value per y value')
                chart_series = data.add_series(item.get('name') or 'Series')
                for xv, yv in zip(x_values, values):
                    chart_series.add_data_point(float(xv), float(yv))
            chart_type = XL_CHART_TYPE.XY_SCATTER
        else:
            data = CategoryChartData()
            categories = obj.get('categories') or [str(index + 1) for index in
                                                   range(len(series[0].get('values') or []))]
            data.categories = categories
            for item in series:
                data.add_series(item.get('name') or 'Series', [float(value) for value in item.get('values') or []])
            chart_type = {
                'line': XL_CHART_TYPE.LINE_MARKERS,
                'bar': XL_CHART_TYPE.BAR_CLUSTERED,
                'column': XL_CHART_TYPE.COLUMN_CLUSTERED,
            }.get(kind, XL_CHART_TYPE.LINE_MARKERS)
        frame = slide.shapes.add_chart(chart_type, Inches(x), Inches(y), Inches(w), Inches(h), data)
        chart = frame.chart
        chart.font.name = self.font
        chart.font.size = Pt(obj.get('font_size', 11))
        chart.has_legend = bool(obj.get('legend', len(series) > 1))
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
        if obj.get('title'):
            chart.has_title = True
            chart.chart_title.text_frame.text = obj['title']
        chart.has_title = bool(obj.get('title', False))
        for axis, key in ((chart.category_axis, obj.get('x_label')), (chart.value_axis, obj.get('y_label'))):
            if key:
                axis.has_title = True
                axis.axis_title.text_frame.text = key
        chart.value_axis.has_major_gridlines = True
        chart.value_axis.major_gridlines.format.line.color.rgb = rgb('#D7DEE6')
        return frame

    def render_object(self, slide, obj):
        kind = obj['type']
        if kind == 'group':
            gx, gy = obj['box'][0], obj['box'][1]
            for child in obj.get('children', []):
                c = copy.deepcopy(child)
                if c.get('box') and len(c['box']) == 4:
                    c['box'] = [c['box'][0] + gx, c['box'][1] + gy, c['box'][2], c['box'][3]]
                self.render_object(slide, c)
            return
        if kind == 'text':
            role = obj.get('role', 'body')
            default_size = {'body': 18, 'label': 13, 'caption': 9.3, 'note': 11}[role]
            default_color = {'body': self.ink, 'label': self.navy, 'caption': self.gray, 'note': self.gray}[role]
            self.add_text(
                slide, *obj['box'], self.resolve_text(obj), obj.get('size', default_size),
                rgb(obj.get('color')) if obj.get('color') else default_color,
                obj.get('bold', False), obj.get('italic', False),
                align_from(obj.get('align', 'left')), anchor_from(obj.get('valign', 'top')),
                obj.get('line_spacing', 1.12), obj.get('bullet', False),
                obj.get('emphasis'), obj.get('emphasis_color'),
            )
        elif kind == 'list':
            self.add_list(slide, obj)
        elif kind == 'image':
            self.add_image(slide, obj)
        elif kind == 'shape':
            self.add_shape(slide, obj)
        elif kind == 'line':
            self.add_line(slide, obj)
        elif kind == 'table':
            self.add_table(slide, obj)
        elif kind == 'formula':
            self.add_formula(slide, obj)
        elif kind == 'path':
            self.add_path(slide, obj)
        elif kind == 'chart':
            self.add_chart(slide, obj)
        else:
            raise ValueError('Unknown object type: %s' % kind)

    def render_page(self, page, index, total):
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = self.white
        title_y = page.get('title_y', 0.75)
        title_h = page.get('title_h', 0.60)
        title_size = page.get('title_size', 27.5)
        take_y = page.get('take_y', 1.53)
        take_h = page.get('take_h', 0.58)
        if page.get('section'):
            self.add_section_chip(slide, page['section'])
        self.add_text(slide, MARGIN, title_y, PAGE_W - 2 * MARGIN, title_h,
                      self.page_text(page, 'title'), title_size, self.navy, True, spacing=1.0,
                      emphasis=page.get('title_emphasis'), emphasis_color=self.accent)
        self.add_take_band(slide, self.page_text(page, 'take'), take_y, take_h,
                           page.get('take_emphasis'))
        self.add_rule(slide, MARGIN, 2.165, PAGE_W - 2 * MARGIN, rgb('#D7DEE6'), 0.008)
        for obj in page['objects']:
            self.render_object(slide, obj)
        # Always materialize a notes part; package-level QA otherwise cannot
        # distinguish "no notes" from a malformed/missing relationship.
        slide.notes_slide.notes_text_frame.text = page.get('notes') or ''
        if page.get('footer', True):
            self.add_rule(slide, MARGIN, FOOTER['rule_y'], PAGE_W - 2 * MARGIN, rgb('#D7DEE6'), 0.01)
            self.add_text(slide, MARGIN, FOOTER['text_y'], 8.6, 0.18, 'Tian et al. · Nat. Commun. 2026 · AVDG digital–analog multimode circuits', 8.8, self.gray)
            self.add_text(slide, PAGE_W - 1.0, FOOTER['text_y'], 0.35, 0.18, str(page.get('page_number', index)), 8.8, self.gray, align=PP_ALIGN.RIGHT)
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
