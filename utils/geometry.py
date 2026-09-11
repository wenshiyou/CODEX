"""
几何计算工具模块
"""
import math


def distance(p1, p2):
    """两点之间的欧氏距离"""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def horizontal_distance(p1, p2):
    """水平距离"""
    return abs(p1[0] - p2[0])


def vertical_distance(p1, p2):
    """垂直距离"""
    return abs(p1[1] - p2[1])


def direction(from_pos, to_pos):
    """
    判断从 from_pos 到 to_pos 的水平方向
    返回: "left" / "right" / "same"
    """
    dx = to_pos[0] - from_pos[0]
    if dx > 5:
        return "right"
    elif dx < -5:
        return "left"
    return "same"


def is_on_same_platform(y1, y2, threshold=30):
    """判断两个 y 坐标是否在同一平台（垂直差在阈值内）"""
    return abs(y1 - y2) <= threshold


def clamp(value, min_val, max_val):
    """将值限制在范围内"""
    return max(min_val, min(max_val, value))


def bbox_center(bbox):
    """
    从检测框 [x1, y1, x2, y2] 计算中心点
    """
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def bbox_width(bbox):
    return bbox[2] - bbox[0]


def bbox_height(bbox):
    return bbox[3] - bbox[1]
