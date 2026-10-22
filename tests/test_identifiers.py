"""identifiers.py: read-only snapshots, fingerprints only, before/after comparison."""
import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

from test_workflows import Fixture, common
import identifiers as ID

DESKTOP = 'Library/Application Support/Claude'


class IdentifierFixture(Fixture):
    def populate(self, suffix=''):
        v = lambda name: f'RAWSECRET-{name}{suffix}'  # distinctive: must never appear in any output
        self.file('.claude.json', json.dumps({
            'userID': v('user'), 'machineID': v('machine'), 'firstStartTime': v('start'),
            'oauthAccount': {'accountUuid': v('acc'), 'organizationUuid': v('org'), 'emailAddress': v('mail')}}))
        self.file(f'{DESKTOP}/ant-did', v('device'))
        self.file(f'{DESKTOP}/ant-device-registry.json', json.dumps({'uuid': v('token')}))
        self.file(f'{DESKTOP}/ccd-ids.json', json.dumps({'salt': v('salt')}))
        self.file(f'{DESKTOP}/config.json', json.dumps({'lastKnownAccountUuid': v('acc'),
                                                        'first_launch_at': v('launch'),
                                                        'version_first_launch': v('ver')}))
        self.file(f'{DESKTOP}/sentry/scope_v3.json', json.dumps({'scope': {'user': {'id': v('su')}}}))
        self.file(f'{DESKTOP}/sentry/session.json', json.dumps({'did': v('did'), 'sid': v('sid')}))
        self.file(f'{DESKTOP}/Local Storage/leveldb/000001.ldb', v('anonymous_id'))
        self.file(f'{DESKTOP}/Session Storage/000001.log', v('session'))
        self.file(f'{DESKTOP}/IndexedDB/https_claude.ai_0.indexeddb.leveldb/CURRENT', v('manifest'))
        self.file(f'{DESKTOP}/Cookies', v('cookies'))
        self.file(f'{DESKTOP}/vm_bundles/claudevm.bundle/machineIdentifier', v('vm'))

    def run_cli(self, *argv):
        out = io.StringIO()
        with patch.object(sys, 'argv', ['identifiers', *argv]), contextlib.redirect_stdout(out):
            code = ID.main()
        return code, out.getvalue()


class SnapshotTests(IdentifierFixture):
    def test_every_identifier_present_with_fingerprint_and_no_raw_value(self):
        self.populate()
        data = ID.collect()
        by_id = {i['id']: i for i in data['items']}
        expected = {i[0] for i in ID.CODE_ITEMS} | {i[0] for i in ID.DESKTOP_ITEMS} | {'code.keychain'}
        self.assertEqual(set(by_id), expected)
        for item_id, item in by_id.items():
            if item_id in ('code.credentials_file', 'code.keychain'):
                continue
            self.assertTrue(item['present'], item_id)
            self.assertRegex(item['fingerprint'], r'^[0-9a-f]{12}$')
        self.assertFalse(by_id['code.credentials_file']['present'])
        self.assertFalse(by_id['code.keychain']['present'])  # run_status -> 44 in the fixture
        self.assertNotIn('RAWSECRET', json.dumps(data, ensure_ascii=False))
        code, table = self.run_cli()
        self.assertNotIn('RAWSECRET', table)

    def test_empty_home_is_all_absent_and_exit_zero(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertNotIn('存在 ', out.replace('不存在', ''))
        self.assertIn('不存在', out)

    def test_keychain_presence_only(self):
        self.keychain.return_value = 0
        by_id = {i['id']: i for i in ID.collect()['items']}
        self.assertTrue(by_id['code.keychain']['present'])
        self.assertIsNone(by_id['code.keychain']['fingerprint'])

    def test_json_key_missing_is_absent_not_error(self):
        self.file('.claude.json', json.dumps({'numStartups': 3}))
        by_id = {i['id']: i for i in ID.collect()['items']}
        self.assertFalse(by_id['code.user_id']['present'])
        self.assertIn('键不存在', by_id['code.user_id']['note'])

    def test_corrupt_json_is_error_and_exit_two(self):
        self.file('.claude.json', '{not json')
        code, out = self.run_cli('--json')
        self.assertEqual(code, 2)
        item = next(i for i in json.loads(out)['items'] if i['id'] == 'code.user_id')
        self.assertEqual(item['status'], 'error')
        self.assertIn('JSONDecodeError', item['error'])

    def test_symlinked_identifier_is_error(self):
        self.populate()
        target = self.home / DESKTOP / 'ant-did'
        link = self.home / DESKTOP / 'ant-device-registry.json'
        link.unlink()
        link.symlink_to(target)
        by_id = {i['id']: i for i in ID.collect()['items']}
        self.assertEqual(by_id['desktop.device_registry']['status'], 'error')

    def test_snapshot_writes_only_the_target_and_refuses_overwrite(self):
        self.populate()
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        target = self.root / 'before.json'
        code, out = self.run_cli('--snapshot', str(target))
        self.assertEqual(code, 0)
        after = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        self.assertEqual(set(after) - set(before), {'before.json'})
        self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['schema_version'], ID.SCHEMA)
        with self.assertRaises(FileExistsError):
            ID.write_snapshot(target, ID.collect())
        with self.assertRaises(ValueError):
            ID.write_snapshot('relative.json', ID.collect())

    def test_directory_fingerprint_is_order_independent_but_content_sensitive(self):
        self.populate()
        root = self.home / DESKTOP / 'Local Storage/leveldb'
        first = ID.dir_fingerprint(root)
        self.file(f'{DESKTOP}/Local Storage/leveldb/000002.ldb', 'more')
        second = ID.dir_fingerprint(root)
        self.assertNotEqual(first, second)
        self.assertEqual(second, ID.dir_fingerprint(root))


