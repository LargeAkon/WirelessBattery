# -*- coding: utf-8 -*-
"""厂商协议库引擎：一条协议只描述「怎么读」，不描述「是哪只设备」。

为什么要有这一层：原来每个品牌都要在 `providers/oem.py` 里手写一个探针函数，
加一条协议就要改代码、重新打包。而市面上同方案的贴牌设备有几十个（凌豹、
狼蛛、LEOBOB 共用同一颗 Compx 接收器），协议的差异只是「发什么帧、取第几字节」。
把这些写成数据之后，加一个品牌 = 放一个 JSON，不用动 Python。

结构见 `profiles_data.py` 顶部说明。四种能力：

    load()       内置 57 条 + 配置目录 device_profiles/*.json
    for_ids()    按 VID:PID 找协议（精确 PID 优先于 VID 通配）
    read()       按协议发一帧、读回包、按偏移取电量
    probe()      协议未知时轮试全部模板（诊断页「自动探测」用）

两条和原实现一致的硬约定，不要「顺手优化」：
- 回包里 `level` 落在协议声明的 [min,max] 之外就不算命中，绝不 clamp 成 0~100；
- 全部样本都是 0 时按「休眠」处理，不显示 0%（0% 的鼠标早就关机了）。
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

try:
    import hid
except Exception:  # pragma: no cover
    hid = None

import profiles_data
from providers.hidpath import is_bluetooth, phys_token

DEFAULT_TIMEOUT = 4.5
_ID_OK = set("abcdefghijklmnopqrstuvwxyz0123456789._-")

# 描述符拿不到时的兜底：绝大多数厂商接收器是 64 字节报文
_FALLBACK_LEN = 64


# ---------------- 归一化 ----------------

def _int(value, default=None):
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip(), 0)
    except Exception:
        return default


def _hex_bytes(text) -> bytes:
    if not text:
        return b""
    if isinstance(text, (bytes, bytearray)):
        return bytes(text)
    parts = str(text).replace(",", " ").split()
    out = bytearray()
    for part in parts:
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part, 16) & 0xFF)
        except ValueError:
            continue
    return bytes(out)


def _offset(value, default=None):
    n = _int(value, default)
    if n is None:
        return None
    return max(0, min(1023, n))


def normalize(raw: dict, source: str = "builtin", fallback_id: str = "") -> dict | None:
    """把 JSON 摊平成读代码直接可用的结构；非法返回 None。"""
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("id") or fallback_id or "").strip().lower()
    if not pid or len(pid) > 64 or any(ch not in _ID_OK for ch in pid):
        return None

    known = []
    for item in raw.get("known_ids") or []:
        if not isinstance(item, dict):
            continue
        vid = str(item.get("vid") or "").strip().upper()
        if not vid:
            continue
        known.append({
            "vid": vid,
            "pid": str(item.get("pid") or "").strip().upper(),
            "wired_pid": str(item.get("wired_pid") or "").strip().upper(),
        })

    match = raw.get("match") or {}
    request = raw.get("request") or {}
    response = raw.get("response") or {}
    sampling = raw.get("sampling") or {}

    transport = str(request.get("transport") or "write_read").strip().lower()
    if transport not in ("write_read", "feature_read", "feature_write_read"):
        return None

    level = response.get("level") or {}
    status = response.get("status") or {}
    charging = response.get("charging") or {}

    return {
        "id": pid,
        "label": str(raw.get("label") or pid),
        "vendor": str(raw.get("vendor") or "其他"),
        "keywords": str(raw.get("keywords") or ""),
        "notes": str(raw.get("notes") or ""),
        "source": str(raw.get("source") or source),
        "enabled": raw.get("enabled", True) is not False,
        # 公版接收器共用 VID:PID 时靠它分流型号（Compx 会话 ACK）
        "model_code": _int(raw.get("model_code"), None),
        "known_ids": known,
        "match": {
            "usage_page": _int(match.get("usage_page"), 0xFF02) or 0xFF02,
            "usage": _int(match.get("usage"), None),
            "require_pid_hit": bool(match.get("require_pid_hit")),
        },
        "request": {
            "transport": transport,
            "payload": _hex_bytes(request.get("payload_hex")),
            "out_len": _int(request.get("out_len"), None),
            "in_len": _int(request.get("in_len"), None),
            "report_id": _int(request.get("report_id"), None),
            "read_matching": bool(request.get("read_matching")),
        },
        "response": {
            "min_length": _int(response.get("min_length"), 7) or 7,
            "exact_length": _int(response.get("exact_length"), None),
            "markers": [(o, b) for o, b in
                        ((_offset(p[0]), _int(p[1], 0)) for p in (response.get("markers") or [])
                         if isinstance(p, (list, tuple)) and len(p) == 2)
                        if o is not None and b is not None],
            "status": {
                "offset": _offset(status.get("offset"), None),
                "ok_values": [_int(v, 0) for v in (status.get("ok_values") or [0])],
            },
            "level": {
                "offset": _offset(level.get("offset"), 6) or 0,
                "encoding": str(level.get("encoding") or "u8").lower(),
                "min": _int(level.get("min"), 0),
                "max": _int(level.get("max"), 100),
                "scale": float(_int(level.get("scale"), 1) or 1),
                "add": float(_int(level.get("add"), 0) or 0),
                "mask": _int(level.get("mask"), None),
            },
            "charging": {
                "offset": _offset(charging.get("offset"), None),
                "nonzero": charging.get("nonzero", True) is not False,
                "when_charging": _int(charging.get("when_charging"), None),
                "mask": _int(charging.get("mask"), None),
            },
        },
        "sampling": {
            "attempts": max(1, min(8, _int(sampling.get("attempts"), 3) or 3)),
            "stable_count": max(1, _int(sampling.get("stable_count"), 2) or 2),
            "request_timeout_ms": max(100, min(10000, _int(sampling.get("request_timeout_ms"), 1200) or 1200)),
            "total_timeout_s": max(1.0, min(30.0, float(_int(sampling.get("total_timeout_s"), 5) or 4.5))),
            "pick": str(sampling.get("pick") or "mode_nonzero").lower(),
        },
    }


# ---------------- 加载 ----------------

_CACHE: dict[str, dict] = {}
_CACHE_AT = 0.0
_CACHE_TTL = 5.0


def external_dir() -> Path:
    """用户/诊断页新增的协议放这里，与内置同 id 时整体覆盖。"""
    from config import config_dir
    path = config_dir() / "device_profiles"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return path


def load(force: bool = False) -> dict[str, dict]:
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    if not force and _CACHE and (now - _CACHE_AT) < _CACHE_TTL:
        return _CACHE

    table: dict[str, dict] = {}
    for pid, raw in profiles_data.BUILTIN.items():
        item = normalize(raw, "builtin", pid)
        if item:
            table[item["id"]] = item

    folder = external_dir()
    try:
        files = sorted(folder.glob("*.json"))
    except Exception:
        files = []
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # 三种写法都收：单个协议对象（诊断页写的就是这种）、id → 协议的映射、
        # 以及协议数组。判据看有没有 request/response —— 映射的顶层键是 id。
        if isinstance(raw, list):
            entries = [(None, r) for r in raw]
        elif isinstance(raw, dict) and any(k in raw for k in ("request", "response", "known_ids")):
            entries = [(raw.get("id"), raw)]
        elif isinstance(raw, dict):
            entries = list(raw.items())
        else:
            continue
        for key, value in entries:
            item = normalize(value, str(path), key or "")
            if not item:
                continue
            if item["enabled"]:
                table[item["id"]] = item
            else:
                table.pop(item["id"], None)

    _CACHE, _CACHE_AT = table, now
    return table


def invalidate() -> None:
    global _CACHE_AT
    _CACHE_AT = 0.0


def choices() -> list[dict]:
    """诊断页下拉用：按品牌分组，带搜索别名。"""
    out = [{"id": "", "label": "自动判断", "vendor": "自动", "keywords": ""}]
    for item in sorted(load().values(), key=lambda p: (p["vendor"], p["label"])):
        out.append({"id": item["id"], "label": item["label"],
                    "vendor": item["vendor"], "keywords": item["keywords"]})
    return out


def _pids(pid: str, wired_pid: str = "") -> list[str]:
    out = []
    for value in (pid, wired_pid):
        value = (value or "").strip().upper()
        if value and value not in out:
            out.append(value)
    return out


def for_ids(vid: str, pid: str, wired_pid: str = "") -> list[dict]:
    """按 VID:PID 找协议。精确 PID 命中排在 VID 通配前面。"""
    vid = (vid or "").strip().upper()
    if not vid:
        return []
    pids = _pids(pid, wired_pid)
    exact, wildcard = [], []
    for item in load().values():
        for known in item["known_ids"]:
            if known["vid"] != vid:
                continue
            if known["pid"] and known["pid"] in pids:
                exact.append(item)
                break
            if not known["pid"] and item not in wildcard:
                wildcard.append(item)
    exact.sort(key=lambda p: p["id"])
    wildcard.sort(key=lambda p: p["id"])
    return exact or wildcard


def by_id(profile_id: str) -> dict | None:
    return load().get((profile_id or "").strip().lower())


# ---------------- 解析 ----------------

def parse_level(level: dict, raw: bytes) -> int | None:
    offset = level["offset"]
    if level["encoding"] == "u16le":
        if len(raw) < offset + 2:
            return None
        value = raw[offset] | (raw[offset + 1] << 8)
    else:
        if len(raw) <= offset:
            return None
        value = raw[offset]
    if level["mask"] is not None:
        value &= level["mask"]
    if value < level["min"] or value > level["max"]:
        return None
    scaled = value * level["scale"] + level["add"]
    return int(max(0.0, min(100.0, round(scaled))))


def parse_report(profile: dict, raw: bytes, wired: bool = False):
    """回包 → (电量, 是否充电)。不是这套协议的回包返回 (None, wired)。"""
    resp = profile["response"]
    if len(raw) < resp["min_length"]:
        return None, wired
    if resp["exact_length"] is not None and len(raw) != resp["exact_length"]:
        return None, wired
    for offset, byte in resp["markers"]:
        if offset >= len(raw) or raw[offset] != byte:
            return None, wired
    # 原始实现里针对具体型号的两条硬判据，属于协议事实，跟着搬
    if profile["id"] == "atk-a87-pro" and raw[4:6] == b"\x00\x00":
        return None, wired
    if profile["id"] == "hyperx-cloud-alpha-wireless" and not raw.startswith(b"\x21\xBB\x0B"):
        return None, wired

    status = resp["status"]
    if status["offset"] is not None:
        if status["offset"] >= len(raw):
            return None, wired
        if raw[status["offset"]] not in status["ok_values"]:
            return None, wired

    level = parse_level(resp["level"], raw)
    if level is None:
        return None, wired

    charge = resp["charging"]
    charging = wired
    if charge["offset"] is not None and charge["offset"] < len(raw):
        value = raw[charge["offset"]]
        if charge["mask"] is not None:
            value &= charge["mask"]
        if charge["when_charging"] is not None:
            charging = wired or value == charge["when_charging"]
        elif charge["nonzero"]:
            charging = wired or value != 0
    return level, charging


def pick_level(values: list[int], how: str) -> int:
    """多次采样里挑一个作为最终读数。

    mode_nonzero：取出现次数最多的值（并列时取小的），抗单次误读；
    last：取最后一次（WOB 那类回包慢的键盘）；
    median：取中位数。
    """
    if not values:
        return 0
    if how == "last":
        return values[-1]
    if how == "median":
        return sorted(values)[len(values) // 2]
    best, best_count = values[0], 0
    for value in values:
        count = values.count(value)
        if count > best_count or (count == best_count and value < best):
            best, best_count = value, count
    return best


# ---------------- 读写 ----------------

def _open(path):
    dev = hid.device()
    dev.open_path(path)
    dev.set_nonblocking(True)
    return dev


def _close(dev) -> None:
    try:
        if dev is not None:
            dev.close()
    except Exception:
        pass


def _drain(dev, limit: int = 6) -> None:
    for _ in range(limit):
        try:
            if not dev.read(64, 1):
                return
        except Exception:
            return


def _pad(payload: bytes, length: int) -> bytes:
    if length <= 0:
        return payload
    if len(payload) >= length:
        return payload[:length]
    return payload + b"\x00" * (length - len(payload))


def _write(dev, payload: bytes, length: int) -> bool:
    """按声明的报文长度写；长度不合时依次退到 32 / 16 / 原样。

    某些接收器的中断 OUT 端点只有 8 字节，写 64 字节会直接报错；
    退一档就能通，比按描述符精确计算更省事，也不会误伤正常的 64 字节设备。
    """
    for size in (length, 32, 16, len(payload)):
        if size <= 0:
            continue
        try:
            if dev.write(_pad(payload, size)):
                return True
        except Exception:
            continue
    return False


def _feature_write(dev, payload: bytes, length: int) -> bool:
    for size in (length, 32, 16, len(payload)):
        if size <= 0:
            continue
        try:
            if dev.send_feature_report(_pad(payload, size)) >= 0:
                return True
        except Exception:
            continue
    return False


def _read_reply(dev, profile: dict, deadline: float, in_len: int) -> bytes | None:
    """在一个请求的时间窗内读回包；开了 read_matching 就只认本协议的回包。"""
    timeout = profile["sampling"]["request_timeout_ms"] / 1000.0
    stop = min(deadline, time.monotonic() + timeout)
    matching = profile["request"]["read_matching"]
    while time.monotonic() < stop:
        try:
            raw = dev.read(in_len, 40)
        except Exception:
            return None
        if not raw:
            continue
        data = bytes(raw)
        if not matching:
            return data
        if parse_report(profile, data)[0] is not None:
            return data
    return None


def _sample(dev, profile: dict, deadline: float) -> bytes | None:
    req = profile["request"]
    out_len = req["out_len"] or _FALLBACK_LEN
    in_len = req["in_len"] or _FALLBACK_LEN
    payload = bytearray(req["payload"])
    if req["report_id"] is not None and payload:
        payload[0] = req["report_id"]
    payload = bytes(payload)

    if req["transport"] == "feature_read":
        report_id = req["report_id"] or 0
        try:
            return bytes(dev.get_feature_report(report_id, in_len) or b"")
        except Exception:
            return None
    if req["transport"] == "feature_write_read":
        report_id = req["report_id"]
        if report_id is None and payload:
            report_id = payload[0]
        if not _feature_write(dev, payload, out_len):
            return None
        time.sleep(0.08)
        try:
            return bytes(dev.get_feature_report(report_id or 0, in_len) or b"")
        except Exception:
            return None
    if not _write(dev, payload, out_len):
        return None
    return _read_reply(dev, profile, deadline, in_len)


def read(profile: dict, paths: list, wired: bool = False) -> dict:
    """按协议读一台设备。paths 是同一只接收器的若干接口，按优先级排好。

    返回 {level, charging, samples, raw, error}。
    """
    result = {"level": None, "charging": False, "samples": [], "raw": b"", "error": ""}
    if hid is None:
        result["error"] = "hidapi 不可用"
        return result
    if not paths:
        result["error"] = "没有匹配的接口"
        return result

    sampling = profile["sampling"]
    deadline = time.monotonic() + sampling["total_timeout_s"]
    want = sampling["stable_count"]

    for path in paths:
        if time.monotonic() >= deadline:
            break
        try:
            dev = _open(path)
        except Exception as exc:
            result["error"] = f"打开失败: {exc}"
            continue
        try:
            _drain(dev)
            samples: list[int] = []
            for _ in range(sampling["attempts"]):
                if time.monotonic() >= deadline:
                    break
                raw = _sample(dev, profile, deadline)
                if not raw:
                    if len(samples) < want:
                        time.sleep(0.05)
                    continue
                result["raw"] = raw
                level, charging = parse_report(profile, raw, wired)
                if level is None:
                    if len(samples) < want:
                        time.sleep(0.05)
                    continue
                samples.append(level)
                result["charging"] = charging
                if len(samples) >= want:
                    break
                time.sleep(0.08)
            if samples:
                nonzero = [v for v in samples if v > 0]
                result["samples"] = samples
                if not nonzero:
                    # 全是 0% 视为休眠：真 0% 的设备已经关机了
                    result["error"] = "设备休眠（应答全为 0）"
                    result["level"] = None
                else:
                    result["level"] = float(pick_level(nonzero, sampling["pick"]))
                    result["error"] = ""
                return result
        finally:
            _close(dev)

    if not result["error"]:
        result["error"] = "没有应答"
    return result


def order_paths(profile: dict, infos: list) -> list:
    """挑接口：先按协议声明的页面/用法过滤，再按接口号排序。

    应答不一定回到写出查询的那一条，所以 page 对上的全部返回，
    让 `read()` 依次试。
    """
    page = profile["match"]["usage_page"]
    usage = profile["match"]["usage"]
    hits, others = [], []
    for info in infos:
        ep_page = info.get("usage_page") or 0
        ep_usage = info.get("usage") or 0
        if page >= 0xFF00:
            if ep_page != page:
                continue
            if usage is not None and ep_usage != usage:
                # 页面相同、用法不同：留着当备选，应答可能落在这一条
                others.append(info)
                continue
            hits.append(info)
        else:
            if ep_page == page and (usage is None or ep_usage == usage):
                hits.append(info)
    hits.sort(key=lambda i: (i.get("interface_number") or 0))
    others.sort(key=lambda i: (i.get("interface_number") or 0))
    return [i.get("path") for i in (hits + others) if i.get("path")]


# ---------------- 共用接收器的型号码 ----------------

# Compx 公版接收器（3554:FA09 这类）把品牌和型号藏在会话 ACK 里：
# 先发这一帧开会话，回包第 9/10 字节就是型号码（大端）。
# 凌豹 K98 = 0x0212(530)、狼蛛 F99 Pro = 0x0158(344)，读法完全相同，
# 不读这一下就只能把凌豹显示成狼蛛。
_SESSION = bytes([0x13, 0x05, 0x01] + [0x00] * 16 + [(0x13 + 0x05 + 0x01) & 0xFF])


def parse_model_code(raw: bytes) -> int | None:
    """ACK 形如 13 05 01 00 0A 03 00 00 00 02 12 01 …；带不带报号前缀都试。"""
    for offset in (0, 1):
        end = offset + 12
        if len(raw) < end:
            continue
        if raw[offset] == 0x13 and raw[offset + 1] == 0x05 and raw[offset + 2] == 0x01:
            return (raw[offset + 9] << 8) | raw[offset + 10]
    return None


def read_model_code(paths: list) -> int | None:
    """只读场景也要写这一帧（设备本来就得先开会话才应答），350ms 内没回就放弃。"""
    if hid is None:
        return None
    for path in paths:
        try:
            dev = _open(path)
        except Exception:
            continue
        try:
            _drain(dev)
            # 部分固件会先推一条电量帧，再试一次就能拿到 ACK
            for _ in range(2):
                try:
                    if not dev.write(_SESSION):
                        break
                except Exception:
                    break
                deadline = time.monotonic() + 0.35
                while time.monotonic() < deadline:
                    try:
                        raw = dev.read(20, 60)
                    except Exception:
                        raw = None
                    if not raw:
                        continue
                    code = parse_model_code(bytes(raw))
                    if code is not None:
                        return code
        finally:
            _close(dev)
    return None


# ---------------- 自动探测 ----------------

def candidates_for(usage_page: int, usage: int, skip: set | None = None,
                   vid_pid: str = "") -> list[dict]:
    """某条厂商页上值得试的协议，按优先级排好。

    顺序：页面 + 用法都对上的 → 同页面别的用法（应答可能落在另一条集合）
    → 只声明了页面的通配协议。同一档里，`known_ids` 就写着这台接收器
    VID:PID 的排最前 —— 同族协议（ATK/VGN/WOB 共用帧）能读到但标签是错的，
    先把"本来就登记过这台设备"的型号试出来，标签才不至于张冠李戴。

    探测与"还剩多少条"共用这一份规则，免得文案承诺的条数和真正能试的
    条数对不上。
    """
    skip = set(skip or ())
    vid, _, pid = (vid_pid or "").upper().partition(":")

    def known_first(item: dict) -> bool:
        if not vid or not pid:
            return False
        for entry in item.get("known_ids") or []:
            if (str(entry.get("vid") or "").upper() == vid
                    and str(entry.get("pid") or "").upper() == pid):
                return True
        return False

    same, other, wildcard = [], [], []
    for item in load().values():
        page = item["match"].get("usage_page") or 0
        if page >= 0xFF00 and page != usage_page:
            continue
        matched = item["match"].get("usage")
        if matched is None:
            wildcard.append(item)
        elif matched == usage:
            same.append(item)
        else:
            other.append(item)
    ordered: list[dict] = []
    for group in (same, other, wildcard):
        ordered.extend(sorted(group, key=lambda p: (not known_first(p), p["id"])))
    return [p for p in ordered if p["id"] not in skip]


def probe(infos: list, usage_page: int, usage: int, stop=None,
          progress=None, skip: set | None = None,
          budget: float = 25.0, vid_pid: str = "") -> dict:
    """协议未知时轮试全部模板（诊断页「自动探测」）。

    命中条件：读到电量后隔 200ms 再读一次，两次相差 ≤8 才算
    稳定命中 —— 只对一次就采纳，很容易把「恰好等于某字节」的随机值当成电量。

    这里多了两处防「转圈」：`budget` 秒到点就返回已经试过哪些（skip 可以让
    下一次接着往后试），单条模板的超时压到 2 秒 —— 全 57 条 × 4.5 秒，
    用户会以为卡死。
    """
    base = list(infos)
    skip = set(skip or ())
    candidates = candidates_for(usage_page, usage, skip, vid_pid)

    started = time.monotonic()
    tried_ids: list[str] = []
    for item in candidates:
        if stop is not None and stop.is_set():
            break
        if time.monotonic() - started > budget:
            break
        tried_ids.append(item["id"])
        if progress is not None:
            try:
                progress(f"正在尝试 {item['vendor']} · {item['label']}"
                         f"（{len(tried_ids)}/{len(candidates)}）…")
            except Exception:
                pass
        # 深拷贝：下面要改 match，不能动缓存里的共享结构
        probe_profile = copy.deepcopy(item)
        probe_profile["match"]["usage_page"] = usage_page
        probe_profile["match"]["usage"] = usage
        # 探测阶段压缩超时：没反应的模板不值得等 4.5 秒
        probe_profile["sampling"]["total_timeout_s"] = min(
            2.0, probe_profile["sampling"]["total_timeout_s"])
        probe_profile["sampling"]["attempts"] = 1
        paths = order_paths(probe_profile, base) or [i.get("path") for i in base if i.get("path")]
        first = read(probe_profile, paths)
        if first["level"] is None:
            continue
        time.sleep(0.2)
        second = read(probe_profile, paths)
        if second["level"] is None:
            continue
        if abs(second["level"] - first["level"]) > 8:
            continue
        return {
            "ok": True,
            "profile": item,
            "level": first["level"],
            "charging": second["charging"],
            "path": paths[0] if paths else "",
            "tried": len(tried_ids),
            "tried_ids": tried_ids,
            "remaining": [p["id"] for p in candidates[len(tried_ids):]],
        }
    remaining = [p["id"] for p in candidates[len(tried_ids):]]
    return {"ok": False, "profile": None, "level": None, "charging": False,
            "tried": len(tried_ids), "tried_ids": tried_ids, "remaining": remaining}


def save_external(profile: dict, vid: str, pid: str, usage_page: int, usage: int,
                  label: str = "") -> Path:
    """把命中的模板固化成外置协议：同一只接收器下次开机直接按它读。"""
    data = {
        "schema_version": 1,
        "id": profile["id"],
        "label": label or profile["label"],
        "vendor": profile["vendor"],
        "keywords": profile["keywords"],
        "notes": (profile["notes"] or "") + f"\n由诊断页适配生成（{vid}:{pid}）。",
        "source": "auto-probe",
        "enabled": True,
        "known_ids": [{"vid": vid.upper(), "pid": pid.upper(), "wired_pid": ""}],
        "match": {"usage_page": f"0x{usage_page:04X}",
                  "usage": f"0x{usage:04X}",
                  "require_pid_hit": True},
        "request": {
            "transport": profile["request"]["transport"],
            "payload_hex": " ".join(f"{b:02X}" for b in profile["request"]["payload"]),
            "out_len": profile["request"]["out_len"],
            "in_len": profile["request"]["in_len"],
            "report_id": profile["request"]["report_id"],
            "read_matching": profile["request"]["read_matching"],
        },
        "response": {
            "min_length": profile["response"]["min_length"],
            "exact_length": profile["response"]["exact_length"],
            "markers": [[o, b] for o, b in profile["response"]["markers"]],
            "status": profile["response"]["status"],
            "level": profile["response"]["level"],
            "charging": profile["response"]["charging"],
        },
        "sampling": profile["sampling"],
    }
    if profile.get("model_code") is not None:
        data["model_code"] = profile["model_code"]
    path = external_dir() / f"{profile['id']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate()
    return path


def device_instance(path) -> str:
    """同一只接收器的分组键：去掉末段集合号。"""
    token = phys_token(path)
    return token.rsplit("&", 1)[0] if "&" in token else token


def unique_bluetooth(infos: list) -> list:
    return [i for i in infos if not is_bluetooth(i.get("path"))]


__all__ = [
    "load", "invalidate", "choices", "for_ids", "by_id", "normalize",
    "read", "probe", "save_external", "order_paths", "parse_report",
    "parse_level", "pick_level", "device_instance", "external_dir",
    "parse_model_code", "read_model_code",
]
