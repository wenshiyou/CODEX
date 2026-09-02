p = r'C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py'
with open(p, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到 _on_mouse 定义行
start = None
for i, line in enumerate(lines):
    if line.strip() == 'def _on_mouse(self, event, x, y, flags, param):':
        start = i
        break
assert start is not None, '_on_mouse not found'
print('Found _on_mouse at line', start+1)

# 找到下一个同级 def (4个空格缩进的 def)
end = None
for i in range(start+1, len(lines)):
    if lines[i].startswith('    def '):
        end = i
        break
assert end is not None, 'end not found'
print('_on_mouse ends before line', end+1)

# 提取函数体（从 docstring 后开始）
func_lines = lines[start:end]
# 找到 docstring 结束行（第一个非注释、非空行之后）
body_start = start + 1  # def 行
while body_start < end and (lines[body_start].strip().startswith('"""') or lines[body_start].strip() == '' or lines[body_start].strip().startswith('#')):
    if lines[body_start].strip().startswith('"""') and lines[body_start].strip().endswith('"""') and len(lines[body_start].strip()) > 3:
        body_start += 1
        break
    body_start += 1
print('Body starts at line', body_start+1)

# 构建新函数
new_func = []
new_func.append('    def _on_mouse(self, event, x, y, flags, param):\n')
new_func.append('        """鼠标点击回调：标签页切换 + 路线页按钮"""\n')
new_func.append('        try:\n')
new_func.append('            self._on_mouse_body(event, x, y, flags, param)\n')
new_func.append('        except Exception as _e:\n')
new_func.append('            print("[鼠标] _on_mouse异常:", _e)\n')
new_func.append('            import traceback\n')
new_func.append('            traceback.print_exc()\n')
new_func.append('\n')
new_func.append('    def _on_mouse_body(self, event, x, y, flags, param):\n')
# 原来的函数体（从 body_start 到 end），保持原缩进（已经是8空格）
for i in range(body_start, end):
    new_func.append(lines[i])

# 替换
new_lines = lines[:start] + new_func + lines[end:]
with open(p, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Done. _on_mouse wrapped with try-except')
