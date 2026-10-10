#!/usr/bin/env python3
# =============================================================================
# claude-client-full-reset :: Chrome/Chromium 系 · SQL 级精删
# -----------------------------------------------------------------------------
# 契约：
#   - 默认 dry-run，只报「将删多少行」，不写任何数据。加 --apply 才真删。
#   - 目标浏览器在运行 → 直接拒绝执行（运行中改库会被内存状态回写覆盖）。
#   - 删后执行 VACUUM，把已删除的页真正回收。
#   - 逐表逐列 LIKE 定位，不猜表名。
#
# ⚠️ 两类残留 DELETE 清不掉，必须整文件/整目录删（见 SKILL.md / references）：
#     ① BLOB 里的命中（SQLite 的 LIKE 遇 \x00 截断）→ 如 Network Action Predictor
#     ② 已删除但未 VACUUM 的旧页
#
# 用法：
#   python3 scripts/chrome_purge.py                     # dry-run，全部浏览器
#   python3 scripts/chrome_purge.py --apply             # 真删
#   python3 scripts/chrome_purge.py --apply --browser Chrome --profile "Profile 7"
# =============================================================================

import os
import sqlite3
import subprocess
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import browser_scan as BS
except Exception:
    print("错误：同目录下找不到 browser_scan.py", file=sys.stderr)
    sys.exit(2)

APPLY = "--apply" in sys.argv
ONLY_BROWSER = None
ONLY_PROFILE = None
for i, a in enumerate(sys.argv):
    if a == "--browser" and i + 1 < len(sys.argv):
        ONLY_BROWSER = sys.argv[i + 1]
    if a == "--profile" and i + 1 < len(sys.argv):
        ONLY_PROFILE = sys.argv[i + 1]

SKIP_TABLES = {"sqlite_sequence", "sqlite_stat1", "sqlite_stat4"}


# -----------------------------------------------------------------------------
def running_procs(names):
    try:
        out = subprocess.run(["ps", "-eo", "comm="], capture_output=True,
                             text=True, timeout=15).stdout
    except Exception:
        return []
    procs = {l.strip() for l in out.splitlines()}
    return [n for n in names if n in procs]


def sqlite_files(bdir):
    out = []
    for e in sorted(os.listdir(bdir)):
        f = os.path.join(bdir, e)
        if os.path.isfile(f) and BS._looks_sqlite(f):
            out.append(f)
    return out


def purge_db(path, apply_changes):
    """逐表逐列 DELETE。返回 (deleted_rows, detail_list)"""
    uri = "file:" + quote(os.path.abspath(path))
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5.0)
        con.execute("PRAGMA foreign_keys=OFF")
    except Exception as e:
        return 0, ["<打开失败: %s>" % e]
    deleted = 0
    detail = []
    try:
        cur = con.cursor()
        tables = [r[0] for r in cur.execute(
            "select name from sqlite_master where type='table'")]
        for t in tables:
            if t in SKIP_TABLES or t.startswith("sqlite_"):
                continue
            try:
                cols = [r[1] for r in cur.execute('pragma table_info("%s")' % t)]
            except Exception:
                continue
            for c in cols:
                sql = ('select count(*) from "%s" where "%s" like ? or "%s" like ?'
                       % (t, c, c))
                try:
                    n = cur.execute(sql, ("%claude%", "%anthropic%")).fetchone()[0]
                except Exception:
                    continue
                if not n:
                    continue
                detail.append("%s.%s=%d" % (t, c, n))
                if apply_changes:
                    try:
                        cur.execute('delete from "%s" where "%s" like ? or "%s" like ?'
                                    % (t, c, c), ("%claude%", "%anthropic%"))
                        deleted += cur.rowcount
                    except Exception as e:
                        detail.append("<删除失败 %s.%s: %s>" % (t, c, e))
        if apply_changes:
            con.commit()
            try:
                cur.execute("VACUUM")
            except Exception as e:
                detail.append("<VACUUM 失败: %s>" % e)
    finally:
        con.close()
    return deleted, detail


# -----------------------------------------------------------------------------
def main():
    names = [n for n, _ in BS.BROWSERS]
    alive = running_procs(names)

    print("═══ Chromium 系浏览器 · SQL 级精删 %s ═══"
          % ("[APPLY]" if APPLY else "[DRY-RUN]"))

    if alive:
        print("  ⛔ 拒绝执行：以下浏览器正在运行 → %s" % ", ".join(alive))
        print("     请先退出：osascript -e 'tell application \"Google Chrome\" to quit'")
        print("     然后轮询确认进程消失，再重跑本脚本。")
        return 2
    if APPLY:
        print("  ✓ 未检测到浏览器进程")

    total_files = 0
    total_rows = 0
    for name, root in BS.BROWSERS:
        if not os.path.isdir(root):
            continue
        if ONLY_BROWSER and name != ONLY_BROWSER:
            continue
        for prof, bdir in BS.iter_profiles(root):
            if ONLY_PROFILE and prof != ONLY_PROFILE:
                continue
            for f in sqlite_files(bdir):
                if not BS.byte_hits(f):
                    continue
                n, detail = purge_db(f, APPLY)
                total_files += 1
                total_rows += n
                tag = "APPLY" if APPLY else "DRY "
                print("  [%s] %s/%s/%s" % (tag, name, prof, os.path.basename(f)))
                if detail:
                    print("          " + "  ".join(detail[:8]))
                if APPLY and n:
                    print("          → 删除 %d 行" % n)

    print("─" * 60)
    print("  命中库文件: %d     %s: %d 行"
          % (total_files, "已删除" if APPLY else "待删除", total_rows))
    if total_files == 0:
        print("  ✓ 无命中，无需处理")
    elif not APPLY:
        print("  加 --apply 执行；执行前请把命中清单交用户确认。")
    else:
        print("  复核：python3 scripts/browser_scan.py")
        print("  ⚠️  若复核仍有 bytes 命中但 SQL 明细为 0 → BLOB/未回收页，需整文件删。")
    print("═" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
