# MapleBot 打包完整操作说明

> **用途**：打包出错时参考此文档，确保不遗漏任何文件和步骤。

---

## 一、打包方式

### 1.1 打包工具
- **工具**：PyInstaller
- **配置文件**：`MapleBot.spec`
- **入口脚本**：`maple_route_ui.py`（注意：不是 `MapleBot.py`）

### 1.2 spec 文件完整内容
```python
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['maple_route_ui.py'],          # 入口脚本
    pathex=[],
    binaries=[],
    datas=[('config', 'config'), ('data', 'data')],  # 打包的数据目录
    hiddenimports=['ultralytics', 'cv2', 'mss', 'sklearn'],  # 隐式导入
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MapleBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                     # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

### 1.3 spec 文件关键参数说明

| 参数 | 值 | 说明 |
|------|-----|------|
| 入口脚本 | `maple_route_ui.py` | 程序主入口，不是 MapleBot.py |
| datas | `('config', 'config'), ('data', 'data')` | 打包 config 和 data 两个目录 |
| hiddenimports | `ultralytics, cv2, mss, sklearn` | 隐式导入的库，必须指定 |
| name | `MapleBot` | 输出 exe 文件名 |
| console | `False` | 不显示控制台窗口（窗口程序） |
| upx | `True` | 启用 UPX 压缩 |

---

## 二、项目文件结构

### 2.1 根目录文件

| 文件名 | 大小 | 用途 |
|--------|------|------|
| `maple_route_ui.py` | 主源码 | 程序主入口，包含所有UI和逻辑 |
| `MapleBot.py` | 入口 | 备用入口（实际打包用 maple_route_ui.py） |
| `MapleBot.spec` | 打包配置 | PyInstaller 配置文件 |
| `BACKUP_LOG.md` | 备份记录 | 备份记录和回滚方法 |
| `BUILD_GUIDE.md` | 打包说明 | 本文档 |
| `CODING_STANDARDS.md` | 代码规范 | 代码注释规范 |
| `PROJECT_STATE.md` | 项目状态 | 项目当前状态记录 |

### 2.2 config 目录（必须打包）

| 文件名 | 大小 | 用途 |
|--------|------|------|
| `config.json` | 2032B | 程序配置文件 |
| `config_loader.py` | 1404B | 配置加载器 |
| `__init__.py` | 0B | 包初始化文件 |

### 2.3 data 目录（必须打包）

#### 2.3.1 根目录文件

| 文件名 | 大小 | 用途 |
|--------|------|------|
| `ui_bg_blank.png` | 86191B | **主背景图**（UI界面背景，替换背景图就是改这个） |
| `ui_bound_dropdown.png` | 9515B | 下拉菜单背景 |
| `ui_calib_auto.png` | 5098B | 自动校准按钮 |
| `ui_calib_left.png` | 3496B | 左校准按钮 |
| `ui_calib_right.png` | 3486B | 右校准按钮 |
| `ui_calib_top.png` | 3609B | 上校准按钮 |
| `ui_char_btn.png` | 8195B | 角色按钮 |
| `ui_crosshair.png` | 8255B | 准星图标 |
| `ui_fight_latest.png` | 200764B | 战斗页背景（最新） |
| `ui_fight_new.png` | 128568B | 战斗页背景（新） |
| `ui_ladder.png` | 7229B | 梯子按钮 |
| `ui_ladder_clear.png` | 8317B | 清除梯子按钮 |
| `ui_log_bg.png` | 6022B | 日志背景 |
| `ui_manual.png` | 12103B | 手动按钮 |
| `ui_mode.png` | 7822B | 模式按钮 |
| `ui_monster_data.png` | 9746B | 怪物数据按钮 |
| `ui_offset_label.png` | 12088B | 偏移标签 |
| `ui_plan.png` | 7874B | 方案按钮 |
| `ui_plan_clear.png` | 9039B | 清除方案按钮 |
| `ui_plan_toolbar.png` | 3746B | 方案工具栏按钮 |
| `ui_platform.png` | 7159B | 平台按钮 |
| `ui_platform_clear.png` | 8625B | 清除平台按钮 |
| `ui_refresh.png` | 8208B | 刷新按钮 |
| `ui_run.png` | 13280B | 运行按钮 |
| `ui_save.png` | 7899B | 保存按钮 |
| `ui_stop.png` | 10308B | 停止按钮 |
| `ui_tab_chat.png` | 156402B | 聊天页标签 |
| `ui_tab_fight.png` | 128568B | 战斗页标签 |
| `ui_tab_lie.png` | 144079B | 路径页标签 |
| `ui_tab_potion.png` | 140597B | 药水页标签 |
| `ui_winbind_bg.png` | 22029B | 窗口绑定背景 |
| `minimap_region.json` | 180B | 小地图区域配置 |
| `route_1_ladders.json` | 36B | 方案1梯子数据 |
| `route_1_platforms.json` | 138B | 方案1平台数据 |
| `route_config.json` | 59B | 路径配置 |

#### 2.3.2 data/char_templates 目录

| 文件名 | 大小 | 用途 |
|--------|------|------|
| `char_0.png` | 20906B | 角色模板图 |

#### 2.3.3 data/templates 目录（小地图识别模板）

| 文件名 | 大小 | 用途 |
|--------|------|------|
| `bigmap_title.png` | 518B | 大地图标题模板（右边界定位） |
| `btn_bar.png` | 26339B | 按钮栏模板 |
| `btn_clear_ladder.png` | 2864B | 清除梯子按钮模板 |
| `btn_clear_platform.png` | 3216B | 清除平台按钮模板 |
| `btn_clear_route.png` | 2747B | 清除方案按钮模板 |
| `btn_ladder.png` | 2528B | 梯子按钮模板 |
| `btn_mode.png` | 2675B | 模式按钮模板 |
| `btn_platform.png` | 2300B | 平台按钮模板 |
| `btn_route.png` | 2144B | 方案按钮模板 |
| `btn_save.png` | 2691B | 保存按钮模板 |
| `gray_bar.png` | 165B | 灰色条模板 |
| `minimap_blue_arc.png` | 172B | 小地图蓝色弧模板 |
| `minimap_bottom.png` | 191B | **小地图底部模板**（下边界定位，96x13） |
| `minimap_bottom_line.png` | 135B | 小地图底部线模板 |
| `minimap_corner.png` | 32376B | 小地图角落模板 |
| `minimap_header.png` | 6807B | 小地图标题栏模板 |
| `minimap_title.png` | 443B | **小地图标题模板**（左边界定位） |
| `monster_hp_bar.png` | 25104B | 怪物血条模板 |
| `monster_hp_bar_sample.png` | 1722B | 怪物血条样本 |
| `mp_bar.png` | 589B | 蓝条模板 |
| `mp_bar_sample.png` | 2150B | 蓝条样本1 |
| `mp_bar_sample2.png` | 1504B | 蓝条样本2 |
| `mp_label.png` | 423B | 蓝条标签模板 |
| `mp_label_user.png` | 555B | 用户蓝条标签模板 |
| `player_left_0.png` | 337B | 玩家左向模板 |
| `player_right_0.png` | 337B | 玩家右向模板 |
| `ui_bar_full.png` | 3226B | UI完整栏模板 |

---

## 三、打包前准备（必须按顺序执行）

### 3.1 关闭正在运行的程序（最重要！）

**必须先关闭 MapleBot.exe，否则打包会报 PermissionError。**

```powershell
# 方法1：命令行终止
taskkill /F /IM MapleBot.exe

