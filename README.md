# Claude Client Full Reset

用于 macOS 上 Claude Code CLI 与 Claude Desktop 本地数据检查、备份和清理的 Agent Skill。

**状态：发布配置已准备，功能发布验收未完成。** 原始清理脚本存在错误处理与删除边界待修项，见 [发布任务卡](docs/release-tasks.md)。自动检查通过只表示结构和语法合格，不表示可以安全执行清理。

## 环境

- macOS；Windows / Linux 不属于清理脚本支持范围。
- Bash、Python 3，以及 macOS 的 `ditto`、`md5`、`osascript` 等工具。
- 仅 LevelDB 清理需要 Node.js 18+ 与 npm；依赖版本记录在 `package-lock.json`。
- 访问浏览器数据可能需要系统权限；无权限必须报告检查不完整。

## 安装

从仓库下载源码并解压，将包含 `SKILL.md`、`scripts/`、`references/` 的整个文件夹命名为 `claude-client-full-reset`，复制到对应工具的 skills 目录。若目标目录已存在，先检查现有版本，不要合并覆盖。

| 工具 | 用户级安装目录 |
| --- | --- |
| Codex（默认配置） | `~/.codex/skills/claude-client-full-reset/` |
| Claude Code | `~/.claude/skills/claude-client-full-reset/` |

Codex 设置了自定义 `CODEX_HOME` 时，使用该目录下的 `skills/`。安装后重新加载工具并确认 skill 已被发现。当前尚未完成两种工具的端到端加载测试。

需要 LevelDB 功能时，在安装后的 skill 文件夹中执行：

```bash
npm ci
```

安装依赖不会自动启动扫描、备份或删除。

## 使用

先提交仅检查的请求：

> 使用 claude-client-full-reset，只检查 Claude 本地数据并报告命中项，不执行删除。

在 Codex 中也可显式使用 `$claude-client-full-reset`。所有脚本命令都以 skill 文件夹为工作目录。

检查 → 备份 → 确认具体清单 → 清理 → 验收。任务授权必须对应具体清理范围；该 skill 包含修改浏览器数据库、移动文件和处理本地配置的操作。

本地清理无法删除服务端记录，也不能承诺获得“全新设备”身份、解除账号限制或清除磁盘上的所有物理痕迹。原包中的相关绝对表述仍需修订，见发布任务卡。

## 维护检查

```bash
python3 -m pip install -r requirements-dev.txt
python3 tools/check.py
```

检查内容：skill 元数据、内部引用、依赖锁文件一致性、Python / Bash / JavaScript 语法。检查器不执行清理脚本，不读取本机 Claude 或浏览器数据。GitHub Actions 在推送和拉取请求时执行同一检查。

## 目录

```text
SKILL.md                  技能入口
agents/openai.yaml        Codex 展示信息
scripts/                  原始检查、备份和清理脚本
references/               工作流参考
tools/check.py            发布结构与语法检查
docs/release-tasks.md     任务卡、验收与待修项
```

## 许可证

[MIT](LICENSE)。发布问题或提供示例时，不要上传登录凭证、浏览器数据库、备份或个人配置。
