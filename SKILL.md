---
name: claude-client-full-reset
description: 在 macOS 上把 Claude Code CLI 与 Claude Desktop 的数据面做「重置式」清理，使客户端呈现全新安装状态——清除 machineID/userID/ant-did 设备标识、Keychain 条目、Cookie 与各类本地存储、缓存、日志、编辑器扩展残留、浏览器痕迹与 shell 环境变量。当用户表达下列任一意图时使用：「把 Claude 的缓存/残留/设备指纹清掉」「重置 Claude CLI 或桌面端」「清掉设备 ID / machineID」「换号或买新号前把机器清一遍」「账号老被封，查查是不是本机有残留」「彻底卸载 Claude 并清干净」「模拟全新设备登录」。覆盖分层切分（身份层/痕迹层/自有资产）、先备份后动手、移入废纸篓而非 rm、多 ant-did 陷阱、浏览器全 profile 扫描、SQLite/LevelDB 清除边界与全盘终检。
license: MIT
---

# macOS · Claude 客户端全量重置

把 Claude Code CLI 与 Claude Desktop 在 macOS 上的**数据面**清成一个全新安装的状态。
本 skill 面向「清理作业」：先普查、再备份、后分批删除、最后用脚本断言残留为 0。

## 核心心智模型（先对齐认知，再动手）

**本地清理对服务端是零可见的**，它不抹掉任何已上传的记录。唯一价值是：

> **让新号登录时不带着旧指纹上去。**

| 路径 | 服务端能看到 |
|---|---|
| 命令行 CLI | 出口 IP + 凭证 + 客户端版本（**不带指纹/Cookie**） |
| 浏览器 | 多得多：Cookie、设备 ID、登录检测标记、各类指纹 |

封号归因是**五层锚点**（出口 IP / 设备指纹 / 支付主体 / 邮箱域 / 使用行为），**必须成组替换**，
单换 IP 或单清设备都无效。**本 skill 只解决其中一层**——必须主动把这个边界告诉用户。

## 何时用 / 何时不用

**用**：重置客户端、反关联前清理、彻底卸载、"模拟全新设备"。
**不用**：只是想登出账号（浏览器里点一下即可）；只想清磁盘空间（那是另一回事）。

## 铁律（四条，不可协商）

1. **先备份，后动手。** 备份必须含 `~/.claude`、`~/.claude.json`、App Support、plist、Caches、HTTPStorages、Logs。
   备份完留 md5 → 这是「备份 == 清理前状态」的唯一硬证据。
2. **移入废纸篓，不用 `rm -rf`。** 同卷移动是秒级 rename，随时可取回。
3. **先出清单、取得确认、再删。** 清单与执行**不能是同一批命令**，否则"确认"形同虚设。
4. **删前确认无相关进程在跑。** 否则会改到一半被内存状态回写覆盖。

## 分层切分（整套流程的关键洞察）

`~/.claude` **不是缓存**，是混合体。刀口画在「身份层 + 痕迹层」与「自有资产」之间：

| 层 | 内容 | 动作 |
|---|---|---|
| **身份层** | `~/.claude.json` 的 `machineID` `userID`；`App Support/Claude/ant-did`、`Claude-3p/ant-did`；桌面端 Cookies / Local State / Preferences / DIPS / Trust Tokens / fcache / Network Persistent State / TransportSecurity；Local Storage / Session Storage / IndexedDB / blob_storage / shared_proto_db；Keychain `Claude Safe Storage` | **切除** |
| **痕迹层** | `~/.claude/projects`（常 40M+）`history.jsonl` `sessions` `tasks` `teams` `shell-snapshots` `session-env` `file-history` `paste-cache` `.cc-writes`；`~/Library/Logs/Claude`、`Caches`、`HTTPStorages`、plist、sentry、Crashpad | **切除** |
| **自有资产** | `~/.claude/agents` `skills` `hooks` `scripts` `gsd-core` `gsd-*.json` `settings.json`（含网关配置）`plugins` `CLAUDE.md` `backups` | **保留**（除非用户明确要求清空） |

