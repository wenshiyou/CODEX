# 2D横版游戏挂机助手

基于 Python + OpenCV + YOLO 的 2D 横版游戏通用挂机脚本框架。

## 功能特性

### 核心功能
- **人物/怪物定位**: YOLO 目标检测，实时定位人物和怪物位置
- **距离计算**: 欧氏距离、水平距离、垂直距离，判定攻击还是靠近
- **三级优先级选怪**:
  1. 左右最近的怪（同平台 + 攻击范围内）→ 直接攻击
  2. 同平台远距离怪 → 向怪靠近
  3. 上下平台的怪 → 跳/瞬移或爬梯子

### 路线记录
- **平台录制**: 人物在平台上走一遍，自动记录平台范围，以后只打这些位置的怪
- **梯子录制**: 人物爬一遍梯子，自动记录梯子位置
- **智能路径选择**: 根据垂直差和预估耗时，科学选择跳/瞬移还是爬梯子

### 小地图标记
- 独立 OpenCV 窗口，映射游戏小地图
- 实时绘制: 平台(绿)、梯子(蓝)、怪物(红)、人物(黄)

### 技能与药品
- **主攻技能**: 可配置按键和冷却
- **BUFF技能**: 定时自动释放
- **药品BUFF**: 同 BUFF 逻辑
- **红药/蓝药**: 图像识别血条/蓝条百分比，低于阈值自动吃药

### GUI 面板（切换式 Tab）
| Tab | 功能 |
|-----|------|
| 攻击 | 攻击范围、主攻技能、开始/停止、运行状态 |
| 路线 | 平台录制、梯子录制、已记录列表管理 |
| 技能 | BUFF/药品BUFF 技能配置 |
| 药品 | 红药/蓝药阈值、键位、血条区域 |
| 设置 | YOLO模型路径、截图区域、检测参数 |
| 小地图 | 独立窗口开关、区域设置 |

## 目录结构

```
maple_bot/
├── main.py                  # 入口
├── requirements.txt         # 依赖
├── build.bat                # 打包脚本
├── config/
│   ├── config.json          # 配置文件
│   └── config_loader.py     # 配置加载
├── core/
│   ├── bot.py               # 核心状态机（主循环）
│   ├── detector.py          # YOLO 检测封装
│   ├── locator.py           # 人物/怪物定位
│   ├── decision.py          # 攻击决策
│   ├── controller.py        # 键鼠控制（Win32 SendInput）
│   ├── platform.py          # 平台记录管理
│   ├── ladder.py            # 梯子记录管理
│   ├── pathfinder.py        # 路径选择（跳/爬）
│   ├── skill.py             # 技能系统
│   └── potion.py            # 药品自动系统
├── ui/
│   ├── main_window.py       # PyQt5 主面板
│   └── minimap_window.py    # 小地图标记窗口
├── utils/
│   ├── capture.py           # 屏幕截图
│   └── geometry.py          # 几何计算
└── data/
    ├── models/              # 存放训练好的 YOLO 模型 (.pt)
    ├── platforms.json       # 平台记录（自动生成）
    └── ladders.json         # 梯子记录（自动生成）
```

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 放置 YOLO 模型
将你训练好的模型文件放到 `data/models/best.pt`

模型需要能检测以下类别（类别名可在 `config/config.json` 中修改）:
- `player` - 玩家人物
- `monster` - 怪物
- `ladder` - 梯子（可选）
- `npc` - NPC（可选）
- `portal` - 传送点（可选）

### 3. 配置
编辑 `config/config.json`:
- `yolo.model_path`: 模型路径
- `game.capture_region`: 截图区域 `[x, y, w, h]`
- `combat.attack_range`: 攻击范围
- `potions.hp_bar_region`: 血条在屏幕上的位置

### 4. 运行
```bash
python main.py
```

### 5. 使用流程
1. 打开游戏，调整好窗口位置
2. 在「设置」Tab 配置截图区域和模型路径
3. 在「路线」Tab 录制平台和梯子
4. 在「技能」Tab 配置技能
5. 在「药品」Tab 配置药品
6. 在「攻击」Tab 点击「开始挂机」

## 打包成 EXE

运行打包脚本:
```bash
build.bat
```

或手动执行:
```bash
pyinstaller --onefile --windowed --name "MapleBot" ^
    --add-data "config;config" --add-data "data;data" ^
    --hidden-import ultralytics --hidden-import cv2 ^
    --hidden-import mss --hidden-import PyQt5 ^
    --hidden-import sklearn main.py
```

打包完成后，可执行文件在 `dist/MapleBot.exe`

## YOLO 模型对接说明

本框架已封装好 YOLO 检测接口（`core/detector.py`），你只需要:

1. 用你自己的数据集训练 YOLOv8 模型
2. 将训练好的 `best.pt` 放到 `data/models/` 目录
3. 在 `config/config.json` 中配置 `class_names`（类别名到ID的映射）

程序启动时会自动加载模型，每帧截图后调用 `detector.detect(frame)` 获取检测结果。

检测结果格式:
```python
{
    "class": "monster",      # 类别名
    "class_id": 1,           # 类别ID
    "confidence": 0.92,      # 置信度
    "bbox": [x1, y1, x2, y2], # 检测框
    "center": (cx, cy)       # 中心点
}
```

## 注意事项

- 本工具仅供学习研究使用，请遵守游戏用户协议
- 部分游戏有反作弊机制，Win32 SendInput 可能被拦截
- 首次使用建议先在低风险区域测试
- 血条/蓝药识别需要准确配置屏幕区域
