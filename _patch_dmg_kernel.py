# -*- coding: utf-8 -*-
"""补丁:伤害数字检测内核重做为多点颜色加权 + A(怪头顶X±35)/B(人物技能带)双窗逐团评分。
逐锚点 assert,全过才写盘;CRLF归一;utf-8-sig。仅替换 _detect_damage_number 与两处调用/探针日志。"""
import io, os, sys

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'maple_route_ui.py')

with io.open(PATH, 'r', encoding='utf-8-sig', newline='') as f:
    src = f.read()

errors = []
def must1(old, tag):
    c = src.count(old)
    if c != 1:
        errors.append('%s: count=%d (need 1)' % (tag, c))
    return c

# ---------- 锚点1:模块级常量(插到 AOE_Y_DOWN 行后) ----------
CONST = (
"# === 伤害数字多点颜色加权检测(用户2026-09-22定稿,真机样本b0718d86离线标定:5串真数字全中/10类干扰0误判)===\n"
"# 数字外观=白描边包裹+顶部橙红→底部亮黄竖向渐变粗体;橙瓶/岩石/木怪只有橙、无高亮黄无白边无渐变,血条是扁横条\n"
"DMG_A_X = 35             # A窗:出手怪基点X前后各35px(与血条A同口径;旧值±30作废)\n"
"DMG_Y_UP = 150           # A/B窗Y:基点上方55~150px(数字飘怪头顶,排怪身体与近头顶背景)\n"
"DMG_Y_LO = 55\n"
"DMG_SCORE_T = 1.0        # 加权命中阈值(实测真数字块1.32~2.0;过颜色共现门的血条0.91且被扁条形态门排除)\n"
"DMG_YEL_MIN = 0.05       # 亮黄占比硬门(橙瓶/岩石/木怪≈0,真数字≥0.073)\n"
"DMG_RED_MIN = 0.04       # 橙红+纯红占比硬门(真数字≥0.096,干扰≤0.067且多为0)\n"
"DMG_FLAT_AR = 2.6        # 扁横条(血条)宽高比门…\n"
"DMG_FLAT_H_R = 0.35      #   …配合团高/窗高<此值=血条(真数字团高约占窗高0.7)\n"
"DMG_BIG_H_R = 1.15       # 团高/窗高超此=超大背景块(岩石/UI),排除\n"
"DMG_MIN_H_R = 0.30       # 团高/窗高低于此=碎噪点,排除\n"
"DMG_PAD = 3              # 暖色团外扩px,把外侧白描边纳入评分区\n"
)
import re as _re
_const_m = _re.search(r'^AOE_Y_DOWN = 30[^\r\n]*\r?\n', src, flags=_re.M)
if not _const_m:
    errors.append('const_anchor: AOE_Y_DOWN line not found')
if 'DMG_SCORE_T' in src:
    errors.append('constants already inserted')

# ---------- 锚点2:整段替换 _detect_damage_number(起点签名行 -> 下一个同级 def) ----------
sig = "    def _detect_damage_number(self, target_cx, target_cy, frame=None, monsters=None, dbg=None):"
must1(sig, 'func_sig')

