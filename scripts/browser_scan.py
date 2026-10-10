#!/usr/bin/env python3
# =============================================================================
# claude-client-full-reset :: 浏览器层全谱扫描（只读）
# -----------------------------------------------------------------------------
# 为什么单独成模块：
#   本流程最大的翻车点是「只查 Default/History 就断言干净」。
#   实测 12 个 profile 里藏着 48 个命中文件，含真设备标识 anthropic-device-id。
#   因此必须：① 遍历所有 Chromium 系浏览器的所有 profile
#             ② 每个 profile 扫所有库文件（不枚举固定文件名）
#             ③ 对 sqlite 逐表逐列查（claude 痕迹不在 urls 表，在 4 张旁表）
#
# 双层检测：
#   第 1 层 字节扫描（流式，快）—— 命中才进入第 2 层，也覆盖 BLOB 与未 VACUUM 残留
#   第 2 层 SQL 逐表逐列 —— 给出「在哪个表哪一列」的精确定位
#   两者不一致时（bytes>0 但 sqlite=0）说明命中在 BLOB 或已删除未回收的页里。
#
# 只读，可安全在浏览器运行时执行（immutable 打开，不阻塞、不改动）。
# =============================================================================

import json
import os
import re
import sqlite3
import sys
from urllib.parse import quote

HOME = os.path.expanduser("~")
APPSUP = os.path.join(HOME, "Library", "Application Support")
LIB = os.path.join(HOME, "Library")

PAT = re.compile(rb"claude|anthropic", re.I)
PAT_S = re.compile(r"claude|anthropic", re.I)

# 浏览器 → 用户数据根目录
BROWSERS = [
    ("Chrome",        os.path.join(APPSUP, "Google", "Chrome")),
    ("Chrome Beta",   os.path.join(APPSUP, "Google", "Chrome Beta")),
    ("Chrome Canary", os.path.join(APPSUP, "Google", "Chrome Canary")),
    ("Edge",          os.path.join(APPSUP, "Microsoft Edge")),
    ("Brave",         os.path.join(APPSUP, "BraveSoftware", "Brave-Browser")),
    ("Vivaldi",       os.path.join(APPSUP, "Vivaldi")),
    ("Chromium",      os.path.join(APPSUP, "Chromium")),
    ("Arc",           os.path.join(APPSUP, "Arc", "User Data")),
]

# profile 目录内需要递归下钻的子目录（缓存层，整目录删最干净）
SUBDIRS = [
    "Local Storage", "Session Storage", "Service Worker", "IndexedDB",
    "Shared Dictionary", "blob_storage", "File System", "Sync Data",
]

MAX_FILE = 800 * 1024 * 1024  # 单文件上限，防极端大文件拖慢
CHUNK = 1 << 20


# -----------------------------------------------------------------------------
# 基础检测原语
# -----------------------------------------------------------------------------
def byte_hits(path):
    """流式字节扫描，返回 claude/anthropic 出现次数。跨块用 8 字节重叠兜住。"""
    n = 0
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_FILE:
            return 0
        with open(path, "rb") as f:
            prev = b""
            while True:
                buf = f.read(CHUNK)
                if not buf:
                    break
                n += len(PAT.findall(prev[-8:] + buf))
                prev = buf
    except Exception:
        return 0
    return n


def sqlite_hits(path):
    """逐表逐列 LIKE 定位。返回 [(table, column, count)]。"""
    out = []
    uri = "file:" + quote(os.path.abspath(path)) + "?immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=2.0)
    except Exception:
        return out
    try:
        cur = con.cursor()
        tables = [r[0] for r in cur.execute(
            "select name from sqlite_master where type='table'")]
        for t in tables:
            try:
                cols = [r[1] for r in cur.execute('pragma table_info("%s")' % t)]
            except Exception:
                continue
            for c in cols:
                try:
                    n = cur.execute(
                        'select count(*) from "%s" where "%s" like ? or "%s" like ?'
                        % (t, c, c), ("%claude%", "%anthropic%")).fetchone()[0]
                except Exception:
                    continue
                if n:
                    out.append((t, c, n))
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass
    return out


def json_hits(path, limit=25):
    """Preferences 类 JSON 的递归 key/value 查找。返回 [(keypath, snippet)]。"""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            obj = json.load(f)
    except Exception:
        return out

    def walk(o, p):
        if len(out) >= limit:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                ks = str(k)
                if PAT_S.search(ks):
                    out.append((".".join(p + [ks]), "<key>"))
                walk(v, p + [ks])
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, p + [str(i)])
        elif isinstance(o, str) and PAT_S.search(o):
            out.append((".".join(p), o[:70].replace("\n", " ")))

    walk(obj, [])
    return out


# -----------------------------------------------------------------------------
# 结构遍历
# -----------------------------------------------------------------------------
def iter_profiles(root):
    """枚举一个浏览器根下的所有 profile 目录（以 Preferences/Cookies 为标志）。"""
    if not os.path.isdir(root):
        return
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        if os.path.exists(os.path.join(d, "Preferences")) or \
           os.path.exists(os.path.join(d, "Cookies")):
            yield name, d


