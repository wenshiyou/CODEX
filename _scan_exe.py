# -*- coding: utf-8 -*-
# 临时：静态判断 NB 主程序技术路线（内存 vs 图色），只读不运行
import os, re, json, glob, collections
NB = r"C:\Users\wenwen\Desktop\nb\nb"

# ---------- 1) 一个 snap 的完整结构 ----------
p = glob.glob(os.path.join(NB, "data", "snap", "**", "*.snap"), recursive=True)[0]
obj = json.load(open(p, "r", encoding="utf-8"))
print("===== SNAP 顶层字段:", os.path.basename(p), "=====")
def shape(v, depth=0):
    if isinstance(v, dict):
        return {k: shape(x, depth+1) for k, x in list(v.items())[:12]}
    if isinstance(v, list):
        return ["list len=%d" % len(v)] + ([shape(v[0], depth+1)] if v else [])
    if isinstance(v, str):
        return "str:%s" % (v[:40])
    return "%r" % type(v).__name__
print(json.dumps(shape(obj), ensure_ascii=False, indent=1)[:2500])

# ---------- 2) 二进制字符串关键字扫描 ----------
GROUPS = {
 "内存/进程API": [b"ReadProcessMemory", b"WriteProcessMemory", b"OpenProcess", b"VirtualAllocEx",
        b"CreateRemoteThread", b"NtReadVirtualMemory", b"GetWindowThreadProcessId", b"Toolhelp32",
        b"Module32", b"Process32", b"pymem", b"inject", b"base_addr", b"memory", b"CheatEngine"],
 "图色/截屏": [b"BitBlt", b"PrintWindow", b"GetDC", b"CreateCompatibleBitmap", b"GetDIBits",
        b"DXGI", b"D3D11", b"DesktopDuplication", b"opencv", b"cv2", b"matchTemplate", b"numpy",
        b"FindColor", b"FindPic", b"screenshot", b"capture", b"win32gui", b"mss", b"dxcam", b"Gdiplus"],
 "键鼠模拟": [b"keybd_event", b"SendInput", b"PostMessage", b"SendMessage", b"mouse_event",
        b"SetCursorPos", b"MapVirtualKey", b"pyautogui", b"scan"],
 "打包/语言": [b"python3", b"PyInstaller", b"_MEI", b"MEIPASS", b"Nuitka", b"Electron",
        b"node.dll", b"Go build", b"krnln", b"dm.dll", b"AutoHotkey", b"PySide", b"PyQt", b"tkinter",
        b".pyc", b"PYZ", b"libcrypto", b"UPX"],
}
def strings_ascii(data):
    return re.findall(rb"[\x20-\x7e]{5,}", data)
def strings_u16(data):
    # utf-16le 可打印：(char\x00) 重复
    return re.findall((rb"(?:[\x20-\x7e]\x00){4,}"), data)

for exe in ["wt.exe", "usercl.exe", "usercl.pkg"]:
    fp = os.path.join(NB, exe)
    if not os.path.exists(fp): continue
    data = open(fp, "rb").read()
    print("\n\n########## %s  size=%.1f MB ##########" % (exe, len(data)/1e6))
    sascii = strings_ascii(data)
    su16 = strings_u16(data)
    blob_ascii = b"\n".join(sascii).lower()
    # u16 转成 ascii 便于匹配
    u16flat = b"".join(su16).replace(b"\x00", b"").lower()
    for g, kws in GROUPS.items():
        hits = []
        for kw in kws:
            k = kw.lower()
            c = blob_ascii.count(k) + u16flat.count(k)
            if c: hits.append("%s=%d" % (kw.decode(errors="replace"), c))
        print("  [%-10s] %s" % (g, "  ".join(hits) if hits else "（无）"))
    # PyInstaller 魔数
    print("  MEI magic:", data.find(b"MEI\x0c\x0b\x0a\x0b\x0e"), " PYZ:", data.find(b"PYZ\x00"),
          " pyinstaller-str:", data.lower().find(b"pyinstaller"))
