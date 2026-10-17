# 首次准备：环境、权限与执行位置

第 1–4 节是 macOS，第 5 节是 Windows。两边的规则相同：先只读检测，写入前退出相关应用，在独立终端执行，错误就停。

## 1. 准备独立终端和依赖（macOS）

在 Mac 的“应用程序 → 实用工具 → 终端”（Terminal）打开一个窗口，也可用独立的 iTerm。准备与检查不要求退出 Claude；到备份、修改及最终验收时，再按下节退出相关应用。不要在 Claude Code、VS Code、Cursor 或 Windsurf 的内置终端里安排整个重置过程。

逐条执行：

```bash
sw_vers
python3 --version
python3 -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10+"; print("Python 版本符合要求")'
git --version
command -v ditto
command -v osascript
```

| 依赖 | 用途 | 缺少时 |
| --- | --- | --- |
| macOS | 实际检查、备份和清理 | Windows 见第 5 节；Linux 不运行清理，Linux CI 仅验证可移植逻辑 |
| Python 3.10+ | Python 脚本，运行只用标准库 | 从 [Python 官方 macOS 下载页](https://www.python.org/downloads/macos/) 安装；重新打开独立终端核对版本 |
| Git | 下载仓库 | 按 [Git 官方 macOS 安装说明](https://git-scm.com/install/mac) 准备；macOS 可能提示安装开发者命令行工具 |
| Bash、ditto、osascript、Finder | 包装命令、复制及废纸篓移动 | 使用系统自带组件；缺少时停止并检查系统环境 |
| Node.js 18+、npm（可选） | 仅 LevelDB 清理 | 从 [Node.js 官方下载页](https://nodejs.org/en/download) 安装受支持的 LTS 版本，再运行 `node --version`、`npm --version` |

LevelDB 还需在实际执行脚本的 skill 目录运行 `npm ci`；不要只在另一个源码副本安装。Python 的 PyYAML 仅开发检查需要，普通使用无需安装开发依赖。依赖安装失败就处理该依赖，不换数据库实现或跳过失败继续。

## 2. 区分“装在哪里”和“在哪里执行”

| 使用方式 | 能做什么 | 修改阶段怎么交接 |
| --- | --- | --- |
| Codex skill | 帮助查看规则、检查及制定清单 | 只要相关应用仍运行，写入也会拒绝；准备好清单后在独立终端操作 |
| Claude Code skill（`--client claude`） | 在 Claude Code 会话里帮助理解和准备步骤 | 必须退出 Claude Code 自身；用独立终端运行已确认的命令 |
| Claude Desktop | 是本工具可检查的对象 | 安装器的 `--client claude` 指 Claude Code 的本地 skill 目录，不是向 Desktop 导入技能 |
| 直接用脚本 | 无需安装到任何 Agent | 从下载的仓库根目录执行即可 |

备份、实际清理、恢复和最终验收前，保存工作并正常退出 Claude Desktop、所有 Claude Code 会话、支持的浏览器和 Code/Cursor/Windsurf。关闭一个窗口不一定是退出应用；可用应用菜单“退出”或 ⌘Q。脚本不会替你结束进程；仍有进程就停止。不要绕过检查，也不要为了完成本任务中断尚未保存的工作。

保留一份位于清理范围之外的源码，例如 `~/Developer/claude-client-full-reset`。若准备移走整个 `~/.claude`，不能继续从其中安装的 skill 运行；先在独立源码目录准备并操作。整个 `.claude` 含技能和个人配置，必须另行明确授权。

## 3. macOS 首次权限

权限授予的是执行命令的宿主应用（如 Terminal/iTerm），不是远端 GitHub 仓库。仅授权当前明确需要的宿主和范围；安装本 skill 不会替你修改系统权限。

- **读取文件失败**：先核对报错路径与文件归属。在“系统设置 → 隐私与安全性 → 文件与文件夹”检查该宿主对应的访问许可。Safari、废纸篓等受保护位置仍被系统拒绝且你确实要检查时，审阅“完全磁盘访问权限”，按需要给该宿主授权。具体权限名称和弹窗依系统版本而异；受管理的 Mac 可能需管理员处理。不要把所有权限失败都当作需要完全磁盘权限。参见 [Apple 文件访问控制说明](https://support.apple.com/guide/security/controlling-app-access-to-files-secddd1d86a6/web)。
- **Finder 控制被拒绝**：实际 `--apply` 移动时可能出现宿主请求控制 Finder 的弹窗。核对宿主与操作后决定是否允许；此前拒绝过可在“隐私与安全性 → 自动化”查看宿主下的 Finder。尚未提出请求时，该项可能未出现。参见 [Apple 自动化权限说明](https://support.apple.com/en-au/guide/mac-help/mchl07817563/mac)。
- **授权后系统要求重开宿主**：先保存该宿主里的任务，再自行重开它并重新检查；不必为此重启整台 Mac。不要由 Agent 擅自关闭你正在使用的软件。

不要改用 `sudo`、永久删除、重置整套隐私权限或忽略退出码来通过检查。本工具不需要辅助功能、录屏权限来执行其 Finder AppleScript。权限变更不会自动重试失败操作；重新确认已完成目标和备份后再决定剩余范围。

## 4. 找到路径再操作

在仓库/skill 根目录执行 `pwd`，确认当前目录内有 `SKILL.md` 和 `scripts`。路径含空格时必须加引号。

先用 Finder“前往 → 前往文件夹”查看候选位置，例如：

```text
~/Library/Application Support/Google/Chrome/
```

也可在准备阶段从 Chrome 的 `chrome://version` 查看 **Profile Path**，记录后退出浏览器，再执行扫描。目录可能是 `Default`、`Profile 1` 或其他实际名称，界面里的个人资料昵称不等于目录名。其他浏览器按自身路径确认；不在工具支持的默认根目录内的自定义位置，不宣称已覆盖。参见 [Chromium 用户数据目录说明](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/user_data_dir.md)。

`backup.sh` 成功会打印 `[OK] 备份与源数据一致: /完整路径/Claude-Reset-Backup-...`。默认父目录是用户家目录。把完整路径记录下来；不要选择一个没有 `manifest.json` 的失败目录，不要把备份放进待清理目标内，也不要上传含凭证的备份。

检查退出码时，紧接上一条命令运行 `echo $?`：痕迹扫描 0=无命中、1=有命中或相关进程需审阅、2=失败；环境检测 1 则表示异常或基础依赖待处理。其他非零异常同样按失败处理。备份/恢复/清理成功为 0；SQL/LevelDB 预览的匹配数需另读输出。完整规则见 [执行手册](agent-runbook.md)。不要将“有命中”直接当作删除授权，也不要整段粘贴跨越错误继续清理。

## 5. Windows 首次准备

### 5.1 终端与依赖

在开始菜单打开 **Windows Terminal** 或 **Windows PowerShell**，不要在 Claude Code、VS Code、Cursor 或 Windsurf 的内置终端里安排整个重置过程。**不需要也不要用“以管理员身份运行”**：工具只处理当前用户的数据。

逐条执行：

```powershell
[Environment]::OSVersion.Version
py -3 --version
py -3 -c "import sys; assert sys.version_info >= (3, 10), '需要 Python 3.10+'; print('Python 版本符合要求')"
git --version
```

| 依赖 | 用途 | 缺少时 |
| --- | --- | --- |
| Windows 10 1809+ / 11 | 检查、备份和清理 | 更早版本未测试，不要使用 |
| Python 3.10+ 与 `py` 启动器 | 所有入口 | 从 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/) 安装（默认勾选 py launcher），或 `winget install Python.Python.3.12`；重新打开终端核对 |
| Windows PowerShell | 查询进程（工具调用系统自带的 `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`） | 系统自带；缺少时停止并检查系统 |
| Git | 下载仓库 | [Git for Windows](https://git-scm.com/downloads/win)；它也提供 Claude Code 可选使用的 Git Bash |
| Node.js 18+、npm（可选） | 仅 LevelDB 清理 | [Node.js 官方下载页](https://nodejs.org/en/download)；`node --version`、`npm --version` 核对 |

`scripts\*.sh` 只是 macOS 的包装，Windows 一律用 `py -3 scripts\<入口>.py`。`ls_purge.js` 默认用 `py -3` 调用 Python；用的是其他解释器时，先设置 `$env:CLAUDE_RESET_PYTHON = "C:\完整路径\python.exe"`，找不到解释器会报错停止，不会改用别的名字。

### 5.2 退出相关应用

备份、实际清理、恢复和最终验收前，保存工作并正常退出：Claude Desktop（**包括通知区域/托盘图标里的“退出”**，只关窗口不算）、所有 Claude Code 会话、Chrome/Edge/Brave/Vivaldi/Firefox、Code/Cursor/Windsurf。

Edge 默认可能在关闭窗口后仍在后台运行。工具发现 `msedge.exe` 仍在时会拒绝写入；请在 Edge 设置“系统和性能”里关闭“启动增强”和“关闭 Microsoft Edge 后继续运行后台扩展和应用”，再退出 Edge，或由你自己在任务管理器确认后结束。工具不会替你结束进程。

### 5.3 Windows 权限与安全设置

- **读取被拒绝**：先核对报错路径和文件归属；企业管理的电脑可能限制访问。不要为此改用管理员身份或修改文件权限。
- **受控文件夹访问（Windows 安全中心 → 病毒和威胁防护 → 勒索软件防护）**：开启时，写入受保护文件夹可能被拦截并弹出通知。按通知确认被拦截的是哪个程序和路径；是否放行由你决定，工具不会修改安全设置，失败就停止。
- **回收站**：工具只把目标移入**本地固定磁盘**的回收站。U 盘、网络盘，或回收站被设为“不将文件移到回收站，直接删除”的磁盘会被拒绝；万一系统弹出“永久删除”的确认框，请选 **否**，工具会报错停止，不会改用永久删除。
- **OneDrive**：“文档”等文件夹被 OneDrive 接管时，按需下载的占位文件和 junction 属于重解析点，工具一律拒绝读取或移动，需要先人工处理。

### 5.4 找到路径再操作

在仓库/skill 根目录执行 `Get-Location`，确认能看到 `SKILL.md` 和 `scripts`。路径含空格时用引号。

常用位置（在文件资源管理器地址栏粘贴即可打开）：

```text
%USERPROFILE%\.claude
%APPDATA%\Claude
%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude
%LOCALAPPDATA%\Google\Chrome\User Data
%LOCALAPPDATA%\Microsoft\Edge\User Data
%APPDATA%\Mozilla\Firefox\Profiles
```

从官网下载的 Claude Desktop 是 MSIX 包，实际配置和日志在 `Packages\Claude_…\LocalCache\Roaming\Claude`，而不是 `%APPDATA%\Claude`；工具两处都检查。浏览器 profile 目录名可在 `chrome://version` 或 `edge://version` 的“个人资料路径”看到。

`backup.py` 成功会打印 `[OK] 备份与源数据一致: C:\...\Claude-Reset-Backup-...`，默认放在用户目录（`%USERPROFILE%`）下。Windows 不能用 `chmod` 限制访问，备份的保密性依赖用户目录本身的权限；放到用户目录之外时工具会提示。

PowerShell 里紧接上一条命令运行 `$LASTEXITCODE` 查看退出码，含义与 macOS 相同，见 [执行手册](agent-runbook.md)。
