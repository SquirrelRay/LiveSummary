# 設定框（啟動面板的齒輪、膠囊／系統匣選單的「設定」）：功能開關、顯示上限、字幕速度段位、模型、存檔
# 按「儲存」才寫回 config.json（寫之前先備份成 config.backup.json）；
# config.json 裡已停用的舊欄位（overlay、hotkey_compact、translate_batch_seconds／translate_batch_lines）原樣保留。
# API 金鑰：輸入時遮蔽（眼睛按鈕可暫時顯示剛輸入的字）；存在這台電腦的認證管理員（api_key.py），不寫進 config.json。
#   「測試連線」成功才存、失敗絕不存；按「儲存」也會存；只輸入不按這兩顆就關掉，金鑰不會被存（和其他欄位一致）。
#   已存的金鑰永遠不會放回輸入框，只顯示白話狀態。
import os
import threading

from PySide6.QtCore import Qt, QObject, QEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QFrame, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox,
    QLineEdit, QGridLayout, QHBoxLayout, QVBoxLayout,
)

import api_key
import config
import cost_estimate
import llm
import subtitle_speed


def 小標(字):
    w = QLabel(字)
    w.setObjectName("淡")
    return w


class 滾輪過濾(QObject):
    """數字欄位、下拉選單：沒有點選（沒有取得焦點）時不吃滑鼠滾輪，改成捲動整個設定頁，避免捲頁面時誤改數值。"""

    def __init__(self, 捲動區):
        super().__init__(捲動區)
        self.捲動區 = 捲動區

    def eventFilter(self, 物, e):
        if e.type() == QEvent.Wheel and not 物.hasFocus():
            QApplication.sendEvent(self.捲動區.verticalScrollBar(), e)
            return True
        return False


