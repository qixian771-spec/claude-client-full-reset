#!/usr/bin/env python3
"""Preview or delete SQLite rows containing Claude/Anthropic service domains."""
import argparse
import contextlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote
import common
import browser_scan as BS
import backup


def sqlite_files(profile):
    return [p for p in common.walk_files(profile) if BS._looks_sqlite(p)]


def purge_db(path, apply_changes=False):
    path = Path(path)
    common.regular(path)
    uri = 'file:' + quote(str(path.absolute())) + ('?mode=rw' if apply_changes else '?mode=ro')
    # Preview runs on a disposable copy (including WAL), not on the original DB.
    context = contextlib.nullcontext(path) if apply_changes else common.sqlite_snapshot(path)
    with context as snapshot:
        if not apply_changes:
            uri = 'file:' + quote(str(snapshot)) + '?mode=ro'
        con = sqlite3.connect(uri, uri=True, timeout=5)
        con.create_function('target_domain', 1, lambda value: int(isinstance(value, str) and bool(common.DOMAIN.search(value))))
        try:
            con.execute('PRAGMA foreign_keys=ON')
            con.execute('BEGIN IMMEDIATE' if apply_changes else 'BEGIN')
            plan = []
            tables = con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
            for table, schema in tables:
                if table.startswith('sqlite_'):
                    continue
                if schema and 'CREATE VIRTUAL TABLE' in schema.upper():
                    raise ValueError(f'不支持自动修改虚拟表数据库: {path}')
                qt = common.quote_identifier(table)
                columns = con.execute(f'PRAGMA table_info({qt})').fetchall()
                predicate = ' OR '.join('target_domain(' + common.quote_identifier(col[1]) + ')' for col in columns)
                if not predicate:
                    raise ValueError(f'数据库表没有可检查列: {path}')
                count = con.execute(f'SELECT count(*) FROM {qt} WHERE {predicate}').fetchone()[0]
                if count:
                    plan.append((table, predicate, count))
            # Triggers and foreign keys can change unrelated rows. Refuse these
            # schemas instead of turning constraints off or silently skipping.
            if plan:
                if con.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' LIMIT 1").fetchone():
                    raise ValueError(f'数据库包含触发器，需要人工审阅: {path}')
                if any(con.execute('PRAGMA foreign_key_list(' + common.quote_identifier(t) + ')').fetchone() for t, _ in tables):
                    raise ValueError(f'数据库包含外键，需要人工审阅: {path}')
            total = sum(count for _, _, count in plan)
            if apply_changes:
                for table, predicate, count in plan:
                    changed = con.execute(f'DELETE FROM {common.quote_identifier(table)} WHERE {predicate}').rowcount
                    if changed != count:
                        raise RuntimeError('删除行数与预检不一致')
                con.commit()
                if total:
                    # If VACUUM fails, propagate error. The committed row deletion
                    # may already have happened; callers retain the backup.
                    con.execute('VACUUM')
            else:
                con.rollback()
            return total, [(table, count) for table, _, count in plan]
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--browser', help='浏览器显示名称，例如 Chrome、Edge；按当前平台校验')
    parser.add_argument('--profile')
    args = parser.parse_args()
    platform = common.require_supported()
    if args.browser is not None and args.browser not in platform.browser_names():
        parser.error(f'--browser 必须是以下之一: {", ".join(platform.browser_names())}')
    common.require_stopped()
    if args.apply and not args.backup:
        parser.error('--apply 需要 --backup')
    files = []
    profiles = 0
    for name, root in BS.browser_roots():
        if args.browser and name != args.browser:
            continue
        for profile, folder in BS.iter_profiles(root):
            if args.profile and profile != args.profile:
                continue
            profiles += 1
            files.extend(sqlite_files(folder))
    if (args.profile or args.browser) and not profiles:
        raise ValueError('指定浏览器/profile 不存在；未执行操作')
    # Validate every DB and backup before touching any database.
    plans = []
    for path in files:
        count, detail = purge_db(path)
        if count:
            if args.apply:
                for suffix in ('', '-wal', '-shm', '-journal'):
                    sidecar = Path(str(path) + suffix)
                    if common.exists(sidecar):
                        backup.require_covered(args.backup, sidecar)
            plans.append((path, count, detail))
    total = 0
    for path, count, detail in plans:
        if args.apply:
            common.require_stopped()
            backup.require_covered(args.backup, path)
            count, detail = purge_db(path, True)
        total += count
        print(json.dumps({'mode': 'APPLY' if args.apply else 'DRY', 'database': str(path),
                          'rows': count, 'tables': detail}, ensure_ascii=False))
    print(f'files={len(plans)}; rows={total}；仅处理文本中的服务域名；其他命中需单独审阅。')
    return 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
