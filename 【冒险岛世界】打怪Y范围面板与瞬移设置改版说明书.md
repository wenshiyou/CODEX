# 【冒险岛世界】打怪Y范围面板 + 瞬移设置改版 说明书

> 版本：冒险岛世界 MapleStory Worlds（唯一主线；怀旧服仅参考）
> 完成日期：2026-09-07
> 主程序：`maple_route_ui.py`（单体 UI+执行）；纯决策：`combat_logic.py`（本次未改）
> 关联：强绑窗口 1276×749、小地图三模板见《【冒险岛世界】强绑窗口尺寸与小地图三模板定位说明书.md》；弹窗统一做法见《弹窗组件实现规范与做法.md》

---

## 一、本次功能总览（两块）

1. **打怪Y范围面板化**：打怪页新增绿色「Y距离」按钮，点击弹窗设置「上方打怪范围 / 下方打怪范围」，替代原来写死的常量 `ATTACK_Y_UP=60 / ATTACK_Y_DOWN=30`。**以人物脚底为基点：上方为负、下方为正，默认 上-60 / 下+30，允许负数。**
2. **瞬移设置改版**：
   - 取消打怪页原来的「瞬移技能键框 + 瞬移距离框」两个录入框（值仍保留在配置里），改为绿色「瞬移设置」按钮 + 「动作录制」占位按钮（功能后做），两张原图并排**完整盖住原两个输入框区域**。
   - 点「瞬移设置」弹窗设置 **X瞬移距离（水平追怪）/ Y瞬移距离（垂直上下）**，**默认都为空；X 或 Y 任一填了值、且瞬移技能键存在才会瞬移，两个都空 = 完全不瞬移（纯走路/跳/梯子）。**

---

## 二、打怪Y范围（Y距离按钮）

### 2.1 按钮
- 常量 `BTN_Y_RANGE = (312, 291, 94, 32)`：瞬移行右侧，贴图 `data/y_range_btn.png`（用户原图 94×32，带 alpha，**不缩放、不改背景**，alpha 混合叠加）。
- 按下统一变暗特效（`_pressed_btn` + 圆角半透明黑 addWeighted，与其他按钮一致）。
- 绘制：`_draw_y_range_btn()`，在 `draw()` 的 fight 分支叠加。

### 2.2 弹窗（`_draw_y_dialog` / `_handle_y_dialog_event`）
- 320×220 灰底白字、标题栏（顶部50px）可在控制面板内全屏拖拽、右上角 X、绿确认 / 深蓝取消，布局同倍率差弹窗。
- 两个输入框：
  - `attack_y_up` 上方范围，**默认 -60**
  - `attack_y_down` 下方范围，**默认 30（即+30）**
- 点框聚焦（橙框）→ 键盘输入；**确认才 `_save_input_config` 保存；取消 / X / 点窗口外 = 用 `_y_dialog_backup` 回退，不保存。**

### 2.3 方向约定（重点，别再改反）
- 屏幕坐标 Y 向下增大；以**人物脚底**为基点，怪脚 Y - 人脚 Y = `dy`：怪在上方 `dy<0`、下方 `dy>0`。
- 所以 UI 上「上方」填**负数**（-60）、「下方」填**正数**（+30），符合直觉。
- **决策层仍用正数容差**：`combat_logic.select_combat_target` 的判定是 `-attack_y_up <= dy <= attack_y_down`（形参是两个正数）。因此在 `_get_fight_config()` 返回有向原始值（-60/30），在调用决策前用 `abs()` 归一化成正容差，**combat_logic 与 36 个单测完全不用改**：
  - `_combat_tick`：`_atk_y_up = abs(int(fight_cfg.get("attack_y_up", -ATTACK_Y_UP)))`、`_atk_y_down = abs(...)`；诊断 `_yok` 与 `combat_step(...)` 末参都用这两个。
  - `_shadow_combat_decision`：`_sy_up/_sy_dn` 同样 abs。
- 常量 `ATTACK_Y_UP=60 / ATTACK_Y_DOWN=30`（约 295 行）保留，只作为**缺省值**来源（UI 缺省显示 `-ATTACK_Y_UP`/`ATTACK_Y_DOWN`）。

