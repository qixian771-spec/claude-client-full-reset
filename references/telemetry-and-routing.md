# 监测与上报（遥测）、域名、CDN、第三方、分流规则与 `claude.ai` 进程兜底（给对方 AI 的傻瓜式一键指南）

本说明整合了 [Net.Coffee Claude Code 域名分流规则大全](https://ip.net.coffee/claude/site.html)、[Claude Code 稳定使用指南](https://ip.net.coffee/claude/claudecode.html)、[Claude 时区与设备信息自查教程](https://ip.net.coffee/claude/timezone.html) 以及 Claude 官方文档 [Enterprise network configuration](https://code.claude.com/docs/en/network-config)、[Data usage](https://code.claude.com/docs/en/data-usage)、[Monitoring](https://code.claude.com/docs/en/monitoring-usage)、[Environment variables](https://code.claude.com/docs/en/env-vars)。

核心原则：**“如果有的话就不用覆盖，补充缺点”**。对方 AI 从 GitHub 下载本仓库后，只需运行一条命令即可完成**只读体检 → 自动备份 → 增量补齐缺失的遥测关闭项与分流/进程兜底规则**。

## 1. 给对方 AI 的傻瓜式一键命令

在仓库或已安装 skill 根目录直接执行（无需先关闭正在运行的 Claude 或浏览器）：

| AI 执行目标 | macOS / Linux 命令 | Windows 命令 |
| --- | --- | --- |
| **一键补齐全部缺口（推荐 AI 直接跑）**：补齐 `~/.claude/settings.json` 缺失遥测项 + 生成 4 种格式规则集 + 自动把缺失规则注入本机 Clash Verge `Merge.yaml`/`config.yaml`（均先自动备份，已有项不覆盖） | `python3 scripts/telemetry_routing.py --apply --auto-patch-proxy --json` | `py -3 scripts\telemetry_routing.py --apply --auto-patch-proxy --json` |
| **仅补齐 `settings.json` 并生成规则集文件**（不直接改代理客户端原配置） | `python3 scripts/telemetry_routing.py --apply --json` | `py -3 scripts\telemetry_routing.py --apply --json` |
| **指定某个 Clash/Mihomo 配置文件增量补齐** | `python3 scripts/telemetry_routing.py --apply --proxy-config /absolute/config.yaml` | `py -3 scripts\telemetry_routing.py --apply --proxy-config C:\absolute\config.yaml` |
| **只读体检（不写任何文件）** | `python3 scripts/telemetry_routing.py --json` | `py -3 scripts\telemetry_routing.py --json` |
| **生成桌面双击运行文件给用户点** | `python3 scripts/telemetry_routing.py --launcher` | `py -3 scripts\telemetry_routing.py --launcher` |

可选参数：

- `--proxy-group 策略组名`：默认 `Proxy`；若用户的 Clash 策略组叫 `Claude` 或 `🚀 节点选择`，传入 `--proxy-group "Claude"` 即可。
- `--telemetry-policy proxy|reject`：默认 `proxy`（按照 [Net.Coffee 监测和上报规则](https://ip.net.coffee/claude/site.html) 将 Sentry / Statsig / Datadog / Sift 等监控上报走同一代理出口，防止上报 IP 与请求 IP 不一致触发风控；同时在本地 `settings.json` 关闭 CLI 遥测）；若纯 API 用户希望在代理层直接拦截遥测，可传 `--telemetry-policy reject`（此时 `sift` 反欺诈仍保持走代理以防封号）。
- `--include-optional`：额外补齐 `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`、`CLAUDE_CODE_ATTRIBUTION_HEADER=0`、`ENABLE_CLAUDEAI_MCP_SERVERS=false`、`CLAUDE_CODE_DISABLE_ARTIFACT=1`。

## 2. 六大模块完整补齐清单

### 模块 ①：本地遥测与上报关闭配置（`~/.claude/settings.json`）

`scripts/telemetry_routing.py --apply` 会在 `~/.claude/` 下先创建带 SHA-256 校验的私有备份 `settings.privacy-backup-<时间戳>.json`，再向 `env` 补充**尚未配置**的键（用户已有的键、第三方网关 `ANTHROPIC_BASE_URL`、权限、hooks 等原样保留，绝不覆盖）：

| 环境变量键 | 默认补齐值 | 作用说明（依据官方 [Data usage](https://code.claude.com/docs/en/data-usage) 与 [Environment variables](https://code.claude.com/docs/en/env-vars)） |
| --- | --- | --- |
| `DISABLE_TELEMETRY` | `"1"` | 关闭使用率指标上报、Statsig/GrowthBook 遥测与 Datadog 运营日志 |
| `DISABLE_ERROR_REPORTING` | `"1"` | 关闭内部错误堆栈与崩溃上报（Sentry / Datadog） |
| `DISABLE_FEEDBACK_COMMAND` | `"1"` | 禁用 `/feedback`、`/bug`、`/share` 命令上传会话记录 |
| `DISABLE_BUG_COMMAND` | `"1"` | 兼容禁用旧版 `/bug` 命令上传 |
| `CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY` | `"1"` | 禁用会话质量调查弹窗及后续聊天记录上传追问 |
| `DO_NOT_TRACK` | `"1"` | 通用 Do Not Track 标记（官方文档支持用于关闭调查与运营遥测） |
| `CLAUDE_CODE_ENABLE_TELEMETRY` | `"0"` | 关闭 OpenTelemetry (OTel) 采集总开关 |
| `CLAUDE_CODE_ENABLE_FEEDBACK_SURVEY_FOR_OTEL` | `"0"` | 禁止通过 OTel 导出会话调查评分 |
| `OTEL_METRICS_EXPORTER` | `"none"` | 禁用 OTel 指标导出器 |
| `OTEL_LOGS_EXPORTER` | `"none"` | 禁用 OTel 日志/事件导出器 |
| `OTEL_TRACES_EXPORTER` | `"none"` | 禁用 OTel 分布式追踪导出器 |

### 模块 ②：核心域名与认证服务（Core Domains & Auth）

同时覆盖分流规则与浏览器 SQLite（`chrome_purge.py`）、LevelDB（`ls_purge.js`）、Firefox（`browser_scan.py`）扫描：

| 规则类型 | 域名 | 用途说明 |
| --- | --- | --- |
| `DOMAIN-SUFFIX` | `anthropic.com` | Anthropic 主域（涵盖 `api`、`console`、`workbench`、`mcp`、`docs`、`support` 等全部子域） |
| `DOMAIN-SUFFIX` | `claude.ai` | Claude 网页版与桌面端主域（涵盖 `claude.ai`、`api`、`downloads`、`assets`、`preview`） |
| `DOMAIN-SUFFIX` | `claude.com` | Claude 备用与平台主域（涵盖 `platform`、`code`、`docs`、`support`、`status.claude.com` 及 `*.mcp.claude.com`） |
| `DOMAIN-SUFFIX` | `clau.de` | Claude 官方短域名（CLI 输出与重定向） |
| `DOMAIN-SUFFIX` | `claudemcpclient.com` | Claude MCP 客户端通信域名 |
| `DOMAIN-SUFFIX` | `claudemcpcontent.com` | Claude Desktop 与网页端交互式 MCP 组件内容分发（`*.claudemcpcontent.com`） |
| `DOMAIN-SUFFIX` | `claudeusercontent.com` | 用户内容、附件、Chrome 扩展桥接（`bridge.claudeusercontent.com`）与 Artifact（`*.frame.claudeusercontent.com`） |
| `DOMAIN-SUFFIX` | `modelcontextprotocol.io` | MCP 协议官方站点与规范资源 |
| `DOMAIN` | `api.anthropic.com`、`platform.claude.com`、`console.anthropic.com`、`workbench.anthropic.com`、`mcp.anthropic.com`、`mcp-proxy.anthropic.com`、`bridge.claudeusercontent.com` | 核心 API、OAuth 令牌交换、控制台、远端 MCP 代理与 Chrome 扩展桥接（官方要求 `bridge.claudeusercontent.com` 必须与主站同代理出口） |
| `DOMAIN` | `anthropic.auth0.com`、`anthropic-com.ghost.io` | OAuth 登录认证服务与官方博客/CMS 内容 |

### 模块 ③：CDN 与静态资源基础设施（CDN & Static Assets）

| 规则类型 | 域名 | 用途说明 |
| --- | --- | --- |
| `DOMAIN` | `cdn.anthropic.com` | Anthropic 官方 CDN 资源 |
| `DOMAIN` | `assets-proxy.anthropic.com` | Claude Desktop 与 `claude.ai` 加载前端应用代码的核心 CDN（阻断会导致客户端白屏） |
| `DOMAIN` | `anthropic.com.cdn.cloudflare.net` | Anthropic Cloudflare CDN 回源与边缘节点 |
| `DOMAIN` | `servd-anthropic-website.b-cdn.net` | Anthropic 网站 BunnyCDN 静态资源 |
| `DOMAIN` | `downloads.claude.ai` | Claude Code 原生安装器、自动更新与插件二进制下载 CDN |
| `DOMAIN` | `assets.claude.ai` | `claude.ai` 静态资源 CDN |
| `DOMAIN` | `storage.googleapis.com` | Claude Code 插件元数据与旧版安装器分发 GCS 存储桶 |

### 模块 ④：监测和上报 / 遥测（Monitoring, Telemetry & Anti-Fraud）

依据 [Net.Coffee 监控和数据上报栏](https://ip.net.coffee/claude/site.html) 与 [官方网络配置文档](https://code.claude.com/docs/en/network-config)：

| 规则类型 | 域名 / 关键词 | 关键细节与原因 |
| --- | --- | --- |
| `DOMAIN` | `http-intake.logs.us5.datadoghq.com` | Claude Code 官方公布的 Datadog 运营遥测接收端 |
| `DOMAIN` / `DOMAIN-SUFFIX` | `browser-intake-us5-datadoghq.com` | Datadog RUM 前端性能与错误上报精确域名（注意中间是连字符 `-` 而非 `.`，`DOMAIN-SUFFIX,datadoghq.com` 抓不到它，必须单列） |
| `DOMAIN` | `o1158394.ingest.us.sentry.io` | Claude Desktop 专用 Sentry 崩溃与 minidump 上报端点 |
| `DOMAIN` | `a-api.anthropic.com`、`s-cdn.anthropic.com`、`a-cdn.anthropic.com` | Anthropic 第一方子域代理的 Segment 统计上报（`/v1/b`）与追踪像素（`/s.js`） |
| `DOMAIN-SUFFIX` | `sentry.io`、`statsigapi.net`、`statsig.com`、`datadoghq.com`、`datadoghq.eu`、`ddog-gov.com`、`segment.io`、`segment.com` | Sentry 错误追踪、Statsig 功能开关/AB 测试、Datadog 各区监控与 Segment 埋点后缀 |
| `DOMAIN` | `cdn.growthbook.io` | GrowthBook A/B 测试与功能门控配置 |
| `DOMAIN-KEYWORD` | `datadog`、`sentry`、`sift` | 跨区域监控端点（如切换 `us3`/`eu1`/`ap1`）与 **Sift 反欺诈检测**关键词通配兜底（保证与 Claude 主请求同出口，防止 IP 分裂触发风控） |

### 模块 ⑤：第三方客服、验证、支付与 Artifact 前端库（Third-Party）

| 规则类型 | 域名 | 用途说明 |
| --- | --- | --- |
| `DOMAIN-SUFFIX` | `intercom.io`、`intercomcdn.com` | Intercom 在线客服 widget 与静态资源（含 `nexus-websocket-a.intercom.io`） |
| `DOMAIN` | `cdn.usefathom.com` | Fathom 访问统计 |
| `DOMAIN-SUFFIX` | `stripe.com`、`hcaptcha.com` | Stripe 订阅支付环境校验与 hCaptcha 登录人机验证 |
| `DOMAIN` | `cdnjs.cloudflare.com`、`cdn.jsdelivr.net`、`cdn.tailwindcss.com`、`code.jquery.com`、`unpkg.com`、`fonts.googleapis.com`、`fonts.gstatic.com` | 官方文档列明的 Artifact 第三方 JS 库（React/图表/Tailwind 等）与 Google Fonts 字体主机 |

### 模块 ⑥：分流兜底（IP/Geosite/NTP）与 `claude.ai` 进程兜底（`PROCESS-NAME`）

| 类别 | 规则 | 为什么需要 |
| --- | --- | --- |
| **Anthropic IP 兜底** | `IP-CIDR,160.79.104.0/21,{proxy},no-resolve`<br>`IP-CIDR6,2607:6bc0::/32,{proxy},no-resolve` | 当 DoH/ECH 加密或未知新子域绕过域名匹配时，按 Anthropic 自有 IPv4/IPv6 段兜底。**不用 `IP-ASN,399358`**：mihomo 要先联网下载 ASN.mmdb，新机器还没有代理时下载超时，整份配置验证失败、Clash 退回最小配置 |
| **Geosite 与 NTP 时区防泄露** | `GEOSITE,anthropic,{proxy}`<br>`GEOSITE,category-ntp,{proxy}` | 覆盖 `geosite:anthropic` 分类，并将 UDP NTP 时间同步纳入代理出口，防止系统校时直连暴露真实时区 |
| **`claude.ai` 客户端与 CLI 进程兜底** | macOS / Linux：`PROCESS-NAME,Claude`、`Claude Helper`、`Claude Helper (Renderer)`、`Claude Helper (GPU)`、`Claude Helper (Plugin)`、`chrome-native-host`、`claude`<br>Windows：`PROCESS-NAME,Claude.exe`、`claude.exe`、`chrome-native-host.exe` | 桌面端承载 `claude.ai` 会话、内置任务引擎与 CLI 子进程在发起直接连接、WebSocket 桥接或非域名流量时，按进程名强制走同一代理出口，彻底堵死直连漏出 |

## 3. 生成的 4 种规则文件（位于 `~/.claude/routing-rules/`）

执行 `--apply` 后会自动生成以下 4 个文件，方便不同代理软件直接使用：

1. `claude-routing-supplement.yaml`：**仅包含本机当前缺失的规则**（已有规则不重复覆盖），可直接粘贴到 Clash Verge 的 `Merge.yaml`；
2. `claude-routing-full.yaml`：完整的 Clash / Mihomo `prepend-rules:` 规则模板；
3. `claude-routing.list`：适用于 Surge / Shadowrocket / Quantumult X / Loon 的 classical `RULE-SET` 列表；
4. `claude-routing-singbox.json`：适用于 sing-box 的 `version: 2` 结构化规则集 JSON。

## 4. 已知限制（AI 必须如实报告）

- “规则是否已存在”是把默认目录下**所有** Clash/Mihomo YAML（含未激活的 profile 与 Merge/Script 覆写）合并后判断的。某条规则只写在未激活配置里也会被算作“已有”；要精确到当前生效配置，用 `--proxy-config` 指定那一个文件。
- `--auto-patch-proxy` 的目标：先读 Clash Verge 的 `profiles.yaml`，`current` 指向哪个 profile 就写它的文件（这是唯一保证进生成配置的地方；profile 绑定的脚本可能会删掉 `prepend-rules`，所以不写全局 Merge.yaml）；没有 `profiles.yaml` 才退回 `profiles/Merge.yaml` / `Merge.yaml` / `config.yaml`。报告里 `proxy_config_patch.path` 写明实际改了哪个文件。
- `--auto-patch-proxy` / `--proxy-config` 插入规则时沿用目标文件里该列表已有的缩进（Clash Verge 生成的 `rules:` 为 0 缩进，Merge.yaml 模板为 2 缩进）；列表为空时用键缩进 + 2。插入后请用 `verge-mihomo -t -f <文件>`（或重新激活配置）验证能加载。
- 本工具不改代理分组、不切节点、不重启核心；补齐后由 Clash Verge 重新激活配置才生效。
