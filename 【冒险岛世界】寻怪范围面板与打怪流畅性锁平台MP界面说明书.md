# 【冒险岛世界】寻怪范围面板 + 打怪流畅性 + 锁单平台 + MP界面门控 说明书

> 版本：冒险岛世界（msw.exe，强绑 1276×749）
> 日期：2026-09-07
> 主程序：`maple_route_ui.py`；纯决策：`combat_logic.py`（单测 test_combat_sim.py 38/38 PASS）
> 上一快照：e9b8ff5；本说明书对应 e9b8ff5 之后到本次提交之间的全部真机已验收改动。

---

## 一、功能总览（本次全部正常功能）

1. **寻怪范围可自定义 X/Y**：原写死的同平台寻怪 X=800、同平台 Y=150 改成面板可设，默认 **X=1300（左右各 1300，共用一个值）、Y=150（上下共用）**。
2. **fight 页三按钮一排（各 135×39，原图不缩放、统一按压变暗）**：
   - 第1位「瞬移设置」`BTN_TP_SETTING=(22,288)`；
   - 第2位「寻怪范围」`BTN_SEARCH_RANGE=(170,288)`，**替换原"动作录制"占位按钮**，图 `data/search_range_btn.jpg`；
   - 第3位「技能Y范围」`BTN_Y_RANGE=(312,288,135,39)`，由原 94×32 小按钮换成 `data/skill_y_range_btn.jpg`，热区同步放大到 135×39。
3. **寻怪范围弹窗**（与 Y 范围/瞬移弹窗同款：灰底白字、标题栏可全屏拖拽、右上 X、确认/取消、最上层）：两条输入 `X 左右各`(far_range_x)、`Y 同平台`(far_range_y)，确认才保存，取消/点外部回退。
4. **群攻独立 Y 范围（4 条弹窗）**：Y 弹窗内分「主攻 上/下」「群攻 上/下」共 4 条，群攻默认 **上 -60 / 下 +30**；群攻计数 Y 用群攻自己的范围，下层够不着的怪不再凑数空放。
5. **空打（打空气）根因修复**：打一下后约 250ms 内既无血条也无伤害数字即放弃换目标，不再打三四下。
6. **打怪不带方向键**：进入攻击范围够得着就松开所有方向键"站定只打怪"，删掉原"攻击时随机小走位"；方向键只在追怪（pursue）和够不着的高坡/下坡贴近时按。
7. **位移解卡窗口 450ms→5000ms**：按住方向真 5 秒没动才判定卡住、重按方向+跳一下；连续 2 次（约 10 秒）才放弃该怪改锁最近怪。平地正常追怪/坐标小抖动不再误跳。
8. **锁单平台绿线硬边界**：勾选平台编号后，人物移动硬边界直接取"勾选平台绿线"的小地图 X 范围（不依赖脚下离哪条线近），追怪/上坡/下坡走到绿线端点即停；勾选时禁用"正下方按下+跳落层"，保证只在该台子绿线内打、不掉下去。
9. **自动吃药 MP 界面门控恢复**：必须"窗口在前台 **且** 底部横带匹配到 MP 文字标志（≥0.85）"才加血加蓝；小退/选角/活动弹窗等无血条界面一律不加。

---

## 二、寻怪范围面板（功能 1~3）

### 2.1 数据链路
- 字段：`far_range_x`（默认 `COMBAT_FAR_RANGE=1300`）、`far_range_y`（默认 `FAR_RANGE_Y_DEFAULT=150`）。
- 登记：`known_ids` 加两字段；`_get_fight_config()` 读取（空值回退默认，X 下限 50、Y 下限 10 兜底）。
- 落盘：`data/fight_potion_config.json`（运行时配置，不入 git）。
- 生效：
  - 战斗 tick 读 `_far_x/_far_y`，两处决策调用（`combat_logic.select_combat_target`、`combat_logic.combat_step`）的 far_range 传 `_far_x`（不再传写死常量）。
  - `_is_monster_on_platform()` 的同平台 Y 容差用 `self._far_range_y`（=旧 LAYER_Y_GAP，默认 150）。

