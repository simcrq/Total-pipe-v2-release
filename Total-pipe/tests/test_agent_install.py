import json
import subprocess
import sys
import tomllib
import os
import stat
from pathlib import Path

from agent import ROOT
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
        result = subprocess.run([sys.executable, ROOT/'install.py', '--client', 'codex', '--venv', venv,
                                 '--config', config, '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'DRY_RUN')
        self.assertFalse(venv.exists())
        self.assertFalse(config.exists())

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

    def test_config_and_backup_permissions_do_not_expose_existing_secrets(self):
        path = self.root/'private.toml'
        path.write_text('model="private-choice"\n')
        path.chmod(0o600)
        result = configure(path, 'codex', profile_servers('agent', sys.executable))
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(result['backup']).stat().st_mode), 0o600)
