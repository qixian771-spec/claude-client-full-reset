#!/usr/bin/env python3
"""Read local browser data; failures are errors, never empty scan results."""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import quote
import common
import platforms

PAT = re.compile(rb'claude|anthropic', re.I)
CHUNK = 1024 * 1024


def browser_roots():
    """Supported Chromium roots for the current platform and home directory."""
    return platforms.current().browsers()


def byte_hits(path):
    common.regular(path)
    n = 0
    carry = b''
    with open(path, 'rb') as stream:
        while True:
            block = stream.read(CHUNK)
            if not block:
                return n
            data = carry + block
            n += sum(match.end() > len(carry) for match in PAT.finditer(data))
            carry = data[-8:]


def _looks_sqlite(path):
    common.regular(path)
    with open(path, 'rb') as stream:
        return stream.read(16) == b'SQLite format 3\x00'


def sqlite_hits(path):
    # Copy the main DB and WAL together; querying the copy cannot create an SHM
    # file or recover a journal in the user's profile. Callers stop browsers first.
    with common.sqlite_snapshot(path) as snapshot:
        con = sqlite3.connect('file:' + quote(str(snapshot)) + '?mode=ro', uri=True)
        try:
            result = []
            for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                if table.startswith('sqlite_'):
                    continue
                qt = common.quote_identifier(table)
                for col in con.execute(f'PRAGMA table_info({qt})').fetchall():
                    qc = common.quote_identifier(col[1])
                    count = con.execute(f'SELECT count(*) FROM {qt} WHERE {qc} LIKE ? OR {qc} LIKE ?',
                                        ('%claude%', '%anthropic%')).fetchone()[0]
                    if count:
                        result.append((table, col[1], count))
            return result
        except sqlite3.Error as exc:
            raise RuntimeError(f'SQLite 扫描失败: {path} ({type(exc).__name__})') from exc
        finally:
            con.close()


def json_hits(path, limit=25):
    common.regular(path)
    obj = json.loads(Path(path).read_text(encoding='utf-8'))
    result = []
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.search('claude|anthropic', key, re.I):
                    result.append(('<redacted-key>', '<match>'))
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and re.search('claude|anthropic', value, re.I):
            result.append(('<redacted-value>', '<match>'))
    visit(obj)
    return result[:limit]


def iter_profiles(root):
    if not common.directory(root):
        return
    for child in sorted(Path(root).iterdir()):
        if common.is_link(child):
            raise ValueError(f'浏览器根目录存在符号链接，无法完整扫描: {child}')
        if child.is_dir() and (child.name == 'Default' or child.name.startswith('Profile ') or
                              any(common.exists(child / name) for name in ('Preferences', 'Cookies', 'History', 'Network'))):
            yield child.name, child


def scan_profile(root):
    result = []
    for path in common.walk_files(root):
        # SQLite gets inspected even without byte hits: WAL can contain all rows.
        count = byte_hits(path)
        sql = sqlite_hits(path) if _looks_sqlite(path) else []
        if count or sql:
            # '/' separators on every platform keep reports comparable.
            result.append((path.relative_to(root).as_posix(), count, sql))
    return result


def scan_safari():
    result = []
    platform = platforms.current()
    if platform.safari_root is None:
        return result
    root = platform.resolve(platform.safari_root)
    if common.directory(root):
        for name in platform.safari_files:
            path = root / name
            if common.exists(path):
                count = byte_hits(path)
                sql = sqlite_hits(path) if _looks_sqlite(path) else []
                if count or sql:
                    result.append((name, count, sql))
    return result


def scan_http_cache():
    count = size = 0
    platform = platforms.current()
    for path in common.walk_files(platform.resolve(platform.browser_cache)):
        size += path.stat().st_size
        count += bool(byte_hits(path))
    return [], count, size


def scope_note(platform):
    parts = ['Chromium profiles 与 Local State']
    parts.append('Safari 三类文件' if platform.safari_root else 'Safari 不适用')
    parts.append('--deep 加 Chrome HTTP 缓存' if platform.browser_cache
                 else 'HTTP 缓存位于 profile 内，已随 profile 扫描')
    return '；'.join(parts) + '。'


def collect(deep=False, browsers=None):
    result = {'chromium': [], 'safari': [], 'profiles': 0, 'files': 0, 'cache': None}
    for name, root in browser_roots() if browsers is None else browsers:
        for profile, folder in iter_profiles(root):
            result['profiles'] += 1
            for entry, count, sql in scan_profile(folder):
                result['chromium'].append((name, profile, entry, count, sql))
                result['files'] += 1
        # Browser-wide Local State is outside profiles.
        state = Path(root) / 'Local State'
        if common.exists(state):
            count = byte_hits(state)
            if count:
                result['chromium'].append((name, '<root>', 'Local State', count, []))
                result['files'] += 1
    result['safari'] = scan_safari()
    result['files'] += len(result['safari'])
    if deep and platforms.current().browser_cache is not None:
        _, count, size = scan_http_cache()
        result['cache'] = (count, size)
        result['files'] += count
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deep', action='store_true')
    args = parser.parse_args()
    common.require_supported()
    common.require_stopped(browsers_only=True)
    result = collect(args.deep)
    for browser, profile, entry, count, sql in result['chromium']:
        print(f'[FOUND] {browser}/{profile}/{entry}: byte_matches={count}, sql_columns={len(sql)}')
    for entry, count, sql in result['safari']:
        print(f'[FOUND] Safari/{entry}: byte_matches={count}, sql_columns={len(sql)}')
    if result['cache']:
        print(f'[CACHE] matched_files={result["cache"][0]}')
    print(f'profiles={result["profiles"]}; matched_entries={result["files"]}')
    print('范围：' + scope_note(platforms.current()))
    return 1 if result['files'] else 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
