#!/usr/bin/env python3
"""Preview or move approved, backed-up ordinary paths to the Trash (macOS) or Recycle Bin (Windows)."""
import argparse
from pathlib import Path
import sys
import common
import backup
import platforms


def validate_path(raw, must_exist=True):
    if any(ord(c) < 32 for c in raw):
        raise ValueError('路径包含控制字符')
    path = backup.absolute_path(raw)
    backup.no_symlink_parents(path)
    if common.exists(path) and common.is_link(path):
        raise ValueError('不支持移动符号链接、junction 或其他重解析点（包括断链）；请单独检查')
    platform = platforms.current()
    home = Path.home().resolve()
    protected = {home, *home.parents}
    protected.update(platform.resolve_all(platform.protected, home))
    if path in protected or any(p in path.parents for p in platform.resolve_all(platform.protected_trees, home)):
        raise ValueError(f'拒绝危险路径: {path}')
    for container, entries in platform.confined:
        if platform.resolve(container, home) in path.parents:
            permitted = platform.expand_all(entries, home)
            if not any(path == item or item in path.parents for item in permitted):
                raise ValueError(f'此容器内只允许处理 Claude 数据目录: {path}')
    allowed = home in path.parents or path in platform.resolve_all(platform.trash_allowed, home)
    if platform.trash_diagnostic_dir is not None:
        diagnostic = platform.resolve(platform.trash_diagnostic_dir, home)
        if path.parent == diagnostic and path.name.lower().startswith(('claude', 'anthropic')):
            allowed = True
    if not allowed:
        raise ValueError(f'目标不在支持的清理范围: {path}')
    if must_exist and not common.exists(path):
        raise ValueError(f'目标不存在: {path}')
    return path


def finder_trash(path):
    # The path is passed as argv, never interpolated into AppleScript source.
    script = ('on run argv\n'
              'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)\n'
              'end run')
    common.run(['osascript', '-e', script, str(path)])
    if common.exists(path):
        raise RuntimeError(f'Finder 返回后目标仍存在: {path}')


def move_to_trash(path):
    if platforms.current().key == 'win32':
        import winplat  # deferred: Windows-only module
        winplat.recycle(path)
    else:
        finder_trash(path)


def auto_memory_dirs(path):
    """Auto-memory folders under ~/.claude/projects affected by moving path."""
    projects = Path.home().resolve() / '.claude/projects'
    if path != projects and projects not in path.parents:
        return 0
    if path.name == 'memory' and path.parent.parent == projects:
        return 1
    if path.parent == projects:
        return int(common.exists(path / 'memory'))
    if path == projects:
        return sum(common.exists(child / 'memory') for child in path.iterdir() if common.directory(child))
    return 0


def execute(paths, apply=False, backup_dir=None):
    if not paths or len(paths) > 10:
        raise ValueError('每次需要 1–10 个明确路径')
    approved = [validate_path(raw) for raw in paths]
    for i, path in enumerate(approved):
        if any(path == other or path in other.parents or other in path.parents
               for other in approved[i + 1:]):
            raise ValueError('清单包含重复或父子重叠路径')
    if apply:
        if backup_dir is None:
            raise ValueError('实际移动需要 --backup 已验证的备份目录')
        common.require_stopped()
        for path in approved:
            backup.require_covered(backup_dir, path)
    for path in approved:
        memory = auto_memory_dirs(path)
        if memory:
            print(f'[注意] {path} 含 {memory} 个项目的自动记忆（memory/）；处理后这些记忆一并移走')
    # No target is touched until the entire batch passes preflight.
    for path in approved:
        if apply:
            common.require_stopped()
            validate_path(str(path))
            backup.require_covered(backup_dir, path)
            move_to_trash(path)
        print(f'[{"OK" if apply else "DRY"}] {path}')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('paths', nargs='+')
    args = parser.parse_args()
    common.require_supported()
    paths = args.paths
    if paths == ['-']:
        paths = sys.stdin.read().splitlines()
    elif '-' in paths:
        parser.error('stdin 模式 - 不能与其他路径混用')
    return execute(paths, args.apply, args.backup)


if __name__ == '__main__':
    sys.exit(common.cli(main))
