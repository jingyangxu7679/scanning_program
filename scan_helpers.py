"""
Helpers for the 2D (X/Y) raster scan in Motor_GUI.py.

Contains:
  * ZFunction      - safe parser/evaluator for a user-entered z = f(x, y) focus
                     compensation expression (modeled on shift_zfocus_stage() in
                     Move_2D_1064.py).
  * generate_positions / preview_z_map - grid + z preview utilities.
  * ScanConfig / run_scan - threaded scan engine: zigzag X/Y raster, z focus
                     compensation, optional Keysight EXA capture + peak-frequency
                     analysis (same as Move_2D_1064.py), CSV logging, stop support.

The scan engine never touches Tk; it reports progress through an `emit(kind, data)`
callback so the GUI can marshal events onto its main thread.
"""

from __future__ import annotations

import ast
import csv
import math
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# z = f(x, y) expression handling
# ---------------------------------------------------------------------------

Z_VARIABLES = ("x", "y", "x0", "y0", "z0", "dx", "dy")

_Z_FUNCTIONS: Dict[str, Callable] = {
	"abs": abs,
	"min": min,
	"max": max,
	"round": round,
	"sqrt": math.sqrt,
	"exp": math.exp,
	"log": math.log,
	"log10": math.log10,
	"sin": math.sin,
	"cos": math.cos,
	"tan": math.tan,
	"floor": math.floor,
	"ceil": math.ceil,
	"hypot": math.hypot,
	"clip": lambda v, lo, hi: max(lo, min(hi, v)),
}

_Z_CONSTANTS = {"pi": math.pi, "e": math.e}

_ALLOWED_NODES = (
	ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
	ast.Call, ast.Name, ast.Load, ast.Constant,
	ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
	ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
	ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
)

# Reproduces shift_zfocus_stage() from Move_2D_1064.py as a z = f(x, y) expression.
MOVE_2D_1064_Z_EXPRESSION = """\
# Same focus map as shift_zfocus_stage() in Move_2D_1064.py
z0
+ ((x - 2.20) / 0.05 * 0.001 if x < 2.55
   else (2.55 - 2.20) / 0.05 * 0.001 + (x - 2.55) / 0.05 * 0.0015)
+ (0.0 if y < 2.35 else 0.001 if y < 2.45 else 0.002 if y < 2.55
   else 0.003 if y < 2.65 else 0.004 if y < 2.70 else 0.005)
"""

DEFAULT_Z_EXPRESSION = "# z stays at the starting z position (no compensation)\nz0\n"

Z_EXPRESSION_HELP = (
	"Enter the absolute z position as a function of x and y. Variables: x, y (current "
	"stage position), x0, y0 (scan start), z0 (z at scan start), dx = x - x0, dy = y - y0. "
	"Functions: " + ", ".join(sorted(_Z_FUNCTIONS)) + "; constants: pi, e. "
	"Piecewise: 'a if cond else b'. Multi-line and # comments allowed."
)


class ZFunctionError(ValueError):
	pass


class ZFunction:
	"""Safely compiled user expression z = f(x, y, x0, y0, z0, dx, dy)."""

	def __init__(self, text: str):
		self.text = text
		lines = [line.split("#", 1)[0] for line in text.splitlines()]
		body = "\n".join(lines).strip()
		if not body:
			raise ZFunctionError("Z function is empty.")
		try:
			# Wrapping in parentheses lets the expression span multiple lines.
			tree = ast.parse(f"(\n{body}\n)", mode="eval")
		except SyntaxError as exc:
			raise ZFunctionError(f"Syntax error in z function: {exc.msg}") from exc
		self._validate(tree)
		self._code = compile(tree, "<z_function>", "eval")

	@staticmethod
	def _validate(tree: ast.AST) -> None:
		for node in ast.walk(tree):
			if not isinstance(node, _ALLOWED_NODES):
				raise ZFunctionError(f"Unsupported syntax in z function: {type(node).__name__}")
			if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
				raise ZFunctionError(f"Only numeric constants are allowed (got {node.value!r}).")
			if isinstance(node, ast.Call):
				if not isinstance(node.func, ast.Name) or node.func.id not in _Z_FUNCTIONS:
					raise ZFunctionError("Only these functions are allowed: " + ", ".join(sorted(_Z_FUNCTIONS)))
				if node.keywords:
					raise ZFunctionError("Keyword arguments are not allowed in the z function.")
			if isinstance(node, ast.Name):
				if node.id not in Z_VARIABLES and node.id not in _Z_FUNCTIONS and node.id not in _Z_CONSTANTS:
					raise ZFunctionError(
						f"Unknown name '{node.id}'. Allowed variables: {', '.join(Z_VARIABLES)}"
					)

	def __call__(self, x: float, y: float, x0: float, y0: float, z0: float) -> float:
		namespace = {"__builtins__": {}}
		namespace.update(_Z_FUNCTIONS)
		namespace.update(_Z_CONSTANTS)
		namespace.update({"x": x, "y": y, "x0": x0, "y0": y0, "z0": z0, "dx": x - x0, "dy": y - y0})
		try:
			value = float(eval(self._code, namespace))  # noqa: S307 - AST is whitelisted above
		except Exception as exc:
			raise ZFunctionError(f"Error evaluating z function at x={x}, y={y}: {exc}") from exc
		if not math.isfinite(value):
			raise ZFunctionError(f"Z function returned a non-finite value at x={x}, y={y}.")
		return value


