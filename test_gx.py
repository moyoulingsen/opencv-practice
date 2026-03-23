import gxipy as gx
import cv2

device_manager = gx.DeviceManager()
dev_num, dev_info_list = device_manager.update_device_list()

print("发现设备数量:", dev_num)

if dev_num == 0:
    print("没有发现相机")
    raise SystemExit

cam = device_manager.open_device_by_index(1)
cam.stream_on()

print("开始取流，按 ESC 退出，按 s 保存图片")

count = 0

while True:
    raw_image = cam.data_stream[0].get_image()
    if raw_image is None:
        continue

    rgb_image = raw_image.convert("RGB")
    if rgb_image is None:
        continue

    frame = rgb_image.get_numpy_array()
    if frame is None:
        continue

    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    cv2.imshow("Daheng Camera", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == 27:  # ESC
        break
    elif key == ord("s"):
        filename = f"frame_{count}.jpg"
        cv2.imwrite(filename, frame)
        print("已保存:", filename)
        count += 1

cam.stream_off()
cam.close_device()
cv2.destroyAllWindows()
