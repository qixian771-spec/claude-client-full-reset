# 浏览器层 · 全谱排查

**客户端删了 ≠ 网页端没痕迹。** `claude.ai` 的使用记录全在浏览器里。

---

## ⛔ 铁律：必须遍历**所有** profile

这是本流程最容易翻车的地方。**只查 `Default` 会产生严重假阴性。**

真实教训（本流程第五轮）：曾断言「浏览器层已清干净」，实际只查了 `Default/History` 一个文件。复查发现 **12 个 profile 里有 48 个库文件命中**，其中含**真正的设备标识**：

| 位置 | 命中的是什么 | 性质 |
|---|---|---|
| `Profile 7/8/Cookies` | `anthropic-device-id` | **真设备标识** |
| `Profile 8/Preferences` | `login_detection.oauth_signed_in_origins` | 明确记录「已登录过」 |
| `Default/Web Data` | autofill 里的 `claude-api-key` | **API 密钥**，最该清 |

**因此**：不要在脚本里枚举固定 profile 名；用「目录内有 `Preferences` 或 `Cookies`」判定 profile，动态枚举。

```bash
# 正确姿势——动态枚举（browser_scan.py 内部即此逻辑）
CH="$HOME/Library/Application Support/Google/Chrome"
for d in "$CH"/*/; do
  [ -f "$d/Preferences" ] || [ -f "$d/Cookies" ] || continue
  echo "profile: $(basename "$d")"
done
```

用 `scripts/browser_scan.py` 一把梭，它会覆盖：Chrome / Chrome Beta / Chrome Canary / Edge / Brave / Vivaldi / Chromium / Arc，每个 profile 扫顶层全部文件 + 7 类子目录。

---

## 每个 profile 要查的东西（不枚举固定文件名）

顶层库（名字随版本变，按内容判定更稳）：

`Cookies` · `Web Data` · `Top Sites` · `Shortcuts` · `Favicons` · `Network Action Predictor` · `Reporting and NEL` · `Preferences` · `Secure Preferences` · `Visited Links` · `History` · `Current/Last Session` · `Current/Last Tabs` · `Login Data` · `Affiliation Database` · `History Provider Cache`

子目录：`Local Storage` · `Session Storage` · `Service Worker` · `IndexedDB` · `Shared Dictionary` · `blob_storage` · `File System`

---

## Chrome History：claude 痕迹**不在** `urls` 表

只删 `urls` 会得到「335 → 0」的**假成功**——实际还有近千条藏在 4 张旁表：

| 表 | 列 | 说明 |
|---|---|---|
| `visited_links` | `top_level_url` / `frame_url` | **量最大**，页面内所有链接关系 |
| `visits` | `external_referrer_url` | 从 claude.ai 跳出的记录 |
| `content_annotations` | `search_terms` / `search_normalized_url` | 地址栏搜索词 |
| `downloads_url_chains` | `url` | 下载链路 |

另需处理 `urls.title`（第三方页面标题含 Claude）、`segments`（搜索段）、`downloads`。

### 定位方法（不要猜表名）

1. 删完 `urls` 后用 `grep -c -a claude <History>` 做**字节复核**，非 0 就继续
2. 遍历 `sqlite_master` 取表名 → `pragma table_info` 取列 → 逐表逐列 `LIKE` 计数，定位到具体表
3. 清理后 `VACUUM`，再复核

```python
import sqlite3
con = sqlite3.connect(f"file:{H}?immutable=1", uri=True); cur = con.cursor()
for t in [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]:
    for c in [r[1] for r in cur.execute(f'pragma table_info("{t}")')]:
        try:
            n = cur.execute(f'select count(*) from "{t}" where "{c}" like ?',
                            ('%claude%',)).fetchone()[0]
            if n: print(t, c, n)
        except Exception: pass
```

> 注意 `sqlite3.connect` 的 URI 里**空格必须 percent-encode**，否则路径被截断。
> 用 `"file:" + urllib.parse.quote(path) + "?immutable=1"`。

---

## 各库看点（易漏清单）

- **Cookies**：`host_key like '%claude%'`（含 `.claude.ai` / `claude.ai` / `.claude.com`），删后 `VACUUM`。
  ⚠️ `cookies` 表还有 **`top_frame_site_key`** 列——在 anthropic 页面加载的第三方 cookie（如 `.youtube.com`）会带 `https://anthropic.com` 的 top_frame 值，**也得删**
