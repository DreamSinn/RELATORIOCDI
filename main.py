from __future__ import annotations

import json
import os
import random
import threading
import time
import tkinter as tk
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, simpledialog

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

try:
    import ctypes
    import win32api
    import win32con
    import win32gui
    import win32ui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    from license_client import LicenseClient
except ImportError:
    LicenseClient = None

user32 = ctypes.WinDLL("user32", use_last_error=True) if HAS_WIN32 else None
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 1, 0x0002, 0x0008

if HAS_WIN32:
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("ki", KEYBDINPUT)]


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"
SETTINGS_PATH = DATA_DIR / "settings.json"
PROFILES_PATH = DATA_DIR / "profiles.json"
LICENSE_CACHE_PATH = DATA_DIR / "license_cache.json"
LICENSE_MANIFEST_URL = "https://raw.githubusercontent.com/DreamSinn/RELATORIOCDI/main/data/licenses.json"

DEFAULT_SETTINGS = {
    "window_title_contains": "Royal Quest",
    "image1_path": "assets/imagem1.png",
    "image2_path": "assets/imagem2.png",
    "image1_region": [0, 0, 0, 0],
    "image2_region": [0, 0, 0, 0],
    "key": "1",
    "input_method": "SendInput scan code",
    "threshold": 0.88,
    "poll_interval_ms": 120,
    "start_timeout_s": 15,
    "trigger_timeout_s": 120,
    "post_trigger_delay_s": 2.0,
    "trigger_consecutive_frames": 2,
    "dry_run": False,
    "bag_enabled": False,
    "bag_key": "B",
    "bag_interval_s": 24.0,
    "avatar_path": "assets/avatar_daros.png",
}

AVATAR_POOL = [
    "assets/avatar_daros.png",
    "assets/avatar_mistake.png",
    "assets/avatar_riplay.png",
    "assets/avatar_lake.png",
    "assets/avatar_gold.png",
]


def load_settings() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            result = DEFAULT_SETTINGS.copy()
            result.update(data)
            return result
        except (OSError, ValueError):
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    temp = SETTINGS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(SETTINGS_PATH)


def load_profiles() -> dict[str, dict]:
    DATA_DIR.mkdir(exist_ok=True)
    if PROFILES_PATH.exists():
        try:
            raw = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw:
                changed = False
                for index, (name, profile) in enumerate(raw.items()):
                    if "avatar_path" not in profile:
                        profile["avatar_path"] = AVATAR_POOL[index % len(AVATAR_POOL)]
                        changed = True
                if changed:
                    PROFILES_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
                return raw
        except (OSError, ValueError):
            pass
    profile = load_settings()
    profiles = {"Principal": profile}
    PROFILES_PATH.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
    return profiles


def save_profiles(profiles: dict[str, dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    temp = PROFILES_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(PROFILES_PATH)


@dataclass
class Rect:
    x1: int
    y1: int
    x2: int
    y2: int

    @classmethod
    def from_text(cls, text: str) -> "Rect":
        values = [int(v.strip()) for v in text.split(",")]
        if len(values) != 4:
            raise ValueError("Use x1, y1, x2, y2")
        x1, y1, x2, y2 = values
        return cls(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    @classmethod
    def from_list(cls, values: list[int]) -> "Rect":
        return cls(*values)

    def to_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]

    def valid(self) -> bool:
        return self.x2 > self.x1 and self.y2 > self.y1


class WindowCapture:
    @staticmethod
    def find_windows(title_part: str) -> list[tuple[str, int]]:
        if not HAS_WIN32:
            return []
        found = []
        needle = title_part.lower().strip()

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and needle in title.lower():
                    found.append((title, hwnd))
            return True

        win32gui.EnumWindows(callback, None)
        return found

    @staticmethod
    def capture(hwnd: int):
        if not HAS_WIN32 or cv2 is None or not win32gui.IsWindow(hwnd):
            return None
        full_left, full_top, full_right, full_bottom = win32gui.GetWindowRect(hwnd)
        full_width, full_height = full_right - full_left, full_bottom - full_top
        client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)
        client_width, client_height = client_right - client_left, client_bottom - client_top
        if full_width <= 0 or full_height <= 0 or client_width <= 0 or client_height <= 0:
            return None
        client_origin = win32gui.ClientToScreen(hwnd, (0, 0))
        offset_x = client_origin[0] - full_left
        offset_y = client_origin[1] - full_top
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(src_dc, full_width, full_height)
        mem_dc.SelectObject(bitmap)
        try:
            result = ctypes.windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 3)
            if not result:
                mem_dc.BitBlt((0, 0), (full_width, full_height), src_dc, (0, 0), win32con.SRCCOPY)
            info = bitmap.GetInfo()
            raw = bitmap.GetBitmapBits(True)
            image = np.frombuffer(raw, dtype=np.uint8).reshape((info["bmHeight"], info["bmWidth"], 4))
            client_image = image[offset_y:offset_y + client_height, offset_x:offset_x + client_width]
            if client_image.size == 0:
                return None
            return cv2.cvtColor(client_image, cv2.COLOR_BGRA2BGR)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            mem_dc.DeleteDC()
            src_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)


