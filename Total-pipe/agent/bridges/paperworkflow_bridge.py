"""Process boundary around the existing PWF handlers; stdout is one JSON result."""
import argparse
from contextlib import redirect_stdout
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]/'PaperWorkflow'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--op', choices=('version', 'literature_workflow', 'process_pdf', 'search_evidence'), required=True)
    parser.add_argument('--args', type=Path)
    args = parser.parse_args()
    try:
        with redirect_stdout(sys.stderr):
            spec = importlib.util.spec_from_file_location('agent_pwf', ROOT/'mcp_server.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if args.op == 'version':
                result = module.SERVER_INFO
            else:
                result = getattr(module, 'tool_'+args.op)(json.loads(args.args.read_text(encoding='utf-8')))
        response = {'ok': True, 'result': result}
    except Exception as error:
        response = {'ok': False, 'code': 'PAPERWORKFLOW_FAILED', 'message': str(error)}
    print(json.dumps(response, ensure_ascii=True))


if __name__ == '__main__':
    main()
