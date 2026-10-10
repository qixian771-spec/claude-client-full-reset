# 坑库（Pitfalls）

按「会怎么坑你」分组。每条都带**现象 → 根因 → 正确做法**，全部来自实战。

---

## A. Shell / 脚本类

### A1. `grep -c` 无匹配时**既输出 0 又返回退出码 1**
**现象**：`n=$(grep -c X f || echo 0)` 之后 `[ "$n" != "0" ]` 判定为真，脚本以为「有残留」。
**根因**：`grep -c` 无匹配时 stdout 输出 `0`、exit code 却是 1，于是 `||` 也执行，变量变成 `"0\n0"`。
**正确**：`n=$(grep -c X f || true); n=${n:-0}`，或干脆用 Python 做终检（`verify_reset.py` 即为此设计）。

### A2. `for f in $(grep -rl ...)` 会被路径中的**空格**拆断
**现象**：`Application Support` 下的文件被拆成两个「路径」，删除全错。
**根因**：命令替换后按 IFS 分词。
**正确**：`grep -rlZ ... | xargs -0 rm`，或 `grep -rl ... | while IFS= read -r f`。

### A3. `ls | grep X | sed Y || echo "无匹配"` 的 `||` **永远不触发**
**根因**：管道最后一段是 `sed`，它总是返回 0。
**正确**：判断有无匹配用 `grep -q` 或计数。

### A4. zsh 的 `nomatch` 会让未匹配的 glob **中断整个脚本**
**现象**：`no matches found: ~/.vscode/extensions/*claude*` 后脚本直接停。
**正确**：脚本开头 `setopt +o nomatch`，或不匹配时用 `2>/dev/null` + 显式判空。

### A5. macOS 的 BSD sed **不支持 `\|` 或运算，且静默失败**
**现象**：`sed -i '' '\(A\|B\)' f` 返回 0，但什么也没删。
**正确**：`sed -i '' -E '/...(A|B).../d'`。改完用行数变化 + 残留计数**双重验证**。

### A6. `$(( ))` 里塞入含换行的值 → `bad math expression`
**根因**：同 A1，变量成了 `"0\n0"`。
**正确**：先 `tr -d '\n'` 或只取第一行。

### A7. `[ -e ]` **判定不出断链符号链接**
**现象**：CLI 包删掉后 `~/.nvm/.../bin/claude` 是悬空链接，`[ -e ]` 返回 false → 误报「已移除」。
**正确**：`[ -e "$p" ] || [ -L "$p" ]`，并用 `ls -la | grep claude` 复核。

### A8. zsh here-doc 里的 `${...}` 会被展开
**现象**：`Error: Bad substitution: Buffer.from`。
**正确**：把脚本用 Write 工具写成文件再跑，不要塞进 `bash -c "...${...}..."`。

---

## B. 删除 / 文件系统类

### B1. `rm` 用不得，哪怕文件看起来像日志
**现象**：Clash 目录下 `grep` 命中的 `chat.json` / `pre_tool_use.json` / `user_prompt_submit.json` / `subagent_stop.json` **不是应用日志**，是 agent hook 的会话数据（GSD 等框架的 `logs/<session-uuid>/` 结构）。
**正确**：一律走废纸篓。判断依据 → **看文件名是否符合 hook 事件名，看是否在 `<uuid>/` 子目录里**。

### B2. `npm uninstall -g` 可能只回一句 "up to date" 而不报错
**根因**：包已被视为「不满足安装条件」，npm 直接跳过。
**正确**：补 `rm -rf` 包目录 + `rm -f` bin 链接（注意 A7），再复核。

### B3. 删除前必须确认目标进程已退出
**现象**：Chrome / VS Code / Cursor / Safari 在跑时改数据库会被内存状态**回写覆盖**，等于白干。
**正确**：`osascript ... to quit` → 轮询 `pgrep` → 再动手。`chrome_purge.py` / `ls_purge.js` 已内置拒绝逻辑。

### B4. 危险路径必须硬拒绝
`/`、`$HOME` 本身、`/Users`、`/Applications`、`/Library`、`/System` 等 —— `trash_paths.sh` 内置 DENY 名单，且拒绝深度 < 2 的路径。

### B5. 路径含双引号会破坏 AppleScript
`osascript -e "tell application \"Finder\" to delete (POSIX file \"$p\" as alias)"` 里若 `$p` 自身含 `"`，语法断裂。`trash_paths.sh` 直接 DENY 这类路径。

---

## C. SQLite / LevelDB 类

### C1. SQLite 的 `LIKE` / `instr` 对含 `\x00` 的 BLOB **在首个 NUL 处截断**
**现象**：Chrome `Network Action Predictor` 有 2 处字节命中，但 SQL 层「无命中」——因为匹配的是 protobuf 序列化数据。
**正确**：`hex(col) LIKE ...` 或**整文件删**（这类多为纯性能缓存，重建即可）。

