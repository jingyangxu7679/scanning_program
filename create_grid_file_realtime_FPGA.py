"""
Real-time grid display for the FPGA multi-peak scanning program
(Move_2D_FPGA.py), modeled on creat_grid_file_realtime.py's live-display API.

Unlike the PicoScope/Keysight EXA workflows, Move_2D_FPGA.py already has each
pixel's frequency data in memory as soon as log_pixel() returns, so this
module only provides the generic live-grid-display machinery plus a small
helper (compute_realtime_value()) that reduces one pixel's frame array to
the single number plotted at that grid cell - no per-position file lookup
or parsing is needed.
"""

from __future__ import annotations

import csv
import math
import multiprocessing
import time
from pathlib import Path
from queue import Empty
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np

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
# Per-pixel stat helper. Move_2D_FPGA.py already has the frame array for a
# pixel in memory as soon as log_pixel() returns, so - unlike the PicoScope
# and Keysight EXA workflows this module was modeled on - no file needs to
# be located or parsed here.
# ---------------------------------------------------------------------------


def compute_realtime_value(frames: np.ndarray, freq_col: str = "f0_hz", stat: str = "mean") -> float:
	"""Reduce one pixel's structured frame array to the single number to plot."""
	vals = frames[freq_col].astype(float)
	if stat == "mean":
		return float(np.mean(vals))
	if stat == "median":
		return float(np.median(vals))
	if stat == "rms":
		return float(np.sqrt(np.mean(np.square(vals))))
	raise ValueError(f"Unknown stat: {stat}")


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

	fig.tight_layout()
	fig.canvas.draw()
	plt.pause(0.01)

	return {
		"fig": fig,
		"ax": ax,
		"image": image,
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
