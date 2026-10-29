"""
Computer-vision focus (resolution) quantification and z = f(x, y) focus mapping
using a Thorlabs ThorCam scientific camera (tested with a CS165CU) under white light.

What it does
  1. Grabs frames from the ThorCam (thorlabs_tsi_sdk), picking only frames whose exposure
     started *after* the stage settled (by frame counter). Colour (Bayer) sensors are
     2x2 binned to a grey image so the colour mosaic doesn't look like "detail".
  2. Turns an image into a sharpness number (focus metric): variance of the
     Laplacian, Tenengrad, Brenner or normalised variance - all brightness-normalised.
  3. Autofocus at one (x, y): coarse z sweep (re-centred if the peak is at the edge),
     fine sweep around the best coarse z, and a log-parabola (Gaussian) peak fit for
     sub-step precision. Every sweep approaches from below to cancel backlash.
  4. Focus map: autofocus on a sparse X/Y grid, robustly fit a plane / quadratic
     surface z(x, y) (MAD outlier rejection) and print it as an expression that can be
     pasted straight into Motor_GUI's "Z focus" tab (scan_helpers.ZFunction syntax).
     The fitted surface is what extrapolates z to every point of the real scan.

Usage
  python resolution_cv.py              # GUI with camera + motors
  python resolution_cv.py --simulate   # GUI with a simulated camera/stage (no hardware)
  python resolution_cv.py --install    # extract Thorlabs DLLs + pip install SDK/OpenCV
  python resolution_cv.py --snap       # grab one frame, print focus scores, save PNG
  python resolution_cv.py --selftest   # offline check of metrics/autofocus/fit

Do not run this at the same time as Motor_GUI.py: both open the same Kinesis
controller and the same camera. Build the map here, then paste the expression there.
Positions are stage DevicePosition units (x10^-1 mm), the same as Motor_GUI.
"""

from __future__ import annotations

import argparse
import csv
import os
import queue
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

try:
	import cv2
except ImportError:  # scipy fallback is used for the metrics
	cv2 = None

X_CHANNEL, Y_CHANNEL, Z_CHANNEL = 1, 2, 3
MOTOR_CHANNELS = [X_CHANNEL, Y_CHANNEL, Z_CHANNEL]
DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "motor_pos_time"

# ---------------------------------------------------------------------------
# Thorlabs SDK / driver setup
# ---------------------------------------------------------------------------

THORLABS_IMAGING_DIR = Path(r"C:\Program Files\Thorlabs\Scientific Imaging")
THORLABS_SDK_ZIP = THORLABS_IMAGING_DIR / "Scientific Camera Support" / "Scientific_Camera_Interfaces.zip"
_ZIP_DLL_PREFIX = "Scientific Camera Interfaces/SDK/Native Toolkit/dlls/Native_64_lib/"
_ZIP_PY_PACKAGE = "Scientific Camera Interfaces/SDK/Python Toolkit/thorlabs_tsi_camera_python_sdk_package.zip"
LOCAL_DLL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Thorlabs_TSI_SDK" / "Native_64_lib"
THORCAM_DOWNLOAD_URL = "https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=ThorCam"

_dll_dir_handles = []  # keep os.add_dll_directory handles alive


class CameraSetupError(RuntimeError):
	pass


def extract_native_dlls(target: Path = LOCAL_DLL_DIR) -> Path:
	"""Extract the 64-bit TSI native DLLs from the ThorCam install into a per-user folder.

	The Python SDK needs the 'Native Toolkit' DLLs; the copies in the ThorCam
	application folder are a different build and crash tl_camera_open_sdk().
	"""
	if not THORLABS_SDK_ZIP.exists():
		raise CameraSetupError(
			f"ThorCam is not installed ({THORLABS_SDK_ZIP} missing). Install ThorCam from {THORCAM_DOWNLOAD_URL}"
		)
	target.mkdir(parents=True, exist_ok=True)
	with zipfile.ZipFile(THORLABS_SDK_ZIP) as archive:
		for name in archive.namelist():
			if name.startswith(_ZIP_DLL_PREFIX) and name.lower().endswith(".dll"):
				(target / Path(name).name).write_bytes(archive.read(name))
	return target


def install_dependencies() -> None:
	"""Extract the native DLLs and pip-install the Thorlabs Python SDK + OpenCV."""
	print(f"Extracting Thorlabs native DLLs to {extract_native_dlls()}")
	package_zip = LOCAL_DLL_DIR.parent / "thorlabs_tsi_camera_python_sdk_package.zip"
	with zipfile.ZipFile(THORLABS_SDK_ZIP) as archive:
		package_zip.write_bytes(archive.read(_ZIP_PY_PACKAGE))
	for requirement in (str(package_zip), "opencv-python-headless", "scipy", "matplotlib", "pillow"):
		print(f"pip install {requirement}")
		subprocess.check_call([sys.executable, "-m", "pip", "install", requirement])
	print("Done. Close the ThorCam application before using the camera from Python.")


def configure_thorlabs_dlls() -> Path:
	"""Make the native TSI DLLs visible to this process (extracting them on first use)."""
	candidates = [os.environ.get("THORLABS_TSI_DLL_DIR"), str(LOCAL_DLL_DIR)]
	dll_dir = next((Path(c) for c in candidates if c and (Path(c) / "thorlabs_tsi_camera_sdk.dll").exists()), None)
	if dll_dir is None:
		dll_dir = extract_native_dlls()
	if str(dll_dir) not in os.environ.get("PATH", ""):
		os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
		if hasattr(os, "add_dll_directory"):
			_dll_dir_handles.append(os.add_dll_directory(str(dll_dir)))
	return dll_dir


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

def bayer_to_gray(raw: np.ndarray) -> np.ndarray:
	"""2x2 bin a Bayer mosaic (any phase) into a half-resolution grey image."""
	h, w = raw.shape[0] // 2 * 2, raw.shape[1] // 2 * 2
	r = raw[:h, :w].astype(np.float32)
	return (r[0::2, 0::2] + r[0::2, 1::2] + r[1::2, 0::2] + r[1::2, 1::2]) * 0.25


class ThorCam:
	"""ThorCam (TSI SDK) wrapper. grab() returns a float32 grey image exposed after the call."""

	def __init__(self, serial: Optional[str] = None, exposure_us: int = 20000, gain: Optional[int] = None):
		configure_thorlabs_dlls()
		try:
			from thorlabs_tsi_sdk.tl_camera import TLCameraSDK
		except ImportError as exc:
			raise CameraSetupError("thorlabs_tsi_sdk is not installed - run: python resolution_cv.py --install") from exc
		self._lock = threading.RLock()
		self._sdk = TLCameraSDK()
		try:
			cameras = self._sdk.discover_available_cameras()
			if not cameras:
				raise CameraSetupError("No ThorCam found. Check USB and close the ThorCam application.")
			self.serial = serial or cameras[0]
			if self.serial not in cameras:
				raise CameraSetupError(f"Camera {self.serial} not found (available: {cameras}).")
			self._cam = self._sdk.open_camera(self.serial)
		except Exception:
			self._sdk.dispose()
			raise
		self.model = self._cam.model
		self.bit_depth = int(self._cam.bit_depth)
		self.max_value = float(2 ** self.bit_depth - 1)
		self.is_color = int(self._cam.camera_sensor_type) == 1  # SENSOR_TYPE.BAYER
		self.exposure_us = exposure_us
		if gain is not None:
			try:
				self._cam.gain = int(gain)
			except Exception:
				pass
		# Single-frame software triggers (frames_per_trigger=1) never deliver on the CS165CU with this
		# SDK, so the camera free-runs and grab_raw() picks a frame by its frame counter instead.
		self._ref: Optional[Tuple[int, float]] = None  # (frame_count, host arrival time)
		self._cam.frames_per_trigger_zero_for_unlimited = 0
		self._cam.image_poll_timeout_ms = 20
		self._cam.arm(2)
		self._cam.issue_software_trigger()

	@property
	def exposure_us(self) -> int:
		return int(self._cam.exposure_time_us)

	@exposure_us.setter
	def exposure_us(self, value: int) -> None:
		lo, hi = self._cam.exposure_time_range_us
		with self._lock:
			self._cam.exposure_time_us = int(min(max(int(value), lo), hi))
			self._ref = None

	def grab_raw(self, timeout_s: float = 5.0, latency_margin_s: float = 0.1) -> np.ndarray:
		"""Return a frame whose exposure started after this call (i.e. after the stage settled).

		Frame k+m starts m frame periods after frame k, and frame k had arrived by its host
		arrival time, so a frame is fresh once its count is far enough past the last one seen.
		"""
		with self._lock:
			t_req = time.monotonic()
			period = max(float(self._cam.frame_time_us), 1.0) * 1e-6
			exposure = self.exposure_us * 1e-6
			while True:  # drain stale frames
				frame = self._cam.get_pending_frame_or_null()
				if frame is None:
					break
				self._ref = (int(frame.frame_count), time.monotonic())
			needed = None
			if self._ref is not None:
				ref_count, ref_time = self._ref
				needed = ref_count + int(np.ceil((t_req - ref_time + exposure + latency_margin_s) / period)) + 1
			deadline = t_req + timeout_s + 3 * (exposure + period)
			while time.monotonic() < deadline:
				frame = self._cam.get_pending_frame_or_null()
				if frame is None:
					continue
				count, now = int(frame.frame_count), time.monotonic()
				self._ref = (count, now)
				if needed is None:  # first frame since arming / exposure change: skip a few
					needed = count + int(np.ceil((exposure + latency_margin_s) / period)) + 1
				elif count >= needed:
					return np.array(frame.image_buffer, dtype=np.uint16, copy=True)
			raise TimeoutError("ThorCam did not deliver a frame (is the ThorCam app open?).")

	def grab(self, n_avg: int = 1) -> np.ndarray:
		"""Average n_avg fresh frames (reduces noise in the focus score)."""
		acc = None
		for _ in range(max(1, n_avg)):
			raw = self.grab_raw().astype(np.float32)
			img = bayer_to_gray(raw) if self.is_color else raw
			acc = img if acc is None else acc + img
		return acc / max(1, n_avg)

	def close(self) -> None:
		with self._lock:
			try:
				self._cam.disarm()
				self._cam.dispose()
			finally:
				self._sdk.dispose()

	def __enter__(self):
		return self

	def __exit__(self, *_):
		self.close()


