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
# 原生崩溃(段错误)栈记录:Tk跨线程/OpenCV等C层崩溃Python的try拦不住、进程直接消失,faulthandler把所有线程栈写crash.log便于定位
try:
    import faulthandler
    _cf = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crash.log'), 'a', encoding='utf-8')
    _cf.write('\n===== run %s =====\n' % time.strftime('%Y-%m-%d %H:%M:%S')); _cf.flush()
    faulthandler.enable(file=_cf, all_threads=True)
except Exception:
    pass
# 主线程未捕获异常同样留痕:提权隐藏窗口启动时stderr被吞,普通Python异常导致的"安静闪退"看不到报错,
# 写进和faulthandler同一个crash.log,下次闪退即可拿到完整Python traceback精确定位。
try:
    import sys as _sys, traceback as _tbmod
    def _main_excepthook(et, ev, tb):
        try:
            _cf.write("[主线程未捕获异常] " + "".join(_tbmod.format_exception(et, ev, tb)) + "\n"); _cf.flush()
        except Exception:
            pass
        _sys.__excepthook__(et, ev, tb)  # 仍走默认行为(打印到stderr)
    _sys.excepthook = _main_excepthook
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
from core.world_snapshot import WorldSnapshot, SnapshotStore

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
_SELF_PID = os.getpid()  # 脚本自身进程PID：自动枚举/准星绑定一律排除本进程窗口(控制面板/框选窗都是自己),禁止绑定自己

@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
def _enum_windows_cb(hwnd, lparam):
    try:
        if user32.IsWindowVisible(hwnd):
            _ppid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(_ppid))
            if _ppid.value == _SELF_PID:
                return True  # 脚本自身窗口永不参与自动绑定
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

VK_F3 = 0x72  # 架构B:动作权仲裁器"实控/影子"一键切换(只切内部开关,不发键给游戏)
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
# ==================== 角色识别(2026-09-13:小锚点多冗余+局部半径跟踪,替代旧整框/小块人物特征) ====================
ROLE_REC_DIR = os.path.join(DATA_DIR, "role_recognize")  # 全局角色锚点目录(只跟角色有关、不随地图方案变,采一次长期用,重采才覆盖)
os.makedirs(ROLE_REC_DIR, exist_ok=True)
ROLE_REC_FILE = os.path.join(ROLE_REC_DIR, "role_recognize.json")
# 锚点定义(key,中文名,说明):角色名=主模板;面部只采朝右一张=人物主体(朝左由水平镜像自动生成,顺带判朝向);宠物名=被特效盖住时冗余
# 锚点项:角色名/面部朝右/宠物名1-3/黑名单,没有"钻石"项(2026-09-13实机截图确认)
ROLE_ANCHORS = [
    ("name",    "角色名(主模板)",  "主要模板·头顶名字,固定不变,优先用它"),
    ("face_r",  "面部·朝右",      "只采朝右一张=人物主体;朝左由它水平镜像自动生成(不采会换的衣服)"),
    ("back",    "后脑",          "人物后脑/背面样式(爬梯等脸朝里、正面脸匹配不到时),彩色原图不抠图"),
    ("pet1",    "宠物名1",        "人被特效盖住时改用宠物名,建议给宠物改独特名"),
    ("pet2",    "宠物名2",        "第二个宠物名冗余(需先采1)"),
    ("pet3",    "宠物名3",        "第三个宠物名冗余(需先采2)"),
]
ROLE_ANCHOR_KEYS = [_a[0] for _a in ROLE_ANCHORS]
# 跟踪参数默认值(默认写死,角色识别面板可调、自动存盘)
ROLE_TRACK_DEFAULT = {
    "fps": 24,         # 每秒跟踪次数
    "thr": 0.62,       # 锚点匹配阈值
    "rx": 180,         # 横向半径=局部跟踪窗半宽(以上一帧锚点为中心)
    "ry": 120,         # 纵向半径=局部跟踪窗半高
    "maxmove": 48,     # 最大跳变:相邻帧锚点位移超此值判为瞬移到别人身上,丢弃
    "faststep": 2,     # 快速失配:局部窗内连续失配多少帧后切全图搜索
    "research": 1500,  # 全图搜索间隔(ms):局部跟丢后限频全屏找回,避免每帧全屏拖帧
    "hold": 90,        # 丢失保持(帧):刚丢先保持上一可信点,不立刻乱跳
}
ROLE_TRACK_FIELDS = [  # (参数key,中文标签,是否小数)
    ("fps", "跟踪FPS", False), ("thr", "匹配阈值", True),
    ("rx", "横向半径", False), ("ry", "纵向半径", False),
    ("maxmove", "最大跳变", False), ("faststep", "快速失配", False),
    ("research", "全图搜索ms", False), ("hold", "丢失保持", False),
]
ROLE_POLY_CLOSE_DIST = 14  # 描点采集:鼠标靠近顶点/边线的命中距离(px)
ROLE_MAX_CHARS = 10        # 角色方案最多保存10套(以角色为单位,每套内含该角色全部锚点),满了再建自动删最旧一套
ROLE_CN_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]  # 默认命名 角色一..角色十
ROLE_POLY_AUTO_CLOSE = 4   # 点满几个点自动闭合(长方形点4角即可,不要求直角;闭合后点边线可继续加点)
ROLE_POLY_MIN_PTS = 3      # 闭合多边形最少点数(删点不得少于此)
ROLE_ANCHOR_TO_FOOT_Y = 0  # 已废弃(2026-09-13用户定稿):不做到脚补偿,锚点中心即人物坐标;单平台打怪只看X、跨平台走引导线,留常量=0仅为兼容
ROLE_MAG_SRC = 100         # 放大描点:以鼠标点击点为中心取的原图边长(px)
ROLE_MAG_ZOOM = 2          # 放大描点:放大倍数(放大图显示在点击点旁边,在放大图上描点、坐标映射回原图)
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
GAME_W = 1280             # 游戏固定窗口宽度(用户2026-09-06游戏更新后定稿：全窗口写死1280x800，不区分客户区，不要运行时动态识别，避免窗口一变尺寸就漂移/识别变化)
GAME_H = 800              # 游戏固定窗口高度(GetWindowRect全窗口含标题栏，用户2026-09-06更新后=1280x800；旧1290x756已废弃)
COMBAT_FAR_RANGE = 1300   # 同平台寻怪X范围·默认值(用户2026-09-07：800→1300，左右各1300)；可在fight页"寻怪范围"弹窗自定义far_range_x
FAR_RANGE_Y_UP_DEFAULT = 150   # 寻怪Y上方范围默认(怪脚Y比人物Y小多少算上方可检测)
FAR_RANGE_Y_DOWN_DEFAULT = 150 # 寻怪Y下方范围默认(怪脚Y比人物Y大多少算下方可检测)
DETECT_PERIOD_MS = 120    # 后台检测线程·忙时周期(2026-09-09 CPU优化100→120≈8.3Hz:截图/人物匹配省约17%,人物点8Hz仍跟手；重活YOLO/血条各自节流)；无怪走DETECT_IDLE_MS省电
LADDER_PRECISE_PERIOD_MS = 22  # 上梯高帧【高配目标】周期≈45Hz(≥8核);中低配由下面分档给更稳的起点,再叠加自适应退避,慢机也不卡死
LADDER_PRECISE_HI_CORES = 8     # 逻辑核数≥此值用高配目标档22ms
LADDER_PRECISE_TARGET_MS_MID = 28  # 4~7核目标周期≈36Hz(用户2026-09-11:四核也要带得动,起点更稳、少退避抖动)
LADDER_PRECISE_TARGET_MS_LOW = 34  # ≤3核目标周期≈29Hz(低配保底,仍远快于常态120ms)
LADDER_PRECISE_MIN_SLEEP_MS = 3   # 高帧每轮至少留出的空闲ms(保GIL/主线UI绘制),防止检测线程把一个核吃满(四核低配适配,用户2026-09-11)
LADDER_PRECISE_PERIOD_MAX = 45    # 高帧自适应退避上限:机器再慢周期也只放宽到45ms(≈22Hz),宁降帧不卡死CPU
LADDER_PRECISE_OVERLOAD_N = 3     # 连续几轮"单轮耗时逼近周期、留不出MIN_SLEEP"=过载,降帧一档
LADDER_PRECISE_RELAX_N = 15       # 连续约多少轮都很轻松(≈0.3-0.4s)=性能够,升回一档直到目标周期
LADDER_PRECISE_STEP_MS = 3        # 高帧自适应每档退避/回升的步长ms
LADDER_PRECISE_MARK_MS = 20       # 高帧下梯子特征白框扫描节流(在识别线程;用户2026-09-15加快30→20≈50Hz,选梯更跟手;CPU有自适应退避兜底)
YOLO_FAST_S = 0.20        # YOLO扫描·找怪档(2026-09-09 CPU优化0.15→0.20=5Hz:cv2.dnn CPU推理是最大头,找怪5Hz仍快;原6.7Hz把整机顶到86%)
YOLO_SLOW_S = 0.30        # YOLO扫描·战斗档(2026-09-09 CPU优化0.22→0.30≈3.3Hz:正打近身怪时3.3Hz够判存活/换目标,配合DNN多线程单次更快)
BARS_SCAN_S = 0.25        # 怪物血条扫描节流(2026-09-09 CPU优化0.20→0.25=4Hz)：判存活4Hz足够,配合出手后130ms反馈窗口
# === CPU性能三档(用户2026-09-11定稿:慢/普通/快,默认普通;控制面板"性能档"弹窗三选一) ===
# 集中收拢原本分散的检测/YOLO/血条/怪模板/上梯高帧/UI帧/边界轮询周期。档定基准,原"按核数自适应+
# 高帧过载退避+每轮最少留3ms"安全网继续兜底,四核弱机误选快也会被退避兜住不会硬吃满一个核。
# 运行中切档:频率类下一轮即时生效;onnx推理线程数重建会话代价大,启动时按档+核数定、下次启动生效。
PERF_DEFAULT_LEVEL = "normal"
PERF_LEVEL_ORDER = ["slow", "normal", "fast"]
PERF_LEVEL_CN = {"slow": "慢", "normal": "普通", "fast": "快"}
PERF_DIALOG_W = 300        # 性能档三选一弹窗宽(UI坐标)
PERF_DIALOG_H = 262        # 高(标题50+三选项120+底部说明)
PERF_PROFILES = {
    # 检测忙/闲周期ms、YOLO找怪/战斗间隔s、血条s、怪模板s、上梯高帧目标周期ms、UI waitKey ms、边界守护轮询ms
    "slow":   dict(detect_busy_ms=180, detect_idle_ms=600, yolo_fast_s=0.32, yolo_slow_s=0.45,
                   bars_s=0.40, feat_s=0.32, precise_ms=30, ui_wait_ms=40, bound_poll_ms=90),
    "normal": dict(detect_busy_ms=120, detect_idle_ms=400, yolo_fast_s=0.20, yolo_slow_s=0.30,
                   bars_s=0.25, feat_s=0.20, precise_ms=24, ui_wait_ms=25, bound_poll_ms=60),
    "fast":   dict(detect_busy_ms=90,  detect_idle_ms=300, yolo_fast_s=0.15, yolo_slow_s=0.22,
                   bars_s=0.20, feat_s=0.15, precise_ms=18, ui_wait_ms=15, bound_poll_ms=50),
}
# 推理线程/频率不在此写死:运行时按性能档+os.cpu_count()定(见_perf_val/_perf_onnx_threads),四核→少线程并自动放慢YOLO帧率,八核→多线程维持跟手
POST_STRIKE_CHECK_MS = 450 # 攻击后反馈检测窗口(用户2026-09-11:130→450)：首次出手满450ms后才看血条/伤害判"打死没/是不是空怪";怪多/特效/掉帧(实测帧率曾掉到1-3fps)时130ms拿不到出手后稳定帧、真怪被当空怪清掉→一圈怪轮流锁左右抖;另须拿到出手之后的新帧才判,避免用出手前旧帧误丢真怪
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
WD_STALL_RECOVER_MAX = 2  # 监管兜底:水平移动连续2个1秒窗口(约2秒,用户2026-09-10"任何卡死不超2秒")判没动→放弃本次跨层回主线重选;第1窗口清键重处理、第2窗口仍不动就放弃,不再拖到3秒
# === 第二层监管·原地左右横跳探测(用户2026-09-11:两个脑子/锁怪在左右怪间横跳→方向快速来回、人原地不动,要拉回正轨) ===
AJ_WIN_MS = 1500           # 横跳观察窗:最近1.5s
AJ_FLIP_MIN = 4            # 窗内左右换向≥4次(来回≥2个回合)才算横跳
AJ_NET_MAP_DX = 15         # 且窗内小地图光点净位移<此值=原地没挪窝(真在走的换向不算)
AJ_TRIG_COOLDOWN = 2500    # 监管置横跳令的冷却,防刷屏/连环拉回
AJ_HOLD_MS = 900           # A级拉回:锁定净一侧900ms(只在这侧选怪/移动),方向唯一不再左右摆
AJ_ESCALATE_MS = 1000      # A级后1s内又横跳→升级B级(完整硬清零重来,用户2026-09-11确认先A后B)
# === 全局2秒总兜底看门狗(用户2026-09-10:不动/卡住/出问题,任何异常状态都不许存在超过2秒→全部清零重新开始) ===
ENABLE_GLOBAL_STALL_FALLBACK = True   # 【总开关·用户2026-09-11确认打开】三层兜底最后一层:前两层没救回、整体无进展才硬清零
GLOBAL_STALL_MS = 3000       # 有任务在身却连续3秒无任一"进展心跳"→总复位(用户2026-09-11由2秒改3秒,给正常动作留余量,减少误重置)
GLOBAL_MOVE_PX = 6           # 屏幕基点累计位移≥此值=在移动(进展)
GLOBAL_MAP_D = 2             # 小地图光点累计位移≥此值=在移动(进展)
GLOBAL_SKILL_HB_MS = 2000    # 最近这么多ms内放过主攻/群攻=站桩输出中(进展,不误判施法站桩)
GLOBAL_RESET_COOLDOWN_MS = 3000  # 总复位后冷却:给重识别/重决策留时间,冷却内不再次复位
# 监管线专用背景运动采样区(用户2026-09-09截图指定)：不能放人物边上(旁边怪动会误判),选远离人物/怪的纯背景。
# 只用【上、右】两块,两块画面同时帧差超阈=人物在正确移动(镜头在滚);单块变化可能是怪/特效/绳索摆动,忽略。整窗坐标(含标题栏)。
WD_BG_REGIONS = [
    {"x": 498, "y": 42, "w": 52, "h": 18},    # 上:顶部天空/吊钩横向带(纯背景无怪,横滚时吊钩/云扫过)
    {"x": 1200, "y": 384, "w": 58, "h": 18},  # 右:右侧岩壁(纹理丰富,横/纵滚变化明显,远离人物与怪群)
]
WD_BG_MOTION_MIN = 2      # 上+右两块必须同时在动,才判定背景在滚=人物真移动(用户:二处同时变化才算)
WD_JUMP_GATE_MS = 1000    # 跳后静默(用户2026-09-09定最简单方案)：起跳后1秒内不做背景帧差(跳跃空中镜头会上下抖,1秒必已落地),落地后再接着对比,不搞离地/落地状态机
# === 打怪区域·小地图边界(用户2026-09-11定稿:左右=手划竖线,上下=点选平台绿线) ===
# 原理:左右边界=用户拖两条竖线(l/r),黄光点越竖线→守护线程发令、主线朝内固定拉回一段;
#      上下边界=用户点两条录制好的平台绿线(第1次点=上限平台top_pf、第2次点=下限平台bot_pf),
#      人物【站在上限平台】禁止再向上跨层/瞬移、【站在下限平台】禁止向下跳/跨层/瞬移(认平台身份,不比Y数值,根治横线防不住)。
#      独立守护线程(_bound_guard_loop)只判左右越线发令,主线唯一移动通道执行(不另开脑子抢键)。
BOUND_POLL_MS = 60          # 守护线程轮询周期(ms):约16帧/s盯光点,跟手又省CPU
BOUND_PULL_MIN_MS = 1000    # 左右越线后朝画面内拉回的持续时长·随机下限(用户2026-09-11定1000~1500ms)
BOUND_PULL_MAX_MS = 1500    # 上限:走够这一段才恢复打怪,天然不会在边上来回碎步
BOUND_RELEASE_MS = 50       # 拉回前清场间隙:停主线后先把左右/攻击键全松这么久,再压朝内键(防松/压同帧被游戏吞=相抵碎步)
BOUND_TP_COOLDOWN_MS = 2000 # 拉回结束后,禁止再朝"刚越线那一侧"水平瞬移的冷却:这期间改走路靠近(走路在R-50站定不会越线;瞬移落点不可控会一步闪回线上→再拉回死循环,用户2026-09-12实锤)
BOUND_DRAG_HIT = 12         # 编辑态鼠标点中左右竖线的命中半径(小地图块像素,放大好按中、治时灵时不灵)
BOUND_PICK_TOL = 8          # 编辑态点选平台绿线的命中容差(点到折线最近距离≤此值=选中该平台,小地图块像素)
BOUND_LINE_W = 3            # 左右竖线粗细基准(px,用户:线粗一点点);UI小地图常态2/编辑3
BOUND_DEFAULT_INSET = 6     # 默认竖线距小地图左右边的内缩(块px):不贴边、肉眼可见
BOUND_FILE = os.path.join(DATA_DIR, "bound_lines.json")  # 边界持久化 {l,r,top_pf,bot_pf}(退出编辑时写、启动懒加载)

# === 战斗瞬移生效校验(用户2026-09-11:台子有距离、有的瞬移不过去;按完键必须核对人物是否真朝该轴位移) ===
TP_VERIFY_MS = 350        # 瞬移后等350ms(给瞬移动作+人物特征重定位时间)再开始校验
TP_VERIFY_TIMEOUT = 800   # 最多等到800ms,仍没朝预期方向位移=本次瞬移无效(被台距/墙挡/没蓝)
TP_MIN_SCREEN_DX = 25     # 水平瞬移有效:人物屏幕X朝预期方向至少变25px(真瞬移远大于此)
TP_MIN_SCREEN_DY = 20     # 竖直瞬移有效:人物屏幕Y朝预期方向至少变20px
TP_FAIL_MAX = 2           # 同一目标连续瞬移无效达2次→暂时对它禁用瞬移,改走路/跳/梯子
TP_BLOCK_MS = 3000        # 对该目标禁用瞬移3秒(绑定目标,换目标自动解除),过后可再试
TP_ATK_RELEASE_MS = 50    # 瞬移前置:先松主攻键再等50ms前摇(本游戏攻击硬直/瞬移前后摇没给够会吞键失效,用户2026-09-11:150→50先试)

# === 梯子特征模板（YOLO前过渡方案，用户2026-09-09定稿：随方案永久存盘，仅上梯近距在主窗口匹配梯子竖条X，辅助精准起跳）===
LADDER_TPL_MAX = 10            # 每方案最多梯子模板数
LADDER_TPL_DEFAULT_SIM = 0.70  # 梯子模板匹配默认相似度
LADDER_TPL_ENTER_PX = 7        # [已不做硬门槛·保留] 用户2026-09-14起小地图粗导航与主窗口屏幕对位同时进行,不再用小地图差≤7卡切换(旧设计切进去已贴脸、越过75跑跳带);屏幕每帧尝试匹配、算到就接管
LADDER_TPL_X_RANGE = 150       # 主窗口搜索X半宽：只朝目标怪所在那一侧扩150(怪在右只搜右/在左只搜左)
LADDER_TPL_Y_NEAR = 20         # Y近人物侧留白(避开人物本体)
LADDER_TPL_Y_FAR = 150         # Y远侧搜索距离(上行搜头顶/下行搜脚下)
LADDER_MARK_SCAN_MS = 250      # 常驻白框:人物周围特征全扫节流(ms),控CPU不每帧匹配
LADDER_MARK_NMS_X = 28         # 特征白框NMS:两命中中心X差≤此值视为同一把梯(合并同梯多峰)
LADDER_MARK_MATCH_X = 32       # 红框(倍率选中,会漂)与白框(特征真实)中心X差≤此值=重合/大约同位置→强制吸附到白框,锁定正确梯子才准起跳(用户2026-09-09)
LADDER_MARK_SIDE_NEUTRAL = 12  # 左右同边判定的中性带(屏幕px):白框离人物这么近视为"正在脚下",不做左右硬删
LADDER_SCR_NUDGE = 35         # 仅下行方式二用:|X差|>35按住朝梯正常走,5~35三次碎步递减,≤LADDER_SCR_TOL(5)才按↓(上行不用它,上行用LADDER_SCR_FAST_PX)
LADDER_SCR_FAST_PX = 100      # 上行分段(用户2026-09-11 22:38改:真机目测离梯70~100起跳都上得去,且补偿主线~110ms一拍的延迟、往远放;主窗口屏幕px,X差按绝对值):>100大步助跑;70~100移动中跑跳;35~70按住趋近;5~35三次碎步修正;≤5原地直跳
LADDER_SCR_TOL = 5            # 屏幕对位最终准入(上下行共用,用户2026-09-10晚:10→5治"10太宽、没碎步贴近就原地跳"):上行|X差|≤5且连续2帧=原地直跳;下行|X差|≤5且连续2帧=按↓下移;5~35必须先走三次碎步贴近
LADDER_SCR_HOLD_FRAMES = 2     # 屏幕对齐连续多少帧才原地直跳
LADDER_SCR_STALL_MS = 700      # 屏幕点动后多久没靠近=想动没动
LADDER_SCR_STALL_MAX = 3       # 想动没动解卡上限,超过回主线重选不死磕
# === 上梯分段(用户2026-09-10晚定稿:先跑跳、跑跳不上再贴脸直跳,全用主窗口屏幕px,目标X用双框吸附稳定值_ladder_snap_x防抖动) ===
# >100按住大步助跑(置running) → 助跑中X差落入70~100【移动中跑跳·第1次起跳】(朝梯键不松按跳,跳完80ms跳键和左右一起松、同时只按住↑,1秒内Y变小=抓住;
#   贴脸X差≈0水平速度为0跑跳跳不上,必须在70~100带速度提前跳,区间已含主线~110ms延迟补偿) → 跑跳没挂上不回主线、留to_ladder,35~70按住正常趋近
# → 5~35【全局唯一允许小碎步处】最多3拍修正对齐(任一拍进≤5下帧直跳,3拍进不了=对不上回主线) → ≤5原地直立跳(第2次起跳,只跳1次)
# === 自适应提前一拍跑跳(治"检测到时还远、真跳已冲到梯底,跑跳从不触发"):按上一周期实测趋近速度v提前一帧,快就早跳、慢就贴近理想点 ===
LADDER_SCR_RUNJUMP_IDEAL = 85    # 理想腾空点≈85(跑跳带70~100中部,用户2026-09-11 22:38:区间改70~100;判据asdx≤IDEAL+v,主线~110ms一拍v大、IDEAL+v可覆盖到上限100,延迟大/速度快自动多提前)
LADDER_SCR_RUNJUMP_TRIG_HI = 100  # 跑跳带上限:X差>100还太远,继续大步助跑不跳(用户2026-09-11 22:38:90→100,真机目测100处带速起跳仍上得去,同时补偿主线~110ms决策延迟)
LADDER_SCR_RUNJUMP_TRIG_LO = 70  # 跑跳带下限:X差<70已贴太近、水平速度不足,不硬跑跳,交按住趋近→碎步→直跳(用户2026-09-11 22:38:65→70)
LADDER_TP_DX = 300          # 向梯水平瞬移阈值(用户2026-09-15):人梯屏幕X差>此值且配了瞬移键/X瞬移距离,先朝梯水平瞬移快速接近;850ms节流(复用战斗瞬移时间戳),闪不成/节流内落段1按住走绝不站等
LADDER_PICK_X_HALF = 300  # 选梯X窗口:只在人物左右300px内选梯,超出不看(用户2026-09-15)
LADDER_PICK_UP_DY = 100   # 上行梯Y窗口:梯中心在[人Y-100,人Y](头顶100内/平行)才算向上的梯
LADDER_PICK_DOWN_DY = 100 # 下行梯Y窗口:梯中心在[人Y,人Y+100](脚底下100内)才算向下的梯
LADDER_RUNJUMP_HI = 80         # 第一次上梯跑跳带上限(用户2026-09-14晚):屏幕人梯X差落入[60,80]、移动中跑跳
LADDER_RUNJUMP_LO = 60         # 跑跳带下限;X差<=60不再跑跳,走直跳路径(按住趋近→三拍碎步对齐→<=5原地直跳);一进屏幕对位就已<=60=直接走直跳,不等跑跳
LADDER_RUNJUMP_HORIZ_REL = 12    # 跑跳腾空后:人梯屏幕X差≤此值松开朝梯水平键、只留↑,防水平惯性把人冲过梯子抓空
LADDER_SCR_STICK_MS = 150        # 屏幕精对齐粘滞:模板偶发丢帧时沿用上一次稳定梯X的最长时间,防状态掉回小地图走到X差0原地直跳
LADDER_MERGE_WAIT_MS = 1500      # 红框(倍率)白框(特征)吸附合并等待上限(用户2026-09-10:必须合并才起跳):进屏幕对位后超过这么久仍没合并=白框没扫到/模板问题,放弃回主线,既不没合并硬跳、也不死等
LADDER_SCR_SLOW_NUDGE = 30     # 碎步区(10~40)内的兜底按键快慢档分界(主用下方递减拍,此处仅_lad_scr_key_hold缺失时兜底)
LADDER_SCR_NUDGE_HOLD_RANGE = (170, 200)  # 碎步三拍·单拍按住时间上限随机区间ms(用户2026-09-10晚定稿:延时统一170-200;定长点动=按住中实时检测,达标/走到步长/按满时间任一满足即抬键)
LADDER_SCR_NUDGE_STEP_PX = (100, 80, 60)  # 碎步三拍·单拍最多一口气移动的屏幕px(用户:第1拍100/第2拍80/第3拍60递减,越近越保守防冲过头;若按住中已实时达标≤TOL则立即抬、不必走满)
LADDER_SCR_NUDGE_GAP_RANGE = (100, 110)  # 每拍【松开后】到下一拍前的停顿时长随机区间ms(用户:中间延时100-110随机,拟人不机械;时序=按住→达标/到步长/到时间抬起→停gap→检测→再按)
LADDER_SCR_NUDGE_HOLD_MS = (100, 60, 40)  # 碎步三拍·每拍按住方向键时长基准ms(用户2026-09-11晚定稿100/60/40递减,原170-200太长对不准;各±JITTER随机)
LADDER_SCR_NUDGE_JITTER = 5               # 每拍按住时长±随机ms(100±5/60±5/40±5,拟人不机械)
LADDER_SCR_NUDGE_MAX_TRIES = 3 # 碎步最多按几拍(用户2026-09-10:首拍150起、每拍×0.75,最多再按3次;3次还没进≤10直跳区=对不上,直接回主线打怪不死磕)
LADDER_SCR_ALIGN_MAX = 35      # 三次碎步修正区上限(用户2026-09-10晚:40→35):|人-梯X差|10~35=碎步对位区,≤10才原地直跳;35以上按住正常走、不碎步
LADDER_SCR_BO_LO = 35          # 按住趋近区下沿(=碎步上限):35<X差≤100没赶上/没跑成跑跳就按住朝梯正常走;≤35进三次碎步
LADDER_SCR_BO_HI = 100         # 按住趋近区上沿(=跑跳带上限,用户2026-09-11 22:38:90→100):跑跳在段2已优先,落这=没合并/没跳成→按住继续趋近
LADDER_SCR_OUT_EXTRA = 50      # 朝梯子外侧(远离梯方向)多退50屏幕px,脱离尴尬区回主线打怪,打完再上梯
RUNJUMP_UP_DELAY_MS = 80       # 跑跳:移动中起跳后多少ms"松掉左右水平键、同时只按住↑"(用户2026-09-11 22:38定稿:50→80,对齐跳键duration=80=跳完那一刻;新动作=方向键不松按跳→跳完跳键和左右一起松→同时只按↑不松,靠起跳惯性滑到梯位抓梯,不再空中持续按水平趋近)
RUNJUMP_GRAB_WINDOW_MS = 1000  # 跑跳抓梯硬上限(用户2026-09-10:按住↑给足1秒再判成败,600→1000,提高上梯成功率);成功靠Y变小实时触发、不用等满
RUNJUMP_GRAB_FAIL_MIN_MS = 1000 # 跑跳起跳后至少这么久才允许用"Y落回起跳高度"判失败(用户2026-09-10:一直按住超过1秒再判,300→1000,避免上升/贴梯途中误判失败)
LADDER_NUDGE_KEY_SMALL_MS = 38 # ≤35超慢挪时一次点动的按键ms(2026-09-10:28→38,单次多挪一点、减少一抽一抽的碎片感;仍短于按住冲过中线)

# === 爬梯登顶·绑定人物基点的三背景点（用户2026-09-09定稿，替代小地图Y对梯端/人怪同Y对比）===
# 三个采样小框固定在人物基点的 右上/右下/左下，随人物一起移动，测"人物相对地图背景有没有动"，与镜头如何滚动无关。
# 静止判据(用户定稿,抗怪物/特效干扰)：三个有效点里【只要有一个确认不动】就算人物本帧静止；只有三个点全部在动才算还在爬。
# 连续静止 CLIMB_STILL_MS=一直按↑却上不去、停在顶=登顶。收边clamp保证人物贴屏幕边时点也不出屏(收回贴人物另一侧)，
# 三点强制分离+尽量躲开怪物框，避免叠一处/同时罩到同一只怪，保证总有一个干净背景点可判静止。
CLIMB_BOX_RADIUS = 150         # 采样点中心距人物基点的理想距离
CLIMB_BOX_SIZE = 26            # 采样框边长(小框,尽量纯背景)
CLIMB_VSEARCH_R = 5           # 垂直运动分解:行投影上下搜索半径px(覆盖低帧率两帧间纵向位移)
CLIMB_VMOTION_RATIO = 0.35    # 纵向对齐至少消掉35%零位残差才算"真在上下爬";被怪横向撞时纵向对不齐、比值≈0→按垂直静止不挡到顶
CLIMB_BOX_SEP_MIN = 60         # 任意两采样点中心最小间距(曼哈顿距离,防收回后叠一处)
CLIMB_STILL_MS = 200           # 第二步:确认"真的在爬"后,背景点连续静止多久=到顶/到底(2026-09-10再提效300→200:垂直运动分解后被横向撞不误判,200ms足够确认停稳,到顶更快)
CLIMB_TOP_HOLD_MS = 300        # 阶段1主窗口Y到记录高度后,再多按住方向键300ms确保翻上不平台面,再核对小地图梯端(用户2026-09-11晚:150→300,台子不平)
CLIMB_CONFIRM_FALLBACK_MS = 1500 # 第一步"确认在爬"兜底:抓住后背景点和人物Y都没识别到动时,最多1500ms也强制进入第二步到顶判定(治检测失灵→人到顶却干等12s总超时;按住↑1.5s不可能还在原地)
CLIMB_REAL_MOVE_PX = 8         # 到顶硬门槛(用户2026-09-10治"人没动却假到顶"):抓住后光点Y必须相对抓住基准真移动≥8px(上=变小/下=变大),背景静止/光点停止信号才准判到顶;没真移动=假抓住
CLIMB_FAKE_GRAB_MS = 2000      # 假抓住失败:抓住满2000ms,但"背景从没动过 且 Y从没真移动"双通道都否定=根本没爬上,按抓梯失败回主线,绝不判到顶/不触发到达清锁(略晚于1500确认兜底,给检测留时间)
CLIMB_TARGET_Y_TOL = 20        # 阶段1主窗口到顶容差:人物基点Y与抓住时冻结记录点Y差≤20=爬到记录层高度(用户2026-09-11晚:台子不平不要求重合,5→20)
CLIMB_YSTOP_MS = 200           # 快速到顶信号B:确认在爬后小地图光点Y连续200ms不再创新低(停止上升)=到顶(世界坐标,背景法失灵/锁的是背景时的保险)
CLIMB_TOTAL_TIMEOUT_MS = 12000 # 爬梯总超时兜底(防异常永久卡),到点按到顶收尾
ARRIVAL_RESET_COOLDOWN_MS = 500 # 到顶/落地/走台"到达新平台"重扫冷却(2026-09-10再提效1200→500:到顶发呆主因之一;两次真实换台必>500ms仍挡得住"到达连发→清空重锁左右横跳",又能更快重锁本层怪)
ARRIVAL_EMPTY_MAX = 3          # 走台"终点就在身边、根本没真移动却判到达"的连续次数上限:超了强制留本层正常打怪、短时间不再cross空转(用户:每个执行机制都要有次数上限,不许无限循环)
FIGHT_BACK_HOLD_MS = 700       # 走向梯子(未起跳)时发现本层怪→弃梯回打怪后的防抖窗:窗内不重启cross走梯,给本层重扫/锁怪稳定时间,防cross↔战斗临界逐帧抖(用户2026-09-10三步走)
# 【用户2026-09-09定稿】跳高打（怪比人高时，屏幕像素PX）——区间在"技能Y范围"弹窗最下一行两个框自定义：
#   下限~上限(如25~180)两个都填才启用：怪比人高落在[下限,上限]内 且 X差≤300 → 直接朝怪"走-跳-打"，每500~600ms跳一次(不连跳)，
#   两次跳之间落地空档能打到就站定攻击，【不去找梯子】；比上限还高(>上限)的怪不跳不打，对接正常锁定流程——锁到别的层就走梯子/瞬移上去打；
#   比下限还低(<下限)=当平地正常走打。两个框任一留空=不启用跳高打，高处怪一律走正常跨层(梯子/瞬移)。
#   射程外追怪段只朝怪正常走、不跳（用户：不在300px内不用跳）。跳打出手一次后无血条无伤害=当前位置够不着→放弃这只、降级走梯子/瞬移。
# 用户2026-09-09：不做预验证/二次验证(那会和"重锁→还打不到→再验证"形成死区)；打不打得到以"出手后有无血条/伤害数字"为准。
SLOPE_JUMP_X_MAX = 300     # 跳高打·旧水平距离上限(已弃用:用户2026-09-09改为X差≤面板技能射程atk1_distance才跳,战法一致;常量保留备用)
SLOPE_AIR_MS = 360         # 一次跳跃腾空时长ms(战士再跳基准:落地后才再跳,防空中连跳)
# 【用户2026-09-10晚·跳高打大幅简化】填值即开、不分群攻/就近,只分战法,起跳时一次性算好本跳攻击/下次跳时刻:
SLOPE_WAR_HIT_MIN = 80     # 战士(不勾法师·空中可打):起跳后主攻时刻随机下限ms(用户2026-09-11:120~150→80~100,更快出手)
SLOPE_WAR_HIT_MAX = 100    # 战士:起跳后主攻时刻随机上限ms(80~100随机打一下,不管空档/攻击间隔)
SLOPE_WAR_REJUMP_MIN = 700 # 战士(极简循环):主攻后再等700~850ms才起跳下一跳(用户2026-09-11:450~550→700~850,落地站稳再跳)
SLOPE_WAR_REJUMP_MAX = 850 # 战士:主攻后→下一跳延时随机上限ms
SLOPE_MAGE_HIT_MS = 1000   # 法师(空中放不出技能):起跳后1000ms(已落地)才主攻
SLOPE_MAGE_NEXT_MS = 1000  # 法师:主攻后再过1000ms才再跑跳
SLOPE_MAGE_JITTER = 50     # 法师上述两个时间节点各±50ms随机
CHAR_EDGE_MARGIN = 45     # 地图左右边缘区：人物脚X距画面边≤此值且特征匹配丢失=贴边,钳在边缘并标stale(不误判防卡),等全图重定位
GREEN_SLOPE_LOOK = 15     # 到坡脚触发前视窗口(小地图px,用户2026-09-14定稿"刚好要上坡才跳":45→15,1小地图px≈10屏幕px→约150屏幕px=2~3个身位,到坡脚跟前才起跳,不离坡老远空跳)
GREEN_SLOPE_MIN = 5       # 绿线Y波动>5px才算坡(用户2026-09-14口径:6→5)：低向高(上坡)向前跑+跳,高向低(下坡)只走不跳；≤5当平地正常走
DETECT_IDLE_MS = 400      # 自适应降频(2026-09-09提效700→400)：无怪/非战斗400ms≈2.5Hz,别睡太死,见到怪0.4s内回到DETECT_PERIOD_MS快周期跟手
LAYER_Y_GAP = 150         # 用户2026-09-05：怪脚Y与人物Y差≤150px=同平台怪（超150=跨层/不同平台）；简单直接不靠绿线
ATTACK_Y_UP = 60         # 打怪Y范围·向上：怪比人物高最多60px(人物上方+60内可直打；>60够不着→走近)。用户2026-09-06：80→60
ATTACK_Y_DOWN = 30       # 打怪Y范围·向下：怪比人物低最多30px(人物下方-30内可直打；>30够不着→走近)
AOE_Y_UP = 60            # 群攻Y范围·向上(用户2026-09-07独立于主攻,默认与主攻一致-60)：群攻只数Y在[-上,+下]内的怪,可在Y弹窗改
AOE_Y_DOWN = 30          # 群攻Y范围·向下(默认+30,用户2026-09-07)：下层差太多打不到的怪不许凑数触发群攻
# === 跨层选梯/爬梯常量（2026-09-07跨层改造，2026-09-09选梯严格重合定稿）===
LADDER_REACH_HEIGHT = 15   # 选梯·下端直跳够得着：人物比梯子下端y_bottom低不超过此值=一个直跳能抓到梯子(用户定稿默认15)
LADDER_END_MATCH_TOL = 1    # 选梯·梯子连接端(上行顶端/下行底端)必须和目标怪所在层Y重合的容差(小地图px,用户2026-09-09定稿:
# 必须重合、最多±1,差多了就是通向别的层会误判(在错梯下空跳);一个台子最多两个梯相连,相连梯顶端Y和怪重合,合格梯里再按离怪X最近选
LADDER_TOP_ARRIVE_TOL = 1  # 爬梯到顶验证(用户2026-09-11晚)：光点与梯顶重合或高于梯顶即到,容差只留1px当检测误差；
# 且用"到达/越过"单向判定(上行 py<=y_top+2),人还在顶端下方(差>2)绝不判到顶——旧版abs≤8会提前8px松手导致没翻上平台就掉下
LADDER_TOP_HOLD_MS = 200    # 到顶多按(用户2026-09-15):光点与录制梯端完全重合后,继续按住↑/↓200ms再松,确保整个人翻上台/踩稳
LADDER_GRAB_UP_TOL = 2       # 抓梯成功阈值(镜头滚动原理·用户2026-09-09)：光点Y相对【起跳前站地基准Y】变小≥此值=抓住；只比动作前稳态,不做相邻帧比较
LADDER_GRAB_WINDOW_MS = 1000  # 直跳抓梯硬上限(用户2026-09-10:按住↑给足1秒再判成败,450→1000提高上梯成功率);成功靠Y变小实时触发、不用等满
LADDER_GRAB_FAIL_MIN_MS = 1000 # 直跳起跳后至少这么久才允许"Y落回起跳=没抓住"判失败(用户2026-09-10:一直按住超过1秒再判,220→1000,避免上升/贴梯途中误判)
LADDER_FAIL_REENTER_MS = 120  # 抓梯失败回主线后的极短冷却(2026-09-10替代原随机300~500:防同帧立刻又选同一梯空跳,又不发呆;本层有怪会被先锁去打)
# === 梯子【失败集合】校准(用户2026-09-14定稿:直跳没抓住不回主线,最多3轮"朝梯移动当前剩余距离70%→停下→检测,达标就直跳";
#   任一直跳后Y变小=抓住→接上梯集合、剩余轮次作废;3轮移动后仍没抓住→重新算怪距回主线打怪。移动用主窗口梯子屏幕X,和正常直跳同口径) ===
LADDER_REALIGN_MAX_ROUNDS = 3     # 失败集合最多移动几轮(每轮=走剩余70%→停→检测→达标直跳)
LADDER_REALIGN_RATIO = 0.70       # 每轮朝梯移动"本轮开始时剩余屏幕X差"的70%(离得远首轮多走,不碎步)
LADDER_REALIGN_MIN_STEP = 6       # 单轮最少移动屏幕px(剩余太小时也保证真的挪一点,不会原地空转)
LADDER_REALIGN_MOVE_CAP_MS = 320  # 单轮按住朝梯方向键的时长上限(实时走到本轮步长即提前抬键;防走过头/卡住死按)
LADDER_REALIGN_GAP_MIN = 90       # 抬键后停顿时长随机下限ms(停稳再检测新距离)
LADDER_REALIGN_GAP_MAX = 140      # 抬键后停顿时长随机上限ms
LADDER_REALIGN_TOL = 5            # 达标=屏幕|人-梯X差|≤此值(复用LADDER_SCR_TOL口径5px)
LADDER_REALIGN_HOLD_FRAMES = 2    # 达标需连续帧数(防抖,和正常屏幕直跳一致)
LADDER_REALIGN_NO_TPL_MS = 1200   # 失败集合里连续多久拿不到梯子屏幕X(无模板/匹配不到)=回主线,不死等
# === 梯子水平对齐·精细点动(用户2026-09-09定稿)：远距正常走,进3px内才1~2px点动挪到重合,关键动作(直跳)必须过准入标准 ===
LADDER_ALIGN_FINE = 3        # |小地图X差|≤3进入精细点动区(>3仍正常按住方向走,像人不磨叽)
LADDER_ALIGN_TOL = 1         # 直跳准入硬标准:|X差|必须≤1(用户:小于2、不等于2;杜绝2.x边界没对齐就跳)
LADDER_ALIGN_HOLD_FRAMES = 2 # 连续2帧都≤1才算停稳对准(防光点抖动/滑过误判),达到才允许原地直跳
LADDER_NUDGE_KEY_MS = 52     # 点动一次方向键保持ms(非阻塞跨帧抬起,2026-09-10:45→52略增单次位移,动作更连贯)
LADDER_NUDGE_CYCLE_MS = 150  # 点动节拍:每150ms最多点一下(2026-09-10:200→150缩短抬键停顿,减少肉眼可见的小碎片/抽动感),节拍间隔用来观测"到底动没动"
LADDER_ALIGN_STALL_MS = 600  # 精细区"指令朝梯走但X一直没靠近"持续这么久=想动没动(卡住)
LADDER_ALIGN_STALL_MAX = 3   # 卡住解卡尝试上限:每次先全松再干净重点,超过仍不动=这把梯对不齐,回主线重选/打怪不死磕
LADDER_VERT_FAIL_LIMIT = 2    # 原地直跳抓梯连续失败上限(用户2026-09-09)：<2对齐直跳连续2次没抓住→退开120~150屏幕px回主线打怪,打完再自动上梯(固定点6跑跳失败不计入)
LADDER_BACKOFF_MIN = 120      # 直跳2次失败后远离梯子的屏幕位移下限(px)
LADDER_BACKOFF_MAX = 150      # 上限(px)：退开120~150再正常选梯上
LADDER_BACKOFF_TIMEOUT_MS = 4000  # 退开兜底超时：屏幕定位异常/被挡住时最多横走4秒强制结束,避免一直走
JUMP_DOWN_LAND_STABLE_MS = 180   # 下跳落地判定(2026-09-10收紧250→180,治到底后↓多按扑倒)：开始下落后光点Y连续180ms不再增大(≤3px抖动)=落到台子,立刻松↓
JUMP_DOWN_LAND_TIMEOUT_MS = 1500 # 下跳总兜底：补跳后最多1500ms强制按落地收尾,防大落差一直观测不到稳定而干等
JUMP_DOWN_HOLD_BEFORE_JUMP_MS = 150 # 下跳时序(用户2026-09-09最新)：松攻击/左右→按住↓150ms采到"向下"→按跳→跳后立刻松↓(自由落体不长按,真人化)
# === 下行 descend 状态机(用户2026-09-10最终定稿:只留两种下跳方式;不找口子/不走边缘,原地直接跳,动作先做完整、事后一次判Y)===
# 方式一 first_jump:压↓100ms→第一跳(下穿台)→松↓→随机左/右按100ms→第二跳(左右跳、跳前记人物特征基准Y)→松左右
#   →check_drop固定DESC_DROP_CHECK_MS后一次性比"人物特征Y比左右跳前增大≥DESC_DROP_DY=10"(屏幕特征Y或小地图世界Y任一)=真下去→fall自由落体(背景静止/Y稳定=落地);
#   没增大=这位置直接跳不下去→转方式二找梯子(不在动作执行中途判失败,避免小光点闪断误判"跳不了")。
# 方式二(直接跳不了才用)·两段对位:to_ladder小地图走到梯X对齐光点中心|差|≤5(同拍进30Hz高帧)→lad_scr切主窗口用人物特征对齐"红框白框二合一白框",
#   >50按住趋近、10~50碎步三拍递减(150→×0.75,最多3拍、流利不停)、≤10且双框合并连续2帧=对齐→lad_grab按住↓观察500ms,Y变大=抓住
#   →lad_slide继续按↓1秒→lad_leap松↓随机侧100+跳离梯→lad_fall_wait固定1秒回主线;lad_grab满500 Y没变=抓不住回主线,不补跳不死磕。
DESC_LAD_ALIGN_TOL = 5         # 方式二·段1:小地图梯X对齐人物光点中心,|差|≤5即切主窗口精对位+同拍进30Hz高帧(和上行≤7同款;2→5放宽求稳,小地图px)
DESC_GOTO_STALL_MS = 600       # 段1朝梯走但连续600ms没靠近=被边挡住,直接切主窗口段(用特征兜底对位)
DESC_DROP_CHECK_MS = 300       # 方式一:两跳后最早开始判Y增大的时刻(此前是跳跃上升期,不判,防噪声)
DESC_DROP_WAIT_MAX_MS = 900    # 方式一:两跳后观察窗上限——窗内任一人Y往下增大达标=跳下成功立刻自由落体;到900ms仍纹丝不动=实心台真跳不下去,这才转方式二对齐梯子(用户2026-09-10:直接跳任意位置、别动不动就对齐梯子)
DESC_DROP_DY = 25              # 方式一·主窗口:人物特征屏幕Y比"左右跳之前"增大≥25=确实穿到下一层(用户2026-09-10:向下不用像向上那么精,10→25放宽,只掉几px的原地小跳不算)
DESC_DROP_DY_MAP = 8           # 方式一·小地图:世界Y增大≥8也算(小地图1px≈主窗口~10px,8≈屏幕80px真实落差;与屏幕Y取或,抗镜头跟随/光点抖动)
DESC_DIRECT_DOWN_HOLD_MS = 100 # 方式一:第一跳(下穿台)前按住↓100ms(用户2026-09-10:压住↓100ms再跳)
DESC_DIRECT_SIDE_MS = 100      # 方式一:第一跳松↓后,随机左/右方向键按100ms再按第二跳(左右跳离台),随即松左右
DESC_LAD_GRAB_MS = 500         # 方式二:梯位按住↓观察500ms,期间Y变大=抓住梯子开始下滑
DESC_LAD_SLIDE_MS = 1000       # 方式二:抓住后继续按住↓下滑1秒(用户:有变大就再按一秒)
DESC_LAD_LEAP_SIDE_MS = 100    # 方式二:侧跳离梯前随机左/右方向键按压100ms
DESC_LAD_FALL_WAIT_MS = 1000   # 方式二:侧跳离梯后固定等1000ms直接开主线打怪(不再判背景、不沿梯到底)
DESC_Y_MOVE_TOL = 5            # 方式二lad_grab:光点Y比基准增大>5=抓住梯子向下动了
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
                # [2026-09-14 根因修复·A:重启后录制线与光点错开] 启动优先读回上次保存的小地图裁剪框,
                # 与录制时严格保持同一块内像素坐标系;读不到(首次/文件丢失)才三模板自动检测。
                # 旧逻辑每次启动都_detect_minimap重算,三模板整数匹配帧间抖1~3px,而录制线/梯子是块内绝对
                # 像素坐标,重启后裁剪框原点一抖旧线就整体错开(运行中因8px锁定不抖,故"刚录对、重启后错")。
                # 兜底:运行期debug=False定时/丢光重定位仍在,与读回基准差≤8px锁定不动、真变>8px才更新。
                if not self._load_region():
                    self._detect_minimap()  # 无保存区域时才自动检测，避免显示窗口变小
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
        self._char_feature_window = None  # 人物特征管理弹窗(旧小块特征,已旁路保留可回滚)
        # === 角色识别(2026-09-13):全局锚点+跟踪参数,启动直接加载、重采才覆盖,不随地图方案变 ===
        self._role_rec_window = None   # 「角色识别」tk管理窗引用
        self._role_rec = None          # 角色识别数据 {anchors:{key:{file,poly,off_x,off_y}}, params:{...}}
        self._load_role_recognize()    # 启动即加载(无文件则给默认空壳)
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
        # === CPU性能三档(用户2026-09-11):慢/普通/快,小地图"打怪区"下方"性能档"按钮弹窗三选一 ===
        self._perf_level = self._load_perf_level()   # 当前档slow/normal/fast(读data/perf_config.json,缺省normal)
        self._perf_cache = None                      # 当前档参数缓存(切档清空,热路径直接取、零重复查表)
        self._btn_perf = None                        # 小地图"性能档"按钮矩形(每帧draw更新供点击命中)
        self._show_perf_dialog = False               # 是否显示性能档三选一弹窗
        self._perf_dialog_pos = [70, 210]            # 弹窗位置(可拖标题栏移动)
        self._perf_dialog_dragging = False
        self._perf_dialog_drag_offset = [0, 0]
        self._dlg_perf_close = (0, 0, 0, 0)          # 弹窗右上角X(必须初始化,否则首开点击None解包崩)
        self._dlg_perf_opt = {"slow": (0, 0, 0, 0), "normal": (0, 0, 0, 0), "fast": (0, 0, 0, 0)}  # 三选项条
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
        self._combat_last_h_teleport = 0          # 上次战斗瞬移时间(水平/竖直共用850ms节流,追怪用)
        # 瞬移后人物会合法地大跳变几百px，此时间戳之前跳过ROI直接全图搜、并允许远距同步新位置(治瞬移后点钉原地)
        self._char_relocate_until = 0
        # 战斗瞬移生效校验(用户2026-09-11):发起后记前坐标,350~800ms内核对该轴是否真位移;连续无效则对该目标暂停瞬移
        self._combat_tp_pending = None            # 待校验 {axis:'x'/'y',dir:±1,sx,sy,t,key:(cx,cy)}
        self._combat_tp_fail_key = None           # 累计失败对应的目标键(锁定坐标),换目标自动重新计
        self._combat_tp_fail_cnt = 0              # 该目标连续瞬移无效次数
        self._combat_tp_block_until = 0           # 对该目标禁用瞬移到的时间戳(ms)
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
        self._yolo_sess = None  # onnxruntime推理会话(优先;cv2.dnn算错新版ultralytics导出模型,2026-09-10)
        self._yolo_backend = None  # 推理后端:'ort'=onnxruntime / 'cv2'=cv2.dnn兜底
        self._yolo_iname = "images"  # onnxruntime输入张量名
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._arrival_relock_until = 0  # 到顶重识别保护期截止(ms)：此前不拿旧怪表判cross往下走(用户2026-09-09)
        self._last_yolo_check = 0
        self._yolo_conf = 0.5   # YOLO置信度(用户2026-09-05：0.6→0.5，多检出一些怪)
        self._yolo_nms = 0.45
        # YOLO怪物检测
        self._yolo_net = None
        self._yolo_sess = None  # onnxruntime推理会话(优先;cv2.dnn算错新版ultralytics导出模型,2026-09-10)
        self._yolo_backend = None  # 推理后端:'ort'=onnxruntime / 'cv2'=cv2.dnn兜底
        self._yolo_iname = "images"  # onnxruntime输入张量名
        self._monsters = []  # [(x1,y1,x2,y2,score), ...]
        self._last_yolo_check = 0
        self._yolo_conf = 0.5   # YOLO置信度(用户2026-09-05：0.6→0.5，多检出一些怪)
        self._yolo_nms = 0.45
        # BUFF/药品冷却状态（启动后生效）
        self._buff_last = {}  # buffN_key -> 上次释放时间戳
        self._potion_last = {}  # potionN_key -> 上次释放时间戳
        self._attack_last = {}  # atk1/aoe -> 上次释放时间戳
        self._player_screen_pos = None  # (x,y) 人物画面坐标
        self._role_track = None         # 新多锚点跟踪状态:last锚点/foot脚点/miss失配/last_full全图时间/face朝向/score
        self._role_face = None          # 面部锚点判定的朝向 'L'/'R'(打怪左右决策用)
        self._role_anchor_polys = {}    # 本帧识别到(过阈)的各锚点缩小多边形{key:([(x,y)...],score)},供蒙板画框
        self._role_search_box = None    # 本帧局部跟踪搜索范围框(x0,y0,x1,y1);全图重搜时=None(不画)
        # === 梯子特征模板（随方案永久存盘，内存仅为运行时副本，权威在 data/route_xxx_ladder_tpl.json）===
        self._ladder_templates = []     # [{id,img,width,height}]
        self._ladder_tpl_sim = LADDER_TPL_DEFAULT_SIM
        # === 梯子检测双通道(用户2026-09-10):有梯子YOLO模型(ladder.onnx)用YOLO,没有自动回退上面的特征模板(以图识图);
        # 两个入口(_match_ladder_screen_x近距选一把/_scan_ladder_marks常驻全扫)内部按后端自动分流,上层对齐/起跳只拿梯子中心X,不感知来源 ===
        self._ladder_yolo_model_path = None  # 预留:可手动指定梯子模型;空则自动找根目录/data下的ladder.onnx
        self._ladder_yolo_net = None         # cv2.dnn会话(兜底后端)
        self._ladder_yolo_sess = None        # onnxruntime会话(优先后端)
        self._ladder_yolo_backend = None     # 'ort'/'cv2'/None=没模型
        self._ladder_yolo_iname = "images"
        self._ladder_yolo_input = 416        # 梯子模型输入边长(自动读模型,默认416小模型减负)
        self._ladder_yolo_inited = False     # 是否已尝试过加载(懒加载,全程只找一次文件,不每帧IO)
        self._ladder_backend = 'template'    # 实际生效来源:'yolo'=有模型 / 'template'=以图识图
        self._ladder_yolo_conf = 0.5
        self._ladder_yolo_nms = 0.45
        self._ladder_yolo_class_id = 0     # "梯子"标签对应的类别id(读类别表按名解析,无类别表默认0)
        self._ladder_yolo_threads = None   # 梯子推理CPU线程数(懒加载时按核数定)
        self._ladder_tpl_matches = []   # 最近梯子模板匹配候选(调试/蒙板显示)
        self._ladder_tpl_dbg = None     # 最近一次主窗口梯子匹配调试信息{roi,cands,best,ppx,sim,t}(蒙板白竖线/识别不到红框,用户2026-09-09)
        self._ladder_feature_window = None  # 梯子特征管理弹窗
        # 主窗口梯子模板"屏幕X精对齐"状态（每次爬梯由_reset_climb清零）
        self._lad_scr_ok_frames = 0
        self._lad_scr_key_vk = None
        self._lad_scr_key_t = 0
        self._lad_scr_nudge_t = 0
        self._lad_scr_ref_spx = None
        self._lad_scr_stall_t = 0
        self._lad_scr_stall_n = 0
        self._lad_scr_nudge_n = 0
        self._lad_scr_key_hold = 0
        self._lad_scr_nudge_step = 0      # 定长点动·当前拍位移上限px(0=非点动拍)
        self._lad_scr_nudge_from_x = None # 定长点动·当前拍起点屏幕X
        self._lad_scr_nudge_gap = 100     # 定长点动·抬起后停顿ms
        # 登顶三背景点状态（右上/右下/左下，随人物基点移动）
        self._climb_box_prev = [None, None, None]      # 三点上一帧纹理
        self._climb_box_centers = [None, None, None]   # 三点上一帧中心(锚点突变时本帧只建基准不判动)
        self._climb_still_since = 0                    # 存在静止点的连续起始时刻(0=三点都在动)
        self._climb_move_confirmed = False             # 两步法第一步:是否已确认"真的在爬"(三背景点至少出现过一次在动);未确认前静止=起步,不判到顶
        self._climb_y_align_since = 0                  # 快速到顶信号A:人怪主窗口Y对齐起始时刻
        self._climb_min_y = 0                          # 快速到顶信号B:爬梯中光点达到的最小Y(最高处)
        self._climb_ever_moved = False                 # 到顶硬门槛锁存:抓住后任一阵"背景在动或Y真移动"即True(不可逆),没动过=假抓住不准到顶
        self._climb_ystop_since = 0                    # 快速到顶信号B:光点Y停止上升起始时刻
        self._char_match_ok = False     # 本帧人物特征是否匹配成功
        self._char_lost_edge = None     # 特征丢失时位置：'left'/'right'贴地图边 / None=中间或正常
        # === 打怪区域·小地图边界(用户2026-09-11:左右=手划竖线,上下=点选平台绿线定上下限) ===
        self._bound_lines = None        # 左右竖线·小地图块像素坐标 {'l','r'};None=尚未初始化(首次按小地图尺寸给默认)
        self._bound_from_file = False   # 边界是否来自用户存盘:True=用户设置(只钳不重置),False=默认铺满当前小地图
        # Y上下限=两条"界线",每条界线由用户点选的多个相连台子合并而成(同高度分多次录的线可并成一条)
        self._bound_staging = []        # 编辑态暂存区:已点选但还没按回车成形的台子id列表(再点已选=取消)
        self._bound_grpA = []           # 第1次回车成形的界线(台子id列表)
        self._bound_grpB = []           # 第2次回车成形的界线(台子id列表)
        self._bound_top_grp = []        # 最终Y上限组(两条里平均Y小者);空=未设=不拦向上
        self._bound_bot_grp = []        # 最终Y下限组(两条里平均Y大者);空=未设=不拦向下
        self._bound_edit = False        # 编辑态:True="打怪区域"按钮变绿、可拖左右竖线+点绿线选上下限;False=常态灰、守护生效
        self._bound_drag = None         # UI小地图上正在拖动哪条竖线 'l'/'r'/None
        self._bound_guard_side = None   # 守护线程→主线·左右越线令:None/'left'(越左竖线,需朝右拉回)/'right'(越右竖线,需朝左拉回)
        self._bound_pull = None         # 主线左右拉回进行中 {dir,until}/None:触发后固定朝内走1000~1500ms,到时恢复打怪(不碎步)
        self._bound_last_side = None    # 最近一次越线拉回的侧 'left'/'right'/None(冷却期内禁朝这侧水平瞬移)
        self._bound_tp_block_until = 0  # 朝_bound_last_side水平瞬移的冷却截止ms(拉回结束起BOUND_TP_COOLDOWN_MS)
        self._bound_thread = None       # 边界守护线程句柄
        self._bound_running = False     # 边界守护线程运行标志
        self._btn_bound_area = None     # UI小地图区"打怪区域"切换按钮矩形(每帧draw更新供点击命中)
        self._bound_clear_menu = None   # 右键Y界线→"清除"气泡 {'which':'A'/'B','mx','my'(块坐标),'rect'(显示空间命中框,每帧刷新)}
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
        self._aux_enable_fall = False      # 掉台归位线(_fall_return_tick)
        self._aux_enable_unblock = False   # 卡住解卡线(_unblock_tick)；同时门控主线内_check_move_blocked登记,避免主线自我挂起
        self._aux_enable_retreat = False   # 主线内"平台边界回退"段(到绿线边缘往回走+小跳并整帧return,会抢占锁怪打怪)
        self._aux_enable_rest = False      # 主线内"拟人周期小休"段(5~8分钟停5~10秒,期间完全不动不打)
        # === 移动监管线 watchdog(用户2026-09-09三线模型:主线/监管线/辅助线) ===
        # 独立后台线程,只监测不发键;v1观察版只打行为日志(异常红字),不挂起主线、不执行修复。
        self._wd_lock = threading.RLock()  # 监管状态锁:用可重入RLock(同线程嵌套acquire不自死锁,跨线程仍互斥);监管线程判停滞/主线按键对账都要抢它,曾因锁内嵌套with导致整UI未响应
        self._mv_intent = {}               # 当前移动意图 {'x':intent,'y':intent},水平/垂直独立记账可同时存在;intent=dict{dir,src,seg_t,seg_x,seg_y,reported...}
        self._wd_thread = None             # 监管线程句柄
        self._wd_running = False           # 监管线程运行标志
        self._wd_log_last = {}             # 同类监管日志去重 {key:t}
        self._wd_bg_last = [None, None]  # 监管线独立的上/右两块上一帧ROI(与原镜头检测_bg_last_frames分开,互不干扰绿框)
        self._wd_jump_gate_until = 0     # 跳后静默截止时间戳(ms)：此前不做背景帧差(起跳时在_press_game_key置,1秒必落地)
        self._wd_stall_req = None        # 监管线程→主线的"水平停滞重处理"请求{axis,dir,t,win};主线每帧consume,跨线程只经_wd_lock传递(线程本身绝不发键)
        self._wd_recover_cnt = 0         # 同一移动段连续停滞重处理次数(真动了清零);累计到WD_STALL_RECOVER_MAX放弃本次跨层回主线
        self._wd_recover_seg = None      # 上轮重处理对应的意图段标识(方向);换向/重新规划自动清零计数
        # === 监管线掌控的跨线程硬重置(用户2026-09-10)：监管线程独立轮询实时发现卡死,不等主线串行跑完(慢几拍) ===
        self._hard_reset_req = None     # 监管线程→主线帧首的硬重置令{reason,t}(经_wd_lock传递)；监管实时发令、主线帧首统一清零
        self._hard_reset_last_t = 0.0   # 监管侧上次发令时间(ms)，GLOBAL_RESET_COOLDOWN_MS冷却内不重复发，防连环重置刷屏
        # 横跳探测(第二层监管):_wd_x_flips=主线登记的X换向[(t,小地图X)];_wd_antijitter_req=线程→主线拉回令;
        # _aj_hold_side=主线A级锁侧态{dir:±1,until};_aj_stage/last=A→B升级计数
        self._wd_x_flips = []
        self._wd_antijitter_req = None
        self._aj_hold_side = None
        self._aj_stage = 0
        self._aj_last_trigger_t = 0.0
        self._wd_aj_last_req = 0.0     # 监管侧上次置横跳令时间(AJ_TRIG_COOLDOWN节流)
        self._detect_reset_seq = 0      # 检测线程自清版本号：主线硬重置时+1，检测线程循环顶部见新版本就清跨帧怪表缓存并立即全量重扫
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
        self._last_arrival_reset_t = 0     # 上次"到达新平台重扫"时刻(冷却去重,治到达连发→左右小碎步)
        self._arrival_empty_streak = 0     # 走台没真移动却判到达的连续次数(上限ARRIVAL_EMPTY_MAX)
        self._transit_walk_from = None     # 本次走台启动时人物小地图坐标(判是否真移动过一段)
        self._no_transit_until = 0         # 空转达上限后强制本层打怪、暂不cross的截止时刻ms
        self._combat_timed_keys = []       # 定时释放的按键 [(vk, release_ms)]（仅用于短按转身）
        self._combat_last_target_pos = None  # 上一次攻击目标位置(x,y)，用于近战挡身体时搜血条
        self._combat_held_keys = set()     # 持续按住的方向键（流畅移动用）
        self._combat_move_dir = None       # 当前持续移动方向 "left"/"right"/None
        self._combat_locked_target = None  # 锁定的目标 (cx, cy)，打死才换，不中途切换
        self._ladder_target_mon_x = None  # 进上梯集合时冻结的目标怪屏幕X(关怪扫后锁定怪会清空,选梯/找梯以它为固定终点参照)
        self._combat_lock_tier = None      # 锁定类别 in=技能范围内/out=同层范围外/cross=跨层(两类锁怪维持依据,每帧由决策回存)
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
        # 【跨层=锁定梯子·用户2026-09-11定稿】不再锚定上层怪的空坐标(怪会空/脱检/刷新,易出bug):
        # 目标是"上到那一层"而非某只怪——锁梯那一下用当前怪(怪→梯→人)选出正确梯子并锁整把梯(含连接端Y),
        # 之后引路只认锁定梯、一路到顶再开主线重识怪;平地去梯途中仅被"技能范围内可直打怪"解绑,抓梯后硬绑到登顶/失败/硬重置才清。
        self._climb_fail_at = 0                      # 上次爬梯/跳跃失败时间戳(ms)，失败后2秒冷却（先打边上怪再上）
        # === 显示层速度外推状态（低帧率下蒙板落后一拍，按人物速度外推显示位置跟手）===
        self._char_disp_pos_prev = None              # 上次同步的原始匹配位置（用于算速度，不存外推值）
        self._char_disp_pos_time = 0                 # 上次同步时间戳(ms)
        self._char_disp_vel = (0.0, 0.0)             # 人物最近速度(px/s)，匹配失败宽限期内维持外推
        self._player_map_pos = None        # 玩家小地图坐标，用于判断当前平台
        # 光点中心一次性微调(小地图块像素,默认0):小地图红十字与游戏黄光点视觉中心固定差多少就填多少;
        # find_player_dot返回前叠加,绿线/梯子/导航/边界全部共用校准后的同一中心(用户2026-09-14)
        self._dot_center_off_x = 0
        self._dot_center_off_y = 0
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
        self._climb_state = "none"  # none/to_ladder/climbing/jump_down/jump_up/teleport/descend
        self._ladder_precise_mode = False  # 上梯屏幕精对齐高频档标志(用户2026-09-10方案B):进屏幕对位True→检测线程30Hz跳YOLO/血条;_reset_climb复位
        self._climb_ladder_x = 0
        # 锁定的【目标梯】整把梯子dict(含x/y_top/y_bottom;用户2026-09-11"锁定梯子"定稿,替代上层怪空坐标):
        # 锁梯那一下按 怪→梯→人 选出连怪层的正确梯,跨层期间固定不横跳,引路终点=梯连接端(上行y_top/下行y_bottom);
        # 和锁怪互斥(跨层只锁梯),登顶/失败/近身打断随_clear_locked_ladder解绑回主线重锁怪
        self._locked_ladder = None
        self._climb_target_y = 0
        self._climb_target_x = 0    # 下行descend:目标怪小地图X(先水平走到怪正头上/最近X再下跳)
        self._climb_direction = 0  # 1=up, -1=down
        self._climb_start_y = 0    # 跳跃/瞬移前的y坐标，用于检测是否生效
        self._climb_action_time = 0  # 跳跃/瞬移动作开始时间
        # === 下行descend子状态机(用户2026-09-09重定义下行,替代旧"X对齐+小落差才跳、失败走上梯抓法")===
        self._desc_phase = None       # first_jump/to_ladder/lad_grab/lad_slide/lad_leap/lad_fall_wait/fall
        self._desc_base_y = 0         # 当前阶段基准光点Y(判Y变大=向下动了)
        self._desc_phase_t = 0        # 当前阶段开始时刻ms
        self._desc_ref_px = None      # 水平走向目标时上一拍人物X(判卡住/到平台边)
        self._desc_stall_t = 0        # 水平"没靠近"的起始时刻
        self._desc_jumped = False     # 本阶段是否已补按过跳跃键
        self._desc_j2 = False         # 方式一第二跳(随机侧向)是否已按
        self._desc_leap_dir = 1       # 方式一/二侧跳离梯的随机方向(-1左/1右)
        self._desc_j2 = False         # 方式一:第二跳(随机侧向)是否已按
        self._desc_leap_dir = 1       # 方式一/二侧跳离梯的随机方向(1右/-1左)
        self._desc_pre_leap_sy = None  # 方式一:左右跳前人物特征屏幕Y基准
        self._desc_pre_leap_my = 0     # 方式一:左右跳前小地图世界Y基准
        self._desc_scr_key_vk = None  # 方式二段2主窗口碎步当前按键/时刻/时长/拍数复位
        self._desc_scr_key_t = 0
        self._desc_scr_key_hold = 0
        self._desc_scr_nudge_t = 0
        self._desc_scr_nudge_t = 0
        self._desc_scr_nudge_n = 0
        self._desc_scr_nudge_step = 0
        self._desc_scr_nudge_from_x = None
        self._desc_scr_nudge_gap = 100
        self._desc_scr_ok_frames = 0
        self._desc_scr_last_x = None
        self._desc_scr_last_t = 0
        self._desc_scr_enter_t = 0
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
        self._debug_overlay = True  # 调试显示总开关(F4切):True=画全部框/线,False=蒙板等同干净原画面(纯显示、不参与识别,不影响打怪)
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
        self._capture_thread = None         # 截图线程:全项目唯一全窗截图、写帧槽,不做识别(多线程重构:从A独立)
        self._person_thread = None          # 人物识别线程:从帧槽取帧、高频出人物点(多线程重构:从A独立)
        self._recognize_thread = None       # 怪物线程:怪模板/YOLO/血条(低频,从帧槽取帧,自己不截图)
        # 物理拆分帧槽:A每周期把最新截图写这里,B永远只取最新一帧;seq单调递增,B按seq只处理新帧不重复算
        self._latest_frame = None
        self._latest_frame_t = 0.0
        self._latest_frame_seq = 0
        self.client_subrect = None        # 游戏画面(客户区)在外窗坐标系里的子矩形(x1,y1,x2,y2),由_update_window_rect动态算(用户2026-09-14)
        self._detect_running = False        # 常开层(截图+人物)运行标志:绑定游戏窗口即True
        self._monster_running = False       # 运行层(怪物模板/YOLO/血条)标志:点"开始运行"才True、停止即False(方案B)
        self._detect_lock = threading.Lock()  # 截图/结果写入锁，保证与主线程/蒙板线程不打架
        self._raw_monsters = []             # 后台线程算出的原始合并怪列表 [(x1,y1,x2,y2,score)]
        self._raw_hp_bars = []              # 后台线程算出的血条 [(x,y,w,h)]
        self._raw_char_pos = None           # 后台线程算出的人物脚位置
        # 世界快照仓(识别线程唯一出口)。动作权仲裁器/范围迟滞门已按用户2026-09-15整套删除:打怪/巡路一条线直连,不再有第三方劝架。
        self._snap_store = SnapshotStore()
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
        # 游戏画面(客户区)在"外窗坐标系"里的子矩形(x1,y1,x2,y2),动态随窗口样式/标题栏/DPI自适应。
        # 蒙板仍盖整个外窗,但所有框/识别只在这块画面内生效,标题栏+边框那圈不画不识别(用户2026-09-14)。
        try:
            _cr = ctypes.create_string_buffer(16)
            user32.GetClientRect(self.hwnd, _cr)
            _cl0, _ct0, _crr, _cbb = struct.unpack("llll", _cr.raw)
            _pt = POINT(0, 0)
            user32.ClientToScreen(self.hwnd, ctypes.byref(_pt))
            _ox, _oy = _pt.x - l, _pt.y - t
            self.client_subrect = (_ox, _oy, _ox + (_crr - _cl0), _oy + (_cbb - _ct0))
        except Exception:
            self.client_subrect = (0, 0, r - l, b - t)  # 取不到就退回整个外窗,绝不因此崩

    # ==================== CPU性能三档(慢/普通/快,用户2026-09-11) ====================
    def _load_perf_level(self):
        """启动读 data/perf_config.json 的档位;非法/缺失/异常一律回退normal,绝不因配置崩"""
        try:
            _p = os.path.join(DATA_DIR, "perf_config.json")
            if os.path.exists(_p):
                with open(_p, "r", encoding="utf-8") as fp:
                    _lv = json.load(fp).get("level", PERF_DEFAULT_LEVEL)
                if _lv in PERF_PROFILES:
                    return _lv
        except Exception as _e:
            try:
                _debug_log("[性能档] 读取失败:%s,回退普通" % _e)
            except Exception:
                pass
        return PERF_DEFAULT_LEVEL

    def _save_perf_level(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(os.path.join(DATA_DIR, "perf_config.json"), "w", encoding="utf-8") as fp:
                json.dump({"level": self._perf_level}, fp, ensure_ascii=False, indent=2)
        except Exception as _e:
            _debug_log("[性能档] 保存失败:%s" % _e)

    def _perf(self):
        """当前档参数dict(带缓存,切档才重算)"""
        if self._perf_cache is None or self._perf_cache[0] != self._perf_level:
            lv = self._perf_level if self._perf_level in PERF_PROFILES else PERF_DEFAULT_LEVEL
            self._perf_cache = (lv, PERF_PROFILES[lv])
        return self._perf_cache[1]

    def _perf_val(self, key):
        return self._perf()[key]

    def _perf_onnx_threads(self):
        """onnx推理CPU线程数=档+逻辑核数(启动时定,切档下次启动生效):
        快=核-2尽量多;普通=max(2,核-3);慢=封顶2条,多留核给游戏/系统(四核弱机也不爆)"""
        n = os.cpu_count() or 4
        lv = self._perf_level if self._perf_level in PERF_PROFILES else PERF_DEFAULT_LEVEL
        if lv == "fast":
            return max(1, n - 2)
        if lv == "slow":
            return max(1, min(2, n - 2))
        return max(2, n - 3)

    def _set_perf_level(self, lv):
        if lv not in PERF_PROFILES or lv == self._perf_level:
            return
        self._perf_level = lv
        self._perf_cache = None
        self._save_perf_level()
        p = self._perf()
        _msg = "[性能档] 切换为%s(%s):检测忙%d/闲%dms YOLO找怪%.2f/战斗%.2fs 血条%.2f 高帧%dms UI%dms 边界%dms;推理线程数下次启动生效" % (
            PERF_LEVEL_CN[lv], lv, p['detect_busy_ms'], p['detect_idle_ms'],
            p['yolo_fast_s'], p['yolo_slow_s'], p['bars_s'], p['precise_ms'],
            p['ui_wait_ms'], p['bound_poll_ms'])
        print(_msg)
        _debug_log(_msg)
        try:
            self._add_log("性能档→%s(频率即时生效)" % PERF_LEVEL_CN[lv])
        except Exception:
            pass

    def _open_perf_dialog(self):
        self._show_perf_dialog = True
        self._update_perf_dialog_positions()  # 打开即算控件位置(规范:根治首开点击无反应)

    def _update_perf_dialog_positions(self):
        """性能档弹窗控件位置(打开即算+每帧绘制重算,照弹窗规范,拖拽不偏移)"""
        x, y = self._perf_dialog_pos[0], self._perf_dialog_pos[1]
        self._dlg_perf_close = (x + PERF_DIALOG_W - 30, y + 5, 25, 25)
        _oy = y + 58
        for i, lv in enumerate(PERF_LEVEL_ORDER):  # 三个选项条纵向排列
            self._dlg_perf_opt[lv] = (x + 20, _oy + i * 40, PERF_DIALOG_W - 40, 34)

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
        """记录目标窗口大小（绑定成功后调用）。写死 GAME_W x GAME_H(1280x800)，不读当前窗口——用户要写死固定，窗口变大会被_ensure_window_size拉回。
        同时移除窗口的WS_THICKFRAME(可调大小边框)——用户改不了大小，但保留标题栏WS_CAPTION仍可拖动移动位置。"""
        if self.hwnd and self.window_rect:
            self._target_window_size = (GAME_W, GAME_H)
            print("[窗口固定] 目标大小已写死: %dx%d" % self._target_window_size)
            try:
                style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_STYLE)
                win32gui.SetWindowLong(self.hwnd, win32con.GWL_STYLE, style & ~win32con.WS_THICKFRAME)
            except Exception as e:
                print("[窗口固定] 移除WS_THICKFRAME异常:", e)
            self._ensure_window_size()  # 绑定后立即拉回指定尺寸1280x800(不等主循环30帧)，用户改不了大小

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
                _debug_log("[小地图] 启动读回保存裁剪框 %dx%d @(L%d,T%d),与录制保持同一块内像素坐标系(不三模板重算)" % (
                    self.map_area_rect["width"], self.map_area_rect["height"],
                    self.map_area_rect["left"], self.map_area_rect["top"]))
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

        # [2026-09-14 根因修复·保存后线与光点错位] 录制点=find_player_dot在"当时裁剪框"里的绝对像素坐标。
        # 三模板是整数像素匹配,帧间会抖1~3px;旧规则差>1px就整块换框→新光点坐标系平移、旧录制点整体错位
        # (表现:录制当下重合,保存后继续跑/重启时裁剪框被重定位→绿线梯子和光点错开)。
        # 现锁定裁剪基准:自动(debug=False)重定位时,与已锁定基准任一边差≤_RECT_LOCK_TOL一律视为帧间抖动,
        # 保持旧框直接return(不换框/不写region/不清光点锚点),保证录制点与光点永远同一像素坐标系;
        # 仅真换图·拖窗·UI缩放(任一边差>8px)才接受新框。手动按R(debug=True)/鼠标框定不走此分支,照常重设。
        _RECT_LOCK_TOL = 8
        if not debug:
            old = self.map_area_rect
            if old is not None:
                _dmax = max(abs(old["left"] - new_map["left"]), abs(old["top"] - new_map["top"]),
                            abs(old["width"] - new_map["width"]), abs(old["height"] - new_map["height"]))
                if _dmax <= _RECT_LOCK_TOL:
                    return  # 小抖动:锁定基准不动=坐标系恒定(关键:不清last_player_pos,光点最近邻锚点连续)
                print("[自动刷新] 小地图区域显著变化(%dpx>%d)才重定: L%dT%d %dx%d -> L%dT%d %dx%d" % (
                    _dmax, _RECT_LOCK_TOL, old["left"], old["top"], old["width"], old["height"],
                    new_map["left"], new_map["top"], new_map["width"], new_map["height"]))

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
                        self._yolo_sess = None
                        self._yolo_backend = None
                        self._yolo_iname = "images"
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
                    self._yolo_sess = None
                    self._yolo_backend = None
                    self._yolo_iname = "images"
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


    # ==================== 角色识别:全局数据读写(2026-09-13) ====================
    def _role_char_dir(self, cid):
        """某角色套的锚点图目录 data/role_recognize/<cid>/"""
        d = os.path.join(ROLE_REC_DIR, str(cid))
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _role_cur_character(self, rec=None):
        """当前角色套dict(没有则补一套默认"角色一")"""
        rec = rec or self._role_rec
        if not rec:
            return None
        chars = rec.setdefault("characters", [])
        if not chars:
            chars.append({"id": "c0", "name": "角色一", "anchors": {}})
            rec["active"] = "c0"; rec.setdefault("_seq", 1)
        cid = rec.get("active")
        cur = next((c for c in chars if c.get("id") == cid), None)
        if cur is None:  # active失效→默认最后一套
            cur = chars[-1]; rec["active"] = cur.get("id")
        cur.setdefault("anchors", {})
        return cur

    def _load_role_recognize(self):
        """加载全局角色识别数据(2026-09-13起以角色为单位整套保存,最多10套):
        {params全局跟踪参数, blocklist全局黑名单, active当前套id, characters:[{id,name,anchors}×≤10]}。
        内存里把"当前套anchors"挂到顶层rec['anchors'](与该套dict同一引用),现有匹配/采集/UI读顶层即用当前套、零改动。
        旧单套格式(顶层anchors+平铺<png>)首次加载自动迁移成「角色一」、平铺png移进 c0/ 子目录。"""
        import shutil
        rec = {"anchors": {}, "params": dict(ROLE_TRACK_DEFAULT), "blocklist": [],
               "blocklist_monster": False, "active": None, "characters": [], "_seq": 0}
        saved = {}
        _migrated = False  # 本次是否发生"旧单套→多套"迁移;迁移完落盘一次,json一步转新结构
        try:
            if os.path.exists(ROLE_REC_FILE):
                with open(ROLE_REC_FILE, "r", encoding="utf-8") as fp:
                    saved = json.load(fp)
            p = saved.get("params")  # 跟踪参数=全局共用一套
            if isinstance(p, dict):
                for k, dv in ROLE_TRACK_DEFAULT.items():
                    try:
                        rec["params"][k] = float(p[k]) if isinstance(dv, float) else int(float(p.get(k, dv)))
                    except (TypeError, ValueError):
                        rec["params"][k] = dv
            _bl = saved.get("blocklist")  # 黑名单=全局共用一套(可多处矩形,同时生效)
            if isinstance(_bl, list):
                rec["blocklist"] = [list(map(int, r)) for r in _bl
                                    if isinstance(r, (list, tuple)) and len(r) == 4]
            rec["blocklist_monster"] = bool(saved.get("blocklist_monster", False))  # 黑名单是否同时对怪物YOLO生效(默认只人物)
            try:
                rec["_seq"] = int(saved.get("_seq", 0))
            except Exception:
                rec["_seq"] = 0

            def _clean_anchors(a):
                return {k: v for k, v in (a or {}).items() if k in ROLE_ANCHOR_KEYS and isinstance(v, dict)}

            if isinstance(saved.get("characters"), list) and saved["characters"]:  # 新多套格式
                for c in saved["characters"]:
                    if isinstance(c, dict) and c.get("id"):
                        rec["characters"].append({"id": str(c["id"]),
                                                  "name": str(c.get("name") or "角色"),
                                                  "anchors": _clean_anchors(c.get("anchors"))})
                rec["active"] = saved.get("active")
            else:  # 旧单套格式→迁移为「角色一」,平铺锚点png移进 c0/
                rec["characters"].append({"id": "c0", "name": "角色一",
                                          "anchors": _clean_anchors(saved.get("anchors"))})
                rec["active"] = "c0"; rec["_seq"] = max(rec["_seq"], 1)
                d0 = os.path.join(ROLE_REC_DIR, "c0")
                try:
                    os.makedirs(d0, exist_ok=True)
                    for k in ROLE_ANCHOR_KEYS:
                        old_png = os.path.join(ROLE_REC_DIR, "%s.png" % k)
                        new_png = os.path.join(d0, "%s.png" % k)
                        if os.path.exists(old_png) and not os.path.exists(new_png):
                            shutil.move(old_png, new_png)
                except Exception as e:
                    print("[角色识别] 旧锚点图迁移异常:", e)
                _migrated = True
            cur = self._role_cur_character(rec)
            rec["anchors"] = cur["anchors"]
            self._role_char_dir(cur["id"])
        except Exception as e:
            print("[角色识别] 加载失败,用默认:", e)
            cur = self._role_cur_character(rec); rec["anchors"] = cur["anchors"]
        self._role_rec = rec
        if _migrated:  # 旧格式迁移完成→立即落盘新结构(含characters/active),避免图已分目录而json仍旧格式的中间态
            try:
                self._save_role_recognize()
            except Exception:
                pass
        return rec

    def _save_role_recognize(self):
        """落盘:顶层anchors即当前套引用,先回写当前character,再dump params/blocklist/active/characters(不冗余写顶层anchors)"""
        try:
            if self._role_rec is None:
                self._role_rec = self._load_role_recognize()
            rec = self._role_rec
            cur = self._role_cur_character(rec)
            cur["anchors"] = rec.get("anchors", {})  # 顶层与当前套保持同步
            out = {"params": rec.get("params", dict(ROLE_TRACK_DEFAULT)),
                   "blocklist": rec.get("blocklist", []),
                   "blocklist_monster": bool(rec.get("blocklist_monster", False)),
                   "active": rec.get("active"),
                   "_seq": int(rec.get("_seq", 0)),
                   "characters": rec.get("characters", [])}
            with open(ROLE_REC_FILE, "w", encoding="utf-8") as fp:
                json.dump(out, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[角色识别] 保存失败:", e)

    def _role_anchor_path(self, key):
        """锚点模板图路径=当前角色套子目录/<key>.png(切套即换目录,各角色互不串图)。
        高频调用(每帧name/脸/后脑各一次),不在此makedirs;目录由load/select/采集落盘时建好。"""
        cid = (self._role_rec or {}).get("active") if self._role_rec else None
        return os.path.join(ROLE_REC_DIR, str(cid or "c0"), "%s.png" % key)

    def _role_has_anchor(self, key):
        """该锚点在当前套是否已采集(元数据在且模板图存在)"""
        if not self._role_rec or key not in self._role_rec.get("anchors", {}):
            return False
        return os.path.exists(self._role_anchor_path(key))

    # ==================== 角色套管理(以角色为单位整套,最多10套) ====================
    def _role_next_char_name(self, rec=None):
        """取 角色一..角色十 中第一个未被占用的名字(删中间再建也不重名)"""
        rec = rec or self._role_rec
        used = {c.get("name") for c in rec.get("characters", [])}
        for w in ROLE_CN_NUM:
            nm = "角色" + w
            if nm not in used:
                return nm
        return "角色%d" % (len(rec.get("characters", [])) + 1)

    def _role_new_character(self):
        """新建一套并切为当前;已满10套先删最旧(列表第一套,含其图目录)。返回新套id"""
        import shutil
        rec = self._role_rec or self._load_role_recognize()
        chars = rec.setdefault("characters", [])
        if len(chars) >= ROLE_MAX_CHARS:  # 用户定:超10删最旧那套
            old = chars.pop(0)
            try:
                shutil.rmtree(os.path.join(ROLE_REC_DIR, str(old.get("id"))), ignore_errors=True)
            except Exception:
                pass
            self._add_log("角色方案已满%d套,已删最旧的「%s」" % (ROLE_MAX_CHARS, old.get("name")))
        seq = int(rec.get("_seq", 0)) + 1; rec["_seq"] = seq
        cid = "c%d" % seq
        chars.append({"id": cid, "name": self._role_next_char_name(rec), "anchors": {}})
        self._role_select_character(cid)
        return cid

    def _role_select_character(self, cid, refresh=True):
        """切当前套:顶层anchors指向该套、换图目录、清模板缓存、落盘、刷新管理窗"""
        rec = self._role_rec or self._load_role_recognize()
        cur = next((c for c in rec.get("characters", []) if c.get("id") == cid), None)
        if cur is None:
            return False
        rec["active"] = cid
        cur.setdefault("anchors", {})
        rec["anchors"] = cur["anchors"]      # 顶层引用当前套
        self._role_char_dir(cid)
        self._role_tpl_c = {}                # 切套清模板缓存,匹配立即读新套图
        self._role_last_scores = {}
        self._save_role_recognize()
        if refresh:  # 管理窗开着时同步下拉选中+锚点列表/缩略图
            for fn in ("_role_refresh_chars", "_role_refresh_window"):
                try:
                    f = getattr(self, fn, None)
                    if f:
                        f()
                except Exception:
                    pass
        return True

    def _role_delete_character(self, cid):
        """删整套;删当前套则切到剩下最新一套;一套不剩自动补一套空的"""
        import shutil
        rec = self._role_rec or self._load_role_recognize()
        chars = rec.setdefault("characters", [])
        idx = next((i for i, c in enumerate(chars) if c.get("id") == cid), -1)
        if idx < 0:
            return
        gone = chars.pop(idx)
        try:
            shutil.rmtree(os.path.join(ROLE_REC_DIR, str(cid)), ignore_errors=True)
        except Exception:
            pass
        if not chars:
            seq = int(rec.get("_seq", 0)) + 1; rec["_seq"] = seq
            chars.append({"id": "c%d" % seq, "name": "角色一", "anchors": {}})
        if rec.get("active") == cid:
            target = chars[-1]
        else:
            target = next((c for c in chars if c.get("id") == rec.get("active")), chars[-1])
        self._role_select_character(target["id"])
        self._add_log("已删除角色套「%s」" % gone.get("name"))

    def _role_rename_character(self, cid, name):
        """给某套改名(管理窗双击/改名按钮用)"""
        rec = self._role_rec or self._load_role_recognize()
        name = (name or "").strip()
        if not name:
            return
        cur = next((c for c in rec.get("characters", []) if c.get("id") == cid), None)
        if cur is not None:
            cur["name"] = name[:16]
            self._save_role_recognize()

    def _capture_role_anchor(self, key):
        """角色识别·统一多边形描点采集(2026-09-13定稿:不另定基点;角色名/面部/后脑/宠物名全部同一流程)。
        流程:①左键点目标中心→以该点为中心取ROLE_MAG_SRC方块放大ROLE_MAG_ZOOM倍、放大框贴在点击点旁;
        ②在放大框内左键逐点,点满4点自动闭合(长方形点4角、不要求直角,多边形通杀);
        ③闭合后编辑:点白色边线=该处插新点并直接拖、拖白点改形、右键点白点删除;空格/回车确认,C重选中心,ESC取消。
        描点坐标自动从放大框映射回原图。名字/宠物名圈内OTSU自动抠黑底白字,面部/后脑存彩色原图。
        锚点中心即人物坐标(不做到脚补偿,单平台打怪只看X)。模态阻塞主循环,结束恢复tk管理窗。"""
        if key not in ROLE_ANCHOR_KEYS:
            return False
        win = "角色锚点采集"
        VK_ESC, VK_SP, VK_EN = 0x1B, 0x20, 0x0D
        try:
            self._update_window_rect(); wr = self.window_rect
            if not wr or wr.get("left", 0) <= -30000 or wr.get("width", 0) < 200:
                self._add_log("游戏窗口未正常显示,无法采集角色锚点"); return False
            frame = self._capture_window()
            if frame is None:
                self._add_log("截图为空,请先绑定游戏窗口后再采集"); return False
            H, W = frame.shape[:2]
            rw = getattr(self, "_role_rec_window", None)  # 隐藏tk管理窗,避免tk/cv2冲突闪退
            try:
                if rw is not None: rw.withdraw(); rw.update()
            except Exception:
                pass
            cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
            try:
                cv2.moveWindow(win, int(wr.get("left", 40)), int(wr.get("top", 40)))
                cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
            except Exception:
                pass
            st = {"pts": [], "mouse": None, "phase": "pick", "drag": None,
                  "center": None, "src": None, "mag": None}  # pick=选放大中心;poly=放大框内逐点;edit=闭合调形
            HALF = ROLE_MAG_SRC // 2
            ZM = ROLE_MAG_ZOOM
            HITM = 8                                    # 放大框内顶点/边线的命中手感像素
            HITS = max(3, int(HITM / ZM))               # 换算回原图坐标的命中半径

            def _set_center(cx, cy):  # 以点击点为中心取ROLE_MAG_SRC方块,放大ZM倍,放大框贴在点击点旁边
                sx0 = max(0, min(W - ROLE_MAG_SRC, cx - HALF))
                sy0 = max(0, min(H - ROLE_MAG_SRC, cy - HALF))
                mw = mh = ROLE_MAG_SRC * ZM
                mx0 = cx + 60
                if mx0 + mw > W - 4:
                    mx0 = cx - 60 - mw                  # 右边放不下就放左边
                mx0 = max(4, min(W - mw - 4, mx0))
                my0 = max(4, min(H - mh - 4, cy - mh // 2))
                st["center"] = (cx, cy)
                st["src"] = (sx0, sy0, ROLE_MAG_SRC, ROLE_MAG_SRC)
                st["mag"] = (mx0, my0, mw, mh)
                st["pts"] = []; st["drag"] = None; st["phase"] = "poly"

            def _in_mag(x, y):
                mg = st["mag"]
                return mg is not None and mg[0] <= x < mg[0] + mg[2] and mg[1] <= y < mg[1] + mg[3]

            def _to_src(x, y):  # 放大窗口坐标→原图坐标
                sx0, sy0, sw, sh = st["src"]; mx0, my0, _, _ = st["mag"]
                ox = sx0 + int((x - mx0) / ZM); oy = sy0 + int((y - my0) / ZM)
                return max(sx0, min(sx0 + sw - 1, ox)), max(sy0, min(sy0 + sh - 1, oy))

            def _near_vertex(x, y):
                for i, (px, py) in enumerate(st["pts"]):
                    if (px - x) ** 2 + (py - y) ** 2 <= HITS * HITS:
                        return i
                return None

            def _seg_dist(x, y, a, b):  # 点到线段距离
                ax, ay = a; bx, by = b; dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                if l2 == 0:
                    return ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
                t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
                qx, qy = ax + t * dx, ay + t * dy
                return ((x - qx) ** 2 + (y - qy) ** 2) ** 0.5

            def _near_edge(x, y):
                pts = st["pts"]; n = len(pts); best = None; bd = HITS
                for i in range(n):  # 闭合边,含 最后点→首点
                    d = _seg_dist(x, y, pts[i], pts[(i + 1) % n])
                    if d < bd:
                        bd, best = d, i + 1  # 新点插在 i 与 i+1 之间,index=i+1
                return best

            def on_mouse(e, x, y, fl, p):
                x, y = int(x), int(y)
                if e == cv2.EVENT_MOUSEMOVE:
                    st["mouse"] = (x, y)
                    if st["drag"] is not None and _in_mag(x, y):  # 拖顶点(含刚插入的新点)
                        st["pts"][st["drag"]] = _to_src(x, y)
                    return
                if st["phase"] == "pick":
                    if e == cv2.EVENT_LBUTTONDOWN:
                        _set_center(x, y)
                    return
                if not _in_mag(x, y):  # 描点一律在放大框内进行,框外点击忽略
                    if e == cv2.EVENT_LBUTTONUP:
                        st["drag"] = None
                    return
                sx, sy = _to_src(x, y)  # 后续统一用原图坐标,pts存原图坐标
                if st["phase"] == "poly":
                    if e == cv2.EVENT_LBUTTONDOWN:
                        st["pts"].append((sx, sy))
                        if len(st["pts"]) >= ROLE_POLY_AUTO_CLOSE:  # 点满4点自动闭合
                            st["phase"] = "edit"
                    elif e == cv2.EVENT_RBUTTONDOWN and st["pts"]:
                        st["pts"].pop()  # 加点阶段右键=撤销上一点
                elif st["phase"] == "edit":
                    if e == cv2.EVENT_LBUTTONDOWN:
                        vi = _near_vertex(sx, sy)
                        if vi is not None:
                            st["drag"] = vi  # 按住已有白点→拖
                        else:
                            ei = _near_edge(sx, sy)
                            if ei is not None:  # 点白线→该处插新点并直接拖
                                st["pts"].insert(ei, (sx, sy)); st["drag"] = ei
                    elif e == cv2.EVENT_LBUTTONUP:
                        st["drag"] = None
                    elif e == cv2.EVENT_RBUTTONDOWN:
                        vi = _near_vertex(sx, sy)
                        if vi is not None and len(st["pts"]) > ROLE_POLY_MIN_PTS:
                            st["pts"].pop(vi)  # 编辑态右键点白点=删除(不少于3点)
            cv2.setMouseCallback(win, on_mouse)

            def draw():
                img = frame.copy(); pts = st["pts"]; m = st["mouse"]
                if st["phase"] == "pick":  # 选中心:跟随鼠标画100×100取景框+十字
                    if m is not None:
                        cv2.rectangle(img, (m[0] - HALF, m[1] - HALF),
                                      (m[0] - HALF + ROLE_MAG_SRC, m[1] - HALF + ROLE_MAG_SRC), (0, 255, 255), 1)
                        cv2.drawMarker(img, m, (0, 0, 255), cv2.MARKER_CROSS, 10, 1)
                    self._draw_cn_mixed(img, "左键点目标中心(以该点%d×%d放大%d倍,再在放大框里描点); ESC取消" % (ROLE_MAG_SRC, ROLE_MAG_SRC, ZM),
                                        12, 26, 0.6, (0, 255, 255), 1)
                    return img
                sx0, sy0, sw, sh = st["src"]; mx0, my0, mw, mh = st["mag"]
                closed = st["phase"] == "edit"
                if len(pts) >= 2:  # 主图上只画细轮廓(线宽1/点半径2,减半不挡字)+源区细框
                    cv2.polylines(img, [np.array(pts, np.int32)], closed, (0, 200, 255), 1)
                for (px, py) in pts:
                    cv2.circle(img, (px, py), 2, (0, 0, 255), -1)
                cv2.rectangle(img, (sx0, sy0), (sx0 + sw, sy0 + sh), (255, 255, 255), 1)
                region = frame[sy0:sy0 + sh, sx0:sx0 + sw]  # 放大子图(2倍),描点主要在这里进行
                magimg = cv2.resize(region, (sw * ZM, sh * ZM), interpolation=cv2.INTER_LINEAR)

                def M(pt):
                    return (int((pt[0] - sx0) * ZM), int((pt[1] - sy0) * ZM))
                if len(pts) >= 2:
                    cv2.polylines(magimg, [np.array([M(q) for q in pts], np.int32)], closed, (0, 200, 255), 2)
                    if st["phase"] == "poly" and pts and m is not None and _in_mag(*m):  # 放大框内橡皮筋
                        ex, ey = M(pts[-1])
                        cv2.line(magimg, (ex, ey), (m[0] - mx0, m[1] - my0), (0, 200, 255), 1)
                for i, (px, py) in enumerate(pts):
                    qx, qy = M((px, py))
                    cv2.circle(magimg, (qx, qy), 3, (0, 0, 255) if st["drag"] == i else (255, 255, 255), -1)
                cv2.rectangle(magimg, (0, 0), (sw * ZM - 1, sh * ZM - 1), (255, 255, 255), 1)
                img[my0:my0 + mh, mx0:mx0 + mw] = magimg
                tip = ("在放大框内左键点4点自动闭合; C重选中心; 右键撤销; ESC取消" if st["phase"] == "poly"
                       else "放大框内:点白线=加点并拖 / 拖白点改形 / 右键删点; 空格确认; C重选; ESC取消")
                self._draw_cn_mixed(img, tip, 12, 26, 0.6, (0, 255, 255), 1)
                return img

            ok = False
            VK_C = 0x43
            while True:
                k = cv2.waitKey(20) & 0xFF
                if k == VK_ESC:
                    break
                if k == VK_C and st["phase"] != "pick":  # C=重选放大中心、清空重描
                    st["phase"] = "pick"; st["pts"] = []; st["drag"] = None; st["src"] = None; st["mag"] = None
                    continue
                if st["phase"] == "edit" and k in (VK_SP, VK_EN):  # 闭合调形后:空格/回车确认保存
                    ok = True; break
                cv2.imshow(win, draw())
            try: cv2.destroyWindow(win)
            except Exception: pass
            for _ in range(2): cv2.waitKey(20)
            if not ok or len(st["pts"]) < ROLE_POLY_MIN_PTS:
                return False
            # === 按多边形外接框抠图(框外置黑减背景干扰),落盘 ===
            pts = st["pts"]
            xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
            x0, x1 = max(0, min(xs)), min(W - 1, max(xs)); y0, y1 = max(0, min(ys)), min(H - 1, max(ys))
            if x1 - x0 < 3 or y1 - y0 < 3:
                self._add_log("描边区域太小,本次采集作废"); return False
            poly_mask = np.zeros(frame.shape[:2], np.uint8)
            cv2.fillPoly(poly_mask, [np.array(pts, np.int32)], 255)
            pm = poly_mask[y0:y1 + 1, x0:x1 + 1]
            crop = cv2.bitwise_and(frame, frame, mask=poly_mask)[y0:y1 + 1, x0:x1 + 1].copy()
            is_text = (key == "name") or key.startswith("pet")  # 名字/宠物名=半透明底板上的亮字→自动抠笔画;脸=实体→存彩色
            if is_text:
                # OTSU只在多边形内部像素上自动找"亮字/暗底"分界(零手调阈值),多边形外强制黑,再去碎点。
                # 这样底板后透出的任意背景/特效都不进模板,运行时小窗内同样OTSU后再比笔画。
                vv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2]
                if vv[pm > 0].size < 8:
                    self._add_log("名字区域太小,本次采集作废"); return False
                out_img = self._role_text_binarize(vv, pm)  # 与实时匹配同源(OTSU+去碎点),避免采集/识别两套二值化
                kind = "text"
            else:
                out_img, kind = crop, "color"
            okenc, buf = cv2.imencode(".png", out_img)
            if not okenc:
                self._add_log("锚点图像编码失败,采集作废"); return False
            _ap = self._role_anchor_path(key)
            try:
                os.makedirs(os.path.dirname(_ap), exist_ok=True)  # 当前套目录兜底(正常load/select已建)
            except Exception:
                pass
            buf.tofile(_ap)
            meta = {"kind": kind,
                    "poly": [[px - x0, py - y0] for px, py in pts],  # 相对裁剪框的顶点
                    "box": [int(x0), int(y0), int(x1), int(y1)],
                    "off_x": 0, "off_y": 0,  # 不做到脚补偿:锚点中心即人物坐标(单平台只看X)
                    "w": int(x1 - x0 + 1), "h": int(y1 - y0 + 1)}
            if self._role_rec is None:
                self._load_role_recognize()
            self._role_rec.setdefault("anchors", {})[key] = meta
            self._save_role_recognize()
            if getattr(self, '_role_tpl_c', None) is not None:  # 重录后清模板缓存,下次匹配用新图+新掩膜
                self._role_tpl_c.pop(key, None)
            print("[角色识别] 已采集锚点 %s kind=%s 尺寸%dx%d" % (key, kind, meta["w"], meta["h"]))
            return True
        except Exception as e:
            import traceback; traceback.print_exc(); print("[角色识别] 采集异常:", e); return False
        finally:
            try: cv2.destroyWindow("角色锚点采集")
            except Exception: pass
            for _ in range(2):
                try: cv2.waitKey(20)
                except Exception: pass
            rw = getattr(self, "_role_rec_window", None)  # 恢复tk管理窗
            try:
                if rw is not None: rw.deiconify(); rw.lift(); rw.update()
            except Exception: pass
            try:
                if rw is not None and hasattr(self, "_role_refresh_window"):
                    self._role_refresh_window()
            except Exception: pass

    def _role_text_binarize(self, vv, mask=None, denoise=True):
        """名字/宠物名统一二值化(采集与实时必须同源,否则真名字相似度被压低、背景纹理反成假阳性):
        V通道OTSU自动找"亮笔画/底"分界→黑底白字。denoise=连通域去面积<3碎点(仅采集小模板用);
        实时整窗必须传denoise=False——整帧连通域极慢,曾把帧率拖到1.3、主循环卡957ms致F12失灵/闪退。"""
        try:
            sel = vv[mask > 0] if mask is not None else vv
            if sel is None or sel.size < 8:
                return np.zeros_like(vv)
            tval, _ = cv2.threshold(sel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if mask is not None:
                out = np.where((vv > tval) & (mask > 0), 255, 0).astype(np.uint8)
            else:
                out = np.where(vv > tval, 255, 0).astype(np.uint8)
            if denoise:  # 连通域去碎点只在采集小模板上做;实时整窗做会拖垮帧率
                _n, _lab, _st, _ = cv2.connectedComponentsWithStats(out)  # 去笔画外孤立碎点
                for _i in range(1, _n):
                    if _st[_i, cv2.CC_STAT_AREA] < 3:
                        out[_lab == _i] = 0
            return out
        except Exception:
            return np.zeros_like(vv, np.uint8)

    def _role_blocked(self, gx, gy):
        """全局坐标(gx,gy)是否落在角色识别黑名单矩形内(框内命中不采信,防固定UI/图标被误认成锚点)。"""
        rec = self._role_rec
        if not rec:
            return False
        for _r in rec.get("blocklist", []):
            try:
                _x, _y, _w, _h = _r
                if _x <= gx <= _x + _w and _y <= gy <= _y + _h:
                    return True
            except Exception:
                continue
        return False

    def _role_sub_rects(self, S, tw, th):
        """搜索矩形S=(x0,y0,x1,y1)全局坐标,几何扣除所有黑名单矩形后,拆成若干【不含黑名单、且放得下模板tw×th】
        的不重叠子矩形(全局)。用户:400×300识别区拉黑100×300→模板只在剩下300×300上滑窗、根本不扫黑名单。
        做法:依次用每个黑名单矩形对当前所有子矩形做矩形差集(相交就切成:上/下两条【全宽】横带+黑名单Y段内的
        左/右两块,四块拼起来正好=原子块减黑名单、不多扣也不漏),递归处理多个黑名单;最后丢掉宽<tw或高<th的碎片。
        注意上下带必须全宽、左右块只占黑名单的Y段(写反会让多条不同宽横带之间的干净区域被错误收窄=过度扣除)。
        无黑名单时原样返回[S]。"""
        x0, y0, x1, y1 = S
        rects = [[int(x0), int(y0), int(x1), int(y1)]]
        try:
            for _r in (self._role_rec or {}).get("blocklist", []):
                bx, by, bw, bh = int(_r[0]), int(_r[1]), int(_r[2]), int(_r[3])
                bx1, by1 = bx + bw, by + bh
                out = []
                for rx0, ry0, rx1, ry1 in rects:
                    if bx >= rx1 or bx1 <= rx0 or by >= ry1 or by1 <= ry0:  # 与该黑名单不相交→整块保留
                        out.append([rx0, ry0, rx1, ry1]); continue
                    ix0, ix1 = max(rx0, bx), min(rx1, bx1)  # 与黑名单重叠的X/Y段
                    iy0, iy1 = max(ry0, by), min(ry1, by1)
                    if iy0 > ry0:  # 上横带·全宽
                        out.append([rx0, ry0, rx1, iy0])
                    if iy1 < ry1:  # 下横带·全宽
                        out.append([rx0, iy1, rx1, ry1])
                    if ix0 > rx0 and iy1 > iy0:  # 黑名单Y段内·左侧块
                        out.append([rx0, iy0, ix0, iy1])
                    if ix1 < rx1 and iy1 > iy0:  # 黑名单Y段内·右侧块
                        out.append([ix1, iy0, rx1, iy1])
                rects = out
        except Exception:
            return [[int(x0), int(y0), int(x1), int(y1)]]
        return [[a, b, c, d] for a, b, c, d in rects if (c - a) >= tw and (d - b) >= th]

    def _role_anchor_pivot(self, key, tw, th):
        """返回锚点'所描多边形主体'相对外接png左上角的中心偏移(顶点质心);没poly就回退外接png中心。
        用户要求人脸/人名/后脑一律以'描出来的形状中心'为基点,而不是整张外接矩形的几何中心(形状偏画时会偏)。"""
        try:
            _r = self._role_rec or self._load_role_recognize()
            _pp = (_r or {}).get("anchors", {}).get(key, {}).get("poly")
            if _pp:
                _ox = int(round(sum(p[0] for p in _pp) / len(_pp)))
                _oy = int(round(sum(p[1] for p in _pp) / len(_pp)))
                return _ox, _oy
        except Exception:
            pass
        return tw // 2, th // 2

    def _role_match_in(self, frame, key, box=None):
        """在指定区域 box=(x0,y0,x1,y1)(None=整帧)内匹配单锚点→(score0~1, 锚点中心全局(x,y)或None, 朝向'L'/'R'/None)。
        名字/宠物名:区域V通道自适应二值成黑底白字再比(和采集OTSU笔画同源,抗半透明底板/换背景);
        面部:区域灰度匹配+朝右模板水平镜像再配一次、谁分高判朝向;后脑:灰度直配(爬梯脸朝里兜底)。"""
        try:
            if not self._role_has_anchor(key):
                return 0.0, None, None
            tpl = cv2.imdecode(np.fromfile(self._role_anchor_path(key), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if tpl is None or tpl.size == 0:
                return 0.0, None, None
            th, tw = tpl.shape[:2]
            H, W = frame.shape[:2]
            if box is None:
                # 全图重搜只搜活动带(拉黑顶部标题栏/底部血蓝技能UI栏),减小面积提速+防UI误匹配
                x0, y0, x1, y1 = 0, DETECT_TOP_MARGIN, W, max(DETECT_TOP_MARGIN + 1, H - DETECT_BOTTOM_MARGIN)
            else:
                x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
                x1, y1 = min(W, int(box[2])), min(H, int(box[3]))
            src = frame[y0:y1, x0:x1]
            if src.shape[0] < th or src.shape[1] < tw:
                return 0.0, None, None
            ox, oy = self._role_anchor_pivot(key, tw, th)  # 基点=所描形状中心(名字/脸/后脑统一)
            is_text = (key == "name") or key.startswith("pet")
            # 脸/后脑:模板多边形外圈填主体内平均灰度,CCOEFF减均值后外圈≈0贡献(固定图也能上分数);脸另备镜像定朝向
            tpl_m = None
            if not is_text:
                try:
                    _pp0 = (self._role_rec or {}).get("anchors", {}).get(key, {}).get("poly")
                    if _pp0:
                        _mk0 = np.zeros(tpl.shape[:2], np.uint8)
                        cv2.fillPoly(_mk0, [np.array(_pp0, np.int32)], 255)
                        if (_mk0 > 0).any():
                            tpl = tpl.copy(); tpl[_mk0 == 0] = int(tpl[_mk0 > 0].mean())
                except Exception:
                    pass
                if key == "face_r":
                    tpl_m = cv2.flip(tpl, 1)
            # 核心:搜索矩形几何扣除黑名单→只在剩余子矩形上滑窗比对(模板根本不扫黑名单那片),逐子矩形取全局最佳
            subs = self._role_sub_rects((x0, y0, x1, y1), tw, th)
            best_s, best_xy, best_face = -2.0, None, None
            _binc = getattr(self, '_role_bin_cache', None)  # name/pet二值化按子矩形缓存,同帧复用
            if not isinstance(_binc, dict):
                _binc = {}; self._role_bin_cache = _binc
            for (gx0, gy0, gx1, gy1) in subs:
                sub = frame[gy0:gy1, gx0:gx1]
                if sub.shape[0] < th or sub.shape[1] < tw:
                    continue
                if is_text:  # 名字/宠物名:V通道OTSU二值(黑底白字)再比,和采集同源
                    _ck = (id(frame), (gx0, gy0, gx1, gy1))
                    scene = _binc.get(_ck)
                    if scene is None:
                        scene = self._role_text_binarize(cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)[:, :, 2], denoise=False)
                        _binc[_ck] = scene
                        if len(_binc) > 48:
                            _binc.clear(); _binc[_ck] = scene
                    _, mv, _, ml = cv2.minMaxLoc(cv2.matchTemplate(scene, tpl, cv2.TM_CCOEFF_NORMED))
                    if float(mv) > best_s:
                        best_s, best_xy, best_face = float(mv), (gx0 + ml[0] + ox, gy0 + ml[1] + oy), None
                else:  # 脸/后脑:灰度比;脸再比镜像,谁高定朝向
                    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
                    _, sr, _, sl = cv2.minMaxLoc(cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED))
                    ss, ll, ff = float(sr), sl, "R"
                    if tpl_m is not None:
                        _, s2, _, l2 = cv2.minMaxLoc(cv2.matchTemplate(gray, tpl_m, cv2.TM_CCOEFF_NORMED))
                        if float(s2) > ss:
                            ss, ll, ff = float(s2), l2, "L"
                    if ss > best_s:
                        best_s, best_xy, best_face = ss, (gx0 + ll[0] + ox, gy0 + ll[1] + oy), ff
            if best_xy is None:  # 搜索区被黑名单全部扣除/都放不下模板
                return 0.0, None, None
            if self._role_blocked(best_xy[0], best_xy[1]):  # 双保险(几何扣除后理论不会命中框内)
                return 0.0, None, None
            return best_s, best_xy, best_face
        except Exception:
            return 0.0, None, None

    def _role_match_one(self, frame, key):
        """整帧匹配单锚点(管理窗实时识别率用)"""
        return self._role_match_in(frame, key, None)

    def _role_eval_live(self):
        """截一帧、对全部已采锚点各匹配一次,返回{scores:{key:(s,loc,face)}, best:(key,s,x,y,face)};供管理窗实时显示识别率。"""
        try:
            frame = self._capture_window()
            if frame is None:
                return None
            scores, best = {}, None
            for key in ROLE_ANCHOR_KEYS:
                s, loc, face = self._role_match_one(frame, key)
                scores[key] = (s, loc, face)
                if loc is not None and (best is None or s > best[1]):
                    best = (key, s, loc[0], loc[1], face)
            return {"scores": scores, "best": best}
        except Exception:
            return None

    def _role_remove_anchor(self, key):
        """移除某角色锚点:删模板图+删元数据+落盘"""
        try:
            p = self._role_anchor_path(key)
            if os.path.exists(p):
                os.remove(p)
        except Exception as e:
            print("[角色识别] 删除锚点图失败:", e)
        if self._role_rec and key in self._role_rec.get("anchors", {}):
            self._role_rec["anchors"].pop(key, None)
            self._save_role_recognize()
        if getattr(self, '_role_tpl_c', None) is not None:  # 移除后清模板缓存
            self._role_tpl_c.pop(key, None)

    def _role_pick_blocklist_region(self):
        """在游戏截图上拖一个矩形加入角色识别黑名单(框内不采信锚点命中,防固定UI/图标误检)。
        完全照抄角色锚点采集_capture_role_anchor的成熟窗口骨架:cv2 WINDOW_AUTOSIZE+moveWindow到游戏窗口+TOPMOST、
        先withdraw tk管理窗、setMouseCallback、while waitKey、finally里deiconify恢复管理窗。
        鼠标回调(x,y)永远是【截图内像素坐标】,与窗口在屏幕的位置/标题栏/DPI无关,而截图=_capture_window按window_rect抓、
        检测帧和_role_blocked判定、主蒙板客户区也都=window_rect坐标,四者同源天然1:1不偏移(透明分层蒙板colorkey像素鼠标会
        穿透、收不到左键,故不在蒙板上拖)。操作:左键拖矩形(可重拖),回车/空格确认,ESC或右键取消。"""
        win = "拉黑区域框选(左键拖框 回车确认 ESC取消)"
        rw = getattr(self, "_role_rec_window", None)
        ok = False
        added = None
        try:
            if self.hwnd is None:
                self._add_log("请先绑定游戏窗口"); return
            self._update_window_rect(); wr = self.window_rect
            if not wr or wr.get("left", 0) <= -30000 or wr.get("width", 0) < 200:
                self._add_log("游戏窗口未正常显示,无法框选"); return
            frame = self._capture_window()
            if frame is None:
                self._add_log("截图为空,请重试"); return
            H, W = frame.shape[:2]
            try:  # 隐藏tk管理窗,避免tk/cv2冲突闪退(同锚点采集)
                if rw is not None: rw.withdraw(); rw.update()
            except Exception:
                pass
            cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
            try:
                cv2.moveWindow(win, int(wr.get("left", 40)), int(wr.get("top", 40)))
                cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
            except Exception:
                pass
            st = {"x1": -1, "y1": -1, "x2": -1, "y2": -1, "drag": False, "cancel": False}

            def on_mouse(e, x, y, fl, p):
                x, y = int(x), int(y)
                if e == cv2.EVENT_LBUTTONDOWN:
                    st["drag"] = True; st["x1"], st["y1"], st["x2"], st["y2"] = x, y, x, y
                elif e == cv2.EVENT_MOUSEMOVE and st["drag"]:
                    st["x2"], st["y2"] = x, y
                elif e == cv2.EVENT_LBUTTONUP:
                    st["drag"] = False
                elif e == cv2.EVENT_RBUTTONDOWN:
                    st["cancel"] = True

            cv2.setMouseCallback(win, on_mouse)
            while True:
                disp = frame.copy()
                if st["x2"] >= 0:
                    _a, _b = min(st["x1"], st["x2"]), min(st["y1"], st["y2"])
                    _c, _d = max(st["x1"], st["x2"]), max(st["y1"], st["y2"])
                    cv2.rectangle(disp, (_a, _b), (_c, _d), (0, 0, 255), 2)
                cv2.imshow(win, disp)
                k = cv2.waitKey(20) & 0xFF
                if k == 27 or st["cancel"]:
                    st["cancel"] = True; break
                if k in (13, 32) and st["x2"] >= 0 and (st["x2"] != st["x1"] or st["y2"] != st["y1"]):
                    ok = True; break
            if ok:
                x0, y0 = min(st["x1"], st["x2"]), min(st["y1"], st["y2"])
                ww, hh = abs(st["x2"] - st["x1"]), abs(st["y2"] - st["y1"])
                if ww < 8 or hh < 8:
                    self._add_log("框选区域太小,请重新框选"); return
                added = [int(x0), int(y0), int(ww), int(hh)]
        except Exception as e:
            import traceback; traceback.print_exc(); print("[角色识别] 黑名单框选异常:", e)
            _debug_log("[角色识别] 黑名单框选异常: %s" % e)
        finally:
            try: cv2.destroyWindow(win)
            except Exception: pass
            for _ in range(2):
                try: cv2.waitKey(20)
                except Exception: pass
            try:  # 恢复tk管理窗(同锚点采集收尾)
                if rw is not None: rw.deiconify(); rw.lift(); rw.update()
            except Exception: pass
        if added is not None:
            self._role_rec.setdefault("blocklist", []).append(added)
            self._save_role_recognize()
            self._add_log("已加角色黑名单 %s" % added)
            if hasattr(self, "_role_refresh_blocklist"):
                try: self._role_refresh_blocklist()
                except Exception: pass

    def _open_role_recognize_window(self):
        """打开「角色识别」管理窗(2026-09-13):全局锚点采集/移除+缩略图+8项跟踪参数。
        入口=控制面板"人物特征"按钮BTN_CHAR(替代旧小块人物特征窗)。数据全局长期保存、启动直接加载,不随地图方案变。"""
        import tkinter as tk
        from tkinter import ttk, simpledialog, messagebox
        from PIL import Image, ImageTk
        if not self._ensure_tk_root():
            return
        if getattr(self, "_role_rec_window", None) is not None:  # 单例:已开则提到最前
            try:
                self._role_rec_window.lift(); return
            except Exception:
                pass
        if self._role_rec is None:
            self._load_role_recognize()
        win = tk.Toplevel(self._tk_root)
        self._role_rec_window = win
        win.title("角色识别")
        win.resizable(False, False)  # 固定大小不拉伸,文字不变形;标题栏可拖动
        win.attributes("-topmost", True)
        self._position_window(win, 600, 740)
        self._role_thumbs = []  # 持有PhotoImage引用防被GC导致缩略图不显示

        tk.Label(win, text="角色识别（小锚点多冗余 · 局部半径跟踪）",
                 font=("微软雅黑", 11, "bold")).pack(pady=(8, 2))
        self._role_live_var = tk.StringVar(value="实时锚点：（采好锚点、游戏画面可见角色时，这里显示坐标 / 识别率 / 朝向）")
        self._role_live_lbl = tk.Label(win, textvariable=self._role_live_var, font=("微软雅黑", 9, "bold"),
                                       fg="#1565C0", bg="#E3F2FD")
        self._role_live_lbl.pack(fill="x", padx=8, pady=2)
        tk.Label(win, text="优先顺序：角色名 → 宠物名1/2/3 → 面部/后脑。面部只采朝右一张，朝左由程序水平镜像自动生成。采集：左键点目标中心放大2倍 → 在放大框内点4点自动闭合 → 点白线加点/拖点微调 → 空格确认。",
                 font=("微软雅黑", 8), fg="gray", wraplength=570, justify="left").pack(pady=(0, 4))

        # ===== 角色方案(以角色为单位整套保存,最多10套;切换=换整套锚点;跟踪参数/黑名单全局共用,不随套变) =====
        char_outer = tk.LabelFrame(win, text="角色方案（整套保存·最多10套·满了新建自动删最旧）", font=("微软雅黑", 9, "bold"))
        char_outer.pack(fill="x", padx=8, pady=(2, 4))
        crow = tk.Frame(char_outer); crow.pack(fill="x", padx=6, pady=3)
        tk.Label(crow, text="当前角色", font=("微软雅黑", 9)).pack(side="left")
        self._role_char_var = tk.StringVar()
        self._role_char_combo = ttk.Combobox(crow, textvariable=self._role_char_var, state="readonly",
                                             width=14, font=("微软雅黑", 9))
        self._role_char_combo.pack(side="left", padx=4)

        def _on_pick_char(_evt=None):  # 下拉选某套→切为当前(select内部会刷新下拉选中与锚点列表)
            i = self._role_char_combo.current()
            chars = self._role_rec.get("characters", [])
            if 0 <= i < len(chars):
                self._role_select_character(chars[i]["id"])

        def _do_new():  # 新建空套并切过去(满10套时helper自动删最旧)
            self._role_new_character()

        def _do_rename():
            chars = self._role_rec.get("characters", []); i = self._role_char_combo.current()
            if not (0 <= i < len(chars)):
                return
            c = chars[i]
            nm = simpledialog.askstring("改名", "角色套名称：", initialvalue=c.get("name", ""), parent=win)
            if nm:
                self._role_rename_character(c["id"], nm); _rebuild_chars()

        def _do_del():
            chars = self._role_rec.get("characters", []); i = self._role_char_combo.current()
            if not (0 <= i < len(chars)):
                return
            if len(chars) <= 1:
                messagebox.showinfo("提示", "至少保留一套，不能删除最后一套", parent=win); return
            if messagebox.askyesno("删除整套", "确定删除「%s」？该套全部锚点图都会删除" % chars[i].get("name"), parent=win):
                self._role_delete_character(chars[i]["id"])  # delete内部会切到剩余最新套并刷新
        tk.Button(crow, text="新建", width=6, command=_do_new).pack(side="left", padx=2)
        tk.Button(crow, text="改名", width=6, command=_do_rename).pack(side="left", padx=2)
        tk.Button(crow, text="删除", width=6, command=_do_del).pack(side="left", padx=2)

        def _rebuild_chars():  # 按数据重建下拉项并选中当前套(程序化current不触发选中事件,不会递归)
            chars = self._role_rec.get("characters", [])
            names = [c.get("name", "角色") for c in chars]
            self._role_char_combo.config(values=names)
            aid = self._role_rec.get("active")
            ci = next((i for i, c in enumerate(chars) if c.get("id") == aid), 0)
            if names:
                self._role_char_combo.current(ci); self._role_char_var.set(names[ci])
        self._role_char_combo.bind("<<ComboboxSelected>>", _on_pick_char)
        self._role_refresh_chars = _rebuild_chars
        _rebuild_chars()

        self._role_anchor_frame = tk.Frame(win)
        self._role_anchor_frame.pack(fill="x", padx=8)

        # ===== 跟踪参数区(可调,关窗统一落盘) =====
        param_outer = tk.LabelFrame(win, text="角色跟踪参数（可调）", font=("微软雅黑", 9, "bold"))
        param_outer.pack(fill="x", padx=8, pady=6)
        self._role_param_vars = {}
        params = self._role_rec["params"]
        for i, (k, label, is_float) in enumerate(ROLE_TRACK_FIELDS):
            r, c = divmod(i, 2)
            cell = tk.Frame(param_outer); cell.grid(row=r, column=c, sticky="w", padx=10, pady=3)
            tk.Label(cell, text=label, width=10, anchor="w", font=("微软雅黑", 9)).pack(side="left")
            var = tk.StringVar(value=str(params.get(k, ROLE_TRACK_DEFAULT[k])))
            self._role_param_vars[k] = var
            tk.Entry(cell, width=8, textvariable=var, font=("微软雅黑", 9)).pack(side="left")

        def _apply_params():
            try:
                for (k, label, is_float) in ROLE_TRACK_FIELDS:
                    v = self._role_param_vars[k].get().strip()
                    dv = ROLE_TRACK_DEFAULT[k]
                    if v == "":
                        self._role_rec["params"][k] = dv; continue
                    self._role_rec["params"][k] = float(v) if isinstance(dv, float) else int(float(v))
                self._save_role_recognize()
            except Exception as e:
                print("[角色识别] 参数保存失败:", e)
        self._role_apply_params = _apply_params

        def _rebuild_anchors():
            for w in self._role_anchor_frame.winfo_children():
                w.destroy()
            self._role_thumbs = []
            self._row_score_lbl = {}
            anchors = self._role_rec.get("anchors", {})
            for key, cn, desc in ROLE_ANCHORS:
                row = tk.Frame(self._role_anchor_frame); row.pack(fill="x", pady=2)
                has = self._role_has_anchor(key)
                locked = (key == "pet2" and not self._role_has_anchor("pet1")) or \
                         (key == "pet3" and not self._role_has_anchor("pet2"))  # 宠物名按顺序解锁
                def do_cap(k=key):
                    win.update(); self._capture_role_anchor(k)  # 采集器内部会withdraw/恢复并回调刷新
                def do_rm(k=key):
                    self._role_remove_anchor(k); _rebuild_anchors()
                tk.Button(row, text="采集", width=6, state=("disabled" if locked else "normal"),
                          command=do_cap).pack(side="left")
                tk.Button(row, text="移除", width=6, state=("normal" if has else "disabled"),
                          command=do_rm).pack(side="left", padx=(2, 6))
                tk.Label(row, text=cn, width=14, anchor="w", font=("微软雅黑", 9, "bold")).pack(side="left")
                if has:
                    m = anchors.get(key, {})
                    tk.Label(row, text="已采 %dx%d" % (m.get("w", 0), m.get("h", 0)), fg="green",
                             font=("微软雅黑", 8)).pack(side="left")
                    sl = tk.Label(row, text="--%", width=7, anchor="w", fg="gray",
                                  font=("微软雅黑", 8, "bold"))
                    sl.pack(side="left", padx=(8, 0)); self._row_score_lbl[key] = sl  # 每行实时识别率
                    try:  # 锚点缩略图
                        im = Image.open(self._role_anchor_path(key)); im.thumbnail((48, 48))
                        ph = ImageTk.PhotoImage(im); self._role_thumbs.append(ph)
                        tk.Label(row, image=ph).pack(side="right")
                    except Exception:
                        pass
                else:
                    tk.Label(row, text=("未采 · " + ("请先采集上一级宠物名" if locked else desc)),
                             fg="gray", font=("微软雅黑", 8), wraplength=380, justify="left").pack(side="left")
        self._role_refresh_window = _rebuild_anchors
        _rebuild_anchors()

        # 实时识别率:直接读检测线程现成分数刷新控件。【角色窗彻底不用Tk after定时器】拖动标题栏时Windows进入
        # 模态移动循环,after回调会在其中嵌套进入"不可重入"的Tcl解释器→进程直接退出(faulthandler都抓不到栈,
        # 这正是"角色窗一移动就闪退"的根因)。改为OpenCV主循环在左键松开(=没在拖窗)的安全时机每500ms直接调
        # self._role_live_do一次,和其他不崩的弹窗一样窗内无任何定时器。
        _cn_map = {k: c for k, c, _ in ROLE_ANCHORS}

        def _do_refresh():
            try:
                thr = float(self._role_rec.get("params", {}).get("thr", ROLE_TRACK_DEFAULT["thr"]))
                scores = getattr(self, "_role_last_scores", {}) or {}  # 读检测线程现成分数,不自己抓帧
                for _k, _lbl in getattr(self, "_row_score_lbl", {}).items():  # 每行实时识别率
                    _t = scores.get(_k)
                    if _t is not None:
                        _ss = _t[0]
                        _lbl.config(text="%d%%" % int(_ss * 100),
                                    fg=("#2E7D32" if _ss >= thr else "#E65100"))
                    else:
                        _lbl.config(text="--%", fg="gray")
                _cand = [(v[0], k, v) for k, v in scores.items()]
                if _cand:
                    bs, bk, _t = max(_cand, key=lambda z: z[0])
                    bx, by, face = _t[1][0], _t[1][1], _t[2]
                    fa = "朝右" if face == "R" else ("朝左" if face == "L" else "")
                    self._role_live_var.set("实时锚点：X%d / Y%d · %d%% · %s %s" % (bx, by, int(bs * 100), _cn_map.get(bk, bk), fa))
                    self._role_live_lbl.config(fg=("#2E7D32" if bs >= thr else "#E65100"),
                                               bg=("#E8F5E9" if bs >= thr else "#FFF3E0"))
                else:
                    self._role_live_var.set("实时锚点：当前画面未识别到已采锚点")
                    self._role_live_lbl.config(fg="#9E9E9E", bg="#F5F5F5")
            except Exception:
                pass
        self._role_live_do = _do_refresh   # 主循环持有的刷新闭包;关窗置None即停
        self._role_live_next = 0.0         # 下次允许刷新的时间戳(主循环侧节流500ms)

        def on_close():
            self._role_live_do = None  # 先断开主循环刷新闭包,避免关窗后还去config已销毁控件
            _apply_params(); self._close_window("_role_rec_window")
        # ===== 角色识别黑名单(放最下方:框内不采信任何锚点命中,防固定UI/图标误检) =====
        blk_outer = tk.LabelFrame(win, text="黑名单区域（默认只屏蔽人物锚点；勾选后怪物YOLO也屏蔽；可框多处同时生效）", font=("微软雅黑", 9, "bold"))
        blk_outer.pack(fill="x", padx=8, pady=4, side="bottom")
        blk_top = tk.Frame(blk_outer); blk_top.pack(fill="x", padx=6, pady=2)
        self._role_blk_list_frame = tk.Frame(blk_outer); self._role_blk_list_frame.pack(fill="x", padx=6)

        def _rebuild_blocklist():
            for w in self._role_blk_list_frame.winfo_children():
                w.destroy()
            bl = self._role_rec.get("blocklist", [])
            if not bl:
                tk.Label(self._role_blk_list_frame, text="（暂无·点左侧在游戏画面框选要屏蔽的区域）", fg="gray",
                         font=("微软雅黑", 8)).pack(anchor="w")
            for i, rr in enumerate(bl):
                row = tk.Frame(self._role_blk_list_frame); row.pack(fill="x", pady=1)

                def do_del(idx=i):
                    self._role_rec["blocklist"].pop(idx); self._save_role_recognize(); _rebuild_blocklist()
                tk.Label(row, text="#%d  x%d y%d %d×%d" % (i + 1, rr[0], rr[1], rr[2], rr[3]), width=22,
                         anchor="w", font=("微软雅黑", 8)).pack(side="left")
                tk.Button(row, text="删除", width=5, command=do_del).pack(side="left")
        self._role_refresh_blocklist = _rebuild_blocklist
        tk.Button(blk_top, text="在画面框选添加", width=14,
                  command=self._role_pick_blocklist_region).pack(side="left")

        def _clear_blk():
            self._role_rec["blocklist"] = []; self._save_role_recognize(); _rebuild_blocklist()
        tk.Button(blk_top, text="清空全部", width=10, command=_clear_blk).pack(side="left", padx=6)
        _blk_mon_var = tk.BooleanVar(value=bool(self._role_rec.get("blocklist_monster", False)))  # 默认只对人物,勾选才对怪
        def _toggle_blk_mon():
            self._role_rec["blocklist_monster"] = bool(_blk_mon_var.get()); self._save_role_recognize()
        tk.Checkbutton(blk_top, text="对怪物也生效", variable=_blk_mon_var,
                       command=_toggle_blk_mon, font=("微软雅黑", 8)).pack(side="left", padx=6)
        _rebuild_blocklist()

        win.protocol("WM_DELETE_WINDOW", on_close)
        tk.Button(win, text="保存并关闭", width=16, height=2, bg="#2196F3", fg="white",
                  command=on_close).pack(side="bottom", pady=8)

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

    def _lock_recorded_ladder_endpoints(self, px, py):
        """进to_ladder当下直接锁一把【小地图录制梯】(用户2026-09-15:梯子是小地图一点点录的,
        每把天生带最上y_top/最下y_bottom和x)。按梯底端离人物光点Y近、再X近选一把,一次钉死端点;
        到顶判定=人物光点中心Y与y_top重合(容差LADDER_TOP_ARRIVE_TOL),不需要屏幕白框、不需要借Y。钉到返回True。"""
        lds = getattr(self, 'ladders', None)
        if not lds:
            return False
        ld = min(lds, key=lambda t: (abs(float(t['y_bottom']) - float(py)), abs(float(t['x']) - float(px))))
        self._climb_ladder_x = float(ld['x'])
        self._climb_ladder_y_top = float(ld['y_top'])
        self._climb_ladder_y_bottom = float(ld['y_bottom'])
        self._climb_top_end_borrowed = True
        _debug_log("[选梯·小地图] 光点(%.0f,%.0f)锁定录制梯x=%.0f 顶=%.0f 底=%.0f,到顶直接比光点Y与梯顶" % (
            px, py, float(ld['x']), float(ld['y_top']), float(ld['y_bottom'])))
        return True

    def _find_nearest_ladder(self, px, py, target_y, monster_x=None):
        """找最近的可用梯子（2026-09-11"锁定梯子"定稿：选梯那一下由怪发出 怪→梯→人,锁整把梯后不再依赖怪）
        硬门槛：连接端Y必须和目标层Y重合(±1)——上行看顶端y_top、下行看底端y_bottom,差>1=通向别的层直接排除(治在错梯下空跳)。
        阶段1【怪→梯:离怪最近定目标】：所有Y±1合格梯(不管当前够不够得着)里,离目标怪X最近的那把=真正连怪层的目标梯并【锁死】;
              已锁梯且它仍Y合格→跨层恒定沿用、绝不帧间横跳。monster_x=选梯那一下的怪小地图X(怪发出);未传则取已锁梯/transit目标。
        阶段2【梯→人:离人最近选当前跳】：目标梯现在够得着就直接上;够不着(人在更下层需中转)先上离人最近的合格梯,逐层接近。
        全用小地图坐标；px/py=人物光点,target_y=目标层Y。"""
        going_up = target_y < py   # 小地图Y越小越靠上
        # 目标怪小地图X(怪→梯的第一段,只在选梯那下用):显式传入>已锁梯X>transit终点>人物X
        _ll0 = getattr(self, '_locked_ladder', None)
        if monster_x is not None:
            target_x = float(monster_x)
        elif _ll0 is not None:
            target_x = float(_ll0["x"])
        else:
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
            # 下行也锁梯(用户2026-09-11):已锁且梯还在→恒定沿用不横跳;没锁才按"够得着优先、离人最近"选一把并锁
            _lld = getattr(self, '_locked_ladder', None)
            _pick_t = None
            if _lld is not None:
                for _t in _dn:
                    if abs(_t[2]["x"] - _lld["x"]) <= LADDER_DEL_X_TOL:
                        _pick_t = _t
                        break
            if _pick_t is None:
                _dn_reach = [t for t in _dn if t[1]]
                _pick_t = min(_dn_reach, key=lambda t: t[0]) if _dn_reach else min(_dn, key=lambda t: t[0])
                if _lld is None:
                    self._locked_ladder = dict(_pick_t[2])
                    _debug_log("[选梯] 下行锁定目标梯x=%.0f(本次跨层固定不换)" % _pick_t[2]["x"])
            _debug_log("[选梯] 下行不要求Y对齐,选梯x=%.0f(离人%d,%s)" % (
                _pick_t[2]["x"], _pick_t[0], "当前够得着" if _pick_t[1] else "无够得着梯放宽取最近"))
            return _pick_t[2]
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
        # 阶段1【怪→梯】离怪X最近=连怪层的目标梯。【锁定梯子·用户2026-09-11】已锁过且它仍是Y合格梯→
        # 跨层恒定沿用、绝不在两把近邻梯间帧间横跳;没锁过才按(离怪X差,离人X差)确定性选一把并锁【整把梯】,直到解绑。
        _ll = getattr(self, '_locked_ladder', None)
        anchor = None
        if _ll is not None:
            for _t in allY:
                if abs(_t[3]["x"] - _ll["x"]) <= LADDER_DEL_X_TOL:
                    anchor = _t
                    break
        if anchor is None:
            anchor = min(allY, key=lambda t: (t[0], t[1]))   # 怪→梯离怪最近优先,并列再比梯→人离人近=确定性不抖
            self._locked_ladder = dict(anchor[3])            # 锁整把梯(含x/y_top/y_bottom),引路终点取其连接端,不再依赖怪
            _debug_log("[选梯] 阶段1锁定目标梯(本次跨层固定不换): x=%.0f 顶=%.0f 底=%.0f 离怪X差=%d 离人X差=%d" % (
                anchor[3]["x"], anchor[3]["y_top"], anchor[3]["y_bottom"], anchor[0], anchor[1]))
        else:
            _debug_log("[选梯] 阶段1沿用已锁定目标梯: x=%.0f 离怪X差=%d" % (anchor[3]["x"], anchor[0]))
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
        self._ladder_precise_mode = False   # 退出上梯:检测线程恢复正常120ms全检测档(用户2026-09-10方案B)
        self._ladder_snap_x = None          # 出梯清空选中梯屏幕X,下把重新就近选(用户2026-09-15)
        self._ladder_target_mon_x = None   # 出梯清冻结目标怪屏幕X
        self._lad_scr_enter_t = 0
        self._climb_top_end_borrowed = False  # 到顶梯端Y是否已从录制梯借好(每把梯只借一次)
        self._climb_ladder_x = 0
        self._climb_ladder_y_top = 0      # 当前爬的梯子顶端Y（小地图，到顶验证用）
        self._climb_ladder_y_bottom = 0   # 当前爬的梯子底端Y（小地图，到底验证用）
        self._climb_record_scr_y = None   # 抓住梯子那一下冻结的"记录坐标点"主窗口Y(到顶三信号投票·票2用,怪空/脱检也在)
        self._climb_target_y = 0
        self._climb_target_x = 0
        self._climb_direction = 0
        self._climb_start_y = 0
        self._climb_action_time = 0
        # 下行descend子状态复位(用户2026-09-09)
        self._desc_phase = None
        self._desc_base_y = 0
        self._desc_phase_t = 0
        self._desc_ref_px = None
        self._desc_stall_t = 0
        self._desc_jumped = False
        self._desc_j2 = False
        self._desc_leap_dir = 1
        self._desc_pre_leap_sy = None    # 方式一:左右跳前人物特征屏幕Y基准复位
        self._desc_pre_leap_my = 0
        # 方式二段2主窗口白框精对位状态复位(用户2026-09-10)
        self._desc_scr_key_vk = None
        self._desc_scr_key_t = 0
        self._desc_scr_key_hold = 0
        self._desc_scr_nudge_t = 0
        self._desc_scr_nudge_t = 0
        self._desc_scr_nudge_n = 0
        self._desc_scr_nudge_step = 0
        self._desc_scr_nudge_from_x = None
        self._desc_scr_nudge_gap = 100
        self._desc_scr_ok_frames = 0
        self._desc_scr_last_x = None
        self._desc_scr_last_t = 0
        self._desc_scr_enter_t = 0
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
        self._slope_phase = 'wait_jump'                # 跳高打(极简循环·用户2026-09-11)：当前等哪个动作 'wait_jump'=该跳了 / 'wait_attack'=该攻击了
        self._slope_next_at = 0                        # 跳高打：下一动作(跳/攻击)的最早时刻ms,到点就执行,无冷却概念只有节奏延时
        self._slope_resume_at = 0                      # 跳高打：跨层爬梯到顶后保护截止(ms)，此时间前不启用跳高打(防刚翻上梯顶没站稳被跳下来,用户2026-09-09)
        self._slope_ref = None                         # 跳高打：当前钉住的高处参照怪(cx,cy),同层不每帧换X最近怪(治移动/出手方向左右碎步,用户2026-09-11);脱检/离开区间/走远才重选
        self._move_stuck_inited = False  # 爬梯结束重置卡住检测
        # 主窗口梯子模板"屏幕X精对齐"状态复位(用户2026-09-09)
        self._lad_scr_ok_frames = 0
        self._lad_scr_key_vk = None
        self._lad_scr_key_t = 0
        self._lad_scr_nudge_t = 0
        self._lad_scr_ref_spx = None
        self._lad_scr_stall_t = 0
        self._lad_scr_stall_n = 0
        self._lad_scr_nomove_n = 0       # 碎步"按了没动"监管计数复位(用户2026-09-11)
        self._lad_scr_running = False   # 大步助跑态复位(跑跳穿越触发用,用户2026-09-10)
        self._lad_scr_nudge_n = 0        # 碎步已按拍数复位(最多3拍)
        self._lad_scr_key_hold = 0       # 当前拍按住时长复位
        self._lad_scr_nudge_step = 0     # 定长点动·当前拍位移上限px复位(0=非点动拍)
        self._lad_scr_nudge_from_x = None  # 定长点动·当前拍起点屏幕X复位
        self._lad_scr_nudge_gap = 100    # 定长点动·抬起后停顿ms复位
        self._lad_scr_prev_asdx = None   # 上一检测周期人梯X差(自适应跑跳趋近速度),复位
        self._lad_scr_last_x = None      # 上次屏幕模板匹配到的稳定梯X(丢帧粘滞),复位
        self._lad_scr_last_t = 0
        self._lad_scr_enter_t = 0        # 进入屏幕对位的时刻(红框白框合并等待计时),复位
        self._ladder_run_dir = 1        # 跑跳空中趋近方向(屏幕:右1/左-1)
        self._ladder_run_t0 = 0         # 跑跳起跳时刻(抓梯1秒窗口从这起算)
        # 登顶三背景点状态复位
        self._climb_box_prev = [None, None, None]
        self._climb_box_centers = [None, None, None]
        self._climb_still_since = 0
        self._climb_move_confirmed = False   # 两步法:复位"已确认在爬",下次抓梯重新走第一步
        self._climb_top_hold = False         # 到顶补按200ms子态复位
        self._climb_top_hold_t = 0
        self._climb_y_align_since = 0
        self._climb_min_y = 0
        self._climb_ystop_since = 0
        self._climb_ever_moved = False   # 复位真移动锁存,下次抓梯重新累计
        self._ladder_snap_x = None           # 每帧实时选中梯的真实屏幕X,出梯清空
        # === 梯子失败集合(70%×3轮校准)状态复位(用户2026-09-14) ===
        self._ladder_realign_round = 0       # 失败集合已开始的移动轮数(每进入一次move段+1,最多3)
        self._ladder_realign_phase = None    # 'move'走剩余70% / 'gap'抬键停顿 / 'align'等连续达标帧
        self._ladder_realign_t = 0           # 当前阶段开始时刻/本轮随机停顿截止
        self._ladder_realign_gap_to = 0      # 本轮抬键停顿截止时刻ms
        self._ladder_realign_from_x = None   # 本轮移动起点·人物屏幕X
        self._ladder_realign_px = 0        # 本轮计划移动屏幕px(=进入时剩余*0.7)
        self._ladder_realign_key_vk = None   # 本轮按住的方向键vk
        self._ladder_realign_ok_frames = 0   # 达标连续帧计数
        self._ladder_realign_no_tpl_since = 0  # 拿不到梯子屏幕X的起始时刻(超时回主线)
        # === 上梯集合到顶·三背景点静止(第一道)状态复位(用户2026-09-14:先背景不动、再光点重合梯顶) ===
        self._climb_bg_still_since = 0       # 三背景点连续静止起始时刻ms(0=还在动/未开始计)
        self._climb_bg_ok = False            # 背景已确认静止CLIMB_STILL_MS(第一道,确认在爬之后才允许锁存)

    def _pre_teleport_release(self):
        """瞬移前置(用户2026-09-11):这个游戏攻击动作没停下前,瞬移等很多动作做不出来(攻击硬直会吞键)。
        所以瞬移前必须①松开连续按住的主攻键;②物理兜底再松一次主攻键(防点按攻击残余);③留一段前摇再瞬移。"""
        try:
            self._release_attack_key()           # 松连续主攻(连放按住的那把)
        except Exception:
            pass
        try:
            _ak = self._get_fight_config().get("atk1_key", "")
            if _ak:
                _vk = self._key_to_vk(_ak)
                if _vk is not None:
                    self._send_win_key(_vk, keyup=True)   # 物理兜底再松一次,防点按攻击还没抬
        except Exception:
            pass
        time.sleep(TP_ATK_RELEASE_MS / 1000.0)   # 前摇:等攻击硬直过去再瞬移

    def _do_teleport(self, current_y):
        """执行一次瞬移：先松攻击+前摇,再按方向键+瞬移技能键"""
        fight_cfg = self._get_fight_config()
        tp_key = fight_cfg.get("teleport_key", "")
        if not tp_key:
            return
        self._pre_teleport_release()   # 瞬移前先松攻击键+前摇(攻击硬直会吞瞬移)
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
        跳后50ms按↑不松+松左右(原地直跳/固定点6跑跳统一50ms，先松↓上下互斥) → 抓梯窗口LADDER_GRAB_WINDOW_MS(1秒)内
        只和【起跳前站地基准Y】比：任一帧Y变小≥LADDER_GRAB_UP_TOL=抓住,锁存转climbing一直按↑(中间帧镜头回弹不判错)；
        走到窗口上限全程没变小=没抓住，松↑重置回正常找怪（锁定的台子怪不放弃，会再引上来）。"""
        step = getattr(self, '_ladder_post_jump_step', 'delay1')
        start_t = getattr(self, '_ladder_post_jump_t', now_ms)

        # ===== 跑跳固定时序(用户2026-09-14):起跳当帧已松左右、按住↑;这里持续按住↑满RUNJUMP_GRAB_WINDOW_MS(=1秒),
        #       期间不判Y;满1秒那一刻只和【起跳前站地Y】比——Y变小=抓住接上梯集合(climbing),没变小=放开↑进失败集合 =====
        if step == 'run_hold':
            # 全程只保持↑、左右绝不重按(防水平惯性冲过梯子)
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            if VK_UP not in self._random_move_keys:
                self._key_down(VK_UP)
            if now_ms - start_t < RUNJUMP_GRAB_WINDOW_MS:
                return False   # 按住↑未满1秒,不检测Y
            # —— 满1秒:检测Y并放开↑ ——
            if VK_UP in self._random_move_keys:
                self._key_up(VK_UP)
            if py < self._climb_start_y - LADDER_GRAB_UP_TOL:
                # Y变小=跑跳抓住→接上梯集合(climbing段开头会重新按住↑一直爬到顶)
                self._release_move_conflicts()
                self._climb_state = 'climbing'
                self._climb_action_time = now_ms
                self._climb_start_y = py
                _ltrec = getattr(self, '_combat_locked_target', None)
                self._climb_record_scr_y = _ltrec[1] if _ltrec else None
                self._climb_move_confirmed = False
                self._climb_still_since = 0
                self._climb_bg_ok = False
                self._climb_bg_still_since = 0
                self._climb_top_hold = False
                self._climb_top_hold_t = 0
                self._climb_y_align_since = 0
                self._climb_min_y = py
                self._climb_ystop_since = 0
                self._climb_ever_moved = False
                self._ladder_vert_fail_count = 0
                self._ladder_backoff = None
                self._ladder_jump_phase = None
                self._ladder_post_jump_step = None
                _debug_log("[爬梯·屏幕·跑跳] 按↑满1秒Y变小(%.0f→%.0f)=抓住,接上梯集合持续爬到顶" % (self._climb_start_y, py))
                self._rlog("跑跳抓住梯子,持续向上到顶", LOG_OK, log='behavior')
                return False
            # 满1秒Y没变小=没抓住→松键进失败集合(70%×3轮校准直跳)
            _debug_log("[爬梯·屏幕·跑跳] 按↑满1秒Y=%.0f未比起跳基准%.0f小=没抓住,放开↑进失败集合" % (py, self._climb_start_y))
            self._key_up(VK_LEFT)
            self._key_up(VK_RIGHT)
            return self._ladder_enter_realign(py, now_ms, "跑跳1秒没抓住")

        if step == 'delay1':
            # 起跳后延时再按↑：用户2026-09-10定稿,原地直跳/固定点跑跳统一跳后50ms按↑(原直跳100/固定点150),更早抓梯
            _is_vert = getattr(self, '_ladder_vert_jumped', False) and not getattr(self, '_ladder_run_jumped', False)
            _up_delay = 50
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
            _ltrec2 = getattr(self, '_combat_locked_target', None)  # 直跳抓住:冻结记录坐标点主窗口Y(到顶票2)
            self._climb_record_scr_y = _ltrec2[1] if _ltrec2 else None
            self._climb_move_confirmed = False   # 两步法:刚抓住=第一步起步,先确认真的在爬,未确认前背景静止不算到顶
            self._climb_still_since = 0
            self._climb_bg_ok = False           # 上梯集合第一道:刚抓住,背景静止重新计(用户2026-09-14)
            self._climb_bg_still_since = 0
            self._climb_top_hold = False
            self._climb_top_hold_t = 0
            self._climb_y_align_since = 0
            self._climb_min_y = py
            self._climb_ystop_since = 0
            self._climb_ever_moved = False
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
        _el = now_ms - start_t
        _fell_back = _el >= LADDER_GRAB_FAIL_MIN_MS and py >= self._climb_start_y - 1
        if not _fell_back and _el < LADDER_GRAB_WINDOW_MS:
            if VK_UP not in self._random_move_keys:
                self._key_down(VK_UP)  # 还在上升/抓梯窗口内:继续按住↑等,镜头回弹帧忽略
            return False
        # 直跳没抓住(用户2026-09-14):不回主线,进【失败集合】移动剩余70%→停→达标直跳,最多3轮,轮满才回主线打怪
        if VK_UP in self._random_move_keys:
            self._key_up(VK_UP)
        _debug_log("[爬梯] 直跳%dms后Y=%.0f回落基准%.0f=没抓住,进失败集合校准" % (_el, py, self._climb_start_y))
        return self._ladder_enter_realign(py, now_ms, "直跳没抓住")

    def _ladder_enter_realign(self, py, now_ms, why):
        """进入/重回【梯子失败集合】(用户2026-09-14):起跳后Y没变小=没抓住梯子时调用,不回主线打怪。
        每"开始一次70%移动"算一轮(move段内+1),最多LADDER_REALIGN_MAX_ROUNDS轮;已满轮仍要进=三次都没成,
        松键、置短冷却、回主线重新算怪距。进入时保持_climb_state='to_ladder'、相位切realign(被_is_lock_frozen硬冻,不打怪不巡路)。"""
        for _vk in (VK_UP, VK_LEFT, VK_RIGHT):
            if _vk in self._random_move_keys:
                self._key_up(_vk)
        if self._ladder_realign_round >= LADDER_REALIGN_MAX_ROUNDS:
            _debug_log("[失败集合] 已%d轮校准仍没抓住(%s),放弃回主线重新算怪距打怪"
                       % (self._ladder_realign_round, why))
            self._rlog("梯子校准%d轮没挂上,回主线打怪" % self._ladder_realign_round, LOG_RED, log='behavior')
            self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
            self._reset_climb()
            self._decide_climb_fail_action()
            return False
        # 锁存跑跳已用(失败集合只走对齐直跳)、开放重新直跳;相位realign硬冻,从move段开下一轮(move内round+1)
        self._ladder_run_jumped = True
        self._ladder_vert_jumped = False
        self._lad_scr_running = False
        self._ladder_precise_mode = True   # 失败集合全程彻底关怪物扫描,直到3轮失败_reset_climb/成功到顶才恢复(用户2026-09-14)
        self._ladder_jump_phase = 'realign'
        self._ladder_post_jump_step = None
        self._ladder_realign_phase = 'move'
        self._ladder_realign_from_x = None
        self._ladder_realign_px = 0
        self._ladder_realign_key_vk = None
        self._ladder_realign_ok_frames = 0
        self._ladder_realign_no_tpl_since = 0
        self._ladder_realign_t = now_ms
        _debug_log("[失败集合] 进校准(原因=%s,已用轮=%d/%d):下一轮走剩余70%%→停下→检测直跳"
                   % (why, self._ladder_realign_round, LADDER_REALIGN_MAX_ROUNDS))
        return False

    def _realign_release_move(self):
        """失败集合内统一抬掉左右移动键(幂等,不碰↑/攻击)。"""
        for _vk in (VK_LEFT, VK_RIGHT):
            if _vk in self._random_move_keys:
                self._key_up(_vk)
        self._ladder_realign_key_vk = None

    def _ladder_realign_step(self, py, now_ms):
        """【梯子失败集合】每帧(用户2026-09-14定稿):move走当前剩余屏幕X差的70%→gap抬键停稳→align连续达标就原地直跳;
        直跳后交_ladder_post_jump_process判Y:Y变小=抓住接上梯集合,没变小再回本集合开下一轮;满3轮由enter回主线。坐标用主窗口屏幕X。"""
        sp = self._player_screen_pos
        # 取梯子屏幕X:优先吸附稳定值_ladder_snap_x,否则用梯子模板现匹配(和to_ladder屏幕对位同一来源)
        if self._raw_frame is None or sp is None or not getattr(self, '_ladder_templates', None):
            if self._ladder_realign_no_tpl_since == 0:
                self._ladder_realign_no_tpl_since = now_ms
            elif now_ms - self._ladder_realign_no_tpl_since >= LADDER_REALIGN_NO_TPL_MS:
                _debug_log("[失败集合] 连续%dms无帧/无梯子模板,回主线" % LADDER_REALIGN_NO_TPL_MS)
                return self._ladder_enter_realign(py, now_ms, "无梯子屏幕模板")
            self._realign_release_move()
            return False
        # 每帧现匹配梯子屏幕X(人物横移时镜头会跟随、梯X会变,不能一直用旧吸附值);匹配不到才短期沿用上一次稳定值
        _lkx = getattr(self, '_ladder_target_mon_x', None)   # 固定终点怪X(关怪扫后锁定怪已清空)
        _mx = self._match_ladder_screen_x(self._raw_frame, sp, self._climb_direction, _lkx)
        if _mx is not None:
            tpl_x = _mx
            self._lad_scr_last_x = _mx
            self._lad_scr_last_t = now_ms
        else:
            _stick = getattr(self, '_lad_scr_last_x', None)
            if _stick is not None and now_ms - getattr(self, '_lad_scr_last_t', 0) <= LADDER_SCR_STICK_MS:
                tpl_x = _stick
            else:
                tpl_x = None
        if tpl_x is None:
            if self._ladder_realign_no_tpl_since == 0:
                self._ladder_realign_no_tpl_since = now_ms
            elif now_ms - self._ladder_realign_no_tpl_since >= LADDER_REALIGN_NO_TPL_MS:
                _debug_log("[失败集合] 连续%dms匹配不到梯子白框,回主线" % LADDER_REALIGN_NO_TPL_MS)
                return self._ladder_enter_realign(py, now_ms, "匹配不到梯子")
            self._realign_release_move()
            return False
        self._ladder_realign_no_tpl_since = 0
        spx = sp[0]
        diff = tpl_x - spx                  # 带符号:正=梯子在人物右侧
        adiff = abs(diff)
        dir_vk = VK_RIGHT if diff > 0 else VK_LEFT
        opp_vk = VK_LEFT if dir_vk == VK_RIGHT else VK_RIGHT
        ph = self._ladder_realign_phase

        if ph == 'move':
            # 本轮起步:轮数+1,按"当前剩余"的70%定本轮步长(离得远多走、不碎步)
            if self._ladder_realign_from_x is None:
                self._ladder_realign_round += 1
                self._ladder_realign_from_x = spx
                self._ladder_realign_px = max(LADDER_REALIGN_MIN_STEP, adiff * LADDER_REALIGN_RATIO)
                self._ladder_realign_t = now_ms
                _debug_log("[失败集合] 第%d/%d轮:剩余%.0f屏幕px,本轮走70%%=%.0f"
                           % (self._ladder_realign_round, LADDER_REALIGN_MAX_ROUNDS,
                              adiff, self._ladder_realign_px))
            if opp_vk in self._random_move_keys:
                self._key_up(opp_vk)
            if dir_vk not in self._random_move_keys:
                self._key_down(dir_vk)
            self._ladder_realign_key_vk = dir_vk
            moved = abs(spx - self._ladder_realign_from_x)
            if moved >= self._ladder_realign_px or adiff <= LADDER_REALIGN_TOL                     or now_ms - self._ladder_realign_t >= LADDER_REALIGN_MOVE_CAP_MS:
                # 走到本轮步长/已达标/按满时长→抬键,进gap停稳
                if dir_vk in self._random_move_keys:
                    self._key_up(dir_vk)
                self._ladder_realign_key_vk = None
                self._ladder_realign_phase = 'gap'
                self._ladder_realign_gap_to = now_ms + random.randint(LADDER_REALIGN_GAP_MIN,
                                                                       LADDER_REALIGN_GAP_MAX)
                _debug_log("[失败集合] 本轮移动%.0fpx后剩余%.0f,抬键停稳" % (moved, adiff))
            return False

        if ph == 'gap':
            self._realign_release_move()
            if now_ms >= self._ladder_realign_gap_to:
                self._ladder_realign_phase = 'align'
                self._ladder_realign_ok_frames = 0
                self._ladder_realign_t = now_ms
            return False

        # align:停下检测新距离,连续达标=原地直跳;没达标且轮次没用完回move再走70%,满轮回主线
        self._realign_release_move()
        if adiff <= LADDER_REALIGN_TOL:
            self._ladder_realign_ok_frames += 1
            if self._ladder_realign_ok_frames >= LADDER_REALIGN_HOLD_FRAMES:
                _jk = self._get_fight_config().get("jump_key", "")
                self._climb_start_y = py    # 起跳前小地图Y=成败基准,起跳后Y变小=抓住接上梯集合
                if _jk:
                    self._press_game_key(_jk, duration=80)
                self._ladder_vert_jumped = True
                self._ladder_jump_phase = 'post_jump'
                self._ladder_post_jump_step = 'delay1'
                self._ladder_post_jump_t = now_ms
                self._ladder_realign_phase = None
                _debug_log("[失败集合] 第%d轮对齐达标(X差%.1f<=%d)→原地直跳,跳后判Y"
                           % (self._ladder_realign_round, diff, LADDER_REALIGN_TOL))
            return False
        self._ladder_realign_ok_frames = 0
        # gap已停稳:停下检测没达标就立刻进下一次70%移动(给150ms确认,防落地/滑行惯性误判);已满3轮回主线
        if now_ms - self._ladder_realign_t >= 150:
            if self._ladder_realign_round >= LADDER_REALIGN_MAX_ROUNDS:
                return self._ladder_enter_realign(py, now_ms, "3轮移动仍对不齐")
            self._ladder_realign_phase = 'move'
            self._ladder_realign_from_x = None
        return False


    def _enter_to_ladder_up(self, px, py, now_ms, monster_screen_x=None):
        """cross上层怪·纯屏幕上梯集合入口(用户2026-09-15):先_reset_climb清掉上一把全部相位(零残留),再置to_ladder。
        锁录制梯端点只用于到顶比y_top;选哪把梯/对位/跑跳直跳全程在主游戏窗口屏幕就近完成,不用怪的小地图坐标。
        monster_screen_x=目标怪屏幕X,冻结为固定终点参照(关怪扫后锁定怪会清空;选梯第一键离它近,次序不随人物走动变)。"""
        self._reset_climb()
        self._ladder_target_mon_x = monster_screen_x   # reset会清None,必须在reset之后冻结
        self._release_move_conflicts()
        self._climb_state = "to_ladder"
        self._climb_ladder_x = 0
        self._climb_ladder_y_top = 0
        self._climb_ladder_y_bottom = 0
        self._lock_recorded_ladder_endpoints(px, py)
        self._climb_target_y = 0
        self._climb_direction = 1
        self._climb_action_time = now_ms
        self._ladder_run_jump = False
        self._ladder_vert_jump = False
        self._lad_scr_enter_t = 0

    def _enter_descend(self, target_x, target_y, px, py, now_ms):
        """进入下行descend状态机(用户2026-09-10:下行不对齐怪、不碎步走位,原地直接下跳→按↓到底;跳不了状态机自动转梯子)。"""
        self._release_move_conflicts()  # 进垂直动作前松攻击+左右
        self._climb_state = 'descend'
        self._climb_direction = -1
        self._ladder_precise_mode = True   # 用户2026-09-15:第一次下跳就关怪物识别,横跳离梯+1秒/落地由_reset_climb重开
        self._climb_target_x = target_x
        self._climb_target_y = target_y
        self._climb_action_time = now_ms
        # 用户2026-09-11:跳前点基线已解决下跳腾空误判高低,删掉旧3秒冻结;防重复下跳靠descend状态机自身(进descend后不再走入口)
        # 用户2026-09-10:跳过旧goto_x(小碎步走到怪正头上才跳),进descend原地直接按住↓下跳;
        # first_jump满窗口Y没变(跳不了)会自动转to_ladder走梯子,不需要先水平对齐怪
        self._desc_phase = 'first_jump'
        self._desc_phase_t = now_ms
        self._desc_base_y = py
        self._desc_ref_px = px
        self._desc_stall_t = 0
        self._desc_jumped = False
        self._desc_j2 = False
        self._desc_leap_dir = 1
        # 基准在"决定下跳、人还站定"时就记(用户2026-09-10:原在第二跳空中记会取到无效屏幕Y=0/动作抖动,导致Δ=0误判没下去→每次都转梯子对齐)
        self._desc_pre_leap_sy = self._player_screen_pos[1] if self._player_screen_pos else None  # 站定人物特征屏幕Y
        self._desc_pre_leap_my = py     # 站定小地图世界Y基准(不受镜头滚动影响,主判据)
        self._climb_still_since = 0
        self._climb_top_hold = False
        if VK_DOWN not in self._random_move_keys:
            self._key_down(VK_DOWN)

    def _desc_horiz_walk(self, target_x, px, now_ms, on_stall, stall_dbg):
        """descend内水平朝target_x走(对侧键先松防相抵)；走不到(被平台边挡/连续STALL没靠近)→回调on_stall()。返回True=已触发stall。"""
        ddx = target_x - px
        if ddx > 0:
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT not in self._random_move_keys:
                self._key_down(VK_RIGHT)
        else:
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            if VK_LEFT not in self._random_move_keys:
                self._key_down(VK_LEFT)
        ref = self._desc_ref_px
        # 真朝目标靠近了(剩余|差|减小>0.5)→清卡住计时并刷新基准
        if ref is None or abs(target_x - ref) > abs(target_x - px) + 0.5:
            self._desc_ref_px = px
            self._desc_stall_t = 0
        else:
            if self._desc_stall_t == 0:
                self._desc_stall_t = now_ms
            elif now_ms - self._desc_stall_t >= DESC_GOTO_STALL_MS:
                self._key_up(VK_LEFT)
                self._key_up(VK_RIGHT)
                _debug_log(stall_dbg)
                on_stall()
                return True
        return False

    def _enter_desc_first_jump(self, py, now_ms):
        """阶段first_jump：松左右后按住↓不松(200ms后由状态机补一次跳)。"""
        self._release_move_conflicts()
        self._desc_phase = 'first_jump'
        self._desc_phase_t = now_ms
        self._desc_base_y = py
        self._desc_jumped = False
        self._desc_j2 = False
        self._desc_pre_leap_sy = self._player_screen_pos[1] if self._player_screen_pos else None  # 站定屏幕Y基准
        self._desc_pre_leap_my = py     # 站定世界Y基准
        if VK_DOWN not in self._random_move_keys:
            self._key_down(VK_DOWN)
        self._rlog("原地按住↓直接下跳(不对齐怪)", log='behavior')

    def _enter_desc_lad_scr(self, now_ms):
        """方式二段2入口:小地图梯X已对齐光点中心(±5),切主窗口用梯子特征白框做屏幕X精对位(用户2026-09-10)。"""
        self._desc_phase = 'lad_scr'
        self._desc_phase_t = now_ms
        self._ladder_precise_mode = True   # 切30Hz高频轻量检测档(和上梯一致;出梯由_reset_climb关)
        self._desc_scr_key_vk = None       # 当前碎步按下的方向键(跨帧非阻塞抬起)
        self._desc_scr_key_t = 0
        self._desc_scr_key_hold = 0        # 本拍按住时长(递减)
        self._desc_scr_nudge_t = 0         # 上一碎步拍时刻(拍间gap)
        self._desc_scr_nudge_t = 0   # 下一拍时长(150→×0.75…)
        self._desc_scr_nudge_n = 0         # 已碎步拍数(最多3拍)
        self._desc_scr_ok_frames = 0       # |X差|≤10且双框合并的连续帧
        self._desc_scr_last_x = None       # 上次匹配梯X(丢帧粘滞)
        self._desc_scr_last_t = 0
        self._desc_scr_enter_t = now_ms    # 进屏幕段时刻(合并等待计时)
        _debug_log("[下行·方式二] 小地图对齐光点中心,切主窗口用二合一白框精对位")

    def _desc_align_ladder_screen(self, px, py, now_ms):
        """方式二段2·主窗口对位(屏幕px;用户2026-09-10晚:与上行同口径)。人物特征对齐红框白框二合一白框X。
        无梯子特征/YOLO→小地图已±5直接lad_grab兜底;>35按住朝梯正常走、5~35碎步三拍递减(最多3拍、流利不停)、
        ≤5且双框合并连续2帧=对齐进lad_grab按↓;合并超时/碎步3拍对不上=放弃回主线,绝不没对齐死按↓或卡死。"""
        # 无任何梯子特征来源(没录梯子图、也没梯子YOLO):小地图已对齐到±5,直接lad_grab,不依赖白框也能下
        if not self._ladder_templates and not self._ladder_use_yolo():
            self._key_up(VK_LEFT)
            self._key_up(VK_RIGHT)
            self._enter_desc_lad_grab(py, now_ms)
            _debug_log("[下行·方式二] 无梯子特征/YOLO,小地图已对齐直接lad_grab试抓")
            return False
        _sp = self._player_screen_pos
        if self._raw_frame is None or _sp is None:
            return False   # 本帧无画面/无人物,下帧再试(趋近键不瞎松,总超时兜底)
        spx = int(_sp[0])
        # 目标白框中心X:优先已选中白框的稳定X;否则本帧定向ROI匹配(下行direction=-1搜脚下),丢帧粘滞
        _tx = getattr(self, '_ladder_snap_x', None)
        if _tx is None:
            _lk = getattr(self, '_combat_locked_target', None)
            _lkx = _lk[0] if _lk else None
            _m = self._match_ladder_screen_x(self._raw_frame, _sp, -1, _lkx)
            if _m is not None:
                self._desc_scr_last_x, self._desc_scr_last_t = _m, now_ms
                _tx = _m
            elif getattr(self, '_desc_scr_last_x', None) is not None and now_ms - self._desc_scr_last_t <= LADDER_SCR_STICK_MS:
                _tx = self._desc_scr_last_x
        # 进屏幕段超过合并等待上限仍没锁定任何白框X=识别不到这把梯:放弃回主线(不硬按↓、不死等)
        if _tx is None:
            if now_ms - self._desc_scr_enter_t >= LADDER_MERGE_WAIT_MS:
                self._rlog("下行主窗口%.0fms没识别到梯子白框,放弃回主线" % LADDER_MERGE_WAIT_MS, LOG_RED, log='behavior')
                self._key_up(VK_LEFT)
                self._key_up(VK_RIGHT)
                self._reset_climb()
                self._decide_climb_fail_action()
            return False
        sdx = _tx - spx                       # 正=梯在屏幕右侧
        asdx = abs(sdx)
        _merged = getattr(self, '_ladder_snap_x', None) is not None
        _dir_vk = VK_RIGHT if sdx > 0 else VK_LEFT
        _opp_vk = VK_LEFT if sdx > 0 else VK_RIGHT
        # 上一拍按键抬起:碎步段C定长点动拍的抬键由段C内部闭环判(实时达标/到步长/到时间),不在这抬
        _ak = getattr(self, '_desc_scr_key_vk', None)
        _d_in_nudge = getattr(self, '_desc_scr_nudge_step', 0) or 0
        if _ak is not None and not _d_in_nudge and now_ms - getattr(self, '_desc_scr_key_t', 0) >= getattr(self, '_desc_scr_key_hold', 0):
            self._key_up(_ak)
            self._desc_scr_key_vk = None
            _ak = None
        # 段A:|X差|≤5且已选中白框→连续LADDER_SCR_HOLD_FRAMES帧=对齐,进lad_grab按↓(用户2026-09-10晚:10→5)
        if asdx <= LADDER_SCR_TOL:
            if _ak is not None:
                self._key_up(_ak)
                self._desc_scr_key_vk = None
            self._desc_scr_nudge_t = 0
            self._desc_scr_nudge_n = 0
            self._desc_scr_nudge_step = 0
            self._desc_scr_key_hold = 0
            self._key_up(VK_LEFT)
            self._key_up(VK_RIGHT)
            if _merged:
                self._desc_scr_ok_frames = getattr(self, '_desc_scr_ok_frames', 0) + 1
            else:
                self._desc_scr_ok_frames = 0   # 此刻没选中白框(特征丢帧)不进lad_grab,站住等识别
                self._rlog_throttle('desc_wait_merge', "下行已到梯上X差%.1f但此刻没选中白框,暂等识别" % sdx, 300, log='behavior')
            if _merged and self._desc_scr_ok_frames >= LADDER_SCR_HOLD_FRAMES:
                _debug_log("[下行·方式二] 主窗口对齐白框中心(X差%.1f,连续%d帧)→按住↓%dms看Y变大" % (
                    sdx, self._desc_scr_ok_frames, DESC_LAD_GRAB_MS))
                self._enter_desc_lad_grab(py, now_ms)
            return False
        # 段B:|X差|>35 按住朝梯正常走(不碎步、流利趋近,冲过头由下帧收进碎步区)
        if asdx > LADDER_SCR_NUDGE:
            if _ak is not None:
                self._key_up(_ak)
                self._desc_scr_key_vk = None
            self._desc_scr_nudge_t = 0
            self._desc_scr_nudge_n = 0
            self._desc_scr_nudge_step = 0
            self._desc_scr_key_hold = 0
            self._desc_scr_ok_frames = 0
            if _opp_vk in self._random_move_keys:
                self._key_up(_opp_vk)
            if _dir_vk not in self._random_move_keys:
                self._key_down(_dir_vk)
            return False
        # 段C:5<|X差|≤35 定长点动三拍(用户2026-09-10晚:与上行段3同一套——单拍100/80/60px、按住上限170-200ms随机,
        # 按住中实时达标≤5/走够步长/按满时间即抬,抬起随机停100-110再检测下一拍),只朝梯方向、最多3拍
        self._desc_scr_ok_frames = 0
        if _ak is not None:
            # 本拍按住中→闭环抬键:实时达标/走够本拍步长/按满时间上限,任一即抬,抬起后停gap再检测
            _d_from_x = getattr(self, '_desc_scr_nudge_from_x', spx)
            _d_moved = abs(spx - _d_from_x)
            _d_el = now_ms - getattr(self, '_desc_scr_key_t', now_ms)
            _d_step = getattr(self, '_desc_scr_nudge_step', 0) or 0
            _d_hold = getattr(self, '_desc_scr_key_hold', 200) or 200
            if asdx <= LADDER_SCR_TOL or (_d_step and _d_moved >= _d_step) or _d_el >= _d_hold:
                self._key_up(_ak)
                self._desc_scr_key_vk = None
                self._desc_scr_nudge_step = 0
                self._desc_scr_nudge_t = now_ms + getattr(self, '_desc_scr_nudge_gap', 100)
            return False
        # _ak is None:松开停gap中,到下一拍最早时刻才按
        if now_ms >= getattr(self, '_desc_scr_nudge_t', 0):
            if self._desc_scr_nudge_n >= LADDER_SCR_NUDGE_MAX_TRIES:
                self._rlog("下行定长点动%d拍仍X差%.1f没对齐,放弃回主线(不死磕)" % (LADDER_SCR_NUDGE_MAX_TRIES, asdx),
                           LOG_RED, log='behavior')
                self._key_up(VK_LEFT)
                self._key_up(VK_RIGHT)
                self._reset_climb()
                self._decide_climb_fail_action()
                return False
            if _opp_vk in self._random_move_keys:
                self._key_up(_opp_vk)
            _this, _this_gap, _this_step = self._scr_nudge_timing(self._desc_scr_nudge_n)  # 按住上限/停顿/单拍步长
            self._desc_scr_key_hold = _this
            self._desc_scr_nudge_gap = _this_gap
            self._desc_scr_nudge_step = _this_step
            self._desc_scr_nudge_from_x = spx
            self._desc_scr_nudge_n += 1
            self._key_down(_dir_vk)
            self._desc_scr_key_vk = _dir_vk
            self._desc_scr_key_t = now_ms
            self._rlog_throttle('desc_scr', "下行屏幕定长点动(梯在%s,X差%.1f,第%d拍步长%dpx按住上限%dms停%dms)" % (
                "右" if sdx > 0 else "左", asdx, self._desc_scr_nudge_n, _this_step, _this, _this_gap), 400, log='behavior')
        return False

    def _enter_desc_lad_grab(self, py, now_ms):
        """方式二步骤2:梯子正上方按住↓,观察DESC_LAD_GRAB_MS看Y有没有变大(抓住梯子下滑)。"""
        self._desc_phase = 'lad_grab'
        self._desc_phase_t = now_ms
        self._desc_base_y = py
        self._desc_jumped = False
        if VK_DOWN not in self._random_move_keys:
            self._key_down(VK_DOWN)

    def _enter_desc_lad_slide(self, py, now_ms):
        """方式二步骤3:已抓住梯子(Y变大),继续按住↓下滑DESC_LAD_SLIDE_MS再侧跳离梯(不沿梯到底)。"""
        self._desc_phase = 'lad_slide'
        self._desc_phase_t = now_ms
        if VK_DOWN not in self._random_move_keys:
            self._key_down(VK_DOWN)

    def _enter_desc_fall(self, py, now_ms):
        """阶段fall：直接下跳已确认Y变大后的自由落体——不按任何键(用户2026-09-09:跳后即松↓不长按),
        只等三背景点连续静止=落地站稳。"""
        self._desc_phase = 'fall'
        self._desc_base_y = py
        self._climb_still_since = 0
        self._climb_top_hold = False
        self._desc_land_y = py       # Y稳定落地判据基准(2026-09-10:与三背景点静止取或,落地更快接下一动作)
        self._desc_land_t = now_ms
        self._key_up(VK_DOWN)   # 进自由落体即确保↓已松(直立下落,key_up幂等)

    def _enter_desc_to_ladder(self, px, py, now_ms, reason=""):
        """直接下跳Y没变(跳不了)：水平走到最近梯子X(不直跳抓上梯)；无梯则回主线重选不死磕。返回True=已回主线。"""
        _lad = self._find_nearest_ladder(px, py, self._climb_target_y)
        if _lad:
            self._climb_ladder_x = _lad["x"]
            self._climb_ladder_y_top = _lad["y_top"]
            self._climb_ladder_y_bottom = _lad["y_bottom"]
            self._desc_phase = 'to_ladder'
            self._desc_phase_t = now_ms
            self._desc_ref_px = px
            self._desc_stall_t = 0
            _debug_log("[下行] %s→去梯子x=%.0f" % (reason, _lad["x"]))
            self._rlog("直接跳不下去,改走梯子", log='behavior')
            return False
        _debug_log("[下行] %s,且无可用梯子,回主线重选" % reason)
        if VK_DOWN in self._random_move_keys:
            self._key_up(VK_DOWN)
        self._climb_fail_pause_until = now_ms + random.randint(300, 500)
        self._reset_climb()
        self._decide_climb_fail_action()
        return True

    def _descend_step(self, px, py, now_ms):
        """下行状态机(用户2026-09-10最终定稿,只两种方式,第三种两小层/沿梯到底已删)。px/py=人物小地图坐标。
        方式一 first_jump:压200第一跳→松随机侧键100→第二跳→Y变大转fall自由落体(背景静止/Y稳定落地)。
        方式二(直接跳不了):to_ladder走到梯正上方<=10→lad_grab按500确认Y变大→lad_slide再按1秒
          →lad_leap随机侧100+跳离梯→lad_fall_wait固定1秒回主线;lad_grab满500没Y变大=抓不住回主线,不补跳。"""
        _jk = self._get_fight_config().get("jump_key", "")
        ph = self._desc_phase

        # ①first_jump【方式一·用户2026-09-10定稿:不找口子/不走边缘,原地直接跳;动作无条件做完整,事后在check_drop一次性判Y】
        #   压↓100ms→第一跳(下穿台)→松↓→随机侧键100ms→第二跳(左右跳,跳前记人物特征基准Y)→松左右→进check_drop
        if ph == 'first_jump':
            if not self._desc_jumped:
                # 子步1:按住↓满100ms→第一跳,随即松↓、按下随机侧键
                if VK_DOWN not in self._random_move_keys:
                    self._key_down(VK_DOWN)
                if now_ms - self._desc_phase_t >= DESC_DIRECT_DOWN_HOLD_MS:
                    if _jk:
                        self._press_game_key(_jk, duration=80)   # 第一跳:向下穿台
                    self._desc_jumped = True
                    self._desc_jump_t = now_ms
                    if VK_DOWN in self._random_move_keys:
                        self._key_up(VK_DOWN)                   # 第一跳后立刻松↓(不长按)
                    self._desc_leap_dir = random.choice([-1, 1])  # 随机左/右拟人
                    _svk = VK_RIGHT if self._desc_leap_dir > 0 else VK_LEFT
                    _ovk = VK_LEFT if _svk == VK_RIGHT else VK_RIGHT
                    if _ovk in self._random_move_keys:
                        self._key_up(_ovk)
                    if _svk not in self._random_move_keys:
                        self._key_down(_svk)
                    _debug_log("[下行·方式一] ↓压%.0fms第一跳+松↓+随机向%s" % (
                        DESC_DIRECT_DOWN_HOLD_MS, "右" if self._desc_leap_dir > 0 else "左"))
            elif not getattr(self, '_desc_j2', False):
                # 子步2:随机侧键按满100ms→第二跳(左右跳、带侧向速度离台),跳【前】记人物特征基准Y,随即松左右进check_drop
                _svk = VK_RIGHT if getattr(self, '_desc_leap_dir', 1) > 0 else VK_LEFT
                if _svk not in self._random_move_keys:
                    self._key_down(_svk)
                if now_ms - self._desc_jump_t >= DESC_DIRECT_SIDE_MS:
                    # 基准沿用_enter_descend站定值(不在第二跳空中重取,避免取到无效0/抖动)
                    if _jk:
                        self._press_game_key(_jk, duration=80)   # 第二跳(左右跳)
                    self._desc_j2 = True
                    self._key_up(VK_LEFT)
                    self._key_up(VK_RIGHT)
                    self._desc_phase = 'check_drop'             # 动作做完→事后一次性判Y(不在动作中途判,避免光点闪断误判)
                    self._desc_phase_t = now_ms
                    _debug_log("[下行·方式一] 侧向%.0fms第二跳(左右跳)+松键,记基准Y(屏幕=%s/世界=%.0f),%.0fms后判增大(屏≥%d/世≥%d)" % (
                        DESC_DIRECT_SIDE_MS, self._desc_pre_leap_sy, self._desc_pre_leap_my,
                        DESC_DROP_CHECK_MS, DESC_DROP_DY, DESC_DROP_DY_MAP))
            return False

        # ①.5 check_drop【方式一·观察窗判定(用户2026-09-10晚:任意位置先直接跳、别动不动对齐梯子)】基准用_enter_descend站定值。
        #   两跳后300ms起逐帧比"人物Y比站定基准增大"(屏幕特征Y或小地图世界Y任一,世界Y不受镜头影响更可靠):
        #   一旦增大=确实跳下→fall自由落体;直到900ms观察窗满仍纹丝不动=实心台真跳不下去→才转方式二找梯子。窗内不按任何键。
        if ph == 'check_drop':
            self._key_up(VK_DOWN)
            self._key_up(VK_LEFT)
            self._key_up(VK_RIGHT)
            _el = now_ms - self._desc_phase_t
            _cur_sy = self._player_screen_pos[1] if self._player_screen_pos else None
            # 屏幕Y判据要求站定基准有效(非None/非0,排除进入时就没特征);世界Y(站定py→当前py)为主判据,不受镜头影响
            _dsy = (_cur_sy - self._desc_pre_leap_sy) if (
                _cur_sy is not None and self._desc_pre_leap_sy) else None
            _dmy = py - self._desc_pre_leap_my
            _moved = ((_dsy is not None and _dsy >= DESC_DROP_DY) or (_dmy >= DESC_DROP_DY_MAP))
            if _el >= DESC_DROP_CHECK_MS and _moved:
                # 观察窗内一旦Y往下增大=确实跳下,立刻自由落体等落地(直接跳成功,绝不去对齐梯子)
                _debug_log("[下行·方式一] 直接下跳Y增大(屏幕Δ%s/世界Δ%.0f,起%.0fms)=穿到下一层,自由落体" % (
                    ("%.0f" % _dsy) if _dsy is not None else "NA", _dmy, _el))
                self._enter_desc_fall(py, now_ms)
            elif _el >= DESC_DROP_WAIT_MAX_MS:
                # 实心台横跳不下去:用户2026-09-15——清掉"小地图_find_nearest_ladder选梯+小地图粗对齐(to_ladder)",
                # 直接切到大游戏窗口用梯子白框/模板找梯对位(lad_scr纯屏幕),后续抓住下滑→再横跳离梯时序不变。
                _debug_log("[下行·方式一] 观察%.0fms Y始终没增大(屏幕Δ%s/世界Δ%.0f)=实心台,直接主窗口找梯(不走小地图)" % (
                    _el, ("%.0f" % _dsy) if _dsy is not None else "NA", _dmy))
                self._rlog("横跳%.0fms没下去,直接主窗口找梯子" % _el, log='behavior')
                self._enter_desc_lad_scr(now_ms)
            # 其余(未到最早判定/还在腾空下落途中):不按任何键继续观察
            return False

        # ②to_ladder【方式二·段1·小地图粗导航】直接跳不了:用小地图梯X对齐人物光点中心(|差|≤DESC_LAD_ALIGN_TOL=5),
        #   >5持续按住走、≤5切段2主窗口lad_scr精对位(同拍进30Hz高帧);被挡走不到(stall)也切段2用梯子特征白框兜底。
        if ph == 'to_ladder':
            _ladx = self._climb_ladder_x
            _ldx = _ladx - px
            if abs(_ldx) <= DESC_LAD_ALIGN_TOL:
                self._key_up(VK_LEFT)
                self._key_up(VK_RIGHT)
                self._enter_desc_lad_scr(now_ms)
                return False

            def _on_lad_stall():
                # 小地图走不到梯X(被挡/到平台边):不硬等,切主窗口段靠梯子特征白框就近对位
                self._enter_desc_lad_scr(now_ms)
            self._desc_horiz_walk(_ladx, px, now_ms, _on_lad_stall, "[下行·方式二] 小地图走不到梯X,切主窗口特征对位")
            return False

        # ②.5 lad_scr【方式二·段2·主窗口精对位(用户2026-09-10)】切游戏窗口,用人物特征对齐红框白框二合一白框X,
        #   碎步三拍递减对齐后进lad_grab;具体状态机在_desc_align_ladder_screen(与上梯同套屏幕对位、但到点是按↓不是起跳)。
        if ph == 'lad_scr':
            return self._desc_align_ladder_screen(px, py, now_ms)

        # ③lad_grab【方式二·步骤2】梯正上方按住↓,500ms内Y变大=抓住梯子下滑→lad_slide;满500没变=抓不住,回主线(不补跳/删除两小层)
        if ph == 'lad_grab':
            if VK_DOWN not in self._random_move_keys:
                self._key_down(VK_DOWN)
            if py > self._desc_base_y + DESC_Y_MOVE_TOL:
                _debug_log("[下行·方式二] 梯位按↓Y变大(%.0f→%.0f)=抓住梯子,继续按↓下滑%dms" % (
                    self._desc_base_y, py, DESC_LAD_SLIDE_MS))
                self._enter_desc_lad_slide(py, now_ms)
                return False
            if now_ms - self._desc_phase_t >= DESC_LAD_GRAB_MS:
                _debug_log("[下行·方式二] 梯位按↓%dms Y仍没变=抓不住,松↓回主线(不补跳/不死磕)" % DESC_LAD_GRAB_MS)
                self._rlog("梯子位下不去,回主线重选", LOG_RED, log='behavior')
                if VK_DOWN in self._random_move_keys:
                    self._key_up(VK_DOWN)
                self._climb_fail_pause_until = now_ms + LADDER_FAIL_REENTER_MS
                self._reset_climb()
                self._decide_climb_fail_action()
            return False

        # ④lad_slide【方式二·步骤3】抓住后继续按住↓下滑1秒,到点松↓随机选左/右进lad_leap侧跳离梯
        if ph == 'lad_slide':
            if VK_DOWN not in self._random_move_keys:
                self._key_down(VK_DOWN)
            if now_ms - self._desc_phase_t >= DESC_LAD_SLIDE_MS:
                if VK_DOWN in self._random_move_keys:
                    self._key_up(VK_DOWN)
                self._desc_leap_dir = random.choice([-1, 1])   # 随机左/右拟人,避免每次同方向离梯
                _svk = VK_RIGHT if self._desc_leap_dir > 0 else VK_LEFT
                if _svk not in self._random_move_keys:
                    self._key_down(_svk)
                self._desc_phase = 'lad_leap'
                self._desc_phase_t = now_ms
                self._desc_jumped = False
                _debug_log("[下行·方式二] 下滑%dms够,随机向%s侧跳离梯" % (
                    DESC_LAD_SLIDE_MS, "右" if self._desc_leap_dir > 0 else "左"))
            return False

        # ⑤lad_leap【方式二·步骤4】随机侧键按满100ms时按跳(带侧向速度离梯),随即松左右、进lad_fall_wait
        if ph == 'lad_leap':
            _svk = VK_RIGHT if getattr(self, '_desc_leap_dir', 1) > 0 else VK_LEFT
            _ovk = VK_LEFT if _svk == VK_RIGHT else VK_RIGHT
            if _ovk in self._random_move_keys:
                self._key_up(_ovk)
            if _svk not in self._random_move_keys:
                self._key_down(_svk)
            if not self._desc_jumped and now_ms - self._desc_phase_t >= DESC_LAD_LEAP_SIDE_MS:
                if _jk:
                    self._press_game_key(_jk, duration=80)
                self._desc_jumped = True
                self._key_up(VK_LEFT)
                self._key_up(VK_RIGHT)   # 侧按100ms给个初速度即可,跳后松侧键避免落地还在横走
                self._desc_phase = 'lad_fall_wait'
                self._desc_phase_t = now_ms
                _debug_log("[下行·方式二] 侧向%dms+跳离梯,固定%dms后回主线" % (DESC_LAD_LEAP_SIDE_MS, DESC_LAD_FALL_WAIT_MS))
            return False

        # ⑥lad_fall_wait【方式二·步骤5】侧跳离梯后自由落体,固定等1000ms直接回主线打怪(用户定稿:数1000ms开主线,不判背景、不沿梯到底)
        if ph == 'lad_fall_wait':
            self._key_up(VK_DOWN)
            self._key_up(VK_LEFT)
            self._key_up(VK_RIGHT)
            if now_ms - self._desc_phase_t >= DESC_LAD_FALL_WAIT_MS:
                _debug_log("[下行·方式二] 侧跳离梯满%dms,直接回主线打怪" % DESC_LAD_FALL_WAIT_MS)
                self._rlog("借梯侧跳落下,回主线打怪", log='behavior')
                self._reset_climb()
                self._reset_lock_after_arrival('借梯侧跳落下')
            return False

        # ⑦fall【方式一自由落体】两跳离台后不按任何键;三背景点连续静止 或 光点Y停止下降(取或,先到先落地)→清锁回主线
        # (方式一first_jump已确认Y变大=确实下落;旧"沿梯一直按↓到底hold"已按用户2026-09-10删除,方式二改为侧跳离梯)
        if ph == 'fall':
            _arrived = False
            _why = ""
            if self._raw_frame is not None and self._player_screen_pos:
                _fh, _fw = self._raw_frame.shape[:2]
                _centers = self._pick_climb_boxes(self._player_screen_pos, _fh, _fw)
                _n_still, _n_valid = self._climb_boxes_still(self._raw_frame, _centers)
                if _n_still >= 1:
                    if self._climb_still_since == 0:
                        self._climb_still_since = now_ms
                    elif now_ms - self._climb_still_since >= CLIMB_STILL_MS:
                        _arrived = True
                        _why = "自由落体三背景点静止%.0fms落地" % CLIMB_STILL_MS
                elif _n_valid >= 1:
                    self._climb_still_since = 0   # 还在下落(背景在动),清零
                # n_valid==0空帧:保持计时不打断
            # 【Y稳定并行判据·用户2026-09-10】小地图光点Y连续180ms不再增大=落到底,与背景静止取"或",
            # 不被落地特效/怪撞干扰,先到先落地(治死按↓、背景判不出静止→人到底还压着↓扑倒在地)
            if py > self._desc_land_y + 3:
                self._desc_land_y = py
                self._desc_land_t = now_ms
            elif not _arrived and now_ms - self._desc_land_t >= JUMP_DOWN_LAND_STABLE_MS:
                _arrived = True
                _why = "光点Y稳定%.0fms不再下降=落地" % JUMP_DOWN_LAND_STABLE_MS
            if not _arrived and self._climb_action_time and now_ms - self._climb_action_time > CLIMB_TOTAL_TIMEOUT_MS:
                _arrived = True
                _why = "下行总超时%dms兜底" % CLIMB_TOTAL_TIMEOUT_MS
            if _arrived:
                self._key_up(VK_DOWN)
                _debug_log("[下行] %s(Y=%.0f),落地接下一动作" % (_why, py))
                self._rlog("%s,落地接下一动作" % _why, log='behavior')
                self._reset_climb()
                self._reset_lock_after_arrival('下行自由落')
            return False
        return False

    def _climb_state_machine(self, px, py, now_ms):
        """纯屏幕/光点爬梯状态机(2026-09-15定稿):只处理 _climb_state!=none 的
        descend/to_ladder/climbing/跳/瞬移各相位,全程只用人物光点(px,py)、屏幕梯X、录制梯端,
        不用怪的小地图坐标(怪只在屏幕、选中梯后即出局)。state==none 返回False,让调用方走普通导航。
        返回True=本帧已由状态机处理(调用方直接return);False=state为none未处理。"""
        if self._climb_state == 'none':
            return False
        _now_ms = now_ms   # 状态块整体从_move_to搬出,块内沿用_now_ms局部名,这里做别名(不影响_move_to自身)
        if self._climb_state == "descend":
            return self._descend_step(px, py, _now_ms)
        if self._climb_state == "to_ladder":
            fight_cfg = self._get_fight_config()
            jump_key = fight_cfg.get("jump_key", "")
            now_ms = time.time() * 1000
            # 只要目标是梯子就关怪扫(用户2026-09-15拍板·不等90px):一进to_ladder识别B立刻清空怪表,战斗决策算不到
            # "技能范围内有怪"(不出cast)→近身解绑条件不成立、不会被身边怪拉回,下面屏幕选梯/朝梯走/对位/起跳全程不被打断;
            # 到顶或3轮失败由_reset_climb把标志置False恢复扫描。决定跨层去梯那一刻(_try_platform_transition)也提前关,堵首帧空窗。
            self._ladder_precise_mode = True

            # 起跳后统一流程优先（跑跳/直跳都走这里）
            if getattr(self, '_ladder_jump_phase', None) == 'post_jump':
                return self._ladder_post_jump_process(py, now_ms)
            # 【失败集合】校准中(70%×3轮),与打怪/巡路互斥(用户2026-09-14)
            if getattr(self, '_ladder_jump_phase', None) == 'realign':
                return self._ladder_realign_step(py, now_ms)

            # === 纯屏幕找梯对位(用户2026-09-15定稿:删掉小地图找梯/小地图粗导航,找梯-朝梯走-对位-起跳全程游戏窗口屏幕坐标) ===
            # 选中梯屏幕X:主循环蒙板段已按(Y最近、X最近)选好的稳定白框_ladder_snap_x优先;本帧没选中才用模板现匹配兜底。
            _sel_x = getattr(self, '_ladder_snap_x', None)
            if _sel_x is None and getattr(self, '_ladder_templates', None) \
                    and self._raw_frame is not None and self._player_screen_pos:
                _lkx0 = getattr(self, '_ladder_target_mon_x', None)   # 固定终点怪X(关怪扫后锁定怪已清空,不能用)
                _sel_x = self._match_ladder_screen_x(self._raw_frame, self._player_screen_pos,
                                                     self._climb_direction, _lkx0)
            if _sel_x is not None:
                self._lad_scr_last_t = now_ms
                self._lad_scr_last_x = _sel_x
                return self._ladder_align_by_screen(_sel_x, px, py, now_ms, jump_key)   # 各分带持续朝梯走,不停
            # 保命出口(不是补丁):进to_ladder连续LADDER_MERGE_WAIT_MS屏幕上一把梯都识别不到=没录梯图/没YOLO/不在梯旁,
            # 松左右键回主线打怪,绝不永久空转;刚进、短暂丢帧则站住不发键(不再回退小地图按住乱走)。
            if getattr(self, '_lad_scr_enter_t', 0) == 0:
                self._lad_scr_enter_t = now_ms
            if now_ms - self._lad_scr_enter_t >= LADDER_MERGE_WAIT_MS:
                self._rlog("屏幕连续%.0fms找不到梯子,松键回主线打怪(不死等)" % LADDER_MERGE_WAIT_MS, LOG_RED, log='behavior')
                self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                self._reset_climb(); self._decide_climb_fail_action()
                return False
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
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

            # === 到顶判定(用户2026-09-15极简定稿):抓住后本段开头已一直按住↑;只认【小地图光点重合梯端】
            # (上行比y_top、下行比y_bottom,重合/单向越过容差LADDER_TOP_ARRIVE_TOL)=到顶,当帧松键、清旧怪重扫开打。
            # 两步确认/主窗口补按/三背景点/假抓住这些补丁全部删除;只留一个总超时保命(没录到顶端点/异常时防永久卡梯)。
            _end_y = self._climb_ladder_y_top if self._climb_direction > 0 else self._climb_ladder_y_bottom
            if not _end_y:
                # 兜底:入口没钉到端点就按当前光点现锁一把(永不因端点=0干等12s总超时);到顶只认小地图光点与梯端重合
                self._lock_recorded_ladder_endpoints(px, py)
                _end_y = self._climb_ladder_y_top if self._climb_direction > 0 else self._climb_ladder_y_bottom
            _arrived = False
            _arrive_why = ""
            if _end_y:
                _map_ok = (py <= _end_y + LADDER_TOP_ARRIVE_TOL) if self._climb_direction > 0 \
                    else (py >= _end_y - LADDER_TOP_ARRIVE_TOL)
                # 用户2026-09-15:光点与录制梯端"完全重合"那一刻不立刻松,继续按住↑/↓多走LADDER_TOP_HOLD_MS再松,
                # 确保整个人翻上台/踩稳(本段开头每帧补按方向键,hold期间天然保持按住);上下行同一套。
                if _map_ok:
                    if not self._climb_top_hold:
                        self._climb_top_hold = True
                        self._climb_top_hold_t = now_ms
                    elif now_ms - self._climb_top_hold_t >= LADDER_TOP_HOLD_MS:
                        _arrived = True
                        _arrive_why = "光点重合梯端后多按%dms翻稳" % LADDER_TOP_HOLD_MS
            # 总超时保命(没录到梯端/异常防永久卡梯);已进hold(200ms内必收尾)不再被超时打断
            if not _arrived and not self._climb_top_hold and self._climb_action_time and now_ms - self._climb_action_time > CLIMB_TOTAL_TIMEOUT_MS:
                _arrived = True
                _arrive_why = "总超时%dms保命收尾" % CLIMB_TOTAL_TIMEOUT_MS
            if _arrived:
                _debug_log("[爬梯] %s(光点Y=%.0f 梯端Y=%.0f),松键开主线" % (_arrive_why, py, _end_y or 0))
                self._rlog("%s,到顶开打" % _arrive_why, LOG_OK, log='behavior')
                if VK_UP in self._random_move_keys:
                    self._key_up(VK_UP)
                if VK_DOWN in self._random_move_keys:
                    self._key_up(VK_DOWN)
                self._reset_climb()
                # 到顶清梯子上测的旧怪表+寻怪范围重扫重锁(防拿下方旧怪判cross一上去就下来)
                self._reset_lock_after_arrival('梯到顶')
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
                # ★用户:向下跳到别的台子、Y不再变化=到底,必须清旧锁定/怪表缓存,在寻怪范围重扫重识别,不拿上层旧怪表决策
                self._reset_lock_after_arrival('下跳落地')
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

        return True


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

        # 打怪区域·上下跨层闸门(用户2026-09-11改:手划横线防不住→改认平台绿线身份,一条界线可由多个相连台子合并;只限跨层,跳高打不在此列)。
        # 人站在【上限组】任一台上不发起向上跨层、站在【下限组】任一台上不发起向下跨层/下跳(判当前站哪条绿线);
        # 尚未进爬梯状态机才拦,已在descend/to_ladder/climbing进行中不拦(中途打断反而把人挂梯子上);编辑态不拦;未选上下限=放行。
        if getattr(self, '_climb_state', 'none') == 'none' and not getattr(self, '_bound_edit', False):
            if dy < 0 and self._bound_block_up():
                _debug_log("[打怪区域] 上闸门:人在上限组%s,不发起向上跨层" % self._bound_top_grp)
                return False
            if dy > 0 and self._bound_block_down():
                _debug_log("[打怪区域] 下硬防:人在下限组%s,不发下跳/下爬" % self._bound_bot_grp)
                return False

        # ============================================================
        # 爬梯状态机（2026-09-08 重写·简洁版）
        # 点位全部用小地图距离：固定点6跑跳、<2直跳
        # 到顶判断：小地图人物光标Y 与 梯子顶端 y_top（下行 y_bottom）对齐
        # ============================================================
        # 下行descend状态机优先(用户2026-09-09)：走到怪X直接下跳→按↓到底,跳不了走梯子,与上梯to_ladder完全分开
        if self._climb_state_machine(px, py, _now_ms):
            return False
        # === 正常移动（非攀爬状态）===
        # 需要上下层时：先找梯子（上行直接去梯子；下行先尝试下跳，下跳失败再走梯子）
        if abs(dy) > 8 and target_y < py:
            # 上行跨层(用户2026-09-15全图乱打):不再用小地图_find的"梯端Y和怪层±1对齐"门槛卡人,
            # 怪在上方就直接进to_ladder;选哪把梯/对位/起跳全程屏幕就近(Y最近、X最近),梯顶端点选中后再借录制Y判到顶。
            self._climb_state = "to_ladder"
            self._climb_ladder_x = 0; self._climb_ladder_y_top = 0; self._climb_ladder_y_bottom = 0
            self._lock_recorded_ladder_endpoints(px, py)   # 1+1:直接锁这把小地图录制梯的最上/最下点
            self._climb_target_y = target_y
            self._climb_direction = 1
            self._ladder_run_jump = False
            self._ladder_vert_jump = False
            self._lad_scr_enter_t = 0
            _debug_log("[路线] 目标在上层dy=%.0f,进to_ladder就近找梯上" % dy)
            return False

        # 【用户2026-09-09补·下行跨层入口】旧代码这里只有 target_y<py(上行)半套;下行(target_y>py)只能靠后面兜底块、
        # 却被其 `not _combat_transit` 挡死(跨层进行中恒True)→怪在下方时既不跳也不选梯、人原地不动不跳(真机"下方尤其不动")。
        # 补对称下行入口(跨层中也生效):水平基本对齐且落差不大→直接下跳;否则找离人最近梯子按↓爬下去(下行选梯不要求Y对齐)。
        # 【用户2026-09-09重定义下行】去下层一律走descend状态机:先水平走到怪正头上/最近X→按住↓直接下跳(Y变大)→持续按↓到底;
        # 直接跳不了状态机内部再水平走到梯子X按住↓下(两小层补下跳)。不再要求"小地图X差≤15/落差≤60"才跳——旧门槛让下方怪
        # 总被逼去走梯子、还错套上梯的"直跳+按↑判Y变小",向下Y只会变大必然失败(真机"下方怪不下去反退避"的根因)。
        if abs(dy) > 8 and target_y > py:
            # 用户2026-09-11:不用录制绿线判最底层(有的图没录平台);py/target_y是小地图世界Y,人原地跳/镜头滚都不改世界Y,
            # target_y>py即目标光点确实在更下方=真下层。跳前点基线已解决腾空误判,删掉旧3秒冻结;防重靠enter_descend进入descend状态机。
            self._enter_descend(target_x, target_y, px, py, _now_ms)
            _debug_log("[下行] 目标在下层dy=%.0f,进descend:原地直接下跳(不对齐怪X=%.0f),跳不了再走梯子" % (dy, target_x))
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
                # 3. 都不行→爬梯子(屏幕就近选梯,不再卡小地图Y对齐门槛;用户2026-09-15)
                self._climb_state = "to_ladder"
                self._climb_ladder_x = 0; self._climb_ladder_y_top = 0; self._climb_ladder_y_bottom = 0
                self._lock_recorded_ladder_endpoints(px, py)   # 1+1:直接锁这把小地图录制梯的最上/最下点
                self._climb_target_y = target_y
                self._climb_direction = 1
                self._lad_scr_enter_t = 0
                _debug_log("[爬梯] 目标y=%.0f 当前y=%.0f,进to_ladder屏幕就近找梯向上" % (target_y, py))
                return False

            # --- 去下层(用户2026-09-09)：非跨层场景也统一走descend(先走到怪X直接下跳,跳不了走梯子),与跨层下行入口一致 ---
            else:
                # 用户2026-09-11:跳前点基线解决腾空误判,删掉旧3秒冻结,直接进descend状态机
                self._enter_descend(target_x, target_y, px, py, now_ms)
                _debug_log("[下行·兜底入口] 目标在下层dy=%.0f,进descend" % vertical_gap)
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

            # === 录制绿线坡度优先(用户2026-09-07；2026-09-10再定稿)：前方【录制绿线】Y波动>6判坡——
            # 低向高(上坡)=按住方向跑+连跳爬上去。这是"被地形/台阶挡住过不去"的正道解法,跨层去梯子路上被挡同样靠它跑跳过去,
            # 故绿线坡跳全程生效、不屏蔽(用户:有东西挡住就用绿线波动6px跑跳解决,不靠看门狗重置)；高向低(下坡)=只走不跳。
            # 只有下面的"平台对接跳"(按目标点dy,易被小地图光点±几px抖动误判成台阶=离梯很远乱跳的真凶)才在跨层中屏蔽、且下限提到6。
            _in_transit_walk = getattr(self, '_combat_transit', False)
            _grn_slope = self._platform_slope_ahead(px, py, 1 if dx > 0 else -1)
            _grn_jkey = self._get_fight_config().get("jump_key", "")
            if _grn_slope == 'up':
                # 绿线坡跳：跨层/非跨层都生效(过挡正道),仅350ms去重
                if _grn_jkey and now_ms - getattr(self, '_last_green_slope_jump', 0) > 350:
                    self._press_game_key(_grn_jkey, duration=60)
                    self._last_green_slope_jump = now_ms
                    _debug_log("[绿线坡] 前方上坡(低向高) 跑+跳")
            elif _grn_slope == 'down':
                pass  # 下坡只走，不跳，也不进微高差跳
            elif (not _in_transit_walk) and 6 <= abs(dy) <= 20:
                # 微高差平台对接：按目标点dy判(非录制绿线),易被小地图抖动误触发→跨层去梯子时屏蔽、下限3→6(用户2026-09-10)
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
        """【模块B】检测小地图上人物黄色光点(四角芒星)的几何中心。
        [2026-09-14 定稿·真机诊断] 光点是上下左右对称的黄色芒星(约8x8、20~40像素),中心最亮色=ffff88。
        旧版只认 ffff88→一帧仅命中1~2像素,这1~2像素随芒星闪烁/抗锯齿在星内抖1~2px、还偏上,
        录制的平台绿线/梯子(全部由本中心点聚合)因此"刚录对、过一会就错位漂移"。
        现改:亮黄阈值圈住整颗芒星→连通域→取外接矩形几何中心(真机实测比像素质心稳,芒角亮灭不上下跳);优先锁定离上一帧最近的团(自己不瞬移,
        避免串到别的黄点),无历史/最近团过远才取最大团;面积区间滤碎点与异常大亮块。
        返回:(x,y)小地图块坐标;空图沿用上一帧;无合格团返回None(主循环丢点/重定位契约不变)。"""
        bgr = map_area  # BGR原图(小地图块)
        # [健壮性] 截图瞬时失败传入None/空数组时沿用上一光点、不清空,绝不因inRange空图闪退
        if bgr is None or getattr(bgr, "size", 0) == 0:
            return getattr(self, "last_player_pos", None)
        # 亮黄:R/G≥220、B≤205 → 圈住整颗黄芒星(中心ffff88、芒角亮黄都在内),排除土黄背景(G仅~170)
        mask = cv2.inRange(bgr, np.array([0, 220, 220]), np.array([205, 255, 255]))
        _n, _lab, _st, _ce = cv2.connectedComponentsWithStats(mask, 8)
        cands = []  # (面积, 中心x, 中心y)
        for _k in range(1, _n):
            _a = int(_st[_k, cv2.CC_STAT_AREA])
            if _a < 6 or _a > 220:   # 自己光点约20~40:滤单像素碎点与异常大亮块(UI亮区)
                continue
            # [2026-09-14 稳中心] 用外接矩形几何中心、不用像素质心:真机站定40帧实测,芒星上下芒角随帧亮灭,
            # 像素质心Y在87.7~87.9反复跳(红十字上下跳),外接盒只取最上/最下/最左/最右边界、对称芒星边界稳定,Y恒定0抖动。
            _cxh = _st[_k, cv2.CC_STAT_LEFT] + _st[_k, cv2.CC_STAT_WIDTH] / 2.0
            _cyh = _st[_k, cv2.CC_STAT_TOP] + _st[_k, cv2.CC_STAT_HEIGHT] / 2.0
            cands.append((_a, float(_cxh), float(_cyh)))
        if not cands:
            # 本帧无合格团:不清除last_player_pos(留作下帧最近邻锚点),但仍返回None交主循环丢点逻辑
            return None
        _last = getattr(self, "last_player_pos", None)
        if _last is not None:
            cands.sort(key=lambda c: (c[1] - _last[0]) ** 2 + (c[2] - _last[1]) ** 2)  # 离上一帧最近=自己
            _ax, _ay = cands[0][1], cands[0][2]
            if (_ax - _last[0]) ** 2 + (_ay - _last[1]) ** 2 > 28 * 28:  # 最近团也>28px=锚点失效,改取最大团
                cands.sort(reverse=True)
                _ax, _ay = cands[0][1], cands[0][2]
        else:
            cands.sort(reverse=True)  # 首帧无历史:取最大团
            _ax, _ay = cands[0][1], cands[0][2]
        # 整颗芒星连通域质心(对称星=视觉几何中心);_dot_center_off=最后1px级手动微调,默认0
        cx = int(round(_ax)) + int(getattr(self, '_dot_center_off_x', 0) or 0)
        cy = int(round(_ay)) + int(getattr(self, '_dot_center_off_y', 0) or 0)
        if getattr(self, 'frame_count', 0) % 10 == 0:
            _debug_log("[光点] 中心=(%d,%d) 候选团=%d 面积=%s" % (
                cx, cy, len(cands), str(sorted([c[0] for c in cands], reverse=True)[:4])))
        self.last_player_pos = (cx, cy)  # 更新上次位置(下帧最近邻锚点)
        return (cx, cy)  # 录制绿线/梯子/导航/边界共用的唯一中心点

    # ==================== 打怪区域·小地图四线安全框(用户2026-09-11定稿) ====================
    def _bound_map_size(self):
        """四线/光点共用的小地图块像素尺寸(=map_area_rect原始宽高,与find_player_dot返回坐标同空间、与蒙板客户区1:1)。"""
        r = getattr(self, 'map_area_rect', None)
        if r and r.get('width', 0) > 0 and r.get('height', 0) > 0:
            return int(r['width']), int(r['height'])
        return int(getattr(self, '_last_map_w', FIXED_W) or FIXED_W), int(getattr(self, '_last_map_h', MAP_H) or MAP_H)

    def _get_bound_lines(self):
        """取左右竖线{'l','r'}(小地图块坐标),同时懒加载上下限平台id。
        用户存过盘(_bound_from_file=True)=固定用户设置,只按当前宽度clamp防越界/反转;
        没存过=默认左右竖线铺满当前小地图(标定尺寸就绪后自动正确,不被首次兜底尺寸锁死)。
        兼容旧版{l,r,t,b}存盘:l/r沿用、t/b丢弃,上下限平台id留空(需重新点两条绿线)。"""
        w, h = self._bound_map_size()
        if self._bound_lines is None:
            _loaded = None
            try:
                if os.path.exists(BOUND_FILE):
                    with open(BOUND_FILE, 'r', encoding='utf-8') as _f:
                        _loaded = json.load(_f)
            except Exception as _e:
                _debug_log("[打怪区域] 读边界异常:%s" % _e)
            if isinstance(_loaded, dict) and 'l' in _loaded and 'r' in _loaded:
                self._bound_from_file = True
                self._bound_lines = self._clamp_bound_lines({'l': _loaded['l'], 'r': _loaded['r']}, w, h)
                # Y上下限界线(台子id组):兼容新格式top_grp/bot_grp(list)与更早单值top_pf/bot_pf;逐id校验当前平台表仍有效(重录后旧id自动剔除)
                self._bound_top_grp = self._valid_pf_group(_loaded.get('top_grp', _loaded.get('top_pf')))
                self._bound_bot_grp = self._valid_pf_group(_loaded.get('bot_grp', _loaded.get('bot_pf')))
                # 进编辑前grpA/grpB沿用已存两组(顺序无所谓,退出时按Y重排),暂存区清空
                self._bound_grpA, self._bound_grpB, self._bound_staging = list(self._bound_top_grp), list(self._bound_bot_grp), []
            else:
                self._bound_from_file = False
        if getattr(self, '_bound_from_file', False):
            self._bound_lines = self._clamp_bound_lines(self._bound_lines, w, h)  # 用户竖线只钳不重置
        else:
            self._bound_lines = {'l': BOUND_DEFAULT_INSET,
                                 'r': max(BOUND_DEFAULT_INSET + 10, w - BOUND_DEFAULT_INSET)}  # 默认近乎铺满但内缩可见
        return self._bound_lines

    def _valid_pf_id(self, pf_id):
        """校验平台id对当前self.platforms仍有效(重录/换方案后平台数变化→旧id失效返回None,防误判到别的平台)。"""
        if pf_id is None:
            return None
        try:
            pf_id = int(pf_id)
        except (TypeError, ValueError):
            return None
        for _pf in (self.platforms or []):
            if _pf.get('id', -1) == pf_id:
                return pf_id
        return None

    def _valid_pf_group(self, ids):
        """把存盘里的一条界线(台子id列表,或更早的单值)校验为'对当前平台表有效且去重'的id列表;无效/空→[]。"""
        if ids is None:
            return []
        if not isinstance(ids, (list, tuple)):
            ids = [ids]
        _out = []
        for _x in ids:
            _v = self._valid_pf_id(_x)
            if _v is not None and _v not in _out:
                _out.append(_v)
        return _out

    def _clamp_bound_lines(self, lines, w=None, h=None):
        """左右竖线钳在小地图宽度内,并保证 l<r(中间至少留10单位),换图尺寸变也不越界、不反转。h形参保留兼容调用。"""
        if w is None:
            w, _h = self._bound_map_size()
        l = max(0, min(int(lines['l']), w - 11))
        r = max(l + 10, min(int(lines['r']), w - 1))
        return {'l': l, 'r': r}

    def _save_bound_lines(self):
        if self._bound_lines is None:
            return
        try:
            _top = self._valid_pf_group(self._bound_top_grp)
            _bot = self._valid_pf_group(self._bound_bot_grp)
            self._bound_top_grp, self._bound_bot_grp = _top, _bot
            _out = {'l': self._bound_lines['l'], 'r': self._bound_lines['r'],
                    'top_grp': _top, 'bot_grp': _bot}
            with open(BOUND_FILE, 'w', encoding='utf-8') as _f:
                json.dump(_out, _f)
            self._bound_from_file = True   # 存盘后即用户设置,不再自动铺满重置
            _debug_log("[打怪区域] 边界已保存:%s" % _out)
        except Exception as _e:
            _debug_log("[打怪区域] 保存异常:%s" % _e)

    def _bound_toggle_edit(self):
        """UI'打怪区域'按钮:常态灰(守护生效)↔编辑绿(拖左右竖线;点多个相连台子按回车合并成一条界线,共两条,自动按Y定上下);退出编辑即存盘。"""
        self._bound_edit = not self._bound_edit
        self._bound_drag = None
        self._bound_clear_menu = None   # 进/出编辑都关掉右键清除气泡
        if self._bound_edit:
            # 进入编辑:已存上/下组回填grpA/grpB(顺序无关,退出按Y重排),暂存区清空
            self._bound_grpA = self._valid_pf_group(self._bound_top_grp)
            self._bound_grpB = self._valid_pf_group(self._bound_bot_grp)
            self._bound_staging = []
            self._bound_reorder()
        else:
            # 退出:没按回车成形的暂存台子不计入(必须回车才算一条界线)
            if self._bound_staging:
                self._add_log("还有%d个台子没按回车成形,已不计入" % len(self._bound_staging))
                self._bound_staging = []
            self._bound_reorder()
            self._save_bound_lines()
        try:
            self._add_log("打怪区域:%s" % ("进入编辑:点多个相连台子→按回车合成一条;再点一批→回车成第二条(自动按Y定上/下)" if self._bound_edit else "已保存,边界守护生效"))
        except Exception:
            pass

    def _bound_pf_by_id(self, pf_id):
        """按平台id取平台dict,找不到返回None。"""
        if pf_id is None:
            return None
        for _pf in (self.platforms or []):
            if _pf.get('id', -1) == pf_id:
                return _pf
        return None

    def _bound_group_y_avg(self, grp):
        """一条界线(多个台子id)的整体平均Y:组内各台平均Y再取均值;空组返回999(排序沉底)。"""
        _ys = []
        for _id in grp:
            _pf = self._bound_pf_by_id(_id)
            if _pf is not None:
                _ys.append(self._platform_y_avg(_pf))
        return (sum(_ys) / len(_ys)) if _ys else 999.0

    def _bound_reorder(self):
        """按grpA/grpB两条界线的整体平均Y自动定上下:Y小→上限组top_grp、Y大→下限组bot_grp;只成形一条时它暂作top、bot空。"""
        _a, _b = list(self._bound_grpA), list(self._bound_grpB)
        if _a and _b:
            if self._bound_group_y_avg(_a) <= self._bound_group_y_avg(_b):
                self._bound_top_grp, self._bound_bot_grp = _a, _b
            else:
                self._bound_top_grp, self._bound_bot_grp = _b, _a
        elif _a:
            self._bound_top_grp, self._bound_bot_grp = _a, []
        elif _b:
            self._bound_top_grp, self._bound_bot_grp = _b, []
        else:
            self._bound_top_grp, self._bound_bot_grp = [], []

    def _bound_pick_at(self, mx, my):
        """编辑态:点选最近的平台绿线加入暂存区(照梯删除范式,点到折线距离≤BOUND_PICK_TOL);再点已在暂存区的同一台=取消。暂存区要按回车才合并成一条界线。"""
        if not getattr(self, '_bound_edit', False):
            return
        if not self.platforms:
            self._add_log("还没录制平台绿线,无法选Y界线")
            return
        _best_id, _best_d = -1, 1e9
        for _pf in self.platforms:
            _d = self._point_to_polyline_dist(mx, my, self._platform_points(_pf))
            if _d < _best_d:
                _best_d, _best_id = _d, _pf.get('id', -1)
        if _best_id < 0 or _best_d > BOUND_PICK_TOL:
            return  # 没点中任何绿线,不打断拖竖线
        if _best_id in self._bound_staging:
            self._bound_staging.remove(_best_id)
            self._add_log("取消平台%d,暂存剩%d个" % (_best_id + 1, len(self._bound_staging)))
        else:
            self._bound_staging.append(_best_id)
            self._add_log("平台%d进暂存(共%d个),选完相连台子按回车合成一条" % (_best_id + 1, len(self._bound_staging)))
        _debug_log("[打怪区域] 暂存区=%s" % self._bound_staging)

    def _bound_commit_group(self):
        """编辑态按回车:把暂存区多个台子合并成'一条界线'。第1次回车→grpA、第2次→grpB;两条已满再回车=清空重选(本次当新第一条)。成形后自动按Y定上/下。"""
        if not getattr(self, '_bound_edit', False):
            return
        if not self._bound_staging:
            self._add_log("暂存区空:先点选台子,再按回车合成一条界线")
            return
        _grp = self._valid_pf_group(self._bound_staging)
        self._bound_staging = []
        if self._bound_grpA and self._bound_grpB:
            self._bound_grpA, self._bound_grpB = _grp, []   # 两条已满→重新开始,本次当新第一条
            self._add_log("两条已满重选:第1条已合成(%d台),再选第2条按回车" % len(_grp))
        elif not self._bound_grpA:
            self._bound_grpA = _grp
            self._add_log("第1条界线已合成(%d台);再点相连台子、按回车合成第2条" % len(_grp))
        else:
            self._bound_grpB = _grp
            self._add_log("第2条界线已合成(%d台),已自动按Y定好上/下" % len(_grp))
        self._bound_reorder()
        _debug_log("[打怪区域] 回车成组 grpA=%s grpB=%s → top=%s bot=%s" % (
            self._bound_grpA, self._bound_grpB, self._bound_top_grp, self._bound_bot_grp))

    def _bound_group_at(self, mx, my):
        """编辑态右键:块坐标(mx,my)命中哪条【已成形】界线组,返回'A'/'B'/None。
        组内任一平台折线到光标点≤BOUND_PICK_TOL即算命中该条;两条都中取更近者。暂存区不算(左键可直接再点取消)。"""
        if not getattr(self, '_bound_edit', False):
            return None

        def _grp_min_dist(grp):
            _d = 1e9
            for _id in grp:
                _pf = self._bound_pf_by_id(_id)
                if _pf is not None:
                    _d = min(_d, self._point_to_polyline_dist(mx, my, self._platform_points(_pf)))
            return _d

        _da, _db = _grp_min_dist(self._bound_grpA), _grp_min_dist(self._bound_grpB)
        _best, _bd = None, BOUND_PICK_TOL
        if _da <= _bd:
            _best, _bd = 'A', _da
        if _db < _bd:
            _best = 'B'
        return _best

    def _bound_clear_group(self, which):
        """点'清除'气泡:清空指定的那条已成形界线组(A/B),暂存也清、重排上下;不在此存盘——
        用户再点'打怪区域'退出编辑时_bound_toggle_edit统一_save_bound_lines,空组即保存为空、可重新录(用户2026-09-12)。"""
        if which == 'A':
            self._bound_grpA = []
        elif which == 'B':
            self._bound_grpB = []
        else:
            return
        self._bound_staging = []
        self._bound_reorder()
        self._bound_clear_menu = None
        self._add_log("已清空第%s条Y界线,再点'打怪区域'退出即保存为空、可重新录" % which)
        _debug_log("[打怪区域] 清除界线%s → grpA=%s grpB=%s top=%s bot=%s" % (
            which, self._bound_grpA, self._bound_grpB, self._bound_top_grp, self._bound_bot_grp))

    def _bound_current_pf_id(self):
        """人物当前所在录制平台id(复用_get_current_manual_platform:光点距某绿线≤15即站该台);腾空/梯上判不到返回None。"""
        _pf = self._get_current_manual_platform()
        return None if _pf is None else _pf.get('id')

    def _bound_block_up(self):
        """Y上闸门:人物当前站的台子属于选定的上限组(该界线合并的任一台)=禁止再向上。未设上限/编辑态/判不到当前台=放行。"""
        if getattr(self, '_bound_edit', False):
            return False
        _grp = self._valid_pf_group(self._bound_top_grp)
        if not _grp:
            return False
        return self._bound_current_pf_id() in _grp

    def _bound_block_down(self):
        """Y下闸门:人物当前站的台子属于选定的下限组(该界线合并的任一台)=禁止向下。未设下限/编辑态/判不到当前台=放行。"""
        if getattr(self, '_bound_edit', False):
            return False
        _grp = self._valid_pf_group(self._bound_bot_grp)
        if not _grp:
            return False
        return self._bound_current_pf_id() in _grp

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
        - 窗口内绿线Y波动≤GREEN_SLOPE_MIN(5)=平地小抖动→返回None正常走；
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
            # 全图模式(没勾台号):【不用单个台子的绿线边界】,左右边界统一由"打怪区域·小地图四线安全框"守护线程负责
            # (人物黄光点越左右竖线→主线朝内拉回1000~1500ms,用户2026-09-11定稿,已删除旧屏幕100/140边缘A+B)。旧逻辑退回"当前录制台"X范围当边界,
            # 会把全图追边界外远怪每帧静默拦下(决策喊追、人钉死发呆)。故台子边界只在勾了台号时生效,这里放行。
            return False
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

    def _bottom_floor_gate_map(self, tx, ty):
        """【下行最底层硬闸·小地图世界坐标·用户2026-09-11治"人在第一层/人跳起来比怪高还向下跳"】
        tx,ty=目标怪的【小地图世界坐标】。用世界坐标判:人物原地腾空、镜头滚动都不改变小地图光点Y,
        从根上免疫"人一跳屏幕Y变小→同层地面怪被误判成在下方→瞎下跳"。
        返回 True=目标确在比当前层更低的另一层录制平台(允许下行);False=同层/人已最底/目标不落更低层(禁止下行);
        None=没录平台或判不出当前层(调用方维持原纯Y逻辑,不硬拦没录平台的图)。"""
        try:
            if not self.platforms or not self._player_map_pos:
                return None
            _pp = self._get_current_platform()
            if _pp is None:
                return None
            _mt, _best = None, 15.0   # 目标小地图点到某层折线最近距离≤15才算落在该层
            for _pf in self.platforms:
                _d = self._point_to_polyline_dist(tx, ty, self._platform_points(_pf))
                if _d < _best:
                    _best, _mt = _d, _pf
            if _mt is None:
                return False   # 目标点不落任何录制层=下方无可去层(人已最底),不下
            if _mt.get('id') == _pp.get('id'):
                return False   # 同一层:世界Y差再大也不下
            return self._platform_y_avg(_mt) > self._platform_y_avg(_pp) + 5  # 必须确实更低一层
        except Exception as _e:
            _debug_log("[下行硬闸] 世界坐标判定异常:%s(不硬拦,维持原逻辑)" % _e)
            return None

    def _monster_really_on_lower_platform(self, sx, sy):
        """【落层硬闸·屏幕坐标入口】屏幕怪坐标先转小地图世界坐标,再走世界坐标最底层硬闸(免疫腾空/镜头);
        没录平台/屏幕转不出世界坐标时维持原逻辑(允许),不硬拦没录平台的图。"""
        try:
            _mp = self._screen_to_map(sx, sy)
            if _mp is None:
                return True
            _g = self._bottom_floor_gate_map(_mp[0], _mp[1])
            return True if _g is None else _g
        except Exception:
            return True

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
        for vk in [VK_F3, VK_F4, VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F11, VK_F12]:
            pressed = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if pressed and not self._key_state[vk]:
                _debug_log("[热键] 检测到按键 VK=0x%X" % vk)
                self._handle_hotkey(vk)
            self._key_state[vk] = pressed

    def _handle_hotkey(self, vk):
        if vk == VK_F4:
            # F4=调试显示总开关:开=画全部框/线(锚点橙框/白搜索框/黄怪物框/蓝技能框/怪物点等);关=蒙板等同干净原画面。
            # 蒙板只负责显示、不参与识别,关掉不影响任何打怪逻辑。旧连拍采集已改由"人物特征"按钮的角色识别管理窗承担(方法保留备用)。
            self._debug_overlay = not getattr(self, '_debug_overlay', True)
            _msg = "调试显示 开(F4)" if self._debug_overlay else "调试显示 关(F4)·画面干净"
            print("[F4]", _msg)
            self._add_log(_msg)
            _debug_log("[F4] _debug_overlay=%s" % self._debug_overlay)
            return
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
                self._stop_runtime_detection()  # 停止运行层(怪物+监管+边界),保留常开截图+人物(方案B)
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
        # 无条件记录最新客户区坐标/左键flag(和小地图绘制严格同空间、零DPI偏移;供主循环四线拖拽轮询,治MOUSEMOVE丢帧)
        self._ui_mouse_x, self._ui_mouse_y, self._ui_mouse_flags = x, y, flags
        # 松开按钮：清除按下状态
        if event == cv2.EVENT_LBUTTONUP:
            self._pressed_btn = None
            self._bound_drag = None   # 打怪区域:松键即停止拖线(退出编辑时统一存盘)
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

        # === 性能档弹窗交互(用户2026-09-11):优先X→标题栏拖拽→点档位切换;照倍率弹窗范式) ===
        if self._show_perf_dialog and event == cv2.EVENT_LBUTTONDOWN:
            cx, cy, cw, ch = self._dlg_perf_close
            if cx <= x < cx+cw and cy <= y < cy+ch:          # 1.右上角X关闭
                self._show_perf_dialog = False
                return
            dlg_x, dlg_y = self._perf_dialog_pos[0], self._perf_dialog_pos[1]
            if dlg_x <= x < dlg_x+PERF_DIALOG_W and dlg_y <= y < dlg_y+50:  # 2.标题栏拖拽
                self._perf_dialog_dragging = True
                self._perf_dialog_drag_offset = [x-dlg_x, y-dlg_y]
                return
            for lv in PERF_LEVEL_ORDER:                      # 3.点某档=切换(频率即时生效+存盘)
                ox, oy, ow, oh = self._dlg_perf_opt[lv]
                if ox <= x < ox+ow and oy <= y < oy+oh:
                    self._set_perf_level(lv)
                    return
            if not (dlg_x <= x < dlg_x+PERF_DIALOG_W and dlg_y <= y < dlg_y+PERF_DIALOG_H):  # 点外部关闭
                self._show_perf_dialog = False
                return
        if self._show_perf_dialog and self._perf_dialog_dragging and event == cv2.EVENT_MOUSEMOVE:
            self._perf_dialog_pos[0] = x - self._perf_dialog_drag_offset[0]
            self._perf_dialog_pos[1] = y - self._perf_dialog_drag_offset[1]
            self._perf_dialog_pos[0] = max(0, min(UI_W-PERF_DIALOG_W, self._perf_dialog_pos[0]))
            self._perf_dialog_pos[1] = max(0, min(UI_H-PERF_DIALOG_H, self._perf_dialog_pos[1]))
            return
        if self._perf_dialog_dragging and event == cv2.EVENT_LBUTTONUP:
            self._perf_dialog_dragging = False
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
        # 滚动单位=折行后的渲染行(最新在上、条内首行在上)，和绘制处保持一致(否则长消息折行后滚动条对不齐)
        _avail_w = UI_LOG_W - 4 - 8 - 2 - 6
        total = len(self._log_display_lines(_entries, _avail_w))
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
            # 【打怪区域·用户2026-09-11】梯删除正下方"打怪区"钮:点一下变绿=可拖左右竖线+点绿线选Y上下限,再点=保存变灰
            if self._btn_bound_area and _in(self._btn_bound_area, x, y):
                self._bound_toggle_edit()
                return
            # 【性能档·用户2026-09-11】打怪区正下方"性能档"钮:点开慢/普通/快三选一弹窗
            if self._btn_perf and _in(self._btn_perf, x, y):
                self._open_perf_dialog()
                return
            # 【打怪区域·Y上下限点选】编辑态下点小地图只服务打怪区域。坐标必须用小地图"实际贴放矩形"_map_disp_*严格逆运算:
            # 固定UI_MAP_Y=131与实际贴放顶143差12px、显示高还是动态值,用公共map_y会Y系统性偏上(用户实锤);竖线拖拽_bound_drag_tick
            # 正是用_map_disp_*才准、绿线也是按它缩放绘制,这里同源=点哪中哪、零偏移。按竖线=交拖拽;没按竖线=点绿线(先上限后下限)。
            # 编辑态一律return,不落到梯删除/台子选择(非编辑态整段跳过、原逻辑不变);_map_disp缺失才退回公共map_x/map_y兜底
            if getattr(self, '_bound_edit', False):
                _bdx = getattr(self, '_map_disp_x', UI_MAP_X)
                _bdy = getattr(self, '_map_disp_y', UI_MAP_Y)
                _bdw = getattr(self, '_map_disp_w', UI_MAP_W)
                _bdh = getattr(self, '_map_disp_h', UI_MAP_H)
                _bmw = getattr(self, '_last_map_w', FIXED_W)
                _bmh = getattr(self, '_last_map_h', MAP_H)
                _bmx = int((x - _bdx) / _bdw * _bmw) if _bdw else map_x
                _bmy = int((y - _bdy) / _bdh * _bmh) if _bdh else map_y
                _mpx, _mpy = x - _bdx, y - _bdy   # map_display显示空间坐标(和气泡绘制同空间,用于命中)
                # 右键:点中某条已成形Y界线→在该处弹"清除"气泡;点空白=关气泡
                if event == cv2.EVENT_RBUTTONDOWN:
                    _w = self._bound_group_at(_bmx, _bmy)
                    if _w:
                        self._bound_clear_menu = {'which': _w, 'mx': _bmx, 'my': _bmy, 'rect': None}
                        self._add_log("选中第%s条Y界线,左键点'清除'清空,再点'打怪区'退出即保存" % _w)
                    else:
                        self._bound_clear_menu = None
                    return
                # 左键:优先命中"清除"气泡→清空该条界线
                _cm = getattr(self, '_bound_clear_menu', None)
                if _cm and _cm.get('rect'):
                    _cx, _cy, _cw, _ch = _cm['rect']
                    if _cx <= _mpx < _cx + _cw and _cy <= _mpy < _cy + _ch:
                        self._bound_clear_group(_cm['which'])
                        return
                if _cm:
                    self._bound_clear_menu = None   # 左键点其它地方=关掉气泡,再走正常选台/拖线
                if self._bound_hit_line(_bmx, _bmy) is None:
                    self._bound_pick_at(_bmx, _bmy)
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
            self._open_role_recognize_window()
            print("[鼠标] 打开角色识别窗(名字主锚点/脸镜像/宠物名冗余/跟踪参数)")
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

        # 打怪区域·左右竖线(照平台绿线缩放画UI小地图;不透明;调整中=橙、常态=青)+选中的Y上下限绿线原地高亮(上限红/下限蓝)
        try:
            _bln = self._get_bound_lines()
            _bedit = getattr(self, '_bound_edit', False)
            _bcol = (0, 165, 255) if _bedit else (255, 255, 0)   # cv2 BGR:竖线调整中=橙、常态=青
            _blw = max(1, int(round(BOUND_LINE_W * 0.8)))        # 线宽=基准80%(3→2)
            _bxl, _bxr = int(_bln['l'] * scale_x), int(_bln['r'] * scale_x)
            cv2.line(map_display, (_bxl, 0), (_bxl, render_h), _bcol, _blw)   # 左竖线
            cv2.line(map_display, (_bxr, 0), (_bxr, render_h), _bcol, _blw)   # 右竖线
            # Y界线高亮(一条界线可合并多个相连台子,同组染同色=连成一体):编辑态暂存=黄、只成形1条待配对=紫、两条齐后上限红/下限蓝;常态上限红/下限蓝。本段在绿线之后、高亮盖上层
            _idcol = {}
            _tg = self._valid_pf_group(getattr(self, '_bound_top_grp', []))
            _bg = self._valid_pf_group(getattr(self, '_bound_bot_grp', []))
            if _bedit:
                if _tg and _bg:
                    for _i in _tg: _idcol[_i] = (0, 0, 255)     # 上限=红BGR
                    for _i in _bg: _idcol[_i] = (255, 0, 0)     # 下限=蓝BGR
                elif _tg:
                    for _i in _tg: _idcol[_i] = (255, 0, 255)   # 只成形一条=紫(待第二条定上下)
                for _i in getattr(self, '_bound_staging', []):
                    _idcol[_i] = (0, 255, 255)                  # 暂存区=黄BGR(优先级最高)
            else:
                for _i in _tg: _idcol[_i] = (0, 0, 255)
                for _i in _bg: _idcol[_i] = (255, 0, 0)
            for _p in self.platforms:
                _pid = _p.get('id', -1)
                if _pid not in _idcol:
                    continue
                _hpts = self._platform_points(_p)
                if len(_hpts) >= 2:
                    _spts = [(int(pt[0] * scale_x), int(pt[1] * scale_y)) for pt in _hpts]
                    cv2.polylines(map_display, [np.array(_spts, np.int32).reshape(-1, 1, 2)],
                                  False, _idcol[_pid], 3)
            # 右键清除Y界线气泡(仅编辑态):右键点中某条已成形界线→命中处弹"清除",左键点中清空该组;退出编辑时统一存盘(用户2026-09-12)
            _cm = getattr(self, '_bound_clear_menu', None)
            if _bedit and _cm:
                _rw = map_display.shape[1]
                _rh = map_display.shape[0]
                _ax = int(_cm['mx'] * scale_x)
                _ay = int(_cm['my'] * scale_y)
                _cw, _ch = 46, 20
                _ax = max(2, min(_ax, _rw - _cw - 2))
                _ay = max(2, min(_ay + 6, _rh - _ch - 2))   # 落在命中点略下方,钳在小地图内
                cv2.rectangle(map_display, (_ax, _ay), (_ax + _cw, _ay + _ch), (60, 60, 60), -1)
                cv2.rectangle(map_display, (_ax, _ay), (_ax + _cw, _ay + _ch), (0, 165, 255), 1)
                self._putcn(map_display, "清除", _ax + 9, _ay + 15, (255, 255, 255))
                _cm['rect'] = (_ax, _ay, _cw, _ch)         # 回写显示空间命中框供左键判定(每帧随缩放刷新)
        except Exception as _be:
            _debug_log("[UI小地图] 打怪区域画线异常: %s" % _be)

        # 【人物光点认定中心·用户2026-09-14】在find_player_dot算出的光点正中心叠红色十字+实心点。
        # 平台绿线/梯子都从此中心点吐出:红十字正好压住游戏自带黄光点=中心定准;压住录制线最新端=线从中心出,一眼验证100%重合。
        # 坐标空间:player_pos是小地图块原始像素,乘scale_x/y落到缩放后的map_display(和怪紫点同一画法)。
        if player_pos is not None:
            _dcx = int(player_pos[0] * scale_x)
            _dcy = int(player_pos[1] * scale_y)
            if 0 <= _dcx < render_w and 0 <= _dcy < render_h:
                cv2.line(map_display, (_dcx - 6, _dcy), (_dcx + 6, _dcy), (0, 0, 255), 1)  # 红十字横
                cv2.line(map_display, (_dcx, _dcy - 6), (_dcx, _dcy + 6), (0, 0, 255), 1)  # 红十字竖
                cv2.circle(map_display, (_dcx, _dcy), 2, (0, 0, 255), -1)                 # 中心红实心点

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
        # 第三个框显示当前方案【名字】或"随机"。
        # [修2026-09-14] 旧版写死"方案%d"%current_route=底层文件编号;新建方案补最小空id(route_001/002)
        # 而名字按列表个数起(方案5/方案6),id与名字错位→实际用"方案6"(id=route_002)却显示"方案2"。
        # 改为查当前方案的name显示,和方案列表/用户认知永远一致;查不到才退回底层编号。
        if self.route_mode == "随机":
            plan_label = "随机"
        else:
            _cur_plan, _ = self._find_plan(num_to_plan_id(self.current_route))
            plan_label = (_cur_plan.get("name") if _cur_plan and _cur_plan.get("name")
                          else ("方案%d" % self.current_route))
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

        # === 打怪区域按钮(梯删除正下方,用户2026-09-11):灰=常态(左右竖线守护+Y平台闸门生效);点一下变绿=编辑态,
        # 可拖左右竖线、点两条平台绿线定Y上下限,再点一下=保存并变回灰(效果同日志上方打怪/行为切换钮) ===
        btn_ba_w, btn_ba_h = 60, 20       # 与梯删除等宽等长(用户2026-09-11:改名"打怪区",三字对齐更好看)
        btn_ba_x = btn_ld_x + btn_ld_w - btn_ba_w     # 与梯删除右对齐(等宽后即左右都对齐)
        btn_ba_y = btn_ld_y + btn_ld_h + 3           # 紧贴梯删除下方
        self._btn_bound_area = (btn_ba_x, btn_ba_y, btn_ba_w, btn_ba_h)
        if self._bound_edit:
            cv2.rectangle(frame, (btn_ba_x, btn_ba_y), (btn_ba_x+btn_ba_w, btn_ba_y+btn_ba_h), (0, 150, 0), -1)  # 编辑=绿底
            cv2.rectangle(frame, (btn_ba_x, btn_ba_y), (btn_ba_x+btn_ba_w, btn_ba_y+btn_ba_h), (0, 220, 0), 1)
            self._putcn(frame, "调整中", btn_ba_x+8, btn_ba_y+14, (255, 255, 255))
        else:
            cv2.rectangle(frame, (btn_ba_x, btn_ba_y), (btn_ba_x+btn_ba_w, btn_ba_y+btn_ba_h), (60, 60, 60), -1)
            cv2.rectangle(frame, (btn_ba_x, btn_ba_y), (btn_ba_x+btn_ba_w, btn_ba_y+btn_ba_h), (150, 150, 150), 1)
            self._putcn(frame, "打怪区", btn_ba_x+8, btn_ba_y+14, (190, 190, 190))

        # === 性能档按钮(打怪区正下方,用户2026-09-11):点一下弹"慢/普通/快"三选一弹窗 ===
        btn_pf_w, btn_pf_h = 60, 20                    # 与梯删除/打怪区等宽,竖排对齐
        btn_pf_x = btn_ba_x + btn_ba_w - btn_pf_w
        btn_pf_y = btn_ba_y + btn_ba_h + 3            # 紧贴打怪区下方3px
        self._btn_perf = (btn_pf_x, btn_pf_y, btn_pf_w, btn_pf_h)
        cv2.rectangle(frame, (btn_pf_x, btn_pf_y), (btn_pf_x+btn_pf_w, btn_pf_y+btn_pf_h), (60, 60, 60), -1)
        cv2.rectangle(frame, (btn_pf_x, btn_pf_y), (btn_pf_x+btn_pf_w, btn_pf_y+btn_pf_h), (150, 150, 150), 1)
        self._putcn(frame, "性能档", btn_pf_x+8, btn_pf_y+14, (190, 190, 190))

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
        _tab_x0 = lx + 4 + 45  # 打怪/行为分栏整体右移45px(用户2026-09-10,让开日志底板左上位置)
        self._log_tab_combat = (_tab_x0, _tab_y, _tab_w, _tab_h)
        self._log_tab_behavior = (_tab_x0 + _tab_w + 4, _tab_y, _tab_w, _tab_h)
        max_lines = max(1, log_content_h // line_h)
        _avail_w = lw - 4 - 8 - 2 - 6   # 左留白4 + 右滚动条(8+2) + 余量6
        display = self._log_display_lines(_logs, _avail_w)  # 从上到下:最新条目在最上,条内首行(带时间)在上
        total = len(display)
        # scroll=0 停在顶部看最新N行；>0 向下滚动看更旧历史(单位=折行后的渲染行)
        visible = display[_scroll:_scroll + max_lines]
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
                for i, (text, col, indent) in enumerate(visible):
                    ty = log_content_y + i * line_h
                    if ty > ly + lh - line_h:
                        break
                    # display已是"最新在上、条内首行(带时间)在上"顺序,正序画;首行indent=0,续行indent=时间戳宽不写时间
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

        # === 性能档三选一弹窗(灰底白字/右上X/可拖标题栏/最上层,照弹窗组件规范;用户2026-09-11) ===
        if self._show_perf_dialog:
            self._update_perf_dialog_positions()  # 每帧重算,拖拽不偏移
            px, py = self._perf_dialog_pos[0], self._perf_dialog_pos[1]
            pw, ph = PERF_DIALOG_W, PERF_DIALOG_H
            cv2.rectangle(frame, (px, py), (px+pw-1, py+ph-1), (60, 60, 60), -1)
            cv2.rectangle(frame, (px, py), (px+pw-1, py+ph-1), (100, 100, 100), 1)
            cv2.rectangle(frame, (px, py), (px+pw-1, py+50), (80, 80, 80), -1)  # 标题栏(可拖拽区)
            self._draw_cn_mixed(frame, "性能档选择", px+15, py+32, 0.6, (255, 255, 255))
            cx, cy, cw, ch = self._dlg_perf_close
            cv2.rectangle(frame, (cx, cy), (cx+cw-1, cy+ch-1), (80, 80, 80), -1)
            cv2.putText(frame, "X", (cx+7, cy+18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            _opt_label = {"slow": "慢：四核/配置差·最省CPU",
                          "normal": "普通：一般电脑·默认推荐",
                          "fast": "快：八核/配置好·识别最跟手"}
            for lv in PERF_LEVEL_ORDER:  # 当前档绿底高亮,其余深灰
                ox, oy, ow, oh = self._dlg_perf_opt[lv]
                _sel = (lv == self._perf_level)
                cv2.rectangle(frame, (ox, oy), (ox+ow-1, oy+oh-1), (0, 130, 0) if _sel else (45, 45, 45), -1)
                cv2.rectangle(frame, (ox, oy), (ox+ow-1, oy+oh-1), (0, 220, 0) if _sel else (150, 150, 150), 1)
                self._draw_cn_mixed(frame, _opt_label[lv], ox+12, oy+23, 0.5, (255, 255, 255))
            _ty = py + 58 + 3 * 40 + 6  # 底部建议说明
            self._draw_cn_mixed(frame, "建议：配置好选快、一般选普通、", px+20, _ty, 0.42, (200, 200, 200))
            self._draw_cn_mixed(frame, "卡顿或发热选慢。切换即时生效，", px+20, _ty+20, 0.42, (200, 200, 200))
            self._draw_cn_mixed(frame, "推理线程数下次启动才生效。", px+20, _ty+40, 0.42, (200, 200, 200))

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

    def _dedup_whole_frames(self, frames):
        """整框连拍去重(用户定稿:只去掉几乎一模一样的帧,动作不同/受击明暗递进一律保留,剩几张算几张)。
        判重复=16x16归一化结构相关≥WHOLE_DUP_SIM 且 亮度均值差≤WHOLE_DUP_DMEAN(两条件同时满足);
        只结构像但一明一暗=受击明暗变化,保留。保持原时间顺序返回。"""
        kept, keys, means = [], [], []
        for im in frames:
            if im is None or im.shape[0] < 8 or im.shape[1] < 8:
                continue  # 空/坏帧跳过
            g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
            z = cv2.resize(g, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32).flatten()
            m = float(z.mean()); z = z - m
            nrm = float(np.linalg.norm(z)); v = z / nrm if nrm > 1e-6 else z
            is_dup = False
            for kp, km in zip(keys, means):
                if abs(m - km) <= self.WHOLE_DUP_DMEAN and float(np.dot(v, kp)) >= self.WHOLE_DUP_SIM:
                    is_dup = True
                    break  # 与某张已留帧结构+明暗都几乎一致=重复,丢掉
            if not is_dup:
                kept.append(im); keys.append(v); means.append(m)
        return kept

    def _save_whole_set(self, batch_dir, tpl_imgs, anchors):
        """整框特征组落盘(覆盖式重写本批):每张整人图一个模板、自带脚下基点(ax,ay=相对该图左上)。
        写 t_00.png... + char_feature_set.json(mode='whole')。返回模板数;-1=异常。"""
        import glob
        try:
            os.makedirs(batch_dir, exist_ok=True)
            for f in glob.glob(os.path.join(batch_dir, "t_*.png")):  # 清掉旧整框模板,不残留旧文件
                try: os.remove(f)
                except Exception: pass
            entries = []
            for i, (im, anc) in enumerate(zip(tpl_imgs, anchors)):
                if im is None or anc is None:
                    continue
                fn = "t_%02d.png" % i
                ok, buf = cv2.imencode(".png", im)
                if not ok:
                    continue
                buf.tofile(os.path.join(batch_dir, fn))  # imencode+tofile,中文路径安全
                entries.append({"file": fn, "ax": int(anc[0]), "ay": int(anc[1])})
            fset = {"mode": "whole", "n_templates": len(entries), "templates": entries}
            with open(os.path.join(batch_dir, "char_feature_set.json"), "w", encoding="utf-8") as fp:
                json.dump(fset, fp, ensure_ascii=False, indent=1)
            print("[F4整框] 保存 %s 模板%d张" % (batch_dir, len(entries)))
            return len(entries)
        except Exception:
            import traceback; _debug_log("[F4整框] 保存异常: %s" % traceback.format_exc())
            return -1

    def _append_whole_templates(self, batch_dir, tpl_imgs, anchors):
        """手动补帧:把若干整框模板(各自带基点)追加进一个已存在的whole组,文件名序号续接。返回追加后总数;-1异常。"""
        try:
            os.makedirs(batch_dir, exist_ok=True)
            jp = os.path.join(batch_dir, "char_feature_set.json")
            entries = []
            if os.path.exists(jp):
                old = json.load(open(jp, encoding="utf-8"))
                if old.get("mode") == "whole":
                    entries = list(old.get("templates", []))  # 续接已有条目
            next_i = 0
            for e in entries:  # 算下一个 t_XX 序号,避免覆盖已有
                try:
                    next_i = max(next_i, int(os.path.splitext(e["file"])[0].split("_")[1]) + 1)
                except Exception:
                    pass
            for im, anc in zip(tpl_imgs, anchors):
                if im is None or anc is None:
                    continue
                fn = "t_%02d.png" % next_i; next_i += 1
                ok, buf = cv2.imencode(".png", im)
                if not ok:
                    continue
                buf.tofile(os.path.join(batch_dir, fn))
                entries.append({"file": fn, "ax": int(anc[0]), "ay": int(anc[1])})
            fset = {"mode": "whole", "n_templates": len(entries), "templates": entries}
            with open(jp, "w", encoding="utf-8") as fp:
                json.dump(fset, fp, ensure_ascii=False, indent=1)
            print("[F4整框] 手动追加 %s 现共%d张" % (batch_dir, len(entries)))
            return len(entries)
        except Exception:
            import traceback; _debug_log("[F4整框] 追加异常: %s" % traceback.format_exc())
            return -1

    def _latest_whole_batch(self, create=False):
        """返回最新一个 mode=whole 批次目录;没有时 create=True 返回新建批次路径(仅建目录),否则 None。"""
        import glob
        root = os.path.join(DATA_DIR, "char_capture")
        cands = []
        if os.path.isdir(root):
            for d in sorted(glob.glob(os.path.join(root, "batch_*"))):
                jp = os.path.join(d, "char_feature_set.json")
                if os.path.exists(jp):
                    try:
                        if json.load(open(jp, encoding="utf-8")).get("mode") == "whole":
                            cands.append(d)  # 只认整框组,旧描点批次跳过
                    except Exception:
                        pass
        if cands:
            return cands[-1]
        if create:
            bd = os.path.join(root, "batch_" + time.strftime("%Y%m%d_%H%M%S"))
            os.makedirs(bd, exist_ok=True)
            return bd
        return None

    def _char_feature_capture(self):
        """F4 整框特征组(用户2026-09-13定稿,替代旧逐张描点投票)。
        自动原地连拍:鼠标拖【正方形】框紧贴人物(空白拖=画/框内拖=移/重拖=改)→3秒倒计时做动作→
        固定框内3秒、每秒15张共45张→自动去重(只去几乎相同,明暗递进全留,剩几张算几张)→
        点一次脚下基点(默认框底边正中,整组共用)→存为whole整框组。
        手动补帧:全图拖正方形框住移动/瞬移姿态→裁剪→点这张自己的基点→并入最新whole组。
        查看管理:列整框组、删单张、删整批。模态阻塞主循环(期间不自动打怪),Esc按下边沿逐级回退绝不卡后台。"""
        import glob, shutil
        win = "CharFeature F4"
        try:
            self._update_window_rect()
            CAP_SEC = self.WHOLE_CAP_SEC       # 自动连拍秒数=3
            CAP_HZ = self.WHOLE_CAP_HZ         # 每秒张数=15(3秒共45张)
            CD_SEC = self.WHOLE_COUNTDOWN      # 开拍前倒计时=3秒
            SQ_MIN = self.WHOLE_SQ_MIN         # 正方形选框最小边长
            MW, MH = 780, 560                  # 菜单/管理窗口尺寸(固定不可拉伸,文字不变形)
            AW, AH = 560, 620                  # 定基点窗口尺寸
            _sw, _sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
            mx, my = (_sw - MW) // 2, 40
            VK_ESC = 0x1B
            _fv = cv2.FONT_HERSHEY_SIMPLEX

            def _show_win(w, h, x, y):
                # WINDOW_AUTOSIZE:窗口严格=图像像素、用户不可拉伸(文字绝不压扁),只移动+置顶
                try:
                    cv2.moveWindow(win, int(x), int(y))
                    cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
                except Exception:
                    pass

            def _in_rect(r, x, y):
                return r[0] <= x <= r[2] and r[1] <= y <= r[3]

            def _text_w(text, scale, th):
                try:
                    fs = self._load_cn_font(int(round(round(cv2.getTextSize("A", _fv, scale, th)[0][1]) * 1.3)))
                    dd = ImageDraw.Draw(Image.new("RGB", (1, 1))); w = 0
                    for ch in text:
                        if '一' <= ch <= '鿿' or ch in '，。、；：？！（）【】《》“”':
                            w += int(dd.textbbox((0, 0), ch, font=fs)[2])
                        else:
                            w += cv2.getTextSize(ch, _fv, scale, th)[0][0]
                    return w
                except Exception:
                    return len(text) * int(12 * scale)

            def _ctext(img, text, cx, y, scale, color, th=1):
                self._draw_cn_mixed(img, text, int(cx - _text_w(text, scale, th) / 2), y, scale, color, th)

            def _btn(img, r, name, col=(40, 130, 255), ts=0.9):
                cv2.rectangle(img, (r[0], r[1]), (r[2], r[3]), col, -1)
                cv2.rectangle(img, (r[0], r[1]), (r[2], r[3]), (255, 255, 255), 2)
                _ctext(img, name, (r[0] + r[2]) // 2, (r[1] + r[3]) // 2 + 9, ts, (255, 255, 255), 2)

            def _small_geom(gl, gt, gw, gh, fw, fh):
                # 实时采集时把显示窗挪到游戏窗口外侧(不挡游戏),尺寸按画面比例缩放
                rf, lf = _sw - (gl + gw), gl
                w2 = min(430, max(140, max(rf, lf) - 8)); h2 = int(w2 * fh / max(1, fw))
                if rf >= w2:
                    xx = gl + gw + 6
                elif lf >= w2:
                    xx = gl - w2 - 6
                else:
                    xx = gl
                    if gt + gh + h2 + 6 <= _sh:
                        return w2, h2, max(0, xx), gt + gh + 6
                yy = gt if gt + h2 <= _sh else max(0, _sh - h2)
                return w2, h2, max(0, xx), max(0, yy)

            def _focus_game():
                try:
                    if self.hwnd: user32.SetForegroundWindow(self.hwnd)
                except Exception:
                    pass

            def _focus_cv():
                try:
                    h = user32.FindWindowW(None, win)
                    if h: user32.SetForegroundWindow(h)
                except Exception:
                    pass

            def _list_whole_batches():
                # 只列 mode=whole 整框组(旧描点批次不显示),返回[(批次名,模板数)]
                root = os.path.join(DATA_DIR, "char_capture"); out = []
                if os.path.isdir(root):
                    for d in sorted(glob.glob(os.path.join(root, "batch_*"))):
                        jp = os.path.join(d, "char_feature_set.json")
                        if not os.path.exists(jp):
                            continue
                        try:
                            fs = json.load(open(jp, encoding="utf-8"))
                            if fs.get("mode") == "whole":
                                out.append((os.path.basename(d), int(fs.get("n_templates", 0))))
                        except Exception:
                            pass
                return sorted(out, key=lambda t: t[0])

            def _load_whole(batchdir):
                # 按 json 顺序读整框模板(imdecode兼容中文路径),返回(imgs,metas,fs)
                jp = os.path.join(batchdir, "char_feature_set.json")
                fs = json.load(open(jp, encoding="utf-8"))
                imgs, metas = [], []
                for e in fs.get("templates", []):
                    p = os.path.join(batchdir, e["file"])
                    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if im is not None:
                        imgs.append(im); metas.append(e)
                return imgs, metas, fs

            cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)  # 固定=图像像素、不可拉伸、标题栏可拖
            _show_win(MW, MH, mx, my)
            st = {"phase": "menu", "click": None,
                  "base_full": None, "sq": None, "drag_mode": None, "draw_start": None, "move_off": None,
                  "t0": 0.0, "next": 0.0, "last_full": None,
                  "raw": [], "frames": [], "anchor": None, "idx": 0,
                  "m_img": None, "mb": [], "sel": None, "cells": [],
                  "imgs": [], "metas": [], "amap": None, "aclick": None,
                  "toast": "", "toast_t": 0.0, "ret": "menu"}
            B_START = (40, 80, MW - 40, 150)
            B_MANUAL = (40, 170, MW - 40, 240)
            B_MGR = (40, 260, MW - 40, 330)
            B_EXIT = (40, MH - 90, MW - 40, MH - 30)

            def _goto(ph):
                st["phase"] = ph; st["click"] = None

            def _begin_place(manual):
                # 进入拖框:先校验游戏窗口正常,截一帧全屏作可实时刷新底图
                self._update_window_rect(); wr = self.window_rect
                if not wr or wr.get("left", 0) <= -30000 or wr.get("width", 0) < 200:
                    st["toast"] = "游戏窗口未正常显示(可能最小化)"; st["toast_t"] = time.time(); _goto("toast"); return
                pf = self._capture_window()
                if pf is None:
                    st["toast"] = "截图为空,请先绑定游戏窗口"; st["toast_t"] = time.time(); _goto("toast"); return
                st["base_full"] = pf; st["last_full"] = pf
                st["sq"] = None; st["drag_mode"] = None; st["draw_start"] = None; st["move_off"] = None
                fh, fw = pf.shape[:2]
                _show_win(fw, fh, wr["left"], wr["top"])
                _goto("m_place" if manual else "place")

            def on_mouse(e, x, y, fl, p):
                if e == cv2.EVENT_LBUTTONDOWN:
                    st["click"] = (x, y)
                ph = st["phase"]
                if ph in ("place", "m_place"):
                    bf = st["base_full"]
                    if bf is None:
                        return
                    fh, fw = bf.shape[:2]; sq = st["sq"]
                    if e == cv2.EVENT_LBUTTONDOWN:
                        if sq is not None and _in_rect(sq, x, y):
                            st["drag_mode"] = "move"; st["move_off"] = (x - sq[0], y - sq[1])  # 点框内=整体移动
                        else:
                            st["drag_mode"] = "draw"; st["draw_start"] = (x, y)  # 点空白=重画正方形
                    elif e == cv2.EVENT_MOUSEMOVE and st["drag_mode"] == "draw":
                        sx, sy = st["draw_start"]
                        side = max(abs(x - sx), abs(y - sy))  # 边长=横纵较大值,保证整个人装下
                        if side < SQ_MIN:
                            st["sq"] = None
                        else:
                            if x >= sx: x0, x1 = sx, sx + side
                            else: x0, x1 = sx - side, sx
                            if y >= sy: y0, y1 = sy, sy + side
                            else: y0, y1 = sy - side, sy
                            if x0 < 0: x1, x0 = x1 - x0, 0       # 超左/上边界:整体平移回来,边长不变(恒正方形)
                            if y0 < 0: y1, y0 = y1 - y0, 0
                            if x1 > fw - 1: x0, x1 = x0 - (x1 - (fw - 1)), fw - 1  # 超右/下同理
                            if y1 > fh - 1: y0, y1 = y0 - (y1 - (fh - 1)), fh - 1
                            x0, y0 = max(0, x0), max(0, y0)
                            st["sq"] = (int(x0), int(y0), int(x1), int(y1))
                    elif e == cv2.EVENT_MOUSEMOVE and st["drag_mode"] == "move" and sq is not None:
                        ox, oy = st["move_off"]; side = sq[2] - sq[0]
                        nx = max(0, min(fw - side, x - ox)); ny = max(0, min(fh - side, y - oy))
                        st["sq"] = (int(nx), int(ny), int(nx + side), int(ny + side))
                    elif e == cv2.EVENT_LBUTTONUP:
                        st["drag_mode"] = None
                        q = st["sq"]
                        if q is not None and (q[2] - q[0]) < SQ_MIN:
                            st["sq"] = None  # 边长太小=误触,作废
                elif ph in ("anchor", "m_anchor"):
                    if e == cv2.EVENT_LBUTTONDOWN:
                        st["aclick"] = (x, y)
            cv2.setMouseCallback(win, on_mouse)
            VK_L, VK_U, VK_R_, VK_D = 0x25, 0x26, 0x27, 0x28

            def render_anchor():
                # 把当前模板等比放大居中,画脚下基点(红实心小圆),返回(画布,原图宽,高);amap供点击逆映射
                timg = st["m_img"] if st["phase"] == "m_anchor" else st["frames"][st["idx"]]
                th, tw = timg.shape[:2]
                top, bot = 64, 96
                s = min((AW - 40) / float(tw), (AH - top - bot) / float(th))
                rw, rh = int(tw * s), int(th * s)
                ox, oy = (AW - rw) // 2, top + (AH - top - bot - rh) // 2
                canvas = np.full((AH, AW, 3), 24, np.uint8)
                canvas[oy:oy + rh, ox:ox + rw] = cv2.resize(timg, (rw, rh), interpolation=cv2.INTER_NEAREST)
                st["amap"] = (s, ox, oy)  # 模板坐标=(显示坐标-偏移)/s
                ax, ay = st["anchor"]
                dx, dy = int(ox + ax * s), int(oy + ay * s)
                cv2.circle(canvas, (dx, dy), 6, (0, 0, 255), -1)  # 基点=红色实心小圆(脚下)
                cv2.circle(canvas, (dx, dy), 9, (0, 255, 255), 1)
                return canvas, tw, th

            prev_esc = False
            while True:
                ph = st["phase"]; now = time.time(); key = 255
                esc_down = (user32.GetAsyncKeyState(VK_ESC) & 0x8000) != 0
                esc_pressed = esc_down and not prev_esc
                click = st["click"]; st["click"] = None
                if esc_pressed:  # Esc按下边沿:逐级回退,绝不卡后台
                    if ph == "menu":
                        break
                    if ph == "frames":
                        st["mb"] = _list_whole_batches(); _show_win(MW, MH, mx, my); _goto("batches")
                    else:
                        _show_win(MW, MH, mx, my); _goto("menu")
                    prev_esc = esc_down; continue

                if ph == "menu":
                    img = np.full((MH, MW, 3), 32, np.uint8)
                    _ctext(img, "角色整框特征组", MW // 2, 48, 1.1, (255, 255, 255), 2)
                    _btn(img, B_START, "开始采集(原地连拍)")
                    _btn(img, B_MANUAL, "手动补帧(移动/瞬移)", (40, 110, 180))
                    _btn(img, B_MGR, "查看管理(删张/删批)", (70, 70, 70))
                    _ctext(img, "自动:拖正方形框紧贴身→3秒倒计时做动作→连拍3秒45张→自动去重→点脚下基点保存",
                           MW // 2, 380, 0.58, (180, 220, 255), 1)
                    _ctext(img, "手动:移动/瞬移姿态截几张补进同一组;每组基点=脚下,用于和怪算距离",
                           MW // 2, 410, 0.58, (180, 220, 255), 1)
                    _btn(img, B_EXIT, "退出(Esc)", (90, 90, 90))
                    cv2.imshow(win, img); key = cv2.waitKey(15) & 0xFF
                    if click:
                        x, y = click
                        if _in_rect(B_START, x, y): _begin_place(False)
                        elif _in_rect(B_MANUAL, x, y): _begin_place(True)
                        elif _in_rect(B_MGR, x, y):
                            st["mb"] = _list_whole_batches(); _goto("batches")
                        elif _in_rect(B_EXIT, x, y): break

                elif ph in ("place", "m_place"):
                    fr = self._capture_window()  # 实时画面,方便对准当前人物
                    if fr is not None:
                        st["base_full"] = fr; st["last_full"] = fr
                    disp = st["base_full"].copy(); sq = st["sq"]
                    if sq is not None:  # 方向键整体微调位置
                        bx, by = sq[0], sq[1]; side = sq[2] - sq[0]
                        if user32.GetAsyncKeyState(VK_L) & 0x8000: bx -= 2
                        if user32.GetAsyncKeyState(VK_R_) & 0x8000: bx += 2
                        if user32.GetAsyncKeyState(VK_U) & 0x8000: by -= 2
                        if user32.GetAsyncKeyState(VK_D) & 0x8000: by += 2
                        fh, fw = disp.shape[:2]
                        bx = max(0, min(fw - side, bx)); by = max(0, min(fh - side, by))
                        sq = (bx, by, bx + side, by + side); st["sq"] = sq
                        cv2.rectangle(disp, (sq[0], sq[1]), (sq[2], sq[3]), (0, 200, 255), 2)
                        self._draw_cn_mixed(disp, "边长%d  空格=确定  Esc=回菜单" % side,
                                            sq[0], max(12, sq[1] - 12), 0.7, (0, 0, 255), 2)
                    self._draw_cn_mixed(disp, "空白处按住拖=画正方形框紧贴人物(头到脚);框内拖=移动;重拖=改大小",
                                        12, 30, 0.7, (0, 0, 255), 2)
                    cv2.imshow(win, disp); key = cv2.waitKey(15) & 0xFF
                    if key == ord(' ') and sq is not None and (sq[2] - sq[0]) >= SQ_MIN:
                        if ph == "place":
                            wr = self.window_rect
                            w2, h2, xx, yy = _small_geom(wr["left"], wr["top"], wr["width"], wr["height"],
                                                         disp.shape[1], disp.shape[0])
                            _show_win(w2, h2, xx, yy); st["t0"] = now; _goto("countdown"); _focus_game()
                        else:
                            x0, y0, x1, y1 = sq
                            st["m_img"] = st["base_full"][y0:y1, x0:x1].copy()
                            hh, ww = st["m_img"].shape[:2]
                            st["anchor"] = (ww // 2, hh - 1)  # 默认框底边正中=脚
                            _show_win(AW, AH, (_sw - AW) // 2, 30); _focus_cv(); _goto("m_anchor")

                elif ph == "countdown":
                    fr = self._capture_window()
                    if fr is not None: st["last_full"] = fr
                    disp = st["last_full"].copy(); sq = st["sq"]
                    el = now - st["t0"]; n = max(1, int(CD_SEC - el) + 1)
                    cv2.rectangle(disp, (sq[0], sq[1]), (sq[2], sq[3]), (0, 200, 255), 2)
                    self._draw_cn_mixed(disp, "%d秒后开始,请完整做攻击动作(打怪前→放技能→收招)" % n,
                                        sq[0], max(12, sq[1] - 12), 0.85, (0, 0, 255), 2)
                    cv2.putText(disp, str(n), (sq[0] + (sq[2]-sq[0])//2 - 35, sq[1] + (sq[3]-sq[1])//2 + 45),
                                cv2.FONT_HERSHEY_SIMPLEX, 2.6, (0, 0, 255), 6)
                    wr = self.window_rect
                    w2, h2, _, _ = _small_geom(wr["left"], wr["top"], wr["width"], wr["height"],
                                               disp.shape[1], disp.shape[0])
                    cv2.imshow(win, cv2.resize(disp, (w2, h2))); cv2.waitKey(15)
                    if el >= CD_SEC:
                        st["t0"] = now; st["next"] = now; st["raw"] = []; _goto("capture")

                elif ph == "capture":
                    fr = self._capture_window()
                    if fr is not None: st["last_full"] = fr
                    disp = st["last_full"].copy(); sq = st["sq"]
                    N = int(round(CAP_SEC * CAP_HZ)); DT = 1.0 / CAP_HZ
                    if now >= st["next"] and len(st["raw"]) < N:  # 固定节拍裁框内正方形
                        x0, y0, x1, y1 = sq
                        crop = st["last_full"][y0:y1, x0:x1].copy()
                        if crop.shape[0] == (y1-y0) and crop.shape[1] == (x1-x0):
                            st["raw"].append(crop)
                        st["next"] += DT
                    got = len(st["raw"])
                    cv2.rectangle(disp, (sq[0], sq[1]), (sq[2], sq[3]), (0, 200, 255), 2)
                    cv2.rectangle(disp, (sq[0], sq[1] - 8), (sq[2], sq[1] - 2), (255, 255, 255), -1)
                    cv2.rectangle(disp, (sq[0], sq[1] - 8),
                                  (sq[0] + int((sq[2]-sq[0]) * got / max(1, N)), sq[1] - 2), (0, 0, 255), -1)
                    self._draw_cn_mixed(disp, "采集中 %d/%d 持续做动作" % (got, N),
                                        sq[0], max(12, sq[1] - 16), 0.7, (0, 0, 255), 2)
                    wr = self.window_rect
                    w2, h2, _, _ = _small_geom(wr["left"], wr["top"], wr["width"], wr["height"],
                                               disp.shape[1], disp.shape[0])
                    cv2.imshow(win, cv2.resize(disp, (w2, h2))); cv2.waitKey(5)
                    if got >= N:
                        frames = self._dedup_whole_frames(st["raw"])  # 自动去重,剩几张算几张
                        st["raw"] = []
                        if not frames:
                            st["toast"] = "未采到有效帧,请重试"; st["toast_t"] = now
                            _show_win(MW, MH, mx, my); _goto("toast")
                        else:
                            st["frames"] = frames; st["idx"] = 0
                            hh, ww = frames[0].shape[:2]
                            st["anchor"] = (ww // 2, hh - 1)  # 整组默认基点=框底边正中
                            _show_win(AW, AH, (_sw - AW) // 2, 30); _focus_cv(); _goto("anchor")

                elif ph in ("anchor", "m_anchor"):
                    canvas, tw, th = render_anchor()
                    nfrm = len(st["frames"])
                    title = "定脚下基点(整组共用) %d/%d张" % (st["idx"]+1, nfrm) if ph == "anchor" else "定这张的脚下基点"
                    self._draw_cn_mixed(canvas, title, 8, 24, 0.62, (0, 0, 255), 2)
                    self._draw_cn_mixed(canvas, "左键=基点设到这  方向键微调  空格=保存" +
                                        ("  n/b翻看" if ph == "anchor" else "") + "  Esc=取消",
                                        8, 48, 0.55, (0, 255, 255), 1)
                    self._draw_cn_mixed(canvas, "基点默认在框底边正中(脚),红点对在脚底下即可", 8, AH - 64, 0.55,
                                        (200, 200, 200), 1)
                    self._draw_cn_mixed(canvas, "基点(%d,%d)" % (st["anchor"][0], st["anchor"][1]),
                                        8, AH - 36, 0.6, (0, 255, 255), 1)
                    cv2.imshow(win, canvas); key = cv2.waitKey(15) & 0xFF
                    if st["aclick"] is not None:  # 鼠标点设基点:显示坐标逆映射回模板坐标并限界
                        axs, ays = st["aclick"]; st["aclick"] = None
                        s, ox, oy = st["amap"]
                        tax = int(round((axs - ox) / s)); tay = int(round((ays - oy) / s))
                        st["anchor"] = (max(0, min(tw-1, tax)), max(0, min(th-1, tay)))
                    else:
                        step = 5 if (user32.GetAsyncKeyState(0x10) & 0x8000) else 1  # Shift快移
                        ddx = (1 if user32.GetAsyncKeyState(0x27) & 0x8000 else 0) - (1 if user32.GetAsyncKeyState(0x25) & 0x8000 else 0)
                        ddy = (1 if user32.GetAsyncKeyState(0x28) & 0x8000 else 0) - (1 if user32.GetAsyncKeyState(0x26) & 0x8000 else 0)
                        if ddx or ddy:
                            ax, ay = st["anchor"]
                            st["anchor"] = (max(0, min(tw-1, ax + ddx*step)), max(0, min(th-1, ay + ddy*step)))
                    if key == ord(' '):
                        if ph == "anchor":
                            bd = os.path.join(DATA_DIR, "char_capture", "batch_" + time.strftime("%Y%m%d_%H%M%S"))
                            nk = self._save_whole_set(bd, st["frames"], [st["anchor"]] * len(st["frames"]))
                            st["toast"] = "已保存整框组%d张" % nk if nk >= 0 else "保存异常,见debug.log"
                        else:
                            bd = self._latest_whole_batch(create=True)
                            nk = self._append_whole_templates(bd, [st["m_img"]], [st["anchor"]])
                            st["toast"] = "已补入整框组,现共%d张" % nk if nk >= 0 else "追加异常,见debug.log"
                        st["toast_t"] = time.time(); st["m_img"] = None
                        _show_win(MW, MH, mx, my); _goto("toast")
                    elif key == ord('n') and ph == "anchor":
                        st["idx"] = min(nfrm - 1, st["idx"] + 1)
                    elif key == ord('b') and ph == "anchor":
                        st["idx"] = max(0, st["idx"] - 1)

                elif ph == "batches":
                    img = np.full((MH, MW, 3), 32, np.uint8)
                    _ctext(img, "查看管理 - 选择整框组", MW // 2, 40, 1.0, (255, 255, 255), 2)
                    st["cells"] = []; y0, rh = 70, 58; rows = st["mb"]
                    if not rows: _ctext(img, "(还没有整框组,先开始采集)", MW // 2, 190, 0.8, (180, 180, 180), 1)
                    for k, (name, nt) in enumerate(rows):
                        ry = y0 + k * rh; r = (30, ry, MW - 30, ry + rh - 6); st["cells"].append((r, name))
                        cv2.rectangle(img, (r[0], r[1]), (r[2], r[3]), (45, 55, 70), -1)
                        cv2.rectangle(img, (r[0], r[1]), (r[2], r[3]), (200, 200, 200), 1)
                        self._draw_cn_mixed(img, name.replace("batch_", "批次 "), 50, ry + 20, 0.7, (255, 255, 255), 1)
                        self._draw_cn_mixed(img, "整框模板%d张(点进去可删单张)" % nt, 50, ry + 44, 0.62, (0, 255, 255), 1)
                    BB = (40, MH - 70, 240, MH - 20); _btn(img, BB, "返回", (90, 90, 90))
                    cv2.imshow(win, img); cv2.waitKey(15)
                    if click:
                        x, y = click
                        if _in_rect(BB, x, y):
                            _goto("menu")
                        else:
                            for r, name in st["cells"]:
                                if _in_rect(r, x, y):
                                    st["sel"] = os.path.join(DATA_DIR, "char_capture", name)
                                    st["imgs"], st["metas"], _ = _load_whole(st["sel"])
                                    _goto("frames"); break

                elif ph == "frames":
                    img = np.full((MH, MW, 3), 28, np.uint8)
                    _ctext(img, "%s  点缩略图=删这张" % os.path.basename(st["sel"] or ""), MW // 2, 32, 0.6, (255, 255, 255), 1)
                    cols, cw = 5, 132; chh = cw; gx, gy, pad = 24, 64, 12
                    st["cells"] = []
                    for k, tim in enumerate(st["imgs"]):
                        rr, cc = divmod(k, cols); x = gx + cc * (cw + pad); y = gy + rr * (chh + 30)
                        r = (x, y, x + cw, y + chh); st["cells"].append((r, k))
                        img[y:y+chh, x:x+cw] = cv2.resize(tim, (cw, chh))
                        cv2.rectangle(img, (x, y), (x + cw, y + chh), (0, 230, 0), 2)
                    BDEL = (40, MH - 70, 260, MH - 20); BB = (280, MH - 70, 500, MH - 20)
                    _btn(img, BDEL, "删整批", (50, 50, 200)); _btn(img, BB, "返回批次", (90, 90, 90))
                    cv2.imshow(win, img); cv2.waitKey(15)
                    if click:
                        x, y = click
                        if _in_rect(BDEL, x, y):  # 删整批
                            try:
                                if st["sel"] and os.path.isdir(st["sel"]): shutil.rmtree(st["sel"])
                            except Exception:
                                pass
                            st["mb"] = _list_whole_batches(); _goto("batches")
                        elif _in_rect(BB, x, y):
                            st["mb"] = _list_whole_batches(); _goto("batches")
                        else:
                            hit = None
                            for r, k in st["cells"]:
                                if _in_rect(r, x, y): hit = k; break
                            if hit is not None:  # 删单张:删png+重写json(序号不重排,加载按json读),删空删目录
                                sel = st["sel"]; imgs, metas, _ = _load_whole(sel)
                                rm_file = os.path.join(sel, metas[hit]["file"])
                                try: os.remove(rm_file)
                                except Exception: pass
                                imgs.pop(hit); metas.pop(hit)
                                if metas:
                                    fset = {"mode": "whole", "n_templates": len(metas), "templates": metas}
                                    with open(os.path.join(sel, "char_feature_set.json"), "w", encoding="utf-8") as fp:
                                        json.dump(fset, fp, ensure_ascii=False, indent=1)
                                    st["imgs"], st["metas"] = imgs, metas
                                else:
                                    try: shutil.rmtree(sel)
                                    except Exception: pass
                                    st["mb"] = _list_whole_batches(); _goto("batches")

                elif ph == "toast":
                    img = np.full((180, 620, 3), 30, np.uint8)
                    _ctext(img, st["toast"], 310, 100, 0.72, (0, 255, 255), 2)
                    _show_win(620, 180, (_sw - 620) // 2, (_sh - 180) // 2)
                    cv2.imshow(win, img); cv2.waitKey(1)
                    if now - st["toast_t"] >= 1.2:
                        _show_win(MW, MH, mx, my); _goto("menu")
                prev_esc = esc_down
            try: cv2.destroyWindow(win)
            except Exception: pass
            self._add_log("F4整框特征管理已关闭")
        except Exception:
            import traceback; _debug_log("[F4整框] 异常: %s" % traceback.format_exc())
            try: cv2.destroyWindow("CharFeature F4")
            except Exception: pass

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
        groups = []
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
            grp = [(head + segs[0], col, 0)]
            for sg in segs[1:]:
                grp.append((sg, col, indent))
            groups.append(grp)   # 外层=条目(旧→新)，内层=该条折行(首行带时间在上、续行在下)
        return groups

    def _log_display_lines(self, entries, avail_w):
        """日志区从上到下的显示行：最新条目排最上(条目倒序)，但每条内部保持首行(带时间)在上、续行在下。
        修复折行bug：不能把所有行整体reversed,否则一条多行消息内部也被倒序、时间戳跑到该段最后一行。"""
        disp = []
        for grp in reversed(self._log_wrap_lines(entries, avail_w)):
            disp.extend(grp)
        return disp

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
        _cv.resizeWindow(win, fw, fh)  # 客户区(图像显示区)=游戏窗口尺寸
        _cv.imshow(win, frame)
        _cv.waitKey(1)  # 先让窗口真正创建出来,下面才能FindWindow做精确对齐
        # 客户区精确覆盖游戏window_rect:OpenCV自带窗有标题栏/边框,moveWindow只对齐"窗外框",图像客户区会比
        # 真实游戏窗口错位一个标题栏+边框;黑名单存的是窗口绝对坐标,错位即表现为"保存后红框和原窗口对不上"。
        # 用win32反推客户区屏幕原点、移动窗外框使客户区原点=(window_rect.left,top)、客户区尺寸=fw×fh,
        # 这样框选坐标与抓帧/主蒙板严格1:1同源(人物特征/F9等所有框选一并受益)。
        try:
            import ctypes as _ct
            from ctypes import wintypes as _wt
            _u = _ct.windll.user32
            _u.FindWindowW.restype = _wt.HWND
            _u.FindWindowW.argtypes = [_wt.LPCWSTR, _wt.LPCWSTR]
            _u.GetClientRect.argtypes = [_wt.HWND, _ct.c_void_p]
            _u.GetWindowRect.argtypes = [_wt.HWND, _ct.c_void_p]
            _u.ClientToScreen.argtypes = [_wt.HWND, _ct.c_void_p]
            _u.SetWindowPos.argtypes = [_wt.HWND, _wt.HWND, _ct.c_int, _ct.c_int,
                                        _ct.c_int, _ct.c_int, _wt.UINT]
            _wh = _u.FindWindowW(None, win)
            _wr = self.window_rect

            class _PT(_ct.Structure):
                _fields_ = [("x", _ct.c_long), ("y", _ct.c_long)]
            if _wh and _wr:
                for _ in range(2):  # 边框厚度固定,迭代2次收敛(1次即可,二次保险);NOSIZE|NOZORDER=0x1|0x4
                    _p0 = _PT(0, 0); _u.ClientToScreen(_wh, _ct.byref(_p0))
                    _wr0 = _wt.RECT(); _u.GetWindowRect(_wh, _ct.byref(_wr0))
                    _u.SetWindowPos(_wh, None,
                                    int(_wr0.left + _wr["left"] - _p0.x),
                                    int(_wr0.top + _wr["top"] - _p0.y),
                                    0, 0, 0x0001 | 0x0004)
            else:
                _cv.moveWindow(win, self.window_rect["left"], self.window_rect["top"])
        except Exception:
            try:
                _cv.moveWindow(win, self.window_rect["left"], self.window_rect["top"])
            except Exception:
                pass

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
        X:只朝目标怪那一侧扩寻怪X范围far_range_x(怪在右只搜右/在左只搜左;无怪方位左右各far_range兜底,用户2026-09-15远接近不再限±150);
        Y:上行搜人物头顶(-150~-20)、下行搜脚下(+20~+150),防止一上一下两把相邻梯认错;
        同侧匹配到多把梯子时,选X最贴近目标怪X的那把(用户2026-09-09)。"""
        if frame is None or ppos is None:
            return None
        if not self._ladder_templates and not self._ladder_use_yolo():
            return None   # 既没录梯子模板、也没梯子YOLO模型=无可用来源
        fh, fw = frame.shape[:2]
        ppx, ppy = int(ppos[0]), int(ppos[1])
        _frx = max(50, int(self._get_fight_config().get("far_range_x", COMBAT_FAR_RANGE) or COMBAT_FAR_RANGE))
        if monster_x is None:
            rx1, rx2 = ppx - _frx, ppx + _frx
        elif monster_x >= ppx:
            rx1, rx2 = ppx, ppx + _frx          # 怪在右:只搜右侧(宽度=寻怪X范围,远接近阶段也兜底得到,不再限±150)
        else:
            rx1, rx2 = ppx - _frx, ppx           # 怪在左:只搜左侧
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
        if self._ladder_use_yolo():
            # YOLO通道:同一定向ROI内推理'梯子'类,产出(cx,score)复用下方"离怪最近/置信度最高"选最佳
            cands = [(cx, s) for cx, _cy, s in self._detect_ladder_yolo(frame, (x1, y1, x2, y2))]
        else:
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
        _dbg_t = time.time() * 1000
        if not cands:
            self._ladder_tpl_matches = []
            # 调试蒙板:没匹配到也存ROI(画红框+NO LADDER),真机看哪些梯子识别不到(用户2026-09-09)
            self._ladder_tpl_dbg = {'roi': (x1, y1, x2, y2), 'cands': [], 'best': None,
                                    'ppx': ppx, 'sim': _sim, 't': _dbg_t}
            return None
        if monster_x is not None:
            cands.sort(key=lambda c: abs(c[0] - monster_x))   # 同侧多梯:X最贴近怪
        else:
            cands.sort(key=lambda c: -c[1])                   # 无怪方位:置信度最高
        self._ladder_tpl_matches = cands[:4]
        # 调试蒙板:命中候选(白竖线)+搜索ROI+最佳X/相似度/与人物X差(用户2026-09-09)
        self._ladder_tpl_dbg = {'roi': (x1, y1, x2, y2), 'cands': cands[:4], 'best': cands[0][0],
                                'ppx': ppx, 'sim': _sim, 't': _dbg_t}
        return cands[0][0]

    def _ladder_use_yolo(self):
        """梯子检测后端选择(用户2026-09-10定稿):当前方案录了梯子图片→OpenCV以图识图(返回False);
        没录模板且存在ladder.onnx(含'梯子'类)→YOLO(返回True);都没有→False(无模板自然返回空)。模型懒加载、全程只找一次。"""
        if getattr(self, '_ladder_templates', None):
            return False   # 录了梯子模板一律以图识图,放弃YOLO梯子
        if not getattr(self, '_ladder_yolo_inited', False):
            self._init_ladder_yolo()
        return getattr(self, '_ladder_backend', 'template') == 'yolo'

    def _init_ladder_yolo(self):
        """懒加载梯子YOLO(ladder.onnx),机制同怪物:onnxruntime优先、cv2.dnn兜底;找不到/加载失败静默回退模板,不报错打断。"""
        self._ladder_yolo_inited = True
        try:
            mp = getattr(self, '_ladder_yolo_model_path', None)
            if not mp or not os.path.exists(mp):
                _root = os.path.dirname(os.path.abspath(__file__))
                for _cand in (os.path.join(_root, "ladder.onnx"), os.path.join(DATA_DIR, "ladder.onnx")):
                    if os.path.exists(_cand):
                        mp = _cand
                        break
            if not mp or not os.path.exists(mp):
                self._ladder_backend = 'template'
                return False
            _ncpu = os.cpu_count() or 4
            self._ladder_yolo_threads = self._perf_onnx_threads()  # 同怪物模型,按CPU性能档+核数
            try:
                import onnxruntime as _ort
                _so = _ort.SessionOptions()
                _so.intra_op_num_threads = self._ladder_yolo_threads
                _so.inter_op_num_threads = 1
                try:
                    _so.graph_optimization_level = _ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                except Exception:
                    pass
                self._ladder_yolo_sess = _ort.InferenceSession(
                    mp, sess_options=_so, providers=['CPUExecutionProvider'])
                self._ladder_yolo_iname = self._ladder_yolo_sess.get_inputs()[0].name
                _sh = self._ladder_yolo_sess.get_inputs()[0].shape
                self._ladder_yolo_input = int(_sh[2]) if len(_sh) >= 4 and isinstance(_sh[2], int) and _sh[2] == _sh[3] else 416
                self._ladder_yolo_backend = 'ort'
            except Exception:
                self._ladder_yolo_sess = None
                self._ladder_yolo_net = cv2.dnn.readNetFromONNX(mp)
                self._ladder_yolo_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self._ladder_yolo_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self._ladder_yolo_input = self._read_onnx_input_size(mp, 416)
                self._ladder_yolo_backend = 'cv2'
            self._ladder_yolo_class_id = self._read_ladder_class_id(mp)
            self._ladder_backend = 'yolo'
            print("[梯子YOLO] 加载成功:%s 输入%d 后端%s '梯子'类id=%d" % (
                mp, self._ladder_yolo_input, self._ladder_yolo_backend, self._ladder_yolo_class_id))
            return True
        except Exception as e:
            self._ladder_yolo_sess = None
            self._ladder_yolo_net = None
            self._ladder_backend = 'template'
            print("[梯子YOLO] 不可用,回退以图识图:", e)
            return False

    def _read_ladder_class_id(self, model_path):
        """从模型同目录类别表解析梯子类别id(onnx本身不含类名):ladder.json 或 data.yaml。
        用户训练类别名定为 'tizi'(大小写/空格不敏感),同时兼容中文'梯子'别名;解析不到默认0。"""
        import re as _re

        def _is_tizi(s):
            return str(s).strip().lower() in ("tizi", "梯子")

        _d = os.path.dirname(model_path)
        _jp = os.path.join(_d, "ladder.json")
        if os.path.exists(_jp):
            try:
                with open(_jp, "r", encoding="utf-8") as _f:
                    dd = json.load(_f)
                nm = dd.get('names', dd)
                if isinstance(nm, dict):
                    for k, v in nm.items():
                        if _is_tizi(v):
                            return int(k)
                elif isinstance(nm, list):
                    for i, v in enumerate(nm):
                        if _is_tizi(v):
                            return i
                inv = dd.get('id_map')
                if isinstance(inv, dict):
                    for _n, _id in inv.items():
                        if _is_tizi(_n):
                            return int(_id)
            except Exception:
                pass
        for fn in ("data.yaml", "data.yml", "ladder.yaml"):
            _yp = os.path.join(_d, fn)
            if os.path.exists(_yp):
                try:
                    seg = _re.search(r'names\s*:\s*(.+)', open(_yp, 'r', encoding='utf-8').read()).group(1)
                    lm = [s.strip() for s in _re.findall(r'["\']([^"\']+)["\']', seg)]
                    for i, s in enumerate(lm):
                        if _is_tizi(s):
                            return i
                    for k, v in _re.findall(r'(\d+)\s*:\s*["\']([^"\']+)["\']', seg):
                        if _is_tizi(v):
                            return int(k)
                except Exception:
                    pass
        return 0

    def _detect_ladder_yolo(self, frame, crop_rect=None):
        """梯子YOLO推理→[(cx,cy,score),...](整帧坐标);只留'梯子'类,细长竖条尺寸过滤+NMS。
        crop_rect=(x1,y1,x2,y2)只推理小ROI(近距/常驻白框都传小ROI省CPU),坐标自动加偏移映射回整帧。"""
        if frame is None:
            return []
        if self._ladder_yolo_backend == 'ort' and self._ladder_yolo_sess is None:
            return []
        if self._ladder_yolo_backend == 'cv2' and self._ladder_yolo_net is None:
            return []
        ox = oy = 0
        if crop_rect is not None:
            cx1, cy1, cx2, cy2 = crop_rect
            fh, fw = frame.shape[:2]
            cx1, cy1 = max(0, cx1), max(0, cy1)
            cx2, cy2 = min(fw, cx2), min(fh, cy2)
            if cx2 <= cx1 or cy2 <= cy1:
                return []
            frame = frame[cy1:cy2, cx1:cx2]
            ox, oy = cx1, cy1
        h, w = frame.shape[:2]
        IS = int(getattr(self, '_ladder_yolo_input', 416) or 416)
        scale = min(IS / w, IS / h)
        nw, nh = int(w * scale), int(h * scale)
        pdx, pdy = (IS - nw) // 2, (IS - nh) // 2
        padded = np.full((IS, IS, 3), 114, dtype=np.uint8)
        padded[pdy:pdy + nh, pdx:pdx + nw] = cv2.resize(frame, (nw, nh))
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, (IS, IS), swapRB=True, crop=False)
        try:
            if self._ladder_yolo_backend == 'ort':
                out = self._ladder_yolo_sess.run(
                    None, {self._ladder_yolo_iname: np.ascontiguousarray(blob, dtype=np.float32)})[0][0]
            else:
                self._ladder_yolo_net.setInput(blob)
                out = self._ladder_yolo_net.forward()[0]
        except Exception:
            return []
        cid = int(getattr(self, '_ladder_yolo_class_id', 0))
        det = []
        for row in out:
            try:
                x1, y1, x2, y2, score, cls = row[0], row[1], row[2], row[3], row[4], int(row[5])
            except Exception:
                continue
            if score < self._ladder_yolo_conf or cls != cid:
                continue
            x1 = int((x1 - pdx) / scale) + ox
            y1 = int((y1 - pdy) / scale) + oy
            x2 = int((x2 - pdx) / scale) + ox
            y2 = int((y2 - pdy) / scale) + oy
            if x2 > x1 and y2 > y1:
                bw, bh = x2 - x1, y2 - y1
                if 12 <= bw <= 140 and 35 <= bh <= 320:   # 梯子/绳索细长竖条宽松带(典型白框50宽120高)
                    det.append((x1, y1, x2, y2, float(score)))
        if det:
            boxes = [[d[0], d[1], d[2] - d[0], d[3] - d[1]] for d in det]
            scores = [d[4] for d in det]
            ii = cv2.dnn.NMSBoxes(boxes, scores, self._ladder_yolo_conf, self._ladder_yolo_nms)
            det = [det[i] for i in ii] if len(ii) > 0 else []
        return [((d[0] + d[2]) // 2, (d[1] + d[3]) // 2, d[4]) for d in det]

    def _scan_ladder_marks(self, frame, ppos):
        """常驻白框用:在人物周围(寻怪X/Y范围)用梯子特征模板扫出【所有真实梯子】的屏幕中心。
        返回[(cx,cy,sim),...](按X排序)。用dilate局部极大值避免同一把梯出一片高分区,再按X做NMS合并同梯多峰。
        与_match_ladder_screen_x区别:那个是上梯近距朝怪侧只找一把最佳;这个是常驻、范围更大、要全部梯子。"""
        if frame is None or ppos is None:
            return []
        if not self._ladder_templates and not self._ladder_use_yolo():
            return []   # 既没录梯子模板、也没梯子YOLO模型=无来源
        fh, fw = frame.shape[:2]
        ppx, ppy = int(ppos[0]), int(ppos[1])
        _fc = self._get_fight_config()
        # X统一用寻怪大框(用户2026-09-15拍板·简单方案):上梯精准态不再缩成±150小框——选梯/远接近时人梯X差可达数百px,
        # 小框扫不到目标梯→_ladder_snap_x持续None→选梯后站住发呆;大框全程看得到梯,精准态只保留20ms高频、不再缩范围。
        _rx = max(50, int(_fc.get("far_range_x", COMBAT_FAR_RANGE) or COMBAT_FAR_RANGE))
        if getattr(self, '_ladder_precise_mode', False):
            # 精准态Y只扫同层±150窄带(上下各150),避免把上下层相邻梯一起扫进来认错;非精准用寻怪Y范围
            _yu = LADDER_TPL_Y_FAR
            _yd = LADDER_TPL_Y_FAR
        else:
            _yu = getattr(self, '_far_range_y_up', FAR_RANGE_Y_UP_DEFAULT)
            _yd = getattr(self, '_far_range_y_down', FAR_RANGE_Y_DOWN_DEFAULT)
        x1 = max(0, ppx - _rx)
        x2 = min(fw, ppx + _rx)
        y1 = max(DETECT_TOP_MARGIN, ppy - _yu)
        y2 = min(fh - DETECT_BOTTOM_MARGIN, ppy + _yd)
        if x2 - x1 <= 5 or y2 - y1 <= 5:
            return []
        crop = frame[y1:y2, x1:x2]
        ch, cw = crop.shape[:2]
        if self._ladder_use_yolo():
            # YOLO通道:同范围推理全部'梯子',直接返回[(cx,cy,score)]按X排序,不走模板dilate/NMS
            _yc = self._detect_ladder_yolo(frame, (x1, y1, x2, y2))
            return sorted([(int(cx), int(cy), round(s, 3)) for cx, cy, s in _yc], key=lambda c: c[0])
        _sim = float(getattr(self, '_ladder_tpl_sim', LADDER_TPL_DEFAULT_SIM) or LADDER_TPL_DEFAULT_SIM)
        peaks = []
        _ker = np.ones((5, 5), dtype=np.uint8)
        for tpl in self._ladder_templates:
            timg = tpl["img"]
            th, tw = timg.shape[:2]
            if th > ch or tw > cw:
                continue
            res = cv2.matchTemplate(crop, timg, cv2.TM_CCOEFF_NORMED)
            pool = cv2.dilate(res, _ker)              # 5x5局部最大,只保留局部极大点=每把梯少数几个峰
            ys, xs = np.where((res >= _sim) & (res == pool))
            cand = sorted(((float(res[y, x]), x1 + x + tw // 2, y1 + y + th // 2)
                           for y, x in zip(ys, xs)), reverse=True)
            for s, cx, cy in cand:                    # 按分数从高到低贪心NMS:近邻已选则跳过
                if all(abs(cx - qx) > LADDER_MARK_NMS_X for _, qx, qy in peaks):
                    peaks.append((s, int(cx), int(cy)))
        peaks.sort(key=lambda p: p[1])
        return [(cx, cy, round(s, 3)) for s, cx, cy in peaks]

    def _scr_nudge_timing(self, n):
        """碎步第n拍(0基)的(按住时长ms, 松开后停顿ms, 单拍步长px),上行段3/下行方式二段C共用。
        用户2026-09-11晚定稿:按住时长按拍递减100/60/40ms、各±5随机(原170-200太长对不准);拍间仍停100-110。"""
        _i = min(n, len(LADDER_SCR_NUDGE_STEP_PX) - 1)
        _hold = LADDER_SCR_NUDGE_HOLD_MS[_i] + random.randint(-LADDER_SCR_NUDGE_JITTER, LADDER_SCR_NUDGE_JITTER)
        _gap = random.randint(LADDER_SCR_NUDGE_GAP_RANGE[0], LADDER_SCR_NUDGE_GAP_RANGE[1])
        return _hold, _gap, LADDER_SCR_NUDGE_STEP_PX[_i]

    def _ladder_align_by_screen(self, tpl_x, px, py, now_ms, jump_key):
        """主窗口梯子X对齐起跳(屏幕坐标;用户2026-09-10定稿,全用主窗口屏幕px,X差可正可负按绝对值分段,小碎步全局只此函数、且只在离梯10~40px):
        目标X优先用双框吸附锁定的稳定真实X(_ladder_snap_x,带滞回不抖),没吸附才退回单帧匹配tpl_x(治目标抖动致方向反复)。
        >100按住朝梯大步助跑;助跑中70~100移动中【跑跳·第1次起跳】(朝梯键不松按跳、跳完80ms跳键和左右一起松、同时只按住↑、1秒内Y变小=抓住;贴脸X差≈0带不出水平速度跳不上,故提前到70~100,区间已含主线~110ms延迟补偿);
        跑跳没挂上不回主线、留在to_ladder;35~70按住正常趋近;5~35【全局唯一小碎步】最多3拍修正、任一拍进≤5下帧即直跳;
        ≤5连续2帧【直跳·第2次起跳,只跳1次】,失败即回主线打怪。碎步3拍对不齐/卡住也回主线不死磕。"""
        _sp = self._player_screen_pos
        if _sp is None:
            return False
        _snap_x = getattr(self, '_ladder_snap_x', None)
        if _snap_x is not None:
            tpl_x = _snap_x                  # 吸附稳定真实X优先,单帧模板匹配会在梯纹理上左右抖
        spx = int(_sp[0])
        sdx = tpl_x - spx                       # 正=梯子在屏幕右侧
        asdx = abs(sdx)
        # 趋近速度(自适应提前量):上一检测周期人梯X差缩小了多少(正=在靠近);算出立刻刷新基准,保证下方各return路径都已更新
        _prev_asdx = getattr(self, '_lad_scr_prev_asdx', None)
        _approach_v = (_prev_asdx - asdx) if _prev_asdx is not None else 0.0
        self._lad_scr_prev_asdx = asdx
        # 用户2026-09-11:取消红框/红白合并,_merged=本帧已选中一把梯子白框(三点或就近),有白框中心才许跑跳/直跳
        _merged = _snap_x is not None
        if getattr(self, '_lad_scr_enter_t', 0) == 0:
            self._lad_scr_enter_t = now_ms
        if (not _merged) and now_ms - self._lad_scr_enter_t >= LADDER_MERGE_WAIT_MS:
            # 进屏幕对位超过上限仍没扫到/选中任何白框(没录梯图/没YOLO/相似度不够):不硬跳也不死等,放弃回主线打怪
            self._rlog("进主窗口%.0fms仍没识别到梯子白框,放弃回主线" % LADDER_MERGE_WAIT_MS, LOG_RED, log='behavior')
            self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
            self._reset_climb(); self._decide_climb_fail_action()
            return False
        _dir_vk = VK_RIGHT if sdx > 0 else VK_LEFT
        _opp_vk = VK_LEFT if sdx > 0 else VK_RIGHT
        # 到点抬起上一拍按键:碎步段(段3)定长点动拍的抬键由段3内部闭环判(实时达标/到步长/到时间),不在这抬;其它路径用兜底固定档
        _key_hold = getattr(self, '_lad_scr_key_hold', 0) or \
                    (LADDER_NUDGE_KEY_SMALL_MS if asdx <= LADDER_SCR_SLOW_NUDGE else LADDER_NUDGE_KEY_MS)
        _ak = getattr(self, '_lad_scr_key_vk', None)
        _in_nudge_step = getattr(self, '_lad_scr_nudge_step', 0) or 0
        if _ak is not None and not _in_nudge_step and now_ms - getattr(self, '_lad_scr_key_t', 0) >= _key_hold:
            self._key_up(_ak)                  # 一拍按满抬起,留GAP检测到没到再续下一拍
            self._lad_scr_key_vk = None
            _ak = None
        # 段0(用户2026-09-15):人梯X差>300且配了水平瞬移键/X距离→先朝梯瞬移快速接近。850ms节流复用战斗瞬移时间戳
        # (上梯时战斗瞬移本就不触发,共用一个节流还能防战斗/上梯切换瞬间连闪);瞬移那拍先按住朝梯方向,闪不成(没蓝/被挡)
        # 或处于节流内的帧自然往下落段1按住走,绝不站着等;打怪区刚从该侧拉回的冷却内不朝这侧瞬移(防闪回竖线死循环)。
        _tcfg = self._get_fight_config()
        _tp_key0 = _tcfg.get("teleport_key", "")
        _tp_x0 = int(_tcfg.get("teleport_distance", 0) or 0)
        _tp_dir0 = 'right' if sdx > 0 else 'left'
        _tp_bound0 = (_tp_dir0 == getattr(self, '_bound_last_side', None)
                      and now_ms < getattr(self, '_bound_tp_block_until', 0))
        if (asdx > LADDER_TP_DX and bool(_tp_key0) and _tp_x0 > 0
                and now_ms - self._combat_last_h_teleport > 850 and not _tp_bound0):
            self._hold_toward_ladder(sdx)              # 先按住朝梯方向(瞬移不成也在持续走,不发呆)
            self._pre_teleport_release()               # 松攻击+50ms前摇(攻击硬直会吞瞬移),方向键保持
            self._press_game_key(_tp_key0, duration=60)
            self._combat_last_h_teleport = now_ms
            self._char_relocate_until = now_ms + 700   # 瞬移合法大跳变:人物识别700ms全图重捕
            self._rlog_throttle('lad_tp', "向梯瞬移(X差%.0f>%d朝%s)" % (asdx, LADDER_TP_DX, _tp_dir0), 800, log='behavior')
            return False
        # 段1:X差>100 按住朝梯大步助跑(不磨叽;下行方式二另用LADDER_SCR_NUDGE=35,互不影响)
        if asdx > LADDER_SCR_FAST_PX:
            if _ak is not None:
                self._key_up(_ak)
                self._lad_scr_key_vk = None
            self._lad_scr_ok_frames = 0
            self._lad_scr_stall_t = 0
            self._lad_scr_stall_n = 0
            self._lad_scr_nudge_t = 0   # 离开碎步区:拍数清0、下一拍时刻清0,下次进5~35第一拍立即按
            self._lad_scr_nudge_n = 0
            self._lad_scr_nudge_step = 0
            self._lad_scr_key_hold = 0
            self._hold_toward_ladder(sdx)
            self._lad_scr_running = True   # 大步助跑态:供段2跑跳判定水平惯性来源(22:38起朝梯键正按住也算,双保险)
            return False
        # 段2:助跑趋近中【自适应提前一拍】跑跳(用户2026-09-11 22:38:真机目测离梯70~100带速起跳都能上,补偿主线~110ms延迟往远放)。
        # 水平速度来源(22:38修时序bug):不再只认"先经过>FAST段才置的_lad_scr_running"——小地图|X差|≤7才切屏幕对位、切进来asdx已落在
        # 70~100带内,running要等段2.5帧尾才补上=带内第一帧不跳、下帧已出带(真机5分钟只跳1次的根因)。改为 running 或 "朝梯方向键此刻正按住"
        # (小地图导航本就一直按住朝梯键=正在助跑)即算有水平速度;叠加 asdx≤IDEAL+v 自适应提前,快/延迟大v大就多提前。
        _moving_to_lad = _dir_vk in self._random_move_keys
        # 第一次上梯分带(用户2026-09-14晚):屏幕X差[60,80]内、朝梯键按住、选中白框=移动中跑跳;X差<=60不跑跳(落下面趋近/碎步/段4走直跳三步)
        _rj_trig = (not getattr(self, '_ladder_run_jumped', False)) \
            and _moving_to_lad \
            and LADDER_RUNJUMP_LO <= asdx <= LADDER_RUNJUMP_HI \
            and _merged
        if _rj_trig:
            if _ak is not None:
                self._key_up(_ak)
                self._lad_scr_key_vk = None
            # 用户2026-09-14固定时序:落入60-80跑跳带→按跳,【起跳同时松开左右键】、立刻只按住↑(满1秒后run_hold判Y)
            self._key_up(VK_LEFT)
            self._key_up(VK_RIGHT)
            if VK_DOWN in self._random_move_keys:
                self._key_up(VK_DOWN)
            self._ladder_run_jumped = True
            self._lad_scr_running = False
            self._ladder_vert_jumped = False
            self._ladder_run_dir = 1 if sdx > 0 else -1
            self._ladder_run_t0 = now_ms
            self._climb_start_y = py            # 起跳前站地Y=1秒后判成败基准
            self._press_game_key(jump_key, duration=80)
            if VK_UP not in self._random_move_keys:
                self._key_down(VK_UP)
            _debug_log("[爬梯·屏幕·跑跳] 60-80带起跳(梯X=%d 人X=%d 差%.1f):起跳即松左右、按住↑满%dms再判Y(基准Y=%.0f)" % (
                tpl_x, spx, sdx, RUNJUMP_GRAB_WINDOW_MS, py))
            self._rlog("跑跳上梯(60-80带X差%.1f起跳,松左右按↑1秒判Y)" % sdx, log='behavior')
            self._ladder_jump_phase = 'post_jump'
            self._ladder_post_jump_step = 'run_hold'
            self._ladder_post_jump_t = now_ms
            return False
        # 段2.5:X差>35却没被段2跑跳消费(没进60-80带/没选中白框/跑跳已用/已跌破60归直跳)→按住朝梯单调正常走:
        # 80以上按住等进跑跳带;X差<=60归直跳路径,一路按住走到<=35进段3三拍碎步、<=5段4原地直跳。不reset、不转打怪、不左右摆(段1已挡>100)
        if asdx > LADDER_SCR_BO_LO:
            if _ak is not None:
                self._key_up(_ak)
                self._lad_scr_key_vk = None
            self._lad_scr_nudge_t = 0   # 回到35外趋近区:拍数/下一拍时刻清零,重新进5~35时第一拍立即按
            self._lad_scr_nudge_n = 0
            self._lad_scr_nudge_step = 0
            self._lad_scr_key_hold = 0
            if not getattr(self, '_ladder_run_jumped', False):
                self._lad_scr_running = True
            self._hold_toward_ladder(sdx)
            return False
        # 段4:X差≤5 连续帧原地直跳抓梯(用户2026-09-10晚:10→5,太宽没贴近就跳=抓空)
        if asdx <= LADDER_SCR_TOL:
            if _ak is not None:
                self._key_up(_ak)
                self._lad_scr_key_vk = None
            self._lad_scr_nudge_t = 0   # 已进直跳区=碎步对位成功,清下一拍时刻
            self._lad_scr_nudge_n = 0
            self._lad_scr_nudge_step = 0
            self._lad_scr_key_hold = 0
            if VK_LEFT in self._random_move_keys:
                self._key_up(VK_LEFT)
            if VK_RIGHT in self._random_move_keys:
                self._key_up(VK_RIGHT)
            if _merged:
                self._lad_scr_ok_frames = getattr(self, '_lad_scr_ok_frames', 0) + 1
            else:
                self._lad_scr_ok_frames = 0   # 此刻没选中白框(特征丢帧)不累计直跳帧、不起跳,站住等白框
                # 用户2026-09-11:差≤5却不动=这帧没扫到白框,日志写清已等多久/上限,便于看出是"卡在等白框"
                _wait_merge = now_ms - getattr(self, '_lad_scr_enter_t', now_ms)
                self._rlog_throttle('lad_wait_merge',
                    "已到梯下X差%.1f≤5但此刻没选中白框→不碎步/不直跳,站等识别(%.0f/%dms)" % (
                        sdx, _wait_merge, LADDER_MERGE_WAIT_MS), 500, log='behavior')
            if _merged and self._lad_scr_ok_frames >= LADDER_SCR_HOLD_FRAMES and not getattr(self, '_ladder_vert_jumped', False):
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
        # 段3:5<X差≤35 定长点动三拍(用户2026-09-10晚定稿:单拍最多移动100/80/60px递减、按住时间上限170-200ms随机;
        # 按住中实时闭环:①一到≤5立刻抬(下帧段4直跳)②走够本拍步长③按满时间上限,任一满足即抬;抬起随机停100-110再检测按下一拍;
        # 只朝梯方向绝不反向;任一拍挪进≤5下帧段4直跳;三拍按完仍>5=对不上回主线。>35段2.5按住走、≤5段4直跳)
        self._lad_scr_running = False   # 进入离梯≤35对位区,只点动校正、不再跑跳
        self._lad_scr_ok_frames = 0
        if _ak is not None:
            # 本拍按住中→闭环抬键:实时达标/走够本拍步长/按满时间上限,任一即抬,抬起后停gap再检测是否按下一拍
            _from_x = getattr(self, '_lad_scr_nudge_from_x', spx)
            _signed_move = spx - _from_x              # 带符号位移(正=向右),应与sdx同号才是朝梯子走
            _moved = abs(_signed_move)
            _el = now_ms - getattr(self, '_lad_scr_key_t', now_ms)
            _nstep = getattr(self, '_lad_scr_nudge_step', 0) or 0
            _nhold = getattr(self, '_lad_scr_key_hold', 200) or 200
            _hit_tol = asdx <= LADDER_SCR_TOL
            _hit_step = bool(_nstep and _moved >= _nstep)
            _hit_time = _el >= _nhold
            if _hit_tol or _hit_step or _hit_time:
                self._key_up(_ak)
                self._lad_scr_key_vk = None
                self._lad_scr_nudge_step = 0
                _gapv = getattr(self, '_lad_scr_nudge_gap', 100)
                self._lad_scr_nudge_t = now_ms + _gapv  # 抬起后停gap再允许下一拍
                _why = "已进≤5直跳区" if _hit_tol else ("走到本拍步长%dpx" % _nstep if _hit_step else "按满%dms时间上限" % _nhold)
                _nextplan = "下帧进≤5直跳" if _hit_tol else (
                    "停%dms后按第%d拍" % (_gapv, self._lad_scr_nudge_n + 1) if self._lad_scr_nudge_n < LADDER_SCR_NUDGE_MAX_TRIES else "三拍用完→回主线打怪")
                # 用户2026-09-11:每拍抬起都写明"移动前/后离梯多远、实际挪了多少、为什么抬、下一步怎么调"
                _debug_log("[梯对位·抬键] 第%d拍 起X=%.0f→现X=%d 实移%+.1fpx(应朝%s) 按住%d/%dms 抬因=%s 现X差%.1f →%s" % (
                    self._lad_scr_nudge_n, _from_x, spx, _signed_move, "右" if sdx > 0 else "左",
                    _el, _nhold, _why, asdx, _nextplan))
                # 监管线(用户2026-09-11):按满了整拍时长却几乎零位移=这拍按键没让人物动起来,明确报出"没动的原因",不原地干站
                if _hit_time and not _hit_tol and _moved < 2:
                    self._lad_scr_nomove_n = getattr(self, '_lad_scr_nomove_n', 0) + 1
                    _rev = (_signed_move != 0 and _signed_move * sdx < 0)
                    _reason = "人物朝反方向挪(方向键疑似被战斗/边缘闸另一线程松开)" if _rev else (
                        "按住%dms人物屏幕X零位移:按压时长太短游戏没起步/方向键被其它线程抢松/被地形卡住/人物特征X没刷新" % _nhold)
                    self._rlog("梯对位监管:第%d拍按了没动→%s" % (self._lad_scr_nudge_n, _reason), LOG_RED, log='behavior')
                    _debug_log("[梯对位·没动] %s;累计没动%d次(≥%d回主线,不原地干站)" % (
                        _reason, self._lad_scr_nomove_n, LADDER_SCR_STALL_MAX))
                    self._lad_scr_stall_n = getattr(self, '_lad_scr_stall_n', 0) + 1
                    if self._lad_scr_stall_n > LADDER_SCR_STALL_MAX:
                        self._rlog("梯对位连续按了不动,回主线重选(不死磕)", LOG_RED, log='behavior')
                        self._key_up(VK_LEFT); self._key_up(VK_RIGHT)
                        self._reset_climb(); self._decide_climb_fail_action()
            return False
        # _ak is None:松开停gap中,到下一拍最早时刻才按
        if now_ms >= getattr(self, '_lad_scr_nudge_t', 0):
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
            # 三拍按完仍>5(没进直跳区)=对不上,放弃对位回主线打怪(用户2026-09-10晚:最多三次、不再校准)
            if self._lad_scr_nudge_n >= LADDER_SCR_NUDGE_MAX_TRIES:
                self._rlog("定长点动%d拍仍X差%.1f未进5px直跳区,放弃回主线打怪" % (LADDER_SCR_NUDGE_MAX_TRIES, asdx),
                           LOG_RED, log='behavior')
                self._key_up(VK_LEFT)
                self._key_up(VK_RIGHT)
                self._reset_climb()
                self._decide_climb_fail_action()
                return False
            self._key_up(_opp_vk)
            _this_hold, _this_gap, _this_step = self._scr_nudge_timing(self._lad_scr_nudge_n)  # 按住上限/松开停顿/单拍步长
            self._lad_scr_key_hold = _this_hold            # 本拍按住时间上限(闭环里按满也抬)
            self._lad_scr_nudge_gap = _this_gap            # 抬起后停顿
            self._lad_scr_nudge_step = _this_step          # 本拍最多移动px(走到就抬)
            self._lad_scr_nudge_from_x = spx               # 本拍起点X(算实际位移)
            self._lad_scr_nudge_n += 1
            self._key_down(_dir_vk)
            self._lad_scr_key_vk = _dir_vk
            self._lad_scr_key_t = now_ms
            self._lad_scr_ref_spx = spx
            # 用户2026-09-11:每一拍按下都打日志(不限频),写明"离梯多远、朝哪、按多久、走多少、抬后停多久、达标怎么收"
            _debug_log("[梯对位·按下] 第%d拍 梯在%s 现X差%.1f 按住%d±%dms/本拍步长%dpx/抬后停%dms;一到≤5立即抬→下帧直跳,按满没动监管会报原因" % (
                self._lad_scr_nudge_n, "右" if sdx > 0 else "左", asdx,
                _this_hold, LADDER_SCR_NUDGE_JITTER, _this_step, _this_gap))
            self._rlog_throttle('lad_scr', "屏幕定长点动(梯在%s,X差%.1f,第%d拍步长%dpx按住上限%dms停%dms)" % (
                "右" if sdx > 0 else "左", asdx, self._lad_scr_nudge_n, _this_step, _this_hold, _this_gap), 400, log='behavior')
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
        """三点在各自当前位置取小ROI与上一帧比,返回(垂直静止点数n_still,有效点数n_valid)。
        【用户2026-09-10·只认垂直运动】爬梯是人物相对背景做上下运动;到顶时被怪撞只会左右晃。
        旧法整框absdiff不分方向,被怪横向一撞框内背景横向错位就误判"还在动"→拖着不判到顶。
        新法取灰度【行投影】(沿列求每行平均亮度):它对纵向位移敏感、对横向平移不敏感(横向错位被行平均抹掉)。
        在±CLIMB_VSEARCH_R内搜最佳垂直平移dy,比较零位移残差sad0与最优残差best_sad:
          ·sad0≤阈=本来就没动→垂直静止;
          ·存在非零dy且把残差消掉≥CLIMB_VMOTION_RATIO=真在上下爬→垂直在动;
          ·纵向怎么移都对不齐(残差消不掉)=差异来自横向被撞/噪声→按垂直静止(不挡到顶)。
        锚点突变(换角/收边位移>2px)、首帧、纯色平坦框只建基准/不计,不计静也不计动。
        返回语义与旧版一致(静止点/有效点),调用处 n_valid-n_still 即"垂直在动点数",两步法对接不变。"""
        if frame is None:
            return 0, 0
        n_still = 0
        n_valid = 0
        hs = CLIMB_BOX_SIZE // 2
        R = CLIMB_VSEARCH_R
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
            g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
            pg = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY).astype(np.float32)
            n_valid += 1
            prof = g.mean(axis=1)           # 行投影:长度=框高,纵向位移=整向量上下平移
            pprof = pg.mean(axis=1)
            sad0 = float(np.abs(prof - pprof).mean())     # 零垂直位移残差
            if sad0 <= BG_DIFF_THRESHOLD:
                n_still += 1               # 零位残差就很小=完全没动
                continue
            best_dy, best_sad = 0, sad0
            for dy in range(1, R + 1):     # 搜上下平移,取重叠段残差最小者
                su = float(np.abs(prof[dy:] - pprof[:-dy]).mean())
                sd = float(np.abs(prof[:-dy] - pprof[dy:]).mean())
                if su < best_sad:
                    best_sad, best_dy = su, dy
                if sd < best_sad:
                    best_sad, best_dy = sd, -dy
            improve = (sad0 - best_sad) / (sad0 + 1e-6)
            v_moving = (best_dy != 0 and improve >= CLIMB_VMOTION_RATIO)  # 纵向对齐显著解释差异=真在爬
            if not v_moving:
                n_still += 1               # 横向被撞/噪声:纵向无运动,按垂直静止(到顶照常触发)
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
            # 上梯高频档(方案B):实测mss单次grab固定~17ms与截取面积无关(缩截图无效),瓶颈在人物匹配搜索区面积。
            # precise档人物30ms仅移动十几px、贴梯几乎不动,把人物ROI从±200(400²)缩到±100(200²,1/4面积),匹配~16ms→~4ms,
            # 单轮grab17+匹配4≈21ms压进30ms;万一±100没找到,下方全图匹配兜底(9205起)绝不丢人物。其它状态保持±200不变。
            if getattr(self, '_ladder_precise_mode', False) \
                    and getattr(self, '_climb_state', 'none') in ('to_ladder', 'climbing'):
                roi_half = 100
            else:
                roi_half = 200  # 常态400x400范围
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
            # 游戏画面识别范围：写死固定窗口尺寸 GAME_W x GAME_H(1280x800，用户定稿不要动态识别，窗口变大也会被拉回，避免识别范围随窗口漂移)
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
        """后台线程：主游戏窗口唯一的置顶透明蒙板(Win32分层窗),每100ms更新
        统一显示:角色锚点框/黑名单框/黄蓝范围框 + 角色点 + 怪物框/连线 + 血条蓝条(主窗口只此一套蒙板)"""
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
        gdi32.CreateRectRgn.restype = ctypes.c_void_p
        gdi32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.SelectClipRgn.restype = ctypes.c_void_p
        gdi32.SelectClipRgn.argtypes = [wintypes.HDC, ctypes.c_void_p]
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
                        return 0
                elif msg == 0x0204:  # WM_RBUTTONDOWN：右键点检测框弹编辑/保存
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
                        # 调试总开关(F4):关时data置空→所有实战框/点/线都不画,蒙板只剩透明背景=干净原画面
                        data = self._monster_overlay_data if getattr(self, '_debug_overlay', True) else {}
                        # 做法2(用户2026-09-14):蒙板仍盖整个外窗,但实战框/点/线只允许画在游戏画面(客户区)子矩形内,
                        # 标题栏+边框那圈一律裁掉→任何框都不伸出游戏画面。纯GDI显示裁剪,坐标与战斗判定一律不动;
                        # 校准引导/基点在这之前已画完,不受裁剪影响。
                        _clip_rgn = None
                        _cs = getattr(self, 'client_subrect', None)
                        if data and _cs:
                            _clip_rgn = gdi32.CreateRectRgn(int(_cs[0]), int(_cs[1]), int(_cs[2]), int(_cs[3]))
                            if _clip_rgn:
                                gdi_objs.append(_clip_rgn)
                                gdi32.SelectClipRgn(hdc, _clip_rgn)
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

                            # === 新角色锚点:局部跟踪搜索范围框(白细框,全图重搜时不画)+识别到的锚点缩小多边形(识别不到不画) ===
                            _rsb = data.get('role_search_box')
                            if _rsb:
                                _bx0, _by0, _bx1, _by1 = _rsb
                                rpen = gdi32.CreatePen(0, 1, 0xFFFFFF)  # 白色1px=rx/ry局部搜索范围
                                if rpen:
                                    gdi_objs.append(rpen)
                                old_rpen = gdi32.SelectObject(hdc, rpen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷
                                gdi32.Rectangle(hdc, int(_bx0), int(_by0), int(_bx1), int(_by1))
                                gdi32.SelectObject(hdc, old_rpen)
                            # 三个角色锚点统一橙色框(用户:不要五颜六色);禁用品红0xFF00FF=蒙板透明色键、画了会被抠空看不见
                            _role_colors = {"name": 0x00A5FF, "face_r": 0x00A5FF, "back": 0x00A5FF,
                                            "pet1": 0x00A5FF, "pet2": 0x00A5FF, "pet3": 0x00A5FF}
                            for _rk, (_rpts, _rscore) in (data.get('role_anchor_polys') or {}).items():
                                if not _rpts:
                                    continue
                                _rc = _role_colors.get(_rk, 0xFFFFFF)
                                apen = gdi32.CreatePen(0, 2, _rc)  # 名=青 脸=绿 后脑=品红 宠物=黄
                                if apen:
                                    gdi_objs.append(apen)
                                old_apen = gdi32.SelectObject(hdc, apen)
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷只描边
                                _p0 = _rpts[0]
                                gdi32.MoveToEx(hdc, int(_p0[0]), int(_p0[1]), None)
                                for _px, _py in _rpts[1:]:
                                    gdi32.LineTo(hdc, int(_px), int(_py))
                                gdi32.LineTo(hdc, int(_p0[0]), int(_p0[1]))  # 闭合(用户:框上不显示任何文字)
                                gdi32.SelectObject(hdc, old_apen)

                            # 角色识别黑名单矩形(纯红0x0000FF细线,调试显示开时可见,避开品红透明色键)
                            for _br in (data.get('role_blocklist') or []):
                                try:
                                    _bx0, _by0, _bw, _bh = int(_br[0]), int(_br[1]), int(_br[2]), int(_br[3])
                                    _bpen = gdi32.CreatePen(0, 1, 0x0000FF)
                                    if _bpen:
                                        gdi_objs.append(_bpen)
                                    _old_bpen = gdi32.SelectObject(hdc, _bpen)
                                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷只描边
                                    gdi32.Rectangle(hdc, _bx0, _by0, _bx0 + _bw, _by0 + _bh)
                                    gdi32.SelectObject(hdc, _old_bpen)
                                except Exception:
                                    pass

                            # 两个实战范围框(都以人物为中心、随人移动):黄=怪物识别(YOLO)范围,紫=人物技能(攻击射程)范围
                            # 黄=怪物识别范围;技能范围用蓝(禁用品红0xFF00FF=透明色键,旧紫框被抠空才看不见,用户:换蓝)
                            for _rk2, _rc2, _rlab in (("yolo_crop", 0x0000FFFF, "怪物识别"),
                                                      ("feat_crop", 0x00FF0000, "技能范围")):
                                _cb = data.get(_rk2)
                                if _cb:
                                    _cpen = gdi32.CreatePen(0, 2, _rc2)
                                    if _cpen:
                                        gdi_objs.append(_cpen)
                                    old_cpen = gdi32.SelectObject(hdc, _cpen)
                                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷只描边
                                    gdi32.Rectangle(hdc, int(_cb[0]), int(_cb[1]), int(_cb[2]), int(_cb[3]))
                                    gdi32.SelectObject(hdc, old_cpen)
                                    cfont = gdi32.CreateFontW(15, 0, 0, 0, 400, 0, 0, 0, 134, 3, 2, 1, 49, "微软雅黑")
                                    if cfont:
                                        gdi_objs.append(cfont)
                                    old_cfont = gdi32.SelectObject(hdc, cfont)
                                    gdi32.SetTextColor(hdc, _rc2); gdi32.SetBkMode(hdc, 1)
                                    gdi32.TextOutW(hdc, int(_cb[0]) + 3, int(_cb[1]) + 2, _rlab, len(_rlab))
                                    gdi32.SelectObject(hdc, old_cfont)

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
                                # ===== 梯子框(用户2026-09-11定稿):所有真实梯子先画细白框;选中哪把,哪把白框消失、原地转红框 =====
                                # 红框位置=被选中白框的特征中心(三点/就近选的真实梯子),不是倍率推算、不会漂;未选中的保持细白框
                                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # 空刷只画框
                                _ld_sel = data.get('ladder_sel')
                                _sel_x = _ld_sel[0] if _ld_sel else None
                                _lm_pen = gdi32.CreatePen(0, 2, 0xFFFFFF)   # 未选中=细白框2px
                                if _lm_pen:
                                    gdi_objs.append(_lm_pen)
                                    _o_lm = gdi32.SelectObject(hdc, _lm_pen)
                                    for (_lmx, _lmy) in data.get('ladder_marks', []):
                                        if _sel_x is not None and abs(_lmx - _sel_x) <= LADDER_MARK_NMS_X:
                                            continue   # 被选中的这把白框不画(下面原地转红框)
                                        gdi32.Rectangle(hdc, _lmx - 25, _lmy - 60, _lmx + 25, _lmy + 60)  # 宽50高120,中心=白框中心
                                    gdi32.SelectObject(hdc, _o_lm)
                                if _ld_sel:
                                    _sx, _sy = _ld_sel[0], _ld_sel[1]   # 选中梯:坐标就是白框特征中心,不漂移
                                    _sel_pen = gdi32.CreatePen(0, 3, 0x0000FF)  # 选中=3px红框(BGR红)
                                    if _sel_pen:
                                        gdi_objs.append(_sel_pen)
                                        _o_sp = gdi32.SelectObject(hdc, _sel_pen)
                                        gdi32.Rectangle(hdc, _sx - 25, _sy - 60, _sx + 25, _sy + 60)
                                        gdi32.SelectObject(hdc, _o_sp)
                                    gdi32.SetTextColor(hdc, 0x0000FF)
                                    gdi32.SetBkMode(hdc, 1)
                                    _stxt = "梯X:%d" % _sx
                                    gdi32.TextOutW(hdc, _sx - 25, _sy - 78, _stxt, len(_stxt))
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

                        # 打怪区域·左右竖线与Y上下限平台高亮已改画到UI小地图(照平台绿线原理缩放显示),游戏蒙板不再绘制(用户2026-09-11)

                    except Exception as e:
                        _debug_log("[怪物蒙板] 绘制异常: %s" % e)
                    finally:
                        try:
                            gdi32.SelectClipRgn(hdc, None)  # 先解除裁剪区,下面才能DeleteObject成功,防GDI句柄泄漏
                        except Exception:
                            pass
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
                if self.hwnd:
                    # 蒙板自己每轮直接GetWindowRect取游戏窗口实时几何(该API微秒级、只读,与主循环_update互不干扰)。
                    # 旧逻辑只读self.window_rect缓存、要等主循环十几秒刷新一次→拖游戏窗口时黑名单等静态框钉在屏幕原地。
                    _gr = ctypes.create_string_buffer(16)
                    user32.GetWindowRect(self.hwnd, _gr)
                    _gl, _gt, _grr, _gb = struct.unpack("llll", _gr.raw)
                    _cur_geom = (_gl, _gt, _grr - _gl, _gb - _gt)
                    if first_draw[0]:
                        _debug_log("[怪物蒙板] 窗口几何: %dx%d +%d+%d" % (_cur_geom[2], _cur_geom[3], _cur_geom[0], _cur_geom[1]))
                        first_draw[0] = False
                    # 载体尺寸硬锁死(用户2026-09-14:寻怪黄框跑到游戏窗外=载体蒙板变大/错位):
                    # 每轮读蒙板"自身实际几何"与游戏外窗对比,只要不一致(被系统/其它逻辑改大或错位、或没跟上),
                    # 50ms内立即SetWindowPos拉回=游戏外窗;一致才跳过(保留CPU优化、不多重绘)。
                    _ob = ctypes.create_string_buffer(16)
                    user32.GetWindowRect(hwnd, _ob)
                    _osl, _ost, _osr, _osb = struct.unpack("llll", _ob.raw)
                    _ov_geom = (_osl, _ost, _osr - _osl, _osb - _ost)
                    if _ov_geom != _cur_geom:
                        user32.SetWindowPos(hwnd, -1, _cur_geom[0], _cur_geom[1],
                                            _cur_geom[2], _cur_geom[3], 0x0050)
                        self._overlay_last_geom = _cur_geom
                        _debug_log("[怪物蒙板] 载体偏离游戏已拉回: 蒙板%s -> 游戏%s" % (_ov_geom, _cur_geom))
                elif first_draw[0]:
                    _debug_log("[怪物蒙板] 警告：hwnd无效")
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
        _debug_log("[怪物蒙板] Win32窗口已销毁")

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
            self._yolo_sess = None
            self._yolo_backend = None
            self._yolo_iname = "images"
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
        """加载YOLO onnx模型。优先onnxruntime(新版ultralytics导出模型只有ort能算对且CPU更快、以后可走显存)，
        ort不可用时回退cv2.dnn(只能正确跑旧版导出的640模型)。"""
        if self._yolo_backend is not None and (self._yolo_sess is not None or self._yolo_net is not None):
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
            # CPU推理线程按逻辑核自适应、留2核给游戏/主线程/系统(用户2026-09-09要适配低配四核)
            _ncpu = os.cpu_count() or 4
            self._yolo_threads = self._perf_onnx_threads()  # CPU性能三档+核数定推理线程(慢档封顶2,用户2026-09-11)
            # —— 优先 onnxruntime ——
            # 2026-09-10实测:新版ultralytics(8.4.x)导出的onnx(含C3k2/新NMS算子)在cv2.dnn下会算错
            # (输出score>1、巨型误检框,416/640、换opset/simplify均无效),onnxruntime结果正确且CPU更快;
            # 以后装onnxruntime-gpu且有N卡,把providers改成CUDA即可把推理挪到显存(用户要的GPU/CPU共存)。
            try:
                import onnxruntime as _ort
                _so = _ort.SessionOptions()
                _so.intra_op_num_threads = self._yolo_threads
                _so.inter_op_num_threads = 1
                try:
                    _so.graph_optimization_level = _ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                except Exception:
                    pass
                self._yolo_sess = _ort.InferenceSession(
                    model_path, sess_options=_so, providers=['CPUExecutionProvider'])
                self._yolo_iname = self._yolo_sess.get_inputs()[0].name
                _sh = self._yolo_sess.get_inputs()[0].shape  # [1,3,H,W]
                if len(_sh) >= 4 and isinstance(_sh[2], int) and isinstance(_sh[3], int) and _sh[2] == _sh[3]:
                    self._yolo_input = int(_sh[2])
                else:
                    self._yolo_input = self._read_onnx_input_size(model_path, 640)
                self._yolo_backend = 'ort'
            except Exception as _oe:
                # —— 回退 cv2.dnn(仅旧版导出的640模型能算对) ——
                self._yolo_sess = None
                self._yolo_net = cv2.dnn.readNetFromONNX(model_path)
                self._yolo_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self._yolo_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                try:
                    cv2.setNumThreads(self._yolo_threads)
                except Exception:
                    pass
                # 输入尺寸自动读模型(写死640会让重导出的320/416小模型白减负):读不到回退640
                self._yolo_input = self._read_onnx_input_size(model_path, 640)
                self._yolo_backend = 'cv2'
                print("[YOLO] onnxruntime不可用(%s),回退cv2.dnn后端(仅旧版640模型保证正确)" % _oe)
            # YOLO帧率间隔由CPU性能三档统一给(慢档=低配放慢、快档=跟手,已替代原按核数_k系数):
            # 检测线程运行中每轮读_perf_val、切档即时生效,这里两个gap作首次初值/兜底
            self._yolo_fast_gap = round(self._perf_val('yolo_fast_s'), 3)
            self._yolo_slow_gap = round(self._perf_val('yolo_slow_s'), 3)
            _bk = 'onnxruntime-CPU' if self._yolo_backend == 'ort' else 'OpenCV-cv2.dnn(兜底)'
            print("[YOLO] 加载成功:%s 输入%dpx CPU线程%d/%d核 后端%s 找怪%.2fHz战斗%.2fHz" % (
                model_path, self._yolo_input, self._yolo_threads, _ncpu, _bk,
                1.0 / self._yolo_fast_gap, 1.0 / self._yolo_slow_gap))
            return True
        except Exception as e:
            print("[YOLO] 加载失败:", e)
            return False

    def _read_onnx_input_size(self, model_path, default=640):
        """读onnx模型输入边长(正方形输入),用于自动适配320/416/640等不同导出尺寸,换小模型无需改代码。
        用已装的onnxruntime只读shape(不推理,老版本run可能崩但读shape安全);任何失败回退default。"""
        try:
            import onnxruntime as _ort
            _sess = _ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
            _sh = _sess.get_inputs()[0].shape   # 形如 [1,3,H,W];动态维是字符串/负数
            _h, _w = int(_sh[2]), int(_sh[3])
            del _sess
            if _h == _w and 32 <= _h <= 4096:
                return _h
        except Exception:
            pass
        return default

    def _nms_monsters(self, detections):
        """对一批怪框做一次NMS去重(单个区域、多个黑名单子块合并后都用它)。"""
        if not detections:
            return []
        boxes = [[d[0], d[1], d[2] - d[0], d[3] - d[1]] for d in detections]
        scores = [d[4] for d in detections]
        indices = cv2.dnn.NMSBoxes(boxes, scores, self._yolo_conf, self._yolo_nms)
        return [detections[i] for i in indices] if len(indices) > 0 else []

    def _detect_monsters(self, frame, crop_rect=None, _bl_split=True):
        """YOLO检测怪物，返回 [(x1,y1,x2,y2,score), ...]
        crop_rect: (x1,y1,x2,y2) 限定检测区域（人物+寻怪范围），None=全图检测,裁剪后只推理局部、坐标映射回原图。
        黑名单勾选'对怪物也生效'时在【推理前】就用黑名单把搜索区几何切成多块分别推理(复用_role_sub_rects),
        YOLO根本不看拉黑那块(用户:要识别前扣除,不是识别完再丢结果);各块结果合并再NMS。_bl_split=False=递归内的单个子块、不再切。"""
        if frame is None or not self._init_yolo():
            return []
        # —— 黑名单几何扣除(识别前):把本次搜索区按黑名单切成若干不含黑名单的子矩形,逐块推理后合并 ——
        _rrec = self._role_rec or {}
        if _bl_split and _rrec.get("blocklist_monster") and _rrec.get("blocklist"):
            _fh0, _fw0 = frame.shape[:2]
            if crop_rect is None:
                S0 = (0, 0, _fw0, _fh0)
            else:
                S0 = (max(0, int(crop_rect[0])), max(0, int(crop_rect[1])),
                      min(_fw0, int(crop_rect[2])), min(_fh0, int(crop_rect[3])))
            _subs = self._role_sub_rects(S0, 20, 30)  # 子块至少放得下最小怪(宽20高30),更小的碎片不推理
            if _subs and not (len(_subs) == 1 and tuple(_subs[0]) == S0):  # 搜索区确实被黑名单切开才分块
                _allm = []
                for _sb in _subs:
                    _allm.extend(self._detect_monsters(frame, tuple(_sb), _bl_split=False))
                return self._nms_monsters(_allm)  # 跨子块边界可能重复检到同一只怪,合并后统一NMS
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
        INPUT_SIZE = int(getattr(self, '_yolo_input', 640) or 640)  # 跟随模型导出尺寸(320/416/640自动适配,小模型从根源降CPU)
        scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
        new_w, new_h = int(w * scale), int(h * scale)
        pad_x = (INPUT_SIZE - new_w) // 2
        pad_y = (INPUT_SIZE - new_h) // 2
        resized = cv2.resize(frame, (new_w, new_h))
        padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        padded[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = resized
        blob = cv2.dnn.blobFromImage(padded, 1/255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
        if self._yolo_backend == 'ort' and self._yolo_sess is not None:
            out = self._yolo_sess.run(
                None, {self._yolo_iname: np.ascontiguousarray(blob, dtype=np.float32)})[0][0]
        else:
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
        # NMS去重(黑名单分块推理时,外层合并后还会再统一NMS一次)
        detections = self._nms_monsters(detections)
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

    # ===== 整框特征组定脚(whole,F4正方形框连拍一组整人模板,每模板自带脚下基点ax/ay) =====
    WHOLE_MATCH_SCALE = 0.5   # 匹配统一缩半(面积1/4提速,颜色面色不受影响),坐标再除回原尺度
    WHOLE_THR = 0.60          # 综合分采信阈值(整框大图,用户定稿0.6不误判)
    WHOLE_W_COLOR = 0.70      # 综合分=颜色(HS色相饱和,丢V明度抗受击明暗)权重
    WHOLE_W_SHAPE = 0.30      # 综合分=形状(灰度)权重
    WHOLE_CAP_SEC = 3.0       # F4自动连拍秒数(用户定稿3秒)
    WHOLE_CAP_HZ = 15         # F4每秒张数(3秒共45张,再自动去重)
    WHOLE_COUNTDOWN = 3.0     # F4开拍前倒计时秒数
    WHOLE_DUP_SIM = 0.95      # 连拍去重:16x16归一化结构相关≥此值
    WHOLE_DUP_DMEAN = 12.0    # 且亮度均值差≤此值才算重复(只结构像但明暗递进=受击,保留)
    WHOLE_SQ_MIN = 40         # F4正方形选框最小边长(px)
    WHOLE_TRACK_MX = 55       # 跟踪小窗:模板相对脚的外延之外,水平再留一检测周期位移余量
    WHOLE_TRACK_MU = 36       # 跟踪小窗:向上额外余量
    WHOLE_TRACK_MD = 20       # 跟踪小窗:向下额外余量
    WHOLE_COARSE_MX = 150     # 光点粗位大窗水平余量(光点有镜头惯性误差,窗要罩得住真人)
    WHOLE_COARSE_MU = 120     # 粗位大窗向上余量
    WHOLE_COARSE_MD = 190     # 粗位大窗向下余量
    WHOLE_MAX_MOVE = 45       # 跟踪:候选脚离上一脚超此=小窗没跟上,丢并转粗位重捕(人一帧不瞬移)

    def _load_char_vote_set(self):
        """载入最新 whole 整框特征组。每模板=(缩半灰度gh, 缩半HS颜色ch, 基点ax, 基点ay, 原高th0, 原宽tw0)。
        基点ax/ay=相对该模板左上的脚下坐标(自动组整组共用/手动帧各自带),不缩放、匹配时按缩半比还原。
        只认 mode=whole(旧描点patch批次跳过);缓存,F4新保存后按目录名热重载。方法名保留以免动调用点。"""
        try:
            bd = self._latest_whole_batch()
            if not bd:
                return getattr(self, "_vote_tpls", []) or []
            if getattr(self, "_vote_sig", None) == bd and getattr(self, "_vote_tpls", None):
                return self._vote_tpls
            fs = json.load(open(os.path.join(bd, "char_feature_set.json"), encoding="utf-8"))
            sc = self.WHOLE_MATCH_SCALE
            tpls = []
            for e in fs.get("templates", []):
                im = cv2.imdecode(np.fromfile(os.path.join(bd, e["file"]), dtype=np.uint8),
                                  cv2.IMREAD_COLOR)  # imdecode兼容中文路径
                if im is None or im.shape[0] < 8 or im.shape[1] < 8:
                    continue
                th0, tw0 = im.shape[:2]
                g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)                    # 形状(灰度)
                hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
                col = cv2.merge([hsv[:, :, 0], hsv[:, :, 1]])              # 颜色=H色相+S饱和(丢V明度→抗受击明暗)
                gh = cv2.resize(g, (max(1, int(tw0*sc)), max(1, int(th0*sc))))
                ch = cv2.resize(col, (max(1, int(tw0*sc)), max(1, int(th0*sc))))
                tpls.append((gh, ch, int(e["ax"]), int(e["ay"]), int(th0), int(tw0)))
            self._vote_sig, self._vote_tpls = bd, tpls
            print("[人物整框] 载入 %s 模板%d张" % (os.path.basename(bd), len(tpls)))
            _debug_log("[人物整框] 载入 %s 模板%d张(整框竞争/颜色0.7形状0.3/缩半)" % (os.path.basename(bd), len(tpls)))
            return tpls
        except Exception:
            import traceback; _debug_log("[人物整框] 载入异常: %s" % traceback.format_exc())
            return getattr(self, "_vote_tpls", []) or []

    def _vote_match_character(self, frame, center, coarse=False):
        """整框特征组定脚(用户定稿:多整框模板竞争,颜色0.7+形状0.3取综合分最高一张,≥WHOLE_THR才采信)。
        两段式:track(coarse=False)以上一脚为中心开小窗+相邻帧位移门限(最快最稳);
        coarse以小地图光点换算的屏幕大位置为中心开较大窗、不卡位移门限(光点有镜头惯性误差)。
        每张模板自带脚下基点(ax,ay):模板最佳匹配左上角+基点=脚。返回(foot_x,foot_y,conf)或None。"""
        tpls = self._load_char_vote_set()
        def _diag(reason, extra=""):
            _tn = time.time()
            if _tn - getattr(self, "_vote_diag_t", 0) > 0.6:
                self._vote_diag_t = _tn
                _debug_log("[整框诊断] %s tpls=%d 中心=%s 粗位=%d %s" % (
                    reason, len(tpls), "有" if center else "无", 1 if coarse else 0, extra))
        if not tpls:
            _diag("无整框模板(先F4采集)"); return None
        if frame is None or center is None:
            return None
        fh, fw = frame.shape[:2]; cx, cy = center
        # 1) 所有模板相对"脚基点"的最大外延(原尺度):保证脚=center时整张人都落在搜索区内
        L = max(t[2] for t in tpls)
        R = max(t[5] - t[2] for t in tpls)
        U = max(t[3] for t in tpls)
        D = max(t[4] - t[3] for t in tpls)
        if coarse:
            mx, mu, md = self.WHOLE_COARSE_MX, self.WHOLE_COARSE_MU, self.WHOLE_COARSE_MD
        else:
            mx, mu, md = self.WHOLE_TRACK_MX, self.WHOLE_TRACK_MU, self.WHOLE_TRACK_MD
        rx1 = int(max(0, cx - L - mx)); rx2 = int(min(fw, cx + R + mx))
        ry1 = int(max(0, cy - U - mu)); ry2 = int(min(fh, cy + D + md))
        src = frame[ry1:ry2, rx1:rx2]
        if src.shape[0] < 20 or src.shape[1] < 20:
            _diag("搜索区过小"); return None
        sc = self.WHOLE_MATCH_SCALE
        sg = cv2.resize(cv2.cvtColor(src, cv2.COLOR_BGR2GRAY),
                        (max(1, int(src.shape[1]*sc)), max(1, int(src.shape[0]*sc))))
        _hsv = cv2.cvtColor(src, cv2.COLOR_BGR2HSV)
        sco = cv2.resize(cv2.merge([_hsv[:, :, 0], _hsv[:, :, 1]]), (sg.shape[1], sg.shape[0]))
        wc, wsh, thr = self.WHOLE_W_COLOR, self.WHOLE_W_SHAPE, self.WHOLE_THR
        # 2) 逐模板在缩半搜索区找各自最佳,全局取综合分最高一张(整框大图竞争,背景凑不出整张人)
        best_v, best_t, best_lx, best_ly = -2.0, None, 0, 0
        for gh, ch, ax, ay, th0, tw0 in tpls:
            th, tw = gh.shape[:2]
            if th > sg.shape[0] or tw > sg.shape[1]:
                continue  # 模板比搜索区还大(移动过快/粗位窗也没罩住),跳过,靠下帧或上层兜底
            r_sh = cv2.matchTemplate(sg, gh, cv2.TM_CCOEFF_NORMED)    # 形状分
            r_co = cv2.matchTemplate(sco, ch, cv2.TM_CCOEFF_NORMED)   # 颜色分
            r = wc*r_co + wsh*r_sh                                    # 综合:颜色为主、形状为辅
            _, mv, _, ml = cv2.minMaxLoc(r)
            if mv > best_v:
                best_v, best_t, best_lx, best_ly = float(mv), (gh, ch, ax, ay, th0, tw0), ml[0], ml[1]
        if best_t is None or best_v < thr:
            _diag("综合分不足", "最高%.3f(门限%.2f)" % (best_v, thr)); return None
        gh, ch, ax, ay, th0, tw0 = best_t
        # 3) 缩半loc→原尺度模板左上→加该模板基点=脚
        top_x = rx1 + best_lx/sc
        top_y = ry1 + best_ly/sc
        fx = int(round(top_x + ax))
        fy = int(round(top_y + ay))
        if not coarse and np.hypot(fx-cx, fy-cy) > self.WHOLE_MAX_MOVE:
            _diag("小窗位移超门限", "候选脚(%d,%d)离上一脚%.0f" % (
                fx, fy, np.hypot(fx-cx, fy-cy)))
            return None  # 跟踪小窗没跟上→上层_get_player_screen_pos自动转光点粗位大窗重捕
        if coarse:
            _debug_log("[人物整框] 光点粗位首捕 脚(%d,%d) 综合%.3f" % (fx, fy, best_v))
        return fx, fy, float(best_v)

    def _get_player_screen_pos(self, frame):
        """人物坐标·多锚点局部跟踪(2026-09-13;输出格式不变:脚点(x,y)/从未定位None)。
        实际参与定位的锚点=角色名name+面部face_r+后脑back(_match_keys);人名第一,人名丢了脸/后脑分高者兜底
        (宠物pet1/2/3按用户定稿不参与定位,只在管理窗显示识别率)。以上一锚点为中心开 rx×ry 局部窗快跟,搜索区在比对前
        几何扣除黑名单(_role_sub_rects,模板不扫黑名单);连续faststep帧失配或距上次全图>research(ms)就全图重搜;
        局部窗相邻帧跳变>maxmove且弱匹配(<0.75)才丢弃(≥0.75强匹配=合法瞬移、全图重搜也不限跳变);面部原图/镜像谁高定朝向。
        人物匹配频率受fps节流(A线程,上梯高帧豁免);丢失先保持上一可信点、连续hold个跟踪节拍没找回才清空(保持秒数≈hold/fps)。
        边缘自救靠_char_match_ok/_char_lost_edge,下游零改。人物坐标=锚点中心(不做到脚补偿,单平台只看X、跨平台走引导线)。"""
        tr = getattr(self, '_role_track', None)
        if tr is None:
            tr = {"last": None, "foot": None, "miss": 0, "last_full": 0.0, "face": None, "score": 0.0}
            self._role_track = tr
        if frame is None:
            return tr["foot"]
        # 一个已采锚点都没有→新链无数据(测试期不再回退旧整框链),返回最后点/None
        if not any(self._role_has_anchor(_k) for _k in ROLE_ANCHOR_KEYS):
            self._char_match_ok = False
            return tr["foot"]
        P = self._role_rec.get("params", ROLE_TRACK_DEFAULT) if self._role_rec else ROLE_TRACK_DEFAULT
        thr = float(P.get("thr", 0.62)); rx = int(P.get("rx", 180)); ry = int(P.get("ry", 120))
        maxmove = int(P.get("maxmove", 48)); faststep = int(P.get("faststep", 2)); research = float(P.get("research", 1500))
        hold = int(P.get("hold", 90))  # 丢失保持(识别节拍数):丢了先沿用上一可信点,超过hold拍仍没找回才清空
        now = time.time() * 1000
        last = tr["last"]
        # 失配时miss每帧+1、≥faststep就全图=几乎每帧全图(脸还镜像=每帧4次全图匹配),吃满CPU/GIL把主循环绘制拖到
        # 400ms、帧率掉到10~15、动作中更抓不到锚点=死循环。给"miss触发的全图"加350ms最小间隔,期间只跑便宜局部窗,把帧率让回来。
        _FULL_GAP_MS = 350.0
        need_full = (last is None) or (now - tr["last_full"] > research) \
            or ((tr["miss"] >= faststep) and (now - tr["last_full"] > _FULL_GAP_MS))
        box = None if need_full else (last[0] - rx, last[1] - ry, last[0] + rx, last[1] + ry)
        self._role_search_box = box  # 局部跟踪搜索范围框(全图重搜时=None不画),供蒙板可视化"在哪片区域找锚点"
        # 人名永远第一;其余=冗余兜底(脸/后脑/宠物名1-3),人名丢时谁分高用谁、各带"→人名线"偏移,只显示分高那个。
        # 宠物始终跟人、位置绑定,人名/脸/后脑全被特效挡住时用宠物名兜底定位(用户:采了就要参与定位,不是只在管理窗看分)。
        got = {}
        _AUX = ("face_r", "back", "pet1", "pet2", "pet3")
        _match_keys = ("name",) + _AUX
        for k in _match_keys:
            s, loc, face = self._role_match_in(frame, k, box)
            if loc is not None:
                got[k] = (s, loc, face)
        # 可视化:过阈锚点用其采集多边形、以命中中心为不动点画框。人名过阈就画;脸/后脑只画分高的那个(互斥、只显示一个)
        ameta = self._role_rec.get("anchors", {}) if self._role_rec else {}
        _show_keys = set()
        if got.get("name", (0.0,))[0] >= thr:
            _show_keys.add("name")
        _fbs = [(got[_k][0], _k) for _k in _AUX if _k in got and got[_k][0] >= thr]
        if _fbs:
            _show_keys.add(max(_fbs)[1])  # 脸/后脑/宠物里分高者显示(只显示一个,不杂乱)
        polys = {}
        for _k in _show_keys:
            _s, _loc, _f = got[_k]
            _m = ameta.get(_k)
            if not _m:
                continue
            _w, _h, _pp = int(_m.get("w", 0)), int(_m.get("h", 0)), _m.get("poly")
            if _w <= 0 or _h <= 0 or not _pp:
                continue
            _cx, _cy = _loc  # loc=多边形质心;外接png左上角=质心-pivot,多边形才准确画在命中原位(显示不挪)
            _pxo, _pyo = self._role_anchor_pivot(_k, _w, _h)
            _tlx, _tly = _cx - _pxo, _cy - _pyo
            _g = [(_tlx + int(dx), _tly + int(dy)) for dx, dy in _pp]  # 采集原尺寸、原位显示
            polys[_k] = (_g, float(_s))
        self._role_anchor_polys = polys
        # 最新一帧各锚点分数/位置/朝向存出来,供「角色识别」管理窗直接显示(管理窗不再自己抓帧全图匹配,避免拖动/关窗时重活交错闪退、也省CPU)
        self._role_last_scores = got
        if time.time() - getattr(self, '_role_diag_t', 0) > 0.5:  # 0.5s一次分数诊断,看谁稳谁飘
            self._role_diag_t = time.time()
            _debug_log("[角色跟踪] 模式=%s last=%s 分数[%s]" % (
                "全图" if need_full else "局部", last,
                " ".join("%s=%.2f" % (kk, got[kk][0]) for kk in got) or "无命中"))
        # 定位仲裁:人名优先;人名丢了用脸/后脑里分高者兜底(谁分高谁更可能是真角色),不让定位框丢
        _nv = got.get("name")
        if _nv is not None and _nv[0] >= thr:
            _cand = [("name", _nv)]
        else:
            # 人名丢→脸/后脑/宠物名里谁过阈且分最高谁兜底(宠物是最后一道,人名脸后脑都没时顶上)
            _cand = sorted(((kk, got[kk]) for kk in _AUX if kk in got and got[kk][0] >= thr),
                           key=lambda kv: -kv[1][0])
        # 人名在时学习"各兜底锚点中心→人名中心"偏移(EMA平滑);人名丢、用脸/后脑/宠物定位时把命中点加该偏移映射回人名那条线,
        # 于是所有源的【实际基点】统一在人名位置、打怪不上下跳;但各锚点橙框仍画在命中原位(显示不动)。
        # 人名在时只给脸/后脑学"→人名中心"偏移(EMA);宠物在人左右位置不固定、无法学固定偏移,故宠物不偏移、兜底时直接用其命中点
        _nloc = _nv[1] if (_nv is not None and _nv[0] >= thr) else None
        for _kk in ("face_r", "back"):
            if _nloc is not None and _kk in got and got[_kk][0] >= thr:
                _dx, _dy = _nloc[0] - got[_kk][1][0], _nloc[1] - got[_kk][1][1]
                _o = tr.get("off_" + _kk)
                if _o is None:
                    tr["off_" + _kk] = [float(_dx), float(_dy)]
                else:  # EMA平滑,避免单帧抖动让基点飘
                    _o[0] = _o[0] * 0.7 + _dx * 0.3; _o[1] = _o[1] * 0.7 + _dy * 0.3
        _pick = None
        for _pk, _pv in _cand:
            _ploc = _pv[1]
            if _pk == "name" or str(_pk).startswith("pet"):  # 人名直接用;宠物不偏移(在人左右不固定)、直接用命中点托底,保证定位大框不丢
                _bx, _by = float(_ploc[0]), float(_ploc[1])
            else:  # 脸/后脑:实际基点偏移到人名位置;刚启动还没和人名同帧学到偏移时才暂用自身点
                _o = tr.get("off_" + _pk)
                _bx, _by = (_ploc[0] + _o[0], _ploc[1] + _o[1]) if _o else (float(_ploc[0]), float(_ploc[1]))
            # 局部窗内离上一基点跳变>maxmove:弱匹配(<0.75)当误匹配丢弃;≥0.75强匹配=合法瞬移直接采信(背景假分到不了0.75)
            if last is not None and not need_full \
                    and np.hypot(_bx - last[0], _by - last[1]) > maxmove and _pv[0] < 0.75:
                continue
            _pick = (_pk, _pv, _bx, _by); break
        if _pick is not None:
            _pk, (ps, _srcloc, _pf0), axf, ayf = _pick
            ax, ay = int(round(axf)), int(round(ayf))  # 实际基点(三源已统一到人名那条线)
            tr["last"] = (ax, ay)
            tr["foot"] = (ax, ay)  # 单平台只看X,不做到脚补偿
            tr["miss"] = 0; tr["score"] = ps
            if need_full:
                tr["last_full"] = now
            _fv = got.get("face_r")  # 朝向优先由面部锚点判;面部没中就保持上一次朝向、不乱翻
            if _fv is not None and _fv[0] >= thr:
                tr["face"] = _fv[2]
            self._role_face = tr["face"]
            self._role_pos_src = _pk  # 当前定位源name/face_r/back(诊断用)
            self._last_char_match_pos = tr["foot"]; self._last_char_match_time = now
            self._char_match_ok = True; self._char_lost_edge = None
            return tr["foot"]
        # 没定出:失配计数,全图没找到也重置全图计时(避免每帧全图);停在最后脚点继续等重搜
        tr["miss"] += 1
        if need_full:
            tr["last_full"] = now
        self._char_match_ok = False
        fp = tr["foot"]
        self._char_lost_edge = None
        if fp is not None and tr["miss"] > hold:  # 丢失保持到期:连续hold个识别节拍没找回→清空旧点,不再死停(后台仍全图重搜,搜到自动恢复)
            tr["foot"] = None; fp = None
        if fp is not None:
            _fw = frame.shape[1]
            if fp[0] <= CHAR_EDGE_MARGIN:
                self._char_lost_edge = 'left'
            elif fp[0] >= _fw - CHAR_EDGE_MARGIN:
                self._char_lost_edge = 'right'
            return fp
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

    def _clear_locked_ladder(self, why=''):
        """解绑锁定梯(登顶/上梯失败/近身怪三步走/硬重置时调用):解绑后回主线重新识怪锁怪,下次跨层再由当前怪选梯。"""
        if getattr(self, '_locked_ladder', None) is not None:
            _debug_log("[锁定梯] 解绑(原因=%s)" % (why or '?'))
        self._locked_ladder = None

    def _is_lock_frozen(self):
        """锁怪冻结硬信号(用户2026-09-09定稿)：以"我们自己的抓梯/垂直动作阶段"为唯一判据,不靠画面Y/X(镜头会滚、对齐会抖)。
        ·to_ladder平地走向梯子、还没跳=不冻,身边有更该打的怪允许换(换了重新选梯)；
        ·一旦跳起来进入抓梯流程(post_jump)、或已在climbing爬梯/jump_down下跳/teleport瞬移=锁死,
         一直到到顶/到底_reset_lock_after_arrival才解冻重识别。信号只有冻/不冻两种,明确稳定。
        【用户2026-09-11定稿·跨层怪=范围外怪,分两档】平地走向梯子/走台子(还没起跳,_climb_state=none/to_ladder未post_jump)
        =软冻结:锚点坐标固定保存不丢,但套用"范围外锁定"规则——技能范围内刷出能直打的本层怪允许解绑回主线先打(三步走在移动权
        裁决处做);一旦起跳抓梯(post_jump)/climbing/jump_down/teleport/descend=硬冻结,近身怪也不换,一心到登顶/失败。
        故这里【不能】再因_combat_transit=True就硬冻(transit走平地去梯时也是True,那会让近身怪打不了、和用户最新规则冲突);
        硬冻只认"自己的垂直爬梯动作阶段"。掉台归位的爬梯同理按_climb_state判。"""
        cs = getattr(self, '_climb_state', 'none')
        if cs in ('climbing', 'jump_down', 'jump_up', 'teleport', 'descend'):
            return True
        if cs == 'to_ladder' and getattr(self, '_ladder_jump_phase', None) in ('post_jump', 'realign'):
            return True
        return False

    def _set_combat_move(self, direction, allow_in_transit=False):
        """设置持续移动方向，direction='left'/'right'/None。流畅切换不卡顿。
        allow_in_transit=True=跨层transit自身走路(走台子路径点)调用,放行；默认False=战斗追怪/待机/回退调用。
        【根因收口·用户2026-09-09】跨层去梯/走台进行中(_combat_transit)默认一律挡下战斗侧水平移动并松战斗左右键：
        水平移动权唯一归transit(_transit_step/_move_to),否则cross帧去梯按右、pursue帧追别的层怪按左,两套水平键
        高速相抵=人物被钉在原地空卡(真机卡约50秒的根因)。真要停下来打怪时,上层会先把_combat_transit清False再走到这,不受挡。"""
        if not allow_in_transit and getattr(self, '_combat_transit', False):
            self._release_combat_key(VK_LEFT)
            self._release_combat_key(VK_RIGHT)
            self._combat_move_dir = None
            return
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
            # X方向相对上一段发生换向=记一次翻转(第二层横跳探测用),只留最近2倍观察窗,防列表无限增长
            if axis == 'x' and it is not None and bx is not None:
                self._wd_x_flips.append((now, bx))
                self._wd_x_flips = [f for f in self._wd_x_flips if now - f[0] <= AJ_WIN_MS * 2]
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
            # 【测试期·用户2026-09-10】左右两套方向键互搏=两个脑子抢键冲突(也是"平地上该走却呆住不走"的线程根因)。
            # 测试期不做"选一方继续"的软仲裁、不计数等待:看门狗一见到冲突就当场硬重置(即时松全部键+主线帧首清零重来),
            # 每次冲突都立刻解决/暴露。地形单向被挡不会左右互搏,故不在此(靠录制绿线6px跑跳)。重置冷却内不重复发。
            self._request_hard_reset(
                "左右方向键互搏冲突(战斗L%d/R%d 巡路L%d/R%d),冲突即硬重置,全部停止重新决策" % (cl, cr, rl, rr))
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
        mmp = getattr(self, '_player_map_pos', None)
        in_gate = now < self._wd_jump_gate_until
        # 原地左右横跳探测不依赖当前intent(换向间隙intent可能已clear),独立先判,置拉回令交主线consume
        self._wd_check_antijitter(now, mmp, in_gate)
        if not intents:
            return  # 无移动意图不做背景帧差(省CPU)
        # 跳后静默窗内不截背景(基准帧停在跳前地面);否则算上/右两块几块在动
        bg_count = 0 if in_gate else self._wd_bg_motion_count(getattr(self, '_raw_frame', None))
        _req_t0 = self._hard_reset_req['t'] if self._hard_reset_req else 0
        for axis, it in intents.items():
            self._wd_check_axis(axis, it, mmp, bg_count, in_gate, now)
        # 锁外即时停手:_wd_check_axis持锁段只能置令(锁不可重入),这里在同一轮、锁外检测本轮是否新发硬重置令,
        # 若新发则幂等松全部键让人物当刻停下(不等主线帧首),满足"监管实时反应、不慢几拍"
        _req = self._hard_reset_req
        if _req and _req.get('t', 0) > _req_t0:
            self._wd_immediate_release(_req.get('reason', ''))

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
                # 真在动=移动有效,清空监管兜底的连续停滞计数(用户2026-09-09)
                self._wd_recover_cnt = 0
                self._wd_recover_seg = None
            else:
                if not cur.get('reported'):
                    self._wd_log(
                        'wd_%s_stall' % axis,
                        "%s停滞:朝%s%.0fms 背景同动%d块/光点段差%s,采样%d真实运动%d次<%d,疑似没动[观察]" % (
                            'X' if axis == 'x' else 'Y', dn, win, bg_count,
                            ('%.1f' % dseg) if dseg is not None else 'NA', n, hits, WD_SEG_MIN_HITS))
                # 用户2026-09-10定稿:X轴"单向走却没动"不在此硬重置。它分两种、各有正路:
                # ①被地形/台阶挡(只按一个方向、无按键互搏)→靠录制绿线波动6px跑跳 + 卡住1.5s跳脱困,不重置;
                # ②线程/两套逻辑抢键冲突→必表现为左右两套键互搏,由_wd_audit_keys冲突检测识别、持续压不住才硬重置。
                # 即看门狗硬重置只认"按键互搏冲突",不按平地/跨层、也不按单向停滞来重置。
                cur.update(seg_t=now, seg_n=0, seg_hits=0, reported=True, seg_x=nx, seg_y=ny)

    def _wd_check_antijitter(self, now, mmp, in_gate):
        """第二层监管·原地左右横跳探测(线程侧,只置令不发键)。最近AJ_WIN_MS内X换向≥AJ_FLIP_MIN次、
        且小地图光点净位移<AJ_NET_MAP_DX=方向来回摆、人却没挪窝(锁怪在左右怪间横跳/两个脑子抢方向)。
        跳后1秒(in_gate)不判;置令冷却AJ_TRIG_COOLDOWN;真正松键/锁侧/重置由主线_consume_anti_jitter执行。"""
        if in_gate or mmp is None:
            return
        with self._wd_lock:
            self._wd_x_flips[:] = [f for f in self._wd_x_flips if now - f[0] <= AJ_WIN_MS]
            n = len(self._wd_x_flips)
            net = abs(mmp[0] - self._wd_x_flips[0][1]) if self._wd_x_flips else 0
        if n < AJ_FLIP_MIN or net >= AJ_NET_MAP_DX:
            return
        if now - getattr(self, '_wd_aj_last_req', 0) < AJ_TRIG_COOLDOWN:
            return
        self._wd_aj_last_req = now
        with self._wd_lock:
            self._wd_antijitter_req = {'t': now, 'n': n, 'net': net}
        self._wd_log('wd_antijitter',
                     "原地左右横跳:%.1fs内换向%d次、光点净位移仅%.1f<%d,请求拉回正轨" % (
                         AJ_WIN_MS / 1000.0, n, net, AJ_NET_MAP_DX), color=(0, 0, 255))

    def _global_stall_watchdog(self, now):
        """全局2秒总兜底(用户2026-09-10:任何卡住/不动/异常都不许存在超过2秒,到点全部清零重新开始)。主线内每帧调,不另起线程。
        判据:【有任务在身】(画面有怪/有锁定/在跨层/在爬梯)却连续GLOBAL_STALL_MS无任一"进展心跳"→总复位;纯空闲(无怪无任务)站着等刷怪不算故障。
        进展心跳(任一):①屏幕基点移动≥6 ②小地图光点移动≥2 ③最近2秒放过技能(站桩输出) ④怪比段起点少(打死了)
        ⑤豁免的正常长动作(确实在爬/下跳/起跳空中/独占解卡/平台回退——自带完成与超时判据,不被2秒打断)。"""
        if not self._running:
            return False
        if not ENABLE_GLOBAL_STALL_FALLBACK:
            return False   # 全局总兜底总开关关闭(用户2026-09-10:先关、只关不删,正式用改ENABLE_GLOBAL_STALL_FALLBACK=True恢复);函数本体完整保留
        if now < getattr(self, '_gsr_cooldown', 0):
            self._gsr_hb = now
            self._gsr_sp = self._player_screen_pos
            self._gsr_mp = self._player_map_pos
            self._gsr_nmon = len(self._monsters or [])
            return False
        cs = getattr(self, '_climb_state', 'none')
        has_job = bool(self._monsters) or self._combat_locked_target is not None \
            or getattr(self, '_combat_transit', False) or cs != 'none'
        exempt = (
            (cs == 'climbing' and getattr(self, '_climb_move_confirmed', False)) or  # 确实在爬(另有12s总超时兜底)
            cs == 'descend' or
            getattr(self, '_ladder_jump_phase', None) == 'post_jump' or              # 起跳抓梯空中
            getattr(self, '_unblock_state', None) is not None or                     # 独占解卡中
            getattr(self, '_platform_retreat_active', False)                          # 平台边界回退中
        )
        sp = self._player_screen_pos
        mp = self._player_map_pos
        if not hasattr(self, '_gsr_hb'):
            self._gsr_hb = now
            self._gsr_sp, self._gsr_mp = sp, mp
            self._gsr_nmon = len(self._monsters or [])
        moved = bool(sp is not None and self._gsr_sp is not None and
                     (abs(sp[0] - self._gsr_sp[0]) + abs(sp[1] - self._gsr_sp[1])) >= GLOBAL_MOVE_PX)
        mapmoved = bool(mp is not None and self._gsr_mp is not None and
                        (abs(mp[0] - self._gsr_mp[0]) + abs(mp[1] - self._gsr_mp[1])) >= GLOBAL_MAP_D)
        _last_atk = max(self._attack_last.values()) if self._attack_last else 0
        casting = (now - _last_atk) < GLOBAL_SKILL_HB_MS
        killed = len(self._monsters or []) < self._gsr_nmon
        if exempt or moved or mapmoved or casting or killed or not has_job:
            self._gsr_hb = now
            self._gsr_sp, self._gsr_mp = sp, mp
            self._gsr_nmon = len(self._monsters or [])
            return False
        if now - self._gsr_hb >= GLOBAL_STALL_MS:
            return self._global_stall_reset(now, cs)
        return False

    def _global_stall_reset(self, now, cs, reason=''):
        """2秒全局自动兜底入口(主线内每帧判,总开关ENABLE_GLOBAL_STALL_FALLBACK)；统一走_hard_reset_state单一清零出口。"""
        _msg = reason or ("全局兜底:有动作却%.0f秒无移动/输出/推进(cs=%s,怪%d),全部清零重新开始" % (
                         GLOBAL_STALL_MS / 1000.0, cs, len(self._monsters or [])))
        return self._hard_reset_state(now, _msg)

    def _mark_hard_reset_locked(self, reason, now=None):
        """【调用方必须已持有_wd_lock】冷却判断+置硬重置令,不在此松键(_release_all_keys会经_wd_sync_from_keys
        重入本把不可重入锁→监管线程自死锁、主线抢锁即UI卡死,2026-09-09教训)。返回True=本轮新发令。"""
        now = now if now is not None else time.time() * 1000
        if now - self._hard_reset_last_t < GLOBAL_RESET_COOLDOWN_MS:
            return False
        self._hard_reset_last_t = now
        self._hard_reset_req = {'reason': reason, 't': now}
        return True

    def _wd_immediate_release(self, reason):
        """【锁外调用】监管线程发现卡死当刻幂等松全部键立即停手(不等主线串行跑完);keyup幂等、键没按也无害。"""
        try:
            self._release_all_keys()
            self._release_combat_move()
            self._release_attack_key()
        except Exception as e:
            _debug_log("[监管线] 硬重置即时停手异常:%s" % e)
        self._wd_log('wd_hard_reset_req', "监管线即时停手并请求硬重置: " + reason, color=(0, 0, 255))

    def _request_hard_reset(self, reason):
        """【锁外通用入口】非持锁场景发硬重置令:加锁置令,再在锁外即时停手。"""
        now = time.time() * 1000
        with self._wd_lock:
            fired = self._mark_hard_reset_locked(reason, now)
        if fired:
            self._wd_immediate_release(reason)
        return fired

    def _consume_hard_reset(self):
        """【主线帧首·最高优先级】取走监管线程硬重置令并执行统一清零。返回True=本帧应跳过旧的random/combat决策,下一帧从识别重来。"""
        with self._wd_lock:
            req = self._hard_reset_req
            self._hard_reset_req = None
        if not req:
            return False
        return self._hard_reset_state(time.time() * 1000, req.get('reason', '监管线硬重置'))

    def _consume_anti_jitter(self, now):
        """【主线帧首】消费第二层监管的横跳拉回令(线程只置令、发键在主线)。
        A级=锁定净一侧AJ_HOLD_MS(只在这侧选怪/移动,方向唯一不再左右摆);A级后AJ_ESCALATE_MS内又横跳→B级=完整硬清零重来。
        返回True=本帧已拉回(调用方跳过旧决策)。无令时只负责让到期的锁侧态解除。"""
        with self._wd_lock:
            req = self._wd_antijitter_req
            self._wd_antijitter_req = None
        if not req:
            _hs = self._aj_hold_side
            if _hs and now >= _hs['until']:
                self._aj_hold_side = None
            return False
        # A→B升级:距上次拉回很近且已来过A级=A级没压住
        if 0 < now - self._aj_last_trigger_t < AJ_ESCALATE_MS and self._aj_stage >= 1:
            self._aj_stage = 2
        else:
            self._aj_stage = 1
        self._aj_last_trigger_t = now
        if self._aj_stage >= 2:
            self._aj_hold_side = None
            self._wd_log('aj_B', "横跳A级未压住,升级B级硬清零重新决策", color=(0, 0, 255))
            return self._hard_reset_state(now, "原地左右横跳·B级硬重置")
        # A级:定净方向=优先当前锁定怪相对人物的方向,没有则默认向右(下帧锁侧过滤会自然校正)
        _sp = getattr(self, '_player_screen_pos', None)
        _lk = self._combat_locked_target
        _d = 1
        if _lk and _sp:
            _d = 1 if _lk[0] >= _sp[0] else -1
        try:
            self._release_attack_key()
        except Exception:
            pass
        self._release_combat_move()
        for _vk in (VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN):
            if _vk in self._random_move_keys:
                self._key_up(_vk)
        self._aj_hold_side = {'dir': _d, 'until': now + AJ_HOLD_MS}
        self._wd_log('aj_A', "横跳拉回A:锁定%s侧%.0fms,只在这侧选怪/移动" % (
            '右' if _d > 0 else '左', AJ_HOLD_MS), color=(0, 0, 255))
        return True

    def _hard_reset_state(self, now, reason):
        """【唯一硬清零出口·跨三个线程域】用户2026-09-10:任何卡死/两套拉扯,不管之前在做什么、做没做完,全部停止、从"识别→锁怪→巡路→打怪"干净重来。
        ①主线决策域:松全部键+爬梯/跨层/锁怪/战斗/跳阶段状态全归零;
        ②检测线程域:版本号+1令检测线程在自己循环顶部自清跨帧怪表缓存(它正在迭代的list由它自己清,避免跨线程改迭代对象),
          主线侧同时原子清空已发布怪表与检测节流,保证重置后不被1.5~2秒前的时序平滑/2秒宽限旧怪带偏;
        ③监管自身域:清移动意图/未消费请求/续跑计数/仲裁滞回,以及空怪/压制侧/静止投票等旧偏见,防刚复位又被残留请求二次触发。返回True。"""
        self._gsr_cooldown = now + GLOBAL_RESET_COOLDOWN_MS
        self._gsr_hb = now
        self._wd_log('gsr_reset', reason, color=(0, 0, 255))
        try:
            # ① 主线决策域
            self._release_all_keys()
            self._release_attack_key()
            self._release_combat_move()
            try:
                self._reset_climb()
            except Exception as e:
                _debug_log("[硬重置]_reset_climb异常:%s" % e)
            self._combat_transit = False
            self._transit_target = None
            self._clear_locked_ladder('硬重置')
            self._combat_locked_target = None
            self._combat_active = False
            self._combat_had_target = False
            self._unblock_state = None
            self._platform_retreat_active = False
            self._ladder_jump_phase = None
            self._ladder_post_jump_step = None
            # ② 检测线程域:版本号通知检测线程自清 + 主线侧原子清已发布结果与节流(下轮≤150ms即全量重扫)
            self._detect_reset_seq = getattr(self, '_detect_reset_seq', 0) + 1
            self._yolo_last_t = 0.0
            self._bars_last_t = 0.0
            if hasattr(self, '_feat_last_t'):
                self._feat_last_t = 0.0
            self._raw_monsters = []
            self._raw_hp_bars = []
            self._monsters = []
            # ③ 监管自身域 + 选怪旧偏见
            with self._wd_lock:
                self._mv_intent.clear()
                self._wd_stall_req = None
            self._wd_recover_cnt = 0
            self._wd_recover_seg = None
            # 战斗瞬移生效校验状态一并清零,避免重置后被旧的待校验/失败禁用误伤
            self._combat_tp_pending = None
            self._combat_tp_fail_key = None
            self._combat_tp_fail_cnt = 0
            self._combat_tp_block_until = 0
            # 横跳拉回状态/未消费令一并清,防重置后被旧锁侧/旧拉回令二次触发
            self._wd_antijitter_req = None
            self._wd_x_flips = []
            self._aj_hold_side = None
            self._aj_stage = 0
            self._combat_dropped_phantoms = []
            self._combat_suppress_side = None
            self._monster_static_track = {}
            self._gsr_sp = self._player_screen_pos
            self._gsr_mp = self._player_map_pos
            self._gsr_nmon = len(self._monsters or [])
        except Exception as e:
            _debug_log("[硬重置]复位异常:%s" % e)
        return True

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

    # ==================== 打怪区域·边界守护独立线程(用户2026-09-11定稿) ====================
    def _bound_guard_loop(self):
        """独立线程:每BOUND_POLL_MS用小地图黄光点对照左右两条竖线判X越线,只发令、绝不直接发物理键
        (物理方向键统一由主线消费,避免两个脑子抢键=碎步病根;Y上下限是发起动作处的同步平台闸门,不在本线程)。全程try自保护,绝不崩主线。"""
        while self._bound_running:
            try:
                if getattr(self, '_running', False) or getattr(self, '_random_running', False):
                    self._bound_check_once()
            except Exception as e:
                try:
                    _debug_log("[打怪区域] 守护循环异常: %s" % e)
                except Exception:
                    pass
            time.sleep(self._perf_val('bound_poll_ms') / 1000.0)  # 边界守护轮询按CPU性能档(快50/普通60/慢90ms)

    def _bound_check_once(self):
        # 编辑态(正在拖线/选线)不守护。光点直接用主循环每帧算好、倍率校准也在用的现成 self._player_map_pos
        # (用户2026-09-11:不另裁帧/不另搞识别,照搬成熟光点;它和左右竖线同属小地图块坐标,线在哪就拿光点x直接比)。
        # Y上下限已改为"认平台绿线身份"的同步闸门(_bound_block_up/down在发起动作处即时判),守护线程只管左右越线。
        if getattr(self, '_bound_edit', False):
            return
        dot = getattr(self, '_player_map_pos', None)
        if not dot:
            return
        cx, cy = int(dot[0]), int(dot[1])
        lines = self._get_bound_lines()
        l, r = lines['l'], lines['r']
        # 左右越线令(用户2026-09-11定稿·极简):只在当前没在拉回(gs=None)时检测,光点碰到/越过竖线即置令;
        # 一旦置令就交给主线硬压固定1000~1500ms,压完由_pull_tick清令再重新判——中途不翻转、不滞回,从根上消灭碎步。
        if self._bound_guard_side is None:
            if cx <= l:
                self._bound_guard_side = 'left'
            elif cx >= r:
                self._bound_guard_side = 'right'
        # [临时·光点核对]每1秒打一次"光点vs左右竖线+上下限组",真机验证现成光点是否准(用户2026-09-11"先测试光点");验证OK可删
        _tn = time.time()
        if _tn - getattr(self, '_bound_dot_diag_t', 0) >= 1.0:
            self._bound_dot_diag_t = _tn
            _debug_log("[打怪区域] 光点=(%d,%d) 竖线l=%d r=%d side=%s 上限组=%s 下限组=%s"
                       % (cx, cy, l, r, self._bound_guard_side, self._bound_top_grp, self._bound_bot_grp))

    def _start_bound_guard(self):
        if self._bound_thread and self._bound_thread.is_alive():
            return
        self._bound_running = True
        self._bound_thread = threading.Thread(target=self._bound_guard_loop, daemon=True)
        self._bound_thread.start()
        _debug_log("[打怪区域] 边界守护线程已启动")

    def _stop_bound_guard(self):
        self._bound_running = False
        if self._bound_thread and self._bound_thread.is_alive():
            self._bound_thread.join(timeout=1.0)
        self._bound_thread = None
        self._bound_guard_side = None
        self._bound_pull = None
        try:
            self._release_combat_move()   # 停守护时松开拉回按住的朝内方向键,不留键
        except Exception:
            pass

    def _bound_blocked_vertical(self, direction):
        """Y上下闸门(用户2026-09-11改认平台绿线):direction='up'且人正站在选定上限平台=禁再向上返回True;
        'down'且人站在选定下限平台=禁向下。未选该向上下限/编辑态/判不到当前台=放行(详见_bound_block_up/down)。"""
        if direction == 'up':
            return self._bound_block_up()
        if direction == 'down':
            return self._bound_block_down()
        return False

    def _bound_pull_tick(self, now):
        """打怪区域·左右越线硬拉回(用户2026-09-11定稿时序,百分百照做):
        ①停主线(返回True占_aux_busy,打怪/巡路暂停) ②左右方向键+攻击键全松、清场BOUND_RELEASE_MS
        ③硬压朝内方向键1000~1500ms随机、一口气拉回中间(中途不重判/不翻转=不碎步) ④到点立马松键、恢复主线。
        爬梯/跨层冻结中不水平拉回(梯子上水平无意义)。物理键只在主线发,守护线程只置令。"""
        side = self._bound_guard_side
        if side is None or self._is_lock_frozen() or getattr(self, '_climb_state', 'none') != 'none':
            return False
        pull = self._bound_pull
        # 阶段0·刚越线:停主线,只把攻击键+战斗套/巡路套左右键全松开,先不压(松/压分开,游戏才不吞键、不左右相抵)
        if pull is None:
            inward = 'right' if side == 'left' else 'left'    # 越左竖线朝右回、越右竖线朝左回
            pull = {'dir_side': side, 'dir': inward,
                    'release_until': now + BOUND_RELEASE_MS, 'pull_until': None}
            self._bound_pull = pull
            try:
                self._release_attack_key()
                self._release_combat_move()
                self._key_up(VK_LEFT)
                self._key_up(VK_RIGHT)
            except Exception:
                pass
            _ln = self._get_bound_lines()
            _dx = self._player_map_pos[0] if self._player_map_pos else -1
            _debug_log("[打怪区域] 光点x=%d 越%s线(l=%d r=%d)→停主线、松开左右+攻击键清场%dms"
                       % (_dx, side, _ln['l'], _ln['r'], BOUND_RELEASE_MS))
            return True
        # 清场间隙:键保持全松、不压键(此期间_aux_busy已停主线,没人会重新按)
        if now < pull['release_until']:
            return True
        # 阶段1·清场结束这一帧:才定1000~1500ms随机时长,硬压朝内方向键
        if pull.get('pull_until') is None:
            dur = random.randint(BOUND_PULL_MIN_MS, BOUND_PULL_MAX_MS)
            pull['pull_until'] = now + dur
            self._hold_combat_key(VK_RIGHT if pull['dir'] == 'right' else VK_LEFT)
            self._combat_move_dir = pull['dir']
            _debug_log("[打怪区域] 清场完→硬压朝内(%s)拉回%dms" % (pull['dir'], dur))
        # 阶段2·压键进行中:每帧幂等确保朝内键按住,不重判/不翻转/不看平台边
        if now < pull['pull_until']:
            self._hold_combat_key(VK_RIGHT if pull['dir'] == 'right' else VK_LEFT)
            self._combat_move_dir = pull['dir']
            return True
        # 阶段3·时长走完:立马松朝内键、清拉回令(下一检测窗口重新看光点),恢复主线打怪
        # 同时落一道"朝刚越线侧水平瞬移冷却":防主线一恢复就瞬移闪回边上→再越线→再拉回的死循环(用户2026-09-12)
        self._bound_last_side = side
        self._bound_tp_block_until = now + BOUND_TP_COOLDOWN_MS
        self._bound_pull = None
        self._bound_guard_side = None
        self._release_combat_move()
        return False

    def _bound_hit_line(self, mx, my):
        """小地图块坐标(mx,my)命中哪条左右竖线(仅编辑态):返回'l'/'r'/None,两条都命中取最近。
        UI小地图点选已先换算成块坐标(和平台绿线/梯删除/人物光点同一空间,用户2026-09-11改)。Y上下限改为点绿线,不再有横线。"""
        if not getattr(self, '_bound_edit', False):
            return None
        w, h = self._bound_map_size()
        if not (0 <= mx <= w and 0 <= my <= h):
            return None
        ln = self._get_bound_lines()
        cands = []
        if abs(mx - ln['l']) <= BOUND_DRAG_HIT:
            cands.append((abs(mx - ln['l']), 'l'))
        if abs(mx - ln['r']) <= BOUND_DRAG_HIT:
            cands.append((abs(mx - ln['r']), 'r'))
        if not cands:
            return None
        cands.sort(key=lambda _c: _c[0])
        return cands[0][1]

    def _bound_drag_update(self, mx, my):
        """小地图块坐标平行拖左右竖线:竖线只改x。
        双重边界:先把光标x硬钳在小地图[0,w-1](用户:线不许跑出窗口),再过线间钳制l<r。"""
        which = getattr(self, '_bound_drag', None)
        if which is None:
            return
        w, h = self._bound_map_size()
        mx = max(0, min(int(mx), w - 1))     # 竖线移动硬边界
        ln = self._get_bound_lines()
        if which in ('l', 'r'):
            ln[which] = mx
        self._bound_lines = self._clamp_bound_lines(ln, w, h)

    def _bound_drag_tick(self):
        """打怪区域·左右竖线编辑拖拽(用户2026-09-11:全局ScreenToClient坐标有DPI偏移=点不中/时灵时不灵,
        改用cv2鼠标回调实时记录的客户区坐标——和小地图绘制严格同空间、零偏移;主循环每帧轮询推进,规避MOUSEMOVE丢帧)。
        仅编辑态;左键刚按=点中哪条竖线、按住=左右平行拖、松开=停拖。Y上下限改由_on_mouse点平台绿线选取,不在此拖拽。"""
        if not getattr(self, '_bound_edit', False):
            self._bound_drag = None
            return
        _x = getattr(self, '_ui_mouse_x', None)
        _y = getattr(self, '_ui_mouse_y', None)
        if _x is None or _y is None:
            return
        try:
            left_down = bool(int(getattr(self, '_ui_mouse_flags', 0)) & 0x1)  # cv2.EVENT_FLAG_LBUTTON=1
            # 用小地图"实际贴放矩形"反算(固定UI_MAP_Y=131与实际顶143差12px、显示高还是动态值→横线Y系统性偏上;
            # X因水平居中碰巧≈UI_MAP_X才正常)。_map_disp_*是画线同帧存的真实位置/尺寸,用它=绘制的严格逆运算、零偏移)
            _dx = getattr(self, '_map_disp_x', UI_MAP_X)
            _dy = getattr(self, '_map_disp_y', UI_MAP_Y)
            _dw = getattr(self, '_map_disp_w', UI_MAP_W)
            _dh = getattr(self, '_map_disp_h', UI_MAP_H)
            if not (_dx <= _x < _dx + _dw and _dy <= _y < _dy + _dh):
                if not left_down:
                    self._bound_drag = None
                return
            _mw = getattr(self, '_last_map_w', FIXED_W)
            _mh = getattr(self, '_last_map_h', MAP_H)
            mx = int((_x - _dx) / _dw * _mw)   # 显示坐标→小地图块坐标(scale=_dw/_mw,与画线严格互逆)
            my = int((_y - _dy) / _dh * _mh)
            if left_down and self._bound_drag is None:
                self._bound_drag = self._bound_hit_line(mx, my)   # 刚按下:点中哪条(没中=None不拖)
            elif left_down and self._bound_drag is not None:
                self._bound_drag_update(mx, my)                   # 按住:平行拖(内含硬边界钳制)
            elif (not left_down) and self._bound_drag is not None:
                self._bound_drag = None                           # 松开:停拖
        except Exception as _e:
            _debug_log("[打怪区域] 拖拽tick异常: %s" % _e)

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

    def _check_combat_teleport(self, now, px, py):
        """战斗瞬移生效校验(用户2026-09-11):瞬移发起TP_VERIFY_MS后核对人物是否真朝该轴位移,TP_VERIFY_TIMEOUT仍没动=
        瞬移无效(台子太远/被墙挡/没蓝);同一锁定目标连续TP_FAIL_MAX次无效→TP_BLOCK_MS内对它禁用瞬移,改走路/跳/梯子,
        换目标自动重新计数。只读坐标+置标记,不发键(发键统一在主线动作段)。"""
        pen = self._combat_tp_pending
        if pen is None or px is None or py is None:
            return
        dt = now - pen['t']
        if dt < TP_VERIFY_MS:
            return
        if pen['axis'] == 'x':
            _prog = (px - pen['sx']) * pen['dir']     # 朝预期方向(右x增/左x减)为正
            moved = _prog >= TP_MIN_SCREEN_DX
        else:
            _prog = (py - pen['sy']) * pen['dir']     # 朝下(屏幕y增)/朝上(y减)为正
            moved = _prog >= TP_MIN_SCREEN_DY
        if moved:
            self._combat_tp_pending = None
            self._combat_tp_fail_cnt = 0
            self._combat_tp_fail_key = None
            return
        if dt < TP_VERIFY_TIMEOUT:
            return
        # 到超时仍无朝预期位移=本次瞬移无效
        _key = pen.get('key')
        if self._combat_tp_fail_key == _key:
            self._combat_tp_fail_cnt += 1
        else:
            self._combat_tp_fail_key = _key
            self._combat_tp_fail_cnt = 1
        _axis = '水平' if pen['axis'] == 'x' else '竖直'
        self._combat_tp_pending = None
        if self._combat_tp_fail_cnt >= TP_FAIL_MAX:
            self._combat_tp_block_until = now + TP_BLOCK_MS
            self._wd_log('tp_ineff', "%s瞬移连续%d次无位移=过不去,%.0f秒内对该目标改走路/跳/梯子" % (
                _axis, self._combat_tp_fail_cnt, TP_BLOCK_MS / 1000.0), color=(0, 0, 255))
        else:
            self._wd_log('tp_ineff1', "%s瞬移无位移(第%d次,进度%.0f),可能台距不够/被挡" % (
                _axis, self._combat_tp_fail_cnt, _prog))

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
        self._slope_phase = 'wait_jump'
        self._slope_next_at = 0
        self._slope_high_mode = False
        self._release_combat_move()
        self._release_attack_key()
        _debug_log("[防卡死] 连续移动受阻(%s)，判定目标(%d,%d)打不到→放弃，下帧改锁另一侧最近怪" % (why or "卡住", cx, cy))

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

    def _same_recorded_platform(self, monster_cx, monster_cy):
        """【可靠同层判据·用户2026-09-11】怪与人物是否归属【同一条录制绿线平台】(比平台id,不猜Y差)。
        用于决策分桶破格:同一条录制平台上的怪,哪怕缓坡/透视致Y差超攻击带,也按同层走过去打,不误判cross站桩。
        任一归属判不出(没录平台/屏幕→小地图估算失败)返回False=退回纯Y分桶,绝不臆断把上层怪拉成同层。"""
        try:
            _mpf = self._get_monster_platform(monster_cx, monster_cy)
            _ppf = self._get_current_platform()
            if _mpf is None or _ppf is None:
                return False
            return _mpf.get('id') == _ppf.get('id')
        except Exception:
            return False

    def _reset_lock_after_arrival(self, source=''):
        """到新平台(梯子到顶/走台子到点)后强制重新识别+重新锁定(用户2026-09-09)：
        翻层后镜头变了,跨层前在旧屏幕坐标上的锁定若不清,会错配/沿旧坐标把人往回带(表现=到顶不锁本层怪、反而跑下去)。
        这里清掉旧锁定及其出手/存活状态,并把YOLO/特征/血条节流清零,让下一检测周期立刻在【寻怪范围ROI】内重扫,
        combat_logic按当前画面Y近优先重新锁定。
        【次数控制·用户2026-09-10】ARRIVAL_RESET_COOLDOWN_MS内的重复触发(走台/落地边界抖动、锁远怪→cross→终点在身边
        立刻又判到达的空转)一律忽略:旧逻辑每触发一次就清空整张怪表,清→空站→重锁→又清,锁定在怪群横跳、方向左右切=小碎步。"""
        _now_arr = time.time() * 1000
        if _now_arr - self._last_arrival_reset_t < ARRIVAL_RESET_COOLDOWN_MS:
            _debug_log("[跨层] 到达重扫冷却%.0fms内,忽略重复触发(来源=%s)" % (ARRIVAL_RESET_COOLDOWN_MS, source or '?'))
            return False
        self._last_arrival_reset_t = _now_arr
        self._combat_locked_target = None
        self._combat_last_target_pos = None
        self._clear_locked_ladder('登顶/到新平台')   # 锁定梯到此自然终点,解绑回主线重锁本层怪(用户2026-09-11:到顶就开主线自由发挥)
        self._combat_target_alive = False
        self._combat_target_attacked = False
        self._combat_first_strike_time = 0
        self._combat_had_target = False
        # 【用户2026-09-09·关键】检测是在梯子上做的,到顶时缓存没更新:必须把"梯子/旧平台那一帧"的旧检测结果一并清空,
        # 否则新重扫(下面节流置0)出结果前的空窗期,combat仍拿旧怪表(旧怪在下方)选成cross→人刚上去又被拉下来。
        # 清空后到新检测填回前怪表为空→combat判idle站定等待,绝不沿旧坐标往下跨层。
        self._monsters = []
        self._monster_hp_bars = []
        self._monster_feature_matches = []
        # 到顶重识别保护期(0.5s)双保险：防检测线程用手里旧帧在清空瞬间又回填、再把下方旧怪锁成cross
        self._arrival_relock_until = time.time() * 1000 + 150  # 2026-09-10提效300→150:只挡清空瞬间旧帧回填(几十ms),新检测一帧本就>150ms,缩短登顶站定发呆
        # 强制下一检测周期立刻在寻怪范围ROI内做YOLO+怪物特征+血条(不等YOLO 2Hz/特征0.33s/血条节流)，新层怪表最快刷新
        self._yolo_last_t = 0.0
        self._feat_last_t = 0.0
        self._bars_last_t = 0.0
        _debug_log("[跨层] 到达新平台(来源=%s):清旧锁定+寻怪范围立刻重扫重锁" % (source or '?'))
        self._rlog("到达新平台(%s):清旧锁定+寻怪范围重扫重锁" % (source or '?'), log='behavior')
        return True

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

    def _start_ladder_out_backoff(self, now_ms, away_dir, extra, cur_gap=0):
        """尴尬距离撤退(用户2026-09-10):人在梯下25~50、助跑跑跳没成/直立跳够不着,朝梯子【外侧】away_dir
        退extra(50)屏幕px回主线打怪,打完再上梯。复用_ladder_backoff_step执行与到位判据;
        与直跳2次失败的_start_ladder_backoff(随机/宽侧退120~150)区分:这里方向固定朝外、短距50。"""
        if self._ladder_backoff is not None:
            return  # 已在退开中,不重复启动
        _ssx = self._player_screen_pos[0] if self._player_screen_pos else 0
        _smx = self._player_map_pos[0] if self._player_map_pos else 0
        self._ladder_backoff = {
            'dir': away_dir,
            'start_sx': _ssx,        # 退开起始屏幕X(到位主判据:朝外横移≥extra)
            'start_mx': _smx,
            'target': extra,
            'start_t': now_ms,
            'out': True,             # 标记=尴尬距离外侧撤退(区别于直跳失败退开)
        }
        self._rlog("梯下X差%.0f处直立跳够不着,朝%s外侧退%dpx回主线打怪,打完再上梯" % (cur_gap, away_dir, extra),
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
        self._ladder_precise_mode = False   # 3轮失败回打怪:重开怪扫(保险,_reset_climb也会关)
        self._clear_locked_ladder('上梯失败')   # 失败=锁定梯另一自然终点,解绑回正常找怪(先锁下面Y相近的)
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
        if not self._combat_transit or not self._player_map_pos:
            self._combat_transit = False
            self._transit_target = None
            self._ladder_precise_mode = False   # 异常出口也要重开怪扫(用户2026-09-15开关配对)
            return
        # walk必须有绿线终点;ladder的cross集合允许_transit_target=None(纯屏幕状态机,不喂怪坐标)
        if getattr(self, '_transit_via', 'ladder') == 'walk' and not self._transit_target:
            self._combat_transit = False
            self._transit_target = None
            self._ladder_precise_mode = False
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
                # 次数控制(用户2026-09-10·每个机制都要有次数上限):区分"真走到新平台"与"终点本就在身边、根本没移动的空到达"。
                # 空到达=锁了范围外怪→cross→铺的路径终点就在脚下→立刻判到达→清锁定→又锁范围外怪的死循环(表现=原地左右小碎步)。
                _wf = self._transit_walk_from
                _really_moved = (_wf is None) or (abs(mpx - _wf[0]) + abs(mpy - _wf[1]) >= 18)
                if not _really_moved:
                    self._arrival_empty_streak += 1
                    if self._arrival_empty_streak >= ARRIVAL_EMPTY_MAX:
                        # 连续空到达达上限:强制留本层正常打怪、2秒内不再cross走台,从根上掐断无限空转
                        self._arrival_empty_streak = 0
                        self._no_transit_until = now_ms + 2000
                        self._combat_transit = False
                        self._transit_target = None
                        self._ladder_precise_mode = False   # 空转达上限回打怪:重开怪扫
                        self._transit_walk_path = None
                        self._release_combat_move()
                        self._release_all_keys()
                        _debug_log("[跨层] 走台连续%d次空到达(没真移动),强制本层打怪2s不再cross" % ARRIVAL_EMPTY_MAX)
                        self._rlog("走台空转达上限,留本层打怪不再空转", LOG_WARN, log='behavior')
                        return
                    # 未达上限:空到达不算"到新平台",不重扫/不清锁定,松键回主线,下帧重新决策
                    self._combat_transit = False
                    self._ladder_precise_mode = False   # 回主线:重开怪扫
                    self._release_combat_move()
                    self._release_all_keys()
                    return
                self._arrival_empty_streak = 0   # 真移动到新平台,清零空转计数
                # 到达最终目标平台：和梯子到达一样的收尾
                self._combat_transit = False
                self._transit_target = None
                self._ladder_precise_mode = False   # 到达收尾:重开怪扫回打怪段
                self._probe_side = random.choice([-1, 1])
                self._probe_switched = False
                self._climb_fail_count = 0
                self._climb_fail_limit = random.choice([2, 3])
                self._climb_fail_pause_until = 0
                self._transit_via = 'ladder'
                self._release_combat_move()
                self._release_all_keys()
                self._reset_lock_after_arrival('走台到点')   # 走到新平台同样强制重新识别+重新锁定
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
                self._set_combat_move(_dir, allow_in_transit=True)  # transit自身走路,显式放行(战斗追怪默认被跨层门控挡住)
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
        # === ladder集合(用户2026-09-15极简定稿):cross梯集合纯屏幕状态机驱动,不喂怪小地图坐标 ===
        mpx, mpy = self._player_map_pos
        if self._climb_state != 'none':
            # 上(to_ladder/climbing)/下(descend)梯集合:纯屏幕状态机推进;到顶(光点Y重合录制梯顶+多按200ms)、
            # 失败3轮、落地都在状态机内部_reset_climb回none并重锁,这里只负责每帧驱动
            self._climb_state_machine(mpx, mpy, now_ms)
            return
        if self._transit_target:
            # 选台模式:目标=录制台点(真实小地图坐标),走_move_to旧路径(随机/掉台也复用),到点才重锁
            arrived = self._move_to(self._player_map_pos, self._transit_target[0], self._transit_target[1])
            if not arrived:
                return
            self._reset_lock_after_arrival()
        else:
            # cross上/下梯集合:状态机已自行回none收尾(到顶/失败/落地已重锁),这里只做公共收尾,不重复重锁
            arrived = True
        self._combat_transit = False
        self._transit_target = None
        self._ladder_precise_mode = False   # 集合结束:重开怪扫切回打怪段
        self._slope_resume_at = now_ms + 1000
        self._probe_side = random.choice([-1, 1])
        self._probe_switched = False
        self._climb_fail_count = 0
        self._climb_fail_limit = random.choice([2, 3])
        self._climb_fail_pause_until = 0
        self._release_all_keys()
        print("[跨层] 梯/台集合结束，开始新一轮打怪")

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
        self._transit_walk_from = self._player_map_pos  # 走台启动时人物小地图坐标(到点判是否真移动过,防空到达→原地小碎步空转)
        self._arrival_empty_streak = 0
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
        """跨层决策(用户2026-09-15极简定稿):怪只活在主游戏窗口屏幕,只用来判上/下方向那一下;
        选中即进上/下梯集合,全程不再把怪换算成小地图坐标(小地图不显示怪、scale压扁是旧版原地空转根因)。
        ·绿线相连(walk):人+怪都在相连绿线→沿绿线组合路径点走(目标=真实小地图绿线点,保留,不关怪扫)。
        ·上行(怪屏幕Y在人上方):直接进to_ladder纯屏幕集合(主窗口选梯/对位/跑跳直跳,到顶只比录制梯顶Y)。
        ·下行(怪屏幕Y在人下方):进descend横跳集合(首跳即关怪扫,跳不动直接主窗口找梯,下跳动作不变)。
        ·无cross怪:选台模式去下一选中台(录制台点=真实小地图坐标,保留_move_to旧路径);全图未选台→False等刷。
        返回True=已启动;False=无可去目标(松手等刷)。"""
        if not self._player_map_pos or not self._player_screen_pos:
            self._trans_stall_diag('no_pos(人物小地图/屏幕坐标缺失,多为人物特征没匹配上)', now,
                                   map_pos=self._player_map_pos, screen_pos=self._player_screen_pos)
            return False
        mpx, mpy = self._player_map_pos
        spx, spy = self._player_screen_pos
        if getattr(self, '_climb_fail_pause_until', 0) and now < self._climb_fail_pause_until:
            self._trans_stall_diag('fail_pause(爬梯失败短冷却中)', now,
                                   left_ms=int(self._climb_fail_pause_until - now))
            return False
        self._transit_walk_path = None
        self._transit_walk_fork_idx = -1
        # 最近cross怪(屏幕坐标)=(dist,screen_x,screen_y)
        fx = fy = None
        if cross_candidates:
            cross_candidates.sort()
            _, fx, fy = cross_candidates[0]
        target_mid = None
        via = 'ladder'
        if fx is not None:
            # 仅当怪在绿线、人也在绿线、且两绿线有交叉点才走walk
            monster_pf = self._get_monster_platform(fx, fy)
            cur_pf = self._get_current_manual_platform() if monster_pf else None
            inter = self._find_platform_intersection(cur_pf, monster_pf) if (monster_pf and cur_pf) else None
            if monster_pf and cur_pf and inter:
                via = 'walk'
                _path = []
                _bpts = sorted(self._platform_points(cur_pf),
                               key=lambda p: (abs(float(p[0]) - mpx) + abs(float(p[1]) - mpy)))
                _path += [(float(p[0]), float(p[1])) for p in _bpts]
                _path.append((float(inter[0]), float(inter[1])))
                _fork = len(_path) - 1
                _tpts = sorted(self._platform_points(monster_pf),
                               key=lambda p: (abs(float(p[0]) - inter[0]) + abs(float(p[1]) - inter[1])))
                _path += [(float(p[0]), float(p[1])) for p in _tpts]
                self._transit_walk_fork_idx = _fork
                self._transit_walk_path = _path
                target_mid = _path[-1]
                _debug_log("[跨层] 绿线相连交叉点(%.0f,%.0f),走绿线组合路径(%d点)" % (inter[0], inter[1], len(_path)))
            elif monster_pf:
                _debug_log("[跨层] 怪在绿线但人不在/绿线不相连,走梯/跳集合")
        else:
            # 无cross怪:选台模式→下一选中台(录制台点真实小地图坐标);全图未选台→原地等刷
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
                    self._trans_stall_diag('no_next_platform(只选当前台/无下一台)', now,
                                           selected=self._selected_platforms, cur=cur_num)
                    return False
                pts = self._platform_points(next_pf)
                target_mid = (float(pts[len(pts) // 2][0]), float(pts[len(pts) // 2][1]))
            else:
                self._trans_stall_diag('idle_no_platform(全图无怪未选台,原地等刷)', now)
                return False
        # === 启动跨层集合:先松键,再按via分别进入 ===
        self._combat_active = False
        self._release_combat_move()
        self._release_all_keys()
        self._combat_transit = True
        self._transit_via = via
        self._transit_walk_started = now
        self._transit_walk_from = self._player_map_pos
        self._arrival_empty_streak = 0
        self._transit_walk_last_x = None
        self._transit_walk_stall = 0
        self._transit_jump_probe_y = None
        self._transit_jump_probe_t = 0
        self._transit_jump_probe_next = 0
        self._transit_jump_effective = False
        if via == 'walk':
            # 绿线找本层怪:不关怪扫,目标=绿线终点(真实小地图坐标)
            self._ladder_precise_mode = False
            self._transit_target = target_mid
            print("[跨层] 绿线相连,走台子路径(%.0f,%.0f)" % (target_mid[0], target_mid[1]))
            return True
        if fx is not None:
            # cross上/下梯集合:关怪扫、不设怪小地图目标;方向只看屏幕Y(怪Y<人Y=上层)
            self._ladder_precise_mode = True
            self._transit_target = None
            going_up = fy < spy
            if going_up:
                self._enter_to_ladder_up(mpx, mpy, now, fx)  # fx=目标怪屏幕X,冻结作选梯固定参照
                print("[跨层] 上层怪(屏幕人Y%.0f 怪Y%.0f),进纯屏幕上梯集合" % (spy, fy))
            else:
                self._reset_climb()
                self._enter_descend(mpx, mpy + 1, mpx, mpy, now)  # 横跳下台;方式一不用target值,仅表方向向下
                print("[跨层] 下层怪(屏幕人Y%.0f 怪Y%.0f),进descend横跳集合" % (spy, fy))
            return True
        # 选台模式:目标=录制台点(真实小地图坐标),state保持none交_move_to旧路径
        self._ladder_precise_mode = True
        self._transit_target = target_mid
        print("[跨层] 选台模式前往目标台(%.0f,%.0f)" % (target_mid[0], target_mid[1]))
        return True

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

    def _capture_loop(self):
        """截图线程(多线程重构·用户定稿):【全项目唯一截图者】,只做一件事——按周期截一张全窗图写进帧槽
        (_latest_frame/seq/_t/_raw_frame),供人物/怪物/加药所有识别线程共用同一张,自己不做任何识别。
        周期=上梯高帧(22~34ms自适应)/忙/闲CPU档;自建mss(BitBlt走GDI、释放GIL,可与人物/怪物识别真并行)。"""
        import mss as _mss_mod
        try:
            _sct = _mss_mod.mss()
        except Exception as _e:
            print("[截图] mss初始化失败:", _e)
            return
        # 窗口矩形(客户区)获取
        self._detect_lock.acquire()
        self._detect_sct = _sct
        self._detect_lock.release()
        last_rect = None
        # [CPU诊断] A线程只统计截图+人物耗时(怪模板/YOLO/血条在B线程各自统计)
        _dt_grab = 0.0
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
                        # === 临时·真机全屏抓帧(验证仿YOLO全屏投票可行性):检测 data/_grab_real.flag(内容=张数)即连续存原始全屏帧 ===
                        try:
                            _gfp = os.path.join(DATA_DIR, "_grab_real.flag")
                            if os.path.exists(_gfp) and getattr(self, '_grab_real_left', 0) <= 0:
                                try: _gn = int(open(_gfp, encoding="utf-8").read().strip() or "40")
                                except Exception: _gn = 40
                                try: os.remove(_gfp)
                                except Exception: pass
                                self._grab_real_left = _gn
                                self._grab_real_i = 0
                                self._grab_real_dir = os.path.join(DATA_DIR, "real_capture", "real_" + time.strftime("%Y%m%d_%H%M%S"))
                                os.makedirs(self._grab_real_dir, exist_ok=True)
                                _debug_log("[真机抓帧] 开始抓%d张全屏 -> %s" % (_gn, self._grab_real_dir))
                            if getattr(self, '_grab_real_left', 0) > 0:
                                _gi = getattr(self, '_grab_real_i', 0); self._grab_real_i = _gi + 1
                                self._grab_real_left -= 1
                                cv2.imwrite(os.path.join(self._grab_real_dir, "real_%03d.png" % _gi), _frame)
                                if self._grab_real_left <= 0:
                                    _debug_log("[真机抓帧] 完成 共%d张 -> %s" % (_gi + 1, self._grab_real_dir))
                        except Exception as _ge:
                            _debug_log("[真机抓帧] 异常:%s" % _ge)
                        # 截图线程只写帧槽:人物/怪物/加药都在各自线程取这同一张帧,不在此做任何识别(多线程重构)
                        self._latest_frame = _frame                       # 最新帧槽:原子引用替换,所有识别线程只取最新一帧
                        self._latest_frame_t = time.time()
                        self._latest_frame_seq = getattr(self, '_latest_frame_seq', 0) + 1
                        self._raw_frame = _frame                          # 供吃药/伤害/镜头/上梯对位复用,帧龄用_raw_frame_t判
                        self._raw_frame_t = self._latest_frame_t
            except Exception as _e:
                if self._detect_running:
                    print("[截图] 异常:", _e)
            # 自适应周期(用户2026-09-07 CPU94%)：最近0.4s见到怪、或正锁着怪/在战斗 → 150ms跟手；否则空闲300ms省电降占用
            # 高帧档只在to_ladder/climbing用;但_ladder_precise_mode(=梯子集合段关怪扫)只允许由进/出集合
            # 事件显式置位,绝不在此"看climb_state不对就自动关"——那会在刚决定cross、正平地朝梯走的空档
            # 重开怪扫->冒出cast->争抢抖动(用户2026-09-15拔除该后门)。
            _precise_now = bool(getattr(self, '_ladder_precise_mode', False)) \
                and getattr(self, '_climb_state', 'none') in ('to_ladder', 'climbing')
            _busy = (time.time() - self._last_monster_seen < 0.4) or bool(getattr(self, '_combat_locked_target', None))
            _elapse = (time.time() - _t0) * 1000   # 本轮检测实际耗时(先算,高帧自适应监管要用)
            if _precise_now:
                # 上梯对位高帧(用户2026-09-11:目标按核数分档八核22/四核28/低配34ms+CPU监管防卡死):按本轮实测耗时自适应——
                # 连续几轮留不出最小空闲=跑不完→周期每档+3退避(封顶45ms),防检测线程吃满一个核;持续轻松再每档-3升回本档目标。
                _tgt = self._precise_target_period()
                _ap = getattr(self, '_precise_adapt_p', None) or _tgt
                if _elapse > _ap - LADDER_PRECISE_MIN_SLEEP_MS:
                    self._precise_ov_n = getattr(self, '_precise_ov_n', 0) + 1
                    self._precise_rx_n = 0
                    if self._precise_ov_n >= LADDER_PRECISE_OVERLOAD_N and _ap < LADDER_PRECISE_PERIOD_MAX:
                        _ap = min(LADDER_PRECISE_PERIOD_MAX, _ap + LADDER_PRECISE_STEP_MS)
                        self._precise_adapt_p, self._precise_ov_n = _ap, 0
                        _debug_log("[高帧监管] 单轮%.0fms跑不完%dms档,退避到%dms防CPU卡死" % (
                            _elapse, _ap - LADDER_PRECISE_STEP_MS, _ap))
                else:
                    self._precise_rx_n = getattr(self, '_precise_rx_n', 0) + 1
                    self._precise_ov_n = 0
                    if self._precise_rx_n >= LADDER_PRECISE_RELAX_N and _ap > _tgt:
                        _ap = max(_tgt, _ap - LADDER_PRECISE_STEP_MS)
                        self._precise_adapt_p, self._precise_rx_n = _ap, 0
                _period = _ap
            else:
                self._precise_adapt_p = None  # 离开高帧:自适应档位清空,下次进按核数目标重新起步
                self._precise_ov_n = self._precise_rx_n = 0
                _period = self._perf_val('detect_busy_ms') if _busy else self._perf_val('detect_idle_ms')  # 忙/闲周期按CPU性能档
            # [CPU诊断2026-09-07] 每约1秒汇总检测线程各阶段耗时(毫秒)，定位检测侧CPU大头
            _dt_rounds += 1
            _dt_now = time.time()
            if _dt_now - _dt_last_report >= 1.0:
                _msg = "[截图耗时] %d轮 周期%s 截图%d (ms/秒)" % (
                    _dt_rounds, "精" if _precise_now else ("忙" if _busy else "闲"),
                    _dt_grab * 1000)
                print(_msg)
                _debug_log(_msg)
                _dt_grab = 0.0
                _dt_rounds = 0
                _dt_last_report = _dt_now
            _slack = _period - _elapse
            if _precise_now and _slack < LADDER_PRECISE_MIN_SLEEP_MS:
                _slack = LADDER_PRECISE_MIN_SLEEP_MS   # 高帧CPU监管兜底:哪怕本轮跑超时也强制让出3ms给GIL/主线UI,绝不吃满一个核
            if _slack > 0:
                time.sleep(_slack / 1000.0)

    def _person_loop(self):
        """人物识别线程(多线程重构·用户定稿·三地基线程之一):自己【不截图】,只从截图线程帧槽取最新一帧,
        按角色fps节拍(上梯高帧每帧)跑人物多锚点匹配,原子发布_raw_char_pos+人物世界快照。
        人物识别不再被截图/怪物YOLO拖住、最跟手。按seq只处理新帧,没新帧轻睡10ms,全程try自保护绝不崩。"""
        _last_seq = -1
        _dt_char = 0.0
        _dt_rounds = 0
        _dt_last_report = time.time()
        while self._detect_running:
            try:
                _frame = self._latest_frame               # 截图线程发布的最新帧(原子只读)
                _seq = getattr(self, '_latest_frame_seq', 0)
                if _frame is None or _seq == _last_seq:
                    time.sleep(0.010)                      # 没新帧轻等,不空转
                    continue
                _last_seq = _seq
                _fh, _fw = _frame.shape[:2]
                _band_y1 = DETECT_TOP_MARGIN
                _band_y2 = max(_band_y1 + 1, _fh - DETECT_BOTTOM_MARGIN)
                # 上梯对位高帧豁免fps节流(必须跟手);否则按面板角色fps节流,未到节拍沿用上一人物点
                _in_precise = bool(getattr(self, '_ladder_precise_mode', False)) \
                    and getattr(self, '_climb_state', 'none') in ('to_ladder', 'climbing')
                try:
                    _role_fps = int((self._role_rec or {}).get("params", {}).get("fps", 24) or 24)
                except Exception:
                    _role_fps = 24
                if _in_precise or time.time() - getattr(self, '_role_last_track_t', 0) >= 1.0 / max(1, _role_fps):
                    _tc0 = time.time()
                    _ch = self._get_player_screen_pos(_frame)   # 到节拍才匹配(局部很轻,丢失才全图)
                    _dt_char += time.time() - _tc0
                    self._role_last_track_t = time.time()
                    # 人物点落在顶部标题栏/底部UI带=误匹配(人物不可能站UI上),作废
                    if _ch is not None and not (_band_y1 <= _ch[1] <= _band_y2):
                        _ch = None
                    self._raw_char_pos = _ch                 # 原子发布:动作线程直接读最新人物点
                    self._char_feature_matches = getattr(self, '_char_feature_matches', [])
                    try:
                        self._snap_store.update_parts(player_screen=_ch, player_t=time.time())
                    except Exception as _se:
                        _debug_log("[人物] 快照发布异常:%s" % _se)
                # 停止态(没在运行打怪)低频扫梯子白框供蒙板常开显示;运行态由识别B线程扫,门控互斥、不同时写缓存(用户2026-09-15)
                if not self._monster_running and self._raw_char_pos is not None:
                    _lm_now = time.time()
                    if _lm_now - getattr(self, '_lad_marks_scan_t', 0.0) >= LADDER_MARK_SCAN_MS / 1000.0:
                        try:
                            self._lad_marks_cache = self._scan_ladder_marks(_frame, self._raw_char_pos)
                            self._lad_marks_scan_t = _lm_now
                        except Exception:
                            pass
                _dt_rounds += 1
                _rn = time.time()
                if _rn - _dt_last_report >= 1.0:
                    _debug_log("[人物耗时] %d帧 人物匹配%d (ms/秒)" % (_dt_rounds, _dt_char * 1000))
                    _dt_char = 0.0
                    _dt_rounds = 0
                    _dt_last_report = _rn
            except Exception as _e:
                if self._detect_running:
                    print("[人物] 异常:", _e)
                    _debug_log("[人物] 异常:%s" % _e)
            time.sleep(0.005)

    def _recognize_loop(self):
        """识别B线程(物理拆分·用户2026-09-12):【自己不截图】,只从A线程发布的最新帧槽取新帧,低频跑重活
        (怪模板匹配+YOLO+血条+合并/时序平滑/2秒宽限),原子发布_raw_monsters/_raw_hp_bars。
        人物由A线程高频出,B重活跑多慢都不拖人物。按帧槽seq只处理新帧,重活各自节流,没新帧轻睡10ms,全程try自保护绝不崩。"""
        _seen_reset_seq = 0
        _last_seq = -1
        _dt_feat = _dt_yolo = _dt_bars = 0.0
        _dt_rounds = 0
        _dt_last_report = time.time()
        if not hasattr(self, '_yolo_cache'):   # 重活缓存归B私有
            self._yolo_cache, self._yolo_last_t = [], 0.0
            self._feat_cache, self._feat_last_t = [], 0.0
            self._bars_cache, self._bars_last_t = [], 0.0
        while self._monster_running:   # 方案B:怪物线程只在"开始运行"期间跑,停止即退出(截图/人物常开不受影响)
            try:
                # 硬重置版本号自清(清的全是怪/血条跨帧缓存,归怪物线程;人物不清)
                if self._detect_reset_seq != _seen_reset_seq:
                    _seen_reset_seq = self._detect_reset_seq
                    self._yolo_cache, self._feat_cache, self._bars_cache = [], [], []
                    self._yolo_last_t = self._feat_last_t = self._bars_last_t = 0.0
                    self._detect_last_monsters = None
                    self._detect_last_monsters_time = 0
                    self._detect_recent = []
                    self._monster_static_track = {}
                    self._raw_monsters = []
                    _debug_log("[识别B] 硬重置seq=%d,清怪/血条缓存并全量重扫" % _seen_reset_seq)
                _frame = self._latest_frame                 # A发布的最新帧(原子引用,B只读不改)
                _seq = getattr(self, '_latest_frame_seq', 0)
                if _frame is None or _seq == _last_seq:
                    time.sleep(0.010)                       # 没新帧:轻等不空转
                    continue
                _last_seq = _seq
                # 选梯/上下梯阶段(用户2026-09-15):检测B只保留【梯子识别】(人物识别由常开的人物线程负责),
                # 关怪模板/YOLO=清怪表,主线 self._monsters=list(_raw_monsters) 拿空→算不到怪距→不打怪不巡路、不与上/下梯抢主权。
                # 覆盖上梯to_ladder/climbing与下梯descend;到顶或3轮失败由_reset_climb把_ladder_precise_mode置False自然恢复。
                # 玩家HP/MP加药在主线程_check_auto_potion独立常开(直接用截图A),不经过这里,上梯照常吃药、绝不在此关玩家血条。
                _precise = bool(getattr(self, '_ladder_precise_mode', False)) \
                    and getattr(self, '_climb_state', 'none') in ('to_ladder', 'climbing', 'descend')
                if _precise:
                    # 只清怪物位置/检测缓存,不碰任何血条;【不再continue】——落到本循环尾部做梯子白框高频扫描。
                    # (旧写法continue把尾部梯子扫描也跳过→选梯/爬梯时_lad_marks_cache冻结不更新=选梯反而不实时,已修)
                    self._raw_monsters = []
                    self._raw_cached_feature_monsters = []
                    self._yolo_cache, self._feat_cache = [], []
                    self._detect_last_monsters = None
                if not _precise:
                    _fh, _fw = _frame.shape[:2]
                    # 识别物理边界=游戏画面(客户区)子矩形,标题栏/边框那圈不扫(用户2026-09-14);取不到退回整帧
                    _csub = getattr(self, 'client_subrect', None)
                    if _csub:
                        _px1, _py1, _px2, _py2 = int(_csub[0]), int(_csub[1]), int(_csub[2]), int(_csub[3])
                    else:
                        _px1, _py1, _px2, _py2 = 0, 0, _fw, _fh
                    _band_y1 = max(DETECT_TOP_MARGIN, _py1)
                    _band_y2 = min(max(_band_y1 + 1, _fh - DETECT_BOTTOM_MARGIN), _py2)
                    _ch = self._raw_char_pos   # 用A最新人物点做范围裁剪(差一个A周期,寻怪范围有余量,不影响)
                    _now_det = time.time()
                    _fc = self._get_fight_config()
                    _skr = int(_fc.get("atk1_distance", 150) or 150)
                    _yupr = abs(int(_fc.get("attack_y_up", -ATTACK_Y_UP)))
                    _ydnr = abs(int(_fc.get("attack_y_down", ATTACK_Y_DOWN)))
                    _far_x = int(_fc.get("far_range_x", 0) or 0)
                    _far_y_up = int(_fc.get("far_range_y_up", 0) or 0)
                    _far_y_down = int(_fc.get("far_range_y_down", 0) or 0)
                    if _ch is not None and _far_x > 0 and (_far_y_up > 0 or _far_y_down > 0):
                        _dyx1 = max(_px1, _ch[0] - _far_x)
                        _dyx2 = min(_px2, _ch[0] + _far_x)
                        _dyy1 = _ch[1] - _far_y_up if _far_y_up > 0 else _band_y1
                        _dyy2 = _ch[1] + _far_y_down if _far_y_down > 0 else _band_y2
                    else:
                        _dyx1, _dyx2, _dyy1, _dyy2 = _px1, _px2, _band_y1, _band_y2
                    _yolo_crop = (max(_px1, _dyx1), max(_band_y1, _dyy1), min(_px2, _dyx2), min(_band_y2, _dyy2))
                    if _yolo_crop[2] <= _yolo_crop[0] or _yolo_crop[3] <= _yolo_crop[1]:
                        _yolo_crop = (_px1, _band_y1, _px2, _band_y2)
                    self._disp_yolo_crop = _yolo_crop  # 怪物识别(YOLO推理)范围,供蒙板黄框可视化
                    if _ch is not None:
                        _ftx1, _ftx2 = max(_px1, _ch[0] - _skr), min(_px2, _ch[0] + _skr)
                        _fty1, _fty2 = max(_band_y1, _ch[1] - _yupr), min(_band_y2, _ch[1] + _ydnr)
                    else:
                        _ftx1, _ftx2, _fty1, _fty2 = _px1, _px2, _band_y1, _band_y2
                    _feat_crop = (_ftx1, _fty1, _ftx2, _fty2)
                    if _feat_crop[2] <= _feat_crop[0] or _feat_crop[3] <= _feat_crop[1]:
                        _feat_crop = (_px1, _band_y1, _px2, _band_y2)
                    self._disp_feat_crop = _feat_crop  # 人物技能(攻击射程atk1_distance+Y上下)范围,供蒙板紫框
                    if _now_det - self._feat_last_t >= self._perf_val('feat_s'):  # 怪模板节流按CPU档(无模板直接[]零开销)
                        _tf0 = time.time()
                        self._feat_cache = self._match_monster(_frame, _feat_crop) if self._monster_templates else []
                        _dt_feat += time.time() - _tf0
                        self._feat_last_t = _now_det
                    _feat = self._feat_cache
                    _lk = getattr(self, '_combat_locked_target', None)
                    _locked_in = bool(_lk) and _ch is not None and abs(_lk[0] - _ch[0]) <= _skr \
                        and -_yupr <= (_lk[1] - _ch[1]) <= _ydnr
                    _yolo_gap = (self._perf_val('yolo_slow_s') if _locked_in else self._perf_val('yolo_fast_s'))
                    if _now_det - self._yolo_last_t >= _yolo_gap:
                        _ty0 = time.time()
                        self._yolo_cache = self._detect_monsters(_frame, _yolo_crop)
                        _dt_yolo += time.time() - _ty0
                        self._yolo_last_t = _now_det
                    _yolo = self._yolo_cache
                    _merged = self._merge_detections(_yolo, _feat)
                    _search = []
                    for (x1, y1, x2, y2, _s) in _merged:
                        _mcx, _mcy = (x1 + x2) // 2, y2
                        if _ch is None or (abs(_mcx - _ch[0]) <= _skr
                                           and -_yupr <= (_mcy - _ch[1]) <= _ydnr):
                            _search.append((max(0, x1 - 15), max(0, y1 - 40), x2 + 15, y1 + 5))
                    if self._combat_last_target_pos and _ch is not None:
                        _tx, _ty = self._combat_last_target_pos
                        if abs(_tx - _ch[0]) <= _skr + 40:
                            _search.append((max(0, _tx - 50), max(0, _ty - 55),
                                            min(_frame.shape[1], _tx + 50), min(_frame.shape[0], _ty + 10)))
                    if _now_det - self._bars_last_t >= self._perf_val('bars_s'):
                        _tb0 = time.time()
                        self._bars_cache = self._detect_monster_hp_bars(_frame, _search if _search else None)
                        _dt_bars += time.time() - _tb0
                        self._bars_last_t = _now_det
                    _bars = self._bars_cache
                    if _merged:   # 怪2秒宽限:本轮空但2秒内有怪则保留,防偶发漏检闪没
                        self._detect_last_monsters = _merged
                        self._detect_last_monsters_time = time.time()
                    elif (time.time() - self._detect_last_monsters_time < 2.0
                          and self._detect_last_monsters):
                        _merged = self._detect_last_monsters
                    _merged = self._temporal_smooth_detections(_merged)  # 单帧漏检不清目标
                    _merged = [b for b in _merged if _band_y1 <= (b[1] + b[3]) // 2 <= _band_y2]  # 识别带兜底剔UI误检
                    self._raw_cached_feature_monsters = _feat
                    self._raw_monsters = _merged
                    self._raw_hp_bars = _bars
                    if not self._monster_templates:
                        self._monster_feature_matches = []
                    if _merged:
                        self._last_monster_seen = time.time()
                    try:
                        _bt = time.time()
                        self._snap_store.update_parts(monsters=list(_merged), monsters_t=_bt,
                                                      extra={'hp_bars': list(_bars) if _bars is not None else []},
                                                      hp_bars_t=_bt)
                    except Exception as _se:
                        _debug_log("[识别B] 怪/血条快照发布异常:%s" % _se)
                    _dt_rounds += 1
                # 梯子白框扫描【2026-09-14性能·从主线程7d搬到识别B线程异步跑】:主线程不再被多模板matchTemplate/
                # dilate堵住(原近全屏范围单次数百ms、帧率掉到3~5、人物1秒才跟手)。精准(上梯)用小ROI高频档、非精准用
                # far_range大ROI的250ms档(_scan_ladder_marks内部按_ladder_precise_mode自选范围);结果原子写_lad_marks_cache,
                # 主线程选梯/蒙板只读,数据格式[(cx,cy,sim)]与节流口径完全不变,仅生产位置改后台、异步一拍(在原gap内)。
                try:
                    _lm_ch = self._raw_char_pos
                    if _frame is not None and _lm_ch is not None:
                        _lm_precise = bool(getattr(self, '_ladder_precise_mode', False)) and \
                            getattr(self, '_climb_state', 'none') in ('to_ladder', 'climbing', 'descend')
                        _lm_gap_s = (LADDER_PRECISE_MARK_MS if _lm_precise else LADDER_MARK_SCAN_MS) / 1000.0
                        _lm_now = time.time()
                        if _lm_now - getattr(self, '_lad_marks_scan_t', 0.0) >= _lm_gap_s:
                            self._lad_marks_cache = self._scan_ladder_marks(_frame, _lm_ch)
                            self._lad_marks_scan_t = _lm_now
                except Exception:
                    pass
                _rn = time.time()   # B耗时统计每秒一条
                if _rn - _dt_last_report >= 1.0:
                    _debug_log("[识别B耗时] %d新帧 怪模板%d YOLO%d 血条%d (ms/秒)" % (
                        _dt_rounds, _dt_feat * 1000, _dt_yolo * 1000, _dt_bars * 1000))
                    _dt_feat = _dt_yolo = _dt_bars = 0.0
                    _dt_rounds = 0
                    _dt_last_report = _rn
            except Exception as _e:
                if self._monster_running:
                    print("[识别B] 异常:", _e)
                    _debug_log("[识别B] 异常:%s" % _e)
            time.sleep(0.010)

    def _precise_target_period(self):
        """上梯高帧【目标周期】由CPU性能三档给(快22/普通28/慢34ms≈45/36/29Hz);实际周期再由检测线程自适应监管
        (跑不完每档+3退避、封顶LADDER_PRECISE_PERIOD_MAX、轻松再升回此目标),保证慢机不吃满核。读_perf缓存、切档即时变。"""
        return int(self._perf_val('precise_ms'))

    def _start_detection_thread(self):
        # 常开层(方案B·用户定稿):截图+人物 绑定游戏窗口就常开,喂角色识别框/实时识别率/加药竖框,不随运行停
        if (self._capture_thread and self._capture_thread.is_alive()) and \
                (self._person_thread and self._person_thread.is_alive()):
            return
        self._detect_running = True
        if self._latest_frame is None:
            self._latest_frame_seq = 0
        if not (self._capture_thread and self._capture_thread.is_alive()):
            self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True, name="detect_capture")
            self._capture_thread.start()
        if not (self._person_thread and self._person_thread.is_alive()):
            self._person_thread = threading.Thread(target=self._person_loop, daemon=True, name="detect_person")
            self._person_thread.start()
        print("[识别线程] 常开层启动: 截图+人物(绑定窗口常开)")

    def _start_runtime_detection(self):
        # 运行层(方案B):怪物识别(模板+YOLO+血条)+移动监管+边界守护,点"开始运行"才启动、停止即停(幂等,主循环按_running收敛)
        if not (self._recognize_thread and self._recognize_thread.is_alive()):
            self._monster_running = True
            self._recognize_thread = threading.Thread(target=self._recognize_loop, daemon=True, name="detect_monster")
            self._recognize_thread.start()
            print("[识别线程] 运行层启动: 怪物(模板+YOLO+血条)")
        self._start_move_watchdog()  # 移动监管线(独立线程)
        self._start_bound_guard()    # 打怪区域边界守护(独立线程)

    def _stop_runtime_detection(self):
        # 停运行层(怪物+监管+边界),保留常开层截图+人物(角色识别框/识别率继续显示)
        self._monster_running = False
        _th = self._recognize_thread
        if _th and _th.is_alive():
            _th.join(timeout=1.0)
        self._recognize_thread = None
        self._stop_move_watchdog()
        self._stop_bound_guard()

    def _stop_detection_thread(self):
        # 全停(解绑窗口/彻底关闭用):先停运行层,再停常开层截图+人物
        self._stop_runtime_detection()
        self._detect_running = False
        for _th in (self._capture_thread, self._person_thread):
            if _th and _th.is_alive():
                _th.join(timeout=1.0)
        self._capture_thread = None
        self._person_thread = None

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

        # 全局2秒总兜底(用户2026-09-10):任何卡住/不动/异常满2秒→全部清零重来;放在所有决策之前,覆盖战斗/追怪/跨层/爬梯,返回True本帧交还下帧
        if self._global_stall_watchdog(now):
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

        # 单向走不动(地形挡)不在此处理,靠录制绿线6px跑跳+卡住跳脱困;硬重置只认左右互搏冲突。
        # 注:旧"主线每帧消费水平停滞→续跑/放弃"已撤,统一在主循环帧首 _consume_hard_reset 跨线程清零,不在combat_tick中途串行处理。

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

        # 左右越线强制拉回已上移到主循环帧首(_bound_pull_tick,第一时间独占拉回1000~1500ms),combat_tick内不再重复处理

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
            self._release_combat_move()
            return

        # === 有目标（当前平台上有怪）===
        px, py = self._player_screen_pos
        # 人怪Y分层直接用"实时人物Y"(同2026-09-10及之前版本,用户确认那时一直正常)。
        # 2026-09-11曾改用"落地稳定基线_char_ground_y"(腾空时冻结),但人走上更高台阶/坡后脚Y永久抬高,
        # 被误判成起跳→基线冻结在旧低处、且要求Y回落才解锁,上台阶后永远解不开(实测实时脚528/基线卡620差92),
        # 导致几乎同高的怪被算成"上方99"一直误判跳高打。回退实时Y,与X用同一套坐标,简单不卡死。
        py_layer = py

        # 首次发现目标：反应延迟
        if not self._combat_had_target:
            self._combat_had_target = True
            self._combat_react_until = now + random.randint(30, 90)  # 2026-09-09提效80-250→30-90,先求快;拟人化阶段再调回随机区间
            return

        # 【冒险岛世界2026-09-07清理】旧"手写分边探测(monster_dists/cross_candidates/probe_side排序)+跨层中遇怪取消"
        # 整段已删除：选目标/分层/跨层/取消跨层全部由下方 combat_step 统一决策（其结果 _dl['state'] 在后面处理跨层取消），
        # 旧段构建后无任何消费者(A2后群攻也改数self._monsters)，属死代码。

        # === 用已验证的决策核心 combat_step 选目标/方向/存活（同平台优先 + 跨平台/cross/idle 一次搞定）===
        # 静态/空怪过滤已由主循环在做，这里直接用主循环过滤后的 self._monsters
        skill_range = int(fight_cfg.get("atk1_distance", 150) or 150)
        # 【用户2026-09-10】停步出手线=技能射程4/5(250→200):(stop_range,skill_range]仍pursue一直按住走,≤stop_range才站定开打,
        # 与combat_logic cast_range同一口径,治"大圈内怪被判cast站定、只靠转身短按蹭、不走过去"的碎步
        stop_range = max(1, int(skill_range * 4 // 5))
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
        # 伤害数字只在"停步出手线+Y范围内"的锁定目标上检测（用户2026-09-10：4/5线内才算真能打到,之外继续走近、不判空怪）；
        # 超线(pursue还没走近)不判空怪、也省一次抓帧
        _in_skill = bool(_lock_p) and abs(_lcx - px) <= stop_range and -_atk_y_up <= (_lcy - py_layer) <= _atk_y_down
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
                _dy = _mcy - py_layer  # 怪脚Y - 人物落地基线Y（负=怪在上,正=怪在下;用基线不被腾空带偏）
                _yok = (-_atk_y_up <= _dy <= _atk_y_down)
                _xok = abs(_mcx - px) <= skill_range
                _sameplt = self._is_monster_on_platform(_mcx, _mcy)
                _mstrs.append("(%d,%d)X差%d Y差%d 同平台=%s 直打=%s" % (
                    _mcx, _mcy, abs(_mcx - px), abs(_mcy - py_layer), _sameplt,
                    ("可" if (_yok and _xok and _sameplt) else "不可")))
            _debug_log("[怪分类] 人物=(%d,%d) 怪数=%d → %s" % (px, py_layer, len(self._monsters), " | ".join(_mstrs)))
        # 锁怪冻结(用户2026-09-09)：已进入爬梯/上下跳/瞬移动作就不换锁——中途有怪进技能范围也不替换,
        # 等上/下到位(_climb_state回none)后下一帧重新识别时才解绑重锁；平地走向梯子那段(_climb_state=none)不冻,仍允许近身怪优先。
        # 【2026-09-09修复"一上去就下来"】独占判据只看_climb_state!=none,不再and _combat_transit:
        # 边界帧transit可能还没置位/已被取消分支清掉,旧写法此刻漏冻→锁到活着=False死怪/近身怪,决策抖成cast抢发攻击键把人从梯上弄下来。
        _freeze_lock = self._is_lock_frozen()  # 硬信号:跳起抓梯(post_jump)/爬梯/下跳/瞬移才冻;平地走向梯子(to_ladder未跳)不冻可换怪
        # 【责任硬分界·用户2026-09-10定稿】第一次起跳(post_jump)→登顶/失败=跨层执行期,与打怪彻底互斥:
        # 这期间不跑打怪决策(不找怪/不锁怪/不判空怪/不攻击),战斗侧也不碰左右移动键,只由transit一心爬到顶或出失败结果。
        # 从决策最源头切干净,不再靠后面逐段if拦截(根治"战斗移动与跨层抢方向键/两个脑子左右拉扯")。
        # 跨层前本层有怪先打由决策层保证(state=cast/pursue优先,cross=本层无够得着的怪才触发);登顶/失败_reset_climb后自动恢复找怪打怪。
        if _freeze_lock:
            self._release_attack_key()
            self._release_combat_move()
            if self._combat_transit:
                self._transit_step()
            return
        # 每帧先核对上一次战斗瞬移是否真的让人物位移(用户2026-09-11:瞬移不过去要立刻知道、转跳/梯子,不卡住空闪)
        self._check_combat_teleport(now, px, py)
        # 第二层横跳拉回·A级锁侧(用户2026-09-11):锁侧窗口内只把净方向那一侧(含正上方15px容差)的怪交给决策,
        # 从数据源头断掉"在左右怪间反复横跳选目标";该侧一只都没有时不过滤(避免无怪空站),交下一轮B级处理。
        _combat_mons = self._monsters
        _ajhs = self._aj_hold_side
        if _ajhs and now < _ajhs['until']:
            _kept = [_m for _m in _combat_mons
                     if (((_m[0] + _m[2]) // 2 - px) * _ajhs['dir']) >= -15]
            if _kept:
                _combat_mons = _kept
        elif _ajhs and now >= _ajhs['until']:
            self._aj_hold_side = None
        _dl = combat_logic.combat_step(
            now, px, py_layer, _combat_mons, self._selected_platforms, skill_range, aoe_range,
            _far_x, self._combat_locked_target, self._monster_hp_bars, _has_dmg,
            True, True, self._probe_side, self._probe_switched,
            self._is_monster_on_platform, self._get_monster_platform,
            self._combat_target_lock_time,
            self._combat_target_hp_confirmed, self._combat_gone_frames, self._combat_locked_target, _attacked,
            # 【用户2026-09-09】上方"可锁定/可接近"分界=_eff_up_band：启用跳高打=用户上限(区间内进cand走高跳打、不找梯子，
            # 超上限落cross走梯子/瞬移)；未启用或当前目标跳打打空降级=_atk_y_up(旧行为)。主攻真出手仍由本地_atk_y_up门控(跳到够得着才打)。
            _eff_up_band, _atk_y_down, True, freeze_lock=_freeze_lock,
            group_priority=bool(fight_cfg.get("group_priority")), group_radius=aoe_range,
            # 群怪优先圈群唯一判据=群攻X射程(aoe_range)+群攻Y范围；aoe_dual=双向近身技能(站怪群中心,两侧同时出伤害)
            aoe_y_up=_aoe_y_up, aoe_y_down=_aoe_y_down, aoe_dual=bool(fight_cfg.get("aoe_dual")),
            # 用户2026-09-10:只有本层射程内真能打到(_in_skill)才允许"血条消失/出手无反馈"判死drop;
            # 跨层/射程外打不到的目标can_strike=False→不丢,起跳前只被本层能直打怪自然替换,起跳后freeze死锁到登顶/失败
            can_strike=_in_skill, lock_tier=getattr(self, '_combat_lock_tier', None),
            # 用户2026-09-11定稿:绿线只辅助【寻路】、不参与【打怪分层】。战斗决策这里传None=纯按Y差分层,
            # 不再用录制绿线把远处隔着地形的怪破格成同层(实锤:绿线画长/弯折时Y差111的远怪被判同层锁了却走不到=发呆)。
            # 规则=先水平走到X射程内,再纯判Y:Y在主攻/高跳带=能打,仍超=cross找梯子/下台。(跨层寻路_try_platform_transition仍用绿线)
            same_platform_fn=None)
        self._combat_target_hp_confirmed = _dl['hp_confirmed']
        self._combat_gone_frames = _dl['gone_frames']
        self._combat_target_alive = _dl['alive']
        # 回存本帧锁定类别(in/out/cross)作下一帧维持依据;idle/drop重选时由决策结果自带,无目标=None自然清(两类锁怪)
        self._combat_lock_tier = _dl.get('tier')
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
                    _dl['state'], self._combat_locked_target, _tg[0], _tg[1], px, py_layer,
                    abs(_tg[0] - px), abs(_tg[1] - py_layer), _dl['dist'], _act))
            else:
                _debug_log("[打怪决策] 状态=%s 无目标(候选空/全不在平台/全超Y范围) 人物=(%d,%d)" % (
                    _dl['state'], px, py_layer))
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
        # 【不可打断态收窄·用户2026-09-11】只有"已抓梯在爬/已起跳/下落/瞬移中"才硬冻走完巡路(爬一半被近身怪
        # 拉下来会掉梯);to_ladder=平地走向/对齐梯子、还没抓上,不属于硬冻——放行到下面移动权裁决,
        # 让"近身技能范围内刷可直打怪→三步走解绑回主线先打"生效(原条件!=none把to_ladder也冻住=梯框合不上时干卡数秒的根因)。
        if getattr(self, '_climb_state', 'none') in ('climbing', 'jump_up', 'jump_down', 'descend', 'teleport'):
            self._release_attack_key()
            if self._combat_transit:
                self._transit_step()
            return

        # === 平地阶段移动权唯一裁决(用户2026-09-11:跨层怪=范围外怪,套范围外规则) ===
        # 锁定上层怪后锚点坐标固定保存;平地走向梯子/走台子(_climb_state=none,还没起跳,能走到这说明未硬冻)时:
        #  ·技能范围内刷出能直打的本层怪(决策state=cast)→严格三步走:解绑锚点→取消去梯子动作→松键回主线,下帧主线自然锁近身怪打;
        #  ·没有近身可直打怪(state=pursue/cross,都是范围外)→锚点不换不丢,一心_transit_step去上层;
        #  ·起跳抓梯后由上面 _climb_state!='none' 分支硬冻巡路优先,根本走不到这,近身怪也不打断。
        if self._combat_transit or getattr(self, '_climb_state', 'none') == 'to_ladder':
            # 一条线串行(用户2026-09-15):一旦进入跨层/上梯段就只干这一件事,整段不再看打怪决策、
            # 没有"近身刷怪就解绑回打"分支(它=1212左右争抢抖动的根源,已废)。只走_transit_step,
            # 到顶/3轮失败这些"集合结束事件"里才松键+重开怪扫+切回打怪。攻击键进入即松(打完怪再上梯)。
            self._release_attack_key()
            if now < getattr(self, '_arrival_relock_until', 0):
                self._release_combat_move()
                return
            if self._ladder_backoff is not None and self._ladder_backoff_step(now):
                return
            self._transit_step()
            return
        # 非transit:移动权在战斗手里,继续往下走 cast/pursue(打/追) 或 cross(首次启动跨层),互不重叠

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
                # 改打身边能直打的怪(cast)=不再去上层,清掉可能残留的锁定梯,防下帧又被拉回cross拉扯(用户2026-09-11)
                if _dl['state'] == 'cast' and getattr(self, '_locked_ladder', None) is not None:
                    self._clear_locked_ladder('改打技能范围内近身怪')
                self._combat_target_attacked = False  # 换了新目标：重置"已出手"标记（空怪判定用）
                self._combat_first_strike_time = 0    # 换新目标：首次出手计时清零，重新给反馈窗口
                self._combat_target_lock_time = now     # 重置锁定基准时间
                self._combat_target_lock_x = t_cx       # 重置1秒X无变化基准
                self._combat_target_hp_confirmed = False
                self._slope_high_blocked = False        # 换新目标：清除"上一只跳打打空"降级，新目标重新按用户区间判定
                # 跳高打节奏(用户2026-09-11治"两种模式都不起跳/只乱跳不出手"):上层一排怪Y都落在跳打区间,人物一移动,
                # "X最近的高处参照怪"就在多只之间切换→旧逻辑每换一只就把起跳时刻_slope_jump_t清0,状态机永远到不了
                # "跳后80~100ms主攻"(真机日志:跳后恒=0ms、下次跳余恒~300反复重置)。故新旧目标【都】落在跳高打Y区间
                # (=同一高处层、只是换X参照)时保留起跳/出手节奏,让"起跳→空中出手→落地再跳"闭环走完;只有真离开
                # 跳打区间(换层/改平地打/走梯子)才清零重来。
                _new_in_sj = bool(_slope_on) and _sj_min <= (py_layer - t_cy) <= _sj_max
                _old_in_sj = bool(_slope_on) and _oldlk is not None and _sj_min <= (py_layer - _oldlk[1]) <= _sj_max
                if not (_new_in_sj and _old_in_sj):
                    self._slope_high_mode = False
                    self._slope_phase = 'wait_jump'   # 离开跳打区间:重置循环,下次进high_slope第一帧直接跳
                    self._slope_next_at = 0
                else:
                    _debug_log("[跳高打] 同高处层换参照怪(%d,%d)->(%d,%d),保留跳-攻循环节奏不清零" % (
                        _oldlk[0], _oldlk[1], t_cx, t_cy))
                # 上屏(用户2026-09-09要看日志滚动)：锁定/换锁瞬间报目标相对位置，Y差正=怪在人物上方
                self._rlog("锁定怪 X差%+d Y差%+d(正=在上) 距离%d [%s]" % (
                    t_cx - px, py_layer - t_cy, int(_dl.get('dist', 0) or 0), _dl['state']))
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
            # 【用户2026-09-11】此处不再绑上层怪坐标:跨层统一在state=cross的_try_platform_transition里由怪锁定梯子,
            # cast/pursue锁的是当前要打的怪、不锁梯,避免"边打边被跨层坐标拉扯"。
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
                    self._rlog("跳高打打空:无血条无伤害=这位置够不着(怪在上%dpx),改走梯子/瞬移" % (py_layer - t_cy), LOG_RED)
                else:
                    # 普通空怪(假怪/刚打死)：记录位置，短时间不再重锁（防空怪"drop后又选同一只"死循环空打）
                    self._combat_dropped_phantoms.append((t_cx, t_cy, now))
                    self._rlog("怪无血条/无伤害(已死或假怪,在上%+dpx),放弃并重新锁怪" % (py_layer - t_cy), LOG_RED)
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
            # 到顶重识别保护期(用户2026-09-09；提效500→300ms)：刚翻上/下平台0.3s内,旧帧可能把梯子上测的旧怪(在下方)判成cross把人又拉下去
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
                # 【用户2026-09-11】此处不再绑怪空坐标:锁定梯由下面_try_platform_transition按怪→梯→人选并锁,锁后不依赖怪
                # 上屏(用户2026-09-09)：本层够不着→报目标在上/下多少px、需要跨层；限频700ms防刷
                self._rlog_throttle('cross_need', "本层无够得着的怪,目标在%s%dpx(X差%+d),需走梯子/瞬移跨层" % (
                    "上方" if _ccy < py_layer else "下方", abs(py_layer - _ccy), _ccx - px), 1500, log='behavior')
            # 原地直跳连续2次抓不住梯子的退开(用户2026-09-09)：本层无怪(cross)时先朝外侧退120~150px,
            # 退够前不选梯子；本层有怪时上面cast/pursue已先打怪、不会进cross,天然"打完怪再自动上梯"
            if self._ladder_backoff is not None and self._ladder_backoff_step(now):
                return
            # 能走到这 _combat_transit 必为False:transit在手的情况已由上面"平地移动权裁决"统一处理(本层出怪回切/无怪transit_step)
            # 空转达上限/弃梯回切后的"强制本层"防抖窗(用户2026-09-10):窗内不启动cross走台,掐断"锁范围外怪→空到达→清锁→左右碎步"死循环;松键等本层刷怪/重锁
            if now < getattr(self, '_no_transit_until', 0):
                self._release_combat_move()
                return
            # 打怪区域·上下闸门(用户2026-09-11改认平台绿线):人站选定上限平台=禁再向上跨层、站下限平台=禁向下跨层;
            # 只拦"新发起的跨层",已在梯上的连续攀爬由上面攀爬段处理,不在这里打断
            _bdir_ccy = _dl['target'][1] if _dl.get('target') else py_layer
            _bound_vdir = 'up' if _bdir_ccy < py_layer else ('down' if _bdir_ccy > py_layer else None)
            if _bound_vdir and self._bound_blocked_vertical(_bound_vdir):
                self._release_combat_move()
                self._rlog_throttle('bound_v_gate', "打怪区域:已到%s边界,不%s跨层" % (
                    "上" if _bound_vdir == 'up' else "下", "向上" if _bound_vdir == 'up' else "向下"), 1000, log='behavior')
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
        # 一条线直连(用户2026-09-15:删动作权仲裁器/迟滞门):距离进停步线就站定开打,不经过第三方劝架
        in_attack_range = t_dist <= stop_range
        # 【用户2026-09-10·治碎步过冲】进停步线后脸朝错,只发40ms极短方向点掰脸(不位移/不sleep/不return当帧继续站定出手,主攻前还会再点一次双保险);
        # |X差|≤15死区(怪几乎正对不掰,治几px抖动让朝向左右翻)+同目标300ms迟滞(不重复点)。
        # 旧"松键+sleep50+按住新方向120~150ms+return"会真位移跨过怪→下帧怪到另一侧再反向按=原地左右抖,已删。
        if (in_attack_range and abs(t_cx - px) > 15
                and getattr(self, '_combat_last_face_dir', None) != needed_facing
                and now - getattr(self, '_face_nudge_t', 0) > 300):
            self._release_attack_key()
            _fvk = 0x27 if needed_facing > 0 else 0x25
            self._send_win_key(_fvk, keyup=False)
            self._combat_timed_keys.append((_fvk, now + 40))
            self._combat_last_face_dir = needed_facing
            self._combat_facing = needed_facing
            self._face_nudge_t = now
            _debug_log("[面向] 进停步线脸朝%s,40ms短点掰脸(不位移) 目标X=%d 人物X=%d" % (
                "右" if needed_facing > 0 else "左", t_cx, px))
        # 上轮刚转身：等转身动画结束再打，避免转身瞬间就出手打反方向
        if now < self._combat_turn_until:
            return

        # === 跳高打（怪比人高）：区间[下限,上限]由弹窗自定义、X差在技能射程内才走-跳-打，每500~600ms跳一次；超上限由combat_step判cross走梯子 ===
        jump_key = fight_cfg.get("jump_key", "")

        # === 远处怪朝怪移动靠近 ===
        # 【用户2026-09-10】一直按住方向走到停步线(技能射程4/5)才站定;(stop_range,skill_range]这段也要持续走,
        # 旧用满技能距离当停步线→这段被判cast站定、只靠转身短按蹭=碎步不走
        effective_range = stop_range
        if not in_attack_range:   # 架构B:走近还是站定统一听仲裁(实控=R-50进/R+25出迟滞;关时in_attack_range=t_dist<=stop_range,等价原t_dist>stop_range走近)
            move_dir = "right" if t_cx > px else "left"
            # 平台硬边界(用户2026-09-07锁单平台)：勾了平台就按勾选绿线X范围,到边缘停住不走下去(半空/斜坡也稳)；没勾按当前所在平台
            if self._combat_at_locked_edge(move_dir):
                self._release_combat_move()
                return
            # 用户2026-09-11 瞬移独立规则:只填X=只水平瞬移,填了Y=能竖直瞬移,留空=该方向默认关闭;触发只看本轴距离≥设定值
            # 就直接用——水平瞬移不看Y差、竖直瞬移不看X差;一次只走一条直线、【水平优先】(和"先走近再判Y"一致:
            # 先水平闪进X射程,Y仍超才竖直,绝不斜向);水平/竖直共用850ms节流。每次瞬移登记前后坐标由_check_combat_teleport校验。
            _tp_key = fight_cfg.get("teleport_key", "")
            _tp_x = int(fight_cfg.get("teleport_distance", 0) or 0)        # X瞬移距离(空/0=关闭水平瞬移)
            _tp_y = int(fight_cfg.get("teleport_distance_y", 0) or 0)      # Y瞬移距离(空/0=关闭竖直瞬移)
            # 同一目标连续瞬移无效=暂时禁用(绑定目标,换目标自动解除),改走路/跳/梯子,不反复空闪
            _tp_blk = (now < self._combat_tp_block_until and self._combat_tp_fail_key == (t_cx, t_cy))
            # 已锁定梯子(要走梯子跨层)时战斗瞬移不介入:跨层移动归transit状态机,
            # 否则会朝锁梯方向战斗空闪(真机cross/pursue抖动中向左瞬移又闪不动,添乱)。
            _tp_ready = (bool(_tp_key) and self._climb_state == 'none'
                         and getattr(self, '_locked_ladder', None) is None
                         and not _tp_blk and now - self._combat_last_h_teleport > 850)
            _dyv = t_cy - py_layer                                        # 正=怪在人物下方,负=在上方(用落地基线,腾空不误触发竖直瞬移)
            # 打怪区域:刚从某侧越线被拉回后的冷却内,禁再朝那一侧水平瞬移(瞬移落点不可控会一步闪回竖线→再越线→再拉回死循环);
            # 冷却期落到③走路靠近,走到R-50站定距离自然停住、够不到竖线(用户2026-09-12实锤)。竖直瞬移不拦(不造成X越线)。
            _tp_bound_block = (move_dir == getattr(self, '_bound_last_side', None)
                               and now < getattr(self, '_bound_tp_block_until', 0))
            if _tp_bound_block:
                self._rlog_throttle('bound_tp_block',
                                    "打怪区域:刚从%s侧拉回,冷却内不水平瞬移、改走路靠近(防闪回线上死循环)" % move_dir,
                                    800, log='behavior')
            # ①水平优先:配了X且水平差≥X阈值→按住水平方向+瞬移(不管Y差)
            if _tp_ready and _tp_x > 0 and t_dist >= _tp_x and not _tp_bound_block:
                # 用户2026-09-05：追怪稳稳按住方向键连续走，不停顿
                self._set_combat_move(move_dir)
                # 位移检测：按住方向却没走=卡住→已登记【独占解卡】，本帧停手
                if getattr(self, '_aux_enable_unblock', True) and self._check_move_blocked(now, px, move_dir, jump_key):
                    return
                self._pre_teleport_release()   # 瞬移前先松攻击键+前摇(攻击硬直会吞瞬移),方向键保持
                self._press_game_key(_tp_key, duration=60)
                self._combat_last_h_teleport = now
                self._char_relocate_until = now + 700
                self._combat_tp_pending = {'axis': 'x', 'dir': 1 if move_dir == 'right' else -1,
                                           'sx': px, 'sy': py, 't': now, 'key': (t_cx, t_cy)}
                _debug_log("[瞬移追怪] 水平向=%s X差=%d≥%d,瞬移(不看Y)" % (move_dir, t_dist, _tp_x))
                self._combat_last_move = now
                return
            # ②水平不用闪(没配X/X已不够远/被禁用)时,配了Y且|Y差|≥Y阈值→纯竖直瞬移(松开水平不夹方向,不管X);
            #   上/下方向键定时120ms自动抬起(谁按谁松,不依赖已删除的帧末仲裁收敛,防↑/↓卡住)
            # 打怪区域·Y边界:向下瞬移时人在下限平台不闪、向上瞬移时人在上限平台不闪(用户2026-09-11:上线平台禁止再向上,补拦向上)
            if _tp_ready and _tp_y > 0 and abs(_dyv) >= _tp_y \
                    and not ((_dyv > 0 and self._bound_block_down()) or (_dyv < 0 and self._bound_block_up())):
                self._release_combat_move()
                for _hk in (VK_LEFT, VK_RIGHT):
                    if _hk in self._random_move_keys:
                        self._key_up(_hk)
                _vvk = VK_DOWN if _dyv > 0 else VK_UP
                if _vvk not in self._random_move_keys:
                    self._key_down(_vvk)
                self._combat_timed_keys = [t for t in self._combat_timed_keys if t[0] != _vvk]
                self._combat_timed_keys.append((_vvk, now + 120))
                self._pre_teleport_release()   # 瞬移前先松攻击键+前摇(攻击硬直会吞瞬移),竖直方向键保持
                self._press_game_key(_tp_key, duration=60)
                self._combat_last_h_teleport = now
                self._char_relocate_until = now + 700
                self._combat_tp_pending = {'axis': 'y', 'dir': 1 if _dyv > 0 else -1,
                                           'sx': px, 'sy': py, 't': now, 'key': (t_cx, t_cy)}
                _debug_log("[瞬移追怪] 竖直向=%s |Y差|=%d≥%d,瞬移(不看X)" % ("下" if _dyv > 0 else "上", abs(_dyv), _tp_y))
                self._combat_last_move = now
                return
            # ③都不瞬移:稳稳按住水平方向连续走(用户2026-09-05)
            self._set_combat_move(move_dir)
            # 位移检测：按住方向却没走=卡住→已登记【独占解卡】(主线下帧起暂停,由_unblock_tick向前+跳、连试上限放弃重锁)，本帧停手
            if getattr(self, '_aux_enable_unblock', True) and self._check_move_blocked(now, px, move_dir, jump_key):
                return
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
        # 跳高打判定(用户2026-09-10晚简化)：两框都填(_slope_on)即开启,【不分群攻优先/就近,统一一套就近机制】;
        # 怪比人高落在[_sj_min,_sj_max]且X差≤技能射程才"走-跳-打"。群攻模式锁定点是怪群窗中心、Y差会被平均到区间外
        # →永不触发(用户实锤),故锁定点高度不在区间时,就近在X射程内另找一只Y差正好落在区间的高处怪做跳高打参照(主锁定不变)。
        # 高处参照怪sticky钉住(用户2026-09-11):上层一排怪Y都在跳打区间时,旧逻辑每帧选"X最近"那只当参照,
        # 人物一动参照就在左右怪间跳→_hmove/出手方向左右碎步、还每帧"换新目标"清跳打节奏。改为:钉住上一只参照,
        # 只要它本帧仍被检测到(±30X/±40Y容差)、Y仍在跳打区间、X仍≤技能射程就沿用;脱检/离开区间/走远才重选X最近。
        _sref = getattr(self, '_slope_ref', None)
        _sref_ok = False
        if _sref is not None:
            for _m in (self._monsters or []):
                _mcx = (_m[0] + _m[2]) // 2
                _mcy = _m[3]
                if abs(_mcx - _sref[0]) <= 30 and abs(_mcy - _sref[1]) <= 40 \
                        and _sj_min <= (py_layer - _mcy) <= _sj_max and abs(_mcx - px) <= skill_range:
                    _sref, _sref_ok = (_mcx, _mcy), True
                    break
        if _sref_ok:
            _ref_x, _ref_y = _sref
            self._slope_ref = _sref
        else:
            _ref_x, _ref_y = t_cx, t_cy
            if not (_sj_min <= (py_layer - t_cy) <= _sj_max) or abs(t_cx - px) > skill_range:
                _best_hi = None
                for _m in (self._monsters or []):
                    _mcx = (_m[0] + _m[2]) // 2
                    _mcy = _m[3]
                    if _sj_min <= (py_layer - _mcy) <= _sj_max and abs(_mcx - px) <= skill_range:
                        if _best_hi is None or abs(_mcx - px) < abs(_best_hi[0] - px):
                            _best_hi = (_mcx, _mcy)
                if _best_hi is not None:
                    _ref_x, _ref_y = _best_hi
            self._slope_ref = (_ref_x, _ref_y)
        _above2 = py_layer - _ref_y   # 怪在人物落地基线上方多少px(正=怪上方;用基线,人跳起不误落进跳高打区间空打)
        high_slope = bool(_slope_on) and bool(self.platforms) and not getattr(self, '_combat_transit', False) \
            and now >= getattr(self, '_slope_resume_at', 0) \
            and (_sj_min <= _above2 <= _sj_max) and abs(_ref_x - px) <= skill_range  # 用户2026-09-11:X差必须<技能攻击范围才跳打(原4/5停步线)
        # 下方够不着：怪脚Y-人脚Y 超出下方攻击范围(_atk_y_down,默认30)。用户2026-09-07：下方差100+还站着打=bug,要走下去靠近而不是空打
        _below2 = (t_cy - py_layer) > _atk_y_down   # 用落地基线:人跳起时地面怪不会瞬时变"正下方"误触发下跳(用户2026-09-11)
        if not _below2:
            self._release_combat_key(VK_DOWN)  # 不在下方贴近时松开下方向键,避免残留影响走位
            self._below_down_since = 0         # 离开下方状态:清下跳按住计时,下次重新等50ms
        if _below2 and not high_slope:
            if self._bound_block_down():
                # 打怪区域·Y下限(用户2026-09-11改认平台):人在选定下限平台时绝不主动按↓+跳落层,松净↓,只水平朝怪走或站定
                self._release_combat_key(VK_DOWN)
                if VK_DOWN in self._random_move_keys:
                    self._key_up(VK_DOWN)
                self._below_down_since = 0
                if move_dir is not None and not self._combat_at_locked_edge(move_dir):
                    self._set_combat_move(move_dir)
                else:
                    self._release_combat_move()
                self._rlog_throttle('bound_down_stop', "打怪区域:已到下限平台,不发下跳(硬防)", 1000, log='behavior')
                self._combat_last_move = now
                return
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
                # 用户2026-09-11:分层已用"跳前点基线Y"(起跳冻结、整跳不变),下跳腾空不会再误判高低,
                # 故删掉旧的3秒Y冻结;防连按只靠下面 _combat_last_jump>450 的跳冷却。
                self._release_combat_move()
                self._hold_combat_key(VK_DOWN)
                # 【2026-09-09下跳时序】先按住↓≥50ms建立向下状态再按跳(同帧按=普通跳不下落,下跳0成功根因)
                if not getattr(self, '_below_down_since', 0):
                    self._below_down_since = now
                if jump_key and (now - self._below_down_since) >= 50 and now - self._combat_last_jump > 450:
                    self._press_game_key(jump_key, duration=70)
                    self._combat_last_jump = now
                    _debug_log("[下坡] 怪在正下方Y差%d,↓按住≥50ms+跳落层" % (t_cy - py_layer))
            self._combat_last_move = now
            return
        if high_slope:
            # === 跳高打(极简循环·用户2026-09-11定稿)：删4变量状态机,只要上面有怪就直接起跳→延时→攻击→延时→跳,不断循环 ===
            # 无冷却概念,只有两段节奏延时:跳后→攻击(战80~100ms/法1000±50ms),攻击后→下一跳(战280~330ms/法1000±50ms)。
            # 群攻/普通模式共用这一套(用户2026-09-11)。人物Y基点用跳前冻结基线py_layer(人跳起时Y不变,治腾空误判)。
            # 本段自管移动+跳+主攻后return,不走下方通用移动闸门与主攻。怪死/离开跳打区间→high_slope=False→else重置阶段停跳。
            self._slope_high_mode = True
            _sj_mage = bool(fight_cfg.get("slope_jump_mage"))
            _sl_atk = fight_cfg.get("atk1_key", "")
            _hmove = "right" if _ref_x > px else ("left" if _ref_x < px else None)  # 朝就近高处怪方向
            # 阶段兜底初始化(防None/空字符串)
            if getattr(self, '_slope_phase', None) not in ('wait_jump', 'wait_attack'):
                self._slope_phase = 'wait_jump'
                self._slope_next_at = 0
            # ①朝怪走(到勾选绿线边缘停住只原地跳;法师攻击前松键站定由wait_attack分支处理)
            if self._combat_at_locked_edge(_hmove):
                self._release_combat_move()  # 到绿线边缘不水平走,只原地跳上坡
            elif _hmove is not None:
                self._set_combat_move(_hmove)
                if getattr(self, '_aux_enable_unblock', True) and self._check_move_blocked(now, px, _hmove, jump_key):
                    return
            # ②极简循环:wait_jump到点→跳;wait_attack到点→攻击(出手前再核X仍在射程内才打,治离好远空打)
            if self._slope_phase == 'wait_jump' and now >= self._slope_next_at:
                # 该跳了(进入high_slope第一帧_slope_next_at=0,直接跳,不等)
                # 跳高打在原图层原地起跳、人不会出界(用户2026-09-11),故不加打怪区域上下闸门,只跨层才限
                if jump_key:
                    self._press_game_key(jump_key, duration=70)
                    self._combat_last_jump = now
                    self._slope_phase = 'wait_attack'
                    # 跳后延时(到攻击):战士80~100ms空中打;法师1000±50ms(已落地)才打
                    if _sj_mage:
                        self._slope_next_at = now + SLOPE_MAGE_HIT_MS + random.randint(-SLOPE_MAGE_JITTER, SLOPE_MAGE_JITTER)
                    else:
                        self._slope_next_at = now + random.randint(SLOPE_WAR_HIT_MIN, SLOPE_WAR_HIT_MAX)
                    self._rlog("实行跳高打·%s:怪在上方%dpx X差%d 朝%s 跳-攻循环" % (
                        "法师" if _sj_mage else "战士", _above2, abs(_ref_x - px), _hmove))
            elif self._slope_phase == 'wait_attack' and now >= self._slope_next_at:
                # 跳后延时到了,该攻击了(出手瞬间再核X:被怪撞开/没走到射程内本跳不出手,只等下一跳)
                if abs(_ref_x - px) <= skill_range:
                    if _sj_mage:
                        self._release_combat_move()   # 法师落地站定放技能
                    _fvk = VK_RIGHT if _ref_x >= px else VK_LEFT   # 出手前短点朝怪方向掰脸40ms
                    self._send_win_key(_fvk, keyup=False)
                    self._combat_timed_keys.append((_fvk, now + 40))
                    if _sl_atk:
                        self._press_game_key(_sl_atk)
                        self._attack_last["atk1"] = now
                        print("[主攻] %s 释放(跳高打·%s)" % (_sl_atk, "法师落地" if _sj_mage else "战士空中"))
                    self._combat_target_attacked = True
                    if not self._combat_first_strike_time:
                        self._combat_first_strike_time = now
                # 攻击完(或本跳射程不够跳过),进入攻击后延时,到点再跳下一轮
                self._slope_phase = 'wait_jump'
                if _sj_mage:
                    self._slope_next_at = now + SLOPE_MAGE_NEXT_MS + random.randint(-SLOPE_MAGE_JITTER, SLOPE_MAGE_JITTER)
                else:
                    self._slope_next_at = now + random.randint(SLOPE_WAR_REJUMP_MIN, SLOPE_WAR_REJUMP_MAX)
            _debug_log("[跳高打] %s Y差=%d X差=%d 阶段=%s 下一动作余%dms" % (
                "法师" if _sj_mage else "战士", _above2, abs(_ref_x - px),
                self._slope_phase, max(0, self._slope_next_at - now)))
            return   # 跳高打自管移动/跳/主攻,不走下方通用移动闸门与主攻
        else:
            self._slope_phase = 'wait_jump'   # 离开跳打区间:重置循环,下次进high_slope第一帧直接跳
            self._slope_next_at = 0
            # 平地够得着：站定"只打怪"，攻击时不按任何方向键(用户2026-09-07定稿：打怪就只打怪,不许带方向走位)。
            # 方向键只在上方 t_dist>effective_range 的pursue段(找怪/追怪)和够不着的高坡/下坡贴近段按；
            # 一旦进攻击范围够得着就松开方向站定打，这只打死/放弃进入pursue后才重新按方向去找下一只。
            self._slope_high_mode = False
            self._combat_stance_target_x = None
            self._release_combat_move()

        skill_rand = fight_cfg.get("skill_random", 50)
        skill_cast = False
        # 移动中游戏发不出技能（用户规则：跳起来可能放不出来）→ 只有站定（落地）才施法；
        # 跳高打已在上方high_slope段自管攻击并return,不会走到这,故此处统一要求站定
        if (self._combat_move_dir is not None or self._combat_held_keys):
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
            atk_cd = int(fight_cfg.get("atk1_interval", 300))  # 直接用配置值，不乘漂移
            last = self._attack_last.get("atk1", 0)
            # 攻击判定诊断(每1秒)：人物+目标坐标+X差+Y差，看距离是否算错(治"出范围还在打")
            if not hasattr(self, '_atk_diag_last') or now - self._atk_diag_last > 1000:
                self._atk_diag_last = now
                _debug_log("[攻击判定] 人物=(%d,%d) 目标=(%d,%d) X差=%d Y差=%d 射程=%d 状态=%s" % (
                    px, py_layer, t_cx, t_cy, abs(t_cx - px), abs(t_cy - py_layer), stop_range, _dl['state']))
            # 2026-09-07：主攻必须X进射程 且 Y在攻击Y范围内(怪太高/太低物理打不到就不出手,继续走跳贴近,治高处站定空打)
            # 跳高打已在上方high_slope段自管(跳→延时→攻循环)并return,此处只处理平地站定主攻。
            # 面向不再作为攻击前置条件（用户：判定不了面向，最多是空打方向不对，不能因此不打发呆）；朝向由转身逻辑保证。
            _dy_atk = t_cy - py_layer  # 主攻Y门控用落地基线:人腾空瞬时Y不决定出不出手
            _stance_ok = (self._combat_move_dir is None and not self._combat_held_keys)
            _cd_ok = (now - last > atk_cd)
            if (_stance_ok and in_attack_range   # 架构B:出手距离与走近/站定分水岭同源(实控=迟滞门;关=原t_dist<=stop_range)
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
                self._combat_target_attacked = True  # 已对锁定目标出手：空怪判定用
                if not self._combat_first_strike_time:  # 仅记首次出手，持续攻击不刷新，保证130ms窗口后空怪能被drop
                    self._combat_first_strike_time = now
                skill_cast = True
                print("[主攻] %s 释放 (目标%dpx)" % (atk_key, t_dist))

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
            # [2026-09-14 根因修复·A] 同__init__:绑定窗口优先沿用已保存裁剪框(与录制同一块内坐标系),
            # 磁盘无保存区域才三模板检测。否则每次重启/重绑都重算,实测top会抖8px、宽高抖3~4px,旧录制线整体错位。
            # 准星换窗口绑定/手动R/刷新按钮仍走强制_detect_minimap(用户主动换目标或校正,不在此函数)。
            if not self._load_region():
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
                # [CPU优化2026-09-07] 主循环只需要小地图块，直接截小地图区域，不再每帧全屏抓1280x800。
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
                    _debug_log("[主循环退出] 找不到控制面板窗口(FindWindowW/IsWindow失败),判定窗口关闭→break退出")
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
                self._seg_loop = {}        # [诊断]主循环非draw各段每秒累计耗时
            self._lk = {}                  # [诊断]本帧各段边界时间戳(dict,每帧重建)
            self._lk['cap'] = _t1_cap      # [诊断]截小地图后=帧逻辑起点
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
                if getattr(self, '_seg_loop', None):  # [诊断]主循环非draw各段每秒耗时,定位帧慢大头
                    _loop_s = " ".join("%s=%dms" % (k, v * 1000)
                                       for k, v in sorted(self._seg_loop.items()) if v > 0.0005)
                    if _loop_s:
                        _debug_log("[主循环分段] " + _loop_s)
                    self._seg_loop = {}
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
            _lkd = time.time()
            player_pos = self.find_player_dot(map_area)  # 每帧都检测光点
            self._seg_loop['1dot'] = self._seg_loop.get('1dot', 0) + time.time() - _lkd
            self._lk['after_dot'] = time.time()
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
            self._seg_loop['2read'] = self._seg_loop.get('2read', 0) + time.time() - self._lk.get('after_dot', time.time())
            self._lk['before_scale'] = time.time()
            self._update_scale_calibration()
            # 【模块B】自动记录端点已取消，改用手动同屏三点校准（不跨画面更准）
            # self._auto_calibrate_edges()

            # 打怪区域·四线编辑拖拽(照倍率X:全局左键+光标主循环轮询,不依赖cv2回调;仅编辑态生效)
            self._bound_drag_tick()
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

            # 掉台归位独占线(用户2026-09-09)：辅助线独占期间主线(_random_step/_combat_tick)一律暂停,
            # 辅助线结束(光点回台)才恢复主线——辅助线与主线同一时间只跑一个,不并行抢键
            _fall_returning = self._fall_return_tick() if getattr(self, '_aux_enable_fall', True) else False
            # 卡住解卡独占线(用户2026-09-09)：仅在没有更高优先级辅助线(掉台归位)时运行
            _unblocking = (self._unblock_tick() if not _fall_returning else False) if getattr(self, '_aux_enable_unblock', True) else False
            # 打怪区域·左右越线强制拉回(用户2026-09-11):独立守护线程实时检测,主循环帧首第一时间消费=朝内固定走1000~1500ms再松手恢复主线;
            # 掉台归位/解卡优先级更高(它们进行时本帧不拉,并清掉进行中的拉回、松朝内键,避免两套辅助线抢键)。
            # 拉回中并入_aux_busy=暂停巡路_random_step与打怪_combat_tick,不并行抢键。Y上下限是发起动作处的同步平台闸门,不在主循环占线
            if _fall_returning or _unblocking:
                if self._bound_pull is not None:
                    self._bound_pull = None
                    self._release_combat_move()
                _bound_pulling = False
            else:
                _bound_pulling = self._bound_pull_tick(time.time() * 1000)
            _aux_busy = _fall_returning or _unblocking or _bound_pulling
            # 监管线硬重置·帧首最高优先级(用户2026-09-10):监管线程独立轮询实时发现卡死、已当场松键停手并发令,
            # 主线这里(跑任何锁怪/巡路/打怪之前)第一件事统一跨线程清零;重置当帧不再跑random/combat旧决策,
            # 下一帧从"识别→锁怪→巡路→打怪"干净重来,不再等主线串行跑完慢几拍
            _hard_reset_done = self._consume_hard_reset() if not _aux_busy else False
            # 第二层横跳拉回(仅在没有辅助线独占、也没被硬重置接管时):A级锁侧/B级内部转硬重置
            _anti_jitter_done = False
            if not _aux_busy and not _hard_reset_done:
                _anti_jitter_done = self._consume_anti_jitter(time.time() * 1000)
            self._seg_loop['3misc'] = self._seg_loop.get('3misc', 0) + time.time() - self._lk.get('before_scale', time.time())
            self._lk['before_route'] = time.time()
            if not _aux_busy and not _hard_reset_done and not _anti_jitter_done:
                self._random_step(player_pos)
            self._seg_loop['4route'] = self._seg_loop.get('4route', 0) + time.time() - self._lk.get('before_route', time.time())
            self._lk['after_route'] = time.time()
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
            self._seg_loop['5premisc'] = self._seg_loop.get('5premisc', 0) + time.time() - self._lk.get('after_route', time.time())
            self._lk['before_combat'] = time.time()
            try:
                if not _aux_busy and not _hard_reset_done:
                    self._combat_tick()
            except Exception as e:
                print("[战斗] 异常:", e)
                import traceback; _debug_log("[战斗] 异常: " + str(e) + "\n" + traceback.format_exc())
            self._seg_loop['6combat'] = self._seg_loop.get('6combat', 0) + time.time() - self._lk.get('before_combat', time.time())
            self._lk['after_combat'] = time.time()
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
                               getattr(self, '_ladder_feature_window', None) is not None or
                               getattr(self, '_role_rec_window', None) is not None)
                    if has_win:
                        # 【防拖动闪退·2026-09-13】OpenCV主循环线程在跨线程手动泵Tk事件;按住左键拖动Toplevel标题栏时
                        # Windows进入模态移动循环,此刻再dooneevent并发泵同一Tcl队列(Tk非线程安全)会段错误、整程序闪退
                        # (角色识别窗一移动就崩的根因)。故左键按住期间(=正在拖窗/点控件)跳过泵事件、松开再泵,拖动交Windows独占。
                        _lb_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)  # 0x01=VK_LBUTTON
                        if not _lb_down:
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

            # 角色识别窗实时识别率:窗内不用Tk after(拖动模态循环里after嵌套Tcl会闪退),
            # 改由主循环在"左键松开=没在拖窗"时每500ms直接刷新一次控件(与Tk同一线程、非模态重入,安全)
            try:
                if getattr(self, '_role_live_do', None) is not None and \
                        getattr(self, '_role_rec_window', None) is not None and \
                        not bool(user32.GetAsyncKeyState(0x01) & 0x8000):
                    _nowv = time.time()
                    if _nowv >= getattr(self, '_role_live_next', 0.0):
                        self._role_live_next = _nowv + 0.5
                        self._role_live_do()
            except Exception:
                pass

            # === 偏移视觉反馈（游戏画面中角色匹配点+偏移点）===
            self._seg_loop['7a'] = self._seg_loop.get('7a', 0) + time.time() - self._lk.get('after_combat', time.time())
            self._lk['tk_done'] = time.time()
            try:
                self._show_offset_feedback()
            except Exception as e:
                print("[偏移反馈] 异常:", e)

            # === 透明蒙板（怪物/黄点/血条红点/蓝条蓝点统一显示）===
            # 检测结果由 _combat_tick 每350ms更新到 self._monsters / self._player_screen_pos
            # 蒙板只要窗口绑定成功就启动（不依赖_running），确保加药竖框始终可见
            if self.hwnd and not self._monster_overlay_running:
                self._start_monster_overlay()
            # 方案B:窗口绑定成功就常开截图+人物(喂角色识别框/实时识别率/加药竖框);点"开始运行"才起怪物识别+监管+边界(幂等收敛)
            self._start_detection_thread()
            if self._running:
                self._start_runtime_detection()
            # === 显示层速度外推：低帧率(6-7fps)下蒙板天然落后1帧≈160ms，按人物速度外推显示位置，
            #    绿框中心/特征点/黄点全部用外推后的显示位置，走路跟手不拖后腿。纯显示，不动匹配/搜索/打怪 ===
            self._seg_loop['7b'] = self._seg_loop.get('7b', 0) + time.time() - self._lk.get('tk_done', time.time())
            self._lk['extrap_t'] = time.time()
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
            # 新角色锚点:识别到的缩小多边形框 + 局部跟踪搜索范围框(每帧由检测线程写入,识别不到就为空)
            self._monster_overlay_data["role_anchor_polys"] = getattr(self, "_role_anchor_polys", {})
            self._monster_overlay_data["role_search_box"] = getattr(self, "_role_search_box", None)
            # 角色识别黑名单矩形(调试显示开时画红框,让人看到哪片被屏蔽);wnd_proc不能用self,走overlay_data
            self._monster_overlay_data["role_blocklist"] = \
                (self._role_rec or {}).get("blocklist", []) if self._role_rec else []
            # 黄/紫范围框直接按人物显示点几何算(不依赖B线程:上梯冻结B或未运行时也必须显示,用户2026-09-13)
            try:
                _rf0 = self._raw_frame
                _Hh, _Ww = (_rf0.shape[:2] if _rf0 is not None else (GAME_H, GAME_W))
                _Ww = min(int(_Ww), GAME_W); _Hh = min(int(_Hh), GAME_H)
                # 显示框物理边界=游戏画面(客户区)子矩形,标题栏/边框那圈不进(用户2026-09-14);取不到退回整帧
                _csub2 = getattr(self, 'client_subrect', None)
                if _csub2:
                    _px1, _py1, _px2, _py2 = int(_csub2[0]), int(_csub2[1]), int(_csub2[2]), int(_csub2[3])
                else:
                    _px1, _py1, _px2, _py2 = 0, 0, _Ww, _Hh
                _by1 = max(DETECT_TOP_MARGIN, _py1)
                _by2 = min(max(_by1 + 1, _Hh - DETECT_BOTTOM_MARGIN), _py2)
                _fcc = self._get_fight_config()
                _skr = int(_fcc.get("atk1_distance", 150) or 150)
                _yup = abs(int(_fcc.get("attack_y_up", -ATTACK_Y_UP)))
                _ydn = abs(int(_fcc.get("attack_y_down", ATTACK_Y_DOWN)))
                _fxr = int(_fcc.get("far_range_x", 0) or 0)
                _fyup = int(_fcc.get("far_range_y_up", 0) or 0)
                _fydn = int(_fcc.get("far_range_y_down", 0) or 0)
                if _disp_pos:
                    if _fxr > 0 and (_fyup > 0 or _fydn > 0):
                        _yx1, _yx2 = max(_px1, _disp_pos[0] - _fxr), min(_px2, _disp_pos[0] + _fxr)
                        _yy1 = _disp_pos[1] - _fyup if _fyup > 0 else _by1
                        _yy2 = _disp_pos[1] + _fydn if _fydn > 0 else _by2
                    else:
                        _yx1, _yx2, _yy1, _yy2 = _px1, _px2, _by1, _by2
                    _ycrop = (max(_px1, _yx1), max(_by1, _yy1), min(_px2, _yx2), min(_by2, _yy2))  # 黄=怪物识别范围
                    _fcrop = (max(_px1, _disp_pos[0] - _skr), max(_by1, _disp_pos[1] - _yup),
                              min(_px2, _disp_pos[0] + _skr), min(_by2, _disp_pos[1] + _ydn))  # 蓝=技能范围
                else:
                    _ycrop = _fcrop = None
                self._monster_overlay_data["yolo_crop"] = _ycrop
                self._monster_overlay_data["feat_crop"] = _fcrop
            except Exception:
                self._monster_overlay_data["yolo_crop"] = None
                self._monster_overlay_data["feat_crop"] = None
            # 梯子白框【常开显示】(用户2026-09-15:不按运行也要看到梯子检测,静止画面还乱跳=检测源头漂)。
            # 白框由识别B线程(运行态)/人物线程(停止态)互斥扫描写_lad_marks_cache,这里只读下发;停止态没有"选中",清掉残留红框
            if not hasattr(self, '_lad_marks_cache'):
                self._lad_marks_cache = []
            self._monster_overlay_data["ladder_marks"] = [(c[0], c[1]) for c in self._lad_marks_cache]
            if not self._running:
                self._monster_overlay_data["ladder_sel"] = None
                self._monster_overlay_data["ladder_rect"] = None
            _now_sync = time.time()
            if not hasattr(self, '_last_monster_sync_log') or _now_sync - self._last_monster_sync_log > 2:
                self._last_monster_sync_log = _now_sync
                _debug_log("[蒙板同步] 人物特征点%d个 怪物特征点%d个 怪物匹配值:%s" % (
                    len(self._char_feature_matches), len(self._monster_feature_matches),
                    str([(f[0], f[1], f[2]) for f in self._monster_feature_matches[:3]])))
            self._seg_loop['7c'] = self._seg_loop.get('7c', 0) + time.time() - self._lk.get('extrap_t', time.time())
            self._lk['runblk_t'] = time.time()
            if self._running:
                try:
                    if self._monster_overlay_data is None:
                        self._monster_overlay_data = {}
                    # 同步怪物和人物位置到蒙板
                    self._monster_overlay_data["monsters"] = self._monsters
                    self._monster_overlay_data["monster_hp_bars"] = self._monster_hp_bars
                    self._monster_overlay_data["locked_target"] = getattr(self, '_combat_locked_target', None)
                    # === 梯子选框(用户2026-09-15:不锁定,每帧实时选) ===
                    # 白框【下发蒙板】已挪到常开层(不按运行也显示,便于肉眼检查检测稳不稳);运行态这里只取最新白框供下面实时选梯
                    _now_lm = time.time() * 1000
                    if not hasattr(self, '_lad_marks_cache'):
                        self._lad_marks_cache = []
                    _white_marks = [(c[0], c[1]) for c in self._lad_marks_cache]
                    # 2) 每帧【实时】选当前要上的梯子=只认特征/YOLO白框(用户2026-09-15:不锁定、不滞回、不黏住;
                    # 人物走动镜头跟随,锁屏幕X锁不住、人梯一起滚相对距离不变=白锁,所以每帧用最新白框+最新人物位重算)
                    _sel = None
                    if getattr(self, '_climb_state', 'none') != 'none' and self._player_screen_pos:
                        try:
                            _psx, _psy = self._player_screen_pos
                            _cdir = int(getattr(self, '_climb_direction', 1) or 1)
                            _tmonx = getattr(self, '_ladder_target_mon_x', None)  # 进梯时冻结的目标怪屏幕X(固定终点,不是锁梯)
                            # 以人物为中心选梯(用户2026-09-15定稿·固定窗口,旧三点折线/容差/兜底全删):
                            # X窗口=人物左右±300内才看;上下由怪Y定——上行梯Y∈[人Y-100,人Y](头顶/平行)、下行梯Y∈[人Y,人Y+100](脚下100内);
                            # 左右由怪X定——窗口内多把选X最靠怪的(怪在哪边选哪边),X并列再Y离人最近;无冻结怪(选台/掉台)才Y靠人、X靠人。窗口空=本帧无梯。
                            if _cdir > 0:
                                _half = [(_wx, _wy) for (_wx, _wy) in _white_marks
                                         if abs(_wx - _psx) <= LADDER_PICK_X_HALF
                                         and (_psy - LADDER_PICK_UP_DY) <= _wy <= _psy]
                            else:
                                _half = [(_wx, _wy) for (_wx, _wy) in _white_marks
                                         if abs(_wx - _psx) <= LADDER_PICK_X_HALF
                                         and _psy <= _wy <= (_psy + LADDER_PICK_DOWN_DY)]
                            if _tmonx is not None:
                                _cand_all = [(abs(_wx - _tmonx), abs(_wy - _psy), _wx, _wy) for (_wx, _wy) in _half]
                            else:
                                _cand_all = [(abs(_wy - _psy), abs(_wx - _psx), _wx, _wy) for (_wx, _wy) in _half]
                            _snap = bool(_cand_all)
                            _rx = None
                            if _snap:
                                _mc = min(_cand_all, key=lambda c: (c[0], c[1]))
                                _rx, _ry = _mc[2], _mc[3]
                                self._ladder_snap_x = _rx      # 当帧选中梯真实中心X(下帧重算,不黏住),供屏幕对位起跳
                                _sel = (_rx, _ry, True)
                                # 到顶端点在进to_ladder时已由_lock_recorded_ladder_endpoints从小地图录制梯取好,
                                # 此处不再借Y(用户2026-09-15:到顶=光点Y与录制梯最上点重合)
                            else:
                                self._ladder_snap_x = None
                            if _now_lm - getattr(self, '_snap_dbg_t', 0) >= 300:
                                self._snap_dbg_t = _now_lm
                                _allx = ','.join('%d/%d' % (wx, wy) for wx, wy in _white_marks) or '无'
                                _debug_log("[实时选梯·怪X近优先人Y近] 人=(%d,%d) 怪X=%s 向%s 白框[%s]→选中X=%s" % (
                                    _psx, _psy, _tmonx, ('上' if _cdir > 0 else '下'), _allx, _rx))
                        except Exception:
                            _sel = None
                    self._monster_overlay_data["ladder_sel"] = _sel
                    self._monster_overlay_data["ladder_rect"] = None  # 旧洋红16宽全长框停用,统一为120x50红框ladder_sel
                except Exception as e:
                    print("[蒙板] 同步异常:", e)

            # === 准星拖拽绑定检测 ===
            self._seg_loop['7d'] = self._seg_loop.get('7d', 0) + time.time() - self._lk.get('runblk_t', time.time())
            self._lk['cross_t'] = time.time()
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
                    # [2026-09-14] 禁止绑定脚本自身进程窗口(控制面板PLAY AND HAPPY/各类cv2框选窗都是本进程):
                    # 准星误拖到自己面板上直接拒绝,否则截图/按键全发到脚本UI导致错乱
                    _tpid = ctypes.c_ulong(0)
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(_tpid))
                    if _tpid.value == os.getpid():
                        self._add_log("不能绑定脚本自身窗口")
                        _debug_log("[窗口绑定] 准星拖到脚本自身窗口(pid=%d hwnd=%s),已拒绝绑定" % (_tpid.value, hwnd))
                        self._drag_crosshair = False
                        self._crosshair_pos = self._crosshair_home
                        self._destroy_crosshair_window()
                        continue
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

            self._seg_loop['7e'] = self._seg_loop.get('7e', 0) + time.time() - self._lk.get('cross_t', time.time())
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

            key = cv2.waitKey(int(self._perf_val('ui_wait_ms'))) & 0xFF  # UI帧间隔按CPU性能档(快15/普通25/慢40ms);挂机面板无需高刷,战斗按键靠内部时间戳节流不受影响
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
                _debug_log("[主循环退出] 收到q/ESC键(key=%d)→break退出" % key)
                self._stop_random()
                break
            elif key == ord('r'):
                print("Redetecting...")
                self._detect_minimap()
            elif key == ord('n'):
                self.manual_select_region()
            elif key == 13 and getattr(self, '_bound_edit', False):
                # 打怪区域编辑态:回车=把暂存区点选的多个相连台子合并成一条Y界线(第1/2条,自动按Y定上下)
                self._bound_commit_group()
        # Ensure overlay is destroyed before exit
        if self._monster_overlay_running:
            self._stop_monster_overlay()
        # 人物跟踪线程已删除
        cv2.destroyAllWindows()
        _debug_log("[主循环退出] run()主循环已结束,准备退出进程")
        print("Final:", len(self.platforms), "platforms,", len(self.ladders), "ladders")



if __name__ == "__main__":
    # === 单实例锁v3（2026-09-07加固）：探测函数定义在文件顶部(重import之前)已先行执行一次，
    # 此处复用 _probe_any_instance_running 在提权前后各再查一次，彻底杜绝双实例并存。
    import ctypes as _ctypes, sys as _sys
    # 后台线程未捕获异常留痕(检测/守护线程若静默死掉,人物坐标不再更新会表现为一直走/空打;记进debug.log便于定位闪退)
    import threading as _threading, traceback as _tbmod
    def _thread_excepthook(args):
        try:
            _debug_log("[线程未捕获异常] 线程=%s %s: %s" % (
                getattr(args.thread, 'name', '?'), getattr(args.exc_type, '__name__', '?'),
                "".join(_tbmod.format_exception(args.exc_type, args.exc_value, args.exc_traceback))))
        except Exception:
            pass
    _threading.excepthook = _thread_excepthook
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
    _app = None
    try:
        _app = MinimapRouteRecorder()
        _app.run()
    except Exception as _e:
        import traceback
        _err = traceback.format_exc()
        print("[全局异常] %s" % _e)
        _debug_log("[全局异常] %s" % _err)
        _debug_log(_err)
        # 异常退出前松开全部按键(用户2026-09-10:进程闪退时若方向键正按下、没人发keyup,游戏里会一直趴着/一直走)
        try:
            if _app is not None:
                _app._release_all_keys()
        except Exception:
            pass
        try:
            import ctypes as _ct
            for _vk in (0x25, 0x26, 0x27, 0x28):  # 左右上下方向键硬松(扩展键|KEYUP),不管哪套键按着都松开
                _ct.windll.user32.keybd_event(_vk, _ct.windll.user32.MapVirtualKeyW(_vk, 0), 0x0001 | 0x0002, 0)
        except Exception:
            pass
        # 异常后等待3秒让用户看到错误，然后退出（避免input卡住表现为未响应）
        import time
        time.sleep(3)

