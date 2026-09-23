# -*- coding: utf-8 -*-
# 补丁离线验证: 不实例化/不起线程, 未绑定方法 + 源码常量 + AST遮蔽扫描
import io, re, ast, types, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
src = io.open(P, "rb").read().decode("utf-8-sig")
fails = []
def ck(cond, msg):
    print(("[OK] " if cond else "[FAIL] ") + msg)
    if not cond: fails.append(msg)

# 1) 旧字段/旧常量清零(self.last_player_pos 词边界, 排除 _last_player_pos_ok)
n_lpp = len(re.findall(r"(?<![\w])self\.last_player_pos\b", src))
ck(n_lpp == 0, "self.last_player_pos 彻底清零(剩%d)" % n_lpp)
ck("_last_smooth_dot" not in src, "_last_smooth_dot 彻底清零")
ck("ROLE_BIGJUMP_PX" not in src, "ROLE_BIGJUMP_PX 固定120常量已移除")
ck("_PERSON_BUSY_MAX_MS" not in src, "_PERSON_BUSY_MAX_MS 旧忙档常量已移除")
ck(src.count("_last_player_pos_ok") >= 2, "_last_player_pos_ok 无关标志保留(%d)" % src.count("_last_player_pos_ok"))

# 2) 新常量/字段就位
for k in ["ROLE_MAX_SPEED_PX_S", "ROLE_BIGJUMP_FLOOR_PX", "ROLE_BIGJUMP_CAP_PX",
          "PERSON_BUSY_TARGET_MS", "PERSON_BUSY_PERIOD_MAX", "PERSON_BUSY_MIN_SLEEP_MS",
          "PERSON_BUSY_OVERLOAD_N", "PERSON_BUSY_RELAX_N", "PERSON_BUSY_STEP_MS",
          "_busy_adapt_p", "_bigjump_log_t", '"last_t"']:
    ck(k in src, "新符号就位: " + k)

# 3) 速度闸阈值数值(用源码常量, 验证数学边界)
ns = {}
for name in ["ROLE_MAX_SPEED_PX_S","ROLE_BIGJUMP_FLOOR_PX","ROLE_BIGJUMP_CAP_PX"]:
    m = re.search(r"^%s\s*=\s*([0-9.]+)" % name, src, re.M)
    ns[name] = float(m.group(1))
def lim(dt):
    return min(ns["ROLE_BIGJUMP_CAP_PX"], max(ns["ROLE_BIGJUMP_FLOOR_PX"], ns["ROLE_MAX_SPEED_PX_S"]*dt/1000.0))
v33, v100, v16, v60 = lim(33), lim(100), lim(16), lim(60)
print("    阈值 dt33ms=%.0f dt60ms=%.0f dt100ms=%.0f dt16ms=%.0f" % (v33,v60,v100,v16))
ck(abs(v33-60)<1e-6 and abs(v100-150)<1e-6 and abs(v16-60)<1e-6 and abs(v60-108)<1e-6, "速度闸: 30fps夹60 / 旧16fps=108 / 低帧夹150")
# 本次事故误匹配70px@忙档: 30fps下70>60被拦; 真实跑步<60放行
ck(70 > v33, "误匹配70px@30fps 被拦(70>%.0f)" % v33)

# 4) import 模块(不起线程), 未绑定方法行为
sys.path.insert(0, r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2")
import maple_route_ui as M
Cls = M.MinimapRouteRecorder
ck(Cls.find_player_dot(types.SimpleNamespace(), None) is None, "find_player_dot(None) 返回None不钉旧值")
ck(Cls.find_player_dot(types.SimpleNamespace(size=0), None) is None, "find_player_dot(size=0) 返回None")

# 爬梯中(_climb_state!=none)光点None: 只暂停本帧, 不终止/不清状态
s1 = types.SimpleNamespace(_combat_transit=True, _player_map_pos=None, _climb_state="climbing",
                           _transit_target=("KEEP",), _ladder_precise_mode=True)
Cls._transit_step(s1)
ck(s1._combat_transit is True and s1._transit_target == ("KEEP",) and s1._ladder_precise_mode is True,
   "爬梯中丢光点: 不终止跨层/不清状态/不松键")
# 未进梯(walk/none)光点None: 终止回打怪
s2 = types.SimpleNamespace(_combat_transit=True, _player_map_pos=None, _climb_state="none",
                           _transit_target=("X",), _ladder_precise_mode=True,
                           _transit_via="ladder")
Cls._transit_step(s2)
ck(s2._combat_transit is False and s2._transit_target is None and s2._ladder_precise_mode is False,
   "非爬梯段丢光点: 终止跨层回打怪(原行为保留)")

# 5) AST 命名遮蔽: 新增 self 属性不得与方法名重名
tree = ast.parse(src)
method_names = set()
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        for b in node.body:
            if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_names.add(b.name)
new_attrs = {"_busy_adapt_p","_busy_ov_n","_busy_rx_n","_bigjump_log_t"}
shadow = new_attrs & method_names
ck(not shadow, "AST命名遮蔽扫描(新增属性 vs 方法名) 无交集: %s" % (shadow or "无"))

print("\n==== %s ====" % ("全部通过" if not fails else ("%d项失败: %s" % (len(fails), fails))))
sys.exit(1 if fails else 0)
