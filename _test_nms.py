# -*- coding: utf-8 -*-
import cv2, numpy as np
print('cv2', cv2.__version__)
# 完全复刻源码 7265-7269 的畸形写法
detections = [(10, 10, 50, 50, 0.9), (12, 12, 52, 52, 0.8)]
try:
    boxes = [[d, d, d - d, d - d] for d in detections]
    scores = [d for d in detections]
    print('畸形boxes =', boxes)
    idx = cv2.dnn.NMSBoxes(boxes, scores, 0.4, 0.45)
    print('畸形NMS返回:', idx)
except Exception as e:
    print('畸形NMS抛Python异常:', repr(e))

# 正确写法: [x,y,w,h] + 纯float分数
try:
    boxes2 = [[x1, y1, x2 - x1, y2 - y1] for (x1, y1, x2, y2, s) in detections]
    scores2 = [float(s) for (x1, y1, x2, y2, s) in detections]
    idx2 = cv2.dnn.NMSBoxes(boxes2, scores2, 0.4, 0.45)
    print('正确NMS返回:', idx2)
except Exception as e:
    print('正确NMS异常:', repr(e))
