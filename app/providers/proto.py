# -*- coding: utf-8 -*-
"""各家 2.4G 方案的只读电量帧。

这里只做组帧和校验，不打开设备。校验失败就返回 None，
调用方不得把对不上的字节当成电量。
"""
from __future__ import annotations


def compx_request() -> bytes:
    """Compx / Nordic 17 字节电量查询。末字节使整帧和为 0x55。"""
    frame = bytearray(17)
    frame[0] = 0x08
    frame[1] = 0x04
    frame[16] = (0x55 - (sum(frame[:16]) & 0xFF)) & 0xFF
    return bytes(frame)


def parse_compx(data: bytes, tenths: bool = False) -> tuple[float, bool] | None:
    """17 字节帧。有的驱动会在前面再垫一个报告号，两种起点都认，但校验必须过。

    Nordic 的 0x08 / 0x09 应答本身就是百分比。只有 Areson 的 25A7 接收器
    把 0x09 的电量写成 0–10 档，调用方把 tenths 打开后才按 10% 一档换算。
    """
    for start in (0, 1):
        if len(data) < start + 17:
            continue
        chunk = bytes(data[start:start + 17])
        if chunk[0] not in (0x08, 0x09) or chunk[1] != 0x04:
            continue
        if (sum(chunk) & 0xFF) != 0x55:
            continue
        level = chunk[6]
        if not 0 <= level <= 100:
            continue
        if tenths and chunk[0] == 0x09 and level <= 10:
            level *= 10
        return float(level), chunk[7] != 0
    return None


def feature83_request() -> bytes:
    """万灵 / 兰族 / 卓威等 8K 接收器、中颖公版共用的特征报告。

    报告号 0，随后 ``00 00 02 02 00 83``。
    """
    buf = bytearray(65)
    buf[3] = 0x02
    buf[4] = 0x02
    buf[6] = 0x83
    return bytes(buf)


def _charging_flag(value: int) -> bool:
    """1 是充电，2 是充满仍插着。别的值不当成“这帧无效”。"""
    return value in (1, 2)


def parse_feature83(data: bytes) -> tuple[float, bool] | None:
    if len(data) < 8:
        return None
    # 中颖 / 万灵：0x83 在第 6 字节，电量在第 8 字节。
    # 报告号被系统拿掉时，整帧会往前错一字节，0x83 落到第 5 字节。
    for mark in (6, 5):
        level_at = mark + 2
        if level_at >= len(data) or data[mark] != 0x83:
            continue
        level = data[level_at]
        if 0 <= level <= 100:
            return float(level), data[mark + 1] not in (0, 0xFF)
    # 迈从 A5：前部带 0xA1，电量在第 7 字节。充电字节不是 0/1 也不把电量丢掉。
    if (0xA1 in data[:4] and 0x83 in data[:6] and 0 <= data[7] <= 100):
        return float(data[7]), _charging_flag(data[6])
    return None


def parse_hidpp_version(payload: bytes) -> tuple[int, int] | None:
    """HID++ 根特性返回的协议版本。

    普通 2.0 设备前两字节就是主、次版本。C54D 这种 LIGHTSPEED 接收器
    （GPW / PRO X）把应答写成 ``00 00 02``，版本在第 3 字节，0x02 表示 2.0。
    前两字节是 0 不能当成 1.0，否则电量会去读根本不存在的旧寄存器。
    """
    if not payload:
        return None
    major = payload[0]
    minor = payload[1] if len(payload) > 1 else 0
    # 第 3 字节 0x02 是 HID++ 2.0，0x04 是仍走 2.0 特性表的 4.x。
    if major == 0 and minor == 0 and len(payload) > 2 and payload[2] in (0x02, 0x04):
        return payload[2], 0
    return major, minor


