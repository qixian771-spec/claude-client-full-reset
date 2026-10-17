# 备份校验、局部恢复与保留项

macOS 备份与恢复只通过 `ditto` 复制；Windows 只用工具内置的严格复制（不跟随也不创建链接，拒绝 junction 和重解析点，新目标独占创建，不合并不覆盖）。文件 SHA-256、目录与符号链接内容清单会与副本及复制后的源比较。复制或校验失败立即停止，不切换工具或生成虚假的通过结果。`manifest.json` 记录平台，另一平台的备份会被拒绝。

Windows 把下文命令中的 `python3 scripts/backup.py` 换成 `py -3 scripts\backup.py`，`bash scripts/*.sh` 换成对应的 `py -3 scripts\*.py`，路径写成 `C:\...`；备份目录内的 RESTORE.md 会按平台给出命令。

## 先确认是哪种恢复

| 情况 | 使用方式 |
| --- | --- |
| 只移走少量客户端文件或子目录 | `--restore BACKUP --path ORIGINAL`；可重复 `--path`，其余配置保持原状 |
| 所有原始来源都已移走，确实要全部恢复 | `--restore BACKUP`；任何原目标仍存在都会拒绝 |
| SQL/LevelDB 已修改，原文件仍存在 | 先按下节保全当前状态并审阅数据库一致性；不能直接覆盖 |

恢复前保存工作并退出支持的客户端、浏览器及编辑器，在独立终端从清理范围以外的 skill/源码目录操作，见 [首次准备](first-run.md)。只有校验、列出备份来源时不要求退出应用。

先核对备份来源及完整性：

```bash
python3 scripts/backup.py --verify /absolute/backup-directory
python3 scripts/backup.py --list /absolute/backup-directory
```

`--list` 只列原始来源，不显示备份内容。默认备份包含 `.claude` 的技能、设置及 shell rc，不应为了恢复一个文件而移走全部保留资产。来源目录中的具体子路径也能按原绝对路径选中。

预检后再写入（按实际情况替换占位符）：

```bash
python3 scripts/backup.py --restore /absolute/backup-directory --path /absolute/original/target --dry-run
python3 scripts/backup.py --restore /absolute/backup-directory --path /absolute/original/target
```

例如只恢复已移走的历史文件和项目子目录：

```bash
python3 scripts/backup.py --restore /absolute/backup-directory --path "$HOME/.claude/history.jsonl" --path "$HOME/.claude/projects" --dry-run
```

仅当两者都已明确确认且不存在，预检才成功。写入时去掉 `--dry-run`；不需要移走仍保留的 `.claude/settings.json`、技能或 `.zshrc`。

## 恢复契约

- `--path` 只接受备份涵盖的原始绝对路径；不能指定新的恢复位置。
- `--path` 或 `--dry-run` 不带 `--restore` 会报错，不会意外变成创建备份。
- 即使只选一项，也先校验完整备份；未选中的副本损坏同样会停止。
- 整批预检：任一选择不存在于备份、重复/父子重叠、路径不受支持或目标已存在，全部不开始复制。
- 拒绝独立的符号链接目标及符号链接父目录；恢复普通目录时保留其中备份的链接，不跟随链接去恢复外部数据。
- `--dry-run` 不创建目标或父目录；预检结果不是之后可以忽略现场变化的许可。
- 实际复制前再查进程、路径和所选副本；独占创建新目标，拒绝当时已存在的目标，不合并或覆盖。然后用 `ditto` 复制，逐项校验。
- 多目标没有统一事务。复制或校验失败立即停止，可能保留前序已恢复项目及当前不完整目标；不自动回滚、删除、重试或扩大范围。保留备份和输出，单独检查失败目标，明确决定如何移走不完整副本后再重试剩余范围。

## 数据库已修改：保全当前状态后再决定回退

SQLite 主文件与 `-wal`、`-shm`、`-journal`，以及 LevelDB 整个目录都存在一致性要求。不要只覆盖一个主文件、保留来自另一个时刻的 sidecar，也不要挑选零散 LevelDB 文件拼接。

对浏览器 profile 的完整回退可按以下步骤进行，但**会回退该 profile 内所有网站的数据和自备份以来的变化**；只有明确同意该范围才可执行。这是用户主动选择的回退方案，不是精删失败后的自动替代动作。

1. 退出相关应用，确认旧备份覆盖完整 profile 并校验成功。如果当时只备份了单个数据库，停止并另行审阅，不能假定已覆盖整个 profile。
2. 用新的备份保存当前完整 profile（明确加入 `--include`），校验成功后记录新旧两个备份路径。
3. 预览并确认将当前 profile 移入废纸篓；实际移动必须使用**新备份**授权，因为旧备份与修改后的当前数据不一致。
4. 原 profile 路径不存在后，用**旧备份**对该 profile 执行选择恢复，先 `--dry-run` 再实际恢复。工具会验证还原内容与旧快照一致。

示例中的每个路径均需替换，逐条核对，不整段粘贴执行：

```bash
bash scripts/backup.sh --include /absolute/current/browser-profile
python3 scripts/backup.py --verify /absolute/new-current-backup
bash scripts/trash_paths.sh --dry-run /absolute/current/browser-profile
bash scripts/trash_paths.sh --apply --backup /absolute/new-current-backup /absolute/current/browser-profile
python3 scripts/backup.py --restore /absolute/old-original-backup --path /absolute/current/browser-profile --dry-run
python3 scripts/backup.py --restore /absolute/old-original-backup --path /absolute/current/browser-profile
```

不想回退其他网站的数据时，停止并单独设计一致的数据库级恢复；本工具不会自动扩大范围。恢复与“清理干净”含义不同，恢复旧数据后出现原来的 Claude 命中项是预期现象，不要为通过清理验收又把它删除。

## 信任与数据保留

内容校验依赖可信 `manifest.json`，不是签名。不要用来源不明的备份，不手动修改清单以通过检查。备份归属当前家目录；不支持把其他用户的备份当成本次修改授权。

默认备份包括用户资产，浏览器、应用本体和其他非默认位置必须显式 `--include`。恢复旧配置不能承诺产生新设备身份或解除服务端限制。备份通常含凭证；只保存在可信位置，由用户决定何时销毁，不自动清空废纸篓。
