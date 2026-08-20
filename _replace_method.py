import re

with open('test_minimap_route.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_method = '''    def _detect_minimap(self):
        """自动检测小地图和地图内容区域（扫描线法，适应不同大小）"""
        self._update_window_rect()
        frame = self._capture_window()

        roi_top = 15
        roi = frame[roi_top:roi_top + 230, 0:220].copy()
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # 1. 灰白色检测找外层大框
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        border_mask = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 50, 255]))
        border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(border_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        outer = None
        max_a = 0
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            a = cv2.contourArea(c)
            if cw > 80 and ch > 100 and a > max_a:
                max_a = a
                outer = (x, y, cw, ch)

        ox, oy, ow, oh = outer if outer else (5, 0, 200, 220)
        self.minimap_rect = {'left': ox, 'top': roi_top + oy, 'width': ow, 'height': oh}

        # 2. 扫描线法找内层地图边框
        inner = gray[oy:oy + oh, ox:ox + ow]

        def find_hborder(img, sy, ey, step, thresh=130, ratio=0.75):
            for y in range(sy, ey, step):
                if 0 <= y < img.shape[0]:
                    if np.sum(img[y, :] > thresh) > ow * ratio:
                        return y
            return None

        def find_vborder(img, sx, ex, step, y_range, thresh=130, ratio=0.45):
            y1, y2 = y_range
            for x in range(sx, ex, step):
                if 0 <= x < img.shape[1]:
                    if np.sum(img[y1:y2, x] > thresh) > (y2 - y1) * ratio:
                        return x
            return None

        top_y = find_hborder(inner, int(oh * 0.35), int(oh * 0.6), 1)
        bottom_y = find_hborder(inner, oh - 3, int(oh * 0.5), -1)

        if top_y and bottom_y and bottom_y > top_y:
            left_x = find_vborder(inner, 3, ow // 2, 1, (top_y, bottom_y))
            right_x = find_vborder(inner, ow - 4, ow // 2, -1, (top_y, bottom_y))
        else:
            top_y = top_y or int(oh * 0.38)
            bottom_y = bottom_y or oh - 3
            left_x = 3
            right_x = ow - 3

        # 3. 地图内容区域 = 边框内部
        pad = 2
        self.map_area_rect = {
            'left': ox + left_x + pad,
            'top': roi_top + oy + top_y + pad,
            'width': right_x - left_x - pad * 2,
            'height': bottom_y - top_y - pad * 2
        }

        print(f'外层大框: ({ox},{oy}) {ow}x{oh}')
        print(f'地图边框: top={top_y} bottom={bottom_y} left={left_x} right={right_x}')
        print(f'地图内容区: {self.map_area_rect["width"]}x{self.map_area_rect["height"]}')

        self._save_region()

'''

pattern = r'    def _detect_minimap\(self\):.*?(?=\n    def )'
content = re.sub(pattern, new_method, content, flags=re.DOTALL)

with open('test_minimap_route.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('方法替换成功')
