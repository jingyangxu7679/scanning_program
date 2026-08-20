#!/usr/bin/env python3
"""
Headless multi-peak readout capture: acquires for a fixed duration, then exits.

    python plot_multi_timed.py --peaks 1 --duration 0.5 --log run.csv
    python plot_multi_timed.py --peaks 1 --window 4000 --duration 0.5 --log run.csv

No GUI - unlike plot_multi.py, this exits on its own after --duration seconds
instead of blocking on plt.show(), so it can be called per grid-point from a
scan (e.g. via subprocess) without needing a window to be manually closed.

Serial runs in a background thread so acquisition never throttles the link.
"""

import argparse
import csv
import struct
import threading
import time
from collections import deque

import serial

BIN_MHZ = 244_138_657          # keep in sync with the RTL
BINHZ = BIN_MHZ / 128.0 / 1000.0


def crc16_ccitt(data, crc=0xFFFF):
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 \
                else (crc << 1) & 0xFFFF
    return crc


class Reader(threading.Thread):
    """Drains the serial port continuously, independent of plot rate."""

    def __init__(self, port, baud, n_peaks, window, logfile=None,
                 binhz=BINHZ):
        super().__init__(daemon=True)
        self.binhz = binhz
        self.ser = serial.Serial(port, baud, timeout=2.0)
        self.ser.reset_input_buffer()
        self.n = n_peaks
        self.body = 1 + 6 * n_peaks
        self.freq = [deque(maxlen=window) for _ in range(n_peaks)]
        self.mag = [deque(maxlen=window) for _ in range(n_peaks)]
        self.ok = [True] * n_peaks
        self.n_ok = 0
        self.n_crc = 0
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.running = True
        self.csv = None
        if logfile:
            self.fh = open(logfile, 'w', newline='')
            self.csv = csv.writer(self.fh)
            cols = ['timestamp']
            for p in range(n_peaks):
                cols += [f'f{p}_hz', f'f{p}_mag', f'f{p}_ok']
            self.csv.writerow(cols)

    def run(self):
        while self.running:
            match = self.ser.read_until(b'\xAA\x55')
            if not match.endswith(b'\xAA\x55'):
                continue
            rest = self.ser.read(self.body + 2)
            if len(rest) < self.body + 2:
                continue
            got = (rest[self.body] << 8) | rest[self.body + 1]
            if got != crc16_ccitt(rest[:self.body]):
                self.n_crc += 1
                continue

            status = rest[0]
            fs, ms, oks = [], [], []
            for p in range(self.n):
                o = 1 + 6 * p
                b = struct.unpack_from('<H', rest, o)[0]
                off = struct.unpack_from('<h', rest, o + 2)[0]
                mag = struct.unpack_from('<H', rest, o + 4)[0]
                fs.append((b + off / 32768.0) * self.binhz)
                ms.append(mag)
                oks.append(bool((status >> p) & 1))

            with self.lock:
                self.n_ok += 1
                for p in range(self.n):
                    self.freq[p].append(fs[p])
                    self.mag[p].append(ms[p])
                self.ok = oks

            if self.csv:
                row = [f'{time.time():.6f}']
                for p in range(self.n):
                    row += [f'{fs[p]:.3f}', ms[p], int(oks[p])]
                self.csv.writerow(row)

    def snapshot(self):
        with self.lock:
            return ([list(d) for d in self.freq],
                    [list(d) for d in self.mag],
                    list(self.ok), self.n_ok, self.n_crc)

    def close(self):
        self.running = False
        time.sleep(0.3)
        self.ser.close()
        if self.csv:
            self.fh.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--peaks', type=int, default=3)
    ap.add_argument('--port', default='COM3')
    ap.add_argument('--baud', type=int, default=1_000_000)
    ap.add_argument('--window', type=int, default=2000,
                    help='samples held on screen (~1 s at 1907 pkt/s)')
    ap.add_argument('--log', default=None)
    ap.add_argument('--span', type=float, default=10.0,
                    help='y-axis full range in Hz, centred on the mean')
    ap.add_argument('--tick', type=float, default=1.0,
                    help='y-axis tick spacing in Hz')
    ap.add_argument('--auto', action='store_true',
                    help='autoscale y instead of using a fixed span')
    ap.add_argument('--title', default=None,
                    help='figure title for slides; defaults to a description '
                         'of the tone set')
    ap.add_argument('--bin-mhz', type=int, default=BIN_MHZ,
                    help='override the RTL scale constant for display')
    ap.add_argument('--ppm', type=float, default=0.0,
                    help='additional ppm correction applied to readings')
    ap.add_argument('--true', type=float, nargs='+', default=None,
                    help='expected tone frequencies; plots error vs these')
    ap.add_argument('--duration', type=float, default=1,#specify the duration of acquisition wanted
                    help='seconds to acquire before exiting (headless, no GUI)')
    a = ap.parse_args()

    # effective bin width: overridden constant, then any extra ppm trim
    binhz = (a.bin_mhz / 128.0 / 1000.0) / (1.0 + a.ppm * 1e-6)
    rd = Reader(a.port, a.baud, a.peaks, a.window, a.log, binhz)
    rd.start()
    print(f'reading {a.port} @ {a.baud}, {a.peaks} peaks for {a.duration:.3f}s')
    print(f'BIN_MHZ={a.bin_mhz}  ppm trim={a.ppm:+.4f}  '
          f'-> bin {binhz:.6f} Hz')
    if a.true:
        print(f'expected: {[f"{t/1e6:.6f} MHz" for t in a.true]}')

    # Headless timed capture (no GUI/matplotlib) so the process exits on its
    # own after --duration instead of blocking on plt.show() until a window
    # is manually closed - lets this be called per grid-point from a scan.
    try:
        time.sleep(a.duration)
    finally:
        rd.close()
    print(f'\n{rd.n_ok} good, {rd.n_crc} CRC failures')


if __name__ == '__main__':
    assert crc16_ccitt(b'123456789') == 0x29B1
    main()