NEW_FUNC = '''    # ===== 伤害数字检测核:多点颜色加权(2026-09-22重做,替代旧红橙阈值找色;离线5串真数字全中/10类干扰0误判)=====
    @staticmethod
    def _damage_roi_hit(roi):
        # 对单个检测窗(A=怪头顶 / B=人物技能带)判有无伤害数字色块:白描边/纯红/橙红/橙/亮黄互斥分箱,
        # 暖色闭合成团,以团bbox(外扩纳入白边)为分母算各色占比+上红下黄渐变,加扁条/超大形态门。返回(命中,info)。
        if roi is None or getattr(roi, 'size', 0) == 0:
            return False, {'reason': 'bad_roi', 'n_red': 0, 'n_org': 0, 'max_area': 0, 'max_h': 0, 'score': 0.0}
        rh, rw = roi.shape[0], roi.shape[1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hh, ss, vv = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        wht = (ss <= 55) & (vv >= 195)
        red = (((hh <= 8) | (hh >= 172)) & (ss >= 110) & (vv >= 140))
        ror = ((hh >= 9) & (hh <= 20) & (ss >= 170) & (vv >= 150))
        org = ((hh >= 9) & (hh <= 22) & (ss >= 85) & (vv >= 150) & (~ror))
        yel = ((hh >= 23) & (hh <= 32) & (ss >= 55) & (vv >= 170))
        warm = (red | ror | org | yel).astype(np.uint8) * 255
        warm = cv2.morphologyEx(warm, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=2)
        nlab, _lab, stats, _cent = cv2.connectedComponentsWithStats(warm, 8)
        best = None
        best_score = -9.0
        for _i in range(1, nlab):
            bx, by, bw, bh, ba = (int(x) for x in stats[_i])
            if bh < rh * DMG_MIN_H_R or bw < 8 or ba < 250:
                continue
            x0 = max(0, bx - DMG_PAD); y0 = max(0, by - DMG_PAD)
            x1 = min(rw, bx + bw + DMG_PAD); y1 = min(rh, by + bh + DMG_PAD)
            chh = y1 - y0; cww = x1 - x0
            area = float(max(1, chh * cww))
            cw = wht[y0:y1, x0:x1]; cr = red[y0:y1, x0:x1]; crr = ror[y0:y1, x0:x1]
            co = org[y0:y1, x0:x1]; cy = yel[y0:y1, x0:x1]
            rr = cr | crr
            pw = float(cw.sum()) / area
            pr = float(cr.sum()) / area
            prr = float(crr.sum()) / area
            po = float(co.sum()) / area
            py = float(cy.sum()) / area
            t3 = max(1, chh // 3)
            grad = float(rr[0:t3, :].mean()) - float(rr[chh - t3:, :].mean())
            ar = bw / float(max(1, bh))
            score = 3.0 * py + 2.0 * prr + 1.0 * pr + 1.2 * po + 1.5 * pw + 3.0 * grad
            flat = bool(ar > DMG_FLAT_AR and bh < rh * DMG_FLAT_H_R)
            big = bool(bh > rh * DMG_BIG_H_R)
            cooc = bool(py >= DMG_YEL_MIN and (prr + pr) >= DMG_RED_MIN)
            rec = {'score': round(score, 3), 'yel': round(py, 3), 'ror': round(prr, 3),
                   'red': round(pr, 3), 'org': round(po, 3), 'wht': round(pw, 3),
                   'grad': round(grad, 3), 'max_h': int(bh), 'ar': round(ar, 2),
                   'n_red': int(rr.sum()), 'n_org': int((co | cy).sum()), 'max_area': int(ba),
                   'flat': flat, 'big': big, 'co': cooc}
            if cooc and not flat and not big and score >= DMG_SCORE_T:
                rec['reason'] = 'hit'
                return True, rec
            if score > best_score:
                best_score = score
                rec['reason'] = 'flat' if flat else ('big' if big else ('color_low' if not cooc else 'score_low'))
                best = rec
        if best is None:
            best = {'reason': ('no_contour' if nlab <= 1 else 'all_small'),
                    'n_red': 0, 'n_org': 0, 'max_area': 0, 'max_h': 0, 'score': 0.0}
        return False, best

    def _detect_damage_number(self, target_cx, target_cy, frame=None, monsters=None, dbg=None,
                              person_center=None, skill_range=None):
        # 多点颜色加权检测伤害数字(2026-09-22)。A窗=出手怪基点X±DMG_A_X/Y上55~150;B窗=人物基点X±技能范围/Y上55~150;
        # 两窗逐暖色团评分,任一命中=有伤害=怪活着;不全图扫;B线程必须传本检测帧frame(禁止自行截图)。
        target_y1 = None
        _best_d = None
        for (x1m, y1m, x2m, y2m, _sm) in (monsters if monsters is not None else self._monsters):
            _d = abs(((x1m + x2m) // 2) - target_cx) + abs(y2m - target_cy)
            if _best_d is None or _d < _best_d:
                _best_d = _d
                target_y1 = y2m
        if frame is None:
            if not self._running and time.time() - self._raw_frame_t <= 0.6:
                frame = self._raw_frame
            else:
                frame = self._capture_window()
        if frame is None:
            if dbg is not None:
                dbg['reason'] = 'no_frame'
            return False
        fh, fw = frame.shape[0], frame.shape[1]
        wins = [('A', int(target_cx) - DMG_A_X, int(target_cy) - DMG_Y_UP,
                 int(target_cx) + DMG_A_X, int(target_cy) - DMG_Y_LO)]
        if person_center is not None and skill_range:
            _px, _py = person_center
            _sr = int(skill_range)
            wins.append(('B', int(_px) - _sr, int(_py) - DMG_Y_UP,
                         int(_px) + _sr, int(_py) - DMG_Y_LO))
        last = None
        for _tag, ax1, ay1, ax2, ay2 in wins:
            gx1, gy1 = max(0, ax1), max(0, ay1)
            gx2, gy2 = min(fw, ax2), min(fh, ay2)
            if gx2 - gx1 < 10 or gy2 - gy1 < 20:
                continue
            if self._hp_dmg_blocked((gx1 + gx2) / 2.0, (gy1 + gy2) / 2.0):
                if last is None:
                    last = {'reason': 'blocked', 'win': _tag, 'n_red': 0, 'n_org': 0,
                            'max_area': 0, 'max_h': 0, 'score': 0.0}
                continue
            hit, info = self._damage_roi_hit(frame[gy1:gy2, gx1:gx2])
            info['win'] = _tag
            if hit:
                if dbg is not None:
                    dbg.update(info)
                    dbg['ty'] = target_y1
                return True
            if last is None or float(info.get('score', -9)) > float(last.get('score', -9)):
                last = info
        if dbg is not None:
            if last is not None:
                dbg.update(last)
            dbg['ty'] = target_y1
        return False
'''

