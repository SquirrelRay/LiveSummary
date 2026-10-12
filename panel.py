# 面板（新介面第一階段）：可自由擺放的無邊框小視窗，每個面板顯示五種內容之一：
#   分鐘摘要、話題摘要、逐句翻譯、直播稿、聊天室
# 面板不另外跑引擎：和主控台接同一條事件（主控台的 事件橋），內容的顯示上限、捲動方向（newest_on_top）、
# 手動往上捲不被拉回、「較早的內容已存檔」都直接重用主控台分頁的元件（app.py 的 卡片清單／文字清單／逐句頁）。
# 每個面板兩種樣式：清單（深色背景的內容清單）、字幕（透明背景、大字置中、只顯示最新幾則）。
# 面板上只有一個小 ✕（滑鼠移到面板上才在右上角浮現，離開約 1.5 秒後淡出）；其他設定都在膠囊／系統匣選單的「面板」子選單（建立面板選單）。
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
from PySide6.QtGui import QActionGroup

import overlay          # 最上層、滑鼠穿透（Windows 原生）
import subtitle
import live_topics
import startup_timeline

版面檔 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "版面配置.json")
種類們 = ["分鐘摘要", "話題摘要", "逐句翻譯", "直播稿", "聊天室"]
上限鍵 = {"分鐘摘要": "ui_max_summary", "話題摘要": "ui_max_summary", "直播稿": "ui_max_transcript",
         "逐句翻譯": "ui_max_translation", "聊天室": "ui_max_chat"}
檔案鍵 = {"直播稿": "稿", "聊天室": "聊天", "分鐘摘要": "分鐘", "話題摘要": "話題"}
清單基準字級 = 14          # 清單樣式的字級 = 14 時和主控台分頁一樣大
HWND_NOTOPMOST = overlay.wintypes.HWND(-2)
WS_EX_TOPMOST = 0x8

提示種類 = ("逐句翻譯", "分鐘摘要", "話題摘要")      # 還沒有內容時顯示階段提示的面板
最小尺寸 = {"清單": (200, 40), "字幕": (200, 20)}     # (最小寬, 最小高)
透明度級距 = [1.0, 0.8, 0.6, 0.4, 0.2]               # 文字、背景透明度選單的固定級距（背景另外多一個 0%）

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
    最寬, 最高 = 最小尺寸[s["樣式"]]
    s["w"], s["h"] = max(最寬, s["w"]), max(最高, s["h"])
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
class 關閉鈕(QPushButton):
    """面板右上角的小 ✕：是面板裡面的一個小元件（不是獨立視窗），所以滑鼠停在上面或在面板與 ✕ 之間移動都不會閃。
    滑鼠在面板範圍內就顯示（淡入），離開約 1.5 秒後淡出；其他設定都在膠囊選單的「面板」子選單。"""
    尺寸 = 22

    def __init__(self, 面):
        super().__init__("✕", 面)
        self.面 = 面
        self.setToolTip("關閉這個面板")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self.尺寸, self.尺寸)
        self.setStyleSheet("QPushButton { background: rgba(22,25,32,235); color: #ff5c7a; border: 1px solid #8b6cff;"
                           " border-radius: 11px; padding: 0; font-size: 12px; font-weight: 700; }"
                           "QPushButton:hover { background: #ff5c7a; color: white; }")
        self.效果 = QGraphicsOpacityEffect(self)
        self.效果.setOpacity(0.0)
        self.setGraphicsEffect(self.效果)
        self.動畫 = QPropertyAnimation(self.效果, b"opacity", self)
        self.動畫.setDuration(250)
        self.動畫.finished.connect(self._完成)
        self.淡出計時 = QTimer(self, singleShot=True, interval=1500, timeout=self.淡出)
        self.目標 = 0.0
        self.hide()
        self.clicked.connect(面.關閉)

    def _動到(self, v):
        if self.目標 == v:
            return
        self.目標 = v
        self.動畫.stop()
        self.動畫.setStartValue(self.效果.opacity())
        self.動畫.setEndValue(v)
        self.動畫.start()

    def _完成(self):
        if self.目標 == 0.0:
            self.hide()

    def 浮現(self):
        """滑鼠在面板上：持續呼叫也不會重新開始動畫，不會閃。"""
        self.淡出計時.stop()
        if not self.isVisible():
            self.show()
        self.raise_()
        self._動到(1.0)

    def 準備淡出(self):
        if self.isVisible() and self.目標 == 1.0 and not self.淡出計時.isActive():
            self.淡出計時.start()

    def 淡出(self):
        self._動到(0.0)

    def 立刻隱藏(self):
        self.淡出計時.stop()
        self.動畫.stop()
        self.目標 = 0.0
        self.效果.setOpacity(0.0)
        self.hide()

    def 擺放(self):
        self.move(self.面.width() - self.width() - 4, 4)
        self.raise_()


