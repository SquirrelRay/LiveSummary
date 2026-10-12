"""介面冒煙測試（offscreen，不開真的視窗）：主控台、啟動面板、膠囊、面板一起跑。
全部用假模型（llm.call_llm 換掉）、假引擎（直播流程用假的 live_topics.執行），不花 API、不連網、不需要 ffmpeg／streamlink。
本機記憶檔（網址紀錄、介面設定、版面配置、啟動里程碑、config.json）全部換到暫存資料夾，不會動到專案裡的檔案。
「沒有未處理的例外」：攔下 sys.excepthook（Qt 槽函式裡的例外會走這裡）與 threading.excepthook，並檢查 stderr 沒有 Traceback。"""
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

import app
import capsule
import events
import live_topics
import llm
import panel
import settings_page
import startup_timeline
import subtitle
import ui_state

專案設定 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")


# ---------- 假模型 ----------
class 假模型:
    def __init__(self):
        self.翻譯次數 = 0
        self.摘要次數 = 0

    def __call__(self, 提示詞, 模型=None, 類別="摘要"):
        if 類別 == "翻譯":
            self.翻譯次數 += 1
            n = len(re.findall(r"^\d+\. ", 提示詞, re.MULTILINE))
            return json.dumps([f"假譯文{i + 1}" for i in range(n)], ensure_ascii=False)
        self.摘要次數 += 1
        if '"decision"' in 提示詞:
            return json.dumps({"decision": "same", "topic_brief": "假話題", "side_notes": [],
                               "minute_summary": {"summary": "[00:10] 假的分鐘摘要", "audience": ""}}, ensure_ascii=False)
        return "【話題標題】假話題\n【摘要】假的話題摘要"


def 等(條件, 秒=15):
    """一邊處理 Qt 事件一邊等，條件成立回傳 True。"""
    終 = time.time() + 秒
    while time.time() < 終:
        QApplication.processEvents()
        if 條件():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return 條件()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def 環境(qapp, tmp_path, monkeypatch, capfd):
    設定檔 = tmp_path / "config.json"
    if os.path.exists(專案設定):
        shutil.copy2(專案設定, 設定檔)            # 用現有的 config.json（含舊的 overlay 區塊）
    else:
        設定檔.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(live_topics, "設定檔路徑", str(設定檔))
    monkeypatch.setattr(settings_page, "備份檔", str(tmp_path / "config.backup.json"))
    monkeypatch.setattr(ui_state, "網址紀錄檔", str(tmp_path / "網址紀錄.json"))
    monkeypatch.setattr(ui_state, "介面設定檔", str(tmp_path / "介面設定.json"))
    monkeypatch.setattr(panel, "版面檔", str(tmp_path / "版面配置.json"))
    monkeypatch.setattr(startup_timeline.紀錄, "資料夾", str(tmp_path / "logs"))
    模型 = 假模型()
    monkeypatch.setattr(llm, "call_llm", 模型)
    monkeypatch.setattr(llm, "檢查金鑰", lambda: None)
    monkeypatch.setattr(capsule, "確認", lambda *a: True)
    例外們 = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: 例外們.append(a))
    monkeypatch.setattr(threading, "excepthook", lambda a: 例外們.append(a))
    events.停止.clear()
    events.重新偵測.clear()
    舊接收者 = list(events.接收者們)

    台 = app.主控台()
    台.膠囊.顯示()
    台.啟動面板.顯示()
    yield {"台": 台, "模型": 模型, "暫存": tmp_path, "設定檔": 設定檔, "例外們": 例外們}

    if 台.執行中():                         # 收尾：還在跑就停掉
        events.停止.set()
        等(lambda: not 台.執行中(), 15)
    台.要結束 = True
    台.close()
    台.字幕器.結束()
    QApplication.instance().removeEventFilter(台.面板)
    台.面板.懸停計時.stop()
    QApplication.processEvents()
    events.接收者們[:] = 舊接收者
    events.停止.clear()
    assert 例外們 == [], f"有未處理的例外：{例外們}"
    assert "Traceback" not in capfd.readouterr().err


