lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找_capture_ladder_feature函数
for i in range(len(lines)):
    if 'def _capture_ladder_feature(self):' in lines[i]:
        print('找到位置:', i+1)
        # 找函数结束（下一个def）
        end = i+1
        while end < len(lines) and not lines[end].strip().startswith('def '):
            end += 1
        print('函数结束于:', end)
        
        # 新的函数内容
        new_func = '''    def _capture_ladder_feature(self):
        """框选梯子/绳索竖条样式存为特征(只用其X)，同时记录爬梯时间，保存到梯子特征里"""
        if self.hwnd is None:
            self._add_log("请先绑定游戏窗口")
            return
        if len(self._ladder_templates) >= LADDER_TPL_MAX:
            self._ladder_templates.pop(0)
            self._add_log("梯子模板已满，替换最早一套")
        self._update_window_rect()
        frame = self._capture_window()
        if frame is None:
            self._add_log("截图失败，请重试")
            return
        print("[梯子特征] 弹出框选：拖拽框住整根绳索/梯子竖条，回车确认，ESC取消")
        x, y, w, h = self._interactive_box_select("Select Ladder", frame)
        if w <= 0 or h <= 0:
            print("[梯子特征] 取消框选")
            return
        cap = frame[y:y + h, x:x + w].copy()
        ids = [t["id"] for t in self._ladder_templates]
        new_id = (max(ids) + 1) if ids else 0
        ch, cw = cap.shape[:2]
        
        # 【用户要求】记录爬梯时间：框选后，提示用户手动爬梯子到顶，按回车结束
        import tkinter.messagebox as mb
        mb.showinfo("录梯子时间", "现在请手动爬这把梯子到顶，爬到顶后点确定结束")
        t_start = time.time()
        mb.showinfo("录梯子时间", "现在开始计时，请爬梯子到顶")
        t_end = time.time()
        climb_ms = int((t_end - t_start) * 1000)
        print("[梯子特征#%d] 爬梯时间=%dms" % (new_id, climb_ms))
        self._add_log("梯子特征#%d 爬梯时间=%dms(超时兜底=%dms)" % (new_id, climb_ms, climb_ms + 2000))
        
        self._ladder_templates.append({"id": new_id, "img": cap, "width": cw, "height": ch, "climb_ms": climb_ms})
        self._save_ladder_templates(self.current_route)
        self._add_log("梯子特征#%d已保存(%dx%d) 共%d套，已存入方案%d" % (
            new_id, cw, ch, len(self._ladder_templates), self.current_route))
        print("[梯子特征] #%d 已存 %dx%d，共%d套" % (new_id, cw, ch, len(self._ladder_templates)))
'''
        lines[i:end] = [new_func]
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