# 内核 hid-logitech-hidpp.c 的 0x1001 电压曲线，下标 0 是 100%，下标 99 是 1%。
_HIDPP_MV = (
    4186, 4156, 4143, 4133, 4122, 4113, 4103, 4094, 4086, 4075,
    4067, 4059, 4051, 4043, 4035, 4027, 4019, 4011, 4003, 3997,
    3989, 3983, 3976, 3969, 3961, 3955, 3949, 3942, 3935, 3929,
    3922, 3916, 3909, 3902, 3896, 3890, 3883, 3877, 3870, 3865,
    3859, 3853, 3848, 3842, 3837, 3833, 3828, 3824, 3819, 3815,
    3811, 3808, 3804, 3800, 3797, 3793, 3790, 3787, 3784, 3781,
    3778, 3775, 3772, 3770, 3767, 3764, 3762, 3759, 3757, 3754,
    3751, 3748, 3744, 3741, 3737, 3734, 3730, 3726, 3724, 3720,
    3717, 3714, 3710, 3706, 3702, 3697, 3693, 3688, 3683, 3677,
    3671, 3666, 3662, 3658, 3654, 3646, 3633, 3612, 3579, 3537,
)


def parse_hidpp20_level(payload: bytes) -> tuple[float, bool] | None:
    """特性 0x1000。第 0 字节是百分比，第 2 字节是状态，不是另一份电量。

    放电中的 0 是空电。充电等状态下的 0 表示固件还不知道，不能显示成 0%。
    状态 1–4 都是在充电（含慢充和充满）。
    """
    if len(payload) < 3:
        return None
    level = payload[0]
    status = payload[2]
    if status > 7:
        return None
    if level == 0 and status != 0:
        return None
    if not 0 <= level <= 100:
        return None
    return float(level), status in (1, 2, 3, 4)


def parse_hidpp20_voltage(payload: bytes) -> tuple[float, bool] | None:
    """特性 0x1001。前两字节是毫伏，第 3 字节不是百分比。"""
    if len(payload) < 3:
        return None
    mv = (payload[0] << 8) | payload[1]
    if not 3500 <= mv < 5000:
        return None
    percent = 0
    for index, threshold in enumerate(_HIDPP_MV):
        if mv >= threshold:
            percent = 100 - index
            break
    flags = payload[2]
    charging = bool(flags & 0x80) and (flags & 0x07) != 2
    return float(percent), charging


def parse_hidpp20_unified(payload: bytes) -> tuple[float, bool] | None:
    """特性 0x1004 的电量状态。有百分比就用百分比，没有就用粗档。"""
    if len(payload) < 3:
        return None
    status = payload[2]
    if status > 7:
        return None
    charging = status in (1, 2, 3, 4)
    level = payload[0]
    if 1 <= level <= 100 or (level == 0 and status == 0):
        return float(level), charging
    coarse = {1: 5, 2: 20, 4: 55, 8: 100}.get(payload[1])
    if coarse is None:
        return None
    return float(coarse), charging


def parse_hidpp10_mileage(params: bytes) -> tuple[float, bool] | None:
    """寄存器 0x0D：第 0 字节是百分比，第 2 字节高 2 位是充放电。"""
    if not params or not 0 <= params[0] <= 100:
        return None
    status = params[2] if len(params) > 2 else 0
    return float(params[0]), (status >> 6) == 1


def parse_hidpp10_status(params: bytes) -> tuple[float, bool] | None:
    """寄存器 0x07：电量只有四档，换成大致百分比。"""
    if len(params) < 2:
        return None
    mapped = {1: 5, 2: 5, 3: 20, 4: 20, 5: 55, 6: 55, 7: 90}
    level = mapped.get(params[0])
    if level is None:
        return None
    charging = params[1] in (0x21, 0x22, 0x24, 0x25, 0x26)
    return float(level), charging


def razer_feature(transaction: int, command_id: int) -> bytes:
    """90 字节雷蛇报告，前面再加报告号 0。电量类 0x07。"""
    body = bytearray(90)
    body[1] = transaction & 0xFF
    body[5] = 0x02
    body[6] = 0x07
    body[7] = command_id & 0xFF
    crc = 0
    for i in range(2, 88):
        crc ^= body[i]
    body[88] = crc & 0xFF
    return bytes([0x00]) + bytes(body)


def _razer_arg1(data: bytes, command_id: int) -> int | None:
    """成功应答的状态字节是 0x02。

    带报告号时状态在第 1 字节、电量参数在第 10 字节。
    报告号 0 被系统省略时，整帧前移一字节。只认其中一种会把真电量丢掉。
    """
    layouts = (
        (1, 7, 8, 10),
        (0, 6, 7, 9),
    )
    for status_at, class_at, cmd_at, arg_at in layouts:
        if arg_at >= len(data):
            continue
        if (data[status_at] == 0x02 and data[class_at] == 0x07
                and data[cmd_at] == command_id):
            return data[arg_at]
    return None


