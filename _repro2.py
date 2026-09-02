# -*- coding: utf-8 -*-
import mss, cv2, numpy as np, time, traceback
sct = mss.mss()
mon = {'left': -14, 'top': 56, 'width': 1382, 'height': 807}
net = cv2.dnn.readNetFromONNX('best.onnx')
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
INPUT = 640
fwd_times = []
nms_ok = 0
det_total = 0
t0 = time.time()
for i in range(300):
    try:
        raw = np.array(sct.grab(mon))
        img = raw[:, :, :3]
        h, w = img.shape[:2]
        scale = min(INPUT / w, INPUT / h)
        nw, nh = int(w * scale), int(h * scale)
        px = (INPUT - nw) // 2; py = (INPUT - nh) // 2
        resized = cv2.resize(img, (nw, nh))
        padded = np.full((INPUT, INPUT, 3), 114, dtype=np.uint8)
        padded[py:py + nh, px:px + nw] = resized
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, (INPUT, INPUT), swapRB=True, crop=False)
        net.setInput(blob)
        tf = time.time(); out = net.forward()[0]; fwd_times.append(time.time() - tf)
        detections = []
        for row in out:
            x1, y1, x2, y2, score, cls = row
            if score >= 0.4:
                x1 = int((x1 - px) / scale); y1 = int((y1 - py) / scale)
                x2 = int((x2 - px) / scale); y2 = int((y2 - py) / scale)
                if x2 > x1 and y2 > y1 and 20 <= x2 - x1 <= 130 and 30 <= y2 - y1 <= 160:
                    detections.append((x1, y1, x2, y2, float(score)))
        if detections:
            det_total += len(detections)
            boxes = [[d[0], d[1], d[2] - d[0], d[3] - d[1]] for d in detections]
            scores = [d[4] for d in detections]
            indices = cv2.dnn.NMSBoxes(boxes, scores, 0.4, 0.45)
            if len(indices) > 0:
                nms_ok += 1
                if i <= 2:
                    print('帧%d 检测到%d目标, NMS后保留%d' % (i, len(detections), len(indices)))
    except Exception as e:
        print('帧%d 异常: %r' % (i, e))
        traceback.print_exc()
        break
print('完成%d帧 总耗时%.1fs forward平均%.3fs最大%.3fs 有目标帧NMS成功%d次 总检测目标%d' % (
    i + 1, time.time() - t0, sum(fwd_times) / max(1, len(fwd_times)),
    max(fwd_times) if fwd_times else 0, nms_ok, det_total))
