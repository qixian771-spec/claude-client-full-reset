---
name: claude-client-full-reset
description: 检测 macOS 上 Claude 安装与依赖并准备配置清单，检查、备份和清理 Claude Code 与 Claude Desktop 的本地数据。适用于首次环境准备、检查残留或重置客户端；先报告范围、校验备份，再按确认清单处理。保留用户技能和设置，不承诺消除服务端记录、解除账号限制或物理擦除磁盘。
license: MIT
---

# Claude 环境检测与本地重置

所有命令以本 skill 目录为工作目录。支持 macOS；Python 3.10+、Bash 是基础依赖。LevelDB 清理另需 Node.js 18+，先在本目录运行 `npm ci`。

## 操作约束

- **错误必须停止。** 权限不足、数据损坏、进程查询失败、备份校验失败都不能解释为“干净”。不更换实现、不吞错误、不跳过失败目标继续宣告成功。
- **确认具体范围。** 用户授权检查不等于授权删除。展示目标、影响及备份位置后，按用户已确认清单执行；不要重复请求已有授权。
- **修改前备份。** 实际移动、SQLite 和 LevelDB 修改必须提供 `--backup`。清单须覆盖目标及相关数据库 sidecar，并与当前内容一致。备份需要私密保存，不能上传 GitHub。
- **退出相关应用。** 备份、清理、恢复和验收前退出 Claude、浏览器及支持的编辑器。无法判断进程状态时停止。浏览器扫描也要求浏览器关闭，以取得一致数据。
- **保留用户资产。** `~/.claude/skills`、agents、hooks、settings、plugins 等不属于默认痕迹清单。删整个 `~/.claude` 需要用户明确授权；不要因文件名包含 Claude 就删除技能或项目。
- 只通过 Finder 移动批准文件；不清空废纸篓、不直接强制删除用户目录。清理脚本默认预览，实际清理必须加 `--apply`；恢复用 `--restore`，先以 `--dry-run` 预检。

## 执行环境与交接

首次使用先读 [环境与权限准备](references/first-run.md)。`--client claude` 指 Claude Code 的技能目录，不是 Desktop 导入入口。Claude Code 自身也属于必须退出的进程；在其会话或受检查编辑器内只能准备清单和说明，不得绕过进程检查来执行写入。把已确认路径、备份位置及逐步命令交给独立 Terminal/iTerm，由用户保存工作、正常退出相关应用后执行。脚本应位于待清理范围之外。不要擅自退出当前应用或代改隐私权限。

## 工作流

### 0. 环境检测与准备（首次使用或状态不明时）

读 [环境检测与配置](references/environment-check.md)，先运行：

```bash
python3 scripts/check_environment.py
```

可在应用运行时检测；不启动 Claude、不联网、不写入。根据未发现安装/安装候选/仅有本地数据/异常四种状态，安排首次准备、保留已有环境或审阅残留。权限/查询失败必须停止，不能改判未安装。新用户没有待清理数据时不要调用清理或创建空备份。安装本 skill 自身不计作 Claude 使用；未发现不等于从未使用。不能从本地文件推断封禁、登录状态或解除账号限制。

若用户要实际安装配置，先核对目标是 Desktop、Claude Code 还是本 skill；按官方当前说明实施已授权范围，不自动关闭软件、覆盖设置或修改代理/防火墙。检测不是写入授权。此检测器的退出码 0=检测完成且基础准备无问题、1=需处理、2=失败，与痕迹扫描的 1=有命中不同。

### 1. 检查与界定

先读 [覆盖范围](references/coverage-matrix.md)。

```bash
bash scripts/scan_readonly.sh
bash scripts/scan_readonly.sh --no-browser
python3 scripts/browser_scan.py --deep
```

只报告路径、键存在数量、命中计数，不输出凭证或浏览器键值。`--no-browser` 是用户明确缩小范围，不能据此宣称完成浏览器验收。检查不会运行 shell 启动文件。

### 2. 备份并验证

