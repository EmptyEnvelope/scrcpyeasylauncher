import os
import sys
import json
import time
import ctypes
from ctypes import wintypes
import threading
import traceback
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

# 锁定工作目录
app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(app_dir)

NO_WINDOW = subprocess.CREATE_NO_WINDOW
CONFIG_FILE = "launcher_config.json"
SCRCPY_TITLE = "Scrcpy_Display"
PAD_Y = 50  # 开启底栏防误触时预留的缓冲跑道高度

# 64 位兼容 Win32 API 绑定
user32 = ctypes.windll.user32

if hasattr(user32, "SetWindowLongPtrW"):
    set_window_long = user32.SetWindowLongPtrW
    set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_window_long.restype = ctypes.c_ssize_t
    get_window_long = user32.GetWindowLongPtrW
    get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
    get_window_long.restype = ctypes.c_ssize_t
else:
    set_window_long = user32.SetWindowLongW
    set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    set_window_long.restype = ctypes.c_long
    get_window_long = user32.GetWindowLongW
    get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
    get_window_long.restype = ctypes.c_long

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.GetSystemMenu.restype = wintypes.HMENU
user32.DeleteMenu.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.DeleteMenu.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

SWP_NOZORDER = 0x0004

RESOLUTION_PRESETS = {
    "保持当前": None,
    "720x1280 (720P)": "720x1280",
    "900x1600 (900P)": "900x1600",
    "1080x1920 (1080P)": "1080x1920",
    "1440x2560 (2K)": "1440x2560",
}

DPI_PRESETS = ["系统自适应", "280", "320", "360", "400", "440", "480", "560", "640"]
FPS_PRESETS = ["30", "45", "60", "90", "120"]
BITRATE_PRESETS = ["2M", "4M", "6M", "8M", "12M", "16M", "20M"]

DEFAULT_CONFIG = {
    "mode": "window",
    "lock_size": True,
    "bottom_pad": False,
    "widen_gesture": True,
    "res": "1080x1920 (1080P)",
    "dpi": "系统自适应",
    "fps": "60",
    "bitrate": "6M"
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = DEFAULT_CONFIG.copy()
                cfg.update(data)
                return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def global_exception_handler(exc_type, exc_value, exc_traceback):
    err = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    messagebox.showerror("运行错误", f"发生未捕获的异常：\n\n{err}")

sys.excepthook = global_exception_handler

def run_cmd(cmd_list, capture=False):
    if capture:
        res = subprocess.run(cmd_list, capture_output=True, text=True, creationflags=NO_WINDOW)
        return res.stdout
    return subprocess.run(cmd_list, creationflags=NO_WINDOW)

def get_hotspot_gateway():
    out = run_cmd(["route", "print", "0.0.0.0"], capture=True)
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            if parts[2] != "0.0.0.0":
                return parts[2]
    return None

def activate_usb_ports():
    out = run_cmd(["adb.exe", "devices"], capture=True)
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            dev_id = parts[0]
            if "." not in dev_id:
                run_cmd(["adb.exe", "-s", dev_id, "tcpip", "5555"])
                time.sleep(2)

def connect_adb(phone_ip):
    for _ in range(3):
        run_cmd(["adb.exe", "connect", f"{phone_ip}:5555"])
        time.sleep(1)
        out = run_cmd(["adb.exe", "devices"], capture=True)
        if f"{phone_ip}:5555\tdevice" in out or f"{phone_ip}:5555 device" in out:
            return True
        time.sleep(1)
    return False

def get_current_density(phone_ip):
    """记录启动前的原始 DPI 设置"""
    density_out = run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "density"], capture=True)
    orig_density = None
    for line in density_out.splitlines():
        if "Override density:" in line:
            orig_density = line.split(":")[-1].strip()
    return orig_density

def get_current_gesture_insets(phone_ip):
    """抓取修改前的侧滑手势判定区原始配置"""
    out_l = run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "get", "secure", "back_gesture_inset_scale_left"], capture=True).strip()
    out_r = run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "get", "secure", "back_gesture_inset_scale_right"], capture=True).strip()
    orig_l = None if out_l in ("", "null") else out_l
    orig_r = None if out_r in ("", "null") else out_r
    return orig_l, orig_r

