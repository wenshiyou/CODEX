with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 撤销小地图内容裁剪，恢复原来的合成方式
old = '''        # === 缩放到UI尺寸并合成到背景 ===
        # 先裁剪小地图内容右边5px和底部15px对应的原始分辨率部分（去掉灰色边框）
        crop_r = int(5 * FIXED_W / UI_MAP_W)  # 右边5px对应原始分辨率约4px
        crop_b = int(15 * MAP_H / UI_MAP_H)    # 底部15px对应原始分辨率约13px
        map_trimmed = map_display[:MAP_H-crop_b, :FIXED_W-crop_r]  # 裁剪右边和底部
        map_scaled = cv2.resize(map_trimmed, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)  # 缩放到UI显示尺寸
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled  # 合成到背景'''

new = '''        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)  # 缩放到UI显示尺寸
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled  # 合成到背景'''

if old in content:
    content = content.replace(old, new, 1)
    print('已撤销小地图内容裁剪')
else:
    print('未找到裁剪代码')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