### 2.2 弹窗全套（仿 Y 范围弹窗）
- 状态：`_show_search_dialog/_search_dialog_pos[70,230]/_search_dialog_dragging/_search_dialog_backup`。
- 控件：`_dlg_search_x_input/_dlg_search_y_input/_dlg_search_ok_btn/_dlg_search_cancel_btn/_dlg_search_close_btn`，dlg 320×200。
- 方法：`_update_search_dialog_positions / _open_search_range_dialog / _restore_search_dialog_backup / _handle_search_dialog_event / _draw_search_dialog`。
- 分发：`_on_mouse` fight 分支"弹窗最上层优先"加 search；按钮点击区 `BTN_SEARCH_RANGE`→打开弹窗；绘制 `_draw_search_range_btn` + 最上层 `_draw_search_dialog`。

### 2.3 关键参数
| 项 | 值 |
|---|---|
| 默认 X（左右各） | 1300（旧写死 800） |
| 默认 Y（同平台容差） | 150 |
| 按钮尺寸/位置 | 瞬移(22,288)/寻怪(170,288)/技能Y(312,288)，均 135×39 |
| 图片加载 | jpg 无 alpha、中文路径 cv2.imread 会失败 → 复制进 data 改英文名，用 `cv2.imdecode(np.fromfile(p,np.uint8),IMREAD_UNCHANGED)` |

### 2.4 踩坑
- jpg 是 3 通道，叠加走"直接贴"分支（无 alpha 混合）；原图不缩放，`min(iw,bw)` 取原图大小。
- 三个 135 宽按钮一排右缘到 x=447，UI_W=461，不超界。

---

## 三、群攻独立 Y + 空打修复（功能 4、5）

### 3.1 群攻 4 条 Y
- Y 弹窗 dlg_h 220→315；字段 `attack_y_up/down`（主攻，默认 -60/+30）、`aoe_y_up/down`（群攻，默认 -60/+30）。
- 战斗 tick 读 `_aoe_y_up/_aoe_y_down`；群攻 in_range 计数条件：`abs(cx-px)<=aoe_dist 且 -_aoe_y_up<=怪脚Y-人脚Y<=_aoe_y_down`。
- 群攻释放也置 `_combat_target_attacked=True + _combat_first_strike_time`，使群攻空放同样走 250ms 空怪 drop。

### 3.2 空打根因（关键）
- **根因不是 250ms 宽限太长**，而是锁定处用**精确坐标相等**判断"是否换目标"，怪检测框每帧抖几 px → 每帧误判换新目标 → 首次出手计时/已出手标记反复清零 → 250ms 永远攒不够，拖到假怪超时（打 3~4 下）。
- **修复**：容差判同一只 `_is_new_target = 旧锁None 或 |dx|>40 或 |dy|>50`（与 select 维持锁定容差一致），同一只抖动不重置。
- 反馈链：主攻/群攻出手置 attacked+首次出手时间；`attacked 且 now-首次>250ms 且 无血条 且 无伤害 → drop`；drop 进 `_combat_dropped_phantoms`（±60px/3 秒不重锁）。

---

## 四、打怪不带方向 + 解卡 5 秒（功能 6、7）

### 4.1 站定只打怪
- 进入攻击范围后的**平地分支**（非 high_slope 非 _below2）：删掉原 5~9 秒 roll、20% 走 40~120px 的"随机小走位"，改为每帧 `_release_combat_move()` 站定。
- 主攻门控本就要求 `move_dir is None 且 held 空 且 X≤射程 且 Y 在[-上,+下]`，站定后才点按攻击。
- 方向键只保留在：①追怪 `t_dist>effective_range`；②高坡走跳（怪比人高>攻击上容差，真够不着）；③下坡贴近（怪比人低>攻击下容差）。

### 4.2 解卡时间
| 常量 | 旧 | 新 | 含义 |
|---|---|---|---|
| MOVE_STALL_CHECK_MS | 450 | **5000** | 按住方向后 5 秒 X 没朝该方向走够 10px 才算卡住 |
| MOVE_MIN_DX | 10 | 10 | 一个窗口至少移动的 X 像素 |
| MOVE_STALL_ABORT | 2 | 2 | 连续 2 次（≈10 秒）放弃该怪、改锁最近怪 |

- `_check_move_blocked()`：卡住先强制松发一次方向键（绕过"方向没变不重发"缓存）+跳一下；`_abort_unreachable_target()` 连续失败则加入幻影过滤、清锁定/移动/相位、下帧重选。

