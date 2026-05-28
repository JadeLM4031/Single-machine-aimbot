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

# ==================== 白色主题样式表 ====================

LIGHT_STYLE = """
QMainWindow, QWidget {
    background-color: #f5f7fa;
    color: #2c3e50;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 12px;
}

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e1e8ed;
    border-radius: 10px;
    margin-top: 14px;
    padding: 16px 10px 10px 10px;
    font-weight: bold;
    font-size: 12px;
    color: #3498db;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
}

QPushButton {
    background-color: #ffffff;
    color: #2c3e50;
    border: 1px solid #dce1e6;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #eaf2fb;
    border-color: #3498db;
    color: #3498db;
}
QPushButton:pressed {
    background-color: #d6eaf8;
}

QComboBox {
    background-color: #ffffff;
    color: #2c3e50;
    border: 1px solid #dce1e6;
    border-radius: 6px;
    padding: 4px 8px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #2c3e50;
    border: 1px solid #dce1e6;
    selection-background-color: #3498db;
    selection-color: white;
}

QSlider::groove:horizontal {
    background: #e1e8ed;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #3498db;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #2980b9;
}
QSlider::sub-page:horizontal {
    background: #3498db;
    border-radius: 3px;
}

QCheckBox {
    color: #5a6c7d;
    spacing: 8px;
    font-size: 11px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 2px solid #c8d1da;
    background-color: #ffffff;
}
QCheckBox::indicator:checked {
    background-color: #3498db;
    border-color: #3498db;
}
QCheckBox::indicator:hover {
    border-color: #3498db;
}

QLineEdit {
    background-color: #ffffff;
    color: #2c3e50;
    border: 1px solid #dce1e6;
    border-radius: 6px;
    padding: 4px 8px;
}
QLineEdit:focus {
    border-color: #3498db;
}

QLabel {
    color: #7f8c9b;
    font-size: 11px;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 4px;
    margin: 4px 0;
}
QScrollBar::handle:vertical {
    background: rgba(0,0,0,0.12);
    border-radius: 2px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0,0,0,0.22);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
"""


class _LogBridge(QObject):
    """子线程 → 主线程的日志信号桥接"""

    log_signal = Signal(str)


class AimWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 🟢 【环境防御】：随机伪装成无害系统/显卡控制台后台服务进程，绕过简单的窗口指纹扫描
        import random as rand_mod
        fake_titles = [
            "NVIDIA Container Overlay",
            "Windows Audio Service Host",
            "Steam Web Helper Overlay",
            "Microsoft OneDrive Sync",
            "Intel Graphics Control Panel",
            "Realtek Audio Universal Service",
            "Xbox Live Game Overlay"
        ]
        config.WINDOW_TITLE = rand_mod.choice(fake_titles)
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setMinimumSize(1120, 680)
        self.setStyleSheet(LIGHT_STYLE)

        self.capture = OBSCapture()
        self.detector = Detector()
        self.mover = MouseController()

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
        
        # 🟢 【行为特征防御】：引入生理学神经反射和控制决策参数
        self.handover_cooldown_until = 0.0  # 击毙/丢失后的反应时间冷却（秒）
        self.drift_x = 0.0                  # 生理性 ocular Fixational Drift 微颤 (X轴)
        self.drift_y = 0.0                  # 生理性 ocular Fixational Drift 微颤 (Y轴)
        self.dispersal_x = 0.0              # 人眼锁敌时的高斯落点偏置 (X轴)
        self.dispersal_y = 0.0              # 人眼锁敌时的高斯落点偏置 (Y轴)
        self.is_new_lock_session = True     # 标志是否是新一次锁敌会话，用于重新生成固定高斯落点偏置
        
        self.detect_fps = 0
        self._det_count = 0
        self._det_time = time.time()
        self.display_fps = 0
        self._disp_count = 0
        self._disp_time = time.time()

        self._build_ui()
        self._connect_signals()

        self._log_bridge = _LogBridge()
        self._log_bridge.log_signal.connect(self._on_log)
        config._log_callback = lambda line: self._log_bridge.log_signal.emit(line)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_frame)

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
            "color: #3498db; font-size: 20px; font-weight: bold; "
            "letter-spacing: 6px; padding: 6px 0;"
        )
        header.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(header)

        self.preview_label = QLabel("点击「开始」运行")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(640, 480)
        self.preview_label.setStyleSheet(
            "background-color: #eef1f5; color: #b0b8c1; "
            "border: 1px solid #dce1e6; border-radius: 10px; font-size: 14px;"
        )
        left_layout.addWidget(self.preview_label, stretch=1)

        status_bar = QFrame()
        status_bar.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #e1e8ed; "
            "border-radius: 8px; padding: 4px 12px; }"
        )
        status_bar.setFixedHeight(34)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(14, 0, 14, 0)

        self.lbl_status = QLabel("状态: 未启动")
        self.lbl_status.setStyleSheet(
            "color: #a0aab4; font-size: 11px; font-weight: bold;"
        )
        self.lbl_fps = QLabel("FPS: --")
        self.lbl_fps.setStyleSheet(
            "color: #27ae60; font-size: 11px; font-weight: bold;"
        )
        self.lbl_det = QLabel("检测: --")
        self.lbl_det.setStyleSheet(
            "color: #e67e22; font-size: 11px; font-weight: bold;"
        )
        self.lbl_targets = QLabel("目标: 0")
        self.lbl_targets.setStyleSheet(
            "color: #3498db; font-size: 11px; font-weight: bold;"
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
        self.log_box.setStyleSheet(
            "QTextEdit { background-color: #1e1e2e; color: #a6e3a1; "
            "border: 1px solid #313244; border-radius: 6px; "
            "padding: 4px 6px; font-family: Consolas, monospace; font-size: 11px; }"
            "QScrollBar:vertical { width: 4px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,0.15); border-radius: 2px; }"
        )
        self.log_lines = []
        left_layout.addWidget(self.log_box)

        main_layout.addWidget(left_widget, stretch=3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        panel = QWidget()
        panel.setMinimumWidth(280)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(8)
        panel_layout.setContentsMargins(8, 8, 20, 8)

        self.btn_toggle = QPushButton("▶  开始")
        self.btn_toggle.setFixedHeight(44)
        self.btn_toggle.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; "
            "background-color: #27ae60; color: white; border: none; border-radius: 10px; }"
            "QPushButton:hover { background-color: #2ecc71; }"
        )
        panel_layout.addWidget(self.btn_toggle)

        aim_group = QGroupBox("瞄准设置")
        aim_layout = QVBoxLayout(aim_group)
        aim_layout.setSpacing(6)

        self._add_label(aim_layout, "触发键")
        self.combo_trigger = QComboBox()
        self.combo_trigger.addItems(
            ["鼠标右键", "Ctrl", "Shift", "Alt", "鼠标侧键"]
        )
        trigger_map = {
            "right_mouse": 0,
            "ctrl": 1,
            "shift": 2,
            "alt": 3,
            "xbutton": 4,
        }
        self.combo_trigger.setCurrentIndex(trigger_map.get(config.AIM_TRIGGER_KEY, 0))
        aim_layout.addWidget(self.combo_trigger)

        self._add_label(aim_layout, "瞄准部位")
        self.combo_part = QComboBox()
        self.combo_part.addItems(["头部", "颈部", "胸部"])
        part_map = {"head": 0, "neck": 1, "chest": 2}
        self.combo_part.setCurrentIndex(part_map.get(getattr(config, "AIM_PART", "head"), 0))
        aim_layout.addWidget(self.combo_part)

        self._add_label(aim_layout, "平滑度")
        smooth_row = QHBoxLayout()
        self.slider_smooth = QSlider(Qt.Horizontal)
        self.slider_smooth.setRange(1, 10)
        self.slider_smooth.setValue(int(config.SMOOTH_FACTOR * 10))
        self.lbl_smooth = QLabel(f"{config.SMOOTH_FACTOR:.1f}")
        self.lbl_smooth.setFixedWidth(30)
        self.lbl_smooth.setStyleSheet("color: #3498db; font-weight: bold;")
        smooth_row.addWidget(self.slider_smooth)
        smooth_row.addWidget(self.lbl_smooth)
        aim_layout.addLayout(smooth_row)

        self._add_label(aim_layout, "置信度")
        conf_row = QHBoxLayout()
        self.slider_conf = QSlider(Qt.Horizontal)
        self.slider_conf.setRange(1, 10)
        self.slider_conf.setValue(int(config.CONFIDENCE_THRESHOLD * 10))
        self.lbl_conf = QLabel(f"{config.CONFIDENCE_THRESHOLD:.1f}")
        self.lbl_conf.setFixedWidth(30)
        self.lbl_conf.setStyleSheet("color: #3498db; font-weight: bold;")
        conf_row.addWidget(self.slider_conf)
        conf_row.addWidget(self.lbl_conf)
        aim_layout.addLayout(conf_row)

        panel_layout.addWidget(aim_group)

        mouse_group = QGroupBox("鼠标模式")
        mouse_layout = QVBoxLayout(mouse_group)
        mouse_layout.setSpacing(6)

        self.combo_mouse = QComboBox()
        self.combo_mouse.addItems(["真鼠标 (Win32)", "KMBox 网络", "KMBox 串口"])
        mode_map = {"mouse": 0, "kmbox_net": 1, "kmbox_serial": 2}
        self.combo_mouse.setCurrentIndex(mode_map.get(config.MOUSE_MODE, 0))
        mouse_layout.addWidget(self.combo_mouse)

        self.kmbox_net_widget = QWidget()
        km_net_layout = QVBoxLayout(self.kmbox_net_widget)
        km_net_layout.setContentsMargins(0, 0, 0, 0)
        km_net_layout.setSpacing(4)
        ip_row = QHBoxLayout()
        ip_lbl = QLabel("IP")
        ip_lbl.setFixedWidth(30)
        self.edit_ip = QLineEdit(config.KMBOX_IP)
        ip_row.addWidget(ip_lbl)
        ip_row.addWidget(self.edit_ip)
        km_net_layout.addLayout(ip_row)
        port_row = QHBoxLayout()
        port_lbl = QLabel("端口")
        port_lbl.setFixedWidth(30)
        self.edit_port = QLineEdit(str(config.KMBOX_PORT))
        port_row.addWidget(port_lbl)
        port_row.addWidget(self.edit_port)
        km_net_layout.addLayout(port_row)
        mac_row = QHBoxLayout()
        mac_lbl = QLabel("MAC")
        mac_lbl.setFixedWidth(30)
        self.edit_mac = QLineEdit(config.KMBOX_MAC)
        self.edit_mac.setPlaceholderText("设备底部标签")
        mac_row.addWidget(mac_lbl)
        mac_row.addWidget(self.edit_mac)
        km_net_layout.addLayout(mac_row)
        mouse_layout.addWidget(self.kmbox_net_widget)

        self.kmbox_serial_widget = QWidget()
        km_ser_layout = QVBoxLayout(self.kmbox_serial_widget)
        km_ser_layout.setContentsMargins(0, 0, 0, 0)
        ser_row = QHBoxLayout()
        ser_lbl = QLabel("串口")
        ser_lbl.setFixedWidth(30)
        self.edit_serial = QLineEdit(config.KMBOX_SERIAL_PORT)
        ser_row.addWidget(ser_lbl)
        ser_row.addWidget(self.edit_serial)
        km_ser_layout.addLayout(ser_row)
        mouse_layout.addWidget(self.kmbox_serial_widget)

        self._update_kmbox_visibility()
        panel_layout.addWidget(mouse_group)

        display_group = QGroupBox("显示设置")
        display_layout = QVBoxLayout(display_group)
        display_layout.setSpacing(3)

        self.chk_preview = QCheckBox("预览画面")
        self.chk_preview.setChecked(config.SHOW_PREVIEW)
        self.chk_bbox = QCheckBox("检测框")
        self.chk_bbox.setChecked(config.SHOW_BBOX)
        self.chk_crosshair = QCheckBox("准心")
        self.chk_crosshair.setChecked(config.SHOW_CROSSHAIR)
        self.chk_perf = QCheckBox("性能统计")
        self.chk_perf.setChecked(config.SHOW_PERF)

        for chk in [
            self.chk_preview,
            self.chk_bbox,
            self.chk_crosshair,
            self.chk_perf,
        ]:
            display_layout.addWidget(chk)
        panel_layout.addWidget(display_group)

        model_group = QGroupBox("模型")
        model_layout = QVBoxLayout(model_group)
        model_row = QHBoxLayout()
        self.edit_model = QLineEdit(config.MODEL_PATH)
        self.edit_model.setPlaceholderText("模型路径 (.pt / .onnx)")
        self.btn_model = QPushButton("浏览")
        self.btn_model.setFixedWidth(56)
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
        self.btn_save.setStyleSheet(
            "QPushButton { background-color: #ffffff; color: #3498db; "
            "border: 1px solid #3498db; border-radius: 8px; "
            "padding: 8px; font-weight: bold; font-size: 11px; }"
            "QPushButton:hover { background-color: #eaf2fb; }"
        )
        panel_layout.addWidget(self.btn_save)
        panel_layout.addStretch()

        scroll.setWidget(panel)
        main_layout.addWidget(scroll, stretch=1)

        for w in panel.findChildren(QComboBox):
            w.installEventFilter(self)
        for w in panel.findChildren(QSlider):
            w.installEventFilter(self)

    @staticmethod
    def _add_label(layout, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #95a5b6; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )
        layout.addWidget(lbl)

    def _connect_signals(self):
        self.btn_toggle.clicked.connect(self._toggle_run)
        self.combo_mouse.currentIndexChanged.connect(self._on_mouse_mode_changed)
        self.combo_trigger.currentIndexChanged.connect(self._on_trigger_changed)
        self.combo_part.currentIndexChanged.connect(self._on_part_changed)
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

    def _on_log(self, line):
        self.log_lines.append(line)
        if len(self.log_lines) > 100:
            self.log_lines = self.log_lines[-100:]
        self.log_box.setText("\n".join(self.log_lines))
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def log(self, msg):
        config.log(msg)

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
            self._on_mouse_mode_changed(self.combo_mouse.currentIndex())
        except Exception as e:
            config.log(f"启动失败: {e}")
            QMessageBox.critical(self, "启动失败", str(e))
            return

        self.running = True
        self.btn_toggle.setText("■  停止")
        self.btn_toggle.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; "
            "background-color: #e74c3c; color: white; border: none; border-radius: 10px; }"
            "QPushButton:hover { background-color: #ec7063; }"
        )
        self.lbl_status.setText("状态: 运行中")
        self.lbl_status.setStyleSheet(
            "color: #27ae60; font-size: 11px; font-weight: bold;"
        )

        t = threading.Thread(target=self._detect_loop, daemon=True)
        t.start()
        self.timer.start(16)

    def _stop(self):
        self.running = False
        self.timer.stop()
        self.capture.close()
        self.mover.close()
        config.log("已停止")

        self.btn_toggle.setText("▶  开始")
        self.btn_toggle.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; "
            "background-color: #27ae60; color: white; border: none; border-radius: 10px; }"
            "QPushButton:hover { background-color: #2ecc71; }"
        )
        self.lbl_status.setText("状态: 已停止")
        self.lbl_status.setStyleSheet(
            "color: #a0aab4; font-size: 11px; font-weight: bold;"
        )
        self.lbl_fps.setText("FPS: --")
        self.lbl_det.setText("检测: --")
        self.lbl_targets.setText("目标: 0")
        self.preview_label.setText("点击「开始」运行")

    def _detect_loop(self):
        last_move_time = 0
        last_frame_ptr = None

        while self.running:
            try:
                frame = self.capture.read()
                if frame is None:
                    time.sleep(0.001)
                    continue

                if id(frame) == last_frame_ptr:
                    time.sleep(0.001)
                    continue
                last_frame_ptr = id(frame)

                # 2. 送入 YOLO 模型检测
                crop, offset = self.capture.crop_detect_region(frame)
                targets = self.detector.detect(crop)

                # 3. 🟢 核心改动：两边各自安好
                # 存一份给 UI 绘制用的全局坐标（让绿框完美挂在人头上）
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
                    # UI 拿有加偏置的，自瞄用纯局部未污染坐标
                    self.latest_targets = targets_global
                    self.latest_targets_local = targets

                self._det_count += 1
                now = time.time()
                if now - self._det_time >= 1.0:
                    self.detect_fps = int(self._det_count / (now - self._det_time))
                    config.log(f"[Module] Processing FPS: {self.detect_fps}")
                    self._det_count = 0
                    self._det_time = now

                # 5. 触发逻辑：完全基于 320x320 切片相对偏差进行拟人化 PID 自瞄
                if self._is_aim_triggered():
                    self.pid_active = True
                    
                    # 🟢 生理神经反应延迟：如果处于击毙目标或丢失目标的反应认知期内，则不产生鼠标移动，完美模拟大脑判断时间
                    if now < self.handover_cooldown_until:
                        self.last_target_center = None
                        self.last_target_time = 0.0
                        self.target_vel_x = 0.0
                        self.target_vel_y = 0.0
                        self.is_new_lock_session = True
                        continue

                    if targets:
                        # 🟢 第一阶段：智能目标选择与短期锁定记忆机制
                        target_to_track = None
                        
                        # 检查是否有锁定时间记忆（500ms 内）
                        if self.locked_target_center is not None and now - self.locked_target_time < 0.5:
                            # 寻找原锁定点 45 像素邻域内的目标
                            min_match_dist = float('inf')
                            best_match = None
                            for t in targets:
                                tx, ty = t["center"]
                                lx, ly = self.locked_target_center
                                dist = math.sqrt((tx - lx)**2 + (ty - ly)**2)
                                if dist < 45.0:  # 45像素追踪阈值
                                    if dist < min_match_dist:
                                        min_match_dist = dist
                                        best_match = t
                            if best_match is not None:
                                target_to_track = best_match
                            else:
                                # 🟢 【行为核心优化】：原追踪目标在这一帧丢失/被击毙！立刻注入 110ms~190ms 的随机人类神经反射冷却
                                # 彻底消灭 0 毫秒瞬间 snapping 反人类指纹，保护物理行为曲线不被上传审计
                                self.handover_cooldown_until = now + random.uniform(0.110, 0.190)
                                self.locked_target_center = None
                                self.is_new_lock_session = True

                        # 🟢 第二阶段：击毙秒切/无锁定记忆时，选择离当前准心最近的敌人（Crosshair Proximity Priority）
                        if target_to_track is None:
                            min_center_dist = float('inf')
                            best_t = targets[0]
                            crop_h, crop_w = frame.shape[:2]
                            cx, cy = crop_w // 2, crop_h // 2
                            
                            for t in targets:
                                tx, ty = t["center"]
                                dist = math.sqrt((tx - cx)**2 + (ty - cy)**2)
                                if dist < min_center_dist:
                                    min_center_dist = dist
                                    best_t = t
                            target_to_track = best_t

                        # 🟢 第三阶段：更新锁敌追踪记忆并计算自适应 EMA 运动预测，最后执行自瞄
                        if target_to_track is not None:
                            self.locked_target_center = target_to_track["center"]
                            self.locked_target_time = now
                            
                            # 🟢 【生理抖动微漂移】：更新低频且极其平滑的 ocular fixational drift 生理眼球微游离位移 (自回归过程)
                            # 漂移回归系数 0.08 (极缓)，标准差 0.25 (超精细子像素级别手抖)，让准心产生极其自然的生物颤动
                            self.drift_x += -0.08 * self.drift_x + 0.25 * random.gauss(0, 1)
                            self.drift_y += -0.08 * self.drift_y + 0.25 * random.gauss(0, 1)

                            # 🟢 【落点随机离散化】：如果是新锁敌或刚切目标，随机生成本轮锁敌的高斯定点偏差 (标准差为目标包长宽的 3.5%)
                            # 代表人眼聚焦时无法 100% 对齐到完美物理中点的天然视差误差，在持续锁敌期间该偏差保持锁定
                            x1, y1, x2, y2 = target_to_track["bbox"]
                            t_w = max(1, x2 - x1)
                            t_h = max(1, y2 - y1)
                            if self.is_new_lock_session:
                                self.dispersal_x = random.normalvariate(0.0, t_w * 0.035)
                                self.dispersal_y = random.normalvariate(0.0, t_h * 0.035)
                                self.is_new_lock_session = False
                            
                            # 🟢 运动预测提前量估算 (极轻量级卡尔曼式 EMA 速度滤波器)
                            pred_dx = 0.0
                            pred_dy = 0.0
                            
                            if self.last_target_center is not None and self.last_target_time > 0.0:
                                last_cx, last_cy = self.last_target_center
                                current_cx, current_cy = target_to_track["center"]
                                time_delta = now - self.last_target_time
                                
                                # 限制时差范围在 1ms 到 200ms 内，防止大掉帧或初始帧带来的瞬时极端速度
                                if 0.001 < time_delta < 0.2:
                                    # 瞬时相对移动速度 (像素/秒)
                                    inst_vx = (current_cx - last_cx) / time_delta
                                    inst_vy = (current_cy - last_cy) / time_delta
                                    
                                    # EMA 指数滑动平均平滑去噪，滤波因子 0.2
                                    self.target_vel_x = 0.2 * inst_vx + 0.8 * self.target_vel_x
                                    self.target_vel_y = 0.2 * inst_vy + 0.8 * self.target_vel_y
                                    
                                    # 物理预测补偿时间 (截屏延迟 + 推理延迟约 15 毫秒)
                                    compensation_time = 0.015
                                    pred_dx = self.target_vel_x * compensation_time
                                    pred_dy = self.target_vel_y * compensation_time
                                    
                            # 更新历史追踪缓存
                            self.last_target_center = target_to_track["center"]
                            self.last_target_time = now

                            # 计算带运动预测提前量、生理漂移与高斯离散弹着点的最终目标坐标
                            aim_part = getattr(config, "AIM_PART", "head")
                            aim_pt = target_to_track.get(aim_part, target_to_track["head"])
                            aim_x = aim_pt[0] + pred_dx + self.dispersal_x + self.drift_x
                            aim_y = aim_pt[1] + pred_dy + self.dispersal_y + self.drift_y

                            crop_h, crop_w = frame.shape[:2]
                            center_x = crop_w // 2
                            center_y = crop_h // 2

                            raw_dx = aim_x - center_x
                            raw_dy = aim_y - center_y

                            distance = math.sqrt(raw_dx**2 + raw_dy**2)

                            # 2像素死区判定，彻底杜绝准心最后阶段频繁发包抽搐
                            if distance <= 2.5:
                                self.mover.pid_x.reset()
                                self.mover.pid_y.reset()
                                continue

                            # 🟢 终极防抖与高刷同步发包
                            if now - last_move_time > random.uniform(0.010, 0.015):
                                # 🟢 【核心优化】：代数 Sigmoid 连续粘滞阻尼平滑算法，替代原始死板的阶梯限速
                                # 极近距离下提供 0.45 磁性粘性，远距离快速拉枪渐近线收敛于 1.0，过渡半宽 k=12.0 像素 (k^2 = 144)
                                sigmoid_factor = 0.45 + 0.55 * (distance**2) / (distance**2 + 144.0)
                                x1, y1, x2, y2 = target_to_track["bbox"]
                                t_w = max(1, x2 - x1)
                                self.mover.move(raw_dx * sigmoid_factor, raw_dy * sigmoid_factor, target_w=t_w)
                                last_move_time = now
                        else:
                            self.locked_target_center = None
                            self.last_target_center = None
                            self.last_target_time = 0.0
                            self.target_vel_x = 0.0
                            self.target_vel_y = 0.0
                            self.mover.pid_x.reset()
                            self.mover.pid_y.reset()
                            self.is_new_lock_session = True
                    else:
                        self.locked_target_center = None
                        self.last_target_center = None
                        self.last_target_time = 0.0
                        self.target_vel_x = 0.0
                        self.target_vel_y = 0.0
                        self.mover.pid_x.reset()
                        self.mover.pid_y.reset()
                        self.is_new_lock_session = True
                else:
                    self.locked_target_center = None
                    self.last_target_center = None
                    self.last_target_time = 0.0
                    self.target_vel_x = 0.0
                    self.target_vel_y = 0.0
                    self.is_new_lock_session = True
                    # 🟢 PID 状态锁优化：仅在从“活跃”切换至“非活跃”的瞬间重置一次，避免高频静止帧空转刷新
                    if self.pid_active:
                        self.mover.pid_x.reset()
                        self.mover.pid_y.reset()
                        self.pid_active = False

            except Exception as e:
                QTimer.singleShot(0, lambda: self.log(f"运行错误: {e}"))

            time.sleep(0.001)

    def _is_aim_triggered(self):
        if win32api is None or win32con is None:
            return False
        key = config.AIM_TRIGGER_KEY
        try:
            if key == "right_mouse":
                return bool(win32api.GetAsyncKeyState(win32con.VK_RBUTTON) & 0x8000)
            elif key == "ctrl":
                return bool(win32api.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000)
            elif key == "shift":
                return bool(win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000)
            elif key == "alt":
                return bool(win32api.GetAsyncKeyState(win32con.VK_MENU) & 0x8000)
            elif key == "xbutton":
                return bool(win32api.GetAsyncKeyState(0x05) & 0x8000)
        except Exception:
            pass
        return False

    def _update_frame(self):
        if not self.running or not config.SHOW_PREVIEW:
            return

        ret, frame = self.capture.retrieve()
        if not ret or frame is None or frame.size == 0:
            return

        with self.lock:
            targets = list(self.latest_targets_local)
            det_fps = self.detect_fps

        self.detector.draw_results(frame, targets)
        self.detector.draw_hud(frame, self.display_fps, det_fps)

        if config.SHOW_PERF:
            cv2.putText(
                frame,
                f"Targets: {len(targets)}",
                (10, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 0),
                1,
            )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(pixmap)

        self._disp_count += 1
        now = time.time()
        if now - self._disp_time >= 1.0:
            self.display_fps = int(self._disp_count / (now - self._disp_time))
            self._disp_count = 0
            self._disp_time = now
            self.lbl_fps.setText(f"FPS: {self.display_fps}")
            self.lbl_det.setText(f"检测: {det_fps}")
            self.lbl_targets.setText(f"目标: {len(targets)}")

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
            self.mover.mode = "mouse"
            config.MOUSE_MODE = "mouse"
            self.combo_mouse.blockSignals(True)
            self.combo_mouse.setCurrentIndex(0)
            self.combo_mouse.blockSignals(False)
            self._update_kmbox_visibility()
            config.log(f"[Output] Interface link error: {e}")
            QMessageBox.warning(
                self, "连接失败", f"KMBox 连接失败，已回退到真鼠标模式。\n\n{e}"
            )

    def _update_kmbox_visibility(self):
        mode = config.MOUSE_MODE
        self.kmbox_net_widget.setVisible(mode == "kmbox_net")
        self.kmbox_serial_widget.setVisible(mode == "kmbox_serial")

    def _on_trigger_changed(self, idx):
        trigger_keys = ["right_mouse", "ctrl", "shift", "alt", "xbutton"]
        if idx < len(trigger_keys):
            config.AIM_TRIGGER_KEY = trigger_keys[idx]

    def _on_part_changed(self, idx):
        parts = ["head", "neck", "chest"]
        if idx < len(parts):
            config.AIM_PART = parts[idx]

    def _on_smooth_changed(self, val):
        config.SMOOTH_FACTOR = val / 10.0
        self.mover.smooth = config.SMOOTH_FACTOR
        self.lbl_smooth.setText(f"{config.SMOOTH_FACTOR:.1f}")

    def _on_conf_changed(self, val):
        config.CONFIDENCE_THRESHOLD = val / 10.0
        self.detector.confidence = config.CONFIDENCE_THRESHOLD
        self.lbl_conf.setText(f"{config.CONFIDENCE_THRESHOLD:.1f}")

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
            try:
                self.capture.switch_monitor(idx)
            except Exception as e:
                QMessageBox.warning(self, "切换失败", f"切换显示器失败: {e}")

    def _on_capture_size_changed(self, idx):
        sizes = [320, 640]
        config.CAPTURE_SIZE = sizes[idx] if idx < len(sizes) else 320
        if self.running:
            try:
                self.capture.close()
                time.sleep(0.1)
                self.capture.open()
            except Exception as e:
                QMessageBox.warning(self, "切换失败", f"切换捕获尺寸失败: {e}")

    def _on_save_config(self):
        trigger_keys = ["right_mouse", "ctrl", "shift", "alt", "xbutton"]
        if self.combo_trigger.currentIndex() < len(trigger_keys):
            config.AIM_TRIGGER_KEY = trigger_keys[self.combo_trigger.currentIndex()]
        parts = ["head", "neck", "chest"]
        if self.combo_part.currentIndex() < len(parts):
            config.AIM_PART = parts[self.combo_part.currentIndex()]
        config.MODEL_PATH = self.edit_model.text()
        config.KMBOX_IP = self.edit_ip.text()
        config.KMBOX_PORT = self.edit_port.text()
        config.KMBOX_MAC = self.edit_mac.text()
        config.KMBOX_SERIAL_PORT = self.edit_serial.text()
        config.save_config()
        QMessageBox.information(self, "保存成功", "配置已保存到 config.json")

    def closeEvent(self, event):
        self._stop()
        event.accept()
