from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np


FPGA_LOG_DIR = Path.home() / "Desktop" / "FPGA_scan_data" / "08_18_test6_frames"
DEFAULT_OUTPUT_GRAPH_DIR = FPGA_LOG_DIR / "Grid_graphs"
DEFAULT_OUTPUT_FREQTIME_DIR = FPGA_LOG_DIR / "frequencyVStime"

# Matches the fpga_data_x{x:.4f}_y{y:.4f}.csv filenames written by Move_2D_FPGA.py
FILENAME_RE = re.compile(r"fpga_data_x([-+]?\d*\.?\d+)_y([-+]?\d*\.?\d+)\.csv$")


def _to_float(value: object) -> float:
    if value is None:
        raise ValueError("Missing numeric value")
    text = str(value).strip()
    if not text:
        raise ValueError("Missing numeric value")
    return float(text)


def parse_position_from_filename(path: Path) -> Tuple[float, float]:
    match = FILENAME_RE.search(path.name)
    if not match:
        raise ValueError(f"Filename does not match fpga_data_x<x>_y<y>.csv pattern: {path.name}")
    return float(match.group(1)), float(match.group(2))


def compute_frequency_stats(path: Path) -> Dict[str, Dict[str, float]]:
    """Read one FPGA log CSV (as written by plot_multi_timed.py) and compute the mean and median of every f{p}_hz column."""
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        freq_cols = [name for name in (reader.fieldnames or []) if name.endswith("_hz")]
        if not freq_cols:
            raise ValueError(f"No *_hz frequency column found in: {path}")
        values: Dict[str, List[float]] = {name: [] for name in freq_cols}
        for row in reader:
            for name in freq_cols:
                value = row.get(name)
                if value in (None, ""):
                    continue
                values[name].append(_to_float(value))

    return {
        name: {
            "mean": float(np.mean(vals)),
            "median": float(np.median(vals)),
            "rms": float(np.sqrt(np.mean(np.square(vals)))),
        }
        for name, vals in values.items()
        if vals
    }


def collect_frequency_stats(input_dir: Path) -> Tuple[Dict[Tuple[float, float], Dict[str, Dict[str, float]]], List[str]]:
    points: Dict[Tuple[float, float], Dict[str, Dict[str, float]]] = {}
    freq_col_names: List[str] = []
    for path in sorted(input_dir.glob("fpga_data_x*_y*.csv")):
        x_val, y_val = parse_position_from_filename(path)
        stats = compute_frequency_stats(path)
        for name in stats:
            if name not in freq_col_names:
                freq_col_names.append(name)
        points[(round(x_val, 10), round(y_val, 10))] = stats

    if not points:
        raise FileNotFoundError(f"No fpga_data_x*_y*.csv files found in: {input_dir}")
    return points, freq_col_names


def load_time_series(path: Path) -> Tuple[List[float], Dict[str, List[float]]]:
    """Read one FPGA log CSV's raw timestamp and f{p}_hz columns in row order."""
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        freq_cols = [name for name in (reader.fieldnames or []) if name.endswith("_hz")]
        timestamps: List[float] = []
        series: Dict[str, List[float]] = {name: [] for name in freq_cols}
        for row in reader:
            ts = row.get("timestamp")
            if ts in (None, ""):
                continue
            timestamps.append(_to_float(ts))
            for name in freq_cols:
                value = row.get(name)
                series[name].append(_to_float(value) if value not in (None, "") else float("nan"))
    return timestamps, series


