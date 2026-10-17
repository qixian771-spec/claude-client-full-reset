# 0.3.0 Windows 适配验收

- macOS 与 Windows 10/11 共用同一套规则；平台差异只在 `scripts/platforms.py` 与 `scripts/winplat.py`。
- Windows：系统 PowerShell 查询进程；严格复制备份/恢复；本地固定磁盘回收站；junction、重解析点、UNC 一律拒绝；MSIX 数据只允许处理 `LocalCache\Roaming\Claude(-3p)`。
- 两平台：官方文档分类的 `.claude` 痕迹/资产、`unclassified_items`、自动记忆提示、凭证位置存在性、`CLAUDE_CONFIG_DIR` 提示、Firefox 只读扫描；macOS 不再把 `.app` 内独立扩展/XPC 当作应用在运行。

## 测试与验收

| 验收项 | 结果 |
| --- | --- |
| Python（macOS 本地） | 174 项通过，6 项为 Windows 原生测试在 macOS 跳过 |
| JavaScript | 16 项通过 |
| GitHub Actions | ubuntu-24.04、macos-14（Py 3.10/3.12）、windows-2022（Py 3.10/3.12，Node 18/22）全部通过 |
| Windows 原生 | 进程查询、junction 拒绝、UNC/设备路径拒绝、大小写变体拒绝、回收站（核对原始位置）、真实环境检测；smoke 与浏览器只读预览在 runner 自己的 profile 上通过，并实测到一次 `[EMPTY]` |
| macOS 原生（runner） | smoke（路径、进程、检测、凭证）与浏览器只读预览通过 |
| macOS 本机 | 检测 `installed`、退出 0；钥匙串凭证项存在（只查属性）；浏览器扫描在 Chromium 部分完成，读 Safari `History.db` 因宿主无“完全磁盘访问权限”被拒，按设计退出 2 |
| Windows 实机 | Windows 10 专业工作站版 19045 x64、Python 3.11、提交 `3d88ec7` 经 SSH 部署到临时目录（SHA-256 核对一致）。环境检测退出 0：`installed`，识别 MSIX 包 `Claude_pzs8sxrjxfjjc` 及包内 `LocalCache\Roaming\Claude(-3p)`、PATH 上 npm 安装的 `claude.cmd`、2 个未归类项、1 个含自动记忆的项目，无 issues。后台 9 个 `msedge.exe` 阻止扫描（经用户同意强制结束）后，完整只读扫描 95 秒完成、退出 1：客户端数据 13、浏览器 36（Chrome 3、Edge 33，含 SQLite、LevelDB、IndexedDB、缓存），编辑器、系统目录、shell 与注册表变量名均 CLEAR |
| macOS 本机（终端，完全磁盘访问） | 提交 `72f1148`，浏览器已退出，在已授予“完全磁盘访问权限”的 Terminal.app 中运行 `scan_readonly.py`：退出 1、无报错；客户端数据 17、编辑器 2（Code/Cursor state.vscdb）、系统指定目录 1（`~/Applications` 中的 Claude Code URL Handler）、shell CLEAR、浏览器 87（Chrome 8 个 profile 85、Safari History.db 与 RecentlyClosedTabs.plist）。同一命令在 Claude App 内置终端运行时因宿主没有该权限读 `~/.Trash` 被拒、退出 2，符合设计 |

全部验收项均已实际执行。所有写入类测试只在临时夹具或 runner 的一次性数据上进行。

# 0.2.0 环境检测验收

- 新增 `scripts/check_environment.py`：常见 Desktop/CLI 候选路径、本地配置/数据位置、命令依赖路径和进程数量；支持文本及 JSON。
- 未发现、安装候选、仅有数据、需审阅异常四种报告；缺少基础工具返回 1，读取或进程查询失败返回 2，不降级为未安装。
- 区分首次准备、已有环境维护和残留审阅；仅安装 skill 不当作 Claude 使用。检测期间无需退出应用，不启动 Claude、不联网、不写设置或安装依赖。
- 官方安装指引区分 Desktop、Claude Code 和本 skill；检测不判断账号状态、不证明从未使用或解除限制。

