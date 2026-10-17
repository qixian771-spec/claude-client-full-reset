import contextlib
import io
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

from test_workflows import Fixture, REAL_CURRENT, backup, common, platforms


class SelectiveRestoreTests(Fixture):
    def restore(self, folder, paths=None, dry_run=False):
        with patch.object(common, 'run', side_effect=self.copy_command), contextlib.redirect_stdout(io.StringIO()):
            backup.restore(folder, paths, dry_run)

    def test_partial_restore_keeps_shell_and_settings(self):
        target = self.file('.claude.json', 'original')
        shell = self.file('.zshrc', 'keep shell')
        settings = self.file('.claude/settings.json', 'keep settings')
        folder = self.backup()
        target.unlink()
        self.restore(folder, [str(target)])
        self.assertEqual(target.read_text(), 'original')
        self.assertEqual(shell.read_text(), 'keep shell')
        self.assertEqual(settings.read_text(), 'keep settings')

    def test_nested_file_restore_does_not_require_parent_absent(self):
        target = self.file('.claude/history.jsonl', 'history')
        settings = self.file('.claude/settings.json', 'settings')
        folder = self.backup()
        target.unlink()
        self.restore(folder, [str(target)])
        self.assertEqual(target.read_text(), 'history')
        self.assertEqual(settings.read_text(), 'settings')

    def test_directory_restore_preserves_internal_links_and_empty_dirs(self):
        target = self.home / '.claude/projects'
        self.file('.claude/projects/chat/file', 'history')
        (target / 'empty').mkdir()
        (target / 'link').symlink_to('chat/file')
        sibling = self.file('.claude/settings.json', 'keep')
        folder = self.backup()
        expected = backup.inventory(target)
        shutil.rmtree(target)
        self.restore(folder, [str(target)])
        self.assertEqual(backup.inventory(target), expected)
        self.assertEqual(sibling.read_text(), 'keep')

    def test_dry_run_creates_no_files_or_parents(self):
        target = self.file('.claude/projects/chat/file', 'history')
        folder = self.backup()
        shutil.rmtree(self.home / '.claude')
        before = backup.inventory(self.home)
        with patch.object(common, 'run') as copy, contextlib.redirect_stdout(io.StringIO()):
            backup.restore(folder, [str(target)], dry_run=True)
        copy.assert_not_called()
        self.assertEqual(backup.inventory(self.home), before)

    def test_unknown_or_empty_selection_never_becomes_full_restore(self):
        target = self.file('.claude.json')
        folder = self.backup()
        target.unlink()
        for paths in ([], [str(self.home / 'missing')], [str(self.home / '.claude.json/child')]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.restore(folder, paths)
            self.assertFalse(target.exists())

    def test_all_targets_preflight_before_any_copy(self):
        one = self.file('.claude.json')
        existing = self.file('.zshrc', 'keep')
        folder = self.backup()
        one.unlink()
        with self.assertRaises(ValueError):
            self.restore(folder, [str(one), str(existing)])
        self.assertFalse(one.exists())
        self.assertEqual(existing.read_text(), 'keep')
        with self.assertRaises(ValueError):
            self.restore(folder, [str(one), str(self.home / 'unknown')])
        self.assertFalse(one.exists())

    def test_existing_directory_not_merged(self):
        self.file('.claude/projects/data')
        folder = self.backup()
        before = backup.inventory(self.home)
        with self.assertRaises(ValueError):
            self.restore(folder, [str(self.home / '.claude/projects')])
        self.assertEqual(backup.inventory(self.home), before)

    def test_duplicate_overlap_and_traversal_refused(self):
        target = self.file('.claude/projects/data')
        folder = self.backup()
        shutil.rmtree(self.home / '.claude')
        for paths in ([str(target), str(target)],
                      [str(self.home / '.claude'), str(target)],
                      [str(self.home / '.claude/../.claude/projects/data')],
                      ['relative'], [str(self.home)]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.restore(folder, paths)
        self.assertFalse((self.home / '.claude').exists())

    def test_symlink_target_and_parent_refused(self):
        self.file('.claude/data')
        link = self.home / '.claude/link'
        link.symlink_to('data')
        folder = self.backup()
        link.unlink()
        with self.assertRaises(ValueError):
            self.restore(folder, [str(link)])
        shutil.rmtree(self.home / '.claude')
        (self.home / '.claude').symlink_to(self.dest, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.restore(folder, [str(self.home / '.claude/data')])
        self.assertFalse((self.dest / 'data').exists())

    def test_unselected_corrupt_backup_still_blocks(self):
        target = self.file('.claude.json')
        self.file('.zshrc')
        folder = self.backup()
        target.unlink()
        (folder / 'payload/shell/.zshrc').write_text('corrupt')
        with self.assertRaises(ValueError):
            self.restore(folder, [str(target)])
        self.assertFalse(target.exists())

    def test_copy_failure_stops_following_targets_and_keeps_partial(self):
        one, two = self.file('.claude.json'), self.file('.zshrc')
        folder = self.backup()
        one.unlink(); two.unlink()
        with patch.object(common, 'run', side_effect=RuntimeError('copy refused')) as copy:
            with self.assertRaises(RuntimeError):
                backup.restore(folder, [str(one), str(two)])
        self.assertEqual(copy.call_count, 1)
        self.assertTrue(one.exists())  # Reserved partial target, no cleanup or retry.
        self.assertFalse(two.exists())

    def test_bad_copy_verification_stops_following_targets(self):
        one, two = self.file('.claude.json'), self.file('.zshrc')
        folder = self.backup()
        one.unlink(); two.unlink()
        with patch.object(common, 'run', side_effect=lambda args: Path(args[2]).write_text('wrong')) as copy:
            with self.assertRaises(RuntimeError):
                backup.restore(folder, [str(one), str(two)])
        self.assertEqual(copy.call_count, 1)
        self.assertFalse(two.exists())

    def test_later_target_appears_after_preflight_not_overwritten(self):
        one, two = self.file('.claude.json'), self.file('.zshrc')
        folder = self.backup()
        one.unlink(); two.unlink()
        def copy_first(args):
            self.copy_command(args)
            two.write_text('new data')
        with patch.object(common, 'run', side_effect=copy_first) as copy, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                backup.restore(folder, [str(one), str(two)])
        self.assertEqual(copy.call_count, 1)
        self.assertEqual(two.read_text(), 'new data')

    def test_exclusive_destination_reservation_refuses_racing_file(self):
        target = self.file('.claude.json')
        folder = self.backup()
        target.unlink()
        original_open = os.open
        def appear(path, flags, mode):
            Path(path).write_text('appeared')
            return original_open(path, flags, mode)
        with patch.object(backup.os, 'open', side_effect=appear), patch.object(common, 'run') as copy:
            with self.assertRaises(FileExistsError):
                backup.restore(folder, [str(target)])
        copy.assert_not_called()
        self.assertEqual(target.read_text(), 'appeared')

    def test_source_changes_after_preflight_stops(self):
        target = self.file('.claude.json')
        folder = self.backup()
        target.unlink()
        calls = 0
        def stopped():
            nonlocal calls
            calls += 1
            if calls == 2:
                (folder / 'payload/dot-claude.json').write_text('changed')
        with patch.object(common, 'require_stopped', side_effect=stopped):
            with self.assertRaises(ValueError):
                self.restore(folder, [str(target)])
        self.assertFalse(target.exists())

    def test_active_claude_blocks_restore_without_writes(self):
        target = self.file('.claude.json')
        folder = self.backup()
        target.unlink()
        with patch.object(common, 'process_list', return_value=['/opt/bin/claude --resume']):
            with self.assertRaises(RuntimeError):
                self.restore(folder, [str(target)])
        self.assertFalse(target.exists())

    def test_cli_selection_preview_apply_and_list(self):
        target = self.file('.claude/history.jsonl', 'original')
        self.file('.zshrc', 'unchanged')
        folder = self.backup()
        target.unlink()
        args = ['backup', '--restore', str(folder), '--path', str(target)]
        with patch.object(common, 'require_supported', return_value=platforms.MACOS), contextlib.redirect_stdout(io.StringIO()):
            with patch.object(sys, 'argv', [*args, '--dry-run']):
                self.assertEqual(backup.main(), 0)
            self.assertFalse(target.exists())
            with patch.object(sys, 'argv', args), patch.object(common, 'run', side_effect=self.copy_command):
                self.assertEqual(backup.main(), 0)
            with patch.object(sys, 'argv', ['backup', '--list', str(folder)]), patch.object(common, 'require_stopped', side_effect=AssertionError('must not query apps')):
                self.assertEqual(backup.main(), 0)
        self.assertEqual(target.read_text(), 'original')

    def test_restore_only_options_cannot_silently_create_backup(self):
        for argv in (['--path', str(self.home / 'data')], ['--dry-run'],
                     ['--verify', str(self.dest), '--path', str(self.home / 'data')],
                     ['--list', str(self.dest), '--dry-run'],
                     ['--restore', str(self.dest), '--include', str(self.home)]):
            with self.subTest(argv=argv), patch.object(common, 'require_supported', return_value=platforms.MACOS), patch.object(sys, 'argv', ['backup', *argv]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    backup.main()
                self.assertEqual(exc.exception.code, 2)
        self.assertEqual(list(self.dest.iterdir()), [])

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS native ditto selective restore')
    def test_native_partial_restore_files_and_directories(self):
        target = self.file('.claude/history.jsonl', 'original')
        child = self.file('.claude/projects/chat/data', 'content')
        (child.parent / 'link').symlink_to('data')
        shell = self.file('.zshrc', 'keep')
        with contextlib.redirect_stdout(io.StringIO()):
            folder = backup.create_backup(self.dest)
            target.unlink()
            shutil.rmtree(child.parent)
            backup.restore(folder, [str(target), str(child.parent)])
            backup.verify_backup(folder)
        self.assertEqual(target.read_text(), 'original')
        self.assertEqual(child.read_text(), 'content')
        self.assertTrue((child.parent / 'link').is_symlink())
        self.assertEqual(shell.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
