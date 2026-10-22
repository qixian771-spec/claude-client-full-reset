#!/usr/bin/env python3
"""AI-ready one-click inspection and non-destructive supplementation for Claude telemetry, domains, CDN, routing rules, third-party services, and claude.ai process fallback.

Designed for direct AI execution after cloning from GitHub:
- Read-only by default: inspects ~/.claude/settings.json telemetry/reporting
  variables, third-party gateway presence (never reading or printing secret
  values), local timezone risk signals, and local Clash/Mihomo/Surge routing
  configs across all 6 modules:
    1. 核心域名 (Domains)
    2. CDN 与静态/认证基础设施 (CDN)
    3. 监测和上报 / 遥测 (Telemetry & Monitoring)
    4. 第三方组件与前端库/客服 (Third-party)
    5. 分流规则与 IP/ASN/NTP 兜底 (Routing & IP/ASN/NTP Fallback)
    6. claude.ai 客户端与 CLI 进程兜底 (Process Fallback)
- Auto-detects the existing proxy group name (e.g., from an existing claude.ai
  or anthropic.com rule in the user's Clash/Mihomo config) when --proxy-group
  is not explicitly passed, guaranteeing zero group-name mismatch and consistent
  proxy egress.
- --apply supplements ONLY missing items ("如果有的话就不用覆盖，补充缺点"):
    * Existing keys in ~/.claude/settings.json are never overwritten.
    * Verified private backup is created before touching ~/.claude/settings.json.
    * Generates Clash/Mihomo YAML (missing-only supplement + full payload),
      Surge/Shadowrocket .list, and sing-box v2 JSON rule-set in ~/.claude/routing-rules/.
    * With --auto-patch-proxy or --proxy-config, backs up the target Clash/Mihomo
      YAML file and injects only missing rules without duplicating existing ones.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

import common
import platforms

ROOT = Path(__file__).resolve().parents[1]
CONFIRM = '是'
DEFAULT_PROXY_GROUP = 'Proxy'

# Official Claude Code telemetry & reporting opt-out variables
# (https://code.claude.com/docs/en/data-usage, monitoring-usage, env-vars).
TELEMETRY_ENV_SPEC = (
    ('DISABLE_TELEMETRY', '1', '关闭使用率指标上报、Statsig/GrowthBook 功能门控遥测与 Datadog 运营日志'),
    ('DISABLE_ERROR_REPORTING', '1', '关闭内部错误堆栈与崩溃上报 (Sentry / Datadog)'),
    ('DISABLE_FEEDBACK_COMMAND', '1', '禁用 /feedback、/bug、/share 命令上传会话历史'),
    ('DISABLE_BUG_COMMAND', '1', '兼容禁用旧版 /bug 命令上传'),
    ('CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY', '1', '禁用会话质量调查与聊天记录上传追问'),
    ('DO_NOT_TRACK', '1', '通用 Do Not Track 声明（官方 data-usage 文档支持用于关闭调查与运营遥测）'),
    ('CLAUDE_CODE_ENABLE_TELEMETRY', '0', '关闭 OpenTelemetry (OTel) 采集总开关'),
    ('CLAUDE_CODE_ENABLE_FEEDBACK_SURVEY_FOR_OTEL', '0', '禁止通过 OTel 导出会话调查评分'),
    ('OTEL_METRICS_EXPORTER', 'none', '禁用 OTel 指标导出器'),
    ('OTEL_LOGS_EXPORTER', 'none', '禁用 OTel 日志/事件导出器'),
    ('OTEL_TRACES_EXPORTER', 'none', '禁用 OTel 分布式追踪导出器'),
)

# Optional settings/env switches documented in network-config & env-vars.
OPTIONAL_PRIVACY_SPEC = (
    ('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', '1', '一键关闭全部非必要流量（注意：会连带关闭自动更新与部分远程功能标记）'),
    ('CLAUDE_CODE_ATTRIBUTION_HEADER', '0', '移除系统提示词开头的客户端版本与提示词指纹归属块'),
    ('ENABLE_CLAUDEAI_MCP_SERVERS', 'false', '停止默认拉取 claude.ai 远端 MCP 连接器 (mcp-proxy.anthropic.com)'),
    ('CLAUDE_CODE_DISABLE_ARTIFACT', '1', '禁用 Artifact 工具以减少 *.frame.claudeusercontent.com 请求'),
)

# Third-party provider / gateway keys: presence is reported, values are NEVER printed or overwritten.
THIRD_PARTY_PROVIDER_KEYS = (
    'ANTHROPIC_BASE_URL',
    'ANTHROPIC_AWS_BASE_URL',
    'ANTHROPIC_BEDROCK_BASE_URL',
    'ANTHROPIC_VERTEX_BASE_URL',
    'ANTHROPIC_FOUNDRY_BASE_URL',
    'CLAUDE_CODE_USE_BEDROCK',
    'CLAUDE_CODE_USE_VERTEX',
    'CLAUDE_CODE_USE_FOUNDRY',
    'CLAUDE_CODE_USE_ANTHROPIC_AWS',
)

# Complete 6-module catalog combining:
# - https://ip.net.coffee/claude/site.html (监测和上报、核心域名、CDN、认证、客服/第三方、IP/ASN/NTP 兜底)
# - https://code.claude.com/docs/en/network-config & data-usage & monitoring-usage
# - https://github.com/xiaolai/anthropic-claude-surge-rules-set
# - Local static bundle audit (Claude Desktop & Claude Code CLI)
RULE_MODULES = (
    ('domains', '1. 核心域名与认证服务 (Core Domains & Auth)', (
        ('DOMAIN-SUFFIX', 'anthropic.com', '{proxy}', 'Anthropic 主域（涵盖 api/console/workbench/mcp/docs/support/status.anthropic.com 等全部子域）'),
        ('DOMAIN-SUFFIX', 'claude.ai', '{proxy}', 'Claude 网页版与桌面端主域（涵盖 claude.ai、api/downloads/assets/preview.claude.ai）'),
        ('DOMAIN-SUFFIX', 'claude.com', '{proxy}', 'Claude 备用与平台主域（涵盖 platform/code/docs/support/status.claude.com 及 *.mcp.claude.com）'),
        ('DOMAIN-SUFFIX', 'clau.de', '{proxy}', 'Claude 官方短域名（CLI 输出与链接重定向）'),
        ('DOMAIN-SUFFIX', 'claudemcpclient.com', '{proxy}', 'Claude MCP 客户端通信域名'),
        ('DOMAIN-SUFFIX', 'claudemcpcontent.com', '{proxy}', 'Claude Desktop 与网页端交互式 MCP 组件内容分发 (*.claudemcpcontent.com)'),
        ('DOMAIN-SUFFIX', 'claudeusercontent.com', '{proxy}', 'Claude 用户内容、附件、Chrome 扩展桥接 (bridge) 与 Artifact (*.frame.claudeusercontent.com)'),
        ('DOMAIN-SUFFIX', 'modelcontextprotocol.io', '{proxy}', 'MCP 协议官方站点与规范资源'),
        ('DOMAIN', 'api.anthropic.com', '{proxy}', 'Claude 核心 API、OAuth 与 WebFetch 安全预检'),
        ('DOMAIN', 'platform.claude.com', '{proxy}', 'Console 认证与 claude.ai OAuth 令牌交换/刷新'),
        ('DOMAIN', 'code.claude.com', '{proxy}', 'Claude Code 官方文档与 CLI 内置文档查询'),
        ('DOMAIN', 'console.anthropic.com', '{proxy}', 'Anthropic 开发者控制台'),
        ('DOMAIN', 'workbench.anthropic.com', '{proxy}', 'Anthropic Workbench 调试台'),
        ('DOMAIN', 'docs.anthropic.com', '{proxy}', 'Anthropic 开发者文档'),
        ('DOMAIN', 'docs.claude.com', '{proxy}', 'Claude 官方文档站'),
        ('DOMAIN', 'support.anthropic.com', '{proxy}', 'Anthropic 帮助与支持中心'),
        ('DOMAIN', 'support.claude.com', '{proxy}', 'Claude 帮助与支持中心'),
        ('DOMAIN', 'status.anthropic.com', '{proxy}', 'Anthropic 服务状态页'),
        ('DOMAIN', 'status.claude.com', '{proxy}', 'Claude 服务状态页'),
        ('DOMAIN', 'mcp.anthropic.com', '{proxy}', 'Anthropic MCP 服务端点'),
        ('DOMAIN', 'mcp-proxy.anthropic.com', '{proxy}', 'claude.ai 远端 MCP 连接器代理'),
        ('DOMAIN', 'bridge.claudeusercontent.com', '{proxy}', 'Chrome 扩展 WebSocket 桥接（官方要求须与主站走同一代理出口 IP）'),
        ('DOMAIN', 'anthropic.auth0.com', '{proxy}', 'Anthropic OAuth 登录认证服务'),
        ('DOMAIN', 'anthropic-com.ghost.io', '{proxy}', 'Anthropic 博客与 CMS 内容服务'),
    )),
    ('cdn', '2. CDN 与静态资源基础设施 (CDN & Static Assets)', (
        ('DOMAIN', 'cdn.anthropic.com', '{proxy}', 'Anthropic 官方 CDN 资源'),
        ('DOMAIN', 'assets-proxy.anthropic.com', '{proxy}', 'Claude Desktop 与 claude.ai 前端代码与静态资源核心 CDN（阻断会导致白屏）'),
        ('DOMAIN', 'anthropic.com.cdn.cloudflare.net', '{proxy}', 'Anthropic Cloudflare CDN 节点'),
        ('DOMAIN', 'servd-anthropic-website.b-cdn.net', '{proxy}', 'Anthropic 网站 BunnyCDN 静态资源'),
        ('DOMAIN', 'downloads.claude.ai', '{proxy}', 'Claude Code 原生安装器、自动更新与插件二进制下载 CDN'),
        ('DOMAIN', 'assets.claude.ai', '{proxy}', 'claude.ai 静态资源 CDN'),
        ('DOMAIN', 'storage.googleapis.com', '{proxy}', 'Claude Code 插件元数据与旧版二进制分发 GCS 存储桶'),
    )),
    ('telemetry', '3. 监测和上报 / 遥测 (Monitoring, Telemetry & Anti-Fraud)', (
        ('DOMAIN', 'http-intake.logs.us5.datadoghq.com', '{telemetry}', 'Claude Code 官方公布的 Datadog 运营遥测日志接收端'),
        ('DOMAIN', 'browser-intake-us5-datadoghq.com', '{telemetry}', 'Claude Code 与网页端 Datadog RUM 性能与错误上报精确域名（连字符根域，非 datadoghq.com 子域）'),
        ('DOMAIN-SUFFIX', 'browser-intake-us5-datadoghq.com', '{telemetry}', '覆盖 logs.browser-intake-us5-datadoghq.com 等子域名变体'),
        ('DOMAIN', 'browser-intake-datadoghq.com', '{telemetry}', 'Datadog 通用浏览器 RUM 上报根域名'),
        ('DOMAIN-SUFFIX', 'browser-intake-datadoghq.com', '{telemetry}', '覆盖 Datadog 通用浏览器 RUM 子域名变体'),
        ('DOMAIN', 'o1158394.ingest.us.sentry.io', '{telemetry}', 'Claude Desktop 专用 Sentry 崩溃与错误上报 ingest 端点'),
        ('DOMAIN', 'a-api.anthropic.com', '{telemetry}', 'Anthropic 第一方代理 Segment 统计上报端 (/v1/b, /v1/m)'),
        ('DOMAIN', 's-cdn.anthropic.com', '{telemetry}', 'Anthropic 第一方代理统计脚本 (/s.js) 与像素上报端'),
        ('DOMAIN', 'a-cdn.anthropic.com', '{telemetry}', 'Anthropic 第一方代理 Segment 脚本 CDN'),
        ('DOMAIN', 'statsig.anthropic.com', '{telemetry}', 'Anthropic 第一方 Statsig 实验代理端点'),
        ('DOMAIN-SUFFIX', 'sentry.io', '{telemetry}', 'Sentry 错误监控上报域名后缀'),
        ('DOMAIN-SUFFIX', 'statsigapi.net', '{telemetry}', 'Statsig 功能开关 / AB 测试上报 API（建议走代理保持出口 IP 一致）'),
        ('DOMAIN-SUFFIX', 'statsig.com', '{telemetry}', 'Statsig 功能开关与实验主域'),
        ('DOMAIN-SUFFIX', 'featuregates.org', '{telemetry}', 'Statsig 官方防拦截备用域名后缀'),
        ('DOMAIN', 'cdn.growthbook.io', '{telemetry}', 'GrowthBook A/B 测试与功能门控配置 CDN'),
        ('DOMAIN-SUFFIX', 'growthbook.io', '{telemetry}', 'GrowthBook 实验与门控服务域名后缀'),
        ('DOMAIN-SUFFIX', 'datadoghq.com', '{telemetry}', 'Datadog 性能监控 (US) 域名后缀'),
        ('DOMAIN-SUFFIX', 'datadoghq.eu', '{telemetry}', 'Datadog 性能监控 (EU) 域名后缀'),
        ('DOMAIN-SUFFIX', 'ddog-gov.com', '{telemetry}', 'Datadog 性能监控 (Gov) 域名后缀'),
        ('DOMAIN-SUFFIX', 'segment.io', '{telemetry}', 'Segment 埋点遥测上报域名后缀'),
        ('DOMAIN-SUFFIX', 'segment.com', '{telemetry}', 'Segment 埋点遥测主域后缀'),
        ('DOMAIN-KEYWORD', 'datadog', '{telemetry}', 'Datadog 跨区域接收端点（如 us3/eu1/ap1）关键词通配兜底'),
        ('DOMAIN-KEYWORD', 'sentry', '{telemetry}', 'Sentry 错误追踪关键词通配兜底'),
        ('DOMAIN-SUFFIX', 'sift.com', '{proxy}', 'Sift 反欺诈检测主域名（必须与主站走同一代理出口以防风控）'),
        ('DOMAIN-SUFFIX', 'siftscience.com', '{proxy}', 'Sift Science 反欺诈检测脚本与上报域名（须走同一代理出口）'),
        ('DOMAIN-KEYWORD', 'sift', '{proxy}', 'Sift 反欺诈检测关键词兜底（必须与主站走同一代理出口以防风控）'),
    )),
    ('third_party', '4. 第三方客服、统计、验证与 Artifact 前端库 (Third-Party Widgets & Libraries)', (
        ('DOMAIN-SUFFIX', 'intercom.io', '{proxy}', 'Intercom 在线客服 widget 主域名（含 nexus-websocket-a.intercom.io）'),
        ('DOMAIN-SUFFIX', 'intercomcdn.com', '{proxy}', 'Intercom 客服静态资源 CDN'),
        ('DOMAIN', 'cdn.usefathom.com', '{proxy}', 'Fathom 访问统计脚本'),
        ('DOMAIN-SUFFIX', 'stripe.com', '{proxy}', 'Stripe 订阅支付与账单环境校验'),
        ('DOMAIN-SUFFIX', 'stripecdn.com', '{proxy}', 'Stripe 支付静态资源 CDN'),
        ('DOMAIN-SUFFIX', 'hcaptcha.com', '{proxy}', 'Claude 登录与安全验证 hCaptcha'),
        ('DOMAIN-SUFFIX', 'arkoselabs.com', '{proxy}', 'Arkose Labs 登录安全人机验证'),
        ('DOMAIN', 'cdnjs.cloudflare.com', '{proxy}', 'Artifact 第三方前端库 CDN (Cloudflare)'),
        ('DOMAIN', 'cdn.jsdelivr.net', '{proxy}', 'Artifact 第三方前端库 CDN (jsDelivr)'),
        ('DOMAIN', 'cdn.tailwindcss.com', '{proxy}', 'Artifact Tailwind CSS CDN'),
        ('DOMAIN', 'code.jquery.com', '{proxy}', 'Artifact jQuery CDN'),
        ('DOMAIN', 'unpkg.com', '{proxy}', 'Artifact unpkg 前端库 CDN'),
        ('DOMAIN', 'fonts.googleapis.com', '{proxy}', 'Artifact Google Fonts 样式表'),
        ('DOMAIN', 'fonts.gstatic.com', '{proxy}', 'Artifact Google Fonts 字体文件'),
    )),
    ('routing_rules', '5. 分流规则：IP 段 / ASN / Geosite / NTP 时区防泄露兜底 (Routing & IP/ASN/NTP Fallback)', (
        ('IP-CIDR', '160.79.104.0/21', '{proxy},no-resolve', 'Anthropic 自有 IPv4 段 (160.79.104.0 ~ 160.79.111.255) 兜底'),
        ('IP-CIDR6', '2607:6bc0::/32', '{proxy},no-resolve', 'Anthropic 自有 IPv6 段兜底'),
        ('IP-ASN', '399358', '{proxy},no-resolve', 'Anthropic, PBC 自治系统号 (AS399358) 路由兜底'),
        ('GEOSITE', 'anthropic', '{proxy}', 'v2fly / Mihomo 内置 geosite:anthropic 分类兜底'),
        ('GEOSITE', 'category-ntp', '{proxy}', 'NTP 时间同步分流兜底（防 UDP 校时直连暴露真实本地时区）'),
    )),
    ('process_fallback', '6. claude.ai 客户端与 CLI 进程兜底 (Process Fallback)', (
        ('PROCESS-NAME', 'Claude', '{proxy}', 'macOS Claude Desktop 主进程兜底（承载 claude.ai 会话，防 IP 直连/WebSocket 漏出）'),
        ('PROCESS-NAME', 'Claude Helper', '{proxy}', 'macOS Claude Desktop 通用 Helper 进程兜底'),
        ('PROCESS-NAME', 'Claude Helper (Renderer)', '{proxy}', 'macOS Claude Desktop 渲染进程兜底'),
        ('PROCESS-NAME', 'Claude Helper (GPU)', '{proxy}', 'macOS Claude Desktop GPU 进程兜底'),
        ('PROCESS-NAME', 'Claude Helper (Plugin)', '{proxy}', 'macOS Claude Desktop 插件进程兜底'),
        ('PROCESS-NAME', 'chrome-native-host', '{proxy}', 'macOS Claude Chrome 扩展原生通信宿主进程兜底'),
        ('PROCESS-NAME', 'ShipIt', '{proxy}', 'macOS Claude Desktop Squirrel 自动更新进程兜底'),
        ('PROCESS-NAME', 'claude', '{proxy}', 'macOS / Linux Claude Code CLI 终端进程兜底'),
        ('PROCESS-NAME', 'Claude.exe', '{proxy}', 'Windows Claude Desktop 主进程兜底'),
        ('PROCESS-NAME', 'claude.exe', '{proxy}', 'Windows Claude Code CLI / Desktop 进程兜底'),
        ('PROCESS-NAME', 'chrome-native-host.exe', '{proxy}', 'Windows Claude Chrome 扩展原生通信宿主进程兜底'),
    )),
)

PROXY_DIRS_MACOS = (
    '~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev',
    '~/Library/Application Support/Clash Verge',
    '~/.config/mihomo',
    '~/.config/clash',
    '~/.config/clash.meta',
    '~/.config/clash-verge',
)

PROXY_DIRS_WINDOWS = (
    '%APPDATA%/io.github.clash-verge-rev.clash-verge-rev',
    '%APPDATA%/Clash Verge',
    '~/.config/mihomo',
    '~/.config/clash',
)

HIGH_RISK_TIMEZONES = ('asia/shanghai', 'asia/urumqi', 'asia/chongqing', 'asia/harbin', 'china standard time')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'JSON 包含重复键: {key}')
        result[key] = value
    return result


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def check_no_symlink_chain(path, stop_at=None):
    path = Path(path)
    stop = Path(stop_at).resolve() if stop_at else None
    for current in (path, *path.parents):
        if common.exists(current) and common.is_link(current):
            raise ValueError(f'拒绝符号链接或重解析点路径: {current}')
        if stop is not None and current == stop:
            break


def inspect_timezone():
    """Read-only check for high-risk mainland China timezone identifiers (never modifies system settings)."""
    tz_env = os.environ.get('TZ', '').strip()
    tz_name = tz_env
    if not tz_name and sys.platform == 'darwin':
        localtime = Path('/etc/localtime')
        try:
            if localtime.is_symlink():
                target = os.readlink(localtime)
                if 'zoneinfo/' in target:
                    tz_name = target.split('zoneinfo/', 1)[1]
        except OSError:
            pass
    if not tz_name:
        tz_name = str(datetime.now().astimezone().tzinfo or '')
    flagged = any(risk in tz_name.lower() for risk in HIGH_RISK_TIMEZONES)
    return {
        'detected_timezone': tz_name or 'unknown',
        'needs_attention': flagged,
        'recommendation': (
            '检测到中国大陆时区标识（如 Asia/Shanghai）；若使用海外代理出口，建议在系统设置中改为同为 UTC+8 的 '
            'Asia/Singapore 或 Asia/Taipei（时间分秒不差），或改为与代理出口一致的时区，并配合 GEOSITE,category-ntp 规则防泄露。'
            if flagged else '当前时区标识未命中 Asia/Shanghai / Asia/Urumqi 高危特征。'
        ),
    }


def TELEMETRY_ENV_DEFAULTS_WITH_OPTIONAL(include_optional=False):
    if include_optional:
        return TELEMETRY_ENV_SPEC + OPTIONAL_PRIVACY_SPEC
    return TELEMETRY_ENV_SPEC


def inspect_settings(home=None, include_optional=False):
    home = Path.home() if home is None else Path(home)
    settings_path = home / '.claude/settings.json'
    spec = list(TELEMETRY_ENV_DEFAULTS_WITH_OPTIONAL(include_optional))
    if not common.exists(settings_path):
        return {
            'path': str(settings_path),
            'exists': False,
            'present_keys': [],
            'missing_keys': [{'key': k, 'recommended': v, 'description': d} for k, v, d in spec],
            'third_party_providers_configured': [],
            'skip_webfetch_preflight': False,
        }
    check_no_symlink_chain(settings_path, home)
    common.regular(settings_path)
    raw = settings_path.read_text(encoding='utf-8')
    data = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError(f'配置文件顶层必须是 JSON 对象: {settings_path}')
    env = data.get('env', {})
    if not isinstance(env, dict):
        raise ValueError(f'配置文件的 env 字段必须是 JSON 对象: {settings_path}')
    present, missing = [], []
    for key, recommended, desc in spec:
        if key in env:
            matches = str(env[key]) == recommended
            present.append({'key': key, 'matches_recommended': matches, 'description': desc})
        else:
            missing.append({'key': key, 'recommended': recommended, 'description': desc})
    third_party = [key for key in THIRD_PARTY_PROVIDER_KEYS if key in env and bool(env[key])]
    return {
        'path': str(settings_path),
        'exists': True,
        'present_keys': present,
        'missing_keys': missing,
        'third_party_providers_configured': third_party,
        'skip_webfetch_preflight': bool(data.get('skipWebFetchPreflight')),
    }


def candidate_proxy_files(platform, home, explicit_config=None):
    if explicit_config is not None:
        path = Path(explicit_config)
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError(f'代理配置文件必须是无 .. 的绝对路径: {explicit_config}')
        check_no_symlink_chain(path)
        if not common.exists(path):
            raise FileNotFoundError(f'指定的代理配置文件不存在: {path}')
        common.regular(path)
        return [path]
    entries = PROXY_DIRS_WINDOWS if platform.key == 'win32' else PROXY_DIRS_MACOS
    files = []
    for entry in entries:
        try:
            folder = platform.resolve(entry, home)
        except RuntimeError:
            continue
        if not common.exists(folder) or common.is_link(folder) or not folder.is_dir():
            continue
        profiles_dir = folder / 'profiles'
        candidates = list(sorted(folder.glob('*.y*ml')))
        if common.exists(profiles_dir) and not common.is_link(profiles_dir) and profiles_dir.is_dir():
            candidates.extend(sorted(profiles_dir.glob('*.y*ml')))
        for candidate in candidates:
            if common.is_link(candidate) or not candidate.is_file():
                continue
            if '.bak' in candidate.name or 'backup' in candidate.name.lower():
                continue
            files.append(candidate)
    return files


def _parse_rule_tokens(line):
    """Strip YAML list marker, comments, and outer quotes, returning comma-split tokens."""
    no_comment = line.split('#', 1)[0].strip()
    if not no_comment:
        return []
    if no_comment.startswith('-'):
        no_comment = no_comment[1:].strip()
    if len(no_comment) >= 2 and no_comment[0] == no_comment[-1] and no_comment[0] in ('"', "'"):
        no_comment = no_comment[1:-1].strip()
    return [part.strip().strip('\'"') for part in no_comment.split(',')]


def detect_existing_proxy_group(content_lines):
    """Auto-detect the proxy group name already used for Claude/Anthropic rules in existing configs."""
    ignored_actions = {'direct', 'reject', 'reject-drop', 'pass', 'compatible', 'no-resolve'}
    primary_targets = {'claude.ai', 'anthropic.com', 'api.anthropic.com', 'claude.com', 'claude', 'claude.exe'}
    for line in content_lines:
        parts = _parse_rule_tokens(line)
        if len(parts) >= 3 and parts[1].lower() in primary_targets:
            candidate_group = parts[2]
            if candidate_group and candidate_group.lower() not in ignored_actions:
                return candidate_group
    return None


def resolve_action(action_template, proxy_group, telemetry_policy):
    telemetry_target = 'REJECT' if telemetry_policy == 'reject' else proxy_group
    return (
        action_template
        .replace('{proxy}', proxy_group)
        .replace('{telemetry}', telemetry_target)
    )


def rule_line(rule_type, target, action_template, proxy_group, telemetry_policy='proxy'):
    resolved_action = resolve_action(action_template, proxy_group, telemetry_policy)
    return f'{rule_type},{target},{resolved_action}'


def _rule_target_present(rule_type, target, content_lines):
    type_lower = rule_type.lower()
    case_sensitive = type_lower == 'process-name'
    target_cmp = target if case_sensitive else target.lower()
    for line in content_lines:
        parts = _parse_rule_tokens(line)
        if len(parts) >= 2 and parts[0].lower().endswith(type_lower):
            candidate = parts[1] if case_sensitive else parts[1].lower()
            if candidate == target_cmp:
                return True
    return False


def inspect_routing(home=None, proxy_group=None, explicit_config=None, telemetry_policy='proxy'):
    platform = platforms.current()
    home = Path.home() if home is None else Path(home)
    files = candidate_proxy_files(platform, home, explicit_config)
    all_lines = []
    scanned_files = []
    for path in files:
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        all_lines.extend(text.splitlines())
        scanned_files.append(str(path))
    detected_group = detect_existing_proxy_group(all_lines)
    effective_group = proxy_group if proxy_group else (detected_group or DEFAULT_PROXY_GROUP)
    modules_report = []
    total_rules = 0
    missing_count = 0
    for mod_key, mod_title, rules in RULE_MODULES:
        present_items, missing_items = [], []
        for rule_type, target, action_tpl, comment in rules:
            total_rules += 1
            formatted = rule_line(rule_type, target, action_tpl, effective_group, telemetry_policy)
            resolved_act = resolve_action(action_tpl, effective_group, telemetry_policy)
            item = {
                'rule': formatted,
                'type': rule_type,
                'target': target,
                'action': resolved_act,
                'description': comment,
            }
            if _rule_target_present(rule_type, target, all_lines):
                present_items.append(item)
            else:
                missing_items.append(item)
                missing_count += 1
        modules_report.append({
            'module': mod_key,
            'title': mod_title,
            'present_count': len(present_items),
            'missing_count': len(missing_items),
            'present': present_items,
            'missing': missing_items,
        })
    return {
        'proxy_group': effective_group,
        'auto_detected_proxy_group': detected_group,
        'telemetry_policy': telemetry_policy,
        'scanned_files': scanned_files,
        'total_rules': total_rules,
        'present_rules_count': total_rules - missing_count,
        'missing_rules_count': missing_count,
        'modules': modules_report,
    }


def collect(home=None, proxy_group=None, explicit_config=None, include_optional=False, telemetry_policy='proxy'):
    platform = platforms.current()
    home = Path.home() if home is None else Path(home)
    settings_report = inspect_settings(home, include_optional=include_optional)
    routing_report = inspect_routing(
        home, proxy_group=proxy_group, explicit_config=explicit_config, telemetry_policy=telemetry_policy
    )
    tz_report = inspect_timezone()
    has_gaps = bool(settings_report['missing_keys']) or routing_report['missing_rules_count'] > 0
    return {
        'schema_version': 1,
        'platform': platform.key,
        'has_gaps': has_gaps,
        'settings': settings_report,
        'routing': routing_report,
        'timezone_check': tz_report,
        'reference_sources': [
            'https://ip.net.coffee/claude/site.html',
            'https://ip.net.coffee/claude/claudecode.html',
            'https://ip.net.coffee/claude/timezone.html',
            'https://code.claude.com/docs/en/network-config',
            'https://code.claude.com/docs/en/data-usage',
            'https://code.claude.com/docs/en/monitoring-usage',
        ],
    }


def apply_settings_supplement(home=None, include_optional=False):
    """Supplement missing telemetry keys in ~/.claude/settings.json without overwriting existing keys."""
    home = Path.home() if home is None else Path(home)
    claude_dir = home / '.claude'
    settings_path = claude_dir / 'settings.json'
    check_no_symlink_chain(settings_path, home)
    spec = TELEMETRY_ENV_DEFAULTS_WITH_OPTIONAL(include_optional)
    backup_path = None
    if common.exists(settings_path):
        common.regular(settings_path)
        raw_bytes = settings_path.read_bytes()
        data = json.loads(raw_bytes.decode('utf-8'), object_pairs_hook=unique_object)
        if not isinstance(data, dict) or not isinstance(data.get('env', {}), dict):
            raise ValueError(f'settings.json 或其 env 字段不是 JSON 对象: {settings_path}')
    else:
        claude_dir.mkdir(parents=True, exist_ok=True)
        raw_bytes = None
        data = {}
    env = data.setdefault('env', {})
    added, kept = [], []
    for key, recommended, _ in spec:
        if key in env:
            kept.append(key)
        else:
            env[key] = recommended
            added.append(key)
    if not added and raw_bytes is not None:
        return {'path': str(settings_path), 'backup': None, 'added_keys': [], 'kept_keys': kept, 'changed': False}
    if raw_bytes is not None:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        fd, bk_name = tempfile.mkstemp(prefix=f'settings.privacy-backup-{stamp}-', suffix='.json', dir=claude_dir)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        backup_path = Path(bk_name)
        if backup_path.read_bytes() != raw_bytes:
            raise RuntimeError(f'settings.json 备份校验失败: {backup_path}')
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    fd, tmp_name = tempfile.mkstemp(prefix='.settings-supplement-', suffix='.json', dir=claude_dir)
    temp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        if raw_bytes is not None and settings_path.read_bytes() != raw_bytes:
            raise RuntimeError('settings.json 在写入期间发生变化，已中止替换以保护数据')
        os.replace(temp_path, settings_path)
        readback = json.loads(settings_path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        if readback != data:
            raise RuntimeError('settings.json 写入后回读校验不一致')
    finally:
        temp_path.unlink(missing_ok=True)
    return {
        'path': str(settings_path),
        'backup': str(backup_path) if backup_path else None,
        'added_keys': added,
        'kept_keys': kept,
        'changed': True,
    }


def render_yaml_rules(modules, proxy_group, only_missing=False):
    lines = [
        '# Claude 域名、CDN、监测和上报（遥测）、第三方、分流规则与 claude.ai 进程兜底',
        f'# 模式：{"仅缺失项增量补充（已有规则不覆盖）" if only_missing else "完整 6 大模块参考规则"}',
        f'# 策略组名称：{proxy_group}',
        '# 用法（Clash Verge / Mihomo）：可粘贴到 Merge.yaml 的 prepend-rules: 下，或通过 --auto-patch-proxy 自动注入',
        '',
        'prepend-rules:',
    ]
    count = 0
    for mod in modules:
        items = mod['missing'] if only_missing else (mod['present'] + mod['missing'])
        if not items:
            continue
        lines.append(f'  # === {mod["title"]} ===')
        for item in items:
            lines.append(f'  - {item["rule"]} # {item["description"]}')
            count += 1
    if count == 0:
        lines.append('  # 当前检测范围内全部规则均已存在，无需额外补充')
    return '\n'.join(lines) + '\n', count


def render_classical_list(modules):
    lines = [
        '# Claude / Anthropic 完整分流与进程兜底规则集 (Surge / Shadowrocket / Quantumult X / Loon / Clash classical)',
    ]
    for mod in modules:
        items = mod['present'] + mod['missing']
        if not items:
            continue
        lines.append(f'# === {mod["title"]} ===')
        for item in items:
            if item['type'] in ('IP-CIDR', 'IP-CIDR6', 'IP-ASN'):
                lines.append(f'{item["type"]},{item["target"]},no-resolve')
            else:
                lines.append(f'{item["type"]},{item["target"]}')
    return '\n'.join(lines) + '\n'


def render_singbox_ruleset(modules):
    domain, domain_suffix, domain_keyword, ip_cidr, process_name = [], [], [], [], []
    for mod in modules:
        for item in mod['present'] + mod['missing']:
            t, target = item['type'], item['target']
            if t == 'DOMAIN':
                domain.append(target)
            elif t == 'DOMAIN-SUFFIX':
                domain_suffix.append(target)
            elif t == 'DOMAIN-KEYWORD':
                domain_keyword.append(target)
            elif t in ('IP-CIDR', 'IP-CIDR6'):
                ip_cidr.append(target)
            elif t == 'PROCESS-NAME':
                process_name.append(target)
    payload = {
        'version': 2,
        'rules': [
            {
                'domain': domain,
                'domain_suffix': domain_suffix,
                'domain_keyword': domain_keyword,
                'ip_cidr': ip_cidr,
                'process_name': process_name,
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + '\n'


def write_routing_files(routing_report, out_dir):
    out_dir = Path(out_dir)
    check_no_symlink_chain(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    supplement_text, missing_count = render_yaml_rules(
        routing_report['modules'], routing_report['proxy_group'], only_missing=True
    )
    full_text, full_count = render_yaml_rules(
        routing_report['modules'], routing_report['proxy_group'], only_missing=False
    )
    list_text = render_classical_list(routing_report['modules'])
    singbox_text = render_singbox_ruleset(routing_report['modules'])

    supplement_path = out_dir / 'claude-routing-supplement.yaml'
    full_path = out_dir / 'claude-routing-full.yaml'
    list_path = out_dir / 'claude-routing.list'
    singbox_path = out_dir / 'claude-routing-singbox.json'
    for target, content in (
        (supplement_path, supplement_text),
        (full_path, full_text),
        (list_path, list_text),
        (singbox_path, singbox_text),
    ):
        if common.exists(target) and common.is_link(target):
            raise ValueError(f'拒绝覆盖符号链接: {target}')
        target.write_text(content, encoding='utf-8')
    return {
        'supplement_file': str(supplement_path),
        'full_template_file': str(full_path),
        'classical_list_file': str(list_path),
        'singbox_json_file': str(singbox_path),
        'supplement_rules_count': missing_count,
        'full_rules_count': full_count,
    }


def find_default_merge_target(platform, home):
    """Locate a user Merge.yaml or config.yaml in Clash Verge / Mihomo if present."""
    entries = PROXY_DIRS_WINDOWS if platform.key == 'win32' else PROXY_DIRS_MACOS
    for entry in entries:
        try:
            folder = platform.resolve(entry, home)
        except RuntimeError:
            continue
        if not common.exists(folder) or common.is_link(folder) or not folder.is_dir():
            continue
        for candidate in (
            folder / 'profiles/Merge.yaml',
            folder / 'Merge.yaml',
            folder / 'config.yaml',
        ):
            if common.exists(candidate) and not common.is_link(candidate) and candidate.is_file():
                return candidate
    return None


def _list_item_indent(text, match):
    """Indentation of the first "- " item under the matched rules key; key indent + 2 when the list is empty."""
    if match is None:
        return '  '
    key_indent = match.group(1)
    for line in text[match.end():].splitlines()[1:]:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        stripped = line.lstrip(' ')
        current = line[:len(line) - len(stripped)]
        if stripped.startswith('- ') and len(current) >= len(key_indent):
            return current
        break
    return key_indent + '  '


def patch_proxy_config_file(config_path, routing_report):
    """Append/prepend ONLY missing rules into an explicit Clash/Mihomo YAML file after backup."""
    config_path = Path(config_path)
    check_no_symlink_chain(config_path)
    common.regular(config_path)
    missing_items = [item for mod in routing_report['modules'] for item in mod['missing']]
    if not missing_items:
        return {'path': str(config_path), 'backup': None, 'added_rules_count': 0, 'changed': False}
    raw_bytes = config_path.read_bytes()
    text = raw_bytes.decode('utf-8')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = config_path.with_name(f'{config_path.name}.claude-backup-{stamp}')
    if common.exists(backup_path):
        raise FileExistsError(f'备份文件已存在: {backup_path}')
    backup_path.write_bytes(raw_bytes)
    if sha256_bytes(backup_path.read_bytes()) != sha256_bytes(raw_bytes):
        raise RuntimeError(f'代理配置文件备份校验失败: {backup_path}')
    match = re.search(r'^( *)(prepend-rules|rules)\s*:\s*$', text, re.M)
    # Follow the indentation the file already uses for this list: Clash Verge writes
    # "- RULE" at column 0, Merge.yaml templates use two spaces. Mixing both inside
    # one sequence is a YAML error, so the inserted lines must match.
    indent = _list_item_indent(text, match)
    block_lines = [f'{indent}# === Claude 缺失分流与进程兜底补充 ===']
    for item in missing_items:
        block_lines.append(f'{indent}- {item["rule"]} # {item["description"]}')
    block = '\n'.join(block_lines)
    if match:
        insert_pos = match.end()
        updated = text[:insert_pos] + '\n' + block + text[insert_pos:]
    else:
        sep = '' if text.endswith('\n') else '\n'
        updated = text + sep + '\nprepend-rules:\n' + block + '\n'
    fd, tmp_name = tempfile.mkstemp(prefix='.proxy-supplement-', suffix='.yaml', dir=config_path.parent)
    temp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if config_path.read_bytes() != raw_bytes:
            raise RuntimeError('代理配置文件在写入期间发生变化，已中止替换')
        os.replace(temp_path, config_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return {
        'path': str(config_path),
        'backup': str(backup_path),
        'added_rules_count': len(missing_items),
        'changed': True,
    }


def apply_all(
    home=None,
    proxy_group=None,
    explicit_config=None,
    out_dir=None,
    include_optional=False,
    telemetry_policy='proxy',
    auto_patch_proxy=False,
):
    platform = platforms.current()
    home = Path.home() if home is None else Path(home)
    out_dir = Path(out_dir) if out_dir else (home / '.claude/routing-rules')
    target_config = explicit_config
    if target_config is None and auto_patch_proxy:
        target_config = find_default_merge_target(platform, home)
    before = collect(
        home=home,
        proxy_group=proxy_group,
        explicit_config=target_config,
        include_optional=include_optional,
        telemetry_policy=telemetry_policy,
    )
    settings_result = apply_settings_supplement(home=home, include_optional=include_optional)
    routing_files = write_routing_files(before['routing'], out_dir=out_dir)
    proxy_patch = None
    if target_config is not None:
        proxy_patch = patch_proxy_config_file(target_config, before['routing'])
    after = collect(
        home=home,
        proxy_group=proxy_group,
        explicit_config=target_config,
        include_optional=include_optional,
        telemetry_policy=telemetry_policy,
    )
    return {
        'settings_update': settings_result,
        'routing_files': routing_files,
        'proxy_config_patch': proxy_patch,
        'verification': {
            'remaining_missing_settings_keys': len(after['settings']['missing_keys']),
            'remaining_missing_proxy_rules': after['routing']['missing_rules_count'],
        },
    }


def generate_launcher(
    out_dir=None,
    proxy_group=None,
    explicit_config=None,
    include_optional=False,
    telemetry_policy='proxy',
    home=None,
):
    platform = platforms.current()
    home = Path.home() if home is None else Path(home)
    if out_dir is None:
        desktop = home / 'Desktop'
        out_dir = desktop if common.exists(desktop) and not common.is_link(desktop) and desktop.is_dir() else home
    out_dir = Path(out_dir).resolve(strict=True)
    if not out_dir.is_dir():
        raise ValueError(f'输出目录不存在: {out_dir}')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    script_rel = 'scripts\\telemetry_routing.py' if platform.key == 'win32' else 'scripts/telemetry_routing.py'
    extra_flags = ['--interactive', '--telemetry-policy', telemetry_policy]
    if proxy_group:
        extra_flags += ['--proxy-group', proxy_group]
    if explicit_config is not None:
        extra_flags += ['--proxy-config', str(Path(explicit_config).resolve(strict=True))]
    if include_optional:
        extra_flags.append('--include-optional')
    if platform.key == 'win32':
        launch_path = out_dir / f'Claude遥测与分流一键补齐-{stamp}.cmd'
        for value in (str(ROOT), *extra_flags):
            if '%' in value or '"' in value:
                raise ValueError(f'参数含 % 或 "，无法安全生成 .cmd 启动器: {value}')
        quoted_args = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in extra_flags)
        content = (
            '@echo off\r\nchcp 65001 >nul\r\n'
            f'cd /d "{ROOT}"\r\n'
            f'py -3 {script_rel} {quoted_args}\r\n'
            'set "code=%ERRORLEVEL%"\r\necho.\r\npause\r\nexit /b %code%\r\n'
        )
        with open(launch_path, 'x', encoding='utf-8', newline='') as stream:
            stream.write(content)
    else:
        launch_path = out_dir / f'Claude遥测与分流一键补齐-{stamp}.command'
        quoted_args = ' '.join(shlex.quote(arg) for arg in extra_flags)
        content = (
            '#!/bin/bash\n'
            f'cd -- {shlex.quote(str(ROOT))} || exit 2\n'
            f'python3 {script_rel} {quoted_args}\n'
            'code=$?\necho\nread -r -p "按回车关闭窗口" _\nexit $code\n'
        )
        with open(launch_path, 'x', encoding='utf-8') as stream:
            stream.write(content)
        os.chmod(launch_path, 0o700)
    return launch_path


def print_human_report(report):
    s = report['settings']
    r = report['routing']
    tz = report['timezone_check']
    print('=== 1. 监测与上报（遥测）本地配置核查 (~/.claude/settings.json) ===')
    print(f'配置文件: {s["path"]} ({"已存在" if s["exists"] else "尚未创建"})')
    print(f'已配置项（保留原值不覆盖）: {len(s["present_keys"])} 项；缺失待补充: {len(s["missing_keys"])} 项')
    for item in s['present_keys']:
        state = '✅ 已生效' if item['matches_recommended'] else 'ℹ️ 已有自定义值（不覆盖）'
        print(f'  {state} {item["key"]} — {item["description"]}')
    for item in s['missing_keys']:
        print(f'  ❌ 缺失 {item["key"]}={item["recommended"]} — {item["description"]}')
    if s['third_party_providers_configured']:
        print('  [第三方网关/提供商] 检测到已配置键（值已隐藏，严格保留不覆盖）: ' + ', '.join(s['third_party_providers_configured']))
    else:
        print('  [第三方网关/提供商] 未检测到自定义网关键（默认第一方直连/代理模式）')

    print('\n=== 2. 时区与环境一致性只读自查 ===')
    tz_mark = '⚠️ 需注意' if tz['needs_attention'] else '✅ 正常'
    print(f'  [{tz_mark}] 当前时区标识: {tz["detected_timezone"]} — {tz["recommendation"]}')

    print('\n=== 3. 域名、CDN、监测上报、第三方、分流规则与 claude.ai 进程兜底 ===')
    if r['scanned_files']:
        print('已扫描本地代理配置: ' + '；'.join(r['scanned_files']))
    else:
        print('未在默认路径发现 Clash/Mihomo 配置文件（将直接生成可直接导入的 4 种规则文件）')
    if r.get('auto_detected_proxy_group'):
        print(f'已从现有配置自动识别代理策略组: {r["proxy_group"]}（保持与原有规则同出口）')
    else:
        print(f'使用代理策略组名称: {r["proxy_group"]}')
    print(f'规则总计 {r["total_rules"]} 条：已覆盖 {r["present_rules_count"]} 条（不覆盖），缺失待补充 {r["missing_rules_count"]} 条')
    for mod in r['modules']:
        status = '✅ 已齐全' if mod['missing_count'] == 0 else f'❌ 缺 {mod["missing_count"]} 条'
        print(f'  [{status}] {mod["title"]}（已有 {mod["present_count"]} / 缺失 {mod["missing_count"]}）')
        for item in mod['missing']:
            print(f'    + 待补: {item["rule"]}  # {item["description"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='输出结构化 JSON 报告（供 AI 直接解析）')
    parser.add_argument('--apply', action='store_true', help='傻瓜式一键补齐缺失的遥测配置与分流/进程兜底规则（已有项不覆盖）')
    parser.add_argument('--auto-patch-proxy', action='store_true', help='配合 --apply 自动将缺失规则增量写入本机 Clash Verge Merge.yaml / config.yaml（先备份）')
    parser.add_argument('--interactive', action='store_true', help='交互式预览并输入“是”确认后执行一键补齐')
    parser.add_argument('--launcher', action='store_true', help='在桌面生成双击运行的一键补齐文件（.command / .cmd）')
    parser.add_argument('--proxy-group', default=None, help='分流规则使用的代理策略组名称（默认自动识别现有规则策略组，未识别则用 Proxy）')
    parser.add_argument(
        '--telemetry-policy',
        choices=('proxy', 'reject'),
        default='proxy',
        help='监测/遥测域名的代理策略：proxy（默认，走同一代理出口防 IP 分裂风控）或 reject（在代理层直接拦截）',
    )
    parser.add_argument('--proxy-config', type=Path, help='可选：指定要核查或增量补齐的 Clash/Mihomo YAML 配置文件绝对路径')
    parser.add_argument('--out-dir', type=Path, help='生成的分流规则或启动器输出目录')
    parser.add_argument('--include-optional', action='store_true', help='同时检查并补充可选的非必要流量/归属头/MCP/Artifact 禁用变量')
    args = parser.parse_args()
    common.require_supported()
    if args.launcher:
        launch_path = generate_launcher(
            out_dir=args.out_dir,
            proxy_group=args.proxy_group,
            explicit_config=args.proxy_config,
            include_optional=args.include_optional,
            telemetry_policy=args.telemetry_policy,
        )
        print(f'[OK] 已生成傻瓜式双击一键补齐文件: {launch_path}')
        print('双击运行步骤：自动检测缺口 → 列出待补充项（已有设置不覆盖）→ 输入“是”确认 → 自动备份并补齐 → 验收。')
        return 0

    report = collect(
        proxy_group=args.proxy_group,
        explicit_config=args.proxy_config,
        include_optional=args.include_optional,
        telemetry_policy=args.telemetry_policy,
    )
    if args.interactive:
        print_human_report(report)
        if not report['has_gaps']:
            print('\n[OK] 所有遥测开关与 6 大分流/进程兜底规则均已齐备，无需修改。')
            return 0
        print('\n以上为本次将要补充的缺口（已存在的配置和规则不会覆盖，修改前自动创建备份）。')
        try:
            reply = input(f'确认一键补齐请输入“{CONFIRM}”并回车，其他输入取消：').strip()
        except EOFError:
            reply = ''
        if reply != CONFIRM:
            print('[已取消] 未修改任何文件。')
            return 3
        args.apply = True

    if args.apply:
        result = apply_all(
            proxy_group=args.proxy_group,
            explicit_config=args.proxy_config,
            out_dir=args.out_dir,
            include_optional=args.include_optional,
            telemetry_policy=args.telemetry_policy,
            auto_patch_proxy=args.auto_patch_proxy,
        )
        if args.json:
            print(json.dumps({'report': report, 'applied': result}, ensure_ascii=False, indent=2))
        else:
            if not args.interactive:
                print_human_report(report)
            s_up = result['settings_update']
            r_up = result['routing_files']
            print('\n=== 一键补齐执行结果（已有项未覆盖） ===')
            print(f'[遥测配置] {s_up["path"]}：新增 {len(s_up["added_keys"])} 项，保留已有 {len(s_up["kept_keys"])} 项')
            if s_up['backup']:
                print(f'[配置备份] {s_up["backup"]}')
            print(f'[增量分流规则（仅缺失项）] {r_up["supplement_file"]}（共 {r_up["supplement_rules_count"]} 条）')
            print(f'[完整 Clash/Mihomo 规则] {r_up["full_template_file"]}（共 {r_up["full_rules_count"]} 条）')
            print(f'[Surge/Shadowrocket/QX 规则集] {r_up["classical_list_file"]}')
            print(f'[sing-box v2 JSON 规则集] {r_up["singbox_json_file"]}')
            if result['proxy_config_patch'] and result['proxy_config_patch']['changed']:
                p_up = result['proxy_config_patch']
                print(f'[代理配置已补齐] {p_up["path"]}（新增 {p_up["added_rules_count"]} 条，备份在 {p_up["backup"]}）')
        return 0

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human_report(report)
        if report['has_gaps']:
            cmd = 'py -3 scripts\\telemetry_routing.py --apply' if sys.platform == 'win32' else 'python3 scripts/telemetry_routing.py --apply'
            print(f'\n[下一步] 发现待补充缺口；AI 或用户可直接运行 `{cmd}` 一键补齐缺失项（已有项不覆盖）。')
        else:
            print('\n[OK] 监测与上报（遥测）及分流规则全部齐备。')
    return 1 if report['has_gaps'] else 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
