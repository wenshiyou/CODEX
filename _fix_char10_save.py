# -*- coding: utf-8 -*-
path = 'maple_route_ui.py'
with open(path, encoding='utf-8-sig') as f:
    content = f.read()

old2 = '''            # 人物特征转base64（只保留最后一次）
            char_b64 = None
            if self._char_templates:
                tpl = self._char_templates[-1]  # 方案保存最后一个[0]
                ok, buf = cv2.imencode(".png", tpl["img"])
                if ok:
                    char_b64 = base64.b64encode(buf.tobytes()).decode("ascii")'''

new2 = '''            # 人物特征转base64（仅兼容旧方案备份，不再作为加载来源）
            # 权威存储是磁盘 data/char_templates/char_<id>.png（10张滚动），启动时由_load_char_templates加载
            # 此处只存最后1张到方案文件，供旧版本兼容读取，新版本切换方案时不再从此字段加载
            char_b64 = None
            if self._char_templates:
                tpl = self._char_templates[-1]
                ok, buf = cv2.imencode(".png", tpl["img"])
                if ok:
                    char_b64 = base64.b64encode(buf.tobytes()).decode("ascii")'''

if old2 in content:
    content = content.replace(old2, new2)
    print('第二处替换成功')
else:
    print('第二处未找到')
    idx = content.find('人物特征转base64')
    if idx >= 0:
        print('附近内容:', repr(content[idx:idx+300]))

with open(path, 'w', encoding='utf-8-sig') as f:
    f.write(content)
print('文件已保存')
