"""全屏半透明覆盖窗口，拖拽选择屏幕区域，坐标通过 stdout JSON 输出"""
import tkinter as tk
import json
import sys


def main():
    result = [None]
    start = [None, None]
    rect_item = [None]

    root = tk.Tk()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.overrideredirect(True)
    root.geometry("%dx%d+0+0" % (sw, sh))
    root.attributes('-alpha', 0.4)
    root.attributes('-topmost', True)
    root.configure(bg='gray')
    root.config(cursor="cross")
    root.lift()

    canvas = tk.Canvas(root, bg='gray', highlightthickness=0, cursor="cross")
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_text(sw // 2, 30, text="拖拽框选小地图区域，松开确认，Esc取消",
                       fill='yellow', font=('Arial', 16, 'bold'))

    def on_press(event):
        start[0] = event.x_root
        start[1] = event.y_root
        if rect_item[0]:
            canvas.delete(rect_item[0])
        rect_item[0] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline='lime', width=3)

    def on_drag(event):
        if rect_item[0]:
            canvas.coords(rect_item[0], start[0], start[1], event.x_root, event.y_root)

    def on_release(event):
        if start[0] is None:
            return
        x1, y1 = start[0], start[1]
        x2, y2 = event.x_root, event.y_root
        if abs(x2 - x1) > 5 and abs(y2 - y1) > 5:
            result[0] = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        root.destroy()

    def on_esc(event):
        root.destroy()

    canvas.bind('<ButtonPress-1>', on_press)
    canvas.bind('<B1-Motion>', on_drag)
    canvas.bind('<ButtonRelease-1>', on_release)
    root.bind('<Escape>', on_esc)
    canvas.focus_set()
    root.mainloop()

    if result[0]:
        print(json.dumps({"x1": result[0][0], "y1": result[0][1],
                          "x2": result[0][2], "y2": result[0][3]}))
    else:
        print("null")


if __name__ == "__main__":
    main()
