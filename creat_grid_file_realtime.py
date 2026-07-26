from __future__ import annotations

import argparse
import csv
import math
import multiprocessing
import time
from pathlib import Path
from queue import Empty
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import analyze_0427_singlefile

DEFAULT_DATA_DIR = analyze_0427_singlefile.DEFAULT_DATA_DIR

DEFAULT_OUTPUT_CSV_DIR = Path.home() / "Desktop" / "test_data_04" / "27" / "0722_scan1" / "CSV" / "summary_0427_20260722_175618"
DEFAULT_OUTPUT_GRAPH_DIR = Path.home() / "Desktop" / "test_data_04" / "27" / "0722_scan1" / "Grid_graphs"
DEFAULT_OUTPUT_GRAPH_MEAN_DIR = Path.home() / "Desktop" / "test_data_04" / "27" / "0722_scan1" / "grid_graph_mean"

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

	fig, ax = plt.subplots(figsize=_figure_size(len(x_unique), len(y_unique)))
	# origin="upper": y increases from top to bottom on the rendered map.
	image = ax.imshow(grid_for_plot, origin="upper", cmap="viridis", aspect="auto")

	x_tick_idx, x_tick_labels = _thinned_ticks(x_unique)
	y_tick_idx, y_tick_labels = _thinned_ticks(y_unique)
	ax.set_xticks(x_tick_idx)
	ax.set_yticks(y_tick_idx)
	ax.set_xticklabels(x_tick_labels, rotation=45, ha="right", fontsize=8)
	ax.set_yticklabels(y_tick_labels, fontsize=8)

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


def generate_positions(start: float, stop: float, step: float) -> List[float]:
	"""Build an inclusive list of positions from start to stop using step."""
	if step <= 0:
		raise ValueError("step must be positive")
	n_steps = int(round((stop - start) / step)) + 1
	return [round(start + i * step, 6) for i in range(max(n_steps, 1))]


