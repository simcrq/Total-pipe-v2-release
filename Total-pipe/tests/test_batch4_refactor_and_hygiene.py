"""Batch 4 regression tests: shared MCP transport, discover-fonts CLI, modular refactors, and repo hygiene."""
import io
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

TOTAL_PIPE = Path(__file__).resolve().parents[1]
REPO_ROOT = TOTAL_PIPE.parent

if str(TOTAL_PIPE) not in sys.path:
    sys.path.insert(0, str(TOTAL_PIPE))


class SharedMcpTransportTests(unittest.TestCase):
    def test_stdio_mcp_server_initialize_list_and_call(self):
        from deck_compiler.mcp_transport import StdioMcpServer

        def echo(args):
            print('handler noisy stdout should be diverted')
            return {'echo': args.get('value')}

        server = StdioMcpServer(
            'demo_mcp',
            '1.2.3',
            'Short instructions.',
            tools={
                'demo_echo': {
                    'description': 'Echo input',
                    'inputSchema': {'type': 'object', 'properties': {'value': {'type': 'string'}}},
                    'handler': echo,
                },
            },
        )

        init_resp = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
        self.assertEqual(init_resp['result']['serverInfo'], {'name': 'demo_mcp', 'version': '1.2.3'})
        self.assertEqual(init_resp['result']['instructions'], 'Short instructions.')

        list_resp = server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
        self.assertEqual([t['name'] for t in list_resp['result']['tools']], ['demo_echo'])

        err_buf = io.StringIO()
        with mock.patch.object(sys, 'stderr', err_buf):
            call_resp = server.handle({
                'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                'params': {'name': 'demo_echo', 'arguments': {'value': 'ok'}},
            })
        self.assertFalse(call_resp['result']['isError'])
        self.assertEqual(json.loads(call_resp['result']['content'][0]['text']), {'echo': 'ok'})
        self.assertIn('handler noisy stdout', err_buf.getvalue())

    def test_agent_and_deck_compiler_mcp_servers_use_shared_transport(self):
        from deck_compiler.mcp_transport import StdioMcpServer
        import agent.mcp_server as agent_mcp
        import deck_compiler.mcp_server as compiler_mcp

        self.assertIsInstance(agent_mcp.transport, StdioMcpServer)
        self.assertEqual(sorted(agent_mcp.transport.TOOLS), [
            'totalpipe_advance',
            'totalpipe_doctor',
            'totalpipe_start',
            'totalpipe_status',
        ])

        self.assertIsInstance(compiler_mcp.transport, StdioMcpServer)
        self.assertLess(len(compiler_mcp.transport.INSTRUCTIONS), 2000)
        self.assertIn('pwf2rpa_check', compiler_mcp.transport.TOOLS)
        self.assertIn('pwf2rpa_convert', compiler_mcp.transport.TOOLS)
        self.assertNotIn('pwf2rpa_refresh_capacity', compiler_mcp.transport.TOOLS)


class DiscoverFontsCliTests(unittest.TestCase):
    def _run_cli(self, *args):
        env = dict(os.environ, PYTHONPATH=str(TOTAL_PIPE))
        return subprocess.run(
            [sys.executable, *args],
            cwd=str(TOTAL_PIPE),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_deck_compiler_discover_fonts_json(self):
        proc = self._run_cli('-m', 'deck_compiler', 'discover-fonts', '--json')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload['fonts'], dict)
        self.assertIn('default', payload)
        self.assertIsInstance(payload['search_directories'], list)

    def test_unified_cli_discover_fonts_json(self):
        proc = self._run_cli('totalpipe.py', 'discover-fonts', '--json')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload['fonts'], dict)
        self.assertIn('default', payload)
        self.assertIsInstance(payload['search_directories'], list)


