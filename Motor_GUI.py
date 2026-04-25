import threading
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

#To DO list for the motor control GUI: 1. live updates for the position(ideally in terms of encoder counts and mm), 2. error handling for invalid position input, 3. error handling for move/home errors, 4. display of motor status (enabled/disabled etc)
#automatically connect the moors once launching the GUI program

motor = None
MOTOR_IMPORT_ERROR = None
MOTOR_IO_LOCK = threading.Lock()


MOTOR_CHANNELS = [1, 2, 3]


class MotorPanel(ttk.LabelFrame):
	def __init__(self, parent, channel_num):
		title_by_channel = {
			1: "X-axis control(Channel 1)",
			2: "Y axis control(Channel 2)",
			3: "Z axis control(Channel 3)",
		}
		panel_title = title_by_channel.get(channel_num, f"Motor Channel {channel_num}")
		super().__init__(parent, text=panel_title, padding=10)
		self.channel_num = channel_num

		self.status_var = tk.StringVar(value="Status: not queried yet")
		self.current_position_var = tk.StringVar(value="--")
		self.position_var = tk.StringVar()

		self._build_widgets()

	def _build_widgets(self):
		self.columnconfigure(0, weight=1)
		self.columnconfigure(1, weight=1)

		status_label = ttk.Label(self, textvariable=self.status_var, wraplength=400, justify="left")
		status_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

		refresh_btn = ttk.Button(self, text="Refresh Status", command=self.refresh_status)
		refresh_btn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

		ttk.Label(self, text="Current position").grid(row=2, column=0, sticky="w")
		current_position_frame = ttk.Frame(self)
		current_position_frame.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(0, 6))
		current_position_frame.columnconfigure(0, weight=1)

		current_position_entry = ttk.Entry(current_position_frame, textvariable=self.current_position_var, state="readonly")
		current_position_entry.grid(row=0, column=0, sticky="ew")
		ttk.Label(current_position_frame, text="*10^-1 mm").grid(row=0, column=1, sticky="w", padx=(6, 0))

		ttk.Label(self, text="Target position").grid(row=3, column=0, sticky="w")
		position_frame = ttk.Frame(self)
		position_frame.grid(row=3, column=1, sticky="ew", padx=(8, 0))
		position_frame.columnconfigure(0, weight=1)

		ttk.Entry(position_frame, textvariable=self.position_var).grid(row=0, column=0, sticky="ew")
		ttk.Label(position_frame, text="*10^-1 mm").grid(row=0, column=1, sticky="w", padx=(6, 0))

		move_btn = ttk.Button(self, text="Move", command=self.move_to_position)
		move_btn.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 10))

		home_btn = ttk.Button(self, text="Home", command=self.home_motor)
		home_btn.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))

	def _set_status(self, msg):
		self.status_var.set(msg)

	def _set_displayed_position(self, position):
		if position is None:
			self.current_position_var.set("--")
			return
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


