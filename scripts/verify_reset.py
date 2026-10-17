#!/usr/bin/env python3
"""Validate the documented local-data scope; no claim of forensic erasure."""
import argparse
import os
from pathlib import Path
import re
import sys
import common
import browser_scan
import platforms

PAT = re.compile(r'claude|anthropic', re.I)
ENV_PAT = re.compile(r'^(ANTHROPIC|CLAUDE|HEADROOM)[A-Z_]*$')


def core_paths(home):
    # .claude contains user assets; do not classify the entire directory as cache.
    platform = platforms.current()
    paths = platform.client_data_paths(home)
    paths += [home / '.claude' / name for name in platform.trace_names]
    paths += platform.resolve_all(platform.extra_config, home)
    return [str(path) for path in paths if common.exists(path)]


def shell_findings(home):
    platform = platforms.current()
    result = []
    for path in platform.resolve_all(platform.shell_files, home):
        if common.exists(path):
            common.regular(path)
            for index, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if platform.shell_pattern.search(line):
                    result.append(f'{path}:{index}')
    # No startup files are executed. Only names, never environment values.
    result += ['current-env:' + key for key in os.environ if ENV_PAT.fullmatch(key)]
    result += ['user-env:' + key for key in platform.persistent_env_names() if ENV_PAT.fullmatch(key.upper())]
    return result


def editor_findings(home):
    platform = platforms.current()
    result = []
    for folder in platform.resolve_all(platform.editor_extensions, home):
        if common.directory(folder):
            result += [str(p) for p in folder.iterdir() if PAT.search(p.name)]
    for root in platform.resolve_all(platform.editor_user_dirs, home):
        for suffix in ('settings.json', 'globalStorage/state.vscdb'):
            path = root / suffix
            if common.exists(path) and browser_scan.byte_hits(path):
                result.append(str(path))
    return result


def system_findings(home):
    platform = platforms.current()
    result = []
    for folder in platform.resolve_all(platform.system_dirs, home):
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
    print(platforms.current().out_of_scope)
    print('保留：.claude 中未列入痕迹清单的用户技能、设置等资产；单独保存的备份。')
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deep', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--uninstalled', action='store_true', help='额外要求应用和 PATH 中的 CLI 已卸载')
    args = parser.parse_args()
    platform = common.require_supported()
    common.require_stopped()
    if args.uninstalled:
        # Same installation rules as the environment check (PATH, PATHEXT,
        # known launchers, Desktop locations, native version store).
        import check_environment
        found = check_environment.collect()
        if (found['desktop_paths'] or found['cli_install_dirs']
                or any(item['usable_path'] for item in found['cli_candidates'])):
            raise RuntimeError('卸载验收前提不满足：仍有 Claude 安装')
    total = report(collect(deep=args.deep), args.quiet)
    import check_environment
    for item in check_environment.credential_locations(platform, Path.home()):
        if item['present']:
            # Informational: credentials are kept assets, not counted as hits.
            print(f"[INFO] 凭证位置仍存在（工具不处理，未读取内容）：{item['location']}")
    print('PASS：所列范围未见命中（不等于全盘擦除）' if not total else 'REVIEW：仍有命中项，需逐项判断')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
