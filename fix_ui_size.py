with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 撤销裁剪代码，恢复原来的合成方式
old = '''        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)  # 缩放到UI显示尺寸
        # 裁剪底部15px和右边5px（隐藏多余部分，不影响鼠标坐标转换）
        map_cropped = map_scaled[:UI_MAP_H-15, :UI_MAP_W-5]
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H-15, UI_MAP_X:UI_MAP_X+UI_MAP_W-5] = map_cropped'''

new = '''        # === 缩放到UI尺寸并合成到背景 ===
        map_scaled = cv2.resize(map_display, (UI_MAP_W, UI_MAP_H), interpolation=cv2.INTER_LINEAR)  # 缩放到UI显示尺寸
        frame[UI_MAP_Y:UI_MAP_Y+UI_MAP_H, UI_MAP_X:UI_MAP_X+UI_MAP_W] = map_scaled  # 合成到背景'''

if old in content:
    content = content.replace(old, new, 1)
    print('已撤销裁剪代码')
else:
    print('未找到裁剪代码')

# 修改UI显示区域尺寸：右边减5px，底部减15px
old2 = 'UI_MAP_W = 403\nUI_MAP_H = 279'
new2 = 'UI_MAP_W = 398  # 显示宽度减5px，隐藏右边灰色边框\nUI_MAP_H = 264  # 显示高度减15px，隐藏底部灰色边框'
if old2 in content:
    content = content.replace(old2, new2, 1)
    print('已修改UI显示区域尺寸')
else:
    print('未找到UI尺寸定义')

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