class ScanPanel(ttk.LabelFrame):
	def __init__(self, parent):
		super().__init__(parent, text="2D/3D Scan", padding=10)

		self.status_var = tk.StringVar(value="Scan status: idle")
		self.x_position_var = tk.StringVar(value="1")
		self.y_position_var = tk.StringVar(value="1")
		self.z_position_var = tk.StringVar(value="1")
		self.x_step_size_var = tk.StringVar(value="1")
		self.y_step_size_var = tk.StringVar(value="1")
		self.z_step_size_var = tk.StringVar(value="1")

		self._build_widgets()

	def _build_widgets(self):
		for i in range(6):
			self.columnconfigure(i, weight=1)

		ttk.Label(self, textvariable=self.status_var, wraplength=900, justify="left").grid(
			row=0, column=0, columnspan=6, sticky="ew", pady=(0, 8)
		)

		ttk.Label(self, text="X Position").grid(row=1, column=0, sticky="w")
		x_pos_frame = ttk.Frame(self)
		x_pos_frame.grid(row=2, column=0, sticky="ew", padx=(0, 8))
		x_pos_frame.columnconfigure(0, weight=1)
		ttk.Entry(x_pos_frame, textvariable=self.x_position_var).grid(row=0, column=0, sticky="ew")
		ttk.Label(x_pos_frame, text="*10^-1 mm").grid(row=0, column=1, sticky="w", padx=(6, 0))

		ttk.Label(self, text="Y Position").grid(row=1, column=1, sticky="w")
		y_pos_frame = ttk.Frame(self)
		y_pos_frame.grid(row=2, column=1, sticky="ew", padx=(0, 8))
		y_pos_frame.columnconfigure(0, weight=1)
		ttk.Entry(y_pos_frame, textvariable=self.y_position_var).grid(row=0, column=0, sticky="ew")
		ttk.Label(y_pos_frame, text="*10^-1 mm").grid(row=0, column=1, sticky="w", padx=(6, 0))

		ttk.Label(self, text="Z Position").grid(row=1, column=2, sticky="w")
		z_pos_frame = ttk.Frame(self)
		z_pos_frame.grid(row=2, column=2, sticky="ew", padx=(0, 8))
		z_pos_frame.columnconfigure(0, weight=1)
		ttk.Entry(z_pos_frame, textvariable=self.z_position_var).grid(row=0, column=0, sticky="ew")
		ttk.Label(z_pos_frame, text="*10^-1 mm").grid(row=0, column=1, sticky="w", padx=(6, 0))

		ttk.Label(self, text="X Step Size").grid(row=1, column=3, sticky="w")
		x_step_frame = ttk.Frame(self)
		x_step_frame.grid(row=2, column=3, sticky="ew", padx=(0, 8))
		x_step_frame.columnconfigure(0, weight=1)
		tk.Entry(x_step_frame, textvariable=self.x_step_size_var).grid(row=0, column=0, sticky="ew")
		ttk.Label(x_step_frame, text="*10^-1 mm").grid(row=0, column=1, sticky="w", padx=(6, 0))

		ttk.Label(self, text="Y Step Size").grid(row=1, column=4, sticky="w")
		y_step_frame = ttk.Frame(self)
		y_step_frame.grid(row=2, column=4, sticky="ew", padx=(0, 8))
		y_step_frame.columnconfigure(0, weight=1)
		tk.Entry(y_step_frame, textvariable=self.y_step_size_var).grid(row=0, column=0, sticky="ew")
		ttk.Label(y_step_frame, text="*10^-1 mm").grid(row=0, column=1, sticky="w", padx=(6, 0))

		ttk.Label(self, text="Z Step Size").grid(row=1, column=5, sticky="w")
		z_step_frame = ttk.Frame(self)
		z_step_frame.grid(row=2, column=5, sticky="ew")
		z_step_frame.columnconfigure(0, weight=1)
		tk.Entry(z_step_frame, textvariable=self.z_step_size_var).grid(row=0, column=0, sticky="ew")
		ttk.Label(z_step_frame, text="*10^-1 mm").grid(row=0, column=1, sticky="w", padx=(6, 0))

		ttk.Button(self, text="Start Scan", command=self.start_scan).grid(
			row=3, column=0, columnspan=6, sticky="ew", pady=(10, 0)
		)

	def _set_status(self, msg):
		self.status_var.set(msg)

	def start_scan(self):
		if motor is None:
			self._set_status(f"Scan status: motor library unavailable - {MOTOR_IMPORT_ERROR}")
			return

		try:
			x_position = float(self.x_position_var.get().strip())
			y_position = float(self.y_position_var.get().strip())
			z_position = float(self.z_position_var.get().strip())
			x_step_size = float(self.x_step_size_var.get().strip())
			y_step_size = float(self.y_step_size_var.get().strip())
			z_step_size = float(self.z_step_size_var.get().strip())
		except ValueError:
			self._set_status("Scan status: invalid input. Use numbers for positions and step sizes.")
			return

		if x_position < 0 or y_position < 0 or z_position < 0:
			self._set_status("Scan status: x_position, y_position, and z_position must be >= 0.")
			return

		if x_step_size <= 0 or y_step_size <= 0 or z_step_size <= 0:
			self._set_status("Scan status: x_step_size, y_step_size, and z_step_size must be > 0.")
			return

		self._set_status(
			f"Scan status: running x={x_position}, y={y_position}, z={z_position}, "
			f"x_step={x_step_size}, y_step={y_step_size}, z_step={z_step_size}..."
		)

		def worker():
			try:
				with MOTOR_IO_LOCK:
					motor.scan(x_position, y_position, z_position, x_step_size, y_step_size, z_step_size)
				msg = "Scan status: completed"
			except Exception as exc:
				msg = f"Scan status: error - {exc}"
			self.after(0, lambda: self._set_status(msg))

		threading.Thread(target=worker, daemon=True).start()


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
	root.title("Motor Control")
	num_channels = len(MOTOR_CHANNELS)
	window_width = max(950, 360 * num_channels)
	root.geometry(f"{window_width}x560")
	root.minsize(window_width, 560)

	container = ttk.Frame(root, padding=12)
	container.pack(fill="both", expand=True)

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
	ttk.Label(container, text=startup_msg, wraplength=900, justify="left").grid(
		row=0, column=0, columnspan=num_channels, sticky="ew", pady=(0, 8)
	)
	if not connection_ok:
		messagebox.showwarning("Motor Connection", startup_msg)

	for i in range(num_channels):
		container.columnconfigure(i, weight=1)

	panels = []
	panel_by_channel = {}
	for idx, channel in enumerate(MOTOR_CHANNELS):
		panel = MotorPanel(container, channel)
		panel.grid(row=1, column=idx, sticky="nsew", padx=6, pady=6)
		panels.append(panel)
		panel_by_channel[channel] = panel

	scan_panel = ScanPanel(container)
	scan_panel.grid(row=2, column=0, columnspan=num_channels, sticky="ew", padx=6, pady=(4, 6))

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
