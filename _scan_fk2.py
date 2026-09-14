# -*- coding: utf-8 -*-
# 临时：深挖 FK/MSC Core.dll 的视觉定位手段与中文功能词，只读
import os, re
D = r"C:\Users\wenwen\Desktop\FK_Taiwan_0911\MSC_Taiwan"
core = open(os.path.join(D,"Core.dll"),"rb").read()
cli  = open(os.path.join(D,"Client.exe"),"rb").read()

def astrs(d): return [m.group(0) for m in re.finditer(rb"[\x20-\x7e]{4,}", d)]
def cn_utf8(d):
    out=[]
    for m in re.finditer(rb"(?:[\xe3-\xe9][\x80-\xbf]{2}){2,}", d):
        try: out.append(m.group(0).decode("utf-8"))
        except: pass
    return out

# 1) 视觉/定位/检测 英文上下文
engpat = re.compile(r"name|title|medal|player|char|self|pos|center|template|match|similar|color|hsv|"
                    r"find|capture|screen|dxgi|duplic|desktop|onnx|session|detect|bbox|label|model|yolo|"
                    r"conf|iou|nms|anchor|infer|runtime|blob|resize|gray|threshold|contour|feature|"
                    r"minimap|hp|mp|monster|mob|target|lock|direction|foothold|platform|ladder|jump", re.I)
print("===== Core.dll 英文关键串（去重前80）=====")
seen=set(); c=0
for s in astrs(core):
    t=s.decode(errors="replace")
    if engpat.search(t) and 4<len(t)<90 and t not in seen:
        # 过滤掉太随机的（要求含元音或下划线/路径特征）
        if re.search(r"[a-z]{3}", t):
            seen.add(t); print("  ",t); c+=1
            if c>=80: break

# 2) 中文功能词
print("\n===== Core.dll 中文串（含定位/识别相关）=====")
cnkw = re.compile(r"角色|人物|名|血|怪|图|色|坐标|定位|中心|模板|相似|匹配|平台|梯|跳|方向|锁|"
                  r"识别|截|屏|检测|模型|标签|勋|脚|基点|范围|层|路线|寻路|锚|框|血条|蓝条")
seen=set(); c=0
for t in cn_utf8(core):
    if cnkw.search(t) and t not in seen and len(t)<40:
        seen.add(t); print("  ",t); c+=1
        if c>=120: break

# 3) 内嵌资源魔数
print("\n===== 内嵌资源魔数计数 =====")
for nm,mg in [("PNG",rb"\x89PNG\r\n\x1a\n"),("JPG",b"\xff\xd8\xff"),("ONNX?proto",b"onnx"),
              ("ZIP/PK",b"PK\x03\x04"),("RCC qrc",b"qrc:/"),("DDS",b"DDS "),("RIFF",b"RIFF")]:
    print("  Core %-12s %d   Client %d"%(nm, core.count(mg), cli.count(mg)))

# 4) AOB 上下文
print("\n===== AOB 上下文 =====")
for m in list(re.finditer(rb"AOB", core))[:7]:
    i=m.start(); print("  ", core[max(0,i-40):i+40].decode(errors='replace').replace("\n"," "))
