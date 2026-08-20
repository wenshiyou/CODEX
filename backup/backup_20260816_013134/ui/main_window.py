"""
PyQt5 切换式主面板
Tab 结构:
  1. 攻击 - 攻击范围、主攻技能、开启/暂停、运行状态
  2. 路线 - 平台录制、梯子录制、已记录列表、小地图预览
  3. 技能 - BUFF技能列表、药品BUFF、技能配置
  4. 药品 - 红药/蓝药阈值、键位、血条区域校准
  5. 设置 - YOLO模型路径、截图区域、游戏窗口、检测参数
  6. 小地图 - 独立窗口开关、坐标映射校准
"""
import sys
import time
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QCheckBox, QGroupBox, QListWidget, QListWidgetItem, QTextEdit,
    QGridLayout, QSlider, QMessageBox, QFrame, QDialog, QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, QEvent, QRect, QPoint, QSize
from PyQt5.QtGui import QFont, QColor, QPalette, QKeyEvent, QPixmap, QImage, QPainter, QPen

from core.bot import GameBot, BotState
from ui.minimap_window import MinimapWindow


# Qt键码到字符串的映射（用于键位录制）
QT_KEY_MAP = {
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
    Qt.Key_Escape: "esc", Qt.Key_Tab: "tab", Qt.Key_Backspace: "backspace",
    Qt.Key_Shift: "shift", Qt.Key_Control: "ctrl", Qt.Key_Alt: "alt",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
    Qt.Key_F1: "f1", Qt.Key_F2: "f2", Qt.Key_F3: "f3", Qt.Key_F4: "f4",
    Qt.Key_F5: "f5", Qt.Key_F6: "f6", Qt.Key_F7: "f7", Qt.Key_F8: "f8",
    Qt.Key_F9: "f9", Qt.Key_F10: "f10", Qt.Key_F11: "f11", Qt.Key_F12: "f12",
    Qt.Key_0: "0", Qt.Key_1: "1", Qt.Key_2: "2", Qt.Key_3: "3", Qt.Key_4: "4",
    Qt.Key_5: "5", Qt.Key_6: "6", Qt.Key_7: "7", Qt.Key_8: "8", Qt.Key_9: "9",
}


