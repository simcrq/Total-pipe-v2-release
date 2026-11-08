"""Four-tool server reusing the existing stdio transport (no MCP client)."""
import importlib.util
import json
from pathlib import Path

from . import COMPONENT, VERSION
from .doctor import doctor
from .runner import start, advance, status

spec = importlib.util.spec_from_file_location('agent_transport', COMPONENT/'pwf2rpa/integrations/mcp/server.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
transport.SERVER_NAME, transport.SERVER_VERSION = 'total-pipe-agent', VERSION
transport.INSTRUCTIONS = ('Drive the evidence-to-candidate workflow using next_action. Read only the indicated full prompt. '
    'Agent-authored queries, Story, canonical IR and visual proposal retain scientific content. '
    'Story requires a real independent subagent and the user’s explicit model choice. Never invent provenance. '
    'When status is running, call advance; when blocked, resolve the reported issue. '
    'New atomic Stories use scientific_review before RPA, page design 1.3 and actual source/copy review before IR. '
    'Scientific records are archived; approved audience copy and scoped qualifiers must be visible. Never auto-attest review. '
    'Native render/review/ingest are explicit advance operations after candidate. Never auto-attest UI review. '
    'Candidate REVIEW notes do not satisfy PowerPoint final promotion; final remains CLI-only.')

STRING = {'type': 'string', 'minLength': 1}
DEFINITIONS = {
    'totalpipe_doctor': (doctor, {'deep': {'type': 'boolean'}, 'source_kind': {'type': 'string', 'enum': ['pdf','markdown','workflow','deck_ir']},
        'page_mode': {'type': 'string', 'enum': ['deck_ir','page_scene'], 'default': 'deck_ir'}}, []),
    'totalpipe_start': (start, {'source': STRING, 'out_dir': STRING, 'language': STRING, 'presentation_type': STRING,
        'source_kind': {'type': 'string', 'enum': ['auto','pdf','markdown','workflow','deck_ir']}, 'requirements': {'type': 'string'},
        'queries': {'type': 'array'}, 'supplementary_paths': {'type': 'array', 'items': STRING},
        'supplementary_content_included': {'type': 'boolean'},
        'supplement': {'type': 'string', 'enum': ['off', 'inline', 'pages', 'both']},
        'explain_viz_mode': {'enum': ['auto', 'off', 'prefer'], 'default': 'auto',
                             'description': 'Automatic native teaching diagrams and bounded body reflow; off disables.'},
        'page_mode': {'type': 'string', 'enum': ['deck_ir', 'page_scene'], 'default': 'deck_ir',
                      'description': 'deck_ir preserves the full compiler/OfficeCLI object model; page_scene builds explicit native page boxes with PageScene path/formula/chart support.'},
        'slide_count': {'type': 'integer', 'minimum': 1, 'maximum': 40,
                        'description': 'Final paper-page target, independent of Story nodes/briefs; standalone supplement pages are extra.'}}, ['source','out_dir','language','presentation_type']),
    'totalpipe_advance': (advance, {'job_id': STRING, 'artifact_kind': {'type': 'string', 'enum': ['queries','story_plan','scientific_review','page_design','page_design_review','page_scene','deck_ir','deck_ir_page','visual_proposal','deck_ir_patch']},
        'artifact_path': STRING, 'preflight': {'type': 'boolean', 'description': 'Validate Deck IR and geometry without acceptance, writes to the job or revision accounting.'}, 'inputs': {'type': 'object', 'properties': {'model': STRING,
            'reasoning_effort': {'type': 'string', 'enum': ['high','xhigh','max','ultra']}, 'selected_by_user': {'const': True}},
            'required': ['model','reasoning_effort','selected_by_user'], 'additionalProperties': False},
        'replan_from': STRING, 'acknowledge': {'type': 'object', 'properties': {'reviewer': STRING, 'note': STRING,
            'review_ids': {'type': 'array', 'minItems': 1, 'items': STRING}},
            'required': ['reviewer','note','review_ids'], 'additionalProperties': False},
        'preview': {**json.loads((Path(__file__).parent/'schemas/ir-preview.schema.json').read_text(encoding='utf-8')),
                    'description': 'Render selected draft IR pages to cached HTML PNGs without acceptance, revision use or candidate changes. Open PNGs, edit IR, repeat.'},
        'scene_preview': json.loads((Path(__file__).parent/'schemas/page-scene-preview.schema.json').read_text(encoding='utf-8')),
        'native': json.loads((Path(__file__).parent/'schemas/native-acceptance.schema.json').read_text(encoding='utf-8'))}, ['job_id']),
    'totalpipe_status': (status, {'job_id': STRING,
        'detail': {'type': 'string', 'enum': ['summary', 'full'], 'default': 'summary'}}, ['job_id']),
}


def validate(value, schema):
    expected = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list), 'string': isinstance(value, str),
             'integer': type(value) is int, 'boolean': type(value) is bool}
    if expected and not valid[expected]:
        raise ValueError(f'Expected {expected}')
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise ValueError('Invalid constant')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('Invalid enum value')
    if expected == 'object':
        properties = schema.get('properties', {})
        if any(k not in value for k in schema.get('required', [])) or (schema.get('additionalProperties') is False and set(value)-set(properties)):
            raise ValueError('Missing or unknown arguments')
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key])
    if expected == 'array':
        if len(value) < schema.get('minItems', 0):
            raise ValueError('Array is empty')
        for item in value:
            validate(item, schema.get('items', {}))
    if expected == 'string' and len(value.strip()) < schema.get('minLength', 0):
        raise ValueError('String is empty')
    if expected == 'integer' and not schema.get('minimum', value) <= value <= schema.get('maximum', value):
        raise ValueError('Integer outside supported range')


transport.TOOLS = {}
for name, (function, properties, required) in DEFINITIONS.items():
    schema = {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}
    def handler(arguments, function=function, schema=schema):
        validate(arguments, schema)
        for key in ('source', 'out_dir', 'artifact_path'):
            if key in arguments and not Path(arguments[key]).is_absolute():
                raise ValueError(f'{key} must be an absolute path')
        if any(not Path(path).is_absolute() for path in arguments.get('supplementary_paths', [])):
            raise ValueError('supplementary_paths must be absolute')
        return function(**arguments)
    transport.TOOLS[name] = {'description': {'totalpipe_doctor': 'Check prerequisites and candidate/native capabilities.',
        'totalpipe_start': 'Start or resume a job from PDF, Markdown, workflow or Deck IR; never supplies a model implicitly.',
        'totalpipe_advance': 'Accept an explicit artifact or user input, then advance until the next decision or candidate. scene_preview renders selected PageScene pages natively without acceptance.',
        'totalpipe_status': 'Read state and QA without writes or running components. Defaults to a compact summary; detail=full adds request and artifact inventory.'}[name],
        'handler': handler, 'inputSchema': schema, 'timeout': 1800}


if __name__ == '__main__':
    raise SystemExit(transport.main())
