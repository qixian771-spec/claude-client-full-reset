# 环境检测与分场景配置

本功能用于先判断常见位置的安装与依赖情况，再决定准备、保留还是审阅残留。**它不是账号检测、封禁诊断或新设备认证。** 安装和本地数据都未发现，也不能证明从未使用过网页、其他客户端或其他账号。

## 检测入口

检测器本身需要 Python 3.10+，未安装 Python 时先按 [首次准备](first-run.md) 准备。下载源码或安装 skill 后，在其根目录运行：

```bash
python3 scripts/check_environment.py
```

需要交给其他工具处理时可使用 JSON：

```bash
python3 scripts/check_environment.py --json
```

Windows 在 PowerShell 中运行：

```powershell
py -3 scripts\check_environment.py --json
```

不会启动 Claude、运行 `claude --version`、登录、联网、安装软件、写配置或结束进程。只查询路径、文件属性及进程数量，不读 cookie、token、凭证文件内容或 shell 配置；进程参数不输出。macOS 另用 `security find-generic-password -s "Claude Code-credentials"`（不带 `-w`/`-g`，不返回密码、不弹授权框，输出丢弃）只判断钥匙串项是否存在；Windows 只读注册表中的卸载项显示名称。**检测期间无需退出 Claude 或浏览器。** 它只为后续准备提供依据，不能取代备份、清理前的退出检查。

| 报告状态 | 意义 | 下一步 |
| --- | --- | --- |
| `not_detected` | 常见位置未发现安装或所列本地数据 | 仅检测则报告并结束；明确要求配置才按首次安装清单准备，不先做重置/备份/清理 |
| `installed` | 找到 Desktop 目录或可执行 CLI 路径 | 保留已有环境，核对要解决的具体问题；未启动确认安装完整性 |
| `local_data_only` | 未发现安装，找到配置或数据 | 可能是卸载残留或手工配置；先审阅，不能自动删除 |
| `needs_review` | 损坏链接、不可执行路径、运行进程或系统登记与常见路径不一致、有 Claude Code 版本目录却没有启动器、多个 Claude MSIX 包目录、设置了 `CLAUDE_CONFIG_DIR` | 先查清异常，不自动安装、换源或清理 |

检测退出码与扫描不同：**0=本次检测完成且未发现基础准备问题，不表示从未用过或无数据；1=有异常或基础依赖待处理；2=检测失败。** JSON 模式失败时不输出一份貌似成功的报告，错误写到 stderr。任何其他非零异常同样停止。缺少可选 Node/npm 不妨碍基础检查；损坏的可选工具路径仍会提示审阅。

检查范围（macOS）：`/Applications/Claude.app`、`~/Applications/Claude.app`、PATH 内 `claude` 和 `~/.local/bin/claude`、`/opt/homebrew/bin/claude`、`/usr/local/bin/claude`；`~/.local/share/claude` 版本目录；列明的 Claude 数据/配置路径；Bash/ditto/osascript/Git/Node/npm 是否有可执行路径，以及当前 Python 版本。

检查范围（Windows）：MSIX 包目录 `%LOCALAPPDATA%\Packages\Claude_*` 与旧版 `%LOCALAPPDATA%\AnthropicClaude`；按 `PATHEXT` 在 PATH 中找 `claude.exe`/`claude.cmd`，以及 `%USERPROFILE%\.local\bin\claude.exe`、`%APPDATA%\npm\claude.cmd`、`%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe`；`%USERPROFILE%\.local\share\claude` 版本目录；HKCU/HKLM 卸载项中含 Claude/Anthropic 的显示名称；PowerShell/Git/Node/npm 路径与 Python 版本。

只安装 `~/.claude/skills` 不计作曾使用 Claude。

报告中的附加字段：