class KeyCaptureLineEdit(QLineEdit):
    """
    键位录制输入框
    点击获得焦点后，按下键盘任意键自动录入键名
    支持字母、数字、功能键、方向键、Ctrl/Alt/Shift/Space等
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("点击后按键盘录入键位")
        self.setReadOnly(True)
        self._capturing = False
        self.setStyleSheet("""
            QLineEdit {
                background-color: #2d2d2d;
                border: 1px solid #555;
                padding: 4px;
                border-radius: 3px;
            }
            QLineEdit:focus {
                border: 2px solid #2196F3;
                background-color: #1e3a5f;
            }
        """)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._capturing = True
        self.setText("按下任意键...")
        self.setStyleSheet("""
            QLineEdit {
                background-color: #1e3a5f;
                border: 2px solid #2196F3;
                padding: 4px;
                border-radius: 3px;
                color: #2196F3;
            }
        """)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._capturing = False
        if self.text() == "按下任意键...":
            self.setText("")
        self.setStyleSheet("""
            QLineEdit {
                background-color: #2d2d2d;
                border: 1px solid #555;
                padding: 4px;
                border-radius: 3px;
            }
        """)

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return

        key = event.key()
        # 映射键名
        if key in QT_KEY_MAP:
            key_name = QT_KEY_MAP[key]
        elif Qt.Key_A <= key <= Qt.Key_Z:
            key_name = chr(key).lower()
        else:
            # 其他键尝试用文本
            text = event.text().lower()
            if text:
                key_name = text
            else:
                key_name = f"key_{key}"

        self.setText(key_name)
        self._capturing = False
        # 录制完成后清除焦点
        self.clearFocus()


class RegionSelectDialog(QDialog):
    """
    截图区域框选对话框
    显示全屏截图，用户用鼠标拖拽框选区域，确认后返回裁剪的图像
    """
    def __init__(self, frame_np, parent=None):
        """
        Args:
            frame_np: numpy BGR 图像（全屏截图）
        """
        super().__init__(parent)
        self.setWindowTitle("框选人物特征区域 - 拖拽鼠标选择，回车确认，ESC取消")
        self.frame_np = frame_np
        self.selected_rect = None
        self._start_pos = None
        self._end_pos = None
        self._dragging = False

        # 转换为QPixmap显示
        h, w = frame_np.shape[:2]
        # 缩放显示（如果屏幕太大）
        self.scale = min(1.0, 1400 / w, 800 / h)
        self.display_w = int(w * self.scale)
        self.display_h = int(h * self.scale)

        rgb = cv2.cvtColor(frame_np, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        self.pixmap = QPixmap.fromImage(qimg).scaled(
            self.display_w, self.display_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        self.setFixedSize(self.display_w + 20, self.display_h + 60)

        layout = QVBoxLayout(self)
        self.image_label = QLabel()
        self.image_label.setPixmap(self.pixmap)
        self.image_label.setFixedSize(self.display_w, self.display_h)
        self.image_label.setMouseTracking(True)
        self.image_label.installEventFilter(self)
        layout.addWidget(self.image_label)

        btn_layout = QHBoxLayout()
        self.hint_label = QLabel("拖拽鼠标框选人物特征区域（建议选头部或身体有辨识度的部分）")
        btn_layout.addWidget(self.hint_label)
        btn_layout.addStretch()
        btn_ok = QPushButton("确认 (Enter)")
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel = QPushButton("取消 (Esc)")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def eventFilter(self, obj, event):
        if obj == self.image_label:
            if event.type() == QEvent.MouseButtonPress:
                self._start_pos = event.pos()
                self._dragging = True
                self._end_pos = event.pos()
                self._update_display()
                return True
            elif event.type() == QEvent.MouseMove and self._dragging:
                self._end_pos = event.pos()
                self._update_display()
                return True
            elif event.type() == QEvent.MouseButtonRelease:
                self._end_pos = event.pos()
                self._dragging = False
                self._update_display()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self._on_ok()
        elif event.key() == Qt.Key_Escape:
            self.reject()

    def _update_display(self):
        if self._start_pos and self._end_pos:
            pix = self.pixmap.copy()
            painter = QPainter(pix)
            pen = QPen(QColor(0, 255, 0), 2)
            painter.setPen(pen)
            x = min(self._start_pos.x(), self._end_pos.x())
            y = min(self._start_pos.y(), self._end_pos.y())
            w = abs(self._end_pos.x() - self._start_pos.x())
            h = abs(self._end_pos.y() - self._start_pos.y())
            painter.drawRect(x, y, w, h)
            painter.end()
            self.image_label.setPixmap(pix)

    def _on_ok(self):
        if not self._start_pos or not self._end_pos:
            QMessageBox.warning(self, "提示", "请先框选一个区域")
            return
        x1 = min(self._start_pos.x(), self._end_pos.x())
        y1 = min(self._start_pos.y(), self._end_pos.y())
        x2 = max(self._start_pos.x(), self._end_pos.x())
        y2 = max(self._start_pos.y(), self._end_pos.y())
        if x2 - x1 < 5 or y2 - y1 < 5:
            QMessageBox.warning(self, "提示", "框选区域太小")
            return
        # 转换回原图坐标
        self.selected_rect = (
            int(x1 / self.scale), int(y1 / self.scale),
            int(x2 / self.scale), int(y2 / self.scale)
        )
        self.accept()

    def get_cropped_image(self):
        """获取裁剪后的图像（numpy BGR）"""
        if not self.selected_rect:
            return None
        x1, y1, x2, y2 = self.selected_rect
        return self.frame_np[y1:y2, x1:x2].copy()


class AttackTab(QWidget):
    """攻击面板"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 运行控制
        ctrl_group = QGroupBox("运行控制")
        ctrl_layout = QHBoxLayout()

        self.btn_start = QPushButton("开始挂机")
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-size: 16px; padding: 10px;")
        self.btn_start.clicked.connect(self._on_start)

        self.btn_stop = QPushButton("停止挂机")
        self.btn_stop.setStyleSheet("background-color: #f44336; color: white; font-size: 16px; padding: 10px;")
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.setEnabled(False)

        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        ctrl_group.setLayout(ctrl_layout)
        layout.addWidget(ctrl_group)

        # 攻击参数
        param_group = QGroupBox("攻击参数")
        param_layout = QGridLayout()

        param_layout.addWidget(QLabel("当前攻击范围(px):"), 0, 0)
        self.label_attack_range = QLabel("150")
        self.label_attack_range.setStyleSheet("color: #4CAF50; font-weight: bold;")
        param_layout.addWidget(self.label_attack_range, 0, 1)

        param_layout.addWidget(QLabel("(由攻击技能最大距离决定)"), 0, 2)

        param_layout.addWidget(QLabel("平台垂直阈值(px):"), 1, 0)
        self.spin_platform_thresh = QSpinBox()
        self.spin_platform_thresh.setRange(5, 100)
        self.spin_platform_thresh.setValue(self.bot.config.get("combat.platform_y_threshold", 30))
        param_layout.addWidget(self.spin_platform_thresh, 1, 1)

        param_layout.addWidget(QLabel("移动方向键:"), 2, 0)
        dir_layout = QHBoxLayout()
        self.edit_left_key = KeyCaptureLineEdit()
        self.edit_left_key.setText(self.bot.config.get("combat.left_key", "a"))
        self.edit_left_key.setMaximumWidth(80)
        self.edit_right_key = KeyCaptureLineEdit()
        self.edit_right_key.setText(self.bot.config.get("combat.right_key", "d"))
        self.edit_right_key.setMaximumWidth(80)
        dir_layout.addWidget(QLabel("左:"))
        dir_layout.addWidget(self.edit_left_key)
        dir_layout.addWidget(QLabel("右:"))
        dir_layout.addWidget(self.edit_right_key)
        param_layout.addLayout(dir_layout, 2, 1)

        param_layout.addWidget(QLabel("上下键:"), 3, 0)
        ud_layout = QHBoxLayout()
        self.edit_up_key = KeyCaptureLineEdit()
        self.edit_up_key.setText(self.bot.config.get("combat.up_key", "w"))
        self.edit_up_key.setMaximumWidth(80)
        self.edit_down_key = KeyCaptureLineEdit()
        self.edit_down_key.setText(self.bot.config.get("combat.down_key", "s"))
        self.edit_down_key.setMaximumWidth(80)
        ud_layout.addWidget(QLabel("上:"))
        ud_layout.addWidget(self.edit_up_key)
        ud_layout.addWidget(QLabel("下:"))
        ud_layout.addWidget(self.edit_down_key)
        param_layout.addLayout(ud_layout, 3, 1)

        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # 运行状态
        status_group = QGroupBox("运行状态")
        status_layout = QGridLayout()

        self.label_state = QLabel("状态: 空闲")
        self.label_state.setStyleSheet("font-size: 14px; font-weight: bold;")
        status_layout.addWidget(self.label_state, 0, 0, 1, 2)

        self.label_player = QLabel("人物位置: --")
        status_layout.addWidget(self.label_player, 1, 0)

        self.label_monsters = QLabel("怪物数量: 0")
        status_layout.addWidget(self.label_monsters, 1, 1)

        self.label_elapsed = QLabel("运行时长: 0s")
        status_layout.addWidget(self.label_elapsed, 2, 0)

        self.label_attacks = QLabel("攻击次数: 0")
        status_layout.addWidget(self.label_attacks, 2, 1)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        layout.addStretch()

    def _on_start(self):
        self.bot.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _on_stop(self):
        self.bot.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def update_status(self):
        info = self.bot.get_runtime_info()
        self.label_state.setText(f"状态: {info['state']}")
        if info['player_pos']:
            self.label_player.setText(f"人物: ({info['player_pos'][0]:.0f}, {info['player_pos'][1]:.0f})")
        self.label_monsters.setText(f"怪物: {info['monster_count']}")
        self.label_elapsed.setText(f"时长: {info['elapsed']:.0f}s")
        self.label_attacks.setText(f"攻击: {info['attack_count']}")
        # 动态显示当前攻击范围（由技能最大距离决定）
        current_range = self.bot.skill_mgr.get_max_attack_range()
        self.label_attack_range.setText(f"{current_range:.0f}")