# 方法2：如果命令行无法终止（Access denied），手动在任务管理器中结束进程
```

**验证是否关闭成功**：
```powershell
Get-Process MapleBot -ErrorAction SilentlyContinue
# 如果没有输出，说明已关闭
```

### 3.2 语法检查

```powershell
cd C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot
python -c "import py_compile; py_compile.compile('maple_route_ui.py', doraise=True); print('语法检查通过')"
```

**如果语法检查失败**，修复错误后再继续。

### 3.3 确认背景图已正确替换

如果替换了背景图，确认文件已复制到正确位置：
```powershell
# 确认背景图
Get-Item data\ui_bg_blank.png | Select-Object LastWriteTime, Length

# 确认尺寸是 461x900
python -c "import cv2; img = cv2.imread('data/ui_bg_blank.png'); print('背景图尺寸:', img.shape[1], 'x', img.shape[0])"
```

### 3.4 清理旧的打包缓存

```powershell
# 删除 build 目录（打包缓存）
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue

# 删除旧的 exe
Remove-Item dist\MapleBot.exe -Force -ErrorAction SilentlyContinue
```

---

## 四、执行打包

### 4.1 打包命令

```powershell
cd C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot
pyinstaller --noconfirm MapleBot.spec
```

### 4.2 参数说明

| 参数 | 说明 |
|------|------|
| `--noconfirm` | 不询问确认，直接覆盖输出目录 |
| `MapleBot.spec` | 使用指定的 spec 文件打包 |

### 4.3 打包过程说明

PyInstaller 会执行以下步骤：
1. 分析入口脚本 `maple_route_ui.py` 的依赖
2. 收集隐式导入的库（ultralytics, cv2, mss, sklearn）
3. 打包 datas 中指定的目录（config, data）
4. 生成 PYZ 归档
5. 生成 EXE 文件
6. 输出到 `dist\MapleBot.exe`

**打包时间约 30-60 秒**，请耐心等待。

---

## 五、打包后验证

### 5.1 确认输出文件

```powershell
Get-Item dist\MapleBot.exe | Select-Object LastWriteTime, Length
```

**确认要点**：
- `LastWriteTime` 是最新的打包时间
- `Length` 约 70-75MB（72000000 字节左右）

### 5.2 运行测试

双击 `dist\MapleBot.exe` 运行程序，确认：
1. 程序能正常启动
2. UI界面显示正常（背景图正确）
3. 小地图显示正常
4. 按钮点击正常
5. 没有报错弹窗

---

## 六、常见问题及解决方案

### 6.1 PermissionError: [WinError 5] 拒绝访问

**错误信息**：
```
PermissionError: [WinError 5] 拒绝访问。: '...\\dist\\MapleBot.exe'
```

**原因**：MapleBot.exe 正在运行中，无法被删除覆盖。

**解决方案**：
1. 先关闭程序：`taskkill /F /IM MapleBot.exe`
2. 如果无法终止，手动在任务管理器中结束进程
3. 确认关闭后重新打包

### 6.2 打包后功能没变化

**原因**：
1. 源码没保存
2. build 目录缓存问题
3. 打包的不是最新代码

**解决方案**：
1. 确认源码已保存
2. 删除 build 目录：`Remove-Item -Recurse -Force build`
3. 删除旧 exe：`Remove-Item dist\MapleBot.exe -Force`
4. 重新打包

### 6.3 背景图没更新

**原因**：
1. 背景图没复制到正确位置
2. 背景图尺寸不对
3. 打包缓存问题

**解决方案**：
1. 确认背景图已复制到 `data\ui_bg_blank.png`
2. 确认背景图尺寸是 461x900
3. 删除 build 目录后重新打包

### 6.4 程序启动后闪退

**原因**：
1. 缺少依赖库
2. 资源文件缺失
3. 代码运行时错误

**解决方案**：
1. 临时修改 spec 文件，设置 `console=True`，重新打包查看错误信息
2. 确认 config 和 data 目录已打包
3. 检查代码运行时错误

### 6.5 小地图显示异常

**原因**：
1. 模板图片缺失
2. 小地图区域配置错误
3. 背景图尺寸不对

**解决方案**：
1. 确认 `data\templates\` 目录下所有模板图片存在
2. 确认 `data\minimap_region.json` 配置正确
3. 确认背景图尺寸是 461x900

---

## 七、背景图替换详细步骤

### 7.1 准备新背景图

**要求**：
- 尺寸：461 x 900 像素
- 格式：PNG
- 内容：UI界面背景，包含按钮区域、小地图显示区域等

### 7.2 替换背景图

```powershell
# 复制新背景图到 data 目录
Copy-Item "新背景图路径.png" "data\ui_bg_blank.png" -Force

