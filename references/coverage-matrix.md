# 覆盖范围与边界

本表定义自动检查的实际范围，不代表全机取证。无法读取支持范围内的文件时退出 2；不存在的可选路径可以报告不存在，不能把权限错误当作不存在。`.claude` 的痕迹/资产划分两个平台相同；第一张表是 macOS，[Windows](#windows) 见后。

| 层 | 自动检查范围（macOS） | 自动修改范围 |
| --- | --- | --- |
| 进程 | Chrome/Beta/Canary、Edge、Brave、Vivaldi、Chromium、Arc、Safari、Firefox；修改还检查 Claude、Code、Cursor、Windsurf，包括应用本体和 helper；`.app` 内独立运行的扩展（Contents/Extensions、PlugIns）和 XPC 服务不算应用在运行 | 不终止进程，要求用户退出 |
| 客户端 | `.claude.json`、Claude/Claude-3p App Support、plist、Caches、HTTPStorages、Logs、Saved State、`.config/claude`、`.anthropic` | 具体批准路径移入废纸篓，必须有备份 |
| 安装 | `/Applications/Claude.app`、`~/Applications/Claude.app`、PATH 与常见位置的 `claude`、`~/.local/share/claude` 版本目录 | 应用本体可按明确路径移入废纸篓；版本目录在家目录内，需 `--include` 备份 |
| 凭证 | 钥匙串项 `Claude Code-credentials`（只查是否存在）、`.claude/.credentials.json`、`~/.config/anthropic` | 不自动处理；只报告存在与否 |
| 标识 | `identifiers.py`：`.claude.json` 的 userID / machineID / 账号与组织 UUID / 邮箱 / 首启时间；`Application Support/Claude` 的 `ant-did`、`ant-device-registry.json`、`ccd-ids.json` 盐、`config.json` 账号与首启、Sentry user/did/sid、Local Storage / Session Storage / IndexedDB 目录、Cookies、Cowork VM `machineIdentifier`；钥匙串只查存在 | 不改任何 ID；只记指纹；清理前后 `--compare` 证明已变（[标识清单](identifiers.md)） |
| CLI 痕迹 | `.claude` 中 projects、history.jsonl、sessions、tasks、teams、shell-snapshots、session-env、file-history、paste-cache、.cc-writes、plans、debug、backups、cache、image-cache、uploads、dev-mods、usage-data、feedback、feedback-bundles、stats-cache.json、remote-settings.json、policy-limits.json(.stamp.json)、旧版 todos/statsig/logs | 同上；`projects/<项目>/memory/` 是自动记忆，处理 projects 会一并移走，预览会提示 |
| 自有资产 | `.claude` 中 skills、agents、hooks、plugins、settings*.json、.credentials.json、CLAUDE.md、keybindings.json、themes、rules、commands、output-styles、workflows、agent-memory、jobs、daemon | 默认保留；整个 `.claude` 需明确授权 |
| 未归类 | `.claude` 中不属于上两类的顶层名称（例如第三方工具文件），只列名称不读内容 | 不自动处理；检测报告 `unclassified_items` 列出供人工确认 |
| Chromium | 支持的全部浏览器根下 Default、Profile 开头或具有 Preferences/Cookies/History/Network 标记的目录，递归全部普通文件；根下 Local State | SQLite 文本中的服务域名（`claude.ai`、`claude.com`、`anthropic.com`、`claudeusercontent.com`、`claudemcpcontent.com` 及子域）；Local Storage LevelDB key 中的服务域名 |
| Safari | History.db、RecentlyClosedTabs.plist、Downloads.plist | 无自动精删；已确认文件可备份后移入废纸篓 |
| Firefox | Profiles 下各 profile 的 places/cookies/webappsstore/formhistory.sqlite（快照查询）及 storage/default 中 `claude.ai`、`claude.com`、`anthropic.com`、`claudeusercontent.com`、`claudemcpcontent.com` 站点目录名 | 只读扫描，无自动精删；具体文件需单独评估并备份 |
| 监测与分流 | `telemetry_routing.py` 检查 `.claude/settings.json` 遥测/上报开关、第三方网关键名，以及本地 Clash/Mihomo 配置中的域名、CDN、遥测/第三方 `REJECT` 与 `claude.ai` 进程兜底（`PROCESS-NAME`） | `--apply` 备份后仅补充缺失项（已有项不覆盖），并输出增量/完整 Clash 规则文件；详见 [监测与分流说明](telemetry-and-routing.md) |
| HTTP 缓存 | `--deep` 加 Chrome HTTP 缓存，不宣称其他浏览器缓存已检查 | 具体批准路径 |
| 编辑器 | VS Code/Cursor/Windsurf 扩展名称；对应 settings.json、globalStorage/state.vscdb 内容关键词 | 不自动编辑配置或扩展注册表 |
| 系统指定目录 | 用户与系统 DiagnosticReports；家目录 Applications、.Trash；用户 Containers、Group Containers、Application Scripts 的名称 | 家目录下明确目标；系统只允许 `/Applications/Claude.app` 及指定名称的系统诊断文件 |
| Shell | 5 个用户 rc 文件的静态赋值/alias 行，以及当前进程环境变量名称 | 不运行 rc、不自动改 shell 配置 |

## Windows

| 层 | 自动检查范围（Windows） | 自动修改范围 |
| --- | --- | --- |
| 进程 | 通过系统 PowerShell 的 `Get-CimInstance Win32_Process` 按进程名匹配：chrome.exe（含 Beta/Canary/Chromium）、msedge.exe、brave.exe、vivaldi.exe、firefox.exe；修改还检查 claude.exe（Desktop 与 CLI）、运行 `@anthropic-ai/claude-code` 的 node.exe、Code/Cursor/Windsurf.exe | 不终止进程，要求用户退出（含托盘和后台 Edge） |
| 客户端 | `%USERPROFILE%\.claude.json`、`%APPDATA%\Claude`、`%APPDATA%\Claude-3p`、MSIX 包内 `LocalCache\Roaming\Claude(-3p)`（每个 `Claude_*` 包单独备份）、`%LOCALAPPDATA%\claude-cli-nodejs`、`.config\claude`、`.anthropic` | 具体批准路径移入回收站，必须有备份 |
| 安装 | MSIX 包目录 `Claude_*`、`%LOCALAPPDATA%\AnthropicClaude`、`claude.exe`/`claude.cmd`（PATHEXT）、WinGet 链接、`%USERPROFILE%\.local\share\claude`、卸载项显示名称 | MSIX 应用本体（`WindowsApps`）和包根目录不处理，用系统“设置 → 应用”卸载 |
| 凭证 | `%USERPROFILE%\.claude\.credentials.json`、`%APPDATA%\Anthropic` | 不自动处理；只报告存在与否 |
| 标识 | 同 macOS，桌面端路径为 `%APPDATA%\Claude` 与 MSIX `…\LocalCache\Roaming\Claude`（id 带 `@msix`）；`.credentials.json` 记文件指纹 | 同 macOS |
| Chromium | `%LOCALAPPDATA%` 下 Chrome、Chrome Beta、Chrome SxS（Canary）、Edge、Brave、Vivaldi、Chromium 的 `User Data`；profile 规则同 macOS；HTTP 缓存在 profile 内，默认扫描已包含 | 同 macOS |
| Firefox | `%APPDATA%\Mozilla\Firefox\Profiles`，规则同 macOS | 只读扫描 |
| 编辑器 | `.vscode`/`.cursor`/`.windsurf` 扩展名称；`%APPDATA%\Code|Cursor|Windsurf\User` 的 settings.json、state.vscdb 关键词 | 不自动编辑 |
| 系统指定目录 | `%LOCALAPPDATA%\CrashDumps`、开始菜单 `Programs` 中含 Claude/Anthropic 的名称 | 家目录下明确目标 |
| Shell 与环境 | Git Bash 的 `.bashrc`/`.bash_profile`/`.profile`；“文档”文件夹（可能被 OneDrive 重定向）下 PowerShell 与 Windows PowerShell 的 profile；`$env:` 赋值、`Set-Alias claude`、`SetEnvironmentVariable`；当前进程与 `HKCU\Environment` 中的变量**名称** | 不运行、不修改；不读变量值 |

Windows 不覆盖：Arc、Safari、凭据管理器、注册表其他位置、卷影副本/系统还原、回收站内容、WSL 内数据、其他用户、外置盘、任意项目目录、npm 缓存。

痕迹与资产的划分依据 Claude Code 官方文档 [Application data](https://code.claude.com/docs/en/claude-directory#application-data)：其中列为会话产生、可删除的归为痕迹；列为用户配置或“State files to keep”的归为资产。

## 环境检测入口

`check_environment.py` 是单独的只读准备入口：常见安装路径、工具可执行路径、部分本地数据/配置和进程数量；不做浏览器数据扫描。仅找到候选路径不保证安装完整；不读取凭证内容，不执行 Claude，不联网或改环境。检测范围和退出码见 [环境检测与配置](environment-check.md)。

## 不在自动检查范围

macOS：钥匙串内容（只查 Claude Code 凭证项是否存在）、LaunchServices 注册、APFS/Time Machine 快照、系统应用近期列表、任意项目目录、npm 缓存、其他用户、外置盘、登录 shell 动态行为。Windows 见上节。两个平台都不覆盖：设置了 `CLAUDE_CONFIG_DIR` 时的自定义配置目录、Claude Code 临时目录中的粘贴图片和 scratchpad。针对这些内容，需要另行确认范围和人工检查，不得依赖本脚本退出码表示已处理。

## 备份范围

默认备份 `backup.py` 的 CORE 清单（含 `.claude` 自有资产、客户端配置/缓存/日志及 shell rc；Windows 含 PowerShell profile 与 MSIX 包内 Claude 数据）。备份记录平台，跨平台校验或恢复会被拒绝。浏览器 profile、应用本体、其他目标需 `--include`；实际清理必须验证目标和当前数据由该备份覆盖。

## 路径移动边界

macOS 仅允许家目录内的明确子路径、`/Applications/Claude.app`、`/Library/Logs/DiagnosticReports` 下 Claude/Anthropic 名称的具体文件。拒绝家目录、Library 常用容器、Desktop/Documents/Downloads 等顶层目录、`.ssh`、`.Trash` 及其中内容、系统任意路径、`..`、符号链接。需要处理不支持位置时停止并说明，不能改用强制删除。

Windows 仅允许用户目录内的明确子路径，并且：只接受本地盘符路径（拒绝 UNC、`\\?\`、`\\.\`）；符号链接、junction 和其他重解析点（含 OneDrive 占位文件）一律拒绝；拒绝 AppData、AppData\Local/Roaming/LocalLow、Packages、Programs、真实的“文档”文件夹、OneDrive、桌面/下载等顶层目录及 `.ssh` 内容；`Packages` 下只允许 `Claude_*\LocalCache\Roaming\Claude(-3p)` 及其子路径。只移入本地固定磁盘的回收站，回收站设为直接删除的磁盘会被拒绝。

移动到废纸篓不会擦除物理字节；数据库逻辑删除和 VACUUM 也不构成物理擦除保证。保留的备份、快照及服务端数据不因本地操作消失。
