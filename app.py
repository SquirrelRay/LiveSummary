# 直播摘要主控台（桌面介面）
# 用法：python app.py
# 引擎（live_topics.py）在背景執行緒跑，結果透過 events.py 的事件送過來，介面只負責顯示。
import os
import sys
import html
import time
import threading

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QPoint, QEvent, QSize
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QTextCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QLineEdit, QPushButton, QComboBox,
    QHBoxLayout, QVBoxLayout, QTabBar, QTextBrowser, QScrollArea, QFileDialog,
    QButtonGroup, QSizePolicy,
)

專案目錄 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 專案目錄)

import events
import llm
import live_topics
import subtitle      # 逐句字幕（原文或翻譯）
import chat_translate  # 聊天室翻譯（和逐句字幕分開的另一條翻譯執行緒）
import settings_page # 設定框
import names_page    # 名詞清單（直播主詞庫的寫法訂正）
import glossary
import ui_state      # 網址紀錄、並排欄數（本機記憶）
import panel         # 可自由擺放的面板與版面配置（新介面第一階段）
import capsule       # 浮動膠囊與系統匣圖示（新介面第二階段）
import launcher      # 啟動面板（開程式時出現，取代主控台當作入口）
import onboarding    # 首次引導（第一次打開時出現；選單「使用說明」可重新打開）
import startup_timeline  # 啟動時間里程碑紀錄
import subtitle_speed    # 字幕速度段位（分段秒數與翻譯批次）
import language_state    # 目前語言（狀態列的語言藥丸與重新偵測）
import config            # 設定檔 config.json 的讀取、語言清單
import model_catalog     # 模型服務目錄與單價（單價未知 → 費用顯示「單價未知，無法估算」）
import stream_clock      # 這一場的直播時軸（「幾分鐘前」要知道現在是直播的第幾秒）
import timefmt           # 時間格式與「幾分鐘前」

語言選項 = config.語言選項()          # 中文、日文、英文、韓文、自動偵測
速度選項 = [("60 倍速", 60), ("30 倍速", 30), ("10 倍速", 10), ("真實速度", 1), ("瞬間跑完", 0)]

# ---- 顏色（深色主題）----
底色, 面板, 卡片, 邊框 = "#0e1015", "#161920", "#1d2029", "#2a2e3a"
文字色, 淡字, 主色, 綠, 紅, 黃 = "#e7e9ef", "#8a91a5", "#8b6cff", "#3ecf8e", "#ff5c7a", "#f5b84a"
名字顏色 = ["#8b6cff", "#3ecf8e", "#4aa8ff", "#f5b84a", "#ff7ab6", "#5fd4d4", "#ff9f5a", "#b8e05a"]

樣式表 = f"""
* {{ color: {文字色}; }}
QMainWindow, QWidget#根 {{ background: {底色}; }}
QFrame#面板 {{ background: {面板}; border: 1px solid {邊框}; border-radius: 14px; }}
QFrame#卡片 {{ background: {卡片}; border: 1px solid {邊框}; border-radius: 12px; }}
QLabel {{ background: transparent; border: none; }}
QLabel#標題 {{ font-size: 18px; font-weight: 700; }}
QLabel#淡 {{ color: {淡字}; }}
QLabel#小標 {{ color: {淡字}; font-size: 12px; }}
QLabel#藥丸 {{ background: {卡片}; border: 1px solid {邊框}; border-radius: 9px; padding: 1px 8px; font-size: 12px; }}
QFrame#進行卡 {{ background: {卡片}; border: 1px solid {主色}; border-radius: 12px; }}
QLabel#進行標 {{ background: {主色}; color: white; font-weight: 700; font-size: 12px; border-radius: 8px; padding: 1px 8px; }}
QFrame#提示條 {{ background: {卡片}; border: 1px solid {邊框}; border-radius: 10px; }}
QFrame#提示條[錯誤="true"] {{ border: 1px solid {紅}; }}
QPushButton#關閉 {{ padding: 0px; border: none; border-radius: 9px; color: {淡字}; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; }}
QPushButton#關閉:hover {{ background: {邊框}; }}
QLabel#話題浮窗 {{ background: {卡片}; border: 1px solid {主色}; border-radius: 10px; padding: 10px 14px; }}
QLineEdit, QComboBox {{
    background: {卡片}; border: 1px solid {邊框}; border-radius: 10px; padding: 7px 12px;
    selection-background-color: {主色};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {主色}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {淡字}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {卡片}; border: 1px solid {邊框}; selection-background-color: {主色}; outline: none; padding: 4px;
}}
QPushButton {{
    background: {卡片}; border: 1px solid {邊框}; border-radius: 10px; padding: 8px 16px;
}}
QPushButton:hover {{ border: 1px solid {主色}; }}
QPushButton:disabled {{ color: #5a6072; border: 1px solid {邊框}; }}
QPushButton#開始 {{ background: {主色}; border: none; font-weight: 700; color: white; }}
QPushButton#開始:hover {{ background: #9d82ff; }}
QPushButton#開始:disabled {{ background: #3a3456; color: #8f88aa; }}
QPushButton#停止 {{ background: transparent; border: 1px solid {紅}; color: {紅}; font-weight: 700; }}
QPushButton#停止:hover {{ background: rgba(255,92,122,0.12); }}
QPushButton#停止:disabled {{ border: 1px solid {邊框}; color: #5a6072; }}
QPushButton#切換 {{ border-radius: 9px; padding: 6px 14px; background: transparent; border: none; color: {淡字}; }}
QPushButton#切換:checked {{ background: {主色}; color: white; font-weight: 700; }}
QPushButton#小鈕 {{ padding: 2px 10px; border-radius: 8px; font-size: 12px; color: {淡字}; }}
QCheckBox {{ spacing: 6px; }}
QFrame#切換框 {{ background: {卡片}; border: 1px solid {邊框}; border-radius: 12px; }}
QFrame#窗格 {{ border: 1px solid {邊框}; border-radius: 14px; background: {面板}; }}
QPushButton#並排鈕 {{ padding: 2px 8px; min-width: 10px; border-radius: 8px; border: none; background: transparent; color: {淡字}; font-size: 12px; }}
QPushButton#並排鈕:checked {{ background: {主色}; color: white; font-weight: 700; }}
QPushButton#並排鈕[超過="true"] {{ color: #5a6072; }}
QPushButton#並排鈕[超過="true"]:checked {{ background: #3a3456; color: #8f88aa; }}
QTabBar QToolButton {{ background: {卡片}; border: 1px solid {邊框}; border-radius: 6px; }}
QFrame#網址清單 {{ background: {卡片}; border: 1px solid {主色}; border-radius: 10px; }}
QFrame#網址列 {{ background: transparent; border: none; border-radius: 8px; }}
QFrame#網址列:hover {{ background: #262a38; }}
QPushButton#圖鈕 {{ padding: 0px; border: none; border-radius: 9px; color: {淡字}; background: transparent; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; }}
QPushButton#圖鈕:hover {{ background: {邊框}; }}
QTabBar::tab {{
    background: transparent; color: {淡字}; padding: 8px 18px; margin-right: 4px;
    border-top-left-radius: 10px; border-top-right-radius: 10px;
}}
QTabBar::tab:selected {{ background: {面板}; color: {文字色}; font-weight: 700; border: 1px solid {邊框}; border-bottom: 2px solid {主色}; }}
QTabBar::tab:hover:!selected {{ color: {文字色}; }}
QTextBrowser, QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: #343947; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #454b5c; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ height: 0; background: none; }}
QMessageBox {{ background: {面板}; }}
QMessageBox QPushButton {{ min-width: 80px; }}
QToolTip {{ background: {卡片}; color: {文字色}; border: 1px solid {邊框}; }}
QTableWidget {{ background: {面板}; border: 1px solid {邊框}; border-radius: 8px; gridline-color: {邊框};
    selection-background-color: #3a3456; selection-color: {文字色}; }}
QTableWidget QLineEdit {{ border-radius: 4px; padding: 2px 6px; }}
QHeaderView::section {{ background: {卡片}; color: {淡字}; border: none; border-bottom: 1px solid {邊框}; padding: 6px 8px; }}
"""


結束中文字 = "正在產生最後一個話題的摘要，約需 10 秒…"
翻譯收尾文字 = "正在翻譯剩下的句子…"
翻譯收尾最多秒 = 10     # 收尾翻譯最多等幾秒，超時就放棄


def 跳脫(字):
    return html.escape(str(字))


class 事件橋(QObject):
    """背景執行緒送來的事件，透過 Qt 訊號轉到介面執行緒處理（介面元件只能在介面執行緒動）。"""
    收到 = Signal(str, dict)
    結束 = Signal()

    def 接收(self, 種類, 內容):
        self.收到.emit(種類, dict(內容))


class 跟隨(QObject):
    """新內容進來時自動跟隨：最新在下 → 捲在最底時跟著到底；最新在上 → 捲在最頂時留在頂。
    使用者手動捲離了就不動；最新在上時內容加在上方，會把捲動位置往下補回去，讓使用者正在看的那一段不跑掉。"""

    def __init__(self, 捲軸):
        super().__init__(捲軸)
        self.捲軸 = 捲軸
        self.置頂 = False
        self.黏 = True
        self.舊高 = 捲軸.maximum()
        self.補償 = 0          # 最新在上時，從最下面移除的內容高度（範圍縮小不是因為上方變少）
        捲軸.valueChanged.connect(self._值變了)
        捲軸.rangeChanged.connect(self._範圍變了)

    def 設方向(self, 置頂):
        self.置頂 = 置頂
        self.黏 = True
        self.補償 = 0
        self.舊高 = self.捲軸.maximum()
        self.捲軸.setValue(0 if 置頂 else self.捲軸.maximum())

    def _值變了(self, v):
        self.黏 = v <= 8 if self.置頂 else v >= self.捲軸.maximum() - 8

    def _範圍變了(self, lo, hi):
        舊, self.舊高 = self.舊高, hi
        if self.黏:
            self.捲軸.setValue(0 if self.置頂 else hi)
        elif self.置頂:
            self.捲軸.setValue(self.捲軸.value() + (hi - 舊) + self.補償)
        self.補償 = 0


class 頂列(QWidget):
    """分頁上「較早的內容已存檔」＋「打開檔案」按鈕，放在最舊內容的那一端；內容還沒超過上限時不顯示。"""

    def __init__(self):
        super().__init__()
        版 = QHBoxLayout(self)
        版.setContentsMargins(16, 8, 16, 0)
        self.字 = QLabel("較早的內容已存檔")
        self.字.setObjectName("淡")
        self.鈕 = QPushButton("打開檔案")
        self.鈕.setObjectName("小鈕")
        self.鈕.setCursor(Qt.PointingHandCursor)
        self.鈕.clicked.connect(self.打開)
        版.addWidget(self.字)
        版.addWidget(self.鈕)
        版.addStretch(1)
        self.檔案 = None
        self.hide()

    def 打開(self):
        if self.檔案 and os.path.exists(self.檔案):
            os.startfile(self.檔案)
        else:
            self.字.setText("較早的內容已存檔（檔案找不到）")


