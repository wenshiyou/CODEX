# -*- coding: utf-8 -*-
import io, re, ast
P=r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw=io.open(P,'rb').read()
txt=raw.decode('utf-8-sig')
print("BOM:", raw[:3]==b'\xef\xbb\xbf', "CRLF数:", txt.count('\r\n'), "孤立LF:", txt.replace('\r\n','').count('\n'))
checks_present=[
 "PERSON_BUSY_MAIN_FLOOR_FPS = 27.0","PERSON_BUSY_MAIN_OK_FPS","PERSON_BUSY_MAIN_DOWN_STEP = 6",
 "self._main_fps = float(_fps)","战斗挨饿,后台让路到",
 "_busy_main_last_t","_ui_throttle","_need_ui_draw","_last_ui_draw_t",
 "key = cv2.waitKey(_ui_wait_ms) & 0xFF",
]
checks_gone=[  # 旧原文应已不存在
 "key = cv2.waitKey(int(self._perf_val('ui_wait_ms'))) & 0xFF  # UI帧间隔按CPU性能档(快15/普通25/慢40ms);挂机面板无需高刷,战斗按键靠内部时间戳节流不受影响",
]
for c in checks_present:
    print(("OK 存在 " if txt.count(c)>=1 else "!! 缺失 ")+c+" x%d"%txt.count(c))
for c in checks_gone:
    print(("OK 已替换 " if txt.count(c)==0 else "!! 仍残留 ")+c[:40]+" x%d"%txt.count(c))
# AST 遮蔽: 新增self属性不得与def方法同名
tree=ast.parse(txt)
methods=set()
for n in ast.walk(tree):
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)): methods.add(n.name)
new_attrs=["_main_fps","_main_fps_t","_busy_main_ov","_busy_main_rx","_busy_main_last_t",
           "_ui_throttle","_need_ui_draw","_last_ui_draw_t","_ui_wait_ms"]
for a in new_attrs:
    print(("!! 遮蔽 " if a in methods else "OK 无遮蔽 ")+a)
# 主循环闭环片段缩进自检: 打印忙档裁决关键行
for i,l in enumerate(txt.replace('\r\n','\n').split('\n')):
    if "战斗挨饿,后台让路" in l or "主循环帧率闭环(最高准则)" in l or ("_ui_wait_ms = 5" in l):
        print("行%d 缩进%d: %s"%(i+1, len(l)-len(l.lstrip()), l.strip()[:80]))
