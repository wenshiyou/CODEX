# -*- coding: utf-8 -*-
import mss, cv2, numpy as np, time, traceback
sct = mss.mss()
# 游戏窗口 rect(来自日志): left=-14 top=56 1382x807
mon = {'left': -14, 'top': 56, 'width': 1382, 'height': 807}
net = cv2.dnn.readNetFromONNX('best.onnx')
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
INPUT = 640
nms_err = 0
fwd_times = []
t0 = time.time()
for i in range(300):
    try:
        raw = np.array(sct.grab(mon))
        img = raw[:, :, :3]  # BGRA -> BGR
        h, w = img.shape[:2]
        scale = min(INPUT / w, INPUT / h)
        nw, nh = int(w * scale), int(h * scale)
        px = (INPUT - nw) // 2; py = (INPUT - nh) // 2
        resized = cv2.resize(img, (nw, nh))
        padded = np.full((INPUT, INPUT, 3), 114, dtype=np.uint8)
        padded[py:py + nh, px:px + nw] = resized
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, (INPUT, INPUT), swapRB=True, crop=False)
        net.setInput(blob)
        tf = time.time(); out = net.forward(); fwd_times.append(time.time() - tf)
        dets = []
        for row in out:
            x1, y1, x2, y2, score, cls = row
            if score >= 0.4:
                x1 = int((x1 - px) / scale); y1 = int((y1 - py) / scale)
                x2 = int((x2 - px) / scale); y2 = int((y2 - py) / scale)
                if x2 > x1 and y2 > y1 and 20 <= x2 - x1 <= 130 and 30 <= y2 - y1 <= 160:
                    dets.append((x1, y1, x2, y2, float(score)))
        if dets:
            try:
                # 完全复刻源码7266畸形写法
                boxes = [[d, d, d - d, d - d] for d in dets]
                scores = [d for d in dets]
                cv2.dnn.NMSBoxes(boxes, scores, 0.4, 0.45)
            except Exception:
                nms_err += 1
                if nms_err <= 2:
                    print('帧%d NMS异常(检测到%d目标): %s' % (i, len(dets), traceback.format_exc().splitlines()[-1]))
    except Exception as e:
        print('帧%d 整体异常: %r' % (i, e))
        traceback.print_exc()
        break
print('完成 %d 帧, 总耗时%.1fs, forward平均%.3fs 最大%.3fs, 检测到目标的帧NMS异常=%d次' % (
    i + 1, time.time() - t0, sum(fwd_times) / max(1, len(fwd_times)), max(fwd_times) if fwd_times else 0, nms_err))
