"""Windows logic exercised on any OS with a synthetic profile.

Native behaviour (registry, processes, Recycle Bin, junctions) is covered by
the windows-latest CI job; these tests pin the portable rules.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_workflows import BS, common, platforms, verify
import winplat

WIN = platforms.WINDOWS
# An absolute path on the running OS (has a drive on Windows).
PROFILE = Path(Path.cwd().anchor) / 'Users' / 'fixture'


class WindowsFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reset-win-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / 'Users/fixture'
        self.roaming = self.home / 'AppData/Roaming'
        self.local = self.home / 'AppData/Local'
        self.documents = self.home / 'OneDrive/Documents'
        for folder in (self.roaming, self.local, self.documents):
            folder.mkdir(parents=True)
        self.user_env = []
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(Path, 'home', return_value=self.home))
        environment = {key: value for key, value in os.environ.items()
                       if not verify.ENV_PAT.fullmatch(key)}
        environment.update(APPDATA=str(self.roaming), LOCALAPPDATA=str(self.local))
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        stack.enter_context(patch.object(platforms, 'current', return_value=WIN))
        stack.enter_context(patch.object(winplat, 'documents_dir', side_effect=lambda: self.documents))
        stack.enter_context(patch.object(winplat, 'user_environment_names', side_effect=lambda: self.user_env))

    def file(self, path, text='data'):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def msix(self, package='Claude_pzs8sxrjxfjjc'):
        return self.file(self.local / 'Packages' / package / 'LocalCache/Roaming/Claude/config.json').parent


class WindowsPathTableTests(WindowsFixture):
    def test_variables_resolve_from_environment(self):
        self.assertEqual(WIN.resolve('%APPDATA%/Claude'), self.roaming / 'Claude')
        self.assertEqual(WIN.resolve('%LOCALAPPDATA%/Google/Chrome/User Data'), self.local / 'Google/Chrome/User Data')
        self.assertEqual(WIN.resolve('%DOCUMENTS%/PowerShell/profile.ps1'), self.documents / 'PowerShell/profile.ps1')
        self.assertEqual(WIN.resolve('~/.claude'), self.home / '.claude')

    def test_missing_environment_variable_is_an_error_not_a_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'APPDATA'):
                WIN.resolve('%APPDATA%/Claude')

    def test_glob_entry_cannot_be_resolved_directly(self):
        with self.assertRaises(ValueError):
            WIN.resolve(platforms.MSIX_DATA[0])

    def test_core_lists_msix_data_per_package_and_documents_shell_files(self):
        data = self.msix()
        core = dict((str(path), stored) for path, stored in WIN.core())
        self.assertEqual(core[str(data)], 'MSIX-Claude/Claude_pzs8sxrjxfjjc')
        self.assertEqual(core[str(self.roaming / 'Claude')], 'AppData-Claude')
        self.assertEqual(core[str(self.documents / 'PowerShell/Microsoft.PowerShell_profile.ps1')],
                         'shell/PowerShell/Microsoft.PowerShell_profile.ps1')
        self.assertEqual(core[str(self.home / '.bashrc')], 'shell/.bashrc')
        self.assertEqual(len(set(core.values())), len(core), 'stored names must be unique')

    def test_multiple_msix_packages_are_all_listed(self):
        self.msix('Claude_one'); self.msix('Claude_two')
        found = [stored for _, stored in WIN.core() if stored.startswith('MSIX-Claude/')]
        self.assertEqual(found, ['MSIX-Claude/Claude_one', 'MSIX-Claude/Claude_two'])

    def test_glob_does_not_match_other_packages_and_is_case_insensitive(self):
        self.file(self.local / 'Packages/ClaudeHelper_x/LocalCache/Roaming/Claude/a')
        self.file(self.local / 'Packages/claude_lower/LocalCache/Roaming/Claude/a')
        self.assertEqual([p.parts[-4] for p in WIN.expand(platforms.MSIX_DATA[0])], ['claude_lower'])

    def test_glob_parent_symlink_is_an_error(self):
        target = self.home / 'elsewhere'
        target.mkdir()
        (self.local / 'Packages').symlink_to(target)
        with self.assertRaises(ValueError):
            WIN.expand(platforms.MSIX_DATA[0])

    def test_browser_roots_live_under_localappdata_without_arc(self):
        roots = dict(WIN.browsers())
        self.assertEqual(roots['Chrome Canary'], self.local / 'Google/Chrome SxS/User Data')
        self.assertEqual(roots['Edge'], self.local / 'Microsoft/Edge/User Data')
        self.assertNotIn('Arc', roots)


class WindowsScanTests(WindowsFixture):
    def collect(self):
        return verify.collect(self.home, no_browser=True)

    def test_clean_profile_reports_no_findings(self):
        self.assertEqual(sum(map(len, self.collect().values())), 0)

    def test_client_data_traces_and_msix_are_found(self):
        self.file(self.roaming / 'Claude/config.json')
        self.file(self.home / '.claude/projects/p/s.jsonl')
        data = self.msix()
        found = self.collect()['客户端数据']
        self.assertIn(str(self.roaming / 'Claude'), found)
        self.assertIn(str(self.home / '.claude/projects'), found)
        self.assertIn(str(data), found)

    def test_powershell_profile_assignments_and_registry_names_found_without_values(self):
        profile = self.file(self.documents / 'PowerShell/Microsoft.PowerShell_profile.ps1',
                            'Write-Host hi\n$env:ANTHROPIC_API_KEY = "SECRET-VALUE"\nSet-Alias claude foo\n'
                            "[Environment]::SetEnvironmentVariable('CLAUDE_CODE_X', '1', 'User')\n")
        self.file(self.home / '.bashrc', 'export ANTHROPIC_BASE_URL=https://example\n')
        self.user_env = ['Path', 'Anthropic_Api_Key', 'TEMP']
        found = self.collect()['shell/当前环境']
        self.assertIn(f'{profile}:2', found)
        self.assertIn(f'{profile}:3', found)
        self.assertIn(f'{profile}:4', found)
        self.assertIn(f'{self.home / ".bashrc"}:1', found)
        self.assertIn('user-env:Anthropic_Api_Key', found)
        self.assertNotIn(f'{profile}:1', found)
        self.assertNotIn('SECRET-VALUE', repr(found))

    def test_system_and_editor_locations(self):
        self.file(self.local / 'CrashDumps/claude.exe.1234.dmp')
        self.file(self.roaming / 'Microsoft/Windows/Start Menu/Programs/Claude.lnk')
        self.file(self.roaming / 'Code/User/settings.json', '{"claude.enabled": true}')
        found = self.collect()
        self.assertEqual(len(found['系统指定目录']), 2)
        self.assertEqual(found['编辑器'], [str(self.roaming / 'Code/User/settings.json')])

    def test_browser_scan_has_no_safari_and_no_separate_cache(self):
        self.assertEqual(BS.scan_safari(), [])
        with patch.object(BS, 'browser_roots', return_value=[]):
            self.assertIsNone(BS.collect(deep=True)['cache'])
        self.assertIn('Safari 不适用', BS.scope_note(WIN))
        self.assertIn('profile 内', BS.scope_note(WIN))

    def test_out_of_scope_note_is_windows_specific(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            verify.report({'x': []})
        self.assertIn('凭据管理器', output.getvalue())


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeRegistry:
    HKEY_CURRENT_USER = 'HKCU'

    def __init__(self, values=None, names=()):
        self.values = values or {}
        self.names = list(names)

    def OpenKey(self, root, path):
        return FakeKey()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(2, 'missing')
        return self.values[name], 2

    def ExpandEnvironmentStrings(self, value):
        return value.replace('%USERPROFILE%', str(PROFILE))

    def QueryInfoKey(self, key):
        return (0, len(self.names), 0)

    def EnumValue(self, key, index):
        return (self.names[index], 'value-not-read', 1)


class WindowsRegistryTests(unittest.TestCase):
    def test_documents_folder_expands_registry_value(self):
        fake = FakeRegistry({'Personal': '%USERPROFILE%/OneDrive/Documents'})
        with patch.object(winplat, '_winreg', return_value=fake):
            self.assertEqual(winplat.documents_dir(), PROFILE / 'OneDrive/Documents')

    def test_missing_documents_value_is_an_error(self):
        with patch.object(winplat, '_winreg', return_value=FakeRegistry()):
            with self.assertRaisesRegex(RuntimeError, '文档'):
                winplat.documents_dir()

    def test_relative_documents_value_is_an_error(self):
        with patch.object(winplat, '_winreg', return_value=FakeRegistry({'Personal': 'Documents'})):
            with self.assertRaises(RuntimeError):
                winplat.documents_dir()

    def test_environment_names_enumerated_by_count(self):
        with patch.object(winplat, '_winreg', return_value=FakeRegistry(names=['Path', 'ANTHROPIC_API_KEY'])):
            self.assertEqual(winplat.user_environment_names(), ['Path', 'ANTHROPIC_API_KEY'])


def process(name, path='', command=''):
    return {'Name': name, 'ExecutablePath': path, 'CommandLine': command}


class WindowsProcessTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(platforms, 'current', return_value=WIN))
        stack.enter_context(patch.dict(os.environ, {'SystemRoot': 'C:/Windows'}))

    def records(self, output):
        with patch.object(common, 'run', return_value=output) as run:
            records = common.process_list()
        args = run.call_args.args[0]
        self.assertTrue(Path(args[0]).as_posix().endswith('System32/WindowsPowerShell/v1.0/powershell.exe'))
        self.assertIn('-NoProfile', args)
        return records

    def test_matches_desktop_cli_node_editors_and_browsers(self):
        procs = self.records(json.dumps([
            process('Claude.exe', r'C:\Program Files\WindowsApps\Claude_1.0_x64__pzs8sxrjxfjjc\app\Claude.exe'),
            process('claude.exe', r'C:\Users\u\.local\bin\claude.exe', 'claude --resume'),
            process('node.exe', r'C:\nodejs\node.exe', r'node C:\Users\u\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\cli.js'),
            process('node.exe', r'C:\nodejs\node.exe', r'node C:\work\server.js'),
            process('Code.exe'), process('CHROME.EXE'), process('msedge.exe'),
            process('svchost.exe'), process('claude-notes.exe'), process('System Idle Process', None, None),
        ]))
        self.assertEqual(len(common.relevant_processes(procs)), 6)
        self.assertEqual(len(common.relevant_processes(procs, True)), 2)
        self.assertEqual(sum(WIN.is_claude_process(p) for p in procs), 3)

    def test_single_object_output_is_accepted(self):
        self.assertEqual(self.records(json.dumps(process('chrome.exe'))), [('chrome.exe', '', '')])

    def test_invalid_or_empty_output_is_an_error_without_echoing_it(self):
        for output in ('not json SECRET', '[]', '"text"', json.dumps([{'ExecutablePath': 'x'}])):
            with self.subTest(output=output), self.assertRaises(RuntimeError) as caught:
                self.records(output)
            self.assertNotIn('SECRET', str(caught.exception))

    def test_powershell_failure_propagates(self):
        with patch.object(common, 'run', side_effect=subprocess.CalledProcessError(1, ['powershell'])):
            with self.assertRaises(subprocess.CalledProcessError):
                common.require_stopped()

    def test_missing_systemroot_is_an_error(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, 'SystemRoot'):
            common.process_list()

    def test_running_browser_blocks_writes(self):
        with patch.object(common, 'run', return_value=json.dumps([process('brave.exe')])):
            with self.assertRaisesRegex(RuntimeError, '仍在运行'):
                common.require_stopped(browsers_only=True)


@unittest.skipUnless(sys.platform == 'win32', 'native Windows process query')
class NativeWindowsProcessTests(unittest.TestCase):
    def test_real_query_includes_this_python_process(self):
        names = [name.lower() for name, _, _ in common.process_list()]
        self.assertIn(Path(sys.executable).name.lower(), names)


if __name__ == '__main__':
    unittest.main()