class 設定頁(QScrollArea):
    _測試完成 = Signal(object)        # 測試連線的背景執行緒 → 介面執行緒

    def __init__(self, 主):
        super().__init__()
        self.主 = 主                 # 主控台（換內容方向、看是否執行中）
        self.背景測試 = True         # 測試連線放背景執行緒（測試時設 False 改成直接執行）
        self._測試完成.connect(self._測試連線完成)
        self._載入中 = False
        self.下次標們 = []           # 「下次開始生效」標籤
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        內 = QWidget()
        版 = QVBoxLayout(內)
        版.setContentsMargins(16, 16, 16, 16)
        版.setSpacing(12)

        上 = QHBoxLayout()
        說明 = QLabel("按「儲存」才會套用並記住這些設定（會先備份舊的設定）。")
        說明.setObjectName("小標")
        說明.setWordWrap(True)
        上.addWidget(說明, 1)
        self.還原鈕 = QPushButton("還原預設值")
        self.儲存鈕 = QPushButton("儲存")
        self.儲存鈕.setObjectName("開始")
        for 鈕 in (self.還原鈕, self.儲存鈕):
            鈕.setCursor(Qt.PointingHandCursor)
            上.addWidget(鈕)
        self.還原鈕.clicked.connect(self.還原預設)
        self.儲存鈕.clicked.connect(self.儲存)
        版.addLayout(上)
        self.狀態字 = QLabel("")
        self.狀態字.setWordWrap(True)
        版.addWidget(self.狀態字)

        版.addWidget(self._做一般區())
        版.addWidget(self._做費用區())
        版.addWidget(self._做存檔區())
        版.addStretch(1)
        self.setWidget(內)
        self._滾輪 = 滾輪過濾(self)
        for w in (w for w in 內.findChildren(QWidget) if isinstance(w, (QSpinBox, QComboBox))):
            w.setFocusPolicy(Qt.StrongFocus)      # 只有點選過才會有焦點（預設的 Wheel 會讓滾輪也能取得焦點）
            w.installEventFilter(self._滾輪)

    # ---------- 版面 ----------
    def _面板(self, 標題):
        框 = QFrame()
        框.setObjectName("卡片")
        外 = QVBoxLayout(框)
        外.setContentsMargins(16, 12, 16, 14)
        t = QLabel(標題)
        t.setStyleSheet("font-weight: 700; font-size: 15px;")
        外.addWidget(t)
        格 = QGridLayout()
        格.setHorizontalSpacing(12)
        格.setVerticalSpacing(8)
        格.setColumnStretch(1, 1)
        格.setColumnStretch(3, 1)
        外.addLayout(格)
        return 框, 格

    def _下次(self):
        w = QLabel("下次開始生效")
        w.setStyleSheet("color: #f5b84a; font-size: 12px;")
        w.hide()
        self.下次標們.append(w)
        return w

    def _做一般區(self):
        框, 格 = self._面板("功能與模型")
        self.欄 = {}
        e = self.欄
        e["subtitle_mode"] = QComboBox()
        for 名, 值 in (("自動（中文用原文，其他語言翻譯）", "auto"), ("原文", "original"), ("翻譯成繁中", "translate")):
            e["subtitle_mode"].addItem(名, 值)
        e["chat"] = QCheckBox("抓聊天室（直播網址模式）")
        e["minute_summary"] = QCheckBox("分鐘摘要")
        e["fix_with_chat"] = QCheckBox("用聊天室參考詞修正專有名詞")
        e["summary_thinking"] = QCheckBox("摘要使用延伸思考：較準但較貴")
        e["chat_translate"] = QCheckBox("聊天室翻譯：外語直播時把留言翻成繁體中文（聊天室面板開著才翻，另外計費）")
        e["web_verify"] = QCheckBox("上網查證詞庫的候選名詞：查到台灣通行寫法就寫回詞庫並附來源網址（只支援 Claude，另外計費）")
        e["web_verify"].setToolTip("每場只查這一場新加入的候選，最多 10 個；查無的標「已查」不再重查。搜尋每次 0.01 美元＋token")
        e["chat_translate_max_per_min"] = QSpinBox()
        e["chat_translate_max_per_min"].setRange(1, 600)
        e["chat_translate_max_per_min"].setSuffix(" 則")
        e["chat_translate_max_per_min"].setToolTip("超過就平均抽樣，沒翻到的留言只顯示原文")
        for k in ("ui_max_transcript", "ui_max_chat", "ui_max_translation", "ui_max_summary"):
            e[k] = QSpinBox()
            e[k].setRange(10, 100000)
            e[k].setSuffix(" 則")
        e["newest_on_top"] = QComboBox()
        e["newest_on_top"].addItem("最下面", False)
        e["newest_on_top"].addItem("最上面", True)
        e["newest_on_top"].currentIndexChanged.connect(self._換方向)
        e["time_display"] = QComboBox()
        e["time_display"].addItem("直播時間（例如 1:23:45）", "stream")
        e["time_display"].addItem("幾分鐘前", "ago")
        e["time_display"].setToolTip("只影響分鐘摘要與話題摘要卡片；直播稿、逐句翻譯、聊天室一律顯示直播時間。抓不到開播時間時自動顯示幾分鐘前")
        e["minute_sentences"] = QSpinBox()
        e["minute_sentences"].setRange(1, 3)
        e["minute_sentences"].setSuffix(" 句")
        e["subtitle_speed"] = QComboBox()
        for 代碼 in subtitle_speed.代碼們:
            e["subtitle_speed"].addItem(subtitle_speed.取得(代碼)["名稱"], 代碼)
        e["subtitle_speed"].currentIndexChanged.connect(self._更新段位說明)
        e["subtitle_mode"].currentIndexChanged.connect(self._更新段位說明)
        for k in ("chat", "minute_summary", "summary_thinking", "chat_translate", "web_verify"):
            e[k].toggled.connect(self._更新段位說明)
        e["minute_sentences"].valueChanged.connect(self._更新段位說明)
        e["chat_translate_max_per_min"].valueChanged.connect(self._更新段位說明)
        self.段位說明 = QLabel()
        self.段位說明.setObjectName("小標")
        self.段位說明.setWordWrap(True)
        self._單價 = (config.出廠預設()["price_input"], config.出廠預設()["price_output"])   # 估算費用用的單價，載入時從 config.json 讀
        e["provider"] = QComboBox()
        e["provider"].addItem("Claude", "anthropic")
        e["provider"].addItem("OpenAI 相容服務", "openai_compatible")
        e["provider"].currentIndexChanged.connect(self._更新段位說明)       # 上網查證只支援 anthropic：費用表跟著變
        e["model"] = QLineEdit()
        self._做金鑰欄()
        e["provider"].currentIndexChanged.connect(lambda _: self._換服務())

        列 = 0

        def 加(名, w, 下次=False):
            nonlocal 列
            格.addWidget(小標(名), 列, 0)
            格.addWidget(w, 列, 1, 1, 2)
            if 下次:
                格.addWidget(self._下次(), 列, 3)
            列 += 1

        加("逐句字幕模式", e["subtitle_mode"], True)
        for k in ("chat", "minute_summary", "fix_with_chat", "summary_thinking", "web_verify"):
            加("", e[k], True)
        加("", e["chat_translate"])                 # 按「儲存」當場生效（膠囊選單也可以直接切換）
        加("聊天室翻譯每分鐘最多翻", e["chat_translate_max_per_min"], True)
        加("分鐘摘要句數", e["minute_sentences"], True)
        加("最新內容顯示在", e["newest_on_top"])
        加("摘要卡片的時間", e["time_display"])        # 按「儲存」當場生效（膠囊選單也可以直接切換）
        加("直播稿分頁最多顯示", e["ui_max_transcript"], True)
        加("聊天室分頁最多顯示", e["ui_max_chat"], True)
        加("逐句翻譯分頁最多顯示", e["ui_max_translation"], True)
        加("摘要分頁最多顯示（分鐘、話題各）", e["ui_max_summary"], True)
        加("字幕速度（預設）", e["subtitle_speed"], True)
        self.段位下次標 = self.下次標們[-1]
        格.addWidget(self.段位說明, 列, 1, 1, 3)
        列 += 1
        加("模型服務", e["provider"], True)
        加("模型名稱", e["model"], True)
        加("API 金鑰", self.金鑰列)
        for w in (self.金鑰狀態列, self.金鑰訊息, self.金鑰進階):
            格.addWidget(w, 列, 1, 1, 3)
            列 += 1
        return 框

    def _做金鑰欄(self):
        """金鑰輸入欄（遮蔽）＋眼睛＋測試連線＋清除；下面一行狀態與「如何取得金鑰」，再下面是測試結果與進階小字。"""
        self.金鑰欄 = QLineEdit()
        self.金鑰欄.setEchoMode(QLineEdit.Password)
        self.眼睛鈕 = QPushButton("👁")
        self.眼睛鈕.setCheckable(True)
        self.眼睛鈕.setToolTip("暫時顯示剛輸入的金鑰（再按一次遮起來）")
        self.眼睛鈕.toggled.connect(
            lambda 開: self.金鑰欄.setEchoMode(QLineEdit.Normal if 開 else QLineEdit.Password))
        self.測試鈕 = QPushButton("測試連線")
        self.測試鈕.setToolTip("只列出模型清單確認金鑰有效，不會產生費用；成功才會存起來")
        self.清除鈕 = QPushButton("清除")
        self.清除鈕.setToolTip("刪掉這台電腦儲存的這個服務的金鑰")
        self.測試鈕.clicked.connect(self.測試連線)
        self.清除鈕.clicked.connect(self.清除金鑰)
        self.金鑰列 = QWidget()
        橫 = QHBoxLayout(self.金鑰列)
        橫.setContentsMargins(0, 0, 0, 0)
        橫.setSpacing(6)
        橫.addWidget(self.金鑰欄, 1)
        for 鈕 in (self.眼睛鈕, self.測試鈕, self.清除鈕):
            鈕.setCursor(Qt.PointingHandCursor)
            橫.addWidget(鈕)
        self.金鑰字 = QLabel()               # 白話狀態：已儲存在這台電腦／使用系統環境變數／尚未設定
        self.取得連結 = QLabel()
        self.取得連結.setTextFormat(Qt.RichText)
        self.取得連結.setOpenExternalLinks(True)
        self.取得連結.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.金鑰狀態列 = QWidget()
        橫2 = QHBoxLayout(self.金鑰狀態列)
        橫2.setContentsMargins(0, 0, 0, 0)
        橫2.addWidget(self.金鑰字)
        橫2.addStretch(1)
        橫2.addWidget(self.取得連結)
        self.金鑰訊息 = QLabel("")             # 測試連線、清除、儲存金鑰的結果（白話，不含金鑰）
        self.金鑰訊息.setWordWrap(True)
        self.金鑰訊息.hide()
        self.金鑰進階 = QLabel("")             # 進階小字：也可以用系統環境變數
        self.金鑰進階.setObjectName("小標")
        self.金鑰進階.setWordWrap(True)
        self.金鑰進階.setStyleSheet("font-size: 11px;")

    def _做費用區(self):
        """每小時費用表：項目／每小時（估算）／受字幕段位影響／目前狀態，最後一列是合計。內容由 cost_estimate 算。"""
        框, 格 = self._面板("每小時費用（估算）")
        self.費用格 = QGridLayout()
        self.費用格.setHorizontalSpacing(16)
        self.費用格.setVerticalSpacing(6)
        self.費用格.setColumnStretch(3, 1)
        格.addLayout(self.費用格, 0, 0, 1, 4)
        self.費用註們 = []
        for i, 字 in enumerate(cost_estimate.備註們):
            註 = QLabel(字)
            註.setObjectName("小標")
            註.setWordWrap(True)
            self.費用註們.append(註)
            格.addWidget(註, 1 + i, 0, 1, 4)
        self.聊天註 = QLabel("")                   # 熱門台的聊天室翻譯有每分鐘上限封頂（金額依目前單價與上限）
        self.聊天註.setObjectName("小標")
        self.聊天註.setWordWrap(True)
        self.費用註們.append(self.聊天註)
        格.addWidget(self.聊天註, 1 + len(cost_estimate.備註們), 0, 1, 4)
        self.費用表 = []                 # 目前表格每一列的文字（測試與除錯用）
        return 框

    存檔項目 = (("save_summary", "摘要（分鐘摘要與話題摘要）"), ("save_transcript", "直播稿"),
              ("save_chat", "聊天室"), ("save_translation", "逐句翻譯"), ("save_audio", "音訊（每段一個 wav，段長依字幕速度 8～20 秒，檔案較大）"))

    def _做存檔區(self):
        """存檔：五個開關（預設全關）＋打開存檔資料夾。關掉的內容只顯示在畫面上，不寫檔。"""
        框, 格 = self._面板("存檔")
        說明 = QLabel("打開的項目才會存成檔案（存在專案資料夾）。關掉的內容只顯示在畫面上，超過顯示上限的較早內容會直接移除。")
        說明.setObjectName("小標")
        說明.setWordWrap(True)
        格.addWidget(說明, 0, 0, 1, 4)
        for i, (k, 名) in enumerate(self.存檔項目):
            self.欄[k] = QCheckBox(名)
            格.addWidget(self.欄[k], 1 + i, 0, 1, 3)
            格.addWidget(self._下次(), 1 + i, 3)
        self.資料夾鈕 = QPushButton("打開存檔資料夾")
        self.資料夾鈕.setCursor(Qt.PointingHandCursor)
        self.資料夾鈕.clicked.connect(self.打開資料夾)
        格.addWidget(self.資料夾鈕, 1 + len(self.存檔項目), 0, 1, 2)
        return 框

    def 打開資料夾(self):
        os.startfile(os.path.dirname(config.設定檔路徑))

    # ---------- 表單 ⇄ 設定 ----------
    def 載入(self, 設定=None):
        """把設定（config.載入設定 的格式）放進表單。不給就讀 config.json。"""
        現行 = config.目前設定()
        if 設定 is None:
            設定 = 現行
        self._單價 = (現行["price_input"], 現行["price_output"])     # 單價不在表單上：估算費用一律用 config.json 的單價（還原預設也一樣）
        self._載入中 = True
        try:
            e = self.欄
            for k, w in e.items():
                v = 設定[k]
                if isinstance(w, QCheckBox):
                    w.setChecked(v)
                elif isinstance(w, QComboBox):
                    w.setCurrentIndex(max(0, w.findData(v)))
                elif isinstance(w, QSpinBox):
                    w.setValue(int(v))
                elif isinstance(w, QLineEdit):
                    w.setText(str(v))
        finally:
            self._載入中 = False
        self._更新段位說明()
        self.更新金鑰()

    def _更新段位說明(self, *_):
        """字幕速度下方：延遲與準確度、分段與批次設定；並重算下方的每小時費用表。"""
        if "chat" not in self.欄 or "費用格" not in self.__dict__:      # 建構途中，表單還沒建完
            return
        代碼 = self.欄["subtitle_speed"].currentData()
        self.段位說明.setText(subtitle_speed.延遲準確度字(代碼) + chr(10) + subtitle_speed.批次文字(代碼))
        self._更新費用表()

    def _表單設定(self):
        """目前表單上的值（含還沒按儲存的）合成一份設定，費用表用它估算；語言不在表單上，取 config.json 的。"""
        e = self.欄
        return dict(config.目前設定(),
                    subtitle_mode=e["subtitle_mode"].currentData(), chat=e["chat"].isChecked(),
                    minute_summary=e["minute_summary"].isChecked(), summary_thinking=e["summary_thinking"].isChecked(),
                    minute_sentences=e["minute_sentences"].value(), price_input=self._單價[0], price_output=self._單價[1],
                    chat_translate=e["chat_translate"].isChecked(),
                    chat_translate_max_per_min=e["chat_translate_max_per_min"].value(),
                    web_verify=e["web_verify"].isChecked(), provider=e["provider"].currentData())

    def _更新費用表(self):
        代碼 = self.欄["subtitle_speed"].currentData()
        表單 = self._表單設定()
        結果 = cost_estimate.估算(表單, 代碼, self.主.面板.翻譯將啟用(), self.主.面板.聊天將開啟())
        self.聊天註.setText(cost_estimate.聊天備註(表單))
        格 = self.費用格
        while 格.count():
            w = 格.takeAt(0).widget()
            if w:
                w.deleteLater()
        列們 = cost_estimate.表格列們(結果)
        for r, 列 in enumerate(列們):
            for c, 字 in enumerate(列):
                w = QLabel(字)
                w.setObjectName("小標" if r == 0 else "")
                if r == len(列們) - 1:
                    w.setStyleSheet("font-weight: 700;")
                格.addWidget(w, r, c)
        self.費用表 = 列們

    # ---------- API 金鑰 ----------
    def _表單服務(self):
        """表單上選的模型服務 → (provider, 服務網址, 舊設定的環境變數名稱)。
        和記住的設定同一種服務就沿用它的網址與環境變數名稱；切到別種服務就用該家預設。"""
        現行 = config.目前設定()
        provider = self.欄["provider"].currentData()
        if provider == 現行["provider"]:
            return provider, 現行["base_url"], 現行["api_key_env"]
        return provider, "", api_key.出廠環境變數

    def 金鑰代號(self):
        provider, 網址, _ = self._表單服務()
        return api_key.服務代號(provider, 網址)

    def _換服務(self):
        if self._載入中:
            return
        self.金鑰欄.clear()                 # 打到一半的金鑰不跟著換到別的服務
        self.金鑰訊息.hide()
        self.更新金鑰()

    def 更新金鑰(self):
        """依表單上選的服務顯示：狀態（白話）、如何取得金鑰、進階小字；不需要金鑰的服務停用輸入欄。"""
        provider, 網址, 環境 = self._表單服務()
        代號 = api_key.服務代號(provider, 網址)
        狀態 = api_key.來源與金鑰(代號, 環境)[0]
        需要 = 狀態 != api_key.不需要
        名稱 = api_key.服務名稱(代號)
        self.金鑰字.setText(f"{名稱}：{api_key.狀態字們[狀態]}")
        self.金鑰字.setStyleSheet(f"color: {'#f5b84a' if 狀態 == api_key.未設定 else '#3ecf8e' if 需要 else '#8a91a5'};")
        for w in (self.金鑰欄, self.眼睛鈕, self.測試鈕):
            w.setEnabled(需要)
        self.清除鈕.setEnabled(api_key.讀取已儲存(代號) is not None)
        self.金鑰欄.setPlaceholderText(
            "" if not 需要 else "已儲存（要更換就貼上新的金鑰）" if 狀態 == api_key.已儲存 else f"貼上 {名稱} 的 API 金鑰")
        連結 = api_key.取得網址(代號)
        self.取得連結.setText(f"<a href='{連結}' style='color:#7aa2ff;'>如何取得金鑰</a>" if 連結 else "")
        self.取得連結.setToolTip(連結)
        self.取得連結.setVisible(bool(連結) and 需要)
        變數 = api_key.環境變數名(代號, 環境)
        self.金鑰進階.setText(f"進階：也可以用系統環境變數 {變數} 設定金鑰；這台電腦已儲存的金鑰優先。" if 變數 and 需要 else "")
        self.金鑰進階.setVisible(bool(self.金鑰進階.text()))

    def _金鑰提示(self, 字, 錯=False, 顏色=None):
        self.金鑰訊息.setStyleSheet(f"color: {顏色 or ('#ff5c7a' if 錯 else '#3ecf8e')};")
        self.金鑰訊息.setText(字)
        self.金鑰訊息.setVisible(bool(字))

    def 捲到金鑰(self):
        """啟動面板「設定金鑰」：捲到金鑰欄並讓游標停在輸入框。"""
        self.ensureWidgetVisible(self.金鑰列, 20, 120)
        self.金鑰欄.setFocus(Qt.OtherFocusReason)

    def 測試連線(self):
        """用輸入框的金鑰（空白就用目前讀得到的那把）列出模型清單。成功且是輸入框的金鑰才存；失敗絕不存。"""
        provider, 網址, 環境 = self._表單服務()
        代號 = api_key.服務代號(provider, 網址)
        輸入 = self.金鑰欄.text().strip()
        金鑰 = 輸入 or api_key.來源與金鑰(代號, 環境)[1]
        if not 金鑰:
            return self._金鑰提示("請先貼上金鑰，再按「測試連線」。", 錯=True)
        self.測試鈕.setEnabled(False)
        self._金鑰提示("測試中…", 顏色="#8a91a5")

        def 做():
            try:
                結果, 說明 = llm.測試連線(provider, 網址, 金鑰)
            except Exception:          # noqa: BLE001  不讓背景執行緒的錯誤帶出任何內容
                結果, 說明 = llm.測試其他, "測試時發生問題，請再試一次。"
            self._測試完成.emit((代號, 輸入, 結果, api_key.遮掉(說明, 金鑰)))
        if self.背景測試:
            threading.Thread(target=做, daemon=True, name="測試連線").start()
        else:
            做()

    def _測試連線完成(self, 包):
        代號, 輸入, 結果, 說明 = 包
        if 結果 == llm.測試成功 and 輸入:
            try:
                api_key.儲存(代號, 輸入)
            except api_key.金鑰存取錯誤 as e:
                self.更新金鑰()
                return self._金鑰提示(f"{說明}但{e}", 錯=True)
            if self.金鑰欄.text().strip() == 輸入:
                self.金鑰欄.clear()
            說明 += "已儲存在這台電腦。"
        elif 結果 != llm.測試成功 and 輸入:
            說明 += "（沒有儲存）"
        self.更新金鑰()                          # 也會把測試鈕恢復可按
        self._金鑰提示(說明, 錯=結果 != llm.測試成功)
        self.主.更新啟動面板費用()                 # 啟動面板開著：金鑰提示跟著重新檢查

    def 清除金鑰(self):
        代號 = self.金鑰代號()
        try:
            api_key.清除(代號)
        except api_key.金鑰存取錯誤 as e:
            return self._金鑰提示(str(e), 錯=True)
        self.金鑰欄.clear()
        self.更新金鑰()
        字 = f"已清除這台電腦儲存的 {api_key.服務名稱(代號)} 金鑰。"
        if api_key.來源與金鑰(代號, self._表單服務()[2])[0] == api_key.環境變數中:
            字 += "目前改用系統環境變數裡的金鑰。"
        self._金鑰提示(字)
        self.主.更新啟動面板費用()

    def 讀全部(self):
        """回傳要寫進 config.json 的欄位（不含已停用的舊欄位）。"""
        e = self.欄
        一般 = {
            "subtitle_mode": e["subtitle_mode"].currentData(),
            "chat": e["chat"].isChecked(), "minute_summary": e["minute_summary"].isChecked(),
            "fix_with_chat": e["fix_with_chat"].isChecked(),
            **{k: e[k].isChecked() for k, _ in self.存檔項目},
            "summary_thinking": e["summary_thinking"].isChecked(),
            "chat_translate": e["chat_translate"].isChecked(),
            "web_verify": e["web_verify"].isChecked(),
            "chat_translate_max_per_min": e["chat_translate_max_per_min"].value(),
            "minute_sentences": e["minute_sentences"].value(),
            "ui_max_transcript": e["ui_max_transcript"].value(), "ui_max_chat": e["ui_max_chat"].value(),
            "ui_max_translation": e["ui_max_translation"].value(), "newest_on_top": bool(e["newest_on_top"].currentData()),
            "ui_max_summary": e["ui_max_summary"].value(),
            "subtitle_speed": e["subtitle_speed"].currentData(),
            "time_display": e["time_display"].currentData(),
            "provider": e["provider"].currentData(), "model": e["model"].text().strip(),
        }
        return 一般

    # ---------- 立即生效的項目 ----------
    def _換方向(self, *_):
        """選了「最新內容顯示在」就立刻重新排列所有分頁（按「儲存」才寫進 config.json）。"""
        if not self._載入中:
            self.主.設方向(bool(self.欄["newest_on_top"].currentData()))

    def 同步時間顯示(self, 模式):
        """膠囊選單切換了時間顯示：表單跟著改（已經寫進 config.json 了）。"""
        self.欄["time_display"].setCurrentIndex(max(0, self.欄["time_display"].findData(模式)))

    def 同步聊天翻譯(self, 開):
        """膠囊選單切換了聊天室翻譯：表單上的勾選跟著改（已經寫進 config.json 了）。"""
        self.欄["chat_translate"].setChecked(bool(開))

    # ---------- 執行中提示 ----------
    def 設執行中(self, 執行中):
        for w in self.下次標們:
            w.setVisible(執行中)

    # ---------- 儲存、還原 ----------
    def 儲存(self):
        一般 = self.讀全部()
        if not 一般["model"]:
            return self._提示("模型名稱不能空白。", 錯=True)
        代號 = self.金鑰代號()                   # 用寫入前的設定決定是哪個服務（寫入後 provider 可能已改）
        金鑰 = self.金鑰欄.text().strip() if self.金鑰欄.isEnabled() else ""
        try:
            config.寫入設定(一般)        # 只更新表單上的欄位；其他欄位（含已停用的 overlay、hotkey_compact）原樣保留；寫之前先備份
        except Exception as e:
            return self._提示(f"儲存失敗：{type(e).__name__}：{e}", 錯=True)
        金鑰字 = ""
        if 金鑰:
            try:
                api_key.儲存(代號, 金鑰)       # 金鑰只進認證管理員，不進 config.json
                self.金鑰欄.clear()
                金鑰字 = "金鑰已儲存在這台電腦。"
            except api_key.金鑰存取錯誤 as e:
                金鑰字 = str(e)
        self.更新金鑰()
        self.主.聊天翻譯器.開啟 = 一般["chat_translate"]     # 聊天室翻譯開關當場生效（和膠囊選單一樣）
        self.主._更新聊天藥丸()
        if 一般["time_display"] != self.主.時間顯示:          # 時間顯示當場生效（和膠囊選單一樣）
            self.主.設時間顯示(一般["time_display"], 寫回=False)
        self.主.更新啟動面板費用()                             # 啟動面板開著：每小時總費用照新設定重算
        字 = "已儲存（舊的設定已備份）。" + 金鑰字
        if self.主.執行中():
            字 += "標示「下次開始生效」的項目，要等下次按「開始」才會用新的設定。"
        self._提示(字)

    def 還原預設(self):
        self.載入(config.出廠預設())          # 一律用出廠預設，不受上一場改寫的全域值影響
        self.主.設方向(bool(self.欄["newest_on_top"].currentData()))
        self._提示("已還原成預設值。按「儲存」才會套用並記住。")

    def _提示(self, 字, 錯=False):
        self.狀態字.setStyleSheet(f"color: {'#ff5c7a' if 錯 else '#3ecf8e'};")
        self.狀態字.setText(字)