**必须主动提示**：删 `settings.json` = 立即失去网关通道；删 `agents/` `skills/` `gsd-core/` = 工作流框架全废。

完整的「层 × 位置 × 判据 × 动作」穷举表见 `references/coverage-matrix.md` —— **执行前先通读，执行中当 checklist。**

---

## 工作流

五阶段。**阶段之间必须停下来给用户看结果**，不要一口气跑完。

### Stage 0 · 只读普查

```bash
bash scripts/scan_readonly.sh              # 全量
bash scripts/scan_readonly.sh --no-browser # 跳过浏览器层（省时）
python3 scripts/browser_scan.py            # 浏览器层单独细查
```

产出：命中项清单 + 身份键存在性（**只报存在性与条数，绝不打印 cookie/token/machineID 的值**）。
→ 参考 `references/coverage-matrix.md` 逐层核对，特别是 L5 系统层与 L7 编辑器层。

### Stage 1 · 备份 + 硬证据

```bash
bash scripts/backup.sh
bash scripts/backup.sh --dest /Volumes/Ext/claude-bk   # 备份到异盘更稳
```

产出：备份目录 + `MD5SUMS.txt` + 自动生成的 `RESTORE.md`。

### Stage 2 · 出清单 + 确认

把「要删什么 / 各属于哪一层 / 其中哪些是自有资产」列成表交用户确认。
**这一步不执行任何删除。** 自有资产单列并标注可恢复性（见 `references/restore-and-rebuild.md`）。

### Stage 3 · 分批删除

```bash
bash scripts/trash_paths.sh --dry-run "/path/a" "/path/b"   # 先看
bash scripts/trash_paths.sh "/path/a" "/path/b"             # 再删（≤10/批，批后复核）
```

危险路径（`/`、`$HOME`、`/Applications`、`/Library` …）会被硬拒绝。
清单也可从 stdin 喂入：`printf '%s\n' "$p1" "$p2" | bash scripts/trash_paths.sh -`

### Stage 4 · 精删（需逐条清到表/列/key 级别）

```bash
# 浏览器 SQL 层（默认 dry-run；检测到浏览器运行中会直接拒绝）
python3 scripts/chrome_purge.py
python3 scripts/chrome_purge.py --apply

# Local Storage 按 key 精删（需 npm i classic-level）
node scripts/ls_purge.js
node scripts/ls_purge.js --apply
```

**边界必须交代清楚**（详见 `references/browser-layer.md`）：
- SQL `DELETE` 清不掉 BLOB 命中（`LIKE` 遇 `\x00` 截断）与未 `VACUUM` 的旧页 → 那类只能**整文件删**
- LevelDB `del()` 是**逻辑删除** → 要"磁盘无痕迹"必须**整目录删** `Local Storage`

**先问用户要哪个判据**：功能上不存在（精删够） vs 磁盘上无痕迹（必须整删）。

### Stage 5 · 全盘终检

```bash
python3 scripts/verify_reset.py          # 七维度，退出码 0 = PASS
python3 scripts/verify_reset.py --deep   # 追加 Chrome HTTP 缓存扫描
```

**以脚本退出码为准，不以"我看了一遍"为准。**

脚本自带**前提校验**：若检测到 Claude 仍处于已安装/运行状态，返回退出码 2 并声明「本报告不能作为残留已清零的依据」——因为此时命中项大多是**当前安装的组成部分**，而非历史残留。这是最容易自欺的地方：把活跃安装的 53 个正常文件读成「51 项残留」。

---

## 脚本清单（调用契约）

