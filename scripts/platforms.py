"""Per-platform locations, tool names and process rules.

Location entries:
  '~/rest'          relative to the user's home directory
  '%NAME%/rest'     relative to environment variable NAME (Windows); a missing
                    variable is an error, never a guessed default
  '%DOCUMENTS%/...' the user's real Documents folder (may be redirected)
  anything else     absolute
One path segment may contain '*' (expand() lists matches strictly).
Nothing here touches the filesystem at import time, so modules stay importable
on unsupported platforms (CI checks portable logic there).
"""
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import re
import sys

CLI_PROCESS = re.compile(r'(?:^|/)claude(?:\s|$)', re.I)
CLI_PACKAGE = '/@anthropic-ai/claude-code/'
VARIABLE = re.compile(r'^%([A-Z_]+)%(?:/(.*))?$')


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
    safari_root: object
    safari_files: tuple
    browser_cache: object
    editor_extensions: tuple
    editor_user_dirs: tuple
    system_dirs: tuple
    protected: tuple
    # Every path below these is refused, not only the directory itself.
    protected_trees: tuple
    # (container, allowed entries): below a container only the allowed
    # entries and their descendants may be moved.
    confined: tuple
    trash_allowed: tuple
    trash_diagnostic_dir: object
    out_of_scope: str
    shell_pattern: object

    def resolve(self, entry, home=None):
        if '*' in entry:
            raise ValueError(f'通配位置需要 expand(): {entry}')
        home = Path.home() if home is None else Path(home)
        if entry.startswith('~/'):
            return home / entry[2:]
        match = VARIABLE.match(entry)
        if match:
            return self.variable_dir(match.group(1)) / (match.group(2) or '')
        return Path(entry)

    def variable_dir(self, name):
        if name not in os.environ:
            raise RuntimeError(f'环境变量 {name} 未设置，无法确定位置；未执行任何操作')
        return Path(os.environ[name])

    def resolve_all(self, entries, home=None):
        return [self.resolve(entry, home) for entry in entries]

    def matches(self, entry, home=None):
        """[(path, matched segment or None)]; '*' lists existing matches strictly."""
        if '*' not in entry:
            return [(self.resolve(entry, home), None)]
        import common  # deferred: common imports this module
        head, _, pattern = entry.partition('*')
        head, _, start = head.rpartition('/')
        segment, _, tail = (start + '*' + pattern).partition('/')
        if '*' in tail:
            raise ValueError(f'只支持一个通配段: {entry}')
        parent = self.resolve(head, home)
        if not common.directory(parent):
            return []
        found = []
        for child in sorted(parent.iterdir()):
            if fnmatch.fnmatchcase(child.name.lower(), segment.lower()) and common.directory(child):
                found.append((child / tail if tail else child, child.name))
        return found

    def expand(self, entry, home=None):
        return [path for path, _ in self.matches(entry, home)]

    def expand_all(self, entries, home=None):
        return [path for entry in entries for path in self.expand(entry, home)]

    def core(self, home=None):
        """Default backup list as (path, stored name): client data, then shell files."""
        items = [(path, stored if name is None else f'{stored}/{name}')
                 for entry, stored in self.client_data for path, name in self.matches(entry, home)]
        items += [(self.resolve(entry, home), 'shell/' + entry.split('/', 1)[1]) for entry in self.shell_files]
        return items

    def client_data_paths(self, home=None):
        """Client data excluding the whole .claude directory (it holds user assets)."""
        return [path for entry, _ in self.client_data if entry != '~/.claude'
                for path in self.expand(entry, home)]

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

    def persistent_env_names(self):
        """Environment variable names stored outside shell files (none on macOS)."""
        return []

    def check_path_form(self, path):
        """Reject path forms the tools do not support (POSIX absolute paths are fine)."""

    def is_claude_process(self, proc):
        return ('/Claude.app/' in proc or Path(proc).name.startswith('Claude Helper')
                or self.is_cli_process(proc))


@dataclass(frozen=True)
class WindowsPlatform(Platform):
    """Processes are (name, executable path, command line) records."""

    def variable_dir(self, name):
        if name == 'DOCUMENTS':
            import winplat  # deferred: only Windows reads the registry
            return winplat.documents_dir()
        # Long names: variables may hold 8.3 short paths (e.g. RUNNER~1).
        return super().variable_dir(name).resolve()

    def persistent_env_names(self):
        import winplat
        return winplat.user_environment_names()

    def check_path_form(self, path):
        # Only local drive-letter paths: no UNC shares, no \\?\ device paths.
        if not re.fullmatch(r'[A-Za-z]:', path.drive):
            raise ValueError(f'只支持本地盘符绝对路径（不支持 UNC、\\\\?\\ 或网络路径）: {path}')

    def match_process(self, proc, names):
        return proc[0].lower() in {name.lower() for name in names}

    def is_cli_process(self, proc):
        name, _, command = proc
        command = command.lower().replace('\\', '/')
        return name.lower() == 'node.exe' and CLI_PACKAGE in command

    def is_claude_process(self, proc):
        return proc[0].lower() == 'claude.exe' or self.is_cli_process(proc)


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
    shell_files=('~/.zshrc', '~/.bashrc', '~/.profile', '~/.zprofile', '~/.zshenv'),
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
    protected_trees=('~/.Trash', '~/.ssh'),
    confined=(),
    trash_allowed=('/Applications/Claude.app',),
    trash_diagnostic_dir='/Library/Logs/DiagnosticReports',
    out_of_scope='范围外：钥匙串、APFS/Time Machine、其他用户、外置盘、任意项目目录、npm 缓存、登录 shell 动态行为。',
    shell_pattern=re.compile(r'^\s*(?:export\s+)?(?:ANTHROPIC|CLAUDE|HEADROOM)[A-Z_]*=|^\s*alias\s+claude='),
)

