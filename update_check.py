# 檢查更新：程式啟動後在背景向 GitHub 查這個專案最新發布的版本號，比 version.py 新就跳出視窗通知。
# - 只通知，不自動下載安裝；只送一個 GET 請求查版本號，不傳送任何個人資料。
# - 不能拖慢啟動：查詢在背景執行緒，逾時上限約 5 秒；主畫面完全不等它。
# - 網路不通、GitHub 連不上、專案還沒有發布版（404）、逾時、回傳格式不對：一律安靜跳過，
#   只在 logs\更新檢查紀錄.txt 記一行，不跳任何錯誤視窗。
# - 「略過這個版本」記在介面設定.json（ui_state），以後不再提醒那一版（更新的版本照常提醒）。
import http.client
import json
import os
import re
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

import app_paths
import ui_state
import version

逾時秒 = 5
回應上限 = 1024 * 1024        # 發布資訊再大也不讀超過 1 MB
內容上限 = 600                # 視窗裡的更新內容最多顯示幾個字，太長截斷

狀態_新版 = "新版"
狀態_最新 = "最新"
狀態_略過 = "略過"
狀態_失敗 = "失敗"


class 查詢失敗(Exception):
    pass


class 結果:
    def __init__(self, 狀態, 版本="", 內容="", 網址="", 原因=""):
        self.狀態 = 狀態
        self.版本 = 版本          # 最新發布版的版本號（沒有開頭的 v）
        self.內容 = 內容          # 更新內容（發布說明，原文）
        self.網址 = 網址          # 發布頁網址（前往下載用）
        self.原因 = 原因          # 失敗時的白話原因（只寫進 log）

    def __repr__(self):
        return f"結果({self.狀態!r}, {self.版本!r}, {self.原因!r})"


# ---------- 版本號 ----------
def 解析版本(字):
    """'v1.0.10' → (1, 0, 10)；開頭可以有 v／V，後面的 -beta 之類不看。不是版本號回傳 None。"""
    m = re.match(r"^[vV]?(\d+(?:\.\d+)*)", str(字 or "").strip())
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split("."))


def 較新(新, 舊):
    """新版本號是否比舊的新（逐段比整數，所以 1.0.10 比 1.0.9 新；段數不同時補 0）。任一邊不是版本號回傳 False。"""
    甲, 乙 = 解析版本(新), 解析版本(舊)
    if 甲 is None or 乙 is None:
        return False
    長 = max(len(甲), len(乙))
    return (甲 + (0,) * (長 - len(甲))) > (乙 + (0,) * (長 - len(乙)))


def 乾淨版本字(字):
    """顯示與記錄用：去掉開頭的 v，例如 'v1.2.0' → '1.2.0'。"""
    return re.sub(r"^[vV]", "", str(字 or "").strip())


# ---------- 查詢 ----------
def 發布資訊網址():
    return f"https://api.github.com/repos/{version.GitHub倉庫}/releases/latest"


def _預設開網址(網址, 逾時):
    要求 = urllib.request.Request(網址, headers={       # noqa: S310  固定的 https GitHub API 網址
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{version.英文名}/{version.版本}",
    })
    return urllib.request.urlopen(要求, timeout=逾時)   # noqa: S310


def 查最新(開網址=None, 逾時=逾時秒):
    """向 GitHub 查最新發布版，回傳 (版本號, 更新內容, 發布頁網址)。任何問題都丟 查詢失敗（白話原因）。
    開網址(網址, 逾時) 要回傳有 read() 的物件（可當 with 用）；測試傳假的。"""
    開 = 開網址 or _預設開網址
    try:
        with 開(發布資訊網址(), 逾時) as 回應:
            原始 = 回應.read(回應上限)
    except (OSError, http.client.HTTPException) as e:       # URLError、HTTPError、逾時、斷線都是 OSError
        代碼 = getattr(e, "code", None)
        if 代碼 == 404:
            raise 查詢失敗("HTTP 404：專案或發布版還不存在") from e
        if 代碼 is not None:
            raise 查詢失敗(f"HTTP {代碼}") from e
        if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):      # urlopen 會把逾時包成 URLError
            raise 查詢失敗("逾時") from e
        raise 查詢失敗(f"連不上（{type(e).__name__}）") from e
    try:
        資料 = json.loads(原始)
    except (ValueError, TypeError) as e:
        raise 查詢失敗("回傳不是 JSON") from e
    if not isinstance(資料, dict):
        raise 查詢失敗("回傳格式不對（不是物件）")
    標籤 = 資料.get("tag_name")
    if not isinstance(標籤, str) or 解析版本(標籤) is None:
        raise 查詢失敗("回傳格式不對（沒有可讀的 tag_name）")
    內容 = 資料.get("body")
    網址 = 資料.get("html_url")
    # 網址只收這個專案的 GitHub 頁面，其他一律退回發布頁（不信任回傳內容裡的任意連結）
    if not (isinstance(網址, str) and 網址.startswith(version.專案網址 + "/")):
        網址 = version.發布頁網址
    return 乾淨版本字(標籤), 內容 if isinstance(內容, str) else "", 網址


