import json
import subprocess
import sys
import tomllib
import os
import stat
from pathlib import Path
from unittest.mock import patch

from agent import ROOT
from agent.harnesses import CLIENTS, default_config, deepseek_plan, register_deepseek
from agent.installation import BEGIN, END, configure, profile_servers, handshake, toml_config, json_config
from agent_fixture import AgentCase


class InstallTests(AgentCase):
    def test_toml_round_trip_is_idempotent_and_preserves_unmanaged_bytes(self):
        path = self.root/'config.toml'
        original = '# A user comment\nmodel = "chosen"\n[mcp_servers.other]\ncommand = "other"\n'
        path.write_text(original)
        servers = profile_servers('agent', sys.executable)
        result = configure(path, 'codex', servers)
        first = path.read_text()
        self.assertTrue(first.startswith(original))
        self.assertEqual(Path(result['backup']).read_text(), original)
        self.assertFalse(configure(path, 'codex', servers)['changed'])
        self.assertEqual(path.read_text(), first)
        self.assertEqual(first.count(BEGIN), 1)
        configure(path, 'codex', profile_servers('advanced', sys.executable))
        parsed = tomllib.loads(path.read_text())
        self.assertNotIn('total_pipe', parsed['mcp_servers'])
        self.assertIn('other', parsed['mcp_servers'])
        self.assertEqual(len(parsed['mcp_servers']), 4)

    def test_bad_toml_markers_and_unmanaged_collisions_are_never_overwritten(self):
        for original in ('broken = [', '[mcp_servers.total_pipe]\ncommand="user"\n', BEGIN+'\n'):
            path = self.root/'config.toml'
            path.write_text(original)
            with self.assertRaises(ValueError):
                configure(path, 'codex', profile_servers('agent', sys.executable), force=True)
            self.assertEqual(path.read_text(), original)

    def test_root_keys_after_managed_block_cannot_silently_change_scope(self):
        servers = profile_servers('agent', sys.executable)
        managed = toml_config('model="x"\n', servers)
        with self.assertRaisesRegex(ValueError, 'semantics'):
            toml_config(managed+'user_setting = "must remain meaningful"\n', servers)

    def test_json_merge_keeps_other_keys_and_profile_switch_removes_only_owned_servers(self):
        original = {'other': {'enabled': True}, 'mcpServers': {'keep': {'command': 'another'}}}
        value = json_config(json.dumps(original), profile_servers('agent', sys.executable))
        self.assertEqual(json_config(value, profile_servers('agent', sys.executable)), value)
        updated = json.loads(json_config(value, profile_servers('advanced', sys.executable)))
        self.assertEqual(updated['other'], original['other'])
        self.assertEqual(updated['mcpServers']['keep'], original['mcpServers']['keep'])
        self.assertNotIn('total_pipe', updated['mcpServers'])
        self.assertEqual(len(updated['mcpServers']), 4)

    def test_dry_run_does_not_create_venv_config_or_report(self):
        venv = self.root/'no-venv'
        config = self.root/'no-config/config.toml'
        skills = self.root/'no-skills'
        result = subprocess.run([sys.executable, ROOT/'install.py', '--client', 'codex', '--venv', venv,
                                 '--config', config, '--skills-root', skills, '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'DRY_RUN')
        self.assertFalse(venv.exists())
        self.assertFalse(config.exists())
        self.assertFalse(skills.exists())

    def test_actual_agent_and_advanced_handshakes_discover_tools(self):
        default = profile_servers('agent', sys.executable)
        receipt = handshake(default['total_pipe'])
        self.assertEqual(set(receipt['tools']), {'totalpipe_doctor','totalpipe_start','totalpipe_advance','totalpipe_status'})
        advanced = {name: handshake(server) for name, server in profile_servers('advanced', sys.executable).items()}
        self.assertIn('totalpipe_build', advanced['total_pipe_v3']['tools'])
        self.assertIn('pwf2rpa_check', advanced['total_pipe_v3']['tools'])
        self.assertIn('normalize_content', advanced['research_ppt']['tools'])
        self.assertIn('paperworkflow_literature_workflow', advanced['paperworkflow']['tools'])

    def test_target_interpreter_keeps_venv_identity(self):
        self.assertEqual(profile_servers('agent', sys.executable)['total_pipe']['command'], sys.executable)

    def test_host_formats_support_a_real_stdio_handshake(self):
        servers = profile_servers('agent', sys.executable)
        for client, version in (('claude', '2'), ('workbuddy', '2'), ('gemini', '2'),
                                ('opencode', '1'), ('opencode', '2')):
            with self.subTest(client=client, version=version):
                original = {'theme': 'custom', 'mcp': {'policy': 'keep'}} if client == 'opencode' else {
                    'mcpServers': {'keep': {'command': 'other'}}, 'theme': 'custom'}
                encoded = json_config(json.dumps(original), servers, client=client, opencode_default=version)
                value = json.loads(encoded)
                self.assertEqual(value['theme'], 'custom')
                self.assertEqual(json_config(encoded, servers, client=client, opencode_default=version), encoded)
                if client == 'opencode':
                    self.assertEqual(value['mcp']['policy'], 'keep')
                    entries = value['mcp']['servers'] if version == '2' else value['mcp']
                    command, *args = entries['total_pipe']['command']
                    if version == '2':
                        self.assertFalse(entries['total_pipe']['codemode'])
                    environment = {}  # Host-specific variable expansion belongs to OpenCode.
                else:
                    self.assertEqual(value['mcpServers']['keep'], original['mcpServers']['keep'])
                    entry = value['mcpServers']['total_pipe']
                    command, args, environment = entry['command'], entry['args'], entry['env']
                    if client == 'gemini':
                        self.assertFalse(entry['trust'])
                        self.assertEqual(entry['timeout'], 1800000)
                        self.assertEqual(environment['MINERU_TOKEN'], '${MINERU_TOKEN}')
                        environment = {'PYTHONUTF8': environment['PYTHONUTF8']}
                result = handshake({'command': command, 'args': args, 'cwd': str(self.root), 'env': environment})
                self.assertEqual(set(result['tools']),
                                 {'totalpipe_doctor', 'totalpipe_start', 'totalpipe_advance', 'totalpipe_status'})

    def test_opencode_jsonc_backs_up_comments_and_retains_legacy_map(self):
        path = self.root/'opencode.jsonc'
        text = '''{
          // User comment
          "url": "https://example.test/a/*literal*/", /* a second comment */
          "mcp": {"old": {"type": "remote", "url": "https://example.test/mcp"},},
        }'''
        path.write_text(text, encoding='utf-8')
        configured = configure(path, 'opencode', profile_servers('agent', sys.executable))
        self.assertEqual(Path(configured['backup']).read_text(encoding='utf-8'), text)
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['url'], 'https://example.test/a/*literal*/')
        self.assertEqual(data['mcp']['old']['type'], 'remote')
        self.assertEqual(data['mcp']['total_pipe']['timeout'], 1800000)

    def test_client_discovery_and_default_paths(self):
        result = subprocess.run([sys.executable, ROOT/'install.py', '--list-clients'], check=True,
                                capture_output=True, text=True)
        self.assertEqual({item['id'] for item in json.loads(result.stdout)['clients']}, set(CLIENTS))
        with patch.dict(os.environ, {'GEMINI_CLI_HOME': str(self.root),
                                     'OPENCODE_CONFIG_DIR': str(self.root), 'OPENCODE_CONFIG': ''}):
            self.assertEqual(default_config('gemini'), self.root/'.gemini/settings.json')
            self.assertEqual(default_config('opencode'), self.root/'opencode.json')

    def test_deepseek_bundle_is_registered_and_checked_via_profile_cli(self):
        with patch('agent.harnesses.shutil.which', return_value='/usr/bin/dsh'):
            planned = deepseek_plan(self.root/'venv', 'web')
        responses = [subprocess.CompletedProcess([], 0, '', ''),
                     subprocess.CompletedProcess([], 0, 'totalpipe-mcp-total-pipe', '')]
        with patch('agent.harnesses.subprocess.run', side_effect=responses) as cli:
            result = register_deepseek(planned, profile_servers('agent', sys.executable))
        self.assertEqual([call.args[0] for call in cli.call_args_list], [planned['register'], planned['inspect']])
        self.assertTrue(result['verified_profile'])
        row = json.loads((Path(result['path'])/'cordis.patch.yml').read_text())[0]['insert'][0]
        self.assertEqual(row['config']['transport'], 'stdio')
        self.assertEqual(row['config']['toolCallTimeoutMs'], 1800000)
        self.assertNotIn('MINERU_TOKEN', row['config']['env'])

    def test_config_and_backup_permissions_do_not_expose_existing_secrets(self):
        path = self.root/'private.toml'
        path.write_text('model="private-choice"\n')
        path.chmod(0o600)
        result = configure(path, 'codex', profile_servers('agent', sys.executable))
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(result['backup']).stat().st_mode), 0o600)
