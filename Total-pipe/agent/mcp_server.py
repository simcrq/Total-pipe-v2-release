"""Four-tool server using the shared Total-pipe stdio MCP transport."""
import json
import re
from pathlib import Path

from deck_compiler.mcp_transport import StdioMcpServer
from . import VERSION
from .doctor import doctor
from .requests import PAGE_MODES, SOURCE_KINDS
from .runner import start, advance, status

transport = StdioMcpServer(
    server_name='total-pipe-agent',
    server_version=VERSION,
    instructions=(
        'Drive the workflow using next_action. Read only the indicated full prompt. '
        'For a topic or question, start with source_kind=topic and the text as source. Author topic content and page design, '
        'use the example library, then implement PageScene. Model delegation is optional for topic jobs. '
        'Agent-authored queries, Story, canonical IR and visual proposal retain scientific content. '
        'Paper Story requires a real independent subagent and the user’s explicit model choice; use advance.evidence_query '
        'or story_prompt.evidence_lookup to search the evidence registry, full paper Markdown, and SI on demand. Never invent EV IDs. '
        'When status is running, call advance; when blocked, resolve the reported issue. '
        'New atomic Stories use scientific_review before RPA, page design 1.3 and actual source/copy review before IR. '
        'During page_design, you may co-design and live-debug single-page Deck IR drafts via advance.preview before submission. '
        'At deck_ir, dispatch at most 2 parallel IR subagents (one per batch in page_authoring.parallel_authoring.batches). '
        'Scientific records are archived; approved audience copy and scoped qualifiers must be visible. Never auto-attest review. '
        'Native render/review/ingest are explicit advance operations after candidate. Never auto-attest UI review. '
        'Candidate REVIEW notes do not satisfy PowerPoint final promotion; final remains CLI-only.'
    ),
)

