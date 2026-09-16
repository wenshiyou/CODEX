# -*- coding: utf-8 -*-
# 等价性强校验：旧版_move_to状态块 vs 新版_climb_state_machine状态块，必须逐行相同
import subprocess, io
old = subprocess.run(['git','show','99e1955:maple_route_ui.py'],capture_output=True,text=True,encoding='utf-8').stdout.splitlines()
new = io.open('maple_route_ui.py',encoding='utf-8').read().splitlines()

def extract_state_block(lines, method_name):
    mi=[i for i,l in enumerate(lines) if l.lstrip().startswith('def %s('%method_name)][0]
    di=[i for i in range(mi,len(lines)) if lines[i].strip()=='if self._climb_state == "descend":'][0]
    if method_name=='_climb_state_machine':
        # 新方法:状态块到方法尾"        return True"(8空格)为止(不含)
        ni=[i for i in range(di,len(lines)) if lines[i]=='        return True'][0]
    else:
        ni=[i for i in range(di,len(lines)) if lines[i].lstrip().startswith('# === 正常移动')][0]
    return lines[di:ni]

ob=extract_state_block(old,'_move_to')
nb_full=extract_state_block(new,'_climb_state_machine')
# 新旧块都从 descend 行起、到"正常移动"注释前,区间天然相同,直接逐行比
nb=nb_full
print('旧状态块行数',len(ob),'新状态块行数',len(nb))
if ob==nb:
    print('EQUIVALENT_OK: 状态分支逐行完全一致,抽取零逻辑改动')
else:
    print('DIFF_FOUND!!')
    import difflib
    for l in difflib.unified_diff(ob,nb,lineterm='',n=1):
        print(l[:120])