### C2. LevelDB 的 `del()` 是**逻辑删除**
**现象**：删完 key 不可见，但旧 `.ldb` 里物理字节仍在，字节扫描仍命中（实测 26 个文件）。
**正确**：按判据二选一——功能干净用精删，磁盘无痕必须整目录删。

### C3. `sqlite3.connect` 的 URI 里**空格必须 percent-encode**
`f"file:{path}?immutable=1"` 遇 `Application Support` 会截断 → 打开错误的库或报错。
**正确**：`"file:" + urllib.parse.quote(path) + "?immutable=1"`。

### C4. `WAL` 模式下删了要 `VACUUM`
否则已删页仍留在文件里，字节扫描命中。

### C5. `immutable=1` 读不到 WAL 里的未 checkpoint 数据
**现象**：检测时漏报。
**正确**：检测时若同目录存在非空 `-wal`，提示「浏览器运行中，结果可能不完整」，先退出浏览器再扫。

### C6. `plyvel` 在 macOS 上编译通过但**运行时**失败
**报错**：`ImportError: dlopen(...): symbol not found in flat namespace '__ZTIN7leveldb10ComparatorE'`
**正确**：改用 Node `classic-level`（预编译绑定），`npm i classic-level` 后立即可用。

---

## D. macOS 系统类

### D1. `lsregister -kill` 在 macOS 26 **已被移除**
**报错**：`The -kill option has been removed because it was dangerous and no longer useful.`
**正确**：逐个 `"$LSR" -u "<path>"` 注销。实测把 87 处降到 1 处（剩下的 1 处为无害失效注册）。

### D2. `pgrep -f 'claude'` / `ps aux | grep claude` 会**匹配到自己**
**现象**：终检永远报「Claude 进程 = 1」。
**正确**：`ps -eo comm=` 精确匹配进程名，或排除自身 PID。

### D3. `~/Library/Caches` 体积巨大，别全量字节扫
Chrome HTTP 缓存实测 3.2G。只在判定需要时扫，且流式分块读。

---

## E. 判定类（把什么当痕迹）

### E1. 别把「用户浏览其他网站时内容里出现 claude」当痕迹
实测命中：
- 币安 `fi_ANTHROPIC` → **交易标的代码**
- GitHub 上 `anthropics/claude-code` 仓库页 → **用户浏览记录**
- DeepSeek 对话里提到 claude → **用户聊天内容**

这类删了纯属破坏用户数据。**IndexedDB 按文件名（origin）判断，不按内容。**

### E2. 家目录里带 `claude` 字样的**未必是客户端数据**
动手前逐项判定，凡符合以下特征一律**先问再动**：

| 特征 | 判定 |
|---|---|
| 含 `.git` / `package.json` / 多工具配置目录（`.cursor` `.codex` `.gemini` `.claude-plugin`） | 用户的仓库 |
| 含 `manifest.json` + `popup.html` | 用户自研浏览器扩展 |
| 命名含 `snap` / `r<n>snap` / `dist` / `error` + 日期 | 用户的逆向分析快照 |
| `*.bak*` 带日期 | 用户自己的配置备份 |

### E3. 代理/网络工具的配置里也有 "claude"，但**绝对不动**
Clash Verge 等的 `profiles/*.yaml`、`Merge.yaml`、`clash-verge.yaml`、`geosite.dat` 命中 `claude` —— 那是**分流规则或节点名**，删除会**直接废掉用户的代理**。只有 `logs/`、`service-logs/` 下的日志可以清。

动手前先看命中文件的目录分布：

```bash
grep -rlZ "claude" "$ROOT" | sed "s|$ROOT/||" | awk -F/ '{print $1}' | sort | uniq -c
```

确认全是日志再删。

### E4. npm 缓存里的 `anthropic` 多半是**依赖包名噪声**
见 `restore-and-rebuild.md`。

### E5. `~/.claude_backup_pre_clean_*` / `~/.claude.json.bak-*` 是**重置的漏点**
这些历史备份里带着旧的 `machineID` / `userID`，任何一次误恢复都会把旧身份带回来。要主动指出。

---

## F. 流程类

### F1. 别在第一轮就删
用户说的「全清理」通常不知道自己有什么。**先给分层清单再确认。**

### F2. 别用 `rm -rf ~/.claude`
里面有用户的框架与网关配置（L4 自有资产）。

### F3. 用户自有资产要单列并显式警告不可恢复（除非确认可重装）
删 `settings.json` = 立即失去网关通道；删 `agents/` `skills/` `gsd-core/` = 工作流框架全废。
**但先查清是否可从 npm 重装**（见 `restore-and-rebuild.md`），不要把可恢复的说成不可恢复。

### F4. 生成清单与执行删除**不能是同一批命令**
否则「确认」形同虚设——用户在输出里才第一次看到清单，而删已经发生了。
