import argparse
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from test_workflows import Fixture, backup, common, platforms
from test_windows import WindowsFixture
import preflight


def options(**values):
    defaults = dict(dest=None, include=[], browsers_only=False, leveldb=False, json=False)
    defaults.update(values)
    return argparse.Namespace(**defaults)


class PreflightTests(Fixture):
    def setUp(self):
        super().setUp()
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        for name in platforms.MACOS.tools:
            path = self.bin / name
            path.write_text('#!/bin/sh\nexit 99\n')
            path.chmod(0o700)
        context = patch.dict(os.environ, {'PATH': str(self.bin)})
        context.start()
        self.addCleanup(context.stop)
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
        self.file('.claude/history.jsonl', 'x' * 1000)

    def states(self, **values):
        return {item['check']: item['state'] for item in preflight.collect(options(**values), self.home)}

    def run_main(self, *argv):
        with patch.object(sys, 'argv', ['preflight', *argv]), contextlib.redirect_stdout(io.StringIO()) as out:
            code = common.cli(preflight.main)
        return code, out.getvalue()

    def test_all_met_is_ready_and_read_only(self):
        before = backup.inventory(self.home)
        with patch.object(common, 'run', side_effect=AssertionError('must not run commands')):
            code, text = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn('可以开始', text)
        self.assertEqual(backup.inventory(self.home), before)

    def test_every_unmet_item_is_reported_independently(self):
        (self.bin / 'ditto').unlink()
        with patch.object(common, 'process_list', return_value=['/Applications/Safari.app/Contents/MacOS/Safari']), \
                patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': '/private/secret-dir'}):
            code, text = self.run_main('--json')
        data = json.loads(text)
        blocked = {item['check'] for item in data['checks'] if item['state'] == 'blocked'}
        self.assertEqual(blocked, {'tools', 'apps', 'config_dir'})
        self.assertEqual((code, data['ready']), (1, False))
        self.assertIn('Safari×1', text)
        self.assertNotIn('secret-dir', text)

    def test_failing_check_is_an_error_but_others_still_run(self):
        with patch.object(common, 'process_list', side_effect=RuntimeError('ps failed')):
            code, text = self.run_main('--json')
        data = json.loads(text)
        states = {item['check']: item['state'] for item in data['checks']}
        self.assertEqual(code, 2)
        self.assertEqual(states['apps'], 'error')
        self.assertEqual(states['backup_parent'], 'ok')
        self.assertEqual(len(states), len(preflight.CHECKS))

    def test_privacy_denial_points_to_full_disk_access(self):
        (self.home / '.Trash').mkdir()
        denied = PermissionError(errno.EPERM, 'Operation not permitted')
        real = os.scandir
        def scandir(path):
            if Path(path).name == '.Trash':
                raise denied
            return real(path)
        with patch.object(preflight.os, 'scandir', side_effect=scandir):
            result = {item['check']: item for item in preflight.collect(options(), self.home)}
        self.assertEqual(result['privacy']['state'], 'blocked')
        self.assertIn('完全磁盘访问权限', result['privacy']['next_step'])

    def test_backup_parent_rules(self):
        self.assertEqual(self.states(dest=str(self.home / 'missing'))['backup_parent'], 'blocked')
        self.assertEqual(self.states(dest=str(self.home / '.claude'))['backup_parent'], 'blocked')
        usage = type(preflight.shutil.disk_usage(self.home))(total=1000, used=900, free=100)
        with patch.object(preflight.shutil, 'disk_usage', return_value=usage):
            self.assertEqual(self.states()['backup_parent'], 'blocked')

    def test_macos_backup_links_are_counted_not_followed(self):
        target = self.home / 'elsewhere'
        target.mkdir()
        (target / 'big').write_text('y' * 10_000)
        (self.home / '.claude/link').symlink_to(target)
        size, links = preflight.tree_size(self.home / '.claude')
        self.assertEqual(links, [self.home / '.claude/link'])
        self.assertLess(size, 10_000)
        self.assertEqual(self.states()['backup_parent'], 'ok')

    def test_browsers_only_ignores_running_claude(self):
        claude = ['/Applications/Claude.app/Contents/MacOS/Claude']
        with patch.object(common, 'process_list', return_value=claude):
            self.assertEqual(self.states()['apps'], 'blocked')
            self.assertEqual(self.states(browsers_only=True)['apps'], 'ok')

    def test_leveldb_requires_node(self):
        (self.bin / 'node').unlink()
        result = {i['check']: i for i in preflight.collect(options(leveldb=True), self.home)}
        self.assertEqual(result['tools']['state'], 'blocked')
        self.assertIn('node', result['tools']['detail'])


class WindowsPreflightTests(WindowsFixture):
    def test_links_in_backup_sources_block_on_windows(self):
        self.file(self.home / '.claude/history.jsonl')
        target = self.home / 'elsewhere'
        target.mkdir()
        (self.home / '.claude/link').symlink_to(target)
        with patch.object(common, 'process_list', return_value=[]):
            result = {i['check']: i for i in preflight.collect(options(), self.home)}
        self.assertEqual(result['backup_parent']['state'], 'blocked')
        self.assertIn('Windows 备份不支持', result['backup_parent']['detail'])
        self.assertEqual(result['privacy']['state'], 'ok')
