# 字幕疊加層：兩個各自獨立的小視窗（無邊框、背景透明、永遠在最上層），給 Twitch 劇院模式、全螢幕時看
#   摘要框：預設停靠螢幕上緣，顯示分鐘摘要、目前話題、支線、觀眾反應（各自可開關），字較小
#   字幕框：預設停靠螢幕下緣，顯示最近 1 到 2 句逐句字幕，字較大、置中，像電影字幕
# 樣式全部從 config.json 的 overlay 區塊讀取：共用的快捷鍵、穿透，加上 summary_box、subtitle_box 兩組。缺的欄位用預設。
# 舊版（只有一個框、欄位平鋪在 overlay 裡）的設定會自動轉成新格式。
# 這個檔案也放了全域快捷鍵的註冊（Windows 原生 RegisterHotKey，不需要系統管理員權限）。
import os
import json
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QGuiApplication
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect, QSizePolicy

位置檔 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay_位置.json")   # 兩個框各自記住位置與寬度

# 兩個框共用的樣式欄位
框共用預設 = {
    "show": True,                      # 按 Ctrl+Shift+S（同時開關）時要不要顯示這個框
    "font": "Microsoft JhengHei UI",   # 字型
    "font_size": 18,                   # 字級
    "text_color": "#ffffff",           # 文字顏色
    "bg_color": "#101218",             # 背景色
    "bg_opacity": 0.6,                 # 背景透明度（0 = 全透明，1 = 不透明）
    "text_effect": "shadow",           # 文字效果：shadow 陰影、outline 描邊、none 無
    "fade_seconds": 0,                 # 幾秒沒更新就淡出（0 = 不淡出）
    "position": "top",                 # 位置：top 停靠上緣、bottom 停靠下緣、free 自由位置
    "screen": 0,                       # 第幾個螢幕（0 = 主螢幕）
    "width": 900,                      # 寬度（像素）；高度依內容自動調整
}
摘要框預設 = dict(框共用預設, font_size=17, position="top",
              show_minute=True,         # 顯示分鐘摘要
              show_topic=True,          # 顯示目前話題
              show_side=False,          # 顯示支線
              show_audience=True,       # 顯示觀眾反應
              max_lines=3)              # 分鐘摘要最多幾行
字幕框預設 = dict(框共用預設, font_size=30, position="bottom", bg_opacity=0.45, text_effect="outline",
              width=1100,
              lines=2)                  # 顯示最近幾句（1 或 2）
共用預設 = {
    "click_through": True,                 # 一開啟就是滑鼠穿透
    "hotkey_toggle": "Ctrl+Shift+S",       # 同時開關兩個框
    "hotkey_summary": "Ctrl+Shift+A",      # 只開關摘要框
    "hotkey_subtitle": "Ctrl+Shift+D",     # 只開關字幕框
    "hotkey_click_through": "Ctrl+Shift+X",   # 切換滑鼠穿透（兩個框一起）
}
選項 = {"text_effect": ("shadow", "outline", "none"), "position": ("top", "bottom", "free")}
舊版欄位 = {"subtitle_size", "summary_size", "summary_max_lines", "show_topic", "show_side", "show_audience",
          "font", "text_color", "bg_color", "bg_opacity", "text_effect", "fade_seconds", "position", "screen"}


def 預設設定():
    return dict(共用預設, summary_box=dict(摘要框預設), subtitle_box=dict(字幕框預設))


def 是舊版(原始):
    return isinstance(原始, dict) and "summary_box" not in 原始 and "subtitle_box" not in 原始 \
        and any(k in 原始 for k in 舊版欄位)


def 轉換舊版(原始):
    """舊版（一個框）→ 新版（兩個框）。顏色、字型、效果、淡出、螢幕、顯示項目、快捷鍵沿用；
    字級因為兩個框的角色不同（字幕變大、摘要變小），改用新的預設。"""
    新 = {k: 原始[k] for k in ("click_through", "hotkey_toggle", "hotkey_click_through") if k in 原始}
    共同 = {k: 原始[k] for k in ("font", "text_color", "bg_color", "bg_opacity", "text_effect", "fade_seconds", "screen")
          if k in 原始}
    摘要 = dict(共同)
    for k in ("show_topic", "show_side", "show_audience"):
        if k in 原始:
            摘要[k] = 原始[k]
    if "summary_max_lines" in 原始:
        摘要["max_lines"] = 原始["summary_max_lines"]
    字幕 = dict(共同)
    if 原始.get("position") in ("top", "bottom", "free"):
        字幕["position"] = 原始["position"]      # 舊的框停在哪，字幕框就停在哪
        if 原始["position"] == "top":
            摘要["position"] = "bottom"          # 避免兩個框疊在一起
    新["summary_box"], 新["subtitle_box"] = 摘要, 字幕
    return 新


