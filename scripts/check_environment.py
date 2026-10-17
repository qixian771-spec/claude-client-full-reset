#!/usr/bin/env python3
"""Read-only macOS Claude environment inventory; never execute Claude or install anything."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

import common
import platforms

LABELS = {
    'not_detected': '常见位置未发现安装或本地数据',
    'installed': '发现安装候选路径',
    'local_data_only': '未发现安装，发现本地数据/配置',
    'needs_review': '发现异常或范围不确定，需要人工检查',
}


def executable_info(path, platform=None):
    platform = platforms.current() if platform is None else platform
    path = Path(path)
    if not common.exists(path):
        return None
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return {'path': str(path), 'usable_path': False, 'reason': '符号链接指向不存在的位置'}
    info = resolved.stat()
    usable = stat.S_ISREG(info.st_mode) and platform.is_executable(resolved, info)
    return {'path': str(path), 'usable_path': usable,
            'reason': '找到可执行路径，未运行或验证版本' if usable else '不是可执行的普通文件'}


def command_paths(name, search_path, platform=None):
    platform = platforms.current() if platform is None else platform
    found = []
    # PATH syntax belongs to the host OS, not to the platform table.
    for part in search_path.split(os.pathsep):
        directory = Path(part) if part else Path.cwd()
        # Stat explicitly: unreadable PATH locations must not become "missing".
        if not common.exists(directory):
            continue
        if not stat.S_ISDIR(directory.stat().st_mode):
            raise ValueError(f'PATH 项不是目录: {directory}')
        for candidate in platform.executable_names(name):
            entry = executable_info(directory / candidate, platform)
            if entry is not None and Path(entry['path']) not in {Path(item['path']) for item in found}:
                found.append(entry)
    return found


def auto_memory_projects(projects):
    """Number of projects with an auto-memory folder (names only, nothing read)."""
    if not common.directory(projects):
        return 0
    return sum(common.directory(child) and common.exists(child / 'memory') for child in projects.iterdir())


KEYCHAIN_NOT_FOUND = 44  # security(1): item could not be found


def credential_locations(platform, home):
    """Whether credential stores exist. Values are never read or printed."""
    found = []
    if platform.keychain_service is not None:
        # Without -w/-g only attributes are queried, so no secret is returned
        # and no Keychain access prompt is shown.
        code = common.run_status(['security', 'find-generic-password', '-s', platform.keychain_service])
        if code not in (0, KEYCHAIN_NOT_FOUND):
            raise RuntimeError(f'查询钥匙串失败（security 退出码 {code}），无法判断凭证位置')
        found.append({'location': f'macOS 钥匙串项 {platform.keychain_service}（名称来自社区资料）',
                      'present': code == 0})
    for label, path in (('Claude Code 凭证文件', home / '.claude/.credentials.json'),
                        ('Anthropic profile 目录', platform.resolve(platform.anthropic_profile_dir, home))):
        found.append({'location': f'{label} {path}', 'present': common.exists(path)})
    return found


def collect(home=None, search_path=None, app_paths=None, cli_paths=None):
    platform = platforms.current()
    home = Path.home() if home is None else Path(home)
    search_path = os.environ.get('PATH', os.defpath) if search_path is None else search_path
    app_paths = platform.expand_all(platform.desktop_apps, home) if app_paths is None else app_paths
    cli_paths = platform.resolve_all(platform.cli_candidates, home) if cli_paths is None else cli_paths
    issues = []
    desktop = []
    if platform.key == 'win32':
        packages = [path for path in app_paths if path.name.lower().startswith('claude_')]
        if len(packages) > 1:
            issues.append({'reason': f'发现 {len(packages)} 个 Claude MSIX 包目录，需人工确认哪个在用'})
    for path in map(Path, app_paths):
        if common.exists(path):
            if common.is_link(path):
                issues.append({'path': str(path), 'reason': '应用路径为符号链接，需核对实际安装'})
            elif stat.S_ISDIR(path.stat().st_mode):
                desktop.append(str(path))
            else:
                issues.append({'path': str(path), 'reason': '应用路径存在但不是目录'})
    cli = command_paths('claude', search_path, platform)
    for entry in cli:
        entry['on_path'] = True
    for path in cli_paths:
        entry = executable_info(path, platform)
        if entry is not None and Path(entry['path']) not in {Path(item['path']) for item in cli}:
            entry['on_path'] = False
            cli.append(entry)
    issues.extend({'path': item['path'], 'reason': item['reason']} for item in cli if not item['usable_path'])
    active_cli = [item['path'] for item in cli if item['usable_path']]
    candidates = platform.client_data_paths(home)
    candidates += [home / '.claude' / name for name in platform.trace_names]
    candidates += platform.resolve_all(platform.extra_config, home)
    candidates += [home / '.claude' / name for name in platform.asset_names]
    local = []
    for path in candidates:
        if common.exists(path):
            local.append(str(path))
            if common.is_link(path):
                issues.append({'path': str(path), 'reason': '数据/配置路径为符号链接，不能据此安排自动清理'})
    install_dirs = [str(path) for path in platform.resolve_all(platform.cli_install_dirs, home)
                    if common.directory(path)]
    if install_dirs and not active_cli:
        issues.append({'reason': '发现 Claude Code 版本目录，但未找到可用的 claude 启动器，可能安装不完整'})
    # Installing this skill alone must not count as prior Claude use.
    skill_present = common.exists(home / '.claude/skills/claude-client-full-reset/SKILL.md')
    claude_root = home / '.claude'
    unclassified = []
    if common.directory(claude_root):
        known = set(platform.trace_names) | set(platform.asset_names) | {'skills'}
        # Names only; contents are never read.
        unclassified = sorted(child.name for child in claude_root.iterdir() if child.name not in known)
    memory_projects = auto_memory_projects(claude_root / 'projects')
    credentials = credential_locations(platform, home)
    if 'CLAUDE_CONFIG_DIR' in os.environ:
        # Name only: the value is a user path and is not reported.
        issues.append({'reason': '已设置 CLAUDE_CONFIG_DIR：配置、历史与凭证可能不在 ~/.claude，本工具的默认范围不完整'})
    processes = common.process_list()
    related = len(common.relevant_processes(processes))
    claude_running = sum(platform.is_claude_process(proc) for proc in processes)
    if claude_running and not (desktop or active_cli):
        issues.append({'reason': '发现 Claude 进程但常见位置无安装路径，可能位于自定义位置'})
    registered = platform.registered_apps()
    if registered and not (desktop or active_cli):
        issues.append({'reason': '系统登记了 Claude 相关安装项，但常见位置未发现安装路径，可能位于自定义位置'})
    tools = {name: command_paths(name, search_path, platform) for name in platform.tools}
    issues.extend({'path': item['path'], 'reason': name + ': ' + item['reason']}
                  for name, paths in tools.items() for item in paths if not item['usable_path'])
    python_ok = sys.version_info >= (3, 10)
    missing = [name for name in platform.base_tools
               if not any(item['usable_path'] for item in tools[name])]
    if issues:
        status = 'needs_review'
    elif desktop or active_cli:
        status = 'installed'
    elif local or unclassified:
        status = 'local_data_only'
    else:
        status = 'not_detected'
    next_steps = {
        'not_detected': ['无需先重置或创建清理备份。选择 Desktop 或 Claude Code，按 references/environment-check.md 的首次安装清单准备。'],
        'installed': ['保留现有安装和配置；按需检查本地问题，不自动重装、覆盖或清理。'],
        'local_data_only': ['先审阅残留和自有配置；需要修改时再退出应用、备份并确认具体目标，不自动删除整个 .claude。'],
        'needs_review': ['先处理或核实异常路径，不根据本次结果安排自动安装、清理或恢复。'],
    }[status]
    if missing or not python_ok:
        next_steps.append('先按 references/first-run.md 补齐工具基础依赖，再重新检查。')
    if active_cli and not any(item['usable_path'] and item['on_path'] for item in cli):
        next_steps.append('找到 CLI 但它不在当前 PATH 中；按官方安装说明核对 PATH，不自动改 shell 配置或重装。')
    if unclassified:
        next_steps.append(f'.claude 有 {len(unclassified)} 个未归类的顶层项目（见 unclassified_items），'
                          '工具不会自动处理；需要时人工逐项确认用途。')
    if memory_projects:
        next_steps.append(f'.claude/projects 中有 {memory_projects} 个项目含自动记忆（memory/）；'
                          '处理 projects 会一并移走这些记忆，需单独确认是否保留。')
    if related:
        next_steps.append('环境检测可继续；备份、清理、恢复和最终验收必须等相关应用正常退出后，在独立终端执行。')
    return {
        'schema_version': 1, 'platform': sys.platform, 'status': status, 'label': LABELS[status],
        'desktop_paths': desktop, 'cli_candidates': cli, 'cli_install_dirs': install_dirs,
        'local_paths': local, 'unclassified_items': unclassified, 'auto_memory_projects': memory_projects,
        'credential_locations': credentials,
        'skill_present': skill_present, 'registered_apps': registered, 'related_process_count': related,
        'claude_process_count': claude_running, 'issues': issues,
        'python': {'version': '.'.join(map(str, sys.version_info[:3])), 'supported': python_ok},
        'tools': tools, 'missing_base_tools': missing, 'next_steps': next_steps,
        'account_status': 'not_checked', 'prior_use': 'not_determinable',
        'scope': ['只查常见安装路径、PATH、已列本地位置和进程；不启动 Claude，不联网，不安装或修改设置。',
                  '找到路径不等于安装完整或可登录；不执行命令验证 Claude、Git、Node 或 npm 版本。',
                  '未检查浏览器使用记录、钥匙串/凭据管理器、云端、其他用户、自定义安装和数据目录；未发现不代表从未安装或使用。',
                  '不查询账号状态；重装或本地清理不能作为账号限制已解除的证明。'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='输出结构化报告；错误退出 2，不能当作无安装')
    args = parser.parse_args()
    common.require_supported()
    report = collect()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print('[环境] ' + report['label'])
        print(f'[Python] {report["python"]["version"]}；符合要求={report["python"]["supported"]}')
        for path in report['desktop_paths']:
            print('[Desktop 目录] ' + path)
        for item in report['cli_candidates']:
            print(f'[CLI 路径] {item["path"]}；在 PATH={item["on_path"]}；{item["reason"]}')
        for path in report['cli_install_dirs']:
            print('[CLI 版本目录] ' + path)
        for path in report['local_paths']:
            print('[本地数据/配置] ' + path)
        for name in report['unclassified_items']:
            print('[未归类] .claude/' + name)
        for name in report['registered_apps']:
            print('[系统登记] ' + name)
        for item in report['credential_locations']:
            print(f"[凭证位置] {item['location']}：{'存在' if item['present'] else '不存在'}（未读取内容，工具不处理）")
        for name, paths in report['tools'].items():
            state = '发现可执行路径，版本未验证' if any(p['usable_path'] for p in paths) else '未找到可执行路径'
            print(f'[依赖] {name}: {state}')
        print(f'[进程] Claude={report["claude_process_count"]}；阻止修改的相关进程={report["related_process_count"]}')
        for item in report['issues']:
            print('[需检查] ' + item['reason'] + ('：' + item['path'] if 'path' in item else ''))
        for step in report['next_steps']:
            print('[下一步] ' + step)
        for note in report['scope']:
            print('[范围] ' + note)
    return 1 if report['issues'] or report['missing_base_tools'] or not report['python']['supported'] else 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