def init_realtime_display(x_positions: List[float], y_positions: List[float], channel: str) -> Dict[str, object]:
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
	ax.set_title(f"Real-time Mean Channel {channel} (mV)")
	# X increases to the left; Y increases from top to bottom.
	ax.invert_xaxis()

	cbar = fig.colorbar(image, ax=ax)
	cbar.set_label(f"Mean Voltage {channel} (mV)")

	texts = [
		[ax.text(col_idx, row_idx, "--", ha="center", va="center", color="white", fontsize=8) for col_idx in range(len(x_positions))]
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
	state["texts"][row_idx][col_idx].set_text(f"{value:.3f}")  # type: ignore[index]

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


def _display_worker(queue: "multiprocessing.Queue", x_positions: List[float], y_positions: List[float], channel: str) -> None:
	"""Entry point for the live display's dedicated process.

	Running the plot here means its GUI event loop is never blocked by whatever
	the caller (e.g. motor control code) is doing in the main process - this is
	what keeps the window movable/responsive during a long scan.
	"""
	state = init_realtime_display(x_positions, y_positions, channel)

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


def launch_realtime_display(x_positions: List[float], y_positions: List[float], channel: str = "A") -> RealtimeDisplayHandle:
	"""Start the live grid plot in its own process and return a handle to control it.

	Use this instead of init_realtime_display()/update_realtime_display() when the
	caller (e.g. a motor scan loop) will be doing long blocking operations between
	updates - keeping the plot in a separate process means its window stays
	movable/responsive no matter how busy the caller's process is.
	"""
	ctx = multiprocessing.get_context("spawn")
	queue = ctx.Queue()
	process = ctx.Process(target=_display_worker, args=(queue, x_positions, y_positions, channel), daemon=False)
	process.start()
	return RealtimeDisplayHandle(process, queue)


def run_realtime_scan(
	x_positions: List[float],
	y_positions: List[float],
	data_dir: Path,
	channel: str = "A",
	pause_seconds: float = 0.05,
	output_csv_dir: Path = DEFAULT_OUTPUT_CSV_DIR,
	output_graph_dir: Path = DEFAULT_OUTPUT_GRAPH_MEAN_DIR,
	output_prefix: str = "realtime_scan",
) -> Tuple[List[float], List[float], np.ndarray]:
	"""Scan through (x, y) positions, calling analyze_single for each one, and
	explicitly refresh the live grid plot only when a new value is obtained.
	"""
	value_key = f"mean_{channel}_mV"
	state = init_realtime_display(x_positions, y_positions, channel)

	for row_idx, y_val in enumerate(y_positions):
		for col_idx, x_val in enumerate(x_positions):
			try:
				result = analyze_0427_singlefile.analyze_single(x=x_val, y=y_val, data_dir=data_dir)
				value = float(result[value_key])
			except FileNotFoundError as exc:
				print(f"Skipping x={x_val:.3f}, y={y_val:.3f}: {exc}")
				continue

			# The grid graph is only updated by this explicit call.
			update_realtime_display(state, x_val, y_val, value, pause_seconds=pause_seconds)

			print(f"x={x_val:.3f}, y={y_val:.3f} -> mean_{channel}_mV={value:.4f}")

	fig: plt.Figure = state["fig"]  # type: ignore[assignment]
	grid: np.ndarray = state["grid"]  # type: ignore[assignment]

	output_csv_dir.mkdir(parents=True, exist_ok=True)
	output_graph_dir.mkdir(parents=True, exist_ok=True)
	csv_path = output_csv_dir / f"{output_prefix}_mean_{channel}_grid.csv"
	png_path = output_graph_dir / f"{output_prefix}_mean_{channel}_grid.png"
	save_grid_csv(csv_path, x_positions, y_positions, grid)
	fig.savefig(png_path, dpi=300)

	print(f"Real-time grid CSV written to: {csv_path}")
	print(f"Real-time grid image written to: {png_path}")

	plt.ioff()
	plt.show()

	return x_positions, y_positions, grid


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Real-time scan grid: analyze each (x, y) position via analyze_single and update a live plot as results arrive."
	)
	parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help=f"Folder containing .h5 recordings (default: {DEFAULT_DATA_DIR})")
	parser.add_argument("--x-start", type=float, default=0.0, help="First x position (default: 0.0)")
	parser.add_argument("--x-stop", type=float, default=0.40, help="Last x position (default: 0.40)")
	parser.add_argument("--x-step", type=float, default=0.01, help="Step size between x positions (default: 0.01)")
	parser.add_argument("--y-start", type=float, default=0.0, help="First y position (default: 0.0)")
	parser.add_argument("--y-stop", type=float, default=0.04, help="Last y position (default: 0.04)")
	parser.add_argument("--y-step", type=float, default=0.01, help="Step size between y positions (default: 0.01)")
	parser.add_argument("--channel", choices=["A", "B"], default="A", help="Which channel's mean to display (default: A)")
	parser.add_argument("--pause", type=float, default=0.05, help="Seconds to pause between live plot updates (default: 0.05)")
	parser.add_argument("--output-csv-dir", type=Path, default=DEFAULT_OUTPUT_CSV_DIR, help="Folder for the final grid CSV file")
	parser.add_argument("--output-graph-dir", type=Path, default=DEFAULT_OUTPUT_GRAPH_MEAN_DIR, help="Folder for the final grid image")
	parser.add_argument("--output-prefix", type=str, default="realtime_scan", help="Prefix for generated output files")
	args = parser.parse_args()

	x_positions = generate_positions(args.x_start, args.x_stop, args.x_step)
	y_positions = generate_positions(args.y_start, args.y_stop, args.y_step)

	run_realtime_scan(
		x_positions,
		y_positions,
		data_dir=args.data_dir,
		channel=args.channel,
		pause_seconds=args.pause,
		output_csv_dir=args.output_csv_dir,
		output_graph_dir=args.output_graph_dir,
		output_prefix=args.output_prefix,
	)


if __name__ == "__main__":
	main()
