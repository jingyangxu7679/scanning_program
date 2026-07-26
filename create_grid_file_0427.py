from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np


DEFAULT_INPUT = (
	Path.home()
	/ "Desktop"
	/ "test_data_04"
	/ "27"
	/ "0725_scan2"
	/ "CSV"
	/ "summary_0427_20260726_071654.csv"
)

DEFAULT_OUTPUT_CSV_DIR = Path.home() / "Desktop" / "test_data_04" / "27" / "0725_scan2" / "CSV" / "summary_0427_20260726"
DEFAULT_OUTPUT_GRAPH_DIR = Path.home() / "Desktop" / "test_data_04" / "27" / "0725_scan2" / "Grid_graphs"
DEFAULT_OUTPUT_GRAPH_MEAN_DIR = Path.home() / "Desktop" / "test_data_04" / "27" / "0725_scan2" / "grid_graph_mean"


def _to_float(value: object) -> float:
	if value is None:
		raise ValueError("Missing numeric value")
	if isinstance(value, (float, int, np.floating, np.integer)):
		return float(value)
	text = str(value).strip()
	if not text:
		raise ValueError("Missing numeric value")
	return float(text)


def load_summary_rows(path: Path) -> List[Dict[str, object]]:
	"""Load the analysis summary CSV produced from the 04/27 recordings."""
	with path.open("r", encoding="utf-8", newline="") as f:
		reader = csv.DictReader(f)
		rows: List[Dict[str, object]] = []
		for row in reader:
			if not row:
				continue
			rows.append(row)
	return rows


def resolve_input_csv(input_path: Path) -> Path:
	"""Resolve input to a concrete CSV file path.

	- If a file is provided, use it.
	- If a directory is provided, use the newest summary_0427_*.csv.
	"""
	resolved = input_path.expanduser().resolve()
	if resolved.is_file():
		return resolved
	if resolved.is_dir():
		candidates = sorted(resolved.glob("summary_0427_*.csv"), key=lambda p: p.stat().st_mtime)
		if not candidates:
			raise FileNotFoundError(f"No summary_0427_*.csv found in directory: {resolved}")
		return candidates[-1]
	raise FileNotFoundError(f"Input path does not exist: {resolved}")


def build_grid(rows: List[Dict[str, object]], value_key: str):
	if not rows:
		raise ValueError("No data found in summary CSV.")

	# Average duplicate points at the same (x, y) instead of silently overwriting.
	points_accum: Dict[Tuple[float, float], List[float]] = {}
	for row in rows:
		x_val = _to_float(row.get("x_pos"))
		y_val = _to_float(row.get("y_pos"))
		value = _to_float(row.get(value_key))
		key = (round(x_val, 10), round(y_val, 10))
		points_accum.setdefault(key, []).append(value)

	points: Dict[Tuple[float, float], float] = {
		key: float(np.mean(values)) for key, values in points_accum.items()
	}

	if not points:
		raise ValueError(f"No values found for column {value_key}.")

	x_unique = sorted({x for x, _ in points.keys()})
	y_unique = sorted({y for _, y in points.keys()})
	x_index = {x: idx for idx, x in enumerate(x_unique)}
	y_index = {y: idx for idx, y in enumerate(y_unique)}

	grid = np.full((len(y_unique), len(x_unique)), np.nan, dtype=float)
	for (x_val, y_val), value in points.items():
		grid[y_index[y_val], x_index[x_val]] = value

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


