"""Total-pipe v3 low-level compiler MCP server (advanced profile)."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from .mcp_transport import StdioMcpServer

ROOT = Path(__file__).resolve().parents[1]
SAFE_PWF2RPA_TOOLS = (
    'pwf2rpa_story_prompt',
    'pwf2rpa_check',
    'pwf2rpa_convert',
    'pwf2rpa_list_categories',
)


def _load_pwf2rpa_tools():
    """Import only read-only/conversion pwf2rpa tools; never expose capacity refresh over MCP."""
    spec = importlib.util.spec_from_file_location('pwf2rpa_mcp_tools', ROOT/'pwf2rpa/integrations/mcp/server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {name: module.TOOLS[name] for name in SAFE_PWF2RPA_TOOLS if name in module.TOOLS}


transport = StdioMcpServer(
    server_name='total-pipe-v3',
    server_version='3.2.0',
    instructions=(
        'Total-pipe v3.2 low-level compiler tools (advanced profile). '
        'Query totalpipe_capabilities for layout_tree, ExplainViz, math, table, graphic and backend contracts. '
        'Author canonical Deck IR v2.0 (see schemas/deck-ir.schema.json) without page coordinates; '
        'keep complete scientific terminology (preserve-terms emits REVIEW rather than truncating). '
        'Run totalpipe_visual_prompt -> totalpipe_apply_visual_plan before totalpipe_compile/totalpipe_build '
        '(use skip_visual_design=true only for explicitly requested legacy builds). '
        'ExplainViz defaults to auto (mode=off disables). '
        'totalpipe_build produces an OfficeCLI candidate PPTX + QA report, not final approval. '
        'Use totalpipe_review for on-demand screenshots, totalpipe_qa to inspect pending REVIEW items, '
        'and totalpipe_ack_review only after actual inspection; final promotion remains CLI-only.'
    ),
    tools=_load_pwf2rpa_tools(),
)


def capability_handler(arguments):
    if arguments:
        raise ValueError('No arguments supported')
    from .layout_tree import capabilities
    from .explain_viz.specs import capabilities as explain_capabilities
    return {'deck_ir_version': '2.0', 'layout_tree': capabilities(),
            'explain_viz': explain_capabilities(),
            'backend': {'name': 'officecli', 'minimum_version': '1.0.152', 'runtime_probe_required': True}}


transport.TOOLS['totalpipe_capabilities'] = {'description': 'Declare compiler region-tree contracts and required native backend capabilities; runtime OfficeCLI support is checked again at build time.',
    'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    'handler': capability_handler, 'timeout': 10}

BUILTIN_PROVIDERS = {'packer', 'compiler', 'deterministic', 'none'}


def _check_executables(arguments):
    """MCP arguments may select built-in behaviour only, never arbitrary code or executables."""
    provider = arguments.get('layout_provider')
    if provider is not None and provider not in BUILTIN_PROVIDERS:
        raise ValueError('layout_provider over MCP must be one of ' + ', '.join(sorted(BUILTIN_PROVIDERS))
                         + '; external module:factory providers are CLI-only')
    officecli = arguments.get('officecli')
    if officecli is not None and Path(officecli).stem.lower() != 'officecli':
        raise ValueError('officecli must name the OfficeCLI executable (officecli or a path ending in it)')


def invoke(command, arguments):
    argv = [sys.executable, '-m', 'deck_compiler', command, '--out', arguments['out']]
    if command in ('compile', 'build'):
        argv += ['--ir', arguments['ir'], '--layout-provider', arguments.get('layout_provider', 'packer')]
        if arguments.get('skip_visual_design', False):
            argv += ['--skip-visual-design']
        if arguments.get('explain_viz_request'):
            argv += ['--explain-viz-request', arguments['explain_viz_request']]
        if arguments.get('explain_viz_mode'):
            argv += ['--explain-viz-mode', arguments['explain_viz_mode']]
    if command == 'build':
        argv += ['--skip-native']
    if command in ('build', 'review-officecli'):
        argv += ['--officecli', arguments.get('officecli', 'officecli')]
    if command == 'qa' and arguments.get('include_acked'):
        argv += ['--include-acked']
    if command == 'ack-review':
        argv += ['--reviewer', arguments['reviewer'], '--note', arguments['note'], '--ids', *arguments['review_ids']]
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=540)
    if result.returncode not in (0, 1):
        raise ValueError(result.stderr.strip() or result.stdout.strip())
    value = json.loads(result.stdout)
    value['exit_code'] = result.returncode
    if command == 'build':
        out = Path(arguments['out']).resolve()
        value['candidate'] = str(out/'candidate.pptx') if (out/'candidate.pptx').is_file() else None
        value['layout_provider_report'] = str(out/'layout_provider.json')
    return value


for name, command, description in (
    ('totalpipe_compile', 'compile', 'Compile designed canonical Deck IR with the bundled packer. Requires academic_design and visual plans for eligible slides; otherwise returns VISUAL_DESIGN_REQUIRED with a full agent prompt. No PPTX rendering.'),
    ('totalpipe_build', 'build', 'Generate a PPTX candidate and QA through OfficeCLI from designed canonical Deck IR. Missing design returns VISUAL_DESIGN_REQUIRED and the prompt before rendering. Defaults to the bundled packer.'),
    ('totalpipe_review', 'review-officecli', 'Inspect an existing build and export slide screenshots, schema, and issues on demand. OfficeCLI Text overflow is an unreliable heuristic.'),
    ('totalpipe_qa', 'qa', 'Read candidate QA and pending REVIEW count; acknowledged notes are hidden unless include_acked=true. Does not change final approval.'),
    ('totalpipe_ack_review', 'ack-review', 'Record actual candidate review of explicit REVIEW ids with reviewer and note. Unchanged page evidence retains notes on rebuild; final still needs artifact-bound approval.'),
):
    properties = {'out': {'type':'string', 'description':'Absolute build directory path.'}}
    required = ['out']
    if command in ('compile', 'build'):
        properties.update({'ir':{'type':'string', 'description':'Absolute canonical deck_ir.json path.'},
                           'layout_provider':{'type':'string','default':'packer'},
                           'skip_visual_design':{'type':'boolean','default':False,
                               'description':'Explicit legacy mode only; bypass the default visual design stage.'},
                           'explain_viz_request': {'type': 'string',
                               'description': 'Optional absolute path to ExplainViz configuration/proposal; omitted uses auto.'},
                           'explain_viz_mode': {'enum': ['auto', 'off', 'prefer'],
                               'description': 'Optional mode override; off explicitly disables automatic diagrams.'}})
        required.append('ir')
    if command in ('build', 'review-officecli'):
        properties['officecli'] = {'type':'string','description':'OfficeCLI executable path or PATH command.','default':'officecli'}
    if command == 'qa':
        properties['include_acked'] = {'type': 'boolean', 'default': False}
    if command == 'ack-review':
        properties.update({'reviewer': {'type': 'string', 'minLength': 1},
                           'note': {'type': 'string', 'minLength': 1},
                           'review_ids': {'type': 'array', 'minItems': 1,
                                          'items': {'type': 'string', 'minLength': 1}}})
        required += ['reviewer', 'note', 'review_ids']
    def handler(arguments, command=command, properties=properties, required=required):
        if set(arguments)-set(properties) or any(k not in arguments for k in required):
            raise ValueError('Missing or unknown arguments')
        for key, value in arguments.items():
            if key in ('skip_visual_design', 'include_acked'):
                if not isinstance(value, bool):
                    raise ValueError(f'{key} must be a boolean')
                continue
            if key == 'review_ids':
                if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
                    raise ValueError('review_ids must be a nonempty list of REVIEW ids')
                continue
            if not isinstance(value, str):
                raise ValueError(f'{key} must be a string')
        for key in ('ir','out','explain_viz_request'):
            if key in arguments and not Path(arguments[key]).is_absolute():
                raise ValueError(f'{key} must be an absolute path')
        _check_executables(arguments)
        return invoke(command, arguments)
    transport.TOOLS[name] = {'description':description,
        'inputSchema':{'type':'object','properties':properties,'required':required,'additionalProperties':False},
        'handler':handler, 'timeout':570}

def visual_invoke(command, arguments):
    allowed = {'ir', 'out', 'requirements', 'slide_ids'} if command == 'visual-prompt' else {'ir', 'out', 'proposal'}
    required = {'ir', 'out'} if command == 'visual-prompt' else {'ir', 'out', 'proposal'}
    if set(arguments)-allowed or not required <= set(arguments):
        raise ValueError('Missing or unknown arguments')
    for key, value in arguments.items():
        if key == 'slide_ids':
            if not isinstance(value, list) or not value or not all(isinstance(sid, str) and sid for sid in value):
                raise ValueError('slide_ids must be a nonempty list of slide ids')
        elif not isinstance(value, str):
            raise ValueError(f'{key} must be a string')
    for key in ('ir', 'out', 'proposal'):
        if key in arguments and not Path(arguments[key]).is_absolute():
            raise ValueError(f'{key} must be an absolute path')
    argv = [sys.executable, '-m', 'deck_compiler', command, '--ir', arguments['ir'], '--out', arguments['out']]
    if command == 'visual-prompt':
        argv += ['--requirements', arguments.get('requirements', '')]
        if 'slide_ids' in arguments:
            argv += ['--slides', *arguments['slide_ids']]
    else:
        argv += ['--proposal', arguments['proposal']]
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=60)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


for name, command, description in (
    ('totalpipe_visual_prompt', 'visual-prompt', 'Required design stage: prepare the full Deck IR, asset metadata, eligible slide jobs and strict V6 schemas. Read the complete output, author a proposal covering eligible slides, then apply it. No model call. out is a JSON file.'),
    ('totalpipe_apply_visual_plan', 'apply-visual-plan', 'Validate and merge a SHA-bound visual proposal into canonical Deck IR, changing presentation only. Keep output alongside source IR when it uses relative assets. out is a JSON file.'),
):
    properties = {'ir': {'type': 'string'}, 'out': {'type': 'string'}}
    required = ['ir', 'out']
    if command == 'visual-prompt':
        properties.update({'requirements': {'type': 'string'},
                           'slide_ids': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}}})
    else:
        properties['proposal'] = {'type': 'string'}
        required.append('proposal')
    transport.TOOLS[name] = {'description': description,
        'inputSchema': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False},
        'handler': lambda arguments, command=command: visual_invoke(command, arguments), 'timeout': 65}


def explain_viz_invoke(command, arguments):
    allowed = {'ir', 'slots', 'out'}
    required = {'ir', 'out'}
    if command == 'apply-explain-viz':
        allowed |= {'proposal', 'mode', 'max_visuals_per_deck'}
    if not isinstance(arguments, dict) or set(arguments)-allowed or not required <= set(arguments):
        raise ValueError('Missing or unknown ExplainViz arguments')
    for key, value in arguments.items():
        if key == 'max_visuals_per_deck':
            if type(value) is not int or not 0 <= value <= 32:
                raise ValueError('max_visuals_per_deck must be an integer in [0,32]')
        elif key == 'mode':
            if value not in ('off', 'auto', 'prefer'):
                raise ValueError('mode must be off, auto or prefer')
        elif not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f'{key} must be an absolute path')
    argv = [sys.executable, '-m', 'deck_compiler', command,
            '--ir', arguments['ir'], '--out', arguments['out']]
    if arguments.get('slots'):
        argv += ['--slots', arguments['slots']]
    if command == 'apply-explain-viz':
        if arguments.get('proposal'):
            argv += ['--proposal', arguments['proposal']]
        argv += ['--mode', arguments.get('mode', 'auto'),
                 '--max-visuals-per-deck', str(arguments.get('max_visuals_per_deck', 4))]
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=560)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


for name, command, description in (
    ('totalpipe_explain_viz_prompt', 'explain-viz-prompt',
     'Optional ExplainViz: filter explicitly reserved Path IR scenes and prepare source facts and a strict proposal schema. No model call; out is a JSON file.'),
    ('totalpipe_apply_explain_viz', 'apply-explain-viz',
     'ExplainViz: append source-bound native diagrams, detect free regions and try bounded local body reflow. Default auto; off disables it. Keep output alongside source IR. Fallback preserves input.'),
):
    properties = {key: {'type': 'string'} for key in ('ir', 'slots', 'out')}
    required = ['ir', 'out']
    if command == 'apply-explain-viz':
        properties.update({'proposal': {'type': 'string'},
                           'mode': {'enum': ['off', 'auto', 'prefer'], 'default': 'auto'},
                           'max_visuals_per_deck': {'type': 'integer', 'minimum': 0,
                                                    'maximum': 32, 'default': 4}})
    transport.TOOLS[name] = {'description': description,
        'inputSchema': {'type': 'object', 'properties': properties, 'required': required,
                        'additionalProperties': False},
        'handler': lambda arguments, command=command: explain_viz_invoke(command, arguments),
        'timeout': 570}


if __name__ == '__main__':
    raise SystemExit(transport.main())
