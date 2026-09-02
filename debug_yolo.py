"""测试YOLO怪物检测 + 数字OCR"""
import cv2
import numpy as np

# === YOLO测试 ===
net = cv2.dnn.readNetFromONNX('best.onnx')
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

frame = cv2.imread('debug_capture.png')
h, w = frame.shape[:2]
print("frame:", frame.shape)

# YOLOv8预处理
INPUT_SIZE = 640
blob = cv2.dnn.blobFromImage(frame, 1/255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=True, crop=False)
net.setInput(blob)
outputs = net.forward()
print("output shape:", outputs.shape)  # (1, 84, 8400) for YOLOv8

# 解析YOLOv8输出
output = outputs[0].T  # (8400, 84)
boxes = []
confidences = []
class_ids = []
x_factor = w / INPUT_SIZE
y_factor = h / INPUT_SIZE

for det in output:
    scores = det[4:]
    class_id = int(np.argmax(scores))
    confidence = scores[class_id]
    if confidence > 0.25:
        cx, cy, bw, bh = det[0], det[1], det[2], det[3]
        x1 = int((cx - bw/2) * x_factor)
        y1 = int((cy - bh/2) * y_factor)
        x2 = int((cx + bw/2) * x_factor)
        y2 = int((cy + bh/2) * y_factor)
        boxes.append([x1, y1, x2-x1, y2-y1])
        confidences.append(float(confidence))
        class_ids.append(class_id)

indices = cv2.dnn.NMSBoxes(boxes, confidences, 0.25, 0.45)
print(f"检测到 {len(indices)} 个目标")

# 读取classes.txt
try:
    with open('classes.txt', 'r') as f:
        classes = [l.strip() for l in f.readlines()]
    print("classes:", classes)
except:
    classes = [f"class_{i}" for i in range(80)]
    print("未找到classes.txt，用默认名")

disp = frame.copy()
for i in indices:
    x, y, bw, bh = boxes[i]
    cv2.rectangle(disp, (x, y), (x+bw, y+bh), (0, 255, 0), 2)
    label = f"{classes[class_ids[i]]} {confidences[i]:.2f}"
    cv2.putText(disp, label, (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    print(f"  {label} at ({x},{y},{bw},{bh})")

cv2.imwrite('debug_yolo.png', disp)
print("已保存 debug_yolo.png")