class 面板(QWidget):
    邊寬 = 7          # 滑鼠在邊緣幾像素內 = 拖曳縮放

    def __init__(self, 管理, 設定):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.管理, self.設 = 管理, dict(設定)
        self.種類 = 設定["種類"]
        self.setWindowTitle("直播摘要 面板：" + self.種類)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumSize(*最小尺寸[設定.get('樣式', '清單')])
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
        self.關鈕 = 關閉鈕(self)
        self.懸停 = False
        self.置頂計時 = QTimer(self, interval=500, timeout=self._保持置頂)
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
        self._原提示 = None
        self._排()
        self.更新提示()

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
            提示 = self._空提示() or f"（{self.種類}會出現在這裡）"
            self.字幕字.setText(f'<span style="color:rgba(255,255,255,{round(140 * a)});">{跳脫(提示)}</span>')

    def _空提示(self):
        """還沒有內容時的階段提示（載入模型中…等）；這種面板不顯示、或已經完成就是空字串。"""
        return self.管理.階段.提示() if self.種類 in 提示種類 else ""

    def 更新提示(self):
        """清單樣式：把頁面原本的空白提示換成階段提示（沒有階段提示就換回原文字）；字幕樣式：重畫。"""
        頁 = self.清單頁
        if 頁 is None:
            return
        提示 = self._空提示()
        if isinstance(getattr(頁, "提示", None), QLabel):          # 卡片清單（分鐘摘要、話題摘要）
            if self._原提示 is None:
                self._原提示 = 頁.提示.text()
            頁.提示.setText(提示 or self._原提示)
        elif hasattr(頁, "瀏覽"):                                    # 文字清單、逐句頁（逐句翻譯）
            if self._原提示 is None:
                self._原提示 = 頁.瀏覽.placeholderText()
            頁.瀏覽.setPlaceholderText(提示 or self._原提示)
        if self.設["樣式"] == "字幕":
            self._畫字幕()

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
        self.setMinimumSize(*最小尺寸[s["樣式"]])
        self._排()
        self.update()

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
        self.設則數(self.設["字幕則數"] + 差)

    def 設則數(self, n):
        self.設["字幕則數"] = min(10, max(1, int(n)))
        self.改了()

    def 設置頂(self, 開):
        self.設["置頂"] = bool(開)
        self._套視窗樣式()
        self.存計時.start()

    def 設穿透(self, 開):
        self.設["穿透"] = bool(開)
        if 開:
            self.關鈕.立刻隱藏()
        self._套視窗樣式()
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

    def _保持置頂(self):
        """只有前景是全螢幕程式（例如瀏覽器全螢幕播放）才重新拉到最上層；
        截圖工具、工作管理員、開始選單等系統視窗出現時不去蓋它們。"""
        if self.isVisible() and self.設["置頂"] and overlay.前景是全螢幕程式():
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
        self.關鈕.立刻隱藏()
        self.管理.面板關了(self)

    def 收掉(self):
        self.存計時.stop()          # 已經關掉的面板不能再把版面存回去
        self.置頂計時.stop()
        self.close()
        self.deleteLater()

    def _排(self):
        r = self.rect()
        self.清單容器.setGeometry(r.adjusted(2, 2, -2, -2))
        self.字幕字.setGeometry(r.adjusted(6, 2, -6, -2))
        self.關鈕.擺放()
        if self.清單頁 is not None:          # 很矮的橫條：不顯示「較早的內容已存檔」那一列，把空間留給內容
            self.清單頁.頂.setMaximumHeight(0 if self.height() < 90 else 16777215)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._排()
        if self.isVisible():
            self.存計時.start()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.isVisible():
            self.存計時.start()

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
        self.階段 = startup_timeline.啟動階段()      # 面板還沒有內容時顯示哪一句提示

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

    def 套用上次或預設(self):
        """按了「開始」：還沒有面板開著時，套用上次使用的版面（上次開著的面板），沒有紀錄就套用預設版面。"""
        if not self.面板們:
            self.套用(self.存檔["目前"] or 預設版面())

    def 全部收掉(self):
        """結束程式時：記下目前的面板，再全部關掉（一個面板都沒開時不覆蓋上次的版面）。"""
        if self.面板們:
            self.存目前()
        for 面 in list(self.面板們.values()):
            面.收掉()
        self.面板們 = {}

    def 要翻譯(self):
        return "逐句翻譯" in self.面板們

    def _更新翻譯啟用(self):
        """只有逐句翻譯面板開著才進行翻譯（翻譯邏輯本身不變）；其他面板都不需要翻譯。"""
        台 = self.台
        if 台.執行中():
            台.字幕器.啟用 = self.要翻譯()
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
    def 開始(self, 設定, 直播=True):
        self.階段.重設(有模型=直播)
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

    def _更新提示(self):
        for 面 in self.面板們.values():
            面.更新提示()

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
        elif 種類 == "milestone":
            self.階段.收里程碑(內容["名稱"])
            self._更新提示()
        elif 種類 == "subtitle":
            startup_timeline.標記(startup_timeline.第一句顯示)
        elif 種類 == "transcript_line":
            if not 台.字幕器.啟用:           # 沒開逐句翻譯面板：不會有字幕，第一句文字稿出現就當作第一句
                startup_timeline.標記(startup_timeline.第一句顯示_無字幕)
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
            self.階段.結束()
            self._更新提示()
        elif 種類 == "language_detected":
            self._同步註()

    # ---------- 懸停控制項、邊緣游標、拖曳 ----------
    def _看懸停(self):
        點 = self.游標位置()
        邊游標 = None
        for 面 in list(self.面板們.values()):
            if not 面.isVisible():
                continue
            在上面 = 面.frameGeometry().contains(點) and not 面.設["穿透"]
            if 在上面 != 面.懸停:
                面.懸停 = 在上面
                面.update()
            if 在上面:
                面.關鈕.浮現()
                if not 面.關鈕.geometry().contains(面.mapFromGlobal(點)):
                    邊 = 面.邊緣(面.mapFromGlobal(點))
                    邊游標 = 游標形狀.get(_值(邊)) if _值(邊) else None
            else:
                面.關鈕.準備淡出()
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

    # ---------- 版面對話框 ----------
    def 問另存(self, 父=None):
        父 = 父 or self.台
        名, 好 = QInputDialog.getText(父, "另存版面", "版面名稱（同名會覆蓋）：")
        名 = (名 or "").strip()
        if not 好 or not 名:
            return
        if 名 in self.存檔["版面們"]:
            if QMessageBox.question(父, "另存版面", f"已經有「{名}」，要覆蓋嗎？") != QMessageBox.Yes:
                return
        self.另存版面(名)
        self.台._訊息(f"已存成版面「{名}」（{len(self.面板們)} 個面板）。")

    def 問刪除(self, 名, 父=None):
        if QMessageBox.question(父 or self.台, "刪除版面", f"確定刪除版面「{名}」？") == QMessageBox.Yes:
            self.刪除版面(名)


