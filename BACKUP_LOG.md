# 项目备份记录

## 备份说明
每次修改前必须创建完整项目副本备份，确保100%可回滚。

## 备份方法
```powershell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot_backup_$timestamp"
Copy-Item -Path "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot" -Destination $backupDir -Recurse -Force
```

## 回滚方法
```powershell
# 删除当前项目
Remove-Item -Path "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot" -Recurse -Force
# 从备份恢复
Copy-Item -Path "<备份目录路径>" -Destination "C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot" -Recurse -Force
```

## 备份记录

| 时间 | 备份路径 | 文件数 | 说明 |
|------|----------|--------|------|
| 2026-08-30 18:09:57 | backup\完整备份_绿框钳制左4右7上5下5_20260830_180957.zip | 完整（源码+config+data json+模板+UI图片+文档+spec） | 恢复2026-08-29 23:16备份后，绿框整体移动范围钳制改为左4右7上5下5（_draw_blue_box和lock_screen_from_dot两处同步），onedir模式打包，v56 |
| 2026-08-23 14:57:40 | `C:\Users\PC\Doubao\chats\2026-08-15\new-chat-4\maple_bot_backup_20260823_145740` | 1982 | 当前状态（小地图底部灰边问题） |

## 工作流程规范
1. **修改前**：创建完整项目副本备份（必须包含运行时配置文件）
2. **修改中**：只改需要改的部分，绝不碰其他功能
3. **修改后**：先验证，再打包
4. **验证成功**：Git完整提交 + 记录备份
5. **验证失败**：从备份回滚

## 完整备份规范（强制遵守）
**每次备份必须是完整备份，包含以下所有文件：**
1. **代码文件**：所有 `.py` 源文件
2. **data目录**：`data/` 下所有文件（方案数据、校准数据、配置文件、模板图片、UI素材等）
3. **配置文件**：`MapleBot.spec`、`.gitignore` 等
4. **MD文档**：所有 `.md` 文档（PROJECT_STATE.md、BACKUP_LOG.md、CODING_STANDARDS.md、BUILD_GUIDE.md、功能实现指南与排错手册.md等）
5. **dist目录**：打包后的exe和运行时数据（可选，但建议包含）

**备份位置：** 全部提交到GIT远程仓库（https://github.com/wenshiyou/CODEX.git）

**备份命名规范：**
- Git commit message 格式：`备份_YYYYMMDD_功能描述+修改内容`
- 示例：`备份_20260823_平台梯子显示修复+倍率文字白色+三点校准调试`
- 命名要清晰描述本次备份包含的功能和修改，方便后续查找和回滚

**备份命令：**
```powershell
git add -A
git commit -m "备份_YYYYMMDD_功能描述"
git push origin main
```

## 重大教训

### 教训1：备份必须包含运行时配置文件（2026-08-23）
**问题现象**：平台绿线、梯子蓝线不显示，只显示怪物紫色点。即使代码回滚到正常备份版本，问题依旧。

**根本原因**：只备份了代码文件（`.py`），没有备份运行时生成的配置文件。`data/minimap_region.json` 配置错误（小地图高度只有10像素），导致平台/梯子坐标超出范围被过滤。代码正确但配置错误，问题依旧。

**必须备份的运行时文件清单**：
- `data/minimap_region.json` — 小地图截取区域配置
- `data/route_*_platforms.json` — 平台数据
- `data/route_*_ladders.json` — 梯子数据
- `data/route_*_calib.json` — 校准数据
- `data/route_config.json` — 当前方案配置
- `data/fight_potion_config.json` — 吃药配置
- `data/ui_bg_blank.png` — UI背景图
- `debug.log` — 运行日志（可选）

**正确备份方式**：备份整个项目目录，包括 `data/` 目录下的所有文件，而不是只备份 `.py` 文件。
