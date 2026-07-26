from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import h5py
import matplotlib.pyplot as plt
import numpy as np


DEFAULT_DATA_DIR = Path.home() / "Desktop" / "test_data_04" / "27" / "0722_testing"
CSV_DIRNAME = "CSV_single"
GRAPH_DIRNAME = "GRAPH_single"

POS_PATTERN = re.compile(r"x(?P<x>m?\d+p\d+)_y(?P<y>m?\d+p\d+)", re.IGNORECASE)

CSV_COLUMNS = [
    "file",
    "position_label",
    "x_pos",
    "y_pos",
    "n_samples",
    "t_start",
    "t_end",
    "mean_A_mV",
    "p2p_A_mV",
    "snr_A_dB",
    "mean_B_mV",
    "p2p_B_mV",
    "snr_B_dB",
]


def _decode_position_token(token: str) -> float:
    token_norm = token.lower()
    if token_norm.startswith("m"):
        token_norm = "-" + token_norm[1:]
    token_norm = token_norm.replace("p", ".")
    return float(token_norm)


def _encode_position_token(value: float) -> str:
    return f"{value:.3f}".replace("-", "m").replace(".", "p")


def extract_position_from_name(file_stem: str) -> Tuple[str, float | None, float | None]:
    match = POS_PATTERN.search(file_stem)
    if not match:
        return "xNA_yNA", None, None

    x_raw = match.group("x")
    y_raw = match.group("y")
    label = f"x{x_raw}_y{y_raw}"
    return label, _decode_position_token(x_raw), _decode_position_token(y_raw)


def find_file_by_position(data_dir: Path, x_pos: float, y_pos: float, tolerance: float = 1e-9) -> Path:
    """Find newest .h5 file in data_dir matching requested x/y position."""
    if not data_dir.exists() or not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    x_token = _encode_position_token(x_pos)
    y_token = _encode_position_token(y_pos)
    pattern = f"picoscope_recording_x{x_token}_y{y_token}_*.h5"
    direct_matches = sorted(data_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    if direct_matches:
        return direct_matches[-1]

    # Fallback for any token formatting differences: parse and compare numerically.
    numeric_matches: List[Path] = []
    for path in data_dir.glob("picoscope_recording_*.h5"):
        _, x_file, y_file = extract_position_from_name(path.stem)
        if x_file is None or y_file is None:
            continue
        if abs(x_file - x_pos) <= tolerance and abs(y_file - y_pos) <= tolerance:
            numeric_matches.append(path)

    if not numeric_matches:
        raise FileNotFoundError(
            f"No file found for x={x_pos:.3f}, y={y_pos:.3f} in {data_dir}"
        )

    numeric_matches.sort(key=lambda p: p.stat().st_mtime)
    return numeric_matches[-1]


def load_h5(path: Path) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, object]]:
    with h5py.File(path, "r") as f:
        if "time" not in f:
            raise ValueError("Missing required dataset: time")
        if "channels" not in f:
            raise ValueError("Missing required group: channels")

        time = np.asarray(f["time"], dtype=np.float64)
        channels = {
            name: np.asarray(f["channels"][name], dtype=np.float64)
            for name in f["channels"].keys()
        }
        meta = {key: f.attrs[key] for key in f.attrs.keys()}

    return time, channels, meta


def channel_stats(signal: np.ndarray) -> Tuple[float, float]:
    if signal.size == 0:
        return float("nan"), float("nan")
    return float(np.mean(signal)), float(np.ptp(signal))


