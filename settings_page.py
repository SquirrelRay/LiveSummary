# 設定框（啟動面板的齒輪、膠囊／系統匣選單的「設定」）：模型服務與金鑰、功能開關、顯示上限、字幕速度段位、存檔
# 按「儲存」才寫回 config.json（寫之前先備份成 config.backup.json）；
# config.json 裡已停用的舊欄位（overlay、hotkey_compact、translate_batch_seconds／translate_batch_lines）原樣保留。
# 模型服務與模型：兩個下拉選單（目錄在 model_catalog.py）。選服務自動帶入服務網址、金鑰欄位、「如何取得金鑰」；
#   只有「其他相容服務」才顯示網址欄。模型選單列推薦模型（白話名稱＋說明），最後一項「其他（自己輸入）」才出現文字欄。
#   「載入可用模型」用列出模型（不花錢）把服務實際提供的模型放進選單的進階區塊（可篩選）；Ollama 的推薦清單就是本機已下載的模型。
#   單價查不到的模型（自己輸入、清單外沒附價格）費用一律顯示「單價未知，無法估算」。
# API 金鑰：輸入時遮蔽（眼睛按鈕可暫時顯示剛輸入的字）；存在這台電腦的認證管理員（api_key.py），不寫進 config.json。
#   「測試連線」成功才存、失敗絕不存；按「儲存」也會存；只輸入不按這兩顆就關掉，金鑰不會被存（和其他欄位一致）。
#   已存的金鑰永遠不會放回輸入框，只顯示白話狀態。
# 視窗大小：預設依內容算（不截斷文字），使用者拉過就記在 介面設定.json；超出目前螢幕時自動縮回。
# 開發者選項（最下面，預設收起）：「顯示文字稿重播模式」勾選後主控台的來源才出現「文字稿檔案」；
#   記在本機的 介面設定.json（不進 config.json、不進 git），勾了立即生效，不用按「儲存」。
import os
import re
import threading

from PySide6.QtCore import Qt, QObject, QEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QFrame, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox,
    QLineEdit, QGridLayout, QHBoxLayout, QVBoxLayout,
)

import api_key
import app_paths
import config
import cost_estimate
import llm
import model_catalog
import subtitle_speed
import tray_tip
import ui_state
import version

授權說明 = ("本程式以 GNU GPLv3 授權開放原始碼（全文在程式資料夾的 LICENSE.txt），"
        "並依 GPLv3 第 7 條加上額外許可，允許與 NVIDIA CUDA、Intel 的函式庫一起使用（LICENSE-ADDITIONAL-PERMISSION.txt）。"
        "使用 FFmpeg（LGPL v3）處理直播聲音。第三方元件的授權清單在程式資料夾的 licenses 資料夾。")

清單上限 = 300           # 「載入可用模型」最多一次放幾個進選單（OpenRouter 有幾百個，其餘用篩選找）
文字稿旗標 = "顯示文字稿模式"       # 介面設定.json 的旗標：主控台來源要不要出現「文字稿檔案」（開發測試用）
查證原因字 = "目前的模型服務不支援上網查證：只有直接連 Claude 時能用（透過 OpenRouter 用 Claude 也不支援）。"


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


