import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_workflows import Fixture, ROOT, common, platforms
import handover
import handover_run

OK_LINE = handover_run.OK_LINE


class GeneratorTests(Fixture):
    def setUp(self):
        super().setUp()
        self.out = self.root / 'out'
        self.out.mkdir()

    def test_plan_has_only_confirmed_targets_and_adds_missing_backup_coverage(self):
        history = self.file('.claude/history.jsonl')
        profile = self.file('Library/Application Support/Google/Chrome/Default/History').parent
        plan, plan_path, launch = handover.create([str(history), str(profile)], self.dest, [], self.out, self.home)
        self.assertEqual(plan['targets'], [str(history), str(profile)])
        self.assertEqual(plan['includes'], [str(profile)])  # history is covered by ~/.claude
        self.assertEqual(json.loads(plan_path.read_text(encoding='utf-8')), plan)
        self.assertTrue(os.access(launch, os.X_OK))
        self.assertEqual(launch.suffix, '.command')

    def test_unsafe_or_overlapping_targets_are_refused_before_writing(self):
        history = self.file('.claude/history.jsonl')
        for targets in ([str(self.home)], [str(history), str(history.parent)], ['relative/path'], []):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                handover.create(targets, self.dest, [], self.out, self.home)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_existing_files_are_never_overwritten(self):
        history = self.file('.claude/history.jsonl')
        class Fixed:
            @staticmethod
            def now():
                from datetime import datetime
                return datetime(2026, 1, 2, 3, 4, 5)
        with patch.object(handover, 'datetime', Fixed):
            handover.create([str(history)], self.dest, [], self.out, self.home)
            with self.assertRaises(FileExistsError):
                handover.create([str(history)], self.dest, [], self.out, self.home)

    @unittest.skipIf(sys.platform == 'win32', 'bash syntax check of the macOS launcher')
    def test_macos_launcher_quotes_awkward_paths(self):
        tricky = self.root / "skill dir 'quoted' $HOME 中文"
        with patch.object(handover, 'ROOT', tricky):
            text = handover.launcher(platforms.MACOS, self.out / "plan 'x' 中文.json")
        script = self.root / 'launcher.command'
        script.write_text(text, encoding='utf-8')
        subprocess.run(['bash', '-n', str(script)], check=True)
        self.assertIn(handover.shlex.quote(str(tricky)), text)
        self.assertIn('read -r -p', text)

    def test_windows_launcher_refuses_percent_and_quotes(self):
        for bad in (r'C:\a%PATH%b', 'C:\\a"b'):
            with self.subTest(path=bad), patch.object(handover, 'ROOT', Path(bad)):
                with self.assertRaisesRegex(ValueError, '%'):
                    handover.launcher(platforms.WINDOWS, Path('C:/x/plan.json'))
        with patch.object(handover, 'ROOT', Path('C:/skills/claude-client-full-reset')):
            text = handover.launcher(platforms.WINDOWS, Path('C:/Users/u/Desktop/Claude清理交接.json'))
        self.assertTrue(text.startswith('@echo off\r\nchcp 65001'))
        self.assertIn('pause', text)