def _合法(k, v, d):
    if isinstance(d, bool):
        合法 = isinstance(v, bool)
    elif isinstance(d, (int, float)):
        合法 = isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
    else:
        合法 = isinstance(v, str) and v.strip() != ""
    if 合法 and k in 選項:
        合法 = v in 選項[k]
    if 合法 and k == "bg_opacity":
        合法 = v <= 1
    if 合法 and k == "lines":
        合法 = v in (1, 2)
    return 合法


def _讀一組(原始, 預設, 名, 警告們):
    設定 = dict(預設)
    for k, v in (原始 or {}).items():
        if k not in 預設:
            警告們.append(f"overlay 的 {名} 裡有不認得的欄位「{k}」，已忽略。")
        elif _合法(k, v, 預設[k]):
            設定[k] = v
        else:
            警告們.append(f"overlay 的 {名}.{k} 值不合法（{v!r}），改用預設值 {預設[k]!r}。")
    return 設定


def 讀設定(原始):
    """原始：config.json 的 overlay 區塊（新版或舊版都可以）。回傳 (設定, 警告們)。不合法的欄位用預設值，不會崩潰。"""
    原始 = dict(原始 or {})
    if 是舊版(原始):
        原始 = 轉換舊版(原始)
    警告們 = []
    設定 = {}
    for k, d in 共用預設.items():
        v = 原始.get(k, d)
        if _合法(k, v, d):
            設定[k] = v
        else:
            設定[k] = d
            警告們.append(f"overlay 的 {k} 值不合法（{v!r}），改用預設值 {d!r}。")
    for k in 原始:
        if k not in 共用預設 and k not in ("summary_box", "subtitle_box"):
            警告們.append(f"overlay 裡有不認得的欄位「{k}」，已忽略。")
    設定["summary_box"] = _讀一組(原始.get("summary_box"), 摘要框預設, "summary_box", 警告們)
    設定["subtitle_box"] = _讀一組(原始.get("subtitle_box"), 字幕框預設, "subtitle_box", 警告們)
    return 設定, 警告們


# ---------- Windows 原生功能 ----------
user32 = ctypes.windll.user32
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000
HWND_TOPMOST = wintypes.HWND(-1)
SWP_旗標 = 0x0001 | 0x0002 | 0x0010   # 不動位置、不動大小、不搶焦點
WM_HOTKEY = 0x0312


def 解析快捷鍵(字串):
    """"Ctrl+Shift+S" → (修飾鍵, 按鍵碼)；看不懂回傳 None。"""
    修飾表 = {"ctrl": 0x2, "control": 0x2, "shift": 0x4, "alt": 0x1, "win": 0x8}
    部分 = [p.strip().lower() for p in 字串.split("+") if p.strip()]
    if not 部分:
        return None
    修飾 = 0x4000          # MOD_NOREPEAT：按住不放不會一直觸發
    for p in 部分[:-1]:
        if p not in 修飾表:
            return None
        修飾 |= 修飾表[p]
    鍵 = 部分[-1]
    if len(鍵) == 1 and 鍵.isascii() and 鍵.isalnum():
        return 修飾, ord(鍵.upper())
    if 鍵.startswith("f") and 鍵[1:].isdigit() and 1 <= int(鍵[1:]) <= 24:
        return 修飾, 0x70 + int(鍵[1:]) - 1
    return None


def 註冊快捷鍵(hwnd, 編號, 字串):
    """成功回傳 None，失敗回傳一句中文說明。"""
    解析 = 解析快捷鍵(字串)
    if not 解析:
        return f"快捷鍵「{字串}」看不懂（寫法例如 Ctrl+Shift+S），這個快捷鍵不啟用。"
    if not user32.RegisterHotKey(hwnd, 編號, *解析):
        return f"快捷鍵「{字串}」被其他程式佔用了，這個快捷鍵不啟用（可在「設定」分頁改成別的按鍵）。"
    return None


