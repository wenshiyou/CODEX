' 双击运行，自动请求管理员权限
Set objShell = CreateObject("Shell.Application")
objShell.ShellExecute "python", "maple_route_ui.py", "C:\Users\wenwen\Desktop\MXD\maple_bot", "runas", 1
