path = r"C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot\maple_route_ui.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Remove import tkinter (line 20, index 19)
new_lines = []
for i, line in enumerate(lines):
    if line.strip() == "import tkinter as tk":
        print("Removed import tkinter at line", i+1)
        continue
    # Remove select_region_on_screen function (lines 274-328, indices 273-327)
    if 273 <= i <= 327:
        continue
    new_lines.append(line)

with open(path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Done. Removed tkinter import and select_region_on_screen function")