## 测试与验收

| 验收项 | 结果 |
| --- | --- |
| Python | 85 项通过：原 47 项、局部恢复新增 19 项、环境检测新增 19 项 |
| JavaScript | 10 项通过 |
| 安装后的环境检测 | 5 组合成场景通过：新环境、仅 skill、Desktop 目录、残留、损坏 CLI 链接；文件状态不变 |
| 打包与入口 | 新检测器帮助入口、安装包相对链接和技能元数据检查通过 |
| 保密与不执行 | 凭证内容未读取；环境变量值、进程参数不输出；可执行候选不运行 |
| 错误分支 | 权限失败、进程查询失败、PATH 非目录、未知数据、损坏链接、缺基础依赖、非 macOS CLI 均按预期处理 |

检测只确认候选路径和当前 Python 版本。其他工具版本、真实启动/登录、浏览器/云端使用、自定义安装和目录不在本次检测验证范围。测试使用合成目录与进程记录，不为验收而读取或修改用户真实 Claude 数据。

0.1.1 提交 `080fc23` 已通过 [三组 GitHub CI](https://github.com/qixian771-spec/claude-client-full-reset/actions/runs/38309891542)，包括 Python 3.10 / Node 18。0.2.0 同样使用该三组工作流；本版本具体提交的实际结果见 [Actions](https://github.com/qixian771-spec/claude-client-full-reset/actions/workflows/validate.yml)。

---

# 0.1.1 使用准备与局部恢复验收

## 变更与验收范围

- 新增恢复 `--path`（可重复、支持来源内子路径）、`--dry-run` 和校验后 `--list`。
- 保留全备份校验、退出应用、拒绝覆盖、复制校验和错误停止；路径选择不正确不转为整包恢复。
- 新增独立终端交接、首次依赖及 macOS 权限准备；说明 Claude Code 技能宿主与 Claude Desktop 清理对象的区别。
- 安装包带 README、首次准备、恢复指南和验收说明，所有相对文档链接一并校验。

## 本地验收

环境：macOS、Python 3.13.7、Node.js 24.15.0。

| 验收项 | 结果 |
| --- | --- |
| Python 隔离测试 | 66 项通过，其中 19 项为新增局部恢复回归测试 |
| JavaScript 隔离测试 | 10 项通过 |
| Skill 元数据与脚本语法 | tools/check.py 与 skill-creator quick_validate.py 通过 |
| 原生复制与恢复 | 使用真实 ditto 恢复夹具文件、目录及目录内链接；保留配置内容一致 |
| 新安装后命令验收 | 8 项通过：备份、校验、列来源、预览、局部恢复、拒绝覆盖、拒绝未知选择、恢复后再次校验备份 |
| 安装后 LevelDB 依赖 | npm ci 与 classic-level 加载通过 |
| 安装包文档 | 检查所有 Markdown 相对链接，不存在缺失目标 |

新增测试验证：局部恢复保留 shell/设置；嵌套文件和目录；预览不创建目标或父目录；空选择/未知路径不变成整包恢复；整批预检；拒绝现有目标、重复/父子重叠/穿越和符号链接；未选择的备份损坏仍失败；复制失败、校验失败及现场变化立即停止；目的路径独占创建；活跃 Claude 阻断；CLI 参数组合与真实 ditto 往返。

安装后 CLI 验收使用独立进程、任务专属合成家目录和模拟的空进程列表，实际复制调用系统 ditto。真实进程拒绝行为由独立注入测试覆盖，不意味着本次退出过用户应用。

## CI 与适用边界

本次工作流包含三组：macOS 14 / Python 3.10 / Node 18、macOS 14 / Python 3.12 / Node 22、Ubuntu 24.04 / Python 3.12 / Node 22。对应提交的实际结果以 [GitHub Actions](https://github.com/qixian771-spec/claude-client-full-reset/actions/workflows/validate.yml) 为准；本地验收不替代远端结果。Ubuntu 明确跳过两项 macOS ditto 原生测试，实际清理仍只支持 macOS。

本次不读写真实 Claude/浏览器数据，不重启或关闭正在使用的软件，不更改代理、防火墙或系统隐私权限。未触发新的 macOS 隐私授权弹窗，未重复执行 Finder 原生移动；这部分沿用下方历史原生验收及官方权限说明，不宣称在所有用户权限环境复现。

最低版本兼容性由新增 CI 检查；不承诺未来所有浏览器 schema 均可精删。不支持的 schema、权限和进程状态仍停止。恢复失败可能留下已恢复的前序目标与当前不完整目标，操作指南明确要求保留现场后审阅，不自动清除或重试。

---

# 0.1.0 测试与验收

## 本地验收

- 环境：macOS，Python 3.13，Node.js 24。
- Python：47 项测试通过。
- JavaScript：10 项测试通过。
- 原生集成：真实 `ditto` 复制临时文件和符号链接后验证 SHA-256；通过。
- 原生 Finder：仅使用任务创建的临时文件，实际移入废纸篓后恢复，内容一致；通过，测试数据已清理。
- 安装：复制到隔离目录，检查入口及引用结构，运行安装后全部 Python/Bash 入口的 `--help`；已有目标和符号链接父目录拒绝覆盖。
- 测试未扫描、备份或清理开发者真实 Claude / 浏览器数据。

## 行为验收

| 任务 | 证据 | 结论 |
| --- | --- | --- |
| R1 备份 | 复制失败、源变化、损坏副本、重复来源、额外来源、SHA-256 校验、符号链接、拒绝覆盖恢复、恢复往返 | 通过 |
| R2 扫描 | 权限失败传播、目录遍历失败、损坏 JSON/SQLite、跨块计数、所有 profiles、Network/Cookies、WAL 快照、敏感值不输出 | 通过 |
| R3 移动 | 危险路径变体、路径穿越、符号链接、全批预检、无备份拒绝、失败后停止、引号路径通过 argv 传递、真实 Finder 往返 | 通过 |
| R4 数据库 | SQL 唯一行计数、无关记录保留、转义表列、事务回滚、VACUUM 失败报告、复杂 schema 拒绝；LevelDB 原始二进制键、只读预览、损坏库、读写失败与资源关闭 | 通过 |
| R5 分发 | 安装器隔离安装、不覆盖、入口加载、文档同步、依赖锁定 | 通过 |

## 适用边界

测试使用可控 SQLite / LevelDB 夹具，不代表每个浏览器未来版本的 schema 都兼容；不支持的 schema 明确拒绝，不能绕过。仓库安装和命令加载已验证，Agent 自动选择技能的行为仍由所用客户端决定。

原包的“全盘无痕迹”“全新设备”承诺已删除。自动范围以 `references/coverage-matrix.md` 为准；不自动处理钥匙串、LaunchServices、快照、任意项目和其他用户数据。废纸篓移动与逻辑删除不是物理擦除。

多路径和多库不构成全局事务；发生中途错误时前序目标可能已经处理。备份与执行记录必须保留，不能将局部完成报告成全部成功。

## GitHub 验证

代码提交 `904ffb6` 已通过 [GitHub Actions](https://github.com/qixian771-spec/claude-client-full-reset/actions/runs/38085182935)：

- macOS 14 / Python 3.12 / Node.js 22：结构检查、47 项 Python 测试、10 项 JavaScript 测试通过。
- Ubuntu 24.04 / Python 3.12 / Node.js 22：结构检查通过；Python 测试 46 项通过、1 项 macOS 原生 ditto 测试按平台明确跳过；10 项 JavaScript 测试通过。
- Finder 原生往返在本机完成，未声称 GitHub 无界面 runner 执行过该交互。

本次功能修复完成所定义范围的测试与验收；使用者仍需按实际目标完成自己的备份和清理验收。
