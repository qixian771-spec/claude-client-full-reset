from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from test_workflows import REAL_CURRENT, platforms

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
        self.assertEqual([(mac.resolve(src, self.home), name) for src, name in mac.core()],
                         [(self.home / src, name) for src, name in LEGACY_CORE])

    def test_browser_roots_match_legacy(self):
        support = self.home / 'Library/Application Support'
        self.assertEqual(platforms.MACOS.browsers(self.home),
                         [(name, support / sub) for name, sub in LEGACY_BROWSER_PATHS])

    def test_process_names_match_legacy_order_and_grouping(self):
        mac = platforms.MACOS
        self.assertEqual(mac.browser_processes + mac.client_processes, LEGACY_APP_NAMES)
        self.assertEqual(mac.browser_processes, LEGACY_APP_NAMES[:9])

    def test_trace_assets_and_protected_match_legacy(self):
        mac = platforms.MACOS
        self.assertEqual(mac.trace_names, LEGACY_TRACE_NAMES)
        self.assertEqual(mac.asset_names, ('settings.json', 'settings.local.json', '.credentials.json',
                                           'agents', 'hooks', 'plugins'))
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


if __name__ == '__main__':
    unittest.main()
