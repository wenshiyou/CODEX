# -*- coding: utf-8 -*-
"""块1b+块2（maple，BOM/LF）：
   1b 群攻去脚本CD、去80%随机，范围内>=3只(含3)即放（仅保留瞬移后摇门控、出手登记）；
   2  high_slope 跳高打加 _above2>0 硬校验，只打上方，永不打下方。下跳/下台一字不动。"""
import io
import py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py'
b = io.open(P, 'rb').read()
assert b.startswith(b'\xef\xbb\xbf'), 'maple 缺 UTF-8 BOM，中止'
raw = b[3:].decode('utf-8')
assert '\r\n' not in raw, 'maple 出现 CRLF，中止'

# ---------- 块1b：群攻段 ----------
old_aoe = (
    "        # 群攻：范围内>=3只怪，80%概率放（用户2026-09-07：删除随机漂移，稳定节奏）\n"
    "        aoe_key = fight_cfg.get(\"aoe_key\", \"\")\n"
    "        if not skill_cast and aoe_key:\n"
    "            aoe_dist = fight_cfg.get(\"aoe_distance\", 200)\n"
    "            aoe_cd = int(fight_cfg.get(\"aoe_interval\", 1000))  # 直接用配置值，不乘漂移\n"
    "            # A2修复：群攻\"范围内≥3只\"数完整怪表self._monsters(原数被覆盖的monster_dists只剩锁定1只→永远<3放不出)；口径同combat_logic的aoe_count：中心X/脚Y与人物差都在aoe_dist内\n"
    "            in_range = 0\n"
    "            for (_am_x1, _am_y1, _am_x2, _am_y2, _am_score) in self._monsters:\n"
    "                _am_cx = (_am_x1 + _am_x2) // 2\n"
    "                _am_cy = _am_y2\n"
    "                _am_dy = _am_cy - py  # 怪脚Y-人脚Y(负=在上,正=在下)\n"
    "                # 群攻计数：X用群攻射程aoe_dist，Y用群攻自己的上/下范围(用户2026-09-07独立于主攻：下层差太多打不到的怪不许凑数空放群攻)\n"
    "                if abs(_am_cx - px) <= aoe_dist and -_aoe_y_up <= _am_dy <= _aoe_y_down:\n"
    "                    in_range += 1\n"
    "            last = self._attack_last.get(\"aoe\", 0)\n"
    "            if in_range >= 3 and now - last > aoe_cd and now >= getattr(self, '_combat_tp_post_until', 0):\n"
    "                if random.random() < 0.8:\n"
    "                    # 群攻出手前同样短点朝锁定怪方向40ms(理由同主攻,治朝向漂移反打);双向近身群攻也不影响两侧出伤\n"
    "                    _afvk = VK_RIGHT if t_cx >= px else VK_LEFT\n"
    "                    self._send_win_key(_afvk, keyup=False)\n"
    "                    self._combat_timed_keys.append((_afvk, now + 40))\n"
    "                    self._press_game_key(aoe_key)\n"
    "                    self._attack_last[\"aoe\"] = now\n"
    "                    self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标(治\"群攻一直空打不停\")\n"
    "                    if not self._combat_first_strike_time:\n"
    "                        self._combat_first_strike_time = now\n"
    "                    skill_cast = True\n"
    "                    self._rlog(\"群攻 %s 范围内%d只\" % (aoe_key, in_range), (0, 165, 255))\n"
    "                    print(\"[群攻] %s 释放 (范围内%d只怪)\" % (aoe_key, in_range))\n"
)
new_aoe = (
    "        # 群攻：范围内>=3只(含3)即放、无脚本冷却(用户2026-09-18定稿:够3就群攻,不足3只走主攻)；仅瞬移前后摇窗内不发\n"
    "        aoe_key = fight_cfg.get(\"aoe_key\", \"\")\n"
    "        if not skill_cast and aoe_key:\n"
    "            aoe_dist = fight_cfg.get(\"aoe_distance\", 200)\n"
    "            # 群攻\"范围内≥3只\"数完整怪表self._monsters；口径同combat_logic的aoe_count：中心X/脚Y与人物差都在aoe_dist/Y带内\n"
    "            in_range = 0\n"
    "            for (_am_x1, _am_y1, _am_x2, _am_y2, _am_score) in self._monsters:\n"
    "                _am_cx = (_am_x1 + _am_x2) // 2\n"
    "                _am_cy = _am_y2\n"
    "                _am_dy = _am_cy - py  # 怪脚Y-人脚Y(负=在上,正=在下)\n"
    "                # 群攻计数：X用群攻射程aoe_dist，Y用群攻自己的上/下范围(下层差太多打不到的怪不许凑数空放群攻)\n"
    "                if abs(_am_cx - px) <= aoe_dist and -_aoe_y_up <= _am_dy <= _aoe_y_down:\n"
    "                    in_range += 1\n"
    "            if in_range >= 3 and now >= getattr(self, '_combat_tp_post_until', 0):\n"
    "                # 群攻出手前短点朝锁定怪方向40ms(治朝向漂移反打);双向近身群攻也不影响两侧出伤\n"
    "                _afvk = VK_RIGHT if t_cx >= px else VK_LEFT\n"
    "                self._send_win_key(_afvk, keyup=False)\n"
    "                self._combat_timed_keys.append((_afvk, now + 40))\n"
    "                self._press_game_key(aoe_key)\n"
    "                # 仍登记出手时刻(站桩输出判定GLOBAL_SKILL_HB_MS用),只是不再拿它当群攻CD门控(用户2026-09-18群攻无CD)\n"
    "                self._attack_last[\"aoe\"] = now\n"
    "                self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标\n"
    "                if not self._combat_first_strike_time:\n"
    "                    self._combat_first_strike_time = now\n"
    "                skill_cast = True\n"
    "                self._rlog(\"群攻 %s 范围内%d只\" % (aoe_key, in_range), (0, 165, 255))\n"
    "                print(\"[群攻] %s 释放 (范围内%d只怪)\" % (aoe_key, in_range))\n"
)

# ---------- 块2：跳高只向上硬校验 ----------
old_hs = (
    "        high_slope = bool(_slope_on) and bool(self.platforms) and not getattr(self, '_combat_transit', False) \\\n"
    "            and now >= getattr(self, '_slope_resume_at', 0) \\\n"
    "            and (_sj_min <= _above2 <= _sj_max) and abs(_ref_x - px) <= skill_range  # 用户2026-09-11:X差必须<技能攻击范围才跳打(原4/5停步线)\n"
)
new_hs = (
    "        high_slope = bool(_slope_on) and bool(self.platforms) and not getattr(self, '_combat_transit', False) \\\n"
    "            and now >= getattr(self, '_slope_resume_at', 0) \\\n"
    "            and _above2 > 0 and (_sj_min <= _above2 <= _sj_max) and abs(_ref_x - px) <= skill_range  # 硬校验只打上方(_above2>0,用户2026-09-18:跳高永不打下方);X差须<技能范围\n"
)

for i, (o, n) in enumerate([(old_aoe, new_aoe), (old_hs, new_hs)], 1):
    c = raw.count(o)
    assert c == 1, '块%d 锚点命中 %d 次（应为1），中止' % (i, c)
    raw = raw.replace(o, n)

io.open(P, 'wb').write(b'\xef\xbb\xbf' + raw.encode('utf-8'))
py_compile.compile(P, doraise=True)
print('BLOCK1b+2 maple OK, py_compile pass')