def get_active_resolution(phone_ip):
    size_out = run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "size"], capture=True)
    override_size = None
    physical_size = None
    for line in size_out.splitlines():
        if "Override size:" in line:
            override_size = line.split(":")[-1].strip()
        elif "Physical size:" in line:
            physical_size = line.split(":")[-1].strip()

    res_str = override_size or physical_size
    if res_str and "x" in res_str:
        try:
            w, h = map(int, res_str.split("x"))
            return w, h
        except Exception:
            pass
    return 1080, 1920

def restore_state(phone_ip, orig_density, size_changed, dpi_changed, orig_l_inset, orig_r_inset, gesture_changed):
    """
    退出恢复：
    - 侧滑贴边扩展：改动后退出时精确还原为运行前的初始数值
    - 屏幕尺寸改变：恢复厂商默认物理分辨率 (wm size reset)
    - DPI 改变：退回启动前捕获到的原数值
    """
    if gesture_changed:
        if orig_l_inset is not None:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "put", "secure", "back_gesture_inset_scale_left", orig_l_inset])
        else:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "delete", "secure", "back_gesture_inset_scale_left"])

        if orig_r_inset is not None:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "put", "secure", "back_gesture_inset_scale_right", orig_r_inset])
        else:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "delete", "secure", "back_gesture_inset_scale_right"])

    if size_changed:
        run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "size", "reset"])

    if dpi_changed:
        if orig_density:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "density", orig_density])
        else:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "density", "reset"])

def apply_window_lock(hwnd):
    """剥离拉伸边框手柄并移除系统菜单最大化"""
    for _ in range(30):
        if user32.IsWindowVisible(hwnd):
            break
        time.sleep(0.05)
    time.sleep(0.4)

    if not user32.IsWindow(hwnd):
        return

    hmenu = user32.GetSystemMenu(hwnd, False)
    if hmenu:
        user32.DeleteMenu(hmenu, 0xF000, 0)
        user32.DeleteMenu(hmenu, 0xF030, 0)

    style = get_window_long(hwnd, -16)
    style &= ~0x00040000  # WS_THICKFRAME
    style &= ~0x00010000  # WS_MAXIMIZEBOX
    set_window_long(hwnd, -16, style)

    user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        0x0001 | 0x0002 | 0x0004 | 0x0020
    )

