#!/usr/bin/env python3
"""Read-only macOS Claude environment inventory; never execute Claude or install anything."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

import backup
import common
import verify_reset

LABELS = {
    'not_detected': '常见位置未发现安装或本地数据',
    'installed': '发现安装候选路径',
    'local_data_only': '未发现安装，发现本地数据/配置',
    'needs_review': '发现异常或范围不确定，需要人工检查',
}
ASSETS = ('settings.json', 'settings.local.json', '.credentials.json', 'agents', 'hooks', 'plugins')
TOOLS = ('bash', 'ditto', 'osascript', 'git', 'node', 'npm')


def executable_info(path):
    path = Path(path)
    if not common.exists(path):
        return None
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return {'path': str(path), 'usable_path': False, 'reason': '符号链接指向不存在的位置'}
    info = resolved.stat()
    usable = stat.S_ISREG(info.st_mode) and os.access(resolved, os.X_OK)
    return {'path': str(path), 'usable_path': usable,
            'reason': '找到可执行路径，未运行或验证版本' if usable else '不是可执行的普通文件'}


def command_paths(name, search_path):
    found = []
    for part in search_path.split(os.pathsep):
        directory = Path(part) if part else Path.cwd()
        # Stat explicitly: unreadable PATH locations must not become "missing".
        if not common.exists(directory):
            continue
        if not stat.S_ISDIR(directory.stat().st_mode):
            raise ValueError(f'PATH 项不是目录: {directory}')
        entry = executable_info(directory / name)
        if entry is not None and entry['path'] not in {item['path'] for item in found}:
            found.append(entry)
    return found


def collect(home=None, search_path=None, app_paths=None, cli_paths=None):
    home = Path.home() if home is None else Path(home)
    search_path = os.environ.get('PATH', os.defpath) if search_path is None else search_path
    app_paths = [Path('/Applications/Claude.app'), home / 'Applications/Claude.app'] if app_paths is None else app_paths
    cli_paths = [home / '.local/bin/claude', Path('/opt/homebrew/bin/claude'), Path('/usr/local/bin/claude')] if cli_paths is None else cli_paths
    issues = []
    desktop = []
    for path in map(Path, app_paths):
        if common.exists(path):
            if path.is_symlink():
                issues.append({'path': str(path), 'reason': '应用路径为符号链接，需核对实际安装'})
            elif stat.S_ISDIR(path.stat().st_mode):
                desktop.append(str(path))
            else:
                issues.append({'path': str(path), 'reason': '应用路径存在但不是目录'})
    cli = command_paths('claude', search_path)
    for entry in cli:
        entry['on_path'] = True
    for path in cli_paths:
        entry = executable_info(path)
        if entry is not None and entry['path'] not in {item['path'] for item in cli}:
            entry['on_path'] = False
            cli.append(entry)
    issues.extend({'path': item['path'], 'reason': item['reason']} for item in cli if not item['usable_path'])
    active_cli = [item['path'] for item in cli if item['usable_path']]
    candidates = [home / source for source, _ in backup.CORE
                  if source not in ('.claude', '.zshrc', '.bashrc', '.profile', '.zprofile', '.zshenv')]
    candidates += [home / '.claude' / name for name in verify_reset.TRACE_NAMES]
    candidates += [home / '.config/claude', home / '.anthropic']
    candidates += [home / '.claude' / name for name in ASSETS]
    local = []
    for path in candidates:
        if common.exists(path):
            local.append(str(path))
            if path.is_symlink():
                issues.append({'path': str(path), 'reason': '数据/配置路径为符号链接，不能据此安排自动清理'})
    # Installing this skill alone must not count as prior Claude use.
    skill_present = common.exists(home / '.claude/skills/claude-client-full-reset/SKILL.md')
    claude_root = home / '.claude'
    if common.directory(claude_root):
        known = set(verify_reset.TRACE_NAMES) | set(ASSETS) | {'skills'}
        unknown = sum(child.name not in known for child in claude_root.iterdir())
        if unknown:
            issues.append({'reason': f'.claude 含 {unknown} 个范围未识别的顶层项目，需人工审阅；未读取内容'})
    processes = common.process_list()
    related = len(common.relevant_processes(processes))
    claude_running = sum(bool('/Claude.app/' in proc or Path(proc).name.startswith('Claude Helper')
                              or re.search(r'(?:^|/)claude(?:\s|$)', proc, re.I)
                              or '/@anthropic-ai/claude-code/' in proc) for proc in processes)
    if claude_running and not (desktop or active_cli):
        issues.append({'reason': '发现 Claude 进程但常见位置无安装路径，可能位于自定义位置'})
    tools = {name: command_paths(name, search_path) for name in TOOLS}
    issues.extend({'path': item['path'], 'reason': name + ': ' + item['reason']}
                  for name, paths in tools.items() for item in paths if not item['usable_path'])
    python_ok = sys.version_info >= (3, 10)
    missing = [name for name in ('bash', 'ditto', 'osascript')
               if not any(item['usable_path'] for item in tools[name])]
    if issues:
        status = 'needs_review'
    elif desktop or active_cli:
        status = 'installed'
    elif local:
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
    if related:
        next_steps.append('环境检测可继续；备份、清理、恢复和最终验收必须等相关应用正常退出后，在独立终端执行。')
    return {
        'schema_version': 1, 'platform': sys.platform, 'status': status, 'label': LABELS[status],
        'desktop_paths': desktop, 'cli_candidates': cli, 'local_paths': local,
        'skill_present': skill_present, 'related_process_count': related,
        'claude_process_count': claude_running, 'issues': issues,
        'python': {'version': '.'.join(map(str, sys.version_info[:3])), 'supported': python_ok},
        'tools': tools, 'missing_base_tools': missing, 'next_steps': next_steps,
        'account_status': 'not_checked', 'prior_use': 'not_determinable',
        'scope': ['只查常见安装路径、PATH、已列本地位置和进程；不启动 Claude，不联网，不安装或修改设置。',
                  '找到路径不等于安装完整或可登录；不执行命令验证 Claude、Git、Node 或 npm 版本。',
                  '未检查浏览器使用记录、钥匙串、云端、其他用户、自定义安装和数据目录；未发现不代表从未安装或使用。',
                  '不查询账号状态；重装或本地清理不能作为账号限制已解除的证明。'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='输出结构化报告；错误退出 2，不能当作无安装')
    args = parser.parse_args()
    common.require_macos()
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
        for path in report['local_paths']:
            print('[本地数据/配置] ' + path)
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