# ---------- 假直播引擎：送出 files 後一直等到按停止（或測試叫它送錯誤） ----------
class 假引擎:
    def __init__(self, 錯誤訊息=None):
        self.送錯誤 = threading.Event()
        self.錯誤訊息 = 錯誤訊息

    def __call__(self, 設定, 檔案=None, 網址=None, speed=0, 聊天檔=None):
        events.送出("stage", 階段="檢查直播")
        events.送出("files", 基底="假基底", 稿=None, 聊天=None, 分鐘=None, 話題=None)
        while not events.停止.is_set():
            if self.送錯誤.is_set():
                events.送出("error", 訊息=self.錯誤訊息, 印出=self.錯誤訊息)
                return False
            time.sleep(0.02)
        events.送出("finished", 話題數=0, 檔案們=[], 印出="完成")
        return True


def 從啟動面板開始(台, monkeypatch, 引擎):
    monkeypatch.setattr(live_topics, "執行", 引擎)
    啟 = 台.啟動面板
    啟.網址框.setText("https://www.twitch.tv/假頻道")
    啟.語言選.setCurrentIndex(啟.語言選.findData("auto"))
    啟.開始()
    assert 等(lambda: not 啟.isVisible() and 台.面板.面板們), "啟動面板沒有收起、面板沒有出現"


def 停止並等完(台):
    台.膠囊.問停止()
    assert 等(lambda: not 台.執行中() and 台.開始鈕.isEnabled(), 20)


def 送句子(句們):
    for i, 字 in enumerate(句們):
        events.送出("transcript_line", 秒=i, 時間字=f"00:{i:02d}", 內容=字, 行=f"[00:{i:02d}] {字}")


def 選單文字(台):
    m = QMenu()
    台.膠囊.填選單(m)
    return [a.text() if not a.isSeparator() else "—" for a in m.actions()]


# ---------- 1. 主控台跑完一次文字稿重播 ----------
def test_主控台文字稿重播_跑完沒有例外(環境):
    台 = 環境["台"]
    稿 = 環境["暫存"] / "假文字稿.txt"
    稿.write_text("\n".join(f"[{s // 60:02d}:{s % 60:02d}] テスト{s}です" for s in range(0, 200, 5)), encoding="utf-8")
    台.檔案鈕.setChecked(True)
    台._切換來源()
    台.檔案框.setText(str(稿))
    台.速度選.setCurrentIndex(台.速度選.findData(0))
    台.語言選.setCurrentIndex(台.語言選.findData("ja"))
    台.開始()
    assert 台.執行中()
    assert 等(lambda: not 台.執行中() and 台.開始鈕.isEnabled(), 30)
    assert 台.稿頁.總數 == 40
    assert 台.分鐘頁.總數 > 0 and 台.話題頁.總數 > 0
    assert 環境["模型"].摘要次數 > 0


# ---------- 2. 新流程：啟動面板 → 膠囊 → 字幕樣式面板 ----------
def test_新流程_啟動面板到字幕樣式面板(環境, monkeypatch):
    台 = 環境["台"]
    從啟動面板開始(台, monkeypatch, 假引擎())
    assert not 台.isVisible()                                  # 主控台收著
    assert 台.膠囊.膠囊.isVisible()
    字幕面 = 台.面板.面板們["逐句翻譯"]                          # 預設版面：逐句翻譯是字幕樣式
    assert 字幕面.設["樣式"] == "字幕"
    assert 台.字幕器.啟用
    台.字幕器.模式, 台.字幕器.語言 = "translate", "ja"
    送句子(["こんにちは", "今日は配信です"])
    assert 等(lambda: "假譯文" in 字幕面.字幕字.text(), 15), 字幕面.字幕字.text()
    停止並等完(台)


# ---------- 3. 翻譯開關只看逐句翻譯面板 ----------
def test_沒開逐句翻譯面板就不翻譯_開了就翻譯(環境, monkeypatch):
    台, 模型 = 環境["台"], 環境["模型"]
    從啟動面板開始(台, monkeypatch, 假引擎())
    台.字幕器.模式, 台.字幕器.語言 = "translate", "ja"

    台.面板.開關("逐句翻譯", False)                             # 只剩分鐘摘要、話題摘要面板（都不需要翻譯）
    assert not 台.字幕器.啟用
    送句子(["一つ目", "二つ目", "三つ目"])
    等(lambda: False, 1.5)                                       # 給翻譯執行緒時間：確認真的沒翻
    assert 模型.翻譯次數 == 0
    assert "逐句翻譯面板沒有開" in 台.翻譯頁.註.text()

    台.面板.開關("逐句翻譯", True)
    assert 台.字幕器.啟用
    送句子(["四つ目", "五つ目"])
    assert 等(lambda: 模型.翻譯次數 > 0, 15)
    assert 等(lambda: any("假譯文" in str(項[1]) for 項 in 台.面板.紀錄們["逐句翻譯"].項目們), 5)
    停止並等完(台)


