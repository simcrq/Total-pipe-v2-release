"""Explicit synthetic science; never a model invocation or real source acceptance."""
from agent.state import sha, read
from agent_fixture import workflow


def atomic_story():
    def unit(text, ev, kind='claim', visibility='required', **extra):
        return dict(text=text, evidence=[ev], kind=kind, visibility=visibility, epistemic='author_claim', **extra)
    units = {
        'C_cost': unit('Separated sensing and processing require data transfer.', 'EV0001'),
        'C_fashion': unit('Noisy Fashion-MNIST accuracy improves from 16% to 62%.', 'EV0002'),
        'Q_fashion': unit('Gaussian noise; identical training conditions.', 'EV0003', 'condition', 'with_claim', applies_to=['C_fashion']),
        'C_detector': unit('Responsivity is 1.11 mA/W.', 'EV0004'),
        'C_oracle': unit('Oracle-MNIST accuracy is 98.58%.', 'EV0005'),
        'Q_oracle': unit('Oracle-MNIST uses 8000 training and 2000 test images.', 'EV0006', 'condition', 'with_claim', applies_to=['C_oracle']),
        'C_modes': unit('The same device supplies preprocessing and temporal memory.', 'EV0007'),
        'U_scope': unit('The reported sample limits generalization.', 'EV0008', 'scope')}
    narrative = {
        'S1.answer':['C_cost'], 'S2.answer':['C_fashion','Q_fashion'],
        'S3.answer':['C_detector','C_oracle','Q_oracle'], 'S4.answer':['C_modes','U_scope'],
        'ending.takeaway':['C_modes'], 'ending.limitation':['U_scope']}
    nodes=[]
    for i in range(1,5):
        refs=narrative[f'S{i}.answer']
        nodes.append({'question':'Which observation constrains this scientific step?',
                      'title':'Evidence supports the tested response',
                      'answer':' '.join(units[r]['text'] for r in refs),
                      'evidence':list(dict.fromkeys(ev for r in refs for ev in units[r]['evidence'])),
                      'next':'But an independent test is needed to constrain interpretation.'})
    return {'planner':{'mode':'subagent','model':'test-model','reasoning_effort':'high','selected_by_user':True},
            'core_question':'Can one device supply both functions?', 'main_message':units['C_modes']['text'],
            'story':nodes,'ending':{'takeaway':units['C_modes']['text'],'limitation':units['U_scope']['text']},
            'content_contract':{'version':'2.0','units':units,'narrative_map':narrative}}


def atomic_workflow(story):
    flow=workflow()
    flow['evidence_registry']=[{'evidence_id':u['evidence'][0], 'text':u['text'], 'query_ids':['results'],
        'modality':'body_text','support_type':'direct_observation'} for u in story['content_contract']['units'].values()]
    return flow


def atomic_design(story):
    units=story['content_contract']['units']
    assignments=[['C_cost','C_modes'],['C_fashion','Q_fashion'],['C_detector'],['C_oracle','Q_oracle'],['U_scope']]
    pages=[]
    for i,owned in enumerate(assignments,1):
        refs=owned+(['C_modes'] if i==5 else [])
        title_ref=refs[0] if i!=5 else 'C_modes'
        copies=[{'id':'title','role':'title','text':units[title_ref]['text'],'source_refs':[title_ref]},
                {'id':'take','role':'takeaway','text':units[title_ref]['text'],'source_refs':[title_ref]},
                {'id':'lead','role':'body','text':units[title_ref]['text'],'source_refs':[title_ref]}]
        routes={title_ref:{'destination':'visible','carriers':[{'kind':'copy','ref':'take'}]}}
        for r in refs:
            if r==title_ref:continue
            copies.append({'id':r,'role':'body','text':units[r]['text'],'source_refs':[r]})
            routes[r]={'destination':'visible','carriers':[{'kind':'copy','ref':r}]}
        pages.append({'id':f'P{i}','content_refs':owned,'reuse_refs':['C_modes'] if i==5 else [],
                      'figures':[],'figure_sources':{},'display_copy':copies,'content_map':routes,
                      'design':'Explain the distinct assertion and its directly applicable conditions. No inherited unrelated task.'})
    return {'schema_version':'1.3','deck_id':'atomic-synthetic','setting':{'audience':'Peers unfamiliar with the source',
        'occasion':'group-meeting','reading':'spoken'},'pages':pages}


def synthetic_science_review(work, story):
    note={'status':'pass','note':'Explicit synthetic test source audit; no real paper/model review claimed.'}
    return {'schema_version':'1.0','method':'agent-source-review','reviewer':'Synthetic test reviewer',
            'story_sha256':sha(work/'story_plan.json'),'workflow_sha256':sha(read(work/'evidence_pointer.json')['workflow']),
            'coverage':dict(note),'decisions':[{'id':'synthetic-topic','unit_refs':list(story['content_contract']['units']),
             'checks':{k:dict(note) for k in ('evidence_fidelity','atomic_scope','essential_conditions')}}]}
