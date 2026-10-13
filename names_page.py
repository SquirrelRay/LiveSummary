# 名詞清單（膠囊／系統匣選單的「名詞清單」、啟動面板網址欄下方的「名詞清單」按鈕）：
#   讓不會打日文的使用者在介面上訂正這位直播主詞庫裡的名字寫法。原文由程式帶入（不能改），使用者只改「顯示寫法」
#   （中文、羅馬拼音、英文都可以）；改了就變成手動，從下一輪摘要開始照新寫法，已經顯示的摘要不回頭改。
#   哪位直播主：直播中＝這一場的頻道（直接改引擎正在用的詞庫物件）；待命＝啟動面板網址欄的頻道。
#   YouTube：詞庫用頻道 ID（檔名 YT_頻道ID.txt）；網址欄是 YouTube 網址時在背景查頻道 ID，查詢中按鈕停用並顯示「查詢頻道中…」。
#   每個動作都立刻存檔（glossary 的鎖與安全寫法；只動那一行，記事本同時改的其他行不會被蓋掉）。
#   「刪除」＝把那一行標成「忽略」：不會再被話題摘要自動加回來，也不會被上網查證。
#   視窗開著時每秒看一次詞庫有沒有變（新候選、上網查證結果、記事本存檔），有變就重新整理；
#   使用者正在編輯某一格時先不整理，等編輯完再更新，不會清掉正在打的字。
import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import glossary
import platforms

欄名們 = ("原文", "顯示寫法", "來源", "這一場", "網址")
原文欄, 寫法欄, 來源欄, 這場欄, 網址欄 = range(5)
更新毫秒 = 1000
查詢中 = "查詢頻道中…"
查不到原因們 = {"連線": "查不到頻道：連不上 YouTube，請確認網路後再試",
           "找不到": "查不到這個 YouTube 頻道，請確認網址",
           "格式": "查不到頻道：這個網址看不出是哪個頻道（影片不存在，或 YouTube 頁面改版）"}
重查秒 = 30                 # 查不到的結果過這麼久，網址欄再變動時重新查（網路恢復後不必重開程式）


def YouTube詞庫名(頻道ID):
    """YouTube 直播主的詞庫名（檔名 YT_頻道ID.txt）：頻道 ID 不會變，所有網址格式都對得上同一份。"""
    return "YT_" + 頻道ID


class YouTube頻道查詢(QObject):
    """名詞清單按鈕用：YouTube 網址在背景查頻道 ID（stream_info.查YouTube詳細），結果依網址的查詢鍵快取。
    查完送出 查完 訊號（在主執行緒收到），按鈕與選單重新判斷。"""
    查完 = Signal()

    def __init__(self, 查=None):
        super().__init__()
        self._查 = 查             # 測試換成假的；None = stream_info.查YouTube詳細
        self._結果 = {}           # 查詢鍵 -> ("查詢中", None) / ("查到", 資訊) / ("查不到", (原因, 時刻))
        self._鎖 = threading.Lock()

    def 狀態(self, 資):
        """回傳 ("查詢中", None)／("查到", 資訊)／("查不到", 原因代碼)；還沒查過就開始在背景查。"""
        鍵 = 資.查詢鍵
        with self._鎖:
            狀, 值 = self._結果.get(鍵, (None, None))
            if 狀 == "查不到" and time.time() - 值[1] < 重查秒:
                return 狀, 值[0]
            if 狀 in ("查詢中", "查到"):
                return 狀, 值
            self._結果[鍵] = ("查詢中", None)
        threading.Thread(target=self._跑, args=(鍵, 資), daemon=True).start()
        return "查詢中", None

    def _跑(self, 鍵, 資):
        try:
            if self._查 is not None:
                資訊, 原因 = self._查(資)
            else:
                import stream_info
                資訊, 原因 = stream_info.查YouTube詳細(platforms.觀看頁網址(資))
        except Exception:        # noqa: BLE001  查詢本身不應出錯；萬一出錯也當作查不到
            資訊, 原因 = None, "格式"
        with self._鎖:
            self._結果[鍵] = ("查到", 資訊) if 資訊 and 資訊.get("頻道ID") else ("查不到", (原因 or "格式", time.time()))
        self.查完.emit()

    def 已知(self, 詞庫名):
        """詞庫名（YT_頻道ID）→ 查到過的資訊；沒有回傳 None。"""
        with self._鎖:
            for 狀, 值 in self._結果.values():
                if 狀 == "查到" and YouTube詞庫名(值["頻道ID"]) == 詞庫名:
                    return 值
        return None


