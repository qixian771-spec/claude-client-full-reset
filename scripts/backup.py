#!/usr/bin/env python3
"""Verified backups: ditto on macOS, strict Python copy on Windows, SHA-256 manifests, no overwrite on restore."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
import common
import platforms

def fingerprint(path):
    path = Path(path)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return {'type': 'link', 'target': os.readlink(path)}
    if common.reparse_point(info):
        raise ValueError(f'备份不支持 junction 或其他重解析点: {path}')
    if stat.S_ISDIR(info.st_mode):
        return {'type': 'dir'}
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'备份不支持特殊文件: {path}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'type': 'file', 'sha256': digest.hexdigest(), 'size': info.st_size}


def inventory(root):
    root = Path(root)
    data = {'.': fingerprint(root)}
    if data['.']['type'] == 'dir':
        for child in sorted(root.iterdir()):
            for name, value in inventory(child).items():
                data[child.name if name == '.' else child.name + '/' + name] = value
    return data


def absolute_path(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('必须使用不含 .. 的绝对路径')
    platforms.current().check_path_form(path)
    return path


def no_symlink_parents(path):
    for parent in Path(path).parents:
        if common.exists(parent) and common.is_link(parent):
            # macOS /var and /tmp are system aliases. Resolve before calling this
            # function; arbitrary user-created links remain visible at CLI input.
            raise ValueError(f'父目录是符号链接或 junction: {parent}')


def copy_strict(source, target, reserved=False):
    """Windows copy: never follows or creates links, never merges or overwrites.

    reserved=True only for the exact empty placeholder restore() creates.
    Content is verified afterwards against the SHA-256 inventory.
    """
    source, target = Path(source), Path(target)
    info = source.lstat()
    if stat.S_ISLNK(info.st_mode) or common.reparse_point(info):
        raise ValueError(f'Windows 备份不支持符号链接、junction 或其他重解析点: {source}')
    if stat.S_ISDIR(info.st_mode):
        if reserved:
            if common.is_link(target) or not target.is_dir() or any(target.iterdir()):
                raise ValueError(f'恢复占位目录不是空目录，停止: {target}')
        else:
            target.mkdir()
        for child in sorted(source.iterdir()):
            copy_strict(child, target / child.name)
        shutil.copystat(source, target)
    elif stat.S_ISREG(info.st_mode):
        if reserved:
            placeholder = target.lstat()
            if not stat.S_ISREG(placeholder.st_mode) or common.reparse_point(placeholder) or placeholder.st_size:
                raise ValueError(f'恢复占位文件不是空文件，停止: {target}')
        with source.open('rb') as reader, (target.open('wb') if reserved else target.open('xb')) as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
        shutil.copystat(source, target)
    else:
        raise ValueError(f'备份不支持特殊文件: {source}')


def copy_entry(source, target, reserved=False):
    if platforms.current().key == 'darwin':
        common.run(['ditto', str(source), str(target)])
    else:
        copy_strict(source, target, reserved)


def restore_instructions(platform):
    if platform.key == 'win32':
        command, backup_dir, original, fence = 'py -3 scripts\\backup.py', 'C:\\absolute\\backup-directory', 'C:\\absolute\\original\\target', 'powershell'
    else:
        command, backup_dir, original, fence = 'python3 scripts/backup.py', '/absolute/backup-directory', '/absolute/original/target', 'bash'
    return (
        '# 备份校验与恢复\n\n在 skill 根目录执行（使用本备份目录的绝对路径）：\n\n'
        f'```{fence}\n{command} --verify {backup_dir}\n'
        f'{command} --list {backup_dir}\n'
        f'{command} --restore {backup_dir} --path {original} --dry-run\n'
        f'{command} --restore {backup_dir} --path {original}\n```\n\n'
        '把占位符替换为备份及原目标的绝对路径。--path 可重复，只恢复指定目标或备份内的子路径；'
        '不指定 --path 才是整包恢复，要求全部原目标都不存在。局部清理后通常应使用 --path。'
        '恢复前退出相关应用，在独立终端执行。所选目标必须不存在；不会合并或覆盖。'
        '仍存在的配置、SQLite/LevelDB 数据不要强行覆盖；先另行备份并确认移走具体目标。'
        '复制失败会保留可能产生的不完整目标并停止，不会自动删除、重试或扩大范围。'
        'manifest.json 记录完整 SHA-256 内容清单、目录与符号链接；不是签名或防篡改证明。\n')


def create_backup(dest, extra=()):
    platform = common.require_supported()
    common.require_stopped()
    home = Path.home().resolve()
    dest = Path(dest).resolve(strict=True)
    if not dest.is_dir():
        raise ValueError('备份父目录必须已存在')
    sources = [(src, name) for src, name in platform.core(home) if common.exists(src)]
    for index, item in enumerate(extra):
        src = absolute_path(item)
        no_symlink_parents(src)
        if not common.exists(src):
            raise ValueError(f'额外备份路径不存在: {src}')
        sources.append((src, f'extra/{index}'))
    sources = list({str(src): (src, name) for src, name in sources}.values())
    sources = [(src, name) for src, name in sources
               if not any(src != other and other in src.parents for other, _ in sources)]
    if not sources:
        raise ValueError('没有可备份的源数据；未创建成功备份')
    for src, _ in sources:
        if src == dest or src in dest.parents:
            raise ValueError('备份目录不能位于源目录内')
    folder = Path(tempfile.mkdtemp(prefix='Claude-Reset-Backup-', dir=dest))
    os.chmod(folder, 0o700)
    if platform.key == 'win32' and dest != home and home not in dest.parents:
        # chmod cannot restrict access on Windows; the user profile's ACL does.
        print(f'[注意] 备份位于用户目录之外，Windows 不会按 0700 限制访问；请确认该位置只有本人可读: {folder}',
              file=sys.stderr)
    payload = folder / 'payload'
    payload.mkdir()
    # Incomplete backups never receive manifest.json, and cannot authorize writes.
    entries = []
    for src, name in sources:
        before = inventory(src)
        target = payload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        copy_entry(src, target)
        if before != inventory(target) or before != inventory(src):
            raise RuntimeError(f'复制或源数据一致性验证失败: {src}；备份不完整: {folder}')
        entries.append({'source': str(src), 'stored': name, 'entries': before})
    data = {'version': 1, 'platform': platform.key, 'created_at': datetime.now(timezone.utc).isoformat(),
            'home': str(home), 'sources': entries, 'payload': inventory(payload)}
    (folder / 'manifest.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (folder / 'RESTORE.md').write_text(restore_instructions(platform), encoding='utf-8')
    verify_backup(folder)
    print(f'[OK] 备份与源数据一致: {folder}')
    return folder


def verify_backup(folder):
    folder = Path(folder).resolve(strict=True)
    data = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if data.get('version') != 1 or not data.get('sources'):
        raise ValueError('备份清单缺失或版本无效')
    # Manifests written before the platform field existed came from macOS only.
    if data.get('platform', 'darwin') != platforms.current().key:
        raise ValueError('备份来自其他平台，拒绝作为本次校验或修改依据')
    if data['home'] != str(Path.home().resolve()):
        raise ValueError('备份属于其他家目录，拒绝作为本次修改授权')
    payload = folder / 'payload'
    if inventory(payload) != data['payload']:
        raise ValueError(f'备份内容校验失败: {folder}')
    seen = set()
    for entry in data['sources']:
        stored = Path(entry['stored'])
        if stored.is_absolute() or '..' in stored.parts or str(stored) in seen:
            raise ValueError('非法或重复的备份条目')
        seen.add(str(stored))
        absolute_path(entry['source'])
        if inventory(payload / stored) != entry['entries']:
            raise ValueError('备份源清单不一致')
    return data


def require_covered(folder, target):
    data = verify_backup(folder)
    target = absolute_path(target)
    no_symlink_parents(target)
    for entry in data['sources']:
        src = Path(entry['source'])
        if target == src or src in target.parents:
            rel = target.relative_to(src).as_posix()
            subset = {}
            for name, value in entry['entries'].items():
                if rel == '.':
                    subset[name] = value
                elif name == rel:
                    subset['.'] = value
                elif name.startswith(rel + '/'):
                    subset[name[len(rel) + 1:]] = value
            if subset and inventory(target) == subset:
                return
            raise ValueError(f'目标自备份后已变化，请重新备份: {target}')
    raise ValueError(f'备份未覆盖目标: {target}')


def restore_plan(folder, data, paths=None):
    """Resolve exact original paths, including descendants, without writing."""
    from trash_paths import validate_path
    requested = [entry['source'] for entry in data['sources']] if paths is None else paths
    if not requested:
        raise ValueError('恢复清单不能为空')
    targets = [validate_path(str(value), must_exist=False) for value in requested]
    for i, target in enumerate(targets):
        if any(target == other or target in other.parents or other in target.parents
               for other in targets[i + 1:]):
            raise ValueError('恢复清单包含重复或父子重叠路径')
        if common.exists(target):
            raise ValueError(f'恢复目标已存在，拒绝覆盖: {target}')
    plan = []
    for target in targets:
        candidates = [entry for entry in data['sources']
                      if target == Path(entry['source']) or Path(entry['source']) in target.parents]
        if len(candidates) != 1:
            raise ValueError(f'恢复目标没有唯一备份来源: {target}')
        entry = candidates[0]
        relative = target.relative_to(entry['source'])
        key = relative.as_posix()
        if key not in entry['entries']:
            raise ValueError(f'备份未包含恢复目标: {target}')
        if entry['entries'][key]['type'] not in ('file', 'dir'):
            raise ValueError(f'不支持单独恢复符号链接目标: {target}')
        source = folder / 'payload' / entry['stored'] / relative
        no_symlink_parents(source)
        expected = {}
        for name, value in entry['entries'].items():
            if key == '.':
                expected[name] = value
            elif name == key:
                expected['.'] = value
            elif name.startswith(key + '/'):
                expected[name[len(key) + 1:]] = value
        if inventory(source) != expected:
            raise ValueError(f'待恢复副本校验失败: {target}')
        plan.append((target, source, expected))
    return plan


def restore(folder, paths=None, dry_run=False):
    common.require_stopped()
    folder = Path(folder).resolve(strict=True)
    data = verify_backup(folder)
    plan = restore_plan(folder, data, paths)
    if dry_run:
        for target, _, _ in plan:
            print(f'[DRY] 将恢复: {target}')
        return
    from trash_paths import validate_path
    for target, source, expected in plan:
        common.require_stopped()
        validate_path(str(target), must_exist=False)
        if common.exists(target):
            raise ValueError(f'恢复过程中目标出现，停止: {target}')
        if inventory(source) != expected:
            raise ValueError(f'待恢复副本已变化，停止: {target}')
        target.parent.mkdir(parents=True, exist_ok=True)
        # Reserve the exact destination exclusively; an intervening existing
        # target must fail instead of being merged or overwritten by the copy.
        if expected['.']['type'] == 'dir':
            target.mkdir(mode=0o700)
        else:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        copy_entry(source, target, reserved=True)
        if inventory(target) != expected:
            raise RuntimeError(f'恢复内容验证失败: {target}')
        print(f'[OK] 已恢复并验证: {target}')
    print('[OK] 恢复并验证完成')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify', type=Path)
    mode.add_argument('--restore', type=Path)
    mode.add_argument('--list', dest='list_backup', type=Path, help='校验备份并列出原始来源路径')
    mode.add_argument('--check-path', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--dest', type=Path)
    parser.add_argument('--include', action='append', default=[])
    parser.add_argument('--path', action='append', help='仅恢复指定原始绝对路径，可重复；仅与 --restore 使用')
    parser.add_argument('--dry-run', action='store_true', help='仅预检并显示恢复计划；仅与 --restore 使用')
    args = parser.parse_args()
    common.require_supported()
    has_mode = any(value is not None for value in (args.verify, args.restore, args.check_path, args.list_backup))
    if (args.path is not None or args.dry_run) and args.restore is None:
        parser.error('--path/--dry-run 只能与 --restore 一起使用')
    if has_mode and (args.dest is not None or args.include):
        parser.error('--dest/--include 只能用于创建备份')
    if args.backup and args.check_path is None:
        parser.error('--backup 只能与 --check-path 一起使用')
    if args.verify:
        verify_backup(args.verify)
        print('[OK] SHA-256 内容清单校验通过')
    elif args.restore:
        restore(args.restore, args.path, args.dry_run)
    elif args.list_backup:
        data = verify_backup(args.list_backup)
        for entry in data['sources']:
            print(f'[SOURCE] {entry["source"]}')
        print('只列来源路径，不输出内容；可用 --path 选择来源或其中具体子路径。')
    elif args.check_path:
        if not args.backup:
            parser.error('--check-path 需要 --backup')
        require_covered(args.backup, args.check_path)
    else:
        if args.backup:
            parser.error('--backup 只能与 --check-path 一起使用')
        create_backup(Path.home() if args.dest is None else args.dest, args.include)
    return 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
