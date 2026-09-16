# -*- coding: utf-8 -*-
import io
lines = io.open('debug.log', encoding='utf-8', errors='ignore').read().splitlines()
# 找含 _ladder_realign_step 的 traceback 块,打印其异常类型行(块尾第一个含 Error/Exception 的行)
seen = set()
blocks = []
for i, l in enumerate(lines):
    if '_ladder_realign_step' in l:
        # 向下找最近的异常类型行
        for j in range(i, min(i + 12, len(lines))):
            s = lines[j].strip()
            if ('Error' in s or 'Exception' in s or 'Traceback' in s) and 'line ' not in s and '.py"' not in s:
                if s not in seen:
                    seen.add(s)
                    # 同时向上回溯本块的文件行
                    blk = []
                    for k in range(max(0, i - 8), j + 1):
                        blk.append(lines[k])
                    blocks.append((s, blk))
                break
print('distinct realign exceptions: %d' % len(blocks))
for s, blk in blocks[:3]:
    print('================ EXC:', s)
    for b in blk:
        print('   ', b[:160])
