# 覆盖矩阵（Coverage Matrix）

本文件是整套流程的**系统性骨架**。执行前先通读，执行中当 checklist 用，执行后当验收基线用。

核心原则：**残留不是一个点，是一张网。** 只堵一个位置必然漏。下表按「层」穷举，每层给出位置、干净判据、动作、负责脚本。

图例：`切` = 移入废纸篓 / 精删；`留` = 有意保留；`判` = 需人工判定

| 层 | 位置 | 干净判据 | 动作 | 工具/命令 |
|---|---|---|---|---|
| **L0 进程** | `ps -eo comm=` 含 Google Chrome / Claude / VS Code | 无相关进程 | 先退再动 | `osascript ... to quit` |
| **L1 身份层** | `~/.claude.json` → `machineID` `userID` | 键不存在 | 切 | `trash_paths.sh` |
| | `~/Library/Application Support/Claude/ant-did` | 不存在 | 切 | 同上 |
| | `~/Library/Application Support/Claude-3p/ant-did` | 不存在 | 切 | 同上（**第二个独立 ID，最易漏**） |
| | 钥匙串 `Claude Safe Storage` | 无 `claude|anthropic` 条目 | 切 | `security delete-generic-password` |
| | Cookies 里 `anthropic-device-id` | 无命中 | 切 | `browser_scan.py` 定位 |
| **L2 桌面端数据** | `App Support/Claude` `Claude-3p` Cookies / Local State / Preferences / DIPS / Trust Tokens / fcache / Network Persistent State / TransportSecurity | 目录不在 | 切 | `trash_paths.sh` |
| | Local Storage / Session Storage / IndexedDB / blob_storage / shared_proto_db / WebStorage | 无命中 | 切（**整目录**，见 pitfalls #13） | `ls_purge.js` / `trash_paths.sh` |
| | plist / Caches / Caches.ShipIt / HTTPStorages / Saved Application State | 不在 | 切 | `trash_paths.sh` |
| **L3 CLI 痕迹层** | `~/.claude/projects`（常 40M+）`history.jsonl` `sessions` `tasks` `teams` `shell-snapshots` `session-env` `file-history` `paste-cache` `.cc-writes` | 不在 | 切 | `trash_paths.sh` |
| | `~/Library/Logs/Claude` `Logs/Claude-3p` `Caches/claude-cli-nodejs` | 不在 | 切 | 同上 |
| | `~/.claude_backup_pre_clean_*` `~/.claude.json.bak-*` | 不在 | 切（**旧身份载体**） | 同上 |
| **L4 自有资产** | `~/.claude/agents` `skills` `hooks` `scripts` `gsd-core` `gsd-*.json` `settings.json` `plugins` `CLAUDE.md` `backups` | — | **留** | 除非用户明确要求清空 |
| **L5 系统层** | `/Library/Logs/DiagnosticReports/Claude_*.diag` | 不在 | 切 | `trash_paths.sh` |
| | `~/Library/Saved Application State/*claude*` | 不在 | 切 | 同上 |
| | `~/Library/Group Containers` `Containers` `Application Scripts` 含 claude | 不在 | 判 | `scan_readonly.sh` §3 |
| | LaunchServices 失效注册 | 0 处（或仅剩无害残留） | 注销 | `lsregister -u "<path>"`（见 pitfalls #15） |
| | `com.apple.LSSharedFileList.ApplicationRecentDocuments/*.sfl4` | 无 claude 项 | 切（系统重建） | 同上 |
| **L6 浏览器层** | 见 `browser-layer.md`（**全部浏览器 × 全部 profile × 全部库**） | 命中文件 = 0 | 切 | `browser_scan.py` / `chrome_purge.py` |
| **L7 编辑器层** | `~/.vscode/extensions/*claude*` `*anthropic*`（含 native binary，可达数百 M） | 不在 | 切 | `trash_paths.sh` |
| | `~/.cursor/extensions/*claude*` `~/.windsurf/extensions/*claude*` | 不在 | 切 | 同上 |
| | `~/Library/Application Support/{Code,Cursor}/User/settings.json` 里的 `claudeCode.*` | 无命中 | 改 | 编辑后 `zsh -n`/`node -e` 校验 |
| | `.../User/globalStorage/state.vscdb` 的 key 层 | 无命中 | 精删 | sqlite `itemTable` |
| | 扩展日志 `.../logs/*claude*`、扩展注册表 `extensions.json` | 无命中 | 切/改 | 同上 |
| **L8 shell / env** | `~/.zshrc` `.bashrc` `.profile` `.zprofile` `.zshenv` 里的 `ANTHROPIC_*` `HEADROOM_*` `CLAUDE_*` `alias claude=` | 无匹配行 | 改 | BSD sed `-E`（见 pitfalls #5） |
| | 干净 login shell 的 env | 无相关变量 | 验证 | `env -i ... /bin/zsh -l -c 'env \| grep ...'` |
| | `$TMPDIR` `/tmp` 下 `*claude*` `*anthropic*` | 不在 | 切 | `trash_paths.sh` |
| **L9 网络工具** | Clash Verge 等 `profiles/*.yaml` `Merge.yaml` `clash-verge.yaml` `geosite.dat` | — | **留**（删了废代理） | 只清 `logs/` `service-logs/` |
| **L10 外部残留** | `~/.npm/_cacache` 命中 | 仅剩依赖名噪声 | **留** | 见 `restore-and-rebuild.md` |
| | 无头 `~/<project>/.claude` `CLAUDE.md` 等项目产物 | — | **留** | 逐项判定 |
| | 废纸篓 `~/.Trash/*claude*` | 0 项 | 清空 | 确认后 Finder 清空 |
| | APFS 本地快照 | 存在但正常 | 提示 | `tmutil listlocalsnapshots /` |

---

## 三层逻辑关系（为什么必须这么分）

```
身份层  ── 决定「服务端把新号认成谁」 ── 必须成组切除
   │
痕迹层  ── 决定「本机是否还能翻出旧记录」 ── 切除，但优先级低于身份层
   │
自有资产 ── 决定「用户自己的工作流还在不在」 ── 默认全保
```

**判据分界线**：`~/.claude` 是混合体，不是缓存。刀口画在「身份层 + 痕迹层」与「自有资产」之间。

**必须主动提示用户**：
- 删 `settings.json` = 立即失去网关通道（`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`）
- 删 `agents/` `skills/` `gsd-core/` = 工作流框架全废，且**不可从外部恢复**

---

## 两个判据，两种动作（先问清楚要哪个）

| 判据 | 含义 | 动作尺度 |
|---|---|---|
| **功能上不存在** | 应用读不到、不再关联 | 精删（`DELETE` / `del()`）足够 |
| **磁盘上无痕迹** | 字节级扫描也扫不出来 | 必须**整文件 / 整目录删**（旧页、tombstone 清不掉） |

买号前反关联场景通常要**后者**。这一点必须在动手前与用户确认，否则会做出「SQL 层面 0 命中但字节扫描仍命中」的半成品。