# 验证替换成功
Get-Item data\ui_bg_blank.png | Select-Object LastWriteTime, Length
python -c "import cv2; img = cv2.imread('data/ui_bg_blank.png'); print('背景图尺寸:', img.shape[1], 'x', img.shape[0])"
```

### 7.3 重新打包

替换背景图后必须重新打包，否则 exe 中的背景图不会更新。

---

## 八、代码修改后打包流程

1. 修改源码 `maple_route_ui.py`
2. 保存文件
3. 语法检查
4. 关闭正在运行的 MapleBot.exe
5. 清理 build 缓存
6. 执行打包
7. 验证输出
8. 运行测试
9. 测试成功后完整备份（Git提交 + 项目副本）

---

## 九、完整备份流程

### 9.1 Git 提交

```powershell
cd C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot
git add -A
git commit -m "备份_日期_修改内容说明"
```

### 9.2 项目副本备份（最可靠）

```powershell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot_backup_$timestamp"
Copy-Item -Path "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot" -Destination $backupDir -Recurse -Force
```

### 9.3 回滚方法

**从项目副本回滚**（最可靠）：
```powershell
# 删除当前项目
Remove-Item -Path "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot" -Recurse -Force

# 从备份恢复
Copy-Item -Path "<备份目录路径>" -Destination "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot" -Recurse -Force
```

**从 Git 回滚**：
```powershell
git log --oneline -5  # 查看提交历史
git checkout <commit_id> -- maple_route_ui.py  # 恢复指定文件
```

---

## 十、一键打包脚本

将以下内容保存为 `build.ps1`，双击即可执行打包：

```powershell
# MapleBot 一键打包脚本
Write-Host "=== MapleBot 打包开始 ===" -ForegroundColor Green

