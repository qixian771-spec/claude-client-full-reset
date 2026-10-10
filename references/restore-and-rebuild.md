# 可恢复性、重建与回滚

---

## 一、可恢复性：动手前查清，别吓唬用户

### 判据

删 `~/.claude/gsd-core` 之前，先确认框架的 **npm 包是否仍在**：

```bash
ls -d ~/.nvm/versions/node/*/lib/node_modules/@opengsd/gsd-core
```

| 情况 | 结论 |
|---|---|
| npm 全局包仍在 | `~/.claude/gsd-core` 只是**安装副本**，可重装 → **可以说"可恢复"** |
| 包已不在，且无 lock 文件 | 需重新拉取（有网即可） |
| 用户自写、无仓库、无备份 | **真的不可恢复** → 必须显式警告 |

**不要把可恢复的东西说成不可恢复**，也不要反过来。

### 通用检查顺序

1. 该产物是否来自包管理器？（npm / pip / 系统）
2. 是否有源仓库（`.git` / remote）？
3. 是否有备份目录？
4. 是否在**项目级**另有副本？（`~/<project>/.claude` 等）

---

## 二、重置后需重建（主动告知用户）

| 项目 | 位置 | 内容 |
|---|---|---|
| 网关配置 | `~/.claude/settings.json` | `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` |
| 框架 | `~/.claude/gsd-core`、`agents`、`skills`、`hooks` | 工作流全套 |
| 桌面端 MCP | `claude_desktop_config.json` | MCP server 定义 |
| 设备身份 | — | 下次运行会生成**全新** `machineID` / `userID` / `ant-did` |

> 最后一条是好消息：全新身份 = 反关联的**目的达成**。要明确告诉用户这是预期行为，不是故障。

---

## 三、依赖名噪声：别把包名当使用痕迹

终检时最常见的**假阳性**是 npm 内容寻址缓存命中：

```bash
grep -rl "anthropic" ~/.npm/_cacache
```

命中文件内容可能形如：

```json
{"_id":"@opengsd/gsd-core","_rev":"40-...","versions":{...}}
```

即**某个包的 registry metadata（packument）**，`anthropic` 只是它 `dependencies` 里的
`@anthropic-ai/claude-agent-sdk` 之类的**依赖包名**。

### 三步定性

```bash
f=$(grep -rl "anthropic" ~/.npm/_cacache | head -1)
head -c 200 "$f"                                    # ① 看 _id = 哪个包
grep -o "anthropic[^\"]\{0,60\}" "$f" | head -5     # ② 命中上下文是否依赖声明
ls -la "$f"                                         # ③ mtime 是否 = 本次 npm 操作时间
```

**判据**：命中词在 `dependencies` / `peerDependencies` / `devDependencies` 里 → **噪声，保留**。

**三条理由**：
1. 该字符串**对服务端完全不可见**（本地缓存不参与网络请求），清除对反关联零收益
2. 强行删会被 npm 下次拉取**重新写入** → 无效动作
3. 破坏离线重装能力

同理适用于：`node_modules` 里的包名目录、lock 文件的包名条目、任何「包名恰好含目标词」的场景。

> `verify_reset.py` 已内置该判定（`is_dep_noise()`），会把这类单列为「已识别噪声」**不计入实质残留**。

---

## 四、RESTORE.md 模板

`backup.sh` 会自动生成，此处留一份供手工重建时参考：

```markdown
# Claude 重置 · 回滚说明

本目录是执行「Claude 客户端全量重置」**之前**的快照。
回滚 = 把下列内容放回原位。执行前确认目标不存在（避免合并污染）。

## 回滚命令

```bash
BK="$(cd "$(dirname "$0")" && pwd)"

[ -d "$BK/dot-claude" ]      && ditto "$BK/dot-claude"      "$HOME/.claude"
[ -f "$BK/dot-claude.json" ] && cp -p "$BK/dot-claude.json" "$HOME/.claude.json"

[ -d "$BK/AppSupport-Claude" ]    && ditto "$BK/AppSupport-Claude"    "$HOME/Library/Application Support/Claude"
[ -d "$BK/AppSupport-Claude-3p" ] && ditto "$BK/AppSupport-Claude-3p" "$HOME/Library/Application Support/Claude-3p"
[ -f "$BK/plist" ] && cp -p "$BK/plist" "$HOME/Library/Preferences/com.anthropic.claudefordesktop.plist"

for f in "$BK/shell-rc"/*; do cp -p "$f" "$HOME/$(basename "$f")"; done
```

## 校验

```bash
cd "$BK" && md5 -c MD5SUMS.txt
```

## 注意

- md5 与 MD5SUMS.txt 一致 = 备份未损坏。
- 回滚 `machineID` / `userID` / `ant-did` = 把**旧设备身份带回来**。
  若不是有意为之，新号登录时会被关联。**回滚前想清楚目的。**
- 清空本目录是**不可逆**的。确认新号跑通后再清。
```

---

## 五、清空备份的决策点

备份是**给"后悔"用的窗口**，不是长期存档。推荐节奏：

```
备份 → 清理 → 终检 PASS → 新号登录跑通 → （此时才）清空备份
```

**在"新号跑通"之前不要清**——否则一旦发现漏删或误删，没有任何退路。

清空动作同样走废纸篓 + 用户显式确认，且清空前**列出目录内容清单**（避免连带删掉用户放进来的其他产物）。

> 实战教训：曾有一次在用户要求「备份给我清理掉」时直接整目录删，事后才发现里面还躺着一份用户自有产物归档。
> **教训：即便用户说"整个删掉"，也先 `ls` 一遍内容贴给用户看，再删。**