def save_freq_vs_time_plot(
    path: Path,
    times: List[float],
    freq_values: List[float],
    freq_col: str,
    x_pos: float,
    y_pos: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = times[0] if times else 0.0
    rel_times = [t - t0 for t in times]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(rel_times, freq_values, lw=0.9)
    ax.set_xlabel("time (s)")
    ax.set_ylabel(f"{freq_col} (Hz)")
    ax.set_title(f"{freq_col} vs time at x={x_pos:.4f}, y={y_pos:.4f}")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def generate_freq_vs_time_plots(input_dir: Path, output_dir: Path) -> None:
    for path in sorted(input_dir.glob("fpga_data_x*_y*.csv")):
        x_pos, y_pos = parse_position_from_filename(path)
        times, series = load_time_series(path)
        for freq_col, freq_values in series.items():
            output_png = output_dir / f"freqVsTime_x{x_pos:.4f}_y{y_pos:.4f}_{freq_col}.png"
            save_freq_vs_time_plot(output_png, times, freq_values, freq_col, x_pos, y_pos)


def build_grid(points: Dict[Tuple[float, float], Dict[str, Dict[str, float]]], freq_col: str, stat_key: str):
    x_unique = sorted({x for x, _ in points.keys()})
    y_unique = sorted({y for _, y in points.keys()})
    x_index = {x: idx for idx, x in enumerate(x_unique)}
    y_index = {y: idx for idx, y in enumerate(y_unique)}

    grid = np.full((len(y_unique), len(x_unique)), np.nan, dtype=float)
    for (x_val, y_val), stats in points.items():
        if freq_col in stats:
            grid[y_index[y_val], x_index[x_val]] = stats[freq_col][stat_key]

    return x_unique, y_unique, grid


def save_grid_plot(
    path: Path,
    x_unique: List[float],
    y_unique: List[float],
    grid: np.ndarray,
    title: str,
    cbar_label: str,
    show_values: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(max(8, len(x_unique) * 0.7), max(5, len(y_unique) * 0.7)))
    # origin="upper": y increases from top to bottom on the rendered map.
    image = ax.imshow(grid, origin="upper", cmap="viridis", aspect="auto")

    ax.set_xticks(np.arange(len(x_unique)))
    ax.set_yticks(np.arange(len(y_unique)))
    ax.set_xticklabels([f"{x:.3f}" for x in x_unique], rotation=45, ha="right")
    ax.set_yticklabels([f"{y:.3f}" for y in y_unique])

    ax.set_xlabel("X position")
    ax.set_ylabel("Y position")
    ax.set_title(title)

    # Make x increase toward the left side.
    ax.invert_xaxis()

    if show_values:
        for row_idx in range(grid.shape[0]):
            for col_idx in range(grid.shape[1]):
                val = grid[row_idx, col_idx]
                text = "--" if np.isnan(val) else f"{val:.1f}"
                ax.text(col_idx, row_idx, text, ha="center", va="center", color="white", fontsize=8)

    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label(cbar_label)

    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grid-plot the average FPGA peak frequency of each scan position."
    )
    parser.add_argument("--input-dir", type=Path, default=FPGA_LOG_DIR, help="Folder containing fpga_data_x<x>_y<y>.csv files")
    parser.add_argument("--output-graph-dir", type=Path, default=DEFAULT_OUTPUT_GRAPH_DIR, help="Folder for generated grid graph images")
    parser.add_argument("--output-freqtime-dir", type=Path, default=DEFAULT_OUTPUT_FREQTIME_DIR, help="Folder for generated frequency-vs-time images")
    args = parser.parse_args()

    input_dir = args.input_dir
    output_graph_dir = args.output_graph_dir
    output_freqtime_dir = args.output_freqtime_dir

    points, freq_cols = collect_frequency_stats(input_dir)
    print(f"Loaded {len(points)} position(s) from {input_dir}")

    for freq_col in freq_cols:
        x_unique, y_unique, mean_grid = build_grid(points, freq_col, "mean")
        output_png = output_graph_dir / f"{freq_col}_grid.png"
        save_grid_plot(
            output_png,
            x_unique,
            y_unique,
            mean_grid,
            title=f"Average {freq_col} by Spatial Position",
            cbar_label=f"Average {freq_col} (Hz)",
        )
        print(f"{freq_col} mean grid image written to: {output_png}")

        _, _, median_grid = build_grid(points, freq_col, "median")
        output_median_png = output_graph_dir / f"{freq_col}_median_grid.png"
        save_grid_plot(
            output_median_png,
            x_unique,
            y_unique,
            median_grid,
            title=f"Median {freq_col} by Spatial Position",
            cbar_label=f"Median {freq_col} (Hz)",
        )
        print(f"{freq_col} median grid image written to: {output_median_png}")

        _, _, rms_grid = build_grid(points, freq_col, "rms")
        output_rms_png = output_graph_dir / f"{freq_col}_rms_grid.png"
        save_grid_plot(
            output_rms_png,
            x_unique,
            y_unique,
            rms_grid,
            title=f"RMS {freq_col} by Spatial Position",
            cbar_label=f"RMS {freq_col} (Hz)",
        )
        print(f"{freq_col} rms grid image written to: {output_rms_png}")

    generate_freq_vs_time_plots(input_dir, output_freqtime_dir)
    print(f"Frequency-vs-time images written to: {output_freqtime_dir}")


if __name__ == "__main__":
    main()
