#!/usr/bin/env python3
"""Write a double-click hand-over for confirmed cleanup targets.

The AI host itself must quit before any write, so it prepares this instead:
a JSON plan with exactly the confirmed targets plus a launcher the user
double-clicks in a standalone terminal (macOS .command, Windows .cmd). The
launcher runs scripts/handover_run.py, which stops at the first failure and
asks the user to type 是 before writing anything. Generating writes only the
two new files; existing files are never overwritten.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import sys

import backup
import common
import platforms
import trash_paths

ROOT = Path(__file__).resolve().parents[1]


def default_out_dir(home):
    desktop = home / 'Desktop'
    return desktop if common.directory(desktop) else home


def build_plan(targets, dest, includes, home):
    platform = platforms.current()
    approved = [trash_paths.validate_path(raw) for raw in targets]
    if not 1 <= len(approved) <= 10:
        raise ValueError('每次需要 1–10 个明确路径')
    for i, path in enumerate(approved):
        if any(path == other or path in other.parents or other in path.parents for other in approved[i + 1:]):
            raise ValueError('清单包含重复或父子重叠路径')
    dest = Path(dest).resolve(strict=True)
    if not dest.is_dir():
        raise ValueError(f'备份父目录必须已存在: {dest}')
    extra = [backup.absolute_path(item) for item in includes]
    # Targets outside the default backup list must be added, or the move
    # would be refused for lack of coverage.
    covered = [path for path, _ in platform.core(home) if common.exists(path)] + extra
    for path in approved:
        if not any(path == src or src in path.parents for src in covered):
            extra.append(path)
            covered.append(path)
    return {'version': 1, 'platform': platform.key, 'skill_root': str(ROOT),
            'targets': [str(path) for path in approved], 'dest': str(dest),
            'includes': [str(path) for path in extra]}


def launcher(platform, plan_path):
    if platform.key == 'win32':
        for value in (str(ROOT), str(plan_path)):
            # cmd.exe expands % even inside quotes and cannot nest quotes.
            if '%' in value or '"' in value:
                raise ValueError(f'路径含 % 或 "，无法安全写入 .cmd 启动器: {value}')
        return ('@echo off\r\nchcp 65001 >nul\r\n'
                f'cd /d "{ROOT}"\r\n'
                f'py -3 scripts\\handover_run.py --plan "{plan_path}"\r\n'
                # pause resets ERRORLEVEL; keep the run's exit code for the caller.
                'set "code=%ERRORLEVEL%"\r\necho.\r\npause\r\nexit /b %code%\r\n')
    return ('#!/bin/bash\n'
            f'cd -- {shlex.quote(str(ROOT))} || exit 2\n'
            f'python3 scripts/handover_run.py --plan {shlex.quote(str(plan_path))}\n'
            'code=$?\necho\nread -r -p "按回车关闭这个窗口" _\nexit $code\n')


def write_new(path, text, newline=None):
    with open(path, 'x', encoding='utf-8', newline=newline) as stream:
        stream.write(text)


def create(targets, dest, includes, out_dir, home=None):
    platform = platforms.current()
    home = Path.home() if home is None else Path(home)
    plan = build_plan(targets, dest, includes, home)
    out_dir = Path(out_dir).resolve(strict=True)
    if not out_dir.is_dir():
        raise ValueError(f'交接文件目录必须已存在: {out_dir}')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    plan_path = out_dir / f'Claude清理交接-{stamp}.json'
    launch_path = out_dir / f'Claude清理交接-{stamp}.{"cmd" if platform.key == "win32" else "command"}'
    text = launcher(platform, plan_path)
    write_new(plan_path, json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    write_new(launch_path, text, newline='' if platform.key == 'win32' else None)
    if platform.key != 'win32':
        os.chmod(launch_path, 0o700)
    return plan, plan_path, launch_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', action='append', required=True, help='已确认的目标绝对路径，可重复，最多 10 个')
    parser.add_argument('--dest', help='备份父目录（默认用户目录）')
    parser.add_argument('--include', action='append', default=[], help='额外备份的绝对路径，可重复')
    parser.add_argument('--out-dir', help='写交接文件的目录（默认桌面，没有桌面则用户目录）')
    args = parser.parse_args()
    common.require_supported()
    home = Path.home()
    plan, plan_path, launch_path = create(args.target, args.dest or home, args.include,
                                          args.out_dir or default_out_dir(home), home)
    print('[OK] 已生成交接文件（只包含下面这些已确认的目标）：')
    for target in plan['targets']:
        print('  目标: ' + target)
    for item in plan['includes']:
        print('  额外备份: ' + item)
    print('  备份父目录: ' + plan['dest'])
    print('  计划: ' + str(plan_path))
    print('  双击运行: ' + str(launch_path))
    print('  日志（运行后生成）: ' + str(plan_path.with_suffix('.log')))
    print('步骤：前提自检 → 预览 → 输入“是”确认 → 备份 → 校验 → 移入废纸篓/回收站 → 验收；不确认就什么都不写，任何一步失败即停止。')
    return 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
