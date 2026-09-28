"""悄匿社交 —— 桌面通知（Windows 右下角）。

优先用**任务栏托盘气泡**：托盘区加一个图标，新消息时用 Shell_NotifyIcon
弹一条通知（Win10 以后会进「操作中心」，就是右下角那个提示）。

如果托盘 API 不可用（非 Windows、或系统限制了通知），自动退回一个
贴屏幕右下角的小浮窗，保证「有消息」这件事一定看得见。

音效由 chat_sound 负责，这里发的通知带 NIIF_NOSOUND，避免和自定义提示音重叠。
"""
import ctypes
import os
import sys
import threading
import time

IS_WINDOWS = sys.platform.startswith('win')

# --- Shell_NotifyIcon 常量 ---
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4

NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_STATE = 0x08
NIF_INFO = 0x10
NIF_SHOWTIP = 0x80

NOTIFYICON_VERSION_4 = 4
NIIF_INFO = 0x01
NIIF_WARNING = 0x02
NIIF_NOSOUND = 0x10
NIIF_LARGE_ICON = 0x20

WM_APP = 0x8000
IDI_APPLICATION = 32512


if IS_WINDOWS:
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD), ('Data4', ctypes.c_byte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('hWnd', wintypes.HWND),
            ('uID', wintypes.UINT),
            ('uFlags', wintypes.UINT),
            ('uCallbackMessage', wintypes.UINT),
            ('hIcon', wintypes.HICON),
            ('szTip', wintypes.WCHAR * 128),
            ('dwState', wintypes.DWORD),
            ('dwStateMask', wintypes.DWORD),
            ('szInfo', wintypes.WCHAR * 256),
            ('uTimeout', wintypes.UINT),
            ('szInfoTitle', wintypes.WCHAR * 64),
            ('dwInfoFlags', wintypes.DWORD),
            ('guidItem', GUID),
            ('hBalloonIcon', wintypes.HICON),
        ]
else:
    NOTIFYICONDATAW = None


class TrayNotifier:
    """任务栏托盘通知。attach 一次，之后 notify 即可。"""

    _next_uid = 0x51A0
    _uid_lock = threading.Lock()

    @classmethod
    def _alloc_uid(cls):
        """每个实例用不同的托盘 ID：同一个 id 重复 NIM_ADD 会被 shell 拒绝。"""
        with cls._uid_lock:
            uid = cls._next_uid
            cls._next_uid += 1
        return uid

    def __init__(self, tooltip='悄匿社交', icon_path=None):
        self.tooltip = (tooltip or '悄匿社交')[:127]
        self.icon_path = icon_path or sys.executable
        self.uid = self._alloc_uid()
        self.hwnd = None
        self.available = False
        self.last_error = ''
        self._added = False
        self._nid = None
        self._lock = threading.Lock()

    # ---------- 图标 ----------
    def _load_icon(self):
        """优先用 exe 自己的图标，取不到就用系统默认图标。"""
        h = 0
        try:
            shell32 = ctypes.windll.shell32          # ExtractIconW 在 shell32 里
            shell32.ExtractIconW.restype = ctypes.c_void_p
            shell32.ExtractIconW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                             ctypes.c_int]
            if self.icon_path and os.path.exists(self.icon_path):
                h = shell32.ExtractIconW(None, self.icon_path, 0) or 0
        except Exception:
            h = 0
        if not h:
            try:
                user32 = ctypes.windll.user32
                user32.LoadIconW.restype = ctypes.c_void_p
                user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                h = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION)) or 0
            except Exception:
                h = 0
        return h

    def attach(self, hwnd):
        """把托盘图标挂到给定的窗口句柄上。"""
        if not IS_WINDOWS:
            self.last_error = '非 Windows 平台'
            return False
        try:
            shell32 = ctypes.windll.shell32
            user32 = ctypes.windll.user32
            shell32.Shell_NotifyIconW.restype = wintypes.BOOL
            shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                                  ctypes.POINTER(NOTIFYICONDATAW)]
            h = int(hwnd)
            try:
                parent = user32.GetParent(wintypes.HWND(h))
                if parent:
                    h = int(parent)
            except Exception:
                pass
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = wintypes.HWND(h)
            nid.uID = self.uid
            nid.uFlags = NIF_ICON | NIF_TIP | NIF_MESSAGE | NIF_SHOWTIP
            nid.uCallbackMessage = WM_APP + 1
            nid.hIcon = self._load_icon()
            nid.szTip = self.tooltip
            ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
            if not ok:
                self.last_error = f'Shell_NotifyIcon(NIM_ADD) 返回 0（错误 {ctypes.GetLastError()}）'
                return False
            self._added = True
            self._nid = nid
            self.hwnd = h
            # 声明使用 V4 行为（否则气泡提示在部分系统上不显示）
            ver = NOTIFYICONDATAW()
            ver.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            ver.hWnd = wintypes.HWND(h)
            ver.uID = nid.uID
            ver.uTimeout = NOTIFYICON_VERSION_4
            shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(ver))
            self.available = True
            return True
        except Exception as e:
            self.last_error = f'{type(e).__name__}: {e}'
            self.available = False
            return False

    # ---------- 发通知 ----------
    def notify(self, title, text, warning=False):
        if not self.available or not self._added:
            return False
        try:
            shell32 = ctypes.windll.shell32
            with self._lock:
                nid = self._nid
                nid.uFlags = NIF_INFO | NIF_ICON | NIF_TIP | NIF_SHOWTIP
                nid.szInfoTitle = (title or '')[:63]
                nid.szInfo = (text or '')[:255]
                nid.dwInfoFlags = (NIIF_WARNING if warning else NIIF_INFO) | NIIF_NOSOUND
                nid.uTimeout = 8000
                nid.hIcon = self._load_icon()
                nid.szTip = self.tooltip
                ok = bool(shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))
            if not ok:
                self.last_error = 'Shell_NotifyIcon(NIM_MODIFY) 返回 0'
            return ok
        except Exception as e:
            self.last_error = f'{type(e).__name__}: {e}'
            return False

    def detach(self):
        if not self._added:
            return
        try:
            shell32 = ctypes.windll.shell32
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = wintypes.HWND(self.hwnd)
            nid.uID = self.uid
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:
            pass
        self._added = False
        self.available = False


