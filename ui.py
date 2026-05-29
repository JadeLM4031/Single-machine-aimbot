"""PySide6 主窗口 - 白色现代风格"""

import time
import threading
import random
import cv2
import numpy as np
import math
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGroupBox,
    QPushButton,
    QComboBox,
    QCheckBox,
    QSlider,
    QLabel,
    QLineEdit,
    QFileDialog,
    QScrollArea,
    QMessageBox,
    QFrame,
    QTextEdit,
)
from PySide6.QtCore import Qt, QTimer, QEvent, Signal, QObject
from PySide6.QtGui import QImage, QPixmap

import config
from capture import OBSCapture
from detector import Detector
from mover import MouseController

try:
    import win32api
    import win32con
except ImportError:
    win32api = None
    win32con = None

LIGHT_STYLE = """
QMainWindow, QWidget {
    background-color: #f8fafc;
    color: #0f172a;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 12px;
}
QScrollArea {
    background-color: #f8fafc;
    border: none;
}
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    margin-top: 14px;
    padding: 16px 14px 12px 14px;
    font-weight: bold;
    font-size: 13px;
    color: #4f46e5;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
}
QPushButton {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #4f46e5;
    color: #4f46e5;
}
QPushButton:pressed {
    background-color: #e2e8f0;
}
QComboBox {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 5px 10px;
}
QComboBox:hover {
    border-color: #4f46e5;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left-width: 0px;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    selection-background-color: #f1f5f9;
    selection-color: #4f46e5;
}
QSlider::groove:horizontal {
    background: #e2e8f0;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #4f46e5;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #4338ca;
}
QSlider::sub-page:horizontal {
    background: #4f46e5;
    border-radius: 3px;
}
QCheckBox {
    color: #64748b;
    spacing: 8px;
    font-size: 12px;
}
QCheckBox:hover {
    color: #0f172a;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 2px solid #cbd5e1;
    background-color: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #4f46e5;
}
QCheckBox::indicator:checked {
    background-color: #4f46e5;
    border-color: #4f46e5;
}
QLineEdit {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 5px 10px;
}
QLineEdit:focus {
    border-color: #4f46e5;
}
QTextEdit {
    background-color: #1e1e2e;
    color: #a6e3a1;
    border: 1px solid #313244;
    border-radius: 10px;
    padding: 6px 10px;
    font-family: Consolas, monospace;
    font-size: 11px;
}
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 20px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    background: none;
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
"""


class _LogBridge(QObject):
    log_signal = Signal(str)


class SoundAlertManager:
    def __init__(self):
        self.enabled = False
        self.last_play_time = 0.0
        self.cooldown = 3.0  # 🟢 战术降频：三秒内最多响一下，绝对防止刷音和噪音干扰
        self.has_triggered_active = False  # 标志当前波次锁定是否已触发声音提示

    def trigger(self, count):
        if not self.enabled:
            return
        
        # 🟢 战术优先过滤：只有在目标模式为“敌人(enemy)”时才发声警报，靶场、小兵、队友等其它模式保持 100% 绝对静音
        if getattr(config, "TARGET_MODE", "enemy") != "enemy":
            self.has_triggered_active = False
            return
            
        now = time.time()
        
        if count > 0:
            # 只有从 0 个目标变成有目标（即 has_triggered_active 为 False 且首次露头）时才会触发单次提示音
            if not self.has_triggered_active:
                if now - self.last_play_time >= self.cooldown:
                    import winsound
                    import os
                    try:
                        sound_path = getattr(config, "SOUND_FILE", "tool/tip.wav")
                        if os.path.exists(sound_path):
                            # 播放用户放置的自定义快速 WAV 声音文件
                            winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                        else:
                            # 如果未放置，自动降级为系统中最快的 "SystemQuestion"（滴答水滴音）
                            winsound.PlaySound("SystemQuestion", winsound.SND_ALIAS | winsound.SND_ASYNC)
                        self.last_play_time = now
                        self.has_triggered_active = True
                    except Exception:
                        pass
        else:
            # 目标完全消失后，重置触发标志，等待下一次“从0到有”的瞬时露头再次警报
            self.has_triggered_active = False

    def close(self):
        pass