| 字段 | 含义 |
| --- | --- |
| `unclassified_items` | `.claude` 中不属于官方痕迹/资产清单的顶层名称（只列名称，不读内容）；不会被自动处理，需要时人工确认 |
| `auto_memory_projects` | `.claude/projects` 中含自动记忆 `memory/` 的项目数；处理 `projects` 会一并移走 |
| `credential_locations` | 钥匙串项、`.credentials.json`、Anthropic profile 目录是否存在；只报存在与否 |
| `cli_install_dirs` | 原生安装器的版本目录；属于程序文件，不进默认备份 |
| `registered_apps` | Windows 卸载项中的 Claude 相关显示名称；macOS 为空 |

非 Python 工具只检查路径，不执行或验证其版本。目录名和可执行标志不能证明软件来源可信、安装完整或能登录。浏览器记录、钥匙串、云端、自定义安装/数据目录、其他用户及终端临时别名未检查；不根据检测结果修改系统网络或权限。

## 首次安装清单：没有使用过的人

先选择要用的产品，避免为 Desktop 额外安装 CLI：

| 目标 | 配置步骤 | 不需要做什么 |
| --- | --- | --- |
| Claude Desktop | 查看官方系统要求；从 [官方下载页](https://claude.com/download) 下载 macOS 安装包，按 [Desktop 安装说明](https://support.claude.com/en/articles/10065433-install-claude-desktop) 安装到应用程序目录；用户准备好后自行启动和登录 | 不因使用 Desktop 而安装 Node、Claude CLI 或重置 skill |
| Claude Code 命令行 | 按 [官方安装说明](https://code.claude.com/docs/en/setup) 选择并执行一种安装方式；安装完重新打开终端，按该说明核对 PATH 与版本；用户准备好后再登录 | 不用本工具自动执行远程安装脚本；失败不自动切换来源或旧包 |
| Claude Desktop（Windows） | 从 [官方下载页](https://claude.com/download) 下载 Windows 安装包（MSIX），按提示安装；配置与日志在 `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\Claude` | 不手动改 `WindowsApps` 下的程序文件 |
| Claude Code（Windows） | 官方说明提供 PowerShell 原生安装、CMD 安装与 `winget install Anthropic.ClaudeCode` 三种方式，任选一种；Git for Windows 可选（提供 Bash 工具），不装时 Claude Code 使用 PowerShell 工具 | 不需要管理员身份；不因为本工具而安装 WSL |
| 只使用本 skill 检查 | 准备 Python；从源码运行检测；有需要才安装到 Agent | 不必先安装 Claude，不必安装 LevelDB 依赖 |

核对区分：Python/Git 是下载及运行本工具相关依赖；Node/npm 是本工具 LevelDB 功能相关依赖，不应把这张依赖表当作 Claude Desktop 的安装条件。Claude 产品自身的系统、硬件及账号要求以对应官方文档为准。

安装后可再次运行本检测器，核对常见路径变化。要验证真正启动、版本或登录，需要另一步明确执行；本检测器不会代做，也不会因此宣称安装可用或账号正常。

## 已有环境或以前账号出过问题的人

先保留现有环境。按报告检查命令路径、依赖、当前正在运行的应用与本地配置，再区分本地故障和账号提示。需要修正本地安装时，先备份并说明影响；需要清理时，仍按确认清单和 [恢复说明](restore-and-rebuild.md) 处理，禁止检测后自动删数据或覆盖设置。

本工具不读取账号凭证、不查询封禁状态，不改设备标识、伪装身份或声称重置后可以解封。账号无法使用时，应按账号提示和 [官方帮助中心](https://support.claude.com/) 的支持流程处理；本地环境检测可以独立完成，不能替代账号问题处理。

## Agent 协助配置时的交接

先运行只读检测，解释实际缺口和未覆盖项。用户明确要求安装/配置时，核对其选择的是 Desktop、Claude Code 还是仅本 skill，再按对应官方当前说明实施已授权范围。安装或验证失败就停止并报告，不自动更换安装方式、第三方来源或放宽校验。保留个人设置、代理、防火墙和正在运行的软件；需要改变这些时另行说明具体影响，不能从“配置 Claude”推断授权。账号登录由用户操作。

检测报告可用于安排下一步，不是自动重置许可。对未发现本地数据的用户，不应执行 `backup.sh` 制造空备份，更不能编造待清理路径。
