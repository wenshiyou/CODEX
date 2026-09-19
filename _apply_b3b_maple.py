# -*- coding: utf-8 -*-
"""块3·脚本B（maple，BOM/LF）：post_jump 抓住判据 起跳前后Y变小 → 连续BACK_GRAB_FRAMES帧看到后脑。
   run_hold(跑跳) 与 check(直跳/校准直跳) 两段整体替换；delay1按↑时序、校准三次、放弃出口不动。"""
import io
import py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(P, 'rb').read()
assert b.startswith(b'\xef\xbb\xbf'), '缺 BOM'
t = b[3:].decode('utf-8')
assert '\r\n' not in t, 'CRLF'


def replace_span(s, start_mark, end_mark, new_text, tag):
    assert s.count(start_mark) == 1, tag + ' 起点命中%d' % s.count(start_mark)
    assert s.count(end_mark) == 1, tag + ' 终点命中%d' % s.count(end_mark)
    i = s.find(start_mark)
    j = s.find(end_mark)
    assert 0 <= i < j, tag + ' 顺序错'
    return s[:i] + new_text + s[j + len(end_mark):]


# ---- run_hold（跑跳）整段 ----
rh_start = "        if step == 'run_hold':\n"
rh_end = '            return self._ladder_realign_jump(py, now_ms, "跑跳1秒没抓住")\n'
rh_new = (
    "        if step == 'run_hold':\n"
    "            # 全程只保持↑、左右绝不重按(防水平惯性冲过梯子)\n"
    "            if VK_LEFT in self._random_move_keys:\n"
    "                self._key_up(VK_LEFT)\n"
    "            if VK_RIGHT in self._random_move_keys:\n"
    "                self._key_up(VK_RIGHT)\n"
    "            if VK_UP not in self._random_move_keys:\n"
    "                self._key_down(VK_UP)\n"
    "            # 抓住判据(用户2026-09-18):按住↑期间连续BACK_GRAB_FRAMES帧看到后脑勺=已挂上梯,不必等满抓梯窗、提前转climbing\n"
    "            _bv, _bs = self._back_head_visible()\n"
    "            if _bv:\n"
    "                self._ladder_back_seen_frames += 1\n"
    "                if self._ladder_back_seen_frames >= BACK_GRAB_FRAMES:\n"
    "                    self._grab_to_climbing('跑跳', py, now_ms, _bs)\n"
    "                    return False\n"
    "            else:\n"
    "                self._ladder_back_seen_frames = 0\n"
    "            if now_ms - start_t < RUNJUMP_GRAB_WINDOW_MS:\n"
    "                return False   # 抓梯窗未满、且还没看到后脑:继续按住↑等\n"
    "            # —— 满窗仍看不到后脑=没抓住,放开↑进校准直跳(70%×3轮) ——\n"
    "            if VK_UP in self._random_move_keys:\n"
    "                self._key_up(VK_UP)\n"
    "            _debug_log(\"[爬梯·屏幕·跑跳] 按↑满窗仍看不到后脑(back=%.2f)=没抓住,放开↑进校准直跳\" % _bs)\n"
    "            self._key_up(VK_LEFT)\n"
    "            self._key_up(VK_RIGHT)\n"
    "            return self._ladder_realign_jump(py, now_ms, \"跑跳满窗没后脑\")\n"
)
t = replace_span(t, rh_start, rh_end, rh_new, 'run_hold')

# ---- check（直跳/校准直跳）整段 ----
ck_start = "        # check【镜头滚动原理·用户2026-09-09定稿】"
ck_end = '        return self._ladder_realign_jump(py, now_ms, "直跳没抓住")\n'
ck_new = (
    "        # check【抓住判据·用户2026-09-18定稿】:不再比\"起跳前后光点Y变小\"(镜头滚动/起跳腾空会让Y抖动误判),\n"
    "        # 改为只看后脑勺——直跳/校准直跳后连续BACK_GRAB_FRAMES帧看到后脑=人物已挂上梯子,立刻锁存转climbing(不可逆);\n"
    "        # 抓梯窗LADDER_GRAB_WINDOW_MS内一直没后脑=没抓住,松↑进校准直跳(不回主线,最多3轮,轮满才回主线打怪)。\n"
    "        _bv, _bs = self._back_head_visible()\n"
    "        if _bv:\n"
    "            self._ladder_back_seen_frames += 1\n"
    "            if self._ladder_back_seen_frames >= BACK_GRAB_FRAMES:\n"
    "                self._grab_to_climbing('直跳', py, now_ms, _bs)\n"
    "                return False\n"
    "        else:\n"
    "            self._ladder_back_seen_frames = 0\n"
    "        _el = now_ms - start_t\n"
    "        if _el < LADDER_GRAB_WINDOW_MS:\n"
    "            if VK_UP not in self._random_move_keys:\n"
    "                self._key_down(VK_UP)  # 抓梯窗内还没看到后脑:继续按住↑等\n"
    "            return False\n"
    "        # 满窗仍无后脑=直跳没抓住,松↑进【校准直跳】移动剩余70%→停→达标直跳,最多3轮,轮满才回主线打怪\n"
    "        if VK_UP in self._random_move_keys:\n"
    "            self._key_up(VK_UP)\n"
    "        _debug_log(\"[爬梯] 直跳%dms后仍看不到后脑(back=%.2f)=没抓住,进校准直跳\" % (_el, _bs))\n"
    "        return self._ladder_realign_jump(py, now_ms, \"直跳满窗没后脑\")\n"
)
t = replace_span(t, ck_start, ck_end, ck_new, 'check')

io.open(P, 'wb').write(b'\xef\xbb\xbf' + t.encode('utf-8'))
py_compile.compile(P, doraise=True)
print('BLOCK3-B maple OK(跑跳/直跳抓住改后脑), py_compile pass')