STRING = {'type': 'string', 'minLength': 1}
DEFINITIONS = {
    'totalpipe_doctor': (doctor, {'deep': {'type': 'boolean'}, 'source_kind': {'type': 'string', 'enum': list(SOURCE_KINDS)},
        'page_mode': {'type': 'string', 'enum': list(PAGE_MODES),
                      'description': 'Defaults to page_scene for topic, deck_ir otherwise.'}}, []),
    'totalpipe_start': (start, {'source': {**STRING, 'description': 'Absolute file path, or raw topic/question text for source_kind=topic.'},
        'out_dir': STRING, 'language': {**STRING, 'description': 'Required for file sources. Topics default to auto.'},
        'presentation_type': {**STRING, 'description': 'Required for file sources. Topics default to custom.'},
        'source_kind': {'type': 'string', 'enum': ['auto', *SOURCE_KINDS]}, 'requirements': {'type': 'string'},
        'queries': {'type': 'array'}, 'supplementary_paths': {'type': 'array', 'items': STRING},
        'supplementary_content_included': {'type': 'boolean'},
        'supplement': {'type': 'string', 'enum': ['off', 'inline', 'pages', 'both']},
        'explain_viz_mode': {'enum': ['auto', 'off', 'prefer'], 'default': 'auto',
                             'description': 'Automatic native teaching diagrams and bounded body reflow; off disables.'},
        'page_mode': {'type': 'string', 'enum': list(PAGE_MODES),
                      'description': 'Topics default to page_scene (or opt into deck_ir for automatic layout/native components). File sources default to deck_ir.'},
        'slide_count': {'type': 'integer', 'minimum': 1, 'maximum': 40,
                        'description': 'Optional page target. For paper jobs standalone supplement pages are extra.'}}, ['source','out_dir']),
    'totalpipe_advance': (advance, {'job_id': STRING, 'artifact_kind': {'type': 'string', 'enum': ['queries','story_plan','scientific_review','page_design','page_design_review','page_scene','deck_ir','deck_ir_page','visual_proposal','deck_ir_patch']},
        'artifact_path': STRING, 'preflight': {'type': 'boolean', 'description': 'Validate Deck IR and geometry without acceptance, writes to the job or revision accounting.'}, 'inputs': {'type': 'object', 'properties': {'model': STRING,
            'reasoning_effort': {'type': 'string', 'enum': ['high','xhigh','max','ultra']}, 'selected_by_user': {'const': True}},
            'required': ['model','reasoning_effort','selected_by_user'], 'additionalProperties': False},
        'replan_from': STRING, 'acknowledge': {'type': 'object', 'properties': {'reviewer': STRING, 'note': STRING,
            'review_ids': {'type': 'array', 'minItems': 1, 'items': STRING}},
            'required': ['reviewer','note','review_ids'], 'additionalProperties': False},
        'preview': {**json.loads((Path(__file__).parent/'schemas/ir-preview.schema.json').read_text(encoding='utf-8')),
                    'description': 'Render selected draft IR pages to cached skeleton/HTML PNGs without acceptance, revision use or candidate changes. Available from page_design onward.'},
        'scene_preview': json.loads((Path(__file__).parent/'schemas/page-scene-preview.schema.json').read_text(encoding='utf-8')),
        'evidence_query': {**json.loads((Path(__file__).parent/'schemas/evidence-query.schema.json').read_text(encoding='utf-8')),
                           'description': 'Read-only evidence retrieval across evidence_registry (exact EV IDs), full paper Markdown, and paired SI during story/review/design.'},
        'figure_crop': {**json.loads((Path(__file__).parent/'schemas/figure-crop.schema.json').read_text(encoding='utf-8')),
                        'description': 'Inspect multi-panel figures with a pixel ruler grid or extract lossless rectangular sub-panel crops certified by crops.verified_source().'},
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
    elif 'required' in schema and isinstance(value, dict):
        if any(k not in value for k in schema['required']):
            raise ValueError('Missing required arguments')
    if expected == 'array':
        if len(value) < schema.get('minItems', 0):
            raise ValueError('Array is empty')
        if 'maxItems' in schema and len(value) > schema['maxItems']:
            raise ValueError('Array exceeds maxItems')
        if schema.get('uniqueItems'):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(set(encoded)) != len(encoded):
                raise ValueError('Array items must be unique')
        for item in value:
            validate(item, schema.get('items', {}))
    if expected == 'string':
        if len(value.strip()) < schema.get('minLength', 0):
            raise ValueError('String is empty')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise ValueError('String does not match required pattern')
    if expected == 'integer' and not schema.get('minimum', value) <= value <= schema.get('maximum', value):
        raise ValueError('Integer outside supported range')
    if 'not' in schema:
        try:
            validate(value, schema['not'])
        except ValueError:
            pass
        else:
            raise ValueError('Value matches forbidden schema branch')
    for branch_key, exact_one in (('anyOf', False), ('oneOf', True)):
        if branch_key in schema:
            matched = 0
            for subschema in schema[branch_key]:
                try:
                    validate(value, subschema)
                    matched += 1
                except ValueError:
                    continue
            if (matched != 1) if exact_one else (matched == 0):
                raise ValueError(f'Value failed {branch_key} constraint')


transport.TOOLS = {}
for name, (function, properties, required) in DEFINITIONS.items():
    schema = {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}
    def handler(arguments, function=function, schema=schema):
        validate(arguments, schema)
        paths = ('out_dir', 'artifact_path') if arguments.get('source_kind') == 'topic' else ('source', 'out_dir', 'artifact_path')
        for key in paths:
            if key in arguments and not Path(arguments[key]).is_absolute():
                raise ValueError(f'{key} must be an absolute path')
        if any(not Path(path).is_absolute() for path in arguments.get('supplementary_paths', [])):
            raise ValueError('supplementary_paths must be absolute')
        return function(**arguments)
    transport.TOOLS[name] = {'description': {'totalpipe_doctor': 'Check prerequisites and candidate/native capabilities.',
        'totalpipe_start': 'Start or resume a job from a topic, PDF, Markdown, workflow or Deck IR.',
        'totalpipe_advance': 'Accept an explicit artifact or user input, then advance until the next decision or candidate. scene_preview renders selected PageScene pages natively without acceptance.',
        'totalpipe_status': 'Read state and QA without writes or running components. Defaults to a compact summary; detail=full adds request and artifact inventory.'}[name],
        'handler': handler, 'inputSchema': schema, 'timeout': 1800}


if __name__ == '__main__':
    raise SystemExit(transport.main())
