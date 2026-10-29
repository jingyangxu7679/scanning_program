import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from tkinter import ttk
from tkinter import messagebox

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

import gui_theme
import scan_helpers

#To DO list for the motor control GUI: 1. live updates for the position(ideally in terms of encoder counts and mm), 2. error handling for invalid position input, 3. error handling for move/home errors, 4. display of motor status (enabled/disabled etc)
#automatically connect the moors once launching the GUI program

motor = None
MOTOR_IMPORT_ERROR = None
MOTOR_IO_LOCK = threading.Lock()
# Set while a 2D scan is running; manual Move/Home are blocked so they can't fight the scan.
SCAN_ACTIVE = threading.Event()


MOTOR_CHANNELS = [1, 2, 3]


class MotorPanel(ttk.Frame):
	AXIS_NAMES = {1: "X axis", 2: "Y axis", 3: "Z axis"}

	def __init__(self, parent, channel_num):
		super().__init__(parent, style="Card.TFrame", padding=0)
		self.channel_num = channel_num

		self.status_var = tk.StringVar(value="Status: not queried yet")
		self.current_position_var = tk.StringVar(value="--")
		self.position_var = tk.StringVar()

		self._build_widgets()

	def _build_widgets(self):
		self.columnconfigure(0, weight=1)
		accent = gui_theme.AXIS_COLORS.get(self.channel_num, gui_theme.COLORS["accent"])
		tk.Frame(self, background=accent, height=4).grid(row=0, column=0, sticky="ew")

		body = ttk.Frame(self, padding=(14, 10, 14, 12))
		body.grid(row=1, column=0, sticky="nsew")
		body.columnconfigure(1, weight=1)

		title = ttk.Frame(body)
		title.grid(row=0, column=0, columnspan=3, sticky="ew")
		title.columnconfigure(1, weight=1)
		ttk.Label(title, text=self.AXIS_NAMES.get(self.channel_num, f"Motor {self.channel_num}"),
				  style="H2.TLabel", foreground=accent).grid(row=0, column=0, sticky="w")
		ttk.Label(title, text=f"  Channel {self.channel_num}", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
		refresh_btn = ttk.Button(title, text="⟳ Refresh", command=self.refresh_status)
		refresh_btn.grid(row=0, column=2, sticky="e")
		gui_theme.Tooltip(refresh_btn, "Query the controller for enabled state, device id and position.")

		readout = ttk.Frame(body, style="Readout.TFrame")
		readout.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 8))
		readout.columnconfigure(0, weight=1)
		ttk.Label(readout, textvariable=self.current_position_var, style="Readout.TLabel").grid(row=0, column=0, sticky="ew")
		ttk.Label(readout, text=gui_theme.UNIT, style="ReadoutUnit.TLabel").grid(row=0, column=1, sticky="se", pady=(0, 8))

		ttk.Label(body, text="Target").grid(row=2, column=0, sticky="w", padx=(0, 8))
		target_entry = ttk.Entry(body, textvariable=self.position_var, width=10)
		target_entry.grid(row=2, column=1, sticky="ew")
		target_entry.bind("<Return>", lambda _e: self.move_to_position())
		ttk.Label(body, text=gui_theme.UNIT, style="Muted.TLabel").grid(row=2, column=2, sticky="w", padx=(6, 0))

		buttons = ttk.Frame(body)
		buttons.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
		buttons.columnconfigure(0, weight=3)
		buttons.columnconfigure(1, weight=2)
		ttk.Button(buttons, text="Move", style="Accent.TButton", command=self.move_to_position).grid(
			row=0, column=0, sticky="ew", padx=(0, 6)
		)
		home_btn = ttk.Button(buttons, text="⌂ Home", command=self.home_motor)
		home_btn.grid(row=0, column=1, sticky="ew")
		gui_theme.Tooltip(home_btn, "Run the controller's homing sequence for this axis.")

		self._status_label = ttk.Label(body, textvariable=self.status_var, style="Status.TLabel",
									   wraplength=420, justify="left", font=gui_theme.FONTS["small"])
		self._status_label.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))

	def _set_status(self, msg):
		self.status_var.set(msg)
		self._status_label.configure(style=gui_theme.status_style(msg))

	def _set_displayed_position(self, position):
		if position is None:
			self.current_position_var.set("--")
			return
		try:
			self.current_position_var.set(f"{float(str(position)):.4f}")
		except ValueError:
			self.current_position_var.set(str(position))

	def _query_motor_position(self):
		# motor_position currently requires a second arg; use 0 as placeholder when querying.
		with MOTOR_IO_LOCK:
			return motor.motor_position(self.channel_num, 0)

	def refresh_status(self):
		if motor is None:
			self._set_status(f"Status: motor library unavailable - {MOTOR_IMPORT_ERROR}")
			return

		self._set_status("Status: querying...")

		def worker():
			try:
				with MOTOR_IO_LOCK:
					info = motor.return_motor_info(self.channel_num)
				position = self._query_motor_position()
				msg = (
					f"Status: enabled={info.get('is_enabled')} | "
					f"position={position} | "
					f"id={info.get('device_id')}"
				)
				self.after(0, lambda: self._set_displayed_position(position))
			except Exception as exc:
				msg = f"Status: error - {exc}"
			self.after(0, lambda: self._set_status(msg))

		threading.Thread(target=worker, daemon=True).start()

	def move_to_position(self):
		if motor is None:
			self._set_status(f"Status: motor library unavailable - {MOTOR_IMPORT_ERROR}")
			return
		if SCAN_ACTIVE.is_set():
			self._set_status("Status: scan in progress - stop the scan before moving manually.")
			return

		raw_value = (self.position_var.get().strip())#currently this input is in mm, but motor moves the input value/10
		print(f"Debug: raw position input='{raw_value}'")
		try:
			position = float(raw_value)
		except ValueError:
			self._set_status(f"Status: invalid position '{raw_value}'")
			return

		self._set_status(f"Status: moving to {position}...")

		def worker():
			try:
				with MOTOR_IO_LOCK:
					motor.connect_and_move("", self.channel_num, position)
				final_pos = self._query_motor_position()
				msg = f"Status: moved to target={position} | reported={final_pos}"
				self.after(0, lambda: self._set_displayed_position(final_pos))
			except Exception as exc:
				msg = f"Status: move error - {exc}"
			self.after(0, lambda: self._set_status(msg))

		threading.Thread(target=worker, daemon=True).start()

	def home_motor(self):
		if motor is None:
			self._set_status(f"Status: motor library unavailable - {MOTOR_IMPORT_ERROR}")
			return
		if SCAN_ACTIVE.is_set():
			self._set_status("Status: scan in progress - stop the scan before homing.")
			return

		self._set_status("Status: homing...")

		def worker():
			try:
				with MOTOR_IO_LOCK:
					motor.home_motor(self.channel_num)
				position = self._query_motor_position()
				msg = f"Status: homing complete | reported={position}"
				self.after(0, lambda: self._set_displayed_position(position))
			except Exception as exc:
				msg = f"Status: homing error - {exc}"
			self.after(0, lambda: self._set_status(msg))

		threading.Thread(target=worker, daemon=True).start()


