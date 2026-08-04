"""
Analyze peak frequencies from Keysight EXA N9010A trace CSV files.

Scans output_dir for CSV files with "frequency_hz,amplitude" columns
(as saved by testsaveTrace_keysight.py), finds the peak (maximum amplitude)
in each trace, fits a Lorentzian around the peak (saving a raw-data + fit
plot with residual error bars to a "Lorentzian" subfolder of scan_dir),
writes a summary CSV of x/y position, peak frequency, and peak power per
file, writes the full Lorentzian fit parameters (including FWHM linewidth
and area) to a separate CSV, and (for files whose x/y position could be
parsed from the filename) builds X/Y grid CSVs and grid plots of peak
frequency, peak power, Lorentzian peak frequency/power, and Lorentzian
linewidth/area, in the same style as create_grid_file_0427.py.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import csv
import re

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

# Number of points to include on each side of the detected peak when fitting
# the Lorentzian (keeps the fit local to the resonance instead of the whole,
# mostly-noise spectrum).
LORENTZIAN_FIT_WINDOW_POINTS = 200

output_dir = Path.home() / "Desktop" / "Keysight_EXA_N9010A"
scan_dir = output_dir / "0731_test1_UCLA"
summary_file = output_dir / "Analysis" / "peak_frequency_summary.csv"
summary_file.parent.mkdir(parents=True, exist_ok=True)
grid_dir = scan_dir / "grid_graphs"
grid_dir.mkdir(parents=True, exist_ok=True)
lorentzian_dir = scan_dir / "Lorentzian"
lorentzian_dir.mkdir(parents=True, exist_ok=True)

# Matches the "..._x{value}_y{value}_..." pattern used by testsaveTrace_keysight.py
# (e.g. "ONtrace_data_x2.2000_y2.2300_20260729_200401.csv").
_POSITION_PATTERN = re.compile(r"x(-?\d+(?:\.\d+)?)_y(-?\d+(?:\.\d+)?)")


def load_trace(csv_path: Path):
    """Load frequency (Hz) and amplitude arrays from a trace CSV file."""
    frequencies = []
    amplitudes = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return np.array([]), np.array([])

        header_map = {name.strip().lower(): name for name in reader.fieldnames if name is not None}
        freq_key = header_map.get("frequency_hz")
        amp_key = header_map.get("amplitude")
        if not freq_key or not amp_key:
            print(f"  Warning: unrecognized headers in {csv_path.name}, skipping")
            return np.array([]), np.array([])

        for row in reader:
            try:
                frequencies.append(float(row[freq_key]))
                amplitudes.append(float(row[amp_key]))
            except (ValueError, KeyError):
                continue

    return np.array(frequencies), np.array(amplitudes)


def find_peak(frequencies: np.ndarray, amplitudes: np.ndarray):
    """Return (peak_frequency, peak_amplitude) for the maximum amplitude point."""
    peak_index = int(np.argmax(amplitudes))
    return frequencies[peak_index], amplitudes[peak_index]


def lorentzian(f, amplitude, center, gamma, offset):
    """Lorentzian line shape: amplitude / (1 + ((f - center) / gamma) ** 2) + offset."""
    return amplitude / (1.0 + ((f - center) / gamma) ** 2) + offset


def fit_lorentzian(
    frequencies: np.ndarray,
    amplitudes: np.ndarray,
    peak_freq: float,
    peak_amp: float,
    window_points: int = LORENTZIAN_FIT_WINDOW_POINTS,
):
    """Fit a Lorentzian around the detected peak.

    Returns a dict with keys "amplitude", "center", "gamma", "offset",
    "peak_amplitude", "f_window", "a_window", "fitted_curve", or None if
    there isn't enough data or the fit fails to converge.
    """
    peak_index = int(np.argmin(np.abs(frequencies - peak_freq)))
    lo = max(0, peak_index - window_points)
    hi = min(len(frequencies), peak_index + window_points + 1)
    f_window = frequencies[lo:hi]
    a_window = amplitudes[lo:hi]

    if len(f_window) < 4:
        return None

    offset_guess = float(np.median(a_window))
    amplitude_guess = float(peak_amp - offset_guess)
    freq_span = float(f_window[-1] - f_window[0]) if len(f_window) > 1 else 1.0
    gamma_guess = max(freq_span / 10.0, 1e-6)

    p0 = [amplitude_guess, peak_freq, gamma_guess, offset_guess]

    try:
        popt, _ = curve_fit(lorentzian, f_window, a_window, p0=p0, maxfev=10000)
    except (RuntimeError, ValueError):
        return None

    amplitude_fit, center_fit, gamma_fit, offset_fit = popt
    gamma_fit = abs(gamma_fit)
    peak_amp_fit = amplitude_fit + offset_fit
    fitted_curve = lorentzian(f_window, *popt)
    # FWHM of a Lorentzian is twice the half-width-at-half-maximum (gamma).
    linewidth_fwhm = 2.0 * gamma_fit
    # Analytic area under the Lorentzian peak (excluding the constant offset):
    # integral of amplitude / (1 + ((f - center) / gamma) ** 2) df = pi * amplitude * gamma.
    area = np.pi * amplitude_fit * gamma_fit
    return {
        "amplitude": float(amplitude_fit),
        "center": float(center_fit),
        "gamma": float(gamma_fit),
        "offset": float(offset_fit),
        "peak_amplitude": float(peak_amp_fit),
        "linewidth_fwhm": float(linewidth_fwhm),
        "area": float(area),
        "f_window": f_window,
        "a_window": a_window,
        "fitted_curve": fitted_curve,
    }


def parse_xy_from_filename(name: str) -> Optional[Tuple[float, float]]:
    """Parse the stage x/y position from a trace filename, if present."""
    match = _POSITION_PATTERN.search(name)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def build_grid(points: Dict[Tuple[float, float], float]):
    """Pivot a {(x, y): value} mapping into a 2D grid indexed by unique x/y."""
    if not points:
        raise ValueError("No positional data available to build a grid.")

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

    # Make x increase toward the left side (matches create_grid_file_0427.py).
    ax.invert_xaxis()

    for row_idx in range(grid.shape[0]):
        for col_idx in range(grid.shape[1]):
            val = grid[row_idx, col_idx]
            text = "--" if np.isnan(val) else value_format.format(val)
            ax.text(col_idx, row_idx, text, ha="center", va="center", color="white", fontsize=8)

    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label(cbar_label)

    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def plot_spectrum(
    csv_file: Path,
    frequencies: np.ndarray,
    amplitudes: np.ndarray,
    peak_freq: float,
    peak_amp: float,
    lorentzian_fit=None,
):
    """Plot frequency vs amplitude, mark the peak, optionally overlay a
    Lorentzian fit with error bars showing the deviation between the raw
    data and the fit, and save the figure as a PNG in the Lorentzian folder.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(frequencies, amplitudes, linewidth=0.8, label="Trace")
    ax.plot(peak_freq, peak_amp, "rx", markersize=10, markeredgewidth=2, label="Max point")
    ax.annotate(
        f"{peak_freq:,.1f} Hz\n{peak_amp:.2f}",
        xy=(peak_freq, peak_amp),
        xytext=(10, 10),
        textcoords="offset points",
        color="red",
    )

    if lorentzian_fit is not None:
        fit_center = lorentzian_fit["center"]
        fit_peak_amp = lorentzian_fit["peak_amplitude"]
        f_window = lorentzian_fit["f_window"]
        a_window = lorentzian_fit["a_window"]
        fitted_curve = lorentzian_fit["fitted_curve"]

        # Error bars spanning between the fit curve and the raw data at each
        # frequency point in the fit window (visualizes the fit residual).
        diff = a_window - fitted_curve
        yerr_lower = np.where(diff < 0, -diff, 0.0)
        yerr_upper = np.where(diff > 0, diff, 0.0)
        ax.errorbar(
            f_window,
            fitted_curve,
            yerr=[yerr_lower, yerr_upper],
            fmt="none",
            ecolor="gray",
            elinewidth=0.6,
            alpha=0.5,
            label="Raw-fit deviation",
        )

        ax.plot(f_window, fitted_curve, color="orange", linewidth=1.5, label="Lorentzian fit")
        ax.plot(fit_center, fit_peak_amp, "g+", markersize=12, markeredgewidth=2, label="Lorentzian peak")
        ax.annotate(
            f"{fit_center:,.1f} Hz\n{fit_peak_amp:.2f}",
            xy=(fit_center, fit_peak_amp),
            xytext=(10, -20),
            textcoords="offset points",
            color="green",
        )

    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Amplitude")
    ax.set_title(csv_file.stem)
    ax.grid(True, linewidth=0.3)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()

    plot_file = lorentzian_dir / f"{csv_file.stem}.png"
    fig.savefig(plot_file, dpi=150)
    plt.close(fig)
    return plot_file


