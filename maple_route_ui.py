"""
Minimap Route Recorder - 鼠标操作版
Auto lock game window + blue border detection (projection) + ROI dot tracking
三套方案（route_1/2/3），每套独立存储平台+梯子；方式：手动/随机
操作：纯鼠标点击，第一排 平台/梯子/清平台/清梯子/保存/手动/刷新
      第二排 方案1/方案2/方案3/清方案/方式切换
"""
import ctypes
import struct
import mss
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import os
import json
import base64
import time
import sys

# === 最早固定工作目录=脚本所在目录 ===
# 管理员提权重启(runas)后cwd可能变成System32，导致debug.log/data相对路径全丢；在所有重逻辑前强制切回脚本目录
try:
    _SCRIPT_PATH = sys.argv[0] if getattr(sys, "argv", None) and sys.argv[0] else __file__
    SCRIPT_DIR = os.path.dirname(os.path.abspath(_SCRIPT_PATH))
    if os.path.isdir(SCRIPT_DIR):
        os.chdir(SCRIPT_DIR)
except Exception:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# === 单实例锁v3（2026-09-07加固，防任务管理器Python(2)双实例抢CPU）===
# 必须放在所有重import(mss/numpy/cv2/pygame等)之前：第二个实例一启动就探测退出，
# 否则import耗时1-2秒内任务管理器会短暂显示Python(2)。
# 三道防线：①主窗口探测(FindWindow,不受UIPI限制) ②互斥体探测(OpenMutexW只读,不创建,不挡自己提权链路)
#           ③提权后创建互斥体主锁(句柄挂全局防GC) + 错误码用ctypes.get_last_error()规范读取。
_SINGLE_MUTEX_NAME = "MapleBot_MSW_SingleInstance_Mutex"
_BOT_WIN_TITLE = "PLAY AND HAPPY"
_K32 = None
_U32 = None

def _init_single_winapi():
    """初始化单实例锁用到的Win32 API（惰性，只在需要时加载，避免拖慢import）。"""
    global _K32, _U32
    if _K32 is None:
        _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _U32 = ctypes.WinDLL("user32", use_last_error=True)

def _probe_any_instance_running():
    """只读探测是否已有实例在跑（不创建互斥体，避免挡住自己提权链路的后续进程）。"""
    _init_single_winapi()
    # 探测1：主窗口标题存在=已有一个bot实例窗口在显示（窗口句柄枚举不受UIPI限制，普通权限也能看到）
    if _U32.FindWindowW(None, _BOT_WIN_TITLE):
        return True
    # 探测2：互斥体能打开=已有实例持有锁
    # MUTEX_ALL_ACCESS=0x1F0001；返回句柄=存在；返回NULL且错误码2(不存在)→继续启动；
    # 返回NULL且错误码5(拒绝访问)/183(已存在)/其他→保守视为已有实例，退出
    _h = _K32.OpenMutexW(0x1F0001, False, _SINGLE_MUTEX_NAME)
    if _h:
        _K32.CloseHandle(_h)
        return True
    _err = ctypes.get_last_error()
    if _err in (0, 2):  # 0=成功(理论不会，成功会返回句柄)；2=互斥体不存在
        return False
    return True  # 5/183/其他一律视为已有实例，宁多退不多跑

if __name__ == "__main__":
    try:
        if _probe_any_instance_running():
            print("[单实例] 已有一个脚本在运行，本实例自动退出（避免重复抢CPU）")
            sys.exit(0)
    except Exception as _e:
        # 早期探测失败不阻塞启动，由底部__main__的正式锁再兜底
        print("[单实例] 早期探测失败(降级由正式锁兜底): %s" % _e)
# 设置默认编码为UTF-8，解决Python 3.9中文乱码问题
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
import subprocess
import queue
import random
import threading
import pygame  # 用于创建透明置顶准星窗口，支持拖拽到屏幕任意位置
import win32gui  # Windows GUI API，用于设置窗口置顶和透明
import win32con  # Windows常量定义
import win32api  # Windows API，用于RGB颜色转换
import combat_logic  # 打怪决策核心(纯逻辑)；顶层静态导入保证PyInstaller打进exe，供[新决策]影子日志使用

# === 必须在创建任何窗口之前设置 DPI 感知，否则高DPI缩放下蒙板坐标错位 ===
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

def _debug_log(msg):
    """写调试日志到文件，exe无控制台时用。超过20MB自动轮转备份。"""
    try:
        # 日志固定写到脚本/exe所在目录的绝对路径，避免管理员提权重启后工作目录变成System32导致日志丢失
        if getattr(sys, 'frozen', False):
            log_dir = os.path.dirname(sys.executable)
        else:
            log_dir = globals().get("SCRIPT_DIR", os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(log_dir, "debug.log")
        if os.path.exists(path) and os.path.getsize(path) > 20 * 1024 * 1024:
            bak = path + ".bak"
            if os.path.exists(bak):
                os.remove(bak)
            os.rename(path, bak)
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass

# 无缓冲输出，方便实时看日志（windowed模式下stdout为None，跳过）
if sys.stdout is not None:
    sys.stdout.reconfigure(line_buffering=True)

def resource_path(relative_path):
    """获取资源文件路径，兼容PyInstaller打包"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def load_png(path):
    """加载PNG（保留alpha透明通道），兼容中文路径"""
    try:
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        return img
    except Exception:
        return None

def draw_asset(frame, asset, x, y, w, h):
    """将素材绘制到frame上，支持PNG透明通道混合"""
    if asset is None:
        return
    img = cv2.resize(asset, (w, h))
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = (img[:, :, 3:4].astype(np.float32)) / 255.0
        roi = frame[y:y+h, x:x+w].astype(np.float32)
        frame[y:y+h, x:x+w] = (img[:, :, :3].astype(np.float32) * alpha + roi * (1.0 - alpha)).astype(np.uint8)
    else:
        frame[y:y+h, x:x+w] = img

def draw_rounded_rect(img, x, y, w, h, radius, color, thickness=-1):
    """绘制圆角矩形（thickness=-1为填充）"""
    r = min(radius, w // 2, h // 2)
    # 四个角
    cv2.circle(img, (x + r, y + r), r, color, thickness)
    cv2.circle(img, (x + w - r, y + r), r, color, thickness)
    cv2.circle(img, (x + r, y + h - r), r, color, thickness)
    cv2.circle(img, (x + w - r, y + h - r), r, color, thickness)
    # 中间矩形
    cv2.rectangle(img, (x + r, y), (x + w - r, y + h), color, thickness)
    cv2.rectangle(img, (x, y + r), (x + w, y + h - r), color, thickness)

def app_dir():
    """获取程序所在目录（用于可写数据），兼容PyInstaller"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

os.chdir(app_dir())

DISPLAY_SCALE = 1
WINDOW_TITLE = "冒险岛怀旧服"
WINDOW_KEYWORDS = ["冒险岛", "MapleStory Worlds"]  # 自动绑定匹配冒险岛和MapleStory Worlds，其他窗口用准星手动绑定
# 人物/怪物特征/YOLO识别有效区固定边距(整窗坐标,用户2026-09-09定稿,写死不随配置变):
# 顶部去30(标题栏/最顶边),底部去90(HP/MP/EXP条+技能快捷栏+聊天UI),只在中间游戏画面带识别,避免把上下UI误识别成人物/怪;X方向整宽
DETECT_TOP_MARGIN = 30
DETECT_BOTTOM_MARGIN = 90
_enum_result = []

@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
def _enum_windows_cb(hwnd, lparam):
    try:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0 and length < 500:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                for kw in WINDOW_KEYWORDS:
                    if kw in title:
                        _enum_result.append((hwnd, title))
                        break
    except Exception:
        pass
    return True

def _find_game_window():
    """枚举所有顶层窗口，找标题包含关键词的游戏窗口"""
    global _enum_result
    _enum_result = []
    try:
        user32.EnumWindows(_enum_windows_cb, 0)
    except Exception as e:
        print("[窗口枚举] 异常:", e)
        return None
    if _enum_result:
        for hwnd, title in _enum_result:
            if "MapleStory" in title:
                return hwnd
        print("[窗口绑定] 未找到游戏窗口(MapleStory)")
        return _enum_result[0][0]
    print("[窗口绑定] 未找到游戏窗口(MapleStory)")
    return None
# 内部小地图渲染尺寸（渲染后缩放到UI区域）
FIXED_W = 340
MAP_H = 250
BTN_BAR_H = 77
BTN_ROW_H = BTN_BAR_H // 2
BTN_COLS = 4
BTN_W = FIXED_W // BTN_COLS
FIXED_H = MAP_H + BTN_BAR_H
DROPDOWN_ITEM_H = 24

# === UI 整体缩放 ===
# === UI 整体尺寸（按参考图 效果图一.png 461x900）===
UI_W = 461
UI_H = 900

def _s(v):
    """fight/potion页用：原330x566设计缩放到UI尺寸"""
    return int(round(v * UI_W / 330.0))

# === 小地图内容区域 ===
UI_MAP_X = 29
UI_MAP_Y = 131
UI_MAP_W = 403
UI_MAP_H = 279
UI_MAP_SCALE = UI_MAP_W / FIXED_W

# === 按钮（参考图精确坐标）===
BTN_PLATFORM = (43, 451, 81, 43)
BTN_LADDER   = (134, 451, 80, 42)
BTN_SAVE     = (229, 451, 80, 42)
BTN_PLAN     = (324, 450, 94, 42)
BTN_PLATFORM_CLR = (43, 500, 81, 39)
BTN_LADDER_CLR   = (134, 499, 80, 39)
BTN_MODE         = (229, 499, 80, 40)
BTN_PLAN_CLR     = (326, 499, 92, 39)
BTN_RUN  = (27, 552, 195, 60)
BTN_STOP = (241, 552, 195, 60)
BTN_CHAR    = (54, 629, 152, 50)
BTN_OFFSET  = (210, 628, 215, 52)
BTN_MONSTER = (61, 694, 344, 46)
# 怪物特征按钮（盖住原来的X/Y偏移输入框，点击打开怪物特征管理弹窗）
BTN_MONSTER_FEATURE = (215, 624, 190, 60)  # 和UI图片大小一致(190x60)，直接用原图不缩放

# === 偏移输入框 ===
# 数字实际绘制区域（小框）
OFFSET_X_DRAW = (228, 653, 87, 22)
OFFSET_Y_DRAW = (324, 654, 85, 22)
# 点击区域（扩大，包含"X偏移/Y偏移"标签文字）
OFFSET_X_CLICK = (228, 628, 87, 44)
OFFSET_Y_CLICK = (319, 628, 85, 45)

# === 工具栏（小地图上方）===
BTN_REFRESH = (28, 103, 57, 26)
BTN_MANUAL = (91, 104, 56, 25)
BTN_PLAN_TOOLBAR = (156, 104, 57, 25)
# 【模块B】X倍率按钮（分开取样：只用绿圈取X分量；坐标对准背景图"X倍率"按钮 x227-284）
BTN_CALIB_AUTO = (227, 104, 57, 25)
# 【模块B】Y倍率按钮（分开取样：只用蓝圈取Y分量；坐标对准背景图"Y倍率"按钮 x294-351）
BTN_CALIB_Y = (294, 104, 57, 25)
# 【技能Y范围按钮·冒险岛世界2026-09-07换图】data/skill_y_range_btn.jpg原图135x39直接叠加(不缩放)，点击弹"主攻/群攻Y范围"窗
# 2026-09-07：原94x32的"Y距离"小按钮换成135x39"技能Y范围"，与左两个135宽按钮一排(瞬移22/寻怪170/技能Y312)，热区同步放大
BTN_Y_RANGE = (312, 288, 135, 39)
# 【瞬移设置按钮·冒险岛世界2026-09-06】data/tp_setting_btn.png原图135x39直接叠加，盖住原"瞬移键/瞬移距离"两输入框(已取消录入功能)；点击弹"X/Y瞬移距离"窗
# 左缘x=22与上一行"跳跃"文字对齐并盖住"瞬移"文字；与右侧"寻怪范围"按钮(各135宽)无缝盖满整行
BTN_TP_SETTING = (22, 288, 135, 39)
# 【寻怪范围按钮·冒险岛世界2026-09-07】替换原"动作录制"占位按钮，data/search_range_btn.jpg原图135x39直接叠加(不缩放)；点击弹"寻怪X/Y范围"窗(默认X1300/Y150)
BTN_SEARCH_RANGE = (170, 288, 135, 39)

# === 窗口绑定 + 准星 ===
BTN_WINBIND = (25, 826, 124, 46)
CROSSHAIR_POS = (116, 849)
CROSSHAIR_SIZE = 30

# === 日志区域 ===
UI_LOG_X = 166
UI_LOG_Y = 754
UI_LOG_W = 274
UI_LOG_H = 135
UI_LOG_CONTENT_Y = 776
# 日志文字颜色(BGR)：失败红/警告橙/正常绿/默认深灰(用户2026-09-09:失败类日志红字,如上梯失败)
LOG_RED = (0, 0, 220)
LOG_WARN = (0, 140, 230)
LOG_OK = (0, 150, 0)

# === 已绑窗口下拉 ===
UI_BOUND_X = 31
UI_BOUND_Y = 777
UI_BOUND_W = 114
UI_BOUND_H = 24

# === 人物特征下拉面板 ===
CHAR_DD_X = 54
CHAR_DD_W = 180
CHAR_DD_SCROLL_W = 22
CHAR_DD_ITEM_H = 26
CHAR_DD_VISIBLE = 5
CHAR_DD_ITEMS = 10
CHAR_DD_FEAT_PER_PAGE = 4
YELLOW_H_LOW = 20  # 黄色H下限
YELLOW_H_HIGH = 35  # 黄色H上限（收紧，排除偏橙/偏绿的噪声）
YELLOW_S_LOW = 100  # 饱和度下限（从80提高到100，排除淡黄噪声）
YELLOW_V_LOW = 180  # 亮度下限（从150提高到180，人物光点很亮，排除偏暗黄色）

VK_F4 = 0x73
VK_F5 = 0x74
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78
VK_F10 = 0x79
VK_F11 = 0x7A  # 坐标测量热键
VK_F12 = 0x7B

# 游戏控制按键（冒险岛默认，可根据实际设置调整）
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_UP = 0x26
VK_DOWN = 0x28
VK_JUMP = 0x20   # Space
VK_ATTACK = 0x11  # Ctrl

DATA_DIR = os.path.join(app_dir(), "data")
os.makedirs(DATA_DIR, exist_ok=True)
REGION_FILE = os.path.join(DATA_DIR, "minimap_region.json")
ROUTE_CONFIG_FILE = os.path.join(DATA_DIR, "route_config.json")
PLANS_FILE = os.path.join(DATA_DIR, "plans.json")  # 方案索引（地图分组+方案列表）
BLUE_BOX_FILE = os.path.join(DATA_DIR, "blue_box_config.json")  # 蓝色框(一屏范围在小地图上的对应尺寸)校准配置

# === 人物特征模板 ===
CHAR_TEMPLATE_DIR = os.path.join(DATA_DIR, "char_templates")
os.makedirs(CHAR_TEMPLATE_DIR, exist_ok=True)
CHAR_TEMPLATE_META = os.path.join(CHAR_TEMPLATE_DIR, "meta.json")
CHAR_MAX_TEMPLATES = 10
CHAR_MATCH_THRESHOLD = 0.70  # 全图人物匹配阈值(用户2026-09-05：0.75太高角色只到~0.7被拒→降回0.70)
# 人物特征颜色（暖色系，BGR格式，10种不重复）
CHAR_FEATURE_COLORS = [
    (0, 0, 255),      # 红
    (0, 165, 255),    # 橙
    (0, 255, 255),    # 黄
    (203, 192, 255),  # 粉
    (255, 0, 255),    # 紫
    (128, 0, 128),    # 洋红
    (0, 0, 139),      # 深红
    (0, 140, 255),    # 深橙
    (0, 215, 255),    # 金黄
    (180, 105, 255),  # 浅粉
]

# === 怪物特征模板（手动添加怪物特征，和YOLO合并显示小地图紫点） ===
MONSTER_TEMPLATE_DIR = os.path.join(DATA_DIR, "monster_templates")
os.makedirs(MONSTER_TEMPLATE_DIR, exist_ok=True)
MONSTER_TEMPLATE_META = os.path.join(MONSTER_TEMPLATE_DIR, "meta.json")
MONSTER_MAX_TEMPLATES = 10
MONSTER_MATCH_THRESHOLD = 0.70  # 阈值0.70（和人物一样），匹配更稳定减少闪烁，移动时跟手不延迟

# === 打怪搜索范围常量 ===
GAME_W = 1276             # 游戏固定窗口宽度(用户2026-09-06游戏更新后定稿：全窗口写死1276x749，不区分客户区，不要运行时动态识别，避免窗口一变尺寸就漂移/识别变化)
GAME_H = 749              # 游戏固定窗口高度(GetWindowRect全窗口含标题栏，用户2026-09-06更新后=1276x749；旧1290x756已废弃)
COMBAT_FAR_RANGE = 1300   # 同平台寻怪X范围·默认值(用户2026-09-07：800→1300，左右各1300)；可在fight页"寻怪范围"弹窗自定义far_range_x
FAR_RANGE_Y_UP_DEFAULT = 150   # 寻怪Y上方范围默认(怪脚Y比人物Y小多少算上方可检测)
FAR_RANGE_Y_DOWN_DEFAULT = 150 # 寻怪Y下方范围默认(怪脚Y比人物Y大多少算下方可检测)
DETECT_PERIOD_MS = 150    # 后台检测线程·忙时周期(2026-09-07：配合攻击后130ms判死,250→150)：打怪/锁敌时150ms≈6.7Hz,保证出手后130ms内能拿到一帧新画面判血条/伤害；重活YOLO已限2Hz、血条3Hz,单轮很轻；无怪仍走DETECT_IDLE_MS=700省电
YOLO_FAST_S = 0.25        # YOLO全图扫描·找怪档(用户2026-09-07)：无锁/锁的是范围外怪正在寻敌时4Hz,打完一只/发现新怪更快(治"换锁等几秒")
YOLO_SLOW_S = 0.50        # YOLO全图扫描·战斗档：已锁范围内怪正在打时降到2Hz(近身靠技能范围怪模板维持),省YOLO最大头
BARS_SCAN_S = 0.30        # 怪物血条扫描节流：和怪表(3Hz)对齐,避免怪表没更新的空轮重复扫同一批ROI(血条是检测线程第二大头)
POST_STRIKE_CHECK_MS = 130 # 攻击后反馈检测窗口(用户2026-09-07：250→130)：首次出手满130ms后看血条/伤害判"打死没/是不是空怪";另须拿到出手之后的新帧才判,避免用出手前旧帧误丢真怪
MOVE_STALL_CHECK_MS = 1000 # 位移检测(用户2026-09-07定稿)：下令左/右移动后每这么多ms比对一次是否真移动；1秒还在原地=卡住→按住方向+跳解卡(原5000太慢)
MOVE_MIN_DX = 10          # (旧屏幕特征判定位移,已弃用保留) 屏幕X像素门槛
MOVE_MIN_MAP_DX = 2       # 位移检测·小地图版(用户2026-09-07)：直接用光点X判定更准,1秒窗口内光点朝移动方向走≥2个小地图单位=真在动(约合20屏幕px,抗光点抖动)
MOVE_STALL_ABORT = 2      # 防卡死(用户2026-09-07)：连续卡住这么多次(1s解卡+再1s仍不动≈2秒)→这一侧地形过不去,放弃该侧怪(3秒不重锁)改锁另一侧
# === 移动监管线 watchdog 常量(用户2026-09-09三线模型；v1只监测打行为日志,不挂起主线、不发键) ===
WD_POLL_MS = 100          # 监管线程轮询间隔
WD_X_CHECK_MS = 1000      # X(水平)停滞窗口：镜头横向基本不滚,下令水平移动后满1秒做一次窗口判定
WD_Y_SEG_MS = 1500        # Y(垂直)端点比对段长：镜头会随人物上下滚动,中间帧光点相对Y会"假不动/回弹",
# 故Y不做相邻帧精细比较,只比每段【段首~段尾】两个端点、段内不管(用户:只测开始和结束两个点,中间不管);段长给宽到1.5s留镜头裕量
WD_MIN_MAP_D = 2          # 端点/窗口内光点朝目标方向至少变化这么多个小地图单位才算"真在动"(抗抖动,同MOVE_MIN_MAP_DX)
WD_IDLE_AUDIT_MS = 500    # 无移动意图时的按键残留/抢键仲裁巡检间隔
WD_SEG_MIN_HITS = 2       # 一个判定段内至少几次采样到"真实运动"(三块背景同动 或 光点同向位移)才算在动,否则段末判卡住
WD_LOG_DEDUP_MS = 1500    # 监管同类日志去重间隔,避免刷屏
# 监管线专用背景运动采样区(用户2026-09-09截图指定)：不能放人物边上(旁边怪动会误判),选远离人物/怪的纯背景。
# 只用【上、右】两块,两块画面同时帧差超阈=人物在正确移动(镜头在滚);单块变化可能是怪/特效/绳索摆动,忽略。整窗坐标(含标题栏)。
WD_BG_REGIONS = [
    {"x": 498, "y": 42, "w": 52, "h": 18},    # 上:顶部天空/吊钩横向带(纯背景无怪,横滚时吊钩/云扫过)
    {"x": 1200, "y": 384, "w": 58, "h": 18},  # 右:右侧岩壁(纹理丰富,横/纵滚变化明显,远离人物与怪群)
]
WD_BG_MOTION_MIN = 2      # 上+右两块必须同时在动,才判定背景在滚=人物真移动(用户:二处同时变化才算)
WD_JUMP_GATE_MS = 1000    # 跳后静默(用户2026-09-09定最简单方案)：起跳后1秒内不做背景帧差(跳跃空中镜头会上下抖,1秒必已落地),落地后再接着对比,不搞离地/落地状态机

# === 梯子特征模板（YOLO前过渡方案，用户2026-09-09定稿：随方案永久存盘，仅上梯近距在主窗口匹配梯子竖条X，辅助精准起跳）===
LADDER_TPL_MAX = 10            # 每方案最多梯子模板数
LADDER_TPL_DEFAULT_SIM = 0.70  # 梯子模板匹配默认相似度
LADDER_TPL_ENTER_PX = 5        # 小地图|人-梯X差|≤此值才从"小地图粗导航"切到"主窗口梯子模板精对齐"
LADDER_TPL_X_RANGE = 150       # 主窗口搜索X半宽：只朝目标怪所在那一侧扩150(怪在右只搜右/在左只搜左)
LADDER_TPL_Y_NEAR = 20         # Y近人物侧留白(避开人物本体)
LADDER_TPL_Y_FAR = 150         # Y远侧搜索距离(上行搜头顶/下行搜脚下)
LADDER_SCR_NUDGE = 6           # 屏幕|人-梯X差|>此值=按住朝梯走,≤此值=点动微调
LADDER_SCR_TOL = 2             # 屏幕|人-梯X差|≤此值=对齐
LADDER_SCR_HOLD_FRAMES = 2     # 屏幕对齐连续多少帧才原地直跳
LADDER_SCR_STALL_MS = 700      # 屏幕点动后多久没靠近=想动没动
LADDER_SCR_STALL_MAX = 3       # 想动没动解卡上限,超过回主线重选不死磕

# === 爬梯登顶·绑定人物基点的三背景点（用户2026-09-09定稿，替代小地图Y对梯端/人怪同Y对比）===
# 三个采样小框固定在人物基点的 右上/右下/左下，随人物一起移动，测"人物相对地图背景有没有动"，与镜头如何滚动无关。
# 静止判据(用户定稿,抗怪物/特效干扰)：三个有效点里【只要有一个确认不动】就算人物本帧静止；只有三个点全部在动才算还在爬。
# 连续静止 CLIMB_STILL_MS=一直按↑却上不去、停在顶=登顶。收边clamp保证人物贴屏幕边时点也不出屏(收回贴人物另一侧)，
# 三点强制分离+尽量躲开怪物框，避免叠一处/同时罩到同一只怪，保证总有一个干净背景点可判静止。
CLIMB_BOX_RADIUS = 150         # 采样点中心距人物基点的理想距离
CLIMB_BOX_SIZE = 26            # 采样框边长(小框,尽量纯背景)
CLIMB_BOX_SEP_MIN = 60         # 任意两采样点中心最小间距(曼哈顿距离,防收回后叠一处)
CLIMB_STILL_MS = 1000          # 存在静止点连续多久=登顶
CLIMB_TOTAL_TIMEOUT_MS = 12000 # 爬梯总超时兜底(防异常永久卡),到点按到顶收尾
# 【用户2026-09-09定稿】跳高打（怪比人高时，屏幕像素PX）——区间在"技能Y范围"弹窗最下一行两个框自定义：
#   下限~上限(如25~180)两个都填才启用：怪比人高落在[下限,上限]内 且 X差≤300 → 直接朝怪"走-跳-打"，每500~600ms跳一次(不连跳)，
#   两次跳之间落地空档能打到就站定攻击，【不去找梯子】；比上限还高(>上限)的怪不跳不打，对接正常锁定流程——锁到别的层就走梯子/瞬移上去打；
#   比下限还低(<下限)=当平地正常走打。两个框任一留空=不启用跳高打，高处怪一律走正常跨层(梯子/瞬移)。
#   射程外追怪段只朝怪正常走、不跳（用户：不在300px内不用跳）。跳打出手一次后无血条无伤害=当前位置够不着→放弃这只、降级走梯子/瞬移。
# 用户2026-09-09：不做预验证/二次验证(那会和"重锁→还打不到→再验证"形成死区)；打不打得到以"出手后有无血条/伤害数字"为准。
SLOPE_JUMP_X_MAX = 300     # 跳高打·旧水平距离上限(已弃用:用户2026-09-09改为X差≤面板技能射程atk1_distance才跳,战法一致;常量保留备用)
SLOPE_JUMP_GAP_MIN = 500   # 两次跳间隔下限ms（用户：不要一直跳，隔500~600ms跳一次）
SLOPE_JUMP_GAP_MAX = 600   # 两次跳间隔上限ms
SLOPE_HIT_DELAY_MS = 250   # 战士跳打延迟：起跳后250ms人物抬到高位=进入跳打窗口,在空中放技能打高处怪(用户2026-09-09：150→250)
SLOPE_AIR_MS = 360         # 一次跳跃的空中时长ms：战士跳打窗口=[跳后250ms, 跳后360ms落地]，窗口内允许空中放技能
SLOPE_MAGE_STAND_MS = 200  # 法师模式落地站定窗ms：法师空中放不出技能,跳后360ms落地起站定200ms放技能(走-跳-落地放循环,用户2026-09-09)
CHAR_EDGE_MARGIN = 45     # 地图左右边缘区：人物脚X距画面边≤此值且特征匹配丢失=贴边,钳在边缘并标stale(不误判防卡),等全图重定位
GREEN_SLOPE_LOOK = 45     # 录制绿线坡度前视窗口(小地图px,用户2026-09-07补充)：沿移动方向看前方45个小地图单位的绿线起伏(约合450屏幕px)
GREEN_SLOPE_MIN = 6       # 绿线Y波动>6px才算坡(用户口径)：低向高(上坡)跑+跳,高向低(下坡)只走不跳；≤6当平地正常走
DETECT_IDLE_MS = 700      # 自适应降频(2026-09-07二档：300→500→700)：无怪/非战斗700ms≈1.4Hz省电；见到怪0.4s内回到DETECT_PERIOD_MS(250)跟手
LAYER_Y_GAP = 150         # 用户2026-09-05：怪脚Y与人物Y差≤150px=同平台怪（超150=跨层/不同平台）；简单直接不靠绿线
ATTACK_Y_UP = 60         # 打怪Y范围·向上：怪比人物高最多60px(人物上方+60内可直打；>60够不着→走近)。用户2026-09-06：80→60
ATTACK_Y_DOWN = 30       # 打怪Y范围·向下：怪比人物低最多30px(人物下方-30内可直打；>30够不着→走近)
AOE_Y_UP = 60            # 群攻Y范围·向上(用户2026-09-07独立于主攻,默认与主攻一致-60)：群攻只数Y在[-上,+下]内的怪,可在Y弹窗改
AOE_Y_DOWN = 30          # 群攻Y范围·向下(默认+30,用户2026-09-07)：下层差太多打不到的怪不许凑数触发群攻
# === 跨层选梯/爬梯常量（2026-09-07跨层改造，2026-09-09选梯严格重合定稿）===
LADDER_REACH_HEIGHT = 15   # 选梯·下端直跳够得着：人物比梯子下端y_bottom低不超过此值=一个直跳能抓到梯子(用户定稿默认15)
LADDER_END_MATCH_TOL = 1    # 选梯·梯子连接端(上行顶端/下行底端)必须和目标怪所在层Y重合的容差(小地图px,用户2026-09-09定稿:
# 必须重合、最多±1,差多了就是通向别的层会误判(在错梯下空跳);一个台子最多两个梯相连,相连梯顶端Y和怪重合,合格梯里再按离怪X最近选
LADDER_TOP_ARRIVE_TOL = 2  # 爬梯到顶验证(用户2026-09-09定稿)：必须光点中心与梯子顶端真正重合才算到顶,容差只留2px防抖；
# 且用"到达/越过"单向判定(上行 py<=y_top+2),人还在顶端下方(差>2)绝不判到顶——旧版abs≤8会提前8px松手导致没翻上平台就掉下
LADDER_GRAB_UP_TOL = 2       # 抓梯成功阈值(镜头滚动原理·用户2026-09-09)：光点Y相对【起跳前站地基准Y】变小≥此值=抓住；只比动作前稳态,不做相邻帧比较
LADDER_GRAB_WINDOW_MS = 700  # 抓梯检测窗口(按↑后ms)：窗口内任一帧观测到Y变小即锁存成功并一直按↑；走到窗口上限全程没变小才判真没抓住(防镜头滚动期中间帧回弹误判)
# === 梯子水平对齐·精细点动(用户2026-09-09定稿)：远距正常走,进3px内才1~2px点动挪到重合,关键动作(直跳)必须过准入标准 ===
LADDER_ALIGN_FINE = 3        # |小地图X差|≤3进入精细点动区(>3仍正常按住方向走,像人不磨叽)
LADDER_ALIGN_TOL = 1         # 直跳准入硬标准:|X差|必须≤1(用户:小于2、不等于2;杜绝2.x边界没对齐就跳)
LADDER_ALIGN_HOLD_FRAMES = 2 # 连续2帧都≤1才算停稳对准(防光点抖动/滑过误判),达到才允许原地直跳
LADDER_NUDGE_KEY_MS = 45     # 点动一次方向键保持ms(非阻塞跨帧抬起,真机调到小地图每次挪1~2px)
LADDER_NUDGE_CYCLE_MS = 200  # 点动节拍:每200ms最多点一下,节拍间隔用来观测"到底动没动"
LADDER_ALIGN_STALL_MS = 600  # 精细区"指令朝梯走但X一直没靠近"持续这么久=想动没动(卡住)
LADDER_ALIGN_STALL_MAX = 3   # 卡住解卡尝试上限:每次先全松再干净重点,超过仍不动=这把梯对不齐,回主线重选/打怪不死磕
LADDER_VERT_FAIL_LIMIT = 2    # 原地直跳抓梯连续失败上限(用户2026-09-09)：<2对齐直跳连续2次没抓住→退开120~150屏幕px回主线打怪,打完再自动上梯(固定点6跑跳失败不计入)
LADDER_BACKOFF_MIN = 120      # 直跳2次失败后远离梯子的屏幕位移下限(px)
LADDER_BACKOFF_MAX = 150      # 上限(px)：退开120~150再正常选梯上
LADDER_BACKOFF_TIMEOUT_MS = 4000  # 退开兜底超时：屏幕定位异常/被挡住时最多横走4秒强制结束,避免一直走
JUMP_DOWN_LAND_STABLE_MS = 250   # 下跳落地判定(用户2026-09-09)：开始下落后光点Y连续250ms不再增大(≤3px抖动)=落到台子
JUMP_DOWN_LAND_TIMEOUT_MS = 1500 # 下跳总兜底：补跳后最多1500ms强制按落地收尾,防大落差一直观测不到稳定而干等
JUMP_DOWN_HOLD_BEFORE_JUMP_MS = 200 # 下跳时序(用户2026-09-09定)：先松攻击/左右→按住↓保持200ms让游戏采到"向下"→再按跳→确认下落后松↓
LADDER_DEL_X_TOL = 6          # 梯删除点选命中：点击点与梯子X差≤6(小地图原始分辨率)且Y落在线段内=删这条
LADDER_DEL_Y_TOL = 4
SLOPE_WALK_Y_DIFF = 60    # 斜坡可走判定：两平台小地图Y差≤60(约一层内)且X范围重叠=坡道连着→走台子不走梯子
# === 掉台归位·独占辅助线(用户2026-09-09)：单台锁定时持续监测光点在不在该台折线上,连续离开超过防抖时长=掉下去 ===
FALL_OFF_DEBOUNCE_MS = 500   # 光点离开home台连续达到500ms才判掉台(正常跳跃/瞬离不触发,真掉台是持续离开)
FALL_ON_TOL = 10             # 光点到home台折线距离≤此值=在台上(与_get_current_platform同口径)
# === 卡住解卡·独占辅助线(用户2026-09-09)：向前走不动时关主线,独占"向前+跳"试X变化,脱困再开主线;连试上限仍不动=放弃当前目标 ===
UNBLOCK_MAX_TRIES = 3        # 解卡最多连试次数,超过=地形真过不去,放弃当前锁定回主线重锁
CHAR_ROI_THRESHOLD = 0.70  # 人物匹配阈值(用户2026-09-05：0.7是合格匹配、0.4是垃圾无关；卡0.70把0.4垃圾拒掉，只认0.7+真角色)
# === 投票式空怪过滤（用户2026-09-05定稿：锁怪前识别环节，同一位置连续识别N次不动=假怪，临时排除再恢复）===
STATIC_VOTE_N = 10           # 同一位置连续识别N次仍不动 → 判假怪临时排除（用户2026-09-06定稿：连续10帧同位置=放弃识别）
STATIC_EXCLUDE_MS = 3000     # 临时排除时长（3秒），时间到恢复；若还不动再重新投票排除（用户2026-09-06：3秒）
STATIC_MOVE_TOL = 35         # 判定"同一位置"的容差px（中心移动>此值=动了，重置投票计数）
# === 检测稳定化（用户2026-09-05：YOLO对同一只怪会闪检[有时检出有时没检出]，把近期见过的怪保留，单帧漏检不清目标）===
MON_DETECT_KEEP_MIN = 800   # 检测稳定化：每只怪"最后一次被检测到"起保留时长下限ms(怪会走，太久就攻击旧位置空打)
MON_DETECT_KEEP_MAX = 1200  # 上限1200ms(用户2026-09-05：最多记1.2秒，再多怪走了会空打)
# 怪物特征颜色（冷色系，BGR格式，10种不重复，和人物颜色分开）
MONSTER_FEATURE_COLORS = [
    (255, 0, 0),      # 蓝
    (0, 255, 0),      # 绿
    (255, 255, 0),    # 青
    (255, 255, 128),  # 浅蓝
    (128, 255, 128),  # 浅绿
    (139, 0, 0),      # 深蓝
    (0, 139, 0),      # 深绿
    (139, 139, 0),    # 深青
    (255, 128, 0),    # 湖蓝
    (0, 255, 128),    # 春绿
]

# === 人物定位框（蒙板绿色大框，以人物黄点为中心） ===
PLAYER_BOX_W = 150  # 人物定位框宽度（先用大尺寸框住，精准后再改小）
PLAYER_BOX_H = 190  # 人物定位框高度

# === 绿框钳制（限制小地图绿框整体移动范围，不重叠窗口边缘） ===
BOX_CLAMP_LEFT = 4    # 绿框左边距窗口左边缘最小px
BOX_CLAMP_RIGHT = 5   # 绿框右边距窗口右边缘最小px
BOX_CLAMP_TOP = 3     # 绿框上边距窗口上边缘最小px
BOX_CLAMP_BOTTOM = 3  # 绿框下边距窗口下边缘最小px

# === 镜头死区检测（三个背景框，帧差对比检测镜头是否在动） ===
# 三个默认检测点（整个窗口坐标，含标题栏+边框）：左下/左上/右中
BG_DETECT_DEFAULT_REGIONS = [
    {"x": 35, "y": 744, "w": 40, "h": 39},    # 左下
    {"x": 170, "y": 43, "w": 46, "h": 23},    # 左上
    {"x": 1320, "y": 409, "w": 43, "h": 28},  # 右中
]
BG_DIFF_THRESHOLD = 5.0       # 帧差均值阈值，超过此值判定该区域在动（调小更灵敏，镜头动了更容易检测到）
BG_MOTION_MIN_REGIONS = 3     # 至少几个区域在动才判定镜头在跟随
BG_STILL_FRAMES_TO_DEADZONE = 3  # 连续几帧不动才切到死区状态
BG_DETECT_REGIONS_FILE = os.path.join(DATA_DIR, "bg_detect_regions.json")  # 检测框位置持久化

# === 打怪/药品 输入框配置 ===
INPUT_CONFIG_FILE = os.path.join(DATA_DIR, "fight_potion_config.json")
YOLO_CONFIG_FILE = os.path.join(DATA_DIR, "yolo_config.json")
INPUT_FONT = cv2.FONT_HERSHEY_SIMPLEX
INPUT_FONT_SCALE = 0.5 * UI_W / 330.0
INPUT_FONT_THICKNESS = 1
INPUT_TEXT_COLOR = (40, 40, 40)  # BGR 深色文字
INPUT_FOCUS_COLOR = (0, 170, 255)  # BGR 橙色聚焦边框

# 打怪页字段定义 (x, y, w, h, type, id) — 坐标由新背景(461x900)白色方框精确检测
# type: "key"=按键录入, "num"=数字录入
# 坐标由新背景(ui_tab_fight.png, 462x900)白色输入框精确检测
FIGHT_FIELDS = [
    # 主攻
    (100, 155, 54, 26, "key", "atk1_key"),
    (211, 154, 108, 30, "num", "atk1_interval"),
    (371, 154, 74, 29, "num", "atk1_distance"),
    # 群攻
    (100, 198, 54, 26, "key", "aoe_key"),
    (211, 196, 110, 29, "num", "aoe_interval"),
    (371, 195, 74, 29, "num", "aoe_distance"),
    # 跳跃 + 技能随机时间
    (100, 251, 54, 26, "key", "jump_key"),
    (306, 242, 138, 27, "num", "skill_random"),
    # 瞬移(2026-09-06改版)：原"瞬移键/瞬移距离"两个录入框已取消，改由"瞬移设置"按钮(BTN_TP_SETTING)弹窗设X/Y瞬移距离；
    # 瞬移技能键 teleport_key 不再在本页录入，沿用配置文件已存值(如z)；X或Y任一>0且技能键存在才瞬移，都空=不瞬移
    # BUFF 1-6（技能/冷却/后摇）
    (95, 432, 67, 29, "key", "buff1_key"),
    (207, 432, 117, 29, "num", "buff1_cd"),
    (373, 433, 70, 29, "num", "buff1_delay"),
    (95, 482, 67, 29, "key", "buff2_key"),
    (207, 482, 117, 29, "num", "buff2_cd"),
    (373, 482, 70, 29, "num", "buff2_delay"),
    (95, 527, 67, 29, "key", "buff3_key"),
    (207, 527, 117, 29, "num", "buff3_cd"),
    (373, 526, 70, 29, "num", "buff3_delay"),
    (95, 572, 67, 29, "key", "buff4_key"),
    (207, 572, 117, 29, "num", "buff4_cd"),
    (373, 572, 70, 29, "num", "buff4_delay"),
    (95, 616, 67, 29, "key", "buff5_key"),
    (207, 616, 117, 29, "num", "buff5_cd"),
    (373, 615, 70, 29, "num", "buff5_delay"),
    (95, 659, 67, 29, "key", "buff6_key"),
    (207, 659, 117, 29, "num", "buff6_cd"),
    (373, 659, 70, 29, "num", "buff6_delay"),
    # BUFF技能随机时间
    (229, 706, 182, 28, "num", "buff_random"),
]

# 路线页字段定义 — 人物X/Y偏移（点击范围加大，覆盖偏移标签下半部分）
ROUTE_FIELDS = [
    (OFFSET_X_CLICK[0], OFFSET_X_CLICK[1], OFFSET_X_CLICK[2], OFFSET_X_CLICK[3], "num", "char_x_offset"),
    (OFFSET_Y_CLICK[0], OFFSET_Y_CLICK[1], OFFSET_Y_CLICK[2], OFFSET_Y_CLICK[3], "num", "char_y_offset"),
]

# 药品页字段定义 (x, y, w, h, type, id) — 坐标由新背景(461x900)白色方框精确检测
POTION_FIELDS = [
    # Hp / Mp / 宠物食
    (101, 174, 119, 43, "key", "hp_key"),
    (314, 177, 124, 37, "num", "hp_value"),
    (101, 226, 119, 43, "key", "mp_key"),
    (314, 229, 124, 38, "num", "mp_value"),
    (101, 286, 119, 43, "key", "pet_key"),
    (314, 287, 124, 38, "num", "pet_cd"),
    # 1-5按键（冷却框加宽）
    (102, 361, 105, 43, "key", "pot1_key"),
    (268, 364, 175, 38, "num", "pot1_cd"),
    (102, 420, 105, 44, "key", "pot2_key"),
    (268, 424, 175, 37, "num", "pot2_cd"),
    (102, 480, 105, 41, "key", "pot3_key"),
    (268, 482, 175, 37, "num", "pot3_cd"),
    (102, 539, 105, 41, "key", "pot4_key"),
    (268, 541, 175, 38, "num", "pot4_cd"),
    (102, 600, 105, 41, "key", "pot5_key"),
    (268, 601, 175, 38, "num", "pot5_cd"),
    # 药品技能随机时间
    (213, 673, 218, 31, "num", "potion_random"),
]

# 按钮颜色 (BGR)
BTN_GREEN = (0, 165, 0)
BTN_BLUE = (210, 130, 0)
BTN_BLACK = (48, 48, 48)
BTN_ORANGE = (0, 135, 225)
BTN_WHITE = (255, 255, 255)

# 完整虚拟键码→键名映射（用于GetAsyncKeyState按键捕获）
VK_TO_NAME = {
    0x08: "backspace", 0x09: "tab", 0x0C: "clear", 0x0D: "enter",
    0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x13: "pause",
    0x14: "capslock", 0x1B: "esc", 0x20: "space",
    0x21: "pgup", 0x22: "pgdn", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "printscreen", 0x2D: "insert", 0x2E: "delete",
    0x30: "0", 0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4",
    0x35: "5", 0x36: "6", 0x37: "7", 0x38: "8", 0x39: "9",
    0x41: "a", 0x42: "b", 0x43: "c", 0x44: "d", 0x45: "e",
    0x46: "f", 0x47: "g", 0x48: "h", 0x49: "i", 0x4A: "j",
    0x4B: "k", 0x4C: "l", 0x4D: "m", 0x4E: "n", 0x4F: "o",
    0x50: "p", 0x51: "q", 0x52: "r", 0x53: "s", 0x54: "t",
    0x55: "u", 0x56: "v", 0x57: "w", 0x58: "x", 0x59: "y", 0x5A: "z",
    0x5B: "lwin", 0x5C: "rwin",
    0x60: "num0", 0x61: "num1", 0x62: "num2", 0x63: "num3",
    0x64: "num4", 0x65: "num5", 0x66: "num6", 0x67: "num7",
    0x68: "num8", 0x69: "num9",
    0x6A: "num*", 0x6B: "num+", 0x6C: "numsep", 0x6D: "num-",
    0x6E: "num.", 0x6F: "num/",
    0x70: "f1", 0x71: "f2", 0x72: "f3", 0x73: "f4", 0x74: "f5",
    0x75: "f6", 0x76: "f7", 0x77: "f8", 0x78: "f9", 0x79: "f10",
    0x7A: "f11", 0x7B: "f12",
    0x90: "numlock", 0x91: "scrolllock",
    0xA0: "lshift", 0xA1: "rshift", 0xA2: "lctrl", 0xA3: "rctrl",
    0xA4: "lalt", 0xA5: "ralt",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".",
    0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}
# 轮询捕获时检测的键码列表（按优先级排序，修饰键放后面避免误触）
VK_POLL_LIST = (
    [0x70+i for i in range(4)] +  # F1-F4 (F5-F12留作热键不捕获)
    [0x30+i for i in range(10)] +  # 0-9
    [0x41+i for i in range(26)] +  # A-Z
    [0x60+i for i in range(10)] +  # num0-9
    [0x20, 0x0D, 0x09] +  # space enter tab (backspace/esc单独处理不捕获)
    [0x21, 0x22, 0x23, 0x24, 0x2D, 0x2E] +  # pgup pgdn end home insert delete
    # 方向键/ScrollLock/Pause/PrintScreen 不捕获，避免冲突
    [0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE] +  # 符号
    [0x6A, 0x6B, 0x6D, 0x6E, 0x6F] +  # 小键盘运算
    [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5]  # 左右修饰键
)

# 按钮布局：(文字, 背景色, 是否有下拉)
BTN_ROW1 = [
    ("平台", BTN_GREEN, False),
    ("梯子", BTN_BLUE, False),
    ("保存", BTN_BLACK, True),
    ("方案", BTN_ORANGE, True),
]
BTN_ROW2 = [
    ("清除", BTN_GREEN, False),   # 清平台
    ("清除", BTN_BLUE, False),    # 清梯子
    ("模式", BTN_BLACK, True),
    ("清除", BTN_ORANGE, True),   # 清方案
]


def route_files(route_id):
    """返回指定方案的平台文件和梯子文件路径（route_id为数字1~100，文件名route_001格式）"""
    return (
        os.path.join(DATA_DIR, "route_%03d_platforms.json" % route_id),
        os.path.join(DATA_DIR, "route_%03d_ladders.json" % route_id)
    )

def route_files_by_id(plan_id):
    """通过plan_id字符串（如'route_001'）返回文件路径"""
    num = int(plan_id.split("_")[1])
    return route_files(num)

def plan_id_to_num(plan_id):
    """route_001 → 1"""
    return int(plan_id.split("_")[1])

def num_to_plan_id(num):
    """1 → route_001"""
    return "route_%03d" % num

COLOR_PLATFORM = (0, 255, 0)
COLOR_LADDER = (255, 100, 0)
COLOR_RECORDING = (0, 0, 255)
COLOR_PLAYER = (0, 255, 255)

user32 = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = ctypes.c_bool
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetParent.argtypes = [ctypes.c_void_p]
user32.GetParent.restype = ctypes.c_void_p


def key_pressed(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class GlobalHotkeyListener:
    """低级键盘钩子全局热键（主线程版），绕过 UIPI，游戏前台也能捕获"""
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    def __init__(self, vk_list):
        self.vk_list = set(vk_list)
        self.events = queue.Queue()
        self._hook = None
        self._hook_proc_ref = None

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
            vk = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_ulong))[0] & 0xFF
            if vk in self.vk_list:
                self.events.put(vk)
        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def install(self):
        """在主线程安装钩子，返回是否成功"""
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)
        self._hook_proc_ref = HOOKPROC(self._hook_proc)
        kernel32 = ctypes.windll.kernel32
        self._hook = user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._hook_proc_ref,
            kernel32.GetModuleHandleW(None), 0
        )
        return bool(self._hook)

    def pump(self):
        """每帧调用，处理钩子消息（必须在安装钩子的线程调用）"""
        msg = ctypes.c_void_p()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
            if msg.value == 0x0012:  # WM_QUIT
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def uninstall(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def get_events(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events


class GlobalMouseListener:
    """低级鼠标钩子（主线程版），全局捕获鼠标事件，游戏前台也能捕获"""
    WH_MOUSE_LL = 14
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_MOUSEMOVE = 0x0200

    def __init__(self):
        self.events = queue.Queue()
        self._hook = None
        self._hook_proc_ref = None

    def _hook_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (self.WM_LBUTTONDOWN, self.WM_LBUTTONUP, self.WM_MOUSEMOVE):
            ms = ctypes.cast(lParam, ctypes.POINTER(POINT))[0]
            self.events.put((wParam, ms.x, ms.y))
        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def install(self):
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)
        self._hook_proc_ref = HOOKPROC(self._hook_proc)
        kernel32 = ctypes.windll.kernel32
        self._hook = user32.SetWindowsHookExW(
            self.WH_MOUSE_LL, self._hook_proc_ref,
            kernel32.GetModuleHandleW(None), 0
        )
        return bool(self._hook)

    def pump(self):
        msg = ctypes.c_void_p()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.value == 0x0012:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def get_events(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events

    def uninstall(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None




class MinimapRouteRecorder:
    def __init__(self):
        self.sct = mss.mss()
        self.map_area_rect = None
        try:
            self.hwnd = _find_game_window()
            self._hwnd_auto = bool(self.hwnd)  # 自动绑定=True(句柄失效时看门狗自动重绑)；准星手选=False(不抢用户指定窗口)
            self._hwnd_watch_last = 0.0        # 句柄看门狗上次检查时间(1秒节流,避免频繁EnumWindows)
            if self.hwnd:
                self._update_window_rect()
                self._detect_minimap()  # 恢复原来的自动检测，避免显示窗口变小
                self._save_target_window_size()
                print("[窗口绑定] 自动绑定成功")
                # 启动人物坐标跟踪线程（暂时注释，排查绑定问题）
                # self._start_player_track()
            else:
                print("[警告] 未找到游戏窗口，请用准星拖拽绑定")
                self.hwnd = None
                self.window_rect = None
                self.map_area_rect = None
        except Exception as e:
            print("[窗口绑定] 自动绑定异常:", e)
            self.hwnd = None
            self._hwnd_auto = False
            self._hwnd_watch_last = 0.0
            self.window_rect = None
            self.map_area_rect = None

        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        # 方案系统：地图分组+多方案（最多100地图×每地图10方案）
        self.current_route = 1
        self.route_mode = "手动"
        self.plans_data = {"maps": [], "current_id": "route_001"}  # 方案索引数据
        self._dropdown = None  # 当前展开的下拉菜单: None/"save"/"route"/"mode"/"clear_route"
        # 独立窗口引用
        self._plan_window = None  # 方案管理窗口
        self._char_feature_window = None  # 人物特征管理弹窗
        self._save_window = None  # 保存方案窗口
        self._clear_window = None  # 删除方案窗口
        # 原地打怪归位相关
        self._idle_combat_start_pos = None  # 原地打怪起始屏幕坐标
        self._idle_combat_attack_start = 0  # 开始攻击时间戳
        self._idle_combat_no_damage_duration = 0  # 第一次无伤害时的攻击总时长(秒)
        self._idle_combat_last_turn = 0  # 上次转身时间
        self._idle_combat_turn_interval = 0  # 转身间隔(秒)，在无伤害时长±5秒内随机
        self._idle_combat_no_damage_logged = False  # 是否已提示未勾选方案
        self._route_reelect_time = 0  # 下次重新随机选路线的时间戳
        self._return_fail_count = 0  # 归位失败计数
        self._return_attempt_mode = None  # 当前归位尝试方式: 'jump'/'ladder'/'platform'
        # 【模块B】平台选择：选择在哪个平台上打怪（编号从1开始，空列表=全部平台）
        self._selected_platforms = []  # 选中的平台编号列表，空=全部平台
        self._show_platform_selector = False  # 是否显示平台选择面板
        # 平台选择按钮区域（小地图左上方）
        self._btn_platform_selector = None  # "台子选择"按钮
        self._btn_platform_selector_close = None  # 选择面板关闭按钮
        # 梯删除(用户2026-09-09)：小地图右上角"梯删除"按钮，进入待选后点梯子蓝线删该条(只改内存,保存时落盘)
        self._ladder_delete_mode = False    # 是否处于"点梯子删除"待选状态
        self._btn_ladder_delete = None      # "梯删除"按钮矩形(UI坐标)
        # 【倍率差弹窗】按照弹窗组件实现规范实现
        self._show_scale_dialog = False  # 是否显示倍率差弹窗
        self._scale_dialog_pos = [70, 230]  # 弹窗位置（可移动，拖拽标题栏移动）
        self._scale_dialog_dragging = False  # 是否正在拖拽弹窗
        self._scale_dialog_drag_offset = [0, 0]  # 拖拽时的偏移量
        self._scale_dialog_backup = {}  # 弹窗打开时备份原始值，取消/关闭时恢复（确认才保存）
        # 弹窗内控件位置（必须初始化，否则点击检测时None会崩溃）
        self._dlg_scale_x_input = (0, 0, 0, 0)  # X偏差输入框位置
        self._dlg_scale_y_input = (0, 0, 0, 0)  # Y偏差输入框位置
        self._dlg_scale_ok_btn = (0, 0, 0, 0)  # 确认按钮位置
        self._dlg_scale_cancel_btn = (0, 0, 0, 0)  # 取消按钮位置
        self._dlg_scale_close_btn = (0, 0, 0, 0)  # 右上角关闭按钮X位置
        # 倍率差按钮区域（右上角，对准新背景图上的倍率差按钮）
        self._btn_scale_dialog = (370, 96, 45, 30)  # 倍率差按钮位置
        # 【打怪Y范围弹窗·冒险岛世界2026-09-06】仿倍率差弹窗：灰底白字/标题栏可全屏拖拽/右上角X/确认取消，fight页"Y距离"按钮打开
        self._show_y_dialog = False              # 是否显示打怪Y范围弹窗
        self._y_dialog_pos = [70, 230]           # 弹窗位置（可拖拽）
        self._y_dialog_dragging = False          # 是否拖拽中
        self._y_dialog_drag_offset = [0, 0]      # 拖拽偏移
        self._y_dialog_backup = {}               # 打开时备份，取消/关闭恢复（确认才保存）
        self._dlg_y_up_input = (0, 0, 0, 0)      # 上方打怪范围输入框(主攻)
        self._dlg_y_down_input = (0, 0, 0, 0)    # 下方打怪范围输入框(主攻)
        self._dlg_aoe_y_up_input = (0, 0, 0, 0)  # 群攻上方范围输入框(用户2026-09-07)
        self._dlg_aoe_y_down_input = (0, 0, 0, 0)# 群攻下方范围输入框
        self._dlg_slope_jump_ymin_input = (0, 0, 0, 0)# 跳高打下限(起始)输入框(用户2026-09-09)
        self._dlg_slope_jump_ymax_input = (0, 0, 0, 0)# 跳高打上限输入框(用户2026-09-09)：两框都填才启用,怪比人高在[下限,上限]内走"走-跳-打",留空不启用
        self._dlg_y_ok_btn = (0, 0, 0, 0)
        self._dlg_y_cancel_btn = (0, 0, 0, 0)
        self._dlg_y_close_btn = (0, 0, 0, 0)
        self._y_range_btn_img = None             # Y距离按钮贴图(懒加载,只加载一次)
        # 【瞬移设置弹窗·冒险岛世界2026-09-06】仿Y范围弹窗，"瞬移设置"按钮打开；设X/Y瞬移距离，默认空，X或Y任一有值才瞬移
        self._show_tp_dialog = False
        self._tp_dialog_pos = [70, 230]
        self._tp_dialog_dragging = False
        self._tp_dialog_drag_offset = [0, 0]
        self._tp_dialog_backup = {}
        self._dlg_tp_x_input = (0, 0, 0, 0)       # X瞬移距离(水平追怪)
        self._dlg_tp_y_input = (0, 0, 0, 0)       # Y瞬移距离(垂直上下,空=不垂直瞬移)
        self._dlg_tp_key_input = (0, 0, 0, 0)     # 瞬移按键(点一下→按键盘录入对应键)
        self._dlg_tp_ok_btn = (0, 0, 0, 0)
        self._dlg_tp_cancel_btn = (0, 0, 0, 0)
        self._dlg_tp_close_btn = (0, 0, 0, 0)
        self._tp_setting_btn_img = None          # 瞬移设置按钮贴图(懒加载)
        self._search_range_btn_img = None        # 寻怪范围按钮贴图(懒加载；2026-09-07替换原动作录制占位)
        # 【寻怪范围弹窗·冒险岛世界2026-09-07】仿Y范围弹窗，"寻怪范围"按钮打开；设同平台寻怪X(左右共用,默认1300)/Y(上下共用,默认150)
        self._show_search_dialog = False
        self._search_dialog_pos = [70, 230]
        self._search_dialog_dragging = False
        self._search_dialog_drag_offset = [0, 0]
        self._search_dialog_backup = {}
        self._dlg_search_x_input = (0, 0, 0, 0)   # 寻怪X范围(左右各这么多)
        self._dlg_search_y_up_input = (0, 0, 0, 0)   # 寻怪Y上方范围
        self._dlg_search_y_down_input = (0, 0, 0, 0) # 寻怪Y下方范围
        self._dlg_search_group_chk = (0, 0, 0, 0)  # 群怪优先勾选框(用户2026-09-09)
        self._dlg_search_ok_btn = (0, 0, 0, 0)
        self._dlg_search_cancel_btn = (0, 0, 0, 0)
        self._dlg_search_close_btn = (0, 0, 0, 0)
        self._far_range_y_up = FAR_RANGE_Y_UP_DEFAULT     # 当前上方Y容差
        self._far_range_y_down = FAR_RANGE_Y_DOWN_DEFAULT # 当前下方Y容差
        self._combat_last_h_teleport = 0          # 上次水平瞬移时间(节流,追怪用)
        # 瞬移后人物会合法地大跳变几百px，此时间戳之前跳过ROI直接全图搜、并允许远距同步新位置(治瞬移后点钉原地)
        self._char_relocate_until = 0
        # 【模块B】端点按钮按下特效状态
        self._calib_left_pressed = False
        self._calib_right_pressed = False
        self._calib_top_pressed = False
        self._calib_top_pt = None  # Y轴上端点：(屏幕Y, 小地图Y)
        # 可拖拽准星（窗口绑定用）
        self._crosshair_size = CROSSHAIR_SIZE
        self._crosshair_home = CROSSHAIR_POS
        self._crosshair_pos = self._crosshair_home
        self._drag_crosshair = False
        # pygame透明置顶准星窗口（拖拽时显示，可拖到屏幕任意位置）
        self._crosshair_pygame_window = None  # pygame窗口对象
        self._crosshair_pygame_screen = None  # pygame屏幕对象
        self._crosshair_pygame_hwnd = None  # 准星窗口句柄
        self._crosshair_pygame_inited = False  # pygame是否已初始化
        # 已绑窗口列表
        self._bound_windows = []  # [{hwnd, title}]
        # 自动绑定的窗口加入已绑定列表
        if self.hwnd:
            try:
                length = user32.GetWindowTextLengthW(self.hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(self.hwnd, buf, length + 1)
                title = buf.value or "未知窗口"
                self._bound_windows.append({"hwnd": self.hwnd, "title": title})
            except Exception:
                self._bound_windows.append({"hwnd": self.hwnd, "title": "游戏窗口"})
        self._bound_dropdown = False
        self._char_dropdown = False  # 人物特征下拉面板开关
        self._char_scroll = 0  # 下拉面板当前滚动位置（特征起始索引）
        # 加载路线页UI素材（带透明通道）
        self._ui_run = load_png(resource_path(os.path.join("data", "ui_run.png")))
        self._ui_stop = load_png(resource_path(os.path.join("data", "ui_stop.png")))
        self._ui_platform = load_png(resource_path(os.path.join("data", "ui_platform.png")))
        self._ui_ladder = load_png(resource_path(os.path.join("data", "ui_ladder.png")))
        self._ui_save = load_png(resource_path(os.path.join("data", "ui_save.png")))
        self._ui_plan = load_png(resource_path(os.path.join("data", "ui_plan.png")))
        self._ui_platform_clear = load_png(resource_path(os.path.join("data", "ui_platform_clear.png")))
        self._ui_ladder_clear = load_png(resource_path(os.path.join("data", "ui_ladder_clear.png")))
        self._ui_mode = load_png(resource_path(os.path.join("data", "ui_mode.png")))
        self._ui_plan_clear = load_png(resource_path(os.path.join("data", "ui_plan_clear.png")))
        self._ui_char_btn = load_png(resource_path(os.path.join("data", "ui_char_btn.png")))
        self._ui_offset_label = load_png(resource_path(os.path.join("data", "ui_offset_label.png")))
        self._ui_monster_data = load_png(resource_path(os.path.join("data", "ui_monster_data.png")))
        self._ui_winbind_bg = load_png(resource_path(os.path.join("data", "ui_winbind_bg.png")))
        self._ui_crosshair = load_png(resource_path(os.path.join("data", "ui_crosshair.png")))
        self._ui_log_bg = load_png(resource_path(os.path.join("data", "ui_log_bg.png")))
        self._ui_bound_dropdown = load_png(resource_path(os.path.join("data", "ui_bound_dropdown.png")))
        self._ui_bound_dropdown = load_png(resource_path(os.path.join("data", "ui_bound_dropdown.png")))
        # 工具栏素材（小地图上方）
        self._ui_refresh = load_png(resource_path(os.path.join("data", "ui_refresh.png")))
        self._ui_manual = load_png(resource_path(os.path.join("data", "ui_manual.png")))
        self._ui_plan_toolbar = load_png(resource_path(os.path.join("data", "ui_plan_toolbar.png")))
        # 【模块B】自动校准按钮（同屏三点校准：基点+右800+上500）
        self._ui_calib_auto = load_png(resource_path(os.path.join("data", "ui_calib_auto.png")))
        # MP标签模板（遮挡检测：标签在=没挡住=吃药，标签消失=被挡住=不吃药）
        _mp_label_path = resource_path(os.path.join("data", "templates", "mp_label.png"))
        if os.path.exists(_mp_label_path):
            self._mp_label_template = cv2.imread(_mp_label_path)
            _debug_log("[MP遮挡] 标签模板已加载 %dx%d" % self._mp_label_template.shape[:2])
        else:
            self._mp_label_template = None
            _debug_log("[MP遮挡] 标签模板不存在, 跳过遮挡检测")
        # 血条空白灰色模板（竖框内模板匹配，匹配到=空白=加药）
        _gray_bar_path = resource_path(os.path.join("data", "templates", "gray_bar.png"))
        if os.path.exists(_gray_bar_path):
            self._gray_bar_template = cv2.imread(_gray_bar_path)
            _debug_log("[加药] 灰色空白模板已加载 %dx%d" % self._gray_bar_template.shape[:2])
        else:
            self._gray_bar_template = None
            _debug_log("[加药] 灰色空白模板不存在, 回退颜色检测")
        # 运行日志（新信息在底部，向上流动，可滚动）
        self._runtime_logs = []  # [{time, msg, color}]
        self._log_scroll = 0  # 0=顶部（最新），正数=向下滚动看更旧历史（2026-09-07改为最新在最上）
        self._log_max = 500
        self._rlog_last = {}  # 限频上屏日志各key上次发送时间(ms)，配合_rlog_throttle防每帧刷屏
        # 日志区渲染缓存（2026-09-07 CPU优化：日志内容/滚动位置不变时直接贴缓存图，跳过每帧PIL重绘，实测68ms/秒）
        self._log_cache_key = None  # 上次渲染时的缓存键=(滚动位置,日志总数,可见条目内容)，键相同=画面完全相同
        self._log_cache_img = None  # 上次渲染好的日志区整块图（含底板+文字+滚动条）
        # 双日志切换(用户2026-09-09)：打怪日志=_runtime_logs(找怪/锁定/打怪/换锁/空怪)，行为日志=_behavior_logs(爬梯/跨层/走位/退开/吃药等因果动作)
        self._behavior_logs = []       # 行为日志[{t,msg,color}]
        self._behavior_scroll = 0      # 行为日志滚动位置
        self._log_view = 'combat'      # 当前显示 'combat'=打怪 / 'behavior'=行为，点标题栏按钮切换
        self._last_maint_ts = 0        # 定期维护(日志留5分钟/清调试缓存)时间戳，0=启动即执行一次
        self._log_tab_combat = None    # 【打怪】tab按钮矩形(UI坐标)
        self._log_tab_behavior = None  # 【行为】tab按钮矩形(UI坐标)
        # 人工查看日志(用户2026-09-09)：手动滚轮/拖垂直条/拖水平条时暂停自动跟随最新,停手3秒恢复;底部水平条看长日志右边
        self._log_hscroll = 0          # 打怪日志横向像素偏移(0=最左,正数=左移露出右边)
        self._behavior_hscroll = 0     # 行为日志横向像素偏移
        self._log_manual_t = 0         # 打怪日志最近一次人工滚动时刻(ms),3秒内不被新日志拉回最新
        self._behavior_manual_t = 0    # 行为日志最近一次人工滚动时刻(ms)
        self._dragging_log_hscroll = False  # 正在拖底部水平滚动条
        # 窗口大小固定：绑定时记录目标大小，运行中监控拉回
        self._target_window_size = None  # (width, height) 或 None
        # 蓝色框校准（一屏范围在小地图上的对应尺寸，光点在框内归一化=人物在屏幕内归一化）
        self._blue_box = None  # {"width":w, "height":h} 校准后大小，None=未校准(回退旧方案)
        # 镜头死区检测（三个背景框，帧差对比检测镜头是否在动）
        # === 镜头死区检测状态（31号版本实现：状态机+绿框冻结） ===
        self._bg_regions = [dict(r) for r in BG_DETECT_DEFAULT_REGIONS]  # 三个检测区域
        self._bg_last_frames = [None, None, None]  # 上一帧各区域ROI
        self._bg_diff_values = [0.0, 0.0, 0.0]  # 各区域帧差均值
        self._camera_state = "deadzone"  # 状态机：deadzone(镜头不动)/following(镜头在动)
        self._camera_still_count = 0  # 连续不动帧数
        self._blue_box_deadzone_pos = None  # 进入死区时冻结的绿框位置
        # 注意：蒙板覆盖整个游戏窗口（含标题栏），和lock_screen_from_dot坐标体系一致，不需要_char_box_offset偏移
        self._last_dot_pos = None  # 上一帧光点位置（用于判断光点是否在移动）
        self._bg_dragging = -1  # 右键移动模式：当前选中的检测框索引，-1=无
        self._bg_editing = False  # 检测框编辑状态：True=可拖动，False=正常
        self._bg_motion_count = 0  # 当前帧背景在动的区域数(0~3)，蒙板三框着色用：3=全动绿，否则红
        self._deadzone_delay = 0  # 死区切换延迟计数器：光点停了后等30帧确认镜头真停了再切死区（镜头惯性约0.5秒）
        self._feedforward_strength = 0.0  # 前馈强度系数：启动阶段0→2渐变(约60帧/1秒)，匀速保持2，停止后2→0渐变
        self._follow_frame_count = 0  # 跟随状态持续帧数，用于前馈启动渐变
        self._stop_frame_count = 0  # 人物停止后帧数，用于前馈衰减渐变和延迟切死区
        self._last_rbutton_down = False  # 上一帧右键是否按下（防抖）
        self._load_bg_regions()  # 从配置文件加载检测框位置
        self._calibrating_blue_box = False  # 是否在校准模式
        self._blue_box_corners = []  # 校准中四个角点坐标[(x,y),...]（小地图原始坐标）
        self._selected_corner = -1  # 当前选中的角点索引0-3，-1=未选中
        # 人物特征模板（最多10套）
        self._char_templates = []  # [{id, img(numpy), width, height, created_at}]
        self._load_char_templates()
        # 怪物特征模板（手动添加，和YOLO合并显示小地图紫点，最多10套）
        self._monster_templates = []  # [{id, img, width, height, offset_x, offset_y, direction, created_at}]
        self._last_monster_match_pos = None
        self._last_monster_match_time = 0
        self._load_monster_templates()
        # 打怪/药品输入框状态
        self._field_values = {}  # {field_id: value_string}
        self._focused_field = None  # 当前聚焦的字段id
        # 人物/怪物识别相似度阈值(分开管理，默认0.70，识别不到可手动调低如0.6)——用户2026-09-06
        self._match_sim = {"char": "0.70", "monster": "0.70"}
        self._load_match_sim()
        self._load_input_config()
        # YOLO模型路径（手动选择）
        self._yolo_model_path = None
        self._load_yolo_config()
        # 加载蓝色框校准配置
        self._load_blue_box()
        # HP/MP自动吃药状态
        self._hp_bar = None  # (x, y, w) 扫描线
        self._mp_bar = None
        self._last_hp_pot = 0  # 上次吃红时间戳
        self._last_mp_pot = 0
        self._hp_pot_delay = 1  # 吃红后延时(ms)，1-20毫秒随机
        self._mp_pot_delay = 1
        self._last_pot_check = 0
        self._auto_potion_enabled = True
        self._max_hp = 0  # 检测到的HP上限，0=未知
        self._max_mp = 0
        self._digit_templates = {}  # 0-9数字模板
        self._last_max_check = 0
        # YOLO怪物检测
        self._yolo_net = None
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._arrival_relock_until = 0  # 到顶重识别保护期截止(ms)：此前不拿旧怪表判cross往下走(用户2026-09-09)
        self._last_yolo_check = 0
        self._yolo_conf = 0.5   # YOLO置信度(用户2026-09-05：0.6→0.5，多检出一些怪)
        self._yolo_nms = 0.45
        # YOLO怪物检测
        self._yolo_net = None
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._last_yolo_check = 0
        self._yolo_conf = 0.5   # YOLO置信度(用户2026-09-05：0.6→0.5，多检出一些怪)
        self._yolo_nms = 0.45
        # BUFF/药品冷却状态（启动后生效）
        self._buff_last = {}  # buffN_key -> 上次释放时间戳
        self._potion_last = {}  # potionN_key -> 上次释放时间戳
        self._attack_last = {}  # atk1/aoe -> 上次释放时间戳
        self._player_screen_pos = None  # (x,y) 人物画面坐标
        # === 梯子特征模板（随方案永久存盘，内存仅为运行时副本，权威在 data/route_xxx_ladder_tpl.json）===
        self._ladder_templates = []     # [{id,img,width,height}]
        self._ladder_tpl_sim = LADDER_TPL_DEFAULT_SIM
        self._ladder_tpl_matches = []   # 最近梯子模板匹配候选(调试/蒙板显示)
        self._ladder_feature_window = None  # 梯子特征管理弹窗
        # 主窗口梯子模板"屏幕X精对齐"状态（每次爬梯由_reset_climb清零）
        self._lad_scr_ok_frames = 0
        self._lad_scr_key_vk = None
        self._lad_scr_key_t = 0
        self._lad_scr_nudge_t = 0
        self._lad_scr_ref_spx = None
        self._lad_scr_stall_t = 0
        self._lad_scr_stall_n = 0
        # 登顶三背景点状态（右上/右下/左下，随人物基点移动）
        self._climb_box_prev = [None, None, None]      # 三点上一帧纹理
        self._climb_box_centers = [None, None, None]   # 三点上一帧中心(锚点突变时本帧只建基准不判动)
        self._climb_still_since = 0                    # 存在静止点的连续起始时刻(0=三点都在动)
        self._char_match_ok = False     # 本帧人物特征是否匹配成功(边缘自救用)
        self._char_lost_edge = None     # 特征丢失时位置：'left'/'right'贴地图边 / None=中间或正常
        self._edge_recover = None       # 边缘自救状态 {dir,dot0,goal,until}：贴边丢特征时向中间走随机300-500px找回特征
        # === 掉台归位·独占辅助线(用户2026-09-09)：单平台(只勾一个台)时持续监测光点是否还在该台折线上,
        # 连续离开>防抖时长=掉下去→关主线、用_move_to回原台,光点重新回到原台折线=归位完成→恢复主线 ===
        self._fall_returning = False    # 是否正在掉台归位(归位期间主线锁怪/巡路/打怪暂停)
        self._fall_off_since = 0        # 首次检测到光点离开home台的时间(ms)，用于防抖(正常跳跃瞬离不触发)
        self._fall_home_pf_id = None    # 归位目标平台id(=pf['id'])，单平台锁定
        self._fall_home_target = None   # 归位目标点(小地图坐标)，喂给_move_to
        # === 卡住解卡·独占辅助线(用户2026-09-09)：主线移动中检测到卡住→关主线,独占"向前+跳"试X,脱困/上限后恢复 ===
        self._unblock_state = None      # None=未在解卡；dict{dir,jump,tries,dot0,act_t,phase}=解卡进行中(主线暂停)
        # === 辅助线隔离排查开关(用户2026-09-09)：只留主线_combat_tick排查"哪条辅助线抢行动/导致不锁不打"。
        # 排查期先全False=纯主线；确认主线正常后逐个置True打开验证，定位抢占者；排查结束恢复全True。
        self._aux_enable_edge = False      # 边缘自救线(_edge_recovery_tick)
        self._aux_enable_fall = False      # 掉台归位线(_fall_return_tick)
        self._aux_enable_unblock = False   # 卡住解卡线(_unblock_tick)；同时门控主线内_check_move_blocked登记,避免主线自我挂起
        self._aux_enable_retreat = False   # 主线内"平台边界回退"段(到绿线边缘往回走+小跳并整帧return,会抢占锁怪打怪)
        self._aux_enable_rest = False      # 主线内"拟人周期小休"段(5~8分钟停5~10秒,期间完全不动不打)
        # === 移动监管线 watchdog(用户2026-09-09三线模型:主线/监管线/辅助线) ===
        # 独立后台线程,只监测不发键;v1观察版只打行为日志(异常红字),不挂起主线、不执行修复。
        self._wd_lock = threading.Lock()   # 监管状态锁:主线登记意图/监管线程读取,跨线程访问加锁
        self._mv_intent = {}               # 当前移动意图 {'x':intent,'y':intent},水平/垂直独立记账可同时存在;intent=dict{dir,src,seg_t,seg_x,seg_y,reported...}
        self._motion_owner = None          # 动作权 'main'/'aux:edge'/'aux:fall'/'aux:unblock'/None(v1只记录交接,不强制)
        self._wd_thread = None             # 监管线程句柄
        self._wd_running = False           # 监管线程运行标志
        self._wd_log_last = {}             # 同类监管日志去重 {key:t}
        self._wd_bg_last = [None, None]  # 监管线独立的上/右两块上一帧ROI(与原镜头检测_bg_last_frames分开,互不干扰绿框)
        self._wd_jump_gate_until = 0     # 跳后静默截止时间戳(ms)：此前不做背景帧差(起跳时在_press_game_key置,1秒必落地)
        # === 原地直跳二次失败退开(用户2026-09-09)：<2对齐直跳连续2次没抓住梯子→主动退开120~150屏幕px再回主线,
        # 退开途中本层有怪先打怪(cast/pursue优先),本层无怪(cross)才继续横走,走够/超时后恢复正常选梯自动再上 ===
        self._ladder_vert_fail_count = 0   # 原地直跳连续失败计数(跨_reset_climb保留；抓住梯子/退开触发时清零,跑跳失败不计)
        self._ladder_backoff = None        # None=未在退开；dict{dir,start_sx,start_mx,target,start_t}=退开进行中
        self._combat_busy_until = 0  # 后摇锁定时间戳
        # === 人性化战斗状态 ===
        self._combat_react_until = 0       # 反应延迟结束时间
        self._combat_idle_until = 0        # 发呆结束时间
        self._combat_last_idle_check = 0   # 上次发呆检查
        self._combat_last_jump = 0         # 上次跳跃时间
        self._combat_last_move = 0         # 上次走位时间
        self._move_mon = None              # 位移检测基准 {dir,x0,t0,stalls}：按住方向后比对X是否真的移动，卡住则解卡(用户2026-09-07)
        self._last_monster_seen = 0.0      # 自适应降频：最后一次检测到怪的时间，0.4s内按战斗周期150ms、否则空闲周期300ms
        self._combat_target_idx = 0        # 当前目标索引（排序后）
        self._combat_facing = 0            # 0=未知, 1=右, -1=左
        self._combat_last_face_dir = None  # 上次让角色朝怪的方向(用于决定是否要转身)，None=还没转过
        self._combat_air_until = 0         # 本次跳起后落地前的截止时间ms(法师空中不能放技能,落地才攻击)
        self._combat_held_attack_key = None  # 当前按住的主攻键vk(连续攻击连放用), None=没按
        self._combat_turn_until = 0        # 转身动画结束时间
        self._combat_had_target = False    # 上一帧是否有目标
        self._combat_timed_keys = []       # 定时释放的按键 [(vk, release_ms)]（仅用于短按转身）
        self._combat_last_target_pos = None  # 上一次攻击目标位置(x,y)，用于近战挡身体时搜血条
        self._combat_held_keys = set()     # 持续按住的方向键（流畅移动用）
        self._combat_move_dir = None       # 当前持续移动方向 "left"/"right"/None
        self._combat_locked_target = None  # 锁定的目标 (cx, cy)，打死才换，不中途切换
        # === 模块A：打怪优化新增状态变量 ===
        self._combat_active = False         # 【战斗活跃标志】技能范围内有怪时=True，此时暂停巡路移动，专心打怪
        self._combat_target_lock_x = None   # 【锁定目标首次X】记录刚锁定时目标的X坐标，用于1秒无变化检测
        self._combat_target_lock_time = 0    # 【锁定目标时间戳】记录锁定目标的时间(毫秒)
        self._combat_target_alive = False    # 【目标是否存活】有血条或伤害数字时=True，说明怪还没打死
        self._combat_gone_frames = 0         # 打怪中"无血条无伤害"连续帧数（2帧判怪没了立即换）
        self._combat_target_hp_confirmed = False   # 是否已确认命中过血条(空怪判定用)；combat_step直接访问，必须__init__初始化
        self._combat_target_attacked = False       # 已对锁定目标出手(打一下无血条无伤害=空怪判定用)
        self._combat_first_strike_time = 0         # 对当前锁定目标【首次】出手时间(ms)：出手后留POST_STRIKE_CHECK_MS(130ms)反馈窗口再判空怪/打死，换目标清零
        self._combat_dropped_phantoms = []         # [(cx,cy,ms)] 最近放弃的空怪位置，短时间不再重锁，防空打死循环
        self._combat_suppress_side = None          # ('left'/'right', 到期ms) 某侧地形过不去时短时压制该侧、改锁另一侧(用户2026-09-07)
        self._slope_high_mode = False              # 当前锁定目标是否处于"高坡走-跳-打"模式(用于区分高坡打空vs普通空怪)
        self._slope_high_blocked = False           # 当前锁定目标跳打已打空(无血条无伤害=够不着)→降级:本次让它落cross走梯子/瞬移，换目标清除
        self._combat_range_clear = False     # 【范围清怪模式】技能范围内有怪时=True，范围内怪全部打完才恢复巡路
        # === 打怪分层探测状态（350近距→500同平台一边随机→跨层）===
        self._probe_side = random.choice([-1, 1])   # 当前探测方向 1=右 -1=左（每轮随机，先看哪边随机）
        self._probe_switched = False                 # 本轮是否已换边探测过（两边都空才跨层）
        self._combat_transit = False                 # 跨层行进中（去目标平台）
        self._transit_target = None                  # 跨层目标 (小地图X, 小地图Y)
        self._climb_fail_at = 0                      # 上次爬梯/跳跃失败时间戳(ms)，失败后2秒冷却（先打边上怪再上）
        # === 显示层速度外推状态（低帧率下蒙板落后一拍，按人物速度外推显示位置跟手）===
        self._char_disp_pos_prev = None              # 上次同步的原始匹配位置（用于算速度，不存外推值）
        self._char_disp_pos_time = 0                 # 上次同步时间戳(ms)
        self._char_disp_vel = (0.0, 0.0)             # 人物最近速度(px/s)，匹配失败宽限期内维持外推
        self._player_map_pos = None        # 玩家小地图坐标，用于判断当前平台
        self._monster_hp_bars = []         # 检测到的怪物血条 [(x,y,w,h),...]
        self._hp_pot_wait_until = 0        # HP吃药等待到这个时间
        self._mp_pot_wait_until = 0        # MP吃药等待到这个时间
        self._prev_key_states = set()  # 按键捕获轮询用
        # 按键捕获状态（GetAsyncKeyState轮询）
        self._prev_key_states = set()  # 上一轮已按下的键码集合
        self._last_periodic_pot = {}  # {pot_key: last_use_ms} 周期性吃药记录
        self._load_route_config()
        pf_file, ld_file = route_files(self.current_route)
        self.platforms = self._load(pf_file, "platforms")
        self.ladders = self._load(ld_file, "ladders")
        self._load_ladder_templates(self.current_route)  # 重开脚本:加载当前方案的梯子特征(永久文件→运行时副本)
        _debug_log("[初始化] 路线=%d 平台=%d条 梯子=%d条 梯子文件=%s" % (
            self.current_route, len(self.platforms), len(self.ladders), ld_file))
        # 加载当前方案的左右端点（和平台梯子一起作为一套方案，永久保存）
        self._calib_left_pt = None
        self._calib_right_pt = None
        self._calib_top_pt = None
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % self.current_route)
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cd = json.load(f)
                self._calib_left_pt = cd.get("calib_left")
                self._calib_right_pt = cd.get("calib_right")
                self._calib_top_pt = cd.get("calib_top")
                # 加载倍率数据（程序重启后自动恢复，不需要重新校准）
                saved_sx = cd.get("calibrated_scale_x", 0)
                saved_sy = cd.get("calibrated_scale_y", 0)
                if saved_sx > 0 and saved_sy > 0:
                    self._calibrated_scale_x = saved_sx
                    self._calibrated_scale_y = saved_sy
                    self._map_screen_scale = saved_sx
                    print("[初始化] 已加载方案%d倍率: X=%.4f Y=%.4f" % (self.current_route, saved_sx, saved_sy))
            except Exception:
                pass

        # 加载按钮栏整图
        self._btn_bar_img = None
        btn_path = resource_path(os.path.join("data", "templates", "btn_bar.png"))
        if os.path.exists(btn_path):
            self._btn_bar_img = cv2.imread(btn_path)

        # 手动框选模式状态
        self._selecting = False
        self._select_frame = None
        self._select_rect = None
        self._select_dragging = False

        # 随机模式运行状态
        self._random_running = False
        self._random_route_id = None
        self._random_platform_idx = 0
        self._random_state = "idle"  # idle/moving/attacking/returning/climbing
        self._random_attack_start = 0
        self._random_move_keys = set()  # 当前按住的移动键
        # 梯子攀爬状态机
        self._climb_state = "none"  # none/to_ladder/climbing/jump_down/teleport
        self._climb_ladder_x = 0
        self._climb_target_y = 0
        self._climb_direction = 0  # 1=up, -1=down
        self._climb_start_y = 0    # 跳跃/瞬移前的y坐标，用于检测是否生效
        self._climb_action_time = 0  # 跳跃/瞬移动作开始时间
        self._climb_fail_count = 0   # 本轮爬梯失败计数(__init__先初始化,防_reset_climb未跑就进_transit_step报AttributeError)
        self._climb_fail_limit = random.choice([2, 3])  # 失败随机上限
        self._climb_fail_pause_until = 0
        self._climb_fail_decided = None

        # 自动刷新状态：默认开启，手动框选后关闭，点刷新重新开启
        self._auto_refresh = True

        self.last_player_pos = None
        self.frame_count = 0

        # 热键状态（保留以备鼠标回调复用_handle_hotkey）
        self._key_state = {vk: False for vk in [VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F12]}
        self._running = False  # 脚本运行状态，F10启动 F12停止
        self._last_input_change = 0  # 输入框最后修改时间，用于3秒自动失焦
        # 偏移视觉反馈：设好偏移后等3秒，在人物偏移点位画黄点闪烁5次
        self._offset_feedback_start = 0  # 偏移修改时间戳
        self._offset_feedback_done = True  # 是否已完成本次反馈（避免重复触发）
        # 怪物检测透明蒙板（统一蒙板：黄点+怪物框+血条红点+蓝条蓝点）
        self._monster_overlay_running = False
        self._overlay_hwnd = None
        self._monster_overlay_data = None  # {char_pos, monsters, hp_marker, mp_marker, blink_until}
        self._char_feature_matches = []     # 人物特征单独匹配结果 [(x, y, tpl_id, confidence), ...]
        self._monster_feature_matches = []  # 怪物特征单独匹配结果 [(x, y, tpl_id, confidence), ...]
        self._monster_overlay_thread = None
        # 人物坐标跟踪线程（单独线程，每帧截图+人物匹配，确保人物点死死咬住位置不跳变）
        # 人物跟踪线程已删除（改用主循环共用截图，性能更好）
        # === 后台检测线程：把重活(截图+人物匹配+怪物匹配+YOLO+血条)拆到独立线程，主线程只读结果做移动/蒙板/战斗，
        #     避免主线程被拖累导致 YOLO/蒙板/小地图 几秒才刷一次（用户2026-09-05"主线太厚重要分解"）===
        self._detect_thread = None          # 后台检测线程
        self._detect_running = False        # 线程运行标志
        self._detect_lock = threading.Lock()  # 截图/结果写入锁，保证与主线程/蒙板线程不打架
        self._raw_monsters = []             # 后台线程算出的原始合并怪列表 [(x1,y1,x2,y2,score)]
        self._raw_hp_bars = []              # 后台线程算出的血条 [(x,y,w,h)]
        self._raw_char_pos = None           # 后台线程算出的人物脚位置
        self._raw_cached_feature_monsters = []  # 后台线程算出的怪物特征匹配结果
        self._detect_sct = None             # 后台线程自己的 mss 实例（不共用主线程的 self.sct）
        self._detect_last_monsters = None   # 后台线程最近一次非空怪列表（2秒宽限用）
        self._detect_last_monsters_time = 0 # 最近一次非空怪列表时间戳
        # 【模块B】自动校准状态（同屏三点校准：基点+右800+上500）
        self._auto_calib_stage = 0  # 0=空闲, 1=蒙板出三点可拖动定特色位置, 2=已记录绿点小地图位置待记录蓝点, 3=完成
        self._auto_calib_base = None  # 基点：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
        self._auto_calib_green_map = None  # 绿点小地图坐标（人物走到特色位置后记录光点位置）
        self._auto_calib_blue_map = None  # 蓝点小地图坐标（人物走到特色位置后记录光点位置）
        self._auto_calib_green_screen = None  # 绿点屏幕坐标（蒙板拖动定特色位置，stage>=2时固定）
        self._auto_calib_blue_screen = None  # 蓝点屏幕坐标（蒙板拖动定特色位置，stage>=2时固定）
        self._auto_calib_green_offset = (400, 0)  # 绿点相对基点的偏移（stage=1时拖动调整，跟着人物移动）
        self._auto_calib_blue_offset = (0, -400)  # 蓝点相对基点的偏移（stage=1时拖动调整，跟着人物移动）
        self._auto_calib_dragging = None  # 蒙板拖动状态：None/'green'/'blue'
        self._auto_calib_axis = 'X'  # 【倍率新方案】当前校准方向：'X'=绿圈只取X，'Y'=蓝圈只取Y（由点X倍率/Y倍率按钮决定）
        self._auto_calib_retry = 0  # 【倍率新方案】当前步骤连续失败次数，达到3次退出整个校准流程
        # 模板匹配跟踪（第二次点倍率后截图特色背景，模板匹配跟踪位置，画绿/蓝空心圆）
        self._calib_green_template = None  # 绿点位置的背景模板图（numpy数组）
        self._calib_blue_template = None   # 蓝点位置的背景模板图
        self._calib_green_match_pos = None  # 绿点模板匹配到的屏幕位置 (x, y)
        self._calib_blue_match_pos = None   # 蓝点模板匹配到的屏幕位置 (x, y)
        self._calib_template_size = 45       # 模板截图大小（45x45像素，圆45里面内容44，匹配更精准）
        self._calib_match_threshold = 0.65   # 模板匹配置信度阈值（降到0.65，远处绿/蓝圈也能识别到）
        # [CPU优化2026-09-07] 热键跑马灯已整段删除（每帧PIL重绘固定文字耗87~172ms/秒，装饰性提示无实际功能，用户确认移除）
        # 日志框中文字体：cv2.putText 画不了中文会变???乱码，改用 PIL 中文字体
        self._log_font = ImageFont.load_default()
        for _fp in ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/msyh.ttc",
                    "C:/Windows/Fonts/simsun.ttc", "simhei.ttf"):
            try:
                self._log_font = ImageFont.truetype(_fp, 13)
                break
            except Exception:
                continue
        # 按钮点击特效
        self._pressed_btn = None       # 当前按下的按钮rect (x,y,w,h)
        self._btn_flashes = []         # [(rect, start_ms, color_bgr), ...]

        # 加载UI背景图（五个标签页）
        self._ui_bgs = {}
        for tab, fname in [("route", "ui_bg_blank.png"), ("fight", "ui_tab_fight.png"),
                           ("potion", "ui_tab_potion.png"), ("chat", "ui_tab_chat.png"),
                           ("lie", "ui_tab_lie.png")]:
            p = resource_path(os.path.join("data", fname))
            img = load_png(p)
            if img is not None:
                if img.ndim == 3 and img.shape[2] == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                self._ui_bgs[tab] = cv2.resize(img, (UI_W, UI_H))
                print("[UI背景] 加载成功:", fname, img.shape)
            else:
                print("[UI背景] 加载失败:", p)
                self._ui_bgs[tab] = np.ones((UI_H, UI_W, 3), dtype=np.uint8) * 200
        self._ui_bg = self._ui_bgs["route"]
        self._current_tab = "route"

        # 顶部标签页点击区域（高度收紧，避免和下方按钮重叠）
        self._tab_areas = {
            "route": (_s(5), _s(34), _s(75), _s(28)),
            "fight": (_s(82), _s(34), _s(60), _s(28)),
            "potion": (_s(145), _s(34), _s(60), _s(28)),
            "chat": (_s(207), _s(34), _s(58), _s(28)),
            "lie": (_s(266), _s(34), _s(58), _s(28)),
        }

        # 日志
        self._logs = []

        # map_area_rect 已在__init__开头初始化，此处不重置（会覆盖自动绑定的检测结果）

        if self.map_area_rect:
            print("Map area:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
        else:
            print("Map area: 未检测到（请先绑定游戏窗口或F9校准）")
        print("方案 %d 已加载: %d 平台, %d 梯子 (模式: %s)" % (
            self.current_route, len(self.platforms), len(self.ladders), self.route_mode))
        print("UI: 左上角=刷新/手动/方案X  第一排=平台/梯子/保存▼/方案▼")
        print("    第二排=清除(绿=平台)/清除(蓝=梯子)/模式▼/清除(橙=方案)")
        print("=== 梯子录制=旧版原理(直接收集光点画面像素坐标,与平台同一空间);已移除滚动相位相关和手动编辑功能 ===\n")

        # 自动备份线程：已永久关闭（2026-09-01用户要求），函数_auto_backup_loop保留但不启动
        # self._auto_backup_interval = 1800  # 30分钟
        # self._last_backup_time = 0
        # self._auto_backup_thread = threading.Thread(target=self._auto_backup_loop, daemon=True)
        # self._auto_backup_thread.start()
        # print("[自动备份] 已启动，每30分钟Git自动提交一次")

    def _auto_backup_loop(self):
        """自动备份循环：每30分钟检查一次，源码有修改则git commit并push到远程
        用途：防止本地文件丢失，自动同步到GitHub远程仓库
        注意：GitHub单文件硬限制100MB，exe约66MB可正常推送"""
        import subprocess
        git_exe = r"C:\Program Files\Git\bin\git.exe"
        work_dir = os.path.dirname(os.path.abspath(__file__))
        # Windows专用：CREATE_NO_WINDOW标志，防止subprocess弹出控制台黑窗
        CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
        while True:
            try:
                time.sleep(60)  # 每分钟检查一次
                now = time.time()
                if now - self._last_backup_time < self._auto_backup_interval:
                    continue
                if not os.path.exists(git_exe):
                    continue
                # 步骤1：检查是否有修改
                result = subprocess.run([git_exe, "status", "--porcelain"], cwd=work_dir,
                                        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                if not result.stdout.strip():
                    self._last_backup_time = now
                    continue
                # 步骤2：git add 所有修改
                subprocess.run([git_exe, "add", "-A"], cwd=work_dir,
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
                # 步骤3：git commit
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                commit_msg = "自动备份 %s" % timestamp
                subprocess.run([git_exe, "commit", "-m", commit_msg], cwd=work_dir,
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
                self._last_backup_time = now
                print("[自动备份] Git已提交: %s" % commit_msg)
                # 步骤4：git push 到远程GitHub（大陆网络可能失败，失败不影响本地commit）
                push_result = subprocess.run([git_exe, "push", "origin", "main"], cwd=work_dir,
                                             capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
                                             timeout=60)
                if push_result.returncode == 0:
                    print("[自动备份] 已推送到远程GitHub")
                else:
                    # push失败（网络问题），本地commit已保存，下次重试
                    print("[自动备份] push失败(网络问题)，本地已保存，下次重试: %s" % push_result.stderr[:200])
            except subprocess.TimeoutExpired:
                print("[自动备份] push超时(网络慢)，本地已保存，下次重试")
            except Exception as e:
                print("[自动备份] 异常:", e)
                time.sleep(60)

    def _update_window_rect(self):
        rect = ctypes.create_string_buffer(16)
        user32.GetWindowRect(self.hwnd, rect)
        l, t, r, b = struct.unpack("llll", rect.raw)
        self.window_rect = {"left": l, "top": t, "width": r - l, "height": b - t}

    def _update_scale_dialog_positions(self):
        """立即计算弹窗内所有控件的位置（解决第一次打开弹窗点击没反应的问题）"""
        dlg_x = self._scale_dialog_pos[0]  # 弹窗X坐标
        dlg_y = self._scale_dialog_pos[1]  # 弹窗Y坐标
        dlg_w, dlg_h = 320, 220  # 弹窗宽高
        # 右上角关闭按钮X
        self._dlg_scale_close_btn = (dlg_x+dlg_w-30, dlg_y+5, 25, 25)
        # X偏差输入框
        self._dlg_scale_x_input = (dlg_x+110, dlg_y+65, 160, 35)
        # Y偏差输入框
        self._dlg_scale_y_input = (dlg_x+110, dlg_y+125, 160, 35)
        # 确认按钮
        self._dlg_scale_ok_btn = (dlg_x+60, dlg_y+175, 80, 30)
        # 取消按钮
        self._dlg_scale_cancel_btn = (dlg_x+180, dlg_y+175, 80, 30)

    def _update_y_dialog_positions(self):
        """打怪Y范围弹窗：立即计算所有控件位置（布局同倍率差弹窗，解决首次打开点击无反应）"""
        dlg_x = self._y_dialog_pos[0]
        dlg_y = self._y_dialog_pos[1]
        dlg_w, dlg_h = 320, 365  # 用户2026-09-09：主攻上/下+群攻上/下+跳高打上限 共5条，弹窗加高
        self._dlg_y_close_btn = (dlg_x+dlg_w-30, dlg_y+5, 25, 25)   # 右上角X
        self._dlg_y_up_input = (dlg_x+110, dlg_y+60, 160, 33)       # 主攻·上方范围
        self._dlg_y_down_input = (dlg_x+110, dlg_y+110, 160, 33)    # 主攻·下方范围
        self._dlg_aoe_y_up_input = (dlg_x+110, dlg_y+170, 160, 33)  # 群攻·上方范围
        self._dlg_aoe_y_down_input = (dlg_x+110, dlg_y+220, 160, 33)# 群攻·下方范围
        # 跳高打区间(最下一行,用户2026-09-09)：下限~上限两个小框并排，都填才启用，怪比人高落在区间内才走-跳-打
        self._dlg_slope_jump_ymin_input = (dlg_x+100, dlg_y+270, 72, 33)  # 跳高打下限(起始)
        self._dlg_slope_jump_ymax_input = (dlg_x+198, dlg_y+270, 72, 33)  # 跳高打上限
        self._dlg_slope_mage_chk = (dlg_x+276, dlg_y+280, 14, 14)         # 法师模式勾选(用户2026-09-09)：勾=法师落地放技能,不勾=战士空中150ms放
        self._dlg_y_ok_btn = (dlg_x+60, dlg_y+322, 80, 30)          # 确认
        self._dlg_y_cancel_btn = (dlg_x+180, dlg_y+322, 80, 30)     # 取消

    def _open_y_range_dialog(self):
        """打开打怪Y范围弹窗：备份现值，空值预填默认(上60/下30)，确认才保存"""
        self._show_y_dialog = True
        _up = self._field_values.get("attack_y_up", "")
        _dn = self._field_values.get("attack_y_down", "")
        _aup = self._field_values.get("aoe_y_up", "")
        _adn = self._field_values.get("aoe_y_down", "")
        _sjmin = self._field_values.get("slope_jump_y_min", "")
        _sjmax = self._field_values.get("slope_jump_y_max", "")
        _sjmage = self._field_values.get("slope_jump_mage", "")
        self._y_dialog_backup = {"attack_y_up": _up, "attack_y_down": _dn,
                                 "aoe_y_up": _aup, "aoe_y_down": _adn,
                                 "slope_jump_y_min": _sjmin, "slope_jump_y_max": _sjmax,
                                 "slope_jump_mage": _sjmage}
        # 首次打开(未设置过)预填默认值；以人物脚底为基点：上方为负、下方为正。主攻默认-60/+30，群攻默认-80/+60(范围技更宽)
        if not _up:
            self._field_values["attack_y_up"] = str(-ATTACK_Y_UP)
        if not _dn:
            self._field_values["attack_y_down"] = str(ATTACK_Y_DOWN)
        if not _aup:
            self._field_values["aoe_y_up"] = str(-AOE_Y_UP)
        if not _adn:
            self._field_values["aoe_y_down"] = str(AOE_Y_DOWN)
        # 跳高打下限/上限：用户2026-09-09要求默认留空、不预填；两个都填才启用跳高打，任一留空=不启用(高处怪走梯子)
        print("[Y范围弹窗] 打开 主攻上/下=%s/%s 群攻上/下=%s/%s 跳高打=%s~%s" % (
            self._field_values.get("attack_y_up"), self._field_values.get("attack_y_down"),
            self._field_values.get("aoe_y_up"), self._field_values.get("aoe_y_down"),
            self._field_values.get("slope_jump_y_min"), self._field_values.get("slope_jump_y_max")))

    def _restore_y_dialog_backup(self):
        """取消/关闭Y范围弹窗：恢复打开前的值（不保存）"""
        if "attack_y_up" in self._y_dialog_backup:
            self._field_values["attack_y_up"] = self._y_dialog_backup["attack_y_up"]
        if "attack_y_down" in self._y_dialog_backup:
            self._field_values["attack_y_down"] = self._y_dialog_backup["attack_y_down"]
        if "aoe_y_up" in self._y_dialog_backup:
            self._field_values["aoe_y_up"] = self._y_dialog_backup["aoe_y_up"]
        if "aoe_y_down" in self._y_dialog_backup:
            self._field_values["aoe_y_down"] = self._y_dialog_backup["aoe_y_down"]
        if "slope_jump_y_min" in self._y_dialog_backup:
            self._field_values["slope_jump_y_min"] = self._y_dialog_backup["slope_jump_y_min"]
        if "slope_jump_y_max" in self._y_dialog_backup:
            self._field_values["slope_jump_y_max"] = self._y_dialog_backup["slope_jump_y_max"]
        if "slope_jump_mage" in self._y_dialog_backup:
            self._field_values["slope_jump_mage"] = self._y_dialog_backup["slope_jump_mage"]

    # ============ 寻怪范围弹窗(用户2026-09-08，Y拆成上方/下方独立设置)：X=左右各寻怪距离 Y上=上方容差 Y下=下方容差 ============
    def _update_search_dialog_positions(self):
        dlg_x = self._search_dialog_pos[0]
        dlg_y = self._search_dialog_pos[1]
        dlg_w, dlg_h = 320, 250
        self._dlg_search_close_btn = (dlg_x+dlg_w-30, dlg_y+5, 25, 25)
        # 用户2026-09-09：三个输入框统一缩短到原60%(160→96)，第一行右侧空出放"群怪优先"勾选
        self._dlg_search_x_input = (dlg_x+110, dlg_y+62, 96, 35)       # X寻怪范围(左右共用)
        self._dlg_search_y_up_input = (dlg_x+110, dlg_y+108, 96, 35)   # Y上方范围
        self._dlg_search_y_down_input = (dlg_x+110, dlg_y+155, 96, 35) # Y下方范围
        self._dlg_search_group_chk = (dlg_x+214, dlg_y+71, 16, 16)     # 群怪优先勾选(与X框垂直居中对齐)
        self._dlg_search_dual_chk = (dlg_x+214, dlg_y+117, 16, 16)     # 群攻双向勾选(与Y上框垂直居中对齐,群怪优先下方)
        self._dlg_search_ok_btn = (dlg_x+60, dlg_y+205, 80, 30)
        self._dlg_search_cancel_btn = (dlg_x+180, dlg_y+205, 80, 30)

    def _open_search_range_dialog(self):
        """打开寻怪范围弹窗：备份现值，空值预填默认，确认才保存"""
        self._show_search_dialog = True
        _x = self._field_values.get("far_range_x", "")
        _yu = self._field_values.get("far_range_y_up", "")
        _yd = self._field_values.get("far_range_y_down", "")
        _gp = self._field_values.get("group_priority", "")
        _dual = self._field_values.get("aoe_dual", "")
        self._search_dialog_backup = {"far_range_x": _x, "far_range_y_up": _yu, "far_range_y_down": _yd,
                                      "group_priority": _gp, "aoe_dual": _dual}
        if not _x:
            self._field_values["far_range_x"] = str(COMBAT_FAR_RANGE)   # 默认1300
        if not _yu:
            self._field_values["far_range_y_up"] = str(FAR_RANGE_Y_UP_DEFAULT)   # 默认150
        if not _yd:
            self._field_values["far_range_y_down"] = str(FAR_RANGE_Y_DOWN_DEFAULT) # 默认150
        print("[寻怪范围弹窗] 打开 X=%s Y上=%s Y下=%s" % (
            self._field_values.get("far_range_x"),
            self._field_values.get("far_range_y_up"),
            self._field_values.get("far_range_y_down")))

    def _restore_search_dialog_backup(self):
        if "far_range_x" in self._search_dialog_backup:
            self._field_values["far_range_x"] = self._search_dialog_backup["far_range_x"]
        if "far_range_y_up" in self._search_dialog_backup:
            self._field_values["far_range_y_up"] = self._search_dialog_backup["far_range_y_up"]
        if "far_range_y_down" in self._search_dialog_backup:
            self._field_values["far_range_y_down"] = self._search_dialog_backup["far_range_y_down"]
        if "group_priority" in self._search_dialog_backup:
            self._field_values["group_priority"] = self._search_dialog_backup["group_priority"]
        if "aoe_dual" in self._search_dialog_backup:
            self._field_values["aoe_dual"] = self._search_dialog_backup["aoe_dual"]

    def _update_tp_dialog_positions(self):
        """瞬移设置弹窗控件位置（布局同Y范围弹窗）"""
        dlg_x = self._tp_dialog_pos[0]
        dlg_y = self._tp_dialog_pos[1]
        dlg_w = 320
        self._dlg_tp_close_btn = (dlg_x+dlg_w-30, dlg_y+5, 25, 25)
        self._dlg_tp_x_input = (dlg_x+110, dlg_y+60, 160, 33)
        self._dlg_tp_y_input = (dlg_x+110, dlg_y+113, 160, 33)
        self._dlg_tp_key_input = (dlg_x+110, dlg_y+166, 160, 33)   # 瞬移按键录入框
        self._dlg_tp_ok_btn = (dlg_x+60, dlg_y+222, 80, 30)
        self._dlg_tp_cancel_btn = (dlg_x+180, dlg_y+222, 80, 30)

    def _open_tp_dialog(self):
        """打开瞬移设置弹窗：备份现值（默认空=不瞬移）"""
        self._show_tp_dialog = True
        _x = self._field_values.get("teleport_distance", "")
        _y = self._field_values.get("teleport_distance_y", "")
        _k = self._field_values.get("teleport_key", "")
        self._tp_dialog_backup = {"teleport_distance": _x, "teleport_distance_y": _y, "teleport_key": _k}
        print("[瞬移弹窗] 打开 X=%s Y=%s 按键=%s" % (_x or "空", _y or "空", _k or "空"))

    def _restore_tp_dialog_backup(self):
        """取消/关闭瞬移弹窗：恢复（不保存）"""
        if "teleport_distance" in self._tp_dialog_backup:
            self._field_values["teleport_distance"] = self._tp_dialog_backup["teleport_distance"]
        if "teleport_distance_y" in self._tp_dialog_backup:
            self._field_values["teleport_distance_y"] = self._tp_dialog_backup["teleport_distance_y"]
        if "teleport_key" in self._tp_dialog_backup:
            self._field_values["teleport_key"] = self._tp_dialog_backup["teleport_key"]

    def _create_crosshair_window(self):
        """创建pygame透明置顶准星窗口，用于拖拽时显示准星，可拖到屏幕任意位置"""
        if not self._crosshair_pygame_inited:
            pygame.init()  # 初始化pygame
            self._crosshair_pygame_inited = True
        # 创建无边框窗口
        cs = self._crosshair_size * 2  # 窗口大小是准星大小的2倍，留出边距
        self._crosshair_pygame_window = pygame.display.set_mode((cs, cs), pygame.NOFRAME)
        self._crosshair_pygame_screen = self._crosshair_pygame_window
        # 获取窗口句柄
        self._crosshair_pygame_hwnd = pygame.display.get_wm_info()["window"]
        # 设置窗口置顶
        win32gui.SetWindowPos(self._crosshair_pygame_hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                               win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        # 设置窗口透明（白色透明）
        ex_style = win32gui.GetWindowLong(self._crosshair_pygame_hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(self._crosshair_pygame_hwnd, win32con.GWL_EXSTYLE,
                                ex_style | win32con.WS_EX_LAYERED)
        win32gui.SetLayeredWindowAttributes(self._crosshair_pygame_hwnd, win32api.RGB(255, 255, 255), 0, win32con.LWA_COLORKEY)
        print("[准星] pygame透明置顶窗口已创建")

    def _update_crosshair_window(self, screen_x, screen_y):
        """更新准星窗口位置到屏幕坐标
        Args:
            screen_x: 屏幕X坐标
            screen_y: 屏幕Y坐标
        """
        if self._crosshair_pygame_hwnd is None:
            return
        cs = self._crosshair_size * 2  # 窗口大小
        # 把窗口左上角移动到准星中心减去窗口半径的位置
        win_x = screen_x - cs // 2
        win_y = screen_y - cs // 2
        win32gui.SetWindowPos(self._crosshair_pygame_hwnd, 0, win_x, win_y, 0, 0,
                               win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
        # 绘制准星
        self._draw_crosshair_on_pygame()

    def _draw_crosshair_on_pygame(self):
        """在pygame窗口上绘制准星（红色）"""
        if self._crosshair_pygame_screen is None:
            return
        cs = self._crosshair_size * 2  # 窗口大小
        center = cs // 2  # 准星中心
        r = self._crosshair_size // 2  # 准星半径
        # 清屏（白色背景，会被透明化）
        self._crosshair_pygame_screen.fill((255, 255, 255))
        # 绘制准星（红色）
        pygame.draw.circle(self._crosshair_pygame_screen, (255, 0, 0), (center, center), r, 2)
        pygame.draw.line(self._crosshair_pygame_screen, (255, 0, 0), (center - r - 4, center), (center - r + 1, center), 2)
        pygame.draw.line(self._crosshair_pygame_screen, (255, 0, 0), (center + r - 1, center), (center + r + 4, center), 2)
        pygame.draw.line(self._crosshair_pygame_screen, (255, 0, 0), (center, center - r - 4), (center, center - r + 1), 2)
        pygame.draw.line(self._crosshair_pygame_screen, (255, 0, 0), (center, center + r - 1), (center, center + r + 4), 2)
        pygame.display.flip()  # 更新显示

    def _destroy_crosshair_window(self):
        """销毁pygame准星窗口（只隐藏窗口，不调用pygame.display.quit()，避免video system not initialized错误）"""
        if self._crosshair_pygame_hwnd is not None:
            # 只隐藏窗口，不退出pygame显示，避免下一帧调用pygame.event.pump()时报错
            win32gui.ShowWindow(self._crosshair_pygame_hwnd, win32con.SW_HIDE)
            self._crosshair_pygame_window = None
            self._crosshair_pygame_screen = None
            self._crosshair_pygame_hwnd = None
            print("[准星] pygame透明置顶窗口已隐藏")

    def _save_target_window_size(self):
        """记录目标窗口大小（绑定成功后调用）。写死 GAME_W x GAME_H(1276x749)，不读当前窗口——用户要写死固定，窗口变大会被_ensure_window_size拉回。
        同时移除窗口的WS_THICKFRAME(可调大小边框)——用户改不了大小，但保留标题栏WS_CAPTION仍可拖动移动位置。"""
        if self.hwnd and self.window_rect:
            self._target_window_size = (GAME_W, GAME_H)
            print("[窗口固定] 目标大小已写死: %dx%d" % self._target_window_size)
            try:
                style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_STYLE)
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_STYLE, style & ~win32con.WS_THICKFRAME)
            except Exception as e:
                print("[窗口固定] 移除WS_THICKFRAME异常:", e)
            self._ensure_window_size()  # 绑定后立即拉回指定尺寸1276x749(不等主循环30帧)，用户改不了大小

    def _ensure_window_size(self):
        """检测窗口大小是否变动，变动则拉回目标大小"""
        if self.hwnd is None or self._target_window_size is None:
            _debug_log("[窗口固定诊断] 不拉回: hwnd=%s _target_window_size=%s" % (self.hwnd, self._target_window_size))
            return
        self._update_window_rect()
        cur_w = self.window_rect["width"]
        cur_h = self.window_rect["height"]
        tgt_w, tgt_h = self._target_window_size
        _debug_log("[窗口固定诊断] cur=%dx%d tgt=%dx%d 差=%d/%d" % (cur_w, cur_h, tgt_w, tgt_h, abs(cur_w-tgt_w), abs(cur_h-tgt_h)))
        if abs(cur_w - tgt_w) > 2 or abs(cur_h - tgt_h) > 2:
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            user32.SetWindowPos(self.hwnd, 0, 0, 0, tgt_w, tgt_h,
                                SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)
            self._update_window_rect()
            print("[窗口固定] 检测到大小变动 %dx%d -> 已拉回 %dx%d" % (cur_w, cur_h, tgt_w, tgt_h))

    def _load_region(self):
        """从文件加载已保存的小地图区域，成功返回 True"""
        if not os.path.exists(REGION_FILE):
            return False
        try:
            with open(REGION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "map" in data and "minimap" in data:
                self.map_area_rect = data["map"]
                self.minimap_rect = data["minimap"]
                self._recalc_scale_from_region()
                print("Loaded saved region:", self.map_area_rect["width"], "x", self.map_area_rect["height"])
                return True
        except Exception:
            pass
        return False

    def _detect_minimap(self, debug=True):
        """三特征点定位：左=小地图文字左，右=大地图文字右，下=底部蓝色线（颜色检测）
        debug=False 时为每帧轻量模式，不写调试图"""
        if self.hwnd is None:
            return
        self._update_window_rect()
        # [CPU优化2026-09-07] 三模板重定位也复用检测线程帧(帧龄≤0.8s)，不再独立全窗口截图；
        # debug=True(手动按r)或无共享帧时才补截。截图失败(frame=None)直接跳过本轮，绝不抛异常闪退。
        frame = None
        if not debug:
            _rf = getattr(self, '_raw_frame', None)
            _rft = getattr(self, '_raw_frame_t', 0)
            if _rf is not None and (time.time() - _rft) <= 0.8:
                frame = _rf
        if frame is None:
            frame = self._capture_window()
        if frame is None:
            return
        fh, fw = frame.shape[:2]

        # 懒加载模板
        if not hasattr(self, '_tpl_minimap'):
            base = resource_path(os.path.join("data", "templates"))
            self._tpl_minimap = cv2.imread(os.path.join(base, "minimap_title.png"))
            self._tpl_bigmap = cv2.imread(os.path.join(base, "bigmap_title.png"))
            self._tpl_minimap_bottom = cv2.imread(os.path.join(base, "minimap_bottom.png"))
            print("Templates loaded: mini%dx%d big%dx%d bottom%dx%d" % (
                self._tpl_minimap.shape[1], self._tpl_minimap.shape[0],
                self._tpl_bigmap.shape[1], self._tpl_bigmap.shape[0],
                self._tpl_minimap_bottom.shape[1], self._tpl_minimap_bottom.shape[0]))

        tpl_m, tpl_b = self._tpl_minimap, self._tpl_bigmap
        mh, mw = tpl_m.shape[:2]
        bh, bw = tpl_b.shape[:2]

        # 1. 找"小地图"文字
        roi_m = frame[0:120, 0:300]
        res_m = cv2.matchTemplate(roi_m, tpl_m, cv2.TM_CCOEFF_NORMED)
        _, val_m, _, loc_m = cv2.minMaxLoc(res_m)
        mini_x, mini_y = loc_m
        if debug:
            print("小地图: val=%.3f at (%d,%d)" % (val_m, mini_x, mini_y))
        if val_m < 0.55:
            if debug:
                print("小地图标题匹配度过低(%.3f)，本帧跳过不定位(唯一方案=三模板，已移除描线法兜底)" % val_m)
            return

        # 2. 找"大地图"文字（小地图右侧同行）
        # X范围固定100-400（不管地图多宽都能检测到，避免宽地图时超出范围）
        roi_b_x1 = 100
        roi_b_x2 = 400
        roi_b = frame[0:120, roi_b_x1:roi_b_x2]
        res_b = cv2.matchTemplate(roi_b, tpl_b, cv2.TM_CCOEFF_NORMED)
        _, val_b, _, loc_b = cv2.minMaxLoc(res_b)
        big_x = roi_b_x1 + loc_b[0]
        big_y = max(0, mini_y - 5) + loc_b[1]
        if debug:
            print("大地图: val=%.3f at (%d,%d)" % (val_b, big_x, big_y))

        # 3. 边界：左=小地图左，右=大地图右，上=小地图下
        # 白边偏移量：LEFT_OFFSET正数=向右移=左边增加白边；TOP_OFFSET正数=向下移=去掉上面白边；BOTTOM_OFFSET负数=向上移=去掉下面白边
        LEFT_OFFSET = -6  # 左边向右偏1px(用户2026-09-06调试：-7→-6)
        TOP_OFFSET = 24  # 上边向下移1px(用户2026-09-06冒险岛世界调试：27→24，小地图上方Y上移3px)
        BOTTOM_OFFSET = -8  # 下边(用户2026-09-06冒险岛世界调试：-9→-8，下边Y下移1px)
        left = mini_x + LEFT_OFFSET  # 左边加偏移量
        right = big_x + bw + 3  # 右边(用户2026-09-06冒险岛世界调试：+1→+3，右边X右移2px)
        top = mini_y + mh + TOP_OFFSET  # 上面加偏移量
        if debug:
            print("边界: L=%d R=%d T=%d W=%d" % (left, right, top, right - left))

        # 4. 模板匹配底部边界图（替代蓝色线颜色检测，避免人物经过时误判）
        tpl_btm = self._tpl_minimap_bottom
        btm_h, btm_w = tpl_btm.shape[:2]
        search_y1 = top
        search_y2 = min(fh, top + 350)
        # 在小地图左右边界内搜索底部模板（宽度可能小于小地图宽度，居中或偏左都能匹配）
        search_x1 = max(0, left - 20)
        search_x2 = min(fw, right + 20)
        roi_btm = frame[search_y1:search_y2, search_x1:search_x2]
        bottom = None
        if roi_btm.shape[0] >= btm_h and roi_btm.shape[1] >= btm_w:
            res_btm = cv2.matchTemplate(roi_btm, tpl_btm, cv2.TM_CCOEFF_NORMED)
            _, val_btm, _, loc_btm = cv2.minMaxLoc(res_btm)
            if val_btm >= 0.55:
                # 底部边界定在模板图片的上下正中间，加BOTTOM_OFFSET偏移量（负数=向上移=去掉下面白边）
                bottom = search_y1 + loc_btm[1] + btm_h // 2 + BOTTOM_OFFSET
                if debug:
                    print("底部模板: val=%.3f at (%d,%d), bottom_y=%d" % (
                        val_btm, search_x1 + loc_btm[0], search_y1 + loc_btm[1], bottom))
        if bottom is None:
            if debug:
                print("底部模板未找到(匹配度过低)，跳过本帧")
            return

        # 5. 计算区域
        new_minimap = {
            "left": left, "top": mini_y,
            "width": right - left, "height": bottom - mini_y
        }
        TITLE_PAD = 45
        new_map = {
            "left": left,
            "top": top + TITLE_PAD,
            "width": right - left,
            "height": bottom - top - TITLE_PAD
        }

        # 轻量模式：区域变化小于1px则不更新（防抖，确保小变化也能生效），不写文件不写图
        if not debug:
            old = self.map_area_rect
            if old is not None and (abs(old["left"] - new_map["left"]) <= 1 and
                abs(old["top"] - new_map["top"]) <= 1 and
                abs(old["width"] - new_map["width"]) <= 1 and
                abs(old["height"] - new_map["height"]) <= 1):
                return
            if old is not None:
                print("[自动刷新] 小地图区域变化: %dx%d -> %dx%d" % (
                    old["width"], old["height"], new_map["width"], new_map["height"]))

        self.minimap_rect = new_minimap
        self.map_area_rect = new_map
        self._save_region()
        self.last_player_pos = None

        if debug:
            # 调试图
            dbg = frame.copy()
            cv2.rectangle(dbg, (mini_x, mini_y), (mini_x + mw, mini_y + mh), (0, 0, 255), 1)
            cv2.rectangle(dbg, (big_x, big_y), (big_x + bw, big_y + bh), (0, 165, 255), 1)
            cv2.line(dbg, (left, bottom), (right, bottom), (255, 0, 255), 2)
            cv2.rectangle(dbg, (self.minimap_rect["left"], self.minimap_rect["top"]),
                          (self.minimap_rect["left"] + self.minimap_rect["width"],
                           self.minimap_rect["top"] + self.minimap_rect["height"]), (255, 0, 0), 1)
            mr = self.map_area_rect
            cv2.rectangle(dbg, (mr["left"], mr["top"]),
                          (mr["left"] + mr["width"], mr["top"] + mr["height"]), (0, 255, 0), 2)
            cv2.imwrite("debug_detect.png", dbg)
            print("Map area: %dx%d" % (self.map_area_rect["width"], self.map_area_rect["height"]))

    def _save_region(self):
        with open(REGION_FILE, "w", encoding="utf-8") as f:
            json.dump({"minimap": self.minimap_rect, "map": self.map_area_rect}, f, indent=2)

    def _load_route_config(self):
        """加载方案配置：plans.json（地图+方案）+ route_config.json（运行方式），自动迁移旧数据"""
        # 先迁移旧数据（route_1/2/3 → plans.json）
        self._migrate_old_plans()
        # 加载plans.json
        if os.path.exists(PLANS_FILE):
            try:
                with open(PLANS_FILE, "r", encoding="utf-8") as f:
                    self.plans_data = json.load(f)
            except Exception:
                pass
        # 从plans_data恢复current_route
        cid = self.plans_data.get("current_id", "route_001")
        self.current_route = plan_id_to_num(cid)
        # 加载运行方式
        if os.path.exists(ROUTE_CONFIG_FILE):
            try:
                with open(ROUTE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.route_mode = data.get("route_mode", "手动")
            except Exception:
                pass

    def _save_route_config(self):
        """保存运行方式（手动/随机）"""
        with open(ROUTE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"route_mode": self.route_mode}, f, indent=2)

    def _save_plans(self):
        """保存plans.json方案索引"""
        with open(PLANS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.plans_data, f, indent=2, ensure_ascii=False)

    def _migrate_old_plans(self):
        """旧数据迁移：route_1/2/3 → plans.json（只在plans.json不存在时执行）"""
        if os.path.exists(PLANS_FILE):
            return
        plans = []
        name_map = {1: "方案一", 2: "方案二", 3: "方案三"}
        for i in range(1, 4):
            old_pf = os.path.join(DATA_DIR, "route_%d_platforms.json" % i)
            new_pf = os.path.join(DATA_DIR, "route_%03d_platforms.json" % i)
            old_ld = os.path.join(DATA_DIR, "route_%d_ladders.json" % i)
            new_ld = os.path.join(DATA_DIR, "route_%03d_ladders.json" % i)
            old_cb = os.path.join(DATA_DIR, "route_%d_calib.json" % i)
            new_cb = os.path.join(DATA_DIR, "route_%03d_calib.json" % i)
            # 重命名文件
            for old, new in ((old_pf, new_pf), (old_ld, new_ld), (old_cb, new_cb)):
                if os.path.exists(old) and not os.path.exists(new):
                    try:
                        os.rename(old, new)
                    except Exception:
                        pass
            # 如果新文件存在，加入迁移列表
            if os.path.exists(new_pf):
                plans.append({"id": num_to_plan_id(i), "name": name_map[i], "selected": False})
        if plans:
            self.plans_data = {
                "maps": [{"name": "默认地图", "plans": plans}],
                "current_id": plans[0]["id"]
            }
            self._save_plans()
            print("[迁移] 旧方案数据已迁移到plans.json: %d个方案" % len(plans))

    # ===== 方案CRUD =====

    def _find_map(self, map_name):
        """查找地图dict，找不到返回None"""
        for m in self.plans_data["maps"]:
            if m["name"] == map_name:
                return m
        return None

    def _find_plan(self, plan_id):
        """查找方案dict和所属地图dict，返回(plan_dict, map_dict)"""
        for m in self.plans_data["maps"]:
            for p in m["plans"]:
                if p["id"] == plan_id:
                    return p, m
        return None, None

    def _next_plan_id(self):
        """获取下一个可用的方案ID（route_001~route_100）"""
        used = set()
        for m in self.plans_data["maps"]:
            for p in m["plans"]:
                used.add(p["id"])
        for i in range(1, 101):
            pid = num_to_plan_id(i)
            if pid not in used:
                return pid
        return None

    def _create_plan(self, map_name):
        """在指定地图下创建新方案，返回plan_dict或None（满了）"""
        mp = self._find_map(map_name)
        if mp is None:
            # 创建新地图
            if len(self.plans_data["maps"]) >= 100:
                return None
            mp = {"name": map_name, "plans": []}
            self.plans_data["maps"].append(mp)
        if len(mp["plans"]) >= 10:
            return None
        pid = self._next_plan_id()
        if pid is None:
            return None
        plan = {"id": pid, "name": "方案%d" % (len(mp["plans"]) + 1), "selected": False}
        mp["plans"].append(plan)
        self._save_plans()
        return plan

    def _delete_plan(self, plan_id):
        """删除方案（文件+索引）"""
        plan, mp = self._find_plan(plan_id)
        if plan is None:
            return
        num = plan_id_to_num(plan_id)
        pf_file, ld_file = route_files(num)
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % num)
        for f in (pf_file, ld_file, calib_file):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        mp["plans"].remove(plan)
        # 空地图也删除
        if not mp["plans"]:
            self.plans_data["maps"].remove(mp)
        self._save_plans()
        print("[删除] 方案 %s 已删除" % plan["name"])

    def _delete_map(self, map_name):
        """删除整个地图及其下所有方案"""
        mp = self._find_map(map_name)
        if mp is None:
            return
        for plan in mp["plans"]:
            num = plan_id_to_num(plan["id"])
            pf_file, ld_file = route_files(num)
            calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % num)
            for f in (pf_file, ld_file, calib_file):
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
        self.plans_data["maps"].remove(mp)
        self._save_plans()
        print("[删除] 地图 '%s' 及其下%d个方案已清空" % (map_name, len(mp["plans"])))

    def _rename_plan(self, plan_id, new_name):
        """重命名方案"""
        plan, _ = self._find_plan(plan_id)
        if plan:
            plan["name"] = new_name
            self._save_plans()

    def _rename_map(self, old_name, new_name):
        """重命名地图"""
        mp = self._find_map(old_name)
        if mp and not self._find_map(new_name):
            mp["name"] = new_name
            self._save_plans()

    def _set_plan_selected(self, plan_id, selected):
        """勾选/取消勾选方案（跨地图自动取消其他地图勾选）"""
        target_plan, target_map = self._find_plan(plan_id)
        if target_plan is None:
            return
        if selected:
            # 勾选：取消其他所有地图的勾选
            for m in self.plans_data["maps"]:
                if m is not target_map:
                    for p in m["plans"]:
                        p["selected"] = False
            target_plan["selected"] = True
        else:
            target_plan["selected"] = False
        self._save_plans()

    def _get_selected_plans(self):
        """获取当前勾选的方案列表（同一地图下）"""
        result = []
        for m in self.plans_data["maps"]:
            for p in m["plans"]:
                if p["selected"]:
                    result.append(p)
        return result

    def _load(self, path, key):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f).get(key, [])
            except Exception:
                return []
        return []

    def _route_has_file(self, route_id):
        """方案是否已录：只要平台文件存在就算已录"""
        pf_file, _ = route_files(route_id)
        return os.path.exists(pf_file)

    def _save_to_route(self, route_id):
        """保存当前录制的平台+梯子+端点+怪物特征到指定方案文件（覆盖）"""
        pf_file, ld_file = route_files(route_id)
        with open(pf_file, "w", encoding="utf-8") as f:
            json.dump({"platforms": self.platforms, "count": len(self.platforms)}, f, indent=2)
        with open(ld_file, "w", encoding="utf-8") as f:
            json.dump({"ladders": self.ladders, "count": len(self.ladders)}, f, indent=2)
        self._save_ladder_templates(route_id)  # 梯子特征随方案永久保存(F8双保险,捕获时也已即时落盘)
        # 怪物特征也随方案保存（每个图怪物不同，切换方案=切换怪物特征）——用户规则
        monster_file = os.path.join(DATA_DIR, "route_%03d_monsters.json" % route_id)
        try:
            monsters_out = []
            for t in self._monster_templates:
                _ok, _buf = cv2.imencode(".png", t["img"])
                if _ok:
                    monsters_out.append({
                        "id": t.get("id", 0),
                        "width": t.get("width", 0),
                        "height": t.get("height", 0),
                        "offset_x": t.get("offset_x", 0),
                        "offset_y": t.get("offset_y", 0),
                        "direction": t.get("direction", "right"),
                        "color": t.get("color", [255, 0, 0]),
                        "created_at": t.get("created_at", ""),
                        "img_b64": base64.b64encode(_buf).decode("utf-8"),
                    })
            with open(monster_file, "w", encoding="utf-8") as f:
                json.dump({"monsters": monsters_out, "count": len(monsters_out)}, f, indent=2)
            print("[保存] 方案%d 怪物特征%d套" % (route_id, len(monsters_out)))
        except Exception as _e:
            print("[保存] 怪物特征保存失败:", _e)
        # 同时保存端点（左/右/上）到方案文件
        self._save_calib()
        self.current_route = route_id
        self.plans_data["current_id"] = num_to_plan_id(route_id)
        self._save_plans()
        self._save_route_config()
        print("[保存] 方案%d: %d 平台, %d 梯子, 端点左=%s 右=%s 上=%s（已覆盖）" % (
            route_id, len(self.platforms), len(self.ladders),
            "有" if self._calib_left_pt else "无", "有" if self._calib_right_pt else "无",
            "有" if getattr(self, '_calib_top_pt', None) else "无"))

    def _next_free_route_id(self):
        """下一个空闲方案编号（1-99）"""
        _used = set()
        for _m in self.plans_data.get("maps", []):
            for _p in _m.get("plans", []):
                _used.add(plan_id_to_num(_p["id"]))
        for _i in range(1, 100):
            if _i not in _used:
                return _i
        return 100

    def _apply_plan_data(self, data, route_id, yolo_dir=None):
        """把单方案数据写入指定编号：平台/梯子/怪物特征/calib + 方案索引（不存在则创建）
        yolo_dir: 导入的导出文件夹路径 → 把calib里的YOLO模型路径改写为"该目录/best.onnx"
        （导出记录的是导出机器上的绝对路径，换机导入必失效；改为跟随导出文件所在目录，用户要求）"""
        pf_file, ld_file = route_files(route_id)
        with open(pf_file, "w", encoding="utf-8") as f:
            json.dump({"platforms": data.get("platforms", []), "count": len(data.get("platforms", []))}, f, ensure_ascii=False, indent=2)
        with open(ld_file, "w", encoding="utf-8") as f:
            json.dump({"ladders": data.get("ladders", []), "count": len(data.get("ladders", []))}, f, ensure_ascii=False, indent=2)
        monster_file = os.path.join(DATA_DIR, "route_%03d_monsters.json" % route_id)
        with open(monster_file, "w", encoding="utf-8") as f:
            json.dump({"monsters": data.get("monsters", []), "count": len(data.get("monsters", []))}, f, ensure_ascii=False, indent=2)
        # 梯子特征随方案导入：永久落盘；若导入到当前方案，同时刷新运行时副本
        _lt = data.get("ladder_templates")
        try:
            with open(self._ladder_tpl_path(route_id), "w", encoding="utf-8") as f:
                json.dump({"templates": _lt or [], "count": len(_lt or []),
                           "sim": data.get("ladder_tpl_sim", LADDER_TPL_DEFAULT_SIM)},
                          f, ensure_ascii=False, indent=2)
            if route_id == self.current_route:
                self._load_ladder_templates(route_id)
        except Exception as _e:
            print("[导入] 梯子特征写入失败:", _e)
        _calib = dict(data.get("calib") or {})
        if yolo_dir and _calib.get("yolo_model_path"):
            _calib["yolo_model_path"] = os.path.join(yolo_dir, "best.onnx")
        with open(os.path.join(DATA_DIR, "route_%03d_calib.json" % route_id), "w", encoding="utf-8") as f:
            json.dump(_calib, f, ensure_ascii=False, indent=2)
        if not self._find_plan(num_to_plan_id(route_id))[0]:
            _mp = self.plans_data.get("maps", [])
            _target_map = None
            _mname = data.get("map_name", "导入")
            for _m in _mp:
                if _m.get("name") == _mname:
                    _target_map = _m
                    break
            if _target_map is None:
                _target_map = {"name": _mname, "plans": []}
                _mp.append(_target_map)
            _target_map["plans"].append({"id": num_to_plan_id(route_id),
                                         "name": "方案%d" % route_id, "selected": False})  # 导入后名字=方案<占用编号>，编号与名字永远一致
            self.plans_data["maps"] = _mp
            self._save_plans()
        return True

    def _import_plan_menu(self):
        """导入方案入口弹窗：按文件夹全部导入 / 按单文件导入"""
        import tkinter as tk
        _m = tk.Toplevel(self._plan_window if self._plan_window else None)
        _m.title("导入方案")
        _m.attributes("-topmost", True)
        _m.geometry("300x150+300+180")
        tk.Label(_m, text="选择导入方式", font=("微软雅黑", 11)).pack(pady=12)

        def _do_folder():
            _m.destroy()  # 先关"选择导入方式"菜单窗，再执行导入（否则窗口残留挡屏）
            self._import_plan_folder()
        def _do_file():
            _m.destroy()
            self._import_plan_file(None)
        _row = tk.Frame(_m)
        _row.pack(pady=8)
        tk.Button(_row, text="按文件夹全部导入", width=18, command=_do_folder).pack(side="left", padx=6)
        tk.Button(_row, text="按单文件导入", width=14, command=_do_file).pack(side="left", padx=6)
        tk.Button(_m, text="取消", width=8, command=_m.destroy).pack(pady=6)

    def _hide_main_window(self, show):
        """导入/导出时暂时隐藏/恢复主OpenCV窗口("PLAY AND HAPPY")，避免挡住系统选择框"""
        try:
            import ctypes
            hwnd = user32.FindWindowW(None, "PLAY AND HAPPY")
            if hwnd:
                user32.ShowWindow(hwnd, 5 if show else 0)  # 5=SW_SHOW, 0=SW_HIDE
        except Exception as e:
            print("[窗口] 隐藏/恢复主窗口失败:", e)

    def _import_plan_folder(self):
        """按文件夹导入：递归读取目录下所有方案json（v1单方案/v2合集都支持，兼容旧的平铺备份），
        并把YOLO路径改写为各json所在目录的best.onnx（用户要求：跟随导出文件的路径）；带best.onnx则自动安装"""
        import tkinter.filedialog as _fd
        import shutil
        _dir = _fd.askdirectory(title="选择方案备份文件夹（全部导入，支持子文件夹）")
        if not _dir:
            return
        _files = []
        for _root, _dirs, _fns in os.walk(_dir):
            for _fn in sorted(_fns):
                if _fn.lower().endswith(".json"):
                    _files.append(os.path.join(_root, _fn))
        if not _files:
            self._add_log("导入文件夹：没有找到方案json文件")
            return
        _cnt = 0
        _mdl_installed = False
        for _fpath in _files:
            try:
                with open(_fpath, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception as _e:
                print("[导入] %s 解析失败: %s" % (_fpath, _e))
                continue
            if d.get("format") == "MapleBot_plans_v2":
                _plans = d.get("plans", [])
            elif d.get("format") == "MapleBot_plan_v1" and "platforms" in d:
                _plans = [d]
            else:
                print("[导入] %s 不是方案文件，已跳过" % os.path.basename(_fpath))
                continue
            _yolo_dir = os.path.dirname(_fpath)  # YOLO路径改写为导出文件所在目录
            for _pd in _plans:
                if not isinstance(_pd, dict) or "platforms" not in _pd:
                    continue
                _rid0 = _pd.get("route_id", self._next_free_route_id())
                if self._find_plan(num_to_plan_id(_rid0))[0]:
                    _rid0 = self._next_free_route_id()  # 编号被占用→空闲编号，不覆盖现有
                self._apply_plan_data(_pd, _rid0, _yolo_dir)
                _cnt += 1
            # json同目录有best.onnx → 自动安装到本机data（多文件夹首个生效，通常各处一致）
            if not _mdl_installed:
                _mdl = os.path.join(_yolo_dir, "best.onnx")
                if os.path.exists(_mdl):
                    try:
                        shutil.copy2(_mdl, os.path.join(DATA_DIR, "best.onnx"))
                        self._yolo_model_path = os.path.join(DATA_DIR, "best.onnx")
                        self._yolo_net = None
                        _mdl_installed = True
                        print("[导入] 已安装YOLO模型: %s" % _mdl)
                    except Exception as _e:
                        print("[导入] 模型安装失败:", _e)
        self._add_log("文件夹导入完成：%d个方案" % _cnt)
        print("[导入] 文件夹导入完成：%d个方案（%s）" % (_cnt, _dir))
        try:
            win = self._plan_window
            if win:
                win.after(200, lambda: (self._close_window("_plan_window"), self._open_plan_window()))
        except Exception:
            pass

    def _import_plan_file(self, route_id=None):
        """导入方案单文件：v1单方案（指定编号则进该编号，否则弹窗问）；v2多方案合集逐个导入空闲编号"""
        import tkinter.filedialog as _fd
        import tkinter.simpledialog as _sd
        _title = "导入到方案%d" % int(route_id) if route_id is not None else "导入方案"
        path = _fd.askopenfilename(title=_title, filetypes=[("MapleBot方案", "*.json")], initialdir=DATA_DIR)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as _e:
            self._add_log("导入失败(文件读取错误): %s" % _e)
            print("[导入] 读取失败:", _e)
            return
        if data.get("format") == "MapleBot_plans_v2":
            _n = 0
            _yolo_dir = os.path.dirname(path)  # 单文件导入：YOLO路径改写为文件所在目录
            for _pd in data.get("plans", []):
                if not isinstance(_pd, dict) or "platforms" not in _pd:
                    continue
                _rid = _pd.get("route_id", self._next_free_route_id())
                if self._find_plan(num_to_plan_id(_rid))[0]:
                    _rid = self._next_free_route_id()
                self._apply_plan_data(_pd, _rid, _yolo_dir)
                _n += 1
            self._add_log("导入合集完成：%d个方案" % _n)
            print("[导入] 合集%d个方案" % _n)
        elif data.get("format") == "MapleBot_plan_v1" and "platforms" in data:
            if route_id is None:
                route_id = self._next_free_route_id()
                _ans = _sd.askinteger("导入方案", "导入到方案编号(1-99)：", initialvalue=route_id, minvalue=1, maxvalue=99, parent=self._plan_window)
                if not _ans:
                    return
                route_id = int(_ans)
            else:
                route_id = int(route_id)
            self._apply_plan_data(data, route_id, os.path.dirname(path))
            self._add_log("方案%d已导入(%s)" % (route_id, os.path.basename(path)))
            print("[导入] 方案%d（%d平台 %d梯子 %d怪物特征）" % (
                route_id, len(data.get("platforms", [])), len(data.get("ladders", [])), len(data.get("monsters", []))))
        else:
            self._add_log("导入失败：不是有效的MapleBot方案文件")
            return
        try:
            win = self._plan_window
            if win:
                win.after(200, lambda: (self._close_window("_plan_window"), self._open_plan_window()))
        except Exception:
            pass

    def _save(self):
        """保存到当前方案（兼容切换时调用）"""
        self._save_to_route(self.current_route)

    def _switch_route(self, route_id):
        """切换方案：不自动保存，直接加载目标方案数据"""
        if route_id == self.current_route:
            return
        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        self.current_route = route_id
        self.plans_data["current_id"] = num_to_plan_id(route_id)
        pf_file, ld_file = route_files(route_id)
        self.platforms = self._load(pf_file, "platforms")
        self.ladders = self._load(ld_file, "ladders")
        self._load_ladder_templates(route_id)  # 切换方案:换成该方案(地图)的梯子特征,一个地图一份不串图
        # 切换方案时加载对应方案的左右端点
        self._calib_left_pt = None
        self._calib_right_pt = None
        self._calib_top_pt = None
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % route_id)
        if os.path.exists(calib_file):
            try:
                with open(calib_file, "r", encoding="utf-8") as f:
                    cd = json.load(f)
                self._calib_left_pt = cd.get("calib_left")
                self._calib_right_pt = cd.get("calib_right")
                self._calib_top_pt = cd.get("calib_top")
                # 加载倍率数据
                saved_sx = cd.get("calibrated_scale_x", 0)
                saved_sy = cd.get("calibrated_scale_y", 0)
                if saved_sx > 0 and saved_sy > 0:
                    self._calibrated_scale_x = saved_sx
                    self._calibrated_scale_y = saved_sy
                    self._map_screen_scale = saved_sx
                    print("[切换] 方案%d 已加载倍率: X=%.4f Y=%.4f" % (route_id, saved_sx, saved_sy))
                # 人物特征是全局数据（识别自己角色），不随方案切换；权威存储为磁盘 data/char_templates/char_<id>.png，由_load_char_templates加载
                # 此处不再从方案配置的char_template_b64读取并覆盖内存（旧机制会把10张覆盖成1张，记录005/v94已修复）
                # 加载YOLO模型路径
                yolo_path = cd.get("yolo_model_path")
                if yolo_path:
                    self._yolo_model_path = yolo_path
                    self._yolo_net = None
                    print("[切换] 方案%d 已加载YOLO路径: %s" % (route_id, os.path.basename(yolo_path)))
                # 加载绿框配置
                bb = cd.get("blue_box")
                if bb and bb.get("width", 0) > 0:
                    self._blue_box = bb
                    print("[切换] 方案%d 已加载绿框 %dx%d" % (route_id, bb["width"], bb["height"]))
                else:
                    self._blue_box = None
            except Exception as e:
                print("[切换] 方案配置加载失败:", e)
        self._save_plans()
        plan, mp = self._find_plan(num_to_plan_id(route_id))
        pname = plan["name"] if plan else str(route_id)
        mname = mp["name"] if mp else "?"
        print("[切换] %s/%s: %d 平台, %d 梯子" % (mname, pname, len(self.platforms), len(self.ladders)))

    def _clear_route_file(self, route_id):
        """清除指定方案：删除文件，若为当前方案则清空内存"""
        pf_file, ld_file = route_files(route_id)
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % route_id)
        ltpl_file = self._ladder_tpl_path(route_id)
        for f in (pf_file, ld_file, calib_file, ltpl_file):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        if route_id == self.current_route:
            self.platforms = []
            self.ladders = []
            self._ladder_templates = []  # 清当前方案同时清空运行时梯子特征
            self.platform_points = []
            self.ladder_points = []
            self.recording_platform = False
            self.recording_ladder = False
        print("[清除] 方案%d 已删除" % route_id)

    def _clear_route(self):
        """清除当前方案（保留兼容）"""
        self._clear_route_file(self.current_route)

    def _pop_platform(self):
        """删除最后一个平台段"""
        if self.platforms:
            removed = self.platforms.pop()
            print("[清平台] 删除最后一个平台 id=%s (剩余 %d)" % (removed.get("id"), len(self.platforms)))
        else:
            print("[清平台] 没有可删除的平台")

    def _pop_ladder(self):
        """删除最后一个梯子段"""
        if self.ladders:
            removed = self.ladders.pop()
            print("[清梯子] 删除最后一个梯子 id=%s (剩余 %d)" % (removed.get("id"), len(self.ladders)))
        else:
            print("[清梯子] 没有可删除的梯子")

    def _toggle_mode(self):
        """切换运行方式：手动 <-> 随机"""
        self.route_mode = "随机" if self.route_mode == "手动" else "手动"
        self._save_route_config()
        if self.route_mode == "随机":
            self._start_random()
        else:
            self._stop_random()
        print("[方式] 切换为: %s" % self.route_mode)

    def _dropdown_items(self):
        """返回当前下拉菜单的菜单项列表（仅mode下拉保留）"""
        if self._dropdown == "mode":
            return ["手动", "随机"]
        return []

    # ===== 方案系统独立窗口 =====

    def _ensure_tk_root(self):
        import tkinter as tk
        if not hasattr(self, '_tk_root') or self._tk_root is None:
            try:
                self._tk_root = tk.Tk()
                self._tk_root.withdraw()
                _debug_log("[方案窗口] tk root创建成功")
            except Exception as e:
                _debug_log("[方案窗口] tk root创建失败: %s" % e)
                return False
        return True

    def _position_window(self, win, w, h):
        """把tk窗口定位在OpenCV窗口上方居中"""
        try:
            import win32gui
            hwnd = win32gui.FindWindow(None, "PLAY AND HAPPY")
            if hwnd:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                cx = left + (right - left) // 2
                cy = top + max(0, (bottom - top) // 2 - h // 2)
                win.geometry("%dx%d+%d+%d" % (w, h, cx - w // 2, cy))
                return
        except Exception:
            pass
        # 兜底：屏幕居中
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))

    def _show_msg(self, kind, title, message, parent=None):
        """固定位置确认框：无标题栏，锁定在脚本窗口中心，不能拖动"""
        import tkinter as tk
        dlg = tk.Toplevel(self._tk_root)
        dlg.overrideredirect(True)  # 去掉标题栏，不能拖动
        dlg.attributes("-topmost", True)
        dlg.grab_set()
        # 计算尺寸
        lines = message.split("\n")
        w = max(280, min(450, max(len(l) * 15 for l in lines) + 80))
        h = 110 + len(lines) * 22
        # 定位到脚本窗口中心
        try:
            import win32gui
            hwnd = win32gui.FindWindow(None, "PLAY AND HAPPY")
            if hwnd:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                cx = left + (right - left) // 2
                cy = top + (bottom - top) // 2
                dlg.geometry("%dx%d+%d+%d" % (w, h, cx - w // 2, cy - h // 2))
            else:
                dlg.geometry("%dx%d" % (w, h))
        except Exception:
            dlg.geometry("%dx%d" % (w, h))
        # 边框和背景
        dlg.configure(bg="#404040")
        outer = tk.Frame(dlg, bg="#606060", bd=1)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        inner = tk.Frame(outer, bg="#404040")
        inner.pack(fill="both", expand=True)
        # 标题
        tk.Label(inner, text=title, font=("微软雅黑", 10, "bold"), bg="#404040", fg="white").pack(pady=(10, 5))
        # 消息
        tk.Label(inner, text=message, font=("微软雅黑", 9), bg="#404040", fg="white", wraplength=w-60, justify="left").pack(pady=5, padx=20)
        # 按钮
        btn_frame = tk.Frame(inner, bg="#404040")
        btn_frame.pack(pady=10)
        result = {"val": None}
        def on_yes():
            result["val"] = True
            dlg.destroy()
        def on_no():
            result["val"] = False
            dlg.destroy()
        if kind == "yesno":
            tk.Button(btn_frame, text="是", width=8, command=on_yes, bg="#2E7D32", fg="white", relief="flat").pack(side="left", padx=15)
            tk.Button(btn_frame, text="否", width=8, command=on_no, bg="#757575", fg="white", relief="flat").pack(side="left", padx=15)
            dlg.bind("<Return>", lambda e: on_yes())
            dlg.bind("<Escape>", lambda e: on_no())
        else:
            tk.Button(btn_frame, text="确定", width=8, command=on_yes, bg="#2E7D32", fg="white", relief="flat").pack(side="left", padx=15)
            dlg.bind("<Return>", lambda e: on_yes())
            dlg.bind("<Escape>", lambda e: on_yes())
        dlg.wait_window()
        return result["val"]

    def _open_save_window(self):
        """打开保存方案窗口：有地图则列表选择，无地图则输入新地图名"""
        import tkinter as tk
        from tkinter import messagebox
        print('[怪物特征弹窗] 步骤1: 开始创建弹窗')
        if not self._ensure_tk_root():
            print('[怪物特征弹窗] 步骤1失败: tk_root创建失败')
            return
        print('[怪物特征弹窗] 步骤2: tk_root已就绪')
        if self._save_window is not None:
            try:
                self._save_window.destroy()
            except Exception:
                pass
            self._save_window = None
        try:
            win = tk.Toplevel(self._tk_root)
        except Exception as e:
            _debug_log("[方案窗口] Toplevel创建失败: %s" % e)
            return
        self._save_window = win
        _debug_log("[方案窗口] 保存窗口已创建")
        win.title("保存方案")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_window("_save_window"))

        maps = self.plans_data.get("maps", [])
        if not maps:
            win.geometry("280x200")
            self._position_window(win, 280, 200)
            # 没有地图：显示输入框
            tk.Label(win, text="请输入当前地图名", font=("微软雅黑", 12)).pack(pady=(20, 10))
            entry = tk.Entry(win, font=("微软雅黑", 12), width=20, bg="black", fg="white",
                             insertbackground="white", relief="solid", bd=1)
            entry.pack(pady=5)
            entry.focus_set()

            def do_save():
                name = entry.get().strip()
                if not name:
                    self._show_msg("warning", "提示", "请输入地图名")
                    return
                plan = self._create_plan(name)
                if plan is None:
                    self._show_msg("warning", "提示", "地图或方案数量已满")
                    return
                self._save_to_route(plan_id_to_num(plan["id"]))
                self._show_msg("info", "成功", "已保存到地图「%s」的「%s」" % (name, plan["name"]), parent=win)
                self._close_window("_save_window")

            btn_frame = tk.Frame(win)
            btn_frame.pack(pady=20)
            tk.Button(btn_frame, text="保存", width=8, command=do_save).pack(side="left", padx=10)
            tk.Button(btn_frame, text="取消", width=8, command=lambda: self._close_window("_save_window")).pack(side="left", padx=10)
            win.update()
        else:
            # 有地图：单击选中 + 保存按钮
            win.geometry("280x380")
            self._position_window(win, 280, 380)
            tk.Label(win, text="选择地图后点保存", font=("微软雅黑", 11)).pack(pady=(10, 5))
            list_frame = tk.Frame(win)
            list_frame.pack(fill="both", expand=True, padx=10, pady=5)
            scrollbar = tk.Scrollbar(list_frame)
            scrollbar.pack(side="right", fill="y")
            listbox = tk.Listbox(list_frame, font=("微软雅黑", 11), yscrollcommand=scrollbar.set,
                                 selectbackground="#FFD700", selectforeground="black", height=12,
                                 exportselection=False)
            for mp in maps:
                listbox.insert("end", "%s (%d个方案)" % (mp["name"], len(mp["plans"])))
            listbox.pack(side="left", fill="both", expand=True)
            scrollbar.config(command=listbox.yview)

            def do_save_to_map():
                sel = listbox.curselection()
                if not sel:
                    self._show_msg("warning", "提示", "请先选择一个地图")
                    return
                mp = maps[sel[0]]
                if len(mp["plans"]) >= 10:
                    self._show_msg("warning", "提示", "「%s」方案数量已满（10个）" % mp["name"])
                    return
                plan = self._create_plan(mp["name"])
                if plan is None:
                    self._show_msg("warning", "提示", "方案数量已满")
                    return
                self._save_to_route(plan_id_to_num(plan["id"]))
                self._show_msg("info", "成功", "已保存到「%s」的「%s」" % (mp["name"], plan["name"]), parent=win)
                self._close_window("_save_window")

            # 底部按钮：保存 | 新地图 | 关闭
            btn_frame = tk.Frame(win)
            btn_frame.pack(pady=8)
            tk.Button(btn_frame, text="保存", width=7, command=do_save_to_map).pack(side="left", padx=5)
            tk.Button(btn_frame, text="新地图", width=7,
                      command=lambda: (self._close_window("_save_window"), self._show_new_map_input())).pack(side="left", padx=5)
            tk.Button(btn_frame, text="关闭", width=7, command=lambda: self._close_window("_save_window")).pack(side="left", padx=5)
            win.update()

    def _show_new_map_input(self):
        """显示新地图输入窗口（从保存窗口点'新地图'进入）"""
        import tkinter as tk
        from tkinter import messagebox
        win = tk.Toplevel(self._tk_root)
        self._save_window = win
        win.title("新地图")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        self._position_window(win, 280, 160)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_window("_save_window"))
        tk.Label(win, text="请输入当前地图名", font=("微软雅黑", 12)).pack(pady=(20, 10))
        entry = tk.Entry(win, font=("微软雅黑", 12), width=20, bg="black", fg="white",
                         insertbackground="white", relief="solid", bd=1)
        entry.pack(pady=5)
        entry.focus_set()

        def do_save():
            name = entry.get().strip()
            if not name:
                self._show_msg("warning", "提示", "请输入地图名")
                return
            if self._find_map(name):
                self._show_msg("warning", "提示", "地图名已存在")
                return
            plan = self._create_plan(name)
            if plan is None:
                self._show_msg("warning", "提示", "数量已满")
                return
            self._save_to_route(plan_id_to_num(plan["id"]))
            self._show_msg("info", "成功", "已保存到地图「%s」" % name)
            self._close_window("_save_window")

        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="保存", width=8, command=do_save).pack(side="left", padx=10)
        tk.Button(btn_frame, text="取消", width=8, command=lambda: self._close_window("_save_window")).pack(side="left", padx=10)
        win.update()

    def _open_plan_window(self):
        """打开方案管理窗口：按地图分组，单击激活/双击改名/勾选多选"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if self._plan_window is not None:
            try:
                self._plan_window.destroy()
            except Exception:
                pass
            self._plan_window = None
        win = tk.Toplevel(self._tk_root)
        self._plan_window = win
        win.title("方案管理")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_window("_plan_window"))
        self._position_window(win, 320, 460)

        # 底部按钮：必须先pack(side=bottom)占住底部空间，滚动区再填剩余
        # （若滚动区先pack且expand=True，会把整个窗口吃掉，按钮行分不到空间=看不到）
        btn_row = tk.Frame(win)
        btn_row.pack(side="bottom", fill="x", pady=4)
        tk.Button(btn_row, text="导出方案", width=9, command=self._export_plan_dialog).pack(side="left", padx=3)
        tk.Button(btn_row, text="导入方案", width=9, command=self._import_plan_menu).pack(side="left", padx=3)
        tk.Button(btn_row, text="关闭", width=9, command=lambda: self._close_window("_plan_window")).pack(side="left", padx=3)

        # 滚动区域
        canvas = tk.Canvas(win, highlightthickness=0)
        scrollbar = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        scrollbar.pack(side="right", fill="y")
        # 鼠标滚轮
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)

        current_id = self.plans_data.get("current_id", "")
        self._plan_check_vars = {}  # plan_id -> BooleanVar
        self._plan_row_widgets = {}  # plan_id -> (row, name_lbl, chk)

        for mp in self.plans_data.get("maps", []):
            # 地图名标题行（灰色底，双击改名）
            map_frame = tk.Frame(scroll_frame, bg="#C0C0C0")
            map_frame.pack(fill="x", pady=(8, 0))
            map_label = tk.Label(map_frame, text=mp["name"], font=("微软雅黑", 10, "bold"),
                                 bg="#C0C0C0", fg="black", anchor="w")
            map_label.pack(side="left", fill="x", expand=True, padx=5, pady=3)

            def make_map_rename(mname, lbl):
                def on_double(event):
                    entry = tk.Entry(lbl.master, font=("微软雅黑", 10), bg="black", fg="white",
                                     insertbackground="white")
                    entry.insert(0, mname)
                    entry.select_range(0, "end")
                    entry.focus_set()
                    lbl.pack_forget()
                    entry.pack(side="left", fill="x", expand=True, padx=5, pady=3)
                    def confirm(event=None):
                        new_name = entry.get().strip()
                        if new_name and new_name != mname and not self._find_map(new_name):
                            self._rename_map(mname, new_name)
                        entry.destroy()
                        lbl.config(text=new_name if new_name else mname)
                        lbl.pack(side="left", fill="x", expand=True, padx=5, pady=3)
                    entry.bind("<Return>", confirm)
                    entry.bind("<FocusOut>", confirm)
                return on_double
            map_label.bind("<Double-Button-1>", make_map_rename(mp["name"], map_label))

            # 方案列表
            for plan in mp["plans"]:
                pid = plan["id"]
                row = tk.Frame(scroll_frame)
                row.pack(fill="x")
                is_current = (pid == current_id)
                bg = "#FFD700" if is_current else "white"
                var = tk.BooleanVar(value=plan.get("selected", False))
                self._plan_check_vars[pid] = var

                def make_toggle(p):
                    def toggle():
                        self._set_plan_selected(p, self._plan_check_vars[p].get())
                    return toggle
                chk = tk.Checkbutton(row, variable=var, command=make_toggle(pid), bg=bg)
                chk.pack(side="left")

                name_lbl = tk.Label(row, text=plan["name"], font=("微软雅黑", 10),
                                    bg=bg, fg="black", anchor="w")
                name_lbl.pack(side="left", fill="x", expand=True, pady=2)
                self._plan_row_widgets[pid] = (row, name_lbl, chk)

                def make_activate(pid_):
                    def on_click(event):
                        self._switch_route(plan_id_to_num(pid_))
                        # 不关闭窗口，直接更新所有行颜色
                        for rid, (rrow, rlbl, rchk) in self._plan_row_widgets.items():
                            c = "#FFD700" if rid == pid_ else "white"
                            rrow.config(bg=c)
                            rlbl.config(bg=c)
                            rchk.config(bg=c)
                    return on_click
                for w in (name_lbl, row):
                    w.bind("<Button-1>", make_activate(pid))

                def make_rename(pid_, lbl):
                    def on_double(event):
                        entry = tk.Entry(lbl.master, font=("微软雅黑", 10), bg="black", fg="white",
                                         insertbackground="white")
                        old_name = lbl.cget("text")
                        entry.insert(0, old_name)
                        entry.select_range(0, "end")
                        entry.focus_set()
                        lbl.pack_forget()
                        entry.pack(side="left", fill="x", expand=True, pady=2)
                        def confirm(event=None):
                            new_name = entry.get().strip()
                            if new_name:
                                self._rename_plan(pid_, new_name)
                            entry.destroy()
                            lbl.config(text=new_name if new_name else old_name)
                            lbl.pack(side="left", fill="x", expand=True, pady=2)
                        entry.bind("<Return>", confirm)
                        entry.bind("<FocusOut>", confirm)
                    return on_double
                name_lbl.bind("<Double-Button-1>", make_rename(pid, name_lbl))


        win.update()

    def _export_plan_dialog(self):
        """导出方案弹窗：列出全部方案打勾（默认不勾），确定后把勾选的方案导出到目录（每个方案一个同名文件夹+best.onnx）"""
        import tkinter as tk
        import tkinter.filedialog as _fd
        _dlg = tk.Toplevel(self._plan_window if self._plan_window else None)
        _dlg.title("导出方案（勾选要导出的）")
        _dlg.attributes("-topmost", True)
        _dlg.geometry("380x420+200+120")
        _vars = []
        _all_plans = []
        for _m in self.plans_data.get("maps", []):
            for _p in _m.get("plans", []):
                _all_plans.append((_m["name"], _p))
        if not _all_plans:
            tk.Label(_dlg, text="还没有方案，先保存一个再导出").pack(pady=20)
            return
        tk.Label(_dlg, text="勾选要导出的方案（没勾的不导出）", font=("微软雅黑", 9)).pack(anchor="w", padx=8)
        _box = tk.Frame(_dlg)
        _box.pack(fill="both", expand=True, padx=8, pady=6)
        for _mname, _p in _all_plans:
            _v = tk.BooleanVar(value=False)  # 默认不勾，用户按需打勾
            _vars.append((plan_id_to_num(_p["id"]), _v))
            tk.Checkbutton(_box, text="%s / %s  (方案%d)" % (_mname, _p["name"], plan_id_to_num(_p["id"])),
                           variable=_v, font=("微软雅黑", 9), anchor="w").pack(fill="x")
        _sub = tk.Frame(_dlg)
        _sub.pack(pady=6)
        def _confirm():
            _ids = [rid for rid, _v in _vars if _v.get()]
            if not _ids:
                return
            _dlg.destroy()
            self._ask_export_dir(_ids)
        tk.Button(_sub, text="确定导出", width=10, command=_confirm).pack(side="left", padx=6)
        tk.Button(_sub, text="取消", width=8, command=_dlg.destroy).pack(side="left", padx=6)

    def _ask_export_dir(self, route_ids):
        """导出目标目录固定为脚本根目录（用户要求：定死不改动，避免best.onnx路径失效/不生效）。
        app_dir() 在跑.py时=脚本所在目录；直接导出到脚本根目录，不再弹目录选择、不再浏览/记忆"""
        _root = app_dir()
        self._export_plans_multi(route_ids, _root)

    def _plan_payload_v1(self, route_id):
        """生成单个方案的数据包（导出用）：平台+梯子+怪物特征+calib(端点/倍率/YOLO路径)"""
        pf_file, ld_file = route_files(route_id)
        calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % route_id)
        monster_file = os.path.join(DATA_DIR, "route_%03d_monsters.json" % route_id)
        plan, mp = self._find_plan(num_to_plan_id(route_id))
        data = {"format": "MapleBot_plan_v1", "route_id": route_id,
                "plan_name": plan["name"] if plan else ("方案%d" % route_id),
                "map_name": mp["name"] if mp else "",
                "platforms": self._load(pf_file, "platforms"),
                "ladders": self._load(ld_file, "ladders"),
                "monsters": self._load(monster_file, "monsters"),
                "ladder_templates": self._load(self._ladder_tpl_path(route_id), "templates"),  # 梯子特征随方案导出
                "ladder_tpl_sim": getattr(self, '_ladder_tpl_sim', LADDER_TPL_DEFAULT_SIM),
                "calib": {}}
        try:
            with open(calib_file, "r", encoding="utf-8") as f:
                data["calib"] = json.load(f)
        except Exception:
            pass
        return data

    def _export_plans_multi(self, route_ids, out_dir):
        """导出勾选的方案为"整理好的目录"（备份/分发用）：每个方案一个文件夹（文件夹名=方案名），
        内含方案json + best.onnx（模型与方案同目录，导入时按此目录改写YOLO路径）"""
        import shutil
        if not route_ids:
            return
        _dir = out_dir
        # YOLO模型来源：优先当前加载路径，兜底data/best.onnx
        _yolo_path = None
        if getattr(self, '_yolo_model_path', None) and os.path.exists(self._yolo_model_path):
            _yolo_path = self._yolo_model_path
        elif os.path.exists(os.path.join(DATA_DIR, "best.onnx")):
            _yolo_path = os.path.join(DATA_DIR, "best.onnx")
        _wrote = []
        for _rid in route_ids:
            _payload = self._plan_payload_v1(_rid)
            _mname = (_payload["map_name"] or "默认地图").replace("\\", "").replace("/", "").replace(":", "").replace("*", "").replace("?", "").replace("\"", "").replace("<", "").replace(">", "").replace("|", "")
            _pname = (_payload["plan_name"] or ("方案%d" % _rid)).replace("\\", "").replace("/", "").replace(":", "").replace("*", "").replace("?", "").replace("\"", "").replace("<", "").replace(">", "").replace("|", "")
            _fname = "方案%d_%s_%s.json" % (_rid, _mname, _pname)
            # 每个方案一个独立文件夹，文件夹名=方案名；重名时追加编号防覆盖（用户要求）
            _pdir = os.path.join(_dir, _pname)
            if os.path.exists(_pdir):
                _pdir = os.path.join(_dir, "%s(方案%d)" % (_pname, _rid))
            os.makedirs(_pdir, exist_ok=True)
            with open(os.path.join(_pdir, _fname), "w", encoding="utf-8") as f:
                json.dump(_payload, f, ensure_ascii=False, indent=2)
            # best.onnx 与方案json放同一文件夹（导入时按该目录改写YOLO路径）
            if _yolo_path:
                try:
                    shutil.copy2(_yolo_path, os.path.join(_pdir, "best.onnx"))
                except Exception as _e:
                    print("[导出] 模型复制失败:", _e)
            _wrote.append(os.path.join(_pdir, _fname))
        self._add_log("已导出%d个方案到: %s" % (len(_wrote), _dir))
        print("[导出] 整理完成 %d个方案（每方案一文件夹含best.onnx）→ %s" % (len(_wrote), _dir))


    def _open_char_feature_window(self):
        """打开人物特征管理弹窗：左右分栏，左边特征列表(含偏移X/Y)，右边操作区"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if getattr(self, '_char_feature_window', None) is not None:
            try:
                self._char_feature_window.destroy()
            except Exception:
                pass
            self._char_feature_window = None
        win = tk.Toplevel(self._tk_root)
        self._char_feature_window = win
        win.title("人物特征管理")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        def _on_char_win_close():
            """X关闭：恢复原始偏移值，取消所有防抖定时器"""
            for _tid, _after_id in list(_char_offset_timers.items()):
                try:
                    win.after_cancel(_after_id)
                except Exception:
                    pass
            _char_offset_timers.clear()
            for _t in self._char_templates:
                if _t["id"] in _char_orig_offsets:
                    _ox, _oy = _char_orig_offsets[_t["id"]]
                    _t["offset_x"] = _ox
                    _t["offset_y"] = _oy
            self._close_window("_char_feature_window")
        win.protocol("WM_DELETE_WINDOW", _on_char_win_close)
        self._position_window(win, 520, 420)

        # === 左边：特征列表（滚动区域）===
        left_frame = tk.Frame(win, width=340, height=380)
        left_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        left_frame.pack_propagate(False)

        tk.Label(left_frame, text="特征列表（每个特征独立偏移到人物脚）", font=("微软雅黑", 9, "bold")).pack(anchor="w")

        # 滚动区域
        canvas = tk.Canvas(left_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # 保存输入框引用，关闭时读取
        self._char_offset_entries = {}  # tpl_id -> (entry_x, entry_y)
        _char_orig_offsets = {}  # 原始偏移值，X关闭时恢复 {tpl_id: (ox, oy)}
        _char_offset_timers = {}  # 防抖定时器 {tpl_id: after_id}
        for _t in self._char_templates:
            _char_orig_offsets[_t["id"]] = (_t.get("offset_x", 0), _t.get("offset_y", 0))

        def _apply_char_offset(tid):
            """防抖到期后应用偏移值"""
            if tid not in self._char_offset_entries:
                return
            ex, ey = self._char_offset_entries[tid]
            try:
                ox = int(ex.get() or "0")
                oy = int(ey.get() or "0")
            except ValueError:
                ox, oy = 0, 0
            for _t in self._char_templates:
                if _t["id"] == tid:
                    _t["offset_x"] = ox
                    _t["offset_y"] = oy
                    break
            _char_offset_timers.pop(tid, None)

        def _on_char_offset_key(tid):
            """偏移输入框按键事件：2秒防抖后生效"""
            if tid in _char_offset_timers:
                win.after_cancel(_char_offset_timers[tid])
            _char_offset_timers[tid] = win.after(2000, lambda: _apply_char_offset(tid))

        def refresh_list():
            """刷新特征列表"""
            for w in scroll_frame.winfo_children():
                w.destroy()
            self._char_offset_entries.clear()
            if not self._char_templates:
                tk.Label(scroll_frame, text="暂无特征，点击右边'添加特征'按钮",
                         font=("微软雅黑", 9), fg="gray").pack(pady=20)
                return
            for idx, tpl in enumerate(self._char_templates):
                row = tk.Frame(scroll_frame, relief="solid", borderwidth=1)
                row.pack(fill="x", pady=2, padx=2)

                # 特征ID + 方向
                dir_text = "左" if tpl.get("direction", "right") == "left" else "右"
                dir_color = "#FF9800" if tpl.get("direction", "right") == "left" else "#2196F3"
                tk.Label(row, text="#%d" % tpl["id"], font=("微软雅黑", 9, "bold"),
                         width=3).pack(side="left")
                tk.Label(row, text=dir_text, font=("微软雅黑", 8, "bold"),
                         fg="white", bg=dir_color, width=2).pack(side="left", padx=2)

                # 偏移X
                tk.Label(row, text="X:", font=("微软雅黑", 9)).pack(side="left")
                entry_x = tk.Entry(row, width=5, font=("微软雅黑", 9))
                entry_x.insert(0, str(tpl.get("offset_x", 0)))
                entry_x.pack(side="left", padx=2)
                entry_x.bind("<KeyRelease>", lambda e, tid=tpl["id"]: _on_char_offset_key(tid))

                # 偏移Y
                tk.Label(row, text="Y:", font=("微软雅黑", 9)).pack(side="left")
                entry_y = tk.Entry(row, width=5, font=("微软雅黑", 9))
                entry_y.insert(0, str(tpl.get("offset_y", 0)))
                entry_y.pack(side="left", padx=2)
                entry_y.bind("<KeyRelease>", lambda e, tid=tpl["id"]: _on_char_offset_key(tid))

                self._char_offset_entries[tpl["id"]] = (entry_x, entry_y)

                # 尺寸显示
                tk.Label(row, text="%dx%d" % (tpl["width"], tpl["height"]),
                         font=("微软雅黑", 8), fg="gray").pack(side="left", padx=5)

                # === 截图缩略图(新增)：显示该特征模板缩略图，删除时随refresh一起消失 ===
                try:
                    import tkinter as _tkimg
                    from PIL import Image as _PImage, ImageTk as _PITk
                    _pil = _PImage.fromarray(tpl["img"])
                    _pil.thumbnail((30, 30))
                    _photo = _PITk.PhotoImage(_pil)
                    _thumb = tk.Label(row, image=_photo, width=30, height=30,
                                      relief="solid", borderwidth=1, bg="white")
                    _thumb.image = _photo  # 防GC
                    _thumb.pack(side="left", padx=5)
                except Exception as _te:
                    print("[缩略图] 异常:", _te)

                # 删除按钮
                def make_delete(tid):
                    def on_delete():
                        if messagebox.askyesno("确认", "删除特征#%d？" % tid):
                            for i, t in enumerate(self._char_templates):
                                if t["id"] == tid:
                                    self._delete_char_template(i)
                                    break
                            refresh_list()
                    return on_delete
                tk.Button(row, text="删", width=3, command=make_delete(tpl["id"]),
                          bg="#FF6666", fg="white").pack(side="right", padx=2)

        refresh_list()

        # === 右边：操作区 ===
        right_frame = tk.Frame(win, width=160, height=380)
        right_frame.pack(side="right", fill="y", padx=5, pady=5)
        right_frame.pack_propagate(False)

        def on_add(direction):
            # 先关闭弹窗，避免cv2.selectROI和tkinter冲突导致闪退
            try:
                win.withdraw()
            except:
                pass
            self._capture_character_feature(direction=direction)
            try:
                win.deiconify()
                win.lift()
            except:
                pass
            refresh_list()

        tk.Button(right_frame, text="添加向左特征", width=14, height=1,
                  command=lambda: on_add("left"), bg="#FF9800", fg="white").pack(pady=2)
        tk.Button(right_frame, text="添加向右特征", width=14, height=1,
                  command=lambda: on_add("right"), bg="#2196F3", fg="white").pack(pady=2)

        def on_clear_all():
            if messagebox.askyesno("确认", "清除全部特征？"):
                self._clear_character_features()
                refresh_list()
        tk.Button(right_frame, text="全部删除", width=14, height=2,
                  command=on_clear_all, bg="#FF6666", fg="white").pack(pady=5)

        def on_save_and_close():
            """保存所有偏移和方向并关闭"""
            for tid, (ex, ey) in self._char_offset_entries.items():
                try:
                    ox = int(ex.get() or "0")
                    oy = int(ey.get() or "0")
                except ValueError:
                    ox, oy = 0, 0
                for t in self._char_templates:
                    if t["id"] == tid:
                        t["offset_x"] = ox
                        t["offset_y"] = oy
                        break
            self._save_char_meta()
            try:
                self._match_sim["char"] = _char_sim_entry.get().strip() or "0.70"
                self._save_match_sim()
            except Exception:
                pass
            self._add_log("人物特征偏移已保存")
            self._close_window("_char_feature_window")
        # 人物识别相似度调节(默认0.7，识别不到可手动调低如0.6)——用户2026-09-06
        _sim_frame = tk.Frame(right_frame)
        _sim_frame.pack(fill="x", pady=(4, 2))
        tk.Label(_sim_frame, text="相似度", font=("微软雅黑", 9, "bold")).pack(side="left", padx=4)
        _char_sim_entry = tk.Entry(_sim_frame, width=6, font=("微软雅黑", 9))
        _char_sim_entry.insert(0, self._match_sim.get("char", "0.70"))
        _char_sim_entry.pack(side="left", padx=4)
        tk.Label(_sim_frame, text="0.7默认，识别不到可调0.6", font=("微软雅黑", 7), fg="gray").pack(side="left", padx=2)
        tk.Button(right_frame, text="保存并关闭", width=14, height=2,
                  command=on_save_and_close, bg="#2196F3", fg="white").pack(pady=5)

        # 说明
        info = tk.Label(right_frame, text='说明：\n左=人物向左走\n右=人物向右走\n每方向最多5个\n偏移=特征中心到脚\n匹配时自动选朝向',
                        font=('微软雅黑', 8), fg='gray', justify='left', wraplength=140)
        info.pack(pady=10, anchor="n")

        win.update()

    def _open_monster_feature_window(self):
        """打开怪物特征管理弹窗：左右分栏，左边特征列表(含偏移X/Y)，右边操作区
        怪物特征和YOLO检测合并显示小地图紫点"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if getattr(self, '_monster_feature_window', None) is not None:
            try:
                self._monster_feature_window.destroy()
            except Exception:
                pass
            self._monster_feature_window = None
        print('[怪物特征弹窗] 步骤3: 创建Toplevel窗口')
        win = tk.Toplevel(self._tk_root)
        self._monster_feature_window = win
        win.title("怪物特征管理")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        print('[怪物特征弹窗] 步骤4: 设置X关闭按钮回调')
        def on_close_monster_win():
            """关闭怪物特征弹窗（确保X按钮有效）：恢复原始偏移值，取消所有防抖定时器"""
            for _tid, _after_id in list(_monster_offset_timers.items()):
                try:
                    win.after_cancel(_after_id)
                except Exception:
                    pass
            _monster_offset_timers.clear()
            for _t in self._monster_templates:
                if _t["id"] in _monster_orig_offsets:
                    _ox, _oy = _monster_orig_offsets[_t["id"]]
                    _t["offset_x"] = _ox
                    _t["offset_y"] = _oy
            try:
                win.destroy()
            except Exception:
                pass
            self._monster_feature_window = None
        win.protocol("WM_DELETE_WINDOW", on_close_monster_win)
        print('[怪物特征弹窗] 步骤5: 定位窗口')
        self._position_window(win, 520, 420)
        print('[怪物特征弹窗] 步骤6: 创建左边特征列表')

        # === 左边：特征列表（滚动区域）===
        left_frame = tk.Frame(win, width=340, height=380)
        left_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        left_frame.pack_propagate(False)
        tk.Label(left_frame, text="怪物特征列表（每个特征独立偏移到怪物中心）", font=("微软雅黑", 9, "bold")).pack(anchor="w")

        canvas = tk.Canvas(left_frame, highlightthickness=0)
        scrollbar = tk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._monster_offset_entries = {}
        _monster_orig_offsets = {}  # 原始偏移值，X关闭时恢复 {tpl_id: (ox, oy)}
        _monster_offset_timers = {}  # 防抖定时器 {tpl_id: after_id}
        for _t in self._monster_templates:
            _monster_orig_offsets[_t["id"]] = (_t.get("offset_x", 0), _t.get("offset_y", 0))

        def _apply_monster_offset(tid):
            """防抖到期后应用偏移值"""
            if tid not in self._monster_offset_entries:
                return
            ex, ey = self._monster_offset_entries[tid]
            try:
                ox = int(ex.get() or "0")
                oy = int(ey.get() or "0")
            except ValueError:
                ox, oy = 0, 0
            for _t in self._monster_templates:
                if _t["id"] == tid:
                    _t["offset_x"] = ox
                    _t["offset_y"] = oy
                    break
            _monster_offset_timers.pop(tid, None)

        def _on_monster_offset_key(tid):
            """偏移输入框按键事件：2秒防抖后生效"""
            if tid in _monster_offset_timers:
                win.after_cancel(_monster_offset_timers[tid])
            _monster_offset_timers[tid] = win.after(2000, lambda: _apply_monster_offset(tid))

        def refresh_list():
            """刷新特征列表"""
            for w in scroll_frame.winfo_children():
                w.destroy()
            self._monster_offset_entries.clear()
            if not self._monster_templates:
                tk.Label(scroll_frame, text="暂无怪物特征，点击右边按钮添加",
                         font=("微软雅黑", 9), fg="gray").pack(pady=20)
                return
            for idx, tpl in enumerate(self._monster_templates):
                row = tk.Frame(scroll_frame, relief="solid", borderwidth=1)
                row.pack(fill="x", pady=2, padx=2)
                dir_text = "左" if tpl.get("direction", "right") == "left" else "右"
                dir_color = "#FF9800" if tpl.get("direction", "right") == "left" else "#2196F3"
                tk.Label(row, text="#%d" % tpl["id"], font=("微软雅黑", 9, "bold"), width=3).pack(side="left")
                tk.Label(row, text=dir_text, font=("微软雅黑", 8, "bold"), fg="white", bg=dir_color, width=2).pack(side="left", padx=2)
                tk.Label(row, text="X:", font=("微软雅黑", 9)).pack(side="left")
                entry_x = tk.Entry(row, width=5, font=("微软雅黑", 9))
                entry_x.insert(0, str(tpl.get("offset_x", 0)))
                entry_x.pack(side="left", padx=2)
                entry_x.bind("<KeyRelease>", lambda e, tid=tpl["id"]: _on_monster_offset_key(tid))
                tk.Label(row, text="Y:", font=("微软雅黑", 9)).pack(side="left")
                entry_y = tk.Entry(row, width=5, font=("微软雅黑", 9))
                entry_y.insert(0, str(tpl.get("offset_y", 0)))
                entry_y.pack(side="left", padx=2)
                entry_y.bind("<KeyRelease>", lambda e, tid=tpl["id"]: _on_monster_offset_key(tid))
                self._monster_offset_entries[tpl["id"]] = (entry_x, entry_y)
                tk.Label(row, text="%dx%d" % (tpl["width"], tpl["height"]), font=("微软雅黑", 8), fg="gray").pack(side="left", padx=5)
                # === 截图缩略图(新增)：显示该怪物特征模板缩略图，删除时随refresh消失 ===
                try:
                    from PIL import Image as _PImage, ImageTk as _PITk
                    _pil = _PImage.fromarray(tpl["img"])
                    _pil.thumbnail((30, 30))
                    _photo = _PITk.PhotoImage(_pil)
                    _thumb = tk.Label(row, image=_photo, width=30, height=30,
                                      relief="solid", borderwidth=1, bg="white")
                    _thumb.image = _photo
                    _thumb.pack(side="left", padx=5)
                except Exception as _te:
                    print("[怪物缩略图] 异常:", _te)
                def make_delete(tid):
                    def on_delete():
                        if messagebox.askyesno("确认", "删除怪物特征#%d？" % tid):
                            for i, t in enumerate(self._monster_templates):
                                if t["id"] == tid:
                                    self._delete_monster_template(i)
                                    break
                            refresh_list()
                    return on_delete
                tk.Button(row, text="删", width=3, command=make_delete(tpl["id"]), bg="#FF6666", fg="white").pack(side="right", padx=2)

        refresh_list()

        # === 右边：操作区 ===
        right_frame = tk.Frame(win, width=160, height=380)
        right_frame.pack(side="right", fill="y", padx=5, pady=5)
        right_frame.pack_propagate(False)

        def on_add(direction):
            try:
                win.withdraw()
            except:
                pass
            self._capture_monster_feature(direction=direction)
            try:
                win.deiconify()
                win.lift()
            except:
                pass
            refresh_list()

        tk.Button(right_frame, text="添加向左特征", width=14, height=1, command=lambda: on_add("left"), bg="#FF9800", fg="white").pack(pady=2)
        tk.Button(right_frame, text="添加向右特征", width=14, height=1, command=lambda: on_add("right"), bg="#2196F3", fg="white").pack(pady=2)

        def on_clear_all():
            if messagebox.askyesno("确认", "清除全部怪物特征？"):
                self._clear_monster_features()
                refresh_list()
        tk.Button(right_frame, text="全部删除", width=14, height=2, command=on_clear_all, bg="#FF6666", fg="white").pack(pady=5)
        # 梯子特征入口(主控制面板无空位,从特征弹窗进入;梯子特征随方案永久存,只用于上梯近距对齐X)
        tk.Button(right_frame, text="梯子特征管理", width=14, height=1,
                  command=lambda: self._open_ladder_feature_window(), bg="#009688", fg="white").pack(pady=2)

        def on_save_and_close():
            for tid, (ex, ey) in self._monster_offset_entries.items():
                try:
                    ox = int(ex.get() or "0")
                    oy = int(ey.get() or "0")
                except ValueError:
                    ox, oy = 0, 0
                for t in self._monster_templates:
                    if t["id"] == tid:
                        t["offset_x"] = ox
                        t["offset_y"] = oy
                        break
            self._save_monster_meta()
            try:
                self._match_sim["monster"] = _monster_sim_entry.get().strip() or "0.70"
                self._save_match_sim()
            except Exception:
                pass
            self._add_log("怪物特征偏移已保存")
            self._close_window("_monster_feature_window")
        # 怪物识别相似度调节(默认0.7，识别不到可手动调低如0.6)——用户2026-09-06
        _sim_frame = tk.Frame(right_frame)
        _sim_frame.pack(fill="x", pady=(4, 2))
        tk.Label(_sim_frame, text="相似度", font=("微软雅黑", 9, "bold")).pack(side="left", padx=4)
        _monster_sim_entry = tk.Entry(_sim_frame, width=6, font=("微软雅黑", 9))
        _monster_sim_entry.insert(0, self._match_sim.get("monster", "0.70"))
        _monster_sim_entry.pack(side="left", padx=4)
        tk.Label(_sim_frame, text="0.7默认，识别不到可调0.6", font=("微软雅黑", 7), fg="gray").pack(side="left", padx=2)
        tk.Button(right_frame, text="保存并关闭", width=14, height=2, command=on_save_and_close, bg="#2196F3", fg="white").pack(pady=5)

        info = tk.Label(right_frame, text='说明：\n左=怪物朝左\n右=怪物朝右\n每方向最多5个\n偏移=特征中心到怪心和YOLO合并显示紫点', font=('微软雅黑', 8), fg='gray', justify='left', wraplength=140)
        info.pack(pady=10, anchor="n")

        print('[怪物特征弹窗] 步骤7: 弹窗创建完成')
        win.update()

    def _open_ladder_feature_window(self):
        """梯子特征管理弹窗(随当前方案永久保存)：左列表(缩略图+删单个)，右操作(添加框选/全删/相似度/保存关闭)。
        梯子特征只用于上梯近距在主窗口匹配竖条X，不用方向/偏移(用户2026-09-09)。"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if getattr(self, '_ladder_feature_window', None) is not None:
            try:
                self._ladder_feature_window.destroy()
            except Exception:
                pass
            self._ladder_feature_window = None
        win = tk.Toplevel(self._tk_root)
        self._ladder_feature_window = win
        win.title("梯子特征管理（随当前方案%d永久保存）" % self.current_route)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        def on_close():
            try:
                win.destroy()
            except Exception:
                pass
            self._ladder_feature_window = None
        win.protocol("WM_DELETE_WINDOW", on_close)
        self._position_window(win, 460, 380)

        left = tk.Frame(win, width=300, height=350)
        left.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        left.pack_propagate(False)
        tk.Label(left, text="梯子特征列表（框整根绳索/梯子竖条，只用其X）",
                 font=("微软雅黑", 9, "bold")).pack(anchor="w")
        canvas = tk.Canvas(left, highlightthickness=0)
        sb = tk.Scrollbar(left, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas)
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        def refresh():
            for w in sf.winfo_children():
                w.destroy()
            if not self._ladder_templates:
                tk.Label(sf, text="暂无梯子特征，点右边“添加梯子特征”",
                         font=("微软雅黑", 9), fg="gray").pack(pady=20)
                return
            for idx, tpl in enumerate(self._ladder_templates):
                row = tk.Frame(sf, relief="solid", borderwidth=1)
                row.pack(fill="x", pady=2, padx=2)
                tk.Label(row, text="#%d" % tpl["id"], font=("微软雅黑", 9, "bold"), width=3).pack(side="left")
                tk.Label(row, text="%dx%d" % (tpl["width"], tpl["height"]),
                         font=("微软雅黑", 8), fg="gray").pack(side="left", padx=5)
                try:
                    from PIL import Image as _PI, ImageTk as _PIT
                    _p = _PI.fromarray(tpl["img"])
                    _p.thumbnail((30, 60))
                    _ph = _PIT.PhotoImage(_p)
                    _th = tk.Label(row, image=_ph, width=30, height=60, relief="solid", borderwidth=1, bg="white")
                    _th.image = _ph
                    _th.pack(side="left", padx=5)
                except Exception as _te:
                    print("[梯子缩略图] 异常:", _te)

                def mk_del(i):
                    def od():
                        if messagebox.askyesno("确认", "删除梯子特征#%d？" % self._ladder_templates[i]["id"]):
                            self._delete_ladder_template(i)
                            refresh()
                    return od
                tk.Button(row, text="删", width=3, command=mk_del(idx), bg="#FF6666", fg="white").pack(side="right", padx=2)
        refresh()

        right = tk.Frame(win, width=150, height=350)
        right.pack(side="right", fill="y", padx=5, pady=5)
        right.pack_propagate(False)

        def on_add():
            try:
                win.withdraw()
            except Exception:
                pass
            self._capture_ladder_feature()
            try:
                win.deiconify()
                win.lift()
            except Exception:
                pass
            refresh()
        tk.Button(right, text="添加梯子特征", width=14, height=1, command=on_add,
                  bg="#2196F3", fg="white").pack(pady=4)

        def on_clear():
            if messagebox.askyesno("确认", "清除当前方案全部梯子特征？"):
                self._clear_ladder_templates()
                refresh()
        tk.Button(right, text="全部删除", width=14, height=1, command=on_clear,
                  bg="#FF6666", fg="white").pack(pady=4)

        sim_frame = tk.Frame(right)
        sim_frame.pack(fill="x", pady=(6, 2))
        tk.Label(sim_frame, text="相似度", font=("微软雅黑", 9, "bold")).pack(side="left", padx=4)
        sim_entry = tk.Entry(sim_frame, width=6, font=("微软雅黑", 9))
        sim_entry.insert(0, str(getattr(self, '_ladder_tpl_sim', LADDER_TPL_DEFAULT_SIM)))
        sim_entry.pack(side="left", padx=4)

        def on_save():
            try:
                self._ladder_tpl_sim = float(sim_entry.get().strip() or LADDER_TPL_DEFAULT_SIM)
            except Exception:
                self._ladder_tpl_sim = LADDER_TPL_DEFAULT_SIM
            self._save_ladder_templates(self.current_route)
            self._add_log("梯子特征已保存到方案%d（共%d套）" % (self.current_route, len(self._ladder_templates)))
            self._close_window("_ladder_feature_window")
        tk.Button(right, text="保存并关闭", width=14, height=2, command=on_save,
                  bg="#4CAF50", fg="white").pack(pady=6)
        tk.Label(right, text="说明:\n一个地图录一次\n随方案导出/导入\n只在上梯、小地图差≤5时识别\n只取梯子X对齐起跳",
                 font=("微软雅黑", 8), fg="gray", justify="left", wraplength=135).pack(pady=8, anchor="n")
        win.update()

    def _open_clear_window(self):
        """打开删除方案窗口：双击方案删方案，双击地图删地图（Listbox布局）"""
        import tkinter as tk
        from tkinter import messagebox
        if not self._ensure_tk_root():
            return
        if self._clear_window is not None:
            try:
                self._clear_window.destroy()
            except Exception:
                pass
            self._clear_window = None
        try:
            win = tk.Toplevel(self._tk_root)
        except Exception as e:
            _debug_log("[方案窗口] 清除窗口Toplevel失败: %s" % e)
            return
        self._clear_window = win
        _debug_log("[方案窗口] 清除窗口已创建")
        win.title("删除方案")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_window("_clear_window"))
        self._position_window(win, 300, 400)

        tk.Label(win, text="双击地图名删地图，双击方案删方案", font=("微软雅黑", 10)).pack(pady=(8, 4))

        list_frame = tk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(list_frame, font=("微软雅黑", 10), yscrollcommand=scrollbar.set,
                             selectbackground="#FFD700", selectforeground="black", height=14)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        # 构建扁平列表：(类型, 名称, id)  类型: map/plan
        items = []
        for mp in self.plans_data.get("maps", []):
            items.append(("map", "[地图] " + mp["name"], mp["name"]))
            for plan in mp["plans"]:
                items.append(("plan", "    " + plan["name"], plan["id"]))
        for it in items:
            listbox.insert("end", it[1])

        def on_double(event):
            sel = listbox.curselection()
            if not sel:
                return
            itype, iname, iid = items[sel[0]]
            if itype == "map":
                if self._show_msg("yesno", "确认", "您确定要删除当前地图吗？\n删除后所属地图下的方案也会清空，请慎重！", parent=win):
                    self._delete_map(iid)
                    self._close_window("_clear_window")
                    self._open_clear_window()
            else:
                if self._show_msg("yesno", "确认", "您确定要删除此方案吗？", parent=win):
                    self._delete_plan(iid)
                    self._close_window("_clear_window")
                    self._open_clear_window()

        listbox.bind("<Double-Button-1>", on_double)
        tk.Button(win, text="关闭", width=10, command=lambda: self._close_window("_clear_window")).pack(pady=8)
        win.update()

    def _close_window(self, attr):
        """关闭指定窗口"""
        win = getattr(self, attr, None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
            setattr(self, attr, None)

    def _handle_dropdown_item(self, menu, item_idx):
        """处理下拉菜单项点击（仅mode下拉保留，save/route/clear_route改为独立窗口）"""
        if menu == "mode":
            self.route_mode = "手动" if item_idx == 0 else "随机"
            self._save_route_config()
            if self.route_mode == "随机":
                self._start_random()
            else:
                self._stop_random()
            print("[模式] 切换为: %s" % self.route_mode)

    # ===== 随机模式运行逻辑 =====

    def _key_down(self, vk):
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
        user32.keybd_event(vk, scan, ext, 0)
        self._random_move_keys.add(vk)
        self._wd_sync_from_keys('route')  # 监管线:巡路方向键按下即登记(走向梯子/走台/爬梯/上下跳全覆盖)

    def _key_up(self, vk):
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
        user32.keybd_event(vk, scan, ext | 0x0002, 0)  # KEYEVENTF_KEYUP
        self._random_move_keys.discard(vk)
        self._wd_sync_from_keys('route')  # 监管线:松方向键后对账意图

    def _release_all_keys(self):
        for vk in list(self._random_move_keys):
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            user32.keybd_event(vk, scan, ext | 0x0002, 0)
        self._random_move_keys.clear()
        self._wd_sync_from_keys('route')  # 监管线:全松后按剩余战斗键对账(巡路意图清空)

    def _start_random(self):
        """启动随机模式：停止录制，清空按键，开始状态机"""
        if self._random_running:
            return
        if self.hwnd is None:
            print("[启动] 未绑定游戏窗口，请先绑定")
            self._add_log("未绑定窗口，无法启动")
            return
        self.recording_platform = False
        self.recording_ladder = False
        self.platform_points = []
        self.ladder_points = []
        self._release_all_keys()
        self._reset_climb()
        self._random_running = True
        self._random_state = "idle"
        self._random_platform_idx = 0
        self._random_no_route_logged = False
        # 重置增强逻辑状态
        self._route_reelect_time = 0
        self._idle_combat_start_pos = None
        self._idle_combat_attack_start = 0
        self._idle_combat_no_damage_duration = 0
        self._idle_combat_no_damage_logged = False
        self._idle_combat_last_turn = 0
        self._idle_combat_turn_interval = 0
        self._return_fail_count = 0
        self._return_attempt_mode = None
        # 同时启动战斗逻辑和透明蒙板（与F10一致）
        self._running = True
        print("[随机] 模式已启动，将自动选方案打平台")
        self._add_log("随机模式已启动（含战斗+蒙板）")
        _debug_log("[随机] 运行按钮已触发, _running=True, _random_running=True")

    def _stop_random(self):
        """停止随机模式：松开所有按键"""
        if not self._random_running:
            return
        self._release_all_keys()
        self._reset_climb()
        self._random_running = False
        self._random_state = "idle"
        # 同时停止战斗逻辑和透明蒙板
        self._running = False
        if self._monster_overlay_running:
            self._stop_monster_overlay()
        print("[随机] 模式已停止")
        self._add_log("随机模式已停止")
        _debug_log("[随机] 模式已停止")

    def _random_pick_route(self):
        """从勾选的方案中随机选一个（排除上一个避免连续重复）；没勾选返回None"""
        selected = self._get_selected_plans()
        available = []
        for p in selected:
            num = plan_id_to_num(p["id"])
            if self._route_has_file(num):
                available.append(num)
        if not available:
            return None
        if len(available) > 1 and self._random_route_id in available:
            available = [i for i in available if i != self._random_route_id]
        return random.choice(available)

    def _find_nearest_ladder(self, px, py, target_y):
        """找最近的可用梯子（2026-09-09两阶段定稿：先离怪锁定目标梯，再离人选当前这一跳）
        硬门槛：连接端Y必须和目标怪Y重合(±1)——上行看顶端y_top、下行看底端y_bottom，差>1=通向别的层直接排除(治在错梯下空跳)。
        阶段1【离怪最近定目标】：所有Y±1合格梯(不管当前够不够得着)里，离目标怪X最近的那把=真正连怪台的目标梯(锚点)，
              排除"Y碰巧同层但在地图另一端"的无关梯；不要求梯子X和怪X对齐(梯子在台边、怪在台面走)。
        阶段2【离人最近选当前跳】：目标梯现在够得着(一个直跳能抓到下端/顶端)就直接上它；
              目标梯暂够不着(人还在更下层需中转)时，在够得着的合格梯里选离人物X最近的先上一层，下一帧再朝目标梯走。
        全用小地图坐标；px/py=人物光点,target_y=目标怪Y,目标怪X取自self._transit_target(缺省=人物X,此时离怪=离人等价旧逻辑)。"""
        going_up = target_y < py   # 小地图Y越小越靠上
        # 目标怪小地图X：阶段1离怪锚定用；直接调用/测试无_transit_target时退回人物X
        _tt = getattr(self, '_transit_target', None)
        target_x = float(_tt[0]) if (_tt is not None and len(_tt) >= 1) else px
        # ===== 下行(用户2026-09-09定稿)：不要求梯子底端与怪Y±1对齐,只看怪在下方,离哪把梯近就从哪下 =====
        # 上行才需要"梯端与怪台重合"防选错层;下层怪小地图Y受镜头/倍率影响对不齐,硬卡±1会一把都选不出→下方不动。
        # 下行优先选"人当前够得着(人在梯纵向范围内)且离人X最近"的梯;一把够得着的都没有时放宽到离人最近,保证选得出。
        if not going_up:
            _dn = []
            for ld in self.ladders:
                _reach_dn = (ld["y_top"] - LADDER_REACH_HEIGHT <= py <= ld["y_bottom"])
                _dn.append((abs(ld["x"] - px), _reach_dn, ld))
            if not _dn:
                _debug_log("[选梯] 下行:当前无任何梯子,本次不选等下一帧")
                return None
            _dn_reach = [t for t in _dn if t[1]]
            _dn_pick = min(_dn_reach, key=lambda t: t[0]) if _dn_reach else min(_dn, key=lambda t: t[0])
            _debug_log("[选梯] 下行不要求Y对齐,选离人最近梯x=%.0f(离人%d,%s)" % (
                _dn_pick[2]["x"], _dn_pick[0], "当前够得着" if _dn_pick[1] else "无够得着梯放宽取最近"))
            return _dn_pick[2]
        # 【用户2026-09-08/09】选梯详细调试日志：人物位置、目标怪、所有梯子、筛选过程、最终结果
        _ld_list = ["梯%d(x=%.0f,yt=%.0f,yb=%.0f)" % (i, ld["x"], ld["y_top"], ld["y_bottom"]) for i, ld in enumerate(self.ladders)]
        _debug_log("[选梯] 人物(%.0f,%.0f) 目标怪(%.0f,%.0f) 方向=%s 梯子共%d条: %s" % (
            px, py, target_x, target_y, "上行" if going_up else "下行", len(self.ladders), ", ".join(_ld_list) if _ld_list else "无"))
        # 收集所有Y±1合格梯：(离怪X差dg, 离人X差dp, 够得着reach, 梯子ld)；Y不合格(错层)直接排除，够不着不排除(留作锚点)
        allY = []
        for i, ld in enumerate(self.ladders):
            lx = ld["x"]
            y_top = ld["y_top"]
            y_bottom = ld["y_bottom"]
            end_y = y_top if going_up else y_bottom
            # 硬门槛：连接端Y必须和怪Y±1重合，否则是通向别的层的梯
            if abs(end_y - target_y) > LADDER_END_MATCH_TOL:
                _debug_log("[选梯] 梯%d排除:连接端Y没和怪重合(|端=%.0f-怪Y=%.0f|=%d>%d,通向别处)" % (
                    i, end_y, target_y, abs(end_y - target_y), LADDER_END_MATCH_TOL))
                continue
            if going_up:
                reach = (y_top <= py <= y_bottom + LADDER_REACH_HEIGHT)   # 下端一个直跳够得着
            else:
                reach = (y_top - LADDER_REACH_HEIGHT <= py <= y_bottom)   # 顶端一个直跳够得着
            _dg = abs(lx - target_x)
            _dp = abs(lx - px)
            allY.append((_dg, _dp, reach, ld))
            _debug_log("[选梯] 梯%d Y±1合格:离怪X差=%d 离人X差=%d %s" % (
                i, _dg, _dp, "当前够得着" if reach else "暂够不着(可作目标/中转)"))
        if not allY:
            _debug_log("[选梯] 无Y±1重合梯子(都通向别的层),本次不选等下一帧")
            return None
        # 阶段1：离怪X最近=目标锚点梯(连怪台的正确入口)
        anchor = min(allY, key=lambda t: t[0])
        _debug_log("[选梯] 阶段1离怪锁定目标梯: x=%.0f 离怪X差=%d" % (anchor[3]["x"], anchor[0]))
        # 阶段2：目标梯够得着直接上；否则在够得着的合格梯里选离人最近的中转
        if anchor[2]:
            best = anchor[3]
            _debug_log("[选梯] 最终选中: 目标梯x=%.0f 当前够得着,直接上(离怪%d/离人%d)" % (
                best["x"], anchor[0], anchor[1]))
        else:
            reachable = [t for t in allY if t[2]]
            if reachable:
                _step = min(reachable, key=lambda t: t[1])
                best = _step[3]
                _debug_log("[选梯] 最终选中: 目标梯x=%.0f暂够不着,先上离人最近中转梯x=%.0f(离人%d),逐层接近" % (
                    anchor[3]["x"], best["x"], _step[1]))
            else:
                _debug_log("[选梯] 目标梯x=%.0f及所有合格梯当前都够不着,先走近/等下一帧" % anchor[3]["x"])
                best = None
        return best

    def _reset_climb(self):
        """重置攀爬/跳跃/瞬移状态"""
        # 上下左右都显式松开：走向梯子时_hold_toward_ladder按的左右若残留在_random_move_keys,
        # 会和战斗移动(_combat_held_keys)相抵/方向污染,表现为知道去梯子却原地不走(2026-09-09真机)。
        if VK_UP in self._random_move_keys:
            self._key_up(VK_UP)
        if VK_DOWN in self._random_move_keys:
            self._key_up(VK_DOWN)
        if VK_LEFT in self._random_move_keys:
            self._key_up(VK_LEFT)
        if VK_RIGHT in self._random_move_keys:
            self._key_up(VK_RIGHT)
        self._climb_state = "none"
        self._climb_ladder_x = 0
        self._climb_ladder_y_top = 0      # 当前爬的梯子顶端Y（小地图，到顶验证用）
        self._climb_ladder_y_bottom = 0   # 当前爬的梯子底端Y（小地图，到底验证用）
        self._climb_target_y = 0
        self._climb_direction = 0
        self._climb_start_y = 0
        self._climb_action_time = 0
        self._ladder_run_jump = False   # 25px点位跑跳标记(到25跳一次并保持向梯移动)
        self._ladder_vert_jump = False  # 10px内直跳标记(走进10内原地直跳抓梯)
        self._ladder_run_jumped = False  # 25点位是否已跑跳过（防止重复跳）
        self._ladder_vert_jumped = False  # 10点位是否已直跳过
        # 精细点动对齐状态(用户2026-09-09),每次爬梯复位
        self._lad_align_key_vk = None     # 当前点动按下的方向键vk(跨帧非阻塞抬起),None=没按
        self._lad_align_key_t = 0         # 点动键按下时刻
        self._lad_align_nudge_t = 0       # 上一点动节拍时刻
        self._lad_align_ref_px = None     # 上节拍人物X(比有没有朝梯子靠近)
        self._lad_align_ok_frames = 0     # 连续|X差|≤1的帧数(直跳准入)
        self._lad_align_stall_t = 0       # 精细区开始"没靠近"的时刻
        self._lad_align_stall_n = 0       # 想动没动的解卡尝试次数
        self._ladder_jump_phase = None    # None=未起跳 / 'post_jump'=起跳后流程中
        self._ladder_post_jump_step = None  # 'delay1'/'delay2'/'check_y'
        self._ladder_post_jump_t = 0       # 起跳后各阶段时间戳
        self._climb_top_hold = False       # 到顶多按100ms保持标记
        self._climb_top_hold_t = 0         # 到顶保持开始时间
        self._climb_fail_count = 0                     # 本轮爬梯失败次数（拟人：随机上限放弃）
        self._climb_fail_limit = random.choice([2, 3])  # 失败上限：随机2次或3次（拟人：不固定）
        self._climb_fail_pause_until = 0               # 随机放弃后的"歇一会"截止时间(ms)
        self._climb_fail_decided = None                # 失败后随机决策结果: 'farm'再打一波 / 'climb'直接上
        self._transit_farm_until = 0                   # 'farm'决策的截止时间(ms)，到点重新随机/继续上
        # === 拟人化状态（站位随机/周期小休）===
        self._combat_stance_target_x = None            # 站位随机目标X（小地图坐标）
        self._combat_stance_until = 0                  # 站位走位截止时间(ms)
        self._combat_stance_next_roll = 0              # 站位随机决策时间(ms)（5~9秒一次）
        self._rest_next_at = 0                         # 拟人周期小休：下次休息时间(ms)（5~8分钟随机）
        self._rest_until = 0                           # 本次休息截止时间(ms)（5~10秒）
        self._slope_next_jump = 0                      # 跳高打：下次允许跳的时间(ms)，每500~600ms跳一次不连跳
        self._slope_jump_t = 0                         # 跳高打：最近一次起跳时刻(ms)，跳后150ms进跳打窗口
        self._slope_jump_hit = False                   # 跳高打：本跳是否已在空中打过一下(每跳只打一下,起跳重置)
        self._slope_hit_window = False                 # 跳高打：本帧是否处于"跳后150ms~落地"的空中放技能窗口
        self._slope_resume_at = 0                      # 跳高打：跨层爬梯到顶后保护截止(ms)，此时间前不启用跳高打(防刚翻上梯顶没站稳被跳下来,用户2026-09-09)
        self._move_stuck_inited = False  # 爬梯结束重置卡住检测
        # 主窗口梯子模板"屏幕X精对齐"状态复位(用户2026-09-09)
        self._lad_scr_ok_frames = 0
        self._lad_scr_key_vk = None
        self._lad_scr_key_t = 0
        self._lad_scr_nudge_t = 0
        self._lad_scr_ref_spx = None
        self._lad_scr_stall_t = 0
        self._lad_scr_stall_n = 0
        # 登顶三背景点状态复位
        self._climb_box_prev = [None, None, None]
        self._climb_box_centers = [None, None, None]
        self._climb_still_since = 0

    def _do_teleport(self, current_y):
        """执行一次瞬移：按方向键+瞬移技能键"""
        fight_cfg = self._get_fight_config()
        tp_key = fight_cfg.get("teleport_key", "")
        if not tp_key:
            return
        # 先按方向键（上/下）
        if self._climb_direction > 0:
            if VK_DOWN in self._random_move_keys:
                self._key_up(VK_DOWN)
            if VK_UP not in self._random_move_keys:
                self._key_down(VK_UP)
        else:
            if VK_UP in self._random_move_keys:
                self._key_up(VK_UP)
            if VK_DOWN not in self._random_move_keys:
                self._key_down(VK_DOWN)
        # 按瞬移技能键
        self._press_game_key(tp_key, duration=60)
        # 瞬移后人物合法大跳变：700ms内人物匹配跳过ROI直接全图、允许远距同步(治点钉原地)
        self._char_relocate_until = time.time() * 1000 + 700
        self._climb_start_y = current_y
        self._climb_action_time = time.time() * 1000

    def _hold_toward_ladder(self, ldx):
        """朝梯子方向按住水平移动键（ldx=梯子小地图X-光点X，正=梯子在右边）。对侧键先松开防左右相抵。"""
        if ldx > 0:
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT not in self._random_move_keys:
                self._key_down(VK_RIGHT)
        else:
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            if VK_LEFT not in self._random_move_keys:
                self._key_down(VK_LEFT)
        # 上屏(用户2026-09-09)：持续走向梯子时限频报方向/剩余小地图X差，600ms一条
        self._rlog_throttle('to_ladder', "正走向梯子(梯在%s,小地图X差%.0f)" % (
            "右" if ldx > 0 else "左", abs(ldx)), 1500, log='behavior')

    def _ladder_post_jump_process(self, py, now_ms):
        """起跳后统一流程（2026-09-08 重写；2026-09-09 直跳延时100ms + 镜头滚动定稿）：
        跳后延时按↑不松+松左右(原地直跳100ms/固定点6跑跳150ms，先松↓上下互斥) → 抓梯窗口LADDER_GRAB_WINDOW_MS内
        只和【起跳前站地基准Y】比：任一帧Y变小≥LADDER_GRAB_UP_TOL=抓住,锁存转climbing一直按↑(中间帧镜头回弹不判错)；
        走到窗口上限全程没变小=没抓住，松↑重置回正常找怪（锁定的台子怪不放弃，会再引上来）。"""
        step = getattr(self, '_ladder_post_jump_step', 'delay1')
        start_t = getattr(self, '_ladder_post_jump_t', now_ms)

        if step == 'delay1':
            # 起跳后延时再按↑：原地直跳(<2,vert)跳后100ms按↑(用户2026-09-09)；固定点6跑跳保持150ms
            _is_vert = getattr(self, '_ladder_vert_jumped', False) and not getattr(self, '_ladder_run_jumped', False)
            _up_delay = 100 if _is_vert else 150
            if now_ms - start_t >= _up_delay:
                self._release_move_conflicts()  # 按↑抓梯前清攻击+两套左右(残留键会打断爬梯=上一半停)
                if VK_DOWN in self._random_move_keys:
                    self._key_up(VK_DOWN)  # 上下互斥,再松一次↓
                if VK_UP not in self._random_move_keys:
                    self._key_down(VK_UP)
                self._ladder_post_jump_step = 'check'
                self._ladder_post_jump_t = now_ms
                # 【镜头滚动原理·用户2026-09-09】抓梯基准必须用"起跳前站地Y"(跑跳/直跳起跳时已写入_climb_start_y),
                # 不能在此用跳后当前py覆盖:快到顶镜头会滚动、跳后Y已被污染。仅基准无效(0)时才用当前值兜底。
                if not self._climb_start_y:
                    self._climb_start_y = py
                _debug_log("[爬梯] 起跳后%dms按↑松左右(%s),窗口%dms内对比起跳前地面基准Y=%.0f(当前Y=%.0f)" % (
                    _up_delay, "直跳" if _is_vert else "跑跳", LADDER_GRAB_WINDOW_MS, self._climb_start_y, py))
            return False

        # check【镜头滚动原理·用户2026-09-09定稿】：只和"起跳前站地基准Y"比,不做相邻帧比较
        # (镜头滚动期相邻帧会抖动/回弹,逐帧比会把"其实上升了"误判成没抓住,真机74→71→86即此坑)。
        # 窗口内任一帧Y比基准小≥LADDER_GRAB_UP_TOL=抓住,立刻锁存转climbing(不可逆),之后一直按↑、中间帧回弹不再判错。
        if py < self._climb_start_y - LADDER_GRAB_UP_TOL:
            # Y变小=成功抓住，转持续攀爬
            self._release_move_conflicts()  # 抓住瞬间清攻击+两套左右,只留↑持续爬(治上到一半/差一点到顶被残留键打断)
            if VK_DOWN in self._random_move_keys:
                self._key_up(VK_DOWN)
            if VK_UP not in self._random_move_keys:
                self._key_down(VK_UP)
            self._climb_state = 'climbing'
            self._climb_action_time = now_ms
            self._climb_start_y = py
            self._ladder_vert_fail_count = 0   # 成功抓住：直跳连续失败计数清零(用户2026-09-09)
            self._ladder_backoff = None        # 清掉可能残留的退开状态
            self._ladder_jump_phase = None
            self._ladder_post_jump_step = None
            _debug_log("[爬梯] 抓住梯子Y上升(→%.0f)，转持续爬+检测到顶" % py)
            self._rlog("抓住梯子,持续向%s(梯端Y=%.0f 当前Y=%.0f)" % (
                "上" if self._climb_direction > 0 else "下",
                self._climb_ladder_y_top if self._climb_direction > 0 else self._climb_ladder_y_bottom, py),
                log='behavior')
            return False
        # 还没观测到"相对起跳前基准上升"：仍在抓梯窗口内就继续按住↑等(不松键、不判失败),镜头回弹帧直接忽略
        if now_ms - start_t < LADDER_GRAB_WINDOW_MS:
            if VK_UP not in self._random_move_keys:
                self._key_down(VK_UP)
            return False
        # 走出抓梯窗口、Y相对起跳前基准全程没变小=真没抓住，在地上，失败重置回正常找怪
        # 【用户2026-09-09】只统计"原地直跳"(<2对齐)连续失败：满2次→退开120~150px回主线打怪,打完再自动上梯；
        # 固定点6跑跳失败不计入(跑跳本来就会退回点位重试)。计数跨_reset_climb保留,故在reset前处理。
        _is_vert_fail = getattr(self, '_ladder_vert_jumped', False) and not getattr(self, '_ladder_run_jumped', False)
        if _is_vert_fail:
            self._ladder_vert_fail_count = getattr(self, '_ladder_vert_fail_count', 0) + 1
            if self._ladder_vert_fail_count >= LADDER_VERT_FAIL_LIMIT:
                self._ladder_vert_fail_count = 0
                self._start_ladder_backoff(now_ms)
                _debug_log("[爬梯] 原地直跳连续%d次未抓住梯子，退开%dpx后回主线打怪、打完再自动上梯" % (
                    LADDER_VERT_FAIL_LIMIT, self._ladder_backoff["target"] if self._ladder_backoff else 0))
        _debug_log("[爬梯] 失败：%dms窗口内Y相对起跳前基准全程未上升(%.0f→%.0f)，松↑重置" % (LADDER_GRAB_WINDOW_MS, self._climb_start_y, py))
        self._rlog("起跳没抓住梯子(%dms没上升),%s,回主线重试" % (LADDER_GRAB_WINDOW_MS, "原地直跳" if _is_vert_fail else "跑跳"),
                   LOG_RED, log='behavior')
        if VK_UP in self._random_move_keys:
            self._key_up(VK_UP)
        self._climb_fail_pause_until = now_ms + random.randint(300, 500)
        self._reset_climb()
        self._decide_climb_fail_action()
        return False


    def _move_to(self, player_pos, target_x, target_y):
        """移动角色到目标位置（小地图坐标），支持梯子攀爬。返回是否到达"""
        if player_pos is None:
            return False
        px, py = player_pos
        dx = target_x - px
        dy = target_y - py
        # 【用户2026-09-08】爬梯失败冷却期内不重新进入爬梯（治"失败后原地乱跳"）：
        # _try_platform_transition检查了冷却但_move_to没检查，导致失败后下一轮立刻又跳。
        _now_ms = time.time() * 1000
        if getattr(self, '_climb_fail_pause_until', 0) and _now_ms < self._climb_fail_pause_until:
            return False

        # ============================================================
        # 爬梯状态机（2026-09-08 重写·简洁版）
        # 点位全部用小地图距离：固定点6跑跳、<2直跳
        # 到顶判断：小地图人物光标Y 与 梯子顶端 y_top（下行 y_bottom）对齐
        # ============================================================
        if self._climb_state == "to_ladder":
            ldx = self._climb_ladder_x - px          # 梯子X-人物X（正=梯子在右）
            _alx = abs(ldx)
            fight_cfg = self._get_fight_config()
            jump_key = fight_cfg.get("jump_key", "")
            now_ms = time.time() * 1000

            # 起跳后统一流程优先（跑跳/直跳都走这里）
            if getattr(self, '_ladder_jump_phase', None) == 'post_jump':
                return self._ladder_post_jump_process(py, now_ms)

            # === 小地图近距→主窗口梯子模板"屏幕X精对齐"(用户2026-09-09,只用X;无模板/没匹配到自动回退下面小地图逻辑)===
            if _alx <= LADDER_TPL_ENTER_PX and getattr(self, '_ladder_templates', None) \
                    and self._raw_frame is not None and self._player_screen_pos:
                _lk = getattr(self, '_combat_locked_target', None)
                _lkx = _lk[0] if _lk else None
                _tpl_x = self._match_ladder_screen_x(self._raw_frame, self._player_screen_pos,
                                                     self._climb_direction, _lkx)
                if _tpl_x is not None:
                    return self._ladder_align_by_screen(_tpl_x, px, py, now_ms, jump_key)

            # 冲过头弹回>7：重置点位重来
            if _alx > 7 and (getattr(self, '_ladder_run_jumped', False) or getattr(self, '_ladder_vert_jumped', False)):
                self._ladder_run_jumped = False
                self._ladder_vert_jumped = False
                _debug_log("[爬梯] 冲过头退回%.0f,重置抓梯点位重试" % _alx)

            # ===== 水平对齐状态机(用户2026-09-09定稿) =====
            # 远距(>3)正常按住方向走(像人不磨叽);≤3进精细区非阻塞点动1~2px;直跳是关键动作,
            # 必须|X差|≤1且连续2帧停稳(准入标准)才跳;指令朝梯走但X没靠近(想动没动)要解卡,不许卡边界死按/没对齐就跳。
            if _alx > LADDER_ALIGN_FINE:
                _ak0 = getattr(self, '_lad_align_key_vk', None)  # 离开精细区前抬起残留点动键
                if _ak0 is not None:
                    self._key_up(_ak0)
                    self._lad_align_key_vk = None
                self._lad_align_ok_frames = 0
                self._lad_align_stall_t = 0
                self._lad_align_stall_n = 0
                self._ladder_run_jumped = False
                self._hold_toward_ladder(ldx)
                return False

            # ---- 精细区 _alx<=3：非阻塞点动，先抬起到时的点动键 ----
            _dir_vk = VK_RIGHT if ldx > 0 else VK_LEFT
            _opp_vk = VK_LEFT if ldx > 0 else VK_RIGHT
            _ak = getattr(self, '_lad_align_key_vk', None)
            if _ak is not None and now_ms - getattr(self, '_lad_align_key_t', 0) >= LADDER_NUDGE_KEY_MS:
                self._key_up(_ak)
                self._lad_align_key_vk = None
                _ak = None

            # 准入标准：|X差|≤1，且连续LADDER_ALIGN_HOLD_FRAMES帧停稳才原地直跳
            if _alx <= LADDER_ALIGN_TOL:
                if _ak is not None:
                    self._key_up(_ak)
                    self._lad_align_key_vk = None
                if VK_LEFT in self._random_move_keys:
                    self._key_up(VK_LEFT)
                if VK_RIGHT in self._random_move_keys:
                    self._key_up(VK_RIGHT)
                self._lad_align_ok_frames = getattr(self, '_lad_align_ok_frames', 0) + 1
                if self._lad_align_ok_frames >= LADDER_ALIGN_HOLD_FRAMES and not getattr(self, '_ladder_vert_jumped', False):
                    self._ladder_vert_jumped = True
                    self._climb_start_y = py
                    self._press_game_key(jump_key, duration=80)
                    _debug_log("[爬梯] 对齐准入通过(连续%d帧X差%.2f≤%d)→原地直跳" % (
                        self._lad_align_ok_frames, ldx, LADDER_ALIGN_TOL))
                    self._rlog("对齐重合直跳抓梯(X差%.1f),跳后100ms按↑" % ldx, log='behavior')
                    self._ladder_jump_phase = 'post_jump'
                    self._ladder_post_jump_step = 'delay1'
                    self._ladder_post_jump_t = now_ms
                return False
            self._lad_align_ok_frames = 0  # 还没到≤1,重置连续帧

            # 1<_alx<=3：点动微调 + 想动没动检测（每个节拍比一次X有没有真朝梯子靠近）
            if now_ms - getattr(self, '_lad_align_nudge_t', 0) >= LADDER_NUDGE_CYCLE_MS:
                _ref = getattr(self, '_lad_align_ref_px', None)
                if _ref is not None:
                    _prev_alx = abs(self._climb_ladder_x - _ref)
                    if _alx < _prev_alx - 0.5:
                        self._lad_align_stall_t = 0       # 上一拍真靠近了,清卡住
                        self._lad_align_stall_n = 0
                    else:
                        if self._lad_align_stall_t == 0:
                            self._lad_align_stall_t = now_ms
                        elif now_ms - self._lad_align_stall_t >= LADDER_ALIGN_STALL_MS:
                            self._lad_align_stall_n += 1
                            self._lad_align_stall_t = now_ms
                            _debug_log("[对齐] 点动后X未靠近(%.1f→%.1f),解卡第%d次:全松重新干净点" % (
                                _prev_alx, _alx, self._lad_align_stall_n))
                            if self._lad_align_stall_n > LADDER_ALIGN_STALL_MAX:
                                # 对不齐(被挡/梯坐标问题):回主线重选或打怪,绝不在此死循环
                                self._rlog("梯子对齐卡住:点动%d次仍不动,回主线重选(不死磕)" % LADDER_ALIGN_STALL_MAX,
                                           LOG_RED, log='behavior')
                                self._key_up(VK_LEFT)
                                self._key_up(VK_RIGHT)
                                self._reset_climb()
                                self._decide_climb_fail_action()
                                return False
                # 发新一拍点动：先松对侧防抵消，再干净短按(跨帧45ms后由帧首抬起,不sleep卡主线)
                self._key_up(_opp_vk)
                if getattr(self, '_lad_align_key_vk', None) is None:
                    self._key_down(_dir_vk)
                    self._lad_align_key_vk = _dir_vk
                    self._lad_align_key_t = now_ms
                self._lad_align_nudge_t = now_ms
                self._lad_align_ref_px = px
                self._rlog_throttle('lad_align', "精细对齐梯子(梯在%s,X差%.1f,点动微调)" % (
                    "右" if ldx > 0 else "左", ldx), 500, log='behavior')
            return False

        if self._climb_state == "climbing":
            now_ms = time.time() * 1000
            # 持续按住↑/↓：按↑前先松↓、按↓前先松↑，上下互斥防抖动
            if self._climb_direction > 0:
                if VK_DOWN in self._random_move_keys:
                    self._key_up(VK_DOWN)
                if VK_UP not in self._random_move_keys:
                    self._key_down(VK_UP)
            elif self._climb_direction < 0:
                if VK_UP in self._random_move_keys:
                    self._key_up(VK_UP)
                if VK_DOWN not in self._random_move_keys:
                    self._key_down(VK_DOWN)

            # === 到顶判定(用户2026-09-09定稿)：绑定人物的右上/右下/左下三背景点随人移动,
            # 任一点确认不动=人物本帧静止,连续CLIMB_STILL_MS静止=一直按↑却上不去、停在顶=登顶(测人物相对背景运动,与镜头滚动无关,不比人怪Y)===
            _arrived = False
            _arrive_why = ""
            if self._raw_frame is not None and self._player_screen_pos:
                _fh, _fw = self._raw_frame.shape[:2]
                _centers = self._pick_climb_boxes(self._player_screen_pos, _fh, _fw)
                _n_still, _n_valid = self._climb_boxes_still(self._raw_frame, _centers)
                if _n_valid >= 1 and _n_still >= 1:
                    if self._climb_still_since == 0:
                        self._climb_still_since = now_ms
                    elif now_ms - self._climb_still_since >= CLIMB_STILL_MS:
                        _arrived = True
                        _arrive_why = "三背景点静止%.0fms登顶" % CLIMB_STILL_MS
                else:
                    self._climb_still_since = 0   # 没有任何静止点(三点都在动/有效点不足)=还在爬
            # 兜底1:小地图光点到达/越过梯端(背景法异常时的安全网,不比人怪Y)
            if not _arrived:
                _end_y = self._climb_ladder_y_top if self._climb_direction > 0 else self._climb_ladder_y_bottom
                _map_arr = (py <= _end_y + LADDER_TOP_ARRIVE_TOL) if self._climb_direction > 0 \
                    else (py >= _end_y - LADDER_TOP_ARRIVE_TOL)
                if _map_arr:
                    _arrived = True
                    _arrive_why = "小地图梯端兜底"
            # 兜底2:爬梯总超时(防异常永久卡),到点按到顶收尾
            if not _arrived and self._climb_action_time and now_ms - self._climb_action_time > CLIMB_TOTAL_TIMEOUT_MS:
                _arrived = True
                _arrive_why = "总超时%dms兜底收尾" % CLIMB_TOTAL_TIMEOUT_MS
            if _arrived:
                if not getattr(self, '_climb_top_hold', False):
                    self._climb_top_hold = True
                    self._climb_top_hold_t = now_ms
                    _debug_log("[爬梯] %s(光点Y=%.0f)，继续按住500ms翻上/下平台" % (_arrive_why, py))
                    self._rlog("%s(Y=%.0f),多按500ms出梯" % (_arrive_why, py), log='behavior')
                # 到顶后继续按住方向500ms确保站上/站下平台,再显式松开↑/↓出梯(用户2026-09-09:原1秒改500ms)
                if now_ms - self._climb_top_hold_t >= 500:
                    _debug_log("[爬梯] 到顶后按住满500ms，松开方向键出梯水平找怪")
                    self._rlog("已翻上平台,松开方向键,重新识别找怪", LOG_OK, log='behavior')
                    if VK_UP in self._random_move_keys:
                        self._key_up(VK_UP)
                    if VK_DOWN in self._random_move_keys:
                        self._key_up(VK_DOWN)
                    self._reset_climb()
                    # 梯子真正到顶/到底出梯:清掉梯子上测的旧怪表+强制全图重扫重锁(用户2026-09-09,原来漏调→拿梯子上的下方旧怪判cross,一上去就下来)
                    self._reset_lock_after_arrival()
                return False
            # 注:旧"1000ms小地图Y没动判失败"已删(地图中间镜头跟随时小地图Y会不动=误判);新方案以三背景点为准,按↑到顶才停,总超时兜底
            return False

        # === 向上跳状态（跳跃键，检测y是否上升）===
        if self._climb_state == "jump_up":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            # 小地图y减小=向上移动
            went_up = py < self._climb_start_y - 5
            if went_up:
                if abs(py - self._climb_target_y) <= 8:
                    self._reset_climb()
                else:
                    self._climb_state = "none"
                return False
            if elapsed > 800:
                # 超时没上升=跳不上去(用户2026-09-09)：不计数、不硬磕，松↑+短冷却(防原地连跳)+复位爬梯+直接回主线，
                # 本层有怪先打、本层清空后主线重新决策(再跳/瞬移/梯子)，自成循环
                if VK_UP in self._random_move_keys:
                    self._key_up(VK_UP)
                self._climb_fail_pause_until = time.time() * 1000 + random.randint(300, 500)
                self._reset_climb()
                self._decide_climb_fail_action()
                _debug_log("[上跳] 跳不上去（y未上升），复位回主线(本层先打,没怪再上)")
                return False
            return False

        # === 向下跳状态（下+跳跃键，检测y是否下降）===
        if self._climb_state == "jump_down":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            # 【阶段1·用户2026-09-09定时序】进入时已先松攻击/左右并按住↓,保持JUMP_DOWN_HOLD_BEFORE_JUMP_MS(200ms)
            # 让游戏确实采到"向下"状态再补按一次跳(不sleep卡帧);同帧/太快按跳会被判成普通原地跳不下落。
            if not getattr(self, '_jd_jumped', False) and elapsed >= JUMP_DOWN_HOLD_BEFORE_JUMP_MS:
                _jk = self._get_fight_config().get("jump_key", "")
                if _jk:
                    self._press_game_key(_jk, duration=80)
                self._jd_jumped = True
                _debug_log("[下跳] ↓已按住%.0fms,补按跳跃键" % elapsed)
            # 【阶段2】等下落：光点Y比起跳点增大>5=已离开平台开始下落→此时松↓(用户:按跳后再松下),进入落地观测;满800ms还没下降=跳不下去改梯子
            if not getattr(self, '_jd_falling', False):
                if py > self._climb_start_y + 5:
                    self._jd_falling = True
                    self._jd_land_y = py
                    self._jd_land_t = now_ms
                    self._key_up(VK_DOWN)  # 确认开始下落即松↓,下落过程无需再按
                    _debug_log("[下跳] 光点Y开始下降(%.0f→%.0f),松↓进入落地观测" % (self._climb_start_y, py))
                elif elapsed > 800:
                    # 超时没下降 = 跳不下去，改用梯子（直接找梯子，避免下一轮又下跳形成死循环）
                    self._key_up(VK_DOWN)
                    ladder = self._find_nearest_ladder(px, py, self._climb_target_y)
                    if ladder:
                        self._climb_state = "to_ladder"
                        self._climb_ladder_x = ladder["x"]
                        self._climb_ladder_y_top = ladder["y_top"]
                        self._climb_ladder_y_bottom = ladder["y_bottom"]
                        self._climb_direction = -1
                        self._ladder_run_jump = False
                        self._ladder_vert_jump = False
                        _debug_log("[下跳] 跳不下去（y未下降），改用梯子x=%.0f" % ladder["x"])
                    else:
                        self._climb_state = "none"
                        _debug_log("[下跳] 跳不下去且无可用梯子，放弃本次移动")
                return False
            # 【阶段3·用户2026-09-09】下落中观测落地：Y仍明显增大(>3)=还在空中,刷新基准;连续稳定不再增大=落到台子
            if py > self._jd_land_y + 3:
                self._jd_land_y = py
                self._jd_land_t = now_ms
                return False
            _stable_ms = now_ms - self._jd_land_t
            if _stable_ms >= JUMP_DOWN_LAND_STABLE_MS or elapsed > JUMP_DOWN_LAND_TIMEOUT_MS:
                self._key_up(VK_DOWN)
                _why = ("Y稳定%.0fms无大变化=落到台子" % _stable_ms) if _stable_ms >= JUMP_DOWN_LAND_STABLE_MS \
                       else ("满%dms兜底落地" % JUMP_DOWN_LAND_TIMEOUT_MS)
                _debug_log("[下跳] %s,松↓并清旧识别缓存+全图重扫重锁(与上梯到顶一致)" % _why)
                self._rlog("下跳落到台子:清旧缓存+全图重扫重锁", log='behavior')
                self._reset_climb()
                # ★用户:向下跳到别的台子、Y不再变化=到底,必须清旧锁定/怪表缓存强制重扫重识别,不拿上层旧怪表决策
                self._reset_lock_after_arrival()
                return False
            return False

        # === 瞬移状态（方向键+瞬移技能，检测是否生效）===
        if self._climb_state == "teleport":
            now_ms = time.time() * 1000
            elapsed = now_ms - self._climb_action_time
            y_changed = abs(py - self._climb_start_y) > 3
            if y_changed or elapsed > 800:
                if abs(py - self._climb_target_y) <= 8:
                    self._reset_climb()
                    return False
                # 没到目标层，再瞬移一次（最多3秒）
                if elapsed > 3000:
                    self._reset_climb()
                    _debug_log("[瞬移] 多次未到达目标，改用梯子")
                else:
                    self._do_teleport(py)
            return False

        # === 正常移动（非攀爬状态）===
        # 需要上下层时：先找梯子（上行直接去梯子；下行先尝试下跳，下跳失败再走梯子）
        if abs(dy) > 8 and target_y < py:
            ladder = self._find_nearest_ladder(px, py, target_y)
            if ladder:
                self._climb_state = "to_ladder"
                self._climb_ladder_x = ladder["x"]
                self._climb_ladder_y_top = ladder["y_top"]
                self._climb_ladder_y_bottom = ladder["y_bottom"]
                self._climb_target_y = target_y
                self._climb_direction = 1 if target_y < py else -1
                self._ladder_run_jump = False   # 新一轮抓梯：重置点位跳标记
                self._ladder_vert_jump = False
                _debug_log("[路线] 需上下层dy=%.0f，直接去梯子x=%.0f" % (dy, ladder["x"]))
                return False

        # 【用户2026-09-09补·下行跨层入口】旧代码这里只有 target_y<py(上行)半套;下行(target_y>py)只能靠后面兜底块、
        # 却被其 `not _combat_transit` 挡死(跨层进行中恒True)→怪在下方时既不跳也不选梯、人原地不动不跳(真机"下方尤其不动")。
        # 补对称下行入口(跨层中也生效):水平基本对齐且落差不大→直接下跳;否则找离人最近梯子按↓爬下去(下行选梯不要求Y对齐)。
        if abs(dy) > 8 and target_y > py:
            _dn_jk = self._get_fight_config().get("jump_key", "")

            def _enter_jump_down():
                self._release_move_conflicts()  # 用户定时序:先松攻击+左右,再按↓,避免干扰下跳
                self._climb_state = "jump_down"
                self._climb_target_y = target_y
                self._climb_start_y = py
                self._climb_action_time = time.time() * 1000
                self._jd_jumped = False      # 先只按住↓,状态机满200ms补按跳
                self._jd_falling = False     # 下落/落地观测阶段标志
                if VK_DOWN not in self._random_move_keys:
                    self._key_down(VK_DOWN)

            if _dn_jk and abs(dx) <= 15 and abs(dy) <= 60:
                _enter_jump_down()
                _debug_log("[下跳·下行入口] 间距%.0f X差%.0f,松攻击/左右后按住↓等200ms再跳" % (dy, dx))
                return False
            _dn_lad = self._find_nearest_ladder(px, py, target_y)  # 下行=离人最近,不要求梯端与怪Y对齐
            if _dn_lad:
                self._climb_state = "to_ladder"
                self._climb_ladder_x = _dn_lad["x"]
                self._climb_ladder_y_top = _dn_lad["y_top"]
                self._climb_ladder_y_bottom = _dn_lad["y_bottom"]
                self._climb_target_y = target_y
                self._climb_direction = -1
                self._ladder_run_jump = False
                self._ladder_vert_jump = False
                _debug_log("[路线] 目标在下层dy=%.0f,去离人最近梯子x=%.0f按↓下" % (dy, _dn_lad["x"]))
                return False
            if _dn_jk and abs(dx) <= 15:
                # 没选到梯子但水平已对齐:仍允许直接下跳,落地后下轮重新决策
                _enter_jump_down()
                _debug_log("[下跳·下行入口] 无梯但X对齐,松攻击/左右后按住↓等200ms再跳 dy=%.0f" % dy)
                return False

        # 垂直差异大且水平已对齐 → 跳跃/瞬移（没梯子时的兜底）
        # 【用户2026-09-08】跨层移动中不触发这个兜底跳：到顶后人物黄点和梯子上端重合=到顶，左右走就好了，不要跳（一跳就掉回第一层）
        if abs(dy) > 8 and abs(dx) <= 25 and not getattr(self, '_combat_transit', False):
            now_ms = time.time() * 1000
            fight_cfg = self._get_fight_config()
            tp_key = fight_cfg.get("teleport_key", "")
            tp_dist = fight_cfg.get("teleport_distance_y", 0)  # 垂直瞬移看Y瞬移距离(空/0=不垂直瞬移→走跳/梯子)
            jump_key = fight_cfg.get("jump_key", "")
            vertical_gap = abs(dy)
            going_up = target_y < py  # 小地图y越小越靠上
            aligned = abs(dx) <= 15  # 水平对齐才跳，避免乱跳（下跳放宽到15）

            # --- 去上层：先跳 → 瞬移 → 梯子 ---
            if going_up:
                # 1. 小高度差且水平对齐才跳
                if vertical_gap <= 15 and jump_key and aligned:
                    self._climb_state = "jump_up"
                    self._climb_target_y = target_y
                    self._climb_start_y = py
                    self._climb_action_time = now_ms
                    self._press_game_key(jump_key, duration=80)
                    # 跳起后按住上键（向上移动；Y检测在jump_up状态里）
                    if VK_UP not in self._random_move_keys:
                        self._key_down(VK_UP)
                    _debug_log("[上跳] 目标y=%.0f 当前y=%.0f，间距=%.0f，尝试跳跃" % (
                        target_y, py, vertical_gap))
                    return False
                # 2. 瞬移（没配置直接忽略）
                if tp_key and tp_dist > 0 and tp_dist >= vertical_gap:
                    self._climb_state = "teleport"
                    self._climb_target_y = target_y
                    self._climb_direction = 1
                    self._do_teleport(py)
                    _debug_log("[瞬移] 目标y=%.0f 当前y=%.0f，间距=%.0f，瞬移距离=%d，向上" % (
                        target_y, py, vertical_gap, tp_dist))
                    return False
                # 3. 都不行 → 爬梯子
                ladder = self._find_nearest_ladder(px, py, target_y)
                if ladder:
                    self._climb_state = "to_ladder"
                    self._climb_ladder_x = ladder["x"]
                    self._climb_ladder_y_top = ladder["y_top"]
                    self._climb_ladder_y_bottom = ladder["y_bottom"]
                    self._climb_target_y = target_y
                    self._climb_direction = 1
                    _debug_log("[爬梯] 目标y=%.0f 当前y=%.0f，找梯子x=%.0f，向上" % (
                        target_y, py, ladder["x"]))
                    return False

            # --- 去下层：先判定下跳 → 瞬移 → 梯子 ---
            else:
                # 1. 判定高度差能否下跳且水平对齐
                if jump_key and vertical_gap <= 60 and aligned:
                    self._release_move_conflicts()  # 用户定时序:先松攻击+左右再按↓
                    self._climb_state = "jump_down"
                    self._climb_target_y = target_y
                    self._climb_start_y = py
                    self._climb_action_time = now_ms
                    self._jd_jumped = False  # 下跳序列标志:先只按住↓,由jump_down状态机满200ms后补按跳
                    self._jd_falling = False  # 下落/落地观测阶段标志,每次新下跳重置
                    if VK_DOWN not in self._random_move_keys:
                        self._key_down(VK_DOWN)
                    _debug_log("[下跳] 间距%.0f,松攻击/左右后按住↓等200ms再跳" % vertical_gap)
                    return False
                # 2. 瞬移（没配置直接忽略）
                if tp_key and tp_dist > 0 and tp_dist >= vertical_gap:
                    self._climb_state = "teleport"
                    self._climb_target_y = target_y
                    self._climb_direction = -1
                    self._do_teleport(py)
                    _debug_log("[瞬移] 目标y=%.0f 当前y=%.0f，间距=%.0f，瞬移距离=%d，向下" % (
                        target_y, py, vertical_gap, tp_dist))
                    return False
                # 3. 都不行 → 爬梯子
                ladder = self._find_nearest_ladder(px, py, target_y)
                if ladder:
                    self._climb_state = "to_ladder"
                    self._climb_ladder_x = ladder["x"]
                    self._climb_ladder_y_top = ladder["y_top"]
                    self._climb_ladder_y_bottom = ladder["y_bottom"]
                    self._climb_target_y = target_y
                    self._climb_direction = -1
                    _debug_log("[爬梯] 目标y=%.0f 当前y=%.0f，找梯子x=%.0f，向下" % (
                        target_y, py, ladder["x"]))
                    return False

            # 没有梯子，小高度差尝试普通跳跃
            if abs(dy) <= 20 and jump_key:
                self._press_game_key(jump_key, duration=80)
                return False

        # 水平移动
        if abs(dx) > 4:
            if dx > 0:
                if VK_LEFT in self._random_move_keys:
                    self._key_up(VK_LEFT)
                if VK_RIGHT not in self._random_move_keys:
                    self._key_down(VK_RIGHT)
            else:
                if VK_RIGHT in self._random_move_keys:
                    self._key_up(VK_RIGHT)
                if VK_LEFT not in self._random_move_keys:
                    self._key_down(VK_LEFT)

            # === 卡住检测：水平移动时每1.5秒确认X是否变化，没变化=被障碍物卡住→跳跃脱困 ===
            now_ms = time.time() * 1000
            if not getattr(self, '_move_stuck_inited', False) or self._move_stuck_dir != (1 if dx > 0 else -1):
                self._move_stuck_last_x = px
                self._move_stuck_last_time = now_ms
                self._move_stuck_dir = 1 if dx > 0 else -1
                self._move_stuck_inited = True
            elif now_ms - self._move_stuck_last_time > 1500:
                if abs(px - self._move_stuck_last_x) < 5:
                    fight_cfg = self._get_fight_config()
                    jump_key = fight_cfg.get("jump_key", "")
                    if jump_key and now_ms - getattr(self, '_move_stuck_jump_time', 0) > 1200:
                        self._press_game_key(jump_key, duration=80)
                        self._move_stuck_jump_time = now_ms
                        _debug_log("[移动] 卡住：方向=%s X=%.0f 1.5秒未变化，跳跃脱困" % (
                            "右" if dx > 0 else "左", px))
                self._move_stuck_last_x = px
                self._move_stuck_last_time = now_ms

            # === 录制绿线坡度优先(用户2026-09-07补充)：前方绿线Y波动>6判坡——
            # 低向高(上坡)=按住方向跑+连跳爬上去；高向低(下坡)=只走不跳(下坡跳反而乱蹦)；平地才走下面的微高差对接 ===
            _grn_slope = self._platform_slope_ahead(px, py, 1 if dx > 0 else -1)
            _grn_jkey = self._get_fight_config().get("jump_key", "")
            if _grn_slope == 'up':
                if _grn_jkey and now_ms - getattr(self, '_last_green_slope_jump', 0) > 350:
                    self._press_game_key(_grn_jkey, duration=60)
                    self._last_green_slope_jump = now_ms
                    _debug_log("[绿线坡] 前方上坡(低向高) 跑+跳")
            elif _grn_slope == 'down':
                pass  # 下坡只走，不跳，也不进微高差跳
            elif 3 <= abs(dy) <= 20:
                # 微高差平台对接：Y差3-20像素，边走边跳跨上相邻平台（无录制坡/平地时保留原逻辑）
                jump_key = _grn_jkey
                if jump_key:
                    last_jump = getattr(self, '_last_platform_gap_jump', 0)
                    if now_ms - last_jump > 350:
                        self._press_game_key(jump_key, duration=60)
                        self._last_platform_gap_jump = now_ms
                        _debug_log("[平台对接] 微高差%.0fpx，边走边跳" % dy)
        else:
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            self._move_stuck_inited = False  # 到达目标X，重置卡住检测

        # 到达判断
        if abs(dx) <= 4 and abs(dy) <= 6:
            self._reset_climb()
            return True
        return False

    def _play_alert(self, count=5):
        """播放报警音count次"""
        import threading
        alert_path = resource_path(os.path.join("data", "alert.mp3"))
        def _play():
            try:
                import pygame
                pygame.mixer.init()
                snd = pygame.mixer.Sound(alert_path)
                for _ in range(count):
                    snd.play()
                    while pygame.mixer.get_busy():
                        time.sleep(0.1)
                    time.sleep(0.2)
            except Exception:
                try:
                    import winsound
                    for _ in range(count):
                        winsound.PlaySound(alert_path, winsound.SND_FILENAME)
                        time.sleep(0.2)
                except Exception:
                    for _ in range(count):
                        winsound.Beep(800, 300)
                        time.sleep(0.2)
        threading.Thread(target=_play, daemon=True).start()

    def _random_enhanced_tick(self, player_pos):
        """随机模式增强：2-3分钟重选路线 + 原地打怪转身 + 被撞归位"""
        now = time.time()

        # === 1. 每2-3分钟重新随机选路线（仅随机模式+有勾选方案）===
        if self.route_mode == "随机" and self._get_selected_plans():
            if self._route_reelect_time == 0:
                # 首次设置重选计时器
                self._route_reelect_time = now + random.uniform(120, 180)
            elif now >= self._route_reelect_time:
                new_route = self._random_pick_route()
                if new_route and new_route != self.current_route:
                    print("[随机] 定时重选路线：方案%d" % new_route)
                    self._switch_route(new_route)
                    self._random_route_id = new_route
                    self._add_log("定时切换路线：方案%d" % new_route)
                self._route_reelect_time = now + random.uniform(120, 180)
        else:
            self._route_reelect_time = 0

        # === 2. 原地打怪模式（没勾选方案时）===
        selected = self._get_selected_plans()
        if self.route_mode == "随机" and not selected:
            if not self._idle_combat_no_damage_logged:
                self._idle_combat_no_damage_logged = True
                print("[随机] 未勾选任何方案，原地打怪中")
                self._add_log("未勾选任何方案")

            # 记录起始位置
            if self._player_screen_pos and self._idle_combat_start_pos is None:
                self._idle_combat_start_pos = self._player_screen_pos
                self._idle_combat_attack_start = now

            # 2a. 防卡死转身：统计无伤害时长，T±5秒随机转身
            if self._combat_locked_target and self._idle_combat_attack_start > 0:
                tx, ty = self._combat_locked_target
                has_damage = self._detect_damage_number(tx, ty)
                if has_damage:
                    # 有伤害，重置攻击计时
                    self._idle_combat_attack_start = now
                    self._idle_combat_no_damage_duration = 0
                else:
                    # 无伤害，累计时长
                    attack_duration = now - self._idle_combat_attack_start
                    if self._idle_combat_no_damage_duration == 0 and attack_duration > 10:
                        # 第一次检测到持续10秒无伤害，记录T
                        self._idle_combat_no_damage_duration = attack_duration
                        self._idle_combat_turn_interval = random.uniform(
                            max(10, attack_duration - 5), attack_duration + 5)
                        self._idle_combat_last_turn = now
                        print("[转身] 首次无伤害T=%.0f秒，转身间隔=%.0f秒" % (
                            attack_duration, self._idle_combat_turn_interval))
                    elif self._idle_combat_no_damage_duration > 0:
                        # 已记录T，按间隔转身
                        if now - self._idle_combat_last_turn >= self._idle_combat_turn_interval:
                            self._do_human_turn()
                            self._idle_combat_last_turn = now
                            self._idle_combat_turn_interval = random.uniform(
                                max(10, self._idle_combat_no_damage_duration - 5),
                                self._idle_combat_no_damage_duration + 5)

            # 2b. 被怪碰撞归位（±150px）
            if self._player_screen_pos and self._idle_combat_start_pos:
                sx, sy = self._idle_combat_start_pos
                cx, cy = self._player_screen_pos
                dx = cx - sx
                dy = cy - sy
                if abs(dx) > 150 or abs(dy) > 150:
                    self._do_return_to_start(sx, sy)
        else:
            # 有方案时重置原地打怪状态
            self._idle_combat_start_pos = None
            self._idle_combat_attack_start = 0
            self._idle_combat_no_damage_duration = 0
            self._idle_combat_no_damage_logged = False
            self._return_fail_count = 0
            self._return_attempt_mode = None

    def _do_human_turn(self):
        """人性化转身：短按反方向键再转回来"""
        facing = getattr(self, '_combat_facing', 0)
        if facing == 0:
            # 朝向未知，随机转一下
            vk = random.choice([0x25, 0x27])
        else:
            # 按反方向
            vk = 0x25 if facing > 0 else 0x27
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001
        user32.keybd_event(vk, scan, ext, 0)
        time.sleep(random.uniform(0.08, 0.15))
        user32.keybd_event(vk, scan, ext | 0x0002, 0)
        # 等一下再按回原方向
        time.sleep(random.uniform(0.1, 0.2))
        back_vk = 0x27 if vk == 0x25 else 0x25
        scan2 = user32.MapVirtualKeyW(back_vk, 0)
        user32.keybd_event(back_vk, scan2, ext, 0)
        time.sleep(random.uniform(0.08, 0.15))
        user32.keybd_event(back_vk, scan2, ext | 0x0002, 0)
        print("[转身] 完成人性化转身")

    def _do_return_to_start(self, target_x, target_y):
        """归位到起始位置：跳3次→梯子→平台→暂停报警"""
        if not self._player_screen_pos:
            return
        cx, cy = self._player_screen_pos
        dx = target_x - cx
        dy = target_y - cy

        # 释放战斗移动
        self._release_combat_move()

        if self._return_attempt_mode is None:
            self._return_attempt_mode = 'jump'
            self._return_fail_count = 0
            print("[归位] 偏移(%.0f,%.0f)超150px，开始归位" % (dx, dy))

        if self._return_attempt_mode == 'jump':
            # 尝试跳3次，每次跳完检测X变化
            old_x = cx
            self._jump_once()
            time.sleep(0.5)
            if self._player_screen_pos:
                new_x = self._player_screen_pos[0]
                if abs(new_x - target_x) < 150:
                    print("[归位] 跳跃归位成功")
                    self._return_attempt_mode = None
                    self._return_fail_count = 0
                    return
                if abs(new_x - old_x) < 5:
                    self._return_fail_count += 1
                else:
                    self._return_fail_count = 0  # 有进展重置
            else:
                self._return_fail_count += 1
            if self._return_fail_count >= 3:
                self._return_attempt_mode = 'ladder'
                self._return_fail_count = 0
                print("[归位] 跳跃失败，尝试梯子")

        elif self._return_attempt_mode == 'ladder':
            # 检测身边是否有梯子
            ladder_found = self._try_ladder_return(target_x, target_y)
            if ladder_found:
                print("[归位] 梯子归位成功")
                self._return_attempt_mode = None
                self._return_fail_count = 0
                return
            self._return_fail_count += 1
            if self._return_fail_count >= 3:
                self._return_attempt_mode = 'platform'
                self._return_fail_count = 0
                print("[归位] 梯子失败，尝试平台路线")

        elif self._return_attempt_mode == 'platform':
            # 检测绿色平台线是否能直达
            platform_found = self._try_platform_return(target_x, target_y)
            if platform_found:
                print("[归位] 平台路线归位成功")
                self._return_attempt_mode = None
                self._return_fail_count = 0
                return
            self._return_fail_count += 1
            if self._return_fail_count >= 3:
                # 全部失败，暂停脚本+报警
                print("[归位] 归位失败，暂停脚本并报警")
                self._add_log("归位失败，脚本已暂停")
                self._stop_random()
                self._play_alert(5)
                self._return_attempt_mode = None
                self._return_fail_count = 0

    def _jump_once(self):
        """跳一次（短按跳跃键）"""
        # 尝试常见跳跃键：Alt
        vk = 0x12  # VK_MENU = Alt
        scan = user32.MapVirtualKeyW(vk, 0)
        ext = 0x0001
        user32.keybd_event(vk, scan, ext, 0)
        time.sleep(0.08)
        user32.keybd_event(vk, scan, ext | 0x0002, 0)

    def _try_ladder_return(self, target_x, target_y):
        """尝试通过梯子归位，返回True/False"""
        if not self.ladders or not self._player_screen_pos:
            return False
        cx, cy = self._player_screen_pos
        # 找身边最近的梯子（屏幕距离100px内）
        best = None
        best_dist = 100
        for ld in self.ladders:
            lx = ld.get("x", 0)
            dist = abs(lx - cx)
            if dist < best_dist:
                best_dist = dist
                best = ld
        if best is None:
            return False
        # 往梯子方向移动
        dir_key = 0x27 if best["x"] > cx else 0x25
        scan = user32.MapVirtualKeyW(dir_key, 0)
        ext = 0x0001
        user32.keybd_event(dir_key, scan, ext, 0)
        time.sleep(0.3)
        user32.keybd_event(dir_key, scan, ext | 0x0002, 0)
        # 检查是否靠近目标
        if self._player_screen_pos:
            if abs(self._player_screen_pos[0] - target_x) < 150:
                return True
        return False

    def _try_platform_return(self, target_x, target_y):
        """尝试通过绿色平台线归位，返回True/False"""
        if not self.platforms or not self._player_screen_pos:
            return False
        cx, cy = self._player_screen_pos
        # 找当前所在平台，沿平台方向移动
        current_pf = self._get_current_manual_platform()
        if current_pf:
            pts = self._platform_points(current_pf)
            if pts:
                # 往目标方向移动
                dir_key = 0x27 if target_x > cx else 0x25
                scan = user32.MapVirtualKeyW(dir_key, 0)
                ext = 0x0001
                user32.keybd_event(dir_key, scan, ext, 0)
                time.sleep(0.3)
                user32.keybd_event(dir_key, scan, ext | 0x0002, 0)
                if self._player_screen_pos:
                    if abs(self._player_screen_pos[0] - target_x) < 150:
                        return True
        return False

    def _random_step(self, player_pos):
        """随机模式每帧状态机"""
        if not self._random_running:
            return

        # 【一条线原则·用户2026-09-09】新系统(_use_new_system恒True)下,所有角色行动(左右走/上下跳/瞬移/上下梯/打怪)
        # 统一由 _combat_tick 主线按 识别→锁怪→巡路→打怪 串行循环发出,本函数不再产生任何旁路行动:
        #   _random_enhanced_tick 内含 _do_human_turn(自按方向转身) 与 _do_return_to_start(自按Alt跳/找梯/走平台+阻塞sleep),
        #   是主线之外的第二条行动线,会在爬梯/打怪时抢方向/跳键把人从梯上弄下来,新系统停用(仅旧系统_use_new_system=False才往下走,保留可回滚)。
        if getattr(self, '_use_new_system', True):
            return

        # ===== 旧系统专用增强逻辑（新系统上面已return，不会执行，保留可回滚）=====
        self._random_enhanced_tick(player_pos)

        # 【新系统】使用重新定义的打怪/移动/梯子系统时，禁用旧巡路状态机
        if getattr(self, '_use_new_system', True):
            return

        if self._random_state == "idle":
            if self.route_mode == "手动":
                # 手动模式：用当前指定的方案，不随机选
                route_id = self.current_route if self._route_has_file(self.current_route) else None
            else:
                # 随机模式：随机选方案（排除上一个）
                route_id = self._random_pick_route()
            if route_id is None:
                # 没有保存路线时原地打怪，不跑平台，只检测身边怪（保持_running=True战斗继续）
                if not getattr(self, '_random_no_route_logged', False):
                    self._random_no_route_logged = True
                    print("[随机] 没有可用路线，原地打怪中（不跑平台）")
                    _debug_log("[随机] 没有可用路线，原地打怪中（不跑平台）")
                    self._add_log("无路线，原地打怪中")
                return
            self._switch_route(route_id)
            self._random_route_id = route_id
            self._random_platform_idx = 0
            self._random_state = "moving"
            print("[随机] 选择方案%d（%d平台），开始逐个打" % (route_id, len(self.platforms)))

        elif self._random_state == "moving":
            # 【模块A-需求2】战斗活跃时暂停巡路移动，由_combat_tick接管打怪
            # 原理：技能范围内有怪时_combat_active=True，此时人物应专心打怪不往别的平台跑
            if getattr(self, '_combat_active', False):
                self._release_combat_move()  # 释放上次巡路按住的移动键，避免攻击被移动拦住
                return
            if self._random_platform_idx >= len(self.platforms):
                # 全部平台打完，回起点
                self._random_state = "returning"
                return
            pf = self.platforms[self._random_platform_idx]
            pts = self._platform_points(pf)
            # 目标=曲线中点（路径中间的点）
            mid_pt = pts[len(pts) // 2]
            target_x, target_y = float(mid_pt[0]), float(mid_pt[1])
            arrived = self._move_to(player_pos, target_x, target_y)
            # 路线诊断日志（每1秒一次）
            if player_pos and time.time() - getattr(self, '_last_route_log', 0) > 1.0:
                self._last_route_log = time.time()
                px, py = player_pos
                _debug_log("[路线] 平台%d/%d 状态=%s 玩家(%.0f,%.0f) 目标(%.0f,%.0f) dx=%.0f dy=%.0f climb=%s" % (
                    self._random_platform_idx + 1, len(self.platforms),
                    self._random_state, px, py, target_x, target_y,
                    target_x - px, target_y - py, self._climb_state))
            if arrived:
                self._release_all_keys()
                self._random_state = "attacking"
                self._random_attack_start = time.time()
                self._key_down(VK_ATTACK)
                print("[随机] 到达平台%d，开始攻击" % self._random_platform_idx)

        elif self._random_state == "attacking":
            # 第三层：当前平台清完后才切换下一个平台（至少攻击1秒避免YOLO未检测到就走）
            attack_elapsed = time.time() - self._random_attack_start
            if attack_elapsed > 1.0:
                monsters_on_platform = self._filter_monsters_on_platform(
                    self._monsters, self._player_screen_pos) if self._player_screen_pos else self._monsters
                if not monsters_on_platform:
                    self._key_up(VK_ATTACK)
                    self._random_platform_idx += 1
                    self._random_state = "moving"
                    print("[随机] 平台%d已清完，前往下一个" % (self._random_platform_idx - 1))

        elif self._random_state == "returning":
            # 回到起点（第一个平台位置），然后重新随机选方案
            if self.platforms:
                pf = self.platforms[0]
                pts = self._platform_points(pf)
                mid_pt = pts[len(pts) // 2]
                target_x, target_y = float(mid_pt[0]), float(mid_pt[1])
                arrived = self._move_to(player_pos, target_x, target_y)
                if arrived:
                    self._release_all_keys()
                    self._random_state = "idle"
                    print("[随机] 已回起点，重新随机选方案")

    def _capture_window(self):
        """截取游戏整个窗口画面（包括标题栏，和自动吃药等功能坐标一致）。
        定稿方案=用mss(BitBlt)从屏幕DC截取游戏窗口矩形（见PROJECT_STATE.md 截图方式），不换底层。"""
        if self.hwnd is None or not self.window_rect or self.window_rect.get("width", 0) <= 0:
            return None
        r = self.window_rect
        try:
            return np.array(self.sct.grab(r))[:, :, :3]
        except Exception as _e:
            # 截图瞬时失败：不抛异常（防闪退），返回None让调用方等下一帧；限频打印避免刷屏
            _now_cap = time.time()
            if _now_cap - getattr(self, '_last_capfail_t', 0) > 2.0:
                self._last_capfail_t = _now_cap
                print("[截图] mss瞬时失败已跳过本帧: %s" % _e)
            return None

    def _capture_map(self):
        if self.hwnd is None or not self.window_rect or self.window_rect.get("width", 0) <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
        r = self.map_area_rect
        # 未截取小地图时map_area_rect为None，返回全黑图，不抛异常（否则主循环卡死第0帧）
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)
        # [CPU优化2026-09-07] 截图共用：检测线程每周期已有全窗口帧_raw_frame(客户区坐标)，
        # 小地图区域直接从中裁剪，省掉主循环每帧一次独立mss截图(~10-13ms/帧，每秒130-180ms)。
        # 帧龄≤0.8s才复用：检测线程战斗周期250ms/空闲周期700ms都能命中，超龄才补截（光点最多滞后0.7s，
        # 挂机状态光点几乎不动无影响，战斗时检测线程自动切250ms周期光点依然跟手）。
        _rf = getattr(self, '_raw_frame', None)
        _rft = getattr(self, '_raw_frame_t', 0)
        if _rf is not None and (time.time() - _rft) <= 0.8:
            _h, _w = _rf.shape[:2]
            _x0, _y0 = int(r["left"]), int(r["top"])
            _x1 = min(_x0 + int(r["width"]), _w)
            _y1 = min(_y0 + int(r["height"]), _h)
            if _x1 > _x0 and _y1 > _y0:
                return _rf[_y0:_y1, _x0:_x1].copy()
        # 兜底补截：用mss全窗口再裁剪小地图区域
        try:
            _full = self._capture_window()
            if _full is not None:
                _fh, _fw = _full.shape[:2]
                _x0, _y0 = int(r["left"]), int(r["top"])
                _x1 = min(_x0 + int(r["width"]), _fw)
                _y1 = min(_y0 + int(r["height"]), _fh)
                if _x1 > _x0 and _y1 > _y0:
                    return _full[_y0:_y1, _x0:_x1].copy()
        except Exception:
            pass
        return np.zeros((MAP_H, FIXED_W, 3), dtype=np.uint8)

    def find_player_dot(self, map_area):
        """【模块B】检测小地图上人物黄色光点（纯色识别：只认中心色 ffff88，加偏色±5，在小地图块内找唯一中心，取中心点）
        原理：人物光点中心颜色 = ffff88 (BGR 136,255,255)，加一点偏色容差, 在map_area(整个小地图块)内找该色像素, 取质心作为光点中心。
        返回：(x, y) 光点中心坐标；找不到返回None"""
        bgr = map_area  # BGR原图(小地图块)
        # 中心色 ffff88 = BGR(136,255,255)；加偏色±5 -> B 131~141
        mask = cv2.inRange(bgr, np.array([131, 250, 250]), np.array([141, 255, 255]))
        ys, xs = np.where(mask > 0)
        if len(xs) > 0:
            cx = int(xs.mean())  # 中心X(该色像素质心)
            cy = int(ys.mean())  # 中心Y
            if getattr(self, 'frame_count', 0) % 10 == 0:
                _debug_log("[光点检测] ffff88纯色定位 center=(%d,%d) 像素数=%d" % (cx, cy, len(xs)))
            self.last_player_pos = (cx, cy)  # 更新上次位置
            return (cx, cy)  # 返回光点中心
        self.last_player_pos = None  # 没找到，清空上次位置
        return None  # 返回None

    def _point_to_polyline_dist(self, px, py, points):
        """点到折线的最近距离（小地图坐标）。points为[(x,y),...]列表。"""
        if not points or len(points) < 2:
            return 999.0
        min_dist = 999.0
        for i in range(len(points) - 1):
            x1, y1 = float(points[i][0]), float(points[i][1])
            x2, y2 = float(points[i+1][0]), float(points[i+1][1])
            dx, dy = x2 - x1, y2 - y1
            if dx == 0 and dy == 0:
                d = ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
                proj_x = x1 + t * dx
                proj_y = y1 + t * dy
                d = ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
            if d < min_dist:
                min_dist = d
        return min_dist

    def _platform_points(self, pf):
        """获取平台的折线路径点，兼容旧格式{x_min,x_max,y_base}（转成水平线）。"""
        if "points" in pf and pf["points"] and len(pf["points"]) >= 2:
            return pf["points"]
        # 旧格式兼容：生成水平直线
        x_min, x_max, y_base = pf["x_min"], pf["x_max"], pf["y_base"]
        return [[x_min, y_base], [x_max, y_base]]

    def _platform_x_range(self, pf):
        """获取平台的x范围（兼容新旧格式）。"""
        pts = self._platform_points(pf)
        xs = [p[0] for p in pts]
        return min(xs), max(xs)

    def _platform_y_avg(self, pf):
        """平台平均Y（小地图坐标）：折线点Y均值；旧格式用y_base"""
        pts = self._platform_points(pf)
        if pts:
            return sum(float(p[1]) for p in pts) / len(pts)
        return float(pf.get("y_base", 0.0))

    def _polyline_y_at(self, points, x):
        """录制绿线(折线)在指定小地图X处的Y，按X排序后分段线性插值；x超出折线范围取最近端点Y；无点返回None。"""
        if not points:
            return None
        sp = sorted([(float(p[0]), float(p[1])) for p in points], key=lambda p: p[0])
        if x <= sp[0][0]:
            return sp[0][1]
        if x >= sp[-1][0]:
            return sp[-1][1]
        for i in range(len(sp) - 1):
            x0, y0 = sp[i]
            x1, y1 = sp[i + 1]
            if x0 <= x <= x1:
                if x1 == x0:
                    return y0
                return y0 + (y1 - y0) * ((x - x0) / (x1 - x0))
        return None

    def _platform_slope_ahead(self, px, py, dir_sign, look=GREEN_SLOPE_LOOK):
        """沿当前录制绿线看前方 look 个小地图单位的地形起伏(用户2026-09-07补充)。
        前提：人物正站在某条录制绿线上(_get_current_manual_platform)。
        - 窗口内绿线Y波动≤GREEN_SLOPE_MIN(6)=平地小抖动→返回None正常走；
        - 'up'=低向高(前方小地图Y变小=上坡)→调用方跑+跳；
        - 'down'=高向低(前方Y变大=下坡)→调用方只走不跳；
        dir_sign=+1向右/-1向左；py=人物当前小地图Y(近端基准)。"""
        pf = self._get_current_manual_platform()
        if pf is None:
            return None
        pts = self._platform_points(pf)
        if not pts or len(pts) < 2:
            return None
        x_far = px + dir_sign * look
        y_far = self._polyline_y_at(pts, x_far)
        if y_far is None:
            return None
        lo_x, hi_x = sorted((px, x_far))
        win_ys = [float(y) for (x, y) in pts if lo_x - 1 <= float(x) <= hi_x + 1]
        # 波动≤6px视为平地(录制噪声/水平台)，不触发跑跳
        if win_ys and (max(win_ys) - min(win_ys)) <= GREEN_SLOPE_MIN:
            return None
        d = y_far - py   # 负=前方更高=人物由低向高=上坡
        if d < -GREEN_SLOPE_MIN:
            return 'up'
        if d > GREEN_SLOPE_MIN:
            return 'down'
        return None

    def _get_current_manual_platform(self):
        """【模块B】获取人物当前所在的手动录制平台（用于移动边界限制）
        用途：判断人物在哪个手动录制平台上，限制人物在平台X范围内打怪
        原理：
          1. 遍历所有手动录制平台
          2. 计算人物小地图坐标到平台折线的距离
          3. 距离最小且≤15px的平台 = 人物当前所在平台
        返回：平台对象dict；找不到返回None"""
        if not self.platforms or not self._player_map_pos:
            return None
        mx, my = self._player_map_pos
        best_pf = None
        best_dist = 999.0
        for pf in self.platforms:
            pts = self._platform_points(pf)
            d = self._point_to_polyline_dist(mx, my, pts)
            if d < best_dist:
                best_dist = d
                best_pf = pf
        if best_pf and best_dist <= 15:
            return best_pf
        return None

    def _check_platform_boundary(self):
        """【模块B】检测人物是否超出手动录制平台的X边界，超出则返回往回走的方向
        用途：人物到了平台边缘自动回去，只打平台X范围内的怪
        原理：
          1. 获取人物当前所在的手动录制平台
          2. 获取平台X范围（x_min, x_max）
          3. 人物X < x_min → 需要往右走回去
          4. 人物X > x_max → 需要往左走回去
          5. 在范围内 → 返回None（不需要调整）
        返回：'right'=需要往右走, 'left'=需要往左走, None=在范围内"""
        pf = self._get_current_manual_platform()
        if pf is None or not self._player_map_pos:
            return None
        x_min, x_max = self._platform_x_range(pf)
        px = self._player_map_pos[0]
        if px < x_min + 2:  # 超出左边界2px
            return 'right'
        elif px > x_max - 2:  # 超出右边界2px
            return 'left'
        return None

    def _locked_platform_x_range(self):
        """【锁平台·冒险岛世界2026-09-07】勾选了平台编号时，返回这些平台绿线在【小地图】上的X范围并集(min,max)，
        作为人物移动的硬边界——只勾1个就是那条绿线的左右端点。未勾选任何平台(全图模式)返回None=不限制。
        编号口径与combat_logic一致：平台显示编号 = pf['id']+1。"""
        if not self._selected_platforms or not self.platforms:
            return None
        xs = []
        for pf in self.platforms:
            if (pf.get('id', 0) + 1) in self._selected_platforms:
                _xmn, _xmx = self._platform_x_range(pf)
                xs.append(_xmn)
                xs.append(_xmx)
        if not xs:
            return None
        return min(xs), max(xs)

    def _combat_at_locked_edge(self, move_dir):
        """【锁平台·拟人化2026-09-07】战斗移动方向是否已到平台X边缘。
        优先用"勾选平台绿线"硬边界；没勾平台才退回"人物当前所在平台"。
        拟人：①离端点随机4~10就停(不每次精确贴±2) ②触发线/恢复线分开(滞回8单位,不在边上来回抖)
        ③硬保底：已超出边界时朝界外方向绝对不能走。True=朝该方向不能再走。"""
        if move_dir not in ("left", "right") or not self._player_map_pos:
            return False
        xr = self._locked_platform_x_range()
        if xr is None:
            cur = self._get_current_platform()
            if not cur:
                return False
            xr = self._platform_x_range(cur)
        ppx = self._player_map_pos[0]
        _xmin, _xmax = xr
        # 硬保底：已超出边界，朝界外方向绝对不能走（宁可原地跳/停，也不掉）
        if move_dir == "right" and ppx >= _xmax:
            return True
        if move_dir == "left" and ppx <= _xmin:
            return True
        # 拟人：随机停止余量（4~10）+ 滞回状态（每次从边缘回来后重新随机）
        if not hasattr(self, '_edge_stop_margin'):
            self._edge_stop_margin = {'left': random.randint(4, 10), 'right': random.randint(4, 10)}
            self._edge_at_edge = {'left': False, 'right': False}
        m = self._edge_stop_margin
        at = self._edge_at_edge
        if move_dir == "right":
            # 触发线：到 xmax-margin 就停；恢复线：回到 xmax-margin-8 才允许再走（滞回防抖）
            if ppx >= _xmax - m['right']:
                at['right'] = True
            elif ppx <= _xmax - m['right'] - 8:
                at['right'] = False
                m['right'] = random.randint(4, 10)  # 恢复后重新随机余量，不每次停同一位置
            return at['right']
        else:
            if ppx <= _xmin + m['left']:
                at['left'] = True
            elif ppx >= _xmin + m['left'] + 8:
                at['left'] = False
                m['left'] = random.randint(4, 10)
            return at['left']

    # ========================================================================
    # 【模块B】平台判定优化：配合小地图绿线和人物光点，判定怪在哪个平台
    # ========================================================================

    def _effective_scale(self):
        """【模块B】返回最终倍率(总值) = 检测值 + 手动偏移值。
        检测值：三点检测/手动记录写入的 _calibrated_scale_x/y；未检测时用默认值(0.10)。
        手动偏移：倍率差弹窗里用户输入的 scale_x_offset/scale_y_offset。
        总值一旦定下来就被锁定(见 _update_scale_calibration)，不再随人物走动变化。
        注意：换算用的scale不能为0(否则怪物坐标全换算到人物/崩)，未校准用0.10兜底。"""
        base_x = getattr(self, '_calibrated_scale_x', 0.10)
        base_y = getattr(self, '_calibrated_scale_y', 0.10)
        try:
            off_x = float(self._field_values.get("scale_x_offset", "0") or "0")
        except (ValueError, TypeError):
            off_x = 0.0
        try:
            off_y = float(self._field_values.get("scale_y_offset", "0") or "0")
        except (ValueError, TypeError):
            off_y = 0.0
        return (base_x + off_x, base_y + off_y)

    def _screen_to_map(self, screen_x, screen_y):
        """【模块B】屏幕坐标转小地图坐标（以人物光点为参考点，比固定scale更准）
        用途：怪在屏幕中的位置(YOLO检测) → 估算怪在小地图上的坐标
        原理：怪小地图X = 人物小地图X + (怪屏幕X - 人物屏幕X) * scale
              怪小地图Y = 人物小地图Y + (怪屏幕Y - 人物屏幕Y) * scale
        参数：screen_x, screen_y = 怪在游戏画面中的屏幕坐标
        返回：(map_x, map_y) 估算的小地图坐标；人物位置未知时返回None"""
        # 人物小地图坐标（黄色光点中心）
        if not self._player_map_pos or not self._player_screen_pos:
            return None
        pmap_x, pmap_y = self._player_map_pos       # 人物在小地图上的坐标
        pscr_x, pscr_y = self._player_screen_pos     # 人物在游戏画面中的屏幕坐标
        # X和Y用各自的最终scale = 定完点锁定的倍率 + 手动偏移（最终值）
        effective_sx, effective_sy = self._effective_scale()
        # 以人物为参考点，计算怪相对于人物的偏移，再转成小地图偏移
        map_x = pmap_x + (screen_x - pscr_x) * effective_sx
        map_y = pmap_y + (screen_y - pscr_y) * effective_sy
        return (map_x, map_y)

    def _update_scale_calibration(self):
        """【模块B】自动校准scale比例（人物移动时记录屏幕和小地图变化，计算实际比例）
        用途：替代固定scale=0.10，越跑越准
        原理：
          1. 记录上一帧人物的屏幕坐标和小地图坐标
          2. 当前帧计算变化量 Δ屏幕 和 Δ小地图
          3. 实际scale = Δ小地图 / Δ屏幕（变化量足够大时才更新，避免噪声）
          4. 用滑动平均更新校准值（新值占20%，旧值占80%）
        调用时机：每帧人物位置更新后调用"""
        # ===== 用户需求：总值(检测值+偏移)定下后就固定，绝不自动变。 =====
        # 检测值 _calibrated_scale_x/y 只能由「三点检测 / 手动记录」写入，且可被下次检测覆盖；
        # 偏移值 scale_x_offset/y_offset 只能手动调。这里禁止任何自动校准改动检测值。
        # 否则人物一走动，检测值被滑动平均改动，总值就会一直漂移。
        return
    def _auto_calibrate_edges(self):
        """【模块B】自动记录人物最左/最右端点（每3秒检测一次，人物站在边缘3秒自动记录）
        用途：通过记录人物在最左和最右时的屏幕X和小地图X，计算实际scale_x
        原理：
          1. 每3秒检测一次人物位置（避免每帧比较，减少性能消耗）
          2. 比最左点更左 → 更新最左点（记录屏幕X+小地图X+小地图Y）
          3. 比最右点更右 → 更新最右点
          4. 左右都记录到后 → scale_x = (右小地图X - 左小地图X) / (右屏幕X - 左屏幕X)
        使用方法：人物站在最左边3秒自动记录，再站最右边3秒自动记录
        手动校准优先：_manual_calib_done=True时，跳过自动记录（避免覆盖手动值）
        副作用（永久记住）：
          1. 自动记录的左右端点可能不是真正的平台两端（人物没走到边缘）
          2. 如果人物在小地图范围内移动，记录的范围偏小，scale_x不准
          3. 解决：不准时用手动记录（人物停在平台两端点按钮）"""
        # 手动校准已执行时，跳过自动记录（避免覆盖手动值）
        if getattr(self, '_manual_calib_done', False):
            return
        # 每3秒检测一次（避免每帧比较，减少性能消耗，人物站在边缘3秒自动记录）
        now_ms = time.time() * 1000
        last_time = getattr(self, '_last_auto_calib_time', 0)
        if now_ms - last_time < 3000:
            return
        self._last_auto_calib_time = now_ms
        if not self._player_map_pos or not self._player_screen_pos:
            # 调试：每5秒打印一次检测状态，帮助排查
            _now = time.time()
            if not hasattr(self, '_last_calib_debug') or _now - self._last_calib_debug > 5:
                self._last_calib_debug = _now
                _debug_log("[自动校准] 检测状态: 小地图位置=%s 屏幕位置=%s (屏幕位置需设置人物特征模板)" % (
                    'OK' if self._player_map_pos else 'None',
                    'OK' if self._player_screen_pos else 'None(需设置人物特征)'))
            return
        cur_scr_x = self._player_screen_pos[0]
        cur_scr_y = self._player_screen_pos[1]
        cur_map_x = self._player_map_pos[0]
        cur_map_y = self._player_map_pos[1]
        # 初始化左右端点记录
        left_pt = getattr(self, '_calib_left_pt', None)
        right_pt = getattr(self, '_calib_right_pt', None)
        old_left = left_pt
        old_right = right_pt
        # 自动更新最左点（当前屏幕X比记录的更左）
        if left_pt is None or cur_scr_x < left_pt[0]:
            # 记录完整坐标：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
            self._calib_left_pt = (cur_scr_x, cur_scr_y, cur_map_x, cur_map_y)
            left_pt = self._calib_left_pt
        # 自动更新最右点（当前屏幕X比记录的更右）
        if right_pt is None or cur_scr_x > right_pt[0]:
            # 记录完整坐标：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
            self._calib_right_pt = (cur_scr_x, cur_scr_y, cur_map_x, cur_map_y)
            right_pt = self._calib_right_pt
        # 自动更新最高点（当前屏幕Y比记录的更小=更高）
        top_pt = getattr(self, '_calib_top_pt', None)
        old_top = top_pt
        if top_pt is None or cur_scr_y < top_pt[0]:
            self._calib_top_pt = (cur_scr_y, cur_map_y)
            top_pt = self._calib_top_pt
        # 左右都记录到后，计算scale_x
        if left_pt and right_pt and right_pt[0] > left_pt[0] + 50:
            # 屏幕X差>50px才计算（避免范围太小不准）
            dx_scr = right_pt[0] - left_pt[0]
            # 兼容旧格式：新格式小地图X在索引2，旧格式在索引1
            lx_map = left_pt[2] if len(left_pt) >= 4 else left_pt[1]
            rx_map = right_pt[2] if len(right_pt) >= 4 else right_pt[1]
            dx_map = rx_map - lx_map
            if dx_map > 1:
                scale_x = dx_map / dx_scr
                # 自动校准的scale_x权重50%（因为可能不是真正的平台两端）
                old_scale = getattr(self, '_calibrated_scale_x', 0.10)
                self._calibrated_scale_x = old_scale * 0.5 + scale_x * 0.5
                self._map_screen_scale = self._calibrated_scale_x
        # 端点有更新就自动保存到文件（永久保存，重启不丢失）
        if (old_left != self._calib_left_pt) or (old_right != self._calib_right_pt) or (old_top != self._calib_top_pt):
            self._save_calib()
            # 上端点或左端点变化时重新计算scale_y
            if old_top != self._calib_top_pt or old_left != self._calib_left_pt:
                self._recalc_scale_from_edges()

    def _manual_calibrate_left(self):
        """【模块B】手动记录左端点（人物停在平台最左端后点按钮）
        用途：精确记录平台左端，同时作为Y轴下端点
        原理：记录当前人物的屏幕(X,Y)和小地图(X,Y)作为左端点
        副作用：手动记录后关闭自动记录（避免自动记录覆盖手动值）"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("手动校准失败：未检测到人物位置")
            return
        # 记录完整坐标：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
        self._calib_left_pt = (self._player_screen_pos[0], self._player_screen_pos[1],
                               self._player_map_pos[0], self._player_map_pos[1])
        self._manual_calib_done = True  # 标记手动校准已执行，关闭自动记录
        self._add_log("已记录左端点：屏幕(%d,%d) 小地图(%d,%d)" % (
            self._player_screen_pos[0], self._player_screen_pos[1],
            self._player_map_pos[0], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _manual_calibrate_right(self):
        """【模块B】手动记录右端点（人物停在平台最右端后点按钮）
        用途：精确记录平台右端
        原理：记录当前人物的屏幕(X,Y)和小地图(X,Y)作为右端点
        副作用：手动记录后关闭自动记录（避免自动记录覆盖手动值）"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("手动校准失败：未检测到人物位置")
            return
        # 记录完整坐标：(屏幕X, 屏幕Y, 小地图X, 小地图Y)
        self._calib_right_pt = (self._player_screen_pos[0], self._player_screen_pos[1],
                                self._player_map_pos[0], self._player_map_pos[1])
        self._manual_calib_done = True  # 标记手动校准已执行，关闭自动记录
        self._add_log("已记录右端点：屏幕(%d,%d) 小地图(%d,%d)" % (
            self._player_screen_pos[0], self._player_screen_pos[1],
            self._player_map_pos[0], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _manual_calibrate_top(self):
        """【模块B】手动记录上端点（人物爬到最高处后点按钮）
        用途：Y轴校准，配合左端点（Y下端点）算出scale_y
        原理：记录当前人物的屏幕Y和小地图Y作为上端点
        记录格式：(屏幕Y, 小地图Y)"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._add_log("手动校准失败：未检测到人物位置")
            return
        self._calib_top_pt = (self._player_screen_pos[1], self._player_map_pos[1])
        self._add_log("已记录上端点：屏幕Y=%d 小地图Y=%d" % (
            self._player_screen_pos[1], self._player_map_pos[1]))
        self._save_calib()
        self._recalc_scale_from_edges()

    def _calib_fail(self, msg):
        """【倍率新方案】某步记录失败：提示重试，连续失败3次退出整个校准流程"""
        self._auto_calib_retry += 1  # 失败次数+1
        self._add_log("%s（第%d次，请重试）" % (msg, self._auto_calib_retry))
        if self._auto_calib_retry >= 3:  # 连续3次失败
            self._add_log("连续失败3次，退出倍率校准")
            self._reset_calib_state()  # 清空校准状态
            self._auto_calib_stage = 0  # 回到空闲
            self._auto_calib_retry = 0  # 重置失败计数

    def _reset_calib_state(self):
        """【倍率新方案】清空所有校准相关数据/点位（当前校准结束时或失败退出时调用）"""
        self._auto_calib_base = None  # 基点
        self._auto_calib_green_map = None  # 绿点(红圈X)小地图坐标
        self._auto_calib_blue_map = None  # 蓝点(蓝圈Y)小地图坐标
        self._auto_calib_green_screen = None  # 绿点屏幕坐标
        self._auto_calib_blue_screen = None  # 蓝点屏幕坐标
        self._auto_calib_dragging = None  # 拖动状态
        self._calib_green_template = None  # 绿点背景模板
        self._calib_blue_template = None   # 蓝点背景模板
        self._calib_green_match_pos = None  # 绿点模板匹配位置
        self._calib_blue_match_pos = None   # 蓝点模板匹配位置
        self._auto_calib_green_offset = (400, 0)  # 复位X光圈在基点右方400（水平，可拖动调）
        self._auto_calib_blue_offset = (0, -400)  # 复位Y光圈在基点上方400（可拖动调）

    def _calib_finish_keep_dot(self):
        """【倍率新方案】完成时：清光圈(基点屏幕/光圈屏幕位置/模板/拖动)，同时清小地图红点(基点)/绿点/蓝点"""
        self._auto_calib_green_screen = None   # 清绿圈屏幕位置(光圈)
        self._auto_calib_blue_screen = None    # 清蓝圈屏幕位置(光圈)
        self._auto_calib_dragging = None       # 清拖动状态
        self._calib_green_template = None      # 清绿点模板(光圈识别用)
        self._calib_blue_template = None       # 清蓝点模板
        self._calib_green_match_pos = None     # 清绿点匹配位置(光圈)
        self._calib_blue_match_pos = None      # 清蓝点匹配位置
        # 【需求】第3次点完成后小地图红/绿/蓝点也全部消失，不留任何标记
        self._auto_calib_base = None           # 清基点(红点)
        self._auto_calib_green_map = None      # 清绿点
        self._auto_calib_blue_map = None       # 清蓝点

    def _start_auto_calibration(self, axis='X'):
        """【倍率新方案】分开取样：axis='X' 用绿圈只取X分量，axis='Y' 用蓝圈只取Y分量
        光圈流程：记基点→出光圈(绿/蓝)拖到独特位置→人物走到光圈→记录→算倍率
        每步引导文字(窗口最顶白区红字)；某步失败提示重试，连续失败3次退出整个流程"""
        if axis not in ('X', 'Y'):  # 非法方向直接忽略
            return
        self._auto_calib_axis = axis  # 当前校准方向
        _ax_label = "X" if axis == 'X' else "Y"  # 显示用方向名
        _ring = "绿" if axis == 'X' else "蓝"      # 光圈颜色名

        # 3次点击流程：第3次点直接完成(算倍率+清光圈保留红/绿点)，无第4次

        # 每次点记录：强制重新截取小地图+检测人物光点，确保最新准确坐标（不用缓存）
        try:
            _map_frame = self._capture_map()
            if _map_frame is not None:
                _detected = self.find_player_dot(_map_frame)
                if _detected:
                    self._player_map_pos = _detected
        except Exception:
            pass

        cur_sx = cur_sy = cur_mx = cur_my = 0
        # 未加载人物特征(模板0套)时，X/Y倍率无法定位人物屏幕位置，提示先添加人物特征
        if not getattr(self, '_char_templates', None):
            self._calib_fail("%s倍率：未添加人物特征，请先添加人物特征" % _ax_label)
            self._add_log("请先添加人物特征（框选角色），再点%s倍率" % _ax_label)
            return
        if self._auto_calib_stage in (0, 1):  # 第1/2步需要屏幕+小地图坐标
            if not self._player_map_pos or not self._player_screen_pos:
                self._calib_fail("%s倍率：未检测到人物位置" % _ax_label)
                return
            cur_sx, cur_sy = self._player_screen_pos[0], self._player_screen_pos[1]
            cur_mx, cur_my = self._player_map_pos[0], self._player_map_pos[1]
        elif self._auto_calib_stage == 2:  # 第3步只需小地图坐标
            if not self._player_map_pos:
                self._calib_fail("记录失败请重试")
                return
            cur_mx, cur_my = self._player_map_pos[0], self._player_map_pos[1]

        # 第1步：记基点 + 出光圈（X=绿圈，Y=蓝圈），默认偏移400可拖动
        if self._auto_calib_stage == 0:
            self._auto_calib_base = (cur_sx, cur_sy, cur_mx, cur_my)  # 记录基点(人物位置)
            if axis == 'X':
                self._auto_calib_green_offset = (400, 0)  # X光圈默认在基点右方400（水平，提供X分量，可拖动调）
            else:
                self._auto_calib_blue_offset = (0, -400)  # Y光圈默认在基点上方400（可拖动调）
            self._auto_calib_green_map = None  # 清空旧绿点
            self._auto_calib_blue_map = None   # 清空旧蓝点
            self._auto_calib_green_screen = None
            self._auto_calib_blue_screen = None
            self._auto_calib_dragging = None
            self._calib_green_template = None
            self._calib_blue_template = None
            self._calib_green_match_pos = None
            self._calib_blue_match_pos = None
            self._auto_calib_stage = 1
            self._add_log("请移动光圈到角色能够到达的位置并且相对固定的背景上")
            return

        # 第2步：定光圈屏幕位置（截图45x45模板，记忆文件坑5）
        if self._auto_calib_stage == 1:
            if axis == 'X':
                goff = self._auto_calib_green_offset
                self._auto_calib_green_screen = (cur_sx + goff[0], cur_sy + goff[1])
            else:
                boff = self._auto_calib_blue_offset
                self._auto_calib_blue_screen = (cur_sx + boff[0], cur_sy + boff[1])
            if self._overlay_hwnd:
                user32.ShowWindow(self._overlay_hwnd, 0)  # 隐藏蒙板避免截到圈本身
                time.sleep(0.1)
            if axis == 'X':
                _ok = self._capture_calib_template(self._auto_calib_green_screen, 'green')
            else:
                _ok = self._capture_calib_template(self._auto_calib_blue_screen, 'blue')
            time.sleep(0.1)
            if self._overlay_hwnd:
                user32.ShowWindow(self._overlay_hwnd, 5)  # 恢复蒙板显示
                time.sleep(0.05)
            if not _ok:  # 截图保存失败：提示重试，连续3次退出整个流程
                self._calib_fail("图片保存失败请重试")
                return
            self._auto_calib_stage = 2
            self._add_log("请移动角色到光圈位置")
            return

        # 第3次点：人物走到光圈，记录位置 → 算倍率 + 小地图红/绿点(保留) + 光圈消失 + 完成(3次点击结束)
        if self._auto_calib_stage == 2:
            if axis == 'X':
                self._auto_calib_green_map = (cur_mx, cur_my)  # 只取X点小地图坐标(绿点)
            else:
                self._auto_calib_blue_map = (cur_mx, cur_my)   # 只取Y点小地图坐标(蓝点)
            self._finish_auto_calibration()   # 直接算倍率(取X/Y分量)
            self._calib_finish_keep_dot()     # 清光圈(游戏画面圈消失)，保留红/绿点(小地图继续显示)
            self._auto_calib_stage = 0        # 回到空闲
            if axis == 'X':
                self._add_log("X点记录完成 请按【Y倍率】进行下一步")
            else:
                self._add_log("Y点记录完成")
            return

    def _finish_auto_calibration(self):
        """【倍率新方案】按 _auto_calib_axis 只算对应轴倍率（X用绿圈=右，Y用蓝圈=上），沿用记忆文件除以2"""
        axis = self._auto_calib_axis  # 当前校准方向
        if not self._auto_calib_base:  # 无基点
            self._calib_fail("倍率：无基点")
            return
        base_sx, base_sy, base_mx, base_my = self._auto_calib_base
        if axis == 'X':  # X倍率：用绿圈(右)
            if not self._auto_calib_green_map or not self._auto_calib_green_screen:
                self._calib_fail("X倍率：数据不完整")
                return
            gsx, gsy = self._auto_calib_green_screen  # 绿圈屏幕坐标
            gmx, gmy = self._auto_calib_green_map      # 绿圈小地图坐标
            dx_screen = gsx - base_sx  # 屏幕X位移（绿圈在基点右方为正）
            dx_map = gmx - base_mx      # 小地图X位移
            if dx_screen <= 0:
                self._calib_fail("X倍率：绿圈应在基点右方")
                return
            self._calibrated_scale_x = (dx_map / 2.0) / float(dx_screen)  # 除以2（记忆文件坑4）
            # 【护栏】倍率超出(0.01~100)说明屏幕/小地图位移异常(人物没走到光圈/光点检测跳飞)，
            # 判失败，避免算出 36555 这种垃圾值污染打怪逻辑
            if not (0.01 <= self._calibrated_scale_x <= 100.0):
                self._calib_fail("X倍率异常(%.4f)，请重试" % self._calibrated_scale_x)
                self._calibrated_scale_x = 0.10  # 回退默认，避免残留垃圾值
                return
            self._map_screen_scale = self._calibrated_scale_x  # 主scale兼容旧代码
            self._add_log("X倍率=%.4f (小地图%dpx/屏幕%dpx)" % (self._calibrated_scale_x, dx_map, dx_screen))
        elif axis == 'Y':  # Y倍率：用蓝圈(上)
            if not self._auto_calib_blue_map or not self._auto_calib_blue_screen:
                self._calib_fail("Y倍率：数据不完整")
                return
            bsx, bsy = self._auto_calib_blue_screen  # 蓝圈屏幕坐标
            bmx, bmy = self._auto_calib_blue_map      # 蓝圈小地图坐标
            dy_screen = base_sy - bsy  # 屏幕Y位移（蓝圈在基点上方为正）
            dy_map = base_my - bmy      # 小地图Y位移
            if dy_screen <= 0:
                self._calib_fail("Y倍率：蓝圈应在基点上方")
                return
            self._calibrated_scale_y = (dy_map / 2.0) / float(dy_screen)  # 除以2
            # 【护栏】Y倍率超出(0.01~100)判失败，避免垃圾值，与X一致
            if not (0.01 <= self._calibrated_scale_y <= 100.0):
                self._calib_fail("Y倍率异常(%.4f)，请重试" % self._calibrated_scale_y)
                self._calibrated_scale_y = 0.10  # 回退默认，避免残留垃圾值
                return
            self._add_log("Y倍率=%.4f (小地图%dpx/屏幕%dpx)" % (self._calibrated_scale_y, dy_map, dy_screen))
        else:
            return
        self._manual_calib_done = True  # 三点校准成功：锁定倍率，避免游戏中自动校准覆盖
        self._save_calib()  # 保存倍率到文件

    def _recalc_auto_calib_scale(self):
        """【模块B】蒙板拖动绿点蓝点后重新计算屏幕距离（仅更新屏幕坐标，倍率等人物走完再算）"""
        # 蒙板拖动只改变屏幕位置，小地图位置还没记录，所以这里不计算倍率
        pass

    def _capture_calib_template(self, screen_pos, color_tag):
        """【模块B】截取指定屏幕位置周围的背景图作为模板（用于模板匹配跟踪特色位置）
        参数：screen_pos=(屏幕X,屏幕Y)，color_tag='green'/'blue'
        返回：True成功，False失败"""
        try:
            frame = self._capture_window()
            if frame is None:
                return False
            h, w = frame.shape[:2]
            sx, sy = screen_pos
            half = self._calib_template_size // 2
            odd_offset = 1 if self._calib_template_size % 2 else 0  # 奇数尺寸+1确保完整（45→45x45，不是44x44）
            # 确保模板完整，靠近边缘自动内移（避免边界截断导致匹配失败）
            sx = max(half, min(w - half - odd_offset - 1, sx))
            sy = max(half, min(h - half - odd_offset - 1, sy))
            x1 = sx - half
            y1 = sy - half
            x2 = sx + half + odd_offset  # 奇数尺寸+1确保完整
            y2 = sy + half + odd_offset
            template = frame[y1:y2, x1:x2].copy()
            if color_tag == 'green':
                self._calib_green_template = template
            else:
                self._calib_blue_template = template
            _debug_log("[校准模板] %s截图成功 %dx%d at (%d,%d)" % (color_tag, template.shape[1], template.shape[0], sx, sy))
            return True
        except Exception as e:
            _debug_log("[校准模板] 截图失败: %s" % e)
            return False

    def _match_calib_templates(self):
        """【模块B】模板匹配：在当前游戏画面中搜索绿蓝模板的位置，更新匹配坐标
        仅在校准stage>=2时调用，每帧或每几帧调用一次"""
        if self._auto_calib_stage < 2:
            return
        if self._calib_green_template is None and self._calib_blue_template is None:
            return
        try:
            frame = self._capture_window()
            if frame is None:
                return
            # 匹配绿点模板
            if self._calib_green_template is not None:
                res = cv2.matchTemplate(frame, self._calib_green_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= self._calib_match_threshold:
                    th, tw = self._calib_green_template.shape[:2]
                    self._calib_green_match_pos = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
                else:
                    self._calib_green_match_pos = None
            # 匹配蓝点模板
            if self._calib_blue_template is not None:
                res = cv2.matchTemplate(frame, self._calib_blue_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= self._calib_match_threshold:
                    th, tw = self._calib_blue_template.shape[:2]
                    self._calib_blue_match_pos = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
                else:
                    self._calib_blue_match_pos = None
        except Exception as e:
            _debug_log("[校准模板匹配] 异常: %s" % e)

    def _save_calib(self):
        """保存端点数据和倍率到文件（左/右/上端点 + 校准倍率 + 人物特征 + YOLO路径 + 绿框）"""
        try:
            calib_file = os.path.join(DATA_DIR, "route_%03d_calib.json" % self.current_route)
            # 人物特征转base64（只保留最后一次）
            char_b64 = None
            if self._char_templates:
                tpl = self._char_templates[-1]  # 取最后一张模板存base64(兼容旧方案文件)
                ok, buf = cv2.imencode(".png", tpl["img"])
                if ok:
                    char_b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            with open(calib_file, "w", encoding="utf-8") as f:
                json.dump({
                    "calib_left": self._calib_left_pt,
                    "calib_right": self._calib_right_pt,
                    "calib_top": getattr(self, '_calib_top_pt', None),
                    "calibrated_scale_x": getattr(self, '_calibrated_scale_x', 0),
                    "calibrated_scale_y": getattr(self, '_calibrated_scale_y', 0),
                    "char_template_b64": char_b64,
                    "yolo_model_path": getattr(self, '_yolo_model_path', None),
                    "blue_box": self._blue_box,
                }, f, indent=2)
        except Exception as e:
            print("[保存] 方案配置保存失败:", e)

    def _recalc_scale_from_region(self):
        """【模块B】根据小地图区域尺寸计算X/Y scale初始值（仅当从未检测/手动记录过时使用）
        原理：scale_x=FIXED_W/小地图宽度，scale_y=MAP_H/小地图高度
        X和Y缩放比率不同，必须分开算，不能默认相等
        用户需求：检测值定下后固定(总值=检测值+偏移)，可被再次检测/手动记录覆盖，但区域初始化只在无检测值时生效"""
        r = getattr(self, 'map_area_rect', None)
        # 已有检测值(非0) → 保留用户检测/手动记录值，不让区域初始化覆盖（否则总值会变）
        if getattr(self, '_calibrated_scale_x', 0) or getattr(self, '_calibrated_scale_y', 0):
            return
        if r and r["width"] > 0 and r["height"] > 0:
            self._calibrated_scale_x = FIXED_W / r["width"]
            self._calibrated_scale_y = MAP_H / r["height"]
            self._map_screen_scale = self._calibrated_scale_x
            print("[scale] 初始值: X=%.4f Y=%.4f (区域%dx%d)" % (
                self._calibrated_scale_x, self._calibrated_scale_y, r["width"], r["height"]))

    def _recalc_scale_from_edges(self):
        """【模块B】根据端点重新计算scale_x和scale_y（手动记录后调用）
        原理：scale_x = (右小地图X - 左小地图X) / (右屏幕X - 左屏幕X)
              scale_y = (上端点小地图Y - 左端点小地图Y) / (左端点屏幕Y - 上端点屏幕Y)
        记录格式：左/右端点=(屏幕X, 屏幕Y, 小地图X, 小地图Y)，上端点=(屏幕Y, 小地图Y)
        兼容旧格式：(屏幕X, 小地图X, 小地图Y)没有屏幕Y时跳过Y校准
        手动记录直接覆盖（100%权重）"""
        left_pt = getattr(self, '_calib_left_pt', None)
        right_pt = getattr(self, '_calib_right_pt', None)
        top_pt = getattr(self, '_calib_top_pt', None)
        # scale_x校准
        if left_pt and right_pt and right_pt[0] > left_pt[0]:
            dx_scr = right_pt[0] - left_pt[0]   # 屏幕X距离
            dx_map = right_pt[2] - left_pt[2] if len(left_pt) >= 4 else right_pt[1] - left_pt[1]  # 小地图X距离
            if dx_map > 0 and dx_scr > 0:
                scale_x = dx_map / dx_scr
                self._calibrated_scale_x = scale_x  # 手动记录直接覆盖（100%权重）
                self._map_screen_scale = scale_x
                # 清晰显示：屏幕距离、小地图距离、倍率
                self._add_log("X校准: 屏幕距离=%dpx, 小地图距离=%dpx, 倍率=%.4f" % (dx_scr, dx_map, scale_x))
        # scale_y校准：上端点 + 左端点（Y下端点）
        if top_pt and left_pt and len(left_pt) >= 4:
            dy_scr = left_pt[1] - top_pt[0]   # 屏幕Y距离（下端屏幕Y - 上端屏幕Y）
            dy_map = left_pt[3] - top_pt[1]   # 小地图Y距离（下端小地图Y - 上端小地图Y）
            if dy_scr > 10 and dy_map > 1:
                scale_y = dy_map / dy_scr
                self._calibrated_scale_y = scale_y
                # 清晰显示：屏幕距离、小地图距离、倍率
                self._add_log("Y校准: 屏幕距离=%dpx, 小地图距离=%dpx, 倍率=%.4f" % (dy_scr, dy_map, scale_y))

    def _get_monster_map_pos_verified(self, screen_x, screen_y):
        """【模块B】怪物屏幕坐标转小地图坐标（人物锚点+相对偏移，Y用同平台绿线校准）
        原理：
          X = 人物小地图X + (怪屏幕X - 人物屏幕X) * scale_x
          Y = 人物小地图Y + (怪屏幕Y - 人物屏幕Y) * scale_y
          绿线校准：只在怪物Y和人物Y相差<30px（同平台范围）时，才找X最接近的绿线点修正Y
          - 高处/低处平台的怪（Y差>30px）不强制拉到绿线上，保留线性转换Y
        参数：screen_x, screen_y = 怪物屏幕坐标（YOLO检测框的中心点X，底部Y）
        返回：(map_x, map_y) 小地图坐标；人物位置未知时返回None"""
        # 方法A：以人物为参考点线性转换
        pos_a = self._screen_to_map(screen_x, screen_y)
        if pos_a is None:
            return None
        map_x, map_y = pos_a
        # 绿线Y校准：只校准和人物Y相差<30px的怪（同平台），避免高处怪被拉到低层
        player_map_y = self._player_map_pos[1] if self._player_map_pos else None
        if player_map_y is not None and abs(map_y - player_map_y) < 30:
            best_y = None
            best_dx = 999
            for p in self.platforms:
                pts = self._platform_points(p)
                for (px, py) in pts:
                    dx = abs(px - map_x)
                    dy = abs(py - map_y)
                    # X最接近且Y偏差<15px（怪站在这个平台上）
                    if dx < best_dx and dy < 15:
                        best_dx = dx
                        best_y = py
            if best_y is not None:
                map_y = best_y
        return (map_x, map_y)

    def _get_monster_platform(self, screen_x, screen_y):
        """【模块B】判定怪在哪个平台上（用手动录制平台判定）
        用途：找怪时判断怪和人物是否同平台，还是在上面/下面的平台
        原理：
          1. 怪屏幕坐标(YOLO) → 估算小地图坐标(_screen_to_map)
          2. 用手动录制的平台判定：距离≤15px = 在该平台上
        参数：screen_x, screen_y = 怪在游戏画面中的屏幕坐标
        返回：平台对象dict；找不到返回None"""
        map_pos = self._screen_to_map(screen_x, screen_y)
        if map_pos is None:
            return None
        mx, my = map_pos
        # 用手动录制的平台判定
        if not self.platforms:
            return None
        best_pf = None
        best_dist = 999.0
        for pf in self.platforms:
            pts = self._platform_points(pf)
            d = self._point_to_polyline_dist(mx, my, pts)
            if d < best_dist:
                best_dist = d
                best_pf = pf
        if best_pf and best_dist <= 15:
            return best_pf
        return None

    def _get_slope_direction(self, screen_x, screen_y):
        """【模块B】判定怪相对于人物是上坡、下坡还是平地
        用途：斜坡打怪时，上坡需要跳着打，下坡直接走过去打
        原理：
          1. 先判定怪在哪个平台(_get_monster_platform)
          2. 怪和人物同平台：比较怪估算的小地图Y 和 人物在绿线上的Y
             - 怪Y < 人物Y → 上坡（怪在更高处）
             - 怪Y > 人物Y → 下坡（怪在更低处）
             - 相差≤5 → 平地
          3. 怪在不同平台：直接判定上平台/下平台
        参数：screen_x, screen_y = 怪在游戏画面中的屏幕坐标
        返回：'up'=上坡/上平台, 'down'=下坡/下平台, 'flat'=平地, None=未知"""
        if not self._player_map_pos:
            return None
        # 步骤1：怪在哪个平台
        monster_pf = self._get_monster_platform(screen_x, screen_y)
        # 步骤2：人物在哪个平台
        player_pf = self._get_current_platform()
        if monster_pf is None or player_pf is None:
            return None
        # 步骤3：同平台 → 比较Y判断上坡/下坡
        if monster_pf.get('id') == player_pf.get('id'):
            map_pos = self._screen_to_map(screen_x, screen_y)
            if map_pos is None:
                return None
            monster_y = map_pos[1]  # 怪估算的小地图Y
            player_y = self._player_map_pos[1]  # 人物小地图Y
            y_diff = monster_y - player_y
            if y_diff < -5:
                return 'up'    # 怪Y更小 = 怪在更高处 = 上坡
            elif y_diff > 5:
                return 'down'  # 怪Y更大 = 怪在更低处 = 下坡
            else:
                return 'flat'  # Y相近 = 平地
        else:
            # 步骤4：不同平台 → 比较平台Y判断上/下平台
            m_pts = self._platform_points(monster_pf)
            p_pts = self._platform_points(player_pf)
            m_avg_y = sum(p[1] for p in m_pts) / len(m_pts)
            p_avg_y = sum(p[1] for p in p_pts) / len(p_pts)
            if m_avg_y < p_avg_y:
                return 'up'    # 怪所在平台Y更小 = 上面的平台
            else:
                return 'down'  # 怪所在平台Y更大 = 下面的平台

    def _find_nearest_monster_all(self):
        """【模块B】综合找最近的怪（包括同平台和上下平台，考虑平台切换惩罚）
        用途：同平台没怪时，找最近的怪，包括需要爬梯子/跳下去的怪
        原理：
          1. 对每个检测到的怪，计算"综合距离" = 屏幕距离 + 平台切换惩罚
          2. 同平台怪：惩罚=0（直接走过去打）
          3. 上平台怪：惩罚≈爬梯子时间(约2秒=2000距离单位)
          4. 下平台怪：惩罚≈跳下去时间(约0.5秒=500距离单位)
          5. 返回综合距离最小的怪
        返回：(screen_x, screen_y, 综合距离, 平台对象, 方向)；没怪返回None"""
        if not self._monsters or not self._player_screen_pos:
            return None
        px, py = self._player_screen_pos
        best = None
        best_cost = 99999
        for (x1, y1, x2, y2, score) in self._monsters:
            cx = (x1 + x2) // 2  # 怪中心X
            cy = y2               # 怪脚底Y
            screen_dist = int(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
            # 判定怪在哪个平台
            monster_pf = self._get_monster_platform(cx, cy)
            player_pf = self._get_current_platform()
            # 平台切换惩罚
            if monster_pf and player_pf and monster_pf.get('id') != player_pf.get('id'):
                direction = self._get_slope_direction(cx, cy)
                if direction == 'up':
                    penalty = 2000  # 上平台需要爬梯子，惩罚大
                elif direction == 'down':
                    penalty = 500   # 下平台跳下去，惩罚小
                else:
                    penalty = 1000
            else:
                direction = self._get_slope_direction(cx, cy) or 'flat'
                penalty = 0       # 同平台无惩罚
            cost = screen_dist + penalty
            if cost < best_cost:
                best_cost = cost
                best = (cx, cy, cost, monster_pf, direction)
        return best

    # ========================================================================
    # 【模块C】绿线波动检测：只要绿线不是直的，有波动的地方就要跳着跑
    # ========================================================================

    def _check_platform_slope_ahead(self, move_dir, look_ahead=50):
        """【模块C】检测人物前方绿线是否有波动（断层/上坡/下坡），有则需要跳着跑
        用途：只要绿线不是直的，有波动的地方（断层、上坡、下坡），就要跳着跑过去
        原理：
          1. 获取人物当前平台的绿线折点
          2. 找到人物在绿线上的最近点
          3. 根据移动方向，取前方look_ahead距离(小地图px)内的绿线点
          4. 计算这些点的Y变化范围(maxY - minY)
          5. Y变化>阈值(10px) = 有波动，需要跳
        参数：move_dir='left'/'right'，look_ahead=前方检测距离(小地图px，默认50)
        返回：True=前方有波动需要跳，False=平直绿线不需要跳"""
        current_pf = self._get_current_platform()
        if not current_pf or not self._player_map_pos:
            return False
        pts = self._platform_points(current_pf)
        if len(pts) < 2:
            return False
        ppx, ppy = self._player_map_pos
        # 步骤1：找到人物在绿线上的最近点索引
        best_idx = 0
        best_dist = 999.0
        for i, (x, y) in enumerate(pts):
            d = ((x - ppx) ** 2 + (y - ppy) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_idx = i
        # 步骤2：根据移动方向，取前方look_ahead距离内的绿线点
        ahead_pts = []
        if move_dir == 'right':
            # 向右移动：取索引增大方向的点（X增大）
            for i in range(best_idx, len(pts)):
                if pts[i][0] - ppx <= look_ahead:
                    ahead_pts.append(pts[i])
                else:
                    break
        else:  # left
            # 向左移动：取索引减小方向的点（X减小）
            for i in range(best_idx, -1, -1):
                if ppx - pts[i][0] <= look_ahead:
                    ahead_pts.append(pts[i])
                else:
                    break
        if len(ahead_pts) < 2:
            return False
        # 步骤3：计算前方绿线点的Y变化范围
        ys = [p[1] for p in ahead_pts]
        y_range = max(ys) - min(ys)
        # Y变化>10px判定为有波动（断层/上坡/下坡），需要跳着跑
        return y_range > 10

    def extract_platform(self, points):
        """录制的路径点抽稀后保存为折线（曲线），一条录制=一个平台。"""
        if len(points) < 2:
            return []
        # 按间距抽稀（至少2小地图px一个点），保留曲线形状
        simplified = [points[0]]
        for p in points[1:]:
            last = simplified[-1]
            dist = ((p[0] - last[0]) ** 2 + (p[1] - last[1]) ** 2) ** 0.5
            if dist >= 2:
                simplified.append(p)
        if simplified[-1] != points[-1]:
            simplified.append(points[-1])
        return [{
            "id": len(self.platforms),
            "points": [[float(x), float(y)] for x, y in simplified]
        }]

    def extract_ladder(self, points):
        if len(points) < 2:
            _debug_log("[梯录B] extract失败：点数=%d < 2" % len(points))  # 调试日志：点数不足
            return []
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        result = [{
            "id": len(self.ladders),
            "x": float(sorted(xs)[len(xs) // 2]),
            "y_top": float(min(ys)),
            "y_bottom": float(max(ys))
        }]
        # 超详细日志：确认点收集是否完整(第一个点/最后一个点/Y的min-max/点数)
        _debug_log("[梯录B] extract详细：点数=%d 首点=%s 末点=%s Ymin=%.1f Ymax=%.1f Yrange=%.1f x=%.1f" % (
            len(points), str(points[0]), str(points[-1]), min(ys), max(ys), max(ys)-min(ys), result[0]["x"]))
        _debug_log("[梯录B] extract成功：原始点数=%d x=%.1f y_top=%.1f y_bottom=%.1f ladders总数将=%d" % (
            len(points), result[0]["x"], result[0]["y_top"], result[0]["y_bottom"], len(self.ladders) + len(result)))  # 调试日志：验证extract_ladder是否返回非空结果
        return result

    def _check_hotkeys(self):
        """GetAsyncKeyState 轮询，按下瞬间触发一次"""
        for vk in [VK_F4, VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F11, VK_F12]:
            pressed = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if pressed and not self._key_state[vk]:
                _debug_log("[热键] 检测到按键 VK=0x%X" % vk)
                self._handle_hotkey(vk)
            self._key_state[vk] = pressed

    def _handle_hotkey(self, vk):
        if vk == VK_F5:
            if self.recording_ladder:
                print("Stop ladder first (F6)")
            elif self.recording_platform:
                np_ = self.extract_platform(self.platform_points)
                _debug_log("[录制B] extract结果=%s 原始点数=%d platforms总数将=%d" % (str(np_), len(self.platform_points), len(self.platforms) + len(np_)))  # 调试日志：验证extract_platform是否返回非空结果
                if np_:
                    self.platforms.extend(np_)
                    print("Extracted", len(np_), "platforms,", len(self.platform_points), "points")
                else:
                    print("No platform extracted,", len(self.platform_points), "points")
                self.platform_points = []
                self.recording_platform = False
            else:
                self.recording_platform = True
                self.platform_points = []
                print("Platform recording started...")
        elif vk == VK_F6:
            if self.recording_platform:
                print("Stop platform first (F5)")
            elif self.recording_ladder:
                nl = self.extract_ladder(self.ladder_points)
                if nl:
                    # 梯子覆盖规则：同一梯子=X基本一样(差值<2) 且 Y范围有交叠，新录制覆盖旧记录(不管保没保存)；X差≥2 或 Y范围完全不重叠=不同梯子不覆盖
                    new_ld = nl[0]
                    replaced = False
                    for i, old in enumerate(self.ladders):
                        y_overlap = not (new_ld["y_bottom"] < old["y_top"] or new_ld["y_top"] > old["y_bottom"])  # Y范围有交叠
                        if abs(old["x"] - new_ld["x"]) < 2 and y_overlap:
                            new_ld["id"] = old["id"]  # 保持原编号
                            self.ladders[i] = new_ld
                            replaced = True
                            _debug_log("[梯录D] 覆盖旧梯子 id=%s 旧x=%.1f 新x=%.1f y_top=%.1f y_bottom=%.1f" % (old["id"], old["x"], new_ld["x"], new_ld["y_top"], new_ld["y_bottom"]))
                            break
                    if not replaced:
                        self.ladders.append(new_ld)
                    print("Extracted 1 ladder,", len(self.ladder_points), "points,", "覆盖旧梯" if replaced else "新增", "ladders总数=", len(self.ladders))
                else:
                    print("No ladder extracted,", len(self.ladder_points), "points")
                self.ladder_points = []
                self.recording_ladder = False
            else:
                self.recording_ladder = True
                self.ladder_points = []
                print("Ladder recording started...")
        elif vk == VK_F7:
            self.platform_points = []
            self.ladder_points = []
            self.platforms = []
            self.ladders = []
            print("Cleared all (points + saved platforms/ladders)")
        elif vk == VK_F8:
            self._save()
        elif vk == VK_F9:
            print("Manual select triggered (F9)")
            self.manual_select_region()
        elif vk == VK_F10:
            if self.hwnd is None:
                print("[启动] 未绑定游戏窗口，请先绑定")
                self._add_log("未绑定窗口，无法启动")
            else:
                self._running = True
                print("[启动] 脚本已启动 (F10)")
                self._add_log("脚本已启动 F10")
                _debug_log("[启动] F10 已触发, _running=True, hwnd=%s" % self.hwnd)
        elif vk == VK_F11:
            print("[热键] 倍率校准 (F11)")
            self._start_auto_calibration()
        elif vk == VK_F12:
            if self._running or self._random_running:
                self._running = False
                self._release_combat_move()  # 释放战斗中持续按住的方向键
                self._release_all_keys()      # 释放所有按键(含移动)，防止停止后还动/还打
                self._release_attack_key()    # 松开攻击键
                self._combat_move_dir = None
                self._combat_active = False
                self._combat_locked_target = None
                self._stop_detection_thread()  # 停止后台检测线程
                if self._random_running:
                    self._release_all_keys()
                    self._reset_climb()
                    self._random_running = False
                    self._random_state = "idle"
                if self._monster_overlay_running:
                    self._stop_monster_overlay()
                print("[停止] 脚本已停止 (F12)")
                self._add_log("脚本已停止 F12")

    def _on_mouse(self, event, x, y, flags, param):
        """鼠标点击回调：标签页切换 + 路线页按钮"""
        # 松开按钮：清除按下状态
        if event == cv2.EVENT_LBUTTONUP:
            self._pressed_btn = None
        if event == cv2.EVENT_LBUTTONDOWN:
            _debug_log("[鼠标] 点击 tab=%s pos=(%d,%d)" % (self._current_tab, x, y))
        # 1. 顶部标签页切换
        if event == cv2.EVENT_LBUTTONDOWN:
            for tab, (tx, ty, tw, th) in self._tab_areas.items():
                if tx <= x < tx + tw and ty <= y < ty + th:
                    if tab != self._current_tab:
                        self._current_tab = tab
                        self._ui_bg = self._ui_bgs[tab]
                        self._dropdown = None
                        if self._focused_field is not None:
                            self._save_input_config()
                            self._focused_field = None
                        print("[标签页] 切换到:", tab)
                    return

        if self._current_tab == "fight":
            # 弹窗最上层优先（技能Y范围 / 寻怪范围 / 瞬移设置）
            if self._show_y_dialog and self._handle_y_dialog_event(event, x, y):
                return
            if self._show_search_dialog and self._handle_search_dialog_event(event, x, y):
                return
            if self._show_tp_dialog and self._handle_tp_dialog_event(event, x, y):
                return
            if event == cv2.EVENT_LBUTTONDOWN:
                bx, by, bw, bh = BTN_Y_RANGE
                if bx <= x < bx+bw and by <= y < by+bh:
                    self._pressed_btn = BTN_Y_RANGE  # 第3位：技能Y范围
                    self._open_y_range_dialog()
                    return
                sx, sy, sw, sh = BTN_SEARCH_RANGE
                if sx <= x < sx+sw and sy <= y < sy+sh:
                    self._pressed_btn = BTN_SEARCH_RANGE  # 第2位：寻怪范围
                    self._open_search_range_dialog()
                    return
                tx, ty, tw, th = BTN_TP_SETTING
                if tx <= x < tx+tw and ty <= y < ty+th:
                    self._pressed_btn = BTN_TP_SETTING
                    self._open_tp_dialog()
                    return
                self._handle_input_mouse(x, y)
            return
        if self._current_tab == "potion":
            if event == cv2.EVENT_LBUTTONDOWN:
                self._handle_input_mouse(x, y)
            return

        if self._current_tab != "route":
            return

        # === 倍率差弹窗点击检测（优先检测，因为弹窗在最上层）===
        if self._show_scale_dialog and event == cv2.EVENT_LBUTTONDOWN:
            # 1. 优先检测右上角关闭按钮X（避免被标题栏拖拽覆盖）
            cx, cy, cw, ch = self._dlg_scale_close_btn
            if cx <= x < cx+cw and cy <= y < cy+ch:
                self._show_scale_dialog = False
                # 关闭时恢复原始值（不保存）
                if "scale_x_offset" in self._scale_dialog_backup:
                    self._field_values["scale_x_offset"] = self._scale_dialog_backup["scale_x_offset"]
                if "scale_y_offset" in self._scale_dialog_backup:
                    self._field_values["scale_y_offset"] = self._scale_dialog_backup["scale_y_offset"]
                self._focused_field = None
                print("[倍率差弹窗] 关闭（不保存）")
                return
            # 2. 检测标题栏拖拽（顶部50像素区域）
            dlg_x = self._scale_dialog_pos[0]
            dlg_y = self._scale_dialog_pos[1]
            dlg_w, dlg_h = 320, 220
            if dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+50:
                self._scale_dialog_dragging = True
                self._scale_dialog_drag_offset = [x - dlg_x, y - dlg_y]
                print("[倍率差弹窗] 开始拖拽")
                return
            # 3. 检测X偏差输入框（点击整个输入框都能聚焦，不只是边框）
            sx_x, sx_y, sx_w, sx_h = self._dlg_scale_x_input
            if sx_x <= x < sx_x+sx_w and sx_y <= y < sx_y+sx_h:
                self._focused_field = "scale_x_offset"
                self._prev_num_states = set()  # 重置按键状态，避免旧状态残留导致新键被忽略
                self._num_field_replace = True
                self._last_input_change = time.time() * 1000  # 点击聚焦也算操作，重置5秒失焦计时器
                print("[倍率差弹窗] 聚焦X偏差输入框")
                return
            # 4. 检测Y偏差输入框
            sy_x, sy_y, sy_w, sy_h = self._dlg_scale_y_input
            if sy_x <= x < sy_x+sy_w and sy_y <= y < sy_y+sy_h:
                self._focused_field = "scale_y_offset"
                self._prev_num_states = set()  # 重置按键状态，避免旧状态残留导致新键被忽略
                self._num_field_replace = True
                self._last_input_change = time.time() * 1000  # 点击聚焦也算操作，重置5秒失焦计时器
                print("[倍率差弹窗] 聚焦Y偏差输入框")
                return
            # 5. 检测确认按钮
            ok_x, ok_y, ok_w, ok_h = self._dlg_scale_ok_btn
            if ok_x <= x < ok_x+ok_w and ok_y <= y < ok_y+ok_h:
                # 确认保存
                self._save_input_config()
                self._show_scale_dialog = False
                self._focused_field = None
                print("[倍率差弹窗] 确认保存")
                return
            # 6. 检测取消按钮
            cancel_x, cancel_y, cancel_w, cancel_h = self._dlg_scale_cancel_btn
            if cancel_x <= x < cancel_x+cancel_w and cancel_y <= y < cancel_y+cancel_h:
                # 取消，恢复原始值
                if "scale_x_offset" in self._scale_dialog_backup:
                    self._field_values["scale_x_offset"] = self._scale_dialog_backup["scale_x_offset"]
                if "scale_y_offset" in self._scale_dialog_backup:
                    self._field_values["scale_y_offset"] = self._scale_dialog_backup["scale_y_offset"]
                self._show_scale_dialog = False
                self._focused_field = None
                print("[倍率差弹窗] 取消（不保存）")
                return
            # 7. 点击弹窗外部，关闭弹窗（不保存）
            if not (dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+dlg_h):
                if "scale_x_offset" in self._scale_dialog_backup:
                    self._field_values["scale_x_offset"] = self._scale_dialog_backup["scale_x_offset"]
                if "scale_y_offset" in self._scale_dialog_backup:
                    self._field_values["scale_y_offset"] = self._scale_dialog_backup["scale_y_offset"]
                self._show_scale_dialog = False
                self._focused_field = None
                print("[倍率差弹窗] 点击外部关闭（不保存）")
                return
        # 弹窗拖拽中（鼠标移动时更新位置）
        if self._show_scale_dialog and self._scale_dialog_dragging and event == cv2.EVENT_MOUSEMOVE:
            self._scale_dialog_pos[0] = x - self._scale_dialog_drag_offset[0]
            self._scale_dialog_pos[1] = y - self._scale_dialog_drag_offset[1]
            # 边界保护，不让弹窗拖出屏幕
            self._scale_dialog_pos[0] = max(0, min(UI_W - 320, self._scale_dialog_pos[0]))
            self._scale_dialog_pos[1] = max(0, min(UI_H - 220, self._scale_dialog_pos[1]))
            return
        # 松开鼠标时停止拖拽
        if self._scale_dialog_dragging and event == cv2.EVENT_LBUTTONUP:
            self._scale_dialog_dragging = False
            print("[倍率差弹窗] 停止拖拽")
            return

        # 路线页输入框（X/Y偏移）聚焦处理
        if event == cv2.EVENT_LBUTTONDOWN:
            self._handle_input_mouse(x, y)

        # 人物特征下拉面板（向下弹出）
        dd_top = BTN_CHAR[1] + BTN_CHAR[3]
        dd_bottom = dd_top + CHAR_DD_VISIBLE * CHAR_DD_ITEM_H
        dd_main_x2 = CHAR_DD_X + CHAR_DD_W
        dd_scroll_x2 = dd_main_x2 + CHAR_DD_SCROLL_W
        in_dd_main = (dd_top <= y < dd_bottom and CHAR_DD_X <= x < dd_main_x2)
        in_dd_scroll = (dd_top <= y < dd_bottom and dd_main_x2 <= x < dd_scroll_x2)
        in_dd = in_dd_main or in_dd_scroll
        on_char_btn = (BTN_CHAR[1] <= y < BTN_CHAR[1] + BTN_CHAR[3] and BTN_CHAR[0] <= x < BTN_CHAR[0] + BTN_CHAR[2])

        if self._char_dropdown:
            # 右键：删除单个特征
            if event == cv2.EVENT_RBUTTONDOWN and in_dd_main:
                row = (y - dd_top) // CHAR_DD_ITEM_H
                if row >= 1:  # row0是删除全部
                    slot_idx = self._char_scroll + (row - 1)
                    if 0 <= slot_idx < len(self._char_templates):
                        self._delete_char_template(slot_idx)
                return
            # 左键
            if event == cv2.EVENT_LBUTTONDOWN:
                if in_dd_main:
                    row = (y - dd_top) // CHAR_DD_ITEM_H
                    if row == 0:
                        # 删除全部
                        self._clear_character_features()
                        self._char_scroll = 0
                    else:
                        slot_idx = self._char_scroll + (row - 1)
                        if 0 <= slot_idx < len(self._char_templates):
                            self._char_dropdown = False
                            print("[鼠标] 选中人物特征#%d" % self._char_templates[slot_idx]["id"])
                        elif slot_idx < CHAR_DD_ITEMS:
                            self._char_dropdown = False
                            self._capture_character_feature()
                    return
                elif in_dd_scroll:
                    # 翻页箭头
                    mid_y = dd_top + (dd_bottom - dd_top) // 2
                    if y < mid_y:
                        self._char_scroll = max(0, self._char_scroll - 1)
                    else:
                        max_scroll = CHAR_DD_ITEMS - CHAR_DD_FEAT_PER_PAGE
                        self._char_scroll = min(max_scroll, self._char_scroll + 1)
                    return
                elif not on_char_btn:
                    # 点击菜单外收起
                    self._char_dropdown = False
                    return

        # 日志滚动条：拖拽+滚轮（双日志视图，作用于当前tab）
        sb_x = UI_LOG_X + UI_LOG_W - 10
        sb_y = UI_LOG_Y + 22
        sb_w = 8
        sb_h = UI_LOG_H - 24
        line_h = 16
        _lch = UI_LOG_H - (UI_LOG_CONTENT_Y - UI_LOG_Y) - 4   # 与绘制块同一内容高度
        max_lines = max(1, _lch // line_h)
        _is_beh = (self._log_view == 'behavior')
        _entries = self._behavior_logs if _is_beh else self._runtime_logs
        # 滚动单位=折行后的渲染行，和绘制处保持一致(否则长消息折行后滚动条对不齐)
        _avail_w = UI_LOG_W - 4 - 8 - 2 - 6
        total = len(self._log_wrap_lines(_entries, _avail_w))
        max_scroll = max(0, total - max_lines)

        def _get_scr():
            return self._behavior_scroll if _is_beh else self._log_scroll

        def _set_scr(v):
            if _is_beh:
                self._behavior_scroll = v
            else:
                self._log_scroll = v

        def _clamp_scroll(v):
            return max(0, min(max_scroll, v))

        # 点标题栏【打怪】【行为】tab切换日志界面
        if event == cv2.EVENT_LBUTTONDOWN:
            def _tab_hit(r):
                return r is not None and r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]
            if _tab_hit(self._log_tab_combat):
                self._log_view = 'combat'
                return
            if _tab_hit(self._log_tab_behavior):
                self._log_view = 'behavior'
                return

        # 鼠标滚轮（在日志区域内滚动3行）
        if event == cv2.EVENT_MOUSEWHEEL:
            if UI_LOG_X <= x < UI_LOG_X + UI_LOG_W and UI_LOG_Y <= y < UI_LOG_Y + UI_LOG_H:
                _step = -3 if flags > 0 else 3  # 向上滚看更新、向下滚看更旧
                _set_scr(_clamp_scroll(_get_scr() + _step))
                return

        # 点击滚动条：开始拖拽
        if event == cv2.EVENT_LBUTTONDOWN:
            if sb_x <= x < sb_x + sb_w and sb_y <= y < sb_y + sb_h:
                self._dragging_log_scroll = True
                # 直接跳到点击位置
                if max_scroll > 0 and sb_h > 0:
                    rel = (y - sb_y) / sb_h
                    _set_scr(_clamp_scroll(int(rel * max_scroll)))
                return

        # 拖拽滚动条
        if event == cv2.EVENT_MOUSEMOVE and getattr(self, '_dragging_log_scroll', False):
            if max_scroll > 0 and sb_h > 0:
                rel = max(0.0, min(1.0, (y - sb_y) / sb_h))
                _set_scr(_clamp_scroll(int(rel * max_scroll)))
            return

        # 松开拖拽
        if event == cv2.EVENT_LBUTTONUP and getattr(self, '_dragging_log_scroll', False):
            self._dragging_log_scroll = False
            return

        # 2. 手动框选模式（小地图合成区域内拖拽）
        if self._selecting:
            mx = int((x - UI_MAP_X) / UI_MAP_SCALE)
            my = int((y - UI_MAP_Y) / UI_MAP_SCALE)
            if my < 22:
                if event == cv2.EVENT_LBUTTONDOWN and mx < 48:
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
            elif my >= MAP_H:
                if event == cv2.EVENT_LBUTTONDOWN:
                    self._selecting = False
                    self._select_rect = None
                    self._select_dragging = False
                    if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
                        self._start_random()
            else:
                if event == cv2.EVENT_LBUTTONDOWN:
                    self._select_dragging = True
                    self._select_rect = (mx, my, mx, my)
                elif event == cv2.EVENT_MOUSEMOVE and self._select_dragging:
                    x1, y1, _, _ = self._select_rect
                    self._select_rect = (x1, y1, mx, my)
                elif event == cv2.EVENT_LBUTTONUP:
                    self._select_dragging = False
                    x1, y1, _, _ = self._select_rect
                    self._select_rect = (x1, y1, mx, my)
                    self._confirm_select()
                return

        if event not in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_RBUTTONDOWN):
            return

        # 右键：已绑窗口下拉列表项解绑（向上弹出，最多10项）
        if event == cv2.EVENT_RBUTTONDOWN:
            if self._bound_dropdown and self._bound_windows:
                item_h = 20
                show_count = min(len(self._bound_windows), 10)
                menu_y2 = UI_BOUND_Y  # 菜单底部在按钮顶部
                menu_y1 = menu_y2 - show_count * item_h
                if UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and menu_y1 <= y < menu_y2:
                    idx = (y - menu_y1) // item_h
                    if 0 <= idx < show_count:
                        w = self._bound_windows.pop(idx)
                        self._add_log("已解绑: %s" % w["title"][:20])
                        print("[已绑窗口] 解绑:", w["title"])
                        # 如果解绑的是当前活动窗口，自动切换到列表中的下一个
                        if self.hwnd == w["hwnd"]:
                            if self._bound_windows:
                                next_w = self._bound_windows[0]
                                self.hwnd = next_w["hwnd"]
                                self._hwnd_auto = False  # 下拉手选窗口=手动模式,看门狗不自动抢
                                self._update_window_rect()
                                self._detect_minimap()
                                self._add_log("切换到: %s" % next_w["title"][:20])
                            else:
                                self.hwnd = None
                                self._hwnd_auto = False
                                self._auto_refresh = False
                                self._stop_random()
                        if not self._bound_windows:
                            self._bound_dropdown = False
                    return
            # 注意：这里不能return，否则其他区域的右键点击（如坐标测量）会被拦截

        # 已绑窗口下拉菜单：左键点击其他地方则关闭
        if self._bound_dropdown and event == cv2.EVENT_LBUTTONDOWN:
            in_button = UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and UI_BOUND_Y <= y < UI_BOUND_Y + UI_BOUND_H
            in_menu = False
            if self._bound_windows:
                item_h = 20
                show_count = min(len(self._bound_windows), 10)
                menu_y2 = UI_BOUND_Y
                menu_y1 = menu_y2 - show_count * item_h
                in_menu = UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and menu_y1 <= y < menu_y2
            if not in_button and not in_menu:
                self._bound_dropdown = False

        # 3. 下拉菜单优先（向下弹出，在小地图检测之前）
        if self._dropdown is not None:
            dd_btn_map = {"mode": BTN_MODE}
            bx, by, bw, bh = dd_btn_map[self._dropdown]
            items = self._dropdown_items()
            n = len(items)
            menu_h = n * DROPDOWN_ITEM_H
            menu_y1 = by + bh
            if bx <= x < bx + bw and menu_y1 <= y < menu_y1 + menu_h:
                item_idx = (y - menu_y1) // DROPDOWN_ITEM_H
                if 0 <= item_idx < n:
                    self._handle_dropdown_item(self._dropdown, item_idx)
                self._dropdown = None
                return
            if bx <= x < bx + bw and by <= y < by + bh:
                self._dropdown = None
                return
            self._dropdown = None

        # 4. 工具栏（小地图上方，帧坐标）
        def _in(rect, x, y):
            return rect[0] <= x < rect[0]+rect[2] and rect[1] <= y < rect[1]+rect[3]

        # 按钮按下特效：命中任意按钮时记录按下状态+闪光
        _EFFECT_BTNS = [BTN_REFRESH, BTN_MANUAL, BTN_PLATFORM, BTN_LADDER, BTN_SAVE, BTN_PLAN,
                        BTN_PLATFORM_CLR, BTN_LADDER_CLR, BTN_MODE, BTN_PLAN_CLR,
                        BTN_RUN, BTN_STOP, BTN_CHAR, BTN_MONSTER, BTN_MONSTER_FEATURE,
                        BTN_CALIB_AUTO, BTN_CALIB_Y]  # X/Y倍率按钮也用统一圆角按压特效
        for _br in _EFFECT_BTNS:
            if _in(_br, x, y):
                self._pressed_btn = _br
                break

        if _in(BTN_REFRESH, x, y):
            print("[鼠标] 刷新")
            self._auto_refresh = True
            self._detect_minimap()
            self.frame_count = 0
            self.last_player_pos = None
            return
        if _in(BTN_MANUAL, x, y):
            print("[鼠标] 手动框选")
            self.manual_select_region()
            return
        # BTN_PLAN_TOOLBAR 仅显示方案名/自动，不处理点击
        # 【模块B】自动校准按钮点击（同屏三点校准：基点+右800+上500）
        if _in(BTN_CALIB_AUTO, x, y):
            print("[鼠标] X倍率校准")
            self._calib_auto_pressed = 3  # 按下特效：显示3帧阴影
            self._start_auto_calibration('X')
            return
        if _in(BTN_CALIB_Y, x, y):
            print("[鼠标] Y倍率校准")
            self._calib_y_pressed = 3  # 按下特效：显示3帧阴影（与X倍率一致）
            self._start_auto_calibration('Y')
            return
        # 【倍率差弹窗】点击倍率差按钮打开弹窗
        if self._btn_scale_dialog and _in(self._btn_scale_dialog, x, y):
            print("[鼠标] 倍率差调整")
            self._show_scale_dialog = True
            # 打开弹窗时备份原始值（取消/关闭时恢复，确认才保存）
            self._scale_dialog_backup = {
                "scale_x_offset": self._field_values.get("scale_x_offset", "0"),
                "scale_y_offset": self._field_values.get("scale_y_offset", "0")
            }
            # 打开弹窗时立即计算所有控件位置（解决第一次打开弹窗点击没反应的问题）
            self._update_scale_dialog_positions()
            self._focused_field = None
            return

        # 5. 小地图区域内点击
        if UI_MAP_X <= x < UI_MAP_X + UI_MAP_W and UI_MAP_Y <= y < UI_MAP_Y + UI_MAP_H:
            # UI坐标转小地图原始分辨率坐标
            map_w = getattr(self, '_last_map_w', FIXED_W)
            map_h = getattr(self, '_last_map_h', MAP_H)
            map_x = int((x - UI_MAP_X) / UI_MAP_W * map_w)
            map_y = int((y - UI_MAP_Y) / UI_MAP_H * map_h)
            # 【梯删除·用户2026-09-09】右上角"梯删除"按钮：点一下进入待选(再点退出)
            if self._btn_ladder_delete and _in(self._btn_ladder_delete, x, y):
                self._ladder_delete_mode = not self._ladder_delete_mode
                print("[梯删除] %s" % ("进入：点梯子蓝线删除该条" if self._ladder_delete_mode else "退出删除"))
                return
            # 待选状态下点小地图=删除点中的梯子(点完保持待选,可连续删;再点按钮退出)
            if self._ladder_delete_mode:
                self._delete_ladder_at(map_x, map_y)
                return
            # 【模块B】台子选择按钮点击（小地图左上方）
            if self._btn_platform_selector and _in(self._btn_platform_selector, x, y):
                self._show_platform_selector = not self._show_platform_selector
                print("[台子选择] 打开面板" if self._show_platform_selector else "[台子选择] 关闭面板")
                return
            # 【模块B】台子选择面板中的点击
            if self._show_platform_selector and self.platforms:
                panel_x, panel_y = UI_MAP_X + 10, UI_MAP_Y + 30
                panel_w = UI_MAP_W - 20
                # 关闭按钮X
                if self._btn_platform_selector_close and _in(self._btn_platform_selector_close, x, y):
                    self._show_platform_selector = False
                    print("[台子选择] 关闭面板")
                    return
                # 平台编号点击（切换选中状态：点一下选择，再点一下取消）
                per_row = 5
                for idx, pf in enumerate(self.platforms):
                    pf_num = idx + 1
                    row = idx // per_row
                    col = idx % per_row
                    item_x = panel_x + 10 + col * 36
                    item_y = panel_y + 28 + row * 22
                    # 点击区域：圆形周围（比圆形稍大一点方便点击）
                    if item_x <= x < item_x + 18 and item_y <= y < item_y + 18:
                        if pf_num in self._selected_platforms:
                            self._selected_platforms.remove(pf_num)
                            print("[台子选择] 取消选择平台%d" % pf_num)
                        else:
                            self._selected_platforms.append(pf_num)
                            print("[台子选择] 选择平台%d" % pf_num)
                        return
                return
            return
        if _in(BTN_PLATFORM, x, y):
            print("[鼠标] 平台"); self._handle_hotkey(VK_F5); return
        if _in(BTN_LADDER, x, y):
            print("[鼠标] 梯子"); self._handle_hotkey(VK_F6); return
        if _in(BTN_SAVE, x, y):
            self._dropdown = None
            _debug_log("[鼠标] 点击保存按钮")
            try:
                self._open_save_window()
            except Exception as e:
                _debug_log("[方案窗口] 保存窗口异常: %s" % e)
            return
        if _in(BTN_PLAN, x, y):
            self._dropdown = None
            _debug_log("[鼠标] 点击方案按钮")
            try:
                self._open_plan_window()
            except Exception as e:
                _debug_log("[方案窗口] 方案窗口异常: %s" % e)
            return

        # 6. 第二排按钮（清除平台/清除梯子/模式▼/清除方案▼）
        if _in(BTN_PLATFORM_CLR, x, y):
            self._pop_platform(); return
        if _in(BTN_LADDER_CLR, x, y):
            self._pop_ladder(); return
        if _in(BTN_MODE, x, y):
            self._dropdown = "mode" if self._dropdown != "mode" else None; return
        if _in(BTN_PLAN_CLR, x, y):
            self._dropdown = None
            _debug_log("[鼠标] 点击清除按钮")
            try:
                self._open_clear_window()
            except Exception as e:
                _debug_log("[方案窗口] 清除窗口异常: %s" % e)
            return

        # 7. 运行/停止
        if _in(BTN_RUN, x, y):
            print("[鼠标] 运行")
            if self.route_mode == "随机":
                self._start_random()
            elif self.hwnd is not None:
                # 手动模式：有录制路线就启动路线跟随（用当前方案），没路线只启动战斗
                if self._route_has_file(self.current_route):
                    self._start_random()
                    self._add_log("路线%d已启动（手动）" % self.current_route)
                else:
                    self._running = True
                    self._add_log("战斗已启动（无路线）")
                    _debug_log("[运行] 手动模式无路线，仅启动战斗")
            else:
                self._add_log("未绑定窗口，无法启动")
                _debug_log("[运行] 未绑定窗口")
            return
        if _in(BTN_STOP, x, y):
            print("[鼠标] 停止")
            if self._random_running:
                self._stop_random()
            elif self._running:
                # 手动模式：只停战斗+蒙板
                self._running = False
                self._release_combat_move()  # 释放持续按住的方向键
                if self._monster_overlay_running:
                    self._stop_monster_overlay()
                self._add_log("战斗已停止")
                _debug_log("[停止] 手动模式已停止")
            return

        # 8. 子标签页（人物特征弹窗/怪物数据）
        if _in(BTN_CHAR, x, y):
            self._open_char_feature_window()
            print("[鼠标] 打开人物特征管理弹窗")
            return
        if _in(BTN_MONSTER, x, y):
            _debug_log("[鼠标] 点击怪物数据按钮")
            print("[鼠标] 怪物数据 - 选择YOLO模型"); self._select_yolo_model(); return

        # 怪物特征按钮（打开怪物特征管理弹窗）
        if _in(BTN_MONSTER_FEATURE, x, y):
            _debug_log("[鼠标] 点击怪物特征按钮")
            print("[鼠标] 怪物特征管理")
            self._open_monster_feature_window()
            return

        # 9. 可拖拽准星（按住拖到游戏窗口释放即绑定前台窗口）
        chx, chy = self._crosshair_pos
        half = self._crosshair_size // 2
        if chx - half <= x < chx + half and chy - half <= y < chy + half:
            print("[鼠标] 准星拖拽开始 - 拖到游戏窗口释放")
            self._drag_crosshair = True
            self._add_log("拖到游戏窗口释放")
            return

        # 10. 已绑窗口下拉按钮
        if UI_BOUND_X <= x < UI_BOUND_X + UI_BOUND_W and UI_BOUND_Y <= y < UI_BOUND_Y + UI_BOUND_H:
            self._bound_dropdown = not self._bound_dropdown
            print("[鼠标] 已绑窗口下拉:", "展开" if self._bound_dropdown else "收起")
            return


    def _putcn(self, frame, text, x, y, color=(255, 255, 255)):
        """用PIL中文字体画文本，位置与cv2.putText的基线(x,y)完全一致(anchor='ls')：
        不乱码、且不改动原位置（解决'方案名/倍率中文'乱码，避免乱动已排好的布局）。
        [CPU优化2026-09-07] 只对文字包围盒小ROI做BGR<->RGB转换(实测整画布2.87ms->小ROI0.13ms,快21倍)；
        原实现每画一个词都把整个461x900画布来回转色+全图拷贝，draw内十余处叠加成每帧约32ms的主循环大头。"""
        try:
            H, W = frame.shape[:2]
            bb = self._log_font.getbbox(text, anchor="ls")  # 相对基线锚点(x,y)的包围盒,上方为负
            pad = 2
            X0 = max(0, x + bb[0] - pad); Y0 = max(0, y + bb[1] - pad)
            X1 = min(W, x + bb[2] + pad); Y1 = min(H, y + bb[3] + pad)
            if X1 <= X0 or Y1 <= Y0:
                return
            roi = frame[Y0:Y1, X0:X1]
            _pil = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
            ImageDraw.Draw(_pil).text((x - X0, y - Y0), text, font=self._log_font,
                                      fill=(color[2], color[1], color[0]), anchor="ls")
            frame[Y0:Y1, X0:X1] = cv2.cvtColor(np.array(_pil), cv2.COLOR_RGB2BGR)
        except Exception:
            pass

    def _load_cn_font(self, size):
        """按字号加载中文字体（缓存）。字体优先级与_log_font一致：simhei→微软雅黑→simsun，
        保持'以前用过的字体就是 simhei'，不另换字体。"""
        if not hasattr(self, '_cn_font_cache'):
            self._cn_font_cache = {}
        if size not in self._cn_font_cache:
            _f = ImageFont.load_default()
            for _fp in ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/msyh.ttc",
                        "C:/Windows/Fonts/simsun.ttc", "simhei.ttf"):
                try:
                    _f = ImageFont.truetype(_fp, size)
                    break
                except Exception:
                    continue
            self._cn_font_cache[size] = _f
        return self._cn_font_cache[size]

    def _draw_cn_mixed(self, frame, text, x, y, scale, color=(255, 255, 255), thickness=1):
        """保留原cv2字号+原字体：把text拆成'中文/非中文'段，非中文(数字/字母)仍用cv2原字体原字号画，
        中文用中文字体(simhei)画，字号与cv2该scale等高，同基线(y)、同水平起笔、依次推进。
        用于'只中文换字体、数字字母保留原样'的乱码修复（不扁平化到固定13px）。"""
        _fv = cv2.FONT_HERSHEY_SIMPLEX
        _cn_size = int(round(round(cv2.getTextSize("A", _fv, scale, thickness)[0][1]) * 1.3))  # 统一字体大小(微软雅黑中文够大,和英文一致)
        _cn_font = self._load_cn_font(_cn_size)
        _meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        _is_cn = lambda c: '\u4e00' <= c <= '\u9fff' or c in '，。、；：？！（）【】《》“”'
        # 拆段：非中文/中文连续段
        _segs, _buf, _cur = [], "", False
        for _c in text:
            _cn = bool(_is_cn(_c))
            if _cn != _cur:
                if _buf:
                    _segs.append((_cur, _buf))
                _cur, _buf = _cn, _c
            else:
                _buf += _c
        if _buf:
            _segs.append((_cur, _buf))
        # 预计算每段起点（水平推进）
        _starts, _cx = [], x
        for _is_cn, _seg in _segs:
            _starts.append((_cx, _is_cn, _seg))
            if _is_cn:
                _cx += int(_meas.textbbox((0, 0), _seg, font=_cn_font)[2])
            else:
                _cx += cv2.getTextSize(_seg, _fv, scale, thickness)[0][0]
        # 全部用微软雅黑(_cn_font)画(中文+非中文统一，用户2026-9-6要统一微软雅黑)
        # [CPU优化2026-09-07] 只对整段文字包围盒小ROI转色(同_putcn，避免每处文字整画布461x900来回转)
        try:
            H, W = frame.shape[:2]
            _bb = _cn_font.getbbox(text, anchor="ls")  # 整串文字相对基线(x,y)的包围盒
            pad = max(2, thickness + 1)
            X0 = max(0, x + _bb[0] - pad); Y0 = max(0, y + _bb[1] - pad)
            X1 = min(W, x + _bb[2] + pad); Y1 = min(H, y + _bb[3] + pad)
            if X1 > X0 and Y1 > Y0:
                roi = frame[Y0:Y1, X0:X1]
                _pil = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
                _draw = ImageDraw.Draw(_pil)
                for _sx, _is_cn, _seg in _starts:
                    _draw.text((_sx - X0, y - Y0), _seg, font=_cn_font,
                               fill=(color[2], color[1], color[0]), anchor="ls")
                frame[Y0:Y1, X0:X1] = cv2.cvtColor(np.array(_pil), cv2.COLOR_RGB2BGR)
        except Exception:
            pass

    def draw(self, map_area, player_pos):
        _seg_t0 = time.time()
        frame = self._ui_bg.copy()
        if not hasattr(self, '_seg_sum'):
            self._seg_sum = {}
        self._seg_sum['bg'] = self._seg_sum.get('bg', 0) + time.time() - _seg_t0
        self._seg_tp = time.time()

        if self._current_tab in ("fight", "potion"):
            self._draw_input_fields(frame)
            if self._current_tab == "fight":
                self._draw_tp_setting_btn(frame)   # 第1位：瞬移设置按钮+按压变暗
                self._draw_search_range_btn(frame) # 第2位：寻怪范围按钮(替换原动作录制,原图不拉伸)+按压变暗
                self._draw_y_range_btn(frame)      # 第3位：技能Y范围按钮(原图不缩放)+按压变暗
                if self._show_tp_dialog:
                    self._draw_tp_dialog(frame)    # 瞬移设置弹窗(最上层)
                if self._show_y_dialog:
                    self._draw_y_dialog(frame)     # 技能Y范围弹窗(最上层)
                if self._show_search_dialog:
                    self._draw_search_dialog(frame)  # 寻怪范围弹窗(最上层)
            self._seg_sum['fight'] = self._seg_sum.get('fight', 0) + time.time() - self._seg_tp
            return frame

        if self._current_tab != "route":
            return frame

        self._seg_tp = time.time()  # [分段计时]小地图段起点
        # === 渲染小地图内容 ===
        display = map_area.copy()
        h, w = display.shape[:2]
        # 存储当前小地图原始尺寸，供鼠标拖动时坐标转换用
        self._last_map_w = w
        self._last_map_h = h
        # 【模块B】在小地图上画自动校准点（红点=基点小地图坐标，绿点=记录的绿点位置，蓝点=记录的蓝点位置）
        auto_base = getattr(self, '_auto_calib_base', None)
        auto_stage = getattr(self, '_auto_calib_stage', 0)
        auto_green = getattr(self, '_auto_calib_green_map', None)
        auto_blue = getattr(self, '_auto_calib_blue_map', None)
        # 圆点半径：按人物光点大小（原始小地图坐标下半径3，缩放后约7px，和游戏自带黄点差不多）
        CALIB_DOT_R = 1
        # 红点：基点的小地图坐标（第1次记录后显示，完成也保留）
        if auto_base and len(auto_base) >= 4:
            rx, ry = int(auto_base[2]), int(auto_base[3])
            if 0 <= rx < w and 0 <= ry < h:
                cv2.circle(display, (rx, ry), CALIB_DOT_R, (0, 0, 255), -1)  # 红色实心圆，基点位置
        # 绿点：记录绿点后显示（小地图绿点，完成也保留）
        if auto_green:
            gx, gy = int(auto_green[0]), int(auto_green[1])
            if 0 <= gx < w and 0 <= gy < h:
                cv2.circle(display, (gx, gy), CALIB_DOT_R, (0, 255, 0), -1)  # 绿色实心圆
        # 蓝点：记录蓝点后显示（小地图蓝点，完成也保留）
        if auto_blue:
            blx, bly = int(auto_blue[0]), int(auto_blue[1])
            if 0 <= blx < w and 0 <= bly < h:
                cv2.circle(display, (blx, bly), CALIB_DOT_R, (255, 0, 0), -1)  # 蓝色实心圆
        # 录制中的平台/梯子（红色）
        if self.recording_platform and len(self.platform_points) > 1:
            cv2.polylines(display, [np.array(self.platform_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        if self.recording_ladder and len(self.ladder_points) > 1:
            cv2.polylines(display, [np.array(self.ladder_points, np.int32).reshape(-1, 1, 2)], False, COLOR_RECORDING, 1)
        # 动态计算放大倍数，确保每个地图都能完整显示在UI窗口中，最大2倍
        max_scale_x = (UI_W - 40) / float(w) if w > 0 else 2.0  # 左右各留20像素边距
        max_scale_y = (UI_H - 200) / float(h) if h > 0 else 2.0  # 上下留足够空间给按钮和底部
        MAP_SCALE = min(2.0, max_scale_x, max_scale_y)  # 最大2倍，确保完整显示
        render_w = int(w * MAP_SCALE)  # 渲染宽度=原始宽度×动态放大倍数
        render_h = int(h * MAP_SCALE)  # 渲染高度=原始高度×动态放大倍数
        map_display = cv2.resize(display, (render_w, render_h), interpolation=cv2.INTER_NEAREST)  # 按原始比率动态放大，确保完整显示

        # 【模块B】在缩放后的map_display上画怪物紫色点（半径6，清晰可见）
        scale_x = render_w / w if w > 0 else 1.0  # X缩放比例=渲染宽度/原始宽度
        scale_y = render_h / h if h > 0 else 1.0  # Y缩放比例=渲染高度/原始高度
        if self._monsters and self._player_map_pos and self._player_screen_pos:
            COLOR_MONSTER_MAP = (255, 0, 255)  # 紫色BGR
            for (x1, y1, x2, y2, score) in self._monsters:
                mcx = (x1 + x2) // 2
                mcy = y2
                mpos = self._get_monster_map_pos_verified(mcx, mcy)
                if mpos:
                    dx_s = int(mpos[0] * scale_x)
                    dy_s = int(mpos[1] * scale_y)
                    if 0 <= dx_s < render_w and 0 <= dy_s < render_h:  # 边界检查用实际渲染尺寸
                        cv2.circle(map_display, (dx_s, dy_s), 6, COLOR_MONSTER_MAP, -1)

        # 平台编号（缩放后画，红色白描边）
        for p in self.platforms:
            pts = self._platform_points(p)
            if len(pts) >= 2:
                pf_id = p.get('id', 0) + 1
                xs = [pt[0] for pt in pts]
                ys = [pt[1] for pt in pts]
                cx = int(sum(xs) / len(xs) * scale_x)
                cy_top = int(min(ys) * scale_y) - 8
                if 0 <= cx < render_w and 0 <= cy_top < render_h:  # 边界检查用实际渲染尺寸
                    cv2.putText(map_display, str(pf_id), (cx, cy_top),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 3, cv2.LINE_AA)
                    cv2.putText(map_display, str(pf_id), (cx, cy_top),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)

        # 梯子蓝线（在编号上方，缩放后画，线宽2）
        for l in self.ladders:
            lx = int(l["x"] * scale_x)
            ly1 = int(l["y_top"] * scale_y)
            ly2 = int(l["y_bottom"] * scale_y)
            lx = max(0, min(lx, render_w - 1))  # X边界检查用实际渲染宽度
            ly1 = max(0, min(ly1, render_h - 1))  # Y1边界检查用实际渲染高度
            ly2 = max(0, min(ly2, render_h - 1))  # Y2边界检查用实际渲染高度
            cv2.line(map_display, (lx, ly1), (lx, ly2), COLOR_LADDER, 2)

        # 平台绿线（最后画，始终在最上层，缩放后画，线宽1）
        # [绘制C] 每30帧全量平台坐标日志已关闭(2026-09-07 CPU优化：超长字符串格式化+debug.log IO占CPU)
        for p in self.platforms:
            pts = self._platform_points(p)
            if len(pts) >= 2:
                scaled_pts = [(int(pt[0] * scale_x), int(pt[1] * scale_y)) for pt in pts]
                cv2.polylines(map_display, [np.array(scaled_pts, np.int32).reshape(-1, 1, 2)],
                              False, COLOR_PLATFORM, 2)


        # 人物光点：只保留游戏自带的原始光点，不自己画（find_player_dot负责检测光点位置）

        # 光点锁定可视化框已移除（与校准/正常模式绿框重复，保留后者即可）
        # 随机模式运行状态（已被倍率显示替代）
        # if self._random_running:
        #     state_text = {"idle": "选方案中", "moving": "移动中", "attacking": "攻击中", "returning": "返回起点"}.get(self._random_state, self._random_state)
        #     progress = "%d/%d" % (min(self._random_platform_idx + 1, len(self.platforms)), len(self.platforms)) if self.platforms else "0/0"
        #     status = "随机: %s 平台%s" % (state_text, progress)
        #     cv2.rectangle(map_display, (0, MAP_H - 20), (FIXED_W, MAP_H), (25, 25, 25), -1)
        #     cv2.putText(map_display, status, (6, MAP_H - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1)

        # 【模块B】自动校准倍率显示（红字 + 浅灰圆角底条，直接显示在小地图底部）始终显示
        # 各轴单独显示：X设好后先显示X，Y设好后追加显示Y；都不显示"待设置中..."
        eff_sx, eff_sy = self._effective_scale()
        if eff_sx <= 0 and eff_sy <= 0:
            scale_text = "待设置中..."
        else:
            _parts = []
            _parts.append("X %.4f" % eff_sx if eff_sx > 0 else "X 未校准")
            _parts.append("Y %.4f" % eff_sy if eff_sy > 0 else "Y 未校准")
            scale_text = "  ".join(_parts)
        _fs = 0.5   # 字体约为原来的2/3
        _txt_size = cv2.getTextSize(scale_text, cv2.FONT_HERSHEY_SIMPLEX, _fs, 1)[0]  # 用和绘制一致厚度，宽度更准
        _left = max(0, (render_w - _txt_size[0]) // 2 + 35)  # 小地图中间再向右35PX（左移15）
        _baseline = 16  # 显示在小地图窗口顶部中间(用户2026-9-6:从底部移到顶部箭头位置)
        _txt_org = (_left, _baseline)
        # 浅灰底条：左右各留1px，刚好包住文字，不突出来
        _pad = 1
        _bx1 = _txt_org[0] - _pad
        _bx2 = _txt_org[0] + _txt_size[0] + _pad
        _by1 = _baseline - _txt_size[1] - 2
        _by2 = _baseline + 2
        cv2.rectangle(map_display, (_bx1, _by1), (_bx2, _by2), (210, 210, 210), -1)  # 浅灰底条
        cv2.rectangle(map_display, (_bx1, _by1), (_bx2, _by2), (170, 170, 170), 1)   # 细边框，更精致
        # 红色主体 + 一条细黑边(粗细1)做对比，干净利落
        self._putcn(map_display, scale_text, _txt_org[0], _txt_org[1], (0, 0, 255))  # PIL中文，位置与cv2基线一致

        # 手动框选拖拽矩形
        if self._selecting and self._select_rect and self._select_dragging:
            x1, y1, x2, y2 = self._select_rect
            cv2.rectangle(map_display, (x1, y1), (x2, y2), (0, 255, 255), 1)

        # === 工具栏（小地图上方）=== 【已去掉UI绘制，用背景图自带按钮】
        # draw_asset(frame, self._ui_refresh, *BTN_REFRESH)
        # draw_asset(frame, self._ui_manual, *BTN_MANUAL)
        # draw_asset(frame, self._ui_plan_toolbar, *BTN_PLAN_TOOLBAR)
        # 【模块B】自动校准按钮（同屏三点校准）
        # draw_asset(frame, self._ui_calib_auto, *BTN_CALIB_AUTO)
        # X/Y倍率按钮：按压特效改用统一的 _pressed_btn 圆角变暗(与平台/梯子一致)，见下方"按钮点击特效"
        # 第三个框显示当前方案名或"随机"
        plan_label = "随机" if self.route_mode == "随机" else "方案%d" % self.current_route
        try:
            _ppb = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), plan_label, font=self._log_font)
            plw = _ppb[2] - _ppb[0]; plh = _ppb[3] - _ppb[1]
        except Exception:
            plw, plh = 0, 0
        plx = BTN_PLAN_TOOLBAR[0] + (BTN_PLAN_TOOLBAR[2] - plw) // 2
        ply = BTN_PLAN_TOOLBAR[1] + (BTN_PLAN_TOOLBAR[3] + plh) // 2 - 2
        self._putcn(frame, plan_label, plx, ply)  # PIL中文+按PIL字体尺寸居中

        # === 按原始大小合成到背景（不拉伸，保持原始比率，显示在顶部按钮下方）===
        map_h, map_w = map_display.shape[:2]  # 获取map_display实际尺寸
        map_display_x = (UI_W - map_w) // 2  # 水平居中
        map_display_y = 143  # 垂直位置：从162再向上移19像素
        # 保存小地图显示位置和缩放比例（供鼠标点击坐标转换用）
        self._map_disp_x = map_display_x
        self._map_disp_y = map_display_y
        self._map_disp_w = map_w
        self._map_disp_h = map_h
        self._map_scale_x = scale_x
        self._map_scale_y = scale_y
        frame[map_display_y:map_display_y+map_h, map_display_x:map_display_x+map_w] = map_display  # 显示在顶部按钮下方

        self._seg_sum['map'] = self._seg_sum.get('map', 0) + time.time() - self._seg_tp  # [分段]小地图段
        self._seg_tp = time.time()
        # === 【模块B】台子选择按钮（小地图左上方）===
        # 点击弹出选择面板，可多选平台，选完关闭
        btn_sel_x, btn_sel_y, btn_sel_w, btn_sel_h = map_display_x + 5, map_display_y + 5, 60, 20
        self._btn_platform_selector = (btn_sel_x, btn_sel_y, btn_sel_w, btn_sel_h)
        cv2.rectangle(frame, (btn_sel_x, btn_sel_y), (btn_sel_x+btn_sel_w, btn_sel_y+btn_sel_h), (60, 60, 60), -1)
        cv2.rectangle(frame, (btn_sel_x, btn_sel_y), (btn_sel_x+btn_sel_w, btn_sel_y+btn_sel_h), (150, 150, 150), 1)
        self._putcn(frame, "台子选择", btn_sel_x+5, btn_sel_y+14)  # PIL中文，位置与cv2一致
        # 显示当前选中的平台数量
        if self._selected_platforms:
            sel_text = "已选:%d" % len(self._selected_platforms)
            self._putcn(frame, sel_text, btn_sel_x+btn_sel_w+5, btn_sel_y+14, (0, 255, 0))
        else:
            self._putcn(frame, "全部", btn_sel_x+btn_sel_w+5, btn_sel_y+14, (200, 200, 200))

        # === 梯删除按钮（小地图右上角，用户2026-09-09）：点一下进入待选→点梯子蓝线删该条，再点退出 ===
        btn_ld_w, btn_ld_h = 60, 20
        btn_ld_x = map_display_x + map_w - btn_ld_w - 5
        btn_ld_y = map_display_y + 5
        self._btn_ladder_delete = (btn_ld_x, btn_ld_y, btn_ld_w, btn_ld_h)
        if self._ladder_delete_mode:
            cv2.rectangle(frame, (btn_ld_x, btn_ld_y), (btn_ld_x+btn_ld_w, btn_ld_y+btn_ld_h), (0, 0, 180), -1)  # 待选中=红底
            self._putcn(frame, "删除中", btn_ld_x+8, btn_ld_y+14, (255, 255, 255))
        else:
            cv2.rectangle(frame, (btn_ld_x, btn_ld_y), (btn_ld_x+btn_ld_w, btn_ld_y+btn_ld_h), (60, 60, 60), -1)
            cv2.rectangle(frame, (btn_ld_x, btn_ld_y), (btn_ld_x+btn_ld_w, btn_ld_y+btn_ld_h), (150, 150, 150), 1)
            self._putcn(frame, "梯删除", btn_ld_x+8, btn_ld_y+14)

        # === 【模块B】台子选择面板（点击"台子选择"后弹出）===
        if self._show_platform_selector and self.platforms:
            # 面板位置：小地图内部，覆盖在小地图上
            panel_x, panel_y = UI_MAP_X + 10, UI_MAP_Y + 30
            panel_w, panel_h = UI_MAP_W - 20, min(150, 30 + len(self.platforms) * 22)
            # 面板背景
            cv2.rectangle(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h), (40, 40, 40), -1)
            cv2.rectangle(frame, (panel_x, panel_y), (panel_x+panel_w, panel_y+panel_h), (180, 180, 180), 1)
            # 标题
            self._draw_cn_mixed(frame, "选择打怪平台（可多选）", panel_x+8, panel_y+16, 0.4, (255, 255, 255))  # 原cv2字号，只中文换字体
            # 关闭按钮X
            close_x, close_y = panel_x + panel_w - 20, panel_y + 4
            self._btn_platform_selector_close = (close_x, close_y, 16, 16)
            cv2.rectangle(frame, (close_x, close_y), (close_x+16, close_y+16), (80, 80, 80), -1)
            cv2.putText(frame, "X", (close_x+4, close_y+13),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            # 平台编号列表（每行5个，圆形样式：选中=黄底黑字，未选中=白底黑字）
            per_row = 5
            for idx, pf in enumerate(self.platforms):
                pf_num = idx + 1  # 编号从1开始
                row = idx // per_row
                col = idx % per_row
                item_x = panel_x + 10 + col * 36
                item_y = panel_y + 28 + row * 22
                # 圆形中心和半径
                circle_cx = item_x + 8
                circle_cy = item_y + 8
                circle_r = 8
                # 选中=黄底黑字，未选中=白底黑字
                checked = pf_num in self._selected_platforms
                bg_color = (0, 255, 255) if checked else (255, 255, 255)  # 黄色/白色BGR
                text_color = (0, 0, 0)  # 黑色
                cv2.circle(frame, (circle_cx, circle_cy), circle_r, bg_color, -1)
                cv2.circle(frame, (circle_cx, circle_cy), circle_r, (100, 100, 100), 1)
                # 编号文字（居中）
                num_text = str(pf_num)
                (tw, th), _ = cv2.getTextSize(num_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                cv2.putText(frame, num_text, (circle_cx - tw//2, circle_cy + th//2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, text_color, 1, cv2.LINE_AA)
                # 记录每个编号的点击区域（用于鼠标点击检测）
                # 存储在临时变量中，on_mouse时用
        else:
            self._btn_platform_selector_close = None

        self._seg_sum['ctrl'] = self._seg_sum.get('ctrl', 0) + time.time() - self._seg_tp  # [分段]台子按钮/面板
        self._seg_tp = time.time()
        # [CPU优化2026-09-07] 热键跑马灯已整段删除：固定提示文字每帧PIL画两段白描边大字实测耗87~172ms/秒，
        # 是draw最大头；该提示仅为装饰、功能无实际作用，经用户确认直接移除（背景图红框为静态图片，保留不动）
        # === 路线页按钮素材（参考图精确坐标，支持透明）=== 【已去掉UI绘制，用背景图自带按钮】
        # draw_asset(frame, self._ui_platform, *BTN_PLATFORM)
        # draw_asset(frame, self._ui_ladder, *BTN_LADDER)
        # draw_asset(frame, self._ui_save, *BTN_SAVE)
        # draw_asset(frame, self._ui_plan, *BTN_PLAN)
        # draw_asset(frame, self._ui_platform_clear, *BTN_PLATFORM_CLR)
        # draw_asset(frame, self._ui_ladder_clear, *BTN_LADDER_CLR)
        # draw_asset(frame, self._ui_mode, *BTN_MODE)
        # draw_asset(frame, self._ui_plan_clear, *BTN_PLAN_CLR)
        # draw_asset(frame, self._ui_run, *BTN_RUN)
        # draw_asset(frame, self._ui_stop, *BTN_STOP)
        # draw_asset(frame, self._ui_char_btn, *BTN_CHAR)
        # draw_asset(frame, self._ui_offset_label, *BTN_OFFSET)
        # draw_asset(frame, self._ui_monster_data, *BTN_MONSTER)
        # 在怪物数据按钮右侧白色区域显示文件夹名+BEST.ONNX（自动换行，最多2行）
        if self._yolo_model_path:
            _folder = os.path.basename(os.path.dirname(self._yolo_model_path)) or ""
            _fname = os.path.basename(self._yolo_model_path)
            if _fname.lower().endswith('.onnx'):
                _fname = _fname[:-5].upper() + ".ONNX"
            _right_x = BTN_MONSTER[0] + int(BTN_MONSTER[2] * 0.50)
            _right_w = BTN_MONSTER[2] - int(BTN_MONSTER[2] * 0.50) - 8
            _base_scale = 0.55
            _thickness = 2
            _full = ("%s\\%s" % (_folder, _fname)) if _folder else _fname
            # 先试单行
            (mw, mh), _ = cv2.getTextSize(_full, cv2.FONT_HERSHEY_SIMPLEX, _base_scale, _thickness)
            if mw <= _right_w:
                _lines = [_full]
                _scale = _base_scale
            else:
                # 超出则在 \ 处换行，最多2行
                if _folder and "\\" in _full:
                    _line1 = _folder + "\\"
                    _line2 = _fname
                else:
                    _line1 = _full
                    _line2 = ""
                # 测第二行宽度，超了就缩
                (mw2, _), _ = cv2.getTextSize(_line2, cv2.FONT_HERSHEY_SIMPLEX, _base_scale, _thickness)
                _scale = _base_scale
                if mw2 > _right_w:
                    _scale = max(0.38, _base_scale * _right_w / mw2)
                (mw1, mh), _ = cv2.getTextSize(_line1, cv2.FONT_HERSHEY_SIMPLEX, _scale, _thickness)
                if mw1 > _right_w:
                    # 第一行也超，截断
                    while _line1 and cv2.getTextSize(_line1, cv2.FONT_HERSHEY_SIMPLEX, _scale, _thickness)[0][0] > _right_w:
                        _line1 = _line1[:-2]
                    _line1 = _line1[:-1] + ".." if len(_line1) > 2 else _line1
                _lines = [_line1]
                if _line2:
                    _lines.append(_line2)
            # 绘制（垂直居中，2行时向上偏移给第二行腾空间）
            _line_h = mh + 4
            _total_h = len(_lines) * _line_h - 4
            _start_y = BTN_MONSTER[1] + (BTN_MONSTER[3] - _total_h) // 2 + mh
            for _i, _line in enumerate(_lines):
                _txy = (_right_x + 4, _start_y + _i * _line_h)
                # 路径用微软雅黑(_draw_cn_mixed,_cn_font=msyh)画，白描边+深灰字
                self._draw_cn_mixed(frame, _line, _txy[0], _txy[1], _scale, (255, 255, 255), _thickness + 2)
                self._draw_cn_mixed(frame, _line, _txy[0], _txy[1], _scale, (40, 40, 40), _thickness)
        draw_asset(frame, self._ui_winbind_bg, *BTN_WINBIND)
        # 已绑定窗口下拉框
        draw_asset(frame, self._ui_bound_dropdown, UI_BOUND_X, UI_BOUND_Y, UI_BOUND_W, UI_BOUND_H)

        # === 录制状态红色闪烁指示器（在对应按钮左上角）===
        import time as _t
        if int(_t.time() * 3) % 2 == 0:
            if self.recording_platform:
                cv2.circle(frame, (BTN_PLATFORM[0] + 8, BTN_PLATFORM[1] + 8), 5, (0, 0, 255), -1)
                cv2.circle(frame, (BTN_PLATFORM[0] + 8, BTN_PLATFORM[1] + 8), 5, (0, 0, 180), 1)
            if self.recording_ladder:
                cv2.circle(frame, (BTN_LADDER[0] + 8, BTN_LADDER[1] + 8), 5, (0, 0, 255), -1)
                cv2.circle(frame, (BTN_LADDER[0] + 8, BTN_LADDER[1] + 8), 5, (0, 0, 180), 1)

        # === 下拉菜单 ===
        if self._dropdown is not None:
            items = self._dropdown_items()
            n = len(items)
            dd_btn_map = {"mode": BTN_MODE}
            bx, by, bw, bh = dd_btn_map[self._dropdown]
            menu_h = n * DROPDOWN_ITEM_H
            menu_y1 = by + bh
            menu_y2 = menu_y1 + menu_h
            cv2.rectangle(frame, (bx, menu_y1), (bx + bw - 1, menu_y2 - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (bx, menu_y1), (bx + bw - 1, menu_y2 - 1), (110, 110, 110), 1)
            for i, text in enumerate(items):
                iy = menu_y1 + i * DROPDOWN_ITEM_H
                if i > 0:
                    cv2.line(frame, (bx + 3, iy), (bx + bw - 4, iy), (85, 85, 85), 1)
                is_current = (self._dropdown == "mode" and text == self.route_mode)
                if is_current:
                    cv2.rectangle(frame, (bx + 1, iy + 1), (bx + bw - 2, iy + DROPDOWN_ITEM_H - 1), (0, 70, 0), -1)
                color = (0, 255, 0) if is_current else (240, 240, 240)
                self._draw_cn_mixed(frame, text, bx + 6, iy + 17, 0.42, color)  # 原cv2字号，只中文换字体

        self._seg_sum['mid'] = self._seg_sum.get('mid', 0) + time.time() - self._seg_tp  # [分段]按钮素材/绑定框/下拉
        self._seg_tp = time.time()
        # === 运行日志区域（日志底板+向上流动+右侧滚动条）===
        # [CPU优化2026-09-07] 日志内容/滚动位置不变时画面每帧完全相同，整块贴缓存跳过PIL重绘（旧实现每帧拷贝ROI+BGR<->RGB转换+逐行PIL画字，实测68ms/秒）
        lx, ly, lw, lh = UI_LOG_X, UI_LOG_Y, UI_LOG_W, UI_LOG_H
        # 日志内容（最新信息在最上方，向下越来越旧）
        log_content_y = UI_LOG_CONTENT_Y
        log_content_h = UI_LOG_H - (UI_LOG_CONTENT_Y - UI_LOG_Y) - 4
        line_h = 16
        # 双日志视图(用户2026-09-09)：combat=打怪日志 / behavior=行为日志，标题栏两个tab点开切换
        _view = self._log_view
        _logs = self._runtime_logs if _view == 'combat' else self._behavior_logs
        _scroll = self._log_scroll if _view == 'combat' else self._behavior_scroll
        # tab按钮矩形(标题栏内)，每帧更新供鼠标点击命中(无论缓存是否命中)
        _tab_w, _tab_h = 50, 17
        _tab_y = ly + 3
        self._log_tab_combat = (lx + 4, _tab_y, _tab_w, _tab_h)
        self._log_tab_behavior = (lx + 4 + _tab_w + 4, _tab_y, _tab_w, _tab_h)
        max_lines = max(1, log_content_h // line_h)
        _avail_w = lw - 4 - 8 - 2 - 6   # 左留白4 + 右滚动条(8+2) + 余量6
        render = self._log_wrap_lines(_logs, _avail_w)  # 旧→新的折行渲染行(续行不带时间)
        total = len(render)
        # scroll=0 停在顶部看最新N行；>0 向下滚动看更旧历史(单位=折行后的渲染行)
        end_idx = total - _scroll
        start_idx = max(0, end_idx - max_lines)
        visible = render[start_idx:end_idx]
        # 缓存键=视图+滚动+总行数+可见渲染行，任一变化才重PIL渲染（视图切换/新日志/滚动才耗一次PIL，其余帧零开销）
        _log_key = (_view, _scroll, total, tuple(visible))
        if self._log_cache_img is not None and _log_key == self._log_cache_key:
            frame[ly:ly+lh, lx:lx+lw] = self._log_cache_img  # 命中：整块贴回（含底板+tab+文字+滚动条），零PIL开销
        else:
            draw_asset(frame, self._ui_log_bg, lx, ly, lw, lh)  # 未命中：先贴日志底板
            # 两个tab：当前选中=深绿底白字，未选=深灰底灰字
            for _tv, _tr, _tn in (('combat', self._log_tab_combat, '打怪'),
                                  ('behavior', self._log_tab_behavior, '行为')):
                _tx, _tyy, _tw, _th = _tr
                _sel = (_view == _tv)
                cv2.rectangle(frame, (_tx, _tyy), (_tx + _tw, _tyy + _th),
                              (0, 110, 0) if _sel else (55, 55, 55), -1)
                cv2.rectangle(frame, (_tx, _tyy), (_tx + _tw, _tyy + _th), (180, 180, 180), 1)
                self._putcn(frame, _tn, _tx + 12, _tyy + 13,
                            (255, 255, 255) if _sel else (185, 185, 185))
            # 用PIL中文字体画日志（cv2.putText画不了中文会变???乱码）
            if visible:
                _roi = frame[ly:ly+lh, lx:lx+lw].copy()
                _pil = Image.fromarray(cv2.cvtColor(_roi, cv2.COLOR_BGR2RGB))
                _draw = ImageDraw.Draw(_pil)
                # 切片仍是旧→新，倒序绘制让最新一条落在第一行(最上方)；顶格起画不再空两行(用户2026-09-09)
                for i, (text, col, indent) in enumerate(reversed(visible)):
                    ty = log_content_y + i * line_h
                    if ty > ly + lh - line_h:
                        break
                    # 首行indent=0带[时间]，续行indent=时间戳宽、只画消息、不写时间
                    _draw.text((4 + indent, ty - ly), text, font=self._log_font,
                               fill=(col[2], col[1], col[0]))
                frame[ly:ly+lh, lx:lx+lw] = cv2.cvtColor(np.array(_pil), cv2.COLOR_RGB2BGR)
            # 右侧滚动条（跟随当前视图）
            sb_w = 8
            sb_x = lx + lw - sb_w - 2
            sb_y = log_content_y
            sb_h = log_content_h
            cv2.rectangle(frame, (sb_x, sb_y), (sb_x+sb_w-1, sb_y+sb_h-1), (220, 220, 220), -1)
            if total > max_lines:
                thumb_h = max(10, int(sb_h * max_lines / total))
                max_scroll = total - max_lines
                thumb_y = sb_y + int((sb_h - thumb_h) * (_scroll / max(max_scroll, 1)))
                cv2.rectangle(frame, (sb_x+1, thumb_y), (sb_x+sb_w-2, thumb_y+thumb_h-1), (140, 140, 140), -1)
            # 渲染完成，整块截图存缓存（下一帧键不变直接复用）
            self._log_cache_img = frame[ly:ly+lh, lx:lx+lw].copy()
            self._log_cache_key = _log_key

        self._seg_sum['log'] = self._seg_sum.get('log', 0) + time.time() - self._seg_tp  # [分段]日志区
        self._seg_tp = time.time()
        # === 已绑窗口下拉列表（向上弹出，最多10项）===
        if self._bound_dropdown and self._bound_windows:
            item_h = 20
            show_count = min(len(self._bound_windows), 10)
            menu_y2 = UI_BOUND_Y  # 菜单底部在按钮顶部
            menu_y1 = menu_y2 - show_count * item_h
            # 背景
            cv2.rectangle(frame, (UI_BOUND_X, menu_y1), (UI_BOUND_X + UI_BOUND_W - 1, menu_y2 - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (UI_BOUND_X, menu_y1), (UI_BOUND_X + UI_BOUND_W - 1, menu_y2 - 1), (110, 110, 110), 1)
            for i, w in enumerate(self._bound_windows[:10]):
                iy = menu_y1 + i * item_h
                if i > 0:
                    cv2.line(frame, (UI_BOUND_X + 3, iy), (UI_BOUND_X + UI_BOUND_W - 4, iy), (85, 85, 85), 1)
                is_current = (w["hwnd"] == self.hwnd)
                if is_current:
                    cv2.rectangle(frame, (UI_BOUND_X + 1, iy + 1), (UI_BOUND_X + UI_BOUND_W - 2, iy + item_h - 1), (0, 70, 0), -1)
                color = (0, 255, 0) if is_current else (240, 240, 240)
                title = w["title"][:12] if len(w["title"]) > 12 else w["title"]
                cv2.putText(frame, title, (UI_BOUND_X + 4, iy + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.32, color, 1)
            # 提示右键解绑
            cv2.putText(frame, "RMB unbind", (UI_BOUND_X, menu_y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1)
            if len(self._bound_windows) > 10:
                cv2.putText(frame, "...+%d more" % (len(self._bound_windows) - 10), (UI_BOUND_X, menu_y1 - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (180, 180, 180), 1)

        # === 可拖拽准星（窗口绑定，用素材，支持透明）===
        # 拖拽时不绘制UI窗口上的准星，只显示pygame透明置顶窗口的准星（避免两个准星同时动）
        if not self._drag_crosshair:
            chx, chy = self._crosshair_pos
            cs = self._crosshair_size
            if self._ui_crosshair is not None:
                draw_asset(frame, self._ui_crosshair, chx-cs//2, chy-cs//2, cs, cs)
            else:
                r = cs // 2
                cv2.circle(frame, (chx, chy), r, (0, 0, 255), 2)
                cv2.circle(frame, (chx, chy), max(1, r // 3), (0, 0, 255), -1)
                cv2.line(frame, (chx - r - 4, chy), (chx - r + 1, chy), (0, 0, 255), 2)
                cv2.line(frame, (chx + r - 1, chy), (chx + r + 4, chy), (0, 0, 255), 2)
                cv2.line(frame, (chx, chy - r - 4), (chx, chy - r + 1), (0, 0, 255), 2)
                cv2.line(frame, (chx, chy + r - 1), (chx, chy + r + 4), (0, 0, 255), 2)

        # === 准星拖拽模式提示 ===
        if self._drag_crosshair:
            cv2.putText(frame, "DRAG TO GAME WINDOW", (UI_W // 2 - 100, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # === 人物特征下拉面板（向下弹出，5行：删除全部+4特征）===
        if self._char_dropdown:
            dd_top = BTN_CHAR[1] + BTN_CHAR[3]
            dd_bottom = dd_top + CHAR_DD_VISIBLE * CHAR_DD_ITEM_H
            dd_main_x2 = CHAR_DD_X + CHAR_DD_W
            dd_scroll_x2 = dd_main_x2 + CHAR_DD_SCROLL_W
            # 主体背景
            cv2.rectangle(frame, (CHAR_DD_X, dd_top), (dd_main_x2 - 1, dd_bottom - 1), (48, 48, 48), -1)
            cv2.rectangle(frame, (CHAR_DD_X, dd_top), (dd_main_x2 - 1, dd_bottom - 1), (100, 100, 100), 1)
            # 翻页条背景
            cv2.rectangle(frame, (dd_main_x2, dd_top), (dd_scroll_x2 - 1, dd_bottom - 1), (58, 58, 58), -1)
            cv2.rectangle(frame, (dd_main_x2, dd_top), (dd_scroll_x2 - 1, dd_bottom - 1), (100, 100, 100), 1)
            # 翻页箭头
            mid_y = dd_top + (dd_bottom - dd_top) // 2
            cv2.putText(frame, "^", (dd_main_x2 + 5, mid_y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            cv2.putText(frame, "v", (dd_main_x2 + 5, dd_bottom - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            # 行0：删除全部
            cv2.line(frame, (CHAR_DD_X + 2, dd_top + CHAR_DD_ITEM_H), (dd_main_x2 - 3, dd_top + CHAR_DD_ITEM_H), (80, 80, 80), 1)
            cv2.putText(frame, "[Delete All]", (CHAR_DD_X + 18, dd_top + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 80, 255), 1)
            # 行1-4：特征槽位
            for row in range(CHAR_DD_FEAT_PER_PAGE):
                slot_idx = self._char_scroll + row
                iy = dd_top + (row + 1) * CHAR_DD_ITEM_H
                if row > 0:
                    cv2.line(frame, (CHAR_DD_X + 2, iy), (dd_main_x2 - 3, iy), (75, 75, 75), 1)
                if slot_idx < len(self._char_templates):
                    t = self._char_templates[slot_idx]
                    try:
                        thumb = cv2.resize(t["img"], (14, 14))
                        th, tw = thumb.shape[:2]
                        if iy + 3 + th <= frame.shape[0] and CHAR_DD_X + 4 + tw <= frame.shape[1]:
                            frame[iy + 3:iy + 3 + th, CHAR_DD_X + 4:CHAR_DD_X + 4 + tw] = thumb
                    except Exception:
                        pass
                    cv2.putText(frame, "#%d %dx%d" % (t["id"], t["width"], t["height"]),
                                (CHAR_DD_X + 22, iy + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.28, (230, 230, 230), 1)
                elif slot_idx < CHAR_DD_ITEMS:
                    cv2.putText(frame, "[%d] +" % slot_idx, (CHAR_DD_X + 6, iy + 14),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.28, (140, 140, 140), 1)
            # 滚动位置提示
            cv2.putText(frame, "%d/%d" % (self._char_scroll + 1, CHAR_DD_ITEMS - CHAR_DD_FEAT_PER_PAGE + 1),
                        (dd_main_x2 + 1, dd_top + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.22, (160, 160, 160), 1)

        # === 路线页输入框（X/Y偏移，标签下方）===
        self._draw_input_fields(frame)

        # === 怪物特征按钮（用UI图片，盖住原来的X/Y偏移输入框，点击打开怪物特征管理弹窗）===
        _mbfx, _mbfy, _mbfw, _mbfh = BTN_MONSTER_FEATURE
        # 加载怪物特征按钮UI图片（懒加载，只加载一次，用IMREAD_UNCHANGED保留alpha通道做透明混合）
        if not hasattr(self, '_monster_btn_img') or self._monster_btn_img is None:
            _btn_img_path = os.path.join(DATA_DIR, "monster_feature_btn.png")
            if os.path.exists(_btn_img_path):
                self._monster_btn_img = cv2.imdecode(np.fromfile(_btn_img_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            else:
                self._monster_btn_img = None
        if self._monster_btn_img is not None:
            # 直接用原图大小绘制，不缩放（图片尺寸190x60，和按钮尺寸一致）
            _img_h, _img_w = self._monster_btn_img.shape[:2]
            _draw_w = min(_img_w, _mbfw)
            _draw_h = min(_img_h, _mbfh)
            _roi = frame[_mbfy:_mbfy+_draw_h, _mbfx:_mbfx+_draw_w]
            _btn_roi = self._monster_btn_img[:_draw_h, :_draw_w]
            # 透明混合：如果有alpha通道（4通道），按alpha值混合；否则直接覆盖
            if _btn_roi.shape[2] == 4:
                _alpha = _btn_roi[:, :, 3:4].astype(np.float32) / 255.0
                _bg = _roi.astype(np.float32)
                _fg = _btn_roi[:, :, :3].astype(np.float32)
                frame[_mbfy:_mbfy+_draw_h, _mbfx:_mbfx+_draw_w] = (_fg * _alpha + _bg * (1 - _alpha)).astype(np.uint8)
            else:
                frame[_mbfy:_mbfy+_draw_h, _mbfx:_mbfx+_draw_w] = _btn_roi
        else:
            # 图片加载失败，用代码绘制兜底
            draw_rounded_rect(frame, _mbfx, _mbfy, _mbfw, _mbfh, 8, (46, 125, 50), -1)
            draw_rounded_rect(frame, _mbfx, _mbfy, _mbfw, _mbfh, 8, (76, 175, 80), 2)
            _mbtn_text = "怪物特征"
            (_mtw, _mth), _ = cv2.getTextSize(_mbtn_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            _mtx = _mbfx + (_mbfw - _mtw) // 2
            _mty = _mbfy + (_mbfh + _mth) // 2
            self._draw_cn_mixed(frame, _mbtn_text, _mtx, _mty, 0.7, (255, 255, 255), 2)  # 原cv2字号，只中文换字体
        # 右上角显示特征数量
        _mcount = len(self._monster_templates)
        if _mcount > 0:
            self._draw_cn_mixed(frame, "%d套" % _mcount, _mbfx + _mbfw - 35, _mbfy + 18, 0.4, (200, 255, 200))  # 原cv2字号，只"套"换字体

        # === 按钮点击特效（仅按下变暗，圆角）===
        now_ms = time.time() * 1000
        if self._pressed_btn is not None:
            bx, by, bw, bh = self._pressed_btn
            overlay = frame.copy()
            draw_rounded_rect(overlay, bx, by, bw, bh, 10, (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        self._btn_flashes.clear()

        # === 倍率差弹窗（按照弹窗组件实现规范，灰底白字，右上角X关闭，可拖拽，最上层）===
        if self._show_scale_dialog:
            self._update_scale_dialog_positions()  # 每次绘制都更新位置，确保拖拽后位置正确
            dlg_x = self._scale_dialog_pos[0]
            dlg_y = self._scale_dialog_pos[1]
            dlg_w, dlg_h = 320, 220
            # 弹窗背景（灰底）
            cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (60, 60, 60), -1)
            cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (100, 100, 100), 1)
            # 标题栏（顶部50像素区域，可拖拽）
            cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+50), (80, 80, 80), -1)
            self._draw_cn_mixed(frame, "倍率差调整", dlg_x+15, dlg_y+32, 0.6, (255, 255, 255))  # 原cv2字号，只中文换字体
            # 右上角关闭按钮X
            cx, cy, cw, ch = self._dlg_scale_close_btn
            cv2.rectangle(frame, (cx, cy), (cx+cw-1, cy+ch-1), (80, 80, 80), -1)
            cv2.putText(frame, "X", (cx+7, cy+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            # X偏差标签和输入框
            self._draw_cn_mixed(frame, "X偏差:", dlg_x+20, dlg_y+88, 0.5, (255, 255, 255))  # 原cv2字号，只中文换字体
            sx_x, sx_y, sx_w, sx_h = self._dlg_scale_x_input
            cv2.rectangle(frame, (sx_x, sx_y), (sx_x+sx_w-1, sx_y+sx_h-1), (0, 0, 0), -1)  # 黑底
            border_color = (0, 165, 255) if self._focused_field == "scale_x_offset" else (255, 255, 255)  # 聚焦时橙色边框，否则白色
            border_thick = 2 if self._focused_field == "scale_x_offset" else 1
            cv2.rectangle(frame, (sx_x, sx_y), (sx_x+sx_w-1, sx_y+sx_h-1), border_color, border_thick)
            x_offset_val = self._field_values.get("scale_x_offset", "0")
            cv2.putText(frame, x_offset_val, (sx_x+8, sx_y+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            # Y偏差标签和输入框
            self._draw_cn_mixed(frame, "Y偏差:", dlg_x+20, dlg_y+148, 0.5, (255, 255, 255))  # 原cv2字号，只中文换字体
            sy_x, sy_y, sy_w, sy_h = self._dlg_scale_y_input
            cv2.rectangle(frame, (sy_x, sy_y), (sy_x+sy_w-1, sy_y+sy_h-1), (0, 0, 0), -1)  # 黑底
            border_color = (0, 165, 255) if self._focused_field == "scale_y_offset" else (255, 255, 255)  # 聚焦时橙色边框，否则白色
            border_thick = 2 if self._focused_field == "scale_y_offset" else 1
            cv2.rectangle(frame, (sy_x, sy_y), (sy_x+sy_w-1, sy_y+sy_h-1), border_color, border_thick)
            y_offset_val = self._field_values.get("scale_y_offset", "0")
            cv2.putText(frame, y_offset_val, (sy_x+8, sy_y+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            # 确认按钮
            ok_x, ok_y, ok_w, ok_h = self._dlg_scale_ok_btn
            cv2.rectangle(frame, (ok_x, ok_y), (ok_x+ok_w-1, ok_y+ok_h-1), (0, 128, 0), -1)
            self._draw_cn_mixed(frame, "确认", ok_x+20, ok_y+20, 0.5, (255, 255, 255))  # 原cv2字号，只中文换字体
            # 取消按钮
            cancel_x, cancel_y, cancel_w, cancel_h = self._dlg_scale_cancel_btn
            cv2.rectangle(frame, (cancel_x, cancel_y), (cancel_x+cancel_w-1, cancel_y+cancel_h-1), (128, 0, 0), -1)
            self._draw_cn_mixed(frame, "取消", cancel_x+20, cancel_y+20, 0.5, (255, 255, 255))  # 原cv2字号，只中文换字体

        self._seg_sum['rest'] = self._seg_sum.get('rest', 0) + time.time() - self._seg_tp  # [分段]其余控件/弹窗
        return frame


    def manual_select_region(self):
        """手动框选：OpenCV独立窗口1:1显示游戏截图，拖拽框选，坐标即游戏窗口坐标"""
        self._was_random_running = self._random_running
        if self._random_running:
            self._stop_random()

        print("\n=== 手动框选 ===")
        self._update_window_rect()
        frame = self._capture_window()
        if frame is None:  # [健壮性2026-09-07] 截图瞬时失败不崩，提示重试
            self._add_log("截图失败，请重试")
            return
        fh, fw = frame.shape[:2]

        sel_win = "Select Minimap"
        cv2.namedWindow(sel_win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(sel_win, fw, fh)
        # OpenCV窗口对齐游戏窗口位置，避免偏移
        if self.window_rect:
            cv2.moveWindow(sel_win, self.window_rect["left"], self.window_rect["top"])
        else:
            cv2.moveWindow(sel_win, 0, 0)
        # 置顶：避免被游戏窗口挡住
        cv2.setWindowProperty(sel_win, cv2.WND_PROP_TOPMOST, 1)

        self._select_rect = None
        self._select_dragging = False
        self._select_confirmed = False

        def on_sel_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                self._select_dragging = True
                self._select_rect = (x, y, x, y)
            elif event == cv2.EVENT_MOUSEMOVE and self._select_dragging:
                x1, y1, _, _ = self._select_rect
                self._select_rect = (x1, y1, x, y)
            elif event == cv2.EVENT_LBUTTONUP:
                self._select_dragging = False
                x1, y1, _, _ = self._select_rect
                self._select_rect = (x1, y1, x, y)
                self._select_confirmed = True

        cv2.setMouseCallback(sel_win, on_sel_mouse)
        print("在弹出的窗口上拖拽框选小地图，松开自动确认，按 Esc 取消")

        while True:
            display = frame.copy()
            if self._select_rect:
                x1, y1, x2, y2 = self._select_rect
                x1, x2 = min(x1, x2), max(x1, x2)
                y1, y2 = min(y1, y2), max(y1, y2)
                cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(display, "Drag to select minimap, release=apply, Esc=exit",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.imshow(sel_win, display)
            key = cv2.waitKey(20) & 0xFF
            if key == 27:
                print("取消框选")
                break
            if self._select_confirmed:
                x1, y1, x2, y2 = self._select_rect
                x1, x2 = min(x1, x2), max(x1, x2)
                y1, y2 = min(y1, y2), max(y1, y2)
                w = x2 - x1
                h = y2 - y1
                if w >= 20 and h >= 20:
                    self.minimap_rect = {"left": x1, "top": y1, "width": w, "height": h}
                    pad_l, pad_t, pad_r, pad_b = 8, 2, 2, 2
                    self.map_area_rect = {
                        "left": x1 + pad_l, "top": y1 + pad_t,
                        "width": w - pad_l - pad_r, "height": h - pad_t - pad_b
                    }
                    self._save_region()
                    self.frame_count = 0
                    self.last_player_pos = None
                    self._auto_refresh = False
                    print("已应用: (%d,%d) %dx%d（自动刷新已关闭，点刷新可重新开启）" % (x1, y1, w, h))
                else:
                    print("选择区域太小")
                break
            if cv2.getWindowProperty(sel_win, cv2.WND_PROP_VISIBLE) < 1:
                break

        cv2.destroyWindow(sel_win)
        # F9结束后强制重新定位和置顶怪物蒙板（避免OpenCV窗口影响蒙板置顶和位置）
        if getattr(self, '_overlay_hwnd', None) and self.hwnd and self.window_rect:
            try:
                wr = self.window_rect
                user32.SetWindowPos(self._overlay_hwnd, -1, wr['left'], wr['top'],
                                    wr['width'], wr['height'], 0x0050)
                _debug_log("[F9] 蒙板已重新定位置顶: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
            except Exception as _e:
                _debug_log("[F9] 蒙板重新定位失败: %s" % _e)
        if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
            self._start_random()

    def _stop_select_listener(self):
        pass

    def _confirm_select(self):
        """确认框选（松开鼠标自动调用），将显示坐标映射到游戏窗口坐标"""
        if not self._select_rect:
            return
        x1, y1, x2, y2 = self._select_rect
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        w = x2 - x1
        h = y2 - y1
        if w < 10 or h < 10:
            print("选择区域太小，请重新拉取")
            self._select_rect = None
            return
        # 显示坐标(FIXED_W x MAP_H)映射到游戏窗口坐标
        self._update_window_rect()
        frame = self._capture_window()
        if frame is None:  # [健壮性2026-09-07] 截图瞬时失败不崩
            self._select_rect = None
            return
        fh, fw = frame.shape[:2]
        sx = fw / FIXED_W
        sy = fh / MAP_H
        gx = int(x1 * sx)
        gy = int(y1 * sy)
        gw = int(w * sx)
        gh = int(h * sy)
        self.minimap_rect = {"left": gx, "top": gy, "width": gw, "height": gh}
        pad_l, pad_t, pad_r, pad_b = 8, 2, 2, 2
        self.map_area_rect = {
            "left": gx + pad_l, "top": gy + pad_t,
            "width": gw - pad_l - pad_r, "height": gh - pad_t - pad_b
        }
        self._recalc_scale_from_region()
        self._save_region()
        self.frame_count = 0
        self.last_player_pos = None
        self._auto_refresh = False
        self._selecting = False
        self._select_rect = None
        self._select_dragging = False
        if hasattr(self, '_win_name'):
            cv2.setWindowProperty(self._win_name, cv2.WND_PROP_TOPMOST, 0)
        if getattr(self, '_was_random_running', False) and self.route_mode == "随机":
            self._start_random()
        print("已应用: (%d,%d) %dx%d（自动刷新已关闭，点刷新可重新开启）" % (gx, gy, gw, gh))

    def _add_log(self, msg):
        self._logs.append(msg)
        if len(self._logs) > 20:
            self._logs = self._logs[-20:]

    def _rlog(self, msg, color=None, log='combat'):
        """添加运行日志（新信息在顶部，向下越来越旧）。
        log='combat'=打怪日志(找怪/锁定/打怪/换锁/空怪)；log='behavior'=行为日志(爬梯/跨层/走位/退开/吃药等因果)。
        color用BGR，失败类传 LOG_RED=(0,0,255) 红字。"""
        if color is None:
            color = (40, 40, 40)
        t = time.strftime("%H:%M:%S")
        _entry = {"t": t, "msg": msg, "color": color}
        if log == 'behavior':
            self._behavior_logs.append(_entry)
            if len(self._behavior_logs) > self._log_max:
                self._behavior_logs = self._behavior_logs[-self._log_max:]
            self._behavior_scroll = 0   # 新行为日志回到顶部
        else:
            self._runtime_logs.append(_entry)
            if len(self._runtime_logs) > self._log_max:
                self._runtime_logs = self._runtime_logs[-self._log_max:]
            self._log_scroll = 0       # 新打怪日志回到顶部

    def _rlog_throttle(self, key, msg, interval_ms=700, color=None, log='combat'):
        """同一key限频上屏到日志滚动区(默认700ms最多一条)，用于_combat_tick/_move_to等每帧热路径，
        避免状态日志刷屏；一次性状态转换事件请直接用_rlog。log分类同_rlog。"""
        _now = int(time.time() * 1000)
        _last = getattr(self, '_rlog_last', {}).get(key, 0)
        if _now - _last >= interval_ms:
            if not hasattr(self, '_rlog_last'):
                self._rlog_last = {}
            self._rlog_last[key] = _now
            self._rlog(msg, color, log=log)

    def _log_wrap_lines(self, entries, avail_w):
        """把日志条目(旧→新)展开成渲染行 [(text,color,indent_px), ...]。
        长消息按像素宽自动折行；第一行带[HH:MM:SS]，续行不写时间、缩进对齐到消息首字(用户2026-09-09)。"""
        f = self._log_font

        def _tw(s):
            try:
                return f.getlength(s)          # Pillow>=8 像素宽
            except Exception:
                try:
                    return f.getsize(s)[0]
                except Exception:
                    return len(s) * 7
        out = []
        for e in entries:
            col = e.get("color", (40, 40, 40))
            head = "[%s] " % e["t"]
            head_w = _tw(head)
            indent = int(head_w)
            first_limit = avail_w - head_w
            next_limit = avail_w - indent
            segs = []
            for raw in str(e["msg"]).split("\n"):
                # 每段逐字符贪心折行；第一段让时间戳，后续段用续行宽
                limit = first_limit if not segs else next_limit
                cur = ""
                for ch in raw:
                    if cur and _tw(cur + ch) > limit:
                        segs.append(cur)
                        cur = ch
                        limit = next_limit
                    else:
                        cur += ch
                segs.append(cur)
            if not segs:
                segs = [""]
            out.append((head + segs[0], col, 0))
            for sg in segs[1:]:
                out.append((sg, col, indent))
        return out

    def _maint_trim_debug_log(self, keep_minutes=5):
        """debug.log 只保留最近 keep_minutes 分钟(按行首[HH:MM:SS])；小于0.5MB不动避免频繁IO。
        _debug_log 每次重开 'a' 追加，故这里可安全 os.replace 替换正在写的文件。"""
        try:
            p = os.path.join(SCRIPT_DIR, "debug.log")
            if not os.path.exists(p) or os.path.getsize(p) < 512 * 1024:
                return
            import io as _io
            rows = _io.open(p, "rb").read().decode("utf-8", "ignore").splitlines()

            def _ts(l):
                if l[:1] == "[" and len(l) >= 9 and l[3] == ":" and l[6] == ":":
                    try:
                        return int(l[1:3]) * 3600 + int(l[4:6]) * 60 + int(l[7:9])
                    except Exception:
                        return None
                return None
            last = None
            for l in reversed(rows):
                t = _ts(l)
                if t is not None:
                    last = t
                    break
            if last is None:
                return
            cut = last - keep_minutes * 60
            keep = [l for l in rows if _ts(l) is None or _ts(l) >= cut]
            if len(keep) < len(rows):
                tmp = p + ".tmp"
                _io.open(tmp, "w", encoding="utf-8").write("\n".join(keep) + "\n")
                os.replace(tmp, p)
                _debug_log("[维护] debug.log保留最近%d分钟 %d→%d行" % (keep_minutes, len(rows), len(keep)))
        except Exception as ex:
            _debug_log("[维护] 修剪debug.log异常: %s" % ex)

    def _maint_clean_old_cache(self, days=1):
        """清程序自己生成的调试截图/运行日志(超过days天)。绝不碰 backups/data/用户文件/模型。"""
        try:
            import glob as _glob
            now = time.time()
            n = 0
            for pat in ("debug_*.png", "_dbg*.png", "runtime_out*.log", "runtime_err*.log"):
                for fp in _glob.glob(os.path.join(SCRIPT_DIR, pat)):
                    try:
                        if now - os.path.getmtime(fp) > days * 86400:
                            os.remove(fp)
                            n += 1
                    except Exception:
                        pass
            if n:
                _debug_log("[维护] 清理过期调试缓存%d个" % n)
        except Exception as ex:
            _debug_log("[维护] 清缓存异常: %s" % ex)

    def _maint_run(self):
        """定期维护：debug.log留最近5分钟 + 清1天前调试缓存。
        backups自动快照按用户要求全部保留，不在此删除。"""
        self._maint_trim_debug_log(5)
        self._maint_clean_old_cache(1)

    def _load_char_templates(self):
        """从磁盘加载已保存的人物特征模板（优先运行时目录app_dir/data，打包后也能加载用户保存的模板）"""
        self._char_templates = []
        # 优先从运行时目录加载（用户保存的模板，打包后也在app_dir/data/char_templates）
        tpl_dir = CHAR_TEMPLATE_DIR
        has_runtime = False
        if os.path.exists(tpl_dir):
            has_runtime = any(f.startswith("char_") and f.endswith(".png") for f in os.listdir(tpl_dir))
        # 打包环境下运行时目录没有模板，则从内置_MEIPASS加载默认模板（记录003：修复保存后重启丢失）
        if not has_runtime and getattr(sys, 'frozen', False):
            tpl_dir = os.path.join(sys._MEIPASS, "data", "char_templates")
        if not os.path.exists(tpl_dir):
            print("[人物特征] 无保存的特征模板，为空")
            return
        # 先加载元数据（含偏移）
        meta_list = []
        try:
            if os.path.exists(CHAR_TEMPLATE_META):
                with open(CHAR_TEMPLATE_META, "r", encoding="utf-8") as _mf:
                    meta_list = json.load(_mf)
        except Exception:
            meta_list = []
        try:
            # 扫描 char_<id>.png，按文件名排序加载（ID小的在前）
            for fname in sorted(os.listdir(tpl_dir)):
                if fname.startswith("char_") and fname.endswith(".png"):
                    try:
                        tid = int(fname.replace("char_", "").replace(".png", ""))
                    except ValueError:
                        continue  # 非标准命名的文件跳过，不影响其他模板加载
                    img_path = os.path.join(tpl_dir, fname)
                    # 用imdecode+fromfile兼容中文路径（cv2.imread中文路径静默失败）
                    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape[:2]  # 3通道图shape=(h,w,3)，取前2维避免解包失败
                        # 从元数据加载偏移（默认0，兼容旧模板）
                        _off_x = 0
                        _off_y = 0
                        _direction = "right"  # 默认向右，兼容旧模板
                        for _m in meta_list:
                            if _m.get("id") == tid:
                                _off_x = int(_m.get("offset_x", 0))
                                _off_y = int(_m.get("offset_y", 0))
                                _direction = _m.get("direction", "right")
                                break
                        self._char_templates.append({
                            "id": tid,
                            "img": img,
                            "width": w,
                            "height": h,
                            "offset_x": _off_x,   # 特征匹配点→人物脚的X偏移
                            "offset_y": _off_y,   # 特征匹配点→人物脚的Y偏移
                            "direction": _direction,  # 朝向: left/right
                            "created_at": ""
                        })
            print("[人物特征] 已加载 %d 套模板" % len(self._char_templates))
        except Exception as e:
            print("[人物特征] 加载模板失败:", e)
    def _save_char_meta(self):
        """保存人物特征模板元数据到磁盘"""
        meta_list = []
        for t in self._char_templates:
            meta_list.append({
                "id": t["id"],
                "width": t["width"],
                "height": t["height"],
                "offset_x": t.get("offset_x", 0),
                "offset_y": t.get("offset_y", 0),
                "direction": t.get("direction", "right"),
                "color": t.get("color", CHAR_FEATURE_COLORS[t["id"] % len(CHAR_FEATURE_COLORS)]),
                "created_at": t["created_at"]
            })
        try:
            with open(CHAR_TEMPLATE_META, "w", encoding="utf-8") as f:
                json.dump(meta_list, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[人物特征] 保存元数据失败:", e)

    def _feature_quality_check(self, frame, timg, roi_xy=None):
        """特征点质量检测（用户2026-09-04）：对刚添加的特征模板做全图匹配
        返回 (最高分, ≥0.70命中处数, 是否可疑) 或 None
        可疑=排自匹配后最高分≥0.95 或 命中≥2处(≥0.70都算=易撞脸/重复/换处)
        roi_xy=特征被裁取的左上角(x,y)：模板就是从frame[ry:ry+th,rx:rx+tw]裁的，
        那里必然是1.00自匹配，必须排除，否则所有刚录的特征都被误判为"撞脸/背景"。
        作用：添加后当场标出坏点，不用靠反复试/猜。"""
        if frame is None or timg is None:
            return None
        th, tw = timg.shape[:2]
        if th <= 0 or tw <= 0 or th > frame.shape[0] or tw > frame.shape[1]:
            return None
        try:
            # 兼容4通道RGBA模板
            if timg.ndim == 3 and timg.shape[2] == 4:
                timg = cv2.cvtColor(timg, cv2.COLOR_BGRA2BGR)
            if frame.ndim == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            res = cv2.matchTemplate(frame, timg, cv2.TM_CCOEFF_NORMED)
            # 排除自匹配区域（模板就是从这裁的，匹配必=1.00，不算撞脸）
            if roi_xy is not None:
                rx, ry = int(roi_xy[0]), int(roi_xy[1])
                rh_, rw_ = res.shape
                res[max(0, ry):min(rh_, ry + th), max(0, rx):min(rw_, rx + tw)] = 0.0
            _, max_val, _, _ = cv2.minMaxLoc(res)
            locs = np.where(res >= 0.70)
            hits = int(len(locs[0]))
            suspicious = (max_val >= 0.95) or (hits >= 2)
            return {"max": round(float(max_val), 2), "hits": hits, "suspicious": suspicious}
        except Exception as e:
            print("[特征质量] 检测异常:", e)
            return None

    def _interactive_box_select(self, caption, frame, line_w=1):
        """自绘框选(替代cv2.selectROI)：蓝框线宽line_w(1px,比selectROI粗框细一半) + 框好后键盘方向键(↑↓←→)移动整个框位置 + 回车确认/ESC取消。
        返回 (x, y, w, h)，取消返回(0,0,0,0)。坐标=frame内相对坐标。"""
        import cv2 as _cv
        fh, fw = frame.shape[:2]
        state = {"x1": -1, "y1": -1, "x2": -1, "y2": -1, "dragging": False, "moving": False,
                 "cancel": False}
        win = caption
        _cv.namedWindow(win, _cv.WINDOW_NORMAL)
        _cv.moveWindow(win, self.window_rect["left"], self.window_rect["top"])
        _cv.resizeWindow(win, fw, fh)
        _cv.imshow(win, frame)

        def on_mouse(ev, x, y, flags, param):
            s = state
            if s["cancel"]:
                return
            if ev == _cv.EVENT_LBUTTONDOWN:
                s["dragging"] = True
                s["x1"], s["y1"], s["x2"], s["y2"] = x, y, x, y
            elif ev == _cv.EVENT_MOUSEMOVE and s["dragging"]:
                s["x2"], s["y2"] = x, y
            elif ev == _cv.EVENT_LBUTTONUP:
                s["dragging"] = False
            elif ev == _cv.EVENT_RBUTTONDOWN:
                s["cancel"] = True

        _cv.setMouseCallback(win, on_mouse)
        while True:
            disp = frame.copy()
            if state["x2"] >= 0:
                x0, y0 = min(state["x1"], state["x2"]), min(state["y1"], state["y2"])
                x1, y1 = max(state["x1"], state["x2"]), max(state["y1"], state["y2"])
                _cv.rectangle(disp, (int(x0), int(y0)), (int(x1), int(y1)), (255, 0, 0), line_w)  # 蓝框线宽细一半(int取整避免浮点闪退)
                # === 放大镜：画在框边显示"框+周边20px"区域10倍放大(不是只框内)，方便看清框周围(用户2026-9-6) ===
                ri = int(max(0, y0)); rj = int(max(0, x0)); rw = int(x1 - x0); rh = int(y1 - y0)
                _pad = 10  # 框周边10px(用户2026-9-6:改10)
                _gy0 = int(max(0, y0 - _pad)); _gy1 = int(min(fh, y1 + _pad))
                _gx0 = int(max(0, x0 - _pad)); _gx1 = int(min(fw, x1 + _pad))
                if _gx1 > _gx0 and _gy1 > _gy0:
                    _roi = disp[_gy0:_gy1, _gx0:_gx1]  # 取含蓝框的画面(用你画的蓝框一起放大，不另画线)
                    if _roi.shape[0] > 1 and _roi.shape[1] > 1:
                        _zscale = 5
                        _want_w = int((_gx1 - _gx0)) * _zscale
                        _want_h = int((_gy1 - _gy0)) * _zscale
                        _zoom = _cv.resize(_roi, (_want_w, _want_h), interpolation=_cv.INTER_NEAREST)
                        _zh, _zw = _zoom.shape[:2]
                        _zx = int(x1) + 8  # 画在框右边8px(框边上,不远)
                        _zy = int(y0)
                        if _zx + _zw > fw and int(x0) - 8 - _zw >= 0:
                            _zx = int(x0) - 8 - _zw  # 右边超画面则画框左边
                        if _zy + _zh > fh and int(y0) - 8 - _zh >= 0:
                            _zy = int(y0) - 8 - _zh  # 下边超画面则画框上边
                        if _zx + _zw <= fw and _zy + _zh <= fh and _zx >= 0 and _zy >= 0:
                            disp[_zy:_zy+_zh, _zx:_zx+_zw] = _zoom  # 含蓝框的"框+周边10px"一起放大
            _cv.imshow(win, disp)
            k = _cv.waitKey(1)
            kf = k & 0xFF
            if kf == 27 or state["cancel"]:
                state["cancel"] = True
                break
            if kf == 13 and state["x2"] >= 0 and (state["x2"] > state["x1"] or state["y2"] > state["y1"]):
                break
            # 方向键移动整个框位置(框好后键盘↑↓←→平移框)——用GetAsyncKeyState(方向键虚拟码37/38/39/40)比waitKey方向键值可靠
            if state["x2"] >= 0:
                _st = 0.1  # 步长0.1px(用户2026-9-6:调到0.1更精细；int取整保护防闪退)
                # 节流：按住方向键时每0.05s才移一次，避免每秒狂移=太快(用户要精细慢速)
                if not hasattr(state, "_last_arrow_t"):
                    state["_last_arrow_t"] = 0.0
                _now_t = time.time()
                if _now_t - state["_last_arrow_t"] >= 0.05:
                    _vk = {37: (-_st, 0), 39: (_st, 0), 38: (0, -_st), 40: (0, _st)}
                    _moved = False
                    for _code, (_dx, _dy) in _vk.items():
                        if bool(user32.GetAsyncKeyState(_code) & 0x8000):
                            state["x1"] += _dx; state["x2"] += _dx
                            state["y1"] += _dy; state["y2"] += _dy
                            _moved = True
                    if _moved:
                        state["_last_arrow_t"] = _now_t
        _cv.destroyWindow(win)
        if state["cancel"]:
            return (0, 0, 0, 0)
        x0, y0 = min(state["x1"], state["x2"]), min(state["y1"], state["y2"])
        return (int(max(0, x0)), int(max(0, y0)), int(abs(state["x2"] - state["x1"])), int(abs(state["y2"] - state["y1"])))

    def _capture_character_feature(self, direction="right"):
        """人物特征截图：在游戏窗口框选人物身体，保存为特征模板（最多10套）
        direction: "left"=向左的特征, "right"=向右的特征
        使用 cv2.selectROI 内置框选，坐标可靠，无最小尺寸限制（越小越精确）"""
        if self.hwnd is None:
            self._add_log("请先绑定游戏窗口")
            print("[人物特征] 未绑定窗口")
            return

        # 超过上限则先替换最早的一套（框选前删除最旧，保证磁盘和内存都不超10）
        if len(self._char_templates) >= CHAR_MAX_TEMPLATES:
            oldest = self._char_templates.pop(0)
            old_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % oldest["id"])
            if os.path.exists(old_path):
                os.remove(old_path)
            self._add_log("模板已满，替换最早一套")

        self._update_window_rect()
        frame = self._capture_window()
        if frame is None:  # [健壮性2026-09-07] 截图瞬时失败不崩
            self._add_log("截图失败，请重试")
            return
        fh, fw = frame.shape[:2]  # 兼容3通道图shape=(h,w,3)
        if fh <= 0 or fw <= 0:
            self._add_log("截图失败")
            return

        print("[人物特征] 弹出框选窗口，拖拽框选人物身体，回车确认，ESC取消")
        # 自绘框选(蓝框细一半+方向键移动框)
        roi = self._interactive_box_select("Select Character", frame)

        x, y, w, h = roi
        if w <= 0 or h <= 0:
            print("[人物特征] 取消框选")
            return

        captured = frame[y:y + h, x:x + w].copy()

        # 分配新ID（取最大ID+1，空列表从0开始）
        existing_ids = [t["id"] for t in self._char_templates]
        new_id = (max(existing_ids) + 1) if existing_ids else 0
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # 保存到磁盘（用imencode+tofile兼容中文路径，cv2.imwrite中文路径静默失败）
        img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % new_id)
        ok, buf = cv2.imencode(".png", captured)
        if ok:
            buf.tofile(img_path)
            print("[人物特征] 模板已保存:", img_path)
        else:
            self._add_log("人物特征保存失败")
            print("[人物特征] 保存失败: cv2.imencode返回False")

        ch, cw = captured.shape[:2]  # 兼容3通道图shape=(h,w,3)
        # 自动分配颜色（按ID取色，保证不重复）
        feat_color = CHAR_FEATURE_COLORS[new_id % len(CHAR_FEATURE_COLORS)]
        self._char_templates.append({
            "id": new_id,
            "img": captured,
            "width": cw,
            "height": ch,
            "offset_x": 0,   # 默认偏移0，用户在弹窗中校准到人物脚
            "offset_y": 0,
            "color": feat_color,  # 特征颜色，用于蒙板上显示匹配点
            "direction": direction,  # 朝向: left/right
            "created_at": created_at
        })
        self._save_char_meta()

        # 特征点质量检测（用户2026-09-04）：当场标出坏点
        q = self._feature_quality_check(frame, captured, (x, y))
        if q:
            if q["suspicious"]:
                qmsg = "⚠️ 人物特征#%d 质量差：全图最高分%.2f、≥0.70命中%d处 → 疑似背景/重复/撞脸，建议重录(选独有且不变部位)" % (
                    new_id, q["max"], q["hits"])
                self._rlog(qmsg, (200, 0, 0))
                print("[人物特征质量]", qmsg)
                _debug_log("[人物特征质量] " + qmsg)
            else:
                qmsg = "人物特征#%d 质量OK：全图最高分%.2f、≥0.70唯一命中%d处" % (new_id, q["max"], q["hits"])
                self._rlog(qmsg, (0, 180, 0))
                print("[人物特征质量]", qmsg)
                _debug_log("[人物特征质量] " + qmsg)

        dir_name = "向左" if direction == "left" else "向右"
        msg = "人物特征#%d已保存(%s) (%dx%d) 共%d套" % (new_id, dir_name, cw, ch, len(self._char_templates))
        self._add_log(msg)
        print("[人物特征]", msg)
    def _clear_character_features(self):
        """清除所有人物特征模板"""
        count = len(self._char_templates)
        if count == 0:
            self._add_log("没有可清除的特征")
            return
        for t in self._char_templates:
            img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % t["id"])
            if os.path.exists(img_path):
                os.remove(img_path)
        self._char_templates = []
        self._char_feature_matches = []  # 清空蒙板显示的人物特征点，避免全部删除后仍残留旧记录(用户2026-09-05)
        if os.path.exists(CHAR_TEMPLATE_META):
            os.remove(CHAR_TEMPLATE_META)
        self._add_log("已清除 %d 套人物特征" % count)
        print("[特征清除] 已清除 %d 套" % count)

    def _delete_char_template(self, index):
        """删除指定索引的人物特征模板"""
        if index < 0 or index >= len(self._char_templates):
            return
        t = self._char_templates.pop(index)
        img_path = os.path.join(CHAR_TEMPLATE_DIR, "char_%d.png" % t["id"])
        if os.path.exists(img_path):
            os.remove(img_path)
        self._save_char_meta()
        self._add_log("已删除人物特征#%d" % t["id"])
        print("[人物特征] 已删除 #%d" % t["id"])

    # ==================== 怪物特征模板（手动添加，和YOLO合并显示小地图紫点） ====================
    def _load_monster_templates(self):
        """从磁盘加载已保存的怪物特征模板"""
        self._monster_templates = []
        tpl_dir = MONSTER_TEMPLATE_DIR
        if not os.path.exists(tpl_dir):
            print("[怪物特征] 无保存的特征模板，为空")
            return
        # 加载元数据（含偏移、方向）
        meta_list = []
        try:
            if os.path.exists(MONSTER_TEMPLATE_META):
                with open(MONSTER_TEMPLATE_META, "r", encoding="utf-8") as _mf:
                    meta_list = json.load(_mf)
        except Exception:
            meta_list = []
        try:
            for fname in sorted(os.listdir(tpl_dir)):
                if fname.startswith("monster_") and fname.endswith(".png"):
                    try:
                        tid = int(fname.replace("monster_", "").replace(".png", ""))
                    except ValueError:
                        continue
                    img_path = os.path.join(tpl_dir, fname)
                    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape[:2]
                        _off_x = 0
                        _off_y = 0
                        _direction = "right"
                        for _m in meta_list:
                            if _m.get("id") == tid:
                                _off_x = int(_m.get("offset_x", 0))
                                _off_y = int(_m.get("offset_y", 0))
                                _direction = _m.get("direction", "right")
                                break
                        self._monster_templates.append({
                            "id": tid, "img": img, "width": w, "height": h,
                            "offset_x": _off_x, "offset_y": _off_y,
                            "direction": _direction, "created_at": ""
                        })
            print("[怪物特征] 已加载 %d 套模板" % len(self._monster_templates))
        except Exception as e:
            print("[怪物特征] 加载模板失败:", e)

    def _save_monster_meta(self):
        """保存怪物特征模板元数据到磁盘"""
        meta_list = []
        for t in self._monster_templates:
            meta_list.append({
                "id": t["id"], "width": t["width"], "height": t["height"],
                "offset_x": t.get("offset_x", 0), "offset_y": t.get("offset_y", 0),
                "direction": t.get("direction", "right"), "created_at": t["created_at"]
            })
        try:
            with open(MONSTER_TEMPLATE_META, "w", encoding="utf-8") as f:
                json.dump(meta_list, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[怪物特征] 保存元数据失败:", e)

    def _capture_monster_feature(self, direction="right"):
        """怪物特征截图：在游戏窗口框选怪物身体，保存为特征模板（最多10套）"""
        if self.hwnd is None:
            self._add_log("请先绑定游戏窗口")
            print("[怪物特征] 未绑定窗口")
            return
        if len(self._monster_templates) >= MONSTER_MAX_TEMPLATES:
            oldest = self._monster_templates.pop(0)
            old_path = os.path.join(MONSTER_TEMPLATE_DIR, "monster_%d.png" % oldest["id"])
            if os.path.exists(old_path):
                os.remove(old_path)
            self._add_log("怪物模板已满，替换最早一套")
        self._update_window_rect()
        frame = self._capture_window()
        if frame is None:  # [健壮性2026-09-07] 截图瞬时失败不崩
            self._add_log("截图失败，请重试")
            return
        fh, fw = frame.shape[:2]
        if fh <= 0 or fw <= 0:
            self._add_log("截图失败")
            return
        print("[怪物特征] 弹出框选窗口，拖拽框选怪物身体，回车确认，ESC取消")
        # 自绘框选(蓝框细一半+方向键移动框)
        roi = self._interactive_box_select("Select Monster", frame)
        x, y, w, h = roi
        if w <= 0 or h <= 0:
            print("[怪物特征] 取消框选")
            return
        captured = frame[y:y + h, x:x + w].copy()
        existing_ids = [t["id"] for t in self._monster_templates]
        new_id = (max(existing_ids) + 1) if existing_ids else 0
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        img_path = os.path.join(MONSTER_TEMPLATE_DIR, "monster_%d.png" % new_id)
        ok, buf = cv2.imencode(".png", captured)
        if ok:
            buf.tofile(img_path)
            print("[怪物特征] 模板已保存:", img_path)
        else:
            self._add_log("怪物特征保存失败")
        ch, cw = captured.shape[:2]
        self._monster_templates.append({
            "id": new_id, "img": captured, "width": cw, "height": ch,
            "offset_x": 0, "offset_y": 0, "direction": direction, "created_at": created_at
        })
        self._save_monster_meta()
        # 特征点质量检测（用户2026-09-04）：当场标出坏点
        q = self._feature_quality_check(frame, captured, (x, y))
        if q:
            if q["suspicious"]:
                qmsg = "⚠️ 怪物特征#%d 质量差：全图最高分%.2f、≥0.70命中%d处 → 疑似背景/重复/撞脸，建议重录(选独特部位)" % (
                    new_id, q["max"], q["hits"])
                self._rlog(qmsg, (200, 0, 0))
                print("[怪物特征质量]", qmsg)
                _debug_log("[怪物特征质量] " + qmsg)
            else:
                qmsg = "怪物特征#%d 质量OK：全图最高分%.2f、≥0.70唯一命中%d处" % (new_id, q["max"], q["hits"])
                self._rlog(qmsg, (0, 180, 0))
                print("[怪物特征质量]", qmsg)
                _debug_log("[怪物特征质量] " + qmsg)

        dir_name = "向左" if direction == "left" else "向右"
        msg = "怪物特征#%d已保存(%s) (%dx%d) 共%d套" % (new_id, dir_name, cw, ch, len(self._monster_templates))
        self._add_log(msg)
        print("[怪物特征]", msg)

    def _clear_monster_features(self):
        """清除所有怪物特征模板"""
        count = len(self._monster_templates)
        if count == 0:
            self._add_log("没有可清除的怪物特征")
            return
        for t in self._monster_templates:
            img_path = os.path.join(MONSTER_TEMPLATE_DIR, "monster_%d.png" % t["id"])
            if os.path.exists(img_path):
                os.remove(img_path)
        self._monster_templates = []
        if os.path.exists(MONSTER_TEMPLATE_META):
            os.remove(MONSTER_TEMPLATE_META)
        self._add_log("已清除 %d 套怪物特征" % count)
        print("[怪物特征] 已清除 %d 套" % count)

    def _delete_monster_template(self, index):
        """删除指定索引的怪物特征模板"""
        if index < 0 or index >= len(self._monster_templates):
            return
        t = self._monster_templates.pop(index)
        img_path = os.path.join(MONSTER_TEMPLATE_DIR, "monster_%d.png" % t["id"])
        if os.path.exists(img_path):
            os.remove(img_path)
        self._save_monster_meta()
        self._monster_feature_matches = []  # 删除特征后清空匹配结果，避免旧点继续显示
        self._monsters = []  # 删除特征后也清空小地图怪物点，避免旧点继续显示
        self._add_log("已删除怪物特征#%d" % t["id"])
        print("[怪物特征] 已删除 #%d")

    # ==================== 梯子特征模板（随方案永久存盘，仅上梯近距匹配竖条X，辅助精准起跳；YOLO前过渡） ====================
    def _ladder_tpl_path(self, route_id):
        """梯子特征永久文件：随方案，和平台/梯子蓝线等 route 文件并列，一个地图(方案)一份"""
        return os.path.join(DATA_DIR, "route_%03d_ladder_tpl.json" % route_id)

    def _load_ladder_templates(self, route_id):
        """从方案永久文件加载梯子特征到运行时副本（重开脚本/切换方案/导入都调它）"""
        self._ladder_templates = []
        self._ladder_tpl_sim = LADDER_TPL_DEFAULT_SIM
        p = self._ladder_tpl_path(route_id)
        if not os.path.exists(p):
            print("[梯子特征] 方案%d 无梯子模板，为空" % route_id)
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            self._ladder_tpl_sim = float(d.get("sim", LADDER_TPL_DEFAULT_SIM))
            for it in d.get("templates", []):
                try:
                    buf = np.frombuffer(base64.b64decode(it["img_b64"]), dtype=np.uint8)
                    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape[:2]
                        self._ladder_templates.append({"id": it.get("id", 0), "img": img, "width": w, "height": h})
                except Exception as _e:
                    print("[梯子特征] 单张解码失败:", _e)
            print("[梯子特征] 方案%d 已加载 %d 套, 相似度%.2f" % (route_id, len(self._ladder_templates), self._ladder_tpl_sim))
        except Exception as e:
            print("[梯子特征] 加载失败:", e)

    def _save_ladder_templates(self, route_id=None):
        """把运行时梯子模板永久写回方案文件（捕获/删/清/F8保存都即时落盘，关机不丢）"""
        rid = self.current_route if route_id is None else route_id
        out = []
        for t in self._ladder_templates:
            _ok, _buf = cv2.imencode(".png", t["img"])
            if _ok:
                out.append({"id": t.get("id", 0), "width": t.get("width", 0), "height": t.get("height", 0),
                            "img_b64": base64.b64encode(_buf).decode("utf-8")})
        try:
            with open(self._ladder_tpl_path(rid), "w", encoding="utf-8") as f:
                json.dump({"templates": out, "count": len(out),
                           "sim": getattr(self, '_ladder_tpl_sim', LADDER_TPL_DEFAULT_SIM)},
                          f, ensure_ascii=False, indent=2)
            print("[梯子特征] 方案%d 永久保存 %d 套" % (rid, len(out)))
        except Exception as e:
            print("[梯子特征] 保存失败:", e)

    def _capture_ladder_feature(self):
        """框选梯子/绳索竖条样式存为特征(只用其X)，捕获即永久写入当前方案文件"""
        if self.hwnd is None:
            self._add_log("请先绑定游戏窗口")
            return
        if len(self._ladder_templates) >= LADDER_TPL_MAX:
            self._ladder_templates.pop(0)
            self._add_log("梯子模板已满，替换最早一套")
        self._update_window_rect()
        frame = self._capture_window()
        if frame is None:
            self._add_log("截图失败，请重试")
            return
        print("[梯子特征] 弹出框选：拖拽框住整根绳索/梯子竖条，回车确认，ESC取消")
        x, y, w, h = self._interactive_box_select("Select Ladder", frame)
        if w <= 0 or h <= 0:
            print("[梯子特征] 取消框选")
            return
        cap = frame[y:y + h, x:x + w].copy()
        ids = [t["id"] for t in self._ladder_templates]
        new_id = (max(ids) + 1) if ids else 0
        ch, cw = cap.shape[:2]
        self._ladder_templates.append({"id": new_id, "img": cap, "width": cw, "height": ch})
        self._save_ladder_templates(self.current_route)
        self._add_log("梯子特征#%d已保存(%dx%d) 共%d套，已存入方案%d" % (
            new_id, cw, ch, len(self._ladder_templates), self.current_route))
        print("[梯子特征] #%d 已存 %dx%d，共%d套" % (new_id, cw, ch, len(self._ladder_templates)))

    def _delete_ladder_template(self, index):
        if 0 <= index < len(self._ladder_templates):
            t = self._ladder_templates.pop(index)
            self._save_ladder_templates(self.current_route)
            self._add_log("已删除梯子特征#%d" % t["id"])

    def _clear_ladder_templates(self):
        n = len(self._ladder_templates)
        self._ladder_templates = []
        try:
            p = self._ladder_tpl_path(self.current_route)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
        self._add_log("已清除 %d 套梯子特征" % n)
        print("[梯子特征] 已清除 %d 套" % n)

    def _match_ladder_screen_x(self, frame, ppos, direction, monster_x):
        """上梯近距在主窗口定向ROI匹配梯子竖条，只返回最佳梯子中心屏幕X(不要Y)。
        X:只朝目标怪那一侧扩LADDER_TPL_X_RANGE(怪在右只搜右/在左只搜左;无怪方位左右各150兜底);
        Y:上行搜人物头顶(-150~-20)、下行搜脚下(+20~+150),防止一上一下两把相邻梯认错;
        同侧匹配到多把梯子时,选X最贴近目标怪X的那把(用户2026-09-09)。"""
        if not self._ladder_templates or frame is None or ppos is None:
            return None
        fh, fw = frame.shape[:2]
        ppx, ppy = int(ppos[0]), int(ppos[1])
        if monster_x is None:
            rx1, rx2 = ppx - LADDER_TPL_X_RANGE, ppx + LADDER_TPL_X_RANGE
        elif monster_x >= ppx:
            rx1, rx2 = ppx, ppx + LADDER_TPL_X_RANGE          # 怪在右:只搜右侧
        else:
            rx1, rx2 = ppx - LADDER_TPL_X_RANGE, ppx           # 怪在左:只搜左侧
        if direction is not None and direction < 0:
            ry1, ry2 = ppy + LADDER_TPL_Y_NEAR, ppy + LADDER_TPL_Y_FAR   # 下行:脚下
        else:
            ry1, ry2 = ppy - LADDER_TPL_Y_FAR, ppy - LADDER_TPL_Y_NEAR   # 上行:头顶
        x1 = max(0, rx1)
        y1 = max(DETECT_TOP_MARGIN, ry1)
        x2 = min(fw, rx2)
        y2 = min(fh - DETECT_BOTTOM_MARGIN, ry2)
        if x2 - x1 <= 5 or y2 - y1 <= 5:
            return None
        crop = frame[y1:y2, x1:x2]
        ch, cw = crop.shape[:2]
        _sim = float(getattr(self, '_ladder_tpl_sim', LADDER_TPL_DEFAULT_SIM) or LADDER_TPL_DEFAULT_SIM)
        cands = []
        for tpl in self._ladder_templates:
            timg = tpl["img"]
            th, tw = timg.shape[:2]
            if th > ch or tw > cw:
                continue
            res = cv2.matchTemplate(crop, timg, cv2.TM_CCOEFF_NORMED)
            mval = float(res.max())
            if mval >= _sim:
                _, _, _, maxloc = cv2.minMaxLoc(res)
                cx = x1 + maxloc[0] + tw // 2
                cands.append((cx, mval))
        if not cands:
            self._ladder_tpl_matches = []
            return None
        if monster_x is not None:
            cands.sort(key=lambda c: abs(c[0] - monster_x))   # 同侧多梯:X最贴近怪
        else:
            cands.sort(key=lambda c: -c[1])                   # 无怪方位:置信度最高
        self._ladder_tpl_matches = cands[:4]
        return cands[0][0]

    def _ladder_align_by_screen(self, tpl_x, px, py, now_ms, jump_key):
        """主窗口梯子竖条X对齐起跳(屏幕坐标,比小地图光点准;用户2026-09-09)。
        屏幕差>6按住朝梯、≤6非阻塞点动、≤2连续2帧原地直跳;点动后屏幕X没靠近=想动没动,解卡超限回主线不死磕。"""
        _sp = self._player_screen_pos
        if _sp is None:
            return False
        spx = int(_sp[0])
        sdx = tpl_x - spx                       # 正=梯子在屏幕右侧
        asdx = abs(sdx)
        _ak = getattr(self, '_lad_scr_key_vk', None)
        if _ak is not None and now_ms - getattr(self, '_lad_scr_key_t', 0) >= LADDER_NUDGE_KEY_MS:
            self._key_up(_ak)
            self._lad_scr_key_vk = None
            _ak = None
        if asdx > LADDER_SCR_NUDGE:
            if _ak is not None:
                self._key_up(_ak)
                self._lad_scr_key_vk = None
            self._lad_scr_ok_frames = 0
            self._lad_scr_stall_t = 0
            self._lad_scr_stall_n = 0
            self._hold_toward_ladder(sdx)
            return False
        _dir_vk = VK_RIGHT if sdx > 0 else VK_LEFT
        _opp_vk = VK_LEFT if sdx > 0 else VK_RIGHT
        if asdx <= LADDER_SCR_TOL:
            if _ak is not None:
                self._key_up(_ak)
                self._lad_scr_key_vk = None
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            self._lad_scr_ok_frames = getattr(self, '_lad_scr_ok_frames', 0) + 1
            if self._lad_scr_ok_frames >= LADDER_SCR_HOLD_FRAMES and not getattr(self, '_ladder_vert_jumped', False):
                self._ladder_vert_jumped = True
                self._climb_start_y = py
                self._press_game_key(jump_key, duration=80)
                _debug_log("[爬梯·屏幕] 梯X=%d 人X=%d 差%.1f 连续%d帧→原地直跳抓梯" % (
                    tpl_x, spx, sdx, self._lad_scr_ok_frames))
                self._rlog("屏幕对齐梯子(X差%.1f)直跳抓梯" % sdx, log='behavior')
                self._ladder_jump_phase = 'post_jump'
                self._ladder_post_jump_step = 'delay1'
                self._ladder_post_jump_t = now_ms
            return False
        self._lad_scr_ok_frames = 0
        if now_ms - getattr(self, '_lad_scr_nudge_t', 0) >= LADDER_NUDGE_CYCLE_MS:
            _ref = getattr(self, '_lad_scr_ref_spx', None)
            if _ref is not None:
                _prev_gap = abs(tpl_x - _ref)
                if asdx < _prev_gap - 0.5:
                    self._lad_scr_stall_t = 0
                    self._lad_scr_stall_n = 0
                else:
                    if self._lad_scr_stall_t == 0:
                        self._lad_scr_stall_t = now_ms
                    elif now_ms - self._lad_scr_stall_t >= LADDER_SCR_STALL_MS:
                        self._lad_scr_stall_n += 1
                        self._lad_scr_stall_t = now_ms
                        if self._lad_scr_stall_n > LADDER_SCR_STALL_MAX:
                            self._rlog("屏幕对齐梯子卡住,回主线重选(不死磕)", LOG_RED, log='behavior')
                            self._key_up(VK_LEFT)
                            self._key_up(VK_RIGHT)
                            self._reset_climb()
                            self._decide_climb_fail_action()
                            return False
            self._key_up(_opp_vk)
            if getattr(self, '_lad_scr_key_vk', None) is None:
                self._key_down(_dir_vk)
                self._lad_scr_key_vk = _dir_vk
                self._lad_scr_key_t = now_ms
            self._lad_scr_nudge_t = now_ms
            self._lad_scr_ref_spx = spx
            self._rlog_throttle('lad_scr', "屏幕精对梯子(梯在%s,X差%.1f点动)" % (
                "右" if sdx > 0 else "左", asdx), 500, log='behavior')
        return False

    # ==================== 爬梯登顶·绑定人物基点的三背景点（右上/右下/左下，随人移动不出屏，任一静即静） ====================
    def _pick_climb_boxes(self, ppos, fh, fw):
        """选三个背景采样点中心:右上/右下/左下,距人物CLIMB_BOX_RADIUS;clamp收边保证永不出屏(贴边时收回人物另一侧);
        尽量躲开怪物框、且三点彼此分离,保证总有干净背景点。返回[(cx,cy)]x3(整像素)。"""
        ppx, ppy = int(ppos[0]), int(ppos[1])
        hs = CLIMB_BOX_SIZE // 2
        R = CLIMB_BOX_RADIUS
        xL, xR = hs, fw - hs
        yT, yB = DETECT_TOP_MARGIN + hs, fh - DETECT_BOTTOM_MARGIN - hs

        def clamp(cx, cy):
            return min(max(cx, xL), xR), min(max(cy, yT), yB)

        def on_monster(cx, cy):
            for m in (getattr(self, '_monsters', None) or []):
                try:
                    if cx - hs < m[2] and cx + hs > m[0] and cy - hs < m[3] and cy + hs > m[1]:
                        return True
                except Exception:
                    continue
            return False

        ideal = [(ppx + R, ppy - R), (ppx + R, ppy + R), (ppx - R, ppy + R)]  # 右上/右下/左下
        chosen = []
        for ix, iy in ideal:
            cx, cy = clamp(ix, iy)
            bad = on_monster(cx, cy) or any(abs(cx - q[0]) + abs(cy - q[1]) < CLIMB_BOX_SEP_MIN for q in chosen)
            if bad:
                # 由近及远找一个"不罩怪、与已选点分离"的最近替代位
                best = None
                for step in range(0, R + 1, 15):
                    for ddx in (-step, 0, step) if step else (0,):
                        for ddy in (-step, 0, step) if step else (0,):
                            tx, ty = clamp(cx + ddx, cy + ddy)
                            if on_monster(tx, ty):
                                continue
                            if any(abs(tx - q[0]) + abs(ty - q[1]) < CLIMB_BOX_SEP_MIN for q in chosen):
                                continue
                            d = abs(tx - cx) + abs(ty - cy)
                            if best is None or d < best[0]:
                                best = (d, tx, ty)
                    if best is not None:
                        break
                if best is not None:
                    cx, cy = best[1], best[2]
            chosen.append((cx, cy))
        return chosen

    def _climb_boxes_still(self, frame, centers):
        """三点在各自当前位置取小ROI与上一帧纹理比,返回(静止点数n_still,有效点数n_valid)。
        锚点突变(换角/收边位移>2px)或首帧该点只建基准、不计静也不计动。"""
        if frame is None:
            return 0, 0
        n_still = 0
        n_valid = 0
        hs = CLIMB_BOX_SIZE // 2
        for i, (cx, cy) in enumerate(centers):
            if i >= len(self._climb_box_prev):
                break
            roi = frame[cy - hs:cy + hs, cx - hs:cx + hs]
            if roi.size == 0:
                continue
            prev = self._climb_box_prev[i]
            pc = self._climb_box_centers[i]
            anchor_jump = pc is not None and (abs(pc[0] - cx) > 2 or abs(pc[1] - cy) > 2)
            self._climb_box_centers[i] = (cx, cy)
            self._climb_box_prev[i] = roi.copy()
            if anchor_jump or prev is None or prev.shape != roi.shape:
                continue
            n_valid += 1
            if float(cv2.absdiff(roi, prev).mean()) <= BG_DIFF_THRESHOLD:
                n_still += 1
        return n_still, n_valid

    # _player_track_loop已删除
    def _char_three_score(self, tpl, region):
        """三维度加权平均分(0~1)：颜色+形状+亮度。对少数候选点算(快,不影响帧率)。
        权重0.4颜色(色度H/S去亮度,容光照)+0.4形状(灰度归一化互相关,对亮度不敏感)+0.2亮度(平均亮度差容差)。
        分高=该候选点颜色/形状/亮度都对→位置可信；用于选生效特征(取三维分最高的那个)。
        """
        if tpl is None or region is None or region.shape[:2] != tpl.shape[:2]:
            return 0.0
        # 颜色(色度H/S，去亮度)
        t_h = cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV).astype(np.float32)
        r_h = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).astype(np.float32)
        dh = np.abs(t_h[..., 0] - r_h[..., 0]); dh = np.minimum(dh, 180 - dh) / 180.0
        ds = np.abs(t_h[..., 1] - r_h[..., 1]) / 255.0
        color = max(0.0, min(1.0, 1.0 - (0.6 * dh + 0.4 * ds).mean()))
        # 形状(灰度归一化互相关)
        tg = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY).astype(np.float32)
        rg = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
        tm = tg - tg.mean(); rm = rg - rg.mean()
        ncc = float((tm * rm).sum() / ((np.sqrt((tm*tm).sum()) * np.sqrt((rm*rm).sum())) + 1e-9))
        shape = max(0.0, min(1.0, (ncc + 1.0) / 2.0))
        # 亮度(平均亮度差容差)
        luma = max(0.0, min(1.0, 1.0 - abs(tg.mean() - rg.mean()) / 50.0))
        return 0.40 * color + 0.40 * shape + 0.20 * luma

    def _findpic(self, screen, template, sim=0.7, delta=30):
        """大漠FindPic+国际边缘匹配升级：原尺寸模板匹配 + 偏色容差 + 边缘/梯度匹配(抗光照变化/部分遮挡，参考国外edge-based法)。
        定位=cv2.matchTemplate(CCOEFF)取最高分；偏色=候选像素BGR差<=delta占比；边缘=Sobel梯度归一化相似度(对光照/遮挡鲁棒)。
        返回 (相似度, 命中中心x, y) 或 (None,None,None)。"""
        if screen is None or template is None:
            return (None, None, None)
        th, tw = template.shape[:2]
        if th > screen.shape[0] or tw > screen.shape[1]:
            return (None, None, None)
        res = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, mx, _, ml = cv2.minMaxLoc(res)
        if mx < sim:
            return (None, None, None)
        cx = ml[0] + tw // 2
        cy = ml[1] + th // 2
        top_l = (ml[1], ml[0])
        reg = screen[top_l[0]:top_l[0]+th, top_l[1]:top_l[1]+tw]
        if reg.shape[:2] != (th, tw):
            return (None, None, None)
        # 偏色容差(抗光照/抗锯齿)确认：候选像素BGR差<=delta占比足够=命中(边缘Sobel费时已去掉，用户2026-9-6)
        diff = np.abs(reg.astype(np.int16) - template.astype(np.int16))
        ratio = float((diff <= delta).all(axis=2).mean())
        if ratio >= 0.5:
            return (mx, cx, cy)
        return (None, None, None)

    def _color_ratio_confirm(self, screen, top_y, top_x, template, delta=30):
        """彩色偏色容差确认：候选区与模板逐像素BGR差<=delta的占比(大漠相似度语义)。快速版用它做彩色把关。"""
        th, tw = template.shape[:2]
        reg = screen[top_y:top_y + th, top_x:top_x + tw]
        if reg.shape[:2] != (th, tw):
            return 0.0
        diff = np.abs(reg.astype(np.int16) - template.astype(np.int16))
        return float((diff <= delta).all(axis=2).mean())

    def _findpic_roi_fast(self, screen, template, sim=0.7, delta=30):
        """【ROI快速版 2026-09-07 识图算法优化】人物就在上一帧±200小范围内，用R单通道做CCOEFF_NORMED
        (实测比3通道彩色快约3.3倍：400x400区域34.6ms->9.6ms)，再用彩色偏色容差二次确认，防R通道在
        背景纹理上误配。返回值与_findpic完全一致：(分数,中心x,中心y)或(None,None,None)，坐标相对传入screen。
        依据：3个人物模板主色为红/橙/黄(meta color的R=255)，真人帧R通道与彩色定位Δ0、分数0.947vs0.949一致。"""
        if screen is None or template is None:
            return (None, None, None)
        th, tw = template.shape[:2]
        if th > screen.shape[0] or tw > screen.shape[1]:
            return (None, None, None)
        res = cv2.matchTemplate(screen[:, :, 2], template[:, :, 2], cv2.TM_CCOEFF_NORMED)
        _, mx, _, ml = cv2.minMaxLoc(res)
        if mx < sim:
            return (None, None, None)
        if self._color_ratio_confirm(screen, ml[1], ml[0], template, delta) < 0.5:
            return (None, None, None)
        return (mx, ml[0] + tw // 2, ml[1] + th // 2)

    def _findpic_full_fast(self, screen, template, sim=0.7, delta=30, top_k=6, refine=14):
        """【全图级联版 2026-09-07 识图算法优化】人物丢失/瞬移时全图兜底搜索，两级级联兼顾速度与准度：
        第一级 R单通道全图CCOEFF_NORMED快速粗筛(比彩色快约3.3倍)，取top_k个局部候选峰(非极大抑制)；
        第二级 只对每个候选±refine的极小邻域跑原彩色CCOEFF_NORMED精验，取彩色分最高且>=sim者，再彩色偏色确认。
        实测：真人R粗分0.95必进候选、彩色精验分与纯彩色浮点一致；背景R假峰(0.71~0.88)在彩色精验下12个拦11，
        最终准度等同纯彩色全图，而3模板全图耗时171ms->约55ms。返回值与_findpic一致，坐标相对传入screen。"""
        if screen is None or template is None:
            return (None, None, None)
        th, tw = template.shape[:2]
        H, W = screen.shape[:2]
        if th > H or tw > W:
            return (None, None, None)
        # 第一级：R通道粗筛，非极大抑制取 top_k 候选左上角
        res = cv2.matchTemplate(screen[:, :, 2], template[:, :, 2], cv2.TM_CCOEFF_NORMED)
        suppr = max(th, tw)
        work = res.copy()
        cand_tops = []
        for _ in range(top_k):
            _, rv, _, rl = cv2.minMaxLoc(work)
            if rv < 0.5:  # R粗分已低，后面更低，提前结束（真人通常0.9+）
                break
            cand_tops.append(rl)  # (x, y) 候选左上角
            work[max(0, rl[1] - suppr):rl[1] + suppr, max(0, rl[0] - suppr):rl[0] + suppr] = -1.0
        # 第二级：每个候选小邻域彩色精验，取彩色分最高
        best = None  # (彩色分, 绝对左上角x, 绝对左上角y)
        for (lx, ly) in cand_tops:
            x0, y0 = max(0, lx - refine), max(0, ly - refine)
            x1, y1 = min(W, lx + tw + refine), min(H, ly + th + refine)
            patch = screen[y0:y1, x0:x1]
            if patch.shape[0] < th or patch.shape[1] < tw:
                continue
            rr = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
            _, cv_, _, cl = cv2.minMaxLoc(rr)
            ax, ay = x0 + cl[0], y0 + cl[1]  # 精验命中点映射回全图绝对左上角
            if best is None or cv_ > best[0]:
                best = (float(cv_), ax, ay)
        if best is None:
            return (None, None, None)
        cv_, ax, ay = best
        if cv_ < sim:
            return (None, None, None)
        if self._color_ratio_confirm(screen, ay, ax, template, delta) < 0.5:
            return (None, None, None)
        return (cv_, ax + tw // 2, ay + th // 2)

    def _match_character(self, frame):
        """【多特征融合】在游戏画面中用多个特征模板匹配查找人物脚位置（2026-09-07重构，治瞬移后点钉原地）
        1. ROI优先：有上次位置且非瞬移relocate窗口时，先在原地±200(400x400)内匹配，达标就近采信（省算力、稳）
        2. ROI无达标 / 刚瞬移：立即全图匹配（不等待），全图允许离上次很远也同步（瞬移/走远是合法大位移）
           - ≥2个特征在同一处(≤50px)一致命中：按置信度加权平均，最可信
           - 仅1个特征：常态远距要求≥0.75防误配；瞬移relocate窗口内≥0.70即采信
        3. 都没达标返回None（输出层_get_player_screen_pos让点停在最后消失位置，后台每帧继续全图搜直到找回）
        Returns:
            (foot_x, foot_y, confidence) 或 None
        """
        if not self._char_templates or frame is None:
            if not self._char_templates:
                _now = time.time()
                if not hasattr(self, '_last_no_tpl_log') or _now - self._last_no_tpl_log > 5:
                    self._last_no_tpl_log = _now
                    print("[人物匹配] 没有人物特征模板，请先在人物特征弹窗中添加")
            return None
        fh, fw = frame.shape[:2]

        # === ROI优先：有上次位置时先在400x400范围内匹配，大幅减少matchTemplate耗时 ===
        predictions = []  # [(foot_x, foot_y, confidence, tpl_id, direction, source), ...]
        last_pos = getattr(self, "_last_char_match_pos", None)  # 脚位置（偏移后），ROI用这个做中心
        _now_ms = time.time() * 1000
        # 刚瞬移后的relocate窗口：人物合法跳走几百px，ROI(原地附近)必搜不到→跳过ROI直接全图，第一时间重定位
        _force_full = _now_ms < getattr(self, '_char_relocate_until', 0)
        if last_pos and not _force_full:
            lx, ly = last_pos  # ROI中心=脚位置（偏移后）
            roi_half = 200  # 400x400范围
            rx1 = max(0, lx - roi_half)
            ry1 = max(0, ly - roi_half)  # 上下各200，400x400
            rx2 = min(fw, lx + roi_half)
            ry2 = min(fh, ly + roi_half)
            roi = frame[ry1:ry2, rx1:rx2]
            if roi.shape[0] > 20 and roi.shape[1] > 20:
                self._char_match_roi_rect = (rx1, ry1, rx2, ry2)  # 保存ROI范围用于蒙板显示绿框
                for tpl in self._char_templates:
                    # 大漠FindPic复刻：模板图+多档缩放+相似度>=sim才算命中(一模一样的找图方式)
                    timg = tpl['img']
                    th, tw = timg.shape[:2]
                    if th > roi.shape[0] or tw > roi.shape[1]:
                        continue
                    _score, _cx, _cy = self._findpic_roi_fast(roi, timg, sim=float(self._match_sim.get("char", "0.70")))
                    if _score is None:
                        continue
                    max_val = _score
                    feat_cx = rx1 + _cx
                    feat_cy = ry1 + _cy
                    # ROI匹配详细日志（每2秒一次，看每个特征在ROI内的分数）
                    _now_roi_d = time.time()
                    if not hasattr(self, "_last_roi_detail_log") or _now_roi_d - self._last_roi_detail_log > 2:
                        self._last_roi_detail_log = _now_roi_d
                        print("[ROI详细] 特征%d 方向=%s ROI范围=(%d,%d,%d,%d) 找图分=%.3f" % (tpl["id"], tpl.get("direction","?"), rx1, ry1, rx2, ry2, max_val))
                    foot_x = feat_cx + int(tpl.get('offset_x', 0))
                    foot_y = feat_cy + int(tpl.get('offset_y', 0))
                    predictions.append((foot_x, foot_y, max_val, tpl['id'], tpl.get('direction', 'right'), 'roi'))

        # ROI匹配诊断日志（每2秒一次，看ROI是否生效）
        _now_roi = time.time()
        if not hasattr(self, "_last_roi_log") or _now_roi - self._last_roi_log > 2:
            self._last_roi_log = _now_roi
            _has_last = 1 if last_pos else 0
            _roi_ok = 1 if (last_pos and predictions) else 0
            _full_ok = 1 if (not last_pos and predictions) else 0
            print("[ROI诊断] 有上次位置=%d ROI匹配成功=%d 全图匹配成功=%d 预测数=%d" % (_has_last, _roi_ok, _full_ok, len(predictions)))

        # === ROI匹配失败或无上次位置 且 没有≥0.70可信预测：全图匹配所有特征（固定识别范围3,30到1365,738，减少匹配面积）===
        # 注意：ROI内0.40~0.69的低分命中不算可信，否则会把全图兜底挡住（人物丢失就永远找不回）——2026-09-04修复
        if not any(p[2] >= CHAR_MATCH_THRESHOLD for p in predictions):
            # 游戏画面识别范围：写死固定窗口尺寸 GAME_W x GAME_H(1276x749，用户定稿不要动态识别，窗口变大也会被拉回，避免识别范围随窗口漂移)
            _ccx1, _ccy1 = 3, DETECT_TOP_MARGIN
            _cfh, _cfw = frame.shape[:2]
            _ccx2, _ccy2 = min(GAME_W, _cfw), min(GAME_H, _cfh)  # 固定容量到 1368x800，不超 frame
            _ccy2 = max(_ccy1 + 1, _ccy2 - DETECT_BOTTOM_MARGIN)  # 底部去90(HP/MP/EXP+技能栏+聊天UI),统一固定识别带(2026-09-09前仅去40)
            _full_frame = frame[_ccy1:_ccy2, _ccx1:_ccx2] if _ccx2 > _ccx1 and _ccy2 > _ccy1 else frame
            _ffh, _ffw = _full_frame.shape[:2]
            for tpl in self._char_templates:
                # 大漠FindPic复刻：模板图+多档缩放+相似度>=sim才算命中(一模一样的找图方式)
                timg = tpl['img']
                th, tw = timg.shape[:2]
                if th > _ffh or tw > _ffw:
                    continue
                _score, _cx, _cy = self._findpic_full_fast(_full_frame, timg, sim=float(self._match_sim.get("char", "0.70")))
                if _score is None:
                    continue
                max_val = _score
                feat_cx = _cx + _ccx1
                feat_cy = _cy + _ccy1
                foot_x = feat_cx + int(tpl.get('offset_x', 0))
                foot_y = feat_cy + int(tpl.get('offset_y', 0))
                predictions.append((foot_x, foot_y, max_val, tpl['id'], tpl.get('direction', 'right'), 'full'))

        # 只显示"达标"(分数≥阈值)的特征点，不显示没识别到(低分/错位)的特征；没匹配到达标点则清空消失(用户2026-09-05)
        _ok_all = [p for p in predictions if p[2] >= CHAR_ROI_THRESHOLD]
        self._char_feature_matches = [(p[0], p[1], p[3], p[2]) for p in _ok_all]

        if not _ok_all:
            # ROI+全图都没达标 → 本帧找不到（输出层让点停在最后消失位置，后台下一帧继续全图搜，搜到立即同步）
            _now = time.time()
            if not hasattr(self, '_last_lowscore_log') or _now - self._last_lowscore_log > 5:
                self._last_lowscore_log = _now
                _debug_log("[人物匹配] ROI+全图都未达标，特征%d套（点保持最后位置，继续全图搜）" % len(self._char_templates))
            return None

        # === 决策1：ROI内达标候选（原地±200小范围，最可靠）→ 就近采信，不再做150px跳变拒绝(ROI内本就是原地附近) ===
        _roi_ok = [p for p in _ok_all if p[5] == 'roi']
        if _roi_ok and not _force_full:
            if last_pos:
                best = min(_roi_ok, key=lambda p: (p[0] - last_pos[0]) ** 2 + (p[1] - last_pos[1]) ** 2)
            else:
                best = max(_roi_ok, key=lambda p: p[2])
            self._last_char_match_pos = (best[0], best[1])
            self._last_char_match_time = time.time() * 1000
            _debug_log("[人物匹配] ROI就近 特征#%d 分%.3f 基点(%d,%d)" % (best[3], best[2], best[0], best[1]))
            return (best[0], best[1], 1.0)

        # === 决策2：全图达标候选（人物走远/瞬移/切屏，允许离上次很远也要立即同步——2026-09-07治瞬移后点钉原地）===
        _full_ok = [p for p in _ok_all if p[5] == 'full'] or _ok_all
        # 多特征一致性融合：以最高分候选为锚，聚拢与其≤50px的候选，按置信度加权平均（≥2个一致=高可信，抗单模板误配）
        anchor = max(_full_ok, key=lambda p: p[2])
        cluster = [p for p in _full_ok if float(np.hypot(p[0] - anchor[0], p[1] - anchor[1])) <= 50]
        if len(cluster) >= 2:
            _w = np.array([p[2] for p in cluster], dtype=np.float64)
            _w = _w / _w.sum()
            fx = int(round(sum(p[0] * w_ for p, w_ in zip(cluster, _w))))
            fy = int(round(sum(p[1] * w_ for p, w_ in zip(cluster, _w))))
            best = (fx, fy, float(max(p[2] for p in cluster)), anchor[3], anchor[4], 'full')
        else:
            # 仅单特征：常态远距要求0.75高门槛防误配到怪/别的玩家；刚瞬移relocate窗口内0.70即采信(主动瞬移、预期跳走)
            _single_min = CHAR_MATCH_THRESHOLD if _force_full else 0.75
            if anchor[2] < _single_min:
                _debug_log("[人物匹配] 全图单特征分%.3f<%.2f，远距暂不采信，等更稳匹配" % (anchor[2], _single_min))
                return None
            best = anchor
        self._last_char_match_pos = (best[0], best[1])
        self._last_char_match_time = time.time() * 1000
        _jump = int(np.hypot(best[0] - last_pos[0], best[1] - last_pos[1])) if last_pos else 0
        _debug_log("[人物匹配] 全图重定位 特征#%d 分%.3f 基点(%d,%d) 距上次%dpx%s" % (
            best[3], best[2], best[0], best[1], _jump, "（瞬移同步）" if _force_full else ""))
        return (best[0], best[1], 1.0)

    def _match_monster(self, frame, crop_rect=None):
        """【怪物特征多目标匹配】在游戏画面中用怪物特征模板匹配查找所有怪物
        1. 全图匹配所有特征，收集所有超过阈值的匹配位置
        2. 非极大值抑制（距离太近的合并，保留置信度最高的）
        3. 返回怪物框列表 [(x1, y1, x2, y2, score), ...]
        优化：方向过滤（只匹配当前朝向的特征），ROI优先（在上次位置附近匹配）
        crop_rect: (x1,y1,x2,y2) 限定匹配区域（人物+技能范围），None=用默认ROI逻辑。
        """
        if not self._monster_templates or frame is None:
            return []
        fh, fw = frame.shape[:2]
        # 2026-09-07：优先用传入的crop_rect（检测线程按技能范围动态计算）；没有则用默认ROI逻辑
        if crop_rect is not None:
            cx1, cy1, cx2, cy2 = crop_rect
            cx1, cy1 = max(0, cx1), max(0, cy1)
            cx2, cy2 = min(fw, cx2), min(fh, cy2)
            if cx2 <= cx1 or cy2 <= cy1:
                return []
            frame = frame[cy1:cy2, cx1:cx2]
            _crop_x1, _crop_y1 = cx1, cy1
        # 运行时：只在人物周围800x400范围识别(左右各400上下各200)，远怪YOLO全图兜底，提高速度
        # 不运行时：全图识别(游戏画面区域3,30到1365,738)，用于紫点显示
        elif getattr(self, '_running', False) and getattr(self, '_player_screen_pos', None):
            _px, _py = self._player_screen_pos
            _roi_x1 = max(0, _px - 350)
            _roi_y1 = max(DETECT_TOP_MARGIN, _py - 150)
            _roi_x2 = min(fw, _px + 350)
            _roi_y2 = min(fh - DETECT_BOTTOM_MARGIN, _py + 150)
            if _roi_x2 <= _roi_x1 or _roi_y2 <= _roi_y1:
                return []
            frame = frame[_roi_y1:_roi_y2, _roi_x1:_roi_x2]
            _crop_x1, _crop_y1 = _roi_x1, _roi_y1
        else:
            _crop_x1, _crop_y1 = 3, DETECT_TOP_MARGIN
            _crop_x2, _crop_y2 = 1365, fh - DETECT_BOTTOM_MARGIN
            _cx2 = min(_crop_x2, fw)
            _cy2 = min(_crop_y2, fh)
            if _cx2 <= _crop_x1 or _cy2 <= _crop_y1:
                return []
            frame = frame[_crop_y1:_cy2, _crop_x1:_cx2]
        fh, fw = frame.shape[:2]
        all_matches = []  # [(cx, cy, score, tpl_w, tpl_h), ...]

        # 【定稿】怪物特征只在面板技能范围(atk1_distance)内识别，超范围的交给YOLO全图。
        # 仅在运行时(有人物屏幕位置)做范围限定；不运行时(显示用)保持全图识别。
        _skill_gap = int(self._get_fight_config().get("atk1_distance", 150) or 150)
        _pos_char = getattr(self, '_player_screen_pos', None)

        # === 全图匹配所有特征，收集所有超过阈值的位置 ===
        feature_best = {}  # 每个特征的最佳匹配 {tpl_id: (cx, cy, score)}
        for tpl in self._monster_templates:
            timg = tpl["img"]
            th, tw = timg.shape[:2]
            if th > fh or tw > fw:
                continue
            result = cv2.matchTemplate(frame, timg, cv2.TM_CCOEFF_NORMED)
            # 找所有超过阈值的位置
            locs = np.where(result >= float(self._match_sim.get("monster", "0.70")))
            for pt in zip(*locs[::-1]):  # pt = (x, y)
                score = result[pt[1], pt[0]]
                cx = pt[0] + tw // 2 + int(tpl.get("offset_x", 0)) + _crop_x1
                cy = pt[1] + th // 2 + int(tpl.get("offset_y", 0)) + _crop_y1
                # 【定稿】特征只认面板技能范围(以X差=atk1_distance为准)；超范围的特征点不采用(交YOLO全图)。
                # 只在运行时(有人物位置)才限定；不运行时(编辑/显示用)保持全图识别。
                if _pos_char is not None and abs(cx - _pos_char[0]) > _skill_gap:
                    continue
                all_matches.append((cx, cy, score, tw, th))
                # 记录每个特征的最佳匹配位置（用于蒙板显示特征点+数字）
                tid = tpl["id"]
                if tid not in feature_best or score > feature_best[tid][2]:
                    feature_best[tid] = (cx, cy, score)
        # 记录每个特征的最佳匹配结果到蒙板（显示紫色点+数字编号，方便发现哪个特征误判）
        self._monster_feature_matches = [(v[0], v[1], k, v[2]) for k, v in feature_best.items()]
        # 调试日志：查看怪物特征匹配结果
        _now_dbg = time.time()
        if not hasattr(self, '_last_monster_dbg_log') or _now_dbg - self._last_monster_dbg_log > 2:
            self._last_monster_dbg_log = _now_dbg
            _debug_log("[怪物特征匹配] 模板%d套 匹配到%d个特征点: %s" % (
                len(self._monster_templates), len(self._monster_feature_matches),
                str([(f[0], f[1], f[2], round(f[3], 2)) for f in self._monster_feature_matches[:5]])))

        # === 非极大值抑制（距离太近的合并，保留置信度最高的） ===
        all_matches.sort(key=lambda x: x[2], reverse=True)  # 按置信度降序
        monsters = []
        used = [False] * len(all_matches)
        for i, (cx, cy, score, tw, th) in enumerate(all_matches):
            if used[i]:
                continue
            # 找所有距离这个匹配太近的，合并
            cluster = [(cx, cy, score, tw, th)]
            used[i] = True
            for j in range(i + 1, len(all_matches)):
                if used[j]:
                    continue
                cx2, cy2, _, _, _ = all_matches[j]
                dist = ((cx - cx2)**2 + (cy - cy2)**2) ** 0.5
                if dist < max(tw, th) * 0.8:  # 距离小于模板尺寸的80%，合并
                    cluster.append(all_matches[j])
                    used[j] = True
            # 取聚类中置信度最高的作为代表
            best = max(cluster, key=lambda x: x[2])
            bcx, bcy, bscore, btw, bth = best
            # 转换成怪物框格式 (x1, y1, x2, y2, score)
            x1 = max(0, bcx - btw // 2)
            y1 = max(0, bcy - bth // 2)
            x2 = min(fw, bcx + btw // 2)
            y2 = min(fh, bcy + bth // 2)
            monsters.append((x1, y1, x2, y2, bscore))

        if monsters:
            _debug_log("[怪物特征匹配] 检测到 %d 个怪物" % len(monsters))
        return monsters

    def _show_offset_feedback(self):
        """偏移视觉反馈：输入完成3秒后，在统一蒙板上让黄点闪烁约5秒"""
        if self._offset_feedback_done or self._offset_feedback_start == 0:
            return
        now_ms = time.time() * 1000
        elapsed = now_ms - self._offset_feedback_start
        if elapsed < 3000:
            return  # 等3秒
        # 只触发一次
        self._offset_feedback_done = True
        print("[偏移反馈] 偏移黄点将在蒙板上闪烁5秒")
        # 在蒙板数据中设置闪烁截止时间（蒙板主循环负责闪烁）
        if self._monster_overlay_data is not None:
            self._monster_overlay_data['blink_until'] = now_ms + 5000
        else:
            # 蒙板还没数据，先建一个空壳，等角色匹配到了自然会闪烁
            self._monster_overlay_data = {'blink_until': now_ms + 5000}

    def _start_monster_overlay(self):
        """启动怪物检测透明蒙板（置顶透明窗口，绿色线条从角色偏移点指向怪物）"""
        if self._monster_overlay_running:
            return
        self._monster_overlay_running = True
        # 保留已有数据（如偏移闪烁blink_until），不重置为None
        if self._monster_overlay_data is None:
            self._monster_overlay_data = {}
        t = threading.Thread(target=self._monster_overlay_loop, daemon=True)
        self._monster_overlay_thread = t
        t.start()
        _debug_log("[怪物蒙板] 已启动（人物模板%d套，阈值%.2f）" % (len(self._char_templates), CHAR_MATCH_THRESHOLD))
        if not self._char_templates:
            self._add_log("蒙板已启动，但未添加人物特征模板，黄点不会显示")

    def _stop_monster_overlay(self):
        """停止怪物检测透明蒙板"""
        self._monster_overlay_running = False
        self._monster_overlay_data = None
        # Force destroy the overlay window immediately (don't wait for thread loop)
        if self._overlay_hwnd:
            try:
                user32 = ctypes.windll.user32
                user32.DestroyWindow(self._overlay_hwnd)
                _debug_log("[怪物蒙板] 强制销毁窗口 hwnd=%s" % self._overlay_hwnd)
            except Exception as e:
                _debug_log("[怪物蒙板] DestroyWindow异常: %s" % e)
            self._overlay_hwnd = None
        # Wait for overlay thread to exit (max 1 second)
        if self._monster_overlay_thread and self._monster_overlay_thread.is_alive():
            self._monster_overlay_thread.join(timeout=1.0)
            _debug_log("[怪物蒙板] 线程已join")
        _debug_log("[怪物蒙板] 已停止")

    def _monster_overlay_loop(self):
        """后台线程：创建置顶透明蒙板窗口，每100ms更新
        优先使用Win32原生API（打包可靠），失败回退tkinter
        统一显示：角色偏移黄点 + 怪物绿框/连线 + 血条红点 + 蓝条蓝点"""
        try:
            self._win32_overlay_loop()
        except Exception as e:
            _debug_log("[怪物蒙板] Win32窗口失败: %s" % e)
        finally:
            # 线程退出时重置标志，允许下次重启
            self._monster_overlay_running = False
            _debug_log("[怪物蒙板] 线程已退出，标志已重置")

    def _win32_overlay_loop(self):
        """Win32原生分层透明窗口（不依赖tkinter，打包后可靠）"""
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

        # === 64位函数签名（必须设置，否则句柄被截断成32位）===
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.RegisterClassW.argtypes = [ctypes.c_void_p]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        # 蒙板对屏幕捕获隐身(用户2026-09-09:识别必须看原游戏图层,不能把蒙板上画的蓝梯/绿线/锁框抓进去):
        # WDA_EXCLUDEFROMCAPTURE=0x11(Win10 19041+)窗口人眼照常显示,但mss/BitBlt等一切屏幕截图里都不出现,
        # 从根上杜绝小地图蓝线边缘被ffff88误认成人物光点(2~4px贴着梯子的假点→爬梯Y不涨误判失败→下来)。零闪烁零延迟。
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetTimer.restype = ctypes.c_void_p
        user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
        user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.BeginPaint.restype = wintypes.HDC
        user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        user32.PeekMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.DefWindowProcW.restype = ctypes.c_longlong
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        gdi32.CreateSolidBrush.restype = ctypes.c_void_p
        gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
        gdi32.CreatePen.restype = ctypes.c_void_p
        gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.SelectObject.restype = ctypes.c_void_p
        gdi32.SelectObject.argtypes = [wintypes.HDC, ctypes.c_void_p]
        user32.FillRect.restype = ctypes.c_int
        user32.FillRect.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.HBRUSH]
        gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi32.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
        gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
        gdi32.GetStockObject.restype = ctypes.c_void_p
        gdi32.GetStockObject.argtypes = [ctypes.c_int]

        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        WS_POPUP = 0x80000000
        WS_VISIBLE = 0x10000000
        LWA_COLORKEY = 0x00000001
        WM_PAINT = 0x000F
        WM_TIMER = 0x0113
        WM_DESTROY = 0x0002
        WM_ERASEBKGND = 0x0014
        COLOR_MAGENTA = 0x00FF00FF  # BGR: R=255,G=0,B=255
        IDT_TIMER = 1

        # 回调函数类型（必须在WNDCLASS之前定义，字段类型用它）
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class PAINTSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hdc", wintypes.HDC),
                ("fErase", wintypes.BOOL),
                ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", wintypes.BYTE * 32),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
            ]

        hinst = kernel32.GetModuleHandleW(None)
        if not hasattr(self, '_overlay_class_seq'):
            self._overlay_class_seq = 0
        self._overlay_class_seq += 1
        className = "MapleBotOverlay_%d_%d" % (id(self), self._overlay_class_seq)
        first_draw = [True]
        _paint_count = [0]

        def wnd_proc(hwnd, msg, wParam, lParam):
            try:
                if msg == WM_TIMER:
                    user32.InvalidateRect(hwnd, None, True)
                    return 0
                elif msg == WM_ERASEBKGND:
                    return 1
                # === 自动校准蒙板拖动（仅stage=1时，拖动绿点蓝点定特色位置）===
                elif msg == 0x0201:  # WM_LBUTTONDOWN
                    if getattr(self, '_auto_calib_stage', 0) == 1:
                        # 用GetCursorPos取屏幕坐标（最准，不依赖窗口客户区）
                        cursor = wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(cursor))
                        mx, my = cursor.x, cursor.y
                        green_scr = getattr(self, '_auto_calib_green_screen', None)
                        blue_scr = getattr(self, '_auto_calib_blue_screen', None)
                        # 检测是否点中绿点或蓝点（±10px范围，方便点击）
                        if green_scr and abs(mx - green_scr[0]) <= 10 and abs(my - green_scr[1]) <= 10:
                            self._auto_calib_dragging = 'green'
                            return 0
                        if blue_scr and abs(mx - blue_scr[0]) <= 10 and abs(my - blue_scr[1]) <= 10:
                            self._auto_calib_dragging = 'blue'
                            return 0
                elif msg == 0x0200:  # WM_MOUSEMOVE
                    if getattr(self, '_auto_calib_dragging', None):
                        cursor = wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(cursor))
                        mx, my = cursor.x, cursor.y
                        base = getattr(self, '_auto_calib_base', None)
                        if base:
                            bx, by = base[0], base[1]
                            if self._auto_calib_dragging == 'green':
                                # 绿点只能水平拖动，Y保持基点Y（水平）
                                self._auto_calib_green_screen = (mx, by)
                            elif self._auto_calib_dragging == 'blue':
                                # 蓝点只能垂直拖动，X保持基点X（垂直）
                                self._auto_calib_blue_screen = (bx, my)
                        return 0
                elif msg == 0x0202:  # WM_LBUTTONUP
                    if getattr(self, '_auto_calib_dragging', None):
                        self._auto_calib_dragging = None
                elif msg == 0x0204:  # WM_RBUTTONDOWN：右键点击检测框内弹出对话框（编辑/保存）
                    _rx = ctypes.c_short(lParam & 0xFFFF).value
                    _ry = ctypes.c_short((lParam >> 16) & 0xFFFF).value
                    for _di, _db in enumerate(self._bg_regions):
                        if _db["x"] <= _rx <= _db["x"] + _db["w"] and _db["y"] <= _ry <= _db["y"] + _db["h"]:
                            # 点击在检测框内：弹出对话框，是=进入编辑，否=保存并退出编辑
                            _ret = user32.MessageBoxW(hwnd, "是=进入编辑（可拖动检测框）\n否=保存位置", "检测框操作", 4)  # MB_YESNO
                            if _ret == 6:  # IDYES = 进入编辑状态
                                self._bg_editing = True
                                self._bg_dragging = _di
                                print("[检测框] 进入编辑状态，框%d可拖动" % _di)
                            elif _ret == 7:  # IDNO = 保存
                                self._bg_editing = False
                                self._bg_dragging = -1
                                self._save_bg_regions()
                                print("[检测框] 已保存检测框位置")
                            return 0
                elif msg == 0x0200:  # WM_MOUSEMOVE：编辑状态下拖动死区检测框
                    if getattr(self, '_bg_editing', False) and self._bg_dragging >= 0:
                        _mx = ctypes.c_short(lParam & 0xFFFF).value
                        _my = ctypes.c_short((lParam >> 16) & 0xFFFF).value
                        _db = self._bg_regions[self._bg_dragging]
                        _db["x"] = max(0, _mx - _db["w"] // 2)
                        _db["y"] = max(0, _my - _db["h"] // 2)
                        return 0
                elif msg == 0x0205:  # WM_RBUTTONUP：编辑状态下右键松开不处理（对话框已在按下时弹出）
                    return 0
                elif msg == WM_PAINT:
                    _paint_count[0] += 1
                    if _paint_count[0] <= 3 or _paint_count[0] % 30 == 0:
                        _debug_log("[怪物蒙板] WM_PAINT 第%d次" % _paint_count[0])
                    ps = PAINTSTRUCT()
                    hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                    gdi_objs = []
                    try:
                        rect = wintypes.RECT()
                        user32.GetClientRect(hwnd, ctypes.byref(rect))
                        brush = gdi32.CreateSolidBrush(COLOR_MAGENTA)
                        if brush:
                            gdi_objs.append(brush)
                        user32.FillRect(hdc, ctypes.byref(rect), brush)
                        # === 自动校准点标记（仅stage=1时显示红绿蓝三点+连线，截图后隐藏，只留绿/蓝跟踪圆）===
                        auto_base = getattr(self, '_auto_calib_base', None)
                        auto_stage = getattr(self, '_auto_calib_stage', 0)
                        if auto_base and len(auto_base) >= 4 and auto_stage == 1:
                            bx, by = auto_base[0], auto_base[1]  # 基点屏幕坐标（stage=1时实时跟随人物）
                            _axis = getattr(self, '_auto_calib_axis', 'X')  # 当前校准方向（X绿圈/Y蓝圈）
                            goff = getattr(self, '_auto_calib_green_offset', (400, 0))  # 绿点偏移
                            boff = getattr(self, '_auto_calib_blue_offset', (0, -400))   # 蓝点偏移
                            # 画基点（红色实心圆）
                            brush_calib = gdi32.CreateSolidBrush(0x0000FF)
                            if brush_calib:
                                gdi_objs.append(brush_calib)
                            old_brush_calib = gdi32.SelectObject(hdc, brush_calib)
                            gdi32.Ellipse(hdc, bx - 6, by - 6, bx + 7, by + 7)
                            gdi32.SelectObject(hdc, old_brush_calib)
                            gdi32.SetTextColor(hdc, 0x0000FF)
                            gdi32.SetBkMode(hdc, 1)
                            gdi32.TextOutW(hdc, bx + 8, by - 8, "基", 1)
                            if _axis == 'X':
                                # 只画绿圈（X方向）
                                rx, ry = bx + goff[0], by + goff[1]  # 绿点屏幕位置
                                brush_g = gdi32.CreateSolidBrush(0x00FF00)
                                if brush_g:
                                    gdi_objs.append(brush_g)
                                old_brush_g = gdi32.SelectObject(hdc, brush_g)
                                gdi32.Ellipse(hdc, rx - 6, ry - 6, rx + 7, ry + 7)
                                gdi32.SelectObject(hdc, old_brush_g)
                                gdi32.SetTextColor(hdc, 0x00FF00)
                                gdi32.TextOutW(hdc, rx + 8, ry - 8, "X", 1)
                                pen = gdi32.CreatePen(0, 2, 0x0000FF)
                                if pen:
                                    gdi_objs.append(pen)
                                old_pen = gdi32.SelectObject(hdc, pen)
                                gdi32.MoveToEx(hdc, bx, by, None)
                                gdi32.LineTo(hdc, rx, ry)
                                gdi32.SelectObject(hdc, old_pen)
                                gdi32.SetTextColor(hdc, 0x00FFFF)
                                txt = "X:%d" % (rx - bx)
                                gdi32.TextOutW(hdc, (bx + rx) // 2 - 20, (by + ry) // 2 - 10, txt, len(txt))
                            else:
                                # 只画蓝圈（Y方向）
                                tx, ty = bx + boff[0], by + boff[1]  # 蓝点屏幕位置
                                brush_b = gdi32.CreateSolidBrush(0xFF0000)
                                if brush_b:
                                    gdi_objs.append(brush_b)
                                old_brush_b = gdi32.SelectObject(hdc, brush_b)
                                gdi32.Ellipse(hdc, tx - 6, ty - 6, tx + 7, ty + 7)
                                gdi32.SelectObject(hdc, old_brush_b)
                                gdi32.SetTextColor(hdc, 0xFF0000)
                                gdi32.TextOutW(hdc, tx + 8, ty - 8, "Y", 1)
                                pen_b = gdi32.CreatePen(0, 2, 0xFF0000)
                                if pen_b:
                                    gdi_objs.append(pen_b)
                                old_pen_b = gdi32.SelectObject(hdc, pen_b)
                                gdi32.MoveToEx(hdc, bx, by, None)
                                gdi32.LineTo(hdc, tx, ty)
                                gdi32.SelectObject(hdc, old_pen_b)
                                gdi32.SetTextColor(hdc, 0x00FFFF)
                                txt_y = "Y:%d" % (by - ty)
                                gdi32.TextOutW(hdc, (bx + tx) // 2 + 5, (by + ty) // 2, txt_y, len(txt_y))
                        # === 模板匹配空心圆（stage>=2时，在匹配位置画空心圆，标记特色位置）===
                        if auto_stage >= 2:
                            # 绿色特色位置绿光圈（半径20，线宽4）
                            gmatch = getattr(self, '_calib_green_match_pos', None)
                            if gmatch:
                                green_pen = gdi32.CreatePen(0, 4, 0x00FF00)  # 绿色BGR
                                if green_pen:
                                    gdi_objs.append(green_pen)
                                old_pen_g = gdi32.SelectObject(hdc, green_pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                gx, gy = gmatch
                                gdi32.Ellipse(hdc, gx - 20, gy - 20, gx + 21, gy + 21)
                                gdi32.SelectObject(hdc, old_pen_g)
                            # 蓝色特色位置蓝光圈（半径20，线宽4）
                            bmatch = getattr(self, '_calib_blue_match_pos', None)
                            if bmatch:
                                blue_pen = gdi32.CreatePen(0, 4, 0xFF0000)  # 蓝色BGR
                                if blue_pen:
                                    gdi_objs.append(blue_pen)
                                old_pen_b = gdi32.SelectObject(hdc, blue_pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                blx, bly = bmatch
                                gdi32.Ellipse(hdc, blx - 20, bly - 20, blx + 21, bly + 21)
                                gdi32.SelectObject(hdc, old_pen_b)
                        # === 校准步骤文字提示（窗口最上方白边，红色大字，明显提示当前第几步）===
                        if auto_stage >= 1:
                            _cal_axis = getattr(self, '_auto_calib_axis', 'X')  # 当前校准方向(第3步引导按X/Y区分)
                            step_texts = {
                                1: "请移动光圈到角色能够到达的位置并且相对固定的背景上",
                                2: "请移动角色到光圈位置",
                                3: ("X点记录完成 请按【Y倍率】进行下一步" if _cal_axis == 'X' else "Y点记录完成"),
                            }
                            step_txt = step_texts.get(auto_stage, "")
                            if step_txt:
                                gdi32.SetTextColor(hdc, 0x0000FF)  # 红色文字（BGR格式）
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                # 文字显示在窗口最上方白边（水平居中，垂直靠上）
                                txt_x = max(10, rect.right // 2 - 280)
                                txt_y = 15  # 窗口最上方白边
                                gdi32.TextOutW(hdc, txt_x, txt_y, step_txt, len(step_txt))
                        data = self._monster_overlay_data
                        # 人物位置取数（黄点/怪物连线/框都依赖它；丢失会使后面绘制抛异常）
                        char_pos = data.get('char_pos') if data else None
                        cx = cy = 0
                        if char_pos:
                            cx, cy = char_pos
                        now_ms = time.time() * 1000
                        if data:
                            hp_marker = data.get('hp_marker')
                            if hp_marker:
                                hx, hy = hp_marker
                                pen = gdi32.CreatePen(0, 1, 0xFFFFFF)  # 白框1px
                                if pen:
                                    gdi_objs.append(pen)
                                old_pen = gdi32.SelectObject(hdc, pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                gdi32.Rectangle(hdc, hx - 3, hy, hx + 3, hy + 10)
                                gdi32.SelectObject(hdc, old_pen)
                            mp_marker = data.get('mp_marker')
                            if mp_marker:
                                mx, my = mp_marker
                                pen = gdi32.CreatePen(0, 1, 0xFFFFFF)  # 白框1px
                                if pen:
                                    gdi_objs.append(pen)
                                old_pen = gdi32.SelectObject(hdc, pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                gdi32.Rectangle(hdc, mx - 3, my, mx + 3, my + 10)
                                gdi32.SelectObject(hdc, old_pen)
                            # === 人物匹配ROI范围绿框（400x400，以上次位置为中心，方便看是否出界）===
                            # 用户2026-09-05：默认隐藏看不清（不删，以后要显示把 _show_char_roi 置True）
                            char_roi = data.get('char_match_roi')
                            if char_roi and getattr(self, '_show_char_roi', False):
                                rx1, ry1, rx2, ry2 = char_roi
                                roi_pen = gdi32.CreatePen(0, 2, 0x00FF00)  # 绿色2px
                                if roi_pen:
                                    gdi_objs.append(roi_pen)
                                old_roi_pen = gdi32.SelectObject(hdc, roi_pen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                gdi32.Rectangle(hdc, rx1, ry1, rx2, ry2)
                                gdi32.SelectObject(hdc, old_roi_pen)

                            # 人物特征单独匹配点（黄色小点+数字编号，方便发现哪个特征误判）
                            # 注：已去掉大的常驻黄点（半径6），只用带编号的小光点显示每个特征的匹配情况
                            for (fx, fy, fid, fconf) in data.get('char_feature_matches', []):
                                r = 4  # 半径4（原3加大20%）
                                fpen = gdi32.CreatePen(0, 1, 0x0080FF)  # 橙色边框
                                if fpen:
                                    gdi_objs.append(fpen)
                                fbrush = gdi32.CreateSolidBrush(0x00FFFF)  # 黄色填充
                                if fbrush:
                                    gdi_objs.append(fbrush)
                                old_fpen = gdi32.SelectObject(hdc, fpen)
                                old_fbrush = gdi32.SelectObject(hdc, fbrush)
                                gdi32.Ellipse(hdc, fx - r, fy - r, fx + r + 1, fy + r + 1)
                                gdi32.SelectObject(hdc, old_fpen)
                                gdi32.SelectObject(hdc, old_fbrush)
                                # 数字编号（在点的右边，17号字体，原14加大20%）
                                txt = str(fid)
                                ffont = gdi32.CreateFontW(17, 0, 0, 0, 400, 0, 0, 0, 134, 3, 2, 1, 49, "微软雅黑")
                                if ffont:
                                    gdi_objs.append(ffont)
                                old_ffont = gdi32.SelectObject(hdc, ffont)
                                gdi32.SetTextColor(hdc, 0x00FFFF)  # 黄色文字
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                gdi32.TextOutW(hdc, fx + 7, fy - 11, txt, len(txt))
                                gdi32.SelectObject(hdc, old_ffont)

                            # 怪物特征单独匹配点（紫色小点+数字编号，方便发现哪个特征误判）
                            # 注：和人物特征点写法完全一样，不用self（wnd_proc回调中self会导致异常）
                            for (fx, fy, fid, fconf) in data.get('monster_feature_matches', []):
                                r = 4  # 半径4（和人物特征点一样）
                                # 怪物特征点：紫蓝色 0x8000FF（测试是不是只有0xFF00FF有问题）
                                fpen = gdi32.CreatePen(0, 1, 0x800080)  # 深紫色边框
                                if fpen:
                                    gdi_objs.append(fpen)
                                fbrush = gdi32.CreateSolidBrush(0x8000FF)  # 紫蓝色填充（测试）
                                if fbrush:
                                    gdi_objs.append(fbrush)
                                old_fpen = gdi32.SelectObject(hdc, fpen)
                                old_fbrush = gdi32.SelectObject(hdc, fbrush)
                                gdi32.Ellipse(hdc, fx - r, fy - r, fx + r + 1, fy + r + 1)
                                gdi32.SelectObject(hdc, old_fpen)
                                gdi32.SelectObject(hdc, old_fbrush)
                                # 数字编号（在点的右边，17号字体）
                                txt = str(fid)
                                ffont = gdi32.CreateFontW(17, 0, 0, 0, 400, 0, 0, 0, 134, 3, 2, 1, 49, "微软雅黑")
                                if ffont:
                                    gdi_objs.append(ffont)
                                old_ffont = gdi32.SelectObject(hdc, ffont)
                                gdi32.SetTextColor(hdc, 0x8000FF)  # 紫蓝色文字
                                gdi32.SetBkMode(hdc, 1)  # 透明背景
                                gdi32.TextOutW(hdc, fx + 7, fy - 11, txt, len(txt))
                                gdi32.SelectObject(hdc, old_ffont)

                            if char_pos:
                                # 锁定怪用红框(宽3px)，其他怪用绿框——方便看清当前在打哪只(用户2026-09-05)
                                _locked_t = data.get('locked_target')
                                green_pen = gdi32.CreatePen(0, 2, 0x00FF00)
                                red_pen = gdi32.CreatePen(0, 3, 0x0000FF)
                                if green_pen:
                                    gdi_objs.append(green_pen)
                                if red_pen:
                                    gdi_objs.append(red_pen)
                                old_pen = gdi32.SelectObject(hdc, green_pen)
                                null_brush = gdi32.GetStockObject(5)
                                old_brush = gdi32.SelectObject(hdc, null_brush)
                                for (x1, y1, x2, y2, score) in data.get('monsters', []):
                                    mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                                    _is_locked = (_locked_t is not None and
                                                  abs(mx - _locked_t[0]) <= 60 and abs(my - _locked_t[1]) <= 60)
                                    if _is_locked:
                                        gdi32.SelectObject(hdc, red_pen)
                                    else:
                                        gdi32.SelectObject(hdc, green_pen)
                                    gdi32.MoveToEx(hdc, cx, cy, None)
                                    gdi32.LineTo(hdc, mx, my)
                                    gdi32.Rectangle(hdc, x1, y1, x2, y2)
                                gdi32.SelectObject(hdc, old_pen)
                                gdi32.SelectObject(hdc, old_brush)
                                # 【用户2026-09-08】当前选中的梯子红框（洋红色3px，框住梯子位置，方便调试看选的对不对）
                                _ld_rect = data.get('ladder_rect')
                                if _ld_rect:
                                    _lx1, _ly1, _lx2, _ly2 = _ld_rect
                                    _ld_pen = gdi32.CreatePen(0, 3, 0xFF00FF)  # 洋红色BGR
                                    if _ld_pen:
                                        gdi_objs.append(_ld_pen)
                                    _old_ld_pen = gdi32.SelectObject(hdc, _ld_pen)
                                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                    gdi32.Rectangle(hdc, _lx1, _ly1, _lx2, _ly2)
                                    gdi32.SelectObject(hdc, _old_ld_pen)
                                    # 梯子X坐标文字
                                    gdi32.SetTextColor(hdc, 0xFF00FF)
                                    gdi32.SetBkMode(hdc, 1)
                                    _ld_txt = "梯X:%d" % ((_lx1 + _lx2) // 2)
                                    gdi32.TextOutW(hdc, _lx1, _ly1 - 18, _ld_txt, len(_ld_txt))
                                for (x1, y1, x2, y2, score) in data.get('monsters', []):
                                    mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                                    dist = int(((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5)
                                    txt = str(dist)
                                    gdi32.SetTextColor(hdc, 0x00FF00)
                                    gdi32.SetBkMode(hdc, 1)
                                    gdi32.TextOutW(hdc, (cx + mx) // 2 - 8, (cy + my) // 2 - 7, txt, len(txt))
                                # 怪物头顶血条绿色标记（近战挡住怪时凭血条定位）
                                for (bx, by, bw, bh) in data.get('monster_hp_bars', []):
                                    gdi32.Rectangle(hdc, bx, by, bx + bw, by + bh)

                    except Exception as e:
                        _debug_log("[怪物蒙板] 绘制异常: %s" % e)
                    finally:
                        for _obj in gdi_objs:
                            try:
                                gdi32.DeleteObject(_obj)
                            except Exception:
                                pass
                        user32.EndPaint(hwnd, ctypes.byref(ps))
                    return 0
                elif msg == WM_DESTROY:
                    user32.KillTimer(hwnd, IDT_TIMER)
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wParam, lParam)
            except Exception as _e:
                try:
                    _debug_log("[怪物蒙板] wnd_proc未捕获异常 msg=%d: %s" % (msg, _e))
                except Exception:
                    pass
                return 0

        wnd_proc_ref = WNDPROC(wnd_proc)
        # 保留所有历史回调对象，防止被GC后旧窗口残余消息调用已回收内存
        if not hasattr(self, '_overlay_wndprocs'):
            self._overlay_wndprocs = []
        self._overlay_wndprocs.append(wnd_proc_ref)
        self._overlay_wndproc = wnd_proc_ref

        # === 第二个蒙板：专门显示人物绿框（小地图光点映射内容），独立窗口过程 ===

        wc = WNDCLASS()
        wc.lpfnWndProc = wnd_proc_ref
        wc.hInstance = hinst
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszClassName = className
        atom = user32.RegisterClassW(ctypes.byref(wc))
        _debug_log("[怪物蒙板] RegisterClass atom=%s hinst=%s" % (atom, hinst))
        if not atom:
            _err = ctypes.get_last_error()
            _debug_log("[怪物蒙板] RegisterClass失败 err=%d，先注销再重试" % _err)
            try:
                user32.UnregisterClassW(className, hinst)
            except Exception:
                pass
            atom = user32.RegisterClassW(ctypes.byref(wc))
            _debug_log("[怪物蒙板] RegisterClass重试 atom=%s" % atom)

        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST,
            className, "Overlay", WS_POPUP | WS_VISIBLE,
            0, 0, 100, 100, None, None, hinst, None)
        _debug_log("[怪物蒙板] CreateWindow hwnd=%s" % hwnd)
        self._overlay_hwnd = hwnd
        if not hwnd:
            err = ctypes.get_last_error()
            _debug_log("[怪物蒙板] CreateWindowExW失败, 错误码: %d" % err)
            raise RuntimeError("CreateWindowExW失败, 错误码: %d" % err)

        user32.SetLayeredWindowAttributes(hwnd, COLOR_MAGENTA, 0, LWA_COLORKEY)
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
        # 对屏幕捕获隐身、人眼照常显示(用户2026-09-09)：检测线程mss从屏幕BitBlt时不再抓到蒙板上的
        # 蓝梯/绿线/锁框,小地图ffff88光点不再被蓝线边缘假点污染,YOLO/血条也只看原游戏画面。返回0=老系统不支持,忽略。
        try:
            _aff = user32.SetWindowDisplayAffinity(hwnd, 0x00000011)  # WDA_EXCLUDEFROMCAPTURE
            _debug_log("[怪物蒙板] SetWindowDisplayAffinity(EXCLUDEFROMCAPTURE)=%s (1=截图隐身/人眼可见)" % _aff)
        except Exception as _e:
            _debug_log("[怪物蒙板] SetWindowDisplayAffinity异常(老系统?): %s" % _e)
        # 创建后立即定位到游戏窗口（整个窗口，包括标题栏，和_capture_window坐标系一致）
        if self.hwnd and self.window_rect:
            wr = self.window_rect
            _debug_log("[怪物蒙板] 立即定位: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
            user32.SetWindowPos(hwnd, -1, wr['left'], wr['top'],
                                wr['width'], wr['height'], 0x0050)
        else:
            # 无游戏窗口坐标时默认显示在屏幕中央，确保窗口可见用于诊断
            _sw = user32.GetSystemMetrics(0)
            _sh = user32.GetSystemMetrics(1)
            _dw, _dh = 800, 600
            _dx, _dy = (_sw - _dw) // 2, (_sh - _dh) // 2
            _debug_log("[怪物蒙板] 无游戏坐标，默认定位: %dx%d +%d+%d" % (_dw, _dh, _dx, _dy))
            user32.SetWindowPos(hwnd, -1, _dx, _dy, _dw, _dh, 0x0050)
        user32.UpdateWindow(hwnd)

        user32.SetTimer(hwnd, IDT_TIMER, 100, None)
        _vis = user32.IsWindowVisible(hwnd)
        _style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        _debug_log("[怪物蒙板] 窗口状态: visible=%s exstyle=0x%X" % (_vis, _style))
        _debug_log("[怪物蒙板] Win32窗口已创建，等待数据...")

        msg = MSG()
        while self._monster_overlay_running:
            try:
                if self.hwnd and self.window_rect:
                    wr = self.window_rect
                    if first_draw[0]:
                        _debug_log("[怪物蒙板] 窗口几何: %dx%d +%d+%d" % (wr['width'], wr['height'], wr['left'], wr['top']))
                        first_draw[0] = False
                    # 2026-09-07 CPU优化：原每50ms无条件SetWindowPos→每次都触发WM_PAINT(叠加到30fps重绘)。
                    # 只在几何变化时SetWindowPos，蒙板重绘降为 WM_TIMER(100ms)+主循环节流(100ms)≈10fps
                    _cur_geom = (wr['left'], wr['top'], wr['width'], wr['height'])
                    if getattr(self, '_overlay_last_geom', None) != _cur_geom:
                        user32.SetWindowPos(hwnd, -1, wr['left'], wr['top'],
                                            wr['width'], wr['height'], 0x0050)
                        self._overlay_last_geom = _cur_geom
                elif first_draw[0]:
                    _debug_log("[怪物蒙板] 警告：hwnd或window_rect无效")
                    first_draw[0] = False
            except Exception as e:
                _debug_log("[怪物蒙板] SetWindowPos异常: %s" % e)

            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_DESTROY:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.05)

        user32.DestroyWindow(hwnd)
        self._overlay_hwnd = None
        try:
            user32.UnregisterClassW(className, hinst)
        except Exception:
            pass
        try:
            user32.UnregisterClassW(className2, hinst)
        except Exception:
            pass
        _debug_log("[怪物蒙板] Win32窗口已销毁")

    def _tkinter_overlay_loop(self):
        """tkinter透明蒙板（回退方案）"""
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        overlay = tk.Toplevel(root)
        overlay.overrideredirect(True)
        overlay.attributes('-topmost', True)
        overlay.attributes('-transparentcolor', 'magenta')
        canvas = tk.Canvas(overlay, bg='magenta', highlightthickness=0, bd=0)
        canvas.pack(fill='both', expand=True)
        print("[怪物蒙板] Tk窗口已创建，等待数据...")
        _overlay_first_draw = [True]

        def update():
            if not self._monster_overlay_running:
                root.destroy()
                return
            try:
                if self.hwnd and self.window_rect:
                    wr = self.window_rect
                    overlay.geometry("%dx%d+%d+%d" % (
                        wr['width'], wr['height'], wr['left'], wr['top']))
                canvas.delete('all')
                data = self._monster_overlay_data
                now_ms = time.time() * 1000
                if data:
                    hp_marker = data.get('hp_marker')
                    if hp_marker:
                        hx, hy = hp_marker
                        canvas.create_rectangle(hx - 2, hy, hx + 2, hy + 10, outline='red', width=2)
                    mp_marker = data.get('mp_marker')
                    if mp_marker:
                        mx, my = mp_marker
                        canvas.create_rectangle(mx - 2, my, mx + 2, my + 10, outline='#0080FF', width=2)
                    char_pos = data.get('char_pos')
                    if char_pos:
                        if _overlay_first_draw[0]:
                            _overlay_first_draw[0] = False
                            print("[怪物蒙板] 首次绘制黄点 at", char_pos)
                        cx, cy = char_pos
                        blink_until = data.get('blink_until', 0)
                        if blink_until > now_ms:
                            if int(now_ms / 300) % 2 == 0:
                                canvas.create_oval(cx - 6, cy - 6, cx + 6, cy + 6,
                                                   fill='yellow', outline='orange', width=2)
                        else:
                            canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5,
                                               fill='yellow', outline='orange', width=2)
                        for (x1, y1, x2, y2, score) in data.get('monsters', []):
                            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
                            canvas.create_line(cx, cy, mx, my, fill='#00FF00', width=2)
                            canvas.create_rectangle(x1, y1, x2, y2, outline='#00FF00', width=2)
                            dist = int(((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5)
                            canvas.create_text((cx + mx) // 2, (cy + my) // 2,
                                               text=str(dist), fill='#00FF00',
                                               font=('Arial', 9, 'bold'))
            except Exception as e:
                print("[怪物蒙板] 更新异常:", e)
            overlay.after(100, update)

        overlay.after(100, update)
        root.mainloop()

    def _calc_character_monster_distance(self, char_pos, monster_bbox):
        """计算人物与怪物之间的像素距离
        Args:
            char_pos: (x, y) 人物中心点坐标（游戏窗口像素）
            monster_bbox: (x1, y1, x2, y2) 怪物检测框（游戏窗口像素）
        Returns:
            float: 欧氏距离（像素），或 None 如果输入无效
        """
        if char_pos is None or monster_bbox is None:
            return None
        cx, cy = char_pos[0], char_pos[1]
        mx1, my1, mx2, my2 = monster_bbox
        mcx = (mx1 + mx2) // 2
        mcy = (my1 + my2) // 2
        return float(np.sqrt((cx - mcx) ** 2 + (cy - mcy) ** 2))

    def _find_nearest_monster(self, char_pos, monster_bboxes):
        """从怪物检测列表中找到离人物最近的怪物
        Args:
            char_pos: (x, y) 人物中心点
            monster_bboxes: [(x1,y1,x2,y2,conf,cls), ...] YOLO检测结果
        Returns:
            (index, distance) 或 (None, None)
        """
        if char_pos is None or not monster_bboxes:
            return None, None
        best_idx = None
        best_dist = float("inf")
        for i, bbox in enumerate(monster_bboxes):
            dist = self._calc_character_monster_distance(char_pos, bbox[:4])
            if dist is not None and dist < best_dist:
                best_dist = dist
                best_idx = i
        return best_idx, best_dist

    # ===== 打怪/药品 输入框系统 =====

    def _load_match_sim(self):
        """从config读人物/怪物识别相似度(存在fight_potion_config.json的match_sim字段)，默认0.70"""
        try:
            if os.path.exists(INPUT_CONFIG_FILE):
                with open(INPUT_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                ms = cfg.get("match_sim", {})
                if isinstance(ms, dict):
                    for k in ("char", "monster"):
                        if ms.get(k):
                            self._match_sim[k] = str(ms[k])
        except Exception as e:
            _debug_log("[相似度] 加载失败: %s" % e)

    def _save_match_sim(self):
        """保存人物/怪物相似度到config(match_sim字段)"""
        try:
            cfg = {}
            if os.path.exists(INPUT_CONFIG_FILE):
                with open(INPUT_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["match_sim"] = self._match_sim
            with open(INPUT_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _debug_log("[相似度] 保存失败: %s" % e)

    def _load_input_config(self):
        """加载打怪/药品配置到 _field_values（只加载用户已录入的值，不设默认显示）"""
        self._field_values = {}
        _debug_log("配置文件路径: %s 存在=%s" % (INPUT_CONFIG_FILE, os.path.exists(INPUT_CONFIG_FILE)))
        if os.path.exists(INPUT_CONFIG_FILE):
            try:
                with open(INPUT_CONFIG_FILE, "r", encoding="utf-8") as fp:
                    saved = json.load(fp)
                for k, v in saved.items():
                    if v:
                        self._field_values[k] = str(v)
                _debug_log("加载配置: %s" % dict(self._field_values))
                print("[输入框] 已加载配置，共 %d 项" % len(self._field_values))
            except Exception as e:
                _debug_log("加载配置失败: %s" % e)
                print("[输入框] 加载配置失败:", e)

    @staticmethod
    def _parse_optional_int(v):
        """输入框留空/非法→None(表示该可选项不启用)；合法数字串→int。用于跳高打区间这种"留空=不启用"的字段"""
        try:
            s = str(v if v is not None else "").strip()
            return int(s) if s else None
        except (TypeError, ValueError):
            return None

    def _save_input_config(self):
        """保存 _field_values 到磁盘（只保存已知字段且非空的值）"""
        known_ids = set(f[5] for f in FIGHT_FIELDS + POTION_FIELDS + ROUTE_FIELDS)
        # 倍率差弹窗的字段也需要保存
        known_ids.add("scale_x_offset")
        known_ids.add("scale_y_offset")
        # 打怪Y范围弹窗字段（上方/下方打怪范围，可负）
        known_ids.add("attack_y_up")
        known_ids.add("attack_y_down")
        known_ids.add("aoe_y_up")     # 群攻Y上/下范围(用户2026-09-07)
        known_ids.add("aoe_y_down")
        known_ids.add("slope_jump_y_min")  # 跳高打下限(起始,用户2026-09-09)
        known_ids.add("slope_jump_y_max")  # 跳高打上限：两框都填才启用,怪比人高在[下限,上限]内走"走-跳-打",超上限走梯子；任一留空不启用
        known_ids.add("slope_jump_mage")   # 法师模式勾选("1"=法师落地放技能,空=战士空中150ms放,用户2026-09-09)
        known_ids.add("far_range_x")  # 寻怪X范围(左右各,用户2026-09-07可自定义,默认1300)
        known_ids.add("far_range_y_up")    # 寻怪Y上方范围(默认150)
        known_ids.add("far_range_y_down")  # 寻怪Y下方范围(默认150)
        known_ids.add("group_priority")    # 群怪优先勾选("1"=射程外按怪群数量优先锁,空=最近原则,用户2026-09-09)
        known_ids.add("aoe_dual")          # 群攻双向勾选("1"=近身双向技能站怪群中心两侧同时打,空=单向选多侧,用户2026-09-09)
        # 瞬移：原瞬移键/距离框已移出FIGHT_FIELDS，这里手动保留，另加Y瞬移距离
        known_ids.add("teleport_key")
        known_ids.add("teleport_distance")
        known_ids.add("teleport_distance_y")
        to_save = {k: v for k, v in self._field_values.items() if k in known_ids and v}
        try:
            with open(INPUT_CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump(to_save, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[输入框] 保存配置失败:", e)

    def _load_yolo_config(self):
        """加载YOLO模型路径配置"""
        try:
            if os.path.exists(YOLO_CONFIG_FILE):
                with open(YOLO_CONFIG_FILE, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                self._yolo_model_path = data.get("model_path")
                if self._yolo_model_path:
                    print("[YOLO] 已配置模型:", self._yolo_model_path)
        except Exception as e:
            print("[YOLO] 加载配置失败:", e)

    def _save_yolo_config(self):
        """保存YOLO模型路径配置"""
        try:
            with open(YOLO_CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump({"model_path": self._yolo_model_path}, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[YOLO] 保存配置失败:", e)

    def _select_yolo_model(self):
        """弹出文件选择框，手动选择YOLO onnx模型文件
        优先使用Win32原生对话框（打包后可靠），失败则回退tkinter"""
        path = self._win32_open_file(
            title="选择YOLO模型文件(.onnx)",
            filter_str="ONNX模型 (*.onnx)\0*.onnx\0所有文件 (*.*)\0*.*\0",
            def_ext="onnx",
        )
        if path is None:
            return  # 用户取消
        if path is False:
            self._add_log("文件对话框打开失败，请查看日志")
            print("[YOLO] 文件对话框打开失败（Win32和tkinter均不可用）")
            return
        if path:
            self._yolo_model_path = path
            self._yolo_net = None  # 重置，强制下次重新加载
            self._save_yolo_config()
            if self._init_yolo():
                self._add_log("YOLO模型已加载: %s" % os.path.basename(path))
                print("[YOLO] 模型已加载:", path)
            else:
                self._add_log("YOLO模型加载失败")
                print("[YOLO] 模型加载失败")

    @staticmethod
    def _win32_open_file(title, filter_str, def_ext=""):
        """Win32原生打开文件对话框，返回路径字符串或None（取消）/False（失败）"""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            comdlg32 = ctypes.windll.comdlg32

            # 正确设置64位函数签名
            user32.FindWindowW.restype = wintypes.HWND
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.BringWindowToTop.restype = wintypes.BOOL
            user32.BringWindowToTop.argtypes = [wintypes.HWND]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
            user32.UnhookWindowsHookEx.restype = wintypes.BOOL
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            user32.CallNextHookEx.restype = ctypes.c_longlong
            user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]

            class OPENFILENAMEW(ctypes.Structure):
                _fields_ = [
                    ("lStructSize", wintypes.DWORD),
                    ("hwndOwner", wintypes.HWND),
                    ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR),
                    ("lpstrCustomFilter", wintypes.LPWSTR),
                    ("nMaxCustFilter", wintypes.DWORD),
                    ("nFilterIndex", wintypes.DWORD),
                    ("lpstrFile", wintypes.LPWSTR),
                    ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR),
                    ("nMaxFileTitle", wintypes.DWORD),
                    ("lpstrInitialDir", wintypes.LPCWSTR),
                    ("lpstrTitle", wintypes.LPCWSTR),
                    ("Flags", wintypes.DWORD),
                    ("nFileOffset", wintypes.WORD),
                    ("nFileExtension", wintypes.WORD),
                    ("lpstrDefExt", wintypes.LPCWSTR),
                    ("lCustData", wintypes.LPARAM),
                    ("lpfnHook", ctypes.c_void_p),
                    ("lpTemplateName", wintypes.LPCWSTR),
                    ("pvReserved", ctypes.c_void_p),
                    ("dwReserved", wintypes.DWORD),
                    ("FlagsEx", wintypes.DWORD),
                ]

            OFN_EXPLORER = 0x00080000
            OFN_FILEMUSTEXIST = 0x00001000
            OFN_PATHMUSTEXIST = 0x00000800
            OFN_NOCHANGEDIR = 0x00000008
            OFN_HIDEREADONLY = 0x00000004

            file_buf = ctypes.create_unicode_buffer(260)
            ofn = OPENFILENAMEW()
            ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
            ofn.lpstrFilter = filter_str
            ofn.lpstrFile = ctypes.cast(file_buf, wintypes.LPWSTR)
            ofn.nMaxFile = 260
            ofn.lpstrTitle = title
            ofn.Flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_HIDEREADONLY
            ofn.lpstrDefExt = def_ext
            # 取自身UI窗口作为父窗口
            owner = user32.FindWindowW(None, "PLAY AND HAPPY")
            ofn.hwndOwner = owner if owner else None
            if owner:
                user32.SetForegroundWindow(owner)

            # CBT钩子：对话框激活时强制置顶（防止藏在其他窗口后面）
            WH_CBT = 5
            HCBT_ACTIVATE = 5
            CBTProc = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int,
                                         wintypes.WPARAM, wintypes.LPARAM)
            hook_ref = [None]  # 保持引用防止GC

            def cbt_proc(nCode, wParam, lParam):
                if nCode == HCBT_ACTIVATE:
                    dlg_hwnd = wParam
                    user32.SetForegroundWindow(dlg_hwnd)
                    user32.BringWindowToTop(dlg_hwnd)
                return user32.CallNextHookEx(hook_ref[0], nCode, wParam, lParam)

            cbt_callback = CBTProc(cbt_proc)
            hook_ref[0] = user32.SetWindowsHookExW(
                WH_CBT, cbt_callback,
                kernel32.GetModuleHandleW(None),
                kernel32.GetCurrentThreadId())
            _debug_log("[文件选择] CBT钩子=%s owner=%s structSize=%d" % (hook_ref[0], owner, ctypes.sizeof(OPENFILENAMEW)))

            result = comdlg32.GetOpenFileNameW(ctypes.byref(ofn))

            if hook_ref[0]:
                user32.UnhookWindowsHookEx(hook_ref[0])

            if result:
                _debug_log("[文件选择] 成功: %s" % file_buf.value)
                return file_buf.value
            # 返回0：用户取消或出错
            try:
                err = comdlg32.CommDlgExtendedError()
            except Exception:
                err = 0
            if err != 0:
                _debug_log("[文件选择] GetOpenFileNameW错误码: 0x%X" % err)
            else:
                _debug_log("[文件选择] 用户取消")
            return None  # 用户取消
        except Exception as e:
            _debug_log("[文件选择] Win32对话框异常: %s" % e)
            # 回退到tkinter
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                path = filedialog.askopenfilename(
                    title=title,
                    filetypes=[("ONNX模型", "*.onnx"), ("所有文件", "*.*")]
                )
                root.destroy()
                return path if path else None
            except Exception as e2:
                _debug_log("[文件选择] tkinter也失败: %s" % e2)
                return False

    def _get_fields_for_tab(self, tab):
        """返回指定标签页的字段列表"""
        if tab == "fight":
            return FIGHT_FIELDS
        elif tab == "potion":
            return POTION_FIELDS
        elif tab == "route":
            return ROUTE_FIELDS
        return []

    def _find_field_at(self, x, y, tab):
        """查找 (x,y) 位置的字段，返回字段元组或 None"""
        for f in self._get_fields_for_tab(tab):
            fx, fy, fw, fh, ftype, fid = f
            if fx <= x < fx + fw and fy <= y < fy + fh:
                return f
        return None

    def _handle_input_mouse(self, x, y):
        """打怪/药品页的鼠标点击处理：聚焦输入框或取消聚焦"""
        field = self._find_field_at(x, y, self._current_tab)
        if field:
            _, _, _, _, ftype, fid = field
            self._focused_field = fid
            self._last_input_change = time.time() * 1000
            self._num_field_replace = (ftype == "num")  # 数字框聚焦后首次输入覆盖旧值
            self._prev_num_states = set()  # 重置按键状态，避免旧状态残留导致新键被忽略
            print("[输入框] 聚焦:", fid, "类型:", ftype)
        else:
            # 点击其他地方，保存并取消聚焦
            if self._focused_field is not None:
                self._save_input_config()
                self._focused_field = None

    def _handle_y_dialog_event(self, event, x, y):
        """打怪Y范围弹窗的鼠标事件（fight页）。返回True=事件已被弹窗消费。布局/交互同倍率差弹窗。"""
        def _in(r, xx, yy):
            return r[0] <= xx < r[0]+r[2] and r[1] <= yy < r[1]+r[3]
        # 拖拽移动（标题栏按住时移动鼠标，窗口跟随，限制在控制面板内=可全屏拖动不飞出）
        if event == cv2.EVENT_MOUSEMOVE and self._y_dialog_dragging:
            self._y_dialog_pos[0] = x - self._y_dialog_drag_offset[0]
            self._y_dialog_pos[1] = y - self._y_dialog_drag_offset[1]
            self._y_dialog_pos[0] = max(0, min(UI_W - 320, self._y_dialog_pos[0]))
            self._y_dialog_pos[1] = max(0, min(UI_H - 365, self._y_dialog_pos[1]))
            self._update_y_dialog_positions()
            return True
        if event == cv2.EVENT_LBUTTONUP and self._y_dialog_dragging:
            self._y_dialog_dragging = False
            return True
        if event != cv2.EVENT_LBUTTONDOWN:
            return False
        self._update_y_dialog_positions()
        dlg_x, dlg_y = self._y_dialog_pos
        dlg_w, dlg_h = 320, 365
        # 1. 右上角X（不保存）
        if _in(self._dlg_y_close_btn, x, y):
            self._restore_y_dialog_backup()
            self._show_y_dialog = False
            self._focused_field = None
            print("[Y范围弹窗] 关闭（不保存）")
            return True
        # 2. 标题栏（顶部50）开始拖拽
        if dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+50:
            self._y_dialog_dragging = True
            self._y_dialog_drag_offset = [x-dlg_x, y-dlg_y]
            return True
        # 3. 上方打怪范围输入框
        if _in(self._dlg_y_up_input, x, y):
            self._focused_field = "attack_y_up"
            self._prev_num_states = set()
            self._num_field_replace = True
            self._last_input_change = time.time() * 1000
            return True
        # 4. 下方打怪范围输入框(主攻)
        if _in(self._dlg_y_down_input, x, y):
            self._focused_field = "attack_y_down"
            self._prev_num_states = set()
            self._num_field_replace = True
            self._last_input_change = time.time() * 1000
            return True
        # 4b. 群攻上方范围输入框
        if _in(self._dlg_aoe_y_up_input, x, y):
            self._focused_field = "aoe_y_up"
            self._prev_num_states = set()
            self._num_field_replace = True
            self._last_input_change = time.time() * 1000
            return True
        # 4c. 群攻下方范围输入框
        if _in(self._dlg_aoe_y_down_input, x, y):
            self._focused_field = "aoe_y_down"
            self._prev_num_states = set()
            self._num_field_replace = True
            self._last_input_change = time.time() * 1000
            return True
        # 4d. 跳高打下限输入框(用户2026-09-09，最下一行左)
        if _in(self._dlg_slope_jump_ymin_input, x, y):
            self._focused_field = "slope_jump_y_min"
            self._prev_num_states = set()
            self._num_field_replace = True
            self._last_input_change = time.time() * 1000
            return True
        # 4e. 跳高打上限输入框(最下一行右)
        if _in(self._dlg_slope_jump_ymax_input, x, y):
            self._focused_field = "slope_jump_y_max"
            self._prev_num_states = set()
            self._num_field_replace = True
            self._last_input_change = time.time() * 1000
            return True
        # 4f. 法师模式勾选框(用户2026-09-09)：点一下切换 勾=法师(落地放技能)/不勾=战士(空中150ms放)
        if _in(self._dlg_slope_mage_chk, x, y):
            self._field_values["slope_jump_mage"] = "" if self._field_values.get("slope_jump_mage") == "1" else "1"
            self._focused_field = None  # 点勾选不应停留在数字输入态
            return True
        # 5. 确认（保存）
        if _in(self._dlg_y_ok_btn, x, y):
            self._save_input_config()
            self._show_y_dialog = False
            self._focused_field = None
            print("[Y范围弹窗] 确认保存 主攻上/下=%s/%s 群攻上/下=%s/%s 跳高打=%s~%s" % (
                self._field_values.get("attack_y_up"), self._field_values.get("attack_y_down"),
                self._field_values.get("aoe_y_up"), self._field_values.get("aoe_y_down"),
                self._field_values.get("slope_jump_y_min"), self._field_values.get("slope_jump_y_max")))
            return True
        # 6. 取消（恢复，不保存）
        if _in(self._dlg_y_cancel_btn, x, y):
            self._restore_y_dialog_backup()
            self._show_y_dialog = False
            self._focused_field = None
            print("[Y范围弹窗] 取消（不保存）")
            return True
        # 7. 点到弹窗外部：关闭并恢复（不保存）
        if not (dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+dlg_h):
            self._restore_y_dialog_backup()
            self._show_y_dialog = False
            self._focused_field = None
            return True
        return False

    def _handle_search_dialog_event(self, event, x, y):
        """寻怪范围弹窗鼠标事件（fight页），交互同Y范围弹窗。返回True=已消费。"""
        def _in(r, xx, yy):
            return r[0] <= xx < r[0]+r[2] and r[1] <= yy < r[1]+r[3]
        if event == cv2.EVENT_MOUSEMOVE and self._search_dialog_dragging:
            self._search_dialog_pos[0] = x - self._search_dialog_drag_offset[0]
            self._search_dialog_pos[1] = y - self._search_dialog_drag_offset[1]
            self._search_dialog_pos[0] = max(0, min(UI_W - 320, self._search_dialog_pos[0]))
            self._search_dialog_pos[1] = max(0, min(UI_H - 200, self._search_dialog_pos[1]))
            self._update_search_dialog_positions()
            return True
        if event == cv2.EVENT_LBUTTONUP and self._search_dialog_dragging:
            self._search_dialog_dragging = False
            return True
        if event != cv2.EVENT_LBUTTONDOWN:
            return False
        self._update_search_dialog_positions()
        dlg_x, dlg_y = self._search_dialog_pos
        dlg_w, dlg_h = 320, 250
        if _in(self._dlg_search_close_btn, x, y):
            self._restore_search_dialog_backup()
            self._show_search_dialog = False
            self._focused_field = None
            return True
        if dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+50:
            self._search_dialog_dragging = True
            self._search_dialog_drag_offset = [x-dlg_x, y-dlg_y]
            return True
        # X / Y上 / Y下 输入框
        for _rect, _fid in ((self._dlg_search_x_input, "far_range_x"),
                            (self._dlg_search_y_up_input, "far_range_y_up"),
                            (self._dlg_search_y_down_input, "far_range_y_down")):
            if _in(_rect, x, y):
                self._focused_field = _fid
                self._prev_num_states = set()
                self._num_field_replace = True
                self._last_input_change = time.time() * 1000
                return True
        # 群怪优先勾选：点一下切换
        if _in(self._dlg_search_group_chk, x, y):
            self._field_values["group_priority"] = "" if self._field_values.get("group_priority") == "1" else "1"
            self._focused_field = None
            return True
        # 群攻双向勾选：点一下切换(勾=该群攻是近身双向技能,人物站怪群中心两侧同时出伤害)
        if _in(self._dlg_search_dual_chk, x, y):
            self._field_values["aoe_dual"] = "" if self._field_values.get("aoe_dual") == "1" else "1"
            self._focused_field = None
            return True
        if _in(self._dlg_search_ok_btn, x, y):
            self._save_input_config()
            self._show_search_dialog = False
            self._focused_field = None
            print("[寻怪范围弹窗] 确认保存 X=%s Y上=%s Y下=%s" % (
                self._field_values.get("far_range_x"),
                self._field_values.get("far_range_y_up"),
                self._field_values.get("far_range_y_down")))
            return True
        if _in(self._dlg_search_cancel_btn, x, y):
            self._restore_search_dialog_backup()
            self._show_search_dialog = False
            self._focused_field = None
            return True
        if not (dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+dlg_h):
            self._restore_search_dialog_backup()
            self._show_search_dialog = False
            self._focused_field = None
            return True
        return False

    def _handle_tp_dialog_event(self, event, x, y):
        """瞬移设置弹窗鼠标事件（fight页），交互同Y范围弹窗。返回True=已消费。"""
        def _in(r, xx, yy):
            return r[0] <= xx < r[0]+r[2] and r[1] <= yy < r[1]+r[3]
        if event == cv2.EVENT_MOUSEMOVE and self._tp_dialog_dragging:
            self._tp_dialog_pos[0] = x - self._tp_dialog_drag_offset[0]
            self._tp_dialog_pos[1] = y - self._tp_dialog_drag_offset[1]
            self._tp_dialog_pos[0] = max(0, min(UI_W - 320, self._tp_dialog_pos[0]))
            self._tp_dialog_pos[1] = max(0, min(UI_H - 280, self._tp_dialog_pos[1]))
            self._update_tp_dialog_positions()
            return True
        if event == cv2.EVENT_LBUTTONUP and self._tp_dialog_dragging:
            self._tp_dialog_dragging = False
            return True
        if event != cv2.EVENT_LBUTTONDOWN:
            return False
        self._update_tp_dialog_positions()
        dlg_x, dlg_y = self._tp_dialog_pos
        dlg_w, dlg_h = 320, 280
        if _in(self._dlg_tp_close_btn, x, y):
            self._restore_tp_dialog_backup()
            self._show_tp_dialog = False
            self._focused_field = None
            return True
        if dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+50:
            self._tp_dialog_dragging = True
            self._tp_dialog_drag_offset = [x-dlg_x, y-dlg_y]
            return True
        if _in(self._dlg_tp_x_input, x, y):
            self._focused_field = "teleport_distance"
            self._prev_num_states = set()
            self._num_field_replace = True
            self._last_input_change = time.time() * 1000
            return True
        if _in(self._dlg_tp_y_input, x, y):
            self._focused_field = "teleport_distance_y"
            self._prev_num_states = set()
            self._num_field_replace = True
            self._last_input_change = time.time() * 1000
            return True
        if _in(self._dlg_tp_key_input, x, y):
            # 点一下进入"录键"模式：下一次按键盘任意键即录为瞬移键(由_poll_key_capture捕获写入)
            self._focused_field = "teleport_key"
            self._prev_key_states = set()   # 清空按键基线，避免把当前正按住的键立刻录进去
            self._last_input_change = time.time() * 1000
            return True
        if _in(self._dlg_tp_ok_btn, x, y):
            self._save_input_config()
            self._show_tp_dialog = False
            self._focused_field = None
            print("[瞬移弹窗] 确认 X=%s Y=%s 按键=%s" % (
                self._field_values.get("teleport_distance") or "空",
                self._field_values.get("teleport_distance_y") or "空",
                self._field_values.get("teleport_key") or "空"))
            return True
        if _in(self._dlg_tp_cancel_btn, x, y):
            self._restore_tp_dialog_backup()
            self._show_tp_dialog = False
            self._focused_field = None
            return True
        if not (dlg_x <= x < dlg_x+dlg_w and dlg_y <= y < dlg_y+dlg_h):
            self._restore_tp_dialog_backup()
            self._show_tp_dialog = False
            self._focused_field = None
            return True
        return False

    def _key_code_to_name(self, key):
        """将 cv2.waitKey 返回的键码转为键名字符串"""
        if key == 32:
            return "space"
        elif key == 13:
            return "enter"
        elif key == 9:
            return "tab"
        elif key == 8:
            return "backspace"
        elif 0 <= key < 256:
            ch = chr(key)
            if ch.isalnum():
                return ch.lower()
            # 符号键直接用字符
            if ch in "`-=[]\\;',./":
                return ch
        return None

    def _handle_input_key(self, key):
        """聚焦输入框时的键盘处理，返回 True 表示已消费该按键"""
        if self._focused_field is None:
            return False

        fid = self._focused_field
        # 找字段类型
        ftype = "num"
        for f in FIGHT_FIELDS + POTION_FIELDS:
            if f[5] == fid:
                ftype = f[4]
                break

        if ftype == "key":
            # ESC清空键值，回车取消
            if key == 27:
                self._field_values[fid] = ""
                self._save_input_config()
                self._focused_field = None
                return True
            if key == 13:
                self._focused_field = None
                return True
            # 按键录入：捕获第一个有效键后自动失焦
            name = self._key_code_to_name(key)
            if name:
                self._field_values[fid] = name
                print("[输入框] 按键录入:", fid, "=", name)
                self._focused_field = None
                self._save_input_config()
            return True

        elif ftype == "num":
            # 数字录入
            _is_offset = fid in ("char_x_offset", "char_y_offset", "scale_x_offset", "scale_y_offset",
                                 "attack_y_up", "attack_y_down", "aoe_y_up",
                                 "slope_jump_y_min", "slope_jump_y_max")  # 主攻/群攻Y上方范围+跳高打区间(向上为负)允许负数
            _allow_decimal = fid in ("scale_x_offset", "scale_y_offset")  # 倍率差允许小数点
            if 48 <= key <= 57:  # 0-9
                cur = self._field_values.get(fid, "")
                if getattr(self, '_num_field_replace', False):
                    new_val = chr(key)  # 聚焦后首次输入覆盖旧值
                    self._num_field_replace = False
                else:
                    new_val = cur + chr(key)
                # HP/MP阈值百分比上限100
                if fid in ("hp_value", "mp_value") and int(new_val) > 100:
                    return True
                if len(new_val) <= 10:
                    self._field_values[fid] = new_val
                    self._last_input_change = time.time() * 1000
            elif _is_offset and key == 45:  # 负号（仅偏移字段和倍率差字段允许）
                cur = self._field_values.get(fid, "")
                if getattr(self, '_num_field_replace', False):
                    new_val = "-"
                    self._num_field_replace = False
                elif not cur.startswith("-"):
                    new_val = "-" + cur  # 在开头加负号
                else:
                    new_val = cur[1:]  # 已有负号则去掉
                if len(new_val) <= 10:
                    self._field_values[fid] = new_val
                    self._last_input_change = time.time() * 1000
            elif _allow_decimal and key == 46:  # 小数点（仅倍率差字段允许）
                cur = self._field_values.get(fid, "")
                if getattr(self, '_num_field_replace', False):
                    new_val = "0."
                    self._num_field_replace = False
                elif "." not in cur:
                    new_val = cur + "."  # 没有小数点则添加
                else:
                    new_val = cur  # 已有小数点则不重复添加
                if len(new_val) <= 10:
                    self._field_values[fid] = new_val
                    self._last_input_change = time.time() * 1000
            elif key == 8:  # 退格
                cur = self._field_values.get(fid, "")
                if cur:
                    self._field_values[fid] = cur[:-1]
                    self._last_input_change = time.time() * 1000
                self._num_field_replace = False  # 退格后取消覆盖状态
            elif key in (13, 27):  # 回车或ESC确认
                # 回车时再做一次上限校验
                if key == 13 and fid in ("hp_value", "mp_value"):
                    val = self._field_values.get(fid, "")
                    if val:
                        max_val = self._max_hp if fid == "hp_value" else self._max_mp
                        if max_val > 0 and int(val) > max_val:
                            print("[校验] %s阈值 %s 超出上限 %d，已清空" % (fid, val, max_val))
                            self._field_values[fid] = ""
                self._focused_field = None
                self._save_input_config()
            return True

        return False

    def _draw_input_fields(self, frame):
        """在 frame 上绘制输入框聚焦边框和用户已录入的值（不画任何默认/占位文字）"""
        fields = self._get_fields_for_tab(self._current_tab)
        for f in fields:
            fx, fy, fw, fh, ftype, fid = f
            val = self._field_values.get(fid, "")
            is_focused = (self._focused_field == fid)

            # 偏移字段使用实际绘制区域画聚焦框
            if fid == "char_x_offset":
                fx, fy, fw, fh = OFFSET_X_DRAW
            elif fid == "char_y_offset":
                fx, fy, fw, fh = OFFSET_Y_DRAW

            # 聚焦时画橙色边框
            if is_focused:
                cv2.rectangle(frame, (fx, fy), (fx + fw - 1, fy + fh - 1),
                              INPUT_FOCUS_COLOR, 2)

            # 只在用户已录入时画值
            if val:
                if fid in ("char_x_offset", "char_y_offset"):
                    # 偏移数字：小一号、不加粗
                    fscale = 0.6
                    fthick = 1
                    (tw, th), _ = cv2.getTextSize(val, INPUT_FONT, fscale, fthick)
                    tx = fx + (fw - tw) // 2
                    ty = fy + (fh + th) // 2 - 1 + 2  # 向下微调
                    cv2.putText(frame, val, (tx, ty), INPUT_FONT, fscale,
                                INPUT_TEXT_COLOR, fthick, cv2.LINE_AA)
                else:
                    fscale = 0.32 if fh < 20 else INPUT_FONT_SCALE
                    fthick = 1 if fh < 20 else INPUT_FONT_THICKNESS
                    (tw, th), _ = cv2.getTextSize(val, INPUT_FONT, fscale, fthick)
                    tx = fx + (fw - tw) // 2
                    ty = fy + (fh + th) // 2 - 1
                    cv2.putText(frame, val, (tx, ty), INPUT_FONT, fscale,
                                INPUT_TEXT_COLOR, fthick, cv2.LINE_AA)
            elif fid in ("hp_value", "mp_value"):
                # 空框显示占位文字
                ph = "百分比设置"
                (tw, th), _ = cv2.getTextSize(ph, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                tx = fx + (fw - tw) // 2
                ty = fy + (fh + th) // 2 - 1
                self._draw_cn_mixed(frame, ph, tx, ty, 0.42, (150, 150, 150))  # 原cv2字号，只中文换字体

    def _draw_y_range_btn(self, frame):
        """打怪页叠加"技能Y范围"按钮：data/skill_y_range_btn.jpg 原图135x39直接叠加(不缩放)，按下统一变暗(用户2026-09-07换图)"""
        bx, by, bw, bh = BTN_Y_RANGE
        if self._y_range_btn_img is None:
            _p = os.path.join(DATA_DIR, "skill_y_range_btn.jpg")
            if os.path.exists(_p):
                self._y_range_btn_img = cv2.imdecode(np.fromfile(_p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        img = self._y_range_btn_img
        if img is not None:
            ih, iw = img.shape[:2]
            dw, dh = min(iw, bw), min(ih, bh)  # 原图尺寸，不缩放
            roi = frame[by:by+dh, bx:bx+dw]
            src = img[:dh, :dw]
            if src.shape[2] == 4:
                a = src[:, :, 3:4].astype(np.float32) / 255.0
                fg = src[:, :, :3].astype(np.float32)
                bg = roi.astype(np.float32)
                frame[by:by+dh, bx:bx+dw] = (fg*a + bg*(1-a)).astype(np.uint8)
            else:
                frame[by:by+dh, bx:bx+dw] = src
        else:
            # 贴图缺失兜底：绿底白字
            draw_rounded_rect(frame, bx, by, bw, bh, 8, (46, 125, 50), -1)
            self._draw_cn_mixed(frame, "技能Y范围", bx+12, by+26, 0.55, (255, 255, 255))
        # 统一按压变暗特效（与其他按钮一致：按下叠半透明黑圆角）
        if self._pressed_btn == BTN_Y_RANGE:
            overlay = frame.copy()
            draw_rounded_rect(overlay, bx, by, bw, bh, 10, (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    def _draw_y_dialog(self, frame):
        """打怪Y范围弹窗（灰底白字/标题栏可拖拽/右上角X/确认取消，最上层），布局同倍率差弹窗"""
        self._update_y_dialog_positions()
        dlg_x, dlg_y = self._y_dialog_pos
        dlg_w, dlg_h = 320, 365
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (60, 60, 60), -1)
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (100, 100, 100), 1)
        # 标题栏（可拖拽）
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+50), (80, 80, 80), -1)
        self._draw_cn_mixed(frame, "主攻/群攻Y范围(px)", dlg_x+15, dlg_y+32, 0.6, (255, 255, 255))
        # 右上角X
        cx, cy, cw, ch = self._dlg_y_close_btn
        cv2.rectangle(frame, (cx, cy), (cx+cw-1, cy+ch-1), (80, 80, 80), -1)
        cv2.putText(frame, "X", (cx+7, cy+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        def _num_box(rect, fid, label):
            ix, iy, iw, ih = rect
            self._draw_cn_mixed(frame, label, dlg_x+20, iy+24, 0.5, (255, 255, 255))
            cv2.rectangle(frame, (ix, iy), (ix+iw-1, iy+ih-1), (0, 0, 0), -1)  # 黑底
            focused = (self._focused_field == fid)
            cv2.rectangle(frame, (ix, iy), (ix+iw-1, iy+ih-1),
                          (0, 165, 255) if focused else (255, 255, 255), 2 if focused else 1)
            val = self._field_values.get(fid, "")
            cv2.putText(frame, val, (ix+8, iy+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 1, cv2.LINE_AA)
        # 主攻分组小标题 + 上/下两条
        self._draw_cn_mixed(frame, "— 主攻 —", dlg_x+20, dlg_y+56, 0.48, (0, 200, 255))
        _num_box(self._dlg_y_up_input, "attack_y_up", "上方范围:")
        _num_box(self._dlg_y_down_input, "attack_y_down", "下方范围:")
        # 群攻分组小标题 + 上/下两条(用户2026-09-07：群攻独立Y范围)
        self._draw_cn_mixed(frame, "— 群攻 —", dlg_x+20, dlg_y+166, 0.48, (0, 200, 255))
        _num_box(self._dlg_aoe_y_up_input, "aoe_y_up", "上方范围:")
        _num_box(self._dlg_aoe_y_down_input, "aoe_y_down", "下方范围:")
        # 跳高打区间(最下一行,用户2026-09-09)：以人物为基准向上为负(同上方范围)，下限~上限两个框都填才启用，怪比人高落在区间内才走-跳-打；任一留空=不启用
        _sj_iy = self._dlg_slope_jump_ymin_input[1]
        self._draw_cn_mixed(frame, "跳高打(负):", dlg_x+14, _sj_iy+24, 0.5, (255, 255, 255))
        def _sj_box(rect, fid):
            ix, iy, iw, ih = rect
            cv2.rectangle(frame, (ix, iy), (ix+iw-1, iy+ih-1), (0, 0, 0), -1)  # 黑底
            _foc = (self._focused_field == fid)
            cv2.rectangle(frame, (ix, iy), (ix+iw-1, iy+ih-1),
                          (0, 165, 255) if _foc else (255, 255, 255), 2 if _foc else 1)
            cv2.putText(frame, self._field_values.get(fid, ""), (ix+8, iy+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 1, cv2.LINE_AA)
        _sj_box(self._dlg_slope_jump_ymin_input, "slope_jump_y_min")
        cv2.putText(frame, "~", (self._dlg_slope_jump_ymin_input[0]+77, _sj_iy+24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        _sj_box(self._dlg_slope_jump_ymax_input, "slope_jump_y_max")
        # 法师模式勾选(用户2026-09-09)：勾=法师(空中放不出,走-跳-落地放技能循环)；不勾=战士(跳后150ms空中放技能)
        _mx, _my, _mw, _mh = self._dlg_slope_mage_chk
        _mage_on = (self._field_values.get("slope_jump_mage") == "1")
        cv2.rectangle(frame, (_mx, _my), (_mx+_mw-1, _my+_mh-1),
                      (0, 165, 255) if _mage_on else (0, 0, 0), -1)
        cv2.rectangle(frame, (_mx, _my), (_mx+_mw-1, _my+_mh-1), (255, 255, 255), 1)
        if _mage_on:  # 白色对勾
            cv2.line(frame, (_mx+2, _my+8), (_mx+6, _my+11), (255, 255, 255), 2, cv2.LINE_AA)
            cv2.line(frame, (_mx+6, _my+11), (_mx+12, _my+3), (255, 255, 255), 2, cv2.LINE_AA)
        self._draw_cn_mixed(frame, "法师", _mx+_mw+2, _my+12, 0.42, (255, 255, 255))
        # 确认/取消
        ok_x, ok_y, ok_w, ok_h = self._dlg_y_ok_btn
        cv2.rectangle(frame, (ok_x, ok_y), (ok_x+ok_w-1, ok_y+ok_h-1), (0, 128, 0), -1)
        self._draw_cn_mixed(frame, "确认", ok_x+20, ok_y+20, 0.5, (255, 255, 255))
        cx2, cy2, cw2, ch2 = self._dlg_y_cancel_btn
        cv2.rectangle(frame, (cx2, cy2), (cx2+cw2-1, cy2+ch2-1), (128, 0, 0), -1)
        self._draw_cn_mixed(frame, "取消", cx2+20, cy2+20, 0.5, (255, 255, 255))

    def _draw_search_dialog(self, frame):
        """寻怪范围弹窗(灰底白字/标题栏可拖拽/右上X/确认取消,最上层)，布局同Y范围弹窗"""
        self._update_search_dialog_positions()
        dlg_x, dlg_y = self._search_dialog_pos
        dlg_w, dlg_h = 320, 250
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (60, 60, 60), -1)
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (100, 100, 100), 1)
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+50), (80, 80, 80), -1)
        self._draw_cn_mixed(frame, "寻怪范围(px) X共用/Y上下独立", dlg_x+12, dlg_y+32, 0.52, (255, 255, 255))
        cx, cy, cw, ch = self._dlg_search_close_btn
        cv2.rectangle(frame, (cx, cy), (cx+cw-1, cy+ch-1), (80, 80, 80), -1)
        cv2.putText(frame, "X", (cx+7, cy+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        def _num_box(rect, fid, label):
            ix, iy, iw, ih = rect
            self._draw_cn_mixed(frame, label, dlg_x+20, iy+24, 0.5, (255, 255, 255))
            cv2.rectangle(frame, (ix, iy), (ix+iw-1, iy+ih-1), (0, 0, 0), -1)
            focused = (self._focused_field == fid)
            cv2.rectangle(frame, (ix, iy), (ix+iw-1, iy+ih-1),
                          (0, 165, 255) if focused else (255, 255, 255), 2 if focused else 1)
            val = self._field_values.get(fid, "")
            cv2.putText(frame, val, (ix+8, iy+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 1, cv2.LINE_AA)
        _num_box(self._dlg_search_x_input, "far_range_x", "X 左右各:")
        _num_box(self._dlg_search_y_up_input, "far_range_y_up", "Y 上方:")
        _num_box(self._dlg_search_y_down_input, "far_range_y_down", "Y 下方:")
        # 群怪优先勾选(用户2026-09-09)：勾=射程外选锁按"群攻范围内数量最多"优先,不勾=按Y近X近最近原则
        _gx, _gy, _gw, _gh = self._dlg_search_group_chk
        _grp_on = (self._field_values.get("group_priority") == "1")
        cv2.rectangle(frame, (_gx, _gy), (_gx+_gw-1, _gy+_gh-1),
                      (0, 165, 255) if _grp_on else (0, 0, 0), -1)
        cv2.rectangle(frame, (_gx, _gy), (_gx+_gw-1, _gy+_gh-1), (255, 255, 255), 1)
        if _grp_on:  # 白色对勾
            cv2.line(frame, (_gx+2, _gy+8), (_gx+6, _gy+11), (255, 255, 255), 2, cv2.LINE_AA)
            cv2.line(frame, (_gx+6, _gy+11), (_gx+12, _gy+3), (255, 255, 255), 2, cv2.LINE_AA)
        self._draw_cn_mixed(frame, "群怪优先", _gx+_gw+3, _gy+12, 0.42, (255, 255, 255))
        # 群攻双向勾选(用户2026-09-09)：勾=群攻是近身双向技能,人物站怪群中心、左右两侧同时出伤害,不选边
        _dx, _dy, _dw, _dh = self._dlg_search_dual_chk
        _dual_on = (self._field_values.get("aoe_dual") == "1")
        cv2.rectangle(frame, (_dx, _dy), (_dx+_dw-1, _dy+_dh-1),
                      (0, 165, 255) if _dual_on else (0, 0, 0), -1)
        cv2.rectangle(frame, (_dx, _dy), (_dx+_dw-1, _dy+_dh-1), (255, 255, 255), 1)
        if _dual_on:  # 白色对勾
            cv2.line(frame, (_dx+2, _dy+8), (_dx+6, _dy+11), (255, 255, 255), 2, cv2.LINE_AA)
            cv2.line(frame, (_dx+6, _dy+11), (_dx+12, _dy+3), (255, 255, 255), 2, cv2.LINE_AA)
        self._draw_cn_mixed(frame, "群攻双向", _dx+_dw+3, _dy+12, 0.42, (255, 255, 255))
        ok_x, ok_y, ok_w, ok_h = self._dlg_search_ok_btn
        cv2.rectangle(frame, (ok_x, ok_y), (ok_x+ok_w-1, ok_y+ok_h-1), (0, 128, 0), -1)
        self._draw_cn_mixed(frame, "确认", ok_x+20, ok_y+20, 0.5, (255, 255, 255))
        cx2, cy2, cw2, ch2 = self._dlg_search_cancel_btn
        cv2.rectangle(frame, (cx2, cy2), (cx2+cw2-1, cy2+ch2-1), (128, 0, 0), -1)
        self._draw_cn_mixed(frame, "取消", cx2+20, cy2+20, 0.5, (255, 255, 255))

    def _draw_tp_setting_btn(self, frame):
        """叠加"瞬移设置"按钮：data/tp_setting_btn.png 原图135x39直接alpha叠加(不改背景/不缩放)，按下统一变暗"""
        bx, by, bw, bh = BTN_TP_SETTING
        if self._tp_setting_btn_img is None:
            _p = os.path.join(DATA_DIR, "tp_setting_btn.png")
            if os.path.exists(_p):
                self._tp_setting_btn_img = cv2.imdecode(np.fromfile(_p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        img = self._tp_setting_btn_img
        if img is not None:
            ih, iw = img.shape[:2]
            dw, dh = min(iw, bw), min(ih, bh)
            roi = frame[by:by+dh, bx:bx+dw]
            src = img[:dh, :dw]
            if src.shape[2] == 4:
                a = src[:, :, 3:4].astype(np.float32) / 255.0
                frame[by:by+dh, bx:bx+dw] = (src[:, :, :3].astype(np.float32)*a + roi.astype(np.float32)*(1-a)).astype(np.uint8)
            else:
                frame[by:by+dh, bx:bx+dw] = src
        else:
            draw_rounded_rect(frame, bx, by, bw, bh, 8, (46, 125, 50), -1)
            self._draw_cn_mixed(frame, "瞬移设置", bx+28, by+26, 0.6, (255, 255, 255))
        if self._pressed_btn == BTN_TP_SETTING:
            overlay = frame.copy()
            draw_rounded_rect(overlay, bx, by, bw, bh, 10, (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    def _draw_search_range_btn(self, frame):
        """叠加"寻怪范围"按钮：data/search_range_btn.jpg 原图135x39直接叠加(不缩放/不改背景)，按下统一变暗(用户2026-09-07替换动作录制)。"""
        bx, by, bw, bh = BTN_SEARCH_RANGE
        if self._search_range_btn_img is None:
            _p = os.path.join(DATA_DIR, "search_range_btn.jpg")
            if os.path.exists(_p):
                self._search_range_btn_img = cv2.imdecode(np.fromfile(_p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        img = self._search_range_btn_img
        if img is not None:
            ih, iw = img.shape[:2]
            dw, dh = min(iw, bw), min(ih, bh)
            roi = frame[by:by+dh, bx:bx+dw]
            src = img[:dh, :dw]
            if src.shape[2] == 4:
                a = src[:, :, 3:4].astype(np.float32) / 255.0
                frame[by:by+dh, bx:bx+dw] = (src[:, :, :3].astype(np.float32)*a + roi.astype(np.float32)*(1-a)).astype(np.uint8)
            else:
                frame[by:by+dh, bx:bx+dw] = src
        else:
            draw_rounded_rect(frame, bx, by, bw, bh, 8, (46, 125, 50), -1)
            self._draw_cn_mixed(frame, "寻怪范围", bx+20, by+26, 0.55, (255, 255, 255))
        if self._pressed_btn == BTN_SEARCH_RANGE:
            overlay = frame.copy()
            draw_rounded_rect(overlay, bx, by, bw, bh, 10, (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    def _draw_tp_dialog(self, frame):
        """瞬移设置弹窗（灰底/标题栏可拖拽/X/确认取消）：X瞬移距离(水平追怪)、Y瞬移距离(垂直,空=不启用)，默认空"""
        self._update_tp_dialog_positions()
        dlg_x, dlg_y = self._tp_dialog_pos
        dlg_w, dlg_h = 320, 280
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (60, 60, 60), -1)
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+dlg_h-1), (100, 100, 100), 1)
        cv2.rectangle(frame, (dlg_x, dlg_y), (dlg_x+dlg_w-1, dlg_y+50), (80, 80, 80), -1)
        self._draw_cn_mixed(frame, "瞬移距离(px)·空=不瞬移", dlg_x+15, dlg_y+32, 0.5, (255, 255, 255))
        cx, cy, cw, ch = self._dlg_tp_close_btn
        cv2.rectangle(frame, (cx, cy), (cx+cw-1, cy+ch-1), (80, 80, 80), -1)
        cv2.putText(frame, "X", (cx+7, cy+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        def _num_box(rect, fid, label):
            ix, iy, iw, ih = rect
            self._draw_cn_mixed(frame, label, dlg_x+20, iy+24, 0.5, (255, 255, 255))
            cv2.rectangle(frame, (ix, iy), (ix+iw-1, iy+ih-1), (0, 0, 0), -1)
            focused = (self._focused_field == fid)
            cv2.rectangle(frame, (ix, iy), (ix+iw-1, iy+ih-1),
                          (0, 165, 255) if focused else (255, 255, 255), 2 if focused else 1)
            val = self._field_values.get(fid, "")
            cv2.putText(frame, val, (ix+8, iy+24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 1, cv2.LINE_AA)
        _num_box(self._dlg_tp_x_input, "teleport_distance", "X瞬移距离:")
        _num_box(self._dlg_tp_y_input, "teleport_distance_y", "Y瞬移距离:")
        # 瞬移按键录入框：点一下→按键盘任意键即录入(与主界面其他键位框一致；空=不瞬移)
        kx, ky, kw, kh = self._dlg_tp_key_input
        self._draw_cn_mixed(frame, "瞬移按键:", dlg_x+20, ky+23, 0.5, (255, 255, 255))
        cv2.rectangle(frame, (kx, ky), (kx+kw-1, ky+kh-1), (0, 0, 0), -1)
        _k_focus = (self._focused_field == "teleport_key")
        cv2.rectangle(frame, (kx, ky), (kx+kw-1, ky+kh-1),
                      (0, 165, 255) if _k_focus else (255, 255, 255), 2 if _k_focus else 1)
        _kval = self._field_values.get("teleport_key", "")
        if _k_focus:
            self._draw_cn_mixed(frame, "按键盘...", kx+8, ky+22, 0.45, (0, 165, 255))
        elif _kval:
            cv2.putText(frame, str(_kval), (kx+8, ky+23), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 1, cv2.LINE_AA)
        else:
            self._draw_cn_mixed(frame, "空=不瞬移", kx+8, ky+22, 0.45, (140, 140, 140))
        ok_x, ok_y, ok_w, ok_h = self._dlg_tp_ok_btn
        cv2.rectangle(frame, (ok_x, ok_y), (ok_x+ok_w-1, ok_y+ok_h-1), (0, 128, 0), -1)
        self._draw_cn_mixed(frame, "确认", ok_x+20, ok_y+20, 0.5, (255, 255, 255))
        cx2, cy2, cw2, ch2 = self._dlg_tp_cancel_btn
        cv2.rectangle(frame, (cx2, cy2), (cx2+cw2-1, cy2+ch2-1), (128, 0, 0), -1)
        self._draw_cn_mixed(frame, "取消", cx2+20, cy2+20, 0.5, (255, 255, 255))

    def _get_fight_config(self):
        """获取打怪配置（供战斗逻辑调用）
        skill_random: 技能随机时间(+-ms)，影响主攻/群攻触发
        buff_random: BUFF技能随机时间(+-ms)，影响BUFF触发"""
        return {
            "atk1_key": self._field_values.get("atk1_key", ""),
            "atk1_interval": int(self._field_values.get("atk1_interval", "300") or "300"),
            "atk1_distance": int(self._field_values.get("atk1_distance", "150") or "150"),
            # 打怪Y上/下范围：以人物脚底为基点，有向值(上负下正，默认上-60/下+30，可改可负)；
            # 决策层取abs归一化为"上方容差/下方容差"正数(见combat_tick)，空则回退默认
            "attack_y_up": int(self._field_values.get("attack_y_up", str(-ATTACK_Y_UP)) or str(-ATTACK_Y_UP)),
            "attack_y_down": int(self._field_values.get("attack_y_down", str(ATTACK_Y_DOWN)) or str(ATTACK_Y_DOWN)),
            "aoe_key": self._field_values.get("aoe_key", ""),
            "aoe_interval": int(self._field_values.get("aoe_interval", "1000") or "1000"),
            "aoe_distance": int(self._field_values.get("aoe_distance", "200") or "200"),
            # 群攻独立Y范围(用户2026-09-07)：上方有向值(负,默认-80)/下方有向值(正,默认+60)，决策层abs归一化；空则回退默认
            "aoe_y_up": int(self._field_values.get("aoe_y_up", str(-AOE_Y_UP)) or str(-AOE_Y_UP)),
            "aoe_y_down": int(self._field_values.get("aoe_y_down", str(AOE_Y_DOWN)) or str(AOE_Y_DOWN)),
            # 跳高打区间(用户2026-09-09)：下限/上限两个都填了才启用，怪比人高落在[下限,上限]内走"走-跳-打"，超上限走梯子；任一留空=None=不启用
            "slope_jump_y_min": self._parse_optional_int(self._field_values.get("slope_jump_y_min", "")),
            "slope_jump_y_max": self._parse_optional_int(self._field_values.get("slope_jump_y_max", "")),
            # 法师模式(用户2026-09-09)：勾"法师"=True,空中放不出技能改走-跳-落地放；False=战士,跳后150ms空中放
            "slope_jump_mage": (self._field_values.get("slope_jump_mage", "") == "1"),
            # 寻怪范围(用户2026-09-07可自定义)：X=左右各寻怪距离(默认1300)，Y=同平台Y容差(默认150)；空则回退默认
            "far_range_x": int(self._field_values.get("far_range_x", str(COMBAT_FAR_RANGE)) or str(COMBAT_FAR_RANGE)),
            "far_range_y_up": int(self._field_values.get("far_range_y_up", str(FAR_RANGE_Y_UP_DEFAULT)) or str(FAR_RANGE_Y_UP_DEFAULT)),
            "far_range_y_down": int(self._field_values.get("far_range_y_down", str(FAR_RANGE_Y_DOWN_DEFAULT)) or str(FAR_RANGE_Y_DOWN_DEFAULT)),
            # 群怪优先(用户2026-09-09)：勾=True时,技能射程外的选锁不按最近、改锁群攻半径内数量最多的怪簇;近身有怪仍最近先打
            "group_priority": (self._field_values.get("group_priority", "") == "1"),
            # 群攻双向(用户2026-09-09)：勾=True时群攻按近身双向技能处理,人物站怪群X中心、左右两侧同时出伤害(不选边/不转身)
            "aoe_dual": (self._field_values.get("aoe_dual", "") == "1"),
            "jump_key": self._field_values.get("jump_key", "alt"),
            "teleport_key": self._field_values.get("teleport_key", ""),
            "teleport_distance": int(self._field_values.get("teleport_distance", "0") or "0"),      # X瞬移距离(水平追怪)，0/空=不水平瞬移
            "teleport_distance_y": int(self._field_values.get("teleport_distance_y", "0") or "0"),  # Y瞬移距离(垂直上下)，0/空=不垂直瞬移
            "skill_random": int(self._field_values.get("skill_random", "50") or "50"),
            "buff_random": int(self._field_values.get("buff_random", "100") or "100"),
            "buffs": [
                {
                    "key": self._field_values.get("buff%d_key" % i, ""),
                    "cd": int(self._field_values.get("buff%d_cd" % i, "60000") or "60000"),
                    "delay": int(self._field_values.get("buff%d_delay" % i, "500") or "500"),
                }
                for i in range(1, 7)
            ],
        }

    def _get_potion_config(self):
        """获取药品配置（供药品逻辑调用）"""
        return {
            "hp_key": self._field_values.get("hp_key", ""),
            "hp_value": int(self._field_values.get("hp_value", "0") or "0"),
            "mp_key": self._field_values.get("mp_key", ""),
            "mp_value": int(self._field_values.get("mp_value", "0") or "0"),
            "pet_key": self._field_values.get("pet_key", ""),
            "pet_cd": int(self._field_values.get("pet_cd", "60000") or "60000"),
            "pots": [
                {
                    "key": self._field_values.get("pot%d_key" % i, ""),
                    "cd": int(self._field_values.get("pot%d_cd" % i, "1000") or "1000"),
                }
                for i in range(1, 6)
            ],
            "potion_random": int(self._field_values.get("potion_random", "50") or "50"),
        }

    # ===== HP/MP自动吃药 =====

    def _is_key_field(self, fid):
        """判断字段是否为按键录入类型"""
        if fid == "teleport_key":   # 瞬移键在瞬移弹窗里录，不在FIGHT_FIELDS表中，单独认定为键位字段
            return True
        for f in FIGHT_FIELDS + POTION_FIELDS:
            if f[5] == fid:
                return f[4] == "key"
        return False

    def _poll_key_capture(self):
        """用GetAsyncKeyState轮询捕获按键（支持F1-F12/Ctrl/Shift/Home/End等所有键）
        只捕获新按下的键（不捕获按住不放的）"""
        if self._focused_field is None or not self._is_key_field(self._focused_field):
            return
        current_pressed = set()
        for vk in VK_POLL_LIST:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                current_pressed.add(vk)
        # 找出新按下的键（本次按下但上次没按下）
        new_keys = current_pressed - self._prev_key_states
        self._prev_key_states = current_pressed
        if new_keys:
            # 取第一个新按下的键
            vk = min(new_keys)
            name = VK_TO_NAME.get(vk, "vk_%d" % vk)
            self._field_values[self._focused_field] = name
            print("[按键录入] %s = %s (vk=0x%02X)" % (self._focused_field, name, vk))
            self._focused_field = None
            self._save_input_config()
            self._prev_key_states = set()
            self._last_input_change = time.time() * 1000

    def _poll_num_input(self):
        """用GetAsyncKeyState轮询捕获数字输入（全局有效，不依赖UI窗口焦点）
        支持主键盘0-9、小键盘0-9、退格、回车、ESC
        只捕获新按下的键（不捕获按住不放的）"""
        if self._focused_field is None or self._is_key_field(self._focused_field):
            return
        fid = self._focused_field
        if not hasattr(self, '_prev_num_states'):
            self._prev_num_states = set()
        # 轮询：主键盘0-9(0x30-0x39) + 小键盘0-9(0x60-0x69) + 退格(0x08) + 回车(0x0D) + ESC(0x1B)
        poll_vks = list(range(0x30, 0x3A)) + list(range(0x60, 0x6A)) + [0x08, 0x0D, 0x1B, 0xBD, 0x6D, 0xBE, 0x6E]
        current = set()
        for vk in poll_vks:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                current.add(vk)
        new_keys = current - self._prev_num_states
        self._prev_num_states = current
        if not new_keys:
            return
        vk = min(new_keys)
        # 解析按键
        if 0x30 <= vk <= 0x39:
            digit = chr(vk)
        elif 0x60 <= vk <= 0x69:
            digit = chr(vk - 0x60 + 0x30)  # 小键盘转数字字符
        elif vk == 0x08:
            # 退格
            cur = self._field_values.get(fid, "")
            if cur:
                self._field_values[fid] = cur[:-1]
                self._last_input_change = time.time() * 1000
            self._num_field_replace = False
            return
        elif vk == 0x0D:
            # 回车确认（HP/MP上限校验）
            val = self._field_values.get(fid, "")
            if val and fid in ("hp_value", "mp_value"):
                max_val = self._max_hp if fid == "hp_value" else self._max_mp
                if max_val > 0 and int(val) > max_val:
                    print("[校验] %s阈值 %s 超出上限 %d，已清空" % (fid, val, max_val))
                    self._field_values[fid] = ""
            self._focused_field = None
            self._save_input_config()
            self._prev_num_states = set()
            return
        elif vk == 0x1B:
            # ESC取消
            self._focused_field = None
            self._save_input_config()
            self._prev_num_states = set()
            return
        elif vk in (0xBD, 0x6D):
            # minus key - toggle negative sign for offset fields and scale fields
            if fid not in ("char_x_offset", "char_y_offset", "scale_x_offset", "scale_y_offset",
                           "attack_y_up", "attack_y_down", "aoe_y_up",
                           "slope_jump_y_min", "slope_jump_y_max"):  # 主攻/群攻Y上方范围+跳高打区间(向上为负)允许负数
                return
            cur = self._field_values.get(fid, "")
            if getattr(self, "_num_field_replace", False):
                new_val = "-"
                self._num_field_replace = False
            elif not cur.startswith("-"):
                new_val = "-" + cur
            else:
                new_val = cur[1:]
            if len(new_val) <= 10:
                self._field_values[fid] = new_val
                self._last_input_change = time.time() * 1000
                if fid in ("char_x_offset", "char_y_offset"):
                    self._offset_feedback_start = time.time() * 1000
                    self._offset_feedback_done = False
            return
        elif vk in (0xBE, 0x6E):
            # decimal point - only for scale fields
            if fid not in ("scale_x_offset", "scale_y_offset"):
                return
            cur = self._field_values.get(fid, "")
            if getattr(self, "_num_field_replace", False):
                new_val = "0."
                self._num_field_replace = False
            elif "." not in cur:
                new_val = cur + "."
            else:
                new_val = cur
            if len(new_val) <= 10:
                self._field_values[fid] = new_val
                self._last_input_change = time.time() * 1000
            return
        else:
            return
        # 数字输入：首次覆盖，后续追加
        cur = self._field_values.get(fid, "")
        if getattr(self, '_num_field_replace', False):
            new_val = digit
            self._num_field_replace = False
        else:
            new_val = cur + digit
        # HP/MP阈值百分比上限100
        if fid in ("hp_value", "mp_value") and int(new_val) > 100:
            return
        if len(new_val) <= 10:
            self._field_values[fid] = new_val
            self._last_input_change = time.time() * 1000
            if fid in ("char_x_offset", "char_y_offset"):
                self._offset_feedback_start = time.time() * 1000
                self._offset_feedback_done = False

    def _key_to_vk(self, key_name):
        """键名转虚拟键码"""
        if not key_name:
            return None
        kn = key_name.lower()
        if len(kn) == 1 and kn.isalnum():
            return ord(kn.upper())
        mapping = {
            "space": 0x20, "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
            "enter": 0x0D, "tab": 0x09, "backspace": 0x08, "esc": 0x1B,
            "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
            "pgup": 0x21, "pgdn": 0x22,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
            "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63,
            "num4": 0x64, "num5": 0x65, "num6": 0x66, "num7": 0x67,
            "num8": 0x68, "num9": 0x69,
            "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F,
            "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
            "printscreen": 0x2C,
        }
        if kn in mapping:
            return mapping[kn]
        if kn.startswith("f") and kn[1:].isdigit():
            n = int(kn[1:])
            if 1 <= n <= 12:
                return 0x6F + n
        if kn in "`-=[]\\;',./":
            return ord(kn)
        return None

    def _press_game_key(self, key_name, duration=None):
        """keybd_event扫描码点按（【冒险岛世界】实测吃keybd_event，SendInput单独发不动）+ AttachThreadInput强制前台。duration为按键保持ms，默认随机80-180"""
        vk = self._key_to_vk(key_name)
        if vk is None:
            _debug_log("按键未知: %s" % key_name)
            return
        if not self.hwnd:
            _debug_log("无窗口句柄")
            return
        if duration is None:
            duration = random.randint(80, 180)
        kernel32 = ctypes.windll.kernel32
        scan = user32.MapVirtualKeyW(vk, 0)
        EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0xA3, 0xA5}
        ext = 0x0001 if vk in EXTENDED_VKS else 0
        _debug_log("发键 %s vk=0x%02X scan=0x%02X ext=%d dur=%d" % (key_name, vk, scan, ext, duration))
        # 监管线：按跳跃键→跳后1秒静默背景帧差(空中镜头会抖,1秒必落地)。包try,绝不能影响正常发键
        try:
            if key_name and key_name == self._get_fight_config().get("jump_key"):
                self._wd_jump_gate_until = time.time() * 1000 + WD_JUMP_GATE_MS
        except Exception:
            pass

        # 【用户2026-09-08修复抢焦点】游戏已在前台：直接keydown→保持duration→keyup，不AttachThreadInput/不模拟Alt/
        # 不SetForegroundWindow/不切回。旧逻辑每次点按都强切前台再切回，爬梯跳/↑与加药高频按键时焦点来回抢、
        # 按键在切换间隙丢失(爬一半掉下来、药加不上)，每次还白耗100ms。游戏在前台直接发最稳最快。
        if user32.GetForegroundWindow() == self.hwnd:
            for mod_vk in (0x12, 0x11, 0x10):  # Alt,Ctrl,Shift：清卡住的修饰键避免Alt+Key组合
                if user32.GetAsyncKeyState(mod_vk) & 0x8000:
                    user32.keybd_event(mod_vk, user32.MapVirtualKeyW(mod_vk, 0), 0x0002, 0)
            user32.keybd_event(vk, scan, ext, 0)  # keydown
            time.sleep(duration / 1000.0)
            user32.keybd_event(vk, scan, ext | 0x0002, 0)  # keyup
            return

        # === 游戏不在前台：才拉前台后点按（兜底，挂机时游戏本就该在前台）===
        old_fg = user32.GetForegroundWindow()
        # === 强制把游戏窗口拉到前台 ===
        game_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()
        attached = False
        if game_thread != 0 and game_thread != cur_thread:
            attached = user32.AttachThreadInput(cur_thread, game_thread, True)

        # 先模拟按一下Alt键，绕过Windows SetForegroundWindow限制
        user32.keybd_event(0x12, 0, 0, 0)  # Alt down
        user32.keybd_event(0x12, 0, 0x0002, 0)  # Alt up
        user32.BringWindowToTop(self.hwnd)
        fg_ret = user32.SetForegroundWindow(self.hwnd)
        # 如果还没成功，再试一次（带最小化恢复）
        if user32.GetForegroundWindow() != self.hwnd:
            if user32.IsIconic(self.hwnd):
                user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.05)
        fg_now = user32.GetForegroundWindow()
        fg_ok = (fg_now == self.hwnd)
        if not fg_ok:
            _debug_log("[发键警告] 前台切换失败! fg_ret=%d 当前前台hwnd=%s 目标hwnd=%s attached=%d" % (
                fg_ret, fg_now, self.hwnd, attached))

        # === 用 keybd_event 发键(冒险岛世界实测 keybd_event 生效，SendInput扫描码单独发没动——用户2026-09-06，区别于旧游戏DirectInput) ===
        # 清除可能卡住的修饰键（Alt/Ctrl/Shift），避免Alt+Key组合
        for mod_vk in (0x12, 0x11, 0x10):  # Alt, Ctrl, Shift
            if user32.GetAsyncKeyState(mod_vk) & 0x8000:
                mod_scan = user32.MapVirtualKeyW(mod_vk, 0)
                user32.keybd_event(mod_vk, mod_scan, 0x0002, 0)
                _debug_log("清除卡住的修饰键 vk=0x%02X" % mod_vk)
        user32.keybd_event(vk, scan, ext, 0)  # keydown
        time.sleep(duration / 1000.0)
        user32.keybd_event(vk, scan, ext | 0x0002, 0)  # keyup
        _debug_log("keybd_event发键已发送 fg_ok=%d attached=%d dur=%d(游戏非前台,已拉前台)" % (fg_ok, attached, duration))

        # 分离线程（不切回old_fg：挂机应让游戏保持前台，切回反而抢焦点丢键）
        if attached:
            user32.AttachThreadInput(cur_thread, game_thread, False)

    def _send_win_key(self, vk, keyup):
        """keybd_event(扫描码)发/松键——【冒险岛世界】实测吃keybd_event、SendInput单独发不动(与怀旧服DirectInput相反)；keyup=True发松开。
        发前先把游戏窗口拉到前台(与_press_game_key一致)，否则键(尤其keyup)进不了游戏→松不开(用户2026-09-05)。"""
        try:
            if not self.hwnd:
                return
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            _up = 0x0002 if keyup else 0
            # 【用户2026-09-08修复抢焦点】游戏已在前台时直接发键：不AttachThreadInput、不模拟Alt、不SetForegroundWindow、
            # 不恢复old_fg——旧逻辑每次按键都"拉游戏前台→发键→切回原窗口"，爬梯/加药高频按键时焦点疯狂来回抢，
            # 按键在切换间隙丢失(↑没进游戏→爬一半掉下来、药加不上)，还白耗30~100ms。游戏在前台直接keybd_event最稳。
            if user32.GetForegroundWindow() == self.hwnd:
                user32.keybd_event(vk, scan, ext | _up, 0)
                return
            # === 游戏不在前台：才把游戏窗口拉到前台后发键（兜底，挂机时游戏本就该在前台，走到这属异常）===
            kernel32 = ctypes.windll.kernel32
            old_fg = user32.GetForegroundWindow()
            game_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
            cur_thread = kernel32.GetCurrentThreadId()
            attached = False
            if game_thread != 0 and game_thread != cur_thread:
                attached = user32.AttachThreadInput(cur_thread, game_thread, True)
            user32.keybd_event(0x12, 0, 0, 0)          # Alt down 绕过SetForegroundWindow限制
            user32.keybd_event(0x12, 0, 0x0002, 0)     # Alt up
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            if user32.GetForegroundWindow() != self.hwnd:
                if user32.IsIconic(self.hwnd):
                    user32.ShowWindow(self.hwnd, 9)
                user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.03)
            # === keybd_event发/松键(冒险岛世界实测 keybd_event 生效，SendInput扫描码单独发没动——用户2026-09-06) ===
            user32.keybd_event(vk, scan, ext | _up, 0)
            _debug_log("_send_win_key keybd_event vk=0x%02X keyup=%d(游戏非前台,已拉前台)" % (vk, keyup))
            # === 分离线程（不再SetForegroundWindow(old_fg)切回去：挂机就该让游戏保持前台，切回去反而抢焦点丢键）===
            if attached:
                user32.AttachThreadInput(cur_thread, game_thread, False)
        except Exception as _e:
            _debug_log("[发键] keybd_event异常: %s" % _e)

    def _hold_attack_key(self, key_name):
        """按住攻击键(keydown保持不放)：连续攻击连放，不像点按那样咔哒咔哒非人类。
        返回vk，供 _release_attack_key 松开。已在按则不重复。"""
        vk = self._key_to_vk(key_name)
        if vk is None or not self.hwnd:
            return None
        if self._combat_held_attack_key is not None and self._combat_held_attack_key != vk:
            self._release_attack_key()  # 换键先松开旧的
        if self._combat_held_attack_key == vk:
            return vk
        self._send_win_key(vk, keyup=False)  # keydown 保持
        self._combat_held_attack_key = vk
        return vk

    def _release_attack_key(self):
        """松开当前按住攻击键(keyup)。没按则忽略。"""
        if self._combat_held_attack_key is None:
            return
        vk = self._combat_held_attack_key
        self._send_win_key(vk, keyup=True)  # keyup 松开（【冒险岛世界】发/松都用keybd_event，同机制才松得掉）
        self._combat_held_attack_key = None

    def _detect_hp_mp_bars(self, frame):
        """检测HP/MP血条：搜底部50px（血条在y=770~778，距底部约30px），HSV颜色，HP在左MP在右"""
        if frame is None:
            return None, None
        h, w = frame.shape[:2]
        y_start = max(0, h - 50)  # 原h-25太小，血条在y=770距底部37px，需要搜到底部50px
        roi = frame[y_start:, :]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # HP红色
        hp_mask1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
        hp_mask2 = cv2.inRange(hsv, np.array([168, 80, 80]), np.array([180, 255, 255]))
        hp_mask = (hp_mask1 | hp_mask2) > 0
        # MP蓝紫色（样品色H≈160，范围放宽覆盖蓝到紫蓝）
        mp_mask = cv2.inRange(hsv, np.array([80, 50, 70]), np.array([175, 255, 255])) > 0
        hp_bar = self._find_longest_hbar(hp_mask, y_start)
        mp_bar = None
        if hp_bar:
            hx, hy, hw = hp_bar
            mp_bar = self._find_longest_hbar(mp_mask, y_start,
                                             x_min=hx + hw - 15, x_max=hx + hw + 160,
                                             y_center=hy, y_tol=6, max_w=120)
        if mp_bar is None:
            mp_bar = self._find_longest_hbar(mp_mask, y_start, max_w=120)

        # === 低血量兜底：红色/蓝色填充<20px时_find_longest_hbar返回None ===
        # 用上次稳定位置兜底（条的y坐标基本不变）
        if hp_bar is None and getattr(self, '_hp_bar_stable', None):
            hp_bar = self._hp_bar_stable
            _debug_log("HP颜色检测失败(<20px)，使用稳定缓存 y=%d" % hp_bar[1])
        if mp_bar is None and getattr(self, '_mp_bar_stable', None):
            mp_bar = self._mp_bar_stable
            _debug_log("MP颜色检测失败(<20px)，使用稳定缓存 y=%d" % mp_bar[1])
        # 首次就低血量：扫描底部25px任意红色像素找y坐标
        if hp_bar is None:
            for row in range(hp_mask.shape[0]):
                if hp_mask[row].sum() >= 1:
                    hp_bar = (0, y_start + row, 0)  # 占位，下面替换为固定位置
                    _debug_log("HP首次低血量，扫描到红色行 y=%d" % (y_start + row))
                    break
        if mp_bar is None and hp_bar:
            for row in range(mp_mask.shape[0]):
                if mp_mask[row].sum() >= 1:
                    mp_bar = (0, y_start + row, 0)
                    _debug_log("MP首次低血量，扫描到蓝色行 y=%d" % (y_start + row))
                    break

        # 血条/蓝条是游戏UI固定位置，按窗口尺寸比例换算。
        # 【冒险岛世界 2026-09-07 真机校准】基准=1296x759实测帧：HP槽左299宽139、MP槽左438宽148（两槽紧贴，宽度不同，必须分开）。
        # 旧1382基准(510/619/107)是旧版布局，在新版里整体偏右一个槽位→HP检测点落到MP槽、MP落到EXP槽，已废弃。
        # Y=h-28（真机在h-25基础上上移3px，HP/MP一起移）。血量多少由gray灰条模板在各自pct%位置判断，与位置无关，故直接赋固定UI槽位。
        FIXED_HP_LEFT = int(round(299 / 1296.0 * w))
        FIXED_HP_WIDTH = int(round(139 / 1296.0 * w))
        FIXED_MP_LEFT = int(round(438 / 1296.0 * w))
        FIXED_MP_WIDTH = int(round(148 / 1296.0 * w))
        FIXED_BAR_Y = h - 28  # 距窗口底部28px（2026-09-07真机：在h-25基础上上移3px，HP/MP一起移）
        hp_bar = (FIXED_HP_LEFT, FIXED_BAR_Y, FIXED_HP_WIDTH)
        mp_bar = (FIXED_MP_LEFT, FIXED_BAR_Y, FIXED_MP_WIDTH)
        _debug_log("血条检测(新版比例): hp=%s mp=%s 窗口=%dx%d" % (hp_bar, mp_bar, w, h))
        return hp_bar, mp_bar

    def _measure_bar_total_width(self, frame, x, y, color_type):
        """从条的左边界向右扫描，找到条的右边缘（非条内颜色），返回总宽度
        MP条内=B>180(亮蓝+暗蓝), HP条内=R>100(亮红+暗红)"""
        if frame is None or y >= frame.shape[0] or x >= frame.shape[1]:
            return None
        scan_y = y + 2
        if scan_y >= frame.shape[0]:
            scan_y = y
        out_count = 0
        for i in range(200):
            cx = x + i
            if cx >= frame.shape[1]:
                break
            b, g, r = frame[scan_y, cx]
            ri, gi, bi = int(r), int(g), int(b)
            if color_type == "hp":
                # 红色占优才算条内（排除灰色空白背景）
                in_bar = ri > 80 and ri - gi > 10 and ri - bi > 10
            else:
                # 蓝色占优才算条内（排除灰色空白背景）
                in_bar = bi > 100 and bi - ri > 10 and bi - gi > 10
            if in_bar:
                out_count = 0
            else:
                out_count += 1
                if out_count >= 5:
                    return i - 4
        return None

    def _find_longest_hbar(self, mask, y_offset, x_min=0, x_max=99999, y_center=None, y_tol=8, max_w=200):
        """跨所有行找最长水平连续段，可限制x范围和y中心，返回(x,y,w)或None"""
        if mask is None or mask.size == 0 or mask.sum() < 15:
            return None
        best = None
        best_len = 0
        for row in range(mask.shape[0]):
            abs_y = y_offset + row
            if y_center is not None and abs(abs_y - y_center) > y_tol:
                continue
            cols = np.where(mask[row])[0]
            cols = cols[(cols >= x_min) & (cols <= x_max)]
            if len(cols) < 15:
                continue
            gaps = np.diff(cols)
            splits = np.where(gaps > 3)[0]
            start = 0
            for sp in splits:
                seg_len = int(cols[sp]) - int(cols[start]) + 1
                if seg_len > best_len and 20 <= seg_len <= max_w:
                    best_len = seg_len
                    best = (int(cols[start]), abs_y, seg_len)
                start = sp + 1
            seg_len = int(cols[-1]) - int(cols[start]) + 1
            if seg_len > best_len and 20 <= seg_len <= max_w:
                best_len = seg_len
                best = (int(cols[start]), abs_y, seg_len)
        return best

    # HP/MP条参考色（从样品图取色，BGR格式）
    HP_REF_COLOR = (0, 0, 238)    # 红色
    MP_REF_COLOR = (222, 111, 0)  # 蓝青色
    COLOR_MATCH_DIST = 50         # 欧氏距离阈值，小于此值算同色

    # 灰槽判据：槽内填充(红/蓝/黄)是高饱和(BGR三通道极差>190)，空槽灰底是零饱和(极差≈0)，
    # 真机实测两簇极差 0 vs >190，鸿沟巨大，60 判灰非常稳。主判据用低饱和占比，不依赖模板，
    # 避免①gray模板缺失就永远不加血 ②CCOEFF对纯色MP蓝误给0.75高分导致满蓝狂按蓝。
    BLANK_GRAY_MAXDIFF = 60     # 单像素 BGR max-min 小于此值视为"灰像素"
    BLANK_GRAY_RATIO = 0.60    # 检测小块内灰像素占比≥此值=该位置是空槽=该补

    def _is_bar_blank_at(self, frame, bar, pct, color_type):
        """在pct%位置取小块判定是否为空槽(灰)。主判据=低饱和(灰)像素占比；
        gray_bar.png 模板匹配仅作辅助日志，模板缺失不再影响判定。"""
        if bar is None or frame is None:
            return False
        x, y, bw = bar
        check_x = x + int(bw * pct / 100.0)
        if check_x >= frame.shape[1] or check_x < 0:
            return False
        # 检测小块：以检测点为中心，高9宽10，落在槽填充厚度内
        px1, px2 = max(0, check_x - 4), min(frame.shape[1], check_x + 6)
        py1, py2 = max(0, y - 4), min(frame.shape[0], y + 5)
        patch = frame[py1:py2, px1:px2]
        if patch.size == 0:
            return False
        bgr = patch.reshape(-1, 3).astype(int)
        gray_pixels = ((bgr.max(axis=1) - bgr.min(axis=1)) < self.BLANK_GRAY_MAXDIFF)
        gray_ratio = float(gray_pixels.mean())
        blank = gray_ratio >= self.BLANK_GRAY_RATIO
        # 模板匹配（辅助，仅日志）
        tpl_val = -1.0
        if self._gray_bar_template is not None:
            th, tw = self._gray_bar_template.shape[:2]
            if patch.shape[0] >= th and patch.shape[1] >= tw:
                res = cv2.matchTemplate(patch, self._gray_bar_template, cv2.TM_CCOEFF_NORMED)
                tpl_val = float(res.max())
        _debug_log("空槽判定 %s: x=%d pct=%d 灰占比=%.2f 模板=%.3f -> %s" % (
            color_type, check_x, pct, gray_ratio, tpl_val, "空(补)" if blank else "有"))
        return blank

    def _init_digit_templates(self):
        """生成0-9数字模板（用cv2绘图，不依赖外部OCR）"""
        if self._digit_templates:
            return
        for d in range(10):
            img = np.zeros((26, 16), dtype=np.uint8)
            cv2.putText(img, str(d), (1, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2, cv2.LINE_AA)
            self._digit_templates[d] = img

    def _recognize_digits(self, crop):
        """从裁剪区域识别数字，返回数字字符串（含/）"""
        if crop is None or crop.size == 0:
            return ""
        self._init_digit_templates()
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # 白字阈值（游戏数字是亮白色）
        _, thresh = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # 按x坐标排序
        boxes = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if 3 <= w <= 22 and 7 <= h <= 24:
                boxes.append((x, y, w, h))
        boxes.sort(key=lambda b: b[0])
        result = ""
        for (x, y, w, h) in boxes:
            digit_img = thresh[y:y+h, x:x+w]
            digit_resized = cv2.resize(digit_img, (16, 26))
            best_d = -1
            best_score = -1
            for d, tmpl in self._digit_templates.items():
                res = cv2.matchTemplate(digit_resized, tmpl, cv2.TM_CCOEFF_NORMED)
                score = float(res[0][0])
                if score > best_score:
                    best_score = score
                    best_d = d
            if best_score > 0.35:
                result += str(best_d)
            elif w <= 4 and h >= 12:
                # 细竖线可能是 / 或 |
                result += "/"
        return result

    def _detect_hp_mp_max(self, frame):
        """用数字模板匹配读取HP/MP的 current/max，更新上限"""
        if frame is None or self.hwnd is None:
            return
        now = time.time() * 1000
        if now - self._last_max_check < 3000:
            return
        self._last_max_check = now
        import re
        for bar, attr in [(self._hp_bar, "_max_hp"), (self._mp_bar, "_max_mp")]:
            if bar is None:
                continue
            x, y, w = bar
            # 裁剪血条上方的文字区域（数字在条上方）
            y1 = max(0, y - 24)
            y2 = y
            x1 = max(0, x - 10)
            x2 = min(frame.shape[1], x + w + 10)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            try:
                text = self._recognize_digits(crop)
                m = re.search(r'(\d+)/(\d+)', text)
                if m:
                    max_val = int(m.group(2))
                    if 50 <= max_val <= 999999:
                        old_max = getattr(self, attr, 0)
                        if old_max != max_val:
                            setattr(self, attr, max_val)
                            print("[上限检测] %s=%d (识别:%s)" % (attr, max_val, text))
                            # 阈值为空时默认设成上限的一半
                            fid = "hp_value" if attr == "_max_hp" else "mp_value"
                            if not self._field_values.get(fid, ""):
                                half = max_val // 2
                                self._field_values[fid] = str(half)
                                self._save_input_config()
                                print("[上限检测] %s 默认阈值=%d" % (fid, half))
            except Exception as e:
                print("[上限检测] 出错:", e)

    def _init_yolo(self):
        """加载YOLO onnx模型（cv2.dnn，不依赖onnxruntime）"""
        if self._yolo_net is not None:
            return True
        # 优先使用手动选择的模型路径
        model_path = self._yolo_model_path
        if not model_path or not os.path.exists(model_path):
            model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.onnx")
        if not os.path.exists(model_path):
            model_path = "best.onnx"
        if not os.path.exists(model_path):
            print("[YOLO] 未找到模型文件，请点击'怪物数据'选择.onnx模型")
            return False
        try:
            self._yolo_net = cv2.dnn.readNetFromONNX(model_path)
            self._yolo_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            print("[YOLO] 模型加载成功:", model_path)
            return True
        except Exception as e:
            print("[YOLO] 加载失败:", e)
            return False

    def _detect_monsters(self, frame, crop_rect=None):
        """YOLO检测怪物，返回 [(x1,y1,x2,y2,score), ...]
        crop_rect: (x1,y1,x2,y2) 限定检测区域（人物+寻怪范围），None=全图检测。
        裁剪后只推理局部区域，坐标自动映射回原图。"""
        if frame is None or not self._init_yolo():
            return []
        _crop_x1 = _crop_y1 = 0
        if crop_rect is not None:
            cx1, cy1, cx2, cy2 = crop_rect
            fh, fw = frame.shape[:2]
            cx1, cy1 = max(0, cx1), max(0, cy1)
            cx2, cy2 = min(fw, cx2), min(fh, cy2)
            if cx2 <= cx1 or cy2 <= cy1:
                return []
            frame = frame[cy1:cy2, cx1:cx2]
            _crop_x1, _crop_y1 = cx1, cy1
        h, w = frame.shape[:2]
        INPUT_SIZE = 640
        scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
        new_w, new_h = int(w * scale), int(h * scale)
        pad_x = (INPUT_SIZE - new_w) // 2
        pad_y = (INPUT_SIZE - new_h) // 2
        resized = cv2.resize(frame, (new_w, new_h))
        padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        padded[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = resized
        blob = cv2.dnn.blobFromImage(padded, 1/255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
        self._yolo_net.setInput(blob)
        out = self._yolo_net.forward()[0]  # (300, 6) = [x1,y1,x2,y2,score,cls]
        detections = []
        for row in out:
            x1, y1, x2, y2, score, cls = row
            if score < self._yolo_conf:
                continue
            x1 = int((x1 - pad_x) / scale) + _crop_x1
            y1 = int((y1 - pad_y) / scale) + _crop_y1
            x2 = int((x2 - pad_x) / scale) + _crop_x1
            y2 = int((y2 - pad_y) / scale) + _crop_y1
            if x2 > x1 and y2 > y1:
                bw, bh = x2 - x1, y2 - y1
                # 大小过滤：怪通常宽30-110，高40-140，太大的是建筑误检
                if 20 <= bw <= 130 and 30 <= bh <= 160:
                    detections.append((x1, y1, x2, y2, float(score)))
        # NMS去重
        if detections:
            boxes = [[d[0], d[1], d[2]-d[0], d[3]-d[1]] for d in detections]
            scores = [d[4] for d in detections]
            indices = cv2.dnn.NMSBoxes(boxes, scores, self._yolo_conf, self._yolo_nms)
            detections = [detections[i] for i in indices] if len(indices) > 0 else []
        return detections

    def _detect_monster_hp_bars(self, frame, search_areas=None):
        """检测怪物头顶血条，返回 [(x, y, w, h), ...]
        search_areas: 限定搜索区域 [(x1,y1,x2,y2),...]，None则全屏搜索
        用于近战人物挡住怪物身体时，凭血条定位怪物"""
        if frame is None:
            return []
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # 怪物血条颜色（样本取色：绿色为主 H:35-80 S:90-255 V:80-255）
        m_g = cv2.inRange(hsv, np.array([35, 90, 80]), np.array([80, 255, 255]))
        # 红色（低血量时可能变红，保留兼容）
        m_r1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
        m_r2 = cv2.inRange(hsv, np.array([165, 80, 80]), np.array([180, 255, 255]))
        mask = cv2.bitwise_or(cv2.bitwise_or(m_r1, m_r2), m_g)
        # 【冒险岛世界2026-09-07样本校准】怪血条=黑槽+亮绿填充，常被等级字/竖边打断成几段；
        # 横向闭运算(7,2)把同一血条的断段连回一条，再按"扁横条"几何筛(真机绿条宽18-47/高2-7)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (7, 2)))
        bars = []
        areas = search_areas if search_areas else [(0, 0, w, h)]
        for (sx1, sy1, sx2, sy2) in areas:
            sx1, sy1 = max(0, sx1), max(0, sy1)
            sx2, sy2 = min(w, sx2), min(h, sy2)
            if sx2 <= sx1 or sy2 <= sy1:
                continue
            roi = mask[sy1:sy2, sx1:sx2]
            contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, bw, bh = cv2.boundingRect(cnt)
                # 血条特征：扁横条 宽>高*2，宽度15-90px，高度2-8px（样本校准：真机绿条宽18-47/高2-7）
                if bw > bh * 2 and 15 <= bw <= 90 and 2 <= bh <= 8:
                    bars.append((sx1 + x, sy1 + y, bw, bh))
        # 去重：位置接近的只保留一个
        if bars:
            filtered = []
            for b in sorted(bars, key=lambda x: x[2] * x[3], reverse=True):
                if not any(abs(b[0] - f[0]) < 25 and abs(b[1] - f[1]) < 12 for f in filtered):
                    filtered.append(b)
            bars = filtered
        return bars

    def _detect_damage_number(self, target_cx, target_cy):
        """【冒险岛世界】检测目标头顶上方是否飘出伤害数字（样本"15041"：红描边→橙黄主体渐变+黑描边）
        用途：攻击命中时怪头顶飘伤害数字，有数字=怪还活着；打一下既没血条也没伤害数字=空怪→drop换目标。
        参数：target_cx=目标中心X, target_cy=目标脚底Y
        原理（2026-09-07 真机样本校准，旧"红橙黄总量≥35"会把暖色背景/血条误判成数字导致空打不停）：
          1. 从怪物bbox找对应目标取头顶y1；只在头顶小窗(±30、上50下5)内搜
          2. 红簇 H0-12 ≥80像素（伤害数字独有，场景暖色/绿血条红簇≈0）且 橙黄簇 H14-35 ≥70
          3. 合并后存在团状笔画连通域(面积≥50、高≥9、非扁横条血条) → 判定有伤害数字
        返回：True=有伤害数字(怪活着), False=没有"""
        # 步骤1：从已检测怪物列表中找到离目标中心最近的怪物，获取其头顶y1
        target_y1 = None
        best_d = 999
        for (x1, y1, x2, y2, _) in self._monsters:
            cx = (x1 + x2) // 2  # 怪物中心X
            cy = y2               # 怪物脚底Y
            d = abs(cx - target_cx) + abs(cy - target_cy)  # 曼哈顿距离
            if d < best_d:
                best_d = d
                target_y1 = y1  # 记录怪物头顶Y
        if target_y1 is None:
            return False  # 没找到对应怪物，无法检测

        # 步骤2：截取游戏画面，在目标头顶上方区域搜索
        # 2026-09-07 CPU优化·截图共用：优先复用检测线程最新帧(战斗时250ms一帧,够用)，超龄才补截
        _rf = getattr(self, '_raw_frame', None)
        _rft = getattr(self, '_raw_frame_t', 0)
        if _rf is not None and (time.time() - _rft) <= 0.6:
            frame = _rf
        else:
            frame = self._capture_window()
        if frame is None:
            return False
        h, w = frame.shape[:2]
        # 搜索区域：限定在目标头顶附近(±30px，垂直头顶-50~+5)，别把附近怪/背景的误判成伤害数字(用户2026-09-05)
        rx1 = max(0, target_cx - 30)
        rx2 = min(w, target_cx + 30)
        ry1 = max(0, target_y1 - 50)  # 头顶上方50px
        ry2 = min(h, target_y1 + 5)   # 包含头顶位置
        if rx2 <= rx1 or ry2 <= ry1:
            return False
        roi = frame[ry1:ry2, rx1:rx2]  # 截取搜索区域

        # 步骤3：【冒险岛世界 2026-09-07 按伤害数字样本"15041"校准】数字=红描边→橙黄主体渐变。
        # 决定性特征：橙黄色在场景里到处都是(飞碟/平台/暖色岩石)，但高饱和"红簇"是伤害数字独有
        # （样本红簇约占彩色27%；绿血条/橙金场景/蓝背景的红簇≈0，实测≤22）。故以红簇为锚，
        # 再要求橙黄主体够量——两者同时满足才可能是数字，从根上杜绝把暖色背景/血条当伤害。
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        m_red = cv2.inRange(hsv, np.array([0, 70, 70]),  np.array([12, 255, 255]))   # 红(描边/阴影)
        m_org = cv2.inRange(hsv, np.array([14, 70, 70]), np.array([35, 255, 255]))   # 橙黄(主体)
        n_red, n_org = int(np.sum(m_red > 0)), int(np.sum(m_org > 0))
        if n_red < 80 or n_org < 70:
            return False  # 红簇不足=暖色背景/绿血条，不是伤害数字
        mask = cv2.bitwise_or(m_red, m_org)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

        # 步骤4：存在"团状笔画"连通域(面积≥50、高≥9、且不是扁横条血条)才算数字
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            _cx, _cy, _cw, _ch = cv2.boundingRect(cnt)
            _is_bar = (_cw > _ch * 2 and _ch <= 8)   # 扁横条=血条，排除
            if cv2.contourArea(cnt) >= 50 and _ch >= 9 and not _is_bar:
                return True
        return False

    def _load_blue_box(self):
        """加载蓝色框校准配置（一屏范围在小地图上的对应尺寸）"""
        if not os.path.exists(BLUE_BOX_FILE):
            self._blue_box = None
            return
        try:
            with open(BLUE_BOX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "width" in data and "height" in data:
                self._blue_box = {
                    "width": int(data["width"]),
                    "height": int(data["height"]),
                    "bl_ox": int(data.get("bl_ox", 0)),
                    "bl_oy": int(data.get("bl_oy", 0)),
                    "tr_ox": int(data.get("tr_ox", 0)),
                    "tr_oy": int(data.get("tr_oy", 0)),
                }
                print("[绿框] 加载成功: %dx%d 偏移(bl=%d,%d tr=%d,%d)" % (
                    self._blue_box["width"], self._blue_box["height"],
                    self._blue_box["bl_ox"], self._blue_box["bl_oy"],
                    self._blue_box["tr_ox"], self._blue_box["tr_oy"]))
            else:
                self._blue_box = None
        except Exception as e:
            print("[蓝色框] 加载失败:", e)
            self._blue_box = None

    def _save_blue_box(self):
        """保存蓝色框校准配置"""
        if not self._blue_box:
            return
        try:
            with open(BLUE_BOX_FILE, "w", encoding="utf-8") as f:
                json.dump(self._blue_box, f, indent=2)
            print("[绿框] 保存成功: %dx%d 偏移(bl=%d,%d tr=%d,%d)" % (
                self._blue_box["width"], self._blue_box["height"],
                self._blue_box["bl_ox"], self._blue_box["bl_oy"],
                self._blue_box["tr_ox"], self._blue_box["tr_oy"]))
        except Exception as e:
            print("[蓝色框] 保存失败:", e)

    def _start_blue_box_calibration(self):
        """开始绿框校准模式（两点定长方形）：点左下角+右上角，自动算另外两个角连成框。
        如有已保存配置，加载偏移量可直接微调。"""
        if not self.map_area_rect:
            self._add_log("请先绑定窗口检测小地图")
            return
        self._calibrating_blue_box = True
        self._selected_corner = None
        # 如有已保存配置，加载偏移量到角点，可直接微调
        if self._blue_box and "bl_ox" in self._blue_box:
            self._blue_box_corners = {
                "bl": (self._blue_box["bl_ox"], self._blue_box["bl_oy"]),
                "tr": (self._blue_box["tr_ox"], self._blue_box["tr_oy"]),
            }
            self._add_log("绿框校准：已加载保存的点，点击圆点选中后方向键微调，S保存")
            print("[绿框] 进入校准模式（已加载保存偏移量）")
        else:
            self._blue_box_corners = {"bl": None, "tr": None}
            self._add_log("绿框校准：请点击二个点")
            print("[绿框] 进入校准模式（新校准：左下+右上）")

    def _save_and_exit_blue_box_calibration(self):
        """保存绿框校准并退出（不管有没有改动点，有已保存配置就用已有的）"""
        bl = self._blue_box_corners.get("bl")
        tr = self._blue_box_corners.get("tr")
        if bl is not None and tr is not None:
            # 两个点都齐了：计算大小+偏移量，保存
            self._calc_blue_box_from_corners()
            if self._blue_box is not None:
                self._save_blue_box()
                self._add_log("绿框已保存: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
            else:
                self._add_log("绿框太小，保存失败")
        elif self._blue_box is not None:
            # 点没齐但有已保存配置：用已有的，不改动
            self._add_log("绿框保持原配置: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
        else:
            self._add_log("没有点也没有已保存配置，无法保存")
        self._calibrating_blue_box = False
        self._selected_corner = None
        print("[绿框] 保存并退出校准模式")

    def _handle_blue_box_click(self, map_x, map_y):
        """校准模式下处理小地图点击：两点定长方形（左下+右上），同方向覆盖，重叠区域无效"""
        if not self._calibrating_blue_box:
            return False
        if not self._player_map_pos:
            self._add_log("未检测到人物光点，无法记录偏移")
            return False
        px, py = self._player_map_pos
        offset_x = int(map_x - px)
        offset_y = int(map_y - py)
        # 点击已有角点附近=选中该方向（用显示位置判断，含自动计算的tl/br）
        for key, val in self._blue_box_corners.items():
            if val is not None:
                ox, oy = val
                cx, cy = px + ox, py + oy
                if abs(map_x - cx) < 8 and abs(map_y - cy) < 8:
                    self._selected_corner = key
                    self._add_log("选中%s角，方向键微调" % self._dir_name(key))
                    return True
        # 方向判断：左下象限直接左下，右上象限直接右上
        # 重叠区域（左上/右下）按主导方向判断（|x|和|y|谁大听谁的），避免第二个点被覆盖
        if offset_x < 0 and offset_y > 0:
            direction = "bl"
            dir_name = "左下"
        elif offset_x > 0 and offset_y < 0:
            direction = "tr"
            dir_name = "右上"
        elif offset_x < 0 and offset_y < 0:
            # 左上重叠区：更偏左→左下，更偏上→右上
            if abs(offset_x) >= abs(offset_y):
                direction = "bl"
                dir_name = "左下"
            else:
                direction = "tr"
                dir_name = "右上"
        elif offset_x > 0 and offset_y > 0:
            # 右下重叠区：更偏右→右上，更偏下→左下
            if abs(offset_x) >= abs(offset_y):
                direction = "tr"
                dir_name = "右上"
            else:
                direction = "bl"
                dir_name = "左下"
        else:
            # 正好在轴上（x=0或y=0）
            if offset_x < 0 or offset_y > 0:
                direction = "bl"
                dir_name = "左下"
            else:
                direction = "tr"
                dir_name = "右上"
        # 记录/覆盖该方向的偏移量
        is_override = self._blue_box_corners[direction] is not None
        self._blue_box_corners[direction] = (offset_x, offset_y)
        self._selected_corner = direction
        self._add_log("%s角: 偏移(%d, %d)%s" % (dir_name, offset_x, offset_y, "（覆盖）" if is_override else ""))
        # 两个点都齐了，计算蓝色框大小
        if all(v is not None for v in self._blue_box_corners.values()):
            self._calc_blue_box_from_corners()
        return True

    def _dir_name(self, key):
        """方向key转中文名（两点定长方形：只有左下/右上两个实点）"""
        return {"bl": "左下", "tr": "右上", "tl": "左上(算)", "br": "右下(算)"}.get(key, key)

    def _calc_blue_box_from_corners(self):
        """两个对角点（左下+右上）齐了，自动算左上角/右下角，得蓝色框宽高"""
        bl = self._blue_box_corners.get("bl")
        tr = self._blue_box_corners.get("tr")
        if bl is None or tr is None:
            return
        bl_ox, bl_oy = bl  # 左下：x<0, y>0
        tr_ox, tr_oy = tr  # 右上：x>0, y<0
        # 左上角=(左下x, 右上y)，右下角=(右上x, 左下y)
        width = tr_ox - bl_ox
        height = bl_oy - tr_oy
        if width > 10 and height > 10:
            self._blue_box = {
                "width": width, "height": height,
                "bl_ox": bl_ox, "bl_oy": bl_oy,
                "tr_ox": tr_ox, "tr_oy": tr_oy,
            }
            self._add_log("绿框大小: %dx%d，S保存" % (width, height))
            print("[绿框] 两点定框: %dx%d 偏移(bl=%d,%d tr=%d,%d)" % (width, height, bl_ox, bl_oy, tr_ox, tr_oy))
        else:
            self._add_log("绿框太小，请重新校准")

    def _handle_blue_box_key(self, key_code):
        """校准模式下键盘方向键微调选中方向的偏移量，S保存，Q退出"""
        if not self._calibrating_blue_box:
            return False
        if self._selected_corner is None or self._blue_box_corners.get(self._selected_corner) is None:
            return False
        ox, oy = self._blue_box_corners[self._selected_corner]
        step = 1
        if key_code == 0x25:  # 左
            ox -= step
        elif key_code == 0x27:  # 右
            ox += step
        elif key_code == 0x26:  # 上
            oy -= step
        elif key_code == 0x28:  # 下
            oy += step
        elif key_code == 0x53:  # S 保存
            self._calc_blue_box_from_corners()
            if self._blue_box is None:
                self._add_log("点没齐，无法保存（需要左下+右上两个点）")
                return True
            self._save_blue_box()
            self._calibrating_blue_box = False
            self._add_log("蓝色框已保存: %dx%d" % (self._blue_box["width"], self._blue_box["height"]))
            return True
        elif key_code == 0x51:  # Q 退出校准
            self._calibrating_blue_box = False
            self._add_log("退出蓝色框校准")
            return True
        else:
            return False
        self._blue_box_corners[self._selected_corner] = (ox, oy)
        if all(v is not None for v in self._blue_box_corners.values()):
            self._calc_blue_box_from_corners()
        return True

    def _calc_blue_box_pos(self, mx, my):
        """绿框(=镜头视野)在小地图上的位置：以光点为中心+边缘钳制(左4/右7/上5/下5)。
        lock_screen_from_dot(大屏幕人物框)与_draw_blue_box(小地图绿框)共用，保证两个框位置永远一致。
        返回(box_x,box_y)；绿框未校准或区域无效返回None。"""
        r = getattr(self, 'map_area_rect', None)
        if not self._blue_box or not r or r.get("width", 0) <= 0:
            return None
        bw, bh = self._blue_box["width"], self._blue_box["height"]
        mw, mh = r["width"], r["height"]
        box_x = int(mx - bw // 2)
        box_y = int(my - bh // 2)
        if box_x < 4:
            box_x = 4
        if box_x > mw - 7 - bw:
            box_x = mw - 7 - bw
        if box_y < 5:
            box_y = 5
        if box_y > mh - 5 - bh:
            box_y = mh - 5 - bh
        return box_x, box_y

    def _draw_blue_box(self, map_frame):
        """在小地图帧上绘制绿框（校准模式：半透明线+圆点；正常模式：实线+无圆点，用偏移量绘制）"""
        if self._calibrating_blue_box:
            if not self._player_map_pos:
                return
            px, py = self._player_map_pos
            h, w = map_frame.shape[:2]
            bl = self._blue_box_corners.get("bl")
            tr = self._blue_box_corners.get("tr")
            # 新校准（两个点都没有）：中间显示提示文字
            if bl is None and tr is None:
                tip = "请点击二个点"
                (tw, th), _ = cv2.getTextSize(tip, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                self._draw_cn_mixed(map_frame, tip, w // 2 - tw // 2, h // 2, 0.5, (0, 255, 255))  # 原cv2字号，只中文换字体
            # 画两个圆点（左下/右上），选中的变黄
            for key, val in [("bl", bl), ("tr", tr)]:
                if val is None:
                    continue
                ox, oy = val
                cx, cy = int(px + ox), int(py + oy)
                cx = max(0, min(cx, w - 1))
                cy = max(0, min(cy, h - 1))
                color = (0, 255, 255) if key == self._selected_corner else (0, 255, 0)
                cv2.circle(map_frame, (cx, cy), 3, color, -1)
            # 两个点都齐了：画半透明绿线长方形
            if bl is not None and tr is not None:
                tl_pt = (max(0, min(int(px + bl[0]), w - 1)), max(0, min(int(py + tr[1]), h - 1)))
                br_pt = (max(0, min(int(px + tr[0]), w - 1)), max(0, min(int(py + bl[1]), h - 1)))
                bl_pt = (max(0, min(int(px + bl[0]), w - 1)), max(0, min(int(py + bl[1]), h - 1)))
                tr_pt = (max(0, min(int(px + tr[0]), w - 1)), max(0, min(int(py + tr[1]), h - 1)))
                pts = [tl_pt, tr_pt, br_pt, bl_pt]
                # 半透明绿线：先在overlay上画，再混合
                overlay = map_frame.copy()
                cv2.polylines(overlay, [np.array(pts, np.int32).reshape((-1, 1, 2))], True, (0, 255, 0), 1)
                cv2.addWeighted(overlay, 0.4, map_frame, 0.6, 0, map_frame)
        elif self._blue_box and self._player_map_pos:
            # 正常模式：跟随=以光点为中心+到边贴边；死区=冻结绿框(镜头不动)。与lock_screen共用算框方法，两框一致
            px, py = self._player_map_pos
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            follow_pos = self._calc_blue_box_pos(px, py)
            if follow_pos is not None:
                frozen_pos = self._blue_box_deadzone_pos
                if self._camera_state == "deadzone" and frozen_pos is not None:
                    box_x, box_y = frozen_pos
                else:
                    box_x, box_y = follow_pos
                cv2.rectangle(map_frame, (box_x, box_y), (box_x + bw, box_y + bh), (0, 255, 0), 1)


    def _load_bg_regions(self):
        """从配置文件加载检测框位置（data/bg_detect_regions.json），加载失败用默认值"""
        try:
            if os.path.exists(BG_DETECT_REGIONS_FILE):
                with open(BG_DETECT_REGIONS_FILE, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, list) and len(data) == 3:
                    self._bg_regions = [dict(r) for r in data]
                    return
        except Exception as e:
            print("[镜头检测] 加载配置失败:", e)
        self._bg_regions = [dict(r) for r in BG_DETECT_DEFAULT_REGIONS]

    def _save_bg_regions(self):
        """保存检测框位置到配置文件（data/bg_detect_regions.json）"""
        try:
            with open(BG_DETECT_REGIONS_FILE, "w", encoding="utf-8") as fp:
                json.dump(self._bg_regions, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[镜头检测] 保存配置失败:", e)

    def _detect_camera_motion(self, frame=None):
        """镜头死区检测：三区域帧间差异对比。直接用主循环已截好的frame（不隐藏蒙板，不闪烁）。
        三个检测区域在屏幕边缘/角落，蒙板绘制内容在中间，不会干扰背景差异检测。
        状态机：deadzone(镜头不动)→following(镜头在动)，进入死区时冻结绿框位置。"""
        if not self._player_map_pos or not self.window_rect:
            return
        if frame is None:
            # 2026-09-07 CPU优化·截图共用：调用方未传帧时复用检测线程最新帧，超龄才补截
            _rf = getattr(self, '_raw_frame', None)
            _rft = getattr(self, '_raw_frame_t', 0)
            if _rf is not None and (time.time() - _rft) <= 0.6:
                frame = _rf
            else:
                frame = self._capture_window()
        if frame is None:
            return
        fh, fw = frame.shape[:2]
        motion_count = 0
        for i, reg in enumerate(self._bg_regions):
            x1 = max(0, min(reg["x"], fw - 1))
            y1 = max(0, min(reg["y"], fh - 1))
            x2 = min(fw, x1 + reg["w"])
            y2 = min(fh, y1 + reg["h"])
            # 内缩3像素：排除蒙板自己画在ROI边缘的检测框线，否则框线红/绿变色会被帧差捕捉，形成自激振荡误判
            _PAD = 3
            cx1, cy1, cx2, cy2 = x1 + _PAD, y1 + _PAD, x2 - _PAD, y2 - _PAD
            if cx2 <= cx1 or cy2 <= cy1:
                self._bg_diff_values[i] = 0.0
                continue
            roi = frame[cy1:cy2, cx1:cx2]
            if self._bg_last_frames[i] is not None and self._bg_last_frames[i].shape == roi.shape:
                diff = cv2.absdiff(roi, self._bg_last_frames[i])
                self._bg_diff_values[i] = float(diff.mean())
                if self._bg_diff_values[i] > BG_DIFF_THRESHOLD:
                    motion_count += 1
            self._bg_last_frames[i] = roi.copy()
        # 判断光点是否在移动（光点不动=人物不动=镜头大概率不动）
        dot_moving = False
        if self._last_dot_pos is not None:
            dot_dx = self._player_map_pos[0] - self._last_dot_pos[0]
            dot_dy = self._player_map_pos[1] - self._last_dot_pos[1]
            if abs(dot_dx) > 0 or abs(dot_dy) > 0:
                dot_moving = True
        self._last_dot_pos = (self._player_map_pos[0], self._player_map_pos[1])
        self._bg_motion_count = motion_count  # 保存当前帧几处背景在动，供蒙板三框实时着色
        # 状态机切换（前馈渐变曲线匹配镜头物理：启动0→2约60帧/1秒，匀速保持2，停止2→0约30帧/0.5秒后切死区）
        if dot_moving and motion_count >= BG_MOTION_MIN_REGIONS:
            # 跟随状态：光点在动且3处背景都在动=镜头在动
            self._stop_frame_count = 0  # 重置停止计数器
            self._follow_frame_count += 1  # 跟随帧数递增
            # 前馈启动渐变：0→60帧从0线性增大到2（模拟镜头加速约1秒），60帧后保持2（匀速）
            if self._follow_frame_count <= 60:
                self._feedforward_strength = 2.0 * (self._follow_frame_count / 60.0)
            else:
                self._feedforward_strength = 2.0
            if self._camera_state != "following":
                self._camera_state = "following"
                self._follow_frame_count = 1  # 刚进入跟随，从第1帧开始渐变
                self._feedforward_strength = 2.0 / 60.0  # 第1帧前馈很小
                # 跟随状态：绿框每帧以光点为中心（_calc_blue_box_pos），不用增量更新
                self._blue_box_follow_pos = None
                self._blue_box_deadzone_pos = None
                self._last_follow_dot_pos = (self._player_map_pos[0], self._player_map_pos[1]) if self._player_map_pos else None
                print("[镜头检测] 切到跟随状态（前馈启动渐变0→2约60帧）")
            else:
                # 跟随状态前馈偏移：记录光点移动量，lock_screen_from_dot里用前馈强度系数乘
                if self._player_map_pos:
                    self._last_follow_dot_pos = (self._player_map_pos[0], self._player_map_pos[1])
        else:
            # 光点停了或背景不动：前馈衰减渐变（2→0约30帧/0.5秒，模拟镜头惯性减速），30帧后切死区
            self._follow_frame_count = 0  # 重置跟随计数器
            self._stop_frame_count += 1  # 停止帧数递增
            # 前馈衰减渐变：30帧内从2线性减到0（模拟镜头惯性减速约0.5秒）
            if self._stop_frame_count <= 30:
                self._feedforward_strength = 2.0 * (1.0 - self._stop_frame_count / 30.0)
            else:
                self._feedforward_strength = 0.0
            # 30帧后确认镜头真停了，切死区
            if self._stop_frame_count >= 30 and self._camera_state != "deadzone":
                self._camera_state = "deadzone"
                # 进入死区(镜头停止)：以光点为中心冻结绿框位置，之后绿框钉住、光点在固定框内移动
                _mp_freeze = self._player_map_pos
                if _mp_freeze and self._blue_box:
                    self._blue_box_deadzone_pos = self._calc_blue_box_pos(_mp_freeze[0], _mp_freeze[1])
                self._blue_box_follow_pos = None
                self._feedforward_strength = 0.0
                print("[镜头检测] 切到死区状态（前馈衰减30帧后确认）")

    def lock_screen_from_dot(self):
        """【光点锁定·不用倍率】小地图光点 → 归一化位置 → 游戏屏幕坐标(锁定人物真实坐标).
        原理: 小地图三特征定位裁剪(map_area_rect)映射到显示窗口; 光点在此窗口内归一化(0~1),
              归一化位置 × 游戏窗口尺寸 = 人物在游戏屏幕的坐标. 归一化尺度不变, 任何地图一套通用.
        返回: (screen_x, screen_y) 或 None"""
        r = getattr(self, 'map_area_rect', None)
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return None
        if not self._player_map_pos:
            return None
        mx, my = self._player_map_pos  # 修复: 解包元组, 不是重复赋值
        win_w, win_h = getattr(self, '_target_window_size', None) or (0, 0)
        if win_w <= 0 or win_h <= 0:
            # _target_window_size未记录时，用当前window_rect的宽高（窗口实际大小，与蒙板同一坐标系）
            _wr = getattr(self, 'window_rect', None)
            if _wr and _wr.get("width", 0) > 0 and _wr.get("height", 0) > 0:
                win_w, win_h = _wr["width"], _wr["height"]
            else:
                if getattr(self, 'frame_count', 0) % 30 == 0:
                    print("[光点锁定] 失败: 窗口大小无效 target=(%d,%d) rect=%s" % (win_w, win_h, _wr))
                return None
        if self._blue_box:
            # 跟随(following)：绿框以光点为中心+到边贴边；死区(deadzone,镜头不动)：绿框冻结，光点在固定框内归一化
            bw, bh = self._blue_box["width"], self._blue_box["height"]
            follow_pos = self._calc_blue_box_pos(mx, my)
            if follow_pos is None:
                return None
            frozen_pos = self._blue_box_deadzone_pos
            if self._camera_state == "deadzone" and frozen_pos is not None:
                box_x, box_y = frozen_pos  # 镜头不动：绿框钉在进入死区那一刻的位置
            else:
                box_x, box_y = follow_pos  # 跟随/兜底：以光点为中心
                # 跟随状态前馈偏移：绿框沿光点移动方向提前2倍光点移动量，补偿镜头缓冲延迟
                _last_dot = getattr(self, '_last_follow_dot_pos', None)
                if _last_dot and self._player_map_pos:
                    _fdx = self._player_map_pos[0] - _last_dot[0]
                    _fdy = self._player_map_pos[1] - _last_dot[1]
                    if _fdx != 0 or _fdy != 0:
                        _ff = getattr(self, '_feedforward_strength', 2.0)
                        if _ff > 0:
                            box_x += int(_fdx * _ff)  # 前馈渐变：人物在动时强度=2，停了后逐渐减到0
                            box_y += int(_fdy * _ff)
                        # 边缘钳制
                        _r = getattr(self, 'map_area_rect', None)
                        if _r and self._blue_box:
                            _bw, _bh = self._blue_box["width"], self._blue_box["height"]
                            _mw, _mh = _r["width"], _r["height"]
                            box_x = max(4, min(box_x, _mw - 7 - _bw))
                            box_y = max(5, min(box_y, _mh - 5 - _bh))
            # 方案B·直接映射：光点在绿框中的偏移 × 缩放比例(窗口/绿框) = 游戏窗口坐标，不用先算比例再乘窗口
            offset_x = mx - box_x
            offset_y = my - box_y
            offset_x = max(0, min(bw, offset_x))  # 钳制偏移在绿框范围内（等价于比例0~1）
            offset_y = max(0, min(bh, offset_y))
            scale_x = win_w / float(bw) if bw > 0 else 1.0
            scale_y = win_h / float(bh) if bh > 0 else 1.0
            rx = offset_x / float(bw) if bw > 0 else 0.5  # 仅用于日志显示
            ry = offset_y / float(bh) if bh > 0 else 0.5
            mode = "绿框"
        else:
            # 未校准：回退旧方案（整个小地图归一化，到边时不准）
            offset_x = mx
            offset_y = my
            scale_x = win_w / float(r["width"]) if r["width"] > 0 else 1.0
            scale_y = win_h / float(r["height"]) if r["height"] > 0 else 1.0
            rx = mx / float(r["width"])
            ry = my / float(r["height"])
            mode = "全图"
        sx = int(offset_x * scale_x)
        sy = int(offset_y * scale_y)
        # 去掉EMA平滑：直接用当前帧坐标，反应更快不延迟（用户要求跟手，抖动可接受）
        if getattr(self, 'frame_count', 0) % 20 == 0:
            _debug_log("[光点锁定] 光点(%d,%d) %s偏移(%d,%d)缩放(%.2f,%.2f)屏幕(%d,%d)" % (mx, my, mode, offset_x, offset_y, scale_x, scale_y, sx, sy))
        if getattr(self, 'frame_count', 0) % 30 == 0:
            _fz = getattr(self, '_blue_box_deadzone_pos', None)
            _cs = getattr(self, '_camera_state', '?')
            print("[光点锁定] 成功: 光点(%d,%d) state=%s box=(%d,%d) 偏移(%d,%d) 缩放(%.2f,%.2f) 屏幕(%d,%d) win=%dx%d" % (
                mx, my, _cs, box_x, box_y, offset_x, offset_y, scale_x, scale_y, sx, sy, win_w, win_h))
        return (sx, sy)

    def monster_to_map(self, monster_sx, monster_sy):
        """【光点锁定·不用倍率】怪物屏幕坐标 → 小地图显示位置(反用归一化, 不用倍率).
        原理: 人物屏幕坐标(锁定的) + 怪物-人物屏幕偏移 归一化 → 映射到小地图显示框内."""
        r = getattr(self, 'map_area_rect', None)
        if not r or r.get("width", 0) <= 0 or r.get("height", 0) <= 0:
            return None
        pos = self._player_screen_pos
        if not pos:
            return None
        psx, psy = pos
        win_w, win_h = getattr(self, '_target_window_size', None) or (0, 0)
        if win_w <= 0 or win_h <= 0:
            # _target_window_size未记录时，用当前window_rect的宽高（窗口实际大小，与蒙板同一坐标系）
            _wr = getattr(self, 'window_rect', None)
            if _wr and _wr.get("width", 0) > 0 and _wr.get("height", 0) > 0:
                win_w, win_h = _wr["width"], _wr["height"]
            else:
                if getattr(self, 'frame_count', 0) % 30 == 0:
                    print("[光点锁定] 失败: 窗口大小无效 target=(%d,%d) rect=%s" % (win_w, win_h, _wr))
                return None
        dx_ratio = (monster_sx - psx) / float(win_w)
        dy_ratio = (monster_sy - psy) / float(win_h)
        p_rx = psx / float(win_w)
        p_ry = psy / float(win_h)
        rx = p_rx + dx_ratio
        ry = p_ry + dy_ratio
        map_x = int(r["left"] + rx * r["width"])
        map_y = int(r["top"] + ry * r["height"])
        return (map_x, map_y)

    def _get_player_screen_pos(self, frame):
        """获取人物在游戏画面中的坐标: 多特征融合模板匹配(已含每特征offset到脚)。
        2026-09-07用户定稿：匹配失败不设1秒宽限、也不清空——点停在最后消失位置，后台每帧继续全图搜，
        _match_character内部ROI找不到会立即全图重搜(瞬移也允许远距同步)，一搜到新位置立刻同步。
        另标注本帧匹配状态供边缘自救用(用户2026-09-07)：
          _char_match_ok=True/False；丢失时 _char_lost_edge='left'/'right'(贴地图边)/None(中间,原地等重扫)。"""
        # 1) 多特征融合匹配(每个特征独立offset到人物脚，一致性校验+加权平均)
        match = self._match_character(frame)
        if match:
            mx, my, _ = match
            self._char_match_ok = True
            self._char_lost_edge = None
            return (mx, my)  # 已含特征偏移，不再加全局偏移
        # 2) 找不到：停在最后消失位置（无限期保持，不乱飞、不判丢），直到全图重新搜到再同步
        self._char_match_ok = False
        last_pos = getattr(self, '_last_char_match_pos', None)
        # 判定丢失位置：最后脚X距画面左右边≤CHAR_EDGE_MARGIN=贴地图边缘(触发向中间自救)，否则=中间(原地等)
        self._char_lost_edge = None
        if last_pos is not None and frame is not None:
            _fw = frame.shape[1]
            if last_pos[0] <= CHAR_EDGE_MARGIN:
                self._char_lost_edge = 'left'
            elif last_pos[0] >= _fw - CHAR_EDGE_MARGIN:
                self._char_lost_edge = 'right'
        if last_pos:
            return last_pos
        # 3) 从未成功定位过才返回None
        return None

    def _draw_monster_overlay(self, frame, player_pos):
        """在游戏画面上画怪物框、人物位置、连线、距离、偏移信息（调试用，已由透明蒙板取代）"""
        disp = frame.copy()
        px, py = player_pos
        x_off = int(self._field_values.get("char_x_offset", "0") or "0")
        y_off = int(self._field_values.get("char_y_offset", "0") or "0")
        # 人物参考点（黄色实心圆）
        cv2.circle(disp, (px, py), 6, (0, 255, 255), -1)
        cv2.circle(disp, (px, py), 9, (0, 255, 255), 1)
        cv2.putText(disp, "PLAYER(%d,%d) X%+d Y%+d" % (px, py, x_off, y_off),
                    (px + 12, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        # 怪物框 + 连线 + 距离
        for i, (x1, y1, x2, y2, score) in enumerate(self._monsters):
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(disp, "M%d %.0f%%" % (i, score * 100), (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            cv2.line(disp, (px, py), (cx, cy), (0, 165, 255), 1)
            dist = int(np.sqrt((cx - px) ** 2 + (cy - py) ** 2))
            mid_x, mid_y = (px + cx) // 2, (py + cy) // 2
            cv2.putText(disp, str(dist), (mid_x, mid_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 165, 255), 1)
        # 左上角状态栏
        cv2.putText(disp, "Monsters:%d  Offset X:%d Y:%d" % (len(self._monsters), x_off, y_off),
                    (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        return disp

    MP_LABEL_THRESH = 0.85   # MP标志匹配阈值(用户2026-09-07：0.75→0.85更严；真机正常游戏0.97稳过，活动/小退底部带0.46被拦)
    def _is_mp_label_visible(self, frame):
        """模板匹配检测"MP"文字标志是否可见(用户2026-09-07：搜索区X从0到1300、Y只取底部往上60px的横带)。
        可见=True => 在游戏内、底部有血蓝条界面，可以吃药；
        不可见=False => 小退/选角/活动弹窗等无血条界面(或被挡)，跳过吃药。
        只搜底部横带而非全窗口：活动/弹窗会在上半屏误匹配到0.5+，限定底部后异常画面降到0.46。"""
        if self._mp_label_template is None or frame is None:
            return True  # 无模板时不拦截
        th, tw = self._mp_label_template.shape[:2]
        h, w = frame.shape[:2]
        x0, x1 = 0, min(1300, w)
        y0, y1 = max(0, h - 60), h
        roi = frame[y0:y1, x0:x1]
        if roi.shape[0] < th or roi.shape[1] < tw:
            return True
        result = cv2.matchTemplate(roi, self._mp_label_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        visible = max_val >= self.MP_LABEL_THRESH
        if not visible:
            _debug_log("[MP界面] 底部横带匹配度%.3f<%.2f, 判定非游戏画面(小退/弹窗)" % (max_val, self.MP_LABEL_THRESH))
        return visible

    def _check_auto_potion(self):
        """自动吃药检测：HP/MP低于设定百分比时按键，带冷却和随机误差"""
        if self.hwnd is None:
            return
        now = time.time() * 1000
        # 启动后3秒内不检测吃药（避免窗口刚加载截图不准导致误加蓝）
        if not hasattr(self, '_pot_start_time'):
            self._pot_start_time = now
        if now - self._pot_start_time < 3000:
            return
        # 每400ms检测一次，避免太频繁
        if now - self._last_pot_check < 500:
            return
        self._last_pot_check = now

        cfg = self._get_potion_config()

        # 2026-09-07 CPU优化·截图共用：优先复用后台检测线程刚截的全窗口帧(忙时250ms/闲时700ms一帧)，
        # 帧龄>1.5s才自己补截(检测线程异常/未启动时兜底)——省掉每500ms一次的全窗口截图
        _rf = getattr(self, '_raw_frame', None)
        _rft = getattr(self, '_raw_frame_t', 0)
        if _rf is not None and (time.time() - _rft) <= 1.5:
            frame = _rf
        else:
            frame = self._capture_window()
        if frame is None:
            return

        # 自动检测血条（每帧都检测，适应窗口移动）
        hp_bar, mp_bar = self._detect_hp_mp_bars(frame)
        if hp_bar:
            self._hp_bar = hp_bar
        if mp_bar:
            self._mp_bar = mp_bar

        # 检测HP/MP上限（每3秒一次，用于输入校验，不影响吃药逻辑）
        self._detect_hp_mp_max(frame)

        # 判定1·遮挡：游戏窗口不在前台（被其他窗口挡住/最小化）时跳过吃药
        import ctypes
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
        occluded = (fg_hwnd != self.hwnd)
        # 判定2·MP界面存在(用户2026-09-07恢复旧版模板门控)：全窗口匹配"MP"文字标志，
        # 匹配到=真在游戏内、底部有血/蓝条界面；小退/选角/登录/频道界面没有MP标志→即便窗口在前台也不加(治小退画面误加蓝)
        mp_visible = self._is_mp_label_visible(frame)
        in_game = (not occluded) and mp_visible
        hp_thresh = min(int(self._field_values.get("hp_value", "30") or "30"), 100)
        mp_thresh = min(int(self._field_values.get("mp_value", "30") or "30"), 100)

        # 【用户2026-09-09】每种状态只在"刚进入"时上屏一条，持续期间不重复刷，恢复正常时再打一条：
        # _ui_block_state: 0=正常游戏中 1=窗口被遮挡 2=前台但无MP界面(小退/选角)
        _ui_block_state_now = 1 if occluded else (2 if not mp_visible else 0)
        _ui_block_state_prev = getattr(self, '_ui_block_state', 0)
        if _ui_block_state_now != _ui_block_state_prev:
            if _ui_block_state_now == 1:
                self._rlog("血条被遮挡，暂不自动加血加蓝", (200, 100, 0), log='behavior')
                print("[吃药] 窗口非前台，跳过吃药")
            elif _ui_block_state_now == 2:
                self._rlog("未检测到MP界面(小退/选角?)，暂不加血加蓝", (200, 100, 0), log='behavior')
                print("[吃药] 未匹配到MP标志=非游戏画面，跳过吃药")
            elif _ui_block_state_now == 0 and _ui_block_state_prev != 0:
                # 遮挡/无界面解除，回到游戏时提示一次
                self._rlog("回到游戏，恢复自动吃药", (0, 180, 0), log='behavior')
            self._ui_block_state = _ui_block_state_now
        # 无MP界面期间持续清待按计时，防回游戏瞬间误按（与日志边沿无关，每帧清）
        if not occluded and not mp_visible:
            self._hp_pot_wait_until = 0
            self._mp_pot_wait_until = 0
        self._was_blocked = not in_game

        if in_game:
            # HP检测 — 小竖框内没红色=低于阈值=吃红
            hp_blank = self._is_bar_blank_at(frame, self._hp_bar, hp_thresh, "hp")
            _debug_log("HP检测: blank=%s thresh=%d key=%s bar=%s" % (hp_blank, hp_thresh, cfg.get("hp_key"), self._hp_bar))
            if hp_blank and cfg.get("hp_key"):
                if self._hp_pot_wait_until == 0:
                    self._hp_pot_wait_until = now + random.randint(0, 800)
                if now >= self._hp_pot_wait_until and now - self._last_hp_pot > self._hp_pot_delay:
                    self._press_game_key(cfg["hp_key"])
                    self._last_hp_pot = now
                    self._hp_pot_delay = random.randint(500, 1000)
                    self._hp_pot_wait_until = 0
                    self._rlog("加血 %s" % cfg["hp_key"], (0, 0, 200), log='behavior')
                    print("[自动吃药] HP低于%d%%, 按 %s" % (hp_thresh, cfg["hp_key"]))
            else:
                self._hp_pot_wait_until = 0

            # MP检测 — 小竖框内没蓝色=低于阈值=吃蓝
            mp_blank = self._is_bar_blank_at(frame, self._mp_bar, mp_thresh, "mp")
            _debug_log("MP检测: blank=%s thresh=%d key=%s bar=%s" % (mp_blank, mp_thresh, cfg.get("mp_key"), self._mp_bar))
            if mp_blank and cfg.get("mp_key"):
                if self._mp_pot_wait_until == 0:
                    self._mp_pot_wait_until = now + random.randint(0, 800)
                if now >= self._mp_pot_wait_until and now - self._last_mp_pot > self._mp_pot_delay:
                    self._press_game_key(cfg["mp_key"])
                    self._last_mp_pot = now
                    self._mp_pot_delay = random.randint(500, 1000)
                    self._mp_pot_wait_until = 0
                    self._rlog("加蓝 %s" % cfg["mp_key"], (200, 100, 0), log='behavior')
                    print("[自动吃药] MP低于%d%%, 按 %s" % (mp_thresh, cfg["mp_key"]))
            else:
                self._mp_pot_wait_until = 0

            # 吃药诊断日志（每秒一次，无条件输出，便于排查）
            if now - getattr(self, '_last_pot_diag_log', 0) > 1000:
                self._last_pot_diag_log = now
                hp_info = "无条" if not self._hp_bar else "x=%d,w=%d" % (self._hp_bar[0], self._hp_bar[2])
                mp_info = "无条" if not self._mp_bar else "x=%d,w=%d" % (self._mp_bar[0], self._mp_bar[2])
                overlay = "开" if self._monster_overlay_running else "关"
                mp_tpl = "无" if self._mp_label_template is None else "%dx%d" % self._mp_label_template.shape[:2]
                print("[吃药诊断] 蒙板=%s 遮挡=%s MP界面=%s MP模板=%s HP条:%s HP空=%s MP条:%s MP空=%s" % (
                    overlay, occluded, mp_visible, mp_tpl, hp_info, hp_blank, mp_info, mp_blank))

        # 宠物食品 — 按冷却周期自动喂（不受运行状态控制，不受遮挡影响，脚本开了就生效）
        pet_key = cfg.get("pet_key", "")
        pet_cd = cfg.get("pet_cd", 0)
        if pet_key and pet_cd > 0:
            last = self._potion_last.get("pet", 0)
            if now - last > pet_cd:
                self._press_game_key(pet_key)
                self._potion_last["pet"] = now
                self._rlog("宠物食 %s" % pet_key, (0, 200, 0), log='behavior')
                print("[宠物食] %s 释放" % pet_key)

        # 将血条/蓝条检测点传给统一透明蒙板显示
        if self._monster_overlay_running:
            if self._monster_overlay_data is None:
                self._monster_overlay_data = {}
            # 保留已有字段（char_pos/monsters/blink_until）
            if self._hp_bar:
                hx, hy, hw = self._hp_bar
                self._monster_overlay_data['hp_marker'] = (
                    hx + int(hw * hp_thresh / 100.0), hy)
            else:
                self._monster_overlay_data['hp_marker'] = None
            if self._mp_bar:
                mx, my, mw = self._mp_bar
                self._monster_overlay_data['mp_marker'] = (
                    mx + int(mw * mp_thresh / 100.0), my)
            else:
                self._monster_overlay_data['mp_marker'] = None

    def _hold_combat_key(self, vk):
        """持续按住一个键（如果没按住的话）"""
        if vk not in self._combat_held_keys:
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            user32.keybd_event(vk, scan, ext, 0)
            self._combat_held_keys.add(vk)
            self._wd_sync_from_keys('combat')  # 监管线:按方向键即登记移动意图

    def _release_combat_key(self, vk):
        """释放一个持续按住的键"""
        if vk in self._combat_held_keys:
            scan = user32.MapVirtualKeyW(vk, 0)
            ext = 0x0001 if vk in (0x25, 0x26, 0x27, 0x28) else 0
            user32.keybd_event(vk, scan, ext | 0x0002, 0)
            self._combat_held_keys.discard(vk)
            self._wd_sync_from_keys('combat')  # 监管线:松方向键后对账意图(键起意图清)

    def _release_combat_move(self):
        """释放所有持续按住的移动键"""
        for vk in list(self._combat_held_keys):
            self._release_combat_key(vk)
        self._combat_move_dir = None

    def _release_move_conflicts(self):
        """垂直动作(上/下梯、下跳、原地直跳抓梯)前统一清干扰键：攻击键 + 左右水平键(战斗/巡路两套全松)。
        用户2026-09-09：攻击或左右键没松干净会和↑/↓冲突,表现为上梯上一半停、差一点到顶停、下跳被打断。只松水平/攻击,不碰垂直键。"""
        try:
            self._release_attack_key()
        except Exception as e:
            _debug_log("[清键] 松攻击异常:%s" % e)
        try:
            self._release_combat_move()  # 战斗套左右
        except Exception as e:
            _debug_log("[清键] 松战斗移动异常:%s" % e)
        for _vk in (VK_LEFT, VK_RIGHT):  # 巡路套左右
            try:
                self._key_up(_vk)
            except Exception:
                pass

    def _is_lock_frozen(self):
        """锁怪冻结硬信号(用户2026-09-09定稿)：以"我们自己的抓梯/垂直动作阶段"为唯一判据,不靠画面Y/X(镜头会滚、对齐会抖)。
        ·to_ladder平地走向梯子、还没跳=不冻,身边有更该打的怪允许换(换了重新选梯)；
        ·一旦跳起来进入抓梯流程(post_jump)、或已在climbing爬梯/jump_down下跳/teleport瞬移=锁死,
         一直到到顶/到底_reset_lock_after_arrival才解冻重识别。信号只有冻/不冻两种,明确稳定。"""
        cs = getattr(self, '_climb_state', 'none')
        if cs in ('climbing', 'jump_down', 'jump_up', 'teleport'):
            return True
        if cs == 'to_ladder' and getattr(self, '_ladder_jump_phase', None) == 'post_jump':
            return True
        return False

    def _set_combat_move(self, direction):
        """设置持续移动方向，direction='left'/'right'/None。流畅切换不卡顿。"""
        if direction == self._combat_move_dir:
            # 方向没变也要校验物理键真的按住：前台漂移/异常keyup可能让"名义按住"失效(表现=只跳不走/原地蹦)，缺了立刻补按
            if direction == "left" and VK_LEFT in self._combat_held_keys:
                return
            if direction == "right" and VK_RIGHT in self._combat_held_keys:
                return
            if direction is None:
                return
            # 落到下方重新发一次 keydown
        # 先松开所有方向键
        self._release_combat_key(VK_LEFT)
        self._release_combat_key(VK_RIGHT)
        # 按新方向
        if direction == "left":
            self._hold_combat_key(VK_LEFT)
        elif direction == "right":
            self._hold_combat_key(VK_RIGHT)
        self._combat_move_dir = direction
        # 【面向】人物朝哪个方向移动，实际朝向就是哪个方向(停步后仍保持)。同步 _combat_facing + _combat_last_face_dir，
        # 避免打怪前转身判定用错朝向导致反向打/多余转身(用户2026-09-05：朝怪走完别再多余转一次)。1=右 -1=左
        if direction == "right":
            self._combat_facing = 1
            self._combat_last_face_dir = 1
        elif direction == "left":
            self._combat_facing = -1
            self._combat_last_face_dir = -1

    # ==================== 移动监管线 watchdog（用户2026-09-09 三线模型；v1观察版：只监测打日志，不挂起、不发键）====================
    def _wd_register_intent(self, axis, direction, src=''):
        """主线【底层按键处】登记移动意图，监管线程据此判停滞。axis='x'/'y'；direction=±1（小地图：右+、上-、下+）。
        双轴dict：_mv_intent['x'/'y']各一份，水平垂直互不覆盖。X同方向续按不重置（确认动了才滑基准）；
        Y首次/换向才锁段首、续按不覆盖——镜头随人物上下滚动时中间帧光点相对Y会假不动/回弹，只比段首段尾两端点、段内不管。"""
        if axis not in ('x', 'y') or not direction:
            return
        now = time.time() * 1000
        mmp = getattr(self, '_player_map_pos', None)
        bx = mmp[0] if mmp else None
        by = mmp[1] if mmp else None
        with self._wd_lock:
            it = self._mv_intent.get(axis)
            if it and it.get('dir') == direction:
                if src:
                    it['src'] = src
                return
            self._mv_intent[axis] = {'dir': direction, 'src': src, 'start_t': now,
                                     'base_x': bx, 'base_y': by,
                                     'seg_t': now, 'seg_x': bx, 'seg_y': by,
                                     'seg_n': 0, 'seg_hits': 0, 'reported': False}

    def _wd_clear_intent(self, axis=None):
        """松方向键/到达/换目标时清移动意图；axis=None清全部。"""
        with self._wd_lock:
            if axis is None:
                self._mv_intent.clear()
            else:
                self._mv_intent.pop(axis, None)

    def _wd_sync_from_keys(self, src=''):
        """每次方向键按下/松开后，按两套键(战斗_combat_held_keys/巡路_random_move_keys)的实际按住状态对账X/Y意图：
        键在意图在、键起意图清，不漏登记也不残留（监管键账册在主线侧的维护；监管线程只读不写键）。"""
        left = VK_LEFT in self._combat_held_keys or VK_LEFT in self._random_move_keys
        right = VK_RIGHT in self._combat_held_keys or VK_RIGHT in self._random_move_keys
        up = VK_UP in self._combat_held_keys or VK_UP in self._random_move_keys
        down = VK_DOWN in self._combat_held_keys or VK_DOWN in self._random_move_keys
        if right:
            self._wd_register_intent('x', 1, src)
        elif left:
            self._wd_register_intent('x', -1, src)
        else:
            self._wd_clear_intent('x')
        if down:
            self._wd_register_intent('y', 1, src)
        elif up:
            self._wd_register_intent('y', -1, src)
        else:
            self._wd_clear_intent('y')

    def _wd_set_owner(self, owner):
        """动作权交接登记（v1只记录+日志；v2用于仲裁：任一时刻只允许一个执行线持有动作权）。"""
        with self._wd_lock:
            old = self._motion_owner
            if old == owner:
                return
            self._motion_owner = owner
        _debug_log("[监管线] 动作权交接: %s → %s" % (old, owner))

    def _wd_log(self, key, msg, color=(0, 0, 255)):
        """监管日志：行为日志栏显示+写debug，同类按WD_LOG_DEDUP_MS去重防刷屏；异常默认红字。"""
        now = time.time() * 1000
        if now - self._wd_log_last.get(key, 0) < WD_LOG_DEDUP_MS:
            return
        self._wd_log_last[key] = now
        try:
            self._rlog(msg, color=color, log='behavior')
        except Exception:
            pass
        _debug_log("[监管线] " + msg)

    def _wd_bg_motion_count(self, frame):
        """上/右两块纯背景帧差，返回几块在动(0~2)。跳后1秒静默期调用方不调用本方法→基准帧停在跳前地面,
        落地后第一帧正好与跳前地面对比(用户:只比跳前和落地后,不在空中取图)。小块absdiff,CPU开销极小。"""
        if frame is None:
            return 0
        fh, fw = frame.shape[:2]
        cnt = 0
        for i, reg in enumerate(WD_BG_REGIONS):
            x1 = max(0, min(reg["x"], fw - 1))
            y1 = max(0, min(reg["y"], fh - 1))
            x2 = min(fw, x1 + reg["w"])
            y2 = min(fh, y1 + reg["h"])
            _P = 3  # 内缩3px排除边缘框线
            roi = frame[y1 + _P:y2 - _P, x1 + _P:x2 - _P]
            if roi.size == 0 or i >= len(self._wd_bg_last):
                continue
            prev = self._wd_bg_last[i]
            self._wd_bg_last[i] = roi.copy()
            if prev is not None and prev.shape == roi.shape and float(cv2.absdiff(roi, prev).mean()) > BG_DIFF_THRESHOLD:
                cnt += 1
        return cnt

    def _wd_audit_keys(self):
        """仲裁巡检(v1只记录)：①战斗/巡路两套方向键左右同时按住=抢键互抵；②无移动意图却有方向键按住=漏登记/按键残留。"""
        cl = VK_LEFT in self._combat_held_keys
        cr = VK_RIGHT in self._combat_held_keys
        rl = VK_LEFT in self._random_move_keys
        rr = VK_RIGHT in self._random_move_keys
        left_held, right_held = cl or rl, cr or rr
        if left_held and right_held:
            self._wd_log('wd_key_fight',
                         "抢键告警:左右方向同时按住(战斗L%s/R%s 巡路L%s/R%s)[观察]" % (cl, cr, rl, rr))
        updown = (VK_UP in self._combat_held_keys or VK_DOWN in self._combat_held_keys
                  or VK_UP in self._random_move_keys or VK_DOWN in self._random_move_keys)
        with self._wd_lock:
            has_intent = bool(self._mv_intent)
        if (left_held or right_held or updown) and not has_intent:
            self._wd_log('wd_key_orphan',
                         "按键残留:无移动意图却按住方向键(战斗%s 巡路%s)[观察]" % (
                             sorted(self._combat_held_keys), sorted(self._random_move_keys)))

    def _wd_check_once(self):
        """监管一轮(简单稳定版,v1只打日志)：仲裁巡检 + X/Y双轴判停滞。
        动没动=【上右两块纯背景同时变化(镜头滚)】或【小地图光点朝意图方向位移】；方向只由光点给。
        起跳后WD_JUMP_GATE_MS内冻结背景对比(空中镜头抖),也不累计、段窗口顺延,落地后与跳前地面帧接着比。"""
        now = time.time() * 1000
        if now - getattr(self, '_wd_audit_t', 0) >= WD_IDLE_AUDIT_MS:
            self._wd_audit_t = now
            self._wd_audit_keys()
        with self._wd_lock:
            intents = {a: dict(v) for a, v in self._mv_intent.items()}
        if not intents:
            return  # 无移动意图不做背景帧差(省CPU)
        mmp = getattr(self, '_player_map_pos', None)
        in_gate = now < self._wd_jump_gate_until
        # 跳后静默窗内不截背景(基准帧停在跳前地面);否则算上/右两块几块在动
        bg_count = 0 if in_gate else self._wd_bg_motion_count(getattr(self, '_raw_frame', None))
        for axis, it in intents.items():
            self._wd_check_axis(axis, it, mmp, bg_count, in_gate, now)

    def _wd_check_axis(self, axis, it, mmp, bg_count, in_gate, now):
        """单轴：段内累计"真实运动"次数,段末(X=1s/Y=1.5s)看是否≥WD_SEG_MIN_HITS;不足=停滞报警(去重)。"""
        win = WD_X_CHECK_MS if axis == 'x' else WD_Y_SEG_MS
        with self._wd_lock:
            cur = self._mv_intent.get(axis)
            if cur is None:
                return
            if in_gate:
                cur['seg_t'] = now  # 跳后1秒不计入判定段,窗口顺延(空中不比)
                return
            cur['seg_n'] = cur.get('seg_n', 0) + 1
            bg_moving = bg_count >= WD_BG_MOTION_MIN  # 上右两块同时变=镜头在滚=人在移动
            dot_moving = False
            base = cur['seg_x'] if axis == 'x' else cur['seg_y']
            if mmp is not None and base is not None:
                dd = (mmp[0] - base) if axis == 'x' else (mmp[1] - base)
                dot_moving = dd >= WD_MIN_MAP_D if cur['dir'] > 0 else dd <= -WD_MIN_MAP_D
            if bg_moving or dot_moving:
                cur['seg_hits'] = cur.get('seg_hits', 0) + 1
            if now - cur['seg_t'] < win:
                return
            n, hits = cur.get('seg_n', 0), cur.get('seg_hits', 0)
            moving = hits >= WD_SEG_MIN_HITS
            dseg = None
            if mmp is not None and base is not None:
                dseg = (mmp[0] - base) if axis == 'x' else (mmp[1] - base)
            nx = mmp[0] if mmp else cur.get('seg_x')
            ny = mmp[1] if mmp else cur.get('seg_y')
            if axis == 'x':
                dn = '右' if cur['dir'] > 0 else '左'
            else:
                dn = '下' if cur['dir'] > 0 else '上'
            if moving:
                cur.update(seg_t=now, seg_n=0, seg_hits=0, reported=False, seg_x=nx, seg_y=ny)
            else:
                if not cur.get('reported'):
                    self._wd_log(
                        'wd_%s_stall' % axis,
                        "%s停滞:朝%s%.0fms 背景同动%d块/光点段差%s,采样%d真实运动%d次<%d,疑似没动[观察]" % (
                            'X' if axis == 'x' else 'Y', dn, win, bg_count,
                            ('%.1f' % dseg) if dseg is not None else 'NA', n, hits, WD_SEG_MIN_HITS))
                cur.update(seg_t=now, seg_n=0, seg_hits=0, reported=True, seg_x=nx, seg_y=ny)

    def _move_watchdog_loop(self):
        """监管线独立线程：只在自动运行时每WD_POLL_MS巡检一次，全程try自保护，绝不发键、绝不崩主线。"""
        while self._wd_running:
            try:
                if getattr(self, '_random_running', False):
                    self._wd_check_once()
            except Exception as e:
                try:
                    _debug_log("[监管线] 循环异常: %s" % e)
                except Exception:
                    pass
            time.sleep(WD_POLL_MS / 1000.0)

    def _start_move_watchdog(self):
        if self._wd_thread and self._wd_thread.is_alive():
            return
        self._wd_running = True
        self._wd_thread = threading.Thread(target=self._move_watchdog_loop, daemon=True)
        self._wd_thread.start()
        _debug_log("[监管线] 移动监管线程已启动(v1观察版:只监测打日志)")

    def _stop_move_watchdog(self):
        self._wd_running = False
        if self._wd_thread and self._wd_thread.is_alive():
            self._wd_thread.join(timeout=1.0)
        self._wd_thread = None
        with self._wd_lock:
            self._mv_intent.clear()

    def _check_move_blocked(self, now, px, move_dir, jump_key):
        """位移检测(用户2026-09-07定稿)：下令左/右移动后，每 MOVE_STALL_CHECK_MS(1秒) 用【小地图光点X】判定是否真在动
        (不看屏幕角色特征点——边缘会丢、会冻结,光点更准)。光点没朝该方向走≥MOVE_MIN_MAP_DX=卡住
        (撞平台边/台阶上不去/方向键名义按住实际失效)，自动"重按一次方向键+跳一下"解卡；确实在走就刷新基准。
        正上方(move_dir=None)不检测；光点暂时丢失(None)不判卡、只刷新基准等下一窗口。返回True=本次判定卡住。"""
        if move_dir not in ("left", "right"):
            self._move_mon = None
            return False
        _mmp = getattr(self, '_player_map_pos', None)
        mon = self._move_mon
        if not mon or mon.get("dir") != move_dir:
            self._move_mon = {"dir": move_dir, "dot0": (_mmp[0] if _mmp else None), "t0": now, "stalls": 0}
            return False
        if now - mon["t0"] < MOVE_STALL_CHECK_MS:
            return False
        # 光点缺失：无法判定，刷新基准不冤枉(等下一窗口)
        if _mmp is None or mon.get("dot0") is None:
            mon["dot0"] = _mmp[0] if _mmp else None
            mon["t0"] = now
            return False
        _ddx = _mmp[0] - mon["dot0"]    # 光点X增量(小地图单位,右正左负)
        moved = (_ddx >= MOVE_MIN_MAP_DX) if move_dir == "right" else (_ddx <= -MOVE_MIN_MAP_DX)
        if moved:
            mon["dot0"] = _mmp[0]       # 确实在走：刷新基准，重新计时
            mon["t0"] = now
            mon["stalls"] = 0
            return False
        # 卡住(用户2026-09-09改独占)：不在主线打怪/巡路里就地按跳(会和主线抢键),只登记"卡住解卡"请求,
        # 本帧返回True让调用点停手,下一帧起由主循环 _unblock_tick 独占执行(先关主线→向前+跳试X→脱困/连试上限放弃→再开主线)
        self._start_unblock(move_dir, jump_key, _mmp[0], now)
        mon["t0"] = now
        mon["dot0"] = _mmp[0]
        _debug_log("[位移检测] 朝%s移动%dms 光点X仅变化%.1f(<%d)=卡住，转入独占解卡(主线暂停)" % (
            move_dir, MOVE_STALL_CHECK_MS, _ddx, MOVE_MIN_MAP_DX))
        return True

    def _start_unblock(self, move_dir, jump_key, dot_x, now):
        """进入卡住解卡独占态(只进一次)：记录方向/跳键/基准光点X，松开主线移动与攻击，等待_unblock_tick接管。"""
        if self._unblock_state is not None:
            return
        self._unblock_state = {'dir': move_dir, 'jump': jump_key, 'tries': 0,
                               'dot0': dot_x, 'act_t': now, 'phase': 'jump'}
        self._release_combat_move()
        self._release_attack_key()
        _debug_log("[卡住解卡] 启动：朝%s卡住，暂停主线，开始向前+跳试探" % move_dir)

    def _cancel_unblock(self):
        """结束卡住解卡：松开解卡按住的方向键、清状态，交还主线。"""
        st = self._unblock_state
        if st:
            _vk = VK_RIGHT if st['dir'] == 'right' else VK_LEFT
            self._release_combat_key(_vk)
        self._unblock_state = None

    def _unblock_tick(self):
        """卡住解卡·独占辅助线(用户2026-09-09)。返回True=解卡中(主循环暂停主线),False=无解卡/已结束(主线运行)。
        每一试：按住卡住方向+跳一下→等500ms看小地图光点X是否朝该方向恢复移动：
        恢复=脱困,松键恢复主线；连试UNBLOCK_MAX_TRIES次仍不动=地形真过不去,放弃当前锁定目标回主线重锁。"""
        st = self._unblock_state
        if st is None:
            return False
        if not getattr(self, '_running', False):
            self._cancel_unblock()
            return False
        now = time.time() * 1000
        mmp = getattr(self, '_player_map_pos', None)
        vk = VK_RIGHT if st['dir'] == 'right' else VK_LEFT
        if st['phase'] == 'jump':
            # 先松再按强制重发方向keydown(绕过"方向没变不重发"缓存)，再跳一下尝试上台阶/脱离卡点
            self._release_combat_key(vk)
            self._hold_combat_key(vk)
            if st['jump'] and now - self._combat_last_jump > 250:
                self._press_game_key(st['jump'], duration=70)
                self._combat_last_jump = now
            st['dot0'] = mmp[0] if mmp else st['dot0']
            st['act_t'] = now
            st['phase'] = 'wait'
            st['tries'] += 1
            _debug_log("[卡住解卡] 第%d/%d次 向前(%s)+跳，观察光点X" % (st['tries'], UNBLOCK_MAX_TRIES, st['dir']))
            return True
        # wait阶段：保持方向按住，满500ms判定这一试有没有脱困
        if vk not in self._random_move_keys:
            self._hold_combat_key(vk)
        if now - st['act_t'] < 500:
            return True
        if mmp is not None:
            _ddx = mmp[0] - st['dot0']
            _moved = (_ddx >= MOVE_MIN_MAP_DX) if st['dir'] == 'right' else (_ddx <= -MOVE_MIN_MAP_DX)
            if _moved:
                _debug_log("[卡住解卡] 光点X恢复移动(%.1f)=脱困，恢复主线" % _ddx)
                self._cancel_unblock()
                return False
        # 这一试没动
        if st['tries'] >= UNBLOCK_MAX_TRIES:
            _lk = getattr(self, '_combat_locked_target', None)
            _debug_log("[卡住解卡] 连试%d次仍不动=地形过不去，放弃当前目标%s回主线重锁" % (
                st['tries'], ("(%d,%d)" % _lk) if _lk else ""))
            self._cancel_unblock()
            if _lk:
                self._abort_unreachable_target(_lk[0], _lk[1], now, why='卡住解卡连试不动')
            return False
        st['phase'] = 'jump'   # 进入下一试
        return True

    def _abort_unreachable_target(self, cx, cy, now, why=""):
        """防卡死(用户2026-09-07)：连续想走却走不动/靠近300跑跳仍上不去=当前锁定怪打不到/地形过不去，放弃它并强制下帧改锁最近的怪。
        - 该位置加入空怪去重列表(3秒内不再重锁同一只,避免drop又立刻选回原地死循环)；
        - 同时短时压制"这一侧"(用户2026-09-07：右边过不去就放弃右边整侧、直接锁左边的怪),由_filter_dropped_phantoms剔除；
        - 清锁定/移动/高坡相位，松开方向键，下帧 combat_step 从另一侧剩余怪里重选X最近且Y达标者。"""
        self._combat_dropped_phantoms.append((cx, cy, now))
        _pp = getattr(self, '_player_screen_pos', None)
        if _pp is not None:
            _side = 'right' if cx >= _pp[0] else 'left'
            self._combat_suppress_side = (_side, now + 3000)  # 3秒内不锁该侧怪(到点_filter自动失效)
            _debug_log("[防卡死] 压制%s侧3秒(地形过不去)" % _side)
        self._combat_locked_target = None
        self._combat_target_alive = False
        self._combat_target_attacked = False
        self._combat_first_strike_time = 0
        self._move_mon = None
        self._slope_next_jump = 0
        self._slope_jump_t = 0
        self._slope_jump_hit = False
        self._slope_hit_window = False
        self._slope_high_mode = False
        self._release_combat_move()
        self._release_attack_key()
        _debug_log("[防卡死] 连续移动受阻(%s)，判定目标(%d,%d)打不到→放弃，下帧改锁另一侧最近怪" % (why or "卡住", cx, cy))

    def _edge_recovery_tick(self, now):
        """贴地图边缘丢特征自救(用户2026-09-07)。
        - 特征正常：结束自救、松键；
        - 在【中间】丢失：原地等全图重扫，不动作(匹配线程每帧全图搜,搜到即更新新基点)；
        - 在【最左/最右边】丢失(人物贴边被画面裁掉)：主动朝画面中间走一段随机300~500屏幕px,
          用小地图光点量位移(X倍率把屏幕px换成光点单位)来判断走完没,走完/2.5s超时就停、转原地等重扫。
        返回True=正在边缘自救(调用方应暂停巡路/战斗移动,避免按键打架)。"""
        # 非挂机运行(编辑/特征录制界面)不做任何移动自救，避免误发键
        if not getattr(self, '_running', False):
            if self._edge_recover is not None:
                self._edge_recover = None
            return False
        # 特征正常：结束自救
        if getattr(self, '_char_match_ok', True):
            if self._edge_recover is not None:
                self._release_combat_move()
                _debug_log("[边缘自救] 特征重新定位成功，结束自救回正常")
                self._edge_recover = None
            return False
        edge = getattr(self, '_char_lost_edge', None)
        # 中间丢失：原地等全图重扫，不动作
        if edge is None:
            if self._edge_recover is not None:
                self._release_combat_move()
                self._edge_recover = None
            return False
        rec = self._edge_recover
        _mmp = getattr(self, '_player_map_pos', None)
        if rec is None or rec.get('dir_side') != edge:
            # 启动自救：随机300~500屏幕px，X倍率换算成光点位移作为停止目标
            _dist_px = random.randint(300, 500)
            _sx, _ = self._effective_scale()
            _goal = _dist_px * _sx if (_sx and _sx > 0) else _dist_px * 0.1
            self._edge_recover = {'dir_side': edge,
                                  'dir': 'right' if edge == 'left' else 'left',
                                  'dot0': (_mmp[0] if _mmp else None),
                                  'goal_map': _goal, 'dist_px': _dist_px, 'until': now + 2500}
            self._release_combat_move()
            rec = self._edge_recover
            _debug_log("[边缘自救] %s边丢特征，向中间走%dpx(光点目标%.1f)以重新进入识别区" % (
                "左" if edge == 'left' else "右", _dist_px, _goal))
        # 终止：超时 / 光点朝中间走完目标位移
        _done = now >= rec['until']
        if _mmp is not None and rec.get('dot0') is not None:
            _moved = (_mmp[0] - rec['dot0']) if rec['dir'] == 'right' else (rec['dot0'] - _mmp[0])
            if _moved >= rec['goal_map']:
                _done = True
        if _done:
            self._release_combat_move()
            _debug_log("[边缘自救] 回中到位/超时，停步转原地等待全图重扫")
            self._edge_recover = None
            return False
        self._set_combat_move(rec['dir'])
        return True

    def _single_home_platform(self):
        """掉台归位只在【只勾选一个平台=单台锁定】时启用，返回该home平台对象；
        未勾选(全图)/勾选多个/找不到对应台 → 返回None(不判掉台,多台正常跨层不被归位打断)。编号口径=pf['id']+1。"""
        if not self.platforms or len(self._selected_platforms) != 1:
            return None
        num = self._selected_platforms[0]
        for pf in self.platforms:
            if pf.get('id', 0) + 1 == num:
                return pf
        return None

    def _fall_return_tick(self):
        """掉台归位·独占辅助线(用户2026-09-09)。单台锁定时持续监测光点是否还在该台折线上:
        - 光点在home台=正常(或已归位)：结束归位、返回False把控制权交还主线;
        - 光点连续FALL_OFF_DEBOUNCE_MS离开home台、且不是主线主动跨层/攀爬=掉下去:启动归位,
          归位期间复用主线同一套 _move_to(自动找梯/跳/瞬移)回home台最近点,主线(_random_step/_combat_tick)由主循环暂停;
        - 光点重新回到home台折线(FALL_ON_TOL内)=归位完成,松键复位、恢复主线。
        返回True=正在归位(主循环应暂停主线),False=正常/已归位(主线运行)。"""
        if not getattr(self, '_running', False):
            if self._fall_returning:
                self._fall_returning = False
                self._fall_off_since = 0
            return False
        home_pf = self._single_home_platform()
        # 非单台锁定(多台/全图/取消勾选)：不做掉台归位；若之前在归位则收尾退出
        if home_pf is None:
            if self._fall_returning:
                self._release_all_keys()
                self._reset_climb()
                self._fall_returning = False
                self._fall_off_since = 0
                self._fall_home_pf_id = None
                self._fall_home_target = None
            return False
        home_id = home_pf.get('id', 0)
        pts = self._platform_points(home_pf)
        if not pts:
            return self._fall_returning
        now_ms = time.time() * 1000
        mmp = getattr(self, '_player_map_pos', None)
        # 仅当【主线主动跨层】(_combat_transit=True)才视为正常离开、不判掉台。注意不能用_climb_state判断:
        # 归位自身复用_move_to回台时也会让_climb_state变成攀爬态,但那时_combat_transit=False,必须继续归位、不能被误停
        if getattr(self, '_combat_transit', False):
            self._fall_off_since = 0
            return False
        if mmp is None:
            # 光点暂时丢失：不冤枉，维持当前状态(归位中继续,正常则等待)
            return self._fall_returning
        _d = self._point_to_polyline_dist(mmp[0], mmp[1], pts)
        on_home = _d <= FALL_ON_TOL
        if on_home:
            self._fall_off_since = 0
            if self._fall_returning:
                # 光点重新回到home台=归位完成
                self._release_all_keys()
                self._reset_climb()
                self._fall_returning = False
                self._fall_home_pf_id = None
                self._fall_home_target = None
                _debug_log("[掉台归位] 光点重新回到%d号台，归位完成→恢复主线" % (home_id + 1))
            return False
        # 光点不在home台：防抖计时(正常跳跃会在防抖窗内回到线上,不触发)
        if self._fall_off_since == 0:
            self._fall_off_since = now_ms
            return self._fall_returning
        if not self._fall_returning and now_ms - self._fall_off_since < FALL_OFF_DEBOUNCE_MS:
            return False
        # 持续离开=确认掉台：启动归位(只启动一次)
        if not self._fall_returning:
            self._fall_returning = True
            self._fall_home_pf_id = home_id
            _best = min(pts, key=lambda q: abs(q[0] - mmp[0]) + abs(q[1] - mmp[1]))
            self._fall_home_target = (float(_best[0]), float(_best[1]))
            self._release_combat_move()
            self._release_all_keys()
            _debug_log("[掉台归位] 光点连续%dms离开%d号台(距折线%.0f)=掉台，暂停主线开始回位" % (
                FALL_OFF_DEBOUNCE_MS, home_id + 1, _d))
        # 归位中：复用主线移动/爬梯状态机朝home台最近点走(自动找梯/跳/瞬移)；是否完成以"光点回台"为准
        _t = self._fall_home_target
        if _t:
            self._move_to(mmp, _t[0], _t[1])
        return True

    def _get_current_platform(self):
        """根据小地图玩家坐标判断当前在哪个平台上（点到折线最近距离≤10）。"""
        if not self._player_map_pos or not self.platforms:
            return None
        px, py = self._player_map_pos
        best = None
        best_dist = 999
        for pf in self.platforms:
            pts = self._platform_points(pf)
            d = self._point_to_polyline_dist(px, py, pts)
            if d < best_dist:
                best_dist = d
                best = pf
        if best and best_dist <= 10:
            return best
        return None

    def _filter_monsters_on_platform(self, monsters, player_screen_pos):
        """过滤出和玩家同一平台的怪（怪用脚Y，人用手Y，同平台差约30-50px）"""
        if not player_screen_pos or not monsters:
            return monsters
        _, py = player_screen_pos
        same_platform = []
        for m in monsters:
            x1, y1, x2, y2, score = m
            if abs(y2 - py) <= 50:  # 怪脚 vs 人手
                same_platform.append(m)
        return same_platform

    def _is_monster_on_platform(self, monster_cx, monster_cy):
        """判断怪是否在玩家当前平台上——Y差在上方/下方容差内算同平台（上下独立设置）。"""
        if self._player_screen_pos:
            _pay = self._player_screen_pos[1]
            _dy = monster_cy - _pay  # 负=怪在上方，正=怪在下方
            if _dy < 0:
                return abs(_dy) <= getattr(self, '_far_range_y_up', FAR_RANGE_Y_UP_DEFAULT)
            else:
                return _dy <= getattr(self, '_far_range_y_down', FAR_RANGE_Y_DOWN_DEFAULT)
        # 无人位置：按绿线归属兜底
        monster_pf = self._get_monster_platform(monster_cx, monster_cy)
        player_pf = self._get_current_platform()
        if monster_pf and player_pf:
            return monster_pf.get('id') == player_pf.get('id')
        return False

    def _reset_lock_after_arrival(self):
        """到新平台(梯子到顶/走台子到点)后强制重新识别+重新锁定(用户2026-09-09)：
        翻层后镜头变了,跨层前在旧屏幕坐标上的锁定若不清,会错配/沿旧坐标把人往回带(表现=到顶不锁本层怪、反而跑下去)。
        这里清掉旧锁定及其出手/存活状态,并把YOLO/特征/血条节流清零,让下一检测周期立刻全图重扫,
        combat_logic按当前画面Y近优先重新锁定——锁到上层或下层都正常打,关键是不粘旧目标、不在梯顶空转死循环。"""
        self._combat_locked_target = None
        self._combat_last_target_pos = None
        self._combat_target_alive = False
        self._combat_target_attacked = False
        self._combat_first_strike_time = 0
        self._combat_had_target = False
        # 【用户2026-09-09·关键】检测是在梯子上做的,到顶时缓存没更新:必须把"梯子/旧平台那一帧"的旧检测结果一并清空,
        # 否则新全图重扫(下面节流置0)出结果前的空窗期,combat仍拿旧怪表(旧怪在下方)选成cross→人刚上去又被拉下来。
        # 清空后到新检测填回前怪表为空→combat判idle站定等待,绝不沿旧坐标往下跨层。
        self._monsters = []
        self._monster_hp_bars = []
        self._monster_feature_matches = []
        # 到顶重识别保护期(0.5s)双保险：防检测线程用手里旧帧在清空瞬间又回填、再把下方旧怪锁成cross
        self._arrival_relock_until = time.time() * 1000 + 500
        # 强制下一检测周期立刻全图YOLO+怪物特征+血条(不等YOLO 2Hz/特征0.33s/血条节流)，新层怪表最快刷新
        self._yolo_last_t = 0.0
        self._feat_last_t = 0.0
        self._bars_last_t = 0.0
        _debug_log("[跨层] 到达新平台：清旧锁定+强制全图重扫，按当前画面重新识别锁定")
        self._rlog("到达新平台:清旧锁定+全图立刻重扫,重新识别锁怪", log='behavior')

    def _start_ladder_backoff(self, now_ms):
        """原地直跳连续2次抓不住梯子后启动退开(用户2026-09-09)：朝当前平台更宽的一侧(取不到随机)
        退开120~150屏幕px，期间回主线；本层有怪先打、无怪(cross)才继续横走，走够/超时由_ladder_backoff_step结束。"""
        _dir = random.choice(['left', 'right'])
        try:
            if self._player_map_pos:
                _cpf = self._get_current_platform()
                if _cpf:
                    _mmx, _ = self._player_map_pos
                    _xmin, _xmax = self._platform_x_range(_cpf)
                    # 朝剩余更宽的一侧退(离平台边缘更远、更不容易走掉下去)
                    _dir = 'left' if (_mmx - _xmin) > (_xmax - _mmx) else 'right'
        except Exception as _e:
            _debug_log("[爬梯] 退开方向计算异常用随机: %s" % _e)
        _ssx = self._player_screen_pos[0] if self._player_screen_pos else 0
        _smx = self._player_map_pos[0] if self._player_map_pos else 0
        self._ladder_backoff = {
            'dir': _dir,
            'start_sx': _ssx,        # 退开起始屏幕X(到位主判据)
            'start_mx': _smx,        # 起始小地图X(留底)
            'target': random.randint(LADDER_BACKOFF_MIN, LADDER_BACKOFF_MAX),
            'start_t': now_ms,
        }
        self._rlog("原地直跳连续2次没抓住,朝%s退开%dpx回主线打怪,打完再自动上梯" % (_dir, self._ladder_backoff['target']),
                   LOG_WARN, log='behavior')

    def _ladder_backoff_step(self, now_ms):
        """退开执行(只在主线cross分支调用=本层无怪想跨层时；本层有怪走cast/pursue打怪优先、不会进这)。
        返回True=仍在退开(已按住方向,调用方return别选梯)；False=退开完成/无退开(恢复正常选梯)。"""
        _b = self._ladder_backoff
        if _b is None:
            return False
        _done = False
        # 主判据：屏幕X离开起始点≥目标(120~150px)即退够
        if self._player_screen_pos and abs(self._player_screen_pos[0] - _b['start_sx']) >= _b['target']:
            _done = True
        # 兜底：屏幕定位异常/被地形挡住横走超时，强制结束交回主线(真卡住另有卡住解卡辅助线处理)
        if now_ms - _b.get('start_t', now_ms) >= LADDER_BACKOFF_TIMEOUT_MS:
            _done = True
        if _done:
            self._release_combat_move()
            self._ladder_backoff = None
            _debug_log("[爬梯] 直跳失败退开完成，恢复正常选梯/打怪")
            self._rlog("退开到位,恢复正常选梯/打怪", log='behavior')
            return False
        self._set_combat_move(_b['dir'])
        return True

    def _delete_ladder_at(self, mx, my):
        """梯删除(用户2026-09-09)：按小地图原始分辨率坐标(mx,my)点选梯子，
        命中=|X差|≤LADDER_DEL_X_TOL 且 my落在线段[y_top,y_bottom]内(上下容差LADDER_DEL_Y_TOL)，
        多条命中取X最近者删除。只改内存self.ladders，点保存后才落盘(同_pop_ladder)。"""
        if not self.ladders:
            print("[梯删除] 当前没有梯子")
            return
        _hit_i, _hit_d = -1, 1e9
        for _i, _ld in enumerate(self.ladders):
            if (abs(mx - _ld["x"]) <= LADDER_DEL_X_TOL
                    and (_ld["y_top"] - LADDER_DEL_Y_TOL) <= my <= (_ld["y_bottom"] + LADDER_DEL_Y_TOL)):
                _d = abs(mx - _ld["x"])
                if _d < _hit_d:
                    _hit_d, _hit_i = _d, _i
        if _hit_i < 0:
            print("[梯删除] 没点中梯子(点%d,%d)" % (mx, my))
            return
        _rm = self.ladders.pop(_hit_i)
        print("[梯删除] 已删梯子 x=%.0f 顶=%.0f 底=%.0f，剩余%d条(未保存,点保存后落盘)" % (
            _rm.get("x", 0), _rm.get("y_top", 0), _rm.get("y_bottom", 0), len(self.ladders)))

    def _decide_climb_fail_action(self):
        """【用户2026-09-08定稿】爬梯失败后丢弃跨层目标（想不丢都不行）：重置跨层状态回正常找怪，
        重新锁定怪——锁定规则先锁下面Y相近的同层怪，清完下面的怪再重新锁上层怪上去。
        （_reset_climb已在调用前把爬梯状态机清零；本函数丢弃跨层目标+松键+300~500ms冷却避免原地连跳）"""
        self._combat_transit = False
        self._transit_target = None
        self._climb_fail_decided = None
        self._transit_farm_until = 0
        self._release_all_keys()
        _debug_log("[跨层] 爬梯失败，丢弃目标回正常找怪（先锁下面Y相近的，清完再重新上）")

    def _find_platform_intersection(self, pf_a, pf_b):
        """找两条绿线平台的交叉点（用户用法A：底线+上坡线画成两条、交叉=分叉口）
        小地图距离≤5px即视为交叠（哪怕只有一个点重合）；返回(x, y)或None"""
        pa = self._platform_points(pf_a)
        pb = self._platform_points(pf_b)
        best = None
        best_d = 5.0
        for (ax, ay) in pa:
            for (bx, by) in pb:
                d = abs(float(ax) - float(bx)) + abs(float(ay) - float(by))
                if d < best_d:
                    best_d = d
                    best = ((float(ax) + float(bx)) / 2.0, (float(ay) + float(by)) / 2.0)
        return best

    def _idle_wander_step(self, now):
        """无怪时的拟人小动作：平台范围内随机左右走一走找怪（不能呆站发呆）
        走1~2秒 → 停0.3~0.6秒 → 随机换方向；平台边界内自动折返"""
        if getattr(self, '_idle_wander_pause_until', 0) and now < self._idle_wander_pause_until:
            self._release_combat_move()
            return
        if getattr(self, '_idle_wander_until', 0) and now < self._idle_wander_until:
            self._set_combat_move(getattr(self, '_idle_wander_dir', 'right'))  # 继续走
        else:
            # 随机换方向走1~2秒
            self._idle_wander_until = now + random.randint(1000, 2000)
            self._idle_wander_pause_until = 0
            _rd = random.choice(['left', 'right'])
            if self._player_map_pos:
                _cpf = self._get_current_platform()
                if _cpf:
                    _ppx, _ = self._player_map_pos
                    _xmin, _xmax = self._platform_x_range(_cpf)
                    if _rd == 'left' and _ppx <= _xmin + 2:
                        _rd = 'right'
                    elif _rd == 'right' and _ppx >= _xmax - 2:
                        _rd = 'left'
            self._idle_wander_dir = _rd
            self._set_combat_move(_rd)
        # 走满1~2秒：停0.3~0.6秒再换方向（拟人：走动-张望-走动）
        if now >= getattr(self, '_idle_wander_until', 0):
            self._idle_wander_pause_until = now + random.randint(300, 600)
            self._idle_wander_until = 0
            self._release_combat_move()

    def _transit_step(self):
        """跨层行进执行：每帧朝目标平台（小地图坐标）移动，复用_move_to攀爬状态机（跳/瞬移/梯子，带Y验证）
        到达后重置探测随机序；失败后不停顿（有怪战斗先打=先清再上，没怪马上重试），达随机上限(2~3)才放弃换目标"""
        if not self._combat_transit or not self._transit_target or not self._player_map_pos:
            self._combat_transit = False
            self._transit_target = None
            return
        now_ms = time.time() * 1000
        # === 走台子模式（斜坡相连）：直接朝目标走，坡道自然上去；走不动(停滞1.5s/超时8s)自动降级走梯子 ===
        if getattr(self, '_transit_via', 'ladder') == 'walk':
            tx, ty = self._transit_target
            mpx, mpy = self._player_map_pos
            # === 铺了绿线：路径点导航（逐点走；分叉点上方才跳；走过头会被路径点拉回，不会越走越远）===
            _wpath = getattr(self, '_transit_walk_path', None)
            _walk_final = None   # 逐点导航最终终点(目标平台中点=_wpath[-1])：只有到它才算"到达新平台"，中间路径点只是经过
            if _wpath and len(_wpath) >= 2:
                _walk_final = (float(_wpath[-1][0]), float(_wpath[-1][1]))
                _best_i, _best_d = 0, 1e18
                for _i, (_px, _py) in enumerate(_wpath):
                    _d = abs(_px - mpx) + abs(_py - mpy)
                    if _d < _best_d:
                        _best_d = _d
                        _best_i = _i
                _nxt = None
                for _j in range(_best_i, len(_wpath)):
                    if abs(_wpath[_j][0] - mpx) + abs(_wpath[_j][1] - mpy) > 4:
                        _nxt = _wpath[_j]
                        break
                if _nxt:
                    tx, ty = float(_nxt[0]), float(_nxt[1])
                # 用法A交叉路径：当前要去的路径点在上方且已过交叉点 → 恒跳走（已知上坡道，不再试探跳）
                if ty < mpy - 2 and getattr(self, '_transit_walk_fork_idx', -1) >= 0:
                    self._transit_jump_effective = True
            # 到达收尾只认【最终终点】(无逐点路径时退回当前目标tx,ty)。
            # 【修复死循环·用户2026-09-09】旧代码拿当前近邻路径点_nxt判到达，可组合路径第一个底线点本就在人物身边(≤8/≤12)，
            # 刚启动就误判"到达新平台"→_reset_lock_after_arrival清空锁定，下帧重锁上层怪又走、又被清，
            # 永远走不到交叉点/上坡、也锁不住本层怪(表现=一直跳、不锁怪不打怪)。中间点走到只让下帧_nxt自动推进，绝不清锁定。
            _arx, _ary = _walk_final if _walk_final is not None else (tx, ty)
            if abs(mpx - _arx) <= 8 and abs(mpy - _ary) <= 12:
                # 到达最终目标平台：和梯子到达一样的收尾
                self._combat_transit = False
                self._transit_target = None
                self._probe_side = random.choice([-1, 1])
                self._probe_switched = False
                self._climb_fail_count = 0
                self._climb_fail_limit = random.choice([2, 3])
                self._climb_fail_pause_until = 0
                self._transit_via = 'ladder'
                self._release_combat_move()
                self._release_all_keys()
                self._reset_lock_after_arrival()   # 走到新平台同样强制重新识别+重新锁定
                print("[跨层] 走台子到达目标，开始新一轮打怪")
                return
            if now_ms - getattr(self, '_transit_walk_started', now_ms) > 8000:
                self._transit_via = 'ladder'  # 走台子超时 → 改走梯子
                self._transit_walk_started = now_ms
                self._release_combat_move()
                _debug_log("[跨层] 走台子超时8秒，改走梯子")
                return
            _mdx = tx - mpx
            if abs(_mdx) > 4:
                _dir = "right" if _mdx > 0 else "left"
                self._set_combat_move(_dir)
                # === 上坡"试探跳+验证"（用户规则：不能空跳测试）===
                # 目标在人物上方时：跳一次 → 检测人物小地图Y是否上升(有效=有坡/台阶，进入跳着走)；
                # 没上升=空跳无效 → 停止跳（只走，走不动交给停滞检测转梯子），2.5~4秒后再试探一次
                if ty < mpy - 2:
                    _jump_key = self._get_fight_config().get("jump_key", "")
                    _probe_y = getattr(self, '_transit_jump_probe_y', None)
                    _probe_t = getattr(self, '_transit_jump_probe_t', 0)
                    if _probe_y is not None and now_ms - _probe_t > 800:
                        # 验证上次试探跳：人物上升=有效
                        if mpy < _probe_y - 2:
                            self._transit_jump_effective = True
                            _debug_log("[跨层] 试探跳有效(人物上升)，进入跳走模式")
                        else:
                            self._transit_jump_effective = False
                            self._transit_jump_probe_next = now_ms + random.randint(2500, 4000)  # 空跳无效，隔段时间再试
                    if _jump_key:
                        if getattr(self, '_transit_jump_effective', False):
                            # 有效：跳着走（450ms间隔）
                            if now_ms - getattr(self, '_combat_last_jump', 0) > 450:
                                self._press_game_key(_jump_key, duration=80)
                                self._combat_last_jump = now_ms
                        elif getattr(self, '_transit_jump_probe_next', 0) == 0 or \
                                now_ms >= getattr(self, '_transit_jump_probe_next', 0):
                            # 试探跳（走近一点才试，避免远处乱跳）
                            if abs(_mdx) <= 250:
                                self._press_game_key(_jump_key, duration=80)
                                self._transit_jump_probe_y = mpy
                                self._transit_jump_probe_t = now_ms
                                self._transit_jump_probe_next = 0
                # 停滞检测：朝目标走但X位置不动超过2.5秒（含跳跃弧线缓冲）→ 被挡，改走梯子
                _last_x = getattr(self, '_transit_walk_last_x', None)
                if _last_x is None or abs(mpx - _last_x) < 2:
                    self._transit_walk_stall = getattr(self, '_transit_walk_stall', 0) or now_ms
                    if now_ms - self._transit_walk_stall > 2500:
                        self._transit_via = 'ladder'
                        self._transit_walk_stall = 0
                        self._release_combat_move()
                        _debug_log("[跨层] 走台子停滞2.5秒，改走梯子")
                        return
                else:
                    self._transit_walk_stall = 0
                    self._transit_walk_last_x = mpx
            else:
                self._release_combat_move()
                # X已对齐但Y没到（怪在上面被挡）：走2秒仍上不去 → 改走梯子
                if abs(mpy - ty) > 8 and now_ms - getattr(self, '_transit_walk_started', now_ms) > 2000:
                    self._transit_via = 'ladder'
                    _debug_log("[跨层] 走台子X已对齐但Y未到达，改走梯子")
                    return
            return
        # 【用户2026-09-09】取消"失败2~3次就放弃/歇3~8秒/随机决策"整套机制：任何上梯/上跳失败都在 _move_to 内
        # 调 _decide_climb_fail_action 直接复位回主线(识怪→锁定→巡路→打怪)——本层有怪先打完，本层清空后主线自然又
        # 决策出"上梯子"，自成循环，不计数、不放弃、不长暂停(仅保留失败后300~500ms防原地连跳短冷却)。
        arrived = self._move_to(self._player_map_pos, self._transit_target[0], self._transit_target[1])
        if arrived:
            self._combat_transit = False
            self._transit_target = None
            # 到顶保护(用户2026-09-09)：跨层刚翻上平台的1秒内不启用跳高打，避免人没站稳被high_slope按跳从梯顶跳下来
            self._slope_resume_at = now_ms + 1000
            self._probe_side = random.choice([-1, 1])  # 新平台新一轮探测：先看左/右随机
            self._probe_switched = False
            self._climb_fail_count = 0                 # 成功到达：失败计数清零
            self._climb_fail_limit = random.choice([2, 3])  # 下轮上限重新随机
            self._climb_fail_pause_until = 0
            self._release_all_keys()
            self._reset_lock_after_arrival()   # 到顶强制重新识别+重新锁定(用户2026-09-09，防粘旧目标/空转/往回跑)
            print("[跨层] 到达目标平台，开始新一轮打怪")

    def _try_farm_same_platform(self, now):
        """同平台远处再打一波（用户2026-09-07随机决策）：本层没怪时，50%概率不跨层，
        而是走到当前平台离人物最远的端点重新扫怪。走到后重置跨层状态，下一帧自然重新选怪/再随机。
        返回True=已启动行走；False=当前平台无绿线/已在端点，不启动（交给跨层逻辑）。"""
        cur_pf = self._get_current_manual_platform()
        if not cur_pf or not self._player_map_pos:
            return False
        pts = self._platform_points(cur_pf)
        if not pts or len(pts) < 2:
            return False
        mpx, mpy = self._player_map_pos
        # 取绿线两个端点中离人物最远的那个（去远端扫一波）
        _d0 = abs(float(pts[0][0]) - mpx)
        _d1 = abs(float(pts[-1][0]) - mpx)
        far_pt = pts[-1] if _d1 > _d0 else pts[0]
        target_mid = (float(far_pt[0]), float(far_pt[1]))
        # 已经在端点附近：不用走，交给跨层逻辑
        if abs(mpx - target_mid[0]) <= 8 and abs(mpy - target_mid[1]) <= 12:
            return False
        # 启动行进（同层Y差≤8，走台子模式不会触发梯子；走到端点后_transit_step自动重置）
        self._release_combat_move()
        self._release_all_keys()
        self._combat_transit = True
        self._transit_target = target_mid
        self._transit_via = 'walk'
        self._transit_walk_path = None
        self._transit_walk_fork_idx = -1
        self._transit_walk_started = now
        self._transit_walk_last_x = None
        self._transit_walk_stall = 0
        self._transit_jump_probe_y = None
        self._transit_jump_probe_t = 0
        self._transit_jump_probe_next = 0
        self._transit_jump_effective = False
        print("[跨层] 随机选择：同平台远处再打一波，前往端点(%.0f,%.0f)" % target_mid)
        return True

    def _trans_stall_diag(self, reason, now, **kw):
        """跨层"启动不起来"的静默出口诊断(限频1s)：定位"决策一直cross、人却原地不动"到底卡在哪一个return False。
        只记录、不改变行为。写debug全量+行为面板限频上屏，让用户/排查直接看到受阻原因。"""
        if not hasattr(self, '_trans_stall_last'):
            self._trans_stall_last = 0
        if now - self._trans_stall_last < 1000:
            return
        self._trans_stall_last = now
        try:
            _msg = " ".join("%s=%s" % (k, v) for k, v in kw.items())
        except Exception:
            _msg = ""
        _debug_log("[跨层卡住] reason=%s %s" % (reason, _msg))
        self._rlog_throttle('trans_stall', "跨层启动受阻:%s" % reason, 1000, log='behavior')

    def _try_platform_transition(self, cross_candidates, now):
        """【模块B】跨层决策：同平台500px内无怪时，选"最近有怪目标平台"（选台模式）
        或"最近的怪"（全图模式）作为跨层目标，复用_move_to攀爬状态机
        返回True=已启动跨层行进；False=没有可去目标（松手等刷怪）"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._trans_stall_diag('no_pos(人物小地图/屏幕坐标缺失,多为人物特征没匹配上)', now, map_pos=self._player_map_pos, screen_pos=self._player_screen_pos)
            return False
        mpx, mpy = self._player_map_pos   # 提前解包：下方 lambda 排序/路径计算用到（修复先用后定义）
        # 拟人：随机放弃后重新选目标前短时随机（有怪则战斗先行，不是发呆）
        if getattr(self, '_climb_fail_pause_until', 0) and now < self._climb_fail_pause_until:
            self._trans_stall_diag('fail_pause(爬梯失败短冷却中)', now, left_ms=int(self._climb_fail_pause_until - now))
            return False
        target_mid = None
        # 【用户2026-09-08】默认走梯子/下跳/瞬移；只有目标怪在录制的绿线台子上(monster_pf不为None)时才走绿线
        # 没有绿线/怪不在绿线上→直接找梯子，不要先走台子试试(走不通浪费时间)
        self._transit_via = 'ladder'
        self._transit_walk_path = None  # 铺了绿线时的路径点导航列表（逐点走）
        self._transit_walk_fork_idx = -1  # 交叉点(分叉口)在路径中的位置：过了它恒跳走
        if cross_candidates:
            # 有怪：取最近的怪
            cross_candidates.sort()
            _, fx, fy = cross_candidates[0]
            # 铺了路（绿线）：底线+上坡线两条交叉=分叉口 → 先走底线到交叉点，过点后恒跳走（用户用法A）
            # 【用户2026-09-08】怪在绿线上还不够，必须人物也在绿线上+两平台绿线有交叉点(相连没断)才走绿线；否则走梯子
            monster_pf = self._get_monster_platform(fx, fy)
            cur_pf = self._get_current_manual_platform() if monster_pf else None
            inter = self._find_platform_intersection(cur_pf, monster_pf) if (monster_pf and cur_pf) else None
            if monster_pf and cur_pf and inter:
                # 人物和怪都在绿线上+绿线相连有交叉点：走绿线组合路径
                self._transit_via = 'walk'
                pts = self._platform_points(monster_pf)
                target_mid = (float(pts[len(pts) // 2][0]), float(pts[len(pts) // 2][1]))
                _path = []
                # 组合路径：底线点(离人物近的在前) → 交叉点 → 上坡线点(离交叉点近的在前)
                _bpts = sorted(self._platform_points(cur_pf),
                               key=lambda p: (abs(float(p[0]) - mpx) + abs(float(p[1]) - mpy)))
                _path += [(float(p[0]), float(p[1])) for p in _bpts]
                _path.append((float(inter[0]), float(inter[1])))
                _fork = len(_path) - 1
                _tpts = sorted(self._platform_points(monster_pf),
                               key=lambda p: (abs(float(p[0]) - inter[0]) + abs(float(p[1]) - inter[1])))
                _path += [(float(p[0]), float(p[1])) for p in _tpts]
                self._transit_walk_fork_idx = _fork  # 交叉点位置：过了它就恒跳走
                self._transit_walk_path = _path
                target_mid = _path[-1]
                _debug_log("[跨层] 绿线相连有交叉点(%.0f,%.0f)，走绿线组合路径(%d点)" % (inter[0], inter[1], len(_path)))
            else:
                # 怪不在绿线/人物不在绿线/绿线不相连：目标=怪的估算小地图位置，走梯子/下跳/瞬移
                if monster_pf:
                    _debug_log("[跨层] 怪在绿线但人物不在绿线或绿线不相连，改走梯子")
                map_pos = self._get_monster_map_pos_verified(fx, fy)
                if map_pos:
                    target_mid = (float(map_pos[0]), float(map_pos[1]))
                else:
                    self._transit_via = 'ladder'  # 兜底：无任何换算信息，走梯子路径
        else:
            # 全地图没怪：选台模式 → 去下一个选中台子（编号最小且不是当前的）；全图模式 → 原地等刷怪
            if self._selected_platforms:
                cur_pf = self._get_current_manual_platform()
                cur_num = (cur_pf.get('id', 0) + 1) if (cur_pf and isinstance(cur_pf, dict)) else None
                next_pf = None
                for pf in self.platforms:
                    pm = pf.get('id', 0) + 1
                    if pm not in self._selected_platforms or pm == cur_num:
                        continue
                    if next_pf is None or pm < next_pf.get('id', 0) + 1:
                        next_pf = pf
                if next_pf is None:
                    self._trans_stall_diag('no_next_platform(只选了当前台/无下一台可去)', now, selected=self._selected_platforms, cur=cur_num)
                    return False  # 只选了一个台子：原地等刷怪
                pts = self._platform_points(next_pf)
                target_mid = (float(pts[len(pts) // 2][0]), float(pts[len(pts) // 2][1]))
            else:
                self._trans_stall_diag('idle_no_platform(全图无怪且未选台,原地等刷)', now)
                return False  # 全图模式无怪：原地等刷怪
        if target_mid is None:
            self._trans_stall_diag('target_none(有cross怪但换算不出小地图目标点/怪不在绿线)', now,
                                   n_cands=len(cross_candidates), via=self._transit_via)
            return False
        # 上高层必须能找到梯子路径，否则放弃本次跨层（走台子模式除外——斜坡可直接走上去）——2026-09-04
        if self._transit_via == 'ladder' and target_mid[1] < mpy - 8 and self._find_nearest_ladder(mpx, mpy, target_mid[1]) is None:
            _debug_log("[跨层] 目标在上层但无可用梯子，放弃本次跨层等刷怪")
            return False
        # 目标已在附近（到达判定），不需要启动
        # 【2026-09-09修复already_near误杀跨层·真机3条跨层卡住诊断实锤】小地图scale_y很小(实测0.06),
        # 屏幕Y差150+的上层怪经_screen_to_map换算到小地图Y只差几px,会被这里误判"已到身边"而永不启动跨层
        # (=决策一直cross、人却原地不上梯的根因之一)。cross怪必须【屏幕Y差也小=真同层近身】才算到;
        # 屏幕上仍明显分层(Y差>主攻上方Y范围)就不许在此return,继续找梯子上去。选台模式(无cross怪)保持原小地图判定。
        _near_map = abs(mpx - target_mid[0]) <= 8 and abs(mpy - target_mid[1]) <= 8
        _screen_layer_gap = -1
        _same_layer_screen = True
        if _near_map and cross_candidates and self._player_screen_pos:
            try:
                _atk_up = abs(int(self._get_fight_config().get("attack_y_up", -80) or -80))
            except (TypeError, ValueError):
                _atk_up = 80
            _c0 = sorted(cross_candidates)[0]          # 最近cross怪(屏幕坐标)
            _screen_layer_gap = abs(_c0[2] - self._player_screen_pos[1])
            _same_layer_screen = _screen_layer_gap <= max(40, _atk_up)
        if _near_map and (not cross_candidates or _same_layer_screen):
            self._trans_stall_diag('already_near(目标换算后就在身边)', now,
                                   player=(round(mpx,1), round(mpy,1)), target=(round(target_mid[0],1), round(target_mid[1],1)),
                                   screen_ygap=_screen_layer_gap)
            return False
        if _near_map:
            _debug_log("[跨层] 小地图看似已近但屏幕Y差%d仍分层(>同层阈值),继续跨层不走already_near(治scale_y小误判)" % _screen_layer_gap)
        # 先释放所有旧移动键（战斗移动键+巡路移动键），再启动跨层行进
        self._combat_active = False
        self._release_combat_move()
        self._release_all_keys()
        self._combat_transit = True
        self._transit_target = target_mid
        self._transit_walk_started = now          # 走台子计时起点
        self._transit_walk_last_x = None
        self._transit_walk_stall = 0
        self._transit_jump_probe_y = None         # 上坡试探跳：跳前Y（用于验证是否上升=有坡）
        self._transit_jump_probe_t = 0
        self._transit_jump_probe_next = 0         # 空跳无效后的下次试探时间
        self._transit_jump_effective = False      # 试探跳是否有效（有效=持续跳着走）
        print("[跨层] 同平台无怪，前往目标平台(%s) 目标(%.0f,%.0f)" % (
            "走台子" if self._transit_via == 'walk' else "走梯子", target_mid[0], target_mid[1]))
        return True

    def _shadow_combat_decision(self):
        """【Phase A 影子日志】用新决策核心(combat_logic)算一遍当前该怎么做，打印出来，
        但绝不改变bot实际行为。目的：真机跑一次，核对"新决策"是否与实际一致；
        一致才进入Phase B真正切换。任何异常只记录，不影响主流程。"""
        try:
            import combat_logic as _cl
            pos = self._player_screen_pos
            if not pos:
                return
            px, py = pos
            fight_cfg = self._get_fight_config()
            skill_range = int(fight_cfg.get("atk1_distance", 150) or 150)
            _sy_up = abs(int(fight_cfg.get("attack_y_up", -ATTACK_Y_UP)))
            _sy_dn = abs(int(fight_cfg.get("attack_y_down", ATTACK_Y_DOWN)))
            _s_farx = max(50, int(fight_cfg.get("far_range_x", COMBAT_FAR_RANGE) or COMBAT_FAR_RANGE))
            self._far_range_y_up = max(10, int(fight_cfg.get("far_range_y_up", FAR_RANGE_Y_UP_DEFAULT) or FAR_RANGE_Y_UP_DEFAULT))
            self._far_range_y_down = max(10, int(fight_cfg.get("far_range_y_down", FAR_RANGE_Y_DOWN_DEFAULT) or FAR_RANGE_Y_DOWN_DEFAULT))
            lock = self._combat_locked_target
            lcx, lcy = (lock if lock else (None, None))
            d = _cl.select_combat_target(
                px, py, self._monsters, self._selected_platforms, skill_range,
                _s_farx, lcx, lcy, self._combat_target_alive,
                self._is_monster_on_platform, self._get_monster_platform,
                self._probe_side, self._probe_switched,
                getattr(self, '_shadow_cross_target', None), _sy_up, _sy_dn, True)
            # 跨层目标稳定：选了就维持，避免左右摇摆
            self._shadow_cross_target = d['target'] if d['state'] == 'cross' else None
            _debug_log("[新决策] state=%s 目标=%s 方向=%s 距离=%s 实际锁定=%s 活着=%s" % (
                d['state'], d['target'], d['direction'], d['dist'],
                self._combat_locked_target, self._combat_target_alive))
        except Exception as e:
            print("[新决策] 影子日志异常:", e)
            _debug_log("[新决策] 影子日志异常: " + str(e))

    def _filter_static_monsters(self, monsters):
        """锁怪前识别环节：同一位置被连续识别N次仍不动=识别错(建筑/背景误检)→临时排除。用户2026-09-05规则。
        不固定等1秒：每秒多次识别；若这多次都在同一位置(中心移动≤STATIC_MOVE_TOL)，投票+1；
        同位置连续STATIC_VOTE_N票(约1秒) → 临时排除该位置STATIC_EXCLUDE_MS(3秒)，时间到恢复，若还静态再重投。
        保持少量输出，避免把整个列表剔空。返回过滤后的怪物列表。"""
        if not monsters:
            return monsters
        now_ms = time.time() * 1000
        track = getattr(self, '_monster_static_track', {})  # key=(cx//40,cy//40) -> {cx,cy,count,last,excluded_until}
        new_track = {}
        out = []
        removed = 0
        _lock = self._combat_locked_target
        for (x1, y1, x2, y2, score) in monsters:
            cx = (x1 + x2) // 2
            cy = y2
            key = (cx // 40, cy // 40)
            # 正在锁定/攻击的怪不剔：否则正要打死就被当假怪剔掉，打打停停(用户2026-09-05)
            if _lock is not None and abs(cx - _lock[0]) <= 60 and abs(cy - _lock[1]) <= 60:
                new_track[key] = track.get(key) or {'cx': cx, 'cy': cy, 'count': 1, 'last': now_ms, 'excluded_until': 0}
                out.append((x1, y1, x2, y2, score))
                continue
            # 同平台怪(人物近旁、bot该打的真怪)绝不剔：站定不动不是误检，否则"明明有怪就不打"(用户2026-09-05)。
            # 误检(背景/建筑)多在人物上方不同平台(Y差大)，仍走下方静止投票剔除。
            if self._is_monster_on_platform(cx, cy):
                new_track[key] = track.get(key) or {'cx': cx, 'cy': cy, 'count': 1, 'last': now_ms, 'excluded_until': 0}
                out.append((x1, y1, x2, y2, score))
                continue
            rec = track.get(key)
            if rec:
                # 临时排除期内：直接剔除该位置怪
                if now_ms < rec.get('excluded_until', 0):
                    new_track[key] = rec
                    removed += 1
                    continue
                # 同位置判定：中心移动≤容差=没动，投票+1；动了=重置
                if abs(cx - rec['cx']) <= STATIC_MOVE_TOL and abs(cy - rec['cy']) <= STATIC_MOVE_TOL:
                    rec['count'] += 1
                else:
                    rec['cx'] = cx
                    rec['cy'] = cy
                    rec['count'] = 1
                rec['last'] = now_ms
                # 同位置连续N票 → 临时排除
                if rec['count'] >= STATIC_VOTE_N:
                    rec['excluded_until'] = now_ms + STATIC_EXCLUDE_MS
                    rec['count'] = 0  # 恢复后若仍静态再重新投票
                    removed += 1
                    _debug_log("[静态过滤] 位置(%d,%d)被连续识别%d次在同一位置(疑似识别错)，临时排除%.1f秒" % (
                        cx, cy, STATIC_VOTE_N, STATIC_EXCLUDE_MS / 1000.0))
                    continue
                new_track[key] = rec
            else:
                new_track[key] = {'cx': cx, 'cy': cy, 'count': 1, 'last': now_ms, 'excluded_until': 0}
            out.append((x1, y1, x2, y2, score))
        # 清掉久未见的桶（默认8秒超时）
        self._monster_static_track = {k: v for k, v in new_track.items() if now_ms - v['last'] < 8000}
        # 若剔得只剩0只但原列表有怪：保留原列表(避免误剔真怪导致彻底不打)
        if removed > 0 and not out and monsters:
            _debug_log("[静态过滤] 剔除%d只疑似静止怪，但为避免全空，保留原列表" % removed)
            return monsters
        return out

    def _temporal_smooth_detections(self, merged):
        """检测稳定化：YOLO 对同一只怪会闪检(有时检出/有时没检出)。
        把"本帧检出的怪"并入近期列表(同一只按中心位置去重、EMA平滑位置)，每只怪用随机1500-2000ms的保留到期时间，
        到点清除；返回近期列表：本帧漏检但近期还在的怪也保留，避免走进/切怪时目标单帧闪没→犹豫/卡(用户2026-09-05)。"""
        if not merged and not hasattr(self, '_detect_recent'):
            return []
        now_ms = time.time() * 1000
        if not hasattr(self, '_detect_recent'):
            self._detect_recent = []  # [(x1,y1,x2,y2,score,expire_at_ms)]
        recent = self._detect_recent
        # 过期清除(每只怪用各自到期时间)
        recent = [(x1, y1, x2, y2, s, ex) for (x1, y1, x2, y2, s, ex) in recent if now_ms < ex]
        # 把本帧检出的怪并入(更新或新增)，到期时间=now+随机1500-2000ms
        for (x1, y1, x2, y2, s) in merged:
            cx = (x1 + x2) // 2
            cy = y2
            found = False
            for i in range(len(recent)):
                ox1, oy1, ox2, oy2, os, oex = recent[i]
                ocx = (ox1 + ox2) // 2
                ocy = oy2
                if abs(cx - ocx) <= 60 and abs(cy - ocy) <= 60:  # 中心接近=同一只
                    # 位置EMA平滑：新检测权重0.6+旧位置0.4，减少框体晃来晃去(用户2026-09-05"识别到的不稳定")
                    recent[i] = (int(0.6 * x1 + 0.4 * ox1), int(0.6 * y1 + 0.4 * oy1),
                                 int(0.6 * x2 + 0.4 * ox2), int(0.6 * y2 + 0.4 * oy2), s,
                                 now_ms + random.randint(MON_DETECT_KEEP_MIN, MON_DETECT_KEEP_MAX))
                    found = True
                    break
            if not found:
                recent.append((x1, y1, x2, y2, s, now_ms + random.randint(MON_DETECT_KEEP_MIN, MON_DETECT_KEEP_MAX)))
        self._detect_recent = recent
        return [(x1, y1, x2, y2, s) for (x1, y1, x2, y2, s, ex) in recent]

    def _filter_dropped_phantoms(self, monsters):
        """剔除两类怪，避免死循环/原地卡：
        ①最近被判定空怪/已放弃位置±60px内的怪(打一下无血条无伤害→drop,3秒不重锁)；
        ②被短时压制的那一侧怪(用户2026-09-07：某侧地形过不去,3秒内不锁该侧、改锁另一侧,到期自动恢复)。"""
        if not monsters:
            return monsters
        now_ms = time.time() * 1000
        # 只保留近3秒内的空怪记录
        self._combat_dropped_phantoms = [(cx, cy, t) for (cx, cy, t) in self._combat_dropped_phantoms
                                         if now_ms - t < 3000]
        # 被压制侧到期清除
        if self._combat_suppress_side is not None and now_ms >= self._combat_suppress_side[1]:
            self._combat_suppress_side = None
        _ss = self._combat_suppress_side
        _ppx = self._player_screen_pos[0] if self._player_screen_pos else None
        if not self._combat_dropped_phantoms and not (_ss and _ppx is not None):
            return monsters
        out = []
        for (x1, y1, x2, y2, score) in monsters:
            cx = (x1 + x2) // 2
            cy = y2
            near = False
            for (dx, dy, _t) in self._combat_dropped_phantoms:
                if abs(cx - dx) <= 60 and abs(cy - dy) <= 60:
                    near = True
                    break
            # 被压制侧：怪相对人物在该侧(右=怪X≥人X)则本帧不锁
            side_blocked = bool(_ss and _ppx is not None
                                and (('right' if cx >= _ppx else 'left') == _ss[0]))
            if not near and not side_blocked:
                out.append((x1, y1, x2, y2, score))
        return out

    def _merge_detections(self, yolo_monsters, feature_monsters):
        """合并YOLO+怪物特征匹配结果，去重(距离太近保留置信度高的)。返回 [(x1,y1,x2,y2,score)]"""
        _all_m = list(yolo_monsters) + list(feature_monsters)
        _all_m.sort(key=lambda m: m[4], reverse=True)
        _merged_m = []
        _used_m = [False] * len(_all_m)
        for _i, _m1 in enumerate(_all_m):
            if _used_m[_i]:
                continue
            _merged_m.append(_m1)
            _used_m[_i] = True
            _c1x = (_m1[0] + _m1[2]) // 2
            _c1y = (_m1[1] + _m1[3]) // 2
            for _j in range(_i + 1, len(_all_m)):
                if _used_m[_j]:
                    continue
                _m2 = _all_m[_j]
                _c2x = (_m2[0] + _m2[2]) // 2
                _c2y = (_m2[1] + _m2[3]) // 2
                _dist = ((_c1x - _c2x) ** 2 + (_c1y - _c2y) ** 2) ** 0.5
                if _dist < max(_m1[2] - _m1[0], _m1[3] - _m1[1]) * 0.6:
                    _used_m[_j] = True
        return _merged_m

    def _detection_loop(self):
        """后台检测线程：约每 150ms(DETECT_PERIOD_MS) 截一张图，人物+怪+YOLO+血条全部在这张同一帧上算(同帧同步→距离准)。
        主线程只读结果做战斗/小地图/蒙板，不再做重活；自己建 mss 实例，避免与主线程共用打架。"""
        import mss as _mss_mod
        try:
            _sct = _mss_mod.mss()
        except Exception as _e:
            print("[检测线程] mss初始化失败:", _e)
            return
        # 窗口矩形(客户区)获取
        self._detect_lock.acquire()
        self._detect_sct = _sct
        self._detect_lock.release()
        last_rect = None
        # [CPU诊断2026-09-07] 检测线程各阶段耗时统计，每秒汇总一条到debug.log（定位检测线程CPU大头）
        _dt_grab = _dt_char = _dt_feat = _dt_yolo = _dt_bars = 0.0
        _dt_rounds = 0
        _dt_last_report = time.time()
        while self._detect_running:
            _t0 = time.time()
            try:
                if self.hwnd is not None:
                    # 获取窗口客户区矩形
                    _r = self.window_rect
                    if _r is None:
                        self._update_window_rect()
                        _r = self.window_rect
                    if _r:
                        _mon = {"left": _r['left'], "top": _r['top'],
                                "width": _r['width'], "height": _r['height']}
                        _tg0 = time.time()
                        # mss(BitBlt)从屏幕DC截游戏窗口矩形（定稿方案，不换底层），瞬时失败本轮跳过沿用上次结果
                        _frame = None
                        try:
                            _frame = np.array(_sct.grab(_mon))[:, :, :3]
                        except Exception:
                            _frame = None
                        _dt_grab += time.time() - _tg0
                    else:
                        _frame = None
                    if _frame is not None:
                        # 固定识别带(整窗坐标):只在 y∈[30,H-90] 识别人物/怪,顶去标题栏、底去血蓝/技能UI栏,防UI误检
                        _fh, _fw = _frame.shape[:2]
                        _band_y1 = DETECT_TOP_MARGIN
                        _band_y2 = max(_band_y1 + 1, _fh - DETECT_BOTTOM_MARGIN)
                        # 同一张帧：人物、怪、血条全在这张上算
                        _tc0 = time.time()
                        _ch = self._get_player_screen_pos(_frame)  # 人物每周期匹配(ROI很轻,丢失才全图),保证人物点跟手
                        # 人物点落在顶部标题栏/底部UI带=误匹配(人物不可能站UI上),作废,避免拿假人物点算距离/锁怪
                        if _ch is not None and not (_band_y1 <= _ch[1] <= _band_y2):
                            _ch = None
                        _dt_char += time.time() - _tc0
                        # 怪物模板匹配/YOLO都是重活：统一限到约3Hz(330ms)，中间周期复用上一次结果；
                        # 怪物另有2秒宽限不会闪没；进一步降CPU(2026-09-07整机80%仍偏高,二档降压)
                        if not hasattr(self, '_yolo_cache'):
                            self._yolo_cache, self._yolo_last_t = [], 0.0
                            self._feat_cache, self._feat_last_t = [], 0.0
                            self._bars_cache, self._bars_last_t = [], 0.0
                        _now_det = time.time()
                        # 战斗配置(技能射程/Y带)提前算：YOLO分档、血条ROI都要用，避免重复取配置
                        _fc = self._get_fight_config()
                        _skr = int(_fc.get("atk1_distance", 150) or 150)
                        _yupr = abs(int(_fc.get("attack_y_up", -ATTACK_Y_UP)))
                        _ydnr = abs(int(_fc.get("attack_y_down", ATTACK_Y_DOWN)))
                        # 2026-09-08 检测范围裁剪优化：
                        # YOLO用寻怪范围(X左右各 + Y上方 + Y下方)限定识别区域→只识别人物周围范围内的怪，范围外不识别(省资源+用户要求)；
                        # 特征匹配用技能范围限定模板搜索区域→省CPU；
                        # 人物丢失或范围为空→传None全图检测(兜底)。
                        _far_x = int(_fc.get("far_range_x", 0) or 0)
                        _far_y_up = int(_fc.get("far_range_y_up", 0) or 0)
                        _far_y_down = int(_fc.get("far_range_y_down", 0) or 0)
                        # 动态寻怪范围(整窗坐标);无人物/范围空→退化为固定识别带全宽(YOLO也不碰上下UI带)
                        if _ch is not None and _far_x > 0 and (_far_y_up > 0 or _far_y_down > 0):
                            _dyx1 = max(0, _ch[0] - _far_x)
                            _dyx2 = min(_fw, _ch[0] + _far_x)
                            _dyy1 = _ch[1] - _far_y_up if _far_y_up > 0 else _band_y1
                            _dyy2 = _ch[1] + _far_y_down if _far_y_down > 0 else _band_y2
                        else:
                            _dyx1, _dyx2, _dyy1, _dyy2 = 0, _fw, _band_y1, _band_y2
                        # 统一夹到固定识别带:纵向绝不越界到标题栏/UI栏,横向夹整窗;退化非法时回退整带
                        _yolo_crop = (max(0, _dyx1), max(_band_y1, _dyy1), min(_fw, _dyx2), min(_band_y2, _dyy2))
                        if _yolo_crop[2] <= _yolo_crop[0] or _yolo_crop[3] <= _yolo_crop[1]:
                            _yolo_crop = (0, _band_y1, _fw, _band_y2)
                        # 特征匹配范围:以人物技能范围为动态区(同样夹进固定带);无人物用固定带全宽
                        if _ch is not None:
                            _ftx1, _ftx2 = max(0, _ch[0] - _skr), min(_fw, _ch[0] + _skr)
                            _fty1, _fty2 = max(_band_y1, _ch[1] - _yupr), min(_band_y2, _ch[1] + _ydnr)
                        else:
                            _ftx1, _ftx2, _fty1, _fty2 = 0, _fw, _band_y1, _band_y2
                        _feat_crop = (_ftx1, _fty1, _ftx2, _fty2)
                        if _feat_crop[2] <= _feat_crop[0] or _feat_crop[3] <= _feat_crop[1]:
                            _feat_crop = (0, _band_y1, _fw, _band_y2)
                        if _now_det - self._feat_last_t >= 0.33:
                            _tf0 = time.time()
                            self._feat_cache = self._match_monster(_frame, _feat_crop) if self._monster_templates else []
                            _dt_feat += time.time() - _tf0
                            self._feat_last_t = _now_det
                        _feat = self._feat_cache
                        # YOLO全图分档(用户2026-09-07)：正锁着【技能范围内】怪=正在打,降到2Hz省最大头(近身怪由技能范围怪模板维持)；
                        # 无锁/锁的是范围外怪=正在寻敌,提到4Hz,打完一只/发现新怪更快(治"换锁要等几秒")
                        _lk = getattr(self, '_combat_locked_target', None)
                        _locked_in = bool(_lk) and _ch is not None and abs(_lk[0] - _ch[0]) <= _skr \
                            and -_yupr <= (_lk[1] - _ch[1]) <= _ydnr
                        _yolo_gap = YOLO_SLOW_S if _locked_in else YOLO_FAST_S
                        if _now_det - self._yolo_last_t >= _yolo_gap:
                            _ty0 = time.time()
                            self._yolo_cache = self._detect_monsters(_frame, _yolo_crop)
                            _dt_yolo += time.time() - _ty0
                            self._yolo_last_t = _now_det
                        _yolo = self._yolo_cache
                        _merged = self._merge_detections(_yolo, _feat)
                        # 血条搜索区【冒险岛世界2026-09-07】以人物技能范围为主：只检测"技能射程+Y范围"内怪的头顶，
                        # 范围外的怪不会被打、其血条也不该参与存活判定——既降误判又省算力；人物没定位到时退化为全怪头顶
                        _search = []
                        for (x1, y1, x2, y2, _s) in _merged:
                            _mcx, _mcy = (x1 + x2) // 2, y2  # 怪中心X / 脚Y
                            if _ch is None or (abs(_mcx - _ch[0]) <= _skr
                                               and -_yupr <= (_mcy - _ch[1]) <= _ydnr):
                                _search.append((max(0, x1 - 15), max(0, y1 - 40), x2 + 15, y1 + 5))
                        # 上次锁定目标头顶：同样限技能范围(略放宽40)，避免换目标瞬间丢血条
                        if self._combat_last_target_pos and _ch is not None:
                            _tx, _ty = self._combat_last_target_pos
                            if abs(_tx - _ch[0]) <= _skr + 40:
                                _search.append((max(0, _tx - 50), max(0, _ty - 55),
                                                min(_frame.shape[1], _tx + 50), min(_frame.shape[0], _ty + 10)))
                        # 血条扫描节流到BARS_SCAN_S(和怪表3Hz对齐)：怪表没更新的空轮ROI一样,复用上一次结果,省第二大头
                        if _now_det - self._bars_last_t >= BARS_SCAN_S:
                            _tb0 = time.time()
                            self._bars_cache = self._detect_monster_hp_bars(_frame, _search if _search else None)
                            _dt_bars += time.time() - _tb0
                            self._bars_last_t = _now_det
                        _bars = self._bars_cache
                        # 发布结果（原子引用替换）
                        # 怪物2秒宽限：这一轮检测为空但2秒内有怪，保留上次结果，避免偶发漏检导致怪点闪没
                        if _merged:
                            self._detect_last_monsters = _merged
                            self._detect_last_monsters_time = time.time()
                        elif (time.time() - self._detect_last_monsters_time < 2.0
                              and self._detect_last_monsters):
                            _merged = self._detect_last_monsters
                        # 检测稳定化：YOLO单帧漏检不清目标(用户2026-09-05，闪检的怪能一直被锁定/攻击)
                        _merged = self._temporal_smooth_detections(_merged)
                        # 固定识别带兜底:剔除框中心落在顶部标题栏/底部UI带的检测(防时序平滑历史框/cache把UI误当怪)
                        _merged = [b for b in _merged if _band_y1 <= (b[1] + b[3]) // 2 <= _band_y2]
                        self._raw_char_pos = _ch
                        self._raw_cached_feature_monsters = _feat
                        self._raw_monsters = _merged
                        self._raw_hp_bars = _bars
                        # 2026-09-07 CPU优化·截图共用：把本帧发布给主线程复用(自动吃药/伤害检测/镜头检测不再各自全窗口截图)。
                        # 原子引用替换(与_raw_monsters同机制)；帧龄由读取方用 _raw_frame_t 判断，超龄才补截。
                        self._raw_frame = _frame
                        self._raw_frame_t = time.time()
                        if _merged:
                            self._last_monster_seen = time.time()  # 自适应降频：见到怪→回到战斗快周期
                        # A1修复：_feat是5元组怪物框(x1,y1,x2,y2,score)，绝不能覆盖特征点(蒙板按4元组 x,y,模板号,置信度 解包)。
                        # 有怪物模板时 _match_monster内部(约6886行)已把 self._monster_feature_matches 设为正确4元组，这里不能再覆盖；仅无模板时清空。
                        if not self._monster_templates:
                            self._monster_feature_matches = []
                        self._char_feature_matches = getattr(self, '_char_feature_matches', [])
            except Exception as _e:
                if self._detect_running:
                    print("[检测线程] 异常:", _e)
            # 自适应周期(用户2026-09-07 CPU94%)：最近0.4s见到怪、或正锁着怪/在战斗 → 150ms跟手；否则空闲300ms省电降占用
            _busy = (time.time() - self._last_monster_seen < 0.4) or bool(getattr(self, '_combat_locked_target', None))
            _period = DETECT_PERIOD_MS if _busy else DETECT_IDLE_MS
            _elapse = (time.time() - _t0) * 1000
            # [CPU诊断2026-09-07] 每约1秒汇总检测线程各阶段耗时(毫秒)，定位检测侧CPU大头
            _dt_rounds += 1
            _dt_now = time.time()
            if _dt_now - _dt_last_report >= 1.0:
                _msg = "[检测耗时] %d轮 周期%s 截图%d 人物%d 怪模板%d YOLO%d 血条%d (ms/秒)" % (
                    _dt_rounds, "忙" if _busy else "闲",
                    _dt_grab * 1000, _dt_char * 1000, _dt_feat * 1000, _dt_yolo * 1000, _dt_bars * 1000)
                print(_msg)
                _debug_log(_msg)
                _dt_grab = _dt_char = _dt_feat = _dt_yolo = _dt_bars = 0.0
                _dt_rounds = 0
                _dt_last_report = _dt_now
            if _elapse < _period:
                time.sleep((_period - _elapse) / 1000.0)

    def _start_detection_thread(self):
        if self._detect_thread and self._detect_thread.is_alive():
            return
        self._detect_running = True
        self._detect_thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._detect_thread.start()
        self._start_move_watchdog()  # 移动监管线(独立线程,v1只监测打日志)
        print("[检测线程] 已启动(同一帧检人物+怪)")

    def _stop_detection_thread(self):
        self._detect_running = False
        if self._detect_thread and self._detect_thread.is_alive():
            self._detect_thread.join(timeout=1.0)
        self._stop_move_watchdog()  # 一并停移动监管线

    def _combat_tick(self):
        """人性化战斗：反应延迟→转身→走位→攻击，群攻3只起，带随机容错"""
        if not self._running or self.hwnd is None:
            return
        now = time.time() * 1000
        fight_cfg = self._get_fight_config()
        pot_cfg = self._get_potion_config()
        # === 拟人周期小休（用户确认保留）：5~8分钟随机休息10~15秒（挂机像人偶尔离座）；爬梯/跨层中顺延1~3分钟 ===
        if getattr(self, '_rest_next_at', 0) == 0:
            self._rest_next_at = now + random.randint(300000, 480000)  # 5~8分钟
        if getattr(self, '_aux_enable_rest', True) and now < getattr(self, '_rest_until', 0):
            self._release_combat_move()
            self._release_all_keys()
            return
        if getattr(self, '_aux_enable_rest', True) and now >= self._rest_next_at:
            if self._climb_state != "none" or self._combat_transit:
                self._rest_next_at = now + random.randint(60000, 180000)  # 爬梯中：顺延1~3分钟
            else:
                self._rest_until = now + random.randint(5000, 10000)  # 休息5~10秒
                self._rest_next_at = now + random.randint(300000, 480000)  # 下轮5~8分钟
                self._combat_locked_target = None
                self._combat_had_target = False
                self._release_combat_move()
                self._release_all_keys()
                print("[拟人] 休息%.1f秒（下轮约%.0f分钟后）" % (
                    (self._rest_until - now) / 1000.0, (self._rest_next_at - now) / 60000.0))
                return

        # === 【模块B】手动录制平台边界检测 + 回退（拟人化2026-09-07）===
        # 人物到了平台边缘触发回退：随机回退15~28%、先松键借惯性滑、回退中偶尔顿/小跳
        # 【用户2026-09-09定稿】平台边界回退只在"勾选了单个/几个台子"(锁平台打)时才生效；
        # 全图/全屏模式(_selected_platforms为空)永不回退——全屏打时回退会抢锁怪打怪主线。
        # 不另起真线程(会和主线抢方向键,正是之前抖键根因)，用条件门控在主线内串行，等效且不抢键。
        # _aux_enable_retreat=排查期总开关(默认关)。
        if getattr(self, '_aux_enable_retreat', True) and getattr(self, '_selected_platforms', None):
            boundary_dir = self._check_platform_boundary()
        else:
            self._platform_retreat_active = False
            boundary_dir = None
        if boundary_dir and not getattr(self, '_platform_retreat_active', False):
            # 触发回退：计算回退目标（拟人：随机15~28%，不固定20%）
            pf = self._get_current_manual_platform()
            if pf and self._player_map_pos:
                x_min, x_max = self._platform_x_range(pf)
                platform_width = x_max - x_min
                retreat_dist = platform_width * random.uniform(0.15, 0.28)
                px = self._player_map_pos[0]
                if boundary_dir == 'right':
                    self._platform_retreat_target_x = px + retreat_dist
                    self._platform_retreat_dir = 'right'
                else:
                    self._platform_retreat_target_x = px - retreat_dist
                    self._platform_retreat_dir = 'left'
                self._platform_retreat_active = True
                self._platform_retreat_slide_until = now + random.randint(100, 200)  # 先松键借惯性滑一点点
                self._platform_retreat_pause_until = 0   # 回退中偶尔顿一下的截止时间
                self._platform_retreat_next_jump = now + random.randint(800, 1500)  # 下次小跳时间
                self._release_combat_move()  # 释放当前移动键（借惯性滑，不是像素级急停）
                _debug_log("[平台边界] 触发回退 方向=%s 目标X=%.1f 回退距离=%.1f(%.0f%%)" % (
                    boundary_dir, self._platform_retreat_target_x, retreat_dist, retreat_dist / platform_width * 100))
        # 回退过程中：按住方向键往回走，不攻击（拟人：滑→走→偶尔顿/小跳）
        if getattr(self, '_aux_enable_retreat', True) and getattr(self, '_selected_platforms', None) and getattr(self, '_platform_retreat_active', False) and self._player_map_pos:
            px = self._player_map_pos[0]
            target = self._platform_retreat_target_x
            rdir = self._platform_retreat_dir
            reached = (rdir == 'right' and px >= target) or (rdir == 'left' and px <= target)
            if reached:
                self._platform_retreat_active = False
                self._release_combat_move()
                _debug_log("[平台边界] 回退完成 到达X=%.1f" % px)
            elif now < getattr(self, '_platform_retreat_slide_until', 0):
                return  # 拟人：先松键借惯性滑一点点，不按方向键
            elif now < getattr(self, '_platform_retreat_pause_until', 0):
                self._release_combat_move()
                return  # 拟人：回退中偶尔顿一下（像人调整站位）
            else:
                self._set_combat_move(rdir)
                # 拟人：回退中偶尔带个小跳（像人在调整站位）
                if now >= getattr(self, '_platform_retreat_next_jump', 0):
                    _jump_key = fight_cfg.get("jump_key", "")
                    if _jump_key:
                        self._press_game_key(_jump_key, duration=80)
                    self._platform_retreat_next_jump = now + random.randint(1200, 2500)
                # 拟人：2%概率触发下一次停顿（0.1~0.25秒）
                if random.random() < 0.02:
                    self._platform_retreat_pause_until = now + random.randint(100, 250)
                return  # 回退过程中不攻击，直接返回

        # === 释放到期的定时按键（走位用，不阻塞主循环）===
        if self._combat_timed_keys:
            _rem = []
            for _vk, _rel in self._combat_timed_keys:
                if now >= _rel:
                    # 松开用 keybd_event(扫描码)，与发键一致——【冒险岛世界】吃keybd_event(怀旧服才只认SendInput)
                    self._send_win_key(_vk, keyup=True)
                else:
                    _rem.append((_vk, _rel))
            self._combat_timed_keys = _rem

        # === 人物/怪/YOLO/血条 已由后台检测线程同一帧算好，主循环过滤进 self._monsters / self._player_screen_pos ===
        # 这里主线程不再做检测重活，只保留镜头死区(右键拖动检测框) + 人物定位日志 + 怪物计数日志
        _rb_down = bool(user32.GetAsyncKeyState(0x02) & 0x8000)  # VK_RBUTTON
        if _rb_down and not self._last_rbutton_down:
            # 右键刚按下：取光标位置转游戏窗口客户区坐标
            _cursor = POINT()
            user32.GetCursorPos(ctypes.byref(_cursor))
            if self.window_rect:
                _cx = _cursor.x - self.window_rect['left']
                _cy = _cursor.y - self.window_rect['top']
            else:
                _cx, _cy = _cursor.x, _cursor.y
            if self._bg_dragging >= 0:
                # 正在移动模式：再次右键=保存并退出
                self._save_bg_regions()
                _di = self._bg_dragging
                _debug_log("[镜头检测] 保存检测框%d位置(%d,%d)，退出移动模式" % (
                    _di + 1, self._bg_regions[_di]["x"], self._bg_regions[_di]["y"]))
                self._bg_dragging = -1
            else:
                # 没在移动模式：检查右键是否点在某个检测框内
                for _ri, _rr in enumerate(self._bg_regions):
                    if _rr["x"] <= _cx <= _rr["x"] + _rr["w"] and _rr["y"] <= _cy <= _rr["y"] + _rr["h"]:
                        self._bg_dragging = _ri
                        _debug_log("[镜头检测] 进入检测框%d移动模式，再次右键保存" % (_ri + 1))
                        break
        self._last_rbutton_down = _rb_down
        # 移动模式下：检测框跟随光标（以光标为中心）
        if self._bg_dragging >= 0:
            _cursor2 = POINT()
            user32.GetCursorPos(ctypes.byref(_cursor2))
            if self.window_rect:
                _mx = _cursor2.x - self.window_rect['left']
                _my = _cursor2.y - self.window_rect['top']
            else:
                _mx, _my = _cursor2.x, _cursor2.y
            _db = self._bg_regions[self._bg_dragging]
            _db["x"] = max(0, _mx - _db["w"] // 2)
            _db["y"] = max(0, _my - _db["h"] // 2)
        _has_pos = self._player_screen_pos is not None
        if _has_pos != getattr(self, '_last_player_pos_ok', None):
            self._last_player_pos_ok = _has_pos
            if _has_pos:
                _debug_log("[人物定位] 成功，黄点位置: %s" % (self._player_screen_pos,))
            else:
                _debug_log("[人物定位] 丢失，黄点隐藏")
        _mc = len(self._monsters)
        if _mc > 0 and _mc != getattr(self, "_last_logged_mc", -1):
            self._rlog("发现怪物%d只" % _mc, (0, 100, 200))
            self._last_logged_mc = _mc
        elif _mc == 0:
            if getattr(self, '_last_logged_mc', 0) and self._last_logged_mc > 0:
                self._rlog("当前画面无怪物", (150, 150, 150))
            self._last_logged_mc = 0

        # === 反应延迟 / 转身 锁定（后摇锁已去掉，连续攻击）===
        if now < self._combat_react_until:
            return
        if now < self._combat_turn_until:
            return
        if now < self._combat_busy_until:
            return

        # 【用户2026-09-08】爬梯不是单独的线，是找怪→锁定→移动→打怪这条线内的一部分（移动方式包括走路/跳/爬梯/下跳）
        # 不在这里单独拦截跨层，让找怪逻辑正常执行，state=cross时自然走跨层移动，爬梯在_move_to内部处理
        # 之前改成"跨层就return不找怪"=另起一条线，弄错了

        # === 不过滤怪物：保留所有检测到的怪，目标选择时同平台优先 ===
        current_platform = self._get_current_platform()
        has_target = bool(self._monsters and self._player_screen_pos)

        # === 战斗诊断（每2秒打一次，定位"为什么不打怪"）===
        if not hasattr(self, '_combat_diag_last') or now - self._combat_diag_last > 2000:
            self._combat_diag_last = now
            _debug_log("[战斗诊断] 运行=%s 人物=%s 怪数=%d has_target=%s "
                       "react余=%dms turn余=%dms busy余=%dms 锁定=%s 怪物匹配=%d套" % (
                self._running, self._player_screen_pos, len(self._monsters), has_target,
                int(self._combat_react_until - now), int(self._combat_turn_until - now),
                int(self._combat_busy_until - now), self._combat_locked_target,
                len(getattr(self, '_monster_templates', []))))

        # === 完全无目标（一只怪都没检测到）：松开移动，由路线系统接管 ===
        if not has_target:
            # 【冻结锁漏口修复·用户2026-09-09】抓梯/爬梯/下跳中检测线程漏一帧怪很常见,旧代码在此直接把锁定清成None,
            # 下帧重锁就可能锁到别的层(表现:人继续往上爬、目标却换成下层怪=两套意图打架中途停)。冻结中保留最后锁定,沿原目标继续跨层。
            if self._is_lock_frozen():
                if self._combat_transit:
                    self._transit_step()
                return
            self._combat_had_target = False
            self._combat_target_idx = 0
            self._combat_last_target_pos = None
            self._combat_locked_target = None
            # 【模块A】无怪时重置所有战斗状态，恢复巡路
            self._combat_active = False          # 取消战斗活跃，巡路恢复移动
            self._release_attack_key()           # 没怪就松开攻击键
            self._combat_range_clear = False     # 退出范围清怪模式
            self._combat_target_lock_x = None    # 清除锁定X基准
            self._combat_target_alive = False    # 清除存活状态
            # 跨层行进中：感知不到怪也继续走向目标平台（_move_to自动跳/瞬移/爬梯）
            if self._combat_transit:
                self._transit_step()
            self._shadow_combat_decision()   # Phase A影子日志：无怪时看新决策(idle/cross)
            self._release_combat_move()
            return

        # === 有目标（当前平台上有怪）===
        px, py = self._player_screen_pos
        self._shadow_combat_decision()   # Phase A影子日志：有怪时看新决策(pursue/cast/switch)

        # 首次发现目标：反应延迟
        if not self._combat_had_target:
            self._combat_had_target = True
            self._combat_react_until = now + random.randint(80, 250)
            return

        # 【冒险岛世界2026-09-07清理】旧"手写分边探测(monster_dists/cross_candidates/probe_side排序)+跨层中遇怪取消"
        # 整段已删除：选目标/分层/跨层/取消跨层全部由下方 combat_step 统一决策（其结果 _dl['state'] 在后面处理跨层取消），
        # 旧段构建后无任何消费者(A2后群攻也改数self._monsters)，属死代码。

        # === 用已验证的决策核心 combat_step 选目标/方向/存活（同平台优先 + 跨平台/cross/idle 一次搞定）===
        # 静态/空怪过滤已由主循环在做，这里直接用主循环过滤后的 self._monsters
        skill_range = int(fight_cfg.get("atk1_distance", 150) or 150)
        aoe_range = int(fight_cfg.get("aoe_distance", 200) or 200)
        _atk_y_up = abs(int(fight_cfg.get("attack_y_up", -ATTACK_Y_UP)))       # 主攻·上方框有向值(负,默认-60)→abs成上方容差
        _atk_y_down = abs(int(fight_cfg.get("attack_y_down", ATTACK_Y_DOWN)))  # 主攻·下方框有向值(正,默认+30)→abs成下方容差
        _aoe_y_up = abs(int(fight_cfg.get("aoe_y_up", -AOE_Y_UP)))             # 群攻·上方容差(默认与主攻一致,用户2026-09-07)
        _aoe_y_down = abs(int(fight_cfg.get("aoe_y_down", AOE_Y_DOWN)))        # 群攻·下方容差
        # 跳高打区间(用户2026-09-09，"技能Y范围"弹窗最下一行两个框自定义)：以人物为基准、向上为负(照抄主攻"上方范围"输入习惯)，
        # 框里填负数，这里abs归一化成正高度；下限/上限都填才启用，任一留空=None=不启用
        _sj_min_v = fight_cfg.get("slope_jump_y_min")
        _sj_max_v = fight_cfg.get("slope_jump_y_max")
        _sj_min = abs(int(_sj_min_v)) if _sj_min_v is not None else None
        _sj_max = abs(int(_sj_max_v)) if _sj_max_v is not None else None
        _slope_on = (_sj_min is not None and _sj_max is not None and _sj_max >= _sj_min)
        # 当前锁定目标若跳打已打空(出手无血条无伤害=当前位置够不着)→本次降级：上方分界收回到攻击Y范围，让它落cross走梯子/瞬移；换目标清除
        _slope_blocked = getattr(self, '_slope_high_blocked', False)
        # 上方"可锁定/可接近"分界：启用且未降级=用户上限(区间内走高跳打、不找梯子)；否则=_atk_y_up(旧行为：超出攻击Y范围就cross走梯子)
        _eff_up_band = _sj_max if (_slope_on and not _slope_blocked) else _atk_y_up
        _far_x = max(50, int(fight_cfg.get("far_range_x", COMBAT_FAR_RANGE) or COMBAT_FAR_RANGE))   # 寻怪X(左右各,默认1300)
        _far_y_up = max(10, int(fight_cfg.get("far_range_y_up", FAR_RANGE_Y_UP_DEFAULT) or FAR_RANGE_Y_UP_DEFAULT))   # 寻怪Y上方容差
        _far_y_down = max(10, int(fight_cfg.get("far_range_y_down", FAR_RANGE_Y_DOWN_DEFAULT) or FAR_RANGE_Y_DOWN_DEFAULT)) # 寻怪Y下方容差
        self._far_range_y_up = _far_y_up
        self._far_range_y_down = _far_y_down
        _lock_p = self._combat_locked_target
        _lcx, _lcy = (_lock_p if _lock_p else (None, None))
        # 伤害数字只在"技能射程+Y范围内"的锁定目标上检测（用户2026-09-07：识别范围以技能范围为主）；
        # 超射程(pursue还没走近)不判空怪、也省一次抓帧
        _in_skill = bool(_lock_p) and abs(_lcx - px) <= skill_range and -_atk_y_up <= (_lcy - py) <= _atk_y_down
        _has_dmg = _in_skill and self._detect_damage_number(_lcx, _lcy)
        # 空怪/打死判定：已出手 且 距【首次】出手超过 POST_STRIKE_CHECK_MS(130ms)反馈窗口(用户2026-09-07：250→130,更快判死换怪)。
        # 关键保护：血条/伤害都来自检测线程帧,必须已拿到一帧"出手时刻之后"的新画面(_raw_frame_t≥首次出手)才判,
        # 否则130ms时用的还是出手前旧帧→会把真怪误判成空怪丢掉。没等到新帧就再等一轮,绝不拿旧帧下结论。
        _fs = getattr(self, '_combat_first_strike_time', 0)
        _post_frame = (not _fs) or (getattr(self, '_raw_frame_t', 0) * 1000 >= _fs)
        _attacked = getattr(self, '_combat_target_attacked', False) and _post_frame \
            and (not _fs or now - _fs > POST_STRIKE_CHECK_MS)
        # 诊断：每只怪的 X/Y差 和是否同平台、能否直打（治"空打/反方向/错位打上层"）——每1秒一次
        if not hasattr(self, '_mon_cls_last') or now - self._mon_cls_last > 1000:
            self._mon_cls_last = now
            _mstrs = []
            for (_mx1, _my1, _mx2, _my2, _msco) in self._monsters:
                _mcx = (_mx1 + _mx2) // 2
                _mcy = _my2
                _dy = _mcy - py  # 怪脚Y - 人物Y（负=怪在上,正=怪在下）
                _yok = (-_atk_y_up <= _dy <= _atk_y_down)
                _xok = abs(_mcx - px) <= skill_range
                _sameplt = self._is_monster_on_platform(_mcx, _mcy)
                _mstrs.append("(%d,%d)X差%d Y差%d 同平台=%s 直打=%s" % (
                    _mcx, _mcy, abs(_mcx - px), abs(_mcy - py), _sameplt,
                    ("可" if (_yok and _xok and _sameplt) else "不可")))
            _debug_log("[怪分类] 人物=(%d,%d) 怪数=%d → %s" % (px, py, len(self._monsters), " | ".join(_mstrs)))
        # 锁怪冻结(用户2026-09-09)：已进入爬梯/上下跳/瞬移动作就不换锁——中途有怪进技能范围也不替换,
        # 等上/下到位(_climb_state回none)后下一帧重新识别时才解绑重锁；平地走向梯子那段(_climb_state=none)不冻,仍允许近身怪优先。
        # 【2026-09-09修复"一上去就下来"】独占判据只看_climb_state!=none,不再and _combat_transit:
        # 边界帧transit可能还没置位/已被取消分支清掉,旧写法此刻漏冻→锁到活着=False死怪/近身怪,决策抖成cast抢发攻击键把人从梯上弄下来。
        _freeze_lock = self._is_lock_frozen()  # 硬信号:跳起抓梯(post_jump)/爬梯/下跳/瞬移才冻;平地走向梯子(to_ladder未跳)不冻可换怪
        _dl = combat_logic.combat_step(
            now, px, py, self._monsters, self._selected_platforms, skill_range, aoe_range,
            _far_x, self._combat_locked_target, self._monster_hp_bars, _has_dmg,
            True, True, self._probe_side, self._probe_switched,
            self._is_monster_on_platform, self._get_monster_platform,
            self._combat_target_lock_time,
            self._combat_target_hp_confirmed, self._combat_gone_frames, self._transit_target, _attacked,
            # 【用户2026-09-09】上方"可锁定/可接近"分界=_eff_up_band：启用跳高打=用户上限(区间内进cand走高跳打、不找梯子，
            # 超上限落cross走梯子/瞬移)；未启用或当前目标跳打打空降级=_atk_y_up(旧行为)。主攻真出手仍由本地_atk_y_up门控(跳到够得着才打)。
            _eff_up_band, _atk_y_down, True, freeze_lock=_freeze_lock,
            group_priority=bool(fight_cfg.get("group_priority")), group_radius=aoe_range,
            # 群怪优先圈群唯一判据=群攻X射程(aoe_range)+群攻Y范围；aoe_dual=双向近身技能(站怪群中心,两侧同时出伤害)
            aoe_y_up=_aoe_y_up, aoe_y_down=_aoe_y_down, aoe_dual=bool(fight_cfg.get("aoe_dual")))
        self._combat_target_hp_confirmed = _dl['hp_confirmed']
        self._combat_gone_frames = _dl['gone_frames']
        self._combat_target_alive = _dl['alive']
        # 战斗状态切换才上屏一条(用户2026-09-09:每个状态一条不刷屏)；cross跨层交给行为日志报,这里不重复
        _cstate_map = {'cast': "正在打怪(射程内,持续攻击)", 'pursue': "正在找怪/靠近(射程外,走向目标)",
                       'switch': "切换锁定目标", 'idle': "无目标,待机找怪中"}
        _cs_now = _dl['state']
        if _cs_now != getattr(self, '_last_combat_state', None):
            if _cs_now in _cstate_map:
                self._rlog(_cstate_map[_cs_now])
            self._last_combat_state = _cs_now
        # 打怪决策日志(用户2026-09-05要求)：锁定怪/X差/Y差/超阈值先移动还是范围内直接打——每0.6秒1次
        if not hasattr(self, '_combat_dlog_last') or now - self._combat_dlog_last > 600:
            self._combat_dlog_last = now
            _tg = _dl['target']
            if _tg:
                if _dl['state'] == "cast":
                    _act = "在射程内直接打"
                elif _dl['state'] == "pursue":
                    _act = "超射程先移动再打"
                else:
                    _act = _dl['state']
                _debug_log("[打怪决策] 状态=%s 锁定=%s 目标=(%d,%d) 人物=(%d,%d) X差=%d Y差=%d 距离=%s 判定=%s" % (
                    _dl['state'], self._combat_locked_target, _tg[0], _tg[1], px, py,
                    abs(_tg[0] - px), abs(_tg[1] - py), _dl['dist'], _act))
            else:
                _debug_log("[打怪决策] 状态=%s 无目标(候选空/全不在平台/全超Y范围) 人物=(%d,%d)" % (
                    _dl['state'], px, py))
        # 空怪诊断：看真机上 drop 为什么不触发(治空打不停)——每1秒
        if not hasattr(self, '_kong_last') or now - self._kong_last > 1000:
            self._kong_last = now
            _debug_log("[空怪诊断] 状态=%s 锁定=%s 活着=%s drop=%s 伤害=%s 已出手=%s 确认血=%s gone=%d 血条数=%d" % (
                _dl['state'], self._combat_locked_target, _dl['alive'], _dl['drop'],
                _has_dmg, _attacked, self._combat_target_hp_confirmed, self._combat_gone_frames,
                len(self._monster_hp_bars)))
        # 距离诊断(每1秒)：面板skill_range vs 实际目标距离，看是否同步/人物XY是否算错
        if not hasattr(self, '_dist_diag_last') or now - self._dist_diag_last > 1000:
            self._dist_diag_last = now
            _debug_log("[距离] skill_range=%d 状态=%s 目标=%s 距离=%s 人物=(%s,%s)" % (
                skill_range, _dl['state'], _dl['target'], _dl['dist'], px, py))

        # 【巡路优先·一条线原则(用户2026-09-09)】流程严格按 识别→锁怪→巡路(走/跳/瞬移/上下梯)→打怪 串行循环：
        # 只要已进入攀爬动作(_climb_state!=none：抓梯/爬梯/上下跳/瞬移)，这一帧不管决策成cast/pursue还是cross，
        # 都先把巡路走完(到顶_reset_climb回none)，绝不在梯子上中途切去打怪，否则松↑/按跳会把人从梯上弄下来。
        # 【2026-09-09修复】独占只看_climb_state!=none,不再要求_combat_transit(旧条件在transit被取消分支清零后失效→爬梯中仍发攻击键)。
        # 跨层行进由_transit_step持续驱动_move_to(持续按↑到顶)；非跨层爬梯(掉台归位/随机)由各自tick驱动,这里只松攻击、不碰移动键,return不抢动作。
        if getattr(self, '_climb_state', 'none') != 'none':
            self._release_attack_key()
            if self._combat_transit:
                self._transit_step()
            return

        # 【用户2026-09-08】没有上梯子时，先选下面的怪打，打完再上梯子
        # 跨层行进中遇到同层可打怪：取消跨层，优先打怪（同层怪优先级高于跨层目标）——仅在"还没开始爬(平地走向梯子,_climb_state=none)"时允许；
        # 已起跳抓梯/爬梯/瞬移(_climb_state!=none)由上面动作独占总闸拦走、根本到不了这,这里再补_climb_state=='none'双保险,
        # 杜绝旧bug:爬梯中决策抖成cast/pursue→在此清_combat_transit并_release_all_keys(连↑一起松)→人从梯子上掉下来钉在梯底(2026-09-09真机定位)
        # 【2026-09-09修复人知道去梯子却不走】只有 state=='cast'(同层怪已进技能范围、马上能打)才中断跨层；
        # 纯 pursue(同层但还在几百px外、且当前锁的常是没出手验证过的远距/死怪)【不打断】跨层。否则cross/pursue逐帧抖:
        # cross帧启动跨层走向梯子,pursue帧又在此清transit+松键,两套移动键高速交替keydown/keyup→人物被抖在原地(dist不减反增),
        # 远距死怪又因走不到、出不了手永远触发不了无血条drop,成死结。真有同层怪走进射程变cast时仍会优先打(保留同层怪优先)。
        if _dl['state'] == 'cast' and self._combat_transit and getattr(self, '_climb_state', 'none') == 'none':
            self._combat_transit = False
            self._transit_target = None
            self._release_all_keys()
        elif _dl['state'] == 'pursue' and self._combat_transit and getattr(self, '_climb_state', 'none') == 'none':
            # 跨层巡路中遇到"同层但超射程"的怪(pursue)：不打断跨层、也不许走下面的追怪移动去按战斗方向键抢动作,
            # 只持续推进跨层走向梯子(攀爬态_climb_state!=none已由上面动作独占总闸处理,这里补平地空档帧),治cross/pursue抖键原地不走。
            self._release_combat_move()
            self._transit_step()
            return

        if _dl['state'] in ('cast', 'pursue') and _dl['target']:
            # 有同平台怪：锁定它，方向由下方面向/移动逻辑按 target 计算
            # 战斗活跃：技能范围内有怪，暂停巡路移动，专心打怪（否则人物被巡路带着走、攻击被移动拦住）
            self._combat_active = True
            t_cx, t_cy = _dl['target']
            target = (_dl['dist'], t_cx, t_cy)
            # 是否"真的换了目标"：用与select维持锁定一致的容差(±40X/±50Y)。
            # 旧代码用精确坐标相等，可怪检测框每帧抖几px→每帧误判换新目标→首次出手计时/已出手标记反复清零，
            # 130ms空怪判定永远攒不够,空怪一直打不停(用户2026-09-07)。同一只怪抖动不再重置。
            _oldlk = self._combat_locked_target
            _is_new_target = (_oldlk is None) or (abs(_oldlk[0]-t_cx) > 40 or abs(_oldlk[1]-t_cy) > 50)
            if _is_new_target:
                self._combat_target_attacked = False  # 换了新目标：重置"已出手"标记（空怪判定用）
                self._combat_first_strike_time = 0    # 换新目标：首次出手计时清零，重新给反馈窗口
                self._combat_target_lock_time = now     # 重置锁定基准时间
                self._combat_target_lock_x = t_cx       # 重置1秒X无变化基准
                self._combat_target_hp_confirmed = False
                self._slope_high_blocked = False        # 换新目标：清除"上一只跳打打空"降级，新目标重新按用户区间判定
                self._slope_high_mode = False
                self._slope_next_jump = 0
                self._slope_jump_t = 0
                self._slope_jump_hit = False
                self._slope_hit_window = False
                # 上屏(用户2026-09-09要看日志滚动)：锁定/换锁瞬间报目标相对位置，Y差正=怪在人物上方
                self._rlog("锁定怪 X差%+d Y差%+d(正=在上) 距离%d [%s]" % (
                    t_cx - px, py - t_cy, int(_dl.get('dist', 0) or 0), _dl['state']))
                # 群怪优先选簇/换簇上屏(只在换新目标瞬间打一条,不刷屏)：双向=站怪群中心;单向=打多的一侧
                _grp = _dl.get('group')
                if _grp:
                    _g_n, _g_tag = _grp
                    if _g_tag == 'dual':
                        _g_desc = "双向·站怪群中心(共%d只,两侧同时打)" % _g_n
                    elif _g_tag in ('left', 'right'):
                        _g_desc = "单向·先打%s侧怪群(%d只,这侧清空再换边)" % ("左" if _g_tag == 'left' else "右", _g_n)
                    else:
                        _g_desc = "锁怪群%d只" % _g_n
                    self._rlog("群怪优先·%s [%s]" % (_g_desc, _dl['state']))
            self._combat_locked_target = (t_cx, t_cy)
            self._combat_last_target_pos = (t_cx, t_cy)
            # A2修复：不再把monster_dists覆盖成只剩锁定目标(原覆盖导致下方群攻永远数不到3只、群攻放不出)；群攻计数改为直接数self._monsters
            if _dl['drop']:
                # 真怪已死/假怪/打空：放弃锁定，重选
                if getattr(self, '_slope_high_mode', False):
                    # 【跳高打打空·用户2026-09-09】高坡走-跳-打出手一次仍无血条无伤害=当前位置够不着这只上层怪。
                    # 它是真怪、只是要换层：不做位置拉黑(否则走梯子也没目标)，只置降级标记→下帧上方分界收回到攻击Y范围、
                    # 让它落 cross 走梯子/瞬移上去打（对接正常跨层流程）。
                    self._slope_high_blocked = True
                    self._slope_high_mode = False
                    _debug_log("[跳高打] 出手无血条无伤害=当前位置够不着，放弃跳打改走梯子/瞬移 目标(%d,%d)" % (t_cx, t_cy))
                    self._rlog("跳高打打空:无血条无伤害=这位置够不着(怪在上%dpx),改走梯子/瞬移" % (py - t_cy), LOG_RED)
                else:
                    # 普通空怪(假怪/刚打死)：记录位置，短时间不再重锁（防空怪"drop后又选同一只"死循环空打）
                    self._combat_dropped_phantoms.append((t_cx, t_cy, now))
                    self._rlog("怪无血条/无伤害(已死或假怪,在上%+dpx),放弃并重新锁怪" % (py - t_cy), LOG_RED)
                self._combat_locked_target = None
                self._combat_target_alive = False
                self._combat_target_attacked = False  # 放弃后重置"已出手"，避免下帧误判同一空怪
                self._combat_first_strike_time = 0    # 放弃后清零首次出手计时
                # 怪死瞬间强制下一检测周期立刻全图YOLO+血条(不等节流间隔)，打完一只秒锁下一只(用户2026-09-07换锁慢)
                self._yolo_last_t = 0.0
                self._bars_last_t = 0.0
                self._release_attack_key()             # 空怪放弃时松开攻击键，别一直按住打空气
                self._release_combat_move()
                return
        elif _dl['state'] == 'cross':
            # 同平台无怪，去跨平台：由 _try_platform_transition 做屏幕→小地图转换 + 走/梯规划
            # （cross候选里的怪只是"引路灯"，到新平台后立即重新选怪，不持久锁定）
            self._combat_active = False
            self._release_attack_key()
            # 到顶重识别保护期(用户2026-09-09)：刚翻上/下平台0.5s内,旧帧可能把梯子上测的旧怪(在下方)判成cross把人又拉下去
            # ("一上去就下来")。此窗口内不锁框、不打跨层日志、不选梯子,站定等全图重扫出新本层怪;保护期一过恢复正常。
            if now < getattr(self, '_arrival_relock_until', 0):
                self._release_combat_move()
                return
            # 【用户2026-09-08】跨层时也要显示红色锁框（锁定上层怪），让用户看到"锁怪→找平台→找梯子"三步走；
            # 不设None(否则无锁框，用户以为没锁定怪不会跳)。到新平台后combat_logic会自动重选。
            if _dl['target']:
                self._combat_locked_target = _dl['target']
                self._combat_last_target_pos = _dl['target']
                _ccx, _ccy = _dl['target']
                # 上屏(用户2026-09-09)：本层够不着→报目标在上/下多少px、需要跨层；限频700ms防刷
                self._rlog_throttle('cross_need', "本层无够得着的怪,目标在%s%dpx(X差%+d),需走梯子/瞬移跨层" % (
                    "上方" if _ccy < py else "下方", abs(py - _ccy), _ccx - px), 1500, log='behavior')
            # 原地直跳连续2次抓不住梯子的退开(用户2026-09-09)：本层无怪(cross)时先朝外侧退120~150px,
            # 退够前不选梯子；本层有怪时上面cast/pursue已先打怪、不会进cross,天然"打完怪再自动上梯"
            if self._ladder_backoff is not None and self._ladder_backoff_step(now):
                return
            if self._combat_transit:
                # 已经在跨层行进中：继续行进，不重新规划（避免每帧重置_transit_via/walk_path导致移动一顿一顿）
                self._transit_step()
                return
            # 启动新的跨层行进
            # 【用户2026-09-08删除】删掉"50%先走到同平台远端打一波再跨层"的随机二选一(_try_farm_same_platform)：
            # 锁定上层/坡上怪后必须直接找梯子/路径上去，不能在同平台绕圈、跟着头上的怪水平走
            _cross_cands = _dl.get('cross_candidates', [])
            if self._try_platform_transition(_cross_cands, now):
                self._transit_step()   # 启动跨层行进
            else:
                self._release_combat_move()   # 没有可去目标：松手等刷怪
            return
        elif _dl['state'] == 'switch':
            # 本边没怪，换另一边探测
            self._combat_active = False
            self._release_attack_key()
            self._probe_side = -self._probe_side
            self._probe_switched = True
            self._release_combat_move()
            self._combat_locked_target = None
            return
        else:
            # idle：无任何可打目标，恢复巡路
            self._combat_active = False
            self._combat_had_target = False
            self._release_attack_key()
            self._combat_locked_target = None
            self._combat_target_alive = False
            if self._combat_transit:
                self._transit_step()
            self._release_combat_move()
            return

        t_dist, t_cx, t_cy = target
        # 更新锁定位置（怪会移动）
        self._combat_locked_target = (t_cx, t_cy)
        # 记录目标位置，用于下一轮血条搜索
        self._combat_last_target_pos = (t_cx, t_cy)

        # === 存活/空怪 已由 combat_step 处理（血条OR伤害=活；打一下都无=空怪drop）===
        # 不再在这里重复检测血条/伤害，避免重复截图+与combat_step冲突

        # 面向判断：怪在右按右键，怪在左按左键。
        # 【用户2026-09-08】追怪(范围外)时不转身，一直按住方向键连续走；进入攻击范围后才松方向键→决定要不要转向→攻击
        needed_facing = 1 if t_cx > px else -1
        atk_dist = fight_cfg.get("atk1_distance", 150)
        in_attack_range = t_dist <= atk_dist
        if in_attack_range and getattr(self, '_combat_last_face_dir', None) != needed_facing:
            # 先松开攻击再转身（用户2026-09-07）：
            # ①松攻击键，避免角色锁在攻击/技能后摇动画里转不动；
            # ②必须松开所有持续按住的移动方向键——追怪时旧方向键是一直按住的，不松就按反方向=左右相抵，人物僵住转不过身（这是"转不了身"的根因）
            # 【用户2026-09-08】先松开方向键再转身：_combat_held_keys + _random_move_keys里的左右都松开，加50ms延时确保旧方向完全松开，再按新方向
            self._release_attack_key()
            self._release_combat_move()
            for _tvk in (VK_LEFT, VK_RIGHT):
                if _tvk in self._random_move_keys:
                    self._key_up(_tvk)
            time.sleep(0.05)  # 50ms确保旧方向键完全松开，避免左右相抵转不动
            _vk = 0x27 if needed_facing > 0 else 0x25
            # 按住新方向键 120~150ms(随机,拟人)，由 _combat_timed_keys 到期自动松开（用户2026-09-07定稿：先松旧方向→按新方向120-150ms）；
            # 【冒险岛世界】发/松都用 keybd_event 扫描码(实测吃这个；SendInput单独发不动，与怀旧服DirectInput相反)
            _turn_hold = random.randint(120, 150)
            self._send_win_key(_vk, keyup=False)
            self._combat_timed_keys.append((_vk, now + _turn_hold))  # 新方向按住120-150ms后自动松开
            # 记录这次朝向：下一只怪若仍在同一方向，_combat_last_face_dir==needed_facing 就不再转身(用户2026-09-07)
            self._combat_last_face_dir = needed_facing
            self._combat_facing = needed_facing
            # 【用户2026-09-09】删掉"转身后再等50ms才攻击"——转完当帧即可出手,不额外停手;
            # 注意保留上面12596的松旧方向键sleep0.05(那是防左右键相抵转不动,与此等待无关)
            self._combat_turn_until = 0
            _debug_log("[面向] 怪在%s 按%s方向键(hold%dms,先松旧方向+50ms延时,转身后等50ms) 目标X=%d 人物X=%d" % (
                "右" if needed_facing > 0 else "左", "右" if needed_facing > 0 else "左", _turn_hold, t_cx, px))
            return
        # 上轮刚转身：等转身动画结束再打，避免转身瞬间就出手打反方向
        if now < self._combat_turn_until:
            return

        # === 跳高打（怪比人高）：区间[下限,上限]由弹窗自定义、X差在技能射程内才走-跳-打，每500~600ms跳一次；超上限由combat_step判cross走梯子 ===
        jump_key = fight_cfg.get("jump_key", "")

        # === 远处怪朝怪移动靠近 ===
        atk_dist = fight_cfg.get("atk1_distance", 150)
        effective_range = atk_dist  # 以面板技能距离为主，走近/施放同一判据，消除(150,200]死区
        if t_dist > effective_range:
            move_dir = "right" if t_cx > px else "left"
            # 平台硬边界(用户2026-09-07锁单平台)：勾了平台就按勾选绿线X范围,到边缘停住不走下去(半空/斜坡也稳)；没勾按当前所在平台
            if self._combat_at_locked_edge(move_dir):
                self._release_combat_move()
                return
            # 用户2026-09-05：追怪要连续、流利地一直走到技能攻击范围，稳稳按住方向键连续走，不停顿/不一阵一阵
            self._set_combat_move(move_dir)
            # 位移检测：按住方向却没走=卡住→已登记【独占解卡】(主线下帧起暂停,由_unblock_tick向前+跳、连试上限放弃重锁)，本帧停手
            # 【隔离排查】解卡线关闭时不检测/不登记/不停手，纯主线持续行动(用户2026-09-09逐个开关排查抢占)
            if getattr(self, '_aux_enable_unblock', True) and self._check_move_blocked(now, px, move_dir, jump_key):
                return
            # 【用户2026-09-09】射程外追怪段只朝怪正常走、不跳：还没进300px/射程，上坡跳统一放到"进射程后"的高坡分支处理
            # 【瞬移追怪·冒险岛世界2026-09-06】走路找怪距离远时，按住方向键的同时间隔按瞬移键快速贴近；
            # 仅当配了X瞬移距离(>0)+瞬移技能键、水平差距≥一次瞬移距离、且基本同层(Y差≤40,避开高怪跳/垂直瞬移)才用；都不填=纯走路
            _tp_key = fight_cfg.get("teleport_key", "")
            _tp_x = int(fight_cfg.get("teleport_distance", 0) or 0)
            if (_tp_key and _tp_x > 0 and t_dist >= _tp_x and t_dist >= 300 and abs(t_cy - py) <= 40
                    and now - self._combat_last_h_teleport > 850
                    and self._climb_state == 'none'):  # 【用户2026-09-08】爬梯流程中不用瞬移+300码以内不用瞬移(太近会跳过目标)
                self._press_game_key(_tp_key, duration=60)
                self._combat_last_h_teleport = now
                # 瞬移后人物合法大跳变：700ms内人物匹配跳过ROI直接全图、允许远距同步(治点钉原地)
                self._char_relocate_until = now + 700
                _debug_log("[瞬移追怪] 方向=%s 水平差=%d≥%d，按瞬移键贴近" % (move_dir, t_dist, _tp_x))
            self._combat_last_move = now
            return

        # 进入攻击范围：立即松开方向键站定（用户2026-09-07：到了范围内立马攻击不要停，
        # 旧逻辑普通平地分支没松方向键→"移动中不发技能"→锁定了也不打/想一会才打）；
        # 高坡/下坡分支需要移动的话会重新_set_combat_move，不受影响。
        # 【用户2026-09-08】强制清空所有移动键状态：_combat_held_keys + _random_move_keys里的左右上下（爬梯残留↑/↓会拦住攻击），确保站定才能打
        self._release_combat_move()
        for _mvk in (VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN):
            if _mvk in self._random_move_keys:
                self._key_up(_mvk)
        # 移动方向带正上方死区：怪几乎在头顶(|X差|≤15)时 move_dir=None，不朝左/右乱走(用户2026-09-07：站坡上锁二层正上方怪,乱走会卡住发呆)，只原地向上跳
        if abs(t_cx - px) <= 15:
            move_dir = None
        else:
            move_dir = "right" if t_cx > px else "left"
        # 跳高打判定(用户2026-09-09)：弹窗"跳高打"下限~上限两个框都填(_slope_on)才启用；
        # 怪比人高落在[_sj_min,_sj_max]且【X差在打怪技能射程(effective_range=atk1_distance)内】才直接"走-跳-打"、不找梯子
        # (用户2026-09-09 X限定：X超出技能射程不跳,战士/法师同一判定)；
        # 任一框留空(_slope_on=False)则high_slope恒False，高怪走正常cross(梯子/瞬移)。保留:有录制平台+非跨层中才跳(防全图/跨层乱跳)。
        _above2 = py - t_cy   # 怪在人物上方多少px(正=怪上方)
        high_slope = bool(_slope_on) and bool(self.platforms) and not getattr(self, '_combat_transit', False) \
            and now >= getattr(self, '_slope_resume_at', 0) \
            and (_sj_min <= _above2 <= _sj_max) and abs(t_cx - px) <= effective_range
        # 下方够不着：怪脚Y-人脚Y 超出下方攻击范围(_atk_y_down,默认30)。用户2026-09-07：下方差100+还站着打=bug,要走下去靠近而不是空打
        _below2 = (t_cy - py) > _atk_y_down
        if not _below2:
            self._release_combat_key(VK_DOWN)  # 不在下方贴近时松开下方向键,避免残留影响走位
            self._below_down_since = 0         # 离开下方状态:清下跳按住计时,下次重新等50ms
        if _below2 and not high_slope:
            if move_dir is not None:
                # 斜下方：朝怪水平方向走,沿斜坡走下/走到平台边缘自动下落；锁平台时到勾选绿线边缘就停(不掉下去)
                if self._combat_at_locked_edge(move_dir):
                    self._release_combat_move()
                    return
                self._set_combat_move(move_dir)
                if getattr(self, '_aux_enable_unblock', True) and self._check_move_blocked(now, px, move_dir, jump_key):  # 卡住→登记独占解卡,本帧停手(连试上限由_unblock_tick放弃重锁)；隔离排查:关解卡线则不登记
                    return
            else:
                # 几乎正下方(|X|≤15)：锁定了平台编号时禁止落层(下层怪不属于勾选平台,本就不该锁;双保险防掉出绿线)；
                # 只有全图模式(没勾平台)才按住下+跳落到下一层
                if self._selected_platforms:
                    self._release_combat_move()
                    self._release_combat_key(VK_DOWN)
                    self._below_down_since = 0
                    return
                self._release_combat_move()
                self._hold_combat_key(VK_DOWN)
                # 【2026-09-09下跳时序】先按住↓≥50ms建立向下状态再按跳(同帧按=普通跳不下落,下跳0成功根因)
                if not getattr(self, '_below_down_since', 0):
                    self._below_down_since = now
                if jump_key and (now - self._below_down_since) >= 50 and now - self._combat_last_jump > 450:
                    self._press_game_key(jump_key, duration=70)
                    self._combat_last_jump = now
                    _debug_log("[下坡] 怪在正下方Y差%d,↓按住≥50ms+跳落层" % (t_cy - py))
            self._combat_last_move = now
            return
        if high_slope:
            # === 跳高打(用户2026-09-09)：每500~600ms跳一次朝怪推进；打不到(无血条无伤害)由空怪drop置blocked走梯子/瞬移 ===
            # 战士模式(不勾法师)：空中能放技能 → 跳后250ms~落地=空中跳打窗口,窗口内带方向在空中主攻
            # 法师模式(勾法师)：空中放不出技能 → 跳后落地站定200ms=跳打窗口,窗口内松方向站定主攻；走-跳-落地放循环,靠跳上台阶贴近高处怪
            self._slope_high_mode = True
            _sj_mage = bool(fight_cfg.get("slope_jump_mage"))
            _since_jump = now - self._slope_jump_t
            if _sj_mage:
                self._slope_hit_window = (self._slope_jump_t > 0 and
                                          SLOPE_AIR_MS <= _since_jump <= SLOPE_AIR_MS + SLOPE_MAGE_STAND_MS)
            else:
                self._slope_hit_window = (self._slope_jump_t > 0 and
                                          SLOPE_HIT_DELAY_MS <= _since_jump <= SLOPE_AIR_MS)
            # 法师落地站定窗内松键站定放技能；其余时间(战士全程、法师空中/推进期)朝怪走
            if _sj_mage and self._slope_hit_window:
                self._release_combat_move()
            elif self._combat_at_locked_edge(move_dir):
                self._release_combat_move()  # 到勾选绿线边缘不水平走,只原地跳上坡
            else:
                self._set_combat_move(move_dir)
                # 位移防卡：按住方向却不动→登记独占解卡、本帧停手；连试上限仍不动由_unblock_tick放弃当前目标(重锁后高处怪落cross走梯子/瞬移)
                # 【隔离排查】解卡线关闭时不登记不停手
                if getattr(self, '_aux_enable_unblock', True) and self._check_move_blocked(now, px, move_dir, jump_key):
                    return
            # 每500~600ms跳一次(两模式共用)
            if now >= self._slope_next_jump:
                if jump_key:
                    self._press_game_key(jump_key, duration=70)
                    self._combat_last_jump = now
                self._slope_jump_t = now
                self._slope_jump_hit = False  # 新一跳：允许在跳打窗口打一下
                self._slope_next_jump = now + random.randint(SLOPE_JUMP_GAP_MIN, SLOPE_JUMP_GAP_MAX)
                # 上屏(用户2026-09-09)：每次起跳报"怪在上方多少px、X差、战法"，每500~600ms一跳一条不刷屏
                self._rlog("实行跳高打·%s:怪在上方%dpx X差%d 朝%s 走-跳-打" % (
                    "法师" if _sj_mage else "战士", _above2, abs(t_cx - px), move_dir))
            _debug_log("[跳高打] %s Y差=%d X差=%d 方向=%s 跳后=%dms 跳打窗口=%s 下次跳余%dms" % (
                "法师" if _sj_mage else "战士", _above2, abs(t_cx - px), move_dir,
                _since_jump, self._slope_hit_window, self._slope_next_jump - now))
        else:
            self._slope_hit_window = False
            # 平地够得着：站定"只打怪"，攻击时不按任何方向键(用户2026-09-07定稿：打怪就只打怪,不许带方向走位)。
            # 方向键只在上方 t_dist>effective_range 的pursue段(找怪/追怪)和够不着的高坡/下坡贴近段按；
            # 一旦进攻击范围够得着就松开方向站定打，这只打死/放弃进入pursue后才重新按方向去找下一只。
            self._slope_high_mode = False
            self._combat_stance_target_x = None
            self._release_combat_move()

        skill_rand = fight_cfg.get("skill_random", 50)
        skill_cast = False
        # 移动中游戏发不出技能（用户规则：跳起来可能放不出来）→ 只有站定（落地）才施法；
        # 【跳高打例外·用户2026-09-09】高处怪必须跳起来打：跳后150ms的_slope_hit_window空中窗口内允许带方向放技能，不拦截
        if (self._combat_move_dir is not None or self._combat_held_keys) and not getattr(self, '_slope_hit_window', False):
            # 移动中游戏发不出技能 → 只有站定（落地）才施法；先松开攻击键
            self._release_attack_key()
            # 诊断：看是不是"移动中不发技能"拦住主攻（治"锁定了也不打"）
            if not hasattr(self, '_atk_block_last') or now - self._atk_block_last > 1000:
                self._atk_block_last = now
                _debug_log("[打怪受阻] 移动中不发技能 move_dir=%s held=%s 距离=%d 射程=%d 目标=%s" % (
                    self._combat_move_dir, list(self._combat_held_keys), t_dist,
                    int(fight_cfg.get("atk1_distance", 150) or 150), (t_cx, t_cy)))
            return
        # 群攻：范围内>=3只怪，80%概率放（用户2026-09-07：删除随机漂移，稳定节奏）
        aoe_key = fight_cfg.get("aoe_key", "")
        if not skill_cast and aoe_key:
            aoe_dist = fight_cfg.get("aoe_distance", 200)
            aoe_cd = int(fight_cfg.get("aoe_interval", 1000))  # 直接用配置值，不乘漂移
            # A2修复：群攻"范围内≥3只"数完整怪表self._monsters(原数被覆盖的monster_dists只剩锁定1只→永远<3放不出)；口径同combat_logic的aoe_count：中心X/脚Y与人物差都在aoe_dist内
            in_range = 0
            for (_am_x1, _am_y1, _am_x2, _am_y2, _am_score) in self._monsters:
                _am_cx = (_am_x1 + _am_x2) // 2
                _am_cy = _am_y2
                _am_dy = _am_cy - py  # 怪脚Y-人脚Y(负=在上,正=在下)
                # 群攻计数：X用群攻射程aoe_dist，Y用群攻自己的上/下范围(用户2026-09-07独立于主攻：下层差太多打不到的怪不许凑数空放群攻)
                if abs(_am_cx - px) <= aoe_dist and -_aoe_y_up <= _am_dy <= _aoe_y_down:
                    in_range += 1
            last = self._attack_last.get("aoe", 0)
            if in_range >= 3 and now - last > aoe_cd:
                if random.random() < 0.8:
                    # 群攻出手前同样短点朝锁定怪方向40ms(理由同主攻,治朝向漂移反打);双向近身群攻也不影响两侧出伤
                    _afvk = VK_RIGHT if t_cx >= px else VK_LEFT
                    self._send_win_key(_afvk, keyup=False)
                    self._combat_timed_keys.append((_afvk, now + 40))
                    self._press_game_key(aoe_key)
                    self._attack_last["aoe"] = now
                    self._combat_target_attacked = True  # 群攻也算对锁定目标出手：空放无反馈时同样走130ms空怪drop换目标(治"群攻一直空打不停")
                    if not self._combat_first_strike_time:
                        self._combat_first_strike_time = now
                    skill_cast = True
                    self._rlog("群攻 %s 范围内%d只" % (aoe_key, in_range), (0, 165, 255))
                    print("[群攻] %s 释放 (范围内%d只怪)" % (aoe_key, in_range))

        # --- 主攻：受控点按(每下 keydown+keyup 都 keybd_event扫描码，能松开)，间隔 atk1_interval（用户2026-09-07：删除随机漂移，稳定节奏） ---
        # 之前"按住攻击键连续打"的问题：松开键要用这个游戏特定模式才松得开，否则一直空打(用户2026-09-05)。
        # 改回点按：每下都能松开，停手=不再点，无"松不开"问题。
        atk_key = fight_cfg.get("atk1_key", "")
        if not skill_cast and atk_key:
            atk_dist = int(fight_cfg.get("atk1_distance", 150) or 150)
            atk_cd = int(fight_cfg.get("atk1_interval", 300))  # 直接用配置值，不乘漂移
            last = self._attack_last.get("atk1", 0)
            # 攻击判定诊断(每1秒)：人物+目标坐标+X差+Y差，看距离是否算错(治"出范围还在打")
            if not hasattr(self, '_atk_diag_last') or now - self._atk_diag_last > 1000:
                self._atk_diag_last = now
                _debug_log("[攻击判定] 人物=(%d,%d) 目标=(%d,%d) X差=%d Y差=%d 射程=%d 状态=%s" % (
                    px, py, t_cx, t_cy, abs(t_cx - px), abs(t_cy - py), atk_dist, _dl['state']))
            # 2026-09-07：主攻必须X进射程 且 Y在攻击Y范围内(怪太高/太低物理打不到就不出手,继续走跳贴近,治高处站定空打)
            # 【跳高打例外·用户2026-09-09】跳后150ms的空中跳打窗口内不要求站定(高处怪必须跳起来在空中打)；其余情况仍须落地站定
            # 面向不再作为攻击前置条件（用户：判定不了面向，最多是空打方向不对，不能因此不打发呆）；朝向由转身逻辑保证。
            _dy_atk = t_cy - py
            _in_hit_win = getattr(self, '_slope_hit_window', False)
            _stance_ok = _in_hit_win or (self._combat_move_dir is None and not self._combat_held_keys)
            # 跳打窗口内每跳只打一下(不等普通攻击间隔,保证跳后150ms必出手)；常规落地站定仍按攻击间隔cd
            _cd_ok = (not self._slope_jump_hit) if _in_hit_win else (now - last > atk_cd)
            if (_stance_ok and t_dist <= atk_dist
                    and -_atk_y_up <= _dy_atk <= _atk_y_down
                    and _cd_ok):
                # 【用户2026-09-09·出手前必短点朝怪方向】人物特征无朝向,爬梯/瞬移/被撞/跳后真实朝向会漂,
                # 不管变没变向,每次主攻出手前都无条件短点朝怪方向键40ms(同向也点),把脸掰回怪再打,治反着打/空打;
                # 走_combat_timed_keys到期自动松,不进_combat_held_keys、不设move_dir→不会被下面"移动中不发技能"拦
                _fvk = VK_RIGHT if t_cx >= px else VK_LEFT
                self._send_win_key(_fvk, keyup=False)
                self._combat_timed_keys.append((_fvk, now + 40))
                self._press_game_key(atk_key)  # keybd_event tap(keydown+keyup)，能松开(用户：用特定模式)
                self._attack_last["atk1"] = now
                if _in_hit_win:
                    self._slope_jump_hit = True  # 本跳已在空中打过，等下一跳
                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用
                if not self._combat_first_strike_time:  # 仅记首次出手，持续攻击不刷新，保证130ms窗口后空怪能被drop
                    self._combat_first_strike_time = now
                skill_cast = True
                print("[主攻] %s 释放 (目标%dpx%s)" % (atk_key, t_dist, "·跳打" if _in_hit_win else ""))

        # === BUFF 1-6（30%概率晚补2-5秒）===
        if not skill_cast:
            buff_rand = fight_cfg.get("buff_random", 50)
            for i, b in enumerate(fight_cfg.get("buffs", []), 1):
                key = b.get("key", "")
                cd = b.get("cd", 0)
                delay = b.get("delay", 0)
                if not key or cd <= 0:
                    continue
                last = self._buff_last.get("buff%d" % i, 0)
                extra = random.randint(2000, 5000) if random.random() < 0.3 else 0
                actual_cd = cd + random.randint(-buff_rand, buff_rand) + extra
                if now - last > actual_cd:
                    self._press_game_key(key)
                    self._buff_last["buff%d" % i] = now
                    if delay > 0:
                        self._combat_busy_until = now + delay
                    self._rlog("BUFF%d %s" % (i, key), (200, 0, 200), log='behavior')
                    print("[BUFF%d] %s 释放" % (i, key))
                    break

        # === 药品1-5（周期性，加随机）===
        pot_rand = pot_cfg.get("potion_random", 50)
        for i, p in enumerate(pot_cfg.get("pots", []), 1):
            key = p.get("key", "")
            cd = p.get("cd", 0)
            if not key or cd <= 0:
                continue
            last = self._potion_last.get("pot%d" % i, 0)
            actual_cd = cd + random.randint(-pot_rand, pot_rand)
            if now - last > actual_cd:
                self._press_game_key(key)
                self._potion_last["pot%d" % i] = now
                print("[药品%d] %s 释放" % (i, key))


    def _bind_window(self):
        """重新绑定游戏窗口（模糊匹配标题）"""
        hwnd = _find_game_window()
        if hwnd:
            self.hwnd = hwnd
            self._hwnd_auto = True  # 用户主动按标题重绑=自动模式,后续句柄变更由看门狗接管
            self._update_window_rect()
            self._detect_minimap()
            self._save_target_window_size()
            self._add_log("窗口已绑定")
            print("[窗口绑定] 已绑定")
            # 启动人物坐标跟踪线程（暂时注释，排查绑定问题）
            # self._start_player_track()
        else:
            self._add_log("未找到游戏窗口")
            print("[窗口绑定] 未找到游戏窗口")

    def _hwnd_title_matches(self, h):
        """句柄标题是否仍是游戏窗口(含关键词),防止旧句柄被系统回收复用到别的窗口"""
        try:
            n = user32.GetWindowTextLengthW(h)
            if n <= 0:
                return False
            b = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, b, n + 1)
            t = b.value or ""
            return any(kw in t for kw in WINDOW_KEYWORDS)
        except Exception:
            return False

    def _ensure_game_hwnd(self):
        """游戏句柄看门狗(仅自动绑定_hwnd_auto=True生效)：游戏重启/换频道会销毁重建窗口、句柄变更,
        旧逻辑只在启动时绑一次,之后拿作废句柄截图→人物/怪全识别0、不锁不打,只能手动删旧再绑。
        这里约1秒校验一次:当前句柄IsWindow且标题仍是游戏→不动;失效→自动_find_game_window重绑并刷新截图区/小地图/绑定列表;
        新窗口还没起来→旧句柄已废则置None等下轮(各处if self.hwnd安全跳过)。准星手选/下拉手选(_hwnd_auto=False)不干预。"""
        if not getattr(self, '_hwnd_auto', False):
            return
        _now_t = time.time()
        if _now_t - getattr(self, '_hwnd_watch_last', 0.0) < 1.0:
            return
        self._hwnd_watch_last = _now_t
        try:
            cur = self.hwnd
            cur_ok = bool(cur) and bool(user32.IsWindow(cur)) and self._hwnd_title_matches(cur)
            if cur_ok:
                return
            new_h = _find_game_window()
            if new_h and user32.IsWindow(new_h):
                if new_h != cur:
                    self.hwnd = new_h
                    self._update_window_rect()
                    try:
                        self._detect_minimap(debug=False)
                    except Exception as _me:
                        _debug_log("[窗口绑定] 重绑后小地图刷新异常: %s" % _me)
                    # 同步绑定列表:移除作废旧句柄,登记新句柄
                    self._bound_windows = [w for w in getattr(self, '_bound_windows', []) if w.get("hwnd") != cur]
                    _n = user32.GetWindowTextLengthW(new_h)
                    _b = ctypes.create_unicode_buffer(_n + 1)
                    user32.GetWindowTextW(new_h, _b, _n + 1)
                    _tt = _b.value or "游戏窗口"
                    if not any(w.get("hwnd") == new_h for w in self._bound_windows):
                        self._bound_windows.append({"hwnd": new_h, "title": _tt})
                    _msg = "游戏句柄变更,已自动重新绑定(%s→%s)" % (cur, new_h)
                    _debug_log("[窗口绑定] " + _msg)
                    self._add_log(_msg)
                    print("[窗口绑定]", _msg)
            else:
                # 没找到新窗口:旧句柄若已彻底销毁就置None,避免继续拿废句柄截图;下轮看门狗再自动找
                if cur and not user32.IsWindow(cur):
                    self.hwnd = None
                    _debug_log("[窗口绑定] 游戏句柄已销毁且暂未找到新窗口,置空等待自动重绑")
        except Exception as _e:
            _debug_log("[窗口绑定] 句柄看门狗异常已跳过: %s" % _e)

    def run(self):
        self._boot_t = time.time()
        print("[冷启动] %.2fs run开始" % (time.time()-self._boot_t))
        win = "PLAY AND HAPPY"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        print("[冷启动] %.2fs namedWindow完成" % (time.time()-self._boot_t))
        cv2.setMouseCallback(win, self._on_mouse)
        self._win_name = win
        self._win_size = (UI_W, UI_H)
        # 防冷启动灰屏：窗口创建后先渲染一帧并泵一次Windows消息，避免第一帧检测耗时过长被系统判未响应（v73验证）
        cv2.imshow(win, self._ui_bg)
        cv2.waitKey(1)
        print("[冷启动] %.2fs 首帧泵消息完成" % (time.time()-self._boot_t))
        while True:
            if self.frame_count <= 3: print("[冷启动] %.2fs 第%d帧开始" % (time.time()-self._boot_t, self.frame_count))
            try:
                # [CPU优化2026-09-07] 主循环只需要小地图块，直接截小地图区域，不再每帧全屏抓1276x749。
                # 旧法每帧全屏抓屏，CPU忙时一次高达200-300ms，是整机CPU满载/掉帧/带不动闪退的主因；
                # 全屏人物/怪/YOLO/血条检测全部在后台检测线程做，主线程只读结果。
                _t0_cap = time.time()
                map_area = self._capture_map()
                _t1_cap = time.time()
            except Exception as _e:
                print("[主循环] 截图异常: %s" % _e)
                time.sleep(0.05)
                continue

            try:
                # 用Win32 IsWindow检测窗口是否真的被销毁（最小化时窗口还在只是不可见，不会误判退出）
                _hwnd = user32.FindWindowW(None, win)
                if not _hwnd or not user32.IsWindow(_hwnd):
                    print("Window closed, exiting...")
                    self._stop_random()
                    break
            except Exception:
                cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
                cv2.setMouseCallback(win, self._on_mouse)

            if self.frame_count == 0:
                cv2.imwrite("debug_map_area.png", map_area)
                print("Captured map_area:", map_area.shape[1], "x", map_area.shape[0])

            self.frame_count += 1
            # FPS统计（每秒打印一次，定位检测慢的原因）
            if not hasattr(self, '_fps_last_time'):
                self._fps_last_time = time.time()
                self._fps_count = 0
                self._fps_capture_time = 0
                self._fps_match_time = 0
                self._fps_char_time = 0  # 人物特征匹配耗时
                self._fps_monster_time = 0  # 怪物特征匹配耗时
                self._fps_yolo_time = 0  # YOLO检测耗时
                self._fps_draw_time = 0  # [CPU诊断]主循环draw绘制耗时
                self._fps_imshow_time = 0  # [CPU诊断]cv2.imshow上屏耗时
            self._fps_count += 1
            _now_fps = time.time()
            if _now_fps - self._fps_last_time >= 1.0:
                _fps = self._fps_count / (_now_fps - self._fps_last_time)
                _fps_msg = "[FPS统计] 帧率=%.1f 截图=%dms 人物匹配=%dms 怪物匹配=%dms YOLO=%dms 绘制=%dms 上屏=%dms" % (_fps, self._fps_capture_time*1000, self._fps_char_time*1000, self._fps_monster_time*1000, self._fps_yolo_time*1000, self._fps_draw_time*1000, self._fps_imshow_time*1000)
                print(_fps_msg)
                _debug_log(_fps_msg)  # 2026-09-07 同时写debug.log，提权进程stdout不可见时仍可定位CPU大头
                if getattr(self, '_seg_sum', None):  # [分段计时]draw各段每秒耗时，定位绘制大头
                    _seg_s = " ".join("%s=%dms" % (k, v * 1000)
                                      for k, v in sorted(self._seg_sum.items(), key=lambda x: -x[1]) if v > 0.0005)
                    if _seg_s:
                        print("[draw分段] " + _seg_s)
                    self._seg_sum = {}
                self._fps_last_time = _now_fps
                self._fps_count = 0
                self._fps_capture_time = 0
                self._fps_char_time = 0
                self._fps_monster_time = 0
                self._fps_yolo_time = 0
                self._fps_draw_time = 0
                self._fps_imshow_time = 0
                self._fps_match_time = 0
            if self._auto_refresh and self.frame_count % 30 == 0:
                # [健壮性2026-09-07] 三模板重定位内部截图失败/匹配异常都不得冒泡到主入口导致闪退
                try:
                    self._detect_minimap(debug=False)
                except Exception as _e:
                    _debug_log("[小地图] 定时重定位异常已跳过: %s" % _e)
            # 窗口大小固定：每30帧检测一次，变动则拉回
            if self.frame_count % 30 == 0:
                self._ensure_game_hwnd()   # 句柄看门狗:游戏重启/换频道句柄变更时自动重绑(仅自动绑定),先于尺寸校正
                self._ensure_window_size()
            player_pos = self.find_player_dot(map_area)  # 每帧都检测光点
            # 光点不做EMA平滑（保证轻微移动也能反映到比例上），检测失败时用上一帧位置
            if player_pos is not None:
                self._player_map_pos = player_pos
                self._last_smooth_dot = player_pos
                self._map_dot_lost = 0  # 找到光点，丢失计数清零
            else:
                _last_dot = getattr(self, '_last_smooth_dot', None)
                if _last_dot is not None:
                    self._player_map_pos = _last_dot
                # 换地图/小地图尺寸变化会让旧矩形截不全→光点连续丢失。不等30帧定时刷新，
                # 连续丢15帧(约0.75s)立即三模板重定位；2秒节流防正常偶发丢点反复全屏匹配(2026-09-07)
                if getattr(self, '_auto_refresh', True) and self.hwnd:
                    self._map_dot_lost = getattr(self, '_map_dot_lost', 0) + 1
                    _now_force = time.time()
                    if (self._map_dot_lost >= 15
                            and _now_force - getattr(self, '_last_minimap_force_t', 0) > 2.0):
                        self._last_minimap_force_t = _now_force
                        self._map_dot_lost = 0
                        try:
                            self._detect_minimap(debug=False)
                            _debug_log("[小地图] 光点连续丢失，立即三模板重定位(换图/尺寸变化兜底)")
                        except Exception as _e:
                            print("[小地图] 光点丢失重定位异常:", _e)
            # 保存小地图坐标供战斗逻辑判断平台
            # 【模块B】独立检测人物屏幕位置+怪物（不依赖运行状态，脚本启动就工作）
            if self.hwnd:  # 人物屏幕位置每帧检测（绿框跟随人物实时刷新）
                try:
                    # 主线程不再截图，只读后台检测线程结果；_frame仅作"有画面"门控(用小地图帧占位,非None即可)
                    _frame = map_area
                    self._fps_capture_time += (_t1_cap - _t0_cap)
                    if _frame is not None:
                        _t2 = time.time()
                        # 人物/怪/YOLO/血条 都由后台检测线程同一帧算好了，主线程只读结果+过滤假怪（主线程不再做重活）
                        self._player_screen_pos = self._raw_char_pos
                        self._monster_hp_bars = self._raw_hp_bars
                        self._raw_cached = self._raw_cached_feature_monsters
                        # 2026-09-07 用户定稿：不再做"静止怪"静态过滤(冒险岛大量怪本就站桩,会误剔近身真怪→有怪不锁/空打)。
                        # 检测到的怪全部保留,真假统一靠"打一下,250ms内无血条且无伤害数字→放弃"来判；只保留已放弃空怪的短时去重
                        self._monsters = list(self._raw_monsters)
                        self._monsters = self._filter_dropped_phantoms(self._monsters)
                        _t3 = time.time()
                        self._fps_char_time += (_t3 - _t2)  # 读后台结果耗时（原人物匹配耗时）
                        # 蒙板重绘节流(2026-09-07 CPU优化)：原每帧InvalidateRect→WM_PAINT高达30次/秒，
                        # 蒙板线程自身已有100ms定时器+20fps消息循环，这里限100ms一次即可(人物框/怪物框仍跟手，
                        # 每帧数据照常写入self._monster_overlay_data，重绘频率不影响检测/打怪逻辑)
                        if getattr(self, '_overlay_hwnd', None):
                            _now_redraw = time.time()
                            if _now_redraw - getattr(self, '_last_overlay_redraw_t', 0) >= 0.10:
                                self._last_overlay_redraw_t = _now_redraw
                                user32.InvalidateRect(self._overlay_hwnd, None, True)
                except Exception as _e:
                    print("[主循环] 帧检测异常:", _e)
            # 【模块B】自动校准scale比例（人物移动时记录屏幕和小地图变化，越跑越准）
            self._update_scale_calibration()
            # 【模块B】自动记录端点已取消，改用手动同屏三点校准（不跨画面更准）
            # self._auto_calibrate_edges()

            # 【模块B】蒙板拖动检测（仅stage=1时，红绿蓝三点跟随人物移动，可拖动绿点蓝点调偏移）
            if self._auto_calib_stage == 1:
                # 实时更新基点位置（红色基点覆盖人物特征，跟随人物移动）
                # 小地图坐标[2],[3]始终用光点实时更新(准)，不受屏幕位置匹配失败影响，避免红点慢一拍
                if self._player_map_pos:
                    _pmx, _pmy = self._player_map_pos[0], self._player_map_pos[1]
                else:
                    _pmx = _pmy = 0
                if self._player_screen_pos:
                    _psx, _psy = self._player_screen_pos[0], self._player_screen_pos[1]
                    self._auto_calib_base = (_psx, _psy, _pmx, _pmy)  # 屏幕+光点都更新
                elif self._player_map_pos:
                    # 屏幕位置匹配失败时，仍用小地图光点更新基点小地图坐标[2],[3]，红点跟上光点不慢一拍
                    _ob = self._auto_calib_base
                    _psx = _ob[0] if _ob else 0
                    _psy = _ob[1] if _ob else 0
                    self._auto_calib_base = (_psx, _psy, _pmx, _pmy)
                # 绿点蓝点屏幕坐标 = 基点 + 相对偏移（跟着人物一起动）
                base = self._auto_calib_base
                if base:
                    bx, by = base[0], base[1]
                    goff = getattr(self, '_auto_calib_green_offset', (400, 0))
                    boff = getattr(self, '_auto_calib_blue_offset', (0, -400))
                    green_scr = (bx + goff[0], by + goff[1])
                    blue_scr = (bx + boff[0], by + boff[1])
                else:
                    green_scr = None
                    blue_scr = None
                # 鼠标拖动检测（全局GetAsyncKeyState，不依赖蒙板窗口消息）
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                cursor = POINT()
                user32.GetCursorPos(ctypes.byref(cursor))
                # 全局坐标转窗口坐标（减窗口左上角，和蒙板绘制/_capture_window一致）
                if self.window_rect:
                    mx = cursor.x - self.window_rect['left']
                    my = cursor.y - self.window_rect['top']
                else:
                    mx, my = cursor.x, cursor.y
                if left_down and not self._auto_calib_dragging:
                    # 左键刚按下，检测是否点中绿点或蓝点（±12px范围）
                    if green_scr and abs(mx - green_scr[0]) <= 18 and abs(my - green_scr[1]) <= 18:
                        self._auto_calib_dragging = 'green'
                    elif blue_scr and abs(mx - blue_scr[0]) <= 18 and abs(my - blue_scr[1]) <= 18:
                        self._auto_calib_dragging = 'blue'
                elif left_down and self._auto_calib_dragging:
                    # 拖动中，更新相对偏移（绿/蓝圈可上下左右自由移动，基点跟随人物）
                    if base:
                        bx, by = base[0], base[1]
                        if self._auto_calib_dragging == 'green':
                            self._auto_calib_green_offset = (mx - bx, my - by)  # 绿圈可上下左右移动
                        elif self._auto_calib_dragging == 'blue':
                            self._auto_calib_blue_offset = (mx - bx, my - by)  # 蓝圈可上下左右移动
                elif not left_down and self._auto_calib_dragging:
                    # 左键松开，结束拖动
                    self._auto_calib_dragging = None

            # 【模块B】模板匹配跟踪（stage>=2时，每5帧匹配一次，跟踪特色位置画绿/蓝圆）
            if self._auto_calib_stage >= 2 and self.frame_count % 5 == 0:
                self._match_calib_templates()

            if self.recording_platform:
                _debug_log("[录制A] player_pos=%s points_count=%d recording=%s" % (str(player_pos), len(self.platform_points), self.recording_platform))  # 调试日志：验证录制时人物光点是否有效
            if self.recording_platform and player_pos:
                # 同一X位置(差值<1px)的新点覆盖旧点，以后画的为准；移动超过1px就记录新点，提高轨迹密度
                if self.platform_points and abs(self.platform_points[-1][0] - player_pos[0]) < 1:
                    self.platform_points[-1] = player_pos
                else:
                    self.platform_points.append(player_pos)
                    _debug_log("[录制C] 新增点 pos=%s 总点数=%d" % (str(player_pos), len(self.platform_points)))
            if self.recording_ladder and player_pos:
                # 【统一坐标空间】梯子与平台、旧梯子完全同一空间=小地图画面原始像素坐标：
                # 直接收集光点画面坐标，不做任何背景滚动/相对位移修正(此前scroll_y修正造出第二坐标空间导致梯子分层,已废弃)
                self.ladder_points.append(player_pos)

            # 边缘自救优先(用户2026-09-07)：贴地图边丢特征时先向中间走找回，自救期间暂停巡路/战斗移动避免按键打架
            _edge_recovering = self._edge_recovery_tick(time.time() * 1000) if getattr(self, '_aux_enable_edge', True) else False
            # 掉台归位独占线(用户2026-09-09)：与边缘自救同级,任一辅助线独占期间主线(_random_step/_combat_tick)一律暂停,
            # 辅助线结束(特征找回/光点回台)才恢复主线——辅助线与主线同一时间只跑一个,不并行抢键
            _fall_returning = (self._fall_return_tick() if not _edge_recovering else False) if getattr(self, '_aux_enable_fall', True) else False
            # 卡住解卡独占线(用户2026-09-09)：仅在没有更高优先级辅助线(边缘自救/掉台归位)时运行
            _unblocking = (self._unblock_tick() if not (_edge_recovering or _fall_returning) else False) if getattr(self, '_aux_enable_unblock', True) else False
            _aux_busy = _edge_recovering or _fall_returning or _unblocking
            if not _aux_busy:
                self._random_step(player_pos)
            self._check_hotkeys()
            # 蓝色框校准模式：方向键微调选中角点，S保存，Q退出（与输入框一致的set差集边沿触发，避免字典重置bug）
            if self._calibrating_blue_box:
                if not hasattr(self, '_bluebox_prev_keys'):
                    self._bluebox_prev_keys = set()
                _bluebox_vks = [0x25, 0x26, 0x27, 0x28, 0x53, 0x51]
                _current = set()
                for _vk in _bluebox_vks:
                    if user32.GetAsyncKeyState(_vk) & 0x8000:
                        _current.add(_vk)
                _new_keys = _current - self._bluebox_prev_keys
                self._bluebox_prev_keys = _current
                for _vk in _new_keys:
                    self._handle_blue_box_key(_vk)

            # === 自动吃药检测（HP/MP低于阈值） ===
            try:
                self._check_auto_potion()
            except Exception as e:
                print("[自动吃药] 异常:", e)
            try:
                if not _aux_busy:
                    self._combat_tick()
            except Exception as e:
                print("[战斗] 异常:", e)
                import traceback; _debug_log("[战斗] 异常: " + str(e) + "\n" + traceback.format_exc())

            # === 定期维护(启动即跑一次，之后每10分钟)：debug.log只留最近5分钟、清1天前调试缓存；backups全部保留 ===
            try:
                _mnt_now = time.time()
                if _mnt_now - getattr(self, '_last_maint_ts', 0) > 600:
                    self._last_maint_ts = _mnt_now
                    self._maint_run()
            except Exception as e:
                print("[维护] 异常:", e)

            # === tkinter独立窗口事件泵（仅在有窗口打开时调用，避免与OpenCV冲突）===
            try:
                if hasattr(self, '_tk_root') and self._tk_root is not None:
                    has_win = (getattr(self, '_save_window', None) is not None or
                               getattr(self, '_plan_window', None) is not None or
                               getattr(self, '_clear_window', None) is not None or
                               getattr(self, '_char_feature_window', None) is not None or
                               getattr(self, '_monster_feature_window', None) is not None or
                               getattr(self, '_ladder_feature_window', None) is not None)
                    if has_win:
                        # 处理所有待处理事件（最多10ms，避免阻塞主循环），提高弹窗输入/移动响应速度
                        # 注意：必须循环调用dooneevent直到没有事件或超时，否则after定时器事件可能不被处理
                        _tk_start = time.time()
                        _tk_count = 0
                        while time.time() - _tk_start < 0.010:
                            if not self._tk_root.dooneevent(0):  # 0 = 不等待，有事件就处理
                                # 没有事件时短暂sleep，避免CPU占用过高
                                time.sleep(0.001)
                                _tk_count += 1
                                if _tk_count > 3:  # 连续3次没有事件就退出
                                    break
                            else:
                                _tk_count = 0  # 有事件时重置计数
            except Exception as e:
                _debug_log("[方案窗口] tk update异常: %s" % e)

            # === 偏移视觉反馈（游戏画面中角色匹配点+偏移点）===
            try:
                self._show_offset_feedback()
            except Exception as e:
                print("[偏移反馈] 异常:", e)

            # === 透明蒙板（怪物/黄点/血条红点/蓝条蓝点统一显示）===
            # 检测结果由 _combat_tick 每350ms更新到 self._monsters / self._player_screen_pos
            # 蒙板只要窗口绑定成功就启动（不依赖_running），确保加药竖框始终可见
            if self.hwnd and not self._monster_overlay_running:
                self._start_monster_overlay()
            # 窗口绑定成功就启动后台检测线程（人物/怪/YOLO/血条同帧算，主线程只读结果）
            self._start_detection_thread()
            # === 显示层速度外推：低帧率(6-7fps)下蒙板天然落后1帧≈160ms，按人物速度外推显示位置，
            #    绿框中心/特征点/黄点全部用外推后的显示位置，走路跟手不拖后腿。纯显示，不动匹配/搜索/打怪 ===
            _now_sync2 = time.time() * 1000
            _raw_pos = self._player_screen_pos
            _dt_sync = (_now_sync2 - getattr(self, '_char_disp_pos_time', _now_sync2)) / 1000.0
            _disp_pos = _raw_pos
            if _raw_pos:
                # 匹配成功：用最近两帧原始位置算速度，显示位置=当前位置+速度×外推时长
                if getattr(self, '_char_disp_pos_prev', None) and _dt_sync > 0.01:
                    _vx = (_raw_pos[0] - self._char_disp_pos_prev[0]) / _dt_sync
                    _vy = (_raw_pos[1] - self._char_disp_pos_prev[1]) / _dt_sync
                    _vmax = 1200.0  # 速度封顶，防急停/大跳时超调
                    _vx = max(-_vmax, min(_vmax, _vx))
                    _vy = max(-_vmax, min(_vmax, _vy))
                    self._char_disp_vel = (_vx, _vy)
                _ext = min(_dt_sync, 0.120)  # 外推最多120ms，静止时外推0
                _vel = getattr(self, '_char_disp_vel', (0.0, 0.0))
                # 外推位移再限界60px，防疾跑/瞬移时显示超调
                _ex = max(-60.0, min(60.0, _vel[0] * _ext))
                _ey = max(-60.0, min(60.0, _vel[1] * _ext))
                _disp_pos = (int(_raw_pos[0] + _ex), int(_raw_pos[1] + _ey))
                # 存原始位置（不是外推值），避免速度计算自反馈
                self._char_disp_pos_prev = _raw_pos
                self._char_disp_pos_time = _now_sync2
            else:
                # 匹配失败宽限期：用上次速度短时继续外推（最多0.5秒），点/框不掉队也不乱飞
                _prev_raw = getattr(self, '_char_disp_pos_prev', None)
                _vel = getattr(self, '_char_disp_vel', (0.0, 0.0))
                if _prev_raw and _dt_sync < 0.5:
                    _ext = min(max(_dt_sync, 0.0), 0.120)
                    _disp_pos = (int(_prev_raw[0] + _vel[0] * _ext), int(_prev_raw[1] + _vel[1] * _ext))
            if self._monster_overlay_data is None:
                self._monster_overlay_data = {}  # 避免主循环在蒙板线程初始化前访问None崩溃
            if _disp_pos:
                self._monster_overlay_data["char_pos"] = _disp_pos
                # 绿框显示：以外推显示位置为中心(400x400)，搜索用的ROI不受影响
                self._monster_overlay_data["char_match_roi"] = (
                    _disp_pos[0] - 200, _disp_pos[1] - 200, _disp_pos[0] + 200, _disp_pos[1] + 200)
                # 特征点随显示位置整体平移，弥补"慢一拍"
                if _raw_pos:
                    _dx = _disp_pos[0] - _raw_pos[0]
                    _dy = _disp_pos[1] - _raw_pos[1]
                    if _dx or _dy:
                        self._monster_overlay_data["char_feature_matches"] = [
                            (fx + _dx, fy + _dy, fid, fc) for (fx, fy, fid, fc) in self._char_feature_matches]
                    else:
                        self._monster_overlay_data["char_feature_matches"] = self._char_feature_matches
                else:
                    self._monster_overlay_data["char_feature_matches"] = self._char_feature_matches
            else:
                # 无任何位置可外推：绿框保持上次搜索ROI显示
                self._monster_overlay_data["char_match_roi"] = getattr(self, "_char_match_roi_rect", None)
            self._monster_overlay_data["monster_feature_matches"] = self._monster_feature_matches
            _now_sync = time.time()
            if not hasattr(self, '_last_monster_sync_log') or _now_sync - self._last_monster_sync_log > 2:
                self._last_monster_sync_log = _now_sync
                _debug_log("[蒙板同步] 人物特征点%d个 怪物特征点%d个 怪物匹配值:%s" % (
                    len(self._char_feature_matches), len(self._monster_feature_matches),
                    str([(f[0], f[1], f[2]) for f in self._monster_feature_matches[:3]])))
            if self._running:
                try:
                    if self._monster_overlay_data is None:
                        self._monster_overlay_data = {}
                    # 同步怪物和人物位置到蒙板
                    self._monster_overlay_data["monsters"] = self._monsters
                    self._monster_overlay_data["monster_hp_bars"] = self._monster_hp_bars
                    self._monster_overlay_data["locked_target"] = getattr(self, '_combat_locked_target', None)
                    # 【用户2026-09-08】当前选中的梯子红框（小地图坐标转屏幕坐标，方便调试看选的对不对）
                    _ld_x = getattr(self, '_climb_ladder_x', 0)
                    _ld_yt = getattr(self, '_climb_ladder_y_top', 0)
                    _ld_yb = getattr(self, '_climb_ladder_y_bottom', 0)
                    _ld_state = getattr(self, '_climb_state', 'none')
                    if _ld_state != 'none' and _ld_x > 0 and self._player_map_pos and self._player_screen_pos:
                        try:
                            _pmx, _pmy = self._player_map_pos
                            _psx, _psy = self._player_screen_pos
                            _esx, _esy = self._effective_scale()
                            if _esx > 0 and _esy > 0:
                                _lscr_x = int(_psx + (_ld_x - _pmx) / _esx)
                                _lscr_yt = int(_psy + (_ld_yt - _pmy) / _esy)
                                _lscr_yb = int(_psy + (_ld_yb - _pmy) / _esy)
                                self._monster_overlay_data["ladder_rect"] = (_lscr_x - 8, _lscr_yt, _lscr_x + 8, _lscr_yb)
                            else:
                                self._monster_overlay_data["ladder_rect"] = None
                        except Exception:
                            self._monster_overlay_data["ladder_rect"] = None
                    else:
                        self._monster_overlay_data["ladder_rect"] = None
                except Exception as e:
                    print("[蒙板] 同步异常:", e)

            # === 准星拖拽绑定检测 ===
            if self._drag_crosshair:
                # 处理pygame事件，避免窗口无响应
                if self._crosshair_pygame_inited:
                    pygame.event.pump()
                left_down = user32.GetAsyncKeyState(0x01) & 0x8000  # VK_LBUTTON
                if left_down:
                    # 跟随全局鼠标位置（不限制在UI窗口内，可拖到其他窗口）
                    cursor = POINT()
                    user32.GetCursorPos(cursor)
                    # 用pygame透明置顶窗口显示准星，可拖到屏幕任意位置
                    if self._crosshair_pygame_hwnd is None:
                        self._create_crosshair_window()  # 首次拖拽时创建窗口
                    self._update_crosshair_window(cursor.x, cursor.y)  # 更新窗口位置到鼠标位置
                    # 同时更新UI窗口上的准星位置（用于UI窗口内显示）
                    hwnd_ui = user32.FindWindowW(None, "PLAY AND HAPPY")
                    if hwnd_ui:
                        client_cursor = POINT(cursor.x, cursor.y)
                        user32.ScreenToClient(hwnd_ui, ctypes.byref(client_cursor))
                        self._crosshair_pos = (client_cursor.x, client_cursor.y)
                else:
                    # 左键释放，绑定鼠标指向的顶层窗口
                    cursor = POINT()
                    user32.GetCursorPos(cursor)
                    hwnd = user32.WindowFromPoint(cursor)
                    # GetAncestor取真正顶层窗口(GA_ROOT=2)
                    hwnd = user32.GetAncestor(hwnd, 2)
                    _debug_log("跨线释放绑定 hwnd=%s" % hwnd)
                    _debug_log("前台绑定 hwnd=%s" % hwnd)
                    if hwnd:
                        length = user32.GetWindowTextLengthW(hwnd)
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value or "未知窗口"
                        _debug_log("前台绑定标题: %s" % title)
                        self.hwnd = hwnd
                        self._hwnd_auto = False  # 准星手动绑定:看门狗不自动抢,除非用户再点自动绑定
                        self._update_window_rect()
                        self._detect_minimap()
                        self._save_target_window_size()
                        if not any(w["hwnd"] == hwnd for w in self._bound_windows):
                            self._bound_windows.append({"hwnd": hwnd, "title": title})
                        self._add_log("已绑定: %s" % title[:20])
                        print("[窗口绑定] 前台窗口已绑定:", title)
                    else:
                        self._add_log("绑定失败")
                    self._drag_crosshair = False
                    self._crosshair_pos = self._crosshair_home
                    # 拖拽结束，销毁pygame准星窗口
                    self._destroy_crosshair_window()

            try:
                _td0 = time.time()
                frame = self.draw(map_area, player_pos)
                self._fps_draw_time += time.time() - _td0
                _ti0 = time.time()
                cv2.imshow(win, frame)
                self._fps_imshow_time += time.time() - _ti0
            except Exception as e:
                print("draw error:", e)
                cv2.imshow(win, self._ui_bg)

            key = cv2.waitKey(25) & 0xFF  # 2026-09-07 CPU二档降压：10→15→25ms，UI约≤40帧(挂机面板+小地图光点无需高刷)，战斗按键靠内部时间戳节流不受影响
            if self.frame_count <= 3: print("[冷启动] %.2fs 第%d帧waitKey完成 key=%d" % (time.time()-self._boot_t, self.frame_count, key))
            # 输入框自动失焦：3秒无变化（全局轮询输入不依赖UI前台，故不检查前台窗口）
            if self._focused_field is not None:
                now_ms = time.time() * 1000
                if now_ms - self._last_input_change > 3000:
                    self._save_input_config()
                    self._focused_field = None
            # 输入框聚焦时优先处理键盘
            if self._focused_field is not None:
                if self._is_key_field(self._focused_field):
                    # BACKSPACE清空键值，ESC取消聚焦（不参与按键捕获）
                    if user32.GetAsyncKeyState(0x08) & 0x8000:
                        self._field_values[self._focused_field] = ""
                        self._save_input_config()
                        self._focused_field = None
                        continue
                    if user32.GetAsyncKeyState(0x1B) & 0x8000:
                        self._focused_field = None
                        continue
                    self._poll_key_capture()
                else:
                    self._poll_num_input()
                continue
            # 任意按键关闭所有下拉菜单
            if key != 255:
                self._dropdown = None
                self._bound_dropdown = False
            if key in (ord('q'), 27):
                self._stop_random()
                break
            elif key == ord('r'):
                print("Redetecting...")
                self._detect_minimap()
            elif key == ord('n'):
                self.manual_select_region()
        # Ensure overlay is destroyed before exit
        if self._monster_overlay_running:
            self._stop_monster_overlay()
        # 人物跟踪线程已删除
        cv2.destroyAllWindows()
        print("Final:", len(self.platforms), "platforms,", len(self.ladders), "ladders")



if __name__ == "__main__":
    # === 单实例锁v3（2026-09-07加固）：探测函数定义在文件顶部(重import之前)已先行执行一次，
    # 此处复用 _probe_any_instance_running 在提权前后各再查一次，彻底杜绝双实例并存。
    import ctypes as _ctypes, sys as _sys
    # === 管理员权限检查 ===
    # 游戏(冒险岛怀旧服)以管理员权限运行，UIPI会阻止普通权限进程向管理员进程发送模拟输入
    # 必须以管理员权限启动bot，否则按键/加药全部无效
    # 启动时自动修正工作目录（防止管理员重启后工作目录变为System32）
    if getattr(_sys, "frozen", False):
        _exe_dir = os.path.dirname(os.path.abspath(_sys.executable))
        if os.getcwd() != _exe_dir:
            os.chdir(_exe_dir)
    def _is_admin():
        try:
            return _ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    if not _is_admin():
        print("[权限] 检测到非管理员权限，游戏以管理员运行时必须以管理员启动bot")
        print("[权限] 正在自动以管理员权限重启...")
        try:
            if getattr(_sys, "frozen", False):
                # exe：重启只需 exe 路径，参数为脚本参数(通常无)
                _params = " ".join(['"%s"' % a for a in _sys.argv[1:]]) if len(_sys.argv) > 1 else ""
                _workdir = os.path.dirname(os.path.abspath(_sys.executable))
            else:
                # .py：必须把脚本路径也拼进去(用绝对路径，保证提权后新进程能定位脚本+固定工作目录)，否则重启成 python 交互窗口
                _abs_argv = [os.path.abspath(_sys.argv[0])] + list(_sys.argv[1:])
                _params = " ".join(['"%s"' % a for a in _abs_argv])
                _workdir = globals().get("SCRIPT_DIR", os.getcwd())
            _ctypes.windll.shell32.ShellExecuteW(None, "runas", _sys.executable, _params, _workdir, 1)
        except Exception as _e:
            print("[权限] 自动提升失败: %s" % _e)
            print("[权限] 请右键 MapleBot.exe 选择'以管理员身份运行'")
            try:
                input("按回车退出...")
            except:
                pass
        _sys.exit()
    print("[权限] 已以管理员权限运行，模拟输入可正常发送到游戏")
    # 提权后再次探测（提权等待期间可能已有其他实例先拿到锁/窗口），命中则退出
    if _probe_any_instance_running():
        print("[单实例] 已有一个脚本在运行，本实例自动退出（避免重复抢CPU）")
        _sys.exit(0)
    # 创建/打开互斥体：句柄必须保留到进程结束（挂全局变量防GC回收=锁失效）
    _single_mutex_handle = _K32.CreateMutexW(None, False, _SINGLE_MUTEX_NAME)
    if _ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS=已有一个实例持有锁
        print("[单实例] 已有一个脚本在运行，本实例自动退出（避免重复抢CPU）")
        _sys.exit(0)
    try:
        MinimapRouteRecorder().run()
    except Exception as _e:
        import traceback
        _err = traceback.format_exc()
        print("[全局异常] %s" % _e)
        _debug_log("[全局异常] %s" % _err)
        _debug_log(_err)
        # 异常后等待3秒让用户看到错误，然后退出（避免input卡住表现为未响应）
        import time
        time.sleep(3)

