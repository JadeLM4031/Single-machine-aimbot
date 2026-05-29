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


class SoundAlertManager:
    """极速声呐声音提示管理器 - 独立后台线程运行，零阻塞自瞄检测"""

    def __init__(self):
        import queue
        self.enabled = False
        self.queue = queue.Queue(maxsize=1)  # 队列大小限制为 1，确保只播报最新状况，丢弃积压信号
        self.last_count = 0
        self.last_play_time = 0.0
        self.cooldown = 1.0  # 1秒冷却，防止人数变动过于频繁时轰炸耳膜
        
        # 听觉去抖动滤波器缓存，防止识别框闪烁时播放“机关枪”重叠爆音
        self.zero_since = 0.0
        self.zero_grace = 0.150  # 150毫秒宽限去抖期
        
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def trigger(self, count):
        """外部触发接口 - 零阻塞瞬间返回"""
        if not self.enabled:
            return
        
        now = time.time()
        
        if count > 0:
            self.zero_since = 0.0  # 重置消失时间缓存
            
            # 只有当目标数量发生变化时，且从 0 到有或过了冷却时间
            if count != self.last_count:
                if now - self.last_play_time >= self.cooldown or self.last_count == 0:
                    # 用非阻塞方式将最新状态塞入队列，如果满了则移出旧值并塞入最新值
                    try:
                        self.queue.put_nowait(count)
                    except Exception:
                        try:
                            self.queue.get_nowait()
                            self.queue.put_nowait(count)
                        except Exception:
                            pass
        else:
            # 当前帧没有任何目标 (count == 0)
            if self.last_count > 0:
                if self.zero_since == 0.0:
                    self.zero_since = now  # 记录首次消失的时间戳
                elif now - self.zero_since >= self.zero_grace:
                    # 只有持续丢失目标超过 150 毫秒，才被认定为真正丢失，清空锁定记录并重置零锁
                    self.last_count = 0
                    self.zero_since = 0.0

    def _worker(self):
        import winsound
        while self.running:
            try:
                # 阻塞式等待，直到队列中有新的目标数需要播报
                count = self.queue.get(timeout=0.1)
            except Exception:
                continue

            if not self.running:
                break
                
            try:
                # 根据目标数量播报专属声呐频率 (极速60ms单音，4个以上播放超短双音)
                if count == 1:
                    winsound.Beep(800, 60)
                elif count == 2:
                    winsound.Beep(1200, 60)
                elif count == 3:
                    winsound.Beep(1600, 60)
                elif count >= 4:
                    winsound.Beep(2000, 45)
                    time.sleep(0.01)
                    winsound.Beep(2000, 45)
            except Exception:
                pass

            # 播报完成后更新状态
            self.last_play_time = time.time()
            self.last_count = count

    def close(self):
        self.running = False


