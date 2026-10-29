"""Visual theme (colors, fonts, ttk styles) and small widgets for Motor_GUI.py."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

COLORS = {
	"bg": "#e9edf2",           # window background (gutters between cards)
	"card": "#ffffff",
	"border": "#d5dbe3",
	"text": "#1f2937",
	"muted": "#6b7280",
	"subtle": "#f4f6f9",       # read-only fields / tab bar
	"accent": "#2563eb",
	"accent_hover": "#1d4ed8",
	"accent_pressed": "#1e40af",
	"success": "#16a34a",
	"success_hover": "#15803d",
	"danger": "#dc2626",
	"danger_hover": "#b91c1c",
	"disabled_bg": "#e5e7eb",
	"disabled_fg": "#9ca3af",
	"header": "#1e293b",
	"header_text": "#f8fafc",
	"header_muted": "#94a3b8",
	"error": "#b91c1c",
	"warning": "#b45309",
}

AXIS_COLORS = {1: "#2563eb", 2: "#16a34a", 3: "#9333ea"}

UNIT = "×10⁻¹ mm"

FONTS = {}


def _pick(families, *candidates, default):
	for name in candidates:
		if name in families:
			return name
	return default


def apply_theme(root: tk.Tk) -> None:
	families = set(tkfont.families(root))
	ui = _pick(families, "Segoe UI", "Helvetica Neue", "Arial", default="TkDefaultFont")
	mono = _pick(families, "Cascadia Mono", "Consolas", "Menlo", "Courier New", default="TkFixedFont")

	for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
		tkfont.nametofont(name).configure(family=ui, size=10)

	FONTS.update({
		"ui": (ui, 10),
		"small": (ui, 9),
		"bold": (ui, 10, "bold"),
		"h2": (ui, 12, "bold"),
		"title": (ui, 16, "bold"),
		"readout": (mono, 22, "bold"),
		"mono": (mono, 10),
		"button_big": (ui, 11, "bold"),
	})

	c = COLORS
	root.configure(background=c["bg"])
	style = ttk.Style(root)
	style.theme_use("clam")

	# Default: widgets sit on white cards.
	style.configure(
		".", background=c["card"], foreground=c["text"], font=FONTS["ui"],
		bordercolor=c["border"], lightcolor=c["card"], darkcolor=c["card"],
		troughcolor=c["subtle"], focuscolor=c["accent"], selectbackground=c["accent"],
		selectforeground="white", insertcolor=c["text"],
	)
	style.configure("App.TFrame", background=c["bg"])
	style.configure("Card.TFrame", background=c["card"], borderwidth=1, relief="solid",
					bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"])

	# Header bar
	style.configure("Header.TFrame", background=c["header"])
	style.configure("HeaderTitle.TLabel", background=c["header"], foreground=c["header_text"], font=FONTS["title"])
	style.configure("HeaderSub.TLabel", background=c["header"], foreground=c["header_muted"], font=FONTS["small"])
	style.configure("PillOK.TLabel", background="#dcfce7", foreground="#166534", font=FONTS["bold"], padding=(12, 3))
	style.configure("PillBad.TLabel", background="#fee2e2", foreground="#991b1b", font=FONTS["bold"], padding=(12, 3))

	# Labels
	style.configure("H2.TLabel", font=FONTS["h2"])
	style.configure("Bold.TLabel", font=FONTS["bold"])
	style.configure("Muted.TLabel", foreground=c["muted"], font=FONTS["small"])
	style.configure("Error.TLabel", foreground=c["error"], font=FONTS["small"])
	style.configure("Warn.TLabel", foreground=c["warning"], font=FONTS["small"])
	style.configure("Readout.TLabel", background=c["subtle"], foreground=c["text"], font=FONTS["readout"],
					padding=(12, 2), anchor="e")
	style.configure("ReadoutUnit.TLabel", background=c["subtle"], foreground=c["muted"], font=FONTS["small"],
					padding=(0, 0, 10, 0))
	style.configure("Readout.TFrame", background=c["subtle"])
	style.configure("Status.TLabel", foreground=c["muted"])
	style.configure("StatusError.TLabel", foreground=c["error"])
	style.configure("StatusOK.TLabel", foreground=c["success"])

	# Buttons
	style.configure("TButton", background=c["subtle"], foreground=c["text"], bordercolor=c["border"],
					lightcolor=c["subtle"], darkcolor=c["subtle"], padding=(10, 4), focusthickness=0)
	style.map("TButton",
			  background=[("disabled", c["disabled_bg"]), ("pressed", "#dfe4ea"), ("active", "#e8ecf1")],
			  foreground=[("disabled", c["disabled_fg"])],
			  lightcolor=[("pressed", "#dfe4ea"), ("active", "#e8ecf1")],
			  darkcolor=[("pressed", "#dfe4ea"), ("active", "#e8ecf1")])
	for name, base, hover, pressed, font in (
		("Accent", c["accent"], c["accent_hover"], c["accent_pressed"], FONTS["bold"]),
		("Success", c["success"], c["success_hover"], c["success_hover"], FONTS["button_big"]),
		("Danger", c["danger"], c["danger_hover"], c["danger_hover"], FONTS["button_big"]),
	):
		style.configure(f"{name}.TButton", background=base, foreground="white", bordercolor=base,
						lightcolor=base, darkcolor=base, font=font, padding=(14, 5))
		style.map(f"{name}.TButton",
				  background=[("disabled", c["disabled_bg"]), ("pressed", pressed), ("active", hover)],
				  foreground=[("disabled", c["disabled_fg"])],
				  bordercolor=[("disabled", c["disabled_bg"]), ("active", hover)],
				  lightcolor=[("disabled", c["disabled_bg"]), ("pressed", pressed), ("active", hover)],
				  darkcolor=[("disabled", c["disabled_bg"]), ("pressed", pressed), ("active", hover)])

	# Inputs
	style.configure("TEntry", fieldbackground="white", bordercolor=c["border"], lightcolor="white",
					darkcolor="white", padding=(6, 3))
	style.map("TEntry",
			  bordercolor=[("focus", c["accent"])],
			  lightcolor=[("focus", c["accent"])],
			  fieldbackground=[("readonly", c["subtle"]), ("disabled", c["subtle"])])
	style.configure("TCheckbutton", indicatorbackground="white", indicatorforeground="white",
					indicatormargin=(0, 0, 6, 0), padding=(0, 2))
	style.map("TCheckbutton",
			  indicatorbackground=[("selected", c["accent"]), ("active", "#eef2ff")],
			  background=[("active", c["card"])])

	# Group boxes
	style.configure("TLabelframe", background=c["card"], bordercolor=c["border"], lightcolor=c["card"],
					darkcolor=c["card"], relief="solid", borderwidth=1, padding=8)
	style.configure("TLabelframe.Label", background=c["card"], foreground=c["muted"], font=FONTS["bold"])

	# Tabs
	style.configure("TNotebook", background=c["card"], bordercolor=c["border"], lightcolor=c["card"],
					darkcolor=c["card"], tabmargins=(0, 0, 0, 0))
	style.configure("TNotebook.Tab", background=c["subtle"], foreground=c["muted"], padding=(14, 6),
					bordercolor=c["border"], lightcolor=c["subtle"], darkcolor=c["subtle"], font=FONTS["bold"])
	style.map("TNotebook.Tab",
			  background=[("selected", c["card"]), ("active", "#eceff3")],
			  foreground=[("selected", c["accent"])],
			  lightcolor=[("selected", c["card"])],
			  expand=[("selected", (0, 2, 0, 0))])

	style.configure("Horizontal.TProgressbar", troughcolor=c["subtle"], background=c["success"],
					bordercolor=c["border"], lightcolor=c["success"], darkcolor=c["success"], thickness=16)
	style.configure("TScrollbar", background=c["subtle"], troughcolor=c["card"], bordercolor=c["card"],
					arrowcolor=c["muted"], lightcolor=c["subtle"], darkcolor=c["subtle"])
	style.configure("TSeparator", background=c["border"])


def style_text_widget(widget: tk.Text) -> None:
	c = COLORS
	widget.configure(
		font=FONTS["mono"], background="#fbfcfe", foreground=c["text"], insertbackground=c["text"],
		relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=c["border"],
		highlightcolor=c["accent"], padx=8, pady=6, selectbackground=c["accent"], selectforeground="white",
	)


def style_mpl_toolbar(toolbar) -> None:
	"""Make the (plain Tk) matplotlib toolbar blend into a white card."""
	for widget in (toolbar, *toolbar.winfo_children()):
		try:
			widget.configure(background=COLORS["card"])
		except tk.TclError:
			pass


def status_style(message: str, base: str = "Status") -> str:
	"""Pick a label style from the content of a status message."""
	text = message.lower()
	if any(word in text for word in ("error", "failed", "invalid", "unavailable", "could not", "must be", "warning")):
		return f"{base}Error.TLabel"
	if any(word in text for word in ("completed", "complete", "moved to", "start set")):
		return f"{base}OK.TLabel"
	return f"{base}.TLabel"


class Tooltip:
	"""Minimal hover tooltip."""

	def __init__(self, widget, text, delay_ms=450):
		self.widget, self.text, self.delay_ms = widget, text, delay_ms
		self._after_id = None
		self._tip = None
		widget.bind("<Enter>", self._schedule, add="+")
		widget.bind("<Leave>", self._hide, add="+")
		widget.bind("<ButtonPress>", self._hide, add="+")

	def _schedule(self, _event=None):
		self._cancel()
		self._after_id = self.widget.after(self.delay_ms, self._show)

	def _cancel(self):
		if self._after_id:
			self.widget.after_cancel(self._after_id)
			self._after_id = None

	def _show(self):
		if self._tip or not self.text:
			return
		x = self.widget.winfo_rootx() + 12
		y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
		self._tip = tip = tk.Toplevel(self.widget)
		tip.wm_overrideredirect(True)
		tip.wm_geometry(f"+{x}+{y}")
		tk.Label(tip, text=self.text, justify="left", wraplength=360, background="#111827", foreground="white",
				 font=FONTS.get("small"), padx=8, pady=5).pack()

	def _hide(self, _event=None):
		self._cancel()
		if self._tip:
			self._tip.destroy()
			self._tip = None
