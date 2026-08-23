from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import matplotlib.pyplot as plt
import numpy as np


FPGA_LOG_DIR = Path.home() / "Desktop" / "FPGA_scan_data" / "08_22_test6_frames_476"
DEFAULT_ARCHIVE_PATH = FPGA_LOG_DIR / "scan_data.npz"
DEFAULT_OUTPUT_GRAPH_DIR = FPGA_LOG_DIR / "Grid_graphs"
DEFAULT_OUTPUT_FREQTIME_DIR = FPGA_LOG_DIR / "frequencyVStime"

# Move_2D_FPGA.py writes one .npz archive per scan, with two entries per pixel:
# "x<x>_y<y>.frames" (structured array with a timestamp field and one or more
# *_hz fields) and "x<x>_y<y>.position" (the [x, y] position as a float pair).
FRAMES_SUFFIX = ".frames"
POSITION_SUFFIX = ".position"


def _iter_archive_entries(archive: np.lib.npyio.NpzFile) -> Iterator[Tuple[float, float, np.ndarray]]:
    """Yield (x_pos, y_pos, frames) for every pixel stored in the scan archive."""
    bases = sorted({name[: -len(FRAMES_SUFFIX)] for name in archive.files if name.endswith(FRAMES_SUFFIX)})
    for base in bases:
        frames = archive[base + FRAMES_SUFFIX]
        position = archive[base + POSITION_SUFFIX]
        yield float(position[0]), float(position[1]), frames


def compute_frequency_stats(frames: np.ndarray) -> Dict[str, Dict[str, float]]:
    """Compute the mean, median and RMS of every *_hz field in one pixel's frame array."""
    freq_cols = [name for name in (frames.dtype.names or ()) if name.endswith("_hz")]
    if not freq_cols:
        raise ValueError("No *_hz frequency field found in frame array")

    stats: Dict[str, Dict[str, float]] = {}
    for name in freq_cols:
        vals = frames[name].astype(float)
        if vals.size == 0:
            continue
        stats[name] = {
            "mean": float(np.mean(vals)),
            "median": float(np.median(vals)),
            "rms": float(np.sqrt(np.mean(np.square(vals)))),
        }
    return stats


def collect_frequency_stats(archive_path: Path) -> Tuple[Dict[Tuple[float, float], Dict[str, Dict[str, float]]], List[str]]:
    points: Dict[Tuple[float, float], Dict[str, Dict[str, float]]] = {}
    freq_col_names: List[str] = []
    with np.load(archive_path) as archive:
        for x_val, y_val, frames in _iter_archive_entries(archive):
            stats = compute_frequency_stats(frames)
            for name in stats:
                if name not in freq_col_names:
                    freq_col_names.append(name)
            points[(round(x_val, 10), round(y_val, 10))] = stats

    if not points:
        raise FileNotFoundError(f"No pixel entries found in: {archive_path}")
    return points, freq_col_names


def load_time_series(frames: np.ndarray) -> Tuple[List[float], Dict[str, List[float]]]:
    """Pull one pixel's raw timestamp and *_hz fields, in frame order, out of its frame array."""
    freq_cols = [name for name in (frames.dtype.names or ()) if name.endswith("_hz")]
    timestamps = frames["timestamp"].astype(float).tolist()
    series = {name: frames[name].astype(float).tolist() for name in freq_cols}
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


def generate_freq_vs_time_plots(archive_path: Path, output_dir: Path) -> None:
    with np.load(archive_path) as archive:
        for x_pos, y_pos, frames in _iter_archive_entries(archive):
            times, series = load_time_series(frames)
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
    parser.add_argument("--archive-path", type=Path, default=DEFAULT_ARCHIVE_PATH, help="Path to the scan_data.npz archive written by Move_2D_FPGA.py")
    parser.add_argument("--output-graph-dir", type=Path, default=DEFAULT_OUTPUT_GRAPH_DIR, help="Folder for generated grid graph images")
    parser.add_argument("--output-freqtime-dir", type=Path, default=DEFAULT_OUTPUT_FREQTIME_DIR, help="Folder for generated frequency-vs-time images")
    args = parser.parse_args()

    archive_path = args.archive_path
    output_graph_dir = args.output_graph_dir
    output_freqtime_dir = args.output_freqtime_dir

    points, freq_cols = collect_frequency_stats(archive_path)
    print(f"Loaded {len(points)} position(s) from {archive_path}")

    mean_outlier_threshold_hz = 100000.0

    for freq_col in freq_cols:
        x_unique, y_unique, mean_grid = build_grid(points, freq_col, "mean")
        # Pixels whose mean frequency exceeds the threshold are blanked out in the mean/RMS grids only.
        outlier_mask = mean_grid > mean_outlier_threshold_hz
        mean_grid[outlier_mask] = np.nan

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
        rms_grid[outlier_mask] = np.nan
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

    generate_freq_vs_time_plots(archive_path, output_freqtime_dir)
    print(f"Frequency-vs-time images written to: {output_freqtime_dir}")


if __name__ == "__main__":
    main()
