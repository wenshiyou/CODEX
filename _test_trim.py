# -*- coding: utf-8 -*-
# 直接抽取源码里真实的 _maint_trim_debug_log，喂合成用例断言 + 真实 debug.log 副本 dry-run。
import ast, io, os, re as _re, shutil, tempfile, textwrap, types

SRC = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
REAL = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"

src = io.open(SRC, "rb").read().decode("utf-8-sig")
tree = ast.parse(src)
func_src = None
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        for st in node.body:
            if isinstance(st, ast.FunctionDef) and st.name == "_maint_trim_debug_log":
                func_src = ast.get_source_segment(src, st)
assert func_src, "没找到方法"

def make_trim(getsize_fn, replace_fn=os.replace, exists_fn=os.path.exists):
    g = {"io": io, "re": _re,
         "os": types.SimpleNamespace(
             path=types.SimpleNamespace(exists=exists_fn, getsize=getsize_fn),
             replace=replace_fn),
         "DEBUG_LOG": None}
    exec(textwrap.dedent(func_src), g)
    return g["_maint_trim_debug_log"]

def hms(s):
    return "%02d:%02d:%02d" % ((s // 3600) % 24, (s // 60) % 60, s % 60)
def L(s, tag="log"):
    return "[%s] %s padding padding padding" % (hms(s), tag)

def run_case(name, lines, keep, expect):
    trim = make_trim(lambda p: 10 ** 7)
    fd, tmp = tempfile.mkstemp(suffix=".log"); os.close(fd)
    trim.__globals__["DEBUG_LOG"] = tmp
    try:
        io.open(tmp, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        trim(object(), keep)
        out = io.open(tmp, "rb").read().decode("utf-8", "ignore").splitlines()
        expect(out)
        print("[PASS]", name, "-> 保留", len(out), "行, 首", out[0][:10], "尾", out[-1][:10])
    finally:
        os.remove(tmp) if os.path.exists(tmp) else None

# A 跨天：昨晚23:50-23:59(600行) + 今天12:00-12:16:40(1001行)，留60分钟 -> 昨晚全删
night = [L(s) for s in range(23*3600+50*60, 23*3600+50*60+600)]
day = [L(s) for s in range(12*3600, 12*3600+1001)]
def chk_a(out):
    assert not any(x.startswith("[23:") for x in out), "昨晚段未删干净"
    assert out[0].startswith("[12:00:00]"), out[0]
    assert out[-1].startswith("[12:16:40]"), out[-1]
    assert len(out) == 1001, len(out)
run_case("A 跨天保留今天", night + day, 60, chk_a)

# B 同天：11:00:00-12:16:40(4601行)，留60分钟 -> 首11:16:40，3601行
b = [L(s) for s in range(11*3600, 11*3600+4601)]
def chk_b(out):
    assert out[0].startswith("[11:16:40]"), out[0]
    assert out[-1].startswith("[12:16:40]"), out[-1]
    assert len(out) == 3601, len(out)
run_case("B 同天60分钟窗口", b, 60, chk_b)

# C 无时间戳续行：保留区内每500秒插一条续行，应全部保留且不丢顺序
lines = []
add = 0
for s in range(11*3600, 11*3600+4601):
    lines.append(L(s))
    if s >= 11*3600+16*60+40 and (s - (11*3600+16*60+40)) % 500 == 0:
        lines.append("    traceback continuation no-ts"); add += 1
def chk_c(out):
    cont = [x for x in out if x.startswith("    traceback")]
    assert len(cont) == add, (len(cont), add)
run_case("C 无戳续行随物理切片保留", lines, 60, chk_c)
print("    (C 插入续行数 =", add, ")")

# D 真实 debug.log 副本 dry-run（真实 os，不动原文件）
fd, tmp = tempfile.mkstemp(suffix=".log"); os.close(fd)
shutil.copy2(REAL, tmp)
before = len(io.open(tmp, "rb").read().decode("utf-8", "ignore").splitlines())
trim_real = make_trim(os.path.getsize)
g_dbg = None
trim_real.__globals__["DEBUG_LOG"] = tmp  # exec 的全局里改 DEBUG_LOG
trim_real(object(), 60)
after_lines = io.open(tmp, "rb").read().decode("utf-8", "ignore").splitlines()
ts = _re.compile(r"^\[(\d\d:\d\d:\d\d)\]")
stamps = [ts.match(x).group(1) for x in after_lines if ts.match(x)]
print("\n[D 真实副本] 裁剪前 %d 行 -> 裁剪后 %d 行" % (before, len(after_lines)))
print("   保留段首3时间:", stamps[:3])
print("   保留段末3时间:", stamps[-3:])
print("   含[22:行:", sum(1 for x in after_lines if x.startswith("[22:")),
      " 含[23:行:", sum(1 for x in after_lines if x.startswith("[23:")))
assert not any(x.startswith(("[22:", "[23:")) for x in after_lines), "昨晚污染段未删"
print("[PASS] D 真实副本昨晚段已清、仅留今天最近窗口")
os.remove(tmp)
print("\n全部用例通过")