def parse_razer_battery(data: bytes) -> float | None:
    raw = _razer_arg1(data, 0x80)
    if raw is None:
        return None
    percent = int(round(raw * 100 / 255))
    if not 0 <= percent <= 100:
        return None
    return float(percent)


def parse_razer_charging(data: bytes) -> bool | None:
    raw = _razer_arg1(data, 0x84)
    if raw is None:
        return None
    return raw == 1


def parse_asus(data: bytes) -> tuple[float, bool] | None:
    """华硕鼠标 ``12 07``，OMNI 键盘 ``12 01``。

    鼠标电量在命令后第 4 字节，充电再往后 5 字节。
    键盘电量在命令后第 5 字节，充电再往后 3 字节。
    应答可能带报告号，也可能从命令本身开始。
    不充电的 0 是休眠，不当成空电。
    """
    for base in (1, 0):
        if len(data) <= base + 1 or data[base] != 0x12:
            continue
        command = data[base + 1]
        if command == 0x07 and len(data) >= base + 10:
            level = data[base + 4]
            charging = data[base + 9] not in (0, 0xFF)
        elif command == 0x01 and len(data) >= base + 9:
            level = data[base + 5]
            charging = data[base + 8] not in (0, 0xFF)
        else:
            continue
        if not 0 <= level <= 100:
            continue
        if level == 0 and not charging:
            continue
        return float(level), charging
    return None


def vaxee_request(command: int) -> bytes:
    buf = bytearray(64)
    buf[0] = 0x0E
    buf[1] = 0xA5
    buf[2] = 0x01
    buf[3] = 0x01
    buf[4] = command & 0xFF
    return bytes(buf)


def parse_vaxee(data: bytes, command: int) -> int | None:
    if len(data) >= 6 and data[0] == 0x0E and data[4] == command:
        return data[5]
    # 报告号 0x0E 被拿掉后，帧从 0xA5 开始，命令和数值各前移一字节
    if len(data) >= 5 and data[0] == 0xA5 and data[3] == command:
        return data[4]
    return None


def parse_ajazz_status(data: bytes) -> float | None:
    """状态报告 0x05，电量在第 3 字节（含报告号）。"""
    if len(data) < 4 or data[0] != 0x05:
        return None
    level = data[3]
    if not 1 <= level <= 100:
        return None
    return float(level)


def parse_ds4(data: bytes) -> tuple[float, bool] | None:
    if len(data) < 64 or data[0] != 0x01:
        return None
    raw = data[30]
    level = raw & 0x0F
    if level > 10:
        return None
    return float(min(100, level * 10)), (raw & 0xF0) != 0


# HyperX Cloud III / Cloud II Core：报告号 0x66，电量指令 0x89。
# 第 2、3 字节都是 0 表示耳机不在线，不能把后面的字节当成电量。
def parse_hyperx_66_battery(data: bytes) -> float | None:
    if len(data) < 5 or data[0] != 0x66 or data[1] not in (0x89, 0x0D):
        return None
    if data[2] == 0 and data[3] == 0:
        return None
    level = data[4]
    if not 0 <= level <= 100:
        return None
    return float(level)


def parse_hyperx_66_charging(data: bytes) -> bool | None:
    if len(data) < 3 or data[0] != 0x66 or data[1] not in (0x8A, 0x0C):
        return None
    return data[2] in (1, 2)


def parse_hyperx_iiis_battery(data: bytes) -> float | None:
    """Cloud III S：报告 0x0C，指令在第 5 字节，电量在第 6 字节。0xFF 表示没有读数。"""
    if len(data) < 7 or data[0] != 0x0C or data[5] != 0x06 or data[6] == 0xFF:
        return None
    if not 0 <= data[6] <= 100:
        return None
    return float(data[6])


def parse_hyperx_iiis_charging(data: bytes) -> bool | None:
    if len(data) < 7 or data[0] != 0x0C or data[5] != 0x48 or data[6] == 0xFF:
        return None
    return data[6] in (1, 2)


