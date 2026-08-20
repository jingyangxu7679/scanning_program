#!/usr/bin/env python3
"""
Capture raw ADC samples from the FPGA and look at them.

    python adc_capture.py grab                       btnc (middle of 5 on Nexys), saves a .npy
    python adc_capture.py grab --out run3.npy
    python adc_capture.py plot run3.npy
    python adc_capture.py plot run3.npy --fmax 300 --zoom-us 200
    python adc_capture.py csv  run3.npy              export to CSV

Captures are saved with a timestamp by default so nothing gets overwritten.
"""

import argparse
import datetime
import os

import numpy as np

# ---- settings -----------------------------------------------------------
PORT   = 'COM3'
BAUD   = 1_000_000
FS     = 125e6
N_SAMP = 131072
FULL_SCALE = 4096          # 12-bit converter, counts peak-to-peak
# -------------------------------------------------------------------------

HDR = b'CAP\xAA\x55'
TRL = b'\x55\xAAEND'


# ------------------------------------------------------------------ grab ---
def do_grab(port, baud, out, n_samp):
    import serial

    if out is None:
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        out = f'adc_{stamp}.npy'

    ser = serial.Serial(port, baud, timeout=30.0)
    ser.reset_input_buffer()
    print(f'{port} @ {baud}   waiting for {n_samp} samples')
    print('press the capture button on the board...')

    buf = ser.read_until(HDR)
    if not buf.endswith(HDR):
        ser.close()
        raise SystemExit('no capture header seen -- did the trigger fire?')

    raw = ser.read(n_samp * 2)
    tail = ser.read(len(TRL))
    ser.close()

    if len(raw) < n_samp * 2:
        raise SystemExit(f'short capture: {len(raw)//2} of {n_samp} samples')
    if tail != TRL:
        print(f'  note: trailer was {tail!r}, expected {TRL!r}')

    s = np.frombuffer(raw, dtype='<i2').astype(float)
    np.save(out, s)
    print(f'\nwrote {out}   ({len(s)} samples, {len(s)/FS*1e3:.2f} ms)')
    summarise(s)
    return out


# --------------------------------------------------------------- summary ---
def summarise(s):
    ac = s - s.mean()
    pp = ac.max() - ac.min()
    print(f'  DC offset   {s.mean():+8.1f} counts')
    print(f'  AC pk-pk    {pp:8.0f} counts = {pp/FULL_SCALE*100:.2f}% of full scale')
    print(f'  AC rms      {ac.std():8.2f} counts')
    print(f'  min / max   {s.min():.0f} / {s.max():.0f}')
    if s.min() <= -2047 or s.max() >= 2046:
        print('  !! clipping at the converter rail -- reduce input level')
    if pp / FULL_SCALE < 0.05:
        print(f'  !! only {pp/FULL_SCALE*100:.2f}% of range in use -- '
              f'~{20*np.log10(FULL_SCALE/max(pp,1)):.0f} dB of SNR available '
              'from more gain')


