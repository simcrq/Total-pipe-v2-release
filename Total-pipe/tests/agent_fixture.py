import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import COMPONENT
from agent.state import write, read


def workflow():
    return {'schema_version': 4, 'source': {'source_sha256': 'a'*64, 'source_fingerprint': 'test'},
        'metadata': {'title_guess': 'A paper'}, 'synthesis_readiness': {'readiness': 'ready'},
        'evidence_registry': [{'evidence_id': f'EV{i:04d}', 'text': f'Observation {i} supports the measured effect.',
            'query_ids': ['results'], 'modality': 'body_text', 'support_type': 'direct_observation'} for i in range(1, 9)]}


def story():
    return {'planner': {'mode': 'subagent', 'model': 'test-model', 'reasoning_effort': 'high', 'selected_by_user': True},
        'core_question': 'Does the effect persist?', 'main_message': 'The measured effect is reproducible.',
        'story': [{'question': f'Question {i}?', 'answer': f'Observation {i} establishes the effect.',
                   'evidence': [f'EV{i:04d}'], 'next': 'But an independent control is needed.'} for i in range(1, 6)],
        'ending': {'takeaway': 'The effect is measured.', 'limitation': 'Only tested conditions.'}}


class AgentCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='totalpipe-agent-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.out = self.root/'out'
        self.env = patch.dict(os.environ, {'TOTALPIPE_AGENT_HOME': str(self.root/'registry')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.source = self.root/'paper.md'
        self.source.write_text('# A paper\n\nMeasured response increases with applied field.\n', encoding='utf-8')

    def fixture_ir(self):
        source = COMPONENT/'examples/complex-mixed/complex-mixed.deck_ir.json'
        return source

    def fake_evidence(self, stage, job):
        if stage != 'evidence':
            from agent.adapters import execute
            return execute(stage, job)
        out = Path(job['request']['out_dir'])
        write(out/'evidence/workflow.json', workflow())
        write(out/'work/evidence_pointer.json', {'workflow': str(out/'evidence/workflow.json')})
        return [out/'evidence', out/'work/evidence_pointer.json']