# ---------- 4. 語言低信心：膠囊「⚠ 語言」、提示泡、重新偵測成功後消失、停止後不殘留 ----------
def test_語言低信心_膠囊警告與消失(環境, monkeypatch):
    台 = 環境["台"]
    膠 = 台.膠囊
    從啟動面板開始(台, monkeypatch, 假引擎())
    assert not 台.isVisible()
    assert ("⚠ 語言", capsule.黃) not in 膠.膠囊.文字段們()

    events.送出("language_detected", 語言="zh", 信心=0.2, 狀態="低信心", 重新偵測=False)
    QApplication.processEvents()
    assert ("⚠ 語言", capsule.黃) in 膠.膠囊.文字段們()
    assert 膠.提示泡.isVisible() and "偵測不確定" in 膠.提示泡.text() and 膠.提示泡.錯誤 is None
    assert "⚠ 語言：中文（偵測不確定" in 膠.膠囊.toolTip()
    assert "⚠ 語言：中文（偵測不確定" in 膠.系統匣.toolTip()
    項 = 選單文字(台)
    assert 項[:4] == ["停止", "—", "⚠ " + 台.語言狀態.文字(), "重新偵測語言"], 項    # 開始…／停止 下方第一組
    assert 項[4] == "—" and 項[5] == "面板"

    台.重新偵測語言()
    events.送出("language_detected", 語言="ja", 信心=0.9, 狀態="ok", 重新偵測=True)
    QApplication.processEvents()
    膠.更新()
    assert ("⚠ 語言", capsule.黃) not in 膠.膠囊.文字段們()          # 重新偵測成功：標記消失
    assert "⚠" not in 膠.膠囊.toolTip() and "語言：日文（自動偵測）" in 膠.膠囊.toolTip()

    events.送出("language_detected", 語言="ja", 信心=0.2, 狀態="低信心", 重新偵測=True)
    QApplication.processEvents()
    assert 膠.語言警示()                                             # 重新偵測又不確定：標記回來
    停止並等完(台)
    膠.更新()
    assert not 膠.語言警示()                                         # 停止後不殘留
    assert all(字 != "⚠ 語言" for 字, _ in 膠.膠囊.文字段們())
    assert "⚠" not in 膠.膠囊.toolTip() and "⚠" not in 膠.系統匣.toolTip()
    assert not any("語言" in t for t in 選單文字(台))


# ---------- 5. 直播中途的錯誤、config.json 警告：膠囊旁顯示中文提示 ----------
def test_直播中途錯誤_膠囊旁顯示中文(環境, monkeypatch):
    台 = 環境["台"]
    引擎 = 假引擎("金鑰無效，請確認 ANTHROPIC_API_KEY。")
    從啟動面板開始(台, monkeypatch, 引擎)
    引擎.送錯誤.set()
    assert 等(lambda: not 台.執行中() and 台.開始鈕.isEnabled(), 10)     # 跑完了（錯誤事件在它之前已處理）
    assert not 台.isVisible()
    泡 = 台.膠囊.提示泡
    assert 泡.isVisible() and 泡.錯誤 is True
    assert 泡.text() == "已停止：金鑰無效，請確認 ANTHROPIC_API_KEY。"
    assert not 台.啟動面板.isVisible()                               # 中途錯誤不會把啟動面板叫回來


def test_啟動中的錯誤_由啟動面板顯示_膠囊不重複(環境, monkeypatch):
    台 = 環境["台"]

    def 開不了(設定, **_):
        time.sleep(0.3)                    # 像真的引擎一樣先花一點時間（檢查直播），才回報錯誤
        events.送出("error", 訊息="這個頻道目前沒有開播。", 印出="")
        return False
    monkeypatch.setattr(live_topics, "執行", 開不了)
    台.啟動面板.網址框.setText("https://www.twitch.tv/假頻道")
    台.啟動面板.開始()
    assert 等(lambda: not 台.執行中() and 台.開始鈕.isEnabled(), 10)
    assert "沒有開播" in 台.啟動面板.狀態字.text()
    assert not (hasattr(台.膠囊, "提示泡") and 台.膠囊.提示泡.isVisible())


