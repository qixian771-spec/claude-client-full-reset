import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import common
import backup
import browser_scan as BS
import chrome_purge as SQL
import trash_paths as trash
import verify_reset as verify
import scan_readonly as scan


@contextlib.contextmanager
def database(path):
    with contextlib.closing(sqlite3.connect(path)) as db:
        with db:
            yield db


def make_db(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with database(path) as db:
        db.execute('CREATE TABLE records (url TEXT, note TEXT)')
        db.executemany('INSERT INTO records VALUES (?, ?)', rows)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reset-test-')
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.dest = self.root / 'backups'
        self.dest.mkdir()
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(Path, 'home', return_value=self.home))
        self.stack.enter_context(patch.object(common, 'process_list', return_value=[]))
        self.stack.enter_context(patch.object(BS, 'LIB', self.home / 'Library'))
        self.stack.enter_context(patch.object(BS, 'BROWSERS', []))
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.stack.close)

    def file(self, name, text='data'):
        p = self.home / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def copy_command(self, args):
        self.assertEqual(args[0], 'ditto')
        source, target = Path(args[1]), Path(args[2])
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
        return ''

    def backup(self, extra=()):
        with patch.object(common, 'run', side_effect=self.copy_command), contextlib.redirect_stdout(io.StringIO()):
            return backup.create_backup(self.dest, extra)


class ProcessTests(unittest.TestCase):
    def test_detect_paths_and_helpers(self):
        procs = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                 '/x/Google Chrome Helper (Renderer)', '/x/Claude.app/Contents/MacOS/Claude',
                 '/usr/local/bin/claude --resume', 'node /x/@anthropic-ai/claude-code/cli.js', 'Safari', '/usr/bin/grep', '/tmp/claude-note.txt']
        self.assertEqual(len(common.relevant_processes(procs)), 6)
        self.assertEqual(len(common.relevant_processes(procs, True)), 3)

    def test_failed_process_command_propagates(self):
        with patch.object(common, 'run', side_effect=subprocess.CalledProcessError(1, ['ps'])):
            with self.assertRaises(subprocess.CalledProcessError):
                common.require_stopped()

    def test_cli_error_is_nonzero(self):
        def fail():
            raise PermissionError('denied')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(common.cli(fail), 2)


class BackupTests(Fixture):
    def test_copy_verify_detect_tamper(self):
        src = self.file('.claude.json', '{"machineID":"private"}')
        folder = self.backup()
        backup.require_covered(folder, src)
        (folder / 'payload/dot-claude.json').write_text('corrupt')
        with self.assertRaises(ValueError):
            backup.verify_backup(folder)

    def test_changed_source_rejected(self):
        src = self.file('.claude.json')
        folder = self.backup()
        src.write_text('changed')
        with self.assertRaises(ValueError):
            backup.require_covered(folder, src)

    def test_failed_copy_never_gets_success_manifest(self):
        self.file('.claude.json')
        with patch.object(common, 'run', side_effect=subprocess.CalledProcessError(1, ['ditto'])):
            with self.assertRaises(subprocess.CalledProcessError):
                backup.create_backup(self.dest)
        self.assertFalse(list(self.dest.glob('*/manifest.json')))

    def test_duplicate_source_is_backed_up_once(self):
        src = self.file('.claude.json')
        data = backup.verify_backup(self.backup([str(src)]))
        self.assertEqual(len(data['sources']), 1)

    def test_source_change_during_copy_rejected(self):
        src = self.file('.claude.json')
        def change(args):
            self.copy_command(args)
            src.write_text('new data')
        with patch.object(common, 'run', side_effect=change):
            with self.assertRaises(RuntimeError):
                backup.create_backup(self.dest)
        self.assertFalse(list(self.dest.glob('*/manifest.json')))

    def test_copy_corruption_rejected(self):
        self.file('.claude.json')
        def broken(args):
            Path(args[2]).write_text('corruption')
        with patch.object(common, 'run', side_effect=broken):
            with self.assertRaises(RuntimeError):
                backup.create_backup(self.dest)
        self.assertFalse(list(self.dest.glob('*/manifest.json')))

    def test_empty_source_and_nested_dest_rejected(self):
        with self.assertRaises(ValueError):
            backup.create_backup(self.dest)
        self.file('.claude/settings.json', '{}')
        with self.assertRaises(ValueError):
            backup.create_backup(self.home / '.claude')

    def test_backup_preserves_links_and_unique_names(self):
        self.file('.claude/settings.json', '{}')
        (self.home / '.claude/link').symlink_to('settings.json')
        a, b = self.backup(), self.backup()
        self.assertNotEqual(a, b)
        self.assertTrue((a / 'payload/dot-claude/link').is_symlink())
        backup.verify_backup(a)

    def test_restore_refuses_existing_target_then_roundtrip(self):
        src = self.file('.claude.json', 'original')
        folder = self.backup()
        with self.assertRaises(ValueError):
            backup.restore(folder)
        src.unlink()
        with patch.object(common, 'run', side_effect=self.copy_command), contextlib.redirect_stdout(io.StringIO()):
            backup.restore(folder)
        self.assertEqual(src.read_text(), 'original')

    def test_unknown_target_not_covered(self):
        self.file('.claude.json')
        other = self.file('other')
        with self.assertRaises(ValueError):
            backup.require_covered(self.backup(), other)

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS ditto integration')
    def test_real_ditto_on_disposable_data(self):
        self.file('.claude/settings.json', '{"fixture":true}')
        (self.home / '.claude/link').symlink_to('settings.json')
        with contextlib.redirect_stdout(io.StringIO()):
            folder = backup.create_backup(self.dest)
        self.assertEqual((folder / 'payload/dot-claude/settings.json').read_text(), '{"fixture":true}')
        backup.verify_backup(folder)