def main():
    if not scan_dir.exists():
        print(f"Scan directory not found: {scan_dir}")
        return

    csv_files = sorted(scan_dir.rglob("*.csv"))
    csv_files = [f for f in csv_files if f.resolve() != summary_file.resolve()]

    if not csv_files:
        print(f"No CSV files found in {scan_dir}")
        return

    results = []
    lorentzian_params = []
    freq_points: Dict[Tuple[float, float], float] = {}
    power_points: Dict[Tuple[float, float], float] = {}
    lorentzian_freq_points: Dict[Tuple[float, float], float] = {}
    lorentzian_power_points: Dict[Tuple[float, float], float] = {}
    lorentzian_linewidth_points: Dict[Tuple[float, float], float] = {}
    lorentzian_area_points: Dict[Tuple[float, float], float] = {}
    for csv_file in csv_files:
        frequencies, amplitudes = load_trace(csv_file)
        if len(frequencies) == 0 or len(amplitudes) == 0:
            print(f"  Skipping {csv_file.name}: no data")
            continue

        peak_freq, peak_amp = find_peak(frequencies, amplitudes)
        position = parse_xy_from_filename(csv_file.name)
        x_pos, y_pos = position if position else (None, None)
        print(f"  {csv_file.name}: peak {peak_freq:,.1f} Hz at {peak_amp:.2f}")

        lorentzian_fit = fit_lorentzian(frequencies, amplitudes, peak_freq, peak_amp)
        if lorentzian_fit is not None:
            fit_center = lorentzian_fit["center"]
            fit_peak_amp = lorentzian_fit["peak_amplitude"]
            print(
                "    Lorentzian fit: peak {:,.1f} Hz at {:.2f} (FWHM {:,.2f} Hz, area {:,.2f})".format(
                    fit_center, fit_peak_amp, lorentzian_fit["linewidth_fwhm"], lorentzian_fit["area"]
                )
            )
            lorentzian_params.append((
                csv_file.name, x_pos, y_pos,
                lorentzian_fit["amplitude"], lorentzian_fit["center"],
                lorentzian_fit["gamma"], lorentzian_fit["offset"], lorentzian_fit["peak_amplitude"],
                lorentzian_fit["linewidth_fwhm"], lorentzian_fit["area"],
            ))
        else:
            fit_center, fit_peak_amp = None, None
            print("    Lorentzian fit failed; leaving fit columns blank")

        results.append((csv_file.name, x_pos, y_pos, peak_freq, peak_amp, fit_center, fit_peak_amp))

        if position:
            freq_points[position] = peak_freq
            power_points[position] = peak_amp
            if fit_center is not None:
                lorentzian_freq_points[position] = fit_center
                lorentzian_power_points[position] = fit_peak_amp
                lorentzian_linewidth_points[position] = lorentzian_fit["linewidth_fwhm"]
                lorentzian_area_points[position] = lorentzian_fit["area"]
        else:
            print(f"    Warning: could not parse x/y position from filename {csv_file.name}")

        plot_file = plot_spectrum(csv_file, frequencies, amplitudes, peak_freq, peak_amp, lorentzian_fit)
        print(f"    Saved plot to {plot_file}")

    if not results:
        print("No valid trace data found; summary not written.")
        return

    with open(summary_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "filename", "x_pos", "y_pos", "peak_frequency_hz", "peak_amplitude",
            "lorentzian_peak_frequency_hz", "lorentzian_peak_amplitude",
        ])
        for filename, x_pos, y_pos, peak_freq, peak_amp, fit_center, fit_peak_amp in results:
            writer.writerow([
                filename,
                "" if x_pos is None else x_pos,
                "" if y_pos is None else y_pos,
                peak_freq,
                peak_amp,
                "" if fit_center is None else fit_center,
                "" if fit_peak_amp is None else fit_peak_amp,
            ])

    print(f"\nSaved peak frequency summary to: {summary_file}")

    lorentzian_params_file = summary_file.parent / "lorentzian_fit_parameters.csv"
    if lorentzian_params:
        with open(lorentzian_params_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "filename", "x_pos", "y_pos",
                "amplitude", "center_frequency_hz", "gamma_hz", "offset", "peak_amplitude",
                "linewidth_fwhm_hz", "area",
            ])
            for (
                filename, x_pos, y_pos, amplitude, center, gamma, offset, peak_amplitude,
                linewidth_fwhm, area,
            ) in lorentzian_params:
                writer.writerow([
                    filename,
                    "" if x_pos is None else x_pos,
                    "" if y_pos is None else y_pos,
                    amplitude,
                    center,
                    gamma,
                    offset,
                    peak_amplitude,
                    linewidth_fwhm,
                    area,
                ])
        print(f"Saved Lorentzian fit parameters to: {lorentzian_params_file}")
    else:
        print("No successful Lorentzian fits; lorentzian_fit_parameters.csv not written.")

    if not freq_points:
        print("No filenames with a parseable x/y position; skipping grid CSV/plots.")
        return

    x_unique, y_unique, freq_grid = build_grid(freq_points)
    _, _, power_grid = build_grid(power_points)

    grid_csv_freq = grid_dir / "peak_frequency_grid.csv"
    grid_csv_power = grid_dir / "peak_power_grid.csv"
    grid_png_freq = grid_dir / "peak_frequency_grid.png"
    grid_png_power = grid_dir / "peak_power_grid.png"

    save_grid_csv(grid_csv_freq, x_unique, y_unique, freq_grid)
    save_grid_csv(grid_csv_power, x_unique, y_unique, power_grid)
    save_grid_plot(
        grid_png_freq,
        x_unique,
        y_unique,
        freq_grid,
        title="Peak Frequency by Spatial Position",
        cbar_label="Peak Frequency (Hz)",
        value_format="{:,.0f}",
    )
    save_grid_plot(
        grid_png_power,
        x_unique,
        y_unique,
        power_grid,
        title="Peak Power by Spatial Position",
        cbar_label="Peak Amplitude",
        value_format="{:.2f}",
    )

    if lorentzian_freq_points:
        lx_unique, ly_unique, lorentzian_freq_grid = build_grid(lorentzian_freq_points)
        _, _, lorentzian_power_grid = build_grid(lorentzian_power_points)

        grid_csv_lorentzian_freq = grid_dir / "lorentzian_peak_frequency_grid.csv"
        grid_csv_lorentzian_power = grid_dir / "lorentzian_peak_power_grid.csv"
        grid_png_lorentzian_freq = grid_dir / "lorentzian_peak_frequency_grid.png"
        grid_png_lorentzian_power = grid_dir / "lorentzian_peak_power_grid.png"

        save_grid_csv(grid_csv_lorentzian_freq, lx_unique, ly_unique, lorentzian_freq_grid)
        save_grid_csv(grid_csv_lorentzian_power, lx_unique, ly_unique, lorentzian_power_grid)
        save_grid_plot(
            grid_png_lorentzian_freq,
            lx_unique,
            ly_unique,
            lorentzian_freq_grid,
            title="Lorentzian-Fit Peak Frequency by Spatial Position",
            cbar_label="Lorentzian Peak Frequency (Hz)",
            value_format="{:,.0f}",
        )
        save_grid_plot(
            grid_png_lorentzian_power,
            lx_unique,
            ly_unique,
            lorentzian_power_grid,
            title="Lorentzian-Fit Peak Power by Spatial Position",
            cbar_label="Lorentzian Peak Amplitude",
            value_format="{:.2f}",
        )
        print(f"Saved Lorentzian grid CSVs to: {grid_csv_lorentzian_freq} and {grid_csv_lorentzian_power}")
        print(f"Saved Lorentzian grid plots to: {grid_png_lorentzian_freq} and {grid_png_lorentzian_power}")

        _, _, lorentzian_linewidth_grid = build_grid(lorentzian_linewidth_points)
        _, _, lorentzian_area_grid = build_grid(lorentzian_area_points)

        grid_csv_linewidth = grid_dir / "lorentzian_linewidth_grid.csv"
        grid_csv_area = grid_dir / "lorentzian_area_grid.csv"
        grid_png_linewidth = grid_dir / "lorentzian_linewidth_grid.png"
        grid_png_area = grid_dir / "lorentzian_area_grid.png"

        save_grid_csv(grid_csv_linewidth, lx_unique, ly_unique, lorentzian_linewidth_grid)
        save_grid_csv(grid_csv_area, lx_unique, ly_unique, lorentzian_area_grid)
        save_grid_plot(
            grid_png_linewidth,
            lx_unique,
            ly_unique,
            lorentzian_linewidth_grid,
            title="Lorentzian-Fit Linewidth (FWHM) by Spatial Position",
            cbar_label="Linewidth FWHM (Hz)",
            value_format="{:,.2f}",
        )
        save_grid_plot(
            grid_png_area,
            lx_unique,
            ly_unique,
            lorentzian_area_grid,
            title="Lorentzian-Fit Area by Spatial Position",
            cbar_label="Area",
            value_format="{:.2f}",
        )
        print(f"Saved Lorentzian linewidth/area grid CSVs to: {grid_csv_linewidth} and {grid_csv_area}")
        print(f"Saved Lorentzian linewidth/area grid plots to: {grid_png_linewidth} and {grid_png_area}")
    else:
        print("No successful Lorentzian fits with a parseable position; skipping Lorentzian grid CSV/plots.")

    print(f"Saved grid CSVs to: {grid_csv_freq} and {grid_csv_power}")
    print(f"Saved grid plots to: {grid_png_freq} and {grid_png_power}")


if __name__ == "__main__":
    main()
