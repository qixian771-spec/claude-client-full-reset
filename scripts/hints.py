"""Plain-language next steps for common failures.

Messages name applications only by the tool's own table names and never
include process arguments, environment values, paths of other users or data
contents. Hints are appended to errors; exit codes do not change.
"""
from collections import Counter
import errno

FRIENDLY = {'msedge.exe': 'Microsoft Edge', 'chrome.exe': 'Google Chrome / Chromium', 'brave.exe': 'Brave',
            'vivaldi.exe': 'Vivaldi', 'firefox.exe': 'Firefox', 'claude.exe': 'Claude',
            'code.exe': 'VS Code', 'cursor.exe': 'Cursor', 'windsurf.exe': 'Windsurf', 'code': 'VS Code'}
CLI_LABEL = 'Claude Code（命令行会话）'
TERMINAL = '系统终端（macOS“终端”/iTerm，Windows Terminal/PowerShell）'


def app_counts(platform, processes):
    """{display name: count} for processes that block writes."""
    names = platform.browser_processes + platform.client_processes
    counts = Counter()
    for proc in processes:
        name = platform.matched_name(proc, names)
        if name is not None:
            counts[FRIENDLY.get(name.lower(), name)] += 1
        elif platform.is_cli_process(proc):
            counts[CLI_LABEL] += 1
    return counts


def running_apps_message(platform, processes):
    counts = app_counts(platform, processes)
    listing = '、'.join(f'{name}×{count}' for name, count in sorted(counts.items()))
    steps = []
    if platform.key == 'win32':
        if 'Claude' in counts:
            steps.append('在任务栏通知区域（托盘）右键 Claude 图标选“退出”，只关窗口不算')
        if 'Microsoft Edge' in counts:
            steps.append('Edge 先在“设置 → 系统和性能”关闭“启动增强”和“关闭 Microsoft Edge 后继续运行后台扩展和应用”，再退出 Edge')
        steps.append('其他应用从菜单正常退出')
    else:
        steps.append('在应用菜单选“退出”或按 ⌘Q 正常退出，只关窗口不算')
    if CLI_LABEL in counts:
        steps.append('Claude Code 会话输入 /exit 结束')
    steps.append(f'如果正在协助你的 AI 就运行在其中某个应用里，请按 AI 给出的交接步骤，在独立的{TERMINAL}里继续')
    return (f'相关应用仍在运行（{len(processes)} 个进程：{listing}）；请退出后重试。'
            f'下一步：{"；".join(steps)}。工具不会替你结束进程。')


def next_step(exc, platform_key):
    """A next step for an exception raised outside the tool's own messages, or None."""
    if isinstance(exc, PermissionError):
        if platform_key == 'darwin' and exc.errno == errno.EPERM:
            return ('macOS 隐私保护拒绝了访问（常见于废纸篓、Safari 等受保护位置）。在“系统设置 → 隐私与安全性 → '
                    '完全磁盘访问权限”中打开“运行这条命令的终端程序”（如“终端”或 iTerm）的开关，重新打开该终端后再运行。'
                    '在 Claude、VS Code 等应用的内置终端里运行时，权限按那个应用计算，请改用独立终端。')
        if platform_key == 'win32' and getattr(exc, 'winerror', None) == 32:
            return '文件正被其他程序占用：先正常退出相关应用（包括托盘和后台进程）后重试。'
        hint = ('当前用户没有该位置的访问权限：核对路径是否属于你；企业管理的电脑可能需要管理员处理。'
                '不要用 sudo 或“以管理员身份运行”绕过。')
        if platform_key == 'win32':
            hint += '如果 Windows 安全中心提示“受控文件夹访问”拦截，按通知核对后由你决定是否放行。'
        return hint
    return None
