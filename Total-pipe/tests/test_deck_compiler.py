import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from PIL import Image
from deck_compiler.contracts import TextBoxContract, issue, report, digest, file_hash
from deck_compiler.ir import validate, derive
from deck_compiler.layout import compile_deck
from deck_compiler.text_flow import select_text_flow
from deck_compiler.ooxml import target_part, fill, background, NS
from deck_compiler.pipeline import (ingest_native, promote, record_powerpoint_review,
                                    write_json, locked)
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parents[1]
def fixture():
    return json.loads((ROOT/'examples/research.deck_ir.json').read_text())

class InfrastructureTests(unittest.TestCase):
    def test_opc_targets(self):
        for target in ('../media/image1.png', '/ppt/media/image1.png', '../media/./image1.png'):
            self.assertEqual(target_part('ppt/slides/slide1.xml', target), 'ppt/media/image1.png')
        self.assertEqual(target_part('ppt/slides/slide1.xml', '../media/a%20b.png'), 'ppt/media/a b.png')
        for bad in ('../../../outside', 'https://host/image', '..\\media\\image.png'):
            with self.assertRaises(ValueError):
                target_part('ppt/slides/slide1.xml', bad)
    def test_line_fill_is_not_shape_fill(self):
        node = ET.fromstring(f'<a:spPr xmlns:a="{NS["a"]}"><a:ln><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></a:ln></a:spPr>')
        self.assertIsNone(fill(node))
    def test_background_inheritance(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'test.pptx'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('ppt/slides/slide1.xml', f'<p:sld xmlns:p="{NS["p"]}"><p:cSld/></p:sld>')
                z.writestr('ppt/slides/_rels/slide1.xml.rels', '<Relationships><Relationship Id="r1" Type="x/slideLayout" Target="../slideLayouts/layout.xml"/></Relationships>')
                z.writestr('ppt/slideLayouts/layout.xml', f'<p:sldLayout xmlns:p="{NS["p"]}" xmlns:a="{NS["a"]}"><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="112233"/></a:solidFill></p:bgPr></p:bg></p:cSld></p:sldLayout>')
            with zipfile.ZipFile(path) as z:
                self.assertEqual(background(z, 'ppt/slides/slide1.xml'), ('#112233', 'ooxml:ppt/slideLayouts/layout.xml'))
    def test_transparency_not_guessed(self):
        node = ET.fromstring(f'<a:spPr xmlns:a="{NS["a"]}"><a:solidFill><a:srgbClr val="FF0000"><a:alpha val="50000"/></a:srgbClr></a:solidFill></a:spPr>')
        self.assertIsNone(fill(node))
    def test_text_floor(self):
        with self.assertRaises(ValueError): TextBoxContract('Arial', 18, '/font', font_floor=24)
    def test_concurrent_build_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with locked(Path(d)):
                with self.assertRaises(FileExistsError):
                    with locked(Path(d)): pass
            self.assertFalse((Path(d)/'.compiler.lock').exists())

class CompilerTests(unittest.TestCase):
    def test_determinism_no_mutation(self):
        ir = fixture(); before = copy.deepcopy(ir)
        a, ai = compile_deck(ir, ROOT); b, bi = compile_deck(ir, ROOT)
        self.assertEqual(a,b); self.assertEqual(ai,bi); self.assertEqual(ir,before)
        self.assertFalse([i for i in ai if i['severity']=='FAIL'])
    def test_all_archetypes(self):
        from deck_compiler.catalog import ARCHETYPES
        ir=fixture()
        for archetype in ARCHETYPES:
            with self.subTest(archetype=archetype):
                s=copy.deepcopy(ir['slides'][0]); s['composition']['archetype']=archetype
                s['composition']['blocks']=[{'id':'b','component':'direct-evidence' if archetype=='evidence-hypothesis' else 'body','text':'A different finding.'}]
                layout, items=compile_deck({**ir,'slides':[s]},ROOT)
                self.assertIsNotNone(layout); self.assertFalse([i for i in items if i['severity']=='FAIL'])
    def test_capacity_excess(self):
        ir=fixture(); ir['slides'][1]['composition']['blocks']*=2
        self.assertIn('CONTENT_CAPACITY_EXCEEDED',{i['rule'] for i in validate(ir)})
    def test_split_not_infinite_shrink(self):
        ir=fixture()
        for b in ir['slides'][1]['composition']['blocks']: b['text']='Long research statement '*24
        _,items=compile_deck(ir,ROOT)
        self.assertIn('SPLIT_REQUIRED',{i['rule'] for i in items})
    def test_geometry_rejected_in_ir(self):
        ir=fixture(); ir['slides'][0]['composition']['blocks'][0]['bbox']=[0,0,1,1]
        self.assertIn('IR_INVALID',{i['rule'] for i in validate(ir)})
    def test_evidence_hypothesis_not_mixed(self):
        ir=fixture(); ir['slides'][0]['composition']['blocks'][0]['component']='body'
        self.assertTrue(validate(ir))
    def test_missing_notes(self):
        ir=fixture(); ir['slides'][0]['semantic']['speaker_notes']=''
        self.assertTrue(validate(ir))
    def test_missing_asset(self):
        ir=fixture(); ir['assets']={'bad':{'path':'does-not-exist.png'}}
        _,items=compile_deck(ir,ROOT)
        self.assertIn('ASSET_INVALID',{i['rule'] for i in items})
    def test_figure_source_mismatch_is_fail(self):
        ir=fixture(); slide=ir['slides'][0]
        ir['assets']={'panel':{'path':'panel.png','source_figure':'3e'}}
        slide['composition']['figure_refs']=[{
            'asset_id':'panel','source_figure':'3f','caption':'Source: Fig.3f','panel_count':1
        }]
        self.assertIn('FIGURE_SOURCE_MISMATCH',{i['rule'] for i in validate(ir)})
    def test_figure_caption_must_name_exact_panel(self):
        ir=fixture(); slide=ir['slides'][0]
        ir['assets']={'panel':{'path':'panel.png','source_figure':'3e'}}
        slide['composition']['figure_refs']=[{
            'asset_id':'panel','source_figure':'3e','caption':'Source: Fig.3','panel_count':1
        }]
        self.assertIn('FIGURE_CAPTION_MISMATCH',{i['rule'] for i in validate(ir)})
    def test_scientific_panel_minimum_is_hard_gate(self):
        with tempfile.TemporaryDirectory() as d:
            image_path=Path(d)/'panel.png'; Image.new('RGB',(400,400),'white').save(image_path)
            ir=fixture(); slide=ir['slides'][0]
            slide['composition']['archetype']='cover-hero'
            ir['assets']={'panel':{'path':str(image_path),'source_figure':'3e'}}
            slide['composition']['figure_refs']=[{
                'asset_id':'panel','source_figure':'3e','caption':'Source: Fig.3e',
                'panel_count':1,'min_panel_extent':500
            }]
            _,items=compile_deck(ir,ROOT)
            self.assertIn('SCIENTIFIC_PANEL_TOO_SMALL',{i['rule'] for i in items})
    def test_derived_truth(self):
        ir=fixture(); layout,_=compile_deck(ir,ROOT)
        self.assertTrue(all(v['ir_sha256']==digest(ir) and v['read_only'] for v in derive(ir,layout).values()))
    def test_explicit_contract(self):
        layout,_=compile_deck(fixture(),ROOT)
        for s in layout['slides']:
            for e in s['elements']:
                if e['kind']=='text':
                    c=TextBoxContract(**e['contract']); self.assertGreaterEqual(c.font_size,c.font_floor)
                    self.assertLessEqual(len(e['text'].split('\n')),c.max_lines)
    def test_wrapped_title_allowed(self):
        ir=fixture(); ir['slides'][0]['semantic']['title']='The scientific result under different conditions with a substantially longer title'
        layout,items=compile_deck(ir,ROOT)
        self.assertIn('\n',layout['slides'][0]['elements'][0]['text'])
        self.assertNotIn('TITLE_WRAPPED',{i['rule'] for i in items})
    def test_long_parallel_paragraphs_use_distributed_arrow_list(self):
        ir=fixture(); slide=ir['slides'][1]
        slide['composition']['blocks']=[{
            'id':'findings','component':'body','label':'Key findings',
            'text':'The first finding establishes the operating regime and its boundary.\n'
                   'The second finding connects the measured response to the proposed mechanism.\n'
                   'The third finding states the remaining uncertainty and the next experiment.'
        }]
        layout,items=compile_deck({**ir,'slides':[slide]},ROOT)
        self.assertFalse([i for i in items if i['severity']=='FAIL'])
        planned=layout['slides'][0]
        self.assertEqual(planned['adaptation_log'][0]['action'],'distributed_arrow_list')
        self.assertEqual([e['text'] for e in planned['elements'] if ':arrow:' in e['id']],['➢']*3)
        self.assertEqual(len([e for e in planned['elements'] if ':item:' in e['id']]),3)
        self.assertTrue(any(e['kind']=='shape' and e['id']=='findings:panel' for e in planned['elements']))
    def test_single_long_paragraph_is_not_semantically_split(self):
        flow=select_text_flow('A single long paragraph stays intact even when it contains many words and ideas. '*3)
        self.assertEqual(flow['mode'],'plain')
    def test_cjk_parallel_paragraphs_use_weighted_length(self):
        flow=select_text_flow('第一条说明实验边界与适用条件。\n第二条连接观测结果与机制证据。\n第三条明确剩余不确定性和下一步实验。')
        self.assertEqual(flow['mode'],'distributed_arrow_list')

class PublicationTests(unittest.TestCase):
    def test_severity(self):
        self.assertEqual(report([issue('SMALL','WARNING','small')])['status'],'PASS')
        self.assertEqual(report([issue('PANEL','REVIEW','inspect')])['status'],'REVIEW')
    def test_stale_report(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); (out/'staging.pptx').write_bytes(b'changed')
            write_json(out/'qa_report.json',report([],'old-hash'))
            with self.assertRaisesRegex(ValueError,'staging'): promote(out)
            self.assertFalse((out/'final.pptx').exists())
    def test_native_required(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); (out/'staging.pptx').write_bytes(b'candidate')
            write_json(out/'deck_ir.json',fixture()); write_json(out/'layout.json',{})
            qa=report([],file_hash(out/'staging.pptx'),digest(fixture()),{'structural':True,'native':False})
            qa['layout_sha256']=file_hash(out/'layout.json'); write_json(out/'qa_report.json',qa)
            with self.assertRaisesRegex(ValueError,'golden'): promote(out)
    def test_compatibility(self):
        i=issue('RENDER','WARNING','difference',detector='native-visual',renderer='libreoffice')
        self.assertEqual(i['diagnosis'],'compatibility')

    def test_native_import_rejects_non_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); fake=out/'native.pdf'; fake.write_bytes(b'not a PDF')
            with self.assertRaisesRegex(ValueError,'required'):
                ingest_native(out,fake)

    def test_powerpoint_review_binds_every_slide(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); (out/'staging.pptx').write_bytes(b'candidate')
            write_json(out/'layout.json',{'slides':[{'id':'a'},{'id':'b'}]})
            with self.assertRaisesRegex(ValueError,'every slide'):
                record_powerpoint_review(out,'reviewer',['a'])
            path=record_powerpoint_review(out,'reviewer',['all'])
            evidence=json.loads(path.read_text())
            self.assertEqual(evidence['method'],'powerpoint-ui')
            self.assertEqual(evidence['reviewed_slide_ids'],['a','b'])

    def test_promotion_requires_direct_powerpoint_review(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d); (out/'staging.pptx').write_bytes(b'candidate')
            (out/'native.pdf').write_bytes(b'%PDF fake')
            write_json(out/'deck_ir.json',fixture()); write_json(out/'layout.json',{'slides':[]})
            qa=report([],file_hash(out/'staging.pptx'),digest(fixture()),
                      {'structural':True,'native':True,'visual_review':False})
            qa['layout_sha256']=file_hash(out/'layout.json'); write_json(out/'qa_report.json',qa)
            with self.assertRaisesRegex(ValueError,'PowerPoint UI review'):
                promote(out)

if __name__=='__main__': unittest.main()