class 模型金鑰區(QWidget):
    """「模型服務與 API 金鑰」這一塊：服務、模型（推薦清單＋其他）、單價、進階（載入可用模型、篩選）、API 金鑰。
    設定框與首次引導第 1 頁共用同一個元件（行為完全相同）。
    宿主：放這一塊的頁面，要有 模型區變了(換服務=False)（服務或模型變了：重算費用等）；
          可以有 背景測試（False = 測試連線、載入可用模型直接執行，測試用）與 _下次()（「下次開始生效」標籤）。
    精簡：首次引導用，不顯示單價、進階、清除與環境變數小字，金鑰結果改由引導自己顯示（其餘都一樣）。"""
    _測試完成 = Signal(object)        # 測試連線的背景執行緒 → 介面執行緒
    _列出完成 = Signal(object)        # 載入可用模型的背景執行緒 → 介面執行緒
    提示了 = Signal(str, str)         # 金鑰的結果訊息（字, 種類：好／錯／中）：首次引導用它顯示 ✓／✕

    def __init__(self, 宿主, 主, 精簡=False):
        super().__init__()
        self.宿主, self.主, self.精簡 = 宿主, 主, 精簡
        self._測試完成.connect(self._測試連線完成)
        self._列出完成.connect(self._載入模型完成)
        self._載入中 = False
        self._已載入 = {}            # 服務代號 → 「載入可用模型」讀到的模型們（這次開程式內有效）
        self._設定服務, self._設定模型, self._設定網址 = "claude", "", ""      # 表單載入時的設定（切回同一個服務時還原）
        self._設定單價 = ("", None, None)    # 表單載入時的設定裡註明的單價（price_model, 輸入, 輸出）
        格 = QGridLayout(self)
        格.setContentsMargins(0, 0, 0, 0)
        格.setHorizontalSpacing(12)
        格.setVerticalSpacing(8)
        格.setColumnStretch(1, 1)            # 「下次開始生效」那一欄平常是空的：寬度都給下拉選單與金鑰欄
        self.服務選 = QComboBox()
        for s in model_catalog.選單服務們():
            self.服務選.addItem(model_catalog.服務顯示名(s["代號"]), s["代號"])
            self.服務選.setItemData(self.服務選.count() - 1,
                                  model_catalog.實驗說明 if s["實驗性"] else "正式支援", Qt.ToolTipRole)
        self.實驗標 = QLabel("實驗性")
        self.實驗標.setStyleSheet("color: #f5b84a; font-weight: 700;")
        self.實驗標.setToolTip(model_catalog.實驗說明)
        服務橫 = QWidget()
        橫 = QHBoxLayout(服務橫)
        橫.setContentsMargins(0, 0, 0, 0)
        橫.addWidget(self.服務選, 1)
        橫.addWidget(self.實驗標)
        self.服務說明 = QLabel("")             # 服務的一句補充（例如 OpenRouter：想用 GPT 等其他家的模型，可以透過它）
        self.服務說明.setObjectName("小標")
        self.服務說明.setWordWrap(True)
        self.服務說明.hide()
        服務列 = QWidget()
        直 = QVBoxLayout(服務列)
        直.setContentsMargins(0, 0, 0, 0)
        直.setSpacing(4)
        直.addWidget(服務橫)
        直.addWidget(self.服務說明)

        self.網址標 = 小標("服務網址")
        self.網址欄 = QLineEdit()
        self.網址欄.setPlaceholderText("服務的網址，例如 https://example.com/v1")
        self.模型選 = QComboBox()
        self.模型選.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)   # 很長的模型名稱不把視窗撐寬
        self.模型選.setMinimumContentsLength(24)
        self.自訂標 = 小標("模型代號")
        self.自訂模型欄 = QLineEdit()
        self.自訂模型欄.setPlaceholderText("輸入服務文件上寫的模型代號（進階）")
        self.單價字 = QLabel("")
        self.單價字.setObjectName("小標")
        self.單價字.setWordWrap(True)

        進階 = QWidget()
        橫2 = QHBoxLayout(進階)
        橫2.setContentsMargins(0, 0, 0, 0)
        進階字 = QLabel("進階：")
        進階字.setObjectName("小標")
        self.載入鈕 = QPushButton("載入可用模型")
        self.載入鈕.setCursor(Qt.PointingHandCursor)
        self.載入鈕.setToolTip("列出這個服務實際提供的模型（不會產生費用），放進模型選單的進階區塊")
        self.篩選欄 = QLineEdit()
        self.篩選欄.setPlaceholderText("輸入關鍵字篩選模型")
        self.篩選欄.hide()
        橫2.addWidget(進階字)
        橫2.addWidget(self.載入鈕)
        橫2.addWidget(self.篩選欄, 1)
        橫2.addStretch(0)
        self.載入訊息 = QLabel("")
        self.載入訊息.setWordWrap(True)
        self.載入訊息.hide()
        self._做金鑰欄()

        列 = 0
        for 名, w, 下次 in (("模型服務", 服務列, True), (self.網址標, self.網址欄, True), ("模型", self.模型選, True),
                         (self.自訂標, self.自訂模型欄, False)):
            格.addWidget(小標(名) if isinstance(名, str) else 名, 列, 0)
            格.addWidget(w, 列, 1, 1, 2)
            if 下次:
                格.addWidget(self._下次(), 列, 3)
            列 += 1
        for w in (self.單價字, 進階, self.載入訊息):
            格.addWidget(w, 列, 1, 1, 3)
            列 += 1
        格.addWidget(小標("API 金鑰"), 列, 0)
        格.addWidget(self.金鑰列, 列, 1, 1, 2)
        列 += 1
        for w in (self.金鑰狀態列, self.金鑰訊息, self.金鑰進階):
            格.addWidget(w, 列, 1, 1, 3)
            列 += 1
        for w in (self.網址標, self.網址欄, self.自訂標, self.自訂模型欄):
            w.hide()

        self.服務選.currentIndexChanged.connect(self._換服務)
        self.模型選.currentIndexChanged.connect(self._換模型)
        self.自訂模型欄.textChanged.connect(lambda _: self.宿主.模型區變了())
        self.網址欄.textChanged.connect(lambda _: self._換網址())
        self.載入鈕.clicked.connect(lambda: self.載入可用模型())
        self.篩選欄.textChanged.connect(lambda _: self._重建模型選單())
        if 精簡:
            for w in (self.單價字, 進階, self.清除鈕, self.金鑰字):      # 金鑰字：引導自己在同一行顯示唯一的狀態
                w.setVisible(False)

    def _下次(self):
        """「下次開始生效」標籤由宿主（設定框）管理；首次引導沒有，放一個不顯示的空標籤。"""
        if hasattr(self.宿主, "_下次"):
            return self.宿主._下次()
        w = QLabel("")
        w.hide()
        return w

    def _背景(self):
        return getattr(self.宿主, "背景測試", True)

    def 載入設定(self, 設定):
        """表單載入：記住設定裡的服務、模型、網址、單價，選到那個服務並套用（不算「使用者換了服務」）。"""
        self._載入中 = True
        try:
            self._記住設定(設定)
            self.服務選.setCurrentIndex(max(0, self.服務選.findData(self._設定服務)))
        finally:
            self._載入中 = False
        self.自訂模型欄.setText("")
        self._套用服務(self._設定服務, 模型=self._設定模型)

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

    def _記住設定(self, 設定):
        self._設定服務 = model_catalog.設定的服務(設定)
        self._設定模型 = 設定.get("model", "")
        self._設定網址 = 設定.get("base_url", "") if self._設定服務 == model_catalog.其他 else ""
        self._設定單價 = (設定.get("price_model", ""), 設定.get("price_input"), 設定.get("price_output"))

    def _模型設定(self):
        """表單上選的服務與模型 → 要寫進設定的 provider、base_url、model 與單價欄位。
        單價查得到（推薦清單、OpenRouter 清單附的價格、本機 0）才寫，並註明是哪個模型的；查不到就清掉對應（費用顯示單價未知）。"""
        模型 = self.目前模型()
        設 = dict(model_catalog.服務設定(self.目前服務(), self.網址欄.text()), model=模型)
        單 = self._選的單價()
        if 單:
            設.update(price_input=單[0], price_output=單[1], price_model=模型)
        else:
            設["price_model"] = ""
        return 設

    def 目前服務(self):
        return self.服務選.currentData()

    def 目前模型(self):
        值 = self.模型選.currentData()
        if 值 == model_catalog.自訂:
            return self.自訂模型欄.text().strip()
        return 值 or ""

    def _換服務(self, *_):
        if self._載入中:
            return
        self.金鑰欄.clear()                 # 打到一半的金鑰不跟著換到別的服務
        self.金鑰訊息.hide()
        self.自訂模型欄.setText("")          # 舊服務的模型不殘留
        self._套用服務(self.目前服務())

    def _套用服務(self, 服務, 模型=None):
        """換到這個服務：網址（只有其他相容服務顯示）、實驗性標示、模型選單（回到記住的或建議的模型）、上網查證、金鑰、費用。"""
        同 = 服務 == self._設定服務
        self.網址欄.blockSignals(True)
        self.網址欄.setText(self._設定網址 if 同 and 服務 == model_catalog.其他 else "")
        self.網址欄.blockSignals(False)
        for w in (self.網址標, self.網址欄):
            w.setVisible(服務 == model_catalog.其他)
        實驗 = model_catalog.服務(服務)["實驗性"]
        self.實驗標.setVisible(實驗)
        提示 = model_catalog.服務(服務).get("提示", "")
        self.服務說明.setText(提示)
        self.服務說明.setVisible(bool(提示))
        self.服務選.setToolTip(model_catalog.實驗說明 if 實驗 else "")
        self.篩選欄.blockSignals(True)
        self.篩選欄.clear()
        self.篩選欄.blockSignals(False)
        self.篩選欄.setVisible(bool(self._清單(服務)))
        self.載入訊息.hide()
        if 模型 is None:
            模型 = self._設定模型 if 同 else (model_catalog.建議模型(服務) or model_catalog.自訂)
        self._重建模型選單(模型)
        self.宿主.模型區變了(換服務=True)        # 設定框：上網查證能不能勾、費用表
        self.更新金鑰()
        if 服務 == "ollama" and "ollama" not in self._已載入:
            self.載入可用模型(自動=True)        # Ollama 的推薦清單就是本機已下載的模型

    def _換網址(self):
        """其他相容服務改了網址：之前載入的清單不算數，金鑰也換成這個網址的那一格。"""
        self._已載入.pop(model_catalog.其他, None)
        self.篩選欄.hide()
        self._重建模型選單()
        self.更新金鑰()

    def _推薦們(self, 服務):
        if 服務 == "ollama":
            已 = self._已載入.get("ollama")
            代號們 = [m["代號"] for m in 已] if 已 is not None else (
                [self._設定模型] if self._設定服務 == "ollama" and self._設定模型 else [])
            return [model_catalog.模型項(c, c, "本機模型", 0.0, 0.0) for c in 代號們]
        return model_catalog.推薦(服務)

    def _清單(self, 服務):
        """「載入可用模型」讀到的清單（Ollama 的直接當推薦清單，不在進階區塊）。"""
        return None if 服務 == "ollama" else self._已載入.get(服務)

    def _加標題(self, 字):
        w = self.模型選
        w.addItem(字, None)
        w.model().item(w.count() - 1).setEnabled(False)

    def _重建模型選單(self, 偏好=None):
        """推薦模型 →（載入過）服務提供的模型（進階，可篩選）→ 其他（自己輸入）。偏好：要選的模型代號（或 自訂）。"""
        服務 = self.目前服務()
        if 偏好 is None:
            偏好 = self.模型選.currentData()
            if 偏好 == model_catalog.自訂 and self.自訂模型欄.text().strip():
                偏好 = self.自訂模型欄.text().strip()
        w = self.模型選
        w.blockSignals(True)
        w.clear()
        推薦們 = self._推薦們(服務)
        for m in 推薦們:
            w.addItem(model_catalog.模型顯示名(m), m["代號"])
            提示 = ("本機模型，不花 API 費用" if 服務 == "ollama" else
                  model_catalog.單價字(m["輸入"], m["輸出"]) + (f"。{m['備註']}" if m["備註"] else ""))
            w.setItemData(w.count() - 1, 提示, Qt.ToolTipRole)
        清單 = self._清單(服務)
        if 清單:
            推薦代號 = {m["代號"] for m in 推薦們}
            篩 = self.篩選欄.text().strip().lower()
            其餘 = [m for m in 清單 if m["代號"] not in 推薦代號
                  and (not 篩 or 篩 in m["代號"].lower() or 篩 in m["名稱"].lower() or m["代號"] == 偏好)]
            if w.count():
                w.insertSeparator(w.count())
            self._加標題(f"服務提供的模型（進階，{'符合的 ' if 篩 else ''}{len(其餘)} 個）")
            for m in 其餘[:清單上限]:
                w.addItem(m["代號"], m["代號"])
                提示 = (model_catalog.單價字(m["輸入"], m["輸出"], 日期="") + "，服務的模型清單附的單價"
                      if m["輸入"] is not None else "單價未知，無法估算費用")
                w.setItemData(w.count() - 1, 提示, Qt.ToolTipRole)
            if len(其餘) > 清單上限:
                self._加標題(f"還有 {len(其餘) - 清單上限} 個，請在篩選欄輸入關鍵字")
        if w.count():
            w.insertSeparator(w.count())
        w.addItem("其他（自己輸入）", model_catalog.自訂)
        w.setItemData(w.count() - 1, "自己輸入模型代號（進階）；單價未知，費用無法估算", Qt.ToolTipRole)
        i = w.findData(偏好) if 偏好 else -1
        if i < 0 and 偏好 and 偏好 != model_catalog.自訂:          # 不在清單裡的模型：顯示成「其他（自己輸入）」並帶入原本的代號
            i = w.findData(model_catalog.自訂)
            self.自訂模型欄.setText(偏好)
        if i < 0:
            建議 = model_catalog.建議模型(服務)
            i = w.findData(建議) if 建議 else (0 if 推薦們 else w.findData(model_catalog.自訂))
        w.setCurrentIndex(i)
        w.blockSignals(False)
        self._換模型()

    def _選的單價(self):
        """目前選的模型的 (輸入, 輸出) 單價；自己輸入的模型若剛好在官方價目表裡也算得出；其餘（清單外沒附價格）→ None（不沿用舊單價）。
        順序和實際估算（model_catalog.單價）一致：設定裡註明是這個模型的單價 → 官方價目表（含暫時隱藏的 OpenAI）→ 本機 0 →
        服務的模型清單附的單價。"""
        模型, 服務 = self.目前模型(), self.目前服務()
        if not 模型:
            return None
        設 = dict(model_catalog.服務設定(服務, self.網址欄.text()), model=模型)
        if 服務 == self._設定服務:
            設.update(price_model=self._設定單價[0], price_input=self._設定單價[1], price_output=self._設定單價[2])
        單 = model_catalog.單價(設)
        if 單:
            return 單
        m = next((x for x in self._清單(服務) or [] if x["代號"] == 模型), None)
        if m and m["輸入"] is not None and m["輸出"] is not None:
            return m["輸入"], m["輸出"]
        return None

    def _換模型(self, *_):
        自訂 = self.模型選.currentData() == model_catalog.自訂
        for w in (self.自訂標, self.自訂模型欄):
            w.setVisible(自訂)
        單 = self._選的單價()
        值, 服務 = self.模型選.currentData(), self.目前服務()
        設 = model_catalog.服務設定(服務, self.網址欄.text())
        m = model_catalog.找模型(model_catalog.對應服務(設["provider"], 設["base_url"], 含隱藏=True), self.目前模型())
        if 服務 == "ollama" and 值 and not 自訂:
            字 = "本機模型，不花 API 費用"
        elif 單 is None:
            字 = model_catalog.未知字 + "（費用表、啟動面板、膠囊都會顯示無法估算）"
        elif m and m["輸入"] == 單[0] and m["輸出"] == 單[1]:
            字 = model_catalog.單價字(*單) + (f"。{m['備註']}" if m["備註"] else "")
        elif 服務 == "openrouter":
            字 = (model_catalog.單價字(*單, 日期="") + "，服務的模型清單附的單價。OpenRouter 列的是最便宜供應商的價格，"
                  "實際依路由到的供應商而定，可能較高")
        else:
            字 = model_catalog.單價字(*單, 日期="") + "，服務的模型清單附的單價"
        self.單價字.setText(字)
        self.模型選.setToolTip(self.模型選.itemData(self.模型選.currentIndex(), Qt.ToolTipRole) or "")
        self.宿主.模型區變了()

    # ---------- 載入可用模型 ----------
    def _載入提示(self, 字, 錯=False, 顏色=None):
        self.載入訊息.setStyleSheet(f"color: {顏色 or ('#ff5c7a' if 錯 else '#3ecf8e')};")
        self.載入訊息.setText(字)
        self.載入訊息.setVisible(bool(字))

    def 載入可用模型(self, 自動=False):
        """用「列出模型」（不花錢）讀服務實際提供的模型。沒有金鑰或連不上時用白話說明。"""
        服務 = self.目前服務()
        provider, 網址, 環境 = self._表單服務()
        if 服務 == model_catalog.其他 and not 網址:
            return self._載入提示("請先填「服務網址」，再按「載入可用模型」。", 錯=True)
        代號 = api_key.服務代號(provider, 網址)
        狀態, 已有 = api_key.來源與金鑰(代號, 環境)
        金鑰 = self.金鑰欄.text().strip() or 已有
        if 狀態 != api_key.不需要 and not 金鑰:
            return self._載入提示("還沒有這個服務的 API 金鑰：請先在下面貼上金鑰，再按「載入可用模型」。", 錯=True)
        self.載入鈕.setEnabled(False)
        self._載入提示("正在讀取 Ollama 裡的模型…" if 服務 == "ollama" else "載入中…", 顏色="#8a91a5")

        def 做():
            try:
                結果, 說明, 模型們 = llm.列出模型(provider, 網址, 金鑰)
            except Exception:          # noqa: BLE001  不讓背景執行緒的錯誤帶出任何內容
                結果, 說明, 模型們 = llm.測試其他, "載入時發生問題，請再試一次。", []
            self._列出完成.emit((服務, 網址, 結果, api_key.遮掉(說明, 金鑰), 模型們))
        if self._背景():
            threading.Thread(target=做, daemon=True, name="載入可用模型").start()
        else:
            做()

    def _載入模型完成(self, 包):
        服務, 網址, 結果, 說明, 模型們 = 包
        self.載入鈕.setEnabled(True)
        if 服務 != self.目前服務() or 網址 != self._表單服務()[1]:      # 使用者已經換了服務或網址：這份清單不用了
            return
        if 結果 != llm.測試成功:
            if 服務 == "ollama" and 結果 == llm.測試連不上:
                說明 = "連不上 Ollama。請先打開 Ollama，再按「載入可用模型」。"
            return self._載入提示(說明, 錯=True)
        模型們 = sorted(模型們, key=lambda m: m["代號"].lower())
        self._已載入[服務] = 模型們
        偏好 = None
        if 服務 == "ollama":
            if not 模型們:
                self._載入提示("Ollama 裡還沒有下載任何模型。請先打開命令提示字元，執行「ollama pull 模型名稱」下載模型，"
                           "再按「載入可用模型」。", 錯=True)
            else:
                self._載入提示(f"已讀到這台電腦裡的 {len(模型們)} 個模型。")
                if not self.目前模型():
                    偏好 = 模型們[0]["代號"]
        else:
            self._載入提示(f"已載入 {len(模型們)} 個模型，放在模型選單的「進階」區塊" +
                       ("；可以在右邊輸入關鍵字篩選。" if 模型們 else "。"))
            self.篩選欄.setVisible(bool(模型們))
        self._重建模型選單(偏好)

    # ---------- API 金鑰 ----------
    def _表單服務(self):
        """表單上選的模型服務 → (provider, 服務網址, 舊設定的環境變數名稱)。
        和記住的設定同一個服務就沿用它的環境變數名稱；切到別的服務就用該家預設。"""
        服務 = self.目前服務()
        設 = model_catalog.服務設定(服務, self.網址欄.text())
        環境 = config.目前設定()["api_key_env"] if 服務 == self._設定服務 else api_key.出廠環境變數
        return 設["provider"], 設["base_url"], 環境

    def 金鑰代號(self):
        provider, 網址, _ = self._表單服務()
        return api_key.服務代號(provider, 網址)

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
            "" if not 需要 else ("已儲存" if self.精簡 else "已儲存（要更換就貼上新的金鑰）") if 狀態 == api_key.已儲存
            else f"貼上 {名稱} 的 API 金鑰")
        連結 = api_key.取得網址(代號)
        self.取得連結.setText(f"<a href='{連結}' style='color:#7aa2ff;'>如何取得金鑰</a>" if 連結 else "")
        self.取得連結.setToolTip(連結)
        self.取得連結.setVisible(bool(連結) and 需要)
        變數 = api_key.環境變數名(代號, 環境)
        self.金鑰進階.setText(f"進階：也可以用系統環境變數 {變數} 設定金鑰；這台電腦已儲存的金鑰優先。" if 變數 and 需要 else "")
        self.金鑰進階.setVisible(bool(self.金鑰進階.text()) and not self.精簡)

    def _金鑰提示(self, 字, 錯=False, 顏色=None):
        self.金鑰訊息.setStyleSheet(f"color: {顏色 or ('#ff5c7a' if 錯 else '#3ecf8e')};")
        self.金鑰訊息.setText(字)
        self.金鑰訊息.setVisible(bool(字) and not self.精簡)
        self.提示了.emit(字, "錯" if 錯 else "中" if 顏色 else "好")

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
        if self._背景():
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


