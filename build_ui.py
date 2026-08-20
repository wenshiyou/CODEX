"""
Build UI background from assets:
- Base: asset_base.png (blank frame with title + tabs)
- Buttons row1+2: data/templates/btn_bar.png
- Bottom group: asset_bottom.png (run/stop, subtabs, log, window bind)
- Window bind text: asset_5889.png
- Window bind crosshair: asset_777.png
"""
import cv2
import numpy as np

def overlay_with_alpha(bg, fg, x, y):
    """Overlay fg (with alpha) onto bg at (x,y)"""
    fh, fw = fg.shape[:2]
    bh, bw = bg.shape[:2]
    # clip
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(bw, x + fw), min(bh, y + fh)
    if x2 <= x1 or y2 <= y1:
        return
    fg_x1, fg_y1 = x1 - x, y1 - y
    fg_x2, fg_y2 = fg_x1 + (x2 - x1), fg_y1 + (y2 - y1)
    roi = bg[y1:y2, x1:x2]
    if fg.shape[2] == 4:
        alpha = fg[fg_y1:fg_y2, fg_x1:fg_x2, 3:4].astype(float) / 255.0
        color = fg[fg_y1:fg_y2, fg_x1:fg_x2, :3].astype(float)
        bg[y1:y2, x1:x2] = (alpha * color + (1 - alpha) * roi.astype(float)).astype(np.uint8)
    else:
        bg[y1:y2, x1:x2] = fg[fg_y1:fg_y2, fg_x1:fg_x2, :3]

# === 1. Load and scale base ===
base = cv2.imread('asset_base.png', cv2.IMREAD_UNCHANGED)
bh, bw = base.shape[:2]
TARGET_W = 330
scale = TARGET_W / bw
TARGET_H = int(bh * scale)
base_small = cv2.resize(base, (TARGET_W, TARGET_H), interpolation=cv2.INTER_AREA)
print(f"Base scaled: {TARGET_W}x{TARGET_H}")

# Convert to BGR (drop alpha for final, we'll add elements on top)
if base_small.shape[2] == 4:
    # composite onto white background
    bg = np.ones((TARGET_H, TARGET_W, 3), dtype=np.uint8) * 255
    alpha = base_small[:, :, 3:4].astype(float) / 255.0
    bg = (alpha * base_small[:, :, :3].astype(float) + (1 - alpha) * bg.astype(float)).astype(np.uint8)
else:
    bg = base_small.copy()

# === 2. Content area starts after tabs ===
# From analysis: title ~y34, tabs ~y34-65, content from ~y65
CONTENT_TOP = 66

# === 3. Buttons row 1+2 (btn_bar.png) ===
btn_bar = cv2.imread('data/templates/btn_bar.png', cv2.IMREAD_UNCHANGED)
# btn_bar is 340x77, 3ch. Scale to fit width 300 (15px margin each side)
BTN_W = 300
BTN_H = int(77 * BTN_W / 340)
btn_bar_small = cv2.resize(btn_bar, (BTN_W, BTN_H), interpolation=cv2.INTER_AREA)
BTN_X = (TARGET_W - BTN_W) // 2  # 15
BTN_Y = CONTENT_TOP + 230  # after minimap area
print(f"Buttons: {BTN_W}x{BTN_H} at ({BTN_X},{BTN_Y})")
overlay_with_alpha(bg, btn_bar_small, BTN_X, BTN_Y)

# === 4. Run/Stop buttons from asset_bottom ===
bottom = cv2.imread('asset_bottom.png', cv2.IMREAD_UNCHANGED)
# Run: x=0-533, y=0-165
run_btn = bottom[0:166, 0:534]
# Stop: x=585-1118, y=0-165
stop_btn = bottom[0:166, 585:1119]

RUN_W = 140
RUN_H = int(166 * RUN_W / 534)  # ~43
run_small = cv2.resize(run_btn, (RUN_W, RUN_H), interpolation=cv2.INTER_AREA)
stop_small = cv2.resize(stop_btn, (RUN_W, RUN_H), interpolation=cv2.INTER_AREA)

RUN_X = 15
RUN_Y = BTN_Y + BTN_H + 12
STOP_X = TARGET_W - RUN_W - 15
STOP_Y = RUN_Y
print(f"Run: {RUN_W}x{RUN_H} at ({RUN_X},{RUN_Y})")
print(f"Stop: {RUN_W}x{RUN_H} at ({STOP_X},{STOP_Y})")
overlay_with_alpha(bg, run_small, RUN_X, RUN_Y)
overlay_with_alpha(bg, stop_small, STOP_X, STOP_Y)

# === 5. Sub-tabs from asset_bottom ===
# 人物特征: x=26-247, y=203-291
char_tab = bottom[203:292, 26:248]
# 特征清除: x=263-489, y=203-291
clear_tab = bottom[203:292, 263:490]
# 怪物数据素材（后面按高度等比缩放裁切）
monster_tab_raw = cv2.imread('asset_1008899.png', cv2.IMREAD_UNCHANGED)

SUBTAB_W = 92
SUBTAB_H = int(89 * SUBTAB_W / 222)  # ~37
char_small = cv2.resize(char_tab, (SUBTAB_W, SUBTAB_H), interpolation=cv2.INTER_AREA)
clear_small = cv2.resize(clear_tab, (SUBTAB_W, SUBTAB_H), interpolation=cv2.INTER_AREA)
# 怪物数据：按高度等比缩放后裁切左边（不拉伸变形）
mh, mw = monster_tab_raw.shape[:2]
scale = SUBTAB_H / mh
monster_scaled = cv2.resize(monster_tab_raw, (int(mw * scale), SUBTAB_H), interpolation=cv2.INTER_AREA)
monster_small = monster_scaled[:, :SUBTAB_W]

