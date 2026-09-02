# -*- coding: utf-8 -*-
"""永久关掉自动备份线程（注释掉启动代码，函数保留不调用）"""
import io

path = r"C:\Users\wenwen\Desktop\MXD\maple_bot\maple_route_ui.py"
with io.open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = '''        # 自动备份线程：每30分钟备份一次源码，保留最近20个
        self._auto_backup_interval = 1800  # 30分钟
        self._last_backup_time = 0
        self._auto_backup_thread = threading.Thread(target=self._auto_backup_loop, daemon=True)
        self._auto_backup_thread.start()
        print("[自动备份] 已启动，每30分钟Git自动提交一次")'''
new = '''        # 自动备份线程：已永久关闭（2026-09-01用户要求），函数_auto_backup_loop保留但不启动
        # self._auto_backup_interval = 1800  # 30分钟
        # self._last_backup_time = 0
        # self._auto_backup_thread = threading.Thread(target=self._auto_backup_loop, daemon=True)
        # self._auto_backup_thread.start()
        # print("[自动备份] 已启动，每30分钟Git自动提交一次")'''
assert old in src, "未找到自动备份启动代码"
src = src.replace(old, new, 1)

with io.open(path, "w", encoding="utf-8") as f:
    f.write(src)
print("自动备份已永久关闭")
