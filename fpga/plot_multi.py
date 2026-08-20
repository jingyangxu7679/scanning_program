#!/usr/bin/env python3
"""
Live plot of the multi-peak readout.

    python plot_multi.py --peaks 1
    python plot_multi.py --peaks 1 -window 4000 --log run.csv
    python plot_multi.py --peaks 1 --span 200 --tick 25 --log output.csv
Top panel:    frequency deviation from each peak's running mean, in Hz.
              Deviations rather than absolutes so all peaks share one axis
              and small shifts are actually visible.
Bottom panel: magnitude, which is your per-frame SNR indicator. Watch this
              to set mag_floor and to spot drive dropouts.

python plot_multi.py --peaks 1 --true 68e3 --span 20 --tick 5 --auto

Serial runs in a background thread so the GUI never throttles the link.
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
    a = ap.parse_args()

    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.ticker import MultipleLocator, ScalarFormatter

    # effective bin width: overridden constant, then any extra ppm trim
    binhz = (a.bin_mhz / 128.0 / 1000.0) / (1.0 + a.ppm * 1e-6)
    rd = Reader(a.port, a.baud, a.peaks, a.window, a.log, binhz)
    rd.start()
    print(f'reading {a.port} @ {a.baud}, {a.peaks} peaks')
    print(f'BIN_MHZ={a.bin_mhz}  ppm trim={a.ppm:+.4f}  '
          f'-> bin {binhz:.6f} Hz')
    if a.true:
        print(f'expected: {[f"{t/1e6:.6f} MHz" for t in a.true]}')
    print('close the window to stop\n')

    # periodic console dump -- the plot title is easy to miss, and these are
    # the numbers you need for setting mag_floor
    def console():
        while rd.running:
            time.sleep(1.0)
            f, m, ok, n_ok, n_crc = rd.snapshot()
            if not f[0]:
                continue
            parts = []
            for q in range(a.peaks):
                mean = sum(f[q]) / len(f[q])
                flag = ' ' if ok[q] else '!'
                parts.append(f"{q}:{mean/1e6:10.6f}MHz{flag}m={m[q][-1]:5d}")
            tot = max(n_ok + n_crc, 1)
            print('  '.join(parts) +
                  f"   raw_mag~{m[0][-1]*262144:,}   crc {100.0*n_crc/tot:.2f}%")
    threading.Thread(target=console, daemon=True).start()

    fig, axes = plt.subplots(a.peaks, 1, figsize=(11, 2.4 * a.peaks),
                             sharex=True, squeeze=False)
    axes = [ax[0] for ax in axes]
    lines = []
    for p, ax in enumerate(axes):
        ln, = ax.plot([], [], lw=0.9, color=f'C{p}')
        lines.append(ln)
        ax.set_ylabel(f'peak {p} (Hz)')
        ax.grid(alpha=0.3, which='both')
        if not a.auto:
            ax.yaxis.set_major_locator(MultipleLocator(a.tick))
            fmt = ScalarFormatter(useOffset=True)
            fmt.set_useOffset(True)
            ax.yaxis.set_major_formatter(fmt)
    axes[-1].set_xlabel('time (s)')

    title = a.title or (f'Simultaneous tracking of {a.peaks} resonances '
                        f'(1 MHz fundamental and harmonics)')
    fig.suptitle(title, fontsize=13)

    t_last = [time.time()]
    n_last = [0]

    def update(_):
        freqs, mags, oks, n_ok, n_crc = rd.snapshot()
        if not freqs[0]:
            return lines

        now = time.time()
        dt = now - t_last[0]
        rate = (n_ok - n_last[0]) / dt if dt > 0 else 0
        if dt > 0.5:
            t_last[0] = now
            n_last[0] = n_ok

        span = a.window / 1907.0          # seconds of history on screen
        for p, ax in enumerate(axes):
            y = freqs[p]
            if a.true and p < len(a.true):
                y = [v - a.true[p] for v in y]     # error in Hz
            x = [i * span / max(len(y), 1) for i in range(len(y))]
            lines[p].set_data(x, y)
            ax.set_xlim(0, span)

            m = sum(y) / len(y)
            if a.auto:
                lo, hi = min(y), max(y)
                if hi - lo < 1e-6:        # flat trace: give it a visible band
                    lo, hi = lo - 1.0, hi + 1.0
                pad = (hi - lo) * 0.12
                ax.set_ylim(lo - pad, hi + pad)
            else:
                # fixed window centred on the mean, so the vertical scale
                # stays comparable frame to frame instead of chasing noise
                mid = 0.0 if (a.true and p < len(a.true)) else m
                ax.set_ylim(mid - a.span / 2.0, mid + a.span / 2.0)
            flag = '' if oks[p] else '   INVALID'
            ax.set_ylabel(f'peak {p} (Hz)\n{m/1e6:.6f} MHz{flag}', fontsize=9)

        tot = max(n_ok + n_crc, 1)
        try:
            fig.canvas.manager.set_window_title(
                f'{rate:.0f} pkt/s   crc {100.0*n_crc/tot:.2f}%   n={n_ok}')
        except Exception:
            pass
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        return lines

    ani = FuncAnimation(fig, update, interval=50, blit=False,
                        cache_frame_data=False)
    try:
        plt.show()
    finally:
        rd.close()
        print(f'\n{rd.n_ok} good, {rd.n_crc} CRC failures')


if __name__ == '__main__':
    assert crc16_ccitt(b'123456789') == 0x29B1
    main()