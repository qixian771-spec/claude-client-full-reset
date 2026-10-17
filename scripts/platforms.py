"""Per-platform locations, tool names and process rules.

Entries beginning with '~/' are relative to the user's home directory; all
others are absolute. Nothing here touches the filesystem at import time, so
modules stay importable on unsupported platforms (CI checks portable logic).
"""
from dataclasses import dataclass
from pathlib import Path
import re
import sys

CLI_PROCESS = re.compile(r'(?:^|/)claude(?:\s|$)', re.I)
CLI_PACKAGE = '/@anthropic-ai/claude-code/'


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    # (location, stored name inside a backup); '.claude' holds user assets.
    client_data: tuple
    shell_files: tuple
    trace_names: tuple
    asset_names: tuple
    extra_config: tuple
    desktop_apps: tuple
    cli_candidates: tuple
    tools: tuple
    base_tools: tuple
    browser_roots: tuple
    browser_processes: tuple
    client_processes: tuple
    safari_root: str
    safari_files: tuple
    browser_cache: str
    editor_extensions: tuple
    editor_user_dirs: tuple
    system_dirs: tuple
    protected: tuple
    trash_allowed: tuple
    trash_diagnostic_dir: str
    out_of_scope: str

    def resolve(self, entry, home=None):
        home = Path.home() if home is None else Path(home)
        return home / entry[2:] if entry.startswith('~/') else Path(entry)

    def resolve_all(self, entries, home=None):
        return [self.resolve(entry, home) for entry in entries]

    def core(self):
        """Default backup list: client data, then shell startup files."""
        return list(self.client_data) + [('~/' + name, 'shell/' + name) for name in self.shell_files]

    def client_data_paths(self, home=None):
        """Client data excluding the whole .claude directory (it holds user assets)."""
        return [self.resolve(entry, home) for entry, _ in self.client_data if entry != '~/.claude']

    def browsers(self, home=None):
        return [(name, self.resolve(root, home)) for name, root in self.browser_roots]

    def browser_names(self):
        return [name for name, _ in self.browser_roots]

    def match_process(self, proc, names):
        base = Path(proc).name
        return any(base == name or base.startswith(name + ' Helper') or
                   f'/{name}.app/' in proc for name in names)

    def is_cli_process(self, proc):
        return bool(CLI_PROCESS.search(proc)) or CLI_PACKAGE in proc

    def is_claude_process(self, proc):
        return ('/Claude.app/' in proc or Path(proc).name.startswith('Claude Helper')
                or self.is_cli_process(proc))


MACOS = Platform(
    key='darwin', label='macOS',
    client_data=(
        ('~/.claude', 'dot-claude'), ('~/.claude.json', 'dot-claude.json'),
        ('~/Library/Application Support/Claude', 'AppSupport-Claude'),
        ('~/Library/Application Support/Claude-3p', 'AppSupport-Claude-3p'),
        ('~/Library/Preferences/com.anthropic.claudefordesktop.plist', 'plist'),
        ('~/Library/Caches/com.anthropic.claudefordesktop', 'Caches-app'),
        ('~/Library/Caches/com.anthropic.claudefordesktop.ShipIt', 'Caches-ShipIt'),
        ('~/Library/Caches/claude-cli-nodejs', 'Caches-cli'),
        ('~/Library/HTTPStorages/com.anthropic.claudefordesktop', 'HTTPStorages-app'),
        ('~/Library/Logs/Claude', 'Logs-Claude'), ('~/Library/Logs/Claude-3p', 'Logs-Claude-3p'),
        ('~/Library/Saved Application State/com.anthropic.claudefordesktop.savedState', 'SavedState'),
    ),
    shell_files=('.zshrc', '.bashrc', '.profile', '.zprofile', '.zshenv'),
    trace_names=('projects', 'history.jsonl', 'sessions', 'tasks', 'teams',
                 'shell-snapshots', 'session-env', 'file-history', 'paste-cache', '.cc-writes'),
    asset_names=('settings.json', 'settings.local.json', '.credentials.json', 'agents', 'hooks', 'plugins'),
    extra_config=('~/.config/claude', '~/.anthropic'),
    desktop_apps=('/Applications/Claude.app', '~/Applications/Claude.app'),
    cli_candidates=('~/.local/bin/claude', '/opt/homebrew/bin/claude', '/usr/local/bin/claude'),
    tools=('bash', 'ditto', 'osascript', 'git', 'node', 'npm'),
    base_tools=('bash', 'ditto', 'osascript'),
    browser_roots=(
        ('Chrome', '~/Library/Application Support/Google/Chrome'),
        ('Chrome Beta', '~/Library/Application Support/Google/Chrome Beta'),
        ('Chrome Canary', '~/Library/Application Support/Google/Chrome Canary'),
        ('Edge', '~/Library/Application Support/Microsoft Edge'),
        ('Brave', '~/Library/Application Support/BraveSoftware/Brave-Browser'),
        ('Vivaldi', '~/Library/Application Support/Vivaldi'),
        ('Chromium', '~/Library/Application Support/Chromium'),
        ('Arc', '~/Library/Application Support/Arc/User Data'),
    ),
    browser_processes=('Google Chrome', 'Google Chrome Beta', 'Google Chrome Canary',
                       'Microsoft Edge', 'Brave Browser', 'Vivaldi', 'Chromium', 'Arc', 'Safari'),
    client_processes=('Claude', 'Code', 'Cursor', 'Windsurf'),
    safari_root='~/Library/Safari',
    safari_files=('History.db', 'RecentlyClosedTabs.plist', 'Downloads.plist'),
    browser_cache='~/Library/Caches/Google/Chrome',
    editor_extensions=('~/.vscode/extensions', '~/.cursor/extensions', '~/.windsurf/extensions'),
    editor_user_dirs=('~/Library/Application Support/Code/User',
                      '~/Library/Application Support/Cursor/User',
                      '~/Library/Application Support/Windsurf/User'),
    system_dirs=('~/Library/Logs/DiagnosticReports', '/Library/Logs/DiagnosticReports',
                 '~/.Trash', '~/Applications', '~/Library/Containers',
                 '~/Library/Group Containers', '~/Library/Application Scripts'),
    protected=('~/Library', '~/Library/Application Support', '~/Library/Caches', '~/Library/Logs',
               '~/Library/Preferences', '~/Library/HTTPStorages', '~/Library/Containers',
               '~/Library/Group Containers', '~/Library/Application Scripts', '~/.Trash',
               '~/Desktop', '~/Documents', '~/Downloads', '~/Pictures', '~/Movies', '~/Music',
               '~/Applications', '~/.config', '~/.local', '~/.ssh', '~/.codex', '~/.agents',
               '~/.vscode', '~/.cursor', '~/.windsurf'),
    trash_allowed=('/Applications/Claude.app',),
    trash_diagnostic_dir='/Library/Logs/DiagnosticReports',
    out_of_scope='范围外：钥匙串、APFS/Time Machine、其他用户、外置盘、任意项目目录、npm 缓存、登录 shell 动态行为。',
)

PLATFORMS = {MACOS.key: MACOS}


def current():
    platform = PLATFORMS.get(sys.platform)
    if platform is None:
        raise RuntimeError(f'不支持的平台 {sys.platform}；仅支持 macOS；未执行任何操作')
    return platform
