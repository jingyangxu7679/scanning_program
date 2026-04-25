from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import h5py
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


# Edit this path to your collected H5 folder.
INPUT_FOLDER = Path(r"C:\Users\wong_\Desktop\test_data_new_1")


def load_recording(path: Path) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, object]]:
	"""Load one HDF5 recording produced by test_picoscope.py."""
	with h5py.File(path, "r") as f:
		if "time" not in f:
			raise KeyError("missing dataset: time")
		if "channels" not in f:
			raise KeyError("missing group: channels")

		time = np.asarray(f["time"][:])
		channels = {name: np.asarray(f[f"channels/{name}"][:]) for name in f["channels"].keys()}
		meta = dict(f.attrs)

	return time, channels, meta


def _to_float(value: object, default: float = float("nan")) -> float:
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def _meta_value(meta: Dict[str, object], *keys: str) -> object:
	"""Return the first non-empty metadata value from a list of candidate keys."""
	for key in keys:
		value = meta.get(key, "")
		if value not in ("", None):
			return value
	return ""


def estimate_dt(time: np.ndarray) -> float:
	"""Estimate time step from the median spacing for robustness."""
	if time.size < 2:
		return float("nan")
	diffs = np.diff(time.astype(np.float64))
	diffs = diffs[np.isfinite(diffs)]
	diffs = diffs[diffs > 0]
	if diffs.size == 0:
		return float("nan")
	return float(np.median(diffs))


def dominant_frequency(signal: np.ndarray, dt: float) -> Tuple[float, float]:
	"""Return dominant frequency and its magnitude from single-sided FFT."""
	if signal.size < 2 or not np.isfinite(dt) or dt <= 0:
		return float("nan"), float("nan")

	centered = signal.astype(np.float64) - np.mean(signal)
	fft_vals = np.fft.rfft(centered)
	freqs = np.fft.rfftfreq(centered.size, d=dt)

	if fft_vals.size <= 1:
		return float("nan"), float("nan")

	idx = int(np.argmax(np.abs(fft_vals[1:])) + 1)
	return float(freqs[idx]), float(np.abs(fft_vals[idx]))


def channel_metrics(time: np.ndarray, signal: np.ndarray) -> Dict[str, float]:
	"""Compute summary metrics for one channel."""
	y = signal.astype(np.float64)
	dt = estimate_dt(time)
	fs = 1.0 / dt if np.isfinite(dt) and dt > 0 else float("nan")
	dom_freq, dom_amp = dominant_frequency(y, dt)

	metrics = {
		"n_samples": int(y.size),
		"t_start": _to_float(time[0]) if time.size else float("nan"),
		"t_end": _to_float(time[-1]) if time.size else float("nan"),
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
	}
	return metrics


def analyze_file(path: Path) -> List[Dict[str, object]]:
	"""Analyze one HDF5 file and return one row per channel."""
	time, channels, meta = load_recording(path)
	x_pos = _meta_value(meta, "x_pos", "x", "x_position", "pos_x")
	y_pos = _meta_value(meta, "y_pos", "y", "y_position", "pos_y")

	rows: List[Dict[str, object]] = []
	for channel_name, values in channels.items():
		row: Dict[str, object] = {
			"file": path.name,
			"channel": channel_name,
			"x_pos": x_pos,
			"y_pos": y_pos,
		}
		row.update(channel_metrics(time, values))

		# Preserve common metadata keys from writer code when present.
		for key in ("saved_at", "time_interval", "time_units", "chA_range", "chB_range"):
			row[key] = meta.get(key, "")

		rows.append(row)

	return rows


def find_h5_files(folder: Path, pattern: str, recursive: bool) -> Iterable[Path]:
	if recursive:
		return sorted(folder.rglob(pattern))
	return sorted(folder.glob(pattern))


