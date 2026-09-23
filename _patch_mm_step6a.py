# -*- coding: utf-8 -*-
"""Step6a: 物理删除两个识别线程里的白框扫描生产块(人物线程停止态扫描 + 识别B线程运行态扫描)。
删后 _lad_marks_cache 永远为空初始化列表,蒙板/建锁消费侧遍历空list安全(白框不再产生、不再耗matchTemplate CPU)。
方法本体 _scan_ladder_marks 及消费/建锁/绘制在后续 step6b/6c 物理删。保持BOM/CRLF。"""
import io
P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()
def crlf(s): return s.replace('\r\n', '\n').replace('\n', '\r\n')

blk_char = '''                # 停止态(没在运行打怪)低频扫梯子白框供蒙板常开显示;运行态由识别B线程扫,门控互斥、不同时写缓存(用户2026-09-15)
                if not self._monster_running and self._raw_char_pos is not None:
                    _lm_now = time.time()
                    if _lm_now - getattr(self, '_lad_marks_scan_t', 0.0) >= LADDER_MARK_SCAN_MS / 1000.0:
                        try:
                            self._lad_marks_cache = self._scan_ladder_marks(_frame, self._raw_char_pos)
                            self._lad_marks_scan_t = _lm_now
                        except Exception:
                            pass
'''
blk_b = '''                # 梯子白框扫描【2026-09-14性能·从主线程7d搬到识别B线程异步跑】:主线程不再被多模板matchTemplate/
                # dilate堵住(原近全屏范围单次数百ms、帧率掉到3~5、人物1秒才跟手)。精准(上梯)用小ROI高频档、非精准用
                # far_range大ROI的250ms档(_scan_ladder_marks内部按_ladder_precise_mode自选范围);结果原子写_lad_marks_cache,
                # 主线程选梯/蒙板只读,数据格式[(cx,cy,sim)]与节流口径完全不变,仅生产位置改后台、异步一拍(在原gap内)。
                try:
                    _lm_ch = self._raw_char_pos
                    if _frame is not None and _lm_ch is not None:
                        _lm_precise = bool(getattr(self, '_ladder_precise_mode', False)) and \\
                            getattr(self, '_climb_state', 'none') in ('to_ladder', 'climbing', 'descend')
                        _lm_gap_s = (LADDER_PRECISE_MARK_MS if _lm_precise else LADDER_MARK_SCAN_MS) / 1000.0
                        _lm_now = time.time()
                        if _lm_now - getattr(self, '_lad_marks_scan_t', 0.0) >= _lm_gap_s:
                            self._lad_marks_cache = self._scan_ladder_marks(_frame, _lm_ch)
                            self._lad_marks_scan_t = _lm_now
                except Exception:
                    pass
'''
for tag, blk in [('char-scan', blk_char), ('b-scan', blk_b)]:
    b = crlf(blk)
    assert text.count(b) == 1, '%s count=%d' % (tag, text.count(b))
    text = text.replace(b, '', 1)

with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)
print('STEP6a OK: white-frame scan producers removed from both recognition threads')
