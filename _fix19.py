lines = open('maple_route_ui.py', 'r', encoding='utf-8').readlines()

# 找解绑梯子的代码
for i in range(len(lines)):
    if "if _dl['state'] == 'cast' and getattr(self, '_locked_ladder', None) is not None:" in lines[i] and '改打技能范围内近身怪' in lines[i+1]:
        print('找到位置:', i+1)
        # 注释掉
        lines[i] = '                # 用户2026-09-16定稿:选了梯子就不解绑了,一心上梯子,有怪也不打,上到顶再打怪\n'
        lines.insert(i+1, '                # if _dl[\'state\'] == \'cast\' and getattr(self, \'_locked_ladder\', None) is not None:\n')
        lines.insert(i+2, '                #     self._clear_locked_ladder(\'改打技能范围内近身怪\')\n')
        break

open('maple_route_ui.py', 'w', encoding='utf-8').writelines(lines)
print('修改完成')
