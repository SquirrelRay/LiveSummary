# 首次引導（第一次打開程式時出現；之後從膠囊／系統匣選單的「使用說明」重新打開）。
#   三頁，一頁一步：(1) 設定模型與金鑰 (2) 檢查這台電腦 (3) 開始使用。
#   每頁固定結構：大圖示 → 短標題 → 最多兩行說明 → 操作區；補充說明收在「了解更多」（點了才展開，展開時取代操作區，視窗大小不變）。
#   內容（圖示到操作區）在固定大小的視窗內垂直置中，三頁切換時視窗大小不跳動。
#   第 2 頁沒有「了解更多」：只有 ⚠／✕ 的項目右邊有「怎麼處理？」，點了在那一項正下方展開；最後一頁沒有「跳過」。
#   最上方三個圓點標示第幾步；底部「上一步」「下一步」（最後一頁是「開始使用」），左下角小字「跳過」。
#   第 1 頁的模型服務與金鑰就是設定框的 模型金鑰區（同一個元件，精簡模式），按「下一步」時把換過的服務、模型寫進設定。
#   第 2 頁打開時自動檢查（顯示卡、ffmpeg、streamlink），每項先轉圈再變成 ✓／⚠／✕；全部完成前「下一步」停用。
#   第 3 頁的模型大小依實際情況：有可用的 NVIDIA 顯示卡 → 顯示卡用的模型；沒有 → CPU 用的 small；已下載過 → 「轉錄模型已準備好」。
#   看過（按完「開始使用」、按「跳過」或關掉視窗）就記在本機的 介面設定.json（引導看過），之後不再自動出現。
#   風格和啟動面板一致：深色、圓角、無邊框、同一個紫色主按鈕；圖示都是程式畫的線條圖示（不用 emoji、不用圖片檔）。
import threading

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import api_key
import config
import cost_estimate
import first_run
import model_catalog
import settings_page
import ui_state

看過旗標 = "引導看過"
寬, 最小高 = 480, 560
紫, 綠, 橘, 紅, 淡, 底, 邊, 卡 = "#8b6cff", "#3ecf8e", "#f5b84a", "#ff5c7a", "#8a91a5", "#161920", "#2a2e3a", "#1d2029"
等級色 = {first_run.好: 綠, first_run.注意: 橘, first_run.錯: 紅}

# ---------- 每一頁的文字（一般使用者看得到的字都在這裡）----------
頁們 = [
    {"圖示": "鑰匙", "標題": "設定模型與金鑰",
     "說明": "摘要和翻譯要用線上的 AI 模型。\n選一個服務，貼上金鑰後按「測試連線」。",
     "了解更多": [
         "金鑰像一組密碼，讓本程式用你的帳號使用 AI 模型。金鑰只存在這台電腦的 Windows 認證管理員，不會寫進任何檔案。",
         "「測試連線」只確認金鑰能不能用，不會產生費用；成功才會存起來。",
         "費用是估算：外語直播開逐句翻譯、開聊天室翻譯時會比較多，實際金額以服務的帳單為準。",
     ]},
    {"圖示": "電腦", "標題": "檢查這台電腦",
     "說明": "確認轉錄需要的東西都準備好了。\n橘色提醒也能用，紅色的要先處理。",
     "了解更多": []},          # 第 2 頁沒有整頁說明：⚠／✕ 的項目各有自己的「怎麼處理？」
    {"圖示": "播放", "標題": "開始使用",
     "說明": "在啟動面板貼上 Twitch 直播網址，按「開始」。\n摘要和字幕會出現在可以自由擺放的面板上。",
     "了解更多": [
         "轉錄模型會存在這台電腦，之後開始就不用再下載。下載時啟動面板會顯示進度。",
         (f"有 NVIDIA 顯示卡時使用比較準的模型（約 {first_run.大小字(first_run.模型大小['large-v3-turbo'])}）；"
          f"沒有的話使用比較小的模型（約 {first_run.大小字(first_run.模型大小['small'])}）。"),
         "點一下浮動膠囊會出現選單：停止、面板、設定都在裡面。",
         "想再看一次這份說明：膠囊或系統匣選單的「使用說明」。",
     ]},
]
流程們 = [("剪貼簿", "貼上網址"), ("播放", "按開始"), ("面板", "面板出現")]
怎麼處理們 = {      # 只有 ⚠／✕ 的項目才有；✓ 的項目不附說明
    "顯示卡": "沒有可用的 NVIDIA 顯示卡時，程式會自動改用處理器轉錄：能用，但比較慢，字幕可能越來越晚。"
            "有 NVIDIA 顯示卡並更新驅動程式後會更快。",
    "ffmpeg": "ffmpeg 是處理直播聲音的工具。打開命令提示字元，執行 winget install Gyan.FFmpeg，裝好後重新開啟本程式。",
    "streamlink": "streamlink 是連上直播的工具。打開命令提示字元，執行 pip install streamlink，裝好後重新開啟本程式。",
}
怎麼處理字, 收起處理字 = "怎麼處理？", "收起"
檢查們 = [("顯示卡", "NVIDIA 顯示卡", first_run.檢查顯示卡),
       ("ffmpeg", "ffmpeg", first_run.檢查ffmpeg),
       ("streamlink", "streamlink", first_run.檢查streamlink)]
