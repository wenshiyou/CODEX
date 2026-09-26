# -*- coding: utf-8 -*-
# 只查最近3分钟:手动模式空打是不是锁了上层怪。聚焦战斗诊断锁定Y差/判活/cross,不看噪声。
import io, re, datetime, sys
P = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\debug.log"
WIN = int(sys.argv[1]) if len(sys.argv) > 1 else 180
now = datetime.datetime.now()
def t_of(l):
    m = re.search(r'(\d{2}):(\d{2}):(\d{2})', l)
    if not m: return None
    t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=int(m.group(3)), microsecond=0)
    if (now-t).total_seconds() > 12*3600: t += datetime.timedelta(days=1)
    return t
rows=[]
for l in io.open(P,encoding='utf-8',errors='replace'):
    t=t_of(l)
    if t is not None and 0 <= (now-t).total_seconds() <= WIN: rows.append((t,l.rstrip()))
out=[]
out.append("now=%s 最近%ds 行数=%d" % (now.strftime('%H:%M:%S'),WIN,len(rows)))
# 运行/模式切换
for t,l in rows:
    if ('运行已触发' in l) or ('F12' in l and ('停止' in l or 'F12' in l)) or ('[模式]' in l) or ('mode=' in l and '启动' in l):
        out.append("%s %s" % (t.strftime('%H:%M:%S'), l[:130]))
# 战斗诊断:算锁定Y差
diag=[]
cnt={'同台<50':0,'上层<-50':0,'下层>50':0,'无锁':0}
for t,l in rows:
    if '[战斗诊断]' in l:
        mp=re.search(r'人物=\((\d+),\s*(\d+)\)',l); ml=re.search(r'锁定=\((\d+),\s*(\d+)\)',l)
        nt=re.search(r'怪数=(\d+)',l); ht=re.search(r'has_target=(\w+)',l)
        if mp:
            py=int(mp.group(2))
            if ml:
                cy=int(ml.group(2)); dy=cy-py
                tag='同台<50' if abs(dy)<=50 else ('上层<-50' if dy<-50 else '下层>50')
                cnt[tag]+=1
                diag.append("%s py=%d 锁=(%s,%s) dy=%d [%s] 怪%s tgt=%s" % (t.strftime('%H:%M:%S'),py,ml.group(1),ml.group(2),dy,tag,nt.group(1) if nt else '?',ht.group(1) if ht else '?'))
            else:
                cnt['无锁']+=1
out.append("\n== 锁定Y差统计(战斗诊断帧) == "+str(cnt))
out.append("== 战斗诊断 最后24条 ==")
out += diag[-24:]
# 判活(空打证据)
ph=[ "%s %s"%(t.strftime('%H:%M:%S'),l[:150]) for t,l in rows if '[判活汇总]' in l]
out.append("\n== 判活汇总 最后8条 =="); out += ph[-8:]
# cross/上层/跳高/梯
cr=[ "%s %s"%(t.strftime('%H:%M:%S'),l[:140]) for t,l in rows if re.search(r'cross|slope|跳高|跨层|上层|上梯|走梯|下跳',l)]
# 空怪诊断(是否真出手)
empty=[ "%s %s"%(t.strftime('%H:%M:%S'),l[:140]) for t,l in rows if '[空怪诊断]' in l]
out.append("\n== 空怪诊断 最后15条(看已出手/伤害/血条) =="); out += empty[-15:]
# 平台边界计数
edge=[l for t,l in rows if '[平台边界]' in l]
out.append("\n== 平台边界 行数=%d, 其中回退超时=%d, 触线=%d ==" % (
    len(edge), sum('回退超时' in l for l in edge), sum('守护触线' in l for l in edge)))
out.append("\n== cross/上层/梯/跳 最后18条 =="); out += cr[-18:]
io.open(r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\_chk3.txt","w",encoding="utf-8").write("\n".join(out))
print("OK")
