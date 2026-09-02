with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

save_result_code = '''
    def _show_save_result(self, msg):
        """显示保存结果弹窗（2秒后自动关闭）"""
        win_name = "SaveResult"
        win_w, win_h = 300, 120
        cv2.namedWindow(win_name, cv2.WINDOW_AUTOSIZE)
        cv2.moveWindow(win_name, 200, 200)
        import time as _t
        start = _t.time()
        while _t.time() - start < 2.0:
            img = np.ones((win_h, win_w, 3), dtype=np.uint8) * 240
            if "success" in msg.lower() or "成功" in msg:
                cv2.rectangle(img, (0, 0), (win_w, win_h), (0, 200, 0), 3)
                color = (0, 150, 0)
            else:
                cv2.rectangle(img, (0, 0), (win_w, win_h), (0, 0, 200), 3)
                color = (0, 0, 150)
            cv2.putText(img, msg[:30], (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            cv2.putText(img, "(auto close in 2s)", (60, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 100), 1)
            cv2.imshow(win_name, img)
            if cv2.waitKey(100) & 0xFF == 27:
                break
        cv2.destroyWindow(win_name)

'''

content = content.replace('    def _show_route_manager(self):', save_result_code + '    def _show_route_manager(self):', 1)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('已插入保存结果弹窗代码')