# ------------------------------------------------------------------ plot ---
def do_plot(path, zoom_us, fmax_khz, out, show):
    import matplotlib
    if not show:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    s_raw = np.load(path)
    s = s_raw - s_raw.mean()
    n = len(s)
    t_ms = np.arange(n) / FS * 1e3

    fig, ax = plt.subplots(3, 1, figsize=(11, 10))

    # whole record
    ax[0].plot(t_ms, s, lw=0.4)
    ax[0].set_xlabel('time (ms)')
    ax[0].set_ylabel('counts')
    ax[0].set_title(f'{os.path.basename(path)}  --  {n} samples, '
                    f'{n/FS*1e3:.2f} ms at {FS/1e6:.0f} MSPS')
    ax[0].grid(alpha=0.3)

    # zoomed, with sample markers so you can see the sampling
    k = min(int(zoom_us * FS / 1e6), n)
    ax[1].plot(np.arange(k) / FS * 1e6, s[:k], lw=0.8, marker='.', ms=2.5)
    ax[1].set_xlabel('time (us)')
    ax[1].set_ylabel('counts')
    ax[1].set_title(f'first {zoom_us:.0f} us')
    ax[1].grid(alpha=0.3)

    # spectrum, for locating the signal
    w = 0.5 * (1 - np.cos(2 * np.pi * np.arange(n) / n))    # periodic Hann
    X = np.abs(np.fft.rfft(s * w))
    binhz = FS / n
    f_khz = np.arange(len(X)) * binhz / 1e3

    m = f_khz <= fmax_khz
    ax[2].semilogy(f_khz[m], np.maximum(X[m], 1e-3), lw=0.7)
    ax[2].set_xlabel('frequency (kHz)')
    ax[2].set_ylabel('magnitude')
    ax[2].set_title(f'spectrum to {fmax_khz:.0f} kHz (Python FFT from raw ADC data quantized to 1.9kHz, not FPGA FFT!) '
                    f'(bin = {binhz:.2f} Hz)')
    ax[2].grid(alpha=0.3, which='both')

    lo = max(int(2e3 / binhz), 2)                # skip DC and its skirt
    hi = int(fmax_khz * 1e3 / binhz)
    if hi > lo:
        kpk = int(np.argmax(X[lo:hi])) + lo
        fpk = kpk * binhz
        ax[2].annotate(f'bin {kpk}\n{fpk/1e3:.3f} kHz',
                       (fpk / 1e3, X[kpk]), fontsize=9,
                       textcoords='offset points', xytext=(12, -12),
                       arrowprops=dict(arrowstyle='->', lw=0.8))
        floor = float(np.median(X[lo:]))
        print(f'strongest peak between 2 kHz and {fmax_khz:.0f} kHz')
        print(f'  bin         {kpk}')
        print(f'  frequency   {fpk:.3f} Hz   ({fpk/1e3:.4f} kHz)')
        print(f'  magnitude   {X[kpk]:.1f}')
        print(f'  above floor {20*np.log10(X[kpk]/max(floor,1e-9)):.1f} dB')
        print()

    summarise(s_raw)

    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f'\nwrote {out}')
    if show:
        plt.show()


# ------------------------------------------------------------------- csv ---
def do_csv(path, out):
    s = np.load(path)
    if out is None:
        out = os.path.splitext(path)[0] + '.csv'
    t = np.arange(len(s)) / FS
    np.savetxt(out, np.column_stack([t, s]), delimiter=',',
               header='time_s,counts', comments='', fmt=['%.12f', '%.0f'])
    print(f'wrote {out}   ({len(s)} rows)')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    g = sub.add_parser('grab')
    g.add_argument('--port', default=PORT)
    g.add_argument('--baud', type=int, default=BAUD)
    g.add_argument('--out', default=None,
                   help='default is a timestamped filename')
    g.add_argument('--samples', type=int, default=N_SAMP)
    g.add_argument('--plot', action='store_true',
                   help='plot straight after capturing')

    p = sub.add_parser('plot')
    p.add_argument('file')
    p.add_argument('--zoom-us', type=float, default=100.0)
    p.add_argument('--fmax', type=float, default=500.0,
                   help='spectrum upper limit, kHz')
    p.add_argument('--out', default=None)
    p.add_argument('--show', action='store_true')

    c = sub.add_parser('csv')
    c.add_argument('file')
    c.add_argument('--out', default=None)

    a = ap.parse_args()
    if a.cmd == 'grab':
        f = do_grab(a.port, a.baud, a.out, a.samples)
        if a.plot:
            do_plot(f, 100.0, 500.0,
                    os.path.splitext(f)[0] + '.png', False)
    elif a.cmd == 'plot':
        out = a.out or (os.path.splitext(a.file)[0] + '.png')
        do_plot(a.file, a.zoom_us, a.fmax, out, a.show)
    else:
        do_csv(a.file, a.out)