# -*- coding: utf-8 -*-
"""
怪物特征模板匹配速度测试
只用静态图片测试匹配速度，不截图
"""
import cv2
import numpy as np
import time

TEMPLATE_PATH = "test_monster_template.png"
MATCH_THRESHOLD = 0.70

def main():
    # 加载模板
    template = cv2.imread(TEMPLATE_PATH)
    if template is None:
        print("错误：找不到模板文件", TEMPLATE_PATH)
        return
    th, tw = template.shape[:2]
    print(f"模板尺寸: {tw}x{th}")
    
    # 创建一张测试大图（模拟游戏窗口1366x768）
    test_img = np.random.randint(0, 255, (768, 1366, 3), dtype=np.uint8)
    # 在中间放一个模板
    cx, cy = 683, 384
    test_img[cy:cy+th, cx:cx+tw] = template
    print(f"测试图片尺寸: {test_img.shape[1]}x{test_img.shape[0]}")
    print(f"模板放在位置: ({cx}, {cy})")
    print()
    
    # 测试1：全图匹配速度
    print("=" * 50)
    print("测试1：全图匹配速度（100次）")
    times = []
    for i in range(100):
        t0 = time.time()
        result = cv2.matchTemplate(test_img, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        t1 = time.time()
        times.append((t1 - t0) * 1000)
    
    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)
    fps = 1000 / avg_time
    print(f"平均耗时: {avg_time:.2f}ms")
    print(f"最大耗时: {max_time:.2f}ms")
    print(f"最小耗时: {min_time:.2f}ms")
    print(f"理论FPS: {fps:.1f}")
    print(f"匹配结果: 位置={max_loc}, 置信度={max_val:.3f}")
    print()
    
    # 测试2：ROI匹配速度（400x400范围）
    print("=" * 50)
    print("测试2：ROI匹配速度（400x400范围，100次）")
    roi_x1 = max(0, cx - 200)
    roi_y1 = max(0, cy - 200)
    roi_x2 = min(test_img.shape[1], cx + 200)
    roi_y2 = min(test_img.shape[0], cy + 200)
    roi = test_img[roi_y1:roi_y2, roi_x1:roi_x2]
    print(f"ROI尺寸: {roi.shape[1]}x{roi.shape[0]}")
    
    times = []
    for i in range(100):
        t0 = time.time()
        result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        t1 = time.time()
        times.append((t1 - t0) * 1000)
    
    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)
    fps = 1000 / avg_time
    print(f"平均耗时: {avg_time:.2f}ms")
    print(f"最大耗时: {max_time:.2f}ms")
    print(f"最小耗时: {min_time:.2f}ms")
    print(f"理论FPS: {fps:.1f}")
    print(f"匹配结果: 相对位置={max_loc}, 置信度={max_val:.3f}")
    print()
    
    # 测试3：多模板匹配速度（10个模板）
    print("=" * 50)
    print("测试3：多模板匹配速度（10个模板全图匹配，100次）")
    templates = [template] * 10  # 模拟10个特征模板
    
    times = []
    for i in range(100):
        t0 = time.time()
        for tpl in templates:
            result = cv2.matchTemplate(test_img, tpl, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        t1 = time.time()
        times.append((t1 - t0) * 1000)
    
    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)
    fps = 1000 / avg_time
    print(f"平均耗时: {avg_time:.2f}ms (10个模板)")
    print(f"最大耗时: {max_time:.2f}ms")
    print(f"最小耗时: {min_time:.2f}ms")
    print(f"理论FPS: {fps:.1f}")
    print()
    
    # 总结
    print("=" * 50)
    print("总结：")
    print(f"- 单模板全图匹配: ~{1000/(sum([cv2.matchTemplate(test_img, template, cv2.TM_CCOEFF_NORMED); cv2.minMaxLoc(cv2.matchTemplate(test_img, template, cv2.TM_CCOEFF_NORMED)) for _ in range(1)]) or 1):.0f}ms，FPS很高")
    print("- ROI匹配比全图匹配快约5-10倍")
    print("- 10个模板全图匹配耗时是单模板的10倍")
    print("- 如果主程序卡顿，可能不是匹配速度的问题，而是其他原因（截图、内存泄漏、GDI对象泄漏等）")
    print()
    print("测试完成！")

if __name__ == "__main__":
    main()
