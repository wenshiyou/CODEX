# -*- coding: utf-8 -*-
# 临时：静态分析 NB 样本的数据格式（只读，不运行样本）
import os, glob, binascii
D = r"C:\Users\wenwen\Desktop\nb\nb\data"

def head_bytes(p, n=64):
    with open(p, "rb") as f: b = f.read(n)
    return b

# 1) snap 文件头：判断是 png/jpg/zip/pickle/json/npy/自定义
snaps = glob.glob(os.path.join(D, "snap", "**", "*.snap"), recursive=True)
print("SNAP count =", len(snaps))
for p in snaps[:3]:
    b = head_bytes(p, 48)
    print("\n---", os.path.basename(p), "size=", os.path.getsize(p))
    print("HEX:", binascii.hexlify(b, " ").decode()[:160])
    print("ASC:", "".join(chr(x) if 32 <= x < 127 else "." for x in b)[:160])
    # 试着按文本解
    try:
        txt = open(p, "r", encoding="utf-8").read(300)
        print("TXT-HEAD:", repr(txt[:300]))
    except Exception as e:
        print("not utf8 text:", e)

# 2) csv 表头 + 一行样例
for name in ["wanmxd_monster_spawns.csv", "wanmxd_maps.csv", "wanmxd_monsters.csv", "wanmxd_job_skills.csv"]:
    p = os.path.join(D, "csv", name)
    print("\n===== %s =====" % name)
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for i in range(3):
            line = f.readline()
            if not line: break
            print(line.rstrip("\n")[:400])