| 脚本 | 阶段 | 读写 | 说明 |
|---|---|---|---|
| `scripts/scan_readonly.sh` | 0 | **只读** | 全机普查，输出 FOUND/CLEAR |
| `scripts/browser_scan.py` | 0 / 4 | **只读** | 全部浏览器 × 全部 profile × 全部库；`--deep` 加扫 HTTP 缓存 |
| `scripts/backup.sh` | 1 | 写备份 | ditto + md5 + 生成 RESTORE.md |
| `scripts/trash_paths.sh` | 3 | 删除 | 移入废纸篓；危险路径 DENY；≤10/批；退出码 = FAIL 数 |
| `scripts/chrome_purge.py` | 4 | 改库 | SQL 精删 + VACUUM；默认 dry-run；浏览器运行中拒跑 |
| `scripts/ls_purge.js` | 4 | 改库 | Local Storage 按 key 删；默认 dry-run；需 classic-level |
| `scripts/verify_reset.py` | 5 | **只读** | 七维度终检；退出码 0=PASS / 1=有残留 / 2=前提不满足；内置状态判定与依赖名噪声判定 |

运行环境：macOS、Bash、Python 3；Python 3 需预先安装并验证可用。`ls_purge.js` 另需 Node.js 18+，在 skill 根目录运行 `npm ci` 安装锁定的依赖。缺少依赖时停止并报告。

---

## 参考文件（按需加载，不要全读）

| 文件 | 何时读 |
|---|---|
| `references/coverage-matrix.md` | **每次执行前**——系统性核查表 |
| `references/browser-layer.md` | 要处理浏览器痕迹时（含全 profile 铁律、Chrome History 四张旁表） |
| `references/pitfalls.md` | 写 shell/SQL 命令前；遇命令"返回 0 但没生效"时 |
| `references/restore-and-rebuild.md` | 判断可恢复性、写回滚说明、区分依赖名噪声时 |
| `references/evidence-log.md` | 要交付报告时——证据分级与报告模板 |

---

## 验收判据

- `python3 scripts/verify_reset.py` 退出码 = **0**

  | 退出码 | 含义 | 该怎么办 |
  |---|---|---|
  | **0** | PASS —— 无活跃安装，实质残留 0 | 交付 |
  | **1** | FAIL —— 无活跃安装，仍有实质残留 | 回到 Stage 3 / 4 继续清 |
  | **2** | **前提不满足** —— 检测到 Claude 已安装/在运行 | **先卸载或退出再验收**；这不是「清理失败」，而是「结论无效」 |

- 七维度实质残留合计 = **0**；噪声与有意保留项**已显式列出并给出理由**
- 干净 login shell 无 `ANTHROPIC_*` / `CLAUDE_*` / `HEADROOM_*`：
  ```bash
  env -i HOME="$HOME" TERM=xterm /bin/zsh -l -c 'env | grep -E "^(ANTHROPIC|CLAUDE|HEADROOM)"'
  ```
- `zsh -n ~/.zshrc` / `bash -n ~/.bashrc` 通过
- 备份目录存在且 `md5 -c MD5SUMS.txt` 一致

交付报告用 `references/evidence-log.md` 的模板——**前后对照 + 退出码 + 保留项理由**。

---

## 常见场景速查

**「清完但我的工作流还在吗」** → 保留 L4 自有资产；需重建项见 `references/restore-and-rebuild.md`。

**「彻底卸载」** → 除上述外再加：
```bash
bash scripts/trash_paths.sh /Applications/Claude.app
"$HOME/.nvm/versions/node/<ver>/bin/npm" uninstall -g @anthropic-ai/claude-code
rm -rf "$HOME/.nvm/versions/node/<ver>/lib/node_modules/@anthropic-ai"
rm -f  "$HOME/.nvm/versions/node/<ver>/bin/claude"   # 断链必须显式删，[ -e ] 判不出来
```
然后用 `ls -la ~/.nvm/versions/node/*/bin/ | grep -i claude` 复核。

**「只想知道有没有残留，先别删」** → 只跑 Stage 0 的只读脚本，出报告即可。
