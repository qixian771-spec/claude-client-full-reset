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

DOMAIN = re.compile(r'(?:^|[^a-z0-9.-])\.?(?:[a-z0-9-]+\.)*(?:claude\.ai|anthropic\.com)(?=[:/?#\x00]|$)', re.I)


def require_supported():
    return platforms.current()


def run(args):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=60).stdout


def utf8_stdio():
    # Redirected output otherwise uses the locale code page on Windows.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding='utf-8')


def cli(main):
    utf8_stdio()
    try:
        return main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as exc:
        # Never print captured process output: it may contain credentials.
        print(f'[ERROR] {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


def exists(path):
    try:
        Path(path).lstat()
        return True
    except FileNotFoundError:
        return False


def directory(path):
    path = Path(path)
    if not exists(path):
        return False
    if path.is_symlink() or not stat.S_ISDIR(path.stat().st_mode):
        raise ValueError(f'不是可扫描的普通目录: {path}')
    return True


def regular(path):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode):
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
        raise RuntimeError(f'相关应用仍在运行（{len(alive)} 个进程）；请退出后重试')


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
