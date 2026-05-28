import os
# 🟢 延迟加载 CUDA 驱动核心，极大幅度缩减系统虚拟内存与物理内存占用 footprint
os.environ["CUDA_MODULE_LOADING"] = "LAZY"

import torch  # 🟢 强行直接写在最顶层，不给任何条件判断拦截它的机会！
import cv2
import numpy as np
import config


class Detector:

    def __init__(self, model_path=None):
        self.model_path = model_path or config.MODEL_PATH
        self.model = None
        self.model_type = None
        self.confidence = config.CONFIDENCE_THRESHOLD
        self.target_classes = config.TARGET_CLASSES
        self.detect_size = 320
        
        # 🟢 【核心优化】：将 PyTorch 的 CUDA 显存强行截断在 15% 的硬限制下，既保留高帧率所需缓存，又彻底消除 2G+ 大显存占用的异常指纹
        try:
            if torch.cuda.is_available():
                torch.cuda.set_per_process_memory_fraction(0.15, 0)
                torch.backends.cudnn.benchmark = False
                torch.backends.cudnn.deterministic = True
        except Exception:
            pass

        self.device = self._detect_device()

    @staticmethod
    def _detect_device():
        # 🟢 确保这里没有用一个空的 except 默默把 torch 的错误吃掉
        try:
            if torch.cuda.is_available():
                return 0
        except Exception as e:
            config.log(f"[Device Error] {e}")
        return "cpu"

    def load(self):
        # 先尝试 ultralytics 新版加载（v8/v11）
        try:
            from ultralytics import YOLO

            self.model = YOLO(self.model_path)
            self.model_type = "v8"
            config.log(f"[Module] Telemetry engine initialized successfully ({self.device})")
            return
        except Exception as e:
            # 🟢 别用 pass 默默吃掉，把真正的报错打印出来，如果是缺 onnx 库一眼就能看到！
            config.log(f"[Module] Telemetry engine initialization bypassed: {e}")

        # 再尝试 torch.hub 加载老版 YOLOv5
        try:
            # 🟢 额外防御逻辑：如果是 .onnx 文件，老版 v5 压根不支持，直接抛出别硬撑
            if str(self.model_path).endswith(".onnx") and self.model is None:
                raise RuntimeError(
                    "检测到 ONNX 模型，但 ultralytics 引擎由于上述报错未能成功启动。"
                )

            self.model = torch.hub.load(
                "ultralytics/yolov5",
                "custom",
                path=self.model_path,
                force_reload=False,
            )
            self.model.conf = self.confidence
            self.model_type = "v5"
            config.log(f"[Module] Legacy telemetry engine initialized successfully ({self.device})")
            return
        except Exception as e:
            raise RuntimeError(f"模型加载失败，v8 和 v5 均不支持: {e}")

    def detect(self, frame):
        if self.model is None:
            return []

        # 🟢 核心优化：直接把原图喂给模型，scale 设为 1.0。
        # 让 YOLO 内部去走 GPU 矩阵缩放，速度比 cv2.resize 快 5 倍！
        if self.model_type == "v8":
            return self._detect_v8(frame, 1.0)
        else:
            scale = self.detect_size / max(frame.shape[:2])
            small = cv2.resize(
                frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale))
            )
            return self._detect_v5(small, scale)

    def _detect_v8(self, small, scale):
        results = self.model(
            small,
            conf=self.confidence,
            verbose=False,
            imgsz=self.detect_size,
            device=self.device,
            half=True,  # 🟢 强行开启半精度推理，RTX显卡速度再翻倍！
        )
        return self._parse_results_v8(results, scale)

    def _detect_v5(self, small, scale):
        results = self.model(small)
        return self._parse_results_v5(results, scale)

    def _parse_results_v8(self, results, scale):
        targets = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                if self.target_classes and cls_id not in self.target_classes:
                    continue
                xyxy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = xyxy / scale
                targets.append(
                    self._make_target(x1, y1, x2, y2, float(box.conf[0]), cls_id)
                )
        targets.sort(key=lambda t: t["area"], reverse=True)
        return targets

    def _parse_results_v5(self, results, scale):
        targets = []
        preds = results.pandas().xyxy[0]
        for _, row in preds.iterrows():
            cls_id = int(row["class"])
            if self.target_classes and cls_id not in self.target_classes:
                continue
            x1, y1, x2, y2 = row[["xmin", "ymin", "xmax", "ymax"]].values / scale
            targets.append(
                self._make_target(x1, y1, x2, y2, float(row["confidence"]), cls_id)
            )
        targets.sort(key=lambda t: t["area"], reverse=True)
        return targets

    @staticmethod
    def _make_target(x1, y1, x2, y2, conf, cls_id):
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        head_y = y1 + (y2 - y1) * 0.12
        neck_y = y1 + (y2 - y1) * 0.20
        chest_y = y1 + (y2 - y1) * 0.35
        return {
            "bbox": (int(x1), int(y1), int(x2), int(y2)),
            "center": (int(center_x), int(center_y)),
            "head": (int(center_x), int(head_y)),
            "neck": (int(center_x), int(neck_y)),
            "chest": (int(center_x), int(chest_y)),
            "confidence": conf,
            "class_id": cls_id,
            "area": int((x2 - x1) * (y2 - y1)),
        }

    def draw_results(self, frame, targets):
        for t in targets:
            x1, y1, x2, y2 = t["bbox"]
            if config.SHOW_BBOX:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                aim_part = getattr(config, "AIM_PART", "head")
                aim_pt = t.get(aim_part, t["head"])
                cv2.circle(frame, aim_pt, 3, (0, 0, 255), -1)
                label = f"person {t['confidence']:.2f}"
                cv2.putText(
                    frame,
                    label,
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                )

    def draw_hud(self, frame, fps, detect_fps):
        h, w = frame.shape[:2]
        if config.SHOW_CROSSHAIR:
            cx, cy = w // 2, h // 2
            cv2.line(frame, (cx - 10, cy), (cx + 10, cy), (0, 255, 255), 1)
            cv2.line(frame, (cx, cy - 10), (cx, cy + 10), (0, 255, 255), 1)
        cv2.putText(
            frame,
            f"FPS: {fps}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            frame,
            f"Det: {detect_fps}",
            (10, 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 200, 200),
            1,
        )
