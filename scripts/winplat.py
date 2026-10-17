"""Windows-only helpers: registry reads. Imported lazily, never on macOS.

Only value *names* are read from the environment key, never values, and only
display names from uninstall entries. Missing keys or values are reported as
errors unless the caller documents them as optional.
"""
from pathlib import Path

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