_查詢 = None


def 頻道查詢():
    """全程式共用一個 YouTube 頻道查詢（第一次用到才建立，要在 QApplication 之後）。"""
    global _查詢
    if _查詢 is None:
        _查詢 = YouTube頻道查詢()
    return _查詢


def 頻道(網址):
    """網址欄的字 → (詞庫名, "")；看不出是哪位直播主 → (None, 白話原因)。
    Twitch：詞庫名＝頻道名稱。YouTube：詞庫名＝YT_頻道ID；頻道 ID 要上網查，查詢中回傳 (None, 查詢中)，查完送出 頻道查詢().查完。"""
    網址 = (網址 or "").strip()
    if not 網址:
        return None, "請先在啟動面板輸入 Twitch 頻道網址或 YouTube 直播網址"
    資 = platforms.判斷(網址)
    if not 資.支援:
        if not 資.平台:
            return None, "這不是 Twitch 頻道網址或 YouTube 直播網址（例如 https://www.twitch.tv/頻道名稱 或 https://www.youtube.com/watch?v=影片代碼）"
        return None, 資.原因
    if 資.平台 == platforms.TWITCH:
        return 資.頻道, ""
    狀, 值 = 頻道查詢().狀態(資)
    if 狀 == "查到":
        return YouTube詞庫名(值["頻道ID"]), ""
    if 狀 == "查詢中":
        return None, 查詢中
    return None, 查不到原因們.get(值, 查不到原因們["格式"])


def 顯示名(詞庫名):
    """按鈕旁邊與詞庫檔開頭用的直播主名稱：YouTube 是「名稱（@帳號）」，Twitch 就是頻道名稱。"""
    資訊 = 頻道查詢().已知(詞庫名) if 詞庫名 and 詞庫名.startswith("YT_") else None
    if not 資訊:
        return 詞庫名
    名 = 資訊.get("直播主") or 資訊["頻道ID"]
    return f"{名}（{資訊['帳號']}）" if 資訊.get("帳號") else 名


def 詞庫標示(詞庫名):
    """詞庫檔開頭「直播主專有名詞詞庫：」後面寫的字：YouTube 加上頻道 ID，之後用記事本也找得到是哪個頻道。"""
    名 = 顯示名(詞庫名)
    return 名 if 名 == 詞庫名 else f"{名}，YouTube 頻道 {詞庫名[3:]}"


def 來源字(e):
    if e.來源 == "手動":
        return "你填的"
    if e.來源 == "上網":
        return "上網查到"
    return "自動找到・上網查無" if e.已查過() else "自動找到・未確認"


def 確認(父, 標題, 文字):
    """跳出「確定／取消」確認框，回傳 True = 確定。（測試時可以換掉）"""
    框 = QMessageBox(QMessageBox.Question, 標題, 文字, QMessageBox.Yes | QMessageBox.No, 父)
    框.button(QMessageBox.Yes).setText("確定")
    框.button(QMessageBox.No).setText("取消")
    框.setDefaultButton(QMessageBox.No)
    return 框.exec() == QMessageBox.Yes


def 用記事本打開(路徑):
    """給進階使用者的小連結：用 Windows 的「編輯」開啟 .txt（預設就是記事本）。（測試時可以換掉）"""
    os.startfile(路徑, "edit")       # noqa: S606 路徑是程式自己組的詞庫檔


