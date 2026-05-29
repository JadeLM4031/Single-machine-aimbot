"""鼠标控制模块 - 融合最强自适应 PID 状态机版本"""

import config
import time
import random
import math
import ctypes

try:
    import win32api
    import win32con
except ImportError:
    win32api = None
    win32con = None

try:
    import serial
except ImportError:
    serial = None


class PythonAdaptivePID:
    def __init__(self, kp, ki, kd):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.last_error = None
        self.stable_count = 0
        self.is_reached = False

        # 完美照抄 C++ 固件底层的状态机参数
        self.reach_thresh = 5.0  # 达标误差阈值 (像素)
        self.min_coef = 1.0  # 最小系数
        self.max_coef = 3.0  # 最大系数
        self.sharpness = 5.0  # 过渡锐度
        self.midpoint = 0.1  # 动态过渡中点
        self.min_data = 2  # 最小数据量
        self.error_tol = 3  # 误差变化容限
        self.smooth_factor = 0.6  # 低通滤波平滑因子

    def update(self, error, dt, target_w=80, img_size=2560.0):
        if dt <= 0:
            dt = 0.001

        if self.last_error is None:
            self.last_error = error

        # 1. 动态阈值计算 (Sigmoid)
        w_ratio = target_w / img_size
        dynamic_coef = self.min_coef + (self.max_coef - self.min_coef) / (
            1.0 + math.exp(-self.sharpness * (w_ratio - self.midpoint))
        )
        dynamic_thresh = dynamic_coef * target_w

        # 2. 状态机判定
        if not self.is_reached and abs(error) < self.reach_thresh:
            self.is_reached = True
        elif abs(error) >= dynamic_thresh:
            self.is_reached = False
            self.integral = 0
            self.stable_count = 0
        elif not self.is_reached and self.reach_thresh <= abs(error) <= dynamic_thresh:
            diff = abs(error - self.last_error)
            if diff < self.error_tol:
                self.stable_count += 1
            else:
                self.stable_count = 0

            if self.stable_count >= self.min_data:
                self.is_reached = True
                self.stable_count = 0
                self.integral = 0

        # 3. PID 核心计算
        err_rate = (error - self.last_error) / dt

        if self.is_reached:
            self.integral += error * dt
            self.integral = max(-100.0, min(100.0, self.integral))  # Anti-windup 限幅
            i_out = self.ki * self.integral
            p_out = self.kp * error
            d_out = self.kd * err_rate
        else:
            self.integral += (error * 0.5) * dt
            self.integral = max(-100.0, min(100.0, self.integral))
            i_out = self.ki * self.integral
            p_out = (self.kp * 0.5) * error
            d_out = self.kd * err_rate

        raw_out = p_out + i_out + d_out
        total_out = self.smooth_factor * raw_out

        self.last_error = error
        return total_out

    def reset(self):
        self.integral = 0.0
        self.last_error = None
        self.stable_count = 0
        self.is_reached = False


class OUNoise:
    """Ornstein-Uhlenbeck 随机过程发生器
    用于完美模拟人类生理性肌肉微颤抖动 (具有均值回归特性，物理防封)
    """

    def __init__(self, theta=0.25, mu=0.0, sigma=0.35):
        self.theta = theta
        self.mu = mu
        self.sigma = sigma
        self.state = 0.0

    def update(self):
        dx = -self.theta * (self.state - self.mu) + self.sigma * random.gauss(0, 1)
        self.state += dx
        return self.state

    def reset(self):
        self.state = 0.0