費用註 = "依用量計費，需要自己申請帳號並儲值"
本機費用註 = "在這台電腦上執行，不另外收費"
金鑰好了字 = "已經設定好金鑰"
不需要金鑰字 = "這個服務不需要金鑰"
測試成功字 = "連線成功，金鑰可以使用"


def 已看過():
    return ui_state.讀旗標(看過旗標)


def 要自動出現():
    """開程式時要不要自動打開引導：只看「還沒看過」（沒有金鑰由啟動面板的提示條處理）。"""
    return not 已看過()


# ---------- 線條圖示 ----------
class 線條圖示(QWidget):
    def __init__(self, 名稱, 大小=56, 顏色=紫):
        super().__init__()
        self.名稱, self.顏色 = 名稱, QColor(顏色)
        self.setFixedSize(大小, 大小)

    def paintEvent(self, e):
        s = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.顏色, max(1.6, s / 24), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)

        def 線(*點們):
            路 = QPainterPath(QPointF(點們[0][0] * s, 點們[0][1] * s))
            for x, y in 點們[1:]:
                路.lineTo(x * s, y * s)
            p.drawPath(路)

        def 方(x, y, w, h, r=0.06):
            p.drawRoundedRect(QRectF(x * s, y * s, w * s, h * s), r * s, r * s)
        名 = self.名稱
        if 名 == "鑰匙":
            p.drawEllipse(QPointF(0.32 * s, 0.5 * s), 0.15 * s, 0.15 * s)
            線((0.47, 0.5), (0.86, 0.5))
            線((0.74, 0.5), (0.74, 0.63))
            線((0.84, 0.5), (0.84, 0.6))
        elif 名 == "電腦":
            方(0.12, 0.17, 0.76, 0.5)
            線((0.5, 0.67), (0.5, 0.8))
            線((0.33, 0.82), (0.67, 0.82))
            線((0.3, 0.44), (0.42, 0.44), (0.48, 0.32), (0.56, 0.54), (0.62, 0.44), (0.72, 0.44))
        elif 名 == "播放":
            p.drawEllipse(QPointF(0.5 * s, 0.5 * s), 0.37 * s, 0.37 * s)
            線((0.43, 0.35), (0.66, 0.5), (0.43, 0.65), (0.43, 0.35))
        elif 名 == "剪貼簿":
            方(0.22, 0.18, 0.56, 0.68)
            方(0.38, 0.12, 0.24, 0.12, 0.04)
            線((0.34, 0.45), (0.66, 0.45))
            線((0.34, 0.58), (0.66, 0.58))
            線((0.34, 0.71), (0.54, 0.71))
        elif 名 == "面板":
            方(0.14, 0.2, 0.72, 0.6)
            線((0.14, 0.36), (0.86, 0.36))
            線((0.26, 0.5), (0.74, 0.5))
            線((0.26, 0.64), (0.6, 0.64))
        elif 名 == "下載":
            線((0.5, 0.18), (0.5, 0.62))
            線((0.33, 0.46), (0.5, 0.63), (0.67, 0.46))
            線((0.2, 0.66), (0.2, 0.8), (0.8, 0.8), (0.8, 0.66))
        elif 名 == "箭頭":
            線((0.2, 0.5), (0.78, 0.5))
            線((0.62, 0.36), (0.78, 0.5), (0.62, 0.64))


