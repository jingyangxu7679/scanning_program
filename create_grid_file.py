from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np


DEFAULT_INPUT = (
	Path(__file__).resolve().parent
	/ "analyzed_data_summary"
	/ "position_time_measurement_trial3_20260622.txt"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "grid_files"
AXIS_SCALE = 0.1


LINE_PATTERN = re.compile(
	r"^x=(?P<x>[^,]+),y=(?P<y>[^:]+):"
	r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
	r"(?P<metrics>.*)$"
)


def parse_position_line(line: str) -> Tuple[float, float, Dict[str, float]]:
	"""Parse one line in format:
	x=<x>,y=<y>:YYYY-mm-dd HH:MM:SS:Metric1=<v1>:Metric2=<v2>:...
	"""
	match = LINE_PATTERN.match(line.strip())
	if not match:
		raise ValueError(f"Invalid line format: {line}")

	x_val = float(match.group("x"))
	y_val = float(match.group("y"))

	metrics_raw = match.group("metrics").lstrip(":")
	metrics: Dict[str, float] = {}
	if metrics_raw:
		for item in metrics_raw.split(":"):
			if "=" not in item:
				continue
			key, val = item.split("=", 1)
			key = key.strip()
			val = val.strip()
			if not key:
				continue
			try:
				metrics[key] = float(val)
			except ValueError:
				# Ignore non-numeric values.
				continue
	return x_val, y_val, metrics


def choose_mean_metric(metrics: Dict[str, float]) -> float | None:
	"""Choose a mean-like metric value from parsed metrics."""
	for key, value in metrics.items():
		if "mean" in key.lower():
			return value
	return None


def load_mean_by_position(path: Path) -> Dict[Tuple[float, float], float]:
	"""Load rows and compute average mean voltage for each scaled (x, y)."""
	grouped: Dict[Tuple[float, float], List[float]] = defaultdict(list)

	with path.open("r", encoding="utf-8") as f:
		for raw_line in f:
			line = raw_line.strip()
			if not line:
				continue

			try:
				x_val, y_val, metrics = parse_position_line(line)
			except ValueError:
				continue

			mean_val = choose_mean_metric(metrics)
			if mean_val is None:
				continue
			x_scaled = round(x_val * AXIS_SCALE, 10)
			y_scaled = round(y_val * AXIS_SCALE, 10)
			grouped[(x_scaled, y_scaled)].append(mean_val)

	result: Dict[Tuple[float, float], float] = {}
	for pos, values in grouped.items():
		result[pos] = float(np.mean(values))
	return result


def build_grid(mean_by_position: Dict[Tuple[float, float], float]):
	if not mean_by_position:
		raise ValueError("No mean-voltage data found in input file.")

	x_unique = sorted({x for x, _ in mean_by_position.keys()})
	y_unique = sorted({y for _, y in mean_by_position.keys()})

	x_index = {x: idx for idx, x in enumerate(x_unique)}
	y_index = {y: idx for idx, y in enumerate(y_unique)}

	grid = np.full((len(y_unique), len(x_unique)), np.nan, dtype=float)
	for (x_val, y_val), mean_val in mean_by_position.items():
		grid[y_index[y_val], x_index[x_val]] = mean_val

	return x_unique, y_unique, grid


def save_grid_csv(path: Path, x_unique: List[float], y_unique: List[float], grid: np.ndarray) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)
		writer.writerow(["y\\x", *x_unique])
		for row_idx, y_val in enumerate(y_unique):
			row = [y_val]
			for col_idx in range(len(x_unique)):
				val = grid[row_idx, col_idx]
				row.append("" if np.isnan(val) else f"{val:.9f}")
			writer.writerow(row)


def save_grid_plot(path: Path, x_unique: List[float], y_unique: List[float], grid: np.ndarray) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)

	fig, ax = plt.subplots(figsize=(max(8, len(x_unique) * 0.7), max(5, len(y_unique) * 0.7)))
	image = ax.imshow(grid, origin="lower", cmap="viridis", aspect="auto")

	ax.set_xticks(np.arange(len(x_unique)))
	ax.set_yticks(np.arange(len(y_unique)))
	ax.set_xticklabels([f"{x:.2f}" for x in x_unique], rotation=45, ha="right")
	ax.set_yticklabels([f"{y:.2f}" for y in y_unique])

	ax.set_xlabel("X position (mm)")
	ax.set_ylabel("Y position (mm)")
	ax.set_title("Mean Voltage Grid by X/Y Position")

	for row_idx in range(grid.shape[0]):
		for col_idx in range(grid.shape[1]):
			val = grid[row_idx, col_idx]
			text = "--" if np.isnan(val) else f"{val:.6f}"
			ax.text(col_idx, row_idx, text, ha="center", va="center", color="white", fontsize=8)

	cbar = fig.colorbar(image, ax=ax)
	cbar.set_label("Mean Voltage (V)")

	fig.tight_layout()
	fig.savefig(path, dpi=300)
	plt.close(fig)


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Create a mean-voltage X/Y grid from position-time-measurement text data."
	)
	parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input text file path")
	parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output folder")
	parser.add_argument("--output-png", type=Path, default=None, help="Output heatmap image")
	parser.add_argument("--output-csv", type=Path, default=None, help="Output grid CSV")
	args = parser.parse_args()

	output_dir = args.output_dir
	input_stem = args.input.stem
	default_png = output_dir / f"analysis_{input_stem}.png"
	default_csv = output_dir / f"analysis_{input_stem}.csv"
	output_png = args.output_png or default_png
	output_csv = args.output_csv or default_csv

	mean_by_position = load_mean_by_position(args.input)
	x_unique, y_unique, grid = build_grid(mean_by_position)

	save_grid_csv(output_csv, x_unique, y_unique, grid)
	save_grid_plot(output_png, x_unique, y_unique, grid)

	print(f"Loaded {len(mean_by_position)} unique X/Y positions from {args.input}")
	print(f"Grid CSV written to: {output_csv}")
	print(f"Grid image written to: {output_png}")


if __name__ == "__main__":
	main()