class 名詞清單框(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Window)
        self.setObjectName("根")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("名詞清單")
        self.resize(820, 600)
        self.詞庫 = None
        self.本場 = False           # True＝直播中，改的是引擎正在用的詞庫物件
        self.列們 = []              # 表格每一列對應的條目
        self._簽名 = None           # 上次整理時詞庫的樣子（版本、檔案修改時間、這一場出現數）
        self._待更新 = False        # 編輯中有變動：編輯完再整理
        self._填表中 = False

        版 = QVBoxLayout(self)
        版.setContentsMargins(16, 16, 16, 16)
        版.setSpacing(12)
        框 = QFrame()
        框.setObjectName("卡片")
        內 = QVBoxLayout(框)
        內.setContentsMargins(16, 12, 16, 14)
        內.setSpacing(8)
        self.標題 = QLabel("名詞清單")
        self.標題.setStyleSheet("font-weight: 700; font-size: 15px;")
        內.addWidget(self.標題)
        說明 = QLabel("原文由程式自動帶入，你只要改「顯示寫法」（雙擊那一格）：可以填中文，也可以填羅馬拼音或英文。"
                    "改了就變成「你填的」，從下一輪摘要開始照這個寫法；已經顯示的摘要不會改。")
        說明.setObjectName("小標")
        說明.setWordWrap(True)
        內.addWidget(說明)

        self.表 = QTableWidget(0, len(欄名們))
        self.表.setHorizontalHeaderLabels(欄名們)
        self.表.verticalHeader().setVisible(False)
        self.表.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.表.setSelectionMode(QAbstractItemView.SingleSelection)
        self.表.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                               | QAbstractItemView.SelectedClicked)
        頭 = self.表.horizontalHeader()
        for c, 模式 in ((原文欄, QHeaderView.Stretch), (寫法欄, QHeaderView.Stretch), (來源欄, QHeaderView.ResizeToContents),
                      (這場欄, QHeaderView.ResizeToContents), (網址欄, QHeaderView.ResizeToContents)):
            頭.setSectionResizeMode(c, 模式)
        self.表.horizontalHeaderItem(這場欄).setToolTip("● ＝這一場的語音稿裡出現過（直播中才會標示）")
        self.表.itemChanged.connect(self._格子改了)
        self.表.itemSelectionChanged.connect(self._更新按鈕)
        內.addWidget(self.表, 1)

        鈕列 = QHBoxLayout()
        self.確認鈕 = QPushButton("確認寫法")
        self.確認鈕.setToolTip("寫法沒問題：不用改字，直接變成「你填的」，之後每一場都會用")
        self.刪除鈕 = QPushButton("刪除")
        self.刪除鈕.setToolTip("不要這個名詞：之後不會再被自動加回來")
        self.整理鈕 = QPushButton("重新整理")
        for 鈕 in (self.確認鈕, self.刪除鈕, self.整理鈕):
            鈕.setCursor(Qt.PointingHandCursor)
        self.確認鈕.clicked.connect(self.確認選取)
        self.刪除鈕.clicked.connect(self.刪除選取)
        self.整理鈕.clicked.connect(lambda: self.重新整理(強制=True))
        鈕列.addWidget(self.確認鈕)
        鈕列.addWidget(self.刪除鈕)
        鈕列.addStretch(1)
        鈕列.addWidget(self.整理鈕)
        內.addLayout(鈕列)
        版.addWidget(框, 1)

        新框 = QFrame()
        新框.setObjectName("卡片")
        新版 = QVBoxLayout(新框)
        新版.setContentsMargins(16, 12, 16, 14)
        新標 = QLabel("新增名詞")
        新標.setStyleSheet("font-weight: 700; font-size: 15px;")
        新版.addWidget(新標)
        新列 = QHBoxLayout()
        self.新寫法 = QLineEdit()
        self.新寫法.setPlaceholderText("顯示寫法（必填，例如 曼太郎 或 Mantarou）")
        self.新原文 = QLineEdit()
        self.新原文.setPlaceholderText("原文（選填，知道的話可以貼上，例如 マン太郎）")
        self.新增鈕 = QPushButton("新增")
        self.新增鈕.setObjectName("開始")
        self.新增鈕.setCursor(Qt.PointingHandCursor)
        self.新增鈕.clicked.connect(self.新增)
        self.新原文.returnPressed.connect(self.新增)
        self.新寫法.returnPressed.connect(self.新增)
        新列.addWidget(self.新寫法, 3)
        新列.addWidget(self.新原文, 3)
        新列.addWidget(self.新增鈕)
        新版.addLayout(新列)
        版.addWidget(新框)

        底列 = QHBoxLayout()
        self.狀態字 = QLabel("")
        self.狀態字.setWordWrap(True)
        底列.addWidget(self.狀態字, 1)
        self.記事本 = QLabel("<a href='#' style='color:#8a91a5;'>用記事本打開</a>")
        self.記事本.setObjectName("小標")
        self.記事本.setToolTip("進階：直接編輯詞庫檔")
        self.記事本.linkActivated.connect(lambda _: self.打開記事本())
        底列.addWidget(self.記事本)
        版.addLayout(底列)

        self.計時器 = QTimer(self)
        self.計時器.timeout.connect(self._看變化)

    # ---------- 打開 ----------
    def 打開(self, 詞庫, 本場=False, 螢幕範圍=None):
        """詞庫：要編輯的 glossary.詞庫 物件。本場：True＝直播中引擎正在用的那一個（改了下一輪就生效）。"""
        換了 = self.詞庫 is not 詞庫
        self.詞庫, self.本場 = 詞庫, 本場
        self.標題.setText(f"名詞清單：{詞庫.直播主}")
        self.setWindowTitle(f"名詞清單：{詞庫.直播主}")
        if 換了:
            self.新寫法.clear()
            self.新原文.clear()
            self.狀態字.setText("")
        self.重新整理(強制=True)
        if not self.isVisible() and 螢幕範圍 is not None:
            self.resize(min(820, 螢幕範圍.width() - 40), min(600, 螢幕範圍.height() - 40))
            self.move(螢幕範圍.center() - self.rect().center())
        self.計時器.start(更新毫秒)
        self.show()
        self.raise_()
        self.activateWindow()

    def hideEvent(self, e):
        self.計時器.stop()
        super().hideEvent(e)

    # ---------- 自動更新 ----------
    def 編輯中(self):
        return self.表.state() == QAbstractItemView.EditingState

    def _簽名值(self):
        try:
            時間 = os.path.getmtime(self.詞庫.路徑)
        except OSError:
            時間 = None
        return self.詞庫.版本, 時間, self.詞庫.出現數()

    def _看變化(self):
        """每秒一次：直播剛載入詞庫就換成引擎的那一個；詞庫有變（新候選、上網查證、記事本）就重新整理。"""
        if self.詞庫 is None:
            return
        本 = glossary.本場詞庫
        if (本 is not None and 本 is not self.詞庫
                and os.path.normcase(os.path.abspath(本.路徑)) == os.path.normcase(os.path.abspath(self.詞庫.路徑))):
            self.詞庫, self.本場, self._簽名 = 本, True, None
        if self._待更新 or self._簽名值() != self._簽名:
            self.重新整理()

    def 重新整理(self, 強制=False):
        """重讀詞庫填表。正在編輯某一格時不動表格（記下來，編輯完的下一次檢查再整理）。"""
        if self.詞庫 is None:
            return
        if self.編輯中():
            self._待更新 = True
            return
        self._待更新 = False
        try:
            條目們 = self.詞庫.清單()
        except glossary.詞庫錯誤 as e:
            條目們 = []
            self._提示(str(e), 錯=True)
        self._簽名 = self._簽名值()
        if not 強制 and self._同內容(條目們):
            return
        選的 = self._選取條目()
        選鍵 = 選的.鍵() if 選的 else None
        捲 = self.表.verticalScrollBar().value()
        self._填表中 = True
        try:
            self.表.setRowCount(len(條目們))
            for r, e in enumerate(條目們):
                self._填列(r, e)
        finally:
            self._填表中 = False
        self.列們 = 條目們
        if 選鍵 is not None:
            for r, e in enumerate(條目們):
                if e.鍵() == 選鍵:
                    self.表.selectRow(r)
                    break
        self.表.verticalScrollBar().setValue(捲)
        self._更新按鈕()

    def _同內容(self, 條目們):
        def 樣(es):
            return [(e.原行, self.本場 and self.詞庫.出現過(e)) for e in es]
        return 樣(條目們) == 樣(self.列們) and self.表.rowCount() == len(條目們)

    def _填列(self, r, e):
        def 唯讀(字, 提示=""):
            item = QTableWidgetItem(字)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if 提示:
                item.setToolTip(提示)
            return item
        原 = 唯讀(e.原文 or "—", "" if e.原文 else "這個名詞沒有原文（例如中文名字），只用顯示寫法比對")
        self.表.setItem(r, 原文欄, 原)
        寫 = QTableWidgetItem(e.寫法)
        寫.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        寫.setToolTip("雙擊修改：中文、羅馬拼音、英文都可以")
        self.表.setItem(r, 寫法欄, 寫)
        self.表.setItem(r, 來源欄, 唯讀(來源字(e)))
        self.表.setItem(r, 這場欄, 唯讀("●" if self.本場 and self.詞庫.出現過(e) else ""))
        網址 = e.網址()
        self.表.setItem(r, 網址欄, 唯讀("", 網址))
        if 網址:
            連結 = QLabel(f"<a href='{網址}' style='color:#8b6cff;'>打開來源</a>")
            連結.setOpenExternalLinks(True)
            連結.setToolTip(網址)
            連結.setContentsMargins(6, 0, 6, 0)
            self.表.setCellWidget(r, 網址欄, 連結)
        else:
            self.表.removeCellWidget(r, 網址欄)

    # ---------- 操作 ----------
    def _選取條目(self):
        列們 = self.表.selectionModel().selectedRows() if self.表.selectionModel() else []
        if not 列們 or 列們[0].row() >= len(self.列們):
            return None
        return self.列們[列們[0].row()]

    def _更新按鈕(self):
        e = self._選取條目()
        self.確認鈕.setEnabled(bool(e) and e.來源 != "手動")
        self.刪除鈕.setEnabled(bool(e))

    def _做(self, 動作, 成功字):
        try:
            動作()
        except glossary.詞庫錯誤 as e:
            self._提示(str(e), 錯=True)
        except OSError as e:
            self._提示(f"存檔失敗：{e}", 錯=True)
        else:
            self._提示(成功字 + ("，下一輪摘要開始使用" if self.本場 else "，下次開始時使用"))
        self.重新整理(強制=True)

    def _格子改了(self, item):
        if self._填表中 or item.column() != 寫法欄 or item.row() >= len(self.列們):
            return
        e = self.列們[item.row()]
        新 = item.text()
        if 新.strip() == e.寫法:
            return
        # 編輯框還沒完全關掉：等這一輪事件跑完再存檔、整理表格
        QTimer.singleShot(0, lambda: self._做(lambda: self.詞庫.改寫法(e, 新),
                                              f"已存檔：「{e.原文 or e.寫法}」改寫成「{新.strip()}」"))

    def 確認選取(self):
        e = self._選取條目()
        if e is None or e.來源 == "手動":
            return
        self._做(lambda: self.詞庫.確認(e), f"已確認「{e.寫法}」")

    def 刪除選取(self):
        e = self._選取條目()
        if e is None:
            return
        if not 確認(self, "刪除名詞", f"確定要刪除「{e.顯示()}」嗎？\n刪除後這個名詞不會再被自動加回來。"):
            return
        self._做(lambda: self.詞庫.忽略(e), f"已刪除「{e.寫法}」")

    def 新增(self):
        寫法, 原文 = self.新寫法.text(), self.新原文.text()
        if not 寫法.strip():
            self._提示("請先填顯示寫法", 錯=True)
            self.新寫法.setFocus()
            return
        成功 = []

        def 動作():
            self.詞庫.新增(寫法, 原文)
            成功.append(True)
        self._做(動作, f"已新增「{寫法.strip()}」")
        if 成功:
            self.新寫法.clear()
            self.新原文.clear()

    def 打開記事本(self):
        路徑 = self.詞庫.路徑
        if not os.path.exists(路徑):
            glossary.安全寫入(路徑, glossary.檔頭.replace("{直播主}", self.詞庫.標示))
        用記事本打開(路徑)

    def _提示(self, 字, 錯=False):
        self.狀態字.setStyleSheet(f"color: {'#ff5c7a' if 錯 else '#3ecf8e'};")
        self.狀態字.setText(字)
