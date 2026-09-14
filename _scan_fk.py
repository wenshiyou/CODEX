# -*- coding: utf-8 -*-
# 临时：静态分析 FK/MSC 样本定位方式，只读不运行
import os, re
D = r"C:\Users\wenwen\Desktop\FK_Taiwan_0911\MSC_Taiwan"
files = ["Client.exe", "Core.dll"]
data = {f: open(os.path.join(D, f), "rb").read() for f in files}

GROUPS = {
 "内存/进程/注入": [b"ReadProcessMemory", b"WriteProcessMemory", b"OpenProcess", b"VirtualAllocEx",
    b"VirtualProtectEx", b"CreateRemoteThread", b"NtReadVirtualMemory", b"GetWindowThreadProcessId",
    b"Toolhelp32", b"Module32", b"Process32", b"pymem", b"inject", b"AOB", b"sigscan", b"pattern",
    b"base_address", b"pointer", b"offset", b"MinHook", b"detour", b"trampoline"],
 "封包/hook网络": [b"WSARecv", b"WSASend", b"recv", b"send", b"encrypt", b"decrypt", b"cipher",
    b"packet", b"hook", b"send_hook", b"recv_hook"],
 "图色/截屏/识别": [b"BitBlt", b"PrintWindow", b"GetDC", b"GetDIBits", b"CreateCompatibleBitmap",
    b"DXGI", b"D3D11", b"DesktopDuplication", b"opencv", b"cv2", b"matchTemplate", b"FindColor",
    b"FindPic", b"FindImage", b"mss", b"screenshot", b"capture", b"Gdiplus", b"HSV", b"template",
    b"onnx", b"yolo", b"ncnn", b"darknet", b"tensorrt", b"ocr", b"pixel"],
 "人物/定位语义": [b"player", b"Player", b"character", b"Character", b"mychar", b"self", b"avatar",
    b"position", b"coord", b"foothold", b"GetPlayer", b"name_tag", b"nametag", b"hp_bar", b"minimap",
    b"localPlayer", b"entity", b"mob", b"Monster", b"x_pos", b"pos_x", b"foot_hold"],
 "语言/界面框架": [b"python", b"PyInstaller", b"mscoree", b".NET", b"Delphi", b"Borland", b"Electron",
    b"node.dll", b"Qt5", b"Qt6", b"MFC", b"DuiLib", b"krnln", b"dm.dll", b"opencv_world", b"libcurl",
    b"VCRUNTIME", b"MSVCP", b"go1.", b"rust", b"fltk", b"wxWidgets", b"cef", b"lua", b"tolua"],
}
def allstr_lower(d):
    a = b"\n".join(re.findall(rb"[\x20-\x7e]{4,}", d)).lower()
    u = b"".join(re.findall(rb"(?:[\x20-\x7e]\x00){4,}", d)).replace(b"\x00", b"").lower()
    return a + b"\n" + u

for f in files:
    low = allstr_lower(data[f])
    print("\n\n########## %s %.1f MB ##########" % (f, len(data[f])/1e6))
    for g, kws in GROUPS.items():
        hits = []
        for k in kws:
            c = low.count(k.lower())
            if c: hits.append("%s=%d" % (k.decode(errors='replace'), c))
        print("[%s] %s" % (g, " | ".join(hits) if hits else "（无）"))
    dlls = sorted(set(m.group(0).decode(errors='replace') for m in re.finditer(rb"[A-Za-z0-9_]+\.dll", data[f], re.I)))
    print("DLL依赖:", ", ".join(dlls))