- **Web Data（autofill）**：`autofill.name` / `autofill.value` 里可能存着 **API key**（实测命中 `claude-api-key`）——最该清，却最容易漏
- **Network Action Predictor**：`network_action_predictor.user_text` / `.url` 会记下地址栏输入的 `claude` 和 `https://claude.ai/login`
- **Reporting and NEL**：`reporting_endpoints.origin_host` / `nel_policies.origin_host` 记 `status.claude.com`
- **Service Worker / Session Storage**：缓存层，含 claude.ai 资源（实测 945M）——整目录删
- **`~/Library/Caches/Google/Chrome`**：HTTP 缓存，实测 **3.2G / 9520 文件**命中，整目录删
- **会话文件**（`Current Session` / `Current Tabs`）：记录打开的标签页，查一下
- **`com.apple.LSSharedFileList.ApplicationRecentDocuments/*.sfl4`**：应用「最近文档」列表；`RecentApplications.sfl4` / `FavoriteVolumes.sfl4` 也留痕，移走后由系统重建最干净

### IndexedDB：按**文件名**判断，不要按内容删

`Chrome/<profile>/IndexedDB/https_claude.ai_0.indexeddb.leveldb`（还有 `https_anthropic.skilljar.com_*`）。

⚠️ 但 IndexedDB 里「内容含 claude」≠ 痕迹。实测命中过：

| 命中 | 真相 | 该不该删 |
|---|---|---|
| 币安 `fi_ANTHROPIC` | 交易标的代码 | **不能删**（用户数据） |
| GitHub `anthropics/claude-code` 提交页 | 用户浏览记录 | **不能删** |
| DeepSeek 对话里提到 claude | 用户聊天内容 | **不能删** |

**判据：文件名（origin）指向 claude.ai / anthropic.com 才处理；内容命中一律不动。**

---

## Local Storage：能精删，但清不掉物理字节

`<profile>/Local Storage/leveldb/` 是标准 LevelDB，**可按 key 精确删除**：

```javascript
const { ClassicLevel } = require('classic-level');
const db = new ClassicLevel(dir, { createIfMissing: false });
await db.open();
const toDel = [];
for await (const [k] of db.iterator()) {
  if (/claude|anthropic/i.test(k.toString('latin1'))) toDel.push(k);
}
for (const k of toDel) await db.del(k);
await db.close();
```

见 `scripts/ls_purge.js`（默认 dry-run）。

⚠️ **`del()` 是逻辑删除**——写 tombstone 后 key 不可见，但**旧 `.ldb` 文件里的物理字节仍在**，字节扫描依旧命中。按判据二选一：

- 判据「功能上不存在」→ 精删足够
- 判据「磁盘上无痕迹」→ **必须整目录删**（`bash scripts/trash_paths.sh "<profile>/Local Storage"`，Chrome 会重建；cookie 登录态不受影响）

> `plyvel`（Python）在 macOS 上即使编译通过也常报 leveldb C++ ABI 符号缺失：
> `symbol not found: __ZTIN7leveldb10ComparatorE`。**直接用 Node `classic-level`**（预编译绑定）。

**改 Chrome 数据库前必须完全退出 Chrome**：

```bash
osascript -e 'tell application "Google Chrome" to quit'
# 轮询确认进程消失，否则数据库会被内存状态回写覆盖 = 白干
while pgrep -x "Google Chrome" >/dev/null; do sleep 1; done
```

会话文件干净的话，重开时标签页会自动恢复。

---

## Safari（不是 Chromium，单独处理）

| 位置 | 内容 | 实测 |
|---|---|---|
| `~/Library/Safari/History.db` | `history_items` / `history_visits` | 60 行命中 |
| `~/Library/Safari/RecentlyClosedTabs.plist` | 历史 URL | 有 |
| `~/Library/Safari/Downloads.plist` | 下载记录 | 视情况 |

Safari 是 WAL 模式，删除同样需要 `VACUUM`。

---

## 其他 Chromium 系浏览器

`Edge` `Brave` `Vivaldi` `Chromium` `Arc` `Chrome Beta/Canary` 结构同 Chrome，但根目录不同：

```
~/Library/Application Support/Google/Chrome
~/Library/Application Support/Google/Chrome Beta
~/Library/Application Support/Microsoft Edge
~/Library/Application Support/BraveSoftware/Brave-Browser
~/Library/Application Support/Vivaldi
~/Library/Application Support/Chromium
~/Library/Application Support/Arc/User Data
```

`browser_scan.py` 已内置全部；支持 `--deep` 追加扫 HTTP 缓存。

---

## 建议的执行顺序

1. `python3 scripts/browser_scan.py` —— 只读，拿到完整命中清单
2. 把清单交用户确认（**尤其 autofill 里的 API key 属于敏感信息，只报存在性**）
3. 退出全部浏览器 → 轮询确认
4. `python3 scripts/chrome_purge.py --apply` —— SQL 精删 + VACUUM
5. `node scripts/ls_purge.js --apply` 或整目录删 `Local Storage`
6. 字节层面仍有命中的文件 → `bash scripts/trash_paths.sh` 整文件删
7. `python3 scripts/browser_scan.py` 复核；`python3 scripts/verify_reset.py` 断言
