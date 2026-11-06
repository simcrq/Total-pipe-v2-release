"""Regression cases from the real rewrite failure, with explicitly synthetic science."""
import copy
import shutil
import unittest

import jsonschema
from PIL import Image

from agent import COMPONENT, adapters as a, runner, science_review
from agent.state import read, write
from agent.ir_pages import bind_sources
from agent_fixture import AgentCase
from atomic_fixture import atomic_story, atomic_workflow, atomic_design, synthetic_science_review
from test_content_projection import authored_ir, synthetic_review
from deck_compiler.design import validate_design
from deck_compiler.content_projection import validate_ir, visible_slots
from deck_compiler.pipeline import compile_input
from pwf2rpa.content_contract import catalog, validate_contract


class AtomicProjectionTests(AgentCase):
    def prepare(self):
        self.story=atomic_story();self.design=atomic_design(self.story);self.flow=atomic_workflow(self.story)
        self.ev={x['evidence_id']:x['text'] for x in self.flow['evidence_registry']}
        work=self.out/'work';source=self.root/'workflow.json'
        write(source,self.flow);write(work/'evidence_pointer.json',{'workflow':str(source)})
        write(work/'story_plan.json',self.story);write(work/'page_design.json',self.design)
        write(work/'scientific_review.json',synthetic_science_review(work,self.story))
        write(work/'page_design_review.json',synthetic_review(work,self.design))
        return work

    def test_independent_assertions_prevent_oracle_conditions_leaking_into_detector_or_conceptual_summary(self):
        self.prepare()
        self.assertEqual(validate_contract(self.story),[])
        self.assertEqual(validate_design(self.design,self.story,self.ev,5),[])
        jsonschema.validate(self.story,read(COMPONENT/'pwf2rpa/schemas/story-plan.schema.json'))
        jsonschema.validate(self.design,read(COMPONENT/'schemas/page-design-v1.3.schema.json'))
        bound=a.load_design(self.out/'work')
        for i in (2,4):
            self.assertNotIn('Q_oracle',[x['source'] for x in bound['pages'][i]['context_items']])
        ir=bind_sources(authored_ir(self.design),bound,self.out/'work',self.out/'work/draft.json')
        self.assertEqual(a.ir_issues(ir,design=bound,slide_count=5),[])

    def test_numeric_restatement_reuses_original_assertion_and_must_show_its_conditions(self):
        self.prepare();page=self.design['pages'][-1]
        page['reuse_refs'].append('C_oracle')
        page['display_copy'].append({'id':'again','role':'body','text':'Oracle-MNIST: 98.58%.','source_refs':['C_oracle']})
        page['content_map']['C_oracle']={'destination':'visible','carriers':[{'kind':'copy','ref':'again'}]}
        self.assertIn('Q_oracle',' '.join(validate_design(self.design,self.story,self.ev)))
        page['display_copy'].append({'id':'conditions','role':'caption','text':self.story['content_contract']['units']['Q_oracle']['text'],'source_refs':['Q_oracle']})
        page['content_map']['Q_oracle']={'destination':'visible','carriers':[{'kind':'copy','ref':'conditions'}]}
        self.assertEqual(validate_design(self.design,self.story,self.ev),[])
        self.assertEqual(sum('C_oracle' in p['content_refs'] for p in self.design['pages']),1)

    def test_qualifiers_cannot_target_paragraphs_or_other_qualifiers(self):
        self.prepare()
        for target in ('S3.answer','Q_fashion','Q_oracle'):
            value=copy.deepcopy(self.story);value['content_contract']['units']['Q_oracle']['applies_to']=[target]
            self.assertTrue(validate_contract(value),target)
        value=copy.deepcopy(self.story);value['content_contract']['narrative_map'].pop('S3.answer')
        self.assertTrue(validate_contract(value))
        value=copy.deepcopy(self.story);value['content_contract']['units']['Q_oracle']['evidence']=['EV9999']
        self.assertTrue(validate_contract(value))

    def test_review_is_required_before_page_design_and_cannot_be_faked_by_page_review_only(self):
        work=self.prepare();(work/'scientific_review.json').unlink()
        with self.assertRaises(a.Failure):a.load_design(work)
        write(work/'scientific_review.json',synthetic_science_review(work,self.story))
        value=read(work/'scientific_review.json');value['coverage']={'status':'fail','note':'A preparation step in the source was omitted from the ledger.'}
        with self.assertRaises(science_review.ReviewRejected):science_review.validate(work,value)
        value=synthetic_science_review(work,self.story);value['decisions'][0]['unit_refs'].pop()
        with self.assertRaises(ValueError):science_review.validate(work,value)

    def test_figure_ids_are_bound_provenance_but_measurements_are_still_checked(self):
        work=self.prepare();page=self.design['pages'][2]
        pic=self.root/'synthetic-source.png';Image.new('RGB',(800,500),'#dfeef1').save(pic)
        page['figures']=[str(pic)];page['figure_sources']={str(pic):{'source_figure':'S11'}}
        page['display_copy'].append({'id':'cap','role':'caption','text':'Fig. S11 — 响应度对照','source_refs':['C_detector']})
        self.assertEqual(validate_design(self.design,self.story,self.ev),[])
        for label in ('图S11：响应度对照', 'S11响应度对照'):
            page['display_copy'][-1]['text']=label
            self.assertEqual(validate_design(self.design,self.story,self.ev),[],label)
        page['display_copy'][-1]['text']='Fig. S11 — 700 nm响应度对照'
        self.assertIn('number 700',' '.join(validate_design(self.design,self.story,self.ev)))
        page['display_copy'][-1]['text']='Fig. S99 — 响应度对照'
        self.assertIn('reference S99',' '.join(validate_design(self.design,self.story,self.ev)))
        page['display_copy'][-1]['text']='响应度对照'
        write(work/'page_design.json',self.design);write(work/'page_design_review.json',synthetic_review(work,self.design))
        ir=authored_ir(self.design);ir['assets']={str(pic):{'path':str(pic),'origin':'paper'}}
        s=ir['slides'][2];s['composition']['figure_refs']=[{'asset_id':str(pic),'caption':{'copy_ref':'cap'}}]
        s['composition']['layout_tree']['regions']['body']['children'].append({'id':'source','type':'figure','ref':0})
        ir=bind_sources(ir,a.load_design(work),work,work/'draft.json')
        self.assertEqual(ir['slides'][2]['composition']['figure_refs'][0]['source_label'],'本文 Fig. S11')
        self.assertEqual(a.ir_issues(ir,design=a.load_design(work),slide_count=5),[])
        ir['slides'][2]['composition']['figure_refs'][0]['source_label']+=' 700 nm'
        self.assertTrue(validate_ir(ir['slides'][2],ir['assets']))

    def test_signed_conditions_and_epistemic_identity_are_not_lost_during_projection(self):
        work=self.prepare();self.ev['EV0004']+=' VCG=+1 V.'
        page=self.design['pages'][2]
        page['display_copy'][-1]['text']='VCG=-1 V.'
        self.assertIn('number -1',' '.join(validate_design(self.design,self.story,self.ev)))
        ir=bind_sources(authored_ir(atomic_design(self.story)),a.load_design(work),work,work/'draft.json')
        self.assertIn('[author_claim]',ir['slides'][2]['semantic']['speaker_notes'])
        ir['slides'][2]['semantic']['speaker_notes']=self.story['content_contract']['units']['C_detector']['text']
        self.assertTrue(any('epistemic identity' in m for _,_,m in validate_ir(ir['slides'][2],{})))

    def test_native_caption_realizes_approved_copy_at_existing_caption_scale(self):
        work=self.prepare();page=self.design['pages'][0]
        for id,text in [('in','Input'),('pre','Preprocessing'),('out','Memory')]:
            page['display_copy'].append({'id':id,'role':'label','text':text,'source_refs':['C_modes']})
        page['display_copy'].append({'id':'cap','role':'caption','text':'功能分工示意','source_refs':['C_modes']})
        write(work/'page_design.json',self.design);write(work/'page_design_review.json',synthetic_review(work,self.design))
        ir=authored_ir(self.design);comp=ir['slides'][0]['composition']
        comp['graphics']=[{'id':'mode_flow','type':'process','direction':'horizontal','nodes':[{'id':id,'title':{'copy_ref':id}} for id in ('in','pre','out')],
            'edges':[{'from':'in','to':'pre'},{'from':'pre','to':'out'}]}]
        comp['blocks'].append({'id':'diagram_caption','component':'caption','text':{'copy_ref':'cap'},'caption_for':{'kind':'graphic','ref':'mode_flow'}})
        comp['layout_tree']['regions']['body']['children'] += [{'id':'flow','type':'graphic','ref':'mode_flow'},{'id':'cap_leaf','type':'block','ref':'diagram_caption'}]
        ir=bind_sources(ir,a.load_design(work),work,work/'draft.json');write(work/'draft.json',ir)
        jsonschema.validate(ir,read(COMPONENT/'schemas/deck-ir.schema.json'))
        _,layout,qa=compile_input(work/'draft.json',self.out/'caption-build',{'name':'packer'},require_visual_design=False)
        self.assertEqual(qa['counts']['FAIL'],0,qa['items'])
        element=next(e for e in layout['slides'][0]['elements'] if e['id']=='diagram_caption')
        self.assertEqual(element['role'],'caption');self.assertEqual(element['contract']['font_size'],20)
        self.assertIn(('caption','功能分工示意'),visible_slots(ir['slides'][0]))
        bad=copy.deepcopy(ir);bad['slides'][0]['composition']['blocks'][-1]['caption_for']['ref']='missing'
        self.assertTrue(any(x['rule']=='CAPTION_ANCHOR_INVALID' for x in __import__('deck_compiler.ir',fromlist=['validate']).validate(bad)))