def write_csv(rows: List[Dict[str, object]], output_path: Path) -> None:
	if not rows:
		return

	output_path.parent.mkdir(parents=True, exist_ok=True)
	fieldnames = list(rows[0].keys())
	with output_path.open("w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(rows)


def _fmt_num(value: object, precision: int = 6) -> str:
	if value is None:
		return "nan"
	try:
		num = float(value)
	except (TypeError, ValueError):
		return str(value)
	if not np.isfinite(num):
		return "nan"
	return f"{num:.{precision}g}"


def build_detailed_report_lines(file_results: List[Tuple[Path, List[Dict[str, object]]]]) -> List[str]:
	"""Build human-readable detailed results grouped by file and channel."""
	lines: List[str] = ["", "Detailed results:"]
	for path, rows in file_results:
		lines.append("")
		lines.append(f"File: {path.name}")
		if not rows:
			lines.append("  No channel data found.")
			continue

		meta_keys = ("saved_at", "time_interval", "time_units", "chA_range", "chB_range", "x_pos", "y_pos")
		meta_parts = []
		first = rows[0]
		for key in meta_keys:
			value = first.get(key, "")
			if value not in ("", None):
				meta_parts.append(f"{key}={value}")
		if meta_parts:
			lines.append("  Meta: " + ", ".join(meta_parts))

		x_pos = first.get("x_pos", "")
		y_pos = first.get("y_pos", "")
		if x_pos not in ("", None) or y_pos not in ("", None):
			x_text = _fmt_num(x_pos) if x_pos not in ("", None) else "?"
			y_text = _fmt_num(y_pos) if y_pos not in ("", None) else "?"
			lines.append(f"  Position: x={x_text}, y={y_text}")

		for row in rows:
			ch = row.get("channel", "?")
			mean_v = _fmt_num(row.get("mean"))
			x_pos_val = row.get("x_pos", "")
			y_pos_val = row.get("y_pos", "")
			x_text = _fmt_num(x_pos_val) if x_pos_val not in ("", None) else "?"
			y_text = _fmt_num(y_pos_val) if y_pos_val not in ("", None) else "?"
			lines.append(
				f"  Channel {ch} | mean voltage = {mean_v} mV | position (units: 0.1 mm): x={x_text}, y={y_text}"
			)
			lines.append(f"  Channel {ch}:")
			lines.append(
				"    "
				f"samples={row.get('n_samples', '')}, "
				f"dt={_fmt_num(row.get('dt'))}, "
				f"sample_rate_hz={_fmt_num(row.get('sample_rate_hz'))}"
			)
			lines.append(
				"    "
				f"mean={_fmt_num(row.get('mean'))}, "
				f"rms={_fmt_num(row.get('rms'))}, "
				f"std={_fmt_num(row.get('std'))}, "
				f"p2p={_fmt_num(row.get('p2p'))}"
			)
			lines.append(
				"    "
				f"min={_fmt_num(row.get('min'))}, "
				f"max={_fmt_num(row.get('max'))}, "
				f"dominant_freq_hz={_fmt_num(row.get('dominant_freq_hz'))}, "
				f"dominant_amp={_fmt_num(row.get('dominant_amp'))}"
			)

	return lines


def print_detailed_report(file_results: List[Tuple[Path, List[Dict[str, object]]]]) -> List[str]:
	"""Print detailed results and return the printed lines for optional file export."""
	lines = build_detailed_report_lines(file_results)
	for line in lines:
		print(line)
	return lines

def plot_recording(path: Path, time: np.ndarray, channels: Dict[str, np.ndarray], meta: Dict[str, object]) -> None:
	"""Plot time-domain waveforms and FFT spectra for all channels in one file."""
	n_channels = len(channels)
	if n_channels == 0:
		return

	fig = plt.figure(figsize=(14, 4 * n_channels))
	pos_suffix = ""
	if "x_pos" in meta or "y_pos" in meta:
		x_txt = _fmt_num(meta.get("x_pos", "")) if meta.get("x_pos", "") != "" else "?"
		y_txt = _fmt_num(meta.get("y_pos", "")) if meta.get("y_pos", "") != "" else "?"
		pos_suffix = f" (x={x_txt}, y={y_txt})"
	fig.suptitle(f"Recording: {path.name}{pos_suffix}", fontsize=14, fontweight="bold")
	gs = GridSpec(n_channels, 2, figure=fig, hspace=0.35, wspace=0.3)

	dt = estimate_dt(time)
	fs = 1.0 / dt if np.isfinite(dt) and dt > 0 else np.nan

	for idx, (ch_name, signal) in enumerate(channels.items()):
		y = signal.astype(np.float64)

		# Time-domain plot
		ax_time = fig.add_subplot(gs[idx, 0])
		ax_time.plot(time, y, linewidth=0.5, color="blue")
		ax_time.set_xlabel("Time")
		ax_time.set_ylabel("Amplitude (mV)")
		ax_time.set_title(f"Channel {ch_name} - Time Domain")
		ax_time.grid(True, alpha=0.3)

		# FFT plot
		ax_fft = fig.add_subplot(gs[idx, 1])
		centered = y - np.mean(y)
		fft_vals = np.fft.rfft(centered)
		if np.isfinite(dt) and dt > 0:
			freqs = np.fft.rfftfreq(centered.size, d=dt)
			ax_fft.semilogy(freqs, np.abs(fft_vals), linewidth=0.5, color="green")
			ax_fft.set_xlabel("Frequency (Hz)")
		else:
			ax_fft.semilogy(np.abs(fft_vals), linewidth=0.5, color="green")
			ax_fft.set_xlabel("FFT Bin")
		ax_fft.set_ylabel("Magnitude")
		ax_fft.set_title(f"Channel {ch_name} - Frequency Spectrum")
		ax_fft.grid(True, alpha=0.3, which="both")

	plt.tight_layout()
	plt.show()

def build_arg_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Analyze collected PicoScope HDF5 recordings.")
	parser.add_argument(
		"--input-folder",
		default=None,
		help="Optional folder containing .h5 files. If omitted, uses INPUT_FOLDER in the script.",
	)
	parser.add_argument("--pattern", default="*.h5", help="Glob pattern for input files (default: *.h5)")
	parser.add_argument("--recursive", action="store_true", help="Search subfolders recursively")
	parser.add_argument(
		"--output",
		default="summary.csv",
		help="Output CSV path (default: summary.csv inside input folder)",
	)
	return parser


def main() -> int:
	parser = build_arg_parser()
	args = parser.parse_args()

	input_folder = (
		Path(args.input_folder).expanduser().resolve()
		if args.input_folder
		else INPUT_FOLDER.expanduser().resolve()
	)
	if not input_folder.exists() or not input_folder.is_dir():
		print(f"Input folder not found: {input_folder}")
		return 1

	files = [p for p in find_h5_files(input_folder, args.pattern, args.recursive) if p.is_file()]
	if not files:
		print(f"No files matched pattern '{args.pattern}' in {input_folder}")
		return 0

	all_rows: List[Dict[str, object]] = []
	failures: List[Tuple[Path, str]] = []
	file_results: List[Tuple[Path, List[Dict[str, object]]]] = []

	for path in files:
		try:
			rows = analyze_file(path)
			file_results.append((path, rows))
			all_rows.extend(rows)
		except Exception as exc:
			failures.append((path, str(exc)))

	plot_warnings: List[str] = []

	# Plot each file
	for path in files:
		try:
			time, channels, meta = load_recording(path)
			#plot_recording(path, time, channels, meta)
		except Exception as exc:
			msg = f"Warning: could not plot {path.name}: {exc}"
			print(msg)
			plot_warnings.append(msg)

	if not all_rows:
		print("No valid channel data found.")
		if failures:
			print("Failed files:")
			for path, reason in failures:
				print(f"  - {path.name}: {reason}")
		return 1

	output_path = Path(args.output)
	if not output_path.is_absolute():
		output_path = input_folder / output_path

	write_csv(all_rows, output_path)
	report_lines = print_detailed_report(file_results)

	analyzed_files_line = f"Analyzed files: {len(files)}"
	channels_analyzed_line = f"Channels analyzed: {len(all_rows)}"
	csv_saved_line = f"Summary saved: {output_path}"
	print(analyzed_files_line)
	print(channels_analyzed_line)
	print(csv_saved_line)

	if failures:
		print("Some files could not be parsed:")
		for path, reason in failures:
			print(f"  - {path.name}: {reason}")

	summary_text_path = input_folder / "summary.txt"
	summary_lines: List[str] = []
	if plot_warnings:
		summary_lines.extend(plot_warnings)
	summary_lines.extend(report_lines)
	summary_lines.append(analyzed_files_line)
	summary_lines.append(channels_analyzed_line)
	summary_lines.append(csv_saved_line)
	if failures:
		summary_lines.append("Some files could not be parsed:")
		for path, reason in failures:
			summary_lines.append(f"  - {path.name}: {reason}")

	summary_text_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
	print(f"Detailed summary text saved: {summary_text_path}")

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