SUBTAB_Y = RUN_Y + RUN_H + 12
SUBTAB_X1 = 15
SUBTAB_X2 = SUBTAB_X1 + SUBTAB_W + 8
SUBTAB_X3 = SUBTAB_X2 + SUBTAB_W + 8
print(f"Subtabs at y={SUBTAB_Y}: x={SUBTAB_X1},{SUBTAB_X2},{SUBTAB_X3}")
overlay_with_alpha(bg, char_small, SUBTAB_X1, SUBTAB_Y)
overlay_with_alpha(bg, clear_small, SUBTAB_X2, SUBTAB_Y)
overlay_with_alpha(bg, monster_small, SUBTAB_X3, SUBTAB_Y)

# === 6. Window bind button (asset_588955.png - orange with circle slot) ===
winbind_btn = cv2.imread('asset_588955.png', cv2.IMREAD_UNCHANGED)
WB_W = 100
WB_H = int(133 * WB_W / 397)  # ~34
wb_small = cv2.resize(winbind_btn, (WB_W, WB_H), interpolation=cv2.INTER_AREA)
WB_X = 15
WB_Y = SUBTAB_Y + SUBTAB_H + 8
print(f"Window bind: {WB_W}x{WB_H} at ({WB_X},{WB_Y})")
overlay_with_alpha(bg, wb_small, WB_X, WB_Y)

# Crosshair drawn dynamically at right circle area of window bind button
# Circle center approx at 78% of button width
CH_HOME_X = WB_X + int(WB_W * 0.70)  # 左移居中
CH_HOME_Y = WB_Y + WB_H // 2

# === 7. Bound window dropdown button (asset_999.png) ===
bound_btn = cv2.imread('asset_999.png', cv2.IMREAD_UNCHANGED)
BW_W = 100
BW_H = int(75 * BW_W / 320)  # ~23
bw_small = cv2.resize(bound_btn, (BW_W, BW_H), interpolation=cv2.INTER_AREA)
BW_X = 15
BW_Y = WB_Y + WB_H + 6
print(f"Bound window btn: {BW_W}x{BW_H} at ({BW_X},{BW_Y})")
overlay_with_alpha(bg, bw_small, BW_X, BW_Y)

# === 8. Log box from asset_bottom ===
log_box = bottom[340:616, 375:1119]
LOG_W = 195
LOG_H = 80
log_small = cv2.resize(log_box, (LOG_W, LOG_H), interpolation=cv2.INTER_AREA)
LOG_X = TARGET_W - LOG_W - 12
LOG_Y = WB_Y
print(f"Log box: {LOG_W}x{LOG_H} at ({LOG_X},{LOG_Y})")
overlay_with_alpha(bg, log_small, LOG_X, LOG_Y)

# === 8. Save ===
cv2.imwrite('ui_route.png', bg)
print(f"\nSaved ui_route.png: {bg.shape[1]}x{bg.shape[0]}")

# Print coordinate summary for code update
print("\n=== COORDINATES FOR CODE ===")
print(f"UI_W = {TARGET_W}")
print(f"UI_H = {TARGET_H}")
print(f"# Minimap area (for dynamic overlay)")
print(f"UI_MAP_X = 15")
print(f"UI_MAP_Y = {CONTENT_TOP + 5}")
print(f"UI_MAP_W = {TARGET_W - 30}")
print(f"UI_MAP_H = {BTN_Y - CONTENT_TOP - 15}")
print(f"# Buttons row1+2")
print(f"UI_BTN_START_X = {BTN_X}")
print(f"UI_BTN_COL_W = {BTN_W // 4}")
print(f"UI_BTN_GAP = 0")
print(f"UI_BTN_ROW1_Y = {BTN_Y}")
print(f"UI_BTN_ROW2_Y = {BTN_Y + BTN_H // 2}")
print(f"UI_BTN_H = {BTN_H // 2}")
print(f"# Run/Stop")
print(f"UI_RUN_X = {RUN_X}, UI_RUN_Y = {RUN_Y}, UI_RUN_W = {RUN_W}, UI_RUN_H = {RUN_H}")
print(f"UI_STOP_X = {STOP_X}, UI_STOP_Y = {STOP_Y}, UI_STOP_W = {RUN_W}, UI_STOP_H = {RUN_H}")
print(f"# Subtabs")
print(f"UI_SUBTAB_Y = {SUBTAB_Y}, UI_SUBTAB_H = {SUBTAB_H}, UI_SUBTAB_W = {SUBTAB_W}")
print(f"# Log")
print(f"UI_LOG_X = {LOG_X}, UI_LOG_Y = {LOG_Y}, UI_LOG_W = {LOG_W}, UI_LOG_H = {LOG_H}")
print(f"# Window bind")
print(f"UI_WINBIND_X = {WB_X}, UI_WINBIND_Y = {WB_Y}, UI_WINBIND_W = {WB_W}, UI_WINBIND_H = {WB_H}")
print(f"# Bound window dropdown")
print(f"UI_BOUND_X = {BW_X}, UI_BOUND_Y = {BW_Y}, UI_BOUND_W = {BW_W}, UI_BOUND_H = {BW_H}")
print(f"# Crosshair home position")
print(f"CH_HOME = ({CH_HOME_X}, {CH_HOME_Y})")