class ScanPanel(ttk.Frame):
	"""X/Y raster scan with live maps and user-defined z = f(x, y) focus compensation."""

	def __init__(self, parent, get_current_positions):
		super().__init__(parent, style="Card.TFrame", padding=(16, 12, 16, 12))
		self._get_current_positions = get_current_positions
		self._events = queue.Queue()
		self._stop_event = threading.Event()
		self._scan_thread = None
		self._x_positions = []
		self._y_positions = []

		self.status_var = tk.StringVar(value="Scan status: idle")
		self.grid_info_var = tk.StringVar(value="")
		self.x_start_var = tk.StringVar(value="0")
		self.x_stop_var = tk.StringVar(value="0.2")
		self.x_step_var = tk.StringVar(value="0.01")
		self.y_start_var = tk.StringVar(value="0")
		self.y_stop_var = tk.StringVar(value="0.1")
		self.y_step_var = tk.StringVar(value="0.01")
		self.dwell_var = tk.StringVar(value="1")
		self.zigzag_var = tk.BooleanVar(value=True)
		self.z_enabled_var = tk.BooleanVar(value=True)
		self.show_z_map_var = tk.BooleanVar(value=True)
		self.z_every_n_var = tk.StringVar(value="1")
		self.z_max_dev_var = tk.StringVar(value="0.1")
		self.acquire_var = tk.BooleanVar(value=False)
		self.data_dir_var = tk.StringVar(value=str(scan_helpers.DEFAULT_KEYSIGHT_DATA_DIR))
		self.output_dir_var = tk.StringVar(value=str(scan_helpers.DEFAULT_OUTPUT_DIR))
		self.file_name_var = tk.StringVar(value=f"scan_{datetime.now():%Y%m%d}_1")
		self.output_preview_var = tk.StringVar(value="")

		self._build_widgets()
		self._build_plot()

		for var in (self.x_start_var, self.x_stop_var, self.x_step_var,
					self.y_start_var, self.y_stop_var, self.y_step_var):
			var.trace_add("write", lambda *_: self._update_grid_info())
		self._update_grid_info()
		for var in (self.output_dir_var, self.file_name_var):
			var.trace_add("write", lambda *_: self._update_output_preview())
		self._update_output_preview()
		self.z_enabled_var.trace_add("write", lambda *_: self._update_z_enabled_state())
		self._update_z_enabled_state()

		self.after(100, self._process_events)

	# ------------------------------------------------------------------ UI

	def _build_widgets(self):
		self.columnconfigure(1, weight=1)
		self.rowconfigure(1, weight=1)

		header = ttk.Frame(self)
		header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
		ttk.Label(header, text="2D Scan", style="H2.TLabel").grid(row=0, column=0, sticky="w")
		ttk.Label(header, text="   X/Y raster with live maps and z = f(x, y) focus compensation",
				  style="Muted.TLabel").grid(row=0, column=1, sticky="w")

		left = ttk.Frame(self)
		left.grid(row=1, column=0, sticky="nsew", padx=(0, 18))
		left.columnconfigure(0, weight=1)
		left.rowconfigure(0, weight=1)

		self.notebook = ttk.Notebook(left)
		self.notebook.grid(row=0, column=0, sticky="nsew")
		area_tab = ttk.Frame(self.notebook, padding=(14, 12))
		z_tab = ttk.Frame(self.notebook, padding=(14, 12))
		out_tab = ttk.Frame(self.notebook, padding=(14, 12))
		self.notebook.add(area_tab, text="  Scan area  ")
		self.notebook.add(z_tab, text="  Z focus  ")
		self.notebook.add(out_tab, text="  Data & output  ")

		self._build_area_tab(area_tab)
		self._build_z_tab(z_tab)
		self._build_output_tab(out_tab)

		subtle = gui_theme.COLORS["subtle"]
		summary = ttk.Frame(left, style="Readout.TFrame", padding=(12, 8))
		summary.grid(row=1, column=0, sticky="ew", pady=(10, 0))
		summary.columnconfigure(0, weight=1)
		ttk.Label(summary, textvariable=self.grid_info_var, style="Bold.TLabel", background=subtle).grid(
			row=0, column=0, sticky="w"
		)
		self._output_preview_label = ttk.Label(
			summary, textvariable=self.output_preview_var, style="Muted.TLabel", background=subtle,
			wraplength=430, justify="left",
		)
		self._output_preview_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))

	def _build_area_tab(self, tab):
		for col in (1, 2, 3):
			tab.columnconfigure(col, weight=1, uniform="xy")

		for col, text in enumerate(("Start", "Stop", "Step"), start=1):
			ttk.Label(tab, text=text, style="Muted.TLabel").grid(row=0, column=col, sticky="w", padx=3)

		for row, (axis, channel, start, stop, step) in enumerate((
			("X", 1, self.x_start_var, self.x_stop_var, self.x_step_var),
			("Y", 2, self.y_start_var, self.y_stop_var, self.y_step_var),
		), start=1):
			ttk.Label(tab, text=axis, style="H2.TLabel", foreground=gui_theme.AXIS_COLORS[channel]).grid(
				row=row, column=0, sticky="w", padx=(0, 10)
			)
			for col, var in enumerate((start, stop, step), start=1):
				ttk.Entry(tab, textvariable=var, width=9).grid(row=row, column=col, sticky="ew", padx=3, pady=3)
		ttk.Label(tab, text=f"All positions in {gui_theme.UNIT}", style="Muted.TLabel").grid(
			row=3, column=1, columnspan=3, sticky="w", padx=3
		)

		self.use_current_btn = ttk.Button(tab, text="⤓  Use current X/Y as start", command=self.use_current_as_start)
		self.use_current_btn.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 0))
		gui_theme.Tooltip(self.use_current_btn, "Reads the stage's X/Y position now and copies it into the Start fields.")

		ttk.Separator(tab).grid(row=5, column=0, columnspan=4, sticky="ew", pady=12)

		ttk.Label(tab, text="Dwell per point").grid(row=6, column=0, columnspan=2, sticky="w")
		dwell = ttk.Frame(tab)
		dwell.grid(row=6, column=2, columnspan=2, sticky="w")
		ttk.Entry(dwell, textvariable=self.dwell_var, width=8).grid(row=0, column=0, padx=3)
		ttk.Label(dwell, text="s", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
		ttk.Checkbutton(tab, text="Zigzag (alternate X direction each row)", variable=self.zigzag_var).grid(
			row=7, column=0, columnspan=4, sticky="w", pady=(8, 0)
		)

	def _build_z_tab(self, tab):
		tab.columnconfigure(1, weight=1)
		tab.rowconfigure(5, weight=1)
		ttk.Checkbutton(tab, text="Enable z focus compensation", variable=self.z_enabled_var).grid(
			row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
		)
		ttk.Label(tab, text="Adjust z every N x points").grid(row=1, column=0, sticky="w")
		ttk.Entry(tab, textvariable=self.z_every_n_var, width=8).grid(row=1, column=1, sticky="w", padx=6, pady=2)
		ttk.Label(tab, text="Max |z − z0| (safety)").grid(row=2, column=0, sticky="w")
		ttk.Entry(tab, textvariable=self.z_max_dev_var, width=8).grid(row=2, column=1, sticky="w", padx=6, pady=2)
		ttk.Label(tab, text=gui_theme.UNIT, style="Muted.TLabel").grid(row=2, column=2, sticky="w")

		expr_header = ttk.Frame(tab)
		expr_header.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
		expr_header.columnconfigure(1, weight=1)
		ttk.Label(expr_header, text="z = f(x, y)", style="Bold.TLabel").grid(row=0, column=0, sticky="w")
		ttk.Button(expr_header, text="? Help", command=lambda: messagebox.showinfo(
			"z = f(x, y) help", scan_helpers.Z_EXPRESSION_HELP, parent=self)).grid(row=0, column=2, sticky="e")
		ttk.Label(tab, text="Variables: x, y, x0, y0, z0, dx, dy  (result is absolute z)", style="Muted.TLabel").grid(
			row=4, column=0, columnspan=3, sticky="w", pady=(0, 4)
		)

		text_frame = ttk.Frame(tab)
		text_frame.grid(row=5, column=0, columnspan=3, sticky="nsew")
		text_frame.columnconfigure(0, weight=1)
		text_frame.rowconfigure(0, weight=1)
		self.z_text = tk.Text(text_frame, height=6, width=50, wrap="none", undo=True)
		gui_theme.style_text_widget(self.z_text)
		self.z_text.grid(row=0, column=0, sticky="nsew")
		z_scroll = ttk.Scrollbar(text_frame, orient="horizontal", command=self.z_text.xview)
		z_scroll.grid(row=1, column=0, sticky="ew")
		self.z_text.configure(xscrollcommand=z_scroll.set)
		self.z_text.insert("1.0", scan_helpers.DEFAULT_Z_EXPRESSION)

		z_buttons = ttk.Frame(tab)
		z_buttons.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))
		for col in range(3):
			z_buttons.columnconfigure(col, weight=1, uniform="zb")
		ttk.Button(z_buttons, text="Load 1064 map", command=self._load_1064_example).grid(row=0, column=0, sticky="ew")
		ttk.Button(z_buttons, text="Constant z", command=self._load_default_expression).grid(
			row=0, column=1, sticky="ew", padx=6
		)
		ttk.Button(z_buttons, text="Preview Z map", style="Accent.TButton", command=self.preview_z).grid(
			row=0, column=2, sticky="ew"
		)

	def _build_output_tab(self, tab):
		tab.columnconfigure(1, weight=1)
		ttk.Label(tab, text="Measurement", style="Bold.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
		ttk.Checkbutton(tab, text="Capture Keysight EXA trace + peak frequency at each point",
						variable=self.acquire_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 4))
		ttk.Label(tab, text="Trace folder").grid(row=2, column=0, sticky="w")
		ttk.Entry(tab, textvariable=self.data_dir_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0))

		ttk.Separator(tab).grid(row=3, column=0, columnspan=3, sticky="ew", pady=14)

		ttk.Label(tab, text="Output file", style="Bold.TLabel").grid(row=4, column=0, columnspan=3, sticky="w")
		ttk.Label(tab, text="Save folder").grid(row=5, column=0, sticky="w", pady=(6, 0))
		ttk.Entry(tab, textvariable=self.output_dir_var).grid(row=5, column=1, sticky="ew", padx=8, pady=(6, 0))
		ttk.Button(tab, text="Browse…", command=self.browse_output_dir).grid(row=5, column=2, sticky="e", pady=(6, 0))
		ttk.Label(tab, text="File name").grid(row=6, column=0, sticky="w", pady=(6, 0))
		ttk.Entry(tab, textvariable=self.file_name_var).grid(row=6, column=1, sticky="ew", padx=8, pady=(6, 0))
		ttk.Label(tab, text=".csv / .png", style="Muted.TLabel").grid(row=6, column=2, sticky="w", pady=(6, 0))

	def _build_plot(self):
		plot_frame = ttk.Frame(self)
		plot_frame.grid(row=1, column=1, sticky="nsew")
		plot_frame.columnconfigure(0, weight=1)
		plot_frame.rowconfigure(1, weight=1)

		ttk.Checkbutton(
			plot_frame, text="Show Z-position map", variable=self.show_z_map_var,
			command=self._draw_maps,
		).grid(row=0, column=0, sticky="w", pady=(0, 4))

		self.figure = Figure(figsize=(8, 4.5), dpi=100, facecolor=gui_theme.COLORS["card"],
							 layout="constrained")
		self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
		self.canvas.get_tk_widget().configure(background=gui_theme.COLORS["card"], highlightthickness=0)
		self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
		toolbar = NavigationToolbar2Tk(self.canvas, plot_frame, pack_toolbar=False)
		toolbar.update()
		gui_theme.style_mpl_toolbar(toolbar)
		toolbar.grid(row=2, column=0, sticky="ew")

		# Run bar spans the whole card so Start/Stop stay visible on smaller screens.
		ttk.Separator(self).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 10))
		controls = ttk.Frame(self)
		controls.grid(row=3, column=0, columnspan=2, sticky="ew")
		controls.columnconfigure(2, weight=1)
		self.start_btn = ttk.Button(controls, text="▶  Start scan", style="Success.TButton", width=16,
									command=self.start_scan)
		self.start_btn.grid(row=0, column=0, sticky="w", padx=(0, 8))
		self.stop_btn = ttk.Button(controls, text="■  Stop", style="Danger.TButton", width=12,
								   command=self.request_stop, state="disabled")
		self.stop_btn.grid(row=0, column=1, sticky="w", padx=(0, 14))
		self.progress = ttk.Progressbar(controls, mode="determinate")
		self.progress.grid(row=0, column=2, sticky="ew")
		self._status_label = ttk.Label(controls, textvariable=self.status_var, style="Status.TLabel",
									   wraplength=1400, justify="left")
		self._status_label.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))

		self._init_maps([0.0], [0.0], "Z position", "Peak frequency (Hz)")

	def _init_maps(self, x_positions, y_positions, z_title, value_title):
		self._x_positions = list(x_positions)
		self._y_positions = list(y_positions)
		shape = (len(self._y_positions), len(self._x_positions))
		self._z_grid = np.full(shape, np.nan)
		self._v_grid = np.full(shape, np.nan)
		self._map_titles = (z_title, value_title)
		self._draw_maps(preserve_marker=False)

	def _draw_maps(self, preserve_marker=True):
		"""Reflow the maps without resetting scan data or the current-point marker."""
		marker_data = ([], [])
		if preserve_marker and getattr(self, "_v_marker", None) is not None:
			marker_data = self._v_marker.get_data()
		self.figure.clf()
		self.ax_z = None
		self._z_image = None
		self._z_marker = None
		if self.show_z_map_var.get():
			self.ax_z, self.ax_v = self.figure.subplots(1, 2)
		else:
			self.ax_v = self.figure.subplots()
		extent = _grid_extent(self._x_positions, self._y_positions)
		z_title, value_title = self._map_titles
		if self.ax_z is not None:
			self._z_image = self._make_map(self.ax_z, self._z_grid, extent, z_title, f"Z position ({gui_theme.UNIT})")
			self._refresh_image(self._z_image, self._z_grid)
			self._z_marker, = self.ax_z.plot(*marker_data, "rx", markersize=10, markeredgewidth=2)
		self._v_image = self._make_map(self.ax_v, self._v_grid, extent, value_title, "Peak frequency (Hz)")
		self._refresh_image(self._v_image, self._v_grid)
		self._v_marker, = self.ax_v.plot(*marker_data, "rx", markersize=10, markeredgewidth=2)
		if self.canvas.toolbar is not None:
			self.canvas.toolbar.update()
		self.canvas.draw_idle()

	def _make_map(self, ax, grid, extent, title, cbar_label):
		# Same orientation as the Move_2D_1064 live grid: X increases to the left, Y top to bottom.
		colors = gui_theme.COLORS
		image = ax.imshow(grid, extent=extent, origin="upper", aspect="auto", cmap="viridis", interpolation="nearest")
		ax.invert_xaxis()
		ax.set_facecolor(colors["subtle"])
		ax.set_xlabel("X position", fontsize=9, color=colors["muted"])
		ax.set_ylabel("Y position", fontsize=9, color=colors["muted"])
		ax.set_title(title, fontsize=11, fontweight="bold", color=colors["text"], loc="left", pad=8)
		ax.tick_params(labelsize=8, colors=colors["muted"])
		for spine in ax.spines.values():
			spine.set_color(colors["border"])
		cbar = self.figure.colorbar(image, ax=ax)
		cbar.set_label(cbar_label, fontsize=8, color=colors["muted"])
		cbar.ax.tick_params(labelsize=8, colors=colors["muted"])
		cbar.outline.set_edgecolor(colors["border"])
		cbar.formatter.set_useOffset(False)
		return image

	@staticmethod
	def _refresh_image(image, grid):
		if image is None:
			return
		image.set_data(grid)
		finite = grid[np.isfinite(grid)]
		if finite.size:
			vmin, vmax = float(finite.min()), float(finite.max())
			if vmin == vmax:
				pad = abs(vmin) * 1e-6 or 1e-6
				vmin, vmax = vmin - pad, vmax + pad
			image.set_clim(vmin=vmin, vmax=vmax)

	def _set_status(self, msg):
		self.status_var.set(msg)
		self._status_label.configure(style=gui_theme.status_style(msg))

	def _replace_z_text(self, text):
		self.z_text.configure(state="normal")
		self.z_text.delete("1.0", "end")
		self.z_text.insert("1.0", text)
		self._update_z_enabled_state()

	def _update_z_enabled_state(self):
		enabled = self.z_enabled_var.get()
		colors = gui_theme.COLORS
		self.z_text.configure(
			state="normal" if enabled else "disabled",
			foreground=colors["text"] if enabled else colors["disabled_fg"],
			background="#fbfcfe" if enabled else colors["subtle"],
		)

	def _load_1064_example(self):
		self._replace_z_text(scan_helpers.MOVE_2D_1064_Z_EXPRESSION)

	def _load_default_expression(self):
		self._replace_z_text(scan_helpers.DEFAULT_Z_EXPRESSION)

	def _update_grid_info(self):
		try:
			xs, ys = self._read_grid()
			self.grid_info_var.set(f"Grid: {len(xs)} (X) x {len(ys)} (Y) = {len(xs) * len(ys)} points")
		except ValueError as exc:
			self.grid_info_var.set(f"Grid: {exc}")

	def use_current_as_start(self):
		"""Read X/Y straight from the controller and copy them into the X/Y start fields."""
		if motor is None:
			self._set_status(f"Scan status: motor library unavailable - {MOTOR_IMPORT_ERROR}")
			return
		self.use_current_btn.configure(state="disabled")
		self._set_status("Scan status: reading current X/Y position...")

		def apply(x, y, note=""):
			self.use_current_btn.configure(state="normal")
			self.x_start_var.set(f"{x:.6g}")
			self.y_start_var.set(f"{y:.6g}")
			self._set_status(f"Scan status: start set to current position X={x:.6g}, Y={y:.6g}{note}.")

		def fail(exc):
			self.use_current_btn.configure(state="normal")
			self._set_status(f"Scan status: could not read current X/Y position - {exc}")

		def worker():
			try:
				# Bounded wait so a long in-progress move doesn't hang the button.
				if not MOTOR_IO_LOCK.acquire(timeout=5):
					raise TimeoutError("controller busy")
				try:
					x = float(str(motor.motor_position(1, 0)))
					y = float(str(motor.motor_position(2, 0)))
				finally:
					MOTOR_IO_LOCK.release()
				self.after(0, lambda: apply(x, y))
			except Exception as exc:
				polled = self._get_current_positions()
				if 1 in polled and 2 in polled:
					self.after(0, lambda: apply(polled[1], polled[2], f" (last polled value; live read failed: {exc})"))
				else:
					self.after(0, lambda: fail(exc))

		threading.Thread(target=worker, daemon=True).start()

	def browse_output_dir(self):
		initial = self.output_dir_var.get().strip()
		folder = filedialog.askdirectory(
			parent=self, title="Choose folder for scan files",
			initialdir=initial if Path(initial).is_dir() else str(Path.home()),
		)
		if folder:
			self.output_dir_var.set(str(Path(folder)))

	def _read_output_target(self):
		folder = self.output_dir_var.get().strip()
		if not folder:
			raise ValueError("save folder is empty")
		folder_path = Path(folder).expanduser()
		if folder_path.exists() and not folder_path.is_dir():
			raise ValueError(f"save folder '{folder_path}' is a file, not a folder")
		return folder_path, scan_helpers.clean_file_stem(self.file_name_var.get())

	def _update_output_preview(self):
		try:
			folder, stem = self._read_output_target()
		except ValueError as exc:
			self.output_preview_var.set(f"Invalid: {exc}")
			self._output_preview_label.configure(style="Error.TLabel")
			return
		exists = bool(scan_helpers.existing_output_files(folder, stem))
		note = "  ⚠ already exists" if exists else ""
		self.output_preview_var.set(f"Saves to: {folder / stem}.csv / .png{note}")
		self._output_preview_label.configure(style="Warn.TLabel" if exists else "Muted.TLabel")

	def _confirm_output_target(self, folder, stem):
		"""Return the file stem to use, or None if the user cancels because the name is taken."""
		existing = scan_helpers.existing_output_files(folder, stem)
		if not existing:
			return stem
		alternative = scan_helpers.next_free_stem(folder, stem)
		answer = messagebox.askyesnocancel(
			"File name already used",
			f"A scan named '{stem}' already exists in:\n{folder}\n\n"
			+ "\n".join(f"  - {p.name}" for p in existing)
			+ f"\n\nYes: overwrite the existing file(s)\n"
			f"No: save as '{alternative}' instead\n"
			f"Cancel: don't start the scan",
			icon="warning", default="cancel", parent=self,
		)
		if answer is None:
			return None
		if answer:
			return stem
		self.file_name_var.set(alternative)
		return alternative

	# --------------------------------------------------------------- inputs

	def _read_grid(self):
		values = {}
		for name, var in (("X start", self.x_start_var), ("X stop", self.x_stop_var), ("X step", self.x_step_var),
						  ("Y start", self.y_start_var), ("Y stop", self.y_stop_var), ("Y step", self.y_step_var)):
			try:
				values[name] = float(var.get().strip())
			except ValueError:
				raise ValueError(f"invalid {name} '{var.get()}'") from None
		if values["X step"] <= 0 or values["Y step"] <= 0:
			raise ValueError("X and Y step must be > 0")
		if values["X start"] < 0 or values["X stop"] < 0 or values["Y start"] < 0 or values["Y stop"] < 0:
			raise ValueError("positions must be >= 0")
		xs = scan_helpers.generate_positions(values["X start"], values["X stop"], values["X step"])
		ys = scan_helpers.generate_positions(values["Y start"], values["Y stop"], values["Y step"])
		return xs, ys

	def _read_z_settings(self):
		try:
			every_n = int(self.z_every_n_var.get().strip())
			max_dev = float(self.z_max_dev_var.get().strip())
		except ValueError:
			raise ValueError("'Adjust z every N' must be an integer and 'Max |z - z0|' a number") from None
		if every_n < 1 or max_dev <= 0:
			raise ValueError("'Adjust z every N' must be >= 1 and 'Max |z - z0|' > 0")
		z_func = scan_helpers.ZFunction(self.z_text.get("1.0", "end"))
		return z_func, every_n, max_dev

	def _current_z(self):
		return self._get_current_positions().get(3)

	# -------------------------------------------------------------- actions

	def preview_z(self):
		try:
			xs, ys = self._read_grid()
			z_func, _, max_dev = self._read_z_settings()
		except ValueError as exc:
			self._set_status(f"Preview: {exc}")
			return
		z0 = self._current_z()
		z0_note = ""
		if z0 is None:
			z0, z0_note = 0.0, " (current z unknown, using z0=0)"
		try:
			z_map = scan_helpers.preview_z_map(z_func, xs, ys, z0)
		except ValueError as exc:
			self._set_status(f"Preview: {exc}")
			return
		if self._scan_running():
			self._set_status("Preview: z function is valid (map not drawn while a scan is running).")
			return
		self._init_maps(xs, ys, f"Z preview (z0={z0:.4f})", "Peak frequency (Hz)")
		self._z_grid[:] = z_map
		self._refresh_image(self._z_image, self._z_grid)
		self.canvas.draw_idle()
		dev = float(np.max(np.abs(z_map - z0)))
		warn = f"  WARNING: exceeds max |z - z0| = {max_dev}; scan would abort." if dev > max_dev else ""
		self._set_status(
			f"Preview{z0_note}: z range {z_map.min():.6f} .. {z_map.max():.6f}, max |z - z0| = {dev:.6f}.{warn}"
		)

	def _scan_running(self):
		return self._scan_thread is not None and self._scan_thread.is_alive()

	def start_scan(self):
		if motor is None:
			self._set_status(f"Scan status: motor library unavailable - {MOTOR_IMPORT_ERROR}")
			return
		if self._scan_running():
			self._set_status("Scan status: a scan is already running.")
			return

		try:
			xs, ys = self._read_grid()
			dwell = float(self.dwell_var.get().strip())
			if dwell < 0:
				raise ValueError("dwell must be >= 0")
			z_func, every_n, max_dev = (None, 1, 0.1)
			if self.z_enabled_var.get():
				z_func, every_n, max_dev = self._read_z_settings()
				z0 = self._current_z()
				if z0 is not None:
					z_map = scan_helpers.preview_z_map(z_func, xs, ys, z0)
					dev = float(np.max(np.abs(z_map - z0)))
					if dev > max_dev:
						raise ValueError(
							f"z function moves z by up to {dev:.6f} from z0={z0:.6f}, more than the "
							f"max |z - z0| = {max_dev}. Check the function or raise the limit."
						)
		except ValueError as exc:
			self._set_status(f"Scan status: {exc}")
			return

		try:
			output_dir, file_stem = self._read_output_target()
		except ValueError as exc:
			self._set_status(f"Scan status: output file - {exc}")
			return

		total = len(xs) * len(ys)
		if total > 5000 and not messagebox.askyesno("Large scan", f"This scan has {total} points. Continue?"):
			return

		file_stem = self._confirm_output_target(output_dir, file_stem)
		if file_stem is None:
			self._set_status("Scan status: not started - choose a different file name.")
			return

		config = scan_helpers.ScanConfig(
			x_positions=xs,
			y_positions=ys,
			dwell_s=dwell,
			zigzag=self.zigzag_var.get(),
			z_function=z_func,
			z_every_n=every_n,
			max_z_deviation=max_dev,
			acquire_keysight=self.acquire_var.get(),
			keysight_data_dir=Path(self.data_dir_var.get().strip()),
			output_dir=output_dir,
			file_stem=file_stem,
		)

		self._stop_event.clear()
		SCAN_ACTIVE.set()
		self.start_btn.configure(state="disabled")
		self.stop_btn.configure(state="normal")
		self.progress.configure(maximum=total, value=0)
		self._set_status(f"Scan status: starting {len(xs)} x {len(ys)} = {total} points...")

		def emit(kind, data):
			self._events.put((kind, data))

		def worker():
			try:
				scan_helpers.run_scan(config, motor, MOTOR_IO_LOCK, self._stop_event, emit)
			except Exception as exc:
				emit("error", {"message": str(exc), "csv_path": None, "completed": 0, "total": total})

		self._scan_thread = threading.Thread(target=worker, daemon=True)
		self._scan_thread.start()

	def request_stop(self):
		if self._scan_running():
			self._stop_event.set()
			self._set_status("Scan status: stopping after the current move...")

	# ------------------------------------------------------ live updates

	def _process_events(self):
		redraw = False
		try:
			while True:
				kind, data = self._events.get_nowait()
				redraw |= self._handle_event(kind, data)
		except queue.Empty:
			pass
		if redraw:
			self.canvas.draw_idle()
		self.after(100, self._process_events)

	def _handle_event(self, kind, data):
		if kind == "start":
			z_title = "Z position (compensated)" if data["z_enabled"] else "Z position (fixed)"
			v_title = "Peak frequency (Hz)" if data["acquire"] else "Peak frequency (measurement off)"
			self._init_maps(data["x_positions"], data["y_positions"], z_title, v_title)
			self._set_status(f"Scan status: running, z0={data['z0']:.6f}, logging to {data['csv_path']}")
			return False

		if kind == "point":
			i, j = data["i"], data["j"]
			self._z_grid[j, i] = data["z"]
			self._refresh_image(self._z_image, self._z_grid)
			if data["value"] is not None:
				self._v_grid[j, i] = data["value"]
				self._refresh_image(self._v_image, self._v_grid)
			cx, cy = [self._x_positions[i]], [self._y_positions[j]]
			if self._z_marker is not None:
				self._z_marker.set_data(cx, cy)
			self._v_marker.set_data(cx, cy)
			self.progress.configure(value=data["completed"])
			z_cmd = "" if data["z_command"] is None else f" (cmd {data['z_command']:.6f})"
			value = "" if data["value"] is None else f", peak={data['value']:.1f} Hz"
			self._set_status(
				f"Scan status: point {data['completed']}/{data['total']}  "
				f"x={data['x']:.6f}, y={data['y']:.6f}, z={data['z']:.6f}{z_cmd}{value}"
			)
			return True

		if kind == "warning":
			print(f"[scan] {data['message']}")
			self._set_status(f"Scan status: {data['message']}")
			return False

		if kind in ("done", "error"):
			SCAN_ACTIVE.clear()
			self.start_btn.configure(state="normal")
			self.stop_btn.configure(state="disabled")
			if self._z_marker is not None:
				self._z_marker.set_data([], [])
			self._v_marker.set_data([], [])
			saved = ""
			csv_path = data.get("csv_path")
			if csv_path and data.get("completed"):
				png_path = Path(csv_path).with_suffix(".png")
				try:
					self.figure.savefig(png_path, dpi=200)
					saved = f" Saved {csv_path} and {png_path.name}."
				except Exception as exc:
					saved = f" Saved {csv_path} (figure save failed: {exc})."
			progress = f"{data.get('completed', 0)}/{data.get('total', 0)} points"
			self._update_output_preview()
			if kind == "error":
				self._set_status(f"Scan status: error after {progress} - {data['message']}.{saved}")
			elif data["stopped"]:
				self._set_status(f"Scan status: stopped by user after {progress}.{saved}")
			else:
				self._set_status(f"Scan status: completed {progress}.{saved}")
			return True

		return False