class TrashTests(Fixture):
    def test_dangerous_variants_rejected(self):
        paths = ['/', '/Applications/', '/Applications//', '/Library/', str(self.home),
                 str(self.home / 'Library'), str(self.home / 'Library/Application Support'),
                 str(self.home / 'Documents'), str(self.home / 'Desktop/..'),
                 '/Users/someone', '/etc/passwd', 'relative/path']
        for p in paths:
            with self.subTest(path=p), self.assertRaises(ValueError):
                trash.validate_path(p, False)

    def test_symlink_and_broken_link_rejected(self):
        self.file('safe/file')
        (self.home / 'link').symlink_to(self.home / 'safe', target_is_directory=True)
        (self.home / 'broken').symlink_to('absent')
        for p in (self.home / 'link/file', self.home / 'broken'):
            with self.assertRaises(ValueError):
                trash.validate_path(str(p))

    def test_whole_batch_preflight_and_missing_backup(self):
        src = self.file('safe/file')
        with patch.object(trash, 'finder_trash') as move:
            for paths, bk in (([str(src)], None), ([str(src), '/'], self.dest)):
                with self.assertRaises(ValueError):
                    trash.execute(paths, True, bk)
            move.assert_not_called()
        self.assertTrue(src.exists())

    def test_preview_no_move_apply_with_backup(self):
        src = self.file('safe/file', 'preserved')
        folder = self.backup([str(src)])
        with patch.object(trash, 'finder_trash') as move, contextlib.redirect_stdout(io.StringIO()):
            trash.execute([str(src)])
            move.assert_not_called()
        target = self.root / 'fake-trash'
        with patch.object(trash, 'finder_trash', side_effect=lambda p: p.rename(target)), contextlib.redirect_stdout(io.StringIO()):
            trash.execute([str(src)], True, folder)
        self.assertEqual(target.read_text(), 'preserved')

    def test_move_failure_stops_following_targets(self):
        one, two = self.file('one'), self.file('two')
        folder = self.backup([str(one), str(two)])
        with patch.object(trash, 'finder_trash', side_effect=RuntimeError('Finder refused')) as move:
            with self.assertRaises(RuntimeError):
                trash.execute([str(one), str(two)], True, folder)
            self.assertEqual(move.call_count, 1)
        self.assertTrue(two.exists())

    def test_quoted_filename_is_argv_not_script(self):
        p = self.file('quote" and \\slash')
        with patch.object(common, 'run', side_effect=lambda args: p.unlink()) as run:
            trash.finder_trash(p)
        args = run.call_args.args[0]
        self.assertEqual(args[-1], str(p))
        self.assertNotIn(str(p), args[2])

    def test_duplicate_empty_and_large_batch_rejected(self):
        src = self.file('safe/file')
        for paths in ([], [str(src)] * 2, [str(src)] * 11):
            with self.assertRaises(ValueError):
                trash.execute(paths)