class 分頁基底(QWidget):
    """一列提示加一個清單。清單超過上限就從最舊的開始從畫面移除（存檔不受影響）。
    置頂 = 最新在上：最舊的內容在最下面，提示列也跟著放最下面。"""

    def __init__(self, 內):
        super().__init__()
        self.版 = QVBoxLayout(self)
        self.版.setContentsMargins(0, 0, 0, 0)
        self.版.setSpacing(0)
        self.頂 = 頂列()
        self.版.addWidget(self.頂)
        self.版.addWidget(內, 1)
        self.上限 = 500
        self.總數 = 0
        self.置頂 = False

    def 設上限(self, n):
        self.上限 = int(n)

    def 設檔案(self, 路徑):
        """路徑 = None：這項內容沒有存檔（存檔關閉），超過上限時只說「已移除」，不顯示「打開檔案」。"""
        self.頂.檔案 = 路徑
        self.頂.字.setText("較早的內容已存檔" if 路徑 else "較早的內容已移除")
        self.頂.鈕.setVisible(bool(路徑))

    def _超過了(self):
        if self.總數 > self.上限:
            self.頂.show()

    def _頂位置(self):
        return 0

    def 設方向(self, 置頂):
        self.置頂 = 置頂
        self.版.removeWidget(self.頂)
        self.版.insertWidget(self.版.count() if 置頂 else self._頂位置(), self.頂)
        self.頂.layout().setContentsMargins(16, 0, 16, 8) if 置頂 else self.頂.layout().setContentsMargins(16, 8, 16, 0)


def 留言資料(內容):
    """chat_line／chat_show 事件 → 聊天室一則留言的資料（chat_line 沒有譯文）。"""
    return {"編號": 內容.get("編號"), "時間字": 內容["時間字"], "使用者": 內容["使用者"], "內容": 內容["內容"],
            "譯文": 內容.get("譯文")}


def 留言html(資料, 只看譯文=False):
    """聊天室一則留言的 html。資料：{編號, 時間字, 使用者, 內容, 譯文}（譯文 None = 沒翻或還沒翻好）。
    有譯文：原文改淡色，下一行縮排「↳ 譯文」（較亮）；只看譯文：有譯文的只顯示譯文，沒譯文的照樣顯示原文。"""
    色 = 名字顏色[sum(map(ord, 資料["使用者"])) % len(名字顏色)]
    頭 = (f'<span style="color:{淡字};">{跳脫(資料["時間字"])}</span>&nbsp;&nbsp;'
         f'<b style="color:{色};">{跳脫(資料["使用者"])}</b>&nbsp;&nbsp;')
    譯 = 資料.get("譯文")
    if not 譯:
        return 頭 + 跳脫(資料["內容"])
    if 只看譯文:
        return 頭 + f'<span style="color:#ffffff;">{跳脫(譯)}</span>'
    return (頭 + f'<span style="color:{淡字};">{跳脫(資料["內容"])}</span><br>'
            f'&nbsp;&nbsp;&nbsp;&nbsp;<span style="color:{淡字};">↳</span>&nbsp;<span style="color:#ffffff;">{跳脫(譯)}</span>')


class 文字清單(分頁基底):
    """直播稿、聊天室用：一行一行加，只留最近的 上限 行。最新在下 = 加在底部；最新在上 = 加在頂部。
    聊天室留言用 加留言：資料裡有譯文就原文（淡色）與譯文一起顯示；只看譯文時有譯文的只顯示譯文。"""

    def __init__(self, 提示):
        self.瀏覽 = QTextBrowser()
        super().__init__(self.瀏覽)
        self.瀏覽.setOpenExternalLinks(False)
        self.瀏覽.setPlaceholderText(提示)
        self.瀏覽.document().setDocumentMargin(16)
        self.條們 = []              # 目前畫面上每一行的 html，最舊的在前
        self.條資料 = []            # 和 條們 一一對應：聊天室留言的資料（dict），一般行是 None
        self.只看譯文 = False
        self.跟隨 = 跟隨(self.瀏覽.verticalScrollBar())

    def 設上限(self, n):
        super().設上限(n)
        self._套上限()

    def _套上限(self):
        # 最新在下：由 Qt 從最舊（最上面）的一行開始移除；最新在上：最舊的在最下面，Qt 做不到，改成自己移除
        self.瀏覽.document().setMaximumBlockCount(0 if self.置頂 else self.上限)

    def 加一行(self, 內容html):
        self._加(內容html, None)

    def 加留言(self, 資料):
        """聊天室留言。資料：{編號, 時間字, 使用者, 內容, 譯文}（譯文 None = 只有原文）。"""
        self._加(留言html(資料, self.只看譯文), 資料)

    def _加(self, 內容html, 資料):
        self.條們.append(內容html)
        self.條資料.append(資料)
        if not self.置頂:
            del self.條們[:-self.上限]
            del self.條資料[:-self.上限]
            self.瀏覽.append(內容html)
        else:
            if len(self.條們) > self.上限:
                del self.條們[0]
                del self.條資料[0]
                self._移除最後一行()
            self._頂端插入(內容html)
        self.總數 += 1
        self._超過了()

    def 設只看譯文(self, 開):
        """聊天室：有譯文的留言只顯示譯文（沒譯文的照樣顯示原文）。整份重畫。"""
        self.只看譯文 = bool(開)
        self.條們 = [留言html(d, self.只看譯文) if d is not None else h for h, d in zip(self.條們, self.條資料, strict=True)]
        self._重排全部()

    def 行文字(self):
        """測試用：畫面上由上到下每一行的純文字（同一則的換行用 / 表示，連續空白與不換行空白都併成一個空白）。"""
        if not self.條們:                    # 空文件也有一個空段落
            return []
        文件 = self.瀏覽.document()
        b, 結果 = 文件.begin(), []
        while b.isValid():
            結果.append(" ".join(b.text().replace("\u2028", " / ").split()))
            b = b.next()
        return 結果

    def _頂端插入(self, 內容html):
        文件 = self.瀏覽.document()
        c = QTextCursor(文件)
        c.beginEditBlock()
        if len(self.條們) > 1:
            c.insertBlock()
            c.movePosition(QTextCursor.Start)
        c.insertHtml(內容html)
        c.endEditBlock()

    def _移除最後一行(self):
        文件 = self.瀏覽.document()
        if 文件.blockCount() <= 1:
            return
        self.跟隨.補償 += int(文件.documentLayout().blockBoundingRect(文件.lastBlock()).height())
        c = QTextCursor(文件)
        c.movePosition(QTextCursor.End)
        c.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
        c.movePosition(QTextCursor.PreviousCharacter, QTextCursor.KeepAnchor)
        c.removeSelectedText()

    def 設方向(self, 置頂):
        super().設方向(置頂)
        self.跟隨.設方向(置頂)
        self._套上限()
        self._重排全部()
        self.跟隨.設方向(置頂)

    def _重排全部(self):
        self.瀏覽.setUpdatesEnabled(False)
        self.瀏覽.clear()
        舊 = list(self.條們)
        self.條們 = []
        for 行 in 舊:                          # 由舊到新重排：最新在下 = 一路加在底部；最新在上 = 一路加在頂部
            self.條們.append(行)
            if self.置頂:
                self._頂端插入(行)
            else:
                self.瀏覽.append(行)
        self.瀏覽.setUpdatesEnabled(True)

    def clear(self):
        self.瀏覽.clear()
        self.條們 = []
        self.條資料 = []
        self.總數 = 0
        self.頂.hide()


class 卡片清單(分頁基底):
    """分鐘摘要、話題摘要用：一張一張卡片，只留最近的 上限 張。「進行中」卡片永遠在「最新」的那一端。"""

    def __init__(self, 提示):
        self.捲 = QScrollArea()
        super().__init__(self.捲)
        self.捲.setWidgetResizable(True)
        self.捲.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        內 = QWidget()
        self.排版 = QVBoxLayout(內)
        self.排版.setContentsMargins(16, 16, 16, 16)
        self.排版.setSpacing(12)
        self.進行卡 = None      # 話題頁用：「進行中」的話題
        self.提示 = QLabel(提示)
        self.提示.setObjectName("淡")
        self.卡們 = []          # 已結束的卡片，最舊的在前
        self.捲.setWidget(內)
        self.跟隨 = 跟隨(self.捲.verticalScrollBar())
        self._排()

    def _排(self):
        """依方向把提示、卡片、進行中卡片重新擺進排版（最新在下：舊→新往下；最新在上：新→舊往下）。"""
        self.捲.setUpdatesEnabled(False)
        while self.排版.count():
            self.排版.takeAt(0)
        依序 = list(self.卡們) + ([self.進行卡] if self.進行卡 is not None else [])
        if self.置頂:
            依序.reverse()
        self.提示.setVisible(not 依序)
        for w in [self.提示] + 依序:
            self.排版.addWidget(w)
        self.排版.addStretch(1)
        self.捲.setUpdatesEnabled(True)

    def 加卡片(self, 內容html):
        """內容html：html 字串，或一個會產生 html 的函式（摘要卡片的時間會隨「直播時間／幾分鐘前」重畫）。"""
        產生 = 內容html if callable(內容html) else None
        卡 = QFrame()
        卡.setObjectName("卡片")
        版 = QVBoxLayout(卡)
        版.setContentsMargins(16, 12, 16, 12)
        字 = QLabel(產生() if 產生 else 內容html)
        卡.產生, 卡.字 = 產生, 字
        字.setWordWrap(True)
        字.setTextFormat(Qt.RichText)
        字.setTextInteractionFlags(Qt.TextSelectableByMouse)
        字.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        版.addWidget(字)
        self.卡們.append(卡)
        self.總數 += 1
        while len(self.卡們) > self.上限:       # 從最舊的一張開始移除
            舊 = self.卡們.pop(0)
            if self.置頂:
                self.跟隨.補償 += 舊.height() + self.排版.spacing()
            舊.hide()
            舊.deleteLater()
        self._排()
        self._超過了()

    def 設進行中(self, 時間字, 內容):
        """話題頁的「進行中」卡片：內容是目前話題的完整文字。"""
        if self.進行卡 is None:
            卡 = QFrame()
            卡.setObjectName("進行卡")
            版 = QVBoxLayout(卡)
            版.setContentsMargins(16, 12, 16, 12)
            版.setSpacing(6)
            頭 = QHBoxLayout()
            標 = QLabel("進行中")
            標.setObjectName("進行標")
            self.進行時間 = QLabel("")
            self.進行時間.setObjectName("淡")
            頭.addWidget(標)
            頭.addWidget(self.進行時間)
            頭.addStretch(1)
            self.進行字 = QLabel("")
            self.進行字.setWordWrap(True)
            self.進行字.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.進行字.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            版.addLayout(頭)
            版.addWidget(self.進行字)
            self.進行卡 = 卡
            self.進行時間.setText(時間字)
            self.進行字.setText(內容)
            self._排()
            return
        self.進行時間.setText(時間字)
        self.進行字.setText(內容)

    def 移除進行中(self):
        if self.進行卡 is not None:
            self.排版.removeWidget(self.進行卡)
            self.進行卡.hide()
            self.進行卡.deleteLater()
            self.進行卡 = None
            self._排()

    def 設方向(self, 置頂):
        super().設方向(置頂)
        self.跟隨.設方向(置頂)
        self._排()

    def 重畫時間(self):
        """重新產生每張卡片的 html（時間顯示換了、或「幾分鐘前」過了一分鐘）；只改有變的。
        看不到時先記著，等出現時（showEvent）才畫。"""
        if not self.isVisible():
            self._待重畫 = True
            return
        self._待重畫 = False
        for 卡 in self.卡們:
            if getattr(卡, "產生", None):
                新 = 卡.產生()
                if 卡.字.text() != 新:
                    卡.字.setText(新)

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_待重畫", False):
            self.重畫時間()

    def 清空(self):
        self.移除進行中()
        for 卡 in self.卡們:
            卡.hide()
            卡.deleteLater()
        self.卡們 = []
        self.總數 = 0
        self.頂.hide()
        self._排()


