import io

path = r"C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py"
with io.open(path, "r", encoding="utf-8") as f:
    content = f.read()

# === 改动1：去掉绿框EMA平滑，直接用当前帧坐标，加快反应 ===
old1 = """        sx = int(offset_x * scale_x)
        sy = int(offset_y * scale_y)
        # EMA平滑：绿框坐标滤波，当前帧占60%，上一帧占40%（响应更快，轻微移动能跟上，同时减少放大后的抖动）
        _last_lock = getattr(self, '_last_smooth_lock', None)
        if _last_lock is not None:
            sx = int(sx * 0.6 + _last_lock[0] * 0.4)
            sy = int(sy * 0.6 + _last_lock[1] * 0.4)
        self._last_smooth_lock = (sx, sy)"""

new1 = """        sx = int(offset_x * scale_x)
        sy = int(offset_y * scale_y)
        # 去掉EMA平滑：直接用当前帧坐标，反应更快不延迟（用户要求跟手，抖动可接受）"""

if old1 in content:
    content = content.replace(old1, new1)
    print("改动1：已去掉绿框EMA平滑")
else:
    print("改动1：未找到原文")

# === 改动2：三点检测内缩从3改成8，缩小实际检测范围，更精确 ===
old2 = """            # 内缩3像素：排除蒙板自己画在ROI边缘的检测框线，否则框线红/绿变色会被帧差捕捉，形成自激振荡误判
            _PAD = 3"""

new2 = """            # 内缩8像素：缩小实际检测范围，排除框线和边缘动态内容，背景检测更精确
            _PAD = 8"""

if old2 in content:
    content = content.replace(old2, new2)
    print("改动2：三点检测内缩从3改成8")
else:
    print("改动2：未找到原文")

with io.open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("全部改动完成")
