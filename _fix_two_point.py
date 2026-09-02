import io

path = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with io.open(path, 'r', encoding='utf-8') as f:
    src = f.read()

# 找到函数开始和结束
start_marker = '    def _calibrate_blue_box_on_minimap(self):'
end_marker = '    def _get_minimap_display_info(self):'

start_idx = src.find(start_marker)
end_idx = src.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print('MARKER NOT FOUND')
    print('start:', start_idx, 'end:', end_idx)
else:
    new_func = '''    def _calibrate_blue_box_on_minimap(self):
        """蓝色框校准模式（两点定长方形：左下角+右上角）
        操作：
        - 鼠标左键：在小地图上点角点（左下/右上，重叠区域无效）
        - 方向键：微调选中的角点（1px），Shift+方向键=10px
        - Tab：切换选中的角点（左下<->右上）
        - S：保存蓝框大小到 blue_box_config.json
        - ESC：退出校准（不保存）
        原理：两点定长方形，左上=(左下x,右上y)，右下=(右上x,左下y)
        """
        if self._minimap_display is None:
            self._add_log("小地图未显示，无法校准")
            print("[蓝框校准] 小地图未显示")
            return

        print("[蓝框校准] 进入校准模式（两点：左下+右上）")
        self._add_log("蓝框校准：点左下角+右上角定长方形，Tab切换，方向键微调，S保存，ESC退出")

        # 两个角点：左下、右上（小地图蒙板坐标）
        cal_points = {
            "left_bottom": None,   # 左下角
            "right_top": None,     # 右上角
        }
        selected_corner = "left_bottom"  # 当前选中的角点（用于方向键微调）

        clock = pygame.time.Clock()
        running = True

        while running:
            clock.tick(30)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        print("[蓝框校准] ESC退出（不保存）")
                        self._add_log("蓝框校准：已退出（未保存）")
                        running = False
                    elif event.key == pygame.K_s:
                        # 保存蓝框大小
                        if cal_points["left_bottom"] and cal_points["right_top"]:
                            lb = cal_points["left_bottom"]
                            rt = cal_points["right_top"]
                            bw = rt[0] - lb[0]
                            bh = lb[1] - rt[1]
                            if bw > 10 and bh > 10:
                                self._blue_box_size = (int(bw), int(bh))
                                self._save_blue_box_config()
                                print("[蓝框校准] 已保存: 宽=%d 高=%d" % (bw, bh))
                                self._add_log("蓝框校准已保存：%dx%d" % (bw, bh))
                                running = False
                            else:
                                self._add_log("蓝框太小（宽高需>10），请重新点")
                        else:
                            self._add_log("请先点左下角和右上角")
                    elif event.key == pygame.K_TAB:
                        # 切换选中的角点
                        if selected_corner == "left_bottom":
                            selected_corner = "right_top"
                        else:
                            selected_corner = "left_bottom"
                        print("[蓝框校准] 选中角点:", selected_corner)
                    elif event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
                        # 微调选中的角点
                        if cal_points[selected_corner] is not None:
                            step = 10 if (event.mod & pygame.KMOD_SHIFT) else 1
                            cx, cy = cal_points[selected_corner]
                            if event.key == pygame.K_LEFT:
                                cx -= step
                            elif event.key == pygame.K_RIGHT:
                                cx += step
                            elif event.key == pygame.K_UP:
                                cy -= step
                            elif event.key == pygame.K_DOWN:
                                cy += step
                            cal_points[selected_corner] = (cx, cy)
                            print("[蓝框校准] 微调%s: (%d,%d)" % (selected_corner, cx, cy))
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # 鼠标左键点角点
                    mx, my = pygame.mouse.get_pos()
                    # 转换为小地图蒙板坐标
                    mm = self._minimap_display
                    if mm["x"] <= mx < mm["x"] + mm["w"] and mm["y"] <= my < mm["y"] + mm["h"]:
                        # 找到光点位置（蒙板坐标）
                        dot_pos = self._player_map_pos
                        if dot_pos is None:
                            self._add_log("未检测到光点，无法判断方向")
                            continue
                        dot_x, dot_y = dot_pos
                        # 点击位置转蒙板坐标
                        click_x = mx - mm["x"]
                        click_y = my - mm["y"]
                        dx = click_x - dot_x
                        dy = click_y - dot_y

                        # 方向判断：左下（dx<0或dy>0），右上（dx>0或dy<0）
                        is_left_bottom = (dx < 0) or (dy > 0)
                        is_right_top = (dx > 0) or (dy < 0)

                        if is_left_bottom and is_right_top:
                            # 重叠区域（左上/右下），无效
                            self._add_log("点在左上/右下重叠区域，无效，请重试")
                            print("[蓝框校准] 重叠区域无效: dx=%d dy=%d" % (dx, dy))
                        elif is_left_bottom:
                            cal_points["left_bottom"] = (click_x, click_y)
                            selected_corner = "left_bottom"
                            print("[蓝框校准] 左下角:", click_x, click_y)
                            self._add_log("左下角已记录（%d,%d）" % (click_x, click_y))
                        elif is_right_top:
                            cal_points["right_top"] = (click_x, click_y)
                            selected_corner = "right_top"
                            print("[蓝框校准] 右上角:", click_x, click_y)
                            self._add_log("右上角已记录（%d,%d）" % (click_x, click_y))

            # 绘制校准画面
            self._calibrate_draw_frame(cal_points, selected_corner)

        pygame.display.quit()
        pygame.display.init()
        print("[蓝框校准] 校准模式结束")

    def _calibrate_draw_frame(self, cal_points, selected_corner):
        """绘制校准画面（小地图+角点+蓝框+提示文字）"""
        mm = self._minimap_display
        if mm is None:
            return

        self._screen.fill((20, 20, 20))

        # 绘制小地图蒙板
        mask_surf = pygame.surfarray.make_surface(mm["mask"].swapaxes(0, 1))
        self._screen.blit(mask_surf, (mm["x"], mm["y"]))

        # 绘制光点
        dot_pos = self._player_map_pos
        if dot_pos is not None:
            dx, dy = dot_pos
            pygame.draw.circle(self._screen, (255, 255, 0), (mm["x"] + dx, mm["y"] + dy), 5, 2)

        # 计算另外两个角点
        lb = cal_points["left_bottom"]
        rt = cal_points["right_top"]
        lt = None  # 左上角（计算点）
        rb = None  # 右下角（计算点）
        if lb and rt:
            lt = (lb[0], rt[1])
            rb = (rt[0], lb[1])

        # 绘制蓝框（四个点连线）
        if lb and rt and lt and rb:
            box_pts = [
                (mm["x"] + lt[0], mm["y"] + lt[1]),
                (mm["x"] + rt[0], mm["y"] + rt[1]),
                (mm["x"] + rb[0], mm["y"] + rb[1]),
                (mm["x"] + lb[0], mm["y"] + lb[1]),
            ]
            pygame.draw.lines(self._screen, (0, 180, 255), True, box_pts, 2)
            # 蓝框半透明填充
            box_surf = pygame.Surface((rt[0] - lb[0], lb[1] - rt[1]), pygame.SRCALPHA)
            box_surf.fill((0, 180, 255, 40))
            self._screen.blit(box_surf, (mm["x"] + lt[0], mm["y"] + lt[1]))

        # 绘制角点
        corner_labels = {
            "left_bottom": ("左下", (0, 255, 0)),
            "right_top": ("右上", (0, 255, 0)),
        }
        for key, (label, color) in corner_labels.items():
            pt = cal_points[key]
            if pt is not None:
                px, py = mm["x"] + pt[0], mm["y"] + pt[1]
                radius = 8 if key == selected_corner else 6
                pygame.draw.circle(self._screen, color, (px, py), radius, 2)
                # 角点标签
                font = pygame.font.SysFont("microsoftyaheimicrosoftyaheiui", 16)
                txt = font.render(label, True, color)
                self._screen.blit(txt, (px + 10, py - 8))

        # 绘制计算点（左上、右下，灰色虚线圆）
        for pt, label in [(lt, "左上"), (rb, "右下")]:
            if pt is not None:
                px, py = mm["x"] + pt[0], mm["y"] + pt[1]
                pygame.draw.circle(self._screen, (150, 150, 150), (px, py), 5, 1)
                font = pygame.font.SysFont("microsoftyaheimicrosoftyaheiui", 14)
                txt = font.render(label + "(算)", True, (150, 150, 150))
                self._screen.blit(txt, (px + 8, py - 6))

        # 提示文字
        font = pygame.font.SysFont("microsoftyaheimicrosoftyaheiui", 18)
        tips = [
            "蓝框校准（两点定长方形）",
            "鼠标左键：点左下角/右上角（左上/右下区域无效）",
            "Tab：切换选中角点 | 方向键：微调1px | Shift+方向键：10px",
            "S：保存 | ESC：退出",
        ]
        lb_status = "已点" if lb else "未点"
        rt_status = "已点" if rt else "未点"
        tips.append("左下角：%s | 右上角：%s | 当前选中：%s" % (
            lb_status, rt_status,
            "左下" if selected_corner == "left_bottom" else "右上"
        ))
        if lb and rt:
            bw = rt[0] - lb[0]
            bh = lb[1] - rt[1]
            tips.append("蓝框大小：%d x %d（按S保存）" % (bw, bh))

        for i, tip in enumerate(tips):
            txt = font.render(tip, True, (255, 255, 255))
            self._screen.blit(txt, (10, 10 + i * 24))

        pygame.display.flip()

'''
    src = src[:start_idx] + new_func + src[end_idx:]
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print('TWO-POINT CALIBRATION DONE')