# ---------------------------------------------------------------------------
# Grid utilities
# ---------------------------------------------------------------------------


def generate_positions(start: float, stop: float, step: float) -> List[float]:
	"""Inclusive list of positions from start to stop (either direction) using |step|."""
	step = abs(step)
	if step <= 0:
		raise ValueError("step must be > 0")
	direction = 1.0 if stop >= start else -1.0
	n_steps = int(round(abs(stop - start) / step)) + 1
	return [round(start + direction * i * step, 6) for i in range(n_steps)]


def preview_z_map(
	z_func: ZFunction, x_positions: List[float], y_positions: List[float], z0: float
) -> np.ndarray:
	"""Evaluate z over the whole grid (rows = y, cols = x) using commanded positions."""
	x0, y0 = x_positions[0], y_positions[0]
	grid = np.empty((len(y_positions), len(x_positions)), dtype=float)
	for j, y in enumerate(y_positions):
		for i, x in enumerate(x_positions):
			grid[j, i] = z_func(x, y, x0, y0, z0)
	return grid


# ---------------------------------------------------------------------------
# Scan engine
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
KEYSIGHT_SCRIPT = HERE / "testsaveTrace_keysight.py"
# Must match the output folder hardcoded in testsaveTrace_keysight.py (see Move_2D_1064.py).
DEFAULT_KEYSIGHT_DATA_DIR = Path.home() / "Desktop" / "Keysight_EXA_N9010A" / "reduceTime_0813"
DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "motor_pos_time"

X_CHANNEL, Y_CHANNEL, Z_CHANNEL = 1, 2, 3


@dataclass
class ScanConfig:
	x_positions: List[float]
	y_positions: List[float]
	dwell_s: float = 1.0
	zigzag: bool = True
	z_function: Optional[ZFunction] = None  # None disables z compensation
	z_every_n: int = 1
	max_z_deviation: float = 0.1
	acquire_keysight: bool = False
	keysight_data_dir: Path = DEFAULT_KEYSIGHT_DATA_DIR
	output_dir: Path = DEFAULT_OUTPUT_DIR
	file_stem: Optional[str] = None  # None -> "gui_scan_<timestamp>"
	move_timeout_ms: int = 60000


class ScanStopped(Exception):
	pass


_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
_RESERVED_WINDOWS_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
OUTPUT_EXTENSIONS = (".csv", ".png")


def clean_file_stem(name: str) -> str:
	"""Validate a user-entered scan file name and return it without a .csv/.png extension."""
	stem = name.strip()
	if stem.lower().endswith(OUTPUT_EXTENSIONS):
		stem = stem[:-4]
	stem = stem.rstrip(" .")
	if not stem:
		raise ValueError("file name is empty")
	bad = sorted({c for c in stem if c in _INVALID_FILENAME_CHARS or ord(c) < 32})
	if bad:
		raise ValueError(f"file name contains invalid characters: {' '.join(bad)}")
	if stem.upper() in _RESERVED_WINDOWS_NAMES:
		raise ValueError(f"'{stem}' is a reserved Windows file name")
	return stem


def output_paths(output_dir: Path, file_stem: str) -> List[Path]:
	"""The files a scan writes: <stem>.csv (point log) and <stem>.png (final maps)."""
	return [Path(output_dir) / f"{file_stem}{ext}" for ext in OUTPUT_EXTENSIONS]


def existing_output_files(output_dir: Path, file_stem: str) -> List[Path]:
	return [p for p in output_paths(output_dir, file_stem) if p.exists()]


def next_free_stem(output_dir: Path, file_stem: str) -> str:
	"""First '<stem>_2', '<stem>_3', ... whose output files don't exist yet."""
	n = 2
	while existing_output_files(output_dir, f"{file_stem}_{n}"):
		n += 1
	return f"{file_stem}_{n}"


def _to_float(value) -> float:
	# Kinesis returns System.Decimal; str() round-trips it exactly.
	return float(str(value))


