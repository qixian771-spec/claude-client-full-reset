# 浏览器检查与精删

先退出浏览器。只读检查会流式搜索 `claude|anthropic`；命中是审阅线索，不是删除授权。每个 profile 递归检查，包括 Network/Cookies。SQLite 主文件和 WAL/journal 复制到临时目录，再查询副本；检查失败退出 2。缺少权限、损坏数据库或不支持的文件类型不能忽略。

## SQLite

`chrome_purge.py` 默认预览，在临时副本上按表、列检查文本中的 `claude.ai` / `anthropic.com` 及子域，包括 cookie 的 `.anthropic.com`。使用 OR 合并列条件，同一行只计数一次；表列标识符正确转义。

实际修改需要 `--apply --backup DIR`。备份需覆盖数据库及现存的 `-wal`、`-shm`、`-journal`。修改前预检所有数据库；触发器、外键或虚拟表的自动处理不受支持，会明确停止。不会关闭数据库约束，也不会在失败后改为整库删除。

每个数据库在事务内删除；SQL 失败回滚该库。成功提交后执行 VACUUM；VACUUM 失败仍退出非零，但已提交删除不会自动撤销。多库之间没有统一事务，后续库失败时可能已有前序库完成。

BLOB、schema 和已删除页中的关键词仅作为检查结果，不承诺全部消除；任意名称含“claude”的正常内容不会仅因词匹配被精删。

## LevelDB

安装锁定依赖 `npm ci`。浏览器可能先建好 `Local Storage/leveldb` 目录却从未写入，或建库到一半被中断（Windows 上的 Edge 实测出现过只有 `LOCK`、`LOG`、`MANIFEST-000001`）。LevelDB 先写 `MANIFEST` 再写 `CURRENT`，没有 `CURRENT` 时自身也视为库不存在；只有记录文件（`*.ldb`、`*.sst`、`*.log`）才存放键值。因此：没有 `CURRENT` 且没有任何记录文件时，输出 `[EMPTY]`、列出目录里的文件名，按 0 条处理、不打开；有记录文件却缺 `CURRENT` 视为可能损坏，报错停止并列出文件名。`ls_purge.js` 默认将数据库复制到私有临时目录再打开，保证预览不写原数据库；源在复制或预览期间变化会报错。

使用 Buffer 读取和删除键，避免 UTF-8 解码破坏二进制 key。只匹配服务域名 key，实际删除使用每库原子 batch 并复核键不存在。读取、写入、关闭或进程检查失败都会终止。日志只显示条数，不显示 key 或 value。

## Windows 说明

Chromium 根目录在 `%LOCALAPPDATA%\<厂商>\User Data`，Canary 为 `Chrome SxS`；不支持 Arc。Cookie 值在 Windows 上加密存储，但 `host_key` 等域名列是明文，SQLite 按域名精删照常工作。HTTP 缓存位于 profile 内，默认扫描已包含，`--deep` 不再额外扫描。`ls_purge.js` 通过 `py -3`（或 `CLAUDE_RESET_PYTHON`）调用 Python 获取浏览器根目录、检查进程和备份覆盖。

## Firefox

`browser_scan.py` 只读扫描各 profile 的 `places.sqlite`、`cookies.sqlite`、`webappsstore.sqlite`、`formhistory.sqlite`（快照查询），以及 `storage/default/` 下源为 claude.ai、anthropic.com（含子域、端口和容器后缀）的站点目录名。没有 Firefox 精删器；需要处理时按具体文件单独评估并备份。

## 选择范围

`--browser` 是显示名称（如 Chrome、Chrome Canary、Edge）；`--profile` 是目录名称。拼错浏览器参数或指定不存在的 profile 会失败，不会转为全量处理。不指定筛选参数意味着检查所有支持的 profiles，实际修改前仍需确认完整清单。

浏览器 Local State、Safari、缓存不是上述精删器的自动修改目标；是否移动具体文件必须单独评估并备份，不能将精删无命中理解为整个浏览器无痕迹。
