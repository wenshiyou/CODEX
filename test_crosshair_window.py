# -*- coding: utf-8 -*-
"""测试：用tkinter创建透明置顶窗口，显示准星，可拖拽到屏幕任意位置"""
import tkinter as tk
import time

def test_crosshair_window():
    """测试透明置顶准星窗口"""
    root = tk.Tk()
    root.title("Crosshair Test")
    root.overrideredirect(True)  # 无边框
    root.attributes("-topmost", True)  # 置顶
    root.attributes("-transparentcolor", "white")  # 白色透明
    
    # 创建Canvas，背景白色（透明）
    canvas = tk.Canvas(root, width=100, height=100, bg="white", highlightthickness=0)
    canvas.pack()
    
    # 绘制准星（红色）
    canvas.create_oval(35, 35, 65, 65, outline="red", width=2)
    canvas.create_line(20, 50, 40, 50, fill="red", width=2)
    canvas.create_line(60, 50, 80, 50, fill="red", width=2)
    canvas.create_line(50, 20, 50, 40, fill="red", width=2)
    canvas.create_line(50, 60, 50, 80, fill="red", width=2)
    
    # 初始位置在屏幕中央
    root.geometry("+500+300")
    
    # 拖拽功能
    drag_data = {"x": 0, "y": 0}
    
    def on_press(event):
        drag_data["x"] = event.x
        drag_data["y"] = event.y
    
    def on_drag(event):
        x = root.winfo_x() + event.x - drag_data["x"]
        y = root.winfo_y() + event.y - drag_data["y"]
        root.geometry(f"+{x}+{y}")
    
    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    
    # 5秒后自动关闭
    root.after(5000, root.destroy)
    
    print("测试窗口已创建，5秒后自动关闭")
    print("请尝试拖拽准星窗口，看看能否拖到屏幕任意位置")
    
    root.mainloop()
    print("测试完成")

if __name__ == "__main__":
    test_crosshair_window()
