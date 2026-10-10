#!/usr/bin/env bash
# =============================================================================
# claude-client-full-reset :: Stage 0 只读普查
# -----------------------------------------------------------------------------
# 契约：
#   - 纯只读。本脚本不删除、不修改、不移动任何文件。
#   - 绝不打印 machineID / userID / ant-did / cookie / token 的【值】，只报存在性与条数。
#   - 输出以 [FOUND] / [CLEAR] / [INFO] 标注，结尾给出 FOUND 合计。
#   - 退出码恒为 0（普查失败不应中断流程）；判定由读取输出的人做。
#
# 用法：
#   bash scripts/scan_readonly.sh            # 全量普查
#   bash scripts/scan_readonly.sh --no-browser   # 跳过浏览器层（省时）
# =============================================================================

set -u
export LC_ALL=C

NO_BROWSER=0
[ "${1:-}" = "--no-browser" ] && NO_BROWSER=1

HITS=0
found() { printf '  [FOUND] %s\n' "$1"; HITS=$((HITS + 1)); }
clear_() { printf '  [CLEAR] %s\n' "$1"; }
info() { printf '  [INFO ] %s\n' "$1"; }
sec() { printf '\n== %s ==\n' "$1"; }

# 路径存在性（含断链符号链接——必须用 -L，否则悬空链接会误报 CLEAR）
pchk() {
  if [ -e "$1" ] || [ -L "$1" ]; then found "$1"; else clear_ "$1"; fi
}

printf '##############################################################\n'
printf '# Claude 客户端残留 · 只读普查报告\n'
printf '# 主机: %s   时间: %s\n' "$(hostname -s 2>/dev/null || echo '?')" "$(date '+%F %T')"
printf '##############################################################\n'

# -----------------------------------------------------------------------------
sec "1. 客户端核心路径"
# -----------------------------------------------------------------------------
pchk "$HOME/.claude"
pchk "$HOME/.claude.json"
pchk "$HOME/Library/Application Support/Claude"
pchk "$HOME/Library/Application Support/Claude-3p"
pchk "$HOME/Library/Preferences/com.anthropic.claudefordesktop.plist"
pchk "$HOME/Library/Caches/com.anthropic.claudefordesktop"
pchk "$HOME/Library/Caches/com.anthropic.claudefordesktop.ShipIt"
pchk "$HOME/Library/Caches/claude-cli-nodejs"
pchk "$HOME/Library/HTTPStorages/com.anthropic.claudefordesktop"
pchk "$HOME/Library/Logs/Claude"
pchk "$HOME/Library/Logs/Claude-3p"
pchk "$HOME/Library/Saved Application State/com.anthropic.claudefordesktop.savedState"
pchk "$HOME/.config/claude"
pchk "$HOME/.anthropic"
pchk "/Applications/Claude.app"

if [ -d "$HOME/.claude" ]; then
  info "~/.claude 体积: $(du -sh "$HOME/.claude" 2>/dev/null | cut -f1)"
  info "~/.claude 条目: $(ls -A "$HOME/.claude" 2>/dev/null | tr '\n' ' ')"
fi

# -----------------------------------------------------------------------------
sec "2. 身份标识（只报存在性，绝不打印值）"
# -----------------------------------------------------------------------------
if [ -f "$HOME/.claude.json" ]; then
  tops=$(/usr/bin/python3 -c "import json,os;print(' '.join(sorted(json.load(open(os.path.expanduser('~/.claude.json'))))[:40]))" 2>/dev/null)
  info "~/.claude.json 顶层键: ${tops:-<解析失败>}"
  keys=$(grep -o -E '"(machineID|userID|deviceId|installationId)"' "$HOME/.claude.json" 2>/dev/null | sort -u | tr -d '"' | tr '\n' ' ')
  if [ -n "$keys" ]; then found "~/.claude.json 身份键: $keys"; else clear_ "~/.claude.json 无身份键"; fi
else
  clear_ "~/.claude.json 不存在（无身份键）"
fi

# ant-did 多实例检测（3p / 多模式并存时每个数据目录各一份）
antdid_n=0
for d in "$HOME/Library/Application Support/Claude" "$HOME/Library/Application Support/Claude-3p"; do
  if [ -f "$d/ant-did" ]; then
    antdid_n=$((antdid_n + 1))
    info "ant-did 存在: $d/ant-did  ($(wc -c < "$d/ant-did" | tr -d ' ') 字节, md5=$(md5 -q "$d/ant-did" 2>/dev/null | cut -c1-8)…)"
  fi
done
[ "$antdid_n" -ge 2 ] && found "发现 $antdid_n 个独立 ant-did —— 只清一处等于没清！"
[ "$antdid_n" -eq 0 ] && clear_ "未发现 ant-did"

# -----------------------------------------------------------------------------
sec "3. 家目录/Library 深扫（find，非枚举固定名）"
# -----------------------------------------------------------------------------
while IFS= read -r p; do [ -n "$p" ] && found "$p"; done < <(
  find "$HOME/Library" -maxdepth 3 \( -iname "*anthropic*" -o -iname "*claude*" \) 2>/dev/null | grep -v -i workbuddy
)
clear_ "(以上为 Library 内 maxdepth 3 的全部命中)"

