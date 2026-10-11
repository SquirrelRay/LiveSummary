# 主控台的「設定」分頁：調整兩個字幕框的樣式與位置、功能開關、快捷鍵、模型
# 調整樣式時疊加層會即時預覽；按「儲存」才寫回 config.json（寫之前先備份成 config.backup.json）。
# 金鑰不會出現在這裡，只顯示「已設定／未設定」。
import os
import json
import shutil

from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QFrame, QLabel, QPushButton, QComboBox, QCheckBox, QSlider, QSpinBox,
    QLineEdit, QFontComboBox, QColorDialog, QGridLayout, QHBoxLayout, QVBoxLayout,
)

import llm
import live_topics
import overlay

備份檔 = os.path.join(os.path.dirname(live_topics.設定檔路徑), "config.backup.json")


def 小標(字):
    w = QLabel(字)
    w.setObjectName("淡")
    return w


class 滑桿(QWidget):
    """滑桿 + 右邊顯示數值。"""

    def __init__(self, 最小, 最大, 格式=str):
        super().__init__()
        版 = QHBoxLayout(self)
        版.setContentsMargins(0, 0, 0, 0)
        self.桿 = QSlider(Qt.Horizontal)
        self.桿.setRange(最小, 最大)
        self.字 = QLabel()
        self.字.setMinimumWidth(56)
        self.格式 = 格式
        self.桿.valueChanged.connect(lambda v: self.字.setText(self.格式(v)))
        版.addWidget(self.桿, 1)
        版.addWidget(self.字)

    def 值(self):
        return self.桿.value()

    def 設值(self, v):
        self.桿.setValue(int(round(v)))
        self.字.setText(self.格式(self.桿.value()))


class 顏色鈕(QPushButton):
    def __init__(self, 改了):
        super().__init__()
        self.色 = "#ffffff"
        self.改了 = 改了
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._選)

    def 設值(self, 色):
        self.色 = 色
        文字色 = "#000000" if QColor(色).lightness() > 140 else "#ffffff"
        self.setText(色)
        self.setStyleSheet(f"background: {色}; color: {文字色}; border: 1px solid #2a2e3a; border-radius: 10px;")

    def _選(self):
        色 = QColorDialog.getColor(QColor(self.色), self, "選擇顏色")
        if 色.isValid():
            self.設值(色.name())
            self.改了()


class 滾輪過濾(QObject):
    """滑桿、數字欄位、下拉選單：沒有點選（沒有取得焦點）時不吃滑鼠滾輪，改成捲動整個設定頁，避免捲頁面時誤改數值。"""

    def __init__(self, 捲動區):
        super().__init__(捲動區)
        self.捲動區 = 捲動區

    def eventFilter(self, 物, e):
        if e.type() == QEvent.Wheel and not 物.hasFocus():
            QApplication.sendEvent(self.捲動區.verticalScrollBar(), e)
            return True
        return False