def native_hotkey_listener(hwnd, initial_w, initial_h):
    """前台全局热键调节视窗体积"""
    aspect = initial_h / max(1, initial_w)
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    while user32.IsWindow(hwnd):
        if user32.GetForegroundWindow() == hwnd:
            ctrl = (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
            if ctrl:
                up = (user32.GetAsyncKeyState(0x26) & 0x8000) or (user32.GetAsyncKeyState(0xBB) & 0x8000) or (user32.GetAsyncKeyState(0x6B) & 0x8000)
                down = (user32.GetAsyncKeyState(0x28) & 0x8000) or (user32.GetAsyncKeyState(0xBD) & 0x8000) or (user32.GetAsyncKeyState(0x6D) & 0x8000)
                reset = (user32.GetAsyncKeyState(0x30) & 0x8000) or (user32.GetAsyncKeyState(0x60) & 0x8000)

                if up or down or reset:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    cur_w = rect.right - rect.left
                    cur_h = rect.bottom - rect.top
                    cur_x = rect.left
                    cur_y = rect.top

                    if reset:
                        new_w = initial_w
                    elif up:
                        new_w = cur_w + 32
                    else:
                        new_w = cur_w - 32

                    new_w = max(260, min(new_w, screen_w - 60))
                    new_h = int(round(new_w * aspect))

                    new_x = cur_x - (new_w - cur_w) // 2
                    new_y = cur_y - (new_h - cur_h) // 2

                    new_x = max(10, min(new_x, screen_w - new_w - 10))
                    new_y = max(10, min(new_y, screen_h - new_h - 10))

                    user32.SetWindowPos(hwnd, 0, new_x, new_y, new_w, new_h, SWP_NOZORDER)
                    time.sleep(0.12)
        time.sleep(0.04)

class ConfigDialog:
    def __init__(self, root):
        self.root = root
        self.confirmed = False
        self.config = load_config()

        self.win = tk.Toplevel(self.root)
        self.win.title("Scrcpy 启动配置")
        self.win.geometry("380x370")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)

        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        x = (screen_w - 380) // 2
        y = (screen_h - 370) // 2
        self.win.geometry(f"+{x}+{y}")

        self.win.protocol("WM_DELETE_WINDOW", self.on_close)
        self.create_widgets()
        self.on_mode_change()

    def create_widgets(self):
        main_frame = ttk.Frame(self.win, padding=16)
        main_frame.pack(fill="both", expand=True)

        # 显示模式
        ttk.Label(main_frame, text="显示模式:").grid(row=0, column=0, sticky="w", pady=5)
        mode_frame = ttk.Frame(main_frame)
        mode_frame.grid(row=0, column=1, sticky="w", pady=5)
        self.var_mode = tk.StringVar(value=self.config.get("mode", "window"))
        ttk.Radiobutton(mode_frame, text="窗口模式", value="window", variable=self.var_mode, command=self.on_mode_change).pack(side="left", padx=(0, 10))
        ttk.Radiobutton(mode_frame, text="全屏模式", value="fullscreen", variable=self.var_mode, command=self.on_mode_change).pack(side="left")

        # 尺寸锁定
        ttk.Label(main_frame, text="尺寸控制:").grid(row=1, column=0, sticky="w", pady=5)
        self.var_lock = tk.BooleanVar(value=self.config.get("lock_size", True))
        self.chk_lock = ttk.Checkbutton(main_frame, text="固定窗口大小 (禁止拉伸光标误触)", variable=self.var_lock)
        self.chk_lock.grid(row=1, column=1, sticky="w", pady=5)

        # 底栏防误触
        ttk.Label(main_frame, text="防误触缓冲:").grid(row=2, column=0, sticky="w", pady=5)
        self.var_bottom_pad = tk.BooleanVar(value=self.config.get("bottom_pad", False))
        self.chk_bottom_pad = ttk.Checkbutton(main_frame, text="底栏防误触", variable=self.var_bottom_pad)
        self.chk_bottom_pad.grid(row=2, column=1, sticky="w", pady=5)

        # 侧滑手势
        ttk.Label(main_frame, text="手势辅助:").grid(row=3, column=0, sticky="w", pady=5)
        self.var_widen = tk.BooleanVar(value=self.config.get("widen_gesture", True))
        self.chk_widen = ttk.Checkbutton(main_frame, text="扩展侧滑返回区 (退出时还原原值)", variable=self.var_widen)
        self.chk_widen.grid(row=3, column=1, sticky="w", pady=5)

        # 渲染分辨率
        ttk.Label(main_frame, text="渲染分辨率:").grid(row=4, column=0, sticky="w", pady=5)
        self.combo_res = ttk.Combobox(main_frame, values=list(RESOLUTION_PRESETS.keys()), state="readonly", width=22)
        saved_res = self.config.get("res", "1080x1920 (1080P)")
        self.combo_res.set(saved_res if saved_res in RESOLUTION_PRESETS else "1080x1920 (1080P)")
        self.combo_res.grid(row=4, column=1, sticky="w", pady=5)

        # DPI 缩放
        ttk.Label(main_frame, text="DPI缩放:").grid(row=5, column=0, sticky="w", pady=5)
        self.combo_dpi = ttk.Combobox(main_frame, values=DPI_PRESETS, width=22)
        self.combo_dpi.set(self.config.get("dpi", "系统自适应"))
        self.combo_dpi.grid(row=5, column=1, sticky="w", pady=5)

        # 刷新率
        ttk.Label(main_frame, text="刷新率:").grid(row=6, column=0, sticky="w", pady=5)
        self.combo_fps = ttk.Combobox(main_frame, values=FPS_PRESETS, state="readonly", width=22)
        saved_fps = self.config.get("fps", "60")
        self.combo_fps.set(saved_fps if saved_fps in FPS_PRESETS else "60")
        self.combo_fps.grid(row=6, column=1, sticky="w", pady=5)

        # 传输率
        ttk.Label(main_frame, text="传输率:").grid(row=7, column=0, sticky="w", pady=5)
        self.combo_bitrate = ttk.Combobox(main_frame, values=BITRATE_PRESETS, state="readonly", width=22)
        saved_bitrate = self.config.get("bitrate", "6M")
        self.combo_bitrate.set(saved_bitrate if saved_bitrate in BITRATE_PRESETS else "6M")
        self.combo_bitrate.grid(row=7, column=1, sticky="w", pady=5)

        # 热键说明
        lbl_tip = ttk.Label(main_frame, text="* 视窗缩放：Ctrl + ↑/+ 放大，Ctrl + ↓/- 缩小，Ctrl + 0 复位", foreground="#666666")
        lbl_tip.grid(row=8, column=0, columnspan=2, pady=(6, 0))

        # 按钮区
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        btn_reset = ttk.Button(btn_frame, text="还原屏幕设置", command=self.on_reset_screen)
        btn_reset.pack(side="left")

        btn_ok = ttk.Button(btn_frame, text="启动", width=9, command=self.on_confirm)
        btn_ok.pack(side="right", padx=(6, 0))

        btn_cancel = ttk.Button(btn_frame, text="取消", width=9, command=self.on_close)
        btn_cancel.pack(side="right")

    def on_mode_change(self):
        if self.var_mode.get() == "fullscreen":
            self.chk_lock.config(state="disabled")
            self.chk_bottom_pad.config(state="disabled")
        else:
            self.chk_lock.config(state="normal")
            self.chk_bottom_pad.config(state="normal")

    def on_reset_screen(self):
        """一键重置手机出厂分辨率与 DPI（弹窗显式置于当前窗口最顶层）"""
        if not messagebox.askyesno("还原确认", "是否立即将手机的屏幕分辨率与 DPI 重置恢复为厂商出厂默认？", parent=self.win):
            return

        phone_ip = get_hotspot_gateway()
        if not phone_ip:
            messagebox.showwarning("网络未连接", "未检测到热点 IP，请确认已连入手机热点。", parent=self.win)
            return

        activate_usb_ports()
        if not connect_adb(phone_ip):
            messagebox.showerror("连接失败", f"无法连接无线调试 ({phone_ip}:5555)。", parent=self.win)
            return

        run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "size", "reset"])
        run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "density", "reset"])
        run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "delete", "secure", "back_gesture_inset_scale_left"])
        run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "delete", "secure", "back_gesture_inset_scale_right"])

        messagebox.showinfo("重置成功", "已成功恢复手机出厂分辨率与 DPI 设置！", parent=self.win)

    def on_confirm(self):
        self.confirmed = True
        self.mode_val = self.var_mode.get()
        self.lock_size_val = self.var_lock.get()
        self.bottom_pad_val = self.var_bottom_pad.get()
        self.widen_gesture_val = self.var_widen.get()
        self.res_val = self.combo_res.get()
        self.dpi_val = self.combo_dpi.get().strip()
        self.fps_val = self.combo_fps.get()
        self.bitrate_val = self.combo_bitrate.get()

        save_config({
            "mode": self.mode_val,
            "lock_size": self.lock_size_val,
            "bottom_pad": self.bottom_pad_val,
            "widen_gesture": self.widen_gesture_val,
            "res": self.res_val,
            "dpi": self.dpi_val,
            "fps": self.fps_val,
            "bitrate": self.bitrate_val
        })

        self.win.destroy()

    def on_close(self):
        self.win.destroy()

