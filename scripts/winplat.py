"""Windows-only helpers: registry and process queries. Imported lazily, never on macOS.

Only value *names* are read from the environment key, never values, and only
display names from uninstall entries. Missing keys or values are reported as
errors unless the caller documents them as optional.
"""
import json
import os
from pathlib import Path

import common

USER_SHELL_FOLDERS = r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'


def _winreg():
    import winreg  # Windows standard library only
    return winreg


def documents_dir():
    """The user's real Documents folder (may be redirected, e.g. to OneDrive)."""
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_SHELL_FOLDERS) as key:
            value, _ = winreg.QueryValueEx(key, 'Personal')
    except FileNotFoundError as exc:
        raise RuntimeError('注册表中找不到“文档”文件夹位置，无法定位 PowerShell 配置文件') from exc
    path = Path(winreg.ExpandEnvironmentStrings(value))
    if not path.is_absolute():
        raise RuntimeError('“文档”文件夹位置不是绝对路径，需要人工检查')
    return path


def user_environment_names():
    """Names of persistent per-user environment variables (HKCU\\Environment)."""
    winreg = _winreg()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
        count = winreg.QueryInfoKey(key)[1]
        return [winreg.EnumValue(key, index)[0] for index in range(count)]


# Stop on any PowerShell error; emit UTF-8 JSON regardless of the console code page.
PROCESS_QUERY = ("$ErrorActionPreference = 'Stop'; "
                 "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; "
                 "Get-CimInstance -ClassName Win32_Process | "
                 "Select-Object Name, ExecutablePath, CommandLine | ConvertTo-Json -Compress")


def powershell():
    if 'SystemRoot' not in os.environ:
        raise RuntimeError('环境变量 SystemRoot 未设置，无法定位 Windows PowerShell')
    return str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def process_records():
    """[(name, executable path, command line)]; used only for matching, never printed."""
    output = common.run([powershell(), '-NoProfile', '-NonInteractive', '-Command', PROCESS_QUERY])
    try:
        data = json.loads(output)
    except ValueError as exc:
        # Do not include the output: command lines may carry credentials.
        raise RuntimeError('进程列表不是有效 JSON，无法判断相关应用是否运行') from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise RuntimeError('进程列表格式无效，无法判断相关应用是否运行')
    records = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get('Name'), str):
            raise RuntimeError('进程记录缺少名称，无法判断相关应用是否运行')
        records.append((item['Name'], item.get('ExecutablePath') or '', item.get('CommandLine') or ''))
    return records
