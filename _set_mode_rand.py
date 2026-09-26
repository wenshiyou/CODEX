# -*- coding: utf-8 -*-
# 一次性:备份 route_config.json 并把 route_mode 由 手动 改为 随机(用于空打判死修复真机验证,验后用 .bak_manual 还原)。
import io, shutil
p = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\data\route_config.json'
shutil.copyfile(p, p + '.bak_manual')
raw = io.open(p, encoding='utf-8').read()
old = '"route_mode": "\\u624b\\u52a8"'   # 手动
new = '"route_mode": "\\u968f\\u673a"'   # 随机
n = raw.count(old)
print('match=', n)
assert n == 1, '模式字段匹配数异常,未写'
io.open(p, 'w', encoding='utf-8', newline='').write(raw.replace(old, new))
chk = io.open(p, encoding='utf-8').read()
print('随机已写入=', new in chk, '| 手动残留=', old in chk, '| 备份=', (p + '.bak_manual'))