class AgentPromptsRefactorTests(unittest.TestCase):
    def test_prompts_module_and_adapter_reexports(self):
        from agent import adapters, prompts

        for name in (
            'DESIGN_MARKER',
            'PROJECTION_IR_INSTRUCTIONS',
            'BODY_GUIDES',
            'BODY_GUIDES_TASK',
            'DESIGN_EXAMPLE_TASK',
            'LEGACY_DESIGN_INSTRUCTIONS',
            'DESIGN_INSTRUCTIONS',
            'ATOMIC_DESIGN_INSTRUCTIONS',
            'example_lookup',
            'design_task',
            'ir_task',
        ):
            self.assertIs(getattr(adapters, name), getattr(prompts, name), name)

        lookup = prompts.example_lookup('test')
        self.assertEqual(lookup['instructions'], 'test')
        self.assertIn('页面设计任务', prompts.design_task({}))
        self.assertIn('Deck IR 实现任务', prompts.ir_task({}))


class ModularRefactorSanityTests(unittest.TestCase):
    def test_ir_validate_helpers_preserve_rules(self):
        from deck_compiler import ir as deck_ir

        self.assertEqual(deck_ir.validate('not-a-dict')[0]['rule'], 'IR_INVALID')
        issues = deck_ir.validate({
            'schema_version': '1.0',
            'deck_id': '',
            'theme': {},
            'slides': [],
        })
        messages = [i['message'] for i in issues]
        self.assertIn('schema_version must be 2.0', messages)
        self.assertIn('deck_id required', messages)
        self.assertIn('Explicit theme fonts required', messages)
        self.assertIn('slides must be a nonempty list', messages)

    def test_structural_verify_handles_corrupt_zip_as_integrity_issue(self):
        import tempfile
        from deck_compiler import structural

        with tempfile.TemporaryDirectory() as tmp:
            bad_pptx = Path(tmp) / 'corrupt.pptx'
            bad_pptx.write_bytes(b'not-a-valid-zip')
            issues = structural.verify(str(bad_pptx), {'slides': [], 'slide_size': [1280, 720]})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['rule'], 'FILE_INTEGRITY')


class RepoHygieneTests(unittest.TestCase):
    def test_tmp2_removed_and_historical_files_archived(self):
        self.assertFalse((REPO_ROOT / '.tmp2').exists())
        archived = [
            'docs/archive/CHANGES-2026-10-25.md',
            'docs/archive/EVALUATION-2026-10-27-teaching-provenance.md',
            'docs/archive/PLAN-2026-10-27-supplement-lane.md',
            'docs/archive/PLAN-2026-10-27-teaching-provenance.md',
            'docs/archive/Total-pipe/test_priority_features.py',
            'docs/archive/Total-pipe/test_deck_ir.json',
            'docs/archive/Total-pipe/test_quality_analysis',
        ]
        index_text = (REPO_ROOT / 'docs' / 'archive' / 'README.md').read_text(encoding='utf-8')
        for rel in archived:
            self.assertTrue((REPO_ROOT / rel).exists(), f'Missing archived path: {rel}')
            self.assertIn(rel.removeprefix('docs/archive/'), index_text)

    def test_zero_broken_relative_markdown_links_in_active_docs(self):
        link_re = re.compile(r'\]\(([^)#\s]+)')
        broken = []
        for md in REPO_ROOT.rglob('*.md'):
            rel = md.relative_to(REPO_ROOT).as_posix()
            if any(part in ('node_modules', '.git', 'builds', 'build', 'work', '__pycache__', '.pytest_cache') for part in md.parts):
                continue
            if rel.startswith('docs/archive/'):
                continue
            text = md.read_text(encoding='utf-8', errors='replace')
            for target in link_re.findall(text):
                if target.startswith(('http://', 'https://', 'mailto:', '#', 'file://')):
                    continue
                target_part = target.split('#', 1)[0]
                if not target_part:
                    continue
                if not (md.parent / target_part).exists():
                    broken.append((rel, target_part))
        self.assertEqual(broken, [])


if __name__ == '__main__':
    unittest.main()
