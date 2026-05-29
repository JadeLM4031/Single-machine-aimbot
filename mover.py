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


def precise_sleep(seconds):
    """微秒级高精度混合休眠，完美消除 Windows 线程调度误差，让微步滑行平滑匀称"""
    start = time.perf_counter()
    if seconds > 0.002:
        time.sleep(seconds - 0.0015)
    while time.perf_counter() - start < seconds:
        pass


class PythonAdaptivePID:
    def __init__(self, kp, ki, kd):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.last_error = None
        self.stable_count = 0
        self.is_reached = False

        # 完美兼容已有的状态机参数
        self.reach_thresh = 5.0  # 达标误差阈值 (像素)
        self.min_coef = 1.0
        self.max_coef = 3.0
        self.sharpness = 5.0
        self.midpoint = 0.1
        self.min_data = 2
        self.error_tol = 3
        self.smooth_factor = 0.6  # 全局平滑因子

    def update(self, error, dt, target_w=80, img_size=2560.0):
        # 1. 采用一阶低通滤波平滑 dt 变化，彻底消除多线程线程调度抖动引起的 D 项（微分）震颤
        if not hasattr(self, "_smoothed_dt"):
            self._smoothed_dt = 0.008
        self._smoothed_dt = 0.95 * self._smoothed_dt + 0.05 * dt
        dt_calc = max(0.004, min(0.020, self._smoothed_dt))

        if self.last_error is None:
            self.last_error = error

        # 2. 彻底移除突然减半/翻倍的阶跃状态切换，改为完全连续平滑的 Kp 控制，避免控制系数突变产生瞬间抽搐与抖动
        p_out = self.kp * error

        # 3. 积分项累计与抗饱和截断限制 (Anti-windup)
        self.integral += error * dt_calc
        self.integral = max(-30.0, min(30.0, self.integral))
        i_out = self.ki * self.integral

        # 4. 对微分项采取极高阻尼（0.96）的一阶数字低通滤波器，从根本上隔离 YOLO 边界框跳变引入的高频数值噪音
        raw_err_rate = (error - self.last_error) / dt_calc
        if not hasattr(self, "_smoothed_err_rate"):
            self._smoothed_err_rate = 0.0
        self._smoothed_err_rate = 0.96 * self._smoothed_err_rate + 0.04 * raw_err_rate
        err_rate = self._smoothed_err_rate
        d_out = self.kd * err_rate

        # 5. 合成输出并应用平滑因子
        raw_out = p_out + i_out + d_out
        total_out = self.smooth_factor * raw_out

        self.last_error = error
        return total_out

    def reset(self):
        self.integral = 0.0
        self.last_error = None
        self.stable_count = 0
        self.is_reached = False
        if hasattr(self, "_smoothed_dt"):
            delattr(self, "_smoothed_dt")
        if hasattr(self, "_smoothed_err_rate"):
            delattr(self, "_smoothed_err_rate")


class OUNoise:
    """Ornstein-Uhlenbeck 随机过程发生器
    用于完美模拟人类生理性肌肉微颤抖动 (具有均值回归特性，物理防封)
    """

    def __init__(self, theta=0.25, mu=0.0, sigma=0.08):
        self.theta = theta
        self.mu = mu
        self.sigma = sigma
        self.state = 0.0
        self.smoothed_state = 0.0
        self.alpha = 0.06  # 🟢 强力低通平滑因子，剔除 330Hz 高频电控刺抖，重塑为柔和的 10Hz 生理震颤

    def update(self):
        dx = -self.theta * (self.state - self.mu) + self.sigma * random.gauss(0, 1)
        self.state += dx
        # 一阶低通滤波
        self.smoothed_state = (1 - self.alpha) * self.smoothed_state + self.alpha * self.state
        return self.smoothed_state

    def reset(self):
        self.state = 0.0
        self.smoothed_state = 0.0


