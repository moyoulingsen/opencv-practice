import gxipy as gx
import cv2
import numpy as np

# ===========================
# 1. 打开相机
# ===========================
device_manager = gx.DeviceManager()
dev_num, dev_info_list = device_manager.update_device_list()
if dev_num == 0:
    raise SystemExit("没有发现相机")

cam = device_manager.open_device_by_index(1)
cam.ExposureAuto.set(gx.GxAutoEntry.OFF)
cam.ExposureTime.set(20000.0)
cam.GainAuto.set(gx.GxAutoEntry.OFF)
cam.Gain.set(10.0)
cam.stream_on()

cv2.namedWindow("Bottle Detection", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Bottle Detection", 960, 540)

count = 0
while True:
    raw_image = cam.data_stream[0].get_image()
    if raw_image is None:
        continue

    rgb_image = raw_image.convert("RGB")
    frame = cv2.cvtColor(rgb_image.get_numpy_array(), cv2.COLOR_RGB2BGR)

    # ---------------------------
    # 2. 边缘检测获取瓶子轮廓
    # ---------------------------
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    edges = cv2.Canny(blur, 50, 150)

    # 闭运算填充透明瓶子轮廓间隙
    kernel = np.ones((5,5), np.uint8)
    edges_closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    # ---------------------------
    # 3. 找轮廓
    # ---------------------------
    contours, _ = cv2.findContours(edges_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    centers = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 2000:  # 过滤小物体
            continue
        # 画整个瓶子轮廓
        cv2.drawContours(frame, [cnt], -1, (0,255,0), 2)
        # 中心坐标
        M = cv2.moments(cnt)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"]/M["m00"])
        cy = int(M["m01"]/M["m00"])
        centers.append((cx, cy))
        cv2.circle(frame, (cx, cy), 5, (0,0,255), -1)

    if centers:
        print("当前帧瓶子中心坐标:", centers)

    # ===========================
    # 显示可调缩放窗口
    # ===========================
    frame_resized = cv2.resize(frame, (960, 540))
    cv2.imshow("Bottle Detection", frame_resized)

    key = cv2.waitKey(1) & 0xFF
    if key == 27:  # ESC退出
        break
    elif key == ord("s"):  # 保存图片
        filename = f"frame_{count}.jpg"
        cv2.imwrite(filename, frame)
        print("已保存:", filename)
        count += 1

cam.stream_off()
cam.close_device()
cv2.destroyAllWindows()