class 逐句頁(文字清單):
    """逐句翻譯：每則一行時間＋譯文（主），下面一行較小較淡的原文。原文模式只顯示原文，頂端註明目前模式。"""

    def __init__(self):
        super().__init__("逐句翻譯會在這裡出現（每則顯示時間、譯文、原文）")
        self.註 = QLabel("")
        self.註.setObjectName("淡")
        self.註.setWordWrap(True)
        self.註.setContentsMargins(16, 10, 16, 0)
        self.註.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.註.hide()
        self.layout().insertWidget(0, self.註)

    def _頂位置(self):
        return 1               # 提示列放在頂端的說明文字下面

    def 設註(self, 字):
        self.註.setText(字)
        self.註.setVisible(bool(字))

    def 加原文(self, 時間字, 原文):
        self.加一行(f'<span style="color:{淡字};">{跳脫(時間字)}</span>&nbsp;&nbsp;'
                  f'<span style="font-size:15px;">{跳脫(原文)}</span>')

    def 加譯文(self, 時間字, 原文, 譯文):
        頭 = f'<span style="color:{淡字};">{跳脫(時間字)}</span>&nbsp;&nbsp;'
        if 譯文:
            self.加一行(頭 + f'<span style="font-size:15px;">{跳脫(譯文)}</span><br>'
                      f'<span style="color:#6b7186; font-size:12px;">{跳脫(原文)}</span>')
        else:
            self.加一行(頭 + f'<span style="color:{淡字}; font-size:13px;">{跳脫(原文)}</span>&nbsp;&nbsp;'
                      f'<span style="color:{黃}; font-size:12px;">未翻譯</span>')


class 並排區(QWidget):
    """分頁區：1～3 欄，每欄自己一條分頁列，各自選要看哪個分頁。
    每個分頁同時只會出現在一欄：在這一欄選到別欄正在看的分頁，兩欄互換。
    頁面本身只有一份、不會被搬家或重建，所以每欄的自動捲動、往上捲不被拉回、「較早內容已存檔」都和單欄時一樣。
    視窗窄時自動減欄（窄於 1100 退成 1 欄、窄於 1600 最多 2 欄），寬了就回到使用者選的欄數。"""
    間距 = 12
    緊湊 = "QTabBar::tab { padding: 8px 8px; margin-right: 1px; font-size: 12px; }"

    def __init__(self, 頁名們, 頁們, 欄數, 欄頁們, 改了=None, 選到頁=None):
        super().__init__()
        self.頁名們 = list(頁名們)
        self.頁們 = dict(zip(頁名們, 頁們))
        self.欄數 = 欄數
        self.欄頁們 = list(欄頁們)
        self.改了, self.選到頁 = 改了, 選到頁
        self._同步中 = False
        self.窗格們 = []
        for _ in range(3):
            窗 = QFrame(self)
            窗.setObjectName("窗格")
            self.窗格們.append(窗)
        self.分頁列們 = []
        for c in range(3):
            列 = QTabBar(self)
            列.setExpanding(False)
            列.setDrawBase(False)
            列.setUsesScrollButtons(True)
            列.setElideMode(Qt.ElideNone)
            列.setFocusPolicy(Qt.NoFocus)
            for 名 in self.頁名們:
                列.addTab(名)
            列.currentChanged.connect(lambda i, c=c: self._點分頁(c, i))
            self.分頁列們.append(列)
        for 頁 in 頁們:
            頁.setParent(self)
        self.選擇器 = QFrame(self)
        self.選擇器.setObjectName("切換框")
        版 = QHBoxLayout(self.選擇器)
        版.setContentsMargins(8, 2, 3, 2)
        版.setSpacing(1)
        標 = QLabel("並排")
        標.setObjectName("小標")
        版.addWidget(標)
        self.欄鈕們 = []
        self.欄組 = QButtonGroup(self)
        for n in (1, 2, 3):
            鈕 = QPushButton(str(n))
            鈕.setToolTip(f"{n} 欄")
            鈕.setObjectName("並排鈕")
            鈕.setCheckable(True)
            鈕.setCursor(Qt.PointingHandCursor)
            鈕.setChecked(n == self.欄數)
            self.欄組.addButton(鈕, n)
            self.欄鈕們.append(鈕)
            版.addWidget(鈕)
        self.欄組.idClicked.connect(self.設欄數)
        self._同步分頁列()
        self.setMinimumHeight(120)

    # ---------- 狀態 ----------
    def 有效欄數(self):
        寬 = self.window().width()
        上限 = 1 if 寬 < 1100 else 2 if 寬 < 1600 else 3
        return min(self.欄數, 上限)

    def 設欄數(self, n):
        self.欄數 = n
        self._存()
        self.排()

    def 選頁(self, 欄, 名):
        舊 = self.欄頁們[欄]
        if 名 == 舊:
            return
        if 名 in self.欄頁們:                 # 別欄正在看：兩欄互換
            他 = self.欄頁們.index(名)
            self.欄頁們[他], self.欄頁們[欄] = 舊, 名
        else:
            self.欄頁們[欄] = 名
        self._同步分頁列()
        self._存()
        self.排()
        if self.選到頁:
            self.選到頁(名)

    def 設標題(self, 名, 字):
        i = self.頁名們.index(名)
        for 列 in self.分頁列們:
            列.setTabText(i, 字)
        self.排()

    def _存(self):
        if self.改了:
            self.改了(self.欄數, self.欄頁們)

    def _點分頁(self, 欄, i):
        if not self._同步中:
            self.選頁(欄, self.頁名們[i])

    def _同步分頁列(self):
        self._同步中 = True
        try:
            for c, 列 in enumerate(self.分頁列們):
                列.setCurrentIndex(self.頁名們.index(self.欄頁們[c]))
        finally:
            self._同步中 = False

    # ---------- 排版 ----------
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.排()

    def showEvent(self, e):
        super().showEvent(e)
        self.排()

    def 排(self):
        n = self.有效欄數()
        寬, 高 = self.width(), self.height()
        欄寬 = (寬 - self.間距 * (n - 1)) // n
        頭高 = self.分頁列們[0].sizeHint().height()
        右框 = self.選擇器
        選寬 = 右框.sizeHint().width()
        for 鈕, k in zip(self.欄鈕們, (1, 2, 3)):       # 窄到放不下的欄數用淡色表示（仍記著使用者的選擇）
            超過 = "true" if k > n else "false"
            if 鈕.property("超過") != 超過:
                鈕.setProperty("超過", 超過)
                鈕.style().unpolish(鈕)
                鈕.style().polish(鈕)
            鈕.setToolTip(f"視窗太窄，目前只顯示 {n} 欄（變寬就會自動回來）" if k > n else f"{k} 欄")
        顯示的 = set()
        for c in range(3):
            開 = c < n
            列, 窗 = self.分頁列們[c], self.窗格們[c]
            列.setVisible(開)
            窗.setVisible(開)
            if not 開:
                continue
            x = c * (欄寬 + self.間距)
            樣式 = self.緊湊 if n > 1 else ""
            if 列.styleSheet() != 樣式:
                列.setStyleSheet(樣式)
            列.setGeometry(x, 0, max(60, 欄寬 - ((選寬 + 8) if c == n - 1 else 0)), 頭高)
            窗.setGeometry(x, 頭高 - 1, 欄寬, max(10, 高 - 頭高 + 1))
            頁 = self.頁們[self.欄頁們[c]]
            頁.setGeometry(x + 1, 頭高, max(10, 欄寬 - 2), max(10, 高 - 頭高 - 1))
            頁.show()
            顯示的.add(頁)
        for 頁 in self.頁們.values():
            if 頁 not in 顯示的:
                頁.hide()
        選高 = 右框.sizeHint().height()
        右框.setGeometry((n - 1) * (欄寬 + self.間距) + 欄寬 - 選寬, (頭高 - 選高) // 2 - 1, 選寬, 選高)
        右框.raise_()


class 網址欄(QLineEdit):
    """直播網址輸入框：點一下（或用 Tab 移進來）就通知外面顯示網址紀錄。"""
    點到 = Signal()        # 使用者用滑鼠點了網址欄，或按了向下鍵（程式自動移焦點、Tab 都不算）
    按了Esc = Signal()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() == Qt.LeftButton:
            self.點到.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.按了Esc.emit()
        elif e.key() == Qt.Key_Down:
            self.點到.emit()
        super().keyPressEvent(e)


class 網址文字(QLabel):
    """清單裡的一筆網址：點一下發出訊號（用正式的 mousePressEvent 覆寫，不靠事後指定）。"""
    點到 = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.點到.emit()


class 網址清單(QFrame):
    """網址框下面的下拉清單（浮在視窗上，不佔版面）：釘選的在最上面，其後是最近用過的 10 個。
    每筆：★釘選、頻道名稱＋網址（點一下填入）、✕刪除。"""
    選了 = Signal(str)

    def __init__(self, 根, 紀錄, 網址框):
        super().__init__(根)
        self.根, self.紀錄, self.網址框 = 根, 紀錄, 網址框
        self.setObjectName("網址清單")
        外 = QVBoxLayout(self)
        外.setContentsMargins(4, 4, 4, 4)
        self.捲 = QScrollArea()
        self.捲.setWidgetResizable(True)
        self.捲.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        外.addWidget(self.捲)
        self.hide()
        網址框.點到.connect(self.顯示)
        網址框.按了Esc.connect(self.hide)
        網址框.textEdited.connect(lambda _: self.hide())

    def 顯示(self):
        if self.isVisible():
            return
        if not self.網址框.isEnabled() or not self.紀錄.清單():
            return
        self.重建()
        QApplication.instance().installEventFilter(self)
        self.show()
        self.raise_()

    def hideEvent(self, e):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(e)

    def eventFilter(self, 物, e):
        """點到清單和網址框以外的地方就收起來。"""
        if e.type() == QEvent.MouseButtonPress:
            w = QApplication.widgetAt(e.globalPosition().toPoint())
            if not (w and (w is self or self.isAncestorOf(w) or w is self.網址框)):
                self.hide()
        return False

    def 重建(self):
        內 = QWidget()
        版 = QVBoxLayout(內)
        版.setContentsMargins(4, 4, 4, 4)
        版.setSpacing(2)
        清單 = self.紀錄.清單()
        寬 = self.網址框.width()
        for 組名, 要釘 in (("已釘選", True), ("最近使用", False)):
            組 = [x for x in 清單 if x["釘選"] == 要釘]
            if not 組:
                continue
            標 = QLabel(組名)
            標.setObjectName("小標")
            標.setContentsMargins(6, 4, 0, 2)
            版.addWidget(標)
            for 項 in 組:
                版.addWidget(self._列(項, 寬 - 120))
        版.addStretch(1)
        self.捲.setWidget(內)
        self.setFixedWidth(寬)
        左上 = self.網址框.mapTo(self.根, QPoint(0, self.網址框.height() + 4))
        可用 = max(120, self.根.height() - 左上.y() - 20)
        內.adjustSize()
        self.setFixedHeight(min(內.sizeHint().height() + 12, 380, 可用))
        self.move(左上)

    def _列(self, 項, 文字寬):
        列 = QFrame()
        列.setObjectName("網址列")
        版 = QHBoxLayout(列)
        版.setContentsMargins(4, 3, 4, 3)
        版.setSpacing(4)
        釘 = QPushButton("★" if 項["釘選"] else "☆")
        釘.setObjectName("圖鈕")
        if 項["釘選"]:
            釘.setStyleSheet(f"color: {黃};")
        釘.setToolTip("取消釘選" if 項["釘選"] else "釘選（固定在最上方）")
        刪 = QPushButton("✕")
        刪.setObjectName("圖鈕")
        刪.setToolTip("從紀錄刪除")
        字 = 網址文字()
        字.setTextFormat(Qt.RichText)
        網址短 = QFontMetrics(self.font()).elidedText(項["網址"], Qt.ElideMiddle, max(100, 文字寬))
        字.setText(f'<b>{跳脫(ui_state.頻道名(項["網址"]))}</b><br>'
                  f'<span style="color:{淡字}; font-size:12px;">{跳脫(網址短)}</span>')
        字.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        字.setCursor(Qt.PointingHandCursor)
        字.點到.connect(lambda u=項["網址"]: self._選(u))
        for 鈕 in (釘, 刪):
            鈕.setFocusPolicy(Qt.NoFocus)
            鈕.setCursor(Qt.PointingHandCursor)
        釘.clicked.connect(lambda _=False, u=項["網址"], 要=not 項["釘選"]: self._釘(u, 要))
        刪.clicked.connect(lambda _=False, u=項["網址"]: self._刪(u))
        版.addWidget(釘)
        版.addWidget(字, 1)
        版.addWidget(刪)
        return 列

    def _選(self, 網址):
        """填入網址並立刻關閉清單；游標留在網址欄，但不會再把清單打開。"""
        self.hide()
        self.網址框.setText(網址)
        self.選了.emit(網址)

    def _釘(self, 網址, 要釘):
        self.紀錄.釘選(網址, 要釘)
        self._更新()

    def _刪(self, 網址):
        self.紀錄.刪除(網址)
        self._更新()

    def _更新(self):
        if self.紀錄.清單():
            self.重建()
        else:
            self.hide()


class 話題標(QLabel):
    """狀態列的「目前話題」：只顯示一行，太長用「…」截斷；點一下展開完整內容的小浮窗，再點一下（或點別處）收回。
    浮窗是主視窗裡的一個小元件（不是獨立的彈出視窗）：獨立的 Qt.Popup 會獨佔滑鼠，收不掉時整個主控台就像當掉。"""

    def __init__(self):
        super().__init__("")
        self.完整 = ""
        self.setStyleSheet("font-weight: 700;")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        self.setCursor(Qt.PointingHandCursor)
        self.浮窗 = QLabel("")
        self.浮窗.setObjectName("話題浮窗")
        self.浮窗.setWordWrap(True)
        self.浮窗.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.浮窗.setStyleSheet("font-weight: 400;")
        self.浮窗.hide()

    def setText(self, 字):
        self.完整 = str(字)
        self.setToolTip(self.完整)
        if self.浮窗.text() != self.完整:
            self.浮窗.setText(self.完整)
            if self.浮窗.isVisible():
                self._擺浮窗()
        self._截斷()

    def text(self):
        return self.完整

    def _截斷(self):
        寬 = max(10, self.width())
        super().setText(QFontMetrics(self.font()).elidedText(self.完整, Qt.ElideRight, 寬))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._截斷()
        if self.浮窗.isVisible():
            self._擺浮窗()

    def _擺浮窗(self):
        窗 = self.window()
        寬 = min(max(self.width(), 360), max(200, 窗.width() - 40))
        self.浮窗.setFixedWidth(寬)
        self.浮窗.setFixedHeight(self.浮窗.heightForWidth(寬) if self.浮窗.hasHeightForWidth() else self.浮窗.sizeHint().height())
        位置 = 窗.mapFromGlobal(self.mapToGlobal(QPoint(0, self.height() + 4)))
        self.浮窗.move(max(10, min(位置.x(), 窗.width() - 寬 - 10)), 位置.y())
        self.浮窗.raise_()

    def _展開(self):
        if self.浮窗.parent() is not self.window():
            self.浮窗.setParent(self.window())
        self._擺浮窗()
        self.浮窗.show()
        self.浮窗.raise_()
        QApplication.instance().installEventFilter(self)

    def _收起(self):
        self.浮窗.hide()
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, 物, e):
        """展開時點到「目前話題」和浮窗以外的地方就收起來。"""
        if e.type() == QEvent.MouseButtonPress:
            w = QApplication.widgetAt(e.globalPosition().toPoint())
            if not (w and (w is self or w is self.浮窗 or self.浮窗.isAncestorOf(w))):
                self._收起()
        return False

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        self._收起() if self.浮窗.isVisible() else self._展開()