def _grid_extent(x_positions, y_positions):
	"""imshow extent so each cell is centered on its stage position (row 0 = first y at the top)."""

	def half_step(positions):
		return (positions[1] - positions[0]) / 2 if len(positions) > 1 else 0.005

	hx, hy = half_step(x_positions), half_step(y_positions)
	return [x_positions[0] - hx, x_positions[-1] + hx, y_positions[-1] + hy, y_positions[0] - hy]


def _load_motor_module():
	global motor
	global MOTOR_IMPORT_ERROR

	try:
		import basic_motor_control as motor_module
		motor = motor_module
		MOTOR_IMPORT_ERROR = None
		return True
	except Exception as exc:
		motor = None
		MOTOR_IMPORT_ERROR = str(exc)
		return False

def build_gui():
	root = tk.Tk()
	root.title("Motor Control & 2D Scan")
	gui_theme.apply_theme(root)
	num_channels = len(MOTOR_CHANNELS)
	window_width = max(1400, 360 * num_channels)
	root.geometry(f"{window_width}x940+0+0")
	root.minsize(1100, 800)
	try:
		root.state("zoomed")  # Windows: start maximized so the scan panel and plots fit
	except tk.TclError:
		pass

	header = ttk.Frame(root, style="Header.TFrame", padding=(20, 12))
	container = ttk.Frame(root, style="App.TFrame", padding=(14, 12, 14, 12))
	header.pack(fill="x")
	container.pack(fill="both", expand=True)
	container.rowconfigure(2, weight=1)

	motor_loaded = _load_motor_module()
	if motor_loaded:
		connection_ok = motor.connect_to_all_channels(MOTOR_CHANNELS)
		startup_msg = (
			f"Startup: connected to serial check for channels {MOTOR_CHANNELS}"
			if connection_ok
			else "Startup: motor connection failed. Check controller serial number and Kinesis installation."
		)
	else:
		connection_ok = False
		startup_msg = (
			"Startup: failed to load motor control library. "
			f"Details: {MOTOR_IMPORT_ERROR}"
		)
	header.columnconfigure(1, weight=1)
	ttk.Label(header, text="Motor Control & 2D Scan", style="HeaderTitle.TLabel").grid(row=0, column=0, sticky="w")
	ttk.Label(header, text="Thorlabs BSC20x  ·  channels " + ", ".join(str(c) for c in MOTOR_CHANNELS),
			  style="HeaderSub.TLabel").grid(row=1, column=0, sticky="w")
	ttk.Label(header, text=startup_msg.removeprefix("Startup: "), style="HeaderSub.TLabel",
			  wraplength=700, justify="right").grid(row=0, column=1, rowspan=2, sticky="e", padx=(20, 14))
	pill = ttk.Label(header, text="●  Connected" if connection_ok else "●  Not connected",
					 style="PillOK.TLabel" if connection_ok else "PillBad.TLabel")
	pill.grid(row=0, column=2, rowspan=2, sticky="e")
	if not connection_ok:
		messagebox.showwarning("Motor Connection", startup_msg)

	for i in range(num_channels):
		container.columnconfigure(i, weight=1, uniform="axis")

	panels = []
	panel_by_channel = {}
	for idx, channel in enumerate(MOTOR_CHANNELS):
		panel = MotorPanel(container, channel)
		left_pad = 0 if idx == 0 else 6
		right_pad = 0 if idx == num_channels - 1 else 6
		panel.grid(row=1, column=idx, sticky="nsew", padx=(left_pad, right_pad))
		panels.append(panel)
		panel_by_channel[channel] = panel

	# Latest polled positions as floats, keyed by channel (used by the scan panel).
	last_positions = {}

	scan_panel = ScanPanel(container, get_current_positions=lambda: dict(last_positions))
	scan_panel.grid(row=2, column=0, columnspan=num_channels, sticky="nsew", pady=(12, 0))

	for panel in panels:
		panel.refresh_status()

	stop_polling_event = threading.Event()

	def position_poller_worker():
		while not stop_polling_event.is_set():
			if motor is not None:
				try:
					with MOTOR_IO_LOCK:
						positions = {
							channel_num: motor.motor_position(channel_num, 0)
							for channel_num in MOTOR_CHANNELS
						}

					def apply_positions(data=positions):
						for channel_num, position in data.items():
							try:
								last_positions[channel_num] = float(str(position))
							except ValueError:
								pass
							panel = panel_by_channel.get(channel_num)
							if panel is not None:
								panel._set_displayed_position(position)

					root.after(0, apply_positions)
				except Exception:
					# Keep poller resilient; operational buttons expose detailed errors.
					pass
			stop_polling_event.wait(0.5)

	threading.Thread(target=position_poller_worker, daemon=True).start()

	def on_close():
		if scan_panel._scan_running():
			if not messagebox.askyesno("Scan running", "A scan is running. Stop it and quit?"):
				return
			scan_panel.request_stop()
			# Let the current move finish so we don't disconnect mid-move.
			scan_panel._scan_thread.join(timeout=65)
		stop_polling_event.set()
		if motor is not None:
			try:
				motor.disconnect_all_channels()
			except Exception as exc:
				print(f"Disconnect warning: {exc}")
		root.destroy()

	root.protocol("WM_DELETE_WINDOW", on_close)

	return root
#next step is to configure the motors to move in loops with given step size and parameters


if __name__ == "__main__":
	app = build_gui()
	app.mainloop()
