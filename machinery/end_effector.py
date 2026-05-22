# STM32 端需要提前烧录好串口接收程序
#
# STM32 指令：
# F：夹爪正转
# B：夹爪反转
# S：夹爪停止
# G：气泵吸取
# R：释放破真空
# I：全部待机

import argparse
import glob
import os
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ModuleNotFoundError as exc:
    raise SystemExit(
        "缺少 pyserial。当前 python 没有 serial 模块。\n"
        "可直接用系统 Python 运行：/usr/bin/python3 machinery/end_effector.py --list\n"
        "或安装到当前环境：python3 -m pip install pyserial"
    ) from exc


DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 1.0
UNSAFE_COMMANDS = {"F", "B", "G", "A", "X"}


def list_serial_ports() -> list[str]:
    """Return likely USB serial device paths on Linux/Windows."""

    ports = []
    for port in list_ports.comports():
        device = port.device
        if (
            device.startswith("/dev/ttyACM")
            or device.startswith("/dev/ttyUSB")
            or device.upper().startswith("COM")
        ):
            ports.append(device)

    # list_ports sometimes misses devices while permissions/metadata are odd.
    for pattern in ("/dev/serial/by-id/*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        ports.extend(glob.glob(pattern))

    # Preserve order while removing duplicates.
    unique_ports = []
    seen = set()
    for port in ports:
        if port not in seen:
            unique_ports.append(port)
            seen.add(port)

    return unique_ports


def auto_detect_port() -> str:
    ports = list_serial_ports()
    if not ports:
        raise RuntimeError(
            "没有找到 STM32/USB-TTL 串口设备。先插上硬件，再运行：\n"
            "  ls -l /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/*\n"
            "如果设备刚插上还没有出现，检查 USB 线、电源、烧录程序和 dmesg。"
        )

    # Prefer stable udev symlinks, then common USB serial names.
    for prefix in ("/dev/serial/by-id/", "/dev/ttyACM", "/dev/ttyUSB"):
        for port in ports:
            if port.startswith(prefix):
                return port

    raise RuntimeError(
        "只检测到非 USB 串口，未自动选择。请用 --port 明确指定末端执行器串口。"
    )


class EndEffector:
    def __init__(
        self,
        port: str | None = None,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT,
        close_cmd: str = "F",
        open_cmd: str = "B",
    ):
        """
        初始化末端执行器串口控制类

        参数说明：
        port：STM32 对应的串口号，例如 /dev/ttyUSB0、/dev/ttyACM0、COM5。
              为空时自动寻找常见 USB 串口。
        baudrate：波特率，必须和 STM32 程序一致，默认 115200
        timeout：串口超时时间
        close_cmd：夹爪闭合方向，默认 F
        open_cmd：夹爪张开方向，默认 B

        如果发现夹爪闭合和张开反了，只需要把 close_cmd 和 open_cmd 对调：
        EndEffector(port="/dev/ttyUSB0", close_cmd="B", open_cmd="F")
        """

        self.port = port or auto_detect_port()
        self.baudrate = baudrate
        self.timeout = timeout

        self.close_cmd = close_cmd
        self.open_cmd = open_cmd

        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )
        except serial.SerialException as exc:
            raise RuntimeError(
                f"无法打开串口 {self.port}: {exc}\n"
                "检查：1) 设备是否存在 2) 用户是否在 dialout 组 3) 串口是否被 Arduino IDE/串口助手占用。"
            ) from exc

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
        print(f"sent {cmd!r} -> {self.port}")

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
    parser = argparse.ArgumentParser(description="STM32 末端执行器串口测试")
    parser.add_argument("--list", action="store_true", help="列出检测到的串口后退出")
    parser.add_argument("--port", default="", help="串口，例如 /dev/ttyUSB0、/dev/ttyACM0；为空时自动检测")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--close-cmd", default="F", choices=["F", "B"], help="夹爪闭合方向")
    parser.add_argument("--open-cmd", default="B", choices=["F", "B"], help="夹爪张开方向")
    parser.add_argument("--cmd", default="", help="发送单条命令后退出：F/B/S/G/R/I/C/O/A/X")
    parser.add_argument("--run-time", type=float, default=0.25, help="C/O 测试时电机运行秒数，默认短脉冲")
    parser.add_argument("--unsafe", action="store_true", help="允许 F/B/G/A/X 这类可能持续动作的命令")
    args = parser.parse_args()

    ports = list_serial_ports()
    if args.list:
        if ports:
            print("检测到串口：")
            for port in ports:
                target = os.path.realpath(port) if os.path.islink(port) else ""
                print(f"  {port}" + (f" -> {target}" if target else ""))
        else:
            print("没有检测到 /dev/ttyUSB* 或 /dev/ttyACM*。请先插上 STM32/USB-TTL。")
        sys.exit(0)

    end = EndEffector(
        port=args.port or None,
        baudrate=args.baudrate,
        timeout=args.timeout,
        close_cmd=args.close_cmd,
        open_cmd=args.open_cmd,
    )

    print("末端执行器测试程序")
    print(f"串口：{end.port}，波特率：{end.baudrate}")
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
        if args.cmd:
            cmd = args.cmd.strip().upper()
            if cmd in UNSAFE_COMMANDS and not args.unsafe:
                raise SystemExit(
                    f"{cmd} 可能触发持续动作。确认安全后加 --unsafe，"
                    "或先用 S/I/C/O/R 这类更安全的命令。"
                )
            if cmd in ["F", "B", "S", "G", "R", "I"]:
                end.send_cmd(cmd)
            elif cmd == "C":
                end.gripper_close(run_time=args.run_time)
            elif cmd == "O":
                end.gripper_open(run_time=args.run_time)
            elif cmd == "A":
                end.grab_by_suction_and_gripper(
                    suction_wait=0.5,
                    close_time=args.run_time,
                )
            elif cmd == "X":
                end.release_all(
                    open_time=args.run_time,
                    valve_wait=0.4,
                )
            else:
                raise SystemExit(f"无效 --cmd: {cmd}")
            sys.exit(0)

        while True:
            cmd = input("请输入指令：").strip().upper()
            if cmd in UNSAFE_COMMANDS and not args.unsafe:
                print(f"{cmd} 已拦截：可能触发持续动作。确认安全后用 --unsafe 重新启动。")
                continue

            if cmd == "Q":
                end.idle()
                break

            elif cmd in ["F", "B", "S", "G", "R", "I"]:
                end.send_cmd(cmd)

            elif cmd == "C":
                end.gripper_close(run_time=args.run_time)

            elif cmd == "O":
                end.gripper_open(run_time=args.run_time)

            elif cmd == "A":
                end.grab_by_suction_and_gripper(
                    suction_wait=0.5,
                    close_time=args.run_time,
                )

            elif cmd == "X":
                end.release_all(
                    open_time=args.run_time,
                    valve_wait=0.4,
                )

            else:
                print("无效指令")

    finally:
        end.close()
        print("串口已关闭")

