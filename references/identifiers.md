# 标识清单：哪些 ID 在哪里，清理后怎样证明它们变了

本页回答两个问题：本机到底有哪些 Claude 相关的标识（用户、机器、设备、遥测、站点），以及清理（路线 C）之后怎样用证据证明它们已经换掉，而不是"应该换了"。工具是 `scripts/identifiers.py`，**只读**，只输出 SHA-256 前 12 位指纹，从不打印 ID 原值。

## 1. 清单（2026-10-22 在 macOS 实机核对；Windows 路径由 `platforms` 表映射）

| 标识 id | 产品 | 位置（macOS → Windows） | 键 / 内容 | 性质 | 清理路线 |
|---|---|---|---|---|---|
| `code.user_id` | Claude Code | `~/.claude.json` | `userID`（64 位十六进制） | 用户 | C3 移走 `.claude.json` |
| `code.machine_id` | Claude Code | `~/.claude.json` | `machineID` | 机器 | 同上 |
| `code.account_uuid` / `code.org_uuid` / `code.email` | Claude Code | `~/.claude.json` | `oauthAccount.accountUuid` / `organizationUuid` / `emailAddress` | 账号 | 同上 |
| `code.first_start` | Claude Code | `~/.claude.json` | `firstStartTime` | 首启 | 同上 |
| `code.credentials_file` | Claude Code | `~/.claude/.credentials.json`（Windows/Linux） | OAuth 令牌 | 凭证 | 属 `.claude` 资产，需明确授权 |
| `code.keychain` | Claude Code | macOS 钥匙串 `Claude Code-credentials` | OAuth 令牌 | 凭证 | 只报存在与否；不参与对比判定 |
| `desktop.device_id` | Claude Desktop | `~/Library/Application Support/Claude/ant-did` → `%APPDATA%\Claude\ant-did` | 48 字符设备标识 | 设备 | C3 移走整个数据目录 |
| `desktop.device_registry` | Claude Desktop | `…/Claude/ant-device-registry.json` | `{设备 UUID: 令牌}` | 设备 | 同上 |
| `desktop.ccd_salt` | Claude Desktop | `…/Claude/ccd-ids.json` | `salt` | 派生会话 ID | 同上 |
| `desktop.account_uuid` / `desktop.first_launch` / `desktop.first_version` | Claude Desktop | `…/Claude/config.json` | `lastKnownAccountUuid` / `first_launch_at` / `version_first_launch` | 账号、首启 | 同上 |
| `desktop.sentry_user` / `desktop.sentry_device` / `desktop.sentry_session` | Claude Desktop | `…/Claude/sentry/scope_v3.json`（`scope.user.id`）、`sentry/session.json`（`did`、`sid`） | Sentry 用户 / 设备 / 会话 | 遥测 | 同上 |
| `desktop.local_storage` | Claude Desktop | `…/Claude/Local Storage/leveldb` | 整个目录（含 Segment `anonymous_id`） | 遥测 | 同上 |
| `desktop.session_storage` | Claude Desktop | `…/Claude/Session Storage` | 整个目录 | 会话 | 同上 |
| `desktop.indexeddb` | Claude Desktop | `…/Claude/IndexedDB/https_claude.ai_0.indexeddb.leveldb` | 整个目录 | 站点 | 同上 |
| `desktop.cookies` | Claude Desktop | `…/Claude/Cookies` | cookie 库（`ajs_anonymous_id`、`cf_clearance` 等） | 站点 | 同上 |
| `desktop.vm_machine_id` | Claude Desktop | `…/Claude/vm_bundles/claudevm.bundle/machineIdentifier` | Cowork 虚拟机标识 | 设备 | 同上 |

MSIX 版 Claude Desktop（`%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`）同样扫描，id 带 `@msix` 后缀。

浏览器里 claude.ai / anthropic.com 的 cookie、Local Storage、IndexedDB（`ajs_anonymous_id`、`ajs_user_id`、`intercom-*`、`__cf_bm`）不在本工具内，由 [浏览器规则](browser-layer.md) 的扫描与精删覆盖。

**不可重置、本 skill 不承诺**：硬件序列号、MAC、磁盘 UUID、Apple ID / Microsoft 账号、服务端保存的 IP 与 TLS 指纹历史。Local Storage / IndexedDB 只记目录指纹：目录被移走后应用重建，指纹必然不同；不逐个解析 LevelDB 值。

## 2. 用法（AI 执行）

| 步骤 | 命令 | 预期 | 退出码 |
|---|---|---|---|
| 清理前快照 | `python3 scripts/identifiers.py --snapshot /绝对路径/ids-before.json` | 写入新文件；已存在则拒绝 | 0；2 = 有项读取失败 |
| 看当前状态 | `python3 scripts/identifiers.py`（或 `--json`） | 每项 存在+指纹 / 不存在 | 同上 |
| 清理并首次重新启动应用后 | `python3 scripts/identifiers.py --compare /绝对路径/ids-before.json` | 每项 `已变` / `已移除` / `新出现` / `两次都不存在`；`未变` 即失败 | 0 通过；1 有未变；2 无法判定 |
| 两份快照对比 | `--compare before.json --after after.json` | 同上 | 同上 |

判定规则：清理前**存在**的标识，现在必须 `已变` 或 `已移除`。钥匙串项只查存在，不判定。`未变` 要点名并停止，不能写成"已重置"。

Windows 用 `py -3 scripts\identifiers.py ...`。快照文件含本机路径与指纹，是私有证据，不上传。

## 3. 与其他路线的关系

- 路线 C（[执行手册](agent-runbook.md)）在 C1.5 前提自检后做清理前快照，在 C5 清理验收里做对比；对话模板见 [对话模板 4B](conversation.md)。
- `verify_reset.py` 验收的是"文件还在不在"，本工具验收的是"重新生成后的 ID 是不是新的"，两者都要。
- 遥测开关与分流规则（让 ID 即使存在也不乱上报）见 [监测与分流说明](telemetry-and-routing.md)。