# ---------------------------------------------------------------- 兜底浮窗
class ScreenToast:
    """托盘通知不可用时，贴在屏幕右下角的小浮窗。"""

    WIDTH = 320
    MARGIN = 16
    STACK = 96

    def __init__(self, master, palette=None, onclick=None):
        self.master = master
        self.pal = palette or {}
        self.onclick = onclick
        self._win = None
        self._after = None

    def show(self, title, text, ms=6000):
        try:
            import customtkinter as ctk
        except Exception:
            return False
        p = self.pal
        try:
            if self._win is not None and self._win.winfo_exists():
                self._win.destroy()
        except Exception:
            pass
        try:
            win = ctk.CTkToplevel(self.master)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            try:
                win.attributes('-alpha', 0.97)
            except Exception:
                pass
            card = ctk.CTkFrame(win, fg_color=p.get('bg_panel', '#17212b'),
                                corner_radius=12, border_width=1,
                                border_color=p.get('accent', '#3390ec'))
            card.pack(fill='both', expand=True)
            ctk.CTkLabel(card, text=title, anchor='w', text_color=p.get('text', '#fff'),
                         font=ctk.CTkFont(family=p.get('font', 'Microsoft YaHei UI'),
                                          size=13, weight='bold')).pack(
                fill='x', padx=14, pady=(10, 0))
            ctk.CTkLabel(card, text=text, anchor='w', justify='left', wraplength=self.WIDTH - 30,
                         text_color=p.get('text_dim', '#7f91a4'),
                         font=ctk.CTkFont(family=p.get('font', 'Microsoft YaHei UI'),
                                          size=12)).pack(fill='x', padx=14, pady=(2, 12))
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            win.geometry(f'{self.WIDTH}x{self.STACK}+{sw - self.WIDTH - self.MARGIN}'
                         f'+{sh - self.STACK - 64 - self.MARGIN}')
            if self.onclick:
                for w in (card, win):
                    try:
                        w.bind('<Button-1>', lambda e: self.onclick())
                    except Exception:
                        pass
            win.after(ms, self._hide)
            self._win = win
            return True
        except Exception:
            return False

    def _hide(self):
        try:
            if self._win is not None and self._win.winfo_exists():
                self._win.destroy()
        except Exception:
            pass
        self._win = None


# ---------------------------------------------------------------- 统一入口
class Notifier:
    """对外只暴露 attach / notify / detach，内部自动挑可用的方式。"""

    def __init__(self, master=None, tooltip='悄匿社交', palette=None, onclick=None):
        self.master = master
        self.tray = TrayNotifier(tooltip=tooltip)
        self.toast = ScreenToast(master, palette, onclick) if master is not None else None
        self.backend = 'none'
        self.last_error = ''

    def attach(self, hwnd):
        if self.tray.attach(hwnd):
            self.backend = 'tray'
            return True
        self.last_error = self.tray.last_error
        if self.toast is not None:
            self.backend = 'toast'
        return False

    def notify(self, title, text, warning=False):
        if self.tray.available and self.tray.notify(title, text, warning=warning):
            return 'tray'
        if self.toast is not None and self.toast.show(title, text):
            return 'toast'
        return ''

    def detach(self):
        self.tray.detach()


def _selftest():
    """命令行自检：py chat_notify.py"""
    import tkinter as tk
    root = tk.Tk()
    root.title('通知自检')
    root.geometry('300x120')
    n = Notifier(root, tooltip='悄匿社交 自检')
    ok = n.attach(root.winfo_id())
    print(f'托盘可用={ok} backend={n.backend} err={n.last_error or "无"}')
    root.after(800, lambda: print('notify ->', n.notify('悄匿社交', '这是一条测试通知')))
    root.after(3000, lambda: (n.detach(), root.destroy()))
    root.mainloop()


if __name__ == '__main__':
    _selftest()
