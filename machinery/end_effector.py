# STM32 端需要提前烧录好串口接收程序
#
# STM32 指令：
# F：夹爪正转
# B：夹爪反转
# S：夹爪停止
# G：气泵吸取
# R：释放破真空
# I：全部待机

import time
import serial


class EndEffector:
    def __init__(
        self,
        port: str = "COM5",
        baudrate: int = 115200,
        timeout: float = 1.0,
        close_cmd: str = "F",
        open_cmd: str = "B",
    ):
        """
        初始化末端执行器串口控制类

        参数说明：
        port：STM32 对应的串口号，例如 COM5、COM6
        baudrate：波特率，必须和 STM32 程序一致，默认 115200
        timeout：串口超时时间
        close_cmd：夹爪闭合方向，默认 F
        open_cmd：夹爪张开方向，默认 B

        如果发现夹爪闭合和张开反了，只需要把 close_cmd 和 open_cmd 对调：
        EndEffector(port="COM5", close_cmd="B", open_cmd="F")
        """

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        self.close_cmd = close_cmd
        self.open_cmd = open_cmd

        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
        )

        # 等待 STM32 串口稳定
        time.sleep(2)

    def send_cmd(self, cmd: str, delay: float = 0.05):
        """
        向 STM32 发送单字符命令
        """

        if not isinstance(cmd, str):
            raise TypeError("cmd 必须是字符串")

        if len(cmd) != 1:
            raise ValueError("cmd 必须是单个字符，例如 'G'、'R'、'F'")

        self.ser.write(cmd.encode("utf-8"))
        self.ser.flush()
        time.sleep(delay)

    # =========================
    # 基础电机控制
    # =========================

    def motor_forward(self):
        """
        电机正转
        """
        self.send_cmd("F")

    def motor_reverse(self):
        """
        电机反转
        """
        self.send_cmd("B")

    def motor_stop(self):
        """
        电机停止
        """
        self.send_cmd("S")

    # =========================
    # 夹爪动作
    # =========================

    def gripper_close(self, run_time: float = 0.8):
        """
        夹爪闭合

        run_time：夹爪闭合持续时间，单位秒
        需要根据实际夹爪开合距离调整
        """

        self.send_cmd(self.close_cmd)
        time.sleep(run_time)
        self.send_cmd("S")

    def gripper_open(self, run_time: float = 0.8):
        """
        夹爪张开

        run_time：夹爪张开持续时间，单位秒
        """

        self.send_cmd(self.open_cmd)
        time.sleep(run_time)
        self.send_cmd("S")

    # =========================
    # 吸盘 / 气泵 / 电磁阀
    # =========================

    def suction_on(self):
        """
        吸盘吸取
        STM32 执行：气泵开，电磁阀关
        """

        self.send_cmd("G")

    def release_vacuum(self):
        """
        释放破真空
        STM32 执行：气泵关，电磁阀打开一小段时间后自动关闭
        """

        self.send_cmd("R")

    def idle(self):
        """
        全部待机
        电机停止，气泵关闭，电磁阀关闭
        """

        self.send_cmd("I")

    # =========================
    # 常用组合动作
    # =========================

    def grab_by_suction(self, wait_time: float = 0.5):
        """
        只用吸盘抓取
        """

        self.suction_on()
        time.sleep(wait_time)

    def grab_by_gripper(self, close_time: float = 0.8):
        """
        只用夹爪抓取
        """

        self.gripper_close(run_time=close_time)

    def grab_by_suction_and_gripper(
        self,
        suction_wait: float = 0.5,
        close_time: float = 0.8,
    ):
        """
        吸盘 + 夹爪组合抓取
        """

        self.suction_on()
        time.sleep(suction_wait)
        self.gripper_close(run_time=close_time)

    def release_all(
        self,
        open_time: float = 0.8,
        valve_wait: float = 0.4,
    ):
        """
        完整释放动作

        先张开夹爪，再破真空释放
        """

        self.gripper_open(run_time=open_time)
        time.sleep(0.1)
        self.release_vacuum()
        time.sleep(valve_wait)
        self.idle()

    def close(self):
        """
        关闭串口
        """

        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        """
        支持 with 语法
        """

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        退出 with 时自动关闭串口
        """

        self.close()


if __name__ == "__main__":
    """
    单独测试用：
    运行这个文件后，可以手动输入 F/B/S/G/R/I 测试末端
    """

    end = EndEffector(port="COM5", baudrate=115200)

    print("末端执行器测试程序")
    print("F：电机正转")
    print("B：电机反转")
    print("S：电机停止")
    print("G：气泵吸取")
    print("R：释放破真空")
    print("I：全部待机")
    print("C：夹爪闭合一次")
    print("O：夹爪张开一次")
    print("A：吸盘+夹爪组合抓取")
    print("X：完整释放")
    print("Q：退出程序")

    try:
        while True:
            cmd = input("请输入指令：").strip().upper()

            if cmd == "Q":
                end.idle()
                break

            elif cmd in ["F", "B", "S", "G", "R", "I"]:
                end.send_cmd(cmd)

            elif cmd == "C":
                end.gripper_close(run_time=0.8)

            elif cmd == "O":
                end.gripper_open(run_time=0.8)

            elif cmd == "A":
                end.grab_by_suction_and_gripper(
                    suction_wait=0.5,
                    close_time=0.8,
                )

            elif cmd == "X":
                end.release_all(
                    open_time=0.8,
                    valve_wait=0.4,
                )

            else:
                print("无效指令")

    finally:
        end.close()
        print("串口已关闭")