def main():
    root = tk.Tk()
    root.withdraw()

    if not os.path.exists("scrcpy.exe") or not os.path.exists("adb.exe"):
        messagebox.showerror("启动失败", "未找到 scrcpy.exe 或 adb.exe，请置于 Scrcpy 根目录下运行。")
        return

    dialog = ConfigDialog(root)
    root.wait_window(dialog.win)

    if not dialog.confirmed:
        root.destroy()
        return

    target_size = RESOLUTION_PRESETS[dialog.res_val]

    run_cmd(["taskkill", "/f", "/im", "scrcpy.exe", "/im", "adb.exe"])
    time.sleep(0.3)
    run_cmd(["adb.exe", "start-server"])
    time.sleep(0.3)

    phone_ip = get_hotspot_gateway()
    if not phone_ip:
        messagebox.showwarning("网络错误", "未检测到热点网关 IP，请确认已连接手机热点。")
        root.destroy()
        return

    activate_usb_ports()

    if not connect_adb(phone_ip):
        messagebox.showerror("连接错误", f"无法连接无线调试 ({phone_ip}:5555)。")
        root.destroy()
        return

    orig_density = get_current_density(phone_ip)
    orig_l_inset, orig_r_inset = get_current_gesture_insets(phone_ip)

    size_changed = False
    dpi_changed = False
    gesture_changed = False

    try:
        # 分辨率配置
        if target_size:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "size", target_size])
            size_changed = True

        # DPI 配置
        if dialog.dpi_val and dialog.dpi_val != "系统自适应":
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "density", dialog.dpi_val])
            dpi_changed = True
        elif size_changed:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "wm", "density", "reset"])
            dpi_changed = True

        # 扩展贴边判定区
        if dialog.widen_gesture_val:
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "put", "secure", "back_gesture_inset_scale_left", "3"])
            run_cmd(["adb.exe", "-s", f"{phone_ip}:5555", "shell", "settings", "put", "secure", "back_gesture_inset_scale_right", "3"])
            gesture_changed = True

        time.sleep(0.3)

        scrcpy_cmd = [
            "scrcpy.exe",
            "-s", f"{phone_ip}:5555",
            "--turn-screen-off",
            "--stay-awake",
            f"--window-title={SCRCPY_TITLE}",
            f"--video-bit-rate={dialog.bitrate_val}",
            f"--max-fps={dialog.fps_val}"
        ]

        win_w, win_h = 460, 820
        if dialog.mode_val == "fullscreen":
            scrcpy_cmd.append("-f")
        else:
            if target_size and "x" in target_size:
                sw, sh = map(int, target_size.split("x"))
            else:
                sw, sh = get_active_resolution(phone_ip)

            base_w = 460
            ratio = sw / max(1, sh)
            video_h = int(round(base_w / ratio))
            win_w = base_w

            if dialog.bottom_pad_val:
                win_h = video_h + PAD_Y * 2
            else:
                win_h = video_h

            scrcpy_cmd.extend([f"--window-width={win_w}", f"--window-height={win_h}"])

        proc = subprocess.Popen(
            scrcpy_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=NO_WINDOW
        )

        if dialog.mode_val == "window":
            scrcpy_hwnd = 0
            for _ in range(60):
                if proc.poll() is not None:
                    break
                scrcpy_hwnd = user32.FindWindowW(None, SCRCPY_TITLE)
                if scrcpy_hwnd:
                    break
                time.sleep(0.1)

            if scrcpy_hwnd:
                if dialog.lock_size_val:
                    threading.Thread(target=apply_window_lock, args=(scrcpy_hwnd,), daemon=True).start()
                threading.Thread(target=native_hotkey_listener, args=(scrcpy_hwnd, win_w, win_h), daemon=True).start()

        def wait_process():
            proc.wait()
            root.after(0, root.quit)

        t = threading.Thread(target=wait_process, daemon=True)
        t.start()

        root.mainloop()

        stdout, stderr = proc.communicate()
        if proc.returncode != 0 and proc.returncode != 15:
            err_msg = stderr.strip() or stdout.strip() or "未知退出状态"
            messagebox.showerror("Scrcpy 异常", f"Scrcpy 退出码 {proc.returncode}：\n\n{err_msg}")

    finally:
        restore_state(phone_ip, orig_density, size_changed, dpi_changed, orig_l_inset, orig_r_inset, gesture_changed)
        root.destroy()

if __name__ == "__main__":
    main()