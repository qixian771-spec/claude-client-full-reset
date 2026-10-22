# Claude Client Full Reset

macOS 与 Windows 上 Claude Code / Claude Desktop 环境检测、本地数据检查、备份与清理的 Agent Skill。MIT 开源。

支持本地文件检查、SHA-256 备份校验、移入废纸篓（macOS Finder）或回收站（Windows，仅本地固定磁盘）、SQLite 域名记录和 LevelDB key 清理；Firefox 只读扫描；凭证位置只报告存在与否。**清理默认预览，实际清理必须有校验通过的备份；恢复拒绝覆盖。** 不处理服务端数据，不承诺解除账号限制或物理擦除磁盘。

## 傻瓜式使用：让 AI 带着走

本 skill 面向“由 AI 带着操作”的用户。AI 读 [对话模板](references/conversation.md) 决定每一步说什么、在哪里停下；用户只在少数介入点亲自动手（退出应用、开权限、确认清单、双击交接文件并输入“是”）。

| 工具 | 作用 |
| --- | --- |
| `scripts/preflight.py` | 一条命令列出写入前所有未满足的条件（要退出的应用、权限、备份空间等），全部满足才显示“可以开始” |
| `scripts/identifiers.py` | **标识清单与清理后验证**：列出本机 22 类 Claude 标识（Claude Code 的 userID/machineID/账号 UUID，桌面端的设备 ID、设备注册、Sentry/Segment 遥测 ID、站点存储、Cowork VM 标识……）在哪，只读、只记 SHA-256 指纹；清理前 `--snapshot`、重开应用后 `--compare`，哪个 ID 没换就点名，详见 [标识清单](references/identifiers.md) |
| `scripts/handover.py` | AI 按确认的清单生成双击运行的交接文件（macOS `.command`，Windows `.cmd`）：前提自检 → 预览 → 输入“是” → 备份 → 校验 → 移入废纸篓/回收站 → 验收；不确认就什么都不写，失败即停，结果写入日志供 AI 读取 |
| `scripts/telemetry_routing.py` | **给 AI 直接调用的傻瓜式一键补齐工具**：自动检测并补齐 **监测与上报（遥测）、域名、CDN、分流规则（含 IP/ASN/NTP）、第三方、claude.ai 进程兜底**（已有设置与规则不覆盖，自动备份后只补缺失项；支持 `--apply --auto-patch-proxy` 一键注入本机代理配置并导出 Clash/Surge/sing-box 四种格式），详见 [监测与分流说明](references/telemetry-and-routing.md) |
| 报错里的 `[下一步]` | 常见失败（应用在运行、macOS 隐私权限、回收站拒绝等）同时给出原因和具体下一步 |

## 交给其他 AI 执行

入口是 [SKILL.md](SKILL.md)，详细编排是 [AI 执行手册](references/agent-runbook.md)：任务输入 → 检测与路线选择 → 任务卡 → 分支执行 → 结果判断 → 验收交付。手册逐步列出前提、命令、停止条件和 14 个路线自查例子，避免把“检查、配置、清理、恢复”机械地从头跑到尾。

可直接要求 AI：

> 阅读 SKILL.md 和 references/agent-runbook.md，先提取我的目标、限制和已有授权，完成只读检测后选正确路线；列出任务卡再执行，不自动扩大范围，失败停止并保留证据。

## 首次准备

需要 macOS 或 Windows 10/11、Python 3.10+、Git；仅 LevelDB 功能另需 Node.js 18+ 和 npm。先阅读 [首次准备](references/first-run.md)：依赖下载、终端选择、系统权限和浏览器路径定位均在其中（Windows 见第 5 节）。

**安装 skill 不等于能在 Claude 自己的会话内重置自己。** `--client claude` 安装到 Claude Code 的 skill 目录，Claude Desktop 是可清理对象，不是这个安装选项的技能宿主。Agent 可帮助准备清单；备份、写入、恢复和最终验收前，需保存工作并退出相关应用，在独立终端（macOS Terminal/iTerm，Windows Terminal/PowerShell）执行。不能跳过进程检查。

## 下载与安装

在独立终端逐条执行。源码目录应在待清理范围之外：

```bash
mkdir -p "$HOME/Developer"
cd "$HOME/Developer"
git clone https://github.com/qixian771-spec/claude-client-full-reset.git
cd claude-client-full-reset
python3 --version
```

想让 Agent 识别技能时，按自己的客户端**任选一条**；只用脚本可跳过安装，直接在源码目录操作。

```bash
python3 tools/install.py --client codex
```

或 Claude Code：

```bash
python3 tools/install.py --client claude
```