def 檢查(目前版本=None, 略過版本="", 開網址=None, 逾時=逾時秒):
    """查一次，回傳 結果。永遠不丟例外（失敗是 狀態_失敗）。"""
    目前 = 目前版本 or version.版本
    try:
        最新, 內容, 網址 = 查最新(開網址, 逾時)
    except 查詢失敗 as e:
        return 結果(狀態_失敗, 原因=str(e))
    except Exception as e:                 # noqa: BLE001  沒料到的錯誤也不能影響程式
        return 結果(狀態_失敗, 原因=f"未預期的錯誤（{type(e).__name__}）")
    if not 較新(最新, 目前):
        return 結果(狀態_最新, 最新, 內容, 網址)
    if 略過版本 and 乾淨版本字(略過版本) == 最新:
        return 結果(狀態_略過, 最新, 內容, 網址)
    return 結果(狀態_新版, 最新, 內容, 網址)


def 寫紀錄(文字):
    """寫一行到 logs\\更新檢查紀錄.txt；寫不進去不影響程式。"""
    try:
        os.makedirs(app_paths.日誌資料夾(), exist_ok=True)
        with open(app_paths.更新檢查紀錄檔(), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {文字}\n")
    except OSError:
        pass


def 紀錄字(結):
    if 結.狀態 == 狀態_失敗:
        return f"檢查更新失敗，已略過：{結.原因}"
    if 結.狀態 == 狀態_新版:
        return f"有新版 {結.版本}（目前 {version.版本}）"
    if 結.狀態 == 狀態_略過:
        return f"有新版 {結.版本}，但使用者已略過這個版本"
    return f"已是最新（目前 {version.版本}，GitHub 最新 {結.版本}）"


def 截斷內容(字, 上限=內容上限):
    字 = (字 or "").strip().replace("\r\n", "\n")
    if not 字:
        return "（這個版本沒有附更新內容）"
    return 字 if len(字) <= 上限 else 字[:上限].rstrip() + "…"


# ---------- 背景執行緒 ----------
class 更新檢查器(QObject):
    """開始() 後在背景查；只有「有新版」才送出 有新版 訊號（回到主執行緒），其他結果只寫 log。"""
    有新版 = Signal(object)

    def __init__(self, 父=None, 開網址=None, 目前版本=None, 讀略過=None):
        super().__init__(父)
        self._開網址 = 開網址
        self._目前版本 = 目前版本
        self._讀略過 = 讀略過 or ui_state.讀略過版本
        self.執行緒 = None

    def 開始(self):
        self.執行緒 = threading.Thread(target=self._跑, name="檢查更新", daemon=True)
        self.執行緒.start()

    def _跑(self):
        try:
            結 = 檢查(self._目前版本, self._讀略過(), self._開網址)
            寫紀錄(紀錄字(結))
            if 結.狀態 == 狀態_新版:
                self.有新版.emit(結)
        except Exception as e:                 # noqa: BLE001  背景執行緒的任何問題都不能冒出來
            寫紀錄(f"檢查更新失敗，已略過：未預期的錯誤（{type(e).__name__}）")


# ---------- 視窗 ----------
class 更新視窗(QDialog):
    """有新版時的通知：新版本號、更新內容、「前往下載」「稍後」「略過這個版本」。不擋住主畫面（用 show，不是 exec）。"""

    def __init__(self, 結, 父=None):
        super().__init__(父)
        self.結 = 結
        self.選擇 = "稍後"          # 前往下載／稍後／略過（直接關視窗等於稍後）
        self.setWindowTitle(f"{version.產品名} 有新版本")
        self.setMinimumWidth(440)
        版 = QVBoxLayout(self)
        版.setContentsMargins(20, 18, 20, 16)
        版.setSpacing(10)
        self.標題字 = QLabel(f"有新版本 v{結.版本} 可以下載（你目前是 {version.版本字()}）")
        self.標題字.setWordWrap(True)
        self.標題字.setStyleSheet("font-weight: 700; font-size: 15px;")
        版.addWidget(self.標題字)
        小標 = QLabel("更新內容：")
        小標.setObjectName("小標")
        版.addWidget(小標)
        self.內容框 = QPlainTextEdit()
        self.內容框.setReadOnly(True)
        self.內容框.setPlainText(截斷內容(結.內容))
        self.內容框.setMinimumHeight(140)
        版.addWidget(self.內容框)
        註 = QLabel("只會通知你，不會自動下載或安裝。")
        註.setObjectName("小標")
        版.addWidget(註)
        列 = QHBoxLayout()
        列.addStretch(1)
        self.略過鈕 = QPushButton("略過這個版本")
        self.稍後鈕 = QPushButton("稍後")
        self.下載鈕 = QPushButton("前往下載")
        self.下載鈕.setObjectName("開始")
        for 鈕 in (self.略過鈕, self.稍後鈕, self.下載鈕):
            鈕.setCursor(Qt.PointingHandCursor)
            列.addWidget(鈕)
        版.addLayout(列)
        self.下載鈕.clicked.connect(self.前往下載)
        self.稍後鈕.clicked.connect(self.稍後)
        self.略過鈕.clicked.connect(self.略過)

    def 前往下載(self):
        self.選擇 = "前往下載"
        QDesktopServices.openUrl(QUrl(self.結.網址))
        self.accept()

    def 稍後(self):
        self.選擇 = "稍後"
        self.reject()

    def 略過(self):
        self.選擇 = "略過"
        ui_state.存略過版本(self.結.版本)
        self.reject()
