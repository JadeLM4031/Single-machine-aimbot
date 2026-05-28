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
    """通用模型类别审判器 - 自动适配 .pt 和 .onnx 格式"""
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
                meta = session.get_modelmeta()
                if "names" in meta.custom_metadata_map:
                    raw_names = meta.custom_metadata_map["names"]
                    classes = json.loads(raw_names.replace("'", '"'))
                    print("\n✨ 破案了哥们！该 .onnx 模型包含的所有类别如下：")
                    for k, v in classes.items():
                        print(f"   索引 {k} ──> 对应标签: {v}")
                    return
            except Exception:
                pass  # 如果 ORT 读取失败，自动尝试下方的 YOLO 备用通路

        # 备用通路：如果 ORT 没装，或者 ONNX 元数据被魔改过，用 YOLO 库强行逆向它
        if HAS_YOLO:
            try:
                model = YOLO(file_path)
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
    TARGET_MODEL = "models/PUBGV8_320.onnx"

    inspect_model(TARGET_MODEL)
