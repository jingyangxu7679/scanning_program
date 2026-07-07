from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Tuple

import h5py
import matplotlib.pyplot as plt
import numpy as np


DEFAULT_INPUT = Path(r"C:\Users\wong_\Desktop\test_data_04\27\picoscope_recording_20260624_155554.h5")
DEFAULT_OUTPUT_DIR = Path(r"C:\Users\wong_\Desktop\test_data_04\27")

CSV_COLUMNS = [
	"file",
	"channel",
	"x_pos",
	"y_pos",
	"n_samples",
	"t_start",
	"t_end",
	"dt",
	"sample_rate_hz",
	"mean",
	"std",
	"rms",
	"min",
	"max",
	"p2p",
	"dominant_freq_hz",
	"dominant_amp",
	"saved_at",
	"time_interval",
	"time_units",
	"chA_range",
	"chB_range",
]


def _to_scalar(value):
	if isinstance(value, np.ndarray):
		if value.ndim == 0:
			return value.item()
		return value.tolist()
	return value


def estimate_dt(time: np.ndarray) -> float:
	if time.size < 2:
		return float("nan")
	diffs = np.diff(time.astype(np.float64))
	diffs = diffs[np.isfinite(diffs)]
	diffs = diffs[diffs > 0]
	if diffs.size == 0:
		return float("nan")
	return float(np.median(diffs))


def dominant_frequency(signal: np.ndarray, dt: float) -> Tuple[float, float]:
	if signal.size < 2 or not np.isfinite(dt) or dt <= 0:
		return float("nan"), float("nan")

	centered = signal.astype(np.float64) - np.mean(signal)
	fft_vals = np.fft.rfft(centered)
	freqs = np.fft.rfftfreq(centered.size, d=dt)

	if fft_vals.size <= 1:
		return float("nan"), float("nan")

	idx = int(np.argmax(np.abs(fft_vals[1:])) + 1)
	return float(freqs[idx]), float(np.abs(fft_vals[idx]))


def load_h5(path: Path):
	with h5py.File(path, "r") as f:
		if "time" not in f:
			raise ValueError("Missing required dataset: time")
		if "channels" not in f:
			raise ValueError("Missing required group: channels")

		time = np.asarray(f["time"], dtype=np.float64)

		channels: Dict[str, np.ndarray] = {}
		for name in sorted(f["channels"].keys()):
			channels[name] = np.asarray(f["channels"][name], dtype=np.float64)

		meta = {key: _to_scalar(value) for key, value in f.attrs.items()}

	return time, channels, meta


def compute_rows(file_name: str, time: np.ndarray, channels: Dict[str, np.ndarray], meta: Dict[str, object]):
	dt = estimate_dt(time)
	fs = 1.0 / dt if np.isfinite(dt) and dt > 0 else float("nan")
	t_start = float(time[0]) if time.size else float("nan")
	t_end = float(time[-1]) if time.size else float("nan")

	x_pos = meta.get("x_pos", "")
	y_pos = meta.get("y_pos", "")

	rows: List[Dict[str, object]] = []
	for ch_name, values in channels.items():
		y = values.astype(np.float64)
		dom_freq, dom_amp = dominant_frequency(y, dt)

		row = {
			"file": file_name,
			"channel": ch_name,
			"x_pos": x_pos,
			"y_pos": y_pos,
			"n_samples": int(y.size),
			"t_start": t_start,
			"t_end": t_end,
			"dt": dt,
			"sample_rate_hz": fs,
			"mean": float(np.mean(y)) if y.size else float("nan"),
			"std": float(np.std(y)) if y.size else float("nan"),
			"rms": float(np.sqrt(np.mean(np.square(y)))) if y.size else float("nan"),
			"min": float(np.min(y)) if y.size else float("nan"),
			"max": float(np.max(y)) if y.size else float("nan"),
			"p2p": float(np.ptp(y)) if y.size else float("nan"),
			"dominant_freq_hz": dom_freq,
			"dominant_amp": dom_amp,
			"saved_at": meta.get("saved_at", ""),
			"time_interval": meta.get("time_interval", ""),
			"time_units": meta.get("time_units", ""),
			"chA_range": meta.get("chA_range", ""),
			"chB_range": meta.get("chB_range", ""),
		}
		rows.append(row)

	return rows


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
		writer.writeheader()
		writer.writerows(rows)


def save_trace_plot(path: Path, time: np.ndarray, channels: Dict[str, np.ndarray], meta: Dict[str, object]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)

	fig, ax = plt.subplots(figsize=(11, 6))
	for ch_name, values in channels.items():
		n = min(time.size, values.size)
		ax.plot(time[:n], values[:n], linewidth=1.0, label=f"Channel {ch_name}")

	x_pos = meta.get("x_pos", "?")
	y_pos = meta.get("y_pos", "?")
	ax.set_title(f"Saved Trace | x={x_pos}, y={y_pos}")
	ax.set_xlabel("Time")
	ax.set_ylabel("Voltage")
	ax.grid(True, alpha=0.3)
	ax.legend(loc="best")
	fig.tight_layout()
	fig.savefig(path, dpi=300)
	plt.close(fig)


def main() -> None:
	parser = argparse.ArgumentParser(description="Analyze one PicoScope HDF5 file and export trace PNG + summary CSV.")
	parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input HDF5 file path")
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output folder")
	args = parser.parse_args()

	input_path = args.input
	output_dir = args.output_dir
	stem = input_path.stem

	csv_path = output_dir / f"analysis_{stem}.csv"
	png_path = output_dir / f"trace_{stem}.png"

	time, channels, meta = load_h5(input_path)
	rows = compute_rows(input_path.name, time, channels, meta)

	write_csv(csv_path, rows)
	save_trace_plot(png_path, time, channels, meta)

	print(f"Analyzed: {input_path}")
	print(f"CSV: {csv_path}")
	print(f"PNG: {png_path}")


if __name__ == "__main__":
	main()
