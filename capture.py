"""屏幕捕获模块 - 基于 dxcam (DXGI 硬件级定点区域直传完全体)"""

import time
import dxcam
import numpy as np
import config


class OBSCapture:
    """DXGI 区域直传 - 显卡硬件级指定区域搬运 + 物理真切片输出"""

    def __init__(self, camera_index=None):
        self.camera_index = (
            camera_index if camera_index is not None else config.OBS_CAMERA_INDEX
        )
        self.cap = None
        self._camera = None
        self.custom_offset = (0, 0)

        # 新增两个内部变量，记录我们真正要切出来的物理高宽
        self.target_w = 640
        self.target_h = 640

    def open(self):
        # 1. 极其严格的生命周期防御：彻底停止并销毁旧的高频异步流与句柄
        if hasattr(self, "_camera") and self._camera is not None:
            try:
                self._camera.stop()
                del self._camera
                time.sleep(0.05)
            except Exception:
                pass

        # 2. 用 Win32 API 获取屏幕分辨率，不占用 dxcam 句柄
        try:
            import ctypes

            user32 = ctypes.windll.user32
            if self.camera_index == 0:
                full_w = user32.GetSystemMetrics(0)
                full_h = user32.GetSystemMetrics(1)
            else:
                full_w, full_h = 1920, 1080
        except Exception:
            full_w, full_h = 1920, 1080

        # 3. 以屏幕中心截取固定大小区域
        size = config.CAPTURE_SIZE
        left = (full_w - size) // 2
        top = (full_h - size) // 2
        right = left + size
        bottom = top + size

        self.target_w = size
        self.target_h = size
        self.custom_offset = (left, top)

        # 4. 开启带 region 的硬件高速流（让显卡省下搬运算力）
        self._camera = dxcam.create(
            output_idx=self.camera_index,
            output_color="BGR",
            region=(left, top, right, bottom),
        )
        self.cap = self

        # 5. 🟢 强行恢复 240 帧超高频双缓冲图传流（彻底榨干高刷显示器与显卡性能，解锁极致物理丝滑度！）
        self._camera.start(target_fps=240, video_mode=True)

        config.log(
            f"[Capture] 中心区域截取已启动 - 显示器 {self.camera_index} "
            f"({full_w}x{full_h}) 截取中心 {size}x{size}"
        )

    def _get_real_crop(self, frame):
        if frame is None:
            return None
        h, w = frame.shape[:2]
        # 如果 dxcam 已经返回了 region 大小的帧，直接返回
        if w == self.target_w and h == self.target_h:
            return frame
        # 如果返回的是全屏帧，手动裁剪
        left, top = self.custom_offset
        return frame[top : top + self.target_h, left : left + self.target_w]

    def read(self):
        if self._camera is None:
            return None

        # 🟢 优化点：使用最滚烫的、显卡缓冲区最新的那一帧，不等待，消灭不跟手感
        raw_frame = self._camera.get_latest_frame()
        return self._get_real_crop(raw_frame)

    def grab(self):
        return self._camera is not None

    def retrieve(self):
        if self._camera is None:
            return False, None
        raw_frame = self._camera.get_latest_frame()
        if raw_frame is not None:
            return True, self._get_real_crop(raw_frame)
        return False, None

    def crop_detect_region(self, frame):
        """物理切片已经完成，直接原样返回，性能开销为 0！"""
        return frame, self.custom_offset

    def switch_monitor(self, monitor_idx):
        self.camera_index = monitor_idx
        config.OBS_CAMERA_INDEX = monitor_idx
        self.close()
        time.sleep(0.1)
        self.open()

    def get_monitor_list(self):
        result = []
        for i in range(2):
            try:
                cam = dxcam.create(output_idx=i, output_color="BGR")
                result.append({"idx": i, "width": cam.width, "height": cam.height})
                cam.stop()
                del cam
            except Exception:
                continue
        return result

    def list_cameras(self):
        pass

    def close(self):
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                pass
            self._camera = None
            config.log("[Capture] DXGI 图传已安全关闭")
