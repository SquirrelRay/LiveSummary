# 啟動面板（新介面第二階段第二步）：開程式時出現的小視窗，取代主控台當作入口。
#   內容：網址欄（重用主控台的網址紀錄下拉清單：最近、釘選、刪除）、語言選單、開始按鈕、右上角齒輪（打開設定框）、✕（收起）。
#   深色、圓角、無邊框，開在膠囊所在螢幕的中間；拖曳空白處可以移動。
#   按「開始」：和主控台的「開始」完全相同（直接把網址、語言填進主控台再呼叫主控台的 開始）。
#     成功開始擷取（收到 files 事件）→ 啟動面板收起，並套用上次使用的版面（沒有就套用預設版面），讓面板出現。
#     網址錯誤、頻道沒開播等錯誤 → 在啟動面板裡用中文顯示，不收起。
# 啟動面板不另外跑引擎，也不改主控台的行為。
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QComboBox, QHBoxLayout, QVBoxLayout

import live_topics

語言選項 = [("自動偵測", "auto"), ("中文", "zh"), ("日文", "ja"), ("英文", "en"), ("韓文", "ko")]
寬 = 480
VOD提示 = "目前只支援直播網址，直播檔（VOD）之後才會支援"


class 啟動面板(QWidget):
    def __init__(self, 台, 網址欄類, 網址清單類):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Window)
        self.台 = 台
        self.setWindowTitle("直播摘要")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(寬)
        self.等待中 = False             # 按了開始、還沒確定成功或失敗
        self.測試檔案 = None            # 測試專用：設成文字稿路徑時，改用「文字稿重播」開始（使用者介面不會用到）

        版 = QVBoxLayout(self)
        版.setContentsMargins(22, 16, 16, 20)
        版.setSpacing(12)
        頭 = QHBoxLayout()
        標題 = QLabel("直播摘要")
        標題.setObjectName("標題")
        頭.addWidget(標題)
        頭.addStretch(1)
        self.齒輪 = QPushButton("⚙")
        self.齒輪.setToolTip("設定")
        self.關鈕 = QPushButton("✕")
        self.關鈕.setToolTip("收起（之後可從膠囊選單「開始…」打開）")
        for 鈕 in (self.齒輪, self.關鈕):
            鈕.setObjectName("圖鈕")
            鈕.setCursor(Qt.PointingHandCursor)
            鈕.setFocusPolicy(Qt.NoFocus)
            頭.addWidget(鈕)
        self.齒輪.setStyleSheet("font-size: 16px;")
        self.齒輪.clicked.connect(台.開設定框)
        self.關鈕.clicked.connect(self.hide)
        版.addLayout(頭)

        self.網址框 = 網址欄類()
        self.網址框.setPlaceholderText("直播網址，例如 https://www.twitch.tv/頻道名稱")
        self.網址框.returnPressed.connect(self.開始)
        版.addWidget(self.網址框)

        列 = QHBoxLayout()
        列.setSpacing(8)
        語言標 = QLabel("語言")
        語言標.setObjectName("淡")
        self.語言選 = QComboBox()
        for 名, 值 in 語言選項:
            self.語言選.addItem(名, 值)
        預設語言 = live_topics.載入設定({})[0]["language"]        # config.json 的語言（預設「自動」）
        self.語言選.setCurrentIndex(max(0, self.語言選.findData(預設語言)))
        self.開始鈕 = QPushButton("開始")
        self.開始鈕.setObjectName("開始")
        self.開始鈕.setCursor(Qt.PointingHandCursor)
        self.開始鈕.setMinimumWidth(110)
        self.開始鈕.clicked.connect(self.開始)
        列.addWidget(語言標)
        列.addWidget(self.語言選)
        列.addStretch(1)
        列.addWidget(self.開始鈕)
        版.addLayout(列)

        self.狀態字 = QLabel("")
        self.狀態字.setWordWrap(True)
        self.狀態字.hide()
        版.addWidget(self.狀態字)
        版.addStretch(1)              # 網址清單撐高視窗時，多出來的高度放在最下面（上面的元件不動）

        # 網址紀錄下拉清單：直接重用主控台的（同一份 網址紀錄.json）。清單浮在啟動面板裡，顯示時把面板往下撐高。
        self.網址清單 = 網址清單類(self, 台.網址紀錄, self.網址框)
        self.網址清單.installEventFilter(self)
        原重建 = self.網址清單.重建

        def 重建():
            self.setFixedHeight(self._基本高() + 400)         # 先撐高，清單才有空間（清單用視窗高度決定能多高）
            原重建()
            self.setFixedHeight(max(self._基本高(), self.網址清單.y() + self.網址清單.height() + 16))
        self.網址清單.重建 = 重建
        self.網址清單.選了.connect(lambda _: self.網址框.setFocus())
        台.橋.收到.connect(self.收事件)
        self.setFixedHeight(self._基本高())

    # ---------- 外觀 ----------
    def _基本高(self):
        self.layout().activate()
        return self.layout().sizeHint().height()

    def _回基本高(self):
        self.setFixedHeight(self._基本高())

    def eventFilter(self, 物, e):
        if 物 is self.網址清單 and e.type() == QEvent.Hide:
            self._回基本高()
        return False

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor("#2a2e3a"))
        p.setBrush(QColor("#161920"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.windowHandle():     # 拖曳空白處移動
            self.windowHandle().startSystemMove()

    # ---------- 顯示 ----------
    def 顯示(self):
        """打開啟動面板（直播中不會打開），放在膠囊所在螢幕的正中間。"""
        if self.台.執行中() or self.台.結束中:
            return
        if not self.等待中:
            self.設狀態("")
            self.開始鈕.setEnabled(True)
        if not self.isVisible():
            self._回基本高()
            螢 = self.台.膠囊.膠囊._所在螢幕()
            self.move(螢.center().x() - self.width() // 2, 螢.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        self.網址框.setFocus()

    def 設狀態(self, 字, 錯誤=False):
        self.狀態字.setText(字)
        self.狀態字.setStyleSheet(f"color: {'#ff5c7a' if 錯誤 else '#8a91a5'};")
        self.狀態字.setVisible(bool(字))
        if not self.網址清單.isVisible():
            self._回基本高()

    # ---------- 開始 ----------
    def 開始(self):
        台 = self.台
        if self.等待中 or 台.執行中() or 台.結束中:
            return
        self.網址清單.hide()
        網址 = self.網址框.text().strip()
        if not 網址 and not self.測試檔案:
            return self.設狀態("請先輸入直播網址，例如 https://www.twitch.tv/頻道名稱", 錯誤=True)
        if not self.測試檔案 and "/videos/" in 網址.lower():
            return self.設狀態(VOD提示, 錯誤=True)
        # 和主控台的「開始」完全相同：把網址、語言填進主控台，再呼叫主控台的 開始
        if self.測試檔案:
            台.檔案鈕.setChecked(True)
            台.檔案框.setText(self.測試檔案)
            台.速度選.setCurrentIndex(max(0, 台.速度選.findData(0)))
        else:
            台.直播鈕.setChecked(True)
            台.網址框.setText(網址)
        台._切換來源()
        台.語言選.setCurrentIndex(max(0, 台.語言選.findData(self.語言選.currentData())))
        self.等待中 = True
        self.開始鈕.setEnabled(False)
        self.設狀態("正在檢查直播…" if not self.測試檔案 else "開始重播文字稿…")
        台.開始()
        if not 台.執行中():           # 主控台在開始前就擋下來（例如找不到檔案）
            self.等待中 = False
            self.開始鈕.setEnabled(True)
            self.設狀態("無法開始，請確認網址後再試一次。", 錯誤=True)

    def 收事件(self, 種類, 內容):
        if not self.等待中:
            return
        if 種類 == "files":                   # 成功開始擷取：收起，套用版面讓面板出現
            self.等待中 = False
            self.開始鈕.setEnabled(True)
            self.設狀態("")
            self.hide()
            self.台.面板.套用上次或預設()
        elif 種類 == "error":                 # 網址錯誤、頻道沒開播、金鑰問題等：留在啟動面板顯示
            self.等待中 = False
            self.開始鈕.setEnabled(True)
            self.設狀態(內容.get("訊息") or "發生錯誤，請再試一次。", 錯誤=True)
            if not self.isVisible():
                self.顯示()
