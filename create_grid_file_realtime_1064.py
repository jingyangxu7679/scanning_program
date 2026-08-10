"""
Real-time grid display for the 1064 nm optomechanical (Keysight EXA N9010A)
scan, modeled on creat_grid_file_realtime.py's live-display API.

Where creat_grid_file_realtime.py looks up a PicoScope .h5 recording for a
given (x, y) position and reports mean voltage, this module looks up the
single Keysight EXA trace CSV file (saved by testsaveTrace_keysight.py) for
a given (x, y) position, finds its peak frequency (optionally refined with a
Lorentzian fit, as in peakfrequency.py), and reports that peak frequency so
it can be plotted at the right grid cell in real time as the scan runs.
"""

from __future__ import annotations

import csv
import math
import multiprocessing
import re
import time
from pathlib import Path
from queue import Empty
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit

DEFAULT_DATA_DIR = Path.home() / "Desktop" / "Keysight_EXA_N9010A"

# Number of points to include on each side of the detected peak when fitting
# the Lorentzian (same default as peakfrequency.py).
LORENTZIAN_FIT_WINDOW_POINTS = 200

# Matches the "..._x{value}_y{value}_..." pattern used by testsaveTrace_keysight.py
# (e.g. "ONtrace_data_x2.2000_y2.2300_20260731_120401.csv").
_POSITION_PATTERN = re.compile(r"x(-?\d+(?:\.\d+)?)_y(-?\d+(?:\.\d+)?)")

# Figure size is capped so the window always fits on screen (and can be dragged/moved),
# regardless of how many x/y positions are in the scan.
MIN_FIG_WIDTH_IN = 8.0
MIN_FIG_HEIGHT_IN = 5.0
MAX_FIG_WIDTH_IN = 14.0
MAX_FIG_HEIGHT_IN = 9.0


def _figure_size(n_x: int, n_y: int) -> Tuple[float, float]:
	"""Compute a figure size (inches) that scales gently with grid size but never
	exceeds MAX_FIG_WIDTH_IN x MAX_FIG_HEIGHT_IN, so the window stays on-screen
	and movable.
	"""
	width = min(MAX_FIG_WIDTH_IN, max(MIN_FIG_WIDTH_IN, n_x * 0.3))
	height = min(MAX_FIG_HEIGHT_IN, max(MIN_FIG_HEIGHT_IN, n_y * 0.3))
	return width, height


def _position_window(fig: "plt.Figure") -> None:
	"""Best-effort move of the figure window near the screen's top-left corner so
	its title bar (and thus drag-to-move) is reachable, regardless of backend.
	"""
	try:
		manager = fig.canvas.manager
		window = getattr(manager, "window", None)
		if window is None:
			return
		if hasattr(window, "wm_geometry"):  # Tk-based backends
			window.wm_geometry("+50+50")
		elif hasattr(window, "move"):  # Qt-based backends
			window.move(50, 50)
	except Exception:
		pass


def _thinned_ticks(positions: List[float], max_labels: int = 20) -> Tuple[List[int], List[str]]:
	"""Pick a subset of tick indices/labels so at most `max_labels` are shown.

	With many scan positions, labeling every single one causes the tick text to
	overlap and become unreadable, so only every Nth position is labeled.
	"""
	n = len(positions)
	step = max(1, math.ceil(n / max_labels))
	indices = list(range(0, n, step))
	labels = [f"{positions[i]:.3f}" for i in indices]
	return indices, labels


def generate_positions(start: float, stop: float, step: float) -> List[float]:
	"""Build an inclusive list of positions from start to stop using step."""
	if step <= 0:
		raise ValueError("step must be positive")
	n_steps = int(round((stop - start) / step)) + 1
	return [round(start + i * step, 6) for i in range(max(n_steps, 1))]


# ---------------------------------------------------------------------------
# Single-file trace analysis (finds the one file for a given x/y position and
# extracts its peak frequency), mirroring peakfrequency.py's algorithms.
# ---------------------------------------------------------------------------