選單樣式 = """
    QMenu { background: #1d2029; border: 1px solid #2a2e3a; padding: 4px; }
    QMenu::item { padding: 6px 22px 6px 22px; border-radius: 6px; color: #e7e9ef; }
    QMenu::item:selected { background: #8b6cff; color: white; }
    QMenu::item:disabled { color: #5a6072; }
    QMenu::separator { height: 1px; background: #2a2e3a; margin: 4px 8px; }
    QMenu::indicator { width: 14px; height: 14px; left: 4px; }
"""


def 建立面板選單(管, 父=None):
    """「面板」選單：開關五種面板、每個已開面板的設定子選單、套用／另存／刪除版面、重設為預設版面、全部取消穿透。
    獨立函式：只需要「面板管理」物件，之後要整份搬到浮動膠囊直接呼叫這個函式即可。
    每次要顯示前才重新填內容（aboutToShow），所以隨時反映目前開了哪些面板。"""
    選單 = QMenu(父)
    選單.setStyleSheet(選單樣式)
    選單.aboutToShow.connect(lambda: 填面板選單(管, 選單, 父))
    return 選單


def _子選單(上層, 標題):
    m = 上層.addMenu(標題)
    m.setStyleSheet(選單樣式)
    return m


def _單選(選單, 項目們, 目前, 動作, 相同=None):
    """項目們：[(顯示文字, 值)]；目前值打勾，點了呼叫 動作(值)。"""
    組 = QActionGroup(選單)
    組.setExclusive(True)
    for 字, 值 in 項目們:
        a = 選單.addAction(字)
        a.setCheckable(True)
        a.setActionGroup(組)
        a.setChecked((相同 or (lambda x, y: x == y))(值, 目前))
        a.triggered.connect(lambda _=False, v=值: 動作(v))


