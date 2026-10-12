# Claude Client Full Reset

macOS 上 Claude Code / Claude Desktop 本地数据检查、备份与清理的 Agent Skill。MIT 开源。

支持本地文件检查、SHA-256 备份校验、Finder 废纸篓移动、SQLite 域名记录和 LevelDB key 清理。**清理默认预览，实际清理必须有校验通过的备份；恢复拒绝覆盖。** 不处理服务端数据，不承诺解除账号限制或物理擦除磁盘。

## 首次准备

需要 macOS、Python 3.10+、Git；仅 LevelDB 功能另需 Node.js 18+ 和 npm。先阅读 [首次准备](references/first-run.md)：依赖下载、终端选择、macOS 权限和浏览器路径定位均在其中。

**安装 skill 不等于能在 Claude 自己的会话内重置自己。** `--client claude` 安装到 Claude Code 的 skill 目录，Claude Desktop 是可清理对象，不是这个安装选项的技能宿主。Agent 可帮助准备清单；备份、写入、恢复和最终验收前，需保存工作并退出相关应用，在独立 Terminal/iTerm 执行。不能跳过进程检查。

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
- 恢复使用 `ditto` 并逐项校验。失败可能留下不完整目标；保留现场并核查，不能盲目重跑、自动删掉冲突目标或改写备份清单。
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

GitHub Actions 在 macOS 和 Linux 运行结构检查与隔离夹具测试；Linux 只测试可移植逻辑，清理 CLI 仍限 macOS。测试不会清理真实 Claude / 浏览器数据。

[任务与验收记录](docs/release-tasks.md) · [测试报告](docs/acceptance.md) · [首次准备](references/first-run.md) · [MIT 许可证](LICENSE)