def _measure_keysight(x: float, y: float, data_dir: Path) -> Optional[float]:
	"""Capture an EXA trace at (x, y) and return its (Lorentzian-refined) peak frequency."""
	import create_grid_file_realtime_1064 as rt1064  # heavy imports (scipy) - load lazily

	# keysight_ktxsan requires Python 3.10, hence the "py -3.10" launcher (as in Move_2D_1064.py).
	subprocess.run(
		["py", "-3.10", str(KEYSIGHT_SCRIPT), "--x-pos", str(x), "--y-pos", str(y)],
		check=True,
	)
	result = rt1064.analyze_single(x=x, y=y, data_dir=data_dir)
	lorentzian = result["lorentzian_peak_frequency_hz"]
	return float(lorentzian if lorentzian is not None else result["peak_frequency_hz"])


def run_scan(
	config: ScanConfig,
	motor_module,
	io_lock: threading.Lock,
	stop_event: threading.Event,
	emit: Callable[[str, Dict[str, object]], None],
) -> None:
	"""Run an X/Y raster scan. Blocking - call from a worker thread.

	Events emitted: "start", "point", "warning", "done", "error".
	The motor lock is taken per move/read so the GUI's position poller keeps
	updating between moves.
	"""

	def move(channel_num: int, position: float) -> float:
		with io_lock:
			channel = motor_module._get_connected_channel(channel_num)
			channel.MoveTo(motor_module.Decimal(float(position)), config.move_timeout_ms)
			return _to_float(channel.DevicePosition)

	def read(channel_num: int) -> float:
		with io_lock:
			return _to_float(motor_module.motor_position(channel_num, 0))

	def check_stop():
		if stop_event.is_set():
			raise ScanStopped()

	x_positions, y_positions = config.x_positions, config.y_positions
	total = len(x_positions) * len(y_positions)
	x0, y0 = x_positions[0], y_positions[0]

	config.output_dir.mkdir(parents=True, exist_ok=True)
	run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
	csv_path = config.output_dir / f"{config.file_stem or f'gui_scan_{run_timestamp}'}.csv"
	tz_minus_7 = timezone(timedelta(hours=-7))

	stopped = False
	completed = 0
	try:
		z0 = read(Z_CHANNEL)
		emit("start", {
			"x_positions": x_positions,
			"y_positions": y_positions,
			"z0": z0,
			"total": total,
			"csv_path": str(csv_path),
			"run_timestamp": run_timestamp,
			"z_enabled": config.z_function is not None,
			"acquire": config.acquire_keysight,
		})

		with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
			writer = csv.writer(csv_file)
			writer.writerow([
				"Time (UTC -07:00 yyyy-MM-dd HH:mm:ss)", "x_index", "y_index",
				"x_pos", "y_pos", "z_command", "z_pos", "peak_frequency_hz",
			])

			z_actual = z0
			for j, y_target in enumerate(y_positions):
				check_stop()
				y_actual = move(Y_CHANNEL, y_target)

				# Zigzag: alternate x direction each row to avoid long backlash-prone return jumps.
				x_indices = range(len(x_positions))
				if config.zigzag and j % 2 == 1:
					x_indices = reversed(x_indices)

				for i in x_indices:
					check_stop()
					x_actual = move(X_CHANNEL, x_positions[i])

					z_command = None
					if config.z_function is not None and i % config.z_every_n == 0:
						z_command = config.z_function(x_actual, y_actual, x0, y0, z0)
						if abs(z_command - z0) > config.max_z_deviation:
							raise ZFunctionError(
								f"Z command {z_command:.6f} at x={x_actual}, y={y_actual} deviates "
								f"more than {config.max_z_deviation} from z0={z0:.6f}; scan aborted."
							)
						z_actual = move(Z_CHANNEL, z_command)

					if config.dwell_s > 0:
						# Sleep in small slices so Stop stays responsive.
						end = time.monotonic() + config.dwell_s
						while True:
							check_stop()
							remaining = end - time.monotonic()
							if remaining <= 0:
								break
							time.sleep(min(0.05, remaining))

					value = None
					if config.acquire_keysight:
						try:
							value = _measure_keysight(x_actual, y_actual, config.keysight_data_dir)
						except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
							emit("warning", {"message": f"Measurement failed at x={x_actual}, y={y_actual}: {exc}"})

					writer.writerow([
						datetime.now(tz_minus_7).strftime("%Y-%m-%d %H:%M:%S"), i, j,
						x_actual, y_actual,
						"" if z_command is None else f"{z_command:.6f}",
						z_actual,
						"" if value is None else f"{value:.6f}",
					])
					csv_file.flush()

					completed += 1
					emit("point", {
						"i": i, "j": j,
						"x": x_actual, "y": y_actual,
						"z_command": z_command, "z": z_actual,
						"value": value,
						"completed": completed, "total": total,
					})
	except ScanStopped:
		stopped = True
	except Exception as exc:
		emit("error", {"message": str(exc), "csv_path": str(csv_path), "completed": completed, "total": total})
		return

	emit("done", {"stopped": stopped, "csv_path": str(csv_path), "completed": completed, "total": total})
