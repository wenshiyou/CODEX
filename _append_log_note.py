# -*- coding: utf-8 -*-
import io, os
p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\工作记录_排障记录.md"
raw = io.open(p, "rb").read()
bom = raw.startswith(b"\xef\xbb\xbf")
crlf = b"\r\n" in raw
text = raw.decode("utf-8-sig")
nl = "\r\n" if crlf else "\n"

note = """
---

## 【记录004】debug.log 按“当日秒数”裁剪，跨天追加时误删今天/误留昨晚 → 运行段切不出、发呆现场被清

- **日期**：2026-09-22
- **现象**：日志“只留最近几分钟”异常——今天上午的运行段被删、昨晚 22/23 点段反被保留；按行首 HH:MM:SS 切“最后运行段”会切到昨晚，真机发呆现场被错误清掉，无法复盘。
- **根因**：`_maint_trim_debug_log`（maple_route_ui.py）拿行首 `[HH:MM:SS]` 的**当日秒数**直接和 cutoff 比较，行首没有日期；日志跨午夜持续追加时，今天上午秒数(~43000) 小于昨晚 22-23 点秒数(~80000+)，今天较早行被当“旧”删、昨晚被当“新”留。
- **解决**：重写为按**物理行序**裁剪——以末尾有戳行时间为基准，从后往前还原每行跨天绝对秒数（从后往前当日秒数反而明显变大、超过 5 分钟容差 = 往前跨过一个午夜，基准 −86400），再从末尾保留 N 分钟做一次物理截断；无时间戳的堆栈/续行随切片自然保留；`.tmp + os.replace` 原子换；`except` 改为 `print` 不再静默吞。保留时长 5 → **60 分钟**（函数默认值与 `_maint_run` 实参都改为 60）。
- **验证**：ast 抽取真实方法 + 假 self 跑 4 组断言全过——A 跨天(昨晚 600 行全删、今天 1001 行全留，首尾时间正确)、B 同天 60 分钟窗口边界(首 11:16:40、3601 行)、C 无戳续行随切片保留、D 真实 debug.log 副本 248245→12603 行且昨晚段清零；真机对真实日志裁剪 **252940→17298 行、[22:/[23: 清零**；提权重启后新进程(PID19700)持续写新文件、无 .tmp 残留；py_compile 通过、AST 方法名/self 属性遮蔽交集为空。
- **触发时机**：维护在战斗线程 `run()` 的 `while True` 内，`_last_maint_ts=0` 首圈即跑、之后每 600s 一次；本次重启后已用同一函数对真实日志等价首裁一次（幂等，程序自裁结果相同）。
- **回滚**：裁剪重写前、已含“保留1小时”改动的提交 = `8138f8b`；本次修复提交 = `2d2c2e7`。
- **注意**：保留 1 小时后日志量约 ×12（满负荷约数万行/十几 MB 每小时），文件到 20MB 仍走原有轮转 `debug.log.bak`；看日志仍守“先最后 3 分钟、只看运行态、按物理行最后 F10/[初始化] 切段、MP 横带<0.85 段忽略”的铁律。
"""

add = note.replace("\n", nl)
if not text.endswith(nl):
    text += nl
text += add
out = text.encode("utf-8")
if bom:
    out = b"\xef\xbb\xbf" + out
io.open(p, "wb").write(out)
print("APPENDED, bom=%s crlf=%s, new bytes=%d" % (bom, crlf, len(out)))
