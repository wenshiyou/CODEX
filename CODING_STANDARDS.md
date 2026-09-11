# 代码规范

## 注释要求
1. **每一行代码后面都要添加一行注释**，说明这行代码的作用
2. 方法/函数开头要有文档字符串（docstring），说明功能、参数、返回值
3. 复杂逻辑处要有注释，说明设计思路
4. 修改代码时，要更新相关注释

## 示例
```python
def _detect_minimap(self, debug=True):
    """三特征点定位：左=小地图文字左，右=大地图文字右，下=底部蓝色线模板匹配
    debug=False 时为每帧轻量模式，不写调试图"""
    if self.hwnd is None:  # 窗口句柄为空则跳过
        return  # 直接返回
    self._update_window_rect()  # 更新窗口矩形坐标
    frame = self._capture_window()  # 截取窗口画面
    fh, fw = frame.shape[:2]  # 获取画面高度和宽度
```

## 三点判定边界法说明
- **左边界**：小地图文字左边缘（mini_x）
- **右边界**：大地图文字右边缘（big_x + bw）
- **上边界**：小地图文字下边缘（mini_y + mh）
- **下边界**：底部模板匹配位置（模板顶部，向上移避免灰色边框）
- **截取区域**：从上边界向下移 TITLE_PAD=45px 开始，到下边界结束
- **minimap_rect**：包含标题栏的完整小地图区域
- **map_area_rect**：不包含标题栏的纯地图内容区域
