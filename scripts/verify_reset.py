#!/usr/bin/env python3
"""Validate the documented local-data scope; no claim of forensic erasure."""
import argparse
import os
from pathlib import Path
import re
import sys
import common
import browser_scan
import backup

TRACE_NAMES = ('projects', 'history.jsonl', 'sessions', 'tasks', 'teams',
               'shell-snapshots', 'session-env', 'file-history', 'paste-cache', '.cc-writes')
PAT = re.compile(r'claude|anthropic', re.I)
ENV_PAT = re.compile(r'^(ANTHROPIC|CLAUDE|HEADROOM)[A-Z_]*$')
RC_PATTERN = re.compile(r'^\s*(?:export\s+)?(?:ANTHROPIC|CLAUDE|HEADROOM)[A-Z_]*=|^\s*alias\s+claude=')


def core_paths(home):
    # .claude contains user assets; do not classify the entire directory as cache.
    paths = [home / src for src, _ in backup.CORE
             if src not in ('.claude', '.zshrc', '.bashrc', '.profile', '.zprofile', '.zshenv')]
    paths += [home / '.claude' / name for name in TRACE_NAMES]
    paths += [home / '.config/claude', home / '.anthropic']
    return [str(path) for path in paths if common.exists(path)]


def shell_findings(home):
    result = []
    for name in ('.zshrc', '.zprofile', '.zshenv', '.bashrc', '.profile'):
        path = home / name
        if common.exists(path):
            common.regular(path)
            for index, line in enumerate(path.read_text().splitlines(), 1):
                if RC_PATTERN.search(line):
                    result.append(f'{path}:{index}')
    # No startup files are executed. Only names, never environment values.
    result += ['current-env:' + key for key in os.environ if ENV_PAT.fullmatch(key)]
    return result


def editor_findings(home):
    result = []
    for name in ('.vscode', '.cursor', '.windsurf'):
        folder = home / name / 'extensions'
        if common.directory(folder):
            result += [str(p) for p in folder.iterdir() if PAT.search(p.name)]
    for editor in ('Code', 'Cursor', 'Windsurf'):
        root = home / 'Library/Application Support' / editor / 'User'
        for suffix in ('settings.json', 'globalStorage/state.vscdb'):
            path = root / suffix
            if common.exists(path) and browser_scan.byte_hits(path):
                result.append(str(path))
    return result


def system_findings(home):
    result = []
    for folder in (home / 'Library/Logs/DiagnosticReports', Path('/Library/Logs/DiagnosticReports'),
                   home / '.Trash', home / 'Applications',
                   home / 'Library/Containers', home / 'Library/Group Containers',
                   home / 'Library/Application Scripts'):
        if common.directory(folder):
            result += [str(p) for p in folder.iterdir() if PAT.search(p.name)]
    return result


def collect(home=None, deep=False, no_browser=False):
    home = Path.home() if home is None else Path(home)
    findings = {
        '客户端数据': core_paths(home), '编辑器': editor_findings(home),
        '系统指定目录': system_findings(home), 'shell/当前环境': shell_findings(home),
    }
    if not no_browser:
        common.require_stopped(browsers_only=True)
        data = browser_scan.collect(deep)
        findings['浏览器'] = [f'{b}/{p}/{f}' for b, p, f, _, _ in data['chromium']]
        findings['浏览器'] += ['Safari/' + item[0] for item in data['safari']]
        if data['cache'] and data['cache'][0]:
            findings['浏览器'].append(f'Chrome HTTP 缓存: {data["cache"][0]} 个文件')
    return findings


def report(findings, quiet=False):
    total = sum(len(items) for items in findings.values())
    for name, items in findings.items():
        print(f'[{"FOUND" if items else "CLEAR"}] {name}: {len(items)}')
        if not quiet:
            for item in items:
                print('  ' + item)
    print(f'命中项合计: {total}')
    print('范围外：钥匙串、APFS/Time Machine、其他用户、外置盘、任意项目目录、npm 缓存、登录 shell 动态行为。')
    print('保留：.claude 中未列入痕迹清单的用户技能、设置等资产；单独保存的备份。')
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deep', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--uninstalled', action='store_true', help='额外要求应用和 PATH 中的 CLI 已卸载')
    args = parser.parse_args()
    common.require_macos()
    common.require_stopped()
    if args.uninstalled:
        import shutil
        if common.exists('/Applications/Claude.app') or common.exists(Path.home() / 'Applications/Claude.app') or shutil.which('claude'):
            raise RuntimeError('卸载验收前提不满足：仍有 Claude 安装')
    total = report(collect(deep=args.deep), args.quiet)
    print('PASS：所列范围未见命中（不等于全盘擦除）' if not total else 'REVIEW：仍有命中项，需逐项判断')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