class MouseController:
    def __init__(self):
        self.mode = config.MOUSE_MODE
        self.smooth = config.SMOOTH_FACTOR
        self._kmbox_serial_conn = None
        self._kmbox_net_ready = False

        # 🟢 极速优化：提升 Kp 以获得更强的磁性锁定，调高 Kd 并通过平滑 dt 让刹车更平稳
        self.pid_x = PythonAdaptivePID(0.28, 0.0, 0.005)
        self.pid_y = PythonAdaptivePID(0.28, 0.0, 0.005)
        self.last_pid_time = time.time()

        self.ou_x = OUNoise(theta=0.25, mu=0.0, sigma=0.08)
        self.ou_y = OUNoise(theta=0.25, mu=0.0, sigma=0.08)
        
        # 浮点微位移残差累积器，用来消除极近距离或微小移动下的整型截断死区
        self.residual_x = 0.0
        self.residual_y = 0.0

    def connect(self):
        self.close()
        self.mode = config.MOUSE_MODE
        self.smooth = config.SMOOTH_FACTOR
        self.pid_x.reset()
        self.pid_y.reset()
        self.ou_x.reset()
        self.ou_y.reset()
        self.residual_x = 0.0
        self.residual_y = 0.0
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

    def _execute_move(self, dx, dy):
        if self.mode == "mouse":
            self._move_mouse(dx, dy)
        elif self.mode == "kmbox_net":
            self._move_kmbox_net(dx, dy)
        elif self.mode == "kmbox_serial":
            self._move_kmbox_serial(dx, dy)

    def move(self, dx, dy, target_w=80):
        now = time.time()
        dt = now - self.last_pid_time
        self.last_pid_time = now

        # 1. 使用重构后的一阶低通平滑 PID 更新移动步长
        step_x = self.pid_x.update(dx, dt, target_w=target_w)
        step_y = self.pid_y.update(dy, dt, target_w=target_w)

        # 2. 根据用户设定的平滑系数与自适应远距离精度增强系数（Precision Boost）计算物理位移。
        # 当目标在屏幕上较小或较远（target_w 较小）时，极其微小的像素偏差对目标而言已经是巨大的相对位置漂移。
        # 如果不加补偿，小偏差带来的微小位移（如 0.2 像素）会被整形截断导致鼠标停滞在目标外围死区，产生“稳态误差”（瞄不准）。
        # 引入动态补偿机制：目标越小/越远，成反比平滑提升微移动增益，确保在远距离依然拥有极致细腻、准确锁死准心中心的能力！
        precision_boost = 1.0
        if target_w < 60:
            # 增益平滑过渡：从宽度 60（不增强）到宽度 12（增强 2.2 倍）
            precision_boost = 1.0 + 1.2 * (60 - max(12, target_w)) / 48.0

        move_x = step_x * self.smooth * 2.8 * precision_boost
        move_y = step_y * self.smooth * 2.8 * precision_boost

        dist = math.sqrt(dx**2 + dy**2)

        # 3. 生理性微颤（OU噪声）的幅度在接近目标时进行适当衰减，避免终点产生微小高频抽动
        jitter_scale = 0.06 if dist < 6.0 else 0.35
        jitter_x = self.ou_x.update() * jitter_scale
        jitter_y = self.ou_y.update() * jitter_scale
        move_x += jitter_x
        move_y += jitter_y

        # 🟢 新增【液态速度平滑滤波器 - Liquid Velocity Filter】（跨帧速度 EMA 滤波）
        # 用于彻底烫平由于 YOLO 检测帧率波动、图像微小抖动导致的帧间速度/加速度阶跃突变。
        # 动态自适应平滑因子 v_smooth 会跟随用户设置的 smooth 自动变化。
        # 从而实现“奶油般顺滑 (Buttery Smooth)”的液态拉枪跟枪轨迹，手感完全追平甚至超越顶级自瞄！
        if not hasattr(self, "_last_move_x"):
            self._last_move_x = 0.0
            self._last_move_y = 0.0
        
        # 融合因子：当 smooth 设置越小（要求越平滑），融合旧速度的比例就越高
        v_smooth = 0.45 + 0.35 * self.smooth  # 处于 0.485 到 0.8 之间
        move_x = v_smooth * move_x + (1.0 - v_smooth) * self._last_move_x
        move_y = v_smooth * move_y + (1.0 - v_smooth) * self._last_move_y
        
        self._last_move_x = move_x
        self._last_move_y = move_y

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

        # 4. 浮点精度累积，消灭极近距离截断死区
        total_move_x = move_x + self.residual_x
        total_move_y = move_y + self.residual_y

        final_move_x = int(total_move_x)
        final_move_y = int(total_move_y)

        self.residual_x = total_move_x - final_move_x
        self.residual_y = total_move_y - final_move_y

        if final_move_x == 0 and final_move_y == 0:
            return

        # 5. 🟢 彻底废除占用 CPU 100% 盲等且阻塞 Python GIL 的同步微步 sleep 循环！
        # 代之以跨帧动态限速策略（Speed Capping）：当位移超过阀值时，限制单帧最大输出。
        # 由于检测和控制主循环运行于 ~120Hz 极限帧率，限速会自动将位移平滑摊分到相邻 2-3 帧内完成。
        # 从而以 0ms 零阻塞时间维持纯天然、极致平滑的拉枪滑行，彻底消灭屏幕抖动与卡顿！
        abs_x = abs(final_move_x)
        abs_y = abs(final_move_y)
        max_val = max(abs_x, abs_y)

        # 设定单帧的最大位移阀值，在近距离和远距离时动态分配
        max_limit = 12.0 if dist < 30.0 else 24.0
        if max_val > max_limit:
            scale = max_limit / max_val
            final_move_x = int(final_move_x * scale)
            final_move_y = int(final_move_y * scale)

        # 0 阻塞直接发送物理移动指令，确保后台主线程 120 FPS 满负荷高频刷新
        self._execute_move(final_move_x, final_move_y)

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
        self.residual_x = 0.0
        self.residual_y = 0.0
        if self._kmbox_serial_conn:
            try:
                self._kmbox_serial_conn.close()
            except Exception:
                pass
            self._kmbox_serial_conn = None