class 狀態標記(QWidget):
    """綠色 ✓、橘色 ⚠、紅色 ✕（程式畫的，不靠字型）。"""

    def __init__(self, 大小=18):
        super().__init__()
        self.等級 = None
        self.setFixedSize(大小, 大小)

    def 設(self, 等級):
        self.等級 = 等級
        self.update()

    def paintEvent(self, e):
        if self.等級 is None:
            return
        s = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        色 = QColor(等級色[self.等級])
        p.setPen(QPen(色, max(1.8, s / 9), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        路 = QPainterPath()
        if self.等級 == first_run.好:
            路.moveTo(0.18 * s, 0.52 * s)
            路.lineTo(0.42 * s, 0.76 * s)
            路.lineTo(0.84 * s, 0.26 * s)
        elif self.等級 == first_run.錯:
            路.moveTo(0.24 * s, 0.24 * s)
            路.lineTo(0.76 * s, 0.76 * s)
            路.moveTo(0.76 * s, 0.24 * s)
            路.lineTo(0.24 * s, 0.76 * s)
        else:
            路.moveTo(0.5 * s, 0.1 * s)
            路.lineTo(0.94 * s, 0.88 * s)
            路.lineTo(0.06 * s, 0.88 * s)
            路.closeSubpath()
            p.drawPath(路)
            路 = QPainterPath()
            路.moveTo(0.5 * s, 0.4 * s)
            路.lineTo(0.5 * s, 0.6 * s)
            路.moveTo(0.5 * s, 0.74 * s)
            路.lineTo(0.5 * s, 0.75 * s)
        p.drawPath(路)


class 轉圈(QWidget):
    def __init__(self, 大小=18):
        super().__init__()
        self.角 = 0
        self.setFixedSize(大小, 大小)
        self.計時 = QTimer(self, interval=60, timeout=self._轉)

    def _轉(self):
        self.角 = (self.角 + 30) % 360
        self.update()

    def showEvent(self, e):
        self.計時.start()

    def hideEvent(self, e):
        self.計時.stop()

    def paintEvent(self, e):
        s = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(紫), max(1.8, s / 9), Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(2, 2, s - 4, s - 4), -self.角 * 16, 270 * 16)


class 結果列(QWidget):
    """一列：轉圈（檢查中）或 ✓／⚠／✕ ＋ 一句短標籤；⚠／✕ 才在右邊有小字連結「怎麼處理？」，點了在這一項正下方展開（預設收起）。"""

    def __init__(self, 處理說明=""):
        super().__init__()
        self.處理說明 = 處理說明
        外 = QVBoxLayout(self)
        外.setContentsMargins(0, 0, 0, 0)
        外.setSpacing(6)
        上 = QHBoxLayout()
        上.setSpacing(10)
        self.轉 = 轉圈()
        self.標記 = 狀態標記()
        self.字 = QLabel("")
        self.字.setWordWrap(True)
        self.處理鈕 = QPushButton(怎麼處理字)
        self.處理鈕.setCursor(Qt.PointingHandCursor)
        self.處理鈕.setFocusPolicy(Qt.NoFocus)
        self.處理鈕.setStyleSheet("QPushButton { border: none; background: transparent; color: #7aa2ff; padding: 0px;"
                               " font-size: 12px; } QPushButton:hover { color: #a9c1ff; }")
        self.處理鈕.clicked.connect(lambda: self.展開處理(self.處理字.isHidden()))
        上.addWidget(self.轉, 0, Qt.AlignTop)
        上.addWidget(self.標記, 0, Qt.AlignTop)
        上.addWidget(self.字, 1)
        上.addWidget(self.處理鈕, 0, Qt.AlignTop)
        外.addLayout(上)
        self.處理字 = QLabel(處理說明)
        self.處理字.setWordWrap(True)
        self.處理字.setStyleSheet(f"color: {淡}; font-size: 12px; padding-left: 28px;")
        外.addWidget(self.處理字)
        self.標記.hide()
        self.處理鈕.hide()
        self.處理字.hide()
        self.結果 = None

    def 展開處理(self, 開=True):
        self.處理字.setVisible(bool(開) and self.處理鈕.isVisibleTo(self))
        self.處理鈕.setText(收起處理字 if self.處理字.isVisibleTo(self) else 怎麼處理字)

    def 檢查中(self, 字):
        self.結果 = None
        self.轉.show()
        self.標記.hide()
        self.展開處理(False)
        self.處理鈕.hide()
        self.字.setText(字)
        self.字.setStyleSheet(f"color: {淡};")

    def 設結果(self, 結果):
        self.結果 = 結果
        self.轉.hide()
        self.標記.設(結果["等級"])
        self.標記.show()
        self.字.setText(結果["標籤"])
        self.字.setStyleSheet("")
        self.處理鈕.setVisible(結果["等級"] != first_run.好 and bool(self.處理說明))     # ✓ 的項目不附任何說明
        self.展開處理(False)

    def 文字(self):
        """測試、回報用：✓ 標籤（檢查中回傳標籤本身）。"""
        return first_run.結果字(self.結果) if self.結果 else self.字.text()


class 步驟點(QWidget):
    def __init__(self, 數=3):
        super().__init__()
        self.數, self.目前 = 數, 0
        self.setFixedSize(數 * 22, 14)

    def 設(self, i):
        self.目前 = i
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(self.數):
            中 = QPointF(11 + i * 22, 7)
            if i == self.目前:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(紫))
                p.drawEllipse(中, 5, 5)
            else:
                p.setPen(QPen(QColor(紫 if i < self.目前 else "#4a4f60"), 1.6))
                p.setBrush(QColor(紫) if i < self.目前 else Qt.NoBrush)
                p.drawEllipse(中, 3.5, 3.5)


