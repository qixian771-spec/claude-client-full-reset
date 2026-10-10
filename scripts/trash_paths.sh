#!/usr/bin/env bash
# =============================================================================
# claude-client-full-reset :: Stage 3 安全删除（移入废纸篓，绝不 rm）
# -----------------------------------------------------------------------------
# 契约：
#   - 一律走 Finder「移到废纸篓」，同卷为秒级 rename，可随时取回。
#   - 危险路径硬拒绝：/、$HOME 本身、/Users、/Applications、/Library、/System 等。
#   - 每批 ≤10 项，批后立即复核存在性（含断链符号链接）。
#   - 路径含双引号 → 拒绝（会破坏 AppleScript 语法）。
#   - 输出 OK / FAIL / SKIP，结尾汇总，退出码 = FAIL 数。
#
# 用法：
#   bash scripts/trash_paths.sh "/path/a" "/path/b"
#   printf '%s\n' "$p1" "$p2" | bash scripts/trash_paths.sh -     # 从 stdin
#   bash scripts/trash_paths.sh --dry-run "/path/a"
#   # 先出清单给用户确认，再执行；不要跳过确认步骤。
# =============================================================================

set -u
export LC_ALL=C

BATCH=10
DRY=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    *) ARGS+=("$a") ;;
  esac
done

OK=0; FAIL=0; SKIP=0; DENY=0
FAILED_LIST=()

deny_check() {
  local p="$1"
  case "$p" in
    ""|"/"|"$HOME"|"$HOME/"|"/Users"|"/Users/"|"/Applications"|"/Library"|\
"/System"|"/usr"|"/bin"|"/sbin"|"/etc"|"/var"|"/private"|"/Volumes")
      return 0 ;;
  esac
  # 拒绝过浅的路径（如 /Users/xxx 只有两级）
  local depth
  depth=$(printf '%s' "$p" | tr -cd '/' | wc -c | tr -d ' ')
  [ "$depth" -lt 2 ] && return 0
  return 1
}

trash_one() {
  local p="$1"
  osascript -e "tell application \"Finder\" to delete (POSIX file \"$p\" as alias)" \
    >/dev/null 2>&1
}

process() {
  local p="$1"
  if deny_check "$p"; then
    printf '  [DENY] %s   ← 危险路径，已拒绝（若要动它请人工确认后再处理）\n' "$p"
    DENY=$((DENY + 1))
    return
  fi
  if printf '%s' "$p" | grep -q '"'; then
    printf '  [DENY] %s   ← 路径含双引号，会破坏 AppleScript\n' "$p"
    DENY=$((DENY + 1))
    return
  fi
  if [ ! -e "$p" ] && [ ! -L "$p" ]; then
    printf '  [SKIP] %s   ← 不存在\n' "$p"
    SKIP=$((SKIP + 1))
    return
  fi
  if [ "$DRY" -eq 1 ]; then
    printf '  [DRY ] %s   ← 将被移入废纸篓\n' "$p"
    return
  fi
  trash_one "$p"
  if [ ! -e "$p" ] && [ ! -L "$p" ]; then
    printf '  [ OK ] %s\n' "$p"
    OK=$((OK + 1))
  else
    printf '  [FAIL] %s   ← 仍在原处，检查是否被占用或无权限\n' "$p"
    FAIL=$((FAIL + 1))
    FAILED_LIST+=("$p")
  fi
}

# 收集路径
PATHS=()
if [ "${#ARGS[@]}" -gt 0 ] && [ "${ARGS[0]}" = "-" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] && PATHS+=("$line")
  done
elif [ "${#ARGS[@]}" -gt 0 ]; then
  PATHS=("${ARGS[@]}")
else
  printf '用法: bash trash_paths.sh [--dry-run] <path...> | -\n' >&2
  exit 2
fi

printf '##############################################################\n'
printf '# 安全删除（移入废纸篓）  共 %d 项  批次 ≤ %d  %s\n' \
  "${#PATHS[@]}" "$BATCH" "$([ "$DRY" -eq 1 ] && echo '[DRY-RUN]' || echo '')"
printf '##############################################################\n'

i=0
for p in "${PATHS[@]}"; do
  i=$((i + 1))
  [ "$i" -gt 1 ] && [ $(((i - 1) % BATCH)) -eq 0 ] && \
    printf '\n--- 第 %d 批复核：OK=%d FAIL=%d SKIP=%d DENY=%d ---\n\n' \
           "$(((i - 1) / BATCH))" "$OK" "$FAIL" "$SKIP" "$DENY"
  process "$p"
done

printf '\n--------------------------------------------------------------\n'
printf ' 合计: OK=%d  FAIL=%d  SKIP=%d  DENY=%d\n' "$OK" "$FAIL" "$SKIP" "$DENY"
if [ "$FAIL" -gt 0 ]; then
  printf ' 失败项:\n'
  for f in "${FAILED_LIST[@]}"; do printf '   - %s\n' "$f"; done
fi
printf ' 复核建议: 逐项 [ -e ] 或 [ -L ] 再确认一次；最后由 verify_reset.py 断言。\n'
printf ' 取回: 打开废纸篓右键「放回原处」；确认无误后再清空。\n'
printf '%s\n' '--------------------------------------------------------------'
exit "$FAIL"