class AimWindow(QMainWindow):
    frame_ready = Signal(np.ndarray, list)

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

        self.frame_ready.connect(self._on_frame_ready)

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
            
            # 🔴 修复启动时序 Bug：直接显式调起底层硬件握手，不经由 _on_mouse_mode_changed 里的 running 检测限制
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
            
            # 🔴 硬件安全防封修改：如果盒子连接失败，此处直接退出启动过程
            if not self.mover._kmbox_net_ready and config.MOUSE_MODE == "kmbox_net":
                self._stop()
                return
            if not self.mover._kmbox_serial_conn and config.MOUSE_MODE == "kmbox_serial":
                self._stop()
                return
                
        except Exception as e:
            self._stop()
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

    def _stop(self):
        self.running = False
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

                # 3. 核心改动：两边各自安好
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
                    self.latest_targets_local = list(targets)

                # 触发极速声呐声音提示 (零阻塞，异步发包)
                self.sound_manager.trigger(len(targets))

                self._det_count += 1
                now = time.time()
                if now - self._det_time >= 1.0:
                    self.detect_fps = int(self._det_count / (now - self._det_time))
                    config.log(f"[Module] Processing FPS: {self.detect_fps}")
                    self._det_count = 0
                    self._det_time = now

                # 5. 触发逻辑：完全基于 320x320 切片相对偏差进行拟人化 PID 自瞄并配合航位推算外推引擎 (EDR)
                if self._is_aim_triggered():
                    self.pid_active = True
                    
                    # 🟢 生理神经反应延迟：如果处于击毙目标或丢失目标的反应认知期内，则不产生鼠标移动，完美模拟大脑判断时间
                    if now < self.handover_cooldown_until:
                        self.last_target_center = None
                        self.last_target_time = 0.0
                        self.target_vel_x = 0.0
                        self.target_vel_y = 0.0
                        self.is_new_lock_session = True
                        # 冷却期间，如果开启预览，依然保持预览的持续同步推送
                        if config.SHOW_PREVIEW:
                            self.frame_ready.emit(crop.copy(), list(targets))
                        continue

                    target_to_track = None
                    is_extrapolated = False

                    # 🟢 EDR 航位推算第一阶段：寻找原锁定目标的匹配，或尝试进入外推阶段
                    if self.locked_target_center is not None and now - self.locked_target_time < 0.5:
                        # 寻找原锁定点 45 像素邻域内的真实检出目标
                        min_match_dist = float('inf')
                        best_match = None
                        for t in targets:
                            tx, ty = t["center"]
                            lx, ly = self.locked_target_center
                            dist = math.sqrt((tx - lx)**2 + (ty - ly)**2)
                            if dist < 45.0:  # 45像素匹配门限
                                if dist < min_match_dist:
                                    min_match_dist = dist
                                    best_match = t
                        
                        if best_match is not None:
                            target_to_track = best_match
                            # 更新锁定目标的状态与尺寸
                            self.locked_target_center = target_to_track["center"]
                            self.locked_target_time = now
                            x1, y1, x2, y2 = target_to_track["bbox"]
                            self.locked_target_size = (x2 - x1, y2 - y1)
                        else:
                            # 🟢 EDR 外插预测逻辑：真实 YOLO 未检出，核算目标丢失时长
                            time_since_last_seen = now - self.locked_target_time
                            if time_since_last_seen < 0.120:  # 允许最多外插 120ms 丢帧（约 2-3 帧推理）
                                # 根据上一次的滤波速度推算新坐标
                                time_delta = now - self.locked_target_time
                                pred_dx = self.target_vel_x * time_delta
                                pred_dy = self.target_vel_y * time_delta
                                
                                ecx = self.locked_target_center[0] + pred_dx
                                ecy = self.locked_target_center[1] + pred_dy
                                
                                # 安全剪切
                                ecx = max(10, min(self.detector.detect_size - 10, ecx))
                                ecy = max(10, min(self.detector.detect_size - 10, ecy))
                                
                                t_w, t_h = getattr(self, "locked_target_size", (60, 60))
                                extrapolated_center = (int(ecx), int(ecy))
                                
                                # 动态构建虚拟预测目标
                                target_to_track = {
                                    "center": extrapolated_center,
                                    "head": extrapolated_center,
                                    "neck": (extrapolated_center[0], int(extrapolated_center[1] + t_h * 0.20)),
                                    "chest": (extrapolated_center[0], int(extrapolated_center[1] + t_h * 0.95)),
                                    "bbox": (int(ecx - t_w/2), int(ecy - t_h/2), int(ecx + t_w/2), int(ecy + t_h/2)),
                                    "confidence": 0.80,
                                    "class_id": 0,
                                    "is_extrapolated": True
                                }
                                is_extrapolated = True
                                
                                # 更新锁定中心缓存以维持后续的外插惯性，但锁定时间保持不动（代表最后一次真检出时间）
                                self.locked_target_center = extrapolated_center
                                # 追加到 targets 以便 draw_results 绘制 "predicting..." 虚框
                                targets.append(target_to_track)
                            else:
                                # 丢失超时：判定为目标死亡或完全拉失，开始注入 110ms~190ms 人类视觉盲区延迟，消灭 0ms 反人类动作
                                self.handover_cooldown_until = now + random.uniform(0.110, 0.190)
                                self.locked_target_center = None
                                self.is_new_lock_session = True

                    # 🟢 EDR 航位推算第二阶段：若当前无追踪目标，或已判定丢失，则寻找画面中离准心最近的新目标
                    if target_to_track is None and targets:
                        min_center_dist = float('inf')
                        best_t = targets[0]
                        cx = self.detector.detect_size // 2
                        cy = self.detector.detect_size // 2
                        
                        for t in targets:
                            # 忽略其他可能已经外插的数据
                            if t.get("is_extrapolated"):
                                continue
                            tx, ty = t["center"]
                            dist = math.sqrt((tx - cx)**2 + (ty - cy)**2)
                            if dist < min_center_dist:
                                min_center_dist = dist
                                best_t = t
                        
                        # 确保不是个空的目标
                        if best_t is not None:
                            target_to_track = best_t
                            self.locked_target_center = target_to_track["center"]
                            self.locked_target_time = now
                            x1, y1, x2, y2 = target_to_track["bbox"]
                            self.locked_target_size = (x2 - x1, y2 - y1)
                            
                            # 速度滤波重置
                            self.last_target_center = None
                            self.last_target_time = 0.0
                            self.target_vel_x = 0.0
                            self.target_vel_y = 0.0
                            self.is_new_lock_session = True

                    # 🟢 EDR 航位推算第三阶段：计算速度与物理控制发包
                    if target_to_track is not None:
                        # 只有在非外推（真检出）状态下，才累加和计算瞬时移动速度，用于自适应 EMA 速度滤波器
                        if not is_extrapolated:
                            if self.last_target_center is not None and self.last_target_time > 0.0:
                                last_cx, last_cy = self.last_target_center
                                current_cx, current_cy = target_to_track["center"]
                                time_delta = now - self.last_target_time
                                
                                if 0.001 < time_delta < 0.2:
                                    inst_vx = (current_cx - last_cx) / time_delta
                                    inst_vy = (current_cy - last_cy) / time_delta
                                    
                                    self.target_vel_x = 0.25 * inst_vx + 0.75 * self.target_vel_x
                                    self.target_vel_y = 0.25 * inst_vy + 0.75 * self.target_vel_y
                            
                            self.last_target_center = target_to_track["center"]
                            self.last_target_time = now

                        # 🟢 计算生理抖动微漂移 (一阶自回归，标准差 0.25 像素)
                        self.drift_x += -0.08 * self.drift_x + 0.25 * random.gauss(0, 1)
                        self.drift_y += -0.08 * self.drift_y + 0.25 * random.gauss(0, 1)

                        # 🟢 生成本轮锁敌的高斯定点偏置
                        x1, y1, x2, y2 = target_to_track["bbox"]
                        t_w = max(1, x2 - x1)
                        t_h = max(1, y2 - y1)
                        if self.is_new_lock_session:
                            self.dispersal_x = random.normalvariate(0.0, t_w * 0.035)
                            self.dispersal_y = random.normalvariate(0.0, t_h * 0.035)
                            self.is_new_lock_session = False
                        
                        # 物理运动预测（只有在真检出时计算，外插时因直接使用推算点，故预测量为 0）
                        pred_dx = 0.0
                        pred_dy = 0.0
                        if not is_extrapolated:
                            compensation_time = 0.015  # 截屏延迟 + 推理延迟约 15 毫秒
                            pred_dx = self.target_vel_x * compensation_time
                            pred_dy = self.target_vel_y * compensation_time

                        aim_part = getattr(config, "AIM_PART", "head")
                        aim_pt = target_to_track.get(aim_part, target_to_track["head"])
                        aim_x = aim_pt[0] + pred_dx + self.dispersal_x + self.drift_x
                        aim_y = aim_pt[1] + pred_dy + self.dispersal_y + self.drift_y

                        center_x = self.detector.detect_size // 2
                        center_y = self.detector.detect_size // 2

                        raw_dx = aim_x - center_x
                        raw_dy = aim_y - center_y

                        distance = math.sqrt(raw_dx**2 + raw_dy**2)

                        # 物理精细死区判定
                        if distance <= 1.2:
                            self.mover.pid_x.reset()
                            self.mover.pid_y.reset()
                        else:
                            # 终极防抖与高刷同步发包
                            if now - last_move_time > random.uniform(0.010, 0.015):
                                sigmoid_factor = 0.55 + 0.45 * (distance**2) / (distance**2 + 144.0)
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
                    self.is_new_lock_session = True
                    if self.pid_active:
                        self.mover.pid_x.reset()
                        self.mover.pid_y.reset()
                        self.pid_active = False

                # 无论是否触发自瞄，只要开启预览，均向主线程发送最新的检测切片进行 100% 同步渲染
                if config.SHOW_PREVIEW:
                    self.frame_ready.emit(crop.copy(), list(targets))

            except Exception as e:
                QTimer.singleShot(0, lambda: self.log(f"运行错误: {e}"))

            time.sleep(0.001)

    def _is_aim_triggered(self):
        # 🟢 终极隐蔽防封 + 智能插入状态诊断系统 (闭环自愈灾备降级)
        # 如果检测到用户在电脑上按下了按键，但硬件盒子没监听到，说明设备被插错了插槽！
        # 此时我们会自动安全降级至系统 API 监听，防止自瞄完全瘫痪，并提供高亮警告提示。
        if config.MOUSE_MODE == "kmbox_net" and self.mover._kmbox_net_ready:
            try:
                import kmNet
                key = config.AIM_TRIGGER_KEY
                
                if key == "right_mouse":
                    hw_pressed = bool(kmNet.isdown(2))
                    sys_pressed = False
                    if win32api is not None and win32con is not None:
                        sys_pressed = bool(win32api.GetAsyncKeyState(win32con.VK_RBUTTON) & 0x8000)
                    
                    if sys_pressed and not hw_pressed:
                        # 🔴 硬件安全防封 Fail-Stop 终极保护：发现错插，绝不降级，直接熔断关停！
                        self._stop()
                        config.log("🚨 [CRITICAL ERROR] 检测到鼠标错插在【电脑主机】上！为了保障防封安全性，自瞄已安全拉闸停机！")
                        # 弹出 UI 提示框，并在子线程中以安全方式警告用户
                        from PySide6.QtWidgets import QMessageBox
                        import threading
                        def show_box():
                            msg = QMessageBox(self)
                            msg.setIcon(QMessageBox.Critical)
                            msg.setWindowTitle("硬件连接错误 (安全断电保护)")
                            msg.setText("🚨 终极安全断电保护触发！\n\n检测到您的右键按键信号发自【电脑主机】，而非物理盒子接口！这说明鼠标被错插到了主机上。\n\n为了您的账号安全，系统已强制断电（Fail-Stop）关停自瞄！请立即将键盘/鼠标插回【KMBox 硬件盒子】，然后再重新启动自瞄。")
                            msg.exec()
                        threading.Thread(target=show_box, daemon=True).start()
                        return False
                    return hw_pressed
                    
                elif key == "xbutton":
                    hw_pressed = bool(kmNet.isdown(4) or kmNet.isdown(5))
                    sys_pressed = False
                    if win32api is not None:
                        sys_pressed = bool(win32api.GetAsyncKeyState(0x05) & 0x8000)
                    
                    if sys_pressed and not hw_pressed:
                        self._stop()
                        config.log("🚨 [CRITICAL ERROR] 检测到鼠标错插在【电脑主机】上！自瞄已安全拉闸停机！")
                        from PySide6.QtWidgets import QMessageBox
                        import threading
                        def show_box():
                            msg = QMessageBox(self)
                            msg.setIcon(QMessageBox.Critical)
                            msg.setWindowTitle("硬件连接错误 (安全断电保护)")
                            msg.setText("🚨 终极安全断电保护触发！\n\n检测到侧键按键信号发自【电脑主机】，说明鼠标被错插到了主机上。\n\n为了账号安全，自瞄已强制拉闸！请立即将鼠标插回【KMBox 硬件盒子】。")
                            msg.exec()
                        threading.Thread(target=show_box, daemon=True).start()
                        return False
                    return hw_pressed
                    
                elif key == "ctrl":
                    hw_pressed = bool(kmNet.isdown_keyboard(224))
                    sys_pressed = False
                    if win32api is not None and win32con is not None:
                        sys_pressed = bool(win32api.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000)
                    
                    if sys_pressed and not hw_pressed:
                        self._stop()
                        config.log("🚨 [CRITICAL ERROR] 检测到键盘错插在【电脑主机】上！自瞄已安全拉闸停机！")
                        from PySide6.QtWidgets import QMessageBox
                        import threading
                        def show_box():
                            msg = QMessageBox(self)
                            msg.setIcon(QMessageBox.Critical)
                            msg.setWindowTitle("硬件连接错误 (安全断电保护)")
                            msg.setText("🚨 终极安全断电保护触发！\n\n检测到键盘 Ctrl 信号发自【电脑主机】，说明键盘被错插到了主机上。\n\n为了账号安全，自瞄已强制拉闸！请立即将键盘插回【KMBox 硬件盒子】。")
                            msg.exec()
                        threading.Thread(target=show_box, daemon=True).start()
                        return False
                    return hw_pressed
                    
                elif key == "shift":
                    hw_pressed = bool(kmNet.isdown_keyboard(225))
                    sys_pressed = False
                    if win32api is not None and win32con is not None:
                        sys_pressed = bool(win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000)
                    
                    if sys_pressed and not hw_pressed:
                        self._stop()
                        config.log("🚨 [CRITICAL ERROR] 检测到键盘错插在【电脑主机】上！自瞄已安全拉闸停机！")
                        from PySide6.QtWidgets import QMessageBox
                        import threading
                        def show_box():
                            msg = QMessageBox(self)
                            msg.setIcon(QMessageBox.Critical)
                            msg.setWindowTitle("硬件连接错误 (安全断电保护)")
                            msg.setText("🚨 终极安全断电保护触发！\n\n检测到键盘 Shift 信号发自【电脑主机】，说明键盘被错插到了主机上。\n\n为了账号安全，自瞄已强制拉闸！请立即将键盘插回【KMBox 硬件盒子】。")
                            msg.exec()
                        threading.Thread(target=show_box, daemon=True).start()
                        return False
                    return hw_pressed
                    
                elif key == "alt":
                    hw_pressed = bool(kmNet.isdown_keyboard(226))
                    sys_pressed = False
                    if win32api is not None and win32con is not None:
                        sys_pressed = bool(win32api.GetAsyncKeyState(win32con.VK_MENU) & 0x8000)
                    
                    if sys_pressed and not hw_pressed:
                        self._stop()
                        config.log("🚨 [CRITICAL ERROR] 检测到键盘错插在【电脑主机】上！自瞄已安全拉闸停机！")
                        from PySide6.QtWidgets import QMessageBox
                        import threading
                        def show_box():
                            msg = QMessageBox(self)
                            msg.setIcon(QMessageBox.Critical)
                            msg.setWindowTitle("硬件连接错误 (安全断电保护)")
                            msg.setText("🚨 终极安全断电保护触发！\n\n检测到键盘 Alt 信号发自【电脑主机】，说明键盘被错插到了主机上。\n\n为了账号安全，自瞄已强制拉闸！请立即将键盘插回【KMBox 硬件盒子】。")
                            msg.exec()
                        threading.Thread(target=show_box, daemon=True).start()
                        return False
                    return hw_pressed
            except Exception:
                pass

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

    def _on_frame_ready(self, frame, targets):
        if not self.running or not config.SHOW_PREVIEW:
            return

        with self.lock:
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
        
        # 🟢 【性能优化】：改用 FastTransformation (最快邻近插值) 缩放，彻底杜绝 SmoothTransformation 的 CPU 阻塞与高延迟，彻底释放 Python GIL 锁
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
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
            # 🔴 硬件安全防封修改：连接失败时坚决不强制降级回 mouse (win32) 模式！
            # 保持所选的硬件模式，但自动切断并停止 Aimbot 线程运行，等待人工排查
            self._stop()
            config.log(f"[ERROR] KMBox 连接失败: {e}")
            QMessageBox.critical(
                self, 
                "硬件连接失败 (安全保护中)", 
                f"KMBox 硬件连接失败，自瞄已安全终止运行！\n\n"
                f"错误详情: {e}\n\n"
                f"💡 安全提示：为了防止被反作弊检测，程序坚决未降级到软件模拟（Win32）模式。请检查盒子网线连接、网络 IP 配置或串口，排查正确后重新开启。"
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
        config.SOUND_ALERT = self.chk_sound.isChecked()
        config.save_config()
        QMessageBox.information(self, "保存成功", "配置已保存到 config.json")
    def closeEvent(self, event):
        self._stop()
        if hasattr(self, "sound_manager"):
            self.sound_manager.close()
        event.accept()
