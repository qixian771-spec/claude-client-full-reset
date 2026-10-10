#!/usr/bin/env python3
"""Verified backups: ditto only, SHA-256 manifests, no overwrite on restore."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from datetime import datetime, timezone
import common

CORE = [
    ('.claude', 'dot-claude'), ('.claude.json', 'dot-claude.json'),
    ('Library/Application Support/Claude', 'AppSupport-Claude'),
    ('Library/Application Support/Claude-3p', 'AppSupport-Claude-3p'),
    ('Library/Preferences/com.anthropic.claudefordesktop.plist', 'plist'),
    ('Library/Caches/com.anthropic.claudefordesktop', 'Caches-app'),
    ('Library/Caches/com.anthropic.claudefordesktop.ShipIt', 'Caches-ShipIt'),
    ('Library/Caches/claude-cli-nodejs', 'Caches-cli'),
    ('Library/HTTPStorages/com.anthropic.claudefordesktop', 'HTTPStorages-app'),
    ('Library/Logs/Claude', 'Logs-Claude'), ('Library/Logs/Claude-3p', 'Logs-Claude-3p'),
    ('Library/Saved Application State/com.anthropic.claudefordesktop.savedState', 'SavedState'),
] + [(name, 'shell/' + name) for name in ('.zshrc', '.bashrc', '.profile', '.zprofile', '.zshenv')]


def fingerprint(path):
    path = Path(path)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return {'type': 'link', 'target': os.readlink(path)}
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
    return path


def no_symlink_parents(path):
    for parent in Path(path).parents:
        if parent.is_symlink():
            # macOS /var and /tmp are system aliases. Resolve before calling this
            # function; arbitrary user-created links remain visible at CLI input.
            raise ValueError(f'父目录是符号链接: {parent}')


def create_backup(dest, extra=()):
    common.require_stopped()
    home = Path.home().resolve()
    dest = Path(dest).resolve(strict=True)
    if not dest.is_dir():
        raise ValueError('备份父目录必须已存在')
    sources = [(home / src, name) for src, name in CORE if common.exists(home / src)]
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
    payload = folder / 'payload'
    payload.mkdir()
    # Incomplete backups never receive manifest.json, and cannot authorize writes.
    entries = []
    for src, name in sources:
        before = inventory(src)
        target = payload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        common.run(['ditto', str(src), str(target)])
        if before != inventory(target) or before != inventory(src):
            raise RuntimeError(f'复制或源数据一致性验证失败: {src}；备份不完整: {folder}')
        entries.append({'source': str(src), 'stored': name, 'entries': before})
    data = {'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
            'home': str(home), 'sources': entries, 'payload': inventory(payload)}
    (folder / 'manifest.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    (folder / 'RESTORE.md').write_text(
        '# 备份校验与恢复\n\n在 skill 根目录执行（使用本备份目录的绝对路径）：\n\n'
        '```bash\npython3 scripts/backup.py --verify /absolute/backup-directory\n'
        'python3 scripts/backup.py --restore /absolute/backup-directory\n```\n\n'
        '恢复前退出相关应用。目标路径必须不存在；不会合并或覆盖。'
        'manifest.json 记录完整 SHA-256 内容清单、目录与符号链接；不是签名或防篡改证明。\n')
    verify_backup(folder)
    print(f'[OK] 备份与源数据一致: {folder}')
    return folder


def verify_backup(folder):
    folder = Path(folder).resolve(strict=True)
    data = json.loads((folder / 'manifest.json').read_text())
    if data.get('version') != 1 or not data.get('sources'):
        raise ValueError('备份清单缺失或版本无效')
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


def restore(folder):
    common.require_stopped()
    folder = Path(folder).resolve(strict=True)
    data = verify_backup(folder)
    from trash_paths import validate_path
    for entry in data['sources']:
        target = Path(entry['source'])
        validate_path(str(target), must_exist=False)
        if common.exists(target):
            raise ValueError(f'恢复目标已存在，拒绝覆盖: {target}')
    for entry in data['sources']:
        target = Path(entry['source'])
        if common.exists(target):
            raise ValueError(f'恢复过程中目标出现，停止: {target}')
        target.parent.mkdir(parents=True, exist_ok=True)
        common.run(['ditto', str(folder / 'payload' / entry['stored']), str(target)])
        if inventory(target) != entry['entries']:
            raise RuntimeError(f'恢复内容验证失败: {target}')
    print('[OK] 恢复并验证完成')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify', type=Path)
    mode.add_argument('--restore', type=Path)
    mode.add_argument('--check-path', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--dest', type=Path)
    parser.add_argument('--include', action='append', default=[])
    args = parser.parse_args()
    common.require_macos()
    has_mode = args.verify is not None or args.restore is not None or args.check_path is not None
    if has_mode and (args.dest is not None or args.include):
        parser.error('--dest/--include 只能用于创建备份')
    if args.backup and args.check_path is None:
        parser.error('--backup 只能与 --check-path 一起使用')
    if args.verify:
        verify_backup(args.verify)
        print('[OK] SHA-256 内容清单校验通过')
    elif args.restore:
        restore(args.restore)
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
