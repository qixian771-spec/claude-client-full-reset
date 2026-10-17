import contextlib
import errno
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

from test_workflows import common, platforms
import hints

SECRET_ARG = '--token=SECRET-ARG'


class RunningAppTests(unittest.TestCase):
    def test_macos_lists_apps_and_how_to_quit_without_arguments(self):
        procs = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome ' + SECRET_ARG,
                 '/Applications/Google Chrome.app/Contents/Frameworks/x/Google Chrome Helper (GPU).app/Contents/MacOS/Google Chrome Helper (GPU)',
                 '/Applications/Claude.app/Contents/MacOS/Claude',
                 '/Users/u/.local/bin/claude ' + SECRET_ARG]
        with patch.object(platforms, 'current', return_value=platforms.MACOS), \
                patch.object(common, 'process_list', return_value=procs):
            with self.assertRaises(RuntimeError) as caught:
                common.require_stopped()
        text = str(caught.exception)
        self.assertIn('相关应用仍在运行（4 个进程：Claude×1、Claude Code（命令行会话）×1、Google Chrome×2）', text)
        self.assertIn('⌘Q', text)
        self.assertIn('/exit', text)
        self.assertNotIn('SECRET', text)

    def test_windows_tray_and_background_edge_steps(self):
        procs = [('msedge.exe', r'C:\x\msedge.exe', SECRET_ARG)] * 9 + [('Claude.exe', '', '')]
        message = hints.running_apps_message(platforms.WINDOWS, procs)
        self.assertIn('Claude×1、Microsoft Edge×9', message)
        self.assertIn('托盘', message)
        self.assertIn('启动增强', message)
        self.assertNotIn('⌘Q', message)
        self.assertNotIn('SECRET', message)

    def test_edge_hint_only_when_edge_is_running(self):
        message = hints.running_apps_message(platforms.WINDOWS, [('chrome.exe', '', '')])
        self.assertIn('Google Chrome / Chromium×1', message)
        self.assertNotIn('启动增强', message)
        self.assertNotIn('托盘', message)


class NextStepTests(unittest.TestCase):
    def run_cli(self, exc, platform):
        def fail():
            raise exc
        with patch.object(sys, 'platform', platform), contextlib.redirect_stderr(io.StringIO()) as err:
            code = common.cli(fail)
        return code, err.getvalue()

    def test_macos_privacy_denial_points_to_full_disk_access(self):
        code, text = self.run_cli(PermissionError(errno.EPERM, 'Operation not permitted', '/Users/u/.Trash'), 'darwin')
        self.assertEqual(code, 2)
        self.assertIn('[ERROR] PermissionError', text)
        self.assertIn('[下一步] macOS 隐私保护', text)
        self.assertIn('完全磁盘访问权限', text)
        self.assertIn('内置终端', text)

    def test_ordinary_permission_denial_never_suggests_sudo_as_fix(self):
        code, text = self.run_cli(PermissionError(errno.EACCES, 'Permission denied', '/x'), 'darwin')
        self.assertEqual(code, 2)
        self.assertIn('不要用 sudo', text)
        self.assertNotIn('完全磁盘访问权限', text)

    def test_windows_file_in_use_and_controlled_folder_access(self):
        busy = PermissionError(errno.EACCES, 'in use')
        busy.winerror = 32
        self.assertIn('占用', self.run_cli(busy, 'win32')[1])
        denied = PermissionError(errno.EACCES, 'denied')
        denied.winerror = 5
        self.assertIn('受控文件夹访问', self.run_cli(denied, 'win32')[1])

    def test_other_errors_have_no_generic_hint(self):
        code, text = self.run_cli(ValueError('bad input'), 'darwin')
        self.assertEqual(code, 2)
        self.assertNotIn('[下一步]', text)


class InlineNextStepTests(unittest.TestCase):
    def test_missing_variable_explains_where_to_run(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, '正常登录的用户会话'):
            platforms.WINDOWS.resolve('%APPDATA%/Claude')

    def test_recycle_refusals_carry_next_steps(self):
        import winplat
        from test_windows import FakeShell
        target = os.path.abspath(__file__)
        with self.assertRaisesRegex(RuntimeError, '本地固定磁盘后再处理'):
            winplat.recycle(target, FakeShell(drive=2))
        with self.assertRaisesRegex(RuntimeError, '自定义大小'):
            winplat.recycle(target, FakeShell(nuke=True))
        self.assertTrue(os.path.exists(target))


if __name__ == '__main__':
    unittest.main()