def sine_snr_db(time: np.ndarray, signal: np.ndarray) -> float:
    """Estimate sine-wave SNR (dB) by fitting a single-tone + DC model.

    Model: y(t) = a*sin(wt) + b*cos(wt) + c
    - Frequency is initialized from FFT peak and refined over a small local grid.
    - Signal power is model power; noise power is residual power.
    """
    y = np.asarray(signal, dtype=np.float64)
    t = np.asarray(time, dtype=np.float64)

    n = min(y.size, t.size)
    if n < 8:
        return float("nan")

    y = y[:n]
    t = t[:n]

    # Use relative time to avoid large absolute values degrading conditioning.
    t_rel = t - t[0]
    dt = np.median(np.diff(t_rel)) if n > 1 else 0.0
    if not np.isfinite(dt) or dt <= 0:
        return float("nan")

    y_centered = y - np.mean(y)
    if np.allclose(y_centered, 0.0):
        return float("nan")

    spectrum = np.fft.rfft(y_centered)
    freqs = np.fft.rfftfreq(n, d=dt)
    if freqs.size < 2:
        return float("nan")

    # Ignore DC bin and pick strongest tone.
    peak_idx = int(np.argmax(np.abs(spectrum[1:])) + 1)
    f0 = float(freqs[peak_idx])
    if not np.isfinite(f0) or f0 <= 0:
        return float("nan")

    def _fit_for_freq(freq_hz: float):
        w = 2.0 * np.pi * freq_hz
        s = np.sin(w * t_rel)
        c = np.cos(w * t_rel)
        x = np.column_stack((s, c, np.ones_like(s)))
        coeffs, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
        y_hat = x @ coeffs
        resid = y - y_hat
        signal_power = float(np.mean(np.square(y_hat - np.mean(y_hat))))
        noise_power = float(np.mean(np.square(resid)))
        return signal_power, noise_power

    # Coarse local refinement around FFT peak.
    search = f0 * np.array([0.90, 0.94, 0.98, 1.00, 1.02, 1.06, 1.10], dtype=np.float64)
    best_snr = float("-inf")
    best_signal = 0.0
    best_noise = 0.0
    for f_test in search:
        if f_test <= 0 or not np.isfinite(f_test):
            continue
        signal_power, noise_power = _fit_for_freq(float(f_test))
        if noise_power <= 0:
            continue
        snr = signal_power / noise_power
        if snr > best_snr:
            best_snr = snr
            best_signal = signal_power
            best_noise = noise_power

    if best_noise <= 0 or best_signal <= 0:
        return float("nan")
    return float(10.0 * np.log10(best_signal / best_noise))


def choose_position(meta: Dict[str, object], file_stem: str) -> Tuple[str, float | None, float | None]:
    pos_label, x_name, y_name = extract_position_from_name(file_stem)

    if x_name is not None and y_name is not None:
        return pos_label, x_name, y_name

    x_meta = meta.get("x_pos", None)
    y_meta = meta.get("y_pos", None)
    if x_meta is not None and y_meta is not None:
        x_val = float(x_meta)
        y_val = float(y_meta)
        return f"x{x_val:.3f}_y{y_val:.3f}", x_val, y_val

    return "xNA_yNA", None, None


