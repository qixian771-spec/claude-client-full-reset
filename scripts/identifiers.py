#!/usr/bin/env python3
"""Snapshot and compare the local Claude identifiers (user, machine, device, telemetry IDs).

Read-only: never prints an identifier value, only a SHA-256 fingerprint (first 12 hex
characters) so a before/after pair proves an identifier changed without revealing it.
The only file written is the --snapshot target, and it must not exist yet.

Exit codes
  table / --json / --snapshot : 0 collected; 2 an item could not be read (status "error")
  --compare BEFORE            : 0 every identifier that existed before is now changed or
                                removed; 1 at least one is unchanged; 2 an item errored
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

import common
import platforms

SCHEMA = 1
FINGERPRINT_CHARS = 12

# Desktop client identifiers, relative to each desktop data root in the platform table.
# kind: file = whole file; dir = every regular file below; json = one key path.
DESKTOP_ITEMS = (
    ('desktop.device_id', 'file', 'ant-did', None, '桌面端设备标识（48 字符）'),
    ('desktop.device_registry', 'file', 'ant-device-registry.json', None, '桌面端设备注册表（设备 UUID → 令牌）'),
    ('desktop.ccd_salt', 'json', 'ccd-ids.json', ('salt',), 'Claude Code Desktop 会话 ID 盐'),
    ('desktop.account_uuid', 'json', 'config.json', ('lastKnownAccountUuid',), '桌面端最近登录账号 UUID'),
    ('desktop.first_launch', 'json', 'config.json', ('first_launch_at',), '桌面端首次启动时间'),
    ('desktop.first_version', 'json', 'config.json', ('version_first_launch',), '桌面端首次启动版本'),
    ('desktop.sentry_user', 'json', 'sentry/scope_v3.json', ('scope', 'user', 'id'), 'Sentry 用户 ID'),
    ('desktop.sentry_device', 'json', 'sentry/session.json', ('did',), 'Sentry 设备 ID'),
    ('desktop.sentry_session', 'json', 'sentry/session.json', ('sid',), 'Sentry 会话 ID'),
    ('desktop.local_storage', 'dir', 'Local Storage/leveldb', None, 'Local Storage（含 Segment anonymous_id）'),
    ('desktop.session_storage', 'dir', 'Session Storage', None, 'Session Storage'),
    ('desktop.indexeddb', 'dir', 'IndexedDB/https_claude.ai_0.indexeddb.leveldb', None, 'claude.ai IndexedDB'),
    ('desktop.cookies', 'file', 'Cookies', None, '桌面端 cookie 库'),
    ('desktop.vm_machine_id', 'file', 'vm_bundles/claudevm.bundle/machineIdentifier', None, 'Cowork 虚拟机标识'),
)
DESKTOP_ROOT_NAMES = ('AppSupport-Claude', 'AppData-Claude', 'MSIX-Claude')

CODE_ITEMS = (
    ('code.user_id', 'json', '~/.claude.json', ('userID',), 'Claude Code 用户 ID'),
    ('code.machine_id', 'json', '~/.claude.json', ('machineID',), 'Claude Code 机器 ID'),
    ('code.account_uuid', 'json', '~/.claude.json', ('oauthAccount', 'accountUuid'), 'OAuth 账号 UUID'),
    ('code.org_uuid', 'json', '~/.claude.json', ('oauthAccount', 'organizationUuid'), 'OAuth 组织 UUID'),
    ('code.email', 'json', '~/.claude.json', ('oauthAccount', 'emailAddress'), '登录邮箱'),
    ('code.first_start', 'json', '~/.claude.json', ('firstStartTime',), 'Claude Code 首次启动时间'),
    ('code.credentials_file', 'file', '~/.claude/.credentials.json', None, 'OAuth 凭证文件（Windows/Linux）'),
)


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()[:FINGERPRINT_CHARS]


def dir_fingerprint(root):
    digest = hashlib.sha256()
    for path in sorted(common.walk_files(root)):
        digest.update(str(path.relative_to(root)).encode('utf-8'))
        digest.update(b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:FINGERPRINT_CHARS]


def json_value(path, keys):
    data = json.loads(path.read_bytes().decode('utf-8'))
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def observe(item_id, kind, path, keys, note, source):
    item = {'id': item_id, 'kind': kind, 'path': str(path), 'source': source, 'note': note,
            'present': False, 'fingerprint': None}
    if not common.exists(path):
        return item
    try:
        if common.is_link(path):
            raise RuntimeError('symlink')
        if kind == 'file':
            common.regular(path)
            item['fingerprint'] = fingerprint(path.read_bytes())
        elif kind == 'dir':
            common.directory(path)
            item['fingerprint'] = dir_fingerprint(path)
        else:
            common.regular(path)
            value = json_value(path, keys)
            if value is None:
                item['note'] += '（文件在，键不存在）'
                return item
            item['fingerprint'] = fingerprint(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8'))
        item['present'] = True
    except (OSError, ValueError, RuntimeError) as exc:
        item['present'] = True
        item['status'] = 'error'
        item['error'] = f'{type(exc).__name__}: {exc}'[:120]
    return item


def desktop_roots(platform, home):
    roots = []
    for entry, stored in platform.client_data:
        if stored in DESKTOP_ROOT_NAMES:
            roots.extend((path, stored) for path in platform.expand(entry, home))
    return roots


def collect(home=None):
    platform = platforms.current()
    home = Path.home() if home is None else Path(home)
    items = []
    for item_id, kind, entry, keys, note in CODE_ITEMS:
        items.append(observe(item_id, kind, platform.resolve(entry, home), keys, note, 'claude-code'))
    for root, stored in desktop_roots(platform, home):
        suffix = '' if stored == 'AppSupport-Claude' or stored == 'AppData-Claude' else '@msix'
        for item_id, kind, rel, keys, note in DESKTOP_ITEMS:
            items.append(observe(item_id + suffix, kind, root / rel, keys, note, stored))
    if platform.keychain_service:
        code = common.run_status(['security', 'find-generic-password', '-s', platform.keychain_service])
        items.append({'id': 'code.keychain', 'kind': 'presence', 'path': platform.keychain_service,
                      'source': 'keychain', 'note': '钥匙串登录项（只查存在，不读内容，不参与对比判定）',
                      'present': code == 0, 'fingerprint': None})
    return {'schema_version': SCHEMA, 'platform': platform.key,
            'generated': dt.datetime.now(dt.timezone.utc).isoformat(), 'items': items}


def compare(before, after):
    """Pair items by id; an identifier that existed before must now differ or be gone."""
    before_items = {i['id']: i for i in before['items']}
    after_items = {i['id']: i for i in after['items']}
    rows = []
    for item_id in sorted(set(before_items) | set(after_items)):
        b, a = before_items.get(item_id), after_items.get(item_id)
        if (b and b.get('status') == 'error') or (a and a.get('status') == 'error'):
            status = 'error'
        elif b is None or not b['present']:
            status = 'new' if a and a['present'] else 'absent'
        elif a is None or not a['present']:
            status = 'removed'
        elif b['fingerprint'] is None or a['fingerprint'] is None:
            status = 'present'  # presence-only item (keychain); never judged
        elif b['fingerprint'] == a['fingerprint']:
            status = 'unchanged'
        else:
            status = 'changed'
        rows.append({'id': item_id, 'status': status,
                     'before': b['fingerprint'] if b else None, 'after': a['fingerprint'] if a else None,
                     'note': (a or b)['note']})
    return rows


def compare_exit(rows):
    statuses = {r['status'] for r in rows}
    if 'error' in statuses:
        return 2
    return 1 if 'unchanged' in statuses else 0


def load_snapshot(path):
    data = json.loads(Path(path).read_bytes().decode('utf-8'))
    if data.get('schema_version') != SCHEMA:
        raise ValueError(f'快照 schema 不支持: {data.get("schema_version")}')
    return data


def write_snapshot(path, data):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError(f'--snapshot 需要绝对路径: {path}')
    if common.exists(path):
        raise FileExistsError(f'快照已存在，不覆盖: {path}')
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    with open(path, 'x', encoding='utf-8') as stream:
        stream.write(text)


MARK = {'changed': '✅ 已变', 'removed': '✅ 已移除', 'new': 'ℹ️ 新出现', 'absent': '— 两次都不存在',
        'present': 'ℹ️ 存在（不比对）', 'unchanged': '❌ 未变', 'error': '❓ 读取失败'}


def print_table(data):
    print(f'# Claude 标识快照  平台={data["platform"]}  {data["generated"]}')
    for item in data['items']:
        if item.get('status') == 'error':
            state = '❓ ' + item['error']
        elif item['present']:
            state = '存在 ' + (item['fingerprint'] or '(只查存在)')
        else:
            state = '不存在'
        print(f'{item["id"]:<28} {state:<24} {item["note"]}  [{item["path"]}]')
    print('值只以 SHA-256 前 12 位指纹显示；硬件序列号、MAC、磁盘 UUID、服务端记录不在本清单内，也无法重置。')


def print_compare(rows, code):
    print('# 标识对比（清理前 → 现在）')
    for r in rows:
        print(f'{r["id"]:<28} {MARK[r["status"]]:<16} {r["before"] or "-":<13} → {r["after"] or "-":<13} {r["note"]}')
    verdict = {0: '通过：清理前存在的标识全部已变或已移除', 1: '不通过：有标识未变', 2: '无法判定：有项读取失败'}[code]
    print(f'结论: {verdict}（exit {code}）')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json', action='store_true', help='输出 JSON 而不是表格')
    parser.add_argument('--snapshot', type=Path, help='把当前快照写到这个新文件（绝对路径，已存在则拒绝）')
    parser.add_argument('--compare', type=Path, help='与这份清理前快照对比；默认对比当前状态')
    parser.add_argument('--after', type=Path, help='配合 --compare：用这份快照代替当前状态')
    args = parser.parse_args()
    common.require_supported()
    if args.compare:
        before = load_snapshot(args.compare)
        after = load_snapshot(args.after) if args.after else collect()
        rows = compare(before, after)
        code = compare_exit(rows)
        if args.json:
            print(json.dumps({'before': str(args.compare), 'after': str(args.after) if args.after else 'current',
                              'exit': code, 'rows': rows}, ensure_ascii=False, indent=2))
        else:
            print_compare(rows, code)
        return code
    data = collect()
    code = 2 if any(i.get('status') == 'error' for i in data['items']) else 0
    if args.snapshot:
        write_snapshot(args.snapshot, data)
        print(f'[OK] 快照已写入 {args.snapshot}（{len(data["items"])} 项，exit {code}）')
        return code
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_table(data)
    return code


if __name__ == '__main__':
    sys.exit(common.cli(main))