安装器分别复制到 `~/.codex/skills/claude-client-full-reset`（遵循显式配置的 `CODEX_HOME`）或 `~/.claude/skills/claude-client-full-reset`。已有安装会报错，不合并覆盖；升级需先审阅并移走旧安装再安装。自定义完整目录使用 `--dest /absolute/skill-directory`。安装后可在方便时重新加载客户端确认技能；不要因此中断正在执行的任务。

可以要求 Agent：

> 使用 claude-client-full-reset，先阅读规则并准备只读检查步骤，不执行清理。若当前宿主需要退出，把后续步骤交给独立终端，不绕过保护。

Codex 可显式使用 `$claude-client-full-reset`。依赖和权限准备见 [首次准备](references/first-run.md)。只有使用 LevelDB 时，才在**实际运行脚本的目录**执行：

```bash
node --version
npm --version
npm ci
```

如果从安装目录运行，就在安装目录装依赖；如果从本次下载的源码运行，就在源码目录装依赖。

Windows 在 PowerShell 中下载与安装（不需要管理员身份）：

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\Developer" | Out-Null
Set-Location "$env:USERPROFILE\Developer"
git clone https://github.com/qixian771-spec/claude-client-full-reset.git
Set-Location claude-client-full-reset
py -3 --version
py -3 tools\install.py --client claude
```

## 不确定是否装过？先做环境检测

在下载的源码或已安装 skill 根目录运行；可以保持现有软件运行：

```bash
python3 scripts/check_environment.py
# 需要结构化报告时：
python3 scripts/check_environment.py --json
```

Windows：`py -3 scripts\check_environment.py --json`。

只查常见安装路径、依赖路径、本地数据/配置位置和进程数量；不启动 Claude、不联网、不安装或修改环境。仅装这个 skill 不会被计作 Claude 使用记录。报告还会列出 `.claude` 中未归类的名称、含自动记忆的项目数、凭证位置是否存在；设置了 `CLAUDE_CONFIG_DIR` 时会提示默认范围不完整。

报告区分未发现、发现安装候选、只有本地数据和需审阅异常，并给出下一步。没有本地数据的人直接按 [首次安装清单](references/environment-check.md) 准备，无需先清理；已有环境的人先保留配置。权限或查询失败返回错误，不能当成“从没用过”。

环境检测 0=完成且无基础准备问题，1=异常/基础依赖待处理，2=检测失败；0 不代表没有数据、能登录或从未使用。未查浏览器历史、云端、自定义路径等；无法判断账号是否被封，本地重置不能作为解除限制的证明。详见 [环境检测与配置](references/environment-check.md)。

## 从检查到清理

以下命令以源码或 skill 根目录为工作目录。逐步查看结果，不要整段盲目粘贴；报错就停止。`/absolute/...` 是必须替换的占位符，不能原样使用。

### 1. 只读检查

**先正常退出支持的浏览器**，再扫描。浏览器路径和权限准备见 [首次准备](references/first-run.md)。

```bash
bash scripts/scan_readonly.sh
```

扫描退出 0=无命中，1=有命中需审阅，2=检查失败。暂不检查浏览器时可以显式运行 `bash scripts/scan_readonly.sh --no-browser`，但它不是完整检查，也不能作为完整验收。扫描允许报告 Claude 正在运行；后续备份和写入会拒绝运行中的 Claude。

### 2. 确认范围、退出应用并备份

查看 [覆盖矩阵](references/coverage-matrix.md)，逐项确认要处理什么。保存工作，退出 Claude Desktop、所有 Claude Code 会话、支持的浏览器及 Code/Cursor/Windsurf。切换到独立 Terminal/iTerm，保持应用关闭，直至恢复或验收结束。

默认备份含客户端数据、`.claude` 自有资产和 shell 配置；普通客户端数据清理可以直接备份：

```bash
bash scripts/backup.sh
```

如果还要处理浏览器，需在**创建备份时**额外加入已确认的 profile。例如 Chrome 默认 profile（必须确实存在且是本次确认的目标）：

```bash
bash scripts/backup.sh --include "$HOME/Library/Application Support/Google/Chrome/Default"
```

其他非默认目标同样用 `--include`，可重复指定。记录成功输出中的完整备份目录，并验证它：

```bash
python3 scripts/backup.py --verify /absolute/backup-directory
```

### 3. 预览已确认目标，再执行

用扫描结果中已审阅的绝对路径替换占位符。先预览：

```bash
bash scripts/trash_paths.sh --dry-run /absolute/approved/path
```

确认输出与授权清单一致后才执行：

```bash
bash scripts/trash_paths.sh --apply --backup /absolute/backup-directory /absolute/approved/path
```

操作可能影响本地历史和登录状态。没有备份、备份损坏或目标自备份后已变化都会拒绝；每批最多 10 个路径；拒绝符号链接目标和系统保护路径；不清空废纸篓。Finder 授权失败按 [权限说明](references/first-run.md) 处理，不改用永久删除。

浏览器 SQL / LevelDB 的选择和精删命令见 [SKILL.md](SKILL.md) 和 [浏览器规则](references/browser-layer.md)。不能因为一个库失败而扩大为整库或整个 profile 清理。

### 4. 验收

保持相关应用关闭：

```bash
python3 scripts/verify_reset.py
```

`PASS` 只覆盖工具列出的位置；废纸篓、保留的编辑器配置等仍可能被报告，须逐项说明，不为取得 PASS 自动删除。钥匙串、服务端、快照、其他用户、任意项目目录等不在自动验收范围。

### Windows 对照命令

规则与上面完全相同，只是入口和路径写法不同。逐条执行，`C:\absolute\...` 必须替换：

```powershell
py -3 scripts\scan_readonly.py
py -3 scripts\backup.py
py -3 scripts\backup.py --include "$env:LOCALAPPDATA\Google\Chrome\User Data\Default"
py -3 scripts\backup.py --verify C:\absolute\backup-directory
py -3 scripts\trash_paths.py --dry-run C:\absolute\approved\path
py -3 scripts\trash_paths.py --apply --backup C:\absolute\backup-directory C:\absolute\approved\path
py -3 scripts\verify_reset.py
```

Windows 要点：退出托盘里的 Claude 和后台常驻的 Edge；Claude Desktop（MSIX）的数据在 `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\Claude`，包根目录和 `WindowsApps` 不处理；只移入本地固定磁盘的回收站；junction、OneDrive 占位文件、UNC 路径一律拒绝。详见 [首次准备第 5 节](references/first-run.md#5-windows-首次准备) 与 [常见故障](references/pitfalls.md)。

## 局部恢复：只还原需要的原目标

备份可能含凭证，目录权限仅当前用户可访问，不要上传。下面的 `--list` 校验备份后只列原始来源路径，不输出内容。

```bash
python3 scripts/backup.py --list /absolute/backup-directory
```

退出相关应用后，用 `--path` 指定要恢复的原始绝对路径，支持备份来源内的子文件/子目录，可重复指定。**所选目标必须不存在；其他仍存在的配置不影响局部恢复。** 先预检：

```bash
python3 scripts/backup.py --restore /absolute/backup-directory --path /absolute/original/target --dry-run
```

核对计划后执行：

```bash
python3 scripts/backup.py --restore /absolute/backup-directory --path /absolute/original/target
```

例如只移走了 `~/.claude/history.jsonl`，可把 `--path` 后的值写成 `"$HOME/.claude/history.jsonl"`，不用移走仍保留的技能、设置或 `.zshrc`。选错路径、重叠选择、损坏备份都会停止，不会转成整包恢复。

不指定 `--path` 是**整包恢复**，要求全部原目标不存在；部分清理后通常不适用。SQL / LevelDB 修改后的目标仍存在，不能直接覆盖；数据库需保持配套文件一致，具体步骤及中途失败处理见 [恢复说明](references/restore-and-rebuild.md)。

## 错误处理与边界

- 错误必须停止：不切换复制方式，不吞异常，不把无法查询进程当成无进程。
- 全批预检之后按目标执行，不具备跨路径、跨数据库事务；后续失败时前序操作可能已完成。
- SQLite 提交后 VACUUM 失败仍返回错误，已提交删除不会自动撤销。LevelDB 每库原子 batch。
- 恢复在 macOS 使用 `ditto`、在 Windows 使用内置严格复制，并逐项校验；备份带平台标记，不能跨平台使用。失败可能留下不完整目标；保留现场并核查，不能盲目重跑、自动删掉冲突目标或改写备份清单。
- 备份清单是内容校验，不是数字签名，只使用可信本地备份。
- 不输出 cookie/token、环境变量值或 Local Storage key 内容。

## 开发与测试

普通使用不需要执行开发测试。开发者在隔离测试数据上运行：

```bash
python3 -m pip install -r requirements-dev.txt
npm ci
python3 tools/check.py
python3 -m unittest discover -s tests -v
node --test tests/level.test.js
```

GitHub Actions 在 macOS、Windows 和 Linux 运行结构检查与隔离夹具测试；macOS 与 Windows 还在 runner 自己的数据上跑只读 smoke 和浏览器预览，Windows 另有 junction、回收站、注册表、进程查询的原生测试。Linux 只测试可移植逻辑，清理 CLI 仅支持 macOS 与 Windows。测试不会清理真实 Claude / 浏览器数据。

[任务与验收记录](docs/release-tasks.md) · [测试报告](docs/acceptance.md) · [首次准备](references/first-run.md) · [MIT 许可证](LICENSE)
