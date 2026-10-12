# 首次准备：环境、权限与执行位置

## 1. 准备独立终端和依赖

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
| macOS | 实际检查、备份和清理 | Windows/Linux 不运行清理；Linux CI 仅验证可移植逻辑 |
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

检查退出码时，紧接上一条命令运行 `echo $?`：扫描 0=无命中、1=有命中需审阅、2=失败；其他非零异常同样按失败处理。备份/恢复/清理成功为 0。不要将“有命中”直接当作删除授权，也不要整段粘贴跨越错误继续清理。