# -----------------------------------------------------------------------------
sec "4. 遗漏点排查（6 类高频漏点）"
# -----------------------------------------------------------------------------
# ① 编辑器扩展
for ed in .vscode .cursor .windsurf; do
  hits=$(ls -d "$HOME/$ed/extensions"/*claude* "$HOME/$ed/extensions"/*anthropic* 2>/dev/null)
  if [ -n "$hits" ]; then
    while IFS= read -r h; do [ -n "$h" ] && found "$h"; done <<< "$hits"
  else clear_ "$ed 无 Claude 扩展"; fi
done
for s in "$HOME/Library/Application Support/Code/User/settings.json" \
         "$HOME/Library/Application Support/Cursor/User/settings.json"; do
  if [ -f "$s" ] && grep -qi claude "$s" 2>/dev/null; then found "$s (含 claude 配置)"; fi
done

# ② URL Handler .app
while IFS= read -r h; do [ -n "$h" ] && found "$h"; done < <(ls -d "$HOME/Applications"/*laude* "$HOME/Applications"/*nthropic* 2>/dev/null)
while IFS= read -r h; do [ -n "$h" ] && found "$h"; done < <(ls -d /Applications/*laude* /Applications/*nthropic* 2>/dev/null | grep -v '^/Applications/Claude.app$')

# ③ LaunchServices 失效注册
LSR=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
if [ -x "$LSR" ]; then
  n=$("$LSR" -dump 2>/dev/null | grep -icE 'anthropic\.claude|claude-code' || true)
  n=${n:-0}
  [ "$n" -gt 0 ] && found "LaunchServices 命中 $n 处" || clear_ "LaunchServices 无命中"
fi

# ④ 崩溃报告
for d in /Library/Logs/DiagnosticReports "$HOME/Library/Logs/DiagnosticReports"; do
  [ -d "$d" ] || continue
  while IFS= read -r h; do [ -n "$h" ] && found "$d/$h"; done < <(ls "$d" 2>/dev/null | grep -i claude)
done

# ⑤ 浏览器 HTTP 缓存
[ -d "$HOME/Library/Caches/Google/Chrome" ] && \
  info "Chrome HTTP 缓存: $(du -sh "$HOME/Library/Caches/Google/Chrome" 2>/dev/null | cut -f1)"

# ⑥ 其他 Chromium 系浏览器
for b in "Microsoft Edge" "BraveSoftware" "Vivaldi" "Chromium" "Arc" "Google/Chrome Beta"; do
  d="$HOME/Library/Application Support/$b"
  [ -d "$d" ] && info "检测到浏览器: $b"
done

# -----------------------------------------------------------------------------
sec "5. shell 配置残留"
# -----------------------------------------------------------------------------
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile" "$HOME/.zprofile" "$HOME/.zshenv"; do
  [ -f "$rc" ] || continue
  n=$(grep -cE '^[[:space:]]*(export[[:space:]]+)?(ANTHROPIC|HEADROOM|CLAUDE)[A-Z_]*=|alias[[:space:]]+claude=' "$rc" 2>/dev/null || true)
  n=${n:-0}
  [ "$n" -gt 0 ] && found "$rc 含 $n 行相关配置" || clear_ "$rc 干净"
done
# 运行时注入 vs 持久化
envout=$(env -i HOME="$HOME" TERM=xterm /bin/zsh -l -c 'env | grep -E "^(ANTHROPIC|CLAUDE|HEADROOM)"' 2>/dev/null)
[ -n "$envout" ] && found "干净 login shell 仍导出: $(echo "$envout" | cut -d= -f1 | tr '\n' ' ')" || clear_ "干净 login shell 无相关 env"

# -----------------------------------------------------------------------------
sec "6. 进程与安装方式"
# -----------------------------------------------------------------------------
p=$(ps -eo comm= 2>/dev/null | grep -icE 'claude|Claude\.app' || true)
p=${p:-0}
[ "$p" -gt 0 ] && found "存在 $p 个 Claude 相关进程（改动前必须先退出）" || clear_ "无 Claude 进程"
info "claude 可执行: $(which claude 2>/dev/null || echo '未在 PATH')"
for d in "$HOME"/.nvm/versions/node/*/lib/node_modules/@anthropic-ai; do
  [ -e "$d" ] && found "npm 全局包: $d"
done

# -----------------------------------------------------------------------------
if [ "$NO_BROWSER" -eq 0 ]; then
  sec "7. 浏览器层（委托 browser_scan.py，遍历所有 profile）"
  if [ -f "$(dirname "$0")/browser_scan.py" ]; then
    /usr/bin/python3 "$(dirname "$0")/browser_scan.py" 2>/dev/null | head -60
    info "（完整结果请直接运行 browser_scan.py）"
  else
    info "browser_scan.py 不存在，跳过"
  fi
fi

# -----------------------------------------------------------------------------
printf '\n##############################################################\n'
printf '# 普查完毕：FOUND = %d\n' "$HITS"
[ "$HITS" -eq 0 ] && printf '# 结论：本机未见任何相关残留。\n'
printf '# 提示：本脚本只读。下一步应先出清单 + 确认，再进入 Stage 3 删除。\n'
printf '##############################################################\n'
exit 0