### 2.4 负数输法（沿用既有机制，PROJECT 有记录）
- 数字真正走 `_poll_num_input()`（GetAsyncKeyState 全局轮询，**不是** `_handle_input_key`）。
- 允许负号的字段白名单**两处都要加**（历史踩坑：只加一处会输不了负号）：
  - `_poll_num_input` 减号分支（VK 0xBD 主键盘 / 0x6D 小键盘）白名单；
  - `_handle_input_key` 的 `_is_offset` 白名单（备用路径）。
- 操作：聚焦后按「-」在开头切换负号（再按取消），再输数字；也可先输数字再按减号。Y 范围**不加入小数点白名单**（只要整数）。

---

## 三、瞬移设置改版

### 3.1 取消原两个录入框
- `FIGHT_FIELDS` 中删除 `teleport_key`(原100,294)、`teleport_distance`(原243,294) 两行 → 主界面不再绘制、不再点击录入。
- **值不丢**：`_save_input_config()` 的 `known_ids` 手动 `.add("teleport_key")/.add("teleport_distance")/.add("teleport_distance_y")`，否则保存时会被过滤掉。
- 瞬移技能键 `teleport_key`（当前=z）**沿用配置文件已存值**，主界面不再提供改键入口（后续需要再加）。

### 3.2 两个并排按钮（原图 135×39，不拉伸）
- `BTN_TP_SETTING = (22, 288, 135, 39)`「瞬移设置」，贴图 `data/tp_setting_btn.png`：左缘 x=22 与上一行「跳跃」文字对齐，盖住「瞬移：」文字与原瞬移键框（到 x157）。
- `BTN_ACTION_RECORD = (170, 288, 135, 39)`「动作录制」，贴图 `data/action_record_btn.png`：盖住「距离：」文字与原距离框（到 x305）。**当前仅占位显示，不响应点击，功能后续再做。**
- 两按钮中间 157–170 正好是原键框与「距离」之间的空隙；右侧 x312 起是「Y距离」按钮，互不重叠。
- 坐标依据：扫描 `data/ui_tab_fight.png` 深色像素——「瞬移」文字 x24-74、「距离」x173-235、原键框 100-154、原距离框 243-305。

### 3.3 X/Y瞬移距离弹窗（`_draw_tp_dialog` / `_handle_tp_dialog_event` / `_open_tp_dialog`）
- 布局、拖拽、确认/取消/X 与 Y 范围弹窗完全一致；标题「瞬移距离(px)·空=不瞬移」。
- 字段：`teleport_distance`（X瞬移距离）、`teleport_distance_y`（Y瞬移距离），**默认空字符串**；只输非负整数（不在负号/小数点白名单），可退格清空。
- `_get_fight_config()`：两者 `int(... or "0")`，空=0。

### 3.4 瞬移启用与执行（关键逻辑）
统一原则：**有瞬移技能键 且（X>0 或 Y>0）才会瞬移；全 0/空 = 不瞬移。**

- **水平瞬移（走路/追怪时距离远就闪）**——在 `_combat_tick` 追怪段（`t_dist > effective_range`，已 `_set_combat_move(move_dir)` 按住朝怪方向键之后）：
  - 条件：`teleport_key` 存在、`teleport_distance(X)>0`、水平差 `t_dist >= X`、且**基本同层 `abs(t_cy-py)<=40`**（避开高怪跳/垂直瞬移抢动作）、距上次水平瞬移 `>850ms`（节流 `_combat_last_h_teleport`）。
  - 动作：方向键已按住，直接 `_press_game_key(瞬移键,60)`，游戏内即朝移动方向瞬移一段，实现边追边闪快速贴近。
- **垂直瞬移（跳不上去/下不去的落差）**——`_move_to` 垂直攀爬段（约 3380 行）：
  - 原来用 `teleport_distance` 判垂直，**改为 `teleport_distance_y`**：`tp_dist = fight_cfg.get("teleport_distance_y",0)`，仅当 `tp_key 且 tp_dist>0 且 tp_dist>=垂直gap` 才 `_do_teleport()`（按上/下方向+瞬移键）；Y 不填则走「跳 → 梯子」老路径。

