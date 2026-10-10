#!/usr/bin/env bash
# =============================================================================
# claude-client-full-reset :: Stage 1 备份 + 硬证据
# -----------------------------------------------------------------------------
# 契约：
#   - 在动任何东西之前执行。备份目录默认 ~/Claude-Reset-Backup-<YYYYMMDD-HHMM>。
#   - 用 ditto 保留资源分支/元数据；plist 等小文件用 cp -p。
#   - 对关键身份文件留 md5 —— 这是「备份确实等于清理前状态」的硬证据。
#   - 自动生成 RESTORE.md 骨架（含逐条回滚命令），随备份一起存放。
#   - 绝不覆盖已存在的备份目录（追加 -2/-3）。
#
# 用法：
#   bash scripts/backup.sh
#   bash scripts/backup.sh --dest /Volumes/Ext/claude-bk   # 备份到外置/异盘更稳
# =============================================================================

set -u
export LC_ALL=C

DEST=""
[ "${1:-}" = "--dest" ] && DEST="${2:-}"

STAMP=$(date +%Y%m%d-%H%M)
BK="${DEST:-$HOME}/Claude-Reset-Backup-$STAMP"
n=1
while [ -e "$BK" ]; do BK="${BK%-*}-$STAMP-$n"; n=$((n + 1)); done

mkdir -p "$BK"
echo "备份目录: $BK"
echo

copy() {  # copy <src> <name>
  if [ -e "$1" ] || [ -L "$1" ]; then
    if ditto "$1" "$BK/$2" 2>/dev/null || cp -Rp "$1" "$BK/$2" 2>/dev/null; then
      printf '  [ OK ] %s → %s\n' "$1" "$2"
    else
      printf '  [FAIL] %s\n' "$1"
    fi
  else
    printf '  [SKIP] %s (不存在)\n' "$1"
  fi
}

echo "── 复制 ──"
copy "$HOME/.claude"                        "dot-claude"
copy "$HOME/.claude.json"                   "dot-claude.json"
copy "$HOME/Library/Application Support/Claude"    "AppSupport-Claude"
copy "$HOME/Library/Application Support/Claude-3p" "AppSupport-Claude-3p"
copy "$HOME/Library/Preferences/com.anthropic.claudefordesktop.plist" "plist"
copy "$HOME/Library/Caches/com.anthropic.claudefordesktop"    "Caches-app"
copy "$HOME/Library/HTTPStorages/com.anthropic.claudefordesktop" "HTTPStorages-app"
copy "$HOME/Library/Logs/Claude"            "Logs-Claude"

mkdir -p "$BK/shell-rc"
for rc in .zshrc .bashrc .profile .zprofile .zshenv; do
  [ -f "$HOME/$rc" ] && cp -p "$HOME/$rc" "$BK/shell-rc/" 2>/dev/null && \
    printf '  [ OK ] ~/%s → shell-rc/\n' "$rc"
done

echo
echo "── 硬证据 (md5) ──"
MD5FILE="$BK/MD5SUMS.txt"
: > "$MD5FILE"
{
  for f in "$BK/dot-claude.json" \
           "$BK/dot-claude/settings.json" \
           "$BK/AppSupport-Claude/ant-did" \
           "$BK/AppSupport-Claude-3p/ant-did"; do
    [ -f "$f" ] && printf '%s  %s\n' "$(md5 -q "$f")" "${f#$BK/}"
  done
} | tee -a "$MD5FILE"
[ -s "$MD5FILE" ] || echo "  (无可计算 md5 的身份文件 —— 说明清理前本机已无相关标识)"

echo
echo "── RESTORE.md ──"
cat > "$BK/RESTORE.md" <<'EOF'
# Claude 重置 · 回滚说明

本目录是执行「Claude 客户端全量重置」**之前**的快照。
回滚 = 把下列内容放回原位。执行前请先确认目标不存在（避免合并污染）。

## 回滚命令（逐条）

```bash
BK="$(cd "$(dirname "$0")" && pwd)"

# CLI
[ -d "$BK/dot-claude" ]     && ditto "$BK/dot-claude"     "$HOME/.claude"
[ -f "$BK/dot-claude.json" ] && cp -p "$BK/dot-claude.json" "$HOME/.claude.json"

# 桌面端
[ -d "$BK/AppSupport-Claude" ]    && ditto "$BK/AppSupport-Claude"    "$HOME/Library/Application Support/Claude"
[ -d "$BK/AppSupport-Claude-3p" ] && ditto "$BK/AppSupport-Claude-3p" "$HOME/Library/Application Support/Claude-3p"
[ -f "$BK/plist" ] && cp -p "$BK/plist" "$HOME/Library/Preferences/com.anthropic.claudefordesktop.plist"

# shell 配置
for f in "$BK/shell-rc"/*; do cp -p "$f" "$HOME/$(basename "$f")"; done
```

## 校验

```bash
cd "$BK" && md5 -c MD5SUMS.txt 2>/dev/null || while read h f; do echo "$h  $f"; done < MD5SUMS.txt
```

## 注意

- md5 与 MD5SUMS.txt 一致 = 备份未损坏。
- 回滚 `machineID` / `userID` / `ant-did` = 把**旧设备身份带回来**，
  若不是有意为之，新号登录时会被关联。回滚前想清楚目的。
- 清空本目录是**不可逆**的。确认新号跑通后再清。
EOF
echo "  [ OK ] $BK/RESTORE.md"

echo
printf '备份体积: %s\n' "$(du -sh "$BK" 2>/dev/null | cut -f1)"
echo "完成。下一步：出清理清单 → 用户确认 → bash scripts/trash_paths.sh"