class 設定頁(QScrollArea):
    def __init__(self, 主):
        super().__init__()
        self.主 = 主                 # 主控台（拿兩個框、重新註冊快捷鍵）
        self._載入中 = False
        self.下次標們 = []           # 「下次開始生效」標籤
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        內 = QWidget()
        版 = QVBoxLayout(內)
        版.setContentsMargins(16, 16, 16, 16)
        版.setSpacing(12)

        上 = QHBoxLayout()
        說明 = QLabel("調整樣式時字幕框會即時預覽；按「儲存」才會寫回 config.json（會先備份成 config.backup.json）。")
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

        self.框欄 = {}
        版.addWidget(self._做框區("summary_box", "摘要框（預設在螢幕上緣）"))
        版.addWidget(self._做框區("subtitle_box", "字幕框（預設在螢幕下緣）"))
        版.addWidget(self._做一般區())
        版.addStretch(1)
        self.setWidget(內)
        self._滾輪 = 滾輪過濾(self)
        for w in (w for w in 內.findChildren(QWidget) if isinstance(w, (QSlider, QSpinBox, QComboBox))):
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

    def _做框區(self, 鍵, 標題):
        框, 格 = self._面板(標題)
        欄 = {}
        預覽 = lambda *_: self._預覽(鍵)
        欄["show"] = QCheckBox("按 Ctrl+Shift+S 同時開關時，顯示這個框")
        欄["font"] = QFontComboBox()
        欄["font_size"] = 滑桿(10, 72, lambda v: f"{v} px")
        欄["text_color"] = 顏色鈕(預覽)
        欄["bg_color"] = 顏色鈕(預覽)
        欄["bg_opacity"] = 滑桿(0, 100, lambda v: f"{v}%")
        欄["text_effect"] = QComboBox()
        for 名, 值 in (("陰影", "shadow"), ("描邊", "outline"), ("無", "none")):
            欄["text_effect"].addItem(名, 值)
        欄["fade_seconds"] = QSpinBox()
        欄["fade_seconds"].setRange(0, 600)
        欄["fade_seconds"].setSpecialValueText("不淡出")
        欄["fade_seconds"].setSuffix(" 秒")
        欄["position"] = QComboBox()
        for 名, 值 in (("停靠上緣", "top"), ("停靠下緣", "bottom"), ("自由位置（拖曳）", "free")):
            欄["position"].addItem(名, 值)
        欄["screen"] = QComboBox()
        for i, s in enumerate(QGuiApplication.screens()):
            欄["screen"].addItem(f"螢幕 {i}" + ("（主螢幕）" if i == 0 else "") + f"  {s.geometry().width()}×{s.geometry().height()}", i)
        最寬 = max(s.geometry().width() for s in QGuiApplication.screens())
        欄["width"] = 滑桿(300, 最寬, lambda v: f"{v} px")
        項目 = [("字型", "font"), ("字級", "font_size"), ("文字顏色", "text_color"), ("背景色", "bg_color"),
              ("背景透明度", "bg_opacity"), ("文字效果", "text_effect"), ("幾秒沒更新就淡出", "fade_seconds"),
              ("位置", "position"), ("螢幕", "screen"), ("寬度（高度自動）", "width")]
        if 鍵 == "summary_box":
            欄["show_minute"] = QCheckBox("分鐘摘要")
            欄["show_topic"] = QCheckBox("目前話題")
            欄["show_side"] = QCheckBox("支線")
            欄["show_audience"] = QCheckBox("觀眾反應")
            欄["max_lines"] = QSpinBox()
            欄["max_lines"].setRange(1, 8)
            欄["max_lines"].setSuffix(" 行")
            項目.append(("分鐘摘要最多", "max_lines"))
        else:
            欄["lines"] = QComboBox()
            欄["lines"].addItem("最近 1 句", 1)
            欄["lines"].addItem("最近 2 句", 2)
            項目.append(("顯示句數", "lines"))
        格.addWidget(欄["show"], 0, 0, 1, 4)
        for i, (名, k) in enumerate(項目):
            列, 行 = 1 + i // 2, (i % 2) * 2
            格.addWidget(小標(名), 列, 行)
            格.addWidget(欄[k], 列, 行 + 1)
        if 鍵 == "summary_box":
            列 = 2 + len(項目) // 2
            勾們 = QHBoxLayout()
            勾們.addWidget(小標("要顯示的項目"))
            for k in ("show_minute", "show_topic", "show_side", "show_audience"):
                勾們.addWidget(欄[k])
            勾們.addStretch(1)
            格.addLayout(勾們, 列, 0, 1, 4)
        # 任何一個改了就即時預覽
        for k, w in 欄.items():
            if isinstance(w, QCheckBox):
                w.toggled.connect(預覽)
            elif isinstance(w, QFontComboBox):
                w.currentFontChanged.connect(預覽)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(預覽)
            elif isinstance(w, QSpinBox):
                w.valueChanged.connect(預覽)
            elif isinstance(w, 滑桿):
                w.桿.valueChanged.connect(預覽)
        self.框欄[鍵] = 欄
        return 框

    def _下次(self):
        w = QLabel("下次開始生效")
        w.setStyleSheet("color: #f5b84a; font-size: 12px;")
        w.hide()
        self.下次標們.append(w)
        return w

    def _做一般區(self):
        框, 格 = self._面板("功能、快捷鍵與模型")
        self.欄 = {}
        e = self.欄
        e["subtitle_mode"] = QComboBox()
        for 名, 值 in (("自動（中文用原文，其他語言翻譯）", "auto"), ("原文", "original"), ("翻譯成繁中", "translate")):
            e["subtitle_mode"].addItem(名, 值)
        e["chat"] = QCheckBox("抓聊天室（直播網址模式）")
        e["minute_summary"] = QCheckBox("分鐘摘要")
        e["save_audio"] = QCheckBox("存音訊（直播網址模式）")
        e["fix_with_chat"] = QCheckBox("用聊天室參考詞修正專有名詞")
        e["summary_thinking"] = QCheckBox("摘要使用延伸思考：較準但較貴")
        for k in ("ui_max_transcript", "ui_max_chat", "ui_max_translation", "ui_max_summary"):
            e[k] = QSpinBox()
            e[k].setRange(10, 100000)
            e[k].setSuffix(" 則")
        e["minute_sentences"] = QSpinBox()
        e["minute_sentences"].setRange(1, 3)
        e["minute_sentences"].setSuffix(" 句")
        e["translate_batch_seconds"] = QSpinBox()
        e["translate_batch_seconds"].setRange(1, 60)
        e["translate_batch_seconds"].setSuffix(" 秒")
        e["translate_batch_lines"] = QSpinBox()
        e["translate_batch_lines"].setRange(1, 8)
        e["translate_batch_lines"].setSuffix(" 句")
        e["click_through"] = QCheckBox("字幕框一開啟就是滑鼠穿透")
        for k in ("hotkey_toggle", "hotkey_summary", "hotkey_subtitle", "hotkey_click_through"):
            e[k] = QLineEdit()
            e[k].setPlaceholderText("例如 Ctrl+Shift+S")
        e["provider"] = QComboBox()
        e["provider"].addItem("Claude（anthropic）", "anthropic")
        e["provider"].addItem("OpenAI 相容（openai_compatible）", "openai_compatible")
        e["model"] = QLineEdit()
        self.金鑰字 = QLabel()

        列 = 0

        def 加(名, w, 下次=False):
            nonlocal 列
            格.addWidget(小標(名), 列, 0)
            格.addWidget(w, 列, 1, 1, 2)
            if 下次:
                格.addWidget(self._下次(), 列, 3)
            列 += 1

        加("逐句字幕模式", e["subtitle_mode"], True)
        for k in ("chat", "minute_summary", "save_audio", "fix_with_chat", "summary_thinking"):
            加("", e[k], True)
        加("分鐘摘要句數", e["minute_sentences"], True)
        加("直播稿分頁最多顯示", e["ui_max_transcript"], True)
        加("聊天室分頁最多顯示", e["ui_max_chat"], True)
        加("逐句翻譯分頁最多顯示", e["ui_max_translation"], True)
        加("摘要分頁最多顯示（分鐘、話題各）", e["ui_max_summary"], True)
        加("翻譯批次：最多等", e["translate_batch_seconds"], True)
        加("翻譯批次：累積", e["translate_batch_lines"], True)
        加("", e["click_through"])
        加("同時開關兩個框", e["hotkey_toggle"])
        加("只開關摘要框", e["hotkey_summary"])
        加("只開關字幕框", e["hotkey_subtitle"])
        加("切換滑鼠穿透", e["hotkey_click_through"])
        加("模型服務", e["provider"], True)
        加("模型名稱", e["model"], True)
        加("API 金鑰", self.金鑰字)
        return 框

    # ---------- 表單 ⇄ 設定 ----------
    def 載入(self, 設定=None):
        """把設定（live_topics.載入設定 的格式）放進表單。不給就讀 config.json，位置用兩個框目前的實際位置。"""
        if 設定 is None:
            設定, _, _ = live_topics.載入設定({})
            ov, _ = overlay.讀設定(設定["overlay"])
            for 框 in self.主.框們():
                ov[框.設定鍵].update(框.目前位置設定())
        else:
            ov, _ = overlay.讀設定(設定["overlay"])
        self._載入中 = True
        try:
            for 鍵, 欄 in self.框欄.items():
                s = ov[鍵]
                for k, w in 欄.items():
                    v = s[k]
                    if k == "bg_opacity":
                        w.設值(v * 100)
                    elif isinstance(w, 滑桿):
                        w.設值(v)
                    elif isinstance(w, 顏色鈕):
                        w.設值(v)
                    elif isinstance(w, QCheckBox):
                        w.setChecked(v)
                    elif isinstance(w, QFontComboBox):
                        w.setCurrentFont(v)
                    elif isinstance(w, QComboBox):
                        w.setCurrentIndex(max(0, w.findData(v)))
                    elif isinstance(w, QSpinBox):
                        w.setValue(int(v))
            e = self.欄
            for k, w in e.items():
                v = ov[k] if k in overlay.共用預設 else 設定[k]
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
        self.更新金鑰()

    def 同步位置(self):
        """切到設定分頁時：位置、寬度、螢幕改成兩個框目前的實際狀態（拖曳過會變成自由位置）。"""
        self._載入中 = True
        try:
            for 框 in self.主.框們():
                欄 = self.框欄[框.設定鍵]
                現在 = 框.目前位置設定()
                欄["position"].setCurrentIndex(max(0, 欄["position"].findData(現在["position"])))
                欄["screen"].setCurrentIndex(max(0, 欄["screen"].findData(現在["screen"])))
                欄["width"].設值(現在["width"])
        finally:
            self._載入中 = False
        self.更新金鑰()

    def 更新金鑰(self):
        環境變數 = live_topics.載入設定({})[0]["api_key_env"].strip()
        if not 環境變數:
            self.金鑰字.setText("不需要（api_key_env 留空）")
        else:
            self.金鑰字.setText(("已設定" if os.environ.get(環境變數) else "未設定") + f"（環境變數 {環境變數}）")

    def 讀框(self, 鍵):
        s = {}
        for k, w in self.框欄[鍵].items():
            if k == "bg_opacity":
                s[k] = round(w.值() / 100, 2)
            elif isinstance(w, 滑桿):
                s[k] = w.值()
            elif isinstance(w, 顏色鈕):
                s[k] = w.色
            elif isinstance(w, QCheckBox):
                s[k] = w.isChecked()
            elif isinstance(w, QFontComboBox):
                s[k] = w.currentFont().family()
            elif isinstance(w, QComboBox):
                s[k] = w.currentData()
            elif isinstance(w, QSpinBox):
                s[k] = w.value()
        return s

    def 讀全部(self):
        """回傳 (要寫進 config.json 的欄位, overlay 區塊)。"""
        e = self.欄
        一般 = {
            "subtitle_mode": e["subtitle_mode"].currentData(),
            "chat": e["chat"].isChecked(), "minute_summary": e["minute_summary"].isChecked(),
            "save_audio": e["save_audio"].isChecked(), "fix_with_chat": e["fix_with_chat"].isChecked(),
            "summary_thinking": e["summary_thinking"].isChecked(),
            "minute_sentences": e["minute_sentences"].value(),
            "ui_max_transcript": e["ui_max_transcript"].value(), "ui_max_chat": e["ui_max_chat"].value(),
            "ui_max_translation": e["ui_max_translation"].value(),
            "ui_max_summary": e["ui_max_summary"].value(),
            "translate_batch_seconds": e["translate_batch_seconds"].value(),
            "translate_batch_lines": e["translate_batch_lines"].value(),
            "provider": e["provider"].currentData(), "model": e["model"].text().strip(),
        }
        ov = {"click_through": e["click_through"].isChecked()}
        for k in ("hotkey_toggle", "hotkey_summary", "hotkey_subtitle", "hotkey_click_through"):
            ov[k] = e[k].text().strip()
        ov["summary_box"] = self.讀框("summary_box")
        ov["subtitle_box"] = self.讀框("subtitle_box")
        return 一般, ov

    # ---------- 即時預覽 ----------
    def _預覽(self, 鍵):
        if self._載入中:
            return
        框 = self.主.框(鍵)
        框.套用設定(self.讀框(鍵), 動位置=True)
        if not 框.開啟:
            self.主.開關框(框, True)

    # ---------- 執行中提示 ----------
    def 設執行中(self, 執行中):
        for w in self.下次標們:
            w.setVisible(執行中)

    # ---------- 儲存、還原 ----------
    def 儲存(self):
        一般, ov = self.讀全部()
        if not 一般["model"]:
            return self._提示("模型名稱不能空白。", 錯=True)
        鍵們 = [ov[k] for k in ("hotkey_toggle", "hotkey_summary", "hotkey_subtitle", "hotkey_click_through")]
        for 鍵 in 鍵們:
            if not overlay.解析快捷鍵(鍵):
                return self._提示(f"快捷鍵「{鍵}」看不懂，請寫成像 Ctrl+Shift+S 這樣（最後一個是英文字母、數字或 F1~F12）。", 錯=True)
        if len({k.lower().replace(" ", "") for k in 鍵們}) < 4:
            return self._提示("四個快捷鍵不能重複，請改成不同的按鍵。", 錯=True)
        路徑 = live_topics.設定檔路徑
        try:
            原本 = {}
            if os.path.exists(路徑):
                shutil.copy2(路徑, 備份檔)          # 寫之前先備份
                with open(路徑, encoding="utf-8-sig") as f:
                    原本 = json.load(f)
                if not isinstance(原本, dict):
                    原本 = {}
            原本.update(一般)
            原本["overlay"] = ov
            with open(路徑, "w", encoding="utf-8") as f:
                json.dump(原本, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception as e:
            return self._提示(f"儲存失敗：{type(e).__name__}：{e}", 錯=True)
        for 框 in self.主.框們():
            框.存檔後(ov[框.設定鍵])
        問題們 = self.主.註冊快捷鍵(ov)
        字 = "已儲存到 config.json（舊的設定備份在 config.backup.json）。"
        if self.主.執行中():
            字 += "標示「下次開始生效」的項目，要等下次按「開始」才會用新的設定。"
        if 問題們:
            字 += "\n" + "　".join(問題們)
        self._提示(字, 錯=bool(問題們))

    def 還原預設(self):
        設定 = live_topics.內建預設()
        設定["overlay"] = overlay.預設設定()
        self.載入(設定)
        for 鍵 in self.框欄:
            self._預覽(鍵)
        self._提示("已還原成預設值，字幕框已預覽。按「儲存」才會寫入 config.json。")

    def _提示(self, 字, 錯=False):
        self.狀態字.setStyleSheet(f"color: {'#ff5c7a' if 錯 else '#3ecf8e'};")
        self.狀態字.setText(字)
