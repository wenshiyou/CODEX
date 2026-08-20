"""YOLO怪物检测 - 正确letterbox缩放"""
import cv2
import numpy as np

net = cv2.dnn.readNetFromONNX('best.onnx')
frame = cv2.imread('debug_capture.png')
h, w = frame.shape[:2]
INPUT_SIZE = 640

# 计算letterbox缩放
scale = min(INPUT_SIZE / w, INPUT_SIZE / h)
new_w = int(w * scale)
new_h = int(h * scale)
pad_x = (INPUT_SIZE - new_w) // 2
pad_y = (INPUT_SIZE - new_h) // 2
print(f"scale={scale:.4f} new={new_w}x{new_h} pad=({pad_x},{pad_y})")

# 预处理
resized = cv2.resize(frame, (new_w, new_h))
padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
padded[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = resized
blob = cv2.dnn.blobFromImage(padded, 1/255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
net.setInput(blob)
out = net.forward()[0]  # (300, 6)

# 解析
detections = []
for row in out:
    x1, y1, x2, y2, score, cls = row
    if score < 0.4:
        continue
    # 还原到原图坐标
    x1 = int((x1 - pad_x) / scale)
    y1 = int((y1 - pad_y) / scale)
    x2 = int((x2 - pad_x) / scale)
    y2 = int((y2 - pad_y) / scale)
    detections.append((x1, y1, x2, y2, float(score), int(cls)))

print(f"检测到 {len(detections)} 个怪物:")
disp = frame.copy()
for i, (x1, y1, x2, y2, score, cls) in enumerate(detections):
    cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cx, cy = (x1+x2)//2, (y1+y2)//2
    cv2.circle(disp, (cx, cy), 4, (0, 0, 255), -1)
    cv2.putText(disp, f"monster{i} {score:.2f}", (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    print(f"  monster{i}: ({x1},{y1})-({x2},{y2}) center=({cx},{cy}) score={score:.2f}")

cv2.imwrite('debug_yolo2.png', disp)
print("已保存 debug_yolo2.png")