```bash
bash scripts/backup.sh
bash scripts/backup.sh --dest /absolute/existing/backup-parent
# 浏览器、应用本体等非默认目标，必须显式加入备份：
bash scripts/backup.sh --include "/absolute/browser/Profile 1"
python3 scripts/backup.py --verify /absolute/backup-directory
```

复制只使用 macOS `ditto`，失败立即停止。成功备份包含 `manifest.json`（完整 SHA-256 内容清单）与 `RESTORE.md`。校验比较源、副本和源的复制后状态，覆盖所有备份文件及链接。备份目录不覆盖现有目录。

默认清单不包含浏览器 profile、钥匙串或应用本体；新增目标用重复 `--include` 指定。恢复规则见 [恢复说明](references/restore-and-rebuild.md)。

### 3. 确认清单后清理

```bash
bash scripts/trash_paths.sh --dry-run /absolute/approved/path
bash scripts/trash_paths.sh --apply --backup /absolute/backup-directory /absolute/approved/path
```

每次 1–10 项。全批路径与备份校验通过后才开始移动；任一操作失败就停止，并报告可能已完成的前序操作。拒绝系统根目录、家目录和常用容器、路径穿越、符号链接、重复或父子重叠目标。路径范围见覆盖表。

### 4. 浏览器精删（按需）

先读 [浏览器规则](references/browser-layer.md)。

```bash
python3 scripts/chrome_purge.py --browser Chrome --profile "Profile 1"
python3 scripts/chrome_purge.py --browser Chrome --profile "Profile 1" --apply --backup /absolute/backup-directory
node scripts/ls_purge.js --browser Chrome --profile "Profile 1"
node scripts/ls_purge.js --browser Chrome --profile "Profile 1" --apply --backup /absolute/backup-directory
```

只处理 `claude.ai` / `anthropic.com` 及子域的文本记录或 Local Storage key。普通人名、其他域名和 BLOB 不按任意关键词删除。预览使用临时副本，不写原数据库。SQLite 中出现触发器、外键或不支持的虚拟表会停止，不能关闭约束绕过。

SQLite 每库事务、LevelDB 每库原子 batch；多库操作不构成跨库事务。后续库出错时保留备份，报告前序已执行内容，不能宣布整批成功或自动切换整库删除。

### 5. 局部恢复（按需）

先读 [恢复说明](references/restore-and-rebuild.md)。部分清理后使用 `--path` 指定原始目标或备份内子路径；不指定才是整包恢复。不得为了通过整包恢复而删除其他保留配置。

```bash
python3 scripts/backup.py --list /absolute/backup-directory
python3 scripts/backup.py --restore /absolute/backup-directory --path /absolute/original/target --dry-run
python3 scripts/backup.py --restore /absolute/backup-directory --path /absolute/original/target
```

先预检，确认后恢复；全备份仍须校验、目标必须不存在。复制失败保留不完整目标并停止；不会自动扩大范围或覆盖。SQLite/LevelDB 修改后不能直接覆盖旧数据，按恢复说明保持整个数据库及配套文件一致。

### 6. 验收

```bash
python3 scripts/verify_reset.py
python3 scripts/verify_reset.py --deep
python3 scripts/verify_reset.py --uninstalled
```

| 退出码 | 含义 |
| --- | --- |
| 0 | 所列范围检查成功且未见命中；或指定备份/修改操作成功 |
| 1 | 扫描存在命中，需要人工判断；不是执行错误 |
| 2 | 前提、输入、依赖、权限、数据库或执行错误；不得继续清理 |

未捕获的运行环境故障也可能返回其他非零状态，均视为失败。`--uninstalled` 额外检查应用及 PATH 中的 CLI；默认验收允许保留应用和自有资产。废纸篓中的 Claude 文件会继续被报告，不应为取得 PASS 自动清空。

使用 [证据报告](references/evidence-log.md) 输出命令、退出码、实际范围、保留项和未检查项。PASS 只适用于覆盖表，不能解读为全盘擦除、服务端删除或新设备身份。

## 故障处理

读 [常见故障](references/pitfalls.md)。失败必须修复原因后由用户确认重试范围；不得 `|| true`、吞异常、伪造成功校验或重新生成备份清单掩盖损坏。