class RouteTab(QWidget):
    """路线面板"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 平台录制
        plat_group = QGroupBox("平台录制")
        plat_layout = QVBoxLayout()

        plat_desc = QLabel("点击开始后，控制人物在目标平台上走一遍，程序会自动记录平台范围。")
        plat_desc.setWordWrap(True)
        plat_layout.addWidget(plat_desc)

        plat_btn_layout = QHBoxLayout()
        self.btn_plat_start = QPushButton("开始录制平台")
        self.btn_plat_start.setStyleSheet("background-color: #2196F3; color: white; padding: 8px;")
        self.btn_plat_start.clicked.connect(self._on_plat_start)
        self.btn_plat_stop = QPushButton("停止录制")
        self.btn_plat_stop.setStyleSheet("background-color: #FF9800; color: white; padding: 8px;")
        self.btn_plat_stop.clicked.connect(self._on_plat_stop)
        self.btn_plat_stop.setEnabled(False)
        plat_btn_layout.addWidget(self.btn_plat_start)
        plat_btn_layout.addWidget(self.btn_plat_stop)
        plat_layout.addLayout(plat_btn_layout)

        self.label_plat_count = QLabel("已记录平台: 0 个")
        plat_layout.addWidget(self.label_plat_count)

        self.list_platforms = QListWidget()
        plat_layout.addWidget(self.list_platforms)

        plat_del_layout = QHBoxLayout()
        self.btn_plat_del = QPushButton("删除选中平台")
        self.btn_plat_del.clicked.connect(self._on_plat_delete)
        self.btn_plat_clear = QPushButton("清空全部")
        self.btn_plat_clear.clicked.connect(self._on_plat_clear)
        plat_del_layout.addWidget(self.btn_plat_del)
        plat_del_layout.addWidget(self.btn_plat_clear)
        plat_layout.addLayout(plat_del_layout)

        plat_group.setLayout(plat_layout)
        layout.addWidget(plat_group)

        # 梯子录制
        ladder_group = QGroupBox("梯子录制")
        ladder_layout = QVBoxLayout()

        ladder_desc = QLabel("点击开始后，控制人物爬一遍目标梯子，程序会自动记录梯子位置。")
        ladder_desc.setWordWrap(True)
        ladder_layout.addWidget(ladder_desc)

        ladder_btn_layout = QHBoxLayout()
        self.btn_ladder_start = QPushButton("开始录制梯子")
        self.btn_ladder_start.setStyleSheet("background-color: #2196F3; color: white; padding: 8px;")
        self.btn_ladder_start.clicked.connect(self._on_ladder_start)
        self.btn_ladder_stop = QPushButton("停止录制")
        self.btn_ladder_stop.setStyleSheet("background-color: #FF9800; color: white; padding: 8px;")
        self.btn_ladder_stop.clicked.connect(self._on_ladder_stop)
        self.btn_ladder_stop.setEnabled(False)
        ladder_btn_layout.addWidget(self.btn_ladder_start)
        ladder_btn_layout.addWidget(self.btn_ladder_stop)
        ladder_layout.addLayout(ladder_btn_layout)

        self.label_ladder_count = QLabel("已记录梯子: 0 个")
        ladder_layout.addWidget(self.label_ladder_count)

        self.list_ladders = QListWidget()
        ladder_layout.addWidget(self.list_ladders)

        ladder_del_layout = QHBoxLayout()
        self.btn_ladder_del = QPushButton("删除选中梯子")
        self.btn_ladder_del.clicked.connect(self._on_ladder_delete)
        self.btn_ladder_clear = QPushButton("清空全部")
        self.btn_ladder_clear.clicked.connect(self._on_ladder_clear)
        ladder_del_layout.addWidget(self.btn_ladder_del)
        ladder_del_layout.addWidget(self.btn_ladder_clear)
        ladder_layout.addLayout(ladder_del_layout)

        ladder_group.setLayout(ladder_layout)
        layout.addWidget(ladder_group)

        self.refresh_lists()

    def _on_plat_start(self):
        self.bot.start_platform_recording()
        self.btn_plat_start.setEnabled(False)
        self.btn_plat_stop.setEnabled(True)

    def _on_plat_stop(self):
        self.bot.stop_platform_recording()
        self.btn_plat_start.setEnabled(True)
        self.btn_plat_stop.setEnabled(False)
        self.refresh_lists()

    def _on_ladder_start(self):
        self.bot.start_ladder_recording()
        self.btn_ladder_start.setEnabled(False)
        self.btn_ladder_stop.setEnabled(True)

    def _on_ladder_stop(self):
        self.bot.stop_ladder_recording()
        self.btn_ladder_start.setEnabled(True)
        self.btn_ladder_stop.setEnabled(False)
        self.refresh_lists()

    def _on_plat_delete(self):
        item = self.list_platforms.currentItem()
        if item:
            pid = item.data(Qt.UserRole)
            self.bot.platform_mgr.remove_platform(pid)
            self.refresh_lists()

    def _on_plat_clear(self):
        reply = QMessageBox.question(self, "确认", "确定清空所有平台记录？")
        if reply == QMessageBox.Yes:
            self.bot.platform_mgr.clear()
            self.refresh_lists()

    def _on_ladder_delete(self):
        item = self.list_ladders.currentItem()
        if item:
            lid = item.data(Qt.UserRole)
            self.bot.ladder_mgr.remove_ladder(lid)
            self.refresh_lists()

    def _on_ladder_clear(self):
        reply = QMessageBox.question(self, "确认", "确定清空所有梯子记录？")
        if reply == QMessageBox.Yes:
            self.bot.ladder_mgr.clear()
            self.refresh_lists()

    def refresh_lists(self):
        self.list_platforms.clear()
        for p in self.bot.platform_mgr.platforms:
            item = QListWidgetItem(
                f"平台{p.id}: x=[{p.x_min:.0f}, {p.x_max:.0f}], y={p.y_base:.0f}"
            )
            item.setData(Qt.UserRole, p.id)
            self.list_platforms.addItem(item)
        self.label_plat_count.setText(f"已记录平台: {len(self.bot.platform_mgr.platforms)} 个")

        self.list_ladders.clear()
        for l in self.bot.ladder_mgr.ladders:
            item = QListWidgetItem(
                f"梯子{l.id}: x={l.x:.0f}, y=[{l.y_top:.0f}, {l.y_bottom:.0f}]"
            )
            item.setData(Qt.UserRole, l.id)
            self.list_ladders.addItem(item)
        self.label_ladder_count.setText(f"已记录梯子: {len(self.bot.ladder_mgr.ladders)} 个")


class SkillTab(QWidget):
    """技能面板 - 四大类（攻击/BUFF/跳跃/瞬移），键位点击录制"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self._build_ui()
        self._refresh_all()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 顶部说明
        tip = QLabel("提示：点击键位输入框后，直接按键盘即可自动录入键位。")
        tip.setStyleSheet("color: #FF9800; padding: 5px;")
        layout.addWidget(tip)

        # 子Tab：四大类
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setStyleSheet("""
            QTabBar::tab { padding: 6px 16px; font-size: 13px; }
            QTabBar::tab:selected { background-color: #FF9800; color: white; }
        """)

        self.attack_page = self._build_attack_page()
        self.buff_page = self._build_buff_page()
        self.jump_page = self._build_jump_page()
        self.teleport_page = self._build_teleport_page()

        self.sub_tabs.addTab(self.attack_page, "攻击技能")
        self.sub_tabs.addTab(self.buff_page, "BUFF技能")
        self.sub_tabs.addTab(self.jump_page, "跳跃技能")
        self.sub_tabs.addTab(self.teleport_page, "瞬移技能")
        layout.addWidget(self.sub_tabs)

        # 底部保存按钮
        self.btn_save = QPushButton("保存全部技能配置")
        self.btn_save.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-size: 14px;")
        self.btn_save.clicked.connect(self._on_save)
        layout.addWidget(self.btn_save)

    def _build_attack_page(self):
        """攻击技能页面：按键 + 频率(冷却) + 距离 + 优先级"""
        page = QWidget()
        layout = QVBoxLayout(page)

        # 列表
        self.list_attack = QListWidget()
        layout.addWidget(self.list_attack)

        # 添加表单
        form = QGroupBox("添加攻击技能")
        grid = QGridLayout()

        grid.addWidget(QLabel("名称:"), 0, 0)
        self.edit_atk_name = QLineEdit()
        self.edit_atk_name.setPlaceholderText("如：主攻、群攻")
        grid.addWidget(self.edit_atk_name, 0, 1)

        grid.addWidget(QLabel("按键:"), 1, 0)
        self.edit_atk_key = KeyCaptureLineEdit()
        grid.addWidget(self.edit_atk_key, 1, 1)

        grid.addWidget(QLabel("频率/冷却(秒):"), 2, 0)
        self.spin_atk_cd = QDoubleSpinBox()
        self.spin_atk_cd.setRange(0.05, 60)
        self.spin_atk_cd.setSingleStep(0.1)
        self.spin_atk_cd.setValue(0.3)
        grid.addWidget(self.spin_atk_cd, 2, 1)

        grid.addWidget(QLabel("攻击距离(px):"), 3, 0)
        self.spin_atk_dist = QSpinBox()
        self.spin_atk_dist.setRange(10, 800)
        self.spin_atk_dist.setValue(150)
        grid.addWidget(self.spin_atk_dist, 3, 1)

        grid.addWidget(QLabel("优先级(小的先放):"), 4, 0)
        self.spin_atk_prio = QSpinBox()
        self.spin_atk_prio.setRange(0, 99)
        self.spin_atk_prio.setValue(0)
        grid.addWidget(self.spin_atk_prio, 4, 1)

        self.check_atk_enabled = QCheckBox("启用")
        self.check_atk_enabled.setChecked(True)
        grid.addWidget(self.check_atk_enabled, 5, 0, 1, 2)

        btn_add = QPushButton("添加攻击技能")
        btn_add.setStyleSheet("background-color: #2196F3; color: white; padding: 6px;")
        btn_add.clicked.connect(self._on_add_attack)
        grid.addWidget(btn_add, 6, 0, 1, 2)

        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(lambda: self._on_delete(self.list_attack, "attack"))
        grid.addWidget(btn_del, 7, 0, 1, 2)

        form.setLayout(grid)
        layout.addWidget(form)
        return page

    def _build_buff_page(self):
        """BUFF技能页面：按键 + 冷却时间"""
        page = QWidget()
        layout = QVBoxLayout(page)

        self.list_buff = QListWidget()
        layout.addWidget(self.list_buff)

        form = QGroupBox("添加BUFF技能")
        grid = QGridLayout()

        grid.addWidget(QLabel("名称:"), 0, 0)
        self.edit_buff_name = QLineEdit()
        self.edit_buff_name.setPlaceholderText("如：攻击BUFF、防御BUFF")
        grid.addWidget(self.edit_buff_name, 0, 1)

        grid.addWidget(QLabel("按键:"), 1, 0)
        self.edit_buff_key = KeyCaptureLineEdit()
        grid.addWidget(self.edit_buff_key, 1, 1)

        grid.addWidget(QLabel("冷却/持续(秒):"), 2, 0)
        self.spin_buff_cd = QDoubleSpinBox()
        self.spin_buff_cd.setRange(1, 3600)
        self.spin_buff_cd.setValue(180)
        grid.addWidget(self.spin_buff_cd, 2, 1)

        self.check_buff_enabled = QCheckBox("启用")
        self.check_buff_enabled.setChecked(True)
        grid.addWidget(self.check_buff_enabled, 3, 0, 1, 2)

        btn_add = QPushButton("添加BUFF技能")
        btn_add.setStyleSheet("background-color: #9C27B0; color: white; padding: 6px;")
        btn_add.clicked.connect(self._on_add_buff)
        grid.addWidget(btn_add, 4, 0, 1, 2)

        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(lambda: self._on_delete(self.list_buff, "buff"))
        grid.addWidget(btn_del, 5, 0, 1, 2)

        form.setLayout(grid)
        layout.addWidget(form)
        return page

    def _build_jump_page(self):
        """跳跃技能页面：按键"""
        page = QWidget()
        layout = QVBoxLayout(page)

        self.list_jump = QListWidget()
        layout.addWidget(self.list_jump)

        form = QGroupBox("添加跳跃技能")
        grid = QGridLayout()

        grid.addWidget(QLabel("名称:"), 0, 0)
        self.edit_jump_name = QLineEdit()
        self.edit_jump_name.setPlaceholderText("如：二段跳、冲刺")
        grid.addWidget(self.edit_jump_name, 0, 1)

        grid.addWidget(QLabel("按键:"), 1, 0)
        self.edit_jump_key = KeyCaptureLineEdit()
        grid.addWidget(self.edit_jump_key, 1, 1)

        grid.addWidget(QLabel("冷却(秒):"), 2, 0)
        self.spin_jump_cd = QDoubleSpinBox()
        self.spin_jump_cd.setRange(0.1, 10)
        self.spin_jump_cd.setSingleStep(0.1)
        self.spin_jump_cd.setValue(0.5)
        grid.addWidget(self.spin_jump_cd, 2, 1)

        self.check_jump_enabled = QCheckBox("启用")
        self.check_jump_enabled.setChecked(True)
        grid.addWidget(self.check_jump_enabled, 3, 0, 1, 2)

        btn_add = QPushButton("添加跳跃技能")
        btn_add.setStyleSheet("background-color: #00BCD4; color: white; padding: 6px;")
        btn_add.clicked.connect(self._on_add_jump)
        grid.addWidget(btn_add, 4, 0, 1, 2)

        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(lambda: self._on_delete(self.list_jump, "jump"))
        grid.addWidget(btn_del, 5, 0, 1, 2)

        form.setLayout(grid)
        layout.addWidget(form)
        return page

    def _build_teleport_page(self):
        """瞬移技能页面：按键 + 距离"""
        page = QWidget()
        layout = QVBoxLayout(page)

        self.list_teleport = QListWidget()
        layout.addWidget(self.list_teleport)

        form = QGroupBox("添加瞬移技能")
        grid = QGridLayout()

        grid.addWidget(QLabel("名称:"), 0, 0)
        self.edit_tp_name = QLineEdit()
        self.edit_tp_name.setPlaceholderText("如：瞬移、闪现")
        grid.addWidget(self.edit_tp_name, 0, 1)

        grid.addWidget(QLabel("按键:"), 1, 0)
        self.edit_tp_key = KeyCaptureLineEdit()
        grid.addWidget(self.edit_tp_key, 1, 1)

        grid.addWidget(QLabel("冷却(秒):"), 2, 0)
        self.spin_tp_cd = QDoubleSpinBox()
        self.spin_tp_cd.setRange(0.1, 60)
        self.spin_tp_cd.setSingleStep(0.1)
        self.spin_tp_cd.setValue(1.0)
        grid.addWidget(self.spin_tp_cd, 2, 1)

        grid.addWidget(QLabel("瞬移距离(px):"), 3, 0)
        self.spin_tp_dist = QSpinBox()
        self.spin_tp_dist.setRange(10, 800)
        self.spin_tp_dist.setValue(200)
        grid.addWidget(self.spin_tp_dist, 3, 1)

        self.check_tp_enabled = QCheckBox("启用")
        self.check_tp_enabled.setChecked(True)
        grid.addWidget(self.check_tp_enabled, 4, 0, 1, 2)

        btn_add = QPushButton("添加瞬移技能")
        btn_add.setStyleSheet("background-color: #FF5722; color: white; padding: 6px;")
        btn_add.clicked.connect(self._on_add_teleport)
        grid.addWidget(btn_add, 5, 0, 1, 2)

        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(lambda: self._on_delete(self.list_teleport, "teleport"))
        grid.addWidget(btn_del, 6, 0, 1, 2)

        form.setLayout(grid)
        layout.addWidget(form)
        return page

    # ========== 刷新列表 ==========

    def _refresh_all(self):
        self._refresh_list(self.list_attack, "attack")
        self._refresh_list(self.list_buff, "buff")
        self._refresh_list(self.list_jump, "jump")
        self._refresh_list(self.list_teleport, "teleport")

    def _refresh_list(self, list_widget, skill_type):
        list_widget.clear()
        for s in self.bot.skill_mgr.skills:
            if s.type.value != skill_type:
                continue
            status = "ON" if s.enabled else "OFF"
            if skill_type == "attack":
                text = f"[{status}] {s.name} | 键:{s.key} | CD:{s.cooldown}s | 距离:{s.distance}px | 优先级:{s.priority}"
            elif skill_type == "buff":
                text = f"[{status}] {s.name} | 键:{s.key} | CD:{s.cooldown}s"
            elif skill_type == "jump":
                text = f"[{status}] {s.name} | 键:{s.key} | CD:{s.cooldown}s"
            elif skill_type == "teleport":
                text = f"[{status}] {s.name} | 键:{s.key} | CD:{s.cooldown}s | 距离:{s.distance}px"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, s.name)
            list_widget.addItem(item)

    # ========== 添加技能 ==========

    def _on_add_attack(self):
        name = self.edit_atk_name.text().strip()
        key = self.edit_atk_key.text().strip()
        if not name or not key:
            QMessageBox.warning(self, "提示", "请填写名称并设置按键")
            return
        self.bot.skill_mgr.add_skill(
            name=name, key=key, skill_type="attack",
            cooldown=self.spin_atk_cd.value(),
            distance=self.spin_atk_dist.value(),
            enabled=self.check_atk_enabled.isChecked(),
            priority=self.spin_atk_prio.value()
        )
        self.edit_atk_name.clear()
        self.edit_atk_key.clear()
        self._refresh_all()

    def _on_add_buff(self):
        name = self.edit_buff_name.text().strip()
        key = self.edit_buff_key.text().strip()
        if not name or not key:
            QMessageBox.warning(self, "提示", "请填写名称并设置按键")
            return
        self.bot.skill_mgr.add_skill(
            name=name, key=key, skill_type="buff",
            cooldown=self.spin_buff_cd.value(),
            distance=0, enabled=self.check_buff_enabled.isChecked(), priority=0
        )
        self.edit_buff_name.clear()
        self.edit_buff_key.clear()
        self._refresh_all()

    def _on_add_jump(self):
        name = self.edit_jump_name.text().strip()
        key = self.edit_jump_key.text().strip()
        if not name or not key:
            QMessageBox.warning(self, "提示", "请填写名称并设置按键")
            return
        self.bot.skill_mgr.add_skill(
            name=name, key=key, skill_type="jump",
            cooldown=self.spin_jump_cd.value(),
            distance=0, enabled=self.check_jump_enabled.isChecked(), priority=0
        )
        self.edit_jump_name.clear()
        self.edit_jump_key.clear()
        self._refresh_all()

    def _on_add_teleport(self):
        name = self.edit_tp_name.text().strip()
        key = self.edit_tp_key.text().strip()
        if not name or not key:
            QMessageBox.warning(self, "提示", "请填写名称并设置按键")
            return
        self.bot.skill_mgr.add_skill(
            name=name, key=key, skill_type="teleport",
            cooldown=self.spin_tp_cd.value(),
            distance=self.spin_tp_dist.value(),
            enabled=self.check_tp_enabled.isChecked(), priority=0
        )
        self.edit_tp_name.clear()
        self.edit_tp_key.clear()
        self._refresh_all()

    def _on_delete(self, list_widget, skill_type):
        item = list_widget.currentItem()
        if item:
            name = item.data(Qt.UserRole)
            self.bot.skill_mgr.remove_skill(name)
            self._refresh_all()

    def _on_save(self):
        skills_config = self.bot.skill_mgr.to_config_list()
        self.bot.config.set("skills", skills_config)
        # 同步更新决策器的攻击范围
        if hasattr(self.bot, 'decision') and self.bot.decision:
            self.bot.decision.set_skill_manager(self.bot.skill_mgr)
        QMessageBox.information(self, "保存", f"技能配置已保存（共{len(skills_config)}个技能）")