class SimulatedCamera:
	"""Textured target blurred by defocus |z - z_focus(x, y)|; for testing without hardware."""

	model = "Simulated"
	serial = "sim"
	bit_depth = 10
	max_value = 1023.0
	is_color = False

	def __init__(self, stage: "SimulatedStage", focus_plane=(2.0, 0.08, -0.05, 0.03), dof: float = 0.02,
				 shape=(270, 360), noise: float = 2.0, seed: int = 0):
		rng = np.random.default_rng(seed)
		texture = ndimage.gaussian_filter(rng.random(shape), 1.2)
		yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
		texture += 0.4 * ((xx // 24 + yy // 24) % 2)
		texture = (texture - texture.min()) / np.ptp(texture)
		self._texture = 150 + 500 * texture
		self._rng = rng
		self.stage, self.focus_plane, self.dof, self.noise = stage, focus_plane, dof, noise
		self.exposure_us = 20000

	def z_focus(self, x: float, y: float) -> float:
		z0, ax, ay, axy = self.focus_plane
		return z0 + ax * x + ay * y + axy * x * y

	def grab(self, n_avg: int = 1) -> np.ndarray:
		x, y, z = (self.stage.read(c) for c in MOTOR_CHANNELS)
		sigma = 0.3 + 6.0 * abs(z - self.z_focus(x, y)) / self.dof
		img = ndimage.gaussian_filter(self._texture, sigma)
		img = img + self._rng.normal(0, self.noise / np.sqrt(max(1, n_avg)), img.shape)
		time.sleep(0.01)
		return np.clip(img, 0, self.max_value).astype(np.float32)

	def close(self) -> None:
		pass


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

class MotorStage:
	"""Thin wrapper around basic_motor_control (same calls Motor_GUI/scan_helpers use)."""

	def __init__(self, motor_module, io_lock: Optional[threading.Lock] = None, move_timeout_ms: int = 60000):
		self.motor = motor_module
		self.lock = io_lock or threading.Lock()
		self.move_timeout_ms = move_timeout_ms

	@classmethod
	def connect(cls) -> "MotorStage":
		import basic_motor_control as motor_module
		if not motor_module.connect_to_all_channels(MOTOR_CHANNELS):
			raise RuntimeError("Motor connection failed. Close Motor_GUI / Kinesis and check the controller.")
		return cls(motor_module)

	def move(self, channel: int, position: float) -> float:
		with self.lock:
			ch = self.motor._get_connected_channel(channel)
			ch.MoveTo(self.motor.Decimal(float(position)), self.move_timeout_ms)
			return float(str(ch.DevicePosition))

	def read(self, channel: int) -> float:
		with self.lock:
			return float(str(self.motor.motor_position(channel, 0)))

	def close(self) -> None:
		try:
			self.motor.disconnect_all_channels()
		except Exception as exc:
			print(f"Disconnect warning: {exc}")


class SimulatedStage:
	def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 2.0, move_delay_s: float = 0.0):
		self.pos = {X_CHANNEL: x, Y_CHANNEL: y, Z_CHANNEL: z}
		self.move_delay_s = move_delay_s
		self.lock = threading.Lock()

	def move(self, channel: int, position: float) -> float:
		time.sleep(self.move_delay_s)
		with self.lock:
			self.pos[channel] = round(float(position), 6)
			return self.pos[channel]

	def read(self, channel: int) -> float:
		with self.lock:
			return self.pos[channel]

	def close(self) -> None:
		pass


# ---------------------------------------------------------------------------
# Focus metrics
# ---------------------------------------------------------------------------

FOCUS_METRICS = ("laplacian", "tenengrad", "brenner", "normvar")
METRIC_HELP = {
	"laplacian": "Variance of Laplacian - sharp edges/fine detail (default, fast)",
	"tenengrad": "Sobel gradient energy - robust on edges, less noise-sensitive",
	"brenner": "Brenner 2-pixel difference - very sensitive near focus",
	"normvar": "Normalised variance - most noise-robust, weaker peak",
}


def crop_roi(img: np.ndarray, roi: Optional[Sequence[int]]) -> np.ndarray:
	"""roi = (x0, y0, x1, y1) in image pixels; None = whole image."""
	if not roi:
		return img
	x0, y0, x1, y1 = (int(round(v)) for v in roi)
	x0, x1 = sorted((max(0, x0), min(img.shape[1], x1)))
	y0, y1 = sorted((max(0, y0), min(img.shape[0], y1)))
	if x1 - x0 < 8 or y1 - y0 < 8:
		return img
	return img[y0:y1, x0:x1]


def focus_score(img: np.ndarray, method: str = "laplacian", roi=None, blur_sigma: float = 1.0) -> float:
	"""Sharpness of an image; higher = better focus. Normalised so brightness changes cancel."""
	a = np.ascontiguousarray(crop_roi(np.asarray(img, dtype=np.float32), roi))
	mean = float(a.mean())
	if mean <= 1e-6:
		return 0.0
	if blur_sigma > 0:  # suppress pixel noise, which otherwise dominates high-pass metrics
		a = cv2.GaussianBlur(a, (0, 0), blur_sigma) if cv2 is not None else ndimage.gaussian_filter(a, blur_sigma)
	if method == "laplacian":
		lap = cv2.Laplacian(a, cv2.CV_32F, ksize=3) if cv2 is not None else ndimage.laplace(a)
		return float(lap.var()) / mean ** 2 * 1e3
	if method == "tenengrad":
		if cv2 is not None:
			gx, gy = cv2.Sobel(a, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(a, cv2.CV_32F, 0, 1, ksize=3)
		else:
			gx, gy = ndimage.sobel(a, 1), ndimage.sobel(a, 0)
		return float(np.mean(gx * gx + gy * gy)) / mean ** 2 * 1e3
	if method == "brenner":
		d = a[:, 2:] - a[:, :-2]
		return float(np.mean(d * d)) / mean ** 2 * 1e3
	if method == "normvar":
		return float(a.var()) / mean ** 2 * 1e3
	raise ValueError(f"Unknown focus metric '{method}'. Choose from {FOCUS_METRICS}")


def saturation_fraction(img: np.ndarray, max_value: float) -> float:
	return float(np.mean(img >= 0.98 * max_value))


# ---------------------------------------------------------------------------
# Autofocus at one (x, y)
# ---------------------------------------------------------------------------

class FocusStopped(Exception):
	pass


class FocusSafetyError(RuntimeError):
	pass


@dataclass
class AutofocusSettings:
	span: float = 0.10            # coarse sweep covers z_guess +/- span
	coarse_step: float = 0.02
	fine_step: float = 0.004
	settle_s: float = 0.25        # wait after each z move before exposing
	n_avg: int = 2                # frames averaged per z
	metric: str = "laplacian"
	roi: Optional[Tuple[int, int, int, int]] = None
	blur_sigma: float = 1.0
	backlash: float = 0.01        # every sweep starts this far below its first z
	max_recenter: int = 3         # coarse re-centres when the peak is at the sweep edge
	min_contrast: float = 0.15    # (max-min)/max of the score curve; lower = no usable texture
	z_min: float = -np.inf        # absolute safety limits for z
	z_max: float = np.inf

	def validate(self) -> None:
		if self.metric not in FOCUS_METRICS:
			raise ValueError(f"metric must be one of {FOCUS_METRICS}")
		if not (0 < self.fine_step < self.coarse_step <= self.span):
			raise ValueError("need 0 < fine step < coarse step <= span")
		if self.settle_s < 0 or self.n_avg < 1 or self.backlash < 0:
			raise ValueError("settle >= 0, frames >= 1 and backlash >= 0 required")
		if self.z_min >= self.z_max:
			raise ValueError("z_min must be < z_max")


@dataclass
class FocusResult:
	x: float
	y: float
	z_best: float
	peak_score: float
	contrast: float
	ok: bool
	reason: str = ""
	z_samples: List[float] = field(default_factory=list)
	scores: List[float] = field(default_factory=list)
	saturation: float = 0.0
	duration_s: float = 0.0


def fit_peak(zs: Sequence[float], scores: Sequence[float]) -> float:
	"""Sub-step peak position: parabola through log(score) around the maximum (= Gaussian fit)."""
	zs, scores = np.asarray(zs, float), np.asarray(scores, float)
	order = np.argsort(zs)
	zs, scores = zs[order], scores[order]
	k = int(np.argmax(scores))
	lo, hi = max(0, k - 2), min(len(zs), k + 3)
	if hi - lo >= 3 and np.all(scores[lo:hi] > 0):
		a, b, _ = np.polyfit(zs[lo:hi], np.log(scores[lo:hi]), 2)
		if a < 0:
			z_peak = -b / (2 * a)
			if zs[lo] <= z_peak <= zs[hi - 1]:
				return float(z_peak)
	lo, hi = max(0, k - 1), min(len(zs), k + 2)  # fallback: weighted centroid of the top points
	w = scores[lo:hi] - scores.min()
	return float(np.sum(zs[lo:hi] * w) / np.sum(w)) if np.sum(w) > 0 else float(zs[k])


def autofocus_at(stage, camera, z_guess: float, settings: AutofocusSettings,
				 stop_event: Optional[threading.Event] = None,
				 on_sample: Optional[Callable[[float, float, np.ndarray], None]] = None) -> FocusResult:
	"""Find the z of best focus at the current x, y. Leaves z at the best focus (or z_guess if failed)."""
	settings.validate()
	t0 = time.monotonic()
	x, y = stage.read(X_CHANNEL), stage.read(Y_CHANNEL)
	all_z: List[float] = []
	all_s: List[float] = []
	max_sat = 0.0

	def safe_move(z: float) -> float:
		if stop_event is not None and stop_event.is_set():
			raise FocusStopped()
		if not (settings.z_min <= z <= settings.z_max):
			raise FocusSafetyError(f"z={z:.5f} outside safety window [{settings.z_min:.5f}, {settings.z_max:.5f}]")
		return stage.move(Z_CHANNEL, z)

	def measure(z: float) -> float:
		nonlocal max_sat
		z_actual = safe_move(z)
		time.sleep(settings.settle_s)
		img = camera.grab(settings.n_avg)
		score = focus_score(img, settings.metric, settings.roi, settings.blur_sigma)
		max_sat = max(max_sat, saturation_fraction(img, camera.max_value))
		all_z.append(z_actual)
		all_s.append(score)
		if on_sample is not None:
			on_sample(z_actual, score, img)
		return score

	def sweep(center: float, half: float, step: float) -> Tuple[np.ndarray, np.ndarray]:
		zs = np.arange(center - half, center + half + step / 2, step)
		zs = zs[(zs >= settings.z_min) & (zs <= settings.z_max)]
		if len(zs) < 3:
			raise FocusSafetyError("sweep would leave the z safety window")
		safe_move(max(settings.z_min, zs[0] - settings.backlash))  # approach from below
		return zs, np.array([measure(z) for z in zs])

	def result(z_best, ok, reason=""):
		peak = max(all_s) if all_s else 0.0
		contrast = (peak - min(all_s)) / peak if all_s and peak > 0 else 0.0
		return FocusResult(x, y, float(z_best), float(peak), float(contrast), ok, reason,
						   list(all_z), list(all_s), max_sat, time.monotonic() - t0)

	def park(z):
		try:
			safe_move(max(settings.z_min, z - settings.backlash))
			safe_move(z)
		except FocusSafetyError:
			pass

	try:
		center = z_guess
		for _ in range(settings.max_recenter + 1):
			zs, sc = sweep(center, settings.span, settings.coarse_step)
			k = int(np.argmax(sc))
			if 0 < k < len(zs) - 1:
				break
			center = zs[k] + (settings.span if k == len(zs) - 1 else -settings.span)
		else:
			park(z_guess)
			return result(z_guess, False, "peak not bracketed - widen span or check z guess")

		zs_f, sc_f = sweep(zs[k], 2 * settings.coarse_step, settings.fine_step)
		z_best = fit_peak(zs_f, sc_f)
		r = result(z_best, True)
		if r.contrast < settings.min_contrast:
			park(z_guess)
			r.ok, r.z_best, r.reason = False, z_guess, f"low contrast {r.contrast:.2f} (no texture in ROI?)"
			return r
		park(z_best)
		if max_sat > 0.01:
			r.reason = f"{max_sat:.1%} pixels saturated - lower exposure"
		return r
	except FocusSafetyError as exc:
		park(z_guess)
		return result(z_guess, False, str(exc))


def quick_refocus(stage, camera, z_now: float, delta: float, settings: AutofocusSettings,
				  max_correction: Optional[float] = None) -> Tuple[float, float]:
	"""3-point (z-d, z, z+d) focus correction for tracking drift during a scan.

	Returns (new_z, correction). The correction is clamped to max_correction (default delta).
	"""
	zs = [z_now - delta, z_now, z_now + delta]
	stage.move(Z_CHANNEL, zs[0] - settings.backlash)
	scores = []
	for z in zs:
		stage.move(Z_CHANNEL, z)
		time.sleep(settings.settle_s)
		scores.append(focus_score(camera.grab(settings.n_avg), settings.metric, settings.roi, settings.blur_sigma))
	limit = delta if max_correction is None else max_correction
	correction = float(np.clip(fit_peak(zs, scores) - z_now, -limit, limit))
	new_z = z_now + correction
	stage.move(Z_CHANNEL, new_z - settings.backlash)
	stage.move(Z_CHANNEL, new_z)
	return new_z, correction


# ---------------------------------------------------------------------------
# Focus surface z(x, y)
# ---------------------------------------------------------------------------

SURFACE_TERMS = {
	0: [(0, 0)],
	1: [(0, 0), (1, 0), (0, 1)],
	2: [(0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2)],
}
SURFACE_NAMES = {0: "constant", 1: "plane (tilt)", 2: "quadratic (tilt + curvature)"}


@dataclass
class FocusSurface:
	order: int
	coef: np.ndarray
	xc: float
	yc: float
	rms: float
	used: np.ndarray       # boolean mask over the input points
	residuals: np.ndarray

	def predict(self, x, y):
		u, v = np.asarray(x, float) - self.xc, np.asarray(y, float) - self.yc
		return sum(c * u ** p * v ** q for c, (p, q) in zip(self.coef, SURFACE_TERMS[self.order]))

	def expression(self, relative: bool = False) -> str:
		"""scan_helpers.ZFunction expression.

		relative=False: absolute z from the map.
		relative=True : z0 + f(x, y) - f(x0, y0), i.e. only the shape of the map is used and it is
		                anchored to the z the scan starts at (robust to a global focus offset).
		"""
		def poly(xs: str, ys: str) -> str:
			parts = []
			for c, (p, q) in zip(self.coef, SURFACE_TERMS[self.order]):
				factor = f" * ({xs} - {self.xc:.6f})" * p + f" * ({ys} - {self.yc:.6f})" * q
				parts.append(f"({c:+.8g}){factor}")
			return "\n+ ".join(parts)

		header = (f"# ThorCam focus map {datetime.now():%Y-%m-%d %H:%M}: {SURFACE_NAMES[self.order]} fit, "
				  f"{int(self.used.sum())} points, rms {self.rms:.5f}")
		if not relative:
			return f"{header}\n{poly('x', 'y')}\n"
		return f"{header} (anchored to z0)\nz0\n+ ({poly('x', 'y')})\n- ({poly('x0', 'y0')})\n"


def fit_focus_surface(x, y, z, order: int = 1, reject_k: float = 3.5, max_iter: int = 5,
					  min_tol: float = 0.002) -> FocusSurface:
	"""Least-squares polynomial surface with iterative MAD outlier rejection.

	Points are only rejected if their residual exceeds both reject_k * MAD and min_tol
	(0.002 units = 0.2 um), so noise-level scatter never counts as an outlier.
	"""
	x, y, z = (np.asarray(a, float) for a in (x, y, z))
	terms = SURFACE_TERMS[order]
	if len(z) < len(terms):
		raise ValueError(f"{SURFACE_NAMES[order]} needs at least {len(terms)} good points (have {len(z)})")
	xc, yc = float(np.mean(x)), float(np.mean(y))
	u, v = x - xc, y - yc
	design = np.column_stack([u ** p * v ** q for p, q in terms])
	used = np.ones(len(z), bool)
	for _ in range(max_iter):
		coef, *_ = np.linalg.lstsq(design[used], z[used], rcond=None)
		residuals = z - design @ coef
		mad = 1.4826 * np.median(np.abs(residuals[used] - np.median(residuals[used])))
		new_used = np.abs(residuals) <= max(reject_k * mad, min_tol)
		if new_used.sum() < len(terms) or np.array_equal(new_used, used):
			break
		used = new_used
	coef, *_ = np.linalg.lstsq(design[used], z[used], rcond=None)
	residuals = z - design @ coef
	rms = float(np.sqrt(np.mean(residuals[used] ** 2)))
	return FocusSurface(order, coef, xc, yc, rms, used, residuals)


def validate_expression(expr: str, x: float, y: float, z0: float) -> float:
	"""Evaluate with Motor_GUI's own parser so the pasted text is guaranteed to be accepted."""
	import scan_helpers
	return scan_helpers.ZFunction(expr)(x, y, x, y, z0)


# ---------------------------------------------------------------------------
# Focus map over an X/Y grid
# ---------------------------------------------------------------------------

def sample_grid(x_start, x_stop, y_start, y_stop, nx: int, ny: int) -> List[Tuple[float, float]]:
	"""Serpentine order sample points (corners included)."""
	xs = np.linspace(x_start, x_stop, max(1, nx))
	ys = np.linspace(y_start, y_stop, max(1, ny))
	points = []
	for j, yv in enumerate(ys):
		row = xs if j % 2 == 0 else xs[::-1]
		points.extend((float(xv), float(yv)) for xv in row)
	return points


def _predict_guess(results: List[FocusResult], x: float, y: float, default: float) -> float:
	good = [r for r in results if r.ok]
	if len(good) >= 3:
		xs = [r.x for r in good]
		ys = [r.y for r in good]
		if np.ptp(xs) > 0 and np.ptp(ys) > 0:
			try:
				return float(fit_focus_surface(xs, ys, [r.z_best for r in good], order=1).predict(x, y))
			except (ValueError, np.linalg.LinAlgError):
				pass
	return good[-1].z_best if good else default


def build_focus_map(stage, camera, points: Sequence[Tuple[float, float]], settings: AutofocusSettings,
					stop_event: threading.Event, emit: Callable[[str, Dict], None],
					z_start: Optional[float] = None, csv_path: Optional[Path] = None,
					start_xy: Optional[Tuple[float, float]] = None, position_tol: float = 0.001) -> List[FocusResult]:
	"""Autofocus at every (x, y) in points. Blocking - run in a worker thread.

	X and Y are first moved back to start_xy (default: the first grid point = X/Y start) and the
	arrival is verified before any focusing begins.
	Events: "status", "map_start", "point_start", "sample", "point", "map_done" (with "stopped"/"error").
	"""
	if not points:
		emit("map_done", {"results": [], "stopped": False, "error": "no sample points", "csv_path": csv_path})
		return []
	start_x, start_y = start_xy if start_xy is not None else points[0]
	z_ref = stage.read(Z_CHANNEL) if z_start is None else z_start
	results: List[FocusResult] = []
	writer = handle = None
	if csv_path is not None:
		csv_path.parent.mkdir(parents=True, exist_ok=True)
		handle = open(csv_path, "w", newline="")
		writer = csv.writer(handle)
		writer.writerow(["x", "y", "z_best", "peak_score", "contrast", "ok", "reason", "saturation", "metric",
						 "z_samples", "scores"])
	emit("map_start", {"points": list(points), "z_ref": z_ref})
	error = None
	stopped = False
	try:
		if stop_event.is_set():
			raise FocusStopped()
		emit("status", {"message": f"Moving X/Y back to start position ({start_x:.4f}, {start_y:.4f}) ..."})
		stage.move(X_CHANNEL, start_x)
		stage.move(Y_CHANNEL, start_y)
		x_now, y_now = stage.read(X_CHANNEL), stage.read(Y_CHANNEL)
		if abs(x_now - start_x) > position_tol or abs(y_now - start_y) > position_tol:
			raise RuntimeError(f"stage did not reach start position: at ({x_now:.4f}, {y_now:.4f}), "
							   f"expected ({start_x:.4f}, {start_y:.4f})")
		emit("status", {"message": f"At start position X={x_now:.4f}, Y={y_now:.4f}. Starting focus map."})
		for idx, (x, y) in enumerate(points):
			if stop_event.is_set():
				raise FocusStopped()
			stage.move(X_CHANNEL, x)
			stage.move(Y_CHANNEL, y)
			guess = _predict_guess(results, x, y, z_ref)
			emit("point_start", {"index": idx, "x": x, "y": y, "z_guess": guess, "total": len(points)})
			r = autofocus_at(stage, camera, guess, settings, stop_event,
							 on_sample=lambda z, s, img, i=idx: emit("sample", {"index": i, "z": z, "score": s, "image": img}))
			results.append(r)
			if writer is not None:
				writer.writerow([f"{r.x:.6f}", f"{r.y:.6f}", f"{r.z_best:.6f}", f"{r.peak_score:.6g}",
								 f"{r.contrast:.4f}", int(r.ok), r.reason, f"{r.saturation:.4f}", settings.metric,
								 " ".join(f"{v:.6f}" for v in r.z_samples), " ".join(f"{v:.6g}" for v in r.scores)])
				handle.flush()
			emit("point", {"index": idx, "total": len(points), "result": r})
	except FocusStopped:
		stopped = True
	except Exception as exc:
		error = str(exc)
	finally:
		if handle is not None:
			handle.close()
	emit("map_done", {"results": results, "stopped": stopped, "error": error, "csv_path": csv_path})
	return results


# ---------------------------------------------------------------------------
# Standalone GUI
# ---------------------------------------------------------------------------

def run_app(simulate: bool = False) -> None:
	import tkinter as tk
	from tkinter import filedialog, messagebox, ttk

	from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
	from matplotlib.figure import Figure
	from matplotlib.patches import Rectangle
	from matplotlib.widgets import RectangleSelector

	try:
		import gui_theme
	except ImportError:
		gui_theme = None

	def style(name: str) -> str:
		return name if gui_theme is not None else name.split(".")[-1]

	unit = "x10^-1 mm"

	class FocusMapApp:
		def __init__(self, root: tk.Tk):
			self.root = root
			self.events: "queue.Queue[Tuple[str, Dict]]" = queue.Queue()
			self.stop_event = threading.Event()
			self.worker: Optional[threading.Thread] = None
			self.live = tk.BooleanVar(value=True)
			self.results: List[FocusResult] = []
			self.surface: Optional[FocusSurface] = None
			self.roi: Optional[Tuple[int, int, int, int]] = None
			self._latest_frame: Optional[np.ndarray] = None
			self._frame_lock = threading.Lock()
			self._live_stop = threading.Event()
			self._map_cbar = None
			self.camera = self.stage = None

			self.v = {}
			for name, default in (
				("exposure_ms", "20"), ("metric", "laplacian"), ("span", "0.10"), ("coarse", "0.02"),
				("fine", "0.004"), ("settle", "0.25"), ("n_avg", "2"), ("backlash", "0.01"),
				("max_dev", "0.30"), ("min_contrast", "0.15"),
				("x_start", "0"), ("x_stop", "0.2"), ("nx", "3"), ("y_start", "0"), ("y_stop", "0.1"), ("ny", "3"),
				("order", "1"), ("output_dir", str(DEFAULT_OUTPUT_DIR)),
				("file_name", f"focusmap_{datetime.now():%Y%m%d_%H%M}"),
			):
				self.v[name] = tk.StringVar(value=default)
			self.relative = tk.BooleanVar(value=False)
			self.status = tk.StringVar(value="Connecting to stage and camera...")
			self.readout = tk.StringVar(value="score: --")
			self.position = tk.StringVar(value="X -- | Y -- | Z --")

			self._build_ui()
			self._reset_curve()
			self.root.protocol("WM_DELETE_WINDOW", self.close)
			self.root.after(100, self._connect)
			self.root.after(100, self._pump)

		# ------------------------------------------------------------ layout
		def _build_ui(self):
			root = self.root
			root.title("ThorCam focus map - z = f(x, y) from image sharpness" + ("  [SIMULATED]" if simulate else ""))
			root.geometry("1500x920")
			if gui_theme is not None:
				gui_theme.apply_theme(root)
			outer = ttk.Frame(root, padding=10, style=style("App.TFrame"))
			outer.pack(fill="both", expand=True)
			outer.columnconfigure(1, weight=1)
			outer.rowconfigure(0, weight=1)

			left = ttk.Frame(outer, padding=10, style=style("Card.TFrame"))
			left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
			nb = ttk.Notebook(left)
			nb.pack(fill="both", expand=True)

			def entry_rows(parent, rows, start=0):
				parent.columnconfigure(1, weight=1)
				for r, (label, key, u) in enumerate(rows, start=start):
					ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2)
					ttk.Entry(parent, textvariable=self.v[key], width=10).grid(row=r, column=1, sticky="ew", padx=6, pady=2)
					ttk.Label(parent, text=u).grid(row=r, column=2, sticky="w")
				return start + len(rows)

			cam_tab = ttk.Frame(nb, padding=10)
			nb.add(cam_tab, text=" Camera ")
			n = entry_rows(cam_tab, [("Exposure", "exposure_ms", "ms")])
			ttk.Button(cam_tab, text="Apply exposure", command=self.apply_exposure).grid(row=n, column=0, columnspan=3, sticky="ew", pady=4)
			ttk.Label(cam_tab, text="Focus metric").grid(row=n + 1, column=0, sticky="w", pady=(10, 2))
			ttk.Combobox(cam_tab, textvariable=self.v["metric"], values=FOCUS_METRICS, state="readonly", width=12).grid(
				row=n + 1, column=1, columnspan=2, sticky="ew", pady=(10, 2))
			self.metric_help = ttk.Label(cam_tab, text=METRIC_HELP["laplacian"], wraplength=300, justify="left")
			self.metric_help.grid(row=n + 2, column=0, columnspan=3, sticky="w")
			self.v["metric"].trace_add("write", lambda *_: self.metric_help.configure(
				text=METRIC_HELP.get(self.v["metric"].get(), "")))
			ttk.Checkbutton(cam_tab, text="Live view", variable=self.live).grid(row=n + 3, column=0, columnspan=3, sticky="w", pady=(12, 0))
			ttk.Label(cam_tab, text="Drag a rectangle on the image to set the ROI\n(choose an area with texture / edges).",
					  justify="left").grid(row=n + 4, column=0, columnspan=3, sticky="w", pady=(6, 4))
			ttk.Button(cam_tab, text="Clear ROI (full frame)", command=self.clear_roi).grid(row=n + 5, column=0, columnspan=3, sticky="ew")

			af_tab = ttk.Frame(nb, padding=10)
			nb.add(af_tab, text=" Autofocus ")
			n = entry_rows(af_tab, [
				("Sweep span (+/-)", "span", unit), ("Coarse step", "coarse", unit),
				("Fine step", "fine", unit), ("Backlash approach", "backlash", unit),
				("Settle time", "settle", "s"), ("Frames averaged", "n_avg", ""),
				("Min contrast", "min_contrast", "0..1"), ("Max |z - z_ref|", "max_dev", unit),
			])
			ttk.Label(af_tab, text="Fine step ~ 1/3 of the depth of field\n(DOF ~ 0.55 um / NA^2; 0.01 units = 1 um).\n"
								   "z_ref = z when you press the button; z never\nleaves z_ref +/- Max |z - z_ref|.",
					  justify="left").grid(row=n, column=0, columnspan=3, sticky="w", pady=(6, 6))
			self.af_btn = ttk.Button(af_tab, text="Autofocus here", command=self.autofocus_here, style=style("Accent.TButton"))
			self.af_btn.grid(row=n + 1, column=0, columnspan=3, sticky="ew")

			map_tab = ttk.Frame(nb, padding=10)
			nb.add(map_tab, text=" Focus map ")
			n = entry_rows(map_tab, [
				("X start", "x_start", unit), ("X stop", "x_stop", unit), ("X samples", "nx", ""),
				("Y start", "y_start", unit), ("Y stop", "y_stop", unit), ("Y samples", "ny", ""),
			])
			ttk.Label(map_tab, text="Use the scan's X/Y range. 3x3 is enough for a\nplane, 4x4 or more for a quadratic.",
					  justify="left").grid(row=n, column=0, columnspan=3, sticky="w", pady=(4, 4))
			ttk.Label(map_tab, text="Surface order").grid(row=n + 1, column=0, sticky="w")
			order_box = ttk.Combobox(map_tab, textvariable=self.v["order"], values=("0", "1", "2"), state="readonly", width=6)
			order_box.grid(row=n + 1, column=1, sticky="w", padx=6)
			order_box.bind("<<ComboboxSelected>>", lambda _e: self.refit())
			ttk.Label(map_tab, text="0 const / 1 plane / 2 quad").grid(row=n + 1, column=2, sticky="w")
			ttk.Checkbutton(map_tab, text="Anchor to scan start z  (z0 + map shape)", variable=self.relative,
							command=self.refit).grid(row=n + 2, column=0, columnspan=3, sticky="w", pady=(4, 0))
			ttk.Label(map_tab, text="Save folder").grid(row=n + 3, column=0, sticky="w", pady=(8, 0))
			ttk.Entry(map_tab, textvariable=self.v["output_dir"], width=22).grid(row=n + 3, column=1, sticky="ew", padx=6, pady=(8, 0))
			ttk.Button(map_tab, text="...", width=3, command=self.browse).grid(row=n + 3, column=2, sticky="w", pady=(8, 0))
			ttk.Label(map_tab, text="File name").grid(row=n + 4, column=0, sticky="w", pady=2)
			ttk.Entry(map_tab, textvariable=self.v["file_name"], width=22).grid(row=n + 4, column=1, columnspan=2, sticky="ew", padx=6, pady=2)
			self.map_btn = ttk.Button(map_tab, text="Build focus map", command=self.build_map, style=style("Success.TButton"))
			self.map_btn.grid(row=n + 5, column=0, columnspan=3, sticky="ew", pady=(10, 2))
			ttk.Button(map_tab, text="Refit surface", command=self.refit).grid(row=n + 6, column=0, columnspan=3, sticky="ew", pady=2)
			ttk.Button(map_tab, text="Go to fitted focus at current X/Y", command=self.goto_fitted).grid(
				row=n + 7, column=0, columnspan=3, sticky="ew", pady=2)

			ttk.Separator(left).pack(fill="x", pady=8)
			ttk.Label(left, textvariable=self.position, font=("Consolas", 10)).pack(anchor="w")
			self.stop_btn = ttk.Button(left, text="Stop", command=self.stop_event.set, state="disabled", style=style("Danger.TButton"))
			self.stop_btn.pack(fill="x", pady=(6, 0))

			right = ttk.Frame(outer, padding=10, style=style("Card.TFrame"))
			right.grid(row=0, column=1, sticky="nsew")
			right.columnconfigure(0, weight=1)
			right.rowconfigure(0, weight=1)
			self.fig = Figure(figsize=(10, 6), dpi=100, facecolor="white")
			gs = self.fig.add_gridspec(2, 2, width_ratios=[1.35, 1], hspace=0.4, wspace=0.25)
			self.ax_img = self.fig.add_subplot(gs[:, 0])
			self.ax_curve = self.fig.add_subplot(gs[0, 1])
			self.ax_map = self.fig.add_subplot(gs[1, 1])
			self.im = self.ax_img.imshow(np.zeros((540, 720)), cmap="gray", vmin=0, vmax=1)
			self.ax_img.set_title("Camera (grey)", fontsize=10, loc="left", fontweight="bold")
			self.ax_img.set_xticks([])
			self.ax_img.set_yticks([])
			self.roi_patch = None
			self.selector = RectangleSelector(self.ax_img, self._on_roi, useblit=True, button=[1],
											  minspanx=10, minspany=10, interactive=False)
			self._draw_map()
			self.canvas = FigureCanvasTkAgg(self.fig, master=right)
			self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
			info = ttk.Frame(right)
			info.grid(row=1, column=0, sticky="ew", pady=(6, 0))
			info.columnconfigure(1, weight=1)
			ttk.Label(info, textvariable=self.readout, font=("Consolas", 11, "bold")).grid(row=0, column=0, sticky="w")
			self.progress = ttk.Progressbar(info, mode="determinate")
			self.progress.grid(row=0, column=1, sticky="ew", padx=10)

			expr_box = ttk.LabelFrame(right, text="z = f(x, y)  ->  paste into Motor_GUI > 2D Scan > Z focus", padding=6)
			expr_box.grid(row=2, column=0, sticky="ew", pady=(6, 0))
			expr_box.columnconfigure(0, weight=1)
			self.expr_text = tk.Text(expr_box, height=6, wrap="none", font=("Consolas", 10))
			self.expr_text.grid(row=0, column=0, rowspan=2, sticky="ew")
			ttk.Button(expr_box, text="Copy", command=self.copy_expression).grid(row=0, column=1, sticky="ew", padx=(6, 0))
			ttk.Button(expr_box, text="Save .txt", command=self.save_expression).grid(row=1, column=1, sticky="ew", padx=(6, 0))
			ttk.Label(right, textvariable=self.status, wraplength=1000, justify="left").grid(row=3, column=0, sticky="ew", pady=(6, 0))

		# ------------------------------------------------------- hardware
		def _connect(self):
			def worker():
				try:
					if simulate:
						stage = SimulatedStage(x=0.0, y=0.0, z=2.0, move_delay_s=0.02)
						camera = SimulatedCamera(stage)
					else:
						stage = MotorStage.connect()
						try:
							camera = ThorCam(exposure_us=int(float(self.v["exposure_ms"].get()) * 1000))
						except Exception:
							stage.close()
							raise
					self.events.put(("connected", {"stage": stage, "camera": camera}))
				except Exception as exc:
					self.events.put(("connect_error", {"message": str(exc)}))
			threading.Thread(target=worker, daemon=True).start()

		def _busy(self) -> bool:
			return self.worker is not None and self.worker.is_alive()

		def _live_loop(self):
			last_pos = 0.0
			while not self._live_stop.is_set():
				if not self._busy():
					if self.live.get():
						try:
							img = self.camera.grab(1)
							with self._frame_lock:
								self._latest_frame = img
						except Exception as exc:
							self.events.put(("status", {"message": f"Camera: {exc}"}))
							time.sleep(1)
					if time.monotonic() - last_pos > 0.5:
						try:
							self.events.put(("position", {"pos": [self.stage.read(c) for c in MOTOR_CHANNELS]}))
						except Exception:
							pass
						last_pos = time.monotonic()
				time.sleep(0.05)

		# ---------------------------------------------------------- inputs
		def _f(self, key):
			try:
				return float(self.v[key].get())
			except ValueError:
				raise ValueError(f"'{key}' must be a number (got '{self.v[key].get()}')") from None

		def _settings(self, z_ref: float) -> AutofocusSettings:
			dev = self._f("max_dev")
			if dev <= 0:
				raise ValueError("Max |z - z_ref| must be > 0")
			s = AutofocusSettings(
				span=self._f("span"), coarse_step=self._f("coarse"), fine_step=self._f("fine"),
				settle_s=self._f("settle"), n_avg=int(self._f("n_avg")), metric=self.v["metric"].get(),
				roi=self.roi, backlash=self._f("backlash"), min_contrast=self._f("min_contrast"),
				z_min=z_ref - dev, z_max=z_ref + dev,
			)
			s.validate()
			return s

		def _ready(self):
			if self.camera is None or self.stage is None:
				self.status.set("Not connected yet.")
				return False
			if self._busy():
				self.status.set("Busy - press Stop first.")
				return False
			return True

		# --------------------------------------------------------- actions
		def apply_exposure(self):
			if self.camera is None:
				return
			try:
				self.camera.exposure_us = int(self._f("exposure_ms") * 1000)
				self.status.set(f"Exposure set to {self.camera.exposure_us / 1000:.2f} ms")
			except Exception as exc:
				self.status.set(f"Exposure: {exc}")

		def _on_roi(self, press, release):
			if press.xdata is None or release.xdata is None:
				return
			x0, x1 = sorted((press.xdata, release.xdata))
			y0, y1 = sorted((press.ydata, release.ydata))
			self.roi = (int(x0), int(y0), int(x1), int(y1))
			self._draw_roi()
			self.status.set(f"ROI: x {self.roi[0]}-{self.roi[2]}, y {self.roi[1]}-{self.roi[3]} (image pixels)")

		def clear_roi(self):
			self.roi = None
			self._draw_roi()
			self.status.set("ROI cleared - using the full frame.")

		def _draw_roi(self):
			if self.roi_patch is not None:
				self.roi_patch.remove()
				self.roi_patch = None
			if self.roi:
				x0, y0, x1, y1 = self.roi
				self.roi_patch = self.ax_img.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec="#22c55e", lw=2))
			self.canvas.draw_idle()

		def _start_worker(self, target):
			self.stop_event.clear()
			self.stop_btn.configure(state="normal")
			self.map_btn.configure(state="disabled")
			self.af_btn.configure(state="disabled")
			self.worker = threading.Thread(target=target, daemon=True)
			self.worker.start()

		def _emit(self, kind, data):
			self.events.put((kind, data))

		def autofocus_here(self):
			if not self._ready():
				return
			try:
				z_ref = self.stage.read(Z_CHANNEL)
				settings = self._settings(z_ref)
			except Exception as exc:
				self.status.set(f"Autofocus: {exc}")
				return
			self._reset_curve()
			self.status.set(f"Autofocus around z={z_ref:.5f} ...")

			def work():
				try:
					r = autofocus_at(self.stage, self.camera, z_ref, settings, self.stop_event,
									 on_sample=lambda z, s, img: self._emit("sample", {"z": z, "score": s, "image": img}))
					self._emit("af_done", {"result": r})
				except FocusStopped:
					self._emit("af_done", {"result": None, "message": "stopped"})
				except Exception as exc:
					self._emit("af_done", {"result": None, "message": str(exc)})
			self._start_worker(work)

		def build_map(self):
			if not self._ready():
				return
			try:
				bounds = [self._f(k) for k in ("x_start", "x_stop", "y_start", "y_stop")]
				if min(bounds) < 0:
					raise ValueError("positions must be >= 0")
				nx, ny = int(self._f("nx")), int(self._f("ny"))
				if nx < 1 or ny < 1:
					raise ValueError("samples must be >= 1")
				points = sample_grid(*bounds, nx, ny)
				z_ref = self.stage.read(Z_CHANNEL)
				settings = self._settings(z_ref)
				csv_path = self._output_path("_focusmap.csv")
			except Exception as exc:
				self.status.set(f"Focus map: {exc}")
				return
			if csv_path.exists() and not messagebox.askyesno(
					"File exists", f"{csv_path.name} already exists in\n{csv_path.parent}\n\nOverwrite?", icon="warning"):
				return
			self.results = []
			self.surface = None
			self._draw_map()
			self.progress.configure(maximum=len(points), value=0)
			self.status.set(f"Building focus map: {len(points)} points around z_ref={z_ref:.5f} "
							f"(safety window +/- {self._f('max_dev')}).")
			start_xy = (bounds[0], bounds[2])
			self._start_worker(lambda: build_focus_map(self.stage, self.camera, points, settings, self.stop_event,
													   self._emit, z_start=z_ref, csv_path=csv_path,
													   start_xy=start_xy))

		def _output_path(self, suffix):
			import scan_helpers
			folder_text = self.v["output_dir"].get().strip()
			if not folder_text:
				raise ValueError("save folder is empty")
			stem = scan_helpers.clean_file_stem(self.v["file_name"].get())
			return Path(folder_text).expanduser() / f"{stem}{suffix}"

		def browse(self):
			folder = filedialog.askdirectory(parent=self.root, initialdir=self.v["output_dir"].get())
			if folder:
				self.v["output_dir"].set(str(Path(folder)))

		def refit(self):
			good = [r for r in self.results if r.ok]
			if not good:
				return
			order = int(self.v["order"].get())
			try:
				if order >= 1 and (np.ptp([r.x for r in good]) == 0 or np.ptp([r.y for r in good]) == 0):
					raise ValueError("need focused points spread in both X and Y for a plane/quadratic")
				self.surface = fit_focus_surface([r.x for r in good], [r.y for r in good], [r.z_best for r in good], order)
				expr = self.surface.expression(relative=self.relative.get())
				validate_expression(expr, good[0].x, good[0].y, good[0].z_best)
			except Exception as exc:
				self.surface = None
				self.status.set(f"Fit: {exc}")
				self._draw_map()
				return
			self.expr_text.delete("1.0", "end")
			self.expr_text.insert("1.0", expr)
			s = self.surface
			tilt = f", dz/dx={s.coef[1]:+.4g}, dz/dy={s.coef[2]:+.4g}" if order >= 1 else ""
			self.status.set(f"Fit {SURFACE_NAMES[order]}: rms residual {s.rms:.5f}, "
							f"{int((~s.used).sum())} outlier(s) rejected{tilt}. Copy the expression into Motor_GUI.")
			self._draw_map()
			self.canvas.draw_idle()

		def goto_fitted(self):
			if not self._ready():
				return
			if self.surface is None:
				self.status.set("Build and fit a focus map first.")
				return
			try:
				x, y, z_now = (self.stage.read(c) for c in MOTOR_CHANNELS)
				z = float(self.surface.predict(x, y))
				backlash = self._f("backlash")
				if abs(z - z_now) > self._f("max_dev"):
					self.status.set(f"Fitted z={z:.5f} is more than Max |z - z_ref| from current z={z_now:.5f}; not moving.")
					return
			except Exception as exc:
				self.status.set(f"Go to fitted focus: {exc}")
				return

			def work():
				try:
					self.stage.move(Z_CHANNEL, z - backlash)
					self.stage.move(Z_CHANNEL, z)
					self._emit("status", {"message": f"Moved to fitted focus z={z:.5f} at x={x:.4f}, y={y:.4f}"})
				except Exception as exc:
					self._emit("status", {"message": f"Move failed: {exc}"})
				self._emit("idle", {})
			self._start_worker(work)

		def copy_expression(self):
			text = self.expr_text.get("1.0", "end").strip()
			if not text:
				self.status.set("Nothing to copy yet - build a focus map first.")
				return
			self.root.clipboard_clear()
			self.root.clipboard_append(text)
			self.status.set("Expression copied - paste it into Motor_GUI > 2D Scan > Z focus.")

		def save_expression(self):
			try:
				path = self._output_path("_zfunction.txt")
				path.parent.mkdir(parents=True, exist_ok=True)
				path.write_text(self.expr_text.get("1.0", "end").strip() + "\n")
				self.status.set(f"Saved {path}")
			except Exception as exc:
				self.status.set(f"Save failed: {exc}")

		# ------------------------------------------------------- plotting
		def _reset_curve(self):
			self.ax_curve.cla()
			self.ax_curve.set_title("Focus score vs z", fontsize=10, loc="left", fontweight="bold")
			self.ax_curve.set_xlabel(f"z ({unit})", fontsize=8)
			self.ax_curve.tick_params(labelsize=8)
			self._curve_z, self._curve_s = [], []
			self._curve_line, = self.ax_curve.plot([], [], "o", ms=3, color="#2563eb")

		def _show_image(self, img):
			lo, hi = (float(v) for v in np.percentile(img, (0.5, 99.5)))
			if self.im.get_array().shape != img.shape:
				self.im.set_extent((-0.5, img.shape[1] - 0.5, img.shape[0] - 0.5, -0.5))
			self.im.set_data(img)
			self.im.set_clim(lo, max(hi, lo + 1))
			try:
				score = focus_score(img, self.v["metric"].get(), self.roi)
				sat = saturation_fraction(img, self.camera.max_value) if self.camera else 0.0
				warn = f"   SATURATED {sat:.1%} - lower exposure" if sat > 0.01 else ""
				self.readout.set(f"{self.v['metric'].get()} score: {score:10.4f}{warn}")
			except Exception:
				pass

		def _draw_map(self):
			ax = self.ax_map
			ax.cla()
			ax.set_title("Best-focus z map", fontsize=10, loc="left", fontweight="bold")
			ax.tick_params(labelsize=8)
			ax.set_xlabel("x", fontsize=8)
			ax.set_ylabel("y", fontsize=8)
			if not self.results:
				return
			good = [r for r in self.results if r.ok]
			bad = [r for r in self.results if not r.ok]
			xs = np.array([r.x for r in self.results])
			ys = np.array([r.y for r in self.results])
			if self.surface is not None and good:
				pad_x = max(np.ptp(xs) * 0.1, 1e-3)
				pad_y = max(np.ptp(ys) * 0.1, 1e-3)
				gx, gy = np.meshgrid(np.linspace(xs.min() - pad_x, xs.max() + pad_x, 60),
									 np.linspace(ys.min() - pad_y, ys.max() + pad_y, 60))
				gz = np.broadcast_to(self.surface.predict(gx, gy), gx.shape)
				cs = ax.contourf(gx, gy, gz, 20, cmap="viridis")
				if self._map_cbar is None:
					self._map_cbar = self.fig.colorbar(cs, ax=ax)
				else:
					self._map_cbar.update_normal(cs)
				self._map_cbar.ax.tick_params(labelsize=7)
			if good:
				ax.scatter([r.x for r in good], [r.y for r in good], c="white", edgecolors="k", s=30, zorder=3)
				for r in good:
					ax.annotate(f"{r.z_best:.4f}", (r.x, r.y), fontsize=6, xytext=(3, 3), textcoords="offset points")
			if bad:
				ax.scatter([r.x for r in bad], [r.y for r in bad], marker="x", c="red", s=40, zorder=3)
			if np.ptp(xs) == 0:
				ax.set_xlim(xs[0] - 0.01, xs[0] + 0.01)
			if np.ptp(ys) == 0:
				ax.set_ylim(ys[0] - 0.01, ys[0] + 0.01)
			ax.invert_xaxis()  # same orientation as the Motor_GUI maps
			ax.invert_yaxis()

		# ------------------------------------------------------ event pump
		def _pump(self):
			redraw = False
			try:
				while True:
					kind, d = self.events.get_nowait()
					redraw |= bool(self._handle(kind, d))
			except queue.Empty:
				pass
			if not self._busy():
				with self._frame_lock:
					frame, self._latest_frame = self._latest_frame, None
				if frame is not None:
					self._show_image(frame)
					redraw = True
			if redraw:
				self.canvas.draw_idle()
			self.root.after(100, self._pump)

		def _handle(self, kind, d):
			if kind == "connected":
				self.stage, self.camera = d["stage"], d["camera"]
				x, y, z = (self.stage.read(c) for c in MOTOR_CHANNELS)
				self.v["x_start"].set(f"{x:.4f}")
				self.v["y_start"].set(f"{y:.4f}")
				self.status.set(f"Connected: camera {self.camera.model} #{self.camera.serial}"
								f"{' (colour sensor, binned to grey)' if self.camera.is_color else ''}; stage at "
								f"X={x:.4f} Y={y:.4f} Z={z:.4f}. Focus roughly by hand, drag an ROI on a "
								f"textured area, then 'Autofocus here' or 'Build focus map'.")
				threading.Thread(target=self._live_loop, daemon=True).start()
				return False
			if kind == "connect_error":
				self.status.set(f"Connection failed: {d['message']}")
				messagebox.showerror("Connection failed", d["message"] + "\n\nClose Motor_GUI and the ThorCam app, then "
									 "restart this program.\nMissing drivers? Run:  python resolution_cv.py --install")
				return False
			if kind == "position":
				x, y, z = d["pos"]
				self.position.set(f"X {x:.4f} | Y {y:.4f} | Z {z:.4f}")
				return False
			if kind == "status":
				self.status.set(d["message"])
				return False
			if kind == "sample":
				self._curve_z.append(d["z"])
				self._curve_s.append(d["score"])
				self._curve_line.set_data(self._curve_z, self._curve_s)
				self.ax_curve.relim()
				self.ax_curve.autoscale_view()
				self._show_image(d["image"])
				self.position.set(f"Z {d['z']:.5f}   score {d['score']:.4f}")
				return True
			if kind == "af_done":
				self._idle()
				r = d.get("result")
				if r is None:
					self.status.set(f"Autofocus: {d.get('message')}")
				else:
					self._mark_best(r)
					self.status.set(f"Autofocus {'OK' if r.ok else 'FAILED'}: z_best={r.z_best:.5f}, contrast "
									f"{r.contrast:.2f}, {len(r.z_samples)} frames in {r.duration_s:.1f}s. {r.reason}")
				return True
			if kind == "map_start":
				return False
			if kind == "point_start":
				self._reset_curve()
				self.status.set(f"Point {d['index'] + 1}/{d['total']}: x={d['x']:.4f}, y={d['y']:.4f}, "
								f"z guess {d['z_guess']:.5f}")
				return True
			if kind == "point":
				r = d["result"]
				self.results.append(r)
				self.progress.configure(value=d["index"] + 1)
				self._mark_best(r)
				self._draw_map()
				return True
			if kind == "map_done":
				self._idle()
				res = d["results"]
				n_ok = sum(r.ok for r in res)
				note = "stopped" if d["stopped"] else f"error: {d['error']}" if d["error"] else "done"
				msg = f"Focus map {note}: {n_ok}/{len(res)} points focused. CSV: {d['csv_path']}"
				failed = [f"({r.x:.3f}, {r.y:.3f}) {r.reason}" for r in res if not r.ok]
				if failed:
					msg += "  Failed: " + "; ".join(failed[:3])
				self.status.set(msg)
				if n_ok:
					self.refit()
					if self.surface is not None:
						self.status.set(self.status.get() + f"  |  {msg}")
				if d.get("csv_path") and res:
					try:
						self.fig.savefig(Path(d["csv_path"]).with_suffix(".png"), dpi=150)
					except Exception:
						pass
				return True
			if kind == "idle":
				self._idle()
			return False

		def _mark_best(self, r: FocusResult):
			self.ax_curve.axvline(r.z_best, color="#16a34a" if r.ok else "#dc2626", ls="--", lw=1)
			self.ax_curve.set_title(f"Focus score vs z  (best {r.z_best:.5f})", fontsize=10, loc="left", fontweight="bold")

		def _idle(self):
			self.stop_btn.configure(state="disabled")
			self.map_btn.configure(state="normal")
			self.af_btn.configure(state="normal")

		def close(self):
			if self._busy():
				if not messagebox.askyesno("Busy", "Autofocus is running. Stop and quit?"):
					return
				self.stop_event.set()
				self.worker.join(timeout=30)
			self._live_stop.set()
			time.sleep(0.2)
			for dev in (self.camera, self.stage):
				if dev is not None:
					try:
						dev.close()
					except Exception as exc:
						print(f"Close warning: {exc}")
			self.root.destroy()

	root = tk.Tk()
	FocusMapApp(root)
	root.mainloop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def snap(metric: str = "laplacian", exposure_ms: float = 20.0, out: Optional[Path] = None) -> None:
	with ThorCam(exposure_us=int(exposure_ms * 1000)) as cam:
		img = cam.grab(2)
		print(f"{cam.model} #{cam.serial}: {img.shape[1]}x{img.shape[0]} grey, mean {img.mean():.1f}, "
			  f"saturated {saturation_fraction(img, cam.max_value):.2%}")
		for m in FOCUS_METRICS:
			print(f"  {m:10s} {focus_score(img, m):.5f}{'  <- selected' if m == metric else ''}")
	out = out or Path.cwd() / f"thorcam_snap_{datetime.now():%Y%m%d_%H%M%S}.png"
	from PIL import Image
	lo, hi = np.percentile(img, (0.5, 99.5))
	Image.fromarray((np.clip((img - lo) / max(hi - lo, 1), 0, 1) * 255).astype(np.uint8)).save(out)
	print(f"Saved {out}")


