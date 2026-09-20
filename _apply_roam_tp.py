# -*- coding: utf-8 -*-
"""巡游找怪加瞬移(用户2026-09-21定稿):无怪横向走到另一边太慢,在 _roam_tick 走路的同时,
符合瞬移条件就朝巡游方向闪一段(瞬移配合移动、不单独用);闪不成/冷却内自然落 _move_horizontal 走路,不发呆。
只改 _roam_tick 一处(不动公共函数 _move_horizontal,不影响走台/向梯);复用战斗/向梯瞬移同一套:
瞬移键+X距离配置、TP_COOLDOWN_MS 2秒冷却、_pre_teleport_release前摇、后摇、边界拉回冷却;
末段(剩余<全程30%)只走不闪防冲过头;不挂战斗pending校验(同向梯瞬移)。"""
import io, ast

P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
with io.open(P, "r", encoding="utf-8-sig", newline="") as f:
    s = f.read()

reps = []

# 1) 初始化巡游起点小地图X
reps.append((
"        self._roam_active = False         # 正在朝小地图远侧走路找怪\n"
"        self._roam_target_mx = None       # 巡游目标小地图X(光点像素)\n"
"        self._roam_cd_until = 0           # 巡游冷却截止ms(一次结束起15s)\n",
"        self._roam_active = False         # 正在朝小地图远侧走路找怪\n"
"        self._roam_target_mx = None       # 巡游目标小地图X(光点像素)\n"
"        self._roam_start_mx = None        # 巡游起点小地图X(算全程,末段30%停瞬移用)\n"
"        self._roam_cd_until = 0           # 巡游冷却截止ms(一次结束起15s)\n",
"init"))

# 2) 激活时记起点
reps.append((
"            self._roam_target_mx = _tgt\n"
"            self._roam_active = True\n",
"            self._roam_target_mx = _tgt\n"
"            self._roam_start_mx = mx\n"
"            self._roam_active = True\n",
"start"))

# 3) _move_horizontal 前插瞬移
reps.append((
"        if self._roam_target_mx is None:\n"
"            self._roam_end(False)\n"
"            return False\n"
"        try:\n"
"            _arrived = self._move_horizontal((mx, my), self._roam_target_mx, my)\n"
"        except Exception as _e:\n",
"        if self._roam_target_mx is None:\n"
"            self._roam_end(False)\n"
"            return False\n"
"        # === 巡游瞬移(用户2026-09-21):配合走路、不单独用。符合条件朝巡游方向闪一段,闪不成/冷却内落下面走路,不发呆 ===\n"
"        # 复用战斗/向梯瞬移同一套(键+X距离、2秒冷却、前摇后摇、边界拉回冷却),不挂战斗pending校验;末段30%只走不闪防冲过头。\n"
"        try:\n"
"            _rtcfg = self._get_fight_config()\n"
"            _rtp_key = _rtcfg.get(\"teleport_key\", \"\")\n"
"            _rtp_x = int(_rtcfg.get(\"teleport_distance\", 0) or 0)\n"
"            _rsgn = 1 if self._roam_target_mx > mx else -1\n"
"            _rrem = abs(self._roam_target_mx - mx)\n"
"            _rspan = abs(self._roam_target_mx - (getattr(self, '_roam_start_mx', mx) or mx))\n"
"            _rspan = _rspan if _rspan > 4 else _rrem\n"
"            _rside = 'right' if _rsgn > 0 else 'left'\n"
"            _rbound = (_rside == getattr(self, '_bound_last_side', None)\n"
"                       and now_ms < getattr(self, '_bound_tp_block_until', 0))\n"
"            if (bool(_rtp_key) and _rtp_x > 0\n"
"                    and now_ms - getattr(self, '_combat_last_h_teleport', 0) > TP_COOLDOWN_MS\n"
"                    and now_ms >= getattr(self, '_combat_tp_post_until', 0)\n"
"                    and not _rbound and _rrem > 0.3 * _rspan):\n"
"                # 配合移动:先朝巡游方向按住左右键(_move_horizontal同款_random_move_keys),瞬移不单独用\n"
"                if _rsgn > 0:\n"
"                    if VK_LEFT in self._random_move_keys:\n"
"                        self._key_up(VK_LEFT)\n"
"                    if VK_RIGHT not in self._random_move_keys:\n"
"                        self._key_down(VK_RIGHT)\n"
"                else:\n"
"                    if VK_RIGHT in self._random_move_keys:\n"
"                        self._key_up(VK_RIGHT)\n"
"                    if VK_LEFT not in self._random_move_keys:\n"
"                        self._key_down(VK_LEFT)\n"
"                self._pre_teleport_release()   # 松主攻+前摇(不松方向),攻击硬直过了才闪得出\n"
"                self._press_game_key(_rtp_key, duration=120)\n"
"                self._combat_last_h_teleport = now_ms   # 与战斗/向梯瞬移共用2秒冷却\n"
"                self._char_relocate_until = now_ms + 700   # 瞬移合法大跳变:人物识别700ms全图重捕\n"
"                self._rlog_throttle('roam_tp', \"巡游找怪朝%s瞬移(剩余小地图%.0fpx)\" % (_rside, _rrem), 800, log='behavior')\n"
"        except Exception as _rte:\n"
"            _debug_log(\"[巡游] 瞬移异常:%s\" % _rte)\n"
"        try:\n"
"            _arrived = self._move_horizontal((mx, my), self._roam_target_mx, my)\n"
"        except Exception as _e:\n",
"inject"))

# 4) _roam_end 清起点
reps.append((
"        self._roam_active = False\n"
"        self._roam_target_mx = None\n",
"        self._roam_active = False\n"
"        self._roam_target_mx = None\n"
"        self._roam_start_mx = None\n",
"end"))

for old, new, tag in reps:
    c = s.count(old)
    assert c == 1, "锚点不唯一/缺失 [%s] count=%d" % (tag, c)
    s = s.replace(old, new)

ast.parse(s)
with io.open(P, "w", encoding="utf-8-sig", newline="") as f:
    f.write(s)
print("ROAM_TP_OK")