class 狀態列(QWidget):
    """燈＋目前話題（一行）＋小標籤。放得下就全在同一行；窄了標籤自動換到下一行，高度跟著算好後固定，不會被撐高或截斷。"""
    間距 = 8

    def __init__(self, 燈, 話題, 標籤們):
        super().__init__()
        self.燈, self.話題, self.標籤們 = 燈, 話題, 標籤們
        for w in (燈, 話題, *標籤們):
            w.setParent(self)
        for w in 標籤們:
            w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._排(600)

    def minimumSizeHint(self):
        return QSize(200, self.height())

    def sizeHint(self):
        return QSize(400, self.height())

    def 重排(self):
        self._排(self.width())

    def resizeEvent(self, e):
        self._排(e.size().width())

    def _排(self, 寬):
        間 = self.間距
        標籤們 = [w for w in self.標籤們 if not w.isHidden()]       # 隱藏的標籤（語言藥丸、重新偵測鈕）不佔位置
        燈寬 = self.燈.sizeHint().width()
        列高 = max(self.話題.sizeHint().height(), self.燈.sizeHint().height(), *(w.sizeHint().height() for w in 標籤們))
        標籤寬 = [w.sizeHint().width() for w in 標籤們]
        總標籤 = sum(標籤寬) + 間 * (len(標籤寬) - 1)
        話題最小 = 180

        def 放(w, x, y, 寬度=None):
            w.setGeometry(x, y + (列高 - w.sizeHint().height()) // 2, 寬度 or w.sizeHint().width(), w.sizeHint().height())

        if 燈寬 + 間 + 話題最小 + 間 + 總標籤 <= 寬:             # 全部同一行
            放(self.燈, 0, 0)
            x = 寬 - 總標籤
            放(self.話題, 燈寬 + 間, 0, x - 間 - 燈寬 - 間)
            for w, 寬度 in zip(標籤們, 標籤寬):
                放(w, x, 0)
                x += 寬度 + 間
            列數 = 1
        else:                                                  # 話題一行，標籤換到下面（放不下再往下換行）
            放(self.燈, 0, 0)
            放(self.話題, 燈寬 + 間, 0, max(10, 寬 - 燈寬 - 間))
            x, 列 = 0, 1
            for w, 寬度 in zip(標籤們, 標籤寬):
                if x > 0 and x + 寬度 > 寬:
                    x, 列 = 0, 列 + 1
                放(w, x, 列 * (列高 + 4))
                x += 寬度 + 間
            列數 = 列 + 1
        高 = 列數 * 列高 + (列數 - 1) * 4
        if self.height() != 高:
            self.setFixedHeight(高)


class 提示層(QWidget):
    """可關閉的小提示條，浮在視窗底部（不佔版面、不會把別的區塊擠變形）。
    同一則訊息不重複堆疊（再來一次只重新計時），幾秒後自動消失，也可按 ✕ 關掉。"""
    最多 = 3

    def __init__(self, 根):
        super().__init__(根)
        self.根 = 根
        self.版 = QVBoxLayout(self)
        self.版.setContentsMargins(0, 0, 0, 0)
        self.版.setSpacing(6)
        self.條們 = {}          # 訊息文字 -> (條, 計時器)
        根.installEventFilter(self)
        self.hide()

    def eventFilter(self, 物, e):
        if 物 is self.根 and e.type() == QEvent.Resize:
            self.擺放()
        return False

    def 擺放(self):
        寬 = max(200, min(self.根.width() - 40, 720))
        self.setFixedWidth(寬)
        self.版.activate()
        self.setFixedHeight(max(1, self.版.heightForWidth(寬)))
        self.move(20, self.根.height() - self.height() - 14)
        self.raise_()

    def 顯示(self, 字, 錯誤=False, 秒=8):
        字 = 字.strip()
        if not 字:
            return
        if 字 in self.條們:
            self.條們[字][1].start(int(秒 * 1000))
            self.擺放()
            return
        while len(self.條們) >= self.最多:
            self.移除(next(iter(self.條們)))
        條 = QFrame()
        條.setObjectName("提示條")
        條.setProperty("錯誤", 錯誤)
        版 = QHBoxLayout(條)
        版.setContentsMargins(14, 8, 8, 8)
        標 = QLabel(字)
        標.setWordWrap(True)
        標.setTextInteractionFlags(Qt.TextSelectableByMouse)
        標.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        鈕 = QPushButton("✕")
        鈕.setObjectName("關閉")
        鈕.setCursor(Qt.PointingHandCursor)
        鈕.setToolTip("關閉")
        鈕.clicked.connect(lambda: self.移除(字))
        版.addWidget(標, 1)
        版.addWidget(鈕, 0, Qt.AlignTop)
        計 = QTimer(條)
        計.setSingleShot(True)
        計.timeout.connect(lambda: self.移除(字))
        計.start(int(秒 * 1000))
        self.條們[字] = (條, 計)
        self.版.addWidget(條)
        self.show()
        self.擺放()

    def 移除(self, 字):
        項 = self.條們.pop(字, None)
        if 項:
            項[0].hide()
            項[0].deleteLater()
        if not self.條們:
            self.hide()
        else:
            QTimer.singleShot(0, self.擺放)


def 時間標(字):
    return (f'<span style="background:#2e2752; color:#c4b5ff; font-weight:700;">'
            f'&nbsp;{跳脫(字)}&nbsp;</span>')


class 主控台(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("直播摘要 主控台")
        self.resize(1080, 760)
        self.setMinimumSize(640, 520)
        self.執行緒 = None
        self.要關閉 = False
        self.要結束 = False        # True = 真的結束程式（膠囊或系統匣的「結束程式」）；False = 關主控台只是收起來
        self.結束中 = False
        self.本次段位 = None       # 啟動面板選的字幕速度段位（只用在下一次開始；None = 用 config.json）
        self.語言狀態 = language_state.語言狀態()
        self._待記網址 = None
        self.本場設定 = None
        self.本場檔案 = []
        self.設定框 = None
        self.名詞清單框 = None
        self.引導 = None

        # 逐句字幕（翻譯）：只有逐句翻譯面板開著時才產生（見 panel.面板管理.要翻譯）
        self.字幕器 = subtitle.字幕器()
        events.接收者們.append(self.字幕器.接收)
        # 聊天室翻譯：設定開著、聊天室面板開著、外語直播才翻（見 chat_translate.py）；膠囊選單可當場開關
        self.聊天翻譯器 = chat_translate.聊天翻譯器()
        self.聊天翻譯器.開啟 = bool(config.目前設定()["chat_translate"])
        events.接收者們.append(self.聊天翻譯器.接收)
        # 摘要卡片的時間：stream 直播時間、ago 幾分鐘前（設定框與膠囊選單都能切，當場生效）
        self.時間顯示 = config.目前設定()["time_display"]
        self.直播資訊 = None          # 這一場的 stream_info 事件（開播時間、直播主、標題、分類）；文字稿模式是 None
        self._時間分 = None
        self.時間計時 = QTimer(self, interval=5000, timeout=self._檢查分鐘)   # 「幾分鐘前」：分鐘數變了才重畫
        self.時間計時.start()

        self.橋 = 事件橋()
        self.橋.收到.connect(self.處理事件)
        self.橋.結束.connect(self.跑完了)
        events.接收者們.append(self.橋.接收)

        根 = QWidget()
        根.setObjectName("根")
        self.setCentralWidget(根)
        總 = QVBoxLayout(根)
        總.setContentsMargins(20, 18, 20, 20)
        總.setSpacing(14)
        總.addWidget(self._做控制區())
        總.addWidget(self._做狀態區())
        總.addWidget(self._做分頁(), 1)       # 只有分頁區吃剩下的空間，上面各區高度固定
        self.提示層 = 提示層(根)
        self._接全螢幕()
        self.網址紀錄 = ui_state.網址紀錄()
        self.網址清單 = 網址清單(根, self.網址紀錄, self.網址框)
        self._待記網址 = None
        self.面板 = panel.面板管理(self)        # 面板和分頁接同一條事件
        self.膠囊 = capsule.膠囊管理(self)       # 浮動膠囊與系統匣（在 main 裡和啟動面板一起顯示）
        self.啟動面板 = launcher.啟動面板(self, 網址欄, 網址清單)
        self.套用開發者選項()
        self._切換來源()

    # ---------- 版面 ----------
    def _做控制區(self):
        框 = QFrame()
        框.setObjectName("面板")
        框.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        版 = QVBoxLayout(框)
        版.setContentsMargins(18, 16, 18, 16)
        版.setSpacing(12)
        self.控制版 = 版

        第一列 = QHBoxLayout()
        self.第一列 = 第一列
        標題 = QLabel("直播摘要")
        標題.setObjectName("標題")
        第一列.addWidget(標題)
        self.收合鈕 = QPushButton("▾ 收合網址與語言")
        self.收合鈕.setObjectName("小鈕")
        self.收合鈕.setCursor(Qt.PointingHandCursor)
        self.收合鈕.clicked.connect(lambda: self.收合設定(not self.已收合))
        self.已收合 = False
        第一列.addWidget(self.收合鈕)
        第一列.addStretch(1)
        切換框 = QFrame()
        切換框.setObjectName("切換框")
        切 = QHBoxLayout(切換框)
        切.setContentsMargins(3, 3, 3, 3)
        切.setSpacing(2)
        self.直播鈕 = QPushButton("直播網址")
        self.檔案鈕 = QPushButton("文字稿檔案")
        self.來源組 = QButtonGroup(self)
        for 鈕 in (self.直播鈕, self.檔案鈕):
            鈕.setObjectName("切換")
            鈕.setCheckable(True)
            鈕.setCursor(Qt.PointingHandCursor)
            self.來源組.addButton(鈕)
            切.addWidget(鈕)
        self.直播鈕.setChecked(True)
        self.來源組.buttonClicked.connect(lambda _: self._切換來源())
        第一列.addWidget(切換框)
        self.切換框 = 切換框
        版.addLayout(第一列)

        self.網址區 = QWidget()
        第二列 = QHBoxLayout(self.網址區)
        第二列.setContentsMargins(0, 0, 0, 0)
        第二列.setSpacing(8)
        self.網址框 = 網址欄()
        self.網址框.setPlaceholderText("https://www.twitch.tv/頻道名稱")
        self.檔案框 = QLineEdit()
        self.檔案框.setPlaceholderText("選一個文字稿 .txt 檔（每行 [mm:ss] 文字）")
        self.瀏覽鈕 = QPushButton("瀏覽…")
        self.瀏覽鈕.clicked.connect(self._選檔案)
        第二列.addWidget(self.網址框, 1)
        第二列.addWidget(self.檔案框, 1)
        第二列.addWidget(self.瀏覽鈕)
        版.addWidget(self.網址區)

        self.第三區 = QWidget()
        第三列 = QHBoxLayout(self.第三區)
        第三列.setContentsMargins(0, 0, 0, 0)
        第三列.setSpacing(8)
        self.第三列 = 第三列
        self.速度標 = QLabel("重播速度")
        self.速度標.setObjectName("淡")
        self.速度選 = QComboBox()
        for 名, 值 in 速度選項:
            self.速度選.addItem(名, 值)
        語言標 = QLabel("語言")
        語言標.setObjectName("淡")
        self.語言選 = QComboBox()
        for 名, 值 in 語言選項:
            self.語言選.addItem(名, 值)
        設定 = config.目前設定()       # 預設選 config.json 的語言
        self.語言選.setCurrentIndex(max(0, [v for _, v in 語言選項].index(設定["language"])))
        self.開始鈕 = QPushButton("開始")
        self.開始鈕.setObjectName("開始")
        self.停止鈕 = QPushButton("停止")
        self.停止鈕.setObjectName("停止")
        self.停止鈕.setEnabled(False)
        for 鈕 in (self.開始鈕, self.停止鈕):
            鈕.setCursor(Qt.PointingHandCursor)
            鈕.setMinimumWidth(88)
        self.開始鈕.clicked.connect(self.開始)
        self.停止鈕.clicked.connect(self.停止)
        self.語言區 = QWidget()
        語言版 = QHBoxLayout(self.語言區)
        語言版.setContentsMargins(0, 0, 0, 0)
        語言版.setSpacing(8)
        for w in (self.速度標, self.速度選, 語言標, self.語言選):
            語言版.addWidget(w)
        第三列.addWidget(self.語言區)
        第三列.addStretch(1)
        # 開始／停止放在一個小容器裡：展開時在最下面一列，收合時搬到標題列同一行
        self.按鈕區 = QWidget()
        按鈕版 = QHBoxLayout(self.按鈕區)
        按鈕版.setContentsMargins(0, 0, 0, 0)
        按鈕版.setSpacing(8)
        for 鈕 in (self.開始鈕, self.停止鈕):
            按鈕版.addWidget(鈕)
        第三列.addWidget(self.按鈕區)
        版.addWidget(self.第三區)
        self.控制框 = 框
        return 框

    def _做狀態區(self):
        框 = QFrame()
        框.setObjectName("面板")
        框.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        版 = QVBoxLayout(框)
        版.setContentsMargins(14, 8, 14, 8)

        self.燈 = QLabel("●")
        self.燈.setStyleSheet(f"color: {淡字}; font-size: 14px;")
        self.話題字 = 話題標()
        self.話題字.setText("尚未開始")
        self.時間藥丸 = QLabel("直播時間 --:--")
        self.轉錄藥丸 = QLabel("轉錄：等待中")
        self.費用藥丸 = QLabel("呼叫 0 次 · 估算 $0.000")
        self.費用藥丸.setToolTip("摘要的呼叫次數與費用（金額為估算，實際以 API 帳單為準）")
        self.翻譯藥丸 = QLabel("翻譯 0 次 · $0.000")
        self.翻譯藥丸.setToolTip("逐句字幕翻譯的呼叫次數與估算費用（和摘要分開算；金額為估算，實際以 API 帳單為準）")
        self.聊天翻譯藥丸 = QLabel("聊天翻譯 0 次 · $0.000")
        self.聊天翻譯藥丸.setToolTip("聊天室翻譯的呼叫次數與估算費用（和摘要、逐句翻譯分開算；金額為估算，實際以 API 帳單為準）")
        self.語言藥丸 = QLabel("")            # 目前語言；放在狀態列，一眼看得到
        self.語言藥丸.setToolTip("目前使用的語言。自動偵測可能判錯，按「重新偵測」或在設定裡手動選語言。")
        self.重偵鈕 = QPushButton("重新偵測")
        self.重偵鈕.setToolTip("不中斷直播，用下一段有人聲的音訊重新判斷語言（只有語言設為自動時可用）")
        self.重偵鈕.setCursor(Qt.PointingHandCursor)
        self.重偵鈕.setFocusPolicy(Qt.NoFocus)
        self.重偵鈕.clicked.connect(self.重新偵測語言)
        藥丸們 = (self.時間藥丸, self.轉錄藥丸, self.費用藥丸, self.翻譯藥丸, self.聊天翻譯藥丸, self.語言藥丸, self.重偵鈕)
        for w in 藥丸們[:6]:
            w.setObjectName("藥丸")
        self.聊天翻譯藥丸.setVisible(self.聊天翻譯器.開啟)
        self.語言藥丸.hide()
        self.重偵鈕.hide()
        self.狀態列 = 狀態列(self.燈, self.話題字, 藥丸們)
        版.addWidget(self.狀態列)
        self.狀態框 = 框
        return 框

    def _設藥丸(self, 標, 字):
        標.setText(字)
        self.狀態列.重排()

    def 更新語言顯示(self):
        """依語言狀態更新狀態列的語言藥丸與重新偵測鈕（有警示時藥丸變黃色）。"""
        s = self.語言狀態
        self.語言藥丸.setText(s.文字())
        self.語言藥丸.setStyleSheet(f"color: {黃};" if s.有警示() else "")
        self.語言藥丸.setVisible(s.顯示中())
        self.重偵鈕.setVisible(s.顯示按鈕())
        self.重偵鈕.setEnabled(s.可重新偵測())
        self.狀態列.重排()

    def 重新偵測語言(self):
        """不停止串流：通知引擎下一段有人聲的音訊重新判斷語言。"""
        if not self.執行中() or not self.語言狀態.要求重新偵測():
            return
        events.重新偵測.set()
        self.更新語言顯示()
        self._訊息("重新偵測語言：下一段有人聲的音訊會重新判斷。")

    def _做分頁(self):
        self.分鐘頁 = 卡片清單("分鐘摘要會在這裡出現（每檢查一次一則，最新在最下面）")
        self.話題頁 = 卡片清單("每個話題結束時，話題摘要會在這裡出現")
        self.稿頁 = 文字清單("逐句轉錄的直播稿會在這裡出現")
        self.翻譯頁 = 逐句頁()
        self.聊天頁 = 文字清單("聊天室留言會在這裡出現（只有直播網址模式會抓聊天室）")
        self.分頁名 = ["分鐘摘要", "話題摘要", "直播稿", "逐句翻譯", "聊天室"]       # 有計數的分頁（設定在獨立的設定框）
        頁們 = [self.分鐘頁, self.話題頁, self.稿頁, self.翻譯頁, self.聊天頁]
        欄數, 欄頁們 = ui_state.讀介面設定(self.分頁名)
        self.計數 = dict.fromkeys(self.分頁名, 0)
        self.並排 = 並排區(self.分頁名, 頁們, 欄數, 欄頁們, 改了=ui_state.存介面設定)
        self.設方向(config.目前設定()["newest_on_top"])
        return self.並排

    def _切換來源(self):
        直播 = self.直播鈕.isChecked()
        if hasattr(self, "網址清單"):
            self.網址清單.hide()
        self.網址框.setVisible(直播)
        self.檔案框.setVisible(not 直播)
        self.瀏覽鈕.setVisible(not 直播)
        self.速度標.setVisible(not 直播)
        self.速度選.setVisible(not 直播)

    def _選檔案(self):
        路徑, _ = QFileDialog.getOpenFileName(self, "選擇文字稿", 專案目錄, "文字稿 (*.txt);;所有檔案 (*)")
        if 路徑:
            self.檔案框.setText(路徑)

    # ---------- 全螢幕 ----------
    def _接全螢幕(self):
        全 = QShortcut(QKeySequence("F11"), self)
        全.setContext(Qt.WindowShortcut)
        全.activated.connect(self.切換全螢幕)

    def 切換全螢幕(self):
        if self.isFullScreen():
            self.showMaximized() if self._全螢幕前最大化 else self.showNormal()
        else:
            self._全螢幕前最大化 = self.isMaximized()
            self.showFullScreen()

    _全螢幕前最大化 = False

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.isFullScreen():
            self.切換全螢幕()
            return
        super().keyPressEvent(e)

    def 設方向(self, 置頂):
        """最新內容顯示在最上面（True）或最下面（False）：五個內容分頁一起換，立即重新排列。"""
        for 頁 in (self.分鐘頁, self.話題頁, self.稿頁, self.翻譯頁, self.聊天頁):
            頁.設方向(bool(置頂))
        if hasattr(self, "面板"):
            self.面板.設方向(置頂)

    def 做面板頁(self, 種類):
        """面板用：做一個和主控台分頁同一種的新清單頁。"""
        if 種類 == "分鐘摘要":
            return 卡片清單("分鐘摘要會在這裡出現")
        if 種類 == "話題摘要":
            return 卡片清單("每個話題結束時，話題摘要會在這裡出現")
        if 種類 == "逐句翻譯":
            return 逐句頁()
        if 種類 == "直播稿":
            return 文字清單("逐句轉錄的直播稿會在這裡出現")
        return 文字清單("聊天室留言會在這裡出現（只有直播網址模式會抓聊天室）")

    def _加計數(self, 名):
        self.計數[名] += 1
        self.並排.設標題(名, f"{名}  {self.計數[名]}")

    # ---------- 開始 / 停止 ----------
    def 開始(self):
        按下時間 = time.time()
        直播 = self.直播鈕.isChecked()
        網址 = self.網址框.text().strip() if 直播 else None
        檔案 = self.檔案框.text().strip().strip('"') if not 直播 else None
        self.網址清單.hide()
        if 直播 and not 網址:
            return self._錯誤框("請先輸入直播網址，例如 https://www.twitch.tv/頻道名稱")
        if 直播 and "/videos/" in 網址.lower():
            return self._錯誤框(launcher.VOD提示)
        if 直播 and (擋 := launcher.YouTube不支援(網址)):
            return self._錯誤框(擋)
        if not 直播 and not os.path.isfile(檔案 or ""):
            return self._錯誤框("找不到這個文字稿檔案，請重新選擇。")

        # 每次開始都重新讀 config.json；介面上的語言只覆蓋這一場，不寫回 config.json
        # 啟動面板選的字幕速度段位也只覆蓋這一場（記住的預設在設定框）
        覆蓋 = {"language": self.語言選.currentData()}
        if self.本次段位:
            覆蓋["subtitle_speed"], self.本次段位 = self.本次段位, None
        設定, _, 警告們, 問題們 = config.載入設定詳細(覆蓋)
        段位 = subtitle_speed.取得(設定["subtitle_speed"])
        llm.套用設定(設定)

        for 頁, 鍵 in ((self.分鐘頁, "ui_max_summary"), (self.話題頁, "ui_max_summary"),
                      (self.稿頁, "ui_max_transcript"), (self.翻譯頁, "ui_max_translation"),
                      (self.聊天頁, "ui_max_chat")):
            頁.設上限(設定[鍵])
            頁.設檔案(None)
        for 頁 in (self.分鐘頁, self.話題頁):
            頁.清空()
        for 頁 in (self.稿頁, self.翻譯頁, self.聊天頁):
            頁.clear()
        self.計數 = dict.fromkeys(self.分頁名, 0)
        for 名 in self.分頁名:
            self.並排.設標題(名, 名)
        self.話題字.setText("準備中…")
        self.直播資訊 = None
        self._時間分 = None
        self.時間藥丸.setStyleSheet("")
        self.時間藥丸.setToolTip("")
        self._設藥丸(self.時間藥丸, "直播時間 --:--")
        self._設藥丸(self.轉錄藥丸, "轉錄：文字稿模式" if not 直播 else "轉錄：等待中")
        self.轉錄藥丸.setStyleSheet("")
        self._設藥丸(self.費用藥丸, "呼叫 0 次 · 估算 $0.000")
        self._設藥丸(self.翻譯藥丸, "翻譯 0 次 · $0.000")
        self._設藥丸(self.聊天翻譯藥丸, "聊天翻譯 0 次 · $0.000")
        self.結束中 = False
        self.語言狀態.開始(設定["language"], 直播)
        events.重新偵測.clear()
        self.更新語言顯示()
        單價 = model_catalog.單價(設定) or (None, None)          # 查不到就是未知，不沿用舊單價
        self.字幕器.開始(設定["subtitle_mode"], 設定["language"], 設定["model"],
                      單價[0], 單價[1],
                      段位["批次秒"], 段位["批次句"])
        self.字幕器.啟用 = self.面板.要翻譯()     # 只有逐句翻譯面板開著才翻譯（省費用）
        self.聊天翻譯器.開始(設定["chat_translate"], 設定["language"], 設定["model"],
                        單價[0], 單價[1], 設定["chat_translate_max_per_min"])
        self.聊天翻譯器.面板開著 = self.面板.聊天面板開著()
        self._更新聊天藥丸()
        startup_timeline.開始({
            "來源": "直播網址" if 直播 else "文字稿重播", "語言設定": 設定["language"], "字幕模式": 設定["subtitle_mode"],
            "摘要模型": 設定["model"], "轉錄模型": 設定["whisper_model"],
            **subtitle_speed.里程碑說明(設定["subtitle_speed"]),
        }, 起點=按下時間)
        self.面板.開始(設定, 直播)
        self.本場設定, self.本場檔案 = 設定, []
        self._待記網址 = 網址           # 成功開始擷取（收到 files 事件）才寫進網址紀錄
        self._更新翻譯註()
        self._訊息("　".join("警告：" + w for w in 警告們) or ("正在檢查直播…" if 直播 else "開始重播文字稿…"))
        if 問題們:                       # 設定檔的警告：主控台常收著，膠囊旁也顯示（白話，不出現檔名與欄位名）
            self.膠囊.錯誤提示(config.介面警告字(問題們))
        self._設燈(綠)

        events.停止.clear()
        self.開始鈕.setEnabled(False)
        self.停止鈕.setEnabled(True)
        self.停止鈕.setText("停止")
        for w in (self.網址框, self.檔案框, self.瀏覽鈕, self.速度選, self.語言選, self.直播鈕, self.檔案鈕):
            w.setEnabled(False)
        self.收合設定(True)              # 開始後收起網址與語言，摘要區變大
        for 頁 in self.設定頁們():
            頁.設執行中(True)

        速度 = self.速度選.currentData()

        def 跑():
            try:
                live_topics.執行(設定, 檔案=檔案, 網址=網址, speed=速度)
            except Exception as e:      # 沒料到的錯誤也只顯示對話框，不讓程式閃退
                events.送出("error", 訊息=f"發生未預期的錯誤：{type(e).__name__}：{e}")
            finally:
                self.橋.結束.emit()

        self.執行緒 = threading.Thread(target=跑, daemon=True)
        self.執行緒.start()

    def 停止(self):
        """等同 Ctrl+C：引擎會整理最後一個話題、關掉音訊擷取與聊天室。"""
        if self.結束中:
            return
        self.結束中 = True
        self.停止鈕.setEnabled(False)
        self._設燈(黃)
        if self.字幕器.有待翻():       # 先把還沒翻的句子翻完（最多等 10 秒），再整理最後一個話題
            self.停止鈕.setText(翻譯收尾文字)
            self._訊息(翻譯收尾文字)
            self.字幕器.收尾()
            self._收尾開始 = time.time()
            self._收尾計時 = QTimer(self)
            self._收尾計時.timeout.connect(self._看收尾)
            self._收尾計時.start(100)
        else:
            self._進入整理()

    def _看收尾(self):
        if self.字幕器.收尾完成.is_set() or time.time() - self._收尾開始 >= 翻譯收尾最多秒:
            self._收尾計時.stop()
            self._進入整理()

    def _進入整理(self):
        """翻譯收尾完成（或超時放棄）後，才通知引擎整理最後一個話題。"""
        events.停止.set()
        self.字幕器.結束()          # 超時沒翻完的句子就放棄（不重送）
        self.聊天翻譯器.結束()      # 聊天室翻譯不收尾：還沒翻的留言只顯示原文
        self.停止鈕.setText(結束中文字)
        self._訊息(結束中文字 + "（同時關閉音訊擷取與聊天室）")

    def 跑完了(self):
        self.執行緒 = None
        self.結束中 = False
        self.語言狀態.結束()
        self.更新語言顯示()
        if getattr(self, "_收尾計時", None):
            self._收尾計時.stop()
        self.字幕器.結束()
        self.聊天翻譯器.結束()
        for 頁 in self.設定頁們():
            頁.設執行中(False)
        self.開始鈕.setEnabled(True)
        self.停止鈕.setEnabled(False)
        self.停止鈕.setText("停止")
        for w in (self.網址框, self.檔案框, self.瀏覽鈕, self.速度選, self.語言選, self.直播鈕, self.檔案鈕):
            w.setEnabled(True)
        self._設燈(淡字)
        if self.要關閉:
            self.close()

    def closeEvent(self, e):
        if not self.要結束:              # 關主控台只是收起來（膠囊、系統匣、擷取都照常）；結束程式要用膠囊或系統匣
            e.ignore()
            self.網址清單.hide()
            self.hide()
            if not ui_state.讀旗標("主控台收起提示過"):
                ui_state.存旗標("主控台收起提示過")
                self.膠囊.小提示("主控台已收起，可從膠囊選單重新打開", 秒=6)
            return
        if self.執行緒 and self.執行緒.is_alive():   # 還在跑：先乾淨結束，完成後自動關窗
            self.要關閉 = True
            self.停止()
            self._訊息("正在結束，完成後視窗會自動關閉…")
            e.ignore()
            return
        events.接收者們.remove(self.橋.接收) if self.橋.接收 in events.接收者們 else None
        self.面板.全部收掉()
        self.膠囊.收掉()
        self.啟動面板.close()
        if self.引導:
            self.引導.hide()             # 只是收起，不算「看過」
        if self.設定框:
            self.設定框.close()
        if self.名詞清單框:
            self.名詞清單框.close()
        e.accept()
        QApplication.quit()              # 主控台常常是隱藏的，不靠「最後一個視窗關閉」來結束

    # ---------- 設定框（齒輪、膠囊選單「設定」）----------
    def 設定頁們(self):
        return [self.設定框.頁] if self.設定框 else []

    def 開設定框(self, 捲到金鑰=False):
        """獨立的設定視窗（設定只在這裡；主控台沒有設定分頁）。捲到金鑰：啟動面板「設定金鑰」用。"""
        if self.設定框 is None:
            self.設定框 = settings_page.設定框(self)
        self.設定框.打開(self.膠囊.膠囊._所在螢幕(), 捲到金鑰=bool(捲到金鑰))

    # ---------- 首次引導（開程式、膠囊／系統匣選單「使用說明」）----------
    def 開程式(self):
        """開程式時：出現浮動膠囊；還沒看過引導就打開引導（關掉後才出現啟動面板），看過就直接出現啟動面板。"""
        self.膠囊.顯示()
        if onboarding.要自動出現():
            self.開引導()
        else:
            self.啟動面板.顯示()

    def 開引導(self):
        if self.引導 is None:
            self.引導 = onboarding.首次引導(self)
            self.引導.關閉了.connect(self._引導關了)
        self.引導.顯示(self.膠囊.膠囊._所在螢幕())

    def _引導關了(self):
        """看完或跳過：沒在直播就打開啟動面板（直播中 啟動面板.顯示 本來就不會打開）。"""
        if not self.要結束:
            self.啟動面板.顯示()

    # ---------- 開發者選項（設定框最下面）----------
    def 顯示文字稿模式(self):
        return ui_state.讀旗標(settings_page.文字稿旗標)

    def 套用開發者選項(self):
        """「文字稿」來源只給開發測試用：預設隱藏，設定框的開發者選項勾選後才出現（命令列的文字稿模式不受影響）。"""
        顯示 = self.顯示文字稿模式()
        self.檔案鈕.setVisible(顯示)
        if not 顯示 and self.檔案鈕.isChecked() and not self.執行中():
            self.直播鈕.setChecked(True)
            self._切換來源()

    # ---------- 名詞清單（膠囊選單、啟動面板的按鈕）----------
    def 名詞清單目標(self):
        """回傳 (直播主, 這一場的詞庫物件或 None, 停用原因)。停用原因是空字串＝可以打開。
        直播中：這一場的頻道（引擎載入詞庫後就用它那一個物件）；文字稿重播沒有直播主 → 停用。
        待命：啟動面板網址欄的頻道；不是有效的 Twitch／YouTube 網址、YouTube 頻道查詢中或查不到 → 停用。"""
        if self.執行中():
            if glossary.本場詞庫 is not None:
                return glossary.本場詞庫.直播主, glossary.本場詞庫, ""
            if not self.直播鈕.isChecked():
                return None, None, "文字稿重播沒有指定直播主"
            名, 原因 = names_page.頻道(self.網址框.text())
            return 名, None, 原因
        名, 原因 = names_page.頻道(self.啟動面板.網址框.text())
        return 名, None, 原因

    def 開名詞清單(self):
        名, 本場, 原因 = self.名詞清單目標()
        if 原因:
            self.膠囊.小提示("名詞清單：" + 原因, 秒=6, 錯誤=True)
            return
        詞庫 = 本場 or glossary.詞庫(glossary.檔名安全(名), 標示=names_page.詞庫標示(名))
        if self.名詞清單框 is None:
            self.名詞清單框 = names_page.名詞清單框()
        elif 本場 is None and self.名詞清單框.詞庫 is not None and self.名詞清單框.詞庫.路徑 == 詞庫.路徑:
            詞庫 = self.名詞清單框.詞庫          # 同一位直播主、視窗已經開過：沿用（保留這一場的出現紀錄）
        self.名詞清單框.打開(詞庫, 本場=本場 is not None, 螢幕範圍=self.膠囊.膠囊._所在螢幕())

    # ---------- 狀態 ----------
    def 執行中(self):
        return bool(self.執行緒 and self.執行緒.is_alive())

    # ---------- 收合、訊息 ----------
    def 收合設定(self, 收):
        self.已收合 = 收
        self.網址清單.hide()
        for w in (self.網址區, self.語言區, self.切換框):
            w.setVisible(not 收)
        # 收合：字幕／開始／停止搬到標題列同一行，下面整列不佔空間；展開：搬回最下面一列
        if 收:
            self.第三區.hide()
            self.第一列.addWidget(self.按鈕區)
            self.控制版.setContentsMargins(14, 8, 14, 8)
            self.控制版.setSpacing(0)
        else:
            self.第三列.addWidget(self.按鈕區)
            self.第三區.show()
            self.控制版.setContentsMargins(18, 16, 18, 16)
            self.控制版.setSpacing(12)
            self._切換來源()
        for 鈕 in (self.開始鈕, self.停止鈕, self.收合鈕):
            鈕.setFixedHeight(30) if 收 else (鈕.setMinimumHeight(0), 鈕.setMaximumHeight(16777215))
        self.收合鈕.setText("▸ 展開網址與語言" if 收 else "▾ 收合網址與語言")

    def _訊息(self, 字, 錯誤=False, 秒=8):
        """提示與錯誤一律用可關閉的小提示條（相同的訊息不重複堆疊）。"""
        self.提示層.顯示(字, 錯誤, 秒)

    def _有存檔(self, 摘要檔們):
        """這一場有沒有真的寫出任何檔案（摘要、直播稿、聊天室、逐句翻譯、音訊）。"""
        路徑們 = list(摘要檔們) + self.本場檔案 + [self.字幕器.存檔路徑]
        if any(p and os.path.exists(p) and os.path.getsize(p) > 0 for p in 路徑們):
            return True
        設 = self.本場設定 or {}
        return bool(設.get("save_audio") and self.直播鈕.isChecked())

    # ---------- 事件 ----------
    def 處理事件(self, 種類, 內容):
        if 種類 == "files":
            for 頁, 鍵 in ((self.稿頁, "稿"), (self.聊天頁, "聊天"), (self.分鐘頁, "分鐘"), (self.話題頁, "話題")):
                頁.設檔案(內容[鍵])
            # 這一場寫出的檔案（文字稿模式的直播稿、聊天室是讀進來的原檔，不算）
            self.本場檔案 = [內容[k] for k in (("稿", "聊天", "分鐘", "話題") if self.直播鈕.isChecked() else ("分鐘", "話題"))
                          if 內容[k]]
            # 逐句翻譯存成「原檔名_逐句翻譯.txt」；存檔區的「逐句翻譯」關著就不存
            存翻譯 = bool(self.本場設定 and self.本場設定["save_translation"])
            self.字幕器.存檔基底 = 內容["基底"] if 存翻譯 else None
            if self._待記網址:
                self.網址紀錄.加入(self._待記網址)
                self._待記網址 = None
        elif 種類 == "language_detected":
            self._更新翻譯註()
            self.語言狀態.收偵測(內容["語言"], 內容.get("狀態", "ok"), 內容.get("重新偵測", False))
            self.更新語言顯示()
            名 = config.語言名稱.get(內容["語言"], 內容["語言"])
            if 內容.get("狀態", "ok") != "ok":           # 低信心或失敗：明確告訴使用者，不要悄悄退回
                self._訊息("警告：" + self.語言狀態.文字())
                self.膠囊.語言警告提示()                  # 主控台常收著：膠囊旁也顯示
            elif subtitle.要翻譯(self.字幕器.模式, 內容["語言"], ""):
                self._訊息(f"偵測到{名}，逐句字幕自動切成翻譯。")
            else:
                self._訊息(f"偵測到{名}，逐句字幕顯示原文。")
        elif 種類 == "transcript_line":
            self.稿頁.加一行(f'<span style="color:{淡字};">{跳脫(內容["時間字"])}</span>&nbsp;&nbsp;{跳脫(內容["內容"])}')
            self._設藥丸(self.時間藥丸, self._時間藥丸字(內容["時間字"]))
            self._加計數("直播稿")
            if 內容["內容"] and not subtitle.要翻譯(self.字幕器.模式, self.字幕器.語言, 內容["內容"]):
                self.翻譯頁.加原文(內容["時間字"], 內容["內容"])        # 原文模式：逐句翻譯分頁顯示原文
                self._加計數("逐句翻譯")
        elif 種類 == "translation_line":
            self.翻譯頁.加譯文(內容["時間字"], 內容["原文"], 內容["譯文"])
            if 內容.get("檔案"):
                self.翻譯頁.設檔案(內容["檔案"])
            self._加計數("逐句翻譯")
        elif 種類 in ("chat_line", "chat_show"):
            if 內容.get("暫留"):            # 聊天室翻譯開著：等 chat_show 時原文與譯文一起出現
                return
            self.聊天頁.加留言(留言資料(內容))
            self._加計數("聊天室")
        elif 種類 == "minute_summary":
            self.分鐘頁.加卡片(lambda 內容=內容: self._分鐘html(內容))     # 傳函式：時間顯示換了可以重畫
            self._加計數("分鐘摘要")
        elif 種類 == "topic_summary":
            self.話題頁.加卡片(lambda 內容=內容: self._話題html(內容))
            self._加計數("話題摘要")
        elif 種類 == "stream_info":
            self.直播資訊 = dict(內容)
            self._更新時間藥丸()
            if not 內容["有開播"]:          # 開始時提示一次：時間改從開始擷取起算
                self.膠囊.小提示("抓不到開播時間：時間改為從開始擷取起算（前面加 +），\n摘要卡片顯示「幾分鐘前」", 8, 錯誤=None)
            self.膠囊.更新()
        elif 種類 == "current_topic":
            簡述 = 內容["簡述"] or "（新話題剛開始）"
            self.話題字.setText(f"目前話題（已進行 {內容['進行分鐘']:.0f} 分鐘）：{簡述}")
            self.話題頁.設進行中(f"已進行 {內容['進行分鐘']:.0f} 分鐘", 簡述)
        elif 種類 == "status":
            if "跟上" in 內容:
                跟上 = 內容["跟上"]
                self._設藥丸(self.轉錄藥丸, "轉錄：跟得上" if 跟上 else "轉錄：跟不上直播")
                self.轉錄藥丸.setStyleSheet(f"color: {綠 if 跟上 else 紅};")
            if "次數" in 內容:
                費用 = model_catalog.費用字(內容["費用"])
                self._設藥丸(self.費用藥丸, f"呼叫 {內容['次數']} 次 · 估算 {費用}")
            if "翻譯次數" in 內容:
                費用 = model_catalog.費用字(內容["翻譯費用"])
                延遲 = f" · 延遲約 {內容['翻譯延遲']:.0f} 秒" if 內容["翻譯延遲"] is not None else ""
                self._設藥丸(self.翻譯藥丸, f"翻譯 {內容['翻譯次數']} 次 · {費用}{延遲}")
            if "聊天翻譯次數" in 內容:
                費用 = model_catalog.費用字(內容["聊天翻譯費用"])
                self._設藥丸(self.聊天翻譯藥丸, f"聊天翻譯 {內容['聊天翻譯次數']} 次 · {費用}")
                self._更新聊天藥丸()
        elif 種類 == "info":
            if not self.結束中:          # 結束中一直顯示「正在產生最後一個話題的摘要…」
                self._訊息((內容.get("印出") or "").strip())
        elif 種類 == "error":
            if self.話題字.text() == "準備中…":
                self.話題字.setText("已停止")
            self.話題頁.移除進行中()
            self._設燈(紅)
            self._錯誤框("已停止：" + 內容["訊息"])
            if not self.啟動面板.等待中 and not self.要結束:      # 啟動中的錯誤由啟動面板顯示；直播中途的錯誤顯示在膠囊旁
                self.膠囊.錯誤提示("已停止：" + 內容["訊息"])
        elif 種類 == "finished":
            self.結束中 = False
            if 內容["檔案們"]:
                檔案 = "結果已存成：" + "、".join(os.path.basename(f) for f in 內容["檔案們"])
            else:
                檔案 = "沒有產生內容，所以沒有建立結果檔。"
            統計們 = [x for x in (self.字幕器.統計文字(), self.聊天翻譯器.統計文字()) if x]     # 逐句翻譯、聊天室翻譯各一行
            self._訊息(f"完成：切出 {內容['話題數']} 個話題。{檔案}" + "".join("\n" + x for x in 統計們))
            self.膠囊.小提示("已結束，已存檔" if self._有存檔(內容["檔案們"]) else "已結束")   # 不跳彈窗，膠囊旁幾秒後自動消失
            self.話題字.setText(self.話題字.text().replace("目前話題", "最後話題"))
            self.話題頁.移除進行中()        # 最後一個話題已經有摘要卡片了

    def 設聊天翻譯(self, 開):
        """膠囊選單「聊天室翻譯：開／關」：當場生效（直播中也是），並寫回 config.json。"""
        self.聊天翻譯器.開啟 = bool(開)
        capsule.寫設定("chat_translate", bool(開))
        self._更新聊天藥丸()
        if self.設定框:
            self.設定框.頁.同步聊天翻譯(bool(開))
        self.更新啟動面板費用()               # 啟動面板的每小時總費用跟著變

    def 更新啟動面板費用(self):
        """設定框儲存、膠囊選單切換聊天室翻譯、面板開關或套用版面之後呼叫：啟動面板開著就重算每小時總費用。
        設定框儲存金鑰、測試連線、清除金鑰之後也呼叫：啟動面板的「尚未設定 API 金鑰」提示跟著重新檢查。"""
        if hasattr(self, "啟動面板") and self.啟動面板.isVisible():
            self.啟動面板.更新金鑰提示()
            self.啟動面板._更新段位註()

    def _更新聊天藥丸(self):
        """聊天翻譯藥丸：聊天室翻譯開著、或這一場已經有呼叫過才顯示。"""
        顯示 = self.聊天翻譯器.開啟 or llm.聊天翻譯用量["次數"] > 0
        if self.聊天翻譯藥丸.isHidden() == 顯示:
            self.聊天翻譯藥丸.setVisible(顯示)
            self.狀態列.重排()

    def _更新翻譯註(self):
        """逐句翻譯分頁頂端的說明：原文模式、逐句翻譯面板沒開所以不翻譯、語言還在偵測。"""
        模式, 語言 = self.字幕器.模式, self.字幕器.語言
        if 模式 == "original" or (模式 == "auto" and 語言 == "zh"):
            字 = "目前為原文模式：這裡顯示原文，不翻譯，也不另外存檔。"
        elif 模式 == "auto" and 語言 == "auto":
            字 = "語言自動偵測中：偵測到外語後才會翻譯。"
        elif not self.字幕器.啟用:
            字 = "逐句翻譯面板沒有開，不會翻譯（省費用）。從膠囊選單「面板」打開「逐句翻譯 面板」後，之後的句子才會翻譯。"
        else:
            字 = ""
        self.翻譯頁.設註(字)

    # ---------- 時間顯示：直播時間／幾分鐘前 ----------
    def 用幾分鐘前(self):
        """摘要卡片要不要顯示「幾分鐘前」：選了 ago，或這一場抓不到開播時間（自動退回）。"""
        return self.時間顯示 == "ago" or bool(self.直播資訊 and not self.直播資訊["有開播"])

    def _卡片時間(self, 秒, 絕對字):
        """摘要卡片上的時間：幾分鐘前模式（且知道現在是直播第幾秒）顯示「3 分鐘前」，否則顯示絕對時間。"""
        現在 = stream_clock.現在直播秒()
        if self.用幾分鐘前() and 現在 is not None and 秒 is not None:
            return timefmt.相對字(現在 - 秒)
        return 絕對字

    def _時間藥丸字(self, 時間字):
        if self.直播資訊 and not self.直播資訊["有開播"]:
            return f"擷取時間 {時間字} · 抓不到開播時間"
        return f"直播時間 {時間字}"

    def _更新時間藥丸(self):
        """抓不到開播時間：藥丸標黃並說明；抓到了：滑鼠提示寫開播時間與來源。"""
        資 = self.直播資訊
        if 資 is None:
            return
        if 資["有開播"]:
            開播字 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(資["開播"]))
            來源 = {"GQL": "Twitch 公開資料", "網頁": "Twitch 頻道網頁"}.get(資.get("來源"), "Twitch")
            self.時間藥丸.setStyleSheet("")
            self.時間藥丸.setToolTip(f"直播實際進行時間（{開播字} 開播，來源：{來源}；已扣除約 {資['延遲']:.0f} 秒串流延遲）")
        else:
            self.時間藥丸.setStyleSheet(f"color: {黃};")
            self.時間藥丸.setToolTip("抓不到 Twitch 開播時間：時間改為從開始擷取起算（前面加 +），摘要卡片顯示「幾分鐘前」。")
            self._設藥丸(self.時間藥丸, "擷取時間 --:-- · 抓不到開播時間")

    def 設時間顯示(self, 模式, 寫回=True):
        """膠囊選單、設定框切換「直播時間／幾分鐘前」：當場重畫摘要卡片（直播稿、逐句翻譯、聊天室不受影響）。"""
        self.時間顯示 = 模式
        if 寫回:
            capsule.寫設定("time_display", 模式)
        if self.設定框:
            self.設定框.頁.同步時間顯示(模式)
        self._時間分 = None
        self.重畫摘要時間()

    def 重畫摘要時間(self):
        for 頁 in (self.分鐘頁, self.話題頁):
            頁.重畫時間()
        self.面板.重畫時間()

    def _檢查分鐘(self):
        """「幾分鐘前」模式：直播時間的分鐘數變了才重畫（看不到的頁面等出現時才畫）。"""
        if not self.用幾分鐘前():
            return
        現在 = stream_clock.現在直播秒()
        if 現在 is None:
            return
        分 = int(現在 // 60)
        if 分 != self._時間分:
            self._時間分 = 分
            self.重畫摘要時間()

    def _分鐘html(self, 內容):
        摘要 = 內容["摘要"]
        m = live_topics.時間標記.match(摘要)
        if m:
            秒 = timefmt.組秒(*m.groups())
            時間, 摘要 = 摘要[1:m.end() - 1], 摘要[m.end():].strip()
        else:
            秒, 時間 = 內容["秒"], live_topics.秒轉字(內容["秒"])
        時間 = self._卡片時間(秒, 時間)
        部分 = [f'{時間標(時間)}&nbsp;&nbsp;<span style="font-size:15px; line-height:150%;">{跳脫(摘要)}</span>']
        if 內容["支線"]:
            支線 = "；".join(f"[{live_topics.秒轉字(s)}] {n}" for s, n in 內容["支線"])
            部分.append(f'<span style="color:{黃};">支線</span>&nbsp; <span style="color:{淡字};">{跳脫(支線)}</span>')
        if 內容["觀眾反應"]:
            部分.append(f'<span style="color:{綠};">觀眾反應</span>&nbsp; <span style="color:{淡字};">{跳脫(內容["觀眾反應"])}</span>')
        return "<br>".join(部分)

    def _話題html(self, 內容):
        標題, 其他 = "", []
        for 行 in 內容["內文"].splitlines():
            行 = 行.strip()
            if not 行:
                continue
            if 行.startswith("【話題標題】"):
                標題 = 行[len("【話題標題】"):].strip()
            elif 行.startswith("【時間範圍】"):
                continue      # 卡片上方已經有時間
            elif 行.startswith("【") and "】" in 行:
                標籤, 剩 = 行[1:].split("】", 1)
                其他.append(f'<br><span style="color:#b9a8ff; font-weight:700;">{跳脫(標籤)}</span>'
                          + (f'&nbsp; {跳脫(剩.strip())}' if 剩.strip() else ""))
            else:
                其他.append(f'<br><span style="color:{淡字};">{跳脫(行)}</span>')
        範圍 = 內容["開始"] + " – " + 內容["結束"]
        if 內容.get("結束秒") is not None:
            起, 訖 = self._卡片時間(內容.get("開始秒"), 內容["開始"]), self._卡片時間(內容["結束秒"], 內容["結束"])
            範圍 = 起 + " – " + 訖
        頭 = (f'{時間標(範圍)}&nbsp;&nbsp;'
             f'<span style="font-size:16px; font-weight:700;">{跳脫(標題 or "話題")}</span>')
        return 頭 + '<span style="line-height:150%;">' + "".join(其他) + "</span>"

    def _設燈(self, 色):
        self.燈.setStyleSheet(f"color: {色}; font-size: 14px;")

    def _錯誤框(self, 訊息):
        self._訊息(訊息, 錯誤=True, 秒=12)


def 選字型():
    已有 = set(QFontDatabase.families())
    for 名 in ("Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans TC", "微軟正黑體"):
        if 名 in 已有:
            return QFont(名, 10)
    return QFont()


def main():
    os.chdir(專案目錄)            # 結果檔和命令列一樣存在專案資料夾（放在啟動時，import app 不會改工作目錄）
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)   # 讓標題列也變深色（Qt 6.8 以上才有）
    except Exception:
        pass
    app.setFont(選字型())
    app.setStyleSheet(樣式表)
    app.setQuitOnLastWindowClosed(False)      # 主控台、啟動面板都可能收著；只有「結束程式」才結束
    窗 = 主控台()                # 主控台先建好但不顯示（可從膠囊選單「顯示主控台」打開）
    窗.開程式()                 # 開程式：只出現浮動膠囊（含系統匣圖示）和啟動面板（第一次是首次引導）；面板等按了「開始」才依版面出現
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
