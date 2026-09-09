# -*- coding: utf-8 -*-
# 只读诊断·快采样5ms：抓前台/Z序/可见/置顶的瞬时脉冲(A->B->A)、窗口增删、鼠标是否真在动
import ctypes, time, struct
from ctypes import wintypes
u = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
TARGETS = ['冒险岛怀旧服', 'PLAY AND HAPPY', 'Overlay', 'MapleBot']

def title_of(h):
    n=u.GetWindowTextLengthW(h); b=ctypes.create_unicode_buffer(n+1); u.GetWindowTextW(h,b,n+1); return b.value
def rect_of(h):
    r=ctypes.create_string_buffer(16); u.GetWindowRect(h,r); L,T,R,B=struct.unpack('llll',r.raw); return (L,T,R-L,B-T)
def all_wins():
    d={}
    def cb(h,l):
        t=title_of(h)
        ex=u.GetWindowLongW(h,-20); st=u.GetWindowLongW(h,-16)
        d[h]=(t,u.IsWindowVisible(h),bool(ex&0x8),bool(st&0x10000000),rect_of(h))  # visible,topmost,WS_VISIBLE
        return True
    u.EnumWindows(WNDENUMPROC(cb),0); return d

def run(seconds=30):
    t0=time.time(); prev_fg=u.GetForegroundWindow(); prev=all_wins(); prev_set=set(prev)
    pt=wintypes.POINT(); prev_xy=None
    fg_pulse=0; change=0; mouse_move=0; win_birth=0; win_dead=0
    log=[]
    print('200Hz快采样开始 %ds，请确保此刻 MapleBot 任务栏正在跳'%seconds,flush=True)
    while time.time()-t0<seconds:
        fg=u.GetForegroundWindow()
        if fg!=prev_fg:
            log.append('[%.3f] 前台脉冲 %s(%s)->%s(%s)'%(time.time()-t0,prev_fg,title_of(prev_fg),fg,title_of(fg)))
            fg_pulse+=1; prev_fg=fg
        u.GetCursorPos(ctypes.byref(pt))
        if prev_xy is not None and (pt.x,pt.y)!=prev_xy: mouse_move+=1
        prev_xy=(pt.x,pt.y)
        cur=all_wins(); cur_set=set(cur)
        born=cur_set-prev_set; dead=prev_set-cur_set
        for h in born:
            t=cur[h]
            if t[0] or t[1]: log.append('[%.3f] 新窗口 hwnd=%s %s vis=%s'%(time.time()-t0,h,t[0],t[1])); win_birth+=1
        for h in dead:
            t=prev[h]
            if t[0] or t[1]: log.append('[%.3f] 窗口消失 hwnd=%s %s'%(time.time()-t0,h,t[0])); win_dead+=1
        for h in (cur_set&prev_set):
            if cur[h]!=prev[h] and (any(k in (cur[h][0] or '') for k in TARGETS)):
                log.append('[%.3f] 目标窗变化 hwnd=%s %s -> %s'%(time.time()-t0,h,prev[h],cur[h])); change+=1
        prev=cur; prev_set=cur_set
        time.sleep(0.005)
    print('---- 结果 ----')
    print('前台脉冲次数:%d  目标窗状态翻转:%d  窗口新建:%d  窗口销毁:%d  鼠标移动采样:%d'%(fg_pulse,change,win_birth,win_dead,mouse_move))
    print('详细(最多60条):')
    for x in log[:60]: print(x)
    if not log: print('（无任何瞬时变化）')

run()
