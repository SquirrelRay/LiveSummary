# 直播摘要主控台（桌面介面）
# 用法：python app.py
# 引擎（live_topics.py）在背景執行緒跑，結果透過 events.py 的事件送過來，介面只負責顯示。
import os
import sys
import json
import html
import shutil
import time
import threading
import subprocess

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QLineEdit, QPushButton, QComboBox,
    QHBoxLayout, QVBoxLayout, QTabWidget, QTextBrowser, QScrollArea, QFileDialog, QMessageBox,
    QButtonGroup, QSizePolicy,
)

專案目錄 = os.path.dirname(os.path.abspath(__file__))
os.chdir(專案目錄)            # 結果檔和命令列一樣存在專案資料夾
sys.path.insert(0, 專案目錄)

import events
import llm
import live_topics
import overlay       # 字幕疊加層與全域快捷鍵
import subtitle      # 逐句字幕（原文或翻譯）
import settings_page # 「設定」分頁

語言選項 = [("中文", "zh"), ("日文", "ja"), ("英文", "en"), ("韓文", "ko"), ("自動偵測", "auto")]
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
QLabel#藥丸 {{ background: {卡片}; border: 1px solid {邊框}; border-radius: 11px; padding: 3px 10px; }}
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
QPushButton#字幕:checked {{ background: rgba(139,108,255,0.18); border: 1px solid {主色}; color: #c4b5ff; font-weight: 700; }}
QFrame#切換框 {{ background: {卡片}; border: 1px solid {邊框}; border-radius: 12px; }}
QTabWidget::pane {{ border: 1px solid {邊框}; border-radius: 14px; background: {面板}; top: -1px; }}
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
"""


結束中文字 = "正在產生最後一個話題的摘要，約需 10 秒…"
翻譯收尾文字 = "正在翻譯剩下的句子…"
翻譯收尾最多秒 = 10     # 收尾翻譯最多等幾秒，超時就放棄
快捷鍵編號 = {"hotkey_toggle": 1, "hotkey_click_through": 2, "hotkey_summary": 3, "hotkey_subtitle": 4}


def 轉換舊設定():
    """config.json 的 overlay 還是舊格式（一個框）時，自動轉成兩個框的格式並寫回（先備份）。回傳提示文字。"""
    路徑 = live_topics.設定檔路徑
    try:
        with open(路徑, encoding="utf-8-sig") as f:
            內容 = json.load(f)
        if not (isinstance(內容, dict) and overlay.是舊版(內容.get("overlay"))):
            return ""
        shutil.copy2(路徑, settings_page.備份檔)
        內容["overlay"] = overlay.讀設定(內容["overlay"])[0]
        with open(路徑, "w", encoding="utf-8") as f:
            json.dump(內容, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return "已把舊的字幕設定自動轉成「摘要框＋字幕框」兩個框的設定（原本的存在 config.backup.json）。"
    except Exception:
        return ""


def 跳脫(字):
    return html.escape(str(字))


class 事件橋(QObject):
    """背景執行緒送來的事件，透過 Qt 訊號轉到介面執行緒處理（介面元件只能在介面執行緒動）。"""
    收到 = Signal(str, dict)
    結束 = Signal()

    def 接收(self, 種類, 內容):
        self.收到.emit(種類, dict(內容))


def 黏在底部(捲軸):
    """新內容進來時自動捲到最下面；使用者往上捲的時候就不動。"""
    狀態 = {"黏": True}
    捲軸.valueChanged.connect(lambda v: 狀態.update(黏=v >= 捲軸.maximum() - 8))
    捲軸.rangeChanged.connect(lambda lo, hi: 捲軸.setValue(hi) if 狀態["黏"] else None)


class 頂列(QWidget):
    """分頁最上方的一行「較早的內容已存檔」＋「打開檔案」按鈕；內容還沒超過上限時不顯示。"""

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
    """上面一列提示、下面是清單。清單超過上限就從最舊的開始從畫面移除（存檔不受影響）。"""

    def __init__(self, 內):
        super().__init__()
        版 = QVBoxLayout(self)
        版.setContentsMargins(0, 0, 0, 0)
        版.setSpacing(0)
        self.頂 = 頂列()
        版.addWidget(self.頂)
        版.addWidget(內, 1)
        self.上限 = 500
        self.總數 = 0

    def 設上限(self, n):
        self.上限 = int(n)

    def 設檔案(self, 路徑):
        self.頂.檔案 = 路徑
        self.頂.字.setText("較早的內容已存檔")

    def _超過了(self):
        if self.總數 > self.上限:
            self.頂.show()


class 文字清單(分頁基底):
    """直播稿、聊天室用：一行一行往下加，只留最近的 上限 行。"""

    def __init__(self, 提示):
        self.瀏覽 = QTextBrowser()
        super().__init__(self.瀏覽)
        self.瀏覽.setOpenExternalLinks(False)
        self.瀏覽.setPlaceholderText(提示)
        self.瀏覽.document().setDocumentMargin(16)
        黏在底部(self.瀏覽.verticalScrollBar())

    def 設上限(self, n):
        super().設上限(n)
        self.瀏覽.document().setMaximumBlockCount(self.上限)     # 超過就從最舊的一行開始移除

    def 加一行(self, 內容html):
        self.瀏覽.append(內容html)
        self.總數 += 1
        self._超過了()

    def clear(self):
        self.瀏覽.clear()
        self.總數 = 0
        self.頂.hide()


class 卡片清單(分頁基底):
    """分鐘摘要、話題摘要用：一張一張卡片往下加（最新在下面），只留最近的 上限 張。"""

    def __init__(self, 提示):
        self.捲 = QScrollArea()
        super().__init__(self.捲)
        self.捲.setWidgetResizable(True)
        self.捲.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        內 = QWidget()
        self.排版 = QVBoxLayout(內)
        self.排版.setContentsMargins(16, 16, 16, 16)
        self.排版.setSpacing(12)
        self.提示 = QLabel(提示)
        self.提示.setObjectName("淡")
        self.排版.addWidget(self.提示)
        self.排版.addStretch(1)
        self.捲.setWidget(內)
        黏在底部(self.捲.verticalScrollBar())
        self.數量 = 0         # 畫面上目前有幾張

    def 加卡片(self, 內容html):
        self.提示.hide()
        卡 = QFrame()
        卡.setObjectName("卡片")
        版 = QVBoxLayout(卡)
        版.setContentsMargins(16, 12, 16, 12)
        字 = QLabel(內容html)
        字.setWordWrap(True)
        字.setTextFormat(Qt.RichText)
        字.setTextInteractionFlags(Qt.TextSelectableByMouse)
        字.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        版.addWidget(字)
        self.排版.insertWidget(self.排版.count() - 1, 卡)
        self.數量 += 1
        self.總數 += 1
        while self.數量 > self.上限:       # 從最舊的一張開始移除
            項 = self.排版.takeAt(1)
            if 項.widget():
                項.widget().deleteLater()
            self.數量 -= 1
        self._超過了()

    def 清空(self):
        while self.排版.count() > 2:
            項 = self.排版.takeAt(1)
            if 項.widget():
                項.widget().deleteLater()
        self.提示.show()
        self.數量 = 0
        self.總數 = 0
        self.頂.hide()


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
        self.結束中 = False

        # 兩個字幕框：跟著引擎的事件更新，不另外跑引擎
        轉換訊息 = 轉換舊設定()
        設定, _, _ = live_topics.載入設定({})
        ov, _ = overlay.讀設定(設定["overlay"])
        self.ov = ov
        self.摘要框 = overlay.摘要框(ov["summary_box"])
        self.字幕框 = overlay.字幕框(ov["subtitle_box"])
        for 框 in self.框們():
            框.設穿透(ov["click_through"])
        self.字幕器 = subtitle.字幕器()
        events.接收者們.append(self.字幕器.接收)

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
        總.addWidget(self._做分頁(), 1)
        self._切換來源()
        if 轉換訊息:
            self._訊息(轉換訊息)
            self.訊息字.show()

    # ---------- 版面 ----------
    def _做控制區(self):
        框 = QFrame()
        框.setObjectName("面板")
        版 = QVBoxLayout(框)
        版.setContentsMargins(18, 16, 18, 16)
        版.setSpacing(12)

        第一列 = QHBoxLayout()
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
        self.網址框 = QLineEdit()
        self.網址框.setPlaceholderText("https://www.twitch.tv/頻道名稱")
        self.檔案框 = QLineEdit()
        self.檔案框.setPlaceholderText("選一個文字稿 .txt 檔（每行 [mm:ss] 文字）")
        self.瀏覽鈕 = QPushButton("瀏覽…")
        self.瀏覽鈕.clicked.connect(self._選檔案)
        第二列.addWidget(self.網址框, 1)
        第二列.addWidget(self.檔案框, 1)
        第二列.addWidget(self.瀏覽鈕)
        版.addWidget(self.網址區)

        第三列 = QHBoxLayout()
        第三列.setSpacing(8)
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
        設定, _, _ = live_topics.載入設定({})       # 預設選 config.json 的語言
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
        self.字幕鈕 = QPushButton("字幕")
        self.字幕鈕.setObjectName("字幕")
        self.字幕鈕.setCheckable(True)
        self.字幕鈕.setCursor(Qt.PointingHandCursor)
        self.字幕鈕.setToolTip("同時開關摘要框與字幕框（預設 Ctrl+Shift+S，可在「設定」分頁改）")
        self.字幕鈕.clicked.connect(self.切換字幕)
        self.語言區 = QWidget()
        語言版 = QHBoxLayout(self.語言區)
        語言版.setContentsMargins(0, 0, 0, 0)
        語言版.setSpacing(8)
        for w in (self.速度標, self.速度選, 語言標, self.語言選):
            語言版.addWidget(w)
        第三列.addWidget(self.語言區)
        第三列.addStretch(1)
        第三列.addWidget(self.字幕鈕)
        第三列.addWidget(self.開始鈕)
        第三列.addWidget(self.停止鈕)
        版.addLayout(第三列)
        return 框

    def _做狀態區(self):
        框 = QFrame()
        框.setObjectName("面板")
        框.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        版 = QVBoxLayout(框)
        版.setContentsMargins(14, 7, 14, 7)
        版.setSpacing(3)

        上 = QHBoxLayout()
        上.setSpacing(8)
        self.燈 = QLabel("●")
        self.燈.setStyleSheet(f"color: {淡字}; font-size: 14px;")
        self.話題字 = QLabel("尚未開始")
        self.話題字.setWordWrap(True)
        self.話題字.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.話題字.setStyleSheet("font-weight: 700;")
        上.addWidget(self.燈, 0, Qt.AlignVCenter)
        上.addWidget(self.話題字, 1)
        下 = 上            # 狀態藥丸和話題放同一列，卡片比較扁
        self.時間藥丸 = QLabel("直播時間 --:--")
        self.轉錄藥丸 = QLabel("轉錄：等待中")
        self.費用藥丸 = QLabel("呼叫 0 次 · 估算 $0.000")
        self.費用藥丸.setToolTip("費用用 config.json 的單價估算，單價未查證，僅供參考")
        self.翻譯藥丸 = QLabel("翻譯 0 次 · $0.000")
        self.翻譯藥丸.setToolTip("逐句字幕翻譯的呼叫次數與估算費用（和摘要分開算，單價未查證）")
        for w in (self.時間藥丸, self.轉錄藥丸, self.費用藥丸, self.翻譯藥丸):
            w.setObjectName("藥丸")
            下.addWidget(w)
        註 = QLabel("（單價未查證）")
        註.setObjectName("小標")
        下.addWidget(註)
        版.addLayout(上)

        self.訊息字 = QLabel("")
        self.訊息字.setObjectName("小標")
        self.訊息字.setWordWrap(True)
        self.訊息字.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.訊息字.hide()          # 沒有訊息時不佔空間
        版.addWidget(self.訊息字)
        return 框

    def _做分頁(self):
        self.分頁 = QTabWidget()
        self.分鐘頁 = 卡片清單("分鐘摘要會在這裡出現（每檢查一次一則，最新在最下面）")
        self.話題頁 = 卡片清單("每個話題結束時，話題摘要會在這裡出現")
        self.稿頁 = 文字清單("逐句轉錄的直播稿會在這裡出現")
        self.聊天頁 = 文字清單("聊天室留言會在這裡出現（只有直播網址模式會抓聊天室）")
        self.分頁名 = ["分鐘摘要", "話題摘要", "直播稿", "聊天室"]
        for 頁, 名 in zip((self.分鐘頁, self.話題頁, self.稿頁, self.聊天頁), self.分頁名):
            self.分頁.addTab(頁, 名)
        self.計數 = [0, 0, 0, 0]
        self.設定頁 = settings_page.設定頁(self)
        self.分頁.addTab(self.設定頁, "設定")
        self.設定頁.載入()
        self.分頁.currentChanged.connect(lambda i: self.設定頁.同步位置() if self.分頁.widget(i) is self.設定頁 else None)
        return self.分頁

    def _切換來源(self):
        直播 = self.直播鈕.isChecked()
        self.網址框.setVisible(直播)
        self.檔案框.setVisible(not 直播)
        self.瀏覽鈕.setVisible(not 直播)
        self.速度標.setVisible(not 直播)
        self.速度選.setVisible(not 直播)

    def _選檔案(self):
        路徑, _ = QFileDialog.getOpenFileName(self, "選擇文字稿", 專案目錄, "文字稿 (*.txt);;所有檔案 (*)")
        if 路徑:
            self.檔案框.setText(路徑)

    def _加計數(self, i):
        self.計數[i] += 1
        self.分頁.setTabText(i, f"{self.分頁名[i]}  {self.計數[i]}")

    # ---------- 開始 / 停止 ----------
    def 開始(self):
        直播 = self.直播鈕.isChecked()
        網址 = self.網址框.text().strip() if 直播 else None
        檔案 = self.檔案框.text().strip().strip('"') if not 直播 else None
        if 直播 and not 網址:
            return self._錯誤框("請先輸入直播網址，例如 https://www.twitch.tv/頻道名稱")
        if not 直播 and not os.path.isfile(檔案 or ""):
            return self._錯誤框("找不到這個文字稿檔案，請重新選擇。")

        # 每次開始都重新讀 config.json；介面上的語言只覆蓋這一場，不寫回 config.json
        設定, _, 警告們 = live_topics.載入設定({"language": self.語言選.currentData()})
        llm.套用設定(設定)

        for 頁, 鍵 in ((self.分鐘頁, "ui_max_summary"), (self.話題頁, "ui_max_summary"),
                      (self.稿頁, "ui_max_transcript"), (self.聊天頁, "ui_max_chat")):
            頁.設上限(設定[鍵])
            頁.設檔案(None)
        for 頁 in (self.分鐘頁, self.話題頁):
            頁.清空()
        for 頁 in (self.稿頁, self.聊天頁):
            頁.clear()
        self.計數 = [0, 0, 0, 0]
        for i, 名 in enumerate(self.分頁名):
            self.分頁.setTabText(i, 名)
        self.話題字.setText("準備中…")
        self.時間藥丸.setText("直播時間 --:--")
        self.轉錄藥丸.setText("轉錄：文字稿模式" if not 直播 else "轉錄：等待中")
        self.轉錄藥丸.setStyleSheet("")
        self.費用藥丸.setText("呼叫 0 次 · 估算 $0.000")
        self.翻譯藥丸.setText("翻譯 0 次 · $0.000")
        self.結束中 = False
        self.摘要框.清空()
        self.字幕框.清空()
        self.字幕器.開始(設定["subtitle_mode"], 設定["language"], 設定["model"],
                      設定["price_input"], 設定["price_output"],
                      設定["translate_batch_seconds"], 設定["translate_batch_lines"])
        self.字幕器.啟用 = self.字幕框.開啟
        self._訊息("　".join("警告：" + w for w in 警告們) or ("正在檢查直播…" if 直播 else "開始重播文字稿…"))
        self._設燈(綠)

        events.停止.clear()
        self.開始鈕.setEnabled(False)
        self.停止鈕.setEnabled(True)
        self.停止鈕.setText("停止")
        for w in (self.網址框, self.檔案框, self.瀏覽鈕, self.速度選, self.語言選, self.直播鈕, self.檔案鈕):
            w.setEnabled(False)
        self.收合設定(True)              # 開始後收起網址與語言，摘要區變大
        self.設定頁.設執行中(True)

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
            self.摘要框.設狀態(翻譯收尾文字)
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
        self.停止鈕.setText(結束中文字)
        self._訊息(結束中文字 + "（同時關閉音訊擷取與聊天室）")
        self.摘要框.設狀態(結束中文字)

    def 跑完了(self):
        self.執行緒 = None
        self.結束中 = False
        if getattr(self, "_收尾計時", None):
            self._收尾計時.stop()
        self.字幕器.結束()
        self.設定頁.設執行中(False)
        if self.摘要框.狀態提示 in (結束中文字, 翻譯收尾文字):
            self.摘要框.設狀態("")
        self.開始鈕.setEnabled(True)
        self.停止鈕.setEnabled(False)
        self.停止鈕.setText("停止")
        for w in (self.網址框, self.檔案框, self.瀏覽鈕, self.速度選, self.語言選, self.直播鈕, self.檔案鈕):
            w.setEnabled(True)
        self._設燈(淡字)
        if self.要關閉:
            self.close()

    def closeEvent(self, e):
        if self.執行緒 and self.執行緒.is_alive():   # 還在跑：先乾淨結束，完成後自動關窗
            self.要關閉 = True
            self.停止()
            self._訊息("正在結束，完成後視窗會自動關閉…")
            e.ignore()
            return
        events.接收者們.remove(self.橋.接收) if self.橋.接收 in events.接收者們 else None
        for 編號 in 快捷鍵編號.values():
            overlay.取消快捷鍵(int(self.winId()), 編號)
        for 框 in self.框們():
            if 框.開啟:
                框.記住位置()
            框.close()
        e.accept()

    # ---------- 兩個字幕框與快捷鍵 ----------
    def 框們(self):
        return (self.摘要框, self.字幕框)

    def 框(self, 設定鍵):
        return self.摘要框 if 設定鍵 == "summary_box" else self.字幕框

    def 執行中(self):
        return bool(self.執行緒 and self.執行緒.is_alive())

    def 開關框(self, 框, 開):
        框.顯示() if 開 else 框.隱藏()
        if 框 is self.字幕框:
            self.字幕器.啟用 = 開          # 字幕框關著就不產生字幕（不翻譯，省錢）
        self.字幕鈕.setChecked(any(f.開啟 for f in self.框們()))
        if 開 and 框.穿透:
            框.閃提示("穿透：開（按 " + self.ov["hotkey_click_through"] + " 可關閉以拖曳）", 2000)

    def 切換字幕(self):
        """同時開關兩個框（設定裡「不顯示」的框不會被打開）。"""
        要開的 = [f for f in self.框們() if f.設定["show"]] or list(self.框們())
        開 = not any(f.開啟 for f in self.框們())
        for 框 in (要開的 if 開 else self.框們()):
            self.開關框(框, 開)
        self.字幕鈕.setChecked(開)

    def 切換穿透(self):
        if not any(f.開啟 for f in self.框們()):
            self._訊息("字幕框沒有開啟，先按「字幕」或 " + self.ov["hotkey_toggle"] + " 開啟。")
            return
        穿透 = not self.摘要框.穿透
        for 框 in self.框們():
            框.設穿透(穿透)
            框.閃提示("穿透：開（點擊會穿過字幕）" if 穿透 else "穿透：關（可拖曳移動、拖左右邊緣改寬度）")

    def 註冊快捷鍵(self, ov=None):
        """重新註冊四個快捷鍵。回傳中文問題清單（沒問題 = 空清單）。"""
        if ov is not None:
            self.ov = dict(self.ov, **{k: ov[k] for k in 快捷鍵編號})
        問題們 = []
        for 編號 in 快捷鍵編號.values():
            overlay.取消快捷鍵(int(self.winId()), 編號)
        for 鍵名, 編號 in 快捷鍵編號.items():
            問題 = overlay.註冊快捷鍵(int(self.winId()), 編號, self.ov[鍵名])
            if 問題:
                問題們.append(問題)
        if 問題們:
            self._訊息("　".join(問題們))
        self.字幕鈕.setToolTip(f"同時開關摘要框與字幕框（{self.ov['hotkey_toggle']}；只開關摘要框 {self.ov['hotkey_summary']}、"
                             f"只開關字幕框 {self.ov['hotkey_subtitle']}、切換穿透 {self.ov['hotkey_click_through']}）")
        return 問題們

    def nativeEvent(self, 種類, 訊息):
        """接收 Windows 全域快捷鍵（WM_HOTKEY）。"""
        if 種類 == b"windows_generic_MSG" or 種類 == "windows_generic_MSG":
            m = overlay.wintypes.MSG.from_address(int(訊息))
            if m.message == overlay.WM_HOTKEY:
                if m.wParam == 快捷鍵編號["hotkey_toggle"]:
                    self.切換字幕()
                elif m.wParam == 快捷鍵編號["hotkey_summary"]:
                    self.開關框(self.摘要框, not self.摘要框.開啟)
                elif m.wParam == 快捷鍵編號["hotkey_subtitle"]:
                    self.開關框(self.字幕框, not self.字幕框.開啟)
                elif m.wParam == 快捷鍵編號["hotkey_click_through"]:
                    self.切換穿透()
                return True, 0
        return super().nativeEvent(種類, 訊息)

    # ---------- 收合、訊息、完成提示 ----------
    def 收合設定(self, 收):
        self.已收合 = 收
        for w in (self.網址區, self.語言區, self.切換框):
            w.setVisible(not 收)
        if not 收:
            self._切換來源()
        self.收合鈕.setText("▸ 展開網址與語言" if 收 else "▾ 收合網址與語言")

    def _訊息(self, 字):
        self.訊息字.setText(字)
        self.訊息字.setVisible(bool(字))

    def _完成提示(self, 檔案們):
        框 = QMessageBox(self)
        框.setIcon(QMessageBox.Information)
        框.setWindowTitle("直播摘要")
        if 檔案們:
            框.setText("已完成，摘要已存到：\n" + "\n".join(os.path.basename(f) for f in 檔案們))
            打開 = 框.addButton("打開資料夾", QMessageBox.ActionRole)
            打開.clicked.connect(lambda: subprocess.Popen(["explorer", "/select,", os.path.abspath(檔案們[0])]))
        else:
            框.setText("已完成，這次沒有產生內容，所以沒有建立摘要檔。")
        框.addButton("知道了", QMessageBox.AcceptRole)
        框.setModal(False)
        框.show()           # 不擋住主控台
        self.完成框 = 框

    # ---------- 事件 ----------
    def 處理事件(self, 種類, 內容):
        if 種類 == "files":
            for 頁, 鍵 in ((self.稿頁, "稿"), (self.聊天頁, "聊天"), (self.分鐘頁, "分鐘"), (self.話題頁, "話題")):
                頁.設檔案(內容[鍵])
        elif 種類 == "subtitle":
            self.字幕框.加字幕(內容["文字"], 內容.get("已翻譯", False))
        elif 種類 == "language_detected":
            名 = {"zh": "中文", "ja": "日文", "en": "英文", "ko": "韓文"}.get(內容["語言"], 內容["語言"])
            if subtitle.要翻譯(self.字幕器.模式, 內容["語言"], ""):
                self._訊息(f"偵測到{名}，逐句字幕自動切成翻譯。")
            else:
                self._訊息(f"偵測到{名}，逐句字幕顯示原文。")
        elif 種類 == "transcript_line":
            self.稿頁.加一行(f'<span style="color:{淡字};">{跳脫(內容["時間字"])}</span>&nbsp;&nbsp;{跳脫(內容["內容"])}')
            self.時間藥丸.setText(f"直播時間 {內容['時間字']}")
            self._加計數(2)
        elif 種類 == "chat_line":
            色 = 名字顏色[sum(map(ord, 內容["使用者"])) % len(名字顏色)]
            self.聊天頁.加一行(
                f'<span style="color:{淡字};">{跳脫(內容["時間字"])}</span>&nbsp;&nbsp;'
                f'<b style="color:{色};">{跳脫(內容["使用者"])}</b>&nbsp;&nbsp;{跳脫(內容["內容"])}')
            self._加計數(3)
        elif 種類 == "minute_summary":
            self.分鐘頁.加卡片(self._分鐘html(內容))
            self._加計數(0)
            self.摘要框.更新摘要(內容)
        elif 種類 == "topic_summary":
            self.話題頁.加卡片(self._話題html(內容))
            self._加計數(1)
        elif 種類 == "current_topic":
            self.話題字.setText(f"目前話題：{內容['簡述'] or '（新話題剛開始）'}　·　已進行 {內容['進行分鐘']:.0f} 分鐘")
            self.摘要框.更新話題(內容["簡述"])
        elif 種類 == "status":
            if "跟上" in 內容:
                跟上 = 內容["跟上"]
                self.轉錄藥丸.setText("轉錄：跟得上" if 跟上 else "轉錄：跟不上直播")
                self.轉錄藥丸.setStyleSheet(f"color: {綠 if 跟上 else 紅};")
            if "次數" in 內容:
                費用 = "無法計算" if 內容["費用"] is None else f"${內容['費用']:.3f}"
                self.費用藥丸.setText(f"呼叫 {內容['次數']} 次 · 估算 {費用}")
            if "翻譯次數" in 內容:
                費用 = "無法計算" if 內容["翻譯費用"] is None else f"${內容['翻譯費用']:.3f}"
                延遲 = f" · 延遲約 {內容['翻譯延遲']:.0f} 秒" if 內容["翻譯延遲"] is not None else ""
                self.翻譯藥丸.setText(f"翻譯 {內容['翻譯次數']} 次 · {費用}{延遲}")
        elif 種類 == "info":
            if not self.結束中:          # 結束中一直顯示「正在產生最後一個話題的摘要…」
                self._訊息((內容.get("印出") or "").strip())
        elif 種類 == "error":
            self._訊息("已停止：" + 內容["訊息"])
            self.摘要框.設狀態("已停止")
            if self.話題字.text() == "準備中…":
                self.話題字.setText("已停止")
            self._設燈(紅)
            self._錯誤框(內容["訊息"])
        elif 種類 == "finished":
            self.結束中 = False
            if 內容["檔案們"]:
                檔案 = "結果已存成：" + "、".join(os.path.basename(f) for f in 內容["檔案們"])
            else:
                檔案 = "沒有產生內容，所以沒有建立結果檔。"
            翻譯 = self.字幕器.統計文字()
            self._訊息(f"完成：切出 {內容['話題數']} 個話題。{檔案}" + ("\n" + 翻譯 if 翻譯 else ""))
            self.摘要框.設狀態("已結束")
            self._完成提示(內容["檔案們"])
            self.話題字.setText(self.話題字.text().replace("目前話題", "最後話題"))

    def _分鐘html(self, 內容):
        摘要 = 內容["摘要"]
        m = live_topics.時間標記.match(摘要)
        if m:
            時間, 摘要 = 摘要[1:m.end() - 1], 摘要[m.end():].strip()
        else:
            時間 = live_topics.秒轉字(內容["秒"])
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
        頭 = (f'{時間標(內容["開始"] + " – " + 內容["結束"])}&nbsp;&nbsp;'
             f'<span style="font-size:16px; font-weight:700;">{跳脫(標題 or "話題")}</span>')
        return 頭 + '<span style="line-height:150%;">' + "".join(其他) + "</span>"

    def _設燈(self, 色):
        self.燈.setStyleSheet(f"color: {色}; font-size: 14px;")

    def _錯誤框(self, 訊息):
        框 = QMessageBox(self)
        框.setIcon(QMessageBox.Warning)
        框.setWindowTitle("直播摘要")
        框.setText(訊息)
        框.setStandardButtons(QMessageBox.Ok)
        框.button(QMessageBox.Ok).setText("知道了")
        框.exec()


def 選字型():
    已有 = set(QFontDatabase.families())
    for 名 in ("Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans TC", "微軟正黑體"):
        if 名 in 已有:
            return QFont(名, 10)
    return QFont()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)   # 讓標題列也變深色（Qt 6.8 以上才有）
    except Exception:
        pass
    app.setFont(選字型())
    app.setStyleSheet(樣式表)
    窗 = 主控台()
    窗.show()
    窗.註冊快捷鍵()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