class AtomicRunnerTests(AgentCase):
    def start_science(self):
        story=atomic_story();source=self.root/'workflow.json';write(source,atomic_workflow(story))
        result=runner.start(str(source),str(self.out),'en','group_meeting',source_kind='workflow',slide_count=5)
        result=runner.advance(result['job_id'],inputs={'model':'test-model','reasoning_effort':'high','selected_by_user':True})
        self.assertEqual(read(self.out/'work/story_prompt.json')['content_contract_version'],'2.0')
        write(self.out/'work/story_plan.json',story)
        result=runner.advance(result['job_id'],artifact_kind='story_plan',artifact_path=str(self.out/'work/story_plan.json'))
        self.assertEqual(result['stage'],'scientific_review',result)
        return story,result

    def test_missing_prerequisite_rejects_to_story_before_any_page_design(self):
        story,result=self.start_science();work=self.out/'work'
        self.assertFalse((work/'page_design_prompt.json').exists())
        review=synthetic_science_review(work,story);review['coverage']={'status':'fail','note':'Original source requires an initialization pulse absent from the ledger.'};write(work/'scientific_review.json',review)
        result=runner.advance(result['job_id'],artifact_kind='scientific_review',artifact_path=str(work/'scientific_review.json'))
        self.assertEqual(result['next_action']['target_stage'],'story');self.assertEqual(result['next_action']['reason'],'SCIENTIFIC_REVIEW_REJECTED')
        self.assertFalse((work/'page_design_prompt.json').exists())

    @unittest.skipUnless(shutil.which('officecli'),'OfficeCLI required')
    def test_atomic_source_and_copy_reviews_bind_through_an_editable_candidate(self):
        story,result=self.start_science();work=self.out/'work'
        write(work/'scientific_review.json',synthetic_science_review(work,story))
        result=runner.advance(result['job_id'],artifact_kind='scientific_review',artifact_path=str(work/'scientific_review.json'))
        self.assertEqual(result['stage'],'page_design',result)
        self.assertEqual(read(work/'page_design_prompt.json')['shape']['schema_version'],'1.3')
        design=atomic_design(story);write(work/'page_design.json',design)
        result=runner.advance(result['job_id'],artifact_kind='page_design',artifact_path=str(work/'page_design.json'))
        self.assertEqual(result['stage'],'page_review',result)
        write(work/'page_design_review.json',synthetic_review(work,design))
        result=runner.advance(result['job_id'],artifact_kind='page_design_review',artifact_path=str(work/'page_design_review.json'))
        self.assertEqual(result['stage'],'deck_ir',result)
        write(work/'draft.json',authored_ir(design));result=runner.advance(result['job_id'],artifact_kind='deck_ir',artifact_path=str(work/'draft.json'))
        self.assertEqual(result['status'],'candidate_ready',result)
        self.assertEqual(result['qa']['counts']['FAIL'],0)
        self.assertTrue((self.out/'build/candidate.pptx').is_file())