class PlayerTab(QWidget):
    """人物定位面板 - 模板匹配截图采集"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self._build_ui()
        self._refresh_template_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 定位模式
        mode_group = QGroupBox("人物定位方式")
        mode_layout = QVBoxLayout()

        self.combo_loc_mode = QComboBox()
        self.combo_loc_mode.addItems([
            ("auto - 优先模板匹配，失败用YOLO"),
            ("template - 仅模板匹配"),
            ("yolo - 仅YOLO检测")
        ])
        mode_map = {"auto": 0, "template": 1, "yolo": 2}
        current = self.bot.config.get("player_tracker.mode", "auto")
        self.combo_loc_mode.setCurrentIndex(mode_map.get(current, 0))
        self.combo_loc_mode.currentIndexChanged.connect(self._on_mode_change)
        mode_layout.addWidget(self.combo_loc_mode)

        mode_layout.addWidget(QLabel("匹配置信度阈值:"))
        self.slider_threshold = QSlider(Qt.Horizontal)
        self.slider_threshold.setRange(50, 95)
        self.slider_threshold.setValue(int(self.bot.player_tracker.match_threshold * 100))
        self.label_threshold = QLabel(f"{self.bot.player_tracker.match_threshold:.2f}")
        self.slider_threshold.valueChanged.connect(self._on_threshold_change)
        th_layout = QHBoxLayout()
        th_layout.addWidget(self.slider_threshold)
        th_layout.addWidget(self.label_threshold)
        mode_layout.addLayout(th_layout)

        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # 模板采集
        capture_group = QGroupBox("人物特征图采集")
        cap_layout = QVBoxLayout()

        tip = QLabel(
            "使用方法：\n"
            "1. 先让游戏人物面朝左/右，站在清晰位置\n"
            "2. 点击对应按钮，2秒后自动全屏截图\n"
            "3. 在截图上拖拽框选人物特征区域（建议选头部或身体）\n"
            "4. 回车确认保存，左右朝向各截1-3张效果最佳"
        )
        tip.setStyleSheet("color: #FF9800; padding: 5px;")
        tip.setWordWrap(True)
        cap_layout.addWidget(tip)

        btn_row = QHBoxLayout()
        self.btn_cap_left = QPushButton("截取左朝向模板")
        self.btn_cap_left.setStyleSheet("background-color: #2196F3; color: white; padding: 10px;")
        self.btn_cap_left.clicked.connect(lambda: self._capture_template("left"))
        self.btn_cap_right = QPushButton("截取右朝向模板")
        self.btn_cap_right.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        self.btn_cap_right.clicked.connect(lambda: self._capture_template("right"))
        btn_row.addWidget(self.btn_cap_left)
        btn_row.addWidget(self.btn_cap_right)
        cap_layout.addLayout(btn_row)

        capture_group.setLayout(cap_layout)
        layout.addWidget(capture_group)

        # 模板列表
        list_group = QGroupBox("已保存模板")
        list_layout = QVBoxLayout()

        self.label_template_count = QLabel("左朝向: 0 张 | 右朝向: 0 张")
        list_layout.addWidget(self.label_template_count)

        self.list_templates = QListWidget()
        list_layout.addWidget(self.list_templates)

        del_row = QHBoxLayout()
        self.btn_del_template = QPushButton("删除选中")
        self.btn_del_template.clicked.connect(self._on_delete_template)
        self.btn_clear_left = QPushButton("清空左朝向")
        self.btn_clear_left.clicked.connect(lambda: self._clear_templates("left"))
        self.btn_clear_right = QPushButton("清空右朝向")
        self.btn_clear_right.clicked.connect(lambda: self._clear_templates("right"))
        del_row.addWidget(self.btn_del_template)
        del_row.addWidget(self.btn_clear_left)
        del_row.addWidget(self.btn_clear_right)
        list_layout.addLayout(del_row)

        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        # 测试定位
        test_group = QGroupBox("定位测试")
        test_layout = QVBoxLayout()
        self.btn_test = QPushButton("测试当前帧人物定位")
        self.btn_test.clicked.connect(self._on_test_track)
        test_layout.addWidget(self.btn_test)
        self.label_test_result = QLabel("")
        test_layout.addWidget(self.label_test_result)
        test_group.setLayout(test_layout)
        layout.addWidget(test_group)

        layout.addStretch()

    def _on_mode_change(self, index):
        mode_map = {0: "auto", 1: "template", 2: "yolo"}
        mode = mode_map.get(index, "auto")
        self.bot.player_loc_mode = mode
        self.bot.config.set("player_tracker.mode", mode)

    def _on_threshold_change(self, value):
        threshold = value / 100.0
        self.label_threshold.setText(f"{threshold:.2f}")
        self.bot.player_tracker.match_threshold = threshold
        self.bot.config.set("player_tracker.match_threshold", threshold)

    def _capture_template(self, direction):
        """截取人物模板图"""
        direction_name = "左" if direction == "left" else "右"
        QMessageBox.information(self, "准备截图",
                                f"2秒后将全屏截图，请切换到游戏窗口，让人物面朝{direction_name}边。")
        # 延迟2秒
        self.btn_cap_left.setEnabled(False)
        self.btn_cap_right.setEnabled(False)
        QTimer.singleShot(2000, lambda: self._do_capture(direction))

    def _do_capture(self, direction):
        """执行截图并框选"""
        try:
            frame = self.bot.capture.capture()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"截图失败: {e}")
            self.btn_cap_left.setEnabled(True)
            self.btn_cap_right.setEnabled(True)
            return

        self.btn_cap_left.setEnabled(True)
        self.btn_cap_right.setEnabled(True)

        # 弹出框选对话框
        dialog = RegionSelectDialog(frame, self)
        if dialog.exec_() == QDialog.Accepted:
            cropped = dialog.get_cropped_image()
            if cropped is not None and cropped.size > 0:
                file_path = self.bot.player_tracker.save_template(cropped, direction)
                QMessageBox.information(self, "保存成功",
                    f"模板已保存:\n{file_path}\n尺寸: {cropped.shape[1]}x{cropped.shape[0]}")
                self._refresh_template_list()

    def _refresh_template_list(self):
        self.list_templates.clear()
        templates = self.bot.player_tracker.list_templates()
        for t in templates:
            dir_name = "左" if t["direction"] == "left" else "右"
            item = QListWidgetItem(
                f"[{dir_name}朝向] {t['file']} - {t['width']}x{t['height']}"
            )
            item.setData(Qt.UserRole, (t["direction"], t["index"]))
            self.list_templates.addItem(item)
        self.label_template_count.setText(
            f"左朝向: {self.bot.player_tracker.left_count} 张 | "
            f"右朝向: {self.bot.player_tracker.right_count} 张"
        )

    def _on_delete_template(self):
        item = self.list_templates.currentItem()
        if item:
            direction, index = item.data(Qt.UserRole)
            # index是列表中的序号，需要找到对应的文件序号
            # 简单处理：重新加载后按文件名删除
            templates = self.bot.player_tracker.list_templates()
            if index < len(templates):
                t = templates[index]
                # 从文件名提取序号
                import re
                m = re.search(r'_(\d+)\.', t["file"])
                if m:
                    file_index = int(m.group(1))
                    self.bot.player_tracker.delete_template(t["direction"], file_index)
            self._refresh_template_list()

    def _clear_templates(self, direction):
        dir_name = "左" if direction == "left" else "右"
        reply = QMessageBox.question(self, "确认", f"确定清空所有{dir_name}朝向模板？")
        if reply == QMessageBox.Yes:
            self.bot.player_tracker.clear_templates(direction)
            self._refresh_template_list()

    def _on_test_track(self):
        """测试当前帧人物定位"""
        try:
            frame = self.bot.capture.capture()
        except Exception as e:
            self.label_test_result.setText(f"截图失败: {e}")
            return

        result = self.bot.player_tracker.track(frame)
        if result:
            self.label_test_result.setText(
                f"定位成功！位置: ({result['center'][0]:.0f}, {result['center'][1]:.0f}) "
                f"朝向: {result['direction']} 置信度: {result['confidence']:.3f}"
            )
            self.label_test_result.setStyleSheet("color: #4CAF50;")
        else:
            self.label_test_result.setText("定位失败：未匹配到人物，请检查模板或阈值")
            self.label_test_result.setStyleSheet("color: #f44336;")


class PotionTab(QWidget):
    """药品面板"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 红药
        hp_group = QGroupBox("红药 (HP)")
        hp_layout = QGridLayout()

        hp_layout.addWidget(QLabel("HP阈值(%):"), 0, 0)
        self.slider_hp = QSlider(Qt.Horizontal)
        self.slider_hp.setRange(5, 90)
        self.slider_hp.setValue(self.bot.potion_mgr.hp_threshold)
        self.label_hp_val = QLabel(f"{self.bot.potion_mgr.hp_threshold}%")
        self.slider_hp.valueChanged.connect(lambda v: self.label_hp_val.setText(f"{v}%"))
        hp_layout.addWidget(self.slider_hp, 0, 1)
        hp_layout.addWidget(self.label_hp_val, 0, 2)

        hp_layout.addWidget(QLabel("红药按键:"), 1, 0)
        self.edit_hp_key = QLineEdit(self.bot.potion_mgr.hp_key)
        hp_layout.addWidget(self.edit_hp_key, 1, 1)

        hp_group.setLayout(hp_layout)
        layout.addWidget(hp_group)

        # 蓝药
        mp_group = QGroupBox("蓝药 (MP)")
        mp_layout = QGridLayout()

        mp_layout.addWidget(QLabel("MP阈值(%):"), 0, 0)
        self.slider_mp = QSlider(Qt.Horizontal)
        self.slider_mp.setRange(5, 90)
        self.slider_mp.setValue(self.bot.potion_mgr.mp_threshold)
        self.label_mp_val = QLabel(f"{self.bot.potion_mgr.mp_threshold}%")
        self.slider_mp.valueChanged.connect(lambda v: self.label_mp_val.setText(f"{v}%"))
        mp_layout.addWidget(self.slider_mp, 0, 1)
        mp_layout.addWidget(self.label_mp_val, 0, 2)

        mp_layout.addWidget(QLabel("蓝药按键:"), 1, 0)
        self.edit_mp_key = QLineEdit(self.bot.potion_mgr.mp_key)
        mp_layout.addWidget(self.edit_mp_key, 1, 1)

        mp_group.setLayout(mp_layout)
        layout.addWidget(mp_group)

        # 血条区域
        bar_group = QGroupBox("血条/蓝条屏幕区域")
        bar_layout = QGridLayout()

        bar_layout.addWidget(QLabel("HP条区域 [x,y,w,h]:"), 0, 0)
        self.edit_hp_bar = QLineEdit(str(self.bot.potion_mgr.hp_bar_region))
        bar_layout.addWidget(self.edit_hp_bar, 0, 1)

        bar_layout.addWidget(QLabel("MP条区域 [x,y,w,h]:"), 1, 0)
        self.edit_mp_bar = QLineEdit(str(self.bot.potion_mgr.mp_bar_region))
        bar_layout.addWidget(self.edit_mp_bar, 1, 1)

        bar_group.setLayout(bar_layout)
        layout.addWidget(bar_group)

        # 保存按钮
        self.btn_save = QPushButton("保存药品配置")
        self.btn_save.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        self.btn_save.clicked.connect(self._on_save)
        layout.addWidget(self.btn_save)

        # 统计
        self.label_potion_stats = QLabel("红药使用: 0 次 | 蓝药使用: 0 次")
        layout.addWidget(self.label_potion_stats)

        layout.addStretch()

    def _on_save(self):
        self.bot.potion_mgr.hp_threshold = self.slider_hp.value()
        self.bot.potion_mgr.mp_threshold = self.slider_mp.value()
        self.bot.potion_mgr.hp_key = self.edit_hp_key.text().strip()
        self.bot.potion_mgr.mp_key = self.edit_mp_key.text().strip()

        try:
            self.bot.potion_mgr.hp_bar_region = eval(self.edit_hp_bar.text())
            self.bot.potion_mgr.mp_bar_region = eval(self.edit_mp_bar.text())
        except Exception:
            QMessageBox.warning(self, "提示", "区域格式错误，应为 [x,y,w,h]")
            return

        self.bot.config.set("potions", self.bot.potion_mgr.to_dict())
        QMessageBox.information(self, "保存", "药品配置已保存")

    def update_stats(self):
        self.label_potion_stats.setText(
            f"红药使用: {self.bot.potion_mgr.hp_potion_count} 次 | "
            f"蓝药使用: {self.bot.potion_mgr.mp_potion_count} 次"
        )