def parse_hyperx_alpha_battery(data: bytes) -> float | None:
    if len(data) < 4 or data[0] != 0x21 or data[1] != 0xBB:
        return None
    if data[2] not in (0x0B, 0x25):
        return None
    if not 0 <= data[3] <= 100:
        return None
    return float(data[3])


def parse_hyperx_alpha_charging(data: bytes) -> bool | None:
    if len(data) < 4 or data[0] != 0x21 or data[1] != 0xBB:
        return None
    if data[2] not in (0x0C, 0x26):
        return None
    return data[3] in (1, 2)


def parse_hyperx_alpha2(data: bytes) -> tuple[float, bool] | None:
    """Cloud Alpha 2：应答 51 02，电量在第 2 字节，第 6 字节最高位表示在充电。"""
    if len(data) < 7 or data[0] != 0x51 or data[1] != 0x02:
        return None
    if not 0 <= data[2] <= 100:
        return None
    return float(data[2]), bool(data[6] & 0x80)


_FLIGHT_MV = (
    3328, 3584, 3674, 3704, 3732, 3744, 3754, 3764, 3774, 3784,
    3794, 3804, 3824, 3840, 3860, 3890, 3910, 3940, 3960, 3970,
)
_FLIGHT_PCT = (
    5, 10, 15, 20, 25, 30, 35, 40, 45, 50,
    55, 60, 65, 70, 75, 80, 85, 90, 95, 100,
)


def parse_hyperx_flight(data: bytes) -> tuple[float | None, bool] | None:
    """Cloud Flight 报的是电压。充电时电压字节是哨兵值，不再换算百分比。"""
    if len(data) < 5 or data[0] != 0x21 or data[1] != 0xFF or data[2] != 0x05:
        return None
    upper, lower = data[3], data[4]
    if (upper == 16 and lower >= 20) or upper >= 17:
        return None, True
    mv = (upper << 8) | lower
    index = 0
    for i, threshold in enumerate(_FLIGHT_MV):
        if threshold <= mv:
            index = i
        else:
            break
    return float(_FLIGHT_PCT[index]), False


def parse_hyperx_ii_dts_battery(data: bytes) -> float | None:
    if (len(data) < 8 or data[0] != 0x06 or data[1] != 0xFF
            or data[2] != 0xBB or data[3] != 0x02):
        return None
    if not 0 <= data[7] <= 100:
        return None
    return float(data[7])


def parse_hyperx_ii_dts_charging(data: bytes) -> bool | None:
    if (len(data) < 5 or data[0] != 0x06 or data[1] != 0xFF
            or data[2] != 0xBB or data[3] != 0x03):
        return None
    return data[4] in (1, 2)


def parse_hyperx_kingston_battery(data: bytes) -> float | None:
    if len(data) < 8 or data[0] != 0x0B or data[2] != 0xBB or data[3] != 0x02:
        return None
    if not 0 <= data[7] <= 100:
        return None
    return float(data[7])


def parse_hyperx_kingston_charging(data: bytes) -> bool | None:
    if len(data) < 5 or data[0] != 0x0B or data[2] != 0xBB or data[3] != 0x03:
        return None
    return data[4] in (1, 2)


def parse_8bitdo(data: bytes) -> tuple[float, bool] | None:
    if len(data) < 15 or data[0] not in (0x01, 0x04):
        return None
    raw = data[14]
    level = raw & 0x7F
    if not 1 <= level <= 100:
        return None
    return float(level), bool(raw & 0x80)


def nordic54_request(link: int) -> bytes:
    """ATK Zero 一类 Nordic 54。link 0 是有线，1 是接收器后面的鼠标。"""
    buf = bytearray(64)
    buf[0] = 0x08
    buf[1] = 0x7D
    buf[2] = 0x72
    buf[3] = 0x02
    buf[5] = link & 0xFF
    buf[6] = 0x07
    buf[7] = 0x01
    return bytes(buf)


def parse_nordic54(data: bytes) -> float | None:
    """应答要回显命令 0x72 和子项 0x07，状态 0 才是鼠标自己答的。

    这条查询在无线上不带充电标志，调用方不要自己猜。
    """
    layouts = (
        (1, 2, 5, 7),  # 报告号还在
        (0, 1, 4, 6),  # 报告号被拿掉
    )
    for cmd_at, status_at, echo_at, level_at in layouts:
        if level_at >= len(data):
            continue
        if data[cmd_at] != 0x72 or data[echo_at] != 0x07 or data[status_at] != 0:
            continue
        level = data[level_at]
        if 0 <= level <= 100:
            return float(level)
    return None