def scan_profile(bdir):
    """扫描单个 profile 目录 → (files_with_hits, file_warnings)"""
    hits = []          # (relpath, bytes_n, sqlite_list)
    for entry in sorted(os.listdir(bdir)):
        full = os.path.join(bdir, entry)
        if os.path.isfile(full):
            bn = byte_hits(full)
            if bn:
                sq = sqlite_hits(full) if full.endswith((".db", "Cookies", "History",
                                                         "Web Data", "Top Sites",
                                                         "Shortcuts", "Favicons",
                                                         "Network Action Predictor",
                                                         "Reporting and NEL",
                                                         "Visited Links",
                                                         "History Provider Cache",
                                                         "Login Data", "Affiliation Database")) \
                     or _looks_sqlite(full) else []
                hits.append((entry, bn, sq))
        elif os.path.isdir(full) and entry in SUBDIRS:
            sub = []
            for dp, _, fns in os.walk(full):
                for fn in fns:
                    fp = os.path.join(dp, fn)
                    bn = byte_hits(fp)
                    if bn:
                        sub.append((os.path.relpath(fp, bdir), bn))
            if sub:
                hits.append((entry + "/", sum(x[1] for x in sub), sub))
    return hits


def _looks_sqlite(path):
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except Exception:
        return False


def scan_safari():
    """Safari：History.db + RecentlyClosedTabs.plist + Downloads.plist"""
    out = []
    hdb = os.path.join(LIB, "Safari", "History.db")
    if os.path.isfile(hdb):
        sq = sqlite_hits(hdb)
        bn = byte_hits(hdb)
        if bn or sq:
            out.append(("History.db", bn, sq))
    for extra in ("RecentlyClosedTabs.plist", "Downloads.plist"):
        p = os.path.join(LIB, "Safari", extra)
        if os.path.isfile(p) and byte_hits(p):
            out.append((extra, byte_hits(p), []))
    return out


def scan_http_cache():
    """Chrome HTTP 缓存（可达数 G，慢，仅在深度模式调用）"""
    out = []
    root = os.path.join(LIB, "Caches", "Google", "Chrome")
    if not os.path.isdir(root):
        return out, 0, 0
    nf = tot = 0
    for dp, _, fns in os.walk(root):
        for fn in fns:
            fp = os.path.join(dp, fn)
            try:
                tot += os.path.getsize(fp)
            except Exception:
                pass
            if byte_hits(fp):
                nf += 1
    return out, nf, tot


# -----------------------------------------------------------------------------
# 汇总入口（供 verify_reset.py import）
# -----------------------------------------------------------------------------
def collect(deep=False, browsers=None):
    """
    返回：
      {
        'chromium': [(browser, profile, entry, bytes_n, sqlite_hits), ...],
        'safari':   [(entry, bytes_n, sqlite_hits), ...],
        'profiles': int,          # 扫到的 profile 总数
        'files':    int,          # 命中文件总数
        'cache':    (nfiles, bytes) or None,
      }
    """
    res = {"chromium": [], "safari": [], "profiles": 0, "files": 0, "cache": None}
    for name, root in (browsers or BROWSERS):
        if not os.path.isdir(root):
            continue
        for prof, bdir in iter_profiles(root):
            res["profiles"] += 1
            for entry, bn, sq in scan_profile(bdir):
                res["chromium"].append((name, prof, entry, bn, sq))
                res["files"] += 1
    for entry, bn, sq in scan_safari():
        res["safari"].append((entry, bn, sq))
        res["files"] += 1
    if deep:
        _, nf, tot = scan_http_cache()
        res["cache"] = (nf, tot)
        res["files"] += nf
    return res


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def _fmt_sql(sq, cap=4):
    """兼容两种格式：sqlite 明细 (table, column, count) 与子目录明细 (relpath, bytes)。"""
    if not sq:
        return ""
    parts = []
    for item in sq[:cap]:
        if len(item) == 3:
            t, c, n = item
            parts.append("%s.%s(%d)" % (t, c, n))
        else:
            parts.append("%s(%s)" % (item[0], item[1]))
    if len(sq) > cap:
        parts.append("…+%d" % (len(sq) - cap))
    return "  " + " ".join(parts)


def main():
    deep = "--deep" in sys.argv
    print("═══ 浏览器层全谱扫描（全部浏览器 × 全部 profile × 全部库）═══")
    r = collect(deep=deep)

    if r["profiles"] == 0:
        print("  [INFO ] 未发现任何 Chromium 系浏览器 profile")

    cur = None
    for b, p, entry, bn, sq in r["chromium"]:
        if (b, p) != cur:
            cur = (b, p)
            print("  ● %s / %s" % (b, p))
        print("      %-38s bytes=%d%s" % (entry, bn, _fmt_sql(sq)))

    if r["safari"]:
        print("  ● Safari")
        for entry, bn, sq in r["safari"]:
            print("      %-38s bytes=%d%s" % (entry, bn,
                                              "  " + " ".join("%s.%s(%d)" % x for x in sq[:4]) if sq else ""))

    if r["cache"] is not None:
        nf, tot = r["cache"]
        print("  ● Chrome HTTP 缓存: 命中 %d 个文件 / 总计 %.1f GB" % (nf, tot / 1e9))

    print("-" * 60)
    print("  扫描 profile 数: %d" % r["profiles"])
    print("  命中文件合计:   %d   %s" % (r["files"], "← 干净" if r["files"] == 0 else "← 需处理"))
    print("  ⚠️  若某文件 bytes>0 但无 sqlite 明细 → 命中在 BLOB 或已删除未 VACUUM 的页里，")
    print("      这类只能整文件/整目录删除，DELETE+VACUUM 清不干净。")
    return 1 if r["files"] else 0


if __name__ == "__main__":
    sys.exit(main())
