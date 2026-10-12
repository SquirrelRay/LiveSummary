# 設定框（啟動面板的齒輪、膠囊／系統匣選單的「設定」）：功能開關、顯示上限、翻譯批次、模型、存檔
# 按「儲存」才寫回 config.json（寫之前先備份成 config.backup.json）；config.json 裡已停用的舊欄位（overlay、hotkey_compact）原樣保留。
# 金鑰不會出現在這裡，只顯示「已設定／未設定」。
import os
import json
import shutil

from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QFrame, QLabel, QPushButton, QComboBox, QCheckBox, QSpinBox,
    QLineEdit, QGridLayout, QHBoxLayout, QVBoxLayout,
)

import live_topics

備份檔 = os.path.join(os.path.dirname(live_topics.設定檔路徑), "config.backup.json")


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
    def __init__(self, 主):
        super().__init__()
        self.主 = 主                 # 主控台（換內容方向、看是否執行中）
        self._載入中 = False
        self.下次標們 = []           # 「下次開始生效」標籤
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        內 = QWidget()
        版 = QVBoxLayout(內)
        版.setContentsMargins(16, 16, 16, 16)
        版.setSpacing(12)

        上 = QHBoxLayout()
        說明 = QLabel("按「儲存」才會寫回 config.json（會先備份成 config.backup.json）。")
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
        for k in ("ui_max_transcript", "ui_max_chat", "ui_max_translation", "ui_max_summary"):
            e[k] = QSpinBox()
            e[k].setRange(10, 100000)
            e[k].setSuffix(" 則")
        e["newest_on_top"] = QComboBox()
        e["newest_on_top"].addItem("最下面", False)
        e["newest_on_top"].addItem("最上面", True)
        e["newest_on_top"].currentIndexChanged.connect(self._換方向)
        e["minute_sentences"] = QSpinBox()
        e["minute_sentences"].setRange(1, 3)
        e["minute_sentences"].setSuffix(" 句")
        e["translate_batch_seconds"] = QSpinBox()
        e["translate_batch_seconds"].setRange(1, 60)
        e["translate_batch_seconds"].setSuffix(" 秒")
        e["translate_batch_lines"] = QSpinBox()
        e["translate_batch_lines"].setRange(1, 8)
        e["translate_batch_lines"].setSuffix(" 句")
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
        for k in ("chat", "minute_summary", "fix_with_chat", "summary_thinking"):
            加("", e[k], True)
        加("分鐘摘要句數", e["minute_sentences"], True)
        加("最新內容顯示在", e["newest_on_top"])
        加("直播稿分頁最多顯示", e["ui_max_transcript"], True)
        加("聊天室分頁最多顯示", e["ui_max_chat"], True)
        加("逐句翻譯分頁最多顯示", e["ui_max_translation"], True)
        加("摘要分頁最多顯示（分鐘、話題各）", e["ui_max_summary"], True)
        加("翻譯批次：最多等", e["translate_batch_seconds"], True)
        加("翻譯批次：累積", e["translate_batch_lines"], True)
        加("模型服務", e["provider"], True)
        加("模型名稱", e["model"], True)
        加("API 金鑰", self.金鑰字)
        return 框

    存檔項目 = (("save_summary", "摘要（分鐘摘要與話題摘要）"), ("save_transcript", "直播稿"),
              ("save_chat", "聊天室"), ("save_translation", "逐句翻譯"), ("save_audio", "音訊（每 20 秒一段 wav，檔案較大）"))

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
        os.startfile(os.path.dirname(live_topics.設定檔路徑))

    # ---------- 表單 ⇄ 設定 ----------
    def 載入(self, 設定=None):
        """把設定（live_topics.載入設定 的格式）放進表單。不給就讀 config.json。"""
        if 設定 is None:
            設定, _, _ = live_topics.載入設定({})
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
        self.更新金鑰()

    def 更新金鑰(self):
        環境變數 = live_topics.載入設定({})[0]["api_key_env"].strip()
        if not 環境變數:
            self.金鑰字.setText("不需要（api_key_env 留空）")
        else:
            self.金鑰字.setText(("已設定" if os.environ.get(環境變數) else "未設定") + f"（環境變數 {環境變數}）")

    def 讀全部(self):
        """回傳要寫進 config.json 的欄位（不含已停用的舊欄位）。"""
        e = self.欄
        一般 = {
            "subtitle_mode": e["subtitle_mode"].currentData(),
            "chat": e["chat"].isChecked(), "minute_summary": e["minute_summary"].isChecked(),
            "fix_with_chat": e["fix_with_chat"].isChecked(),
            **{k: e[k].isChecked() for k, _ in self.存檔項目},
            "summary_thinking": e["summary_thinking"].isChecked(),
            "minute_sentences": e["minute_sentences"].value(),
            "ui_max_transcript": e["ui_max_transcript"].value(), "ui_max_chat": e["ui_max_chat"].value(),
            "ui_max_translation": e["ui_max_translation"].value(), "newest_on_top": bool(e["newest_on_top"].currentData()),
            "ui_max_summary": e["ui_max_summary"].value(),
            "translate_batch_seconds": e["translate_batch_seconds"].value(),
            "translate_batch_lines": e["translate_batch_lines"].value(),
            "provider": e["provider"].currentData(), "model": e["model"].text().strip(),
        }
        return 一般

    # ---------- 立即生效的項目 ----------
    def _換方向(self, *_):
        """選了「最新內容顯示在」就立刻重新排列所有分頁（按「儲存」才寫進 config.json）。"""
        if not self._載入中:
            self.主.設方向(bool(self.欄["newest_on_top"].currentData()))

    # ---------- 執行中提示 ----------
    def 設執行中(self, 執行中):
        for w in self.下次標們:
            w.setVisible(執行中)

    # ---------- 儲存、還原 ----------
    def 儲存(self):
        一般 = self.讀全部()
        if not 一般["model"]:
            return self._提示("模型名稱不能空白。", 錯=True)
        路徑 = live_topics.設定檔路徑
        try:
            原本 = {}
            if os.path.exists(路徑):
                shutil.copy2(路徑, 備份檔)          # 寫之前先備份
                with open(路徑, encoding="utf-8-sig") as f:
                    原本 = json.load(f)
                if not isinstance(原本, dict):
                    原本 = {}
            原本.update(一般)              # 只更新表單上的欄位；其他欄位（含已停用的 overlay、hotkey_compact）原樣保留
            with open(路徑, "w", encoding="utf-8") as f:
                json.dump(原本, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception as e:
            return self._提示(f"儲存失敗：{type(e).__name__}：{e}", 錯=True)
        字 = "已儲存到 config.json（舊的設定備份在 config.backup.json）。"
        if self.主.執行中():
            字 += "標示「下次開始生效」的項目，要等下次按「開始」才會用新的設定。"
        self._提示(字)

    def 還原預設(self):
        self.載入(live_topics.內建預設())
        self.主.設方向(bool(self.欄["newest_on_top"].currentData()))
        self._提示("已還原成預設值。按「儲存」才會寫入 config.json。")

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

    def 打開(self, 螢幕範圍=None):
        """每次打開都從 config.json 重新載入（沒按「儲存」的修改不保留）。放在指定螢幕範圍的中間。"""
        if not self.isVisible():
            self.頁.載入()
            self.頁.設執行中(self.主.執行中())
            self.頁.狀態字.setText("")
            if 螢幕範圍 is not None:
                self.resize(min(820, 螢幕範圍.width() - 40), min(760, 螢幕範圍.height() - 40))
                self.move(螢幕範圍.center() - self.rect().center())
        self.show()
        self.raise_()
        self.activateWindow()
