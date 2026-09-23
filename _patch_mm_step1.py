# -*- coding: utf-8 -*-
"""施工补丁Step1: 新增小地图选梯/对位常量(纯新增,不改任何现有逻辑)。
读写成对保持 BOM(utf-8-sig) 与 CRLF(newline=''),断言锚点唯一命中。"""
import io, sys

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'

with io.open(P, 'r', encoding='utf-8-sig', newline='') as f:
    text = f.read()

anchor = 'LADDER_END_MATCH_TOL = 1    # [小地图巡路模式预留]梯子连接端(上行顶端y_top/下行底端y_bottom)与目标层Y重合容差±1小地图px,差>1判为通向别的层、排除'
assert text.count(anchor) == 1, 'anchor count=%d' % text.count(anchor)

block_lines = [
    '# === 小地图光点+录制梯选梯/对位(用户2026-09-21最终定稿,物理替换游戏窗口白框特征一套;坐标全部=小地图块像素,与find_player_dot/self.ladders同空间)===',
    'LADDER_MM_X_HALF = 60       # 选梯X带:光点左右各60小地图px内找录制梯(白框旧值屏幕±300作废)',
    'LADDER_MM_Y_HALF = 25       # 选梯Y带:光点上/下各25小地图px(粗筛,最终高度门用梯端容差)',
    'LADDER_MM_END_TOL = 10      # 合格高度门:上行梯底y_bottom与光点Y差<=10(人跳起够得到底端)/下行梯顶y_top与光点Y差<=10',
    'LADDER_MM_RUNJUMP_DEFAULT = 7   # 面板默认跑跳起跳人梯X差(小地图单位):6~7带水平速度起跳;面板rj_l/rj_r可调',
    'LADDER_MM_VERT_DEFAULT = 1      # 面板默认直跳起跳人梯X差(小地图单位):0~1松键原地直跳;面板vl_l/vl_r可调',
    'LADDER_MM_FINE_DX = 3           # |X差|<=3进微调点动(走60ms停50ms检测),>3且<跑跳窗=按住走',
    'LADDER_MM_FINE_MOVE_MS = 60     # 微调单拍按住朝梯走时长ms',
    'LADDER_MM_FINE_GAP_MS = 50      # 微调每拍抬起后停稳检测时长ms',
    'LADDER_MM_FINE_MAX = 2          # 微调最多几拍仍进不了0~1直跳窗->放弃清锁回主线打怪(不发呆)',
    'LADDER_MM_DESC_ALIGN_TOL = 1    # 下行方式二:光点对齐录制梯X|差|<=1即按↓抓梯下滑',
]
block = '\r\n'.join(block_lines)

assert 'LADDER_MM_X_HALF = 60' not in text, '常量已存在,勿重复打补丁'
text = text.replace(anchor, anchor + '\r\n' + block, 1)

with io.open(P, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(text)

print('STEP1 OK: constants inserted')
