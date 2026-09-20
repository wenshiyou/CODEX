# -*- coding: utf-8 -*-
"""块A: 人物坐标大跳变硬闸 + 脸face_r固化不自学 (用户2026-09-20 拍板"做")
根因(debug.log 10:25:04-09 逐帧铁证): 人名低分(0.39)丢失帧, 脸在错误位置(475,362)以0.56贴阈兜底,
叠加被自学污染的脸偏移(盘上已写成100,-57/内存30,-60, 正确固化10,61), 把人物点从真身(702~783,506~515)
一帧拽到(505,302)=284px; B线程在假点帧把同层怪误判cross打包, 主线在真点帧拿旧cross包执行=跨帧错配锁空梯。
做法(最小、复用黑框第二源, 不引入二次确认状态机):
 1) 任何定位源(人名/脸/后脑/宠物)、任何帧(局部/全图)、无论分数多高(含>=0.75强匹配), 相对上一稳定基点
    一帧位移>ROLE_BIGJUMP_PX(120)一律不采信该模板候选(continue), 转 _research_anchor_around_dot 黑框ROI重搜;
    正常跑步一帧远<120; 天外误匹配被拦; 真瞬移(>=250)后黑框光点跳到新位置、ROI内命中即重捕, 硬拦不影响真瞬移。
 2) 脸face_r只读盘上固化值、运行时不学(学习循环只留back)、不写盘(固化循环只留back); 启动加载face固化值保留。
 3) 盘上 face_r off 恢复 (10,61)。
maple_route_ui.py 保 UTF-8 BOM/LF; role_recognize.json 保 无BOM/indent2。"""
import os, json, py_compile

root = os.path.dirname(os.path.abspath(__file__))
py = os.path.join(root, 'maple_route_ui.py')

raw = open(py, 'rb').read()
assert raw.startswith(b'\xef\xbb\xbf'), 'maple_route_ui.py 应为 UTF-8 BOM'
text = raw.decode('utf-8-sig')
assert '\r\n' not in text, '应为 LF 换行'
lines = text.split('\n')

def find1(pred, what):
    idx = [i for i, l in enumerate(lines) if pred(l)]
    assert len(idx) == 1, '%s 命中 %d 处(应1): %r' % (what, len(idx), idx)
    return idx[0]

# 1) 新增大跳变硬闸常量(紧跟 ANCHOR_OFF_LEARN_MAXDEV)
i_const = find1(lambda l: l.startswith('ANCHOR_OFF_LEARN_MAXDEV = 70'), 'ANCHOR_OFF_LEARN_MAXDEV常量')
lines.insert(i_const + 1,
    'ROLE_BIGJUMP_PX = 120       # 人物基点一帧最大合法跳变px(用户2026-09-20根治坐标帧间拽飞→B误判cross锁空梯):任何定位源(人名/脸/后脑/宠物)、任何帧(局部/全图)、无论分数多高,相对上一稳定基点位移>120一律不采信该模板候选、丢弃转黑框ROI重搜;正常跑步一帧远<120,真瞬移(>=250)由_research_anchor_around_dot借黑框光点第二源在新位置重捕')

# 2) 跳变门: 在原弱匹配小跳变门之前加"大跳变硬闸"(所有源/帧/分数)
i_if = find1(lambda l: l.strip() == 'if last is not None and _pv[0] < 0.75:' and l.startswith('            if '),
             '跳变门if')