class 設定頁(QScrollArea):
    背景測試 = True                   # 測試連線、載入可用模型放背景執行緒（測試時設 False 改成直接執行）

    def __init__(self, 主):
        super().__init__()
        self.主 = 主                 # 主控台（換內容方向、看是否執行中）
        self._載入中 = False
        self._查證記憶 = False       # 切到不支援上網查證的服務前，勾選的狀態
        self.下次標們 = []           # 「下次開始生效」標籤
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)     # 視窗被縮得太窄時寧可出現橫捲軸，也不截斷文字
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

        版.addWidget(self._做模型區())
        版.addWidget(self._做一般區())
        版.addWidget(self._做費用區())
        版.addWidget(self._做存檔區())
        版.addWidget(self._做系統匣區())
        版.addWidget(self._做關於區())
        版.addWidget(self._做開發者區())
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

    def _做模型區(self):
        """模型服務與 API 金鑰：內容是共用的 模型金鑰區（首次引導第 1 頁也用它）。"""
        框, 格 = self._面板("模型服務與 API 金鑰")
        格.setColumnStretch(3, 0)
        self.模型區 = 模型金鑰區(self, self.主)
        格.addWidget(self.模型區, 0, 0, 1, 4)
        return 框

    def 捲到金鑰(self):
        """啟動面板「設定金鑰」：捲到金鑰欄並讓游標停在輸入框。"""
        self.ensureWidgetVisible(self.模型區.金鑰列, 20, 120)
        self.模型區.金鑰欄.setFocus(Qt.OtherFocusReason)

    def 模型區變了(self, 換服務=False):
        """模型金鑰區的服務或模型變了：換服務時更新上網查證能不能勾；重算段位說明與費用表。"""
        if 換服務 and "web_verify" in getattr(self, "欄", {}):
            self._更新查證可用()
        self._更新段位說明()

    def __getattr__(self, 名):
        """舊的寫法（設定頁.服務選、設定頁.測試連線…）照樣能用：轉給 模型金鑰區。"""
        區 = self.__dict__.get("模型區")
        if 區 is None or 名.startswith("__"):
            raise AttributeError(名)
        return getattr(區, 名)


    def _做一般區(self):
        框, 格 = self._面板("功能")
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
        e["web_verify"].toggled.connect(self._記查證)
        self.查證原因 = QLabel(查證原因字)
        self.查證原因.setObjectName("小標")
        self.查證原因.setWordWrap(True)
        self.查證原因.hide()
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

        列 = 0

        def 加(名, w, 下次=False):
            nonlocal 列
            if 名:
                格.addWidget(小標(名), 列, 0)
                格.addWidget(w, 列, 1, 1, 2)
            else:                                    # 沒有標題的勾選框：從最左邊開始，長的文字才放得下
                格.addWidget(w, 列, 0, 1, 3)
            if 下次:
                格.addWidget(self._下次(), 列, 3)
            列 += 1

        加("逐句字幕模式", e["subtitle_mode"], True)
        for k in ("chat", "minute_summary", "fix_with_chat", "summary_thinking", "web_verify"):
            加("", e[k], True)
        格.addWidget(self.查證原因, 列, 0, 1, 4)
        列 += 1
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
        return 框


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
              ("save_chat", "聊天室"), ("save_translation", "逐句翻譯"), ("save_audio", "音訊（除錯用，每段一個 wav，檔案較大；存在本機 AppData 的「LiveSummary/音訊」，只留最近 5 場）"))

    def _做存檔區(self):
        """存檔：五個開關（出廠預設只有摘要開）＋打開存檔資料夾。關掉的內容只顯示在畫面上，不寫檔。"""
        框, 格 = self._面板("存檔")
        說明 = QLabel("打開的項目才會存成檔案（存在「文件」裡的「直播摘要」資料夾）。關掉的內容只顯示在畫面上，超過顯示上限的較早內容會直接移除。")
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

    def _做系統匣區(self):
        """系統匣圖示說明（和首次引導最後一頁同一張卡）。"""
        框, 格 = self._面板(tray_tip.標題)
        self.系統匣卡 = tray_tip.系統匣說明卡(小標題=False)
        格.addWidget(self.系統匣卡, 0, 0, 1, 4)
        return 框

    def _做關於區(self):
        """關於：版本、授權（GPLv3）、使用 FFmpeg（LGPL）、第三方授權清單的位置。"""
        框, 格 = self._面板("關於")
        self.版本標 = QLabel(f"{version.產品名} {version.版本字()}")      # 版本號只寫在 version.py
        self.版本標.setTextInteractionFlags(Qt.TextSelectableByMouse)
        格.addWidget(self.版本標, 0, 0, 1, 4)
        self.授權字 = QLabel(授權說明)
        self.授權字.setObjectName("小標")
        self.授權字.setWordWrap(True)
        self.授權字.setTextInteractionFlags(Qt.TextSelectableByMouse)
        格.addWidget(self.授權字, 1, 0, 1, 4)
        self.授權鈕 = QPushButton("打開授權清單")
        self.授權鈕.setCursor(Qt.PointingHandCursor)
        self.授權鈕.clicked.connect(self.打開授權清單)
        if not app_paths.授權清單資料夾():
            self.授權鈕.setEnabled(False)
            self.授權鈕.setToolTip("打包版才有授權清單（開發環境沒有）")
        格.addWidget(self.授權鈕, 2, 0, 1, 2)
        return 框

    def 打開授權清單(self):
        資料夾 = app_paths.授權清單資料夾()
        if 資料夾:
            os.startfile(資料夾)      # noqa: S606 程式自己的授權清單資料夾

    def _做開發者區(self):
        """開發者選項（預設收起）：顯示文字稿重播模式。"""
        框 = QFrame()
        框.setObjectName("卡片")
        外 = QVBoxLayout(框)
        外.setContentsMargins(16, 10, 16, 12)
        外.setSpacing(8)
        self.開發者鈕 = QPushButton("▸ 開發者選項")
        self.開發者鈕.setCursor(Qt.PointingHandCursor)
        self.開發者鈕.setStyleSheet("QPushButton { border: none; background: transparent; padding: 2px 0px;"
                                 " font-weight: 700; font-size: 15px; text-align: left; }")
        self.開發者鈕.clicked.connect(lambda: self.展開開發者(self.開發者內容.isHidden()))
        外.addWidget(self.開發者鈕, 0, Qt.AlignLeft)
        self.開發者內容 = QWidget()
        內版 = QVBoxLayout(self.開發者內容)
        內版.setContentsMargins(0, 0, 0, 0)
        內版.setSpacing(4)
        self.文字稿勾 = QCheckBox("顯示文字稿重播模式")
        self.文字稿勾.toggled.connect(self._切文字稿模式)
        註 = QLabel("主控台的來源多一個「文字稿檔案」，用已存的直播稿重播測試（開發用）。勾選後立即生效。")
        註.setObjectName("小標")
        註.setWordWrap(True)
        內版.addWidget(self.文字稿勾)
        內版.addWidget(註)
        外.addWidget(self.開發者內容)
        self.開發者內容.hide()
        return 框

    def 展開開發者(self, 開=True):
        self.開發者內容.setVisible(bool(開))
        self.開發者鈕.setText(("▾ " if 開 else "▸ ") + "開發者選項")

    def _切文字稿模式(self, 開):
        ui_state.存旗標(文字稿旗標, bool(開))
        if hasattr(self.主, "套用開發者選項"):
            self.主.套用開發者選項()

    def 打開資料夾(self):
        os.makedirs(app_paths.輸出資料夾(), exist_ok=True)
        os.startfile(app_paths.輸出資料夾())      # noqa: S606 程式自己的輸出資料夾

    # ---------- 表單 ⇄ 設定 ----------
    def 載入(self, 設定=None):
        """把設定（config.載入設定 的格式）放進表單。不給就讀 config.json。
        舊設定（只有 provider＋base_url＋model）自動對到服務與模型：模型不在推薦清單就顯示成「其他（自己輸入）」；服務對不到就是其他相容服務。"""
        if 設定 is None:
            設定 = config.目前設定()
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
            self._查證記憶 = bool(設定["web_verify"])
            self.文字稿勾.blockSignals(True)
            self.文字稿勾.setChecked(ui_state.讀旗標(文字稿旗標))     # 本機的介面設定，不在 config.json
            self.文字稿勾.blockSignals(False)
        finally:
            self._載入中 = False
        self.模型區.載入設定(設定)


    def _更新段位說明(self, *_):
        """字幕速度下方：延遲與準確度、分段與批次設定；並重算下方的每小時費用表。"""
        if "chat" not in getattr(self, "欄", {}) or "費用格" not in self.__dict__:      # 建構途中，表單還沒建完
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
                    minute_sentences=e["minute_sentences"].value(),
                    chat_translate=e["chat_translate"].isChecked(),
                    chat_translate_max_per_min=e["chat_translate_max_per_min"].value(),
                    web_verify=e["web_verify"].isChecked(), **self.模型區._模型設定())

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

    # ---------- 模型服務與模型 ----------

    def _記查證(self, 開):
        if not self._載入中 and self.欄["web_verify"].isEnabled():
            self._查證記憶 = bool(開)

    def _更新查證可用(self):
        """上網查證只有直接連 Claude 時能用：其他服務停用勾選並寫原因；切回 Claude 還原原本的勾選。"""
        可 = self.模型區.目前服務() == "claude"
        w = self.欄["web_verify"]
        w.blockSignals(True)
        w.setChecked(self._查證記憶 if 可 else False)
        w.setEnabled(可)
        w.blockSignals(False)
        self.查證原因.setVisible(not 可)


    def 讀全部(self):
        """回傳要寫進 config.json 的欄位（不含已停用的舊欄位）。服務、網址、模型、單價一起換，舊服務的值不殘留。"""
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
            **self.模型區._模型設定(),
        }
        if self.模型區.目前服務() != model_catalog.設定的服務(config.目前設定()):
            一般["api_key_env"] = api_key.出廠環境變數       # 換了服務：舊服務的環境變數名稱不殘留（出廠值 = 各家預設名稱）
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
        服務 = self.模型區.目前服務()
        if 服務 == model_catalog.其他 and not re.match(r"https?://\S+$", 一般["base_url"]):
            return self._提示("請填「服務網址」（例如 https://example.com/v1）。", 錯=True)
        if not 一般["model"]:
            return self._提示("請先選擇模型（Ollama 要先下載模型）。" if 服務 == "ollama" else "模型名稱不能空白。", 錯=True)
        代號 = self.模型區.金鑰代號()                   # 用寫入前的設定決定是哪個服務（寫入後 provider 可能已改）
        金鑰 = self.模型區.金鑰欄.text().strip() if self.模型區.金鑰欄.isEnabled() else ""
        try:
            config.寫入設定(一般)        # 只更新表單上的欄位；其他欄位（含已停用的 overlay、hotkey_compact）原樣保留；寫之前先備份
        except Exception as e:
            return self._提示(f"儲存失敗：{type(e).__name__}：{e}", 錯=True)
        self.模型區._記住設定(config.目前設定())
        金鑰字 = ""
        if 金鑰:
            try:
                api_key.儲存(代號, 金鑰)       # 金鑰只進認證管理員，不進 config.json
                self.模型區.金鑰欄.clear()
                金鑰字 = "金鑰已儲存在這台電腦。"
            except api_key.金鑰存取錯誤 as e:
                金鑰字 = str(e)
        self.模型區.更新金鑰()
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
    """獨立的「設定」視窗（啟動面板的齒輪、膠囊選單的「設定」）：內容就是上面的 設定頁，不另外寫一份。
    大小：預設依內容算到所有文字都放得下；使用者拉過就記住；超出目前螢幕就縮回螢幕內。"""
    螢幕邊距 = 20

    def __init__(self, 主):
        super().__init__(None, Qt.Window)
        self.主 = 主
        self.setObjectName("根")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("直播摘要 設定")
        self._程式調整 = False        # 程式自己 resize 時不算「使用者拉過」
        self._使用者拉過 = False
        版 = QVBoxLayout(self)
        版.setContentsMargins(8, 8, 8, 8)
        self.頁 = 設定頁(主)
        版.addWidget(self.頁)
        self._調整大小(*self.預設大小())

    def 預設大小(self, 螢幕範圍=None):
        """內容需要的寬度（所有文字、按鈕不截斷）＋捲軸與邊框；高度最多到螢幕的九成，其餘用捲軸。"""
        內 = self.頁.widget()
        內.ensurePolished()
        需要 = 內.sizeHint()
        邊 = self.layout().contentsMargins()
        框 = 2 * self.頁.frameWidth()
        寬 = 需要.width() + self.頁.verticalScrollBar().sizeHint().width() + 邊.left() + 邊.right() + 框 + 4
        高 = 需要.height() + 邊.top() + 邊.bottom() + 框
        if 螢幕範圍 is not None:
            高 = min(高, int(螢幕範圍.height() * 0.9))
        return self.縮進螢幕(寬, 高, 螢幕範圍)

    def 縮進螢幕(self, 寬, 高, 螢幕範圍):
        if 螢幕範圍 is None:
            return 寬, 高
        return (max(200, min(寬, 螢幕範圍.width() - 2 * self.螢幕邊距)),
                max(200, min(高, 螢幕範圍.height() - 2 * self.螢幕邊距)))

    def _調整大小(self, 寬, 高):
        self._程式調整 = True
        try:
            self.resize(寬, 高)
        finally:
            self._程式調整 = False

    def resizeEvent(self, e):
        if self.isVisible() and not self._程式調整:
            self._使用者拉過 = True
        super().resizeEvent(e)

    def hideEvent(self, e):
        if self._使用者拉過:                      # 使用者拉過才記（存在本機的 介面設定.json，不進 git）
            ui_state.存設定框大小(self.width(), self.height())
            self._使用者拉過 = False
        super().hideEvent(e)

    def 打開(self, 螢幕範圍=None, 捲到金鑰=False):
        """每次打開都從 config.json 重新載入（沒按「儲存」的修改不保留，輸入框裡沒存的金鑰也清掉）。放在指定螢幕範圍的中間。
        捲到金鑰：啟動面板「設定金鑰」打開時，捲到金鑰欄。"""
        if not self.isVisible():
            self.頁.模型區.金鑰欄.clear()
            self.頁.模型區.眼睛鈕.setChecked(False)
            self.頁.模型區.金鑰訊息.hide()
            self.頁.載入()
            self.頁.設執行中(self.主.執行中())
            self.頁.狀態字.setText("")
            記住 = ui_state.讀設定框大小()
            寬, 高 = self.縮進螢幕(*記住, 螢幕範圍) if 記住 else self.預設大小(螢幕範圍)
            self._調整大小(寬, 高)
            if 螢幕範圍 is not None:
                self.move(螢幕範圍.center() - self.rect().center())
        self.show()
        self.raise_()
        self.activateWindow()
        if 捲到金鑰:
            self.頁.捲到金鑰()
            QTimer.singleShot(0, self.頁.捲到金鑰)       # 第一次打開時版面還沒排好，排好後再捲一次
