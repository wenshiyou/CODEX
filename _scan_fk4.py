# -*- coding: utf-8 -*-
# 临时：从VMP壳的.rsrc资源里提取中文菜单/设置项，只读
import os, re
D = r"C:\Users\wenwen\Desktop\FK_Taiwan_0911\MSC_Taiwan"
def load(n): return open(os.path.join(D,n),"rb").read()

def utf16_cn(d):
    out=[]
    # UTF-16LE 中文：低字节任意，高字节 0x4e-0x9f；连续>=2个汉字
    for m in re.finditer(rb"(?:[\x00-\xff][\x4e-\x9f]){2,}", d):
        try:
            t=m.group(0).decode("utf-16-le")
            if re.search(r"[\u4e00-\u9fff]{2,}", t): out.append(t)
        except: pass
    return out

def gbk_cn(d):
    out=[]
    for m in re.finditer(rb"(?:[\xb0-\xf7][\xa0-\xfe]){2,}", d):
        try:
            t=m.group(0).decode("gbk")
            if re.search(r"[\u4e00-\u9fff]{2,}", t): out.append(t)
        except: pass
    return out

kw=re.compile(r"定位|角色|人物|名|勋|血|怪|识别|截|图|色|坐标|中心|模板|相似|匹配|平台|梯|跳|方向|锁|"
              r"检测|模型|标签|脚|基点|范围|层|路线|寻路|锚|框|条|设置|功能|攻击| buff|喝药|测谎|登录|启动|挂机")
for n in ["Client.exe","Core.dll"]:
    d=load(n)
    print("\n########## %s ##########"%n)
    s=set()
    for t in utf16_cn(d)+gbk_cn(d):
        t=t.strip()
        if 2<=len(t)<=30 and kw.search(t) and t not in s:
            s.add(t)
    for t in sorted(s): print("  ",t)
    print("  (matched %d)"%len(s))