def test_config警告_膠囊旁顯示(環境, monkeypatch):
    台 = 環境["台"]
    內容 = json.loads(環境["設定檔"].read_text(encoding="utf-8-sig"))
    內容["chat"] = "要"                                               # 不合法的值
    環境["設定檔"].write_text(json.dumps(內容, ensure_ascii=False), encoding="utf-8")
    從啟動面板開始(台, monkeypatch, 假引擎())
    泡 = 台.膠囊.提示泡
    assert 泡.錯誤 is True and "config.json 設定有問題" in 泡.text() and "chat" in 泡.text()
    停止並等完(台)


# ---------- 6. 設定框儲存：舊的 overlay 區塊、hotkey_compact 原樣保留，寫入前備份 ----------
def test_設定框儲存_保留舊區塊並備份(環境):
    台, 設定檔 = 環境["台"], 環境["設定檔"]
    原本 = json.loads(設定檔.read_text(encoding="utf-8-sig"))
    原本["overlay"] = {"click_through": True, "summary_box": {"font_size": 17}, "subtitle_box": {"lines": 2}}
    原本["hotkey_compact"] = "Ctrl+Shift+M"
    設定檔.write_text(json.dumps(原本, ensure_ascii=False, indent=2), encoding="utf-8")
    寫前 = 設定檔.read_text(encoding="utf-8")

    台.開設定框()
    頁 = 台.設定框.頁
    頁.欄["minute_sentences"].setValue(3)
    頁.儲存()
    之後 = json.loads(設定檔.read_text(encoding="utf-8"))
    assert 之後["overlay"] == 原本["overlay"]
    assert 之後["hotkey_compact"] == "Ctrl+Shift+M"
    assert 之後["minute_sentences"] == 3
    assert (環境["暫存"] / "config.backup.json").read_text(encoding="utf-8") == 寫前
    assert live_topics.載入設定({})[2] == []
    assert "已儲存" in 頁.狀態字.text()


# ---------- 7. 字幕速度段位：啟動面板三段選擇（只影響這一場、啟動中與直播中不能改）、設定框說明與儲存 ----------
class 慢引擎(假引擎):
    """送出 files 之前先等 放行（模擬「啟動中」），並記下這一場拿到的段位。"""

    def __init__(self):
        super().__init__()
        self.放行 = threading.Event()
        self.段位 = None

    def __call__(self, 設定, **k):
        self.段位 = 設定["subtitle_speed"]
        events.送出("stage", 階段="檢查直播")
        self.放行.wait(10)
        return super().__call__(設定, **k)


def _拿掉段位欄位(設定檔):
    內容 = json.loads(設定檔.read_text(encoding="utf-8-sig"))
    內容.pop("subtitle_speed", None)
    內容["translate_batch_seconds"], 內容["translate_batch_lines"] = 8, 4      # 舊版的翻譯批次欄位
    設定檔.write_text(json.dumps(內容, ensure_ascii=False, indent=2), encoding="utf-8")
    return 內容