# ---------- 锚点3:两处调用补 person_center/skill_range ----------
c1_old = "_has_dmg = self._detect_damage_number(_fpos[0], _fpos[1], frame=frame, monsters=merged)"
c1_new = "_has_dmg = self._detect_damage_number(_fpos[0], _fpos[1], frame=frame, monsters=merged, person_center=(px, py), skill_range=_skr)"
must1(c1_old, 'call1')
c2_old = "_p_hit = self._detect_damage_number(_fposP[0], _fposP[1], frame=frame, monsters=merged, dbg=_pdb)"
c2_new = "_p_hit = self._detect_damage_number(_fposP[0], _fposP[1], frame=frame, monsters=merged, dbg=_pdb, person_center=(px, py), skill_range=_skr)"
must1(c2_old, 'call2')

# ---------- 锚点4(可选):探针日志补 得分/窗 ----------
l1_old = "_pdb.get('ty'), _pdb.get('reason')))"
l1_new = "_pdb.get('ty'), _pdb.get('reason'), _pdb.get('score'), _pdb.get('win')))"
l2_old = "原因=%s\" % ("
l2_new = "原因=%s 得分=%s 窗=%s\" % ("

if errors:
    print('ANCHOR FAIL, no write:')
    for e in errors:
        print('  ', e)
    sys.exit(3)

# 执行替换
src = src[:_const_m.end()] + CONST + src[_const_m.end():]
start = src.index(sig)
end = src.index('\n    def ', start)
src = src[:start] + NEW_FUNC + src[end:]
src = src.replace(c1_old, c1_new, 1)
src = src.replace(c2_old, c2_new, 1)
if src.count(l1_old) == 1 and src.count(l2_old) == 1:
    src = src.replace(l1_old, l1_new, 1)
    src = src.replace(l2_old, l2_new, 1)
    print('log probe: updated')
else:
    print('log probe: skipped (l1=%d l2=%d)' % (src.count(l1_old), src.count(l2_old)))

# CRLF 归一 + 写回(utf-8-sig 带BOM)
src = src.replace('\r\n', '\n').replace('\n', '\r\n')
with io.open(PATH, 'w', encoding='utf-8-sig', newline='') as f:
    f.write(src)
print('PATCH OK')
