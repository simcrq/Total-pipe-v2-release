"""Total-pipe v3 tools, reusing the bundled pwf2rpa MCP transport."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('totalpipe_transport', ROOT/'pwf2rpa/integrations/mcp/server.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
transport.SERVER_NAME = 'total-pipe-v3'
transport.SERVER_VERSION = '3.2.0'
transport.INSTRUCTIONS = ('Total-pipe v3.2: use existing PaperWorkflow, Story and RPA planning; '
    'Prepare topic-specific PaperWorkflow queries before OCR, explicitly pair oddly named supplements, '
    'and confirm supplementary_content_included only after its text joins the evidence input. '
    'Gate on synthesis_readiness rather than quality_audit alone. '
    'Story nodes may carry optional key_points; pwf2rpa passes them to RPA briefs, '
    'counts their capacity, preserves body paragraph breaks, and matches the ending title to Story language. '
    'Optional DesignIntentPlanner follows Story: only a four-key_points vertical process, no bbox. '
    'Pass design_intent_path with story_path to pwf2rpa_check or pwf2rpa_convert; a hard group cannot auto-split. '
    'On RPA revisions, compare slides with the original content model; do not compress or drop body or key_points. '
    'SOURCE_TEXT_NOT_BOUND blocks delivery; character limits are coarse, so inspect SLOT_WRAP_RISK. '
    'RPA layout_contract must bind the full ordered group; map its members to actual Deck IR block ids in composition.visual_intent. '
    'Design is a required stage after canonical IR: call totalpipe_visual_prompt, read the full prompt, '
    'author one academic_design and visual plans for every eligible slide, then totalpipe_apply_visual_plan. '
    'Pass the merged IR to totalpipe_compile or totalpipe_build; VISUAL_DESIGN_REQUIRED returns a prompt and missing slides. '
    'Only an explicitly requested legacy build should set skip_visual_design=true. '
    'Displayed equations must use component=formula and LaTeX in block.text with JSON backslashes escaped; '
    'ordinary text blocks do not typeset math. Roots (including indexed roots), grouped powers, fractions, '
    'exp/log/ln, common math styles and matrix/pmatrix/bmatrix/Bmatrix/vmatrix/Vmatrix environments are supported. '
    'Matrix cells use & and rows use a double backslash; retain every cell, blank, fraction and script. '
    'Use equation-derivation for dense mathematical pages. Capacity is measured in actual one/two-column regions, '
    'not by a two-equation cap or the sum of heights across independent columns. Explicit anchors keep '
    'equations with preceding explanation blocks. Never replace an unsupported equation with a wrong expression. '
    'Editable native graphics use composition.graphics: optional on process-flow and '
    'figure-parameters with context and source figures, or standalone on native-graphic. '
    'Declare every relationship explicitly; do not infer edges or replace source evidence with a schematic. '
    'The compiler allocates graphic regions and reports capacity failures without truncation; SCHEMATIC_REVIEW remains required. '
    'Types include process/dag, mechanism, architecture, funnel, path and composite. '
    'Mechanism edges require explicit activate/inhibit/associate kind and evidence/hypothesis basis; '
    'evidence refs must bind to semantic.evidence_refs, and feedback must be explicit. '
    'Path IR accepts local view_box and absolute M/L/C/Q/Z only, compiling to native custom geometry; it is not SVG import. '
    'totalpipe_visual_prompt prepares the full-deck agent prompt, '
    'then totalpipe_apply_visual_plan validates a SHA-bound presentation-only proposal. '
    'Use one academic_design and source-bound visual_plan; VISUAL_PLAN_UNSATISFIABLE requires replanning. '
    'Use one deck frame; ordered figure-parameters blocks are a peer column with 24 px gaps. '
    'An explicit four-step process must pass compiler member validation; legacy method-to-result inference remains compatible. '
    'The compiler draws its numbered sequence rail and preserves original scientific text. '
    'The packer proposes a body layout, the compiler enforces the geometric gates and writes the frame, OfficeCLI writes the PPTX. '
    'A provider that fails or is rejected loses that page to the compiler templates; check layout_provider.json for per-slide provenance. '
    'Build returns a candidate and QA, not automatic final approval. '
    'totalpipe_review inspects builds and exports OfficeCLI screenshots on demand. '
    'OfficeCLI Text overflow issues are unreliable; keep them and verify actual slide appearance.')
transport.INSTRUCTIONS += (' Query totalpipe_capabilities before region-tree composition. '
    'composition.layout_tree version 1.0 reuses the compiler body frame; columns/stack/panel/image_grid '
    'contain block/figure/graphic references exactly once, with no page coordinates. '
    'RPA search_sublayouts/compose_sublayout propose structure; the compiler measures every child. '
    'Read layout_feedback.json for component paths, required/available sizes and replan actions. '
    'Keep deck academic_design; tree pages do not also carry a flat visual_plan. '
    'No arbitrary table renderer is supported by this tree version.')


def capability_handler(arguments):
    if arguments:
        raise ValueError('No arguments supported')
    from .layout_tree import capabilities
    return {'deck_ir_version': '2.0', 'layout_tree': capabilities(),
            'backend': {'name': 'officecli', 'minimum_version': '1.0.152', 'runtime_probe_required': True}}


transport.TOOLS['totalpipe_capabilities'] = {'description': 'Declare compiler region-tree contracts and required native backend capabilities; runtime OfficeCLI support is checked again at build time.',
    'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    'handler': capability_handler, 'timeout': 10}


def invoke(command, arguments):
    argv = [sys.executable, '-m', 'deck_compiler', command, '--out', arguments['out']]
    if command in ('compile', 'build'):
        argv += ['--ir', arguments['ir'], '--layout-provider', arguments.get('layout_provider', 'packer')]
        if arguments.get('skip_visual_design', False):
            argv += ['--skip-visual-design']
    if command == 'build':
        argv += ['--skip-native']
    if command in ('build', 'review-officecli'):
        argv += ['--officecli', arguments.get('officecli', 'officecli')]
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
):
    properties = {'out': {'type':'string', 'description':'Absolute build directory path.'}}
    required = ['out']
    if command in ('compile', 'build'):
        properties.update({'ir':{'type':'string', 'description':'Absolute canonical deck_ir.json path.'},
                           'layout_provider':{'type':'string','default':'packer'},
                           'skip_visual_design':{'type':'boolean','default':False,
                               'description':'Explicit legacy mode only; bypass the default visual design stage.'}})
        required.append('ir')
    if command != 'compile':
        properties['officecli'] = {'type':'string','description':'OfficeCLI executable path or PATH command.','default':'officecli'}
    def handler(arguments, command=command, properties=properties, required=required):
        if set(arguments)-set(properties) or any(k not in arguments for k in required):
            raise ValueError('Missing or unknown arguments')
        for key, value in arguments.items():
            if key == 'skip_visual_design':
                if not isinstance(value, bool):
                    raise ValueError('skip_visual_design must be a boolean')
                continue
            if not isinstance(value, str):
                raise ValueError(f'{key} must be a string')
        for key in ('ir','out'):
            if key in arguments and not Path(arguments[key]).is_absolute():
                raise ValueError(f'{key} must be an absolute path')
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


if __name__ == '__main__':
    raise SystemExit(transport.main())