def 取消快捷鍵(hwnd, 編號):
    user32.UnregisterHotKey(hwnd, 編號)


# ---------- 疊加框（兩個框共用的部分）----------
class 單行字(QLabel):
    """只顯示一行，太長就用「…」截斷（視窗縮小時不會把版面撐開）。"""

    def __init__(self):
        super().__init__()
        self.全文 = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def 設文字(self, 字):
        self.全文 = 字
        self._截斷()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._截斷()

    def _截斷(self):
        寬 = max(10, self.width())
        self.setText(QFontMetrics(self.font()).elidedText(self.全文, Qt.ElideRight, 寬))


def 多行字(對齊=Qt.AlignLeft):
    w = QLabel()
    w.setWordWrap(True)
    w.setAlignment(對齊 | Qt.AlignTop)
    w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return w


class 疊加框(QWidget):
    名稱 = "框"          # 子類別改成「摘要框」「字幕框」，也是位置檔裡的名字
    設定鍵 = ""          # summary_box / subtitle_box
    靠下 = False         # 高度變化時：True = 底邊不動（字幕框），False = 頂邊不動（摘要框）

    def __init__(self, 框設定=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setWindowTitle("直播摘要 " + self.名稱)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setMinimumWidth(240)
        self.開啟 = False          # 使用者要不要看到（淡出時仍算開啟）
        self.穿透 = True
        self._拖曳中 = False
        self.版 = QVBoxLayout(self)
        self.版.setContentsMargins(18, 8, 18, 10)
        self.版.setSpacing(3)
        self.文字們 = self._做內容()
        for w in self.文字們:
            w.setAttribute(Qt.WA_TransparentForMouseEvents)   # 滑鼠事件交給視窗本身（拖曳、縮放）
            self.版.addWidget(w)

        self.閃字 = QLabel(self)      # 「穿透：開／關」短暫提示
        self.閃字.setAlignment(Qt.AlignCenter)
        self.閃字.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.閃字.hide()
        self.閃計時 = QTimer(self, singleShot=True, timeout=self._閃完)
        self.置頂計時 = QTimer(self, interval=1000, timeout=self._置頂)   # 定時確保在最上層（蓋過瀏覽器全螢幕）
        self.存檔計時 = QTimer(self, singleShot=True, interval=600, timeout=self.記住位置)
        self.淡出計時 = QTimer(self, singleShot=True, timeout=self._開始淡出)
        self.動畫 = QPropertyAnimation(self, b"windowOpacity", self)
        self.動畫.setDuration(800)
        self.動畫.finished.connect(self._淡出完成)
        self.已淡出 = False

        self.套用設定(框設定 or {})
        self._還原位置()

    # 子類別實作
    def _做內容(self):
        return []

    def _重畫內容(self):
        pass

    # ---------- 設定與樣式 ----------
    def 套用設定(self, 框設定, 動位置=False):
        """框設定：這個框的設定（已經過 讀設定）。動位置=True 時（設定頁即時預覽）連位置、寬度、螢幕一起套用。"""
        self.設定 = dict(框設定)
        s = self.設定
        self.背景 = QColor(s["bg_color"])
        self.背景.setAlphaF(float(s["bg_opacity"]))
        for w in self.文字們:
            w.setStyleSheet(f"color: {s['text_color']}; background: transparent;")
            self._加效果(w, s["text_effect"])
        閃 = QFont(s["font"])
        閃.setPixelSize(18)
        閃.setBold(True)
        self.閃字.setFont(閃)
        self.閃字.setStyleSheet("color: white; background: rgba(139,108,255,230); border-radius: 10px; padding: 6px 16px;")
        self._設字型()
        self._重畫內容()
        if 動位置:
            self.resize(int(s["width"]), self.height())
            if s["position"] in ("top", "bottom"):
                self.停靠(s["position"])
        self._調高度()
        self.update()

    def _字型(self, 倍率=1.0, 粗=False):
        f = QFont(self.設定["font"])
        f.setPixelSize(max(9, int(self.設定["font_size"] * 倍率)))
        f.setBold(粗)
        return f

    def _設字型(self):
        for w in self.文字們:
            w.setFont(self._字型())

    def _加效果(self, w, 效果):
        if 效果 == "none":
            w.setGraphicsEffect(None)
            return
        影 = QGraphicsDropShadowEffect(w)
        影.setColor(QColor(0, 0, 0, 240))
        if 效果 == "outline":       # 描邊：不偏移、範圍小，看起來像字的外框
            影.setOffset(0, 0)
            影.setBlurRadius(5)
        else:                       # 陰影：往右下偏一點
            影.setOffset(2, 2)
            影.setBlurRadius(6)
        w.setGraphicsEffect(影)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.背景)
        p.drawRoundedRect(self.rect(), 12, 12)
        if not self.穿透:            # 可拖曳時畫一圈細框，讓人知道可以抓
            p.setPen(QColor(139, 108, 255, 200))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

    # ---------- 高度依內容自動調整 ----------
    def _調高度(self):
        self.版.activate()
        高 = max(30, self.版.totalHeightForWidth(self.width()))
        if 高 == self.height():
            return
        g = self.geometry()
        y = g.bottom() + 1 - 高 if self.靠下 and self.isVisible() else g.y()
        self.setFixedHeight(高)
        self.move(g.x(), y)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():     # 拖邊緣改了寬度：重新算高度
            QTimer.singleShot(0, self._調高度)
        if self.isVisible():
            self.存檔計時.start()
        if self.閃字.isVisible():
            self._擺閃字()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self._拖曳中:                  # 使用者拖過：改成自由位置
            self.設定["position"] = "free"
        if self.isVisible():
            self.存檔計時.start()

    def 內容變了(self):
        self._重畫內容()
        self._調高度()
        self._有更新()

    # ---------- 顯示、隱藏、淡出 ----------
    def 顯示(self):
        self.開啟 = True
        self._現身()
        self._有更新()

    def 隱藏(self):
        self.開啟 = False
        self.淡出計時.stop()
        self.動畫.stop()
        self.記住位置()
        self.hide()

    def 切換顯示(self):
        self.隱藏() if self.開啟 else self.顯示()
        return self.開啟

    def _現身(self):
        self.動畫.stop()
        self.setWindowOpacity(1.0)
        self.已淡出 = False
        if not self.isVisible():
            self.show()
        self._調高度()
        self._套用穿透()
        self._置頂()
        self.置頂計時.start()

    def _有更新(self):
        """有新內容：淡出了就叫回來，並重新計時。"""
        if not self.開啟:
            return
        if self.已淡出 or self.windowOpacity() < 1:
            self._現身()
        秒 = self.設定["fade_seconds"]
        if 秒 > 0:
            self.淡出計時.start(int(秒 * 1000))
        else:
            self.淡出計時.stop()

    def _開始淡出(self):
        self.動畫.stop()
        self.動畫.setStartValue(self.windowOpacity())
        self.動畫.setEndValue(0.0)
        self.動畫.start()

    def _淡出完成(self):
        if self.windowOpacity() <= 0.01 and self.開啟:
            self.已淡出 = True
            self.hide()            # 真的藏起來，避免看不見的視窗擋住滑鼠

    # ---------- 最上層、滑鼠穿透 ----------
    def hwnd(self):
        return int(self.winId())

    def _置頂(self):
        if self.isVisible():
            user32.SetWindowPos(self.hwnd(), HWND_TOPMOST, 0, 0, 0, 0, SWP_旗標)

    def _套用穿透(self):
        h = self.hwnd()
        樣式 = user32.GetWindowLongPtrW(h, GWL_EXSTYLE)
        if self.穿透:
            樣式 |= WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            樣式 &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(h, GWL_EXSTYLE, 樣式)
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def 設穿透(self, 開):
        self.穿透 = 開
        if self.isVisible():
            self._套用穿透()

    def 閃提示(self, 文字, 毫秒=1500):
        if not self.開啟:
            return
        if not self.isVisible():
            self._現身()
        self.閃字.setText(文字)
        self.閃字.adjustSize()
        # 框太矮放不下提示時，暫時把框撐高
        self.setFixedHeight(max(self.height(), self.閃字.height() + 8))
        self._擺閃字()
        self.閃字.raise_()
        self.閃字.show()
        self.閃計時.start(毫秒)
        self._有更新()

    def _擺閃字(self):
        self.閃字.move((self.width() - self.閃字.width()) // 2, (self.height() - self.閃字.height()) // 2)

    def _閃完(self):
        self.閃字.hide()
        self._調高度()

    # ---------- 拖曳移動、拖左右邊緣改寬度（穿透關閉時才有作用）----------
    邊寬 = 10

    def _邊緣(self, pos):
        if pos.x() <= self.邊寬:
            return Qt.LeftEdge
        if pos.x() >= self.width() - self.邊寬:
            return Qt.RightEdge
        return None

    def mouseMoveEvent(self, e):
        if not e.buttons():
            self._拖曳中 = False
        self.setCursor(Qt.SizeHorCursor if self._邊緣(e.position().toPoint()) else Qt.SizeAllCursor)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        邊 = self._邊緣(e.position().toPoint())
        if 邊:
            self.windowHandle().startSystemResize(邊)
        else:
            self._拖曳中 = True
            self.windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e):
        self._拖曳中 = False

    # ---------- 位置 ----------
    def _螢幕(self):
        螢幕們 = QGuiApplication.screens()
        i = int(self.設定["screen"])
        return 螢幕們[i] if i < len(螢幕們) else QGuiApplication.primaryScreen()

    def 停靠(self, 位置=None):
        """位置：top / bottom；不給就照設定。free 時不動。"""
        self._拖曳中 = False
        位置 = 位置 or self.設定["position"]
        if 位置 not in ("top", "bottom"):
            return
        self.設定["position"] = 位置
        g = self._螢幕().geometry()
        寬 = min(self.width(), g.width() - 40)
        self.resize(寬, self.height())
        self._調高度()
        x = g.x() + (g.width() - 寬) // 2
        y = g.y() + int(g.height() * 0.03) if 位置 == "top" else g.y() + g.height() - self.height() - int(g.height() * 0.08)
        self.move(x, y)
        if self.isVisible():
            self.存檔計時.start()

    def _讀位置檔(self):
        try:
            with open(位置檔, encoding="utf-8") as f:
                資料 = json.load(f)
            return 資料 if isinstance(資料, dict) else {}
        except Exception:
            return {}

    def _快照(self, 設定):
        return {k: 設定[k] for k in ("position", "width", "screen")}

    def _還原位置(self):
        """config.json 的位置、寬度、螢幕沒被改過時，用上次記住的；改過就照 config.json。"""
        self.設定來源快照 = self._快照(self.設定)
        已存 = self._讀位置檔().get(self.名稱)
        self.resize(int(self.設定["width"]), self.height())
        try:
            if 已存 and 已存.get("config") == self.設定來源快照:
                self.設定["position"] = 已存["position"]
                self.resize(int(已存["w"]), self.height())
                self._調高度()
                if 已存["position"] == "free":
                    # 存的位置要還在某個螢幕裡，不然（例如拔掉螢幕）改回預設停靠
                    中心 = (int(已存["x"]) + int(已存["w"]) // 2, int(已存["y"]) + 10)
                    if any(s.geometry().contains(*中心) for s in QGuiApplication.screens()):
                        self.move(int(已存["x"]), int(已存["y"]))
                        return
                    self.設定["position"] = self.設定來源快照["position"] if self.設定來源快照["position"] != "free" else ("bottom" if self.靠下 else "top")
        except Exception:
            pass
        self._調高度()
        位置 = self.設定["position"]
        self.停靠(位置 if 位置 != "free" else ("bottom" if self.靠下 else "top"))

    def 存檔後(self, 新設定):
        """設定頁按「儲存」後：記下新的 config 快照，讓下次開啟時用現在的位置。"""
        self.設定來源快照 = self._快照(新設定)
        self.記住位置()

    def 記住位置(self):
        try:
            資料 = self._讀位置檔()
            if not all(isinstance(v, dict) for v in 資料.values()):
                資料 = {}           # 舊版位置檔（只有一個框）：不再使用
            g = self.geometry()
            資料[self.名稱] = {"x": g.x(), "y": g.y(), "w": g.width(), "position": self.設定["position"],
                             "config": getattr(self, "設定來源快照", self._快照(self.設定))}
            with open(位置檔, "w", encoding="utf-8") as f:
                json.dump(資料, f, ensure_ascii=False)
        except Exception:
            pass

    def 目前位置設定(self):
        """設定頁用：目前實際的位置、寬度、螢幕（拖曳過會是 free）。"""
        return {"position": self.設定["position"], "width": self.width(), "screen": self.設定["screen"]}


# ---------- 摘要框 ----------
class 摘要框(疊加框):
    名稱 = "摘要框"
    設定鍵 = "summary_box"
    靠下 = False

    def _做內容(self):
        self.摘要內容 = None
        self.話題 = ""
        self.狀態提示 = ""
        self.提示字 = 單行字()
        self.摘要字 = 多行字()
        self.話題字 = 單行字()
        self.支線字 = 單行字()
        self.觀眾字 = 單行字()
        return [self.提示字, self.摘要字, self.話題字, self.支線字, self.觀眾字]

    def _設字型(self):
        self.摘要字.setFont(self._字型(1.0, 粗=True))
        for w in (self.提示字, self.話題字, self.支線字, self.觀眾字):
            w.setFont(self._字型(0.85))
        行高 = QFontMetrics(self._字型(1.0, 粗=True)).lineSpacing()
        self.摘要字.setMaximumHeight(行高 * max(1, int(self.設定["max_lines"])) + 2)

    def 更新摘要(self, 內容):
        self.摘要內容 = 內容
        self.內容變了()

    def 更新話題(self, 簡述):
        self.話題 = 簡述 or ""
        self.內容變了()

    def 設狀態(self, 文字):
        """例如「正在產生最後一個話題的摘要…」；空字串 = 不顯示。"""
        self.狀態提示 = 文字
        self.內容變了()

    def 清空(self):
        self.摘要內容, self.話題, self.狀態提示 = None, "", ""
        self.內容變了()

    def _重畫內容(self):
        s = self.設定
        self.提示字.設文字(self.狀態提示)
        if self.摘要內容:
            self.摘要字.setText(self.摘要內容["摘要"])
            支線 = "；".join(n for _, n in self.摘要內容.get("支線") or [])
            self.支線字.設文字("支線：" + 支線 if 支線 else "")
            觀眾 = self.摘要內容.get("觀眾反應") or ""
            self.觀眾字.設文字("觀眾：" + 觀眾 if 觀眾 else "")
        else:
            self.摘要字.setText("分鐘摘要會出現在這裡")
            self.支線字.設文字("")
            self.觀眾字.設文字("")
        self.話題字.設文字("話題：" + self.話題 if self.話題 else "")
        self.提示字.setVisible(bool(self.狀態提示))
        self.摘要字.setVisible(s["show_minute"])
        self.話題字.setVisible(s["show_topic"] and bool(self.話題))
        self.支線字.setVisible(s["show_side"] and bool(self.支線字.全文))
        self.觀眾字.setVisible(s["show_audience"] and bool(self.觀眾字.全文))
        if not any(w.isVisibleTo(self) for w in self.文字們):     # 全部關掉時至少留一行說明
            self.話題字.設文字("（摘要框目前沒有要顯示的項目）")
            self.話題字.setVisible(True)


# ---------- 字幕框 ----------
class 字幕框(疊加框):
    名稱 = "字幕框"
    設定鍵 = "subtitle_box"
    靠下 = True

    def _做內容(self):
        self.字幕們 = []          # [(文字, 已翻譯)]
        self.字幕字 = 多行字(Qt.AlignHCenter)
        self.翻譯標 = QLabel("翻譯", self)      # 翻譯模式時顯示在右上角
        self.翻譯標.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.翻譯標.setStyleSheet("color: #1a1a1a; background: rgba(255,210,122,220); border-radius: 6px; padding: 1px 6px;")
        self.翻譯標.hide()
        return [self.字幕字]

    def _設字型(self):
        self.字幕字.setFont(self._字型(1.0, 粗=True))
        小 = QFont(self.設定["font"])
        小.setPixelSize(11)
        小.setBold(True)
        self.翻譯標.setFont(小)
        self.翻譯標.adjustSize()

    def 加字幕(self, 文字, 已翻譯=False):
        self.字幕們 = (self.字幕們 + [(文字, 已翻譯)])[-2:]
        self.內容變了()

    def 清空(self):
        self.字幕們 = []
        self.內容變了()

    def _重畫內容(self):
        import html
        句們 = self.字幕們[-int(self.設定["lines"]):]
        if 句們:
            self.字幕字.setText("<br>".join(html.escape(t) for t, _ in 句們))
        else:
            self.字幕字.setText('<span style="color:rgba(255,255,255,140);">（逐句字幕會出現在這裡）</span>')
        self.翻譯標.setVisible(bool(句們) and 句們[-1][1])
        self._擺標籤()

    def _擺標籤(self):
        self.翻譯標.move(self.width() - self.翻譯標.width() - 6, 4)
        self.翻譯標.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._擺標籤()
