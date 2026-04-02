import threading
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

#To DO list for the motor control GUI: 1. live updates for the position(ideally in terms of encoder counts and mm), 2. error handling for invalid position input, 3. error handling for move/home errors, 4. display of motor status (enabled/disabled etc)
#automatically connect the moors once launching the GUI program

motor = None
MOTOR_IMPORT_ERROR = None


MOTOR_CHANNELS = [1, 2]


class MotorPanel(ttk.LabelFrame):
	def __init__(self, parent, channel_num):
		super().__init__(parent, text=f"Motor Channel {channel_num}", padding=10)
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
		return motor.motor_position(self.channel_num, 0)

	def refresh_status(self):
		if motor is None:
			self._set_status(f"Status: motor library unavailable - {MOTOR_IMPORT_ERROR}")
			return

		self._set_status("Status: querying...")

		def worker():
			try:
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
				motor.home_motor(self.channel_num)
				position = self._query_motor_position()
				msg = f"Status: homing complete | reported={position}"
				self.after(0, lambda: self._set_displayed_position(position))
			except Exception as exc:
				msg = f"Status: homing error - {exc}"
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
	root.geometry("950x420")

	container = ttk.Frame(root, padding=12)
	container.pack(fill="both", expand=True)

	motor_loaded = _load_motor_module()
	if motor_loaded:
		connection_ok = motor.connect_to_all(MOTOR_CHANNELS)
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
		row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8)
	)
	if not connection_ok:
		messagebox.showwarning("Motor Connection", startup_msg)

	for i in range(3):
		container.columnconfigure(i, weight=1)

	panels = []
	for idx, channel in enumerate(MOTOR_CHANNELS):
		panel = MotorPanel(container, channel)
		panel.grid(row=1, column=idx, sticky="nsew", padx=6, pady=6)
		panels.append(panel)

	for panel in panels:
		panel.refresh_status()

	return root


if __name__ == "__main__":
	app = build_gui()
	app.mainloop()
