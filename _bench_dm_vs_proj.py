# -*- coding: utf-8 -*-
"""大漠DmClone vs 项目现有匹配 对比测试(用户2026-09-27)
用真实游戏截图(1280x800) + 人物名模板(28x16,半透明背景),跑4种匹配各100次,对比耗时/坐标/分数。
不侵入主程序,独立运行。"""
import cv2, numpy as np, time, os, sys
io = __import__('io')
BASE = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2"
SCREEN = os.path.join(BASE, "data", "real_capture", "real_20260920_074710", "real_000.png")
TEMPLATE = os.path.join(BASE, "data", "role_recognize", "c0", "name.png")
screen = cv2.imread(SCREEN)
tpl = cv2.imread(TEMPLATE)
if screen is None or tpl is None:
    print("读图失败 screen=%s tpl=%s" % (screen is None, tpl is None)); sys.exit(1)
print("截图:", screen.shape, " 模板:", tpl.shape, " cv2:", cv2.__version__)
N = 100

# 1) DmClone.FindPic:彩色全图 TM_CCOEFF_NORMED(和大漠底层一致)
def dm_findpic(scene, tpl):
    res = cv2.matchTemplate(scene, tpl, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res); return ml, mv

# 2) 项目现有:V通道OTSU二值化(黑底白字)再比(人物名专用,扣半透明背景)
def proj_binary(scene, tpl):
    sv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)[:, :, 2]
    tv = cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV)[:, :, 2]
    _, sbin = cv2.threshold(sv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, tbin = cv2.threshold(tv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    res = cv2.matchTemplate(sbin, tbin, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res); return ml, mv

# 3) 透明模板mask:模板里亮像素(文字)参与比,暗像素(半透明黑底)忽略
def mask_match(scene, tpl):
    tv = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(tv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    res = cv2.matchTemplate(scene, tpl, cv2.TM_CCOEFF_NORMED, mask=mask)
    _, mv, _, ml = cv2.minMaxLoc(res); return ml, mv

# 4) 项目ROI优化:只在中心400x400局部匹配(模拟人物局部检测,不全图扫)
def roi_match(scene, tpl):
    h, w = scene.shape[:2]; cx, cy = w // 2, h // 2
    roi = scene[cy - 200:cy + 200, cx - 200:cx + 200]
    res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    return (ml[0] + cx - 200, ml[1] + cy - 200), mv

# 5) ROI+二值化(项目实际人物名匹配:局部+二值化)
def roi_binary(scene, tpl):
    h, w = scene.shape[:2]; cx, cy = w // 2, h // 2
    roi = scene[cy - 200:cy + 200, cx - 200:cx + 200]
    sv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)[:, :, 2]
    tv = cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV)[:, :, 2]
    _, sbin = cv2.threshold(sv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, tbin = cv2.threshold(tv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    res = cv2.matchTemplate(sbin, tbin, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    return (ml[0] + cx - 200, ml[1] + cy - 200), mv

def bench(name, fn):
    fn(screen, tpl)  # warmup
    t0 = time.perf_counter()
    for _ in range(N):
        loc, val = fn(screen, tpl)
    dt = (time.perf_counter() - t0) / N * 1000
    print("%-28s 平均%7.2fms  坐标=%-12s  分数=%.3f" % (name, dt, loc, val))
    return dt

print("\n各跑%d次(模板28x16,截图1280x800):" % N)
bench("1.DmClone彩色全图", dm_findpic)
bench("2.项目二值化全图(V-OTSU)", proj_binary)
bench("3.透明模板mask全图", mask_match)
bench("4.ROI局部彩色(400x400)", roi_match)
bench("5.ROI局部+二值化(项目实际)", roi_binary)
print("\n结论:耗时看平均ms,分数看匹配置信度(越高越准)。")
