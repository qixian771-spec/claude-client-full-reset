import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from test_workflows import Fixture, REAL_CURRENT, backup, common, platforms
import check_environment as env


class EnvironmentTests(Fixture):
    def setUp(self):
        super().setUp()
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        for name in platforms.MACOS.tools:
            self.executable(name)
        self.apps = [self.home / 'Applications/Claude.app']

    def executable_at(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 99\n')
        path.chmod(0o700)
        return path

    def executable(self, name):
        path = self.bin / name
        path.write_text('#!/bin/sh\necho MUST-NOT-EXECUTE\nexit 99\n')
        path.chmod(0o700)
        return path

    def collect(self):
        return env.collect(self.home, str(self.bin), self.apps, [self.home / '.local/bin/claude'])

    def main(self, report, json_output=False):
        output = io.StringIO()
        with patch.object(env, 'collect', return_value=report), patch.object(common, 'require_supported', return_value=platforms.MACOS), patch.object(sys, 'argv', ['check_environment', *(['--json'] if json_output else [])]), contextlib.redirect_stdout(output):
            code = env.main()
        return code, output.getvalue()

    def test_new_environment_not_detected_without_claiming_never_used(self):
        report = self.collect()
        self.assertEqual(report['status'], 'not_detected')
        self.assertEqual(report['prior_use'], 'not_determinable')
        self.assertEqual(report['account_status'], 'not_checked')
        self.assertEqual(self.main(report)[0], 0)

    def test_skill_only_install_is_not_claude_usage(self):
        self.file('.claude/skills/claude-client-full-reset/SKILL.md', 'skill fixture')
        report = self.collect()
        self.assertTrue(report['skill_present'])
        self.assertEqual(report['local_paths'], [])
        self.assertEqual(report['status'], 'not_detected')

    def test_desktop_directory_is_only_an_installation_candidate(self):
        self.apps[0].mkdir(parents=True)
        report = self.collect()
        self.assertEqual(report['status'], 'installed')
        self.assertEqual(report['desktop_paths'], [str(self.apps[0])])
        self.assertIn('候选', report['label'])

    def test_cli_symlink_is_detected_without_executing(self):
        executable = self.executable('real-cli')
        (self.bin / 'claude').symlink_to(executable)
        with patch.object(env.common, 'run', side_effect=AssertionError('must not execute commands')):
            report = self.collect()  # Process list is the explicit Fixture mock.
        self.assertEqual(report['status'], 'installed')
        self.assertTrue(report['cli_candidates'][0]['usable_path'])

    def test_local_config_only_is_not_proof_of_login(self):
        self.file('.claude/.credentials.json', '{"secret":"DO-NOT-PRINT"}')
        with patch.object(Path, 'read_text', side_effect=AssertionError('must not read credentials')):
            report = self.collect()
        self.assertEqual(report['status'], 'local_data_only')
        self.assertNotIn('DO-NOT-PRINT', json.dumps(report))
        self.assertEqual(report['account_status'], 'not_checked')

    def test_known_cli_outside_path_has_specific_configuration_guidance(self):
        target = self.file('.local/bin/claude', 'fixture must not run')
        target.chmod(0o700)
        report = self.collect()
        self.assertEqual(report['status'], 'installed')
        self.assertFalse(report['cli_candidates'][0]['on_path'])
        self.assertTrue(any('不在当前 PATH' in step for step in report['next_steps']))

    def test_custom_running_claude_not_misreported_as_new(self):
        with patch.object(common, 'process_list', return_value=['/custom/Claude.app/Contents/MacOS/Claude --private-arg']):
            report = self.collect()
        self.assertEqual(report['status'], 'needs_review')
        self.assertEqual(report['claude_process_count'], 1)
        self.assertNotIn('--private-arg', json.dumps(report))

    def test_open_browser_does_not_block_readonly_detection(self):
        with patch.object(common, 'process_list', return_value=['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']):
            report = self.collect()
        self.assertEqual(report['status'], 'not_detected')
        self.assertEqual(report['related_process_count'], 1)
        self.assertEqual(self.main(report)[0], 0)

    def test_broken_cli_link_requires_review(self):
        (self.bin / 'claude').symlink_to(self.home / 'missing-cli')
        report = self.collect()
        self.assertEqual(report['status'], 'needs_review')
        self.assertEqual(self.main(report)[0], 1)

    def test_missing_optional_node_does_not_block_base_checks(self):
        (self.bin / 'node').unlink()
        (self.bin / 'npm').unlink()
        report = self.collect()
        self.assertEqual(report['tools']['node'], [])
        self.assertEqual(report['missing_base_tools'], [])
        self.assertEqual(self.main(report)[0], 0)

    def test_missing_base_tool_reports_incomplete_preparation(self):
        (self.bin / 'ditto').unlink()
        report = self.collect()
        self.assertEqual(report['missing_base_tools'], ['ditto'])
        self.assertEqual(self.main(report)[0], 1)

    def test_unknown_claude_directory_entries_are_listed_for_review(self):
        # Contract change (0.3.0): unknown names are listed in
        # unclassified_items instead of forcing needs_review; contents are
        # still never read and nothing is scheduled for cleanup.
        self.file('.claude/custom-state', 'do not read')
        report = self.collect()
        self.assertEqual(report['status'], 'local_data_only')
        self.assertEqual(report['unclassified_items'], ['custom-state'])
        self.assertTrue(any('unclassified_items' in step for step in report['next_steps']))
        self.assertNotIn('do not read', json.dumps(report))

    def test_documented_claude_entries_are_classified(self):
        for name in ('CLAUDE.md', 'backups/a', 'cache/changelog.md', 'plans/p.md', 'commands/x.md',
                     'output-styles/s.md', 'keybindings.json', 'stats-cache.json', 'agent-memory/m.md'):
            self.file('.claude/' + name)
        report = self.collect()
        self.assertEqual(report['unclassified_items'], [])
        self.assertEqual(report['status'], 'local_data_only')

    def test_auto_memory_projects_are_counted_without_reading(self):
        self.file('.claude/projects/-a/memory/MEMORY.md', 'private memory')
        self.file('.claude/projects/-b/session.jsonl', 'transcript')
        report = self.collect()
        self.assertEqual(report['auto_memory_projects'], 1)
        self.assertTrue(any('自动记忆' in step for step in report['next_steps']))
        self.assertNotIn('private memory', json.dumps(report))

    def test_native_version_store_without_launcher_requires_review(self):
        self.file('.local/share/claude/versions/2.1.0', 'binary')
        report = self.collect()
        self.assertEqual(report['status'], 'needs_review')
        self.assertEqual(report['cli_install_dirs'], [str(self.home / '.local/share/claude')])
        self.executable_at(self.home / '.local/bin/claude')
        self.assertEqual(self.collect()['status'], 'installed')

    def test_permission_error_propagates_not_absence(self):
        original = common.exists
        def denied(path):
            if Path(path) == self.home / '.claude.json':
                raise PermissionError('fixture denied')
            return original(path)
        with patch.object(common, 'exists', side_effect=denied):
            with self.assertRaises(PermissionError):
                self.collect()

    def test_process_query_failure_is_error_not_new_machine(self):
        with patch.object(common, 'process_list', side_effect=RuntimeError('ps failed')):
            with self.assertRaises(RuntimeError):
                self.collect()
        with patch.object(env, 'collect', side_effect=PermissionError('denied')), patch.object(common, 'require_supported', return_value=platforms.MACOS), patch.object(sys, 'argv', ['check_environment', '--json']), contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(common.cli(env.main), 2)
        self.assertEqual(output.getvalue(), '')

    def test_json_contains_no_values_or_process_arguments_and_no_writes(self):
        self.file('.claude.json', '{"secret":"DO-NOT-READ"}')
        before = backup.inventory(self.home)
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'PRIVATE-KEY'}):
            code, output = self.main(self.collect(), True)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['status'], 'local_data_only')
        self.assertNotIn('PRIVATE-KEY', output)
        self.assertNotIn('DO-NOT-READ', output)
        self.assertEqual(backup.inventory(self.home), before)

    def test_path_entry_not_directory_is_an_error(self):
        invalid = self.file('not-directory')
        with self.assertRaises(ValueError):
            env.command_paths('claude', str(invalid))

    def test_data_symlink_requires_review(self):
        original = self.file('outside-config')
        (self.home / '.claude.json').symlink_to(original)
        self.assertEqual(self.collect()['status'], 'needs_review')

    def test_broken_optional_tool_is_not_hidden_as_missing(self):
        (self.bin / 'node').unlink()
        (self.bin / 'node').symlink_to('missing-node')
        self.assertEqual(self.collect()['status'], 'needs_review')

    def test_non_macos_cli_refuses_before_collect(self):
        with patch.object(platforms, 'current', REAL_CURRENT), patch.object(sys, 'platform', 'linux'), patch.object(sys, 'argv', ['check_environment']), patch.object(env, 'collect') as collect, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(common.cli(env.main), 2)
        collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
