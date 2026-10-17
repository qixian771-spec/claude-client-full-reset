"""Windows logic exercised on any OS with a synthetic profile.

Native behaviour (registry, processes, Recycle Bin, junctions) is covered by
the windows-latest CI job; these tests pin the portable rules.
"""
import contextlib
import io
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_workflows import BS, backup, common, platforms, trash, verify
import check_environment as env
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
        if sys.platform != 'win32':
            # Fixture paths are POSIX here; the drive-letter rule is covered by
            # WindowsPathFormTests and runs for real on Windows.
            stack.enter_context(patch.object(platforms.WindowsPlatform, 'check_path_form', lambda self, path: None))

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


class FakeStat:
    def __init__(self, mode, attributes):
        self.st_mode = mode
        self.st_file_attributes = attributes
        self.st_size = 0


class WindowsPathFormTests(unittest.TestCase):
    def test_path_forms(self):
        for good in ('C:/Users/u/.claude', r'd:\data\x'):
            WIN.check_path_form(PureWindowsPath(good))
        for bad in (r'\\server\share\x', r'\\?\C:\Users\u', r'\\.\PhysicalDrive0', '/no/drive'):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                WIN.check_path_form(PureWindowsPath(bad))

    def test_bare_variable_entries_resolve_to_the_folder(self):
        with patch.dict(os.environ, {'APPDATA': str(PROFILE / 'Roaming')}):
            self.assertEqual(WIN.resolve('%APPDATA%'), (PROFILE / 'Roaming').resolve())


