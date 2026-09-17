# -*- coding: utf-8 -*-
"""
_fix34b1.py  日志区第三栏【异常】UI(打怪|行为|异常)
- init 新增 _exception_logs/_exception_scroll/_log_tab_exception
- _rlog 支持 log='exception'
- 渲染:三分支选 logs/scroll + 第三个tab(矩形[323-373],底板右缘440放得下)
- 鼠标:三分支选 entries/get_scr/set_scr + 异常tab点击;垂直滚动接全(水平滚动条前两栏本就未实装,不引入)
每处 replace assert 命中数,UTF-8、newline='' 原样写回。
"""
import io

PATH = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(PATH, "r", encoding="utf-8", newline="") as f:
    text = f.read()

def rep(old, new, n):
    global text
    c = text.count(old)
    assert c == n, "命中=%d 期望%d %r" % (c, n, old[:60])
    text = text.replace(old, new)

E = []

# 1) init 字段
E.append((
"""        self._log_tab_behavior = None  # 【行为】tab按钮矩形(UI坐标)""",
"""        self._log_tab_behavior = None  # 【行为】tab按钮矩形(UI坐标)
        self._exception_logs = []      # 异常日志[{t,msg,color}]:停滞/频繁异常/失败事件(2026-09-17新增第三栏)
        self._exception_scroll = 0     # 异常日志垂直滚动位置
        self._log_tab_exception = None # 【异常】tab按钮矩形(UI坐标)""",
1))

# 2) _rlog 异常分支
E.append((
"""        if log == 'behavior':
            self._behavior_logs.append(_entry)
            if len(self._behavior_logs) > self._log_max:
                self._behavior_logs = self._behavior_logs[-self._log_max:]
            self._behavior_scroll = 0   # 新行为日志回到顶部
        else:
            self._runtime_logs.append(_entry)""",
"""        if log == 'behavior':
            self._behavior_logs.append(_entry)
            if len(self._behavior_logs) > self._log_max:
                self._behavior_logs = self._behavior_logs[-self._log_max:]
            self._behavior_scroll = 0   # 新行为日志回到顶部
        elif log == 'exception':
            self._exception_logs.append(_entry)
            if len(self._exception_logs) > self._log_max:
                self._exception_logs = self._exception_logs[-self._log_max:]
            self._exception_scroll = 0  # 新异常日志回到顶部
        else:
            self._runtime_logs.append(_entry)""",
1))

# 3) 渲染选 logs/scroll 三分支
E.append((
"""        _view = self._log_view
        _logs = self._runtime_logs if _view == 'combat' else self._behavior_logs
        _scroll = self._log_scroll if _view == 'combat' else self._behavior_scroll""",
"""        _view = self._log_view
        if _view == 'behavior':
            _logs, _scroll = self._behavior_logs, self._behavior_scroll
        elif _view == 'exception':
            _logs, _scroll = self._exception_logs, self._exception_scroll
        else:
            _logs, _scroll = self._runtime_logs, self._log_scroll""",
1))

# 4) tab 矩形加异常
E.append((
"""        self._log_tab_combat = (_tab_x0, _tab_y, _tab_w, _tab_h)
        self._log_tab_behavior = (_tab_x0 + _tab_w + 4, _tab_y, _tab_w, _tab_h)""",
"""        self._log_tab_combat = (_tab_x0, _tab_y, _tab_w, _tab_h)
        self._log_tab_behavior = (_tab_x0 + _tab_w + 4, _tab_y, _tab_w, _tab_h)
        self._log_tab_exception = (_tab_x0 + 2 * (_tab_w + 4), _tab_y, _tab_w, _tab_h)""",
1))

# 5) tab 绘制循环加异常
E.append((
"""            for _tv, _tr, _tn in (('combat', self._log_tab_combat, '打怪'),
                                  ('behavior', self._log_tab_behavior, '行为')):""",
"""            for _tv, _tr, _tn in (('combat', self._log_tab_combat, '打怪'),
                                  ('behavior', self._log_tab_behavior, '行为'),
                                  ('exception', self._log_tab_exception, '异常')):""",
1))

# 6) 鼠标 entries 三分支
E.append((
"""        _is_beh = (self._log_view == 'behavior')
        _entries = self._behavior_logs if _is_beh else self._runtime_logs""",
"""        _view = self._log_view
        if _view == 'behavior':
            _entries = self._behavior_logs
        elif _view == 'exception':
            _entries = self._exception_logs
        else:
            _entries = self._runtime_logs""",
1))

# 7) 鼠标 get/set scroll 三分支
E.append((
"""        def _get_scr():
            return self._behavior_scroll if _is_beh else self._log_scroll

        def _set_scr(v):
            if _is_beh:
                self._behavior_scroll = v
            else:
                self._log_scroll = v""",
"""        def _get_scr():
            if _view == 'behavior':
                return self._behavior_scroll
            if _view == 'exception':
                return self._exception_scroll
            return self._log_scroll

        def _set_scr(v):
            if _view == 'behavior':
                self._behavior_scroll = v
            elif _view == 'exception':
                self._exception_scroll = v
            else:
                self._log_scroll = v""",
1))

# 8) 异常 tab 点击
E.append((
"""            if _tab_hit(self._log_tab_behavior):
                self._log_view = 'behavior'
                return""",
"""            if _tab_hit(self._log_tab_behavior):
                self._log_view = 'behavior'
                return
            if _tab_hit(self._log_tab_exception):
                self._log_view = 'exception'
                return""",
1))

for i, (o, n, k) in enumerate(E, 1):
    rep(o, n, k)
    print("b1 edit", i, "ok x%d" % k)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("B1 WRITTEN")