MSIX_DATA = ('%LOCALAPPDATA%/Packages/Claude_*/LocalCache/Roaming/Claude',
             '%LOCALAPPDATA%/Packages/Claude_*/LocalCache/Roaming/Claude-3p')

WINDOWS = WindowsPlatform(
    key='win32', label='Windows',
    client_data=(
        ('~/.claude', 'dot-claude'), ('~/.claude.json', 'dot-claude.json'),
        ('%APPDATA%/Claude', 'AppData-Claude'), ('%APPDATA%/Claude-3p', 'AppData-Claude-3p'),
        (MSIX_DATA[0], 'MSIX-Claude'), (MSIX_DATA[1], 'MSIX-Claude-3p'),
        ('%LOCALAPPDATA%/claude-cli-nodejs', 'Local-claude-cli-nodejs'),
    ),
    shell_files=('~/.bashrc', '~/.bash_profile', '~/.profile',
                 '%DOCUMENTS%/PowerShell/Microsoft.PowerShell_profile.ps1',
                 '%DOCUMENTS%/PowerShell/profile.ps1',
                 '%DOCUMENTS%/WindowsPowerShell/Microsoft.PowerShell_profile.ps1',
                 '%DOCUMENTS%/WindowsPowerShell/profile.ps1'),
    trace_names=MACOS.trace_names,
    asset_names=MACOS.asset_names,
    extra_config=MACOS.extra_config,
    desktop_apps=('%LOCALAPPDATA%/AnthropicClaude', '%LOCALAPPDATA%/Packages/Claude_*'),
    cli_candidates=('~/.local/bin/claude.exe', '%APPDATA%/npm/claude.cmd',
                    '%LOCALAPPDATA%/Microsoft/WinGet/Links/claude.exe'),
    tools=('powershell', 'git', 'node', 'npm'),
    base_tools=('powershell',),
    browser_roots=(
        ('Chrome', '%LOCALAPPDATA%/Google/Chrome/User Data'),
        ('Chrome Beta', '%LOCALAPPDATA%/Google/Chrome Beta/User Data'),
        ('Chrome Canary', '%LOCALAPPDATA%/Google/Chrome SxS/User Data'),
        ('Edge', '%LOCALAPPDATA%/Microsoft/Edge/User Data'),
        ('Brave', '%LOCALAPPDATA%/BraveSoftware/Brave-Browser/User Data'),
        ('Vivaldi', '%LOCALAPPDATA%/Vivaldi/User Data'),
        ('Chromium', '%LOCALAPPDATA%/Chromium/User Data'),
    ),
    browser_processes=('chrome.exe', 'msedge.exe', 'brave.exe', 'vivaldi.exe'),
    client_processes=('claude.exe', 'Code.exe', 'Cursor.exe', 'Windsurf.exe'),
    # Safari does not exist; Chromium keeps its HTTP cache inside the profile,
    # which the default profile scan already walks.
    safari_root=None,
    safari_files=(),
    browser_cache=None,
    editor_extensions=MACOS.editor_extensions,
    editor_user_dirs=('%APPDATA%/Code/User', '%APPDATA%/Cursor/User', '%APPDATA%/Windsurf/User'),
    system_dirs=('%LOCALAPPDATA%/CrashDumps', '%APPDATA%/Microsoft/Windows/Start Menu/Programs'),
    protected=('~/AppData', '~/AppData/Local', '~/AppData/Roaming', '~/AppData/LocalLow',
               '%APPDATA%', '%LOCALAPPDATA%', '%LOCALAPPDATA%/Packages', '%LOCALAPPDATA%/Programs',
               '%LOCALAPPDATA%/Microsoft', '%APPDATA%/Microsoft', '%DOCUMENTS%',
               '~/Desktop', '~/Documents', '~/Downloads', '~/Pictures', '~/Videos', '~/Music',
               '~/OneDrive', '~/Favorites', '~/Contacts', '~/Links', '~/Saved Games', '~/Searches',
               '~/.config', '~/.local', '~/.local/bin', '~/.local/share', '~/.ssh', '~/.codex',
               '~/.agents', '~/.vscode', '~/.cursor', '~/.windsurf'),
    protected_trees=('~/.ssh',),
    # Only the Claude data folders inside an MSIX package may be moved.
    confined=(('%LOCALAPPDATA%/Packages', MSIX_DATA),),
    trash_allowed=(),
    trash_diagnostic_dir=None,
    out_of_scope=('范围外：Windows 凭据管理器、注册表（只读取用户环境变量名与卸载项名称）、卷影副本/系统还原、'
                  '回收站内容、其他用户、外置盘、任意项目目录、npm 缓存、WSL 内数据、MSIX 应用本体。'),
    shell_pattern=re.compile(
        r'^\s*(?:export\s+)?(?:ANTHROPIC|CLAUDE|HEADROOM)[A-Z_]*=|^\s*alias\s+claude='
        r'|^\s*\$env:(?:ANTHROPIC|CLAUDE|HEADROOM)[A-Z_]*\s*='
        r'|^\s*Set-Alias\s+(?:-Name\s+)?claude\b'
        r'|SetEnvironmentVariable\(\s*[\'"](?:ANTHROPIC|CLAUDE|HEADROOM)', re.I),
)

PLATFORMS = {MACOS.key: MACOS, WINDOWS.key: WINDOWS}


def current():
    platform = PLATFORMS.get(sys.platform)
    if platform is None:
        raise RuntimeError(f'不支持的平台 {sys.platform}；仅支持 macOS 与 Windows；未执行任何操作')
    return platform