class ScanTests(Fixture):
    def test_chunk_boundary_not_double_counted(self):
        src = self.file('bytes', 'xxclaude--anthropicxxclaude')
        with patch.object(BS, 'CHUNK', 10):
            self.assertEqual(BS.byte_hits(src), 3)

    def test_read_permission_errors_not_clean(self):
        src = self.file('bytes')
        with patch('builtins.open', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                BS.byte_hits(src)

    def test_walk_permission_error_propagates(self):
        def fail(root, onerror, followlinks):
            onerror(PermissionError('denied'))
            return iter(())
        with patch.object(common.os, 'walk', side_effect=fail):
            with self.assertRaises(PermissionError):
                list(common.walk_files(self.home))

    def test_invalid_json_and_sqlite_fail(self):
        src = self.file('bad.json', '{')
        with self.assertRaises(ValueError):
            BS.json_hits(src)
        db = self.home / 'broken'
        db.write_bytes(b'SQLite format 3\x00' + b'broken')
        with self.assertRaises(RuntimeError):
            BS.sqlite_hits(db)

    def test_recursive_network_and_all_profiles(self):
        root = self.home / 'browser'
        make_db(root / 'Profile 7/Network/Cookies', [('https://claude.ai', 'private')])
        self.file('browser/Default/Preferences', '{}')
        self.file('browser/Local State', '{"key":"anthropic"}')
        result = BS.collect(browsers=[('Fixture', root)])
        self.assertEqual(result['profiles'], 2)
        self.assertEqual(result['files'], 2)
        self.assertTrue(any('Network/Cookies' == row[2] for row in result['chromium']))

    def test_sqlite_wal_snapshot_reads_pending_wal(self):
        path = self.home / 'wal.db'
        db = sqlite3.connect(path)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE records (value TEXT)')
            db.execute("INSERT INTO records VALUES ('https://claude.ai')")
            db.commit()
            before = backup.inventory(self.home)
            self.assertEqual(BS.sqlite_hits(path)[0][2], 1)
            self.assertEqual(backup.inventory(self.home), before)
        finally:
            db.close()

    def test_snapshot_detects_source_change(self):
        path = self.home / 'database'
        make_db(path, [('https://claude.ai', 'data')])
        with self.assertRaises(RuntimeError):
            with common.sqlite_snapshot(path):
                path.write_bytes(b'changed')

    def test_environment_values_redacted(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'DO-NOT-PRINT'}):
            result = verify.shell_findings(self.home)
        self.assertIn('current-env:ANTHROPIC_API_KEY', result)
        self.assertNotIn('DO-NOT-PRINT', str(result))

    def test_json_values_redacted(self):
        path = self.file('preferences', '{"key":"claude-secret-value"}')
        self.assertNotIn('secret-value', str(BS.json_hits(path)))

    def test_assets_retained_but_traces_reported(self):
        self.file('.claude/skills/example/SKILL.md', 'fixture')
        trace = self.file('.claude/history.jsonl', 'fixture')
        self.assertEqual(verify.core_paths(self.home), [str(trace)])

    def test_scan_cli_parse_failure_exit2(self):
        self.file('.claude.json', '{')
        with patch.object(common, 'require_macos'), patch.object(sys, 'argv', ['scan', '--no-browser']), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(common.cli(scan.main), 2)

    def test_verify_check_error_exit2_not_pass(self):
        with patch.object(common, 'require_macos'), patch.object(verify, 'collect', side_effect=PermissionError('denied')), patch.object(sys, 'argv', ['verify']), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(common.cli(verify.main), 2)

    def test_verify_clean_and_matches(self):
        with patch.object(common, 'require_macos'), patch.object(sys, 'argv', ['verify']), contextlib.redirect_stdout(io.StringIO()):
            with patch.object(verify, 'collect', return_value={'test': []}):
                self.assertEqual(verify.main(), 0)
            with patch.object(verify, 'collect', return_value={'test': ['hit']}):
                self.assertEqual(verify.main(), 1)


