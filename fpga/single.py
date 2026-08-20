#!/usr/bin/env python3
"""
Single-peak readout and calibration.

    python single.py raw                     stream the estimate, one line per packet
    python single.py meas --true 5e6         average, report error and ppm
    python single.py sweep --tones 1e6 2e6 5e6 8e6 10e6
                                             step through tones, fit ppm,
                                             print the corrected BIN_MHZ
         Single peak commands:                                    
    python single.py meas --true 68e3 -n 5000
    python single.py sweep --tones 68e3 200e3 1e6 5e6 20e6
    python single.py raw

    python plot_multi.py --peaks 1 --true 68e3 --span 20 --tick 5 --auto
    
The FPGA searches the whole spectrum, so any tone within range is found
without seeding. Move the generator wherever you like.
"""

import argparse
import struct
import sys
import time

import serial

# ---- must match the RTL -------------------------------------------------
PORT    = 'COM3'
BAUD    = 1_000_000
NFFT    = 16384
FS      = 125e6
BIN_MHZ = 244_138_657          # bin width = BIN_MHZ / 128 / 1000
# -------------------------------------------------------------------------

BINHZ = BIN_MHZ / 128.0 / 1000.0
BODY = 1 + 6                    # status + one peak
FRAME_RATE = FS / NFFT


def crc16(data, crc=0xFFFF):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 \
                else (crc << 1) & 0xFFFF
    return crc


def open_port(port, baud):
    s = serial.Serial(port, baud, timeout=2.0)
    s.reset_input_buffer()
    return s


def read_one(ser):
    """One packet -> (freq_hz, bin, offset, mag, ok) or None."""
    if not ser.read_until(b'\xAA\x55').endswith(b'\xAA\x55'):
        return None
    rest = ser.read(BODY + 2)
    if len(rest) < BODY + 2:
        return None
    if ((rest[BODY] << 8) | rest[BODY + 1]) != crc16(rest[:BODY]):
        return None
    b = struct.unpack_from('<H', rest, 1)[0]
    off = struct.unpack_from('<h', rest, 3)[0]
    mag = struct.unpack_from('<H', rest, 5)[0]
    ok = bool(rest[0] & 1)
    return ((b + off / 32768.0) * BINHZ, b, off, mag, ok)


def collect(ser, n, expect=None, tol=None):
    """n valid readings. If expect/tol given, gate gross outliers."""
    out, bad, gated = [], 0, 0
    while len(out) < n:
        r = read_one(ser)
        if r is None:
            bad += 1
            if bad > n * 5:
                raise RuntimeError('too many bad packets')
            continue
        if not r[4]:
            gated += 1
            continue
        if expect is not None and abs(r[0] - expect) > tol:
            gated += 1
            continue
        out.append(r)
    return out, bad, gated