def 填面板選單(管, 選單, 父=None):
    選單.clear()
    for k in 種類們:
        a = 選單.addAction(k + " 面板")
        a.setCheckable(True)
        a.setChecked(k in 管.面板們)
        a.toggled.connect(lambda 開, k=k: 管.開關(k, 開))
    開著的 = [k for k in 種類們 if k in 管.面板們]
    if 開著的:
        選單.addSeparator()
    for k in 開著的:
        面 = 管.面板們[k]
        s = 面.設
        子 = _子選單(選單, f"{k} 設定")
        樣 = _子選單(子, "樣式")
        _單選(樣, [("清單", "清單"), ("字幕", "字幕")], s["樣式"], 面.設樣式)
        a = 子.addAction("疊在其他視窗上（置頂）")
        a.setCheckable(True)
        a.setChecked(s["置頂"])
        a.triggered.connect(lambda 開, 面=面: 面.設置頂(開))
        a = 子.addAction("滑鼠穿透")
        a.setCheckable(True)
        a.setChecked(s["穿透"])
        a.triggered.connect(lambda 開, 面=面: 面.設穿透(開))
        近 = lambda 值, 目前: abs(值 - 目前) < 0.1
        文 = _子選單(子, "文字透明度")
        _單選(文, [(f"{round(v * 100)}%", v) for v in 透明度級距], s["文字透明度"], 面.設文字透明度, 近)
        背 = _子選單(子, "背景透明度")
        _單選(背, [(f"{round(v * 100)}%", v) for v in 透明度級距 + [0.0]], s[s["樣式"] + "背景"], 面.設背景透明度, 近)
        子.addAction("字級放大").triggered.connect(lambda _=False, 面=面: 面.改字級(+2))
        子.addAction("字級縮小").triggered.connect(lambda _=False, 面=面: 面.改字級(-2))
        if s["樣式"] == "字幕":
            則 = _子選單(子, "字幕則數")
            _單選(則, [(f"{n} 則", n) for n in range(1, 6)], s["字幕則數"], 面.設則數)
        子.addSeparator()
        子.addAction("關閉這個面板").triggered.connect(lambda _=False, 面=面: 面.關閉())
    選單.addSeparator()
    套 = _子選單(選單, "套用版面")
    刪 = _子選單(選單, "刪除版面")
    名們 = 管.版面名們()
    for 名 in 名們:
        套.addAction(名).triggered.connect(lambda _=False, 名=名: 管.套用版面(名))
        刪.addAction(名).triggered.connect(lambda _=False, 名=名: 管.問刪除(名, 父))
    套.setEnabled(bool(名們))
    刪.setEnabled(bool(名們))
    選單.addAction("另存版面…").triggered.connect(lambda: 管.問另存(父))
    選單.addAction("重設為預設版面").triggered.connect(管.重設預設)
    選單.addSeparator()
    a = 選單.addAction("全部取消穿透")
    a.setEnabled(any(面.設["穿透"] for 面 in 管.面板們.values()))
    a.triggered.connect(管.全部取消穿透)
