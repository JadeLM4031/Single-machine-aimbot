"""列出所有可用摄像头，帮你找到 OBS Virtual Camera 的索引"""

import cv2

print("检测可用摄像头...\n")

for i in range(10):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        print(f"  索引 {i}: {w}x{h} @ {fps}fps")
        cap.release()
    else:
        cap.release()

print("\n提示: OBS Virtual Camera 启动后通常显示为索引 0 或 1")
print("找到后修改 config.py 中的 OBS_CAMERA_INDEX")
