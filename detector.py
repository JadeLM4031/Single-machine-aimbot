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
        self.detected_model_ver = "old"  # 新增：记录自动检测出的版本
        
        # 🟢 【核心优化】：将 PyTorch 的 CUDA 显存强行截断在 40% 的硬限制下，并开启 CUDNN benchmark 自动优化最优硬件算法
        try:
            if torch.cuda.is_available():
                torch.cuda.set_per_process_memory_fraction(0.40, 0)
                torch.backends.cudnn.benchmark = True
                torch.backends.cudnn.deterministic = False
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
            self.detect_signature()
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
            self.detect_signature()
            return
        except Exception as e:
            raise RuntimeError(f"模型加载失败，v8 和 v5 均不支持: {e}")

    def detect_signature(self):
        """模型指纹签名自动识别 - 通过类别名称字典判定是新模型还是旧模型"""
        self.detected_model_ver = "old"  # 默认降级为旧模型
        if self.model is None:
            return
            
        try:
            names = getattr(self.model, "names", None)
            if not names:
                # 兼容不同结构的 YOLO 模型（例如 model.model.names）
                model_attr = getattr(self.model, "model", None)
                if model_attr:
                    names = getattr(model_attr, "names", None)
            
            if names:
                config.log(f"[Module] Loaded model classes: {names}")
                # 检查是否存在 "direntoubu" 字符串（无论是字典值还是列表元素）
                has_new_tag = False
                if isinstance(names, dict):
                    has_new_tag = any("direntoubu" in str(v).lower() for v in names.values())
                elif isinstance(names, list):
                    has_new_tag = any("direntoubu" in str(v).lower() for v in names)
                
                if has_new_tag:
                    self.detected_model_ver = "new"
                    config.log("🚨 [Module] 检测到新版多分类模型签名 ('direntoubu')，自动启用新多分类适配逻辑")
                else:
                    self.detected_model_ver = "old"
                    config.log("🟢 [Module] 未检测到新模型签名，自动启用旧版双分类兼容逻辑 (0: head, 1: body)")
            else:
                config.log("[Module] 无法读取模型类别名称字典，默认启用旧版双分类逻辑")
        except Exception as e:
            config.log(f"[Module] 读取模型指纹特征时发生异常 (默认启用旧版兼容): {e}")

    def detect(self, frame):
        self.target_classes = getattr(config, "TARGET_CLASSES", [0, 1])
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
        detections = []
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
                detections.append({
                    "box": (x1, y1, x2, y2),
                    "conf": float(box.conf[0]),
                    "cls_id": cls_id
                })
        return self._process_detections(detections)

    def _parse_results_v5(self, results, scale):
        detections = []
        preds = results.pandas().xyxy[0]
        for _, row in preds.iterrows():
            cls_id = int(row["class"])
            if self.target_classes and cls_id not in self.target_classes:
                continue
            x1, y1, x2, y2 = row[["xmin", "ymin", "xmax", "ymax"]].values / scale
            detections.append({
                "box": (x1, y1, x2, y2),
                "conf": float(row["confidence"]),
                "cls_id": cls_id
            })
        return self._process_detections(detections)

    def _process_detections(self, detections):
        """
        根据当前模型版本 (新/旧) 及目标模式 (敌人/小兵/倒地/队友/靶场) 动态重构配对逻辑
        """
        # 1. 决定当前最终使用的模型版本 (优先使用手动强制覆盖的 config.MODEL_VERSION，若为 "auto" 则使用自动识别的)
        model_ver = getattr(config, "MODEL_VERSION", "auto")
        if model_ver == "auto":
            model_ver = self.detected_model_ver
            
        target_mode = getattr(config, "TARGET_MODE", "enemy")

        # 2. 动态指定当前需要过滤并配对的头部和身体标签
        if model_ver == "old":
            head_class = 0
            body_class = 1
        else:  # new
            if target_mode == "enemy":
                head_class = 1
                body_class = 0
            elif target_mode == "practice":
                head_class = 6
                body_class = 5
            elif target_mode == "xiaobing":
                head_class = None
                body_class = 3
            elif target_mode == "daodi":
                head_class = None
                body_class = 4
            elif target_mode == "duiyou":
                head_class = None
                body_class = 2
            else:
                head_class = 1
                body_class = 0

        heads = []
        bodies = []
        for det in detections:
            cls_id = det["cls_id"]
            if head_class is not None and cls_id == head_class:
                heads.append(det)
            elif body_class is not None and cls_id == body_class:
                bodies.append(det)

        targets = []
        paired_bodies = set()

        # 3. 智能头身融合配对算法 (针对双部位目标)
        if head_class is not None:
            for head in heads:
                hx1, hy1, hx2, hy2 = head["box"]
                hcx = (hx1 + hx2) / 2
                hcy = (hy1 + hy2) / 2
                h_w = hx2 - hx1
                h_h = hy2 - hy1

                best_body = None
                min_dist = float("inf")

                for idx, body in enumerate(bodies):
                    if idx in paired_bodies:
                        continue
                    bx1, by1, bx2, by2 = body["box"]
                    bcx = (bx1 + bx2) / 2
                    
                    body_top_cx = bcx
                    body_top_cy = by1

                    dist = np.sqrt((hcx - body_top_cx)**2 + (hcy - body_top_cy)**2)
                    max_allowed_dist = max(200.0, (bx2 - bx1) * 1.8)
                    if dist < max_allowed_dist and dist < min_dist:
                        min_dist = dist
                        best_body = (idx, body)

                if best_body is not None:
                    body_idx, body = best_body
                    paired_bodies.add(body_idx)
                    
                    bx1, by1, bx2, by2 = body["box"]
                    x1 = min(hx1, bx1)
                    y1 = min(hy1, by1)
                    x2 = max(hx2, bx2)
                    y2 = max(hy2, by2)
                    
                    # 绝对精准头部点
                    head_x = hcx
                    head_y = hcy
                    
                    # 生理坐标修正
                    neck_x = hcx
                    neck_y = hy2 + h_h * 0.20
                    chest_x = hcx
                    chest_y = hy2 + h_h * 0.95
                    
                    targets.append({
                        "bbox": (int(x1), int(y1), int(x2), int(y2)),
                        "head_bbox": (int(hx1), int(hy1), int(hx2), int(hy2)),
                        "body_bbox": (int(bx1), int(by1), int(bx2), int(by2)),
                        "center": (int((x1 + x2) / 2), int((y1 + y2) / 2)),
                        "head": (int(head_x), int(head_y)),
                        "neck": (int(neck_x), int(neck_y)),
                        "chest": (int(chest_x), int(chest_y)),
                        "confidence": max(head["conf"], body["conf"]),
                        "class_id": 0,  # 0 代表有头有身体的完整目标
                        "area": int((x2 - x1) * (y2 - y1)),
                    })
                else:
                    # 独立头部（比如只露出头）
                    neck_x = hcx
                    neck_y = hy2 + h_h * 0.20
                    chest_x = hcx
                    chest_y = hy2 + h_h * 0.95
                    
                    targets.append({
                        "bbox": (int(hx1), int(hy1), int(hx2), int(hy2)),
                        "head_bbox": (int(hx1), int(hy1), int(hx2), int(hy2)),
                        "body_bbox": None,
                        "center": (int(hcx), int(hcy)),
                        "head": (int(hcx), int(hcy)),
                        "neck": (int(neck_x), int(neck_y)),
                        "chest": (int(chest_x), int(chest_y)),
                        "confidence": head["conf"],
                        "class_id": 0,
                        "area": int(h_w * h_h),
                    })

        # 4. 独立身体目标（针对未配对上的身体，或者单部位目标：小兵/队友/倒地等）
        for idx, body in enumerate(bodies):
            if idx in paired_bodies:
                continue
            bx1, by1, bx2, by2 = body["box"]
            bcx = (bx1 + bx2) / 2
            bcy = (by1 + by2) / 2
            b_w = bx2 - bx1
            b_h = by2 - by1

            # 如果没有头部类别，或者未配对成功，则根据解剖学比例估算
            h_h_est = b_h * 0.15

            head_x = bcx
            head_y = by1 - h_h_est * 0.50
            neck_x = bcx
            neck_y = by1 + b_h * 0.03
            chest_x = bcx
            chest_y = by1 + b_h * 0.12

            targets.append({
                "bbox": (int(bx1), int(by1), int(bx2), int(by2)),
                "head_bbox": None,
                "body_bbox": (int(bx1), int(by1), int(bx2), int(by2)),
                "center": (int(bcx), int(bcy)),
                "head": (int(head_x), int(head_y)),
                "neck": (int(neck_x), int(neck_y)),
                "chest": (int(chest_x), int(chest_y)),
                "confidence": body["conf"],
                "class_id": 1,  # 1 代表独立身体
                "area": int(b_w * b_h),
            })

        # 5. 准心排序算法
        cx = self.detect_size // 2
        cy = self.detect_size // 2

        def get_dist_to_crosshair(t):
            aim_part = getattr(config, "AIM_PART", "head")
            aim_pt = t.get(aim_part, t["head"])
            return np.sqrt((aim_pt[0] - cx)**2 + (aim_pt[1] - cy)**2)

        targets.sort(key=get_dist_to_crosshair)
        return targets

    def draw_results(self, frame, targets):
        for t in targets:
            if config.SHOW_BBOX:
                if t.get("is_extrapolated"):
                    # 5. 绘制航位推算外推框 - 金黄色细线框，展示高智能预测状态
                    x1, y1, x2, y2 = t["bbox"]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (241, 196, 15), 1)
                    cv2.putText(
                        frame,
                        "predicting...",
                        (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        (241, 196, 15),
                        1,
                    )
                else:
                    # 1. 绘制身体框 (如果有) - 浅绿色
                    if t.get("body_bbox") is not None:
                        bx1, by1, bx2, by2 = t["body_bbox"]
                        cv2.rectangle(frame, (bx1, by1), (bx2, by2), (46, 204, 113), 2)
                    
                    # 2. 绘制头部框 (如果有) - 高亮金橙色
                    if t.get("head_bbox") is not None:
                        hx1, hy1, hx2, hy2 = t["head_bbox"]
                        cv2.rectangle(frame, (hx1, hy1), (hx2, hy2), (0, 165, 255), 2)
                    
                    # 3. 绘制标签，优先挂在头部框上方，如果没有头部就挂在身体框上方
                    if t.get("head_bbox") is not None or t.get("body_bbox") is not None:
                        tx1, ty1 = t["head_bbox"][:2] if t.get("head_bbox") is not None else t["body_bbox"][:2]
                        cls_id = t.get("class_id", 0)
                        label_name = "target" if cls_id == 0 else "body"
                        label = f"{label_name} {t['confidence']:.2f}"
                        
                        label_color = (0, 165, 255) if t.get("head_bbox") is not None else (46, 204, 113)
                        cv2.putText(
                            frame,
                            label,
                            (tx1, ty1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.4,
                            label_color,
                            1,
                        )
                
            # 4. 绘制准星/红点瞄准标记 (红色实心小圆点)
            aim_part = getattr(config, "AIM_PART", "head")
            aim_pt = t.get(aim_part, t["head"])
            cv2.circle(frame, aim_pt, 3, (0, 0, 255), -1)

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
