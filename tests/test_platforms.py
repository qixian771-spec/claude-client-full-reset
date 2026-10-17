import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_workflows import REAL_CURRENT, ROOT, SQL, common, platforms

# Literal copies of the macOS constants before the platform table existed
# (commit dd4e985). The table must not change macOS behaviour.
LEGACY_CORE = [
    ('.claude', 'dot-claude'), ('.claude.json', 'dot-claude.json'),
    ('Library/Application Support/Claude', 'AppSupport-Claude'),
    ('Library/Application Support/Claude-3p', 'AppSupport-Claude-3p'),
    ('Library/Preferences/com.anthropic.claudefordesktop.plist', 'plist'),
    ('Library/Caches/com.anthropic.claudefordesktop', 'Caches-app'),
    ('Library/Caches/com.anthropic.claudefordesktop.ShipIt', 'Caches-ShipIt'),
    ('Library/Caches/claude-cli-nodejs', 'Caches-cli'),
    ('Library/HTTPStorages/com.anthropic.claudefordesktop', 'HTTPStorages-app'),
    ('Library/Logs/Claude', 'Logs-Claude'), ('Library/Logs/Claude-3p', 'Logs-Claude-3p'),
    ('Library/Saved Application State/com.anthropic.claudefordesktop.savedState', 'SavedState'),
] + [(name, 'shell/' + name) for name in ('.zshrc', '.bashrc', '.profile', '.zprofile', '.zshenv')]
LEGACY_BROWSER_PATHS = [
    ('Chrome', 'Google/Chrome'), ('Chrome Beta', 'Google/Chrome Beta'),
    ('Chrome Canary', 'Google/Chrome Canary'), ('Edge', 'Microsoft Edge'),
    ('Brave', 'BraveSoftware/Brave-Browser'), ('Vivaldi', 'Vivaldi'),
    ('Chromium', 'Chromium'), ('Arc', 'Arc/User Data'),
]
LEGACY_APP_NAMES = ('Google Chrome', 'Google Chrome Beta', 'Google Chrome Canary',
                    'Microsoft Edge', 'Brave Browser', 'Vivaldi', 'Chromium', 'Arc',
                    'Safari', 'Claude', 'Code', 'Cursor', 'Windsurf')
LEGACY_TRACE_NAMES = ('projects', 'history.jsonl', 'sessions', 'tasks', 'teams',
                      'shell-snapshots', 'session-env', 'file-history', 'paste-cache', '.cc-writes')
LEGACY_PROTECTED = (
    'Library', 'Library/Application Support', 'Library/Caches', 'Library/Logs',
    'Library/Preferences', 'Library/HTTPStorages', 'Library/Containers',
    'Library/Group Containers', 'Library/Application Scripts', '.Trash',
    'Desktop', 'Documents', 'Downloads', 'Pictures', 'Movies', 'Music',
    'Applications', '.config', '.local', '.ssh', '.codex', '.agents',
    '.vscode', '.cursor', '.windsurf')


class MacTableTests(unittest.TestCase):
    home = Path('/Users/fixture')

    def test_core_matches_legacy_backup_list(self):
        mac = platforms.MACOS
        self.assertEqual(mac.core(self.home),
                         [(self.home / src, name) for src, name in LEGACY_CORE])

    def test_browser_roots_match_legacy(self):
        support = self.home / 'Library/Application Support'
        self.assertEqual(platforms.MACOS.browsers(self.home),
                         [(name, support / sub) for name, sub in LEGACY_BROWSER_PATHS])

    def test_process_names_match_legacy_order_and_grouping(self):
        mac = platforms.MACOS
        # 0.3.0 appends Firefox (read-only scan) after the legacy browsers.
        self.assertEqual(mac.browser_processes[:9], LEGACY_APP_NAMES[:9])
        self.assertEqual(mac.browser_processes[9:], ('Firefox', 'Firefox Developer Edition', 'Firefox Nightly'))
        self.assertEqual(mac.client_processes, LEGACY_APP_NAMES[9:])

    def test_trace_assets_and_protected_match_legacy(self):
        mac = platforms.MACOS
        # 0.3.0 extends both lists from the official Application data docs;
        # every legacy entry keeps its classification.
        self.assertEqual(mac.trace_names[:len(LEGACY_TRACE_NAMES)], LEGACY_TRACE_NAMES)
        self.assertEqual(mac.asset_names[:6], ('settings.json', 'settings.local.json', '.credentials.json',
                                               'agents', 'hooks', 'plugins'))
        self.assertFalse(set(mac.trace_names) & set(mac.asset_names))
        self.assertNotIn('skills', mac.asset_names)
        self.assertEqual(mac.resolve_all(mac.protected, self.home),
                         [self.home / name for name in LEGACY_PROTECTED])
        self.assertEqual(mac.resolve_all(mac.trash_allowed, self.home), [Path('/Applications/Claude.app')])

    def test_client_data_paths_exclude_whole_claude_and_shell_files(self):
        paths = platforms.MACOS.client_data_paths(self.home)
        self.assertNotIn(self.home / '.claude', paths)
        self.assertEqual(len(paths), len(LEGACY_CORE) - 1 - 5)

    def test_unsupported_platform_raises_without_default(self):
        with patch.object(sys, 'platform', 'sunos5'):
            with self.assertRaisesRegex(RuntimeError, '不支持的平台'):
                REAL_CURRENT()


class ArgumentTests(unittest.TestCase):
    def test_help_works_on_unsupported_platform(self):
        with patch.object(sys, 'platform', 'linux'), patch.object(sys, 'argv', ['sql', '--help']), \
                patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as caught:
                SQL.main()
        self.assertEqual(caught.exception.code, 0)

    def test_unknown_browser_rejected_after_platform_check(self):
        with patch.object(platforms, 'current', return_value=platforms.WINDOWS), \
                patch.object(sys, 'argv', ['sql', '--browser', 'Arc']), patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as caught:
                SQL.main()
        self.assertEqual(caught.exception.code, 2)


class EncodingTests(unittest.TestCase):
    def test_cli_switches_redirected_streams_to_utf8(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='ascii', newline='\n')
        def main():
            print('中文输出')
            return 0
        with patch.object(sys, 'stdout', stream), patch.object(sys, 'stderr', io.TextIOWrapper(io.BytesIO(), encoding='ascii')):
            self.assertEqual(common.cli(main), 0)
            stream.flush()
        self.assertEqual(raw.getvalue().decode('utf-8'), '中文输出\n')

    def test_cli_reads_piped_input_as_utf8(self):
        stdin = io.TextIOWrapper(io.BytesIO('是\n'.encode('utf-8')), encoding='cp1252')
        def main():
            return 0 if input() == '是' else 1
        with patch.object(sys, 'stdin', stdin), \
                patch.object(sys, 'stdout', io.TextIOWrapper(io.BytesIO(), encoding='ascii')), \
                patch.object(sys, 'stderr', io.TextIOWrapper(io.BytesIO(), encoding='ascii')):
            self.assertEqual(common.cli(main), 0)

    def test_entry_point_output_is_utf8_under_non_utf8_locale_encoding(self):
        env = dict(os.environ, PYTHONIOENCODING='ascii')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_environment.py'), '--help'],
                                capture_output=True, env=env, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        self.assertIn('输出结构化报告', result.stdout.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
