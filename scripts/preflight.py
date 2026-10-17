#!/usr/bin/env python3
"""Read-only check of every precondition for backup, cleanup and restore.

Each check is reported on its own; one unmet or failing check does not hide
the others. Exit 0 = all met, 1 = something to do first, 2 = a check itself
failed (its error is shown). Nothing is written, closed or changed.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

import check_environment
import common
import hints
import platforms

SPACE_MARGIN = 1.1
OK, BLOCKED, ERROR = 'ok', 'blocked', 'error'


def check_python(platform, home, args):
    if sys.version_info >= (3, 10):
        return OK, f'Python {sys.version.split()[0]}', None
    return BLOCKED, f'Python {sys.version.split()[0]} 太旧', '安装 Python 3.10 或更新版本后，用新版本重新运行'


def check_tools(platform, home, args):
    search_path = os.environ.get('PATH', os.defpath)
    missing = [name for name in platform.base_tools
               if not any(item['usable_path'] for item in check_environment.command_paths(name, search_path, platform))]
    if args.leveldb:
        for name in ('node', 'npm'):
            if not any(item['usable_path'] for item in check_environment.command_paths(name, search_path, platform)):
                missing.append(name)
        if not common.exists(Path(__file__).resolve().parents[1] / 'node_modules/classic-level/package.json'):
            missing.append('classic-level（在 skill 目录执行 npm ci）')
    if missing:
        return BLOCKED, '缺少: ' + '、'.join(missing), '按 references/first-run.md 准备这些依赖后重新运行'
    return OK, '基础依赖齐全' + ('（含 LevelDB 依赖）' if args.leveldb else ''), None


def check_apps(platform, home, args):
    alive = common.relevant_processes(common.process_list(), args.browsers_only)
    if not alive:
        return OK, '没有需要先退出的应用', None
    message = hints.running_apps_message(platform, alive)
    reason, _, step = message.partition('下一步：')
    return BLOCKED, reason.rstrip('；。'), step.rstrip('。')


def protected_locations(platform, home):
    if platform.key != 'darwin':
        return []
    return [home / '.Trash', platform.resolve(platform.safari_root, home)]


def check_privacy(platform, home, args):
    probed = []
    for path in protected_locations(platform, home):
        try:
            with os.scandir(path):
                pass
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            return BLOCKED, f'无法读取受保护位置 {path}', hints.next_step(exc, platform.key)
        probed.append(str(path))
    if platform.key != 'darwin':
        return OK, '不适用（Windows 没有 macOS 式的完全磁盘访问权限）', None
    return OK, '受保护位置可读' + (f'（{len(probed)} 处）' if probed else '（不存在，无需权限）'), None


def tree_size(path):
    """(bytes, links) without following links; walk errors propagate."""
    path = Path(path)
    if common.is_link(path):
        return path.lstat().st_size, [path]
    if not path.is_dir():
        return path.lstat().st_size, []
    total, links = 0, []
    def fail(exc):
        raise exc
    for parent, dirs, files in os.walk(path, onerror=fail, followlinks=False):
        for name in list(dirs):
            if common.is_link(Path(parent) / name):
                links.append(Path(parent) / name)
                dirs.remove(name)  # never descend into links or junctions
        for name in files:
            item = Path(parent) / name
            if common.is_link(item):
                links.append(item)
            else:
                total += item.lstat().st_size
    return total, links


def check_backup_parent(platform, home, args):
    dest = Path(args.dest).resolve() if args.dest else home.resolve()
    if not common.directory(dest):
        return BLOCKED, f'备份父目录不存在: {dest}', '先创建该目录，或不加 --dest 使用默认的用户目录'
    if not os.access(dest, os.W_OK):
        return BLOCKED, f'备份父目录不可写: {dest}', '换一个你有写权限的目录（例如用户目录）'
    sources = [path for path, _ in platform.core(home) if common.exists(path)]
    sources += [Path(item) for item in args.include]
    for src in sources:
        if dest == src or src in dest.parents:
            return BLOCKED, f'备份父目录位于备份来源内: {src}', '换一个不在 .claude 等来源目录里的位置'
    needed, links = 0, []
    for src in sources:
        size, found = tree_size(src)
        needed += size
        links += found
    if links and platform.key == 'win32':
        return (BLOCKED, f'备份来源含 {len(links)} 个符号链接/junction（例如 {links[0]}），Windows 备份不支持',
                '先人工确认这些链接的用途并处理，或只备份不含链接的具体路径；工具不会跟随或复制链接')
    free = shutil.disk_usage(dest).free
    detail = f'{dest}；默认备份约 {needed / 1024 ** 2:.1f} MB，可用 {free / 1024 ** 3:.1f} GB'
    if links:
        detail += f'；含 {len(links)} 个符号链接，按链接本身备份、不跟随'
    if free < needed * SPACE_MARGIN:
        return BLOCKED, '磁盘空间不足：' + detail, '清理出空间，或用 --dest 指向空间更大的本地磁盘目录'
    return OK, detail, None


def check_config_dir(platform, home, args):
    if 'CLAUDE_CONFIG_DIR' in os.environ:
        # Name only: the value is a user path and is not reported.
        return (BLOCKED, '已设置 CLAUDE_CONFIG_DIR，数据可能不在默认位置',
                '本工具的默认范围不完整；先确认该目录，由你决定是否取消该设置后再继续')
    return OK, '未设置 CLAUDE_CONFIG_DIR', None


CHECKS = (('python', 'Python 版本', check_python),
          ('tools', '依赖工具', check_tools),
          ('apps', '相关应用已退出', check_apps),
          ('privacy', '受保护位置可读', check_privacy),
          ('backup_parent', '备份位置与空间', check_backup_parent),
          ('config_dir', '默认配置目录', check_config_dir))


def collect(args, home=None):
    platform = platforms.current()
    home = Path.home() if home is None else Path(home)
    results = []
    for key, title, check in CHECKS:
        try:
            state, detail, step = check(platform, home, args)
        except (OSError, ValueError, RuntimeError) as exc:
            # Reported and counted, never treated as "met".
            state, detail = ERROR, f'{type(exc).__name__}: {exc}'
            step = hints.next_step(exc, platform.key) or '先解决该错误，再重新运行自检'
        results.append({'check': key, 'title': title, 'state': state, 'detail': detail, 'next_step': step})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--dest', help='计划使用的备份父目录（默认用户目录）')
    parser.add_argument('--include', action='append', default=[], help='计划额外备份的绝对路径，可重复')
    parser.add_argument('--browsers-only', action='store_true', help='只为只读浏览器扫描检查：只要求浏览器退出')
    parser.add_argument('--leveldb', action='store_true', help='同时检查 LevelDB 精删所需的 Node 与 classic-level')
    args = parser.parse_args()
    common.require_supported()
    results = collect(args)
    code = 2 if any(r['state'] == ERROR for r in results) else 1 if any(r['state'] == BLOCKED for r in results) else 0
    if args.json:
        print(json.dumps({'ready': code == 0, 'exit_code': code, 'checks': results}, ensure_ascii=False, indent=2))
    else:
        mark = {OK: '✅', BLOCKED: '❌', ERROR: '⚠️'}
        for item in results:
            print(f"{mark[item['state']]} {item['title']}：{item['detail']}")
            if item['next_step']:
                print(f"   下一步：{item['next_step']}")
        pending = sum(item['state'] != OK for item in results)
        print('可以开始：全部前提已满足。' if code == 0 else f'还不能开始：{pending} 项需要先处理（见上方“下一步”）。')
    return code


if __name__ == '__main__':
    sys.exit(common.cli(main))
