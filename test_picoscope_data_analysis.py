from __future__ import annotations

import argparse
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np


def find_latest_h5_file(search_dir: Path) -> Path:
	"""Return the newest HDF5 file in the provided directory tree."""
	candidates = list(search_dir.rglob("*.h5"))
	if not candidates:
		raise FileNotFoundError(f"No .h5 files found under: {search_dir}")
	return max(candidates, key=lambda p: p.stat().st_mtime)


def read_recording(file_path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
	"""Read time vector and Channel 1 data (A/ch1) from a recording file."""
	with h5py.File(file_path, "r") as f:
		time = np.asarray(f["time"]) if "time" in f else None

		if "channels/A" in f:
			ch1 = np.asarray(f["channels/A"])
			ch1_name = "A"
		elif "channels/ch1" in f:
			ch1 = np.asarray(f["channels/ch1"])
			ch1_name = "ch1"
		else:
			available = list(f.get("channels", {}).keys()) if "channels" in f else []
			raise KeyError(
				"Could not find Channel 1. Expected dataset 'channels/A' or 'channels/ch1'. "
				f"Available channels: {available}"
			)

		if time is None:
			# Fall back to sample index if time vector is missing.
			time = np.arange(ch1.size, dtype=float)

		attrs = {k: f.attrs[k] for k in f.attrs.keys()}
		attrs["channel_name"] = ch1_name

	return time, ch1, attrs


def compute_mean_and_rms(signal: np.ndarray) -> tuple[float, float]:
	"""Compute arithmetic mean and RMS value."""
	signal = np.asarray(signal, dtype=float)
	mean_val = float(np.mean(signal))
	rms_val = float(np.sqrt(np.mean(np.square(signal))))
	return mean_val, rms_val


def make_plot(time: np.ndarray, ch1: np.ndarray, mean_val: float, rms_val: float, source: Path, channel_name: str) -> None:
	"""Plot Channel 1 waveform and annotate mean/RMS."""
	plt.figure(figsize=(11, 5))
	plt.plot(time, ch1, linewidth=1.2, label=f"Channel {channel_name}")
	plt.axhline(mean_val, color="tab:red", linestyle="--", linewidth=1.5, label=f"Mean = {mean_val:.3f} mV")

	plt.title(f"PicoScope Recording Analysis\n{source.name}")
	plt.xlabel("Time")
	plt.ylabel("Voltage (mV)")
	plt.grid(True, alpha=0.3)
	plt.legend(loc="best")

	stats_text = f"Mean: {mean_val:.6f} mV\nRMS:  {rms_val:.6f} mV"
	plt.gca().text(
		0.01,
		0.98,
		stats_text,
		transform=plt.gca().transAxes,
		verticalalignment="top",
		bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "gray"},
	)

	plt.tight_layout()
	plt.show()


def parse_args() -> argparse.Namespace:
	default_data_dir = Path.home() / "Desktop" / "test_data_04" / "27"

	parser = argparse.ArgumentParser(
		description="Analyze data collected by test_picoscope.py and compute Channel 1 mean/RMS."
	)
	parser.add_argument(
		"--file",
		type=Path,
		default=None,
		help="Path to a specific .h5 file. If omitted, the newest file under --data-dir is used.",
	)
	parser.add_argument(
		"--data-dir",
		type=Path,
		default=default_data_dir,
		help=f"Directory to search for .h5 recordings (default: {default_data_dir}).",
	)
	return parser.parse_args()


def main() -> None:
	args = parse_args()

	if args.file is not None:
		h5_file = args.file.expanduser().resolve()
		if not h5_file.exists():
			raise FileNotFoundError(f"File not found: {h5_file}")
	else:
		data_dir = args.data_dir.expanduser().resolve()
		if not data_dir.exists():
			raise FileNotFoundError(
				f"Data directory not found: {data_dir}. Use --file or --data-dir to point to your recording location."
			)
		h5_file = find_latest_h5_file(data_dir)

	time, ch1, attrs = read_recording(h5_file)
	mean_val, rms_val = compute_mean_and_rms(ch1)

	print(f"Analyzing: {h5_file}")
	print(f"Channel used: {attrs.get('channel_name', 'A')}")
	print(f"Channel 1 Mean (mV): {mean_val:.6f}")
	print(f"Channel 1 RMS  (mV): {rms_val:.6f}")

	make_plot(time, ch1, mean_val, rms_val, h5_file, str(attrs.get("channel_name", "A")))


if __name__ == "__main__":
	main()