def median(xs):
    s = sorted(xs)
    return s[len(s) // 2]


# ------------------------------------------------------------------- raw ---
def do_raw(port, baud):
    ser = open_port(port, baud)
    print(f'bin width {BINHZ:.4f} Hz   frame rate {FRAME_RATE:.0f}/s')
    print('Ctrl-C to stop\n')
    n_ok = n_bad = 0
    try:
        while True:
            r = read_one(ser)
            if r is None:
                n_bad += 1
                continue
            n_ok += 1
            f, b, off, mag, ok = r
            print(f'bin={b:5d} off={off:+6d} mag={mag:5d} '
                  f'{"ok " if ok else "BAD"} '
                  f'f={f:14.3f} Hz ({f/1e6:.6f} MHz)')
    except KeyboardInterrupt:
        print(f'\n{n_ok} good, {n_bad} bad')
    finally:
        ser.close()


# ------------------------------------------------------------------ meas ---
def do_meas(port, baud, true_hz, n):
    ser = open_port(port, baud)
    print(f'averaging {n} frames at {true_hz/1e6:.6f} MHz '
          f'({n/FRAME_RATE:.2f} s)...\n')
    rows, bad, gated = collect(ser, n, true_hz, 50_000.0)
    ser.close()

    fs = [r[0] for r in rows]
    med = median(fs)
    mean = sum(fs) / len(fs)
    sd = (sum((x - mean) ** 2 for x in fs) / len(fs)) ** 0.5
    bins = sorted({r[1] for r in rows})
    mags = [r[3] for r in rows]

    print(f'  bin(s) seen   {bins[:6]}{" ..." if len(bins) > 6 else ""}')
    print(f'  expected bin  {true_hz/BINHZ:.2f}')
    print(f'  magnitude     {median(mags)}')
    print(f'  packets       {len(rows)} good, {bad} bad, {gated} gated\n')
    print(f'  median        {med:14.3f} Hz')
    print(f'  mean          {mean:14.3f} Hz')
    print(f'  sd            {sd:14.3f} Hz   <- single-frame precision')
    print(f'  error         {med - true_hz:+14.3f} Hz')
    print(f'  ppm           {(med/true_hz - 1)*1e6:+14.4f}')
    return med


# ----------------------------------------------------------------- sweep ---
def do_sweep(port, baud, tones, n):
    """Step through tones by hand, fit a line, print the corrected constant.

    With one peak there is no slope to fit from a single frame, so the lever
    arm comes from stepping the generator instead. Same fit, more steps.
    """
    ser = open_port(port, baud)
    pairs = []
    try:
        for t in tones:
            input(f'\nSet the generator to {t/1e6:.6f} MHz, then press Enter.')
            ser.reset_input_buffer()
            time.sleep(0.3)
            rows, bad, gated = collect(ser, n, t, 200_000.0)
            fs = [r[0] for r in rows]
            med = median(fs)
            mean = sum(fs) / len(fs)
            sd = (sum((x - mean) ** 2 for x in fs) / len(fs)) ** 0.5
            pairs.append((t, med))
            print(f'  measured {med:14.3f} Hz   err {med-t:+9.3f} Hz   '
                  f'{(med/t-1)*1e6:+8.4f} ppm   sd {sd:.3f}')
    except KeyboardInterrupt:
        print('\nstopped early')
    finally:
        ser.close()

    if len(pairs) < 2:
        sys.exit('\nneed at least 2 tones to fit')

    n_ = len(pairs)
    sx = sum(t for t, _ in pairs)
    sy = sum(m for _, m in pairs)
    sxx = sum(t * t for t, _ in pairs)
    sxy = sum(t * m for t, m in pairs)
    slope = (n_ * sxy - sx * sy) / (n_ * sxx - sx * sx)
    icept = (sy - slope * sx) / n_
    res = [m - (slope * t + icept) for t, m in pairs]
    rms = (sum(r * r for r in res) / n_) ** 0.5

    print(f'\n  offset      {(slope-1)*1e6:+.4f} ppm')
    print(f'  intercept   {icept:+.3f} Hz')
    print(f'  residual    {rms:.3f} Hz rms')
    if abs(icept) > 50:
        print('  !! large intercept -- a clock error is purely multiplicative,')
        print('     so this points at a separate constant-offset problem')

    corrected = round(BIN_MHZ / slope)
    print(f'\n  new constant:')
    print(f'    BIN_MHZ = {corrected}          (was {BIN_MHZ}, '
          f'{corrected - BIN_MHZ:+d})')
    print(f'  put that at the top of this file and in readout.py')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--port', default=PORT)
    common.add_argument('--baud', type=int, default=BAUD)

    sub.add_parser('raw', parents=[common])

    m = sub.add_parser('meas', parents=[common])
    m.add_argument('--true', type=float, required=True)
    m.add_argument('-n', type=int, default=2000)

    s = sub.add_parser('sweep', parents=[common])
    s.add_argument('--tones', type=float, nargs='+',
                   default=[1e6, 2e6, 5e6, 10e6, 20e6])
    s.add_argument('-n', type=int, default=2000)

    a = ap.parse_args()
    if a.cmd == 'raw':
        do_raw(a.port, a.baud)
    elif a.cmd == 'meas':
        do_meas(a.port, a.baud, a.true, a.n)
    else:
        do_sweep(a.port, a.baud, a.tones, a.n)