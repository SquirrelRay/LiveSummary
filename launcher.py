# 啟動面板（新介面第二階段第二步）：開程式時出現的小視窗，取代主控台當作入口。
#   內容：網址欄（重用主控台的網址紀錄下拉清單：最近、釘選、刪除）、語言選單、字幕速度（速度／平衡／準度）、開始按鈕、右上角齒輪（打開設定框）、✕（收起）。
#   字幕速度：預設是設定框記住的值（config.json 的 subtitle_speed），在這裡選只影響這一場；啟動中停用並標示「下次開始生效」。
#   深色、圓角、無邊框，開在膠囊所在螢幕的中間；拖曳空白處可以移動。
#   按「開始」：和主控台的「開始」完全相同（直接把網址、語言填進主控台再呼叫主控台的 開始）。
#     成功開始擷取（收到 files 事件）→ 啟動面板收起，並套用上次使用的版面（沒有就套用預設版面），讓面板出現。
#     網址錯誤、頻道沒開播等錯誤 → 在啟動面板裡用中文顯示，不收起。
# 啟動面板不另外跑引擎，也不改主控台的行為。
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QComboBox, QHBoxLayout, QVBoxLayout, QProgressBar, QButtonGroup,
)

import cost_estimate
import events
import config
import names_page
import subtitle_speed
from launch_state import 啟動狀態

語言選項 = config.語言選項(自動在前=True)      # 自動偵測、中文、日文、英文、韓文
寬 = 480
VOD提示 = "目前只支援直播網址，直播檔（VOD）之後才會支援"


def 段位樣式(圓角):
    """三段選擇的一顆按鈕：只有最左、最右兩顆有圓角，看起來連成一條。"""
    return ("QPushButton { background: #232733; color: #c9cede; border: 1px solid #343a4a; padding: 4px 12px;"
            f" border-radius: 0px; {圓角} }}"
            "QPushButton:checked { background: #5b8cff; color: #ffffff; border-color: #5b8cff; }"
            "QPushButton:disabled { color: #6b7185; } QPushButton:checked:disabled { background: #3a4a72; color: #b8c2dc; }")