def test_啟動面板_字幕速度_選了只影響這一場_啟動中與直播中不能改(環境, monkeypatch):
    台, 設定檔 = 環境["台"], 環境["設定檔"]
    _拿掉段位欄位(設定檔)
    寫前 = 設定檔.read_text(encoding="utf-8")
    啟 = 台.啟動面板
    啟.hide()
    啟.顯示()                                                        # 重新打開：回到 config.json 的值（沒有欄位 = 平衡）
    assert 啟.段位() == "balanced"
    assert all(b.isEnabled() for b in 啟.段位鈕們.values()) and "估算第一句" in 啟.段位註.text()

    啟.段位鈕們["fast"].click()
    assert 啟.段位() == "fast" and "約 17～21 秒" in 啟.段位註.text()

    引擎 = 慢引擎()
    monkeypatch.setattr(live_topics, "執行", 引擎)
    啟.網址框.setText("https://www.twitch.tv/假頻道")
    啟.開始()
    assert 啟.等待中                                                  # 啟動中：段位鈕停用、標示下次開始生效
    assert not any(b.isEnabled() for b in 啟.段位鈕們.values())
    assert 啟.段位註.text() == "字幕速度：下次開始生效"
    啟.段位鈕們["accurate"].click()                                   # 停用的按鈕點了也沒用
    assert 啟.段位() == "fast"
    引擎.放行.set()
    assert 等(lambda: not 啟.isVisible() and 台.面板.面板們)

    assert 引擎.段位 == "fast"
    assert (subtitle.批次秒數, subtitle.批次句數) == (1, 8)           # 翻譯批次照速度段位
    開頭 = Path(startup_timeline.紀錄.路徑).read_text(encoding="utf-8").split("[+")[0]
    assert "字幕速度段位 = 速度（fast）" in 開頭 and "分段長度設定(秒) = 8" in 開頭
    assert "翻譯批次秒數 = 1" in 開頭 and "翻譯批次句數 = 8" in 開頭
    assert 設定檔.read_text(encoding="utf-8") == 寫前                  # 啟動面板選的不寫回 config.json

    assert 台.執行中() and not 啟.段位可改()                           # 直播中：啟動面板打不開、段位鈕維持停用
    啟.顯示()
    assert not 啟.isVisible() and not any(b.isEnabled() for b in 啟.段位鈕們.values())

    停止並等完(台)
    啟.顯示()                                                        # 結束後：可以再改，並回到記住的預設（平衡）
    assert 啟.isVisible() and all(b.isEnabled() for b in 啟.段位鈕們.values()) and 啟.段位() == "balanced"


def test_從主控台開始_沒經過啟動面板_用config的段位(環境, monkeypatch):
    台, 設定檔 = 環境["台"], 環境["設定檔"]
    內容 = _拿掉段位欄位(設定檔)
    內容["subtitle_speed"] = "accurate"
    設定檔.write_text(json.dumps(內容, ensure_ascii=False), encoding="utf-8")
    引擎 = 慢引擎()
    引擎.放行.set()
    monkeypatch.setattr(live_topics, "執行", 引擎)
    台.直播鈕.setChecked(True)
    台.網址框.setText("https://www.twitch.tv/假頻道")
    台._切換來源()
    台.開始()
    assert 等(lambda: 引擎.段位 is not None)
    assert 引擎.段位 == "accurate" and (subtitle.批次秒數, subtitle.批次句數) == (8, 8)
    停止並等完(台)


def test_設定框_字幕速度說明與儲存_原有欄位保留(環境):
    台, 設定檔 = 環境["台"], 環境["設定檔"]
    原本 = _拿掉段位欄位(設定檔)
    原本["overlay"] = {"click_through": True, "summary_box": {"font_size": 17}}
    原本["hotkey_compact"] = "Ctrl+Shift+M"
    設定檔.write_text(json.dumps(原本, ensure_ascii=False, indent=2), encoding="utf-8")
    assert live_topics.載入設定({})[2] == []                          # 舊設定：沒有 subtitle_speed、有 translate_batch_*，不警告

    台.開設定框()
    頁 = 台.設定框.頁
    assert 頁.欄["subtitle_speed"].currentData() == "balanced"
    說明 = 頁.段位說明.text()
    assert "分段 12 秒" in 說明 and "最多等 1 秒或累積 8 句" in 說明
    assert "估算第一句出現" in 說明 and "估算每小時翻譯費用" in 說明 and "$" in 說明
    頁.欄["subtitle_speed"].setCurrentIndex(頁.欄["subtitle_speed"].findData("accurate"))
    assert "分段 20 秒" in 頁.段位說明.text() and "最多等 8 秒或累積 8 句" in 頁.段位說明.text()

    頁.儲存()
    之後 = json.loads(設定檔.read_text(encoding="utf-8"))
    assert 之後["subtitle_speed"] == "accurate"
    assert {k: 之後[k] for k in 原本} == 原本                          # 原有欄位（含已停用的 translate_batch_*、overlay）一個不少、值不變
    設定, _, 警告們 = live_topics.載入設定({})
    assert 警告們 == [] and 設定["subtitle_speed"] == "accurate"

    assert 頁.段位下次標.isHidden()
    頁.設執行中(True)                                                 # 直播中打開設定框：段位旁標示「下次開始生效」
    assert not 頁.段位下次標.isHidden() and 頁.段位下次標.text() == "下次開始生效"
