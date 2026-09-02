with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 恢复UI_MAP_W/H为原值
old1 = '''UI_MAP_W = 398  # 显示宽度减5px，隐藏右边灰色边框
UI_MAP_H = 264  # 显示高度减15px，隐藏底部灰色边框'''
new1 = '''UI_MAP_W = 403  # 小地图显示宽度
UI_MAP_H = 279  # 小地图显示高度'''
if old1 in content:
    content = content.replace(old1, new1, 1)
    print('已恢复UI尺寸')
else:
    print('未找到UI尺寸定义')

# 修改合成代码：先裁剪小地图内容右边和底部的灰色边框，再缩放
old2 = '''        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)  # 缩放到UI显示尺寸
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled  # 合成到背景'''

new2 = '''        # === 缩放到UI尺寸并合成到背景 ===
        # 先裁剪小地图内容右边5px和底部15px对应的原始分辨率部分（去掉灰色边框）
        crop_r = int(5 * FIXED_W / UI_MAP_W)  # 右边5px对应原始分辨率约4px
        crop_b = int(15 * MAP_H / UI_MAP_H)    # 底部15px对应原始分辨率约13px
        map_trimmed = map_display[:MAP_H-crop_b, :FIXED_W-crop_r]  # 裁剪右边和底部
        map_scaled = cv2.resize(map_trimmed, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)  # 缩放到UI显示尺寸
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled  # 合成到背景'''

if old2 in content:
    content = content.replace(old2, new2, 1)
    print('已修改合成代码')
else:
    print('未找到合成代码')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
