# -*- coding: utf-8 -*-
path = 'maple_route_ui.py'
with open(path, encoding='utf-8-sig') as f:
    content = f.read()

# 第一处：_switch_route 中删除人物特征覆盖逻辑
old1 = '''                # 加载人物特征（base64转图片，方案只存最后一个，直接解码不用try吞异常）
                char_b64 = cd.get("char_template_b64")
                if char_b64:
                    img_bytes = base64.b64decode(char_b64)
                    img = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape
                        self._char_templates = [{"id": 0, "img": img, "width": w, "height": h, "created_at": ""}]
                        print("[切换] 方案%d 已加载人物特征 %dx%d" % (route_id, w, h))
                else:
                    self._char_templates = []'''

new1 = '''                # 人物特征是全局的（识别自己角色用，和地图方案无关），不随方案切换
                # 统一由 _load_char_templates() 从磁盘 data/char_templates/ 加载10张，切换方案时保持不动
                # 旧方案文件中的 char_template_b64 单张base64不再加载，避免覆盖磁盘的10张'''

if old1 in content:
    content = content.replace(old1, new1)
    print('第一处替换成功')
else:
    print('第一处未找到')
    idx = content.find('加载人物特征')
    if idx >= 0:
        print('附近内容:', repr(content[idx:idx+400]))

with open(path, 'w', encoding='utf-8-sig') as f:
    f.write(content)
print('文件已保存')
