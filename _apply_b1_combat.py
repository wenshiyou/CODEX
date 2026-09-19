# -*- coding: utf-8 -*-
"""块1a：combat_logic 单攻射程内排序 纯X近 -> Y近优先再X近（群怪选怪路径不动）。普通UTF-8/LF/无BOM。"""
import io
import py_compile

P = r'C:\Users\wenwen\Desktop\MXD\maple_bot_v2\combat_logic.py'
raw = io.open(P, 'r', encoding='utf-8').read()
assert '\r\n' not in raw, 'combat_logic 出现 CRLF，中止'

REPLS = [
    (
        "单攻范围内按X近、范围外按Y近再X近。返回 _mk dict。\"\"\"",
        "单攻射程内外统一按 Y近优先、Y同档再X近。返回 _mk dict。\"\"\"",
    ),
    (
        "        # ===================== 单攻选怪(用户2026-09-10定稿:范围内按X、范围外按Y,排序键唯一不左右为难) =====================\n"
        "        # ①技能范围内有能直打的:只按X近选(不看Y)→cast站定打;②全都在范围外:才按Y相近优先、再X近→pursue走过去\n"
        "        if in_attack_rows:\n"
        "            in_attack_rows.sort(key=lambda r: r[0])\n"
        "            pick = in_attack_rows[0]\n"
        "        else:\n"
        "            cand.sort(key=lambda r: (abs(r[2] - py), r[0]))\n"
        "            pick = cand[0]\n",
        "        # ===================== 单攻选怪(用户2026-09-18定稿:射程内外统一Y近优先、Y同档再X近,排序键唯一不左右为难) =====================\n"
        "        # ①技能范围内有能直打的:按Y差最近优先、Y同档再X近→cast站定打(不再纯X近,避免Y差更大的同X怪被先锁);\n"
        "        # ②全都在范围外:同一排序键Y近→X近→pursue走过去。两段口径完全一致。\n"
        "        if in_attack_rows:\n"
        "            in_attack_rows.sort(key=lambda r: (abs(r[2] - py), r[0]))\n"
        "            pick = in_attack_rows[0]\n"
        "        else:\n"
        "            cand.sort(key=lambda r: (abs(r[2] - py), r[0]))\n"
        "            pick = cand[0]\n",
    ),
]

for i, (old, new) in enumerate(REPLS, 1):
    c = raw.count(old)
    assert c == 1, '第%d处命中 %d 次（应为1），中止' % (i, c)
    raw = raw.replace(old, new)

io.open(P, 'w', encoding='utf-8', newline='').write(raw)
py_compile.compile(P, doraise=True)
print('BLOCK1a combat_logic OK, py_compile pass')
