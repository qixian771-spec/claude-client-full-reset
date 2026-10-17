"""Windows-only helpers: registry and process queries. Imported lazily, never on macOS.

Only value *names* are read from the environment key, never values, and only
display names from uninstall entries. Missing keys or values are reported as
errors unless the caller documents them as optional.
"""
import json
import os
import re
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


UNINSTALL_KEYS = (('HKEY_CURRENT_USER', r'Software\Microsoft\Windows\CurrentVersion\Uninstall'),
                  ('HKEY_LOCAL_MACHINE', r'Software\Microsoft\Windows\CurrentVersion\Uninstall'),
                  ('HKEY_LOCAL_MACHINE', r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'))


def uninstall_names():
    """DisplayName of uninstall registrations mentioning Claude/Anthropic (read-only)."""
    winreg = _winreg()
    found = []
    for root, path in UNINSTALL_KEYS:
        try:
            parent = winreg.OpenKey(getattr(winreg, root), path)
        except FileNotFoundError:
            continue  # the WOW6432Node view does not exist on 32-bit Windows
        with parent:
            for index in range(winreg.QueryInfoKey(parent)[0]):
                with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as entry:
                    try:
                        name, _ = winreg.QueryValueEx(entry, 'DisplayName')
                    except FileNotFoundError:
                        continue  # many registrations have no display name
                if isinstance(name, str) and re.search('claude|anthropic', name, re.I) and name not in found:
                    found.append(name)
    return found

# Stop on any PowerShell error; emit UTF-8 JSON regardless of the console code page.
PROCESS_QUERY = ("$ErrorActionPreference = 'Stop'; "
                 "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; "
                 "Get-CimInstance -ClassName Win32_Process | "
                 "Select-Object Name, ExecutablePath, CommandLine | ConvertTo-Json -Compress")


def powershell():
    if 'SystemRoot' not in os.environ:
        raise RuntimeError('环境变量 SystemRoot 未设置，无法定位 Windows PowerShell；请在正常登录的用户会话里，用系统终端（macOS“终端”或 Windows Terminal/PowerShell）运行，不要手动伪造该变量')
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


# SHFileOperationW constants (shellapi.h) and GetDriveTypeW result.
FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000
RECYCLE_FLAGS = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT | FOF_WANTNUKEWARNING
DRIVE_FIXED = 3
BITBUCKET = r'Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume'


class NativeShell:
    """Thin ctypes wrapper; replaced by a fake in portable tests."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            # shellapi.h packs this structure to 1 byte on 32-bit Windows only.
            if ctypes.sizeof(ctypes.c_void_p) == 4:
                _pack_ = 1
            _fields_ = [('hwnd', wintypes.HWND), ('wFunc', wintypes.UINT),
                        ('pFrom', wintypes.LPCWSTR), ('pTo', wintypes.LPCWSTR),
                        ('fFlags', wintypes.WORD), ('fAnyOperationsAborted', wintypes.BOOL),
                        ('hNameMappings', wintypes.LPVOID), ('lpszProgressTitle', wintypes.LPCWSTR)]

        self.ctypes, self.wintypes, self.struct = ctypes, wintypes, SHFILEOPSTRUCTW
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        self.shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
        self.shell32.SHFileOperationW.restype = ctypes.c_int

    def drive_type(self, root):
        return self.kernel32.GetDriveTypeW(root)

    def volume_guid(self, root):
        buffer = self.ctypes.create_unicode_buffer(64)
        if not self.kernel32.GetVolumeNameForVolumeMountPointW(root, buffer, len(buffer)):
            raise OSError(self.ctypes.get_last_error(), f'无法读取卷标识: {root}')
        # '\\?\Volume{GUID}\' -> '{GUID}'
        return buffer.value[buffer.value.index('{'):buffer.value.index('}') + 1]

    def nuke_on_delete(self, root):
        """True when the Recycle Bin of this volume deletes permanently."""
        winreg = _winreg()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, BITBUCKET + '\\' + self.volume_guid(root)) as key:
                value, _ = winreg.QueryValueEx(key, 'NukeOnDelete')
        except FileNotFoundError:
            # No per-volume entry: Windows uses its default, which recycles.
            return False
        return bool(value)

    def delete_to_recycle_bin(self, path):
        operation = self.struct(None, FO_DELETE, str(path) + '\0', None, RECYCLE_FLAGS, False, None, None)
        code = self.shell32.SHFileOperationW(self.ctypes.byref(operation))
        return code, bool(operation.fAnyOperationsAborted)


def recycle(path, shell=None):
    """Move one approved path to the Recycle Bin; anything that could delete permanently stops."""
    shell = NativeShell() if shell is None else shell
    path = Path(path)
    root = path.anchor
    if shell.drive_type(root) != DRIVE_FIXED:
        raise RuntimeError(f'只支持本地固定磁盘上的回收站（可移动盘或网络盘会永久删除）: {path}；请把数据放在本地固定磁盘后再处理，或由你人工处理该位置')
    if shell.nuke_on_delete(root):
        raise RuntimeError(f'该磁盘的回收站设置为“直接删除”，拒绝操作: {root}；在桌面右键“回收站 → 属性”，为该磁盘选“自定义大小”而不是“不将文件移到回收站”，然后重试')
    code, aborted = shell.delete_to_recycle_bin(path)
    if code != 0:
        raise RuntimeError(f'移入回收站失败（SHFileOperation 代码 {code:#x}）: {path}')
    if aborted:
        raise RuntimeError(f'移入回收站被取消，目标未处理: {path}；如果你在确认框里选了“否”，这是预期结果，目标保持原样')
    if common.exists(path):
        raise RuntimeError(f'回收站操作返回后目标仍存在: {path}')
