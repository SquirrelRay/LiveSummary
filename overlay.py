# Windows 原生功能：視窗置頂、滑鼠穿透、判斷前景是不是全螢幕程式（面板 panel.py 與浮動膠囊 capsule.py 共用）。
# 舊的「摘要框／字幕框」疊加層與全域快捷鍵已移除（由可自由擺放的面板取代）；檔名沿用 overlay.py，讓其他模組的 import 不用改。
import os
import ctypes
from ctypes import wintypes

# ---------- Windows 原生功能 ----------
user32 = ctypes.windll.user32
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000
HWND_TOPMOST = wintypes.HWND(-1)
SWP_旗標 = 0x0001 | 0x0002 | 0x0010   # 不動位置、不動大小、不搶焦點


# ---------- 前景視窗判斷（決定要不要重新拉到最上層）----------
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
class _螢幕資訊(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_螢幕資訊)]
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
WS_EX_TOPMOST = 0x8


# 這些是系統介面或桌面：就算滿版也不算「全螢幕程式」，面板不能蓋過它們
系統程式 = {"explorer.exe", "screenclippinghost.exe", "snippingtool.exe", "screensketch.exe", "taskmgr.exe",
          "startmenuexperiencehost.exe", "shellexperiencehost.exe", "searchhost.exe", "searchapp.exe",
          "textinputhost.exe", "lockapp.exe", "logonui.exe", "applicationframehost.exe", "systemsettings.exe",
          "widgets.exe", "sihost.exe", "dwm.exe", "csrss.exe"}
系統視窗類別 = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
            "XamlExplorerHostIslandWindow", "Windows.UI.Core.CoreWindow", "ForegroundStaging", "MultitaskingViewFrame"}


def _程式名(hwnd):
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)       # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return "", pid.value
    try:
        緩 = ctypes.create_unicode_buffer(520)
        n = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, 緩, ctypes.byref(n)):
            return os.path.basename(緩.value).lower(), pid.value
    finally:
        kernel32.CloseHandle(h)
    return "", pid.value


def 前景是全螢幕程式(hwnd=None):
    """前景視窗是一般程式、而且蓋滿它所在的整個螢幕（瀏覽器全螢幕、影片全螢幕、遊戲）才回傳 True。
    本程式自己的視窗、桌面、工作列、系統視窗（截圖、工作管理員、開始選單、通知…）、
    以及自己設成「永遠在最上層」的視窗（系統工具通常是）都不算。"""
    try:
        h = hwnd or user32.GetForegroundWindow()
        if not h:
            return False
        名, pid = _程式名(h)
        if pid == os.getpid() or 名 in 系統程式:
            return False
        緩 = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, 緩, 256)
        if 緩.value in 系統視窗類別:
            return False
        if user32.GetWindowLongPtrW(h, GWL_EXSTYLE) & WS_EX_TOPMOST:
            return False
        r = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        資 = _螢幕資訊()
        資.cbSize = ctypes.sizeof(資)
        m = user32.MonitorFromWindow(h, 2)                  # MONITOR_DEFAULTTONEAREST
        if not user32.GetMonitorInfoW(m, ctypes.byref(資)):
            return False
        a = 資.rcMonitor
        return r.left <= a.left and r.top <= a.top and r.right >= a.right and r.bottom >= a.bottom
    except Exception:
        return False
