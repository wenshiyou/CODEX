# -*- coding: utf-8 -*-
"""原子改动:上梯到顶后脑丢失判定 BACK_TOP_LOST_MS 500->333(缩短1/3,留2/3)。
用户2026-09-19:上梯到顶后发呆久。日志实测连续无后脑常拖到574/775/836ms才判到顶。
只改这一个常量,不动任何逻辑。maple 带 BOM/LF。"""
import codecs, py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'

with open(P, 'rb') as f:
    raw = f.read()
assert raw.startswith(codecs.BOM_UTF8), 'maple 必须带 BOM'
text = raw.decode('utf-8-sig')

old = 'BACK_TOP_LOST_MS = 500'
new = 'BACK_TOP_LOST_MS = 333'
n = text.count(old)
assert n == 1, '常量锚点数量异常: %d' % n
text = text.replace(old, new)

# 同步把定义行尾注释补上本次变更(锚定注释片段,唯一)
old_c = '# climbing中连续多久看不到后脑=翻出平台到顶'
new_c = '# climbing中连续多久看不到后脑=翻出平台到顶(用户2026-09-19:500→333缩短1/3留2/3,治上梯到顶发呆;低帧率实测旧值常拖到574~836ms)'
nc = text.count(old_c)
assert nc == 1, '注释锚点数量异常: %d' % nc
text = text.replace(old_c, new_c)

assert '\r' not in text, '出现 CR,违反 LF'
with open(P, 'wb') as f:
    f.write(codecs.BOM_UTF8 + text.encode('utf-8'))

py_compile.compile(P, doraise=True)
print('OK BACK_TOP_LOST_MS 500->333, py_compile pass, BOM/LF kept')
