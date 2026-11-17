"""Read-only SNTP diagnostics. Positive offset means the reference is ahead."""
import argparse
import ctypes
import json
import socket
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

EPOCH = 2_208_988_800
SCALE = 1 << 32

if sys.platform == "win32":
    precise_filetime = ctypes.WinDLL("kernel32").GetSystemTimePreciseAsFileTime
    precise_filetime.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
    precise_filetime.restype = None

    def host_utc_ns():
        stamp = ctypes.c_uint64()
        precise_filetime(ctypes.byref(stamp))
        return (stamp.value - 116_444_736_000_000_000) * 100
else:
    host_utc_ns = time.time_ns


def sample(server):
    packet = bytearray(48)
    packet[0] = 0x23  # NTP v4 client
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.connect((server, 123))
        address = sock.getpeername()[0]
        wall_send = host_utc_ns()
        mono_send = time.monotonic_ns()
        whole, fractional = divmod(wall_send, 1_000_000_000)
        struct.pack_into("!II", packet, 40, (whole + EPOCH) % SCALE,
                         fractional * SCALE // 1_000_000_000)
        sock.send(packet)
        reply = sock.recv(512)
        mono_receive = time.monotonic_ns()
        wall_receive = host_utc_ns()
    if (len(reply) < 48 or reply[0] >> 6 == 3 or reply[0] & 7 != 4
            or not 1 <= reply[1] <= 15 or reply[24:32] != packet[40:48]):
        raise ValueError("Unsynchronized or unmatched NTP response")
    root_delay, dispersion = struct.unpack_from("!iI", reply, 4)
    remote_receive, remote_send = struct.unpack_from("!QQ", reply, 32)
    if not 0 < remote_receive <= remote_send:
        raise ValueError("Invalid reference timestamps")

    def unix_seconds(stamp):
        return stamp / SCALE - EPOCH

    elapsed = (mono_receive - mono_send) / 1e9
    wall_elapsed = (wall_receive - wall_send) / 1e9
    if abs(elapsed - wall_elapsed) > .005:
        raise ValueError("Host clock changed during measurement")
    t1, t4 = wall_send / 1e9, wall_receive / 1e9
    t2, t3 = unix_seconds(remote_receive), unix_seconds(remote_send)
    if min(abs(t2 - t1), abs(t3 - t4)) > 86400:
        raise ValueError("Reference timestamp out of range")
    rtt = elapsed - (t3 - t2)
    if rtt < 0:
        raise ValueError("Negative corrected round trip")
    offset = ((t2 - t1) + (t3 - t4)) / 2
    precision = 2.0 ** struct.unpack_from("!b", reply, 3)[0]
    upstream_delay = max(root_delay / 65536, 0)
    upstream_dispersion = dispersion / 65536
    # Report an allowance rather than certifying the advertised reference state.
    allowance = (rtt + upstream_delay) / 2 + upstream_dispersion + precision + .005
    return dict(server=server, address=address, host_receipt_utc=datetime.fromtimestamp(t4, timezone.utc).isoformat(),
                stratum=reply[1], precision_ms=precision * 1000, rtt_ms=rtt * 1000,
                offset_ms=offset * 1000, root_delay_ms=upstream_delay * 1000,
                root_dispersion_ms=upstream_dispersion * 1000, uncertainty_allowance_ms=allowance * 1000,
                absolute_error_allowance_ms=(abs(offset) + allowance) * 1000)


def series(server, count):
    result = []
    for _ in range(count):
        try:
            result.append(sample(server))
        except (OSError, ValueError) as exc:
            result.append(dict(server=server, error=str(exc)))
        time.sleep(1)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("servers", nargs="+")
    parser.add_argument("--samples", type=int, default=6, choices=range(1, 21))
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=8) as workers:
        groups = list(workers.map(lambda server: series(server, args.samples), args.servers))
    print(json.dumps({"offset_sign": "reference_minus_host",
                      "host_timestamp_source": "GetSystemTimePreciseAsFileTime" if sys.platform == "win32" else "time_ns",
                      "samples": groups}, indent=2))


if __name__ == "__main__":
    main()