class MouseController:
    def __init__(self):
        self.mode = config.MOUSE_MODE
        self.smooth = config.SMOOTH_FACTOR
        self._kmbox_serial_conn = None
        self._kmbox_net_ready = False

        # 🟢 犀利修复：Kp(比例增益)调升至 0.28 磁性变强；Kd(微分刹车)调高到 0.0045，利用阻尼消除高频拉枪过头的剧烈抖动
        self.pid_x = PythonAdaptivePID(0.28, 0.0, 0.0045)
        self.pid_y = PythonAdaptivePID(0.28, 0.0, 0.0045)
        self.last_pid_time = time.time()

        self.ou_x = OUNoise(theta=0.25, mu=0.0, sigma=0.35)
        self.ou_y = OUNoise(theta=0.25, mu=0.0, sigma=0.35)

    def connect(self):
        self.close()
        self.mode = config.MOUSE_MODE
        self.smooth = config.SMOOTH_FACTOR
        self.pid_x.reset()
        self.pid_y.reset()
        self.ou_x.reset()
        self.ou_y.reset()
        self.last_pid_time = time.time()
        if self.mode == "mouse":
            config.log("[Output] Channel configuration completed (default)")
        elif self.mode == "kmbox_net":
            self._connect_kmbox_net()
        elif self.mode == "kmbox_serial":
            self._connect_kmbox_serial()

    def switch_mode(self, mode, **kwargs):
        config.MOUSE_MODE = mode
        if "ip" in kwargs:
            config.KMBOX_IP = kwargs["ip"]
        if "port" in kwargs:
            config.KMBOX_PORT = kwargs["port"]
        if "mac" in kwargs:
            config.KMBOX_MAC = kwargs["mac"]
        if "serial_port" in kwargs:
            config.KMBOX_SERIAL_PORT = kwargs["serial_port"]
        self.connect()

    def move(self, dx, dy, target_w=80):
        now = time.time()
        dt = now - self.last_pid_time
        self.last_pid_time = now

        step_x = self.pid_x.update(dx, dt, target_w=target_w)
        step_y = self.pid_y.update(dy, dt, target_w=target_w)

        # 🟢 犀利修复：杠杆乘数从激进的 4.5 倍理智回调至 2.8 倍，配合已经开大的 Kp，既有强吸附又彻底杜绝了网卡超时假死
        move_x = step_x * self.smooth * 2.8
        move_y = step_y * self.smooth * 2.8

        dist = math.sqrt(dx**2 + dy**2)

        jitter_scale = 0.15 if dist < 6.0 else 1.0
        jitter_x = self.ou_x.update() * jitter_scale
        jitter_y = self.ou_y.update() * jitter_scale
        move_x += jitter_x
        move_y += jitter_y

        if dist >= 6.0:
            if abs(step_x) > 0.05:
                if move_x > 0 and move_x < 1.0:
                    move_x = 1.0
                elif move_x < 0 and move_x > -1.0:
                    move_x = -1.0
            if abs(step_y) > 0.05:
                if move_y > 0 and move_y < 1.0:
                    move_y = 1.0
                elif move_y < 0 and move_y > -1.0:
                    move_y = -1.0

        final_move_x = max(-100, min(100, int(move_x)))
        final_move_y = max(-100, min(100, int(move_y)))

        if final_move_x == 0 and final_move_y == 0:
            return

        if self.mode == "mouse":
            self._move_mouse(final_move_x, final_move_y)
        elif self.mode == "kmbox_net":
            self._move_kmbox_net(final_move_x, final_move_y)
        elif self.mode == "kmbox_serial":
            self._move_kmbox_serial(final_move_x, final_move_y)

    def click(self, button="left"):
        if self.mode == "mouse":
            self._click_mouse(button)
        elif self.mode == "kmbox_net":
            self._click_kmbox_net(button)
        elif self.mode == "kmbox_serial":
            self._click_kmbox_serial(button)

    def _move_mouse(self, dx, dy):
        if ctypes.windll.user32.mouse_event:
            ctypes.windll.user32.mouse_event(0x0001, dx, dy, 0, 0)

    def _click_mouse(self, button="left"):
        if win32api is None or win32con is None:
            return
        x, y = win32api.GetCursorPos()
        delay = max(0.045, min(0.110, random.normalvariate(0.070, 0.012)))
        if button == "left":
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
            time.sleep(delay)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)

    def _connect_kmbox_net(self):
        try:
            import kmNet
        except ImportError:
            raise RuntimeError(
                "找不到 kmNet 驱动文件。请确保 'kmNet.cp310-win_amd64.pyd' 已经放置在项目根目录下！"
            )

        ip = config.KMBOX_IP
        port = str(config.KMBOX_PORT)
        mac = config.KMBOX_MAC

        config.log(
            f"[Output] 正在尝试连接 KMBox 网络版 (IP: {ip}, 端口: {port}, MAC/UUID: {mac})..."
        )

        try:
            result = kmNet.init(ip, port, mac)
        except Exception as e:
            raise RuntimeError(f"KMBox 硬件通讯发生严重异常: {e}")

        if result != 0:
            raise RuntimeError(
                f"KMBox 网络初始化失败 (错误码: {result})。请检查硬件连接与参数配置。"
            )

        self._kmbox_net_ready = True
        config.log(
            "[Output] KMBox 硬件网络连接成功！已开启高隐蔽硬件级加密通讯通道 (enc_move)"
        )

    def _move_kmbox_net(self, dx, dy):
        if not self._kmbox_net_ready:
            return
        import kmNet

        try:
            kmNet.enc_move(dx, dy)
        except Exception as e:
            config.log(f"[Warning] KMBox 发送移动指令失败: {e}")

    def _click_kmbox_net(self, button="left"):
        if not self._kmbox_net_ready:
            return
        import kmNet

        try:
            delay = max(0.045, min(0.110, random.normalvariate(0.070, 0.012)))
            if button == "left":
                kmNet.enc_left(1)
                time.sleep(delay)
                kmNet.enc_left(0)
            elif button == "right":
                kmNet.enc_right(1)
                time.sleep(delay)
                kmNet.enc_right(0)
        except Exception as e:
            config.log(f"[Warning] KMBox 发送点击指令失败: {e}")

    def _connect_kmbox_serial(self):
        if serial is None:
            raise RuntimeError(
                "找不到 pyserial 依赖库，请通过 pip install pyserial 安装"
            )
        self._kmbox_serial_conn = serial.Serial(
            config.KMBOX_SERIAL_PORT, 115200, timeout=1
        )
        config.log("[Output] Channel configuration completed (serial)")

    def _move_kmbox_serial(self, dx, dy):
        if self._kmbox_serial_conn:
            self._kmbox_serial_conn.write(f"km.move({dx},{dy})\r\n".encode())

    def _click_kmbox_serial(self, button="left"):
        if not self._kmbox_serial_conn:
            return
        delay = max(0.045, min(0.110, random.normalvariate(0.070, 0.012)))
        if button == "left":
            self._kmbox_serial_conn.write(b"km.left_down()\r\n")
            time.sleep(delay)
            self._kmbox_serial_conn.write(b"km.left_up()\r\n")

    def close(self):
        self._kmbox_net_ready = False
        if self._kmbox_serial_conn:
            try:
                self._kmbox_serial_conn.close()
            except Exception:
                pass
            self._kmbox_serial_conn = None
