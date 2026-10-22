"""Shared strict I/O, platform, process and browser definitions."""
import os
import contextlib
import hashlib
import io
import shutil
import tempfile
from pathlib import Path
import re
import stat
import sqlite3
import subprocess
import sys

import platforms

DOMAIN = re.compile(
    r'(?:^|[^a-z0-9.-])\.?(?:[a-z0-9-]+\.)*(?:claude\.ai|claude\.com|clau\.de|anthropic\.com|claudeusercontent\.com|claudemcpclient\.com|claudemcpcontent\.com)(?=[:/?#\x00]|$)',
    re.I,
)


def require_supported():
    return platforms.current()


def run(args):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                          check=True, timeout=60).stdout


def utf8_stdio():
    # Redirected streams otherwise use the locale code page on Windows; a
    # piped "是" was read as mojibake and (safely) treated as no confirmation.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding='utf-8')


def run_status(args):
    """Exit status only. Output is discarded: it may name accounts."""
    return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          check=False, timeout=60).returncode


def cli(main):
    utf8_stdio()
    try:
        return main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as exc:
        # Never print captured process output: it may contain credentials.
        print(f'[ERROR] {type(exc).__name__}: {exc}', file=sys.stderr)
        import hints  # deferred: only needed on failure
        step = hints.next_step(exc, sys.platform)
        if step:
            print('[下一步] ' + step, file=sys.stderr)
        return 2


def exists(path):
    try:
        Path(path).lstat()
        return True
    except FileNotFoundError:
        return False


def reparse_point(info):
    # POSIX has no reparse points. On Windows, junctions, mount points and
    # cloud placeholders carry this attribute without being S_ISLNK.
    return bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def is_link(path):
    """Symlink, junction or other reparse point; a missing path raises."""
    info = Path(path).lstat()
    return stat.S_ISLNK(info.st_mode) or reparse_point(info)


def directory(path):
    path = Path(path)
    if not exists(path):
        return False
    if is_link(path) or not stat.S_ISDIR(path.stat().st_mode):
        raise ValueError(f'不是可扫描的普通目录: {path}')
    return True


def regular(path):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or reparse_point(info):
        raise ValueError(f'不支持的文件类型或符号链接: {path}')


def walk_files(root):
    if not directory(root):
        return
    def fail(exc):
        raise exc
    for parent, dirs, files in os.walk(root, onerror=fail, followlinks=False):
        for name in dirs:
            directory(Path(parent) / name)
        for name in sorted(files):
            path = Path(parent) / name
            regular(path)
            yield path


def process_list():
    if platforms.current().key == 'win32':
        import winplat  # deferred: Windows-only module
        return winplat.process_records()
    return [x.strip() for x in run(['ps', '-eo', 'args=']).splitlines() if x.strip()]


def relevant_processes(processes, browsers_only=False):
    platform = platforms.current()
    names = platform.browser_processes
    if not browsers_only:
        names = names + platform.client_processes
    found = []
    for proc in processes:
        if platform.match_process(proc, names):
            found.append(proc)
        elif not browsers_only and platform.is_cli_process(proc):
            found.append(proc)
    return found


def require_stopped(browsers_only=False):
    alive = relevant_processes(process_list(), browsers_only)
    if alive:
        import hints  # deferred: only needed when something is still running
        raise RuntimeError(hints.running_apps_message(platforms.current(), alive))


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


@contextlib.contextmanager
def sqlite_snapshot(path):
    """Copy all present database journals; verify sources did not change."""
    path = Path(path)
    def digest(file):
        regular(file)
        hasher = hashlib.sha256()
        with file.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    def sources():
        return {suffix: digest(Path(str(path) + suffix))
                for suffix in ('', '-wal', '-journal') if exists(Path(str(path) + suffix))}
    before = sources()
    if '' not in before:
        raise FileNotFoundError(f'数据库不存在: {path}')
    with tempfile.TemporaryDirectory(prefix='claude-sql-snapshot-') as tmp:
        snapshot = Path(tmp) / 'data'
        for suffix, checksum in before.items():
            target = Path(str(snapshot) + suffix)
            shutil.copyfile(str(path) + suffix, target)
            if digest(target) != checksum:
                raise RuntimeError(f'数据库复制校验失败: {path}')
        if sources() != before:
            raise RuntimeError(f'数据库在快照期间发生变化: {path}')
        yield snapshot
        if sources() != before:
            raise RuntimeError(f'数据库在预览期间发生变化: {path}')
