"""
Re-plot the Lorentzian peak-frequency grid graph from peakfrequency.py's
output, with the first four (smallest-x) columns removed.

Reads lorentzian_peak_frequency_grid.csv from the grid_graphs folder inside
scan_dir, drops the first four x columns, and re-plots the grid. Because
imshow derives its color scale (vmin/vmax) from whatever array it is given,
dropping those columns automatically rescales the color mapping to the
remaining data instead of being skewed by the removed columns.
"""

from pathlib import Path
from typing import List, Tuple

import csv
import numpy as np
import matplotlib.pyplot as plt

output_dir = Path.home() / "Desktop" / "Keysight_EXA_N9010A"
scan_dir = output_dir / "0729_test6_UCLA"
grid_dir = scan_dir / "grid_graphs"
processed_dir = grid_dir / "processed_graphs"

input_csv = grid_dir / "lorentzian_peak_frequency_grid.csv"
output_csv = processed_dir / "lorentzian_peak_frequency_grid_cropped.csv"
output_png = processed_dir / "lorentzian_peak_frequency_grid_cropped.png"
output_relative_csv = processed_dir / "lorentzian_peak_frequency_grid_cropped_relative.csv"
output_relative_png = processed_dir / "lorentzian_peak_frequency_grid_cropped_relative.png"

# Number of columns (smallest-x side) to drop from the grid before re-plotting.
COLUMNS_TO_REMOVE = 4


def load_grid_csv(path: Path) -> Tuple[List[float], List[float], np.ndarray]:
    """Load a grid CSV in the "y\\x,x1,x2,..." format written by peakfrequency.py."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        x_unique = [float(x) for x in header[1:]]

        y_unique: List[float] = []
        rows: List[List[float]] = []
        for row in reader:
            if not row:
                continue
            y_unique.append(float(row[0]))
            values = [float("nan") if cell == "" else float(cell) for cell in row[1:]]
            rows.append(values)

    grid = np.array(rows, dtype=float)
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
                row.append("" if np.isnan(val) else f"{val:.6f}")
            writer.writerow(row)


def save_grid_plot(
    path: Path,
    x_unique: List[float],
    y_unique: List[float],
    grid: np.ndarray,
    title: str,
    cbar_label: str,
    value_format: str = "{:.3f}",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    # Extra inches per cell (beyond the 8x5 minimum) so the annotated value
    # in each pixel has enough room and doesn't overlap its neighbors.
    fig, ax = plt.subplots(figsize=(max(8, len(x_unique) * 1.1), max(5, len(y_unique) * 1.1)))
    # origin="upper": y increases from top to bottom on the rendered map.
    # imshow computes vmin/vmax from the array passed in, so the color scale
    # automatically rescales to whatever data remains after cropping.
    cmap = plt.get_cmap("viridis")
    image = ax.imshow(grid, origin="upper", cmap=cmap, aspect="auto")

    ax.set_xticks(np.arange(len(x_unique)))
    ax.set_yticks(np.arange(len(y_unique)))
    ax.set_xticklabels([f"{x:.3f}" for x in x_unique], rotation=45, ha="right")
    ax.set_yticklabels([f"{y:.3f}" for y in y_unique])

    ax.set_xlabel("X position")
    ax.set_ylabel("Y position")
    ax.set_title(title)

    # Make x increase toward the left side (matches create_grid_file_0427.py).
    ax.invert_xaxis()

    # Pick each cell's text color from its own background luminance (instead
    # of a fixed white) so the frequency value stays readable whether the
    # cell color is dark (e.g. near vmin) or light (e.g. near vmax).
    for row_idx in range(grid.shape[0]):
        for col_idx in range(grid.shape[1]):
            val = grid[row_idx, col_idx]
            if np.isnan(val):
                text = "--"
                text_color = "white"
            else:
                text = value_format.format(val)
                r, g, b, _ = cmap(image.norm(val))
                luminance = 0.299 * r + 0.587 * g + 0.114 * b
                text_color = "black" if luminance > 0.55 else "white"
            ax.text(col_idx, row_idx, text, ha="center", va="center", color=text_color, fontsize=6)

    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label(cbar_label)

    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def main():
    if not input_csv.exists():
        print(f"Input grid CSV not found: {input_csv}")
        return

    x_unique, y_unique, grid = load_grid_csv(input_csv)

    if len(x_unique) <= COLUMNS_TO_REMOVE:
        print(
            f"Cannot remove {COLUMNS_TO_REMOVE} columns from a grid with only "
            f"{len(x_unique)} x columns."
        )
        return

    # Drop the first COLUMNS_TO_REMOVE columns (smallest-x side); the color
    # scale of the re-plotted grid automatically rescales to the remaining
    # data since imshow derives vmin/vmax from whatever array it is given.
    x_cropped = x_unique[COLUMNS_TO_REMOVE:]
    grid_cropped = grid[:, COLUMNS_TO_REMOVE:]

    save_grid_csv(output_csv, x_cropped, y_unique, grid_cropped)
    print(f"Saved cropped grid CSV to: {output_csv}")

    save_grid_plot(
        output_png,
        x_cropped,
        y_unique,
        grid_cropped,
        title="Lorentzian Peak Frequency by Spatial Position (Cropped)",
        cbar_label="Lorentzian Peak Frequency (Hz)",
        value_format="{:.1f}",
    )
    print(f"Saved cropped grid plot to: {output_png}")

    # Relative grid: subtract the minimum peak frequency in the (cropped)
    # data set from every pixel, so the map shows each pixel's offset above
    # the lowest peak frequency instead of the absolute frequency.
    min_freq = float(np.nanmin(grid_cropped))
    grid_relative = grid_cropped - min_freq
    print(f"Minimum peak frequency in cropped data set: {min_freq:,.3f} Hz")

    save_grid_csv(output_relative_csv, x_cropped, y_unique, grid_relative)
    print(f"Saved relative grid CSV to: {output_relative_csv}")

    save_grid_plot(
        output_relative_png,
        x_cropped,
        y_unique,
        grid_relative,
        title="Lorentzian Peak Frequency Relative to Minimum (Cropped)",
        cbar_label="Peak Frequency − Minimum (Hz)",
        value_format="{:.1f}",
    )
    print(f"Saved relative grid plot to: {output_relative_png}")


if __name__ == "__main__":
    main()
