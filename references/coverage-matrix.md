# 覆盖范围与边界

本表定义自动检查的实际范围，不代表全机取证。无法读取支持范围内的文件时退出 2；不存在的可选路径可以报告不存在，不能把权限错误当作不存在。

| 层 | 自动检查范围 | 自动修改范围 |
| --- | --- | --- |
| 进程 | Chrome/Beta/Canary、Edge、Brave、Vivaldi、Chromium、Arc、Safari；修改还检查 Claude、Code、Cursor、Windsurf，包括应用路径和 helper | 不终止进程，要求用户退出 |
| 客户端 | `.claude.json`、Claude/Claude-3p App Support、plist、Caches、HTTPStorages、Logs、Saved State、`.config/claude`、`.anthropic` | 具体批准路径移入废纸篓，必须有备份 |
| CLI 痕迹 | `.claude` 中 projects、history.jsonl、sessions、tasks、teams、shell-snapshots、session-env、file-history、paste-cache、.cc-writes、plans、debug、backups、cache、image-cache、uploads、dev-mods、usage-data、feedback、feedback-bundles、stats-cache.json、remote-settings.json、policy-limits.json(.stamp.json)、旧版 todos/statsig/logs | 同上；`projects/<项目>/memory/` 是自动记忆，处理 projects 会一并移走，预览会提示 |
| 自有资产 | `.claude` 中 skills、agents、hooks、plugins、settings*.json、.credentials.json、CLAUDE.md、keybindings.json、themes、rules、commands、output-styles、workflows、agent-memory、jobs、daemon | 默认保留；整个 `.claude` 需明确授权 |
| 未归类 | `.claude` 中不属于上两类的顶层名称（例如第三方工具文件），只列名称不读内容 | 不自动处理；检测报告 `unclassified_items` 列出供人工确认 |
| Chromium | 支持的全部浏览器根下 Default、Profile 开头或具有 Preferences/Cookies/History/Network 标记的目录，递归全部普通文件；根下 Local State | SQLite 文本中的服务域名；Local Storage LevelDB key 中的服务域名 |
| Safari | History.db、RecentlyClosedTabs.plist、Downloads.plist | 无自动精删；已确认文件可备份后移入废纸篓 |
| HTTP 缓存 | `--deep` 加 Chrome HTTP 缓存，不宣称其他浏览器缓存已检查 | 具体批准路径 |
| 编辑器 | VS Code/Cursor/Windsurf 扩展名称；对应 settings.json、globalStorage/state.vscdb 内容关键词 | 不自动编辑配置或扩展注册表 |
| 系统指定目录 | 用户与系统 DiagnosticReports；家目录 Applications、.Trash；用户 Containers、Group Containers、Application Scripts 的名称 | 家目录下明确目标；系统只允许 `/Applications/Claude.app` 及指定名称的系统诊断文件 |
| Shell | 5 个用户 rc 文件的静态赋值/alias 行，以及当前进程环境变量名称 | 不运行 rc、不自动改 shell 配置 |

痕迹与资产的划分依据 Claude Code 官方文档 [Application data](https://code.claude.com/docs/en/claude-directory#application-data)：其中列为会话产生、可删除的归为痕迹；列为用户配置或“State files to keep”的归为资产。

## 环境检测入口

`check_environment.py` 是单独的只读准备入口：常见安装路径、工具可执行路径、部分本地数据/配置和进程数量；不做浏览器数据扫描。仅找到候选路径不保证安装完整；不读取凭证内容，不执行 Claude，不联网或改环境。检测范围和退出码见 [环境检测与配置](environment-check.md)。

## 不在自动检查范围

钥匙串、LaunchServices 注册、APFS/Time Machine 快照、系统应用近期列表、任意项目目录、npm 缓存、其他用户、外置盘、登录 shell 动态行为。针对这些内容，需要另行确认范围和人工检查，不得依赖本脚本退出码表示已处理。

## 备份范围

默认备份 `backup.py` 的 CORE 清单（含 `.claude` 自有资产、客户端配置/缓存/日志及 shell rc）。浏览器 profile、应用本体、其他目标需 `--include`；实际清理必须验证目标和当前数据由该备份覆盖。

## 路径移动边界

仅允许家目录内的明确子路径、`/Applications/Claude.app`、`/Library/Logs/DiagnosticReports` 下 Claude/Anthropic 名称的具体文件。拒绝家目录、Library 常用容器、Desktop/Documents/Downloads 等顶层目录、`.ssh`、`.Trash` 及其中内容、系统任意路径、`..`、符号链接。需要处理不支持位置时停止并说明，不能改用强制删除。

移动到废纸篓不会擦除物理字节；数据库逻辑删除和 VACUUM 也不构成物理擦除保证。保留的备份、快照及服务端数据不因本地操作消失。