assert lines[i_if - 2].lstrip().startswith('# 跳变门'), lines[i_if - 2]
assert lines[i_if - 1].lstrip().startswith('# 脸/后脑'), lines[i_if - 1]
assert lines[i_if + 1].strip().startswith('_move_lim = maxmove'), lines[i_if + 1]
assert lines[i_if + 2].strip().startswith('if np.hypot('), lines[i_if + 2]
assert lines[i_if + 3].strip() == 'continue', lines[i_if + 3]
new_gate = [
    '            # 大跳变硬闸(用户2026-09-20根治坐标帧间拽飞→B误判cross锁空梯;实测误匹配把人783,515一帧拽到505,302=284px):',
    '            # 任何定位源、任何帧(局部/全图)、无论分数多高(含≥0.75强匹配),相对上一稳定基点一帧位移>ROLE_BIGJUMP_PX一律不采信、continue转黑框ROI重搜;',
    '            # 正常跑步一帧远<120;真瞬移(≥250)由_research_anchor_around_dot以黑框光点(独立第二源)在新位置ROI内重捕,硬拦不影响真瞬移。',
    '            if last is not None and np.hypot(_bx - last[0], _by - last[1]) > ROLE_BIGJUMP_PX:',
    '                continue',
    '            # 大跳变以内:保留原弱匹配小跳变过滤(人名局部窗>maxmove且弱匹配<0.75丢;兜底锚点>80且弱匹配<0.75丢)',
    '            if last is not None and _pv[0] < 0.75:',
    '                _move_lim = maxmove if _pk == "name" else AUX_ANCHOR_MAX_MOVE',
    '                if np.hypot(_bx - last[0], _by - last[1]) > _move_lim and (_pk != "name" or not need_full):',
    '                    continue',
]
lines[i_if - 2:i_if + 4] = new_gate   # 替换旧2行注释+4行代码(共6行)

# 3) 偏移学习: 脸固化不自学, 学习循环只留后脑back
i_dict = find1(lambda l: '_learn_anchor_on = {"face_r":' in l, '学习门控字典')
assert '"back": (_climb_st_learn == "climbing")}' in lines[i_dict + 1], lines[i_dict + 1]
lines[i_dict:i_dict + 2] = [
    '        _learn_anchor_on = {"back": (_climb_st_learn == "climbing")}  # face_r固化不自学、只读盘(2026-09-20)']
i_for8 = find1(lambda l: l.startswith('        for _kk in ("face_r", "back"):'), '学习for(8空格)')
lines[i_for8] = '        for _kk in ("back",):  # 只后脑在climbing学;脸固化不学(2026-09-20)'
i_facecmt = find1(lambda l: l.lstrip().startswith('# 脸face_r只在非爬梯硬态'), '脸学习注释')
lines[i_facecmt] = '        # 脸face_r【固化不自学·只读盘上(10,61)·不写盘】(用户2026-09-20:脸误匹配污染off+天外误匹配拽飞坐标→锁空梯)。'

# 4) 偏移固化写盘: 只写back, 脸永不写盘(用下一行 _o=tr.get 区分启动加载处的同名for)
idx_w = [i for i, l in enumerate(lines)
         if l.startswith('                for _kk in ("face_r", "back"):')
         and i + 1 < len(lines) and lines[i + 1].strip().startswith('_o = tr.get("off_"')]
assert len(idx_w) == 1, '写盘for命中 %d 处' % len(idx_w)
lines[idx_w[0]] = '                for _kk in ("back",):  # face_r固化、运行时永不写盘(2026-09-20)'

out = '\n'.join(lines)
open(py, 'wb').write(b'\xef\xbb\xbf' + out.encode('utf-8'))
print('[py] written, BOM/LF kept')

# 5) 盘上 face_r 偏移恢复固化值 (10,61)
jp = os.path.join(root, 'data', 'role_recognize', 'role_recognize.json')
jraw = open(jp, 'rb').read()
assert not jraw.startswith(b'\xef\xbb\xbf'), 'role_recognize.json 应无 BOM'
j = json.loads(jraw.decode('utf-8'))
ch = [c for c in j['characters'] if c['id'] == j.get('active')][0]
fr = ch['anchors']['face_r']
print('[json] face before off=(%s,%s)' % (fr.get('off_x'), fr.get('off_y')))
fr['off_x'], fr['off_y'] = 10, 61
open(jp, 'wb').write(json.dumps(j, ensure_ascii=False, indent=2).encode('utf-8'))
print('[json] face after off=(10,61), back kept=(%s,%s)' % (ch['anchors']['back'].get('off_x'),
                                                              ch['anchors']['back'].get('off_y')))

py_compile.compile(py, doraise=True)
print('[verify] py_compile OK')
