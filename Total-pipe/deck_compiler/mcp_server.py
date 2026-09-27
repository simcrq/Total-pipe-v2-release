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
transport.SERVER_VERSION = '3.1.0'
transport.INSTRUCTIONS = ('Total-pipe v3: use existing PaperWorkflow, Story and RPA planning; '
    'Story nodes may carry optional key_points; pwf2rpa passes them to RPA briefs, '
    'counts their capacity, and preserves body paragraph breaks. '
    'On RPA revisions, compare slides with the original content model; do not compress or drop key_points. '
    'Then pass canonical Deck IR to totalpipe_compile or totalpipe_build. '
    'v26 proposes layout, compiler enforces constraints, OfficeCLI writes PPTX. '
    'Build returns a candidate and QA, not automatic final approval. '
    'totalpipe_review inspects builds and exports OfficeCLI screenshots on demand. '
    'OfficeCLI Text overflow issues are unreliable; keep them and verify actual slide appearance.')


def invoke(command, arguments):
    argv = [sys.executable, '-m', 'deck_compiler', command, '--out', arguments['out']]
    if command in ('compile', 'build'):
        argv += ['--ir', arguments['ir'], '--layout-provider', arguments.get('layout_provider', 'v26')]
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
    ('totalpipe_compile', 'compile', 'Compile layout from canonical Deck IR, defaulting to v26. Returns layout and QA without rendering a PPTX.'),
    ('totalpipe_build', 'build', 'Generate a PPTX candidate and QA through OfficeCLI from canonical Deck IR. Defaults to v26 layout.'),
    ('totalpipe_review', 'review-officecli', 'Inspect an existing build and export slide screenshots, schema, and issues on demand. OfficeCLI Text overflow is an unreliable heuristic.'),
):
    properties = {'out': {'type':'string', 'description':'Absolute build directory path.'}}
    required = ['out']
    if command in ('compile', 'build'):
        properties.update({'ir':{'type':'string', 'description':'Absolute canonical deck_ir.json path.'},
                           'layout_provider':{'type':'string','enum':['v26','deterministic'],'default':'v26'}})
        required.append('ir')
    if command != 'compile':
        properties['officecli'] = {'type':'string','description':'OfficeCLI executable path or PATH command.','default':'officecli'}
    def handler(arguments, command=command, properties=properties, required=required):
        if set(arguments)-set(properties) or any(k not in arguments for k in required):
            raise ValueError('Missing or unknown arguments')
        for key, value in arguments.items():
            if not isinstance(value, str):
                raise ValueError(f'{key} must be a string')
        for key in ('ir','out'):
            if key in arguments and not Path(arguments[key]).is_absolute():
                raise ValueError(f'{key} must be an absolute path')
        return invoke(command, arguments)
    transport.TOOLS[name] = {'description':description,
        'inputSchema':{'type':'object','properties':properties,'required':required,'additionalProperties':False},
        'handler':handler, 'timeout':570}

if __name__ == '__main__':
    raise SystemExit(transport.main())