class ImageMatcher:
    SCALE_FACTORS = (0.82, 0.88, 0.94, 1.0, 1.06, 1.12, 1.18)

    @staticmethod
    def crop(image, rect: Rect):
        if image is None or not rect.valid():
            return None
        h, w = image.shape[:2]
        x1, y1 = max(0, rect.x1), max(0, rect.y1)
        x2, y2 = min(w, rect.x2), min(h, rect.y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return image[y1:y2, x1:x2]

    @staticmethod
    def score(image, template_path: str, region: Rect) -> float:
        if cv2 is None or image is None:
            return 0.0
        template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        if template is None or not region.valid():
            return 0.0
        h, w = image.shape[:2]
        region_width = region.x2 - region.x1
        region_height = region.y2 - region.y1
        target_width = max(region_width * 2, template.shape[1] * 2)
        target_height = max(region_height * 2, template.shape[0] * 2)
        center_x = (region.x1 + region.x2) // 2
        center_y = (region.y1 + region.y2) // 2
        search_region = Rect(
            max(0, center_x - target_width // 2),
            max(0, center_y - target_height // 2),
            min(w, center_x + target_width // 2),
            min(h, center_y + target_height // 2),
        )
        area = ImageMatcher.crop(image, search_region)
        if area is None:
            return 0.0
        scores = []
        area_gray = cv2.cvtColor(area, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        for factor in ImageMatcher.SCALE_FACTORS:
            width = max(2, round(template.shape[1] * factor))
            height = max(2, round(template.shape[0] * factor))
            scaled = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC)
            scaled_gray = cv2.resize(template_gray, (width, height), interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC)
            if area.shape[0] >= height and area.shape[1] >= width:
                result = cv2.matchTemplate(area, scaled, cv2.TM_SQDIFF_NORMED)
                difference, _, location, _ = cv2.minMaxLoc(result)
                patch = area[location[1]:location[1] + height, location[0]:location[0] + width]
                pixel_similarity = 1.0 - float(np.mean(cv2.absdiff(patch, scaled))) / 255.0
                scores.append(max(0.0, min(1.0 - float(difference), pixel_similarity)))
            if area_gray.shape[0] >= height and area_gray.shape[1] >= width:
                result_gray = cv2.matchTemplate(area_gray, scaled_gray, cv2.TM_SQDIFF_NORMED)
                difference_gray, _, location_gray, _ = cv2.minMaxLoc(result_gray)
                patch_gray = area_gray[location_gray[1]:location_gray[1] + height, location_gray[0]:location_gray[0] + width]
                gray_similarity = 1.0 - float(np.mean(cv2.absdiff(patch_gray, scaled_gray))) / 255.0
                scores.append(max(0.0, min(1.0 - float(difference_gray), gray_similarity)))
        return max(scores, default=0.0)


class VirtualKeyboard:
    METHODS = ("SendInput scan code", "keybd_event scan code", "PostMessage segundo plano")
    SPECIAL = {
        "ENTER": 0x0D, "SPACE": 0x20, "TAB": 0x09, "ESC": 0x1B,
        "ESCAPE": 0x1B, "BACKSPACE": 0x08, "UP": 0x26, "DOWN": 0x28,
        "LEFT": 0x25, "RIGHT": 0x27,
    }

    @classmethod
    def key_code(cls, key: str) -> int:
        value = key.strip().upper()
        if value in cls.SPECIAL:
            return cls.SPECIAL[value]
        if value.startswith("F") and value[1:].isdigit():
            number = int(value[1:])
            if 1 <= number <= 24:
                return (win32con.VK_F1 if HAS_WIN32 else 0x70) + number - 1
        if len(value) == 1:
            return (win32api.VkKeyScan(value) & 0xFF) if HAS_WIN32 else ord(value)
        raise ValueError("Tecla inválida. Exemplos: 1, F1, E, SPACE, ENTER")

    @classmethod
    def scan_code(cls, vk: int) -> int:
        if HAS_WIN32:
            scan = user32.MapVirtualKeyW(vk, 0)
            if scan:
                return int(scan)
        fallback = {"1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B}
        return fallback.get(chr(vk), vk)

    @classmethod
    def press(cls, hwnd: int, key: str, method: str = "SendInput scan code") -> None:
        if not HAS_WIN32 or not win32gui.IsWindow(hwnd):
            raise RuntimeError("Janela ou suporte Win32 indisponível")
        vk = cls.key_code(key)
        scan = cls.scan_code(vk)
        hold_ms = 50
        if method == "SendInput scan code":
            user32.SetForegroundWindow(hwnd)
            extra = ctypes.pointer(ctypes.c_ulong(0))
            down = INPUT(INPUT_KEYBOARD, KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE, 0, extra))
            up = INPUT(INPUT_KEYBOARD, KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0, extra))
            user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
            time.sleep(hold_ms / 1000.0)
            user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
        elif method == "keybd_event scan code":
            user32.SetForegroundWindow(hwnd)
            user32.keybd_event(0, scan, 0, 0)
            time.sleep(hold_ms / 1000.0)
            user32.keybd_event(0, scan, KEYEVENTF_KEYUP, 0)
        else:
            down_lparam = 1 | (scan << 16)
            up_lparam = 0xC0000001 | (scan << 16)
            win32gui.PostMessage(hwnd, WM_KEYDOWN, vk, down_lparam)
            time.sleep(hold_ms / 1000.0)
            win32gui.PostMessage(hwnd, WM_KEYUP, vk, up_lparam)


class CalibrationOverlay:
    def __init__(self, parent, image, callback):
        self.callback = callback
        self.image = image
        self.zoom = 3.0
        self.photo = None
        self.rect_id = None
        self.start = None
        self.closed = False
        self.top = tk.Toplevel(parent)
        self.top.title("FI$H — Calibrar região com zoom")
        self.top.geometry("1200x800")
        self.top.minsize(800, 600)
        self.top.transient(parent)
        self.top.grab_set()
        toolbar = tk.Frame(self.top, bg="#201713", padx=10, pady=8)
        toolbar.pack(fill="x")
        tk.Label(toolbar, text="CALIBRAÇÃO PRECISA", bg="#201713", fg="#f4c95d", font=("Courier New", 12, "bold")).pack(side="left")
        tk.Button(toolbar, text="−", command=lambda: self.set_zoom(self.zoom - 0.5), bg="#6b3e17", fg="#fff1c4", relief="flat", width=3).pack(side="left", padx=(18, 4))
        tk.Button(toolbar, text="+", command=lambda: self.set_zoom(self.zoom + 0.5), bg="#6b3e17", fg="#fff1c4", relief="flat", width=3).pack(side="left")
        self.zoom_var = tk.StringVar()
        tk.Label(toolbar, textvariable=self.zoom_var, bg="#201713", fg="#ead7b6", font=("Courier New", 10, "bold")).pack(side="left", padx=10)
        tk.Label(toolbar, text="Arraste sobre o ícone. Ctrl + roda também altera o zoom. ESC cancela.", bg="#201713", fg="#ead7b6").pack(side="left", padx=10)
        body = tk.Frame(self.top, bg="#0b1020")
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, cursor="crosshair", bg="#0b1020", highlightthickness=0)
        xbar = tk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        ybar = tk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self._render()
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Control-MouseWheel>", self.wheel_zoom)
        self.top.bind("<Escape>", lambda _: self.close(None))
        self.top.focus_force()

    def set_zoom(self, value):
        self.zoom = max(1.0, min(8.0, value))
        self._render()

    def wheel_zoom(self, event):
        self.set_zoom(self.zoom + (0.5 if event.delta > 0 else -0.5))

    def _render(self):
        if cv2 is None or self.image is None:
            return
        from PIL import Image, ImageTk
        rgb = cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB)
        source = Image.fromarray(rgb)
        width = max(1, round(source.width * self.zoom))
        height = max(1, round(source.height * self.zoom))
        enlarged = source.resize((width, height), Image.Resampling.NEAREST)
        self.photo = ImageTk.PhotoImage(enlarged)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.create_text(12, 12, anchor="nw", fill="#ffe3a4", text=f"ZOOM {self.zoom:.1f}x  |  imagem original: {source.width}x{source.height}", font=("Courier New", 11, "bold"))
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self.zoom_var.set(f"Zoom: {self.zoom:.1f}x")

    def press(self, event):
        self.start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.rect_id = self.canvas.create_rectangle(*self.start, *self.start, outline="#ffcf5a", width=3)

    def drag(self, event):
        if self.rect_id and self.start:
            x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            self.canvas.coords(self.rect_id, self.start[0], self.start[1], x, y)

    def release(self, event):
        if self.start:
            x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            rect = Rect(
                round(min(self.start[0], x) / self.zoom),
                round(min(self.start[1], y) / self.zoom),
                round(max(self.start[0], x) / self.zoom),
                round(max(self.start[1], y) / self.zoom),
            )
            self.close(rect)

    def close(self, rect):
        if self.closed:
            return
        self.closed = True
        self.top.grab_release()
        self.top.destroy()
        self.callback(rect)


class TriggerBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FI$H — Visual Trigger")
        self.root.geometry("760x600")
        self.root.resizable(False, False)
        self.root.configure(bg="#0b1020")
        self.profiles = load_profiles()
        self.profile_name = next(iter(self.profiles))
        self.settings = self.profiles[self.profile_name].copy()
        self.hwnd = None
        self.stop_event = threading.Event()
        self.worker = None
        self.instances = {}
        self.window_reservations = {}
        self.window_locks = {}
        self.state = "PARADO"
        self.vars = {}
        self.license_client = LicenseClient(
            manifest_url=LICENSE_MANIFEST_URL,
            cache_path=LICENSE_CACHE_PATH,
        ) if LicenseClient else None
        self.license_key_var = tk.StringVar()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._show_license_gate()

    def _show_license_gate(self):
        self.root.withdraw()
        self.root.deiconify()
        for child in self.root.winfo_children():
            child.destroy()
        self.root.title("FI$H — Ativação de licença")
        gate = tk.Frame(self.root, bg="#201713", padx=38, pady=32)
        gate.pack(fill="both", expand=True)
        tk.Label(gate, text="FI$H", bg="#201713", fg="#f4c95d", font=("Courier New", 30, "bold")).pack(pady=(28, 0))
        tk.Label(gate, text="PESCARIA VISUAL", bg="#201713", fg="#ffe3a4", font=("Courier New", 11, "bold")).pack(pady=(0, 22))
        tk.Label(gate, text="ATIVAÇÃO NECESSÁRIA", bg="#201713", fg="#67e0c2", font=("Courier New", 13, "bold")).pack(pady=(4, 8))
        tk.Label(gate, text="Digite sua chave de licença para liberar o FI$H.", bg="#201713", fg="#ead7b6", font=("Courier New", 9)).pack()
        tk.Label(gate, text="A chave será validada pelo manifesto oficial do projeto.", bg="#201713", fg="#bda88b", font=("Courier New", 8)).pack(pady=(2, 18))
        entry = tk.Entry(gate, textvariable=self.license_key_var, width=34, justify="center", bg="#39231a", fg="#ffe3a4", insertbackground="#ffe3a4", relief="flat", font=("Courier New", 12, "bold"))
        entry.pack(ipady=8, pady=(0, 12))
        entry.focus_set()
        self.license_status_var = tk.StringVar(value="")
        tk.Label(gate, textvariable=self.license_status_var, bg="#201713", fg="#ff9b76", font=("Courier New", 8), wraplength=520).pack(pady=(0, 12))
        activate_button = tk.Button(gate, text="ATIVAR LICENÇA", command=self._activate_license, bg="#9a5a20", fg="#fff0bf", activebackground="#c1782a", activeforeground="#ffffff", relief="raised", font=("Courier New", 10, "bold"), padx=18, pady=8)
        activate_button.pack()
        tk.Label(gate, text="Manifesto: GitHub / data/licenses.json", bg="#201713", fg="#8f7b65", font=("Courier New", 8)).pack(side="bottom", pady=(20, 0))
        entry.bind("<Return>", lambda _event: self._activate_license())

    def _activate_license(self):
        key = self.license_key_var.get().strip()
        if not key:
            self.license_status_var.set("Digite uma chave de licença.")
            return
        if not self.license_client:
            self.license_status_var.set("Módulo de licença indisponível.")
            return
        self.license_status_var.set("Consultando o manifesto do GitHub...")
        self.root.update_idletasks()
        try:
            result = self.license_client.activate(key)
        except Exception as exc:
            self.license_status_var.set(f"Não foi possível consultar o manifesto: {exc}")
            return
        if not result.get("success"):
            self.license_status_var.set(result.get("message", "Licença inválida."))
            return
        self.license_key = key
        self._build_ui()
        self.refresh_windows()
        self.root.title("FI$H — Visual Trigger")

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#201713")
        style.configure("TLabel", background="#201713", foreground="#f2d5a1")
        style.configure("TLabelframe", background="#201713", foreground="#f1b95e")
        style.configure("TLabelframe.Label", background="#201713", foreground="#f1b95e", font=("Courier New", 9, "bold"))
        style.configure("TNotebook", background="#1a100b", borderwidth=0)
        style.configure("TNotebook.Tab", background="#4a2a14", foreground="#d9bd8a", padding=(11, 5), font=("Courier New", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#9a5a20")], foreground=[("selected", "#fff0bf")])
        style.configure("TButton", background="#5d3416", foreground="#ffe3a4", padding=(7, 4), borderwidth=1, relief="raised", font=("Courier New", 8, "bold"))
        style.map("TButton", background=[("active", "#a26627")], foreground=[("active", "#fff4d0")])
        style.configure("TEntry", fieldbackground="#39231a", foreground="#ffe3a4", insertcolor="#ffe3a4", borderwidth=1)
        style.configure("TCombobox", fieldbackground="#39231a", foreground="#ffe3a4", background="#5d3416", arrowcolor="#f4c95d")
        style.map("TCombobox", fieldbackground=[("readonly", "#39231a")], foreground=[("readonly", "#ffe3a4")], selectbackground=[("readonly", "#6b3e17")], selectforeground=[("readonly", "#fff1c4")])
        style.configure("TCheckbutton", background="#201713", foreground="#ead7b6")
        style.configure("Vertical.TScrollbar", background="#6b3e17", troughcolor="#1a100b", arrowcolor="#f4c95d")
        skin_path = ASSETS_DIR / "fish_panel_760x600.png"
        if HAS_PIL and skin_path.exists():
            skin = Image.open(skin_path).convert("RGB")
            self.skin_photo = ImageTk.PhotoImage(skin)
            tk.Label(self.root, image=self.skin_photo, bd=0).place(x=0, y=0, width=760, height=600)
        main = tk.Frame(self.root, bg="#201713", padx=8, pady=6)
        main.pack(fill="both", expand=True, padx=62, pady=50)
        header = tk.Frame(main, height=45, bg="#3b2111", highlightthickness=1, highlightbackground="#b8782a")
        header.pack(fill="x", pady=(0, 6))
        header.pack_propagate(False)
        tk.Label(header, text="FI$H", font=("Courier New", 21, "bold"), fg="#f4c95d", bg="#3b2111").pack(side="left", padx=12)
        tk.Label(header, text="PESCARIA VISUAL", font=("Courier New", 10, "bold"), fg="#ffe3a4", bg="#3b2111").pack(side="left", padx=5)
        tk.Label(header, text="◆", font=("Courier New", 14, "bold"), fg="#67e0c2", bg="#3b2111").pack(side="right", padx=14)

        profiles_box = ttk.LabelFrame(main, text="Perfis / instâncias", padding=5)
        profiles_box.pack(fill="x", pady=3)
        tk.Label(profiles_box, text="Perfil ativo:", bg="#201713", fg="#f2d5a1", font=("Courier New", 9, "bold")).pack(side="left", padx=(2, 6))
        self.profile_var = tk.StringVar(value=self.profile_name)
        self.profile_combo = ttk.Combobox(profiles_box, textvariable=self.profile_var, state="readonly", values=list(self.profiles), width=20)
        self.profile_combo.pack(side="left")
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _event: self.switch_profile(self.profile_var.get()))
        self.avatar_label = tk.Label(profiles_box, bg="#201713", bd=0)
        self.avatar_label.pack(side="left", padx=(8, 3))
        ttk.Button(profiles_box, text="Novo", command=self.new_profile).pack(side="left", padx=4)
        ttk.Button(profiles_box, text="Renomear", command=self.rename_profile).pack(side="left")
        ttk.Button(profiles_box, text="Excluir", command=self.delete_profile).pack(side="left", padx=4)
        self.profile_status_var = tk.StringVar(value="Instância parada")
        ttk.Label(profiles_box, textvariable=self.profile_status_var).pack(side="right", padx=6)

        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill="both", expand=True, pady=(2, 0))
        control_tab = ttk.Frame(self.notebook, padding=8)
        config_shell = ttk.Frame(self.notebook, padding=2)
        config_canvas = tk.Canvas(config_shell, bg="#201713", highlightthickness=0, bd=0)
        config_scroll = ttk.Scrollbar(config_shell, orient="vertical", command=config_canvas.yview)
        config_canvas.configure(yscrollcommand=config_scroll.set)
        config_canvas.pack(side="left", fill="both", expand=True)
        config_scroll.pack(side="right", fill="y")
        config_tab = ttk.Frame(config_canvas, padding=8)
        config_window = config_canvas.create_window((0, 0), window=config_tab, anchor="nw")
        config_tab.bind("<Configure>", lambda _event: config_canvas.configure(scrollregion=config_canvas.bbox("all")))
        config_canvas.bind("<Configure>", lambda event: config_canvas.itemconfigure(config_window, width=event.width))
        def config_wheel(event):
            if self.notebook.select() == str(config_shell):
                if getattr(event, "delta", 0):
                    config_canvas.yview_scroll(-int(event.delta / 120), "units")
                elif getattr(event, "num", None) == 4:
                    config_canvas.yview_scroll(-3, "units")
                elif getattr(event, "num", None) == 5:
                    config_canvas.yview_scroll(3, "units")
        config_canvas.bind_all("<MouseWheel>", config_wheel)
        config_canvas.bind_all("<Button-4>", config_wheel)
        config_canvas.bind_all("<Button-5>", config_wheel)
        instances_tab = ttk.Frame(self.notebook, padding=8)
        logs_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(control_tab, text="Controle")
        self.notebook.add(config_shell, text="Configuração")
        self.notebook.add(instances_tab, text="Instâncias")
        self.notebook.add(logs_tab, text="Logs")

        window_box = ttk.LabelFrame(control_tab, text="Janela do jogo", padding=5)
        window_box.pack(fill="x", pady=4)
        self.window_combo = ttk.Combobox(window_box, state="readonly")
        self.window_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(window_box, text="Atualizar", command=self.refresh_windows).pack(side="left", padx=(5, 0))

        files = ttk.LabelFrame(config_tab, text="Imagens e regiões", padding=7)
        files.pack(fill="x", pady=4)
        self._file_row(files, "Imagem 1 — ação", "image1_path")
        self._file_row(files, "Imagem 2 — gatilho", "image2_path")
        self._region_row(files, "Região Imagem 1", "image1_region")
        self._region_row(files, "Região Imagem 2", "image2_region")

        behavior = ttk.LabelFrame(config_tab, text="Comportamento", padding=7)
        behavior.pack(fill="x", pady=4)
        behavior_grid = ttk.Frame(behavior)
        behavior_grid.pack(fill="x")
        compact_fields = [
            ("Tecla", "key"), ("Threshold", "threshold"),
            ("Leitura (ms)", "poll_interval_ms"), ("Timeout Imagem 1 (s)", "start_timeout_s"),
            ("Timeout Imagem 2 (s)", "trigger_timeout_s"), ("Aguardar após Imagem 2 (s)", "post_trigger_delay_s"),
            ("Frames consecutivos", "trigger_consecutive_frames"), ("Tecla da bolsa", "bag_key"),
            ("Intervalo bolsa (s)", "bag_interval_s"),
        ]
        for index, (label, key) in enumerate(compact_fields):
            row, column = divmod(index, 2)
            ttk.Label(behavior_grid, text=label, width=28).grid(row=row, column=column * 2, sticky="w", padx=(2, 6), pady=2)
            var = tk.StringVar(value=str(self.settings.get(key, DEFAULT_SETTINGS.get(key, ""))))
            self.vars[key] = var
            ttk.Entry(behavior_grid, textvariable=var, width=14).grid(row=row, column=column * 2 + 1, sticky="w", padx=(0, 14), pady=2)
        behavior_grid.columnconfigure(1, weight=1)
        behavior_grid.columnconfigure(3, weight=1)
        self.dry_run = tk.BooleanVar(value=bool(self.settings.get("dry_run", True)))
        self.bag_enabled = tk.BooleanVar(value=bool(self.settings.get("bag_enabled", False)))
        dry_run_frame = ttk.Frame(behavior)
        dry_run_frame.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(dry_run_frame, text="Modo de teste: não enviar tecla real", variable=self.dry_run).pack(side="left", padx=4)
        ttk.Checkbutton(dry_run_frame, text="Abrir bolsa automaticamente", variable=self.bag_enabled).pack(side="left", padx=14)
        method_row = ttk.Frame(behavior)
        method_row.pack(fill="x", pady=(6, 0))
        tk.Label(method_row, text="Método de entrada", width=22, bg="#201713", fg="#f2d5a1", font=("Courier New", 9, "bold"), anchor="w").pack(side="left")
        self.input_method = tk.StringVar(value=self.settings.get("input_method", "SendInput scan code"))
        ttk.Combobox(method_row, textvariable=self.input_method, state="readonly", values=VirtualKeyboard.METHODS, width=29).pack(side="left")
        tk.Label(method_row, text="Recomendado: SendInput", bg="#201713", fg="#c99b5c", font=("Courier New", 8)).pack(side="left", padx=8)

        actions = ttk.Frame(control_tab)
        actions.pack(fill="x", pady=10)
        ttk.Button(actions, text="Salvar configuração", command=self.save).pack(side="left")
        ttk.Button(actions, text="BLOQUEAR JANELA", command=self.block_window).pack(side="left", padx=6)
        ttk.Button(actions, text="DESBLOQUEAR", command=self.unlock_window).pack(side="left")
        ttk.Button(actions, text="Testar leitura", command=self.test_images).pack(side="left", padx=6)
        ttk.Button(actions, text="INICIAR MONITOR", command=self.start, state="normal").pack(side="left", padx=6)
        ttk.Button(actions, text="PARADA DE EMERGÊNCIA", command=self.stop, style="Danger.TButton").pack(side="left", padx=6)
        ttk.Button(actions, text="Testar tecla", command=self.test_key).pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="PARADO")
        status_bar = tk.Frame(control_tab, bg="#111a33", highlightthickness=1, highlightbackground="#27345c")
        status_bar.pack(fill="x", pady=(0, 4))
        tk.Label(status_bar, text="STATUS", font=("Segoe UI", 9, "bold"), fg="#9aa8c7", bg="#111a33").pack(side="left", padx=12, pady=8)
        tk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 11, "bold"), fg="#62e6c5", bg="#111a33").pack(side="left", pady=8)
        self.log = tk.Text(logs_tab, height=12, state="disabled", bg="#101827", fg="#dce9f2", insertbackground="#ffffff", relief="flat", bd=0)
        self.log.pack(fill="both", expand=True)
        ttk.Label(logs_tab, text="Os eventos são identificados pelo nome do perfil.").pack(anchor="w", pady=(5, 0))
        ttk.Label(instances_tab, text="Cada perfil pode executar em sua própria janela, simultaneamente.").pack(anchor="w")
        self.instances_list = tk.Listbox(instances_tab, height=8, bg="#101827", fg="#dce9f2", relief="flat", bd=0, highlightthickness=0)
        self.instances_list.pack(fill="both", expand=True, pady=8)
        ttk.Button(instances_tab, text="Atualizar estado das instâncias", command=self.refresh_instances_view).pack(anchor="e")
        style.configure("Danger.TButton", foreground="#a40000")
        self.update_avatar()

    def _file_row(self, parent, label, key):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=24).pack(side="left")
        var = tk.StringVar(value=self.settings.get(key, ""))
        self.vars[key] = var
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Escolher", command=lambda: self.choose_file(key)).pack(side="left", padx=5)

    def _region_row(self, parent, label, key):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=24).pack(side="left")
        var = tk.StringVar(value=", ".join(map(str, self.settings.get(key, [0, 0, 0, 0]))))
        self.vars[key] = var
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Marcar na tela", command=lambda: self.calibrate(key)).pack(side="left", padx=5)

    def _entry_row(self, parent, label, key):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=24).pack(side="left")
        var = tk.StringVar(value=str(self.settings.get(key, "")))
        self.vars[key] = var
        ttk.Entry(row, textvariable=var, width=20).pack(side="left")

    def switch_profile(self, name):
        if name not in self.profiles or name == self.profile_name:
            return
        self.save_profile(silent=True)
        self.profile_name = name
        self.settings = self.profiles[name].copy()
        for key, var in self.vars.items():
            value = self.settings.get(key, DEFAULT_SETTINGS.get(key, ""))
            var.set(", ".join(map(str, value)) if key.endswith("_region") else str(value))
        self.dry_run.set(bool(self.settings.get("dry_run", True)))
        self.bag_enabled.set(bool(self.settings.get("bag_enabled", False)))
        self.input_method.set(self.settings.get("input_method", "SendInput scan code"))
        self.update_avatar()
        self.refresh_windows()
        self.log_message(f"Perfil carregado: {name}")
        self.update_profile_status()

    def save_profile(self, silent=False):
        data = self.read_config()
        data["avatar_path"] = self.profiles.get(self.profile_name, {}).get("avatar_path", AVATAR_POOL[0])
        self.settings = data
        self.profiles[self.profile_name] = data
        save_profiles(self.profiles)
        save_settings(data)
        if not silent:
            self.log_message(f"Perfil salvo: {self.profile_name}")

    def new_profile(self):
        name = simpledialog.askstring("Novo perfil", "Nome do perfil:")
        if not name:
            return
        name = name.strip()
        if not name or name in self.profiles:
            messagebox.showerror("Perfil", "Escolha um nome diferente dos perfis existentes.")
            return
        self.save_profile(silent=True)
        self.profiles[name] = self.settings.copy()
        used_avatars = {profile.get("avatar_path") for profile in self.profiles.values()}
        available_avatars = [avatar for avatar in AVATAR_POOL if avatar not in used_avatars]
        self.profiles[name]["avatar_path"] = random.choice(available_avatars or AVATAR_POOL)
        save_profiles(self.profiles)
        self.profile_combo["values"] = list(self.profiles)
        self.profile_var.set(name)
        self.switch_profile(name)

    def rename_profile(self):
        if self.profile_name in self.instances and self.instances[self.profile_name]["thread"].is_alive():
            messagebox.showwarning("Perfil em execução", "Pare esta instância antes de renomear o perfil.")
            return
        name = simpledialog.askstring("Renomear perfil", "Novo nome:", initialvalue=self.profile_name)
        if not name:
            return
        name = name.strip()
        if not name or name in self.profiles:
            messagebox.showerror("Perfil", "Escolha um nome diferente dos perfis existentes.")
            return
        self.profiles[name] = self.profiles.pop(self.profile_name)
        self.profile_name = name
        self.profile_var.set(name)
        self.profile_combo["values"] = list(self.profiles)
        save_profiles(self.profiles)
        self.log_message(f"Perfil renomeado para: {name}")

    def delete_profile(self):
        if len(self.profiles) <= 1:
            messagebox.showwarning("Perfil", "Mantenha pelo menos um perfil.")
            return
        if self.profile_name in self.instances:
            messagebox.showwarning("Perfil em execução", "Pare esta instância antes de excluir o perfil.")
            return
        if not messagebox.askyesno("Excluir perfil", f"Excluir o perfil {self.profile_name}?"):
            return
        del self.profiles[self.profile_name]
        save_profiles(self.profiles)
        name = next(iter(self.profiles))
        self.profile_name = name
        self.profile_var.set(name)
        self.profile_combo["values"] = list(self.profiles)
        self.settings = self.profiles[name].copy()
        for key, var in self.vars.items():
            value = self.settings.get(key, DEFAULT_SETTINGS.get(key, ""))
            var.set(", ".join(map(str, value)) if key.endswith("_region") else str(value))
        self.dry_run.set(bool(self.settings.get("dry_run", True)))
        self.bag_enabled.set(bool(self.settings.get("bag_enabled", False)))
        self.input_method.set(self.settings.get("input_method", "SendInput scan code"))
        self.update_avatar()
        self.refresh_windows()
        self.log_message(f"Perfil carregado: {name}")

    def release_window(self, profile, instance=None):
        lock = self.window_locks.pop(profile, None)
        if lock is None and instance:
            lock = instance
        if not lock:
            return
        hwnd = lock.get("hwnd")
        if HAS_WIN32 and hwnd and win32gui.IsWindow(hwnd):
            original_title = lock.get("original_title", "")
            if original_title:
                win32gui.SetWindowText(hwnd, original_title)
        if hwnd and self.window_reservations.get(hwnd) == profile:
            self.window_reservations.pop(hwnd, None)

    def block_window(self):
        profile = self.profile_name
        existing = self.window_locks.get(profile)
        if existing:
            self.log_message(f"[{profile}] A janela já está bloqueada como '{existing['reserved_title']}'.")
            return
        hwnd = self.selected_hwnd()
        if not hwnd:
            messagebox.showwarning("Bloquear janela", "Selecione uma janela do Royal Quest primeiro.")
            return
        owner = self.window_reservations.get(hwnd)
        if owner and owner != profile:
            messagebox.showerror("Janela ocupada", f"Esta janela já está bloqueada pelo perfil {owner}.")
            return
        original_title = win32gui.GetWindowText(hwnd) if HAS_WIN32 else ""
        reserved_title = f"ROYAL QUEST: {profile}"
        if HAS_WIN32:
            win32gui.SetWindowText(hwnd, reserved_title)
        self.window_reservations[hwnd] = profile
        self.window_locks[profile] = {"hwnd": hwnd, "original_title": original_title, "reserved_title": reserved_title}
        self.log_message(f"[{profile}] Janela bloqueada manualmente como '{reserved_title}'.")
        self.refresh_windows()
        self.refresh_instances_view()

    def unlock_window(self):
        profile = self.profile_name
        instance = self.instances.get(profile)
        if instance and instance["thread"].is_alive():
            messagebox.showwarning("Desbloquear janela", "Pare a instância antes de desbloquear a janela.")
            return
        if profile not in self.window_locks:
            self.log_message(f"[{profile}] Nenhuma janela bloqueada para desbloquear.")
            return
        self.release_window(profile)
        self.log_message(f"[{profile}] Janela desbloqueada e título original restaurado.")
        self.refresh_windows()
        self.refresh_instances_view()

    def update_profile_status(self):
        instance = self.instances.get(self.profile_name)
        running = bool(instance and instance["thread"].is_alive())
        locked = self.profile_name in self.window_locks
        if running:
            status = "Instância em execução"
        elif locked:
            status = "Janela bloqueada"
        else:
            status = "Instância parada"
        self.profile_status_var.set(status)
        self.refresh_instances_view()

    def refresh_instances_view(self):
        if not hasattr(self, "instances_list"):
            return
        self.instances_list.delete(0, "end")
        for name, profile in self.profiles.items():
            instance = self.instances.get(name)
            running = bool(instance and instance["thread"].is_alive())
            window = f"ROYAL QUEST: {name} (HWND {instance.get('hwnd')})" if instance else "não selecionada"
            marker = "● ATIVA" if running else "○ parada"
            self.instances_list.insert("end", f"{marker:<9}  {name:<18}  {window}")

    def update_avatar(self):
        if not hasattr(self, "avatar_label") or not HAS_PIL:
            return
        avatar_path = self.settings.get("avatar_path", AVATAR_POOL[0])
        path = self.resolve_path(avatar_path)
        if not path.exists():
            path = self.resolve_path(AVATAR_POOL[0])
        if path.exists():
            avatar = Image.open(path).convert("RGBA").resize((42, 42), Image.Resampling.LANCZOS)
            self.avatar_photo = ImageTk.PhotoImage(avatar)
            self.avatar_label.configure(image=self.avatar_photo)

    def choose_file(self, key):
        path = filedialog.askopenfilename(filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp"), ("Todos", "*.*")])
        if path:
            try:
                self.vars[key].set(str(Path(path).relative_to(ROOT)))
            except ValueError:
                self.vars[key].set(path)

    def refresh_windows(self):
        all_windows = WindowCapture.find_windows(self.settings.get("window_title_contains", "Royal Quest"))
        windows = []
        for title, hwnd in all_windows:
            owner = self.window_reservations.get(hwnd)
            if owner and owner != self.profile_name:
                continue
            display_title = f"ROYAL QUEST: {owner}" if owner else title
            windows.append((display_title, hwnd))
        self.windows = windows
        self.window_combo["values"] = [f"{title} (HWND {hwnd})" for title, hwnd in windows]
        if windows:
            current_hwnd = self.window_reservations.get(self.profile_name)
            selected = next((i for i, item in enumerate(windows) if item[1] == current_hwnd), 0)
            self.window_combo.current(selected)
            self.hwnd = windows[selected][1]
            self.log_message(f"Janela disponível: {windows[selected][0]}")
        else:
            self.hwnd = None
            self.log_message("Nenhuma janela disponível para este perfil. Janelas reservadas por outras instâncias ficam ocultas.")

    def selected_hwnd(self):
        index = self.window_combo.current()
        return self.windows[index][1] if index >= 0 and index < len(self.windows) else self.hwnd

    def read_config(self):
        data = self.settings.copy()
        for key, var in self.vars.items():
            value = var.get().strip()
            if key.endswith("_region"):
                data[key] = Rect.from_text(value).to_list()
            elif key in {"threshold"}:
                data[key] = float(value)
            elif key in {"poll_interval_ms", "trigger_consecutive_frames"}:
                data[key] = int(value)
            elif key in {"start_timeout_s", "trigger_timeout_s", "post_trigger_delay_s", "bag_interval_s"}:
                data[key] = float(value)
            else:
                data[key] = value
        data["dry_run"] = bool(self.dry_run.get())
        data["bag_enabled"] = bool(self.bag_enabled.get())
        data["input_method"] = self.input_method.get()
        return data

    def save(self):
        try:
            self.save_profile(silent=False)
        except Exception as exc:
            messagebox.showerror("Configuração inválida", str(exc))

    def calibrate(self, key):
        hwnd = self.selected_hwnd()
        if not hwnd:
            messagebox.showwarning("Janela", "Selecione uma janela do jogo primeiro.")
            return
        image = WindowCapture.capture(hwnd)
        if image is None:
            messagebox.showerror("Captura", "Não foi possível capturar a janela.")
            return
        CalibrationOverlay(self.root, image, lambda rect: self._calibration_done(key, rect))

    def _calibration_done(self, key, rect):
        if rect:
            self.vars[key].set(", ".join(map(str, rect.to_list())))
            self.log_message(f"Região calibrada: {key} = {rect.to_list()}")
            self.save()

    def parse_runtime(self):
        cfg = self.read_config()
        return cfg, Rect.from_list(cfg["image1_region"]), Rect.from_list(cfg["image2_region"])

    def test_images(self):
        try:
            cfg, r1, r2 = self.parse_runtime()
            hwnd = self.selected_hwnd()
            if not hwnd or not r1.valid() or not r2.valid():
                raise ValueError("Selecione a janela e calibre as duas regiões.")
            image = WindowCapture.capture(hwnd)
            p1 = self.resolve_path(cfg["image1_path"])
            p2 = self.resolve_path(cfg["image2_path"])
            s1 = ImageMatcher.score(image, str(p1), r1)
            s2 = ImageMatcher.score(image, str(p2), r2)
            self.log_message(f"Teste: Imagem 1={s1:.3f}; Imagem 2={s2:.3f}; threshold={cfg['threshold']:.3f}")
        except Exception as exc:
            messagebox.showerror("Teste", str(exc))

    def test_key(self):
        try:
            cfg, _, _ = self.parse_runtime()
            if cfg["dry_run"]:
                self.log_message(f"Modo de teste: tecla {cfg['key']} não enviada.")
            else:
                hwnd = self.selected_hwnd()
                VirtualKeyboard.press(hwnd, cfg["key"], cfg.get("input_method", "SendInput scan code"))
                self.log_message(f"Tecla virtual enviada: {cfg['key']} | método={cfg.get('input_method')}")
        except Exception as exc:
            messagebox.showerror("Teclado virtual", str(exc))

    def resolve_path(self, value):
        path = Path(value)
        return path if path.is_absolute() else ROOT / path

    def start(self):
        profile = self.profile_name
        instance = self.instances.get(profile)
        if instance and instance["thread"].is_alive():
            self.log_message(f"[{profile}] A instância já está em execução.")
            return
        try:
            cfg, r1, r2 = self.parse_runtime()
            lock = self.window_locks.get(profile)
            hwnd = lock["hwnd"] if lock else self.selected_hwnd()
            owner = self.window_reservations.get(hwnd) if hwnd else None
            if owner and owner != profile:
                raise ValueError(f"Esta janela já está reservada pelo perfil {owner}.")
            if not hwnd or not r1.valid() or not r2.valid():
                raise ValueError("Selecione a janela e calibre as duas regiões.")
            if not self.resolve_path(cfg["image1_path"]).exists() or not self.resolve_path(cfg["image2_path"]).exists():
                raise ValueError("As duas imagens precisam existir.")
            self.settings = cfg
            cfg["avatar_path"] = self.profiles.get(profile, {}).get("avatar_path", AVATAR_POOL[len(self.profiles) % len(AVATAR_POOL)])
            self.profiles[profile] = cfg
            save_profiles(self.profiles)
            save_settings(cfg)
            if lock:
                original_title = lock["original_title"]
                reserved_title = lock["reserved_title"]
            else:
                original_title = win32gui.GetWindowText(hwnd) if HAS_WIN32 else ""
                reserved_title = f"ROYAL QUEST: {profile}"
                if HAS_WIN32:
                    win32gui.SetWindowText(hwnd, reserved_title)
                self.window_reservations[hwnd] = profile
                self.window_locks[profile] = {"hwnd": hwnd, "original_title": original_title, "reserved_title": reserved_title}
            event = threading.Event()
            thread = threading.Thread(target=self.monitor_loop, args=(cfg, r1, r2, hwnd, event, profile), daemon=True)
            self.instances[profile] = {"thread": thread, "event": event, "hwnd": hwnd, "original_title": original_title, "reserved_title": reserved_title}
            thread.start()
            modo = "TESTE — nenhuma tecla real será enviada" if cfg["dry_run"] else "ATIVO — tecla real será enviada"
            self.log_message(f"[{profile}] Instância iniciada. Tecla={cfg['key']}; modo={modo}; método={cfg.get('input_method')}")
            self.log_message(f"[{profile}] Janela reservada como 'ROYAL QUEST: {profile}' | HWND={hwnd}")
            self.log_message(f"[{profile}] Regiões I1={r1.to_list()} | I2={r2.to_list()}")
            self.root.after(0, self.refresh_windows)
            self.update_profile_status()
        except Exception as exc:
            messagebox.showerror("Iniciar", str(exc))

    def stop(self):
        profile = self.profile_name
        instance = self.instances.get(profile)
        if instance:
            instance["event"].set()
            self.log_message(f"[{profile}] Parada de emergência acionada.")
        else:
            self.log_message(f"[{profile}] Nenhuma instância em execução.")
        self.set_state("PARADO", profile)
        self.update_profile_status()

    def send_key(self, cfg, hwnd, profile):
        if cfg["dry_run"]:
            self.log_message(f"[{profile}] [TESTE] Pressionaria a tecla: {cfg['key']}")
            return
        VirtualKeyboard.press(hwnd, cfg["key"], cfg.get("input_method", "SendInput scan code"))
        self.log_message(f"[{profile}] TECLA VIRTUAL ENVIADA: {cfg['key']} | método={cfg.get('input_method')}")

    def maybe_open_bag(self, cfg, hwnd, profile, bag_state):
        if not cfg.get("bag_enabled", False):
            return
        now = time.monotonic()
        if now < bag_state["next"]:
            return
        bag_cfg = cfg.copy()
        bag_cfg["key"] = str(cfg.get("bag_key", "B")).strip() or "B"
        self.send_key(bag_cfg, hwnd, profile)
        self.log_message(f"[{profile}] Bolsa acionada pela tecla {bag_cfg['key']}; próximo acionamento em {float(cfg.get('bag_interval_s', 24.0)):g}s.")
        bag_state["next"] = now + max(1.0, float(cfg.get("bag_interval_s", 24.0)))

    def monitor_loop(self, cfg, r1, r2, hwnd, stop_event, profile):
        threshold = max(0.0, min(1.0, float(cfg["threshold"])))
        interval = max(20, int(cfg["poll_interval_ms"])) / 1000
        start_timeout = max(1.0, float(cfg["start_timeout_s"]))
        trigger_timeout = max(1.0, float(cfg["trigger_timeout_s"]))
        post_trigger_delay = max(0.0, float(cfg["post_trigger_delay_s"]))
        consecutive_needed = max(1, int(cfg["trigger_consecutive_frames"]))
        bag_interval = max(1.0, float(cfg.get("bag_interval_s", 24.0)))
        bag_state = {"next": time.monotonic() + bag_interval}
        p1, p2 = self.resolve_path(cfg["image1_path"]), self.resolve_path(cfg["image2_path"])
        if cfg.get("bag_enabled", False):
            self.log_message(f"[{profile}] Abertura automática da bolsa ativada: tecla={cfg.get('bag_key', 'B')}, intervalo={bag_interval:g}s.")
        try:
            while not stop_event.is_set():
                self.set_state("PRESSIONANDO TECLA", profile)
                self.send_key(cfg, hwnd, profile)
                if not self.wait_for_image(cfg, p1, r1, threshold, start_timeout, "Imagem 1", interval, 1, hwnd, stop_event, profile, bag_state):
                    self.log_message(f"[{profile}] Timeout aguardando Imagem 1; reiniciando ciclo.")
                    continue
                self.set_state("AÇÃO DETECTADA — AGUARDANDO GATILHO", profile)
                if not self.wait_for_image(cfg, p2, r2, threshold, trigger_timeout, "Imagem 2", interval, consecutive_needed, hwnd, stop_event, profile, bag_state):
                    self.log_message(f"[{profile}] Timeout aguardando Imagem 2; reiniciando ciclo.")
                    continue
                if stop_event.is_set():
                    break
                self.set_state("GATILHO DETECTADO — ENVIANDO TECLA", profile)
                self.log_message(f"[{profile}] Imagem 2 detectada; enviando a tecla final agora.")
                self.send_key(cfg, hwnd, profile)
                self.log_message(f"[{profile}] Tecla final enviada; aguardando {post_trigger_delay:g} segundos antes do próximo loop.")
                delay_end = time.monotonic() + post_trigger_delay
                while not stop_event.is_set() and time.monotonic() < delay_end:
                    time.sleep(min(0.1, max(0.0, delay_end - time.monotonic())))
                if not stop_event.is_set():
                    self.wait_for_image_clear(cfg, p2, r2, threshold, max(3.0, post_trigger_delay * 4), "Imagem 2", interval, hwnd, stop_event, profile, bag_state)
        except Exception as exc:
            self.log_message(f"[{profile}] Erro no monitor: {exc}")
        finally:
            instance = self.instances.get(profile)
            if instance and instance.get("event") is stop_event:
                self.instances.pop(profile, None)
            self.set_state("PARADO", profile)
            self.root.after(0, self.refresh_windows)
            self.root.after(0, self.update_profile_status)

    def wait_for_image(self, cfg, path, region, threshold, timeout, name, interval, consecutive_needed, hwnd, stop_event, profile, bag_state=None):
        started = time.monotonic()
        consecutive = 0
        last_log = 0.0
        self.log_message(f"[{profile}] Lendo {name}: arquivo={path.name}, região={region.to_list()}, timeout={timeout:.1f}s")
        if cv2 is not None:
            template = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if template is not None and (region.x2 - region.x1 < template.shape[1] or region.y2 - region.y1 < template.shape[0]):
                self.log_message(f"[{profile}] {name}: região menor que o template; margem automática de busca ativada.")
        while not stop_event.is_set() and time.monotonic() - started < timeout:
            if bag_state is not None:
                self.maybe_open_bag(cfg, hwnd, profile, bag_state)
            image = WindowCapture.capture(hwnd)
            if image is None:
                if time.monotonic() - last_log >= 2.0:
                    self.log_message(f"[{profile}] {name}: não foi possível capturar a janela HWND {hwnd}.")
                    last_log = time.monotonic()
                time.sleep(interval)
                continue
            score = ImageMatcher.score(image, str(path), region)
            if time.monotonic() - last_log >= 1.0:
                self.log_message(f"[{profile}] {name}: score={score:.3f}/{threshold:.3f}")
                last_log = time.monotonic()
            if score >= threshold:
                consecutive += 1
                if consecutive >= consecutive_needed:
                    self.log_message(f"[{profile}] {name} detectada (score={score:.3f}).")
                    return True
            else:
                consecutive = 0
            time.sleep(interval)
        if stop_event.is_set():
            self.log_message(f"[{profile}] {name}: espera interrompida pela parada de emergência.")
        return False

    def wait_for_image_clear(self, cfg, path, region, threshold, timeout, name, interval, hwnd, stop_event, profile, bag_state=None):
        started = time.monotonic()
        self.log_message(f"[{profile}] Aguardando {name} desaparecer antes de rearmar o ciclo.")
        while not stop_event.is_set() and time.monotonic() - started < timeout:
            if bag_state is not None:
                self.maybe_open_bag(cfg, hwnd, profile, bag_state)
            image = WindowCapture.capture(hwnd)
            score = ImageMatcher.score(image, str(path), region) if image is not None else 0.0
            if score < threshold:
                self.log_message(f"[{profile}] {name} liberada; próximo ciclo autorizado.")
                return True
            time.sleep(interval)
        if not stop_event.is_set():
            self.log_message(f"[{profile}] Aviso: {name} permaneceu visível; rearmando por timeout.")
        return False

    def set_state(self, state, profile=None):
        self.state = state
        if profile is None or profile == self.profile_name:
            self.root.after(0, self.status_var.set, state)
            self.root.after(0, self.update_profile_status)

    def log_message(self, message):
        def append():
            self.log.configure(state="normal")
            self.log.insert("end", time.strftime("[%H:%M:%S] ") + message + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, append)

    def close(self):
        for instance in list(self.instances.values()):
            instance["event"].set()
        for profile in list(self.window_locks):
            self.release_window(profile)
        self.instances.clear()
        self.stop_event.set()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    TriggerBotApp(root)
    root.mainloop()