def find_file_by_position(data_dir: Path, x_pos: float, y_pos: float, tolerance: float = 1e-3) -> Path:
	"""Find the newest trace CSV in data_dir matching the requested x/y position."""
	data_dir = Path(data_dir)
	if not data_dir.exists() or not data_dir.is_dir():
		raise FileNotFoundError(f"Data directory not found: {data_dir}")

	pattern = "*x{:.4f}_y{:.4f}_*.csv".format(x_pos, y_pos)
	direct_matches = sorted(data_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
	if direct_matches:
		return direct_matches[-1]

	# Fallback for any token formatting differences: parse and compare numerically.
	numeric_matches: List[Path] = []
	for path in data_dir.glob("*.csv"):
		match = _POSITION_PATTERN.search(path.name)
		if not match:
			continue
		x_file, y_file = float(match.group(1)), float(match.group(2))
		if abs(x_file - x_pos) <= tolerance and abs(y_file - y_pos) <= tolerance:
			numeric_matches.append(path)

	if not numeric_matches:
		raise FileNotFoundError(f"No trace file found for x={x_pos:.4f}, y={y_pos:.4f} in {data_dir}")

	numeric_matches.sort(key=lambda p: p.stat().st_mtime)
	return numeric_matches[-1]


def load_trace(csv_path: Path) -> Tuple[np.ndarray, np.ndarray]:
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
			raise ValueError(f"Unrecognized headers in {csv_path.name}")

		for row in reader:
			try:
				frequencies.append(float(row[freq_key]))
				amplitudes.append(float(row[amp_key]))
			except (ValueError, KeyError):
				continue

	return np.array(frequencies), np.array(amplitudes)


def find_peak(frequencies: np.ndarray, amplitudes: np.ndarray) -> Tuple[float, float]:
	"""Return (peak_frequency, peak_amplitude) for the maximum amplitude point."""
	peak_index = int(np.argmax(amplitudes))
	return float(frequencies[peak_index]), float(amplitudes[peak_index])


def lorentzian(f, amplitude, center, gamma, offset):
	"""Lorentzian line shape: amplitude / (1 + ((f - center) / gamma) ** 2) + offset."""
	return amplitude / (1.0 + ((f - center) / gamma) ** 2) + offset


def fit_lorentzian(
	frequencies: np.ndarray,
	amplitudes: np.ndarray,
	peak_freq: float,
	peak_amp: float,
	window_points: int = LORENTZIAN_FIT_WINDOW_POINTS,
) -> Optional[Dict[str, object]]:
	"""Fit a Lorentzian around the detected peak.

	Returns a dict with keys "center" and "peak_amplitude" (plus the raw fit
	parameters), or None if there isn't enough data or the fit fails to converge.
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
	return {
		"amplitude": float(amplitude_fit),
		"center": float(center_fit),
		"gamma": float(gamma_fit),
		"offset": float(offset_fit),
		"peak_amplitude": float(peak_amp_fit),
	}


def analyze_single(
	x: float,
	y: float,
	data_dir: Path | str = DEFAULT_DATA_DIR,
	tolerance: float = 1e-3,
	use_lorentzian: bool = True,
) -> Dict[str, object]:
	"""Find the trace file for (x, y), analyze it, and return its peak frequency.

	Mirrors analyze_0427_singlefile.analyze_single()'s (x, y, data_dir) -> dict
	shape, so callers (e.g. Move_2D_1064.py) can use it the same way
	Move_2D_picoscope.py uses analyze_0427_singlefile.analyze_single().
	"""
	resolved_data_dir = Path(data_dir).expanduser().resolve()
	file_path = find_file_by_position(resolved_data_dir, x, y, tolerance=tolerance)

	frequencies, amplitudes = load_trace(file_path)
	if len(frequencies) == 0 or len(amplitudes) == 0:
		raise ValueError(f"No trace data found in {file_path.name}")

	peak_freq, peak_amp = find_peak(frequencies, amplitudes)

	lorentzian_freq = None
	lorentzian_amp = None
	if use_lorentzian:
		fit = fit_lorentzian(frequencies, amplitudes, peak_freq, peak_amp)
		if fit is not None:
			lorentzian_freq = fit["center"]
			lorentzian_amp = fit["peak_amplitude"]

	return {
		"file": str(file_path),
		"x_pos": x,
		"y_pos": y,
		"peak_frequency_hz": peak_freq,
		"peak_amplitude": peak_amp,
		"lorentzian_peak_frequency_hz": lorentzian_freq,
		"lorentzian_peak_amplitude": lorentzian_amp,
	}


# ---------------------------------------------------------------------------
# Live grid display (same shape/API as creat_grid_file_realtime.py).
# ---------------------------------------------------------------------------


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


def init_realtime_display(x_positions: List[float], y_positions: List[float]) -> Dict[str, object]:
	"""Create the live grid figure and return a state dict for update_realtime_display().

	The figure is drawn once here but is NOT refreshed automatically afterwards;
	call update_realtime_display() explicitly whenever a new value should appear.
	"""
	grid = np.full((len(y_positions), len(x_positions)), np.nan, dtype=float)

	plt.ion()
	fig, ax = plt.subplots(figsize=_figure_size(len(x_positions), len(y_positions)))
	_position_window(fig)
	image = ax.imshow(grid, origin="upper", cmap="viridis", aspect="auto")

	x_tick_idx, x_tick_labels = _thinned_ticks(x_positions)
	y_tick_idx, y_tick_labels = _thinned_ticks(y_positions)
	ax.set_xticks(x_tick_idx)
	ax.set_yticks(y_tick_idx)
	ax.set_xticklabels(x_tick_labels, rotation=45, ha="right", fontsize=8)
	ax.set_yticklabels(y_tick_labels, fontsize=8)
	ax.set_xlabel("X position")
	ax.set_ylabel("Y position")
	ax.set_title("Real-time Peak Frequency (Hz)")
	# X increases to the left; Y increases from top to bottom.
	ax.invert_xaxis()

	cbar = fig.colorbar(image, ax=ax)
	cbar.set_label("Peak Frequency (Hz)")

	# Fewer decimal places than a typical grid annotation (peak frequencies are
	# ~5-6 digits before the decimal point), so per-cell text doesn't overlap
	# its neighbors once every cell in the grid has a value.
	texts = [
		[ax.text(col_idx, row_idx, "--", ha="center", va="center", color="white", fontsize=7) for col_idx in range(len(x_positions))]
		for row_idx in range(len(y_positions))
	]

	fig.tight_layout()
	fig.canvas.draw()
	plt.pause(0.01)

	return {
		"fig": fig,
		"ax": ax,
		"image": image,
		"texts": texts,
		"grid": grid,
		"x_positions": x_positions,
		"y_positions": y_positions,
	}


def _position_index(positions: List[float], value: float, tolerance: float = 1e-6) -> int:
	"""Return the index of the position list entry closest to value.

	Raises ValueError if no entry is within tolerance.
	"""
	best_idx = min(range(len(positions)), key=lambda i: abs(positions[i] - value))
	if abs(positions[best_idx] - value) > tolerance:
		raise ValueError(f"Position {value} not found in grid positions (closest: {positions[best_idx]})")
	return best_idx


def update_realtime_display(state: Dict[str, object], x: float, y: float, value: float, pause_seconds: float = 0.05) -> None:
	"""Set the grid cell for position (x, y) and redraw the live grid plot.

	The plot only changes when this function is explicitly called - nothing
	updates the figure on its own between calls. The (x, y) position is looked
	up against the grid's position lists to find the correct cell to update.
	"""
	x_positions: List[float] = state["x_positions"]  # type: ignore[assignment]
	y_positions: List[float] = state["y_positions"]  # type: ignore[assignment]
	col_idx = _position_index(x_positions, x)
	row_idx = _position_index(y_positions, y)

	grid: np.ndarray = state["grid"]  # type: ignore[assignment]
	grid[row_idx, col_idx] = value
	state["texts"][row_idx][col_idx].set_text(f"{value:.1f}")  # type: ignore[index]

	finite_vals = grid[np.isfinite(grid)]
	if finite_vals.size:
		state["image"].set_data(grid)  # type: ignore[attr-defined]
		state["image"].set_clim(vmin=float(np.min(finite_vals)), vmax=float(np.max(finite_vals)))  # type: ignore[attr-defined]

	fig = state["fig"]
	fig.canvas.draw_idle()  # type: ignore[attr-defined]
	# Pump the GUI event loop without re-showing/raising the window. plt.pause()
	# internally calls show(block=False) on every invocation, which repeatedly
	# re-raises the window and steals focus from other apps - flush_events()
	# processes pending GUI events (including drag-to-move) without that side effect.
	fig.canvas.flush_events()  # type: ignore[attr-defined]
	if pause_seconds:
		time.sleep(pause_seconds)


def _display_worker(queue: "multiprocessing.Queue", x_positions: List[float], y_positions: List[float]) -> None:
	"""Entry point for the live display's dedicated process.

	Running the plot here means its GUI event loop is never blocked by whatever
	the caller (e.g. motor control code) is doing in the main process - this is
	what keeps the window movable/responsive during a long scan.
	"""
	state = init_realtime_display(x_positions, y_positions)

	while True:
		try:
			msg = queue.get(timeout=0.1)
		except Empty:
			# No new data - still pump the GUI event loop so the window stays responsive,
			# but avoid plt.pause() here since it repeatedly re-shows/raises the window
			# (stealing focus from other apps) on every call.
			try:
				state["fig"].canvas.flush_events()  # type: ignore[attr-defined]
			except Exception:
				pass
			continue

		kind = msg[0]
		if kind == "update":
			_, x, y, value = msg
			try:
				update_realtime_display(state, x, y, value, pause_seconds=0.01)
			except ValueError as exc:
				print(f"[realtime display] {exc}")
		elif kind == "save":
			_, csv_path, png_path = msg
			save_grid_csv(Path(csv_path), x_positions, y_positions, state["grid"])
			state["fig"].savefig(png_path, dpi=300)
		elif kind == "stop":
			break

	# Keep the window open (and still responsive/movable) after the scan ends,
	# until the user closes it.
	try:
		plt.ioff()
		plt.show()
	except Exception:
		pass


class RealtimeDisplayHandle:
	"""Handle for controlling a live grid plot running in its own process."""

	def __init__(self, process: "multiprocessing.Process", queue: "multiprocessing.Queue") -> None:
		self._process = process
		self._queue = queue

	def update(self, x: float, y: float, value: float) -> None:
		"""Send a new (x, y, value) reading to the display process."""
		self._queue.put(("update", x, y, value))

	def save(self, csv_path: Path, png_path: Path) -> None:
		"""Ask the display process to save the current grid to CSV and PNG."""
		self._queue.put(("save", str(csv_path), str(png_path)))

	def close(self, join: bool = False, timeout: float | None = None) -> None:
		"""Tell the display process the scan is done. The window stays open (and
		movable) for the user to inspect until they close it themselves.
		"""
		self._queue.put(("stop",))
		if join:
			self._process.join(timeout)


def launch_realtime_display(x_positions: List[float], y_positions: List[float]) -> RealtimeDisplayHandle:
	"""Start the live grid plot in its own process and return a handle to control it.

	Use this instead of init_realtime_display()/update_realtime_display() when the
	caller (e.g. a motor scan loop) will be doing long blocking operations between
	updates - keeping the plot in a separate process means its window stays
	movable/responsive no matter how busy the caller's process is.
	"""
	ctx = multiprocessing.get_context("spawn")
	queue = ctx.Queue()
	process = ctx.Process(target=_display_worker, args=(queue, x_positions, y_positions), daemon=False)
	process.start()
	return RealtimeDisplayHandle(process, queue)
