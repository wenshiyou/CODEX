# -*- coding: utf-8 -*-
import time, cv2, numpy as np
print('cv2版本:', cv2.__version__)
t = time.time()
try:
    net = cv2.dnn.readNetFromONNX('best.onnx')
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    print('模型加载成功, 耗时 %.2f 秒' % (time.time() - t))
except Exception as e:
    print('模型加载失败(%.2fs): %r' % (time.time() - t, e))
    raise SystemExit
# 跑一次前向
img = np.full((640, 640, 3), 114, dtype=np.uint8)
blob = cv2.dnn.blobFromImage(img, 1/255.0, (640, 640), swapRB=True, crop=False)
net.setInput(blob)
t = time.time()
out = net.forward()
print('首次推理成功, shape=%s, 耗时 %.3f 秒' % (getattr(out, 'shape', None), time.time() - t))
t = time.time()
for _ in range(3):
    net.setInput(blob); net.forward()
print('再推理3次总耗时 %.3f 秒' % (time.time() - t))