class AimWindow(QMainWindow):
    frame_ready = Signal(np.ndarray, list)

    def __init__(self):
        super().__init__()
        import random as rand_mod

        fake_titles = [
            "NVIDIA Container Overlay",
            "Windows Audio Service Host",
            "Steam Web Helper Overlay",
            "Microsoft OneDrive Sync",
            "Intel Graphics Control Panel",
            "Realtek Audio Universal Service",
        ]
        config.WINDOW_TITLE = rand_mod.choice(fake_titles)
        self.setMinimumSize(1120, 680)
        self.setStyleSheet(LIGHT_STYLE)

        self.capture = OBSCapture()
        self.detector = Detector()
        self.mover = MouseController()
        self.sound_manager = SoundAlertManager()
        self.sound_manager.enabled = config.SOUND_ALERT

        self.running = False
        self.lock = threading.Lock()
        self.latest_targets = []
        self.latest_targets_local = []
        self.locked_target_center = None
        self.locked_target_time = 0.0
        self.pid_active = False
        self.last_target_center = None
        self.last_target_time = 0.0
        self.target_vel_x = 0.0
        self.target_vel_y = 0.0
        self.locked_target_size = (60, 60)

        self.handover_cooldown_until = 0.0
        self.drift_x = 0.0
        self.drift_y = 0.0
        self.dispersal_x = 0.0
        self.dispersal_y = 0.0
        self.is_new_lock_session = True

        self.detect_fps = 0
        self._det_count = 0
        self._det_time = time.time()
        self.display_fps = 0
        self._disp_count = 0
        self._disp_time = time.time()

        self._build_ui()
        self._connect_signals()
        self._update_classes_and_mode()

        self._log_bridge = _LogBridge()
        self._log_bridge.log_signal.connect(self._on_log)
        config._log_callback = lambda line: self._log_bridge.log_signal.emit(line)

        self.frame_ready.connect(self._on_frame_ready)

        # 🟢 定时异步刷新 UI 状态信息（每 100ms 刷新一次，确保关闭画面预览时文字指标依然活跃刷新）
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._update_ui_stats)
        self.stats_timer.start(100)

    def eventFilter(self, obj, event):
        if isinstance(obj, (QComboBox, QSlider)):
            if event.type() == QEvent.Type.Wheel:
                return True
        return super().eventFilter(obj, event)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(12, 12, 12, 12)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        header = QLabel("SYSTEM  MONITOR")
        header.setStyleSheet(
            "color: #4f46e5; font-size: 20px; font-weight: bold; letter-spacing: 6px; padding: 6px 0;"
        )
        header.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(header)

        self.preview_label = QLabel("点击「开始」运行")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(640, 480)
        self.preview_label.setStyleSheet(
            "background-color: #e2e8f0; color: #64748b; border: 1px solid #cbd5e1; border-radius: 12px; font-size: 14px;"
        )
        left_layout.addWidget(self.preview_label, stretch=1)

        status_bar = QFrame()
        status_bar.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 4px 12px; }"
        )
        status_bar.setFixedHeight(34)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(14, 0, 14, 0)

        self.lbl_status = QLabel("状态: 未启动")
        self.lbl_status.setStyleSheet(
            "color: #64748b; font-size: 11px; font-weight: bold;"
        )
        self.lbl_fps = QLabel("FPS: --")
        self.lbl_fps.setStyleSheet(
            "color: #10b981; font-size: 11px; font-weight: bold;"
        )
        self.lbl_det = QLabel("检测: --")
        self.lbl_det.setStyleSheet(
            "color: #fb923c; font-size: 11px; font-weight: bold;"
        )
        self.lbl_targets = QLabel("目标: 0")
        self.lbl_targets.setStyleSheet(
            "color: #3b82f6; font-size: 11px; font-weight: bold;"
        )

        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch()
        status_layout.addWidget(self.lbl_targets)
        status_layout.addWidget(self.lbl_det)
        status_layout.addWidget(self.lbl_fps)
        left_layout.addWidget(status_bar)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(80)
        self.log_lines = []
        left_layout.addWidget(self.log_box)

        main_layout.addWidget(left_widget, stretch=3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(340)  # 🟢 固定滚动区宽度，彻底解决滚动条遮挡组件问题

        panel = QWidget()
        panel.setFixedWidth(316)   # 🟢 面板精确适配滚动区，留出滚动条完美通道
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(12) # 🟢 增加间距使界面更具透气呼吸感
        panel_layout.setContentsMargins(10, 10, 10, 10)

        self.btn_toggle = QPushButton("▶  开始")
        self.btn_toggle.setFixedHeight(44)
        self.btn_toggle.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; background-color: #10b981; color: white; border: none; border-radius: 10px; } QPushButton:hover { background-color: #059669; }"
        )
        panel_layout.addWidget(self.btn_toggle)

        aim_group = QGroupBox("瞄准设置")
        aim_layout = QVBoxLayout(aim_group)

        self._add_label(aim_layout, "触发键")
        self.combo_trigger = QComboBox()
        self.combo_trigger.addItems(["鼠标右键", "Ctrl", "Shift", "Alt", "鼠标侧键1", "鼠标侧键2"])
        trigger_map = {
            "right_mouse": 0,
            "ctrl": 1,
            "shift": 2,
            "alt": 3,
            "xbutton1": 4,
            "xbutton2": 5,
            "xbutton": 4,
        }
        self.combo_trigger.setCurrentIndex(trigger_map.get(config.AIM_TRIGGER_KEY, 0))
        aim_layout.addWidget(self.combo_trigger)

        self._add_label(aim_layout, "瞄准部位")
        self.combo_part = QComboBox()
        self.combo_part.addItems(["头部", "颈部", "胸部"])
        part_map = {"head": 0, "neck": 1, "chest": 2}
        self.combo_part.setCurrentIndex(
            part_map.get(getattr(config, "AIM_PART", "head"), 0)
        )
        aim_layout.addWidget(self.combo_part)

        self._add_label(aim_layout, "模型版本")
        self.combo_model_ver = QComboBox()
        self.combo_model_ver.addItems(["自动识别", "新多分类模型", "旧双分类模型"])
        model_ver_map = {"auto": 0, "new": 1, "old": 2}
        self.combo_model_ver.setCurrentIndex(model_ver_map.get(getattr(config, "MODEL_VERSION", "auto"), 0))
        aim_layout.addWidget(self.combo_model_ver)

        self._add_label(aim_layout, "目标模式")
        self.combo_target_mode = QComboBox()
        self.combo_target_mode.addItems(["敌人 (Enemy)", "靶场 (Practice)", "小兵 (Minion)", "倒地 (Downed)", "队友 (Teammate)"])
        target_mode_map = {"enemy": 0, "practice": 1, "xiaobing": 2, "daodi": 3, "duiyou": 4}
        self.combo_target_mode.setCurrentIndex(target_mode_map.get(getattr(config, "TARGET_MODE", "enemy"), 0))
        aim_layout.addWidget(self.combo_target_mode)

        self._add_label(aim_layout, "平滑度")
        smooth_row = QHBoxLayout()
        self.slider_smooth = QSlider(Qt.Horizontal)
        self.slider_smooth.setRange(1, 10)
        self.slider_smooth.setValue(int(config.SMOOTH_FACTOR * 10))
        self.lbl_smooth = QLabel(f"{config.SMOOTH_FACTOR:.1f}")
        smooth_row.addWidget(self.slider_smooth)
        smooth_row.addWidget(self.lbl_smooth)
        aim_layout.addLayout(smooth_row)

        self._add_label(aim_layout, "置信度")
        conf_row = QHBoxLayout()
        self.slider_conf = QSlider(Qt.Horizontal)
        self.slider_conf.setRange(1, 10)
        self.slider_conf.setValue(int(config.CONFIDENCE_THRESHOLD * 10))
        self.lbl_conf = QLabel(f"{config.CONFIDENCE_THRESHOLD:.1f}")
        conf_row.addWidget(self.slider_conf)
        conf_row.addWidget(self.lbl_conf)
        aim_layout.addLayout(conf_row)

        panel_layout.addWidget(aim_group)

        mouse_group = QGroupBox("鼠标模式")
        mouse_layout = QVBoxLayout(mouse_group)

        self.combo_mouse = QComboBox()
        self.combo_mouse.addItems(["真鼠标 (Win32)", "KMBox 网络", "KMBox 串口"])
        mode_map = {"mouse": 0, "kmbox_net": 1, "kmbox_serial": 2}
        self.combo_mouse.setCurrentIndex(mode_map.get(config.MOUSE_MODE, 0))
        mouse_layout.addWidget(self.combo_mouse)

        self.kmbox_net_widget = QWidget()
        km_net_layout = QVBoxLayout(self.kmbox_net_widget)
        ip_row = QHBoxLayout()
        self.edit_ip = QLineEdit(config.KMBOX_IP)
        ip_row.addWidget(QLabel("IP"))
        ip_row.addWidget(self.edit_ip)
        km_net_layout.addLayout(ip_row)

        port_row = QHBoxLayout()
        self.edit_port = QLineEdit(str(config.KMBOX_PORT))
        port_row.addWidget(QLabel("端口"))
        port_row.addWidget(self.edit_port)
        km_net_layout.addLayout(port_row)

        mac_row = QHBoxLayout()
        self.edit_mac = QLineEdit(config.KMBOX_MAC)
        mac_row.addWidget(QLabel("MAC"))
        mac_row.addWidget(self.edit_mac)
        km_net_layout.addLayout(mac_row)
        mouse_layout.addWidget(self.kmbox_net_widget)

        self.kmbox_serial_widget = QWidget()
        km_ser_layout = QVBoxLayout(self.kmbox_serial_widget)
        ser_row = QHBoxLayout()
        self.edit_serial = QLineEdit(config.KMBOX_SERIAL_PORT)
        ser_row.addWidget(QLabel("串口"))
        ser_row.addWidget(self.edit_serial)
        km_ser_layout.addLayout(ser_row)
        mouse_layout.addWidget(self.kmbox_serial_widget)

        self._update_kmbox_visibility()
        panel_layout.addWidget(mouse_group)

        display_group = QGroupBox("显示设置")
        display_layout = QVBoxLayout(display_group)
        self.chk_preview = QCheckBox("预览画面")
        self.chk_preview.setChecked(config.SHOW_PREVIEW)
        self.chk_bbox = QCheckBox("检测框")
        self.chk_bbox.setChecked(config.SHOW_BBOX)
        self.chk_crosshair = QCheckBox("准心")
        self.chk_crosshair.setChecked(config.SHOW_CROSSHAIR)
        self.chk_perf = QCheckBox("性能统计")
        self.chk_perf.setChecked(config.SHOW_PERF)
        self.chk_sound = QCheckBox("声音警报")
        self.chk_sound.setChecked(config.SOUND_ALERT)
        for chk in [
            self.chk_preview,
            self.chk_bbox,
            self.chk_crosshair,
            self.chk_perf,
            self.chk_sound,
        ]:
            display_layout.addWidget(chk)
        panel_layout.addWidget(display_group)

        model_group = QGroupBox("模型")
        model_layout = QVBoxLayout(model_group)
        model_row = QHBoxLayout()
        self.edit_model = QLineEdit(config.MODEL_PATH)
        self.btn_model = QPushButton("浏览")
        model_row.addWidget(self.edit_model)
        model_row.addWidget(self.btn_model)
        model_layout.addLayout(model_row)
        panel_layout.addWidget(model_group)

        size_group = QGroupBox("捕获尺寸")
        size_layout = QVBoxLayout(size_group)
        self.combo_size = QComboBox()
        self.combo_size.addItems(["320x320", "640x640"])
        self.combo_size.setCurrentIndex(0 if config.CAPTURE_SIZE == 320 else 1)
        size_layout.addWidget(self.combo_size)
        panel_layout.addWidget(size_group)

        monitor_group = QGroupBox("显示器")
        monitor_layout = QVBoxLayout(monitor_group)
        self.combo_monitor = QComboBox()
        self.combo_monitor.addItems(["屏幕 0 (主屏)", "屏幕 1 (副屏)"])
        self.combo_monitor.setCurrentIndex(config.OBS_CAMERA_INDEX)
        monitor_layout.addWidget(self.combo_monitor)
        panel_layout.addWidget(monitor_group)

        self.btn_save = QPushButton("保存配置")
        panel_layout.addWidget(self.btn_save)
        panel_layout.addStretch()

        scroll.setWidget(panel)
        main_layout.addWidget(scroll, stretch=1)

        for w in panel.findChildren(QComboBox) + panel.findChildren(QSlider):
            w.installEventFilter(self)

    @staticmethod
    def _add_label(layout, text):
        lbl = QLabel(text)
        layout.addWidget(lbl)

    def _connect_signals(self):
        self.btn_toggle.clicked.connect(self._toggle_run)
        self.combo_mouse.currentIndexChanged.connect(self._on_mouse_mode_changed)
        self.combo_trigger.currentIndexChanged.connect(self._on_trigger_changed)
        self.combo_part.currentIndexChanged.connect(self._on_part_changed)
        self.combo_model_ver.currentIndexChanged.connect(self._on_model_ver_changed)
        self.combo_target_mode.currentIndexChanged.connect(self._on_target_mode_changed)
        self.slider_smooth.valueChanged.connect(self._on_smooth_changed)
        self.slider_conf.valueChanged.connect(self._on_conf_changed)
        self.btn_model.clicked.connect(self._on_browse_model)
        self.btn_save.clicked.connect(self._on_save_config)
        self.combo_monitor.currentIndexChanged.connect(self._on_monitor_changed)
        self.combo_size.currentIndexChanged.connect(self._on_capture_size_changed)
        self.chk_preview.toggled.connect(lambda v: setattr(config, "SHOW_PREVIEW", v))
        self.chk_bbox.toggled.connect(lambda v: setattr(config, "SHOW_BBOX", v))
        self.chk_crosshair.toggled.connect(
            lambda v: setattr(config, "SHOW_CROSSHAIR", v)
        )
        self.chk_perf.toggled.connect(lambda v: setattr(config, "SHOW_PERF", v))
        self.chk_sound.toggled.connect(self._on_sound_alert_toggled)

    def _on_log(self, line):
        self.log_lines.append(line)
        if len(self.log_lines) > 100:
            self.log_lines = self.log_lines[-100:]
        self.log_box.setText("\n".join(self.log_lines))
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def log(self, msg):
        config.log(msg)

    def _on_smooth_changed(self, val):
        config.SMOOTH_FACTOR = val / 10.0
        self.mover.smooth = config.SMOOTH_FACTOR
        self.lbl_smooth.setText(f"{config.SMOOTH_FACTOR:.1f}")

    def _on_conf_changed(self, val):
        config.CONFIDENCE_THRESHOLD = val / 10.0
        self.detector.confidence = config.CONFIDENCE_THRESHOLD
        self.lbl_conf.setText(f"{config.CONFIDENCE_THRESHOLD:.1f}")

    def _on_sound_alert_toggled(self, checked):
        config.SOUND_ALERT = checked
        if hasattr(self, "sound_manager"):
            self.sound_manager.enabled = checked

    def _toggle_run(self):
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        try:
            config.MODEL_PATH = self.edit_model.text()
            self.capture.open()
            self.detector.model_path = config.MODEL_PATH
            self.detector.load()
            self._update_classes_and_mode()

            kwargs = {}
            if config.MOUSE_MODE == "kmbox_net":
                kwargs = {
                    "ip": self.edit_ip.text(),
                    "port": self.edit_port.text(),
                    "mac": self.edit_mac.text(),
                }
            elif config.MOUSE_MODE == "kmbox_serial":
                kwargs = {"serial_port": self.edit_serial.text()}

            self.mover.switch_mode(config.MOUSE_MODE, **kwargs)

            if not self.mover._kmbox_net_ready and config.MOUSE_MODE == "kmbox_net":
                self._stop()
                return
            if (
                not self.mover._kmbox_serial_conn
                and config.MOUSE_MODE == "kmbox_serial"
            ):
                self._stop()
                return
        except Exception as e:
            self._stop()
            QMessageBox.critical(self, "启动失败", str(e))
            return

        self.running = True
        self.btn_toggle.setText("■  停止")
        self.btn_toggle.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; background-color: #ef4444; color: white; border: none; border-radius: 10px; } QPushButton:hover { background-color: #dc2626; }"
        )
        self.lbl_status.setText("状态: 运行中")
        self.lbl_status.setStyleSheet(
            "color: #10b981; font-size: 11px; font-weight: bold;"
        )
        threading.Thread(target=self._detect_loop, daemon=True).start()

    def _stop(self):
        self.running = False
        self.capture.close()
        self.mover.close()
        self.btn_toggle.setText("▶  开始")
        self.btn_toggle.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; background-color: #10b981; color: white; border: none; border-radius: 10px; } QPushButton:hover { background-color: #059669; }"
        )
        self.lbl_status.setText("状态: 已停止")
        self.lbl_status.setStyleSheet(
            "color: #94a3b8; font-size: 11px; font-weight: bold;"
        )
        self.lbl_fps.setText("FPS: --")
        self.lbl_det.setText("检测: --")
        self.lbl_targets.setText("目标: 0")
        self.preview_label.setText("点击「开始」运行")

    def _detect_loop(self):
        last_move_time = 0
        last_frame_ptr = None
        last_preview_time = 0.0

        while self.running:
            try:
                frame = self.capture.read()
                if frame is None or id(frame) == last_frame_ptr:
                    time.sleep(0.001)
                    continue
                last_frame_ptr = id(frame)

                crop, offset = self.capture.crop_detect_region(frame)
                targets = self.detector.detect(crop)

                targets_global = []
                for t in targets:
                    targets_global.append(
                        {
                            "bbox": tuple(
                                v + o
                                for v, o in zip(
                                    t["bbox"],
                                    (offset[0], offset[1], offset[0], offset[1]),
                                )
                            ),
                            "center": (
                                t["center"][0] + offset[0],
                                t["center"][1] + offset[1],
                            ),
                            "head": (
                                t["head"][0] + offset[0],
                                t["head"][1] + offset[1],
                            ),
                            "neck": (
                                t["neck"][0] + offset[0],
                                t["neck"][1] + offset[1],
                            ),
                            "chest": (
                                t["chest"][0] + offset[0],
                                t["chest"][1] + offset[1],
                            ),
                            "confidence": t["confidence"],
                            "class_id": t["class_id"],
                            "area": t["area"],
                        }
                    )

                with self.lock:
                    self.latest_targets = targets_global
                    self.latest_targets_local = list(targets)

                self.sound_manager.trigger(len(targets))
                self._det_count += 1
                now = time.time()
                if now - self._det_time >= 1.0:
                    self.detect_fps = int(self._det_count / (now - self._det_time))
                    self._det_count = 0
                    self._det_time = now

                if self._is_aim_triggered():
                    self.pid_active = True
                    if now < self.handover_cooldown_until:
                        self.last_target_center = None
                        self.is_new_lock_session = True
                        if config.SHOW_PREVIEW:
                            self.frame_ready.emit(crop.copy(), list(targets))
                        continue

                    target_to_track = None
                    is_extrapolated = False

                    if (
                        self.locked_target_center is not None
                        and now - self.locked_target_time < 0.5
                    ):
                        min_match_dist = float("inf")
                        best_match = None
                        for t in targets:
                            dist = math.sqrt(
                                (t["center"][0] - self.locked_target_center[0]) ** 2
                                + (t["center"][1] - self.locked_target_center[1]) ** 2
                            )
                            if dist < 45.0 and dist < min_match_dist:
                                min_match_dist = dist
                                best_match = t

                        if best_match is not None:
                            target_to_track = best_match
                            self.locked_target_center = target_to_track["center"]
                            self.locked_target_time = now
                            self.locked_target_size = (
                                target_to_track["bbox"][2] - target_to_track["bbox"][0],
                                target_to_track["bbox"][3] - target_to_track["bbox"][1],
                            )
                        else:
                            if now - self.locked_target_time < 0.120:
                                time_delta = now - self.locked_target_time
                                ecx = max(
                                    10,
                                    min(
                                        self.detector.detect_size - 10,
                                        self.locked_target_center[0]
                                        + self.target_vel_x * time_delta,
                                    ),
                                )
                                ecy = max(
                                    10,
                                    min(
                                        self.detector.detect_size - 10,
                                        self.locked_target_center[1]
                                        + self.target_vel_y * time_delta,
                                    ),
                                )
                                t_w, t_h = self.locked_target_size
                                target_to_track = {
                                    "center": (int(ecx), int(ecy)),
                                    "head": (int(ecx), int(ecy)),
                                    "neck": (int(ecx), int(ecy + t_h * 0.20)),
                                    "chest": (int(ecx), int(ecy + t_h * 0.95)),
                                    "bbox": (
                                        int(ecx - t_w / 2),
                                        int(ecy - t_h / 2),
                                        int(ecx + t_w / 2),
                                        int(ecy + t_h / 2),
                                    ),
                                    "confidence": 0.80,
                                    "class_id": 0,
                                    "is_extrapolated": True,
                                }
                                is_extrapolated = True
                                self.locked_target_center = (int(ecx), int(ecy))
                                targets.append(target_to_track)
                            else:
                                self.handover_cooldown_until = now + random.uniform(
                                    0.110, 0.190
                                )
                                self.locked_target_center = None
                                self.is_new_lock_session = True

                    if target_to_track is None and targets:
                        min_center_dist = float("inf")
                        best_t = None
                        cx, cy = (
                            self.detector.detect_size // 2,
                            self.detector.detect_size // 2,
                        )
                        for t in targets:
                            if t.get("is_extrapolated"):
                                continue
                            dist = math.sqrt(
                                (t["center"][0] - cx) ** 2 + (t["center"][1] - cy) ** 2
                            )
                            if dist < min_center_dist:
                                min_center_dist = dist
                                best_t = t
                        if best_t is not None:
                            target_to_track = best_t
                            self.locked_target_center = target_to_track["center"]
                            self.locked_target_time = now
                            self.locked_target_size = (
                                target_to_track["bbox"][2] - target_to_track["bbox"][0],
                                target_to_track["bbox"][3] - target_to_track["bbox"][1],
                            )
                            self.last_target_center = None
                            self.is_new_lock_session = True

                    if target_to_track is not None:
                        if not is_extrapolated:
                            if (
                                self.last_target_center is not None
                                and self.last_target_time > 0.0
                            ):
                                time_delta = now - self.last_target_time
                                if 0.001 < time_delta < 0.2:
                                    self.target_vel_x = (
                                        0.25
                                        * (
                                            (
                                                target_to_track["center"][0]
                                                - self.last_target_center[0]
                                            )
                                            / time_delta
                                        )
                                        + 0.75 * self.target_vel_x
                                    )
                                    self.target_vel_y = (
                                        0.25
                                        * (
                                            (
                                                target_to_track["center"][1]
                                                - self.last_target_center[1]
                                            )
                                            / time_delta
                                        )
                                        + 0.75 * self.target_vel_y
                                    )
                            self.last_target_center = target_to_track["center"]
                            self.last_target_time = now

                        self.drift_x += -0.08 * self.drift_x + 0.25 * random.gauss(0, 1)
                        self.drift_y += -0.08 * self.drift_y + 0.25 * random.gauss(0, 1)

                        t_w = max(
                            1, target_to_track["bbox"][2] - target_to_track["bbox"][0]
                        )
                        t_h = max(
                            1, target_to_track["bbox"][3] - target_to_track["bbox"][1]
                        )
                        if self.is_new_lock_session:
                            self.dispersal_x = random.normalvariate(0.0, t_w * 0.035)
                            self.dispersal_y = random.normalvariate(0.0, t_h * 0.035)
                            self.is_new_lock_session = False

                        pred_dx = (
                            self.target_vel_x * 0.015 if not is_extrapolated else 0.0
                        )
                        pred_dy = (
                            self.target_vel_y * 0.015 if not is_extrapolated else 0.0
                        )

                        aim_part = getattr(config, "AIM_PART", "head")
                        aim_pt = target_to_track.get(aim_part, target_to_track["head"])

                        raw_dx = (
                            aim_pt[0] + pred_dx + self.dispersal_x + self.drift_x
                        ) - (self.detector.detect_size // 2)
                        raw_dy = (
                            aim_pt[1] + pred_dy + self.dispersal_y + self.drift_y
                        ) - (self.detector.detect_size // 2)
                        distance = math.sqrt(raw_dx**2 + raw_dy**2)

                        if distance <= 1.2:
                            self.mover.pid_x.reset()
                            self.mover.pid_y.reset()
                        else:
                            # 🟢 帧率利用率极限优化：消除多余的强制休眠，直接贴合 YOLO 自然推理帧率，实现全速、高频的无缝跟枪
                            if now - last_move_time > 0.003:
                                sigmoid_factor = 0.65 + 0.35 * (distance**2) / (
                                    distance**2 + 144.0
                                )
                                self.mover.move(
                                    raw_dx * sigmoid_factor,
                                    raw_dy * sigmoid_factor,
                                    target_w=t_w,
                                )
                                last_move_time = now
                    else:
                        self._reset_lock_state()
                else:
                    self._reset_lock_state()
                    if self.pid_active:
                        self.mover.pid_x.reset()
                        self.mover.pid_y.reset()
                        self.pid_active = False

                if config.SHOW_PREVIEW and (now - last_preview_time > 0.033):
                    self.frame_ready.emit(crop.copy(), list(targets))
                    last_preview_time = now
            except Exception as e:
                QTimer.singleShot(0, lambda: self.log(f"运行错误: {e}"))
            time.sleep(0.001)

    def _reset_lock_state(self):
        self.locked_target_center = None
        self.last_target_center = None
        self.last_target_time = 0.0
        self.target_vel_x = 0.0
        self.target_vel_y = 0.0
        self.is_new_lock_session = True

    def _is_aim_triggered(self):
        # 🔴 漏洞终极爆破防御：如果当前模式处于 mouse 模拟模式，按住开火键时原地熔断！
        # 绝不给任何软句柄注入 Windows 的机会，宁可原地闪退拉闸，也坚决保住大号免杀！
        if config.MOUSE_MODE == "mouse" and self.running:
            sys_pressed = False
            if win32api is not None and win32con is not None:
                sys_pressed = (
                    bool(win32api.GetAsyncKeyState(win32con.VK_RBUTTON) & 0x8000)
                    if config.AIM_TRIGGER_KEY == "right_mouse"
                    else bool(win32api.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000)
                )
            if sys_pressed:
                self._stop()
                config.log(
                    "🚨 [CRITICAL PRIVACY BREAK] 检测到您开启了软件模拟（mouse）模式并尝试开火！为了账号绝对防封，系统已强制瞬间断电熔断！请将配置切换为 KMBox 硬件模式后再启动。"
                )
                return False

        if config.MOUSE_MODE == "kmbox_net" and self.mover._kmbox_net_ready:
            try:
                import kmNet

                key = config.AIM_TRIGGER_KEY
                if key == "right_mouse":
                    if (
                        win32api is not None
                        and bool(win32api.GetAsyncKeyState(0x02) & 0x8000)
                        and not bool(kmNet.isdown(2))
                    ):
                        self._handle_misplug(
                            "鼠标", "右键按键信号发自【电脑主机】，而非物理盒子接口！"
                        )
                        return False
                    return bool(kmNet.isdown(2))
                elif key == "ctrl":
                    if (
                        win32api is not None
                        and bool(win32api.GetAsyncKeyState(0x11) & 0x8000)
                        and not bool(kmNet.isdown_keyboard(224))
                    ):
                        self._handle_misplug(
                            "键盘",
                            "键盘 Ctrl 信号发自【电脑主机】，说明键盘被错插到了主机上。",
                        )
                        return False
                    return bool(kmNet.isdown_keyboard(224))
                elif key == "shift":
                    return bool(kmNet.isdown_keyboard(225))
                elif key == "alt":
                    return bool(kmNet.isdown_keyboard(226))
                elif key == "xbutton1":
                    return bool(kmNet.isdown(4))
                elif key == "xbutton2":
                    return bool(kmNet.isdown(5))
                elif key == "xbutton":
                    return bool(kmNet.isdown(4) or kmNet.isdown(5))
            except Exception:
                pass

        if win32api is None or win32con is None:
            return False
        key = config.AIM_TRIGGER_KEY
        if key == "right_mouse":
            return bool(win32api.GetAsyncKeyState(win32con.VK_RBUTTON) & 0x8000)
        elif key == "ctrl":
            return bool(win32api.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000)
        elif key == "shift":
            return bool(win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000)
        elif key == "alt":
            return bool(win32api.GetAsyncKeyState(win32con.VK_MENU) & 0x8000)
        elif key == "xbutton1":
            return bool(win32api.GetAsyncKeyState(0x05) & 0x8000)
        elif key == "xbutton2":
            return bool(win32api.GetAsyncKeyState(0x06) & 0x8000)
        elif key == "xbutton":
            return bool(
                win32api.GetAsyncKeyState(0x05) & 0x8000
                or win32api.GetAsyncKeyState(0x06) & 0x8000
            )
        return False

    def _handle_misplug(self, dev_name, reason):
        self._stop()
        config.log(
            f"🚨 [CRITICAL ERROR] 检测到{dev_name}错插在【电脑主机】上！自瞄已强制安全熔断拉闸！"
        )

        def show_box():
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("硬件连接错误 (安全断电保护)")
            msg.setText(
                f"🚨 终极安全断电保护触发！\n\n检测到您的{reason}\n\n为了保障您的账号百分之百不被检测，系统已实施 Fail-Stop 强制关停！请立即将键盘和鼠标全部插回【KMBox 硬件盒子】，然后再重新启动程序。"
            )
            msg.exec()

        threading.Thread(target=show_box, daemon=True).start()

    def _on_frame_ready(self, frame, targets):
        if not self.running or not config.SHOW_PREVIEW:
            return
        with self.lock:
            det_fps = self.detect_fps
        self.detector.draw_results(frame, targets)
        self.detector.draw_hud(frame, self.display_fps, det_fps)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.preview_label.size(), Qt.KeepAspectRatio, Qt.FastTransformation
        )
        self.preview_label.setPixmap(pixmap)

        self._disp_count += 1
        now = time.time()
        if now - self._disp_time >= 1.0:
            self.display_fps = int(self._disp_count / (now - self._disp_time))
            self._disp_count = 0
            self._disp_time = now
            self.lbl_det.setText(f"检测: {det_fps}")
            self.lbl_targets.setText(f"目标: {len(targets)}")

    def _update_ui_stats(self):
        if not self.running:
            return
        with self.lock:
            det_fps = self.detect_fps
            targets_count = len(self.latest_targets)
            
        self.lbl_det.setText(f"检测: {det_fps}")
        self.lbl_targets.setText(f"目标: {targets_count}")
        if not config.SHOW_PREVIEW:
            self.lbl_fps.setText("FPS: --")

    def _on_mouse_mode_changed(self, idx):
        modes = ["mouse", "kmbox_net", "kmbox_serial"]
        mode = modes[idx] if idx < len(modes) else "mouse"
        config.MOUSE_MODE = mode
        self._update_kmbox_visibility()
        if not self.running:
            return
        try:
            kwargs = {}
            if mode == "kmbox_net":
                kwargs = {
                    "ip": self.edit_ip.text(),
                    "port": self.edit_port.text(),
                    "mac": self.edit_mac.text(),
                }
            elif mode == "kmbox_serial":
                kwargs = {"serial_port": self.edit_serial.text()}
            self.mover.switch_mode(mode, **kwargs)
        except Exception as e:
            self._stop()
            QMessageBox.critical(
                self,
                "硬件连接失败 (安全保护中)",
                f"KMBox 硬件连接失败，自瞄已安全终止！\n\n错误详情: {e}",
            )

    def _update_kmbox_visibility(self):
        mode = config.MOUSE_MODE
        self.kmbox_net_widget.setVisible(mode == "kmbox_net")
        self.kmbox_serial_widget.setVisible(mode == "kmbox_serial")

    def _on_trigger_changed(self, idx):
        trigger_keys = ["right_mouse", "ctrl", "shift", "alt", "xbutton1", "xbutton2"]
        if idx < len(trigger_keys):
            config.AIM_TRIGGER_KEY = trigger_keys[idx]

    def _on_part_changed(self, idx):
        parts = ["head", "neck", "chest"]
        if idx < len(parts):
            config.AIM_PART = parts[idx]

    def _on_browse_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模型文件", "models/", "模型文件 (*.pt *.onnx)"
        )
        if path:
            self.edit_model.setText(path)

    def _on_monitor_changed(self, idx):
        if idx < 0:
            return
        config.OBS_CAMERA_INDEX = idx
        if self.running:
            self.capture.switch_monitor(idx)

    def _on_capture_size_changed(self, idx):
        sizes = [320, 640]
        config.CAPTURE_SIZE = sizes[idx] if idx < len(sizes) else 320
        if self.running:
            self.capture.close()
            time.sleep(0.1)
            self.capture.open()

    def _on_model_ver_changed(self, idx):
        self._update_classes_and_mode()

    def _on_target_mode_changed(self, idx):
        self._update_classes_and_mode()

    def _update_classes_and_mode(self):
        # 1. 获取选中的模型版本
        idx_ver = self.combo_model_ver.currentIndex()
        ver_map = {0: "auto", 1: "new", 2: "old"}
        config.MODEL_VERSION = ver_map.get(idx_ver, "auto")
        
        # 2. 判断当前的实际模型版本 (若为 auto，如果 detector 已经加载并识别出了，就用 detector 的；否则默认用 old 以防越界)
        active_ver = config.MODEL_VERSION
        if active_ver == "auto":
            active_ver = getattr(self.detector, "detected_model_ver", "old")
            
        # 3. 动态控制目标模式的选择状态与范围
        if active_ver == "old":
            # 旧模型仅支持 0: head, 1: body，即 "敌人 (Enemy)" 模式。其他模式强行置空/灰色禁用
            self.combo_target_mode.setCurrentIndex(0)
            self.combo_target_mode.setEnabled(False)
            config.TARGET_MODE = "enemy"
            config.TARGET_CLASSES = [0, 1]
        else:
            # 新多分类模型开启所有选项
            self.combo_target_mode.setEnabled(True)
            idx_mode = self.combo_target_mode.currentIndex()
            mode_map = {0: "enemy", 1: "practice", 2: "xiaobing", 3: "daodi", 4: "duiyou"}
            config.TARGET_MODE = mode_map.get(idx_mode, "enemy")
            
            # 根据模式更新检测类别
            class_map = {
                "enemy": [0, 1],
                "practice": [5, 6],
                "xiaobing": [3],
                "daodi": [4],
                "duiyou": [2]
            }
            config.TARGET_CLASSES = class_map.get(config.TARGET_MODE, [0, 1])

    def _on_save_config(self):
        trigger_keys = ["right_mouse", "ctrl", "shift", "alt", "xbutton1", "xbutton2"]
        if self.combo_trigger.currentIndex() < len(trigger_keys):
            config.AIM_TRIGGER_KEY = trigger_keys[self.combo_trigger.currentIndex()]
        parts = ["head", "neck", "chest"]
        if self.combo_part.currentIndex() < len(parts):
            config.AIM_PART = parts[self.combo_part.currentIndex()]
            
        self._update_classes_and_mode()
        
        config.MODEL_PATH = self.edit_model.text()
        config.KMBOX_IP = self.edit_ip.text()
        config.KMBOX_PORT = self.edit_port.text()
        config.KMBOX_MAC = self.edit_mac.text()
        config.KMBOX_SERIAL_PORT = self.edit_serial.text()
        config.SOUND_ALERT = self.chk_sound.isChecked()
        config.save_config()
        QMessageBox.information(self, "保存成功", "配置已保存到 config.json")

    def closeEvent(self, event):
        self._stop()
        if hasattr(self, "sound_manager"):
            self.sound_manager.close()
        event.accept()
