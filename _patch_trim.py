# -*- coding: utf-8 -*-
# 根因修复 debug.log 裁剪跨天错乱（边界法整段替换，不依赖逐字匹配函数体）。
import io, sys

p = r"C:\Users\wenwen\Desktop\MXD\maple_bot_v2\maple_route_ui.py"
raw = io.open(p, "rb").read().decode("utf-8-sig")
norm = raw.replace("\r\n", "\n")

START = "    def _maint_trim_debug_log(self, keep_minutes=60):"
END = "    def _maint_run(self):"
if norm.count(START) != 1:
    print("START ANCHOR FAIL", norm.count(START)); sys.exit(3)
if norm.count(END) < 1:
    print("END ANCHOR FAIL", norm.count(END)); sys.exit(3)
i = norm.index(START)
j = norm.index(END, i)
print("旧函数块字符长度:", j - i)

NEW = '''    def _maint_trim_debug_log(self, keep_minutes=60):
        """只保留最近 keep_minutes 分钟的 debug.log（按物理行序、正确处理午夜跨天）。

        日志按追加顺序写、行首只有 [HH:MM:SS] 无日期，午夜秒数会回退。旧实现直接拿
        当日秒数和 cutoff 比较，跨天追加时会把今天上午(秒数小)误删、把昨晚(秒数大)误留。
        新实现以末尾行时间为基准，从后往前还原每行跨天绝对秒数（从后往前当日秒数反而
        明显变大=往前跨过一个午夜，基准减 86400），再按物理行序从末尾保留 N 分钟一次截断；
        无时间戳的堆栈/续行随物理切片自然保留。文件<0.5MB 不动，避免频繁重写小文件。
        """
        p = DEBUG_LOG
        try:
            if not os.path.exists(p):
                return
            if os.path.getsize(p) < 0.5 * 1024 * 1024:
                return
            raw = io.open(p, "rb").read().decode("utf-8", "ignore")
            lines = raw.splitlines()
            if len(lines) < 200:
                return

            def _tod(line):
                m = re.match(r"^\\[(\\d{2}):(\\d{2}):(\\d{2})\\]", line)
                if not m:
                    return None
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))

            secs = [_tod(x) for x in lines]
            last_idx = -1
            for _i in range(len(secs) - 1, -1, -1):
                if secs[_i] is not None:
                    last_idx = _i
                    break
            if last_idx < 0:
                return
            cutoff = secs[last_idx] - keep_minutes * 60
            abs_secs = [None] * len(secs)
            abs_secs[last_idx] = secs[last_idx]
            day = 0
            prev_tod = secs[last_idx]
            for _i in range(last_idx - 1, -1, -1):
                _t = secs[_i]
                if _t is None:
                    continue
                # 从后往前正常应递减；当日秒数反而明显变大(>5分钟容差)=往前跨过一个午夜
                if _t > prev_tod + 300:
                    day -= 86400
                abs_secs[_i] = day + _t
                prev_tod = _t
            # 从末尾往前第一个早于 cutoff 的有戳行即窗口旧边界，其前物理行全部更旧
            cut_pos = -1
            for _i in range(last_idx, -1, -1):
                _a = abs_secs[_i]
                if _a is not None and _a < cutoff:
                    cut_pos = _i
                    break
            keep_from = cut_pos + 1
            if keep_from <= 0:
                return
            out = lines[keep_from:]
            if out:
                tmp = p + ".tmp"
                io.open(tmp, "wb").write(("\\n".join(out) + "\\n").encode("utf-8"))
                os.replace(tmp, p)
        except Exception as _e:
            # 文件维护属外部IO，失败要可见、不能静默吞(规则8)；不影响主循环
            print("[日志维护] debug.log 裁剪失败:", _e)'''

norm2 = norm[:i] + NEW + "\n\n" + norm[j:]
io.open(p, "w", encoding="utf-8-sig", newline="").write(norm2.replace("\n", "\r\n"))
print("PATCH OK: _maint_trim_debug_log 重写为物理行序+跨天还原")
