# 串口：
# F 夹爪正转
# B夹爪反转
# S电机停止
# G气泵吸取
# R气泵释放
# I全部待机

import serial
import time

# COM5 改成你电脑识别到的 USB-TTL 串口号
stm32 = serial.Serial("COM5", 115200, timeout=1)

time.sleep(2)

print("请输入指令：")
print("F=正转, B=反转, S=停止, G=吸取, R=释放, I=待机")

while True:
    cmd = input("指令：").strip().upper()

    if cmd in ["F", "B", "S", "G", "R", "I"]:
        stm32.write(cmd.encode("utf-8"))
        print("已发送：", cmd)
    else:
        print("无效指令")