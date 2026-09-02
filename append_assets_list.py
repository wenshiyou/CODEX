with open('PROJECT_STATE.md', 'a', encoding='utf-8') as f:
    f.write("""
## 常用UI素材清单（data目录下，绝对不能随便换）

### 标签页背景
- ui_bg_blank.png - 路线标签页背景（123380字节）
- ui_tab_fight.png - 战斗标签页背景（128568字节）
- ui_tab_potion.png - 吃药标签页背景（140597字节）
- ui_tab_chat.png - 聊天标签页背景（156402字节）
- ui_tab_lie.png - 测谎标签页背景（144079字节）

### 按钮图标
- ui_platform.png - 平台录制按钮
- ui_ladder.png - 梯子录制按钮
- ui_save.png - 保存按钮
- ui_plan.png - 方案按钮
- ui_platform_clear.png - 清除平台按钮
- ui_ladder_clear.png - 清除梯子按钮
- ui_mode.png - 模式切换按钮
- ui_plan_clear.png - 清除方案按钮
- ui_run.png - 运行按钮
- ui_stop.png - 停止按钮
- ui_refresh.png - 刷新按钮
- ui_manual.png - 手动按钮
- ui_char_btn.png - 人物特征按钮

### 校准相关
- ui_calib_auto.png - 自动校准
- ui_calib_left.png - 左端点
- ui_calib_right.png - 右端点
- ui_calib_top.png - 上端点

### 其他
- ui_log_bg.png - 日志背景
- ui_winbind_bg.png - 窗口绑定背景
- ui_bound_dropdown.png - 绑定下拉菜单
- ui_crosshair.png - 十字准星
- ui_monster_data.png - 怪物数据
- ui_offset_label.png - 偏移标签
- ui_plan_toolbar.png - 方案工具栏

### 注意
- ui_fight_latest.png 和 ui_fight_new.png 是备用版本，当前未使用
- 所有素材路径：data/文件名
- 加载方式：resource_path(os.path.join("data", 文件名))
- 用户没说要换的素材，绝对不能随便换！
""")
print('已追加素材清单到MD')