def save_plot(graph_dir: Path, source_path: Path, position_label: str, time: np.ndarray, channels: Dict[str, np.ndarray]) -> None:
    graph_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(11, 6))

    if "A" in channels:
        n_a = min(time.size, channels["A"].size)
        ax.plot(time[:n_a], channels["A"][:n_a], linewidth=1.2, label="Channel A")

    if "B" in channels:
        n_b = min(time.size, channels["B"].size)
        ax.plot(time[:n_b], channels["B"][:n_b], linewidth=1.2, label="Channel B")

    ax.set_title(f"mV vs Time | {position_label} | {source_path.name}")
    ax.set_xlabel("Time")
    ax.set_ylabel("Voltage (mV)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()

    plot_name = f"plot_{position_label}_{source_path.stem}.png"
    fig.savefig(graph_dir / plot_name, dpi=300)
    plt.close(fig)


def summarize_file(path: Path) -> Dict[str, object]:
    time, channels, meta = load_h5(path)
    position_label, x_pos, y_pos = choose_position(meta, path.stem)

    ch_a = channels.get("A", np.array([], dtype=np.float64))
    ch_b = channels.get("B", np.array([], dtype=np.float64))

    mean_a, p2p_a = channel_stats(ch_a)
    mean_b, p2p_b = channel_stats(ch_b)
    snr_a_db = sine_snr_db(time, ch_a)
    snr_b_db = sine_snr_db(time, ch_b)

    row: Dict[str, object] = {
        "file": path.name,
        "position_label": position_label,
        "x_pos": "" if x_pos is None else x_pos,
        "y_pos": "" if y_pos is None else y_pos,
        "n_samples": int(time.size),
        "t_start": float(time[0]) if time.size else float("nan"),
        "t_end": float(time[-1]) if time.size else float("nan"),
        "mean_A_mV": mean_a,
        "p2p_A_mV": p2p_a,
        "snr_A_dB": snr_a_db,
        "mean_B_mV": mean_b,
        "p2p_B_mV": p2p_b,
        "snr_B_dB": snr_b_db,
    }

    return row


def write_summary_csv(csv_dir: Path, rows: List[Dict[str, object]], position_label: str | None = None) -> Path:
    csv_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if position_label:
        safe_label = re.sub(r"[^A-Za-z0-9_\-]", "_", position_label)
        out_path = csv_dir / f"summary_0427_{safe_label}_{timestamp}.csv"
    else:
        out_path = csv_dir / f"summary_0427_{timestamp}.csv"

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return out_path


def analyze_single(
    x: float,
    y: float,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    tolerance: float = 1e-9,
) -> Dict[str, object]:
    """Analyze the recording at (x, y), save CSV/plot, and return key metrics."""
    resolved_data_dir = Path(data_dir).expanduser().resolve()
    file_path = find_file_by_position(resolved_data_dir, x, y, tolerance=tolerance)

    output_root = file_path.parent
    csv_dir = output_root / CSV_DIRNAME
    graph_dir = output_root / GRAPH_DIRNAME

    row = summarize_file(file_path)
    csv_path = write_summary_csv(csv_dir, [row], position_label=str(row.get("position_label", "xNA_yNA")))

    time, channels, meta = load_h5(file_path)
    position_label, x_pos, y_pos = choose_position(meta, file_path.stem)
    save_plot(graph_dir, file_path, position_label, time, channels)

    return {
        "file": str(file_path),
        "position_label": position_label,
        "x_pos": x_pos,
        "y_pos": y_pos,
        "mean_A_mV": row["mean_A_mV"],
        "mean_B_mV": row["mean_B_mV"],
        "snr_A_dB": row["snr_A_dB"],
        "snr_B_dB": row["snr_B_dB"],
        "summary_csv": str(csv_path),
        "graph_dir": str(graph_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze one PicoScope .h5 file selected by x/y position from a folder."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Folder containing .h5 recordings (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--x-pos",
        type=float,
        required=True,
        help="Requested x position (example: 0.01)",
    )
    parser.add_argument(
        "--y-pos",
        type=float,
        required=True,
        help="Requested y position (example: 0.19)",
    )
    args = parser.parse_args()

    result = analyze_single(x=args.x_pos, y=args.y_pos, data_dir=args.data_dir)

    print(f"Selected by position x={args.x_pos:.3f}, y={args.y_pos:.3f}")
    print(f"Processed file: {result['file']}")
    print(f"Position label: {result['position_label']}")
    print(f"Mean A (mV): {result['mean_A_mV']:.6f}")
    print(f"SNR A (dB): {result['snr_A_dB']:.6f}")
    print(f"Summary CSV: {result['summary_csv']}")
    print(f"Graph folder: {result['graph_dir']}")


if __name__ == "__main__":
    result = analyze_single(x=1, y=2, data_dir=DEFAULT_DATA_DIR)
    mean=result["mean_A_mV"]
    print(mean)
    print(f"Mean A (mV): {result['mean_A_mV']:.6f}")
    print(f"Summary CSV: {result['summary_csv']}")
    # main()
