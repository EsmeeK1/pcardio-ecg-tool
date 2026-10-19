"""Probe the PCardio recorder through the 2M BLE USB dongle and log every raw serial frame.

Only sends documented dongle opcodes (S, C, I, T, D) and, inside T, only Core Interface Read, the PIN
write, Stream and Abort. Nothing else is written to the recorder.

Usage (from the project root, with no other app holding the port):
    python scripts/probe_device.py [COM-port] [--stream-seconds 4]
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

BAUD = 460800
DONGLE_NAME = "2M BLE Dongle"
DONGLE_VID_PID = (0x1915, 0x521A)  # Nordic Semiconductor, as seen on the real dongle
PCARDIO_HEX = b"PCardio".hex().upper()  # 5043617264696F
PIN = bytes([0x6C, 0x6F, 0x76, 0x65])
STREAM_ADDR = 0x10000000
ABORT = 0x03  # v5 doc: "Abort Packet (Opcode 3)"; v7 leaves it out
CONNECT_TIMEOUT_S = 30
REPLY_TIMEOUT_S = 2.0

LOG_DIR = Path(__file__).resolve().parent / "probe_logs"


class Probe:
    def __init__(self, port: serial.Serial, log):
        self.port = port
        self.log = log
        self.buf = b""

    def _write_log(self, direction: str, line: bytes) -> None:
        stamp = f"{time.monotonic():.4f}"
        self.log.write(f"{stamp} {direction} {line.decode('ascii', 'replace').rstrip()}\n")
        self.log.flush()

    def send(self, opcode: str, data: bytes = b"") -> None:
        line = b"$" + opcode.encode() + data.hex().upper().encode() + b"\n"
        self._write_log(">>", line)
        self.port.write(line)

    def lines(self, timeout: float):
        """Yield (opcode, data bytes) for every complete line received until `timeout` passes."""
        einde = time.monotonic() + timeout
        while time.monotonic() < einde:
            self.buf += self.port.read(self.port.in_waiting or 1)
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                self._write_log("<<", line)
                start = line.find(b"$")
                if start < 0 or len(line) < start + 2:
                    continue
                try:
                    yield chr(line[start + 1]), bytes.fromhex(line[start + 2:].decode().strip())
                except ValueError:
                    print(f"  unparsable line: {line!r}")

    def status(self) -> bytes | None:
        self.send("S")
        for op, data in self.lines(REPLY_TIMEOUT_S):
            if op == "S":
                return data
        return None

    def core(self, packet: bytes, timeout: float = REPLY_TIMEOUT_S) -> bytes | None:
        """Send a Core packet and reassemble the reply Data packet (02 addr len data) across R lines."""
        self.send("T", packet)
        acc = b""
        for op, data in self.lines(timeout):
            if op != "R":
                print(f"  (other frame during reply: {op} {data.hex()})")
                continue
            acc += data
            if len(acc) >= 7 and len(acc) >= 7 + int.from_bytes(acc[5:7], "little"):
                return acc
        return acc or None


def read_pkt(addr: int, length: int) -> bytes:
    return bytes([0x01]) + struct.pack("<IH", addr, length)


def find_port() -> str:
    ports = list(list_ports.comports())
    for p in ports:
        print(f"  {p.device}: description={p.description!r} product={p.product!r} hwid={p.hwid!r}")
    for p in ports:
        # pyserial on Windows does not expose the bus-reported description, so fall back to VID:PID.
        if DONGLE_NAME in f"{p.description} {p.product} {p.interface}" or (p.vid, p.pid) == DONGLE_VID_PID:
            return p.device
    sys.exit(f"No port with description '{DONGLE_NAME}' found. Pass the COM port as an argument.")


def run(probe: Probe, stream_seconds: float) -> None:
    st = probe.status()
    print(f"status: {st.hex() if st else None}")
    if not st or st[0] != 2:
        probe.send("C", bytes.fromhex(PCARDIO_HEX))
        einde = time.monotonic() + CONNECT_TIMEOUT_S
        while True:
            time.sleep(0.5)
            st = probe.status()
            print(f"status: {st.hex() if st else None}")
            if st and st[0] == 2:
                break
            if time.monotonic() > einde:
                print("Not connected after timeout: wake the recorder (short button press) and retry.")
                probe.send("I")
                return
    probe.send("I")
    for op, data in probe.lines(0.5):
        print(f"after I: {op} {data.hex()}")

    print("PIN write:", (probe.core(bytes([0x02]) + struct.pack("<IH", 128, 4) + PIN, 1.0) or b"").hex())

    info = probe.core(read_pkt(0, 46))
    print("info raw:", info.hex() if info else None)
    if info and len(info) >= 7 + 46:
        d = info[7:]
        dev_id, mac = struct.unpack_from("<QQ", d, 0)
        free, fsize, batt, dstat, err, errts = struct.unpack_from("<IIIIII", d, 20)
        print(
            f"  id={dev_id:016X} mac={mac:012X} fw={'.'.join(map(str, d[16:20]))} free={free} file={fsize} "
            f"battery={batt}% status={dstat:08b} err={err} errts={errts} hw={d[44]} variant={d[45]}"
        )

    cfg = probe.core(read_pkt(276, 68))
    print("sampling config raw:", cfg.hex() if cfg else None)
    if not cfg or len(cfg) < 7 + 68:
        return
    c = cfg[7:]
    count = int.from_bytes(c[:4], "little")
    sensors = [tuple(c[4 + 4 * i:8 + 4 * i]) for i in range(count)]
    print(f"  {count} sensors (id, gain, rate, type): {sensors}")
    size = _packet_size(sensors)
    print(f"  expected data packet size: {size}")
    if size is None:
        return

    probe.send("T", bytes([0x04]) + struct.pack("<IH", STREAM_ADDR, size))
    n_lines = 0
    for op, data in probe.lines(stream_seconds):
        n_lines += 1
    print(f"stream: {n_lines} lines in {stream_seconds}s")

    probe.send("T", bytes([ABORT]))
    rest = sum(1 for _ in probe.lines(1.0))
    print(f"after abort: {rest} more lines")


SIZE_BY_TYPE = {0: 1, 1: 3, 2: 3, 3: 6, 4: 6, 5: 6, 6: 6, 7: 6, 8: 1}
RATES = [1000, 800, 500, 400, 250, 200, 100, 50, 25, 10, 5]


def _packet_size(sensors) -> int | None:
    try:
        return 13 + sum(SIZE_BY_TYPE[t] * RATES[r] // 5 for _, _, r, t in sensors)
    except (KeyError, IndexError):
        print("  unknown type or rate id, not streaming")
        return None


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("port", nargs="?")
    args.add_argument("--stream-seconds", type=float, default=4)
    a = args.parse_args()

    device = a.port or find_port()
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"probe_{datetime.now():%Y%m%d_%H%M%S}.log"
    print(f"port {device}, log {log_path}")
    try:
        port = serial.Serial(device, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0.05, write_timeout=1.0)
    except serial.SerialException as e:
        sys.exit(f"Cannot open {device} (busy?): {e}")
    port.dtr = True
    with port, open(log_path, "w", encoding="ascii") as log:
        probe = Probe(port, log)
        try:
            time.sleep(0.2)
            for _ in probe.lines(0.5):  # drain anything sent on open
                pass
            run(probe, a.stream_seconds)
        finally:
            try:
                probe.send("T", bytes([ABORT]))
                probe.send("D")
                for _ in probe.lines(1.0):
                    pass
            except serial.SerialException:
                pass


if __name__ == "__main__":
    main()