def save_grid_plot(path: Path, x_unique: List[float], y_unique: List[float], grid: np.ndarray, title: str, cbar_label: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	grid_for_plot = grid

	fig, ax = plt.subplots(figsize=(max(8, len(x_unique) * 0.7), max(5, len(y_unique) * 0.7)))
	# origin="upper": y increases from top to bottom on the rendered map.
	image = ax.imshow(grid_for_plot, origin="upper", cmap="viridis", aspect="auto")

	ax.set_xticks(np.arange(len(x_unique)))
	ax.set_yticks(np.arange(len(y_unique)))
	ax.set_xticklabels([f"{x:.3f}" for x in x_unique], rotation=45, ha="right")
	ax.set_yticklabels([f"{y:.3f}" for y in y_unique])

	ax.set_xlabel("X position")
	ax.set_ylabel("Y position")
	ax.set_title(title)

	# Make x increase toward the left side.
	ax.invert_xaxis()

	for row_idx in range(grid_for_plot.shape[0]):
		for col_idx in range(grid_for_plot.shape[1]):
			val = grid_for_plot[row_idx, col_idx]
			text = "--" if np.isnan(val) else f"{val:.3f}"
			ax.text(col_idx, row_idx, text, ha="center", va="center", color="white", fontsize=8)

	cbar = fig.colorbar(image, ax=ax)
	cbar.set_label(cbar_label)

	fig.tight_layout()
	fig.savefig(path, dpi=300)
	plt.close(fig)


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Create peak-to-peak X/Y grids from 04/27 PicoScope summary CSV data."
	)
	parser.add_argument(
		"--input",
		type=Path,
		default=DEFAULT_INPUT,
		help="Input summary CSV file path or a directory containing summary_0427_*.csv files",
	)
	parser.add_argument("--output-csv-dir", type=Path, default=DEFAULT_OUTPUT_CSV_DIR, help="Folder for generated grid CSV files")
	parser.add_argument("--output-graph-dir", type=Path, default=DEFAULT_OUTPUT_GRAPH_DIR, help="Folder for generated plot images")
	parser.add_argument("--output-graph-mean-dir", type=Path, default=DEFAULT_OUTPUT_GRAPH_MEAN_DIR, help="Folder for generated mean plot images")
	parser.add_argument("--output-prefix", type=str, default=None, help="Prefix for generated output files")
	args = parser.parse_args()

	input_csv = resolve_input_csv(args.input)
	output_csv_dir = args.output_csv_dir
	output_graph_dir = args.output_graph_dir
	output_graph_mean_dir = args.output_graph_mean_dir
	input_stem = input_csv.stem
	output_prefix = args.output_prefix or input_stem
	output_csv_a = output_csv_dir / f"{output_prefix}_p2p_A_grid.csv"
	output_csv_b = output_csv_dir / f"{output_prefix}_p2p_B_grid.csv"
	output_png_a = output_graph_dir / f"{output_prefix}_p2p_A_grid.png"
	output_png_b = output_graph_dir / f"{output_prefix}_p2p_B_grid.png"
	output_mean_png_a = output_graph_mean_dir / f"{output_prefix}_mean_A_grid.png"
	output_mean_png_b = output_graph_mean_dir / f"{output_prefix}_mean_B_grid.png"

	rows = load_summary_rows(input_csv)
	x_unique, y_unique, grid_a = build_grid(rows, "p2p_A_mV")
	_, _, grid_b = build_grid(rows, "p2p_B_mV")
	_, _, mean_grid_a = build_grid(rows, "mean_A_mV")
	_, _, mean_grid_b = build_grid(rows, "mean_B_mV")

	if np.allclose(grid_b, 0.0, equal_nan=False):
		print("Warning: Channel B grid is all zeros. This matches your CSV values and is not a plotting bug.")
	if np.allclose(mean_grid_b, 0.0, equal_nan=False):
		print("Warning: Channel B mean grid is all zeros. This matches your CSV values and is not a plotting bug.")

	save_grid_csv(output_csv_a, x_unique, y_unique, grid_a)
	save_grid_csv(output_csv_b, x_unique, y_unique, grid_b)
	save_grid_plot(
		output_png_a,
		x_unique,
		y_unique,
		grid_a,
		title="Channel A Peak-to-Peak Voltage by Spatial Position",
		cbar_label="P2P Voltage A (mV)",
	)
	save_grid_plot(
		output_png_b,
		x_unique,
		y_unique,
		grid_b,
		title="Channel B Peak-to-Peak Voltage by Spatial Position",
		cbar_label="P2P Voltage B (mV)",
	)
	save_grid_plot(
		output_mean_png_a,
		x_unique,
		y_unique,
		mean_grid_a,
		title="Channel A Mean Voltage by Spatial Position",
		cbar_label="Mean Voltage A (mV)",
	)
	save_grid_plot(
		output_mean_png_b,
		x_unique,
		y_unique,
		mean_grid_b,
		title="Channel B Mean Voltage by Spatial Position",
		cbar_label="Mean Voltage B (mV)",
	)

	print(f"Loaded {len(rows)} rows from {input_csv}")
	print(f"Channel A grid CSV written to: {output_csv_a}")
	print(f"Channel B grid CSV written to: {output_csv_b}")
	print(f"Channel A grid image written to: {output_png_a}")
	print(f"Channel B grid image written to: {output_png_b}")
	print(f"Channel A mean grid image written to: {output_mean_png_a}")
	print(f"Channel B mean grid image written to: {output_mean_png_b}")


if __name__ == "__main__":
	main()