class 引導頁(QWidget):
    """大圖示 → 標題 → 說明 → 操作區（或展開的「了解更多」）→「了解更多」連結。"""

    def __init__(self, 資料, 操作區):
        super().__init__()
        版 = QVBoxLayout(self)
        版.setContentsMargins(0, 0, 0, 0)
        版.setSpacing(0)
        版.addStretch(1)
        self.圖示 = 線條圖示(資料["圖示"])
        版.addWidget(self.圖示, 0, Qt.AlignHCenter)
        版.addSpacing(10)
        self.標題 = QLabel(資料["標題"])
        self.標題.setAlignment(Qt.AlignHCenter)
        self.標題.setStyleSheet("font-size: 20px; font-weight: 700;")
        版.addWidget(self.標題)
        版.addSpacing(6)
        self.說明 = QLabel(資料["說明"])
        self.說明.setAlignment(Qt.AlignHCenter)
        self.說明.setWordWrap(True)
        self.說明.setStyleSheet(f"color: {淡}; font-size: 13px;")
        版.addWidget(self.說明)
        版.addSpacing(16)

        self.槽 = QWidget()
        self.槽層 = QStackedLayout(self.槽)
        self.操作區 = 操作區
        self.說明卡 = QFrame()
        self.說明卡.setObjectName("卡片")
        卡版 = QVBoxLayout(self.說明卡)
        卡版.setContentsMargins(14, 12, 14, 12)
        self.了解字 = QLabel("<br>".join(f"• {x}" for x in 資料["了解更多"]))
        self.了解字.setTextFormat(Qt.RichText)
        self.了解字.setWordWrap(True)
        self.了解字.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.了解字.setStyleSheet("font-size: 12px; line-height: 140%;")
        卡版.addWidget(self.了解字)
        卡版.addStretch(1)
        self.槽層.addWidget(self.操作區)
        self.槽層.addWidget(self.說明卡)
        版.addWidget(self.槽)
        版.addSpacing(8)
        self.了解鈕 = QPushButton("了解更多 ▾")
        self.了解鈕.setCursor(Qt.PointingHandCursor)
        self.了解鈕.setFocusPolicy(Qt.NoFocus)
        self.了解鈕.setStyleSheet("QPushButton { border: none; background: transparent; color: #7aa2ff; padding: 2px 4px;"
                               " font-size: 12px; } QPushButton:hover { color: #a9c1ff; }")
        self.了解鈕.clicked.connect(lambda: self.展開(not self.展開了))
        版.addWidget(self.了解鈕, 0, Qt.AlignHCenter)
        版.addStretch(1)                          # 上下各一個 stretch：內容在視窗內垂直置中
        self.展開了 = False
        if not 資料["了解更多"]:                  # 這一頁沒有整頁說明（第 2 頁）
            self.了解鈕.hide()

    def 展開(self, 開=True):
        self.展開了 = bool(開)
        self.槽層.setCurrentWidget(self.說明卡 if 開 else self.操作區)
        self.了解鈕.setText("收起說明 ▴" if 開 else "了解更多 ▾")


