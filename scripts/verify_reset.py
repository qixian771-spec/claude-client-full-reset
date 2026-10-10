#!/usr/bin/env python3
# =============================================================================
# claude-client-full-reset :: Stage 5 全盘终检（只读，带退出码）
# -----------------------------------------------------------------------------
# 适用前提：刚刚执行完一轮清理。本脚本用于【断言清理结果】。
#
# 退出码语义：
#   0 = PASS   前提成立（无活跃安装），且实质残留 = 0
#   1 = FAIL   前提成立，但仍有实质残留
#   2 = 前提不满足 —— 检测到 Claude 处于已安装/运行状态，
#                    此时命中项多为「当前安装的组成部分」而非历史残留，
#                    本报告不能作为清理验收依据。先卸载/退出再跑。
#
# 结果分四桶：
#   STALE   实质残留（唯一计入验收的桶）
#   ACTIVE  活跃安装/使用产生的（非残留，需先卸载或退出才可能为 0）
#   USER    疑似用户自有产物（.bak / backup 等，只报不判）
#   NOISE   依赖包名（对服务端不可见，清除无收益）
#
# 用法：
#   python3 scripts/verify_reset.py              # 标准七维度 + 状态判定
#   python3 scripts/verify_reset.py --deep       # 追加 Chrome HTTP 缓存扫描
#   python3 scripts/verify_reset.py --expect-clean  # 忽略状态，全部按残留计（强制验收）
#   python3 scripts/verify_reset.py --quiet
# =============================================================================

import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.path.expanduser("~")
LIB = os.path.join(HOME, "Library")
APPSUP = os.path.join(LIB, "Application Support")

try:
    import browser_scan
    HAVE_BS = True
except Exception:
    HAVE_BS = False

QUIET = "--quiet" in sys.argv
DEEP = "--deep" in sys.argv
EXPECT_CLEAN = "--expect-clean" in sys.argv
PAT = re.compile(r"claude|anthropic", re.I)
USER_PAT = re.compile(r"\.bak|[-_.]backup|/backup|\.old$|\.orig$|~$", re.I)


# -----------------------------------------------------------------------------
# 工具
# -----------------------------------------------------------------------------
def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=60).stdout.strip()
    except Exception:
        return ""


def byte_hits(path):
    if HAVE_BS:
        return browser_scan.byte_hits(path)
    n = 0
    try:
        with open(path, "rb") as f:
            n = len(re.findall(rb"claude|anthropic", f.read(), re.I))
    except Exception:
        pass
    return n


def exists_p(p):
    return os.path.exists(p) or os.path.islink(p)


def uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# -----------------------------------------------------------------------------
# 状态判定：本脚本的前提是否成立
# -----------------------------------------------------------------------------
def detect_state():
    """→ (state, n_proc)  state ∈ CLEAN / INSTALLED / RUNNING"""
    procs = []
    try:
        out = subprocess.run(["ps", "-eo", "comm="], capture_output=True,
                             text=True, timeout=15).stdout
        procs = [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        pass
    claude_procs = [p for p in procs if re.search(r"Claude|claude", p)]
    app = exists_p("/Applications/Claude.app")
    dc = exists_p(os.path.join(HOME, ".claude"))
    dcj = exists_p(os.path.join(HOME, ".claude.json"))

    if claude_procs and (app or dc or dcj):
        return "RUNNING", len(claude_procs)
    if app or dc or dcj:
        return "INSTALLED", len(claude_procs)
    return "CLEAN", 0


def classify(text, state):
    if USER_PAT.search(text):
        return "USER"
    if state != "CLEAN" and not EXPECT_CLEAN:
        return "ACTIVE"
    return "STALE"


# -----------------------------------------------------------------------------
# A. 客户端核心路径
# -----------------------------------------------------------------------------
def dim_a():
    paths = [
        f"{HOME}/.claude", f"{HOME}/.claude.json",
        f"{APPSUP}/Claude", f"{APPSUP}/Claude-3p",
        f"{LIB}/Preferences/com.anthropic.claudefordesktop.plist",
        f"{LIB}/Caches/com.anthropic.claudefordesktop",
        f"{LIB}/Caches/com.anthropic.claudefordesktop.ShipIt",
        f"{LIB}/Caches/claude-cli-nodejs",
        f"{LIB}/HTTPStorages/com.anthropic.claudefordesktop",
        f"{LIB}/Logs/Claude", f"{LIB}/Logs/Claude-3p",
        f"{LIB}/Saved Application State/com.anthropic.claudefordesktop.savedState",
        f"{HOME}/.config/claude", f"{HOME}/.anthropic",
        "/Applications/Claude.app",
    ]
    return [p for p in paths if exists_p(p)]


# -----------------------------------------------------------------------------
# B. 浏览器层（全谱）
# -----------------------------------------------------------------------------
def dim_b():
    if not HAVE_BS:
        return ["<browser_scan.py 不可用，已跳过>"]
    r = browser_scan.collect(deep=DEEP)
    out = []
    for b, p, entry, bn, sq in r["chromium"]:
        out.append("%s/%s/%s (bytes=%d%s)" % (
            b, p, entry, bn,
            ", " + " ".join("%s.%s" % (t, c) for t, c, _ in sq[:3]) if sq else ""))
    for entry, bn, sq in r["safari"]:
        out.append("Safari/%s (bytes=%d)" % (entry, bn))
    if r["cache"] is not None and r["cache"][0]:
        out.append("Chrome-HTTP-cache (%d files, %.1f GB)" % (
            r["cache"][0], r["cache"][1] / 1e9))
    return out


# -----------------------------------------------------------------------------
# C. 系统层（Library 浅层深扫，排除自有工具与备份目录）
# -----------------------------------------------------------------------------
def dim_c():
    out = []
    for root, dirs, files in os.walk(LIB):
        rel = os.path.relpath(root, LIB)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= 3:
            dirs[:] = []
        low = root.lower()
        if "workbuddy" in low or "claude-reset-backup" in low:
            dirs[:] = []
            continue
        for n in list(files) + list(dirs):
            if PAT.search(n):
                out.append(os.path.join(root, n))
    return uniq(out)


# -----------------------------------------------------------------------------
# D. 编辑器
# -----------------------------------------------------------------------------
def dim_d():
    out = []
    for pat in (f"{HOME}/.vscode/extensions/*laude*", f"{HOME}/.vscode/extensions/*nthropic*",
                f"{HOME}/.cursor/extensions/*laude*", f"{HOME}/.windsurf/extensions/*laude*"):
        out += glob.glob(pat)
    for s in glob.glob(f"{APPSUP}/Code/User/settings.json") + \
             glob.glob(f"{APPSUP}/Cursor/User/settings.json"):
        try:
            if PAT.search(open(s, encoding="utf-8", errors="replace").read()):
                out.append(s)
        except Exception:
            pass
    for db in glob.glob(f"{APPSUP}/Code/User/globalStorage/state.vscdb") + \
              glob.glob(f"{APPSUP}/Cursor/User/globalStorage/state.vscdb"):
        if os.path.isfile(db) and byte_hits(db):
            out.append(db)
    return out


# -----------------------------------------------------------------------------
# E. 系统诊断报告
# -----------------------------------------------------------------------------
def dim_e():
    out = []
    for d in ("/Library/Logs/DiagnosticReports", f"{LIB}/Logs/DiagnosticReports"):
        if os.path.isdir(d):
            for n in os.listdir(d):
                if PAT.search(n):
                    out.append(os.path.join(d, n))
    return out


# -----------------------------------------------------------------------------
# F. shell 配置与环境
# -----------------------------------------------------------------------------
def dim_f():
    out = []
    for rc in (".zshrc", ".bashrc", ".profile", ".zprofile", ".zshenv"):
        p = os.path.join(HOME, rc)
        if not os.path.isfile(p):
            continue
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            if re.match(r"^\s*(export\s+)?(ANTHROPIC|CLAUDE|HEADROOM)[A-Z_]*=", line) or \
               re.match(r"^\s*alias\s+claude=", line):
                out.append("%s:%d" % (p, i))
    envout = sh('env -i HOME="$HOME" TERM=xterm /bin/zsh -l -c '
                "'env | grep -E \"^(ANTHROPIC|CLAUDE|HEADROOM)\"'")
    if envout:
        out.append("clean-login-shell env: " + envout.replace("\n", " "))
    for d in uniq([os.environ.get("TMPDIR", "/tmp"), "/tmp",
                   "/private" + os.environ.get("TMPDIR", "/tmp")]):
        out += glob.glob(os.path.join(d, "*claude*"))
        out += glob.glob(os.path.join(d, "*anthropic*"))
    return uniq(out)


# -----------------------------------------------------------------------------
# G. 进程 / 废纸篓 / 快照
# -----------------------------------------------------------------------------
def dim_g(nproc=0):
    out = []
    if nproc:
        out.append("运行中的 Claude 进程: %d" % nproc)
    tr = os.path.join(HOME, ".Trash")
    if os.path.isdir(tr):
        for n in os.listdir(tr):
            if PAT.search(n):
                out.append("~/.Trash/" + n)
    snaps = sh("tmutil listlocalsnapshots / 2>/dev/null")
    if snaps:
        out.append("本地 APFS 快照 %d 个（正常；快照内可能含历史文件，非本流程清理对象）" %
                   len([x for x in snaps.splitlines() if x.strip()]))
    return out


# -----------------------------------------------------------------------------
# 噪声识别：npm 缓存里的「依赖包名」
# -----------------------------------------------------------------------------
def is_dep_noise(fp):
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            obj = json.load(f)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    depkeys = ("dependencies", "devDependencies", "peerDependencies",
               "optionalDependencies")
    found = [False]

    def check(d):
        if isinstance(d, dict):
            for k in depkeys:
                v = d.get(k)
                if isinstance(v, dict) and any("anthropic" in str(x).lower() for x in v):
                    found[0] = True

    check(obj)
    vers = obj.get("versions")
    if isinstance(vers, dict):
        for _, vv in vers.items():
            check(vv)
    return found[0]


def scan_npm():
    noise, real = [], []
    root = os.path.join(HOME, ".npm", "_cacache", "content-v2")
    if not os.path.isdir(root):
        return noise, real
    for dp, _, fns in os.walk(root):
        for fn in fns:
            fp = os.path.join(dp, fn)
            if not byte_hits(fp):
                continue
            (noise if is_dep_noise(fp) else real).append(fp)
    return noise, real


# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
def main():
    state, nproc = detect_state()
    dims = [
        ("A 客户端核心路径", dim_a),
        ("B 浏览器层（全谱）", dim_b),
        ("C 系统层 Library", dim_c),
        ("D 编辑器", dim_d),
        ("E 系统诊断", dim_e),
        ("F shell / env / TMPDIR", dim_f),
        ("G 进程 / 废纸篓 / 快照", (lambda: dim_g(nproc))),
    ]

    print("═══════════════════════════════════════════════════════")
    print(" Claude 客户端残留 · 全盘终检")
    print(" 主机 %s   %s%s" % (os.uname().nodename,
                               __import__("time").strftime("%F %T"),
                               "   [deep]" if DEEP else ""))
    print("───────────────────────────────────────────────────────")
    if state == "CLEAN":
        print(" 前提: ✓ 未检测到 Claude 安装 —— 适用「清理后验收」")
    else:
        word = "正在运行" if state == "RUNNING" else "已安装"
        print(" 前提: ✗ 检测到 Claude %s%s" % (
            word, "（%d 个进程）" % nproc if nproc else ""))
        print("       命中项将标为 ACTIVE（当前安装/使用的组成部分），")
        print("       本报告**不能**作为「残留已清零」的依据。")
        print("       先卸载/退出，或加 --expect-clean 强制按残留计。")
    print("═══════════════════════════════════════════════════════")

    buckets = {"STALE": [], "ACTIVE": [], "USER": [], "NOISE": []}
    for label, fn in dims:
        try:
            items = fn()
        except Exception as e:
            items = ["<检查异常: %s>" % e]
        for it in items:
            buckets[classify(it, state)].append((label, it))
        stale = sum(1 for it in items if classify(it, state) == "STALE")
        mark = "✓" if not items else ("●" if stale == 0 else "✗")
        print(" %-26s %4d   %s" % (label, len(items), mark))
        if items and not QUIET:
            for it in items[:10]:
                print("        %s %s" % ("·", it))
            if len(items) > 10:
                print("        · …另有 %d 项" % (len(items) - 10))

    noise, real = scan_npm()
    buckets["NOISE"] += [("H npm 缓存", x) for x in noise]
    for x in real:
        buckets[classify(x, state)].append(("H npm 缓存", x))
    print(" %-26s %4d   %s" % ("H npm 缓存",
                               len(real) + len(noise), "✓" if not real else "●"))

    # ---- 汇总 ----
    print("─" * 55)
    n_stale = len(buckets["STALE"])
    n_active = len(buckets["ACTIVE"])
    n_user = len(buckets["USER"])
    n_noise = len(buckets["NOISE"])

    print("  实质残留 (STALE):   %d" % n_stale)
    if n_active:
        print("  活跃安装 (ACTIVE):  %d   ← 当前安装/使用产生的，非历史残留" % n_active)
    if n_user:
        print("  用户自有 (USER):    %d   ← 只报不判，请人工确认后决定" % n_user)
    if n_noise:
        print("  依赖名噪声 (NOISE): %d   ← 对服务端不可见，清除无收益" % n_noise)

    if not QUIET:
        for tag in ("ACTIVE", "USER", "NOISE"):
            if buckets[tag]:
                print("  ── %s 摘录 ──" % tag)
                for label, it in buckets[tag][:5]:
                    print("     [%s] %s" % (tag, it))
                if len(buckets[tag]) > 5:
                    print("     … 另有 %d 项" % (len(buckets[tag]) - 5))

    if state == "CLEAN":
        if n_stale == 0:
            print("  结论: PASS — 未见任何实质残留")
        else:
            print("  结论: FAIL — 见上列 %d 项" % n_stale)
    else:
        print("  结论: 前提不满足（退出码 2）—— 请先卸载/退出 Claude 再验收")
    print("═══════════════════════════════════════════════════════")

    if state != "CLEAN" and not EXPECT_CLEAN:
        return 2
    return 0 if n_stale == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
