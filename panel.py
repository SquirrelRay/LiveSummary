# 面板（新介面第一階段）：可自由擺放的無邊框小視窗，每個面板顯示五種內容之一：
#   分鐘摘要、話題摘要、逐句翻譯、直播稿、聊天室
# 面板不另外跑引擎：和主控台接同一條事件（主控台的 事件橋），內容的顯示上限、捲動方向（newest_on_top）、
# 手動往上捲不被拉回、「較早的內容已存檔」都直接重用主控台分頁的元件（app.py 的 卡片清單／文字清單／逐句頁）。
# 每個面板兩種樣式：清單（深色背景的內容清單）、字幕（透明背景、大字置中、只顯示最新幾則）。
# 控制項平常隱藏，滑鼠移到面板上才在角落浮現（離開約 1.5 秒後淡出）。
# 版面配置（面板種類、位置、大小、樣式、各項設定）存在 版面配置.json（本機檔案，不進 git），可存多組、各自命名。
import os
import re
import html
import json
from collections import deque

from PySide6.QtCore import Qt, QTimer, QRect, QPropertyAnimation, QObject, QEvent
from PySide6.QtGui import QColor, QFont, QPainter, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QSlider, QHBoxLayout, QVBoxLayout, QMenu,
    QInputDialog, QMessageBox, QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QSizePolicy,
    QAbstractButton, QAbstractSlider,
)

import overlay          # 最上層、滑鼠穿透（Windows 原生）
import subtitle
import live_topics

版面檔 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "版面配置.json")
種類們 = ["分鐘摘要", "話題摘要", "逐句翻譯", "直播稿", "聊天室"]
上限鍵 = {"分鐘摘要": "ui_max_summary", "話題摘要": "ui_max_summary", "直播稿": "ui_max_transcript",
         "逐句翻譯": "ui_max_translation", "聊天室": "ui_max_chat"}
檔案鍵 = {"直播稿": "稿", "聊天室": "聊天", "分鐘摘要": "分鐘", "話題摘要": "話題"}
清單基準字級 = 14          # 清單樣式的字級 = 14 時和主控台分頁一樣大
HWND_NOTOPMOST = overlay.wintypes.HWND(-2)
WS_EX_TOPMOST = 0x8

面板預設 = {
    "樣式": "清單",          # 清單 / 字幕
    "置頂": True,            # 疊在其他視窗上
    "穿透": False,           # 滑鼠點擊穿過面板
    "文字透明度": 1.0,       # 1 = 不透明
    "清單背景": 0.92,        # 清單樣式的背景透明度
    "字幕背景": 0.0,         # 字幕樣式的背景透明度（預設全透明）
    "清單字級": 14,
    "字幕字級": 28,
    "字幕則數": 2,
}


def 跳脫(字):
    return html.escape(str(字))


