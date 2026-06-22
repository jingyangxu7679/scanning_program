from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Optional
from datetime import datetime

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


# Edit this path to your collected CSV measurement folder.
INPUT_FOLDER = Path(r"C:\Users\wong_\Desktop\Measurements_by_picoscope")
MOTOR_POS_TIME_FOLDER = Path(r"C:\Users\wong_\Desktop\motor_pos_time")
OUTPUT_FOLDER = Path(__file__).resolve().parent / "analyzed_data_summary"

# Specify exact filenames to analyze (leave empty to analyze all files)
# Example: "measurement_20260618.csv"
input_data_name = "MeasurementLog2026622.csv"
# Example: "motor_pos_time_20260618_160443.csv"
motor_pos_file_name = "motor_pos_time_20260622_133039.csv"

def load_motor_positions(csv_path: Path) -> Tuple[List[datetime], List[float], List[float]]:
	"""Load motor positions from motor_pos_time CSV file.
	Returns: (timestamps, x_positions, y_positions)
	"""
	timestamps = []
	x_positions = []
	y_positions = []
	
	try:
		with open(csv_path, "r", encoding="utf-8-sig") as f:
			reader = csv.DictReader(f)
			if not reader.fieldnames:
				return timestamps, x_positions, y_positions

			# Build a map from normalized header names to actual header names.
			header_map = {name.strip().lower(): name for name in reader.fieldnames if name is not None}
			time_key = header_map.get("time (utc -07:00 yyyy-mm-dd hh:mm:ss)") or header_map.get("timestamp")
			x_key = header_map.get("x_pos")
			y_key = header_map.get("y_pos")

			if not time_key or not x_key or not y_key:
				print(f"Warning: motor position CSV headers not recognized in {csv_path}")
				return timestamps, x_positions, y_positions

			for row in reader:
				try:
					# Parse timestamp in format "2026-06-18 16:04:43"
					time_str = str(row.get(time_key, "")).strip()
					ts = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
					x_pos = float(str(row.get(x_key, "0")).strip())
					y_pos = float(str(row.get(y_key, "0")).strip())
					
					timestamps.append(ts)
					x_positions.append(x_pos)
					y_positions.append(y_pos)
				except (ValueError, KeyError):
					continue
	except Exception as e:
		print(f"Warning: could not load motor positions from {csv_path}: {e}")
	
	return timestamps, x_positions, y_positions


def find_best_motor_csv(h5_path: Path, h5_metadata: Dict) -> Optional[Path]:
	"""Find the best matching motor_pos_time CSV file for an HDF5 file.
	If motor_pos_file_name is set, use that specific file.
	Otherwise tries to match by creation time or uses the latest CSV.
	"""
	# If user specified a motor file, use it
	if motor_pos_file_name:
		csv_path = MOTOR_POS_TIME_FOLDER / motor_pos_file_name
		if csv_path.exists():
			return csv_path
		else:
			print(f"Warning: specified motor file not found: {csv_path}")
			return None
	
	# Otherwise auto-find
	if not MOTOR_POS_TIME_FOLDER.exists():
		return None
	
	csv_files = sorted(MOTOR_POS_TIME_FOLDER.glob("motor_pos_time_*.csv"))
	if not csv_files:
		return None
	
	# Try to extract timestamp from HDF5 metadata
	saved_at = h5_metadata.get("saved_at", "")
	if saved_at:
		try:
			h5_time = datetime.fromisoformat(str(saved_at))
			# Find CSV closest in time to h5 file
			best_csv = min(csv_files, 
						   key=lambda f: abs((f.stat().st_mtime - h5_time.timestamp())))
			return best_csv
		except:
			pass
	
	# Fall back to latest CSV
	return csv_files[-1]


def match_position_to_timestamp(ts: datetime, motor_timestamps: List[datetime], 
								 x_positions: List[float], y_positions: List[float]) -> Tuple[Optional[float], Optional[float]]:
	"""Find motor position closest to given timestamp.
	Returns: (x_pos, y_pos) or (None, None) if no match found.
	"""
	if not motor_timestamps:
		return None, None
	
	# Find closest timestamp
	min_diff = float('inf')
	closest_idx = None
	
	for i, motor_ts in enumerate(motor_timestamps):
		diff = abs((ts - motor_ts).total_seconds())
		if diff < min_diff:
			min_diff = diff
			closest_idx = i
	
	# Only match if within 2 seconds tolerance
	if closest_idx is not None and min_diff <= 2.0:
		return x_positions[closest_idx], y_positions[closest_idx]
	
	return None, None


