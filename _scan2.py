# -*- coding: utf-8 -*-
# 临时：进一步实锤 NB 数据来源（内存/封包/图色）与打包形态，只读不运行
import os, re
NB = r"C:\Users\wenwen\Desktop\nb\nb"
files = ["wt.exe", "usercl.exe", "usercl.pkg"]
data = {f: open(os.path.join(NB, f), "rb").read() for f in files}

# 文件头 magic
for f in files:
    b = data[f][:16]
    print(f, "head=", b.hex(" "), "ascii=", "".join(chr(x) if 32<=x<127 else "." for x in b))

# 1) snap 专属字段名出现在哪个二进制（证明谁在生产/消费这份世界模型）
fields = [b"foothold", b"move_candidates", b"input_flags", b"m4_ai", b"body_x", b"body_y",
          b"is_upper_foothold", b"forbid_falldown", b"base_zmass", b"move_state", b"hit_type",
          b"m4_ai_map_snapshot", b"cash_item_sn"]
print("\n===== 世界模型字段在二进制中的命中 =====")
for f in files:
    low = data[f].lower()
    row = []
    for k in fields:
        c = low.count(k.lower())
        if c: row.append("%s=%d" % (k.decode(), c))
    print("%-12s %s" % (f, " | ".join(row) if row else "（无）"))

# 2) 更宽的内存/进程/封包/调试 API
api = [b"ReadProcessMemory", b"WriteProcessMemory", b"OpenProcess", b"VirtualQueryEx",
       b"VirtualProtect", b"CreateRemoteThread", b"NtReadVirtualMemory", b"NtQueryInformationProcess",
       b"DebugPrivilege", b"SeDebug", b"Toolhelp32Snapshot", b"Process32First", b"Module32First",
       b"GetWindowThreadProcessId", b"WriteProcessMemory", b"recv", b"send", b"WSASend", b"WSARecv",
       b"packet", b"hook", b"detour", b"minhook", b"inject", b"MapleStory", b"Artale", b"maplestory",
       b"client.exe", b"grap", b"nProtect", b"XignCode"]
print("\n===== 内存/封包/Hook/进程 关键字 =====")
for f in files:
    low = data[f].lower(); row=[]
    for k in api:
        c = low.count(k.lower())
        if c: row.append("%s=%d" % (k.decode(errors='replace'), c))
    print("%-12s %s" % (f, " | ".join(row) if row else "（无）"))

# 3) 语言/打包/图像库
lang = [b"python3", b"Python", b"PyInstaller", b"_MEI", b"site-packages", b".pyc", b"numpy",
        b"cv2", b"opencv", b"mss", b"PIL", b"PySide", b"PyQt", b"tkinter", b"Nuitka", b"__pyx",
        b"Go build", b"rust_panic", b"electron", b"node", b"MSVCP", b"VCRUNTIME", b"tcl",
        b"torch", b"onnx", b"yolo", b"darknet", b"tensorflow", b"easyocr", b"paddle"]
print("\n===== 语言/框架/图像/AI 库 =====")
for f in files:
    low = data[f].lower(); row=[]
    for k in lang:
        c = low.count(k.lower())
        if c: row.append("%s=%d" % (k.decode(errors='replace'), c))
    print("%-12s %s" % (f, " | ".join(row) if row else "（无）"))

# 4) 导入的 DLL 名
print("\n===== 引用的 DLL =====")
for f in files:
    dlls = sorted(set(m.group(0).decode(errors='replace') for m in re.finditer(rb"[A-Za-z0-9_]+\.dll", data[f], re.I)))
    print("%-12s %s" % (f, ", ".join(dlls)))
