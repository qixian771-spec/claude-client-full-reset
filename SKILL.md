---
name: claude-client-full-reset
description: 检测 macOS 与 Windows 上 Claude 安装与依赖并准备配置清单，检查、备份和清理 Claude Code 与 Claude Desktop 的本地数据；支持傻瓜式一键体检与补齐监测和上报（遥测）、域名、CDN、第三方、分流规则与 claude.ai 进程兜底（已有配置与规则不覆盖，先备份后只补缺失项）。适用于首次环境准备、分流与遥测补齐、检查残留或重置客户端；保留用户技能、设置、凭证和自动记忆的决定权，不承诺消除服务端记录、解除账号限制或物理擦除磁盘。
license: MIT
---

# Claude 环境检测与本地重置

支持 macOS 与 Windows 10/11；Python 3.10+。仅 LevelDB 功能另需 Node.js 18+ 与 `npm ci`。命令以本 skill/源码根目录为工作目录，执行代码应位于清理范围之外。

| 平台 | 运行 Python 入口 | 独立终端 | 移走方式 |
| --- | --- | --- | --- |
| macOS | `python3 scripts/<入口>.py`（`.sh` 包装等价） | Terminal / iTerm | Finder 废纸篓 |
| Windows | `py -3 scripts\<入口>.py`（没有 `.sh` 包装） | Windows Terminal / PowerShell | 回收站，仅本地固定磁盘 |

下文命令按 macOS 书写；Windows 把 `python3 scripts/` 换成 `py -3 scripts\`，路径换成 `C:\...` 形式。

## 必须先读与执行顺序

**先读 [AI 执行手册](references/agent-runbook.md)**，再选择本次路线。它定义输入、任务卡、命令前提、返回码、停止条件、验收和交付。不要把所有路线或命令示例串成自动流水线。

1. 提取用户目标、产品、平台、限制和已有授权；沿用此前已明确的信息，不重复确认。
2. 状态不明时只读检测，记录真实 JSON 与退出码；无法运行或读取失败就报告失败，不推断“未安装”。
3. 结合用户意图选 A 配置、B 检查、C 清理或 D 恢复；检测结果本身不授权写入。
4. 建立本次任务卡，再按所选路线执行；每步核对退出码和实际输出后才进入下一步。
5. 按该路线的标准验收并交付；失败保留现场与部分完成清单，不自动换实现或重跑。

## 入口及按需阅读

| 用户目标 | 入口/路线 | 执行前阅读 |
| --- | --- | --- |
| 首次使用、是否安装、依赖缺口 | `python3 scripts/check_environment.py --json`；必要时 A | [环境检测与配置](references/environment-check.md)、[首次准备](references/first-run.md) |
| 只检查残留 | B；浏览器扫描要求浏览器关闭 | [覆盖矩阵](references/coverage-matrix.md) |
| 写入前确认是否具备条件 | `python3 scripts/preflight.py`（只读，0 = 可以开始） | [执行手册](references/agent-runbook.md) |
| 已授权的具体文件/目录清理 | C：生成交接文件 `scripts/handover.py`，用户双击运行（前提自检 → 预览 → 确认 → 备份校验 → 执行 → 验收） | [执行手册 C1](references/agent-runbook.md#c1-交接独立终端)、[恢复说明](references/restore-and-rebuild.md) |
| SQLite/LevelDB 记录精删 | C4，明确浏览器与 profile 选择器 | [浏览器规则](references/browser-layer.md) |
| 恢复文件/目录 | D，优先选择明确 `--path`，先 `--dry-run` | [恢复说明](references/restore-and-rebuild.md) |
| 监测与上报（遥测）、域名/CDN、分流规则、第三方与 `claude.ai` 进程兜底（给 AI 的傻瓜式一键补齐，已有项不覆盖） | E：`python3 scripts/telemetry_routing.py --apply --auto-patch-proxy --json`（一键备份并补齐缺口） / `python3 scripts/telemetry_routing.py --json`（只读体检） | [监测与分流说明](references/telemetry-and-routing.md) |
| 错误、权限或部分完成 | 停止写入并保留证据 | [常见故障](references/pitfalls.md) |
| 带不懂技术的用户走完全程 | 按对话模板说话与停顿 | [对话模板](references/conversation.md) |
| 交付结果 | 按本次路线填写证据 | [证据报告](references/evidence-log.md) |

## 不可放宽的约束

- **错误停止。** 权限、进程查询、依赖、数据库、注册表或备份校验失败，不得解释为无痕迹、未安装或操作成功。禁止吞异常、`|| true`、切换复制/删除方式、伪造校验结果。
- **范围来自用户。** 只检查不等于允许删除。展示目标、影响及备份位置后，执行已有具体授权；不重复索要已明确的授权。新用户没有待清理数据时，不创建空备份、不转入重置。
- **不干扰当前工作。** 环境检测可在应用运行时做；备份、清理、恢复和最终清理验收要求退出相关应用（Windows 包括托盘里的 Claude 和后台运行的 Edge）。不擅自关闭软件或改变代理/防火墙/安全设置。Claude Code 自己也须退出，按手册交接独立终端，不绕过进程检查。
- **保护数据。** 实际移动、SQLite/LevelDB 修改必须提供覆盖目标且与当前内容一致的备份。默认保留技能、设置、agents、hooks、plugins、凭证；`.claude/projects` 含各项目的自动记忆，处理前单独确认。整个 `.claude` 的处理须单独明确授权。
- **写入显式。** 清理默认预览，执行需 `--apply --backup`；恢复使用 `--restore`，先 `--dry-run`，局部恢复明确 `--path`。恢复不能覆盖、合并或删除冲突目标。Windows 只移入本地固定磁盘的回收站，任何可能永久删除的情况都停止。
- **没有自动补救。** 多目标/多库没有统一事务；中途失败可能部分完成。保留备份和现场，指出已完成、失败、未执行项，不自动回滚、扩大范围或盲目重试。
- **结论限于证据。** 未发现不证明从未使用；找到安装路径不保证完整或能登录；本地检测不判断封禁或解除限制。`unclassified_items`、设置了 `CLAUDE_CONFIG_DIR`、浏览器记录、云端、其他用户等未覆盖范围必须明示。
- **不泄露数据。** 不输出 cookie/token、凭证内容、环境变量值、原始进程参数、Local Storage key/value；凭证只报告“存在/不存在”；备份不上传公开仓库。

## 两个容易出错的判断

`check_environment.py` 的 1 表示异常/依赖待处理；痕迹扫描的 1 表示命中需审阅；SQL/LevelDB 预览的 0 仍要读取匹配条数。准确规则见 [执行手册退出码表](references/agent-runbook.md#3-各命令退出码必须按入口解读)，不能套用一个统一的“非零=有痕迹”。

恢复后应验证目标与备份一致，不能为了清理扫描的 PASS 再删除恢复内容。用户只要求检测或检查时，在相应路线交付后结束，不自动执行后续写入。备份带平台标记，跨平台使用会被拒绝。