def get_absolute_time_from_recording(time_array: np.ndarray, h5_metadata: Dict) -> Optional[List[datetime]]:
	"""Convert HDF5 time array to absolute timestamps.
	Assumes time_array is seconds since recording start.
	Uses 'saved_at' metadata if available.
	"""
	saved_at = h5_metadata.get("saved_at", "")
	if not saved_at:
		return None
	
	try:
		start_time = datetime.fromisoformat(str(saved_at))
		# Convert time array (seconds) to absolute datetimes
		absolute_times = [datetime.fromtimestamp(start_time.timestamp() + t) 
						  for t in time_array]
		return absolute_times
	except:
		return None


def load_measurement_csv(csv_path: Path) -> Tuple[List[datetime], Dict[str, np.ndarray], Dict[str, object]]:
	"""Load CSV measurement file from Measurements_by_picoscope folder.
	Supports time headers like "Timestamp" or "Time (UTC -07:00 yyyy-MM-dd HH:mm:ss)".
	All non-time columns are treated as measurement variables.
	Returns: (timestamps, channels_dict, metadata)
	"""
	timestamps = []
	channels = {}
	meta = {}
	
	try:
		with open(csv_path, "r", encoding="utf-8-sig") as f:
			reader = csv.DictReader(f)
			if not reader.fieldnames:
				raise KeyError("CSV file is empty or has no headers")

			# Detect the time column name from common patterns.
			time_col = None
			for col in reader.fieldnames:
				normalized = col.strip().lower()
				if normalized == "timestamp" or normalized.startswith("time"):
					time_col = col
					break
			if time_col is None:
				raise KeyError("Could not find a time column in measurement CSV")
			
			# Initialize channels dict from fieldnames (skip detected time column)
			for col in reader.fieldnames:
				if col != time_col:
					channels[col] = []
			
			for row in reader:
				try:
					# Parse timestamp
					time_str = row.get(time_col, "").strip()
					if not time_str:
						continue
					ts = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
					timestamps.append(ts)
					
					# Parse channel values
					for col in channels.keys():
						try:
							val = float(row.get(col, "nan"))
							channels[col].append(val)
						except ValueError:
							channels[col].append(np.nan)
				except (ValueError, KeyError):
					continue
		
		# Convert lists to numpy arrays
		for col in channels:
			channels[col] = np.array(channels[col])
		
		meta["file_path"] = str(csv_path)
		meta["num_samples"] = len(timestamps)
		
	except Exception as e:
		print(f"Warning: could not load CSV from {csv_path}: {e}")
		raise
	
	return timestamps, channels, meta


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
	"""Analyze one CSV measurement file and return one row per channel, with positions from motor_pos_time CSV."""
	timestamps, channels, meta = load_measurement_csv(path)
	
	# Try to load motor positions from CSV
	motor_csv = find_best_motor_csv(path, meta)
	motor_x_pos = None
	motor_y_pos = None
	
	if motor_csv and timestamps:
		motor_timestamps, motor_x_positions, motor_y_positions = load_motor_positions(motor_csv)
		
		if motor_timestamps:
			# Use the first measurement timestamp to find motor position
			first_time = timestamps[0]
			motor_x_pos, motor_y_pos = match_position_to_timestamp(
				first_time, motor_timestamps, motor_x_positions, motor_y_positions
			)

	# Compute time deltas for sample rate
	dt = float("nan")
	if len(timestamps) >= 2:
		time_diffs = [(timestamps[i+1] - timestamps[i]).total_seconds() for i in range(len(timestamps)-1)]
		time_diffs = [d for d in time_diffs if d > 0]
		if time_diffs:
			dt = float(np.median(time_diffs))

	rows: List[Dict[str, object]] = []
	for channel_name, values in channels.items():
		row: Dict[str, object] = {
			"file": path.name,
			"channel": channel_name,
			"x_pos": motor_x_pos if motor_x_pos is not None else "",
			"y_pos": motor_y_pos if motor_y_pos is not None else "",
		}
		
		# Calculate metrics for this channel
		y = values.astype(np.float64)
		fs = 1.0 / dt if np.isfinite(dt) and dt > 0 else float("nan")
		dom_freq, dom_amp = dominant_frequency(y, dt)
		
		metrics = {
			"n_samples": int(y.size),
			"t_start": timestamps[0].isoformat() if timestamps else "",
			"t_end": timestamps[-1].isoformat() if timestamps else "",
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
		
		row.update(metrics)
		rows.append(row)

	return rows


def find_h5_files(folder: Path, pattern: str, recursive: bool) -> Iterable[Path]:
	"""Find CSV measurement files in folder."""
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


def write_position_time_measurements(files: List[Path], output_path: Path) -> None:
	"""Write mapped samples as position:time:measurement1:measurement2:...

	Format per line:
	x=<x>,y=<y>:<timestamp>:<measurement1=value1>:<measurement2=value2>:...
	Iterates through each motor position and finds matching measurement data.
	"""
	output_path.parent.mkdir(parents=True, exist_ok=True)
	lines: List[str] = []

	for path in files:
		try:
			timestamps, channels, meta = load_measurement_csv(path)
		except Exception:
			continue

		if not timestamps or not channels:
			continue

		motor_csv = find_best_motor_csv(path, meta)
		motor_timestamps: List[datetime] = []
		motor_x_positions: List[float] = []
		motor_y_positions: List[float] = []
		if motor_csv:
			motor_timestamps, motor_x_positions, motor_y_positions = load_motor_positions(motor_csv)

		if not motor_timestamps:
			continue

		channel_names = list(channels.keys())

		# Iterate through each motor position
		for pos_idx in range(len(motor_timestamps)):
			motor_ts = motor_timestamps[pos_idx]
			x_val = motor_x_positions[pos_idx]
			y_val = motor_y_positions[pos_idx]
			ts_str = motor_ts.strftime("%Y-%m-%d %H:%M:%S")

			# Find matching measurement data for this motor position
			measurement_values: List[str] = []
			for ch in channel_names:
				values = channels[ch]
				# Find closest measurement timestamp to motor timestamp
				closest_idx = None
				closest_diff = float('inf')
				for m_idx, m_ts in enumerate(timestamps):
					diff = abs((motor_ts - m_ts).total_seconds())
					if diff < closest_diff and diff <= 2.0:
						closest_diff = diff
						closest_idx = m_idx

				if closest_idx is not None and closest_idx < len(values):
					measurement_values.append(f"{ch}={values[closest_idx]}")
				else:
					measurement_values.append(f"{ch}=nan")

			# Create one line per motor position with all measurements
			line = f"x={x_val},y={y_val}:{ts_str}:" + ":".join(measurement_values)
			lines.append(line)

	output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


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
	parser.add_argument("--pattern", default="*.csv", help="Glob pattern for input files (default: *.csv)")
	parser.add_argument("--recursive", action="store_true", help="Search subfolders recursively")
	parser.add_argument(
		"--output",
		default="summary.csv",
		help="Base output CSV filename (date will be appended in analyzed_data_summary)",
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

	# If user specified a specific file, analyze only that file
	if input_data_name:
		files = [input_folder / input_data_name]
		if not files[0].exists():
			print(f"Specified input file not found: {files[0]}")
			return 1
		print(f"Analyzing specific file: {files[0]}")
	else:
		# Analyze all matching files in folder
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
			timestamps, channels, meta = load_measurement_csv(path)
			#plot_recording(path, timestamps, channels, meta)
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

	OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
	date_suffix = datetime.now().strftime("%Y%m%d")
	output_name = Path(args.output).name
	output_stem = Path(output_name).stem
	output_suffix = Path(output_name).suffix or ".csv"
	output_path = OUTPUT_FOLDER / f"{output_stem}_{date_suffix}{output_suffix}"
	ptm_output_path = OUTPUT_FOLDER / f"position_time_measurement_trial1_{date_suffix}.txt"

	write_csv(all_rows, output_path)
	write_position_time_measurements(files, ptm_output_path)
	report_lines = print_detailed_report(file_results)

	analyzed_files_line = f"Analyzed files: {len(files)}"
	channels_analyzed_line = f"Channels analyzed: {len(all_rows)}"
	csv_saved_line = f"Summary saved: {output_path}"
	ptm_saved_line = f"Position-time-measurement saved: {ptm_output_path}"
	print(analyzed_files_line)
	print(channels_analyzed_line)
	print(csv_saved_line)
	print(ptm_saved_line)

	if failures:
		print("Some files could not be parsed:")
		for path, reason in failures:
			print(f"  - {path.name}: {reason}")

	summary_text_path = OUTPUT_FOLDER / f"summary_{date_suffix}.txt"
	summary_lines: List[str] = []
	if plot_warnings:
		summary_lines.extend(plot_warnings)
	summary_lines.extend(report_lines)
	summary_lines.append(analyzed_files_line)
	summary_lines.append(channels_analyzed_line)
	summary_lines.append(csv_saved_line)
	summary_lines.append(ptm_saved_line)
	if failures:
		summary_lines.append("Some files could not be parsed:")
		for path, reason in failures:
			summary_lines.append(f"  - {path.name}: {reason}")

	summary_text_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
	print(f"Detailed summary text saved: {summary_text_path}")

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
