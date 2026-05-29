import os
import json

# 🟢 【自动检测环境】
try:
    from ultralytics import YOLO

    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False

try:
    import onnxruntime as ort

    HAS_ORT = True
except ImportError:
    HAS_ORT = False


def inspect_model(file_path):
    """通用模型矩阵与类别审判器 - 自动适配 .pt 和 .onnx 格式"""
    if not os.path.exists(file_path):
        print(f"❌ 错误：找不到文件 '{file_path}'，请检查名字是否写错。")
        return

    ext = os.path.splitext(file_path)[1].lower()
    print(f"\n🚀 正在解剖模型: {file_path} ...")

    # ==================== 1. 如果是 PT 模型 ====================
    if ext == ".pt":
        if not HAS_YOLO:
            print("❌ 错误：检测到 .pt 模型，但当前 Python 环境未安装 ultralytics 库！")
            print("💡 解决办法：请在终端运行: pip install ultralytics")
            return

        try:
            model = YOLO(file_path)

            # 🟢 先提取并输出 .pt 模型的矩阵大小
            imgsz = getattr(model.model, "args", {}).get("imgsz", None)
            if imgsz is None and hasattr(model.model, "pt_path"):
                # 备用方案：如果 args 里没拿全，尝试去读模型前向传播的内部配置
                imgsz = [320, 320]  # YOLOv8 默认保底常规尺寸

            print("\n📐 【矩阵指纹分析】")
            print(
                f"   输入张量维度 ──> BatchSize: 1, 通道数: 3 (RGB), 物理高宽: {imgsz}"
            )
            print(f"   💡 调机提示：请确保你代码里的 detect_size 与该高宽完全一致！")

            # 🟢 再输出标签类别
            print("\n✨ 破案了哥们！该 .pt 模型包含的所有类别如下：")
            for k, v in model.names.items():
                print(f"   索引 {k} ──> 对应标签: {v}")

        except Exception as e:
            print(f"❌ 读取 .pt 发生严重异常: {e}")

    # ==================== 2. 如果是 ONNX 模型 ====================
    elif ext == ".onnx":
        # 优先使用 ORT（速度最快且最清爽，不需要安装庞大的 PyTorch）
        if HAS_ORT:
            try:
                session = ort.InferenceSession(
                    file_path, providers=["CPUExecutionProvider"]
                )

                # 🟢 先提取并输出 .onnx 模型的底层输入矩阵维度
                model_inputs = session.get_inputs()
                if model_inputs:
                    input_shape = model_inputs[
                        0
                    ].shape  # 通常格式为 [1, 3, 320, 320] 或 ['batch', 3, 640, 640]
                    print("\n📐 【矩阵指纹分析】")
                    print(f"   ONNX 物理输入矩阵结构 ──> {input_shape}")
                    if len(input_shape) == 4:
                        print(
                            f"   💡 调机提示：网络要求的分辨率为 {input_shape[2]}x{input_shape[3]}，请去 detector.py 里对齐！"
                        )

                # 🟢 再尝试读取元数据里的类别标签
                meta = session.get_modelmeta()
                if "names" in meta.custom_metadata_map:
                    raw_names = meta.custom_metadata_map["names"]
                    classes = json.loads(raw_names.replace("'", '"'))
                    print("\n✨ 破案了哥们！该 .onnx 模型包含的所有类别如下：")
                    for k, v in classes.items():
                        print(f"   索引 {k} ──> 对应标签: {v}")
                    return
                else:
                    print(
                        "\n⚠️ 提示：该 ONNX 元数据中未发现嵌入式的 'names' 属性，正在启用 YOLO 引擎进行深层逆向..."
                    )
            except Exception:
                pass  # 如果 ORT 读取失败，自动尝试下方的 YOLO 备用通路

        # 备用通路：如果 ORT 没装，或者 ONNX 元数据被魔改过，用 YOLO 库强行逆向它
        if HAS_YOLO:
            try:
                model = YOLO(file_path)

                # 🟢 先读取输入高宽
                imgsz = getattr(model.model, "args", {}).get("imgsz", [320, 320])
                print("\n📐 【矩阵指纹分析 (YOLO引擎)】")
                print(f"   输入高宽 ──> {imgsz}")

                # 🟢 再输出类别
                print(
                    "\n✨ 破案了哥们！（通过YOLO引擎）该 .onnx 模型包含的所有类别如下："
                )
                for k, v in model.names.items():
                    print(f"   索引 {k} ──> 对应标签: {v}")
                return
            except Exception as e:
                print(f"❌ YOLO 引擎尝试解析 .onnx 失败: {e}")
                return

        print(
            "❌ 错误：解析 .onnx 失败。请确保你的环境中至少安装了 `onnxruntime` 或 `ultralytics` 的其中一个！"
        )

    else:
        print(f"⚠️ 无法识别的后缀名 '{ext}'。本脚本仅支持标准的 .pt 和 .onnx 模型文件。")


if __name__ == "__main__":
    # 🟢 提示：把下面这行改成你实际拿到的模型名字（放同一个文件夹下）
    TARGET_MODEL = "models/sjz_bb_260305_v11s_320.onnx"

    inspect_model(TARGET_MODEL)
