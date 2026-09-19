# -*- coding: utf-8 -*-
"""块3·脚本D：同步 _ladder_post_jump_process 的 docstring/注释 为后脑判据(旧Y变小描述删除,避免误导)。"""
import io
import py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(P, 'rb').read()
assert b.startswith(b'\xef\xbb\xbf'), '缺 BOM'
t = b[3:].decode('utf-8')
assert '\r\n' not in t, 'CRLF'

old_doc = (
    "        \"\"\"起跳后统一流程（2026-09-08 重写；2026-09-09 直跳延时100ms + 镜头滚动定稿）：\n"
    "        跳后50ms按↑不松+松左右(原地直跳/固定点6跑跳统一50ms，先松↓上下互斥) → 抓梯窗口LADDER_GRAB_WINDOW_MS(1秒)内\n"
    "        只和【起跳前站地基准Y】比：任一帧Y变小≥LADDER_GRAB_UP_TOL=抓住,锁存转climbing一直按↑(中间帧镜头回弹不判错)；\n"
    "        走到窗口上限全程没变小=没抓住，松↑重置回正常找怪（锁定的台子怪不放弃，会再引上来）。\"\"\"\n"
)
new_doc = (
    "        \"\"\"起跳后统一流程（2026-09-08 重写；2026-09-18 抓住判据由\"起跳前后Y变小\"改为【后脑勺】）：\n"
    "        跳后50ms按↑不松+松左右(原地直跳/跑跳统一50ms，先松↓上下互斥) → 抓梯窗口内只看后脑勺：\n"
    "        连续BACK_GRAB_FRAMES帧看到后脑=人物已挂上梯子,立刻锁存转climbing(不必等满抓梯窗);\n"
    "        跑跳满RUNJUMP_GRAB_WINDOW_MS/直跳满LADDER_GRAB_WINDOW_MS仍看不到后脑=没抓住,松↑进校准直跳(70%×3轮,轮满才回主线打怪)。\n"
    "        旧\"光点Y变小\"判据已删(镜头滚动/起跳腾空会让Y抖动误判);到顶判据见climbing段(后脑连续BACK_TOP_LOST_MS消失为主、小地图光点重合梯端兜底、录梯时长+2s总超时保命)。\"\"\"\n"
)

old_cmt = (
    "        # ===== 跑跳固定时序(用户2026-09-14):起跳当帧已松左右、按住↑;这里持续按住↑满RUNJUMP_GRAB_WINDOW_MS(=1秒),\n"
    "        #       期间不判Y;满1秒那一刻只和【起跳前站地Y】比——Y变小=抓住接爬梯段(climbing),没变小=放开↑进校准直跳 =====\n"
)
new_cmt = (
    "        # ===== 跑跳固定时序(2026-09-14起跑跳;2026-09-18抓住改后脑):起跳当帧已松左右、按住↑;这里持续按住↑,\n"
    "        #       期间连续BACK_GRAB_FRAMES帧看到后脑=抓住转climbing(提前于满窗);满RUNJUMP_GRAB_WINDOW_MS仍无后脑=没抓住,放开↑进校准直跳 =====\n"
)

for old, new, tag in ((old_doc, new_doc, 'docstring'), (old_cmt, new_cmt, 'run_hold注释')):
    c = t.count(old)
    assert c == 1, '%s 命中%d次' % (tag, c)
    t = t.replace(old, new)

io.open(P, 'wb').write(b'\xef\xbb\xbf' + t.encode('utf-8'))
py_compile.compile(P, doraise=True)
print('BLOCK3-D doc/注释同步完成, py_compile pass')