class 設定框(QWidget):
    """獨立的「設定」視窗（啟動面板的齒輪、膠囊選單的「設定」）：內容就是上面的 設定頁，不另外寫一份。"""

    def __init__(self, 主):
        super().__init__(None, Qt.Window)
        self.主 = 主
        self.setObjectName("根")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("直播摘要 設定")
        self.resize(820, 760)
        版 = QVBoxLayout(self)
        版.setContentsMargins(8, 8, 8, 8)
        self.頁 = 設定頁(主)
        版.addWidget(self.頁)

    def 打開(self, 螢幕範圍=None, 捲到金鑰=False):
        """每次打開都從 config.json 重新載入（沒按「儲存」的修改不保留，輸入框裡沒存的金鑰也清掉）。放在指定螢幕範圍的中間。
        捲到金鑰：啟動面板「設定金鑰」打開時，捲到金鑰欄。"""
        if not self.isVisible():
            self.頁.金鑰欄.clear()
            self.頁.眼睛鈕.setChecked(False)
            self.頁.金鑰訊息.hide()
            self.頁.載入()
            self.頁.設執行中(self.主.執行中())
            self.頁.狀態字.setText("")
            if 螢幕範圍 is not None:
                self.resize(min(820, 螢幕範圍.width() - 40), min(760, 螢幕範圍.height() - 40))
                self.move(螢幕範圍.center() - self.rect().center())
        self.show()
        self.raise_()
        self.activateWindow()
        if 捲到金鑰:
            self.頁.捲到金鑰()
            QTimer.singleShot(0, self.頁.捲到金鑰)       # 第一次打開時版面還沒排好，排好後再捲一次