class 首次引導(QWidget):
    _檢查完成 = Signal(str, object)     # 背景檢查 → 介面執行緒
    關閉了 = Signal()
    背景測試 = True                     # 給 模型金鑰區：測試連線、載入可用模型放背景（測試時設 False）
    背景檢查 = True                     # 第 2 頁的檢查放背景執行緒（測試時設 False 改成直接執行）

    def __init__(self, 台, 檢查=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Window)
        self.台 = 台
        self.檢查們 = 檢查 if 檢查 is not None else 檢查們
        self.setWindowTitle("直播摘要 使用說明")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._檢查完成.connect(self._收檢查)
        self._檢查開始過 = False
        self.檢查結果們 = {}
        self.顯示卡可用 = None
        self._動畫 = None
        self._已關 = False

        版 = QVBoxLayout(self)
        版.setContentsMargins(28, 20, 28, 18)
        版.setSpacing(0)
        self.點 = 步驟點()
        版.addWidget(self.點, 0, Qt.AlignHCenter)
        版.addSpacing(16)
        self.頁堆 = QStackedWidget()
        self.頁們 = [引導頁(頁們[0], self._做金鑰區()), 引導頁(頁們[1], self._做檢查區()), 引導頁(頁們[2], self._做開始區())]
        for 頁 in self.頁們:
            self.頁堆.addWidget(頁)
        版.addWidget(self.頁堆, 1)
        版.addSpacing(12)
        底 = QHBoxLayout()
        self.跳過鈕 = QPushButton("跳過")
        self.跳過鈕.setCursor(Qt.PointingHandCursor)
        self.跳過鈕.setFocusPolicy(Qt.NoFocus)
        self.跳過鈕.setStyleSheet(f"QPushButton {{ border: none; background: transparent; color: {淡}; font-size: 12px;"
                               " padding: 4px 2px; } QPushButton:hover { color: #c9cede; }")
        self.跳過鈕.clicked.connect(self.跳過)
        self.上一步鈕 = QPushButton("上一步")
        self.下一步鈕 = QPushButton("下一步")
        for 鈕 in (self.上一步鈕, self.下一步鈕):
            鈕.setCursor(Qt.PointingHandCursor)
            鈕.setMinimumWidth(96)
        self.上一步鈕.clicked.connect(self.上一步)
        self.下一步鈕.clicked.connect(self.下一步)
        底.addWidget(self.跳過鈕, 0, Qt.AlignBottom)
        底.addStretch(1)
        底.addWidget(self.上一步鈕)
        底.addSpacing(8)
        底.addWidget(self.下一步鈕)
        版.addLayout(底)

        self.區.載入設定(config.目前設定())
        self._更新金鑰標記()
        self.setFixedSize(*self.需要的大小())
        self.到(0, 動畫=False)

    # ---------- 版面 ----------
    def 需要的大小(self):
        """寬固定 480；高 = 每一頁（操作區與「了解更多」兩種狀態取大的）都放得下的高度，至少 560。內容不需要捲動。"""
        版 = self.layout()
        版.activate()
        高 = 版.totalHeightForWidth(寬) if 版.hasHeightForWidth() else 版.totalSizeHint().height()
        return 寬, max(最小高, 高, 版.totalMinimumSize().height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(邊))
        p.setBrush(QColor(底))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.windowHandle():     # 拖曳空白處移動
            self.windowHandle().startSystemMove()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.跳過()
        else:
            super().keyPressEvent(e)

    # ---------- 第 1 頁：模型與金鑰 ----------
    def _做金鑰區(self):
        區 = QWidget()
        版 = QVBoxLayout(區)
        版.setContentsMargins(0, 0, 0, 0)
        版.setSpacing(10)
        self.區 = settings_page.模型金鑰區(self, self.台, 精簡=True)      # 和設定框同一個元件
        self.區.提示了.connect(self._金鑰提示)
        版.addWidget(self.區)
        標列 = QHBoxLayout()          # 唯一的金鑰狀態：放在金鑰欄下面那一行的左邊（右邊是「如何取得金鑰」）
        標列.setSpacing(8)
        self.金鑰標記 = 狀態標記(16)
        self.金鑰標字 = QLabel("")
        self.金鑰標字.setWordWrap(True)
        self.金鑰標字.setStyleSheet("font-size: 12px;")
        標列.addWidget(self.金鑰標記, 0, Qt.AlignTop)
        標列.addWidget(self.金鑰標字, 1)
        self.金鑰標列 = QWidget()
        self.金鑰標列.setLayout(標列)
        標列.setContentsMargins(0, 0, 0, 0)
        狀態版 = self.區.金鑰狀態列.layout()
        for i in reversed(range(狀態版.count())):
            if 狀態版.itemAt(i).spacerItem():
                狀態版.takeAt(i)
        狀態版.insertWidget(0, self.金鑰標列, 1)
        self.區.取得連結.setAlignment(Qt.AlignRight)

        費 = QFrame()
        費.setObjectName("卡片")
        費版 = QHBoxLayout(費)
        費版.setContentsMargins(16, 10, 16, 10)
        費版.setSpacing(12)
        self.費用大字 = QLabel("")
        self.費用大字.setTextFormat(Qt.RichText)
        self.費用小字 = QLabel(費用註)
        self.費用小字.setWordWrap(True)
        self.費用小字.setStyleSheet(f"color: {淡}; font-size: 12px;")
        費版.addWidget(self.費用大字)
        費版.addWidget(self.費用小字, 1)
        版.addWidget(費)
        版.addStretch(1)
        return 區

    def 模型區變了(self, 換服務=False):
        """模型金鑰區的服務或模型換了：重算費用與金鑰標記（宿主介面，見 settings_page.模型金鑰區）。"""
        if not hasattr(self, "費用大字"):
            return
        self._更新費用()
        if 換服務:
            self._更新金鑰標記()

    def _模型設定(self):
        return dict(config.目前設定(), **self.區._模型設定())

    def _更新費用(self):
        設定 = self._模型設定()
        try:
            翻譯, 聊天 = self.台.面板.翻譯將啟用(), self.台.面板.聊天將開啟()
        except AttributeError:
            翻譯, 聊天 = True, False
        合計 = cost_estimate.估算(設定, 設定["subtitle_speed"], 翻譯, 聊天)["合計"]
        if 合計 is None:
            self.費用大字.setText("<span style='font-size:22px; font-weight:700;'>無法估算</span>")
            self.費用小字.setText("這個模型的單價不明，" + 費用註)
        else:
            self.費用大字.setText(f"<span style='font-size:24px; font-weight:700;'>約 US${合計:.2f}</span>"
                              f"<span style='color:{淡}; font-size:13px;'>／小時</span>")
            本機 = api_key.服務代號(設定["provider"], 設定["base_url"]) == api_key.本機
            self.費用小字.setText(本機費用註 if 本機 else 費用註)
        self.費用合計 = 合計

    def 金鑰好了(self):
        provider, 網址, 環境 = self.區._表單服務()
        return api_key.來源與金鑰(api_key.服務代號(provider, 網址), 環境)[0] != api_key.未設定

    def _設金鑰標(self, 等級, 字):
        self.金鑰標記.設(等級)
        self.金鑰標記.setVisible(等級 is not None)
        self.金鑰標字.setText(字)
        self.金鑰標字.setStyleSheet(f"font-size: 12px; color: {等級色.get(等級, 淡)};")
        self.金鑰標列.setVisible(bool(字))

    def _更新金鑰標記(self):
        provider, 網址, 環境 = self.區._表單服務()
        狀態 = api_key.來源與金鑰(api_key.服務代號(provider, 網址), 環境)[0]
        if 狀態 == api_key.不需要:
            self._設金鑰標(first_run.好, 不需要金鑰字)
        elif 狀態 != api_key.未設定:
            self._設金鑰標(first_run.好, 金鑰好了字)
        else:
            self._設金鑰標(None, "")
        self._更新按鈕()

    def _金鑰提示(self, 字, 種類):
        """模型金鑰區的金鑰結果：成功 → 綠色 ✓；失敗 → 紅色 ✕ ＋ 原因；測試中 → 淡色文字。"""
        if 種類 == "好":
            self._設金鑰標(first_run.好, 測試成功字 if self.金鑰好了() else 字)
        elif 種類 == "錯":
            self._設金鑰標(first_run.錯, 字)
        else:
            self._設金鑰標(None, 字)
        self._更新按鈕()

    def _存模型設定(self):
        """換過服務或模型才寫進設定（和設定框按「儲存」寫的欄位相同，其他欄位原樣保留）。"""
        舊 = config.目前設定()
        新 = self.區._模型設定()
        if all(舊.get(k) == 新[k] for k in ("provider", "base_url", "model")) or not 新["model"]:
            return False
        if self.區.目前服務() != model_catalog.設定的服務(舊):
            新["api_key_env"] = api_key.出廠環境變數        # 換了服務：舊服務的環境變數名稱不殘留
        try:
            config.寫入設定(新)
        except Exception:                 # noqa: BLE001  寫不進去不擋使用者繼續，之後還能在設定框改
            return False
        self.區._記住設定(config.目前設定())
        if hasattr(self.台, "更新啟動面板費用"):
            self.台.更新啟動面板費用()
        return True

    # ---------- 第 2 頁：檢查這台電腦 ----------
    def _做檢查區(self):
        區 = QFrame()
        區.setObjectName("卡片")
        版 = QVBoxLayout(區)
        版.setContentsMargins(16, 14, 16, 14)
        版.setSpacing(14)
        self.檢查列們 = {}
        for 鍵, 名, _ in self.檢查們:
            列 = 結果列(怎麼處理們.get(鍵, ""))
            列.檢查中(f"正在檢查 {名}…")
            self.檢查列們[鍵] = 列
            版.addWidget(列)
        版.addStretch(1)
        return 區

    def 開始檢查(self):
        if self._檢查開始過:
            return
        self._檢查開始過 = True
        for 鍵, 名, 函式 in self.檢查們:
            self.檢查列們[鍵].檢查中(f"正在檢查 {名}…")

            def 做(鍵=鍵, 名=名, 函式=函式):
                try:
                    結果 = 函式()
                except Exception:          # noqa: BLE001  檢查本身出錯就當作無法確認
                    結果 = first_run.檢查結果(first_run.注意, f"無法確認 {名}")
                self._檢查完成.emit(鍵, 結果)
            if self.背景檢查:
                threading.Thread(target=做, daemon=True, name=f"檢查{鍵}").start()
            else:
                做()
        self._更新按鈕()

    def _收檢查(self, 鍵, 結果):
        if isinstance(結果, tuple):         # 顯示卡：(結果, 可用)
            結果, self.顯示卡可用 = 結果
        self.檢查結果們[鍵] = 結果
        self.檢查列們[鍵].設結果(結果)
        self._更新按鈕()

    def 檢查完了(self):
        return len(self.檢查結果們) == len(self.檢查們)

    # ---------- 第 3 頁：開始使用 ----------
    def _做開始區(self):
        區 = QWidget()
        版 = QVBoxLayout(區)
        版.setContentsMargins(0, 0, 0, 0)
        版.setSpacing(16)
        流 = QHBoxLayout()
        流.setSpacing(4)
        流.addStretch(1)
        for i, (圖, 字) in enumerate(流程們):
            if i:
                箭 = QVBoxLayout()
                箭.setContentsMargins(0, 9, 0, 0)          # 和上面 40 高的圖示置中對齊
                箭.addWidget(線條圖示("箭頭", 22, "#4a4f60"))
                箭.addStretch(1)
                流.addLayout(箭)
            格 = QVBoxLayout()
            格.setSpacing(6)
            格.addWidget(線條圖示(圖, 40), 0, Qt.AlignHCenter)
            標 = QLabel(字)
            標.setAlignment(Qt.AlignHCenter)
            標.setStyleSheet("font-size: 12px;")
            格.addWidget(標)
            框 = QWidget()
            框.setLayout(格)
            框.setMinimumWidth(84)
            流.addWidget(框)
        流.addStretch(1)
        版.addLayout(流)
        卡片 = QFrame()
        卡片.setObjectName("卡片")
        卡版 = QHBoxLayout(卡片)
        卡版.setContentsMargins(14, 12, 14, 12)
        卡版.setSpacing(10)
        self.模型圖示 = 線條圖示("下載", 22)
        self.模型標記 = 狀態標記(18)
        self.模型字 = QLabel("")
        self.模型字.setWordWrap(True)
        卡版.addWidget(self.模型圖示, 0, Qt.AlignVCenter)
        卡版.addWidget(self.模型標記, 0, Qt.AlignVCenter)
        卡版.addWidget(self.模型字, 1)
        版.addWidget(卡片)
        版.addStretch(1)
        self.更新模型卡()
        return 區

    def 這次的模型(self):
        return first_run.要用的模型(self.顯示卡可用, config.目前設定()["whisper_model"])

    def 更新模型卡(self):
        """有可用的 NVIDIA 顯示卡 → 顯示卡用的模型的大小；沒有 → small 的大小；已下載過 → 已準備好。"""
        模型 = self.這次的模型()
        if first_run.已下載(模型):
            self.模型圖示.hide()
            self.模型標記.設(first_run.好)
            self.模型標記.show()
            self.模型字.setText("轉錄模型已準備好")
        else:
            大小 = first_run.大小(模型)
            self.模型標記.hide()
            self.模型圖示.show()
            self.模型字.setText(f"第一次開始會下載轉錄模型（約 {first_run.大小字(大小)}，只需一次）" if 大小
                             else "第一次開始會下載轉錄模型（只需一次）")

    # ---------- 換頁 ----------
    @property
    def 目前頁(self):
        return self.頁堆.currentIndex()

    def 到(self, i, 動畫=True):
        i = max(0, min(len(self.頁們) - 1, i))
        舊 = self.頁們[self.目前頁]
        if 舊.展開了:
            舊.展開(False)
        self.頁堆.setCurrentIndex(i)
        self.點.設(i)
        if i == 1:
            self.開始檢查()
        if i == 2:
            self.更新模型卡()
        self._更新按鈕()
        if 動畫:
            self._淡入(self.頁們[i])

    def _淡入(self, 頁):
        """換頁時輕微淡入（約 0.18 秒）；做完就拿掉效果，不影響下拉選單等元件。"""
        效果 = QGraphicsOpacityEffect(頁)
        頁.setGraphicsEffect(效果)
        動 = QPropertyAnimation(效果, b"opacity", self)
        動.setDuration(180)
        動.setStartValue(0.0)
        動.setEndValue(1.0)
        動.setEasingCurve(QEasingCurve.OutCubic)
        動.finished.connect(lambda: 頁.setGraphicsEffect(None))
        動.start()
        self._動畫 = 動

    def _更新按鈕(self):
        if not hasattr(self, "下一步鈕"):
            return
        i = self.目前頁
        self.上一步鈕.setVisible(i > 0)
        最後 = i == len(self.頁們) - 1
        self.跳過鈕.setVisible(not 最後)           # 最後一頁已經有「開始使用」
        self.下一步鈕.setText("開始使用" if 最後 else "下一步")
        可 = self.檢查完了() if i == 1 else True
        self.下一步鈕.setEnabled(可)
        主 = 最後 or (i == 1 and 可) or (i == 0 and self.金鑰好了())
        if (self.下一步鈕.objectName() == "開始") != 主:
            self.下一步鈕.setObjectName("開始" if 主 else "")
            self.下一步鈕.style().unpolish(self.下一步鈕)
            self.下一步鈕.style().polish(self.下一步鈕)

    def 下一步按鈕是主按鈕(self):
        return self.下一步鈕.objectName() == "開始"

    def 下一步(self):
        if not self.下一步鈕.isEnabled():
            return
        if self.目前頁 == 0:
            self._存模型設定()
        if self.目前頁 == len(self.頁們) - 1:
            return self.完成()
        self.到(self.目前頁 + 1)

    def 上一步(self):
        if self.目前頁 > 0:
            self.到(self.目前頁 - 1)

    # ---------- 結束 ----------
    def 跳過(self):
        self.完成()

    def 完成(self):
        """看完、跳過、關掉都算看過：記下來，之後開程式不再自動出現。"""
        ui_state.存旗標(看過旗標, True)
        self.close()

    def closeEvent(self, e):
        ui_state.存旗標(看過旗標, True)
        super().closeEvent(e)
        if not self._已關:
            self._已關 = True
            self.關閉了.emit()

    def 顯示(self, 螢幕範圍=None):
        """打開（每次從第 1 頁開始），放在螢幕正中間。"""
        self._已關 = False
        if not self.isVisible():
            self.區.載入設定(config.目前設定())
            self._更新金鑰標記()
            self.到(0, 動畫=False)
            if 螢幕範圍 is not None:
                self.move(螢幕範圍.center().x() - self.width() // 2, 螢幕範圍.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()