class CompareTests(IdentifierFixture):
    def test_full_reset_changes_or_removes_everything(self):
        self.populate()
        before = ID.collect()
        for name in ('.claude.json',):
            (self.home / name).unlink()
        import shutil
        shutil.rmtree(self.home / DESKTOP)
        self.populate(suffix='-new')
        (self.home / DESKTOP / 'vm_bundles/claudevm.bundle/machineIdentifier').unlink()
        rows = ID.compare(before, ID.collect())
        statuses = {r['id']: r['status'] for r in rows}
        self.assertEqual(statuses['code.user_id'], 'changed')
        self.assertEqual(statuses['desktop.device_id'], 'changed')
        self.assertEqual(statuses['desktop.vm_machine_id'], 'removed')
        self.assertEqual(statuses['code.credentials_file'], 'absent')
        self.assertEqual(statuses['code.keychain'], 'absent')
        self.assertEqual(ID.compare_exit(rows), 0)

    def test_one_unchanged_identifier_fails_and_is_named(self):
        self.populate()
        before = ID.collect()
        self.populate(suffix='-new')
        self.file(f'{DESKTOP}/ant-did', 'RAWSECRET-device')  # device id survived the "reset"
        rows = ID.compare(before, ID.collect())
        unchanged = [r['id'] for r in rows if r['status'] == 'unchanged']
        self.assertEqual(unchanged, ['desktop.device_id'])
        self.assertEqual(ID.compare_exit(rows), 1)

    def test_compare_cli_against_file_and_against_current(self):
        self.populate()
        snap = self.root / 'before.json'
        self.run_cli('--snapshot', str(snap))
        code, out = self.run_cli('--compare', str(snap))
        self.assertEqual(code, 1)
        self.assertIn('❌ 未变', out)
        self.populate(suffix='-2')
        after = self.root / 'after.json'
        self.run_cli('--snapshot', str(after))
        code, out = self.run_cli('--compare', str(snap), '--after', str(after), '--json')
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data['exit'], 0)
        self.assertTrue(all(r['status'] in ('changed', 'absent', 'new') for r in data['rows']))

    def test_keychain_presence_never_judged(self):
        self.keychain.return_value = 0
        self.populate()
        before = ID.collect()
        self.populate(suffix='-2')
        rows = ID.compare(before, ID.collect())
        self.assertEqual(next(r['status'] for r in rows if r['id'] == 'code.keychain'), 'present')
        self.assertEqual(ID.compare_exit(rows), 0)

    def test_error_in_either_snapshot_is_exit_two(self):
        self.populate()
        before = ID.collect()
        self.file('.claude.json', '{broken')
        rows = ID.compare(before, ID.collect())
        self.assertEqual(ID.compare_exit(rows), 2)

    def test_wrong_schema_rejected(self):
        snap = self.file('snap.json', json.dumps({'schema_version': 99, 'items': []}))
        with self.assertRaises(ValueError):
            ID.load_snapshot(snap)


if __name__ == '__main__':
    unittest.main()