def _數(v, 預設, 小, 大):
    return min(大, max(小, v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else 預設


def 整理面板設定(原始):
    """版面檔裡的一個面板 → 合法的設定（缺的、壞的用預設）。種類不認得回傳 None。"""
    if not isinstance(原始, dict) or 原始.get("種類") not in 種類們:
        return None
    s = dict(面板預設, 種類=原始["種類"])
    s["樣式"] = 原始.get("樣式") if 原始.get("樣式") in ("清單", "字幕") else "清單"
    for k in ("置頂", "穿透"):
        if isinstance(原始.get(k), bool):
            s[k] = 原始[k]
    s["文字透明度"] = _數(原始.get("文字透明度"), 1.0, 0.1, 1.0)
    s["清單背景"] = _數(原始.get("清單背景"), 面板預設["清單背景"], 0.0, 1.0)
    s["字幕背景"] = _數(原始.get("字幕背景"), 面板預設["字幕背景"], 0.0, 1.0)
    s["清單字級"] = int(_數(原始.get("清單字級"), 14, 8, 40))
    s["字幕字級"] = int(_數(原始.get("字幕字級"), 28, 10, 96))
    s["字幕則數"] = int(_數(原始.get("字幕則數"), 2, 1, 10))
    for k, 預 in (("x", 100), ("y", 100), ("w", 420), ("h", 300)):
        s[k] = int(_數(原始.get(k), 預, -100000, 100000))
    s["w"], s["h"] = max(30, s["w"]), max(20, s["h"])
    return s


def 預設版面():
    """以主螢幕的可用範圍比例計算（不寫死像素）。"""
    g = QGuiApplication.primaryScreen().availableGeometry()
    右寬 = g.width() // 3
    右x = g.x() + g.width() - 右寬
    半高 = g.height() // 2
    字寬, 字高 = int(g.width() * 0.34), int(g.height() * 0.16)
    return [
        dict(面板預設, 種類="分鐘摘要", x=右x, y=g.y(), w=右寬, h=半高),
        dict(面板預設, 種類="話題摘要", x=右x, y=g.y() + 半高, w=右寬, h=g.height() - 半高),
        dict(面板預設, 種類="逐句翻譯", 樣式="字幕", 穿透=True, 字幕則數=2,
             x=g.x() + (g.width() - 字寬) // 2, y=g.y() + g.height() - 字高 - int(g.height() * 0.04), w=字寬, h=字高),
    ]


def 移回畫面內(s):
    """面板超出目前所有螢幕的範圍就移回（放在重疊最多的螢幕；都沒重疊就放主螢幕），太大就縮到螢幕大小。"""
    框 = QRect(s["x"], s["y"], s["w"], s["h"])
    螢幕們 = QGuiApplication.screens()
    for sc in 螢幕們:
        if sc.availableGeometry().contains(框):
            return s
    def 重疊(sc):
        r = sc.availableGeometry().intersected(框)
        return r.width() * r.height() if r.isValid() else 0
    最好 = max(螢幕們, key=重疊)
    g = (最好 if 重疊(最好) > 0 else QGuiApplication.primaryScreen()).availableGeometry()
    w, h = min(s["w"], g.width()), min(s["h"], g.height())
    x = min(max(s["x"], g.x()), g.x() + g.width() - w)
    y = min(max(s["y"], g.y()), g.y() + g.height() - h)
    return dict(s, x=x, y=y, w=w, h=h)


# ---------- 內容紀錄：面板共用同一份，新開的面板或換字級時從這裡重建 ----------
class 紀錄:
    def __init__(self, 上限=500):
        self.項目們 = deque(maxlen=上限)    # 每項：(方法名, 參數們, 純文字)
        self.總數 = 0
        self.檔案 = None
        self.進行中 = None                  # 話題摘要用：(時間字, 簡述)
        self.註 = ""                        # 逐句翻譯用：頂端說明

    def 設上限(self, n):
        self.項目們 = deque(self.項目們, maxlen=max(1, int(n)))

    def 清空(self):
        self.項目們.clear()
        self.總數 = 0
        self.檔案 = None
        self.進行中 = None


# ---------- 面板 ----------
class 控制列(QFrame):
    """滑鼠移到面板上時浮現的小控制區（獨立的小視窗：面板很窄時也放得下，會擺到面板外側）。"""

    def __init__(self, 面):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.面 = 面
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName("面板控制")
        self.setStyleSheet("""
            QFrame#面板控制 { background: rgba(22,25,32,240); border: 1px solid #8b6cff; border-radius: 10px; }
            QLabel { color: #8a91a5; font-size: 12px; background: transparent; }
            QLabel#名 { color: #e7e9ef; font-weight: 700; }
            QPushButton { padding: 2px 8px; min-width: 14px; border-radius: 7px; border: 1px solid #2a2e3a;
                          background: #1d2029; color: #e7e9ef; font-size: 12px; }
            QPushButton:hover { border: 1px solid #8b6cff; }
            QPushButton:checked { background: #8b6cff; color: white; border: 1px solid #8b6cff; font-weight: 700; }
            QPushButton#關 { color: #ff5c7a; }
            QSlider { min-width: 70px; }
        """)
        版 = QVBoxLayout(self)
        版.setContentsMargins(8, 6, 8, 6)
        版.setSpacing(5)
        列1 = QHBoxLayout()
        列1.setSpacing(4)
        self.名 = QLabel(面.種類)
        self.名.setObjectName("名")
        列1.addWidget(self.名)
        列1.addStretch(1)
        self.清單鈕 = self._鈕("清單", "清單樣式：深色背景的內容清單", True)
        self.字幕鈕 = self._鈕("字幕", "字幕樣式：透明背景、大字置中、只顯示最新幾則", True)
        self.置頂鈕 = self._鈕("置頂", "疊在其他視窗上（開／關）", True)
        self.穿透鈕 = self._鈕("穿透", "穿透（開／關）：開啟後滑鼠點擊會穿過面板，控制項也會暫時無法操作；"
                                   "要取消請用主控台「面板」選單的「全部取消穿透」", True)
        self.小鈕 = self._鈕("A−", "字縮小")
        self.大鈕 = self._鈕("A+", "字放大")
        self.關鈕 = self._鈕("✕", "關閉面板")
        self.關鈕.setObjectName("關")
        for w in (self.清單鈕, self.字幕鈕, self.置頂鈕, self.穿透鈕, self.小鈕, self.大鈕, self.關鈕):
            列1.addWidget(w)
        版.addLayout(列1)
        列2 = QHBoxLayout()
        列2.setSpacing(6)
        self.文字條 = self._條(10, 100)
        self.背景條 = self._條(0, 100)
        列2.addWidget(QLabel("文字"))
        列2.addWidget(self.文字條, 1)
        列2.addWidget(QLabel("背景"))
        列2.addWidget(self.背景條, 1)
        版.addLayout(列2)
        self.則數區 = QWidget()
        列3 = QHBoxLayout(self.則數區)
        列3.setContentsMargins(0, 0, 0, 0)
        列3.setSpacing(4)
        列3.addWidget(QLabel("字幕則數"))
        self.則少 = self._鈕("−", "少一則")
        self.則數字 = QLabel("2")
        self.則數字.setObjectName("名")
        self.則多 = self._鈕("+", "多一則")
        for w in (self.則少, self.則數字, self.則多):
            列3.addWidget(w)
        列3.addStretch(1)
        版.addWidget(self.則數區)

        self.清單鈕.clicked.connect(lambda: 面.設樣式("清單"))
        self.字幕鈕.clicked.connect(lambda: 面.設樣式("字幕"))
        self.置頂鈕.clicked.connect(lambda: 面.設置頂(self.置頂鈕.isChecked()))
        self.穿透鈕.clicked.connect(lambda: 面.設穿透(self.穿透鈕.isChecked()))
        self.小鈕.clicked.connect(lambda: 面.改字級(-2))
        self.大鈕.clicked.connect(lambda: 面.改字級(+2))
        self.關鈕.clicked.connect(面.關閉)
        self.文字條.valueChanged.connect(lambda v: 面.設文字透明度(v / 100))
        self.背景條.valueChanged.connect(lambda v: 面.設背景透明度(v / 100))
        self.則少.clicked.connect(lambda: 面.改則數(-1))
        self.則多.clicked.connect(lambda: 面.改則數(+1))

        self.動畫 = QPropertyAnimation(self, b"windowOpacity", self)
        self.動畫.setDuration(250)
        self.動畫.finished.connect(lambda: self.hide() if self.windowOpacity() <= 0.01 else None)
        self.淡出計時 = QTimer(self, singleShot=True, interval=1500, timeout=self.淡出)

    def _鈕(self, 字, 提示, 可切換=False):
        b = QPushButton(字)
        b.setToolTip(提示)
        b.setCheckable(可切換)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def _條(self, 小, 大):
        s = QSlider(Qt.Horizontal)
        s.setRange(小, 大)
        s.setFocusPolicy(Qt.NoFocus)
        return s

    def 同步(self):
        s = self.面.設
        for w, v in ((self.清單鈕, s["樣式"] == "清單"), (self.字幕鈕, s["樣式"] == "字幕"),
                     (self.置頂鈕, s["置頂"]), (self.穿透鈕, s["穿透"])):
            w.setChecked(v)
        for 條, v in ((self.文字條, s["文字透明度"]), (self.背景條, s[s["樣式"] + "背景"])):
            條.blockSignals(True)
            條.setValue(round(v * 100))
            條.blockSignals(False)
        self.則數字.setText(str(s["字幕則數"]))
        self.則數區.setVisible(s["樣式"] == "字幕")
        self.adjustSize()

    def 擺放(self):
        """面板夠大就放在面板右上角內側，太窄或太矮就放到面板外側（下方，放不下改上方），不超出螢幕。"""
        self.adjustSize()
        g = self.面.frameGeometry()
        w, h = self.width(), self.height()
        sc = QGuiApplication.screenAt(g.center()) or QGuiApplication.primaryScreen()
        a = sc.availableGeometry()
        if g.width() >= w + 12 and g.height() >= h + 12:
            x, y = g.right() - w - 6, g.top() + 6
        else:
            x = g.right() - w
            y = g.bottom() + 4 if g.bottom() + 4 + h <= a.bottom() else g.top() - h - 4
        x = min(max(x, a.x()), a.x() + a.width() - w)
        y = min(max(y, a.y()), a.y() + a.height() - h)
        self.move(x, y)

    def 浮現(self):
        self.淡出計時.stop()
        if not self.isVisible():
            self.同步()
            self.擺放()
            self.setWindowOpacity(0.0)
            self.show()
        overlay.user32.SetWindowPos(int(self.winId()), overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)
        正在淡入 = self.動畫.state() == QPropertyAnimation.Running and self.動畫.endValue() == 1.0
        if self.windowOpacity() < 1 and not 正在淡入:
            self.動畫.stop()
            self.動畫.setStartValue(self.windowOpacity())
            self.動畫.setEndValue(1.0)
            self.動畫.start()

    def 準備淡出(self):
        正在淡出 = self.動畫.state() == QPropertyAnimation.Running and self.動畫.endValue() == 0.0
        if self.isVisible() and not self.淡出計時.isActive() and not 正在淡出:
            self.淡出計時.start()

    def 淡出(self):
        self.動畫.stop()
        self.動畫.setStartValue(self.windowOpacity())
        self.動畫.setEndValue(0.0)
        self.動畫.start()

    def 立刻隱藏(self):
        self.淡出計時.stop()
        self.動畫.stop()
        self.動畫.setEndValue(0.0)
        self.hide()


class 面板(QWidget):
    邊寬 = 7          # 滑鼠在邊緣幾像素內 = 拖曳縮放

    def __init__(self, 管理, 設定):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.管理, self.設 = 管理, dict(設定)
        self.種類 = 設定["種類"]
        self.setWindowTitle("直播摘要 面板：" + self.種類)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumSize(30, 20)
        self.清單頁 = None
        self.清單容器 = QWidget(self)
        self.清單容器.setObjectName("面板清單")
        self.清單容器.setStyleSheet(
            "QFrame#卡片 { background: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,24); }"
            "QFrame#進行卡 { background: rgba(139,108,255,22); }")
        容版 = QVBoxLayout(self.清單容器)
        容版.setContentsMargins(0, 0, 0, 0)
        self.文字效果 = QGraphicsOpacityEffect(self.清單容器)
        self.清單容器.setGraphicsEffect(self.文字效果)
        self.字幕字 = QLabel(self)
        self.字幕字.setWordWrap(True)
        self.字幕字.setTextFormat(Qt.RichText)
        self.字幕字.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        self.字幕字.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.字幕影 = QGraphicsDropShadowEffect(self.字幕字)
        self.字幕影.setOffset(0, 0)
        self.字幕影.setBlurRadius(6)
        self.字幕字.setGraphicsEffect(self.字幕影)
        self.控制 = 控制列(self)
        self.懸停 = False
        self.置頂計時 = QTimer(self, interval=1000, timeout=self._保持置頂)
        self.存計時 = QTimer(self, singleShot=True, interval=500, timeout=self.管理.存目前)
        self.setGeometry(self.設["x"], self.設["y"], self.設["w"], self.設["h"])
        self.重建清單()
        self._套樣式()

    # ---------- 內容 ----------
    def 紀錄(self):
        return self.管理.紀錄們[self.種類]

    def 重建清單(self):
        """從共用紀錄重新做一個清單頁（開新面板、改字級時）。行為和主控台分頁同一套元件。"""
        if self.清單頁 is not None:
            self.清單頁.hide()
            self.清單頁.deleteLater()
        頁 = self.管理.做頁(self.種類)
        倍 = self.設["清單字級"] / 清單基準字級
        縮放 = lambda h: re.sub(r"font-size:\s*(\d+)px", lambda m: f"font-size:{max(7, round(int(m.group(1)) * 倍))}px", h)
        f = QFont(QApplication.font())
        f.setPixelSize(max(8, round(13 * 倍)))
        頁.setFont(f)
        for 名 in ("加一行", "加卡片"):          # 換字級：把內容裡寫死的 px 字級等比例放大縮小
            if hasattr(頁, 名):
                原 = getattr(頁, 名)
                setattr(頁, 名, lambda h, 原=原: 原(縮放(h)))
        紀 = self.紀錄()
        頁.設上限(紀.項目們.maxlen)
        頁.設方向(self.管理.置頂)
        頁.設檔案(紀.檔案)
        for 方法, 參數, _ in 紀.項目們:
            getattr(頁, 方法)(*參數)
        頁.總數 = 紀.總數
        頁._超過了()
        if 紀.進行中:
            頁.設進行中(*紀.進行中)
        if hasattr(頁, "設註"):
            頁.設註(紀.註)
        for w in [頁] + 頁.findChildren(QWidget):     # 允許縮成很窄的橫條或直條
            w.setMinimumSize(0, 0)
        頁.頂.layout().setContentsMargins(8, 4, 8, 0)
        self.清單容器.layout().addWidget(頁)
        self.清單頁 = 頁
        self._排()

    def 新項目(self, 方法, 參數):
        getattr(self.清單頁, 方法)(*參數)
        if self.設["樣式"] == "字幕":
            self._畫字幕()

    def 進行中變了(self):
        紀 = self.紀錄()
        if 紀.進行中:
            self.清單頁.設進行中(*紀.進行中)
        else:
            self.清單頁.移除進行中()
        if self.設["樣式"] == "字幕":
            self._畫字幕()

    def 開始(self):
        """主控台按了開始：清空，套用新的上限與檔案。"""
        self.重建清單()
        self._畫字幕()

    def _畫字幕(self):
        紀 = self.紀錄()
        n = self.設["字幕則數"]
        句們 = [純 for _, _, 純 in 紀.項目們 if 純][-n:]
        if self.種類 == "話題摘要" and 紀.進行中:
            句們 = (句們 + ["進行中：" + 紀.進行中[1]])[-n:]
        a = self.設["文字透明度"]
        if 句們:
            self.字幕字.setText(f'<div style="color:rgba(255,255,255,{round(255 * a)});">'
                             + "<br>".join(跳脫(t) for t in 句們) + "</div>")
        else:
            self.字幕字.setText(f'<span style="color:rgba(255,255,255,{round(140 * a)});">（{self.種類}會出現在這裡）</span>')

    # ---------- 樣式與設定 ----------
    def _套樣式(self):
        s = self.設
        字幕 = s["樣式"] == "字幕"
        self.清單容器.setVisible(not 字幕)
        self.字幕字.setVisible(字幕)
        self.文字效果.setOpacity(s["文字透明度"])
        f = QFont(QApplication.font())
        f.setPixelSize(s["字幕字級"])
        f.setBold(True)
        self.字幕字.setFont(f)
        self.字幕影.setColor(QColor(0, 0, 0, round(240 * s["文字透明度"])))
        if 字幕:
            self._畫字幕()
        self._排()
        self.update()
        self.控制.同步()
        if self.控制.isVisible():
            self.控制.擺放()

    def 改了(self):
        self._套樣式()
        self.存計時.start()

    def 設樣式(self, 樣式):
        self.設["樣式"] = 樣式
        self.改了()

    def 設文字透明度(self, v):
        self.設["文字透明度"] = v
        self.改了()

    def 設背景透明度(self, v):
        self.設[self.設["樣式"] + "背景"] = v
        self.改了()

    def 改字級(self, 差):
        if self.設["樣式"] == "字幕":
            self.設["字幕字級"] = min(96, max(10, self.設["字幕字級"] + 差 * 2))
        else:
            self.設["清單字級"] = min(40, max(8, self.設["清單字級"] + 差))
            self.重建清單()
        self.改了()

    def 改則數(self, 差):
        self.設["字幕則數"] = min(10, max(1, self.設["字幕則數"] + 差))
        self.改了()

    def 設置頂(self, 開):
        self.設["置頂"] = bool(開)
        self._套視窗樣式()
        self.存計時.start()

    def 設穿透(self, 開):
        self.設["穿透"] = bool(開)
        if 開:
            self.控制.立刻隱藏()
        self._套視窗樣式()
        self.控制.同步()
        self.update()
        self.存計時.start()

    def _套視窗樣式(self):
        if not self.isVisible():
            return
        h = int(self.winId())
        樣式 = overlay.user32.GetWindowLongPtrW(h, overlay.GWL_EXSTYLE)
        if self.設["穿透"]:
            樣式 |= overlay.WS_EX_TRANSPARENT | overlay.WS_EX_LAYERED
        else:
            樣式 &= ~overlay.WS_EX_TRANSPARENT
        overlay.user32.SetWindowLongPtrW(h, overlay.GWL_EXSTYLE, 樣式)
        overlay.user32.SetWindowPos(h, overlay.HWND_TOPMOST if self.設["置頂"] else HWND_NOTOPMOST,
                                    0, 0, 0, 0, overlay.SWP_旗標)
        self.置頂計時.start() if self.設["置頂"] else self.置頂計時.stop()

    def _保持置頂(self):          # 定時確保在最上層（蓋過瀏覽器全螢幕）
        if self.isVisible() and self.設["置頂"]:
            overlay.user32.SetWindowPos(int(self.winId()), overlay.HWND_TOPMOST, 0, 0, 0, 0, overlay.SWP_旗標)

    def 視窗旗標(self):
        """測試用：(是否置頂, 是否穿透)，直接讀 Windows 的視窗樣式。"""
        樣式 = overlay.user32.GetWindowLongPtrW(int(self.winId()), overlay.GWL_EXSTYLE)
        return bool(樣式 & WS_EX_TOPMOST), bool(樣式 & overlay.WS_EX_TRANSPARENT)

    def 快照(self):
        g = self.geometry()
        return dict(self.設, x=g.x(), y=g.y(), w=g.width(), h=g.height())

    # ---------- 顯示 ----------
    def 顯示(self):
        self.show()
        self._套視窗樣式()

    def 關閉(self):
        self.控制.立刻隱藏()
        self.管理.面板關了(self)

    def 收掉(self):
        self.存計時.stop()          # 已經關掉的面板不能再把版面存回去
        self.置頂計時.stop()
        self.控制.立刻隱藏()
        self.控制.close()
        self.控制.deleteLater()
        self.close()
        self.deleteLater()

    def _排(self):
        r = self.rect()
        self.清單容器.setGeometry(r.adjusted(2, 2, -2, -2))
        self.字幕字.setGeometry(r.adjusted(6, 2, -6, -2))
        if self.清單頁 is not None:          # 很矮的橫條：不顯示「較早的內容已存檔」那一列，把空間留給內容
            self.清單頁.頂.setMaximumHeight(0 if self.height() < 90 else 16777215)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._排()
        if self.isVisible():
            self.存計時.start()
            if self.控制.isVisible():
                self.控制.擺放()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.isVisible():
            self.存計時.start()
            if self.控制.isVisible():
                self.控制.擺放()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        背 = QColor(22, 25, 32)
        a = self.設[self.設["樣式"] + "背景"]
        if not self.設["穿透"]:
            a = max(a, 2 / 255)      # 全透明的地方 Windows 不會把滑鼠交給視窗：留一點點，才能拖曳
        背.setAlphaF(a)
        p.setBrush(背)
        p.drawRoundedRect(self.rect(), 10, 10)
        if self.懸停 and not self.設["穿透"]:      # 滑鼠在上面時畫一圈細框，讓人看得出面板範圍
            p.setPen(QColor(139, 108, 255, 200))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)

    # ---------- 拖曳移動、拖邊緣縮放 ----------
    def 邊緣(self, pos):
        e = Qt.Edge(0)
        w, h, b = self.width(), self.height(), min(self.邊寬, max(2, min(self.width(), self.height()) // 4))
        if pos.x() <= b:
            e |= Qt.LeftEdge
        elif pos.x() >= w - b:
            e |= Qt.RightEdge
        if pos.y() <= b:
            e |= Qt.TopEdge
        elif pos.y() >= h - b:
            e |= Qt.BottomEdge
        return e

    def 按下(self, 全域點):
        邊 = self.邊緣(self.mapFromGlobal(全域點))
        if _值(邊):
            self.windowHandle().startSystemResize(邊)
        else:
            self.windowHandle().startSystemMove()


def _值(邊):
    return 邊.value if hasattr(邊, "value") else int(邊)


游標形狀 = {
    _值(Qt.LeftEdge): Qt.SizeHorCursor, _值(Qt.RightEdge): Qt.SizeHorCursor,
    _值(Qt.TopEdge): Qt.SizeVerCursor, _值(Qt.BottomEdge): Qt.SizeVerCursor,
    _值(Qt.LeftEdge | Qt.TopEdge): Qt.SizeFDiagCursor, _值(Qt.RightEdge | Qt.BottomEdge): Qt.SizeFDiagCursor,
    _值(Qt.RightEdge | Qt.TopEdge): Qt.SizeBDiagCursor, _值(Qt.LeftEdge | Qt.BottomEdge): Qt.SizeBDiagCursor,
}


# ---------- 管理：開關面板、接事件、版面配置 ----------
class 面板管理(QObject):
    def __init__(self, 台):
        super().__init__(台)
        self.台 = 台                     # 主控台
        self.面板們 = {}                 # 種類 → 面板
        設定 = live_topics.載入設定({})[0]
        self.置頂 = bool(設定["newest_on_top"])
        self.紀錄們 = {k: 紀錄(設定[上限鍵[k]]) for k in 種類們}
        台.橋.收到.connect(self.收事件)      # 和主控台同一條事件
        QApplication.instance().installEventFilter(self)
        self.游標位置 = QCursor.pos        # 測試時可以換掉
        self._游標覆蓋 = None
        self.懸停計時 = QTimer(self, interval=80, timeout=self._看懸停)
        self.懸停計時.start()
        self.存檔 = self._讀檔()

    # ---------- 版面檔 ----------
    def _讀檔(self):
        try:
            with open(版面檔, encoding="utf-8-sig") as f:
                資料 = json.load(f)
        except Exception:
            資料 = {}
        資料 = 資料 if isinstance(資料, dict) else {}
        版面們 = 資料.get("版面們") if isinstance(資料.get("版面們"), dict) else {}
        return {"目前": 資料.get("目前") if isinstance(資料.get("目前"), list) else None,
                "版面們": {str(k): v for k, v in 版面們.items() if isinstance(v, list)}}

    def _寫檔(self):
        try:
            暫存 = 版面檔 + ".tmp"
            with open(暫存, "w", encoding="utf-8") as f:
                json.dump(self.存檔, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(暫存, 版面檔)
        except Exception:
            pass

    def 目前快照(self):
        return [self.面板們[k].快照() for k in 種類們 if k in self.面板們]

    def 存目前(self):
        self.存檔["目前"] = self.目前快照()
        self._寫檔()

    def 還原上次(self):
        """程式開啟時：把上次關掉時開著的面板照原樣開回來（沒有紀錄就什麼都不開）。"""
        if self.存檔["目前"]:
            self.套用(self.存檔["目前"], 存=False)

    def 套用(self, 清單, 存=True):
        for 面 in list(self.面板們.values()):
            面.收掉()
        self.面板們 = {}
        for 原始 in 清單:
            s = 整理面板設定(原始)
            if s and s["種類"] not in self.面板們:
                self._開(移回畫面內(s))
        self._更新翻譯啟用()
        if 存:
            self.存目前()

    def 版面名們(self):
        return list(self.存檔["版面們"])

    def 另存版面(self, 名):
        self.存檔["版面們"][名] = self.目前快照()
        self._寫檔()

    def 套用版面(self, 名):
        if 名 in self.存檔["版面們"]:
            self.套用(self.存檔["版面們"][名])

    def 刪除版面(self, 名):
        self.存檔["版面們"].pop(名, None)
        self._寫檔()

    def 重設預設(self):
        self.套用(預設版面())

    def 全部取消穿透(self):
        for 面 in self.面板們.values():
            面.設穿透(False)

    # ---------- 開關面板 ----------
    def 做頁(self, 種類):
        return self.台.做面板頁(種類)

    def _開(self, s):
        面 = 面板(self, s)
        self.面板們[s["種類"]] = 面
        面.顯示()
        return 面

    def 開關(self, 種類, 開):
        if 開 and 種類 not in self.面板們:
            已存 = next((x for x in (self.存檔["目前"] or []) if isinstance(x, dict) and x.get("種類") == 種類), None)
            s = 整理面板設定(已存) if 已存 else None
            if not s:
                預 = next((x for x in 預設版面() if x["種類"] == 種類), None)
                g = QGuiApplication.primaryScreen().availableGeometry()
                s = 預 or dict(面板預設, 種類=種類, w=g.width() // 4, h=g.height() // 2,
                              x=g.x() + g.width() // 8 + 種類們.index(種類) * 40, y=g.y() + g.height() // 6)
            self._開(移回畫面內(s))
        elif not 開 and 種類 in self.面板們:
            self.面板們.pop(種類).收掉()
        self._更新翻譯啟用()
        self.存目前()

    def 面板關了(self, 面):
        self.開關(面.種類, False)

    def 全部收掉(self):
        """主控台關閉時：記下目前的面板，再全部關掉。"""
        self.存目前()
        for 面 in list(self.面板們.values()):
            面.收掉()
        self.面板們 = {}

    def 要翻譯(self):
        return "逐句翻譯" in self.面板們

    def _更新翻譯啟用(self):
        """逐句翻譯面板開著時，和字幕框開著一樣會進行翻譯（翻譯邏輯本身不變）。"""
        台 = self.台
        if 台.執行中():
            台.字幕器.啟用 = 台.字幕框.開啟 or self.要翻譯()
        台._更新翻譯註()
        self._同步註()

    def _同步註(self):
        註 = self.台.翻譯頁.註.text() if self.台.翻譯頁.註.isVisible() or self.台.翻譯頁.註.text() else ""
        if 註 != self.紀錄們["逐句翻譯"].註:
            self.紀錄們["逐句翻譯"].註 = 註
            面 = self.面板們.get("逐句翻譯")
            if 面 and hasattr(面.清單頁, "設註"):
                面.清單頁.設註(註)

    # ---------- 主控台的動作 ----------
    def 開始(self, 設定):
        for k, 紀 in self.紀錄們.items():
            紀.清空()
            紀.設上限(設定[上限鍵[k]])
        for 面 in self.面板們.values():
            面.開始()
        self._同步註()

    def 設方向(self, 置頂):
        self.置頂 = bool(置頂)
        for 面 in self.面板們.values():
            面.清單頁.設方向(self.置頂)

    # ---------- 事件（和主控台 處理事件 對應）----------
    def _加(self, 種類, 方法, 參數, 純):
        紀 = self.紀錄們[種類]
        紀.項目們.append((方法, 參數, 純))
        紀.總數 += 1
        面 = self.面板們.get(種類)
        if 面:
            面.新項目(方法, 參數)

    def _設檔案(self, 種類, 路徑):
        self.紀錄們[種類].檔案 = 路徑
        面 = self.面板們.get(種類)
        if 面:
            面.清單頁.設檔案(路徑)

    def _設進行中(self, 值):
        self.紀錄們["話題摘要"].進行中 = 值
        面 = self.面板們.get("話題摘要")
        if 面:
            面.進行中變了()

    def 收事件(self, 種類, 內容):
        台 = self.台
        淡 = "#8a91a5"
        if 種類 == "files":
            for k, 鍵 in 檔案鍵.items():
                self._設檔案(k, 內容[鍵])
        elif 種類 == "transcript_line":
            self._加("直播稿", "加一行", (f'<span style="color:{淡};">{跳脫(內容["時間字"])}</span>&nbsp;&nbsp;{跳脫(內容["內容"])}',),
                    內容["內容"])
            if 內容["內容"] and not subtitle.要翻譯(台.字幕器.模式, 台.字幕器.語言, 內容["內容"]):
                self._加("逐句翻譯", "加原文", (內容["時間字"], 內容["內容"]), 內容["內容"])
        elif 種類 == "translation_line":
            self._加("逐句翻譯", "加譯文", (內容["時間字"], 內容["原文"], 內容["譯文"]), 內容["譯文"] or 內容["原文"])
            if 內容.get("檔案"):
                self._設檔案("逐句翻譯", 內容["檔案"])
        elif 種類 == "chat_line":
            色 = ["#8b6cff", "#3ecf8e", "#4aa8ff", "#f5b84a", "#ff7ab6", "#5fd4d4", "#ff9f5a", "#b8e05a"]
            色 = 色[sum(map(ord, 內容["使用者"])) % len(色)]
            self._加("聊天室", "加一行", (
                f'<span style="color:{淡};">{跳脫(內容["時間字"])}</span>&nbsp;&nbsp;'
                f'<b style="color:{色};">{跳脫(內容["使用者"])}</b>&nbsp;&nbsp;{跳脫(內容["內容"])}',),
                f'{內容["使用者"]}：{內容["內容"]}')
        elif 種類 == "minute_summary":
            純 = live_topics.時間標記.sub("", 內容["摘要"], count=1).strip()
            self._加("分鐘摘要", "加卡片", (台._分鐘html(內容),), 純)
        elif 種類 == "topic_summary":
            標題 = next((行.strip()[len("【話題標題】"):].strip() for 行 in 內容["內文"].splitlines()
                       if 行.strip().startswith("【話題標題】")), "話題")
            摘要 = next((行.strip()[len("【摘要】"):].strip() for 行 in 內容["內文"].splitlines()
                       if 行.strip().startswith("【摘要】")), "")
            self._加("話題摘要", "加卡片", (台._話題html(內容),), f"{標題}：{摘要}" if 摘要 else 標題)
        elif 種類 == "current_topic":
            self._設進行中((f"已進行 {內容['進行分鐘']:.0f} 分鐘", 內容["簡述"] or "（新話題剛開始）"))
        elif 種類 in ("error", "finished"):
            self._設進行中(None)
        elif 種類 == "language_detected":
            self._同步註()

    # ---------- 懸停控制項、邊緣游標、拖曳 ----------
    def _看懸停(self):
        點 = self.游標位置()
        邊游標 = None
        for 面 in list(self.面板們.values()):
            if not 面.isVisible():
                continue
            在上面 = 面.frameGeometry().contains(點) or (面.控制.isVisible() and 面.控制.frameGeometry().contains(點))
            if 面.設["穿透"]:
                在上面 = False
            if 在上面 != 面.懸停:
                面.懸停 = 在上面
                面.update()
            if 在上面:
                面.控制.浮現()
                if 面.frameGeometry().contains(點) and not 面.控制.frameGeometry().contains(點):
                    邊 = 面.邊緣(面.mapFromGlobal(點))
                    邊游標 = 游標形狀.get(_值(邊)) if _值(邊) else None
            else:
                面.控制.準備淡出()
        if 邊游標 != self._游標覆蓋:
            if self._游標覆蓋 is not None:
                QApplication.restoreOverrideCursor()
            if 邊游標 is not None:
                QApplication.setOverrideCursor(邊游標)
            self._游標覆蓋 = 邊游標

    def eventFilter(self, 物, e):
        """面板上任何地方按左鍵：邊緣 = 縮放，其他 = 拖曳移動（按鈕、捲軸照常操作）。"""
        if e.type() == QEvent.MouseButtonPress and isinstance(物, QWidget) and e.button() == Qt.LeftButton:
            窗 = 物.window()
            if isinstance(窗, 面板) and 窗.種類 in self.面板們 and self.面板們[窗.種類] is 窗:
                if isinstance(物, (QAbstractButton, QAbstractSlider)):
                    return False
                窗.按下(e.globalPosition().toPoint())
                return True
        return False

    # ---------- 主控台的「面板」選單 ----------
    def 做選單(self, 父):
        選單 = QMenu(父)
        選單.setStyleSheet("""
            QMenu { background: #1d2029; border: 1px solid #2a2e3a; padding: 4px; }
            QMenu::item { padding: 6px 22px 6px 22px; border-radius: 6px; color: #e7e9ef; }
            QMenu::item:selected { background: #8b6cff; color: white; }
            QMenu::item:disabled { color: #5a6072; }
            QMenu::separator { height: 1px; background: #2a2e3a; margin: 4px 8px; }
            QMenu::indicator { width: 14px; height: 14px; left: 4px; }
        """)
        選單.aboutToShow.connect(lambda: self._填選單(選單))
        return 選單

    def _填選單(self, 選單):
        選單.clear()
        for k in 種類們:
            a = 選單.addAction(k + " 面板")
            a.setCheckable(True)
            a.setChecked(k in self.面板們)
            a.toggled.connect(lambda 開, k=k: self.開關(k, 開))
        選單.addSeparator()
        套 = 選單.addMenu("套用版面")
        刪 = 選單.addMenu("刪除版面")
        for 子 in (套, 刪):
            子.setStyleSheet(選單.styleSheet())
        名們 = self.版面名們()
        for 名 in 名們:
            套.addAction(名).triggered.connect(lambda _=False, 名=名: self.套用版面(名))
            刪.addAction(名).triggered.connect(lambda _=False, 名=名: self._問刪除(名))
        套.setEnabled(bool(名們))
        刪.setEnabled(bool(名們))
        選單.addAction("另存版面…").triggered.connect(self._問另存)
        選單.addAction("重設為預設版面").triggered.connect(self.重設預設)
        選單.addSeparator()
        a = 選單.addAction("全部取消穿透")
        a.setEnabled(any(面.設["穿透"] for 面 in self.面板們.values()))
        a.triggered.connect(self.全部取消穿透)

    def _問另存(self):
        名, 好 = QInputDialog.getText(self.台, "另存版面", "版面名稱（同名會覆蓋）：")
        名 = (名 or "").strip()
        if not 好 or not 名:
            return
        if 名 in self.存檔["版面們"]:
            if QMessageBox.question(self.台, "另存版面", f"已經有「{名}」，要覆蓋嗎？") != QMessageBox.Yes:
                return
        self.另存版面(名)
        self.台._訊息(f"已存成版面「{名}」（{len(self.面板們)} 個面板）。")

    def _問刪除(self, 名):
        if QMessageBox.question(self.台, "刪除版面", f"確定刪除版面「{名}」？") == QMessageBox.Yes:
            self.刪除版面(名)
