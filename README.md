# Claude Client Full Reset

macOS 上 Claude Code / Claude Desktop 本地数据检查、备份与清理的 Agent Skill。MIT 开源。

支持范围：本地文件检查、SHA-256 备份校验、Finder 废纸篓移动、SQLite 域名记录清理和 LevelDB key 清理。**默认预览；实际清理必须指定经过校验的备份。** 不处理服务端数据，不承诺解除账号限制或物理擦除磁盘。

## 安装

需要 macOS、Python 3.10+ 和 Git。Python 需自行安装并确保 `python3 --version` 可用。

```bash
git clone https://github.com/qixian771-spec/claude-client-full-reset.git
cd claude-client-full-reset

# 选择自己的客户端：
python3 tools/install.py --client codex
# 或：
python3 tools/install.py --client claude
```

安装器分别复制到 `~/.codex/skills/claude-client-full-reset`（遵循显式配置的 `CODEX_HOME`）或 `~/.claude/skills/claude-client-full-reset`；已有安装会明确报错，不合并覆盖。自定义位置使用 `--dest /absolute/skill-directory`。升级时先检查现有文件，移走旧安装后再安装。

重新加载客户端，在技能列表中确认名称，然后发出：

> 使用 claude-client-full-reset，只检查本地数据，展示范围和命中项，不执行清理。

Codex 可显式使用 `$claude-client-full-reset`。也可直接在源码目录运行脚本。运行时只需要 Python 标准库；PyYAML 是开发检查依赖。

仅在使用 LevelDB 功能时，需要 Node.js 18+ 并在**安装后的 skill 目录**执行：

```bash
npm ci
```

例如 Codex 默认目录：

```bash
cd ~/.codex/skills/claude-client-full-reset
npm ci
```

## 最小工作流

以下命令以 skill 目录为工作目录；`/absolute/...` 必须替换为你检查确认的路径。

```bash
# 1. 只读检查；0=无命中，1=有命中，2=检查失败
bash scripts/scan_readonly.sh

# 2. 退出相关应用后备份；浏览器 profile 需显式 --include
bash scripts/backup.sh --include "/absolute/browser/Profile 1"
python3 scripts/backup.py --verify /absolute/backup-directory

# 3. 预览并确认清单
bash scripts/trash_paths.sh --dry-run /absolute/approved/path

# 4. 执行已确认的清理；拒绝没有备份或备份后已变化的目标
bash scripts/trash_paths.sh --apply --backup /absolute/backup-directory /absolute/approved/path

# 5. 检查覆盖范围内的结果
python3 scripts/verify_reset.py
```

操作会影响本地历史、登录状态等；确认目标后再使用 `--apply`。原来的“不给参数就删除”行为已取消，默认只预览。每批最多 10 个路径；不支持符号链接目标，也不直接删除系统目录。具体范围见 [覆盖矩阵](references/coverage-matrix.md)。

浏览器 SQL / LevelDB 用法见 [SKILL.md](SKILL.md) 和 [浏览器规则](references/browser-layer.md)。浏览器扫描要求退出浏览器，修改和验收还要求退出 Claude 及支持的编辑器。权限不足时必须处理权限，不能将失败解释为干净。

## 备份与恢复

`manifest.json` 记录全部备份内容的 SHA-256、目录及符号链接；复制失败或副本不一致都不会成为可用备份。备份可能含凭证，目录权限为仅当前用户访问，不要上传。

```bash
python3 scripts/backup.py --verify /absolute/backup-directory
python3 scripts/backup.py --restore /absolute/backup-directory
```

恢复要求所有目标不存在，并逐项复制、校验；不覆盖现有文件。备份校验不是数字签名，只使用可信的本地备份。详细规则见 [恢复说明](references/restore-and-rebuild.md)。

## 错误处理与验收范围

- 不使用替代复制命令、不吞掉扫描异常、不把进程查询失败当成无进程。
- SQLite 预览使用副本，修改按库提交事务；LevelDB 保留原始二进制键并按库原子删除。
- SQLite 提交后 VACUUM 失败仍返回错误。多路径、多库不具备跨目标事务；失败时前序操作可能已完成，必须查看输出和备份后再决定。
- `verify_reset.py` 的 PASS 仅覆盖列出的本地位置。钥匙串、服务端记录、快照、其他用户、任意项目目录等不在自动验收范围。相关用户资产默认保留。
- 不输出 cookie/token、环境变量值或 Local Storage key 内容。

## 开发与测试

```bash
python3 -m pip install -r requirements-dev.txt
npm ci
python3 tools/check.py
python3 -m unittest discover -s tests -v
node --test tests/level.test.js
```

GitHub Actions 在 macOS 和 Linux 运行结构检查与隔离夹具测试。Linux 仅运行可移植逻辑测试，实际清理 CLI 仍限制为 macOS。测试不会清理开发者的真实 Claude / 浏览器数据。

[任务与验收记录](docs/release-tasks.md) · [测试报告](docs/acceptance.md) · [MIT 许可证](LICENSE)