---

## 五、锁单平台绿线硬边界（功能 8）

### 5.1 背景
旧移动边界用 `_get_current_platform()`（人物离某条绿线≤10px 才算站在该平台），跳到半空/斜坡会判 None → 边界失效 → 可能走出绿线掉层。

### 5.2 实现
- `_locked_platform_x_range()`：勾选了平台编号时，取这些平台（显示编号=`pf['id']+1`）绿线在**小地图**上 X 的并集 `(min,max)`；未勾选（全图模式）返回 None。
- `_combat_at_locked_edge(move_dir)`：优先用勾选绿线硬边界（不依赖脚下判定），没勾才退回当前所在平台；朝该方向到端点（留 2px）返回 True。
- 接入点：追怪段、下坡斜走段、高坡走跳段，`_set_combat_move` 前先判到边 → 松方向/停；正下方落层分支在 `_selected_platforms` 非空时禁用（松 VK_DOWN，不落层）。
- 选怪过滤本就有效：`combat_logic.select_combat_target` 只把归属到选中平台绿线的怪当候选，且 `ENABLE_CROSS=False` 不跨平台。

### 5.3 行为
- 只勾 1 个台子：只在该绿线 X 范围内左右找怪/打怪，到边停、不掉层、不去别的台子。
- 勾多个台子：本台无怪才跨台（走/跳/瞬移/梯子，由 `_transit_step` 处理）。
- 前提：绿线录准、小地图光点定位准（边界=人物小地图 X 比绿线端点）。

---

## 六、自动吃药 MP 界面门控（功能 9）

### 6.1 问题
后来加的"窗口激活(前台)就吃药"把旧 MP 模板门控架空；且 `data/templates` 为空，模板没加载；旧实现全窗口匹配 + 阈值 0.35 太松，活动弹窗上半屏会误匹配 0.58。结果：小退/选角/活动画面（窗口仍在前台但无血条）也在加药。

### 6.2 最终方案
- 模板：`data/templates/mp_label.png`（29×18，"MP"文字，用户提供）。
- 搜索区（用户指定）：**X 从 0 到 1300、Y 只取底部往上 60px 横带**（`roi=frame[h-60:h, 0:min(1300,w)]`），不再全窗口搜，更快更准。
- 匹配：`TM_CCOEFF_NORMED`，阈值 **`MP_LABEL_THRESH=0.85`**（真机实测：正常游戏 0.9686、活动弹窗底部带 0.4607，0.85 彻底分开）。
- 门控：`in_game = 窗口前台(GetForegroundWindow==hwnd) 且 _is_mp_label_visible(frame)`；只有 in_game 才检测 HP/MP 并按键；否则清掉 HP/MP 待按计时防回游戏瞬间误补，2 秒节流日志"未检测到MP界面"。
- 无模板时 `_is_mp_label_visible` 返回 True（不拦截，兼容缺模板场景）。

### 6.3 验证
- 正常打怪：日志 `[吃药诊断] ... MP界面=True`，低血蓝正常补。
- 活动弹窗/小退选角：日志"未检测到MP界面(小退/选角?)，暂不加血加蓝"，不按药。
- 若正常游戏偶尔判 False：看 `[吃药诊断]` 匹配分，下调阈值；若小退还误判 True，上调阈值。

---

## 七、验证清单（本次真机已过）
- [x] py_compile 通过；test_combat_sim.py 38/38 PASS。
- [x] fight 页三按钮一排、原图不缩放、按压变暗、点击热区正确。
- [x] 寻怪范围弹窗默认 X1300/Y150，输入/拖拽/确认取消/最上层正常，改值实际影响选怪距离。
- [x] 平地打怪站定不跳、不带方向；追怪才走；真卡住 5 秒才跳。
- [x] 单攻/群攻空打约打一下（250ms）就换；群攻不对下层空放、默认 -60/+30。
- [x] 只勾 1 个台子时在绿线内打、到边停、不掉层。
- [x] 游戏内正常补药；活动/小退画面 MP界面=False 不补。

## 八、回滚
- 本次提交为可 100% 回滚快照；本地完整备份 zip 在 `backups/`（文件名带时间戳与"冒险岛世界"）。
- 运行时配置 `data/fight_potion_config.json`、`backups/*.zip` 不入 git。