# 1. 关闭程序
Write-Host "[1/6] 关闭正在运行的 MapleBot.exe..." -ForegroundColor Yellow
taskkill /F /IM MapleBot.exe 2>$null
Start-Sleep -Seconds 2

# 2. 进入项目目录
Write-Host "[2/6] 进入项目目录..." -ForegroundColor Yellow
cd C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot

# 3. 语法检查
Write-Host "[3/6] 语法检查..." -ForegroundColor Yellow
python -c "import py_compile; py_compile.compile('maple_route_ui.py', doraise=True); print('语法检查通过')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "语法检查失败，终止打包" -ForegroundColor Red
    exit 1
}

# 4. 清理缓存
Write-Host "[4/6] 清理打包缓存..." -ForegroundColor Yellow
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item dist\MapleBot.exe -Force -ErrorAction SilentlyContinue

# 5. 执行打包
Write-Host "[5/6] 执行打包（约30-60秒）..." -ForegroundColor Yellow
pyinstaller --noconfirm MapleBot.spec

# 6. 验证输出
Write-Host "[6/6] 验证输出..." -ForegroundColor Yellow
$exe = Get-Item dist\MapleBot.exe -ErrorAction SilentlyContinue
if ($exe) {
    Write-Host "打包成功！" -ForegroundColor Green
    Write-Host "文件: $($exe.FullName)"
    Write-Host "大小: $([math]::Round($exe.Length/1MB, 2)) MB"
    Write-Host "时间: $($exe.LastWriteTime)"
} else {
    Write-Host "打包失败，未找到输出文件" -ForegroundColor Red
    exit 1
}

Write-Host "=== 打包完成 ===" -ForegroundColor Green
```

---

## 十一、注意事项

1. **入口脚本是 `maple_route_ui.py`，不是 `MapleBot.py`**
2. **必须打包 `config` 和 `data` 两个目录**（在 spec 文件的 datas 中配置）
3. **必须指定隐式导入的库**：`ultralytics, cv2, mss, sklearn`
4. **打包前必须关闭 MapleBot.exe**，否则会报 PermissionError
5. **替换背景图后必须重新打包**
6. **修改代码后必须重新打包**
7. **测试成功后必须完整备份**（Git提交 + 项目副本）
8. **背景图尺寸必须是 461x900**
9. **console=False**，不显示控制台窗口
10. **upx=True**，启用压缩

---

**文档版本**：v1.0
**创建时间**：2026-08-23
**最后更新**：2026-08-23

---

## 十二、强制规则

**没有特殊要求，一律不要更换流程和方式。**

> 打包必须使用 `MapleBot.spec` 配置文件，执行 `pyinstaller --noconfirm MapleBot.spec` 命令。
> 禁止擅自使用 `--onefile`、`--onedir` 等参数改变打包方式，除非用户明确要求。
