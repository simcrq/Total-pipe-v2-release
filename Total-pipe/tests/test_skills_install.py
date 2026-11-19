import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import skills


def bundled():
    return sorted(path.name for path in skills.source_dir().iterdir() if path.is_dir())


class PlanTests(unittest.TestCase):
    def test_every_bundled_skill_has_a_manifest(self):
        for name in bundled():
            self.assertTrue((skills.source_dir()/name/'SKILL.md').is_file(), name)

    def test_a_fresh_target_plans_every_skill_as_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = skills.plan('claude', root=tmp)
            self.assertEqual([row['state'] for row in rows], ['new']*len(bundled()))
            self.assertEqual(sorted(row['name'] for row in rows), bundled())

    def test_unknown_client_is_rejected(self):
        with self.assertRaises(ValueError):
            skills.target_dir('no-such-agent')

    def test_client_config_dirs_are_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': tmp}):
                self.assertEqual(skills.target_dir('claude'), Path(tmp)/'skills')
            with mock.patch.dict(os.environ, {'CODEX_HOME': tmp}):
                self.assertEqual(skills.target_dir('codex'), Path(tmp)/'skills')


class InstallTests(unittest.TestCase):
    def test_install_copies_the_whole_skill_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = skills.install('claude', root=tmp)
            self.assertEqual(result['status'], 'PASS')
            self.assertEqual(sorted(result['installed']), bundled())
            for name in bundled():
                self.assertTrue((Path(tmp)/name/'SKILL.md').is_file(), name)
                self.assertEqual(
                    sorted(path.relative_to(Path(tmp)/name) for path in (Path(tmp)/name).rglob('*')
                           if path.is_file()),
                    sorted(path.relative_to(skills.source_dir()/name)
                           for path in (skills.source_dir()/name).rglob('*') if path.is_file()),
                    name)

    def test_a_second_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills.install('claude', root=tmp)
            again = skills.install('claude', root=tmp)
            self.assertEqual(sorted(again['unchanged']), bundled())
            self.assertEqual(again['installed'], [])
            self.assertEqual(again['updated'], [])

    def test_a_local_edit_is_not_overwritten_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills.install('claude', root=tmp)
            name = bundled()[0]
            edited = Path(tmp)/name/'SKILL.md'
            edited.write_text(edited.read_text(encoding='utf-8') + '\nlocal note\n', encoding='utf-8')
            self.assertEqual([row['state'] for row in skills.plan('claude', root=tmp)
                              if row['name'] == name], ['update'])
            result = skills.install('claude', root=tmp)
            self.assertEqual(result['status'], 'PARTIAL')
            self.assertIn(name, [row['name'] for row in result['skipped']])
            self.assertIn('local note', edited.read_text(encoding='utf-8'))

    def test_force_restores_the_bundled_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills.install('claude', root=tmp)
            name = bundled()[0]
            edited = Path(tmp)/name/'SKILL.md'
            edited.write_text('local note\n', encoding='utf-8')
            result = skills.install('claude', root=tmp, force=True)
            self.assertEqual(result['updated'], [name])
            self.assertEqual(edited.read_text(encoding='utf-8'),
                             (skills.source_dir()/name/'SKILL.md').read_text(encoding='utf-8'))

    def test_a_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'skills'
            result = skills.install('claude', root=target, dry_run=True)
            self.assertTrue(result['dry_run'])
            self.assertEqual(sorted(result['installed']), bundled())
            self.assertFalse(target.exists())

    def test_a_folder_without_a_manifest_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source'
            (source/'good').mkdir(parents=True)
            (source/'good'/'SKILL.md').write_text('# good\n', encoding='utf-8')
            (source/'broken').mkdir()
            (source/'broken'/'notes.md').write_text('no manifest\n', encoding='utf-8')
            result = skills.install('claude', root=Path(tmp)/'target', source=source)
            self.assertEqual(result['installed'], ['good'])
            self.assertEqual([row['name'] for row in result['skipped']], ['broken'])
            self.assertEqual(result['status'], 'PARTIAL')


if __name__ == '__main__':
    unittest.main()