---

## 四、配置字段（data/fight_potion_config.json）
| 字段 | 含义 | 默认 | 备注 |
|---|---|---|---|
| attack_y_up | 上方打怪范围（有向） | "-60" | 负数；决策前 abs |
| attack_y_down | 下方打怪范围（有向） | "30" | 正数；决策前 abs |
| teleport_key | 瞬移技能键 | 沿用已存(z) | 主界面不再录入 |
| teleport_distance | X瞬移距离（水平追怪） | 空=0 | >0 才水平瞬移 |
| teleport_distance_y | Y瞬移距离（垂直） | 空=0 | >0 才垂直瞬移 |

---

## 五、代码位置地图（行号为约值，以 Grep 为准）
- 常量：`BTN_Y_RANGE`、`BTN_TP_SETTING`、`BTN_ACTION_RECORD`（约 204-210）；`ATTACK_Y_UP/DOWN`（约295）。
- `FIGHT_FIELDS`：已删瞬移两框（约369有说明注释）。
- `__init__`：Y弹窗状态、TP弹窗状态、`_y_range_btn_img/_tp_setting_btn_img/_action_record_btn_img`、`_combat_last_h_teleport`（约705-735）。
- 弹窗坐标/打开/回退：`_update_y_dialog_positions/_open_y_range_dialog/_restore_y_dialog_backup`、`_update_tp_dialog_positions/_open_tp_dialog/_restore_tp_dialog_backup`（约1150-1240）。
- 鼠标：`_on_mouse` 的 fight 分支（两弹窗最上层优先 → Y按钮 → 瞬移设置按钮 → 普通输入）；`_handle_y_dialog_event`、`_handle_tp_dialog_event`。
- 绘制：`draw()` fight 分支；`_draw_y_range_btn/_draw_y_dialog/_draw_tp_setting_btn/_draw_tp_dialog/_draw_action_record_btn`。
- 输入白名单：`_poll_num_input` 减号分支、`_handle_input_key` 的 `_is_offset`。
- 保存/读取：`_save_input_config`（known_ids）、`_get_fight_config`。
- 决策接通：`_combat_tick`（abs 归一化 + 水平瞬移）、`_shadow_combat_decision`（abs）、`_move_to`（垂直瞬移改读 Y）。

---

## 六、坑 / 注意事项
1. **数字输入走 `_poll_num_input` 不走 `_handle_input_key`**：负数白名单必须两处都加，否则按减号没反应（历史已多次踩）。
2. **UI 有向、决策取 abs**：不要把 combat_logic 改成有向，否则 36 个单测与 `y_ok` 语义全乱；只在调用边界 abs。
3. **移出 FIGHT_FIELDS 的字段必须加进 `_save_input_config` 的 known_ids**，否则一保存就被过滤丢值。
4. `_save_input_config` 是「只重写 known_ids 内字段」，会把不在白名单的旧键（如 match_sim）冲掉——本次未扩大该问题，但后续新增配置要一并补白名单。
5. 按钮一律**原图尺寸 alpha 叠加、不缩放、不改 ui_tab_fight.png 背景**；按压变暗用统一 overlay。
6. `data/fight_potion_config.json`、`data/minimap_region.json` 是**运行时状态**（用户键位/自动检测区域），不纳入功能代码提交；新字段缺省值由代码兜底，不依赖 json。
7. 水平瞬移限「基本同层(Y差≤40)」+ 850ms 节流，避免和高怪跳、垂直瞬移互相打架；真机手感（节流时长/同层阈值）后续可按实测调。

---

## 七、验证记录
- `py_compile maple_route_ui.py` 语法 OK；`test_combat_sim.py` **36/36 PASS**（决策层未破坏）。
- 真机：用户确认两个 135×39 按钮并排完美盖住原瞬移两框、与「跳跃」X 对齐；Y范围弹窗默认 -60/30；瞬移弹窗默认空。
- 本地完整备份：`backups/源码完整备份_冒险岛世界_Y范围与瞬移改版_20260907_000606.zip`（及同名文件夹，纯本地）。