def parse_arctis(data: bytes, direct: bool) -> tuple[float, bool] | None:
    """Arctis ``b0``。字节 1 为 0x03 表示耳机在线，字节 2 是百分比，字节 3 为 1 表示在充电。

    旧款把 0–4 档放在同一个字节。未知型号只接受 5–100，避免把「满档」读成 4%。
    """
    for start in (0, 1):
        if len(data) < start + 4:
            continue
        if data[start] != 0xB0 or data[start + 1] != 0x03:
            continue
        level = data[start + 2]
        charge = data[start + 3]
        if charge not in (0, 1) or not 0 <= level <= 100:
            continue
        if not direct and level <= 4:
            return None
        return float(level), charge == 1
    return None


def parse_aerox(data: bytes) -> tuple[float, bool] | None:
    """Aerox 无线 ``d2``。bit7 是充电，低 7 位 1–21 是 5% 一档，再高就是百分比。0 是休眠。"""
    for start in (0, 1):
        if len(data) <= start + 1 or data[start] != 0xD2:
            continue
        raw = data[start + 1]
        if raw == 0:
            return None
        charging = bool(raw & 0x80)
        value = raw & 0x7F
        if 1 <= value <= 21:
            return float((value - 1) * 5), charging
        if 22 <= value <= 100:
            return float(value), charging
    return None


def parse_rival3(data: bytes) -> tuple[float, bool] | None:
    """Rival 3 无线。应答回显 ``aa``，电量在下一字节，再往后两字节只能是 0 或 1。"""
    for start in (0, 1):
        if len(data) < start + 4 or data[start] != 0xAA:
            continue
        level = data[start + 1]
        charge = data[start + 3]
        if charge not in (0, 1) or not 1 <= level <= 100:
            continue
        return float(level), charge == 1
    return None


def parse_jbl(data: bytes) -> float | None:
    """Quantum 接收器自己推的报告 0x08，电量在第 1 字节。没有充电位。"""
    if len(data) < 2 or data[0] != 0x08:
        return None
    level = data[1]
    if not 1 <= level <= 100:
        return None
    return float(level)


def flydigi_request(report_id: int) -> bytes:
    """Vader 5 Pro 的 GET_INFO。33 字节里前 6 字节是报告号和 ``5A A5 01 02 03``。"""
    buf = bytearray(33)
    buf[0] = report_id & 0xFF
    buf[1] = 0x5A
    buf[2] = 0xA5
    buf[3] = 0x01
    buf[4] = 0x02
    buf[5] = 0x03
    return bytes(buf)


def parse_flydigi(data: bytes) -> tuple[float, bool] | None:
    """只认 GET_INFO 应答。摇杆报告也以 5A A5 开头，但第 3 字节不是 0x01。

    电量字节的高 4 位是状态（0 放电，1 充电，2 充满），低 4 位是 0–5 档。
    """
    limit = min(4, len(data) - 11)
    for start in range(0, max(0, limit)):
        if data[start] != 0x5A or data[start + 1] != 0xA5 or data[start + 2] != 0x01:
            continue
        raw = data[start + 11]
        status = (raw >> 4) & 0x0F
        level = raw & 0x0F
        if level > 5 or status > 2:
            continue
        if status == 2:
            return 100.0, True
        return float(level * 20), status == 1
    return None


def mchose_g7_request() -> bytes:
    buf = bytearray(65)
    payload = bytes([0x00, 0x55, 0x30, 0xA5, 0x0B, 0x2E, 0x01, 0x01, 0x01])
    buf[:len(payload)] = payload
    return bytes(buf)


def parse_mchose_g7(data: bytes) -> tuple[float, bool] | None:
    """迈从 G7。``AA 30`` 后面第 8 字节是百分比，第 9 字节 1 表示在充电。"""
    for start in (0, 1):
        if len(data) < start + 10:
            continue
        if data[start] != 0xAA or data[start + 1] != 0x30:
            continue
        level = data[start + 8]
        charge = data[start + 9]
        if not 0 <= level <= 100 or charge not in (0, 1):
            continue
        return float(level), charge == 1
    return None
