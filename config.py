"""全局配置"""

import json
import os
import datetime

# 配置文件路径
CONFIG_FILE = "config.json"

# UI 日志回调（由 ui.py 设置）
_log_callback = None


def log(msg):
    """全局日志函数，同时输出到控制台和 UI"""
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    if _log_callback is not None:
        _log_callback(line)

# 屏幕捕获（dxcam DXGI）
OBS_CAMERA_INDEX = 0  # 屏幕序号，0=主屏，1=副屏
CAPTURE_SIZE = 320  # 中心捕获区域边长（像素），可选 320 或 640

# 检测区域（相对于捕获画面的比例）
DETECT_REGION = (0.2, 0.1, 0.8, 0.9)

# YOLO 模型
MODEL_PATH = "models/yolov8n.pt"
CONFIDENCE_THRESHOLD = 0.5
TARGET_CLASSES = [0, 1]  # 0: head, 1: body

# 鼠标控制模式: "mouse" / "kmbox_net" / "kmbox_serial"
MOUSE_MODE = "kmbox_net"

# KMBox 配置
KMBOX_IP = "192.168.2.168"
KMBOX_PORT = "64532"
KMBOX_MAC = "B7510C3D"  # KMBox 的 UUID/MAC，设备底部标签上可以找到
KMBOX_SERIAL_PORT = "COM3"

# 移动平滑度（0.1~1.0）
SMOOTH_FACTOR = 0.3

# 瞄准触发键: "right_mouse" / "ctrl" / "shift" / "alt" / "xbutton1" / "xbutton2"
AIM_TRIGGER_KEY = "right_mouse"

# 瞄准部位: "head" / "neck" / "chest"
AIM_PART = "head"

# 目标配置
MODEL_VERSION = "auto"  # "auto" (自动识别) / "new" (新多分类) / "old" (旧双分类)
TARGET_MODE = "enemy"   # "enemy" / "practice" / "xiaobing" / "daodi" / "duiyou"

# 显示控制
SHOW_PREVIEW = True
SHOW_BBOX = True
SHOW_CROSSHAIR = True
SHOW_DETECT_REGION = True
SHOW_PERF = False
SOUND_ALERT = False
SOUND_FILE = "tool/tip.wav"

# 窗口标题
WINDOW_TITLE = "System Monitor"


def load_config():
    """从 config.json 加载用户配置"""
    if not os.path.exists(CONFIG_FILE):
        return
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key, value in data.items():
        if key.isupper():
            globals()[key] = value


def save_config():
    """保存当前配置到 config.json"""
    keys = [
        "OBS_CAMERA_INDEX", "DETECT_REGION", "MODEL_PATH",
        "CONFIDENCE_THRESHOLD", "TARGET_CLASSES", "MOUSE_MODE",
        "KMBOX_IP", "KMBOX_PORT", "KMBOX_MAC", "KMBOX_SERIAL_PORT",
        "SMOOTH_FACTOR", "AIM_TRIGGER_KEY", "AIM_PART",
        "SHOW_PREVIEW", "SHOW_BBOX", "SHOW_CROSSHAIR",
        "SHOW_DETECT_REGION", "SHOW_PERF", "SOUND_ALERT",
        "SOUND_FILE", "MODEL_VERSION", "TARGET_MODE",
    ]
    data = {k: globals()[k] for k in keys}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# 启动时自动加载
load_config()
