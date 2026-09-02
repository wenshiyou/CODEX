with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled'''

new = '''        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)  # 缩放到UI显示尺寸
        # 裁剪底部15px和右边5px（隐藏多余部分，不影响鼠标坐标转换）
        map_cropped = map_scaled[:UI_MAP_H-15, :UI_MAP_W-5]
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H-15, UI_MAP_X:UI_MAP_X+UI_MAP_W-5] = map_cropped'''

if old in content:
    content = content.replace(old, new, 1)
    print('已修改显示区域裁剪')
else:
    print('未找到旧代码')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