def selftest() -> None:
	"""Offline check: simulated tilted sample, recover the focus plane from images alone."""
	stage = SimulatedStage(x=0.0, y=0.0, z=2.0)
	camera = SimulatedCamera(stage, focus_plane=(2.0, 0.08, -0.05, 0.0), dof=0.02)
	settings = AutofocusSettings(span=0.06, coarse_step=0.015, fine_step=0.003, settle_s=0.0, n_avg=1,
								 z_min=1.7, z_max=2.3)
	for metric in FOCUS_METRICS:
		settings.metric = metric
		stage.move(X_CHANNEL, 0.1)
		stage.move(Y_CHANNEL, 0.05)
		r = autofocus_at(stage, camera, 2.02, settings)
		truth = camera.z_focus(0.1, 0.05)
		print(f"{metric:10s} z_best={r.z_best:.5f} truth={truth:.5f} err={r.z_best - truth:+.5f} ok={r.ok} "
			  f"contrast={r.contrast:.2f} frames={len(r.z_samples)}")
	settings.metric = "laplacian"
	points = sample_grid(0.0, 0.2, 0.0, 0.1, 3, 3)
	results = build_focus_map(stage, camera, points, settings, threading.Event(), lambda *_: None, z_start=2.0)
	good = [r for r in results if r.ok]
	surface = fit_focus_surface([r.x for r in good], [r.y for r in good], [r.z_best for r in good], order=1)
	print(f"map: {len(good)}/{len(results)} ok, fitted dz/dx={surface.coef[1]:+.4f} (truth +0.0800), "
		  f"dz/dy={surface.coef[2]:+.4f} (truth -0.0500), rms={surface.rms:.5f}")
	for rel in (False, True):
		expr = surface.expression(relative=rel)
		z = validate_expression(expr, 0.3, 0.2, float(surface.predict(0.3, 0.2)))
		print(f"expression (relative={rel}) accepted by scan_helpers.ZFunction; z(0.3, 0.2) = {z:.5f} "
			  f"(truth {camera.z_focus(0.3, 0.2):.5f})")
	print(surface.expression())


def main(argv=None) -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--install", action="store_true", help="extract Thorlabs DLLs and pip install SDK + OpenCV")
	group.add_argument("--snap", action="store_true", help="grab one frame, print focus scores, save PNG")
	group.add_argument("--selftest", action="store_true", help="offline test with simulated camera/stage")
	group.add_argument("--simulate", action="store_true", help="run the GUI with simulated hardware")
	parser.add_argument("--metric", default="laplacian", choices=FOCUS_METRICS)
	parser.add_argument("--exposure-ms", type=float, default=20.0)
	args = parser.parse_args(argv)
	if args.install:
		install_dependencies()
	elif args.snap:
		snap(args.metric, args.exposure_ms)
	elif args.selftest:
		selftest()
	else:
		run_app(simulate=args.simulate)


if __name__ == "__main__":
	main()