class SettingsTab(QWidget):
    """设置面板"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # YOLO 设置
        yolo_group = QGroupBox("YOLO 检测设置")
        yolo_layout = QGridLayout()

        yolo_layout.addWidget(QLabel("模型路径(.pt):"), 0, 0)
        self.edit_model_path = QLineEdit(self.bot.config.get("yolo.model_path", "data/models/best.pt"))
        yolo_layout.addWidget(self.edit_model_path, 0, 1)

        yolo_layout.addWidget(QLabel("置信度阈值:"), 1, 0)
        self.spin_conf = QDoubleSpinBox()
        self.spin_conf.setRange(0.1, 0.99)
        self.spin_conf.setSingleStep(0.05)
        self.spin_conf.setValue(self.bot.config.get("yolo.confidence", 0.5))
        yolo_layout.addWidget(self.spin_conf, 1, 1)

        yolo_layout.addWidget(QLabel("IoU阈值:"), 2, 0)
        self.spin_iou = QDoubleSpinBox()
        self.spin_iou.setRange(0.1, 0.99)
        self.spin_iou.setSingleStep(0.05)
        self.spin_iou.setValue(self.bot.config.get("yolo.iou_threshold", 0.45))
        yolo_layout.addWidget(self.spin_iou, 2, 1)

        yolo_layout.addWidget(QLabel("推理设备:"), 3, 0)
        self.combo_device = QComboBox()
        self.combo_device.addItems(["cpu", "cuda:0", "cuda:1", "mps"])
        idx = self.combo_device.findText(self.bot.config.get("yolo.device", "cpu"))
        if idx >= 0:
            self.combo_device.setCurrentIndex(idx)
        yolo_layout.addWidget(self.combo_device, 3, 1)

        yolo_group.setLayout(yolo_layout)
        layout.addWidget(yolo_group)

        # 截图设置
        cap_group = QGroupBox("截图设置")
        cap_layout = QGridLayout()

        cap_layout.addWidget(QLabel("游戏窗口标题:"), 0, 0)
        self.edit_window_title = QLineEdit(self.bot.config.get("game.window_title", "MapleStory"))
        cap_layout.addWidget(self.edit_window_title, 0, 1)

        cap_layout.addWidget(QLabel("截图区域 [x,y,w,h]:"), 1, 0)
        self.edit_capture_region = QLineEdit(str(self.bot.config.get("game.capture_region", [0, 0, 1920, 1080])))
        cap_layout.addWidget(self.edit_capture_region, 1, 1)

        cap_layout.addWidget(QLabel("目标FPS:"), 2, 0)
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(5, 60)
        self.spin_fps.setValue(self.bot.config.get("game.fps", 30))
        cap_layout.addWidget(self.spin_fps, 2, 1)

        cap_group.setLayout(cap_layout)
        layout.addWidget(cap_group)

        # 路径选择设置
        pf_group = QGroupBox("路径选择设置")
        pf_layout = QGridLayout()

        pf_layout.addWidget(QLabel("跳跃高度阈值(px):"), 0, 0)
        self.spin_jump_h = QSpinBox()
        self.spin_jump_h.setRange(20, 300)
        self.spin_jump_h.setValue(self.bot.config.get("pathfinding.jump_height_threshold", 120))
        pf_layout.addWidget(self.spin_jump_h, 0, 1)

        pf_layout.addWidget(QLabel("优先爬梯高度(px):"), 1, 0)
        self.spin_ladder_h = QSpinBox()
        self.spin_ladder_h.setRange(50, 500)
        self.spin_ladder_h.setValue(self.bot.config.get("pathfinding.prefer_ladder_height", 200))
        pf_layout.addWidget(self.spin_ladder_h, 1, 1)

        pf_group.setLayout(pf_layout)
        layout.addWidget(pf_group)

        # 保存
        self.btn_save = QPushButton("保存所有设置")
        self.btn_save.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px;")
        self.btn_save.clicked.connect(self._on_save)
        layout.addWidget(self.btn_save)

        layout.addStretch()

    def _on_save(self):
        self.bot.config.set("yolo.model_path", self.edit_model_path.text())
        self.bot.config.set("yolo.confidence", self.spin_conf.value())
        self.bot.config.set("yolo.iou_threshold", self.spin_iou.value())
        self.bot.config.set("yolo.device", self.combo_device.currentText())
        self.bot.config.set("game.window_title", self.edit_window_title.text())
        try:
            self.bot.config.set("game.capture_region", eval(self.edit_capture_region.text()))
        except Exception:
            pass
        self.bot.config.set("game.fps", self.spin_fps.value())
        self.bot.config.set("pathfinding.jump_height_threshold", self.spin_jump_h.value())
        self.bot.config.set("pathfinding.prefer_ladder_height", self.spin_ladder_h.value())
        QMessageBox.information(self, "保存", "设置已保存，重启后生效")


class MinimapTab(QWidget):
    """小地图面板"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.minimap = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 小地图控制
        ctrl_group = QGroupBox("小地图窗口")
        ctrl_layout = QVBoxLayout()

        desc = QLabel("点击按钮打开独立的小地图标记窗口，窗口中会实时显示平台(绿)、梯子(蓝)、怪物(红)、人物(黄)。")
        desc.setWordWrap(True)
        ctrl_layout.addWidget(desc)

        btn_layout = QHBoxLayout()
        self.btn_show = QPushButton("打开小地图窗口")
        self.btn_show.setStyleSheet("background-color: #9C27B0; color: white; padding: 8px;")
        self.btn_show.clicked.connect(self._on_show)
        self.btn_hide = QPushButton("关闭小地图窗口")
        self.btn_hide.clicked.connect(self._on_hide)
        self.btn_hide.setEnabled(False)
        btn_layout.addWidget(self.btn_show)
        btn_layout.addWidget(self.btn_hide)
        ctrl_layout.addLayout(btn_layout)

        ctrl_group.setLayout(ctrl_layout)
        layout.addWidget(ctrl_group)

        # 小地图区域设置
        region_group = QGroupBox("小地图区域设置")
        region_layout = QGridLayout()

        region_layout.addWidget(QLabel("小地图屏幕区域 [x,y,w,h]:"), 0, 0)
        self.edit_minimap_region = QLineEdit(
            str(self.bot.config.get("minimap.region", [1700, 50, 200, 200]))
        )
        region_layout.addWidget(self.edit_minimap_region, 0, 1)

        region_layout.addWidget(QLabel("显示缩放:"), 1, 0)
        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.5, 4.0)
        self.spin_scale.setSingleStep(0.5)
        self.spin_scale.setValue(self.bot.config.get("minimap.scale", 1.0))
        region_layout.addWidget(self.spin_scale, 1, 1)

        region_group.setLayout(region_layout)
        layout.addWidget(region_group)

        # 坐标映射说明
        info_group = QGroupBox("坐标映射说明")
        info_layout = QVBoxLayout()
        info_text = QLabel(
            "小地图坐标映射用于将全屏游戏坐标转换为小地图上的位置。\n"
            "默认使用简单线性映射，如需精确映射可在代码中调用 calibrate() 方法。\n"
            "平台和梯子的标记基于录制时的全屏坐标。"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()

    def _on_show(self):
        try:
            region = eval(self.edit_minimap_region.text())
        except Exception:
            region = [1700, 50, 200, 200]

        self.minimap = MinimapWindow(
            minimap_region=region,
            scale=self.spin_scale.value()
        )
        self.minimap.start()
        self.btn_show.setEnabled(False)
        self.btn_hide.setEnabled(True)

    def _on_hide(self):
        if self.minimap:
            self.minimap.stop()
            self.minimap = None
        self.btn_show.setEnabled(True)
        self.btn_hide.setEnabled(False)

    def update_minimap_data(self):
        """更新小地图数据（由主定时器调用）"""
        if self.minimap and self.bot.locator.has_player():
            monster_positions = [m["pos"] for m in self.bot.locator.monsters]
            self.minimap.set_data(
                player_pos=self.bot.locator.player_pos,
                monsters=monster_positions,
                platforms=self.bot.platform_mgr.platforms,
                ladders=self.bot.ladder_mgr.ladders
            )


class MainWindow(QMainWindow):
    """主窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("2D横版游戏挂机助手")
        self.setGeometry(100, 100, 700, 800)

        # 初始化机器人
        self.bot = GameBot()

        # 注册回调
        self.bot.on_log = self._on_log

        # 构建UI
        self._build_ui()

        # 定时器更新状态
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_ui)
        self.timer.start(500)  # 每500ms更新一次

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 标题
        title = QLabel("2D横版游戏挂机助手")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)

        # Tab 切换面板
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                padding: 10px 20px;
                font-size: 14px;
            }
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
            }
        """)

        self.attack_tab = AttackTab(self.bot)
        self.route_tab = RouteTab(self.bot)
        self.skill_tab = SkillTab(self.bot)
        self.player_tab = PlayerTab(self.bot)
        self.potion_tab = PotionTab(self.bot)
        self.settings_tab = SettingsTab(self.bot)
        self.minimap_tab = MinimapTab(self.bot)

        self.tabs.addTab(self.attack_tab, "攻击")
        self.tabs.addTab(self.route_tab, "路线")
        self.tabs.addTab(self.skill_tab, "技能")
        self.tabs.addTab(self.player_tab, "人物")
        self.tabs.addTab(self.potion_tab, "药品")
        self.tabs.addTab(self.settings_tab, "设置")
        self.tabs.addTab(self.minimap_tab, "小地图")

        layout.addWidget(self.tabs)

        # 日志区
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

    def _on_log(self, msg):
        from PyQt5.QtCore import QMetaObject, Qt as QtCoreQt
        QMetaObject.invokeMethod(self.log_text, "append", QtCoreQt.QueuedConnection, str(msg))

    def _update_ui(self):
        """定时更新UI"""
        self.attack_tab.update_status()
        self.potion_tab.update_stats()
        self.minimap_tab.update_minimap_data()

    def closeEvent(self, event):
        """关闭窗口时清理"""
        self.bot.stop()
        if self.minimap_tab.minimap:
            self.minimap_tab.minimap.stop()
        event.accept()


def run_app():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 深色主题
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(50, 50, 50))
    palette.setColor(QPalette.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.Button, QColor(60, 60, 60))
    palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    run_app()
