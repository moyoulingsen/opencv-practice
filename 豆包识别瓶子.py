import gxipy as gx
import cv2
import numpy as np

def non_max_suppression(boxes, overlap_thresh=0.3):
    """标准 NMS 算法，去除重叠框"""
    if len(boxes) == 0: return []
    boxes = np.array(boxes)
    pick = []
    x1, y1, x2, y2 = boxes[:,0], boxes[:,1], boxes[:,2], boxes[:,3]
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(y2)
    while len(idxs) > 0:
        last = len(idxs) - 1
        i = idxs[last]
        pick.append(i)
        xx1 = np.maximum(x1[i], x1[idxs[:last]])
        yy1 = np.maximum(y1[i], y1[idxs[:last]])
        xx2 = np.minimum(x2[i], x2[idxs[:last]])
        yy2 = np.minimum(y2[i], y2[idxs[:last]])
        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)
        overlap = (w * h) / area[idxs[:last]]
        idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlap_thresh)[0])))
    return boxes[pick].astype("int").tolist()

# ===========================
# 相机初始化
# ===========================
device_manager = gx.DeviceManager()
dev_num, dev_info_list = device_manager.update_device_list()
if dev_num == 0: raise SystemExit("没有发现相机")
cam = device_manager.open_device_by_index(1)
cam.ExposureAuto.set(gx.GxAutoEntry.OFF)
cam.ExposureTime.set(20000.0)
cam.GainAuto.set(gx.GxAutoEntry.OFF)
cam.Gain.set(10.0)
cam.stream_on()
cv2.namedWindow("Precise Detection", cv2.WINDOW_NORMAL)
count = 0

while True:
    raw_image = cam.data_stream[0].get_image()
    if raw_image is None: continue
    rgb_image = raw_image.convert("RGB")
    frame = cv2.cvtColor(rgb_image.get_numpy_array(), cv2.COLOR_RGB2BGR)
    output_frame = frame.copy()

    # ===========================
    # 优化 1: 针对百岁山标签的颜色过滤 (HSV)
    # ===========================
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # 假设百岁山标签是粉色/紫色，你需要根据实际画面调整这两个阈值
    # 范围1: 粉色标签
    lower_pink = np.array([140, 50, 50])
    upper_pink = np.array([170, 255, 255])
    mask_pink = cv2.inRange(hsv, lower_pink, upper_pink)
    
    # 范围2: 白色瓶身/高光 (辅助)
    lower_white = np.array([0, 0, 200])
    upper_white = np.array([180, 30, 255])
    mask_white = cv2.inRange(hsv, lower_white, upper_white)

    # 合并掩码并做膨胀，把零散的色块连起来
    mask = cv2.bitwise_or(mask_pink, mask_white)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=2)

    # ===========================
    # 优化 2: 只在掩码区域找轮廓
    # ===========================
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bottle_boxes = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 2000: continue # 过滤噪点
        
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = h / w
        
        # 优化 3: 形状严格筛选
        # 1. 高宽比
        if not (1.5 < aspect_ratio < 5.0): continue
            
        # 2. 矩形度 (轮廓面积 / 外接矩形面积)，瓶子应该比较"实"
        rect_area = w * h
        extent = float(area) / rect_area
        if extent < 0.3: continue # 太松散的轮廓不要
        
        # 3. 凸包比 (检查形状是否凹陷严重)
        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        solidity = float(area) / hull_area
        if solidity < 0.5: continue # 形状太奇怪的不要

        bottle_boxes.append((x, y, x+w, y+h))

    # ===========================
    # 优化 4: 使用 NMS 去除重叠框
    # ===========================
    merged_boxes = non_max_suppression(bottle_boxes, overlap_thresh=0.3)

    # ===========================
    # 画图
    # ===========================
    centers = []
    for (x1, y1, x2, y2) in merged_boxes:
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        centers.append((cx, cy))
        cv2.rectangle(output_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.circle(output_frame, (cx, cy), 5, (0, 0, 255), -1)
        cv2.putText(output_frame, f"Bottle ({cx},{cy})", (x1, y1-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    # 为了调试，你可以把 mask 窗口也显示出来，看看颜色过滤准不准
    # cv2.imshow("Mask", mask)

    cv2.imshow("Precise Detection", output_frame)
    key = cv2.waitKey(1) & 0xFF
    if key == 27: break
    elif key == ord("s"):
        cv2.imwrite(f"frame_{count}.jpg", output_frame)
        count += 1

cam.stream_off()
cam.close_device()
cv2.destroyAllWindows()