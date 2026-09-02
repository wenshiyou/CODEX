with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_draw = '''    def _draw_blue_box(self, map_frame):
        """在小地图帧上绘制蓝色框（校准模式：两实点+两计算点+框+中心引导词；正常模式画框）"""
        if self._calibrating_blue_box:
            if not self._player_map_pos:
                return
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bl = self._blue_box_corners.get("bl")
            tr = self._blue_box_corners.get("tr")
            # 画两个实点（左下/右上）
            for key, val in [("bl", bl), ("tr", tr)]:
                if val is None:
                    continue
                ox, oy = val
                cx, cy = int(px + ox), int(py + oy)
                color = (0, 255, 255) if key == self._selected_corner else (0, 255, 0)
                if 0 <= cx < w and 0 <= cy < h:
                    cv2.circle(map_frame, (cx, cy), 3, color, -1)
                    cv2.putText(map_frame, self._dir_name(key), (cx + 5, cy - 3),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)
            # 两个点都齐了：自动算左上/右下角，画完整长方形
            if bl is not None and tr is not None:
                tl_pt = (int(px + bl[0]), int(py + tr[1]))
                br_pt = (int(px + tr[0]), int(py + bl[1]))
                bl_pt = (int(px + bl[0]), int(py + bl[1]))
                tr_pt = (int(px + tr[0]), int(py + tr[1]))
                pts = [tl_pt, tr_pt, br_pt, bl_pt]
                cv2.polylines(map_frame, [np.array(pts, np.int32).reshape((-1, 1, 2))], True, (0, 255, 0), 1)
                # 计算点用空心小圆标记
                for pt in [tl_pt, br_pt]:
                    if 0 <= pt[0] < w and 0 <= pt[1] < h:
                        cv2.circle(map_frame, pt, 2, (0, 255, 0), 1)
        elif self._blue_box and self._player_map_pos:
            # 正常模式：以光点为中心画蓝色框，到边贴边
            px, py = self._player_map_pos
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            r = self.map_area_rect
            box_x = int(max(0, min(px - bw // 2, r["width"] - bw)))
            box_y = int(max(0, min(py - bh // 2, r["height"] - bh)))
            cv2.rectangle(map_frame, (box_x, box_y), (box_x + bw, box_y + bh), (0, 255, 0), 1)'''

new_draw = '''    def _draw_blue_box(self, map_frame):
        """在小地图帧上绘制绿框（校准模式：半透明线+圆点；正常模式：实线+无圆点，用偏移量绘制）"""
        if self._calibrating_blue_box:
            if not self._player_map_pos:
                return
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bl = self._blue_box_corners.get("bl")
            tr = self._blue_box_corners.get("tr")
            # 新校准（两个点都没有）：中间显示提示文字
            if bl is None and tr is None:
                tip = "请点击小地图左下和右上的位置点"
                (tw, th), _ = cv2.getTextSize(tip, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.putText(map_frame, tip, (w // 2 - tw // 2, h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            # 画两个圆点（左下/右上），选中的变黄
            for key, val in [("bl", bl), ("tr", tr)]:
                if val is None:
                    continue
                ox, oy = val
                cx, cy = int(px + ox), int(py + oy)
                cx = max(0, min(cx, w - 1))
                cy = max(0, min(cy, h - 1))
                color = (0, 255, 255) if key == self._selected_corner else (0, 255, 0)
                cv2.circle(map_frame, (cx, cy), 3, color, -1)
            # 两个点都齐了：画半透明绿线长方形
            if bl is not None and tr is not None:
                tl_pt = (max(0, min(int(px + bl[0]), w - 1)), max(0, min(int(py + tr[1]), h - 1)))
                br_pt = (max(0, min(int(px + tr[0]), w - 1)), max(0, min(int(py + bl[1]), h - 1)))
                bl_pt = (max(0, min(int(px + bl[0]), w - 1)), max(0, min(int(py + bl[1]), h - 1)))
                tr_pt = (max(0, min(int(px + tr[0]), w - 1)), max(0, min(int(py + tr[1]), h - 1)))
                pts = [tl_pt, tr_pt, br_pt, bl_pt]
                # 半透明绿线：先在overlay上画，再混合
                overlay = map_frame.copy()
                cv2.polylines(overlay, [np.array(pts, np.int32).reshape((-1, 1, 2))], True, (0, 255, 0), 1)
                cv2.addWeighted(overlay, 0.4, map_frame, 0.6, 0, map_frame)
        elif self._blue_box and self._player_map_pos:
            # 正常模式：用偏移量绘制实线绿框，人物在框内任意位置（不强制中心）
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bl_ox = self._blue_box.get("bl_ox", 0)
            bl_oy = self._blue_box.get("bl_oy", 0)
            tr_ox = self._blue_box.get("tr_ox", 0)
            tr_oy = self._blue_box.get("tr_oy", 0)
            # 四个角点（基于偏移量），四边边界限制
            tl_x = max(0, min(int(px + bl_ox), w - 1))
            tl_y = max(0, min(int(py + tr_oy), h - 1))
            br_x = max(0, min(int(px + tr_ox), w - 1))
            br_y = max(0, min(int(py + bl_oy), h - 1))
            cv2.rectangle(map_frame, (tl_x, tl_y), (br_x, br_y), (0, 255, 0), 1)'''

content = content.replace(old_draw, new_draw)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
