"""
核心状态机模块
整合所有子系统，驱动挂机主循环:
  感知(YOLO检测) → 定位 → 决策 → 执行(攻击/移动/技能/药品) → 循环

状态:
  IDLE:      空闲/暂停
  SEARCHING: 搜索怪物
  MOVING:    向怪物移动
  ATTACKING: 攻击中
  PATHING:   切换平台中（跳/爬梯子）
  RECORDING_PLATFORM: 录制平台中
  RECORDING_LADDER:   录制梯子中
"""
import time
import threading
import ctypes
from enum import Enum

from core.detector import YoloDetector
from core.locator import ObjectLocator
from core.decision import CombatDecision, ActionType
from core.controller import InputController
from core.platform import PlatformManager
from core.ladder import LadderManager
from core.pathfinder import PathFinder, TravelMethod
from core.skill import SkillManager
from core.potion import PotionManager
from core.player_tracker import PlayerTracker
from utils.capture import ScreenCapture
from config.config_loader import Config


class BotState(Enum):
    IDLE = "idle"
    SEARCHING = "searching"
    MOVING = "moving"
    ATTACKING = "attacking"
    PATHING = "pathing"
    RECORDING_PLATFORM = "recording_platform"
    RECORDING_LADDER = "recording_ladder"


class GameBot:
    """游戏挂机主类"""

    def __init__(self):
        self.config = Config()
        self.state = BotState.IDLE
        self.running = False
        self._thread = None
        self._stop_event = threading.Event()

        # 初始化各子系统
        self._init_subsystems()

        # 回调（UI层可注册）
        self.on_state_change = None
        self.on_detect = None       # 每帧检测结果回调
        self.on_log = None          # 日志回调

    def _init_subsystems(self):
        """初始化所有子系统"""
        cfg = self.config

        # 截图
        region = cfg.get("game.capture_region")
        self.capture = ScreenCapture(region=region)

        # YOLO 检测器
        yolo_cfg = cfg.get("yolo", {})
        self.detector = YoloDetector(
            model_path=yolo_cfg.get("model_path", "data/models/best.pt"),
            confidence=yolo_cfg.get("confidence", 0.5),
            iou_threshold=yolo_cfg.get("iou_threshold", 0.45),
            device=yolo_cfg.get("device", "cpu"),
            class_names=yolo_cfg.get("class_names", {})
        )

        # 定位器
        self.locator = ObjectLocator(
            platform_y_threshold=cfg.get("combat.platform_y_threshold", 30)
        )

        # 人物模板匹配追踪器（不依赖YOLO，手动截特征图定位）
        self.player_tracker = PlayerTracker(
            templates_dir="data/templates",
            match_threshold=cfg.get("player_tracker.match_threshold", 0.7)
        )
        # 人物定位模式: "template" 模板匹配, "yolo" YOLO检测, "auto" 优先模板
        self.player_loc_mode = cfg.get("player_tracker.mode", "auto")

        # 控制器（必须在技能管理器之前初始化）
        window_title = cfg.get("game.window_title", "冒险岛怀旧服")
        input_method = cfg.get("game.input_method", "auto")
        game_hwnd = ctypes.windll.user32.FindWindowW(None, window_title)
        self.controller = InputController(game_hwnd=game_hwnd, input_method=input_method)
        if game_hwnd:
            print(f"[Bot] Game window found: {window_title} (hwnd={game_hwnd})")
        else:
            print(f"[Bot] WARNING: Game window not found: {window_title}")
        print(f"[Bot] Input method: {input_method}")

        # 技能管理（先初始化，决策器需要引用）
        self.skill_mgr = SkillManager(self.controller)
        skills_cfg = cfg.get("skills", [])
        if skills_cfg:
            self.skill_mgr.load_from_config(skills_cfg)

        # 决策器（攻击范围由技能管理器动态提供）
        self.decision = CombatDecision(
            platform_y_threshold=cfg.get("combat.platform_y_threshold", 30),
            skill_manager=self.skill_mgr
        )

        # 平台/梯子管理
        self.platform_mgr = PlatformManager(
            save_path=cfg.get("platforms_file", "data/platforms.json")
        )
        self.ladder_mgr = LadderManager(
            save_path=cfg.get("ladders_file", "data/ladders.json")
        )

        # 路径选择
        pf_cfg = cfg.get("pathfinding", {})
        self.pathfinder = PathFinder(
            platform_manager=self.platform_mgr,
            ladder_manager=self.ladder_mgr,
            jump_height_threshold=pf_cfg.get("jump_height_threshold", 120),
            prefer_ladder_height=pf_cfg.get("prefer_ladder_height", 200),
            ladder_climb_time_per_100px=pf_cfg.get("ladder_climb_time_per_100px", 1.0),
            jump_time=pf_cfg.get("jump_time", 0.8)
        )

        # 药品管理
        pot_cfg = cfg.get("potions", {})
        self.potion_mgr = PotionManager(
            controller=self.controller,
            hp_threshold=pot_cfg.get("hp_threshold", 30),
            mp_threshold=pot_cfg.get("mp_threshold", 20),
            hp_key=pot_cfg.get("hp_key", "q"),
            mp_key=pot_cfg.get("mp_key", "w"),
            hp_bar_region=pot_cfg.get("hp_bar_region", [10, 10, 200, 20]),
            mp_bar_region=pot_cfg.get("mp_bar_region", [10, 35, 200, 20]),
            hp_color=pot_cfg.get("hp_color", [255, 0, 0]),
            mp_color=pot_cfg.get("mp_color", [0, 0, 255])
        )

        # 运行统计
        self.stats = {
            "start_time": None,
            "attack_count": 0,
            "monster_killed_estimate": 0,
            "frames_processed": 0,
        }

    def _log(self, msg):
        print(f"[Bot] {msg}")
        if self.on_log:
            self.on_log(msg)

    def _set_state(self, state):
        if self.state != state:
            self.state = state
            if self.on_state_change:
                self.on_state_change(state)

    # ========== 主循环 ==========

    def start(self):
        """启动挂机（在后台线程运行）"""
        if self.running:
            return

        # 加载YOLO模型（失败不阻止启动，人物可用模板匹配定位）
        yolo_ready = False
        if not self.detector.is_loaded():
            try:
                self.detector.load_model()
                yolo_ready = True
            except Exception as e:
                self._log(f"YOLO模型加载失败: {e}")
                self._log("怪物检测暂不可用，但人物模板匹配仍可工作。")

        # 检查人物定位是否可用
        if not yolo_ready and not self.player_tracker.has_templates:
            self._log("警告: 既无YOLO模型也无人物模板，无法定位人物！")
            self._log("请先在「人物」面板截取人物特征图，或放置YOLO模型。")

        self.running = True
        self._stop_event.clear()
        self.stats["start_time"] = time.time()
        self._set_state(BotState.SEARCHING)
        self._log("挂机开始")

        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止挂机"""
        self.running = False
        self._stop_event.set()
        self.controller.release_all()
        self._set_state(BotState.IDLE)
        self._log("挂机停止")
        if self._thread:
            self._thread.join(timeout=2)

    def _main_loop(self):
        """主循环"""
        fps = self.config.get("game.fps", 30)
        frame_interval = 1.0 / fps

        while not self._stop_event.is_set():
            loop_start = time.time()

            try:
                self._tick()
            except Exception as e:
                self._log(f"循环异常: {e}")
                time.sleep(0.5)

            # 控制帧率
            elapsed = time.time() - loop_start
            sleep_time = max(0, frame_interval - elapsed)
            time.sleep(sleep_time)

    def _tick(self):
        """单帧处理"""
        # 1. 截图
        frame = self.capture.capture()
        self.stats["frames_processed"] += 1

        # 2. 人物定位（优先模板匹配，不依赖YOLO）
        player_found = False
        if self.player_loc_mode in ("template", "auto") and self.player_tracker.has_templates:
            track_result = self.player_tracker.track(frame)
            if track_result:
                self.locator.set_player_position(
                    pos=track_result["center"],
                    direction=track_result["direction"],
                    confidence=track_result["confidence"]
                )
                player_found = True

        # 3. YOLO 检测（怪物/梯子；人物由模板匹配负责时跳过player类）
        detections = []
        if self.detector.is_loaded():
            try:
                detections = self.detector.detect(frame)
            except Exception as e:
                self._log(f"YOLO检测异常: {e}")

        # 更新定位（人物已由模板匹配设置，这里include_player=False）
        self.locator.update(detections, include_player=not player_found)

        # 回调给UI
        if self.on_detect:
            self.on_detect(frame, detections, self.locator)

        # 4. 检查药品（每帧都检查）
        self.potion_mgr.check_and_use_potions(frame)

        # 5. 检查BUFF
        self.skill_mgr.check_and_use_buffs()

        # 6. 根据状态处理
        if self.state == BotState.RECORDING_PLATFORM:
            self._tick_recording_platform()
        elif self.state == BotState.RECORDING_LADDER:
            self._tick_recording_ladder()
        else:
            self._tick_combat()

    def _tick_combat(self):
        """战斗逻辑"""
        if not self.locator.has_player():
            self._set_state(BotState.SEARCHING)
            return

        # 过滤：只打已记录平台上的怪（如果有记录的话）
        if self.platform_mgr.platforms:
            filtered = self.platform_mgr.filter_monsters_on_platforms(
                self.locator.monsters
            )
            # 临时替换 locator 的怪物列表（只在决策时用）
            original_monsters = self.locator.monsters
            self.locator.monsters = filtered

        # 决策
        result = self.decision.decide(self.locator)

        # 恢复原始怪物列表
        if self.platform_mgr.platforms:
            self.locator.monsters = original_monsters

        action = result["action"]

        # 执行动作
        if action == ActionType.ATTACK:
            self._set_state(BotState.ATTACKING)
            # 释放所有就绪且在范围内的攻击技能（按优先级）
            target_h_dist = result["target"]["h_dist"] if result.get("target") else None
            used = self.skill_mgr.do_attacks(monster_distance=target_h_dist)
            self.stats["attack_count"] += used

        elif action == ActionType.MOVE_LEFT:
            self._set_state(BotState.MOVING)
            left_key = self.config.get("combat.left_key", "a")
            self.controller.hold_key(left_key, 0.1)

        elif action == ActionType.MOVE_RIGHT:
            self._set_state(BotState.MOVING)
            right_key = self.config.get("combat.right_key", "d")
            self.controller.hold_key(right_key, 0.1)

        elif action == ActionType.JUMP:
            self._set_state(BotState.PATHING)
            # 使用配置的跳跃技能
            if not self.skill_mgr.do_jump():
                # 没有配置跳跃技能时，用默认alt键
                self.controller.jump("alt")

        elif action == ActionType.TELEPORT:
            self._set_state(BotState.PATHING)
            # 使用配置的瞬移技能
            if not self.skill_mgr.do_teleport():
                # 没有配置瞬移技能时，用默认e键
                self.controller.press_key("e")

        elif action == ActionType.CLIMB_UP:
            self._set_state(BotState.PATHING)
            up_key = self.config.get("combat.up_key", "w")
            self.controller.hold_key(up_key, 0.2)

        elif action == ActionType.CLIMB_DOWN:
            self._set_state(BotState.PATHING)
            down_key = self.config.get("combat.down_key", "s")
            self.controller.hold_key(down_key, 0.2)

        elif action == ActionType.SEARCH:
            self._set_state(BotState.SEARCHING)
            self._search_pattern()

        else:
            self._set_state(BotState.IDLE)

    def _search_pattern(self):
        """简单的搜索模式：左右来回走"""
        t = time.time()
        left_key = self.config.get("combat.left_key", "a")
        right_key = self.config.get("combat.right_key", "d")
        if int(t * 2) % 2 == 0:
            self.controller.hold_key(left_key, 0.2)
        else:
            self.controller.hold_key(right_key, 0.2)

    # ========== 录制功能 ==========

    def start_platform_recording(self):
        """开始录制平台（人物定位优先用模板匹配）"""
        # 尝试加载YOLO（失败不阻止，模板匹配可定位人物）
        if not self.detector.is_loaded():
            try:
                self.detector.load_model()
            except Exception as e:
                self._log(f"YOLO模型加载失败: {e}，使用模板匹配定位人物")

        if not self.player_tracker.has_templates and not self.detector.is_loaded():
            self._log("无法定位人物：请先截取人物特征图或放置YOLO模型")
            return

        self.platform_mgr.start_recording()
        self._set_state(BotState.RECORDING_PLATFORM)
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()

    def stop_platform_recording(self):
        """停止录制平台"""
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        new_platforms = self.platform_mgr.stop_recording()
        self._set_state(BotState.IDLE)
        return new_platforms

    def start_ladder_recording(self):
        """开始录制梯子（人物定位优先用模板匹配）"""
        if not self.detector.is_loaded():
            try:
                self.detector.load_model()
            except Exception as e:
                self._log(f"YOLO模型加载失败: {e}，使用模板匹配定位人物")

        if not self.player_tracker.has_templates and not self.detector.is_loaded():
            self._log("无法定位人物：请先截取人物特征图或放置YOLO模型")
            return

        self.ladder_mgr.start_recording()
        self._set_state(BotState.RECORDING_LADDER)
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()

    def stop_ladder_recording(self):
        """停止录制梯子"""
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        new_ladders = self.ladder_mgr.stop_recording()
        self._set_state(BotState.IDLE)
        return new_ladders

    def _tick_recording_platform(self):
        """录制平台时的帧处理"""
        if self.locator.has_player():
            x, y = self.locator.player_pos
            self.platform_mgr.record_point(x, y)

    def _tick_recording_ladder(self):
        """录制梯子时的帧处理"""
        if self.locator.has_player():
            x, y = self.locator.player_pos
            self.ladder_mgr.record_point(x, y)

    # ========== 状态查询 ==========

    def get_runtime_info(self):
        """获取运行时信息（供UI显示）"""
        elapsed = 0
        if self.stats["start_time"]:
            elapsed = time.time() - self.stats["start_time"]

        return {
            "state": self.state.value,
            "running": self.running,
            "player_pos": self.locator.player_pos,
            "monster_count": len(self.locator.monsters),
            "platform_count": len(self.platform_mgr.platforms),
            "ladder_count": len(self.ladder_mgr.ladders),
            "elapsed": elapsed,
            "attack_count": self.stats["attack_count"],
            "frames": self.stats["frames_processed"],
            "hp_potions": self.potion_mgr.hp_potion_count,
            "mp_potions": self.potion_mgr.mp_potion_count,
        }