class FakeScripts:
    """Stands in for the entry scripts; records the order of calls."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, args, **kwargs):
        script, rest = Path(args[1]).name, args[2:]
        self.calls.append((script, rest))
        out, code = '', 0
        if script == 'backup.py' and '--verify' not in rest:
            out = OK_LINE + '/backups/Claude-Reset-Backup-x\n'
        if self.fail == (script, rest[:1]):
            code = 2
        return subprocess.CompletedProcess(args, code, out, '[ERROR] RuntimeError: boom\n' if code else '')


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.plan = {'version': 1, 'platform': 'darwin', 'skill_root': '/skill',
                     'targets': ['/Users/u/.claude/history.jsonl'], 'dest': '/Users/u', 'includes': []}
        context = patch.object(platforms, 'current', return_value=platforms.MACOS)
        context.start()
        self.addCleanup(context.stop)

    def run_plan(self, fake, reply='是'):
        log = io.StringIO()
        runner = handover_run.Runner(self.plan, log)
        def answer(prompt):
            if isinstance(reply, BaseException):
                raise reply
            return reply
        with patch.object(handover_run.subprocess, 'run', side_effect=fake), contextlib.redirect_stdout(io.StringIO()):
            try:
                code = runner.run(answer)
            except handover_run.Stop:
                code = 2
        return code, [call[0] + (' ' + call[1][0] if call[1] else '') for call in fake.calls], log.getvalue()

    def test_confirmed_run_goes_through_every_step_in_order(self):
        fake = FakeScripts()
        code, calls, log = self.run_plan(fake)
        self.assertEqual(code, 0)
        self.assertEqual(calls, ['preflight.py --dest', 'backup.py --dest', 'backup.py --verify',
                                 'trash_paths.py --dry-run', 'trash_paths.py --apply', 'scan_readonly.py --no-browser'])
        apply_args = next(rest for script, rest in fake.calls if script == 'trash_paths.py' and rest[0] == '--apply')
        self.assertEqual(apply_args, ['--apply', '--backup', '/backups/Claude-Reset-Backup-x',
                                      '/Users/u/.claude/history.jsonl'])
        self.assertIn('[完成]', log)
        self.assertIn('--restore "/backups/Claude-Reset-Backup-x"', log)

    def test_anything_but_the_exact_word_cancels_without_moving(self):
        for reply in ('', 'yes', '是的', EOFError()):
            with self.subTest(reply=reply):
                fake = FakeScripts()
                code, calls, log = self.run_plan(fake, reply)
                self.assertEqual(code, 3)
                self.assertNotIn('trash_paths.py --apply', calls)
                self.assertIn('[已取消]', log)

    def test_failed_step_stops_everything_after_it(self):
        for failing, last in ((('preflight.py', ['--dest']), 'preflight.py --dest'),
                              (('backup.py', ['--verify']), 'backup.py --verify'),
                              (('trash_paths.py', ['--dry-run']), 'trash_paths.py --dry-run')):
            with self.subTest(step=failing):
                fake = FakeScripts(fail=(failing[0], failing[1]))
                code, calls, log = self.run_plan(fake)
                self.assertEqual(code, 2)
                self.assertEqual(calls[-1], last)
                self.assertNotIn('trash_paths.py --apply', calls)
                self.assertIn('[ERROR] RuntimeError: boom', log)

    def test_plan_validation(self):
        path = Path(self.temp.name) / 'plan.json'
        for broken in ({**self.plan, 'targets': []}, {**self.plan, 'platform': 'win32'},
                       {**self.plan, 'extra': 1}, {**self.plan, 'version': 2}):
            path.write_text(json.dumps(broken), encoding='utf-8')
            with self.subTest(plan=broken), self.assertRaises(ValueError):
                handover_run.load_plan(path)


@unittest.skipUnless(sys.platform == 'win32', 'native end-to-end hand-over on Windows')
class NativeWindowsHandoverTests(unittest.TestCase):
    """Runs the generated .cmd for real in an isolated user profile."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reset-handover-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / '用户 home'
        for folder in ('AppData/Roaming', 'AppData/Local', 'Documents', 'Desktop'):
            (self.home / folder).mkdir(parents=True)
        self.env = dict(os.environ, USERPROFILE=str(self.home), HOME=str(self.home),
                        APPDATA=str(self.home / 'AppData/Roaming'), LOCALAPPDATA=str(self.home / 'AppData/Local'))
        self.target = self.home / '.claude/history.jsonl'
        self.target.parent.mkdir()
        self.target.write_text('历史', encoding='utf-8')
        (self.home / '.claude/settings.json').write_text('keep', encoding='utf-8')

    def generate(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/handover.py'), '--target', str(self.target),
                                 '--out-dir', str(self.home / 'Desktop')],
                                capture_output=True, text=True, encoding='utf-8', env=self.env, check=True)
        launch = next(Path(line.split(': ', 1)[1]) for line in result.stdout.splitlines() if '双击运行' in line)
        return launch

    def run_launcher(self, launch, reply):
        result = subprocess.run(['cmd', '/c', str(launch)], input=reply + '\r\n\r\n', capture_output=True,
                                text=True, encoding='utf-8', env=self.env, timeout=300)
        log = launch.with_suffix('.log').read_text(encoding='utf-8')
        return result.returncode, log

    def test_confirmed_hand_over_backs_up_and_recycles_only_the_target(self):
        code, log = self.run_launcher(self.generate(), '是')
        self.assertIn('[完成]', log, log)
        self.assertFalse(self.target.exists())
        self.assertTrue((self.home / '.claude/settings.json').exists())
        self.assertIn('退出码 0', log)

    def test_cancelled_hand_over_moves_nothing(self):
        code, log = self.run_launcher(self.generate(), 'no')
        self.assertIn('[已取消]', log, log)
        self.assertTrue(self.target.exists())
        self.assertIn('退出码 3', log)