class WindowsPathSafetyTests(WindowsFixture):
    def test_containers_and_user_folders_are_refused(self):
        data = self.msix()
        package = data.parents[2]
        self.file(self.local / 'Packages/Other_x/LocalCache/Roaming/Claude/a')
        for path in (self.home / 'AppData', self.local, self.roaming, self.local / 'Packages', package,
                     package / 'LocalCache', package / 'LocalCache/Roaming', self.documents,
                     self.local / 'Packages/Other_x/LocalCache/Roaming/Claude', self.home / '.local/share'):
            path.mkdir(parents=True, exist_ok=True)
            with self.subTest(path=path), self.assertRaises(ValueError):
                trash.validate_path(str(path))

    def test_ssh_tree_refused(self):
        key = self.file(self.home / '.ssh/id_ed25519')
        with self.assertRaisesRegex(ValueError, '危险'):
            trash.validate_path(str(key))

    def test_msix_claude_data_and_regular_client_data_allowed(self):
        data = self.msix()
        third = self.file(data.parent / 'Claude-3p/x').parent
        for path in (data, data / 'config.json', third, self.file(self.roaming / 'Claude/a').parent,
                     self.file(self.local / 'CrashDumps/claude.exe.1.dmp')):
            self.assertEqual(trash.validate_path(str(path)), path)

    def test_outside_home_refused(self):
        outside = Path(self.temp.name).resolve() / 'elsewhere'
        outside.mkdir()
        with self.assertRaisesRegex(ValueError, '范围'):
            trash.validate_path(str(outside))

    def test_reparse_point_directory_is_a_link(self):
        junction = FakeStat(stat.S_IFDIR | 0o755, stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with patch.object(Path, 'lstat', return_value=junction):
            self.assertTrue(common.is_link(self.home))
            with self.assertRaises(ValueError):
                backup.fingerprint(self.home)
        with patch.object(Path, 'lstat', return_value=junction), patch.object(Path, 'stat', return_value=junction):
            with self.assertRaises(ValueError):
                common.directory(self.home)

    def test_reparse_point_file_is_not_regular(self):
        placeholder = FakeStat(stat.S_IFREG | 0o644, stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with patch.object(Path, 'lstat', return_value=placeholder):
            with self.assertRaises(ValueError):
                common.regular(self.home / 'file')

    def test_plain_attributes_are_not_links(self):
        with patch.object(Path, 'lstat', return_value=FakeStat(stat.S_IFDIR | 0o755, 0x10)):
            self.assertFalse(common.is_link(self.home))


@unittest.skipUnless(sys.platform == 'win32', 'native Windows junctions and drive paths')
class NativeWindowsPathTests(WindowsFixture):
    def junction(self):
        target = self.home / 'target'
        target.mkdir()
        link = self.home / 'junction'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
        self.assertFalse(link.is_symlink(), 'is_symlink() does not see junctions; is_link must')
        return link

    def test_junction_is_refused_everywhere(self):
        link = self.junction()
        self.assertTrue(common.is_link(link))
        with self.assertRaises(ValueError):
            common.directory(link)
        with self.assertRaises(ValueError):
            backup.fingerprint(link)
        with self.assertRaisesRegex(ValueError, 'junction'):
            trash.validate_path(str(link))
        inside = link / 'x'
        with self.assertRaisesRegex(ValueError, 'junction'):
            trash.validate_path(str(inside), must_exist=False)

    def test_unc_and_device_paths_refused(self):
        for raw in (r'\\localhost\c$\Users', '\\\\?\\' + str(self.home)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                backup.absolute_path(raw)

    def test_case_variant_of_protected_folder_refused(self):
        with self.assertRaisesRegex(ValueError, '危险'):
            trash.validate_path(str(self.home / 'APPDATA' / 'local'))


class WindowsBackupTests(WindowsFixture):
    def setUp(self):
        super().setUp()
        self.dest = self.home.parent / 'backups'
        self.dest.mkdir()
        context = patch.object(common, 'process_list', return_value=[])
        context.start()
        self.addCleanup(context.stop)
        context = patch.object(common, 'run', side_effect=AssertionError('Windows must not run ditto or other commands'))
        context.start()
        self.addCleanup(context.stop)

    def backup(self):
        # The fixture profile sits beside the backup parent, so the
        # outside-profile notice is expected; it has its own test.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return backup.create_backup(self.dest)

    def test_backup_verify_and_partial_restore_round_trip(self):
        config = self.file(self.home / '.claude.json', '{"a": 1}')
        history = self.file(self.home / '.claude/history.jsonl', '中文历史\n')
        settings = self.file(self.home / '.claude/settings.json', 'keep')
        data = self.msix()
        self.file(data / 'nested/deep/file.bin', 'x' * 5000)
        profile = self.file(self.documents / 'PowerShell/Microsoft.PowerShell_profile.ps1', '$env:A=1')
        folder = self.backup()
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['platform'], 'win32')
        stored = {entry['stored'] for entry in manifest['sources']}
        self.assertIn('MSIX-Claude/Claude_pzs8sxrjxfjjc', stored)
        self.assertIn('shell/PowerShell/Microsoft.PowerShell_profile.ps1', stored)
        self.assertIn('py -3 scripts\\backup.py', (folder / 'RESTORE.md').read_text(encoding='utf-8'))
        before = backup.inventory(data)
        history.unlink()
        shutil.rmtree(data)
        with contextlib.redirect_stdout(io.StringIO()):
            backup.restore(folder, [str(history), str(data)])
        self.assertEqual(history.read_text(encoding='utf-8'), '中文历史\n')
        self.assertEqual(backup.inventory(data), before)
        self.assertEqual(settings.read_text(encoding='utf-8'), 'keep')
        self.assertEqual(config.read_text(encoding='utf-8'), '{"a": 1}')
        self.assertTrue(profile.exists())

    def test_link_inside_source_stops_backup_without_manifest(self):
        self.file(self.roaming / 'Claude/a')
        (self.roaming / 'Claude/link').symlink_to(self.home)
        with self.assertRaisesRegex(ValueError, '重解析点|链接'):
            self.backup()
        folders = list(self.dest.iterdir())
        self.assertEqual(len(folders), 1)
        self.assertFalse((folders[0] / 'manifest.json').exists())

    def test_strict_copy_never_overwrites_or_merges(self):
        source = self.file(self.home / 'src/a.txt', 'new').parent
        existing = self.file(self.home / 'dst/a.txt', 'old').parent
        with self.assertRaises(FileExistsError):
            backup.copy_strict(source, existing)
        with self.assertRaisesRegex(ValueError, '占位目录'):
            backup.copy_strict(source, existing, reserved=True)
        self.assertEqual((existing / 'a.txt').read_text(encoding='utf-8'), 'old')
        placeholder = self.file(self.home / 'placeholder.txt', 'not empty')
        with self.assertRaisesRegex(ValueError, '占位文件'):
            backup.copy_strict(source / 'a.txt', placeholder, reserved=True)
        self.assertEqual(placeholder.read_text(encoding='utf-8'), 'not empty')

    def test_restore_refuses_existing_target(self):
        target = self.file(self.home / '.claude.json', 'original')
        folder = self.backup()
        with self.assertRaisesRegex(ValueError, '已存在'):
            backup.restore(folder, [str(target)])
        self.assertEqual(target.read_text(encoding='utf-8'), 'original')

    def test_backup_from_other_platform_refused(self):
        self.file(self.home / '.claude.json')
        folder = self.backup()
        with patch.object(platforms, 'current', return_value=platforms.MACOS):
            with self.assertRaisesRegex(ValueError, '其他平台'):
                backup.verify_backup(folder)

    def test_manifest_without_platform_is_treated_as_legacy_macos(self):
        self.file(self.home / '.claude.json')
        folder = self.backup()
        manifest = folder / 'manifest.json'
        data = json.loads(manifest.read_text(encoding='utf-8'))
        del data['platform']
        manifest.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '其他平台'):
            backup.verify_backup(folder)
        with patch.object(platforms, 'current', return_value=platforms.MACOS):
            self.assertEqual(backup.verify_backup(folder)['version'], 1)

    def test_backup_outside_profile_warns_about_permissions(self):
        self.file(self.home / '.claude.json')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            backup.create_backup(self.dest)
        self.assertIn('用户目录之外', err.getvalue())


class FakeShell:
    def __init__(self, drive=winplat.DRIVE_FIXED, nuke=False, code=0, aborted=False, remove=True):
        self.drive, self.nuke, self.code, self.aborted, self.remove = drive, nuke, code, aborted, remove
        self.deleted = []

    def drive_type(self, root):
        return self.drive

    def nuke_on_delete(self, root):
        return self.nuke

    def delete_to_recycle_bin(self, path):
        self.deleted.append(path)
        if self.remove:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        return self.code, self.aborted


class WindowsRecycleTests(WindowsFixture):
    def target(self):
        return self.file(self.roaming / 'Claude/logs/main.log')

    def test_success_requires_target_gone(self):
        path, shell = self.target(), FakeShell()
        winplat.recycle(path, shell)
        self.assertEqual(shell.deleted, [path])
        self.assertFalse(path.exists())

    def test_refusals_happen_before_any_operation(self):
        for shell, message in ((FakeShell(drive=2), '固定磁盘'), (FakeShell(drive=4), '固定磁盘'),
                               (FakeShell(nuke=True), '直接删除')):
            path = self.target()
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                winplat.recycle(path, shell)
            self.assertEqual(shell.deleted, [])
            self.assertTrue(path.exists())

    def test_failure_cancel_or_leftover_is_an_error(self):
        for shell, message in ((FakeShell(code=0x78, remove=False), '代码 0x78'),
                               (FakeShell(aborted=True, remove=False), '取消'),
                               (FakeShell(remove=False), '仍存在')):
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                winplat.recycle(self.target(), shell)

    def test_flags_allow_undo_and_warn_before_permanent_delete(self):
        self.assertTrue(winplat.RECYCLE_FLAGS & winplat.FOF_ALLOWUNDO)
        self.assertTrue(winplat.RECYCLE_FLAGS & winplat.FOF_WANTNUKEWARNING)

    def test_apply_dispatches_to_recycle_bin_after_backup_check(self):
        target = self.target().parent.parent
        with patch.object(common, 'process_list', return_value=[]), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            folder = backup.create_backup(self.home.parent)
        with patch.object(common, 'process_list', return_value=[]), \
                patch.object(winplat, 'recycle', side_effect=lambda p: shutil.rmtree(p)) as recycle, \
                patch.object(trash, 'finder_trash', side_effect=AssertionError('no Finder on Windows')), \
                contextlib.redirect_stdout(io.StringIO()):
            trash.execute([str(target)], apply=True, backup_dir=folder)
        recycle.assert_called_once_with(target)


@unittest.skipUnless(sys.platform == 'win32', 'native Windows Recycle Bin')
class NativeWindowsRecycleTests(unittest.TestCase):
    def test_disposable_file_and_folder_go_to_recycle_bin(self):
        with tempfile.TemporaryDirectory(prefix='reset-recycle-') as temp:
            base = Path(temp).resolve()
            folder = base / 'claude-fixture-folder'
            (folder / 'nested').mkdir(parents=True)
            (folder / 'nested/a.txt').write_text('a', encoding='utf-8')
            # No extension: the Recycle Bin display name hides known extensions.
            single = base / 'claude-fixture-file'
            single.write_text('b', encoding='utf-8')
            winplat.recycle(single)
            winplat.recycle(folder)
            self.assertFalse(single.exists())
            self.assertFalse(folder.exists())
            # Columns of the Recycle Bin folder: 0 = name, 1 = original location.
            script = ('[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; '
                      '$bin = (New-Object -ComObject Shell.Application).NameSpace(10); '
                      '$bin.Items() | ForEach-Object { $bin.GetDetailsOf($_, 0) + "|" + $bin.GetDetailsOf($_, 1) }')
            listing = subprocess.run([winplat.powershell(), '-NoProfile', '-NonInteractive', '-Command', script],
                                     capture_output=True, text=True, encoding='utf-8', check=True,
                                     timeout=60).stdout.splitlines()
            entries = {tuple(line.rsplit('|', 1)) for line in listing if '|' in line}
            for name in (single.name, folder.name):
                with self.subTest(name=name):
                    locations = [Path(where) for shown, where in entries if shown == name]
                    self.assertTrue(locations, f'{name} must be in the Recycle Bin, not deleted: {sorted(entries)}')
                    self.assertTrue(any(where.samefile(base) for where in locations if where.exists()),
                                    f'original location must be {base}: {locations}')


class WindowsEnvironmentTests(WindowsFixture):
    def setUp(self):
        super().setUp()
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        for name in ('powershell.exe', 'git.exe', 'node.exe', 'npm.cmd'):
            self.file(self.bin / name, 'MUST-NOT-EXECUTE')
        self.registered = []
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {'PATHEXT': '.COM;.EXE;.BAT;.CMD'}))
        stack.enter_context(patch.object(common, 'process_list', return_value=[]))
        stack.enter_context(patch.object(winplat, 'uninstall_names', side_effect=lambda: self.registered))
        stack.enter_context(patch.object(common, 'run', side_effect=AssertionError('must not execute commands')))

    def collect(self):
        return env.collect(self.home, str(self.bin))

    def test_new_machine_not_detected(self):
        report = self.collect()
        self.assertEqual(report['status'], 'not_detected')
        self.assertEqual(report['missing_base_tools'], [])
        self.assertEqual(report['registered_apps'], [])

    def test_pathext_finds_cmd_and_ignores_extensionless_file(self):
        self.file(self.bin / 'claude', 'not runnable on Windows')
        self.assertEqual(env.command_paths('claude', str(self.bin), WIN), [])
        # File-name case folding is the file system's job; use the PATHEXT spelling.
        shim = self.file(self.bin / 'claude.cmd')
        found = env.command_paths('claude', str(self.bin), WIN)
        self.assertEqual([(Path(item['path']).name, item['usable_path']) for item in found], [('claude.cmd', True)])
        self.assertTrue(Path(found[0]['path']).samefile(shim))

    def test_native_cli_outside_path_is_installed_with_path_guidance(self):
        self.file(self.home / '.local/bin/claude.exe')
        report = self.collect()
        self.assertEqual(report['status'], 'installed')
        self.assertFalse(report['cli_candidates'][0]['on_path'])
        self.assertTrue(any('PATH' in step for step in report['next_steps']))

    def test_msix_and_legacy_desktop_are_installation_candidates(self):
        self.msix()
        self.assertEqual(self.collect()['status'], 'installed')
        self.file(self.local / 'AnthropicClaude/claude.exe')
        self.assertEqual(len(self.collect()['desktop_paths']), 2)

    def test_two_msix_packages_require_review(self):
        self.msix('Claude_one'); self.msix('Claude_two')
        report = self.collect()
        self.assertEqual(report['status'], 'needs_review')
        self.assertTrue(any('MSIX' in issue['reason'] for issue in report['issues']))

    def test_registration_without_install_path_requires_review(self):
        self.registered = ['Claude']
        report = self.collect()
        self.assertEqual(report['status'], 'needs_review')
        self.assertEqual(report['registered_apps'], ['Claude'])

    def test_local_data_only(self):
        self.file(self.roaming / 'Claude/config.json')
        self.assertEqual(self.collect()['status'], 'local_data_only')

    def test_missing_powershell_is_a_base_tool_gap(self):
        (self.bin / 'powershell.exe').unlink()
        self.assertEqual(self.collect()['missing_base_tools'], ['powershell'])

    def test_missing_pathext_and_registry_errors_propagate(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.update(APPDATA=str(self.roaming), LOCALAPPDATA=str(self.local))
            with self.assertRaisesRegex(RuntimeError, 'PATHEXT'):
                self.collect()
        with patch.object(winplat, 'uninstall_names', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.collect()


class UninstallRegistry(FakeRegistry):
    """Hive -> {subkey name -> values}; the WOW6432Node view is absent."""
    HKEY_LOCAL_MACHINE = 'HKLM'

    def __init__(self, hives):
        super().__init__()
        self.hives = hives

    def OpenKey(self, root, path):
        key = FakeKey()
        if isinstance(root, FakeKey):
            key.values = root.subkeys[path]
        elif 'WOW6432Node' in path:
            raise FileNotFoundError(2, 'no 32-bit view')
        else:
            key.subkeys = self.hives[root]
        return key

    def QueryInfoKey(self, key):
        return (len(key.subkeys), 0, 0)

    def EnumKey(self, key, index):
        return sorted(key.subkeys)[index]

    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(2, 'missing')
        return key.values[name], 1


class WindowsUninstallRegistryTests(unittest.TestCase):
    def test_reads_matching_display_names_and_skips_missing_values(self):
        registry = UninstallRegistry({
            'HKCU': {'a': {'DisplayName': 'Claude'}, 'b': {}},
            'HKLM': {'c': {'DisplayName': 'Anthropic Claude Code'}, 'd': {'DisplayName': 'Git'},
                     'e': {'DisplayName': 'Claude'}},
        })
        with patch.object(winplat, '_winreg', return_value=registry):
            self.assertEqual(winplat.uninstall_names(), ['Claude', 'Anthropic Claude Code'])

    def test_unreadable_entry_propagates(self):
        registry = UninstallRegistry({'HKCU': {'a': {}}, 'HKLM': {}})
        registry.QueryValueEx = lambda key, name: (_ for _ in ()).throw(PermissionError('denied'))
        with patch.object(winplat, '_winreg', return_value=registry):
            with self.assertRaises(PermissionError):
                winplat.uninstall_names()


@unittest.skipUnless(sys.platform == 'win32', 'native Windows detection')
class NativeWindowsEnvironmentTests(unittest.TestCase):
    def test_real_detection_completes(self):
        report = env.collect()
        self.assertIn(report['status'], env.LABELS)
        self.assertIsInstance(report['registered_apps'], list)
        self.assertEqual(report['platform'], 'win32')


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
