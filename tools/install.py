#!/usr/bin/env python3
"""Install this skill locally without replacing an existing installation."""
import argparse
import io
import os
from pathlib import Path
import shutil
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = 'claude-client-full-reset'
CONTENTS = ('SKILL.md', 'README.md', 'LICENSE', 'docs', 'agents', 'scripts', 'references', 'package.json', 'package-lock.json')


def install(target):
    target = Path(target)
    if not target.is_absolute() or '..' in target.parts:
        raise ValueError('安装目标必须是无 .. 的绝对路径')
    for parent in (target, *target.parents):
        if parent.is_symlink() or (parent.exists() and getattr(os.lstat(parent), 'st_file_attributes', 0)
                                   & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f'安装路径不能包含符号链接或 junction: {parent}')
    if target.exists():
        raise FileExistsError(f'目标已存在，拒绝覆盖: {target}')
    for name in CONTENTS:
        if not (ROOT / name).exists():
            raise FileNotFoundError(f'源文件缺失: {name}')
    target.mkdir(parents=True, exist_ok=False)
    for name in CONTENTS:
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, target / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(source, target / name)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--client', choices=('codex', 'claude'))
    choice.add_argument('--dest', type=Path, help='明确指定完整安装目录')
    args = parser.parse_args()
    if args.dest is not None:
        target = args.dest
    elif args.client == 'codex':
        base = Path(os.environ['CODEX_HOME']) if 'CODEX_HOME' in os.environ else Path.home() / '.codex'
        target = base / 'skills' / NAME
    else:
        target = Path.home() / '.claude/skills' / NAME
    target = install(target)
    print(f'[OK] 已安装: {target}')
    command = 'py -3 scripts\\check_environment.py' if sys.platform == 'win32' else 'python3 scripts/check_environment.py'
    print(f'先在该目录运行 {command}，只读检测；准备步骤见 references/first-run.md。')
    print('仅 LevelDB 功能需要在该目录执行 npm ci。')
    print('Claude Code 只能协助准备；备份、清理和恢复需退出相关应用后在独立终端执行。')
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        # Redirected output otherwise uses the locale code page on Windows.
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding='utf-8')
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        sys.exit(2)
