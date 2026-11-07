"""Process boundary around the existing PWF handlers; stdout is one JSON result."""
import argparse
from contextlib import redirect_stdout
import importlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]/'PaperWorkflow'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--op', choices=('version', 'dependencies', 'mineru_auth', 'literature_workflow', 'process_pdf', 'search_evidence'), required=True)
    parser.add_argument('--args', type=Path)
    parser.add_argument('--source-kind', choices=('markdown', 'pdf'), default='markdown')
    args = parser.parse_args()
    try:
        with redirect_stdout(sys.stderr):
            spec = importlib.util.spec_from_file_location('agent_pwf', ROOT/'mcp_server.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if args.op == 'version':
                result = module.SERVER_INFO
            elif args.op == 'mineru_auth':
                from utils.pdf_official_handler import OfficialMinerUProcessor
                result = OfficialMinerUProcessor(module.load_config()).authentication()
            elif args.op == 'dependencies':
                # The server imports handlers lazily. A version handshake cannot
                # detect missing loguru/requests/yaml in the actual PDF path.
                # Import that path without creating processors or sending a PDF.
                modules = ['utils.literature_workflow']
                if args.source_kind == 'pdf':
                    modules += ['utils.pdf_handler', 'yaml']
                checks = []
                for name in modules:
                    try:
                        importlib.import_module(name)
                        checks.append({'module': name, 'ok': True})
                    except Exception as error:
                        checks.append({'module': name, 'ok': False,
                                       'error': type(error).__name__+': '+str(error)})
                result = {'checks': checks,
                          'markdown_ready': checks[0]['ok'],
                          'pdf_ready': all(check['ok'] for check in checks) if args.source_kind == 'pdf' else None}
            else:
                result = getattr(module, 'tool_'+args.op)(json.loads(args.args.read_text(encoding='utf-8')))
        response = {'ok': True, 'result': result}
    except Exception as error:
        response = {'ok': False, 'code': 'PAPERWORKFLOW_FAILED', 'message': str(error)}
    print(json.dumps(response, ensure_ascii=True))


if __name__ == '__main__':
    main()