class 比較表框(QWidget):
    """資訊圖示展開的比較表：獨立的小視窗（比啟動面板寬），不搶焦點、不吃滑鼠，所以滑鼠離開圖示就收起。"""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        版 = QVBoxLayout(self)
        版.setContentsMargins(14, 12, 14, 12)
        self.表 = QLabel("")
        self.表.setTextFormat(Qt.RichText)
        self.表.setStyleSheet("color: #e7e9ef; font-size: 13px;")
        self.註 = QLabel("")
        self.註.setWordWrap(True)
        self.註.setStyleSheet("color: #8a91a5; font-size: 11px;")
        版.addWidget(self.表)
        版.addWidget(self.註)

    def 填(self, 列們, 註們):
        """列們：cost_estimate.比較表列們 的結果；註們：表下方的小字。內容全部來自 subtitle_speed 與 cost_estimate。"""
        格 = "style='padding: 3px 10px;'"
        字 = ["<table cellspacing='0'><tr>" + "".join(f"<th align='left' {格}><span style='color:#8a91a5;'>{h}</span></th>"
                                                   for h in cost_estimate.比較表標題) + "</tr>"]
        for 列 in 列們:
            底 = " bgcolor='#2e2752'" if 列["目前"] else ""
            名 = f"<b>{列['名稱']}</b>" + ("　<span style='color:#c4b5ff;'>◀ 目前</span>" if 列["目前"] else "")
            聊天 = f" ＋ 聊天 {列['聊天']}" if 列.get("聊天") else ""
            每小時 = f"<b>{列['合計']}</b><br><span style='color:#8a91a5;'>摘要 {列['摘要']} ＋ 翻譯 {列['翻譯']}{聊天}</span>"
            字.append(f"<tr{底}><td {格}>{名}</td><td {格}>{列['延遲']}</td><td {格}>{列['準確度']}</td><td {格}>{每小時}</td></tr>")
        字.append("</table>")
        self.表.setText("".join(字))
        self.註.setText("　".join(註們))
        self.adjustSize()

    def 擺在(self, 錨):
        """放在資訊圖示下方（放不下就放上方），左右不超出所在螢幕。"""
        self.adjustSize()
        螢 = 錨.screen().availableGeometry()
        點 = 錨.mapToGlobal(錨.rect().bottomRight())
        x = min(max(點.x() - self.width(), 螢.x()), 螢.right() - self.width())
        y = 點.y() + 6
        if y + self.height() > 螢.bottom():
            y = 錨.mapToGlobal(錨.rect().topLeft()).y() - self.height() - 6
        self.move(x, max(y, 螢.y()))
        self.show()
        self.raise_()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor("#8b6cff"))
        p.setBrush(QColor("#161920"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)


class 啟動面板(QWidget):
    def __init__(self, 台, 網址欄類, 網址清單類):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Window)
        self.台 = 台
        self.setWindowTitle("直播摘要")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(寬)
        self.狀態 = 啟動狀態()           # 按了開始、還沒確定成功或失敗 = 啟動中
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

        名詞列 = QHBoxLayout()            # 名詞清單：用網址欄的頻道決定是哪位直播主，開始前可以先填名字
        名詞列.setSpacing(8)
        self.名詞鈕 = QPushButton("名詞清單")
        self.名詞鈕.setObjectName("小鈕")
        self.名詞鈕.setCursor(Qt.PointingHandCursor)
        self.名詞鈕.setFocusPolicy(Qt.NoFocus)
        self.名詞鈕.setToolTip("先替這位直播主填好名字的寫法（中文、羅馬拼音或英文），摘要會照著寫")
        self.名詞鈕.clicked.connect(台.開名詞清單)
        self.名詞原因 = QLabel("")
        self.名詞原因.setObjectName("小標")
        名詞列.addWidget(self.名詞鈕)
        名詞列.addWidget(self.名詞原因, 1)
        版.addLayout(名詞列)
        self.網址框.textChanged.connect(lambda _: self._更新名詞鈕())
        self._更新名詞鈕()

        列 = QHBoxLayout()
        列.setSpacing(8)
        語言標 = QLabel("語言")
        語言標.setObjectName("淡")
        self.語言選 = QComboBox()
        for 名, 值 in 語言選項:
            self.語言選.addItem(名, 值)
        預設 = config.目前設定()
        self.語言選.setCurrentIndex(max(0, self.語言選.findData(預設["language"])))     # config.json 的語言（預設「自動」）
        self.開始鈕 = QPushButton("開始")
        self.開始鈕.setObjectName("開始")
        self.開始鈕.setCursor(Qt.PointingHandCursor)
        self.開始鈕.setMinimumWidth(110)
        self.開始鈕.clicked.connect(self.開始)
        self.結束鈕 = QPushButton("結束")
        self.結束鈕.setToolTip("結束程式（含膠囊、系統匣）")
        self.結束鈕.setCursor(Qt.PointingHandCursor)
        self.結束鈕.setMinimumWidth(80)
        self.結束鈕.clicked.connect(self.結束)
        列.addWidget(語言標)
        列.addWidget(self.語言選)
        列.addSpacing(10)
        段位標 = QLabel("字幕")
        段位標.setObjectName("淡")
        段位標.setToolTip("字幕速度：越快第一句越早出現，越準轉錄越穩、翻譯越省（估算）")
        列.addWidget(段位標)
        self.段位鈕們 = {}
        self.段位組 = QButtonGroup(self)
        self.段位組.setExclusive(True)
        for i, 代碼 in enumerate(subtitle_speed.代碼們):
            鈕 = QPushButton(subtitle_speed.取得(代碼)["名稱"])
            鈕.setCheckable(True)
            鈕.setCursor(Qt.PointingHandCursor)
            鈕.setFocusPolicy(Qt.NoFocus)
            圓角 = ("border-top-left-radius: 6px; border-bottom-left-radius: 6px;" if i == 0 else
                  "border-top-right-radius: 6px; border-bottom-right-radius: 6px;" if i == len(subtitle_speed.代碼們) - 1 else "")
            鈕.setStyleSheet(段位樣式(圓角))
            self.段位組.addButton(鈕)
            self.段位鈕們[代碼] = 鈕
            列.addWidget(鈕)
        self.資訊鈕 = QPushButton("ⓘ")          # 滑鼠移上去或點一下：三個段位的比較表
        self.資訊鈕.setObjectName("圖鈕")
        self.資訊鈕.setCursor(Qt.PointingHandCursor)
        self.資訊鈕.setFocusPolicy(Qt.NoFocus)
        self.資訊鈕.setStyleSheet("font-size: 15px;")
        self.資訊鈕.installEventFilter(self)
        self.資訊鈕.clicked.connect(self._點資訊)
        列.addWidget(self.資訊鈕)
        列.setSpacing(8)
        列.addStretch(1)
        版.addLayout(列)
        self.比較框 = 比較表框()
        self.比較固定 = False
        self.段位組.buttonClicked.connect(lambda _: self._更新段位註())

        self.語言選.currentIndexChanged.connect(lambda _: self._更新段位註())

        列2 = QHBoxLayout()
        列2.setSpacing(8)
        self.總費用 = QLabel("")             # 按鈕列左邊：目前段位的每小時總費用
        self.總費用.setObjectName("淡")
        self.總費用.setStyleSheet("font-size: 12px;")
        列2.addWidget(self.總費用, 1)
        列2.addWidget(self.結束鈕)
        列2.addWidget(self.開始鈕)
        版.addLayout(列2)
        self.設段位(預設["subtitle_speed"])

        self.進度條 = QProgressBar()         # 啟動中的動態指示（跑動的條，表示沒有當掉）
        self.進度條.setRange(0, 0)
        self.進度條.setTextVisible(False)
        self.進度條.setFixedHeight(4)
        self.進度條.setStyleSheet("QProgressBar { background: #2a2e3a; border: none; border-radius: 2px; }"
                              "QProgressBar::chunk { background: #5b8cff; border-radius: 2px; }")
        self.進度條.hide()
        版.addWidget(self.進度條)

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
        台.橋.結束.connect(self._引擎結束)
        self.setFixedHeight(self._基本高())

    # ---------- 外觀 ----------
    def _基本高(self):
        版 = self.layout()
        版.activate()
        return max(版.sizeHint().height(), 版.totalHeightForWidth(self.width()) if 版.hasHeightForWidth() else 0)

    def _回基本高(self):
        self.setFixedHeight(self._基本高())

    def eventFilter(self, 物, e):
        if 物 is self.資訊鈕:
            if e.type() == QEvent.Enter:
                self.顯示比較()
            elif e.type() == QEvent.Leave and not self.比較固定:
                self.比較框.hide()
        elif 物 is getattr(self, "網址清單", None) and e.type() == QEvent.Hide:
            self._回基本高()
        return False

    def hideEvent(self, e):
        self.收起比較()
        super().hideEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor("#2a2e3a"))
        p.setBrush(QColor("#161920"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)

    def mousePressEvent(self, e):
        self.收起比較()                  # 點面板其他地方就收起比較表
        if e.button() == Qt.LeftButton and self.windowHandle():     # 拖曳空白處移動
            self.windowHandle().startSystemMove()

    def _更新名詞鈕(self):
        """網址欄還不是有效的 Twitch 頻道網址時，名詞清單按鈕停用，旁邊寫出原因。"""
        名, 原因 = names_page.頻道(self.網址框.text())
        self.名詞鈕.setEnabled(bool(名))
        self.名詞原因.setText(原因 or f"直播主：{名}")

    @property
    def 等待中(self):
        return self.狀態.啟動中

    # ---------- 字幕速度段位 ----------
    def 段位(self):
        for 代碼, 鈕 in self.段位鈕們.items():
            if 鈕.isChecked():
                return 代碼
        return subtitle_speed.預設

    def 設段位(self, 代碼):
        self.段位鈕們[代碼 if subtitle_speed.合法(代碼) else subtitle_speed.預設].setChecked(True)
        self._更新段位註()

    def 段位可改(self):
        """啟動中、直播中不能改段位（分段長度在一場直播中固定）。"""
        return not self.等待中 and not self.台.執行中()

    def _更新段位註(self):
        可改 = self.段位可改()
        for 鈕 in self.段位鈕們.values():
            鈕.setEnabled(可改)
        結果 = cost_estimate.估算(self._費用設定(), self.段位(), self.台.面板.翻譯將啟用(), self.台.面板.聊天將開啟())
        字 = cost_estimate.總費用字(結果)
        量 = QFontMetrics(self.總費用.font())
        self.總費用.setMinimumWidth(max(量.horizontalAdvance(字), 量.horizontalAdvance("每小時約 US$99.99（估算）")) + 2)   # 保證放得下、不被截斷
        self.總費用.setText(字)
        if self.比較框.isVisible():
            self._填比較表()
        if hasattr(self, "網址清單") and not self.網址清單.isVisible():     # 建構途中還沒有網址清單
            self._回基本高()

    def _費用設定(self):
        return dict(config.目前設定(), language=self.語言選.currentData(), subtitle_speed=self.段位(),
                    chat_translate=self.台.聊天翻譯器.開啟)     # 聊天室翻譯可能剛在膠囊選單切換過

    # ---------- 資訊圖示：三個段位的比較表 ----------
    def _填比較表(self):
        列們 = cost_estimate.比較表列們(self._費用設定(), self.段位(), self.台.面板.翻譯將啟用(), self.台.面板.聊天將開啟())
        註 = [cost_estimate.備註們[1]] + ([] if self.段位可改() else ["直播進行中不能切換字幕速度，下次開始生效"])
        self.比較框.填(列們, 註)

    def 顯示比較(self):
        self._填比較表()
        self.比較框.擺在(self.資訊鈕)

    def 收起比較(self):
        self.比較固定 = False
        self.比較框.hide()

    def _點資訊(self):
        if self.比較固定 and self.比較框.isVisible():
            self.收起比較()
        else:
            self.比較固定 = True
            self.顯示比較()

    def _套用狀態(self):
        """依啟動狀態更新：開始鈕、進度條、提示文字、字幕速度能不能改。"""
        self._更新段位註()
        self.開始鈕.setEnabled(self.狀態.開始鈕可用())
        self.進度條.setVisible(self.狀態.顯示進度條())
        self.設狀態(self.狀態.文字(), 錯誤=self.狀態.是錯誤())

    # ---------- 顯示 ----------
    def 顯示(self):
        """打開啟動面板（直播中不會打開），放在膠囊所在螢幕的正中間。"""
        if self.台.執行中() or self.台.結束中:
            return
        if not self.等待中:
            if not self.isVisible():    # 重新打開時，字幕速度回到設定框記住的值
                self.設段位(config.目前設定()["subtitle_speed"])
            self._套用狀態()            # 待命：清掉提示（上一次失敗的錯誤文字會保留）
            self.結束鈕.setEnabled(True)
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
        台.本次段位 = self.段位()      # 只用在這一場，不寫回 config.json
        self.狀態.開始("檢查直播" if not self.測試檔案 else "開始重播文字稿")
        self._套用狀態()
        台.開始()
        if not 台.執行中():           # 主控台在開始前就擋下來（例如找不到檔案）
            台.本次段位 = None
            self.狀態.失敗("無法開始，請確認網址後再試一次。")
            self._套用狀態()

    def 結束(self):
        """結束程式：啟動面板階段還沒開始擷取，不需要確認。啟動中按結束，引擎會在下一個檢查點（約 0.2 秒）收到停止。"""
        self.結束鈕.setEnabled(False)
        self.開始鈕.setEnabled(False)
        if self.等待中:
            self.設狀態("正在結束…")
        events.停止.set()
        self.台.要結束 = True
        self.台.close()              # 引擎還在跑會先收尾，完成後自動關閉；沒在跑就直接關閉全部

    def _引擎結束(self):
        """引擎執行緒結束了，但啟動面板還在等（沒收到 files 也沒收到 error）：不能卡在啟動中。"""
        if self.等待中 and not self.台.要結束:
            self.狀態.失敗("啟動失敗，請再試一次。")
            self._套用狀態()

    def 收事件(self, 種類, 內容):
        if not self.等待中:
            return
        if 種類 == "stage":                   # 啟動階段文字
            self.狀態.換階段(內容.get("階段", ""))
            self._套用狀態()
        elif 種類 == "files":                 # 成功開始擷取：收起，套用版面讓面板出現
            self.狀態.成功()
            self._套用狀態()
            self.hide()
            self.台.面板.套用上次或預設()
        elif 種類 == "error":                 # 網址錯誤、頻道沒開播、金鑰問題等：留在啟動面板顯示
            if self.台.要結束:                # 正在結束中被取消，不顯示錯誤
                return
            self.狀態.失敗(內容.get("訊息") or "發生錯誤，請再試一次。")
            self._套用狀態()
            if not self.isVisible():
                self.顯示()