class SQLiteTests(Fixture):
    def setUp(self):
        super().setUp()
        self.db = self.home / 'db'
        make_db(self.db, [('https://claude.ai/chat', 'claude.ai'), ('https://example.com', 'Claude Monet'),
                          ('https://notclaude.ai', 'unrelated'), ('https://api.anthropic.com/path', 'data')])

    def test_preview_no_bytes_changed_unique_row_count(self):
        before = backup.inventory(self.home)
        count, detail = SQL.purge_db(self.db)
        self.assertEqual(count, 2)
        self.assertEqual(backup.inventory(self.home), before)

    def test_apply_preserves_unrelated_rows(self):
        count, detail = SQL.purge_db(self.db, True)
        self.assertEqual(count, 2)
        with database(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT note FROM records WHERE url='https://example.com'").fetchone()[0], 'Claude Monet')
        self.assertEqual(SQL.purge_db(self.db)[0], 0)

    def test_cookie_domain_and_query_url_match(self):
        with database(self.db) as db:
            db.executemany('INSERT INTO records VALUES (?, ?)', [('.anthropic.com', 'a'), ('https://claude.ai?x=1', 'b')])
        self.assertEqual(SQL.purge_db(self.db)[0], 4)

    def test_quoted_identifiers(self):
        with database(self.db) as db:
            db.execute('CREATE TABLE "odd""table" ("a""b" TEXT)')
            db.execute('INSERT INTO "odd""table" VALUES (?)', ('https://claude.ai',))
        self.assertEqual(SQL.purge_db(self.db, True)[0], 3)

    def test_triggers_rejected_before_any_delete(self):
        with database(self.db) as db:
            db.execute('CREATE TRIGGER trigger_delete AFTER DELETE ON records BEGIN DELETE FROM records; END')
        before = self.db.read_bytes()
        with self.assertRaises(ValueError):
            SQL.purge_db(self.db, True)
        self.assertEqual(self.db.read_bytes(), before)

    def test_foreign_keys_refused(self):
        with database(self.db) as db:
            db.execute('CREATE TABLE dependent (ref TEXT REFERENCES records(url))')
        with self.assertRaises(ValueError):
            SQL.purge_db(self.db, True)

    def test_transaction_rolls_back_on_delete_error(self):
        with database(self.db) as db:
            db.execute('CREATE TABLE second (url TEXT)')
            db.execute('INSERT INTO second VALUES (?)', ('https://claude.ai',))
        real_connect = sqlite3.connect
        class Broken(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith('DELETE FROM "second"'):
                    raise sqlite3.OperationalError('injected failure')
                return super().execute(sql, *args)
        with patch.object(SQL.sqlite3, 'connect', side_effect=lambda *a, **k: real_connect(*a, **k, factory=Broken)):
            with self.assertRaises(sqlite3.OperationalError):
                SQL.purge_db(self.db, True)
        with database(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0], 4)

    def test_vacuum_failure_not_reported_success(self):
        real_connect = sqlite3.connect
        class Broken(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql == 'VACUUM':
                    raise sqlite3.OperationalError('injected vacuum failure')
                return super().execute(sql, *args)
        with patch.object(SQL.sqlite3, 'connect', side_effect=lambda *a, **k: real_connect(*a, **k, factory=Broken)):
            with self.assertRaises(sqlite3.OperationalError):
                SQL.purge_db(self.db, True)

    def test_corrupt_db_and_missing_db_fail(self):
        with self.assertRaises(FileNotFoundError):
            SQL.purge_db(self.home / 'absent')
        self.db.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            SQL.purge_db(self.db)

    def test_cli_invalid_profile_and_missing_backup_fail(self):
        with patch.object(common, 'require_macos'), patch.object(sys, 'argv', ['sql', '--profile', 'missing']):
            with self.assertRaises(ValueError):
                SQL.main()
        with patch.object(common, 'require_macos'), patch.object(sys, 'argv', ['sql', '--apply']), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                SQL.main()
            self.assertEqual(ctx.exception.code, 2)

    def test_end_to_end_backup_sql_and_reinspect(self):
        profile = self.home / 'browser/Default'
        profile.mkdir(parents=True)
        self.db.rename(profile / 'History')
        folder = self.backup([str(profile)])
        with patch.object(BS, 'BROWSERS', [('Fixture', profile.parent)]), patch.object(common, 'require_macos'), patch.object(sys, 'argv', ['sql', '--apply', '--backup', str(folder)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(SQL.main(), 0)
        self.assertEqual(SQL.purge_db(profile / 'History')[0], 0)
        backup.verify_backup(folder)

class InstallationTests(Fixture):
    def test_install_and_entrypoint_help_without_user_data_access(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import install
        target = self.home / 'installed-skill'
        install.install(target)
        self.assertTrue((target / 'SKILL.md').is_file())
        for doc in target.rglob('*.md'):
            for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', doc.read_text()):
                if '://' not in link and not link.startswith('#'):
                    self.assertTrue((doc.parent / link.split('#')[0]).is_file(), (doc, link))
        self.assertFalse((target / 'scripts/__pycache__').exists())
        for name in ('backup.sh', 'scan_readonly.sh', 'trash_paths.sh'):
            result = subprocess.run(['bash', str(target / 'scripts' / name), '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('browser_scan.py', 'chrome_purge.py', 'verify_reset.py', 'check_environment.py'):
            result = subprocess.run([sys.executable, str(target / 'scripts' / name), '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaises(FileExistsError):
            install.install(target)

    def test_installer_refuses_symlink_parent(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import install
        (self.home / 'link').symlink_to(self.dest, target_is_directory=True)
        with self.assertRaises(ValueError):
            install.install(self.home / 'link/skill')


if __name__ == '__main__':
    unittest.main()
